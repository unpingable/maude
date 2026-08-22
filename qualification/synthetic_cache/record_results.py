#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Join exact owner projections and record synthetic governed cross-probes.

This qualification helper never reads AG, Nightshift, or Docket databases.  It
invokes their existing read-only commands and joins only identities which all
owner projections establish exactly.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any

from maude.plan.cross_probe import (
    GOVERNED_CROSS_PROBE_SCHEMA,
    GovernedNodeBindingV1,
)
from maude.plan.document import canonical_json_bytes
from maude.plan.store import (
    DraftStore,
    EditOrigin,
    ExternalArtifactReferenceV1,
)

DRAFT_ID = "draft_synthetic_cache_platform"
DRIFT_CRITERION = "A future successor must declare any cache-TTL change explicitly before a new handoff"
MAX_OWNER_OUTPUT = 16 * 1024 * 1024


def exact_json(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    if len(raw) > MAX_OWNER_OUTPUT:
        raise ValueError(f"oversized exact artifact: {path}")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"exact artifact must be an object: {path}")
    return value


def owner_json(program: Path, arguments: list[str]) -> dict[str, Any]:
    if not program.is_absolute() or not program.is_file():
        raise ValueError(f"owner program is not an exact absolute file: {program}")
    completed = subprocess.run(
        [str(program), *arguments],
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
    )
    if len(completed.stdout) > MAX_OWNER_OUTPUT:
        raise ValueError(f"owner output exceeded {MAX_OWNER_OUTPUT} bytes")
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise ValueError("owner output must be a JSON object")
    return value


