#!/usr/bin/env python3
"""Prepare the fixed post-settlement external-evidence successor recipe.

This command reads retained owner projections and writes only derived JSON. It
does not invoke an adapter, mutate Nightshift/AG/Docket, or execute Docker.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

MAX_INPUT = 16 * 1024 * 1024
HORIZON_MS = 120_000
MIN_START_MARGIN_MS = 90_000


def read_object(path: Path) -> dict[str, Any]:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise ValueError("input must be a regular non-symlink file")
        raw = source.read(MAX_INPUT + 1)
    if len(raw) > MAX_INPUT:
        raise ValueError(f"input exceeds {MAX_INPUT} bytes: {path}")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"input is not an object: {path}")
    return value


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical(value)).hexdigest()


def write(path: Path, value: Any) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(canonical(value))
        output.flush()
        os.fsync(output.fileno())


def one_match(value: dict[str, Any], schema: str) -> dict[str, Any]:
    matches = value.get("matches")
    if (isinstance(matches, list) and len(matches) == 1
            and isinstance(matches[0], dict) and matches[0].get("schema") == schema):
        return matches[0]
    found: list[dict[str, Any]] = []
    def walk(item: Any) -> None:
        if isinstance(item, dict):
            if item.get("schema") == schema:
                found.append(item)
            for child in item.values():
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)
    walk(value)
    unique = {canonical(item): item for item in found}
    if len(unique) != 1:
        raise ValueError(f"owner input must contain one distinct {schema}")
    return next(iter(unique.values()))


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    for name in ("docket-inspection", "executor-evidence", "executor-plan",
                 "compilation-receipt", "lineage-export", "custody-export"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target-runtime-id", required=True)
    parser.add_argument("--producer-principal-id", required=True)
    parser.add_argument("--producer-key-id", required=True)
    parser.add_argument("--maude-producer-principal-id", required=True)
    parser.add_argument("--maude-producer-key-id", required=True)
    parser.add_argument("--maude-session-issuer-principal-id", required=True)
    parser.add_argument("--maude-session-issuer-key-id", required=True)
    parser.add_argument("--evaluated-at-unix-ms", type=int, default=None)
    return parser.parse_args()


def main() -> int:
    args = arguments()
    docket = read_object(args.docket_inspection)
    evidence = read_object(args.executor_evidence)
    plan = read_object(args.executor_plan)
    compilation = read_object(args.compilation_receipt)
    lineage = one_match(read_object(args.lineage_export), "nightshift.authoring_context_provenance.v1")
    custody = one_match(read_object(args.custody_export), "nightshift.authoring_context_custody_provenance.v1")
    if docket.get("schema") != "docket.governed-loop.inspection/v1":
        raise ValueError("unsupported Docket inspection")
    record = docket.get("record")
    if not isinstance(record, dict) or record.get("status") != "settled":
        raise ValueError("Docket record is not settled")
    issuance, docket_custody, settlement = (record.get(k) for k in ("issuance", "custody", "settlement"))
    if not all(isinstance(v, dict) for v in (issuance, docket_custody, settlement)):
        raise ValueError("settled owner projection is incomplete")
    if settlement.get("outcome") != "success" or evidence.get("outcome") != "success":
        raise ValueError("strong successor profile requires successful execution")
    facts = {
        "campaign_id": issuance["key"]["campaign"],
        "occurrence_id": issuance["key"]["occurrence"],
        "proposal_id": issuance["proposal"],
        "exact_work_identity": issuance["work"],
        "issuance_id": issuance["issuance"],
        "docket_attempt_id": docket_custody["attempt"],
        "settlement_id": settlement["settlement"],
    }
    checks = (
        docket["requested_issuance"] == facts["issuance_id"],
        settlement["attempt"] == facts["docket_attempt_id"] == evidence["dispatch"]["attempt"],
        settlement["settlement"] == facts["settlement_id"],
        compilation.get("exact_work_identity") == facts["exact_work_identity"] == evidence.get("dispatch", {}).get("work"),
        compilation.get("plan_digest") == plan.get("plan_document_digest") == lineage.get("maude_plan_ref"),
        lineage.get("proposal_id") == custody.get("proposal_id") == facts["proposal_id"],
        lineage.get("occurrence_id") == custody.get("occurrence_id") == facts["occurrence_id"],
        lineage.get("exact_work_id") == custody.get("exact_work_id") == facts["exact_work_identity"],
    )
    if not all(checks):
        raise ValueError("owner/compiler/evidence identities do not form one exact qualification")
    observed = evidence.get("observed_at_unix_ms")
    if not isinstance(observed, int):
        raise ValueError("executor evidence lacks original observation time")
    evaluated = args.evaluated_at_unix_ms if args.evaluated_at_unix_ms is not None else time.time_ns() // 1_000_000
    horizon = observed + HORIZON_MS
    profile_unsigned = {
        "schema": "nightshift.external_evidence_profile.v1",
        "purpose": "post_settlement_successor",
        "expected_adapter_id": "maude.local-compose-observation-adapter",
        "expected_adapter_version": "1",
        "expected_producer_principal_id": args.producer_principal_id,
        "expected_producer_key_id": args.producer_key_id,
        "expected_runtime_id": args.target_runtime_id,
        "required_action": "qualify",
        "required_claims": ["front_door_reachable", "cache_miss_then_hit", "single_cache_failure_survived", "cache_topology_restored"],
        "max_age_ms": HORIZON_MS,
    }
    profile = {**profile_unsigned, "profile_id": digest(profile_unsigned)}
    inspector = "/phosphor-ng/campaigns/{}/occurrences/{}/proposals/{}".format(
        quote(facts["campaign_id"], safe=""), facts["occurrence_id"], quote(facts["proposal_id"], safe="")
    )
    bindings = []
    for node in compilation.get("node_bindings", []):
        unsigned = {
            "schema": "maude.plan-node-governed-binding/v1",
            "draft_id": compilation["draft_id"], "node_id": node["node_id"],
            "plan_digest": compilation["plan_digest"], "compilation_id": compilation["compilation_id"],
            "compiled_output_identity": node["output_identity"], **facts,
            "authoring_provenance_id": lineage["provenance_id"], "handoff_id": custody["handoff_id"],
            "outcome": settlement["outcome"], "inspector_path": inspector,
        }
        bindings.append({**unsigned, "binding_id": digest(unsigned)})
    output = args.output
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    write(output / "external-evidence-profile.json", profile)
    write(output / "qualify-governed-cross-probe.json", {"schema":"maude.plan-governed-cross-probe/v1","bindings":bindings})
    recipe = {
        "schema": "constellation.cache-external-successor-recipe.v1",
        "launch_admissible": evaluated <= horizon - MIN_START_MARGIN_MS,
        "original_observed_at_unix_ms": observed,
        "exclusive_horizon_unix_ms": horizon,
        "evaluated_at_unix_ms": evaluated,
        "minimum_start_margin_ms": MIN_START_MARGIN_MS,
        "source": facts,
        "profile_id": profile["profile_id"],
        "required_order": [
            "same_owner_nq_local_successor_and_pulse", "governed_qualification_settlement",
            "maude_orchestrate_post_settlement", "nightshift_prepare_distinct_successor",
            "nightshift_run_distinct_successor", "ag_decide_and_one_use_authorize",
            "docket_governed_teardown", "verify_exact_project_absent"
        ],
        "acquisition_argv_suffix": [
            "orchestrate-post-settlement", "--ledger", "@ACQUISITION_LEDGER",
            "--docket-program", "@DOCKET", "--docket-state", "@DOCKET_STATE",
            "--issuance", facts["issuance_id"], "--executor-evidence", str(args.executor_evidence.resolve()),
            "--executor-plan", str(args.executor_plan.resolve()), "--compilation-receipt", str(args.compilation_receipt.resolve()),
            "--governed-bindings", str((output / "qualify-governed-cross-probe.json").resolve()),
            "--external-profile", str((output / "external-evidence-profile.json").resolve()),
            "--target-runtime-id", args.target_runtime_id, "--producer-key", "@OBSERVER_KEY",
            "--producer-principal-id", args.producer_principal_id, "--producer-key-id", args.producer_key_id,
            "--nightshift-program", "@NIGHTSHIFT", "--nightshift-store", "@NIGHTSHIFT_STORE",
            "--nightshift-credential", "@OBSERVER_KEY", "--nightshift-runtime-id", args.target_runtime_id
        ],
        "successor_commands": [
            ["@NIGHTSHIFT", "--store", "@NIGHTSHIFT_STORE", "external-observation", "prepare-cycle", "--request", "@SEALED_DISTINCT_SUCCESSOR_BASE", "--profile", str((output / "external-evidence-profile.json").resolve())],
            ["@NIGHTSHIFT", "--store", "@NIGHTSHIFT_STORE", "cycle", "run",
             "--request", "@PREPARED_EXTERNAL_SUCCESSOR",
             "--present-evidence-resolver", "@PULSE_SUPPORT_RESOLVER",
             "--nq-program", "@NQ", "--nq-config", "@ADMITTED_NQ_CONFIG",
             "--nq-source-id", "@FRESH_SUCCESSOR_NQ_SOURCE_ID",
             "--ag-loopctl", "@AG_LOOPCTL", "--ag-database", "@AG_DATABASE",
             "--ag-observation-resolver", "@AG_OBSERVATION_RESOLVER",
             "--ag-observation-resolver-id", "nightshift-observation-resolver/v1",
             "--ag-runtime-profile", "@AG_RUNTIME_PROFILE",
             "--maude-authoring-handoff", "@SUCCESSOR_MAUDE_AUTHORING_HANDOFF",
             "--maude-custody-credential", "@MAUDE_PRODUCER_KEY",
             "--maude-producer-principal-id", args.maude_producer_principal_id,
             "--maude-producer-key-id", args.maude_producer_key_id,
             "--maude-session-custody-credential", "@MAUDE_SESSION_KEY",
             "--maude-session-issuer-principal-id", args.maude_session_issuer_principal_id,
             "--maude-session-issuer-key-id", args.maude_session_issuer_key_id,
             "--nightshift-runtime-id", args.target_runtime_id,
             "--external-evidence-profile", str((output / "external-evidence-profile.json").resolve())]
        ],
        "recovery": {
            "before_durable_handoff": "indeterminate adapter invocation; reconcile ledger and custody before --recover-incomplete",
            "after_durable_handoff": "resend exact stored handoff; do not rerun adapter or refresh observed_at",
            "after_docket_dispatch": "inspect exact attempt and settlement; never redispatch an uncertain attempt",
            "supervisor_loss": "durable unit continues; a new supervisor reads checkpoint, ledger, AG and Docket owner projections"
        }
    }
    write(output / "recipe.json", recipe)
    print(json.dumps({"output":str(output),"launch_admissible":recipe["launch_admissible"],"profile_id":profile["profile_id"],"binding_count":len(bindings),"remaining_ms":horizon-evaluated}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
