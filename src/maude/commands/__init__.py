# SPDX-License-Identifier: Apache-2.0
"""Command objects + registry — the seam that replaces app.py's if/elif intent
dispatch (GS-10b leg 1, per docs/design/governed-shell/loop-ux.md §3).

``build_registry`` wires the desk commands + the quarantined legacy commands.
GS-11..GS-14 move desk commands onto real screens; GS-15 deletes the legacy set.
"""

from maude.commands.base import AppCommand, Command, CommandContext, CommandRegistry
from maude.commands.desk import desk_commands
from maude.commands.legacy import legacy_commands

__all__ = [
    "AppCommand",
    "Command",
    "CommandContext",
    "CommandRegistry",
    "build_registry",
    "desk_commands",
    "legacy_commands",
]


def build_registry() -> CommandRegistry:
    """The full command registry: desk surface + quarantined legacy."""
    registry = CommandRegistry()
    for command in desk_commands():
        registry.register(command)
    for command in legacy_commands():
        registry.register(command)
    return registry
