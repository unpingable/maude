# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import http.client
import json
import re
import sqlite3
import threading
from dataclasses import replace
from urllib.parse import quote, urlencode

import pytest

from maude.design.demo import generate_demo
from maude.design.presentation import (
    PLAN_PRESENTATION_V1_SCHEMA,
    PlanPresentationV2,
    PresentationConflict,
    PresentationError,
    PresentationStore,
    project_presentation,
)
from maude.design.server import (
    DesignApplication,
    DesignServer,
    load_governed_cross_probe,
    serve,
)
from maude.plan.cross_probe import (
    GOVERNED_CROSS_PROBE_SCHEMA,
    GovernedNodeBindingV1,
)
from maude.plan.document import (
    PlanDocumentV1,
    PlanNodeV1,
    SubmitterV1,
    canonical_json_bytes,
    content_digest,
)
from maude.plan.operations import (
    AddNodeV1,
    PlanOperationError,
    PlanOperationV1,
    ReorderNodeV1,
    UpdateNodeV1,
    apply_plan_operation,
)
from maude.plan.proposal_store import ProposalStore
from maude.plan.store import DraftStore, EditOrigin


def digest(character: str) -> str:
    return "sha256:" + character * 64


def governed_binding(
    draft_id: str = "draft_test", *, plan_digest: str | None = None
) -> GovernedNodeBindingV1:
    return GovernedNodeBindingV1.create(
        draft_id=draft_id,
        node_id="pn_a",
        plan_digest=plan_digest or digest("1"),
        compilation_id=digest("2"),
        compiled_output_identity=digest("3"),
        exact_work_identity=digest("4"),
        authoring_provenance_id=digest("5"),
        handoff_id=digest("6"),
        campaign_id=digest("a"),
        occurrence_id="00000000-0000-4000-8000-000000000000",
        proposal_id=digest("7"),
        issuance_id=digest("8"),
        docket_attempt_id=digest("9"),
        settlement_id=digest("b"),
        outcome="success",
        inspector_path=(
            "/phosphor-ng/campaigns/"
            + digest("a").replace(":", "%3A")
            + "/occurrences/00000000-0000-4000-8000-000000000000/proposals/"
            + digest("7").replace(":", "%3A")
        ),
    )


def plan(*nodes: PlanNodeV1) -> PlanDocumentV1:
    return PlanDocumentV1(
        goal="Qualify the board file",
        workspace="/srv/test",
        submitter=SubmitterV1("human", "human_written", "tester"),
        nodes=nodes
        or (
            PlanNodeV1("pn_a", "Inspect"),
            PlanNodeV1("pn_b", "Change", depends_on=("pn_a",)),
        ),
    )


def app(tmp_path):
    store = DraftStore(tmp_path / "plans.sqlite")
    revision = store.create(plan(), draft_id="draft_test")
    application = DesignApplication(
        store, PresentationStore(tmp_path / "presentations.sqlite"), secret=b"s" * 32
    )
    return application, store, revision


def form(application: DesignApplication, **values: str | list[str]):
    result: dict[str, list[str]] = {"csrf": [application.csrf_token]}
    for key, value in values.items():
        result[key] = value if isinstance(value, list) else [value]
    return result


def preview_token(body: bytes) -> str:
    match = re.search(rb'name="preview_token" value="([^"]+)"', body)
    assert match
    return match.group(1).decode()


def set_casework(
    application: DesignApplication,
    revision,
    tab: str,
    *,
    selected_node_id: str | None = None,
    selected_object_kind: str | None = None,
    selected_object_id: str | None = None,
    return_anchor: str | None = None,
):
    state = application._presentation(revision).presentation
    node_id = state.selected_node_id if selected_node_id is None else selected_node_id
    kind = (
        state.selected_object_kind
        if selected_object_kind is None
        else selected_object_kind
    )
    object_id = (
        state.selected_object_id if selected_object_id is None else selected_object_id
    )
    values = form(
        application,
        expected_version=str(state.version),
        semantic_revision_id=revision.revision_id,
        selected_node_id=node_id or "",
        collapsed_node_ids="\n".join(state.collapsed_node_ids),
        outline_percent=str(state.outline_percent),
        active_detail_tab=state.active_detail_tab,
        active_casework_tab=tab,
        selected_object_kind=kind,
        selected_object_id=object_id or "",
    )
    if return_anchor is not None:
        values["return_anchor"] = [return_anchor]
    return application.post(
        f"/phosphor/design/drafts/{revision.draft_id}/presentation",
        values,
    )


def test_closed_typed_operation_round_trip_and_reorder_identity():
    before = plan()
    operation = PlanOperationV1(ReorderNodeV1("pn_b", 0))
    parsed = PlanOperationV1.from_data(operation.to_data())
    preview = apply_plan_operation(before, parsed)
    assert tuple(node.node_id for node in preview.document.nodes) == ("pn_b", "pn_a")
    assert preview.diff.reordered is True
    assert preview.diff.added == preview.diff.removed == ()
    with pytest.raises(PlanOperationError, match="unknown field"):
        PlanOperationV1.from_data({**operation.to_data(), "browser_patch": {}})


