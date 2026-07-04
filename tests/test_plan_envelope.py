# SPDX-License-Identifier: Apache-2.0
"""M-2 plan envelope tests — pin the M-1 contract incl. the CD-1a governance
binding. Every refusal class exercised; fakes only, no daemon."""

from __future__ import annotations

import hashlib

import pytest

from maude.plan import (
    PlanRefusal,
    REFUSAL_GOVERNANCE_APPROVAL_UNVERIFIED,
    REFUSAL_GOVERNANCE_NOT_APPROVED,
    REFUSAL_GOVERNANCE_REF_MISMATCH,
    REFUSAL_INVALID_PLAN_ENVELOPE,
    REFUSAL_SUBMITTER_LIMITS_MISSING,
    admit_for_execution,
    parse_plan_envelope,
)

D = "sha256:" + "a" * 64
D2 = "sha256:" + "b" * 64


def _plan(front: str, body: str = "\nprose body\n") -> str:
    return f"---\n{front}---\n{body}"

HUMAN_MIN = """\
plan_version: 0
goal: "Do the thing"
workspace: "/tmp/proj"
submitter_kind: human
plan_origin: human_written
provenance:
  author: "operator"
"""


class TestParseHumanPath:
    def test_minimal_human_plan_parses(self):
        env = parse_plan_envelope(_plan(HUMAN_MIN))
        assert env.goal == "Do the thing"
        assert env.submitter_kind == "human"
        assert env.governance is None
        assert env.plan_ref.startswith("sha256:")
        assert env.body.strip() == "prose body"

    def test_plan_ref_is_deterministic_and_content_addressed(self):
        text = _plan(HUMAN_MIN)
        a = parse_plan_envelope(text).plan_ref
        b = parse_plan_envelope(text).plan_ref
        assert a == b == "sha256:" + hashlib.sha256(text.encode()).hexdigest()
        assert parse_plan_envelope(_plan(HUMAN_MIN, "\nother body\n")).plan_ref != a

    def test_unknown_top_level_key_warns_not_refuses(self):
        env = parse_plan_envelope(_plan(HUMAN_MIN + "future_field: hi\n"))
        assert any("future_field" in w for w in env.warnings)

    def test_missing_required_field_refuses(self):
        with pytest.raises(PlanRefusal) as e:
            parse_plan_envelope(_plan(HUMAN_MIN.replace('goal: "Do the thing"\n', "")))
        assert e.value.refusal_class == REFUSAL_INVALID_PLAN_ENVELOPE

    def test_unknown_submitter_kind_refuses_not_guessed(self):
        bad = HUMAN_MIN.replace("submitter_kind: human", "submitter_kind: cyborg")
        with pytest.raises(PlanRefusal) as e:
            parse_plan_envelope(_plan(bad))
        assert e.value.refusal_class == REFUSAL_INVALID_PLAN_ENVELOPE

    def test_unknown_plan_version_refuses(self):
        bad = HUMAN_MIN.replace("plan_version: 0", "plan_version: 7")
        with pytest.raises(PlanRefusal):
            parse_plan_envelope(_plan(bad))

    def test_no_front_matter_refuses(self):
        with pytest.raises(PlanRefusal):
            parse_plan_envelope("just prose, no yaml\n")


SYNTH_BASE = """\
plan_version: 0
goal: "Regenerate the client"
workspace: "/tmp/proj"
submitter_kind: synthetic_agent
plan_origin: agent_generated
provenance:
  author: "codex"
"""


class TestSyntheticLimits:
    def test_synthetic_without_limits_refuses(self):
        with pytest.raises(PlanRefusal) as e:
            parse_plan_envelope(_plan(SYNTH_BASE))
        assert e.value.refusal_class == REFUSAL_SUBMITTER_LIMITS_MISSING

    def test_synthetic_with_budget_and_forbidden_parses(self):
        front = SYNTH_BASE + (
            "stop_conditions:\n  budget_tokens: 1000\n  forbidden_paths: [\"infra/**\"]\n"
        )
        env = parse_plan_envelope(_plan(front))
        assert env.stop_budget_tokens == 1000

    def test_synthetic_budget_without_scope_refuses(self):
        front = SYNTH_BASE + "stop_conditions:\n  budget_tokens: 1000\n"
        with pytest.raises(PlanRefusal) as e:
            parse_plan_envelope(_plan(front))
        assert e.value.refusal_class == REFUSAL_SUBMITTER_LIMITS_MISSING


