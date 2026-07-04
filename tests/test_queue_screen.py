# SPDX-License-Identifier: Apache-2.0
"""Live decisions/queue screen (GS-10b leg 3a).

Mounts QueueScreen in a throwaway Textual app with a fake client and exercises
the real desk surface: explicit refresh, empty/loading/error states, cursor
selection, and operator-triggered resolve. The load-bearing pin is that resolve
relays ONLY the chosen ``option_key`` (from the envelope) to
``operator.decisions.resolve`` — the screen decides nothing and never resolves
in the background.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from textual.app import App
from textual.widgets import Static

from maude.feed import DecisionFeedController
from maude.screens import QueueScreen


class FakeClient:
    """Records calls; returns a canned decisions.list snapshot."""

    def __init__(self, *, snapshot=None, list_error=None, resolve_error=None) -> None:
        self._snapshot = snapshot or {"items": [], "count": 0}
        self._list_error = list_error
        self._resolve_error = resolve_error
        self.list_calls = 0
        self.resolve_calls: list[tuple[str, str]] = []

    async def operator_decisions_list(self, kinds=None):
        self.list_calls += 1
        if self._list_error is not None:
            raise self._list_error
        return self._snapshot

    async def operator_decisions_resolve(self, decision_id, option_key, args=None):
        self.resolve_calls.append((decision_id, option_key))
        if self._resolve_error is not None:
            raise self._resolve_error
        return {"resolved": True}


_TWO_ITEMS = {
    "items": [
        {"decision_id": "d1", "kind": "intervention", "urgency": "blocking",
         "summary": "Bash: rm -rf build/",
         "options": [{"key": "y", "label": "approve", "action": "approve"},
                     {"key": "n", "label": "deny", "action": "deny"}]},
        {"decision_id": "d2", "kind": "promotion", "urgency": "normal",
         "summary": "+214 -12, 6 files",
         "options": [{"key": "p", "label": "promote", "action": "promote"}]},
    ],
    "count": 2,
    "feed_seq": 1,
}


@asynccontextmanager
async def mounted(screen):
    class _Harness(App):
        async def on_mount(self) -> None:
            await self.push_screen(screen)

    async with _Harness().run_test() as pilot:
        await pilot.pause()
        yield screen, pilot


def _body_text(screen) -> str:
    return " ".join(str(s.render()) for s in screen.query("#screen-body Static"))


def _status_text(screen) -> str:
    return str(screen.query_one("#queue-status", Static).render())


@pytest.mark.asyncio
async def test_refresh_on_mount_populates_from_client():
    client = FakeClient(snapshot=_TWO_ITEMS)
    async with mounted(QueueScreen(client=client)) as (screen, _):
        assert client.list_calls == 1  # auto-refresh on open
        body = _body_text(screen)
        assert "Bash: rm -rf build/" in body
        assert "+214 -12, 6 files" in body
        # interrupt (blocking) sorts before the accumulated promotion
        assert body.index("rm -rf") < body.index("+214")


@pytest.mark.asyncio
async def test_empty_state_when_no_items():
    client = FakeClient(snapshot={"items": [], "count": 0})
    async with mounted(QueueScreen(client=client)) as (screen, _):
        assert str(screen.query_one("#screen-empty", Static).render()) == "No pending decisions."


@pytest.mark.asyncio
async def test_error_state_on_list_failure_does_not_crash():
    client = FakeClient(list_error=ConnectionRefusedError("no daemon"))
    async with mounted(QueueScreen(client=client)) as (screen, _):
        assert "Error:" in _status_text(screen)
        assert "no daemon" in _status_text(screen)


@pytest.mark.asyncio
async def test_ctrl_r_refreshes_again():
    client = FakeClient(snapshot=_TWO_ITEMS)
    async with mounted(QueueScreen(client=client)) as (screen, pilot):
        assert client.list_calls == 1
        await pilot.press("ctrl+r")
        await pilot.pause()
        assert client.list_calls == 2


@pytest.mark.asyncio
async def test_down_moves_selection_and_shows_its_keymap():
    client = FakeClient(snapshot=_TWO_ITEMS)
    async with mounted(QueueScreen(client=client)) as (screen, pilot):
        # d1 selected first — its keys y/n are in the status line
        assert "approve" in _status_text(screen) and "deny" in _status_text(screen)
        await pilot.press("down")
        await pilot.pause()
        assert screen._selected == 1
        # d2 selected now — its promote key shows, y/n gone
        assert "promote" in _status_text(screen)
        assert "approve" not in _status_text(screen)


@pytest.mark.asyncio
async def test_resolve_relays_selected_option_key_only():
    client = FakeClient(snapshot=_TWO_ITEMS)
    async with mounted(QueueScreen(client=client)) as (screen, pilot):
        # d1 is selected; 'y' is one of its option keys → relay it, nothing else
        await pilot.press("y")
        await pilot.pause()
        assert client.resolve_calls == [("d1", "y")]
        # a resolve triggers a follow-up refresh (list called again)
        assert client.list_calls == 2


@pytest.mark.asyncio
async def test_resolve_uses_the_selected_items_key_after_navigation():
    client = FakeClient(snapshot=_TWO_ITEMS)
    async with mounted(QueueScreen(client=client)) as (screen, pilot):
        await pilot.press("down")   # select d2
        await pilot.pause()
        await pilot.press("p")      # d2's promote key
        await pilot.pause()
        assert client.resolve_calls == [("d2", "p")]


@pytest.mark.asyncio
async def test_key_not_in_selected_keymap_is_ignored():
    client = FakeClient(snapshot=_TWO_ITEMS)
    async with mounted(QueueScreen(client=client)) as (screen, pilot):
        # 'p' belongs to d2, not the selected d1 → no resolve
        await pilot.press("p")
        await pilot.pause()
        assert client.resolve_calls == []


@pytest.mark.asyncio
async def test_resolve_failure_surfaces_error_without_crash():
    client = FakeClient(snapshot=_TWO_ITEMS, resolve_error=RuntimeError("gate refused"))
    async with mounted(QueueScreen(client=client)) as (screen, pilot):
        await pilot.press("y")
        await pilot.pause()
        assert client.resolve_calls == [("d1", "y")]
        assert "gate refused" in _status_text(screen)


@pytest.mark.asyncio
async def test_offline_screen_renders_existing_feed_without_client():
    """No client → no auto-refresh, no crash; renders whatever the feed holds."""
    feed = DecisionFeedController()
    feed.apply_snapshot(_TWO_ITEMS)
    async with mounted(QueueScreen(feed=feed)) as (screen, pilot):
        assert "Bash: rm -rf build/" in _body_text(screen)
        # pressing an option key offline must not crash and issues no RPC
        await pilot.press("y")
        await pilot.pause()
        assert "cannot resolve" in _status_text(screen)
