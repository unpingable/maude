"""Tests for session state management."""

import pytest

from maude.session import MaudeSession, Mode


class TestMaudeSession:
    def test_default_state(self):
        s = MaudeSession()
        assert s.mode == Mode.PLAN
        assert s.governor_session_id is None
        assert s.spec_draft == ""
        assert not s.spec_locked
        assert s.messages == []

    def test_add_message(self):
        s = MaudeSession()
        s.add_message("user", "hello")
        s.add_message("assistant", "hi there")
        assert len(s.messages) == 2
        assert s.messages[0] == {"role": "user", "content": "hello"}
        assert s.messages[1] == {"role": "assistant", "content": "hi there"}

    def test_lock_unlock_spec(self):
        s = MaudeSession()
        assert not s.spec_locked
        s.lock_spec()
        assert s.spec_locked
        s.unlock_spec()
        assert not s.spec_locked

    def test_set_mode_plan_to_build_requires_lock(self):
        s = MaudeSession()
        with pytest.raises(ValueError, match="locked spec"):
            s.set_mode(Mode.BUILD)

    def test_set_mode_plan_to_build_with_lock(self):
        s = MaudeSession()
        s.lock_spec()
        s.set_mode(Mode.BUILD)
        assert s.mode == Mode.BUILD

    def test_set_mode_build_to_plan(self):
        s = MaudeSession()
        s.lock_spec()
        s.set_mode(Mode.BUILD)
        s.set_mode(Mode.PLAN)
        assert s.mode == Mode.PLAN

    def test_status_line_default(self):
        s = MaudeSession()
        line = s.status_line()
        assert "MODE=PLAN" in line
        assert "SPEC=UNLOCKED" in line
        assert "SESSION=none" in line

    def test_status_line_with_session(self):
        s = MaudeSession(governor_session_id="abc123")
        line = s.status_line()
        assert "SESSION=abc123" in line

    def test_status_line_locked_spec(self):
        s = MaudeSession()
        s.lock_spec()
        line = s.status_line()
        assert "SPEC=LOCKED" in line

    def test_status_line_build_mode(self):
        s = MaudeSession()
        s.lock_spec()
        s.set_mode(Mode.BUILD)
        line = s.status_line()
        assert "MODE=BUILD" in line

    def test_status_line_with_governor_now(self):
        class FakeNow:
            status = "ok"
        s = MaudeSession()
        s.last_governor_now = FakeNow()
        line = s.status_line()
        assert "GOV=ok" in line