def test_typed_dependencies_use_exact_existing_node_ids():
    before = plan()
    bad = replace(before.nodes[1], depends_on=("pn_absent",))
    with pytest.raises(PlanOperationError, match="unknown PlanNode"):
        apply_plan_operation(before, PlanOperationV1(UpdateNodeV1(bad)))
    added = PlanNodeV1("pn_c", "Verify", depends_on=("pn_b",))
    after = apply_plan_operation(before, PlanOperationV1(AddNodeV1(added, 2))).document
    assert after.nodes[-1].depends_on == ("pn_b",)


def test_browser_preview_and_exact_apply_create_successor(tmp_path):
    application, store, revision = app(tmp_path)
    preview = application.post(
        "/phosphor/design/drafts/draft_test/preview",
        form(
            application,
            expected_revision_id=revision.revision_id,
            operation_type="reorder_node",
            node_id="pn_b",
            position="0",
        ),
    )
    assert preview.status == 200
    assert b"Semantic changes" in preview.body and b"node order" in preview.body
    applied = application.post(
        "/phosphor/design/drafts/draft_test/apply",
        form(application, preview_token=preview_token(preview.body)),
    )
    assert applied.status == 303
    assert store.current("draft_test").ordinal == 2
    assert [node.node_id for node in store.current("draft_test").document.nodes] == [
        "pn_b",
        "pn_a",
    ]


def test_double_submit_same_reviewed_operation_is_idempotent(tmp_path):
    application, store, revision = app(tmp_path)
    response = application.post(
        "/phosphor/design/drafts/draft_test/preview",
        form(
            application,
            expected_revision_id=revision.revision_id,
            operation_type="add_node",
            description="Verify",
        ),
    )
    token = preview_token(response.body)
    first = application.post(
        "/phosphor/design/drafts/draft_test/apply",
        form(application, preview_token=token),
    )
    second = application.post(
        "/phosphor/design/drafts/draft_test/apply",
        form(application, preview_token=token),
    )
    assert first.status == second.status == 303
    assert len(store.revisions("draft_test")) == 2


def test_preview_tamper_and_cross_draft_substitution_refuse(tmp_path):
    application, store, revision = app(tmp_path)
    response = application.post(
        "/phosphor/design/drafts/draft_test/preview",
        form(
            application,
            expected_revision_id=revision.revision_id,
            operation_type="add_node",
            description="Exact preview",
        ),
    )
    token = preview_token(response.body)
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
    refused = application.post(
        "/phosphor/design/drafts/draft_test/apply",
        form(application, preview_token=tampered),
    )
    assert refused.status == 400
    other = store.create(plan(), draft_id="draft_other")
    crossed = application.post(
        f"/phosphor/design/drafts/{other.draft_id}/apply",
        form(application, preview_token=token),
    )
    assert crossed.status == 409
    assert len(store.revisions("draft_test")) == 1


def test_stale_preview_refuses_instead_of_rebasing(tmp_path):
    application, store, revision = app(tmp_path)
    preview = application.post(
        "/phosphor/design/drafts/draft_test/preview",
        form(
            application,
            expected_revision_id=revision.revision_id,
            operation_type="reorder_node",
            node_id="pn_b",
            position="0",
        ),
    )
    store.save_successor(
        revision.draft_id,
        revision.revision_id,
        replace(revision.document, goal="CLI won the race"),
        edit_origin=EditOrigin.HUMAN,
    )
    refused = application.post(
        "/phosphor/design/drafts/draft_test/apply",
        form(application, preview_token=preview_token(preview.body)),
    )
    assert refused.status == 409
    assert b"Stale edit refused" in refused.body
    assert b"node order" in refused.body
    assert b"reviewed operation was not rebased" in refused.body
    assert store.current("draft_test").document.goal == "CLI won the race"


def test_two_browser_edits_have_one_winner_and_explicit_conflict(tmp_path):
    application, store, revision = app(tmp_path)

    def make_preview(position: int) -> str:
        response = application.post(
            "/phosphor/design/drafts/draft_test/preview",
            form(
                application,
                expected_revision_id=revision.revision_id,
                operation_type="reorder_node",
                node_id="pn_b",
                position=str(position),
            ),
        )
        return preview_token(response.body)

    first = make_preview(0)
    second_response = application.post(
        "/phosphor/design/drafts/draft_test/preview",
        form(
            application,
            expected_revision_id=revision.revision_id,
            operation_type="add_node",
            description="Other tab",
        ),
    )
    second = preview_token(second_response.body)
    assert (
        application.post(
            "/phosphor/design/drafts/draft_test/apply",
            form(application, preview_token=first),
        ).status
        == 303
    )
    assert (
        application.post(
            "/phosphor/design/drafts/draft_test/apply",
            form(application, preview_token=second),
        ).status
        == 409
    )
    assert len(store.revisions("draft_test")) == 2


