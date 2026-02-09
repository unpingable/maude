"""Integration tests — require a live governor.

Run via:
    bash test-with-governor.sh           # starts governor, runs all tests
    bash test-with-governor.sh --mock    # degraded mode (no LLM)

Or manually:
    GOVERNOR_URL=http://127.0.0.1:8000 python3 -m pytest tests/test_integration.py -v

Skipped automatically when GOVERNOR_URL is not set.
"""

from __future__ import annotations

import os

import pytest

from maude.client.http import GovernorClient
from maude.client.models import (
    ChatSession,
    GovernorNow,
    HealthResponse,
    IntentCompilationResult,
    IntentFormSchema,
    IntentPolicy,
    IntentTemplateList,
    IntentValidationResult,
    SessionMessage,
    SessionSummary,
)

_skip_no_governor = pytest.mark.skipif(
    os.environ.get("GOVERNOR_URL") is None,
    reason="GOVERNOR_URL not set — run via test-with-governor.sh",
)


# ============================================================================
# Health
# ============================================================================

pytestmark = _skip_no_governor


class TestHealth:
    async def test_health_returns_response(self, client: GovernorClient):
        health = await client.health()
        assert isinstance(health, HealthResponse)

    async def test_health_has_required_fields(self, client: GovernorClient):
        health = await client.health()
        assert health.status in ("ok", "degraded", "error")
        assert isinstance(health.backend.type, str)
        assert isinstance(health.backend.connected, bool)
        assert isinstance(health.governor.context_id, str)
        assert isinstance(health.governor.mode, str)
        assert isinstance(health.governor.initialized, bool)

    async def test_health_backend_type_known(self, client: GovernorClient):
        health = await client.health()
        assert health.backend.type in (
            "anthropic", "ollama", "claude-code", "codex"
        )


# ============================================================================
# Sessions — full CRUD lifecycle
# ============================================================================


class TestSessionLifecycle:
    async def test_list_sessions_initially(self, client: GovernorClient):
        sessions = await client.list_sessions()
        assert isinstance(sessions, list)
        for s in sessions:
            assert isinstance(s, SessionSummary)

    async def test_create_session(self, client: GovernorClient):
        session = await client.create_session(title="integration-test")
        assert isinstance(session, ChatSession)
        assert session.title == "integration-test"
        assert session.id  # non-empty
        assert session.context_id  # non-empty

    async def test_get_session(self, client: GovernorClient):
        created = await client.create_session(title="get-test")
        fetched = await client.get_session(created.id)
        assert isinstance(fetched, ChatSession)
        assert fetched.id == created.id
        assert fetched.title == "get-test"

    async def test_list_includes_created(self, client: GovernorClient):
        created = await client.create_session(title="list-test")
        sessions = await client.list_sessions()
        ids = [s.id for s in sessions]
        assert created.id in ids

    async def test_delete_session(self, client: GovernorClient):
        created = await client.create_session(title="delete-test")
        result = await client.delete_session(created.id)
        assert result is True

    async def test_delete_nonexistent(self, client: GovernorClient):
        result = await client.delete_session("nonexistent-id-12345")
        assert result is False

    async def test_append_message(self, client: GovernorClient):
        session = await client.create_session(title="append-test")
        msg = await client.append_message(
            session_id=session.id,
            role="user",
            content="Hello from integration test",
        )
        assert isinstance(msg, SessionMessage)
        assert msg.role == "user"
        assert msg.content == "Hello from integration test"
        assert msg.id  # non-empty
        assert msg.timestamp  # non-empty

    async def test_append_message_with_model(self, client: GovernorClient):
        session = await client.create_session(title="append-model-test")
        msg = await client.append_message(
            session_id=session.id,
            role="assistant",
            content="Response with model tag",
            model="test-model",
        )
        assert msg.model == "test-model"

    async def test_append_message_with_usage(self, client: GovernorClient):
        session = await client.create_session(title="append-usage-test")
        usage = {"prompt_tokens": 10, "completion_tokens": 20}
        msg = await client.append_message(
            session_id=session.id,
            role="assistant",
            content="Response with usage",
            usage=usage,
        )
        assert msg.usage == usage

    async def test_get_session_with_messages(self, client: GovernorClient):
        session = await client.create_session(title="messages-test")
        await client.append_message(session.id, "user", "first")
        await client.append_message(session.id, "assistant", "second")
        fetched = await client.get_session(session.id)
        assert len(fetched.messages) == 2
        assert fetched.messages[0].content == "first"
        assert fetched.messages[1].content == "second"


# ============================================================================
# Governor state
# ============================================================================


class TestGovernorState:
    async def test_governor_now(self, client: GovernorClient):
        now = await client.governor_now()
        assert isinstance(now, GovernorNow)
        assert now.status in ("ok", "needs_attention", "blocked")
        assert isinstance(now.sentence, str)
        assert isinstance(now.mode, str)
        assert isinstance(now.context_id, str)

    async def test_governor_status_returns_dict(self, client: GovernorClient):
        status = await client.governor_status()
        assert isinstance(status, dict)
        # Should have at least context_id and mode
        assert "context_id" in status or "mode" in status or "initialized" in status


# ============================================================================
# Constraints
# ============================================================================


