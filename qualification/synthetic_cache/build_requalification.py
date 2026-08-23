#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Create and compile the exact C2 successor of the synthetic cache design.

C2 changes the semantic and runtime workspace from the C1 Compose project to
an independently named project.  The change crosses ordinary typed Plan Core
operations and revision CAS; generated Compose artifacts are produced only
after the successor is checked and locked.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from build_plan import DRAFT_ID, compiler_inputs, write_exact
from maude.plan.compiler import CompilerRegistryV1
from maude.plan.diff import semantic_diff
from maude.plan.document import DocumentConstraintsV1, PlanDocumentV1
from maude.plan.local_compose import (
    LocalComposeWorkflowCompilerV1,
    ag_executor_plan_identity,
    executor_plan_from_handoff,
)
from maude.plan.operations import (
    PlanOperationV1,
    UpdateDocumentV1,
    UpdateNodeV1,
    apply_plan_operation,
)
from maude.plan.store import DraftStore, EditOrigin

C2_PROJECT_NAME = "maude-cache-birthday-c2"
C2_SEMANTIC_WORKSPACE = "synthetic-cache-workspace-c2"
C2_FIXED_TIME = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)


def exact_object(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"exact input must be an object: {path}")
    return value


def c2_operations(document: PlanDocumentV1) -> tuple[PlanOperationV1, ...]:
    """Return the closed successor edit set without mutating the document."""
    constraints = DocumentConstraintsV1(
        declared_write_paths=(C2_SEMANTIC_WORKSPACE,),
        forbidden_paths=document.constraints.forbidden_paths,
        halt_if=document.constraints.halt_if,
        world_requirements=document.constraints.world_requirements,
    )
    operations: list[PlanOperationV1] = [
        PlanOperationV1(
            UpdateDocumentV1(
                goal=document.goal,
                workspace=C2_SEMANTIC_WORKSPACE,
                constraints=constraints,
                acceptance_criteria=document.acceptance_criteria
                + ("The C2 runtime is confined to its distinct exact Compose project",),
                execution_request=document.execution_request,
            )
        )
    ]
    for node in document.nodes:
        if node.work is None:
            continue
        operations.append(
            PlanOperationV1(
                UpdateNodeV1(
                    dataclasses.replace(
                        node,
                        work=dataclasses.replace(
                            node.work, write_paths=(C2_SEMANTIC_WORKSPACE,)
                        ),
                    )
                )
            )
        )
    return tuple(operations)


