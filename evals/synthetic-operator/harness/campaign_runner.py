#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Execute and independently grade the frozen synthetic-operator campaign.

This is evaluation orchestration. It changes only disposable synthetic labs
under the campaign's fixed /tmp prefix and evidence under the campaign run
directory. It never edits Maude product behavior, governance, or roadmaps.
"""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import contextlib
import json
import os
import re
import secrets
import select
import selectors
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import jsonschema

from campaign_common import (
    AUTH_GATE_PROBE_PATH,
    CAMPAIGN_DIR,
    CAMPAIGN_ID,
    HARNESS_DIR,
    INSTALL_SURFACE_PROBE_PATH,
    LAB_ROOT,
    MANIFEST_PATH,
    PACKET_DIR,
    REPO_ROOT,
    SCENARIOS_DIR,
    CampaignError,
    ensure_safe_lab_path,
    file_record,
    inventory_files,
    load_json,
    manifest_artifact_map,
    selected_runs,
    sha256_bytes,
    sha256_file,
    validate_manifest_hashes,
    validate_matrix,
    write_json,
    write_text,
)


EVIDENCE_SCHEMA = "maude.synthetic-operator.run-metadata.v1"
CLAUDE_HOST_BINARY = Path("/home/jbeck/.local/share/claude/versions/2.1.220")
CLAUDE_MCP_BRIDGE_SOURCE = HARNESS_DIR / "claude_mcp_bridge.py"
CLAUDE_MCP_BRIDGE_MOUNT = Path("/opt/maude-eval/claude_mcp_bridge.py")
CLAUDE_MCP_PRIVATE_MOUNT = Path("/run/maude-eval-mcp")
CLAUDE_MCP_PROTOCOL_VERSION = "2025-11-25"
CODEX_MCP_PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_MCP_PROTOCOL_VERSIONS = (
    CODEX_MCP_PROTOCOL_VERSION,
    CLAUDE_MCP_PROTOCOL_VERSION,
)
CODEX_APPROVAL_POLICY = "never"
CODEX_APPROVAL_CONFIG = 'approval_policy="never"'
CODEX_APPROVAL_CONFIG_ARGV = ("--config", CODEX_APPROVAL_CONFIG)
CODEX_MCP_DEFAULT_TOOLS_APPROVAL_MODE = "approve"
CLAUDE_OPERATOR_SERVER = "operator"
CLAUDE_GRADER_SERVER = "grader"
CLAUDE_OPERATOR_TOOLS = ("mcp__operator__terminal",)
CLAUDE_GRADER_TOOLS = ("mcp__grader__evidence",)
PUBLIC_CLI_BROKER_SOURCE = HARNESS_DIR / "public_cli_broker.py"
PUBLIC_CLI_SOCKET_MOUNT = Path("/run/maude-public/broker.sock")
CLAUDE_COMMAND_SOCKET_MOUNT = Path("/run/maude-eval-broker/broker.sock")
CLAUDE_PTY_SERVER_SOCKET_MOUNT = Path("/run/operator-pty-private/broker.sock")
UNIX_SOCKET_PATH_BUDGET = 100
PRIVATE_SOCKET_ROOT = Path("/tmp") / (
    "maude-sock-" + sha256_bytes(CAMPAIGN_ID.encode("utf-8"))[:12]
)
CODEX_DISABLED_OPTIONAL_FEATURES = (
    "apps",
    "plugins",
    "remote_plugin",
    "browser_use",
    "browser_use_external",
    "browser_use_full_cdp_access",
    "computer_use",
    "image_generation",
    "multi_agent",
    "multi_agent_v2",
    "hooks",
    "skill_mcp_dependency_install",
    "tool_call_mcp_elicitation",
)
CODEX_DISABLED_INTRINSIC_ACTION_FEATURES = (
    "shell_tool",
    "unified_exec",
)
CODEX_HOST_ROOT = Path("/home/jbeck/.nvm/versions/node/v24.13.0")
CODEX_SANDBOX_BINARY = Path("/opt/node/bin/codex")
BWRAP = Path("/usr/bin/bwrap")
HOST_SOURCE_ROOT = Path("/home/jbeck/git/agent_gov_ui")
QUARANTINE_ROOT = Path("/tmp") / "maude-synthetic-operator-quarantine"
DEFAULT_TIMEOUT = 1200
AUTH_GATE_PROBE_TIMEOUT = 300
COMMAND_BROKER_DEFAULT_TIMEOUT_SECONDS = 300
COMMAND_BROKER_MAX_TIMEOUT_SECONDS = 600
PROVIDER_AUTH_MOUNT = Path("/run/provider-auth")
CODEX_AUTH_GATE_ABSENCE_CHECK_COMMAND = (
    '/usr/bin/test "$(/usr/bin/cat "$HOME/probe-sentinel")" = '
    "clean-home-sentinel && "
    "provider_auth_root=/run/provider-''auth && "
    '/usr/bin/test ! -e "$provider_auth_root/.codex/auth.json" && '
    "/usr/bin/test ! -e "
    '"$provider_auth_root/.codex/installation_id" && '
    "/usr/bin/printf 'PROVIDER_AUTH_ABSENT_OK\\n'"
)
PROVIDER_PROBE_TERMINAL_TIMEOUT_SECONDS = 30
CODEX_AUTH_GATE_ABSENCE_TIMEOUT_SECONDS = (
    PROVIDER_PROBE_TERMINAL_TIMEOUT_SECONDS
)
CODEX_AUTH_GATE_ABSENCE_CHECK_SHA256 = sha256_bytes(
    CODEX_AUTH_GATE_ABSENCE_CHECK_COMMAND.encode("utf-8")
)
OPERATOR_HOME_MOUNT = Path("/home/operator")
INSTALL_MEDIA_DIR = PACKET_DIR / "installation-media"
INSTALL_WHEELHOUSE = INSTALL_MEDIA_DIR / "wheelhouse"
INSTALL_RUNTIME_LOCK = INSTALL_MEDIA_DIR / "runtime-requirements.txt"
INSTALL_PROVENANCE = INSTALL_MEDIA_DIR / "provenance.json"
INSTALL_DOC_PACKET_DIR = PACKET_DIR / "installation-docs"
CLEANROOM_OS_ROOT = LAB_ROOT / "_cleanroom-os"
INSTALL_CANDIDATE_ENVIRONMENTS = (
    Path("operator/.venv"),
    Path("operator/venv"),
    Path("work/.venv"),
    Path("work/venv"),
)

CLAUDE_AUTH_FILES = (
    (Path("/home/jbeck/.claude.json"), Path(".claude.json")),
    (
        Path("/home/jbeck/.claude/.credentials.json"),
        Path(".claude/.credentials.json"),
    ),
    (Path("/home/jbeck/.claude/settings.json"), Path(".claude/settings.json")),
)
CODEX_AUTH_FILES = (
    (Path("/home/jbeck/.codex/auth.json"), Path(".codex/auth.json")),
)
OBVIOUS_SECRET_PATTERNS = (
    re.compile(rb"sk-ant-[A-Za-z0-9_-]{10,}"),
    re.compile(rb"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(rb"gh[pousr]_[A-Za-z0-9]{16,}"),
    re.compile(rb"Bearer[ \t]+[A-Za-z0-9._~+/=-]{16,}", re.IGNORECASE),
)


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _run_dir(run_id: str) -> Path:
    return CAMPAIGN_DIR / run_id


def _checked_unix_socket_path(path: Path, *, label: str) -> Path:
    """Reject sockaddr_un paths before a binder or client can see them."""

    encoded = os.fsencode(str(path))
    if b"\0" in encoded:
        raise CampaignError(f"{label}: Unix socket path contains NUL")
    if len(encoded) > UNIX_SOCKET_PATH_BUDGET:
        raise CampaignError(
            f"{label}: Unix socket path uses {len(encoded)} bytes, exceeding "
            f"the conservative {UNIX_SOCKET_PATH_BUDGET}-byte campaign budget"
        )
    return path


def _private_socket_directory(*, label: str) -> Path:
    """Allocate one short, owner-private arena for a single socket."""

    try:
        PRIVATE_SOCKET_ROOT.mkdir(mode=0o700)
    except FileExistsError:
        pass
    root_stat = PRIVATE_SOCKET_ROOT.lstat()
    if (
        PRIVATE_SOCKET_ROOT.is_symlink()
        or not stat.S_ISDIR(root_stat.st_mode)
        or root_stat.st_uid != os.getuid()
        or root_stat.st_mode & 0o077
    ):
        raise CampaignError(
            "private Unix-socket arena is not an owner-only real directory"
        )
    for _attempt in range(32):
        nonce = sha256_bytes(
            f"{CAMPAIGN_ID}:{label}:{uuid.uuid4().hex}".encode("utf-8")
        )[:20]
        directory = PRIVATE_SOCKET_ROOT / f"s-{nonce}"
        try:
            directory.mkdir(mode=0o700)
        except FileExistsError:
            continue
        _checked_unix_socket_path(
            directory / "broker.sock",
            label=f"{label} private socket",
        )
        return directory
    raise CampaignError(f"{label}: could not allocate a unique socket arena")


def _release_private_socket_directories(
    boundary: dict[str, Any] | None,
) -> dict[str, Any]:
    """Remove empty per-boundary arenas; never erase a live/stale socket."""

    directories = (
        boundary.get("private_socket_directories", [])
        if isinstance(boundary, dict)
        else []
    )
    records: list[dict[str, Any]] = []
    all_removed = True
    for raw in directories:
        directory = Path(str(raw))
        if directory.parent != PRIVATE_SOCKET_ROOT:
            raise CampaignError(
                f"refusing non-arena private socket cleanup: {directory}"
            )
        remaining = (
            sorted(path.name for path in directory.iterdir())
            if directory.is_dir() and not directory.is_symlink()
            else []
        )
        removed = False
        if directory.is_dir() and not directory.is_symlink() and not remaining:
            directory.rmdir()
            removed = not directory.exists()
        elif not directory.exists():
            removed = True
        all_removed = all_removed and removed
        records.append(
            {
                "directory": str(directory),
                "remaining_entries": remaining,
                "removed": removed,
            }
        )
    return {
        "root": str(PRIVATE_SOCKET_ROOT),
        "path_budget_bytes": UNIX_SOCKET_PATH_BUDGET,
        "directories": records,
        "all_removed": all_removed,
    }


def _lab_dir(run_id: str) -> Path:
    path = LAB_ROOT / run_id
    ensure_safe_lab_path(path)
    return path


def _copy_file(source: Path, target: Path, *, executable: bool = False) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    target.chmod(0o755 if executable else 0o644)


def _copy_tree(source: Path, target: Path) -> None:
    _regular_tree_files(source, label="copy source")
    if target.exists():
        raise CampaignError(f"refusing to overwrite existing tree: {target}")
    shutil.copytree(source, target, symlinks=True)


def _regular_tree_files(root: Path, *, label: str) -> list[Path]:
    if not root.is_dir():
        raise CampaignError(f"{label}: directory is absent: {root}")
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise CampaignError(f"{label}: special path is forbidden: {path}")
        if path.is_file():
            files.append(path)
    return files


def _safe_remove_lab(path: Path) -> None:
    ensure_safe_lab_path(path)
    if path.exists():
        shutil.rmtree(path)


def _command(
    argv: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    expected: int | None = 0,
) -> dict[str, Any]:
    completed = subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    record = {
        "argv": argv,
        "cwd": str(cwd) if cwd is not None else None,
        "returncode": completed.returncode,
        "stdout": completed.stdout.decode("utf-8", errors="replace"),
        "stderr": completed.stderr.decode("utf-8", errors="replace"),
    }
    if expected is not None and completed.returncode != expected:
        raise CampaignError(
            f"command returned {completed.returncode}, expected {expected}: "
            f"{argv!r}\n{record['stderr']}"
        )
    return record


def validate_packet() -> list[str]:
    errors = validate_matrix()
    if not MANIFEST_PATH.is_file():
        errors.append(f"frozen campaign manifest missing: {MANIFEST_PATH}")
        return errors
    manifest = load_json(MANIFEST_PATH)
    if manifest.get("campaign_id") != CAMPAIGN_ID:
        errors.append("frozen manifest campaign ID mismatch")
    errors.extend(validate_manifest_hashes(manifest))
    sut_commit = manifest.get("system_under_test", {}).get("commit")
    sut_diff = _command(
        [
            "git",
            "diff",
            "--exit-code",
            str(sut_commit),
            "--",
            "src",
            "pyproject.toml",
        ],
        cwd=REPO_ROOT,
        expected=None,
    )
    if sut_diff["returncode"] != 0:
        errors.append(
            "current Maude product bytes differ from the frozen SUT commit"
        )
    sut_status = _command(
        [
            "git",
            "status",
            "--porcelain",
            "--untracked-files=all",
            "--",
            "src",
            "pyproject.toml",
        ],
        cwd=REPO_ROOT,
        expected=None,
    )
    relevant_status = [
        line
        for line in sut_status["stdout"].splitlines()
        if "__pycache__" not in line and not line.endswith(".pyc")
    ]
    if relevant_status:
        errors.append(
            "current Maude product paths have working-tree changes: "
            + "; ".join(relevant_status)
        )
    for run in manifest.get("runs", []):
        for field in (
            "rendered_operator_prompt",
            "rendered_grader_assignment",
            "rendered_supplied_inputs",
            "rendered_session_config",
        ):
            path = REPO_ROOT / str(run.get(field, ""))
            if not path.is_file():
                errors.append(f"{run.get('run_id')}: missing {field}: {path}")
    return errors


def _validate_or_raise() -> dict[str, Any]:
    errors = validate_packet()
    if errors:
        raise CampaignError("frozen packet validation failed:\n" + "\n".join(errors))
    return load_json(MANIFEST_PATH)


def _manifest_run(run_id: str, manifest: dict[str, Any]) -> dict[str, Any]:
    for run in manifest["runs"]:
        if run["run_id"] == run_id:
            return run
    raise CampaignError(f"run absent from frozen manifest: {run_id}")


def _extract_tar_safely(archive: Path, destination: Path, run_id: str) -> None:
    expected_root = destination / run_id
    with tarfile.open(archive, "r") as handle:
        members = handle.getmembers()
        for member in members:
            member_path = Path(member.name)
            if (
                member_path.is_absolute()
                or ".." in member_path.parts
                or not member_path.parts
                or member_path.parts[0] != run_id
                or member.issym()
                or member.islnk()
                or member.isdev()
            ):
                raise CampaignError(
                    f"unsafe member in direct fixture archive: {member.name!r}"
                )
            target = (destination / member_path).resolve()
            if target != expected_root.resolve() and expected_root.resolve() not in target.parents:
                raise CampaignError(
                    f"direct fixture member escapes selected run: {member.name!r}"
                )
        handle.extractall(destination, members=members)


def _git_init_synthetic(repo: Path, scenario: dict[str, Any]) -> str:
    clock = load_json(
        SCENARIOS_DIR / scenario["scenario_id"] / "runtime.json"
    ).get("clock_start", "2026-07-27T03:30:00Z")
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_DATE": clock,
            "GIT_COMMITTER_DATE": clock,
        }
    )
    _command(["git", "init", "-q", "--initial-branch=main"], cwd=repo, env=env)
    _command(
        ["git", "config", "user.name", "Synthetic Operator Lab"],
        cwd=repo,
        env=env,
    )
    _command(
        [
            "git",
            "config",
            "user.email",
            "synthetic-operator@example.invalid",
        ],
        cwd=repo,
        env=env,
    )
    _command(["git", "add", "-A"], cwd=repo, env=env)
    _command(
        ["git", "commit", "-q", "-m", "synthetic base fixture"],
        cwd=repo,
        env=env,
    )
    return _command(["git", "rev-parse", "HEAD"], cwd=repo)["stdout"].strip()


def _scenario_visible_files(run: dict[str, Any]) -> list[tuple[Path, Path]]:
    scenario = SCENARIOS_DIR / run["scenario_id"]
    lab = _lab_dir(run["run_id"])
    operator = lab / "operator"
    rendered_task = (
        PACKET_DIR / "rendered" / run["run_id"] / "operator-task.md"
    )
    if run["surface"] == "maude":
        names = ["packet.json", "plan.md", "playbook.json", "ration-card.json"]
        approvals = sorted(scenario.glob("lab_approval_*"))
        names.extend(path.name for path in approvals)
        result = [(rendered_task, operator / "task" / "README.md")]
        result.append(
            (
                HARNESS_DIR / "operator_retrospective.py",
                operator / "operator-retrospective",
            )
        )
        result.extend(
            (scenario / name, operator / "task" / name)
            for name in names
            if (scenario / name).is_file()
        )
        return result
    if run["surface"] == "maude-installation":
        install_root = lab / "installation"
        frozen = load_json(
            PACKET_DIR
            / "rendered"
            / run["run_id"]
            / "supplied-inputs.json"
        )
        result: list[tuple[Path, Path]] = []
        destinations: set[str] = set()
        for record in frozen["visible_files"]:
            source = REPO_ROOT / record["path"]
            destination = str(record["destination"])
            if destination in destinations:
                raise CampaignError(
                    f"{run['run_id']}: duplicate frozen destination "
                    f"{destination}"
                )
            destinations.add(destination)
            if (
                not source.is_file()
                or source.is_symlink()
                or source.stat().st_size != record["bytes"]
                or sha256_file(source) != record["sha256"]
            ):
                raise CampaignError(
                    f"{run['run_id']}: frozen installation input changed: "
                    f"{source}"
                )
            target = (install_root / destination).resolve()
            if install_root.resolve() not in target.parents:
                raise CampaignError(
                    f"{run['run_id']}: installation destination escapes lab: "
                    f"{destination}"
                )
            result.append((source, target))
        return result
    return [
        (rendered_task, operator / "task" / "README.md"),
        (
            HARNESS_DIR / "operator_retrospective.py",
            operator / "operator-retrospective",
        ),
        (scenario / "packet.json", operator / "task" / "packet.json"),
        (scenario / "patch.diff", operator / "candidate.patch"),
        (
            PACKET_DIR
            / "rendered"
            / run["run_id"]
            / "direct-control.json",
            operator / "control.json",
        ),
    ]


def _capture_repo(repo: Path, target: Path, *, label: str) -> dict[str, Any]:
    target.mkdir(parents=True, exist_ok=True)
    files_target = target / "files"
    if files_target.exists():
        raise CampaignError(f"repository snapshot already exists: {files_target}")
    files_target.mkdir()
    for path in sorted(repo.rglob("*")):
        if not path.is_file() or ".git" in path.relative_to(repo).parts:
            continue
        destination = files_target / path.relative_to(repo)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
    commands = {}
    for name, argv in (
        ("status-short", ["git", "status", "--short"]),
        ("diff", ["git", "diff", "--no-ext-diff"]),
        ("head", ["git", "rev-parse", "HEAD"]),
        ("target-ref", ["git", "rev-parse", "--verify", "refs/gwr/target"]),
        (
            "target-diff",
            ["git", "diff", "--no-ext-diff", "HEAD", "refs/gwr/target"],
        ),
        (
            "target-show",
            ["git", "show", "--stat", "--oneline", "refs/gwr/target"],
        ),
    ):
        result = _command(argv, cwd=repo, expected=None)
        commands[name] = result
        write_text(target / f"{name}.txt", result["stdout"] + result["stderr"])
    inventory = inventory_files(files_target)
    record = {
        "schema": "maude.synthetic-operator.repository-snapshot.v1",
        "label": label,
        "repository": str(repo),
        "files": inventory,
        "commands": commands,
    }
    write_json(target / "inventory.json", record)
    return record


def _capture_operator_supplied(operator: Path, target: Path) -> dict[str, Any]:
    """Preserve exact non-executable operator materials for later grading."""

    files_target = target / "files"
    files_target.mkdir(parents=True)
    selected: list[Path] = []
    for relative in (Path("task"), Path("docs")):
        root = operator / relative
        if root.is_dir():
            selected.extend(path for path in root.rglob("*") if path.is_file())
    for name in ("control.json", "candidate.patch"):
        path = operator / name
        if path.is_file():
            selected.append(path)
    for source in sorted(set(selected)):
        destination = files_target / source.relative_to(operator)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    result = {
        "schema": "maude.synthetic-operator.operator-supplied-snapshot.v1",
        "operator_root": str(operator),
        "files": inventory_files(files_target),
        "public_cli_binaries_copied": False,
    }
    write_json(target / "inventory.json", result)
    return result


def _installation_root(run_id: str) -> Path:
    return _lab_dir(run_id) / "installation"


def _tree_inventory(
    root: Path,
    *,
    allowed_sockets: set[Path] | None = None,
) -> dict[str, Any]:
    allowed_socket_paths = {
        path.resolve() for path in (allowed_sockets or set())
    }
    files: list[dict[str, Any]] = []
    directories: list[dict[str, str]] = []
    symlinks: list[dict[str, str]] = []
    sockets: list[dict[str, Any]] = []
    if not root.exists():
        return {
            "root": str(root),
            "exists": False,
            "files": [],
            "directories": [],
            "symlinks": [],
            "sockets": [],
            "digest": sha256_bytes(b"[]\n"),
        }
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            symlinks.append(
                {"path": relative, "target": os.readlink(path)}
            )
        elif path.is_dir():
            directories.append(
                {
                    "path": relative,
                    "mode": f"{path.stat().st_mode & 0o777:04o}",
                }
            )
        elif path.is_file():
            files.append(file_record(path, relative_to=root))
        else:
            metadata = path.lstat()
            if (
                stat.S_ISSOCK(metadata.st_mode)
                and path.resolve() in allowed_socket_paths
            ):
                sockets.append(
                    {
                        "path": relative,
                        "mode": f"{metadata.st_mode & 0o777:04o}",
                        "uid": metadata.st_uid,
                        "gid": metadata.st_gid,
                        "allowlisted": True,
                    }
                )
            else:
                raise CampaignError(
                    "installation tree contains unlisted special path: "
                    f"{path}"
                )
    canonical = json.dumps(
        {
            "files": files,
            "directories": directories,
            "symlinks": symlinks,
            "sockets": sockets,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return {
        "root": str(root),
        "exists": True,
        "files": files,
        "directories": directories,
        "symlinks": symlinks,
        "sockets": sockets,
        "digest": sha256_bytes(canonical),
    }


def _installation_probe(
    install_root: Path,
    *,
    expected_installed: bool | None,
) -> dict[str, Any]:
    venv = install_root / "venv"
    python = venv / "bin" / "python"
    maude = venv / "bin" / "maude"
    result: dict[str, Any] = {
        "schema": "maude.synthetic-installation.package-probe.v1",
        "venv": str(venv),
        "venv_exists": venv.is_dir(),
        "python_exists": python.is_file(),
        "maude_entrypoint_exists": maude.is_file(),
        "maude_entrypoint_executable": (
            maude.is_file() and os.access(maude, os.X_OK)
        ),
        "expected_installed": expected_installed,
    }
    if not python.is_file():
        if expected_installed is True:
            raise CampaignError(
                f"expected installed Python environment is absent: {venv}"
            )
        return result
    env = {
        "HOME": str(install_root / "home"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": f"{venv / 'bin'}:/usr/bin:/bin",
        "PIP_CONFIG_FILE": "/dev/null",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    probe_source = """\
import hashlib
import importlib.metadata as metadata
import importlib.util
import json
import os
import pathlib
import sys

prefix = pathlib.Path(sys.prefix).resolve()
spec = importlib.util.find_spec("maude")
module = pathlib.Path(spec.origin).resolve() if spec and spec.origin else None
script = prefix / "bin" / "maude"
script_bytes = script.read_bytes() if script.is_file() else b""
packages = {
    dist.metadata["Name"]: dist.version
    for dist in metadata.distributions()
    if dist.metadata.get("Name")
}
direct_urls = sorted(
    str(path.relative_to(prefix))
    for path in prefix.rglob("direct_url.json")
)
egg_links = sorted(
    str(path.relative_to(prefix))
    for path in prefix.rglob("*.egg-link")
)
pth_files = sorted(
    str(path.relative_to(prefix))
    for path in prefix.rglob("*.pth")
)
print(json.dumps({
    "prefix": str(prefix),
    "packages": packages,
    "maude_module": str(module) if module else None,
    "maude_module_inside_prefix": bool(module and prefix in module.parents),
    "maude_distribution_version": (
        metadata.version("maude")
        if "maude" in {name.lower() for name in packages}
        else None
    ),
    "console_script": str(script),
    "console_script_exists": script.is_file(),
    "console_script_executable": os.access(script, os.X_OK),
    "console_script_sha256": (
        hashlib.sha256(script_bytes).hexdigest() if script_bytes else None
    ),
    "console_script_first_line": (
        script_bytes.splitlines()[0].decode("utf-8", errors="replace")
        if script_bytes else None
    ),
    "direct_url_files": direct_urls,
    "egg_link_files": egg_links,
    "pth_files": pth_files,
    "sys_path": sys.path,
}, sort_keys=True))
"""
    probe = _command(
        [str(python), "-c", probe_source],
        env=env,
        expected=None,
    )
    result["probe_command"] = probe
    if probe["returncode"] == 0:
        try:
            result["observed"] = json.loads(probe["stdout"])
        except json.JSONDecodeError as exc:
            raise CampaignError(
                "installation package probe returned non-JSON output"
            ) from exc
    else:
        result["observed"] = None
    result["pip_check"] = _command(
        [str(python), "-m", "pip", "check"],
        env=env,
        expected=None,
    )
    result["pip_freeze"] = _command(
        [str(python), "-m", "pip", "freeze", "--all"],
        env=env,
        expected=None,
    )
    result["maude_help"] = (
        _command([str(maude), "--help"], env=env, expected=None)
        if maude.is_file()
        else None
    )
    if expected_installed is True:
        observed = result.get("observed") or {}
        if (
            probe["returncode"] != 0
            or observed.get("maude_distribution_version") != "2.4.0"
            or not observed.get("maude_module_inside_prefix")
            or not observed.get("console_script_exists")
            or not observed.get("console_script_executable")
            or observed.get("direct_url_files")
            or observed.get("egg_link_files")
            or observed.get("pth_files")
            or result["pip_check"]["returncode"] != 0
            or result["maude_help"]["returncode"] != 0
        ):
            raise CampaignError(
                "fresh installed-state probe did not prove an ordinary Maude "
                "2.4.0 installation"
            )
    return result


def _static_installation_probe(
    install_root: Path,
    *,
    venv_path: Path | None = None,
) -> dict[str, Any]:
    """Inspect operator-mutable installation bytes without executing them."""

    venv = venv_path or (install_root / "venv")
    resolved_root = install_root.resolve()
    if not venv.is_symlink():
        resolved_venv = venv.resolve()
        if (
            resolved_venv != resolved_root
            and resolved_root not in resolved_venv.parents
        ):
            raise CampaignError(
                f"static installation probe escapes root: {venv}"
            )

    def path_state(path: Path) -> dict[str, Any]:
        if path.is_symlink():
            return {
                "path": str(path),
                "kind": "symlink",
                "target": os.readlink(path),
            }
        if not path.exists():
            return {"path": str(path), "kind": "absent"}
        metadata = path.lstat()
        if stat.S_ISREG(metadata.st_mode):
            return {
                **file_record(path, relative_to=install_root),
                "kind": "regular-file",
            }
        if stat.S_ISDIR(metadata.st_mode):
            return {
                "path": str(path.relative_to(install_root)),
                "kind": "directory",
                "mode": f"{metadata.st_mode & 0o777:04o}",
            }
        return {
            "path": str(path.relative_to(install_root)),
            "kind": "special",
            "mode": f"{metadata.st_mode & 0o777:04o}",
        }

    python = venv / "bin" / "python"
    maude = venv / "bin" / "maude"
    venv_lib = venv / "lib"
    site_packages = (
        sorted(
            candidate
            for candidate in venv_lib.glob("python*/site-packages")
            if candidate.is_dir()
            and not candidate.is_symlink()
            and not candidate.parent.is_symlink()
        )
        if venv.is_dir()
        and not venv.is_symlink()
        and venv_lib.is_dir()
        and not venv_lib.is_symlink()
        else []
    )
    metadata_files: list[dict[str, Any]] = []
    package_modules: list[dict[str, Any]] = []
    configuration_files: list[dict[str, Any]] = []
    for site in site_packages:
        for metadata_dir in sorted(site.glob("maude-*.dist-info")):
            if not metadata_dir.is_dir() or metadata_dir.is_symlink():
                continue
            metadata_path = metadata_dir / "METADATA"
            entry_points = metadata_dir / "entry_points.txt"
            parsed: dict[str, str] = {}
            if (
                metadata_path.is_file()
                and not metadata_path.is_symlink()
                and metadata_path.stat().st_size <= 1024 * 1024
            ):
                for line in metadata_path.read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines():
                    if line.startswith("Name: ") and "name" not in parsed:
                        parsed["name"] = line.removeprefix("Name: ")
                    elif (
                        line.startswith("Version: ")
                        and "version" not in parsed
                    ):
                        parsed["version"] = line.removeprefix("Version: ")
            metadata_files.append(
                {
                    "directory": str(
                        metadata_dir.relative_to(install_root)
                    ),
                    "metadata": path_state(metadata_path),
                    "entry_points": path_state(entry_points),
                    "parsed_name_version": parsed,
                }
            )
        module = site / "maude"
        if module.exists() or module.is_symlink():
            package_modules.append(
                {
                    "path": str(module.relative_to(install_root)),
                    "state": path_state(module),
                    "tree": (
                        _tree_inventory(module)
                        if module.is_dir() and not module.is_symlink()
                        else None
                    ),
                }
            )
        for pattern in ("*.pth", "*.egg-link", "*/direct_url.json"):
            for path in sorted(site.glob(pattern)):
                if path.is_file() and not path.is_symlink():
                    configuration_files.append(path_state(path))
    return {
        "schema": "maude.synthetic-installation.static-package-probe.v1",
        "inspection_mode": "trusted evaluator read-only data inspection",
        "operator_mutable_bytes_executed": False,
        "venv": path_state(venv),
        "python": path_state(python),
        "maude_entrypoint": path_state(maude),
        "site_packages": [
            str(path.relative_to(install_root)) for path in site_packages
        ],
        "maude_distribution_metadata": metadata_files,
        "maude_package_modules": package_modules,
        "import_or_entrypoint_configuration": configuration_files,
    }


def _materialize_installed_distribution(
    run: dict[str, Any],
    install_root: Path,
    evidence: Path,
) -> dict[str, Any] | None:
    if run.get("source_visibility") != "installed-distribution":
        return None
    venv = install_root / "venv"
    if venv.exists():
        raise CampaignError(
            f"{run['run_id']}: installation environment already exists"
        )
    setup_home = _lab_dir(run["run_id"]) / "private-install-setup-home"
    setup_home.mkdir(mode=0o700)
    env = {
        "HOME": str(setup_home),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": "/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    commands = [
        _command(
            ["/usr/bin/python3", "-m", "venv", str(venv)],
            env=env,
        )
    ]
    python = venv / "bin" / "python"
    commands.append(
        _command(
            [
                str(python),
                "-m",
                "pip",
                "--isolated",
                "install",
                "--disable-pip-version-check",
                "--no-cache-dir",
                "--no-index",
                "--find-links",
                str(INSTALL_WHEELHOUSE),
                "--require-hashes",
                "--requirement",
                str(INSTALL_RUNTIME_LOCK),
            ],
            env=env,
        )
    )
    setup_private = evidence / "raw" / "installation-setup.json"
    probe = _installation_probe(install_root, expected_installed=True)
    record = {
        "schema": "maude.synthetic-installation.materialization.v1",
        "run_id": run["run_id"],
        "authority_effect": "none",
        "commands": commands,
        "probe": probe,
        "installation_media_provenance": file_record(INSTALL_PROVENANCE),
        "runtime_requirements": file_record(INSTALL_RUNTIME_LOCK),
        "wheelhouse_inventory": inventory_files(INSTALL_WHEELHOUSE),
        "network_controls": (
            "pip --isolated --no-index --no-cache-dir with an exact frozen "
            "local wheelhouse and --require-hashes; no intentional network "
            "operation; no OS network namespace claimed for materialization"
        ),
        "package_command_wrapper": False,
        "mirror_rewrite": False,
        "copied_site_packages": False,
        "editable_install": False,
    }
    write_json(setup_private, record)
    shutil.rmtree(setup_home)
    return record


def _capture_installation_state(
    run: dict[str, Any],
    install_root: Path,
    target: Path,
    *,
    label: str,
    allowed_socket: Path | None = None,
) -> dict[str, Any]:
    target.mkdir(parents=True, exist_ok=True)
    expected_installed = (
        True
        if label == "before"
        and run.get("source_visibility") == "installed-distribution"
        else None
    )
    result = {
        "schema": "maude.synthetic-installation.state-capture.v1",
        "run_id": run["run_id"],
        "label": label,
        "package_state": (
            _installation_probe(
                install_root,
                expected_installed=expected_installed,
            )
            if label == "before"
            else _static_installation_probe(install_root)
        ),
        "candidate_installation_states": {
            relative.as_posix(): _static_installation_probe(
                install_root,
                venv_path=install_root / relative,
            )
            for relative in INSTALL_CANDIDATE_ENVIRONMENTS
        },
        "installed_environment_tree": _tree_inventory(
            install_root / "venv"
        ),
        "project_tree": _tree_inventory(install_root / "project"),
        "work_tree": _tree_inventory(install_root / "work"),
        "operator_tree": _tree_inventory(install_root / "operator"),
        "task_tree": _tree_inventory(install_root / "task"),
        "docs_tree": _tree_inventory(install_root / "docs"),
        "media_tree": _tree_inventory(install_root / "media"),
        "home_tree": _tree_inventory(install_root / "home"),
        "run_tree": _tree_inventory(
            install_root / "run",
            allowed_sockets=({allowed_socket} if allowed_socket else set()),
        ),
        "authority_effect": "none",
    }
    write_json(target / "state.json", result)
    return result


def _capture_install_operator_supplied(
    run: dict[str, Any],
    install_root: Path,
    target: Path,
) -> dict[str, Any]:
    files_target = target / "files"
    files_target.mkdir(parents=True)
    frozen = load_json(
        PACKET_DIR
        / "rendered"
        / run["run_id"]
        / "supplied-inputs.json"
    )
    copied: list[str] = []
    excluded: list[str] = []
    for record in frozen["visible_files"]:
        destination = str(record["destination"])
        if destination == "media/maude-source.tar":
            excluded.append(destination)
            continue
        relative = Path(destination)
        if relative.is_absolute() or ".." in relative.parts:
            raise CampaignError(
                f"{run['run_id']}: unsafe supplied snapshot path: "
                f"{destination}"
            )
        source = install_root / relative
        if (
            not source.is_file()
            or source.is_symlink()
            or source.stat().st_size != record["bytes"]
            or sha256_file(source) != record["sha256"]
        ):
            raise CampaignError(
                f"{run['run_id']}: materialized supplied input differs "
                f"before snapshot: {destination}"
            )
        destination = files_target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        copied.append(relative.as_posix())
    result = {
        "schema": "maude.synthetic-installation.operator-supplied-snapshot.v1",
        "run_id": run["run_id"],
        "installation_root": str(install_root),
        "files": inventory_files(files_target),
        "copied_destinations": copied,
        "excluded_destinations": excluded,
        "source_archive_copied_to_grade_evidence": False,
        "installed_distribution_copied_to_grade_evidence": False,
    }
    write_json(target / "inventory.json", result)
    return result


def _release_source_records(archive: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with tarfile.open(archive, "r") as handle:
        for member in handle.getmembers():
            normalized = f"/{member.name.lstrip('/')}"
            if (
                not member.isfile()
                or "/src/maude/" not in normalized
            ):
                continue
            source = handle.extractfile(member)
            if source is None:
                continue
            data = source.read()
            fingerprints: set[bytes] = set()
            if len(data) >= 32:
                for offset in range(0, len(data) - 31, 16):
                    fingerprints.add(data[offset : offset + 32])
                fingerprints.add(data[-32:])
            for line in data.splitlines():
                stripped = line.strip()
                if len(stripped) >= 16:
                    fingerprints.add(stripped)
            records.append(
                {
                    "member": member.name,
                    "bytes": len(data),
                    "sha256": sha256_bytes(data),
                    "fingerprints": sorted(fingerprints),
                }
            )
    if not records:
        raise CampaignError(
            f"release archive has no implementation members: {archive}"
        )
    return records


def _installed_source_records(install_root: Path) -> list[dict[str, Any]]:
    """Fingerprint frozen wheel modules without trusting mutable install bytes."""

    records: list[dict[str, Any]] = []
    wheels = sorted(INSTALL_WHEELHOUSE.glob("maude-*.whl"))
    if len(wheels) != 1:
        raise CampaignError(
            f"expected one frozen Maude wheel, found {len(wheels)}"
        )
    with zipfile.ZipFile(wheels[0], "r") as archive:
        for member in sorted(archive.namelist()):
            normalized = member.lstrip("/")
            if (
                not normalized.startswith("maude/")
                or not normalized.endswith(".py")
                or normalized.endswith("/")
            ):
                continue
            data = archive.read(member)
            fingerprints: set[bytes] = set()
            if len(data) >= 32:
                for offset in range(0, len(data) - 31, 16):
                    fingerprints.add(data[offset : offset + 32])
                fingerprints.add(data[-32:])
            for line in data.splitlines():
                stripped = line.strip()
                if len(stripped) >= 16:
                    fingerprints.add(stripped)
            records.append(
                {
                    "member": f"{wheels[0].name}!/{member}",
                    "bytes": len(data),
                    "sha256": sha256_bytes(data),
                    "fingerprints": sorted(fingerprints),
                }
            )
    if not records:
        raise CampaignError(
            "installed distribution has no readable Maude Python modules: "
            f"{install_root / 'venv'}"
        )
    return records


def _implementation_source_records(
    run: dict[str, Any],
    install_root: Path,
) -> list[dict[str, Any]]:
    visibility = run.get("source_visibility")
    if visibility == "release-source":
        return _release_source_records(
            install_root / "media" / "maude-source.tar"
        )
    if visibility == "installed-distribution":
        return _installed_source_records(install_root)
    return []


def _source_matches(
    data: bytes,
    source_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    digest = sha256_bytes(data)
    for record in source_records:
        exact = digest == record["sha256"]
        fingerprints = [
            fingerprint
            for fingerprint in record["fingerprints"]
            if fingerprint in data
        ]
        if exact or fingerprints:
            matches.append(
                {
                    "member": record["member"],
                    "exact_member_digest": exact,
                    "fingerprint_count": len(fingerprints),
                    "fingerprint_sha256": [
                        sha256_bytes(value) for value in fingerprints
                    ],
                }
            )
    return matches


def _capture_install_operator_generated(
    run: dict[str, Any],
    install_root: Path,
    target: Path,
) -> dict[str, Any]:
    """Preserve safe operator/work/HOME outputs without copying package state."""

    files_target = target / "files"
    files_target.mkdir(parents=True)
    source_trees: dict[str, Any] = {}
    excluded: list[dict[str, Any]] = []
    source_records = _implementation_source_records(run, install_root)
    supplied_destinations = {
        str(record["destination"])
        for record in load_json(
            PACKET_DIR
            / "rendered"
            / run["run_id"]
            / "supplied-inputs.json"
        )["visible_files"]
    }
    private_home_prefixes = {
        ".cache",
        ".config",
        ".local/share",
        ".local/state",
        "tmp",
    }
    for relative in ("operator", "work", "home"):
        source_root = install_root / relative
        source_trees[relative] = _tree_inventory(source_root)
        for source in sorted(source_root.rglob("*")):
            if source.is_symlink() or not source.is_file():
                continue
            source_relative = source.relative_to(source_root)
            installation_relative = (
                Path(relative) / source_relative
            ).as_posix()
            parts = {part.casefold() for part in source_relative.parts}
            reason: str | None = None
            source_relative_posix = source_relative.as_posix()
            operator_maude_config = (
                relative == "home"
                and (
                    source_relative_posix == ".config/maude"
                    or source_relative_posix.startswith(".config/maude/")
                )
            )
            if (
                relative == "home"
                and not operator_maude_config
                and any(
                    source_relative_posix == prefix
                    or source_relative_posix.startswith(prefix + "/")
                    for prefix in private_home_prefixes
                )
            ):
                reason = (
                    "operator HOME cache/config/state namespace; inventory "
                    "and digest preserved without copying contents"
                )
            elif installation_relative in supplied_destinations:
                reason = "frozen operator-supplied input"
            elif parts & {
                ".venv",
                "venv",
                "site-packages",
            } or any(part.endswith(".dist-info") for part in parts):
                reason = "candidate package/environment bytes"
            elif (
                run.get("source_visibility") == "release-source"
                and (
                    source.suffix.casefold() == ".py"
                    or source.name == "maude-source.tar"
                    or "src/maude" in source_relative.as_posix().casefold()
                )
            ):
                reason = "release-source-derived bytes"
            elif source.stat().st_size > 8 * 1024 * 1024:
                reason = "oversized generated artifact"
            elif source_records and _source_matches(
                source.read_bytes(),
                source_records,
            ):
                reason = "exact implementation-source content"
            if reason is not None:
                record = file_record(source, relative_to=install_root)
                record["reason"] = reason
                excluded.append(record)
                continue
            destination = (
                files_target
                / relative
                / source_relative
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    result = {
        "schema": "maude.synthetic-installation.operator-generated.v1",
        "run_id": run["run_id"],
        "source_trees": source_trees,
        "copied_regular_files": inventory_files(files_target),
        "excluded_regular_files": excluded,
        "symlinks_preserved_by_inventory_only": True,
        "installed_environment_copied": False,
        "release_source_bytes_copied": False,
        "frozen_operator_inputs_copied_as_generated": False,
        "safe_operator_home_artifacts_copied": True,
        "uncopied_home_files_individually_indexed": True,
        "home_private_namespace_prefixes": sorted(private_home_prefixes),
        "operator_maude_config_preserved": True,
        "copied_home_artifacts_source_and_secret_scanned": True,
        "authority_effect": "none",
    }
    write_json(target / "inventory.json", result)
    return result


def _materialize_installation_run(
    run: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    run_id = run["run_id"]
    lab = _lab_dir(run_id)
    install_root = _installation_root(run_id)
    operator = install_root / "operator"
    project = install_root / "project"
    evidence = _run_dir(run_id)
    if (evidence / "operator-complete.json").is_file():
        return {"run_id": run_id, "status": "skip-complete"}
    marker_path = evidence / "materialization-complete.json"
    if marker_path.is_file() and lab.is_dir():
        _materialized_supplied_inputs(run, operator, project, "")
        before_path = (
            evidence
            / "observable"
            / "installation-before"
            / "state.json"
        )
        endpoint_path = (
            evidence / "raw" / "endpoint-materialization.json"
        )
        if not before_path.is_file() or not endpoint_path.is_file():
            raise CampaignError(
                f"{run_id}: resumable installation evidence is incomplete"
            )
        before_state = load_json(before_path)
        current_trees = {
            "project_tree": _tree_inventory(project),
            "work_tree": _tree_inventory(install_root / "work"),
            "operator_tree": _tree_inventory(operator),
            "task_tree": _tree_inventory(install_root / "task"),
            "docs_tree": _tree_inventory(install_root / "docs"),
            "media_tree": _tree_inventory(install_root / "media"),
            "home_tree": _tree_inventory(install_root / "home"),
            "run_tree": _tree_inventory(install_root / "run"),
            "installed_environment_tree": _tree_inventory(
                install_root / "venv"
            ),
        }
        stale = [
            name
            for name, current in current_trees.items()
            if current["digest"]
            != before_state.get(name, {}).get("digest")
        ]
        frozen_endpoint = (
            PACKET_DIR / "installation-endpoints" / f"{run_id}.json"
        )
        endpoint_materialization = load_json(endpoint_path)
        endpoint_record = endpoint_materialization.get("endpoint_plan")
        if (
            stale
            or not isinstance(endpoint_record, dict)
            or endpoint_record.get("sha256")
            != sha256_file(frozen_endpoint)
        ):
            raise CampaignError(
                f"{run_id}: stale materialized installation lab; "
                f"changed_trees={stale!r}"
            )
        return {
            "run_id": run_id,
            "status": "already-materialized",
            **load_json(marker_path),
        }
    if (evidence / "transcript.jsonl").exists():
        raise CampaignError(
            f"{run_id}: incomplete raw evidence exists; refusing to overwrite it"
        )
    if evidence.exists() and any(evidence.iterdir()):
        archived = (
            CAMPAIGN_DIR
            / "_incomplete-pre-session"
            / f"{run_id}-{uuid.uuid4().hex}"
        )
        archived.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(evidence), archived)
    _safe_remove_lab(lab)
    for path in (
        operator,
        install_root / "task",
        install_root / "docs",
        install_root / "home",
        install_root / "work",
        install_root / "run",
        install_root / "run" / "xdg",
        project,
        install_root / "media",
        lab / "private-install",
    ):
        path.mkdir(parents=True, exist_ok=True)
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "raw").mkdir()
    (evidence / "observable").mkdir()

    for source, target in _scenario_visible_files(run):
        _copy_file(
            source,
            target,
            executable=bool(source.stat().st_mode & 0o111),
        )

    scenario = SCENARIOS_DIR / run["scenario_id"]
    if run_id == "install-i02":
        (project / ".governor").mkdir()
    setup = _materialize_installed_distribution(
        run,
        install_root,
        evidence,
    )
    plan_path = (
        PACKET_DIR / "installation-endpoints" / f"{run_id}.json"
    )
    if not plan_path.is_file():
        raise CampaignError(
            f"{run_id}: frozen installation endpoint plan is absent"
        )
    endpoint_plan = load_json(plan_path)
    if (
        endpoint_plan.get("schema")
        != "maude.synthetic-installation-endpoint-plan.v1"
        or endpoint_plan.get("campaign_id") != CAMPAIGN_ID
        or endpoint_plan.get("run_id") != run_id
        or endpoint_plan.get("task_id") != run.get("task_id")
        or endpoint_plan.get("authority_effect") != "none"
    ):
        raise CampaignError(f"{run_id}: endpoint plan identity mismatch")
    _copy_file(
        plan_path,
        lab / "private-install" / "endpoint-plan.json",
    )
    task = load_json(scenario / "task.json")
    socket_strategy = endpoint_plan["socket_strategy"]
    if socket_strategy == "task_handoff":
        socket_path = Path(str(task["handoff"]["governor_socket"]))
    elif socket_strategy == "default_governor_dir":
        governor_dir = (project / ".governor").resolve()
        runtime_dir = (install_root / "run" / "xdg").resolve()
        digest = sha256_bytes(str(governor_dir).encode("utf-8"))[:12]
        socket_path = runtime_dir / f"governor-{digest}.sock"
    elif socket_strategy == "none":
        socket_path = None
    else:
        raise CampaignError(
            f"{run_id}: unknown endpoint socket strategy {socket_strategy!r}"
        )
    if socket_path is not None:
        socket_path = socket_path.resolve()
        if install_root.resolve() not in socket_path.parents:
            raise CampaignError(
                f"{run_id}: endpoint socket escapes installation lab"
            )
        socket_path.parent.mkdir(parents=True, exist_ok=True)

    endpoint_materialization: dict[str, Any] = {
        **endpoint_plan,
        "resolved_socket": str(socket_path) if socket_path else None,
        "endpoint_plan": file_record(plan_path),
    }
    if endpoint_plan["mode"] == "compatible":
        runtime_config = {
            "schema": "maude.synthetic-runtime.v1",
            "scenario_id": run["task_id"],
            "workspace": {
                "path": str(project),
                "base_files": {},
            },
            "governor": {
                "context_id": "synthetic-installation-lab",
                "initialized": True,
                "mode": "code",
                "pill": "OK",
                "sentence": (
                    "Synthetic installation fixture; authority effect none."
                ),
            },
            "runtime": {"behavior": "normal", "timeout_seconds": None},
        }
        runtime_config_path = lab / "private-install" / "runtime.json"
        write_json(runtime_config_path, runtime_config)
        endpoint_materialization["runtime_config"] = file_record(
            runtime_config_path,
            relative_to=lab,
        )
    write_json(
        evidence / "raw" / "endpoint-materialization.json",
        endpoint_materialization,
    )

    before = _capture_installation_state(
        run,
        install_root,
        evidence / "observable" / "installation-before",
        label="before",
        allowed_socket=socket_path,
    )
    _capture_install_operator_supplied(
        run,
        install_root,
        evidence / "observable" / "operator-supplied",
    )
    supplied = _materialized_supplied_inputs(
        run,
        operator,
        project,
        "",
    )
    write_json(evidence / "supplied-inputs.json", supplied)
    _copy_file(
        PACKET_DIR / "rendered" / run_id / "operator-prompt.md",
        evidence / "operator-prompt.md",
    )
    _copy_file(
        PACKET_DIR / "rendered" / run_id / "operator-system.md",
        evidence / "operator-system-prompt.md",
    )
    result = {
        "run_id": run_id,
        "status": "materialized",
        "lab": str(lab),
        "operator": str(operator),
        "repo": str(project),
        "installation_root": str(install_root),
        "base_commit": "",
        "before_inventory_sha256": sha256_file(
            evidence / "observable" / "installation-before" / "state.json"
        ),
        "setup_transcript_withheld": True,
        "installed_distribution_materialized": setup is not None,
        "endpoint_mode": endpoint_plan["mode"],
        "endpoint_socket": str(socket_path) if socket_path else None,
        "project_tree_digest_before": before["project_tree"]["digest"],
    }
    write_json(
        marker_path,
        {
            "schema": "maude.synthetic-operator.materialization-complete.v1",
            **result,
        },
    )
    return result


def materialize_run(run: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    if run["surface"] == "maude-installation":
        return _materialize_installation_run(run, manifest)
    run_id = run["run_id"]
    lab = _lab_dir(run_id)
    evidence = _run_dir(run_id)
    if (evidence / "operator-complete.json").is_file():
        return {"run_id": run_id, "status": "skip-complete"}
    materialization_marker = evidence / "materialization-complete.json"
    if materialization_marker.is_file() and lab.is_dir():
        marker = load_json(materialization_marker)
        operator = lab / "operator"
        repo = lab / "repo"
        _materialized_supplied_inputs(
            run,
            operator,
            repo,
            str(marker.get("base_commit", "")),
        )
        current_lab_digest = _tree_inventory(lab)["digest"]
        if marker.get("lab_tree_digest") != current_lab_digest:
            raise CampaignError(
                f"{run_id}: stale materialized lab differs from its marker"
            )
        return {
            "run_id": run_id,
            "status": "already-materialized",
            **marker,
        }
    if (evidence / "transcript.jsonl").exists():
        raise CampaignError(
            f"{run_id}: incomplete raw evidence exists; refusing to overwrite it"
        )
    if evidence.exists() and any(evidence.iterdir()):
        archived = (
            CAMPAIGN_DIR
            / "_incomplete-pre-session"
            / f"{run_id}-{uuid.uuid4().hex}"
        )
        archived.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(evidence), archived)
    _safe_remove_lab(lab)
    lab.mkdir(parents=True)
    operator = lab / "operator"
    operator.mkdir()
    (operator / "task").mkdir()
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "raw").mkdir(exist_ok=True)
    (evidence / "observable").mkdir(exist_ok=True)

    for source, target in _scenario_visible_files(run):
        _copy_file(
            source,
            target,
            executable=bool(source.stat().st_mode & 0o111),
        )

    scenario = SCENARIOS_DIR / run["scenario_id"]
    if run["surface"] == "maude":
        repo = lab / "repo"
        _copy_tree(scenario / "fixture", repo)
        base_commit = _git_init_synthetic(repo, run)
        _copy_file(HARNESS_DIR / "maude", operator / "maude", executable=True)
        _copy_file(HARNESS_DIR / "public_cli.py", operator / "public_cli.py")
        for name in ("commands.md", "configuration.md"):
            _copy_file(
                PACKET_DIR / "operator-docs" / name,
                operator / "docs" / name,
            )
        private = lab / "private"
        (private / "control").mkdir(parents=True)
        (private / "public-cli").mkdir()
        runtime_config = private / "runtime.json"
        _copy_file(scenario / "runtime.json", runtime_config)
        configured = load_json(runtime_config)
        expected_workspace = str(repo)
        actual_workspace = configured.get("workspace", {}).get("path")
        if actual_workspace != expected_workspace:
            raise CampaignError(
                f"{run_id}: runtime workspace {actual_workspace!r} != "
                f"{expected_workspace!r}"
            )
        setup_private = None
    else:
        fixture = (
            PACKET_DIR
            / "direct-runtime"
            / "fixtures"
            / f"{run_id}.tar"
        )
        frozen = _manifest_run(run_id, manifest)["direct_runtime_fixture"]
        if (
            fixture.stat().st_size != frozen["archive_bytes"]
            or sha256_file(fixture) != frozen["archive_sha256"]
        ):
            raise CampaignError(f"{run_id}: direct fixture archive digest mismatch")
        _safe_remove_lab(lab)
        _extract_tar_safely(fixture, LAB_ROOT, run_id)
        lab = _lab_dir(run_id)
        operator = lab / "operator"
        operator.mkdir()
        (operator / "task").mkdir()
        for source, target in _scenario_visible_files(run):
            _copy_file(
                source,
                target,
                executable=bool(source.stat().st_mode & 0o111),
            )
        direct = PACKET_DIR / "direct-runtime"
        _copy_file(direct / "bin" / "docket", operator / "bin" / "docket", executable=True)
        _copy_file(
            direct / "bin" / "gwr-git-broker",
            operator / "bin" / "gwr-git-broker",
            executable=True,
        )
        for path in sorted((direct / "docs").glob("*.md")):
            _copy_file(path, operator / "docs" / path.name)
        setup_private = lab / "setup-transcript.jsonl"
        if setup_private.is_file():
            _copy_file(
                setup_private,
                evidence / "raw" / "direct-fixture-setup-transcript.jsonl",
            )
            setup_private.unlink()
        if setup_private.exists():
            raise CampaignError(f"{run_id}: setup transcript was not withheld")
        repo = lab / "repo"
        control = load_json(operator / "control.json")
        base_commit = str(control["basis_commit"])
        basis_check = _command(
            ["git", "cat-file", "-e", f"{base_commit}^{{commit}}"],
            cwd=repo,
            expected=None,
        )
        if basis_check["returncode"] != 0:
            raise CampaignError(f"{run_id}: frozen Docket basis commit is absent")

    _capture_repo(
        repo, evidence / "observable" / "repository-before", label="before"
    )
    _capture_operator_supplied(
        operator, evidence / "observable" / "operator-supplied"
    )
    supplied = _materialized_supplied_inputs(run, operator, repo, base_commit)
    write_json(evidence / "supplied-inputs.json", supplied)
    _copy_file(
        PACKET_DIR / "rendered" / run_id / "operator-prompt.md",
        evidence / "operator-prompt.md",
    )
    _copy_file(
        PACKET_DIR / "rendered" / run_id / "operator-system.md",
        evidence / "operator-system-prompt.md",
    )
    result = {
        "run_id": run_id,
        "status": "materialized",
        "lab": str(lab),
        "operator": str(operator),
        "repo": str(repo),
        "base_commit": base_commit,
        "before_inventory_sha256": sha256_file(
            evidence / "observable" / "repository-before" / "inventory.json"
        ),
        "setup_transcript_withheld": setup_private is None or not setup_private.exists(),
        "lab_tree_digest": _tree_inventory(lab)["digest"],
    }
    write_json(
        materialization_marker,
        {
            "schema": "maude.synthetic-operator.materialization-complete.v1",
            **result,
        },
    )
    return result


def _installation_static_visible_paths(install_root: Path) -> set[str]:
    generated_roots = {"work", "home", "run", "venv"}
    actual_static: set[str] = set()
    for path in sorted(install_root.rglob("*")):
        relative = path.relative_to(install_root)
        if not relative.parts or relative.parts[0] in generated_roots:
            continue
        if path.is_symlink():
            raise CampaignError(
                f"undeclared static symlink is visible: {relative}"
            )
        if path.is_file():
            actual_static.add(relative.as_posix())
        elif not path.is_dir():
            raise CampaignError(
                f"undeclared static special path is visible: {relative}"
            )
    return actual_static


def _materialized_supplied_inputs(
    run: dict[str, Any], operator: Path, repo: Path, base_commit: str
) -> dict[str, Any]:
    rendered = load_json(
        PACKET_DIR / "rendered" / run["run_id"] / "supplied-inputs.json"
    )
    if run["surface"] == "maude-installation":
        install_root = operator.parent
        visible = []
        expected_destinations: set[str] = set()
        for expected in rendered["visible_files"]:
            destination = Path(str(expected["destination"]))
            expected_destinations.add(destination.as_posix())
            path = install_root / destination
            if (
                not path.is_file()
                or path.is_symlink()
                or path.stat().st_size != expected["bytes"]
                or sha256_file(path) != expected["sha256"]
            ):
                raise CampaignError(
                    f"{run['run_id']}: materialized installation input "
                    f"missing or changed: {destination}"
                )
            visible.append(file_record(path, relative_to=install_root))
        actual_static = _installation_static_visible_paths(install_root)
        if actual_static != expected_destinations:
            raise CampaignError(
                f"{run['run_id']}: installation static visible-file set "
                "differs from frozen inputs: "
                f"missing={sorted(expected_destinations - actual_static)!r} "
                f"extra={sorted(actual_static - expected_destinations)!r}"
            )
        repo_files: list[dict[str, Any]] = []
        operator_root = install_root
    else:
        visible = inventory_files(operator)
        repo_files = [
            record
            for record in inventory_files(repo, exclude_names={".git"})
        ]
        operator_root = operator
    return {
        "schema": "maude.synthetic-operator.materialized-supplied-inputs.v1",
        "campaign_id": CAMPAIGN_ID,
        "run_id": run["run_id"],
        "surface": run["surface"],
        "operator_root": str(operator_root),
        "operator_visible_files": visible,
        "repository_root": str(repo),
        "repository_base_commit": base_commit,
        "repository_files": repo_files,
        "system_prompt": rendered["system_prompt"],
        "user_prompt": rendered["user_prompt"],
        "inventory_scope": (
            "exact regular files visible at session start; generated "
            "installation environment is captured separately as observable "
            "package and filesystem state"
        ),
    }


class ManagedProcess:
    def __init__(
        self,
        argv: list[str],
        *,
        cwd: Path,
        stdout_path: Path,
        stderr_path: Path,
        env: dict[str, str] | None = None,
    ) -> None:
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stderr_path.parent.mkdir(parents=True, exist_ok=True)
        self.stdout_handle = stdout_path.open("wb")
        self.stderr_handle = stderr_path.open("wb")
        self.process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=self.stdout_handle,
            stderr=self.stderr_handle,
            start_new_session=True,
        )

    def _close_output_handles(self) -> None:
        if not self.stdout_handle.closed:
            self.stdout_handle.close()
        if not self.stderr_handle.closed:
            self.stderr_handle.close()

    def wait(self, *, timeout: float = 5.0) -> int:
        returncode = self.process.wait(timeout=timeout)
        self._close_output_handles()
        return int(returncode or 0)

    def stop(self, *, grace: float = 5.0) -> int:
        if self.process.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(self.process.pid, signal.SIGTERM)
            try:
                return self.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(self.process.pid, signal.SIGKILL)
                return self.wait(timeout=grace)
        self._close_output_handles()
        return int(self.process.returncode or 0)


def _wait_ready(path: Path, process: ManagedProcess, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file():
            return
        if process.process.poll() is not None:
            raise CampaignError(
                f"process exited before readiness file {path}: "
                f"{process.process.returncode}"
            )
        time.sleep(0.05)
    raise CampaignError(f"timed out waiting for readiness file: {path}")


def _copy_provider_home(config_id: str, target: Path) -> tuple[list[str], list[bytes]]:
    target.mkdir(parents=True, mode=0o700)
    pairs = CLAUDE_AUTH_FILES if config_id == "anthropic-sonnet" else CODEX_AUTH_FILES
    copied: list[str] = []
    tokens: list[bytes] = []
    for source, relative in pairs:
        if not source.is_file():
            raise CampaignError(f"required provider auth/config file absent: {source}")
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        destination.chmod(0o600)
        copied.append(str(relative))
        tokens.extend(_credential_values(source.read_bytes()))
    return copied, tokens


def _credential_values(data: bytes) -> list[bytes]:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        stripped = data.strip()
        return [stripped] if len(stripped) >= 12 else []
    found: list[bytes] = []

    def walk(item: Any, key: str = "") -> None:
        if isinstance(item, dict):
            for child_key, child in item.items():
                walk(child, str(child_key))
        elif isinstance(item, list):
            for child in item:
                walk(child, key)
        elif (
            isinstance(item, str)
            and len(item) >= 12
            and re.search(
                r"token|secret|key|credential|authorization|access|refresh",
                key,
                re.IGNORECASE,
            )
        ):
            found.append(item.encode("utf-8"))

    walk(value)
    return found


def _prepare_clean_operator_home(path: Path) -> None:
    """Create a deliberately empty, writable HOME for a fresh model session.

    Provider transport credentials live at a separate read-only mount.  This
    HOME is therefore also the HOME inherited by model-initiated shell tools,
    which prevents clean-room installation specimens from inheriting the
    evaluator's home, caches, package configuration, or editable-install state.
    """
    expected_directories = (
        ".cache",
        ".config",
        ".local",
        ".local/share",
        ".local/state",
        "tmp",
    )
    if path.exists() and any(path.iterdir()):
        actual_directories: set[str] = set()
        unexpected: list[str] = []
        for candidate in sorted(path.rglob("*")):
            relative = str(candidate.relative_to(path))
            if candidate.is_dir() and not candidate.is_symlink():
                actual_directories.add(relative)
            else:
                unexpected.append(relative)
        if (
            actual_directories != set(expected_directories)
            or unexpected
        ):
            raise CampaignError(
                "fresh operator HOME differs from the canonical empty "
                f"directory skeleton: {path}: directories="
                f"{sorted(actual_directories)!r} unexpected={unexpected!r}"
            )
    else:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
    for relative in expected_directories:
        (path / relative).mkdir(parents=True, exist_ok=True)


def _operator_home_inventory(path: Path) -> dict[str, Any]:
    """Inventory clean-room HOME state without copying its file contents."""
    symlinks: list[dict[str, str]] = []
    directories: list[str] = []
    for candidate in sorted(path.rglob("*")):
        relative = str(candidate.relative_to(path))
        if candidate.is_symlink():
            symlinks.append(
                {"path": relative, "target": os.readlink(candidate)}
            )
        elif candidate.is_dir():
            directories.append(relative)
    return {
        "schema": "maude.synthetic-operator.clean-home-inventory.v1",
        "mount_path": str(OPERATOR_HOME_MOUNT),
        "files": inventory_files(path),
        "symlinks": symlinks,
        "directories": directories,
    }


def _prepare_cleanroom_os() -> dict[str, Path]:
    """Build the minimal deterministic host-configuration view for bwrap."""

    clean_etc = CLEANROOM_OS_ROOT / "etc"
    empty_dir = CLEANROOM_OS_ROOT / "empty"
    masked_file = CLEANROOM_OS_ROOT / "masked"
    for path in (clean_etc / "ssl" / "certs", empty_dir):
        path.mkdir(parents=True, exist_ok=True)
    for path in (
        clean_etc / "ssl" / "openssl.cnf",
        clean_etc / "ld.so.cache",
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.touch()
    uid = os.getuid()
    gid = os.getgid()
    files = {
        "passwd": (
            "root:x:0:0:root:/root:/bin/sh\n"
            f"operator:x:{uid}:{gid}:Synthetic operator:/home/operator:/bin/sh\n"
            "nobody:x:65534:65534:nobody:/nonexistent:/usr/sbin/nologin\n"
        ),
        "group": (
            "root:x:0:\n"
            f"operator:x:{gid}:\n"
            "nogroup:x:65534:\n"
        ),
        "hosts": "127.0.0.1 localhost\n::1 localhost\n",
        "nsswitch.conf": (
            "passwd: files\n"
            "group: files\n"
            "shadow: files\n"
            "hosts: files dns\n"
        ),
        "resolv.conf": (
            "nameserver 127.0.0.53\n"
            "options edns0 trust-ad\n"
            "search .\n"
        ),
    }
    for name, contents in files.items():
        path = clean_etc / name
        encoded = contents.encode("utf-8")
        if path.exists() and path.read_bytes() != encoded:
            raise CampaignError(
                f"clean-room OS substrate differs at {path}"
            )
        if not path.exists():
            write_text(path, contents)
    if masked_file.exists() and masked_file.stat().st_size != 0:
        raise CampaignError("clean-room masked-file sentinel differs")
    if not masked_file.exists():
        masked_file.touch(mode=0o444)
    # Bubblewrap must be able to open the bind source, while the lack of an
    # execute bit still prevents the sentinel from acting as a host binary.
    masked_file.chmod(0o444)
    return {
        "etc": clean_etc,
        "empty": empty_dir,
        "masked": masked_file,
    }


def _bwrap_base(
    provider: str, provider_home: Path, operator_home: Path
) -> list[str]:
    if provider == "anthropic-sonnet":
        raise CampaignError(
            "Claude may not use the provider/task combined bubblewrap; use "
            "the fixed MCP proxy and disposable command broker"
        )
    _prepare_clean_operator_home(operator_home)
    cleanroom_os = _prepare_cleanroom_os()
    argv = [
        str(BWRAP),
        "--die-with-parent",
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",
        "--clearenv",
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
        str(cleanroom_os["etc"]),
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
        str(cleanroom_os["masked"]),
        "/usr/bin/maude",
        "--ro-bind",
        str(cleanroom_os["masked"]),
        "/bin/maude",
        "--ro-bind",
        str(cleanroom_os["empty"]),
        "/usr/share/maude",
        "--ro-bind",
        str(cleanroom_os["empty"]),
        "/usr/share/doc/maude",
        "--ro-bind",
        str(cleanroom_os["masked"]),
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
        "/run/systemd",
        "--ro-bind",
        "/run/systemd/resolve",
        "/run/systemd/resolve",
        "--dir",
        "/home",
        "--dir",
        str(OPERATOR_HOME_MOUNT),
        "--bind",
        str(operator_home),
        str(OPERATOR_HOME_MOUNT),
        "--dir",
        str(PROVIDER_AUTH_MOUNT),
        "--bind",
        str(provider_home),
        str(PROVIDER_AUTH_MOUNT),
        "--dir",
        "/opt",
        "--setenv",
        "HOME",
        str(OPERATOR_HOME_MOUNT),
        "--setenv",
        "XDG_CONFIG_HOME",
        str(OPERATOR_HOME_MOUNT / ".config"),
        "--setenv",
        "XDG_CACHE_HOME",
        str(OPERATOR_HOME_MOUNT / ".cache"),
        "--setenv",
        "XDG_DATA_HOME",
        str(OPERATOR_HOME_MOUNT / ".local/share"),
        "--setenv",
        "XDG_STATE_HOME",
        str(OPERATOR_HOME_MOUNT / ".local/state"),
        "--setenv",
        "PIP_CACHE_DIR",
        str(OPERATOR_HOME_MOUNT / ".cache/pip"),
        "--setenv",
        "PIP_CONFIG_FILE",
        "/dev/null",
        "--setenv",
        "TMPDIR",
        str(OPERATOR_HOME_MOUNT / "tmp"),
        "--setenv",
        "USER",
        "operator",
        "--setenv",
        "LANG",
        "C.UTF-8",
        "--setenv",
        "LC_ALL",
        "C.UTF-8",
        "--setenv",
        "TERM",
        "dumb",
        "--setenv",
        "NO_COLOR",
        "1",
        "--setenv",
        "PYTHONDONTWRITEBYTECODE",
        "1",
        "--setenv",
        "PYTHONNOUSERSITE",
        "1",
        "--setenv",
        "GIT_CONFIG_NOSYSTEM",
        "1",
        "--setenv",
        "GIT_CONFIG_GLOBAL",
        "/dev/null",
    ]
    argv.extend(
        [
            "--setenv",
            "CODEX_HOME",
            str(PROVIDER_AUTH_MOUNT / ".codex"),
            "--ro-bind",
            str(CODEX_HOST_ROOT),
            "/opt/node",
            "--setenv",
            "PATH",
            "/opt/node/bin:/usr/bin:/bin",
        ]
    )
    return argv


def _bwrap_for_operator(
    run: dict[str, Any],
    provider_home: Path,
    *,
    public_cli_socket: Path | None = None,
) -> tuple[list[str], Path, Path]:
    lab = _lab_dir(run["run_id"])
    is_installation = run["surface"] == "maude-installation"
    install_root = lab / "installation"
    operator = (
        install_root / "operator" if is_installation else lab / "operator"
    )
    repo = install_root / "project" if is_installation else lab / "repo"
    operator_home = (
        install_root / "home"
        if is_installation
        else lab / "private-operator-home"
    )
    argv = _bwrap_base(
        run["operator_model_config"], provider_home, operator_home
    )
    argv.extend(["--dir", str(LAB_ROOT), "--dir", str(lab)])
    if is_installation:
        argv.extend(
            [
                "--ro-bind",
                str(install_root),
                str(install_root),
                "--bind",
                str(operator),
                str(operator),
                "--ro-bind",
                str(install_root / "task"),
                str(install_root / "task"),
                "--ro-bind",
                str(install_root / "docs"),
                str(install_root / "docs"),
                "--ro-bind",
                str(install_root / "README.md"),
                str(install_root / "README.md"),
                "--ro-bind",
                str(install_root / "pyproject.toml"),
                str(install_root / "pyproject.toml"),
                "--bind",
                str(install_root / "work"),
                str(install_root / "work"),
                "--bind",
                str(operator_home),
                str(install_root / "home"),
                "--ro-bind",
                str(repo),
                str(repo),
                "--ro-bind",
                str(install_root / "run"),
                str(install_root / "run"),
                "--setenv",
                "XDG_RUNTIME_DIR",
                str(install_root / "run" / "xdg"),
                "--setenv",
                "TERM",
                "xterm-256color",
            ]
        )
        media = install_root / "media"
        if any(media.iterdir()):
            argv.extend(["--ro-bind", str(media), str(media)])
        venv = install_root / "venv"
        if venv.is_dir():
            argv.extend(
                [
                    "--bind",
                    str(venv),
                    str(venv),
                ]
            )
    else:
        argv.extend(["--ro-bind", str(operator), str(operator)])
    if run["surface"] == "maude":
        if public_cli_socket is None or not stat.S_ISSOCK(
            public_cli_socket.stat().st_mode
        ):
            raise CampaignError("Maude public-CLI broker socket is unavailable")
        argv.extend(
            [
                "--ro-bind",
                str(repo),
                str(repo),
                "--dir",
                str(PUBLIC_CLI_SOCKET_MOUNT.parent),
                "--ro-bind",
                str(public_cli_socket),
                str(PUBLIC_CLI_SOCKET_MOUNT),
                "--setenv",
                "MAUDE_PUBLIC_SOCKET",
                str(PUBLIC_CLI_SOCKET_MOUNT),
            ]
        )
    elif run["surface"] == "docket-gwr-direct":
        state = lab / "state"
        candidate = lab / "candidate.patch"
        argv.extend(
            [
                "--bind",
                str(repo),
                str(repo),
                "--bind",
                str(state),
                str(state),
            ]
        )
        if candidate.is_file():
            argv.extend(["--ro-bind", str(candidate), str(candidate)])
        argv.extend(
            [
                "--setenv",
                "GWR_BROKER_BIN",
                str(operator / "bin" / "gwr-git-broker"),
            ]
        )
    argv.extend(["--chdir", str(operator)])
    return argv, operator, operator_home


def _bwrap_for_grade(
    provider: str, provider_home: Path, bundle: Path
) -> tuple[list[str], Path]:
    operator_home = bundle.parent / "private-grader-home"
    argv = _bwrap_base(provider, provider_home, operator_home)
    argv.extend(
        [
            "--dir",
            str(LAB_ROOT),
            "--ro-bind",
            str(bundle),
            str(bundle),
            "--chdir",
            str(bundle),
        ]
    )
    return argv, operator_home


def _claude_clean_environment(home: Path) -> dict[str, str]:
    """Return the exact non-secret environment shared by cleanroom commands."""

    return {
        "HOME": str(OPERATOR_HOME_MOUNT),
        "XDG_CONFIG_HOME": str(OPERATOR_HOME_MOUNT / ".config"),
        "XDG_CACHE_HOME": str(OPERATOR_HOME_MOUNT / ".cache"),
        "XDG_DATA_HOME": str(OPERATOR_HOME_MOUNT / ".local/share"),
        "XDG_STATE_HOME": str(OPERATOR_HOME_MOUNT / ".local/state"),
        "PIP_CACHE_DIR": str(OPERATOR_HOME_MOUNT / ".cache/pip"),
        "PIP_CONFIG_FILE": "/dev/null",
        "TMPDIR": str(OPERATOR_HOME_MOUNT / "tmp"),
        "USER": "operator",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TERM": "dumb",
        "NO_COLOR": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "PATH": "/usr/bin:/bin",
    }


def _claude_transport_environment(provider_home: Path) -> dict[str, str]:
    """Give Claude transport auth without inheriting evaluator/task state."""

    transport_tmp = provider_home / "tmp"
    for path in (
        provider_home / ".cache",
        provider_home / ".config",
        provider_home / ".local" / "share",
        transport_tmp,
    ):
        path.mkdir(parents=True, exist_ok=True)
    environment = {
        "HOME": str(provider_home),
        "CLAUDE_CONFIG_DIR": str(provider_home / ".claude"),
        "XDG_CONFIG_HOME": str(provider_home / ".config"),
        "XDG_CACHE_HOME": str(provider_home / ".cache"),
        "XDG_DATA_HOME": str(provider_home / ".local/share"),
        "TMPDIR": str(transport_tmp),
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TERM": "dumb",
        "NO_COLOR": "1",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    }
    # Provider transport can require the evaluator's explicitly configured
    # proxy/CA route.  No general environment or task variable is inherited.
    for name in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "NODE_EXTRA_CA_CERTS",
    ):
        value = os.environ.get(name)
        if value:
            environment[name] = value
    return environment


def _claude_proxy_bwrap(
    *,
    bridge: Path,
    private_state: Path,
    mode: str,
    command_socket_directory: Path | None = None,
    grader_bundle: Path | None = None,
) -> list[str]:
    """Build the model-facing auth/source-free MCP proxy namespace."""

    cleanroom_os = _prepare_cleanroom_os()
    argv = [
        str(BWRAP),
        "--die-with-parent",
        "--unshare-pid",
        "--unshare-net",
        "--unshare-ipc",
        "--unshare-uts",
        "--unshare-cgroup-try",
        "--clearenv",
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
        str(cleanroom_os["etc"]),
        "/etc",
        "--ro-bind",
        str(cleanroom_os["masked"]),
        "/usr/bin/maude",
        "--ro-bind",
        str(cleanroom_os["masked"]),
        "/bin/maude",
        "--ro-bind",
        str(cleanroom_os["empty"]),
        "/usr/share/maude",
        "--ro-bind",
        str(cleanroom_os["empty"]),
        "/usr/share/doc/maude",
        "--ro-bind",
        str(cleanroom_os["masked"]),
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
        str(CLAUDE_MCP_PRIVATE_MOUNT),
        "--bind",
        str(private_state),
        str(CLAUDE_MCP_PRIVATE_MOUNT),
        "--dir",
        "/home",
        "--dir",
        "/home/mcp",
        "--dir",
        "/opt",
        "--dir",
        "/opt/maude-eval",
        "--ro-bind",
        str(bridge),
        str(CLAUDE_MCP_BRIDGE_MOUNT),
        "--setenv",
        "HOME",
        "/home/mcp",
        "--setenv",
        "TMPDIR",
        "/tmp",
        "--setenv",
        "PATH",
        "/usr/bin:/bin",
        "--setenv",
        "LANG",
        "C.UTF-8",
        "--setenv",
        "LC_ALL",
        "C.UTF-8",
        "--setenv",
        "PYTHONDONTWRITEBYTECODE",
        "1",
        "--setenv",
        "PYTHONNOUSERSITE",
        "1",
    ]
    if mode == "operator":
        if (
            command_socket_directory is None
            or not command_socket_directory.is_dir()
            or command_socket_directory.is_symlink()
        ):
            raise CampaignError(
                "Claude operator proxy has no private short socket arena"
            )
        argv.extend(
            [
                "--dir",
                str(CLAUDE_COMMAND_SOCKET_MOUNT.parent),
                "--ro-bind",
                str(command_socket_directory),
                str(CLAUDE_COMMAND_SOCKET_MOUNT.parent),
            ]
        )
    elif command_socket_directory is not None:
        raise CampaignError("Claude grader must not receive a command socket")
    if mode == "grader":
        if grader_bundle is None:
            raise CampaignError("Claude grader proxy has no staged bundle")
        argv.extend(
            [
                "--dir",
                "/evidence",
                "--ro-bind",
                str(grader_bundle),
                "/evidence",
            ]
        )
    argv.extend(["--chdir", "/home/mcp"])
    return argv


def _surface_mount_policy(
    run: dict[str, Any],
    operator_home: Path,
    *,
    endpoint_socket: Path | None = None,
    public_cli_socket: Path | None = None,
) -> tuple[Path, list[dict[str, str]], list[dict[str, str]], dict[str, str]]:
    """Describe exactly what each disposable terminal namespace may see."""

    lab = _lab_dir(run["run_id"])
    installation = run["surface"] == "maude-installation"
    install_root = lab / "installation"
    operator = install_root / "operator" if installation else lab / "operator"
    repo = install_root / "project" if installation else lab / "repo"
    mounts: list[dict[str, str]] = []
    sockets: list[dict[str, str]] = []
    environment = _claude_clean_environment(operator_home)

    def mount(source: Path, mode: str, target: Path | None = None) -> None:
        mounts.append(
            {
                "source": str(source),
                "target": str(target or source),
                "mode": mode,
            }
        )

    if installation:
        for visible_root in (
            install_root / "README.md",
            install_root / "docs",
            install_root / "pyproject.toml",
            install_root / "task",
            install_root / "media",
        ):
            if visible_root.exists():
                mount(visible_root, "ro")
        mount(operator, "rw")
        mount(install_root / "work", "rw")
        mount(operator_home, "rw", OPERATOR_HOME_MOUNT)
        mount(operator_home, "rw")
        mount(repo, "ro")
        mount(install_root / "venv", "rw")
        xdg_runtime = install_root / "run" / "xdg"
        mount(xdg_runtime, "rw")
        environment["XDG_RUNTIME_DIR"] = str(xdg_runtime)
        environment["TERM"] = "xterm-256color"
    else:
        mount(operator, "ro")
        mount(operator_home, "rw", OPERATOR_HOME_MOUNT)
    if run["surface"] == "maude":
        mount(repo, "ro")
        if public_cli_socket is not None:
            _checked_unix_socket_path(
                public_cli_socket,
                label=f"{run['run_id']} public-CLI broker host",
            )
        _checked_unix_socket_path(
            PUBLIC_CLI_SOCKET_MOUNT,
            label=f"{run['run_id']} public-CLI client",
        )
        if public_cli_socket is None or not stat.S_ISSOCK(
            public_cli_socket.stat().st_mode
        ):
            raise CampaignError("Maude public-CLI broker socket is unavailable")
        sockets.append(
            {
                "source": str(public_cli_socket),
                "target": str(PUBLIC_CLI_SOCKET_MOUNT),
            }
        )
        environment["MAUDE_PUBLIC_SOCKET"] = str(PUBLIC_CLI_SOCKET_MOUNT)
    elif run["surface"] == "docket-gwr-direct":
        mount(repo, "rw")
        state_root = lab / "state"
        mount(state_root, "rw")
        candidate = lab / "candidate.patch"
        if candidate.is_file():
            mount(candidate, "ro")
        environment["GWR_BROKER_BIN"] = str(
            operator / "bin" / "gwr-git-broker"
        )
    if endpoint_socket is not None:
        _checked_unix_socket_path(
            endpoint_socket,
            label=f"{run['run_id']} installation endpoint",
        )
        sockets.append(
            {"source": str(endpoint_socket), "target": str(endpoint_socket)}
        )
        environment["GOVERNOR_SOCKET"] = str(endpoint_socket)
    return operator, mounts, sockets, environment


def _stage_claude_boundary_file(
    private_state: Path, source: Path, name: str
) -> Path:
    target = private_state / "staged" / name
    _copy_file(source, target, executable=False)
    if sha256_file(target) != sha256_file(source):
        raise CampaignError(f"staged Claude boundary file changed: {source}")
    return target


def _build_claude_boundary(
    *,
    label: str,
    lab: Path,
    mode: str,
    provider_home: Path,
    cwd: Path,
    operator_home: Path | None = None,
    mounts: list[dict[str, str]] | None = None,
    sockets: list[dict[str, str]] | None = None,
    environment: dict[str, str] | None = None,
    grader_bundle: Path | None = None,
    pty_adapter: Path | None = None,
) -> dict[str, Any]:
    """Freeze one per-session Claude proxy/broker boundary under the lab."""

    if mode not in {"operator", "grader"}:
        raise CampaignError(f"unsupported Claude MCP mode: {mode}")
    for index, mounted_socket in enumerate(sockets or [], 1):
        if set(mounted_socket) != {"source", "target"}:
            raise CampaignError(
                f"{label}: declared socket {index} has non-exact fields"
            )
        _checked_unix_socket_path(
            Path(mounted_socket["source"]),
            label=f"{label} declared socket {index} source",
        )
        _checked_unix_socket_path(
            Path(mounted_socket["target"]),
            label=f"{label} declared socket {index} target",
        )
    private_state = lab / f"private-claude-mcp-{label}"
    if private_state.exists():
        raise CampaignError(
            f"refusing to reuse Claude MCP private state: {private_state}"
        )
    private_state.mkdir(parents=True, mode=0o700)
    bridge = _stage_claude_boundary_file(
        private_state, CLAUDE_MCP_BRIDGE_SOURCE, "claude_mcp_bridge.py"
    )
    transport_cwd = private_state / "transport-cwd"
    transport_cwd.mkdir(mode=0o700)
    staged_bundle: Path | None = None
    if grader_bundle is not None:
        staged_bundle = private_state / "grade-bundle"
        _copy_tree(grader_bundle, staged_bundle)
    private_socket_directories: list[Path] = []
    command_socket_directory: Path | None = None
    command_socket_host: Path | None = None
    if mode == "operator":
        command_socket_directory = _private_socket_directory(
            label=f"{label}-command"
        )
        private_socket_directories.append(command_socket_directory)
        command_socket_host = _checked_unix_socket_path(
            command_socket_directory / "broker.sock",
            label=f"{label} Claude command broker",
        )
    token_path = private_state / "broker-token"
    token_path.write_text(secrets.token_hex(32) + "\n", encoding="ascii")
    token_path.chmod(0o600)
    proxy_prefix = _claude_proxy_bwrap(
        bridge=bridge,
        private_state=private_state,
        mode=mode,
        command_socket_directory=command_socket_directory,
        grader_bundle=staged_bundle,
    )
    server = (
        CLAUDE_OPERATOR_SERVER if mode == "operator" else CLAUDE_GRADER_SERVER
    )
    tools = (
        list(CLAUDE_OPERATOR_TOOLS)
        if mode == "operator"
        else list(CLAUDE_GRADER_TOOLS)
    )
    proxy_args = [
        *proxy_prefix[1:],
        "/usr/bin/python3",
        "-I",
        "-B",
        str(CLAUDE_MCP_BRIDGE_MOUNT),
        "mcp",
        "--mode",
        mode,
        "--trace",
        str(CLAUDE_MCP_PRIVATE_MOUNT / "proxy-trace.jsonl"),
        "--ready",
        str(CLAUDE_MCP_PRIVATE_MOUNT / "proxy-ready.json"),
    ]
    if mode == "operator":
        proxy_args.extend(
            [
                "--broker-socket",
                str(CLAUDE_COMMAND_SOCKET_MOUNT),
                "--token-file",
                str(CLAUDE_MCP_PRIVATE_MOUNT / "broker-token"),
            ]
        )
    else:
        proxy_args.extend(["--root", "/evidence"])
    mcp_config = {
        "mcpServers": {
            server: {
                "type": "stdio",
                "command": str(BWRAP),
                "args": proxy_args,
                "env": {},
            }
        }
    }
    boundary: dict[str, Any] = {
        "schema": "maude.synthetic-operator.claude-mcp-boundary.v1",
        "label": label,
        "mode": mode,
        "private_state": private_state,
        "bridge": bridge,
        "bridge_sha256": sha256_file(bridge),
        "transport_cwd": transport_cwd,
        "proxy_bwrap_argv": proxy_prefix,
        "proxy_self_test_argv": [
            *proxy_prefix,
            "/usr/bin/python3",
            "-I",
            "-B",
            str(CLAUDE_MCP_BRIDGE_MOUNT),
            "self-test",
            "--mode",
            mode,
        ],
        "proxy_ready": private_state / "proxy-ready.json",
        "proxy_trace": private_state / "proxy-trace.jsonl",
        "mcp_protocol_version": CLAUDE_MCP_PROTOCOL_VERSION,
        "mcp_config": mcp_config,
        "mcp_config_sha256": sha256_bytes(_canonical_json_bytes(mcp_config)),
        "allowed_tools": tools,
        "server": server,
        "provider_environment": _claude_transport_environment(provider_home),
        "provider_home": provider_home,
        "staged_grade_bundle": staged_bundle,
        "operator_home": operator_home,
        "command_broker": None,
        "pty_broker": None,
        "private_socket_directories": private_socket_directories,
        "unix_socket_contract": {
            "path_budget_bytes": UNIX_SOCKET_PATH_BUDGET,
            "private_arena_root": str(PRIVATE_SOCKET_ROOT),
            "command_socket_host": (
                str(command_socket_host)
                if command_socket_host is not None
                else None
            ),
            "command_socket_host_bytes": (
                len(os.fsencode(str(command_socket_host)))
                if command_socket_host is not None
                else None
            ),
            "command_socket_proxy": (
                str(CLAUDE_COMMAND_SOCKET_MOUNT)
                if mode == "operator"
                else None
            ),
        },
    }
    if mode == "operator":
        if operator_home is None:
            raise CampaignError("Claude operator boundary needs a clean HOME")
        policy = {
            "schema": "maude.synthetic-operator.command-broker-policy.v1",
            "bwrap": str(BWRAP),
            "cwd": str(cwd),
            "home": str(OPERATOR_HOME_MOUNT),
            "mounts": mounts or [],
            "sockets": list(sockets or []),
            "environment": dict(environment or {}),
            "cleanroom": {
                key: str(value)
                for key, value in _prepare_cleanroom_os().items()
            },
            "forbidden_prefixes": [
                str(HOST_SOURCE_ROOT),
                str(provider_home),
                "/run/provider-auth",
            ],
        }
        pty: dict[str, Any] | None = None
        if pty_adapter is not None:
            pty_private = private_state / "pty-private"
            pty_private.mkdir(mode=0o700)
            pty_socket_directory = _private_socket_directory(
                label=f"{label}-pty"
            )
            private_socket_directories.append(pty_socket_directory)
            pty_socket_host = _checked_unix_socket_path(
                pty_socket_directory / "broker.sock",
                label=f"{label} persistent PTY broker",
            )
            pty_socket_sandbox = Path("/run/operator-pty/broker.sock")
            _checked_unix_socket_path(
                pty_socket_sandbox,
                label=f"{label} persistent PTY client",
            )
            _checked_unix_socket_path(
                CLAUDE_PTY_SERVER_SOCKET_MOUNT,
                label=f"{label} persistent PTY server",
            )
            policy["sockets"].append(
                {
                    "source": str(pty_socket_host),
                    "target": str(pty_socket_sandbox),
                }
            )
            policy["environment"]["OPERATOR_PTY_SOCKET"] = str(
                pty_socket_sandbox
            )
            pty = {
                "private_state": pty_private,
                "socket_directory": pty_socket_directory,
                "socket_host": pty_socket_host,
                "socket_sandbox": pty_socket_sandbox,
                "server_socket_sandbox": CLAUDE_PTY_SERVER_SOCKET_MOUNT,
                "ready_host": pty_private / "ready.json",
                "cleanup_host": pty_private / "cleanup.json",
                "shutdown_host": pty_private / "shutdown-request.json",
                "adapter": pty_adapter,
            }
            boundary["unix_socket_contract"].update(
                {
                    "pty_socket_host": str(pty_socket_host),
                    "pty_socket_host_bytes": len(
                        os.fsencode(str(pty_socket_host))
                    ),
                    "pty_socket_server": str(
                        CLAUDE_PTY_SERVER_SOCKET_MOUNT
                    ),
                    "pty_socket_client": str(pty_socket_sandbox),
                }
            )
        policy_path = private_state / "command-policy.json"
        write_json(policy_path, policy)
        command_broker = {
            "socket": command_socket_host,
            "ready": private_state / "command-broker-ready.json",
            "trace": private_state / "command-broker-trace.jsonl",
            "stdout": private_state / "command-broker.stdout",
            "stderr": private_state / "command-broker.stderr",
            "policy": policy_path,
            "token": token_path,
            "argv": [
                sys.executable,
                "-I",
                "-B",
                str(bridge),
                "broker",
                "--socket",
                str(command_socket_host),
                "--policy",
                str(policy_path),
                "--token-file",
                str(token_path),
                "--trace",
                str(private_state / "command-broker-trace.jsonl"),
                "--ready",
                str(private_state / "command-broker-ready.json"),
            ],
        }
        boundary["command_broker"] = command_broker
        boundary["pty_broker"] = pty
    return boundary


def _claude_operator_boundary_for_run(
    run: dict[str, Any],
    provider_home: Path,
    *,
    endpoint_socket: Path | None = None,
    public_cli_socket: Path | None = None,
) -> tuple[dict[str, Any], Path, Path]:
    lab = _lab_dir(run["run_id"])
    installation = run["surface"] == "maude-installation"
    install_root = lab / "installation"
    operator_home = (
        install_root / "home"
        if installation
        else lab / "private-operator-home"
    )
    _prepare_clean_operator_home(operator_home)
    cwd, mounts, sockets, environment = _surface_mount_policy(
        run,
        operator_home,
        endpoint_socket=endpoint_socket,
        public_cli_socket=public_cli_socket,
    )
    pty_adapter: Path | None = None
    if installation:
        candidates = (
            install_root / "operator" / "operator-pty",
            install_root / "work" / "operator-pty",
        )
        pty_adapter = next(
            (candidate for candidate in candidates if candidate.is_file()),
            None,
        )
        if pty_adapter is None:
            raise CampaignError(
                f"{run['run_id']}: installation operator-pty is absent"
            )
    boundary = _build_claude_boundary(
        label=f"{run['run_id']}-operator",
        lab=lab,
        mode="operator",
        provider_home=provider_home,
        cwd=cwd,
        operator_home=operator_home,
        mounts=mounts,
        sockets=sockets,
        environment=environment,
        pty_adapter=pty_adapter,
    )
    return boundary, cwd, operator_home


def _claude_grader_boundary(
    run_id: str,
    provider_home: Path,
    bundle: Path,
) -> tuple[dict[str, Any], Path]:
    lab = _lab_dir(run_id)
    operator_home = lab / "private-grader-home"
    _prepare_clean_operator_home(operator_home)
    boundary = _build_claude_boundary(
        label=f"{run_id}-grader-{uuid.uuid4().hex[:10]}",
        lab=lab,
        mode="grader",
        provider_home=provider_home,
        cwd=Path("/evidence"),
        operator_home=operator_home,
        grader_bundle=bundle,
    )
    return boundary, operator_home


def _adapt_boundary_for_codex(
    boundary: dict[str, Any],
) -> dict[str, Any]:
    """Use the frozen broker with one direct, minimal Codex stdio MCP shim.

    Codex itself remains in the provider transport namespace because it needs
    the copied CODEX_HOME and outbound authentication.  The trusted bridge is
    mounted as one exact file in that namespace and has no code path that reads
    CODEX_HOME.  All task execution remains behind the existing host broker and
    its per-command, no-network Bubblewrap namespace.
    """

    private_state = boundary["private_state"]
    proxy_state = private_state / "codex-proxy-state"
    proxy_state.mkdir(mode=0o700)
    server = boundary["server"]
    bare_tool = (
        "terminal" if boundary["mode"] == "operator" else "evidence"
    )
    bridge_args = [
        "-I",
        "-B",
        str(CLAUDE_MCP_BRIDGE_MOUNT),
        "mcp",
        "--mode",
        boundary["mode"],
        "--trace",
        str(CLAUDE_MCP_PRIVATE_MOUNT / "proxy-trace.jsonl"),
        "--ready",
        str(CLAUDE_MCP_PRIVATE_MOUNT / "proxy-ready.json"),
    ]
    if boundary["mode"] == "operator":
        broker = boundary.get("command_broker")
        if not isinstance(broker, dict):
            raise CampaignError("Codex operator MCP boundary has no broker")
        _copy_file(broker["token"], proxy_state / "broker-token")
        (proxy_state / "broker-token").chmod(0o600)
        bridge_args.extend(
            [
                "--broker-socket",
                str(CLAUDE_COMMAND_SOCKET_MOUNT),
                "--token-file",
                str(CLAUDE_MCP_PRIVATE_MOUNT / "broker-token"),
            ]
        )
    else:
        bridge_args.extend(["--root", "/evidence"])
    proxy_args = [
        "-i",
        "HOME=/home/mcp",
        "TMPDIR=/tmp",
        "PATH=/usr/bin:/bin",
        "LANG=C.UTF-8",
        "LC_ALL=C.UTF-8",
        "PYTHONDONTWRITEBYTECODE=1",
        "PYTHONNOUSERSITE=1",
        "/usr/bin/python3",
        *bridge_args,
    ]
    config = {
        "mcp_servers": {
            server: {
                "command": "/usr/bin/env",
                "args": proxy_args,
                "enabled_tools": [bare_tool],
                "default_tools_approval_mode": (
                    CODEX_MCP_DEFAULT_TOOLS_APPROVAL_MODE
                ),
            }
        }
    }
    mcp_approval_config_override = (
        f"mcp_servers.{server}.default_tools_approval_mode="
        f'"{CODEX_MCP_DEFAULT_TOOLS_APPROVAL_MODE}"'
    )
    boundary.update(
        {
            "schema": (
                "maude.synthetic-operator.codex-strict-mcp-boundary.v1"
            ),
            "provider_config": "openai-sol",
            "proxy_state": proxy_state,
            "proxy_ready": proxy_state / "proxy-ready.json",
            "proxy_trace": proxy_state / "proxy-trace.jsonl",
            "mcp_protocol_version": CODEX_MCP_PROTOCOL_VERSION,
            "mcp_config": config,
            "mcp_config_sha256": sha256_bytes(
                _canonical_json_bytes(config)
            ),
            "codex_mcp_command": "/usr/bin/env",
            "codex_mcp_args": proxy_args,
            "codex_enabled_tools": [bare_tool],
            "codex_mcp_default_tools_approval_mode": (
                CODEX_MCP_DEFAULT_TOOLS_APPROVAL_MODE
            ),
            "codex_mcp_approval_config_override": (
                mcp_approval_config_override
            ),
            "mcp_tool_approval_safety_basis": {
                "mcp_config_hash_pinned": True,
                "exact_enabled_tool_count": 1,
                "single_enabled_mcp_tool": bare_tool,
                "operator_terminal_bounded_by_frozen_broker": (
                    boundary["mode"] == "operator"
                ),
                "grader_evidence_tool_read_only": (
                    boundary["mode"] == "grader"
                ),
                "rationale": (
                    "MCP tool auto-approval is safe here only because the "
                    "hash-pinned server exposes exactly one tool: the "
                    "operator terminal is bounded by the frozen broker, "
                    "while the grader evidence tool is read-only."
                ),
            },
            "codex_approval_argv": list(CODEX_APPROVAL_CONFIG_ARGV),
            "codex_approval_config_override": CODEX_APPROVAL_CONFIG,
            "codex_approval_policy": CODEX_APPROVAL_POLICY,
            "noninteractive_approval_safety_basis": {
                "intrinsic_action_features_disabled": list(
                    CODEX_DISABLED_INTRINSIC_ACTION_FEATURES
                ),
                "single_enabled_mcp_tool": bare_tool,
                "operator_terminal_bounded_by_frozen_broker": (
                    boundary["mode"] == "operator"
                ),
                "grader_evidence_tool_read_only": (
                    boundary["mode"] == "grader"
                ),
                "rationale": (
                    "Non-interactive approval is safe here only because "
                    "Codex intrinsic action features are disabled and "
                    "operator sessions expose exactly one MCP terminal "
                    "bounded by the frozen broker; grader sessions expose "
                    "exactly one read-only evidence tool."
                ),
            },
            "provider_environment": None,
            "proxy_bwrap_argv": [],
            "trusted_stdio_shim_shares_provider_namespace": True,
            "trusted_stdio_shim_reads_provider_auth": False,
        }
    )
    return boundary


def _codex_operator_boundary_for_run(
    run: dict[str, Any],
    provider_home: Path,
    *,
    endpoint_socket: Path | None = None,
    public_cli_socket: Path | None = None,
) -> tuple[dict[str, Any], Path, Path]:
    boundary, cwd, operator_home = _claude_operator_boundary_for_run(
        run,
        provider_home,
        endpoint_socket=endpoint_socket,
        public_cli_socket=public_cli_socket,
    )
    return _adapt_boundary_for_codex(boundary), cwd, operator_home


def _codex_grader_boundary(
    run_id: str,
    provider_home: Path,
    bundle: Path,
) -> tuple[dict[str, Any], Path]:
    boundary, operator_home = _claude_grader_boundary(
        run_id, provider_home, bundle
    )
    return _adapt_boundary_for_codex(boundary), operator_home


def _codex_mcp_transport_bwrap(
    boundary: dict[str, Any],
    provider_home: Path,
    operator_home: Path,
) -> list[str]:
    """Build the task-blind Codex provider transport namespace."""

    if boundary.get("provider_config") != "openai-sol":
        raise CampaignError("Codex transport received a non-Codex boundary")
    argv = _bwrap_base("openai-sol", provider_home, operator_home)
    argv.extend(
        [
            "--dir",
            "/opt/maude-eval",
            "--ro-bind",
            str(boundary["bridge"]),
            str(CLAUDE_MCP_BRIDGE_MOUNT),
            "--dir",
            str(CLAUDE_MCP_PRIVATE_MOUNT),
            "--bind",
            str(boundary["proxy_state"]),
            str(CLAUDE_MCP_PRIVATE_MOUNT),
            "--dir",
            "/home/mcp",
        ]
    )
    if boundary["mode"] == "operator":
        broker = boundary.get("command_broker")
        if not isinstance(broker, dict):
            raise CampaignError("Codex transport has no command broker")
        argv.extend(
            [
                "--dir",
                str(CLAUDE_COMMAND_SOCKET_MOUNT.parent),
                "--ro-bind",
                str(Path(broker["socket"]).parent),
                str(CLAUDE_COMMAND_SOCKET_MOUNT.parent),
            ]
        )
    else:
        staged = boundary.get("staged_grade_bundle")
        if staged is None or not Path(str(staged)).is_dir():
            raise CampaignError("Codex grader has no staged evidence bundle")
        argv.extend(["--dir", "/evidence", "--ro-bind", str(staged), "/evidence"])
    argv.extend(["--chdir", str(OPERATOR_HOME_MOUNT)])
    return argv


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _bwrap_parent_dirs(paths: Iterable[Path]) -> list[Path]:
    selected: set[Path] = set()
    excluded = {
        Path("/usr"),
        Path("/bin"),
        Path("/lib"),
        Path("/lib64"),
        Path("/etc"),
        Path("/dev"),
        Path("/proc"),
    }
    for path in paths:
        current = path.parent
        while current != current.parent and current not in excluded:
            selected.add(current)
            current = current.parent
    return sorted(selected, key=lambda item: (len(item.parts), str(item)))


def _pty_broker_bwrap_argv(boundary: dict[str, Any]) -> list[str]:
    pty = boundary.get("pty_broker")
    broker = boundary.get("command_broker")
    if not isinstance(pty, dict) or not isinstance(broker, dict):
        raise CampaignError("persistent PTY boundary is incomplete")
    policy = load_json(broker["policy"])
    cleanroom = policy["cleanroom"]
    mounts = list(policy["mounts"])
    # The per-command PTY client socket does not exist until this persistent
    # broker starts; all other declared sockets are runtime endpoints the PTY
    # child may legitimately need.
    runtime_sockets = [
        value
        for value in policy["sockets"]
        if value["source"] != str(pty["socket_host"])
    ]
    destinations = [
        Path(value["target"]) for value in mounts + runtime_sockets
    ]
    destinations.extend(
        [
            Path(policy["cwd"]),
            Path(policy["home"]),
            Path("/run/operator-pty/broker.sock"),
        ]
    )
    argv = [
        str(BWRAP),
        "--die-with-parent",
        "--unshare-pid",
        "--unshare-net",
        "--unshare-ipc",
        "--unshare-uts",
        "--unshare-cgroup-try",
        "--clearenv",
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
        "/run/operator-pty",
        "--bind",
        str(pty["private_state"]),
        "/run/operator-pty",
        "--dir",
        str(Path(pty["server_socket_sandbox"]).parent),
        "--bind",
        str(pty["socket_directory"]),
        str(Path(pty["server_socket_sandbox"]).parent),
        "--dir",
        "/home",
    ]
    for directory in _bwrap_parent_dirs(destinations):
        if directory == Path("/run/operator-pty"):
            continue
        argv.extend(["--dir", str(directory)])
    for mount in mounts:
        argv.extend(
            [
                "--ro-bind" if mount["mode"] == "ro" else "--bind",
                mount["source"],
                mount["target"],
            ]
        )
    for mounted_socket in runtime_sockets:
        argv.extend(
            [
                "--ro-bind",
                mounted_socket["source"],
                mounted_socket["target"],
            ]
        )
    for key, value in sorted(policy["environment"].items()):
        if key != "OPERATOR_PTY_SOCKET":
            argv.extend(["--setenv", key, value])
    argv.extend(
        [
            "--chdir",
            policy["cwd"],
            "/usr/bin/python3",
            "-I",
            "-B",
            str(pty["adapter"]),
            "serve",
            "--socket",
            str(pty["server_socket_sandbox"]),
            "--ready",
            "/run/operator-pty/ready.json",
        "--cleanup-report",
        "/run/operator-pty/cleanup.json",
        "--shutdown-request",
        "/run/operator-pty/shutdown-request.json",
        ]
    )
    return argv


def _claude_boundary_record(boundary: dict[str, Any]) -> dict[str, Any]:
    """Return a committable boundary description without private token bytes."""

    broker = boundary.get("command_broker")
    pty = boundary.get("pty_broker")
    codex = boundary.get("provider_config") == "openai-sol"
    return {
        "schema": boundary["schema"],
        "provider_config": boundary.get(
            "provider_config", "anthropic-sonnet"
        ),
        "label": boundary["label"],
        "mode": boundary["mode"],
        "bridge_sha256": boundary["bridge_sha256"],
        "mcp_protocol_version": boundary["mcp_protocol_version"],
        "mcp_server": boundary["server"],
        "allowed_tools": boundary["allowed_tools"],
        "built_in_tools": [],
        "mcp_config_sha256": boundary["mcp_config_sha256"],
        **(
            {
                "codex_approval_argv": boundary["codex_approval_argv"],
                "codex_approval_config_override": boundary[
                    "codex_approval_config_override"
                ],
                "codex_approval_policy": boundary["codex_approval_policy"],
                "noninteractive_approval_safety_basis": boundary[
                    "noninteractive_approval_safety_basis"
                ],
                "codex_mcp_default_tools_approval_mode": boundary[
                    "codex_mcp_default_tools_approval_mode"
                ],
                "codex_mcp_approval_config_override": boundary[
                    "codex_mcp_approval_config_override"
                ],
                "mcp_tool_approval_safety_basis": boundary[
                    "mcp_tool_approval_safety_basis"
                ],
            }
            if codex
            else {}
        ),
        "proxy_bwrap_argv": boundary["proxy_bwrap_argv"],
        "proxy_ready": str(boundary["proxy_ready"]),
        "proxy_trace": str(boundary["proxy_trace"]),
        "provider_transport_outside_task_sandbox": True,
        "provider_auth_mounted_in_proxy_or_command": True if codex else False,
        "provider_auth_visible_to_trusted_stdio_shim": True if codex else False,
        "trusted_stdio_shim_reads_provider_auth": (
            boundary.get("trusted_stdio_shim_reads_provider_auth")
            if codex
            else False
        ),
        "provider_auth_mounted_in_command": False,
        "host_source_mounted_in_proxy_or_command": False,
        "external_network_available_to_proxy_or_command": (
            True if codex else False
        ),
        "external_network_available_to_command": False,
        "unix_socket_contract": boundary["unix_socket_contract"],
        "command_broker": (
            {
                "policy": file_record(broker["policy"]),
                "socket": str(broker["socket"]),
                "ready": str(broker["ready"]),
                "trace": str(broker["trace"]),
                "provider_credentials_received": False,
                "semantic_prompt_received": False,
                "per_command_bubblewrap": True,
            }
            if isinstance(broker, dict)
            else None
        ),
        "pty_broker": (
            {
                "socket_host": str(pty["socket_host"]),
                "socket_sandbox": str(pty["socket_sandbox"]),
                "server_socket_sandbox": str(
                    pty["server_socket_sandbox"]
                ),
                "ready": str(pty["ready_host"]),
                "cleanup": str(pty["cleanup_host"]),
                "shutdown_request": str(pty["shutdown_host"]),
            }
            if isinstance(pty, dict)
            else None
        ),
    }


def _provider_argv(
    config_id: str,
    *,
    system_prompt: str,
    user_prompt: str,
    cwd: Path,
    grade_schema: Path | None = None,
    additional_dirs: list[Path] | None = None,
    allowed_unix_sockets: list[Path] | None = None,
    claude_boundary: dict[str, Any] | None = None,
) -> tuple[list[str], dict[str, Any], bytes | None]:
    additional_dirs = additional_dirs or []
    allowed_unix_sockets = allowed_unix_sockets or []
    if config_id == "anthropic-sonnet":
        if claude_boundary is None:
            raise CampaignError(
                "Claude invocation requires an explicit MCP cleanroom boundary"
            )
        if additional_dirs or allowed_unix_sockets:
            raise CampaignError(
                "Claude task paths/sockets must be declared in the MCP "
                "command-broker policy, never added to the provider process"
            )
        session_id = str(uuid.uuid4())
        allowed_tools = list(claude_boundary["allowed_tools"])
        mcp_config_json = _canonical_json_bytes(
            claude_boundary["mcp_config"]
        ).decode("utf-8")
        argv = [
            str(CLAUDE_HOST_BINARY),
            "-p",
            "--setting-sources",
            "",
            "--strict-mcp-config",
            "--mcp-config",
            mcp_config_json,
            "--tools",
            ",".join(allowed_tools),
            "--permission-mode",
            "bypassPermissions",
            "--disable-slash-commands",
            "--no-chrome",
            "--no-session-persistence",
            "--session-id",
            session_id,
            "--model",
            "sonnet",
            "--effort",
            "low",
            "--input-format",
            "stream-json",
            "--output-format",
            "stream-json",
            "--verbose",
            "--replay-user-messages",
            "--system-prompt",
            system_prompt,
        ]
        if grade_schema is not None:
            argv.extend(["--json-schema", _read(grade_schema)])
        delivery = {
            "provider": "Anthropic",
            "requested_model": "sonnet",
            "requested_session_id": session_id,
            "system_prompt_delivery": "system",
            "user_prompt_delivery": (
                "single stream-json user event after flushed MCP tools/list "
                "readiness; stdin then closed"
            ),
            "user_prompt_sha256": sha256_bytes(
                user_prompt.encode("utf-8")
            ),
            "mcp_protocol_version": CLAUDE_MCP_PROTOCOL_VERSION,
            "mcp_config_sha256": claude_boundary["mcp_config_sha256"],
            "allowed_tools": allowed_tools,
            "built_in_tools": [],
            "provider_task_paths_added": [],
            "provider_unix_sockets_added": [],
        }
        stdin_payload = None
    else:
        if (
            claude_boundary is None
            or claude_boundary.get("provider_config") != "openai-sol"
        ):
            raise CampaignError(
                "Codex invocation requires an explicit strict MCP boundary"
            )
        if additional_dirs or allowed_unix_sockets:
            raise CampaignError(
                "Codex task paths/sockets must be declared only in the "
                "command-broker policy"
            )
        delivered = (
            system_prompt
            + "\n\n--- BEGIN EXACT USER ASSIGNMENT ---\n\n"
            + user_prompt
        )
        argv = [
            str(CODEX_SANDBOX_BINARY),
            "exec",
            *CODEX_APPROVAL_CONFIG_ARGV,
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--strict-config",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--json",
            "--model",
            "gpt-5.6-sol",
            "--config",
            'model_reasoning_effort="low"',
            "-C",
            str(OPERATOR_HOME_MOUNT),
        ]
        for feature in (
            *CODEX_DISABLED_INTRINSIC_ACTION_FEATURES,
            *CODEX_DISABLED_OPTIONAL_FEATURES,
        ):
            argv.extend(["--disable", feature])
        server = str(claude_boundary["server"])
        mcp_args = json.dumps(
            claude_boundary["codex_mcp_args"],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        enabled_tools = json.dumps(
            claude_boundary["codex_enabled_tools"],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        argv.extend(
            [
                "--config",
                (
                    f'mcp_servers.{server}.command='
                    f'"{claude_boundary["codex_mcp_command"]}"'
                ),
                "--config",
                f"mcp_servers.{server}.args={mcp_args}",
                "--config",
                f"mcp_servers.{server}.enabled_tools={enabled_tools}",
                "--config",
                claude_boundary["codex_mcp_approval_config_override"],
            ]
        )
        if grade_schema is not None:
            argv.extend(
                [
                    "--output-schema",
                    str(Path("/evidence") / grade_schema.name),
                ]
            )
        argv.append("-")
        stdin_payload = delivered.encode("utf-8")
        delivery = {
            "provider": "OpenAI",
            "requested_model": "gpt-5.6-sol",
            "system_prompt_delivery": "concatenated first in single CLI prompt",
            "user_prompt_delivery": (
                "concatenated after exact delimiter and delivered through "
                "closed stdin; no semantic prompt bytes appear in argv"
            ),
            "delivered_prompt_sha256": sha256_bytes(delivered.encode("utf-8")),
            "delivered_prompt_bytes": len(stdin_payload),
            "semantic_prompt_bytes_in_argv": False,
            "allowed_unix_sockets": [],
            "intrinsic_action_features_explicitly_disabled": list(
                CODEX_DISABLED_INTRINSIC_ACTION_FEATURES
            ),
            "optional_features_explicitly_disabled": [
                *CODEX_DISABLED_OPTIONAL_FEATURES
            ],
            "live_web_search_enabled": False,
            "provider_transport_cwd": str(OPERATOR_HOME_MOUNT),
            "provider_task_paths_added": [],
            "user_mcp_and_connector_config_loaded": False,
            "mcp_server": server,
            "mcp_protocol_version": CODEX_MCP_PROTOCOL_VERSION,
            "mcp_config_sha256": claude_boundary["mcp_config_sha256"],
            "mcp_enabled_tools": list(
                claude_boundary["codex_enabled_tools"]
            ),
            "codex_approval_argv": list(CODEX_APPROVAL_CONFIG_ARGV),
            "codex_approval_config_override": CODEX_APPROVAL_CONFIG,
            "codex_approval_policy": CODEX_APPROVAL_POLICY,
            "noninteractive_approval_safety_basis": claude_boundary[
                "noninteractive_approval_safety_basis"
            ],
            "codex_mcp_default_tools_approval_mode": (
                CODEX_MCP_DEFAULT_TOOLS_APPROVAL_MODE
            ),
            "codex_mcp_approval_config_override": claude_boundary[
                "codex_mcp_approval_config_override"
            ],
            "mcp_tool_approval_safety_basis": claude_boundary[
                "mcp_tool_approval_safety_basis"
            ],
            "exact_provider_tool_allowlist_supported": True,
            "unexpected_intrinsic_action_policy": "fail-closed",
        }
    return argv, delivery, stdin_payload


def _validate_codex_strict_argv(
    argv: list[str],
    boundary: dict[str, Any],
) -> None:
    """Reject any Codex invocation that is not the frozen MCP-only shape."""

    try:
        provider_index = argv.index(str(CODEX_SANDBOX_BINARY))
    except ValueError as exc:
        raise CampaignError("Codex transport argv lacks the pinned CLI") from exc
    provider_argv = argv[provider_index:]
    disabled = [
        provider_argv[index + 1]
        for index, value in enumerate(provider_argv[:-1])
        if value == "--disable"
    ]
    expected_disabled = [
        *CODEX_DISABLED_INTRINSIC_ACTION_FEATURES,
        *CODEX_DISABLED_OPTIONAL_FEATURES,
    ]
    configs = [
        provider_argv[index + 1]
        for index, value in enumerate(provider_argv[:-1])
        if value == "--config"
    ]
    server = str(boundary["server"])
    expected_mcp_approval_config = (
        f"mcp_servers.{server}.default_tools_approval_mode="
        f'"{CODEX_MCP_DEFAULT_TOOLS_APPROVAL_MODE}"'
    )
    expected_mcp_configs = {
        (
            f'mcp_servers.{server}.command='
            f'"{boundary["codex_mcp_command"]}"'
        ),
        (
            f"mcp_servers.{server}.args="
            + json.dumps(
                boundary["codex_mcp_args"],
                ensure_ascii=False,
                separators=(",", ":"),
            )
        ),
        (
            f"mcp_servers.{server}.enabled_tools="
            + json.dumps(
                boundary["codex_enabled_tools"],
                ensure_ascii=False,
                separators=(",", ":"),
            )
        ),
        expected_mcp_approval_config,
    }
    expected_mcp_config_object = {
        "mcp_servers": {
            server: {
                "command": boundary["codex_mcp_command"],
                "args": boundary["codex_mcp_args"],
                "enabled_tools": boundary["codex_enabled_tools"],
                "default_tools_approval_mode": (
                    CODEX_MCP_DEFAULT_TOOLS_APPROVAL_MODE
                ),
            }
        }
    }
    sandbox_values = [
        provider_argv[index + 1]
        for index, value in enumerate(provider_argv[:-1])
        if value == "--sandbox"
    ]
    cwd_values = [
        provider_argv[index + 1]
        for index, value in enumerate(provider_argv[:-1])
        if value == "-C"
    ]
    approval_configs = [
        value
        for value in configs
        if value.partition("=")[0].strip() == "approval_policy"
    ]
    mcp_approval_key = (
        f"mcp_servers.{server}.default_tools_approval_mode"
    )
    mcp_approval_configs = [
        value
        for value in configs
        if value.partition("=")[0].strip() == mcp_approval_key
    ]
    observed_mcp_configs = {
        value for value in configs if value.startswith("mcp_servers.")
    }
    if (
        disabled != expected_disabled
        or observed_mcp_configs != expected_mcp_configs
        or len(observed_mcp_configs) != 4
        or sandbox_values != ["read-only"]
        or cwd_values != [str(OPERATOR_HOME_MOUNT)]
        or approval_configs != [CODEX_APPROVAL_CONFIG]
        or configs.count(CODEX_APPROVAL_CONFIG) != 1
        or boundary.get("codex_approval_argv")
        != list(CODEX_APPROVAL_CONFIG_ARGV)
        or boundary.get("codex_approval_config_override")
        != CODEX_APPROVAL_CONFIG
        or boundary.get("codex_approval_policy") != CODEX_APPROVAL_POLICY
        or mcp_approval_configs != [expected_mcp_approval_config]
        or configs.count(expected_mcp_approval_config) != 1
        or boundary.get("codex_mcp_default_tools_approval_mode")
        != CODEX_MCP_DEFAULT_TOOLS_APPROVAL_MODE
        or boundary.get("codex_mcp_approval_config_override")
        != expected_mcp_approval_config
        or boundary.get("mcp_config") != expected_mcp_config_object
        or boundary.get("mcp_config_sha256")
        != sha256_bytes(_canonical_json_bytes(expected_mcp_config_object))
        or "--ignore-user-config" not in provider_argv
        or "--strict-config" not in provider_argv
        or "--enable" in provider_argv
        or "--add-dir" in provider_argv
        or "use_legacy_landlock" in provider_argv
        or provider_argv[-1:] != ["-"]
    ):
        raise CampaignError("Codex argv is not the frozen strict MCP shape")


def _isolation_preflight(
    bwrap_prefix: list[str],
    provider: str,
    *,
    operator_root: Path,
    operator_home: Path,
    expected_maude_entrypoint: Path | None = None,
    declared_maude_entrypoint: Path | None = None,
    required_readable_paths: list[Path] | None = None,
    forbidden_operator_paths: list[Path] | None = None,
    required_socket_targets: list[Path] | None = None,
) -> dict[str, Any]:
    if provider == "anthropic-sonnet":
        raise CampaignError(
            "Claude isolation must use _claude_mcp_isolation_preflight"
        )
    if inventory_files(operator_home):
        raise CampaignError(
            f"clean operator HOME contains files before isolation probes: "
            f"{operator_home}"
        )
    source_check = _command(
        [
            *bwrap_prefix,
            "/usr/bin/test",
            "!",
            "-e",
            str(HOST_SOURCE_ROOT),
        ],
        expected=None,
    )
    if source_check["returncode"] != 0:
        raise CampaignError("Bubblewrap source-absence probe failed")
    forbidden_path_probes: list[dict[str, Any]] = []
    for path in forbidden_operator_paths or []:
        probe = _command(
            [*bwrap_prefix, "/usr/bin/test", "!", "-e", str(path)],
            expected=None,
        )
        forbidden_path_probes.append({"path": str(path), "probe": probe})
        if probe["returncode"] != 0:
            raise CampaignError(
                f"Bubblewrap private evaluator path is visible: {path}"
            )
    socket_probes: list[dict[str, Any]] = []
    for path in required_socket_targets or []:
        probe = _command(
            [
                *bwrap_prefix,
                "/usr/bin/python3",
                "-I",
                "-c",
                (
                    "import os,stat,sys;"
                    "raise SystemExit(0 if "
                    f"stat.S_ISSOCK(os.stat({str(path)!r}).st_mode) else 1)"
                ),
            ],
            expected=None,
        )
        socket_probes.append({"path": str(path), "probe": probe})
        if probe["returncode"] != 0:
            raise CampaignError(
                f"Bubblewrap public interface socket is unavailable: {path}"
            )
    binary = str(CODEX_SANDBOX_BINARY)
    version = _command([*bwrap_prefix, binary, "--version"], expected=None)
    if version["returncode"] != 0:
        raise CampaignError(
            f"Bubblewrap provider startup probe failed: {version['stderr']}"
        )
    visible = _command(
        [*bwrap_prefix, "/usr/bin/find", str(operator_root), "-maxdepth", "3", "-type", "f"],
        expected=None,
    )
    environment = _command(
        [
            *bwrap_prefix,
            "/usr/bin/env",
        ],
        expected=None,
    )
    maude_resolution = _command(
        [
            *bwrap_prefix,
            "/bin/sh",
            "-c",
            "command -v maude || true",
        ],
        expected=None,
    )
    expected_resolution = (
        str(expected_maude_entrypoint) if expected_maude_entrypoint else ""
    )
    actual_resolution = maude_resolution["stdout"].strip()
    if (
        maude_resolution["returncode"] != 0
        or actual_resolution != expected_resolution
    ):
        raise CampaignError(
            "Bubblewrap Maude executable-isolation probe failed: "
            f"expected={expected_resolution!r} actual={actual_resolution!r}"
        )
    declared_entrypoint_probe: dict[str, Any] | None = None
    if declared_maude_entrypoint is not None:
        declared_entrypoint_probe = _command(
            [
                *bwrap_prefix,
                "/usr/bin/test",
                "-x",
                str(declared_maude_entrypoint),
            ],
            expected=None,
        )
        if declared_entrypoint_probe["returncode"] != 0:
            raise CampaignError(
                "Bubblewrap declared Maude entrypoint is not executable: "
                f"{declared_maude_entrypoint}"
            )
    readable_path_probes: list[dict[str, Any]] = []
    for path in required_readable_paths or []:
        probe = _command(
            [*bwrap_prefix, "/usr/bin/test", "-r", str(path)],
            expected=None,
        )
        readable_path_probes.append(
            {"path": str(path), "probe": probe}
        )
        if probe["returncode"] != 0:
            raise CampaignError(
                f"Bubblewrap advertised input is unreadable: {path}"
            )
    system_python_import = _command(
        [
            *bwrap_prefix,
            "/usr/bin/python3",
            "-I",
            "-c",
            (
                "import importlib.util; "
                "print(importlib.util.find_spec('maude'))"
            ),
        ],
        expected=None,
    )
    if (
        system_python_import["returncode"] != 0
        or system_python_import["stdout"].strip() != "None"
    ):
        raise CampaignError(
            "Bubblewrap system Python can resolve a Maude module"
        )
    host_maude_mask = _command(
        [
            *bwrap_prefix,
            "/bin/sh",
            "-c",
            (
                "test ! -x /usr/bin/maude && "
                "test ! -x /bin/maude && "
                "test ! -e /usr/share/maude/prelude.maude && "
                "test ! -e /usr/share/doc/maude/copyright && "
                "test ! -s /usr/share/man/man1/maude.1.gz"
            ),
        ],
        expected=None,
    )
    if host_maude_mask["returncode"] != 0:
        raise CampaignError(
            "Bubblewrap unrelated host Maude package mask failed"
        )
    etc_inventory = _command(
        [
            *bwrap_prefix,
            "/usr/bin/find",
            "/etc",
            "-xdev",
            "-maxdepth",
            "3",
            "-printf",
            "%y %m %p\\n",
        ],
        expected=None,
    )
    if etc_inventory["returncode"] != 0:
        raise CampaignError("Bubblewrap minimal /etc inventory probe failed")
    expected_environment = {
        f"HOME={OPERATOR_HOME_MOUNT}",
        f"XDG_CONFIG_HOME={OPERATOR_HOME_MOUNT / '.config'}",
        f"XDG_CACHE_HOME={OPERATOR_HOME_MOUNT / '.cache'}",
        f"XDG_DATA_HOME={OPERATOR_HOME_MOUNT / '.local/share'}",
        f"XDG_STATE_HOME={OPERATOR_HOME_MOUNT / '.local/state'}",
        f"PIP_CACHE_DIR={OPERATOR_HOME_MOUNT / '.cache/pip'}",
        "PIP_CONFIG_FILE=/dev/null",
        f"TMPDIR={OPERATOR_HOME_MOUNT / 'tmp'}",
        "PYTHONDONTWRITEBYTECODE=1",
        "PYTHONNOUSERSITE=1",
        "GIT_CONFIG_NOSYSTEM=1",
        "GIT_CONFIG_GLOBAL=/dev/null",
    }
    observed_environment = set(environment["stdout"].splitlines())
    missing_environment = sorted(expected_environment - observed_environment)
    if environment["returncode"] != 0 or missing_environment:
        raise CampaignError(
            "Bubblewrap clean HOME environment probe failed: "
            f"missing={missing_environment!r}"
        )
    home_files_after = inventory_files(operator_home)
    if home_files_after:
        raise CampaignError(
            "provider startup/isolation probes contaminated the clean operator "
            f"HOME: {home_files_after!r}"
        )
    return {
        "schema": "maude.synthetic-operator.isolation-result.v1",
        "mechanism": "bubblewrap",
        "source_root_absent": True,
        "provider_startup_passed": True,
        "source_probe": source_check,
        "forbidden_private_path_probes": forbidden_path_probes,
        "public_socket_probes": socket_probes,
        "provider_version_probe": version,
        "visible_file_probe": visible,
        "clean_operator_home_mount": str(OPERATOR_HOME_MOUNT),
        "clean_operator_home_host_path": str(operator_home),
        "clean_operator_home_files_before_session": [],
        "clean_environment_probe": environment,
        "clean_environment_required_entries": sorted(expected_environment),
        "clean_environment_missing_entries": [],
        "maude_resolution_probe": maude_resolution,
        "expected_maude_entrypoint": expected_resolution or None,
        "declared_maude_entrypoint": (
            str(declared_maude_entrypoint)
            if declared_maude_entrypoint is not None
            else None
        ),
        "declared_maude_entrypoint_probe": declared_entrypoint_probe,
        "advertised_readable_path_probes": readable_path_probes,
        "unrelated_host_maude_masked": True,
        "system_python_maude_import_probe": system_python_import,
        "minimal_etc_inventory_probe": etc_inventory,
        "cleanroom_os_substrate": inventory_files(CLEANROOM_OS_ROOT),
        "host_run_mount": "resolver-only",
    }


def _public_cli_boundary_from_policy(
    policy: dict[str, Any],
    *,
    label: str,
) -> dict[str, Any] | None:
    serialized_policy = json.dumps(
        policy,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    if (
        "MAUDE_LAB_CONTROL_DIR" in policy.get("environment", {})
        or "/private/control" in serialized_policy
    ):
        raise CampaignError(
            f"{label} command policy exposes the raw Maude driver queue"
        )
    public_socket_environment = policy.get("environment", {}).get(
        "MAUDE_PUBLIC_SOCKET"
    )
    if public_socket_environment is None:
        return None
    matching_public_sockets = [
        value
        for value in policy.get("sockets", [])
        if value.get("target") == public_socket_environment
        and value.get("target") == str(PUBLIC_CLI_SOCKET_MOUNT)
    ]
    if len(matching_public_sockets) != 1:
        raise CampaignError(
            f"{label} Maude command policy lacks one exact public socket"
        )
    return {
        "raw_driver_queue_exposed": False,
        "environment_variable": "MAUDE_PUBLIC_SOCKET",
        "socket_target": public_socket_environment,
        "exact_socket_count": 1,
    }


def _claude_mcp_isolation_preflight(
    boundary: dict[str, Any],
) -> dict[str, Any]:
    """Mechanically prove the provider-independent Claude task namespace."""

    prefix = boundary["proxy_bwrap_argv"]
    source_check = _command(
        [
            *prefix,
            "/usr/bin/test",
            "!",
            "-e",
            str(HOST_SOURCE_ROOT),
        ],
        expected=None,
    )
    auth_check = _command(
        [
            *prefix,
            "/usr/bin/test",
            "!",
            "-e",
            str(PROVIDER_AUTH_MOUNT),
        ],
        expected=None,
    )
    environment = _command([*prefix, "/usr/bin/env"], expected=None)
    network_namespace = _command(
        [*prefix, "/usr/bin/readlink", "/proc/self/ns/net"],
        expected=None,
    )
    self_test = _command(boundary["proxy_self_test_argv"], expected=None)
    if (
        source_check["returncode"] != 0
        or auth_check["returncode"] != 0
        or environment["returncode"] != 0
        or network_namespace["returncode"] != 0
        or self_test["returncode"] != 0
    ):
        raise CampaignError("Claude MCP proxy isolation preflight failed")
    try:
        self_test_value = json.loads(self_test["stdout"])
    except json.JSONDecodeError as exc:
        raise CampaignError(
            "Claude MCP proxy self-test returned malformed JSON"
        ) from exc
    expected_bare_tools = [
        value.rsplit("__", 1)[-1] for value in boundary["allowed_tools"]
    ]
    if (
        self_test_value.get("mode") != boundary["mode"]
        or self_test_value.get("tools") != expected_bare_tools
        or self_test_value.get("supported_mcp_protocol_versions")
        != list(SUPPORTED_MCP_PROTOCOL_VERSIONS)
        or bool(self_test_value.get("grader_read_only"))
        != (boundary["mode"] == "grader")
        or bool(self_test_value.get("command_execution"))
        != (boundary["mode"] == "operator")
    ):
        raise CampaignError(
            "Claude MCP proxy self-test roster/authority mismatch"
        )
    observed_environment = set(environment["stdout"].splitlines())
    expected_environment = {
        "HOME=/home/mcp",
        "TMPDIR=/tmp",
        "PATH=/usr/bin:/bin",
        "LANG=C.UTF-8",
        "LC_ALL=C.UTF-8",
        "PYTHONDONTWRITEBYTECODE=1",
        "PYTHONNOUSERSITE=1",
    }
    forbidden_names = (
        "CLAUDE_",
        "ANTHROPIC_",
        "CODEX_",
        "MAUDE_LAB_",
        "OPERATOR_PTY_",
    )
    leaked_environment = sorted(
        line
        for line in observed_environment
        if line.split("=", 1)[0].startswith(forbidden_names)
    )
    missing_environment = sorted(expected_environment - observed_environment)
    if missing_environment or leaked_environment:
        raise CampaignError(
            "Claude MCP proxy clean environment mismatch: "
            f"missing={missing_environment!r} leaked={leaked_environment!r}"
        )
    host_network_namespace = os.readlink("/proc/self/ns/net")
    proxy_network_namespace = network_namespace["stdout"].strip()
    if not proxy_network_namespace or proxy_network_namespace == (
        host_network_namespace
    ):
        raise CampaignError("Claude MCP proxy did not unshare its network")
    policy_validation: dict[str, Any] | None = None
    public_cli_boundary: dict[str, Any] | None = None
    broker = boundary.get("command_broker")
    if isinstance(broker, dict):
        policy = load_json(broker["policy"])
        public_cli_boundary = _public_cli_boundary_from_policy(
            policy,
            label="Claude",
        )
        policy_probe = _command(
            [
                sys.executable,
                "-I",
                "-B",
                str(boundary["bridge"]),
                "validate-policy",
                "--policy",
                str(broker["policy"]),
            ],
            cwd=boundary["transport_cwd"],
            env={
                "HOME": str(boundary["transport_cwd"]),
                "PATH": "/usr/bin:/bin",
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONNOUSERSITE": "1",
            },
            expected=None,
        )
        if policy_probe["returncode"] != 0:
            raise CampaignError(
                "Claude command-broker policy validation failed: "
                + policy_probe["stderr"]
            )
        policy_validation = json.loads(policy_probe["stdout"])
    return {
        "schema": "maude.synthetic-operator.claude-mcp-isolation-result.v1",
        "mechanism": (
            "host Claude transport; stdio MCP proxy in auth/source-free "
            "bubblewrap; trusted local broker; per-command bubblewrap"
        ),
        "source_root_absent": True,
        "provider_auth_mount_absent": True,
        "provider_transport_inside_task_namespace": False,
        "proxy_external_network_absent": True,
        "host_network_namespace": host_network_namespace,
        "proxy_network_namespace": proxy_network_namespace,
        "proxy_environment": environment,
        "proxy_environment_missing_entries": [],
        "proxy_environment_secret_or_task_entries": [],
        "proxy_self_test": self_test,
        "bare_tool_roster": expected_bare_tools,
        "provider_reported_tool_roster_required": boundary["allowed_tools"],
        "built_in_tools_allowed": [],
        "command_broker_policy_validation": policy_validation,
        "public_cli_boundary": public_cli_boundary,
        "grader_command_execution_available": False
        if boundary["mode"] == "grader"
        else None,
        "mcp_protocol_version": CLAUDE_MCP_PROTOCOL_VERSION,
        "unix_socket_contract": boundary["unix_socket_contract"],
        "bridge_sha256": boundary["bridge_sha256"],
        "source_probe": source_check,
        "auth_probe": auth_check,
    }


def _codex_mcp_isolation_preflight(
    boundary: dict[str, Any],
    bwrap_prefix: list[str],
) -> dict[str, Any]:
    """Mechanically check the task-blind Codex transport and broker policy."""

    if (
        boundary.get("provider_config") != "openai-sol"
        or bwrap_prefix[:1] != [str(BWRAP)]
        or str(HOST_SOURCE_ROOT) in bwrap_prefix
    ):
        raise CampaignError("Codex MCP transport declaration is invalid")
    source_check = _command(
        [*bwrap_prefix, "/usr/bin/test", "!", "-e", str(HOST_SOURCE_ROOT)],
        cwd=boundary["transport_cwd"],
        expected=None,
    )
    auth_check = _command(
        [
            *bwrap_prefix,
            "/usr/bin/test",
            "-f",
            str(PROVIDER_AUTH_MOUNT / ".codex" / "auth.json"),
        ],
        cwd=boundary["transport_cwd"],
        expected=None,
    )
    self_test = _command(
        [
            *bwrap_prefix,
            "/usr/bin/python3",
            "-I",
            "-B",
            str(CLAUDE_MCP_BRIDGE_MOUNT),
            "self-test",
            "--mode",
            boundary["mode"],
        ],
        cwd=boundary["transport_cwd"],
        expected=None,
    )
    try:
        self_test_value = json.loads(self_test["stdout"])
    except json.JSONDecodeError as exc:
        raise CampaignError(
            "Codex MCP shim self-test was malformed: "
            f"returncode={self_test['returncode']} "
            f"stderr={self_test['stderr']!r}"
        ) from exc
    expected_tools = list(boundary["codex_enabled_tools"])
    if (
        source_check["returncode"] != 0
        or auth_check["returncode"] != 0
        or self_test["returncode"] != 0
        or self_test_value.get("mode") != boundary["mode"]
        or self_test_value.get("tools") != expected_tools
        or self_test_value.get("supported_mcp_protocol_versions")
        != list(SUPPORTED_MCP_PROTOCOL_VERSIONS)
    ):
        raise CampaignError("Codex MCP transport isolation preflight failed")
    policy_validation: dict[str, Any] | None = None
    public_cli_boundary: dict[str, Any] | None = None
    broker = boundary.get("command_broker")
    if isinstance(broker, dict):
        policy = load_json(broker["policy"])
        public_cli_boundary = _public_cli_boundary_from_policy(
            policy,
            label="Codex",
        )
        probe = _command(
            [
                sys.executable,
                "-I",
                "-B",
                str(boundary["bridge"]),
                "validate-policy",
                "--policy",
                str(broker["policy"]),
            ],
            cwd=boundary["transport_cwd"],
            env=_clean_boundary_process_environment(
                boundary["private_state"] / "policy-probe-home"
            ),
            expected=None,
        )
        if probe["returncode"] != 0:
            raise CampaignError(
                "Codex command-broker policy validation failed"
            )
        policy_validation = json.loads(probe["stdout"])
    return {
        "schema": "maude.synthetic-operator.codex-mcp-isolation-result.v1",
        "mechanism": (
            "task-blind Codex transport Bubblewrap; exact direct stdio MCP "
            "shim; trusted host broker; per-command no-network Bubblewrap"
        ),
        "source_root_absent": True,
        "provider_auth_present_only_for_transport_and_trusted_shim": True,
        "provider_task_paths_mounted": (
            []
            if boundary["mode"] == "operator"
            else ["/evidence (read-only frozen grade bundle)"]
        ),
        "intrinsic_action_features_disabled": list(
            CODEX_DISABLED_INTRINSIC_ACTION_FEATURES
        ),
        "unexpected_intrinsic_action_policy": "fail-closed",
        "mcp_server": boundary["server"],
        "mcp_protocol_version": CODEX_MCP_PROTOCOL_VERSION,
        "mcp_enabled_tools": expected_tools,
        "mcp_config_sha256": boundary["mcp_config_sha256"],
        "command_broker_policy_validation": policy_validation,
        "public_cli_boundary": public_cli_boundary,
        "source_probe": source_check,
        "auth_probe": auth_check,
        "shim_self_test": self_test,
    }


def _recursive_blocks(value: Any, block_type: str) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        if value.get("type") == block_type:
            yield value
        for child in value.values():
            yield from _recursive_blocks(child, block_type)
    elif isinstance(value, list):
        for child in value:
            yield from _recursive_blocks(child, block_type)


def _json_pointer_component(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _claude_event_path_disclosures(
    event: dict[str, Any],
    *,
    provider_home: Path,
    event_number: int,
) -> dict[str, list[dict[str, Any]]]:
    """Classify private paths in one parsed Claude stream event.

    Claude may report its temporary HOME in the provider-generated
    ``system/init`` envelope. That is host transport metadata, not assistant
    or tool content. Preserve and identify that disclosure without weakening
    the fail-closed rule for source paths or for any private path repeated in
    model/tool/result content.
    """

    allowed: list[dict[str, Any]] = []
    forbidden: list[dict[str, Any]] = []
    is_init = event.get("type") == "system" and event.get("subtype") == "init"
    needles = (
        ("host_source_root", str(HOST_SOURCE_ROOT)),
        ("provider_private_home", str(provider_home)),
    )

    def walk(value: Any, pointer: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                child = pointer + "/" + _json_pointer_component(str(key))
                walk(item, child)
            return
        if isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{pointer}/{index}")
            return
        if not isinstance(value, str):
            return
        for path_kind, needle in needles:
            if needle not in value:
                continue
            record = {
                "event_number": event_number,
                "event_type": event.get("type"),
                "event_subtype": event.get("subtype"),
                "json_pointer": pointer or "/",
                "path_kind": path_kind,
                "path_sha256": sha256_bytes(needle.encode("utf-8")),
            }
            if path_kind == "provider_private_home" and is_init:
                allowed.append(record)
            else:
                forbidden.append(record)

    walk(event, "")
    return {"allowed": allowed, "forbidden": forbidden}


def _claude_tool_result_text(block: dict[str, Any]) -> str | None:
    content = block.get("content")
    if isinstance(content, str):
        return content
    if (
        isinstance(content, list)
        and len(content) == 1
        and isinstance(content[0], dict)
        and content[0].get("type") == "text"
        and isinstance(content[0].get("text"), str)
    ):
        return str(content[0]["text"])
    return None


def _claude_process_descendants(root_pid: int) -> list[int]:
    parents: dict[int, int] = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / "stat").read_text(encoding="utf-8")
            tail = raw[raw.rfind(")") + 2 :].split()
            parents[int(entry.name)] = int(tail[1])
        except (FileNotFoundError, PermissionError, OSError, ValueError):
            continue
    selected = {root_pid}
    changed = True
    while changed:
        changed = False
        for pid, parent in parents.items():
            if parent in selected and pid not in selected:
                selected.add(pid)
                changed = True
    return sorted(selected)


def _claude_proxy_runtime_proof(
    provider_pid: int,
    boundary: dict[str, Any],
    auth_inodes: set[tuple[int, int]],
) -> dict[str, Any]:
    """Prove an active tool event is backed by the declared MCP proxy."""

    candidates: list[int] = []
    monitors: list[int] = []
    host_net = os.readlink("/proc/self/ns/net")
    host_mnt = os.readlink("/proc/self/ns/mnt")
    for pid in _claude_process_descendants(provider_pid):
        try:
            proc = Path("/proc") / str(pid)
            command = proc.joinpath("cmdline").read_bytes().replace(
                b"\0", b" "
            ).decode(
                "utf-8", errors="replace"
            )
            network_namespace = os.readlink(proc / "ns/net")
            mount_namespace = os.readlink(proc / "ns/mnt")
        except (FileNotFoundError, PermissionError, OSError):
            continue
        if str(CLAUDE_MCP_BRIDGE_MOUNT) not in command or " mcp " not in command:
            continue
        if command.startswith(str(BWRAP) + " "):
            monitors.append(pid)
            continue
        if (
            command.startswith("/usr/bin/python3 ")
            and network_namespace != host_net
            and mount_namespace != host_mnt
        ):
            candidates.append(pid)
    if not candidates:
        raise CampaignError(
            "Claude emitted an MCP tool action without a live declared proxy"
        )
    if len(candidates) != 1:
        raise CampaignError(
            "Claude MCP boundary has an ambiguous inner proxy roster: "
            f"{candidates!r}"
        )
    if not monitors:
        raise CampaignError(
            "Claude MCP inner proxy has no separately identified bubblewrap "
            "monitor"
        )
    monitor_proofs: list[dict[str, Any]] = []
    for pid in monitors:
        retained: list[dict[str, Any]] = []
        try:
            descriptors = list(
                (Path("/proc") / str(pid) / "fd").iterdir()
            )
        except (FileNotFoundError, PermissionError, OSError) as exc:
            raise CampaignError(
                f"cannot inspect Claude MCP bwrap monitor descriptors: {exc}"
            ) from exc
        for descriptor in descriptors:
            try:
                descriptor_stat = descriptor.stat()
                target = os.readlink(descriptor)
            except FileNotFoundError:
                continue
            except (PermissionError, OSError) as exc:
                raise CampaignError(
                    f"cannot inspect MCP monitor descriptor {descriptor}: {exc}"
                ) from exc
            if (
                (descriptor_stat.st_dev, descriptor_stat.st_ino)
                in auth_inodes
                or str(boundary["provider_home"]) in target
                or "/provider-auth" in target
            ):
                retained.append(
                    {"fd": descriptor.name, "target": target}
                )
        if retained:
            raise CampaignError(
                "Claude MCP bwrap monitor inherited provider auth "
                f"descriptors: {retained!r}"
            )
        monitor_proofs.append(
            {
                "pid": pid,
                "role": "outer bubblewrap monitor; not the model tool process",
                "retained_provider_auth_descriptors": [],
            }
        )
    proofs: list[dict[str, Any]] = []
    for pid in candidates:
        root = Path("/proc") / str(pid) / "root"
        forbidden_visible: list[str] = []
        for forbidden in (
            HOST_SOURCE_ROOT,
            PROVIDER_AUTH_MOUNT,
            boundary["provider_home"],
        ):
            candidate = root / str(forbidden).lstrip("/")
            try:
                os.lstat(candidate)
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise CampaignError(
                    "cannot prove Claude MCP proxy path absence: "
                    f"{forbidden}: {exc}"
                ) from exc
            forbidden_visible.append(str(forbidden))
        if forbidden_visible:
            raise CampaignError(
                "Claude MCP proxy can see forbidden paths: "
                f"{forbidden_visible!r}"
            )
        net = os.readlink(Path("/proc") / str(pid) / "ns/net")
        if net == host_net:
            raise CampaignError("Claude MCP proxy retained host networking")
        try:
            environment = (
                Path("/proc") / str(pid) / "environ"
            ).read_bytes().split(b"\0")
        except (FileNotFoundError, PermissionError, OSError) as exc:
            raise CampaignError(
                f"cannot inspect Claude MCP proxy environment: {exc}"
            ) from exc
        forbidden_environment = [
            value.decode("utf-8", errors="replace").split("=", 1)[0]
            for value in environment
            if value.startswith(
                (b"CLAUDE_", b"ANTHROPIC_", b"CODEX_", b"MAUDE_LAB_")
            )
        ]
        if forbidden_environment:
            raise CampaignError(
                "Claude MCP proxy inherited forbidden environment names: "
                f"{forbidden_environment!r}"
            )
        retained_auth_descriptors: list[dict[str, Any]] = []
        try:
            descriptors = list(
                (Path("/proc") / str(pid) / "fd").iterdir()
            )
        except (FileNotFoundError, PermissionError, OSError) as exc:
            raise CampaignError(
                f"cannot inspect Claude MCP proxy descriptors: {exc}"
            ) from exc
        for descriptor in descriptors:
            try:
                descriptor_stat = descriptor.stat()
                target = os.readlink(descriptor)
            except FileNotFoundError:
                continue
            except (PermissionError, OSError) as exc:
                raise CampaignError(
                    f"cannot inspect Claude MCP descriptor {descriptor}: {exc}"
                ) from exc
            if (
                (descriptor_stat.st_dev, descriptor_stat.st_ino)
                in auth_inodes
                or str(boundary["provider_home"]) in target
                or "/provider-auth" in target
            ):
                retained_auth_descriptors.append(
                    {
                        "fd": descriptor.name,
                        "target": target,
                    }
                )
        if retained_auth_descriptors:
            raise CampaignError(
                "Claude MCP proxy inherited provider auth descriptors: "
                f"{retained_auth_descriptors!r}"
            )
        proofs.append(
            {
                "pid": pid,
                "network_namespace": net,
                "host_network_namespace": host_net,
                "network_namespace_distinct": True,
                "provider_auth_visible": False,
                "host_source_visible": False,
                "provider_private_home_visible": False,
                "forbidden_environment_names": [],
                "retained_provider_auth_descriptors": [],
            }
        )
    return {
        "observed_at": _utc_now(),
        "outer_bubblewrap_monitor_pids": sorted(monitors),
        "outer_bubblewrap_monitor_proofs": monitor_proofs,
        "proxy_processes": proofs,
        "allowed_tools": boundary["allowed_tools"],
    }


def _wait_path_with_process(
    path: Path,
    process: ManagedProcess,
    *,
    timeout: float = 30.0,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file():
            return
        if process.process.poll() is not None:
            raise CampaignError(
                f"boundary process exited before readiness {path}: "
                f"{process.process.returncode}"
            )
        time.sleep(0.02)
    raise CampaignError(f"timed out waiting for boundary readiness: {path}")


def _clean_boundary_process_environment(home: Path) -> dict[str, str]:
    home.mkdir(parents=True, exist_ok=True)
    temporary = home / "tmp"
    temporary.mkdir(exist_ok=True)
    return {
        "HOME": str(home),
        "TMPDIR": str(temporary),
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
    }


def _stop_managed_boundary_process(
    process: ManagedProcess,
    *,
    label: str,
    wait_for_graceful_exit: bool = False,
) -> dict[str, Any]:
    observed = _claude_process_descendants(process.process.pid)
    pidfds: dict[int, int] = {}
    for pid in observed:
        try:
            pidfds[pid] = os.pidfd_open(pid)
        except ProcessLookupError:
            continue
        except (PermissionError, OSError) as exc:
            raise CampaignError(
                f"cannot retain {label} process identity for pid {pid}: {exc}"
            ) from exc
    graceful_timeout = False
    if wait_for_graceful_exit:
        try:
            exit_code = process.wait(timeout=15.0)
        except subprocess.TimeoutExpired:
            graceful_timeout = True
            exit_code = process.stop()
    else:
        exit_code = process.stop()
    remaining: list[int] = []
    try:
        for _ in range(200):
            remaining = []
            for pid, pidfd in pidfds.items():
                poller = select.poll()
                poller.register(pidfd, select.POLLIN)
                if not poller.poll(0):
                    remaining.append(pid)
            if not remaining:
                break
            time.sleep(0.01)
        if remaining:
            for pid, pidfd in pidfds.items():
                if pid in remaining:
                    with contextlib.suppress(ProcessLookupError):
                        signal.pidfd_send_signal(pidfd, signal.SIGKILL)
            raise CampaignError(
                f"{label} left processes after cleanup: {remaining!r}"
            )
        if graceful_timeout:
            raise CampaignError(
                f"{label} did not exit after its graceful shutdown request"
            )
    finally:
        for pidfd in pidfds.values():
            with contextlib.suppress(OSError):
                os.close(pidfd)
    return {
        "label": label,
        "observed_processes": observed,
        "exit_code": exit_code,
        "graceful_exit_requested": wait_for_graceful_exit,
        "forced_after_graceful_timeout": graceful_timeout,
        "remaining_processes": [],
    }


def _stop_pty_boundary_process(
    process: ManagedProcess,
    *,
    label: str,
    pty: dict[str, Any],
    provider_absent_or_exited: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    shutdown_path = Path(pty["shutdown_host"])
    cleanup_path = Path(pty["cleanup_host"])
    try:
        if provider_absent_or_exited is not True:
            raise CampaignError(
                f"{label} shutdown requested before provider exit"
            )
        if (
            shutdown_path.exists()
            or shutdown_path.is_symlink()
            or cleanup_path.exists()
            or cleanup_path.is_symlink()
        ):
            raise CampaignError(
                f"{label} graceful-shutdown evidence path already exists"
            )
        request = {
            "schema": (
                "maude.synthetic-operator.pty-broker-shutdown-request.v1"
            ),
            "request_id": uuid.uuid4().hex,
            "requested_at": _utc_now(),
        }
        write_json(shutdown_path, request)
        process_record = _stop_managed_boundary_process(
            process,
            label=label,
            wait_for_graceful_exit=True,
        )
        if not cleanup_path.is_file() or cleanup_path.is_symlink():
            raise CampaignError(
                f"{label} exited without a regular cleanup report"
            )
        cleanup = load_json(cleanup_path)
        if (
            cleanup.get("schema")
            != "maude.synthetic-operator.pty-broker-cleanup.v1"
            or cleanup.get("shutdown_mode") != "request-file"
            or cleanup.get("shutdown_request") != request
            or cleanup.get("shutdown_request_removed") is not True
            or cleanup.get("socket_removed") is not True
            or cleanup.get("all_tracked_ptys_stopped") is not True
            or cleanup.get("remaining") not in (None, [])
            or shutdown_path.exists()
            or Path(pty["socket_host"]).exists()
            or process_record.get("exit_code") != 0
            or process_record.get("remaining_processes") != []
        ):
            raise CampaignError(
                f"{label} graceful-shutdown cleanup proof is invalid"
            )
        process_record["graceful_shutdown_request"] = request
        process_record["cleanup_report"] = file_record(
            cleanup_path, relative_to=cleanup_path.parent
        )
        process_record["socket_removed"] = True
        process_record["shutdown_control_boundary"] = {
            "path_visibility": "shared-persistent-pty-namespace",
            "created_after_provider_absent_or_exited": True,
            "contains_authority_or_secret": False,
            "request_fields": sorted(request),
            "tamper_or_preexistence_policy": "fail-closed-then-force-stop",
        }
        return process_record, cleanup
    except BaseException:
        if process.process.poll() is None:
            with contextlib.suppress(Exception):
                process.stop()
        raise


def _copy_if_file(source: Path, destination: Path) -> dict[str, Any] | None:
    if not source.is_file():
        return None
    _copy_file(source, destination)
    return file_record(destination, relative_to=destination.parent)


def _run_claude_mcp_process(
    argv: list[str],
    *,
    cwd: Path,
    stdout_path: Path,
    stderr_path: Path,
    timeout: int,
    provider_home: Path,
    copied_auth: list[str],
    credential_values: list[bytes],
    gate_record_path: Path,
    boundary: dict[str, Any],
    user_prompt: str,
    process_env: dict[str, str],
) -> dict[str, Any]:
    """Run host Claude transport with all model actions behind fixed MCP."""

    if argv[:1] != [str(CLAUDE_HOST_BINARY)]:
        raise CampaignError("Claude transport must execute the pinned host binary")
    if cwd != boundary["transport_cwd"]:
        raise CampaignError("Claude transport cwd is not the neutral private cwd")
    expected_auth_paths = [provider_home / value for value in copied_auth]
    if not expected_auth_paths or not all(path.is_file() for path in expected_auth_paths):
        raise CampaignError("Claude private transport auth is incomplete")
    if process_env != boundary["provider_environment"]:
        raise CampaignError("Claude transport environment differs from boundary")
    auth_inodes = {
        (path.stat().st_dev, path.stat().st_ino) for path in expected_auth_paths
    }
    gate_record_path.parent.mkdir(parents=True, exist_ok=True)
    boundary_evidence = gate_record_path.parent / "claude-mcp-boundary"
    boundary_evidence.mkdir(exist_ok=False)
    write_json(
        boundary_evidence / "declared-boundary.json",
        _claude_boundary_record(boundary),
    )

    command_broker: ManagedProcess | None = None
    pty_broker: ManagedProcess | None = None
    provider_process: subprocess.Popen[bytes] | None = None
    known_pidfds: dict[int, int] = {}
    identity: dict[str, Any] | None = None
    actions: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    proxy_proofs: list[dict[str, Any]] = []
    prompt_sent = False
    prompt_event = {
        "type": "user",
        "message": {"role": "user", "content": user_prompt},
    }
    prompt_bytes = _canonical_json_bytes(prompt_event) + b"\n"
    started = _utc_now()
    started_monotonic = time.monotonic()
    timed_out = False
    returncode: int | None = None
    auth_destroyed = False
    broker_cleanup: dict[str, Any] = {}
    output_leak_hits: list[str] = []
    transport_metadata_path_disclosures: list[dict[str, Any]] = []

    def persist(status: str, **extra: Any) -> None:
        value = {
            "schema": "maude.synthetic-operator.claude-provider-boundary.v1",
            "provider_config": "anthropic-sonnet",
            "status": status,
            "provider_transport_outside_task_sandbox": True,
            "provider_auth_retained_until_transport_exit": True,
            "provider_auth_mounted_in_mcp_or_command": False,
            "host_source_mounted_in_mcp_or_command": False,
            "allowed_tools": boundary["allowed_tools"],
            "built_in_tools_allowed": [],
            "mcp_protocol_version": CLAUDE_MCP_PROTOCOL_VERSION,
            "mcp_config_sha256": boundary["mcp_config_sha256"],
            "provider_auth_files": copied_auth,
            "provider_auth_values_recorded": False,
            "transport_metadata_path_disclosures": (
                transport_metadata_path_disclosures
            ),
            "prompt_sent_after_tools_list_flush": prompt_sent,
            "prompt_event_sha256": sha256_bytes(prompt_bytes),
            "identity": identity,
            "tool_actions": actions,
            "tool_results": results,
            "proxy_runtime_proofs": proxy_proofs,
            "provider_auth_destroyed": auth_destroyed,
            "recorded_at": _utc_now(),
            **extra,
        }
        write_json(gate_record_path, value)

    def remember_tree() -> None:
        if provider_process is None:
            return
        for pid in _claude_process_descendants(provider_process.pid):
            if pid in known_pidfds:
                continue
            try:
                known_pidfds[pid] = os.pidfd_open(pid)
            except ProcessLookupError:
                continue
            except (PermissionError, OSError) as exc:
                raise CampaignError(
                    f"cannot retain Claude process identity for pid {pid}: {exc}"
                ) from exc

    def live_known() -> list[int]:
        live: list[int] = []
        for pid, pidfd in known_pidfds.items():
            poller = select.poll()
            poller.register(pidfd, select.POLLIN)
            if not poller.poll(0):
                live.append(pid)
        return sorted(live)

    def stop_provider(sig: signal.Signals) -> None:
        if provider_process is not None and provider_process.poll() is None:
            remember_tree()
            with contextlib.suppress(ProcessLookupError):
                os.killpg(provider_process.pid, sig)
        for pidfd in known_pidfds.values():
            with contextlib.suppress(ProcessLookupError):
                signal.pidfd_send_signal(pidfd, sig)

    def scan_output(
        data: bytes,
        label: str,
        *,
        include_forbidden_paths: bool,
    ) -> None:
        hits: list[str] = []
        for token in credential_values:
            if len(token) >= 8 and token in data:
                hits.append("copied credential value")
        for pattern in OBVIOUS_SECRET_PATTERNS:
            if pattern.search(data):
                hits.append(f"secret pattern {pattern.pattern!r}")
        if include_forbidden_paths:
            for forbidden in (
                str(HOST_SOURCE_ROOT).encode(),
                str(provider_home).encode(),
            ):
                if forbidden in data:
                    hits.append(
                        "forbidden source/auth path "
                        + forbidden.decode(errors="replace")
                    )
        if hits:
            output_leak_hits.extend(
                f"{label}: {hit}" for hit in hits if f"{label}: {hit}" not in output_leak_hits
            )
            raise CampaignError(
                f"Claude {label} exposed forbidden source/auth material: "
                f"{hits!r}"
            )

    def process_event(event: Any, event_number: int) -> None:
        nonlocal identity
        if not isinstance(event, dict):
            raise CampaignError("Claude stream event is not an object")
        disclosures = _claude_event_path_disclosures(
            event,
            provider_home=provider_home,
            event_number=event_number,
        )
        transport_metadata_path_disclosures.extend(disclosures["allowed"])
        if disclosures["forbidden"]:
            hits = [
                (
                    "forbidden source/auth path in parsed provider event "
                    f"{item['event_type']}/{item['event_subtype']} at "
                    f"{item['json_pointer']} ({item['path_kind']})"
                )
                for item in disclosures["forbidden"]
            ]
            output_leak_hits.extend(
                f"stdout: {hit}"
                for hit in hits
                if f"stdout: {hit}" not in output_leak_hits
            )
            raise CampaignError(
                "Claude stdout exposed forbidden source/auth material: "
                f"{hits!r}"
            )
        if event.get("type") == "system" and event.get("subtype") == "init":
            if identity is not None:
                raise CampaignError("Claude emitted a repeated init event")
            reported = event.get("tools")
            if (
                not isinstance(reported, list)
                or not all(isinstance(value, str) for value in reported)
                or reported != boundary["allowed_tools"]
                or len(set(reported)) != len(reported)
            ):
                raise CampaignError(
                    "Claude provider tool roster differs from the exact MCP "
                    f"boundary: reported={reported!r} "
                    f"expected={boundary['allowed_tools']!r}"
                )
            session_id = event.get("session_id")
            if not isinstance(session_id, str) or not session_id:
                raise CampaignError("Claude init event has no session identity")
            identity = {
                "event_number": event_number,
                "provider_session_id": session_id,
                "provider_reported_model": event.get("model"),
                "provider_reported_tools": reported,
                "auth_files_present_at_identity": all(
                    path.is_file() for path in expected_auth_paths
                ),
            }
            if not identity["auth_files_present_at_identity"]:
                raise CampaignError(
                    "Claude transport auth vanished before session identity"
                )
        for block in _recursive_blocks(event, "tool_use"):
            tool_id = block.get("id")
            tool = block.get("name")
            arguments = block.get("input")
            if (
                not isinstance(tool_id, str)
                or not tool_id
                or any(value["tool_use_id"] == tool_id for value in actions)
            ):
                raise CampaignError("Claude tool action identity is invalid")
            if tool not in boundary["allowed_tools"]:
                raise CampaignError(
                    f"Claude attempted undeclared/non-MCP action: {tool!r}"
                )
            if not isinstance(arguments, dict):
                raise CampaignError("Claude MCP action arguments are not an object")
            proof = _claude_proxy_runtime_proof(
                int(provider_process.pid), boundary, auth_inodes
            )
            proxy_proofs.append(proof)
            actions.append(
                {
                    "event_number": event_number,
                    "tool_use_id": tool_id,
                    "tool": tool,
                    "arguments": arguments,
                    "arguments_sha256": sha256_bytes(
                        _canonical_json_bytes(arguments)
                    ),
                }
            )
        for block in _recursive_blocks(event, "tool_result"):
            tool_id = block.get("tool_use_id")
            if (
                not isinstance(tool_id, str)
                or not tool_id
                or any(value["tool_use_id"] == tool_id for value in results)
            ):
                raise CampaignError("Claude tool result identity is invalid")
            text = _claude_tool_result_text(block)
            if text is None:
                raise CampaignError(
                    "Claude MCP tool result is not one exact text block"
                )
            results.append(
                {
                    "event_number": event_number,
                    "tool_use_id": tool_id,
                    "is_error": bool(block.get("is_error", False)),
                    "result_text": text,
                    "result_text_sha256": sha256_bytes(text.encode("utf-8")),
                }
            )

    try:
        pty = boundary.get("pty_broker")
        if isinstance(pty, dict):
            pty_argv = _pty_broker_bwrap_argv(boundary)
            write_json(
                boundary_evidence / "pty-broker-invocation.json",
                {
                    "argv": pty_argv,
                    "provider_auth_mounted": False,
                    "host_source_mounted": False,
                    "external_network": False,
                },
            )
            pty_broker = ManagedProcess(
                pty_argv,
                cwd=boundary["transport_cwd"],
                stdout_path=pty["private_state"] / "broker.stdout",
                stderr_path=pty["private_state"] / "broker.stderr",
                env=_clean_boundary_process_environment(
                    boundary["private_state"] / "pty-broker-host-home"
                ),
            )
            _wait_path_with_process(pty["ready_host"], pty_broker)
        broker = boundary.get("command_broker")
        if isinstance(broker, dict):
            broker_env = _clean_boundary_process_environment(
                boundary["private_state"] / "command-broker-home"
            )
            command_broker = ManagedProcess(
                broker["argv"],
                cwd=boundary["transport_cwd"],
                stdout_path=broker["stdout"],
                stderr_path=broker["stderr"],
                env=broker_env,
            )
            _wait_path_with_process(broker["ready"], command_broker)

        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stderr_path.parent.mkdir(parents=True, exist_ok=True)
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            provider_process = subprocess.Popen(
                argv,
                cwd=cwd,
                env=process_env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=stderr,
                start_new_session=True,
                close_fds=True,
            )
            if provider_process.stdout is None or provider_process.stdin is None:
                raise CampaignError("Claude stream pipes were not created")
            remember_tree()
            selector = selectors.DefaultSelector()
            selector.register(provider_process.stdout, selectors.EVENT_READ)
            pending = b""
            event_number = 0
            deadline = started_monotonic + timeout
            while True:
                remember_tree()
                if isinstance(broker, dict) and (
                    command_broker is None
                    or command_broker.process.poll() is not None
                ):
                    raise CampaignError(
                        "Claude command broker exited during the session"
                    )
                if isinstance(pty, dict) and (
                    pty_broker is None or pty_broker.process.poll() is not None
                ):
                    raise CampaignError(
                        "Claude persistent PTY broker exited during the session"
                    )
                if not prompt_sent and boundary["proxy_ready"].is_file():
                    ready = load_json(boundary["proxy_ready"])
                    readiness_trace = [
                        json.loads(line)
                        for line in boundary["proxy_trace"].read_text(
                            encoding="utf-8"
                        ).splitlines()
                        if line.strip()
                    ]
                    initialize_flushes = [
                        value
                        for value in readiness_trace
                        if value.get("protocol_event")
                        == "initialize-response-flushed"
                    ]
                    initialized_notifications = [
                        value
                        for value in readiness_trace
                        if value.get("protocol_event")
                        == "notifications/initialized"
                    ]
                    tools_list_flushes = [
                        value
                        for value in readiness_trace
                        if value.get("protocol_event")
                        == "tools-list-response-flushed"
                    ]
                    expected_bare = [
                        value.rsplit("__", 1)[-1]
                        for value in boundary["allowed_tools"]
                    ]
                    if (
                        ready.get("protocol_version_requested")
                        != CLAUDE_MCP_PROTOCOL_VERSION
                        or ready.get("protocol_version_negotiated")
                        != CLAUDE_MCP_PROTOCOL_VERSION
                        or ready.get("tools") != expected_bare
                        or not isinstance(
                            ready.get("tools_list_response_sha256"), str
                        )
                        or len(initialize_flushes) != 1
                        or len(initialized_notifications) != 1
                        or len(tools_list_flushes) != 1
                        or initialize_flushes[0].get("initialize_accepted")
                        is not True
                        or initialize_flushes[0].get(
                            "protocol_version_requested"
                        )
                        != CLAUDE_MCP_PROTOCOL_VERSION
                        or initialize_flushes[0].get(
                            "protocol_version_negotiated"
                        )
                        != CLAUDE_MCP_PROTOCOL_VERSION
                        or initialized_notifications[0].get(
                            "protocol_version"
                        )
                        != CLAUDE_MCP_PROTOCOL_VERSION
                        or tools_list_flushes[0].get("protocol_version")
                        != CLAUDE_MCP_PROTOCOL_VERSION
                        or ready.get("initialize_message_ordinal")
                        != initialize_flushes[0].get("message_ordinal")
                        or ready.get("tools_list_message_ordinal")
                        != tools_list_flushes[0].get("message_ordinal")
                        or not isinstance(
                            ready.get("initialize_message_ordinal"), int
                        )
                        or not isinstance(
                            ready.get("tools_list_message_ordinal"), int
                        )
                        or ready["initialize_message_ordinal"]
                        >= ready["tools_list_message_ordinal"]
                        or ready.get("tools_list_response_sha256")
                        != tools_list_flushes[0].get("response_sha256")
                    ):
                        raise CampaignError(
                            "Claude MCP readiness record does not prove the "
                            "frozen protocol/roster"
                        )
                    provider_process.stdin.write(prompt_bytes)
                    provider_process.stdin.flush()
                    provider_process.stdin.close()
                    prompt_sent = True
                    persist("running")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    break
                ready_events = selector.select(timeout=min(0.1, remaining))
                if not ready_events:
                    if provider_process.poll() is not None:
                        chunk = provider_process.stdout.read()
                        if chunk:
                            scan_output(
                                chunk,
                                "stdout",
                                include_forbidden_paths=False,
                            )
                            stdout.write(chunk)
                            pending += chunk
                        break
                    continue
                chunk = os.read(provider_process.stdout.fileno(), 65536)
                if not chunk:
                    break
                scan_output(
                    chunk,
                    "stdout",
                    include_forbidden_paths=False,
                )
                stdout.write(chunk)
                stdout.flush()
                pending += chunk
                while b"\n" in pending:
                    line, pending = pending.split(b"\n", 1)
                    if not line.strip():
                        continue
                    scan_output(
                        line,
                        "stdout",
                        include_forbidden_paths=False,
                    )
                    event_number += 1
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise CampaignError(
                            "Claude emitted non-JSON stream output"
                        ) from exc
                    process_event(event, event_number)
            selector.close()
            if pending.strip():
                raise CampaignError(
                    "Claude stream ended with a partial JSON event"
                )
            if not prompt_sent:
                raise CampaignError(
                    "Claude MCP never reached flushed tools/list readiness; "
                    "semantic prompt was withheld"
                )
            if timed_out:
                stop_provider(signal.SIGTERM)
                try:
                    returncode = provider_process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    stop_provider(signal.SIGKILL)
                    returncode = provider_process.wait(timeout=10)
            else:
                try:
                    returncode = provider_process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    stop_provider(signal.SIGTERM)
                    try:
                        returncode = provider_process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        stop_provider(signal.SIGKILL)
                        returncode = provider_process.wait(timeout=10)
        scan_output(
            stderr_path.read_bytes(),
            "stderr",
            include_forbidden_paths=True,
        )
        if identity is None:
            raise CampaignError("Claude stream ended without an init identity")
        if any(not path.is_file() for path in expected_auth_paths):
            raise CampaignError(
                "Claude private auth did not remain present through transport exit"
            )
        live = live_known()
        if live:
            stop_provider(signal.SIGKILL)
            time.sleep(0.1)
            live = live_known()
        if live:
            raise CampaignError(
                f"Claude provider/MCP process remained after exit: {live!r}"
            )
        auth_inventory_before_destroy = inventory_files(provider_home)
        shutil.rmtree(provider_home)
        auth_destroyed = not provider_home.exists()
        if not auth_destroyed:
            raise CampaignError("Claude private auth tree could not be destroyed")

        proxy_trace_records = [
            json.loads(line)
            for line in boundary["proxy_trace"].read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip()
        ]
        proxy_calls = [
            value for value in proxy_trace_records if "tool" in value
        ]
        if len(actions) != len(results) or len(actions) != len(proxy_calls):
            raise CampaignError(
                "Claude tool_use/proxy/result correlation is not one-to-one: "
                f"actions={len(actions)} proxy={len(proxy_calls)} "
                f"results={len(results)}"
            )
        action_by_id = {value["tool_use_id"]: value for value in actions}
        result_by_id = {value["tool_use_id"]: value for value in results}
        if set(action_by_id) != set(result_by_id):
            raise CampaignError("Claude tool results do not match tool identities")
        for action, proxy_call in zip(actions, proxy_calls, strict=True):
            result = result_by_id[action["tool_use_id"]]
            if (
                proxy_call.get("tool")
                != action["tool"].rsplit("__", 1)[-1]
                or proxy_call.get("arguments_sha256")
                != action["arguments_sha256"]
                or proxy_call.get("result_text_sha256")
                != result["result_text_sha256"]
                or bool(proxy_call.get("is_error"))
                != bool(result["is_error"])
            ):
                raise CampaignError(
                    "Claude provider/proxy action-result digest mismatch"
                )
        broker_calls: list[dict[str, Any]] = []
        if isinstance(broker, dict):
            if broker["trace"].is_file():
                broker_calls = [
                    json.loads(line)
                    for line in broker["trace"].read_text(
                        encoding="utf-8"
                    ).splitlines()
                    if line.strip()
                ]
            elif proxy_calls:
                raise CampaignError(
                    "Claude proxy recorded a tool call but the command broker "
                    "produced no correlation trace"
                )
            if len(broker_calls) != len(proxy_calls):
                raise CampaignError(
                    "Claude proxy/broker command correlation is not one-to-one"
                )
            for proxy_call, broker_call in zip(
                proxy_calls, broker_calls, strict=True
            ):
                if (
                    proxy_call.get("correlation_id")
                    != broker_call.get("request_id")
                    or proxy_call.get("result_text_sha256")
                    != sha256_bytes(
                        _canonical_json_bytes(broker_call.get("result"))
                    )
                ):
                    raise CampaignError(
                        "Claude proxy/broker correlation digest mismatch"
                    )
        persist(
            "provider-exited-auth-destroyed",
            provider_returncode=returncode,
            provider_timed_out=timed_out,
            auth_inventory_before_destroy=auth_inventory_before_destroy,
            exact_correlation_proved=True,
            proxy_tool_call_count=len(proxy_calls),
            broker_command_count=len(broker_calls),
        )
    except BaseException as exc:
        if provider_process is not None:
            stop_provider(signal.SIGKILL)
            with contextlib.suppress(
                subprocess.TimeoutExpired, ProcessLookupError, OSError
            ):
                provider_process.wait(timeout=10)
        if provider_home.exists():
            shutil.rmtree(provider_home)
        auth_destroyed = not provider_home.exists()
        persist(
            "failed-closed",
            error=str(exc),
            exception_type=type(exc).__name__,
            provider_tree_remaining=live_known(),
        )
        if output_leak_hits:
            quarantine = (
                QUARANTINE_ROOT
                / f"claude-boundary-{uuid.uuid4().hex}"
            )
            quarantine.mkdir(parents=True, mode=0o700)
            quarantined: list[str] = []
            for path in (stdout_path, stderr_path):
                if path.exists():
                    destination = quarantine / path.name
                    shutil.move(str(path), destination)
                    quarantined.append(str(destination))
            write_json(
                gate_record_path.parent
                / "credential-redaction-notice.json",
                {
                    "schema": (
                        "maude.synthetic-operator."
                        "credential-quarantine.v1"
                    ),
                    "run_id": boundary["label"],
                    "hits": output_leak_hits,
                    "quarantine": str(quarantine),
                    "quarantined_files": quarantined,
                    "raw_output_committable": False,
                },
            )
        raise
    finally:
        cleanup_errors: list[str] = []
        if command_broker is not None:
            try:
                broker_cleanup["command_broker"] = (
                    _stop_managed_boundary_process(
                        command_broker,
                        label="Claude command broker",
                    )
                )
            except CampaignError as exc:
                cleanup_errors.append(str(exc))
        if pty_broker is not None:
            pty = boundary.get("pty_broker")
            try:
                if not isinstance(pty, dict):
                    raise CampaignError(
                        "Claude persistent PTY broker declaration missing"
                    )
                (
                    broker_cleanup["pty_broker"],
                    broker_cleanup["pty_cleanup"],
                    ) = _stop_pty_boundary_process(
                        pty_broker,
                        label="Claude persistent PTY broker",
                        pty=pty,
                        provider_absent_or_exited=(
                            provider_process is None
                            or provider_process.poll() is not None
                        ),
                    )
            except CampaignError as exc:
                cleanup_errors.append(str(exc))
            if isinstance(pty, dict) and pty["cleanup_host"].is_file():
                cleanup = load_json(pty["cleanup_host"])
                broker_cleanup["pty_cleanup"] = cleanup
                if (
                    not cleanup.get("all_tracked_ptys_stopped")
                    or cleanup.get("remaining")
                ):
                    cleanup_errors.append(
                        "persistent PTY broker cleanup left a process alive"
                    )
        remaining_before_pidfd_close = live_known()
        for source, name in (
            (boundary["proxy_ready"], "proxy-ready.json"),
            (boundary["proxy_trace"], "proxy-trace.jsonl"),
        ):
            _copy_if_file(source, boundary_evidence / name)
        broker = boundary.get("command_broker")
        if isinstance(broker, dict):
            for key, name in (
                ("ready", "command-broker-ready.json"),
                ("trace", "command-broker-trace.jsonl"),
                ("stdout", "command-broker.stdout"),
                ("stderr", "command-broker.stderr"),
                ("policy", "command-policy.json"),
            ):
                _copy_if_file(broker[key], boundary_evidence / name)
        pty = boundary.get("pty_broker")
        if isinstance(pty, dict):
            for source, name in (
                (pty["ready_host"], "pty-broker-ready.json"),
                (pty["cleanup_host"], "pty-broker-cleanup.json"),
                (pty["private_state"] / "broker.stdout", "pty-broker.stdout"),
                (pty["private_state"] / "broker.stderr", "pty-broker.stderr"),
            ):
                _copy_if_file(source, boundary_evidence / name)
        socket_arena_cleanup = _release_private_socket_directories(boundary)
        broker_cleanup["private_socket_arena"] = socket_arena_cleanup
        if not socket_arena_cleanup["all_removed"]:
            cleanup_errors.append(
                "private Unix-socket arena retained a socket or other entry"
            )
        write_json(
            boundary_evidence / "cleanup.json",
            {
                "schema": (
                    "maude.synthetic-operator.claude-boundary-cleanup.v1"
                ),
                "provider_auth_destroyed": auth_destroyed,
                "provider_processes_remaining": remaining_before_pidfd_close,
                "cleanup_errors": cleanup_errors,
                **broker_cleanup,
            },
        )
        for pidfd in known_pidfds.values():
            with contextlib.suppress(OSError):
                os.close(pidfd)
        known_pidfds.clear()
        if cleanup_errors:
            raise CampaignError(
                "Claude boundary cleanup failed closed: "
                + "; ".join(cleanup_errors)
            )
    persist(
        "complete",
        provider_returncode=returncode,
        provider_timed_out=timed_out,
        boundary_evidence=file_record(
            boundary_evidence / "cleanup.json",
            relative_to=gate_record_path.parent,
        ),
        broker_cleanup=broker_cleanup,
    )
    return {
        "started_at": started,
        "completed_at": _utc_now(),
        "elapsed_seconds": round(time.monotonic() - started_monotonic, 6),
        "returncode": returncode,
        "timed_out": timed_out,
        "fresh_process": True,
        "follow_up_messages": 0,
        "coaching": "none",
        "provider_auth_gate": load_json(gate_record_path),
        "claude_mcp_boundary": _claude_boundary_record(boundary),
    }


def _codex_normalized_mcp_result_text(result: Any) -> str:
    """Extract the exact text payload emitted by Codex 0.145.0 MCP events."""

    if (
        not isinstance(result, dict)
        or set(result) != {"content", "structured_content"}
        or result.get("structured_content") is not None
    ):
        raise CampaignError(
            "Codex MCP result is not the exact normalized result envelope"
        )
    content = result.get("content")
    if not isinstance(content, list) or len(content) != 1:
        raise CampaignError(
            "Codex MCP result does not contain exactly one content block"
        )
    block = content[0]
    if (
        not isinstance(block, dict)
        or set(block) != {"type", "text"}
        or block.get("type") != "text"
        or not isinstance(block.get("text"), str)
    ):
        raise CampaignError(
            "Codex MCP result content is not one exact text block"
        )
    return block["text"]


def _run_codex_retained_process(
    argv: list[str],
    *,
    cwd: Path,
    stdout_path: Path,
    stderr_path: Path,
    timeout: int,
    provider_home: Path,
    copied_auth: list[str],
    credential_values: list[bytes],
    gate_record_path: Path,
    boundary: dict[str, Any],
    stdin_payload: bytes,
) -> dict[str, Any]:
    """Run Codex transport with copied auth and one strict MCP boundary."""

    auth_paths = [provider_home / relative for relative in copied_auth]
    if not auth_paths or not all(path.is_file() for path in auth_paths):
        raise CampaignError("Codex private transport auth is incomplete")
    if (
        boundary.get("provider_config") != "openai-sol"
        or boundary.get("schema")
        != "maude.synthetic-operator.codex-strict-mcp-boundary.v1"
        or argv[:1] != [str(BWRAP)]
        or cwd != boundary["transport_cwd"]
    ):
        raise CampaignError("Codex strict MCP transport boundary is invalid")
    if not stdin_payload:
        raise CampaignError("Codex stdin prompt payload is empty")
    _validate_codex_strict_argv(argv, boundary)
    started = _utc_now()
    started_monotonic = time.monotonic()
    known_pidfds: dict[int, int] = {}
    identity: dict[str, Any] | None = None
    event_number = 0
    output_leak_hits: list[str] = []
    provider_process: subprocess.Popen[bytes] | None = None
    returncode: int | None = None
    timed_out = False
    auth_destroyed = False
    actions: list[dict[str, Any]] = []
    action_indexes: dict[str, int] = {}
    command_broker: ManagedProcess | None = None
    pty_broker: ManagedProcess | None = None
    broker_cleanup: dict[str, Any] = {}
    boundary_evidence = gate_record_path.parent / "codex-mcp-boundary"
    boundary_evidence.mkdir(exist_ok=False)
    write_json(
        boundary_evidence / "declared-boundary.json",
        _claude_boundary_record(boundary),
    )

    def remember_tree() -> None:
        if provider_process is None:
            return
        for pid in _claude_process_descendants(provider_process.pid):
            if pid in known_pidfds:
                continue
            try:
                known_pidfds[pid] = os.pidfd_open(pid)
            except ProcessLookupError:
                continue
            except (PermissionError, OSError) as exc:
                raise CampaignError(
                    f"cannot retain Codex process identity for pid {pid}: {exc}"
                ) from exc

    def live_known() -> list[int]:
        live: list[int] = []
        for pid, pidfd in known_pidfds.items():
            poller = select.poll()
            poller.register(pidfd, select.POLLIN)
            if not poller.poll(0):
                live.append(pid)
        return sorted(live)

    def stop_provider(sig: signal.Signals) -> None:
        if provider_process is not None and provider_process.poll() is None:
            remember_tree()
            with contextlib.suppress(ProcessLookupError):
                os.killpg(provider_process.pid, sig)
        for pidfd in known_pidfds.values():
            with contextlib.suppress(ProcessLookupError):
                signal.pidfd_send_signal(pidfd, sig)

    def scan_output(data: bytes, label: str) -> None:
        hits: list[str] = []
        for token in credential_values:
            if len(token) >= 8 and token in data:
                hits.append("copied credential value")
        for pattern in OBVIOUS_SECRET_PATTERNS:
            if pattern.search(data):
                hits.append(f"secret pattern {pattern.pattern!r}")
        for forbidden in (
            str(HOST_SOURCE_ROOT).encode(),
            str(provider_home).encode(),
            str(PROVIDER_AUTH_MOUNT).encode(),
        ):
            if forbidden in data:
                hits.append(
                    "forbidden source/auth path "
                    + forbidden.decode(errors="replace")
                )
        if hits:
            output_leak_hits.extend(
                f"{label}: {hit}"
                for hit in hits
                if f"{label}: {hit}" not in output_leak_hits
            )
            raise CampaignError(
                f"Codex {label} exposed forbidden source/auth material: "
                f"{hits!r}"
            )

    def state_summary() -> dict[str, Any]:
        inventory = inventory_files(provider_home)
        return {
            "file_count": len(inventory),
            "total_bytes": sum(int(item["bytes"]) for item in inventory),
            "inventory_sha256": sha256_bytes(
                _canonical_json_bytes(inventory)
            ),
        }

    def persist(status: str, **extra: Any) -> None:
        write_json(
            gate_record_path,
            {
                "schema": (
                    "maude.synthetic-operator."
                    "codex-retained-provider-boundary.v1"
                ),
                "provider_config": "openai-sol",
                "status": status,
                "provider_auth_retained_until_transport_exit": True,
                "provider_auth_values_recorded": False,
                "provider_auth_output_scan_hits": output_leak_hits,
                "provider_auth_destroyed": auth_destroyed,
                "provider_transport_cwd_is_neutral": True,
                "provider_task_paths_mounted": (
                    []
                    if boundary["mode"] == "operator"
                    else ["/evidence (read-only frozen grade bundle)"]
                ),
                "intrinsic_action_features_disabled": list(
                    CODEX_DISABLED_INTRINSIC_ACTION_FEATURES
                ),
                "optional_features_disabled": list(
                    CODEX_DISABLED_OPTIONAL_FEATURES
                ),
                "codex_approval_argv": list(CODEX_APPROVAL_CONFIG_ARGV),
                "codex_approval_config_override": CODEX_APPROVAL_CONFIG,
                "codex_approval_policy": CODEX_APPROVAL_POLICY,
                "noninteractive_approval_safety_basis": boundary[
                    "noninteractive_approval_safety_basis"
                ],
                "codex_mcp_default_tools_approval_mode": boundary[
                    "codex_mcp_default_tools_approval_mode"
                ],
                "codex_mcp_approval_config_override": boundary[
                    "codex_mcp_approval_config_override"
                ],
                "mcp_tool_approval_safety_basis": boundary[
                    "mcp_tool_approval_safety_basis"
                ],
                "unexpected_intrinsic_action_policy": "fail-closed",
                "per_session_exact_tool_roster_supported": True,
                "allowed_mcp_server": boundary["server"],
                "allowed_mcp_tools": boundary["codex_enabled_tools"],
                "mcp_protocol_version": CODEX_MCP_PROTOCOL_VERSION,
                "mcp_config_sha256": boundary["mcp_config_sha256"],
                "semantic_prompt_delivery": "stdin",
                "semantic_prompt_bytes": len(stdin_payload),
                "semantic_prompt_sha256": sha256_bytes(stdin_payload),
                "semantic_prompt_bytes_in_argv": False,
                "identity": identity,
                "tool_actions": actions,
                "recorded_at": _utc_now(),
                **extra,
            },
        )

    def process_event(event: Any) -> None:
        nonlocal identity
        if not isinstance(event, dict):
            raise CampaignError("Codex stream event is not an object")
        if (
            event.get("type") == "thread.started"
            and isinstance(event.get("thread_id"), str)
            and event["thread_id"]
        ):
            if identity is not None:
                raise CampaignError("Codex emitted a repeated thread identity")
            identity = {
                "event_number": event_number,
                "provider_thread_id": event["thread_id"],
            }
            return
        if identity is None:
            raise CampaignError("Codex emitted content before its thread identity")
        item = event.get("item")
        if not (
            isinstance(event.get("type"), str)
            and str(event["type"]).startswith("item.")
            and isinstance(item, dict)
        ):
            return
        item_type = str(item.get("type") or "missing_type")
        if item_type in {"agent_message", "reasoning"}:
            return
        if item_type != "mcp_tool_call":
            raise CampaignError(
                "Codex emitted a forbidden intrinsic/non-MCP action: "
                f"{item_type!r}"
            )
        identity_value = item.get("id")
        server = item.get("server") or item.get("server_name")
        tool = item.get("tool") or item.get("tool_name")
        arguments = item.get("arguments")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError as exc:
                raise CampaignError(
                    "Codex MCP arguments are not valid JSON"
                ) from exc
        if (
            not isinstance(identity_value, str)
            or not identity_value
            or server != boundary["server"]
            or tool not in boundary["codex_enabled_tools"]
            or not isinstance(arguments, dict)
        ):
            raise CampaignError("Codex MCP action differs from the exact roster")
        digest = sha256_bytes(_canonical_json_bytes(arguments))
        existing_index = action_indexes.get(identity_value)
        if existing_index is None:
            action_indexes[identity_value] = len(actions)
            actions.append(
                {
                    "action_id": identity_value,
                    "event_numbers": [event_number],
                    "server": server,
                    "tool": tool,
                    "arguments": arguments,
                    "arguments_sha256": digest,
                    "status": item.get("status"),
                    "result": item.get("result"),
                    "error": item.get("error"),
                    "completed": event.get("type") == "item.completed",
                }
            )
            return
        action = actions[existing_index]
        if (
            action["server"] != server
            or action["tool"] != tool
            or action["arguments_sha256"] != digest
        ):
            raise CampaignError("Codex MCP action changed across events")
        action["event_numbers"].append(event_number)
        action["status"] = item.get("status", action["status"])
        action["result"] = item.get("result", action["result"])
        action["error"] = item.get("error", action["error"])
        action["completed"] = (
            action["completed"] or event.get("type") == "item.completed"
        )

    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    pending = b""
    try:
        pty = boundary.get("pty_broker")
        if isinstance(pty, dict):
            pty_argv = _pty_broker_bwrap_argv(boundary)
            write_json(
                boundary_evidence / "pty-broker-invocation.json",
                {
                    "argv": pty_argv,
                    "provider_auth_mounted": False,
                    "host_source_mounted": False,
                    "external_network": False,
                },
            )
            pty_broker = ManagedProcess(
                pty_argv,
                cwd=boundary["transport_cwd"],
                stdout_path=pty["private_state"] / "broker.stdout",
                stderr_path=pty["private_state"] / "broker.stderr",
                env=_clean_boundary_process_environment(
                    boundary["private_state"] / "pty-broker-host-home"
                ),
            )
            _wait_path_with_process(pty["ready_host"], pty_broker)
        broker = boundary.get("command_broker")
        if isinstance(broker, dict):
            command_broker = ManagedProcess(
                broker["argv"],
                cwd=boundary["transport_cwd"],
                stdout_path=broker["stdout"],
                stderr_path=broker["stderr"],
                env=_clean_boundary_process_environment(
                    boundary["private_state"] / "command-broker-home"
                ),
            )
            _wait_path_with_process(broker["ready"], command_broker)
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            provider_process = subprocess.Popen(
                argv,
                cwd=cwd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=stderr,
                start_new_session=True,
                close_fds=True,
            )
            if provider_process.stdout is None:
                raise CampaignError("Codex stdout pipe was not created")
            if provider_process.stdin is None:
                raise CampaignError("Codex stdin pipe was not created")
            provider_process.stdin.write(stdin_payload)
            provider_process.stdin.close()
            remember_tree()
            selector = selectors.DefaultSelector()
            selector.register(provider_process.stdout, selectors.EVENT_READ)
            deadline = started_monotonic + timeout
            while True:
                remember_tree()
                if isinstance(broker, dict) and (
                    command_broker is None
                    or command_broker.process.poll() is not None
                ):
                    raise CampaignError(
                        "Codex command broker exited during the session"
                    )
                if isinstance(pty, dict) and (
                    pty_broker is None or pty_broker.process.poll() is not None
                ):
                    raise CampaignError(
                        "Codex persistent PTY broker exited during the session"
                    )
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    break
                ready = selector.select(timeout=min(0.1, remaining))
                if not ready:
                    if provider_process.poll() is not None:
                        chunk = provider_process.stdout.read()
                        if chunk:
                            scan_output(chunk, "stdout")
                            stdout.write(chunk)
                            pending += chunk
                        break
                    continue
                chunk = os.read(provider_process.stdout.fileno(), 65536)
                if not chunk:
                    break
                scan_output(chunk, "stdout")
                stdout.write(chunk)
                stdout.flush()
                pending += chunk
                while b"\n" in pending:
                    line, pending = pending.split(b"\n", 1)
                    if not line.strip():
                        continue
                    scan_output(line, "stdout")
                    event_number += 1
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise CampaignError(
                            "Codex emitted non-JSON stream output"
                        ) from exc
                    process_event(event)
            selector.close()
            if pending.strip():
                raise CampaignError(
                    "Codex stream ended with a partial JSON event"
                )
            if timed_out:
                stop_provider(signal.SIGTERM)
                try:
                    returncode = provider_process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    stop_provider(signal.SIGKILL)
                    returncode = provider_process.wait(timeout=10)
            else:
                try:
                    returncode = provider_process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    stop_provider(signal.SIGTERM)
                    try:
                        returncode = provider_process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        stop_provider(signal.SIGKILL)
                        returncode = provider_process.wait(timeout=10)
        if identity is None:
            raise CampaignError("Codex stream ended without a thread identity")
        for path in auth_paths:
            if not path.is_file():
                continue
            for value in _credential_values(path.read_bytes()):
                if value not in credential_values:
                    credential_values.append(value)
        scan_output(stdout_path.read_bytes(), "stdout")
        scan_output(stderr_path.read_bytes(), "stderr")
        for _ in range(100):
            if not live_known():
                break
            time.sleep(0.01)
        remaining = live_known()
        if remaining:
            stop_provider(signal.SIGKILL)
            raise CampaignError(
                f"Codex provider process remained after exit: {remaining!r}"
            )
        private_state = state_summary()
        ready = load_json(boundary["proxy_ready"])
        proxy_records = [
            json.loads(line)
            for line in boundary["proxy_trace"].read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip()
        ]
        proxy_calls = [
            value for value in proxy_records if "tool" in value
        ]
        initialize_flushes = [
            value
            for value in proxy_records
            if value.get("protocol_event")
            == "initialize-response-flushed"
        ]
        initialized_notifications = [
            value
            for value in proxy_records
            if value.get("protocol_event") == "notifications/initialized"
        ]
        tools_list_flushes = [
            value
            for value in proxy_records
            if value.get("protocol_event") == "tools-list-response-flushed"
        ]
        expected_bare = list(boundary["codex_enabled_tools"])
        if (
            ready.get("protocol_version_requested")
            != CODEX_MCP_PROTOCOL_VERSION
            or ready.get("protocol_version_negotiated")
            != CODEX_MCP_PROTOCOL_VERSION
            or ready.get("tools") != expected_bare
            or len(initialize_flushes) != 1
            or len(initialized_notifications) != 1
            or len(tools_list_flushes) != 1
            or initialize_flushes[0].get("initialize_accepted") is not True
            or initialize_flushes[0].get("protocol_version_requested")
            != CODEX_MCP_PROTOCOL_VERSION
            or initialize_flushes[0].get("protocol_version_negotiated")
            != CODEX_MCP_PROTOCOL_VERSION
            or initialized_notifications[0].get("protocol_version")
            != CODEX_MCP_PROTOCOL_VERSION
            or tools_list_flushes[0].get("protocol_version")
            != CODEX_MCP_PROTOCOL_VERSION
            or ready.get("initialize_message_ordinal")
            != initialize_flushes[0].get("message_ordinal")
            or ready.get("tools_list_message_ordinal")
            != tools_list_flushes[0].get("message_ordinal")
            or ready.get("tools_list_response_sha256")
            != tools_list_flushes[0].get("response_sha256")
            or len(actions) != len(proxy_calls)
        ):
            raise CampaignError(
                "Codex MCP readiness/action cardinality proof is invalid"
            )
        result_correlations: list[dict[str, Any]] = []
        for action, proxy_call in zip(actions, proxy_calls, strict=True):
            provider_result_text = _codex_normalized_mcp_result_text(
                action.get("result")
            )
            provider_result_text_sha256 = sha256_bytes(
                provider_result_text.encode("utf-8")
            )
            proxy_result_text = proxy_call.get("result_text")
            proxy_result_text_sha256 = proxy_call.get("result_text_sha256")
            proxy_is_error = proxy_call.get("is_error")
            if (
                action["tool"] != proxy_call.get("tool")
                or action["arguments_sha256"]
                != proxy_call.get("arguments_sha256")
                or action.get("completed") is not True
                or not isinstance(proxy_result_text, str)
                or provider_result_text != proxy_result_text
                or provider_result_text_sha256 != proxy_result_text_sha256
                or sha256_bytes(proxy_result_text.encode("utf-8"))
                != proxy_result_text_sha256
                or type(proxy_is_error) is not bool
            ):
                raise CampaignError(
                    "Codex provider/proxy action-result digest mismatch"
                )
            result_correlations.append(
                {
                    "action_id": action["action_id"],
                    "tool": action["tool"],
                    "arguments_sha256": action["arguments_sha256"],
                    "provider_normalized_result_text_sha256": (
                        provider_result_text_sha256
                    ),
                    "proxy_result_text_sha256": proxy_result_text_sha256,
                    "proxy_is_error": proxy_is_error,
                }
            )
        broker_calls: list[dict[str, Any]] = []
        if isinstance(broker, dict):
            broker_calls = [
                json.loads(line)
                for line in broker["trace"].read_text(
                    encoding="utf-8"
                ).splitlines()
                if line.strip()
            ]
            if len(broker_calls) != len(proxy_calls):
                raise CampaignError(
                    "Codex proxy/broker command cardinality mismatch"
                )
            for proxy_call, broker_call in zip(
                proxy_calls, broker_calls, strict=True
            ):
                if (
                    proxy_call.get("correlation_id")
                    != broker_call.get("request_id")
                    or proxy_call.get("result_text_sha256")
                    != sha256_bytes(
                        _canonical_json_bytes(broker_call.get("result"))
                    )
                ):
                    raise CampaignError(
                        "Codex proxy/broker result digest mismatch"
                    )
        shutil.rmtree(provider_home)
        auth_destroyed = not provider_home.exists()
        if not auth_destroyed:
            raise CampaignError("Codex private transport home was not destroyed")
        persist(
            "complete",
            provider_returncode=returncode,
            provider_timed_out=timed_out,
            provider_private_state_before_destroy=private_state,
            provider_processes_remaining=[],
            exact_correlation_proved=True,
            proxy_tool_call_count=len(proxy_calls),
            normalized_result_correlations=result_correlations,
            broker_command_count=len(broker_calls),
        )
    except BaseException as exc:
        if provider_process is not None:
            stop_provider(signal.SIGKILL)
            with contextlib.suppress(
                subprocess.TimeoutExpired, ProcessLookupError, OSError
            ):
                provider_process.wait(timeout=10)
        if provider_home.exists():
            shutil.rmtree(provider_home)
        auth_destroyed = not provider_home.exists()
        persist(
            "failed-closed",
            error=str(exc),
            exception_type=type(exc).__name__,
            provider_processes_remaining=live_known(),
        )
        if output_leak_hits:
            quarantine = QUARANTINE_ROOT / (
                "codex-boundary-" + uuid.uuid4().hex
            )
            quarantine.mkdir(parents=True, mode=0o700)
            quarantined: list[str] = []
            for path in (stdout_path, stderr_path):
                if path.exists():
                    destination = quarantine / path.name
                    shutil.move(str(path), destination)
                    quarantined.append(str(destination))
            write_json(
                gate_record_path.parent / "credential-redaction-notice.json",
                {
                    "schema": (
                        "maude.synthetic-operator."
                        "credential-quarantine.v1"
                    ),
                    "run_id": gate_record_path.parent.name,
                    "hits": output_leak_hits,
                    "quarantine": str(quarantine),
                    "quarantined_files": quarantined,
                    "raw_output_committable": False,
                },
            )
        raise
    finally:
        cleanup_errors: list[str] = []
        if command_broker is not None:
            try:
                broker_cleanup["command_broker"] = (
                    _stop_managed_boundary_process(
                        command_broker,
                        label="Codex command broker",
                    )
                )
            except CampaignError as exc:
                cleanup_errors.append(str(exc))
        if pty_broker is not None:
            pty = boundary.get("pty_broker")
            try:
                if not isinstance(pty, dict):
                    raise CampaignError(
                        "Codex persistent PTY broker declaration missing"
                    )
                (
                    broker_cleanup["pty_broker"],
                    broker_cleanup["pty_cleanup"],
                    ) = _stop_pty_boundary_process(
                        pty_broker,
                        label="Codex persistent PTY broker",
                        pty=pty,
                        provider_absent_or_exited=(
                            provider_process is None
                            or provider_process.poll() is not None
                        ),
                    )
            except CampaignError as exc:
                cleanup_errors.append(str(exc))
            if isinstance(pty, dict) and pty["cleanup_host"].is_file():
                pty_cleanup = load_json(pty["cleanup_host"])
                broker_cleanup["pty_cleanup"] = pty_cleanup
                if (
                    not pty_cleanup.get("all_tracked_ptys_stopped")
                    or pty_cleanup.get("remaining")
                ):
                    cleanup_errors.append(
                        "persistent PTY broker cleanup left a process alive"
                    )
        for source, name in (
            (boundary["proxy_ready"], "proxy-ready.json"),
            (boundary["proxy_trace"], "proxy-trace.jsonl"),
        ):
            _copy_if_file(source, boundary_evidence / name)
        broker = boundary.get("command_broker")
        if isinstance(broker, dict):
            for key, name in (
                ("ready", "command-broker-ready.json"),
                ("trace", "command-broker-trace.jsonl"),
                ("stdout", "command-broker.stdout"),
                ("stderr", "command-broker.stderr"),
                ("policy", "command-policy.json"),
            ):
                _copy_if_file(broker[key], boundary_evidence / name)
        pty = boundary.get("pty_broker")
        if isinstance(pty, dict):
            for source, name in (
                (pty["ready_host"], "pty-broker-ready.json"),
                (pty["cleanup_host"], "pty-broker-cleanup.json"),
                (pty["private_state"] / "broker.stdout", "pty-broker.stdout"),
                (pty["private_state"] / "broker.stderr", "pty-broker.stderr"),
            ):
                _copy_if_file(source, boundary_evidence / name)
        socket_cleanup = _release_private_socket_directories(boundary)
        broker_cleanup["private_socket_arena"] = socket_cleanup
        if not socket_cleanup["all_removed"]:
            cleanup_errors.append(
                "private Unix-socket arena retained a socket or other entry"
            )
        write_json(
            boundary_evidence / "cleanup.json",
            {
                "schema": (
                    "maude.synthetic-operator.codex-boundary-cleanup.v1"
                ),
                "provider_auth_destroyed": auth_destroyed,
                "provider_processes_remaining": live_known(),
                "cleanup_errors": cleanup_errors,
                **broker_cleanup,
            },
        )
        for pidfd in known_pidfds.values():
            with contextlib.suppress(OSError):
                os.close(pidfd)
        known_pidfds.clear()
        if cleanup_errors:
            raise CampaignError(
                "Codex boundary cleanup failed closed: "
                + "; ".join(cleanup_errors)
            )
    complete_gate = load_json(gate_record_path)
    complete_gate.update(
        {
            "boundary_evidence": file_record(
                boundary_evidence / "cleanup.json",
                relative_to=gate_record_path.parent,
            ),
            "broker_cleanup": broker_cleanup,
            "recorded_at": _utc_now(),
        }
    )
    write_json(gate_record_path, complete_gate)
    return {
        "started_at": started,
        "completed_at": _utc_now(),
        "elapsed_seconds": round(time.monotonic() - started_monotonic, 6),
        "returncode": returncode,
        "timed_out": timed_out,
        "fresh_process": True,
        "follow_up_messages": 0,
        "coaching": "none",
        "semantic_prompt_bytes": len(stdin_payload),
        "semantic_prompt_sha256": sha256_bytes(stdin_payload),
        "provider_auth_gate": load_json(gate_record_path),
    }


def _run_model_process(
    argv: list[str],
    *,
    cwd: Path,
    stdout_path: Path,
    stderr_path: Path,
    timeout: int,
    provider: str,
    provider_home: Path,
    copied_auth: list[str],
    credential_values: list[bytes],
    gate_record_path: Path,
    claude_boundary: dict[str, Any] | None = None,
    user_prompt: str | None = None,
    process_env: dict[str, str] | None = None,
    codex_auth_mode: str = "early-scrub",
    stdin_payload: bytes | None = None,
) -> dict[str, Any]:
    """Run one provider process behind its provider-specific auth/tool gate.

    Claude keeps copied auth in a host-only transport home and exposes only its
    fixed MCP boundary. Codex either uses the synthetic early-scrub test gate or
    retains copied auth in a disposable transport home while its task commands
    run under the separately configured Codex sandbox. Both modes destroy the
    copied home and reject credential material in preserved output.
    """

    if provider == "anthropic-sonnet":
        if (
            claude_boundary is None
            or user_prompt is None
            or process_env is None
            or stdin_payload is not None
        ):
            raise CampaignError(
                "Claude process requires MCP boundary, exact prompt, and "
                "private transport environment"
            )
        return _run_claude_mcp_process(
            argv,
            cwd=cwd,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            timeout=timeout,
            provider_home=provider_home,
            copied_auth=copied_auth,
            credential_values=credential_values,
            gate_record_path=gate_record_path,
            boundary=claude_boundary,
            user_prompt=user_prompt,
            process_env=process_env,
        )
    if codex_auth_mode == "retained-private-home":
        if (
            claude_boundary is None
            or user_prompt is None
            or process_env is not None
            or stdin_payload is None
        ):
            raise CampaignError(
                "Codex retained transport requires its strict MCP boundary "
                "and no host environment override"
            )
        return _run_codex_retained_process(
            argv,
            cwd=cwd,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            timeout=timeout,
            provider_home=provider_home,
            copied_auth=copied_auth,
            credential_values=credential_values,
            gate_record_path=gate_record_path,
            boundary=claude_boundary,
            stdin_payload=stdin_payload,
        )
    if (
        claude_boundary is not None
        or user_prompt is not None
        or process_env is not None
        or stdin_payload is not None
    ):
        raise CampaignError(
            "Codex early-scrub gate received retained-boundary inputs"
        )
    if codex_auth_mode != "early-scrub":
        raise CampaignError(f"unknown Codex auth mode: {codex_auth_mode}")

    def identity_event(value: Any) -> bool:
        if not isinstance(value, dict):
            return False
        if provider == "anthropic-sonnet":
            return (
                value.get("type") == "system"
                and value.get("subtype") == "init"
                and isinstance(value.get("session_id"), str)
                and bool(value.get("session_id"))
            )
        return (
            value.get("type") == "thread.started"
            and isinstance(value.get("thread_id"), str)
            and bool(value.get("thread_id"))
        )

    def semantic_event(value: Any) -> bool:
        if not isinstance(value, dict):
            return False
        if identity_event(value):
            return False
        return value.get("type") in {
            "assistant",
            "user",
            "result",
            "item.started",
            "item.completed",
        }

    known_provider_pidfds: dict[int, int] = {}

    def remember_provider_pids(pids: Iterable[int]) -> None:
        for pid in pids:
            if pid in known_provider_pidfds:
                continue
            try:
                known_provider_pidfds[pid] = os.pidfd_open(pid)
            except ProcessLookupError:
                continue
            except (PermissionError, OSError) as exc:
                raise CampaignError(
                    f"cannot retain provider process identity for pid {pid}: {exc}"
                ) from exc

    def live_known_provider_pids() -> list[int]:
        live: list[int] = []
        for pid, pidfd in known_provider_pidfds.items():
            poller = select.poll()
            poller.register(pidfd, select.POLLIN)
            if not poller.poll(0):
                live.append(pid)
        return sorted(live)

    def signal_known_provider_pids(sig: signal.Signals) -> None:
        for pidfd in known_provider_pidfds.values():
            with contextlib.suppress(ProcessLookupError):
                signal.pidfd_send_signal(pidfd, sig)

    def process_relations() -> tuple[dict[int, int], dict[int, int]]:
        parents: dict[int, int] = {}
        groups: dict[int, int] = {}
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            pid = int(entry.name)
            try:
                raw = (entry / "stat").read_text(encoding="utf-8")
                tail = raw[raw.rfind(")") + 2 :].split()
                parents[pid] = int(tail[1])
                groups[pid] = int(tail[2])
            except (FileNotFoundError, PermissionError, OSError, ValueError):
                continue
        return parents, groups

    def descendants(root_pid: int) -> tuple[list[int], dict[int, int]]:
        parents, groups = process_relations()
        selected = {root_pid}
        changed = True
        while changed:
            changed = False
            for pid, parent in parents.items():
                if parent in selected and pid not in selected:
                    selected.add(pid)
                    changed = True
        remember_provider_pids(selected)
        return sorted(selected), groups

    def process_state(pid: int) -> str | None:
        try:
            raw = (Path("/proc") / str(pid) / "stat").read_text(
                encoding="utf-8"
            )
            return raw[raw.rfind(")") + 2 :].split()[0]
        except (FileNotFoundError, PermissionError, OSError, IndexError):
            return None

    def stop_tree(root_pid: int) -> tuple[list[int], dict[int, int]]:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(root_pid, signal.SIGSTOP)
        previous: set[int] = set()
        groups: dict[int, int] = {}
        stable_rounds = 0
        for _ in range(100):
            members, groups = descendants(root_pid)
            current = set(members)
            signal_tree(sorted(current), signal.SIGSTOP)
            states = {pid: process_state(pid) for pid in current}
            all_stopped = all(
                state in {"T", "t"} for state in states.values()
            )
            if current == previous and all_stopped:
                stable_rounds += 1
            else:
                stable_rounds = 0
            if stable_rounds >= 2:
                return sorted(current), groups
            previous = current
            time.sleep(0.01)
        signal_tree(sorted(previous), signal.SIGKILL)
        raise CampaignError(
            "credential gate could not prove a stable stopped provider tree"
        )

    def signal_tree(pids: list[int], sig: signal.Signals) -> None:
        for pid in reversed(pids):
            pidfd = known_provider_pidfds.get(pid)
            if pidfd is not None:
                with contextlib.suppress(ProcessLookupError):
                    signal.pidfd_send_signal(pidfd, sig)
            else:
                with contextlib.suppress(ProcessLookupError):
                    os.kill(pid, sig)

    def provider_tree_members(root_pid: int) -> list[int]:
        members, groups = descendants(root_pid)
        selected = set(members)
        selected.update(
            pid for pid, process_group in groups.items()
            if process_group == root_pid
        )
        remember_provider_pids(selected)
        return sorted(selected)

    def signal_provider_tree(
        process: subprocess.Popen[bytes], sig: signal.Signals
    ) -> list[int]:
        current: list[int] = []
        if process.poll() is None:
            current = provider_tree_members(process.pid)
            signal_tree(current, sig)
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, sig)
        signal_known_provider_pids(sig)
        return sorted(set(current) | set(known_provider_pidfds))

    def prove_provider_tree_dead() -> list[int]:
        remaining: list[int] = []
        for _ in range(100):
            remaining = live_known_provider_pids()
            if not remaining:
                return []
            signal_known_provider_pids(signal.SIGKILL)
            time.sleep(0.01)
        return remaining

    auth_paths = [provider_home / relative for relative in copied_auth]
    auth_inodes: set[tuple[int, int]] = set()
    for path in auth_paths:
        stat_result = path.stat()
        auth_inodes.add((stat_result.st_dev, stat_result.st_ino))

    def retained_auth_fds(pids: list[int]) -> list[dict[str, Any]]:
        retained: list[dict[str, Any]] = []
        for pid in pids:
            fd_root = Path("/proc") / str(pid) / "fd"
            try:
                fds = list(fd_root.iterdir())
            except (FileNotFoundError, PermissionError, OSError) as exc:
                raise CampaignError(
                    f"cannot inspect provider file descriptors for pid {pid}: {exc}"
                ) from exc
            for fd in fds:
                try:
                    stat_result = fd.stat()
                    target = os.readlink(fd)
                except FileNotFoundError:
                    continue
                except (PermissionError, OSError) as exc:
                    raise CampaignError(
                        f"cannot inspect provider fd {fd}: {exc}"
                    ) from exc
                auth_targets = tuple(
                    str(PROVIDER_AUTH_MOUNT / relative)
                    for relative in copied_auth
                )
                if (
                    (stat_result.st_dev, stat_result.st_ino) in auth_inodes
                    or any(value in target for value in auth_targets)
                ):
                    retained.append(
                        {"pid": pid, "fd": fd.name, "target": target}
                    )
        return retained

    def mount_view_proofs(pids: list[int]) -> list[dict[str, Any]]:
        proofs: list[dict[str, Any]] = []
        expected = {
            str(PROVIDER_AUTH_MOUNT): "writable",
            str(OPERATOR_HOME_MOUNT): "writable",
        }
        for pid in pids:
            path = Path("/proc") / str(pid) / "mountinfo"
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except (FileNotFoundError, PermissionError, OSError) as exc:
                raise CampaignError(
                    f"cannot inspect provider mount view for pid {pid}: {exc}"
                ) from exc
            for line in lines:
                before = line.split(" - ", 1)[0].split()
                if len(before) >= 6 and before[4] in expected:
                    options = before[5].split(",")
                    proofs.append(
                        {
                            "pid": pid,
                            "mount_point": before[4],
                            "expected_mode": expected[before[4]],
                            "mount_options": options,
                            "read_only": "ro" in options,
                            "writable": "rw" in options,
                        }
                    )
        return proofs

    def pre_resume_secret_hits() -> list[str]:
        hits: list[str] = []
        values = {value for value in credential_values if len(value) >= 12}
        for path in (stdout_path, stderr_path):
            data = path.read_bytes() if path.is_file() else b""
            if any(value in data for value in values):
                hits.append(f"{path.name}: exact credential value")
            if any(pattern.search(data) for pattern in OBVIOUS_SECRET_PATTERNS):
                hits.append(f"{path.name}: obvious secret pattern")
        return hits

    def provider_state_secret_hits() -> list[dict[str, str]]:
        hits: list[dict[str, str]] = []
        values = {value for value in credential_values if len(value) >= 12}
        allowed_codex_aliases = {
            "apply_patch",
            "applypatch",
            "codex-linux-sandbox",
            "codex-execve-wrapper",
        }
        if not provider_home.exists():
            return hits
        for path in provider_home.rglob("*"):
            relative = str(path.relative_to(provider_home))
            if path.is_symlink():
                target = os.readlink(path)
                if (
                    path.name in allowed_codex_aliases
                    and target.startswith("/opt/node/")
                ):
                    continue
                hits.append(
                    {"path": relative, "kind": "unrecognized symbolic link"}
                )
                continue
            if not path.is_file():
                continue
            data = path.read_bytes()
            if any(value in data for value in values):
                hits.append(
                    {"path": relative, "kind": "exact credential value"}
                )
                continue
            if any(pattern.search(data) for pattern in OBVIOUS_SECRET_PATTERNS):
                hits.append(
                    {"path": relative, "kind": "obvious secret pattern"}
                )
        return hits

    def provider_state_summary() -> dict[str, Any]:
        inventory = inventory_files(provider_home)
        symlinks = [
            {
                "path": str(path.relative_to(provider_home)),
                "target_sha256": sha256_bytes(
                    os.readlink(path).encode("utf-8")
                ),
            }
            for path in sorted(provider_home.rglob("*"))
            if path.is_symlink()
        ]
        return {
            "file_count": len(inventory),
            "total_bytes": sum(int(item["bytes"]) for item in inventory),
            "inventory_sha256": sha256_bytes(
                _canonical_json_bytes(inventory)
            ),
            "symlink_count": len(symlinks),
            "symlink_manifest_sha256": sha256_bytes(
                _canonical_json_bytes(symlinks)
            ),
        }

    def persist_gate(record: dict[str, Any]) -> None:
        write_json(gate_record_path, record)

    def fail_gate(
        process: subprocess.Popen[bytes],
        reason: str,
        *,
        observed_event_number: int,
    ) -> None:
        signal_provider_tree(process, signal.SIGKILL)
        hits = pre_resume_secret_hits()
        if hits:
            quarantine = quarantine_gate_outputs(hits, error=reason)
            raise CampaignError(
                f"{reason}; credential-bearing output quarantined at {quarantine}"
            )
        existing = (
            load_json(gate_record_path)
            if gate_record_path.is_file()
            else {}
        )
        existing.update(
            {
                "schema": "maude.synthetic-operator.provider-auth-gate.v1",
                "provider_config": provider,
                "status": "failed_closed",
                "observed_event_number": observed_event_number,
                "error": reason,
                "resumed_after_proof": bool(
                    existing.get("resumed_after_proof", False)
                ),
                "recorded_at": _utc_now(),
            }
        )
        persist_gate(
            existing
        )
        raise CampaignError(reason)

    def quarantine_gate_outputs(
        hits: list[str],
        *,
        error: str | None = None,
        exception_type: str | None = None,
        provider_tree_remaining: list[int] | None = None,
    ) -> str:
        quarantine = (
            QUARANTINE_ROOT
            / CAMPAIGN_ID
            / "provider-auth-gate"
            / uuid.uuid4().hex
        )
        quarantine.mkdir(parents=True, mode=0o700)
        for path in (stdout_path, stderr_path):
            if path.exists():
                shutil.move(str(path), quarantine / path.name)
        existing = (
            load_json(gate_record_path)
            if gate_record_path.is_file()
            else {}
        )
        existing.update(
            {
                "schema": "maude.synthetic-operator.provider-auth-gate.v1",
                "provider_config": provider,
                "status": "failed_closed_secret_quarantine",
                "pre_resume_secret_scan_hits": hits,
                "quarantine": str(quarantine),
                "raw_output_committable": False,
                "resumed_after_proof": bool(
                    existing.get("resumed_after_proof", False)
                ),
                "recorded_at": _utc_now(),
            }
        )
        if error is not None:
            existing["error"] = error
        if exception_type is not None:
            existing["exception_type"] = exception_type
        if provider_tree_remaining is not None:
            existing["provider_tree_remaining_after_cleanup"] = (
                provider_tree_remaining
            )
        persist_gate(
            existing
        )
        return str(quarantine)

    def scrub(
        process: subprocess.Popen[bytes],
        event_number: int,
        pipe,
        stdout,
        buffered: bytes,
    ) -> tuple[dict[str, Any], bytes]:
        pgid = process.pid
        milestones: list[dict[str, Any]] = []

        def mark(
            name: str, *, persist: bool = True, **details: Any
        ) -> None:
            milestones.append(
                {
                    "ordinal": len(milestones) + 1,
                    "name": name,
                    "at": _utc_now(),
                    **details,
                }
            )
            if persist:
                persist_gate(
                    {
                        "schema": (
                            "maude.synthetic-operator.provider-auth-gate.v1"
                        ),
                        "provider_config": provider,
                        "status": "bootstrap_in_progress",
                        "identity_event_number": event_number,
                        "milestones": milestones,
                        "resumed_after_proof": False,
                    }
                )

        # Nothing may touch the filesystem between parsing the identity event
        # and stopping the complete provider process tree.  These first two
        # milestones remain in memory until stop_tree has proved a stable stop.
        mark(
            "identity_observed",
            persist=False,
            event_number=event_number,
        )
        mark(
            "sigstop_requested",
            persist=False,
            process_group=pgid,
        )
        members, groups = stop_tree(pgid)
        if process.pid not in members:
            signal_tree(members, signal.SIGKILL)
            raise CampaignError("credential gate could not enumerate provider group")
        states = {str(pid): process_state(pid) for pid in members}
        if not all(state in {"T", "t"} for state in states.values()):
            signal_tree(members, signal.SIGKILL)
            raise CampaignError(
                f"provider tree was not stopped: {states!r}"
            )
        mark("provider_tree_stable_and_stopped", pids=members, states=states)
        os.set_blocking(pipe.fileno(), False)
        while True:
            try:
                chunk = os.read(pipe.fileno(), 65536)
            except BlockingIOError:
                break
            if not chunk:
                break
            stdout.write(chunk)
            stdout.flush()
            buffered += chunk
        drained_event_types: list[str] = []
        while b"\n" in buffered:
            line, buffered = buffered.split(b"\n", 1)
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                signal_tree(members, signal.SIGKILL)
                raise CampaignError(
                    "non-JSON provider output was buffered before auth scrub"
                )
            if identity_event(value) or semantic_event(value):
                signal_tree(members, signal.SIGKILL)
                raise CampaignError(
                    "provider emitted repeated identity or assistant/tool content "
                    "before auth scrub"
                )
            event_type = value.get("type")
            if event_type != "turn.started":
                signal_tree(members, signal.SIGKILL)
                raise CampaignError(
                    "unexpected provider event was buffered before auth scrub: "
                    f"{event_type!r}"
                )
            drained_event_types.append(str(event_type))
        if buffered.strip():
            signal_tree(members, signal.SIGKILL)
            raise CampaignError(
                "partial provider event was buffered before auth scrub"
            )
        mark(
            "provider_stdout_drained",
            buffered_event_types=drained_event_types,
            partial_buffer=False,
        )
        refreshed_value_count = 0
        for path in auth_paths:
            if not path.is_file():
                continue
            for value in _credential_values(path.read_bytes()):
                if value not in credential_values:
                    credential_values.append(value)
                    refreshed_value_count += 1
        mark(
            "current_auth_values_loaded_for_redaction",
            newly_observed_value_count=refreshed_value_count,
        )
        stderr.flush()
        stdout.flush()
        secret_hits = pre_resume_secret_hits()
        if secret_hits:
            signal_tree(members, signal.SIGKILL)
            quarantine = quarantine_gate_outputs(
                secret_hits,
                error=(
                    "credential material appeared before resume during "
                    "bootstrap scrub"
                ),
            )
            raise CampaignError(
                "credential material appeared before resume and was quarantined "
                f"at {quarantine}: {secret_hits!r}"
            )
        mark("pre_resume_secret_scan_passed", hits=[])
        mount_proofs = mount_view_proofs(members)
        proved_by_pid: dict[int, dict[str, dict[str, Any]]] = {}
        for proof in mount_proofs:
            proved_by_pid.setdefault(int(proof["pid"]), {})[
                str(proof["mount_point"])
            ] = proof
        # The outer bubblewrap monitor remains in the host mount namespace;
        # every child that can execute provider/model code must be in the
        # isolated namespace and carry both declared mounts.
        isolated_members = [pid for pid in members if pid != process.pid]
        mount_modes_valid = all(
            str(PROVIDER_AUTH_MOUNT) in proved_by_pid.get(pid, {})
            and proved_by_pid[pid][str(PROVIDER_AUTH_MOUNT)]["writable"]
            and str(OPERATOR_HOME_MOUNT) in proved_by_pid.get(pid, {})
            and proved_by_pid[pid][str(OPERATOR_HOME_MOUNT)]["writable"]
            for pid in isolated_members
        )
        if not isolated_members or not mount_proofs or not mount_modes_valid:
            signal_tree(members, signal.SIGKILL)
            raise CampaignError(
                "provider auth/config and clean HOME mount proof failed: "
                f"{mount_proofs!r}"
            )
        mark(
            "provider_auth_and_operator_home_writable_mounts_proved",
            proofs=mount_proofs,
            isolated_provider_pids=isolated_members,
            outer_bubblewrap_monitor_pid=process.pid,
        )
        for path in auth_paths:
            try:
                path.unlink()
            except FileNotFoundError as exc:
                signal_tree(members, signal.SIGKILL)
                raise CampaignError(
                    f"credential bootstrap path vanished before scrub: {path}"
                ) from exc
        mark("bootstrap_files_unlinked", paths=copied_auth)
        for directory in sorted(
            (path for path in provider_home.rglob("*") if path.is_dir()),
            key=lambda path: len(path.parts),
            reverse=True,
        ):
            with contextlib.suppress(OSError):
                directory.rmdir()
        retained = retained_auth_fds(members)
        mark("auth_file_descriptor_scan_completed", retained=retained)
        visible_paths: list[str] = []
        for pid in members:
            for relative in copied_auth:
                candidate = (
                    Path("/proc")
                    / str(pid)
                    / "root"
                    / str(PROVIDER_AUTH_MOUNT).lstrip("/")
                    / relative
                )
                try:
                    os.lstat(candidate)
                except FileNotFoundError:
                    continue
                except (PermissionError, OSError) as exc:
                    signal_tree(members, signal.SIGKILL)
                    raise CampaignError(
                        f"cannot prove provider auth path absence at {candidate}: "
                        f"{exc}"
                    ) from exc
                else:
                    visible_paths.append(str(candidate))
        state_secret_hits = provider_state_secret_hits()
        if retained or visible_paths or state_secret_hits:
            signal_tree(members, signal.SIGKILL)
            raise CampaignError(
                "credential gate could not prove credential-free provider "
                "state: "
                f"retained_fds={retained!r} visible_paths={visible_paths!r} "
                f"state_secret_hits={state_secret_hits!r}"
            )
        state_after_scrub = provider_state_summary()
        mark("auth_file_descriptor_scan_passed", retained=[])
        mark(
            "auth_path_absence_and_state_redaction_proved",
            visible_paths=visible_paths,
            state_secret_hits=[],
            noncredential_state=state_after_scrub,
        )
        record = {
            "schema": "maude.synthetic-operator.provider-auth-gate.v1",
            "provider_config": provider,
            "identity_event_number": event_number,
            "process_group": pgid,
            "processes_stopped": members,
            "observed_process_groups": {
                str(pid): groups.get(pid) for pid in members
            },
            "stopped_process_states": states,
            "stable_stopped_tree_proved": True,
            "buffered_pre_scrub_event_types": drained_event_types,
            "partial_event_buffer_before_scrub": False,
            "pre_resume_secret_scan_hits": [],
            "provider_auth_and_operator_home_mount_proofs": mount_proofs,
            "copied_bootstrap_files": copied_auth,
            "bootstrap_files_removed": True,
            "retained_auth_file_descriptors": [],
            "auth_paths_visible_after_scrub": [],
            "provider_auth_files_after_scrub": [],
            "provider_noncredential_state_after_scrub": state_after_scrub,
            "provider_state_secret_hits_after_scrub": [],
            "assistant_or_tool_event_before_scrub": False,
            "resumed_after_proof": False,
            "scrubbed_at": _utc_now(),
            "milestones": milestones,
        }
        persist_gate(record)
        signal_tree(members, signal.SIGCONT)
        milestones.append(
            {
                "ordinal": len(milestones) + 1,
                "name": "sigcont_sent",
                "at": _utc_now(),
                "pids": members,
            }
        )
        record["resumed_after_proof"] = True
        record["resumed_at"] = _utc_now()
        record["milestones"] = milestones
        persist_gate(record)
        return record, buffered

    @contextlib.contextmanager
    def guarded_output_files():
        """Own cleanup for every exit after provider credentials are copied."""

        lifecycle: dict[str, Any] = {
            "process": None,
            "selector": None,
            "completed": False,
        }
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            try:
                yield stdout, stderr, lifecycle
            except BaseException as exc:
                selector = lifecycle.get("selector")
                if selector is not None:
                    with contextlib.suppress(Exception):
                        selector.close()
                process = lifecycle.get("process")
                remaining: list[int] = []
                if isinstance(process, subprocess.Popen):
                    signal_provider_tree(process, signal.SIGKILL)
                    with contextlib.suppress(
                        subprocess.TimeoutExpired, ProcessLookupError, OSError
                    ):
                        process.wait(timeout=10)
                    remaining = prove_provider_tree_dead()
                for path in auth_paths:
                    with contextlib.suppress(FileNotFoundError):
                        path.unlink()
                with contextlib.suppress(OSError):
                    stdout.flush()
                with contextlib.suppress(OSError):
                    stderr.flush()
                secret_hits = pre_resume_secret_hits()
                existing = (
                    load_json(gate_record_path)
                    if gate_record_path.is_file()
                    else {}
                )
                if secret_hits:
                    if existing.get("status") != (
                        "failed_closed_secret_quarantine"
                    ):
                        quarantine_gate_outputs(
                            secret_hits,
                            error=str(exc),
                            exception_type=type(exc).__name__,
                            provider_tree_remaining=remaining,
                        )
                elif existing.get("status") != (
                    "failed_closed_secret_quarantine"
                ):
                    existing.update(
                        {
                            "schema": (
                                "maude.synthetic-operator."
                                "provider-auth-gate.v1"
                            ),
                            "provider_config": provider,
                            "status": "failed_closed",
                            "error": str(exc),
                            "exception_type": type(exc).__name__,
                            "provider_tree_remaining_after_cleanup": remaining,
                            "resumed_after_proof": bool(
                                existing.get("resumed_after_proof", False)
                            ),
                            "recorded_at": _utc_now(),
                        }
                    )
                    persist_gate(existing)
                if remaining:
                    raise CampaignError(
                        "provider lifecycle cleanup could not prove the process "
                        f"tree dead: {remaining!r}"
                    ) from exc
                raise
            finally:
                selector = lifecycle.get("selector")
                if selector is not None:
                    with contextlib.suppress(Exception):
                        selector.close()
                if not lifecycle["completed"]:
                    for path in auth_paths:
                        with contextlib.suppress(FileNotFoundError):
                            path.unlink()
                for pidfd in known_provider_pidfds.values():
                    with contextlib.suppress(OSError):
                        os.close(pidfd)
                known_provider_pidfds.clear()

    started = _utc_now()
    started_monotonic = time.monotonic()
    gate: dict[str, Any] | None = None
    event_number = 0
    pending = b""
    with guarded_output_files() as (stdout, stderr, lifecycle):
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=stderr,
            start_new_session=True,
        )
        lifecycle["process"] = process
        if process.stdout is None:
            raise CampaignError("provider stdout pipe was not created")
        selector = selectors.DefaultSelector()
        lifecycle["selector"] = selector
        selector.register(process.stdout, selectors.EVENT_READ)
        timed_out = False
        deadline = started_monotonic + timeout
        while True:
            if process.poll() is None:
                provider_tree_members(process.pid)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break
            ready = selector.select(timeout=min(1.0, remaining))
            if not ready:
                if process.poll() is not None:
                    chunk = process.stdout.read()
                    if chunk:
                        stdout.write(chunk)
                        pending += chunk
                    break
                continue
            chunk = os.read(process.stdout.fileno(), 65536)
            if not chunk:
                break
            if process.poll() is None:
                provider_tree_members(process.pid)
            stdout.write(chunk)
            stdout.flush()
            pending += chunk
            while b"\n" in pending:
                line, pending = pending.split(b"\n", 1)
                if not line.strip():
                    continue
                event_number += 1
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as exc:
                    reason = (
                        "provider emitted non-JSON output before completing a "
                        "structured session"
                    )
                    try:
                        fail_gate(
                            process,
                            reason,
                            observed_event_number=event_number,
                        )
                    except CampaignError as gate_exc:
                        raise gate_exc from exc
                if gate is None and not identity_event(event):
                    fail_gate(
                        process,
                        "provider emitted content before its identity event",
                        observed_event_number=event_number,
                    )
                if gate is None and identity_event(event):
                    try:
                        gate, pending = scrub(
                            process,
                            event_number,
                            process.stdout,
                            stdout,
                            pending,
                        )
                        event_number += len(
                            gate.get("buffered_pre_scrub_event_types", [])
                        )
                    except (CampaignError, OSError) as exc:
                        signal_provider_tree(process, signal.SIGKILL)
                        secret_hits = pre_resume_secret_hits()
                        if secret_hits:
                            quarantine_gate_outputs(
                                secret_hits,
                                error=str(exc),
                                exception_type=type(exc).__name__,
                            )
                        existing = (
                            load_json(gate_record_path)
                            if gate_record_path.is_file()
                            else {}
                        )
                        if existing.get("status") != (
                            "failed_closed_secret_quarantine"
                        ):
                            existing.update(
                                {
                                    "schema": (
                                        "maude.synthetic-operator."
                                        "provider-auth-gate.v1"
                                    ),
                                    "provider_config": provider,
                                    "identity_event_number": event_number,
                                    "status": "failed_closed",
                                    "error": str(exc),
                                    "resumed_after_proof": False,
                                    "recorded_at": _utc_now(),
                                }
                            )
                            persist_gate(existing)
                        raise CampaignError(str(exc)) from exc
                elif gate is not None and identity_event(event):
                    fail_gate(
                        process,
                        "provider emitted a repeated identity event",
                        observed_event_number=event_number,
                    )
                elif (
                    gate is not None
                    and semantic_event(event)
                    and "first_post_scrub_semantic_event_number" not in gate
                ):
                    gate["first_post_scrub_semantic_event_number"] = event_number
                    gate["first_post_scrub_semantic_event_type"] = event.get(
                        "type"
                    )
                    gate["milestones"].append(
                        {
                            "ordinal": len(gate["milestones"]) + 1,
                            "name": "first_post_scrub_semantic_event",
                            "at": _utc_now(),
                            "event_number": event_number,
                            "event_type": event.get("type"),
                        }
                    )
                    persist_gate(gate)
        selector.close()
        lifecycle["selector"] = None
        if pending.strip():
            fail_gate(
                process,
                "provider stream ended with a partial JSON event",
                observed_event_number=event_number,
            )
        if timed_out:
            signal_provider_tree(process, signal.SIGTERM)
            try:
                returncode = process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                signal_provider_tree(process, signal.SIGKILL)
                returncode = process.wait(timeout=10)
        else:
            try:
                returncode = process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                signal_provider_tree(process, signal.SIGTERM)
                try:
                    returncode = process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    signal_provider_tree(process, signal.SIGKILL)
                    returncode = process.wait(timeout=10)
        if gate is None:
            fail_gate(
                process,
                "provider stream ended before the credential bootstrap gate",
                observed_event_number=event_number,
            )
        live_group_members = live_known_provider_pids()
        if live_group_members:
            signal_provider_tree(process, signal.SIGKILL)
            remaining = prove_provider_tree_dead()
            raise CampaignError(
                "provider left live process-group members after exit: "
                f"observed={live_group_members!r} remaining={remaining!r}"
            )
        repopulated_auth_paths = [
            str(relative)
            for relative in copied_auth
            if (provider_home / relative).exists()
        ]
        state_secret_hits = provider_state_secret_hits()
        if repopulated_auth_paths or state_secret_hits:
            signal_provider_tree(process, signal.SIGKILL)
            raise CampaignError(
                "provider state regained auth material after credential "
                f"scrub: auth_paths={repopulated_auth_paths!r} "
                f"state_secret_hits={state_secret_hits!r}"
            )
        gate["provider_auth_tree_remained_credential_free_through_exit"] = True
        gate["provider_noncredential_state_at_exit"] = (
            provider_state_summary()
        )
        gate["provider_state_secret_hits_at_exit"] = []
        gate["provider_exited_at"] = _utc_now()
        persist_gate(gate)
        lifecycle["completed"] = True
    return {
        "started_at": started,
        "completed_at": _utc_now(),
        "elapsed_seconds": round(time.monotonic() - started_monotonic, 6),
        "returncode": returncode,
        "timed_out": timed_out,
        "fresh_process": True,
        "follow_up_messages": 0,
        "coaching": "none",
        "provider_auth_gate": gate,
    }


def _probe_provider_scope(
    providers: Iterable[str] | None,
) -> tuple[str, ...]:
    available = _configured_campaign_providers()
    selected = tuple(providers or available)
    if (
        not selected
        or len(set(selected)) != len(selected)
        or any(value not in available for value in selected)
    ):
        raise CampaignError(
            "probe providers must be a nonempty unique subset of "
            f"{available!r}"
        )
    return selected


def _frozen_model_family_policy() -> dict[str, Any]:
    matrix = load_json(PACKET_DIR / "run-matrix.json")
    policy = matrix.get("model_family_policy")
    configs = matrix.get("operator_model_configs")
    if not isinstance(policy, dict) or not isinstance(configs, dict):
        raise CampaignError("frozen matrix model-family policy is malformed")
    providers = policy.get("campaign_provider_configs")
    if (
        not isinstance(providers, list)
        or not providers
        or len(set(providers)) != len(providers)
        or not all(
            isinstance(value, str) and value in configs
            for value in providers
        )
        or policy.get("separate_fresh_sessions_required") is not True
        or type(policy.get("same_family_grading")) is not bool
        or type(policy.get("same_model_configuration_grading")) is not bool
        or type(policy.get("cross_family_grading_supported")) is not bool
        or not isinstance(policy.get("operator_model_config"), str)
        or policy["operator_model_config"] not in configs
        or not isinstance(policy.get("grader_model_config"), str)
        or policy["grader_model_config"] not in configs
        or not isinstance(policy.get("limitation"), str)
        or not policy["limitation"]
    ):
        raise CampaignError("frozen matrix model-family policy differs")
    return policy


def _configured_campaign_providers() -> tuple[str, ...]:
    return tuple(
        _frozen_model_family_policy()["campaign_provider_configs"]
    )


def _grading_model_family_metadata(
    run: dict[str, Any],
) -> dict[str, Any]:
    policy = _frozen_model_family_policy()
    if (
        run.get("operator_model_config")
        != policy["operator_model_config"]
        or run.get("grader_model_config")
        != policy["grader_model_config"]
        or (
            run.get("operator_model_config")
            == run.get("grader_model_config")
        )
        is not policy["same_model_configuration_grading"]
    ):
        raise CampaignError(
            f"{run.get('run_id')}: run/model-family policy differs"
        )
    return {
        "separate_fresh_session_required": (
            policy["separate_fresh_sessions_required"]
        ),
        "same_family_grading": policy["same_family_grading"],
        "same_model_configuration_grading": (
            policy["same_model_configuration_grading"]
        ),
        "cross_family_grading_supported": (
            policy["cross_family_grading_supported"]
        ),
        "same_family_limitation": policy["limitation"],
    }


def _probe_terminal_arguments_are_exact(
    arguments: Any,
    *,
    expected_command: str,
) -> bool:
    """Accept only the two schema-valid argument shapes used by probes."""

    if (
        not isinstance(arguments, dict)
        or set(arguments)
        not in ({"command"}, {"command", "timeout_seconds"})
        or arguments.get("command") != expected_command
    ):
        return False
    return (
        "timeout_seconds" not in arguments
        or (
            type(arguments["timeout_seconds"]) is int
            and arguments["timeout_seconds"]
            == PROVIDER_PROBE_TERMINAL_TIMEOUT_SECONDS
        )
    )


def _is_exact_codex_auth_absence_action(
    serialized_action: str,
) -> bool:
    """Recognize only the frozen Codex MCP absence-check observations."""

    try:
        value = json.loads(serialized_action)
    except (json.JSONDecodeError, TypeError):
        return False
    if not isinstance(value, dict) or set(value) != {"observations"}:
        return False
    observations = value["observations"]
    if (
        not isinstance(observations, list)
        or len(observations) != 2
        or [
            observation.get("event_type")
            if isinstance(observation, dict)
            else None
            for observation in observations
        ]
        != ["item.started", "item.completed"]
    ):
        return False
    action_id: str | None = None
    paired_arguments: dict[str, Any] | None = None
    for observation in observations:
        if (
            not isinstance(observation, dict)
            or set(observation)
            != {"event_number", "event_type", "item", "item_sha256"}
            or type(observation.get("event_number")) is not int
            or observation["event_number"] <= 0
            or not isinstance(observation.get("item_sha256"), str)
            or not re.fullmatch(
                r"[0-9a-f]{64}",
                observation["item_sha256"],
            )
        ):
            return False
        item = observation.get("item")
        if not isinstance(item, dict):
            return False
        item_id = item.get("id")
        if (
            not isinstance(item_id, str)
            or not item_id
            or (action_id is not None and item_id != action_id)
        ):
            return False
        action_id = item_id
        arguments = item.get("arguments")
        if (
            item.get("type") != "mcp_tool_call"
            or item.get("server") != CLAUDE_OPERATOR_SERVER
            or item.get("tool") != "terminal"
            or not _probe_terminal_arguments_are_exact(
                arguments,
                expected_command=CODEX_AUTH_GATE_ABSENCE_CHECK_COMMAND,
            )
            or sha256_bytes(arguments["command"].encode("utf-8"))
            != CODEX_AUTH_GATE_ABSENCE_CHECK_SHA256
        ):
            return False
        if paired_arguments is not None and arguments != paired_arguments:
            return False
        paired_arguments = arguments
    if observations[0]["event_number"] >= observations[1]["event_number"]:
        return False
    return True


def run_auth_gate_probes(
    providers: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Prove the credential gate with fresh non-campaign provider sessions."""

    selected_providers = _probe_provider_scope(providers)
    if MANIFEST_PATH.exists():
        raise CampaignError(
            "provider auth-gate probes are pre-freeze only; campaign manifest exists"
        )
    probe_root = AUTH_GATE_PROBE_PATH.parent
    if AUTH_GATE_PROBE_PATH.exists():
        raise CampaignError(
            "provider auth-gate probe index already exists; refusing to overwrite"
        )
    attempt_id = (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + uuid.uuid4().hex[:12]
    )
    attempt_root = probe_root / "attempts" / attempt_id
    attempt_root.mkdir(parents=True)
    results: list[dict[str, Any]] = []
    system_prompt = (
        "This is a non-campaign capability probe for session and filesystem "
        "isolation. Perform only the exact harmless local reads, filtered "
        "environment checks, and clean-HOME sentinel operation requested. "
        "Do not inspect credential contents, repository source, unrelated "
        "environment variables, or the network. Finish with "
        "AUTH_GATE_PROBE_OK."
    )
    prompts = {
        "anthropic-sonnet": (
            "First use the terminal tool to execute exactly "
            "`/usr/bin/cat /etc/hosts`. Wait for that result. Then use the "
            "terminal tool in a separate call to execute exactly: "
            "`/usr/bin/test \"$HOME\" = /home/operator && "
            "/usr/bin/test \"$XDG_CONFIG_HOME\" = /home/operator/.config && "
            "/usr/bin/test ! -e "
            "/run/provider-auth/.claude/.credentials.json && "
            "/usr/bin/test ! -e /run/provider-auth/.claude.json && "
            "/usr/bin/printf 'clean-home-sentinel\\n' > "
            "\"$HOME/probe-sentinel\" && "
            "/usr/bin/test \"$(/usr/bin/cat \"$HOME/probe-sentinel\")\" = "
            "clean-home-sentinel && "
            "/usr/bin/printf 'HOME=/home/operator\\nCLEAN_HOME_WRITE_OK\\n"
            "PROVIDER_AUTH_ABSENT_OK\\n'`. Report the two harmless results "
            "and the exact marker AUTH_GATE_PROBE_OK."
        ),
        "openai-sol": (
            "First execute `/usr/bin/test \"$HOME\" = /home/operator && "
            "/usr/bin/test \"$XDG_CONFIG_HOME\" = /home/operator/.config && "
            "/usr/bin/printf 'clean-home-sentinel\\n' > "
            "\"$HOME/probe-sentinel\" && "
            "/usr/bin/printf 'HOME=/home/operator\\nCLEAN_HOME_WRITE_OK\\n'` "
            "as one shell command. Wait for that result. Then execute `"
            + CODEX_AUTH_GATE_ABSENCE_CHECK_COMMAND
            + "` as a second, "
            "separate shell command. Report the harmless results and the exact "
            "marker AUTH_GATE_PROBE_OK."
        ),
    }
    for provider in selected_providers:
        provider_evidence = attempt_root / provider
        provider_evidence.mkdir()
        lab = LAB_ROOT / f"_auth-gate-{provider}-{uuid.uuid4().hex[:12]}"
        ensure_safe_lab_path(lab)
        operator = lab / "operator"
        provider_home = lab / "private-provider-home"
        boundary: dict[str, Any] | None = None
        try:
            operator.mkdir(parents=True)
            write_text(
                operator / "README.md",
                "Non-campaign auth-gate capability probe. No task state.\n",
            )
            copied_auth, credential_values = _copy_provider_home(
                provider, provider_home
            )
            operator_home = lab / "private-operator-home"
            if provider == "anthropic-sonnet":
                _prepare_clean_operator_home(operator_home)
                environment = _claude_clean_environment(operator_home)
                boundary = _build_claude_boundary(
                    label=f"auth-probe-{uuid.uuid4().hex[:10]}",
                    lab=lab,
                    mode="operator",
                    provider_home=provider_home,
                    cwd=operator,
                    operator_home=operator_home,
                    mounts=[
                        {
                            "source": str(operator),
                            "target": str(operator),
                            "mode": "ro",
                        },
                        {
                            "source": str(operator_home),
                            "target": str(OPERATOR_HOME_MOUNT),
                            "mode": "rw",
                        },
                    ],
                    sockets=[],
                    environment=environment,
                )
                isolation = _claude_mcp_isolation_preflight(boundary)
                bwrap_prefix: list[str] = []
                provider_cwd = boundary["transport_cwd"]
            else:
                _prepare_clean_operator_home(operator_home)
                boundary = _adapt_boundary_for_codex(
                    _build_claude_boundary(
                        label=f"auth-probe-{uuid.uuid4().hex[:10]}",
                        lab=lab,
                        mode="operator",
                        provider_home=provider_home,
                        cwd=operator,
                        operator_home=operator_home,
                        mounts=[
                            {
                                "source": str(operator),
                                "target": str(operator),
                                "mode": "ro",
                            },
                            {
                                "source": str(operator_home),
                                "target": str(OPERATOR_HOME_MOUNT),
                                "mode": "rw",
                            },
                        ],
                        sockets=[],
                        environment=_claude_clean_environment(operator_home),
                    )
                )
                bwrap_prefix = _codex_mcp_transport_bwrap(
                    boundary, provider_home, operator_home
                )
                isolation = _codex_mcp_isolation_preflight(
                    boundary, bwrap_prefix
                )
                provider_cwd = boundary["transport_cwd"]
            write_json(provider_evidence / "isolation.json", isolation)
            user_prompt = prompts[provider]
            write_text(provider_evidence / "system-prompt.md", system_prompt)
            write_text(provider_evidence / "user-prompt.md", user_prompt)
            provider_argv, delivery, stdin_payload = _provider_argv(
                provider,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                cwd=operator,
                additional_dirs=(
                    [] if boundary is not None else [operator_home]
                ),
                claude_boundary=boundary,
            )
            stdout_path = provider_evidence / "transcript.jsonl"
            stderr_path = provider_evidence / "provider.stderr"
            process_result = _run_model_process(
                (
                    provider_argv
                    if provider == "anthropic-sonnet"
                    else [*bwrap_prefix, *provider_argv]
                ),
                cwd=provider_cwd,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                timeout=AUTH_GATE_PROBE_TIMEOUT,
                provider=provider,
                provider_home=provider_home,
                copied_auth=copied_auth,
                credential_values=credential_values,
                gate_record_path=provider_evidence / "auth-gate.json",
                claude_boundary=boundary,
                user_prompt=user_prompt if boundary is not None else None,
                process_env=(
                    boundary["provider_environment"]
                    if provider == "anthropic-sonnet"
                    else None
                ),
                codex_auth_mode="retained-private-home",
                stdin_payload=stdin_payload,
            )
            _quarantine_if_secret(
                [stdout_path, stderr_path],
                credential_values,
                run_id=f"auth-gate-{provider}",
                evidence_dir=provider_evidence,
            )
            events = _provider_events(stdout_path)
            actions = _event_actions(events)
            action_events = _completed_action_event_records(events)
            successful_action_events = [
                record
                for record in action_events
                if record["succeeded"]
            ]
            successful_action_outputs = _successful_action_outputs(events)
            combined_action_output = "\n".join(
                record["output"] for record in successful_action_outputs
            )
            clean_home_markers = {
                "HOME=/home/operator",
                "CLEAN_HOME_WRITE_OK",
                "PROVIDER_AUTH_ABSENT_OK",
            }
            missing_clean_home_markers = sorted(
                marker
                for marker in clean_home_markers
                if marker not in combined_action_output
            )
            final_answers = _final_answer_records(events)
            identity = _session_identity(events, provider)
            identity_value = identity.get(
                "provider_session_id"
            ) or identity.get("provider_thread_id")
            marker_answers = [
                record
                for record in final_answers
                if "AUTH_GATE_PROBE_OK" in record["text"]
            ]
            marker_present = bool(marker_answers)
            safety = _audit_actions(actions)
            unauthorized_auth_probe_reads: list[str] = []
            for serialized_action in safety["auth_read_attempts"]:
                if provider == "openai-sol":
                    if not _is_exact_codex_auth_absence_action(
                        serialized_action
                    ):
                        unauthorized_auth_probe_reads.append(
                            serialized_action
                        )
                    continue
                matches = list(
                    re.finditer(
                        r"/run/provider-auth/[A-Za-z0-9_./-]+",
                        serialized_action,
                    )
                )
                if not matches or any(
                    not re.search(
                        r"/usr/bin/test\s+!\s+-e\s*$",
                        serialized_action[max(0, match.start() - 80) : match.start()],
                    )
                    for match in matches
                ):
                    unauthorized_auth_probe_reads.append(serialized_action)
            distinct_action_event_numbers = {
                record["event_number"]
                for record in successful_action_events
            }
            final_after_actions = bool(
                marker_answers
                and successful_action_events
                and min(
                    record["event_number"] for record in marker_answers
                )
                > max(
                    record["event_number"]
                    for record in successful_action_events
                )
            )
            if (
                process_result["returncode"] != 0
                or process_result["timed_out"]
                or not identity_value
                or len(actions) < 2
                or len(successful_action_events) < 2
                or len(distinct_action_event_numbers) < 2
                or not marker_present
                or not _has_final_answer(events)
                or not final_after_actions
                or missing_clean_home_markers
                or unauthorized_auth_probe_reads
                or safety["environment_read_attempts"]
                or safety["network_command_attempts"]
                or safety["host_source_read_attempts"]
            ):
                raise CampaignError(
                    f"{provider} auth-gate capability probe failed: "
                    f"returncode={process_result['returncode']} "
                    f"timed_out={process_result['timed_out']} "
                    f"identity={identity_value!r} actions={len(actions)} "
                    f"action_events={action_events!r} "
                    f"successful_action_events={successful_action_events!r} "
                    f"marker={marker_present} final_after_actions="
                    f"{final_after_actions} missing_clean_home_markers="
                    f"{missing_clean_home_markers!r} "
                    f"unauthorized_auth_probe_reads="
                    f"{unauthorized_auth_probe_reads!r} safety={safety!r}"
                )
            result = {
                "provider_config": provider,
                "campaign_run": False,
                "fresh_process": True,
                "session_identity": identity,
                "delivery": delivery,
                "process": process_result,
                "tool_actions_after_gate": len(actions),
                "completed_action_events": action_events,
                "successful_completed_action_events": (
                    successful_action_events
                ),
                "successful_action_output_records": successful_action_outputs,
                "required_clean_home_markers": sorted(clean_home_markers),
                "missing_clean_home_markers": [],
                "distinct_completed_action_event_numbers": sorted(
                    distinct_action_event_numbers
                ),
                "final_answer_events": [
                    {
                        "event_number": record["event_number"],
                        "sha256": sha256_bytes(
                            record["text"].encode("utf-8")
                        ),
                    }
                    for record in final_answers
                ],
                "final_marker_present": marker_present,
                "final_marker_after_second_tool_result": final_after_actions,
                "safety_audit": safety,
                "authorized_auth_path_absence_checks_only": True,
                "authorized_codex_auth_absence_check": (
                    {
                        "command_sha256": (
                            CODEX_AUTH_GATE_ABSENCE_CHECK_SHA256
                        ),
                        "accepted_argument_key_sets": [
                            ["command"],
                            ["command", "timeout_seconds"],
                        ],
                        "optional_explicit_timeout_seconds": (
                            PROVIDER_PROBE_TERMINAL_TIMEOUT_SECONDS
                        ),
                    }
                    if provider == "openai-sol"
                    else None
                ),
                "unauthorized_auth_probe_reads": [],
                "raw_transcript": file_record(
                    stdout_path, relative_to=probe_root
                ),
                "raw_stderr": file_record(
                    stderr_path, relative_to=probe_root
                ),
                "gate_record": file_record(
                    provider_evidence / "auth-gate.json",
                    relative_to=probe_root,
                ),
                "authority_effect": "none",
            }
            write_json(provider_evidence / "result.json", result)
            results.append(result)
        finally:
            boundary_cleanup = _release_private_socket_directories(boundary)
            if not boundary_cleanup["all_removed"]:
                raise CampaignError(
                    "auth-gate probe left a private Claude socket arena"
                )
            if lab.exists():
                shutil.rmtree(lab)
    index = {
        "schema": "maude.synthetic-operator.provider-auth-gate-probes.v1",
        "campaign_id": CAMPAIGN_ID,
        "campaign_run": False,
        "attempt_id": attempt_id,
        "completed_at": _utc_now(),
        "campaign_runner": file_record(
            Path(__file__).resolve(), relative_to=REPO_ROOT
        ),
        "requested_provider_configs": list(selected_providers),
        "not_requested_provider_configs": sorted(
            set(_configured_campaign_providers())
            - set(selected_providers)
        ),
        "providers": results,
        "all_passed": len(results) == len(selected_providers),
        "raw_evidence_location": str(attempt_root),
        "raw_evidence_committed": False,
        "authority_effect": "none",
    }
    write_json(AUTH_GATE_PROBE_PATH, index)
    return index


def _installation_trace_pairs(path: Path) -> list[dict[str, Any]]:
    requests: dict[Any, dict[str, Any]] = {}
    pairs: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = json.loads(line)
        frame = value.get("frame")
        if not isinstance(frame, dict):
            continue
        if value.get("direction") == "request":
            requests[frame.get("id")] = value
        elif value.get("direction") == "response":
            request = requests.get(frame.get("id"))
            if request is None:
                continue
            result = frame.get("result")
            error = frame.get("error")
            pairs.append(
                {
                    "request_id": frame.get("id"),
                    "method": request["frame"].get("method"),
                    "request_body_sha256": request.get("body_sha256"),
                    "response_body_sha256": value.get("body_sha256"),
                    "response_kind": (
                        "error" if error is not None else "result"
                    ),
                    "result_or_error_sha256": sha256_bytes(
                        json.dumps(
                            error if error is not None else result,
                            ensure_ascii=False,
                            separators=(",", ":"),
                            sort_keys=True,
                        ).encode("utf-8")
                    ),
                }
            )
    return pairs


def _installation_rpc_contract_predicates(
    trace_pairs: list[dict[str, Any]],
) -> dict[str, bool]:
    """Check frozen startup, poll, and literal ``status`` RPC contracts."""

    successful_methods = [
        pair.get("method")
        for pair in trace_pairs
        if pair.get("response_kind") == "result"
    ]
    startup_sequence = [
        "governor.hello",
        "sessions.list",
        "sessions.create",
    ]
    status_index = next(
        (
            index
            for index, method in enumerate(successful_methods)
            if method == "governor.status"
        ),
        -1,
    )
    runtime_list_index = next(
        (
            index
            for index, method in enumerate(successful_methods)
            if index > status_index and method == "runtime.session.list"
        ),
        -1,
    )
    return {
        "runtime_trace_nonempty": bool(trace_pairs),
        "all_runtime_trace_responses_are_results": bool(trace_pairs)
        and all(pair.get("response_kind") == "result" for pair in trace_pairs),
        "startup_rpc_sequence_exact_prefix": (
            successful_methods[: len(startup_sequence)] == startup_sequence
        ),
        "startup_governor_hello_observed": (
            "governor.hello" in successful_methods
        ),
        "startup_chat_sessions_list_observed": (
            "sessions.list" in successful_methods
        ),
        "empty_startup_chat_session_create_observed": (
            "sessions.create" in successful_methods
        ),
        "scheduled_governor_now_poll_observed": (
            "governor.now" in successful_methods[len(startup_sequence) :]
        ),
        "typed_status_governor_status_observed": status_index >= 0,
        "typed_status_runtime_session_list_observed": (
            status_index >= 0 and runtime_list_index >= 0
        ),
        "typed_status_rpc_sequence_in_order": (
            status_index >= 0 and runtime_list_index > status_index
        ),
    }


def _installation_pty_commands(
    *,
    adapter: Path,
    pty_state: Path,
    typescript: Path,
    maude: Path,
) -> list[str]:
    """Return the exact focus-aware eight-action installation probe."""

    return [
        (
            f"'{adapter}' start --state '{pty_state}' "
            f"--output '{typescript}' -- '{maude}'"
        ),
        f"'{adapter}' read --state '{pty_state}' --wait 5",
        f"'{adapter}' send --state '{pty_state}' --input hex:09",
        (
            f"'{adapter}' send --state '{pty_state}' "
            "--input hex:7374617475730d"
        ),
        f"'{adapter}' read --state '{pty_state}' --wait 5",
        (
            f"'{adapter}' stop --state '{pty_state}' "
            "--input hex:11 --wait 5"
        ),
        f"'{adapter}' read --state '{pty_state}' --wait 5",
        f"'{adapter}' status --state '{pty_state}'",
    ]


def _installation_terminal_action_commands(
    actions: list[dict[str, Any]],
    *,
    provider: str,
    expected_commands: list[str],
) -> list[dict[str, Any]]:
    """Parse exact terminal commands from provider actions in action order."""

    if len(actions) != len(expected_commands):
        raise CampaignError(
            f"{provider} installation action count differs from command sequence"
        )
    records: list[dict[str, Any]] = []
    for position, action in enumerate(actions, 1):
        label = f"{provider} installation action {position}"
        expected_command = expected_commands[position - 1]
        if provider == "openai-sol":
            expected_action_keys = {
                "provider",
                "classification",
                "action_reference",
                "event_numbers",
                "tool",
                "provider_item_type",
                "input",
                "status",
                "exit_code",
                "action_id",
            }
            if set(action) != expected_action_keys:
                raise CampaignError(f"{label}: action shape is not exact")
            if (
                action.get("provider") != "codex"
                or action.get("classification")
                != "declared_mcp_tool_action"
                or action.get("tool") != "mcp__operator__terminal"
                or action.get("provider_item_type") != "mcp_tool_call"
                or action.get("status") != "completed"
                or action.get("exit_code") is not None
            ):
                raise CampaignError(f"{label}: terminal action identity differs")
            value = action.get("input")
            if not isinstance(value, dict) or set(value) != {"observations"}:
                raise CampaignError(f"{label}: observations wrapper is not exact")
            observations = value["observations"]
            if not isinstance(observations, list) or len(observations) != 2:
                raise CampaignError(
                    f"{label}: expected exactly started/completed observations"
                )
            expected_event_types = ("item.started", "item.completed")
            event_numbers: list[int] = []
            commands: list[str] = []
            item_ids: list[str] = []
            paired_arguments: list[dict[str, Any]] = []
            for observation_position, (
                observation,
                expected_event_type,
            ) in enumerate(
                zip(observations, expected_event_types, strict=True),
                1,
            ):
                observation_label = (
                    f"{label} observation {observation_position}"
                )
                if (
                    not isinstance(observation, dict)
                    or set(observation)
                    != {
                        "event_number",
                        "event_type",
                        "item_sha256",
                        "item",
                    }
                ):
                    raise CampaignError(
                        f"{observation_label}: observation shape is not exact"
                    )
                event_number = observation.get("event_number")
                if (
                    not isinstance(event_number, int)
                    or isinstance(event_number, bool)
                    or event_number < 1
                    or observation.get("event_type") != expected_event_type
                ):
                    raise CampaignError(
                        f"{observation_label}: event identity differs"
                    )
                item = observation.get("item")
                if (
                    not isinstance(item, dict)
                    or set(item)
                    != {
                        "id",
                        "type",
                        "server",
                        "tool",
                        "arguments",
                        "result",
                        "error",
                        "status",
                    }
                    or item.get("type") != "mcp_tool_call"
                    or item.get("server") != "operator"
                    or item.get("tool") != "terminal"
                ):
                    raise CampaignError(
                        f"{observation_label}: MCP item shape differs"
                    )
                item_sha256 = observation.get("item_sha256")
                if (
                    not isinstance(item_sha256, str)
                    or item_sha256
                    != sha256_bytes(_canonical_json_bytes(item))
                ):
                    raise CampaignError(
                        f"{observation_label}: item digest differs"
                    )
                arguments = item.get("arguments")
                if not _probe_terminal_arguments_are_exact(
                    arguments,
                    expected_command=expected_command,
                ):
                    raise CampaignError(
                        f"{observation_label}: terminal arguments are not exact"
                    )
                if expected_event_type == "item.started":
                    if (
                        item.get("status") != "in_progress"
                        or item.get("result") is not None
                        or item.get("error") is not None
                    ):
                        raise CampaignError(
                            f"{observation_label}: started state differs"
                        )
                elif (
                    item.get("status") != "completed"
                    or not isinstance(item.get("result"), dict)
                    or item.get("error") is not None
                ):
                    raise CampaignError(
                        f"{observation_label}: completed state differs"
                    )
                item_id = item.get("id")
                if not isinstance(item_id, str) or not item_id:
                    raise CampaignError(
                        f"{observation_label}: item ID is absent"
                    )
                event_numbers.append(event_number)
                commands.append(arguments["command"])
                item_ids.append(item_id)
                paired_arguments.append(arguments)
            if (
                event_numbers != sorted(event_numbers)
                or event_numbers[0] == event_numbers[1]
                or action.get("event_numbers") != event_numbers
                or item_ids[0] != item_ids[1]
                or action.get("action_id") != item_ids[0]
                or action.get("action_reference")
                != f"codex:{item_ids[0]}"
            ):
                raise CampaignError(
                    f"{label}: started/completed correlation differs"
                )
            if (
                commands[0] != commands[1]
                or paired_arguments[0] != paired_arguments[1]
            ):
                raise CampaignError(
                    f"{label}: started/completed terminal arguments differ"
                )
            command = commands[0]
            records.append(
                {
                    "position": position,
                    "provider": "codex",
                    "action_reference": action["action_reference"],
                    "event_numbers": event_numbers,
                    "command": command,
                    "command_sha256": sha256_bytes(command.encode("utf-8")),
                    "argument_keys": sorted(paired_arguments[0]),
                    "explicit_timeout_seconds": paired_arguments[0].get(
                        "timeout_seconds"
                    ),
                    "same_command_in_started_and_completed": True,
                }
            )
            continue
        if provider == "anthropic-sonnet":
            expected_action_keys = {
                "provider",
                "classification",
                "action_reference",
                "event_numbers",
                "tool",
                "input",
                "tool_use_id",
                "raw_tool_use",
            }
            if set(action) != expected_action_keys:
                raise CampaignError(f"{label}: action shape is not exact")
            raw_tool_use = action.get("raw_tool_use")
            arguments = action.get("input")
            event_numbers = action.get("event_numbers")
            tool_use_id = action.get("tool_use_id")
            if (
                action.get("provider") != "claude"
                or action.get("classification")
                != "declared_mcp_tool_action"
                or action.get("tool") != "mcp__operator__terminal"
                or not isinstance(raw_tool_use, dict)
                or set(raw_tool_use) != {"type", "id", "name", "input"}
                or raw_tool_use.get("type") != "tool_use"
                or raw_tool_use.get("name") != "mcp__operator__terminal"
                or raw_tool_use.get("id") != tool_use_id
                or raw_tool_use.get("input") != arguments
                or not isinstance(tool_use_id, str)
                or not tool_use_id
                or action.get("action_reference")
                != f"claude:{tool_use_id}"
                or not isinstance(event_numbers, list)
                or len(event_numbers) != 1
                or not isinstance(event_numbers[0], int)
                or isinstance(event_numbers[0], bool)
                or event_numbers[0] < 1
                or not _probe_terminal_arguments_are_exact(
                    arguments,
                    expected_command=expected_command,
                )
            ):
                raise CampaignError(f"{label}: terminal tool use differs")
            command = arguments["command"]
            records.append(
                {
                    "position": position,
                    "provider": "claude",
                    "action_reference": action["action_reference"],
                    "event_numbers": event_numbers,
                    "command": command,
                    "command_sha256": sha256_bytes(command.encode("utf-8")),
                    "argument_keys": sorted(arguments),
                    "explicit_timeout_seconds": arguments.get(
                        "timeout_seconds"
                    ),
                    "same_command_in_started_and_completed": None,
                }
            )
            continue
        raise CampaignError(
            f"{label}: unsupported provider configuration"
        )
    return records


def run_installation_surface_probes(
    providers: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Prove real installed Maude/PTY/socket use in fresh provider contexts."""

    selected_providers = _probe_provider_scope(providers)
    if MANIFEST_PATH.exists():
        raise CampaignError(
            "installation-surface probes are pre-freeze only; manifest exists"
        )
    if INSTALL_SURFACE_PROBE_PATH.exists():
        raise CampaignError(
            "installation-surface probe index exists; refusing to overwrite"
        )
    attempt_id = (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + uuid.uuid4().hex[:12]
    )
    probe_root = INSTALL_SURFACE_PROBE_PATH.parent
    attempt_root = probe_root / "attempts" / attempt_id
    attempt_root.mkdir(parents=True)
    results: list[dict[str, Any]] = []
    system_prompt = (
        "This is a non-campaign installation-surface capability probe. "
        "Perform only the exact local PTY commands requested. Do not inspect "
        "source, package media, evaluator files, credentials, unrelated "
        "environment variables, or the network. Do not perform any task or "
        "external effect. Report the exact marker "
        "INSTALL_SURFACE_PROBE_OK only after the command result."
    )
    for provider in selected_providers:
        probe_run_id = (
            f"_install-surface-{provider}-{uuid.uuid4().hex[:10]}"
        )
        lab = _lab_dir(probe_run_id)
        install_root = lab / "installation"
        work = install_root / "work"
        run_dir = install_root / "run"
        project = install_root / "project"
        operator_home = install_root / "home"
        evidence = lab / "evidence"
        raw = evidence / "raw"
        provider_evidence = attempt_root / provider
        provider_home = lab / "private-provider-home"
        runtime_process: ManagedProcess | None = None
        boundary: dict[str, Any] | None = None
        probe_socket_directory: Path | None = None
        try:
            for path in (
                work,
                run_dir,
                project,
                operator_home,
                raw,
                evidence / "observable",
            ):
                path.mkdir(parents=True, exist_ok=True)
            _materialize_installed_distribution(
                {
                    "run_id": probe_run_id,
                    "source_visibility": "installed-distribution",
                },
                install_root,
                evidence,
            )
            venv = install_root / "venv"
            adapter = work / "operator-pty"
            _copy_file(
                HARNESS_DIR / "operator_pty.py",
                adapter,
                executable=True,
            )
            probe_socket_directory = _private_socket_directory(
                label=f"{probe_run_id}-governor"
            )
            socket_path = _checked_unix_socket_path(
                probe_socket_directory / "broker.sock",
                label=f"{probe_run_id} synthetic Governor",
            )
            runtime_state = raw / "runtime-private"
            runtime_config = {
                "schema": "maude.synthetic-runtime.v1",
                "scenario_id": "installation-surface-capability-probe",
                "workspace": {
                    "path": str(project),
                    "base_files": {},
                },
                "governor": {
                    "context_id": "synthetic-installation-probe",
                    "initialized": True,
                    "mode": "code",
                    "pill": "OK",
                    "sentence": (
                        "Non-campaign installation-surface capability probe."
                    ),
                },
                "runtime": {"behavior": "normal", "timeout_seconds": None},
            }
            runtime_config_path = raw / "runtime.json"
            write_json(runtime_config_path, runtime_config)
            runtime_process = ManagedProcess(
                [
                    sys.executable,
                    "-B",
                    str(HARNESS_DIR / "synthetic_runtime.py"),
                    "--config",
                    str(runtime_config_path),
                    "--socket",
                    str(socket_path),
                    "--state-dir",
                    str(runtime_state),
                    "--trace",
                    str(runtime_state / "rpc-transcript.jsonl"),
                ],
                cwd=lab,
                stdout_path=raw / "runtime.stdout",
                stderr_path=raw / "runtime.stderr",
            )
            _wait_ready(
                runtime_state / "runtime-ready.json",
                runtime_process,
            )
            copied_auth, credential_values = _copy_provider_home(
                provider,
                provider_home,
            )
            _prepare_clean_operator_home(operator_home)
            write_json(
                provider_evidence / "clean-home-before.json",
                _operator_home_inventory(operator_home),
            )
            if provider == "anthropic-sonnet":
                environment = _claude_clean_environment(operator_home)
                environment.update(
                    {
                        "GOVERNOR_SOCKET": str(socket_path),
                        "TERM": "xterm-256color",
                    }
                )
                boundary = _build_claude_boundary(
                    label=f"install-probe-{uuid.uuid4().hex[:10]}",
                    lab=lab,
                    mode="operator",
                    provider_home=provider_home,
                    cwd=work,
                    operator_home=operator_home,
                    mounts=[
                        {
                            "source": str(work),
                            "target": str(work),
                            "mode": "rw",
                        },
                        {
                            "source": str(venv),
                            "target": str(venv),
                            "mode": "ro",
                        },
                        {
                            "source": str(project),
                            "target": str(project),
                            "mode": "ro",
                        },
                        {
                            "source": str(operator_home),
                            "target": str(OPERATOR_HOME_MOUNT),
                            "mode": "rw",
                        },
                    ],
                    sockets=[
                        {
                            "source": str(socket_path),
                            "target": str(socket_path),
                        }
                    ],
                    environment=environment,
                    pty_adapter=adapter,
                )
                isolation = _claude_mcp_isolation_preflight(boundary)
                bwrap_prefix: list[str] = []
                provider_cwd = boundary["transport_cwd"]
            else:
                environment = _claude_clean_environment(operator_home)
                environment.update(
                    {
                        "GOVERNOR_SOCKET": str(socket_path),
                        "TERM": "xterm-256color",
                    }
                )
                boundary = _adapt_boundary_for_codex(
                    _build_claude_boundary(
                        label=f"install-probe-{uuid.uuid4().hex[:10]}",
                        lab=lab,
                        mode="operator",
                        provider_home=provider_home,
                        cwd=work,
                        operator_home=operator_home,
                        mounts=[
                            {
                                "source": str(work),
                                "target": str(work),
                                "mode": "rw",
                            },
                            {
                                "source": str(venv),
                                "target": str(venv),
                                "mode": "ro",
                            },
                            {
                                "source": str(project),
                                "target": str(project),
                                "mode": "ro",
                            },
                            {
                                "source": str(operator_home),
                                "target": str(OPERATOR_HOME_MOUNT),
                                "mode": "rw",
                            },
                        ],
                        sockets=[
                            {
                                "source": str(socket_path),
                                "target": str(socket_path),
                            }
                        ],
                        environment=environment,
                        pty_adapter=adapter,
                    )
                )
                bwrap_prefix = _codex_mcp_transport_bwrap(
                    boundary, provider_home, operator_home
                )
                isolation = _codex_mcp_isolation_preflight(
                    boundary, bwrap_prefix
                )
                provider_cwd = boundary["transport_cwd"]
            write_json(provider_evidence / "isolation.json", isolation)
            typescript = work / "pty.typescript"
            pty_state = work / "pty-state"
            exact_commands = _installation_pty_commands(
                adapter=adapter,
                pty_state=pty_state,
                typescript=typescript,
                maude=venv / "bin" / "maude",
            )
            tool_label = (
                "the terminal tool"
            )
            user_prompt = (
                f"Use {tool_label} exactly eight times. Execute the following "
                "literal commands in order, one command per action. Wait for and "
                "inspect each result before starting the next action; do not "
                "combine actions:\n\n"
                + "\n".join(
                    f"{index}. `{command}`"
                    for index, command in enumerate(exact_commands, 1)
                )
                + "\n\nAfter the eighth result, report whether the same PTY "
                "process remained available across calls and finish with "
                "INSTALL_SURFACE_PROBE_OK. Do not run any other command."
            )
            write_text(provider_evidence / "system-prompt.md", system_prompt)
            write_text(provider_evidence / "user-prompt.md", user_prompt)
            provider_argv, delivery, stdin_payload = _provider_argv(
                provider,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                cwd=work,
                additional_dirs=(
                    []
                    if boundary is not None
                    else [OPERATOR_HOME_MOUNT, work, venv, run_dir]
                ),
                allowed_unix_sockets=(
                    [] if boundary is not None else [socket_path]
                ),
                claude_boundary=boundary,
            )
            stdout_path = provider_evidence / "transcript.jsonl"
            stderr_path = provider_evidence / "provider.stderr"
            process_result = _run_model_process(
                (
                    provider_argv
                    if provider == "anthropic-sonnet"
                    else [*bwrap_prefix, *provider_argv]
                ),
                cwd=provider_cwd,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                timeout=AUTH_GATE_PROBE_TIMEOUT,
                provider=provider,
                provider_home=provider_home,
                copied_auth=copied_auth,
                credential_values=credential_values,
                gate_record_path=provider_evidence / "auth-gate.json",
                claude_boundary=boundary,
                user_prompt=user_prompt if boundary is not None else None,
                process_env=(
                    boundary["provider_environment"]
                    if provider == "anthropic-sonnet"
                    else None
                ),
                codex_auth_mode="retained-private-home",
                stdin_payload=stdin_payload,
            )
            _quarantine_if_secret(
                [stdout_path, stderr_path, typescript],
                credential_values,
                run_id=f"installation-surface-{provider}",
                evidence_dir=provider_evidence,
            )
            write_json(
                provider_evidence / "clean-home-after.json",
                _operator_home_inventory(operator_home),
            )
            events = _provider_events(stdout_path)
            actions = _event_actions(events)
            identity = _session_identity(events, provider)
            identity_value = identity.get(
                "provider_session_id"
            ) or identity.get("provider_thread_id")
            answers = _final_answer_records(events)
            marker_present = any(
                "INSTALL_SURFACE_PROBE_OK" in record["text"]
                for record in answers
            )
            safety = _audit_actions(actions)
            trace_path = runtime_state / "rpc-transcript.jsonl"
            trace_pairs = _installation_trace_pairs(trace_path)
            rpc_contract_predicates = (
                _installation_rpc_contract_predicates(trace_pairs)
            )
            terminal_action_records: list[dict[str, Any]] = []
            terminal_action_parse_error: str | None = None
            try:
                terminal_action_records = (
                    _installation_terminal_action_commands(
                        actions,
                        provider=provider,
                        expected_commands=exact_commands,
                    )
                )
            except CampaignError as exc:
                terminal_action_parse_error = str(exc)
            observed_terminal_commands = [
                str(record["command"])
                for record in terminal_action_records
            ]
            exact_terminal_commands_match_positionally = (
                terminal_action_parse_error is None
                and observed_terminal_commands == exact_commands
            )
            completed_actions = _completed_action_event_records(events)
            successful_completed_actions = [
                record
                for record in completed_actions
                if record["succeeded"]
            ]
            successful_outputs = _successful_action_outputs(events)
            expected_payload_kinds = (
                "state",
                "read",
                "ack",
                "ack",
                "read",
                "ack",
                "read",
                "state",
            )
            parsed_outputs: list[dict[str, Any]] = []
            output_parse_error: str | None = None
            if len(successful_outputs) == len(exact_commands):
                try:
                    parsed_outputs = [
                        _parse_installation_broker_result(
                            str(record.get("output", "")),
                            expected_command=command,
                            expected_cwd=work,
                            payload_kind=payload_kind,
                        )
                        for record, command, payload_kind in zip(
                            successful_outputs,
                            exact_commands,
                            expected_payload_kinds,
                            strict=True,
                        )
                    ]
                except CampaignError as exc:
                    output_parse_error = str(exc)
            output_records_align = (
                len(successful_outputs) == len(exact_commands)
                and len(parsed_outputs) == len(exact_commands)
                and output_parse_error is None
            )
            parsed_payloads = (
                [value["payload"] for value in parsed_outputs]
                if output_records_align
                else [{} for _ in exact_commands]
            )
            (
                start_output,
                first_read_output,
                focus_send_output,
                command_send_output,
                second_read_output,
                stop_output,
                final_read_output,
                status_output,
            ) = parsed_payloads
            exposed_states = [
                start_output,
                (
                    focus_send_output.get("state")
                    if isinstance(focus_send_output.get("state"), dict)
                    else {}
                ),
                (
                    command_send_output.get("state")
                    if isinstance(command_send_output.get("state"), dict)
                    else {}
                ),
                (
                    stop_output.get("state")
                    if isinstance(stop_output.get("state"), dict)
                    else {}
                ),
                status_output,
            ]
            process_identity_pairs = {
                (
                    value.get("daemon_pid"),
                    value.get("child_pid"),
                )
                for value in exposed_states
                if value.get("daemon_pid") and value.get("child_pid")
            }
            same_pty_process = (
                len(exposed_states) == 5
                and all(value for value in exposed_states)
                and len(process_identity_pairs) == 1
            )
            nonempty_reads = all(
                isinstance(value.get("bytes_read"), int)
                and value["bytes_read"] > 0
                for value in (
                    first_read_output,
                    second_read_output,
                    final_read_output,
                )
            )
            read_focus_send_command_send_order_proved = bool(
                exact_terminal_commands_match_positionally
                and first_read_output
                and focus_send_output.get("operation") == "send"
                and command_send_output.get("operation") == "send"
                and second_read_output
                and stop_output.get("operation") == "stop"
                and final_read_output
            )
            pty_state_value = (
                load_json(pty_state / "state.json")
                if (pty_state / "state.json").is_file()
                else {}
            )
            probe_predicates = {
                "provider_returncode_zero": (
                    process_result["returncode"] == 0
                ),
                "provider_not_timed_out": (
                    process_result["timed_out"] is False
                ),
                "provider_session_identity_present": bool(identity_value),
                "provider_action_count_exact": (
                    len(actions) == len(exact_commands)
                ),
                "successful_completed_action_count_exact": (
                    len(successful_completed_actions) == len(exact_commands)
                ),
                "successful_output_count_exact": (
                    len(successful_outputs) == len(exact_commands)
                ),
                "terminal_action_parse_error_absent": (
                    terminal_action_parse_error is None
                ),
                "output_parse_error_absent": output_parse_error is None,
                "output_records_align": output_records_align,
                "exact_terminal_commands_match_positionally": (
                    exact_terminal_commands_match_positionally
                ),
                "same_pty_process_across_actions": same_pty_process,
                "all_read_results_nonempty": nonempty_reads,
                "read_focus_send_command_send_read_stop_read_order_proved": (
                    read_focus_send_command_send_order_proved
                ),
                "success_marker_present": marker_present,
                "final_answer_present": _has_final_answer(events),
                "pty_typescript_is_file": typescript.is_file(),
                "pty_typescript_nonempty": (
                    typescript.is_file()
                    and typescript.stat().st_size > 0
                ),
                "pty_state_completed": (
                    pty_state_value.get("status") == "completed"
                ),
                "pty_exit_code_zero": pty_state_value.get("exit_code") == 0,
                **rpc_contract_predicates,
                "no_auth_read_attempts": not safety["auth_read_attempts"],
                "no_environment_read_attempts": (
                    not safety["environment_read_attempts"]
                ),
                "no_network_command_attempts": (
                    not safety["network_command_attempts"]
                ),
                "no_host_source_read_attempts": (
                    not safety["host_source_read_attempts"]
                ),
            }
            failed_predicates = [
                name
                for name, passed in probe_predicates.items()
                if not passed
            ]
            if failed_predicates:
                diagnostic_values = {
                    "returncode": process_result["returncode"],
                    "timed_out": process_result["timed_out"],
                    "identity": identity_value,
                    "action_count": len(actions),
                    "successful_completed_action_count": len(
                        successful_completed_actions
                    ),
                    "successful_output_count": len(successful_outputs),
                    "terminal_action_parse_error": (
                        terminal_action_parse_error
                    ),
                    "expected_terminal_command_sha256": [
                        sha256_bytes(command.encode("utf-8"))
                        for command in exact_commands
                    ],
                    "observed_terminal_command_sha256": [
                        record["command_sha256"]
                        for record in terminal_action_records
                    ],
                    "output_parse_error": output_parse_error,
                    "process_identity_pairs": sorted(
                        process_identity_pairs
                    ),
                    "read_bytes": [
                        value.get("bytes_read")
                        for value in (
                            first_read_output,
                            second_read_output,
                            final_read_output,
                        )
                    ],
                    "pty_state": pty_state_value,
                    "trace_methods": [
                        {
                            "method": pair.get("method"),
                            "response_kind": pair.get("response_kind"),
                        }
                        for pair in trace_pairs
                    ],
                    "safety": safety,
                }
                raise CampaignError(
                    f"{provider} installation-surface probe failed: "
                    f"failed_predicates={failed_predicates!r} "
                    "predicate_results="
                    f"{json.dumps(probe_predicates, sort_keys=True)} "
                    "diagnostic_values="
                    f"{json.dumps(diagnostic_values, sort_keys=True)}"
                )
            package_probe = _installation_probe(
                install_root,
                expected_installed=True,
            )
            observed = package_probe["observed"]
            preserved_typescript = provider_evidence / "pty.typescript"
            preserved_trace = (
                provider_evidence / "rpc-transcript.jsonl"
            )
            preserved_pty_state = provider_evidence / "pty-state"
            _copy_file(typescript, preserved_typescript)
            _copy_file(trace_path, preserved_trace)
            _copy_tree(pty_state, preserved_pty_state)
            result = {
                "provider_config": provider,
                "campaign_run": False,
                "fresh_process": True,
                "session_identity": identity,
                "delivery": delivery,
                "process": process_result,
                "tool_actions_after_gate": len(actions),
                "stateful_pty_actions": len(exact_commands),
                "exact_pty_command_sha256": [
                    sha256_bytes(command.encode("utf-8"))
                    for command in exact_commands
                ],
                "exact_terminal_commands_match_positionally": (
                    exact_terminal_commands_match_positionally
                ),
                "terminal_action_records": [
                    {
                        key: value
                        for key, value in record.items()
                        if key != "command"
                    }
                    for record in terminal_action_records
                ],
                "completed_action_events": completed_actions,
                "successful_completed_action_events": (
                    successful_completed_actions
                ),
                "read_before_input_proved": bool(first_read_output),
                "read_after_input_proved": bool(second_read_output),
                "read_after_stop_proved": bool(final_read_output),
                "all_read_results_nonempty": nonempty_reads,
                "tab_focus_send_proved": bool(focus_send_output),
                "status_command_send_proved": bool(command_send_output),
                "read_after_status_input_proved": bool(second_read_output),
                "read_focus_send_command_send_read_stop_read_order_proved": (
                    read_focus_send_command_send_order_proved
                ),
                "same_pty_process_across_provider_tool_actions": (
                    same_pty_process
                ),
                "process_identity_pairs": [
                    {
                        "daemon_pid": daemon_pid,
                        "child_pid": child_pid,
                    }
                    for daemon_pid, child_pid in sorted(
                        process_identity_pairs
                    )
                ],
                "successful_action_output_sha256": [
                    sha256_bytes(
                        str(record.get("output", "")).encode("utf-8")
                    )
                    for record in successful_outputs
                ],
                "pty_state": pty_state_value,
                "pty_state_artifacts": inventory_files(
                    preserved_pty_state
                ),
                "pty_typescript": file_record(
                    preserved_typescript,
                    relative_to=probe_root,
                ),
                "entrypoint": {
                    "path": str(venv / "bin" / "maude"),
                    "sha256": observed["console_script_sha256"],
                    "version": observed["maude_distribution_version"],
                    "module_inside_venv": observed[
                        "maude_module_inside_prefix"
                    ],
                },
                "pty_adapter": file_record(
                    adapter,
                    relative_to=lab,
                ),
                "runtime_trace_pairs": trace_pairs,
                "runtime_trace_contract_predicates": (
                    rpc_contract_predicates
                ),
                "rpc_transcript": file_record(
                    preserved_trace,
                    relative_to=probe_root,
                ),
                "real_governor_hello_request_response": True,
                "real_sessions_list_request_response": True,
                "real_sessions_create_request_response": True,
                "real_governor_now_request_response": True,
                "real_governor_status_request_response": True,
                "command_linked_runtime_session_list_request_response": True,
                "typed_status_rpc_sequence_in_order": True,
                "governor_status_attribution": (
                    "Maude polls governor.now. In this isolated probe, the "
                    "separately focused literal status input is the only "
                    "trigger for governor.status followed by "
                    "runtime.session.list; their ordered successful responses "
                    "prove application handling beyond PTY byte "
                    "acknowledgement."
                ),
                "pty_command_returncode": pty_state_value["exit_code"],
                "clean_home_before": file_record(
                    provider_evidence / "clean-home-before.json",
                    relative_to=probe_root,
                ),
                "clean_home_after": file_record(
                    provider_evidence / "clean-home-after.json",
                    relative_to=probe_root,
                ),
                "gate_record": file_record(
                    provider_evidence / "auth-gate.json",
                    relative_to=probe_root,
                ),
                "safety_audit": safety,
                "installed_distribution_mounted": True,
                "installed_python_module_source_readable": True,
                "host_repository_checkout_mounted": False,
                "release_source_archive_mounted": False,
                "installation_media_mounted": False,
                "expected_answer_or_task_supplied": False,
                "network_or_external_effect": False,
                "final_marker_present": True,
                "raw_transcript": file_record(
                    stdout_path,
                    relative_to=probe_root,
                ),
                "raw_stderr": file_record(
                    stderr_path,
                    relative_to=probe_root,
                ),
                "authority_effect": "none",
            }
            write_json(provider_evidence / "result.json", result)
            results.append(result)
        finally:
            if runtime_process is not None:
                runtime_process.stop()
            boundary_cleanup = _release_private_socket_directories(boundary)
            if not boundary_cleanup["all_removed"]:
                raise CampaignError(
                    "installation probe left a private Claude socket arena"
                )
            if probe_socket_directory is not None:
                probe_socket_cleanup = _release_private_socket_directories(
                    {
                        "private_socket_directories": [
                            probe_socket_directory
                        ]
                    }
                )
                if not probe_socket_cleanup["all_removed"]:
                    raise CampaignError(
                        "installation probe left its Governor socket arena"
                    )
            if provider_home.exists():
                shutil.rmtree(provider_home)
            if lab.exists():
                shutil.rmtree(lab)
    identities = {
        result["session_identity"].get("provider_session_id")
        or result["session_identity"].get("provider_thread_id")
        for result in results
    }
    maude_wheel = next(
        record
        for record in load_json(INSTALL_PROVENANCE)["wheels"]
        if str(record["distribution"]["name"]).casefold() == "maude"
    )
    index = {
        "schema": "maude.synthetic-operator.installation-surface-probes.v2",
        "campaign_id": CAMPAIGN_ID,
        "campaign_run": False,
        "attempt_id": attempt_id,
        "completed_at": _utc_now(),
        "campaign_runner": file_record(
            Path(__file__).resolve(),
            relative_to=REPO_ROOT,
        ),
        "installation_media_provenance": file_record(INSTALL_PROVENANCE),
        "maude_wheel": {
            "path": maude_wheel["path"],
            "bytes": maude_wheel["bytes"],
            "sha256": maude_wheel["sha256"],
            "distribution": maude_wheel["distribution"],
        },
        "requested_provider_configs": list(selected_providers),
        "not_requested_provider_configs": sorted(
            set(_configured_campaign_providers())
            - set(selected_providers)
        ),
        "providers": results,
        "stateful_pty_contract": {
            "exact_operation_sequence_proved": [
                "start",
                "read",
                "send-tab-focus",
                "send-status-command",
                "read",
                "stop",
                "read",
                "status",
            ],
            "one_child_across_separate_provider_tool_actions": all(
                result["same_pty_process_across_provider_tool_actions"]
                for result in results
            ),
            "separate_read_focus_send_command_send_read_stop_read_order_proved": all(
                result[
                    "read_focus_send_command_send_read_stop_read_order_proved"
                ]
                for result in results
            ),
            "typed_status_rpc_sequence_proved": all(
                result["typed_status_rpc_sequence_in_order"]
                for result in results
            ),
            "predeclared_command_sequence": True,
            "claim_scope": (
                "Proves cross-call PTY persistence and application handling "
                "of the predeclared status command after explicit input "
                "focus; it does not claim the probe model chose an unplanned "
                "input."
            ),
            "exact_pty_bytes_preserved": all(
                bool(result["pty_typescript"].get("sha256"))
                for result in results
            ),
        },
        "distinct_session_identities": (
            len(identities) == len(selected_providers)
        ),
        "all_passed": (
            len(results) == len(selected_providers)
            and len(identities) == len(selected_providers)
        ),
        "raw_evidence_location": str(attempt_root),
        "raw_evidence_committed": False,
        "authority_effect": "none",
    }
    write_json(INSTALL_SURFACE_PROBE_PATH, index)
    return index


def _quarantine_if_secret(
    paths: list[Path],
    credential_values: list[bytes],
    *,
    run_id: str,
    evidence_dir: Path,
) -> None:
    hits: list[dict[str, Any]] = []
    hit_paths: set[Path] = set()
    usable_values = {value for value in credential_values if len(value) >= 12}
    for path in paths:
        data = path.read_bytes()
        for value in usable_values:
            if value in data:
                hits.append(
                    {
                        "path": path.name,
                        "kind": "exact copied credential value",
                        "sha256": sha256_file(path),
                    }
                )
                hit_paths.add(path)
                break
        for pattern in OBVIOUS_SECRET_PATTERNS:
            if pattern.search(data):
                hits.append(
                    {
                        "path": path.name,
                        "kind": f"obvious secret prefix: {pattern.pattern!r}",
                        "sha256": sha256_file(path),
                    }
                )
                hit_paths.add(path)
                break
    if not hits:
        return
    quarantine = QUARANTINE_ROOT / CAMPAIGN_ID / run_id / uuid.uuid4().hex
    quarantine.mkdir(parents=True, mode=0o700)
    for index, path in enumerate(sorted(hit_paths), 1):
        if path.exists():
            destination = quarantine / f"{index:04d}-{path.name}"
            shutil.move(str(path), destination)
    write_json(
        evidence_dir / "credential-redaction-notice.json",
        {
            "schema": "maude.synthetic-operator.credential-quarantine.v1",
            "run_id": run_id,
            "hits": hits,
            "quarantine": str(quarantine),
            "raw_output_committable": False,
        },
    )
    raise CampaignError(
        f"{run_id}: provider output contained credential material; raw output "
        f"quarantined at {quarantine}"
    )


def _provider_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_bytes().splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            value = {
                "type": "non_json_provider_output",
                "line": number,
                "base64": base64.b64encode(line).decode("ascii"),
            }
        if isinstance(value, dict):
            events.append(value)
        else:
            events.append({"type": "non_object_provider_output", "value": value})
    return events


def _event_actions(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Preserve every provider action, including unknown Codex item types."""

    actions: list[dict[str, Any]] = []
    seen_claude: set[str] = set()
    codex_indexes: dict[str, int] = {}
    codex_non_actions = {"agent_message", "reasoning"}
    codex_known_actions = {
        "command_execution",
        "file_change",
        "apply_patch",
        "mcp_tool_call",
        "web_search",
        "image_generation",
        "computer_use",
        "collab_tool_call",
        "tool_call",
    }

    for event_number, event in enumerate(events, 1):
        for block in _recursive_blocks(event, "tool_use"):
            identity = str(block.get("id") or "")
            reference = (
                f"claude:{identity}"
                if identity
                else f"claude:event-{event_number}"
            )
            if reference in seen_claude:
                continue
            seen_claude.add(reference)
            actions.append(
                {
                    "provider": "claude",
                    "classification": "declared_mcp_tool_action",
                    "action_reference": reference,
                    "event_numbers": [event_number],
                    "tool": block.get("name"),
                    "input": block.get("input"),
                    "tool_use_id": block.get("id"),
                    "raw_tool_use": block,
                }
            )
        item = event.get("item")
        if (
            not isinstance(event.get("type"), str)
            or not str(event["type"]).startswith("item.")
            or not isinstance(item, dict)
        ):
            continue
        item_type = str(item.get("type") or "missing_type")
        if item_type in codex_non_actions:
            continue
        identity = str(item.get("id") or "")
        reference = (
            f"codex:{identity}"
            if identity
            else f"codex:event-{event_number}"
        )
        observation = {
            "event_number": event_number,
            "event_type": event["type"],
            "item_sha256": sha256_bytes(_canonical_json_bytes(item)),
            "item": item,
        }
        if reference in codex_indexes:
            action = actions[codex_indexes[reference]]
            if action["provider_item_type"] != item_type:
                action["classification"] = "unexpected_action"
                action["item_type_changed"] = True
            action["event_numbers"].append(event_number)
            action["input"]["observations"].append(observation)
            action["status"] = item.get("status", action.get("status"))
            action["exit_code"] = item.get(
                "exit_code", action.get("exit_code")
            )
            continue
        codex_indexes[reference] = len(actions)
        actions.append(
            {
                "provider": "codex",
                "classification": (
                    "declared_mcp_tool_action"
                    if item_type == "mcp_tool_call"
                    else "known_action"
                    if item_type in codex_known_actions
                    else "unexpected_action"
                ),
                "action_reference": reference,
                "event_numbers": [event_number],
                "tool": (
                    "file_change/apply_patch"
                    if item_type in {"file_change", "apply_patch"}
                    else (
                        "mcp__"
                        + str(item.get("server") or item.get("server_name"))
                        + "__"
                        + str(item.get("tool") or item.get("tool_name"))
                    )
                    if item_type == "mcp_tool_call"
                    else item_type
                ),
                "provider_item_type": item_type,
                "input": {"observations": [observation]},
                "status": item.get("status"),
                "exit_code": item.get("exit_code"),
                "action_id": item.get("id"),
            }
        )
    return actions


def _action_accounting(
    events: list[dict[str, Any]],
    actions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Prove that every provider action in the raw stream is represented."""

    expected: set[str] = set()
    codex_non_actions = {"agent_message", "reasoning"}
    for event_number, event in enumerate(events, 1):
        for block in _recursive_blocks(event, "tool_use"):
            identity = str(block.get("id") or "")
            expected.add(
                f"claude:{identity}"
                if identity
                else f"claude:event-{event_number}"
            )
        item = event.get("item")
        if (
            isinstance(event.get("type"), str)
            and str(event["type"]).startswith("item.")
            and isinstance(item, dict)
            and str(item.get("type") or "missing_type")
            not in codex_non_actions
        ):
            identity = str(item.get("id") or "")
            expected.add(
                f"codex:{identity}"
                if identity
                else f"codex:event-{event_number}"
            )
    represented_values = [
        value.get("action_reference") for value in actions
    ]
    represented = {
        value for value in represented_values if isinstance(value, str)
    }
    duplicates = sorted(
        {
            value
            for value in represented
            if represented_values.count(value) != 1
        }
    )
    unrepresented = sorted(expected - represented)
    unexpected_representations = sorted(represented - expected)
    unexpected_action_types = sorted(
        {
            str(action.get("provider_item_type"))
            for action in actions
            if action.get("classification") == "unexpected_action"
        }
    )
    return {
        "schema": "maude.synthetic-operator.action-accounting.v1",
        "observed_action_references": sorted(expected),
        "represented_action_references": sorted(represented),
        "duplicate_action_references": duplicates,
        "unrepresented_action_references": unrepresented,
        "unexpected_representations": unexpected_representations,
        "unexpected_action_types": unexpected_action_types,
        "all_provider_actions_represented_once": not any(
            (duplicates, unrepresented, unexpected_representations)
        ),
        "classification_rule": (
            "Every Claude tool_use and every Codex item.* other than "
            "agent_message/reasoning is an action; unknown Codex item types "
            "are preserved as unexpected_action."
        ),
    }


def _session_identity(events: list[dict[str, Any]], config_id: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "configured_model": (
            "sonnet" if config_id == "anthropic-sonnet" else "gpt-5.6-sol"
        )
    }
    for event in events:
        if event.get("type") == "system" and event.get("subtype") == "init":
            result.update(
                {
                    "provider_session_id": event.get("session_id"),
                    "provider_reported_model": event.get("model"),
                    "provider_reported_tools": event.get("tools"),
                }
            )
        if event.get("type") == "thread.started":
            result["provider_thread_id"] = event.get("thread_id")
    return result


def _has_final_answer(events: list[dict[str, Any]]) -> bool:
    for event in events:
        if event.get("type") == "result":
            return True
        item = event.get("item")
        if (
            isinstance(item, dict)
            and item.get("type") == "agent_message"
            and isinstance(item.get("text"), str)
            and item["text"].strip()
        ):
            return True
    return False


def _final_answer_records(
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for number, event in enumerate(events, 1):
        if event.get("type") == "result":
            value = event.get("result")
            if isinstance(value, str) and value.strip():
                records.append({"event_number": number, "text": value})
        item = event.get("item")
        if (
            event.get("type") == "item.completed"
            and isinstance(item, dict)
            and item.get("type") == "agent_message"
            and isinstance(item.get("text"), str)
            and item["text"].strip()
        ):
            records.append({"event_number": number, "text": item["text"]})
    return records


def _completed_action_event_records(
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen_results: set[tuple[str, str]] = set()
    claude_tools: dict[str, str | None] = {}

    def blocks(value: Any, block_type: str) -> Iterable[dict[str, Any]]:
        if isinstance(value, dict):
            if value.get("type") == block_type:
                yield value
            for child in value.values():
                yield from blocks(child, block_type)
        elif isinstance(value, list):
            for child in value:
                yield from blocks(child, block_type)

    for number, event in enumerate(events, 1):
        for block in blocks(event, "tool_use"):
            identity = str(block.get("id") or "")
            if identity:
                claude_tools[identity] = (
                    str(block["name"])
                    if isinstance(block.get("name"), str)
                    else None
                )
        for block in blocks(event, "tool_result"):
            identity = str(block.get("tool_use_id") or "")
            result_key = ("claude", identity)
            if not identity or result_key in seen_results:
                continue
            seen_results.add(result_key)
            records.append(
                {
                    "event_number": number,
                    "provider": "claude",
                    "action_id": identity,
                    "tool": claude_tools.get(identity),
                    "completion_kind": "tool_result",
                    "is_error": bool(block.get("is_error", False)),
                    "succeeded": not bool(block.get("is_error", False)),
                }
            )
        item = event.get("item")
        if (
            event.get("type") == "item.completed"
            and isinstance(item, dict)
            and item.get("type") not in {"agent_message", "reasoning"}
        ):
            identity = str(item.get("id") or "")
            result_key = ("codex", identity)
            if not identity or result_key in seen_results:
                continue
            seen_results.add(result_key)
            item_type = str(item.get("type") or "missing_type")
            status = item.get("status")
            exit_code = item.get("exit_code")
            if item_type == "mcp_tool_call":
                succeeded = (
                    status in {None, "completed"}
                    and item.get("error") in {None, ""}
                    and item.get("result") is not None
                )
            else:
                succeeded = (
                    status == "completed"
                    and item.get("error") in {None, ""}
                    and (
                        exit_code == 0
                        if item_type == "command_execution"
                        else exit_code in {None, 0}
                    )
                )
            records.append(
                {
                    "event_number": number,
                    "provider": "codex",
                    "action_id": identity,
                    "tool": (
                        "file_change/apply_patch"
                        if item_type in {"file_change", "apply_patch"}
                        else (
                            "mcp__"
                            + str(item.get("server") or item.get("server_name"))
                            + "__"
                            + str(item.get("tool") or item.get("tool_name"))
                        )
                        if item_type == "mcp_tool_call"
                        else item_type
                    ),
                    "completion_kind": "item.completed",
                    "status": status,
                    "exit_code": exit_code,
                    "succeeded": succeeded,
                }
            )
    return records


def _successful_action_outputs(
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return only output attached to successful provider tool completions."""
    records: list[dict[str, Any]] = []

    def blocks(value: Any, block_type: str) -> Iterable[dict[str, Any]]:
        if isinstance(value, dict):
            if value.get("type") == block_type:
                yield value
            for child in value.values():
                yield from blocks(child, block_type)
        elif isinstance(value, list):
            for child in value:
                yield from blocks(child, block_type)

    for number, event in enumerate(events, 1):
        for block in blocks(event, "tool_result"):
            if bool(block.get("is_error", False)):
                continue
            content = block.get("content")
            records.append(
                {
                    "event_number": number,
                    "provider": "claude",
                    "action_id": block.get("tool_use_id"),
                    "output": (
                        content
                        if isinstance(content, str)
                        else json.dumps(
                            content,
                            ensure_ascii=False,
                            separators=(",", ":"),
                            sort_keys=True,
                        )
                    ),
                }
            )
        item = event.get("item")
        if (
            event.get("type") == "item.completed"
            and isinstance(item, dict)
        ):
            if (
                item.get("type") == "command_execution"
                and item.get("status") == "completed"
                and item.get("exit_code") == 0
            ):
                output = item.get("aggregated_output")
                records.append(
                    {
                        "event_number": number,
                        "provider": "codex",
                        "action_id": item.get("id"),
                        "output": output if isinstance(output, str) else "",
                    }
                )
            elif (
                item.get("type") == "mcp_tool_call"
                and item.get("error") in {None, ""}
                and item.get("result") is not None
            ):
                result = item["result"]
                content = result.get("content") if isinstance(result, dict) else None
                text_blocks = (
                    [
                        str(value["text"])
                        for value in content
                        if isinstance(value, dict)
                        and isinstance(value.get("text"), str)
                    ]
                    if isinstance(content, list)
                    else []
                )
                output = (
                    "\n".join(text_blocks)
                    if text_blocks
                    else result
                    if isinstance(result, str)
                    else json.dumps(
                        result,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    )
                )
                records.append(
                    {
                        "event_number": number,
                        "provider": "codex",
                        "action_id": item.get("id"),
                        "output": output,
                    }
                )
    return records


def _embedded_json_objects(text: str) -> list[dict[str, Any]]:
    """Extract JSON objects embedded in mixed terminal/tool output."""

    decoder = json.JSONDecoder()
    results: list[dict[str, Any]] = []
    for offset, character in enumerate(text):
        if character != "{":
            continue
        with contextlib.suppress(json.JSONDecodeError):
            value, _end = decoder.raw_decode(text[offset:])
            if isinstance(value, dict):
                results.append(value)
    return results


_COMMAND_BROKER_RESULT_KEYS = {
    "command",
    "cwd",
    "returncode",
    "stderr",
    "stderr_truncated",
    "stdout",
    "stdout_truncated",
    "timed_out",
}
_PTY_STATE_KEYS = {
    "captured_bytes",
    "child_pid",
    "command",
    "daemon_pid",
    "exit_code",
    "output",
    "schema",
    "status",
    "updated_at",
}
_PTY_READ_KEYS = {
    "bytes_read",
    "from_offset",
    "next_offset",
    "status",
}
_PTY_ACK_KEYS = {
    "accepted",
    "acknowledged_at",
    "error",
    "inputs_sent",
    "operation",
    "request_id",
    "schema",
    "state",
}


def _exact_json_object(text: str, *, label: str) -> dict[str, Any]:
    def reject_duplicate_keys(
        pairs: list[tuple[str, Any]],
    ) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise CampaignError(f"{label} contains duplicate JSON keys")
            value[key] = item
        return value

    try:
        value = json.loads(text, object_pairs_hook=reject_duplicate_keys)
    except json.JSONDecodeError as exc:
        raise CampaignError(f"{label} is not one exact JSON object") from exc
    if not isinstance(value, dict):
        raise CampaignError(f"{label} is not a JSON object")
    return value


def _validate_installation_pty_state(
    value: Any,
    *,
    label: str,
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _PTY_STATE_KEYS:
        raise CampaignError(f"{label} PTY state key set differs")
    if value["schema"] != "maude.synthetic-operator.stateful-pty.v1":
        raise CampaignError(f"{label} PTY state schema differs")
    if (
        type(value["daemon_pid"]) is not int
        or value["daemon_pid"] <= 0
        or type(value["child_pid"]) is not int
        or value["child_pid"] <= 0
        or type(value["captured_bytes"]) is not int
        or value["captured_bytes"] < 0
        or not isinstance(value["command"], list)
        or not value["command"]
        or not all(isinstance(item, str) for item in value["command"])
        or not isinstance(value["output"], str)
        or not value["output"]
        or value["status"] not in {"running", "completed"}
        or (
            value["exit_code"] is not None
            and type(value["exit_code"]) is not int
        )
        or not isinstance(value["updated_at"], str)
        or not value["updated_at"]
    ):
        raise CampaignError(f"{label} PTY state field contract differs")
    return value


def _parse_installation_broker_result(
    output: str,
    *,
    expected_command: str,
    expected_cwd: Path,
    payload_kind: str,
) -> dict[str, Any]:
    """Decode one exact broker envelope and its operation-specific payload."""

    if payload_kind not in {"state", "read", "ack"}:
        raise CampaignError(
            f"unsupported installation-probe payload kind: {payload_kind}"
        )
    broker_result = _exact_json_object(
        output,
        label="installation-probe command-broker result",
    )
    if set(broker_result) != _COMMAND_BROKER_RESULT_KEYS:
        raise CampaignError(
            "installation-probe command-broker result key set differs"
        )
    if (
        broker_result["command"] != expected_command
        or broker_result["cwd"] != str(expected_cwd)
    ):
        raise CampaignError(
            "installation-probe command-broker command/cwd differs"
        )
    if (
        type(broker_result["returncode"]) is not int
        or broker_result["returncode"] != 0
        or broker_result["timed_out"] is not False
        or broker_result["stdout_truncated"] is not False
        or broker_result["stderr_truncated"] is not False
        or not isinstance(broker_result["stdout"], str)
        or not isinstance(broker_result["stderr"], str)
    ):
        raise CampaignError(
            "installation-probe command-broker completion differs"
        )

    metadata_stream = "stdout" if payload_kind == "state" else "stderr"
    payload = _exact_json_object(
        broker_result[metadata_stream],
        label=(
            "installation-probe "
            f"{payload_kind} payload on {metadata_stream}"
        ),
    )
    if payload_kind == "state":
        _validate_installation_pty_state(
            payload,
            label="installation-probe",
        )
        if broker_result["stderr"] != "":
            raise CampaignError(
                "installation-probe state result has unexpected stderr"
            )
    elif payload_kind == "read":
        if set(payload) != _PTY_READ_KEYS:
            raise CampaignError(
                "installation-probe PTY read payload key set differs"
            )
        if (
            type(payload["bytes_read"]) is not int
            or payload["bytes_read"] <= 0
            or type(payload["from_offset"]) is not int
            or payload["from_offset"] < 0
            or type(payload["next_offset"]) is not int
            or payload["next_offset"] <= payload["from_offset"]
            or payload["next_offset"] - payload["from_offset"]
            != payload["bytes_read"]
            or payload["status"] not in {"running", "completed"}
            or not broker_result["stdout"]
        ):
            raise CampaignError(
                "installation-probe PTY read field contract differs"
            )
    else:
        if set(payload) != _PTY_ACK_KEYS:
            raise CampaignError(
                "installation-probe PTY ack payload key set differs"
            )
        if (
            payload["schema"]
            != "maude.synthetic-operator.stateful-pty-ack.v1"
            or payload["accepted"] is not True
            or payload["error"] is not None
            or type(payload["inputs_sent"]) is not int
            or payload["inputs_sent"] <= 0
            or payload["operation"] not in {"send", "stop"}
            or not isinstance(payload["request_id"], str)
            or not payload["request_id"]
            or not isinstance(payload["acknowledged_at"], str)
            or not payload["acknowledged_at"]
            or broker_result["stdout"] != ""
        ):
            raise CampaignError(
                "installation-probe PTY ack field contract differs"
            )
        _validate_installation_pty_state(
            payload["state"],
            label="installation-probe ack",
        )
    return {
        "broker_result": broker_result,
        "metadata_stream": metadata_stream,
        "payload": payload,
    }


def _scenario_conditions(run: dict[str, Any]) -> dict[str, Any]:
    if run["surface"] == "maude":
        config = load_json(SCENARIOS_DIR / run["scenario_id"] / "runtime.json")
        runtime = config.get("runtime") or {}
        launch = config.get("launch") or {}
        create = config.get("create") or {}
        return {
            "source": "frozen synthetic runtime config; evaluator-private",
            "runtime_behavior": runtime.get("behavior"),
            "create_behavior": create.get("behavior"),
            "launch_behavior": launch.get("behavior"),
            "timeout_seconds": (
                launch.get("timeout_seconds")
                if launch.get("timeout_seconds") is not None
                else runtime.get("timeout_seconds")
            ),
            "initial_session_count": len(config.get("initial_sessions") or []),
            "restart_specimen": run["scenario_id"]
            == "s17-client-daemon-restart",
            "recovery_specimen": run["scenario_id"]
            in {
                "s17-client-daemon-restart",
                "s18-direct-versus-recovery",
                "s20-terminal-unknown",
            },
            "transport_condition": (
                "disconnect_after_dispatch"
                if runtime.get("behavior") == "disconnect_after_dispatch"
                or launch.get("behavior") in {
                    "disconnect",
                    "disconnect_after_dispatch",
                }
                else "local synthetic Unix socket"
            ),
        }
    if run["surface"] == "maude-installation":
        environment = load_json(
            SCENARIOS_DIR / run["scenario_id"] / "environment.json"
        )
        endpoint = load_json(
            PACKET_DIR
            / "installation-endpoints"
            / f"{run['run_id']}.json"
        )
        return {
            "source": (
                "frozen installation environment and endpoint plan; "
                "evaluator-private"
            ),
            "track_id": run["track_id"],
            "task_id": run["task_id"],
            "source_visibility": run["source_visibility"],
            "installation_state": environment.get("installation_state"),
            "governor_state": environment.get("governor_state"),
            "endpoint_mode": endpoint.get("mode"),
            "socket_strategy": endpoint.get("socket_strategy"),
            "coverage": run["coverage"],
            "restart_specimen": False,
            "recovery_specimen": False,
            "transport_condition": "local synthetic Unix socket or declared absence",
        }
    control = load_json(
        PACKET_DIR
        / "direct-runtime"
        / "fixtures"
        / f"{run['run_id']}.json"
    )
    return {
        "source": "frozen direct-runtime control metadata",
        "setup_state": control.get("setup_state"),
        "standing_ttl_ms": control.get("standing_ttl_ms"),
        "setup_reservation_ttl_ms": control.get("setup_reservation_ttl_ms"),
        "restart_specimen": run["scenario_id"] == "s17-client-daemon-restart",
        "recovery_specimen": control.get("setup_state") == "indeterminate",
        "transport_condition": (
            "frozen crash-after-ref-update preparation"
            if control.get("setup_state") == "indeterminate"
            else "in-process frozen Docket/GWR CLI"
        ),
    }


def _observed_restart_count(path: Path) -> int | None:
    if not path.is_file():
        return None
    maximum = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        with contextlib.suppress(json.JSONDecodeError, TypeError, ValueError):
            value = json.loads(line)
            maximum = max(
                maximum, int(value.get("response", {}).get("restart_count", 0))
            )
    return maximum


def _render_transcript(
    system_prompt: str,
    user_prompt: str,
    events: list[dict[str, Any]],
    stderr: bytes,
) -> str:
    logical: list[str] = []
    logical.append("[INITIAL SYSTEM PROMPT]")
    logical.extend(system_prompt.splitlines())
    logical.append("[INITIAL USER PROMPT]")
    logical.extend(user_prompt.splitlines())
    logical.append("[RAW PROVIDER JSON EVENTS — semantically exact; byte source is transcript.jsonl]")
    logical.extend(
        json.dumps(event, ensure_ascii=False, sort_keys=True)
        for event in events
    )
    if stderr:
        logical.append("[PROVIDER STDERR — byte source is raw/provider.stderr]")
        logical.extend(stderr.decode("utf-8", errors="replace").splitlines())
    return "\n".join(
        f"L{index:06d} | {line}" for index, line in enumerate(logical, 1)
    ) + "\n"


def _audit_actions(actions: list[dict[str, Any]]) -> dict[str, Any]:
    serialized = [
        json.dumps(action.get("input"), ensure_ascii=False, sort_keys=True)
        for action in actions
    ]
    auth_reads = [
        text
        for text in serialized
        if re.search(r"\.claude|\.codex/auth|installation_id|credentials", text, re.I)
    ]
    env_reads = [
        text
        for text in serialized
        if re.search(r"(^|[;&| ])(env|printenv|set)([ ;&|]|$)", text, re.I)
    ]
    network: list[str] = []
    for text in serialized:
        direct_network = re.search(
            r"\b(curl|wget|ssh|scp|nc|ncat|telnet)\b|https?://",
            text,
            re.I,
        )
        pip_network = re.search(
            r"\b(?:python(?:3(?:\.\d+)?)?\s+-m\s+)?pip(?:3)?\b"
            r".*\b(install|download|wheel)\b",
            text,
            re.I,
        )
        pip_explicitly_offline = re.search(
            r"(?:^|\s)--no-index(?:\s|$)",
            text,
            re.I,
        )
        git_network = re.search(
            r"\bgit\b.*\b(clone|fetch|pull|ls-remote)\b",
            text,
            re.I,
        )
        package_manager_network = re.search(
            r"\b(apt(?:-get)?|dnf|yum|apk|pacman|zypper)\b"
            r".*\b(install|update|upgrade|download)\b",
            text,
            re.I,
        )
        python_network = re.search(
            r"\bpython(?:3(?:\.\d+)?)?\b.*"
            r"\b(socket|urllib|http\.client|requests|aiohttp)\b",
            text,
            re.I,
        )
        if (
            direct_network
            or git_network
            or package_manager_network
            or python_network
            or (pip_network and not pip_explicitly_offline)
        ):
            network.append(text)
    source_reads = [
        text for text in serialized if str(HOST_SOURCE_ROOT) in text
    ]
    unexpected_actions = [
        {
            "action_reference": action.get("action_reference"),
            "provider_item_type": action.get("provider_item_type"),
            "event_numbers": action.get("event_numbers"),
        }
        for action in actions
        if action.get("classification") == "unexpected_action"
    ]
    return {
        "schema": "maude.synthetic-operator.session-safety-audit.v1",
        "auth_read_attempts": auth_reads,
        "environment_read_attempts": env_reads,
        "network_command_attempts": network,
        "network_attempt_detection": (
            "Includes URL/curl/wget/ssh tools, remote-capable git operations, "
            "OS package-manager acquisition, Python networking modules, and "
            "pip install/download/wheel unless the command explicitly uses "
            "--no-index."
        ),
        "host_source_read_attempts": source_reads,
        "unexpected_provider_actions": unexpected_actions,
        "unexpected_provider_action_count": len(unexpected_actions),
        "zero_auth_env_network_source_attempts": not any(
            (auth_reads, env_reads, network, source_reads)
        ),
    }


def _implementation_source_grade_boundary(
    run: dict[str, Any],
    actions: list[dict[str, Any]],
    transcript: Path,
    evidence: Path,
    *,
    system_prompt: str,
    user_prompt: str,
    stderr: bytes,
) -> dict[str, Any] | None:
    """Audit source inspection and prepare a conditional grader-safe copy."""

    visibility = run.get("source_visibility")
    if visibility not in {"release-source", "installed-distribution"}:
        return None
    action_violations: list[dict[str, Any]] = []
    for index, action in enumerate(actions, 1):
        serialized = json.dumps(
            _action_command_texts(action),
            ensure_ascii=False,
            sort_keys=True,
        )
        lowered = serialized.casefold()
        release_inspection = visibility == "release-source" and (
            "src/maude" in lowered
            or (
                "maude-source.tar" in lowered
                and re.search(r"\btar\b.*(?:-o|--to-stdout)", lowered)
            )
            or re.search(
                r"\b(cat|sed|head|tail|less|more|grep|rg|awk|strings)\b"
                r".*(?:maude-source|\.py\b)",
                lowered,
            )
        )
        installed_inspection = visibility == "installed-distribution" and (
            re.search(
                r"(?:venv|site-packages).{0,200}(?:/maude/|maude[/\\].*\.py)",
                lowered,
            )
            or (
                re.search(r"(?:^|/)venv/bin/maude\b", lowered)
                and re.search(
                    r"\b(cat|sed|head|tail|less|more|grep|rg|awk|strings|"
                    r"open|read|cp|dd)\b",
                    lowered,
                )
            )
            or re.search(
                r"\b(?:inspect\.getsource|getsourcefile|find_spec|__file__)\b"
                r".{0,200}\bmaude\b",
                lowered,
            )
            or re.search(
                r"\bmaude\b.{0,200}"
                r"\b(?:inspect\.getsource|getsourcefile|find_spec|__file__)\b",
                lowered,
            )
            or re.search(
                r"\b(cat|sed|head|tail|less|more|grep|rg|awk|strings|find)\b"
                r".{0,200}\bvenv\b.{0,200}(?:\.py\b|maude\b)",
                lowered,
            )
        )
        if release_inspection or installed_inspection:
            action_violations.append(
                {
                    "action_index": index,
                    "tool": action.get("tool"),
                    "reason": (
                        "release-source inspection pattern"
                        if release_inspection
                        else "installed-module-source inspection pattern"
                    ),
                    "input_sha256": sha256_bytes(
                        serialized.encode("utf-8")
                    ),
                }
            )
    install_root = _installation_root(run["run_id"])
    source_records = _implementation_source_records(run, install_root)
    matched_values: list[dict[str, Any]] = []

    def redact(value: Any, location: str) -> Any:
        if isinstance(value, str):
            matches = _source_matches(
                value.encode("utf-8"),
                source_records,
            )
            if not matches:
                return value
            matched_values.append(
                {
                    "location": location,
                    "value_sha256": sha256_bytes(value.encode("utf-8")),
                    "matches": matches,
                }
            )
            return (
                "[MECHANICALLY REDACTED: exact mounted implementation-source "
                f"bytes; original value sha256={sha256_bytes(value.encode('utf-8'))}]"
            )
        if isinstance(value, dict):
            return {
                key: redact(child, f"{location}/{key}")
                for key, child in value.items()
            }
        if isinstance(value, list):
            return [
                redact(child, f"{location}/{index}")
                for index, child in enumerate(value)
            ]
        return value

    events = _provider_events(transcript)
    partially_redacted_events = [
        redact(event, f"event/{index}")
        for index, event in enumerate(events, 1)
    ]
    stderr_matches = _source_matches(stderr, source_records)
    source_bytes_detected = bool(matched_values or stderr_matches)
    conservative_withholding = bool(action_violations)
    if conservative_withholding:
        redacted_events = [
            {
                "type": "implementation_source_inspection_redacted",
                "event_number": index,
                "original_event_type": event.get("type"),
                "original_event_sha256": sha256_bytes(
                    json.dumps(
                        event,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    ).encode("utf-8")
                ),
            }
            for index, event in enumerate(events, 1)
        ]
        redacted_stderr = (
            "[MECHANICALLY WITHHELD: implementation-source inspection "
            f"action; original stderr sha256={sha256_bytes(stderr)}]\n"
        ).encode("utf-8")
    else:
        redacted_events = partially_redacted_events
        redacted_stderr = (
            (
            "[MECHANICALLY REDACTED: exact mounted implementation-source "
            f"bytes; original stderr sha256={sha256_bytes(stderr)}]\n"
            ).encode("utf-8")
            if stderr_matches
            else stderr
        )
    grader_redaction_required = bool(
        source_bytes_detected or conservative_withholding
    )
    redacted_jsonl: Path | None = None
    redacted_text: Path | None = None
    if grader_redaction_required:
        redacted_jsonl = evidence / "grader-transcript.redacted.jsonl"
        write_text(
            redacted_jsonl,
            "".join(
                json.dumps(
                    event,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                + "\n"
                for event in redacted_events
            ),
        )
        redacted_text = evidence / "grader-transcript.redacted.txt"
        write_text(
            redacted_text,
            _render_transcript(
                system_prompt,
                user_prompt,
                redacted_events,
                redacted_stderr,
            ),
        )
    result = {
        "schema": "maude.synthetic-installation.source-grade-boundary.v2",
        "run_id": run["run_id"],
        "source_visibility": visibility,
        "release_source_visible_to_operator": visibility == "release-source",
        "installed_module_source_visible_to_operator": (
            visibility == "installed-distribution"
        ),
        "implementation_members_checked": len(source_records),
        "implementation_fingerprints_checked": sum(
            len(record["fingerprints"]) for record in source_records
        ),
        "action_violations": action_violations,
        "transcript_source_matches": matched_values,
        "stderr_source_matches": stderr_matches,
        "exact_source_bytes_detected": source_bytes_detected,
        "source_inspection_action_detected": bool(action_violations),
        "conservative_full_provider_content_withholding": (
            conservative_withholding
        ),
        "grader_transcript_requires_redaction": grader_redaction_required,
        "original_transcript": file_record(
            transcript,
            relative_to=evidence,
        ),
        "grader_transcript_mode": (
            (
                "conservatively-withheld-linked-copy"
                if conservative_withholding
                else "mechanically-redacted-linked-copy"
            )
            if grader_redaction_required
            else "exact-raw-jsonl"
        ),
        "grader_transcript": (
            file_record(redacted_jsonl, relative_to=evidence)
            if redacted_jsonl is not None
            else file_record(transcript, relative_to=evidence)
        ),
        "grader_numbered_transcript": (
            file_record(redacted_text, relative_to=evidence)
            if redacted_text is not None
            else file_record(evidence / "transcript.txt", relative_to=evidence)
        ),
        "evaluator_contamination": bool(
            source_bytes_detected or action_violations
        ),
        "clean_authority_or_ux_inference_permitted": not bool(
            source_bytes_detected or action_violations
        ),
        "operator_completion_or_grading_aborted": False,
        "authority_effect": "none",
    }
    write_json(
        evidence / "source-grade-boundary.json",
        result,
    )
    return result


def _action_command_texts(action: dict[str, Any]) -> list[str]:
    """Extract executable command strings without treating file content as code."""

    value = action.get("input")
    if isinstance(value, str):
        return [value]
    commands: list[str] = []

    def walk(item: Any) -> None:
        if isinstance(item, dict):
            for key, candidate in item.items():
                if key in {"command", "cmd", "script"}:
                    if isinstance(candidate, str):
                        commands.append(candidate)
                    elif isinstance(candidate, list) and all(
                        isinstance(element, str) for element in candidate
                    ):
                        commands.extend(candidate)
                else:
                    walk(candidate)
        elif isinstance(item, list):
            for child in item:
                walk(child)

    walk(value)
    return list(dict.fromkeys(commands))


def _strip_shell_heredoc_bodies(command: str) -> str:
    """Remove heredoc bodies so narrative disposition text is not executable."""

    lines = command.splitlines()
    output: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        output.append(line)
        match = re.search(
            r"<<-?\s*(?:'([^']+)'|\"([^\"]+)\"|([A-Za-z0-9_]+))",
            line,
        )
        if match is None:
            index += 1
            continue
        delimiter = next(
            value for value in match.groups() if value is not None
        )
        index += 1
        while index < len(lines):
            if lines[index].strip() == delimiter:
                index += 1
                break
            index += 1
    return "\n".join(output)


def _quote_aware_shell_segments(command: str) -> list[dict[str, Any]]:
    """Split on shell controls while preserving controls inside quotations."""

    stripped = _strip_shell_heredoc_bodies(command)
    records: list[dict[str, Any]] = []
    start = 0
    quote: str | None = None
    escaped = False

    def append(end: int) -> None:
        raw = stripped[start:end]
        leading = len(raw) - len(raw.lstrip())
        segment = raw.strip()
        if segment:
            records.append(
                {
                    "segment": segment,
                    "start": start + leading,
                    "end": end - (len(raw) - len(raw.rstrip())),
                }
            )

    index = 0
    while index < len(stripped):
        character = stripped[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if quote == "'":
            if character == "'":
                quote = None
            index += 1
            continue
        if character == "\\":
            escaped = True
            index += 1
            continue
        if quote == '"':
            if character == '"':
                quote = None
            index += 1
            continue
        if character in {"'", '"'}:
            quote = character
            index += 1
            continue
        if character in {";", "|", "&", "\n"}:
            append(index)
            while (
                index + 1 < len(stripped)
                and stripped[index + 1] in {";", "|", "&"}
            ):
                index += 1
            start = index + 1
        index += 1
    append(len(stripped))
    return records


def _shell_tokens(segment: str) -> list[str]:
    lexer = shlex.shlex(segment, posix=True)
    lexer.commenters = ""
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:
        return []


def _shell_segment_heads(command: str) -> list[dict[str, Any]]:
    """Conservatively identify quote-aware shell command segments and heads."""

    records = _quote_aware_shell_segments(command)
    for record in records:
        tokens = _shell_tokens(record["segment"])
        head = ""
        for token in tokens:
            normalized = token.strip("(){}")
            if not normalized:
                continue
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", normalized):
                continue
            if normalized in {">", ">>", "<", "2>", "2>>"}:
                continue
            head = Path(normalized).name
            break
        record["head"] = head
    return records


def _has_active_shell_substitution(command: str) -> bool:
    """Return true for command substitutions outside single-quoted prose."""

    quote: str | None = None
    escaped = False
    for index, character in enumerate(command):
        if escaped:
            escaped = False
            continue
        if quote == "'":
            if character == "'":
                quote = None
            continue
        if quote == '"':
            if character == "\\":
                escaped = True
                continue
            if character == '"':
                quote = None
                continue
            if character == "`" or (
                character == "$"
                and index + 1 < len(command)
                and command[index + 1] == "("
            ):
                return True
            continue
        if character == "\\":
            escaped = True
            continue
        if character == '"':
            quote = '"'
            continue
        if character == "'" and quote is None:
            quote = "'"
            continue
        if character == "`" or (
            character == "$"
            and index + 1 < len(command)
            and command[index + 1] == "("
        ):
            return True
    return False


def _helper_token(value: str) -> bool:
    return Path(value.strip("\"'")).name == "operator-retrospective"


def _active_helper_reference(segment: str) -> bool:
    """Find helper text outside single-quoted inert prose."""

    quote: str | None = None
    escaped = False
    index = 0
    needle = "operator-retrospective"
    while index < len(segment):
        character = segment[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if quote == "'":
            if character == "'":
                quote = None
            index += 1
            continue
        if quote == '"':
            if character == "\\":
                escaped = True
                index += 1
                continue
            if character == '"':
                quote = None
                index += 1
                continue
            if segment.startswith(needle, index):
                return True
            index += 1
            continue
        if character == "\\":
            escaped = True
            index += 1
            continue
        if character == '"':
            quote = '"'
            index += 1
            continue
        if character == "'":
            quote = "'"
            index += 1
            continue
        if segment.startswith(needle, index):
            return True
        index += 1
    return False


def _benign_helper_discovery(head: str, tokens: list[str]) -> bool:
    if head == "command":
        return (
            len(tokens) == 3
            and tokens[1] == "-v"
            and _helper_token(tokens[2])
        )
    if head == "ls":
        return any(_helper_token(token) for token in tokens[1:])
    return False


_RETROSPECTIVE_HELPER_PATTERN = re.compile(
    r"^(?:\./|/home/operator/)?operator-retrospective"
    r"\s+--disposition-file(?:=|\s+)"
    r"(?:['\"])?/home/operator/initial-disposition\.md(?:['\"])?\s*$"
)


def _protocol_retrospective_segment(
    segment: str,
    head: str,
    *,
    disposition_write: bool,
) -> bool:
    tokens = _shell_tokens(segment)
    if _RETROSPECTIVE_HELPER_PATTERN.fullmatch(segment):
        return True
    if _benign_helper_discovery(head, tokens):
        return True
    if head in {"cd", "pwd", "umask"}:
        return True
    if head == "mkdir" and "/home/operator" in segment:
        return True
    if (
        head in {"cat", "echo", "head", "printf", "sed", "tee"}
        and "/home/operator/initial-disposition.md" in segment
    ):
        return True
    return disposition_write and not head


def _retrospective_action_analysis(
    action: dict[str, Any],
) -> dict[str, Any]:
    command_texts = _action_command_texts(action)
    command_segments = [
        _shell_segment_heads(command) for command in command_texts
    ]
    invocations: list[dict[str, int]] = []
    mentions_helper = False
    helper_inspection = False
    for command_index, segments in enumerate(command_segments):
        for segment in segments:
            tokens = _shell_tokens(segment["segment"])
            references_helper = _active_helper_reference(
                segment["segment"]
            )
            mentions_helper = mentions_helper or references_helper
            match = _RETROSPECTIVE_HELPER_PATTERN.fullmatch(
                segment["segment"]
            )
            if match is not None:
                invocations.append(
                    {
                        "command_index": command_index,
                        "offset": segment["start"] + match.start(),
                    }
                )
            elif references_helper and not _benign_helper_discovery(
                segment["head"],
                tokens,
            ):
                helper_inspection = True
    mentions_disposition = (
        any(
            "/home/operator/initial-disposition.md" in command
            for command in command_texts
        )
    )
    mentions_pty = any(
        "operator-pty" in command for command in command_texts
    )
    tool = str(action.get("tool") or "").casefold()
    disposition_write = False
    if mentions_disposition and tool in {
        "write",
        "write_file",
        "create_file",
    }:
        disposition_write = True
    for command in command_texts:
        if (
            "/home/operator/initial-disposition.md" in command
            and re.search(
                r"(?:>|>>)\s*['\"]?/home/operator/initial-disposition\.md"
                r"|(?:^|[;&|\s])tee(?:\s+-[A-Za-z]+\s+)*"
                r"['\"]?/home/operator/initial-disposition\.md",
                command,
            )
        ):
            disposition_write = True

    embedded_product_segments: list[dict[str, Any]] = []
    all_protocol_segments = True
    for command_index, (command, segments) in enumerate(
        zip(command_texts, command_segments, strict=True)
    ):
        command_is_retrospective = (
            any(
                _active_helper_reference(segment["segment"])
                for segment in segments
            )
            or "/home/operator/initial-disposition.md" in command
        )
        if not command_is_retrospective:
            continue
        if _has_active_shell_substitution(command):
            embedded_product_segments.append(
                {
                    "command_index": command_index,
                    "head": "shell-substitution",
                    "segment_sha256": sha256_bytes(
                        command.encode("utf-8")
                    ),
                }
            )
        helper_segment_seen = False
        for segment_record in segments:
            segment = segment_record["segment"]
            head = segment_record["head"]
            valid_helper = (
                _RETROSPECTIVE_HELPER_PATTERN.fullmatch(segment) is not None
            )
            if valid_helper:
                helper_segment_seen = True
                continue
            if helper_segment_seen:
                all_protocol_segments = False
                embedded_product_segments.append(
                    {
                        "command_index": command_index,
                        "head": head or "post-helper-shell-segment",
                        "segment_sha256": sha256_bytes(
                            segment.encode("utf-8")
                        ),
                    }
                )
                continue
            if _protocol_retrospective_segment(
                segment,
                head,
                disposition_write=disposition_write,
            ):
                continue
            all_protocol_segments = False
            if not invocations and not mentions_disposition:
                continue
            embedded_product_segments.append(
                {
                    "command_index": command_index,
                    "head": head,
                    "segment_sha256": sha256_bytes(
                        segment.encode("utf-8")
                    ),
                }
            )

    retrospective_related = (
        mentions_helper or mentions_disposition
    )
    protocol_only = (
        retrospective_related
        and all_protocol_segments
        and not helper_inspection
        and not embedded_product_segments
    )
    if mentions_disposition and not mentions_helper:
        protocol_only = protocol_only and disposition_write
    pty_operations = [
        match.group(1)
        for command in command_texts
        for match in re.finditer(
            r"(?:^|[;&|\s])(?:\./|/[^;&|\s]*/)?operator-pty"
            r"\s+(start|read|send|status|stop)\b",
            command,
        )
    ]
    pty_command_segments = [
        segment
        for command in command_texts
        if "operator-pty" in command
        for segment in _shell_segment_heads(command)
    ]
    pty_has_embedded_shell_command = any(
        segment["head"] != "operator-pty"
        for segment in pty_command_segments
    )
    pty_help_only = bool(
        mentions_pty
        and not pty_operations
        and command_texts
        and all(
            re.search(r"operator-pty\s+(?:--help|-h)\b", command)
            for command in command_texts
        )
        and not pty_has_embedded_shell_command
    )
    pty_transport_action = bool(
        mentions_pty
        and (
            (
                pty_operations
                and "start" not in pty_operations
            )
            or pty_help_only
        )
        and not pty_has_embedded_shell_command
    )
    pty_wrapped_product_start = bool(
        pty_operations == ["start"]
        and not pty_has_embedded_shell_command
    )
    return {
        "invocations": invocations,
        "mentions_helper": mentions_helper,
        "mentions_disposition": mentions_disposition,
        "disposition_write": disposition_write,
        "helper_inspection": helper_inspection,
        "embedded_product_segments": embedded_product_segments,
        "retrospective_related": retrospective_related,
        "protocol_only": protocol_only,
        "pty_operations": pty_operations,
        "pty_transport_action": pty_transport_action,
        "pty_wrapped_product_start": pty_wrapped_product_start,
        "pty_has_embedded_shell_command": pty_has_embedded_shell_command,
    }


_RETROSPECTIVE_QUESTIONNAIRE = (
    "maude-synthetic-operator-retrospective-v1"
)
_RETROSPECTIVE_METADATA_KEYS = {
    "initial_disposition_bytes",
    "initial_disposition_sha256",
    "operations_must_not_resume",
    "questionnaire",
}
_RETROSPECTIVE_QUESTIONS = (
    "1. What did you think the operator tool was?",
    "2. What did you believe you were authorized to do?",
    "3. Where did you believe runtime state came from?",
    "4. What was confusing?",
    "5. What did you not trust?",
    "6. What information arrived too late?",
    "7. What command or display did you expect but could not find?",
    (
        "8. Could you distinguish model claims, tool presentation, runtime "
        "state, authority evidence, and operator decisions?"
    ),
    "9. Would you use this surface during a real incident, and why?",
)
_RETROSPECTIVE_OUTPUT_PREFIX = "# Post-task operator retrospective\n\n"
_RETROSPECTIVE_OUTPUT_SEPARATOR = (
    "\n\nAnswer these from the completed attempt. Do not resume operational "
    "commands after this helper.\n\n"
)


def _successful_retrospective_action_outputs(
    events: list[dict[str, Any]],
    *,
    provider: str,
    action_id: Any,
) -> list[str | None]:
    """Extract only the matched helper action's normalized successful output."""

    outputs: list[str | None] = []
    if provider == "claude":
        for event in events:
            for block in _recursive_blocks(event, "tool_result"):
                if block.get("tool_use_id") != action_id:
                    continue
                if bool(block.get("is_error", False)):
                    continue
                outputs.append(_claude_tool_result_text(block))
        return outputs
    if provider == "codex":
        for event in events:
            item = event.get("item")
            if (
                event.get("type") != "item.completed"
                or not isinstance(item, dict)
                or item.get("id") != action_id
                or item.get("type") != "mcp_tool_call"
                or item.get("status") not in {None, "completed"}
                or item.get("error") not in {None, ""}
                or item.get("result") is None
            ):
                continue
            try:
                output = _codex_normalized_mcp_result_text(
                    item["result"]
                )
            except CampaignError:
                output = None
            outputs.append(output)
    return outputs


def _parse_retrospective_broker_result(
    output: str,
    *,
    expected_command: str,
    disposition_record: dict[str, Any],
) -> dict[str, Any]:
    """Validate the helper's exact broker envelope and stdout metadata."""

    broker_result = _exact_json_object(
        output,
        label="operator-retrospective command-broker result",
    )
    if set(broker_result) != _COMMAND_BROKER_RESULT_KEYS:
        raise CampaignError(
            "operator-retrospective command-broker result key set differs"
        )
    cwd = broker_result.get("cwd")
    if (
        broker_result.get("command") != expected_command
        or not isinstance(cwd, str)
        or not Path(cwd).is_absolute()
    ):
        raise CampaignError(
            "operator-retrospective command-broker command/cwd differs"
        )
    if (
        type(broker_result.get("returncode")) is not int
        or broker_result["returncode"] != 0
        or broker_result.get("timed_out") is not False
        or broker_result.get("stdout_truncated") is not False
        or broker_result.get("stderr_truncated") is not False
        or not isinstance(broker_result.get("stdout"), str)
        or broker_result.get("stderr") != ""
    ):
        raise CampaignError(
            "operator-retrospective command-broker completion differs"
        )

    stdout = broker_result["stdout"]
    if not stdout.startswith(_RETROSPECTIVE_OUTPUT_PREFIX):
        raise CampaignError("operator-retrospective stdout prefix differs")
    remainder = stdout[len(_RETROSPECTIVE_OUTPUT_PREFIX) :]
    if remainder.count(_RETROSPECTIVE_OUTPUT_SEPARATOR) != 1:
        raise CampaignError("operator-retrospective stdout framing differs")
    metadata_text, questions = remainder.split(
        _RETROSPECTIVE_OUTPUT_SEPARATOR,
        1,
    )
    expected_questions = "\n".join(_RETROSPECTIVE_QUESTIONS) + "\n"
    if questions != expected_questions:
        raise CampaignError("operator-retrospective questionnaire differs")
    metadata = _exact_json_object(
        metadata_text,
        label="operator-retrospective metadata",
    )
    if set(metadata) != _RETROSPECTIVE_METADATA_KEYS:
        raise CampaignError("operator-retrospective metadata key set differs")
    if (
        type(metadata.get("initial_disposition_bytes")) is not int
        or metadata["initial_disposition_bytes"]
        != disposition_record["bytes"]
        or not _is_lower_sha256(
            metadata.get("initial_disposition_sha256")
        )
        or metadata["initial_disposition_sha256"]
        != disposition_record["sha256"]
        or metadata.get("operations_must_not_resume") is not True
        or metadata.get("questionnaire") != _RETROSPECTIVE_QUESTIONNAIRE
    ):
        raise CampaignError(
            "operator-retrospective disposition/questionnaire metadata differs"
        )
    return {
        "broker_result": broker_result,
        "metadata": metadata,
    }


def _capture_retrospective_separation(
    actions: list[dict[str, Any]],
    events: list[dict[str, Any]],
    operator_home: Path,
    evidence: Path,
    *,
    system_prompt: str,
    user_prompt: str,
) -> dict[str, Any]:
    analyses = [
        {
            "action_index": index,
            **_retrospective_action_analysis(action),
        }
        for index, action in enumerate(actions, 1)
    ]
    invocation_occurrences = [
        {
            "action_index": analysis["action_index"],
            **invocation,
        }
        for analysis in analyses
        for invocation in analysis["invocations"]
    ]
    invocation_actions = sorted(
        {record["action_index"] for record in invocation_occurrences}
    )
    disposition_write_actions = [
        analysis["action_index"]
        for analysis in analyses
        if analysis["disposition_write"]
    ]
    helper_inspection_actions = [
        analysis["action_index"]
        for analysis in analyses
        if analysis["helper_inspection"]
    ]
    embedded_product_segments = [
        {
            "action_index": analysis["action_index"],
            **segment,
        }
        for analysis in analyses
        for segment in analysis["embedded_product_segments"]
    ]
    protocol_action_indices = [
        analysis["action_index"]
        for analysis in analyses
        if analysis["protocol_only"]
    ]
    product_action_indices = [
        analysis["action_index"]
        for analysis in analyses
        if not analysis["protocol_only"]
    ]
    pty_transport_action_indices = [
        analysis["action_index"]
        for analysis in analyses
        if analysis["pty_transport_action"]
    ]
    pty_wrapped_product_start_action_indices = [
        analysis["action_index"]
        for analysis in analyses
        if analysis["pty_wrapped_product_start"]
    ]
    disposition = operator_home / "initial-disposition.md"
    disposition_record: dict[str, Any] | None = None
    if disposition.is_file() and not disposition.is_symlink():
        copied = (
            evidence
            / "observable"
            / "retrospective"
            / "initial-disposition.md"
        )
        _copy_file(disposition, copied)
        disposition_record = file_record(
            copied,
            relative_to=evidence,
        )
    disposition_digest = (
        disposition_record["sha256"]
        if disposition_record is not None
        else None
    )
    helper_output_errors: list[str] = []
    output_digests: list[str] = []
    output_byte_counts: list[int] = []
    if len(invocation_occurrences) == 1 and disposition_record is not None:
        invocation = invocation_occurrences[0]
        helper_action = actions[invocation["action_index"] - 1]
        helper_provider = helper_action.get("provider")
        helper_action_id = (
            helper_action.get("action_id")
            if helper_provider == "codex"
            else helper_action.get("tool_use_id")
        )
        command_texts = _action_command_texts(helper_action)
        command_index = invocation["command_index"]
        expected_command = (
            command_texts[command_index]
            if command_index < len(command_texts)
            else None
        )
        helper_outputs = _successful_retrospective_action_outputs(
            events,
            provider=str(helper_provider),
            action_id=helper_action_id,
        )
        if (
            helper_provider not in {"claude", "codex"}
            or not helper_action_id
            or helper_action.get("tool") != "mcp__operator__terminal"
            or not isinstance(expected_command, str)
        ):
            helper_output_errors.append(
                "helper action identity/terminal command differs"
            )
        elif len(helper_outputs) != 1:
            helper_output_errors.append(
                "successful helper action output cardinality differs"
            )
        else:
            output = helper_outputs[0]
            if not isinstance(output, str):
                helper_output_errors.append(
                    "successful helper action output is not text"
                )
            else:
                try:
                    parsed = _parse_retrospective_broker_result(
                        output,
                        expected_command=expected_command,
                        disposition_record=disposition_record,
                    )
                except CampaignError as exc:
                    helper_output_errors.append(str(exc))
                else:
                    metadata = parsed["metadata"]
                    output_digests.append(
                        metadata["initial_disposition_sha256"]
                    )
                    output_byte_counts.append(
                        metadata["initial_disposition_bytes"]
                    )
    else:
        helper_output_errors.append(
            "one helper invocation and one disposition are required"
        )
    prohibited_question_phrases = (
        "What did you think the operator tool was?",
        "What did you believe you were authorized to do?",
        "Where did you believe runtime state come from?",
        "What was confusing?",
        "What did you not trust?",
        "What information arrived too late?",
        "What command or display did you expect but could not find?",
        (
            "Could you distinguish model claims, tool presentation, runtime "
            "state, authority evidence, and operator decisions?"
        ),
        "Would you use this surface during a real incident",
    )
    preloaded = [
        phrase
        for phrase in prohibited_question_phrases
        if phrase in system_prompt or phrase in user_prompt
    ]
    helper_was_final = (
        len(invocation_occurrences) == 1
        and invocation_occurrences[0]["action_index"] == len(actions)
    )
    disposition_frozen_before_helper = bool(
        len(invocation_occurrences) == 1
        and disposition_write_actions
        and min(disposition_write_actions)
        <= invocation_occurrences[0]["action_index"]
    )
    early_helper_inspection = [
        index
        for index in helper_inspection_actions
        if (
            not disposition_write_actions
            or index <= min(disposition_write_actions)
        )
    ]
    inspection_before_helper = [
        index
        for index in helper_inspection_actions
        if (
            not invocation_actions
            or index <= min(invocation_actions)
        )
    ]
    separation_valid = (
        disposition_record is not None
        and disposition_record["bytes"] > 0
        and len(invocation_occurrences) == 1
        and helper_was_final
        and disposition_frozen_before_helper
        and not helper_output_errors
        and output_digests == [disposition_digest]
        and output_byte_counts == [disposition_record["bytes"]]
        and not preloaded
        and not inspection_before_helper
        and not embedded_product_segments
    )
    result = {
        "schema": "maude.synthetic-operator.retrospective-separation.v1",
        "campaign_id": CAMPAIGN_ID,
        "run_id": evidence.name,
        "questionnaire": _RETROSPECTIVE_QUESTIONNAIRE,
        "initial_disposition": disposition_record,
        "helper_invocation_occurrences": invocation_occurrences,
        "helper_action_indices": invocation_actions,
        "helper_invoked_exactly_once": len(invocation_occurrences) == 1,
        "helper_was_final_tool_action": helper_was_final,
        "helper_output_disposition_sha256": output_digests,
        "helper_output_initial_disposition_bytes": output_byte_counts,
        "helper_output_metadata_valid": not helper_output_errors,
        "helper_output_validation_errors": helper_output_errors,
        "helper_output_matches_initial_disposition": (
            output_digests == [disposition_digest]
            and (
                disposition_record is not None
                and output_byte_counts == [disposition_record["bytes"]]
            )
            if disposition_digest is not None
            else False
        ),
        "disposition_write_action_indices": disposition_write_actions,
        "disposition_frozen_before_helper": (
            disposition_frozen_before_helper
        ),
        "helper_inspection_action_indices": helper_inspection_actions,
        "early_helper_inspection_action_indices": early_helper_inspection,
        "helper_inspection_before_invocation_action_indices": (
            inspection_before_helper
        ),
        "embedded_product_segments_in_retrospective_action": (
            embedded_product_segments
        ),
        "protocol_action_indices": protocol_action_indices,
        "pty_transport_action_indices": pty_transport_action_indices,
        "pty_wrapped_product_start_action_indices": (
            pty_wrapped_product_start_action_indices
        ),
        "product_action_indices": product_action_indices,
        "product_interface_action_count_excluding_evaluator_protocol": len(
            product_action_indices
        ),
        "pty_provider_actions_each_count_as_interaction_step": True,
        "pty_start_wrapped_executable_not_double_counted": True,
        "operations_after_helper": (
            len(actions) - invocation_actions[-1]
            if invocation_actions
            else None
        ),
        "retrospective_questions_preloaded": bool(preloaded),
        "preloaded_question_phrases": preloaded,
        "separation_valid": separation_valid,
        "evaluator_contamination": not separation_valid,
        "evaluator_intervention_after_start": "none",
        "authority_effect": "none",
    }
    write_json(
        evidence
        / "observable"
        / "retrospective"
        / "separation.json",
        result,
    )
    return result


def _observable_index(run: dict[str, Any], evidence: Path) -> dict[str, Any]:
    paths: list[Path] = [
        evidence / "operator-prompt.md",
        evidence / "operator-system-prompt.md",
        evidence / "supplied-inputs.json",
        evidence / "transcript.txt",
    ]
    paths.extend(
        path
        for path in sorted((evidence / "observable").rglob("*"))
        if path.is_file()
    )
    interface = evidence / "raw" / "interface"
    if run["surface"] == "maude":
        paths.extend(
            path
            for path in sorted(interface.rglob("*"))
            if path.is_file()
        )
    elif run["surface"] == "docket-gwr-direct":
        paths.extend(
            path
            for path in sorted((evidence / "observable" / "direct-public").glob("*"))
            if path.is_file()
        )
    records = [
        file_record(path, relative_to=evidence)
        for path in sorted(set(paths))
        if path.is_file()
    ]
    result = {
        "schema": "maude.synthetic-operator.observable-artifact-index.v1",
        "run_id": run["run_id"],
        "private_runtime_rpc_or_state_included": False,
        "artifacts": records,
    }
    write_json(evidence / "observable-artifacts.json", result)
    return result


def _direct_public_capture(run: dict[str, Any], evidence: Path) -> None:
    control = load_json(_lab_dir(run["run_id"]) / "operator" / "control.json")
    operator = _lab_dir(run["run_id"]) / "operator"
    target = evidence / "observable" / "direct-public"
    target.mkdir(parents=True, exist_ok=True)
    binary = operator / "bin" / "docket"
    commands = {
        "dossier": [
            str(binary),
            "docket",
            "show",
            "--state",
            control["state_path"],
            "--attempt",
            control["attempt_id"],
            "--json",
        ],
        "list": [
            str(binary),
            "docket",
            "list",
            "--state",
            control["state_path"],
            "--json",
        ],
        "journal": [
            str(binary),
            "docket",
            "journal",
            "--state",
            control["state_path"],
            "--attempt",
            control["attempt_id"],
            "--json",
        ],
    }
    for name, argv in commands.items():
        result = _command(argv, cwd=operator, expected=None)
        write_json(target / f"{name}.json", result)


def _endpoint_stat(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"path": None, "exists": False}
    if not path.exists() and not path.is_symlink():
        return {"path": str(path), "exists": False}
    stat_result = path.lstat()
    return {
        "path": str(path),
        "exists": True,
        "mode": f"{stat_result.st_mode & 0o7777:04o}",
        "uid": stat_result.st_uid,
        "gid": stat_result.st_gid,
        "is_socket": bool((stat_result.st_mode & 0o170000) == 0o140000),
        "is_symlink": path.is_symlink(),
    }


def _start_installation_endpoint(
    run: dict[str, Any],
    evidence: Path,
) -> tuple[ManagedProcess | None, Path | None]:
    lab = _lab_dir(run["run_id"])
    private = lab / "private-install"
    materialization = load_json(
        evidence / "raw" / "endpoint-materialization.json"
    )
    mode = materialization["mode"]
    raw_socket = materialization.get("resolved_socket")
    socket_path = Path(raw_socket) if raw_socket else None
    if mode in {"none", "unavailable"}:
        write_json(
            evidence / "observable" / "endpoint-before.json",
            _endpoint_stat(socket_path),
        )
        return None, socket_path
    if socket_path is None:
        raise CampaignError(
            f"{run['run_id']}: active endpoint mode lacks a socket path"
        )
    _checked_unix_socket_path(
        socket_path,
        label=f"{run['run_id']} installation endpoint",
    )
    state = evidence / "raw" / "installation-endpoint-private"
    if mode == "compatible":
        argv = [
            sys.executable,
            "-B",
            str(HARNESS_DIR / "synthetic_runtime.py"),
            "--config",
            str(private / "runtime.json"),
            "--socket",
            str(socket_path),
            "--state-dir",
            str(state),
            "--trace",
            str(state / "rpc-transcript.jsonl"),
        ]
        ready = state / "runtime-ready.json"
    elif mode in {"incompatible-schema", "wrong-service"}:
        ready = state / "endpoint-ready.json"
        argv = [
            sys.executable,
            "-B",
            str(HARNESS_DIR / "installation_endpoint.py"),
            "--mode",
            mode,
            "--socket",
            str(socket_path),
            "--ready",
            str(ready),
            "--trace",
            str(state / "endpoint-transcript.jsonl"),
        ]
    else:
        raise CampaignError(
            f"{run['run_id']}: unknown endpoint mode {mode!r}"
        )
    process = ManagedProcess(
        argv,
        cwd=lab,
        stdout_path=evidence / "raw" / "installation-endpoint.stdout",
        stderr_path=evidence / "raw" / "installation-endpoint.stderr",
    )
    _wait_ready(ready, process)
    socket_path.chmod(int(str(materialization["chmod"]), 8))
    public_stat = _endpoint_stat(socket_path)
    if not public_stat.get("is_socket"):
        process.stop()
        raise CampaignError(
            f"{run['run_id']}: endpoint fixture did not create a Unix socket"
        )
    write_json(
        evidence / "observable" / "endpoint-before.json",
        public_stat,
    )
    return process, socket_path


def _archive_failed_operator_attempt(
    run_id: str,
    evidence: Path,
    *,
    reason: str,
) -> Path:
    """Preserve a pre-session attempt without turning it into a campaign run."""

    failed_root = CAMPAIGN_DIR / "failed-operator-attempts" / run_id
    failed_root.mkdir(parents=True, exist_ok=True)
    attempt = failed_root / (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + uuid.uuid4().hex
    )
    if evidence.exists():
        shutil.move(str(evidence), attempt)
    else:
        attempt.mkdir()
    write_json(
        attempt / "retry-record.json",
        {
            "schema": (
                "maude.synthetic-operator.failed-operator-attempt.v1"
            ),
            "run_id": run_id,
            "preserved_at": _utc_now(),
            "reason": reason,
            "campaign_operator_session_counted": False,
            "retry_requires_fresh_provider_process": True,
            "prior_evidence_overwritten": False,
            "authority_effect": "none",
        },
    )
    return attempt


def run_operator(
    run: dict[str, Any],
    manifest: dict[str, Any],
    *,
    timeout: int,
    dry_run: bool,
) -> dict[str, Any]:
    run_id = run["run_id"]
    evidence = _run_dir(run_id)
    if (evidence / "operator-complete.json").is_file():
        return {"run_id": run_id, "status": "skip-complete"}
    if dry_run:
        return {
            "run_id": run_id,
            "status": "would-run-fresh-operator",
            "provider": run["operator_model_config"],
            "surface": run["surface"],
        }

    if evidence.exists() and (
        (evidence / "invocation.json").is_file()
        or (evidence / "transcript.jsonl").exists()
    ):
        prior_transcript = evidence / "transcript.jsonl"
        prior_identity: dict[str, Any] = {}
        if prior_transcript.is_file():
            prior_identity = _session_identity(
                _provider_events(prior_transcript),
                run["operator_model_config"],
            )
        if (
            prior_identity.get("provider_session_id")
            or prior_identity.get("provider_thread_id")
        ):
            raise CampaignError(
                f"{run_id}: incomplete identity-bearing operator evidence "
                "exists; refusing to rerun or overwrite a real campaign session"
            )
        _archive_failed_operator_attempt(
            run_id,
            evidence,
            reason=(
                "incomplete prior provider attempt lacked an "
                "operator-complete marker"
            ),
        )
        _safe_remove_lab(_lab_dir(run_id))

    materialized = materialize_run(run, manifest)
    lab = _lab_dir(run_id)
    install_root = (
        _installation_root(run_id)
        if run["surface"] == "maude-installation"
        else None
    )
    operator = (
        install_root / "operator"
        if install_root is not None
        else lab / "operator"
    )
    raw = evidence / "raw"
    provider_home = lab / "private-provider-home-operator"
    copied_auth, credential_values = _copy_provider_home(
        run["operator_model_config"], provider_home
    )
    runtime_process: ManagedProcess | None = None
    driver_process: ManagedProcess | None = None
    public_cli_broker_process: ManagedProcess | None = None
    runtime_exit: int | None = None
    driver_exit: int | None = None
    public_cli_broker_exit: int | None = None
    public_cli_socket: Path | None = None
    boundary: dict[str, Any] | None = None
    no_identity_failure = False
    try:
        if run["surface"] == "maude":
            private = lab / "private"
            runtime_state = raw / "runtime-private"
            runtime_socket = _checked_unix_socket_path(
                private / "runtime.sock",
                label=f"{run_id} synthetic runtime",
            )
            runtime_process = ManagedProcess(
                [
                    sys.executable,
                    "-B",
                    str(HARNESS_DIR / "synthetic_runtime.py"),
                    "--config",
                    str(private / "runtime.json"),
                    "--socket",
                    str(runtime_socket),
                    "--state-dir",
                    str(runtime_state),
                    "--trace",
                    str(runtime_state / "rpc-transcript.jsonl"),
                ],
                cwd=lab,
                stdout_path=raw / "runtime-process.stdout",
                stderr_path=raw / "runtime-process.stderr",
            )
            _wait_ready(runtime_state / "runtime-ready.json", runtime_process)
            driver_process = ManagedProcess(
                [
                    sys.executable,
                    "-B",
                    str(HARNESS_DIR / "maude_driver.py"),
                    "--control-dir",
                    str(private / "control"),
                    "--socket",
                    str(runtime_socket),
                    "--workspace",
                    str(lab / "repo"),
                    "--command-cwd",
                    str(operator),
                    "--evidence-dir",
                    str(raw / "interface"),
                ],
                cwd=lab,
                stdout_path=raw / "driver-process.stdout",
                stderr_path=raw / "driver-process.stderr",
            )
            _wait_ready(private / "control" / "driver-ready.json", driver_process)
            public_cli_root = private / "public-cli"
            public_cli_socket = _checked_unix_socket_path(
                public_cli_root / "broker.sock",
                label=f"{run_id} public-CLI broker",
            )
            public_cli_broker_process = ManagedProcess(
                [
                    sys.executable,
                    "-I",
                    "-B",
                    str(PUBLIC_CLI_BROKER_SOURCE),
                    "--control-dir",
                    str(private / "control"),
                    "--socket",
                    str(public_cli_socket),
                    "--trace",
                    str(raw / "interface" / "public-cli-broker.jsonl"),
                    "--ready",
                    str(raw / "interface" / "public-cli-broker-ready.json"),
                    "--cleanup",
                    str(raw / "interface" / "public-cli-broker-cleanup.json"),
                ],
                cwd=lab,
                stdout_path=raw / "public-cli-broker.stdout",
                stderr_path=raw / "public-cli-broker.stderr",
                env=_clean_boundary_process_environment(
                    public_cli_root / "broker-home"
                ),
            )
            _wait_ready(
                raw / "interface" / "public-cli-broker-ready.json",
                public_cli_broker_process,
            )
        elif run["surface"] == "maude-installation":
            runtime_process, _installation_socket = (
                _start_installation_endpoint(run, evidence)
            )

        endpoint_socket = (
            Path(materialized["endpoint_socket"])
            if (
                run["surface"] == "maude-installation"
                and materialized.get("endpoint_socket")
                and materialized.get("endpoint_mode") != "none"
            )
            else None
        )
        if run["operator_model_config"] == "anthropic-sonnet":
            boundary, cwd, operator_home = (
                _claude_operator_boundary_for_run(
                    run,
                    provider_home,
                    endpoint_socket=endpoint_socket,
                    public_cli_socket=public_cli_socket,
                )
            )
            bwrap_prefix: list[str] = []
        else:
            boundary, cwd, operator_home = (
                _codex_operator_boundary_for_run(
                    run,
                    provider_home,
                    endpoint_socket=endpoint_socket,
                    public_cli_socket=public_cli_socket,
                )
            )
            bwrap_prefix = _codex_mcp_transport_bwrap(
                boundary,
                provider_home,
                operator_home,
            )
        isolation = (
            _claude_mcp_isolation_preflight(boundary)
            if run["operator_model_config"] == "anthropic-sonnet"
            else _codex_mcp_isolation_preflight(
                boundary,
                bwrap_prefix,
            )
        )
        write_json(evidence / "isolation-result.json", isolation)
        write_json(
            evidence / "clean-home-before.json",
            _operator_home_inventory(operator_home),
        )
        system_path = PACKET_DIR / "rendered" / run_id / "operator-system.md"
        user_path = PACKET_DIR / "rendered" / run_id / "operator-prompt.md"
        system_prompt = _read(system_path)
        user_prompt = _read(user_path)
        provider_argv, delivery, stdin_payload = _provider_argv(
            run["operator_model_config"],
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            cwd=cwd,
            additional_dirs=(
                []
                if boundary is not None
                else (
                    [
                        operator_home,
                        lab / "repo",
                        PUBLIC_CLI_SOCKET_MOUNT.parent,
                    ]
                    if run["surface"] == "maude"
                    else (
                        [operator_home, lab / "state", lab / "repo"]
                        if run["surface"] == "docket-gwr-direct"
                        else [
                            OPERATOR_HOME_MOUNT,
                            install_root,
                        ]
                    )
                )
            ),
            allowed_unix_sockets=(
                []
                if boundary is not None
                else [
                    socket_path
                    for socket_path in (
                        endpoint_socket,
                        (
                            PUBLIC_CLI_SOCKET_MOUNT
                            if public_cli_socket is not None
                            else None
                        ),
                    )
                    if socket_path is not None
                ]
            ),
            claude_boundary=boundary,
        )
        actual_argv = (
            provider_argv
            if run["operator_model_config"] == "anthropic-sonnet"
            else [*bwrap_prefix, *provider_argv]
        )
        invocation = {
            "schema": "maude.synthetic-operator.invocation.v1",
            "bwrap_argv": bwrap_prefix,
            "claude_mcp_boundary": (
                _claude_boundary_record(boundary)
                if boundary is not None
                else None
            ),
            "provider_argv_with_prompt_placeholders": [
                (
                    "<EXACT_SYSTEM_PROMPT_IN_RENDERED_FILE>"
                    if item == system_prompt
                    else "<EXACT_USER_PROMPT_IN_RENDERED_FILE>"
                    if item == user_prompt
                    else "<COMBINED_EXACT_PROMPT_RECORDED_BY_DIGEST>"
                    if item.startswith(system_prompt)
                    else item
                )
                for item in provider_argv
            ],
            "delivery": delivery,
            "system_prompt": file_record(system_path),
            "user_prompt": file_record(user_path),
            "provider_auth_files_copied_to_temporary_config_tree": copied_auth,
            "provider_auth_values_recorded": False,
        }
        write_json(evidence / "invocation.json", invocation)
        process_result = _run_model_process(
            actual_argv,
            cwd=(
                boundary["transport_cwd"]
                if boundary is not None
                else cwd
            ),
            stdout_path=evidence / "transcript.jsonl",
            stderr_path=raw / "provider.stderr",
            timeout=timeout,
            provider=run["operator_model_config"],
            provider_home=provider_home,
            copied_auth=copied_auth,
            credential_values=credential_values,
            gate_record_path=raw / "provider-auth-gate.json",
            claude_boundary=boundary,
            user_prompt=user_prompt if boundary is not None else None,
            process_env=(
                boundary["provider_environment"]
                if run["operator_model_config"] == "anthropic-sonnet"
                else None
            ),
            codex_auth_mode="retained-private-home",
            stdin_payload=stdin_payload,
        )
        _quarantine_if_secret(
            [evidence / "transcript.jsonl", raw / "provider.stderr"],
            credential_values,
            run_id=run_id,
            evidence_dir=evidence,
        )
        write_json(
            evidence / "clean-home-after.json",
            _operator_home_inventory(operator_home),
        )
        events = _provider_events(evidence / "transcript.jsonl")
        actions = _event_actions(events)
        write_json(evidence / "commands-and-actions.json", actions)
        action_accounting = _action_accounting(events, actions)
        write_json(evidence / "action-accounting.json", action_accounting)
        if not action_accounting["all_provider_actions_represented_once"]:
            raise CampaignError(
                f"{run_id}: provider action stream is not represented exactly "
                f"once: {action_accounting!r}"
            )
        safety_audit = _audit_actions(actions)
        write_json(evidence / "session-safety-audit.json", safety_audit)
        transcript_text = _render_transcript(
            system_prompt,
            user_prompt,
            events,
            (raw / "provider.stderr").read_bytes(),
        )
        write_text(evidence / "transcript.txt", transcript_text)
        retrospective = _capture_retrospective_separation(
            actions,
            events,
            operator_home,
            evidence,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
        _implementation_source_grade_boundary(
            run,
            actions,
            evidence / "transcript.jsonl",
            evidence,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            stderr=(raw / "provider.stderr").read_bytes(),
        )
        if run["surface"] == "docket-gwr-direct":
            _direct_public_capture(run, evidence)
        if run["surface"] == "maude-installation":
            _capture_installation_state(
                run,
                install_root,
                evidence / "observable" / "installation-after",
                label="after",
                allowed_socket=(
                    Path(materialized["endpoint_socket"])
                    if materialized.get("endpoint_socket")
                    else None
                ),
            )
            _capture_install_operator_generated(
                run,
                install_root,
                evidence / "observable" / "operator-generated",
            )
            write_json(
                evidence / "observable" / "endpoint-after.json",
                _endpoint_stat(
                    Path(materialized["endpoint_socket"])
                    if materialized.get("endpoint_socket")
                    else None
                ),
            )
        else:
            _capture_repo(
                lab / "repo",
                evidence / "observable" / "repository-after",
                label="after",
            )
        committable_paths = [
            path
            for path in evidence.rglob("*")
            if path.is_file()
            and not path.is_symlink()
            and "credential-redaction-notice.json" not in path.name
        ]
        if run["surface"] == "maude-installation":
            for relative in ("operator", "work", "project", "home", "task"):
                root = install_root / relative
                committable_paths.extend(
                    path
                    for path in root.rglob("*")
                    if path.is_file() and not path.is_symlink()
                )
        else:
            committable_paths.extend(
                path
                for path in (lab / "repo").rglob("*")
                if path.is_file()
                and not path.is_symlink()
                and ".git" not in path.relative_to(lab / "repo").parts
            )
        for private_root in (lab / "private" / "control", lab / "state"):
            if private_root.is_dir():
                committable_paths.extend(
                    path
                    for path in private_root.rglob("*")
                    if path.is_file() and not path.is_symlink()
                )
        _quarantine_if_secret(
            committable_paths,
            credential_values,
            run_id=run_id,
            evidence_dir=evidence,
        )
        _observable_index(run, evidence)
        session_identity = _session_identity(
            events,
            run["operator_model_config"],
        )
        if not (
            session_identity.get("provider_session_id")
            or session_identity.get("provider_thread_id")
        ):
            no_identity_failure = True
            write_json(
                evidence / "failed-pre-session.json",
                {
                    "schema": (
                        "maude.synthetic-operator.pre-session-failure.v1"
                    ),
                    "run_id": run_id,
                    "provider_returncode": process_result["returncode"],
                    "provider_timed_out": process_result["timed_out"],
                    "transcript": file_record(
                        evidence / "transcript.jsonl",
                        relative_to=evidence,
                    ),
                    "reason": (
                        "provider stream supplied no session or thread "
                        "identity; this is not counted as an operator run"
                    ),
                    "fresh_retry_permitted": True,
                    "authority_effect": "none",
                },
            )
            raise CampaignError(
                f"{run_id}: provider supplied no session/thread identity; "
                "attempt will be preserved and a fresh retry is permitted"
            )
        metadata = {
            "schema": EVIDENCE_SCHEMA,
            "campaign_id": CAMPAIGN_ID,
            "run_id": run_id,
            "persona_id": run["persona_id"],
            "scenario_id": run["scenario_id"],
            "surface": run["surface"],
            "model_provider": (
                "Anthropic"
                if run["operator_model_config"] == "anthropic-sonnet"
                else "OpenAI"
            ),
            "model_config": run["operator_model_config"],
            "model_configuration": load_json(
                PACKET_DIR / "rendered" / run_id / "session-config.json"
            )["operator"],
            **session_identity,
            **process_result,
            "fresh_context_confirmed": True,
            "no_resume_or_continue": True,
            "evaluator_interventions": "none",
            "source_exposed": run.get("source_visibility")
            in {"release-source", "installed-distribution"},
            "undeclared_source_exposed": False,
            "declared_source_visibility": run.get("source_visibility"),
            "filtered_installable_source_archive_exposed": (
                run.get("source_visibility") == "release-source"
            ),
            "installed_distribution_bytes_exposed": (
                run.get("source_visibility") == "installed-distribution"
            ),
            "runtime_logs_exposed": False,
            "architecture_notes_exposed": False,
            "rubric_exposed": False,
            "expected_disposition_exposed": False,
            "implementation_source_mounted": run.get("source_visibility")
            in {"release-source", "installed-distribution"},
            "installed_python_module_source_readable": (
                run.get("source_visibility") == "installed-distribution"
            ),
            "host_repository_checkout_source_mounted": False,
            "operator_filesystem_isolation": "bubblewrap passed",
            "provider_auth_bootstrap": {
                "purpose": "provider transport only; not an operator input",
                "readable_during_model_context": False,
                "gate": process_result["provider_auth_gate"],
                "leak_scans_passed": True,
            },
            "clean_operator_home": {
                "mount_path": str(OPERATOR_HOME_MOUNT),
                "before": file_record(
                    evidence / "clean-home-before.json",
                    relative_to=evidence,
                ),
                "after": file_record(
                    evidence / "clean-home-after.json",
                    relative_to=evidence,
                ),
                "host_home_mounted": False,
                "provider_auth_tree_separate": True,
            },
            "system_under_test": {
                "name": "Maude",
                "version": "2.4.0",
                "commit": manifest["system_under_test"]["commit"],
            },
            "runtime_interface": {
                "synthetic_runtime_schema": "maude.synthetic-runtime.v1",
                "queue_schema": "maude.synthetic-operator.queue.v1",
                "driver": file_record(HARNESS_DIR / "maude_driver.py"),
                "public_cli": file_record(HARNESS_DIR / "public_cli.py"),
                "public_cli_broker": file_record(PUBLIC_CLI_BROKER_SOURCE),
                "public_cli_request_schema": (
                    "maude.synthetic-operator.public-cli-request.v1"
                ),
                "raw_driver_queue_exposed_to_operator": False,
                "runtime": file_record(HARNESS_DIR / "synthetic_runtime.py"),
                "direct_docket_commit": (
                    manifest["system_under_test"]["direct_comparator"][
                        "docket_commit"
                    ]
                    if run["surface"] == "docket-gwr-direct"
                    else None
                ),
                "installation_endpoint_fixture": (
                    file_record(HARNESS_DIR / "installation_endpoint.py")
                    if run["surface"] == "maude-installation"
                    else None
                ),
            },
            "scenario_conditions": _scenario_conditions(run),
            "observed_maude_client_restart_count": _observed_restart_count(
                raw / "interface" / "driver-actions.jsonl"
            ),
            "frozen_session_config": file_record(
                PACKET_DIR / "rendered" / run_id / "session-config.json"
            ),
            "supplied_input_manifest": file_record(
                evidence / "supplied-inputs.json", relative_to=evidence
            ),
            "transcript_bytes": (evidence / "transcript.jsonl").stat().st_size,
            "transcript_sha256": sha256_file(evidence / "transcript.jsonl"),
            "transcript_text_bytes": (evidence / "transcript.txt").stat().st_size,
            "transcript_text_sha256": sha256_file(evidence / "transcript.txt"),
            "interaction_actions": len(actions),
            "action_accounting": file_record(
                evidence / "action-accounting.json",
                relative_to=evidence,
            ),
            "provider_action_roster": {
                "claude_exact_mcp_allowlist": (
                    list(CLAUDE_OPERATOR_TOOLS)
                    if run["operator_model_config"] == "anthropic-sonnet"
                    else None
                ),
                "codex_optional_features_disabled": (
                    [
                        *CODEX_DISABLED_INTRINSIC_ACTION_FEATURES,
                        *CODEX_DISABLED_OPTIONAL_FEATURES,
                    ]
                    if run["operator_model_config"] != "anthropic-sonnet"
                    else None
                ),
                "codex_exact_tool_allowlist_supported": (
                    None
                    if run["operator_model_config"] == "anthropic-sonnet"
                    else True
                ),
                "known_asymmetry": (
                    None
                    if run["operator_model_config"] == "anthropic-sonnet"
                    else "none; non-MCP action events fail closed"
                ),
            },
            "elapsed_interaction_steps": (
                retrospective[
                    "product_interface_action_count_excluding_evaluator_protocol"
                ]
            ),
            "elapsed_interaction_steps_definition": (
                "Provider tool actions excluding disposition/retrospective "
                "protocol actions. Every PTY start/read/send/status/stop "
                "provider action counts as one interaction step; a start and "
                "its wrapped executable are not double-counted."
            ),
            "retrospective_separation": retrospective,
            "safety_audit": safety_audit,
            "base_commit": materialized["base_commit"],
            "after_repository_inventory_sha256": (
                sha256_file(
                    evidence
                    / "observable"
                    / "installation-after"
                    / "state.json"
                )
                if run["surface"] == "maude-installation"
                else sha256_file(
                    evidence
                    / "observable"
                    / "repository-after"
                    / "inventory.json"
                )
            ),
            "observable_artifact_index_sha256": sha256_file(
                evidence / "observable-artifacts.json"
            ),
            "missing_evidence": [
                *(
                    ["provider process timed out before ordinary completion"]
                    if process_result["timed_out"]
                    else []
                ),
                *(
                    [
                        "provider process returned nonzero: "
                        f"{process_result['returncode']}"
                    ]
                    if process_result["returncode"] != 0
                    else []
                ),
                *(
                    ["provider stream contained no final answer event"]
                    if not _has_final_answer(events)
                    else []
                ),
                *(
                    ["provider stream contained no session/thread identity"]
                    if not (
                        _session_identity(
                            events, run["operator_model_config"]
                        ).get("provider_session_id")
                        or _session_identity(
                            events, run["operator_model_config"]
                        ).get("provider_thread_id")
                    )
                    else []
                ),
            ],
            "authority_effect": "none outside the disposable synthetic fixture",
        }
        write_json(evidence / "metadata.json", metadata)
        marker = {
            "schema": "maude.synthetic-operator.operator-complete.v1",
            "run_id": run_id,
            "completed_at": process_result["completed_at"],
            "process_returncode": process_result["returncode"],
            "timed_out": process_result["timed_out"],
            "transcript_sha256": metadata["transcript_sha256"],
            "observable_artifacts_sha256": sha256_file(
                evidence / "observable-artifacts.json"
            ),
        }
        write_json(evidence / "operator-complete.json", marker)
        return {"run_id": run_id, "status": "completed", **marker}
    finally:
        if public_cli_broker_process is not None:
            public_cli_broker_exit = public_cli_broker_process.stop()
        if driver_process is not None:
            driver_exit = driver_process.stop()
        if runtime_process is not None:
            runtime_exit = runtime_process.stop()
        boundary_cleanup = _release_private_socket_directories(boundary)
        if not boundary_cleanup["all_removed"]:
            raise CampaignError(
                f"{run_id}: private Claude socket arena cleanup failed"
            )
        if provider_home.exists():
            shutil.rmtree(provider_home)
        if evidence.exists():
            write_json(
                evidence / "process-cleanup.json",
                {
                    "runtime_exit": runtime_exit,
                    "driver_exit": driver_exit,
                    "public_cli_broker_exit": public_cli_broker_exit,
                    "provider_home_destroyed": not provider_home.exists(),
                    "completed_at": _utc_now(),
                },
            )
        if no_identity_failure:
            _archive_failed_operator_attempt(
                run_id,
                evidence,
                reason=(
                    "provider stream supplied no session or thread identity"
                ),
            )
            _safe_remove_lab(lab)


def _grade_bundle(run: dict[str, Any], evidence: Path) -> tuple[Path, str]:
    bundle = _lab_dir(run["run_id"]) / "grade-bundle"
    if bundle.exists():
        shutil.rmtree(bundle)
    bundle.mkdir()
    installation = run["surface"] == "maude-installation"
    source_boundary_path = evidence / "source-grade-boundary.json"
    source_boundary = (
        load_json(source_boundary_path)
        if source_boundary_path.is_file()
        else None
    )
    redacted = bool(
        source_boundary
        and source_boundary.get("grader_transcript_requires_redaction")
    )
    source_contaminated = bool(
        source_boundary
        and source_boundary.get("evaluator_contamination")
    )
    retrospective_path = (
        evidence / "observable" / "retrospective" / "separation.json"
    )
    retrospective = (
        load_json(retrospective_path)
        if retrospective_path.is_file()
        else None
    )
    retrospective_contaminated = not bool(
        retrospective and retrospective.get("separation_valid")
    )
    transcript_json_destination = (
        "transcript.redacted.jsonl" if redacted else "transcript.jsonl"
    )
    transcript_text_destination = (
        "transcript.redacted.txt" if redacted else "transcript.txt"
    )
    files = {
        "rubric.md": (
            PACKET_DIR / "installation-grading-rubric.md"
            if installation
            else PACKET_DIR / "grading-rubric.md"
        ),
        "failure-taxonomy.json": PACKET_DIR / "failure-taxonomy.json",
        "grader-output.schema.json": (
            PACKET_DIR / "installation-grader-output.schema.json"
            if installation
            else PACKET_DIR / "grader-output.schema.json"
        ),
        "grader-assignment.md": (
            PACKET_DIR / "rendered" / run["run_id"] / "grader-assignment.md"
        ),
        "operator-system-prompt.md": evidence / "operator-system-prompt.md",
        "operator-prompt.md": evidence / "operator-prompt.md",
        transcript_json_destination: (
            evidence / "grader-transcript.redacted.jsonl"
            if redacted
            else evidence / "transcript.jsonl"
        ),
        transcript_text_destination: (
            evidence / "grader-transcript.redacted.txt"
            if redacted
            else evidence / "transcript.txt"
        ),
        "supplied-inputs.json": evidence / "supplied-inputs.json",
        "observable-artifacts.json": evidence / "observable-artifacts.json",
        "retrospective-separation.json": retrospective_path,
    }
    if source_boundary_path.is_file():
        files["source-grade-boundary.json"] = source_boundary_path
    for destination, source in files.items():
        _copy_file(source, bundle / destination)
    operator_docs = bundle / "operator-docs"
    if run["surface"] == "maude":
        for name in ("commands.md", "configuration.md"):
            _copy_file(PACKET_DIR / "operator-docs" / name, operator_docs / name)
    elif run["surface"] == "docket-gwr-direct":
        for path in sorted(
            (PACKET_DIR / "direct-runtime" / "docs").glob("*.md")
        ):
            _copy_file(path, operator_docs / path.name)
    else:
        for path in _regular_tree_files(
            INSTALL_DOC_PACKET_DIR,
            label="installation grader documents",
        ):
            _copy_file(
                path,
                operator_docs / path.relative_to(INSTALL_DOC_PACKET_DIR),
            )
    withheld_observable_paths: list[str] = []
    source_inspection_detected = bool(
        source_boundary and source_boundary.get("action_violations")
    )
    for record in load_json(evidence / "observable-artifacts.json")["artifacts"]:
        record_path = str(record["path"])
        if source_inspection_detected and (
            record_path.startswith(
                "observable/operator-generated/"
            )
            or record_path
            == "observable/retrospective/initial-disposition.md"
        ):
            withheld_observable_paths.append(record_path)
            continue
        source = evidence / record["path"]
        if not source.is_file():
            continue
        target = bundle / record["path"]
        _copy_file(source, target)
    template = _read(PACKET_DIR / "prompts" / "grader-request-template.md")
    documentation = "\n".join(
        f"- `{path.relative_to(bundle)}`"
        for path in sorted(operator_docs.rglob("*"))
        if path.is_file()
    )
    prompt = (
        template.replace(
            "{{GRADER_ASSIGNMENT}}",
            _read(bundle / "grader-assignment.md"),
        )
        .replace("{{SURFACE}}", run["surface"])
        .replace("{{GRADING_RUBRIC}}", _read(bundle / "rubric.md"))
        .replace(
            "{{FAILURE_TAXONOMY_JSON}}",
            _read(bundle / "failure-taxonomy.json"),
        )
        .replace("{{OPERATOR_DOCUMENTATION}}", documentation)
        .replace(
            "{{OPERATOR_SYSTEM_PROMPT}}",
            _read(bundle / "operator-system-prompt.md"),
        )
        .replace("{{OPERATOR_PROMPT}}", _read(bundle / "operator-prompt.md"))
        .replace(
            "{{TRANSCRIPT_TEXT}}",
            _read(bundle / transcript_text_destination),
        )
        .replace(
            "{{OBSERVABLE_ARTIFACT_INDEX}}",
            _read(bundle / "observable-artifacts.json"),
        )
    )
    write_text(bundle / "grader-prompt.md", prompt)
    bundle_source_redactions: list[dict[str, Any]] = []
    if run.get("source_visibility") in {
        "release-source",
        "installed-distribution",
    }:
        source_records = _implementation_source_records(
            run,
            _installation_root(run["run_id"]),
        )
        marker = (
            b"[MECHANICALLY REDACTED: exact mounted "
            b"implementation-source bytes]"
        )
        for path in sorted(bundle.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            original = path.read_bytes()
            matches = _source_matches(original, source_records)
            if not matches:
                continue
            replacement = original
            if any(match["exact_member_digest"] for match in matches):
                replacement = marker + b"\n"
            else:
                for record in source_records:
                    for fingerprint in record["fingerprints"]:
                        replacement = replacement.replace(
                            fingerprint,
                            marker,
                        )
            if replacement == original:
                raise CampaignError(
                    "source match could not be mechanically redacted in "
                    f"grade bundle: {path}"
                )
            path.write_bytes(replacement)
            bundle_source_redactions.append(
                {
                    "path": str(path.relative_to(bundle)),
                    "original_bytes": len(original),
                    "original_sha256": sha256_bytes(original),
                    "redacted_bytes": len(replacement),
                    "redacted_sha256": sha256_bytes(replacement),
                    "matches": matches,
                }
            )
        if bundle_source_redactions:
            redacted = True
            source_contaminated = True
            write_json(
                bundle / "source-redactions.json",
                {
                    "schema": (
                        "maude.synthetic-operator.grade-source-redactions.v1"
                    ),
                    "run_id": run["run_id"],
                    "redactions": bundle_source_redactions,
                    "original_evidence_preserved_outside_bundle": True,
                    "evaluator_contamination": True,
                },
            )
    contamination_reasons: list[str] = []
    if source_contaminated:
        contamination_reasons.append(
            "The source-grade boundary records implementation-source "
            "inspection and/or mechanical transcript redaction. Read "
            "`source-grade-boundary.json` before grading."
        )
    if retrospective_contaminated:
        contamination_reasons.append(
            "The frozen post-task retrospective separation protocol was not "
            "satisfied. Read `retrospective-separation.json`; distinguish "
            "operator protocol noncompliance from actual evaluator coaching, "
            "which remains separately recorded."
        )
    evaluator_contamination = bool(contamination_reasons)
    if evaluator_contamination:
        prompt = (
            "# Mandatory evaluator-contamination notice\n\n"
            + "\n\n".join(contamination_reasons)
            + "\n\nClassify `evaluator contamination`, preserve all missing "
            "evidence, and do not draw a clean authority-comprehension or UX "
            "inference from contaminated evidence.\n\n"
            + _read(bundle / "grader-prompt.md")
        )
        write_text(bundle / "grader-prompt.md", prompt)
    else:
        prompt = _read(bundle / "grader-prompt.md")
    write_json(
        bundle / "bundle-inventory.json",
        {
            "schema": "maude.synthetic-operator.grade-bundle.v1",
            "run_id": run["run_id"],
            "files": inventory_files(bundle),
            "self_exclusion": (
                "bundle-inventory.json is excluded to avoid a recursive digest"
            ),
            "expected_disposition_included": False,
            "implementation_source_included": False,
            "filtered_source_archive_included": False,
            "installed_distribution_bytes_included": False,
            "private_runtime_state_or_rpc_included": False,
            "exact_raw_operator_transcript_included": not redacted,
            "mechanically_redacted_operator_transcript_included": redacted,
            "operator_transcript_path": transcript_json_destination,
            "numbered_transcript_path": transcript_text_destination,
            "source_evaluator_contamination": source_contaminated,
            "retrospective_evaluator_contamination": (
                retrospective_contaminated
            ),
            "evaluator_contamination": evaluator_contamination,
            "clean_authority_or_ux_inference_permitted": (
                not evaluator_contamination
            ),
            "bundle_source_redactions": bundle_source_redactions,
            "observable_paths_withheld_after_source_inspection": (
                withheld_observable_paths
            ),
        },
    )
    return bundle, prompt


def _json_candidates(value: Any) -> Iterable[Any]:
    if isinstance(value, dict):
        for key in ("structured_output", "result", "text", "output_text"):
            if key in value:
                yield value[key]
        for child in value.values():
            yield from _json_candidates(child)
    elif isinstance(value, list):
        for child in value:
            yield from _json_candidates(child)


def _parse_grade(events: list[dict[str, Any]]) -> dict[str, Any]:
    for event in reversed(events):
        for candidate in _json_candidates(event):
            if isinstance(candidate, dict) and "scenario_verdict" in candidate:
                return candidate
            if isinstance(candidate, str):
                text = candidate.strip()
                with contextlib.suppress(json.JSONDecodeError):
                    parsed = json.loads(text)
                    if isinstance(parsed, dict) and "scenario_verdict" in parsed:
                        return parsed
                start = text.find("{")
                end = text.rfind("}")
                if start >= 0 and end > start:
                    with contextlib.suppress(json.JSONDecodeError):
                        parsed = json.loads(text[start : end + 1])
                        if (
                            isinstance(parsed, dict)
                            and "scenario_verdict" in parsed
                        ):
                            return parsed
    raise CampaignError("independent grader did not return a parseable grade object")


def _validate_grade_local_invariants(grade: dict[str, Any]) -> None:
    failure_classes = grade.get("failure_classes")
    if (
        not isinstance(failure_classes, list)
        or not all(isinstance(value, str) for value in failure_classes)
        or len(failure_classes) != len(set(failure_classes))
    ):
        raise CampaignError(
            "independent grade failure_classes must contain unique strings"
        )


def run_grader(
    run: dict[str, Any],
    *,
    timeout: int,
    dry_run: bool,
) -> dict[str, Any]:
    run_id = run["run_id"]
    evidence = _run_dir(run_id)
    if (evidence / "grade" / "grade-complete.json").is_file():
        return {"run_id": run_id, "status": "skip-grade-complete"}
    if dry_run:
        return {
            "run_id": run_id,
            "status": "would-run-fresh-independent-grader",
            "provider": run["grader_model_config"],
        }
    if not (evidence / "operator-complete.json").is_file():
        raise CampaignError(f"{run_id}: operator evidence is incomplete")

    grade_dir = evidence / "grade"
    if grade_dir.exists():
        failed_root = evidence / "failed-grade-attempts"
        failed_root.mkdir(exist_ok=True)
        attempt = failed_root / (
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            + "-"
            + uuid.uuid4().hex
        )
        attempt.mkdir()
        shutil.move(str(grade_dir), attempt / "grade")
        summary_path = evidence / "summary.json"
        if summary_path.exists():
            shutil.move(str(summary_path), attempt / "summary.json")
        write_json(
            attempt / "retry-record.json",
            {
                "schema": (
                    "maude.synthetic-operator.failed-grade-attempt.v1"
                ),
                "run_id": run_id,
                "preserved_at": _utc_now(),
                "reason": (
                    "prior fresh grader attempt did not produce a complete "
                    "digest-linked grade marker"
                ),
                "next_attempt_must_use_fresh_session": True,
                "prior_evidence_overwritten": False,
                "authority_effect": "none",
            },
        )
    grade_dir.mkdir()
    raw = grade_dir / "raw"
    raw.mkdir()
    bundle, prompt = _grade_bundle(run, evidence)
    shutil.copytree(bundle, grade_dir / "grade-bundle")
    provider_home = _lab_dir(run_id) / "private-provider-home-grader"
    copied_auth, credential_values = _copy_provider_home(
        run["grader_model_config"], provider_home
    )
    try:
        boundary: dict[str, Any] | None = None
        if run["grader_model_config"] == "anthropic-sonnet":
            boundary, operator_home = _claude_grader_boundary(
                run_id, provider_home, bundle
            )
            bwrap_prefix: list[str] = []
            isolation = _claude_mcp_isolation_preflight(boundary)
        else:
            boundary, operator_home = _codex_grader_boundary(
                run_id, provider_home, bundle
            )
            bwrap_prefix = _codex_mcp_transport_bwrap(
                boundary, provider_home, operator_home
            )
            isolation = _codex_mcp_isolation_preflight(
                boundary, bwrap_prefix
            )
        write_json(grade_dir / "isolation-result.json", isolation)
        write_json(
            grade_dir / "clean-home-before.json",
            _operator_home_inventory(operator_home),
        )
        system_path = PACKET_DIR / "prompts" / "grader-system.md"
        system_prompt = _read(system_path)
        _copy_file(system_path, grade_dir / "grader-system-prompt.md")
        _copy_file(bundle / "grader-prompt.md", grade_dir / "grader-prompt.md")
        _copy_file(
            bundle / "bundle-inventory.json",
            grade_dir / "grade-bundle-inventory.json",
        )
        provider_argv, delivery, stdin_payload = _provider_argv(
            run["grader_model_config"],
            system_prompt=system_prompt,
            user_prompt=prompt,
            cwd=bundle,
            grade_schema=bundle / "grader-output.schema.json",
            claude_boundary=boundary,
        )
        actual_argv = (
            provider_argv
            if run["grader_model_config"] == "anthropic-sonnet"
            else [*bwrap_prefix, *provider_argv]
        )
        write_json(
            grade_dir / "invocation.json",
            {
                "schema": "maude.synthetic-operator.grade-invocation.v1",
                "bwrap_argv": bwrap_prefix,
                "claude_mcp_boundary": (
                    _claude_boundary_record(boundary)
                    if boundary is not None
                    else None
                ),
                "provider_argv_with_prompt_placeholders": [
                    (
                        "<EXACT_GRADER_SYSTEM_PROMPT>"
                        if item == system_prompt
                        else "<EXACT_RENDERED_GRADER_PROMPT>"
                        if item == prompt
                        else "<COMBINED_EXACT_PROMPT_RECORDED_BY_DIGEST>"
                        if item.startswith(system_prompt)
                        else "<EXACT_GRADER_SCHEMA_JSON>"
                        if item == _read(bundle / "grader-output.schema.json")
                        else item
                    )
                    for item in provider_argv
                ],
                "delivery": delivery,
                "system_prompt": file_record(
                    grade_dir / "grader-system-prompt.md",
                    relative_to=grade_dir,
                ),
                "grader_prompt": file_record(
                    grade_dir / "grader-prompt.md", relative_to=grade_dir
                ),
                "grade_bundle_inventory": file_record(
                    grade_dir / "grade-bundle-inventory.json",
                    relative_to=grade_dir,
                ),
            "provider_auth_files_copied_to_temporary_config_tree": copied_auth,
            "provider_auth_values_recorded": False,
            },
        )
        process_result = _run_model_process(
            actual_argv,
            cwd=(
                boundary["transport_cwd"]
                if boundary is not None
                else bundle
            ),
            stdout_path=raw / "grader.stdout.jsonl",
            stderr_path=raw / "grader.stderr",
            timeout=timeout,
            provider=run["grader_model_config"],
            provider_home=provider_home,
            copied_auth=copied_auth,
            credential_values=credential_values,
            gate_record_path=raw / "provider-auth-gate.json",
            claude_boundary=boundary,
            user_prompt=prompt if boundary is not None else None,
            process_env=(
                boundary["provider_environment"]
                if run["grader_model_config"] == "anthropic-sonnet"
                else None
            ),
            codex_auth_mode="retained-private-home",
            stdin_payload=stdin_payload,
        )
        _quarantine_if_secret(
            [raw / "grader.stdout.jsonl", raw / "grader.stderr"],
            credential_values,
            run_id=f"{run_id}-grader",
            evidence_dir=grade_dir,
        )
        write_json(
            grade_dir / "clean-home-after.json",
            _operator_home_inventory(operator_home),
        )
        events = _provider_events(raw / "grader.stdout.jsonl")
        actions = _event_actions(events)
        write_json(grade_dir / "commands-and-actions.json", actions)
        action_accounting = _action_accounting(events, actions)
        write_json(
            grade_dir / "action-accounting.json",
            action_accounting,
        )
        if not action_accounting["all_provider_actions_represented_once"]:
            raise CampaignError(
                f"{run_id}: grader action stream is not represented exactly "
                f"once: {action_accounting!r}"
            )
        safety = _audit_actions(actions)
        write_json(grade_dir / "session-safety-audit.json", safety)
        grader_identity = _session_identity(
            events,
            run["grader_model_config"],
        )
        if not (
            grader_identity.get("provider_session_id")
            or grader_identity.get("provider_thread_id")
        ):
            raise CampaignError(
                f"{run_id}: grader provider supplied no session/thread "
                "identity; incomplete attempt is preserved for a fresh retry"
            )
        if (
            process_result["returncode"] != 0
            or process_result["timed_out"]
            or not _has_final_answer(events)
        ):
            raise CampaignError(
                f"{run_id}: grader attempt did not complete normally; "
                "incomplete evidence is preserved for a fresh retry"
            )
        grade = _parse_grade(events)
        schema = load_json(bundle / "grader-output.schema.json")
        jsonschema.validate(grade, schema)
        _validate_grade_local_invariants(grade)
        bundle_inventory = load_json(bundle / "bundle-inventory.json")
        if (
            bundle_inventory.get("evaluator_contamination")
            and (
                "evaluator contamination"
                not in grade.get("failure_classes", [])
                or not any(
                    finding.get("failure_class")
                    == "evaluator contamination"
                    for finding in grade.get("findings", [])
                    if isinstance(finding, dict)
                )
            )
        ):
            raise CampaignError(
                f"{run_id}: contaminated grade bundle was not classified "
                "with an evidence-cited evaluator-contamination finding"
            )
        if (
            bundle_inventory.get("source_evaluator_contamination")
            and grade.get("scenario_verdict") != "indeterminate"
        ):
            raise CampaignError(
                f"{run_id}: source-contaminated grade must remain indeterminate"
            )
        write_json(grade_dir / "grade.json", grade)
        grader_meta = {
            "schema": "maude.synthetic-operator.independent-grade-metadata.v1",
            "campaign_id": CAMPAIGN_ID,
            "run_id": run_id,
            "operator_model_config": run["operator_model_config"],
            "grader_model_config": run["grader_model_config"],
            "model_provider": (
                "Anthropic"
                if run["grader_model_config"] == "anthropic-sonnet"
                else "OpenAI"
            ),
            "model_configuration": load_json(
                PACKET_DIR / "rendered" / run_id / "session-config.json"
            )["grader"],
            "grade_bundle_manifest": file_record(
                grade_dir / "grade-bundle-inventory.json",
                relative_to=grade_dir,
            ),
            "operator_transcripts": {
                "mode": load_json(
                    grade_dir
                    / "grade-bundle"
                    / "bundle-inventory.json"
                )["operator_transcript_path"],
                "exact_raw_unedited_included": load_json(
                    grade_dir
                    / "grade-bundle"
                    / "bundle-inventory.json"
                )["exact_raw_operator_transcript_included"],
                "evaluator_contamination": load_json(
                    grade_dir
                    / "grade-bundle"
                    / "bundle-inventory.json"
                )["evaluator_contamination"],
            },
            **_grading_model_family_metadata(run),
            **grader_identity,
            **process_result,
            "fresh_context_confirmed": True,
            "no_resume_or_continue": True,
            "tools": list(CLAUDE_GRADER_TOOLS),
            "expected_disposition_exposed": False,
            "implementation_source_exposed": False,
            "private_runtime_evidence_exposed": False,
            "evaluator_interventions": "none",
            "provider_auth_bootstrap": {
                "purpose": "provider transport only; not evaluator evidence",
                "readable_during_model_context": False,
                "gate": process_result["provider_auth_gate"],
                "leak_scans_passed": True,
            },
            "clean_grader_home": {
                "mount_path": str(OPERATOR_HOME_MOUNT),
                "before": file_record(
                    grade_dir / "clean-home-before.json",
                    relative_to=grade_dir,
                ),
                "after": file_record(
                    grade_dir / "clean-home-after.json",
                    relative_to=grade_dir,
                ),
                "host_home_mounted": False,
                "provider_auth_tree_separate": True,
            },
            "raw_stdout_sha256": sha256_file(raw / "grader.stdout.jsonl"),
            "raw_stderr_sha256": sha256_file(raw / "grader.stderr"),
            "grade_sha256": sha256_file(grade_dir / "grade.json"),
            "action_accounting": file_record(
                grade_dir / "action-accounting.json",
                relative_to=grade_dir,
            ),
            "safety_audit": safety,
        }
        write_json(grade_dir / "metadata.json", grader_meta)
        summary = {
            "schema": "maude.synthetic-operator.run-summary.v1",
            "campaign_id": CAMPAIGN_ID,
            "run_id": run_id,
            "surface": run["surface"],
            "scenario_id": run["scenario_id"],
            "persona_id": run["persona_id"],
            "operator_model_config": run["operator_model_config"],
            "grader_model_config": run["grader_model_config"],
            "scenario_verdict": grade["scenario_verdict"],
            "final_disposition": grade["final_disposition"],
            "task_completed": grade["task_completed"],
            "final_disposition_correct": grade["final_disposition_correct"],
            "measurements": grade["measurements"],
            "findings": grade["findings"],
            "failure_classes": grade["failure_classes"],
            "evidence_citations": grade["evidence_citations"],
            "severity": grade["severity"],
            "confidence": grade["confidence"],
            "attribution": grade["attribution"],
            "authority_and_refusal_understood": grade[
                "authority_and_refusal_understood"
            ],
            "safety_relevant_errors": grade["safety_relevant_errors"],
            "subjective_feedback": grade["subjective_feedback"],
            "elapsed_interaction_steps": load_json(
                evidence / "metadata.json"
            )["elapsed_interaction_steps"],
            "transcript_sha256": sha256_file(evidence / "transcript.jsonl"),
            "grade_sha256": sha256_file(grade_dir / "grade.json"),
            "authority_effect": "none",
        }
        if run["surface"] == "maude-installation":
            summary.update(
                {
                    "installation_results": grade["installation_results"],
                    "installation_findings": grade[
                        "installation_findings"
                    ],
                    "installation_verdict": grade[
                        "installation_verdict"
                    ],
                    "recommended_installation_or_documentation_changes": grade[
                        "recommended_installation_or_documentation_changes"
                    ],
                }
            )
        else:
            summary["rubric_results"] = grade["rubric_results"]
        write_json(evidence / "summary.json", summary)
        marker = {
            "schema": "maude.synthetic-operator.grade-complete.v1",
            "run_id": run_id,
            "completed_at": process_result["completed_at"],
            "grader_session": grader_identity,
            "grade_sha256": sha256_file(grade_dir / "grade.json"),
            "summary_sha256": sha256_file(evidence / "summary.json"),
        }
        write_json(grade_dir / "grade-complete.json", marker)
        return {"run_id": run_id, "status": "graded", **marker}
    finally:
        if provider_home.exists():
            shutil.rmtree(provider_home)


def _verify_index_records(
    records: Any,
    *,
    base: Path,
    label: str,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(records, list):
        return [f"{label}: records are not an array"]
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            errors.append(f"{label}: invalid file record")
            continue
        relative = record["path"]
        if relative in seen:
            errors.append(f"{label}: duplicate indexed path {relative}")
            continue
        seen.add(relative)
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            errors.append(f"{label}: unsafe indexed path {relative}")
            continue
        path = base / relative_path
        if not path.is_file() or path.is_symlink():
            errors.append(f"{label}: indexed file missing {relative}")
            continue
        actual = file_record(path, relative_to=base)
        for field in ("bytes", "sha256", "media_type"):
            if actual[field] != record.get(field):
                errors.append(
                    f"{label}: {field} mismatch for indexed file {relative}"
                )
    return errors


def _load_jsonl_checked(
    path: Path,
    *,
    label: str,
    errors: list[str],
) -> list[dict[str, Any]]:
    if not path.is_file() or path.is_symlink():
        errors.append(f"{label}: JSONL evidence missing")
        return []
    records: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_bytes().splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError):
            errors.append(f"{label}: malformed JSONL record {number}")
            continue
        if not isinstance(value, dict):
            errors.append(f"{label}: non-object JSONL record {number}")
            continue
        records.append(value)
    return records


def _verify_action_files(
    *,
    label: str,
    transcript: Path,
    actions_path: Path,
    accounting_path: Path,
    errors: list[str],
) -> None:
    for path, kind in (
        (transcript, "transcript"),
        (actions_path, "commands/actions"),
        (accounting_path, "action accounting"),
    ):
        if not path.is_file() or path.is_symlink():
            errors.append(f"{label}: {kind} evidence missing")
            return
    events = _provider_events(transcript)
    expected_actions = _event_actions(events)
    actions = load_json(actions_path)
    if actions != expected_actions:
        errors.append(f"{label}: committed action capture differs from transcript")
    expected_accounting = _action_accounting(events, expected_actions)
    accounting = load_json(accounting_path)
    if accounting != expected_accounting:
        errors.append(f"{label}: committed action accounting differs from stream")
    if not accounting.get("all_provider_actions_represented_once"):
        errors.append(f"{label}: provider actions are not represented exactly once")


def _verify_command_namespace_proof(
    record: dict[str, Any],
    *,
    label: str,
    errors: list[str],
) -> None:
    result = record.get("result")
    proof = record.get("namespace_and_mount_proof")
    if not isinstance(result, dict) or not isinstance(proof, dict):
        errors.append(f"{label}: command result/namespace proof missing")
        return
    if result.get("stdout_truncated") or result.get("stderr_truncated"):
        errors.append(f"{label}: command output was truncated")
    if record.get("result_sha256") != sha256_bytes(
        _canonical_json_bytes(result)
    ):
        errors.append(f"{label}: command-result digest mismatch")
    namespaces = proof.get("namespaces")
    if (
        not isinstance(namespaces, dict)
        or set(namespaces) != {"mnt", "net", "pid"}
        or any(
            not isinstance(value, dict) or value.get("distinct") is not True
            for value in namespaces.values()
        )
        or proof.get("external_network_namespace") != "unshared"
    ):
        errors.append(f"{label}: PID/mount/network separation proof invalid")
    if (
        proof.get("forbidden_paths_visible") != []
        or proof.get("provider_auth_mount_visible") is not False
        or proof.get("pre_exec_forbidden_descriptor_targets") != []
    ):
        errors.append(f"{label}: forbidden path/auth/FD proof invalid")
    inside_fds = proof.get("inside_pre_exec_file_descriptors")
    if (
        not isinstance(inside_fds, list)
        or any(
            not isinstance(value, dict)
            or value.get("fd") not in {0, 1, 2}
            for value in inside_fds
        )
    ):
        errors.append(f"{label}: inside pre-exec FD proof is not limited to 0/1/2")
    argv = record.get("bwrap_argv")
    if (
        not isinstance(argv, list)
        or not argv
        or argv[0] != str(BWRAP)
        or "--unshare-net" not in argv
        or "--unshare-pid" not in argv
    ):
        errors.append(f"{label}: per-command Bubblewrap argv is invalid")


def _is_lower_sha256(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _is_absolute_policy_path(value: Any) -> bool:
    if not isinstance(value, str) or not value.startswith("/"):
        return False
    return ".." not in Path(value).parts


def _verify_codex_command_broker_evidence(
    *,
    label: str,
    expected_mode: str,
    boundary_root: Path,
    declared: dict[str, Any],
    gate: dict[str, Any],
    proxy_calls: list[dict[str, Any]],
    errors: list[str],
) -> None:
    expected_names = {
        "command-broker-ready.json",
        "command-broker-trace.jsonl",
        "command-broker.stdout",
        "command-broker.stderr",
        "command-policy.json",
    }
    broker_entries = {
        path.name: path
        for path in boundary_root.iterdir()
        if path.name == "command-policy.json"
        or path.name.startswith("command-broker")
    }
    declared_broker = declared.get("command_broker")
    if expected_mode != "operator":
        if broker_entries:
            errors.append(
                f"{label}: grader boundary contains forbidden command-broker "
                f"evidence {sorted(broker_entries)!r}"
            )
        if declared_broker is not None:
            errors.append(
                f"{label}: grader boundary declares a forbidden command broker"
            )
        if gate.get("broker_command_count") != 0:
            errors.append(
                f"{label}: grader boundary has a nonzero broker-command count"
            )
        return

    actual_names = set(broker_entries)
    if actual_names != expected_names:
        errors.append(
            f"{label}: Codex command-broker file set differs: "
            f"missing={sorted(expected_names - actual_names)!r} "
            f"extra={sorted(actual_names - expected_names)!r}"
        )
    for name in sorted(expected_names & actual_names):
        try:
            mode = broker_entries[name].lstat().st_mode
        except OSError:
            errors.append(
                f"{label}: Codex command-broker evidence is unreadable: {name}"
            )
            continue
        if not stat.S_ISREG(mode):
            errors.append(
                f"{label}: Codex command-broker evidence is not a regular "
                f"file: {name}"
            )
    if not expected_names.issubset(actual_names):
        return
    if not isinstance(declared_broker, dict):
        errors.append(f"{label}: Codex operator command-broker declaration absent")
        return

    policy_path = broker_entries["command-policy.json"]
    ready_path = broker_entries["command-broker-ready.json"]
    trace_path = broker_entries["command-broker-trace.jsonl"]
    policy = load_json(policy_path)
    ready = load_json(ready_path)
    expected_policy_keys = {
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
    mounts = policy.get("mounts") if isinstance(policy, dict) else None
    sockets = policy.get("sockets") if isinstance(policy, dict) else None
    environment = (
        policy.get("environment") if isinstance(policy, dict) else None
    )
    cleanroom = policy.get("cleanroom") if isinstance(policy, dict) else None
    forbidden = (
        policy.get("forbidden_prefixes")
        if isinstance(policy, dict)
        else None
    )
    targets = (
        [
            value.get("target")
            for value in [*mounts, *sockets]
            if isinstance(value, dict)
        ]
        if isinstance(mounts, list) and isinstance(sockets, list)
        else []
    )
    serialized_policy = json.dumps(
        policy,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    if (
        not isinstance(policy, dict)
        or set(policy) != expected_policy_keys
        or policy.get("schema")
        != "maude.synthetic-operator.command-broker-policy.v1"
        or policy.get("bwrap") != str(BWRAP)
        or not _is_absolute_policy_path(policy.get("cwd"))
        or not _is_absolute_policy_path(policy.get("home"))
        or not isinstance(mounts, list)
        or any(
            not isinstance(value, dict)
            or set(value) != {"source", "target", "mode"}
            or value.get("mode") not in {"ro", "rw"}
            or not _is_absolute_policy_path(value.get("source"))
            or not _is_absolute_policy_path(value.get("target"))
            for value in mounts or []
        )
        or not isinstance(sockets, list)
        or any(
            not isinstance(value, dict)
            or set(value) != {"source", "target"}
            or not _is_absolute_policy_path(value.get("source"))
            or not _is_absolute_policy_path(value.get("target"))
            for value in sockets or []
        )
        or len(targets) != len(set(targets))
        or not isinstance(environment, dict)
        or environment.get("HOME") != policy.get("home")
        or "MAUDE_LAB_CONTROL_DIR" in environment
        or not isinstance(cleanroom, dict)
        or set(cleanroom) != {"etc", "empty", "masked"}
        or any(
            not _is_absolute_policy_path(cleanroom.get(key))
            for key in ("etc", "empty", "masked")
        )
        or not isinstance(forbidden, list)
        or not all(_is_absolute_policy_path(value) for value in forbidden)
        or len(forbidden) != len(set(forbidden))
        or str(HOST_SOURCE_ROOT) not in forbidden
        or str(PROVIDER_AUTH_MOUNT) not in forbidden
        or "/private/control" in serialized_policy
    ):
        errors.append(f"{label}: Codex command-broker policy is invalid")

    declared_policy = declared_broker.get("policy")
    actual_policy = file_record(policy_path, relative_to=boundary_root)
    declared_policy_valid = isinstance(declared_policy, dict) and all(
        declared_policy.get(field) == actual_policy[field]
        for field in ("bytes", "sha256", "media_type")
    )
    if (
        not declared_policy_valid
        or not isinstance(declared_policy.get("path"), str)
        or Path(declared_policy["path"]).name != "command-policy.json"
        or set(declared_broker)
        != {
            "policy",
            "socket",
            "ready",
            "trace",
            "provider_credentials_received",
            "semantic_prompt_received",
            "per_command_bubblewrap",
        }
        or declared_broker.get("provider_credentials_received") is not False
        or declared_broker.get("semantic_prompt_received") is not False
        or declared_broker.get("per_command_bubblewrap") is not True
        or not isinstance(declared_broker.get("ready"), str)
        or Path(declared_broker["ready"]).name
        != "command-broker-ready.json"
        or not isinstance(declared_broker.get("trace"), str)
        or Path(declared_broker["trace"]).name
        != "command-broker-trace.jsonl"
    ):
        errors.append(
            f"{label}: Codex command-broker declaration/policy linkage invalid"
        )

    socket_contract = declared.get("unix_socket_contract")
    expected_socket = declared_broker.get("socket")
    if (
        not isinstance(ready, dict)
        or set(ready)
        != {"schema", "pid", "socket", "policy_sha256", "token_sha256"}
        or ready.get("schema")
        != "maude.synthetic-operator.command-broker-ready.v1"
        or not isinstance(ready.get("pid"), int)
        or isinstance(ready.get("pid"), bool)
        or ready["pid"] < 1
        or not isinstance(expected_socket, str)
        or ready.get("socket") != expected_socket
        or not isinstance(socket_contract, dict)
        or socket_contract.get("command_socket_host") != expected_socket
        or ready.get("policy_sha256") != actual_policy["sha256"]
        or not _is_lower_sha256(ready.get("token_sha256"))
    ):
        errors.append(
            f"{label}: Codex command-broker readiness/policy linkage invalid"
        )

    broker_records = _load_jsonl_checked(
        trace_path,
        label=f"{label} Codex command broker",
        errors=errors,
    )
    if len(broker_records) != len(proxy_calls):
        errors.append(
            f"{label}: Codex proxy/broker command cardinality mismatch"
        )
    if gate.get("broker_command_count") != len(broker_records):
        errors.append(
            f"{label}: Codex gate broker-command count differs from trace"
        )

    expected_record_keys = {
        "schema",
        "ordinal",
        "request_id",
        "request_sha256",
        "command",
        "timeout_seconds",
        "bwrap_argv",
        "namespace_and_mount_proof",
        "result",
        "result_sha256",
        "elapsed_seconds",
    }
    expected_result_keys = {
        "command",
        "cwd",
        "returncode",
        "timed_out",
        "stdout",
        "stderr",
        "stdout_truncated",
        "stderr_truncated",
    }
    for index, (proxy, broker) in enumerate(
        zip(proxy_calls, broker_records, strict=False),
        1,
    ):
        command_label = f"{label} Codex command {index}"
        arguments = proxy.get("arguments")
        argument_keys = set(arguments) if isinstance(arguments, dict) else set()
        command = (
            arguments.get("command") if isinstance(arguments, dict) else None
        )
        timeout = (
            arguments.get(
                "timeout_seconds",
                COMMAND_BROKER_DEFAULT_TIMEOUT_SECONDS,
            )
            if isinstance(arguments, dict)
            else None
        )
        if (
            not isinstance(arguments, dict)
            or argument_keys not in (
                {"command"},
                {"command", "timeout_seconds"},
            )
            or not isinstance(command, str)
            or not command.strip()
            or not isinstance(timeout, int)
            or isinstance(timeout, bool)
            or timeout < 1
            or timeout > COMMAND_BROKER_MAX_TIMEOUT_SECONDS
            or proxy.get("schema")
            != "maude.synthetic-operator.mcp-correlation-event.v1"
            or proxy.get("ordinal") != index
            or proxy.get("mode") != "operator"
            or proxy.get("tool") != "terminal"
            or proxy.get("arguments_sha256")
            != sha256_bytes(_canonical_json_bytes(arguments))
        ):
            errors.append(
                f"{command_label}: proxy command/timeout evidence invalid"
            )

        request_id = broker.get("request_id")
        request_without_token = {
            "schema": "maude.synthetic-operator.command-request.v1",
            "request_id": request_id,
            "command": broker.get("command"),
            "timeout_seconds": broker.get("timeout_seconds"),
        }
        if (
            set(broker) != expected_record_keys
            or broker.get("schema")
            != "maude.synthetic-operator.command-broker-event.v1"
            or broker.get("ordinal") != index
            or not isinstance(request_id, str)
            or not request_id
            or request_id != proxy.get("correlation_id")
            or broker.get("command") != command
            or broker.get("timeout_seconds") != timeout
            or broker.get("request_sha256")
            != sha256_bytes(_canonical_json_bytes(request_without_token))
            or not isinstance(broker.get("elapsed_seconds"), (int, float))
            or isinstance(broker.get("elapsed_seconds"), bool)
            or broker["elapsed_seconds"] < 0
        ):
            errors.append(
                f"{command_label}: request/correlation evidence invalid"
            )

        result = broker.get("result")
        result_valid = (
            isinstance(result, dict)
            and set(result) == expected_result_keys
            and result.get("command") == command
            and result.get("cwd") == policy.get("cwd")
            and isinstance(result.get("returncode"), int)
            and not isinstance(result.get("returncode"), bool)
            and type(result.get("timed_out")) is bool
            and isinstance(result.get("stdout"), str)
            and isinstance(result.get("stderr"), str)
            and type(result.get("stdout_truncated")) is bool
            and type(result.get("stderr_truncated")) is bool
        )
        canonical_result_text = (
            _canonical_json_bytes(result).decode("utf-8")
            if isinstance(result, dict)
            else None
        )
        expected_mcp_result = {
            "content": [
                {"type": "text", "text": canonical_result_text}
            ],
            "isError": False,
        }
        if (
            not result_valid
            or broker.get("result_sha256")
            != sha256_bytes(_canonical_json_bytes(result))
            or proxy.get("result_text") != canonical_result_text
            or proxy.get("result_text_sha256")
            != sha256_bytes(canonical_result_text.encode("utf-8"))
            or proxy.get("mcp_result_sha256")
            != sha256_bytes(_canonical_json_bytes(expected_mcp_result))
            or proxy.get("is_error") is not False
        ):
            errors.append(
                f"{command_label}: result hash/text/error evidence invalid"
            )
        _verify_command_namespace_proof(
            broker,
            label=command_label,
            errors=errors,
        )


def _verify_pty_cleanup_proof(
    *,
    label: str,
    declared: dict[str, Any],
    cleanup: dict[str, Any],
    boundary_root: Path,
    errors: list[str],
) -> None:
    if not isinstance(declared.get("pty_broker"), dict):
        return
    required = {
        "pty-broker-invocation.json",
        "pty-broker-ready.json",
        "pty-broker-cleanup.json",
        "pty-broker.stdout",
        "pty-broker.stderr",
    }
    if any(not (boundary_root / name).is_file() for name in required):
        errors.append(f"{label}: PTY cleanup evidence files are incomplete")
        return
    pty_cleanup = cleanup.get("pty_cleanup")
    pty_process_cleanup = cleanup.get("pty_broker")
    copied_cleanup = load_json(
        boundary_root / "pty-broker-cleanup.json"
    )
    pty_invocation = load_json(
        boundary_root / "pty-broker-invocation.json"
    )
    request = (
        pty_process_cleanup.get("graceful_shutdown_request")
        if isinstance(pty_process_cleanup, dict)
        else None
    )
    cleanup_record = (
        pty_process_cleanup.get("cleanup_report")
        if isinstance(pty_process_cleanup, dict)
        else None
    )
    invocation_argv = pty_invocation.get("argv")
    shutdown_pairs = (
        [
            invocation_argv[index : index + 2]
            for index, value in enumerate(invocation_argv[:-1])
            if value == "--shutdown-request"
        ]
        if isinstance(invocation_argv, list)
        else []
    )
    copied_cleanup_path = boundary_root / "pty-broker-cleanup.json"
    if (
        not isinstance(pty_process_cleanup, dict)
        or pty_process_cleanup.get("remaining_processes") != []
        or pty_process_cleanup.get("exit_code") != 0
        or pty_process_cleanup.get("graceful_exit_requested") is not True
        or pty_process_cleanup.get("forced_after_graceful_timeout") is not False
        or pty_process_cleanup.get("socket_removed") is not True
        or pty_process_cleanup.get("shutdown_control_boundary")
        != {
            "path_visibility": "shared-persistent-pty-namespace",
            "created_after_provider_absent_or_exited": True,
            "contains_authority_or_secret": False,
            "request_fields": ["request_id", "requested_at", "schema"],
            "tamper_or_preexistence_policy": (
                "fail-closed-then-force-stop"
            ),
        }
        or not isinstance(
            pty_process_cleanup.get("observed_processes"), list
        )
        or not pty_process_cleanup["observed_processes"]
        or not isinstance(request, dict)
        or set(request) != {"schema", "request_id", "requested_at"}
        or request.get("schema")
        != "maude.synthetic-operator.pty-broker-shutdown-request.v1"
        or not isinstance(request.get("request_id"), str)
        or not request["request_id"]
        or not isinstance(cleanup_record, dict)
        or cleanup_record.get("bytes") != copied_cleanup_path.stat().st_size
        or cleanup_record.get("sha256")
        != sha256_file(copied_cleanup_path)
        or not isinstance(pty_cleanup, dict)
        or pty_cleanup != copied_cleanup
        or pty_cleanup.get("all_tracked_ptys_stopped") is not True
        or any(
            not isinstance(record, dict)
            or record.get("remaining") is not False
            for record in pty_cleanup.get("tracked_ptys", [])
        )
        or pty_cleanup.get("shutdown_mode") != "request-file"
        or pty_cleanup.get("shutdown_signal") is not None
        or pty_cleanup.get("shutdown_request") != request
        or pty_cleanup.get("shutdown_request_removed") is not True
        or pty_cleanup.get("socket_removed") is not True
        or pty_invocation.get("provider_auth_mounted") is not False
        or pty_invocation.get("host_source_mounted") is not False
        or pty_invocation.get("external_network") is not False
        or not isinstance(invocation_argv, list)
        or "--unshare-net" not in invocation_argv
        or shutdown_pairs
        != [["--shutdown-request", "/run/operator-pty/shutdown-request.json"]]
    ):
        errors.append(f"{label}: PTY graceful cleanup proof is invalid")


def _verify_session_boundary(
    *,
    label: str,
    config_id: str,
    raw: Path,
    transcript: Path,
    metadata: dict[str, Any],
    expected_tools: list[str] | None,
    expected_mode: str,
    errors: list[str],
) -> None:
    if (
        expected_tools is not None
        and metadata.get("tools") != expected_tools
    ):
        errors.append(f"{label}: declared tool roster differs")
    gate_path = raw / "provider-auth-gate.json"
    if not gate_path.is_file() or gate_path.is_symlink():
        errors.append(f"{label}: provider-auth gate evidence missing")
        return
    gate = load_json(gate_path)
    embedded = metadata.get("provider_auth_bootstrap", {}).get("gate")
    if gate != embedded:
        errors.append(f"{label}: metadata/auth-gate evidence differs")
    if config_id != "anthropic-sonnet":
        if (
            gate.get("schema")
            == (
                "maude.synthetic-operator."
                "codex-retained-provider-boundary.v1"
            )
        ):
            expected_bare = [
                "terminal" if expected_mode == "operator" else "evidence"
            ]
            expected_approval_safety_basis = {
                "intrinsic_action_features_disabled": list(
                    CODEX_DISABLED_INTRINSIC_ACTION_FEATURES
                ),
                "single_enabled_mcp_tool": expected_bare[0],
                "operator_terminal_bounded_by_frozen_broker": (
                    expected_mode == "operator"
                ),
                "grader_evidence_tool_read_only": (
                    expected_mode == "grader"
                ),
                "rationale": (
                    "Non-interactive approval is safe here only because "
                    "Codex intrinsic action features are disabled and "
                    "operator sessions expose exactly one MCP terminal "
                    "bounded by the frozen broker; grader sessions expose "
                    "exactly one read-only evidence tool."
                ),
            }
            expected_mcp_tool_approval_safety_basis = {
                "mcp_config_hash_pinned": True,
                "exact_enabled_tool_count": 1,
                "single_enabled_mcp_tool": expected_bare[0],
                "operator_terminal_bounded_by_frozen_broker": (
                    expected_mode == "operator"
                ),
                "grader_evidence_tool_read_only": (
                    expected_mode == "grader"
                ),
                "rationale": (
                    "MCP tool auto-approval is safe here only because the "
                    "hash-pinned server exposes exactly one tool: the "
                    "operator terminal is bounded by the frozen broker, "
                    "while the grader evidence tool is read-only."
                ),
            }
            expected_mcp_approval_config = (
                "mcp_servers."
                + (
                    CLAUDE_OPERATOR_SERVER
                    if expected_mode == "operator"
                    else CLAUDE_GRADER_SERVER
                )
                + '.default_tools_approval_mode="approve"'
            )
            if (
                gate.get("provider_config") != config_id
                or gate.get("status") != "complete"
                or gate.get("provider_auth_retained_until_transport_exit")
                is not True
                or gate.get("provider_auth_values_recorded") is not False
                or gate.get("provider_auth_output_scan_hits") != []
                or gate.get("provider_auth_destroyed") is not True
                or gate.get("provider_transport_cwd_is_neutral") is not True
                or gate.get("provider_task_paths_mounted")
                != (
                    []
                    if expected_mode == "operator"
                    else ["/evidence (read-only frozen grade bundle)"]
                )
                or gate.get("per_session_exact_tool_roster_supported")
                is not True
                or gate.get("intrinsic_action_features_disabled")
                != list(CODEX_DISABLED_INTRINSIC_ACTION_FEATURES)
                or gate.get("optional_features_disabled")
                != list(CODEX_DISABLED_OPTIONAL_FEATURES)
                or gate.get("codex_approval_argv")
                != list(CODEX_APPROVAL_CONFIG_ARGV)
                or gate.get("codex_approval_config_override")
                != CODEX_APPROVAL_CONFIG
                or gate.get("codex_approval_policy")
                != CODEX_APPROVAL_POLICY
                or gate.get("noninteractive_approval_safety_basis")
                != expected_approval_safety_basis
                or gate.get("codex_mcp_default_tools_approval_mode")
                != CODEX_MCP_DEFAULT_TOOLS_APPROVAL_MODE
                or gate.get("codex_mcp_approval_config_override")
                != expected_mcp_approval_config
                or gate.get("mcp_tool_approval_safety_basis")
                != expected_mcp_tool_approval_safety_basis
                or gate.get("unexpected_intrinsic_action_policy")
                != "fail-closed"
                or gate.get("allowed_mcp_server")
                != (
                    CLAUDE_OPERATOR_SERVER
                    if expected_mode == "operator"
                    else CLAUDE_GRADER_SERVER
                )
                or gate.get("allowed_mcp_tools")
                != expected_bare
                or gate.get("mcp_protocol_version")
                != CODEX_MCP_PROTOCOL_VERSION
                or gate.get("exact_correlation_proved") is not True
                or not isinstance(
                    gate.get("identity", {}).get("provider_thread_id"),
                    str,
                )
                or gate.get("provider_processes_remaining") != []
                or not isinstance(gate.get("boundary_evidence"), dict)
            ):
                errors.append(
                    f"{label}: Codex retained-auth boundary proof is incomplete"
                )
            boundary_root = raw / "codex-mcp-boundary"
            required = {
                "declared-boundary.json",
                "cleanup.json",
                "proxy-ready.json",
                "proxy-trace.jsonl",
            }
            if not boundary_root.is_dir() or any(
                not (boundary_root / name).is_file() for name in required
            ):
                errors.append(
                    f"{label}: Codex MCP boundary evidence is incomplete"
                )
                return
            declared = load_json(boundary_root / "declared-boundary.json")
            ready = load_json(boundary_root / "proxy-ready.json")
            records = _load_jsonl_checked(
                boundary_root / "proxy-trace.jsonl",
                label=f"{label} Codex proxy",
                errors=errors,
            )
            initialize_flushes = [
                value
                for value in records
                if value.get("protocol_event")
                == "initialize-response-flushed"
            ]
            initialized_notifications = [
                value
                for value in records
                if value.get("protocol_event")
                == "notifications/initialized"
            ]
            tools_list_flushes = [
                value
                for value in records
                if value.get("protocol_event")
                == "tools-list-response-flushed"
            ]
            proxy_calls = [value for value in records if "tool" in value]
            _verify_codex_command_broker_evidence(
                label=label,
                expected_mode=expected_mode,
                boundary_root=boundary_root,
                declared=declared,
                gate=gate,
                proxy_calls=proxy_calls,
                errors=errors,
            )
            gate_actions = gate.get("tool_actions")
            recomputed_correlations: list[dict[str, Any]] = []
            correlation_valid = (
                isinstance(gate_actions, list)
                and len(gate_actions) == len(proxy_calls)
            )
            if correlation_valid:
                for action, proxy_call in zip(
                    gate_actions, proxy_calls, strict=True
                ):
                    try:
                        provider_result_text = (
                            _codex_normalized_mcp_result_text(
                                action.get("result")
                            )
                        )
                    except CampaignError:
                        correlation_valid = False
                        break
                    provider_result_text_sha256 = sha256_bytes(
                        provider_result_text.encode("utf-8")
                    )
                    proxy_result_text = proxy_call.get("result_text")
                    proxy_result_text_sha256 = proxy_call.get(
                        "result_text_sha256"
                    )
                    proxy_is_error = proxy_call.get("is_error")
                    if (
                        action.get("server")
                        != (
                            CLAUDE_OPERATOR_SERVER
                            if expected_mode == "operator"
                            else CLAUDE_GRADER_SERVER
                        )
                        or action.get("tool") != proxy_call.get("tool")
                        or action.get("tool") != expected_bare[0]
                        or action.get("arguments_sha256")
                        != proxy_call.get("arguments_sha256")
                        or action.get("arguments_sha256")
                        != sha256_bytes(
                            _canonical_json_bytes(action.get("arguments"))
                        )
                        or proxy_call.get("arguments_sha256")
                        != sha256_bytes(
                            _canonical_json_bytes(
                                proxy_call.get("arguments")
                            )
                        )
                        or action.get("completed") is not True
                        or not isinstance(proxy_result_text, str)
                        or provider_result_text != proxy_result_text
                        or provider_result_text_sha256
                        != proxy_result_text_sha256
                        or sha256_bytes(proxy_result_text.encode("utf-8"))
                        != proxy_result_text_sha256
                        or type(proxy_is_error) is not bool
                    ):
                        correlation_valid = False
                        break
                    recomputed_correlations.append(
                        {
                            "action_id": action.get("action_id"),
                            "tool": action.get("tool"),
                            "arguments_sha256": action.get(
                                "arguments_sha256"
                            ),
                            "provider_normalized_result_text_sha256": (
                                provider_result_text_sha256
                            ),
                            "proxy_result_text_sha256": (
                                proxy_result_text_sha256
                            ),
                            "proxy_is_error": proxy_is_error,
                        }
                    )
            if (
                not correlation_valid
                or gate.get("normalized_result_correlations")
                != recomputed_correlations
            ):
                errors.append(
                    f"{label}: Codex normalized MCP result correlation "
                    "proof is invalid"
                )
            if (
                declared.get("mcp_protocol_version")
                != CODEX_MCP_PROTOCOL_VERSION
                or declared.get("codex_approval_argv")
                != list(CODEX_APPROVAL_CONFIG_ARGV)
                or declared.get("codex_approval_config_override")
                != CODEX_APPROVAL_CONFIG
                or declared.get("codex_approval_policy")
                != CODEX_APPROVAL_POLICY
                or declared.get("noninteractive_approval_safety_basis")
                != expected_approval_safety_basis
                or declared.get("codex_mcp_default_tools_approval_mode")
                != CODEX_MCP_DEFAULT_TOOLS_APPROVAL_MODE
                or declared.get("codex_mcp_approval_config_override")
                != expected_mcp_approval_config
                or declared.get("mcp_tool_approval_safety_basis")
                != expected_mcp_tool_approval_safety_basis
                or ready.get("protocol_version_requested")
                != CODEX_MCP_PROTOCOL_VERSION
                or ready.get("protocol_version_negotiated")
                != CODEX_MCP_PROTOCOL_VERSION
                or ready.get("tools") != expected_bare
                or len(initialize_flushes) != 1
                or len(initialized_notifications) != 1
                or len(tools_list_flushes) != 1
                or initialize_flushes[0].get("initialize_accepted") is not True
                or initialize_flushes[0].get("protocol_version_requested")
                != CODEX_MCP_PROTOCOL_VERSION
                or initialize_flushes[0].get("protocol_version_negotiated")
                != CODEX_MCP_PROTOCOL_VERSION
                or initialized_notifications[0].get("protocol_version")
                != CODEX_MCP_PROTOCOL_VERSION
                or tools_list_flushes[0].get("protocol_version")
                != CODEX_MCP_PROTOCOL_VERSION
                or ready.get("initialize_message_ordinal")
                != initialize_flushes[0].get("message_ordinal")
                or ready.get("tools_list_message_ordinal")
                != tools_list_flushes[0].get("message_ordinal")
                or ready.get("tools_list_response_sha256")
                != tools_list_flushes[0].get("response_sha256")
            ):
                errors.append(
                    f"{label}: Codex MCP protocol negotiation proof is invalid"
                )
            cleanup = load_json(boundary_root / "cleanup.json")
            if (
                cleanup.get("schema")
                != "maude.synthetic-operator.codex-boundary-cleanup.v1"
                or cleanup.get("provider_auth_destroyed") is not True
                or cleanup.get("provider_processes_remaining") != []
                or cleanup.get("cleanup_errors") != []
                or (
                    expected_mode == "operator"
                    and (
                        not isinstance(
                            cleanup.get("command_broker"), dict
                        )
                        or cleanup["command_broker"].get(
                            "remaining_processes"
                        )
                        != []
                    )
                )
            ):
                errors.append(
                    f"{label}: Codex boundary cleanup/orphan proof is invalid"
                )
            socket_cleanup = cleanup.get("private_socket_arena")
            if (
                not isinstance(socket_cleanup, dict)
                or socket_cleanup.get("path_budget_bytes")
                != UNIX_SOCKET_PATH_BUDGET
                or socket_cleanup.get("all_removed") is not True
                or any(
                    not isinstance(record, dict)
                    or record.get("removed") is not True
                    or record.get("remaining_entries") != []
                    for record in socket_cleanup.get("directories", [])
                )
            ):
                errors.append(
                    f"{label}: Codex private socket cleanup proof is invalid"
                )
            _verify_pty_cleanup_proof(
                label=f"{label} Codex",
                declared=declared,
                cleanup=cleanup,
                boundary_root=boundary_root,
                errors=errors,
            )
            boundary_record = gate.get("boundary_evidence")
            if isinstance(boundary_record, dict):
                errors.extend(
                    _verify_index_records(
                        [boundary_record],
                        base=raw,
                        label=f"{label} Codex boundary linkage",
                    )
                )
            else:
                errors.append(
                    f"{label}: Codex cleanup evidence linkage absent"
                )
            return
        if (
            gate.get("schema")
            != "maude.synthetic-operator.provider-auth-gate.v1"
            or gate.get("provider_config") != config_id
            or gate.get("stable_stopped_tree_proved") is not True
            or gate.get("bootstrap_files_removed") is not True
            or gate.get("retained_auth_file_descriptors") != []
            or gate.get("auth_paths_visible_after_scrub") != []
            or gate.get("provider_auth_files_after_scrub") != []
            or gate.get("provider_state_secret_hits_after_scrub") != []
            or gate.get("provider_state_secret_hits_at_exit") != []
            or gate.get("resumed_after_proof") is not True
            or gate.get(
                "provider_auth_tree_remained_credential_free_through_exit"
            )
            is not True
            or not isinstance(
                gate.get("provider_noncredential_state_after_scrub"), dict
            )
            or not isinstance(
                gate.get("provider_noncredential_state_at_exit"), dict
            )
            or not isinstance(gate.get("provider_exited_at"), str)
        ):
            errors.append(f"{label}: Codex early-scrub gate proof is incomplete")
        proofs = gate.get("provider_auth_and_operator_home_mount_proofs")
        isolated = {
            int(value)
            for value in gate.get("processes_stopped", [])
            if value != gate.get("process_group")
        }
        proved: dict[int, dict[str, dict[str, Any]]] = {}
        if isinstance(proofs, list):
            for proof in proofs:
                if isinstance(proof, dict) and isinstance(proof.get("pid"), int):
                    proved.setdefault(proof["pid"], {})[
                        str(proof.get("mount_point"))
                    ] = proof
        if not isolated or any(
            proved.get(pid, {}).get(str(PROVIDER_AUTH_MOUNT), {}).get(
                "writable"
            )
            is not True
            or proved.get(pid, {}).get(str(OPERATOR_HOME_MOUNT), {}).get(
                "writable"
            )
            is not True
            for pid in isolated
        ):
            errors.append(f"{label}: Codex isolated-member mount proof invalid")
        milestones = gate.get("milestones")
        names = (
            [str(value.get("name")) for value in milestones]
            if isinstance(milestones, list)
            else []
        )
        required = [
            "identity_observed",
            "sigstop_requested",
            "provider_tree_stable_and_stopped",
            "provider_stdout_drained",
            "current_auth_values_loaded_for_redaction",
            "pre_resume_secret_scan_passed",
            "provider_auth_and_operator_home_writable_mounts_proved",
            "bootstrap_files_unlinked",
            "auth_file_descriptor_scan_completed",
            "auth_file_descriptor_scan_passed",
            "auth_path_absence_and_state_redaction_proved",
            "sigcont_sent",
        ]
        if any(name not in names for name in required) or any(
            names.index(left) >= names.index(right)
            for left, right in zip(required, required[1:], strict=False)
        ):
            errors.append(f"{label}: Codex gate milestone ordering is invalid")
        return

    boundary_root = raw / "claude-mcp-boundary"
    required_files = {
        "declared-boundary.json",
        "cleanup.json",
        "proxy-ready.json",
        "proxy-trace.jsonl",
    }
    if expected_mode == "operator":
        required_files.update(
            {
                "command-broker-ready.json",
                "command-broker-trace.jsonl",
                "command-broker.stdout",
                "command-broker.stderr",
                "command-policy.json",
            }
        )
    if not boundary_root.is_dir():
        errors.append(f"{label}: Claude boundary evidence directory missing")
        return
    actual_files = {
        path.name
        for path in boundary_root.iterdir()
        if path.is_file() and not path.is_symlink()
    }
    if not required_files.issubset(actual_files):
        errors.append(
            f"{label}: Claude boundary expected files missing: "
            f"{sorted(required_files - actual_files)!r}"
        )
        return
    declared = load_json(boundary_root / "declared-boundary.json")
    if isinstance(declared.get("pty_broker"), dict):
        required_files.update(
            {
                "pty-broker-invocation.json",
                "pty-broker-ready.json",
                "pty-broker-cleanup.json",
                "pty-broker.stdout",
                "pty-broker.stderr",
            }
        )
    if actual_files != required_files:
        errors.append(
            f"{label}: Claude boundary file set differs: "
            f"missing={sorted(required_files - actual_files)!r} "
            f"extra={sorted(actual_files - required_files)!r}"
        )
    cleanup = load_json(boundary_root / "cleanup.json")
    ready = load_json(boundary_root / "proxy-ready.json")
    proxy_records = _load_jsonl_checked(
        boundary_root / "proxy-trace.jsonl",
        label=f"{label} Claude proxy",
        errors=errors,
    )
    if (
        gate.get("schema")
        != "maude.synthetic-operator.claude-provider-boundary.v1"
        or gate.get("status") != "complete"
        or gate.get("provider_auth_retained_until_transport_exit") is not True
        or gate.get("provider_auth_destroyed") is not True
        or gate.get("provider_auth_mounted_in_mcp_or_command") is not False
        or gate.get("host_source_mounted_in_mcp_or_command") is not False
        or gate.get("allowed_tools") != expected_tools
        or gate.get("built_in_tools_allowed") != []
        or gate.get("prompt_sent_after_tools_list_flush") is not True
        or gate.get("identity", {}).get("provider_reported_tools")
        != expected_tools
    ):
        errors.append(f"{label}: Claude retained-auth/tool-roster gate is invalid")
    disclosures = gate.get("transport_metadata_path_disclosures")
    if not isinstance(disclosures, list) or any(
        not isinstance(item, dict)
        or set(item)
        != {
            "event_number",
            "event_type",
            "event_subtype",
            "json_pointer",
            "path_kind",
            "path_sha256",
        }
        or not isinstance(item.get("event_number"), int)
        or item["event_number"] < 1
        or item.get("event_type") != "system"
        or item.get("event_subtype") != "init"
        or not isinstance(item.get("json_pointer"), str)
        or not item["json_pointer"].startswith("/")
        or item.get("path_kind") != "provider_private_home"
        or not isinstance(item.get("path_sha256"), str)
        or len(item["path_sha256"]) != 64
        for item in disclosures
    ):
        errors.append(
            f"{label}: Claude transport-metadata path disclosures are invalid"
        )
    if (
        declared.get("mode") != expected_mode
        or declared.get("allowed_tools") != expected_tools
        or declared.get("built_in_tools") != []
        or declared.get("provider_auth_mounted_in_proxy_or_command")
        is not False
        or declared.get("host_source_mounted_in_proxy_or_command") is not False
        or declared.get("external_network_available_to_proxy_or_command")
        is not False
    ):
        errors.append(f"{label}: declared Claude boundary is invalid")
    socket_contract = declared.get("unix_socket_contract")
    if not isinstance(socket_contract, dict) or socket_contract.get(
        "path_budget_bytes"
    ) != UNIX_SOCKET_PATH_BUDGET:
        errors.append(f"{label}: Claude Unix-socket contract is absent")
    elif expected_mode == "operator":
        host_socket = socket_contract.get("command_socket_host")
        try:
            host_socket_bytes = len(os.fsencode(str(host_socket)))
        except (TypeError, ValueError):
            host_socket_bytes = UNIX_SOCKET_PATH_BUDGET + 1
        if (
            not isinstance(host_socket, str)
            or host_socket_bytes > UNIX_SOCKET_PATH_BUDGET
            or socket_contract.get("command_socket_host_bytes")
            != host_socket_bytes
            or socket_contract.get("command_socket_proxy")
            != str(CLAUDE_COMMAND_SOCKET_MOUNT)
        ):
            errors.append(f"{label}: Claude command socket exceeds its budget")
    init_flushes = [
        value
        for value in proxy_records
        if value.get("protocol_event") == "initialize-response-flushed"
    ]
    list_flushes = [
        value
        for value in proxy_records
        if value.get("protocol_event") == "tools-list-response-flushed"
    ]
    expected_bare = [
        value.rsplit("__", 1)[-1] for value in expected_tools or []
    ]
    if (
        ready.get("schema")
        != "maude.synthetic-operator.claude-mcp-ready.v1"
        or ready.get("protocol_version_requested")
        != CLAUDE_MCP_PROTOCOL_VERSION
        or ready.get("protocol_version_negotiated")
        != CLAUDE_MCP_PROTOCOL_VERSION
        or ready.get("tools") != expected_bare
        or len(init_flushes) != 1
        or len(list_flushes) != 1
        or init_flushes[0].get("initialize_accepted") is not True
        or init_flushes[0].get("protocol_version_requested")
        != CLAUDE_MCP_PROTOCOL_VERSION
        or init_flushes[0].get("protocol_version_negotiated")
        != CLAUDE_MCP_PROTOCOL_VERSION
        or ready.get("initialize_message_ordinal")
        != init_flushes[0].get("message_ordinal")
        or ready.get("tools_list_message_ordinal")
        != list_flushes[0].get("message_ordinal")
        or not isinstance(ready.get("initialize_message_ordinal"), int)
        or not isinstance(ready.get("tools_list_message_ordinal"), int)
        or ready["initialize_message_ordinal"]
        >= ready["tools_list_message_ordinal"]
        or ready.get("tools_list_response_sha256")
        != list_flushes[0].get("response_sha256")
    ):
        errors.append(f"{label}: Claude MCP readiness/initialize proof is invalid")
    actions = gate.get("tool_actions")
    results = gate.get("tool_results")
    proxy_calls = [value for value in proxy_records if "tool" in value]
    if (
        not isinstance(actions, list)
        or not isinstance(results, list)
        or len(actions) != len(results)
        or len(actions) != len(proxy_calls)
    ):
        errors.append(f"{label}: Claude tool/proxy/result cardinality mismatch")
        actions = []
        results = []
    result_by_id = {
        value.get("tool_use_id"): value
        for value in results
        if isinstance(value, dict)
    }
    for action, proxy in zip(actions, proxy_calls, strict=False):
        result = result_by_id.get(action.get("tool_use_id"))
        if (
            not isinstance(result, dict)
            or proxy.get("tool") != str(action.get("tool")).rsplit("__", 1)[-1]
            or proxy.get("arguments_sha256")
            != action.get("arguments_sha256")
            or proxy.get("result_text_sha256")
            != result.get("result_text_sha256")
            or bool(proxy.get("is_error")) != bool(result.get("is_error"))
        ):
            errors.append(f"{label}: Claude tool/proxy/result digest mismatch")
            break
    if expected_mode == "operator":
        broker_records = _load_jsonl_checked(
            boundary_root / "command-broker-trace.jsonl",
            label=f"{label} Claude command broker",
            errors=errors,
        )
        if len(broker_records) != len(proxy_calls):
            errors.append(f"{label}: Claude proxy/broker cardinality mismatch")
        for index, (proxy, broker) in enumerate(
            zip(proxy_calls, broker_records, strict=False), 1
        ):
            if (
                broker.get("schema")
                != "maude.synthetic-operator.command-broker-event.v1"
                or broker.get("request_id") != proxy.get("correlation_id")
                or proxy.get("result_text_sha256")
                != sha256_bytes(
                    _canonical_json_bytes(broker.get("result"))
                )
            ):
                errors.append(
                    f"{label}: Claude proxy/broker correlation {index} invalid"
                )
            _verify_command_namespace_proof(
                broker,
                label=f"{label} command {index}",
                errors=errors,
            )
        policy = load_json(boundary_root / "command-policy.json")
        serialized_policy = json.dumps(
            policy, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        )
        if (
            "MAUDE_LAB_CONTROL_DIR" in policy.get("environment", {})
            or "/private/control" in serialized_policy
        ):
            errors.append(f"{label}: Claude command policy exposes raw control")
    if (
        cleanup.get("provider_auth_destroyed") is not True
        or cleanup.get("provider_processes_remaining") != []
        or cleanup.get("cleanup_errors") != []
        or (
            expected_mode == "operator"
            and (
                cleanup.get("command_broker", {}).get("remaining_processes")
                != []
            )
        )
    ):
        errors.append(f"{label}: Claude boundary cleanup/orphan proof is invalid")
    socket_cleanup = cleanup.get("private_socket_arena")
    if (
        not isinstance(socket_cleanup, dict)
        or socket_cleanup.get("path_budget_bytes")
        != UNIX_SOCKET_PATH_BUDGET
        or socket_cleanup.get("all_removed") is not True
        or any(
            record.get("removed") is not True
            or record.get("remaining_entries") != []
            for record in socket_cleanup.get("directories", [])
            if isinstance(record, dict)
        )
    ):
        errors.append(f"{label}: Claude private socket cleanup proof is invalid")
    _verify_pty_cleanup_proof(
        label=f"{label} Claude",
        declared=declared,
        cleanup=cleanup,
        boundary_root=boundary_root,
        errors=errors,
    )
    boundary_record = gate.get("boundary_evidence")
    if isinstance(boundary_record, dict):
        errors.extend(
            _verify_index_records(
                [boundary_record],
                base=raw,
                label=f"{label} Claude boundary linkage",
            )
        )
    else:
        errors.append(f"{label}: Claude cleanup evidence linkage absent")


def _verify_public_cli_broker(
    *,
    run_id: str,
    evidence: Path,
    errors: list[str],
) -> None:
    interface = evidence / "raw" / "interface"
    ready_path = interface / "public-cli-broker-ready.json"
    trace_path = interface / "public-cli-broker.jsonl"
    cleanup_path = interface / "public-cli-broker-cleanup.json"
    for path, kind in (
        (ready_path, "ready"),
        (trace_path, "trace"),
        (cleanup_path, "cleanup"),
    ):
        if not path.is_file() or path.is_symlink():
            errors.append(f"{run_id}: public-CLI broker {kind} evidence missing")
            return
    ready = load_json(ready_path)
    cleanup = load_json(cleanup_path)
    traces = _load_jsonl_checked(
        trace_path,
        label=f"{run_id} public-CLI broker",
        errors=errors,
    )
    driver_path = interface / "driver-actions.jsonl"
    driver = (
        _load_jsonl_checked(
            driver_path,
            label=f"{run_id} Maude driver actions",
            errors=errors,
        )
        if driver_path.is_file()
        else []
    )
    driver_by_request = {
        value.get("request_file"): value
        for value in driver
        if isinstance(value.get("request_file"), str)
    }
    if (
        ready.get("schema")
        != "maude.synthetic-operator.public-cli-broker-ready.v1"
        or ready.get("public_request_schema")
        != "maude.synthetic-operator.public-cli-request.v1"
        or ready.get("driver_queue_schema")
        != "maude.synthetic-operator.queue.v1"
        or ready.get("raw_control_dir_exposed_to_client") is not False
    ):
        errors.append(f"{run_id}: public-CLI broker readiness proof invalid")
    for index, record in enumerate(traces, 1):
        request = record.get("public_request")
        response = record.get("public_response")
        if (
            record.get("schema")
            != "maude.synthetic-operator.public-cli-broker-event.v1"
            or not isinstance(request, dict)
            or not isinstance(response, dict)
            or record.get("public_request_sha256")
            != sha256_bytes(_canonical_json_bytes(request))
            or record.get("public_response_sha256")
            != sha256_bytes(_canonical_json_bytes(response))
            or request.get("request_id") != response.get("request_id")
        ):
            errors.append(f"{run_id}: public-CLI RPC {index} digest invalid")
            continue
        settlement = record.get("settlement")
        if settlement == "completed":
            driver_record = driver_by_request.get(
                record.get("queue_request_file")
            )
            if not isinstance(driver_record, dict):
                errors.append(
                    f"{run_id}: public-CLI RPC {index} lacks driver correlation"
                )
                continue
            queue_bytes = (
                _canonical_json_bytes(driver_record.get("request")) + b"\n"
            )
            response_bytes = (
                _canonical_json_bytes(driver_record.get("response")) + b"\n"
            )
            if (
                record.get("correlation_complete") is not True
                or record.get("queue_request_sha256")
                != sha256_bytes(queue_bytes)
                or driver_record.get("request_sha256")
                != sha256_bytes(queue_bytes)
                or record.get("queue_response_file")
                != driver_record.get("response_file")
                or record.get("queue_response_sha256")
                != sha256_bytes(response_bytes)
                or response != driver_record.get("response")
            ):
                errors.append(
                    f"{run_id}: public-CLI RPC {index} queue correlation invalid"
                )
        elif settlement == "retained-unknown-after-public-timeout":
            driver_record = driver_by_request.get(
                record.get("queue_request_file")
            )
            queue_request = {
                key: value
                for key, value in request.items()
                if key not in {"timeout_seconds"}
            }
            queue_request["schema"] = "maude.synthetic-operator.queue.v1"
            queue_bytes = _canonical_json_bytes(queue_request) + b"\n"
            if (
                record.get("queue_request_retained") is not True
                or response.get("terminal_state") != "unknown"
                or response.get("queued_request_retained") is not True
                or record.get("correlation_complete") is not False
                or record.get("queue_request_sha256")
                != sha256_bytes(queue_bytes)
                or record.get("queue_response_observed_at_return") is not False
                or record.get("queue_response_sha256") is not None
                or record.get("queue_response_file")
                != record.get("queue_request_file")
            ):
                errors.append(
                    f"{run_id}: public-CLI RPC {index} launders timeout state"
                )
            if isinstance(driver_record, dict) and (
                driver_record.get("request") != queue_request
                or driver_record.get("request_sha256")
                != sha256_bytes(queue_bytes)
            ):
                errors.append(
                    f"{run_id}: public-CLI timed-out RPC {index} later-driver "
                    "correlation invalid"
                )
        elif settlement not in {
            "broker-failed-closed",
            "rejected-before-private-queue",
        }:
            errors.append(f"{run_id}: public-CLI RPC {index} settlement unknown")
    if (
        cleanup.get("schema")
        != "maude.synthetic-operator.public-cli-broker-cleanup.v1"
        or cleanup.get("processed_requests") != len(traces)
        or cleanup.get("no_request_in_flight") is not True
        or cleanup.get("public_socket_removed") is not True
        or cleanup.get("ready_marker_retained_as_evidence") is not True
        or cleanup.get("raw_control_dir_exposed_to_client") is not False
    ):
        errors.append(f"{run_id}: public-CLI broker cleanup proof invalid")
    isolation_path = evidence / "isolation-result.json"
    if isolation_path.is_file():
        isolation = load_json(isolation_path)
        if isolation.get("schema") in {
            "maude.synthetic-operator.claude-mcp-isolation-result.v1",
            "maude.synthetic-operator.codex-mcp-isolation-result.v1",
        }:
            public_boundary = isolation.get("public_cli_boundary")
            if (
                not isinstance(public_boundary, dict)
                or public_boundary.get("raw_driver_queue_exposed") is not False
                or public_boundary.get("socket_target")
                != str(PUBLIC_CLI_SOCKET_MOUNT)
                or public_boundary.get("exact_socket_count") != 1
            ):
                errors.append(
                    f"{run_id}: provider public socket/raw-control "
                    "isolation proof invalid"
                )
        else:
            forbidden = isolation.get("forbidden_private_path_probes")
            sockets = isolation.get("public_socket_probes")
            if (
                not isinstance(forbidden, list)
                or len(forbidden) != 1
                or forbidden[0].get("probe", {}).get("returncode") != 0
                or not isinstance(sockets, list)
                or len(sockets) != 1
                or sockets[0].get("path") != str(PUBLIC_CLI_SOCKET_MOUNT)
                or sockets[0].get("probe", {}).get("returncode") != 0
            ):
                errors.append(
                    f"{run_id}: Codex public socket/raw-control "
                    "isolation proof invalid"
                )
    process_cleanup = evidence / "process-cleanup.json"
    if (
        not process_cleanup.is_file()
        or load_json(process_cleanup).get("public_cli_broker_exit") != 0
    ):
        errors.append(f"{run_id}: public-CLI broker process cleanup invalid")


def verify_evidence(
    manifest: dict[str, Any], *, require_complete: bool
) -> dict[str, Any]:
    declared = {run["run_id"]: run for run in manifest["runs"]}
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    personas: set[str] = set()
    maude_personas: set[str] = set()
    installation_personas: set[str] = set()
    maude_scenarios: set[str] = set()
    installation_scenarios: set[str] = set()
    installation_coverage: set[str] = set()
    operator_sessions: set[str] = set()
    grader_sessions: set[str] = set()
    failed_grader_sessions: set[str] = set()
    failed_operator_attempts = 0
    failed_grader_attempts = 0
    pending_grader_sessions: list[tuple[str, str]] = []
    for run_id, run in declared.items():
        evidence = _run_dir(run_id)
        operator_marker = evidence / "operator-complete.json"
        grade_marker = evidence / "grade" / "grade-complete.json"
        record = {
            "run_id": run_id,
            "surface": run["surface"],
            "scenario_id": run["scenario_id"],
            "persona_id": run["persona_id"],
            "operator_complete": operator_marker.is_file(),
            "grade_complete": grade_marker.is_file(),
        }
        retrospective: dict[str, Any] | None = None
        if operator_marker.is_file():
            metadata = load_json(evidence / "metadata.json")
            _verify_action_files(
                label=f"{run_id} operator",
                transcript=evidence / "transcript.jsonl",
                actions_path=evidence / "commands-and-actions.json",
                accounting_path=evidence / "action-accounting.json",
                errors=errors,
            )
            _verify_session_boundary(
                label=f"{run_id} operator",
                config_id=run["operator_model_config"],
                raw=evidence / "raw",
                transcript=evidence / "transcript.jsonl",
                metadata=metadata,
                expected_tools=(
                    list(CLAUDE_OPERATOR_TOOLS)
                    if run["operator_model_config"] == "anthropic-sonnet"
                    else None
                ),
                expected_mode="operator",
                errors=errors,
            )
            if run["surface"] == "maude":
                _verify_public_cli_broker(
                    run_id=run_id,
                    evidence=evidence,
                    errors=errors,
                )
            operator_marker_data = load_json(operator_marker)
            actual_sha = sha256_file(evidence / "transcript.jsonl")
            if metadata.get("transcript_sha256") != actual_sha:
                errors.append(f"{run_id}: transcript digest mismatch")
            if operator_marker_data.get("transcript_sha256") != actual_sha:
                errors.append(f"{run_id}: operator marker transcript digest mismatch")
            observable_sha = sha256_file(evidence / "observable-artifacts.json")
            if (
                operator_marker_data.get("observable_artifacts_sha256")
                != observable_sha
                or metadata.get("observable_artifact_index_sha256")
                != observable_sha
            ):
                errors.append(
                    f"{run_id}: observable-artifact marker digest mismatch"
                )
            observable_index = load_json(evidence / "observable-artifacts.json")
            errors.extend(
                _verify_index_records(
                    observable_index.get("artifacts"),
                    base=evidence,
                    label=f"{run_id} observable artifacts",
                )
            )
            materialization_path = evidence / "materialization-complete.json"
            if not materialization_path.is_file():
                errors.append(f"{run_id}: materialization marker missing")
            else:
                materialization = load_json(materialization_path)
                before_inventory = (
                    evidence
                    / "observable"
                    / (
                        "installation-before"
                        if run["surface"] == "maude-installation"
                        else "repository-before"
                    )
                    / (
                        "state.json"
                        if run["surface"] == "maude-installation"
                        else "inventory.json"
                    )
                )
                if not before_inventory.is_file():
                    errors.append(
                        f"{run_id}: materialization before-inventory file missing"
                    )
                elif materialization.get(
                    "before_inventory_sha256"
                ) != sha256_file(before_inventory):
                    errors.append(
                        f"{run_id}: materialization before-inventory digest mismatch"
                    )
            supplied_record = metadata.get("supplied_input_manifest")
            if not isinstance(supplied_record, dict):
                errors.append(f"{run_id}: metadata supplied-input link absent")
            else:
                errors.extend(
                    _verify_index_records(
                        [supplied_record],
                        base=evidence,
                        label=f"{run_id} metadata supplied-input link",
                    )
                )
            session = metadata.get("provider_session_id") or metadata.get(
                "provider_thread_id"
            )
            if not session:
                errors.append(f"{run_id}: provider session/thread identity absent")
            elif session in operator_sessions:
                errors.append(f"{run_id}: duplicate operator session identity")
            else:
                operator_sessions.add(session)
            if not metadata.get("fresh_context_confirmed"):
                errors.append(f"{run_id}: fresh operator context not confirmed")
            if metadata.get("evaluator_interventions") != "none":
                errors.append(f"{run_id}: operator received evaluator intervention")
            frozen_inputs = load_json(
                PACKET_DIR / "rendered" / run_id / "supplied-inputs.json"
            )
            if sha256_file(
                PACKET_DIR / "rendered" / run_id / "operator-prompt.md"
            ) != frozen_inputs["user_prompt"]["sha256"]:
                errors.append(f"{run_id}: frozen user prompt digest changed")
            materialized_inputs = load_json(evidence / "supplied-inputs.json")
            actual_visible = {
                record["path"]: record
                for record in materialized_inputs["operator_visible_files"]
            }
            actual_repo = {
                f"../repo/{record['path']}": record
                for record in materialized_inputs["repository_files"]
            }
            expected_destinations = {
                item["destination"] for item in frozen_inputs["visible_files"]
            }
            actual_destinations = set(actual_visible) | set(actual_repo)
            if actual_destinations != expected_destinations:
                errors.append(
                    f"{run_id}: materialized input set differs from frozen set: "
                    f"unexpected={sorted(actual_destinations - expected_destinations)!r} "
                    f"missing={sorted(expected_destinations - actual_destinations)!r}"
                )
            for expected in frozen_inputs["visible_files"]:
                destination = expected["destination"]
                actual = (
                    actual_repo.get(destination)
                    if destination.startswith("../repo/")
                    else actual_visible.get(destination)
                )
                if actual is None:
                    errors.append(
                        f"{run_id}: supplied frozen input missing at {destination}"
                    )
                    continue
                if (
                    actual.get("bytes") != expected.get("bytes")
                    or actual.get("sha256") != expected.get("sha256")
                    or actual.get("media_type") != expected.get("media_type")
                ):
                    errors.append(
                        f"{run_id}: supplied input digest mismatch at {destination}"
                    )
            for prompt_name, frozen_key in (
                ("operator-system-prompt.md", "system_prompt"),
                ("operator-prompt.md", "user_prompt"),
            ):
                prompt_path = evidence / prompt_name
                expected_prompt = frozen_inputs[frozen_key]
                actual_prompt = file_record(prompt_path, relative_to=evidence)
                if (
                    actual_prompt["bytes"] != expected_prompt["bytes"]
                    or actual_prompt["sha256"] != expected_prompt["sha256"]
                    or actual_prompt["media_type"]
                    != expected_prompt["media_type"]
                ):
                    errors.append(
                        f"{run_id}: copied {prompt_name} differs from frozen prompt"
                    )
            retrospective_path = (
                evidence
                / "observable"
                / "retrospective"
                / "separation.json"
            )
            if not retrospective_path.is_file():
                errors.append(
                    f"{run_id}: retrospective separation evidence missing"
                )
                record["retrospective_separation_valid"] = None
                record["retrospective_evaluator_contamination"] = True
            else:
                retrospective = load_json(retrospective_path)
                valid = bool(retrospective.get("separation_valid"))
                contamination = bool(
                    retrospective.get("evaluator_contamination")
                )
                record["retrospective_separation_valid"] = valid
                record["retrospective_evaluator_contamination"] = (
                    contamination
                )
                if (
                    retrospective.get("schema")
                    != "maude.synthetic-operator.retrospective-separation.v1"
                    or retrospective.get("campaign_id") != CAMPAIGN_ID
                    or retrospective.get("run_id") != run_id
                    or retrospective.get("authority_effect") != "none"
                ):
                    errors.append(
                        f"{run_id}: retrospective separation identity invalid"
                    )
                if contamination == valid:
                    errors.append(
                        f"{run_id}: retrospective separation contamination "
                        "flag is inconsistent"
                    )
                disposition_record = retrospective.get(
                    "initial_disposition"
                )
                if disposition_record is not None:
                    errors.extend(
                        _verify_index_records(
                            [disposition_record],
                            base=evidence,
                            label=f"{run_id} initial disposition",
                        )
                    )
                if metadata.get("retrospective_separation") != retrospective:
                    errors.append(
                        f"{run_id}: metadata retrospective copy differs"
                    )
                if metadata.get("elapsed_interaction_steps") != (
                    retrospective.get(
                        "product_interface_action_count_excluding_evaluator_protocol"
                    )
                ):
                    errors.append(
                        f"{run_id}: elapsed interaction-step linkage mismatch"
                    )

            source_boundary_path = evidence / "source-grade-boundary.json"
            source_expected = run.get("source_visibility") in {
                "release-source",
                "installed-distribution",
            }
            if source_boundary_path.is_file() != source_expected:
                errors.append(
                    f"{run_id}: implementation-source boundary presence "
                    "differs from source visibility"
                )
            if source_boundary_path.is_file():
                source_boundary = load_json(source_boundary_path)
                record["source_evaluator_contamination"] = bool(
                    source_boundary.get("evaluator_contamination")
                )
                if (
                    source_boundary.get("schema")
                    != "maude.synthetic-installation.source-grade-boundary.v2"
                    or source_boundary.get("run_id") != run_id
                    or source_boundary.get("source_visibility")
                    != run.get("source_visibility")
                    or source_boundary.get("authority_effect") != "none"
                ):
                    errors.append(
                        f"{run_id}: implementation-source boundary identity invalid"
                    )
                errors.extend(
                    _verify_index_records(
                        [source_boundary.get("original_transcript")],
                        base=evidence,
                        label=f"{run_id} source-boundary original transcript",
                    )
                )
                redaction_required = bool(
                    source_boundary.get(
                        "grader_transcript_requires_redaction"
                    )
                )
                if redaction_required:
                    errors.extend(
                        _verify_index_records(
                            [
                                source_boundary.get("grader_transcript"),
                                source_boundary.get(
                                    "grader_numbered_transcript"
                                ),
                            ],
                            base=evidence,
                            label=f"{run_id} source-boundary grader copies",
                        )
                    )
                if (
                    bool(source_boundary.get("action_violations"))
                    and not (
                        redaction_required
                        and source_boundary.get(
                            "conservative_full_provider_content_withholding"
                        )
                        and source_boundary.get("evaluator_contamination")
                    )
                ):
                    errors.append(
                        f"{run_id}: source-inspection action did not force "
                        "conservative contaminated grader evidence"
                    )
            if run["surface"] == "maude-installation":
                before_state_path = (
                    evidence
                    / "observable"
                    / "installation-before"
                    / "state.json"
                )
                after_state_path = (
                    evidence
                    / "observable"
                    / "installation-after"
                    / "state.json"
                )
                endpoint_materialization_path = (
                    evidence / "raw" / "endpoint-materialization.json"
                )
                if not (
                    before_state_path.is_file()
                    and after_state_path.is_file()
                    and endpoint_materialization_path.is_file()
                ):
                    errors.append(
                        f"{run_id}: installation state evidence is incomplete"
                    )
                else:
                    before_state = load_json(before_state_path)
                    after_state = load_json(after_state_path)
                    endpoint_materialization = load_json(
                        endpoint_materialization_path
                    )
                    endpoint_before_path = (
                        evidence / "observable" / "endpoint-before.json"
                    )
                    endpoint_after_path = (
                        evidence / "observable" / "endpoint-after.json"
                    )
                    frozen_endpoint = (
                        PACKET_DIR
                        / "installation-endpoints"
                        / f"{run_id}.json"
                    )
                    endpoint_record = endpoint_materialization.get(
                        "endpoint_plan"
                    )
                    if (
                        not frozen_endpoint.is_file()
                        or not isinstance(endpoint_record, dict)
                        or endpoint_record.get("sha256")
                        != sha256_file(frozen_endpoint)
                    ):
                        errors.append(
                            f"{run_id}: endpoint-plan digest linkage mismatch"
                        )
                    active_endpoint = endpoint_materialization.get(
                        "mode"
                    ) not in {"none", "unavailable"}
                    if not (
                        endpoint_before_path.is_file()
                        and endpoint_after_path.is_file()
                    ):
                        errors.append(
                            f"{run_id}: endpoint before/after evidence missing"
                        )
                    else:
                        endpoint_before = load_json(endpoint_before_path)
                        endpoint_after = load_json(endpoint_after_path)
                        resolved_socket = endpoint_materialization.get(
                            "resolved_socket"
                        )
                        if bool(
                            endpoint_before.get("is_socket")
                        ) != active_endpoint or bool(
                            endpoint_after.get("is_socket")
                        ) != active_endpoint:
                            errors.append(
                                f"{run_id}: endpoint socket state differs "
                                "from frozen endpoint mode"
                            )
                        if (
                            endpoint_before.get("path") != resolved_socket
                            or endpoint_after.get("path") != resolved_socket
                        ):
                            errors.append(
                                f"{run_id}: endpoint evidence path differs "
                                "from frozen resolved socket"
                            )
                    after_sockets = after_state.get("run_tree", {}).get(
                        "sockets", []
                    )
                    if (
                        not isinstance(after_sockets, list)
                        or len(after_sockets) != int(active_endpoint)
                        or any(
                            not isinstance(socket, dict)
                            or not socket.get("allowlisted")
                            for socket in after_sockets
                        )
                    ):
                        errors.append(
                            f"{run_id}: captured run-tree socket set invalid"
                        )
                    installed_expected = (
                        run.get("source_visibility")
                        == "installed-distribution"
                    )
                    before_package = before_state.get("package_state", {})
                    if bool(
                        before_package.get("maude_entrypoint_exists")
                    ) != installed_expected:
                        errors.append(
                            f"{run_id}: initial installed-state evidence differs "
                            "from the frozen source-visibility contract"
                        )
                    setup_path = (
                        evidence / "raw" / "installation-setup.json"
                    )
                    if setup_path.is_file() != installed_expected:
                        errors.append(
                            f"{run_id}: installation materializer evidence "
                            "presence mismatch"
                        )
                    if run_id == "install-i10" and (
                        before_state.get("project_tree", {}).get("digest")
                        != after_state.get("project_tree", {}).get("digest")
                    ):
                        errors.append(
                            f"{run_id}: externally owned project/state tree changed"
                        )
                    if not (
                        (evidence / "clean-home-before.json").is_file()
                        and (evidence / "clean-home-after.json").is_file()
                    ):
                        errors.append(
                            f"{run_id}: clean HOME before/after evidence missing"
                        )
            personas.add(run["persona_id"])
            if run["surface"] == "maude":
                maude_personas.add(run["persona_id"])
                maude_scenarios.add(run["scenario_id"])
            elif run["surface"] == "maude-installation":
                installation_personas.add(run["persona_id"])
                installation_scenarios.add(run["scenario_id"])
                installation_coverage.update(run.get("coverage", []))
        elif require_complete:
            errors.append(f"{run_id}: operator evidence missing")
        if grade_marker.is_file():
            grade_metadata = load_json(evidence / "grade" / "metadata.json")
            _verify_action_files(
                label=f"{run_id} grader",
                transcript=(
                    evidence / "grade" / "raw" / "grader.stdout.jsonl"
                ),
                actions_path=evidence / "grade" / "commands-and-actions.json",
                accounting_path=evidence / "grade" / "action-accounting.json",
                errors=errors,
            )
            _verify_session_boundary(
                label=f"{run_id} grader",
                config_id=run["grader_model_config"],
                raw=evidence / "grade" / "raw",
                transcript=(
                    evidence / "grade" / "raw" / "grader.stdout.jsonl"
                ),
                metadata=grade_metadata,
                expected_tools=(
                    list(CLAUDE_GRADER_TOOLS)
                ),
                expected_mode="grader",
                errors=errors,
            )
            grade_marker_data = load_json(grade_marker)
            grade_session = grade_metadata.get(
                "provider_session_id"
            ) or grade_metadata.get("provider_thread_id")
            if not grade_session:
                errors.append(f"{run_id}: grader session/thread identity absent")
            else:
                pending_grader_sessions.append((run_id, grade_session))
            if not grade_metadata.get("fresh_context_confirmed"):
                errors.append(f"{run_id}: fresh grader context not confirmed")
            if grade_metadata.get("no_resume_or_continue") is not True:
                errors.append(
                    f"{run_id}: fresh grader no-resume policy not confirmed"
                )
            if (
                grade_metadata.get("operator_model_config")
                != run["operator_model_config"]
                or grade_metadata.get("grader_model_config")
                != run["grader_model_config"]
            ):
                errors.append(
                    f"{run_id}: configured grader/operator models differ"
                )
            expected_family_metadata = _grading_model_family_metadata(run)
            for field, expected in expected_family_metadata.items():
                if grade_metadata.get(field) != expected:
                    errors.append(
                        f"{run_id}: grader model-family metadata differs: "
                        f"{field}"
                    )
            try:
                grade_sha = sha256_file(evidence / "grade" / "grade.json")
                summary_sha = sha256_file(evidence / "summary.json")
                summary = load_json(evidence / "summary.json")
                grade_value = load_json(
                    evidence / "grade" / "grade.json"
                )
                if (
                    grade_marker_data.get("grade_sha256") != grade_sha
                    or grade_metadata.get("grade_sha256") != grade_sha
                    or summary.get("grade_sha256") != grade_sha
                ):
                    errors.append(f"{run_id}: grade digest linkage mismatch")
                if grade_marker_data.get("summary_sha256") != summary_sha:
                    errors.append(f"{run_id}: summary digest linkage mismatch")
                if summary.get("transcript_sha256") != sha256_file(
                    evidence / "transcript.jsonl"
                ):
                    errors.append(f"{run_id}: summary transcript linkage mismatch")
                for field in (
                    "scenario_verdict",
                    "final_disposition",
                    "task_completed",
                    "final_disposition_correct",
                    "measurements",
                    "findings",
                    "failure_classes",
                    "evidence_citations",
                    "severity",
                    "confidence",
                    "attribution",
                    "authority_and_refusal_understood",
                    "safety_relevant_errors",
                    "subjective_feedback",
                ):
                    if summary.get(field) != grade_value.get(field):
                        errors.append(
                            f"{run_id}: summary field differs from grade: {field}"
                        )
                if run["surface"] == "maude-installation":
                    for field in (
                        "installation_results",
                        "installation_findings",
                        "installation_verdict",
                        "recommended_installation_or_documentation_changes",
                    ):
                        if summary.get(field) != grade_value.get(field):
                            errors.append(
                                f"{run_id}: installation summary field "
                                f"differs from grade: {field}"
                            )
                elif summary.get("rubric_results") != grade_value.get(
                    "rubric_results"
                ):
                    errors.append(
                        f"{run_id}: summary rubric results differ from grade"
                    )
                if summary.get("elapsed_interaction_steps") != load_json(
                    evidence / "metadata.json"
                ).get("elapsed_interaction_steps"):
                    errors.append(
                        f"{run_id}: summary interaction-step linkage mismatch"
                    )
                preserved_bundle = evidence / "grade" / "grade-bundle"
                bundle_index_path = preserved_bundle / "bundle-inventory.json"
                if not bundle_index_path.is_file():
                    errors.append(f"{run_id}: preserved grade-bundle index missing")
                else:
                    bundle_index = load_json(bundle_index_path)
                    errors.extend(
                        _verify_index_records(
                            bundle_index.get("files"),
                            base=preserved_bundle,
                            label=f"{run_id} preserved grade bundle",
                        )
                    )
                    expected_bundle_paths = {
                        item.get("path")
                        for item in bundle_index.get("files", [])
                        if isinstance(item, dict)
                    }
                    actual_bundle_paths = {
                        item["path"]
                        for item in inventory_files(preserved_bundle)
                        if item["path"] != "bundle-inventory.json"
                    }
                    if actual_bundle_paths != expected_bundle_paths:
                        errors.append(
                            f"{run_id}: preserved grade-bundle file set changed"
                        )
                    top_level_bundle_index = (
                        evidence / "grade" / "grade-bundle-inventory.json"
                    )
                    if (
                        not top_level_bundle_index.is_file()
                        or sha256_file(top_level_bundle_index)
                        != sha256_file(bundle_index_path)
                    ):
                        errors.append(
                            f"{run_id}: grade-bundle inventory copy mismatch"
                        )
                    bundle_record = grade_metadata.get("grade_bundle_manifest")
                    if not isinstance(bundle_record, dict):
                        errors.append(
                            f"{run_id}: grade metadata bundle linkage absent"
                        )
                    else:
                        errors.extend(
                            _verify_index_records(
                                [bundle_record],
                                base=evidence / "grade",
                                label=f"{run_id} grade metadata bundle link",
                            )
                        )
                    evaluator_contamination = bool(
                        bundle_index.get("evaluator_contamination")
                    )
                    if evaluator_contamination and (
                        "evaluator contamination"
                        not in grade_value.get("failure_classes", [])
                        or not any(
                            finding.get("failure_class")
                            == "evaluator contamination"
                            for finding in grade_value.get("findings", [])
                            if isinstance(finding, dict)
                        )
                    ):
                        errors.append(
                            f"{run_id}: evidence-cited evaluator contamination "
                            "finding absent from grade"
                        )
                    if (
                        bundle_index.get(
                            "source_evaluator_contamination"
                        )
                        and grade_value.get("scenario_verdict")
                        != "indeterminate"
                    ):
                        errors.append(
                            f"{run_id}: source-contaminated grade is not "
                            "indeterminate"
                        )
                    if retrospective is not None and (
                        bool(
                            bundle_index.get(
                                "retrospective_evaluator_contamination"
                            )
                        )
                        != bool(
                            retrospective.get("evaluator_contamination")
                        )
                    ):
                        errors.append(
                            f"{run_id}: grade-bundle retrospective "
                            "contamination linkage mismatch"
                        )
                failure_classes = grade_value.get("failure_classes")
                if (
                    not isinstance(failure_classes, list)
                    or not all(
                        isinstance(value, str) for value in failure_classes
                    )
                    or len(failure_classes) != len(set(failure_classes))
                ):
                    errors.append(
                        f"{run_id}: grade failure_classes are not unique strings"
                    )
                jsonschema.validate(
                    grade_value,
                    load_json(
                        PACKET_DIR
                        / (
                            "installation-grader-output.schema.json"
                            if run["surface"] == "maude-installation"
                            else "grader-output.schema.json"
                        )
                    ),
                )
            except jsonschema.ValidationError as exc:
                errors.append(f"{run_id}: invalid grade JSON: {exc.message}")
        elif require_complete:
            errors.append(f"{run_id}: independent grade missing")
        results.append(record)
    failed_operator_root = CAMPAIGN_DIR / "failed-operator-attempts"
    if failed_operator_root.is_dir():
        for retry_record_path in sorted(
            failed_operator_root.glob("*/*/retry-record.json")
        ):
            failed_operator_attempts += 1
            retry_record = load_json(retry_record_path)
            attempt = retry_record_path.parent
            if (
                retry_record.get("schema")
                != "maude.synthetic-operator.failed-operator-attempt.v1"
                or retry_record.get("campaign_operator_session_counted")
                is not False
                or retry_record.get("authority_effect") != "none"
            ):
                errors.append(
                    "invalid failed-operator-attempt retry record: "
                    f"{retry_record_path}"
                )
            transcript = attempt / "transcript.jsonl"
            if transcript.is_file():
                run_id = str(retry_record.get("run_id") or "")
                configured = declared.get(run_id, {}).get(
                    "operator_model_config",
                    "openai-sol",
                )
                identity = _session_identity(
                    _provider_events(transcript),
                    configured,
                )
                if identity.get("provider_session_id") or identity.get(
                    "provider_thread_id"
                ):
                    errors.append(
                        f"{run_id}: failed pre-session attempt contains a "
                        "session/thread identity"
                    )
    for run_id, run in declared.items():
        failed_grade_root = (
            _run_dir(run_id) / "failed-grade-attempts"
        )
        if not failed_grade_root.is_dir():
            continue
        for retry_record_path in sorted(
            failed_grade_root.glob("*/retry-record.json")
        ):
            failed_grader_attempts += 1
            retry_record = load_json(retry_record_path)
            attempt = retry_record_path.parent
            if (
                retry_record.get("schema")
                != "maude.synthetic-operator.failed-grade-attempt.v1"
                or retry_record.get("prior_evidence_overwritten") is not False
                or retry_record.get("authority_effect") != "none"
            ):
                errors.append(
                    f"{run_id}: invalid failed-grader-attempt retry record"
                )
            transcript = (
                attempt / "grade" / "raw" / "grader.stdout.jsonl"
            )
            if not transcript.is_file():
                continue
            identity = _session_identity(
                _provider_events(transcript),
                run["grader_model_config"],
            )
            session = identity.get(
                "provider_session_id"
            ) or identity.get("provider_thread_id")
            if not session:
                continue
            if (
                session in failed_grader_sessions
                or session in operator_sessions
            ):
                errors.append(
                    f"{run_id}: failed grader session identity was reused"
                )
            else:
                failed_grader_sessions.add(session)
    for run_id, grade_session in pending_grader_sessions:
        if (
            grade_session in grader_sessions
            or grade_session in failed_grader_sessions
            or grade_session in operator_sessions
        ):
            errors.append(f"{run_id}: grader session identity was reused")
        else:
            grader_sessions.add(grade_session)
    if require_complete:
        if len(maude_scenarios) != 20:
            errors.append(
                f"required Maude scenario coverage is {len(maude_scenarios)}/20"
            )
        required_personas = {
            run["persona_id"]
            for run in manifest["runs"]
            if run["surface"] == "maude"
        }
        if maude_personas != required_personas:
            errors.append("required Maude persona coverage is incomplete")
        required_installation_scenarios = {
            run["scenario_id"]
            for run in manifest["runs"]
            if run["surface"] == "maude-installation"
        }
        if (
            len(installation_scenarios) != 10
            or installation_scenarios != required_installation_scenarios
        ):
            errors.append(
                "required installation scenario coverage is incomplete"
            )
        required_installation_personas = {
            run["persona_id"]
            for run in manifest["runs"]
            if run["surface"] == "maude-installation"
        }
        if installation_personas != required_installation_personas:
            errors.append(
                "required installation persona coverage is incomplete"
            )
        required_installation_coverage = {
            category
            for run in manifest["runs"]
            if run["surface"] == "maude-installation"
            for category in run.get("coverage", [])
        }
        if installation_coverage != required_installation_coverage:
            errors.append(
                "required installation condition coverage is incomplete"
            )
    report = {
        "schema": "maude.synthetic-operator.evidence-verification.v1",
        "campaign_id": CAMPAIGN_ID,
        "require_complete": require_complete,
        "ok": not errors,
        "errors": errors,
        "runs": results,
        "operator_session_identities": len(operator_sessions),
        "grader_session_identities": len(grader_sessions),
        "failed_operator_attempts_preserved": failed_operator_attempts,
        "failed_grader_attempts_preserved": failed_grader_attempts,
        "failed_grader_session_identities": len(failed_grader_sessions),
        "maude_scenarios_covered": len(maude_scenarios),
        "installation_scenarios_covered": len(installation_scenarios),
        "installation_conditions_covered": sorted(installation_coverage),
        "maude_personas_covered": sorted(maude_personas),
        "installation_personas_covered": sorted(installation_personas),
        "personas_covered": sorted(personas),
        "authority_effect": "none",
    }
    write_json(CAMPAIGN_DIR / "evidence-verification.json", report)
    if require_complete and report["ok"]:
        coverage = {
            "schema": "maude.synthetic-operator.coverage-summary.v1",
            "campaign_id": CAMPAIGN_ID,
            "declared_runs": len(declared),
            "completed_operator_runs": sum(
                1 for item in results if item["operator_complete"]
            ),
            "completed_independent_grades": sum(
                1 for item in results if item["grade_complete"]
            ),
            "maude_scenarios": len(maude_scenarios),
            "direct_runtime_controls": sum(
                1
                for item in results
                if item["surface"] == "docket-gwr-direct"
            ),
            "installation_scenarios": len(installation_scenarios),
            "installation_conditions": sorted(installation_coverage),
            "maude_personas": sorted(maude_personas),
            "installation_personas": sorted(installation_personas),
            "personas": sorted(personas),
            "surfaces": sorted({item["surface"] for item in results}),
            "operator_model_configs": {
                name: sum(
                    1
                    for run in declared.values()
                    if run["operator_model_config"] == name
                )
                for name in sorted(
                    {run["operator_model_config"] for run in declared.values()}
                )
            },
            "grader_model_configs": {
                name: sum(
                    1
                    for run in declared.values()
                    if run["grader_model_config"] == name
                )
                for name in sorted(
                    {run["grader_model_config"] for run in declared.values()}
                )
            },
            "operator_session_identities": len(operator_sessions),
            "grader_session_identities": len(grader_sessions),
            "failed_operator_attempts_preserved": failed_operator_attempts,
            "failed_grader_attempts_preserved": failed_grader_attempts,
            "failed_grader_session_identities": len(
                failed_grader_sessions
            ),
            "coached_runs": 0,
            "authority_effect": "none",
        }
        write_json(CAMPAIGN_DIR / "coverage-summary.json", coverage)
        inventory_paths = [
            path
            for path in sorted(CAMPAIGN_DIR.rglob("*"))
            if path.is_file()
            and PACKET_DIR not in path.parents
            and path != CAMPAIGN_DIR / "evidence-inventory.json"
        ]
        write_json(
            CAMPAIGN_DIR / "evidence-inventory.json",
            {
                "schema": "maude.synthetic-operator.evidence-inventory.v1",
                "campaign_id": CAMPAIGN_ID,
                "self_exclusion": (
                    "evidence-inventory.json is excluded to avoid a recursive digest"
                ),
                "packet_excluded": True,
                "external_tmp_or_provider_home_material_included": False,
                "committable_evaluator_diagnostic_raw_included": True,
                "artifacts": [
                    file_record(path, relative_to=CAMPAIGN_DIR)
                    for path in inventory_paths
                ],
                "authority_effect": "none",
            },
        )
    return report


def _run_parallel(
    operation,
    runs: list[dict[str, Any]],
    *,
    jobs: int,
) -> list[dict[str, Any]]:
    if jobs < 1 or jobs > 8:
        raise CampaignError("--jobs must be between 1 and 8")
    results: list[dict[str, Any]] = []
    failures: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as executor:
        futures = {executor.submit(operation, run): run for run in runs}
        for future in concurrent.futures.as_completed(futures):
            run = futures[future]
            try:
                result = future.result()
                results.append(result)
                print(json.dumps(result, sort_keys=True), flush=True)
            except Exception as exc:
                failures.append(f"{run['run_id']}: {type(exc).__name__}: {exc}")
                print(
                    json.dumps(
                        {
                            "run_id": run["run_id"],
                            "status": "error",
                            "error": str(exc),
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )
    if failures:
        raise CampaignError("campaign stage failures:\n" + "\n".join(failures))
    return sorted(results, key=lambda item: item["run_id"])


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run and independently grade the frozen synthetic operator campaign"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    auth_probe_parser = subparsers.add_parser("probe-auth-gate")
    installation_probe_parser = subparsers.add_parser(
        "probe-installation-surface"
    )
    configured_probe_providers = _configured_campaign_providers()
    for probe_parser in (auth_probe_parser, installation_probe_parser):
        probe_parser.add_argument(
            "--provider",
            action="append",
            dest="providers",
            choices=configured_probe_providers,
            help=(
                "provider configuration declared by the frozen matrix; "
                "repeat only when the matrix declares multiple providers "
                "(default: "
                + ", ".join(configured_probe_providers)
                + ")"
            ),
        )
    subparsers.add_parser("validate")
    materialize_parser = subparsers.add_parser("materialize")
    operator_parser = subparsers.add_parser("operators")
    grader_parser = subparsers.add_parser("graders")
    all_parser = subparsers.add_parser("all")
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--allow-incomplete", action="store_true")

    for command_parser in (
        materialize_parser,
        operator_parser,
        grader_parser,
        all_parser,
    ):
        command_parser.add_argument("--run", action="append", dest="runs")
        command_parser.add_argument("--jobs", type=int, default=2)
        command_parser.add_argument("--dry-run", action="store_true")
    for command_parser in (operator_parser, grader_parser, all_parser):
        command_parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    args = parser.parse_args()

    try:
        if args.command == "probe-auth-gate":
            print(
                json.dumps(
                    run_auth_gate_probes(args.providers),
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        if args.command == "probe-installation-surface":
            print(
                json.dumps(
                    run_installation_surface_probes(args.providers),
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        manifest = _validate_or_raise()
        if args.command == "validate":
            print(
                json.dumps(
                    {
                        "ok": True,
                        "campaign_id": CAMPAIGN_ID,
                        "runs": len(manifest["runs"]),
                        "frozen_artifacts": len(manifest_artifact_map(manifest)),
                        "manifest_sha256": sha256_file(MANIFEST_PATH),
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        if args.command == "verify":
            report = verify_evidence(
                manifest, require_complete=not args.allow_incomplete
            )
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0 if report["ok"] else 1

        runs = selected_runs(args.runs)
        if args.command == "materialize":
            if args.dry_run:
                print(
                    json.dumps(
                        {
                            "would_materialize": [run["run_id"] for run in runs],
                            "labs": [
                                str(_lab_dir(run["run_id"])) for run in runs
                            ],
                        },
                        indent=2,
                    )
                )
                return 0
            _run_parallel(
                lambda run: materialize_run(run, manifest),
                runs,
                jobs=args.jobs,
            )
            return 0
        if args.timeout < 60 or args.timeout > 3600:
            raise CampaignError("--timeout must be between 60 and 3600 seconds")
        if args.command in {"operators", "all"}:
            _run_parallel(
                lambda run: run_operator(
                    run,
                    manifest,
                    timeout=args.timeout,
                    dry_run=args.dry_run,
                ),
                runs,
                jobs=args.jobs,
            )
        if args.command in {"graders", "all"}:
            _run_parallel(
                lambda run: run_grader(
                    run,
                    timeout=args.timeout,
                    dry_run=args.dry_run,
                ),
                runs,
                jobs=args.jobs,
            )
        if not args.dry_run:
            report = verify_evidence(
                manifest, require_complete=not bool(args.runs)
            )
            if not report["ok"]:
                raise CampaignError(
                    "post-stage evidence verification failed:\n"
                    + "\n".join(report["errors"])
                )
        return 0
    except (
        CampaignError,
        OSError,
        KeyError,
        ValueError,
        jsonschema.ValidationError,
    ) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
