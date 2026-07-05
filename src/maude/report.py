# SPDX-License-Identifier: Apache-2.0
"""M-4 run report — the reviewable result, composed from existing daemon reads.

*Displayed evidence, not adjudication.* On session end (or an explicit
``report <session_id>``) this module composes a report from reads that already
exist — ``runtime.session.get``, ``runtime.session.events``,
``runtime.promotion.get`` — plus, when a governed plan produced one, the
``ReviewPacket`` file co-located with the plan. It opens no new RPC and mints no
receipt: the report *cites* AG receipt IDs, it is not itself a receipt.

Two disciplines are load-bearing and pinned by the tests:

* **Honest absence.** A field that was not recorded renders as ``not recorded``
  (:data:`ABSENT`) — never inferred, never defaulted to a confident value.
* **Testimony is not admission.** A provider/actor "success" (exit code, tool
  completions, the ReviewPacket's ``authority.used`` block) is the *run's own
  report* and renders as testimony. Only decisions with standing — the
  operator's keep/discard, the gate's refusals, the granted authority — render
  as acts. The report never upgrades the former into the latter.

Composition is a pure function over already-fetched dicts (no IO, no RPC), so
"zero write-RPCs during composition" is true by construction. The command layer
(:mod:`maude.commands.report`) does the reads and the disk lookup; this module
only shapes and renders.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from maude.plan.envelope import PlanEnvelope

#: Rendered stand-in for any value the reads did not carry. Never a guess.
ABSENT = "not recorded"

# Tool-boundary event kinds (CONTRACT — mirror runtime.events.EventKind values;
# never improvised). Testimony kinds are the run's own trace; DENIED is a gate
# act and is counted separately so the two are never conflated.
_TOOL_PROPOSED = "tool_call_proposed"
_TOOL_ALLOWED = "tool_call_allowed"
_TOOL_COMPLETED = "tool_call_completed"
_TOOL_FAILED = "tool_call_failed"
_TOOL_DENIED = "tool_call_denied"

#: Authority axes of the ReviewPacket ``authority`` block (CONTRACT,
#: ``review_packet.v0``). Fixed order for a stable table.
AUTHORITY_AXES: tuple[str, ...] = (
    "commit",
    "push",
    "network",
    "subprocess",
    "live_origin",
    "doctrine_write",
    "constellation_write",
)


@dataclass(frozen=True)
class ToolCounts:
    """Counts of tool-boundary events. ``denied`` is a gate act; the rest are
    the run's own trace (testimony). Kept distinct so the render never merges a
    refusal into the actor's activity."""

    proposed: int = 0
    allowed: int = 0
    completed: int = 0
    failed: int = 0
    denied: int = 0


@dataclass(frozen=True)
class AuthorityRow:
    """One authority axis. Each cell is the raw tri-state from the packet
    (``True`` / ``False`` / ``None`` for absent). ``overrun`` flags the one
    thing the operator must see: the run *reports* using authority it was not
    granted (used ≤ granted violated). Testimony vs grant is never collapsed."""

    axis: str
    requested: bool | None
    granted: bool | None
    used: bool | None

    @property
    def overrun(self) -> bool:
        # used (testimony) exceeds granted (the standing decision).
        return self.used is True and self.granted is not True


