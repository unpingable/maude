# SPDX-License-Identifier: Apache-2.0
"""S4c — the `grant [session_id]` diagnostic command + its intent."""

from __future__ import annotations

import asyncio

from maude.commands.base import CommandContext
from maude.commands.grant import GrantStatusCommand
from maude.intents import IntentKind, parse_intent


class FakeLog:
    def __init__(self):
        self.lines: list[str] = []

    def write(self, s: object = "") -> None:
        self.lines.append(str(s))

    def text(self) -> str:
        return "\n".join(self.lines)


class FakeClient:
    def __init__(self, grant):
        self._grant = grant
        self.calls: list[str] = []

    async def runtime_grant_get(self, session_id):
        self.calls.append(session_id)
        return self._grant


class FakeApp:
    def __init__(self, grant, active=None):
        self.client = FakeClient(grant)
        self._active_supervised_session = active


def _run(cmd, app, log, payload):
    asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
        cmd.execute(CommandContext(app=app, log=log, text=payload), payload)
    )


_ACTIVE_GRANT = {
    "grant_id": "sgr_abc123",
    "enforcement": "declared-effects-only",
    "state": "active",
    "horizon": "run",
    "expires_after_ns": None,
    "write_paths": ["crates/nightshiftd/src/**"],
    "commands": [{"program": "cargo", "argv_prefix": ["test"]}],
    "recent_uses": [
        {"disposition": "accepted"}, {"disposition": "accepted"},
        {"disposition": "widens", "axis": "write_path"},
    ],
}


def test_intent_grant_with_session():
    i = parse_intent("grant sess-1")
    assert i.kind == IntentKind.GRANT_STATUS and i.payload == "sess-1"


def test_intent_grant_bare():
    assert parse_intent("grant").kind == IntentKind.GRANT_STATUS


def test_render_active_grant():
    app, log = FakeApp(_ACTIVE_GRANT), FakeLog()
    _run(GrantStatusCommand(), app, log, "sess-1")
    out = log.text()
    assert "sgr_abc123" in out and "active" in out
    assert "cargo test" in out and "crates/nightshiftd/src/**" in out
    assert "accepted×2" in out and "widens:write_path×1" in out
    assert app.client.calls == ["sess-1"]


def test_render_revoked_grant():
    grant = dict(_ACTIVE_GRANT, state="revoked", revoked_reason="operator pulled it")
    app, log = FakeApp(grant), FakeLog()
    _run(GrantStatusCommand(), app, log, "sess-1")
    out = log.text()
    assert "revoked" in out and "operator pulled it" in out


def test_no_grant_attached():
    app, log = FakeApp(None), FakeLog()
    _run(GrantStatusCommand(), app, log, "sess-1")
    assert "no execution grant" in log.text()


def test_bare_grant_uses_active_session():
    app, log = FakeApp(_ACTIVE_GRANT, active="sess-live"), FakeLog()
    _run(GrantStatusCommand(), app, log, "grant")
    assert app.client.calls == ["sess-live"]


def test_bare_grant_without_active_session_shows_usage():
    app, log = FakeApp(_ACTIVE_GRANT, active=None), FakeLog()
    _run(GrantStatusCommand(), app, log, "grant")
    assert "Usage:" in log.text() and app.client.calls == []