def walk(value: object):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def issuances_by_occurrence(history: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if history.get("schema") != "ag.governed-loop.transition-history/v1":
        raise ValueError("unsupported AG history schema")
    result: dict[str, dict[str, Any]] = {}
    for value in walk(history):
        if value.get("schema") != "ag.governed-loop.issuance/v1":
            continue
        occurrence = value.get("key", {}).get("occurrence")
        existing = result.get(occurrence)
        if existing is not None and existing != value:
            raise ValueError("AG history contradicts an occurrence issuance")
        result[occurrence] = value
    return result


def write_exact(path: Path, value: Any) -> None:
    path.write_bytes(canonical_json_bytes(value))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan-root", type=Path, required=True)
    parser.add_argument("--governed-summary", type=Path, required=True)
    parser.add_argument("--ag-loopctl", type=Path, required=True)
    parser.add_argument("--ag-database", type=Path, required=True)
    parser.add_argument("--nightshift", type=Path, required=True)
    parser.add_argument("--nightshift-store", type=Path, required=True)
    parser.add_argument("--docket", type=Path, required=True)
    parser.add_argument("--docket-state", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.plan_root.resolve()
    summary = exact_json(args.governed_summary.resolve())
    if summary.get("schema") != "nightshift.synthetic-cache-governed-qualification/v1":
        raise ValueError("unsupported governed qualification summary")

    plan_summary = exact_json(root / "plan-qualification.json")
    store = DraftStore(root / "plan-store.sqlite")
    locked = store.revision(plan_summary["final_revision_id"])
    if locked.plan_digest != plan_summary["locked_plan_digest"]:
        raise ValueError("locked PlanDocument digest is contradictory")

    history = owner_json(
        args.ag_loopctl.resolve(),
        ["history", "--database", str(args.ag_database.resolve())],
    )
    issuances = issuances_by_occurrence(history)
    bindings: list[GovernedNodeBindingV1] = []
    owner_records: list[tuple[dict[str, Any], dict[str, Any]]] = []

    for action in ("qualify", "teardown"):
        compilation = plan_summary["compilations"][action]["compilation_receipt"]
        occurrence = plan_summary["compilations"][action]["occurrence_id"]
        campaign = summary["authoring_lineage"][0]["campaign_id"]
        lineage_export = owner_json(
            args.nightshift.resolve(),
            [
                "--store",
                str(args.nightshift_store.resolve()),
                "cycle",
                "export-authoring-context",
                "--campaign-id",
                campaign,
                "--occurrence-id",
                occurrence,
            ],
        )
        custody_export = owner_json(
            args.nightshift.resolve(),
            [
                "--store",
                str(args.nightshift_store.resolve()),
                "cycle",
                "export-authoring-custody",
                "--campaign-id",
                campaign,
                "--occurrence-id",
                occurrence,
            ],
        )
        if (
            len(lineage_export.get("matches", [])) != 1
            or len(custody_export.get("matches", [])) != 1
        ):
            raise ValueError(
                "exact owner lookup did not return one lineage/custody record"
            )
        lineage = lineage_export["matches"][0]
        custody = custody_export["matches"][0]
        issuance = issuances.get(occurrence)
        if issuance is None:
            raise ValueError("AG history has no exact issuance for occurrence")
        docket = owner_json(
            args.docket.resolve(),
            [
                "governed-loop",
                "inspect",
                "--state",
                str(args.docket_state.resolve()),
                "--issuance",
                issuance["issuance"],
            ],
        )
        record = docket.get("record")
        if not isinstance(record, dict) or record.get("status") != "settled":
            raise ValueError("Docket owner projection is not settled")
        settlement = record.get("settlement")
        if not isinstance(settlement, dict):
            raise ValueError("Docket settlement is absent")
        exact_work = compilation["exact_work_identity"]
        facts = {
            "campaign": campaign,
            "occurrence": occurrence,
            "plan_digest": compilation["plan_digest"],
            "proposal": lineage["proposal_id"],
            "work": exact_work,
        }
        if not (
            facts["plan_digest"]
            == lineage["maude_plan_ref"]
            == custody["maude_plan_ref"]
            == locked.plan_digest
            and exact_work
            == lineage["exact_work_id"]
            == custody["exact_work_id"]
            == issuance["work"]
            == record["issuance"]["work"]
            and facts["proposal"] == custody["proposal_id"] == issuance["proposal"]
            and occurrence
            == lineage["occurrence_id"]
            == custody["occurrence_id"]
            == issuance["key"]["occurrence"]
            == record["issuance"]["key"]["occurrence"]
        ):
            raise ValueError(
                "owner projections do not establish one exact relationship"
            )
        path = (
            "/phosphor-ng/campaigns/"
            + campaign.replace(":", "%3A")
            + "/occurrences/"
            + occurrence
            + "/proposals/"
            + lineage["proposal_id"].replace(":", "%3A")
        )
        for node in compilation["node_bindings"]:
            bindings.append(
                GovernedNodeBindingV1.create(
                    draft_id=DRAFT_ID,
                    node_id=node["node_id"],
                    plan_digest=locked.plan_digest,
                    compilation_id=compilation["compilation_id"],
                    compiled_output_identity=node["output_identity"],
                    exact_work_identity=exact_work,
                    authoring_provenance_id=lineage["provenance_id"],
                    handoff_id=custody["handoff_id"],
                    campaign_id=campaign,
                    occurrence_id=occurrence,
                    proposal_id=lineage["proposal_id"],
                    issuance_id=issuance["issuance"],
                    docket_attempt_id=record["custody"]["attempt"],
                    settlement_id=settlement["settlement"],
                    outcome=settlement["outcome"],
                    inspector_path=path,
                )
            )
        owner_records.append((lineage, custody))

    current = store.current(DRAFT_ID)
    if current.plan_digest == locked.plan_digest:
        successor_document = replace(
            current.document,
            acceptance_criteria=current.document.acceptance_criteria
            + (DRIFT_CRITERION,),
        )
        current = store.save_successor(
            DRAFT_ID,
            current.revision_id,
            successor_document,
            edit_origin=EditOrigin.HUMAN,
        )
    elif DRIFT_CRITERION not in current.document.acceptance_criteria:
        raise ValueError("working draft advanced in an unexpected way")

    qualify_lineage, qualify_custody = owner_records[0]
    references = (
        ExternalArtifactReferenceV1(
            "handoff",
            qualify_custody["handoff_id"],
            locked.plan_digest,
            "nightshift.authoring_context_custody",
        ),
        ExternalArtifactReferenceV1(
            "governed",
            qualify_lineage["provenance_id"],
            locked.plan_digest,
            "nightshift.authoring_context_provenance",
        ),
    )
    projection = store.projection(DRAFT_ID, external_references=references)
    projected = projection.to_data()
    if not (
        projected["working_differs_from_locked"]
        and projected["working_differs_from_handoff"]
        and projected["working_differs_from_governed"]
    ):
        raise ValueError("successor draft did not expose exact artifact drift")

    write_exact(
        root / "governed-cross-probe.json",
        {
            "bindings": [item.to_data() for item in bindings],
            "schema": GOVERNED_CROSS_PROBE_SCHEMA,
        },
    )
    write_exact(
        root / "owner-facts.json",
        {
            "drafts": {
                DRAFT_ID: [item.to_data() for item in references],
            },
            "schema": "maude.plan-design-owner-facts/v1",
        },
    )
    write_exact(root / "plan-working-successor.json", current.document.to_data())
    write_exact(root / "drift-projection.json", projected)
    write_exact(root / "ag-history.json", history)
    result = {
        "binding_count": len(bindings),
        "current_plan_digest": current.plan_digest,
        "current_revision_id": current.revision_id,
        "governed_plan_digest": locked.plan_digest,
        "qualify_occurrence": bindings[0].occurrence_id,
        "schema": "maude.synthetic-cache-result-projection/v1",
        "teardown_occurrence": bindings[-1].occurrence_id,
        "working_differs_from_governed": True,
    }
    write_exact(root / "result-projection.json", result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
