# SPDX-License-Identifier: Apache-2.0
"""Tests for the Transport abstraction layer."""

from __future__ import annotations

import asyncio
from collections import deque

import pytest

from maude.client.transport import Transport, UnixSocketTransport
from maude.client.rpc import GovernorClient


# ---------------------------------------------------------------------------
# MockTransport — injectable test double
# ---------------------------------------------------------------------------


class MockTransport:
    """In-memory transport for testing GovernorClient without a real socket."""

    def __init__(self) -> None:
        self._connected = False
        self._inbox: deque[dict] = deque()  # messages to return from read_message

    @property
    def connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        self._connected = True

    async def close(self) -> None:
        self._connected = False

    async def read_message(self) -> dict | None:
        if not self._connected:
            raise ConnectionError("Not connected")
        if not self._inbox:
            return None
        return self._inbox.popleft()

    async def write_message(self, msg: dict) -> None:
        if not self._connected:
            raise ConnectionError("Not connected")
        # Store the last written message for assertions
        self.last_written = msg

    def enqueue(self, *messages: dict) -> None:
        """Queue messages to be returned by read_message."""
        for m in messages:
            self._inbox.append(m)


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    def test_unix_socket_transport_is_transport(self):
        t = UnixSocketTransport(socket_path="/tmp/fake.sock")
        assert isinstance(t, Transport)

    def test_mock_transport_is_transport(self):
        t = MockTransport()
        assert isinstance(t, Transport)


# ---------------------------------------------------------------------------
# UnixSocketTransport lifecycle
# ---------------------------------------------------------------------------


class TestUnixSocketTransportLifecycle:
    def test_connected_false_before_connect(self):
        t = UnixSocketTransport(socket_path="/tmp/fake.sock")
        assert t.connected is False

    @pytest.mark.asyncio
    async def test_read_before_connect_raises(self):
        t = UnixSocketTransport(socket_path="/tmp/fake.sock")
        with pytest.raises(ConnectionError, match="Not connected"):
            await t.read_message()

    @pytest.mark.asyncio
    async def test_write_before_connect_raises(self):
        t = UnixSocketTransport(socket_path="/tmp/fake.sock")
        with pytest.raises(ConnectionError, match="Not connected"):
            await t.write_message({"test": True})


# ---------------------------------------------------------------------------
# MockTransport injected into GovernorClient
# ---------------------------------------------------------------------------


class TestClientWithMockTransport:
    @pytest.mark.asyncio
    async def test_call_round_trip(self):
        """GovernorClient._call() uses the injected transport for write + read."""
        mock = MockTransport()
        client = GovernorClient(transport=mock)

        # Queue a JSON-RPC response
        mock.enqueue({"jsonrpc": "2.0", "id": 1, "result": {"status": "ok"}})

        result = await client._call("governor.hello")
        assert result == {"status": "ok"}

        # Verify the written message shape
        assert mock.last_written["jsonrpc"] == "2.0"
        assert mock.last_written["method"] == "governor.hello"
        assert mock.last_written["id"] == 1

    @pytest.mark.asyncio
    async def test_call_auto_connects(self):
        """_ensure_connected triggers transport.connect when not connected."""
        mock = MockTransport()
        client = GovernorClient(transport=mock)
        assert mock.connected is False

        mock.enqueue({"jsonrpc": "2.0", "id": 1, "result": "pong"})
        await client._call("ping")

        assert mock.connected is True

    @pytest.mark.asyncio
    async def test_call_rpc_error(self):
        """JSON-RPC error responses raise RuntimeError."""
        mock = MockTransport()
        client = GovernorClient(transport=mock)

        mock.enqueue({
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32600, "message": "Invalid request"},
        })

        with pytest.raises(RuntimeError, match="RPC error -32600"):
            await client._call("bad.method")

    @pytest.mark.asyncio
    async def test_call_skips_notifications(self):
        """Notifications (no id) are skipped until the actual response arrives."""
        mock = MockTransport()
        client = GovernorClient(transport=mock)

        mock.enqueue(
            {"jsonrpc": "2.0", "method": "some.event", "params": {}},  # notification
            {"jsonrpc": "2.0", "id": 1, "result": "got it"},
        )

        result = await client._call("test.method")
        assert result == "got it"

    @pytest.mark.asyncio
    async def test_streaming_with_mock(self):
        """_call_streaming yields notification content and stops at final response."""
        mock = MockTransport()
        client = GovernorClient(transport=mock)

        mock.enqueue(
            {"jsonrpc": "2.0", "method": "chat.delta", "params": {"content": "Hello"}},
            {"jsonrpc": "2.0", "method": "chat.delta", "params": {"content": " world"}},
            {"jsonrpc": "2.0", "id": 1, "result": {"done": True}},
        )

        chunks = []
        async for chunk in client._call_streaming("chat.stream"):
            chunks.append(chunk)

        assert chunks == ["Hello", " world"]

    @pytest.mark.asyncio
    async def test_close_delegates_to_transport(self):
        """client.close() calls transport.close()."""
        mock = MockTransport()
        client = GovernorClient(transport=mock)

        # Connect first
        mock.enqueue({"jsonrpc": "2.0", "id": 1, "result": "ok"})
        await client._call("ping")
        assert mock.connected is True

        await client.close()
        assert mock.connected is False