def test_cycle_is_draftable_but_exact_checker_finds_it(tmp_path):
    application, store, revision = app(tmp_path)
    update = PlanOperationV1(
        UpdateNodeV1(replace(revision.document.nodes[0], depends_on=("pn_b",)))
    )
    proposed = apply_plan_operation(revision.document, update).document
    saved = store.save_successor(
        revision.draft_id,
        revision.revision_id,
        proposed,
        edit_origin=EditOrigin.HUMAN,
    )
    receipt = store.check(saved.draft_id)
    assert receipt.result == "refused"
    assert {finding.rule_id for finding in receipt.findings} == {
        "plan.dependencies.acyclic"
    }


def test_presentation_changes_do_not_change_semantic_digest_or_receipts(tmp_path):
    application, store, revision = app(tmp_path)
    check = store.check(revision.draft_id)
    lock = store.lock(revision.draft_id)
    presentation = application.presentations.save(
        PlanPresentationV2(
            revision.draft_id,
            revision.revision_id,
            selected_node_id="pn_b",
            selected_object_kind="node",
            selected_object_id="pn_b",
            collapsed_node_ids=("pn_a",),
            outline_percent=42,
        ),
        expected_version=None,
    )
    assert presentation.presentation_digest != revision.plan_digest
    assert store.current(revision.draft_id).plan_digest == revision.plan_digest
    assert store.check_receipts(revision.draft_id)[0].receipt_id == check.receipt_id
    assert store.locks(revision.draft_id)[0].lock_id == lock.lock_id
    assert len(store.revisions(revision.draft_id)) == 1


def test_casework_tab_and_selected_object_are_presentation_only(tmp_path):
    application, store, revision = app(tmp_path)
    check = store.check(revision.draft_id)
    lock = store.lock(revision.draft_id)
    response = set_casework(
        application,
        revision,
        "history",
        selected_object_kind="revision",
        selected_object_id=revision.revision_id,
    )
    assert response.status == 303
    assert response.location is not None and response.location.endswith("#active-case")
    saved = application.presentations.load(revision.draft_id)
    assert saved is not None
    assert saved.active_casework_tab == "history"
    assert saved.selected_object_kind == "revision"
    assert saved.selected_object_id == revision.revision_id
    assert store.current(revision.draft_id).plan_digest == revision.plan_digest
    assert store.check_receipts(revision.draft_id) == (check,)
    assert store.locks(revision.draft_id) == (lock,)
    assert len(store.revisions(revision.draft_id)) == 1
    body = application.get("/phosphor/design/drafts/draft_test").body
    assert b'aria-pressed="true">Revision history' in body
    assert b"Active case \xc2\xb7 revision" in body


def test_casework_navigation_focus_and_invalid_anchor_are_closed(tmp_path):
    application, _, revision = app(tmp_path)
    response = set_casework(
        application,
        revision,
        "checks",
        return_anchor="casework",
    )
    assert response.status == 303
    assert response.location is not None and response.location.endswith("#casework")
    page = application.get("/phosphor/design/drafts/draft_test").body
    assert b'id="active-case" class="case-focus" tabindex="-1"' in page
    assert b'id="casework" class="panel lower casework" tabindex="-1"' in page

    current = application.presentations.load(revision.draft_id)
    assert current is not None
    refused = set_casework(
        application,
        revision,
        "history",
        return_anchor="semantic-state",
    )
    assert refused.status == 400
    assert application.presentations.load(revision.draft_id) == current


def test_v1_presentation_has_deterministic_casework_upgrade():
    upgraded = PlanPresentationV2.from_data(
        {
            "active_detail_tab": "node",
            "collapsed_node_ids": [],
            "draft_id": "draft_a",
            "outline_percent": 36,
            "schema": PLAN_PRESENTATION_V1_SCHEMA,
            "selected_node_id": "pn_a",
            "semantic_revision_id": "revision_a",
            "version": 7,
        }
    )
    assert upgraded.schema == "maude.plan-presentation/v2"
    assert upgraded.active_casework_tab == "findings"
    assert upgraded.selected_object_kind == "node"
    assert upgraded.selected_object_id == "pn_a"


def test_selected_finding_persists_as_case_and_exact_node_cross_probe(tmp_path):
    application, store, revision = app(tmp_path)
    changed = store.save_successor(
        revision.draft_id,
        revision.revision_id,
        replace(
            revision.document,
            nodes=(
                revision.document.nodes[0],
                replace(revision.document.nodes[1], depends_on=("pn_a", "pn_a")),
            ),
        ),
        edit_origin=EditOrigin.HUMAN,
    )
    receipt = store.check(changed.draft_id)
    finding = receipt.findings[0]
    response = set_casework(
        application,
        changed,
        "findings",
        selected_node_id="pn_b",
        selected_object_kind="finding",
        selected_object_id=f"{receipt.receipt_id}/{finding.finding_id}",
    )
    assert response.status == 303
    body = application.get("/phosphor/design/drafts/draft_test").body
    assert b"Active case \xc2\xb7 finding" in body
    assert finding.finding_id.encode() in body
    assert b">Change</h2>" in body


