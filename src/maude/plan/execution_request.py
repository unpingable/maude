# SPDX-License-Identifier: Apache-2.0
"""Project an APPROVED plan envelope into a runtime.grant.activate request
(approval-compression S4a).

RATIFIED boundary: a plan REQUESTS scope; only activation (the daemon) MINTS a
grant. This module does the request side — a **deterministic projection** of an
already-approved, already-admitted plan into the RPC request shape. It carries
no authority and mints nothing.

    scope_allowlist        -> write_paths
    ration allowed_shell_commands (structured) -> commands
    plan_ref               -> source_plan_digest
    approval_ref witness   -> approval_witness_digest (+ raw bytes for the
                              daemon to re-verify — a forged digest is refused
                              daemon-side)

FAIL-SAFE: if the plan is not approved, or the approval witness cannot be
resolved, this returns None and the caller runs WITHOUT compression (every
WRITE prompts, as today). A ration card that cannot be resolved/parsed yields
an empty command set — shell calls then widen and prompt. Projection failure
never grants more; it only grants less.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from maude.plan.envelope import PlanEnvelope, WitnessResolver


@dataclass(frozen=True)
class GrantActivationCall:
    """The two RPC arguments for runtime.grant.activate."""

    execution_request: dict[str, Any]
    witness_bytes: str


def _parse_command(cmd: str) -> dict | None:
    """`"cargo test"` -> `{"program": "cargo", "argv_prefix": ["test"]}`.
    Structured, never a shell string."""
    tokens = cmd.split()
    if not tokens:
        return None
    return {"program": tokens[0], "argv_prefix": tokens[1:]}


def _commands_from_ration(resolver: WitnessResolver, ration_card_digest: str) -> list[dict]:
    ration = resolver(ration_card_digest)
    if ration is None:
        return []  # fail-safe: no commands granted -> shell widens/prompts
    try:
        data = json.loads(ration)
        raw = data.get("allowed_shell_commands", [])
    except (ValueError, TypeError):
        return []
    if not isinstance(raw, (list, tuple)):
        return []
    out: list[dict] = []
    for cmd in raw:
        parsed = _parse_command(str(cmd))
        if parsed is not None:
            out.append(parsed)
    return out


def project_execution_request(
    env: PlanEnvelope, resolver: WitnessResolver
) -> GrantActivationCall | None:
    """Project an approved plan into a grant-activation call, or None when it
    cannot be projected (run proceeds without compression — fail-safe)."""
    gov = env.governance
    if gov is None or gov.governance_status != "approved" or not gov.approval_ref:
        return None
    witness = resolver(gov.approval_ref)
    if witness is None:
        return None
    raw = witness if isinstance(witness, bytes) else str(witness).encode()
    try:
        witness_str = raw.decode("utf-8")
    except UnicodeDecodeError:
        # A non-text witness can't round-trip through the JSON-RPC string param;
        # skip compression rather than send something the daemon can't verify.
        return None
    approval_witness_digest = "sha256:" + hashlib.sha256(raw).hexdigest()

    request = {
        "write_paths": list(env.scope_allowlist),
        "commands": _commands_from_ration(resolver, gov.ration_card_digest),
        "source_plan_digest": env.plan_ref,
        "approval_witness_digest": approval_witness_digest,
        "horizon": "run",
    }
    return GrantActivationCall(execution_request=request, witness_bytes=witness_str)
