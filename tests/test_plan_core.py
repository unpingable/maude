# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from maude.plan.checks import CheckReceiptV1, run_checks
from maude.plan.compiler import (
    CompilationResultV1,
    CompilerRegistryV1,
    CompilerUnavailable,
)
from maude.plan.diff import semantic_diff
from maude.plan.document import (
    DeclaredWorldRequirementV1,
    DocumentConstraintsV1,
    PlanDocumentError,
    PlanDocumentV1,
    PlanNodeV1,
    StructuredWorkV1,
    SubmitterV1,
    canonical_json_bytes,
    content_digest,
    import_plan_envelope,
)
from maude.plan.envelope import parse_plan_envelope
from maude.plan.store import (
    CheckApplicability,
    DraftConflict,
    DraftStore,
    EditOrigin,
    ExternalArtifactReferenceV1,
    LockReceiptV1,
    classify_check_receipts,
)


def now() -> datetime:
    return datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def document(*nodes: PlanNodeV1) -> PlanDocumentV1:
    return PlanDocumentV1(
        goal="Deploy café service",
        workspace="/srv/example",
        submitter=SubmitterV1("human", "human_written", "operator-1"),
        nodes=nodes
        or (
            PlanNodeV1("pn_inspect", "Inspect target"),
            PlanNodeV1("pn_apply", "Apply exact change", depends_on=("pn_inspect",)),
        ),
        constraints=DocumentConstraintsV1(
            declared_write_paths=("config/service.toml",),
            forbidden_paths=("secrets/**",),
            budget_tokens=1000,
            world_requirements=(
                DeclaredWorldRequirementV1(
                    "wr_service_available", "service remains available"
                ),
            ),
        ),
        acceptance_criteria=("service responds",),
    )


def test_canonical_serialization_vector_utf8_and_crlf_are_explicit():
    plan = document()
    canonical = plan.canonical_bytes
    assert canonical.decode().startswith('{"acceptance_criteria"')
    assert b"\r" not in canonical and not canonical.endswith(b"\n")
    pretty_crlf = json.dumps(plan.to_data(), ensure_ascii=False, indent=2).replace(
        "\n", "\r\n"
    )
    parsed = PlanDocumentV1.parse(pretty_crlf.encode())
    assert parsed.canonical_bytes == canonical
    assert (
        parsed.digest
        == plan.digest
        == ("sha256:9dde0916c67af63aae7de65449acec153706f80d5465fb41f27edff2a58d6e4c")
    )


def test_layout_fields_are_closed_out_of_semantic_schema():
    raw = document().to_data()
    raw["nodes"][0]["x"] = 10
    with pytest.raises(PlanDocumentError, match="unknown field"):
        PlanDocumentV1.from_data(raw)


@pytest.mark.parametrize("invalid_submitter", [
    SubmitterV1("human", "unsupported_origin", "example-operator"),
    SubmitterV1("unsupported_kind", "human_written", "example-operator"),
])
def test_create_refuses_invalid_wire_document_before_writing(tmp_path, invalid_submitter):
    path = tmp_path / "plans.sqlite"
    store = DraftStore(path, now=now)
    with pytest.raises(PlanDocumentError):
        store.create(replace(document(), submitter=invalid_submitter))
    assert store.list_drafts() == ()
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT count(*) FROM revisions").fetchone()[0] == 0


def test_invalid_successor_preserves_current_revision_and_history(tmp_path):
    path = tmp_path / "plans.sqlite"
    store = DraftStore(path, now=now)
    original = store.create(document())
    invalid = replace(original.document,
                      submitter=SubmitterV1("human", "unsupported_origin", "example-operator"))
    with pytest.raises(PlanDocumentError):
        store.save_successor(original.draft_id, original.revision_id, invalid,
                             edit_origin=EditOrigin.HUMAN)
    reopened = DraftStore(path, now=now)
    assert reopened.current(original.draft_id) == original
    assert reopened.revisions(original.draft_id) == (original,)
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_stable_node_identity_survives_order_and_diff_reports_only_reorder():
    before = document()
    after = replace(before, nodes=tuple(reversed(before.nodes)))
    result = semantic_diff(before, after)
    assert result.reordered is True
    assert result.changed == ()
    assert result.added == result.removed == ()
    assert before.nodes[0].node_id == after.nodes[1].node_id