def test_current_and_historical_findings_remain_separate_cases(tmp_path):
    application, store, revision = app(tmp_path)
    invalid = replace(
        revision.document,
        nodes=(
            revision.document.nodes[0],
            replace(revision.document.nodes[1], depends_on=("pn_a", "pn_a")),
        ),
    )
    first = store.save_successor(
        revision.draft_id,
        revision.revision_id,
        invalid,
        edit_origin=EditOrigin.HUMAN,
    )
    store.check(first.draft_id)
    second = store.save_successor(
        first.draft_id,
        first.revision_id,
        replace(first.document, goal="Same finding, new exact bytes"),
        edit_origin=EditOrigin.HUMAN,
    )
    store.check(second.draft_id)
    body = application.get("/phosphor/design/drafts/draft_test").body
    assert b"Current applicable findings" in body
    assert b"Historical / non-applicable findings" in body
    assert b"historical_digest" in body
    assert b"current_findings" in body
    projected = store.projection(second.draft_id)
    historical = next(
        item
        for item in projected.checks
        if item.applicability.value == "historical_digest"
    )
    current = next(
        item
        for item in projected.checks
        if item.applicability.value == "current_findings"
    )
    finding_id = current.receipt.findings[0].finding_id
    assert historical.receipt.findings[0].finding_id == finding_id
    current_locator = f"{current.receipt.receipt_id}/{finding_id}"
    set_casework(
        application,
        second,
        "findings",
        selected_node_id=current.receipt.findings[0].target.node_id or "",
        selected_object_kind="finding",
        selected_object_id=current_locator,
    )
    current_body = application.get("/phosphor/design/drafts/draft_test").body.decode()
    active = current_body.split('aria-label="Active finding"', 1)[1].split(
        "</section>", 1
    )[0]
    assert "current_findings" in active
    assert current.receipt.receipt_id in active
    assert (
        current_body.count(f'id="finding-{current.receipt.receipt_id}-{finding_id}"')
        == 1
    )
    historical_locator = f"{historical.receipt.receipt_id}/{finding_id}"
    set_casework(
        application,
        second,
        "findings",
        selected_node_id=historical.receipt.findings[0].target.node_id or "",
        selected_object_kind="finding",
        selected_object_id=historical_locator,
    )
    historical_body = application.get(
        "/phosphor/design/drafts/draft_test"
    ).body.decode()
    active = historical_body.split('aria-label="Active finding"', 1)[1].split(
        "</section>", 1
    )[0]
    assert "historical_digest" in active
    assert historical.receipt.receipt_id in active


def test_check_receipt_case_routes_to_checks_not_lock_receipts(tmp_path):
    application, store, revision = app(tmp_path)
    receipt = store.check(revision.draft_id)
    set_casework(
        application,
        revision,
        "checks",
        selected_object_kind="receipt",
        selected_object_id=receipt.receipt_id,
    )
    body = application.get("/phosphor/design/drafts/draft_test").body
    assert b"Active case \xc2\xb7 receipt" in body
    assert b"Immutable check receipt" in body
    assert b">Inspect checks</button>" in body
    assert b'aria-pressed="true">Checks</button>' in body


def test_presentation_stale_and_orphan_are_visible_without_retarget(tmp_path):
    application, store, revision = app(tmp_path)
    sidecar = application.presentations.save(
        PlanPresentationV2(
            revision.draft_id,
            revision.revision_id,
            selected_node_id="pn_a",
            selected_object_kind="node",
            selected_object_id="pn_a",
            collapsed_node_ids=("pn_a",),
        ),
        expected_version=None,
    )
    successor = store.save_successor(
        revision.draft_id,
        revision.revision_id,
        replace(revision.document, nodes=(revision.document.nodes[1],)),
        edit_origin=EditOrigin.HUMAN,
    )
    projection = project_presentation(
        sidecar, successor.document, successor.revision_id
    )
    assert projection.to_data()["schema"] == "maude.plan-presentation-projection/v2"
    assert projection.stale_revision is True
    assert projection.orphaned_node_ids == ("pn_a",)
    page = application.get("/phosphor/design/drafts/draft_test")
    assert b"Orphaned presentation reference" in page.body
    assert [node.node_id for node in store.current("draft_test").document.nodes] == [
        "pn_b"
    ]


def test_presentation_store_cas_substitution_and_malformed_record(tmp_path):
    store = PresentationStore(tmp_path / "presentation.sqlite")
    first = store.save(
        PlanPresentationV2(
            "draft_a",
            "rev_a",
            selected_node_id="pn_a",
            selected_object_kind="node",
            selected_object_id="pn_a",
        ),
        expected_version=None,
    )
    with pytest.raises(PresentationConflict):
        store.save(
            PlanPresentationV2(
                "draft_a",
                "rev_b",
                selected_node_id="pn_b",
                selected_object_kind="node",
                selected_object_id="pn_b",
            ),
            expected_version=0,
        )
    store.save(
        PlanPresentationV2(
            "draft_b",
            "rev_b",
            selected_node_id="pn_b",
            selected_object_kind="node",
            selected_object_id="pn_b",
        ),
        expected_version=None,
    )
    assert store.load("draft_a") == first
    with sqlite3.connect(store.path) as db:
        db.execute(
            "UPDATE presentations SET record=? WHERE draft_id='draft_a'", (b"{}",)
        )
    with pytest.raises(PresentationError):
        store.load("draft_a")


