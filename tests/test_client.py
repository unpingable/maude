"""Tests for client model deserialization."""

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


class TestHealthResponse:
    def test_deserialize(self):
        data = {
            "status": "healthy",
            "backend": {"type": "ollama", "connected": True},
            "governor": {
                "context_id": "default",
                "mode": "code",
                "initialized": True,
            },
        }
        h = HealthResponse.model_validate(data)
        assert h.status == "healthy"
        assert h.backend.type == "ollama"
        assert h.backend.connected is True
        assert h.governor.context_id == "default"
        assert h.governor.mode == "code"
        assert h.governor.initialized is True

    def test_degraded(self):
        data = {
            "status": "degraded",
            "backend": {"type": "anthropic", "connected": False},
            "governor": {
                "context_id": "test",
                "mode": "fiction",
                "initialized": False,
            },
        }
        h = HealthResponse.model_validate(data)
        assert h.status == "degraded"
        assert h.backend.connected is False


class TestSessionModels:
    def test_session_summary(self):
        data = {
            "id": "abc123",
            "context_id": "default",
            "title": "Test session",
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T01:00:00Z",
            "model": "llama3.2",
            "message_count": 5,
        }
        s = SessionSummary.model_validate(data)
        assert s.id == "abc123"
        assert s.message_count == 5

    def test_session_message(self):
        data = {
            "id": "msg001",
            "role": "user",
            "content": "Hello",
            "timestamp": "2025-01-01T00:00:00Z",
        }
        m = SessionMessage.model_validate(data)
        assert m.role == "user"
        assert m.model is None
        assert m.usage is None

    def test_session_message_with_optional(self):
        data = {
            "id": "msg002",
            "role": "assistant",
            "content": "Hi there",
            "timestamp": "2025-01-01T00:00:01Z",
            "model": "llama3.2",
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        m = SessionMessage.model_validate(data)
        assert m.model == "llama3.2"
        assert m.usage["total_tokens"] == 15

    def test_chat_session(self):
        data = {
            "id": "sess001",
            "context_id": "default",
            "title": "Full session",
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T01:00:00Z",
            "model": "llama3.2",
            "message_count": 2,
            "messages": [
                {
                    "id": "m1",
                    "role": "user",
                    "content": "Hi",
                    "timestamp": "2025-01-01T00:00:00Z",
                },
                {
                    "id": "m2",
                    "role": "assistant",
                    "content": "Hello!",
                    "timestamp": "2025-01-01T00:00:01Z",
                    "model": "llama3.2",
                },
            ],
        }
        cs = ChatSession.model_validate(data)
        assert len(cs.messages) == 2
        assert cs.messages[0].role == "user"
        assert cs.messages[1].model == "llama3.2"


class TestGovernorNow:
    def test_deserialize(self):
        data = {
            "context_id": "default",
            "status": "ok",
            "sentence": "OK: no violations.",
            "last_event": None,
            "suggested_action": None,
            "regime": None,
            "mode": "code",
        }
        now = GovernorNow.model_validate(data)
        assert now.status == "ok"
        assert now.mode == "code"
        assert now.regime is None

    def test_with_values(self):
        data = {
            "context_id": "project-x",
            "status": "warning",
            "sentence": "1 violation pending.",
            "last_event": {"type": "violation", "id": "v1"},
            "suggested_action": "Review violation v1",
            "regime": "strict",
            "mode": "fiction",
        }
        now = GovernorNow.model_validate(data)
        assert now.regime == "strict"
        assert now.last_event["type"] == "violation"
        assert now.suggested_action == "Review violation v1"


class TestStreamChunk:
    def test_deserialize(self):
        data = {
            "id": "chatcmpl-abc",
            "object": "chat.completion.chunk",
            "created": 1700000000,
            "model": "llama3.2",
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": "Hello"},
                    "finish_reason": None,
                }
            ],
        }
        chunk = StreamChunk.model_validate(data)
        assert chunk.choices[0].delta.content == "Hello"
        assert chunk.choices[0].finish_reason is None

    def test_empty_delta(self):
        data = {
            "id": "chatcmpl-abc",
            "object": "chat.completion.chunk",
            "created": 1700000000,
            "model": "llama3.2",
            "choices": [
                {
                    "index": 0,
                    "delta": {},
                    "finish_reason": "stop",
                }
            ],
        }
        chunk = StreamChunk.model_validate(data)
        assert chunk.choices[0].delta.content is None
        assert chunk.choices[0].finish_reason == "stop"


class TestRunSummary:
    def test_deserialize(self):
        data = {
            "run_id": "run-001",
            "created_at": "2025-01-01T00:00:00Z",
            "model": "llama3.2",
            "profile": "established",
            "verdict": "pass",
            "claim_count": 3,
            "violation_count": 0,
            "duration_ms": 1234.5,
            "task": "test task",
        }
        r = RunSummary.model_validate(data)
        assert r.run_id == "run-001"
        assert r.verdict == "pass"
        assert r.claim_count == 3

    def test_defaults(self):
        data = {"run_id": "run-002"}
        r = RunSummary.model_validate(data)
        assert r.verdict == "pending"
        assert r.claim_count == 0


class TestDashboardSummary:
    def test_deserialize(self):
        data = {
            "total_runs": 10,
            "passed": 8,
            "failed": 1,
            "cancelled": 1,
            "pass_rate": 0.8,
            "total_claims": 25,
            "total_violations": 3,
            "active_run": None,
        }
        ds = DashboardSummary.model_validate(data)
        assert ds.total_runs == 10
        assert ds.pass_rate == 0.8
        assert ds.active_run is None
