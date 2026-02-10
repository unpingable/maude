"""JSON-RPC 2.0 client over Unix socket for the governor daemon."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, AsyncIterator

from maude.client.models import (
    ChatSession,
    DashboardSummary,
    GovernorNow,
    HealthResponse,
    IntentCompilationResult,
    IntentFormSchema,
    IntentPolicy,
    IntentTemplateList,
    IntentValidationResult,
    RunSummary,
    SessionSummary,
)


# =============================================================================
# Content-Length framing (same protocol as daemon)
# =============================================================================


async def _read_message(reader: asyncio.StreamReader) -> dict | None:
    """Read a Content-Length framed JSON-RPC message."""
    headers: dict[str, str] = {}
    while True:
        line = await reader.readline()
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
    body = await reader.readexactly(content_length)
    return json.loads(body.decode("utf-8"))


async def _write_message(writer: asyncio.StreamWriter, msg: dict) -> None:
    """Write a Content-Length framed JSON-RPC message."""
    json_bytes = json.dumps(msg).encode("utf-8")
    header = f"Content-Length: {len(json_bytes)}\r\n\r\n".encode("utf-8")
    writer.write(header + json_bytes)
    await writer.drain()


# =============================================================================
# Socket path resolution
# =============================================================================


def _default_socket_path(governor_dir: Path) -> Path:
    """Compute the default Unix socket path for a governor directory.

    Same algorithm as governor.daemon.default_socket_path.
    """
    import hashlib

    xdg = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
    dir_hash = hashlib.sha256(str(governor_dir.resolve()).encode()).hexdigest()[:12]
    return Path(xdg) / f"governor-{dir_hash}.sock"


# =============================================================================
# GovernorClient — JSON-RPC 2.0 over Unix socket
# =============================================================================


class GovernorClient:
    """JSON-RPC 2.0 client over Unix socket to the governor daemon.

    Provides the same public API as the HTTP client so that app.py
    can switch transports without code changes.
    """

    def __init__(
        self,
        socket_path: str | Path | None = None,
        governor_dir: str | Path | None = None,
    ) -> None:
        if socket_path:
            self._socket_path = Path(socket_path)
        elif governor_dir:
            self._socket_path = _default_socket_path(Path(governor_dir))
        else:
            # Try GOVERNOR_SOCKET, then GOVERNOR_DIR, then cwd
            env_socket = os.environ.get("GOVERNOR_SOCKET", "")
            if env_socket:
                self._socket_path = Path(env_socket)
            else:
                gov_dir = Path(os.environ.get("GOVERNOR_DIR", os.getcwd()))
                if not (gov_dir / "proposals.json").exists():
                    # Maybe the cwd IS the project root, governor dir is .governor/
                    candidate = gov_dir / ".governor"
                    if candidate.exists():
                        gov_dir = candidate
                self._socket_path = _default_socket_path(gov_dir)

        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._request_id: int = 0

    @property
    def socket_path(self) -> Path:
        return self._socket_path

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

    async def _ensure_connected(self) -> None:
        if self._writer is None or self._writer.is_closing():
            await self.connect()

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    async def _call(self, method: str, params: dict | None = None) -> Any:
        """Send a JSON-RPC request and return the result.

        Raises RuntimeError on JSON-RPC errors.
        """
        await self._ensure_connected()
        assert self._reader is not None and self._writer is not None

        request_id = self._next_id()
        msg = {
            "jsonrpc": "2.0",
            "method": method,
            "id": request_id,
            "params": params or {},
        }
        await _write_message(self._writer, msg)

        # Read responses, skipping notifications until we get our response
        while True:
            resp = await _read_message(self._reader)
            if resp is None:
                raise ConnectionError("Connection closed by daemon")

            # Skip notifications (no id)
            if "id" not in resp:
                continue

            if resp.get("id") != request_id:
                # Unexpected id — skip (shouldn't happen in single-client mode)
                continue

            if "error" in resp:
                err = resp["error"]
                raise RuntimeError(
                    f"RPC error {err.get('code', '?')}: {err.get('message', '?')}"
                )
            return resp.get("result")

    async def _call_streaming(
        self,
        method: str,
        params: dict | None = None,
        notification_method: str = "chat.delta",
    ) -> AsyncIterator[str]:
        """Send a JSON-RPC request and yield streaming notification content.

        Yields content strings from notifications, then returns when the
        final response (with matching id) arrives. The final response is
        NOT yielded — it's available via the return value after iteration.
        """
        await self._ensure_connected()
        assert self._reader is not None and self._writer is not None

        request_id = self._next_id()
        msg = {
            "jsonrpc": "2.0",
            "method": method,
            "id": request_id,
            "params": params or {},
        }
        await _write_message(self._writer, msg)

        while True:
            resp = await _read_message(self._reader)
            if resp is None:
                raise ConnectionError("Connection closed by daemon")

            # Notification — yield content
            if "id" not in resp:
                if resp.get("method") == notification_method:
                    content = resp.get("params", {}).get("content", "")
                    if content:
                        yield content
                continue

            # Final response
            if resp.get("id") == request_id:
                if "error" in resp:
                    err = resp["error"]
                    raise RuntimeError(
                        f"RPC error {err.get('code', '?')}: {err.get('message', '?')}"
                    )
                # Store the final result for the caller to inspect if needed
                self._last_stream_result = resp.get("result")
                return

    # ========================================================================
    # Health / Handshake
    # ========================================================================

    async def health(self) -> HealthResponse:
        """Call governor.hello and adapt to HealthResponse shape."""
        result = await self._call("governor.hello")
        return HealthResponse.model_validate(self._adapt_health(result))

    @staticmethod
    def _adapt_health(hello: dict) -> dict:
        """Adapt daemon governor.hello response → HealthResponse shape."""
        caps = hello.get("capabilities", {})
        backend = caps.get("backend", {})
        governor = hello.get("governor", {})
        return {
            "status": "ok" if governor.get("initialized") else "degraded",
            "backend": {
                "type": backend.get("type", "unknown"),
                "connected": backend.get("connected", False),
            },
            "governor": {
                "context_id": governor.get("context_id", "default"),
                "mode": governor.get("mode", "general"),
                "initialized": governor.get("initialized", False),
            },
        }

    # ========================================================================
    # Sessions
    # ========================================================================

    async def list_sessions(self) -> list[SessionSummary]:
        result = await self._call("sessions.list")
        return [SessionSummary.model_validate(self._adapt_session_summary(s)) for s in result]

    async def create_session(
        self, title: str = "New conversation", model: str = ""
    ) -> ChatSession:
        result = await self._call("sessions.create", {"title": title})
        return ChatSession.model_validate(self._adapt_session(result))

    async def get_session(self, session_id: str) -> ChatSession:
        result = await self._call("sessions.get", {"id": session_id})
        if result is None:
            raise RuntimeError(f"Session not found: {session_id}")
        return ChatSession.model_validate(self._adapt_session(result))

    async def delete_session(self, session_id: str) -> bool:
        result = await self._call("sessions.delete", {"id": session_id})
        return result.get("success", False)

    @staticmethod
    def _adapt_session_summary(capsule: dict) -> dict:
        """Adapt daemon session capsule → SessionSummary shape."""
        meta = capsule.get("metadata", capsule)
        return {
            "id": meta.get("session_id", ""),
            "context_id": meta.get("context_id", "default"),
            "title": meta.get("name", "Untitled"),
            "created_at": meta.get("created_at", ""),
            "updated_at": meta.get("updated_at", meta.get("created_at", "")),
            "model": "",
            "message_count": 0,
        }

    @staticmethod
    def _adapt_session(capsule: dict) -> dict:
        """Adapt daemon session capsule → ChatSession shape."""
        meta = capsule.get("metadata", capsule)
        return {
            "id": meta.get("session_id", ""),
            "context_id": meta.get("context_id", "default"),
            "title": meta.get("name", "Untitled"),
            "created_at": meta.get("created_at", ""),
            "updated_at": meta.get("updated_at", meta.get("created_at", "")),
            "model": "",
            "message_count": 0,
            "messages": [],
        }

    # ========================================================================
    # Chat (governed generation)
    # ========================================================================

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        model: str = "",
        context_id: str = "default",
    ) -> AsyncIterator[str]:
        """Stream governed chat completions, yielding content deltas.

        Sends chat.stream RPC, yields from chat.delta notifications,
        completes when the final response arrives.
        """
        async for delta in self._call_streaming(
            "chat.stream",
            {"messages": messages, "model": model, "context_id": context_id},
            notification_method="chat.delta",
        ):
            yield delta

    async def chat_send(
        self,
        messages: list[dict[str, str]],
        model: str = "",
        context_id: str = "default",
    ) -> dict:
        """Non-streaming governed chat. Returns full result dict."""
        return await self._call(
            "chat.send",
            {"messages": messages, "model": model, "context_id": context_id},
        )

    async def chat_models(self) -> list[dict[str, str]]:
        """List available models from the backend."""
        result = await self._call("chat.models")
        return result.get("models", [])

    async def chat_backend(self) -> dict:
        """Get current backend info."""
        return await self._call("chat.backend")

    # ========================================================================
    # Governor state
    # ========================================================================

    async def governor_now(self) -> GovernorNow:
        result = await self._call("governor.now")
        return GovernorNow.model_validate(self._adapt_governor_now(result))

    async def governor_status(self) -> dict:
        return await self._call("governor.status")

    @staticmethod
    def _adapt_governor_now(now: dict) -> dict:
        """Adapt daemon governor.now → GovernorNow shape."""
        pill = now.get("pill", "UNKNOWN")
        sentence = now.get("sentence", "")
        regime = now.get("regime")
        return {
            "context_id": "default",
            "status": pill,
            "sentence": sentence,
            "last_event": None,
            "suggested_action": None,
            "regime": regime,
            "mode": "general",
        }

    # ========================================================================
    # Intent compiler
    # ========================================================================

    async def intent_templates(self) -> IntentTemplateList:
        result = await self._call("intent.templates")
        return IntentTemplateList.model_validate(result)

    async def intent_schema(self, template_name: str) -> IntentFormSchema:
        result = await self._call("intent.schema", {"template_name": template_name})
        return IntentFormSchema.model_validate(result)

    async def intent_validate(
        self, schema_id: str, values: dict
    ) -> IntentValidationResult:
        result = await self._call(
            "intent.validate", {"schema_id": schema_id, "values": values}
        )
        return IntentValidationResult.model_validate(result)

    async def intent_compile(
        self,
        schema_id: str,
        values: dict,
        template_name: str,
        escape_text: str | None = None,
    ) -> IntentCompilationResult:
        params: dict = {
            "schema_id": schema_id,
            "values": values,
            "template_name": template_name,
        }
        if escape_text is not None:
            params["escape_text"] = escape_text
        result = await self._call("intent.compile", params)
        return IntentCompilationResult.model_validate(result)

    async def intent_policy(self) -> IntentPolicy:
        result = await self._call("intent.policy")
        return IntentPolicy.model_validate(result)

    # ========================================================================
    # Commit / violation resolution
    # ========================================================================

    async def commit_pending(self) -> dict | None:
        return await self._call("commit.pending")

    async def commit_fix(self, corrected_text: str) -> dict:
        return await self._call("commit.fix", {"corrected_text": corrected_text})

    async def commit_revise(self, new_anchor_text: str | None = None) -> dict:
        params: dict = {}
        if new_anchor_text is not None:
            params["new_anchor_text"] = new_anchor_text
        return await self._call("commit.revise", params)

    async def commit_proceed(
        self, reason: str = "", scope: str | None = None, expiry: str | None = None
    ) -> dict:
        params: dict = {"reason": reason}
        if scope is not None:
            params["scope"] = scope
        if expiry is not None:
            params["expiry"] = expiry
        return await self._call("commit.proceed", params)

    async def commit_exceptions(self) -> list:
        return await self._call("commit.exceptions")

    # ========================================================================
    # Receipts & Scars
    # ========================================================================

    async def receipts_list(
        self,
        gate: str | None = None,
        verdict: str | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        params: dict = {}
        if gate:
            params["gate"] = gate
        if verdict:
            params["verdict"] = verdict
        if limit is not None:
            params["limit"] = limit
        return await self._call("receipts.list", params)

    async def receipts_detail(self, receipt_id: str) -> dict:
        return await self._call("receipts.detail", {"receipt_id": receipt_id})

    async def scars_list(self) -> dict:
        return await self._call("scars.list")

    async def scars_history(self, limit: int = 50) -> list:
        return await self._call("scars.history", {"limit": limit})

    # ========================================================================
    # Stubs for HTTP-era methods (no-op or adapted)
    # ========================================================================

    async def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        model: str | None = None,
        usage: dict[str, int] | None = None,
    ) -> None:
        """No-op: daemon manages session persistence internally."""
        pass

    async def add_constraint(
        self, constraint: str, patterns: list[str] | None = None
    ) -> dict:
        """Stub — constraint submission not yet mapped to daemon RPC."""
        return {"status": "not_implemented"}

    async def list_constraints(self) -> list[dict]:
        """Stub — constraints not yet mapped to daemon RPC."""
        return []

    async def list_runs(self, limit: int = 50) -> list[RunSummary]:
        """Stub — v2 runs not yet mapped to daemon RPC."""
        return []

    async def create_run(
        self, task: str, profile: str = "established", scope: str | None = None
    ) -> dict:
        """Stub — v2 runs not yet mapped to daemon RPC."""
        return {"status": "not_implemented"}

    async def dashboard_summary(self) -> DashboardSummary:
        """Stub — dashboard not yet mapped to daemon RPC."""
        return DashboardSummary()