def test_presentation_store_failure_cannot_mutate_plan(tmp_path):
    application, store, revision = app(tmp_path)
    application.presentations.path = tmp_path / "missing" / "bad.sqlite"
    response = application.get("/phosphor/design/drafts/draft_test")
    assert response.status == 503
    assert b"Presentation state unavailable" in response.body
    assert b"PlanDocument semantic state was not changed" in response.body
    assert store.current(revision.draft_id).plan_digest == revision.plan_digest


def test_cross_probe_uses_exact_finding_target_and_survives_reorder(tmp_path):
    application, store, revision = app(tmp_path)
    invalid = replace(
        revision.document,
        nodes=(
            revision.document.nodes[0],
            replace(revision.document.nodes[1], depends_on=("pn_a", "pn_a")),
        ),
    )
    changed = store.save_successor(
        revision.draft_id,
        revision.revision_id,
        invalid,
        edit_origin=EditOrigin.HUMAN,
    )
    receipt = store.check(changed.draft_id)
    finding = next(item for item in receipt.findings if item.target.node_id == "pn_b")
    body = application.get("/phosphor/design/drafts/draft_test").body.decode()
    assert f'value="{receipt.receipt_id}/{finding.finding_id}"' in body
    assert 'value="finding"' in body
    cross_probed = application.get(
        f"/phosphor/design/drafts/draft_test?node=pn_b&finding={quote(finding.finding_id)}"
    ).body
    assert b"Active case \xc2\xb7 finding" in cross_probed
    assert b"Changed exact node" not in cross_probed
    assert b">Change</h2>" in cross_probed
    reordered = replace(invalid, nodes=tuple(reversed(invalid.nodes)))
    latest = store.save_successor(
        changed.draft_id,
        changed.revision_id,
        reordered,
        edit_origin=EditOrigin.HUMAN,
    )
    receipt2 = store.check(latest.draft_id)
    assert any(item.target.node_id == "pn_b" for item in receipt2.findings)


def test_document_finding_cross_probe_does_not_fabricate_node(tmp_path):
    application, store, revision = app(tmp_path)
    changed = store.save_successor(
        revision.draft_id,
        revision.revision_id,
        replace(revision.document, goal=""),
        edit_origin=EditOrigin.HUMAN,
    )
    receipt = store.check(changed.draft_id)
    finding = receipt.findings[0]
    assert finding.target.kind == "document" and finding.target.node_id is None
    body = application.get("/phosphor/design/drafts/draft_test").body.decode()
    assert f'value="{receipt.receipt_id}/{finding.finding_id}"' in body
    assert 'value="finding"' in body


def test_locked_revision_bytes_remain_and_successor_edit_is_normal(tmp_path):
    application, store, revision = app(tmp_path)
    lock = store.lock(revision.draft_id)
    successor = store.save_successor(
        revision.draft_id,
        revision.revision_id,
        replace(revision.document, goal="After lock"),
        edit_origin=EditOrigin.HUMAN,
    )
    assert lock.plan_digest == revision.plan_digest
    assert successor.plan_digest != lock.plan_digest
    assert (
        store.revision(revision.revision_id).document.goal == "Qualify the board file"
    )


def test_semantic_diff_cross_probe_links_current_ids_and_marks_removed_historical(
    tmp_path,
):
    application, store, revision = app(tmp_path)
    store.save_successor(
        revision.draft_id,
        revision.revision_id,
        replace(
            revision.document,
            nodes=(
                replace(revision.document.nodes[1], description="Changed exact node"),
                PlanNodeV1("pn_c", "Added exact node"),
            ),
        ),
        edit_origin=EditOrigin.HUMAN,
    )
    current = store.current("draft_test")
    state = application._presentation(current).presentation
    application.post(
        "/phosphor/design/drafts/draft_test/presentation",
        form(
            application,
            expected_version=str(state.version),
            semantic_revision_id=current.revision_id,
            selected_node_id=state.selected_node_id or "",
            collapsed_node_ids="",
            outline_percent="36",
            active_detail_tab="node",
            active_casework_tab="diff",
            selected_object_kind="node",
            selected_object_id=state.selected_node_id or "",
        ),
    )
    body = application.get("/phosphor/design/drafts/draft_test").body.decode()
    assert 'value="changed:pn_b"' in body
    assert 'value="added:pn_c"' in body
    assert "pn_a</span> · historical target removed; not retargeted" in body


def test_csrf_html_escaping_and_unsupported_handoff(tmp_path):
    application, store, revision = app(tmp_path)
    refused = application.post(
        "/phosphor/design/drafts/draft_test/check",
        {"csrf": ["wrong"], "expected_revision_id": [revision.revision_id]},
    )
    assert refused.status == 403
    escaped = store.save_successor(
        revision.draft_id,
        revision.revision_id,
        replace(revision.document, goal='<script>alert("x")</script>'),
        edit_origin=EditOrigin.HUMAN,
    )
    body = application.get("/phosphor/design/drafts/draft_test").body
    assert b"<script>" not in body and b"&lt;script&gt;" in body
    assert b"No exact workflow compiler, no governed handoff" in body
    assert escaped.ordinal == 2


