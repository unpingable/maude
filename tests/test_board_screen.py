# SPDX-License-Identifier: Apache-2.0
"""Live sessions/watch status board (GS-10b leg 3b).

Mounts BoardScreen in a throwaway Textual app with a fake client and exercises
the read-only status board: explicit refresh, empty/loading/error states, and
waiting-on-you sorted to the top. The board renders the ``runtime.session.list``
payload verbatim and issues no mutations — no resolve, no new fields, no verdict.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from textual.app import App
from textual.widgets import Static

from maude.screens import BoardScreen


class FakeClient:
    def __init__(self, *, sessions=None, error=None) -> None:
        self._sessions = sessions if sessions is not None else []
        self._error = error
        self.list_calls = 0

    async def runtime_session_list(self):
        self.list_calls += 1
        if self._error is not None:
            raise self._error
        return self._sessions


_SESSIONS = [
    {"session_id": "aaaaaaaa1", "status": "running", "task": "refactor parser",
     "pending_interventions": 0},
    {"session_id": "bbbbbbbb2", "status": "waiting_tool_decision",
     "task": "write migration", "pending_interventions": 2},
    {"session_id": "cccccccc3", "status": "running", "task": "add tests",
     "pending_interventions": 0},
]


@asynccontextmanager
async def mounted(screen):
    class _Harness(App):
        async def on_mount(self) -> None:
            await self.push_screen(screen)

    async with _Harness().run_test() as pilot:
        await pilot.pause()
        yield screen, pilot


def _body_lines(screen) -> list[str]:
    return [str(s.render()) for s in screen.query("#screen-body Static")]


def _status_text(screen) -> str:
    return str(screen.query_one("#board-status", Static).render())


@pytest.mark.asyncio
async def test_refresh_on_mount_populates_from_client():
    client = FakeClient(sessions=_SESSIONS)
    async with mounted(BoardScreen(client=client)) as (screen, _):
        assert client.list_calls == 1
        body = " ".join(_body_lines(screen))
        assert "refactor parser" in body
        assert "write migration" in body
        assert "add tests" in body


@pytest.mark.asyncio
async def test_waiting_on_you_sorts_to_the_top():
    client = FakeClient(sessions=_SESSIONS)
    async with mounted(BoardScreen(client=client)) as (screen, _):
        lines = _body_lines(screen)
        # bbbbbbbb2 has 2 pending → its row is first despite being 2nd in payload
        assert "write migration" in lines[0]
        assert "[2 pending]" in lines[0]


@pytest.mark.asyncio
async def test_empty_state_when_no_sessions():
    client = FakeClient(sessions=[])
    async with mounted(BoardScreen(client=client)) as (screen, _):
        assert str(screen.query_one("#screen-empty", Static).render()) == "No active sessions."


@pytest.mark.asyncio
async def test_error_state_on_failure_does_not_crash():
    client = FakeClient(error=ConnectionRefusedError("no daemon"))
    async with mounted(BoardScreen(client=client)) as (screen, _):
        assert "Error:" in _status_text(screen)
        assert "no daemon" in _status_text(screen)


@pytest.mark.asyncio
async def test_ctrl_r_refreshes_again():
    client = FakeClient(sessions=_SESSIONS)
    async with mounted(BoardScreen(client=client)) as (screen, pilot):
        assert client.list_calls == 1
        await pilot.press("ctrl+r")
        await pilot.pause()
        assert client.list_calls == 2


@pytest.mark.asyncio
async def test_status_summary_counts_waiting():
    client = FakeClient(sessions=_SESSIONS)
    async with mounted(BoardScreen(client=client)) as (screen, _):
        text = _status_text(screen)
        assert "3 session(s)" in text
        assert "1 waiting on you" in text


@pytest.mark.asyncio
async def test_unknown_status_renders_raw_without_crash():
    client = FakeClient(sessions=[
        {"session_id": "zzzzzzzz9", "status": "some_new_status", "task": "x",
         "pending_interventions": 0},
    ])
    async with mounted(BoardScreen(client=client)) as (screen, _):
        assert "some_new_status" in " ".join(_body_lines(screen))


@pytest.mark.asyncio
async def test_offline_board_renders_without_client_or_crash():
    async with mounted(BoardScreen()) as (screen, _):
        assert str(screen.query_one("#screen-empty", Static).render()) == "No active sessions."