@dataclass(frozen=True)
class RunReport:
    """A composed, render-ready run report. Every optional field is ``None`` /
    empty when the underlying read did not carry it — the render turns that into
    :data:`ABSENT`, never an inferred value."""

    session_id: str
    # -- surface (from session.get + promotion.get) --
    harness: str | None = None
    status: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    exit_code: int | None = None
    # -- provenance (from the plan envelope) --
    plan_ref: str | None = None
    goal: str | None = None
    submitter_kind: str | None = None
    provenance_author: str | None = None
    governed: bool = False
    # -- detail --
    tool_counts: ToolCounts = field(default_factory=ToolCounts)
    files_changed: tuple[str, ...] = ()
    excluded_files: tuple[str, ...] = ()
    diff_stat: str | None = None
    promotion_status: str | None = None
    acceptance_criteria: tuple[str, ...] = ()
    authority: tuple[AuthorityRow, ...] = ()
    receipt_ids: tuple[str, ...] = ()
    # -- law (verbatim, one `why` away) --
    review_packet: Mapping[str, object] | None = None
    review_packet_path: str | None = None
    # -- provenance of the composition itself: read failures surfaced, not hidden --
    notes: tuple[str, ...] = ()

    @property
    def has_overrun(self) -> bool:
        return any(row.overrun for row in self.authority)


# --------------------------------------------------------------------------- #
# Composition (pure)
# --------------------------------------------------------------------------- #


def _count_tools(events: Sequence[Mapping[str, object]]) -> tuple[ToolCounts, tuple[str, ...]]:
    tally = {
        _TOOL_PROPOSED: 0,
        _TOOL_ALLOWED: 0,
        _TOOL_COMPLETED: 0,
        _TOOL_FAILED: 0,
        _TOOL_DENIED: 0,
    }
    receipts: list[str] = []
    for ev in events:
        kind = str(ev.get("kind", ""))
        if kind in tally:
            tally[kind] += 1
        for rid in ev.get("receipt_ids") or []:
            if rid and rid not in receipts:
                receipts.append(str(rid))
    counts = ToolCounts(
        proposed=tally[_TOOL_PROPOSED],
        allowed=tally[_TOOL_ALLOWED],
        completed=tally[_TOOL_COMPLETED],
        failed=tally[_TOOL_FAILED],
        denied=tally[_TOOL_DENIED],
    )
    return counts, tuple(receipts)


def _authority_rows(review_packet: Mapping[str, object] | None) -> tuple[AuthorityRow, ...]:
    if not review_packet:
        return ()
    auth = review_packet.get("authority")
    if not isinstance(auth, Mapping):
        return ()
    requested = auth.get("requested") if isinstance(auth.get("requested"), Mapping) else {}
    granted = auth.get("granted") if isinstance(auth.get("granted"), Mapping) else {}
    used = auth.get("used") if isinstance(auth.get("used"), Mapping) else {}

    def _cell(block: object, axis: str) -> bool | None:
        # Absent axis stays None (renders as `not recorded`), never coerced.
        if isinstance(block, Mapping) and axis in block:
            v = block[axis]
            return v if isinstance(v, bool) else None
        return None

    rows: list[AuthorityRow] = []
    for axis in AUTHORITY_AXES:
        rows.append(
            AuthorityRow(
                axis=axis,
                requested=_cell(requested, axis),
                granted=_cell(granted, axis),
                used=_cell(used, axis),
            )
        )
    return tuple(rows)


