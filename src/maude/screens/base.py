# SPDX-License-Identifier: Apache-2.0
"""Shared base for the desk screens (GS-10 skeleton).

Each screen is a Textual :class:`~textual.screen.Screen` with a title and a
body region. GS-11..GS-14 fill the bodies with real content (queue cards,
transcript + receipt rail, board rows, diff). Screens render and drive RPCs;
they carry no authority logic (GS-10 stop condition).
"""

from __future__ import annotations

from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Static


class DeskScreen(Screen):
    """A desk screen: a title line over a body region with an empty state."""

    #: ``escape`` returns to the legacy chat shell (GS-10b leg 2: the desk is
    #: pushed on top of chat, never replaces it). Merged with subclass bindings.
    BINDINGS = [Binding("escape", "close_desk", "Back to chat")]

    #: Logical name used by the ScreenManager registry.
    SCREEN_NAME: str = "desk"
    #: Title shown at the top of the screen.
    TITLE_TEXT: str = "Desk"
    #: Message shown when the body has nothing to render yet.
    EMPTY_TEXT: str = ""
    #: A subclass that renders its own body (e.g. the live QueueScreen) sets this
    #: so the skeleton ``on_mount`` below stands down. Textual dispatches
    #: ``on_mount`` for *every* class in the MRO, so the base must yield
    #: explicitly rather than rely on being overridden.
    _MANAGES_OWN_BODY: bool = False

    async def action_close_desk(self) -> None:
        """Pop back to the legacy chat shell, if the host app supports it."""
        close = getattr(self.app, "close_desk", None)
        if close is not None:
            await close()

    def compose(self):
        yield Static(self.TITLE_TEXT, id="screen-title")
        yield Vertical(id="screen-body")

    def on_mount(self) -> None:
        if self._MANAGES_OWN_BODY:
            return
        body = self.query_one("#screen-body", Vertical)
        rows = list(self.body_lines())
        if rows:
            for line in rows:
                body.mount(Static(line))
        else:
            body.mount(Static(self.EMPTY_TEXT, id="screen-empty"))

    def body_lines(self) -> list[str]:
        """Lines to render in the body. Empty → the screen's empty state.

        Overridden by screens that have content to show at the skeleton stage
        (e.g. the queue). GS-11..GS-14 replace these with real widgets."""
        return []