def save_c2_successor(
    store: DraftStore, c1: PlanDocumentV1
) -> tuple[PlanDocumentV1, tuple[dict[str, Any], ...]]:
    """Apply C2 through the same one-operation revision boundary as the UI."""
    current = store.current(DRAFT_ID)
    if current.plan_digest != c1.digest:
        raise ValueError("current working revision is not the exact locked C1 artifact")
    previews: list[dict[str, Any]] = []
    for operation in c2_operations(current.document):
        preview = apply_plan_operation(current.document, operation)
        current = store.save_successor(
            DRAFT_ID,
            current.revision_id,
            preview.document,
            edit_origin=EditOrigin.HUMAN,
        )
        previews.append(
            {
                "operation": operation.to_data(),
                "resulting_digest": current.plan_digest,
                "resulting_revision_id": current.revision_id,
                "semantic_diff": preview.diff.to_data(),
            }
        )
    return current.document, tuple(previews)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan-root", type=Path, required=True)
    parser.add_argument("--runtime-workspace", type=Path, required=True)
    parser.add_argument("--base-compiler-input", type=Path, required=True)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--program-id", required=True)
    parser.add_argument("--subject-digest", required=True)
    parser.add_argument("--scope-digest", required=True)
    parser.add_argument("--qualify-occurrence-id", required=True)
    parser.add_argument("--qualify-observation-id", required=True)
    parser.add_argument("--teardown-occurrence-id", required=True)
    parser.add_argument("--teardown-observation-id", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.plan_root.resolve()
    workspace = args.runtime_workspace.resolve()
    if not str(root).startswith("/tmp/"):
        raise SystemExit("synthetic evidence root must be below /tmp")
    allowed_snap_parent = Path("/home/jbeck/snap/docker/common/ag-synthetic-cache")
    if workspace.name != C2_PROJECT_NAME or not (
        str(workspace).startswith("/tmp/") or workspace.parent == allowed_snap_parent
    ):
        raise SystemExit("C2 runtime workspace is outside the closed campaign roots")

    base = exact_object(args.base_compiler_input.resolve())
    if base.get("schema") != "maude.local-compose-workflow-input/v1":
        raise ValueError("unsupported base compiler input")

    store = DraftStore(root / "plan-store.sqlite", now=lambda: C2_FIXED_TIME)
    summary = exact_object(root / "plan-qualification.json")
    c1_revision = store.revision(summary["final_revision_id"])
    if c1_revision.plan_digest != summary["locked_plan_digest"]:
        raise ValueError("C1 lock/summary identity disagreement")
    if store.current(DRAFT_ID).revision_id != c1_revision.revision_id:
        raise ValueError("C1 store already contains an unreviewed successor")

    c2, operation_receipts = save_c2_successor(store, c1_revision.document)
    c2_diff = semantic_diff(c1_revision.document, c2)
    check = store.check(DRAFT_ID)
    if check.result != "passed":
        raise RuntimeError("C2 did not pass structural checking")
    lock = store.lock(DRAFT_ID)

    registry = CompilerRegistryV1()
    registry.register("local-compose", LocalComposeWorkflowCompilerV1())
    compiled: dict[str, Any] = {}
    for action in ("qualify", "teardown"):
        explicit = compiler_inputs(
            c2,
            action=action,
            workspace=workspace,
            project_name=C2_PROJECT_NAME,
            proposal_class="successor",
            front_port=base["front_port"],
            image=base["image"],
            docker_program=Path(base["docker_program"]),
            docker_program_identity=base["docker_program_identity"],
            docker_client_version=base["docker_client_version"],
            docker_server_version=base["docker_server_version"],
            compose_version=base["compose_version"],
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
        result = registry.compile("local-compose", c2, explicit)
        executor_plan = executor_plan_from_handoff(result.handoff_bytes)
        work = ag_executor_plan_identity(executor_plan)
        receipt = store.record_compilation(
            DRAFT_ID,
            lock.lock_id,
            result,
            compiler_inputs=explicit.canonical_bytes,
            exact_work_identity=work,
        )
        write_exact(root / f"compiler-input-c2-{action}.json", explicit.canonical_bytes)
        write_exact(root / f"handoff-c2-{action}.json", result.handoff_bytes)
        write_exact(root / f"executor-plan-c2-{action}.json", executor_plan)
        write_exact(root / f"compilation-receipt-c2-{action}.json", receipt.to_data())
        compiled[action] = {
            "compilation_id": receipt.compilation_id,
            "exact_work_identity": work,
            "handoff_digest": result.handoff_digest,
            "occurrence_id": explicit.occurrence_id,
        }

    write_exact(root / "plan-c2-locked.json", c2.to_data())
    write_exact(root / "plan-c1-c2-diff.json", c2_diff.to_data())
    write_exact(root / "plan-c2-check.json", check.to_data())
    write_exact(root / "plan-c2-lock.json", lock.to_data())
    write_exact(root / "plan-c2-operations.json", list(operation_receipts))
    result = {
        "c1_plan_digest": c1_revision.plan_digest,
        "c1_revision_id": c1_revision.revision_id,
        "c2_check_receipt_id": check.receipt_id,
        "c2_compilations": compiled,
        "c2_lock_id": lock.lock_id,
        "c2_plan_digest": c2.digest,
        "c2_revision_id": store.current(DRAFT_ID).revision_id,
        "c2_runtime_project": C2_PROJECT_NAME,
        "c2_runtime_workspace": str(workspace),
        "node_ids_preserved": [node.node_id for node in c2.nodes],
        "operation_count": len(operation_receipts),
        "schema": "maude.synthetic-cache-requalification-plan/v1",
    }
    write_exact(root / "plan-requalification.json", result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
