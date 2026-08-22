# SPDX-License-Identifier: Apache-2.0
"""Stable-identity semantic diff for PlanDocument revisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from maude.plan.document import PlanDocumentV1

PLAN_DIFF_SCHEMA = "maude.plan-diff/v1"


@dataclass(frozen=True)
class NodeChangeV1:
    node_id: str
    fields: tuple[str, ...]

    def to_data(self) -> dict[str, Any]:
        return {"fields": list(self.fields), "node_id": self.node_id}


@dataclass(frozen=True)
class PlanDiffV1:
    from_digest: str
    to_digest: str
    added: tuple[str, ...]
    removed: tuple[str, ...]
    changed: tuple[NodeChangeV1, ...]
    reordered: bool
    before_order: tuple[str, ...]
    after_order: tuple[str, ...]
    document_fields: tuple[str, ...]
    schema: str = PLAN_DIFF_SCHEMA

    def to_data(self) -> dict[str, Any]:
        return {
            "after_order": list(self.after_order),
            "before_order": list(self.before_order),
            "document_fields": list(self.document_fields),
            "from_digest": self.from_digest,
            "node_added": list(self.added),
            "node_changed": [change.to_data() for change in self.changed],
            "node_removed": list(self.removed),
            "node_reordered": self.reordered,
            "schema": self.schema,
            "to_digest": self.to_digest,
        }

    def render(self) -> str:
        lines = [f"plan {self.from_digest} -> {self.to_digest}"]
        lines.extend(f"+ node {node_id}" for node_id in self.added)
        lines.extend(f"- node {node_id}" for node_id in self.removed)
        lines.extend(
            f"~ node {change.node_id}: {', '.join(change.fields)}"
            for change in self.changed
        )
        if self.reordered:
            lines.append(
                "↕ node order: "
                + " -> ".join(self.before_order)
                + " => "
                + " -> ".join(self.after_order)
            )
        lines.extend(f"~ document: {field}" for field in self.document_fields)
        if len(lines) == 1:
            lines.append("(no semantic changes)")
        return "\n".join(lines)


def semantic_diff(before: PlanDocumentV1, after: PlanDocumentV1) -> PlanDiffV1:
    old = {node.node_id: node for node in before.nodes}
    new = {node.node_id: node for node in after.nodes}
    added = tuple(node.node_id for node in after.nodes if node.node_id not in old)
    removed = tuple(node.node_id for node in before.nodes if node.node_id not in new)
    changed: list[NodeChangeV1] = []
    for node_id in sorted(old.keys() & new.keys()):
        fields = tuple(
            field
            for field in (
                "description",
                "depends_on",
                "work",
                "acceptance_criteria",
                "stop_conditions",
            )
            if getattr(old[node_id], field) != getattr(new[node_id], field)
        )
        if fields:
            changed.append(NodeChangeV1(node_id, fields))
    before_common = tuple(node.node_id for node in before.nodes if node.node_id in new)
    after_common = tuple(node.node_id for node in after.nodes if node.node_id in old)
    document_fields = tuple(
        field
        for field in (
            "goal",
            "workspace",
            "submitter",
            "constraints",
            "acceptance_criteria",
            "execution_request",
            "source_envelope_ref",
        )
        if getattr(before, field) != getattr(after, field)
    )
    return PlanDiffV1(
        from_digest=before.digest,
        to_digest=after.digest,
        added=added,
        removed=removed,
        changed=tuple(changed),
        reordered=before_common != after_common,
        before_order=before_common,
        after_order=after_common,
        document_fields=document_fields,
    )
