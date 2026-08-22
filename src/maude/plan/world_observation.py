# SPDX-License-Identifier: Apache-2.0
"""Exact local-Compose execution evidence -> Nightshift observation candidate.

The adapter is deliberately workflow-specific.  It verifies the closed
executor record, its Docket receipt, the exact compiler output, and the
PlanNode/governed bindings before projecting a small closed claim set.  The
result is authenticated custody of evidence, not Nightshift currentness and
not governed authority.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import hmac
import json
from pathlib import Path
from typing import Any

from maude.custody import _canonical, _read_exact_file, read_protected_key
from maude.plan.compiler import CompilationReceiptV1
from maude.plan.cross_probe import parse_cross_probe

OBSERVATION_SCHEMA_V1 = "maude.local-compose-world-observation/v1"
HANDOFF_SCHEMA_V1 = "nightshift.external_observation_handoff.v1"
AUTH_SCHEMA_V1 = "maude.hmac_sha256.v1"
EXECUTOR_EVIDENCE_SCHEMA_V1 = "maude.local-compose.executor-evidence/v1"
EXECUTOR_PLAN_SCHEMA_V1 = "maude.local-compose.docket-executor-plan/v1"
COMPILATION_SCHEMA_V1 = "maude.plan-compilation-receipt/v1"
WORK_SCHEMA_V1 = "maude.local-compose-workflow/v1"

EVIDENCE_DOMAIN = "maude.local-compose.executor-evidence/v1"
PLAN_DOMAIN = "ag-effectd.docket-executor-plan/v1"
HANDOFF_AUTH_DOMAIN = b"nightshift-external-observation-handoff/v1\0"
MAX_INPUT_BYTES = 16 * 1024 * 1024

NONCLAIMS = (
    "candidate is not Nightshift currentness",
    "Docket settlement is not world-state freshness",
    "producer authentication is not standing or authorization",
    "observation candidate cannot authorize or execute work",
)


class WorldObservationError(ValueError):
    """Fail-closed source validation, projection, or custody refusal."""


def _digest(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        raise WorldObservationError(f"{name} must use sha256:<64 lowercase hex>")
    tail = value[7:]
    if len(tail) != 64 or any(character not in "0123456789abcdef" for character in tail):
        raise WorldObservationError(f"{name} must use sha256:<64 lowercase hex>")
    return value


def _token(name: str, value: object) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise WorldObservationError(f"{name} must be a non-empty token")
    if any(character.isspace() for character in value):
        raise WorldObservationError(f"{name} must be a non-empty token")
    return value


def _closed(value: object, fields: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise WorldObservationError(f"{name} has unknown or missing fields")
    return value


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _hash_domain(domain: str, payload: bytes) -> str:
    encoded = domain.encode("utf-8")
    digest = hashlib.sha256()
    digest.update(b"ag-ng\0digest\0v1\0")
    digest.update(len(encoded).to_bytes(16, "big"))
    digest.update(encoded)
    digest.update(len(payload).to_bytes(16, "big"))
    digest.update(payload)
    return "sha256:" + digest.hexdigest()


def _semantic_id(value: dict[str, Any], field: str) -> str:
    preimage = dict(value)
    preimage.pop(field, None)
    preimage.pop("authentication", None)
    return _sha256(_canonical(preimage))


def _timestamp(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise WorldObservationError(f"{name} must be an RFC3339 UTC timestamp")
    try:
        parsed = dt.datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise WorldObservationError(f"{name} must be an RFC3339 UTC timestamp") from error
    if parsed.utcoffset() != dt.timedelta(0):
        raise WorldObservationError(f"{name} must be an RFC3339 UTC timestamp")
    return value


def _exact_object(path: Path, name: str) -> tuple[dict[str, Any], bytes]:
    raw = _read_exact_file(path, MAX_INPUT_BYTES, name)
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise WorldObservationError(f"malformed {name}") from error
    if not isinstance(value, dict) or _canonical(value) != raw:
        raise WorldObservationError(f"{name} must be exact canonical JSON")
    return value, raw


def _claims(
    action: str,
    outcome: str,
    evidence: dict[str, Any],
    node_bindings: dict[str, str],
) -> list[dict[str, Any]]:
    status = "satisfied" if outcome == "success" else "unknown"
    specifications: list[tuple[str, str, tuple[str, ...]]]
    if action == "qualify":
        required = {
            "pn_health": "front_door_reachable",
            "pn_cache_behavior": "cache_miss_then_hit",
            "pn_continued": "single_cache_failure_survived",
            "pn_restore": "cache_topology_restored",
        }
        missing = sorted(set(required) - set(node_bindings))
        if missing:
            raise WorldObservationError(
                "compilation receipt lacks claim-bearing PlanNode bindings: "
                + ",".join(missing)
            )
        if outcome == "success":
            sequence = evidence.get("cache_sequence")
            failures = evidence.get("failure_requests")
            if (
                evidence.get("health", {}).get("status") != 200
                or not isinstance(sequence, list)
                or [(item.get("cache"), item.get("cache_node")) for item in sequence]
                != [
                    ("MISS", "cache-a"),
                    ("MISS", "cache-b"),
                    ("HIT", "cache-a"),
                    ("HIT", "cache-b"),
                ]
                or not isinstance(failures, list)
                or not failures
                or any(item.get("status") != 200 or item.get("cache_node") != "cache-b" for item in failures)
                or evidence.get("restored_nodes") != ["cache-a", "cache-b"]
            ):
                raise WorldObservationError(
                    "successful executor outcome contradicts local-Compose acceptance evidence"
                )
        specifications = [
            ("front_door_reachable", "pn_health", ("/evidence/health",)),
            (
                "cache_miss_then_hit",
                "pn_cache_behavior",
                ("/evidence/cache_sequence",),
            ),
            (
                "single_cache_failure_survived",
                "pn_continued",
                ("/evidence/failure_requests",),
            ),
            (
                "cache_topology_restored",
                "pn_restore",
                ("/evidence/restored_nodes", "/evidence/restored_health"),
            ),
        ]
    elif action == "teardown":
        if "pn_teardown" not in node_bindings:
            raise WorldObservationError(
                "compilation receipt lacks teardown PlanNode binding"
            )
        if outcome == "success" and (
            evidence.get("campaign_containers_running") != 0
            or evidence.get("campaign_networks_remaining") not in (None, 0)
        ):
            raise WorldObservationError(
                "successful executor outcome contradicts teardown evidence"
            )
        paths = ["/evidence/campaign_containers_running"]
        if "campaign_networks_remaining" in evidence:
            paths.append("/evidence/campaign_networks_remaining")
        specifications = [("campaign_resources_absent", "pn_teardown", tuple(paths))]
    else:
        raise WorldObservationError("unsupported local-Compose observation action")

    claims: list[dict[str, Any]] = []
    for kind, node_id, evidence_paths in specifications:
        claim = {
            "schema": "maude.local-compose-world-claim/v1",
            "claim_id": "",
            "kind": kind,
            "status": status,
            "plan_node_id": node_id,
            "compiled_output_identity": node_bindings[node_id],
            "evidence_paths": list(evidence_paths),
        }
        claim["claim_id"] = _semantic_id(claim, "claim_id")
        claims.append(claim)
    return claims


def build_observation(
    *,
    executor_evidence: dict[str, Any],
    executor_evidence_bytes: bytes,
    executor_plan: dict[str, Any],
    executor_plan_bytes: bytes,
    compilation_receipt: dict[str, Any],
    governed_bindings: dict[str, Any],
) -> dict[str, Any]:
    """Validate owner-linked evidence and build one immutable candidate."""

    if _canonical(executor_evidence) != executor_evidence_bytes:
        raise WorldObservationError("executor evidence must be exact canonical JSON")

    _closed(
        executor_evidence,
        {
            "dispatch",
            "docket_outcome",
            "evidence",
            "evidence_schema",
            "observed_at_unix_ms",
            "outcome",
        },
        "executor evidence",
    )
    if executor_evidence["evidence_schema"] != EXECUTOR_EVIDENCE_SCHEMA_V1:
        raise WorldObservationError("unsupported executor evidence schema")
    dispatch = _closed(
        executor_evidence["dispatch"],
        {"attempt", "marker", "scope", "subject", "work", "work_schema"},
        "executor dispatch",
    )
    docket_outcome = _closed(
        executor_evidence["docket_outcome"],
        {"attempt", "marker", "outcome", "receipt"},
        "Docket outcome",
    )
    evidence = executor_evidence["evidence"]
    if not isinstance(evidence, dict):
        raise WorldObservationError("executor evidence payload must be an object")
    if executor_evidence["outcome"] not in {"success", "failure", "indeterminate"}:
        raise WorldObservationError("unsupported executor outcome")
    if not isinstance(executor_evidence["observed_at_unix_ms"], int):
        raise WorldObservationError("executor observed time must be an integer")
    receipt_preimage = dict(executor_evidence)
    receipt_preimage.pop("docket_outcome")
    receipt = _hash_domain(EVIDENCE_DOMAIN, _canonical(receipt_preimage))
    if (
        docket_outcome["receipt"] != receipt
        or docket_outcome["attempt"] != dispatch["attempt"]
        or docket_outcome["marker"] != dispatch["marker"]
        or docket_outcome["outcome"] != executor_evidence["outcome"]
    ):
        raise WorldObservationError("Docket outcome does not bind exact executor evidence")

    if executor_plan.get("schema") != EXECUTOR_PLAN_SCHEMA_V1:
        raise WorldObservationError("unsupported executor plan schema")
    if _canonical(executor_plan) != executor_plan_bytes:
        raise WorldObservationError("executor plan must be exact canonical JSON")
    exact_work = _hash_domain(PLAN_DOMAIN, executor_plan_bytes)
    if (
        dispatch["work_schema"] != WORK_SCHEMA_V1
        or dispatch["work"] != exact_work
        or dispatch["subject"] != executor_plan.get("subject_digest")
        or dispatch["scope"] != executor_plan.get("scope_digest")
    ):
        raise WorldObservationError("dispatch does not bind exact compiler output")

    try:
        verified_compilation = CompilationReceiptV1.from_data(compilation_receipt)
    except (KeyError, TypeError, ValueError) as error:
        raise WorldObservationError("invalid compilation receipt") from error
    if verified_compilation.schema != COMPILATION_SCHEMA_V1:
        raise WorldObservationError("unsupported compilation receipt schema")
    for field in ("compilation_id", "plan_digest", "exact_work_identity"):
        _digest(f"compilation {field}", compilation_receipt.get(field))
    if (
        compilation_receipt["exact_work_identity"] != exact_work
        or compilation_receipt["plan_digest"]
        != executor_plan.get("plan_document_digest")
    ):
        raise WorldObservationError("compilation receipt does not bind executor plan")
    node_bindings: dict[str, str] = {}
    for binding in compilation_receipt.get("node_bindings", []):
        node_id = _token("compiled PlanNode ID", binding.get("node_id"))
        output_identity = _digest(
            "compiled PlanNode output", binding.get("output_identity")
        )
        if node_id in node_bindings:
            raise WorldObservationError("duplicate compiled PlanNode binding")
        node_bindings[node_id] = output_identity

    try:
        parsed_bindings = parse_cross_probe(governed_bindings)
    except (KeyError, TypeError, ValueError) as error:
        raise WorldObservationError("invalid governed binding projection") from error
    matches = [
        item.to_data()
        for items in parsed_bindings.values()
        for item in items
        if item.compilation_id == compilation_receipt["compilation_id"]
    ]
    if not matches:
        raise WorldObservationError("no governed binding for compilation")
    facts = {
        field: matches[0].get(field)
        for field in (
            "campaign_id",
            "occurrence_id",
            "proposal_id",
            "issuance_id",
            "docket_attempt_id",
            "settlement_id",
            "outcome",
        )
    }
    for item in matches:
        if any(item.get(field) != value for field, value in facts.items()):
            raise WorldObservationError("governed bindings contradict one occurrence result")
        node_id = item.get("node_id")
        if (
            item.get("plan_digest") != compilation_receipt["plan_digest"]
            or item.get("exact_work_identity") != exact_work
            or node_bindings.get(node_id) != item.get("compiled_output_identity")
        ):
            raise WorldObservationError("governed PlanNode binding is substituted")
    if (
        facts["docket_attempt_id"] != dispatch["attempt"]
        or facts["outcome"] != executor_evidence["outcome"]
    ):
        raise WorldObservationError("governed result does not bind executor evidence")

    claims = _claims(
        executor_plan.get("action"),
        executor_evidence["outcome"],
        evidence,
        node_bindings,
    )
    observation = {
        "schema": OBSERVATION_SCHEMA_V1,
        "observation_id": "",
        "adapter_id": "maude.local-compose-observation-adapter",
        "adapter_version": "1",
        "action": executor_plan["action"],
        "plan_document_digest": compilation_receipt["plan_digest"],
        "compilation_id": compilation_receipt["compilation_id"],
        "campaign_id": facts["campaign_id"],
        "occurrence_id": facts["occurrence_id"],
        "proposal_id": facts["proposal_id"],
        "exact_work_id": exact_work,
        "issuance_id": facts["issuance_id"],
        "attempt_id": facts["docket_attempt_id"],
        "settlement_id": facts["settlement_id"],
        "subject_digest": dispatch["subject"],
        "scope_digest": dispatch["scope"],
        "executor_evidence_receipt": receipt,
        "executor_evidence_bytes": len(executor_evidence_bytes),
        "observed_at_unix_ms": executor_evidence["observed_at_unix_ms"],
        "outcome": executor_evidence["outcome"],
        "source_evidence": executor_evidence,
        "claims": claims,
        "nonclaims": list(NONCLAIMS),
    }
    observation["observation_id"] = _semantic_id(observation, "observation_id")
    return observation


def seal_handoff(
    observation: dict[str, Any],
    *,
    producer_principal_id: str,
    producer_key_id: str,
    target_runtime_id: str,
    producer_key: bytes,
    created_at: str,
) -> dict[str, Any]:
    _token("producer principal", producer_principal_id)
    _token("producer key ID", producer_key_id)
    _token("target Nightshift runtime", target_runtime_id)
    _timestamp("handoff created_at", created_at)
    if len(producer_key) != 32:
        raise WorldObservationError("producer credential must contain exactly 32 bytes")
    if observation.get("observation_id") != _semantic_id(observation, "observation_id"):
        raise WorldObservationError("observation identity mismatch")
    handoff = {
        "schema": HANDOFF_SCHEMA_V1,
        "handoff_id": "",
        "producer_principal_id": producer_principal_id,
        "producer_key_id": producer_key_id,
        "target_runtime_id": target_runtime_id,
        "observation": observation,
        "created_at": created_at,
        "authentication": {
            "schema": AUTH_SCHEMA_V1,
            "key_id": producer_key_id,
            "tag": "",
        },
    }
    handoff["handoff_id"] = _semantic_id(handoff, "handoff_id")
    preimage = dict(handoff)
    preimage.pop("authentication")
    tag = hmac.new(
        producer_key,
        HANDOFF_AUTH_DOMAIN + _canonical(preimage),
        hashlib.sha256,
    ).hexdigest()
    handoff["authentication"]["tag"] = "hmac-sha256:" + tag
    return handoff


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seal exact local-Compose result evidence for Nightshift custody"
    )
    parser.add_argument("--executor-evidence", type=Path, required=True)
    parser.add_argument("--executor-plan", type=Path, required=True)
    parser.add_argument("--compilation-receipt", type=Path, required=True)
    parser.add_argument("--governed-bindings", type=Path, required=True)
    parser.add_argument("--producer-key", type=Path, required=True)
    parser.add_argument("--producer-principal-id", required=True)
    parser.add_argument("--producer-key-id", required=True)
    parser.add_argument("--target-runtime-id", required=True)
    parser.add_argument("--created-at", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    evidence, evidence_bytes = _exact_object(args.executor_evidence, "executor evidence")
    plan, plan_bytes = _exact_object(args.executor_plan, "executor plan")
    compilation, _ = _exact_object(args.compilation_receipt, "compilation receipt")
    bindings, _ = _exact_object(args.governed_bindings, "governed bindings")
    observation = build_observation(
        executor_evidence=evidence,
        executor_evidence_bytes=evidence_bytes,
        executor_plan=plan,
        executor_plan_bytes=plan_bytes,
        compilation_receipt=compilation,
        governed_bindings=bindings,
    )
    handoff = seal_handoff(
        observation,
        producer_principal_id=args.producer_principal_id,
        producer_key_id=args.producer_key_id,
        target_runtime_id=args.target_runtime_id,
        producer_key=read_protected_key(args.producer_key),
        created_at=args.created_at,
    )
    args.output.write_bytes(_canonical(handoff))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
