# SPDX-License-Identifier: Apache-2.0
"""Live adapters capability board (GS-10b leg 3c).

Mounts AdaptersScreen with a fake client and checks it renders
``runtime.adapters.list`` honestly — declared capabilities as ✓/✗, per-adapter
errors surfaced verbatim — read-only, no mutation. Compatibility-tested against
the known daemon response shape, not live testimony.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from textual.app import App
from textual.widgets import Static

from maude.screens import AdaptersScreen


class FakeClient:
    def __init__(self, *, result=None, error=None) -> None:
        self._result = result if result is not None else {"adapters": [], "count": 0}
        self._error = error
        self.calls = 0

    async def runtime_adapters_list(self):
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._result


_ADAPTERS = {
    "adapters": [
        {"backend_kind": "claude_code", "capabilities": {
            "supports_pause": True, "supports_resume": True,
            "supports_input_injection": True, "supports_native_tool_hooks": True,
            "supports_structured_events": True, "supports_graceful_shutdown": True}},
        {"backend_kind": "gemini_cli", "capabilities": {
            "supports_pause": False, "supports_resume": False,
            "supports_input_injection": True, "supports_native_tool_hooks": False,
            "supports_structured_events": True, "supports_graceful_shutdown": True}},
    ],
    "count": 2,
}


@asynccontextmanager
async def mounted(screen):
    class _Harness(App):
        async def on_mount(self) -> None:
            await self.push_screen(screen)

    async with _Harness().run_test() as pilot:
        await pilot.pause()
        yield screen, pilot


def _body(screen) -> str:
    return " ".join(str(s.render()) for s in screen.query("#screen-body Static"))


def _status(screen) -> str:
    return str(screen.query_one("#adapters-status", Static).render())


@pytest.mark.asyncio
async def test_refresh_on_mount_lists_adapters():
    client = FakeClient(result=_ADAPTERS)
    async with mounted(AdaptersScreen(client=client)) as (screen, _):
        assert client.calls == 1
        body = _body(screen)
        assert "claude_code" in body
        assert "gemini_cli" in body


@pytest.mark.asyncio
async def test_capabilities_render_honestly_as_checks_and_crosses():
    client = FakeClient(result=_ADAPTERS)
    async with mounted(AdaptersScreen(client=client)) as (screen, _):
        rows = [str(s.render()) for s in screen.query("#screen-body Static")]
        claude_row = next(r for r in rows if "claude_code" in r)
        gemini_row = next(r for r in rows if "gemini_cli" in r)
        # claude supports pause; gemini does not — the board must not lie
        assert "✓ pause" in claude_row
        assert "✗ pause" in gemini_row
        # both support steer (input injection)
        assert "✓ steer" in gemini_row


@pytest.mark.asyncio
async def test_adapter_construction_error_surfaced_verbatim():
    client = FakeClient(result={"adapters": [
        {"backend_kind": "broken", "error": "missing binary"},
    ], "count": 1})
    async with mounted(AdaptersScreen(client=client)) as (screen, _):
        body = _body(screen)
        assert "broken" in body
        assert "unavailable: missing binary" in body


@pytest.mark.asyncio
async def test_empty_state_when_no_adapters():
    client = FakeClient(result={"adapters": [], "count": 0})
    async with mounted(AdaptersScreen(client=client)) as (screen, _):
        assert str(screen.query_one("#screen-empty", Static).render()) == "No adapters reported."


@pytest.mark.asyncio
async def test_error_state_on_failure_does_not_crash():
    client = FakeClient(error=ConnectionRefusedError("no daemon"))
    async with mounted(AdaptersScreen(client=client)) as (screen, _):
        assert "Error:" in _status(screen)
        assert "no daemon" in _status(screen)


@pytest.mark.asyncio
async def test_ctrl_r_refreshes_again():
    client = FakeClient(result=_ADAPTERS)
    async with mounted(AdaptersScreen(client=client)) as (screen, pilot):
        assert client.calls == 1
        await pilot.press("ctrl+r")
        await pilot.pause()
        assert client.calls == 2


@pytest.mark.asyncio
async def test_offline_renders_without_client_or_crash():
    async with mounted(AdaptersScreen()) as (screen, _):
        assert str(screen.query_one("#screen-empty", Static).render()) == "No adapters reported."
