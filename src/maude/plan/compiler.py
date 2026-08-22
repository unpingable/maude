# SPDX-License-Identifier: Apache-2.0
"""Closed workflow-specific compiler seam for locked plan artifacts.

There is intentionally no prose-to-operation compiler.  A compiler must name a
specific workflow and emit exact existing handoff bytes plus explicit node
bindings; absent one, compilation refuses without guessing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from maude.plan.document import PlanDocumentV1, canonical_json_bytes, content_digest

COMPILATION_RECEIPT_SCHEMA = "maude.plan-compilation-receipt/v1"


class CompilerUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class CompiledNodeBindingV1:
    node_id: str
    output_identity: str


@dataclass(frozen=True)
class CompilationResultV1:
    compiler_id: str
    compiler_version: str
    source_plan_digest: str
    compiler_inputs_schema: str
    compiler_inputs_digest: str
    handoff_bytes: bytes
    node_bindings: tuple[CompiledNodeBindingV1, ...] = ()

    @property
    def handoff_digest(self) -> str:
        return content_digest(self.handoff_bytes)


@dataclass(frozen=True)
class CompilationReceiptV1:
    """Immutable representation receipt for one exact locked artifact.

    The receipt records compilation, not currentness, admissibility, standing,
    authorization, custody, execution, or settlement.
    """

    compilation_id: str
    draft_id: str
    revision_id: str
    lock_id: str
    plan_digest: str
    compiler_id: str
    compiler_version: str
    compiler_inputs_schema: str
    compiler_inputs_digest: str
    compiled_output_digest: str
    exact_work_identity: str
    node_bindings: tuple[CompiledNodeBindingV1, ...]
    compiled_at: str
    schema: str = COMPILATION_RECEIPT_SCHEMA

    def unsigned_data(self) -> dict[str, Any]:
        return {
            "compiled_at": self.compiled_at,
            "compiled_output_digest": self.compiled_output_digest,
            "compiler_id": self.compiler_id,
            "compiler_inputs_digest": self.compiler_inputs_digest,
            "compiler_inputs_schema": self.compiler_inputs_schema,
            "compiler_version": self.compiler_version,
            "draft_id": self.draft_id,
            "exact_work_identity": self.exact_work_identity,
            "lock_id": self.lock_id,
            "node_bindings": [
                {"node_id": item.node_id, "output_identity": item.output_identity}
                for item in self.node_bindings
            ],
            "plan_digest": self.plan_digest,
            "revision_id": self.revision_id,
            "schema": self.schema,
        }

    def to_data(self) -> dict[str, Any]:
        return {**self.unsigned_data(), "compilation_id": self.compilation_id}

    @classmethod
    def create(
        cls,
        *,
        draft_id: str,
        revision_id: str,
        lock_id: str,
        result: CompilationResultV1,
        exact_work_identity: str,
        compiled_at: str,
    ) -> CompilationReceiptV1:
        candidate = cls(
            "",
            draft_id,
            revision_id,
            lock_id,
            result.source_plan_digest,
            result.compiler_id,
            result.compiler_version,
            result.compiler_inputs_schema,
            result.compiler_inputs_digest,
            result.handoff_digest,
            exact_work_identity,
            result.node_bindings,
            compiled_at,
        )
        return cls(content_digest(canonical_json_bytes(candidate.unsigned_data())), **{
            field: getattr(candidate, field)
            for field in (
                "draft_id",
                "revision_id",
                "lock_id",
                "plan_digest",
                "compiler_id",
                "compiler_version",
                "compiler_inputs_schema",
                "compiler_inputs_digest",
                "compiled_output_digest",
                "exact_work_identity",
                "node_bindings",
                "compiled_at",
            )
        })

    @classmethod
    def from_data(cls, value: dict[str, Any]) -> CompilationReceiptV1:
        bindings = tuple(
            CompiledNodeBindingV1(item["node_id"], item["output_identity"])
            for item in value["node_bindings"]
        )
        receipt = cls(
            value["compilation_id"],
            value["draft_id"],
            value["revision_id"],
            value["lock_id"],
            value["plan_digest"],
            value["compiler_id"],
            value["compiler_version"],
            value["compiler_inputs_schema"],
            value["compiler_inputs_digest"],
            value["compiled_output_digest"],
            value["exact_work_identity"],
            bindings,
            value["compiled_at"],
            value["schema"],
        )
        if (
            receipt.schema != COMPILATION_RECEIPT_SCHEMA
            or content_digest(canonical_json_bytes(receipt.unsigned_data()))
            != receipt.compilation_id
        ):
            raise ValueError("compilation receipt identity does not bind its content")
        return receipt


class VersionedCompilerInputs(Protocol):
    """Workflow-specific explicit inputs; no ambient facts are implied."""

    schema: str

    @property
    def canonical_bytes(self) -> bytes: ...


class WorkflowPlanCompilerV1(Protocol):
    compiler_id: str
    compiler_version: str

    def compile(
        self, document: PlanDocumentV1, inputs: VersionedCompilerInputs
    ) -> CompilationResultV1: ...


class CompilerRegistryV1:
    def __init__(self) -> None:
        self._compilers: dict[str, WorkflowPlanCompilerV1] = {}

    def register(self, workflow: str, compiler: WorkflowPlanCompilerV1) -> None:
        if workflow in self._compilers:
            raise ValueError(f"compiler already registered for {workflow}")
        self._compilers[workflow] = compiler

    def compile(
        self,
        workflow: str,
        document: PlanDocumentV1,
        inputs: VersionedCompilerInputs,
    ) -> CompilationResultV1:
        compiler = self._compilers.get(workflow)
        if compiler is None:
            raise CompilerUnavailable(
                f"compiler unavailable for workflow {workflow!r}; exact structured work is required"
            )
        first = compiler.compile(document, inputs)
        second = compiler.compile(document, inputs)
        if first != second:
            raise ValueError(
                "compiler is nondeterministic for identical document/version/explicit inputs"
            )
        result = first
        if result.source_plan_digest != document.digest:
            raise ValueError(
                "compiler output is not bound to the supplied PlanDocument digest"
            )
        if (
            result.compiler_id != compiler.compiler_id
            or result.compiler_version != compiler.compiler_version
        ):
            raise ValueError(
                "compiler output identity/version does not match the selected compiler"
            )
        if (
            result.compiler_inputs_schema != inputs.schema
            or result.compiler_inputs_digest != content_digest(inputs.canonical_bytes)
        ):
            raise ValueError(
                "compiler output is not bound to its explicit versioned inputs"
            )
        known = {node.node_id for node in document.nodes}
        if any(binding.node_id not in known for binding in result.node_bindings):
            raise ValueError("compiler returned a binding for an unknown PlanNode")
        return result
