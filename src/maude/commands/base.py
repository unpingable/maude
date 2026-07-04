# SPDX-License-Identifier: Apache-2.0
"""Command base + registry.

A :class:`Command` owns one operator action; the :class:`CommandRegistry` maps
the parsed :class:`~maude.intents.IntentKind` to its command, replacing the flat
if/elif dispatch in ``app.py``. Commands render and call RPCs — they mint no
authority and make no policy decisions (that stays daemon-side). This is the
GS-10 seam; GS-11..GS-14 populate it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

from maude.intents import IntentKind

if TYPE_CHECKING:  # avoid import cycles / heavy Textual import at runtime
    from maude.client.rpc import GovernorClient
    from maude.session import MaudeSession


@dataclass
class CommandContext:
    """What a command needs to do its work.

    ``write`` is the output sink (the app passes its log-writer); ``client`` and
    ``session`` are the daemon client and local view state. Kept deliberately
    small — a command that needs more is doing too much.
    """

    client: "GovernorClient"
    session: "MaudeSession"
    write: "callable"


class Command(ABC):
    """One operator action, keyed by the intent(s) it handles."""

    #: The intent kind(s) this command handles.
    kinds: tuple[IntentKind, ...] = ()
    #: Short help string shown in the command list.
    help: str = ""

    def handles(self, kind: IntentKind) -> bool:
        return kind in self.kinds

    @abstractmethod
    async def execute(self, ctx: CommandContext, payload: str) -> None:
        """Run the command. ``payload`` is the parsed intent payload."""
        raise NotImplementedError


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
