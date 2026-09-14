#!/usr/bin/env python3
"""Bind one precompiled local-Compose proposal to its exact posture request.

This helper only derives a canonical request. It does not invoke an owner,
acquire an observation, grant authority, or execute the proposal.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path

MAX_INPUT = 16 * 1024 * 1024


def load(path: Path) -> dict:
    if not path.is_absolute() or not path.is_file() or path.is_symlink():
        raise ValueError("input must be an absolute regular non-symlink file")
    with path.open("rb") as stream:
        raw = stream.read(MAX_INPUT + 1)
    if not raw or len(raw) > MAX_INPUT:
        raise ValueError("input is empty or oversized")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("input must be one JSON object")
    return value


def canonical(value: dict) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def object_id(value: dict, field: str) -> str:
    preimage = dict(value)
    preimage.pop(field, None)
    return "sha256:" + hashlib.sha256(canonical(preimage)).hexdigest()


def bind(posture: dict, proposal: dict) -> dict:
    if (
        posture.get("schema") != "nightshift.canonical_cycle_request.v1"
        or posture.get("proposal") is not None
        or posture.get("authoring_context") is not None
    ):
        raise ValueError("base must be a proposal-free canonical request")
    if proposal.get("schema") != "nightshift.precompiled_workflow_proposal.v2":
        raise ValueError("unsupported precompiled proposal")
    proposal_input = proposal.get("proposal_input")
    if not isinstance(proposal_input, dict):
        raise ValueError("precompiled proposal input is absent")
    exact = proposal_input.get("proposal")
    if not isinstance(exact, dict):
        raise ValueError("precompiled proposal body is absent")
    if (
        exact.get("work_schema") != "maude.local-compose-workflow/v1"
        or exact.get("scope") != posture.get("slot", {}).get("scope_id")
    ):
        raise ValueError("proposal does not bind request scope and local-Compose schema")
    if proposal_input.get("observation") != posture.get("observation_id"):
        raise ValueError("proposal does not bind the exact host observation")
    result = dict(posture)
    result["proposal"] = proposal
    result["request_id"] = object_id(result, "request_id")
    return result


def write_new(path: Path, value: dict) -> None:
    if not path.is_absolute() or path.parent == path:
        raise ValueError("output must be an absolute file path")
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
    )
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(canonical(value))
        stream.flush()
        os.fsync(stream.fileno())


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--posture-request", type=Path, required=True)
    result.add_argument("--precompiled-proposal", type=Path, required=True)
    result.add_argument("--output", type=Path, required=True)
    return result


def main() -> None:
    args = parser().parse_args()
    write_new(args.output, bind(load(args.posture_request), load(args.precompiled_proposal)))


if __name__ == "__main__":
    main()
