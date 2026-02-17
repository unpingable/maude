# SPDX-License-Identifier: Apache-2.0
"""Tests for session state management."""

import os

import pytest

from maude.config import Settings
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

    # Template support

    def test_load_template(self):
        s = MaudeSession()
        s.load_template("architecture", "# Arch Template\n...")
        assert s.spec_template == "architecture"
        assert s.spec_template_content == "# Arch Template\n..."

    def test_clear_template(self):
        s = MaudeSession()
        s.load_template("architecture", "content")
        s.clear_template()
        assert s.spec_template is None
        assert s.spec_template_content == ""

    def test_status_line_with_template(self):
        s = MaudeSession()
        s.load_template("architecture", "content")
        line = s.status_line()
        assert "TEMPLATE=architecture" in line

    def test_status_line_without_template(self):
        s = MaudeSession()
        line = s.status_line()
        assert "TEMPLATE" not in line

    def test_lock_spec_returns_draft(self):
        s = MaudeSession()
        s.spec_draft = "my spec content"
        result = s.lock_spec()
        assert result == "my spec content"
        assert s.spec_locked

    # Session identity

    def test_status_line_with_project_name(self):
        s = MaudeSession(project_name="agent_gov")
        line = s.status_line()
        assert line.startswith("agent_gov")

    def test_status_line_with_backend_type(self):
        s = MaudeSession(backend_type="claude")
        line = s.status_line()
        assert "claude" in line

    def test_status_line_with_project_and_backend(self):
        s = MaudeSession(project_name="agent_gov", backend_type="claude")
        line = s.status_line()
        assert "agent_gov" in line
        assert "claude" in line
        # Project comes before backend
        assert line.index("agent_gov") < line.index("claude")

    def test_status_line_identity_before_mode(self):
        s = MaudeSession(project_name="myproj", backend_type="ollama")
        line = s.status_line()
        assert line.index("myproj") < line.index("MODE=")
        assert line.index("ollama") < line.index("MODE=")

    def test_title_line_bare(self):
        s = MaudeSession()
        assert s.title_line() == "maude"

    def test_title_line_with_project(self):
        s = MaudeSession(project_name="agent_gov")
        assert s.title_line() == "maude — agent_gov"

    def test_title_line_with_project_and_backend(self):
        s = MaudeSession(project_name="agent_gov", backend_type="claude")
        assert s.title_line() == "maude — agent_gov | claude"

    def test_title_line_backend_only(self):
        s = MaudeSession(backend_type="ollama")
        assert s.title_line() == "maude — ollama"


class TestSettingsProjectName:
    def test_project_name_from_governor_dir(self):
        s = Settings(governor_dir="/home/jbeck/git/agent_gov/.governor")
        assert s.project_name == "agent_gov"

    def test_project_name_from_dir_without_dot_governor(self):
        s = Settings(governor_dir="/home/jbeck/git/agent_gov")
        assert s.project_name == "agent_gov"

    def test_project_name_empty_when_no_dir(self):
        s = Settings(governor_dir="")
        assert s.project_name == ""

    def test_label_default_empty(self, monkeypatch):
        monkeypatch.delenv("MAUDE_LABEL", raising=False)
        s = Settings(label="")
        assert s.label == ""

    def test_label_from_env(self, monkeypatch):
        monkeypatch.setenv("MAUDE_LABEL", "detector-work")
        s = Settings()
        assert s.label == "detector-work"

    def test_label_from_init(self):
        s = Settings(label="my-session")
        assert s.label == "my-session"
