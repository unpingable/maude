"""Async HTTP client for the governor API."""

from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from maude.client.models import (
    ChatSession,
    DashboardSummary,
    GovernorNow,
    HealthResponse,
    RunSummary,
    SessionMessage,
    SessionSummary,
    StreamChunk,
)


class GovernorClient:
    """Async HTTP client for governor v1 and v2 endpoints."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        timeout: float = 30.0,
        token: str | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.AsyncClient(
            base_url=self.base_url, timeout=timeout, headers=headers
        )

    async def close(self) -> None:
        await self._client.aclose()

    # ========================================================================
    # V1 endpoints (MVP)
    # ========================================================================

    async def health(self) -> HealthResponse:
        resp = await self._client.get("/health")
        resp.raise_for_status()
        return HealthResponse.model_validate(resp.json())

    async def list_sessions(self) -> list[SessionSummary]:
        resp = await self._client.get("/sessions/")
        resp.raise_for_status()
        data = resp.json()
        return [SessionSummary.model_validate(s) for s in data.get("sessions", [])]

    async def create_session(
        self, title: str = "New conversation", model: str = ""
    ) -> ChatSession:
        resp = await self._client.post(
            "/sessions/", json={"title": title, "model": model}
        )
        resp.raise_for_status()
        return ChatSession.model_validate(resp.json())

    async def get_session(self, session_id: str) -> ChatSession:
        resp = await self._client.get(f"/sessions/{session_id}")
        resp.raise_for_status()
        return ChatSession.model_validate(resp.json())

    async def delete_session(self, session_id: str) -> bool:
        resp = await self._client.delete(f"/sessions/{session_id}")
        return resp.status_code == 200

    async def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        model: str | None = None,
        usage: dict[str, int] | None = None,
    ) -> SessionMessage:
        payload: dict = {"role": role, "content": content}
        if model is not None:
            payload["model"] = model
        if usage is not None:
            payload["usage"] = usage
        resp = await self._client.post(
            f"/sessions/{session_id}/messages", json=payload
        )
        resp.raise_for_status()
        return SessionMessage.model_validate(resp.json())

    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        model: str = "",
    ) -> AsyncIterator[str]:
        """Stream chat completions, yielding content deltas."""
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
        }
        async with self._client.stream(
            "POST", "/v1/chat/completions", json=payload, timeout=120.0
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str == "[DONE]":
                    break
                try:
                    chunk = StreamChunk.model_validate(json.loads(data_str))
                    for choice in chunk.choices:
                        if choice.delta.content:
                            yield choice.delta.content
                except (json.JSONDecodeError, Exception):
                    continue

    async def governor_now(self) -> GovernorNow:
        resp = await self._client.get("/governor/now")
        resp.raise_for_status()
        return GovernorNow.model_validate(resp.json())

    async def governor_status(self) -> dict:
        resp = await self._client.get("/governor/status")
        resp.raise_for_status()
        return resp.json()

    async def add_constraint(
        self, constraint: str, patterns: list[str] | None = None
    ) -> dict:
        payload: dict = {"constraint": constraint}
        if patterns is not None:
            payload["patterns"] = patterns
        resp = await self._client.post("/governor/code/constraints", json=payload)
        resp.raise_for_status()
        return resp.json()

    async def list_constraints(self) -> list[dict]:
        resp = await self._client.get("/governor/code/constraints")
        resp.raise_for_status()
        data = resp.json()
        # Server returns {"constraints": [...]} — unwrap to match return type
        if isinstance(data, dict):
            return data.get("constraints", [])
        return data

    # ========================================================================
    # V2 endpoints (stubbed for future)
    # ========================================================================

    async def list_runs(self, limit: int = 50) -> list[RunSummary]:
        # TODO: v2 run management
        resp = await self._client.get("/v2/runs", params={"limit": limit})
        resp.raise_for_status()
        data = resp.json()
        return [RunSummary.model_validate(r) for r in data.get("runs", [])]

    async def create_run(
        self, task: str, profile: str = "established", scope: str | None = None
    ) -> dict:
        # TODO: v2 run creation
        payload: dict = {"task": task, "profile": profile}
        if scope is not None:
            payload["scope"] = scope
        resp = await self._client.post("/v2/runs", json=payload)
        resp.raise_for_status()
        return resp.json()

    async def stream_run_events(self, run_id: str) -> AsyncIterator[dict]:
        # TODO: v2 run event streaming
        async with self._client.stream(
            "GET", f"/v2/runs/{run_id}/events", params={"stream": "true"}
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str == "[DONE]":
                    break
                try:
                    yield json.loads(data_str)
                except json.JSONDecodeError:
                    continue

    async def dashboard_summary(self) -> DashboardSummary:
        # TODO: v2 dashboard
        resp = await self._client.get("/v2/dashboard/summary")
        resp.raise_for_status()
        return DashboardSummary.model_validate(resp.json())
