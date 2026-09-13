# SPDX-License-Identifier: Apache-2.0
"""Component-only Docket transport V1 checks for reviewed local copy."""

from __future__ import annotations

import base64
import json

import pytest

from maude.plan.document import (
    DocumentConstraintsV1,
    PlanDocumentV1,
    PlanNodeV1,
    StructuredWorkV1,
    SubmitterV1,
    canonical_json_bytes,
)
from maude.plan.local_compose import ag_executor_plan_identity
from maude.plan.reviewed_local_copy import ReviewedLocalCopyCompilerV1, ReviewedLocalCopyInputsV1
from maude.plan.reviewed_local_copy_executor import (
    CONFIG_SCHEMA,
    ExecutorRefusal,
    execute,
    reconcile,
)


def digest(letter: str) -> str:
    return "sha256:" + letter * 64


def executor_fixture(tmp_path):
    scratch = tmp_path / "scratch"; scratch.mkdir()
    state = tmp_path / "state"; state.mkdir()
    document = PlanDocumentV1(
        goal="copy", workspace="scratch",
        submitter=SubmitterV1("synthetic_agent", "imported_from_review", "fixture"),
        nodes=(PlanNodeV1("pn_copy", "copy", work=StructuredWorkV1(("result.txt",))),),
        constraints=DocumentConstraintsV1(declared_write_paths=("result.txt",)),
    )
    inputs = ReviewedLocalCopyInputsV1(
        digest("a"), "11111111-1111-4111-8111-111111111111", digest("d"),
        digest("b"), digest("c"), str(scratch), digest("e"), b"exact public text\n",
    )
    plan = json.loads(ReviewedLocalCopyCompilerV1().compile(document, inputs).handoff_bytes)["ag_executor_plan"]
    config = tmp_path / "config.json"
    config.write_bytes(canonical_json_bytes({
        "schema": CONFIG_SCHEMA,
        "executor_plan_base64": base64.b64encode(canonical_json_bytes(plan)).decode(),
        "state_root": str(state),
    }))
    dispatch = canonical_json_bytes({
        "attempt": digest("1"), "marker": digest("2"), "work_schema": "maude.reviewed-local-copy/v1",
        "work": ag_executor_plan_identity(plan), "subject": digest("b"), "scope": digest("c"),
    })
    return scratch, state, config, dispatch


def test_exact_copy_terminal_replay_and_canonical_outcome(tmp_path):
    scratch, _state, config, dispatch = executor_fixture(tmp_path)
    first = execute(config, dispatch)
    assert first.endswith(b"\n")
    assert json.loads(first)["outcome"] == "success"
    assert (scratch / "result.txt").read_bytes() == b"exact public text\n"
    assert execute(config, dispatch) == first
    assert reconcile(config, dispatch) == first


def test_dispatch_substitution_and_existing_or_symlink_destination_refuse(tmp_path):
    scratch, _state, config, dispatch = executor_fixture(tmp_path)
    changed = json.loads(dispatch); changed["scope"] = digest("f")
    with pytest.raises(ExecutorRefusal, match="sealed"):
        execute(config, canonical_json_bytes(changed))
    (scratch / "result.txt").symlink_to(tmp_path / "other")
    with pytest.raises(ExecutorRefusal, match="already exists"):
        execute(config, dispatch)


def test_reserved_interruption_reconciles_indeterminate_without_copy(tmp_path):
    scratch, state, config, dispatch = executor_fixture(tmp_path)
    attempt = digest("1").removeprefix("sha256:")
    directory = state / attempt; directory.mkdir()
    (directory / "record.json").write_bytes(canonical_json_bytes({
        "dispatch": json.loads(dispatch), "schema": "maude.reviewed-local-copy.executor-receipt/v1", "state": "reserved",
    }))
    outcome = json.loads(reconcile(config, dispatch))
    assert outcome["outcome"] == "indeterminate"
    assert not (scratch / "result.txt").exists()
    assert json.loads(execute(config, dispatch))["outcome"] == "indeterminate"
    assert not (scratch / "result.txt").exists()


def test_transport_unknown_fields_and_missing_evidence_fail_closed(tmp_path):
    _scratch, _state, config, dispatch = executor_fixture(tmp_path)
    bad = json.loads(dispatch); bad["schema"] = "v2"
    with pytest.raises(ExecutorRefusal, match="fields"):
        execute(config, canonical_json_bytes(bad))
    with pytest.raises(ExecutorRefusal, match="evidence"):
        reconcile(config, dispatch)