def compose_run_report(
    session_id: str,
    *,
    session: Mapping[str, object] | None = None,
    events: Sequence[Mapping[str, object]] | None = None,
    promotion: Mapping[str, object] | None = None,
    plan: PlanEnvelope | None = None,
    review_packet: Mapping[str, object] | None = None,
    review_packet_path: str | None = None,
    notes: Sequence[str] = (),
) -> RunReport:
    """Compose a :class:`RunReport` from already-fetched reads. Pure: no IO, no
    RPC, no mutation of the inputs. Absent inputs become honest-absence fields."""

    events = list(events or [])
    counts, receipts = _count_tools(events)

    harness = None
    status = None
    started_at = None
    ended_at = None
    exit_code = None
    if session:
        harness = _opt_str(session.get("backend_kind"))
        status = _opt_str(session.get("status"))
        started_at = _opt_str(session.get("started_at"))
        ended_at = _opt_str(session.get("updated_at"))
        raw_exit = session.get("exit_code")
        exit_code = raw_exit if isinstance(raw_exit, int) else None

    files_changed: tuple[str, ...] = ()
    excluded_files: tuple[str, ...] = ()
    diff_stat = None
    promotion_status = None
    if promotion:
        files_changed = tuple(str(f) for f in (promotion.get("changed_files") or []))
        excluded_files = tuple(str(f) for f in (promotion.get("excluded_files") or []))
        diff_stat = _opt_str(promotion.get("diff_stat"))
        promotion_status = _opt_str(promotion.get("status"))

    plan_ref = goal = submitter_kind = provenance_author = None
    acceptance: tuple[str, ...] = ()
    governed = False
    if plan is not None:
        plan_ref = plan.plan_ref
        goal = plan.goal
        submitter_kind = plan.submitter_kind
        provenance_author = plan.provenance_author
        acceptance = tuple(plan.acceptance_criteria)
        governed = plan.governance is not None
        # A governed plan carries harness intent; the *used* harness comes from
        # the session read above and wins — the report shows what actually ran.
        if harness is None and plan.harness:
            harness = plan.harness

    return RunReport(
        session_id=session_id,
        harness=harness,
        status=status,
        started_at=started_at,
        ended_at=ended_at,
        exit_code=exit_code,
        plan_ref=plan_ref,
        goal=goal,
        submitter_kind=submitter_kind,
        provenance_author=provenance_author,
        governed=governed,
        tool_counts=counts,
        files_changed=files_changed,
        excluded_files=excluded_files,
        diff_stat=diff_stat,
        promotion_status=promotion_status,
        acceptance_criteria=acceptance,
        authority=_authority_rows(review_packet),
        receipt_ids=receipts,
        review_packet=review_packet,
        review_packet_path=review_packet_path,
        notes=tuple(notes),
    )


def _opt_str(value: object) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


# --------------------------------------------------------------------------- #
# Rendering (three-layer disclosure; surface + detail shown, law one `why` away)
# --------------------------------------------------------------------------- #


def _shown(value: str | None) -> str:
    return value if value else f"[dim]{ABSENT}[/dim]"


def render_surface(report: RunReport) -> list[str]:
    """Plain-ops first read: what ran, how long, what changed, what needs the
    operator's call. Provider/actor outcome is framed as the run's own report."""
    lines: list[str] = []
    lines.append(f"[bold]RUN REPORT[/bold]  {report.session_id}")
    if report.goal:
        lines.append(f"  goal: {report.goal}")
    lines.append(f"  harness: {_shown(report.harness)}")

    # Duration — absent unless both ends are recorded (never a fabricated span).
    if report.started_at and report.ended_at:
        lines.append(f"  ran: {report.started_at} → {report.ended_at}")
    else:
        lines.append(f"  ran: [dim]{ABSENT}[/dim]")

    # Outcome is TESTIMONY: the run's own status/exit, not a verdict.
    if report.status or report.exit_code is not None:
        exit_part = "" if report.exit_code is None else f", exit code {report.exit_code}"
        status_part = report.status or ABSENT
        lines.append(
            f"  the run reports it ended: {status_part}{exit_part}  "
            "[dim](its own report, not a verdict)[/dim]"
        )
    else:
        lines.append(f"  outcome: [dim]{ABSENT}[/dim]")

    # What changed.
    if report.files_changed:
        lines.append(f"  changed: {len(report.files_changed)} file(s)")
    else:
        lines.append(f"  changed: [dim]{ABSENT}[/dim]")

    # What needs the operator's call (an ACT, framed as the operator's).
    lines.append(f"  {_needs_call(report)}")
    if report.has_overrun:
        lines.append(
            "  [red]⚠ the run reports using authority beyond its grant "
            "— see the authority table[/red]"
        )
    for note in report.notes:
        lines.append(f"  [yellow]note:[/yellow] {note}")
    return lines