def test_diff_distinguishes_node_content_work_and_document_constraints():
    before = document()
    changed_node = replace(
        before.nodes[1],
        description="Apply reviewed exact change",
        work=StructuredWorkV1(write_paths=("config/service.toml",)),
    )
    after = replace(
        before,
        nodes=(before.nodes[0], changed_node),
        acceptance_criteria=("service responds", "logs are clean"),
    )
    result = semantic_diff(before, after)
    assert result.changed[0].fields == ("description", "work")
    assert result.document_fields == ("acceptance_criteria",)


def test_checker_refuses_duplicates_broken_references_and_cycles_without_runtime_claims():
    plan = document(
        PlanNodeV1("pn_cycle", "Cycle", depends_on=("pn_cycle", "pn_missing")),
        PlanNodeV1("pn_same", "A"),
        PlanNodeV1("pn_same", "B"),
    )
    receipt = run_checks(plan, now=now)
    assert receipt.result == "refused"
    rules = {finding.rule_id for finding in receipt.findings}
    assert {
        "plan.node-id.unique",
        "plan.reference.exists",
        "plan.dependencies.acyclic",
    } <= rules
    rendered = json.dumps(receipt.to_data()).lower()
    for forbidden in ("standing", "currentness", "authorization", "admissibility"):
        assert forbidden not in rendered
    assert "service remains available" in json.dumps(plan.to_data())
    assert "currently available" not in rendered


def test_check_receipt_exact_digest_applicability_and_content_binding():
    first = document()
    receipt = run_checks(first, now=now)
    second = replace(first, goal=first.goal + "!")
    assert receipt.applies_to(first)
    assert not receipt.applies_to(second)
    tampered = receipt.to_data()
    tampered["plan_digest"] = second.digest
    with pytest.raises(ValueError, match="does not bind"):
        CheckReceiptV1.from_data(tampered)


def test_check_applicability_distinguishes_never_historical_retired_failure_and_pass():
    plan = document()
    passed = run_checks(plan, now=now)
    summary, projections = classify_check_receipts(plan.digest, ())
    assert summary == CheckApplicability.NEVER_CHECKED and projections == ()
    changed = replace(plan, goal="changed")
    summary, _ = classify_check_receipts(changed.digest, (passed,))
    assert summary == CheckApplicability.HISTORICAL_DIGEST
    retired_data = passed.unsigned_data()
    retired_data["checker_version"] = "0"
    retired_data["receipt_id"] = "ignored"
    retired_data["receipt_id"] = content_digest(
        canonical_json_bytes(
            {k: v for k, v in retired_data.items() if k != "receipt_id"}
        )
    )
    retired = CheckReceiptV1.from_data(retired_data)
    summary, _ = classify_check_receipts(plan.digest, (retired,))
    assert summary == CheckApplicability.RETIRED_CHECKER_OR_RULES
    summary, _ = classify_check_receipts(plan.digest, (passed,))
    assert summary == CheckApplicability.CURRENT_PASS
    failed = run_checks(replace(plan, goal=""), now=now)
    summary, _ = classify_check_receipts(failed.plan_digest, (failed,))
    assert summary == CheckApplicability.CURRENT_FINDINGS


