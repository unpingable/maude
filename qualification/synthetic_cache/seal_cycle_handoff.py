#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Mint one exact supervised-session custody record and cycle handoff.

This qualification adapter has no Nightshift/AG/Docket client.  It receives an
already sealed base cycle request, binds that request identity to exact locked
PlanDocument bytes, and emits the existing authenticated custody envelope.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from maude.custody import (
    HandoffProducerProfileV1,
    MaudeCustodyStoreV1,
    MaudeHandoffStoreV1,
    SessionCustodyProfileV1,
    _canonical,
)


def exact(path: Path, maximum: int) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"exact input is not a regular non-symlink file: {path}")
    data = path.read_bytes()
    if not 1 <= len(data) <= maximum:
        raise ValueError(f"exact input size is outside 1..={maximum}: {path}")
    return data


def read_cycle_request(request_bytes: bytes) -> dict:
    """Accept canonical request bytes with optional single CLI line framing.

    Nightshift's prepare-cycle prints its canonical object followed by LF.
    The LF is transport framing, not part of the request's semantic identity.
    Do not normalize arbitrary JSON or recompute an identity here: downstream
    owners still validate the exact request and its existing request_id.
    """
    request = json.loads(request_bytes)
    if not isinstance(request, dict):
        raise ValueError("base cycle request is not a JSON object")
    canonical = _canonical(request)
    if request_bytes not in (canonical, canonical + b"\n"):
        raise ValueError("base cycle request is not exact canonical JSON with optional LF")
    if not isinstance(request.get("request_id"), str):
        raise ValueError("base cycle request has no request identity")
    return request


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--session-key", type=Path, required=True)
    parser.add_argument("--producer-key", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--base-request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--runtime-id", required=True)
    args = parser.parse_args()

    plan = exact(args.plan, 1024 * 1024)
    request_bytes = exact(args.base_request, 16 * 1024 * 1024)
    request = read_cycle_request(request_bytes)
    request_id = request["request_id"]

    session_profile = SessionCustodyProfileV1(
        args.store,
        args.session_key,
        "maude:synthetic-supervisor",
        "maude-session-key:synthetic-v1",
    )
    handoff_profile = HandoffProducerProfileV1(
        args.store,
        args.producer_key,
        "maude-handoff:synthetic-local",
        "maude-handoff-key:synthetic-v1",
        session_profile.session_issuer_principal_id,
        session_profile.session_issuer_key_id,
    )
    with MaudeCustodyStoreV1(session_profile) as store:
        store.record_session(args.session_id, plan, recorded_at="2026-08-22T18:01:00Z")
    with MaudeHandoffStoreV1(handoff_profile) as store:
        handoff = store.seal_handoff(
            args.session_id,
            plan,
            request_id,
            args.runtime_id,
            created_at="2026-08-22T18:02:00Z",
        )
    args.output.write_bytes(_canonical(handoff))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
