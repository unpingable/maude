#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Stateful, command-neutral PTY adapter for synthetic operator sessions."""

from __future__ import annotations

import argparse
import base64
import contextlib
import json
import os
import pty
import select
import signal
import socket
import struct
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BROKER_ENV = "OPERATOR_PTY_SOCKET"
MAX_REQUEST_BYTES = 1024 * 1024
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
MAX_ARGUMENTS = 256
MAX_ARGUMENT_BYTES = 256 * 1024
BROKER_OPERATION_TIMEOUT_SECONDS = 900


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _input_bytes(value: str) -> bytes:
    if value.startswith("text:"):
        return value.removeprefix("text:").encode("utf-8")
    if value.startswith("hex:"):
        try:
            return bytes.fromhex(value.removeprefix("hex:"))
        except ValueError as exc:
            raise argparse.ArgumentTypeError(
                f"invalid hex input: {value!r}"
            ) from exc
    raise argparse.ArgumentTypeError(
        "input must begin with text: or hex:"
    )


def _positive(value: str) -> float:
    result = float(value)
    if result <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return result


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run any local command in one persistent pseudo-terminal. Use "
            "start, then alternate read/send/status calls, and finally stop. "
            "The exact PTY byte stream is preserved in the chosen output file."
        )
    )
    subparsers = parser.add_subparsers(dest="operation", required=True)

    start = subparsers.add_parser(
        "start",
        help="start one persistent PTY command and return after it is ready",
    )
    start.add_argument("--state", type=Path, required=True)
    start.add_argument("--output", type=Path, required=True)
    start.add_argument("--rows", type=int, default=30)
    start.add_argument("--columns", type=int, default=120)
    start.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="arbitrary command and arguments, conventionally after --",
    )

    for name, help_text in (
        ("send", "send exact bytes to the existing PTY"),
        ("stop", "request orderly stop, then terminate after a grace period"),
    ):
        command = subparsers.add_parser(name, help=help_text)
        command.add_argument("--state", type=Path, required=True)
        command.add_argument(
            "--input",
            action="append",
            type=_input_bytes,
            default=[],
            help="input as text:VALUE or hex:HEXBYTES; repeatable",
        )
        command.add_argument(
            "--wait",
            type=_positive,
            default=5.0,
            help="seconds to wait for acknowledgement/completion",
        )

    read = subparsers.add_parser(
        "read",
        help="print new PTY bytes since the previous read",
    )
    read.add_argument("--state", type=Path, required=True)
    read.add_argument(
        "--wait",
        type=float,
        default=2.0,
        help="seconds to wait for new output (zero is allowed)",
    )
    read.add_argument(
        "--all",
        action="store_true",
        help="print the complete stream without advancing the read cursor",
    )

    status = subparsers.add_parser(
        "status",
        help="show process and transcript state without changing it",
    )
    status.add_argument("--state", type=Path, required=True)
    serve = subparsers.add_parser(
        "serve",
        help=(
            "serve the PTY adapter over a private Unix socket so PTYs can "
            "survive disposable caller namespaces"
        ),
    )
    serve.add_argument("--socket", type=Path, required=True)
    serve.add_argument("--ready", type=Path, required=True)
    serve.add_argument("--cleanup-report", type=Path)
    serve.add_argument("--shutdown-request", type=Path)
    args = parser.parse_args(argv)
    if args.operation == "start":
        if args.command and args.command[0] == "--":
            args.command = args.command[1:]
        if not args.command:
            parser.error("start requires an executable after --")
        if args.rows <= 0 or args.columns <= 0:
            parser.error("rows and columns must be positive")
    if args.operation == "read" and args.wait < 0:
        parser.error("--wait must be nonnegative")
    return args


def _write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"invalid state object: {path}")
    return value


def _state_paths(root: Path) -> dict[str, Path]:
    return {
        "root": root,
        "state": root / "state.json",
        "requests": root / "requests.jsonl",
        "acks": root / "acks",
        "cursor": root / "read-offset",
        "ready": root / "ready.json",
        "error": root / "error.json",
    }


def _status_value(
    *,
    command: list[str],
    output: Path,
    daemon_pid: int,
    child_pid: int,
    status: str,
    exit_code: int | None,
    captured_bytes: int,
) -> dict[str, Any]:
    return {
        "schema": "maude.synthetic-operator.stateful-pty.v1",
        "command": command,
        "output": str(output),
        "daemon_pid": daemon_pid,
        "child_pid": child_pid,
        "status": status,
        "exit_code": exit_code,
        "captured_bytes": captured_bytes,
        "updated_at": _utc_now(),
    }


