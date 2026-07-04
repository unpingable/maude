# SPDX-License-Identifier: Apache-2.0
"""Command objects + registry — the seam that replaces app.py's if/elif intent
dispatch (GS-10 skeleton, per docs/design/governed-shell/loop-ux.md §3).

GS-11..GS-14 register real commands here; GS-10b migrates app.py's dispatch to
``CommandRegistry.resolve``. Legacy chat/PLAN/BUILD handlers are quarantined in
:mod:`maude.commands.legacy` and deleted at GS-15.
"""

from maude.commands.base import Command, CommandContext, CommandRegistry

__all__ = ["Command", "CommandContext", "CommandRegistry"]
