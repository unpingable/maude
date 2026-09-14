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
import sqlite3
import stat
import sys

MAX_JSON = 32 * 1024
MAX_STORE = 64 * 1024 * 1024
MAX_SOURCE = 2 * 1024 * 1024
BUNDLE_SCHEMA = "maude.accepted-cache-plan-bundle/v1"


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
    for path, label in ((args.maude_source, "Maude source"),
                        (args.accepted_store, "accepted store"),
                        (args.bundle, "accepted bundle"),
                        (args.compiler_input, "compiler input")):
        if not path.is_absolute():
            raise ValueError(f"{label} path must be absolute")
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
    bundle = json.loads(bundle_raw)
    if set(bundle) != {"acceptance_ref", "draft_id", "lock_id", "plan_digest", "schema"}:
        raise ValueError("accepted bundle fields differ")
    if bundle["schema"] != BUNDLE_SCHEMA or not bundle["acceptance_ref"]:
        raise ValueError("accepted bundle schema or reference differs")

    args.output.mkdir(mode=0o700, parents=False)
    store_copy = args.output / "accepted-plan.sqlite"
    snapshot_store(args.accepted_store, store_copy, args.accepted_store_sha256)

    sys.path.insert(0, str(args.maude_source / "src"))
    from maude.plan.document import canonical_json_bytes
    from maude.plan.local_compose import (
        LocalComposeWorkflowCompilerV1,
        LocalComposeWorkflowInputsV1,
        NodeActionV1,
        ag_executor_plan_identity,
        executor_plan_from_handoff,
    )
    from maude.plan.store import DraftStore

    raw = json.loads(input_raw)
    raw["node_actions"] = tuple(NodeActionV1(**item) for item in raw["node_actions"])
    inputs = LocalComposeWorkflowInputsV1(**raw)
    if inputs.action != args.action:
        raise ValueError("compiler input action differs from requested action")
    store = DraftStore(store_copy)
    lock = next((item for item in store.locks(bundle["draft_id"])
                 if item.lock_id == bundle["lock_id"]), None)
    if lock is None or lock.plan_digest != bundle["plan_digest"]:
        raise ValueError("accepted lock is absent or has a different plan digest")
    document = store.revision(lock.revision_id).document
    if document.digest != bundle["plan_digest"]:
        raise ValueError("accepted document identity differs")
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


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("action", choices=("qualify", "teardown"))
    result.add_argument("--maude-source", type=Path, required=True)
    result.add_argument("--maude-local-compose-sha256", required=True)
    result.add_argument("--accepted-store", type=Path, required=True)
    result.add_argument("--accepted-store-sha256", required=True)
    result.add_argument("--bundle", type=Path, required=True)
    result.add_argument("--bundle-sha256", required=True)
    result.add_argument("--compiler-input", type=Path, required=True)
    result.add_argument("--compiler-input-sha256", required=True)
    result.add_argument("--output", type=Path, required=True)
    return result


if __name__ == "__main__":
    compile_action(parser().parse_args())
