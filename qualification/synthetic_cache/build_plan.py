#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Build the real Plan Core witness for the disposable cache campaign.

The script deliberately performs planning before deployment.  It creates an
imperfect-but-parseable draft, records the check finding, repairs that exact
finding through the ordinary agent proposal/CAS boundary, records a separate
human revision, checks and locks the result, and finally invokes the one closed
local-Compose compiler for qualify and teardown handoffs.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from maude.design.providers import DeterministicFixtureProvider
from maude.plan.compiler import CompilerRegistryV1
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
    LOCAL_COMPOSE_WORK_SCHEMA,
    LocalComposeWorkflowCompilerV1,
    LocalComposeWorkflowInputsV1,
    NodeActionV1,
    ag_executor_plan_identity,
    executor_plan_from_handoff,
)
from maude.plan.operations import (
    PlanOperationV1,
    UpdateDocumentV1,
    apply_plan_operation,
)
from maude.plan.proposal_service import ProposalService
from maude.plan.proposal_store import ProposalStore
from maude.plan.proposals import ProposalFindingContextV1, ProposalScopeV1
from maude.plan.store import DraftStore, EditOrigin

FIXED_TIME = datetime(2026, 8, 22, 18, 0, tzinfo=UTC)
DRAFT_ID = "draft_synthetic_cache_platform"
PROJECT_NAME = "maude-cache-birthday"


def now() -> datetime:
    return FIXED_TIME


def node(
    node_id: str,
    description: str,
    action: str,
    depends_on: tuple[str, ...] = (),
    *,
    acceptance: tuple[str, ...],
) -> PlanNodeV1:
    return PlanNodeV1(
        node_id=node_id,
        description=description,
        depends_on=depends_on,
        work=StructuredWorkV1(
            write_paths=("synthetic-cache-workspace",),
            commands=(PlanCommandV1("maude-local-compose", (action,)),),
        ),
        acceptance_criteria=acceptance,
        stop_conditions=(
            "Stop on any plan, image, runtime, workspace, or scope identity mismatch",
        ),
    )


