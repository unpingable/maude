#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Trusted public-CLI broker for the synthetic Maude evaluation surface.

The operator-visible ``./maude`` client connects to one Unix socket.  This
broker is the only process that can see the evaluator-private filesystem queue
owned by ``maude_driver.py``.  It validates the complete public request,
forwards one bounded queue request, and records exact request/response
correlation evidence.  It never receives provider credentials or model
prompts.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import signal
import socket
import time
import uuid
from pathlib import Path
from typing import Any


PUBLIC_REQUEST_SCHEMA = "maude.synthetic-operator.public-cli-request.v1"
QUEUE_SCHEMA = "maude.synthetic-operator.queue.v1"
RESPONSE_SCHEMA = "maude.synthetic-operator.response.v1"
TRACE_SCHEMA = "maude.synthetic-operator.public-cli-broker-event.v1"
READY_SCHEMA = "maude.synthetic-operator.public-cli-broker-ready.v1"
CLEANUP_SCHEMA = "maude.synthetic-operator.public-cli-broker-cleanup.v1"
MAX_MESSAGE_BYTES = 8 * 1024 * 1024
MAX_TIMEOUT_SECONDS = 120.0


class BrokerError(RuntimeError):
    """The public request or private queue violated the fixed boundary."""


class QueueTimeout(BrokerError):
    """A validated request remains queued but has no observed response."""

    def __init__(
        self,
        message: str,
        *,
        request_path: Path,
        response_path: Path,
        request_bytes: bytes,
    ) -> None:
        super().__init__(message)
        self.request_path = request_path
        self.response_path = response_path
        self.request_bytes = request_bytes


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
        0o600,
    )
    try:
        encoded = _canonical_bytes(value) + b"\n"
        if os.write(descriptor, encoded) != len(encoded):
            raise BrokerError(f"short write to {path}")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)


def _append_jsonl(path: Path, value: dict[str, Any]) -> None:
    encoded = _canonical_bytes(value) + b"\n"
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_CLOEXEC,
        0o600,
    )
    try:
        if os.write(descriptor, encoded) != len(encoded):
            raise BrokerError(f"short write to {path}")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _read_message(connection: socket.socket) -> tuple[dict[str, Any], bytes]:
    chunks = bytearray()
    while b"\n" not in chunks:
        chunk = connection.recv(65536)
        if not chunk:
            raise BrokerError("client closed before one complete JSON request")
        chunks.extend(chunk)
        if len(chunks) > MAX_MESSAGE_BYTES:
            raise BrokerError("public request exceeds the fixed size limit")
    line, remainder = bytes(chunks).split(b"\n", 1)
    if remainder:
        raise BrokerError("one connection may contain only one request")
    try:
        value = json.loads(line)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BrokerError("public request is malformed JSON") from exc
    if not isinstance(value, dict):
        raise BrokerError("public request must be a JSON object")
    return value, line


def _send_message(connection: socket.socket, value: dict[str, Any]) -> None:
    connection.sendall(_canonical_bytes(value) + b"\n")


def _validate_request(value: dict[str, Any]) -> tuple[dict[str, Any], float]:
    request_id = value.get("request_id")
    action = value.get("action")
    timeout = value.get("timeout_seconds")
    if value.get("schema") != PUBLIC_REQUEST_SCHEMA:
        raise BrokerError("public request schema mismatch")
    if not isinstance(request_id, str) or not re.fullmatch(
        r"req-[0-9a-f]{32}", request_id
    ):
        raise BrokerError("public request_id is invalid")
    if action not in {"command", "key", "wait", "screen", "restart", "quit"}:
        raise BrokerError("public action is not supported")
    if (
        not isinstance(timeout, (int, float))
        or isinstance(timeout, bool)
        or float(timeout) <= 0
        or float(timeout) > MAX_TIMEOUT_SECONDS
    ):
        raise BrokerError("public timeout is outside the fixed bounds")
    allowed = {"schema", "request_id", "action", "timeout_seconds"}
    queue_request: dict[str, Any] = {
        "schema": QUEUE_SCHEMA,
        "request_id": request_id,
        "action": action,
    }
    if action == "command":
        allowed.add("text")
        text = value.get("text")
        if not isinstance(text, str) or not text.strip() or len(text) > 32768:
            raise BrokerError("command text is absent or exceeds its limit")
        queue_request["text"] = text
    elif action == "key":
        allowed.add("key")
        key = value.get("key")
        if not isinstance(key, str) or not key or len(key) > 128:
            raise BrokerError("key value is absent or exceeds its limit")
        queue_request["key"] = key
    elif action == "wait":
        allowed.add("seconds")
        seconds = value.get("seconds")
        if (
            not isinstance(seconds, (int, float))
            or isinstance(seconds, bool)
            or float(seconds) < 0
            or float(seconds) > 15
        ):
            raise BrokerError("wait is outside the fixed bounds")
        queue_request["seconds"] = float(seconds)
    extra = sorted(set(value) - allowed)
    if extra:
        raise BrokerError(f"undeclared public request fields: {extra}")
    return queue_request, float(timeout)


