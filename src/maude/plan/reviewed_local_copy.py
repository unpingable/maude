# SPDX-License-Identifier: Apache-2.0
"""Closed, read-only validation for the reviewed local-copy interface.

This module produces and checks evidence only.  It neither accepts a review nor
performs the resulting copy.  The only work described by its compiler is to
copy one exact, bounded public-text byte sequence to ``result.txt`` inside an
executor-owned exclusive scratch directory.
"""

from __future__ import annotations

import base64
import argparse
import json
import re
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from maude.plan.checks import CHECKER_ID, CHECKER_VERSION, RULE_SET
from maude.plan.compiler import (
    CompiledNodeBindingV1,
    CompilationReceiptV1,
    CompilationResultV1,
)
from maude.plan.document import PlanDocumentV1, canonical_json_bytes, content_digest
from maude.plan.local_compose import ag_executor_plan_identity
from maude.plan.store import DraftStore, LockReceiptV1


BINDING_SCHEMA = "maude.governed-plan-binding/v1"
COMPILER_CONTRACT = "maude.reviewed-local-copy/v1"
INPUT_SCHEMA = "maude.reviewed-local-copy-input/v1"
HANDOFF_SCHEMA = "nightshift.precompiled_workflow_proposal.v2"
EXECUTOR_PLAN_SCHEMA = "maude.reviewed-local-copy.docket-executor-plan/v1"
VALIDATOR_CONFIG_SCHEMA = "maude.reviewed-local-copy-validator-config/v1"
VALIDATION_SCHEMA = "maude.governed-plan-validation/v1"
MAX_OUTER_BYTES = 16 * 1024 * 1024
MAX_PLAN_BYTES = 1024 * 1024
MAX_REVIEWED_TEXT_BYTES = 64 * 1024
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_ARTIFACTS = (
    "plan_document",
    "lock_receipt",
    "compiler_inputs",
    "compiled_handoff",
    "compilation_receipt",
    "executor_plan",
)


class ReviewedLocalCopyError(ValueError):
    """A closed interface or its stored evidence is inconsistent."""


def _closed(value: Mapping[str, Any], expected: set[str], where: str) -> None:
    if set(value) != expected:
        raise ReviewedLocalCopyError(
            f"{where} fields differ: expected {sorted(expected)}, got {sorted(value)}"
        )