def test_store_revision_lock_restart_drift_and_human_agent_same_boundary(tmp_path):
    path = tmp_path / "plans.sqlite"
    store = DraftStore(path, now=now)
    first = store.create(document(), draft_id="draft_" + "a" * 32)
    check = store.check(first.draft_id)
    lock = store.lock(first.draft_id)
    assert lock.plan_digest == check.plan_digest == first.plan_digest

    successor_document = replace(first.document, goal="Successor design")
    agent_revision = store.save_successor(
        first.draft_id,
        first.revision_id,
        successor_document,
        edit_origin=EditOrigin.AGENT,
    )
    assert isinstance(agent_revision.document, PlanDocumentV1)
    assert agent_revision.edit_origin == EditOrigin.AGENT
    assert (
        store.save_successor(
            first.draft_id,
            agent_revision.revision_id,
            replace(successor_document, goal="Human successor"),
            edit_origin=EditOrigin.HUMAN,
        ).document.__class__
        is agent_revision.document.__class__
    )

    reopened = DraftStore(path, now=now)
    refs = (
        ExternalArtifactReferenceV1(
            "handoff", "handoff-1", first.plan_digest, "nightshift"
        ),
        ExternalArtifactReferenceV1(
            "governed", "lineage-1", first.plan_digest, "nightshift"
        ),
    )
    projection = reopened.projection(first.draft_id, external_references=refs).to_data()
    assert projection["working_differs_from_locked"] is True
    assert projection["working_differs_from_handoff"] is True
    assert projection["working_differs_from_governed"] is True
    assert projection["external_references"][0]["plan_digest"] == first.plan_digest
    assert projection["current_revision"]["plan_digest"] != first.plan_digest
    assert projection["check_summary"] == "historical_digest"
    assert projection["last_check_receipt_id"] == check.receipt_id
    assert projection["last_applicable_check_receipt_id"] is None
    assert projection["last_lock_receipt_id"] == lock.lock_id
    assert len(reopened.revisions(first.draft_id)) == 3


def test_locked_revision_is_never_overwritten_and_conflict_refuses(tmp_path):
    store = DraftStore(tmp_path / "plans.sqlite", now=now)
    first = store.create(document())
    locked = store.lock(first.draft_id)
    second = store.save_successor(
        first.draft_id,
        first.revision_id,
        replace(first.document, goal="one byte changes digest!"),
        edit_origin=EditOrigin.HUMAN,
    )
    assert locked.plan_digest != second.plan_digest
    assert store.locks(first.draft_id)[0] == locked
    tampered = locked.to_data()
    tampered["plan_digest"] = second.plan_digest
    with pytest.raises(ValueError, match="does not bind"):
        LockReceiptV1.from_data(tampered)
    with pytest.raises(DraftConflict):
        store.save_successor(
            first.draft_id,
            first.revision_id,
            replace(first.document, goal="lost concurrent edit"),
            edit_origin=EditOrigin.AGENT,
        )


def test_recomputed_outer_receipt_digest_cannot_hide_revision_substitution(tmp_path):
    path = tmp_path / "plans.sqlite"
    store = DraftStore(path, now=now)
    first = store.create(document())
    receipt = store.check(first.draft_id)
    second = store.save_successor(
        first.draft_id,
        first.revision_id,
        replace(first.document, goal="substituted"),
        edit_origin=EditOrigin.HUMAN,
    )
    forged = receipt.unsigned_data()
    forged["plan_digest"] = second.plan_digest
    forged_id = content_digest(canonical_json_bytes(forged))
    forged["receipt_id"] = forged_id
    with sqlite3.connect(path) as db:
        db.execute(
            "UPDATE check_receipts SET receipt_id=?,plan_digest=?,record=? WHERE receipt_id=?",
            (
                forged_id,
                second.plan_digest,
                canonical_json_bytes(forged),
                receipt.receipt_id,
            ),
        )
    with pytest.raises(ValueError, match="persistence binding is contradictory"):
        store.check_receipts(first.draft_id)


def test_duplicate_exact_successor_is_idempotent(tmp_path):
    store = DraftStore(tmp_path / "plans.sqlite", now=now)
    first = store.create(document())
    changed = replace(first.document, goal="changed")
    one = store.save_successor(
        first.draft_id, first.revision_id, changed, edit_origin=EditOrigin.HUMAN
    )
    two = store.save_successor(
        first.draft_id, first.revision_id, changed, edit_origin=EditOrigin.HUMAN
    )
    assert one == two


