# SPDX-License-Identifier: Apache-2.0
"""M-4 run-report tests.

Pins the load-bearing disciplines: the report composes from a CD-4B-shaped
ReviewPacket; absent reads render as honest absence, never inferred; a
provider/actor "success" renders as testimony (never upgraded to an admission);
acceptance criteria render unchecked (count = criteria count); and composition
issues zero write-RPCs (fake-client call-log pin).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from maude.commands.base import CommandContext
from maude.commands.report import ReportCommand
from maude.intents import IntentKind, parse_intent
from maude.plan.envelope import parse_plan_envelope
from maude.report import (
    ABSENT,
    AuthorityRow,
    compose_run_report,
    render_detail,
    render_law,
    render_surface,
)

# --------------------------------------------------------------------------- #
# Fixtures — CD-4B-shaped (docs/campaigns/conveyor-dogfood/specimens/cd4-*)
# --------------------------------------------------------------------------- #

# The all-false authority block from the CD-4B specimen (no change, nothing
# requested/granted/used). No overrun.
_CD4B_AUTHORITY = {
    "requested": {k: False for k in (
        "commit", "push", "network", "subprocess",
        "live_origin", "doctrine_write", "constellation_write")},
    "granted": {k: False for k in (
        "commit", "push", "network", "subprocess",
        "live_origin", "doctrine_write", "constellation_write")},
    "used": {k: False for k in (
        "commit", "push", "network", "subprocess",
        "live_origin", "doctrine_write", "constellation_write")},
}

CD4B_REVIEW_PACKET = {
    "schema_version": "review_packet.v0",
    "packet_id": "cd4-docs-normalize",
    "playbook_id": "chore.docs-playbooks-normalize",
    "status": "no_change",
    "authority": _CD4B_AUTHORITY,
    "files_changed": [],
    "followups": [
        {"id": "cd4-fu-1", "title": "Doctrine decision: glossary terms?"},
    ],
    "operator_review_required": True,
}

PLAN_WITH_CRITERIA = """\
---
plan_version: 0
goal: "Normalize the playbook docs"
workspace: "/tmp/proj"
submitter_kind: human
plan_origin: human_written
provenance:
  author: "operator"
harness: claude_code
acceptance_criteria:
  - "every named term is consistent"
  - "no semantic change to prose"
  - "the survey is recorded"
---