class TestConstraints:
    async def test_list_constraints_returns_list(self, client: GovernorClient):
        """list_constraints returns a list (possibly empty)."""
        result = await client.list_constraints()
        assert isinstance(result, list)

    async def test_add_and_list_constraint(self, client: GovernorClient):
        """Adding a constraint and listing shows it."""
        # Trigger context auto-creation via dashboard (or it may already exist)
        try:
            await client.dashboard_summary()
        except Exception:
            pass  # Fine if it fails — context may already be created

        result = await client.add_constraint(
            constraint="No eval() calls",
            patterns=["eval("],
        )
        assert isinstance(result, dict)

        constraints = await client.list_constraints()
        assert isinstance(constraints, list)
        assert len(constraints) > 0


# ============================================================================
# V2 Dashboard
# ============================================================================


class TestDashboard:
    async def test_list_runs(self, client: GovernorClient):
        """V2 runs endpoint returns a list (possibly empty)."""
        runs = await client.list_runs()
        assert isinstance(runs, list)

    async def test_dashboard_summary(self, client: GovernorClient):
        """V2 dashboard returns a valid DashboardSummary."""
        from maude.client.models import DashboardSummary
        summary = await client.dashboard_summary()
        assert isinstance(summary, DashboardSummary)
        assert isinstance(summary.total_runs, int)

    async def test_create_run(self, client: GovernorClient):
        """V2 run creation returns a dict with run_id."""
        result = await client.create_run(task="integration test", profile="established")
        assert isinstance(result, dict)
        assert "run_id" in result


# ============================================================================
# Streaming — skipped unless backend is connected
# ============================================================================


# ============================================================================
# Intent Compiler
# ============================================================================


class TestIntentCompiler:
    async def test_list_templates(self, client: GovernorClient):
        result = await client.intent_templates()
        assert isinstance(result, IntentTemplateList)
        assert len(result.templates) == 3
        names = [t.name for t in result.templates]
        assert "session_start" in names
        assert "task_scope" in names
        assert "verification_config" in names

    async def test_template_descriptions(self, client: GovernorClient):
        result = await client.intent_templates()
        for t in result.templates:
            assert len(t.description) > 0

    async def test_get_schema_session_start(self, client: GovernorClient):
        schema = await client.intent_schema("session_start")
        assert isinstance(schema, IntentFormSchema)
        assert schema.template_name == "session_start"
        assert len(schema.fields) == 4
        assert schema.schema_id  # non-empty
        assert schema.policy in ("template_only", "validated_custom", "custom_ok")

    async def test_get_schema_task_scope(self, client: GovernorClient):
        schema = await client.intent_schema("task_scope")
        assert isinstance(schema, IntentFormSchema)
        assert schema.template_name == "task_scope"
        assert len(schema.fields) == 5

    async def test_get_schema_verification_config(self, client: GovernorClient):
        schema = await client.intent_schema("verification_config")
        assert isinstance(schema, IntentFormSchema)
        assert schema.template_name == "verification_config"

    async def test_schema_has_branches(self, client: GovernorClient):
        schema = await client.intent_schema("session_start")
        assert len(schema.branches) >= 2
        for branch in schema.branches:
            assert branch.branch_id
            assert branch.name

    async def test_validate_valid_response(self, client: GovernorClient):
        schema = await client.intent_schema("session_start")
        result = await client.intent_validate(
            schema_id=schema.schema_id,
            values={"profile": "strict", "mode": "general"},
        )
        assert isinstance(result, IntentValidationResult)
        assert result.valid is True
        assert result.errors == []

    async def test_validate_invalid_response(self, client: GovernorClient):
        schema = await client.intent_schema("session_start")
        result = await client.intent_validate(
            schema_id=schema.schema_id,
            values={"profile": "nonexistent", "mode": "general"},
        )
        assert isinstance(result, IntentValidationResult)
        assert result.valid is False
        assert len(result.errors) > 0

    async def test_compile_session_start(self, client: GovernorClient):
        schema = await client.intent_schema("session_start")
        result = await client.intent_compile(
            schema_id=schema.schema_id,
            values={"profile": "strict", "mode": "general"},
            template_name="session_start",
        )
        assert isinstance(result, IntentCompilationResult)
        assert result.intent_profile == "strict"
        assert len(result.receipt_hash) == 64

    async def test_compile_with_scope(self, client: GovernorClient):
        schema = await client.intent_schema("session_start")
        result = await client.intent_compile(
            schema_id=schema.schema_id,
            values={"profile": "strict", "mode": "general", "scope": "src/**,tests/**"},
            template_name="session_start",
        )
        assert result.intent_scope == ["src/**", "tests/**"]

    async def test_compile_with_escape(self, client: GovernorClient):
        schema = await client.intent_schema("session_start")
        result = await client.intent_compile(
            schema_id=schema.schema_id,
            values={"profile": "strict", "mode": "general"},
            template_name="session_start",
            escape_text="allow exception for testing",
        )
        assert result.escape_classification == "waiver_candidate"

    async def test_policy(self, client: GovernorClient):
        policy = await client.intent_policy()
        assert isinstance(policy, IntentPolicy)
        assert policy.mode  # non-empty
        assert policy.policy in ("template_only", "validated_custom", "custom_ok")


# ============================================================================
# Streaming — skipped unless backend is connected
# ============================================================================


class TestStreaming:
    @pytest.mark.skipif(True, reason="Requires connected backend — run manually")
    async def test_chat_stream(self, client: GovernorClient):
        chunks = []
        async for chunk in client.chat_stream(
            messages=[{"role": "user", "content": "Say hello in 5 words."}],
        ):
            chunks.append(chunk)
        assert len(chunks) > 0
        full_response = "".join(chunks)
        assert len(full_response) > 0