def initial_document() -> PlanDocumentV1:
    """Return the real draft with one deliberate duplicate dependency."""
    nodes = (
        node(
            "pn_workspace",
            "Establish the bounded disposable workspace",
            "establish_workspace",
            acceptance=("Workspace is confined to the declared synthetic path",),
        ),
        node(
            "pn_origin",
            "Define the deterministic HTTP origin",
            "define_origin",
            ("pn_workspace",),
            acceptance=("Origin exposes health, content, and request-count evidence",),
        ),
        node(
            "pn_cache",
            "Define the closed cache implementation",
            "define_cache",
            ("pn_origin",),
            acceptance=("Cache reports explicit HIT or MISS and cache identity",),
        ),
        node(
            "pn_cache_a",
            "Define independent cache instance A",
            "define_cache_a",
            ("pn_cache",),
            acceptance=("cache-a has an independent in-memory cache",),
        ),
        node(
            "pn_cache_b",
            "Define independent cache instance B",
            "define_cache_b",
            ("pn_cache",),
            acceptance=("cache-b has an independent in-memory cache",),
        ),
        node(
            "pn_front",
            "Define the loopback front door with bounded failover",
            "define_front_door",
            ("pn_cache_a", "pn_cache_b"),
            acceptance=("Front door alternates healthy caches and fails over once",),
        ),
        node(
            "pn_validate",
            "Validate the exact generated Compose configuration",
            "validate_configuration",
            ("pn_front",),
            acceptance=("The pinned Compose runtime accepts the exact configuration",),
        ),
        node(
            "pn_start",
            "Start the bounded local cache platform",
            "start_platform",
            ("pn_validate",),
            acceptance=("All four declared containers become healthy",),
        ),
        node(
            "pn_health",
            "Verify front-door health through the internal observer",
            "verify_health",
            ("pn_start",),
            acceptance=("The internal health request returns HTTP 200",),
        ),
        node(
            "pn_cache_behavior",
            "Verify independent MISS then HIT behavior",
            "verify_cache_behavior",
            ("pn_health",),
            acceptance=(
                "Four equivalent requests prove MISS/A, MISS/B, HIT/A, HIT/B",
                "Origin counters prove two independent cache fills",
            ),
        ),
        node(
            "pn_stop_a",
            "Stop only cache instance A",
            "stop_cache_a",
            ("pn_cache_behavior",),
            acceptance=("cache-a stops without changing the other services",),
        ),
        node(
            "pn_continued",
            "Verify continued front-door service through cache B",
            "verify_continued_service",
            # Deliberate real planning defect: duplicate declaration.
            ("pn_stop_a", "pn_stop_a"),
            acceptance=("All bounded failure requests are served by cache-b",),
        ),
        node(
            "pn_restore",
            "Restore cache instance A",
            "restore_cache_a",
            ("pn_continued",),
            acceptance=("Both cache identities become observable again",),
        ),
        node(
            "pn_accept",
            "Record final topology and acceptance evidence",
            "final_acceptance",
            ("pn_restore",),
            acceptance=(
                "Acceptance evidence binds actual HTTP and container observations",
            ),
        ),
        node(
            "pn_teardown",
            "Tear down only the synthetic Compose project",
            "teardown",
            ("pn_accept",),
            acceptance=("No containers for the exact project remain running",),
        ),
    )
    return PlanDocumentV1(
        goal="Design, govern, deploy, verify, and remove a disposable two-cache HTTP platform",
        workspace="synthetic-cache-workspace",
        submitter=SubmitterV1(
            kind="human",
            origin="human_written",
            author="synthetic-campaign-operator",
        ),
        nodes=nodes,
        constraints=DocumentConstraintsV1(
            declared_write_paths=("synthetic-cache-workspace",),
            forbidden_paths=("repository", "user-home", "unrelated-docker-projects"),
            halt_if="Any exact identity, loopback containment, or acceptance check fails",
            world_requirements=(
                DeclaredWorldRequirementV1(
                    "wr_front_available",
                    "The front door must remain available while one cache is stopped",
                ),
                DeclaredWorldRequirementV1(
                    "wr_local_only",
                    "The front door must remain internal to the campaign network",
                ),
                DeclaredWorldRequirementV1(
                    "wr_clean_teardown",
                    "Teardown must leave no campaign containers running",
                ),
            ),
        ),
        acceptance_criteria=(
            "First equivalent request to each independent cache is MISS",
            "Subsequent equivalent request to each independent cache is HIT",
            "Origin request count demonstrates caching rather than command success",
            "Loss of cache-a does not make the front door unavailable",
            "Restoration makes both cache identities observable",
            "Teardown leaves no synthetic campaign containers running",
        ),
    )


