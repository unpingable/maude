# SPDX-License-Identifier: Apache-2.0
"""Tests for the CommandRegistry seam (GS-10)."""

from __future__ import annotations

import pytest

from maude.commands import build_registry
from maude.commands.base import AppCommand, Command, CommandContext, CommandRegistry
from maude.intents import IntentKind


class _HelpCommand(Command):
    kinds = (IntentKind.HELP,)
    help = "show help"

    def __init__(self):
        self.ran_with = None

    async def execute(self, ctx, payload):
        self.ran_with = payload


class _StatusCommand(Command):
    kinds = (IntentKind.STATUS,)
    help = "governor status"

    async def execute(self, ctx, payload):
        pass


class _MultiKindCommand(Command):
    kinds = (IntentKind.APPLY, IntentKind.ROLLBACK)

    async def execute(self, ctx, payload):
        pass


class TestRegistry:
    def test_resolve_by_kind(self):
        reg = CommandRegistry()
        help_cmd = _HelpCommand()
        reg.register(help_cmd)
        assert reg.resolve(IntentKind.HELP) is help_cmd

    def test_unregistered_kind_resolves_none(self):
        reg = CommandRegistry()
        assert reg.resolve(IntentKind.STATUS) is None

    def test_multi_kind_command_claims_all_its_kinds(self):
        reg = CommandRegistry()
        cmd = _MultiKindCommand()
        reg.register(cmd)
        assert reg.resolve(IntentKind.APPLY) is cmd
        assert reg.resolve(IntentKind.ROLLBACK) is cmd

    def test_double_registration_fails_loudly(self):
        reg = CommandRegistry()
        reg.register(_HelpCommand())
        with pytest.raises(ValueError, match="already handled"):
            reg.register(_HelpCommand())

    def test_command_without_kinds_rejected(self):
        reg = CommandRegistry()

        class _NoKinds(Command):
            async def execute(self, ctx, payload):
                pass

        with pytest.raises(ValueError, match="no kinds"):
            reg.register(_NoKinds())

    def test_commands_listed_in_registration_order(self):
        reg = CommandRegistry()
        a, b = _HelpCommand(), _StatusCommand()
        reg.register(a)
        reg.register(b)
        assert reg.commands() == [a, b]

    def test_handles_predicate(self):
        cmd = _HelpCommand()
        assert cmd.handles(IntentKind.HELP)
        assert not cmd.handles(IntentKind.STATUS)

    @pytest.mark.asyncio
    async def test_execute_receives_payload(self):
        cmd = _HelpCommand()
        await cmd.execute(ctx=None, payload="hello")
        assert cmd.ran_with == "hello"


# ---------------------------------------------------------------------------
# GS-10b leg 1: the real registry (build_registry) and AppCommand dispatch
# ---------------------------------------------------------------------------


# Legacy intents (chat + PLAN/BUILD spec-lock), removed at GS-15.
_LEGACY_KINDS = {
    IntentKind.PLAN, IntentKind.PLAN_TEMPLATE, IntentKind.CLEAR_TEMPLATE,
    IntentKind.LOCK_SPEC, IntentKind.BUILD, IntentKind.SHOW_SPEC, IntentKind.CHAT,
}


class TestBuildRegistry:
    def test_every_intent_kind_is_handled(self):
        """Behavior-preservation guard: no intent silently dropped by the
        dispatch migration."""
        registry = build_registry()
        unhandled = [k for k in IntentKind if registry.resolve(k) is None]
        assert unhandled == [], f"intents with no command: {unhandled}"

    def test_every_handler_name_exists_on_the_app(self):
        """Guard against a typo'd handler string — app.py has no tests, so a
        bad name would otherwise fail only at runtime. Applies to AppCommand
        adapters only; self-contained Commands (e.g. M-2 RunPlanCommand) own
        their execute() and have no app handler to name."""
        from maude.app import MaudeApp

        registry = build_registry()
        missing = [
            cmd._handler
            for cmd in registry.commands()
            if isinstance(cmd, AppCommand) and not hasattr(MaudeApp, cmd._handler)
        ]
        assert missing == [], f"handlers not found on MaudeApp: {missing}"

    def test_legacy_set_is_exactly_the_retired_paradigm(self):
        registry = build_registry()
        legacy = {
            k for cmd in registry.commands() if cmd.legacy for k in cmd.kinds
        }
        assert legacy == _LEGACY_KINDS

    def test_launch_and_quick_launch_share_a_handler(self):
        registry = build_registry()
        assert (
            registry.resolve(IntentKind.SUPERVISED_LAUNCH)
            is registry.resolve(IntentKind.QUICK_LAUNCH)
        )


class _FakeApp:
    def __init__(self):
        self.calls = []

    def _handle_sync(self, log):
        self.calls.append(("sync", log))

    async def _handle_async(self, log):
        self.calls.append(("async", log))

    def _handle_payload(self, log, payload):
        self.calls.append(("payload", payload))

    def _handle_text(self, log, text):
        self.calls.append(("text", text))


class TestAppCommandDispatch:
    @pytest.mark.asyncio
    async def test_sync_handler_gets_log_only(self):
        app = _FakeApp()
        cmd = AppCommand((IntentKind.STATUS,), "_handle_sync")
        await cmd.execute(CommandContext(app, log="LOG", text="t"), payload="p")
        assert app.calls == [("sync", "LOG")]

    @pytest.mark.asyncio
    async def test_async_handler_is_awaited(self):
        app = _FakeApp()
        cmd = AppCommand((IntentKind.STATUS,), "_handle_async")
        await cmd.execute(CommandContext(app, log="LOG", text="t"), payload="p")
        assert app.calls == [("async", "LOG")]

    @pytest.mark.asyncio
    async def test_payload_handler_gets_payload(self):
        app = _FakeApp()
        cmd = AppCommand((IntentKind.PLAN,), "_handle_payload", takes_payload=True)
        await cmd.execute(CommandContext(app, log="LOG", text="raw"), payload="P")
        assert app.calls == [("payload", "P")]

    @pytest.mark.asyncio
    async def test_text_handler_gets_raw_text(self):
        app = _FakeApp()
        cmd = AppCommand((IntentKind.CHAT,), "_handle_text", uses_text=True)
        await cmd.execute(CommandContext(app, log="LOG", text="raw line"), payload="ignored")
        assert app.calls == [("text", "raw line")]
