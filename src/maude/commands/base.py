# SPDX-License-Identifier: Apache-2.0
"""Command base + registry.

A :class:`Command` owns one operator action; the :class:`CommandRegistry` maps
the parsed :class:`~maude.intents.IntentKind` to its command, replacing the flat
if/elif dispatch in ``app.py``. Commands render and call RPCs — they mint no
authority and make no policy decisions (that stays daemon-side).

GS-10b leg 1 keeps the handler *bodies* on the app (behavior-preserving) and
routes to them through :class:`AppCommand`; desk vs. legacy commands are
registered from separate modules so the legacy set is a named group GS-15 can
delete wholesale.
"""

from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from maude.intents import IntentKind

if TYPE_CHECKING:  # avoid import cycle with app.py / heavy Textual import
    from textual.widgets import RichLog


@dataclass
class CommandContext:
    """What a command needs to run.

    ``app`` is the running MaudeApp (handler methods, widgets, session, client);
    ``log`` is the output pane; ``text`` is the raw input line (chat needs it).
    Kept small — a command that needs more is doing too much.
    """

    app: Any
    log: "RichLog"
    text: str


class Command(ABC):
    """One operator action, keyed by the intent(s) it handles."""

    #: The intent kind(s) this command handles.
    kinds: tuple[IntentKind, ...] = ()
    #: Short help string shown in the command list.
    help: str = ""
    #: Legacy commands (chat / PLAN / BUILD) — removed at GS-15.
    legacy: bool = False

    def handles(self, kind: IntentKind) -> bool:
        return kind in self.kinds

    @abstractmethod
    async def execute(self, ctx: CommandContext, payload: str) -> None:
        """Run the command. ``payload`` is the parsed intent payload."""
        raise NotImplementedError


class AppCommand(Command):
    """Routes an intent to an existing ``MaudeApp._handle_*`` method.

    Behavior-preserving adapter for GS-10b leg 1: the handler bodies stay on the
    app; this only replaces the if/elif dispatch. ``await``\\s the handler iff it
    is a coroutine, so sync and async handlers register identically.
    """

    def __init__(
        self,
        kinds: tuple[IntentKind, ...],
        handler: str,
        *,
        takes_payload: bool = False,
        uses_text: bool = False,
        legacy: bool = False,
        help: str = "",
    ) -> None:
        self.kinds = kinds
        self._handler = handler
        self._takes_payload = takes_payload
        self._uses_text = uses_text
        self.legacy = legacy
        self.help = help

    async def execute(self, ctx: CommandContext, payload: str) -> None:
        fn = getattr(ctx.app, self._handler)
        args: list[Any] = [ctx.log]
        if self._uses_text:
            args.append(ctx.text)
        elif self._takes_payload:
            args.append(payload)
        result = fn(*args)
        if inspect.isawaitable(result):
            await result


class CommandRegistry:
    """Maps an :class:`IntentKind` to the command that handles it."""

    def __init__(self) -> None:
        self._by_kind: dict[IntentKind, Command] = {}
        self._commands: list[Command] = []

    def register(self, command: Command) -> None:
        """Register a command for each of its ``kinds``.

        A kind may be claimed by only one command — a double registration is a
        programming error (two handlers for one intent), so it fails loudly
        rather than silently shadowing.
        """
        if not command.kinds:
            raise ValueError(f"{command!r} declares no kinds")
        for kind in command.kinds:
            if kind in self._by_kind:
                raise ValueError(
                    f"intent {kind} already handled by {self._by_kind[kind]!r}"
                )
            self._by_kind[kind] = command
        self._commands.append(command)

    def resolve(self, kind: IntentKind) -> Command | None:
        """The command for ``kind``, or ``None`` if unregistered."""
        return self._by_kind.get(kind)

    def commands(self) -> list[Command]:
        """All registered commands, in registration order (for help listings)."""
        return list(self._commands)
