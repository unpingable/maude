#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Claude MCP proxy and trusted disposable-command broker.

The ``mcp`` subcommand is launched by Claude Code inside an auth-free,
source-free bubblewrap cleanroom.  In operator mode it exposes exactly one MCP
tool and forwards authenticated requests over a private Unix socket.  The
trusted ``broker`` subcommand runs with a clean environment and no model prompt
or provider credential.  It launches every requested command in a new,
no-network bubblewrap PID/mount namespace.

Grader mode exposes exactly one read-only evidence tool.  It runs wholly inside
the read-only grade-bundle cleanroom and never connects to a command broker.

Both sides append raw, canonical JSONL correlation records to evaluator-private
files.  MCP results contain deterministic JSON text so the provider stream
retains the exact result bytes shown to the model.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import json
import os
import select
import signal
import socket
import stat
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any


SERVER_NAME = "maude-synthetic-operator-cleanroom"
SERVER_TITLE = "Maude Synthetic Operator Cleanroom"
SERVER_VERSION = "2"
SUPPORTED_MCP_PROTOCOL_VERSIONS = ("2025-06-18", "2025-11-25")
POLICY_SCHEMA = "maude.synthetic-operator.command-broker-policy.v1"
TRACE_SCHEMA = "maude.synthetic-operator.mcp-correlation-event.v1"
BROKER_TRACE_SCHEMA = "maude.synthetic-operator.command-broker-event.v1"
MAX_MESSAGE_BYTES = 8 * 1024 * 1024
MAX_OUTPUT_BYTES = 4 * 1024 * 1024
MAX_READ_BYTES = 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 300
MAX_TIMEOUT_SECONDS = 600
FD_CLOSE_LIMIT = 1_048_576
OPERATOR_TOOL = "terminal"
GRADER_TOOL = "evidence"


class BoundaryError(RuntimeError):
    """A request violates the fixed campaign boundary."""