Background.
"""


def _session(**over):
    base = {
        "session_id": "sess-1",
        "backend_kind": "claude_code",
        "cwd": "/tmp/proj",
        "status": "exited",
        "started_at": "2026-07-05T10:00:00Z",
        "updated_at": "2026-07-05T10:04:00Z",
        "exit_code": 0,
    }
    base.update(over)
    return base


def _events():
    return [
        {"seq": 1, "kind": "tool_call_proposed", "receipt_ids": ["rcpt_a"], "payload": {}},
        {"seq": 2, "kind": "tool_call_allowed", "receipt_ids": ["rcpt_a"], "payload": {}},
        {"seq": 3, "kind": "tool_call_completed", "receipt_ids": [], "payload": {}},
        {"seq": 4, "kind": "tool_call_denied", "receipt_ids": ["rcpt_b"], "payload": {}},
        {"seq": 5, "kind": "session_exited", "receipt_ids": [], "payload": {"exit_code": 0}},
    ]


def _promotion(**over):
    base = {
        "promotion_id": "prom_1",
        "session_id": "sess-1",
        "status": "pending",
        "changed_files": ["docs/a.md", "docs/b.md"],
        "excluded_files": ["docs/preexisting.md"],
        "diff_stat": "2 files changed, 4 insertions(+)",
    }
    base.update(over)
    return base


# --------------------------------------------------------------------------- #
# Composition from a CD-4B-shaped fixture
# --------------------------------------------------------------------------- #


class TestComposeFromFixture:
    def test_composes_core_fields(self):
        plan = parse_plan_envelope(PLAN_WITH_CRITERIA)
        report = compose_run_report(
            "sess-1",
            session=_session(),
            events=_events(),
            promotion=_promotion(),
            plan=plan,
            review_packet=CD4B_REVIEW_PACKET,
            review_packet_path="/x/review_packet.manifest.json",
        )
        assert report.harness == "claude_code"
        assert report.status == "exited"
        assert report.exit_code == 0
        assert report.files_changed == ("docs/a.md", "docs/b.md")
        assert report.excluded_files == ("docs/preexisting.md",)
        assert report.promotion_status == "pending"
        # tool counts split testimony (proposed/allowed/completed) from the gate act (denied)
        assert report.tool_counts.proposed == 1
        assert report.tool_counts.completed == 1
        assert report.tool_counts.denied == 1
        # receipts collected (dedup, order-preserving) — cited, not minted
        assert report.receipt_ids == ("rcpt_a", "rcpt_b")
        # authority = all 7 axes from the packet, none overrun
        assert len(report.authority) == 7
        assert not report.has_overrun
        assert report.plan_ref == plan.plan_ref
        assert report.provenance_author == "operator"

    def test_law_layer_is_verbatim(self):
        report = compose_run_report(
            "sess-1", review_packet=CD4B_REVIEW_PACKET,
            review_packet_path="/x/rp.json",
        )
        text = "\n".join(render_law(report))
        # the raw packet is disclosed, including a distinctive nested value
        assert "cd4-fu-1" in text
        assert "review_packet.v0" in text
        assert "/x/rp.json" in text


# --------------------------------------------------------------------------- #
# Honest absence — nothing inferred
# --------------------------------------------------------------------------- #


class TestHonestAbsence:
    def test_absent_reads_render_not_recorded(self):
        report = compose_run_report("sess-unknown")  # every read absent
        surface = "\n".join(render_surface(report))
        detail = "\n".join(render_detail(report))
        # harness, duration, changed, outcome all honest-absence on the surface
        assert surface.count(ABSENT) >= 3
        # no review packet → authority + acceptance are absent, not zero-filled
        assert ABSENT in detail
        assert "used ≤ granted" in detail
        # no fabricated exit / harness value leaked in
        assert "claude_code" not in surface
        assert report.harness is None
        assert report.exit_code is None

    def test_partial_duration_is_absent_not_halfspan(self):
        # only a start recorded → duration is honest-absence, never a one-ended span
        report = compose_run_report(
            "s", session=_session(updated_at=None),
        )
        surface = "\n".join(render_surface(report))
        assert f"ran: [dim]{ABSENT}" in surface

    def test_read_failure_surfaces_as_note(self):
        report = compose_run_report("s", notes=["session read unavailable: boom"])
        surface = "\n".join(render_surface(report))
        assert "session read unavailable: boom" in surface


# --------------------------------------------------------------------------- #
# Testimony is not admission
# --------------------------------------------------------------------------- #


class TestTestimonyNotAdmission:
    def test_exit_zero_renders_as_testimony_not_verdict(self):
        report = compose_run_report("s", session=_session(exit_code=0, status="exited"))
        surface = "\n".join(render_surface(report))
        # framed as the run's own report, explicitly not a verdict
        assert "the run reports it ended" in surface
        assert "not a verdict" in surface
        # never upgraded to an unqualified success/pass claim
        low = surface.lower()
        assert "succeeded" not in low
        assert "passed" not in low

    def test_used_beyond_grant_is_flagged_overrun_never_authorized(self):
        # actor testimony claims it used 'commit'; the grant said no.
        packet = json.loads(json.dumps(CD4B_REVIEW_PACKET))  # deep copy
        packet["authority"]["used"]["commit"] = True
        report = compose_run_report("s", review_packet=packet)
        commit_row = next(r for r in report.authority if r.axis == "commit")
        assert commit_row.overrun is True
        assert report.has_overrun is True
        rendered = "\n".join(render_surface(report) + render_detail(report))
        assert "OVERRUN" in rendered
        # the overrun is never laundered into an authorization
        assert "authorized" not in rendered.lower()

    def test_granted_is_labelled_a_standing_act_not_actor_report(self):
        report = compose_run_report("s", review_packet=CD4B_REVIEW_PACKET)
        detail = "\n".join(render_detail(report))
        assert "'used' is the run's own report (testimony)" in detail
        assert "'granted' is the standing grant (act)" in detail

    def test_promotion_decision_renders_as_operator_act(self):
        kept = compose_run_report("s", promotion=_promotion(status="approved"))
        assert "you kept the changes" in "\n".join(render_surface(kept))
        assert "your act" in "\n".join(render_surface(kept))
        discarded = compose_run_report("s", promotion=_promotion(status="rejected"))
        assert "you discarded the changes" in "\n".join(render_surface(discarded))


# --------------------------------------------------------------------------- #
# Acceptance criteria — rendered unchecked, count matches
# --------------------------------------------------------------------------- #


class TestAcceptanceUnchecked:
    def test_unchecked_count_equals_criteria_count(self):
        plan = parse_plan_envelope(PLAN_WITH_CRITERIA)
        report = compose_run_report("s", plan=plan)
        detail = render_detail(report)
        unchecked = [ln for ln in detail if "[ ]" in ln]
        assert len(unchecked) == len(plan.acceptance_criteria) == 3
        # never auto-judged: no checked boxes appear
        assert not any("[x]" in ln.lower() for ln in detail)

    def test_no_criteria_renders_absence_not_empty_checklist(self):
        report = compose_run_report("s")  # no plan
        detail = render_detail(report)
        assert not any("[ ]" in ln for ln in detail)
        joined = "\n".join(detail)
        assert "acceptance criteria" in joined
        assert ABSENT in joined


# --------------------------------------------------------------------------- #
# Authority row semantics (pure)
# --------------------------------------------------------------------------- #


class TestAuthorityRow:
    def test_overrun_only_when_used_true_granted_not_true(self):
        assert AuthorityRow("x", None, False, True).overrun is True
        assert AuthorityRow("x", None, True, True).overrun is False
        assert AuthorityRow("x", None, False, False).overrun is False
        # absent used never counts as an overrun (honest absence)
        assert AuthorityRow("x", None, False, None).overrun is False


# --------------------------------------------------------------------------- #
# Intent parsing
# --------------------------------------------------------------------------- #


class TestIntentParse:
    def test_report_session_only(self):
        intent = parse_intent("report sess-1")
        assert intent.kind == IntentKind.REPORT
        assert intent.payload == "sess-1"

    def test_report_with_plan_path(self):
        intent = parse_intent("report sess-1 docs/plan.md")
        assert intent.kind == IntentKind.REPORT
        assert intent.payload == "sess-1 docs/plan.md"

    def test_bare_report_prose_falls_through_to_chat(self):
        assert parse_intent("report on the weather").kind == IntentKind.CHAT


# --------------------------------------------------------------------------- #
# Command layer — zero write-RPC pin + disk lookup
# --------------------------------------------------------------------------- #


class FakeLog:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def write(self, line: str = "") -> None:
        self.lines.append(str(line))

    def text(self) -> str:
        return "\n".join(self.lines)


class RecordingClient:
    """Fake client with a call log. Read methods return canned data; any method
    NOT in the read allowlist would be recorded and fail the write-RPC pin."""

    READS = {"runtime_session_get", "runtime_session_events", "runtime_promotion_get"}

    def __init__(self, *, fail: set[str] | None = None) -> None:
        self.calls: list[str] = []
        self._fail = fail or set()

    async def runtime_session_get(self, sid):
        self.calls.append("runtime_session_get")
        if "runtime_session_get" in self._fail:
            raise RuntimeError("boom")
        return _session(session_id=sid)

    async def runtime_session_events(self, sid, limit=100):
        self.calls.append("runtime_session_events")
        return _events()

    async def runtime_promotion_get(self, sid):
        self.calls.append("runtime_promotion_get")
        return _promotion()


class FakeApp:
    def __init__(self, client) -> None:
        self.client = client
        self._last_plan_block = ("stale", "block", object())
        self._last_run_report = None


def _run(cmd, app, log, payload):
    ctx = CommandContext(app=app, log=log, text="")
    asyncio.new_event_loop().run_until_complete(cmd.execute(ctx, payload))


class TestReportCommand:
    def test_composition_issues_only_reads(self):
        client = RecordingClient()
        app, log = FakeApp(client), FakeLog()
        _run(ReportCommand(), app, log, "sess-1")
        # only read RPCs, no writes/mutations
        assert set(client.calls) <= RecordingClient.READS
        assert client.calls.count("runtime_session_get") == 1
        # report rendered + stashed for `why`, stale block cleared
        assert app._last_run_report is not None
        assert app._last_plan_block is None
        assert "RUN REPORT" in log.text()

    def test_read_failure_degrades_loudly_no_crash(self):
        client = RecordingClient(fail={"runtime_session_get"})
        app, log = FakeApp(client), FakeLog()
        _run(ReportCommand(), app, log, "sess-1")
        assert "session read unavailable" in log.text()
        # still composed a report from the reads that worked
        assert app._last_run_report is not None

    def test_finds_colocated_review_packet(self, tmp_path: Path):
        plan = tmp_path / "plan.md"
        plan.write_text(PLAN_WITH_CRITERIA)
        (tmp_path / "review_packet.manifest.json").write_text(
            json.dumps(CD4B_REVIEW_PACKET)
        )
        client = RecordingClient()
        app, log = FakeApp(client), FakeLog()
        _run(ReportCommand(), app, log, f"sess-1 {plan}")
        report = app._last_run_report
        # plan provenance + co-located packet both wired in
        assert report.provenance_author == "operator"
        assert report.review_packet is not None
        assert len(report.authority) == 7
        # law layer discloses the packet verbatim
        assert "cd4-fu-1" in "\n".join(render_law(report))

    def test_bad_plan_degrades_to_note_not_crash(self, tmp_path: Path):
        plan = tmp_path / "bad.md"
        plan.write_text("---\nplan_version: 0\n---\nmissing fields\n")
        client = RecordingClient()
        app, log = FakeApp(client), FakeLog()
        _run(ReportCommand(), app, log, f"sess-1 {plan}")
        assert "did not parse" in log.text()
        assert app._last_run_report is not None
