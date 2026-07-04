# SPDX-License-Identifier: Apache-2.0
"""Tests for the governed-shell operator client surface (GS-11 data layer).

Covers the operator.* / runtime.adapters.list / why.chain / send_input methods
maude's desk consumes, plus the operator.watch snapshot-streaming path — all
against an injected fake AsyncDaemonClient."""

from __future__ import annotations

import pytest

from ag_shell_client import StreamItem

from maude.client.rpc import GovernorClient
from maude.feed import DecisionFeedController


class FakeDaemonClient:
    def __init__(self, *, result=None, stream_items=None) -> None:
        self.result = result
        self.stream_items = stream_items or []
        self.calls: list[tuple[str, dict | None]] = []
        self.closed = False

    async def call(self, method, params=None, *, timeout=None):
        self.calls.append((method, params))
        return self.result

    async def stream(self, method, params=None, *, read_timeout=None):
        self.calls.append((method, params))
        for item in self.stream_items:
            yield item

    async def aclose(self):
        self.closed = True


def factory_for(*clients):
    seq = list(clients)
    state = {"i": 0}

    async def _factory():
        i = min(state["i"], len(seq) - 1)
        state["i"] += 1
        return seq[i]

    return _factory


def _client(fake):
    return GovernorClient(socket_path="/tmp/x.sock", client_factory=factory_for(fake))


class TestUnaryOperatorMethods:
    @pytest.mark.asyncio
    async def test_decisions_list_no_kinds(self):
        fake = FakeDaemonClient(result={"items": [], "count": 0})
        result = await _client(fake).operator_decisions_list()
        assert fake.calls == [("operator.decisions.list", {})]
        assert result["count"] == 0

    @pytest.mark.asyncio
    async def test_decisions_list_with_kinds(self):
        fake = FakeDaemonClient(result={"items": [], "count": 0})
        await _client(fake).operator_decisions_list(kinds=["intervention", "promotion"])
        assert fake.calls == [
            ("operator.decisions.list", {"kinds": ["intervention", "promotion"]})
        ]

    @pytest.mark.asyncio
    async def test_decisions_resolve_relays_option_key(self):
        fake = FakeDaemonClient(result={"resolved": True})
        await _client(fake).operator_decisions_resolve("dec_1", "y")
        assert fake.calls == [
            ("operator.decisions.resolve", {"decision_id": "dec_1", "option_key": "y"})
        ]

    @pytest.mark.asyncio
    async def test_decisions_resolve_with_args(self):
        fake = FakeDaemonClient(result={"resolved": True})
        await _client(fake).operator_decisions_resolve("dec_1", "f", args={"note": "x"})
        assert fake.calls == [(
            "operator.decisions.resolve",
            {"decision_id": "dec_1", "option_key": "f", "args": {"note": "x"}},
        )]

    @pytest.mark.asyncio
    async def test_send_input(self):
        fake = FakeDaemonClient(result={"ok": True})
        await _client(fake).runtime_session_send_input("sess_1", "keep going")
        assert fake.calls == [
            ("runtime.session.send_input", {"session_id": "sess_1", "text": "keep going"})
        ]

    @pytest.mark.asyncio
    async def test_adapters_list(self):
        fake = FakeDaemonClient(result={"adapters": []})
        await _client(fake).runtime_adapters_list()
        assert fake.calls == [("runtime.adapters.list", {})]

    @pytest.mark.asyncio
    async def test_why_chain(self):
        fake = FakeDaemonClient(result={"chain": []})
        await _client(fake).why_chain("rcpt_1", max_depth=8)
        assert fake.calls == [("why.chain", {"receipt_id": "rcpt_1", "max_depth": 8})]


class TestOperatorWatch:
    @pytest.mark.asyncio
    async def test_watch_yields_update_snapshots(self):
        fake = FakeDaemonClient(stream_items=[
            StreamItem("notification", "operator.watch.update",
                       {"items": [{"decision_id": "d1", "kind": "intervention"}],
                        "count": 1, "tick": 0, "changed": True}),
            StreamItem("notification", "operator.watch.update",
                       {"items": [], "count": 0, "tick": 3, "changed": True}),
            StreamItem("result", None, {"ticks": 30, "updates_emitted": 2}),
        ])
        client = _client(fake)

        updates = [u async for u in client.operator_watch(max_ticks=30)]

        assert [u["count"] for u in updates] == [1, 0]
        assert fake.calls[0] == ("operator.watch", {"max_ticks": 30})
        assert fake.closed is True  # dedicated stream connection closed

    @pytest.mark.asyncio
    async def test_watch_updates_drive_the_feed(self):
        """A watch update is a full snapshot → the feed reflects it."""
        fake = FakeDaemonClient(stream_items=[
            StreamItem("notification", "operator.watch.update",
                       {"items": [
                           {"decision_id": "d1", "kind": "intervention",
                            "urgency": "blocking", "summary": "rm -rf"},
                       ], "count": 1, "tick": 0, "changed": True}),
            StreamItem("result", None, {"updates_emitted": 1}),
        ])
        feed = DecisionFeedController()
        async for update in _client(fake).operator_watch():
            feed.ingest_watch_update(update)

        assert feed.count == 1
        assert feed.interrupts()[0].summary == "rm -rf"
