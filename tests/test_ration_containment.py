# SPDX-License-Identifier: Apache-2.0
"""S7 — Ration Citation Containment. The eight adversarial pins from
`design-s7-ration-citation-containment.md` (the acceptance contract) plus the
predicate's unit + subsumption-consistency tests. Fakes only, no daemon.

Detail tokens (reused `invalid_plan_envelope` class): `ration_citation_required`,
`execution_request_exceeds_ration`.
"""

from __future__ import annotations

import hashlib
import itertools
import json

import pytest

from maude.plan import (
    REFUSAL_GOVERNANCE_REF_MISMATCH,
    REFUSAL_INVALID_PLAN_ENVELOPE,
    PlanRefusal,
    admit_for_execution,
    parse_plan_envelope,
)
from maude.plan.execution_request import project_execution_request
from maude.plan.ration_containment import (
    NOT_MODELLED,
    ParsedRation,
    check_containment,
    command_contained,
    parse_ration,
    write_path_subsumed,
)


# --------------------------------------------------------------------------- #
# Builder: a governed v1 plan with a chosen execution_request + ration + cites
# --------------------------------------------------------------------------- #


def _build(
    *,
    write_paths: list[str] | None = None,
    commands: list[tuple[str, list[str]]] | None = None,
    network: str = "denied",
    git: str = "denied",
    ration: dict,
    cite_write: bool = True,
    cite_commands: bool = True,
):
    """Return (plan_text, resolver). ration is the RationCard dict."""
    er = "execution_request:\n"
    if write_paths is not None:
        er += "  write_paths:\n" + "".join(f'    - "{p}"\n' for p in write_paths)
    if commands is not None:
        er += "  commands:\n" + "".join(
            f"    - {{program: {p}, argv_prefix: [{', '.join(a)}]}}\n" for p, a in commands
        )
    er += f"  network: {network}\n  git: {git}\n"

    ration_bytes = json.dumps(ration).encode()
    d_pb = "sha256:" + hashlib.sha256(b"pb").hexdigest()
    d_rc = "sha256:" + hashlib.sha256(ration_bytes).hexdigest()

    proj = ""
    cites = []
    if cite_write and write_paths is not None:
        cites.append(f'    execution_request.write_paths: "ration_card:{d_rc}"\n')
    if cite_commands and commands is not None:
        cites.append(f'    execution_request.commands: "ration_card:{d_rc}"\n')
    if cites:
        proj = "  projected:\n" + "".join(cites)

    front = (
        "---\nplan_version: 1\n"
        'goal: "x"\nworkspace: "/tmp/p"\n'
        "submitter_kind: human\nplan_origin: human_written\n"
        'provenance:\n  author: "op"\nharness: claude_code\n'
        + er
        + 'steps:\n  - "s"\n'
        "governance:\n  authority_system: ag\n  playbook_id: \"p\"\n"
        f'  playbook_digest: "{d_pb}"\n  ration_card_digest: "{d_rc}"\n'
        '  approval_ref: "operator:act"\n  governance_status: approved\n'
        + proj
        + "---\n\nbody\n"
    )
    store = {d_pb: b"pb", d_rc: ration_bytes, "operator:act": b"act"}
    return front, store.get


CARGO_RATION = {
    "allowed_write_paths": ["crates/nightshiftd/src/**"],
    "allowed_shell_commands": ["cargo test", "cargo build"],
    "network_allowed": False,
    "git_allowed": False,
}


def _admit(front, resolver):
    return admit_for_execution(parse_plan_envelope(front), witness_resolver=resolver)


def _refusal(front, resolver):
    with pytest.raises(PlanRefusal) as e:
        _admit(front, resolver)
    return e.value


# --------------------------------------------------------------------------- #
# The eight adversarial pins
# --------------------------------------------------------------------------- #


