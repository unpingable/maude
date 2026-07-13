# SPDX-License-Identifier: Apache-2.0
"""M-2 plan envelope tests — pin the M-1 contract incl. the CD-1a governance
binding. Every refusal class exercised; fakes only, no daemon."""

from __future__ import annotations

import hashlib
import json

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
plan_version: 1
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
        bad = HUMAN_MIN.replace("plan_version: 1", "plan_version: 7")
        with pytest.raises(PlanRefusal):
            parse_plan_envelope(_plan(bad))

    def test_no_front_matter_refuses(self):
        with pytest.raises(PlanRefusal):
            parse_plan_envelope("just prose, no yaml\n")


SYNTH_BASE = """\
plan_version: 1
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
        + "execution_request:\n  write_paths: [\"docs/**\"]\n"
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
        proj = "  projected:\n    execution_request.write_paths: \"ration_card:%s\"\n" % D2
        env = parse_plan_envelope(_plan(_governed(projected=proj)))
        assert env.governance.projected["execution_request.write_paths"].endswith(D2)

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
        # S7: a real RationCard that CONTAINS the execution_request (docs/**),
        # and the request cited against it — else admission refuses.
        ration_bytes = json.dumps(
            {"allowed_write_paths": ["docs/**"], "allowed_shell_commands": []}
        ).encode()
        d_playbook = "sha256:" + hashlib.sha256(playbook_bytes).hexdigest()
        d_ration = "sha256:" + hashlib.sha256(ration_bytes).hexdigest()
        proj = f'  projected:\n    execution_request.write_paths: "ration_card:{d_ration}"\n'
        front = _governed(projected=proj).replace(D, d_playbook).replace(D2, d_ration)
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


# S6 — the versioned-contract migration. plan_version is the schema
# discriminator; v0 is retired for authorship and decodes ONLY for an explicitly
# frozen pre-v1 specimen. "Unversioned means legacy" is closed by construction.
#: the committed NS-1 candidate specimen's plan_ref (AG repo), registered in
#: FROZEN_V0_PLAN_REFS and adjudicated in AG's S6 design note.
NS1_FROZEN_PLAN_REF = (
    "sha256:da241bc77f8b209c3a25a21866fbde22f2a8b799d1ea3b61d588a727849a1b47"
)


class TestVersionDiscrimination:
    def test_missing_plan_version_refuses_no_legacy_default(self):
        bad = HUMAN_MIN.replace("plan_version: 1\n", "")
        with pytest.raises(PlanRefusal) as e:
            parse_plan_envelope(_plan(bad))
        assert e.value.refusal_class == REFUSAL_INVALID_PLAN_ENVELOPE
        assert "plan_version_missing" in e.value.detail

    def test_fresh_v0_plan_is_retired(self):
        # a brand-new plan_version: 0 plan whose hash is not frozen refuses —
        # you cannot author new v0 plans.
        bad = HUMAN_MIN.replace("plan_version: 1", "plan_version: 0")
        with pytest.raises(PlanRefusal) as e:
            parse_plan_envelope(_plan(bad))
        assert e.value.refusal_class == REFUSAL_INVALID_PLAN_ENVELOPE
        assert "plan_version_retired" in e.value.detail

    def test_unknown_version_refuses(self):
        bad = HUMAN_MIN.replace("plan_version: 1", "plan_version: 9")
        with pytest.raises(PlanRefusal) as e:
            parse_plan_envelope(_plan(bad))
        assert "plan_version_unknown" in e.value.detail

    def test_bool_plan_version_refuses_no_type_coercion(self):
        # YAML `true` -> Python True; True == 1 in Python. The discriminator must
        # not be reachable by bool coercion.
        bad = HUMAN_MIN.replace("plan_version: 1", "plan_version: true")
        with pytest.raises(PlanRefusal) as e:
            parse_plan_envelope(_plan(bad))
        assert "plan_version_unknown" in e.value.detail

    def test_float_plan_version_refuses_no_type_coercion(self):
        # YAML `1.0` -> float; 1.0 == 1 in Python. Must refuse, not reach v1.
        bad = HUMAN_MIN.replace("plan_version: 1", "plan_version: 1.0")
        with pytest.raises(PlanRefusal) as e:
            parse_plan_envelope(_plan(bad))
        assert "plan_version_unknown" in e.value.detail

    def test_ns1_hash_is_registered_frozen(self):
        # pins the registration without a cross-repo file read: if the frozen
        # set changes, this catches it.
        from maude.plan.envelope import FROZEN_V0_PLAN_REFS

        assert NS1_FROZEN_PLAN_REF in FROZEN_V0_PLAN_REFS

    def test_frozen_v0_hash_decodes_via_legacy_path(self, monkeypatch):
        # a v0 plan whose hash IS frozen decodes through the retired path with
        # the legacy scope_allowlist surface. We freeze this exact plan's hash.
        v0_text = _plan(
            HUMAN_MIN.replace("plan_version: 1", "plan_version: 0")
            + "scope_allowlist: [\"legacy/**\"]\n"
        )
        v0_ref = "sha256:" + hashlib.sha256(v0_text.encode()).hexdigest()
        monkeypatch.setattr(
            "maude.plan.envelope.FROZEN_V0_PLAN_REFS", frozenset({v0_ref})
        )
        env = parse_plan_envelope(v0_text)
        assert env.plan_version == 0
        assert env.scope_allowlist == ("legacy/**",)
        assert env.execution_request is None

    def test_v1_forbids_legacy_scope_allowlist(self):
        bad = HUMAN_MIN + "scope_allowlist: [\"docs/**\"]\n"
        with pytest.raises(PlanRefusal) as e:
            parse_plan_envelope(_plan(bad))
        assert "legacy_field_under_v1" in e.value.detail

    def test_governed_v1_requires_execution_request_block(self):
        # _governed() carries execution_request; strip it → a governed v1 plan
        # with no first-class request refuses.
        front = _governed().replace(
            "execution_request:\n  write_paths: [\"docs/**\"]\n", ""
        )
        with pytest.raises(PlanRefusal) as e:
            parse_plan_envelope(_plan(front))
        assert e.value.refusal_class == REFUSAL_INVALID_PLAN_ENVELOPE

    def test_ungoverned_v1_execution_request_is_optional(self):
        # no governance block → no grant → the block is optional (uncompressed).
        env = parse_plan_envelope(_plan(HUMAN_MIN))
        assert env.plan_version == 1
        assert env.execution_request is None
        assert env.governance is None

    def test_v1_execution_request_parses_structured(self):
        front = HUMAN_MIN + (
            "execution_request:\n"
            "  write_paths: [\"src/**\"]\n"
            "  commands:\n"
            "    - {program: cargo, argv_prefix: [test]}\n"
            "  network: requested\n"
            "  horizon: session\n"
        )
        env = parse_plan_envelope(_plan(front))
        assert env.execution_request is not None
        block = env.execution_request
        assert block.write_paths == ("src/**",)
        assert block.commands[0].program == "cargo"
        assert block.commands[0].argv_prefix == ("test",)
        assert block.network == "requested"
        assert block.git == "denied"
        assert block.horizon == "session"

    def test_v1_empty_execution_request_refuses(self):
        front = HUMAN_MIN + "execution_request:\n  write_paths: []\n"
        with pytest.raises(PlanRefusal):
            parse_plan_envelope(_plan(front))

    def test_v1_unknown_axis_value_refuses(self):
        front = HUMAN_MIN + (
            "execution_request:\n  write_paths: [\"src/**\"]\n  network: allowed\n"
        )
        with pytest.raises(PlanRefusal):
            parse_plan_envelope(_plan(front))

    def test_v1_shell_string_command_refuses(self):
        # commands must be structured {program, argv_prefix}, never a bare string
        front = HUMAN_MIN + (
            "execution_request:\n  write_paths: [\"src/**\"]\n  commands: [\"cargo test\"]\n"
        )
        with pytest.raises(PlanRefusal):
            parse_plan_envelope(_plan(front))
