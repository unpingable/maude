# SPDX-License-Identifier: Apache-2.0
"""Closed, typed semantic edit operations for PlanDocument v1.

Every client—CLI, browser, or future model proposal—must cross this boundary.
The operation is applied to an exact immutable revision and produces another
ordinary PlanDocument; it is never an in-place patch or an authority action.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping, TypeAlias

from maude.plan.diff import PlanDiffV1, semantic_diff
from maude.plan.document import (
    DocumentConstraintsV1,
    DocumentExecutionRequestV1,
    PlanDocumentV1,
    PlanNodeV1,
)

PLAN_OPERATION_SCHEMA = "maude.plan-operation/v1"


class PlanOperationError(ValueError):
    """The requested semantic edit is malformed or cannot target this plan."""


def _object(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise PlanOperationError(f"{where} must be an object")
    return value


def _closed(raw: Mapping[str, Any], fields: set[str], where: str) -> None:
    unknown = set(raw) - fields
    if unknown:
        raise PlanOperationError(f"{where}: unknown field(s): {sorted(unknown)}")


def _string(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise PlanOperationError(f"{where} must be a non-empty string without NUL")
    return value


@dataclass(frozen=True)
class AddNodeV1:
    node: PlanNodeV1
    position: int
    operation_type: str = "add_node"

    def to_data(self) -> dict[str, Any]:
        return {
            "node": self.node.to_data(),
            "position": self.position,
            "type": self.operation_type,
        }


@dataclass(frozen=True)
class UpdateNodeV1:
    node: PlanNodeV1
    operation_type: str = "update_node"

    def to_data(self) -> dict[str, Any]:
        return {"node": self.node.to_data(), "type": self.operation_type}


@dataclass(frozen=True)
class RemoveNodeV1:
    node_id: str
    operation_type: str = "remove_node"

    def to_data(self) -> dict[str, Any]:
        return {"node_id": self.node_id, "type": self.operation_type}


@dataclass(frozen=True)
class ReorderNodeV1:
    node_id: str
    position: int
    operation_type: str = "reorder_node"

    def to_data(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "position": self.position,
            "type": self.operation_type,
        }


@dataclass(frozen=True)
class UpdateDocumentV1:
    goal: str
    workspace: str
    constraints: DocumentConstraintsV1
    acceptance_criteria: tuple[str, ...]
    execution_request: DocumentExecutionRequestV1 | None
    operation_type: str = "update_document"

    def to_data(self) -> dict[str, Any]:
        return {
            "acceptance_criteria": list(self.acceptance_criteria),
            "constraints": self.constraints.to_data(),
            "execution_request": (
                None
                if self.execution_request is None
                else self.execution_request.to_data()
            ),
            "goal": self.goal,
            "type": self.operation_type,
            "workspace": self.workspace,
        }


PlanEditV1: TypeAlias = (
    AddNodeV1 | UpdateNodeV1 | RemoveNodeV1 | ReorderNodeV1 | UpdateDocumentV1
)


@dataclass(frozen=True)
class PlanOperationV1:
    edit: PlanEditV1
    schema: str = PLAN_OPERATION_SCHEMA

    def to_data(self) -> dict[str, Any]:
        return {"operation": self.edit.to_data(), "schema": self.schema}

    @classmethod
    def from_data(cls, value: Any) -> PlanOperationV1:
        raw = _object(value, "operation envelope")
        _closed(raw, {"schema", "operation"}, "operation envelope")
        if raw.get("schema") != PLAN_OPERATION_SCHEMA:
            raise PlanOperationError("unsupported plan operation schema")
        body = _object(raw.get("operation"), "operation")
        kind = body.get("type")
        if kind == "add_node":
            _closed(body, {"type", "node", "position"}, "add_node")
            position = body.get("position")
            if not isinstance(position, int) or isinstance(position, bool):
                raise PlanOperationError("add_node.position must be an integer")
            edit: PlanEditV1 = AddNodeV1(
                PlanNodeV1.from_data(body.get("node"), "add_node.node"), position
            )
        elif kind == "update_node":
            _closed(body, {"type", "node"}, "update_node")
            edit = UpdateNodeV1(
                PlanNodeV1.from_data(body.get("node"), "update_node.node")
            )
        elif kind == "remove_node":
            _closed(body, {"type", "node_id"}, "remove_node")
            edit = RemoveNodeV1(_string(body.get("node_id"), "remove_node.node_id"))
        elif kind == "reorder_node":
            _closed(body, {"type", "node_id", "position"}, "reorder_node")
            position = body.get("position")
            if not isinstance(position, int) or isinstance(position, bool):
                raise PlanOperationError("reorder_node.position must be an integer")
            edit = ReorderNodeV1(
                _string(body.get("node_id"), "reorder_node.node_id"), position
            )
        elif kind == "update_document":
            _closed(
                body,
                {
                    "type",
                    "goal",
                    "workspace",
                    "constraints",
                    "acceptance_criteria",
                    "execution_request",
                },
                "update_document",
            )
            acceptance = body.get("acceptance_criteria")
            if not isinstance(acceptance, list) or not all(
                isinstance(item, str) and "\x00" not in item for item in acceptance
            ):
                raise PlanOperationError(
                    "acceptance_criteria must be an array of strings"
                )
            if not isinstance(body.get("goal"), str) or not isinstance(
                body.get("workspace"), str
            ):
                raise PlanOperationError("goal and workspace must be strings")
            execution = body.get("execution_request")
            edit = UpdateDocumentV1(
                goal=body["goal"],
                workspace=body["workspace"],
                constraints=DocumentConstraintsV1.from_data(
                    body.get("constraints"), "update_document.constraints"
                ),
                acceptance_criteria=tuple(acceptance),
                execution_request=(
                    None
                    if execution is None
                    else DocumentExecutionRequestV1.from_data(
                        execution, "update_document.execution_request"
                    )
                ),
            )
        else:
            raise PlanOperationError(f"unsupported plan operation type {kind!r}")
        return cls(edit)


@dataclass(frozen=True)
class PlanOperationPreviewV1:
    operation: PlanOperationV1
    document: PlanDocumentV1
    diff: PlanDiffV1


def _known_ids(document: PlanDocumentV1) -> set[str]:
    return {node.node_id for node in document.nodes}


def _validate_dependencies(node: PlanNodeV1, known: set[str]) -> None:
    missing = sorted(set(node.depends_on) - known)
    if missing:
        raise PlanOperationError(
            f"typed dependency edit references unknown PlanNode(s): {missing}"
        )


def apply_plan_operation(
    document: PlanDocumentV1, operation: PlanOperationV1
) -> PlanOperationPreviewV1:
    """Apply one closed operation to exact semantic input and return its diff."""
    edit = operation.edit
    known = _known_ids(document)
    if isinstance(edit, AddNodeV1):
        if edit.node.node_id in known:
            raise PlanOperationError(f"PlanNode {edit.node.node_id} already exists")
        if not 0 <= edit.position <= len(document.nodes):
            raise PlanOperationError("add_node.position is outside the ordered plan")
        _validate_dependencies(edit.node, known)
        nodes = list(document.nodes)
        nodes.insert(edit.position, edit.node)
        proposed = replace(document, nodes=tuple(nodes))
    elif isinstance(edit, UpdateNodeV1):
        if edit.node.node_id not in known:
            raise PlanOperationError(f"PlanNode {edit.node.node_id} does not exist")
        _validate_dependencies(edit.node, known)
        proposed = replace(
            document,
            nodes=tuple(
                edit.node if node.node_id == edit.node.node_id else node
                for node in document.nodes
            ),
        )
    elif isinstance(edit, RemoveNodeV1):
        if edit.node_id not in known:
            raise PlanOperationError(f"PlanNode {edit.node_id} does not exist")
        proposed = replace(
            document,
            nodes=tuple(
                node for node in document.nodes if node.node_id != edit.node_id
            ),
        )
    elif isinstance(edit, ReorderNodeV1):
        if edit.node_id not in known:
            raise PlanOperationError(f"PlanNode {edit.node_id} does not exist")
        if not 0 <= edit.position < len(document.nodes):
            raise PlanOperationError(
                "reorder_node.position is outside the ordered plan"
            )
        nodes = list(document.nodes)
        node = nodes.pop(
            next(i for i, item in enumerate(nodes) if item.node_id == edit.node_id)
        )
        nodes.insert(edit.position, node)
        proposed = replace(document, nodes=tuple(nodes))
    else:
        proposed = replace(
            document,
            goal=edit.goal,
            workspace=edit.workspace,
            constraints=edit.constraints,
            acceptance_criteria=edit.acceptance_criteria,
            execution_request=edit.execution_request,
        )
    diff = semantic_diff(document, proposed)
    if proposed.digest == document.digest:
        raise PlanOperationError("operation makes no semantic change")
    return PlanOperationPreviewV1(operation, proposed, diff)
