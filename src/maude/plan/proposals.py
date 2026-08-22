# SPDX-License-Identifier: Apache-2.0
"""Immutable, authority-neutral proposals for ordinary Plan Core edits.

Providers produce hostile bytes.  This module closes those bytes over the
existing ``maude.plan-operation/v1`` vocabulary, validates an explicit editing
scope, and previews an operation sequence entirely in memory.  It deliberately
has no persistence or governed-runtime dependency.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from maude.plan.checks import CheckFindingV1
from maude.plan.diff import PlanDiffV1, semantic_diff
from maude.plan.document import PlanDocumentV1, canonical_json_bytes, content_digest
from maude.plan.operations import (
    AddNodeV1,
    PlanOperationError,
    PlanOperationV1,
    RemoveNodeV1,
    ReorderNodeV1,
    UpdateNodeV1,
    apply_plan_operation,
)

PROPOSAL_REQUEST_SCHEMA = "maude.plan-edit-proposal-request/v1"
PROVIDER_OUTPUT_SCHEMA = "maude.plan-edit-provider-output/v1"
PROPOSAL_SCHEMA = "maude.plan-edit-proposal/v1"
MAX_PROPOSAL_OPERATIONS = 32
MAX_PROVIDER_OUTPUT_BYTES = 128 * 1024
OPERATION_TYPES = frozenset(
    {"add_node", "update_node", "remove_node", "reorder_node", "update_document"}
)
NODE_FIELDS = frozenset(
    {"description", "depends_on", "work", "acceptance_criteria", "stop_conditions"}
)
DOCUMENT_FIELDS = frozenset(
    {"goal", "workspace", "constraints", "acceptance_criteria", "execution_request"}
)
SCOPE_KINDS = frozenset({"exact_document", "exact_nodes", "exact_finding"})


class ProposalError(ValueError):
    """Provider output or proposal content violates the closed protocol."""


@dataclass(frozen=True)
class ProviderDescriptorV1:
    provider_id: str
    model_id: str
    model_version: str | None = None


class PlanEditProvider(Protocol):
    """Provider-neutral byte boundary. Providers have no Plan Core store."""

    descriptor: ProviderDescriptorV1

    def generate(self, request: PlanEditProposalRequestV1) -> bytes: ...


def _object(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ProposalError(f"{where} must be an object")
    return value


def _closed(raw: Mapping[str, Any], fields: set[str], where: str) -> None:
    unknown = set(raw) - fields
    if unknown:
        raise ProposalError(f"{where}: unknown field(s): {sorted(unknown)}")


def _text(value: Any, where: str, *, empty: bool = False) -> str:
    if (
        not isinstance(value, str)
        or (not empty and not value.strip())
        or "\x00" in value
    ):
        raise ProposalError(
            f"{where} must be {'a string' if empty else 'a non-empty string'} without NUL"
        )
    return value


def _strings(value: Any, where: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ProposalError(f"{where} must be an array")
    result = tuple(_text(item, f"{where}[{index}]") for index, item in enumerate(value))
    if len(result) != len(set(result)):
        raise ProposalError(f"{where} must not contain duplicates")
    return result


def _identity(unsigned: Mapping[str, Any]) -> str:
    return content_digest(canonical_json_bytes(unsigned))


@dataclass(frozen=True)
class ProposalScopeV1:
    kind: str
    allowed_operation_types: tuple[str, ...]
    target_node_ids: tuple[str, ...] = ()
    allowed_node_fields: tuple[str, ...] = ()
    allowed_document_fields: tuple[str, ...] = ()
    finding_id: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in SCOPE_KINDS:
            raise ProposalError(f"unsupported proposal scope {self.kind!r}")
        if (
            not self.allowed_operation_types
            or not set(self.allowed_operation_types) <= OPERATION_TYPES
        ):
            raise ProposalError(
                "proposal scope has unsupported or empty operation types"
            )
        if not set(self.allowed_node_fields) <= NODE_FIELDS:
            raise ProposalError("proposal scope has unsupported node fields")
        if not set(self.allowed_document_fields) <= DOCUMENT_FIELDS:
            raise ProposalError("proposal scope has unsupported document fields")
        for label, values in (
            ("operation types", self.allowed_operation_types),
            ("target node IDs", self.target_node_ids),
            ("node fields", self.allowed_node_fields),
            ("document fields", self.allowed_document_fields),
        ):
            if len(values) != len(set(values)):
                raise ProposalError(f"proposal scope {label} must be unique")
        if (
            self.kind in {"exact_nodes", "exact_finding"}
            and not self.target_node_ids
            and self.kind == "exact_nodes"
        ):
            raise ProposalError("exact_nodes scope requires at least one PlanNode ID")
        if self.kind == "exact_finding" and not self.finding_id:
            raise ProposalError("exact_finding scope requires a finding identity")
        if self.kind != "exact_finding" and self.finding_id is not None:
            raise ProposalError(
                "finding identity is only valid for exact_finding scope"
            )
        node_operations = {"add_node", "update_node", "remove_node", "reorder_node"}
        if self.kind == "exact_document" and self.target_node_ids:
            raise ProposalError(
                "exact_document scope cannot carry selected node targets"
            )
        if self.kind == "exact_nodes" and (
            "update_document" in self.allowed_operation_types
            or self.allowed_document_fields
        ):
            raise ProposalError("exact_nodes scope cannot authorize document edits")
        if self.kind == "exact_finding":
            if self.target_node_ids and (
                not set(self.allowed_operation_types) <= node_operations
                or self.allowed_document_fields
            ):
                raise ProposalError(
                    "node-targeted finding scope cannot authorize document edits"
                )
            if not self.target_node_ids and (
                self.allowed_operation_types != ("update_document",)
                or self.allowed_node_fields
            ):
                raise ProposalError(
                    "document finding scope may only authorize update_document"
                )

    def to_data(self) -> dict[str, Any]:
        return {
            "allowed_document_fields": list(self.allowed_document_fields),
            "allowed_node_fields": list(self.allowed_node_fields),
            "allowed_operation_types": list(self.allowed_operation_types),
            "finding_id": self.finding_id,
            "kind": self.kind,
            "target_node_ids": list(self.target_node_ids),
        }

    @classmethod
    def from_data(cls, value: Any) -> ProposalScopeV1:
        raw = _object(value, "proposal scope")
        _closed(
            raw,
            {
                "kind",
                "allowed_operation_types",
                "target_node_ids",
                "allowed_node_fields",
                "allowed_document_fields",
                "finding_id",
            },
            "proposal scope",
        )
        finding = raw.get("finding_id")
        return cls(
            kind=_text(raw.get("kind"), "proposal scope.kind"),
            allowed_operation_types=_strings(
                raw.get("allowed_operation_types"),
                "proposal scope.allowed_operation_types",
            ),
            target_node_ids=_strings(
                raw.get("target_node_ids", []), "proposal scope.target_node_ids"
            ),
            allowed_node_fields=_strings(
                raw.get("allowed_node_fields", []), "proposal scope.allowed_node_fields"
            ),
            allowed_document_fields=_strings(
                raw.get("allowed_document_fields", []),
                "proposal scope.allowed_document_fields",
            ),
            finding_id=None
            if finding is None
            else _text(finding, "proposal scope.finding_id"),
        )


@dataclass(frozen=True)
class ProposalFindingContextV1:
    finding_id: str
    rule_id: str
    target_kind: str
    target_node_id: str | None
    message: str

    @classmethod
    def from_finding(cls, finding: CheckFindingV1) -> ProposalFindingContextV1:
        return cls(
            finding.finding_id,
            finding.rule_id,
            finding.target.kind,
            finding.target.node_id,
            finding.message,
        )

    def to_data(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "message": self.message,
            "rule_id": self.rule_id,
            "target": {"kind": self.target_kind, "node_id": self.target_node_id},
        }

    @classmethod
    def from_data(cls, value: Any) -> ProposalFindingContextV1:
        raw = _object(value, "finding context")
        _closed(raw, {"finding_id", "rule_id", "target", "message"}, "finding context")
        target = _object(raw.get("target"), "finding context.target")
        _closed(target, {"kind", "node_id"}, "finding context.target")
        node = target.get("node_id")
        return cls(
            _text(raw.get("finding_id"), "finding context.finding_id"),
            _text(raw.get("rule_id"), "finding context.rule_id"),
            _text(target.get("kind"), "finding context.target.kind"),
            None if node is None else _text(node, "finding context.target.node_id"),
            _text(raw.get("message"), "finding context.message"),
        )


@dataclass(frozen=True)
class PlanEditProposalRequestV1:
    request_id: str
    generation_id: str
    draft_id: str
    base_revision_id: str
    base_plan_digest: str
    task: str
    scope: ProposalScopeV1
    document: PlanDocumentV1
    findings: tuple[ProposalFindingContextV1, ...]
    requested_provider_id: str
    requested_model_id: str
    created_at: str
    schema: str = PROPOSAL_REQUEST_SCHEMA

    def unsigned_data(self) -> dict[str, Any]:
        return {
            "base_plan_digest": self.base_plan_digest,
            "base_revision_id": self.base_revision_id,
            "created_at": self.created_at,
            "document": self.document.to_data(),
            "draft_id": self.draft_id,
            "findings": [item.to_data() for item in self.findings],
            "generation_id": self.generation_id,
            "requested_model_id": self.requested_model_id,
            "requested_provider_id": self.requested_provider_id,
            "schema": self.schema,
            "scope": self.scope.to_data(),
            "task": self.task,
        }

    def to_data(self) -> dict[str, Any]:
        return {**self.unsigned_data(), "request_id": self.request_id}

    @classmethod
    def create(
        cls,
        *,
        draft_id: str,
        generation_id: str,
        base_revision_id: str,
        document: PlanDocumentV1,
        task: str,
        scope: ProposalScopeV1,
        findings: tuple[ProposalFindingContextV1, ...],
        requested_provider_id: str,
        requested_model_id: str,
        created_at: str,
    ) -> PlanEditProposalRequestV1:
        candidate = cls(
            "",
            _text(generation_id, "proposal generation identity"),
            draft_id,
            base_revision_id,
            document.digest,
            _text(task, "proposal task"),
            scope,
            document,
            findings,
            _text(requested_provider_id, "provider identity"),
            _text(requested_model_id, "model identity"),
            _text(created_at, "request creation time"),
        )
        return cls(
            _identity(candidate.unsigned_data()),
            candidate.generation_id,
            candidate.draft_id,
            candidate.base_revision_id,
            candidate.base_plan_digest,
            candidate.task,
            candidate.scope,
            candidate.document,
            candidate.findings,
            candidate.requested_provider_id,
            candidate.requested_model_id,
            candidate.created_at,
        )

    @classmethod
    def from_data(cls, value: Any) -> PlanEditProposalRequestV1:
        raw = _object(value, "proposal request")
        _closed(
            raw,
            {
                "request_id",
                "base_plan_digest",
                "base_revision_id",
                "created_at",
                "document",
                "draft_id",
                "findings",
                "generation_id",
                "requested_model_id",
                "requested_provider_id",
                "schema",
                "scope",
                "task",
            },
            "proposal request",
        )
        if raw.get("schema") != PROPOSAL_REQUEST_SCHEMA:
            raise ProposalError("unsupported proposal request schema")
        document = PlanDocumentV1.from_data(raw.get("document"))
        findings = raw.get("findings")
        if not isinstance(findings, list):
            raise ProposalError("proposal request findings must be an array")
        result = cls(
            request_id=_text(raw.get("request_id"), "request_id"),
            generation_id=_text(raw.get("generation_id"), "generation_id"),
            draft_id=_text(raw.get("draft_id"), "draft_id"),
            base_revision_id=_text(raw.get("base_revision_id"), "base_revision_id"),
            base_plan_digest=_text(raw.get("base_plan_digest"), "base_plan_digest"),
            task=_text(raw.get("task"), "task"),
            scope=ProposalScopeV1.from_data(raw.get("scope")),
            document=document,
            findings=tuple(
                ProposalFindingContextV1.from_data(item) for item in findings
            ),
            requested_provider_id=_text(
                raw.get("requested_provider_id"), "requested_provider_id"
            ),
            requested_model_id=_text(
                raw.get("requested_model_id"), "requested_model_id"
            ),
            created_at=_text(raw.get("created_at"), "created_at"),
        )
        if (
            result.document.digest != result.base_plan_digest
            or _identity(result.unsigned_data()) != result.request_id
        ):
            raise ProposalError(
                "proposal request identity or base digest is contradictory"
            )
        return result


@dataclass(frozen=True)
class ProviderOutputV1:
    request_id: str
    draft_id: str
    base_revision_id: str
    base_plan_digest: str
    operations: tuple[PlanOperationV1, ...]
    rationale: str | None = None
    schema: str = PROVIDER_OUTPUT_SCHEMA

    def to_data(self) -> dict[str, Any]:
        return {
            "base_plan_digest": self.base_plan_digest,
            "base_revision_id": self.base_revision_id,
            "draft_id": self.draft_id,
            "operations": [item.to_data() for item in self.operations],
            "rationale": self.rationale,
            "request_id": self.request_id,
            "schema": self.schema,
        }

    @classmethod
    def parse(cls, value: bytes) -> ProviderOutputV1:
        if len(value) > MAX_PROVIDER_OUTPUT_BYTES:
            raise ProposalError("provider output exceeds bounded response limit")
        try:
            raw = _object(json.loads(value.decode("utf-8")), "provider output")
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProposalError(
                f"provider output is not exact UTF-8 JSON: {exc}"
            ) from exc
        _closed(
            raw,
            {
                "schema",
                "request_id",
                "draft_id",
                "base_revision_id",
                "base_plan_digest",
                "operations",
                "rationale",
            },
            "provider output",
        )
        if raw.get("schema") != PROVIDER_OUTPUT_SCHEMA:
            raise ProposalError("unsupported provider output schema")
        values = raw.get("operations")
        if (
            not isinstance(values, list)
            or not 1 <= len(values) <= MAX_PROPOSAL_OPERATIONS
        ):
            raise ProposalError(
                f"provider output must contain 1..{MAX_PROPOSAL_OPERATIONS} operations"
            )
        rationale = raw.get("rationale")
        return cls(
            request_id=_text(raw.get("request_id"), "provider output.request_id"),
            draft_id=_text(raw.get("draft_id"), "provider output.draft_id"),
            base_revision_id=_text(
                raw.get("base_revision_id"), "provider output.base_revision_id"
            ),
            base_plan_digest=_text(
                raw.get("base_plan_digest"), "provider output.base_plan_digest"
            ),
            operations=tuple(PlanOperationV1.from_data(item) for item in values),
            rationale=None
            if rationale is None
            else _text(rationale, "provider output.rationale", empty=True),
        )


@dataclass(frozen=True)
class PlanEditProposalV1:
    proposal_id: str
    request_id: str
    draft_id: str
    base_revision_id: str
    base_plan_digest: str
    provider_id: str
    model_id: str
    model_version: str | None
    scope: ProposalScopeV1
    operations: tuple[PlanOperationV1, ...]
    rationale: str | None
    created_at: str
    schema: str = PROPOSAL_SCHEMA

    @property
    def operation_set_id(self) -> str:
        return _identity(
            {
                "operations": [item.to_data() for item in self.operations],
                "schema": "maude.plan-operation-set/v1",
            }
        )

    def unsigned_data(self) -> dict[str, Any]:
        return {
            "base_plan_digest": self.base_plan_digest,
            "base_revision_id": self.base_revision_id,
            "created_at": self.created_at,
            "draft_id": self.draft_id,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "operations": [item.to_data() for item in self.operations],
            "provider_id": self.provider_id,
            "rationale": self.rationale,
            "request_id": self.request_id,
            "schema": self.schema,
            "scope": self.scope.to_data(),
        }

    def to_data(self) -> dict[str, Any]:
        return {
            **self.unsigned_data(),
            "operation_set_id": self.operation_set_id,
            "proposal_id": self.proposal_id,
        }

    @classmethod
    def from_data(cls, value: Any) -> PlanEditProposalV1:
        raw = _object(value, "proposal")
        _closed(
            raw,
            {
                "proposal_id",
                "operation_set_id",
                "request_id",
                "draft_id",
                "base_revision_id",
                "base_plan_digest",
                "provider_id",
                "model_id",
                "model_version",
                "scope",
                "operations",
                "rationale",
                "created_at",
                "schema",
            },
            "proposal",
        )
        if raw.get("schema") != PROPOSAL_SCHEMA:
            raise ProposalError("unsupported proposal schema")
        operations = raw.get("operations")
        if (
            not isinstance(operations, list)
            or not 1 <= len(operations) <= MAX_PROPOSAL_OPERATIONS
        ):
            raise ProposalError("proposal operation count is invalid")
        rationale = raw.get("rationale")
        version = raw.get("model_version")
        result = cls(
            proposal_id=_text(raw.get("proposal_id"), "proposal_id"),
            request_id=_text(raw.get("request_id"), "request_id"),
            draft_id=_text(raw.get("draft_id"), "draft_id"),
            base_revision_id=_text(raw.get("base_revision_id"), "base_revision_id"),
            base_plan_digest=_text(raw.get("base_plan_digest"), "base_plan_digest"),
            provider_id=_text(raw.get("provider_id"), "provider_id"),
            model_id=_text(raw.get("model_id"), "model_id"),
            model_version=None if version is None else _text(version, "model_version"),
            scope=ProposalScopeV1.from_data(raw.get("scope")),
            operations=tuple(PlanOperationV1.from_data(item) for item in operations),
            rationale=None
            if rationale is None
            else _text(rationale, "rationale", empty=True),
            created_at=_text(raw.get("created_at"), "created_at"),
        )
        if _identity(
            result.unsigned_data()
        ) != result.proposal_id or result.operation_set_id != raw.get(
            "operation_set_id"
        ):
            raise ProposalError("proposal identity does not bind exact content")
        return result


@dataclass(frozen=True)
class ProposalPreviewV1:
    document: PlanDocumentV1
    diff: PlanDiffV1


def _node_changed_fields(before: Any, after: Any) -> set[str]:
    return {
        field
        for field in NODE_FIELDS
        if getattr(before, field) != getattr(after, field)
    }


def _document_changed_fields(before: PlanDocumentV1, after: PlanDocumentV1) -> set[str]:
    return {
        field
        for field in DOCUMENT_FIELDS
        if getattr(before, field) != getattr(after, field)
    }


def _validate_scope(
    document: PlanDocumentV1, operation: PlanOperationV1, scope: ProposalScopeV1
) -> None:
    edit = operation.edit
    kind = edit.operation_type
    if kind not in scope.allowed_operation_types:
        raise ProposalError(f"operation {kind} exceeds proposal scope")
    targets = set(scope.target_node_ids)
    if isinstance(edit, AddNodeV1):
        target = edit.node.node_id
        changed_fields = set(NODE_FIELDS)
    elif isinstance(edit, UpdateNodeV1):
        target = edit.node.node_id
        existing = next(
            (item for item in document.nodes if item.node_id == target), None
        )
        if existing is None:
            raise ProposalError(f"proposal targets unknown PlanNode {target}")
        changed_fields = _node_changed_fields(existing, edit.node)
    elif isinstance(edit, (RemoveNodeV1, ReorderNodeV1)):
        target = edit.node_id
        changed_fields = set()
    else:
        target = None
        changed_fields = _document_changed_fields(
            document,
            PlanDocumentV1(
                goal=edit.goal,
                workspace=edit.workspace,
                submitter=document.submitter,
                nodes=document.nodes,
                constraints=edit.constraints,
                acceptance_criteria=edit.acceptance_criteria,
                execution_request=edit.execution_request,
                source_envelope_ref=document.source_envelope_ref,
            ),
        )
    if scope.kind != "exact_document" and target is not None and target not in targets:
        raise ProposalError(f"PlanNode {target} exceeds proposal scope")
    if target is None and not scope.allowed_document_fields:
        raise ProposalError("document edit exceeds proposal scope")
    if (
        target is not None
        and changed_fields
        and not changed_fields <= set(scope.allowed_node_fields)
    ):
        raise ProposalError(
            f"node fields {sorted(changed_fields - set(scope.allowed_node_fields))} exceed proposal scope"
        )
    if target is None and not changed_fields <= set(scope.allowed_document_fields):
        raise ProposalError(
            f"document fields {sorted(changed_fields - set(scope.allowed_document_fields))} exceed proposal scope"
        )


def preview_operation_sequence(
    document: PlanDocumentV1,
    operations: tuple[PlanOperationV1, ...],
    scope: ProposalScopeV1,
) -> ProposalPreviewV1:
    """Validate and apply an ordered operation set atomically in memory."""
    if not 1 <= len(operations) <= MAX_PROPOSAL_OPERATIONS:
        raise ProposalError("proposal operation count is outside the bounded protocol")
    encoded = [canonical_json_bytes(item.to_data()) for item in operations]
    if len(encoded) != len(set(encoded)):
        raise ProposalError("proposal contains duplicate operation encoding")
    candidate = document
    for operation in operations:
        _validate_scope(candidate, operation, scope)
        try:
            candidate = apply_plan_operation(candidate, operation).document
        except PlanOperationError as exc:
            raise ProposalError(str(exc)) from exc
    return ProposalPreviewV1(candidate, semantic_diff(document, candidate))


def proposal_from_provider_output(
    request: PlanEditProposalRequestV1,
    output_bytes: bytes,
    *,
    provider_id: str,
    model_id: str,
    model_version: str | None,
    created_at: str,
) -> PlanEditProposalV1:
    output = ProviderOutputV1.parse(output_bytes)
    expected = (
        request.request_id,
        request.draft_id,
        request.base_revision_id,
        request.base_plan_digest,
    )
    actual = (
        output.request_id,
        output.draft_id,
        output.base_revision_id,
        output.base_plan_digest,
    )
    if actual != expected:
        raise ProposalError(
            "provider output substituted its exact request/base binding"
        )
    preview_operation_sequence(request.document, output.operations, request.scope)
    candidate = PlanEditProposalV1(
        "",
        request.request_id,
        request.draft_id,
        request.base_revision_id,
        request.base_plan_digest,
        _text(provider_id, "provider_id"),
        _text(model_id, "model_id"),
        None if model_version is None else _text(model_version, "model_version"),
        request.scope,
        output.operations,
        output.rationale,
        _text(created_at, "proposal creation time"),
    )
    return PlanEditProposalV1(
        _identity(candidate.unsigned_data()),
        candidate.request_id,
        candidate.draft_id,
        candidate.base_revision_id,
        candidate.base_plan_digest,
        candidate.provider_id,
        candidate.model_id,
        candidate.model_version,
        candidate.scope,
        candidate.operations,
        candidate.rationale,
        candidate.created_at,
    )