class TestS7AdversarialPins:
    def test_1_command_narrowing_admits(self):
        # ration allows "cargo test"; request "cargo test --lib" is NARROWER
        front, r = _build(
            write_paths=["crates/nightshiftd/src/**"],
            commands=[("cargo", ["test", "--lib"])],
            ration=CARGO_RATION,
        )
        assert _admit(front, r).governed is True

    def test_2_command_broadening_refuses(self):
        # request "cargo" (no subcommand) is BROADER than "cargo test"/"cargo build"
        front, r = _build(
            write_paths=["crates/nightshiftd/src/**"],
            commands=[("cargo", [])],
            ration=CARGO_RATION,
        )
        e = _refusal(front, r)
        assert e.refusal_class == REFUSAL_INVALID_PLAN_ENVELOPE
        assert "execution_request_exceeds_ration" in e.detail
        assert "commands" in e.detail

    def test_3_prefix_trailing_arg_smuggling_refuses(self):
        # "cargo test --target-dir=/etc" prefix-matches but relocates effects
        front, r = _build(
            write_paths=["crates/nightshiftd/src/**"],
            commands=[("cargo", ["test", "--target-dir=/etc"])],
            ration=CARGO_RATION,
        )
        e = _refusal(front, r)
        assert "execution_request_exceeds_ration" in e.detail

    def test_4_axis_broadening_refuses(self):
        # request network while the ration denies it
        front, r = _build(
            write_paths=["crates/nightshiftd/src/**"],
            network="requested",
            ration=CARGO_RATION,
        )
        e = _refusal(front, r)
        assert "execution_request_exceeds_ration" in e.detail
        assert "network" in e.detail
        # git axis, same rule
        front2, r2 = _build(
            write_paths=["crates/nightshiftd/src/**"], git="requested", ration=CARGO_RATION
        )
        assert "git" in _refusal(front2, r2).detail

    def test_5_correct_citation_substituted_bytes_refuses(self):
        # the digest names ration A; the resolver returns bytes B -> the SAME
        # verify path that feeds containment rejects it (governance_ref_mismatch)
        front, r = _build(write_paths=["crates/nightshiftd/src/**"], ration=CARGO_RATION)
        env = parse_plan_envelope(front)
        d_rc = env.governance.ration_card_digest

        def evil(citation):
            if citation == d_rc:
                return json.dumps({"allowed_write_paths": ["/etc/**"]}).encode()
            return r(citation)

        with pytest.raises(PlanRefusal) as e:
            admit_for_execution(env, witness_resolver=evil)
        assert e.value.refusal_class == REFUSAL_GOVERNANCE_REF_MISMATCH

    def test_6_stateful_resolver_single_verified_read(self):
        # admission verifies the ration once and threads those bytes to
        # projection; a resolver that mutates AFTER admission cannot change what
        # projection consumes. (v1 projection reads the block, so we assert the
        # threaded bytes ARE the admission-verified ones.)
        front, r = _build(
            write_paths=["crates/nightshiftd/src/**"],
            commands=[("cargo", ["test"])],
            ration=CARGO_RATION,
        )
        env = parse_plan_envelope(front)
        rec = admit_for_execution(env, witness_resolver=r)
        assert rec.verified_ration_bytes is not None
        # its hash equals the cited digest — it is the verified artifact
        actual = "sha256:" + hashlib.sha256(rec.verified_ration_bytes).hexdigest()
        assert actual == env.governance.ration_card_digest

        # a resolver that now returns evil bytes cannot poison projection: it is
        # handed the admission-verified bytes.
        def evil(_c):
            return json.dumps({"allowed_shell_commands": ["rm -rf /"]}).encode()

        call = project_execution_request(
            env, evil, verified_ration_bytes=rec.verified_ration_bytes
        )
        assert call is not None
        # v1 commands come from the BLOCK regardless, never from the resolver
        assert call.execution_request["commands"] == [
            {"program": "cargo", "argv_prefix": ["test"]}
        ]

    def test_6b_mutable_ration_bytes_snapshotted_at_admission(self):
        # sandwich finding: a hostile resolver returns a bytearray verified as
        # card A, then mutates that SAME buffer to permissive card B when a later
        # citation (approval_ref) resolves. Admission must snapshot the verified
        # bytes (bytes()) so containment sees A, not B — else a request contained
        # only by B slips through against a card that verified as A.
        A = {"allowed_write_paths": ["safe/**"], "allowed_shell_commands": []}
        B = {"allowed_write_paths": ["/etc/**"], "allowed_shell_commands": []}
        front, _ = _build(write_paths=["/etc/**"], ration=A)  # request only in B
        env = parse_plan_envelope(front)
        d_rc = env.governance.ration_card_digest
        buf = bytearray(json.dumps(A).encode())  # hashes to d_rc

        def evil(citation):
            if citation == d_rc:
                return buf
            if citation == env.governance.approval_ref:
                buf[:] = json.dumps(B).encode()  # mutate AFTER ration verified
                return b"act"
            return b"pb"  # playbook_digest

        with pytest.raises(PlanRefusal) as e:
            admit_for_execution(env, witness_resolver=evil)
        assert "execution_request_exceeds_ration" in e.value.detail

    def test_7_unrelated_valid_ration_refuses_when_not_contained(self):
        # a perfectly valid RationCard that does not authorize the request is not
        # a blank check — containment is against the cited card's contents.
        unrelated = {
            "allowed_write_paths": ["docs/**"],           # not crates/**
            "allowed_shell_commands": ["ruff check"],     # not cargo
        }
        front, r = _build(
            write_paths=["crates/nightshiftd/src/**"],
            commands=[("cargo", ["test"])],
            ration=unrelated,
        )
        e = _refusal(front, r)
        assert "execution_request_exceeds_ration" in e.detail

    def test_8_frozen_v0_behavior_byte_identical(self, monkeypatch):
        # S7 must not touch the frozen v0 path: a v0 plan admits + projects
        # exactly as before (no containment, legacy ration inference).
        ration = json.dumps({"allowed_shell_commands": ["cargo test"]}).encode()
        d_pb = "sha256:" + hashlib.sha256(b"pb").hexdigest()
        d_rc = "sha256:" + hashlib.sha256(ration).hexdigest()
        v0 = (
            "---\nplan_version: 0\n"
            'goal: "x"\nworkspace: "/tmp/p"\n'
            "submitter_kind: human\nplan_origin: human_written\n"
            'provenance:\n  author: "op"\nharness: claude_code\n'
            'scope_allowlist:\n  - "anything/**"\n'  # v0 does NOT containment-check
            'steps:\n  - "s"\n'
            "governance:\n  authority_system: ag\n  playbook_id: \"p\"\n"
            f'  playbook_digest: "{d_pb}"\n  ration_card_digest: "{d_rc}"\n'
            '  approval_ref: "operator:act"\n  governance_status: approved\n'
            "---\n\nbody\n"
        )
        v0_ref = "sha256:" + hashlib.sha256(v0.encode()).hexdigest()
        monkeypatch.setattr(
            "maude.plan.envelope.FROZEN_V0_PLAN_REFS", frozenset({v0_ref})
        )
        store = {d_pb: b"pb", d_rc: ration, "operator:act": b"act"}
        env = parse_plan_envelope(v0)
        rec = admit_for_execution(env, witness_resolver=store.get)  # no S7 refusal
        assert rec.governed is True
        call = project_execution_request(
            env, store.get, verified_ration_bytes=rec.verified_ration_bytes
        )
        # legacy inference intact: scope_allowlist + ration commands
        assert call.execution_request["write_paths"] == ["anything/**"]
        assert call.execution_request["commands"] == [
            {"program": "cargo", "argv_prefix": ["test"]}
        ]


