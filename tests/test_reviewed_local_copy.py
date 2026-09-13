# SPDX-License-Identifier: Apache-2.0
"""Component-only conformance checks for maude.reviewed-local-copy/v1."""

from __future__ import annotations

import base64
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from maude.plan.document import (
    DocumentConstraintsV1,
    DocumentExecutionRequestV1,
    PlanDocumentV1,
    PlanNodeV1,
    StructuredWorkV1,
    SubmitterV1,
    canonical_json_bytes,
    content_digest,
)
from maude.plan.reviewed_local_copy import (
    BINDING_SCHEMA,
    COMPILER_CONTRACT,
    GovernedPlanBindingV1,
    ReviewedLocalCopyCompilerV1,
    ReviewedLocalCopyError,
    ReviewedLocalCopyInputsV1,
    ReviewedLocalCopyValidatorConfigV1,
    build_reviewed_local_copy_binding,
    compile_and_bind_reviewed_local_copy,
    validate_reviewed_local_copy_binding,
)
from maude.plan.store import DraftStore


def now() -> datetime:
    return datetime(2026, 9, 12, tzinfo=UTC)


CAMPAIGN = "sha256:" + "a" * 64
OCCURRENCE = "11111111-1111-4111-8111-111111111111"
PROGRAM = "sha256:" + "d" * 64
SUBJECT = "sha256:" + "b" * 64
SCOPE = "sha256:" + "c" * 64
OBSERVATION = "sha256:" + "e" * 64


def local_inputs(text: bytes) -> ReviewedLocalCopyInputsV1:
    return ReviewedLocalCopyInputsV1(
        CAMPAIGN, OCCURRENCE, PROGRAM, SUBJECT, SCOPE, "/tmp/fixture-scratch", OBSERVATION, text
    )


def document() -> PlanDocumentV1:
    return PlanDocumentV1(
        goal="Copy reviewed public text into executor scratch",
        workspace="exclusive-scratch",
        submitter=SubmitterV1("synthetic_agent", "imported_from_review", "component-fixture"),
        nodes=(PlanNodeV1("pn_copy", "Copy exact reviewed text", work=StructuredWorkV1(("result.txt",))),),
        constraints=DocumentConstraintsV1(declared_write_paths=("result.txt",)),
        acceptance_criteria=("result.txt equals reviewed source bytes",),
    )


def artifact(raw: bytes) -> dict[str, object]:
    return {
        "sha256": content_digest(raw),
        "byte_length": len(raw),
        "bytes_base64": base64.b64encode(raw).decode("ascii"),
    }


def binding_bytes(store_path):
    store = DraftStore(store_path, now=now)
    revision = store.create(document(), draft_id="draft_" + "a" * 32)
    checked = store.check(revision.draft_id)
    assert checked.result == "passed"
    lock = store.lock(revision.draft_id)
    inputs = local_inputs(b"public reviewed text\n")
    result = ReviewedLocalCopyCompilerV1().compile(revision.document, inputs)
    handoff = json.loads(result.handoff_bytes)
    assert handoff["schema"] == "nightshift.precompiled_workflow_proposal.v2"
    # Exact fields mirror Nightshift's deny-unknown-fields
    # PrecompiledWorkflowProposalV2, including a digest-backed Genesis program
    # and independently allocated UUID occurrence.
    assert set(handoff) == {
        "schema", "workflow_id", "intent_kind", "subject_digest",
        "immutable_parameters", "ag_executor_plan", "campaign_id",
        "occurrence_id", "mode", "proposal_input",
    }
    assert handoff["campaign_id"] == CAMPAIGN
    assert handoff["occurrence_id"] == OCCURRENCE
    assert handoff["mode"]["genesis"]["genesis"]["program"] == PROGRAM
    assert result.node_bindings[0].output_identity == __import__(
        "maude.plan.local_compose", fromlist=["ag_executor_plan_identity"]
    ).ag_executor_plan_identity(handoff["ag_executor_plan"])
    receipt = store.record_compilation(
        revision.draft_id, lock.lock_id, result,
        compiler_inputs=inputs.canonical_bytes,
        exact_work_identity=__import__("maude.plan.local_compose", fromlist=["ag_executor_plan_identity"]).ag_executor_plan_identity(json.loads(result.handoff_bytes)["ag_executor_plan"]),
    )
    raw = build_reviewed_local_copy_binding(revision.document, lock, inputs, result, receipt)
    return raw, json.loads(raw)