def _object(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReviewedLocalCopyError(f"{where} must be an object")
    return value


def _reject_floats(value: Any, where: str) -> None:
    if isinstance(value, float):
        raise ReviewedLocalCopyError(f"{where} must not contain floats")
    if isinstance(value, dict):
        for key, item in value.items():
            _reject_floats(item, f"{where}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_floats(item, f"{where}[{index}]")


def _string(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ReviewedLocalCopyError(f"{where} must be a non-empty string without NUL")
    return value


def _digest(value: Any, where: str) -> str:
    value = _string(value, where)
    if not _DIGEST.fullmatch(value):
        raise ReviewedLocalCopyError(f"{where} must be a sha256 digest")
    return value


def _canonical_json(raw: bytes, where: str) -> tuple[dict[str, Any], bytes]:
    if len(raw) > MAX_OUTER_BYTES:
        raise ReviewedLocalCopyError(f"{where} exceeds {MAX_OUTER_BYTES} bytes")
    body = raw[:-1] if raw.endswith(b"\n") else raw
    if raw.endswith(b"\n\n") or not body:
        raise ReviewedLocalCopyError(f"{where} has unsupported trailing data")
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReviewedLocalCopyError(f"{where} is not JSON") from error
    value = _object(value, where)
    _reject_floats(value, where)
    canonical = canonical_json_bytes(value)
    if body != canonical:
        raise ReviewedLocalCopyError(f"{where} must use canonical JSON bytes")
    return value, canonical


def _artifact(value: Any, name: str, *, maximum: int) -> bytes:
    raw = _object(value, f"artifacts.{name}")
    _closed(raw, {"sha256", "byte_length", "bytes_base64"}, f"artifacts.{name}")
    digest = _digest(raw["sha256"], f"artifacts.{name}.sha256")
    length = raw["byte_length"]
    encoded = raw["bytes_base64"]
    if isinstance(length, bool) or not isinstance(length, int) or length < 0:
        raise ReviewedLocalCopyError(f"artifacts.{name}.byte_length must be nonnegative")
    if length > maximum or not isinstance(encoded, str):
        raise ReviewedLocalCopyError(f"artifacts.{name} exceeds its closed bound")
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as error:
        raise ReviewedLocalCopyError(f"artifacts.{name}.bytes_base64 is not standard base64") from error
    if base64.b64encode(decoded).decode("ascii") != encoded:
        raise ReviewedLocalCopyError(f"artifacts.{name}.bytes_base64 is noncanonical")
    if len(decoded) != length or content_digest(decoded) != digest:
        raise ReviewedLocalCopyError(f"artifacts.{name} identity does not bind bytes")
    return decoded


def _artifact_data(raw: bytes) -> dict[str, Any]:
    return {
        "sha256": content_digest(raw),
        "byte_length": len(raw),
        "bytes_base64": base64.b64encode(raw).decode("ascii"),
    }


@dataclass(frozen=True)
class ReviewedLocalCopyInputsV1:
    campaign: str
    occurrence: str
    program: str
    subject: str
    scope: str
    scratch_root: str
    observation: str
    reviewed_text: bytes

    schema: str = INPUT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != INPUT_SCHEMA:
            raise ReviewedLocalCopyError("unsupported compiler input schema")
        for name, value in (
            ("campaign", self.campaign),
            ("subject", self.subject),
            ("scope", self.scope),
            ("program", self.program),
            ("observation", self.observation),
        ):
            _digest(value, f"compiler inputs.{name}")
        try:
            parsed_occurrence = uuid.UUID(self.occurrence)
        except (ValueError, AttributeError) as error:
            raise ReviewedLocalCopyError("compiler inputs.occurrence must be a UUID") from error
        if str(parsed_occurrence) != self.occurrence:
            raise ReviewedLocalCopyError("compiler inputs.occurrence must be canonical lowercase UUID")
        _string(self.scratch_root, "compiler inputs.scratch_root")
        if not Path(self.scratch_root).is_absolute():
            raise ReviewedLocalCopyError("compiler inputs.scratch_root must be absolute")
        if len(self.reviewed_text) > MAX_REVIEWED_TEXT_BYTES:
            raise ReviewedLocalCopyError("reviewed text exceeds 64 KiB")
        try:
            self.reviewed_text.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ReviewedLocalCopyError("reviewed text must be strict UTF-8") from error

    def to_data(self) -> dict[str, Any]:
        return {
            "campaign": self.campaign,
            "occurrence": self.occurrence,
            "program": self.program,
            "reviewed_text_base64": base64.b64encode(self.reviewed_text).decode("ascii"),
            "reviewed_text_byte_length": len(self.reviewed_text),
            "reviewed_text_digest": content_digest(self.reviewed_text),
            "observation": self.observation,
            "schema": self.schema,
            "scope": self.scope,
            "scratch_root": self.scratch_root,
            "subject": self.subject,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_data())

    @classmethod
    def from_bytes(cls, raw: bytes) -> ReviewedLocalCopyInputsV1:
        value, _ = _canonical_json(raw, "compiler inputs")
        _closed(value, {"schema", "campaign", "occurrence", "program", "subject", "scope", "scratch_root", "observation", "reviewed_text_digest", "reviewed_text_byte_length", "reviewed_text_base64"}, "compiler inputs")
        if value["schema"] != INPUT_SCHEMA:
            raise ReviewedLocalCopyError("unsupported compiler input schema")
        text = _artifact(
            {"sha256": value["reviewed_text_digest"], "byte_length": value["reviewed_text_byte_length"], "bytes_base64": value["reviewed_text_base64"]},
            "reviewed_text", maximum=MAX_REVIEWED_TEXT_BYTES,
        )
        return cls(
            value["campaign"], value["occurrence"], value["program"], value["subject"], value["scope"],
            value["scratch_root"], value["observation"], text,
        )


class ReviewedLocalCopyCompilerV1:
    compiler_id = COMPILER_CONTRACT
    compiler_version = "1"

    def compile(self, document: PlanDocumentV1, inputs: ReviewedLocalCopyInputsV1) -> CompilationResultV1:
        copy_nodes = [node for node in document.nodes if node.work is not None and node.work.commands == () and node.work.write_paths == ("result.txt",)]
        # The document must name exactly one typed local-copy node. No command or
        # caller-supplied destination is accepted by this compiler.
        if (
            len(document.nodes) != 1
            or len(copy_nodes) != 1
            or document.execution_request is not None
            or document.constraints.declared_write_paths != ("result.txt",)
        ):
            raise ReviewedLocalCopyError("document must contain exactly one result.txt local-copy node")
        executor_plan = {
            "action": "copy_reviewed_text",
            "campaign": inputs.campaign,
            "compiler": {"id": self.compiler_id, "inputs_digest": content_digest(inputs.canonical_bytes), "version": self.compiler_version},
            "destination": "result.txt",
            "occurrence": inputs.occurrence,
            "plan_document_digest": document.digest,
            "program_basis": inputs.program,
            "reviewed_text_base64": base64.b64encode(inputs.reviewed_text).decode("ascii"),
            "reviewed_text_byte_length": len(inputs.reviewed_text),
            "reviewed_text_digest": content_digest(inputs.reviewed_text),
            "schema": EXECUTOR_PLAN_SCHEMA,
            "scope_digest": inputs.scope,
            "scratch_root": inputs.scratch_root,
            "subject_digest": inputs.subject,
        }
        executor_bytes = canonical_json_bytes(executor_plan)
        work = ag_executor_plan_identity(executor_plan)
        handoff = {
            "ag_executor_plan": executor_plan,
            "campaign_id": inputs.campaign,
            "immutable_parameters": {"compiler_inputs": content_digest(inputs.canonical_bytes), "plan_document": document.digest, "workflow_action": "copy_reviewed_text"},
            "intent_kind": "reviewed_local_copy",
            "mode": {"genesis": {"genesis": {"budget": {"escalation_limit": 0, "escalations_used": 0, "probe_limit": 0, "probes_used": 0, "retries_used": 0, "retry_limit": 0}, "campaign": inputs.campaign, "expected_ag_work": work, "occurrence": inputs.occurrence, "program": inputs.program, "residuals": []}}},
            "occurrence_id": inputs.occurrence,
            "proposal_input": {"class": "initial", "observation": inputs.observation, "proposal": {"campaign": inputs.campaign, "repair": None, "schema": "ag.governed-loop.exact-work-proposal/v1", "scope": inputs.scope, "subject": inputs.subject, "work": work, "work_schema": COMPILER_CONTRACT}},
            "schema": HANDOFF_SCHEMA,
            "subject_digest": inputs.subject,
            "workflow_id": COMPILER_CONTRACT,
        }
        return CompilationResultV1(
            self.compiler_id, self.compiler_version, document.digest, inputs.schema,
            content_digest(inputs.canonical_bytes), canonical_json_bytes(handoff),
            (CompiledNodeBindingV1(copy_nodes[0].node_id, work),),
        )


@dataclass(frozen=True)
class GovernedPlanBindingV1:
    binding_id: str
    campaign: str
    occurrence: str
    subject: str
    scope: str
    work_schema: str
    work: str
    compiler_contract: str
    plan_document_digest: str
    lock_id: str
    compilation_id: str
    artifacts: dict[str, bytes]

    @classmethod
    def from_bytes(cls, raw: bytes) -> GovernedPlanBindingV1:
        value, canonical = _canonical_json(raw, "binding")
        fields = {"schema", "binding_id", "campaign", "occurrence", "subject", "scope", "work_schema", "work", "compiler_contract", "plan_document_digest", "lock_id", "compilation_id", "artifacts"}
        _closed(value, fields, "binding")
        if value["schema"] != BINDING_SCHEMA:
            raise ReviewedLocalCopyError("unsupported binding schema")
        expected_id = content_digest(BINDING_SCHEMA.encode("utf-8") + b"\0" + canonical_json_bytes({key: value[key] for key in value if key != "binding_id"}))
        if value["binding_id"] != expected_id:
            raise ReviewedLocalCopyError("binding identity does not bind its outer fields")
        for key in ("work_schema", "compiler_contract"):
            _string(value[key], f"binding.{key}")
        for key in ("campaign", "subject", "scope"):
            _digest(value[key], f"binding.{key}")
        try:
            parsed_occurrence = uuid.UUID(value["occurrence"])
        except (ValueError, AttributeError) as error:
            raise ReviewedLocalCopyError("binding.occurrence must be a UUID") from error
        if str(parsed_occurrence) != value["occurrence"]:
            raise ReviewedLocalCopyError("binding.occurrence must be canonical lowercase UUID")
        for key in ("work", "plan_document_digest", "lock_id", "compilation_id"):
            _digest(value[key], f"binding.{key}")
        artifacts = _object(value["artifacts"], "binding.artifacts")
        _closed(artifacts, set(_ARTIFACTS), "binding.artifacts")
        decoded = {name: _artifact(artifacts[name], name, maximum=MAX_PLAN_BYTES if name == "plan_document" else MAX_OUTER_BYTES) for name in _ARTIFACTS}
        if content_digest(decoded["plan_document"]) != value["plan_document_digest"]:
            raise ReviewedLocalCopyError("PlanDocument artifact differs from outer digest")
        return cls(value["binding_id"], value["campaign"], value["occurrence"], value["subject"], value["scope"], value["work_schema"], value["work"], value["compiler_contract"], value["plan_document_digest"], value["lock_id"], value["compilation_id"], decoded)


@dataclass(frozen=True)
class ReviewedLocalCopyValidatorConfigV1:
    store_locator: str
    schema: str = VALIDATOR_CONFIG_SCHEMA
    compiler_contract: str = COMPILER_CONTRACT
    compiler_id: str = COMPILER_CONTRACT
    compiler_version: str = "1"
    checker_id: str = CHECKER_ID
    checker_version: str = CHECKER_VERSION
    rule_set: str = RULE_SET

    def to_data(self) -> dict[str, Any]:
        return {
            "checker_id": self.checker_id, "checker_version": self.checker_version,
            "compiler_contract": self.compiler_contract, "compiler_id": self.compiler_id,
            "compiler_version": self.compiler_version, "rule_set": self.rule_set,
            "schema": self.schema, "store_locator": self.store_locator,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_data())

    @property
    def digest(self) -> str:
        return content_digest(self.canonical_bytes)

    @classmethod
    def from_bytes(cls, raw: bytes) -> ReviewedLocalCopyValidatorConfigV1:
        value, _ = _canonical_json(raw, "validator configuration")
        fields = {"schema", "store_locator", "compiler_contract", "compiler_id", "compiler_version", "checker_id", "checker_version", "rule_set"}
        _closed(value, fields, "validator configuration")
        config = cls(**value)
        config.validate()
        return config

    def validate(self) -> None:
        if self.schema != VALIDATOR_CONFIG_SCHEMA or self.compiler_contract != COMPILER_CONTRACT:
            raise ReviewedLocalCopyError("unsupported validator configuration")
        if (self.compiler_id, self.compiler_version, self.checker_id, self.checker_version, self.rule_set) != (COMPILER_CONTRACT, "1", CHECKER_ID, CHECKER_VERSION, RULE_SET):
            raise ReviewedLocalCopyError("validator configuration selects an unenrolled compiler or checker")
        if not isinstance(self.store_locator, str) or not Path(self.store_locator).is_absolute():
            raise ReviewedLocalCopyError("store locator must be an absolute pinned path")


def build_reviewed_local_copy_binding(
    document: PlanDocumentV1,
    lock: LockReceiptV1,
    inputs: ReviewedLocalCopyInputsV1,
    result: CompilationResultV1,
    receipt: CompilationReceiptV1,
) -> bytes:
    """Construct the closed outer binding from already stored compiler facts."""
    handoff, _ = _canonical_json(result.handoff_bytes, "compiled handoff")
    executor_bytes = canonical_json_bytes(handoff.get("ag_executor_plan"))
    unsigned = {
        "schema": BINDING_SCHEMA,
        "campaign": inputs.campaign,
        "occurrence": inputs.occurrence,
        "subject": inputs.subject,
        "scope": inputs.scope,
        "work_schema": COMPILER_CONTRACT,
        "work": receipt.exact_work_identity,
        "compiler_contract": COMPILER_CONTRACT,
        "plan_document_digest": document.digest,
        "lock_id": lock.lock_id,
        "compilation_id": receipt.compilation_id,
        "artifacts": {
            "plan_document": _artifact_data(document.canonical_bytes),
            "lock_receipt": _artifact_data(canonical_json_bytes(lock.to_data())),
            "compiler_inputs": _artifact_data(inputs.canonical_bytes),
            "compiled_handoff": _artifact_data(result.handoff_bytes),
            "compilation_receipt": _artifact_data(canonical_json_bytes(receipt.to_data())),
            "executor_plan": _artifact_data(executor_bytes),
        },
    }
    binding = {
        **unsigned,
        "binding_id": content_digest(
            BINDING_SCHEMA.encode("utf-8") + b"\0" + canonical_json_bytes(unsigned)
        ),
    }
    return canonical_json_bytes(binding)


def compile_and_bind_reviewed_local_copy(
    store: DraftStore, draft_id: str, inputs: ReviewedLocalCopyInputsV1
) -> bytes:
    """Use the supported store/compiler path; it never performs executor work."""
    current = store.current(draft_id)
    lock = next(
        (item for item in store.locks(draft_id) if item.revision_id == current.revision_id),
        None,
    )
    if lock is None:
        raise ReviewedLocalCopyError("current revision must be locked before compilation")
    passed = [
        item
        for item in store.check_receipts(draft_id, current.revision_id)
        if item.plan_digest == current.plan_digest
        and item.checker_id == CHECKER_ID
        and item.checker_version == CHECKER_VERSION
        and item.rule_set == RULE_SET
        and item.result == "passed"
    ]
    if not passed:
        raise ReviewedLocalCopyError("current revision requires a passing Plan Core check")
    result = ReviewedLocalCopyCompilerV1().compile(current.document, inputs)
    receipt = store.record_compilation(
        draft_id,
        lock.lock_id,
        result,
        compiler_inputs=inputs.canonical_bytes,
        exact_work_identity=ag_executor_plan_identity(
            json.loads(result.handoff_bytes)["ag_executor_plan"]
        ),
    )
    return build_reviewed_local_copy_binding(current.document, lock, inputs, result, receipt)


def _json_artifact(raw: bytes, parser: Any, name: str) -> Any:
    value, _ = _canonical_json(raw, name)
    try:
        return parser(value)
    except (KeyError, TypeError, ValueError) as error:
        raise ReviewedLocalCopyError(f"{name} is invalid") from error


def validate_reviewed_local_copy_binding(raw: bytes, config: ReviewedLocalCopyValidatorConfigV1) -> dict[str, Any]:
    """Read and recompile one binding against its configured actual store.

    The operation opens SQLite in read-only mode and performs no executor,
    provider, review, lock, or check mutation.
    """
    config.validate()
    binding = GovernedPlanBindingV1.from_bytes(raw)
    if binding.compiler_contract != COMPILER_CONTRACT or binding.work_schema != COMPILER_CONTRACT:
        raise ReviewedLocalCopyError("binding selects an unsupported compiler contract")
    document = PlanDocumentV1.parse(binding.artifacts["plan_document"])
    lock = _json_artifact(binding.artifacts["lock_receipt"], LockReceiptV1.from_data, "lock receipt")
    receipt = _json_artifact(binding.artifacts["compilation_receipt"], CompilationReceiptV1.from_data, "compilation receipt")
    inputs = ReviewedLocalCopyInputsV1.from_bytes(binding.artifacts["compiler_inputs"])
    handoff, _ = _canonical_json(binding.artifacts["compiled_handoff"], "compiled handoff")
    executor_plan, executor_bytes = _canonical_json(binding.artifacts["executor_plan"], "executor plan")
    if (document.digest, lock.lock_id, receipt.compilation_id) != (binding.plan_document_digest, binding.lock_id, binding.compilation_id):
        raise ReviewedLocalCopyError("binding identities differ from supplied artifacts")
    if (inputs.campaign, inputs.occurrence, inputs.subject, inputs.scope) != (binding.campaign, binding.occurrence, binding.subject, binding.scope):
        raise ReviewedLocalCopyError("compiler inputs differ from outer binding")
    _closed(handoff, {"schema", "ag_executor_plan", "campaign_id", "immutable_parameters", "intent_kind", "mode", "occurrence_id", "proposal_input", "subject_digest", "workflow_id"}, "compiled handoff")
    _closed(executor_plan, {"schema", "action", "campaign", "compiler", "destination", "occurrence", "plan_document_digest", "program_basis", "reviewed_text_base64", "reviewed_text_byte_length", "reviewed_text_digest", "scope_digest", "scratch_root", "subject_digest"}, "executor plan")
    proposal = handoff.get("proposal_input")
    if not isinstance(proposal, dict) or proposal.get("proposal") != {"campaign": binding.campaign, "repair": None, "schema": "ag.governed-loop.exact-work-proposal/v1", "scope": binding.scope, "subject": binding.subject, "work": binding.work, "work_schema": binding.work_schema}:
        raise ReviewedLocalCopyError("handoff differs from outer binding")
    if (handoff.get("schema"), handoff.get("campaign_id"), handoff.get("occurrence_id"), handoff.get("subject_digest"), handoff.get("workflow_id"), handoff.get("ag_executor_plan")) != (HANDOFF_SCHEMA, binding.campaign, binding.occurrence, binding.subject, COMPILER_CONTRACT, executor_plan):
        raise ReviewedLocalCopyError("handoff differs from outer binding")
    if (executor_plan.get("schema"), executor_plan.get("action"), executor_plan.get("campaign"), executor_plan.get("occurrence"), executor_plan.get("program_basis"), executor_plan.get("subject_digest"), executor_plan.get("scope_digest"), executor_plan.get("plan_document_digest"), executor_plan.get("destination"), executor_plan.get("scratch_root"), executor_plan.get("reviewed_text_base64"), executor_plan.get("reviewed_text_byte_length"), executor_plan.get("reviewed_text_digest")) != (EXECUTOR_PLAN_SCHEMA, "copy_reviewed_text", binding.campaign, binding.occurrence, inputs.program, binding.subject, binding.scope, binding.plan_document_digest, "result.txt", inputs.scratch_root, base64.b64encode(inputs.reviewed_text).decode("ascii"), len(inputs.reviewed_text), content_digest(inputs.reviewed_text)):
        raise ReviewedLocalCopyError("executor plan differs from compiler inputs")
    if ag_executor_plan_identity(executor_plan) != binding.work:
        raise ReviewedLocalCopyError("handoff does not carry the exact executor plan")
    store = DraftStore.open_readonly(config.store_locator)
    current = store.current(lock.draft_id)
    if current.revision_id != lock.revision_id or current.revision_id != receipt.revision_id:
        raise ReviewedLocalCopyError("locked revision is not the selected current revision")
    if current.document.canonical_bytes != binding.artifacts["plan_document"] or current.plan_digest != binding.plan_document_digest:
        raise ReviewedLocalCopyError("supplied PlanDocument differs from actual store")
    stored_lock = next((item for item in store.locks(lock.draft_id) if item.lock_id == lock.lock_id), None)
    if stored_lock != lock:
        raise ReviewedLocalCopyError("supplied lock differs from actual store")
    applicable = {
        item.receipt_id
        for item in store.check_receipts(lock.draft_id)
        if item.plan_digest == current.plan_digest
        and item.checker_id == config.checker_id
        and item.checker_version == config.checker_version
        and item.rule_set == config.rule_set
    }
    current_passed = {
        item.receipt_id
        for item in store.check_receipts(lock.draft_id, current.revision_id)
        if item.plan_digest == current.plan_digest
        and item.checker_id == config.checker_id
        and item.checker_version == config.checker_version
        and item.rule_set == config.rule_set
        and item.result == "passed"
    }
    if not set(lock.applicable_check_receipts) <= applicable:
        raise ReviewedLocalCopyError("lock references unavailable applicable checks")
    if not current_passed:
        raise ReviewedLocalCopyError("current revision lacks required passing checks")
    stored = next((item for item in store.compilations(lock.draft_id) if item[0].compilation_id == receipt.compilation_id), None)
    if (receipt.draft_id, receipt.revision_id, receipt.lock_id, receipt.plan_digest, receipt.compiler_id, receipt.compiler_version, receipt.compiler_inputs_schema, receipt.exact_work_identity) != (lock.draft_id, current.revision_id, lock.lock_id, current.plan_digest, config.compiler_id, config.compiler_version, INPUT_SCHEMA, binding.work):
        raise ReviewedLocalCopyError("compilation receipt differs from locked compiler contract")
    if stored is None or stored[0] != receipt or stored[1] != binding.artifacts["compiler_inputs"] or stored[2] != binding.artifacts["compiled_handoff"]:
        raise ReviewedLocalCopyError("supplied compilation differs from actual store")
    result = ReviewedLocalCopyCompilerV1().compile(current.document, inputs)
    if result.handoff_bytes != stored[2] or result.compiler_inputs_digest != receipt.compiler_inputs_digest or result.handoff_digest != receipt.compiled_output_digest or result.node_bindings != receipt.node_bindings or result.compiler_id != receipt.compiler_id or result.compiler_version != receipt.compiler_version or receipt.exact_work_identity != binding.work:
        raise ReviewedLocalCopyError("actual recompilation differs from stored compilation")
    return {
        "binding_id": binding.binding_id,
        "config_digest": config.digest,
        "result": "passed",
        "schema": VALIDATION_SCHEMA,
        "stored_compilation_id": receipt.compilation_id,
        "stored_lock_id": lock.lock_id,
    }


def _cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="maude-reviewed-local-copy")
    commands = parser.add_subparsers(dest="command", required=True)
    compile_command = commands.add_parser("compile", help="compile and bind one locked revision")
    compile_command.add_argument("--store", required=True, type=Path)
    compile_command.add_argument("--draft-id", required=True)
    compile_command.add_argument("--inputs", required=True, type=Path)
    compile_command.add_argument("--output", required=True, type=Path)
    validate_command = commands.add_parser("validate", help="read-only validation of one binding")
    validate_command.add_argument("--config", required=True, type=Path)
    validate_command.add_argument("--binding", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _cli().parse_args(argv)
    try:
        if args.command == "compile":
            inputs = ReviewedLocalCopyInputsV1.from_bytes(args.inputs.read_bytes())
            binding = compile_and_bind_reviewed_local_copy(
                DraftStore(args.store), args.draft_id, inputs
            )
            with args.output.open("xb") as handle:
                handle.write(binding + b"\n")
            print(json.dumps({"binding_id": GovernedPlanBindingV1.from_bytes(binding).binding_id, "result": "compiled"}, sort_keys=True))
        else:
            config = ReviewedLocalCopyValidatorConfigV1.from_bytes(args.config.read_bytes())
            print(json.dumps(validate_reviewed_local_copy_binding(args.binding.read_bytes(), config), sort_keys=True))
    except (OSError, ReviewedLocalCopyError, ValueError) as error:
        print(json.dumps({"result": "refused", "reason": str(error)}, sort_keys=True), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