class BrokerFailure(BoundaryError):
    """The trusted command boundary was unavailable or failed closed."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _json_text(value: Any) -> str:
    return _canonical_bytes(value).decode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _append_jsonl(path: Path, value: dict[str, Any]) -> None:
    encoded = _canonical_bytes(value) + b"\n"
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_CLOEXEC,
        0o600,
    )
    try:
        if os.write(descriptor, encoded) != len(encoded):
            raise BoundaryError(f"short write to private trace: {path}")
    finally:
        os.close(descriptor)


def _write_ready(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
        0o600,
    )
    try:
        encoded = _canonical_bytes(value) + b"\n"
        if os.write(descriptor, encoded) != len(encoded):
            raise BoundaryError(f"short write to readiness file: {path}")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)


def _read_token(path: Path) -> str:
    value = path.read_text(encoding="ascii").strip()
    if len(value) < 32 or not value.isascii():
        raise BoundaryError("private broker token is malformed")
    return value


def _read_exact_message(connection: socket.socket) -> dict[str, Any]:
    chunks = bytearray()
    while b"\n" not in chunks:
        chunk = connection.recv(65536)
        if not chunk:
            raise BoundaryError("peer closed before one complete JSON message")
        chunks.extend(chunk)
        if len(chunks) > MAX_MESSAGE_BYTES:
            raise BoundaryError("JSON message exceeds the fixed size limit")
    line, remainder = bytes(chunks).split(b"\n", 1)
    if remainder:
        raise BoundaryError("one connection may contain only one request")
    try:
        value = json.loads(line)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BoundaryError("peer sent malformed JSON") from exc
    if not isinstance(value, dict):
        raise BoundaryError("peer request must be a JSON object")
    return value


def _send_message(connection: socket.socket, value: dict[str, Any]) -> None:
    encoded = _canonical_bytes(value) + b"\n"
    connection.sendall(encoded)


def _bounded_bytes(data: bytes, limit: int) -> tuple[bytes, bool]:
    if len(data) <= limit:
        return data, False
    return data[:limit], True


def _ancestor_dirs(paths: list[Path]) -> list[Path]:
    selected: set[Path] = set()
    for path in paths:
        # Bubblewrap creates the bind destination itself, but every ancestor
        # must already exist.  Do not infer target type from the host view:
        # neutral sandbox destinations generally do not exist on the host.
        current = path.parent
        while current != current.parent and str(current) not in {
            "/usr",
            "/bin",
            "/lib",
            "/lib64",
            "/etc",
            "/dev",
            "/proc",
        }:
            selected.add(current)
            current = current.parent
    return sorted(selected, key=lambda item: (len(item.parts), str(item)))


def _regular_policy_path(value: Any, *, label: str) -> Path:
    if not isinstance(value, str) or not value.startswith("/"):
        raise BoundaryError(f"{label} must be an absolute path")
    path = Path(value)
    if ".." in path.parts:
        raise BoundaryError(f"{label} contains a parent traversal")
    return path


def _load_policy(
    path: Path, *, require_socket_sources: bool = True
) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BoundaryError(f"cannot load command-broker policy: {path}") from exc
    if not isinstance(value, dict) or value.get("schema") != POLICY_SCHEMA:
        raise BoundaryError("command-broker policy schema mismatch")
    allowed_keys = {
        "schema",
        "bwrap",
        "cwd",
        "home",
        "mounts",
        "sockets",
        "environment",
        "cleanroom",
        "forbidden_prefixes",
    }
    extra = sorted(set(value) - allowed_keys)
    if extra:
        raise BoundaryError(f"undeclared command-broker policy keys: {extra}")
    _regular_policy_path(value.get("bwrap"), label="bwrap")
    _regular_policy_path(value.get("cwd"), label="cwd")
    _regular_policy_path(value.get("home"), label="home")
    if not isinstance(value.get("mounts"), list):
        raise BoundaryError("mounts must be a list")
    if not isinstance(value.get("sockets"), list):
        raise BoundaryError("sockets must be a list")
    if not isinstance(value.get("environment"), dict):
        raise BoundaryError("environment must be an object")
    if not isinstance(value.get("cleanroom"), dict):
        raise BoundaryError("cleanroom must be an object")
    if not isinstance(value.get("forbidden_prefixes"), list):
        raise BoundaryError("forbidden_prefixes must be a list")
    seen_targets: set[str] = set()
    for mount in value["mounts"]:
        if (
            not isinstance(mount, dict)
            or set(mount) != {"source", "target", "mode"}
            or mount.get("mode") not in {"ro", "rw"}
        ):
            raise BoundaryError("each mount needs source, target, and ro/rw mode")
        _regular_policy_path(mount["source"], label="mount source")
        _regular_policy_path(mount["target"], label="mount target")
        if mount["target"] in seen_targets:
            raise BoundaryError("duplicate mount/socket target in policy")
        seen_targets.add(mount["target"])
        try:
            mode = os.lstat(mount["source"]).st_mode
        except OSError as exc:
            raise BoundaryError(
                f"mount source is unavailable: {mount['source']}"
            ) from exc
        if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise BoundaryError(
                "mount source must be one regular file or directory"
            )
    for mounted_socket in value["sockets"]:
        if (
            not isinstance(mounted_socket, dict)
            or set(mounted_socket) != {"source", "target"}
        ):
            raise BoundaryError("each socket needs exact source and target")
        _regular_policy_path(mounted_socket["source"], label="socket source")
        _regular_policy_path(mounted_socket["target"], label="socket target")
        if mounted_socket["target"] in seen_targets:
            raise BoundaryError("duplicate mount/socket target in policy")
        seen_targets.add(mounted_socket["target"])
        try:
            socket_mode = os.lstat(mounted_socket["source"]).st_mode
        except FileNotFoundError:
            if require_socket_sources:
                raise BoundaryError(
                    "declared socket source is unavailable"
                ) from None
        except OSError as exc:
            raise BoundaryError("cannot inspect declared socket source") from exc
        else:
            if not stat.S_ISSOCK(socket_mode):
                raise BoundaryError(
                    "declared socket source is not a Unix socket"
                )
    for key, item in value["environment"].items():
        if (
            not isinstance(key, str)
            or not key
            or "\x00" in key
            or not isinstance(item, str)
            or "\x00" in item
        ):
            raise BoundaryError("environment contains a malformed entry")
    for key in ("etc", "empty", "masked"):
        _regular_policy_path(value["cleanroom"].get(key), label=f"cleanroom {key}")
    if value["environment"].get("HOME") != value["home"]:
        raise BoundaryError("policy HOME and home mount differ")
    cwd = Path(value["cwd"])
    if not cwd.is_dir():
        raise BoundaryError("policy cwd is unavailable or not a directory")
    if not any(
        cwd == Path(mount["target"])
        or Path(mount["target"]) in cwd.parents
        for mount in value["mounts"]
        if Path(mount["source"]).is_dir()
    ):
        raise BoundaryError("policy cwd is outside every declared mount")
    serialized = _json_text(
        {key: item for key, item in value.items() if key != "forbidden_prefixes"}
    )
    for prefix in value["forbidden_prefixes"]:
        if not isinstance(prefix, str) or not prefix.startswith("/"):
            raise BoundaryError("forbidden prefixes must be absolute paths")
        if prefix in serialized:
            raise BoundaryError("policy contains a forbidden path prefix")
    return value


def _command_bwrap_argv(
    policy: dict[str, Any],
    command: str,
    *,
    info_fd: int,
    block_fd: int,
) -> list[str]:
    cleanroom = policy["cleanroom"]
    mounts = policy["mounts"]
    mounted_sockets = policy["sockets"]
    destinations = [
        Path(str(item["target"])) for item in mounts + mounted_sockets
    ]
    destinations.extend(
        [
            Path(str(policy["cwd"])),
            Path(str(policy["home"])),
            Path("/opt"),
        ]
    )
    argv = [
        str(policy["bwrap"]),
        "--die-with-parent",
        "--unshare-pid",
        "--unshare-net",
        "--unshare-ipc",
        "--unshare-uts",
        "--unshare-cgroup-try",
        "--clearenv",
        "--info-fd",
        str(info_fd),
        "--block-fd",
        str(block_fd),
        "--ro-bind",
        "/usr",
        "/usr",
        "--ro-bind",
        "/bin",
        "/bin",
        "--ro-bind",
        "/lib",
        "/lib",
        "--ro-bind",
        "/lib64",
        "/lib64",
        "--ro-bind",
        str(cleanroom["etc"]),
        "/etc",
        "--ro-bind",
        "/etc/ssl/certs",
        "/etc/ssl/certs",
        "--ro-bind",
        "/etc/ssl/openssl.cnf",
        "/etc/ssl/openssl.cnf",
        "--ro-bind",
        "/etc/ld.so.cache",
        "/etc/ld.so.cache",
        "--ro-bind",
        str(cleanroom["masked"]),
        "/usr/bin/maude",
        "--ro-bind",
        str(cleanroom["masked"]),
        "/bin/maude",
        "--ro-bind",
        str(cleanroom["empty"]),
        "/usr/share/maude",
        "--ro-bind",
        str(cleanroom["empty"]),
        "/usr/share/doc/maude",
        "--ro-bind",
        str(cleanroom["masked"]),
        "/usr/share/man/man1/maude.1.gz",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
        "--dir",
        "/run",
        "--dir",
        "/home",
        "--dir",
        "/opt",
    ]
    for directory in _ancestor_dirs(destinations):
        argv.extend(["--dir", str(directory)])
    for mount in mounts:
        argv.extend(
            [
                "--ro-bind" if mount["mode"] == "ro" else "--bind",
                str(mount["source"]),
                str(mount["target"]),
            ]
        )
    for mounted_socket in mounted_sockets:
        argv.extend(
            [
                "--ro-bind",
                str(mounted_socket["source"]),
                str(mounted_socket["target"]),
            ]
        )
    for key, value in sorted(policy["environment"].items()):
        argv.extend(["--setenv", key, value])
    forbidden = base64.b64encode(
        _canonical_bytes(policy["forbidden_prefixes"])
    ).decode("ascii")
    wrapper = (
        "import base64,hashlib,json,os,sys;"
        "forbidden=json.loads(base64.b64decode(sys.argv[2]));"
        "visible=[p for p in forbidden if os.path.lexists(p)];"
        "fds=[];"
        "\nfor name in sorted(os.listdir('/proc/self/fd'),key=int):"
        "\n try: target=os.readlink('/proc/self/fd/'+name)"
        "\n except OSError: continue"
        "\n fds.append({'fd':int(name),'target':target})"
        "\nmountinfo=open('/proc/self/mountinfo','rb').read();"
        "\nproof={'schema':'maude.synthetic-operator.command-preexec-proof.v1',"
        "'pid':os.getpid(),'forbidden_paths_visible':visible,"
        "'provider_auth_visible':os.path.lexists('/run/provider-auth'),"
        "'namespaces':{n:os.readlink('/proc/self/ns/'+n) "
        "for n in ('mnt','net','pid')},'file_descriptors':fds,"
        "'mountinfo_sha256':hashlib.sha256(mountinfo).hexdigest(),"
        "'environment_names':sorted(os.environ),'pwd':os.environ.get('PWD')};"
        "\nsys.stdout.write('__MAUDE_BOUNDARY_PROOF__'+"
        "json.dumps(proof,separators=(',',':'),sort_keys=True)+'\\n');"
        "sys.stdout.flush();"
        "\nif os.read(0,1)!=b'1': raise SystemExit(126);"
        "\nnull=os.open('/dev/null',os.O_RDWR);os.dup2(null,0);"
        f"os.closerange(3,{FD_CLOSE_LIMIT});"
        "\nos.execve('/bin/bash',['/bin/bash','-lc',sys.argv[1]],"
        "dict(os.environ))"
    )
    try:
        compile(wrapper, "<trusted-command-wrapper>", "exec")
    except SyntaxError as exc:
        raise BoundaryError(
            f"internal trusted command wrapper is invalid: {exc}"
        ) from exc
    argv.extend(
        [
            "--chdir",
            str(policy["cwd"]),
            "/usr/bin/python3",
            "-I",
            "-B",
            "-c",
            wrapper,
            command,
            forbidden,
        ]
    )
    return argv


def _read_info_fd(descriptor: int, timeout: float = 10.0) -> dict[str, Any]:
    chunks = bytearray()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        readable, _, _ = select.select([descriptor], [], [], 0.1)
        if not readable:
            continue
        chunk = os.read(descriptor, 65536)
        if not chunk:
            break
        chunks.extend(chunk)
        if len(chunks) > 1024 * 1024:
            raise BoundaryError("bubblewrap info exceeded fixed limit")
        try:
            candidate = json.loads(chunks)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(candidate, dict):
            return candidate
    if not chunks:
        raise BoundaryError("bubblewrap produced no namespace info")
    try:
        value = json.loads(chunks)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BoundaryError("bubblewrap info was malformed") from exc
    if not isinstance(value, dict):
        raise BoundaryError("bubblewrap info was not an object")
    return value


def _namespace_proof(
    child_pid: int,
    policy: dict[str, Any],
    inside: dict[str, Any],
) -> dict[str, Any]:
    proc = Path("/proc") / str(child_pid)
    namespaces: dict[str, dict[str, str]] = {}
    for name in ("mnt", "net", "pid"):
        child = os.readlink(proc / "ns" / name)
        broker = os.readlink(Path("/proc/self/ns") / name)
        namespaces[name] = {
            "broker": broker,
            "sandbox": child,
            "distinct": child != broker,
        }
    if not all(item["distinct"] for item in namespaces.values()):
        raise BoundaryError("per-command namespace separation was not established")
    forbidden_visible: list[str] = []
    for prefix in policy["forbidden_prefixes"]:
        candidate = proc / "root" / prefix.lstrip("/")
        try:
            os.lstat(candidate)
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise BoundaryError(
                f"cannot prove forbidden-path absence: {prefix}: {exc}"
            ) from exc
        forbidden_visible.append(prefix)
    if forbidden_visible:
        raise BoundaryError(
            f"forbidden paths visible in command sandbox: {forbidden_visible}"
        )
    auth_mount = proc / "root" / "run" / "provider-auth"
    try:
        os.lstat(auth_mount)
    except FileNotFoundError:
        auth_visible = False
    except OSError as exc:
        raise BoundaryError("cannot prove provider-auth mount absence") from exc
    else:
        auth_visible = True
    if auth_visible:
        raise BoundaryError("provider-auth mount is visible in command sandbox")
    expected_inside_namespaces = {
        name: value["sandbox"] for name, value in namespaces.items()
    }
    if (
        inside.get("schema")
        != "maude.synthetic-operator.command-preexec-proof.v1"
        or not isinstance(inside.get("pid"), int)
        or int(inside["pid"]) < 1
        or inside.get("forbidden_paths_visible") != []
        or inside.get("provider_auth_visible") is not False
        or inside.get("namespaces") != expected_inside_namespaces
    ):
        raise BoundaryError(
            "trusted in-sandbox pre-exec proof does not match the host proof: "
            f"schema={inside.get('schema')!r} pid={inside.get('pid')!r} "
            f"forbidden={inside.get('forbidden_paths_visible')!r} "
            f"auth={inside.get('provider_auth_visible')!r} "
            f"inside_namespaces={inside.get('namespaces')!r} "
            f"host_namespaces={expected_inside_namespaces!r}"
        )
    descriptors: list[dict[str, Any]] = []
    try:
        fd_paths = sorted(
            (proc / "fd").iterdir(), key=lambda path: int(path.name)
        )
    except (FileNotFoundError, PermissionError, OSError) as exc:
        raise BoundaryError("cannot inspect pre-exec command descriptors") from exc
    for descriptor in fd_paths:
        try:
            target = os.readlink(descriptor)
        except FileNotFoundError:
            continue
        except (PermissionError, OSError) as exc:
            raise BoundaryError(
                f"cannot inspect pre-exec descriptor {descriptor}"
            ) from exc
        descriptors.append({"fd": int(descriptor.name), "target": target})
        if any(prefix in target for prefix in policy["forbidden_prefixes"]):
            raise BoundaryError(
                "pre-exec command descriptor resolves to a forbidden path"
            )
        if "/provider-auth" in target:
            raise BoundaryError(
                "pre-exec command descriptor resolves to provider auth"
            )
    try:
        mountinfo = (proc / "mountinfo").read_bytes()
    except (FileNotFoundError, PermissionError, OSError) as exc:
        raise BoundaryError("cannot inspect command mount table") from exc
    mountinfo_sha256 = hashlib.sha256(mountinfo).hexdigest()
    if inside.get("mountinfo_sha256") != mountinfo_sha256:
        raise BoundaryError("inside/host command mount-table proofs differ")
    expected_environment_names = sorted(
        set(policy["environment"]) | {"PWD"}
    )
    if (
        inside.get("environment_names") != expected_environment_names
        or inside.get("pwd") != policy["cwd"]
    ):
        raise BoundaryError(
            "command environment names differ from policy: "
            f"observed={inside.get('environment_names')!r} "
            f"expected={expected_environment_names!r} "
            f"pwd={inside.get('pwd')!r} expected_pwd={policy['cwd']!r}"
        )
    inside_descriptors = inside.get("file_descriptors")
    if not isinstance(inside_descriptors, list):
        raise BoundaryError("inside pre-exec descriptor proof is malformed")
    for descriptor in inside_descriptors:
        if not isinstance(descriptor, dict):
            raise BoundaryError("inside pre-exec descriptor record is malformed")
        target = descriptor.get("target")
        if not isinstance(target, str):
            raise BoundaryError("inside pre-exec descriptor target is malformed")
        if any(prefix in target for prefix in policy["forbidden_prefixes"]):
            raise BoundaryError(
                "inside pre-exec descriptor resolves to a forbidden path"
            )
        if "/provider-auth" in target:
            raise BoundaryError(
                "inside pre-exec descriptor resolves to provider auth"
            )
    return {
        "sandbox_pid": child_pid,
        "namespaces": namespaces,
        "forbidden_paths_visible": [],
        "provider_auth_mount_visible": False,
        "pre_exec_file_descriptors": descriptors,
        "inside_pre_exec_file_descriptors": inside.get("file_descriptors"),
        "inside_environment_names": inside.get("environment_names"),
        "pre_exec_forbidden_descriptor_targets": [],
        "mountinfo_sha256": mountinfo_sha256,
        "command_fd_contract": (
            "close_fds=True; only bubblewrap info/block setup FDs passed; "
            "trusted wrapper emits an inside-view proof after sandbox setup "
            "and waits for a broker acknowledgement; broker combines it with "
            f"the host view; os.closerange(3,{FD_CLOSE_LIMIT}) immediately "
            "before shell exec; stdin is replaced with /dev/null"
        ),
        "external_network_namespace": "unshared",
    }


def _run_disposable_command(
    policy: dict[str, Any], command: str, timeout: int
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    info_read, info_write = os.pipe2(os.O_CLOEXEC)
    block_read, block_write = os.pipe2(os.O_CLOEXEC)
    argv = _command_bwrap_argv(
        policy,
        command,
        info_fd=info_write,
        block_fd=block_read,
    )
    process: subprocess.Popen[bytes] | None = None
    proof: dict[str, Any] = {}
    try:
        process = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            close_fds=True,
            pass_fds=(info_write, block_read),
            start_new_session=True,
        )
        os.close(info_write)
        info_write = -1
        os.close(block_read)
        block_read = -1
        info = _read_info_fd(info_read)
        child_pid = info.get("child-pid")
        if not isinstance(child_pid, int) or child_pid <= 0:
            raise BoundaryError("bubblewrap did not report a valid child-pid")
        # Bubblewrap's block gate fires before final mount/pivot setup. Release
        # it; the trusted wrapper then emits an inside-view proof and waits on
        # stdin.  No requested command can execute until the broker validates
        # both inside and host views and acknowledges that proof.
        os.write(block_write, b"1")
        os.close(block_write)
        block_write = -1
        if process.stdout is None or process.stdin is None:
            raise BoundaryError("command proof pipes were not created")
        readable, _, _ = select.select([process.stdout], [], [], 10)
        if not readable:
            raise BoundaryError("trusted command wrapper emitted no proof")
        proof_line = process.stdout.readline(MAX_MESSAGE_BYTES + 1)
        prefix = b"__MAUDE_BOUNDARY_PROOF__"
        if len(proof_line) > MAX_MESSAGE_BYTES or not proof_line.startswith(
            prefix
        ):
            stderr_preview = b""
            if process.stderr is not None:
                stderr_ready, _, _ = select.select(
                    [process.stderr], [], [], 0.1
                )
                if stderr_ready:
                    stderr_preview = os.read(process.stderr.fileno(), 65536)
            raise BoundaryError(
                "trusted command wrapper emitted a malformed proof: "
                f"stdout_bytes={len(proof_line)} "
                f"stdout_sha256={hashlib.sha256(proof_line).hexdigest()} "
                f"stderr_bytes={len(stderr_preview)} "
                f"stderr_sha256={hashlib.sha256(stderr_preview).hexdigest()}"
            )
        try:
            inside_proof = json.loads(proof_line[len(prefix) :])
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BoundaryError(
                "trusted command wrapper proof is not valid JSON"
            ) from exc
        if not isinstance(inside_proof, dict):
            raise BoundaryError("trusted command wrapper proof is not an object")
        proof = _namespace_proof(child_pid, policy, inside_proof)
        proof["bubblewrap_info"] = info
        process.stdin.write(b"1")
        process.stdin.flush()
        process.stdin.close()
        process.stdin = None
        timed_out = False
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
            try:
                stdout, stderr = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                stdout, stderr = process.communicate(timeout=5)
        stdout, stdout_truncated = _bounded_bytes(stdout, MAX_OUTPUT_BYTES)
        stderr, stderr_truncated = _bounded_bytes(stderr, MAX_OUTPUT_BYTES)
        result = {
            "command": command,
            "cwd": str(policy["cwd"]),
            "returncode": process.returncode,
            "timed_out": timed_out,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "stdout_truncated": stdout_truncated,
            "stderr_truncated": stderr_truncated,
        }
        return result, proof, argv
    finally:
        for descriptor in (info_read, info_write, block_read, block_write):
            if descriptor >= 0:
                with contextlib.suppress(OSError):
                    os.close(descriptor)
        if process is not None and process.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=5)


def _broker(args: argparse.Namespace) -> int:
    policy = _load_policy(args.policy)
    token = _read_token(args.token_file)
    args.socket.parent.mkdir(parents=True, exist_ok=True)
    if args.socket.exists():
        raise BoundaryError(f"refusing to replace broker socket: {args.socket}")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(args.socket))
    os.chmod(args.socket, 0o600)
    server.listen(8)
    stop_requested = False

    def request_stop(_signum: int, _frame: Any) -> None:
        nonlocal stop_requested
        stop_requested = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    _write_ready(
        args.ready,
        {
            "schema": "maude.synthetic-operator.command-broker-ready.v1",
            "pid": os.getpid(),
            "socket": str(args.socket),
            "policy_sha256": hashlib.sha256(args.policy.read_bytes()).hexdigest(),
            "token_sha256": hashlib.sha256(token.encode("ascii")).hexdigest(),
        },
    )
    ordinal = 0
    try:
        while not stop_requested:
            readable, _, _ = select.select([server], [], [], 0.25)
            if not readable:
                continue
            connection, _ = server.accept()
            with connection:
                ordinal += 1
                started = time.monotonic()
                request: dict[str, Any] | None = None
                try:
                    request = _read_exact_message(connection)
                    if request.get("token") != token:
                        raise BoundaryError("broker authentication failed")
                    if set(request) != {
                        "schema",
                        "token",
                        "request_id",
                        "command",
                        "timeout_seconds",
                    }:
                        raise BoundaryError("broker request fields are not exact")
                    if request.get("schema") != (
                        "maude.synthetic-operator.command-request.v1"
                    ):
                        raise BoundaryError("broker request schema mismatch")
                    request_id = request.get("request_id")
                    command = request.get("command")
                    timeout = request.get("timeout_seconds")
                    if not isinstance(request_id, str) or not request_id:
                        raise BoundaryError("broker request_id is malformed")
                    if not isinstance(command, str) or not command.strip():
                        raise BoundaryError("command must be a non-empty string")
                    if (
                        not isinstance(timeout, int)
                        or isinstance(timeout, bool)
                        or timeout < 1
                        or timeout > MAX_TIMEOUT_SECONDS
                    ):
                        raise BoundaryError("timeout_seconds is out of range")
                    result, proof, bwrap_argv = _run_disposable_command(
                        policy, command, timeout
                    )
                    response = {
                        "schema": "maude.synthetic-operator.command-result.v1",
                        "request_id": request_id,
                        "ok": True,
                        "result": result,
                    }
                    record = {
                        "schema": BROKER_TRACE_SCHEMA,
                        "ordinal": ordinal,
                        "request_id": request_id,
                        "request_sha256": _sha256(
                            {
                                key: value
                                for key, value in request.items()
                                if key != "token"
                            }
                        ),
                        "command": command,
                        "timeout_seconds": timeout,
                        "bwrap_argv": bwrap_argv,
                        "namespace_and_mount_proof": proof,
                        "result": result,
                        "result_sha256": _sha256(result),
                        "elapsed_seconds": round(
                            time.monotonic() - started, 6
                        ),
                    }
                except BaseException as exc:
                    request_id = (
                        request.get("request_id")
                        if isinstance(request, dict)
                        and isinstance(request.get("request_id"), str)
                        else None
                    )
                    response = {
                        "schema": "maude.synthetic-operator.command-result.v1",
                        "request_id": request_id,
                        "ok": False,
                        "error": {
                            "type": type(exc).__name__,
                            "message": str(exc),
                        },
                    }
                    record = {
                        "schema": BROKER_TRACE_SCHEMA,
                        "ordinal": ordinal,
                        "request_id": request_id,
                        "failed_closed": True,
                        "error": response["error"],
                        "elapsed_seconds": round(
                            time.monotonic() - started, 6
                        ),
                    }
                _append_jsonl(args.trace, record)
                _send_message(connection, response)
    finally:
        server.close()
        with contextlib.suppress(FileNotFoundError):
            args.socket.unlink()
    return 0


def _call_broker(
    socket_path: Path,
    token: str,
    *,
    request_id: str,
    command: str,
    timeout: int,
) -> dict[str, Any]:
    request = {
        "schema": "maude.synthetic-operator.command-request.v1",
        "token": token,
        "request_id": request_id,
        "command": command,
        "timeout_seconds": timeout,
    }
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.settimeout(timeout + 30)
    try:
        connection.connect(str(socket_path))
        _send_message(connection, request)
        response = _read_exact_message(connection)
    finally:
        connection.close()
    if response.get("request_id") != request_id:
        raise BrokerFailure("command broker response correlation mismatch")
    if response.get("ok") is not True:
        error = response.get("error")
        raise BrokerFailure(
            "command broker failed closed: "
            + _json_text(error if isinstance(error, dict) else {})
        )
    result = response.get("result")
    if not isinstance(result, dict):
        raise BrokerFailure("command broker returned no result object")
    return result


def _reject_symlink_components(root: Path, path: Path) -> None:
    relative = path.relative_to(root)
    current = root
    for part in relative.parts:
        current = current / part
        try:
            mode = os.lstat(current).st_mode
        except OSError as exc:
            raise BoundaryError(f"cannot inspect evidence path: {path}") from exc
        if stat.S_ISLNK(mode):
            raise BoundaryError("symlinks are forbidden in evidence access")


def _resolve_evidence_path(value: Any, root: Path) -> Path:
    if not isinstance(value, str) or not value:
        raise BoundaryError("path must be a non-empty string")
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root / candidate
    if ".." in candidate.parts:
        raise BoundaryError("parent traversal is forbidden")
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise BoundaryError("path is outside the frozen evidence bundle") from exc
    # Inspect the exact lexically requested path before resolving it.  Checking
    # only the resolved target would miss an in-bundle symlink component that
    # happens to point to another in-bundle object.
    _reject_symlink_components(root, candidate)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise BoundaryError("path is outside the frozen evidence bundle") from exc
    return resolved


def _read_evidence(arguments: dict[str, Any], root: Path) -> dict[str, Any]:
    operation = arguments.get("operation")
    expected_keys = (
        {"operation", "path", "limit"}
        if operation == "list"
        else {"operation", "path", "offset", "limit"}
        if operation == "read"
        else {"operation", "path"}
    )
    extra = sorted(set(arguments) - expected_keys)
    if extra:
        raise BoundaryError(f"undeclared evidence argument keys: {extra}")
    path = _resolve_evidence_path(arguments.get("path", "."), root)
    if operation == "list":
        if not path.is_dir():
            raise BoundaryError("list target is not a directory")
        maximum = arguments.get("limit", 1000)
        if (
            not isinstance(maximum, int)
            or isinstance(maximum, bool)
            or maximum < 1
            or maximum > 10000
        ):
            raise BoundaryError("list limit is out of range")
        entries: list[dict[str, str]] = []
        for child in sorted(path.iterdir(), key=lambda item: item.name):
            if len(entries) >= maximum:
                break
            mode = os.lstat(child).st_mode
            kind = (
                "directory"
                if stat.S_ISDIR(mode)
                else "file"
                if stat.S_ISREG(mode)
                else "forbidden"
            )
            entries.append(
                {"name": child.name, "path": str(child), "kind": kind}
            )
        return {
            "operation": "list",
            "path": str(path),
            "entries": entries,
            "truncated": len(list(path.iterdir())) > len(entries),
        }
    if operation == "read":
        mode = os.lstat(path).st_mode
        if not stat.S_ISREG(mode):
            raise BoundaryError("read target is not a regular file")
        offset = arguments.get("offset", 0)
        limit = arguments.get("limit", MAX_READ_BYTES)
        if (
            not isinstance(offset, int)
            or isinstance(offset, bool)
            or offset < 0
        ):
            raise BoundaryError("offset is out of range")
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or limit < 1
            or limit > MAX_READ_BYTES
        ):
            raise BoundaryError("read limit is out of range")
        with path.open("rb") as handle:
            handle.seek(offset)
            data = handle.read(limit + 1)
        selected, truncated = _bounded_bytes(data, limit)
        return {
            "operation": "read",
            "path": str(path),
            "offset": offset,
            "bytes_returned": len(selected),
            "truncated": truncated,
            "content": selected.decode("utf-8", errors="replace"),
        }
    raise BoundaryError("operation must be read or list")


def _tool_definitions(mode: str) -> list[dict[str, Any]]:
    if mode == "operator":
        return [
            {
                "name": OPERATOR_TOOL,
                "description": (
                    "Run one shell command in the synthetic operator "
                    "cleanroom. Each call gets a new no-network PID/mount "
                    "namespace with only the declared task paths and sockets."
                ),
                "inputSchema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["command"],
                    "properties": {
                        "command": {"type": "string", "minLength": 1},
                        "timeout_seconds": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": MAX_TIMEOUT_SECONDS,
                            "default": DEFAULT_TIMEOUT_SECONDS,
                        },
                    },
                },
            }
        ]
    return [
        {
            "name": GRADER_TOOL,
            "description": (
                "Read or list only the frozen grade evidence bundle. This "
                "tool cannot execute commands or mutate files."
            ),
            "inputSchema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["operation", "path"],
                "properties": {
                    "operation": {"enum": ["read", "list"]},
                    "path": {"type": "string", "minLength": 1},
                    "offset": {"type": "integer", "minimum": 0, "default": 0},
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_READ_BYTES,
                        "default": MAX_READ_BYTES,
                    },
                },
            },
        }
    ]


def _mcp(args: argparse.Namespace) -> int:
    tools = _tool_definitions(args.mode)
    root: Path | None = None
    token: str | None = None
    if args.mode == "operator":
        if args.broker_socket is None or args.token_file is None:
            raise BoundaryError("operator proxy needs broker socket and token")
        token = _read_token(args.token_file)
    else:
        if args.root is None:
            raise BoundaryError("grader proxy needs one evidence root")
        root = args.root.resolve(strict=True)
        if not root.is_dir():
            raise BoundaryError("grader evidence root is not a directory")
    ordinal = 0
    message_ordinal = 0
    initialize_message_ordinal: int | None = None
    negotiated_protocol: str | None = None
    ready_written = False
    protocol_state = "awaiting-initialize"
    for raw_line in sys.stdin.buffer:
        message_ordinal += 1
        if len(raw_line) > MAX_MESSAGE_BYTES:
            raise BoundaryError("MCP message exceeds the fixed size limit")
        request: dict[str, Any] | None = None
        method: Any = None
        requested_protocol: str | None = None
        deferred_ready: dict[str, Any] | None = None
        try:
            request = json.loads(raw_line)
            if not isinstance(request, dict):
                raise BoundaryError("MCP message must be a JSON object")
            method = request.get("method")
            request_id = request.get("id")
            if request_id is None:
                if method == "notifications/initialized":
                    if protocol_state != "awaiting-initialized-notification":
                        raise BoundaryError(
                            "initialized notification arrived out of order"
                        )
                    if negotiated_protocol is None:
                        raise BoundaryError(
                            "initialized notification has no negotiated protocol"
                        )
                    protocol_state = "awaiting-tools-list"
                    _append_jsonl(
                        args.trace,
                        {
                            "schema": TRACE_SCHEMA,
                            "message_ordinal": message_ordinal,
                            "protocol_event": "notifications/initialized",
                            "protocol_version": negotiated_protocol,
                        },
                    )
                    continue
                if method == "notifications/cancelled":
                    continue
                raise BoundaryError("undeclared MCP notification")
            if method == "initialize":
                if protocol_state != "awaiting-initialize":
                    raise BoundaryError("initialize arrived out of order")
                initialize_message_ordinal = message_ordinal
                params = request.get("params")
                protocol = (
                    params.get("protocolVersion")
                    if isinstance(params, dict)
                    and isinstance(params.get("protocolVersion"), str)
                    else None
                )
                requested_protocol = protocol
                if protocol not in SUPPORTED_MCP_PROTOCOL_VERSIONS:
                    raise BoundaryError(
                        "unsupported MCP protocol version: "
                        f"{protocol!r}; expected one of "
                        f"{SUPPORTED_MCP_PROTOCOL_VERSIONS!r}"
                    )
                negotiated_protocol = protocol
                result: dict[str, Any] = {
                    "protocolVersion": negotiated_protocol,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {
                        "name": SERVER_NAME,
                        "title": SERVER_TITLE,
                        "version": SERVER_VERSION,
                    },
                }
                protocol_state = "awaiting-initialized-notification"
            elif method == "ping":
                if protocol_state == "awaiting-initialize":
                    raise BoundaryError("ping arrived before initialize")
                result = {}
            elif method == "tools/list":
                if protocol_state != "awaiting-tools-list":
                    raise BoundaryError("tools/list arrived out of order")
                if negotiated_protocol is None:
                    raise BoundaryError("tools/list has no negotiated protocol")
                result = {"tools": tools}
                if not ready_written:
                    deferred_ready = {
                        "schema": (
                            "maude.synthetic-operator.claude-mcp-ready.v1"
                        ),
                        "pid": os.getpid(),
                        "mode": args.mode,
                        "tools": [tool["name"] for tool in tools],
                        "protocol_version_requested": negotiated_protocol,
                        "protocol_version_negotiated": negotiated_protocol,
                        "initialize_message_ordinal": (
                            initialize_message_ordinal
                        ),
                        "tools_list_message_ordinal": message_ordinal,
                    }
                protocol_state = "ready"
            elif method == "tools/call":
                if protocol_state != "ready" or not ready_written:
                    raise BoundaryError("tools/call arrived before roster readiness")
                ordinal += 1
                params = request.get("params")
                if not isinstance(params, dict):
                    raise BoundaryError("tools/call params must be an object")
                name = params.get("name")
                arguments = params.get("arguments")
                if not isinstance(arguments, dict):
                    raise BoundaryError("tool arguments must be an object")
                started = time.monotonic()
                call_id = f"{ordinal:06d}-{uuid.uuid4().hex}"
                tool_error = False
                try:
                    if args.mode == "operator":
                        if name != OPERATOR_TOOL:
                            raise BoundaryError(
                                "tool is outside operator roster"
                            )
                        extra = sorted(
                            set(arguments) - {"command", "timeout_seconds"}
                        )
                        if extra:
                            raise BoundaryError(
                                f"undeclared terminal argument keys: {extra}"
                            )
                        command = arguments.get("command")
                        timeout = arguments.get(
                            "timeout_seconds", DEFAULT_TIMEOUT_SECONDS
                        )
                        if not isinstance(command, str) or not command.strip():
                            raise BoundaryError("command must be non-empty")
                        if (
                            not isinstance(timeout, int)
                            or isinstance(timeout, bool)
                            or timeout < 1
                            or timeout > MAX_TIMEOUT_SECONDS
                        ):
                            raise BoundaryError(
                                "timeout_seconds is out of range"
                            )
                        assert token is not None
                        assert args.broker_socket is not None
                        value = _call_broker(
                            args.broker_socket,
                            token,
                            request_id=call_id,
                            command=command,
                            timeout=timeout,
                        )
                    else:
                        if name != GRADER_TOOL:
                            raise BoundaryError(
                                "tool is outside grader roster"
                            )
                        assert root is not None
                        value = _read_evidence(arguments, root)
                except BrokerFailure:
                    raise
                except BoundaryError as exc:
                    tool_error = True
                    value = {
                        "error": {
                            "type": type(exc).__name__,
                            "message": str(exc),
                        }
                    }
                text = _json_text(value)
                result = {
                    "content": [{"type": "text", "text": text}],
                    "isError": tool_error,
                }
                _append_jsonl(
                    args.trace,
                    {
                        "schema": TRACE_SCHEMA,
                        "ordinal": ordinal,
                        "mcp_request_id": request_id,
                        "correlation_id": call_id,
                        "mode": args.mode,
                        "tool": name,
                        "arguments": arguments,
                        "arguments_sha256": _sha256(arguments),
                        "result_text": text,
                        "result_text_sha256": hashlib.sha256(
                            text.encode("utf-8")
                        ).hexdigest(),
                        "mcp_result_sha256": _sha256(result),
                        "is_error": tool_error,
                        "elapsed_seconds": round(
                            time.monotonic() - started, 6
                        ),
                    },
                )
            else:
                raise BoundaryError("method is outside the minimal MCP surface")
            response = {"jsonrpc": "2.0", "id": request_id, "result": result}
        except (
            BoundaryError,
            json.JSONDecodeError,
            UnicodeDecodeError,
            OSError,
        ) as exc:
            request_id = (
                request.get("id") if isinstance(request, dict) else None
            )
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32602, "message": str(exc)},
            }
            if (
                isinstance(request, dict)
                and request.get("method") == "tools/call"
            ):
                _append_jsonl(
                    args.trace,
                    {
                        "schema": TRACE_SCHEMA,
                        "ordinal": ordinal,
                        "mcp_request_id": request_id,
                        "mode": args.mode,
                        "failed_closed": True,
                        "error": {
                            "type": type(exc).__name__,
                            "message": str(exc),
                        },
                    },
                )
        sys.stdout.write(_json_text(response) + "\n")
        sys.stdout.flush()
        if method == "initialize":
            _append_jsonl(
                args.trace,
                {
                    "schema": TRACE_SCHEMA,
                    "message_ordinal": message_ordinal,
                    "protocol_event": "initialize-response-flushed",
                    "protocol_version_requested": requested_protocol,
                    "protocol_version_negotiated": negotiated_protocol,
                    "initialize_accepted": "result" in response,
                    "response_sha256": _sha256(response),
                },
            )
        if deferred_ready is not None:
            deferred_ready["tools_list_response_sha256"] = _sha256(response)
            _append_jsonl(
                args.trace,
                {
                    "schema": TRACE_SCHEMA,
                    "message_ordinal": message_ordinal,
                    "protocol_event": "tools-list-response-flushed",
                    "protocol_version": negotiated_protocol,
                    "tools": deferred_ready["tools"],
                    "response_sha256": deferred_ready[
                        "tools_list_response_sha256"
                    ],
                },
            )
            _write_ready(args.ready, deferred_ready)
            ready_written = True
    return 0


def _self_test(args: argparse.Namespace) -> int:
    tools = _tool_definitions(args.mode)
    print(
        _json_text(
            {
                "server": SERVER_NAME,
                "version": SERVER_VERSION,
                "mode": args.mode,
                "tools": [tool["name"] for tool in tools],
                "supported_mcp_protocol_versions": list(
                    SUPPORTED_MCP_PROTOCOL_VERSIONS
                ),
                "command_execution": args.mode == "operator",
                "grader_read_only": args.mode == "grader",
            }
        )
    )
    return 0


def _validate_policy(args: argparse.Namespace) -> int:
    policy = _load_policy(args.policy, require_socket_sources=False)
    print(
        _json_text(
            {
                "schema": POLICY_SCHEMA,
                "policy_sha256": hashlib.sha256(
                    args.policy.read_bytes()
                ).hexdigest(),
                "cwd": policy["cwd"],
                "mount_count": len(policy["mounts"]),
                "socket_count": len(policy["sockets"]),
                "external_network": False,
                "per_command_pid_namespace": True,
                "provider_auth_received": False,
                "semantic_prompt_received": False,
            }
        )
    )
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    mcp = subparsers.add_parser("mcp")
    mcp.add_argument("--mode", choices=("operator", "grader"), required=True)
    mcp.add_argument("--trace", type=Path, required=True)
    mcp.add_argument("--ready", type=Path, required=True)
    mcp.add_argument("--broker-socket", type=Path)
    mcp.add_argument("--token-file", type=Path)
    mcp.add_argument("--root", type=Path)

    broker = subparsers.add_parser("broker")
    broker.add_argument("--socket", type=Path, required=True)
    broker.add_argument("--policy", type=Path, required=True)
    broker.add_argument("--token-file", type=Path, required=True)
    broker.add_argument("--trace", type=Path, required=True)
    broker.add_argument("--ready", type=Path, required=True)

    self_test = subparsers.add_parser("self-test")
    self_test.add_argument(
        "--mode", choices=("operator", "grader"), required=True
    )
    validate = subparsers.add_parser("validate-policy")
    validate.add_argument("--policy", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        if args.subcommand == "mcp":
            return _mcp(args)
        if args.subcommand == "broker":
            return _broker(args)
        if args.subcommand == "self-test":
            return _self_test(args)
        if args.subcommand == "validate-policy":
            return _validate_policy(args)
        raise AssertionError("unknown subcommand")
    except (BoundaryError, OSError, ValueError) as exc:
        print(f"claude-mcp-boundary: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
