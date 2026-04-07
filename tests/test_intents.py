# SPDX-License-Identifier: Apache-2.0
"""Tests for intent parsing."""

from maude.intents import IntentKind, parse_intent


class TestParseIntent:
    def test_plan(self):
        result = parse_intent("plan build a REST API")
        assert result.kind == IntentKind.PLAN
        assert result.payload == "plan build a REST API"

    def test_lets_plan(self):
        result = parse_intent("let's plan")
        assert result.kind == IntentKind.PLAN

    def test_lock_spec(self):
        result = parse_intent("lock spec")
        assert result.kind == IntentKind.LOCK_SPEC

    def test_freeze_spec(self):
        result = parse_intent("freeze spec")
        assert result.kind == IntentKind.LOCK_SPEC

    def test_build(self):
        result = parse_intent("build")
        assert result.kind == IntentKind.BUILD

    def test_implement(self):
        result = parse_intent("implement")
        assert result.kind == IntentKind.BUILD

    def test_do_it(self):
        result = parse_intent("do it")
        assert result.kind == IntentKind.BUILD

    def test_show_spec(self):
        result = parse_intent("show spec")
        assert result.kind == IntentKind.SHOW_SPEC

    def test_spec(self):
        result = parse_intent("spec")
        assert result.kind == IntentKind.SHOW_SPEC

    def test_show_diff(self):
        result = parse_intent("show diff")
        assert result.kind == IntentKind.SHOW_DIFF

    def test_diff(self):
        result = parse_intent("diff")
        assert result.kind == IntentKind.SHOW_DIFF

    def test_apply(self):
        result = parse_intent("apply")
        assert result.kind == IntentKind.APPLY

    def test_merge(self):
        result = parse_intent("merge")
        assert result.kind == IntentKind.APPLY

    def test_rollback(self):
        result = parse_intent("rollback")
        assert result.kind == IntentKind.ROLLBACK

    def test_undo(self):
        result = parse_intent("undo")
        assert result.kind == IntentKind.ROLLBACK

    def test_why(self):
        result = parse_intent("why")
        assert result.kind == IntentKind.WHY

    def test_why_blocked(self):
        result = parse_intent("why blocked")
        assert result.kind == IntentKind.WHY

    def test_blocked(self):
        result = parse_intent("blocked")
        assert result.kind == IntentKind.WHY

    def test_status(self):
        result = parse_intent("status")
        assert result.kind == IntentKind.STATUS

    def test_state(self):
        result = parse_intent("state")
        assert result.kind == IntentKind.STATUS

    def test_help(self):
        result = parse_intent("help")
        assert result.kind == IntentKind.HELP

    def test_question_mark(self):
        result = parse_intent("?")
        assert result.kind == IntentKind.HELP

    def test_chat_default(self):
        result = parse_intent("tell me about Python decorators")
        assert result.kind == IntentKind.CHAT

    def test_chat_preserves_payload(self):
        result = parse_intent("  hello world  ")
        assert result.kind == IntentKind.CHAT
        assert result.payload == "hello world"

    def test_case_insensitive(self):
        assert parse_intent("PLAN something").kind == IntentKind.PLAN
        assert parse_intent("Status").kind == IntentKind.STATUS
        assert parse_intent("HELP").kind == IntentKind.HELP

    def test_whitespace_handling(self):
        result = parse_intent("  status  ")
        assert result.kind == IntentKind.STATUS

    def test_plan_with_text_is_plan(self):
        result = parse_intent("plan")
        assert result.kind == IntentKind.PLAN

    def test_plan_requires_word_boundary(self):
        result = parse_intent("planning ahead")
        assert result.kind == IntentKind.CHAT

    # Session commands

    def test_sessions(self):
        result = parse_intent("sessions")
        assert result.kind == IntentKind.SESSIONS

    def test_list_sessions(self):
        result = parse_intent("list sessions")
        assert result.kind == IntentKind.SESSIONS

    def test_ls(self):
        result = parse_intent("ls")
        assert result.kind == IntentKind.SESSIONS

    def test_switch_session(self):
        result = parse_intent("switch abc123")
        assert result.kind == IntentKind.SWITCH_SESSION
        assert result.payload == "abc123"

    def test_session_id(self):
        result = parse_intent("session abc123")
        assert result.kind == IntentKind.SWITCH_SESSION
        assert result.payload == "abc123"

    def test_resume_session(self):
        result = parse_intent("resume abc123")
        assert result.kind == IntentKind.SWITCH_SESSION
        assert result.payload == "abc123"

    def test_switch_hash_index(self):
        result = parse_intent("switch #2")
        assert result.kind == IntentKind.SWITCH_SESSION
        assert result.payload == "#2"

    def test_delete_session(self):
        result = parse_intent("delete session abc123")
        assert result.kind == IntentKind.DELETE_SESSION
        assert result.payload == "abc123"

    def test_rm_session(self):
        result = parse_intent("rm session abc123")
        assert result.kind == IntentKind.DELETE_SESSION
        assert result.payload == "abc123"

    def test_session_alone_is_chat(self):
        """'session' alone with no ID falls through to CHAT."""
        result = parse_intent("session")
        assert result.kind == IntentKind.CHAT

    def test_switch_alone_is_chat(self):
        """'switch' alone with no ID falls through to CHAT."""
        result = parse_intent("switch")
        assert result.kind == IntentKind.CHAT

    # Template intents

    def test_plan_architecture(self):
        result = parse_intent("plan architecture")
        assert result.kind == IntentKind.PLAN_TEMPLATE
        assert result.payload == "architecture"

    def test_plan_arch(self):
        result = parse_intent("plan arch")
        assert result.kind == IntentKind.PLAN_TEMPLATE
        assert result.payload == "arch"

    def test_plan_product(self):
        result = parse_intent("plan product")
        assert result.kind == IntentKind.PLAN_TEMPLATE
        assert result.payload == "product"

    def test_plan_product_design(self):
        result = parse_intent("plan product design")
        assert result.kind == IntentKind.PLAN_TEMPLATE
        assert result.payload == "product design"

    def test_plan_requirements(self):
        result = parse_intent("plan requirements")
        assert result.kind == IntentKind.PLAN_TEMPLATE
        assert result.payload == "requirements"

    def test_plan_reqs(self):
        result = parse_intent("plan reqs")
        assert result.kind == IntentKind.PLAN_TEMPLATE
        assert result.payload == "reqs"

    def test_plan_freeform_not_template(self):
        """'plan build a REST API' should match PLAN, not PLAN_TEMPLATE."""
        result = parse_intent("plan build a REST API")
        assert result.kind == IntentKind.PLAN
        assert result.payload == "plan build a REST API"

    def test_clear_template(self):
        result = parse_intent("clear template")
        assert result.kind == IntentKind.CLEAR_TEMPLATE

    # Quick supervised loop aliases
    def test_y_approves(self):
        assert parse_intent("y").kind == IntentKind.QUICK_APPROVE

    def test_yes_approves(self):
        assert parse_intent("yes").kind == IntentKind.QUICK_APPROVE

    def test_approve_approves(self):
        assert parse_intent("approve").kind == IntentKind.QUICK_APPROVE

    def test_n_denies(self):
        assert parse_intent("n").kind == IntentKind.QUICK_DENY

    def test_deny_denies(self):
        assert parse_intent("deny").kind == IntentKind.QUICK_DENY

    def test_p_pending(self):
        assert parse_intent("p").kind == IntentKind.QUICK_PENDING

    def test_pending_pending(self):
        assert parse_intent("pending").kind == IntentKind.QUICK_PENDING

    def test_go_launches(self):
        result = parse_intent("go fix the failing tests")
        assert result.kind == IntentKind.QUICK_LAUNCH
        assert result.payload == "fix the failing tests"

    def test_context_intent(self):
        assert parse_intent("context").kind == IntentKind.CONTEXT

    def test_ctx_intent(self):
        assert parse_intent("ctx").kind == IntentKind.CONTEXT

    def test_usage_intent(self):
        assert parse_intent("usage").kind == IntentKind.CONTEXT

    # Promote/reject aliases
    def test_promote_is_apply(self):
        assert parse_intent("promote").kind == IntentKind.APPLY

    def test_accept_is_apply(self):
        assert parse_intent("accept").kind == IntentKind.APPLY

    def test_reject_is_rollback(self):
        assert parse_intent("reject").kind == IntentKind.ROLLBACK

    def test_revert_is_rollback(self):
        assert parse_intent("revert").kind == IntentKind.ROLLBACK

    # Clear
    def test_clear(self):
        assert parse_intent("clear").kind == IntentKind.CLEAR

    def test_reset(self):
        assert parse_intent("reset").kind == IntentKind.CLEAR

    def test_clear_template_not_clear(self):
        """'clear template' should be CLEAR_TEMPLATE, not CLEAR."""
        assert parse_intent("clear template").kind == IntentKind.CLEAR_TEMPLATE

    # Lineage
    def test_lineage(self):
        assert parse_intent("lineage").kind == IntentKind.LINEAGE

    def test_branch(self):
        assert parse_intent("branch").kind == IntentKind.LINEAGE

    def test_lineage_tree(self):
        assert parse_intent("lineage tree").kind == IntentKind.LINEAGE_TREE

    def test_history(self):
        assert parse_intent("history").kind == IntentKind.HISTORY

    def test_log(self):
        assert parse_intent("log").kind == IntentKind.HISTORY