def _queue_round_trip(
    control: Path,
    request: dict[str, Any],
    *,
    timeout: float,
) -> tuple[dict[str, Any], Path, Path, bytes, bytes]:
    request_id = str(request["request_id"])
    name = f"{time.time_ns():020d}-{request_id}.json"
    request_path = control / "requests" / name
    response_path = control / "responses" / name
    request_bytes = _canonical_bytes(request) + b"\n"
    _atomic_json(request_path, request)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if response_path.is_file():
            try:
                response_bytes = response_path.read_bytes()
                response = json.loads(response_bytes)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                time.sleep(0.02)
                continue
            if (
                not isinstance(response, dict)
                or response.get("schema") != RESPONSE_SCHEMA
                or response.get("request_id") != request_id
            ):
                raise BrokerError("private driver returned a mismatched response")
            return (
                response,
                request_path,
                response_path,
                request_bytes,
                response_bytes,
            )
        time.sleep(0.02)
    raise QueueTimeout(
        f"private driver action timed out after {timeout:.1f}s; "
        "the queued request has retained unknown settlement",
        request_path=request_path,
        response_path=response_path,
        request_bytes=request_bytes,
    )


def _failure(request_id: Any, error: str) -> dict[str, Any]:
    return {
        "schema": RESPONSE_SCHEMA,
        "request_id": request_id if isinstance(request_id, str) else None,
        "ok": False,
        "action": "invalid",
        "output": "",
        "error": error,
    }


