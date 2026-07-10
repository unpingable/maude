# SPDX-License-Identifier: Apache-2.0
"""S4a — project an approved plan into a runtime.grant.activate request.
Fail-safe: not-approved / no-witness -> None (run without compression);
unresolvable/bad ration -> empty commands (shell widens). Never grants more.
"""

from __future__ import annotations

import hashlib
import json

from maude.plan.envelope import parse_plan_envelope
from maude.plan.execution_request import project_execution_request

RATION = json.dumps({"allowed_shell_commands": ["cargo test", "cargo build"]}).encode()
WITNESS = b"operator approved this plan 2026-07-10"
D_PB = "sha256:" + hashlib.sha256(b"pb").hexdigest()
D_RC = "sha256:" + hashlib.sha256(RATION).hexdigest()

_PLAN = """\
---
plan_version: 0
goal: "x"
workspace: "/tmp/proj"
submitter_kind: human
plan_origin: human_written
provenance:
  author: "operator"
harness: claude_code
scope_allowlist:
  - "crates/nightshiftd/src/**"
  - "crates/nightshiftd/tests/**"
steps:
  - "step one"
governance:
  authority_system: ag
  playbook_id: "chore.x"
  playbook_digest: "%s"
  ration_card_digest: "%s"
  approval_ref: "operator_plan_approved"
  governance_status: %s
---

Background prose.
"""

APPROVED = _PLAN % (D_PB, D_RC, "approved")
CANDIDATE = (_PLAN % (D_PB, D_RC, "candidate")).replace(
    '  approval_ref: "operator_plan_approved"\n', ""
)


def _resolver(overrides=None):
    store = {D_RC: RATION, "operator_plan_approved": WITNESS, D_PB: b"pb"}
    if overrides is not None:
        store.update(overrides)
    return store.get


def test_projects_approved_plan_to_request():
    env = parse_plan_envelope(APPROVED)
    call = project_execution_request(env, _resolver())
    assert call is not None
    req = call.execution_request
    assert req["write_paths"] == ["crates/nightshiftd/src/**", "crates/nightshiftd/tests/**"]
    assert req["commands"] == [
        {"program": "cargo", "argv_prefix": ["test"]},
        {"program": "cargo", "argv_prefix": ["build"]},
    ]
    assert req["approval_witness_digest"] == "sha256:" + hashlib.sha256(WITNESS).hexdigest()
    assert req["source_plan_digest"] == env.plan_ref
    assert req["horizon"] == "run"
    assert call.witness_bytes == WITNESS.decode()


def test_candidate_plan_not_projected():
    env = parse_plan_envelope(CANDIDATE)
    assert project_execution_request(env, _resolver()) is None


def test_missing_witness_not_projected():
    env = parse_plan_envelope(APPROVED)
    # resolver returns None for the approval_ref -> fail-safe None
    assert project_execution_request(env, lambda c: None) is None


def test_unresolvable_ration_yields_empty_commands():
    env = parse_plan_envelope(APPROVED)
    call = project_execution_request(env, _resolver({D_RC: None}))
    assert call is not None
    assert call.execution_request["commands"] == []


def test_bad_ration_json_yields_empty_commands():
    env = parse_plan_envelope(APPROVED)
    call = project_execution_request(env, _resolver({D_RC: b"not json at all"}))
    assert call is not None
    assert call.execution_request["commands"] == []
