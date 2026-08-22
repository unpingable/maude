# SPDX-License-Identifier: Apache-2.0
"""Deterministic provider fixtures for the Plan Edit Proposal protocol.

This module has no store and no save primitive.  Its only output is bounded
provider bytes in the same shape expected from a future independent model.
"""

from __future__ import annotations

from dataclasses import replace

from maude.plan.document import canonical_json_bytes
from maude.plan.operations import PlanOperationV1, UpdateDocumentV1, UpdateNodeV1
from maude.plan.proposals import (
    MAX_PROVIDER_OUTPUT_BYTES,
    PROVIDER_OUTPUT_SCHEMA,
    PlanEditProposalRequestV1,
    ProviderDescriptorV1,
)


class DeterministicFixtureProvider:
    """Closed fixture provider used for protocol and human-product evaluation."""

    def __init__(self, scenario: str = "bounded_edit") -> None:
        self.scenario = scenario
        self.descriptor = ProviderDescriptorV1(
            "maude.deterministic-fixture-provider", scenario, "1"
        )

    def _output(
        self,
        request: PlanEditProposalRequestV1,
        operations: tuple[PlanOperationV1, ...],
        rationale: str,
        **binding_overrides: str,
    ) -> bytes:
        return canonical_json_bytes(
            {
                "base_plan_digest": binding_overrides.get(
                    "base_plan_digest", request.base_plan_digest
                ),
                "base_revision_id": binding_overrides.get(
                    "base_revision_id", request.base_revision_id
                ),
                "draft_id": binding_overrides.get("draft_id", request.draft_id),
                "operations": [item.to_data() for item in operations],
                "rationale": rationale,
                "request_id": binding_overrides.get("request_id", request.request_id),
                "schema": PROVIDER_OUTPUT_SCHEMA,
            }
        )

    def generate(self, request: PlanEditProposalRequestV1) -> bytes:
        if self.scenario == "malformed":
            return b'{"schema":'
        if self.scenario == "oversized":
            return b"x" * (MAX_PROVIDER_OUTPUT_BYTES + 1)

        document = request.document
        targets = request.scope.target_node_ids
        selected = next(
            (node for node in document.nodes if node.node_id in targets), None
        )
        if (
            selected is None
            and "update_node" in request.scope.allowed_operation_types
            and document.nodes
        ):
            selected = document.nodes[0]
        if selected is None:
            operation = PlanOperationV1(
                UpdateDocumentV1(
                    document.goal + " — proposed",
                    document.workspace,
                    document.constraints,
                    document.acceptance_criteria,
                    document.execution_request,
                )
            )
        else:
            operation = PlanOperationV1(
                UpdateNodeV1(
                    replace(
                        selected,
                        description=f"{selected.description} — {request.task.strip()}",
                    )
                )
            )

        if self.scenario == "bounded_edit":
            return self._output(
                request,
                (operation,),
                "Proposed one ordinary typed edit inside the requested scope.",
            )
        if self.scenario == "finding_fix":
            if selected is None:
                return self._output(request, (operation,), "Document finding proposal.")
            dependencies = tuple(
                item
                for index, item in enumerate(selected.depends_on)
                if item in {node.node_id for node in document.nodes}
                and item not in selected.depends_on[:index]
            )
            fixed = replace(selected, depends_on=dependencies)
            if fixed == selected:
                fixed = replace(
                    selected,
                    description=selected.description + " — finding reviewed",
                )
            return self._output(
                request,
                (PlanOperationV1(UpdateNodeV1(fixed)),),
                "Removed nonexistent or duplicate dependency references when present.",
            )
        if self.scenario == "document_acceptance":
            changed = UpdateDocumentV1(
                document.goal,
                document.workspace,
                document.constraints,
                document.acceptance_criteria
                + ("The exact proposed design change is reviewable",),
                document.execution_request,
            )
            return self._output(
                request,
                (PlanOperationV1(changed),),
                "Added one document acceptance criterion.",
            )
        if self.scenario == "multi_operation":
            first = document.nodes[0]
            node_edit = PlanOperationV1(
                UpdateNodeV1(
                    replace(first, description=first.description + " — clarified")
                )
            )
            doc_edit = PlanOperationV1(
                UpdateDocumentV1(
                    document.goal + " — reviewed",
                    document.workspace,
                    document.constraints,
                    document.acceptance_criteria,
                    document.execution_request,
                )
            )
            return self._output(
                request,
                (node_edit, doc_edit),
                "Two ordered operations form one atomic candidate revision.",
            )
        if self.scenario == "out_of_scope":
            other = next(
                (node for node in document.nodes if node.node_id not in targets),
                selected,
            )
            assert other is not None
            escaped = PlanOperationV1(
                UpdateNodeV1(
                    replace(other, description=other.description + " — escaped")
                )
            )
            return self._output(request, (escaped,), "Claims to honor scope.")
        if self.scenario == "invalid_node":
            assert selected is not None
            invalid = replace(selected, node_id="pn_provider_invented_target")
            return self._output(
                request,
                (PlanOperationV1(UpdateNodeV1(invalid)),),
                "Targets a node that does not exist.",
            )
        if self.scenario == "cycle":
            assert selected is not None
            cycled = replace(selected, depends_on=(selected.node_id,))
            return self._output(
                request,
                (PlanOperationV1(UpdateNodeV1(cycled)),),
                "Creates a syntactically valid draft that the checker should reject.",
            )
        if self.scenario == "rationale_disagreement":
            return self._output(
                request,
                (operation,),
                "Only an acceptance criterion changes (the operation is authoritative).",
            )
        if self.scenario == "wrong_binding":
            return self._output(
                request,
                (operation,),
                "Substituted request binding.",
                draft_id="draft_substituted",
            )
        raise ValueError(f"unknown deterministic provider scenario {self.scenario!r}")


FIXTURE_SCENARIOS = (
    "bounded_edit",
    "finding_fix",
    "document_acceptance",
    "multi_operation",
    "cycle",
    "rationale_disagreement",
    "out_of_scope",
    "invalid_node",
    "malformed",
    "oversized",
    "wrong_binding",
)
