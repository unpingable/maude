# SPDX-License-Identifier: Apache-2.0
"""Typed governor-daemon client for maude.

The wire layer — Content-Length framing, XDG socket-path derivation, JSON-RPC
2.0 dispatch, the ``-32001`` auth error, streaming — lives in the shared
``ag_shell_client`` package (agent_gov ``libs/ag_shell_client``, CI-tested
against the daemon). This module is only maude's *ergonomic surface*: one
place that names every RPC method maude calls and adapts daemon shapes to the
Pydantic rendering models in :mod:`maude.client.models`. Kills the previously
triplicated framing/socket-path code (GS-9).

Connection model (from ag_shell_client): one connection serves one in-flight
request. Unary calls share a single cached connection, serialized by a lock so
the 5s status poll and a command handler never collide on the busy guard. A
held stream (``chat.stream``) runs on its own dedicated connection so it does
not block the poll. An interrupted exchange poisons its connection; the wrapper
drops the poisoned client and reconnects a fresh one on the next call.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable

from ag_shell_client import (
    AsyncDaemonClient,
    DaemonAuthError,
    RPCError,
    default_socket_path,
)

from maude.client.models import (
    ChainPreflightDecision,
    ChainRecordResult,
    ChainStatus,
    ChatSession,
    DashboardSummary,
    GovernorNow,
    HealthResponse,
    IntentCompilationResult,
    IntentFormSchema,
    IntentPolicy,
    IntentTemplateList,
    IntentValidationResult,
    SessionSummary,
)

# Re-export so callers that used to catch transport errors keep a stable name.
__all__ = ["GovernorClient", "DaemonAuthError", "RPCError"]

ClientFactory = Callable[[], Awaitable[AsyncDaemonClient]]


# =============================================================================
# GovernorClient — typed surface over ag_shell_client.AsyncDaemonClient
# =============================================================================


class GovernorClient:
    """Typed async client for the governor daemon.

    Delegates all framing/transport to :class:`ag_shell_client.AsyncDaemonClient`.
    Public method signatures are unchanged from the pre-GS-9 client so callers
    (``app.py``, the integration suite) need no edits.
    """

    def __init__(
        self,
        socket_path: str | Path | None = None,
        governor_dir: str | Path | None = None,
        *,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self._socket_path = self._resolve_socket_path(socket_path, governor_dir)
        # Injectable for tests; default opens a real socket connection.
        self._client_factory: ClientFactory = client_factory or self._default_factory
        self._client: AsyncDaemonClient | None = None
        self._lock = asyncio.Lock()
        self._last_stream_result: Any = None

    async def _default_factory(self) -> AsyncDaemonClient:
        return await AsyncDaemonClient.connect(socket_path=self._socket_path)

    @staticmethod
    def _resolve_socket_path(
        socket_path: str | Path | None,
        governor_dir: str | Path | None,
    ) -> Path:
        """Select the daemon socket. Hash derivation is ag_shell_client's
        (byte-identical to the daemon); the env/subdir *selection* is maude's
        config concern."""
        if socket_path:
            return Path(socket_path)
        if governor_dir:
            return default_socket_path(governor_dir)
        env_socket = os.environ.get("GOVERNOR_SOCKET", "")
        if env_socket:
            return Path(env_socket)
        gov_dir = Path(os.environ.get("GOVERNOR_DIR", os.getcwd()))
        if not (gov_dir / "proposals.json").exists():
            candidate = gov_dir / ".governor"
            if candidate.exists():
                gov_dir = candidate
        return default_socket_path(gov_dir)

    @property
    def socket_path(self) -> Path:
        return self._socket_path

    @property
    def last_stream_usage(self) -> dict[str, int]:
        """Usage data from the last chat.stream response, if available."""
        result = self._last_stream_result
        if result and isinstance(result, dict):
            return result.get("usage", {})
        return {}

    # -- lifecycle ---------------------------------------------------------- #

    async def connect(self) -> None:
        """Open the unary connection (idempotent)."""
        await self._ensure_client()

    async def close(self) -> None:
        """Close the unary connection."""
        await self._reset()

    async def _ensure_client(self) -> AsyncDaemonClient:
        if self._client is None:
            self._client = await self._client_factory()
        return self._client

    async def _reset(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            await client.aclose()

    # -- dispatch ----------------------------------------------------------- #

    async def _call(self, method: str, params: dict | None = None) -> Any:
        """Send a unary RPC and return its result.

        Serialized so maude's own concurrency (poll + command) never trips the
        one-in-flight busy guard. A transport-fatal failure drops the poisoned
        connection so the next call reconnects; a semantic daemon error (a
        well-formed error response) leaves the healthy connection intact and
        simply propagates.
        """
        async with self._lock:
            client = await self._ensure_client()
            try:
                return await client.call(method, params)
            except DaemonAuthError:
                # Backend not authenticated: the connection is fine, surface as-is.
                raise
            except RPCError as e:
                # code 0 == transport-level failure (closed/desync) → reconnect;
                # a real daemon error code means the connection is healthy.
                if getattr(e, "code", 0) == 0:
                    await self._reset()
                raise
            except (RuntimeError, ConnectionError, OSError, asyncio.TimeoutError):
                # Poisoned/indeterminate connection → drop it; next call reconnects.
                await self._reset()
                raise

    async def _call_streaming(
        self,
        method: str,
        params: dict | None = None,
        notification_method: str = "chat.delta",
    ) -> AsyncIterator[str]:
        """Stream an RPC on a dedicated connection, yielding notification
        content. The final result is stashed in ``_last_stream_result``.

        A dedicated connection keeps the held stream from blocking the unary
        poll (per the shell contract's one-in-flight rule)."""
        stream_client = await self._client_factory()
        try:
            async for item in stream_client.stream(method, params, read_timeout=None):
                if item.kind == "notification" and item.method == notification_method:
                    content = (item.payload or {}).get("content", "")
                    if content:
                        yield content
                elif item.kind == "result":
                    self._last_stream_result = item.payload
        finally:
            await stream_client.aclose()

    async def _stream_updates(
        self,
        method: str,
        params: dict | None,
        notification_method: str,
    ) -> AsyncIterator[dict]:
        """Stream an RPC on a dedicated connection, yielding each matching
        notification's full params dict (not just a content string).

        Used by held feeds like ``operator.watch`` whose notifications carry
        structured payloads. The terminal result is stashed in
        ``_last_stream_result``."""
        stream_client = await self._client_factory()
        try:
            async for item in stream_client.stream(method, params, read_timeout=None):
                if item.kind == "notification" and item.method == notification_method:
                    yield item.payload if isinstance(item.payload, dict) else {}
                elif item.kind == "result":
                    self._last_stream_result = item.payload
        finally:
            await stream_client.aclose()

    # ========================================================================
    # Governed-shell operator surface (GS-2..GS-6) — used by the desk (GS-11+)
    # ========================================================================

    async def operator_decisions_list(self, kinds: list[str] | None = None) -> dict:
        """The unified decision feed (operator.decisions.list). Returns
        ``{items, count}`` per shell-contract §2."""
        params: dict[str, Any] = {}
        if kinds is not None:
            params["kinds"] = kinds
        return await self._call("operator.decisions.list", params)

    async def operator_decisions_resolve(
        self, decision_id: str, option_key: str, args: dict | None = None
    ) -> dict:
        """Resolve a decision — THE one mutation door (operator.decisions.resolve).

        Routes by the item's kind + chosen option to the backing subsystem; the
        daemon mints the receipt and applies any refusal. Maude only relays the
        operator's chosen ``option_key`` (from the envelope) — it decides
        nothing."""
        params: dict[str, Any] = {"decision_id": decision_id, "option_key": option_key}
        if args is not None:
            params["args"] = args
        return await self._call("operator.decisions.resolve", params)

    async def operator_watch(
        self,
        kinds: list[str] | None = None,
        *,
        interval_ms: int | None = None,
        max_ticks: int | None = None,
    ) -> AsyncIterator[dict]:
        """Stream the decision feed. Yields each ``operator.watch.update``
        payload — a FULL feed snapshot ``{items, count, tick, changed}`` (the
        daemon dedups by content, not incremental events). The stream is bounded
        (``max_ticks``); the caller re-subscribes to keep watching."""
        params: dict[str, Any] = {}
        if kinds is not None:
            params["kinds"] = kinds
        if interval_ms is not None:
            params["interval_ms"] = interval_ms
        if max_ticks is not None:
            params["max_ticks"] = max_ticks
        async for update in self._stream_updates(
            "operator.watch", params, "operator.watch.update"
        ):
            yield update

    async def runtime_session_send_input(self, session_id: str, text: str) -> dict:
        """Steer a running session (runtime.session.send_input). Downstream tool
        calls stay fully intercepted — steering widens nothing."""
        return await self._call(
            "runtime.session.send_input", {"session_id": session_id, "text": text}
        )

    async def runtime_adapters_list(self) -> dict:
        """List harness adapters + declared capabilities (runtime.adapters.list).
        Introspection only — adapters are AG's, below the authority gate."""
        return await self._call("runtime.adapters.list", {})

    async def why_chain(self, receipt_id: str, max_depth: int | None = None) -> dict:
        """Walk a receipt's chain (why.chain) for the `w` overlay."""
        params: dict[str, Any] = {"receipt_id": receipt_id}
        if max_depth is not None:
            params["max_depth"] = max_depth
        return await self._call("why.chain", params)

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
    # Chat (governed generation) — legacy, removal at GS-15
    # ========================================================================

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        model: str = "",
        context_id: str = "default",
        *,
        use_lanes: bool = False,
        task_hint: str = "",
        risk_class: str = "",
    ) -> AsyncIterator[str]:
        """Stream governed chat completions, yielding content deltas."""
        params: dict[str, Any] = {
            "messages": messages, "model": model, "context_id": context_id,
        }
        if use_lanes:
            params["use_lanes"] = True
        if task_hint:
            params["task_hint"] = task_hint
        if risk_class:
            params["risk_class"] = risk_class
        async for delta in self._call_streaming(
            "chat.stream",
            params,
            notification_method="chat.delta",
        ):
            yield delta

    async def chat_send(
        self,
        messages: list[dict[str, str]],
        model: str = "",
        context_id: str = "default",
        *,
        use_lanes: bool = False,
        task_hint: str = "",
        risk_class: str = "",
    ) -> dict:
        """Non-streaming governed chat. Returns full result dict."""
        params: dict[str, Any] = {
            "messages": messages, "model": model, "context_id": context_id,
        }
        if use_lanes:
            params["use_lanes"] = True
        if task_hint:
            params["task_hint"] = task_hint
        if risk_class:
            params["risk_class"] = risk_class
        return await self._call("chat.send", params)

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
    # Chain composition (Phase 2C/2D)
    # ========================================================================

    async def chain_preflight(
        self,
        tool_id: str,
        correlation_id: str,
        args: dict | None = None,
        exceptions: list[str] | None = None,
    ) -> ChainPreflightDecision:
        """Call chain.preflight — pre-dispatch composition evaluation."""
        params: dict[str, Any] = {
            "tool_id": tool_id,
            "correlation_id": correlation_id,
        }
        if args:
            params["args"] = args
        if exceptions:
            params["exceptions"] = exceptions
        result = await self._call("chain.preflight", params)
        return ChainPreflightDecision.model_validate(result)

    async def chain_record(
        self,
        tool_id: str,
        correlation_id: str,
        result_status: str,
        args: dict | None = None,
        preflight_token: str | None = None,
        record_id: str | None = None,
    ) -> ChainRecordResult:
        """Call chain.record — post-dispatch action recording."""
        params: dict[str, Any] = {
            "tool_id": tool_id,
            "correlation_id": correlation_id,
            "result_status": result_status,
        }
        if args:
            params["args"] = args
        if preflight_token:
            params["preflight_token"] = preflight_token
        if record_id:
            params["record_id"] = record_id
        result = await self._call("chain.record", params)
        return ChainRecordResult.model_validate(result)

    async def chain_status(
        self,
        correlation_id: str | None = None,
    ) -> ChainStatus:
        """Call chain.status — get chain gate status and optional log info."""
        params: dict[str, Any] = {}
        if correlation_id:
            params["correlation_id"] = correlation_id
        result = await self._call("chain.status", params)
        return ChainStatus.model_validate(result)

    # ========================================================================
    # Stubs for HTTP-era methods (legacy PLAN/BUILD, removal at GS-15)
    # ========================================================================

    async def append_message(self, session_id: str, role: str, content: str,
                             model: str | None = None, usage: dict[str, int] | None = None) -> None:
        """No-op: daemon manages session persistence internally."""

    async def add_constraint(self, constraint: str, patterns: list[str] | None = None) -> dict:
        """Stub: constraint submission not wired to daemon RPC."""
        return {"status": "stub"}

    async def create_run(self, task: str, profile: str = "established", scope: str | None = None) -> dict:
        """Stub: v2 runs not wired to daemon RPC."""
        return {"status": "stub"}

    async def dashboard_summary(self) -> DashboardSummary:
        """Stub: dashboard not wired to daemon RPC."""
        return DashboardSummary()

    async def list_runs(self) -> list:
        """Stub: v2 run list not wired to daemon RPC."""
        return []

    # --- Operator snapshot ---

    async def operator_snapshot(self) -> dict:
        return await self._call("operator.snapshot", {})

    # --- Runtime Supervisor ---

    async def runtime_session_create(
        self,
        backend_kind: str = "claude_code",
        cwd: str | None = None,
        task: str | None = None,
        operator_mode: str = "interactive",
        allow_dirty: bool = False,
        harness_args: list[str] | None = None,
    ) -> dict:
        params: dict[str, Any] = {"backend_kind": backend_kind, "operator_mode": operator_mode}
        if cwd:
            params["cwd"] = cwd
        if task:
            params["task"] = task
        if allow_dirty:
            params["allow_dirty"] = True
        if harness_args:
            # NS-0: operator-chosen extra backend argv (e.g. --model). Carries
            # no authority — the daemon validates strings-only, fail closed.
            params["harness_args"] = list(harness_args)
        return await self._call("runtime.session.create", params)

    async def runtime_grant_activate(
        self,
        session_id: str,
        execution_request: dict[str, Any],
        witness_bytes: str | None = None,
    ) -> dict:
        """S4: attach an execution grant (approval compression) to a session.
        The daemon re-verifies ``witness_bytes`` against the request's
        ``approval_witness_digest`` — a forged digest is refused there."""
        params: dict[str, Any] = {
            "session_id": session_id,
            "execution_request": execution_request,
        }
        if witness_bytes is not None:
            params["witness_bytes"] = witness_bytes
        return await self._call("runtime.grant.activate", params)

    async def runtime_grant_get(self, session_id: str) -> dict | None:
        """S4: the execution grant attached to a session + recent grant-use
        dispositions (accepted / widens / unverifiable). Read-only."""
        return await self._call("runtime.grant.get", {"session_id": session_id})

    async def runtime_session_launch(self, session_id: str) -> dict:
        return await self._call("runtime.session.launch", {"session_id": session_id})

    async def runtime_session_get(self, session_id: str) -> dict | None:
        return await self._call("runtime.session.get", {"session_id": session_id})

    async def runtime_session_list(self) -> list[dict]:
        return await self._call("runtime.session.list", {})

    async def runtime_session_events(
        self, session_id: str, since_seq: int = 0, limit: int = 100
    ) -> list[dict]:
        return await self._call("runtime.session.events", {
            "session_id": session_id, "since_seq": since_seq, "limit": limit,
        })

    async def runtime_session_pause(self, session_id: str) -> dict:
        return await self._call("runtime.session.pause", {"session_id": session_id})

    async def runtime_session_resume(self, session_id: str) -> dict:
        return await self._call("runtime.session.resume", {"session_id": session_id})

    async def runtime_session_kill(self, session_id: str) -> dict:
        return await self._call("runtime.session.kill", {"session_id": session_id})

    async def runtime_intervention_list(self, session_id: str) -> list[dict]:
        return await self._call("runtime.intervention.list", {"session_id": session_id})

    async def runtime_intervention_resolve(
        self, session_id: str, tool_call_id: str, decision: str, reason: str | None = None
    ) -> dict:
        params: dict[str, Any] = {
            "session_id": session_id,
            "tool_call_id": tool_call_id,
            "decision": decision,
        }
        if reason:
            params["reason"] = reason
        return await self._call("runtime.intervention.resolve", params)

    async def runtime_promotion_get(self, session_id: str) -> dict | None:
        return await self._call("runtime.promotion.get", {"session_id": session_id})

    async def runtime_promotion_diff(self, session_id: str) -> dict:
        return await self._call("runtime.promotion.diff", {"session_id": session_id})

    async def runtime_promotion_resolve(
        self, session_id: str, decision: str, reason: str | None = None
    ) -> dict:
        params: dict[str, Any] = {"session_id": session_id, "decision": decision}
        if reason:
            params["reason"] = reason
        return await self._call("runtime.promotion.resolve", params)

    async def runtime_session_fork(
        self, parent_session_id: str, task: str | None = None
    ) -> dict:
        params: dict[str, Any] = {"parent_session_id": parent_session_id}
        if task:
            params["task"] = task
        return await self._call("runtime.session.fork", params)

    async def runtime_budget_get(self, session_id: str) -> dict | None:
        return await self._call("runtime.budget.get", {"session_id": session_id})
