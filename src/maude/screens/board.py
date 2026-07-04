# SPDX-License-Identifier: Apache-2.0
"""Sessions board — the status board (GS-10b leg 3b; GS-12 enriches it).

Renders the supervised sessions the daemon already exposes via
``runtime.session.list``: one row per session with its status, pending-decision
count, and task, with **waiting-on-you sorted to the top** (loop-ux §2). Refresh
is explicit (``ctrl+r`` + on open), with empty / loading / error states.

Boundary: this is a *status board, not a diagnosis engine*. It renders the
payload verbatim — status strings as-is, pending counts as-is — and adds no
health/obstruction verdict of its own. It reads no new daemon fields, resolves
nothing, and mints no authority. Steering / session drill-in / budget bars are
GS-12; the live ``operator.watch`` loop stays deferred (explicit refresh).
"""

from __future__ import annotations

from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Static

from maude.screens.base import DeskScreen

#: A glyph per known status — a visual echo of the payload's own ``status``
#: field, never a derived judgement. Unknown statuses fall back to ``•`` and the
#: raw string is always shown alongside, so nothing is hidden or invented.
_STATUS_GLYPH = {
    "running": "▶",
    "waiting_tool_decision": "⏸",
    "paused": "⏸",
    "completed": "✓",
    "exited": "✓",
    "failed": "✗",
    "killed": "✗",
}


class BoardScreen(DeskScreen):
    SCREEN_NAME = "board"
    TITLE_TEXT = "SESSIONS"
    EMPTY_TEXT = "No active sessions."
    #: Renders its own body — the base skeleton on_mount stands down.
    _MANAGES_OWN_BODY = True

    BINDINGS = [Binding("ctrl+r", "refresh_board", "Refresh")]

    _HINT = "[dim]ctrl+r refresh · esc back[/dim]"

    def __init__(self, client=None) -> None:
        super().__init__()
        self._client = client
        self._sessions: list[dict] = []
        self._status = "idle"  # idle | loading | error
        self._error: str | None = None

    # -- layout ------------------------------------------------------------- #

    def compose(self):
        yield Static(self.TITLE_TEXT, id="screen-title")
        yield Vertical(id="screen-body")
        yield Static("", id="board-status")

    async def on_mount(self) -> None:
        if self._client is not None:
            await self._do_refresh()
        else:
            await self._rebuild()

    # -- ordering ----------------------------------------------------------- #

    @staticmethod
    def _waiting(session: dict) -> bool:
        """Whether this session is waiting on the operator — read straight from
        the payload (pending interventions or an explicit wait status)."""
        return bool(session.get("pending_interventions")) or (
            session.get("status") == "waiting_tool_decision"
        )

    def _ordered(self) -> list[dict]:
        # Stable sort: waiting-on-you first, daemon order preserved within groups.
        return sorted(self._sessions, key=lambda s: 0 if self._waiting(s) else 1)

    # -- rendering ---------------------------------------------------------- #

    async def _rebuild(self) -> None:
        body = self.query_one("#screen-body", Vertical)
        await body.remove_children()
        ordered = self._ordered()
        if not ordered:
            await body.mount(Static(self.EMPTY_TEXT, id="screen-empty"))
        else:
            await body.mount(*[Static(self._row(s)) for s in ordered])
        self._update_status()

    def _row(self, s: dict) -> str:
        sid = str(s.get("session_id", "?"))[:8]
        status = str(s.get("status", "?"))
        glyph = _STATUS_GLYPH.get(status, "•")
        pending = s.get("pending_interventions") or 0
        pending_str = f"  [yellow][{pending} pending][/yellow]" if pending else ""
        task = (s.get("task") or "")[:40]
        return f"{glyph} {sid}  {status}{pending_str}  {task}"

    def _update_status(self) -> None:
        status = self.query_one("#board-status", Static)
        if self._status == "loading":
            status.update("Loading…")
            return
        if self._status == "error":
            status.update(f"[red]Error:[/red] {self._error}   {self._HINT}")
            return
        n = len(self._sessions)
        waiting = sum(1 for s in self._sessions if self._waiting(s))
        summary = f"[dim]{n} session(s)"
        if waiting:
            summary += f", [yellow]{waiting} waiting on you[/yellow][dim]"
        status.update(f"{summary} · ctrl+r refresh · esc back[/dim]")

    # -- refresh ------------------------------------------------------------ #

    async def action_refresh_board(self) -> None:
        await self._do_refresh()

    async def _do_refresh(self) -> None:
        """Explicit refresh via ``runtime.session.list`` (loading→data|error)."""
        if self._client is None:
            return
        self._status = "loading"
        self._update_status()
        try:
            sessions = await self._client.runtime_session_list()
            self._sessions = list(sessions or [])
            self._status = "idle"
            self._error = None
        except Exception as e:  # noqa: BLE001 — surface any RPC failure as state
            self._status = "error"
            self._error = str(e)
        await self._rebuild()
