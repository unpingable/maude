# SPDX-License-Identifier: Apache-2.0
"""M-4 ``report <session_id> [plan.md]`` — compose + render a run report.

The command does the reads (``runtime.session.get``, ``runtime.session.events``,
``runtime.promotion.get`` — all EXISTING; no new RPC) and the disk lookup for
the co-located ReviewPacket, then hands already-fetched dicts to the pure
composer in :mod:`maude.report`. It writes nothing back — no write-RPC, no
implicit storage of the report (derived, reviewer-directed output only).

Each read is attempted independently: a read that fails degrades loudly into a
surfaced note, and composition proceeds over what was recorded — honest absence,
never a fabricated field.
"""

from __future__ import annotations

import json
from pathlib import Path

from maude.commands.base import Command, CommandContext
from maude.intents import IntentKind
from maude.plan.envelope import PlanEnvelope, PlanRefusal, parse_plan_envelope
from maude.report import (
    RunReport,
    compose_run_report,
    render_detail,
    render_law,
    render_surface,
)

#: Preferred name for the co-located review packet; then a broadened glob so a
#: differently-named packet is still found (first match wins, ambiguity noted).
_REVIEW_PACKET_NAME = "review_packet.manifest.json"
_REVIEW_PACKET_GLOB = "*review_packet*.json"


class ReportCommand(Command):
    """``report <session_id> [plan.md]`` — the M-4 reviewable result."""

    kinds = (IntentKind.REPORT,)
    help = "run report for a session"

    async def execute(self, ctx: CommandContext, payload: str) -> None:
        log = ctx.log
        parts = payload.split()
        if not parts:
            log.write("[yellow]Usage: report <session_id> [plan.md][/yellow]")
            return
        session_id = parts[0]
        plan_path = Path(parts[1]).expanduser() if len(parts) > 1 else None

        notes: list[str] = []
        session = await self._read(ctx, "session", notes, session_id)
        events = await self._read(ctx, "events", notes, session_id) or []
        promotion = await self._read(ctx, "promotion", notes, session_id)

        plan, review_packet, rp_path = self._load_from_disk(plan_path, notes)

        report = compose_run_report(
            session_id,
            session=session,
            events=events,
            promotion=promotion,
            plan=plan,
            review_packet=review_packet,
            review_packet_path=rp_path,
            notes=notes,
        )
        self._render(ctx, report)

    # -- reads (each independent; failure → surfaced note, not a crash) ------ #

    async def _read(self, ctx: CommandContext, which: str, notes: list[str], sid: str):
        client = ctx.app.client
        try:
            if which == "session":
                return await client.runtime_session_get(sid)
            if which == "events":
                return await client.runtime_session_events(sid, limit=1000)
            if which == "promotion":
                return await client.runtime_promotion_get(sid)
        except Exception as exc:  # noqa: BLE001 — surface, never swallow
            notes.append(f"{which} read unavailable: {exc}")
        return None

    def _load_from_disk(
        self, plan_path: Path | None, notes: list[str]
    ) -> tuple[PlanEnvelope | None, dict | None, str | None]:
        """Parse the plan envelope and its co-located ReviewPacket, if a plan
        path was given. Every failure degrades to a note + honest absence."""
        if plan_path is None:
            return None, None, None
        if not plan_path.is_file():
            notes.append(f"plan file not found: {plan_path}")
            return None, None, None
        plan: PlanEnvelope | None = None
        try:
            plan = parse_plan_envelope(plan_path.read_text(encoding="utf-8"))
        except PlanRefusal as refusal:
            notes.append(f"plan did not parse ({refusal.refusal_class}); provenance omitted")
        except OSError as exc:
            notes.append(f"cannot read plan: {exc}")
        review_packet, rp_path = self._find_review_packet(plan_path.parent, notes)
        return plan, review_packet, rp_path

    def _find_review_packet(
        self, plan_dir: Path, notes: list[str]
    ) -> tuple[dict | None, str | None]:
        preferred = plan_dir / _REVIEW_PACKET_NAME
        candidate = preferred if preferred.is_file() else None
        if candidate is None:
            matches = sorted(plan_dir.glob(_REVIEW_PACKET_GLOB))
            if matches:
                candidate = matches[0]
                if len(matches) > 1:
                    notes.append(
                        f"multiple review packets in {plan_dir}; using {candidate.name}"
                    )
        if candidate is None:
            return None, None
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            notes.append(f"review packet unreadable ({candidate.name}): {exc}")
            return None, None
        if not isinstance(data, dict):
            notes.append(f"review packet {candidate.name} is not a JSON object; ignored")
            return None, None
        return data, str(candidate)

    # -- render (surface + detail inline; law is one `why` away) ------------- #

    def _render(self, ctx: CommandContext, report: RunReport) -> None:
        log = ctx.log
        for line in render_surface(report):
            log.write(line)
        log.write("")
        for line in render_detail(report):
            log.write(line)
        # Stash the composed report so a `why` drilldown can disclose the raw
        # law layer (the ReviewPacket verbatim) without the surface showing it.
        # A report supersedes any prior block for the `why` overlay's context.
        ctx.app._last_plan_block = None
        ctx.app._last_run_report = report
        log.write("")
        log.write("[dim]type 'why' for the underlying record (the review packet, verbatim)[/dim]")


def render_report_law(report: RunReport) -> list[str]:
    """The law-layer lines for the `why` overlay (re-exported for the app)."""
    return render_law(report)
