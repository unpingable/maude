#!/usr/bin/env python3
"""Plan or explicitly run the existing synthetic-cache governed test.

Default mode is a read-only plan. ``--run`` creates one fresh root below /tmp,
generates C1/C2 artifacts with the checked-in builders, then invokes the
existing ignored Nightshift integration target. It never performs broad cleanup.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


def args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Plan/run the existing synthetic-cache tutorial producer"
    )
    p.add_argument(
        "--run",
        action="store_true",
        help="execute builders and the ignored Nightshift test",
    )
    p.add_argument(
        "--run-root", type=Path, required=True, help="absent, fresh root below /tmp"
    )
    p.add_argument("--maude-checkout", type=Path, required=True)
    p.add_argument("--nightshift-checkout", type=Path, required=True)
    p.add_argument("--ag-checkout", type=Path, required=True)
    p.add_argument("--docket-checkout", type=Path, required=True)
    p.add_argument("--ag-loopctl", type=Path, required=True)
    p.add_argument("--ag-standing-resolver", type=Path, required=True)
    p.add_argument("--ag-effectd", type=Path, required=True)
    p.add_argument("--docket-bin", type=Path, required=True)
    p.add_argument("--docker-program", type=Path, required=True)
    p.add_argument("--maude-python", type=Path, required=True)
    p.add_argument("--input-lock", type=Path, required=True)
    return p.parse_args()


def load(path: Path) -> dict:
    value = json.loads(path.read_bytes())
    if value.get("schema") != "constellation.synthetic-cache-tutorial-input-lock/v1":
        raise SystemExit("unsupported input lock schema")
    return value


def command(parts: list[str], env: dict[str, str], cwd: Path | None = None) -> None:
    print("+", " ".join(parts))
    subprocess.run(parts, check=True, env=env, cwd=cwd)


def main() -> int:
    a = args()
    root = a.run_root.resolve()
    lock = load(a.input_lock.resolve())
    if not root.is_absolute() or not str(root).startswith("/tmp/"):
        raise SystemExit("run root must be an absolute path below /tmp")
    if root.exists():
        raise SystemExit(f"run root must be absent and exclusive: {root}")
    artifacts = root / "artifacts"
    runtime_root = root / "runtime"
    runtime = runtime_root / "maude-cache-birthday"
    c2_runtime = runtime_root / "maude-cache-birthday-c2"
    governed = root / "governed"
    image = lock["runtime"].get("image")
    print(
        json.dumps(
            {
                "mode": "run" if a.run else "plan",
                "run_root": str(root),
                "artifacts": str(artifacts),
                "governed_root": str(governed),
                "runtime_workspace": str(runtime),
                "c2_runtime_workspace": str(c2_runtime),
                "image": image,
                "fixture_status": lock.get("status"),
            },
            indent=2,
        )
    )
    preflight = [
        sys.executable,
        str(a.maude_checkout / "scripts/check-constellation-tutorial.py"),
        "--maude-checkout",
        str(a.maude_checkout),
        "--nightshift-checkout",
        str(a.nightshift_checkout),
        "--ag-checkout",
        str(a.ag_checkout),
        "--docket-checkout",
        str(a.docket_checkout),
        "--artifact-root",
        str(artifacts),
        "--artifact-mode",
        "generate",
        "--workspace-root",
        str(runtime.parent),
        "--ag-loopctl",
        str(a.ag_loopctl),
        "--ag-standing-resolver",
        str(a.ag_standing_resolver),
        "--ag-effectd",
        str(a.ag_effectd),
        "--docket-bin",
        str(a.docket_bin),
        "--executor",
        str(
            a.maude_checkout / "qualification/synthetic_cache/local_compose_executor.py"
        ),
        "--docker-program",
        str(a.docker_program),
        "--image",
        image or "python:3.13-alpine",
        "--maude-revision",
        lock["source"]["maude_revision"],
        "--nightshift-revision",
        lock["source"]["nightshift_revision"],
        "--ag-revision",
        lock["source"]["ag_revision"],
        "--docket-revision",
        lock["source"]["docket_revision"],
    ]
    checked = subprocess.run(preflight, check=False)
    if not a.run:
        print(
            "Plan only: no directory, artifact, container, or test process was created."
        )
        return checked.returncode
    if checked.returncode:
        raise SystemExit("preflight reported blockers; refusing --run")
    if not isinstance(image, str) or "@sha256:" not in image:
        raise SystemExit(
            "input lock has no pinned image digest; resolve distribution before --run"
        )
    digest = "sha256:" + hashlib.sha256(a.docker_program.read_bytes()).hexdigest()
    if digest != lock["runtime"]["docker_program_identity"]:
        raise SystemExit("Docker program bytes differ from input lock")
    version = (
        subprocess.run(
            [
                str(a.docker_program),
                "version",
                "--format",
                "{{.Client.Version}} {{.Server.Version}}",
            ],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        )
        .stdout.strip()
        .split()
    )
    if version != [
        lock["runtime"]["docker_client_version"],
        lock["runtime"]["docker_server_version"],
    ]:
        raise SystemExit("Docker client/server versions differ from input lock")
    compose = (
        subprocess.run(
            [str(a.docker_program), "compose", "version", "--short"],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        )
        .stdout.strip()
        .removeprefix("v")
    )
    if compose != lock["runtime"]["compose_version"]:
        raise SystemExit("Docker Compose version differs from input lock")
    root.mkdir(mode=0o700)
    identity = lock["identity"]
    rt = lock["runtime"]
    env = dict(
        os.environ,
        PYTHONPATH=str(a.maude_checkout / "src"),
        MAUDE_SRC=str(a.maude_checkout / "src"),
        MAUDE_PYTHON=str(a.maude_python),
    )
    base = [
        str(a.maude_python),
        str(a.maude_checkout / "qualification/synthetic_cache/build_plan.py"),
        "--output-root",
        str(artifacts),
        "--runtime-root",
        str(runtime_root),
        "--runtime-workspace",
        str(runtime),
        "--front-port",
        str(rt["front_port"]),
        "--image",
        image,
        "--docker-program",
        str(a.docker_program),
        "--docker-program-identity",
        digest,
        "--docker-client-version",
        rt["docker_client_version"],
        "--docker-server-version",
        rt["docker_server_version"],
        "--compose-version",
        rt["compose_version"],
    ]
    for key in (
        "campaign_id",
        "program_id",
        "subject_digest",
        "scope_digest",
        "qualify_occurrence_id",
        "teardown_occurrence_id",
        "qualify_observation_id",
        "teardown_observation_id",
    ):
        base += ["--" + key.replace("_", "-"), identity[key]]
    command(base, env)
    c2 = [
        str(a.maude_python),
        str(
            a.maude_checkout / "qualification/synthetic_cache/build_requalification.py"
        ),
        "--plan-root",
        str(artifacts),
        "--runtime-workspace",
        str(c2_runtime),
        "--base-compiler-input",
        str(artifacts / "compiler-input-qualify.json"),
    ]
    for key in ("campaign_id", "program_id", "subject_digest", "scope_digest"):
        c2 += ["--" + key.replace("_", "-"), identity[key]]
    for key in (
        "qualify_occurrence_id",
        "qualify_observation_id",
        "teardown_occurrence_id",
        "teardown_observation_id",
    ):
        c2 += ["--" + key.replace("_", "-"), identity["c2_" + key]]
    command(c2, env)
    test_env = dict(
        env,
        AG_LOOPCTL_BIN=str(a.ag_loopctl),
        AG_STANDING_RESOLVER_BIN=str(a.ag_standing_resolver),
        AG_EFFECTD_BIN=str(a.ag_effectd),
        AG_DOCKET_BIN=str(a.docket_bin),
        SYNTHETIC_CACHE_GOVERNED_ROOT=str(governed),
        SYNTHETIC_CACHE_EXECUTOR=str(
            a.maude_checkout / "qualification/synthetic_cache/local_compose_executor.py"
        ),
    )
    for name, filename in lock["artifact_environment"].items():
        test_env[name] = str(artifacts / filename)
    command(
        [
            "cargo",
            "test",
            "-p",
            "nightshiftd",
            "--test",
            "ag_governed_integration",
            "synthetic_cache_design_qualifies_and_tears_down_through_governed_runtime",
            "--",
            "--ignored",
        ],
        test_env,
        a.nightshift_checkout,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
