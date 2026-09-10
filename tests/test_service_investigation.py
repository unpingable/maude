# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
import os
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from maude.design.presentation import PresentationStore
from maude.design.server import DesignApplication
from maude.plan.document import PlanDocumentV1, PlanNodeV1, SubmitterV1
from maude.plan.service_investigation import (
    ServiceInvestigationError,
    ServiceInvestigationLedger,
    ServiceInvestigationProfileV1,
    compile_service_investigation,
)
from maude.plan.store import DraftStore, EditOrigin


def digest(character: str) -> str:
    return "sha256:" + character * 64


def profile() -> ServiceInvestigationProfileV1:
    return ServiceInvestigationProfileV1.from_data(
        {
            "schema": "maude.service-investigation-profile/v1",
            "profile_id": "service-posture",
            "audience": "nightshift.service-investigation/v1",
            "subject_label": "sushi-k / fixed HTTP service",
            "subject": digest("a"),
            "diagnostics": [
                {
                    "node_id": "pn_systemd",
                    "profile": "nq.systemd_unit/v1",
                    "scope": digest("b"),
                    "config_digest": digest("c"),
                    "profile_digest": digest("1"),
                    "question_digest": digest("2"),
                    "threshold_policy_digest": digest("3"),
                    "instance": "fixture-systemd",
                    "vantage": "target",
                    "vantage_digest": digest("4"),
                },
                {
                    "node_id": "pn_http",
                    "profile": "nq.http_endpoint/v1",
                    "scope": digest("d"),
                    "config_digest": digest("e"),
                    "profile_digest": digest("5"),
                    "question_digest": digest("6"),
                    "threshold_policy_digest": digest("7"),
                    "instance": "fixture-http",
                    "vantage": "controller",
                    "vantage_digest": digest("8"),
                },
            ],
        }
    )


def document() -> PlanDocumentV1:
    return PlanDocumentV1(
        goal="Investigate the fixed HTTP service",
        workspace="/srv/fixture",
        submitter=SubmitterV1("human", "human_written", "reviewer"),
        nodes=(
            PlanNodeV1("pn_systemd", "Inspect target-local systemd state"),
            PlanNodeV1(
                "pn_http",
                "Inspect controller HTTP reachability",
                depends_on=("pn_systemd",),
            ),
        ),
    )


def owner_program(tmp_path: Path) -> tuple[str, ...]:
    script = tmp_path / "nightshift-submit.py"
    script.write_text(
        """#!/usr/bin/env python3
import argparse, json, pathlib
p=argparse.ArgumentParser(); p.add_argument('--counter'); p.add_argument('--receipt'); p.add_argument('--handoff'); a=p.parse_args()
h=json.loads(pathlib.Path(a.handoff).read_bytes())
c=pathlib.Path(a.counter); c.write_text(c.read_text()+'x' if c.exists() else 'x')
r={'schema':'nightshift.service-investigation-submission/v1','investigation_id':h['investigation_id'],'handoff_digest':h['handoff_digest'],'plan_digest':h['plan_digest'],'revision_id':h['revision_id'],'run_id':'run_fixture','state':'accepted','inspector_path':'/phosphor-ng/investigations/'+h['investigation_id'],'receipt_path':a.receipt}
print(json.dumps(r,sort_keys=True,separators=(',',':')))
""",
        encoding="utf-8",
    )
    os.chmod(script, 0o700)
    return (
        sys.executable,
        str(script),
        "--counter",
        str(tmp_path / "count"),
        "--receipt",
        str(tmp_path / "owner-receipt.json"),
    )


def test_closed_profile_and_exact_revision_compilation(tmp_path: Path) -> None:
    store = DraftStore(tmp_path / "plans.sqlite")
    revision = store.create(document(), draft_id="draft_service")
    compiled = compile_service_investigation(revision, profile())
    assert compiled.plan_digest == revision.plan_digest
    assert compiled.handoff_digest.startswith("sha256:")
    assert [item.profile for item in compiled.profile.diagnostics] == [
        "nq.systemd_unit/v1",
        "nq.http_endpoint/v1",
    ]
    changed = store.save_successor(
        revision.draft_id,
        revision.revision_id,
        replace(revision.document, goal="Changed plan"),
        edit_origin=EditOrigin.HUMAN,
    )
    assert (
        compile_service_investigation(changed, profile()).investigation_id
        != compiled.investigation_id
    )


def test_missing_node_and_mutating_diagnostic_refuse(tmp_path: Path) -> None:
    store = DraftStore(tmp_path / "plans.sqlite")
    revision = store.create(
        replace(document(), nodes=(document().nodes[0],)), draft_id="draft_service"
    )
    with pytest.raises(ServiceInvestigationError, match="absent PlanNode"):
        compile_service_investigation(revision, profile())
    raw = profile().to_data()
    raw["diagnostics"].reverse()
    with pytest.raises(ServiceInvestigationError, match="systemd then HTTP"):
        ServiceInvestigationProfileV1.from_data(raw)


def test_handoff_is_single_dispatch_and_replay_is_read_only(tmp_path: Path) -> None:
    store = DraftStore(tmp_path / "plans.sqlite")
    revision = store.create(document(), draft_id="draft_service")
    compiled = compile_service_investigation(revision, profile())
    ledger = ServiceInvestigationLedger(tmp_path / "investigations.sqlite")
    command = owner_program(tmp_path)
    first = ledger.submit(compiled, command)
    second = ledger.submit(compiled, command)
    assert first == second
    assert (tmp_path / "count").read_text() == "x"
    assert ledger.projection(compiled.investigation_id)["state"] == "accepted"


