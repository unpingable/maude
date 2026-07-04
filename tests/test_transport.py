# SPDX-License-Identifier: Apache-2.0
"""Tests for GovernorClient over the ag_shell_client transport (GS-9).

The wire layer now lives in ``ag_shell_client.AsyncDaemonClient``; these tests
inject a fake client via ``client_factory`` and exercise maude's wrapper: unary
dispatch, streaming, and the connection lifecycle (reconnect on a
transport-fatal error, keep the connection on a semantic daemon error)."""

from __future__ import annotations

import pytest

from ag_shell_client import DaemonAuthError, RPCError, StreamItem

from maude.client.rpc import GovernorClient


# ---------------------------------------------------------------------------
# FakeDaemonClient — injectable AsyncDaemonClient double
# ---------------------------------------------------------------------------


class FakeDaemonClient:
    """Stand-in for ag_shell_client.AsyncDaemonClient.

    ``call`` returns ``result`` or raises ``raises``; every call is recorded.
    ``stream_items`` scripts what ``stream`` yields.
    """

    def __init__(self, *, result=None, raises=None, stream_items=None) -> None:
        self.result = result
        self.raises = raises
        self.stream_items = stream_items or []
        self.calls: list[tuple[str, dict | None]] = []
        self.closed = False

    async def call(self, method, params=None, *, timeout=None):
        self.calls.append((method, params))
        if self.raises is not None:
            raise self.raises
        return self.result

    async def stream(self, method, params=None, *, read_timeout=None):
        self.calls.append((method, params))
        for item in self.stream_items:
            yield item

    async def aclose(self):
        self.closed = True


def factory_for(*clients):
    """Return a client_factory that hands out the given clients in order,
    then repeats the last one. Records how many clients were built."""
    seq = list(clients)
    state = {"i": 0}

    async def _factory():
        i = min(state["i"], len(seq) - 1)
        state["i"] += 1
        return seq[i]

    _factory.built = lambda: state["i"]  # type: ignore[attr-defined]
    return _factory


# ---------------------------------------------------------------------------
# Unary dispatch
# ---------------------------------------------------------------------------


class TestUnaryDispatch:
    @pytest.mark.asyncio
    async def test_call_round_trip(self):
        fake = FakeDaemonClient(result={"status": "ok"})
        client = GovernorClient(socket_path="/tmp/x.sock", client_factory=factory_for(fake))

        result = await client._call("governor.hello")

        assert result == {"status": "ok"}
        assert fake.calls == [("governor.hello", None)]

    @pytest.mark.asyncio
    async def test_call_passes_params(self):
        fake = FakeDaemonClient(result="pong")
        client = GovernorClient(socket_path="/tmp/x.sock", client_factory=factory_for(fake))

        await client._call("ping", {"a": 1})

        assert fake.calls == [("ping", {"a": 1})]

    @pytest.mark.asyncio
    async def test_reuses_one_connection(self):
        fake = FakeDaemonClient(result="ok")
        f = factory_for(fake)
        client = GovernorClient(socket_path="/tmp/x.sock", client_factory=f)

        await client._call("a")
        await client._call("b")

        assert f.built() == 1  # single cached connection

    @pytest.mark.asyncio
    async def test_typed_method_delegates(self):
        """A typed wrapper method maps to the right RPC method + params."""
        fake = FakeDaemonClient(result={"session_id": "sess_1"})
        client = GovernorClient(socket_path="/tmp/x.sock", client_factory=factory_for(fake))

        await client.runtime_session_launch("sess_1")

        assert fake.calls == [("runtime.session.launch", {"session_id": "sess_1"})]


# ---------------------------------------------------------------------------
# Connection lifecycle
# ---------------------------------------------------------------------------


