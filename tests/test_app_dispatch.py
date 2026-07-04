# SPDX-License-Identifier: Apache-2.0
"""End-to-end dispatch smoke for the real MaudeApp (GS-10b leg 1).

Drives the actual ``on_input_submitted`` → CommandRegistry → AppCommand → app
handler path via a Textual pilot, offline (the client factory refuses to
connect, so the app mounts degraded — enough to exercise dispatch). This is the
behavior-preservation evidence for replacing the if/elif with the registry;
app.py otherwise has no tests.
"""

from __future__ import annotations

import pytest
from textual.widgets import Input

from maude.app import MaudeApp
from maude.client.rpc import GovernorClient
from maude.config import Settings


async def _refuse_connection():
    raise ConnectionRefusedError("no daemon in this test")


def _offline_app() -> MaudeApp:
    client = GovernorClient(socket_path="/tmp/none.sock", client_factory=_refuse_connection)
    return MaudeApp(client=client, settings=Settings())


async def _submit(pilot, app, text: str) -> None:
    inp = app.query_one("#input-box", Input)
    inp.focus()
    await pilot.pause()
    inp.value = text
    await pilot.press("enter")
    await pilot.pause()


@pytest.mark.asyncio
async def test_help_dispatches_through_registry():
    app = _offline_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        called = {}
        app._handle_help = lambda log: called.setdefault("help", True)
        await _submit(pilot, app, "help")
        assert called.get("help") is True


@pytest.mark.asyncio
async def test_payload_intent_passes_payload():
    app = _offline_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        seen = {}

        async def fake_events(log, payload):
            seen["payload"] = payload

        app._handle_supervised_events = fake_events
        await _submit(pilot, app, "supervised events sess_42")
        assert seen.get("payload") == "sess_42"


@pytest.mark.asyncio
async def test_unmatched_text_routes_to_chat_with_raw_text():
    app = _offline_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        seen = {}

        async def fake_chat(log, text):
            seen["text"] = text

        app._handle_chat = fake_chat
        await _submit(pilot, app, "explain decorators please")
        assert seen.get("text") == "explain decorators please"


@pytest.mark.asyncio
async def test_empty_input_dispatches_nothing():
    app = _offline_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        fired = {"n": 0}
        app._handle_help = lambda log: fired.__setitem__("n", fired["n"] + 1)
        await _submit(pilot, app, "")
        assert fired["n"] == 0


class _RecordingLog:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def write(self, s: object) -> None:
        self.lines.append(str(s))


@pytest.mark.asyncio
async def test_why_law_view_discloses_blocked_plan():
    """V2 law view: after a blocked plan run, `why` shows the plain surface AND
    discloses the raw contract code (which the block output itself hides)."""
    from maude.labels import refusal_explanation

    app = _offline_app()
    exp = refusal_explanation("governance_not_approved")
    app._last_plan_block = ("governance_not_approved", "detail prose", exp)
    log = _RecordingLog()
    await app._handle_why(log)
    text = "\n".join(log.lines)
    assert "Not approved" in text  # plain-ops surface, first
    assert "governance_not_approved" in text  # cybernetics disclosed on drilldown
