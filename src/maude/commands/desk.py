# SPDX-License-Identifier: Apache-2.0
"""Desk commands — the supported (non-legacy) operator surface.

Each entry routes an :class:`~maude.intents.IntentKind` to the app handler that
already implements it (GS-10b leg 1: dispatch migration only, handlers
unchanged). GS-11..GS-14 move these onto real screens.
"""

from __future__ import annotations

from maude.commands.base import AppCommand, Command
from maude.intents import IntentKind as K


def desk_commands() -> list[Command]:
    return [
        AppCommand((K.HELP,), "_handle_help", help="list commands"),
        AppCommand((K.STATUS,), "_handle_status", help="governor status"),
        AppCommand((K.WHY,), "_handle_why", help="why something is blocked"),
        AppCommand((K.SESSIONS,), "_handle_sessions", help="list sessions"),
        AppCommand((K.SWITCH_SESSION,), "_handle_switch_session", takes_payload=True,
                   help="switch session"),
        AppCommand((K.DELETE_SESSION,), "_handle_delete_session", takes_payload=True,
                   help="delete session"),
        AppCommand((K.SHOW_DIFF,), "_handle_diff", help="show diff"),
        AppCommand((K.APPLY,), "_handle_apply", help="apply / promote"),
        AppCommand((K.ROLLBACK,), "_handle_rollback", help="rollback / reject"),
        # supervised launch + its short alias share one handler.
        AppCommand((K.SUPERVISED_LAUNCH, K.QUICK_LAUNCH), "_handle_supervised_launch",
                   takes_payload=True, help="launch a governed harness run"),
        AppCommand((K.SUPERVISED_LIST,), "_handle_supervised_list",
                   help="list supervised sessions"),
        AppCommand((K.SUPERVISED_EVENTS,), "_handle_supervised_events", takes_payload=True,
                   help="show event stream"),
        AppCommand((K.SUPERVISED_APPROVE,), "_handle_supervised_approve", takes_payload=True,
                   help="approve a tool call"),
        AppCommand((K.SUPERVISED_DENY,), "_handle_supervised_deny", takes_payload=True,
                   help="deny a tool call"),
        AppCommand((K.SUPERVISED_KILL,), "_handle_supervised_kill", takes_payload=True,
                   help="kill a session"),
        AppCommand((K.SUPERVISED_INTERVENTIONS,), "_handle_supervised_interventions",
                   takes_payload=True, help="show pending approvals"),
        AppCommand((K.SUPERVISED_PROMOTION,), "_handle_supervised_promotion",
                   takes_payload=True, help="show workspace changes"),
        AppCommand((K.SUPERVISED_DIFF,), "_handle_supervised_diff", takes_payload=True,
                   help="show unified diff"),
        AppCommand((K.SUPERVISED_PROMOTE,), "_handle_supervised_promote", takes_payload=True,
                   help="accept changes"),
        AppCommand((K.SUPERVISED_REJECT,), "_handle_supervised_reject", takes_payload=True,
                   help="revert changes"),
        AppCommand((K.SUPERVISED_FORK,), "_handle_supervised_fork", takes_payload=True,
                   help="fork from a promoted session"),
        AppCommand((K.SNAPSHOT,), "_handle_snapshot", help="operator overview"),
        AppCommand((K.CONTEXT,), "_handle_context", help="context usage"),
        AppCommand((K.CLEAR,), "_handle_clear", help="reset session"),
        AppCommand((K.LINEAGE,), "_handle_lineage", help="session lineage"),
        AppCommand((K.LINEAGE_TREE,), "_handle_lineage_tree", help="lineage tree"),
        AppCommand((K.HISTORY,), "_handle_history", help="message history"),
        AppCommand((K.QUICK_APPROVE,), "_handle_quick_approve", help="approve (y)"),
        AppCommand((K.QUICK_DENY,), "_handle_quick_deny", help="deny (n)"),
        AppCommand((K.QUICK_PENDING,), "_handle_quick_pending", help="pending (p)"),
    ]
