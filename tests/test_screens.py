# SPDX-License-Identifier: Apache-2.0
"""Isolation-mount tests for the desk screens (GS-10).

Each screen must mount on its own (Textual pilot), per the GS-10 test
requirement. Content is skeleton-level; GS-11..GS-14 fill it in.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from textual.app import App
from textual.widgets import Static

from maude.feed import DecisionFeedController
from maude.screens import (
    BoardScreen,
    DiffScreen,
    QueueScreen,
    ReportScreen,
    ScreenManager,
    SessionScreen,
)


@asynccontextmanager
async def mounted(screen):
    """Push ``screen`` onto a throwaway app and yield it once mounted."""

    class _Harness(App):
        async def on_mount(self) -> None:
            await self.push_screen(screen)

    async with _Harness().run_test() as pilot:
        await pilot.pause()
        yield screen


def _text(static: Static) -> str:
    return str(static.render())


def _title(screen) -> str:
    return _text(screen.query_one("#screen-title", Static))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "screen_cls, title, empty",
    [
        (QueueScreen, "QUEUE", "No pending decisions."),
        (SessionScreen, "SESSION", "No session selected."),
        (BoardScreen, "SESSIONS", "No active sessions."),
        (DiffScreen, "DIFF", "No promotion to review."),
        (ReportScreen, "RUN REPORT", "No run report yet. (Composed at M-4.)"),
    ],
)
async def test_screen_mounts_in_isolation(screen_cls, title, empty):
    async with mounted(screen_cls()) as screen:
        assert title in _title(screen)
        assert _text(screen.query_one("#screen-empty", Static)) == empty


@pytest.mark.asyncio
async def test_queue_renders_feed_items_when_present():
    feed = DecisionFeedController()
    feed.apply_snapshot({
        "items": [
            {"decision_id": "d1", "kind": "intervention", "urgency": "blocking",
             "summary": "Bash: rm -rf build/"},
            {"decision_id": "d2", "kind": "promotion", "urgency": "normal",
             "summary": "+214 -12, 6 files"},
        ],
        "feed_seq": 1,
    })
    async with mounted(QueueScreen(feed=feed)) as screen:
        body_text = " ".join(_text(s) for s in screen.query("#screen-body Static"))
        assert "Bash: rm -rf build/" in body_text
        assert "+214 -12, 6 files" in body_text
        # interrupt (blocking) sorts before the accumulated promotion
        assert body_text.index("rm -rf") < body_text.index("+214")


class TestScreenManager:
    def test_registers_the_desk_screens(self):
        mgr = ScreenManager()
        assert mgr.names() == [
            "queue", "session", "board", "diff", "report", "adapters",
        ]

    def test_create_returns_a_screen_instance(self):
        mgr = ScreenManager()
        assert isinstance(mgr.create("queue"), QueueScreen)
        assert isinstance(mgr.create("report"), ReportScreen)

    def test_unknown_screen_raises(self):
        mgr = ScreenManager()
        with pytest.raises(KeyError, match="no screen registered"):
            mgr.create("nope")

    def test_duplicate_registration_raises(self):
        mgr = ScreenManager()
        with pytest.raises(ValueError, match="already registered"):
            mgr.register("queue", QueueScreen)
