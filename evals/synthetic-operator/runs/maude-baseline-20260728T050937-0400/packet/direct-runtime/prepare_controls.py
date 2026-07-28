#!/usr/bin/env python3
"""Build frozen, local-only Docket/GWR comparison fixtures.

This script is campaign preparation infrastructure. It operates only beneath
the fixed synthetic /tmp prefix and the campaign packet's direct-runtime
fixture directory. It never contacts a network or a non-synthetic repository.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any


CAMPAIGN_ID = "maude-baseline-20260728T050937-0400"
DOCKET_COMMIT = "9050a53cd8a4741d71f5334f90eb22dac52eeb62"
CONTROL_SCHEMA = "maude.synthetic-docket-control.v1"
INDEX_SCHEMA = "maude.synthetic-docket-controls-index.v1"
PACKET = Path(__file__).resolve().parent
REPO_ROOT = Path(__file__).resolve().parents[6]
SCENARIOS = REPO_ROOT / "evals" / "synthetic-operator" / "scenarios"
LAB_PREFIX = Path(f"/tmp/maude-synth-{CAMPAIGN_ID}")
FIXTURE_OUTPUT = PACKET / "fixtures"
DOCKET = PACKET / "bin" / "docket"
BROKER = PACKET / "bin" / "gwr-git-broker"
# Keep the frozen synthetic controls usable throughout packet review and the
# campaign without relying on Docket's one-hour defaults.
CONTROL_TTL_MS = 2_592_000_000  # 30 days

CONTROLS = {
    "docket-s01": {
        "scenario_id": "s01-kubernetes-image-update",
        "task_id": "ux-task-01",
        "actor": "operator-ux-task-01",
        "allowed_paths": ["clusters/store-17/apps/menu/deployment.yaml"],
        "setup_state": "prepared",
    },
    "docket-s11": {
        "scenario_id": "s11-description-scope-mismatch",
        "task_id": "ux-task-11",
        "actor": "operator-ux-task-11",
        "allowed_paths": [
            "apps/menu/deployment.yaml",
            "apps/payments/deployment.yaml",
        ],
        "setup_state": "prepared",
    },
    "docket-s15": {
        "scenario_id": "s15-runtime-refusal-before-dispatch",
        "task_id": "ux-task-15",
        "actor": "operator-ux-task-15",
        "grant_actor": "operator-unassigned",
        "allowed_paths": ["deploy/worker.yaml"],
        "setup_state": "prepared",
    },
    "docket-s17": {
        "scenario_id": "s17-client-daemon-restart",
        "task_id": "ux-task-17",
        "actor": "operator-ux-task-17",
        "allowed_paths": ["config/proxy.yaml"],
        "setup_state": "reserved",
    },
    "docket-s20": {
        "scenario_id": "s20-terminal-unknown",
        "task_id": "ux-task-20",
        "actor": "operator-ux-task-20",
        "allowed_paths": ["deploy/api.yaml"],
        "setup_state": "indeterminate",
    },
}


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True).encode("utf-8")
        + b"\n"
    )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(
    argv: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    transcript: list[dict[str, Any]] | None = None,
    expected: int = 0,
) -> str:
    completed = subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    record = {
        "argv": argv,
        "cwd": str(cwd) if cwd else None,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
    if transcript is not None:
        transcript.append(record)
    if completed.returncode != expected:
        raise RuntimeError(
            f"command returned {completed.returncode}, expected {expected}: {argv!r}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed.stdout


def _field(text: str, name: str) -> str:
    match = re.search(rf"(?m)^{re.escape(name)}:\s*(\S+)\s*$", text)
    if not match:
        raise RuntimeError(f"missing {name!r} in output:\n{text}")
    return match.group(1)


def _initialize_repo(
    run_root: Path, scenario: Path, transcript: list[dict[str, Any]]
) -> tuple[Path, str]:
    repo = run_root / "repo"
    shutil.copytree(scenario / "fixture", repo)
    _run(
        ["git", "init", "-q", "--initial-branch=main"], cwd=repo, transcript=transcript
    )
    _run(
        ["git", "config", "user.name", "Synthetic Operator Lab"],
        cwd=repo,
        transcript=transcript,
    )
    _run(
        ["git", "config", "user.email", "synthetic-operator@example.invalid"],
        cwd=repo,
        transcript=transcript,
    )
    _run(["git", "add", "-A"], cwd=repo, transcript=transcript)
    _run(
        ["git", "commit", "-q", "-m", "synthetic base fixture"],
        cwd=repo,
        transcript=transcript,
    )
    basis = _run(["git", "rev-parse", "HEAD"], cwd=repo, transcript=transcript).strip()
    _run(
        ["git", "update-ref", "refs/gwr/target", basis], cwd=repo, transcript=transcript
    )
    return repo, basis


def _docket(
    args: list[str],
    *,
    transcript: list[dict[str, Any]],
    env: dict[str, str] | None = None,
) -> str:
    return _run([str(DOCKET), *args], transcript=transcript, env=env)


def _prepare_one(run_id: str, spec: dict[str, Any]) -> dict[str, Any]:
    run_root = LAB_PREFIX / run_id
    expected_root = (LAB_PREFIX / run_id).resolve()
    if run_root.resolve() != expected_root or LAB_PREFIX not in expected_root.parents:
        raise RuntimeError(f"refusing unsafe synthetic root: {run_root}")
    if run_root.exists():
        shutil.rmtree(run_root)
    run_root.mkdir(parents=True)

    transcript: list[dict[str, Any]] = []
    scenario = SCENARIOS / spec["scenario_id"]
    repo, basis = _initialize_repo(run_root, scenario, transcript)
    state = run_root / "state"
    patch = run_root / "candidate.patch"
    shutil.copyfile(scenario / "patch.diff", patch)

    number = int(run_id.rsplit("s", 1)[1])
    repository_id = f"repo-{number:032x}"
    target_ref = "refs/gwr/target"
    packet = json.loads((scenario / "packet.json").read_text(encoding="utf-8"))
    goal = packet["description"]

    _docket(
        [
            "repository",
            "register",
            "--state",
            str(state),
            "--repository-id",
            repository_id,
            "--repo",
            str(repo),
        ],
        transcript=transcript,
    )
    request_out = _docket(
        [
            "request",
            "create",
            "--state",
            str(state),
            "--repository-id",
            repository_id,
            "--repo",
            str(repo),
            "--target-ref",
            target_ref,
            "--goal",
            goal,
        ],
        transcript=transcript,
    )
    work_request = _field(request_out, "work_request")
    prepare_out = _docket(
        [
            "prepare",
            "start",
            "--state",
            str(state),
            "--request",
            work_request,
            "--basis",
            basis,
            "--fake-patch",
            str(patch),
        ],
        transcript=transcript,
    )
    candidate = _field(prepare_out, "candidate")
    candidate_digest = _field(prepare_out, "candidate_digest")
    admit_argv = [
        "candidate",
        "admit",
        "--state",
        str(state),
        "--request",
        work_request,
        "--candidate",
        candidate,
        "--basis",
        basis,
    ]
    for allowed_path in spec["allowed_paths"]:
        admit_argv.extend(["--allow", allowed_path])
    admit_argv.extend(["--observe", "git diff --check HEAD^ HEAD"])
    admit_out = _docket(admit_argv, transcript=transcript)
    attempt = _field(admit_out, "attempt")
    prepared_digest = _field(admit_out, "prepared_attempt_digest")
    grant_actor = spec.get("grant_actor", spec["actor"])
    grant_out = _docket(
        [
            "grant",
            "standing",
            "--state",
            str(state),
            "--attempt",
            attempt,
            "--actor",
            grant_actor,
            "--ttl-ms",
            str(CONTROL_TTL_MS),
        ],
        transcript=transcript,
    )
    standing_grant = _field(grant_out, "grant")
    standing_token = _field(grant_out, "token")

    control = {
        "schema": CONTROL_SCHEMA,
        "campaign_id": CAMPAIGN_ID,
        "run_id": run_id,
        "task_id": spec["task_id"],
        "surface": "Docket/GWR direct CLI",
        "docket_commit": DOCKET_COMMIT,
        "dossier_format": "gwr:attempt-dossier:v3",
        "state_path": str(state),
        "repository_path": str(repo),
        "repository_id": repository_id,
        "target_ref": target_ref,
        "basis_commit": basis,
        "work_request_id": work_request,
        "candidate_id": candidate,
        "candidate_digest": candidate_digest,
        "attempt_id": attempt,
        "prepared_attempt_digest": prepared_digest,
        "standing_grant_id": standing_grant,
        "standing_token": standing_token,
        "standing_actor": grant_actor,
        "standing_ttl_ms": CONTROL_TTL_MS,
        "assigned_actor": spec["actor"],
        "allowed_paths": spec["allowed_paths"],
        "candidate_patch": "candidate.patch",
        "setup_state": spec["setup_state"],
        "setup_reservation_ttl_ms": (
            CONTROL_TTL_MS
            if spec["setup_state"] in {"reserved", "indeterminate"}
            else None
        ),
        "authority_effect": "synthetic fixture only; none outside this disposable lab",
    }

    if spec["setup_state"] in {"reserved", "indeterminate"}:
        _docket(
            [
                "ratify",
                "--state",
                str(state),
                "--attempt",
                attempt,
                "--token",
                standing_token,
                "--actor",
                spec["actor"],
                "--digest",
                prepared_digest,
                "--basis",
                basis,
            ],
            transcript=transcript,
        )
        _docket(
            [
                "reserve",
                "--state",
                str(state),
                "--attempt",
                attempt,
                "--ttl-ms",
                str(CONTROL_TTL_MS),
            ],
            transcript=transcript,
        )

    if spec["setup_state"] == "indeterminate":
        dispatch_env = os.environ.copy()
        dispatch_env["GWR_BROKER_BIN"] = str(BROKER)
        dispatch_env["GWR_BROKER_CRASH_AFTER"] = "ref_updated"
        dispatch_out = _docket(
            ["dispatch", "--state", str(state), "--attempt", attempt],
            transcript=transcript,
            env=dispatch_env,
        )
        if "outcome: indeterminate" not in dispatch_out:
            raise RuntimeError(f"expected indeterminate dispatch, got:\n{dispatch_out}")
        control["setup_dispatch_output"] = dispatch_out.strip()

    show_out = _docket(
        ["docket", "show", "--state", str(state), "--attempt", attempt, "--json"],
        transcript=transcript,
    )
    control["initial_dossier_sha256"] = hashlib.sha256(show_out.encode()).hexdigest()
    if spec["setup_state"] == "indeterminate":
        dossier = json.loads(show_out)
        if (
            dossier.get("state") != "indeterminate"
            or dossier.get("settlement") != "unresolved"
        ):
            raise RuntimeError(
                "indeterminate control did not retain indeterminate state"
            )

    (run_root / "control.json").write_bytes(_json_bytes(control))
    with (run_root / "setup-transcript.jsonl").open("wb") as handle:
        for record in transcript:
            handle.write(
                json.dumps(record, ensure_ascii=False, sort_keys=True).encode("utf-8")
                + b"\n"
            )

    FIXTURE_OUTPUT.mkdir(parents=True, exist_ok=True)
    archive = FIXTURE_OUTPUT / f"{run_id}.tar"
    if archive.exists():
        archive.unlink()
    with tarfile.open(archive, "w", format=tarfile.PAX_FORMAT) as tar:
        for path in sorted(run_root.rglob("*")):
            arcname = Path(run_id) / path.relative_to(run_root)
            tar.add(path, arcname=str(arcname), recursive=False)
    control["archive"] = str(archive.relative_to(REPO_ROOT))
    control["archive_bytes"] = archive.stat().st_size
    control["archive_sha256"] = _sha(archive)
    metadata_path = FIXTURE_OUTPUT / f"{run_id}.json"
    metadata_path.write_bytes(_json_bytes(control))
    return control


def _recursive_key_present(value: Any, key: str) -> bool:
    if isinstance(value, dict):
        return key in value or any(
            _recursive_key_present(child, key) for child in value.values()
        )
    if isinstance(value, list):
        return any(_recursive_key_present(child, key) for child in value)
    return False


def _forbidden_operator_labels() -> tuple[bytes, ...]:
    labels: list[bytes] = []
    for spec in CONTROLS.values():
        scenario_id = spec["scenario_id"]
        labels.extend(
            [
                scenario_id.encode("ascii"),
                scenario_id.split("-", 1)[1].encode("ascii"),
            ]
        )
    return tuple(labels)


def _validate_archive_members(
    archive: tarfile.TarFile,
    *,
    run_id: str,
) -> list[tarfile.TarInfo]:
    members = archive.getmembers()
    seen: set[str] = set()
    forbidden = _forbidden_operator_labels()
    for member in members:
        path = PurePosixPath(member.name)
        if (
            path.is_absolute()
            or not path.parts
            or path.parts[0] != run_id
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise RuntimeError(f"unsafe archive member in {run_id}: {member.name!r}")
        if member.name in seen:
            raise RuntimeError(f"duplicate archive member in {run_id}: {member.name!r}")
        seen.add(member.name)
        if not (member.isfile() or member.isdir()):
            raise RuntimeError(
                f"unsupported archive member type in {run_id}: {member.name!r}"
            )
        lowered_name = member.name.lower().encode("utf-8")
        if any(label in lowered_name for label in forbidden):
            raise RuntimeError(
                f"descriptive scenario label leaked into archive path: {member.name!r}"
            )

    required = {
        f"{run_id}/control.json",
        f"{run_id}/setup-transcript.jsonl",
        f"{run_id}/candidate.patch",
        f"{run_id}/repo",
        f"{run_id}/state",
    }
    missing = required - seen
    if missing:
        raise RuntimeError(f"archive {run_id} is missing members: {sorted(missing)!r}")
    return members


def _validate_archive_bytes(
    archive: tarfile.TarFile,
    *,
    run_id: str,
    members: list[tarfile.TarInfo],
) -> None:
    forbidden = (b'"scenario_id"', *_forbidden_operator_labels())
    for member in members:
        if not member.isfile():
            continue
        extracted = archive.extractfile(member)
        if extracted is None:
            raise RuntimeError(f"cannot read archive member: {member.name!r}")
        contents = extracted.read().lower()
        if any(label in contents for label in forbidden):
            raise RuntimeError(
                f"descriptive scenario label leaked into archive: {member.name!r}"
            )


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def _expected_dossier_state(setup_state: str) -> tuple[str, str]:
    expected = {
        "prepared": ("prepared", "not_dispatched"),
        "reserved": ("reserved", "not_dispatched"),
        "indeterminate": ("indeterminate", "unresolved"),
    }
    try:
        return expected[setup_state]
    except KeyError as error:
        raise RuntimeError(f"unsupported setup state: {setup_state!r}") from error


def _validate_extracted_control(
    *,
    extracted_root: Path,
    metadata: dict[str, Any],
    spec: dict[str, Any],
) -> dict[str, Any]:
    run_id = metadata["run_id"]
    run_root = extracted_root / run_id
    internal_control = _load_json(run_root / "control.json")
    expected_internal = {
        key: value
        for key, value in metadata.items()
        if key not in {"archive", "archive_bytes", "archive_sha256"}
    }
    if internal_control != expected_internal:
        raise RuntimeError(f"internal and external controls differ for {run_id}")

    transcript_path = run_root / "setup-transcript.jsonl"
    transcript_records = [
        json.loads(line)
        for line in transcript_path.read_text(encoding="utf-8").splitlines()
    ]
    if not transcript_records or any(
        not isinstance(record, dict) for record in transcript_records
    ):
        raise RuntimeError(f"invalid setup transcript for {run_id}")

    patch = run_root / "candidate.patch"
    source_patch = SCENARIOS / spec["scenario_id"] / "patch.diff"
    if patch.read_bytes() != source_patch.read_bytes():
        raise RuntimeError(f"candidate patch differs from frozen source for {run_id}")

    repo = run_root / "repo"
    basis = metadata["basis_commit"]
    if _run(["git", "-C", str(repo), "rev-parse", "HEAD"]).strip() != basis:
        raise RuntimeError(f"repository HEAD differs from basis for {run_id}")
    target = _run(["git", "-C", str(repo), "rev-parse", metadata["target_ref"]]).strip()
    if metadata["setup_state"] == "indeterminate":
        if target == basis:
            raise RuntimeError(f"indeterminate target did not move for {run_id}")
    elif target != basis:
        raise RuntimeError(f"undispatched target moved for {run_id}")
    if _run(["git", "-C", str(repo), "status", "--porcelain"]):
        raise RuntimeError(f"repository worktree is not clean for {run_id}")
    _run(["git", "-C", str(repo), "apply", "--check", str(patch)])

    state = run_root / "state"
    show_out = _run(
        [
            str(DOCKET),
            "docket",
            "show",
            "--state",
            str(state),
            "--attempt",
            metadata["attempt_id"],
            "--json",
        ]
    )
    if (
        hashlib.sha256(show_out.encode()).hexdigest()
        != metadata["initial_dossier_sha256"]
    ):
        raise RuntimeError(f"initial dossier digest differs for {run_id}")
    dossier = json.loads(show_out)
    state_expected, settlement_expected = _expected_dossier_state(
        metadata["setup_state"]
    )
    identity = dossier.get("identity", {})
    if (
        dossier.get("dossier_format") != metadata["dossier_format"]
        or dossier.get("attempt") != metadata["attempt_id"]
        or dossier.get("state") != state_expected
        or dossier.get("settlement") != settlement_expected
        or identity.get("repository_id") != metadata["repository_id"]
        or identity.get("target_ref") != metadata["target_ref"]
        or identity.get("basis") != basis
        or identity.get("candidate") != metadata["candidate_id"]
        or identity.get("candidate_digest") != metadata["candidate_digest"]
        or identity.get("prepared_attempt_digest")
        != metadata["prepared_attempt_digest"]
        or identity.get("allowed_paths") != metadata["allowed_paths"]
    ):
        raise RuntimeError(f"dossier fields differ from control for {run_id}")
    return {
        "run_id": run_id,
        "task_id": metadata["task_id"],
        "archive_bytes": metadata["archive_bytes"],
        "archive_sha256": metadata["archive_sha256"],
        "dossier_state": dossier["state"],
        "settlement": dossier["settlement"],
        "target_moved": target != basis,
    }


def _validate_one(run_id: str, spec: dict[str, Any]) -> dict[str, Any]:
    metadata_path = FIXTURE_OUTPUT / f"{run_id}.json"
    archive_path = FIXTURE_OUTPUT / f"{run_id}.tar"
    metadata = _load_json(metadata_path)
    if (
        metadata.get("schema") != CONTROL_SCHEMA
        or metadata.get("campaign_id") != CAMPAIGN_ID
        or metadata.get("docket_commit") != DOCKET_COMMIT
        or metadata.get("run_id") != run_id
        or metadata.get("task_id") != spec["task_id"]
        or metadata.get("assigned_actor") != spec["actor"]
        or metadata.get("allowed_paths") != spec["allowed_paths"]
        or metadata.get("setup_state") != spec["setup_state"]
        or metadata.get("archive") != str(archive_path.relative_to(REPO_ROOT))
        or metadata.get("archive_bytes") != archive_path.stat().st_size
        or metadata.get("archive_sha256") != _sha(archive_path)
    ):
        raise RuntimeError(f"control metadata mismatch for {run_id}")
    if _recursive_key_present(metadata, "scenario_id"):
        raise RuntimeError(f"scenario_id leaked into operator control for {run_id}")
    metadata_bytes = _json_bytes(metadata).lower()
    if any(label in metadata_bytes for label in _forbidden_operator_labels()):
        raise RuntimeError(f"descriptive scenario label leaked into {run_id} metadata")

    with tarfile.open(archive_path, "r") as archive:
        members = _validate_archive_members(archive, run_id=run_id)
        _validate_archive_bytes(archive, run_id=run_id, members=members)
        with tempfile.TemporaryDirectory(prefix=f"validate-{run_id}-") as temp_dir:
            extracted_root = Path(temp_dir)
            archive.extractall(
                path=extracted_root,
                members=members,
                filter="data",
            )
            return _validate_extracted_control(
                extracted_root=extracted_root,
                metadata=metadata,
                spec=spec,
            )


def _validate_all() -> dict[str, Any]:
    expected_files = {
        "index.json",
        *{f"{run_id}.json" for run_id in CONTROLS},
        *{f"{run_id}.tar" for run_id in CONTROLS},
    }
    actual_files = {path.name for path in FIXTURE_OUTPUT.iterdir() if path.is_file()}
    if actual_files != expected_files:
        raise RuntimeError(
            "direct fixture file set differs: "
            f"expected={sorted(expected_files)!r}, actual={sorted(actual_files)!r}"
        )
    controls = [_load_json(FIXTURE_OUTPUT / f"{run_id}.json") for run_id in CONTROLS]
    index = _load_json(FIXTURE_OUTPUT / "index.json")
    if index != {
        "schema": INDEX_SCHEMA,
        "campaign_id": CAMPAIGN_ID,
        "docket_commit": DOCKET_COMMIT,
        "controls": controls,
    }:
        raise RuntimeError("direct fixture index does not match individual controls")
    results = [_validate_one(run_id, spec) for run_id, spec in CONTROLS.items()]
    return {
        "schema": "maude.synthetic-docket-controls-validation.v1",
        "campaign_id": CAMPAIGN_ID,
        "status": "pass",
        "controls_validated": len(results),
        "checks": [
            "neutral operator-visible task identities",
            "metadata/index agreement",
            "archive byte length and SHA-256",
            "safe unique archive paths and member types",
            "no descriptive scenario labels in archive paths or bytes",
            "internal/external control agreement",
            "exact candidate patch linkage",
            "clean repository and expected target-ref state",
            "frozen Docket dossier state and digest",
        ],
        "controls": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument(
        "--prepare", action="store_true", help="materialize all controls"
    )
    action.add_argument(
        "--validate",
        action="store_true",
        help="validate frozen controls without modifying them",
    )
    args = parser.parse_args()
    if not DOCKET.is_file() or not BROKER.is_file():
        raise SystemExit("frozen Docket binaries are missing")
    if args.prepare:
        results = [_prepare_one(run_id, spec) for run_id, spec in CONTROLS.items()]
        output = {
            "schema": INDEX_SCHEMA,
            "campaign_id": CAMPAIGN_ID,
            "docket_commit": DOCKET_COMMIT,
            "controls": results,
        }
        (FIXTURE_OUTPUT / "index.json").write_bytes(_json_bytes(output))
    else:
        output = _validate_all()
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
