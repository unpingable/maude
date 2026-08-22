# SPDX-License-Identifier: Apache-2.0
"""Canonical, mutable-before-handoff plan artifact model.

The document is design input, not runtime state.  It deliberately contains no
campaign, occurrence, standing, authorization, spend, custody, or settlement
field.  Stable node IDs survive presentation-order changes and provide the
future cross-probe anchor into compiled/governed facts.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from typing import Any, Mapping

from maude.plan.envelope import ExecutionRequestBlock, PlanEnvelope

PLAN_DOCUMENT_SCHEMA = "maude.plan-document/v1"
SUBMITTER_KINDS = frozenset({"human", "synthetic_agent"})
PLAN_ORIGINS = frozenset(
    {"human_written", "agent_generated", "agent_revised", "imported_from_review"}
)
_NODE_ID = re.compile(r"^pn_[a-z0-9][a-z0-9_-]{0,62}$")
_REQUIREMENT_ID = re.compile(r"^wr_[a-z0-9][a-z0-9_-]{0,62}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class PlanDocumentError(ValueError):
    """The supplied bytes cannot represent the closed v1 document schema."""


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    """Serialize the closed JSON value deterministically as UTF-8, no newline."""
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def content_digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def new_node_id() -> str:
    return "pn_" + uuid.uuid4().hex


def _closed(raw: Mapping[str, Any], allowed: set[str], where: str) -> None:
    unknown = set(raw) - allowed
    if unknown:
        raise PlanDocumentError(f"{where}: unknown field(s): {sorted(unknown)}")


def _mapping(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise PlanDocumentError(f"{where} must be an object")
    return value


def _string(value: Any, where: str, *, empty: bool = False) -> str:
    if not isinstance(value, str) or (not empty and not value.strip()):
        suffix = "a string" if empty else "a non-empty string"
        raise PlanDocumentError(f"{where} must be {suffix}")
    if "\x00" in value:
        raise PlanDocumentError(f"{where} must not contain NUL")
    return value


def _optional_string(value: Any, where: str) -> str | None:
    return None if value is None else _string(value, where)


def _strings(value: Any, where: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise PlanDocumentError(f"{where} must be an array")
    return tuple(_string(item, f"{where}[{index}]") for index, item in enumerate(value))


@dataclass(frozen=True)
class PlanCommandV1:
    program: str
    argv_prefix: tuple[str, ...] = ()

    def to_data(self) -> dict[str, Any]:
        return {"argv_prefix": list(self.argv_prefix), "program": self.program}

    @classmethod
    def from_data(cls, value: Any, where: str) -> PlanCommandV1:
        raw = _mapping(value, where)
        _closed(raw, {"program", "argv_prefix"}, where)
        return cls(
            program=_string(raw.get("program"), f"{where}.program"),
            argv_prefix=_strings(raw.get("argv_prefix", []), f"{where}.argv_prefix"),
        )


@dataclass(frozen=True)
class StructuredWorkV1:
    write_paths: tuple[str, ...] = ()
    commands: tuple[PlanCommandV1, ...] = ()

    def to_data(self) -> dict[str, Any]:
        return {
            "commands": [command.to_data() for command in self.commands],
            "write_paths": list(self.write_paths),
        }

    @classmethod
    def from_data(cls, value: Any, where: str) -> StructuredWorkV1:
        raw = _mapping(value, where)
        _closed(raw, {"write_paths", "commands"}, where)
        commands = raw.get("commands", [])
        if not isinstance(commands, list):
            raise PlanDocumentError(f"{where}.commands must be an array")
        return cls(
            write_paths=_strings(raw.get("write_paths", []), f"{where}.write_paths"),
            commands=tuple(
                PlanCommandV1.from_data(command, f"{where}.commands[{index}]")
                for index, command in enumerate(commands)
            ),
        )


@dataclass(frozen=True)
class DocumentExecutionRequestV1:
    """The existing PlanEnvelope's whole-document structured request.

    It remains a declaration, never authority.  Node-local work is not inferred
    from it; a workflow compiler must make any such mapping explicitly.
    """

    work: StructuredWorkV1
    network: str = "denied"
    git: str = "denied"
    horizon: str = "run"

    def to_data(self) -> dict[str, Any]:
        return {
            "commands": [command.to_data() for command in self.work.commands],
            "git": self.git,
            "horizon": self.horizon,
            "network": self.network,
            "write_paths": list(self.work.write_paths),
        }

    @classmethod
    def from_data(cls, value: Any, where: str) -> DocumentExecutionRequestV1:
        raw = _mapping(value, where)
        _closed(raw, {"write_paths", "commands", "network", "git", "horizon"}, where)
        work = StructuredWorkV1.from_data(
            {
                "write_paths": raw.get("write_paths", []),
                "commands": raw.get("commands", []),
            },
            where,
        )
        network = _string(raw.get("network", "denied"), f"{where}.network")
        git = _string(raw.get("git", "denied"), f"{where}.git")
        horizon = _string(raw.get("horizon", "run"), f"{where}.horizon")
        if network not in {"denied", "requested"} or git not in {"denied", "requested"}:
            raise PlanDocumentError(f"{where}: network/git must be denied or requested")
        if horizon not in {"run", "session"}:
            raise PlanDocumentError(f"{where}.horizon must be run or session")
        return cls(work=work, network=network, git=git, horizon=horizon)


@dataclass(frozen=True)
class PlanNodeV1:
    node_id: str
    description: str
    depends_on: tuple[str, ...] = ()
    work: StructuredWorkV1 | None = None
    acceptance_criteria: tuple[str, ...] = ()
    stop_conditions: tuple[str, ...] = ()

    def to_data(self) -> dict[str, Any]:
        return {
            "acceptance_criteria": list(self.acceptance_criteria),
            "depends_on": list(self.depends_on),
            "description": self.description,
            "id": self.node_id,
            "stop_conditions": list(self.stop_conditions),
            "work": None if self.work is None else self.work.to_data(),
        }

    @classmethod
    def from_data(cls, value: Any, where: str) -> PlanNodeV1:
        raw = _mapping(value, where)
        _closed(
            raw,
            {
                "id",
                "description",
                "depends_on",
                "work",
                "acceptance_criteria",
                "stop_conditions",
            },
            where,
        )
        node_id = _string(raw.get("id"), f"{where}.id")
        if not _NODE_ID.fullmatch(node_id):
            raise PlanDocumentError(f"{where}.id must match pn_<stable-lowercase-id>")
        work = raw.get("work")
        return cls(
            node_id=node_id,
            description=_string(raw.get("description"), f"{where}.description"),
            depends_on=_strings(raw.get("depends_on", []), f"{where}.depends_on"),
            work=None
            if work is None
            else StructuredWorkV1.from_data(work, f"{where}.work"),
            acceptance_criteria=_strings(
                raw.get("acceptance_criteria", []), f"{where}.acceptance_criteria"
            ),
            stop_conditions=_strings(
                raw.get("stop_conditions", []), f"{where}.stop_conditions"
            ),
        )


@dataclass(frozen=True)
class DeclaredWorldRequirementV1:
    """A desired external property, never an observation that it currently holds."""

    requirement_id: str
    statement: str

    def to_data(self) -> dict[str, Any]:
        return {"id": self.requirement_id, "statement": self.statement}

    @classmethod
    def from_data(cls, value: Any, where: str) -> DeclaredWorldRequirementV1:
        raw = _mapping(value, where)
        _closed(raw, {"id", "statement"}, where)
        requirement_id = _string(raw.get("id"), f"{where}.id")
        if not _REQUIREMENT_ID.fullmatch(requirement_id):
            raise PlanDocumentError(f"{where}.id must match wr_<stable-lowercase-id>")
        return cls(requirement_id, _string(raw.get("statement"), f"{where}.statement"))


@dataclass(frozen=True)
class DocumentConstraintsV1:
    declared_write_paths: tuple[str, ...] = ()
    forbidden_paths: tuple[str, ...] = ()
    budget_tokens: int | None = None
    halt_if: str | None = None
    world_requirements: tuple[DeclaredWorldRequirementV1, ...] = ()

    def to_data(self) -> dict[str, Any]:
        return {
            "budget_tokens": self.budget_tokens,
            "declared_write_paths": list(self.declared_write_paths),
            "forbidden_paths": list(self.forbidden_paths),
            "halt_if": self.halt_if,
            "world_requirements": [item.to_data() for item in self.world_requirements],
        }

    @classmethod
    def from_data(cls, value: Any, where: str) -> DocumentConstraintsV1:
        raw = _mapping(value, where)
        _closed(
            raw,
            {
                "declared_write_paths",
                "forbidden_paths",
                "budget_tokens",
                "halt_if",
                "world_requirements",
            },
            where,
        )
        budget = raw.get("budget_tokens")
        if budget is not None and (
            not isinstance(budget, int) or isinstance(budget, bool)
        ):
            raise PlanDocumentError(f"{where}.budget_tokens must be an integer or null")
        requirements = raw.get("world_requirements", [])
        if not isinstance(requirements, list):
            raise PlanDocumentError(f"{where}.world_requirements must be an array")
        return cls(
            declared_write_paths=_strings(
                raw.get("declared_write_paths", []), f"{where}.declared_write_paths"
            ),
            forbidden_paths=_strings(
                raw.get("forbidden_paths", []), f"{where}.forbidden_paths"
            ),
            budget_tokens=budget,
            halt_if=_optional_string(raw.get("halt_if"), f"{where}.halt_if"),
            world_requirements=tuple(
                DeclaredWorldRequirementV1.from_data(
                    item, f"{where}.world_requirements[{index}]"
                )
                for index, item in enumerate(requirements)
            ),
        )


@dataclass(frozen=True)
class SubmitterV1:
    kind: str
    origin: str
    author: str
    reference: str | None = None

    def to_data(self) -> dict[str, Any]:
        return {
            "author": self.author,
            "kind": self.kind,
            "origin": self.origin,
            "reference": self.reference,
        }

    @classmethod
    def from_data(cls, value: Any, where: str) -> SubmitterV1:
        raw = _mapping(value, where)
        _closed(raw, {"kind", "origin", "author", "reference"}, where)
        kind = _string(raw.get("kind"), f"{where}.kind")
        origin = _string(raw.get("origin"), f"{where}.origin")
        if kind not in SUBMITTER_KINDS:
            raise PlanDocumentError(f"{where}.kind is unsupported")
        if origin not in PLAN_ORIGINS:
            raise PlanDocumentError(f"{where}.origin is unsupported")
        return cls(
            kind=kind,
            origin=origin,
            author=_string(raw.get("author"), f"{where}.author"),
            reference=_optional_string(raw.get("reference"), f"{where}.reference"),
        )


@dataclass(frozen=True)
class PlanDocumentV1:
    goal: str
    workspace: str
    submitter: SubmitterV1
    nodes: tuple[PlanNodeV1, ...]
    constraints: DocumentConstraintsV1 = DocumentConstraintsV1()
    acceptance_criteria: tuple[str, ...] = ()
    execution_request: DocumentExecutionRequestV1 | None = None
    source_envelope_ref: str | None = None
    schema: str = PLAN_DOCUMENT_SCHEMA

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
            "nodes": [node.to_data() for node in self.nodes],
            "schema": self.schema,
            "source_envelope_ref": self.source_envelope_ref,
            "submitter": self.submitter.to_data(),
            "workspace": self.workspace,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_data())

    @property
    def digest(self) -> str:
        return content_digest(self.canonical_bytes)

    @classmethod
    def from_data(cls, value: Any) -> PlanDocumentV1:
        raw = _mapping(value, "document")
        _closed(
            raw,
            {
                "schema",
                "goal",
                "workspace",
                "submitter",
                "nodes",
                "constraints",
                "acceptance_criteria",
                "execution_request",
                "source_envelope_ref",
            },
            "document",
        )
        if raw.get("schema") != PLAN_DOCUMENT_SCHEMA:
            raise PlanDocumentError(
                f"unsupported document schema {raw.get('schema')!r}; expected {PLAN_DOCUMENT_SCHEMA}"
            )
        nodes = raw.get("nodes")
        if not isinstance(nodes, list):
            raise PlanDocumentError("document.nodes must be an array")
        source_ref = raw.get("source_envelope_ref")
        if source_ref is not None and not _DIGEST.fullmatch(
            _string(source_ref, "document.source_envelope_ref")
        ):
            raise PlanDocumentError(
                "document.source_envelope_ref must be sha256:<64-hex>"
            )
        execution = raw.get("execution_request")
        return cls(
            goal=_string(raw.get("goal"), "document.goal", empty=True),
            workspace=_string(raw.get("workspace"), "document.workspace", empty=True),
            submitter=SubmitterV1.from_data(raw.get("submitter"), "document.submitter"),
            nodes=tuple(
                PlanNodeV1.from_data(node, f"document.nodes[{index}]")
                for index, node in enumerate(nodes)
            ),
            constraints=DocumentConstraintsV1.from_data(
                raw.get("constraints", {}), "document.constraints"
            ),
            acceptance_criteria=_strings(
                raw.get("acceptance_criteria", []), "document.acceptance_criteria"
            ),
            execution_request=(
                None
                if execution is None
                else DocumentExecutionRequestV1.from_data(
                    execution, "document.execution_request"
                )
            ),
            source_envelope_ref=source_ref,
        )

    @classmethod
    def parse(cls, data: bytes) -> PlanDocumentV1:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PlanDocumentError("document must be UTF-8") from exc
        try:
            raw = json.loads(text)
        except (json.JSONDecodeError, ValueError) as exc:
            raise PlanDocumentError(f"document is not valid JSON: {exc}") from exc
        return cls.from_data(raw)


def _legacy_node_id(plan_ref: str, index: int) -> str:
    seed = f"{plan_ref}\x00step\x00{index}".encode("utf-8")
    return "pn_" + hashlib.sha256(seed).hexdigest()[:32]


def import_plan_envelope(envelope: PlanEnvelope) -> PlanDocumentV1:
    """Explicit one-time conversion.  The historical envelope remains unchanged.

    Existing ordered prose steps become stable nodes.  The aggregate execution
    request remains aggregate: conversion does not guess which step owns it.
    """
    request: DocumentExecutionRequestV1 | None = None
    if envelope.execution_request is not None:
        block: ExecutionRequestBlock = envelope.execution_request
        request = DocumentExecutionRequestV1(
            work=StructuredWorkV1(
                write_paths=block.write_paths,
                commands=tuple(
                    PlanCommandV1(command.program, command.argv_prefix)
                    for command in block.commands
                ),
            ),
            network=block.network,
            git=block.git,
            horizon=block.horizon,
        )
    paths = envelope.scope_allowlist
    if request is not None:
        paths = request.work.write_paths
    return PlanDocumentV1(
        goal=envelope.goal,
        workspace=envelope.workspace,
        submitter=SubmitterV1(
            kind=envelope.submitter_kind,
            origin=envelope.plan_origin,
            author=envelope.provenance_author,
            reference=envelope.provenance_ref,
        ),
        nodes=tuple(
            PlanNodeV1(
                node_id=_legacy_node_id(envelope.plan_ref, index), description=step
            )
            for index, step in enumerate(envelope.steps)
        ),
        constraints=DocumentConstraintsV1(
            declared_write_paths=paths,
            forbidden_paths=envelope.stop_forbidden_paths,
            budget_tokens=envelope.stop_budget_tokens,
            halt_if=envelope.stop_halt_if,
        ),
        acceptance_criteria=envelope.acceptance_criteria,
        execution_request=request,
        source_envelope_ref=envelope.plan_ref,
    )