def test_loopback_http_host_origin_methods_and_read_api(tmp_path):
    application, _, revision = app(tmp_path)
    server = DesignServer(("127.0.0.1", 0), application)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        connection = http.client.HTTPConnection(host, port, timeout=3)
        connection.request("GET", "/phosphor/design/api/v1/drafts")
        response = connection.getresponse()
        payload = json_loads(response.read())
        assert response.status == 200
        assert payload["schema"] == "maude.plan-design-draft-index/v1"

        connection.request("GET", "/phosphor/design/drafts/draft_test/api/v1")
        response = connection.getresponse()
        payload = json_loads(response.read())
        assert response.status == 200
        assert payload["schema"] == "maude.plan-design-workspace/v2"
        assert payload["presentation"]["schema"] == (
            "maude.plan-presentation-projection/v2"
        )

        connection.request("HEAD", "/phosphor/design/drafts/draft_test")
        response = connection.getresponse()
        assert response.status == 200 and response.read() == b""

        body = urlencode(
            {
                "csrf": application.csrf_token,
                "expected_revision_id": revision.revision_id,
            }
        )
        connection.request(
            "POST",
            "/phosphor/design/drafts/draft_test/check",
            body=body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": "http://malicious.invalid",
            },
        )
        response = connection.getresponse()
        assert response.status == 403
        response.read()

        connection.request("PUT", "/phosphor/design/drafts/draft_test")
        response = connection.getresponse()
        assert response.status == 405
        response.read()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def json_loads(value: bytes):
    import json

    return json.loads(value)


def test_non_loopback_bind_refuses_before_listener(tmp_path):
    application, _, _ = app(tmp_path)
    with pytest.raises(ValueError, match="loopback"):
        serve(("0.0.0.0", 0), application)


def test_demo_corpus_uses_real_schemas_and_exercises_applicability_and_drift(tmp_path):
    paths = generate_demo(tmp_path / "demo")
    store = DraftStore(paths["store"])
    application = DesignApplication(
        store,
        PresentationStore(paths["presentation_store"]),
        ProposalStore(paths["proposal_store"]),
        owner_facts=__import__(
            "maude.design.server", fromlist=["load_owner_facts"]
        ).load_owner_facts(tmp_path / "demo" / "owner-facts.json"),
    )
    assert len(store.list_drafts()) == 19
    assert store.projection("draft_historical_check").check_summary.value == (
        "historical_digest"
    )
    assert store.projection("draft_retired_checker").check_summary.value == (
        "retired_checker_or_rules"
    )
    assert store.projection("draft_node_finding").check_summary.value == (
        "current_findings"
    )
    casework = store.projection("draft_casework_findings")
    assert casework.check_summary.value == "current_findings"
    assert any(
        item.applicability.value == "historical_digest" for item in casework.checks
    )
    assert (
        sum(
            len(item.receipt.findings)
            for item in casework.checks
            if item.applicability.value == "current_findings"
        )
        >= 2
    )
    owner = application._projection("draft_owner_fact_drift").to_data()
    assert owner["working_differs_from_handoff"] is True
    assert owner["working_differs_from_governed"] is True
    dense = application.get("/phosphor/design/drafts/draft_dense_24_nodes")
    assert dense.status == 200 and dense.body.count(b'class="node ') == 24
    proposals = application.proposal_store.proposals("draft_dependency_chain")
    assert len(proposals) == 2
    stale = application.proposal_store.proposals("draft_long_content")[0]
    assert application.proposal_service.project(stale.proposal_id).lifecycle.value == (
        "stale"
    )


def test_contextual_agent_proposal_review_accept_and_exact_api(tmp_path):
    application, store, revision = app(tmp_path)
    generated = application.post(
        "/phosphor/design/drafts/draft_test/proposals/generate",
        form(
            application,
            expected_revision_id=revision.revision_id,
            proposal_generation_id="generation_ui_accept",
            scope_kind="node",
            target_node_id="pn_b",
            finding_id="",
            task="clarify verification",
            provider_scenario="bounded_edit",
        ),
    )
    assert generated.status == 303 and generated.location is not None
    review = application.get(generated.location)
    assert review.status == 200
    assert b"Review proposed changes" in review.body
    assert b"exact_nodes" in review.body
    assert b"2 \xc2\xb7 Affected plan steps" in review.body
    assert b"pn_b" in review.body
    assert b"3 \xc2\xb7 What will change" in review.body
    assert review.body.index(b"What will change") < review.body.index(
        b"Exact edit operations"
    )
    assert b"Model rationale" in review.body
    assert b"Accept changes into draft" in review.body
    api = application.get(generated.location + "/api/v1")
    assert api.status == 200
    assert json_loads(api.body)["schema"] == "maude.plan-edit-proposal-review/v1"

    accepted = application.post(generated.location + "/accept", form(application))
    assert accepted.status == 303
    assert store.current("draft_test").edit_origin == EditOrigin.AGENT
    terminal = application.get(generated.location)
    assert b"Terminal proposal disposition: accepted" in terminal.body
    assert b"Accept changes into draft" not in terminal.body


