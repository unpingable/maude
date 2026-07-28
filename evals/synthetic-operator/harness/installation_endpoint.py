#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Evaluator-only Unix-socket fault endpoints for installation UX specimens.

This fixture is not Maude, Governor, or an adapter. It exposes only two
deliberately nonconforming synthetic endpoint conditions through the ordinary
Unix socket handed to the installed public Maude client.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
import signal
from pathlib import Path
from typing import Any


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _append_trace(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(
            json.dumps(
                value,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


async def _read_frame(reader: asyncio.StreamReader) -> bytes | None:
    length: int | None = None
    while True:
        line = await reader.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            break
        with_value = line.decode("ascii", errors="ignore").split(":", 1)
        if (
            len(with_value) == 2
            and with_value[0].strip().casefold() == "content-length"
        ):
            length = int(with_value[1].strip())
    if length is None or length < 0:
        return None
    return await reader.readexactly(length)


class FaultEndpoint:
    def __init__(self, *, mode: str, trace: Path) -> None:
        self.mode = mode
        self.trace = trace
        self.connection = 0

    async def handle(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        self.connection += 1
        connection = self.connection
        try:
            request_bytes = await _read_frame(reader)
            if request_bytes is None:
                return
            _append_trace(
                self.trace,
                {
                    "connection": connection,
                    "direction": "request",
                    "bytes": len(request_bytes),
                    "sha256": hashlib.sha256(request_bytes).hexdigest(),
                    "body_base64": base64.b64encode(request_bytes).decode(
                        "ascii"
                    ),
                },
            )
            if self.mode == "wrong-service":
                response = (
                    b"HTTP/1.1 200 OK\r\n"
                    b"Content-Type: text/plain\r\n"
                    b"Content-Length: 24\r\n\r\n"
                    b"synthetic menu endpoint\n"
                )
            else:
                request = json.loads(request_bytes.decode("utf-8"))
                body = json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": request.get("id"),
                        "result": "retained-state-envelope-v0",
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
                response = (
                    f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
                    + body
                )
            _append_trace(
                self.trace,
                {
                    "connection": connection,
                    "direction": "response",
                    "bytes": len(response),
                    "sha256": hashlib.sha256(response).hexdigest(),
                    "body_base64": base64.b64encode(response).decode("ascii"),
                    "mode": self.mode,
                },
            )
            writer.write(response)
            await writer.drain()
        except (
            asyncio.IncompleteReadError,
            BrokenPipeError,
            ConnectionError,
            json.JSONDecodeError,
        ) as exc:
            _append_trace(
                self.trace,
                {
                    "connection": connection,
                    "direction": "fixture-error",
                    "error_type": type(exc).__name__,
                },
            )
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass


async def _run(args: argparse.Namespace) -> None:
    socket_path = Path(args.socket).resolve()
    ready_path = Path(args.ready).resolve()
    trace_path = Path(args.trace).resolve()
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    if socket_path.exists() or socket_path.is_symlink():
        socket_path.unlink()
    endpoint = FaultEndpoint(mode=args.mode, trace=trace_path)
    server = await asyncio.start_unix_server(
        endpoint.handle,
        str(socket_path),
    )
    _write_json(
        ready_path,
        {
            "schema": "maude.synthetic-installation-endpoint.ready.v1",
            "mode": args.mode,
            "socket": str(socket_path),
            "pid": os.getpid(),
        },
    )
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass
    async with server:
        await stop.wait()
    if socket_path.exists() or socket_path.is_symlink():
        socket_path.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="serve one evaluator-only installation fault endpoint"
    )
    parser.add_argument(
        "--mode",
        choices=("incompatible-schema", "wrong-service"),
        required=True,
    )
    parser.add_argument("--socket", required=True)
    parser.add_argument("--ready", required=True)
    parser.add_argument("--trace", required=True)
    asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    main()
