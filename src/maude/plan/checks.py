# SPDX-License-Identifier: Apache-2.0
"""Versioned structural/design checks for PlanDocument artifacts.

These checks intentionally know nothing about Nightshift currentness, AG
standing/admissibility/authorization, or Docket execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable

from maude.plan.document import PlanDocumentV1, canonical_json_bytes, content_digest

CHECK_RECEIPT_SCHEMA = "maude.plan-check-receipt/v1"
CHECKER_ID = "maude.plan-core"
CHECKER_VERSION = "1"
RULE_SET = "maude.plan-rules/v1"


@dataclass(frozen=True)
class CheckTargetV1:
    kind: str
    node_id: str | None = None

    def to_data(self) -> dict[str, Any]:
        return {"kind": self.kind, "node_id": self.node_id}


@dataclass(frozen=True)
class CheckFindingV1:
    finding_id: str
    rule_id: str
    target: CheckTargetV1
    message: str

    def to_data(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "message": self.message,
            "rule_id": self.rule_id,
            "target": self.target.to_data(),
        }


def _finding(rule: str, target: CheckTargetV1, message: str) -> CheckFindingV1:
    core = {"message": message, "rule_id": rule, "target": target.to_data()}
    return CheckFindingV1(
        content_digest(canonical_json_bytes(core)), rule, target, message
    )


@dataclass(frozen=True)
class CheckReceiptV1:
    receipt_id: str
    plan_digest: str
    checked_at: str
    result: str
    findings: tuple[CheckFindingV1, ...]
    checker_id: str = CHECKER_ID
    checker_version: str = CHECKER_VERSION
    rule_set: str = RULE_SET
    schema: str = CHECK_RECEIPT_SCHEMA

    def unsigned_data(self) -> dict[str, Any]:
        return {
            "checked_at": self.checked_at,
            "checker_id": self.checker_id,
            "checker_version": self.checker_version,
            "findings": [finding.to_data() for finding in self.findings],
            "plan_digest": self.plan_digest,
            "result": self.result,
            "rule_set": self.rule_set,
            "schema": self.schema,
        }

    def to_data(self) -> dict[str, Any]:
        return {**self.unsigned_data(), "receipt_id": self.receipt_id}

    def applies_to(self, document: PlanDocumentV1) -> bool:
        return self.plan_digest == document.digest

    @classmethod
    def from_data(cls, raw: dict[str, Any]) -> CheckReceiptV1:
        findings = tuple(
            CheckFindingV1(
                finding_id=item["finding_id"],
                rule_id=item["rule_id"],
                target=CheckTargetV1(
                    kind=item["target"]["kind"], node_id=item["target"].get("node_id")
                ),
                message=item["message"],
            )
            for item in raw["findings"]
        )
        receipt = cls(
            receipt_id=raw["receipt_id"],
            plan_digest=raw["plan_digest"],
            checked_at=raw["checked_at"],
            result=raw["result"],
            findings=findings,
            checker_id=raw["checker_id"],
            checker_version=raw["checker_version"],
            rule_set=raw["rule_set"],
            schema=raw["schema"],
        )
        if receipt.schema != CHECK_RECEIPT_SCHEMA:
            raise ValueError("unsupported check receipt schema")
        if (
            content_digest(canonical_json_bytes(receipt.unsigned_data()))
            != receipt.receipt_id
        ):
            raise ValueError("check receipt identity does not bind its content")
        return receipt


def _duplicate_findings(
    values: tuple[str, ...], rule: str, label: str
) -> list[CheckFindingV1]:
    seen: set[str] = set()
    repeated: set[str] = set()
    for value in values:
        if value in seen:
            repeated.add(value)
        seen.add(value)
    return [
        _finding(rule, CheckTargetV1("document"), f"duplicate {label}: {value}")
        for value in sorted(repeated)
    ]


def _dependency_cycles(
    document: PlanDocumentV1, known: set[str]
) -> list[CheckFindingV1]:
    adjacency = {
        node.node_id: tuple(dep for dep in node.depends_on if dep in known)
        for node in document.nodes
    }
    visiting: set[str] = set()
    visited: set[str] = set()
    cycle_nodes: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visiting:
            cycle_nodes.update(visiting)
            return
        if node_id in visited:
            return
        visiting.add(node_id)
        for dependency in adjacency.get(node_id, ()):
            visit(dependency)
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in adjacency:
        visit(node_id)
    return [
        _finding(
            "plan.dependencies.acyclic",
            CheckTargetV1("node", node_id),
            "dependency graph contains a cycle",
        )
        for node_id in sorted(cycle_nodes)
    ]


def run_checks(
    document: PlanDocumentV1,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> CheckReceiptV1:
    findings: list[CheckFindingV1] = []
    if not document.goal.strip():
        findings.append(
            _finding(
                "plan.goal.required", CheckTargetV1("document"), "goal is required"
            )
        )
    if not document.workspace.strip():
        findings.append(
            _finding(
                "plan.workspace.required",
                CheckTargetV1("document"),
                "workspace is required",
            )
        )
    if not document.nodes:
        findings.append(
            _finding(
                "plan.nodes.required",
                CheckTargetV1("document"),
                "at least one node is required",
            )
        )

    node_ids = tuple(node.node_id for node in document.nodes)
    findings.extend(_duplicate_findings(node_ids, "plan.node-id.unique", "node ID"))
    known = set(node_ids)
    for node in document.nodes:
        target = CheckTargetV1("node", node.node_id)
        for dependency in node.depends_on:
            if dependency not in known:
                findings.append(
                    _finding(
                        "plan.reference.exists",
                        target,
                        f"dependency references unknown node {dependency}",
                    )
                )
        if len(node.depends_on) != len(set(node.depends_on)):
            findings.append(
                _finding(
                    "plan.reference.unique",
                    target,
                    "dependency is declared more than once",
                )
            )
        if node.work is not None:
            findings.extend(
                _duplicate_findings(
                    node.work.write_paths,
                    "plan.work.write-path.unique",
                    f"write path on {node.node_id}",
                )
            )
            findings.extend(
                _duplicate_findings(
                    tuple(
                        canonical_json_bytes(command.to_data()).decode("utf-8")
                        for command in node.work.commands
                    ),
                    "plan.work.command.unique",
                    f"structured command on {node.node_id}",
                )
            )
        findings.extend(
            _duplicate_findings(
                node.acceptance_criteria,
                "plan.node.acceptance.unique",
                f"acceptance criterion on {node.node_id}",
            )
        )
        findings.extend(
            _duplicate_findings(
                node.stop_conditions,
                "plan.node.stop-condition.unique",
                f"stop condition on {node.node_id}",
            )
        )
    findings.extend(_dependency_cycles(document, known))
    findings.extend(
        _duplicate_findings(
            document.constraints.declared_write_paths,
            "plan.constraint.write-path.unique",
            "declared write path",
        )
    )
    findings.extend(
        _duplicate_findings(
            document.acceptance_criteria,
            "plan.acceptance.unique",
            "document acceptance criterion",
        )
    )
    if document.execution_request is not None:
        findings.extend(
            _duplicate_findings(
                document.execution_request.work.write_paths,
                "plan.execution-request.write-path.unique",
                "document execution write path",
            )
        )
        findings.extend(
            _duplicate_findings(
                tuple(
                    canonical_json_bytes(command.to_data()).decode("utf-8")
                    for command in document.execution_request.work.commands
                ),
                "plan.execution-request.command.unique",
                "document execution command",
            )
        )
    findings.extend(
        _duplicate_findings(
            tuple(
                item.requirement_id for item in document.constraints.world_requirements
            ),
            "plan.constraint.world-requirement.unique",
            "declared world requirement ID",
        )
    )
    findings.extend(
        _duplicate_findings(
            document.constraints.forbidden_paths,
            "plan.constraint.forbidden-path.unique",
            "forbidden path",
        )
    )
    budget = document.constraints.budget_tokens
    if budget is not None and budget <= 0:
        findings.append(
            _finding(
                "plan.constraint.budget.positive",
                CheckTargetV1("document"),
                "budget_tokens must be positive",
            )
        )
    findings.sort(
        key=lambda item: (
            item.rule_id,
            item.target.kind,
            item.target.node_id or "",
            item.message,
        )
    )
    checked_at = now().astimezone(UTC).isoformat().replace("+00:00", "Z")
    unsigned = {
        "checked_at": checked_at,
        "checker_id": CHECKER_ID,
        "checker_version": CHECKER_VERSION,
        "findings": [finding.to_data() for finding in findings],
        "plan_digest": document.digest,
        "result": "passed" if not findings else "refused",
        "rule_set": RULE_SET,
        "schema": CHECK_RECEIPT_SCHEMA,
    }
    return CheckReceiptV1(
        receipt_id=content_digest(canonical_json_bytes(unsigned)),
        plan_digest=document.digest,
        checked_at=checked_at,
        result=unsigned["result"],
        findings=tuple(findings),
    )