def _governed(status: str = "approved", approval: str | None = "operator:act-1",
              projected: str = "", extra: str = "") -> str:
    approval_line = f"  approval_ref: \"{approval}\"\n" if approval else ""
    return (
        HUMAN_MIN
        + "scope_allowlist: [\"docs/**\"]\n"
        + "governance:\n"
        + "  authority_system: ag\n"
        + "  playbook_id: \"chore.docs\"\n"
        + f"  playbook_digest: \"{D}\"\n"
        + f"  ration_card_digest: \"{D2}\"\n"
        + approval_line
        + f"  governance_status: {status}\n"
        + projected
        + extra
    )


class TestGovernanceParsing:
    def test_governed_plan_parses(self):
        env = parse_plan_envelope(_plan(_governed()))
        assert env.governance is not None
        assert env.governance.playbook_digest == D

    def test_malformed_digest_refuses(self):
        bad = _governed().replace(D, "sha256:short")
        with pytest.raises(PlanRefusal):
            parse_plan_envelope(_plan(bad))

    def test_unknown_governance_key_refuses_closed_set(self):
        with pytest.raises(PlanRefusal) as e:
            parse_plan_envelope(_plan(_governed(extra="  vibes: excellent\n")))
        assert e.value.refusal_class == REFUSAL_INVALID_PLAN_ENVELOPE

    def test_review_packet_ref_nonnull_at_submit_refuses(self):
        with pytest.raises(PlanRefusal):
            parse_plan_envelope(
                _plan(_governed(extra=f"  review_packet_ref: \"{D}\"\n"))
            )

    def test_approved_without_approval_ref_refuses(self):
        with pytest.raises(PlanRefusal):
            parse_plan_envelope(_plan(_governed(approval=None)))

    def test_projected_key_must_name_carried_field(self):
        # projects forbidden_paths but the envelope carries none
        proj = "  projected:\n    stop_conditions.forbidden_paths: \"queued:%s\"\n" % D
        with pytest.raises(PlanRefusal) as e:
            parse_plan_envelope(_plan(_governed(projected=proj)))
        assert "copy-with-citation" in e.value.detail

    def test_projected_carried_field_ok(self):
        proj = "  projected:\n    scope_allowlist: \"ration_card:%s\"\n" % D2
        env = parse_plan_envelope(_plan(_governed(projected=proj)))
        assert env.governance.projected["scope_allowlist"].endswith(D2)

    def test_unknown_projected_key_refuses(self):
        proj = "  projected:\n    goal: \"x:%s\"\n" % D
        with pytest.raises(PlanRefusal):
            parse_plan_envelope(_plan(_governed(projected=proj)))


class TestExecutionAdmission:
    def test_ungoverned_plan_admits(self):
        rec = admit_for_execution(parse_plan_envelope(_plan(HUMAN_MIN)))
        assert rec.governed is False

    def test_candidate_never_executes(self):
        env = parse_plan_envelope(_plan(_governed(status="candidate", approval=None)))
        with pytest.raises(PlanRefusal) as e:
            admit_for_execution(env)
        assert e.value.refusal_class == REFUSAL_GOVERNANCE_NOT_APPROVED

    def test_approved_without_resolver_fails_closed(self):
        env = parse_plan_envelope(_plan(_governed()))
        with pytest.raises(PlanRefusal) as e:
            admit_for_execution(env)  # no witness resolver at all
        assert e.value.refusal_class == REFUSAL_GOVERNANCE_APPROVAL_UNVERIFIED

    def test_written_approved_is_prose_until_witnessed(self):
        env = parse_plan_envelope(_plan(_governed()))
        with pytest.raises(PlanRefusal) as e:
            admit_for_execution(env, witness_resolver=lambda ref: None)
        assert e.value.refusal_class == REFUSAL_GOVERNANCE_APPROVAL_UNVERIFIED

    def test_digest_mismatch_refuses(self):
        env = parse_plan_envelope(_plan(_governed()))
        with pytest.raises(PlanRefusal) as e:
            admit_for_execution(env, witness_resolver=lambda ref: b"not-the-cited-bytes")
        assert e.value.refusal_class == REFUSAL_GOVERNANCE_REF_MISMATCH

    def test_fully_witnessed_approved_plan_admits(self):
        playbook_bytes = b"playbook-body"
        ration_bytes = b"ration-body"
        d_playbook = "sha256:" + hashlib.sha256(playbook_bytes).hexdigest()
        d_ration = "sha256:" + hashlib.sha256(ration_bytes).hexdigest()
        front = _governed().replace(D, d_playbook).replace(D2, d_ration)
        env = parse_plan_envelope(_plan(front))

        store = {
            d_playbook: playbook_bytes,
            d_ration: ration_bytes,
            "operator:act-1": b"approval act record",
        }
        rec = admit_for_execution(env, witness_resolver=store.get)
        assert rec.governed is True
        assert dict(rec.verified) == {
            "playbook_digest": "verified",
            "ration_card_digest": "verified",
            "approval_ref": "verified",
        }
