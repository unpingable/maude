#!/usr/bin/env python3
"""Read-only prerequisite check for the synthetic-cache tutorial baseline.

This program never creates a workspace, starts a container, contacts a network
endpoint, installs a package, or invokes a producer.  It only checks the exact
inputs consumed by Nightshift's ignored governed integration qualification.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Finding:
    level: str
    subject: str
    detail: str


REQUIRED_ARTIFACTS: dict[str, tuple[str, str | None]] = {
    "C1 locked plan": ("plan-locked.json", "maude.plan-document/v1"),
    "C1 qualify executor plan": ("executor-plan-qualify.json", None),
    "C1 teardown executor plan": ("executor-plan-teardown.json", None),
    "C1 qualify handoff": (
        "handoff-qualify.json",
        "nightshift.precompiled_workflow_proposal.v2",
    ),
    "C1 teardown handoff": (
        "handoff-teardown.json",
        "nightshift.precompiled_workflow_proposal.v2",
    ),
    "C1 qualify compilation receipt": ("compilation-receipt-qualify.json", None),
    "C2 locked plan": ("plan-c2-locked.json", "maude.plan-document/v1"),
    "C2 qualify executor plan": ("executor-plan-c2-qualify.json", None),
    "C2 teardown executor plan": ("executor-plan-c2-teardown.json", None),
    "C2 qualify handoff": (
        "handoff-c2-qualify.json",
        "nightshift.precompiled_workflow_proposal.v2",
    ),
    "C2 teardown handoff": (
        "handoff-c2-teardown.json",
        "nightshift.precompiled_workflow_proposal.v2",
    ),
    "C2 qualify compilation receipt": (
        "compilation-receipt-c2-qualify.json",
        None,
    ),
}


def absolute_path(value: Path, label: str, findings: list[Finding]) -> Path | None:
    """Resolve only an explicitly absolute CLI pathname."""
    if not value.is_absolute():
        findings.append(Finding("BLOCK", label, "path must be absolute"))
        return None
    # Preserve executable symlinks: resolving a venv Python or /snap/bin/docker
    # can select a different runtime. Workspace containment is checked separately.
    return value


def docker_environment(endpoint: str) -> dict[str, str] | None:
    """Return the sole supported local Docker binding, or reject it."""
    prefix = "unix://"
    socket = endpoint.removeprefix(prefix)
    if (
        not endpoint.startswith(prefix)
        or not socket.startswith("/")
        or socket == "/"
        or any(character.isspace() for character in endpoint)
        or "?" in endpoint
        or "#" in endpoint
    ):
        return None
    env = dict(os.environ)
    env.pop("DOCKER_CONTEXT", None)
    env["DOCKER_HOST"] = endpoint
    return env


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only preflight for the synthetic-cache governed tutorial; "
            "it does not launch the producer."
        )
    )
    parser.add_argument("--maude-checkout", type=Path, required=True)
    parser.add_argument("--nightshift-checkout", type=Path, required=True)
    parser.add_argument("--ag-checkout", type=Path, required=True)
    parser.add_argument("--docket-checkout", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument(
        "--artifact-mode",
        choices=("consume", "generate"),
        default="consume",
        help="consume checks an existing C1/C2 bundle; generate permits an absent fresh output root",
    )
    parser.add_argument(
        "--workspace-root",
        type=Path,
        required=True,
        help="planned disposable runtime root; checked but never created",
    )
    parser.add_argument("--ag-loopctl", type=Path, required=True)
    parser.add_argument("--ag-standing-resolver", type=Path, required=True)
    parser.add_argument("--ag-effectd", type=Path, required=True)
    parser.add_argument("--docket-bin", type=Path, required=True)
    parser.add_argument("--executor", type=Path, required=True)
    parser.add_argument("--docker-program", type=Path, required=True)
    parser.add_argument(
        "--docker-endpoint",
        required=True,
        help="required local Unix socket binding, for example unix:///run/user/1000/docker.sock",
    )
    parser.add_argument("--image", default="python:3.13-alpine")
    parser.add_argument("--maude-revision")
    parser.add_argument("--nightshift-revision")
    parser.add_argument("--ag-revision")
    parser.add_argument("--docket-revision")
    parser.add_argument("--json", action="store_true", help="emit JSON findings")
    return parser.parse_args()


def command(
    args: list[str], timeout: int = 10, env: dict[str, str] | None = None
) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            args,
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)
    return completed.returncode, completed.stdout.strip()


def checkout(
    findings: list[Finding],
    label: str,
    path: Path,
    required: tuple[str, ...],
    expected: str | None,
    env: dict[str, str],
) -> None:
    if not path.is_absolute():
        findings.append(Finding("BLOCK", label, "checkout path must be absolute"))
        return
    if not path.is_dir():
        findings.append(Finding("BLOCK", label, f"missing checkout: {path}"))
        return
    for relative in required:
        if not (path / relative).is_file():
            findings.append(
                Finding("BLOCK", label, f"missing required source: {relative}")
            )
    code, head = command(["git", "-C", str(path), "rev-parse", "HEAD"], env=env)
    if code:
        findings.append(Finding("BLOCK", label, f"cannot read Git revision: {head}"))
        return
    code, dirty = command(["git", "-C", str(path), "status", "--porcelain"], env=env)
    if code:
        findings.append(Finding("BLOCK", label, f"cannot read Git status: {dirty}"))
    elif dirty:
        findings.append(Finding("BLOCK", label, f"checkout is dirty at {head}"))
    else:
        findings.append(Finding("OK", label, f"revision {head}"))
    if expected and head != expected:
        findings.append(
            Finding("BLOCK", label, f"revision {head} differs from required {expected}")
        )
    elif not expected:
        findings.append(
            Finding(
                "WARN",
                label,
                "no expected revision supplied; identity is recorded but not pinned",
            )
        )


def executable(findings: list[Finding], label: str, path: Path) -> None:
    if not path.is_absolute():
        findings.append(Finding("BLOCK", label, "binary path must be absolute"))
    elif not path.is_file():
        findings.append(Finding("BLOCK", label, f"missing file: {path}"))
    elif not os.access(path, os.X_OK):
        findings.append(Finding("BLOCK", label, f"not executable: {path}"))
    else:
        findings.append(Finding("OK", label, str(path)))


def artifacts(findings: list[Finding], root: Path, mode: str) -> None:
    if not root.is_absolute():
        findings.append(Finding("BLOCK", "artifact root", "path must be absolute"))
        return
    if mode == "generate" and os.path.lexists(root):
        findings.append(Finding("BLOCK", "artifact root", f"must be absent: {root}"))
        return
    if not root.is_dir() and mode == "generate":
        findings.append(
            Finding("OK", "artifact root", f"fresh generator output will be: {root}")
        )
        return
    if not root.is_dir():
        findings.append(Finding("BLOCK", "artifact root", f"missing: {root}"))
        return
    for label, (name, schema) in REQUIRED_ARTIFACTS.items():
        path = root / name
        if not path.is_file():
            findings.append(Finding("BLOCK", label, f"missing artifact: {path}"))
            continue
        try:
            value: Any = json.loads(path.read_bytes())
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            findings.append(Finding("BLOCK", label, f"not readable JSON: {exc}"))
            continue
        if not isinstance(value, dict):
            findings.append(Finding("BLOCK", label, "artifact must be a JSON object"))
        elif schema and value.get("schema") != schema:
            findings.append(
                Finding(
                    "BLOCK",
                    label,
                    f"expected schema {schema!r}, got {value.get('schema')!r}",
                )
            )
        else:
            findings.append(Finding("OK", label, path.name))


def workspace(findings: list[Finding], root: Path, mode: str) -> None:
    if not root.is_absolute():
        findings.append(Finding("BLOCK", "workspace root", "path must be absolute"))
        return
    parent = root.parent
    if not parent.is_dir() and mode == "generate" and root.parent.parent.is_dir():
        findings.append(
            Finding(
                "OK", "workspace root", f"fresh generator workspace will be: {root}"
            )
        )
    elif not parent.is_dir():
        findings.append(
            Finding("BLOCK", "workspace root", f"parent does not exist: {parent}")
        )
    elif os.path.lexists(root):
        findings.append(
            Finding(
                "BLOCK",
                "workspace root",
                f"already exists; a fresh governed root is required: {root}",
            )
        )
    else:
        findings.append(Finding("OK", "workspace root", f"candidate is absent: {root}"))
    snap_root = Path("/home/jbeck/snap/docker/common/ag-synthetic-cache")
    if (
        Path("/tmp") not in root.resolve().parents
        and root.resolve() != snap_root
        and snap_root not in root.resolve().parents
    ):
        findings.append(
            Finding(
                "BLOCK",
                "workspace root",
                "must be below /tmp or the qualified Snap Docker campaign root",
            )
        )


def docker_runtime(
    findings: list[Finding], program: Path, image: str, env: dict[str, str] | None
) -> None:
    if env is None:
        findings.append(
            Finding(
                "BLOCK", "Docker endpoint", "must be a unix:// absolute local socket"
            )
        )
        return
    executable(findings, "Docker program", program)
    if not program.is_file() or not os.access(program, os.X_OK):
        return
    code, version = command(
        [
            str(program),
            "version",
            "--format",
            "{{.Client.Version}} {{.Server.Version}}",
        ],
        env=env,
    )
    if code:
        findings.append(
            Finding(
                "BLOCK",
                "Docker daemon",
                f"cannot read client/server version: {version}",
            )
        )
    else:
        findings.append(Finding("OK", "Docker daemon", version))
    code, identity = command(
        [str(program), "image", "inspect", image, "--format", "{{.Id}}"], env=env
    )
    if code:
        findings.append(
            Finding("BLOCK", "container image", f"cannot verify {image}: {identity}")
        )
    else:
        findings.append(Finding("OK", "container image", f"{image} {identity}"))


def report(findings: list[Finding], as_json: bool) -> int:
    if as_json:
        print(json.dumps([item.__dict__ for item in findings], indent=2))
    else:
        for item in findings:
            print(f"{item.level:5} {item.subject}: {item.detail}")
        print(
            "\nSubstitution fixtures: the governed qualification uses a deterministic local NQ admission port, test standing issuer, and a controlled Docket execution-standing resolver. They exercise serialized contracts; they do not install NQ-NG or a production standing service."
        )
        print(
            "\nResult: this check never launches the connected producer. BLOCK findings mean its exact inputs are incomplete."
        )
    return 1 if any(item.level == "BLOCK" for item in findings) else 0


def main() -> int:
    args = arguments()
    findings: list[Finding] = []
    docker_env = docker_environment(args.docker_endpoint)
    if docker_env is None:
        findings.append(
            Finding(
                "BLOCK", "Docker endpoint", "must be a unix:// absolute local socket"
            )
        )
        return report(findings, args.json)
    maude_checkout = absolute_path(args.maude_checkout, "Maude", findings)
    nightshift_checkout = absolute_path(
        args.nightshift_checkout, "Nightshift", findings
    )
    ag_checkout = absolute_path(args.ag_checkout, "Constellation AG", findings)
    docket_checkout = absolute_path(args.docket_checkout, "Docket", findings)
    artifact_root = absolute_path(args.artifact_root, "artifact root", findings)
    workspace_root = absolute_path(args.workspace_root, "workspace root", findings)
    ag_loopctl = absolute_path(args.ag_loopctl, "AG loop control", findings)
    ag_standing_resolver = absolute_path(
        args.ag_standing_resolver, "AG standing resolver", findings
    )
    ag_effectd = absolute_path(args.ag_effectd, "AG effect dispatcher", findings)
    docket_bin = absolute_path(args.docket_bin, "Docket executable", findings)
    executor = absolute_path(args.executor, "synthetic-cache executor", findings)
    docker_program = absolute_path(args.docker_program, "Docker program", findings)
    if None in (
        maude_checkout,
        nightshift_checkout,
        ag_checkout,
        docket_checkout,
        artifact_root,
        workspace_root,
        ag_loopctl,
        ag_standing_resolver,
        ag_effectd,
        docket_bin,
        executor,
        docker_program,
    ):
        return report(findings, args.json)
    checkout(
        findings,
        "Maude",
        maude_checkout,
        (
            "pyproject.toml",
            "qualification/synthetic_cache/build_plan.py",
            "qualification/synthetic_cache/build_requalification.py",
            "qualification/synthetic_cache/local_compose_executor.py",
            "qualification/synthetic_cache/seal_cycle_handoff.py",
            "scripts/check-synthetic-cache-boundaries.sh",
        ),
        args.maude_revision,
        docker_env,
    )
    checkout(
        findings,
        "Nightshift",
        nightshift_checkout,
        (
            "Cargo.toml",
            "crates/nightshiftd/tests/ag_governed_integration.rs",
        ),
        args.nightshift_revision,
        docker_env,
    )
    checkout(
        findings,
        "Constellation AG",
        ag_checkout,
        ("Cargo.toml",),
        args.ag_revision,
        docker_env,
    )
    checkout(
        findings,
        "Docket",
        docket_checkout,
        ("Cargo.toml",),
        args.docket_revision,
        docker_env,
    )
    artifacts(findings, artifact_root, args.artifact_mode)
    workspace(findings, workspace_root, args.artifact_mode)
    executable(findings, "AG loop control", ag_loopctl)
    executable(findings, "AG standing resolver", ag_standing_resolver)
    executable(findings, "AG effect dispatcher", ag_effectd)
    executable(findings, "Docket executable", docket_bin)
    executable(findings, "synthetic-cache executor", executor)
    docker_runtime(findings, docker_program, args.image, docker_env)
    return report(findings, args.json)


if __name__ == "__main__":
    raise SystemExit(main())