def serve(args: argparse.Namespace) -> int:
    control = Path(args.control_dir).resolve()
    public_socket = Path(args.socket).resolve()
    trace = Path(args.trace).resolve()
    ready = Path(args.ready).resolve()
    cleanup = Path(args.cleanup).resolve()
    driver_ready = control / "driver-ready.json"
    if not driver_ready.is_file():
        raise BrokerError("private Maude driver is not ready")
    for directory in (public_socket.parent, trace.parent, ready.parent, cleanup.parent):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if public_socket.exists() or public_socket.is_symlink():
        raise BrokerError("refusing to replace an existing public socket path")

    stopping = False
    sequence = 0
    active_request_id: str | None = None

    def request_stop(_signum: int, _frame: Any) -> None:
        nonlocal stopping
        stopping = True

    previous_term = signal.signal(signal.SIGTERM, request_stop)
    previous_int = signal.signal(signal.SIGINT, request_stop)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(public_socket))
    public_socket.chmod(0o600)
    listener.listen(8)
    listener.settimeout(0.1)
    trace.touch(mode=0o600, exist_ok=False)
    _atomic_json(
        ready,
        {
            "schema": READY_SCHEMA,
            "pid": os.getpid(),
            "public_socket": str(public_socket),
            "public_request_schema": PUBLIC_REQUEST_SCHEMA,
            "driver_queue_schema": QUEUE_SCHEMA,
            "raw_control_dir_exposed_to_client": False,
        },
    )
    try:
        while not stopping:
            try:
                connection, _ = listener.accept()
            except TimeoutError:
                continue
            with connection:
                sequence += 1
                received_at = time.time_ns()
                request: dict[str, Any] | None = None
                public_bytes = b""
                queue_request_path: Path | None = None
                queue_response_path: Path | None = None
                queue_request_bytes = b""
                queue_response_bytes = b""
                settlement = "rejected-before-private-queue"
                queue_request_retained = False
                try:
                    request, public_bytes = _read_message(connection)
                    active_request_id = (
                        str(request.get("request_id"))
                        if isinstance(request.get("request_id"), str)
                        else None
                    )
                    queue_request, timeout = _validate_request(request)
                    (
                        response,
                        queue_request_path,
                        queue_response_path,
                        queue_request_bytes,
                        queue_response_bytes,
                    ) = _queue_round_trip(
                        control,
                        queue_request,
                        timeout=timeout,
                    )
                    settlement = "completed"
                except QueueTimeout as exc:
                    queue_request_path = exc.request_path
                    queue_response_path = exc.response_path
                    queue_request_bytes = exc.request_bytes
                    queue_request_retained = True
                    settlement = "retained-unknown-after-public-timeout"
                    response = _failure(
                        request.get("request_id")
                        if isinstance(request, dict)
                        else None,
                        f"{type(exc).__name__}: {exc}",
                    )
                    response.update(
                        {
                            "terminal_state": "unknown",
                            "queued_request_retained": True,
                        }
                    )
                except (BrokerError, OSError) as exc:
                    settlement = "broker-failed-closed"
                    response = _failure(
                        request.get("request_id")
                        if isinstance(request, dict)
                        else None,
                        f"{type(exc).__name__}: {exc}",
                    )
                response_bytes = _canonical_bytes(response)
                with contextlib.suppress(BrokenPipeError, OSError):
                    _send_message(connection, response)
                _append_jsonl(
                    trace,
                    {
                        "schema": TRACE_SCHEMA,
                        "seq": sequence,
                        "received_at_ns": received_at,
                        "completed_at_ns": time.time_ns(),
                        "request_id": (
                            request.get("request_id")
                            if isinstance(request, dict)
                            else None
                        ),
                        "action": (
                            request.get("action")
                            if isinstance(request, dict)
                            else None
                        ),
                        "public_request": request,
                        "public_request_sha256": _sha256_bytes(public_bytes),
                        "queue_request_file": (
                            queue_request_path.name
                            if queue_request_path is not None
                            else None
                        ),
                        "queue_request_sha256": (
                            _sha256_bytes(queue_request_bytes)
                            if queue_request_bytes
                            else None
                        ),
                        "queue_response_file": (
                            queue_response_path.name
                            if queue_response_path is not None
                            else None
                        ),
                        "queue_response_sha256": (
                            _sha256_bytes(queue_response_bytes)
                            if queue_response_bytes
                            else None
                        ),
                        "public_response": response,
                        "public_response_sha256": _sha256_bytes(response_bytes),
                        "ok": bool(response.get("ok")),
                        "settlement": settlement,
                        "queue_request_retained": queue_request_retained,
                        "queue_response_observed_at_return": bool(
                            queue_response_bytes
                        ),
                        "correlation_complete": bool(
                            settlement == "completed"
                            and queue_response_bytes
                            and
                            queue_request_path is not None
                            and queue_response_path is not None
                            and response.get("request_id")
                            == (
                                request.get("request_id")
                                if isinstance(request, dict)
                                else None
                            )
                        ),
                    },
                )
                active_request_id = None
    finally:
        listener.close()
        with contextlib.suppress(FileNotFoundError):
            public_socket.unlink()
        _atomic_json(
            cleanup,
            {
                "schema": CLEANUP_SCHEMA,
                "completed_at_ns": time.time_ns(),
                "processed_requests": sequence,
                "active_request_id": active_request_id,
                "no_request_in_flight": active_request_id is None,
                "public_socket_removed": not public_socket.exists(),
                "ready_marker_retained_as_evidence": ready.is_file(),
                "raw_control_dir_exposed_to_client": False,
            },
        )
        signal.signal(signal.SIGTERM, previous_term)
        signal.signal(signal.SIGINT, previous_int)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Trusted synthetic Maude public-CLI broker"
    )
    parser.add_argument("--control-dir", required=True)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--trace", required=True)
    parser.add_argument("--ready", required=True)
    parser.add_argument("--cleanup", required=True)
    return serve(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