def test_finding_cross_probe_into_proposal_and_checker_remains_owner(tmp_path):
    application, store, revision = app(tmp_path)
    revision = store.save_successor(
        revision.draft_id,
        revision.revision_id,
        replace(
            revision.document,
            nodes=(
                revision.document.nodes[0],
                replace(revision.document.nodes[1], depends_on=("pn_a", "pn_a")),
            ),
        ),
        edit_origin=EditOrigin.HUMAN,
    )
    store.check(revision.draft_id)
    finding = next(
        item
        for receipt in store.projection(revision.draft_id).checks
        for item in receipt.receipt.findings
        if item.rule_id == "plan.reference.unique"
    )
    workspace = application.get(
        f"/phosphor/design/drafts/draft_test?node=pn_b&finding={quote(finding.finding_id)}"
    )
    assert b"finding " + finding.finding_id.encode() in workspace.body
    generated = application.post(
        "/phosphor/design/drafts/draft_test/proposals/generate",
        form(
            application,
            expected_revision_id=revision.revision_id,
            proposal_generation_id="generation_ui_finding",
            scope_kind="finding",
            target_node_id="pn_b",
            finding_id=finding.finding_id,
            task="propose an exact fix for the selected finding",
            provider_scenario="finding_fix",
        ),
    )
    assert generated.status == 303 and generated.location
    review = application.get(generated.location)
    assert finding.finding_id.encode() in review.body
    application.post(generated.location + "/accept", form(application))
    checked = store.check(revision.draft_id)
    assert all(item.finding_id != finding.finding_id for item in checked.findings)


def test_stale_agent_proposal_is_visible_and_cannot_retarget(tmp_path):
    application, store, revision = app(tmp_path)
    generated = application.post(
        "/phosphor/design/drafts/draft_test/proposals/generate",
        form(
            application,
            expected_revision_id=revision.revision_id,
            proposal_generation_id="generation_ui_stale",
            scope_kind="node",
            target_node_id="pn_b",
            finding_id="",
            task="clarify",
            provider_scenario="bounded_edit",
        ),
    )
    assert generated.location
    store.save_successor(
        revision.draft_id,
        revision.revision_id,
        replace(revision.document, goal="External CLI edit"),
        edit_origin=EditOrigin.HUMAN,
    )
    review = application.get(generated.location)
    assert b"This proposal is stale" in review.body
    assert b"Accept changes into draft" not in review.body
    refused = application.post(generated.location + "/accept", form(application))
    assert refused.status == 409
    assert store.current(revision.draft_id).document.goal == "External CLI edit"


def test_hostile_provider_refusal_is_visible_without_semantic_write(tmp_path):
    application, store, revision = app(tmp_path)
    refused = application.post(
        "/phosphor/design/drafts/draft_test/proposals/generate",
        form(
            application,
            expected_revision_id=revision.revision_id,
            proposal_generation_id="generation_ui_malformed",
            scope_kind="node",
            target_node_id="pn_b",
            finding_id="",
            task="malformed fixture",
            provider_scenario="malformed",
        ),
    )
    assert refused.status == 400
    assert store.current(revision.draft_id).revision_id == revision.revision_id
    presentation = application._presentation(revision).presentation
    switched = application.post(
        "/phosphor/design/drafts/draft_test/presentation",
        form(
            application,
            expected_version=str(presentation.version),
            semantic_revision_id=revision.revision_id,
            selected_node_id=presentation.selected_node_id or "",
            collapsed_node_ids="",
            outline_percent="36",
            active_detail_tab="node",
            active_casework_tab="proposals",
            selected_object_kind="node",
            selected_object_id=presentation.selected_node_id or "",
        ),
    )
    assert switched.status == 303
    workspace = application.get("/phosphor/design/drafts/draft_test")
    assert b"Provider refusals" in workspace.body
    assert b"provider output is not exact UTF-8 JSON" in workspace.body


def test_agent_rejection_preserves_plan_and_exact_proposal(tmp_path):
    application, store, revision = app(tmp_path)
    generated = application.post(
        "/phosphor/design/drafts/draft_test/proposals/generate",
        form(
            application,
            expected_revision_id=revision.revision_id,
            proposal_generation_id="generation_ui_reject",
            scope_kind="node",
            target_node_id="pn_b",
            finding_id="",
            task="debatable change",
            provider_scenario="rationale_disagreement",
        ),
    )
    assert generated.location
    rejected = application.post(
        generated.location + "/reject",
        form(application, reason="rationale does not describe the operation"),
    )
    assert rejected.status == 303
    assert store.current(revision.draft_id).revision_id == revision.revision_id
    review = application.get(generated.location)
    assert b"Terminal proposal disposition: rejected" in review.body


def test_browser_double_generation_submit_converges_on_exact_proposal(tmp_path):
    application, _, revision = app(tmp_path)
    values = form(
        application,
        expected_revision_id=revision.revision_id,
        proposal_generation_id="generation_same_browser_form",
        scope_kind="node",
        target_node_id="pn_b",
        finding_id="",
        task="one exact request",
        provider_scenario="bounded_edit",
    )
    first = application.post(
        "/phosphor/design/drafts/draft_test/proposals/generate", values
    )
    second = application.post(
        "/phosphor/design/drafts/draft_test/proposals/generate", values
    )
    assert first.status == second.status == 303
    assert first.location == second.location
    assert len(application.proposal_store.proposals(revision.draft_id)) == 1