class TestConnectionLifecycle:
    @pytest.mark.asyncio
    async def test_semantic_error_keeps_connection(self):
        """A real daemon error code (connection healthy) does not reconnect."""
        fake = FakeDaemonClient(raises=RPCError(-32601, "method not found"))
        f = factory_for(fake, FakeDaemonClient(result="ok"))
        client = GovernorClient(socket_path="/tmp/x.sock", client_factory=f)

        with pytest.raises(RPCError):
            await client._call("bad.method")
        # Connection not reset → still the same cached client, no new build.
        assert f.built() == 1
        assert fake.closed is False

    @pytest.mark.asyncio
    async def test_transport_error_resets_connection(self):
        """A transport-level RPCError (code 0) drops the connection."""
        broken = FakeDaemonClient(raises=RPCError(0, "connection closed before response"))
        fresh = FakeDaemonClient(result="ok")
        f = factory_for(broken, fresh)
        client = GovernorClient(socket_path="/tmp/x.sock", client_factory=f)

        with pytest.raises(RPCError):
            await client._call("x")
        assert broken.closed is True

        result = await client._call("y")  # reconnects to a fresh client
        assert result == "ok"
        assert f.built() == 2

    @pytest.mark.asyncio
    async def test_poison_runtimeerror_resets(self):
        poisoned = FakeDaemonClient(raises=RuntimeError("indeterminate state"))
        fresh = FakeDaemonClient(result="ok")
        f = factory_for(poisoned, fresh)
        client = GovernorClient(socket_path="/tmp/x.sock", client_factory=f)

        with pytest.raises(RuntimeError):
            await client._call("x")
        assert poisoned.closed is True
        assert await client._call("y") == "ok"
        assert f.built() == 2

    @pytest.mark.asyncio
    async def test_auth_error_propagates_without_reset(self):
        fake = FakeDaemonClient(raises=DaemonAuthError(-32001, "backend not authenticated"))
        f = factory_for(fake, FakeDaemonClient(result="ok"))
        client = GovernorClient(socket_path="/tmp/x.sock", client_factory=f)

        with pytest.raises(DaemonAuthError):
            await client._call("governor.now")
        assert fake.closed is False
        assert f.built() == 1

    @pytest.mark.asyncio
    async def test_close_resets(self):
        fake = FakeDaemonClient(result="ok")
        client = GovernorClient(socket_path="/tmp/x.sock", client_factory=factory_for(fake))

        await client._call("ping")
        await client.close()

        assert fake.closed is True
        # A subsequent call rebuilds.
        f2 = factory_for(FakeDaemonClient(result="ok2"))
        client._client_factory = f2
        assert await client._call("ping") == "ok2"


# ---------------------------------------------------------------------------
# Streaming (dedicated connection)
# ---------------------------------------------------------------------------


class TestStreaming:
    @pytest.mark.asyncio
    async def test_streaming_yields_deltas_and_stores_usage(self):
        stream_client = FakeDaemonClient(stream_items=[
            StreamItem("notification", "chat.delta", {"content": "Hello"}),
            StreamItem("notification", "chat.delta", {"content": " world"}),
            StreamItem("result", None, {"done": True, "usage": {"input": 3, "output": 5}}),
        ])
        client = GovernorClient(
            socket_path="/tmp/x.sock", client_factory=factory_for(stream_client)
        )

        chunks = [c async for c in client._call_streaming("chat.stream")]

        assert chunks == ["Hello", " world"]
        assert client.last_stream_usage == {"input": 3, "output": 5}

    @pytest.mark.asyncio
    async def test_streaming_closes_dedicated_client(self):
        unary = FakeDaemonClient(result="ok")
        stream_client = FakeDaemonClient(stream_items=[
            StreamItem("result", None, {"done": True}),
        ])
        # unary first (cached), then the stream client for the held stream.
        client = GovernorClient(
            socket_path="/tmp/x.sock", client_factory=factory_for(unary, stream_client)
        )

        await client._call("warm-up")  # builds + caches the unary client
        async for _ in client._call_streaming("chat.stream"):
            pass

        assert stream_client.closed is True  # dedicated stream connection closed
        assert unary.closed is False  # unary connection untouched by the stream


# ---------------------------------------------------------------------------
# Socket path resolution
# ---------------------------------------------------------------------------


class TestSocketPathResolution:
    def test_explicit_socket_path_wins(self):
        client = GovernorClient(socket_path="/tmp/explicit.sock")
        assert str(client.socket_path) == "/tmp/explicit.sock"

    def test_governor_dir_derives_daemon_path(self):
        client = GovernorClient(governor_dir="/tmp/proj/.governor")
        # ag_shell_client derivation: governor-<sha256[:12]>.sock
        assert client.socket_path.name.startswith("governor-")
        assert client.socket_path.name.endswith(".sock")
