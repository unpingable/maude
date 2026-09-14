#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Compile one explicit cache action from a caller-supplied accepted-plan bundle.

This helper performs no container, provider, network, AG, Docket, or Nightshift
operation. It snapshots the accepted Plan Core store for qualification and
mutates only that snapshot when recording action-specific compilation custody.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys

MAX_JSON = 32 * 1024
MAX_STORE = 64 * 1024 * 1024
MAX_SOURCE = 2 * 1024 * 1024
MAX_PROGRAM = 128 * 1024 * 1024
BUNDLE_SCHEMA = "maude.accepted-cache-plan-bundle/v1"
CONTEXT_SCHEMA = "maude.connected-cache-run-context/v1"
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


def read_regular(path: Path, limit: int) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        metadata = os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > limit:
            raise ValueError("input is not a bounded regular file")
        raw = stream.read(limit + 1)
    if not raw or len(raw) > limit:
        raise ValueError("input is empty or exceeds its bound")
    return raw


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def require_pin(raw: bytes, expected: str, label: str) -> None:
    if len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
        raise ValueError(f"{label} pin is not lowercase SHA-256")
    if sha256(raw) != expected:
        raise ValueError(f"{label} bytes differ from the supplied pin")


def write_new(path: Path, raw: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def is_pin(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(character in "0123456789abcdef" for character in value))


def require_absolute(value: Path | None, label: str) -> Path:
    if value is None or not value.is_absolute():
        raise ValueError(f"{label} path must be absolute")
    return value


def require_existing_file_pin(path: Path, expected: object, label: str,
                              maximum: int = MAX_PROGRAM) -> bytes:
    if not is_pin(expected):
        raise ValueError(f"{label} pin is not lowercase SHA-256")
    raw = read_regular(path, maximum)
    require_pin(raw, expected, label)
    return raw


def load_plan_core(source: Path):
    sys.path.insert(0, str(source / "src"))
    from maude.plan.document import canonical_json_bytes
    from maude.plan.store import DraftStore
    return canonical_json_bytes, DraftStore


def load_bundle(raw: bytes) -> dict:
    bundle = json.loads(raw)
    if set(bundle) != {"acceptance_ref", "draft_id", "lock_id", "plan_digest", "schema"}:
        raise ValueError("accepted bundle fields differ")
    # The established bundle contract carries an opaque caller reference.  A
    # DraftStore contains locks and revisions, not proposal dispositions, so it
    # cannot authenticate a human acceptance from this field.
    if bundle["schema"] != BUNDLE_SCHEMA or not bundle["acceptance_ref"]:
        raise ValueError("accepted bundle schema or reference differs")
    return bundle


def locked_document(store, bundle: dict):
    lock = next((item for item in store.locks(bundle["draft_id"])
                 if item.lock_id == bundle["lock_id"]), None)
    if lock is None or lock.plan_digest != bundle["plan_digest"]:
        raise ValueError("accepted lock is absent or has a different plan digest")
    document = store.revision(lock.revision_id).document
    if document.digest != bundle["plan_digest"]:
        raise ValueError("accepted document identity differs")
    return lock, document


def snapshot_store(source: Path, destination: Path, expected_sha: str) -> None:
    for suffix in ("-wal", "-shm"):
        if Path(str(source) + suffix).exists():
            raise ValueError("accepted store has a writable SQLite sidecar")
    raw = read_regular(source, MAX_STORE)
    require_pin(raw, expected_sha, "accepted store")
    if destination.exists():
        raise FileExistsError(destination)
    source_uri = f"file:{source}?mode=ro&immutable=1"
    with sqlite3.connect(source_uri, uri=True) as original, sqlite3.connect(destination) as copy:
        original.backup(copy)
    os.chmod(destination, 0o600)


def compile_action(args: argparse.Namespace) -> None:
    if args.prepare_input:
        prepare_compiler_input(args)
        return
    for path, label in ((args.maude_source, "Maude source"),
                        (args.accepted_store, "accepted store"),
                        (args.bundle, "accepted bundle"),
                        (args.compiler_input, "compiler input")):
        require_absolute(path, label)
    for value, label in ((args.maude_local_compose_sha256, "Maude compiler source"),
                         (args.accepted_store_sha256, "accepted store"),
                         (args.bundle_sha256, "accepted bundle"),
                         (args.compiler_input_sha256, "compiler input")):
        if value is None:
            raise ValueError(f"{label} pin is required")
    if args.output.exists():
        raise FileExistsError(args.output)

    bundle_raw = read_regular(args.bundle, MAX_JSON)
    input_raw = read_regular(args.compiler_input, MAX_JSON)
    compiler_source = read_regular(
        args.maude_source / "src" / "maude" / "plan" / "local_compose.py",
        MAX_SOURCE,
    )
    require_pin(bundle_raw, args.bundle_sha256, "accepted bundle")
    require_pin(input_raw, args.compiler_input_sha256, "compiler input")
    require_pin(compiler_source, args.maude_local_compose_sha256, "Maude compiler source")
    bundle = load_bundle(bundle_raw)

    args.output.mkdir(mode=0o700, parents=False)
    store_copy = args.output / "accepted-plan.sqlite"
    snapshot_store(args.accepted_store, store_copy, args.accepted_store_sha256)

    canonical_json_bytes, DraftStore = load_plan_core(args.maude_source)
    from maude.plan.local_compose import (
        LocalComposeWorkflowCompilerV1,
        LocalComposeWorkflowInputsV1,
        NodeActionV1,
        ag_executor_plan_identity,
        executor_plan_from_handoff,
    )

    raw = json.loads(input_raw)
    raw["node_actions"] = tuple(NodeActionV1(**item) for item in raw["node_actions"])
    inputs = LocalComposeWorkflowInputsV1(**raw)
    if inputs.action != args.action:
        raise ValueError("compiler input action differs from requested action")
    store = DraftStore(store_copy)
    lock, document = locked_document(store, bundle)
    result = LocalComposeWorkflowCompilerV1().compile(document, inputs)
    executor = executor_plan_from_handoff(result.handoff_bytes)
    work = ag_executor_plan_identity(executor)
    receipt = store.record_compilation(bundle["draft_id"], lock.lock_id, result,
                                       compiler_inputs=inputs.canonical_bytes,
                                       exact_work_identity=work)
    write_new(args.output / f"compiler-input-{args.action}.json", inputs.canonical_bytes)
    write_new(args.output / f"handoff-{args.action}.json", result.handoff_bytes)
    write_new(args.output / f"executor-plan-{args.action}.json", canonical_json_bytes(executor))
    write_new(args.output / f"compilation-receipt-{args.action}.json",
              canonical_json_bytes(receipt.to_data()))
    write_new(args.output / "plan-locked.json", canonical_json_bytes(document.to_data()))


def context_fields(raw: bytes) -> dict:
    context = json.loads(raw)
    if not isinstance(context, dict) or context.get("schema") != CONTEXT_SCHEMA:
        raise ValueError("unsupported prepared connected-cache context")
    required = {"files", "identities", "nq", "programs", "runtime"}
    if not required <= set(context):
        raise ValueError("prepared context lacks compiler coordinates")
    return context


def exact_coordinate(value: object, label: str) -> tuple[Path, str]:
    if (not isinstance(value, dict) or set(value) != {"path", "sha256"}
            or not isinstance(value["path"], str) or not is_pin(value["sha256"])):
        raise ValueError(f"{label} coordinate differs")
    return require_absolute(Path(value["path"]), label), value["sha256"]


def actual_nq_observation(raw: bytes, context: dict) -> tuple[dict, str]:
    artifact = json.loads(raw)
    if not isinstance(artifact, dict) or artifact.get("schema") != "nq.diagnostic_execution.v2":
        raise ValueError("NQ observation is not diagnostic execution v2")
    if artifact.get("profile", {}).get("id") != "nq.host" or \
            artifact.get("question", {}).get("id") != "nq.host.load_pressure":
        raise ValueError("NQ observation is not the enrolled host/load profile")
    artifact_id = artifact.get("artifact_id")
    if not isinstance(artifact_id, str) or not _DIGEST.fullmatch(artifact_id):
        raise ValueError("NQ observation has no exact artifact identity")
    subject = artifact.get("subject")
    if not isinstance(subject, dict) or subject.get("id") != context["nq"].get("subject") \
            or subject.get("scope", {}).get("digest") != context["identities"].get("scope_digest"):
        raise ValueError("NQ observation subject or scope differs from prepared context")
    if artifact.get("outcome", {}).get("condition") not in {"present", "explicitly_absent"}:
        raise ValueError("NQ observation is not determinate")
    # This is the established posture-construction identity law in
    # cache-host-bootstrap.py. It binds one compiler input to these retained NQ
    # artifact bytes without creating a Nightshift request or cycle.
    return artifact, "sha256:" + hashlib.sha256(canonical({"artifact_id": artifact_id})).hexdigest()


def prepare_compiler_input(args: argparse.Namespace) -> None:
    for path, label in ((args.context, "prepared context"),
                        (args.accepted_store, "accepted store"),
                        (args.bundle, "accepted bundle"),
                        (args.nq_observation, "NQ observation")):
        require_absolute(path, label)
    for value, label in ((args.context_sha256, "prepared context"),
                         (args.accepted_store_sha256, "accepted store"),
                         (args.bundle_sha256, "accepted bundle"),
                         (args.nq_observation_sha256, "NQ observation"),
                         (args.maude_local_compose_sha256, "Maude compiler source")):
        if not is_pin(value):
            raise ValueError(f"{label} pin is not lowercase SHA-256")
    if args.output.exists():
        raise FileExistsError(args.output)

    context_raw = read_regular(args.context, MAX_JSON)
    bundle_raw = read_regular(args.bundle, MAX_JSON)
    observation_raw = read_regular(args.nq_observation, MAX_JSON)
    require_pin(context_raw, args.context_sha256, "prepared context")
    require_pin(bundle_raw, args.bundle_sha256, "accepted bundle")
    require_pin(observation_raw, args.nq_observation_sha256, "NQ observation")
    context = context_fields(context_raw)
    bundle = load_bundle(bundle_raw)

    files, programs, runtime, identities = (context["files"], context["programs"],
                                              context["runtime"], context["identities"])
    source = require_absolute(Path(files.get("maude_source", {}).get("path", "")), "Maude source")
    build_plan_path, build_plan_pin = exact_coordinate(files.get("maude_build_plan"), "Maude build-plan")
    docker_path, docker_pin = exact_coordinate(programs.get("docker"), "Docker")
    compiler_source = source / "src" / "maude" / "plan" / "local_compose.py"
    require_existing_file_pin(build_plan_path, build_plan_pin, "Maude build-plan", MAX_SOURCE)
    require_existing_file_pin(compiler_source, args.maude_local_compose_sha256,
                              "Maude compiler source", MAX_SOURCE)
    require_existing_file_pin(docker_path, docker_pin, "Docker")
    if not isinstance(runtime, dict) or not isinstance(identities, dict) or not isinstance(context["nq"], dict):
        raise ValueError("prepared context compiler fields differ")
    required_runtime = {"workspace", "project", "front_port", "image", "docker_client_version",
                        "docker_server_version", "compose_version"}
    required_identities = {"campaign_id", "program_id", "scope_digest", "subject_digest",
                           "qualification_occurrence_id", "successor_occurrence_id"}
    if not required_runtime <= set(runtime) or not required_identities <= set(identities):
        raise ValueError("prepared context lacks exact compiler inputs")
    for name in ("campaign_id", "program_id", "scope_digest", "subject_digest"):
        if not isinstance(identities[name], str) or not _DIGEST.fullmatch(identities[name]):
            raise ValueError("prepared context content identity differs")

    _, observation_id = actual_nq_observation(observation_raw, context)
    canonical_json_bytes, DraftStore = load_plan_core(source)
    sys.path.insert(0, str(source / "qualification" / "synthetic_cache"))
    from build_plan import PROJECT_NAME, compiler_inputs

    if runtime["project"] != PROJECT_NAME:
        raise ValueError("prepared context project differs from the closed compiler profile")
    workspace = require_absolute(Path(runtime["workspace"]), "runtime workspace")
    with_sidecars = tuple(Path(str(args.accepted_store) + suffix) for suffix in ("-wal", "-shm"))
    if any(path.exists() for path in with_sidecars):
        raise ValueError("accepted store has a writable SQLite sidecar")
    store_raw = read_regular(args.accepted_store, MAX_STORE)
    require_pin(store_raw, args.accepted_store_sha256, "accepted store")
    store = DraftStore.open_readonly(args.accepted_store)
    lock, document = locked_document(store, bundle)
    inputs = compiler_inputs(
        document,
        action=args.action,
        workspace=workspace,
        project_name=runtime["project"],
        front_port=runtime["front_port"],
        image=runtime["image"],
        docker_program=docker_path,
        docker_program_identity="sha256:" + docker_pin,
        docker_client_version=runtime["docker_client_version"],
        docker_server_version=runtime["docker_server_version"],
        compose_version=runtime["compose_version"],
        campaign_id=identities["campaign_id"],
        program_id=identities["program_id"],
        occurrence_id=(identities["qualification_occurrence_id"] if args.action == "qualify"
                       else identities["successor_occurrence_id"]),
        observation_id=observation_id,
        subject_digest=identities["subject_digest"],
        scope_digest=identities["scope_digest"],
    )

    args.output.mkdir(mode=0o700, parents=False)
    snapshot_path = args.output / "accepted-plan.sqlite"
    snapshot_store(args.accepted_store, snapshot_path, args.accepted_store_sha256)
    snapshot_sha256 = sha256(read_regular(snapshot_path, MAX_STORE))
    write_new(args.output / f"compiler-input-{args.action}.json", inputs.canonical_bytes)
    write_new(args.output / "plan-locked.json", canonical_json_bytes(document.to_data()))
    write_new(args.output / "accepted-bundle.json", bundle_raw)
    write_new(args.output / "preparation.json", canonical({
        "schema": "maude.accepted-cache-compiler-input-preparation/v1",
        "action": args.action,
        "accepted_bundle_sha256": "sha256:" + args.bundle_sha256,
        "accepted_store_sha256": "sha256:" + args.accepted_store_sha256,
        "accepted_store_snapshot_sha256": "sha256:" + snapshot_sha256,
        "compiler_input_sha256": "sha256:" + sha256(inputs.canonical_bytes),
        "locked_plan_digest": document.digest,
        "lock_id": lock.lock_id,
        "nq_observation_sha256": "sha256:" + args.nq_observation_sha256,
        "observation_id": observation_id,
        "acceptance_ref": bundle["acceptance_ref"],
        "acceptance_proof": "opaque_caller_reference_not_authenticated_by_draft_store",
        "authority": "none",
        "effects": False,
    }))


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("action", choices=("qualify", "teardown"))
    result.add_argument("--maude-source", type=Path)
    result.add_argument("--maude-local-compose-sha256")
    result.add_argument("--accepted-store", type=Path)
    result.add_argument("--accepted-store-sha256")
    result.add_argument("--bundle", type=Path)
    result.add_argument("--bundle-sha256")
    result.add_argument("--compiler-input", type=Path)
    result.add_argument("--compiler-input-sha256")
    result.add_argument("--prepare-input", action="store_true",
                        help="prepare a pinned compiler input; do not compile")
    result.add_argument("--context", type=Path,
                        help="prepared connected-cache context for --prepare-input")
    result.add_argument("--context-sha256")
    result.add_argument("--nq-observation", type=Path,
                        help="retained determinate NQ diagnostic artifact for --prepare-input")
    result.add_argument("--nq-observation-sha256")
    result.add_argument("--output", type=Path, required=True)
    return result


if __name__ == "__main__":
    compile_action(parser().parse_args())
