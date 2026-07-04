# SPDX-License-Identifier: Apache-2.0
"""Adapters view — the honest capability board (GS-10b leg 3c).

Displays ``runtime.adapters.list`` read-only: one row per backend with the
capabilities it *declares* it supports (pause / resume / steer / tool-hooks /
structured-events / graceful-stop), shown as ✓/✗. This is the surface the daemon
added the read for — "let a shell show what can be launched and which controls
each backend honestly supports (truth, not aspiration)" — so the operator sees
degradation honestly (a backend that can't pause shows ✗ pause, not a lie).

Boundary: introspection only. Adapters are AG's, below the authority gate; this
screen selects nothing, configures nothing, launches nothing (harness *selection*
is M-3; adapter *config* never lives in Maude). Read-only display, explicit
refresh, no mutation. Compatibility-tested against the known daemon response
shape (``{adapters: [{backend_kind, capabilities|error}], count}``), not live
testimony.
"""

from __future__ import annotations

from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Static

from maude.screens.base import DeskScreen

#: Declared-capability keys → short labels, in operator-loop order (the controls
#: an operator reaches for first). Mirrors AdapterCapabilities on the daemon.
_CAPABILITY_LABELS = [
    ("supports_pause", "pause"),
    ("supports_resume", "resume"),
    ("supports_input_injection", "steer"),
    ("supports_native_tool_hooks", "tool-hooks"),
    ("supports_structured_events", "events"),
    ("supports_graceful_shutdown", "graceful-stop"),
]


class AdaptersScreen(DeskScreen):
    SCREEN_NAME = "adapters"
    TITLE_TEXT = "ADAPTERS"
    EMPTY_TEXT = "No adapters reported."
    #: Renders its own body — the base skeleton on_mount stands down.
    _MANAGES_OWN_BODY = True

    BINDINGS = [Binding("ctrl+r", "refresh_adapters", "Refresh")]

    _HINT = "[dim]ctrl+r refresh · esc back[/dim]"

    def __init__(self, client=None) -> None:
        super().__init__()
        self._client = client
        self._adapters: list[dict] = []
        self._status = "idle"  # idle | loading | error
        self._error: str | None = None

    # -- layout ------------------------------------------------------------- #

    def compose(self):
        yield Static(self.TITLE_TEXT, id="screen-title")
        yield Vertical(id="screen-body")
        yield Static("", id="adapters-status")

    async def on_mount(self) -> None:
        if self._client is not None:
            await self._do_refresh()
        else:
            await self._rebuild()

    # -- rendering ---------------------------------------------------------- #

    async def _rebuild(self) -> None:
        body = self.query_one("#screen-body", Vertical)
        await body.remove_children()
        if not self._adapters:
            await body.mount(Static(self.EMPTY_TEXT, id="screen-empty"))
        else:
            await body.mount(*[Static(self._row(a)) for a in self._adapters])
        self._update_status()

    def _row(self, adapter: dict) -> str:
        kind = str(adapter.get("backend_kind", "?"))
        # A construction failure is reported per-adapter, not raised — surface it
        # verbatim so an unavailable backend is visible, not silently dropped.
        if "error" in adapter:
            return f"[b]{kind}[/b]   [red]unavailable: {adapter['error']}[/red]"
        caps = adapter.get("capabilities") or {}
        marks = []
        for key, label in _CAPABILITY_LABELS:
            if caps.get(key):
                marks.append(f"[green]✓ {label}[/green]")
            else:
                marks.append(f"[dim]✗ {label}[/dim]")
        return f"[b]{kind}[/b]   " + "  ".join(marks)

    def _update_status(self) -> None:
        status = self.query_one("#adapters-status", Static)
        if self._status == "loading":
            status.update("Loading…")
            return
        if self._status == "error":
            status.update(f"[red]Error:[/red] {self._error}   {self._HINT}")
            return
        n = len(self._adapters)
        status.update(f"[dim]{n} adapter(s) · ctrl+r refresh · esc back[/dim]")

    # -- refresh ------------------------------------------------------------ #

    async def action_refresh_adapters(self) -> None:
        await self._do_refresh()

    async def _do_refresh(self) -> None:
        """Explicit refresh via ``runtime.adapters.list`` (loading→data|error)."""
        if self._client is None:
            return
        self._status = "loading"
        self._update_status()
        try:
            result = await self._client.runtime_adapters_list()
            self._adapters = list((result or {}).get("adapters") or [])
            self._status = "idle"
            self._error = None
        except Exception as e:  # noqa: BLE001 — surface any RPC failure as state
            self._status = "error"
            self._error = str(e)
        await self._rebuild()
