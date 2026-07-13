# SPDX-License-Identifier: Apache-2.0
"""Project an APPROVED plan envelope into a runtime.grant.activate request
(approval-compression S4a; S6 versioned).

RATIFIED boundary: a plan REQUESTS scope; only activation (the daemon) MINTS a
grant. This module does the request side — a **deterministic projection** of an
already-approved, already-admitted plan into the RPC request shape. It carries
no authority and mints nothing.

Two projection sources by plan version (S6):

- **v1 (the authoring surface):** read the first-class ``execution_request``
  block DIRECTLY. The request is legible in the plan bytes the operator
  approved — nothing is reconstructed.

      execution_request.write_paths      -> write_paths
      execution_request.commands         -> commands (already structured)
      execution_request.network/git      -> network_requested/git_requested
      execution_request.horizon          -> horizon

- **v0 (retired historical decoder, frozen specimens only):** the legacy
  inference — ``scope_allowlist`` -> write_paths and the RationCard's
  ``allowed_shell_commands`` -> commands. Reached only for a plan the envelope
  parser admitted as frozen-v0; new plans cannot land here.

Common to both:

    plan_ref               -> source_plan_digest
    approval_ref witness   -> approval_witness_digest (+ raw bytes for the
                              daemon to re-verify — a forged digest is refused
                              daemon-side)

FAIL-SAFE: if the plan is not approved, or the approval witness cannot be
resolved, this returns None and the caller runs WITHOUT compression (every
WRITE prompts, as today). Under v0 a ration card that cannot be resolved/parsed
yields an empty command set — shell calls then widen and prompt. Projection
failure never grants more; it only grants less.
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
    # Defense-in-depth (TOCTOU): the bytes we CONSUME must hash to the cited
    # digest, even if a stateful resolver returned different bytes here than
    # admission verified earlier. Admission already checked A; we re-check the
    # bytes actually used. A mismatch fails safe (no commands -> shell widens),
    # never trusts substituted bytes.
    if ration_card_digest.startswith("sha256:"):
        if "sha256:" + hashlib.sha256(ration).hexdigest() != ration_card_digest:
            return []
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


def _request_from_v1_block(env: PlanEnvelope) -> dict[str, Any]:
    """v1 — copy the first-class request block into RPC shape. Nothing inferred;
    a ``requested`` axis becomes a request flag (activation still locks it and
    records it in ``unmet_axes`` — declaration is not grant)."""
    block = env.execution_request
    assert block is not None  # guaranteed by the v1 parse path
    return {
        "write_paths": list(block.write_paths),
        "commands": [
            {"program": c.program, "argv_prefix": list(c.argv_prefix)}
            for c in block.commands
        ],
        "horizon": block.horizon,
        "network_requested": block.network == "requested",
        "git_requested": block.git == "requested",
    }


def _request_from_v0(env: PlanEnvelope, resolver: WitnessResolver) -> dict[str, Any]:
    """v0 — retired legacy inference (frozen specimens only): scope_allowlist ->
    write_paths, RationCard allowed_shell_commands -> commands."""
    gov = env.governance
    assert gov is not None  # only reached on an approved, governed plan
    return {
        "write_paths": list(env.scope_allowlist),
        "commands": _commands_from_ration(resolver, gov.ration_card_digest),
        "horizon": "run",
    }


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

    if env.plan_version == 1:
        if env.execution_request is None:
            return None  # governed-but-no-request: run uncompressed (fail-safe)
        request = _request_from_v1_block(env)
    elif env.plan_version == 0:  # frozen-v0 historical decoder
        request = _request_from_v0(env, resolver)
    else:
        # unreachable: parse only produces version 0 or 1. Fail-safe rather than
        # treat an unexpected version as legacy via a catch-all else.
        return None
    request["source_plan_digest"] = env.plan_ref
    request["approval_witness_digest"] = approval_witness_digest
    return GrantActivationCall(execution_request=request, witness_bytes=witness_str)