# --------------------------------------------------------------------------- #
# ration_citation_required + not-modelled + valid-admit
# --------------------------------------------------------------------------- #


class TestS7Citation:
    def test_missing_write_citation_refuses(self):
        front, r = _build(
            write_paths=["crates/nightshiftd/src/**"], ration=CARGO_RATION, cite_write=False
        )
        e = _refusal(front, r)
        assert "ration_citation_required" in e.detail

    def test_missing_command_citation_refuses(self):
        front, r = _build(
            write_paths=["crates/nightshiftd/src/**"],
            commands=[("cargo", ["test"])],
            ration=CARGO_RATION,
            cite_commands=False,
        )
        e = _refusal(front, r)
        assert "ration_citation_required" in e.detail

    def test_cited_and_contained_admits(self):
        front, r = _build(
            write_paths=["crates/nightshiftd/src/**"],
            commands=[("cargo", ["test"]), ("cargo", ["build"])],
            ration=CARGO_RATION,
        )
        assert _admit(front, r).governed is True

    def test_malformed_ration_refuses_fail_closed(self):
        # ration that is valid JSON but not a card shape -> cannot bound -> refuse
        front, r = _build(
            write_paths=["crates/nightshiftd/src/**"],
            ration={"allowed_write_paths": "not-a-list"},
        )
        e = _refusal(front, r)
        assert "ration_citation_required" in e.detail  # parse failure fails closed


