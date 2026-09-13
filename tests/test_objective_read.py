# SPDX-License-Identifier: Apache-2.0
import json
import os

from maude.plan.cli import run
from maude.plan.document import PlanDocumentV1, PlanNodeV1, SubmitterV1
from maude.plan.objective_read import read_objective, MAX_DOCUMENT_BYTES


def document():
    return PlanDocumentV1(goal="Inspect a disposable result", workspace="/private/local-path",
        submitter=SubmitterV1("human", "human_written", "private-operator"),
        nodes=(PlanNodeV1("pn_one", "Read the result"),),
        acceptance_criteria=("Result is readable", "Result is readable"))


def test_exact_read_is_not_completion_or_publication(tmp_path):
    doc = document(); path = tmp_path / "plan.json"; path.write_bytes(doc.canonical_bytes)
    result = read_objective(path, doc.digest)
    assert result["availability"] == "available"
    assert result["publication"] == "operator_only"
    assert result["plan_digest"] == doc.digest
    assert result["acceptance_criteria"][0]["condition_id"] != result["acceptance_criteria"][1]["condition_id"]
    assert "private-operator" not in json.dumps(result)
    assert "/private/local-path" not in json.dumps(result)
    assert "completion" not in result and "authority" not in result


def test_mismatch_omits_authored_fields(tmp_path):
    doc = document(); path = tmp_path / "plan.json"; path.write_bytes(doc.canonical_bytes)
    result = read_objective(path, "sha256:" + "0" * 64)
    assert result["availability"] == "conflicting"
    assert result["error_code"] == "plan_digest_mismatch"
    assert "goal" not in result and "acceptance_criteria" not in result


def test_missing_invalid_symlink_and_fifo_are_explicit(tmp_path):
    digest = document().digest
    assert read_objective(tmp_path / "missing", digest)["error_code"] == "missing"
    path = tmp_path / "invalid"; path.write_bytes(b'{"schema":null,"schema":null}')
    assert read_objective(path, digest)["error_code"] == "invalid_document"
    link = tmp_path / "link"; link.symlink_to(path)
    assert read_objective(link, digest)["availability"] == "unavailable"
    fifo = tmp_path / "fifo"; os.mkfifo(fifo)
    assert read_objective(fifo, digest)["error_code"] == "not_regular_file"
    path.write_bytes(b" " * (MAX_DOCUMENT_BYTES + 1))
    assert read_objective(path, digest)["error_code"] == "document_too_large"


def test_cli_never_initializes_store(tmp_path, capsys):
    doc = document(); path = tmp_path / "plan.json"; path.write_bytes(doc.canonical_bytes)
    store = tmp_path / "absent" / "plans.sqlite"
    assert run(["--store", str(store), "--read-only", "objective-read", "--plan", str(path),
                "--expected-plan-digest", doc.digest]) == 0
    assert json.loads(capsys.readouterr().out)["plan_digest"] == doc.digest
    assert not store.parent.exists()


def test_cli_retains_structured_absence_and_conflict(tmp_path, capsys):
    doc = document(); path = tmp_path / "plan.json"
    assert run(["objective-read", "--plan", str(path), "--expected-plan-digest", doc.digest]) == 0
    assert json.loads(capsys.readouterr().out)["error_code"] == "missing"
    path.write_bytes(doc.canonical_bytes)
    assert run(["objective-read", "--plan", str(path), "--expected-plan-digest", "sha256:" + "0" * 64]) == 0
    assert json.loads(capsys.readouterr().out)["availability"] == "conflicting"