def test_simultaneous_presentation_updates_have_one_winner(tmp_path):
    store = PresentationStore(tmp_path / "presentations.sqlite")
    first = store.save(
        PlanPresentationV2(
            "draft_a",
            "rev_a",
            selected_node_id="pn_a",
            selected_object_kind="node",
            selected_object_id="pn_a",
        ),
        expected_version=None,
    )
    barrier = threading.Barrier(2)
    outcomes = []

    def save(selected: str):
        barrier.wait()
        try:
            store.save(
                PlanPresentationV2(
                    "draft_a",
                    "rev_a",
                    selected_node_id=selected,
                    selected_object_kind="node",
                    selected_object_id=selected,
                ),
                expected_version=first.version,
            )
            outcomes.append("saved")
        except PresentationConflict:
            outcomes.append("conflict")

    threads = [threading.Thread(target=save, args=(item,)) for item in ("pn_b", "pn_c")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["conflict", "saved"]


def test_governed_cross_probe_is_exact_read_only_node_navigation(tmp_path):
    application, store, revision = app(tmp_path)
    binding = governed_binding(plan_digest=revision.plan_digest)
    application.governed_cross_probe = {revision.draft_id: (binding,)}
    before = store.current(revision.draft_id)

    page = application.get(f"/phosphor/design/drafts/{revision.draft_id}?node=pn_a")
    assert page.status == 200
    assert b"Governed history \xc2\xb7 owner-produced exact joins" in page.body
    assert b"Inspect exact governed occurrence in Phosphor-ng" in page.body
    assert b"current PlanDocument binding" in page.body
    assert binding.plan_digest.encode() in page.body
    assert binding.inspector_path.encode() in page.body
    assert binding.docket_attempt_id.encode() in page.body
    api = application.get(f"/phosphor/design/drafts/{revision.draft_id}/api/v1")
    assert api.status == 200
    assert json.loads(api.body)["governed_node_bindings"] == [binding.to_data()]
    assert store.current(revision.draft_id) == before


def test_governed_cross_probe_keeps_stable_node_generation_context(tmp_path):
    application, store, revision = app(tmp_path)
    current = governed_binding(plan_digest=revision.plan_digest)
    historical_facts = current.to_data()
    historical_facts.pop("binding_id")
    historical_facts["plan_digest"] = digest("c")
    historical_facts["compilation_id"] = digest("d")
    historical_facts["compiled_output_identity"] = digest("e")
    historical_facts["exact_work_identity"] = digest("f")
    historical_facts["occurrence_id"] = "00000000-0000-4000-8000-000000000000"
    historical_facts["proposal_id"] = digest("0")
    historical_facts["issuance_id"] = digest("2")
    historical_facts["docket_attempt_id"] = digest("3")
    historical_facts["settlement_id"] = digest("4")
    historical_facts["inspector_path"] = (
        "/phosphor-ng/campaigns/"
        + quote(historical_facts["campaign_id"], safe="")
        + "/occurrences/"
        + historical_facts["occurrence_id"]
        + "/proposals/"
        + quote(historical_facts["proposal_id"], safe="")
    )
    historical = GovernedNodeBindingV1.create(**historical_facts)
    application.governed_cross_probe = {revision.draft_id: (historical, current)}

    page = application.get(f"/phosphor/design/drafts/{revision.draft_id}?node=pn_a")
    assert page.status == 200
    assert b"historical PlanDocument binding" in page.body
    assert b"current PlanDocument binding" in page.body
    assert historical.plan_digest.encode() in page.body
    assert current.plan_digest.encode() in page.body
    assert store.current(revision.draft_id) == revision


def test_governed_cross_probe_substitution_and_path_retarget_refuse(tmp_path):
    binding = governed_binding()
    path = tmp_path / "cross-probe.json"
    path.write_bytes(
        canonical_json_bytes(
            {"bindings": [binding.to_data()], "schema": GOVERNED_CROSS_PROBE_SCHEMA}
        )
    )
    assert load_governed_cross_probe(path) == {"draft_test": (binding,)}

    substituted = binding.to_data()
    substituted["docket_attempt_id"] = digest("c")
    path.write_bytes(
        canonical_json_bytes(
            {"bindings": [substituted], "schema": GOVERNED_CROSS_PROBE_SCHEMA}
        )
    )
    with pytest.raises(ValueError, match="identity does not bind"):
        load_governed_cross_probe(path)

    retargeted = binding.to_data()
    retargeted["inspector_path"] = retargeted["inspector_path"].replace(
        binding.occurrence_id, "00000000-0000-4000-8000-000000000001"
    )
    retargeted["binding_id"] = content_digest(
        canonical_json_bytes(
            {key: value for key, value in retargeted.items() if key != "binding_id"}
        )
    )
    path.write_bytes(
        canonical_json_bytes(
            {"bindings": [retargeted], "schema": GOVERNED_CROSS_PROBE_SCHEMA}
        )
    )
    with pytest.raises(ValueError, match="inspector path is not exact"):
        load_governed_cross_probe(path)
