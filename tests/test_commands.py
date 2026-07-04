# SPDX-License-Identifier: Apache-2.0
"""Tests for the CommandRegistry seam (GS-10)."""

from __future__ import annotations

import pytest

from maude.commands.base import Command, CommandRegistry
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