def test_concurrent_conflicting_edits_cannot_silently_overwrite(tmp_path):
    path = tmp_path / "plans.sqlite"
    first = DraftStore(path, now=now).create(document())
    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def save(goal: str) -> None:
        local = DraftStore(path, now=now)
        barrier.wait()
        try:
            local.save_successor(
                first.draft_id,
                first.revision_id,
                replace(first.document, goal=goal),
                edit_origin=EditOrigin.HUMAN,
            )
            outcomes.append("saved")
        except DraftConflict:
            outcomes.append("conflict")

    threads = [threading.Thread(target=save, args=(goal,)) for goal in ("A", "B")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["conflict", "saved"]
    reopened = DraftStore(path, now=now)
    assert len(reopened.revisions(first.draft_id)) == 2


class _Inputs:
    schema = "test.compiler-input/v1"
    canonical_bytes = b'{"schema":"test.compiler-input/v1"}'


class _Compiler:
    compiler_id = "test.exact"
    compiler_version = "1"

    def compile(self, plan, inputs):
        return CompilationResultV1(
            self.compiler_id,
            self.compiler_version,
            plan.digest,
            inputs.schema,
            "sha256:" + hashlib.sha256(inputs.canonical_bytes).hexdigest(),
            plan.canonical_bytes + b"\n" + inputs.canonical_bytes,
        )


class _NondeterministicCompiler(_Compiler):
    compiler_id = "test.nondeterministic"

    def __init__(self):
        self.calls = 0

    def compile(self, plan, inputs):
        self.calls += 1
        result = super().compile(plan, inputs)
        return replace(
            result, handoff_bytes=result.handoff_bytes + str(self.calls).encode()
        )


def test_compiler_is_closed_and_deterministic_under_irrelevant_ambient_changes(
    tmp_path, monkeypatch
):
    registry = CompilerRegistryV1()
    with pytest.raises(CompilerUnavailable):
        registry.compile("generic prose", document(), _Inputs())
    registry.register("test", _Compiler())
    first = registry.compile("test", document(), _Inputs())
    old = os.getcwd()
    try:
        os.chdir(tmp_path)
        monkeypatch.setenv("IRRELEVANT_COMPILER_AMBIENT", "different")
        second = registry.compile("test", document(), _Inputs())
    finally:
        os.chdir(old)
    assert first == second
    registry.register("nondeterministic", _NondeterministicCompiler())
    with pytest.raises(ValueError, match="nondeterministic"):
        registry.compile("nondeterministic", document(), _Inputs())


def test_document_has_no_runtime_authority_or_presentation_fields():
    keys = json.dumps(document().to_data()).lower()
    for forbidden in (
        "campaign",
        "occurrence",
        "standing",
        "authorization",
        "spend",
        "settlement",
        "viewport",
        "zoom",
        "coordinate",
    ):
        assert forbidden not in keys


def test_legacy_envelope_import_is_explicit_stable_and_keeps_aggregate_work_separate():
    text = """---
plan_version: 1
goal: Inspect and update
workspace: /srv/example
submitter_kind: human
plan_origin: human_written
provenance:
  author: operator
steps: [inspect, update]
acceptance_criteria: [verified]
execution_request:
  write_paths: [config/service.toml]
  commands:
    - program: tool
      argv_prefix: [check]
---
historical prose
"""
    envelope = parse_plan_envelope(text)
    first = import_plan_envelope(envelope)
    second = import_plan_envelope(envelope)
    assert first == second
    assert [node.description for node in first.nodes] == ["inspect", "update"]
    assert len({node.node_id for node in first.nodes}) == 2
    assert all(node.work is None for node in first.nodes)
    assert first.execution_request is not None
    assert first.execution_request.work.write_paths == ("config/service.toml",)
    assert first.source_envelope_ref == envelope.plan_ref