def test_component_only_conformance_recompiles_actual_readonly_store(tmp_path):
    path = tmp_path / "plans.sqlite"
    raw, value = binding_bytes(path)
    config = ReviewedLocalCopyValidatorConfigV1(str(path))
    result = validate_reviewed_local_copy_binding(raw + b"\n", config)
    assert result["result"] == "passed"
    assert result["binding_id"] == value["binding_id"]
    assert DraftStore.open_readonly(path).current("draft_" + "a" * 32).plan_digest == value["plan_document_digest"]


def test_lock_without_passing_receipt_refuses_component_contract(tmp_path):
    path = tmp_path / "plans.sqlite"
    raw, _ = binding_bytes(path)
    # Remove all receipts after the binding is constructed. The lock is still
    # structurally valid but must not be treated as a successful check.
    import sqlite3
    with sqlite3.connect(path) as db:
        db.execute("DELETE FROM check_receipts")
    with pytest.raises(ReviewedLocalCopyError, match="applicable checks"):
        validate_reviewed_local_copy_binding(raw, ReviewedLocalCopyValidatorConfigV1(str(path)))


def test_outer_identity_and_noncanonical_transport_refuse(tmp_path):
    raw, value = binding_bytes(tmp_path / "plans.sqlite")
    changed = dict(value)
    changed["work"] = "sha256:" + "d" * 64
    with pytest.raises(ReviewedLocalCopyError, match="identity"):
        GovernedPlanBindingV1.from_bytes(canonical_json_bytes(changed))
    with pytest.raises(ReviewedLocalCopyError, match="canonical"):
        GovernedPlanBindingV1.from_bytes(b"{ \"schema\": \"" + BINDING_SCHEMA.encode() + b"\"}")
    float_length = dict(value)
    float_artifacts = dict(value["artifacts"])
    float_plan = dict(float_artifacts["plan_document"])
    float_plan["byte_length"] = float(float_plan["byte_length"])
    float_artifacts["plan_document"] = float_plan
    float_length["artifacts"] = float_artifacts
    unsigned = {key: item for key, item in float_length.items() if key != "binding_id"}
    float_length["binding_id"] = content_digest(
        BINDING_SCHEMA.encode() + b"\0" + canonical_json_bytes(unsigned)
    )
    with pytest.raises(ReviewedLocalCopyError, match="floats"):
        GovernedPlanBindingV1.from_bytes(canonical_json_bytes(float_length))


def test_compiler_refuses_commands_or_nonfixed_destination():
    inputs = local_inputs(b"x")
    wrong = PlanDocumentV1(
        goal="wrong", workspace="scratch",
        submitter=SubmitterV1("synthetic_agent", "imported_from_review", "fixture"),
        nodes=(PlanNodeV1("pn_wrong", "wrong", work=StructuredWorkV1(("other.txt",))),),
        constraints=DocumentConstraintsV1(),
    )
    with pytest.raises(ReviewedLocalCopyError, match="result.txt"):
        ReviewedLocalCopyCompilerV1().compile(wrong, inputs)


def test_compiler_refuses_extra_work_and_non_utf8_text():
    inputs = local_inputs(b"x")
    extra = PlanDocumentV1(
        goal="extra", workspace="scratch",
        submitter=SubmitterV1("synthetic_agent", "imported_from_review", "fixture"),
        nodes=(
            PlanNodeV1("pn_copy", "copy", work=StructuredWorkV1(("result.txt",))),
            PlanNodeV1("pn_extra", "extra", work=StructuredWorkV1(("result.txt",))),
        ),
        constraints=DocumentConstraintsV1(declared_write_paths=("result.txt",)),
    )
    with pytest.raises(ReviewedLocalCopyError, match="exactly one"):
        ReviewedLocalCopyCompilerV1().compile(extra, inputs)
    aggregate = PlanDocumentV1(
        goal="aggregate", workspace="scratch",
        submitter=SubmitterV1("synthetic_agent", "imported_from_review", "fixture"),
        nodes=(PlanNodeV1("pn_copy", "copy", work=StructuredWorkV1(("result.txt",))),),
        constraints=DocumentConstraintsV1(declared_write_paths=("result.txt",)),
        execution_request=DocumentExecutionRequestV1(StructuredWorkV1(("result.txt",))),
    )
    with pytest.raises(ReviewedLocalCopyError, match="exactly one"):
        ReviewedLocalCopyCompilerV1().compile(aggregate, inputs)
    with pytest.raises(ReviewedLocalCopyError, match="UTF-8"):
        local_inputs(b"\xff")


