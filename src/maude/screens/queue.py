# SPDX-License-Identifier: Apache-2.0
"""Queue home — "the desk" (GS-10b leg 3a: the first live desk surface).

Renders the unified decision feed from a :class:`~maude.feed.DecisionFeedController`
and drives it through the GS-11 data layer:

  * **refresh** — ``ctrl+r`` (and on open) calls ``operator.decisions.list`` and
    replaces the feed snapshot; empty / loading / error states are explicit;
  * **select** — ``↑`` / ``↓`` move a cursor over the ordered feed (interrupts
    first, then the accumulated rest);
  * **resolve** — pressing one of the *selected* item's option keys relays that
    ``option_key`` to ``operator.decisions.resolve``. The keymap comes straight
    from the envelope's ``options[].key`` — no shell-invented verbs.

Boundary (unchanged from the skeleton): this screen renders and relays. Every
resolve is a direct operator keystroke — no autopilot, no background/implicit
resolution. Maude mints no authority; the daemon decides and mints the receipt.
The live ``operator.watch`` subscribe/re-subscribe loop stays deferred (GS-11);
this surface refreshes explicitly.
"""

from __future__ import annotations

from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Static

from ag_shell_client import DecisionItem
from maude.feed import DecisionFeedController
from maude.screens.base import DeskScreen


class QueueScreen(DeskScreen):
    SCREEN_NAME = "queue"
    TITLE_TEXT = "QUEUE"
    EMPTY_TEXT = "No pending decisions."
    #: This screen renders its own body (rows + status line); the base skeleton
    #: on_mount must stand down (Textual runs both — see DeskScreen).
    _MANAGES_OWN_BODY = True

    #: Navigation + refresh. Merged with DeskScreen's ``escape`` (back to chat).
    #: Resolve keys are dynamic (from the envelope) so they live in ``on_key``.
    BINDINGS = [
        Binding("up", "cursor_up", "Up", show=False),
        Binding("down", "cursor_down", "Down", show=False),
        Binding("ctrl+r", "refresh_feed", "Refresh"),
    ]

    _HINT = "[dim]↑/↓ select · ctrl+r refresh · esc back[/dim]"

    def __init__(
        self,
        feed: DecisionFeedController | None = None,
        client=None,
    ) -> None:
        super().__init__()
        self._feed = feed or DecisionFeedController()
        self._client = client
        self._selected = 0
        self._status = "idle"  # idle | loading | error
        self._error: str | None = None

    @property
    def feed(self) -> DecisionFeedController:
        return self._feed

    # -- layout ------------------------------------------------------------- #

    def compose(self):
        yield Static(self.TITLE_TEXT, id="screen-title")
        yield Vertical(id="screen-body")
        # Status/keymap line lives OUTSIDE #screen-body so it never mingles with
        # the decision rows (queried by `#screen-body Static`).
        yield Static("", id="queue-status")

    async def on_mount(self) -> None:
        # With a client, refresh (which renders); offline, render the cache once.
        # A single render path avoids racing two mounts of the same-id widget.
        if self._client is not None:
            await self._do_refresh()
        else:
            await self._rebuild()

    # -- ordering / selection ---------------------------------------------- #

    def _ordered(self) -> list[DecisionItem]:
        # Obligations before ambitions: interrupts (blocking/expiring) first,
        # then the accumulated rest (D-GS-1 queue-first ordering).
        return self._feed.interrupts() + self._feed.accumulated()

    def _selected_item(self) -> DecisionItem | None:
        ordered = self._ordered()
        if not ordered:
            return None
        self._selected = max(0, min(self._selected, len(ordered) - 1))
        return ordered[self._selected]

    # -- rendering ---------------------------------------------------------- #

    async def _rebuild(self) -> None:
        body = self.query_one("#screen-body", Vertical)
        await body.remove_children()
        ordered = self._ordered()
        if not ordered:
            await body.mount(Static(self.EMPTY_TEXT, id="screen-empty"))
        else:
            if self._selected >= len(ordered):
                self._selected = len(ordered) - 1
            rows = []
            for idx, item in enumerate(ordered):
                marker = "▶ " if idx == self._selected else "  "
                rows.append(Static(f"{marker}[{item.urgency}] {item.kind}  {item.summary}"))
            await body.mount(*rows)
        self._update_status()

    def _update_status(self) -> None:
        status = self.query_one("#queue-status", Static)
        if self._status == "loading":
            status.update("Loading…")
            return
        if self._status == "error":
            status.update(f"[red]Error:[/red] {self._error}   {self._HINT}")
            return
        item = self._selected_item()
        if item is None:
            status.update(self._HINT)
            return
        keymap = self._feed.keymap_for(item)
        if keymap:
            keys = "  ".join(f"[b]{k}[/b] {opt.label}" for k, opt in keymap.items())
        else:
            keys = "[dim](no options)[/dim]"
        status.update(f"{keys}   {self._HINT}")

    # -- actions ------------------------------------------------------------ #

    async def action_cursor_down(self) -> None:
        ordered = self._ordered()
        if ordered:
            self._selected = min(self._selected + 1, len(ordered) - 1)
            await self._rebuild()

    async def action_cursor_up(self) -> None:
        if self._selected > 0:
            self._selected -= 1
            await self._rebuild()

    async def action_refresh_feed(self) -> None:
        await self._do_refresh()

    async def _do_refresh(self) -> None:
        """Explicit refresh via ``operator.decisions.list`` (loading→data|error)."""
        if self._client is None:
            return
        self._status = "loading"
        self._update_status()
        try:
            result = await self._client.operator_decisions_list()
            self._feed.apply_snapshot(result)
            self._status = "idle"
            self._error = None
        except Exception as e:  # noqa: BLE001 — surface any RPC failure as state
            self._status = "error"
            self._error = str(e)
        await self._rebuild()

    async def on_key(self, event) -> None:
        # Dynamic resolve: a single-char key that is one of the *selected* item's
        # option keys relays that option to the daemon. Multi-char keys
        # (up/down/escape/ctrl+r) are handled by BINDINGS, so we skip them.
        if len(event.key) != 1:
            return
        item = self._selected_item()
        if item is None:
            return
        if event.key in self._feed.keymap_for(item):
            event.stop()
            await self._resolve(item, event.key)

    async def _resolve(self, item: DecisionItem, key: str) -> None:
        """Relay the operator's chosen ``option_key`` to the daemon. Decides
        nothing — the daemon routes, applies any refusal, mints the receipt."""
        if self._client is None:
            self._status = "error"
            self._error = "offline — cannot resolve"
            self._update_status()
            return
        try:
            await self._client.operator_decisions_resolve(item.decision_id, key)
        except Exception as e:  # noqa: BLE001 — surface RPC failure as state
            self._status = "error"
            self._error = f"resolve failed: {e}"
            self._update_status()
            return
        await self._do_refresh()