# --------------------------------------------------------------------------- #
# Predicate units + subsumption-consistency property
# --------------------------------------------------------------------------- #


class TestContainmentPredicate:
    def test_command_prefix_containment(self):
        allowed = (("cargo", ("test",)),)
        assert command_contained("cargo", ("test",), allowed)
        assert command_contained("cargo", ("test", "--lib"), allowed)   # narrower
        assert not command_contained("cargo", (), allowed)              # broader
        assert not command_contained("cargo", ("build",), allowed)      # other
        assert not command_contained("rustc", ("test",), allowed)       # other program
        assert not command_contained("cargo", ("test", "--config=x"), allowed)  # escape

    def test_write_path_subsumption(self):
        allowed = ("crates/**", "docs/*")
        assert write_path_subsumed("crates/**", allowed)          # exact
        assert write_path_subsumed("crates/nightshiftd/*", allowed)  # narrower under **
        assert write_path_subsumed("crates/a/b/c.rs", allowed)    # concrete under **
        assert write_path_subsumed("docs/readme.md", allowed)     # concrete single-level
        assert write_path_subsumed("docs/*", allowed)             # exact single-level
        assert not write_path_subsumed("docs/**", allowed)        # ** broader than /*
        assert not write_path_subsumed("docs/sub/x", allowed)     # deeper than /*
        assert not write_path_subsumed("other/**", allowed)       # unrelated
        assert not write_path_subsumed("crates/../etc", allowed)  # traversal

    def test_subsumption_consistent_with_concrete_matching(self):
        """Property: if allow-pattern A subsumes request-pattern R, then every
        concrete path the gate would admit under R it also admits under A. This
        is the honesty anchor — subsumption never over-admits vs the gate's
        concrete `_path_within` semantics (mirrored here)."""
        def concrete_within(path: str, pat: str) -> bool:
            if not path or ".." in path.split("/"):
                return False
            if pat.endswith("/**"):
                return path.startswith(pat[:-2])
            if pat.endswith("/*"):
                pre = pat[:-1]
                return path.startswith(pre) and "/" not in path[len(pre):] and path[len(pre):] != ""
            return path == pat

        patterns = ["a/**", "a/*", "a/b/**", "a/b/*", "a/b", "a/b/c"]
        samples = [
            "a/b", "a/b/c", "a/b/c/d", "a/x", "a/x/y", "b/c", "a", "a/b/c/d/e",
        ]
        for A, R in itertools.product(patterns, patterns):
            if write_path_subsumed(R, (A,)):
                for p in samples:
                    if concrete_within(p, R):
                        assert concrete_within(p, A), (
                            f"{A!r} claims to subsume {R!r} but admits path {p!r} "
                            f"under R and not A"
                        )

    def test_not_modelled_dimensions_reported(self):
        # horizon / task_kind etc. are surfaced as not-modelled, never silently
        # treated as contained.
        ration = ParsedRation(
            allowed_write_paths=("src/**",),
            allowed_commands=(),
            network_allowed=False,
            git_allowed=False,
        )
        result = check_containment(("src/**",), (), False, False, ration)
        assert result.ok is True
        assert set(result.not_modelled) == NOT_MODELLED

    def test_parse_ration_fail_closed(self):
        from maude.plan.ration_containment import RationParseError

        with pytest.raises(RationParseError):
            parse_ration(b"not json")
        with pytest.raises(RationParseError):
            parse_ration(b'["not", "an", "object"]')