def test_indeterminate_handoff_reconciles_original_owner_occurrence(
    tmp_path: Path,
) -> None:
    store = DraftStore(tmp_path / "plans.sqlite")
    compiled = compile_service_investigation(
        store.create(document(), draft_id="draft_service"), profile()
    )
    ledger = ServiceInvestigationLedger(tmp_path / "investigations.sqlite")
    script = tmp_path / "reconcile-owner.py"
    script.write_text(
        """#!/usr/bin/env python3
import argparse,json,pathlib,sys
p=argparse.ArgumentParser();p.add_argument('--marker');p.add_argument('--handoff');a=p.parse_args();m=pathlib.Path(a.marker);h=json.loads(pathlib.Path(a.handoff).read_bytes())
if not m.exists(): m.write_text('original occurrence exists');sys.exit(1)
r={'schema':'nightshift.service-investigation-submission/v1','investigation_id':h['investigation_id'],'handoff_digest':h['handoff_digest'],'plan_digest':h['plan_digest'],'revision_id':h['revision_id'],'run_id':'original_run','state':'accepted','inspector_path':'/phosphor-ng/investigations/'+h['investigation_id'],'receipt_path':str(m.resolve())}
print(json.dumps(r,sort_keys=True,separators=(',',':')))
"""
    )
    os.chmod(script, 0o700)
    command = (sys.executable, str(script), "--marker", str(tmp_path / "marker"))
    with pytest.raises(ServiceInvestigationError, match="refused"):
        ledger.submit(compiled, command)
    assert ledger.projection(compiled.investigation_id)["state"] == "indeterminate"
    receipt = ledger.reconcile(compiled, command)
    assert receipt.run_id == "original_run"
    assert ledger.projection(compiled.investigation_id)["state"] == "accepted"


def test_browser_review_submit_and_stale_revision_refusal(tmp_path: Path) -> None:
    store = DraftStore(tmp_path / "plans.sqlite")
    revision = store.create(document(), draft_id="draft_service")
    ledger = ServiceInvestigationLedger(tmp_path / "investigations.sqlite")
    app = DesignApplication(
        store,
        PresentationStore(tmp_path / "presentations.sqlite"),
        service_investigation_profile=profile(),
        service_investigation_ledger=ledger,
        nightshift_submission_command=owner_program(tmp_path),
        secret=b"i" * 32,
    )
    reviewed = app.get("/phosphor/design/drafts/draft_service/investigation")
    assert reviewed.status == 200
    assert b"Permission to run these checks" in reviewed.body
    assert b"Run supported diagnostic" in reviewed.body
    assert b"nq.systemd_unit/v1" in reviewed.body
    submitted = app.post(
        "/phosphor/design/drafts/draft_service/investigation/submit",
        {
            "csrf": [app.csrf_token],
            "expected_revision_id": [revision.revision_id],
            "expected_plan_digest": [revision.plan_digest],
        },
    )
    assert submitted.status == 303
    api = json.loads(
        app.get("/phosphor/design/drafts/draft_service/investigation/api/v1").body
    )
    assert api["projection"]["state"] == "accepted"
    stale = store.save_successor(
        revision.draft_id,
        revision.revision_id,
        replace(revision.document, goal="New goal"),
        edit_origin=EditOrigin.HUMAN,
    )
    refused = app.post(
        "/phosphor/design/drafts/draft_service/investigation/submit",
        {
            "csrf": [app.csrf_token],
            "expected_revision_id": [revision.revision_id],
            "expected_plan_digest": [revision.plan_digest],
        },
    )
    assert refused.status == 409
    assert stale.revision_id != revision.revision_id
    assert (tmp_path / "count").read_text() == "x"


def test_service_entry_and_preparation_lead_with_operator_task(tmp_path: Path) -> None:
    store = DraftStore(tmp_path / "plans.sqlite")
    store.create(document(), draft_id="draft_service")
    app = DesignApplication(
        store,
        PresentationStore(tmp_path / "presentations.sqlite"),
        service_investigation_profile=profile(),
        service_investigation_ledger=ServiceInvestigationLedger(
            tmp_path / "investigations.sqlite"
        ),
        service_authority_view={
            node_id: {
                "operator": f"operator for {node_id}",
                "workload": f"workload for {node_id}",
                "scope": digest("b" if node_id == "pn_systemd" else "d"),
                "valid_until": "2026-09-10T20:00:00Z",
            }
            for node_id in ("pn_systemd", "pn_http")
        },
        nightshift_submission_command=owner_program(tmp_path),
        secret=b"i" * 32,
    )

    entry = app.get("/phosphor/design").body.decode()
    assert "Investigate a service" in entry
    assert "sushi-k / fixed HTTP service" in entry
    assert "Prepare diagnostic" in entry
    assert "Reported symptom: not supplied by retained owner records" in entry
    assert "Advanced plan editing" in entry
    assert "<h1>PlanDocuments</h1>" not in entry

    preparation = app.get(
        "/phosphor/design/drafts/draft_service/investigation"
    ).body.decode()
    assert "Service-manager observation" in preparation
    assert "HTTP observation" in preparation
    assert "operator for pn_systemd" in preparation
    assert "Each observation has its own single-use grant" in preparation
    assert "does not produce a service-health verdict" in preparation
