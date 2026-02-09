"""Tests for client model deserialization."""

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


class TestIntentTemplateList:
    def test_deserialize(self):
        data = {
            "templates": [
                {"name": "session_start", "description": "Initialize a governance session"},
                {"name": "task_scope", "description": "Scope a specific task"},
                {"name": "verification_config", "description": "Configure verification"},
            ]
        }
        tl = IntentTemplateList.model_validate(data)
        assert len(tl.templates) == 3
        assert tl.templates[0].name == "session_start"

    def test_empty(self):
        data = {"templates": []}
        tl = IntentTemplateList.model_validate(data)
        assert len(tl.templates) == 0


class TestIntentFormSchema:
    def test_deserialize(self):
        data = {
            "schema_id": "abc123def456",
            "template_name": "session_start",
            "mode": "general",
            "policy": "template_only",
            "fields": [
                {
                    "field_id": "profile",
                    "widget": "select_one",
                    "label": "Profile",
                    "options": [
                        {"value": "strict", "label": "Strict", "confidence": 0.8, "branch_id": "b1"},
                    ],
                    "required": True,
                    "help_text": "Select a profile",
                },
            ],
            "branches": [
                {
                    "branch_id": "b1",
                    "name": "Strict",
                    "description": "Full enforcement",
                    "confidence": 0.8,
                    "constraints_implied": ["c1"],
                    "fields_affected": ["profile"],
                },
            ],
            "escape_enabled": True,
        }
        schema = IntentFormSchema.model_validate(data)
        assert schema.schema_id == "abc123def456"
        assert schema.template_name == "session_start"
        assert schema.policy == "template_only"
        assert len(schema.fields) == 1
        assert schema.fields[0].field_id == "profile"
        assert len(schema.fields[0].options) == 1
        assert schema.fields[0].options[0].confidence == 0.8
        assert len(schema.branches) == 1
        assert schema.branches[0].confidence == 0.8

    def test_minimal(self):
        data = {
            "schema_id": "x",
            "template_name": "t",
            "mode": "general",
            "policy": "template_only",
            "fields": [],
            "branches": [],
        }
        schema = IntentFormSchema.model_validate(data)
        assert schema.escape_enabled is True  # default


class TestIntentValidationResult:
    def test_valid(self):
        data = {"valid": True, "errors": []}
        r = IntentValidationResult.model_validate(data)
        assert r.valid is True
        assert r.errors == []

    def test_invalid(self):
        data = {"valid": False, "errors": ["profile: invalid value 'bogus'"]}
        r = IntentValidationResult.model_validate(data)
        assert r.valid is False
        assert len(r.errors) == 1


class TestIntentCompilationResult:
    def test_deserialize(self):
        data = {
            "intent_profile": "strict",
            "intent_scope": ["src/**"],
            "intent_deny": None,
            "intent_timebox_minutes": 120,
            "constraint_block": None,
            "selected_branch": "strict_branch",
            "escape_classification": None,
            "warnings": [],
            "receipt_hash": "a" * 64,
        }
        r = IntentCompilationResult.model_validate(data)
        assert r.intent_profile == "strict"
        assert r.intent_scope == ["src/**"]
        assert r.intent_timebox_minutes == 120
        assert len(r.receipt_hash) == 64

    def test_defaults(self):
        data = {}
        r = IntentCompilationResult.model_validate(data)
        assert r.intent_profile == ""
        assert r.warnings == []

    def test_with_escape(self):
        data = {
            "intent_profile": "strict",
            "escape_classification": "waiver_candidate",
            "receipt_hash": "b" * 64,
        }
        r = IntentCompilationResult.model_validate(data)
        assert r.escape_classification == "waiver_candidate"


class TestIntentPolicy:
    def test_deserialize(self):
        data = {"mode": "general", "policy": "template_only"}
        p = IntentPolicy.model_validate(data)
        assert p.mode == "general"
        assert p.policy == "template_only"

    def test_fiction_mode(self):
        data = {"mode": "fiction", "policy": "custom_ok"}
        p = IntentPolicy.model_validate(data)
        assert p.policy == "custom_ok"