def test_historical_same_digest_lock_needs_and_accepts_current_pass(tmp_path):
    path = tmp_path / "plans.sqlite"
    store = DraftStore(path, now=now)
    first = store.create(document(), draft_id="draft_" + "e" * 32)
    store.check(first.draft_id)
    store.lock(first.draft_id)
    middle = store.save_successor(
        first.draft_id, first.revision_id,
        PlanDocumentV1(
            goal="temporary", workspace=first.document.workspace,
            submitter=first.document.submitter, nodes=first.document.nodes,
            constraints=first.document.constraints,
            acceptance_criteria=first.document.acceptance_criteria,
        ), edit_origin=__import__("maude.plan.store", fromlist=["EditOrigin"]).EditOrigin.HUMAN,
    )
    current = store.save_successor(
        first.draft_id, middle.revision_id, first.document,
        edit_origin=__import__("maude.plan.store", fromlist=["EditOrigin"]).EditOrigin.HUMAN,
    )
    inherited_lock = store.lock(first.draft_id)
    assert inherited_lock.applicable_check_receipts  # from the earlier same-digest A
    store._now = lambda: now() + timedelta(seconds=1)
    store.check(first.draft_id, current.revision_id)  # configured current pass is separate
    inputs = local_inputs(b"x")
    raw = compile_and_bind_reviewed_local_copy(store, first.draft_id, inputs)
    assert validate_reviewed_local_copy_binding(
        raw, ReviewedLocalCopyValidatorConfigV1(str(path))
    )["result"] == "passed"


def test_supported_compile_and_pinned_readonly_validator_cli(tmp_path):
    path = tmp_path / "plans.sqlite"
    store = DraftStore(path, now=now)
    revision = store.create(document(), draft_id="draft_" + "f" * 32)
    store.check(revision.draft_id)
    store.lock(revision.draft_id)
    inputs = local_inputs(b"cli text")
    input_path = tmp_path / "inputs.json"; input_path.write_bytes(inputs.canonical_bytes)
    output_path = tmp_path / "binding.json"
    config_path = tmp_path / "validator.json"
    config_path.write_bytes(ReviewedLocalCopyValidatorConfigV1(str(path)).canonical_bytes)
    env = {**__import__("os").environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src")}
    compiled = subprocess.run(
        [sys.executable, "-m", "maude.plan.reviewed_local_copy", "compile", "--store", str(path), "--draft-id", revision.draft_id, "--inputs", str(input_path), "--output", str(output_path)],
        check=False, capture_output=True, text=True, env=env,
    )
    assert compiled.returncode == 0, compiled.stderr
    checked = subprocess.run(
        [sys.executable, "-m", "maude.plan.reviewed_local_copy", "validate", "--config", str(config_path), "--binding", str(output_path)],
        check=False, capture_output=True, text=True, env=env,
    )
    assert checked.returncode == 0, checked.stderr
    assert json.loads(checked.stdout)["result"] == "passed"


def test_closed_validator_zipapp_embeds_its_import_closure(tmp_path):
    root = Path(__file__).parents[1]
    artifact = tmp_path / "reviewed-local-copy-validator.pyz"
    manifest = tmp_path / "reviewed-local-copy-validator.json"
    built = subprocess.run(
        [
            "/usr/bin/python3.12",
            str(root / "tools" / "build_reviewed_local_copy_validator.py"),
            "--output",
            str(artifact),
            "--manifest",
            str(manifest),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert built.returncode == 0, built.stderr
    package = json.loads(manifest.read_text())
    assert package["interpreter"] == "/usr/bin/python3.12"
    assert "maude/plan/reviewed_local_copy.py" in package["entries"]
    assert "yaml/__init__.py" in package["entries"]
    help_text = subprocess.run(
        [str(artifact), "--help"], check=False, capture_output=True, text=True
    )
    assert help_text.returncode == 0
    assert "compile" not in help_text.stdout