def _needs_call(report: RunReport) -> str:
    st = (report.promotion_status or "").lower()
    if st == "pending":
        return (
            "needs your call: workspace changes pending — "
            "[dim]diff · keep · discard[/dim]"
        )
    if st == "approved":
        return "you kept the changes  [dim](your act)[/dim]"
    if st == "rejected":
        return "you discarded the changes  [dim](your act)[/dim]"
    if report.files_changed and not report.promotion_status:
        return "needs your call: changes present, no promotion recorded"
    return "nothing pending"


def render_detail(report: RunReport) -> list[str]:
    """Second layer: tool activity (testimony) vs gate refusals (acts), files
    touched, the authority table, and the acceptance criteria rendered
    UNCHECKED for the reviewer to judge."""
    lines: list[str] = []

    lines.append("[bold]tool activity[/bold] [dim](the run's own trace — testimony)[/dim]")
    c = report.tool_counts
    lines.append(
        f"  proposed {c.proposed} · allowed {c.allowed} · "
        f"completed {c.completed} · failed {c.failed}"
    )
    lines.append(
        f"[bold]gate refusals[/bold] [dim](governor acts)[/dim]: {c.denied}"
    )

    lines.append("[bold]files touched[/bold]")
    if report.files_changed:
        for f in report.files_changed:
            lines.append(f"  {f}")
    else:
        lines.append(f"  [dim]{ABSENT}[/dim]")
    if report.excluded_files:
        lines.append(
            f"  [dim]{len(report.excluded_files)} pre-existing path(s) fenced "
            "from this run (not attributed to it)[/dim]"
        )
    if report.diff_stat:
        lines.append(f"  [dim]{report.diff_stat}[/dim]")

    lines.extend(_render_authority(report))

    lines.append("[bold]acceptance criteria[/bold] [dim](unchecked — the reviewer judges)[/dim]")
    if report.acceptance_criteria:
        for crit in report.acceptance_criteria:
            lines.append(f"  [ ] {crit}")
    else:
        lines.append(f"  [dim]{ABSENT}[/dim]")

    if report.receipt_ids:
        lines.append("[bold]receipt refs[/bold] [dim](cited, not minted here)[/dim]")
        for rid in report.receipt_ids:
            lines.append(f"  {rid}")
    return lines


def _render_authority(report: RunReport) -> list[str]:
    lines = ["[bold]authority[/bold] used ≤ granted"]
    if not report.authority:
        lines.append(f"  [dim]{ABSENT}[/dim] [dim](no review packet)[/dim]")
        return lines
    lines.append(
        "  [dim]'used' is the run's own report (testimony); "
        "'granted' is the standing grant (act)[/dim]"
    )
    lines.append(f"  {'axis':<20}{'requested':<11}{'granted':<10}{'used':<8}")
    for row in report.authority:
        marker = "  [red](OVERRUN — beyond grant)[/red]" if row.overrun else ""
        lines.append(
            f"  {row.axis:<20}{_tri(row.requested):<11}{_tri(row.granted):<10}"
            f"{_tri(row.used):<8}{marker}"
        )
    return lines


def _tri(value: bool | None) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return ABSENT


def render_law(report: RunReport) -> list[str]:
    """Deepest layer, one `why` away: the raw ReviewPacket verbatim + the plan
    ref + receipt refs. Nothing summarized — the underlying record itself."""
    import json

    lines: list[str] = ["[bold]LAW — the underlying record, verbatim[/bold]"]
    lines.append(f"  plan_ref: {_shown(report.plan_ref)}")
    if report.review_packet is not None:
        lines.append(f"  review packet: {report.review_packet_path or ABSENT}")
        raw = json.dumps(report.review_packet, indent=2, sort_keys=True)
        lines.extend(f"  {ln}" for ln in raw.splitlines())
    else:
        lines.append(f"  review packet: [dim]{ABSENT}[/dim]")
    if report.receipt_ids:
        lines.append("  receipt refs:")
        lines.extend(f"    {rid}" for rid in report.receipt_ids)
    return lines
