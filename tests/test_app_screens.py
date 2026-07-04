# SPDX-License-Identifier: Apache-2.0
"""Screen-plumbing smokes for the real MaudeApp (GS-10b leg 2).

Drives the actual app through a Textual pilot, offline (the client factory
refuses to connect, so the app mounts degraded). Proves the ScreenManager is
wired behind the existing chat shell without becoming ambient global state, and
that toggling to/from a desk screen preserves the chat shell underneath.

This is *screen plumbing, not authority promotion*: chat stays the default
surface; a desk screen is only ever pushed on top and popped back off.
"""

from __future__ import annotations

import pytest
from textual.widgets import Input, RichLog

from maude.app import MaudeApp
from maude.client.rpc import GovernorClient
from maude.config import Settings
from maude.screens import BoardScreen, QueueScreen, ScreenManager


async def _refuse_connection():
    raise ConnectionRefusedError("no daemon in this test")


def _offline_app() -> MaudeApp:
    client = GovernorClient(socket_path="/tmp/none.sock", client_factory=_refuse_connection)
    return MaudeApp(client=client, settings=Settings())


def test_app_owns_a_screen_manager_and_no_global_state():
    a, b = _offline_app(), _offline_app()
    assert isinstance(a._screen_manager, ScreenManager)
    # Each app owns its own manager — no shared/ambient singleton.
    assert a._screen_manager is not b._screen_manager
    assert a._active_desk_screen is None


@pytest.mark.asyncio
async def test_startup_and_quit_smoke():
    """App mounts and unmounts cleanly with the ScreenManager wired in
    (catches Textual lifecycle collisions like the leg-1 ``_registry`` clash)."""
    app = _offline_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app._active_desk_screen is None
    # Exiting the context unmounts; no exception == lifecycle is clean.


@pytest.mark.asyncio
async def test_ctrl_g_opens_and_closes_the_desk():
    app = _offline_app()
    async with app.run_test() as pilot:
        await pilot.pause()

        await pilot.press("ctrl+g")
        await pilot.pause()
        assert app._active_desk_screen == "queue"
        assert isinstance(app.screen, QueueScreen)

        await pilot.press("ctrl+g")
        await pilot.pause()
        assert app._active_desk_screen is None
        # The chat shell is still there underneath.
        assert app.query_one("#chat-log", RichLog) is not None


@pytest.mark.asyncio
async def test_escape_returns_from_desk_to_chat():
    app = _offline_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+g")
        await pilot.pause()
        assert app._active_desk_screen == "queue"

        await pilot.press("escape")
        await pilot.pause()
        assert app._active_desk_screen is None
        assert app.query_one("#chat-log", RichLog) is not None


@pytest.mark.asyncio
async def test_ctrl_b_opens_and_closes_the_sessions_board():
    app = _offline_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+b")
        await pilot.pause()
        assert app._active_desk_screen == "board"
        assert isinstance(app.screen, BoardScreen)
        await pilot.press("ctrl+b")
        await pilot.pause()
        assert app._active_desk_screen is None
        assert app.query_one("#chat-log", RichLog) is not None


@pytest.mark.asyncio
async def test_switching_between_desks_keeps_chat_reachable():
    app = _offline_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("ctrl+g")   # open queue
        await pilot.pause()
        assert isinstance(app.screen, QueueScreen)

        await pilot.press("ctrl+b")   # switch queue -> board (no chat in between)
        await pilot.pause()
        assert app._active_desk_screen == "board"
        assert isinstance(app.screen, BoardScreen)

        await pilot.press("escape")   # board -> chat
        await pilot.pause()
        assert app._active_desk_screen is None
        assert app.query_one("#chat-log", RichLog) is not None


@pytest.mark.asyncio
async def test_switching_preserves_chat_input_state():
    """Toggling to the desk and back must not lose half-typed input — the chat
    screen stays mounted underneath the pushed desk screen (leg-2 guard)."""
    app = _offline_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one("#input-box", Input).value = "half-typed command"

        await pilot.press("ctrl+g")
        await pilot.pause()
        await pilot.press("ctrl+g")
        await pilot.pause()

        assert app.query_one("#input-box", Input).value == "half-typed command"
