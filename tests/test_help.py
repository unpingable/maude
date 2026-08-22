# SPDX-License-Identifier: Apache-2.0
"""Progressive-disclosure help remains explicit without flooding a terminal."""

from maude.app import _HELP_TEXT, _WELCOME_TEXT, _help_text


def test_default_help_fits_a_24_line_terminal_and_points_to_drilldown():
    assert len(_HELP_TEXT.splitlines()) <= 20
    assert "run <plan.md>" in _HELP_TEXT
    assert "sessions" in _HELP_TEXT
    assert "help all" in _HELP_TEXT
    assert "draft new <goal>" in _HELP_TEXT
    assert "plan architecture" not in _HELP_TEXT
    assert "delete session" not in _HELP_TEXT


def test_first_run_guidance_has_three_supported_entry_points():
    assert "draft new <goal>" in _WELCOME_TEXT
    assert "run <plan.md>" in _WELCOME_TEXT
    assert "go <task>" in _WELCOME_TEXT
    assert "sessions" in _WELCOME_TEXT
    assert "Page Up/Down" in _WELCOME_TEXT


def test_help_topics_preserve_explicit_command_categories():
    assert "same revision boundary" in _help_text("draft")
    assert "exact supervised-run ingress" in _help_text("plan")
    assert "local Governor tool decisions" in _help_text("run")
    assert "lineage" in _help_text("sessions")
    assert "unsupported legacy" in _help_text("all").lower()


def test_unknown_help_topic_fails_visible_instead_of_becoming_chat():
    text = _help_text("magic")
    assert "Unknown help topic" in text
    assert "draft, plan, run, sessions, all" in text
