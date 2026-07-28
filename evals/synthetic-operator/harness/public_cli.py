#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Thin operator-facing client for the synthetic Maude public-CLI broker.

The client exposes commands and key actions only.  It never reads the runtime
driver queue, scenario configuration, rubric, expected disposition, or
evaluator findings.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import stat
import sys
import uuid
from pathlib import Path
from typing import Any


REQUEST_SCHEMA = "maude.synthetic-operator.public-cli-request.v1"
RESPONSE_SCHEMA = "maude.synthetic-operator.response.v1"
MAX_MESSAGE_BYTES = 8 * 1024 * 1024


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def _socket_path(explicit: str | None) -> Path:
    raw = explicit or os.environ.get("MAUDE_PUBLIC_SOCKET")
    if not raw:
        raise SystemExit("Maude public interface is not configured")
    path = Path(raw)
    try:
        mode = path.stat().st_mode
    except OSError as exc:
        raise SystemExit("Maude public interface is unavailable") from exc
    if not stat.S_ISSOCK(mode):
        raise SystemExit("Maude public interface is unavailable")
    return path


def _request(
    broker_socket: Path,
    action: str,
    *,
    timeout: float,
    **fields: Any,
) -> dict[str, Any]:
    request_id = f"req-{uuid.uuid4().hex}"
    request = {
        "schema": REQUEST_SCHEMA,
        "request_id": request_id,
        "action": action,
        "timeout_seconds": timeout,
        **fields,
    }
    encoded = _json_bytes(request) + b"\n"
    chunks = bytearray()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(timeout + 2.0)
            connection.connect(str(broker_socket))
            connection.sendall(encoded)
            connection.shutdown(socket.SHUT_WR)
            while b"\n" not in chunks:
                chunk = connection.recv(65536)
                if not chunk:
                    raise SystemExit(
                        "Maude public interface closed without a response"
                    )
                chunks.extend(chunk)
                if len(chunks) > MAX_MESSAGE_BYTES:
                    raise SystemExit("Maude public response exceeded its limit")
    except (OSError, TimeoutError) as exc:
        raise SystemExit(f"Maude public interface failed: {exc}") from exc
    line, remainder = bytes(chunks).split(b"\n", 1)
    if remainder:
        raise SystemExit("Maude public interface returned extra response bytes")
    try:
        response = json.loads(line)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit("Maude public interface returned malformed JSON") from exc
    if (
        not isinstance(response, dict)
        or response.get("schema") != RESPONSE_SCHEMA
        or response.get("request_id") != request_id
    ):
        raise SystemExit("Maude public interface returned a mismatched response")
    return response


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--socket")
    parser.add_argument("--timeout", type=float, default=35.0)
    parser.add_argument("--restart", action="store_true")
    parser.add_argument("--screen", action="store_true")
    parser.add_argument("--quit", action="store_true")
    parser.add_argument("--key")
    parser.add_argument("--wait", type=float)
    parser.add_argument("--cli-help", action="store_true")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser.parse_args(argv)


def _usage() -> str:
    return """\
Synthetic Maude terminal bridge

  ./maude '<Maude command>'
  ./maude help
  ./maude --key ctrl+g
  ./maude --screen
  ./maude --wait 2
  ./maude --restart

Arguments without an adapter flag are submitted verbatim as one Maude command.
Use `./maude help` for Maude's own command help. The bridge flags model terminal
actions; they do not add Maude commands or prescribe an operational workflow.
"""


def main(argv: list[str] | None = None) -> int:
    args = _parse(list(sys.argv[1:] if argv is None else argv))
    if args.cli_help:
        print(_usage(), end="")
        return 0
    broker_socket = _socket_path(args.socket)
    if args.timeout <= 0 or args.timeout > 120:
        raise SystemExit("--timeout must be greater than 0 and at most 120 seconds")

    selected = sum(
        [
            bool(args.restart),
            bool(args.screen),
            bool(args.quit),
            args.key is not None,
            args.wait is not None,
        ]
    )
    if selected > 1:
        raise SystemExit("choose only one adapter action")
    if selected and args.command:
        raise SystemExit("adapter actions cannot be combined with a Maude command")

    if args.restart:
        response = _request(broker_socket, "restart", timeout=args.timeout)
    elif args.screen:
        response = _request(broker_socket, "screen", timeout=args.timeout)
    elif args.quit:
        response = _request(broker_socket, "quit", timeout=args.timeout)
    elif args.key is not None:
        response = _request(
            broker_socket, "key", key=args.key, timeout=args.timeout
        )
    elif args.wait is not None:
        response = _request(
            broker_socket, "wait", seconds=args.wait, timeout=args.timeout
        )
    else:
        if not args.command:
            raise SystemExit(_usage())
        text = " ".join(args.command)
        response = _request(
            broker_socket, "command", text=text, timeout=args.timeout
        )

    output = str(response.get("output") or "")
    if output:
        print(output)
    if not response.get("ok"):
        error = response.get("error") or "Maude lab action failed"
        print(f"maude lab error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
