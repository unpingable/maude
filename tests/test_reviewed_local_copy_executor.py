# SPDX-License-Identifier: Apache-2.0
"""Component-only Docket transport V1 checks for reviewed local copy."""

from __future__ import annotations

import base64
import json
import os
import subprocess
from pathlib import Path
import threading

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
import maude.plan.reviewed_local_copy_executor as executor_module


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


def test_existing_regular_destination_refuses_without_changing_bytes(tmp_path):
    scratch, state, config, dispatch = executor_fixture(tmp_path)
    destination = scratch / "result.txt"
    sentinel = b"pre-existing application bytes\n"
    destination.write_bytes(sentinel)

    with pytest.raises(ExecutorRefusal, match="already exists"):
        execute(config, dispatch)

    assert destination.read_bytes() == sentinel
    attempt = state / digest("1").removeprefix("sha256:") / "record.json"
    record = json.loads(attempt.read_bytes())
    assert record["dispatch"] == json.loads(dispatch)
    assert record["schema"] == "maude.reviewed-local-copy.executor-receipt/v1"
    assert record["state"] == "indeterminate"


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


def test_short_writes_are_completed_for_result_and_record(tmp_path, monkeypatch):
    scratch, _state, config, dispatch = executor_fixture(tmp_path)
    real_write = os.write

    def short_write(descriptor, raw):
        return real_write(descriptor, bytes(raw[: max(1, len(raw) // 3)]))

    monkeypatch.setattr(executor_module.os, "write", short_write)
    outcome = json.loads(execute(config, dispatch))
    assert outcome["outcome"] == "success"
    assert (scratch / "result.txt").read_bytes() == b"exact public text\n"
    assert reconcile(config, dispatch) == canonical_json_bytes(outcome) + b"\n"


@pytest.mark.parametrize("mutation", [
    {"schema": "wrong", "state": "success", "receipt": digest("9")},
    {"schema": "maude.reviewed-local-copy.executor-receipt/v1", "state": "success", "receipt": digest("9")},
    {"schema": "maude.reviewed-local-copy.executor-receipt/v1", "state": "success"},
])
def test_mutated_or_partial_terminal_record_never_replays_success(tmp_path, mutation):
    _scratch, state, config, dispatch = executor_fixture(tmp_path)
    directory = state / digest("1").removeprefix("sha256:"); directory.mkdir()
    mutation["dispatch"] = json.loads(dispatch)
    (directory / "record.json").write_bytes(canonical_json_bytes(mutation))
    with pytest.raises(ExecutorRefusal, match="record|receipt"):
        reconcile(config, dispatch)
    with pytest.raises(ExecutorRefusal, match="record|receipt"):
        execute(config, dispatch)


def test_missing_record_in_reserved_attempt_fails_without_copy(tmp_path):
    scratch, state, config, dispatch = executor_fixture(tmp_path)
    (state / digest("1").removeprefix("sha256:")).mkdir()
    with pytest.raises(ExecutorRefusal, match="absent after reservation"):
        execute(config, dispatch)
    assert not (scratch / "result.txt").exists()


def test_concurrent_invocation_has_one_copy_and_one_indeterminate(tmp_path, monkeypatch):
    scratch, _state, config, dispatch = executor_fixture(tmp_path)
    entered = threading.Event(); release = threading.Event()
    real_write_all = executor_module._write_all

    def paused_write(descriptor, raw):
        if raw == b"exact public text\n":
            entered.set(); assert release.wait(5)
        real_write_all(descriptor, raw)

    monkeypatch.setattr(executor_module, "_write_all", paused_write)
    results = []
    worker = threading.Thread(target=lambda: results.append(json.loads(execute(config, dispatch))))
    worker.start(); assert entered.wait(5)
    second = json.loads(execute(config, dispatch))
    release.set(); worker.join(5)
    assert second["outcome"] == "indeterminate"
    assert results[0]["outcome"] == "success"
    assert (scratch / "result.txt").read_bytes() == b"exact public text\n"


def test_scratch_path_replacement_after_pinning_does_not_redirect_effect(tmp_path, monkeypatch):
    scratch, _state, config, dispatch = executor_fixture(tmp_path)
    pinned = tmp_path / "scratch-pinned"
    replacement = tmp_path / "scratch-replacement"
    real_write_atomic = executor_module._write_atomic
    calls = 0

    def replace_after_reservation(directory, name, raw):
        nonlocal calls
        real_write_atomic(directory, name, raw)
        calls += 1
        if calls == 1:
            scratch.rename(pinned)
            replacement.mkdir()
            replacement.rename(scratch)

    monkeypatch.setattr(executor_module, "_write_atomic", replace_after_reservation)
    assert json.loads(execute(config, dispatch))["outcome"] == "success"
    assert (pinned / "result.txt").read_bytes() == b"exact public text\n"
    assert not (scratch / "result.txt").exists()


def test_state_path_replacement_after_pinning_does_not_redirect_record(tmp_path, monkeypatch):
    scratch, state, config, dispatch = executor_fixture(tmp_path)
    pinned = tmp_path / "state-pinned"
    real_mkdir = executor_module.os.mkdir
    replaced = False

    def replace_after_attempt(name, mode=0o777, *, dir_fd=None):
        nonlocal replaced
        real_mkdir(name, mode, dir_fd=dir_fd)
        if dir_fd is not None and not replaced:
            replaced = True
            state.rename(pinned)
            real_mkdir(state, 0o700)

    monkeypatch.setattr(executor_module.os, "mkdir", replace_after_attempt)
    assert json.loads(execute(config, dispatch))["outcome"] == "success"
    attempt = digest("1").removeprefix("sha256:")
    assert (pinned / attempt / "record.json").is_file()
    assert not (state / attempt).exists()
    assert (scratch / "result.txt").read_bytes() == b"exact public text\n"


def test_closed_executor_zipapp_has_exact_closure_and_restricted_cli(tmp_path):
    root = Path(__file__).parents[1]
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()
    artifacts = []
    manifests = []
    for name in ("first", "second"):
        artifact = tmp_path / f"executor-{name}.pyz"
        manifest = tmp_path / f"executor-{name}.json"
        built = subprocess.run(
            [
                "/usr/bin/python3.12", str(root / "tools" / "build_reviewed_local_copy_validator.py"),
                "--role", "executor", "--output", str(artifact), "--manifest", str(manifest),
                "--source-revision", revision,
            ],
            check=False, capture_output=True, text=True,
        )
        assert built.returncode == 0, built.stderr
        artifacts.append(artifact)
        manifests.append(manifest)
    assert artifacts[0].read_bytes() == artifacts[1].read_bytes()
    assert manifests[0].read_bytes() == manifests[1].read_bytes()
    default_validator = tmp_path / "validator-default.pyz"
    explicit_validator = tmp_path / "validator-explicit.pyz"
    for artifact, role in ((default_validator, []), (explicit_validator, ["--role", "validator"])):
        manifest = artifact.with_suffix(".json")
        built = subprocess.run(
            [
                "/usr/bin/python3.12", str(root / "tools" / "build_reviewed_local_copy_validator.py"),
                *role, "--output", str(artifact), "--manifest", str(manifest),
                "--source-revision", revision,
            ],
            check=False, capture_output=True, text=True,
        )
        assert built.returncode == 0, built.stderr
    assert default_validator.read_bytes() == explicit_validator.read_bytes()
    package = json.loads(manifests[0].read_text())
    assert package["schema"] == "maude.reviewed-local-copy-executor-package/v1"
    assert package["closure"] == "maude.reviewed-local-copy-executor/imports-v1"
    assert "maude/plan/reviewed_local_copy_executor.py" in package["entries"]
    assert "maude/plan/reviewed_local_copy.py" in package["entries"]
    _scratch, _state, config, _dispatch = executor_fixture(tmp_path)
    plan_id = subprocess.run(
        [str(artifacts[0]), "plan-id", str(config)],
        check=False, capture_output=True, text=True, cwd=tmp_path,
        env={"PATH": os.environ["PATH"]},
    )
    assert plan_id.returncode == 0, plan_id.stderr
    assert plan_id.stdout.strip().startswith("sha256:")
    refused = subprocess.run(
        [str(artifacts[0]), "validate"], check=False, capture_output=True, text=True,
        cwd=tmp_path, env={"PATH": os.environ["PATH"]},
    )
    assert refused.returncode != 0
    assert "only the plan-id, execute, and reconcile operations" in refused.stderr
