"""Transport abstraction for governor daemon communication.

Provides the seam for future transport implementations (TCP, etc.)
without changing the GovernorClient API.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class Transport(Protocol):
    """Protocol for JSON-RPC message transport."""

    async def connect(self) -> None: ...
    async def close(self) -> None: ...
    async def read_message(self) -> dict | None: ...
    async def write_message(self, msg: dict) -> None: ...
    @property
    def connected(self) -> bool: ...


class UnixSocketTransport:
    """Transport over a Unix domain socket with Content-Length framing."""

    def __init__(self, socket_path: Path) -> None:
        self._socket_path = socket_path
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    @property
    def connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    async def connect(self) -> None:
        """Open the Unix socket connection."""
        self._reader, self._writer = await asyncio.open_unix_connection(
            str(self._socket_path)
        )

    async def close(self) -> None:
        """Close the connection."""
        if self._writer is not None:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
            self._reader = None

    async def read_message(self) -> dict | None:
        """Read a Content-Length framed JSON-RPC message."""
        if self._reader is None:
            raise ConnectionError("Not connected")

        headers: dict[str, str] = {}
        while True:
            line = await self._reader.readline()
            if not line:
                return None  # EOF
            decoded = line.decode("utf-8")
            if decoded in ("\r\n", "\n"):
                break
            if ":" in decoded:
                key, _, value = decoded.partition(":")
                headers[key.strip()] = value.strip()

        content_length_str = headers.get("Content-Length")
        if content_length_str is None:
            return None

        content_length = int(content_length_str)
        body = await self._reader.readexactly(content_length)
        return json.loads(body.decode("utf-8"))

    async def write_message(self, msg: dict) -> None:
        """Write a Content-Length framed JSON-RPC message."""
        if self._writer is None:
            raise ConnectionError("Not connected")

        json_bytes = json.dumps(msg).encode("utf-8")
        header = f"Content-Length: {len(json_bytes)}\r\n\r\n".encode("utf-8")
        self._writer.write(header + json_bytes)
        await self._writer.drain()


# Placeholder for future transport:
# class TcpTransport:
#     """Transport over TCP with Content-Length framing."""
#     def __init__(self, host: str, port: int) -> None: ...