def _child_exit_code(wait_status: int) -> int:
    if os.WIFEXITED(wait_status):
        return os.WEXITSTATUS(wait_status)
    if os.WIFSIGNALED(wait_status):
        return 128 + os.WTERMSIG(wait_status)
    return 1


def _append_request(
    root: Path,
    *,
    kind: str,
    inputs: list[bytes],
    grace: float,
) -> str:
    paths = _state_paths(root)
    if not paths["state"].is_file():
        raise RuntimeError(f"PTY state is absent: {root}")
    request_id = uuid.uuid4().hex
    request = {
        "id": request_id,
        "kind": kind,
        "inputs_base64": [
            base64.b64encode(value).decode("ascii") for value in inputs
        ],
        "grace_seconds": grace,
        "created_at": _utc_now(),
    }
    encoded = (
        json.dumps(
            request,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    descriptor = os.open(
        paths["requests"],
        os.O_WRONLY | os.O_APPEND | os.O_CLOEXEC,
    )
    try:
        if os.write(descriptor, encoded) != len(encoded):
            raise RuntimeError("short write to PTY request queue")
    finally:
        os.close(descriptor)
    return request_id


def _wait_for(path: Path, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file():
            return True
        time.sleep(0.02)
    return path.is_file()


def _daemon(
    root: Path,
    output: Path,
    command: list[str],
    rows: int,
    columns: int,
) -> int:
    paths = _state_paths(root)
    daemon_pid = os.getpid()
    stop_requested = False

    def request_shutdown(_signum: int, _frame: Any) -> None:
        nonlocal stop_requested
        stop_requested = True

    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)
    child_pid, master = pty.fork()
    if child_pid == 0:
        os.execvp(command[0], command)
        raise AssertionError("unreachable")
    os.set_blocking(master, False)
    with contextlib.suppress(OSError):
        import fcntl
        import termios

        fcntl.ioctl(
            master,
            termios.TIOCSWINSZ,
            struct.pack("HHHH", rows, columns, 0, 0),
        )
    captured = output.stat().st_size
    request_offset = 0
    terminate_at: float | None = None
    wait_status: int | None = None
    _write_json(
        paths["state"],
        _status_value(
            command=command,
            output=output,
            daemon_pid=daemon_pid,
            child_pid=child_pid,
            status="running",
            exit_code=None,
            captured_bytes=captured,
        ),
    )
    _write_json(
        paths["ready"],
        {
            "schema": "maude.synthetic-operator.stateful-pty-ready.v1",
            "daemon_pid": daemon_pid,
            "child_pid": child_pid,
            "ready_at": _utc_now(),
        },
    )
    with output.open("ab", buffering=0) as stream:
        while True:
            readable, _, _ = select.select([master], [], [], 0.05)
            if readable:
                with contextlib.suppress(OSError):
                    chunk = os.read(master, 65536)
                    if chunk:
                        stream.write(chunk)
                        captured += len(chunk)
            with paths["requests"].open("rb") as queue:
                queue.seek(request_offset)
                while line := queue.readline():
                    request_offset = queue.tell()
                    request = json.loads(line)
                    request_id = str(request["id"])
                    accepted = True
                    error: str | None = None
                    try:
                        for encoded in request.get("inputs_base64", []):
                            os.write(master, base64.b64decode(encoded))
                        if request.get("kind") == "stop":
                            terminate_at = (
                                time.monotonic()
                                + float(request.get("grace_seconds", 0))
                            )
                        elif request.get("kind") != "send":
                            raise RuntimeError("unknown request kind")
                    except (OSError, ValueError, RuntimeError) as exc:
                        accepted = False
                        error = str(exc)
                    _write_json(
                        paths["acks"] / f"{request_id}.json",
                        {
                            "schema": (
                                "maude.synthetic-operator.stateful-pty-ack.v1"
                            ),
                            "request_id": request_id,
                            "accepted": accepted,
                            "error": error,
                            "acknowledged_at": _utc_now(),
                        },
                    )
            waited, candidate = os.waitpid(child_pid, os.WNOHANG)
            if waited:
                wait_status = candidate
                break
            if stop_requested or (
                terminate_at is not None and time.monotonic() >= terminate_at
            ):
                with contextlib.suppress(ProcessLookupError):
                    os.kill(child_pid, signal.SIGTERM)
                for _ in range(20):
                    time.sleep(0.05)
                    waited, candidate = os.waitpid(child_pid, os.WNOHANG)
                    if waited:
                        wait_status = candidate
                        break
                if wait_status is None:
                    with contextlib.suppress(ProcessLookupError):
                        os.kill(child_pid, signal.SIGKILL)
                    _, wait_status = os.waitpid(child_pid, 0)
                break
            _write_json(
                paths["state"],
                _status_value(
                    command=command,
                    output=output,
                    daemon_pid=daemon_pid,
                    child_pid=child_pid,
                    status="running",
                    exit_code=None,
                    captured_bytes=captured,
                ),
            )
        while True:
            try:
                chunk = os.read(master, 65536)
            except OSError:
                break
            if not chunk:
                break
            stream.write(chunk)
            captured += len(chunk)
    os.close(master)
    exit_code = _child_exit_code(int(wait_status))
    _write_json(
        paths["state"],
        _status_value(
            command=command,
            output=output,
            daemon_pid=daemon_pid,
            child_pid=child_pid,
            status="completed",
            exit_code=exit_code,
            captured_bytes=captured,
        ),
    )
    return exit_code


def _start(args: argparse.Namespace) -> int:
    root = args.state.resolve()
    output = args.output.resolve()
    if root.exists():
        raise RuntimeError(f"refusing to reuse PTY state directory: {root}")
    if output.exists():
        raise RuntimeError(f"refusing to overwrite PTY output: {output}")
    root.mkdir(parents=True, mode=0o700)
    paths = _state_paths(root)
    paths["acks"].mkdir()
    paths["requests"].write_bytes(b"")
    paths["cursor"].write_text("0\n", encoding="ascii")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"")
    pid = os.fork()
    if pid == 0:
        try:
            os.setsid()
            null = os.open(os.devnull, os.O_RDWR)
            for descriptor in (0, 1, 2):
                os.dup2(null, descriptor)
            if null > 2:
                os.close(null)
            code = _daemon(
                root,
                output,
                list(args.command),
                args.rows,
                args.columns,
            )
        except BaseException as exc:
            with contextlib.suppress(BaseException):
                _write_json(
                    paths["error"],
                    {
                        "schema": (
                            "maude.synthetic-operator.stateful-pty-error.v1"
                        ),
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "failed_at": _utc_now(),
                    },
                )
            code = 125
        os._exit(code)
    if not _wait_for(paths["ready"], 10.0):
        if paths["error"].is_file():
            raise RuntimeError(_load_json(paths["error"])["error"])
        raise RuntimeError("PTY daemon did not become ready")
    print(json.dumps(_load_json(paths["state"]), sort_keys=True))
    return 0


def _send_or_stop(args: argparse.Namespace) -> int:
    root = args.state.resolve()
    request_id = _append_request(
        root,
        kind=args.operation,
        inputs=list(args.input),
        grace=args.wait if args.operation == "stop" else 0.0,
    )
    ack = _state_paths(root)["acks"] / f"{request_id}.json"
    if not _wait_for(ack, args.wait):
        raise RuntimeError("PTY daemon did not acknowledge input")
    acknowledgement = _load_json(ack)
    if not acknowledgement.get("accepted"):
        raise RuntimeError(
            f"PTY daemon rejected input: {acknowledgement.get('error')}"
        )
    if args.operation == "stop":
        deadline = time.monotonic() + args.wait + 2.0
        while time.monotonic() < deadline:
            state = _load_json(_state_paths(root)["state"])
            if state.get("status") == "completed":
                break
            time.sleep(0.05)
    print(
        json.dumps(
            {
                **acknowledgement,
                "inputs_sent": len(args.input),
                "operation": args.operation,
                "state": _load_json(_state_paths(root)["state"]),
            },
            sort_keys=True,
        ),
        file=sys.stderr,
    )
    return 0


def _read(args: argparse.Namespace) -> int:
    root = args.state.resolve()
    paths = _state_paths(root)
    state = _load_json(paths["state"])
    output = Path(str(state["output"]))
    offset = (
        0
        if args.all
        else int(paths["cursor"].read_text(encoding="ascii").strip())
    )
    deadline = time.monotonic() + args.wait
    while (
        output.stat().st_size <= offset
        and state.get("status") == "running"
        and time.monotonic() < deadline
    ):
        time.sleep(0.05)
        state = _load_json(paths["state"])
    with output.open("rb") as stream:
        stream.seek(offset)
        data = stream.read()
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()
    if not args.all:
        paths["cursor"].write_text(
            f"{offset + len(data)}\n",
            encoding="ascii",
        )
    print(
        json.dumps(
            {
                "bytes_read": len(data),
                "from_offset": offset,
                "next_offset": offset + len(data),
                "status": state.get("status"),
            },
            sort_keys=True,
        ),
        file=sys.stderr,
    )
    return 0


def _recv_json_line(connection: socket.socket, limit: int) -> dict[str, Any]:
    data = bytearray()
    while True:
        chunk = connection.recv(min(65536, limit + 1 - len(data)))
        if not chunk:
            raise RuntimeError("socket closed before a complete request")
        data.extend(chunk)
        if len(data) > limit:
            raise RuntimeError("broker message exceeds the byte limit")
        if b"\n" in data:
            line, trailing = bytes(data).split(b"\n", 1)
            if trailing:
                raise RuntimeError("broker connection contained trailing bytes")
            try:
                value = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise RuntimeError("broker message is not valid JSON") from exc
            if not isinstance(value, dict):
                raise RuntimeError("broker message must be a JSON object")
            return value


def _send_json_line(connection: socket.socket, value: dict[str, Any]) -> None:
    encoded = (
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    connection.sendall(encoded)


def _state_argument(argv: list[str]) -> Path | None:
    for index, value in enumerate(argv):
        if value == "--state" and index + 1 < len(argv):
            return Path(argv[index + 1]).resolve()
        if value.startswith("--state="):
            return Path(value.split("=", 1)[1]).resolve()
    return None


def _validate_remote_argv(value: Any) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or len(value) > MAX_ARGUMENTS
        or not all(isinstance(item, str) for item in value)
    ):
        raise RuntimeError("argv must be a non-empty bounded string array")
    encoded_bytes = sum(len(item.encode("utf-8")) for item in value)
    if encoded_bytes > MAX_ARGUMENT_BYTES:
        raise RuntimeError("argv exceeds the broker byte limit")
    if value[0] not in {"start", "read", "send", "stop", "status"}:
        raise RuntimeError("operation is outside the fixed PTY client roster")
    return list(value)


def _run_local_operation(argv: list[str]) -> dict[str, Any]:
    environment = dict(os.environ)
    environment.pop(BROKER_ENV, None)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    process = subprocess.Popen(
        [
            sys.executable,
            "-B",
            str(Path(__file__).resolve()),
            *argv,
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
        start_new_session=True,
    )
    timed_out = False
    try:
        stdout, stderr = process.communicate(
            timeout=BROKER_OPERATION_TIMEOUT_SECONDS
        )
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
    return {
        "returncode": 124 if timed_out else int(process.returncode or 0),
        "timed_out": timed_out,
        "stdout_base64": base64.b64encode(stdout).decode("ascii"),
        "stderr_base64": base64.b64encode(stderr).decode("ascii"),
        "stdout_bytes": len(stdout),
        "stderr_bytes": len(stderr),
    }


def _pidfd_alive(pidfd: int) -> bool:
    poller = select.poll()
    poller.register(pidfd, select.POLLIN)
    return not bool(poller.poll(0))


def _track_started_pty(
    argv: list[str],
    result: dict[str, Any],
    tracked: dict[Path, dict[str, Any]],
) -> None:
    if argv[0] != "start" or result["returncode"] != 0:
        return
    root = _state_argument(argv)
    if root is None:
        return
    state_path = _state_paths(root)["state"]
    if not state_path.is_file():
        raise RuntimeError("successful PTY start did not create state")
    state = _load_json(state_path)
    daemon_pid = int(state["daemon_pid"])
    child_pid = int(state["child_pid"])
    try:
        pidfd = os.pidfd_open(daemon_pid)
    except (ProcessLookupError, PermissionError, OSError) as exc:
        with contextlib.suppress(ProcessLookupError):
            os.kill(daemon_pid, signal.SIGTERM)
        raise RuntimeError(
            f"cannot retain PTY daemon identity for pid {daemon_pid}: {exc}"
        ) from exc
    previous = tracked.pop(root, None)
    if previous is not None:
        with contextlib.suppress(OSError):
            os.close(int(previous["pidfd"]))
    tracked[root] = {
        "daemon_pid": daemon_pid,
        "child_pid": child_pid,
        "pidfd": pidfd,
    }


def _cleanup_tracked_ptys(
    tracked: dict[Path, dict[str, Any]],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for root, identity in sorted(
        tracked.items(), key=lambda item: str(item[0])
    ):
        pidfd = int(identity["pidfd"])
        daemon_pid = int(identity["daemon_pid"])
        child_pid = int(identity["child_pid"])
        stop_result: dict[str, Any] | None = None
        if _pidfd_alive(pidfd):
            stop_result = _run_local_operation(
                ["stop", "--state", str(root), "--wait", "1"]
            )
        for _ in range(100):
            if not _pidfd_alive(pidfd):
                break
            time.sleep(0.02)
        forced_signal: str | None = None
        if _pidfd_alive(pidfd):
            forced_signal = "SIGTERM"
            with contextlib.suppress(ProcessLookupError):
                signal.pidfd_send_signal(pidfd, signal.SIGTERM)
            for _ in range(100):
                if not _pidfd_alive(pidfd):
                    break
                time.sleep(0.02)
        if _pidfd_alive(pidfd):
            forced_signal = "SIGKILL"
            with contextlib.suppress(ProcessLookupError):
                signal.pidfd_send_signal(pidfd, signal.SIGKILL)
            for _ in range(100):
                if not _pidfd_alive(pidfd):
                    break
                time.sleep(0.02)
        remaining = _pidfd_alive(pidfd)
        records.append(
            {
                "state_root": str(root),
                "daemon_pid": daemon_pid,
                "child_pid": child_pid,
                "stop_result": stop_result,
                "forced_signal": forced_signal,
                "remaining": remaining,
            }
        )
        with contextlib.suppress(OSError):
            os.close(pidfd)
    tracked.clear()
    return records


def _load_shutdown_request(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    value = _load_json(path)
    if (
        set(value) != {"schema", "request_id", "requested_at"}
        or value.get("schema")
        != "maude.synthetic-operator.pty-broker-shutdown-request.v1"
        or not isinstance(value.get("request_id"), str)
        or not value["request_id"]
        or not isinstance(value.get("requested_at"), str)
        or not value["requested_at"]
    ):
        raise RuntimeError("invalid PTY broker shutdown request")
    return value


def _serve(args: argparse.Namespace) -> int:
    socket_path = args.socket.resolve()
    ready_path = args.ready.resolve()
    cleanup_path = (
        args.cleanup_report.resolve()
        if args.cleanup_report is not None
        else ready_path.with_name("broker-cleanup.json")
    )
    shutdown_path = (
        args.shutdown_request.resolve()
        if args.shutdown_request is not None
        else ready_path.with_name("broker-shutdown-request.json")
    )
    for path, label in (
        (socket_path, "socket"),
        (ready_path, "ready file"),
        (cleanup_path, "cleanup report"),
        (shutdown_path, "shutdown request"),
    ):
        if path.exists() or path.is_symlink():
            raise RuntimeError(f"refusing to overwrite broker {label}: {path}")
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    ready_path.parent.mkdir(parents=True, exist_ok=True)
    cleanup_path.parent.mkdir(parents=True, exist_ok=True)
    shutdown_path.parent.mkdir(parents=True, exist_ok=True)
    stop_requested = False
    shutdown_signal: int | None = None
    shutdown_request: dict[str, Any] | None = None
    tracked: dict[Path, dict[str, Any]] = {}
    handled_requests = 0
    cleanup_records: list[dict[str, Any]] = []

    def request_shutdown(signum: int, _frame: Any) -> None:
        nonlocal shutdown_signal, stop_requested
        shutdown_signal = signum
        stop_requested = True

    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        server.bind(str(socket_path))
        os.chmod(socket_path, 0o600)
        server.listen(4)
        server.settimeout(0.2)
        _write_json(
            ready_path,
            {
                "schema": "maude.synthetic-operator.pty-broker-ready.v1",
                "socket": str(socket_path),
                "broker_pid": os.getpid(),
                "ready_at": _utc_now(),
                "operations": ["start", "read", "send", "stop", "status"],
            },
        )
        while not stop_requested:
            shutdown_request = _load_shutdown_request(shutdown_path)
            if shutdown_request is not None:
                stop_requested = True
                break
            try:
                connection, _address = server.accept()
            except TimeoutError:
                continue
            with connection:
                request_id: str | None = None
                try:
                    request = _recv_json_line(
                        connection, MAX_REQUEST_BYTES
                    )
                    request_id = (
                        request.get("request_id")
                        if isinstance(request.get("request_id"), str)
                        else None
                    )
                    if not request_id:
                        raise RuntimeError("request_id must be a non-empty string")
                    argv = _validate_remote_argv(request.get("argv"))
                    result = _run_local_operation(argv)
                    _track_started_pty(argv, result, tracked)
                    response = {
                        "schema": (
                            "maude.synthetic-operator.pty-broker-response.v1"
                        ),
                        "request_id": request_id,
                        "ok": True,
                        **result,
                    }
                except (OSError, RuntimeError, ValueError) as exc:
                    response = {
                        "schema": (
                            "maude.synthetic-operator.pty-broker-response.v1"
                        ),
                        "request_id": request_id,
                        "ok": False,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                _send_json_line(connection, response)
                handled_requests += 1
    finally:
        server.close()
        cleanup_records = _cleanup_tracked_ptys(tracked)
        with contextlib.suppress(FileNotFoundError):
            socket_path.unlink()
        with contextlib.suppress(FileNotFoundError):
            shutdown_path.unlink()
        _write_json(
            cleanup_path,
            {
                "schema": "maude.synthetic-operator.pty-broker-cleanup.v1",
                "broker_pid": os.getpid(),
                "handled_requests": handled_requests,
                "tracked_ptys": cleanup_records,
                "all_tracked_ptys_stopped": not any(
                    record["remaining"] for record in cleanup_records
                ),
                "socket_removed": not socket_path.exists(),
                "shutdown_request": shutdown_request,
                "shutdown_request_removed": not shutdown_path.exists(),
                "shutdown_mode": (
                    "request-file"
                    if shutdown_request is not None
                    else "signal"
                    if shutdown_signal is not None
                    else "internal"
                ),
                "shutdown_signal": shutdown_signal,
                "completed_at": _utc_now(),
            },
        )
    if any(record["remaining"] for record in cleanup_records):
        raise RuntimeError("PTY broker cleanup left a tracked daemon alive")
    return 0


def _remote_client(socket_path: Path, argv: list[str]) -> int:
    request = {
        "schema": "maude.synthetic-operator.pty-broker-request.v1",
        "request_id": uuid.uuid4().hex,
        "argv": _validate_remote_argv(argv),
    }
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        connection.connect(str(socket_path))
        _send_json_line(connection, request)
        response = _recv_json_line(connection, MAX_RESPONSE_BYTES)
    finally:
        connection.close()
    if response.get("request_id") != request["request_id"]:
        raise RuntimeError("PTY broker response request_id mismatch")
    if not response.get("ok"):
        raise RuntimeError(
            f"PTY broker rejected request: {response.get('error')}"
        )
    try:
        stdout = base64.b64decode(
            str(response["stdout_base64"]), validate=True
        )
        stderr = base64.b64decode(
            str(response["stderr_base64"]), validate=True
        )
    except (KeyError, ValueError) as exc:
        raise RuntimeError("PTY broker response bytes are invalid") from exc
    if len(stdout) != response.get("stdout_bytes") or len(stderr) != response.get(
        "stderr_bytes"
    ):
        raise RuntimeError("PTY broker response byte count mismatch")
    sys.stdout.buffer.write(stdout)
    sys.stdout.buffer.flush()
    sys.stderr.buffer.write(stderr)
    sys.stderr.buffer.flush()
    return int(response["returncode"])


def main() -> int:
    remote_socket = os.environ.get(BROKER_ENV)
    if remote_socket and sys.argv[1:2] != ["serve"]:
        try:
            return _remote_client(Path(remote_socket), sys.argv[1:])
        except (OSError, RuntimeError, ValueError) as exc:
            print(f"operator-pty: {exc}", file=sys.stderr)
            return 2
    args = _parse_args()
    try:
        if args.operation == "start":
            return _start(args)
        if args.operation in {"send", "stop"}:
            return _send_or_stop(args)
        if args.operation == "read":
            return _read(args)
        if args.operation == "status":
            print(
                json.dumps(
                    _load_json(_state_paths(args.state.resolve())["state"]),
                    sort_keys=True,
                )
            )
            return 0
        if args.operation == "serve":
            return _serve(args)
        raise AssertionError(f"unknown operation: {args.operation}")
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"operator-pty: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