def write_exact(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = value if isinstance(value, bytes) else canonical_json_bytes(value)
    path.write_bytes(encoded)


def compiler_inputs(
    document: PlanDocumentV1,
    *,
    action: str,
    workspace: Path,
    project_name: str = PROJECT_NAME,
    proposal_class: str | None = None,
    front_port: int,
    image: str,
    docker_program: Path,
    docker_program_identity: str,
    docker_client_version: str,
    docker_server_version: str,
    compose_version: str,
    campaign_id: str,
    program_id: str,
    occurrence_id: str,
    observation_id: str,
    subject_digest: str,
    scope_digest: str,
) -> LocalComposeWorkflowInputsV1:
    selected = (
        (next(item for item in document.nodes if item.node_id == "pn_teardown"),)
        if action == "teardown"
        else tuple(item for item in document.nodes if item.node_id != "pn_teardown")
    )
    return LocalComposeWorkflowInputsV1(
        action=action,
        workspace=str(workspace),
        project_name=project_name,
        front_port=front_port,
        image=image,
        docker_program=str(docker_program),
        docker_program_identity=docker_program_identity,
        docker_client_version=docker_client_version,
        docker_server_version=docker_server_version,
        compose_version=compose_version,
        campaign_id=campaign_id,
        occurrence_id=occurrence_id,
        program_id=program_id,
        observation_id=observation_id,
        subject_digest=subject_digest,
        scope_digest=scope_digest,
        proposal_class=(
            proposal_class
            if proposal_class is not None
            else ("initial" if action == "qualify" else "successor")
        ),
        node_actions=tuple(
            NodeActionV1(item.node_id, item.work.commands[0].argv_prefix[0])
            for item in selected
            if item.work is not None
        ),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--runtime-workspace", type=Path, required=True)
    parser.add_argument("--front-port", type=int, default=8080)
    parser.add_argument("--image", required=True)
    parser.add_argument("--docker-program", type=Path, required=True)
    parser.add_argument("--docker-program-identity", required=True)
    parser.add_argument("--docker-client-version", required=True)
    parser.add_argument("--docker-server-version", required=True)
    parser.add_argument("--compose-version", required=True)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--program-id", required=True)
    parser.add_argument("--subject-digest", required=True)
    parser.add_argument("--scope-digest", required=True)
    parser.add_argument("--qualify-occurrence-id", required=True)
    parser.add_argument("--teardown-occurrence-id", required=True)
    parser.add_argument("--qualify-observation-id", required=True)
    parser.add_argument("--teardown-observation-id", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_root = args.output_root.resolve()
    runtime_root = args.runtime_root.resolve()
    workspace = args.runtime_workspace.resolve()
    snap_common = runtime_root.parts[-4:] == (
        "snap",
        "docker",
        "common",
        "ag-synthetic-cache",
    )
    if not str(output_root).startswith("/tmp/"):
        raise SystemExit("synthetic evidence must be below /tmp")
    if not (str(runtime_root).startswith("/tmp/") or snap_common):
        raise SystemExit(
            "runtime root must be below /tmp or the explicit Snap Docker common campaign root"
        )
    if workspace.parent != runtime_root or workspace.name != PROJECT_NAME:
        raise SystemExit(f"runtime workspace basename must be {PROJECT_NAME}")
    output_root.mkdir(parents=True, exist_ok=True)

    drafts = DraftStore(output_root / "plan-store.sqlite", now=now)
    proposals = ProposalStore(output_root / "proposal-store.sqlite", now=now)
    service = ProposalService(drafts, proposals, now=now)

    initial = drafts.create(initial_document(), draft_id=DRAFT_ID)
    first_check = drafts.check(DRAFT_ID)
    finding = next(
        item
        for item in first_check.findings
        if item.rule_id == "plan.reference.unique"
        and item.target.node_id == "pn_continued"
    )
    provider = DeterministicFixtureProvider("finding_fix")
    request = service.request(
        draft_id=DRAFT_ID,
        base_revision_id=initial.revision_id,
        task="remove the duplicate dependency declaration without changing its target",
        scope=ProposalScopeV1(
            "exact_finding",
            ("update_node",),
            ("pn_continued",),
            ("depends_on",),
            finding_id=finding.finding_id,
        ),
        findings=(ProposalFindingContextV1.from_finding(finding),),
        provider=provider,
        generation_id="generation_synthetic_cache_dependency_repair",
    )
    proposal = service.generate(request, provider)
    proposal_preview = service.project(proposal.proposal_id).preview
    acceptance = service.accept(
        proposal.proposal_id, accepting_actor="synthetic-campaign-operator"
    )

    repaired = drafts.current(DRAFT_ID)
    human_operation = PlanOperationV1(
        UpdateDocumentV1(
            repaired.document.goal,
            repaired.document.workspace,
            repaired.document.constraints,
            repaired.document.acceptance_criteria
            + (
                "The exact runtime and compiler identities are pinned before execution",
            ),
            repaired.document.execution_request,
        )
    )
    human_preview = apply_plan_operation(repaired.document, human_operation)
    final = drafts.save_successor(
        DRAFT_ID,
        repaired.revision_id,
        human_preview.document,
        edit_origin=EditOrigin.HUMAN,
    )
    final_check = drafts.check(DRAFT_ID)
    if final_check.result != "passed":
        raise RuntimeError("repaired synthetic plan did not pass structural checking")
    lock = drafts.lock(DRAFT_ID)

    registry = CompilerRegistryV1()
    registry.register("local-compose", LocalComposeWorkflowCompilerV1())
    compiled: dict[str, Any] = {}
    for action in ("qualify", "teardown"):
        explicit = compiler_inputs(
            final.document,
            action=action,
            workspace=workspace,
            front_port=args.front_port,
            image=args.image,
            # Preserve the semantic launcher name (the snap app symlink); its
            # resolved executable bytes are pinned separately below.
            docker_program=args.docker_program,
            docker_program_identity=args.docker_program_identity,
            docker_client_version=args.docker_client_version,
            docker_server_version=args.docker_server_version,
            compose_version=args.compose_version,
            campaign_id=args.campaign_id,
            program_id=args.program_id,
            occurrence_id=(
                args.qualify_occurrence_id
                if action == "qualify"
                else args.teardown_occurrence_id
            ),
            observation_id=(
                args.qualify_observation_id
                if action == "qualify"
                else args.teardown_observation_id
            ),
            subject_digest=args.subject_digest,
            scope_digest=args.scope_digest,
        )
        result = registry.compile("local-compose", final.document, explicit)
        executor_plan = executor_plan_from_handoff(result.handoff_bytes)
        work = ag_executor_plan_identity(executor_plan)
        receipt = drafts.record_compilation(
            DRAFT_ID,
            lock.lock_id,
            result,
            compiler_inputs=explicit.canonical_bytes,
            exact_work_identity=work,
        )
        write_exact(
            output_root / f"compiler-input-{action}.json", explicit.canonical_bytes
        )
        write_exact(output_root / f"handoff-{action}.json", result.handoff_bytes)
        write_exact(output_root / f"executor-plan-{action}.json", executor_plan)
        write_exact(
            output_root / f"compilation-receipt-{action}.json", receipt.to_data()
        )
        compiled[action] = {
            "compilation_receipt": receipt.to_data(),
            "executor_plan_identity": work,
            "handoff_digest": result.handoff_digest,
            "occurrence_id": explicit.occurrence_id,
        }

    write_exact(output_root / "plan-initial.json", initial.document.to_data())
    write_exact(output_root / "plan-locked.json", final.document.to_data())
    write_exact(output_root / "check-initial.json", first_check.to_data())
    write_exact(output_root / "check-final.json", final_check.to_data())
    write_exact(output_root / "proposal-request.json", request.to_data())
    write_exact(output_root / "proposal.json", proposal.to_data())
    write_exact(output_root / "proposal-acceptance.json", acceptance.to_data())
    write_exact(output_root / "proposal-diff.json", proposal_preview.diff.to_data())
    write_exact(output_root / "human-diff.json", human_preview.diff.to_data())
    write_exact(output_root / "lock-receipt.json", lock.to_data())

    summary = {
        "agent_repair": {
            "acceptance_receipt_id": acceptance.receipt_id,
            "finding_id": finding.finding_id,
            "proposal_id": proposal.proposal_id,
            "resulting_revision_id": acceptance.resulting_revision_id,
        },
        "compilations": compiled,
        "draft_id": DRAFT_ID,
        "final_check": final_check.result,
        "final_revision_id": final.revision_id,
        "initial_check": first_check.result,
        "initial_finding_rule": finding.rule_id,
        "initial_revision_id": initial.revision_id,
        "lock_id": lock.lock_id,
        "locked_plan_digest": lock.plan_digest,
        "proposal_semantic_diff": proposal_preview.diff.to_data(),
        "schema": "maude.synthetic-cache-plan-qualification/v1",
        "workflow_schema": LOCAL_COMPOSE_WORK_SCHEMA,
    }
    write_exact(output_root / "plan-qualification.json", summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
