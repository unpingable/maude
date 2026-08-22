# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import dataclasses
import importlib.util
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from maude.plan.compiler import CompilationReceiptV1, CompilerRegistryV1
from maude.plan.document import (
    DeclaredWorldRequirementV1,
    DocumentConstraintsV1,
    PlanCommandV1,
    PlanDocumentV1,
    PlanNodeV1,
    StructuredWorkV1,
    SubmitterV1,
    canonical_json_bytes,
)
from maude.plan.local_compose import (
    LocalComposeCompilerError,
    LocalComposeWorkflowCompilerV1,
    LocalComposeWorkflowInputsV1,
    NodeActionV1,
    ag_executor_plan_identity,
    executor_plan_from_handoff,
)
from maude.plan.store import DraftStore

DIGEST = "sha256:" + "1" * 64
IMAGE = "python:3.13-alpine@sha256:" + "2" * 64
EXECUTOR_PATH = (
    Path(__file__).parents[1]
    / "qualification"
    / "synthetic_cache"
    / "local_compose_executor.py"
)


def executor_module():
    spec = importlib.util.spec_from_file_location(
        "local_compose_executor", EXECUTOR_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def executor_fixture(tmp_path: Path):
    result = LocalComposeWorkflowCompilerV1().compile(document(), inputs(tmp_path))
    plan = executor_plan_from_handoff(result.handoff_bytes)
    plan_bytes = canonical_json_bytes(plan)
    path = tmp_path / "executor-plan.json"
    path.write_bytes(plan_bytes)
    module = executor_module()
    plan_id = module.exact_plan_id(plan_bytes)
    dispatch = {
        "attempt": "sha256:" + "8" * 64,
        "marker": "sha256:" + "9" * 64,
        "scope": plan["scope_digest"],
        "subject": plan["subject_digest"],
        "work": plan_id,
        "work_schema": "maude.local-compose-workflow/v1",
    }
    return module, plan, path, plan_id, dispatch


def node(node_id: str, action: str, depends_on: tuple[str, ...] = ()) -> PlanNodeV1:
    return PlanNodeV1(
        node_id,
        action.replace("_", " "),
        depends_on,
        StructuredWorkV1(commands=(PlanCommandV1("maude-local-compose", (action,)),)),
        acceptance_criteria=(f"{action} is observed exactly",),
        stop_conditions=("stop on any scope or identity mismatch",),
    )


def document() -> PlanDocumentV1:
    return PlanDocumentV1(
        goal="Qualify a disposable local two-cache HTTP platform",
        workspace="synthetic-cache",
        submitter=SubmitterV1("human", "human_written", "qualification"),
        nodes=(
            node("pn_workspace", "establish_workspace"),
            node("pn_origin", "define_origin", ("pn_workspace",)),
            node("pn_cache", "define_cache", ("pn_origin",)),
            node("pn_cache_a", "define_cache_a", ("pn_cache",)),
            node("pn_cache_b", "define_cache_b", ("pn_cache",)),
            node(
                "pn_front",
                "define_front_door",
                ("pn_cache_a", "pn_cache_b"),
            ),
            node("pn_validate", "validate_configuration", ("pn_front",)),
            node("pn_start", "start_platform", ("pn_validate",)),
            node("pn_health", "verify_health", ("pn_start",)),
            node("pn_cache_behavior", "verify_cache_behavior", ("pn_health",)),
            node("pn_stop_a", "stop_cache_a", ("pn_cache_behavior",)),
            node(
                "pn_continued",
                "verify_continued_service",
                ("pn_stop_a",),
            ),
            node("pn_restore", "restore_cache_a", ("pn_continued",)),
            node("pn_accept", "final_acceptance", ("pn_restore",)),
            node("pn_teardown", "teardown", ("pn_accept",)),
        ),
        constraints=DocumentConstraintsV1(
            declared_write_paths=("synthetic-cache-workspace",),
            forbidden_paths=("repository", "user-home"),
            world_requirements=(
                DeclaredWorldRequirementV1(
                    "wr_front_available",
                    "front door remains available while one cache is stopped",
                ),
            ),
        ),
        acceptance_criteria=(
            "both caches show deterministic MISS then HIT evidence",
            "teardown leaves no campaign containers running",
        ),
    )


def inputs(tmp_path: Path, *, action: str = "qualify") -> LocalComposeWorkflowInputsV1:
    actions = (
        (NodeActionV1("pn_teardown", "teardown"),)
        if action == "teardown"
        else tuple(
            NodeActionV1(item.node_id, item.work.commands[0].argv_prefix[0])
            for item in document().nodes
            if item.node_id != "pn_teardown" and item.work is not None
        )
    )
    return LocalComposeWorkflowInputsV1(
        action=action,
        workspace=str(tmp_path / "maude-cache-test"),
        project_name="maude-cache-test",
        front_port=8080,
        image=IMAGE,
        docker_program="/snap/bin/docker",
        docker_program_identity=DIGEST,
        docker_client_version="29.6.1",
        docker_server_version="29.6.1",
        compose_version="5.3.1",
        campaign_id=DIGEST,
        occurrence_id=(
            "00000000-0000-4000-8000-000000000001"
            if action == "qualify"
            else "00000000-0000-4000-8000-000000000002"
        ),
        program_id="sha256:" + "3" * 64,
        observation_id="sha256:" + ("4" if action == "qualify" else "5") * 64,
        subject_digest="sha256:" + "6" * 64,
        scope_digest="sha256:" + "7" * 64,
        proposal_class="initial" if action == "qualify" else "successor",
        node_actions=actions,
    )


def test_exact_compiler_emits_nightshift_handoff_and_node_bindings(tmp_path: Path):
    registry = CompilerRegistryV1()
    registry.register("local-compose", LocalComposeWorkflowCompilerV1())
    result = registry.compile("local-compose", document(), inputs(tmp_path))
    handoff = json.loads(result.handoff_bytes)
    plan = executor_plan_from_handoff(result.handoff_bytes)
    assert handoff["schema"] == "nightshift.precompiled_workflow_proposal.v2"
    assert (
        handoff["mode"]["genesis"]["genesis"]["expected_ag_work"]
        == handoff["proposal_input"]["proposal"]["work"]
    )
    assert handoff["proposal_input"]["proposal"]["work"] == ag_executor_plan_identity(
        plan
    )
    assert {item.node_id for item in result.node_bindings} == {
        node.node_id for node in document().nodes if node.node_id != "pn_teardown"
    }


def test_compiler_refuses_prose_or_structured_work_substitution(tmp_path: Path):
    bad = dataclasses.replace(
        document(),
        nodes=(
            dataclasses.replace(document().nodes[0], work=None),
            *document().nodes[1:],
        ),
    )
    with pytest.raises(LocalComposeCompilerError, match="lacks exact structured work"):
        LocalComposeWorkflowCompilerV1().compile(bad, inputs(tmp_path))


def test_compiler_is_independent_of_cwd_and_irrelevant_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    compiler = LocalComposeWorkflowCompilerV1()
    first = compiler.compile(document(), inputs(tmp_path))
    other = tmp_path / "other-cwd"
    other.mkdir()
    monkeypatch.chdir(other)
    monkeypatch.setenv("HOME", str(tmp_path / "substituted-home"))
    monkeypatch.setenv("PATH", "/definitely/not/the/docker/path")
    second = compiler.compile(document(), inputs(tmp_path))
    assert second == first


def test_identical_locked_bytes_can_produce_distinct_intentional_handoffs(
    tmp_path: Path,
):
    compiler = LocalComposeWorkflowCompilerV1()
    qualify = compiler.compile(document(), inputs(tmp_path))
    teardown = compiler.compile(document(), inputs(tmp_path, action="teardown"))
    assert qualify.source_plan_digest == teardown.source_plan_digest
    assert qualify.compiler_inputs_digest != teardown.compiler_inputs_digest
    assert qualify.handoff_digest != teardown.handoff_digest
    assert ag_executor_plan_identity(
        executor_plan_from_handoff(qualify.handoff_bytes)
    ) != ag_executor_plan_identity(executor_plan_from_handoff(teardown.handoff_bytes))


def test_compilation_receipt_persists_exact_inputs_output_and_lock(tmp_path: Path):
    def now() -> datetime:
        return datetime(2026, 8, 22, 12, tzinfo=UTC)

    store = DraftStore(tmp_path / "drafts.sqlite", now=now)
    revision = store.create(document(), draft_id="draft_cache")
    lock = store.lock(revision.draft_id)
    compiler_inputs = inputs(tmp_path)
    result = LocalComposeWorkflowCompilerV1().compile(document(), compiler_inputs)
    work = ag_executor_plan_identity(executor_plan_from_handoff(result.handoff_bytes))
    receipt = store.record_compilation(
        revision.draft_id,
        lock.lock_id,
        result,
        compiler_inputs=compiler_inputs.canonical_bytes,
        exact_work_identity=work,
    )
    reopened = DraftStore(tmp_path / "drafts.sqlite", now=now)
    [(loaded, loaded_inputs, loaded_output)] = reopened.compilations(revision.draft_id)
    assert loaded == receipt
    assert CompilationReceiptV1.from_data(receipt.to_data()) == receipt
    assert loaded_inputs == compiler_inputs.canonical_bytes
    assert loaded_output == result.handoff_bytes
    assert (
        reopened.projection(revision.draft_id).to_data()["last_compilation_receipt_id"]
        == receipt.compilation_id
    )


def test_compilation_receipt_refuses_wrong_lock_or_substituted_inputs(tmp_path: Path):
    store = DraftStore(tmp_path / "drafts.sqlite")
    revision = store.create(document(), draft_id="draft_cache")
    lock = store.lock(revision.draft_id)
    compiler_inputs = inputs(tmp_path)
    result = LocalComposeWorkflowCompilerV1().compile(document(), compiler_inputs)
    work = ag_executor_plan_identity(executor_plan_from_handoff(result.handoff_bytes))
    with pytest.raises(Exception, match="exact lock receipt"):
        store.record_compilation(
            revision.draft_id,
            DIGEST,
            result,
            compiler_inputs=compiler_inputs.canonical_bytes,
            exact_work_identity=work,
        )
    with pytest.raises(Exception, match="does not bind"):
        store.record_compilation(
            revision.draft_id,
            lock.lock_id,
            result,
            compiler_inputs=compiler_inputs.canonical_bytes + b" ",
            exact_work_identity=work,
        )


def test_executor_plan_never_contains_ambient_process_values(tmp_path: Path):
    result = LocalComposeWorkflowCompilerV1().compile(document(), inputs(tmp_path))
    text = result.handoff_bytes.decode("utf-8")
    assert os.environ.get("HOME", "unavailable-home") not in text
    assert str(Path.cwd()) not in text
    assert "authorization" not in text
    assert "standing" not in text


def test_closed_executor_plan_id_and_dispatch_substitution(tmp_path: Path):
    module, plan, path, plan_id, dispatch = executor_fixture(tmp_path)
    loaded, loaded_bytes = module.load_plan(path)
    assert loaded == plan
    assert module.exact_plan_id(loaded_bytes) == plan_id
    assert module.validate_dispatch(plan, dispatch, plan_id) == dispatch
    for field in ("work", "subject", "scope"):
        substituted = {**dispatch, field: "sha256:" + "a" * 64}
        with pytest.raises(module.Refusal, match="dispatch_binding"):
            module.validate_dispatch(plan, substituted, plan_id)
    with pytest.raises(module.Refusal, match="dispatch_fields"):
        module.validate_dispatch(plan, {**dispatch, "command": "docker rm"}, plan_id)


def test_executor_reconciliation_is_observation_only_and_exact_replay(
    tmp_path: Path,
):
    module, plan, path, _, dispatch = executor_fixture(tmp_path)
    first = subprocess.run(
        [str(EXECUTOR_PATH), "reconcile", str(path)],
        input=canonical_json_bytes(dispatch),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert json.loads(first.stdout)["outcome"] == "indeterminate"
    workspace = Path(plan["workspace"])
    assert not workspace.exists()

    docket_outcome = {
        "attempt": dispatch["attempt"],
        "marker": dispatch["marker"],
        "outcome": "success",
        "receipt": "sha256:" + "b" * 64,
    }
    evidence = {
        "dispatch": dispatch,
        "docket_outcome": docket_outcome,
        "evidence": {"campaign_containers_running": 0},
        "evidence_schema": "maude.local-compose.executor-evidence/v1",
        "observed_at_unix_ms": 1,
        "outcome": "success",
    }
    prior = module.attempt_path(workspace, dispatch["attempt"])
    module.write_once(prior, evidence)
    for operation in ("execute", "reconcile"):
        replay = subprocess.run(
            [str(EXECUTOR_PATH), operation, str(path)],
            input=canonical_json_bytes(dispatch),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert json.loads(replay.stdout) == docket_outcome
    assert json.loads(prior.read_bytes()) == evidence


def test_executor_rejects_symlink_malformed_and_oversized_configs(tmp_path: Path):
    module, _, path, _, _ = executor_fixture(tmp_path)
    link = tmp_path / "plan-link.json"
    link.symlink_to(path)
    with pytest.raises(OSError):
        module.load_plan(link)

    malformed = tmp_path / "malformed.json"
    malformed.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(module.Refusal, match="config_not_exact_canonical_json"):
        module.load_plan(malformed)

    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(b"{" + b" " * module.MAX_CONFIG + b"}")
    with pytest.raises(module.Refusal, match="config_not_bounded_regular_file"):
        module.load_plan(oversized)


def test_teardown_observes_project_inventory_when_workspace_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    module, plan, _, _, _ = executor_fixture(tmp_path)
    workspace = Path(plan["workspace"])
    observed: list[tuple[str, ...]] = []

    def empty_inventory(
        _program: str,
        arguments: list[str],
        _workspace: Path,
        *,
        timeout: int = 120,
    ) -> SimpleNamespace:
        del timeout
        observed.append(tuple(arguments))
        return SimpleNamespace(stdout=b"", stderr=b"", returncode=0)

    monkeypatch.setattr(module, "run", empty_inventory)
    evidence = module.teardown(plan, "docker", workspace)
    assert evidence == {
        "campaign_containers_running": 0,
        "campaign_networks_remaining": 0,
        "workspace_retained_for_evidence": False,
    }
    assert any(arguments[:2] == ("ps", "--all") for arguments in observed)
    assert any(arguments[:2] == ("network", "ls") for arguments in observed)

    def retained_container(
        _program: str,
        arguments: list[str],
        _workspace: Path,
        *,
        timeout: int = 120,
    ) -> SimpleNamespace:
        del timeout
        output = b"deadbeef\n" if arguments[0] == "ps" else b""
        return SimpleNamespace(stdout=output, stderr=b"", returncode=0)

    monkeypatch.setattr(module, "run", retained_container)
    with pytest.raises(module.AcceptanceFailure, match="left_campaign_containers"):
        module.teardown(plan, "docker", workspace)
