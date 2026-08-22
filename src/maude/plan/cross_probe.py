# SPDX-License-Identifier: Apache-2.0
"""Exact read-only PlanNode to governed-runtime cross-probe projections.

The projection joins owner-produced receipts by exact identity.  It is a
navigation/audit artifact, never authority and never a substitute for any
owner's current read model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from maude.plan.document import canonical_json_bytes, content_digest

GOVERNED_NODE_BINDING_SCHEMA = "maude.plan-node-governed-binding/v1"
GOVERNED_CROSS_PROBE_SCHEMA = "maude.plan-governed-cross-probe/v1"


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or not (
        value.startswith("sha256:")
        and len(value) == 71
        and all(character in "0123456789abcdef" for character in value[7:])
    ):
        raise ValueError(f"{field} must be a canonical sha256 identity")
    return value


def _occurrence(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("occurrence_id must be a canonical UUID")
    parsed = UUID(value)
    if str(parsed) != value:
        raise ValueError("occurrence_id must be lowercase canonical UUID")
    return value


@dataclass(frozen=True)
class GovernedNodeBindingV1:
    """One exact node/compiler/lineage/execution relationship.

    The binding contains no spend, signature, credential, capability, or
    authorization material.  Its inspector path is a locator only.
    """

    binding_id: str
    draft_id: str
    node_id: str
    plan_digest: str
    compilation_id: str
    compiled_output_identity: str
    exact_work_identity: str
    authoring_provenance_id: str
    handoff_id: str
    campaign_id: str
    occurrence_id: str
    proposal_id: str
    issuance_id: str
    docket_attempt_id: str
    settlement_id: str
    outcome: str
    inspector_path: str
    schema: str = GOVERNED_NODE_BINDING_SCHEMA

    def unsigned_data(self) -> dict[str, Any]:
        return {
            "authoring_provenance_id": self.authoring_provenance_id,
            "campaign_id": self.campaign_id,
            "compilation_id": self.compilation_id,
            "compiled_output_identity": self.compiled_output_identity,
            "docket_attempt_id": self.docket_attempt_id,
            "draft_id": self.draft_id,
            "exact_work_identity": self.exact_work_identity,
            "handoff_id": self.handoff_id,
            "inspector_path": self.inspector_path,
            "issuance_id": self.issuance_id,
            "node_id": self.node_id,
            "occurrence_id": self.occurrence_id,
            "outcome": self.outcome,
            "plan_digest": self.plan_digest,
            "proposal_id": self.proposal_id,
            "schema": self.schema,
            "settlement_id": self.settlement_id,
        }

    def to_data(self) -> dict[str, Any]:
        return {**self.unsigned_data(), "binding_id": self.binding_id}

    @classmethod
    def create(cls, **facts: str) -> GovernedNodeBindingV1:
        candidate = cls(binding_id="", **facts)
        return cls(
            binding_id=content_digest(canonical_json_bytes(candidate.unsigned_data())),
            **facts,
        )

    @classmethod
    def from_data(cls, value: dict[str, Any]) -> GovernedNodeBindingV1:
        expected = {
            "authoring_provenance_id",
            "binding_id",
            "campaign_id",
            "compilation_id",
            "compiled_output_identity",
            "docket_attempt_id",
            "draft_id",
            "exact_work_identity",
            "handoff_id",
            "inspector_path",
            "issuance_id",
            "node_id",
            "occurrence_id",
            "outcome",
            "plan_digest",
            "proposal_id",
            "schema",
            "settlement_id",
        }
        if (
            set(value) != expected
            or value.get("schema") != GOVERNED_NODE_BINDING_SCHEMA
        ):
            raise ValueError("governed PlanNode binding has an unsupported shape")
        for field in (
            "binding_id",
            "campaign_id",
            "compilation_id",
            "compiled_output_identity",
            "docket_attempt_id",
            "exact_work_identity",
            "handoff_id",
            "issuance_id",
            "plan_digest",
            "proposal_id",
            "settlement_id",
            "authoring_provenance_id",
        ):
            _digest(value[field], field)
        _occurrence(value["occurrence_id"])
        if not isinstance(value["draft_id"], str) or not value["draft_id"]:
            raise ValueError("draft_id must be non-empty")
        if not isinstance(value["node_id"], str) or not value["node_id"]:
            raise ValueError("node_id must be non-empty")
        if value["outcome"] not in {"success", "failure"}:
            raise ValueError("settled governed node binding requires a known outcome")
        expected_path = (
            "/phosphor-ng/campaigns/"
            + value["campaign_id"].replace(":", "%3A")
            + "/occurrences/"
            + value["occurrence_id"]
            + "/proposals/"
            + value["proposal_id"].replace(":", "%3A")
        )
        if value["inspector_path"] != expected_path:
            raise ValueError("governed PlanNode inspector path is not exact")
        binding = cls(**value)
        if (
            content_digest(canonical_json_bytes(binding.unsigned_data()))
            != binding.binding_id
        ):
            raise ValueError(
                "governed PlanNode binding identity does not bind its content"
            )
        return binding


def parse_cross_probe(
    value: object,
) -> dict[str, tuple[GovernedNodeBindingV1, ...]]:
    if not isinstance(value, dict) or set(value) != {"bindings", "schema"}:
        raise ValueError("governed cross-probe projection is malformed")
    if value.get("schema") != GOVERNED_CROSS_PROBE_SCHEMA:
        raise ValueError("unsupported governed cross-probe schema")
    if not isinstance(value["bindings"], list):
        raise ValueError("governed cross-probe bindings must be an array")
    result: dict[str, list[GovernedNodeBindingV1]] = {}
    for raw in value["bindings"]:
        if not isinstance(raw, dict):
            raise ValueError("governed cross-probe binding must be an object")
        binding = GovernedNodeBindingV1.from_data(raw)
        result.setdefault(binding.draft_id, []).append(binding)
    return {draft_id: tuple(items) for draft_id, items in result.items()}
