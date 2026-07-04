# SPDX-License-Identifier: Apache-2.0
"""Legacy commands — chat + PLAN/BUILD spec-lock (unsupported; removed at GS-15).

Quarantined here so the retired paradigm is a named group, not intermixed with
the desk surface (D-GS-2 cut the chat/spec-lock paradigm; see
docs/REPOSITIONING.md). GS-10b leg 1 relocates the *registration* here; the
handler bodies stay on the app until GS-15 removes both this module's entries
and the corresponding ``_handle_*`` methods. Do not build on these.
"""

from __future__ import annotations

from maude.commands.base import AppCommand, Command
from maude.intents import IntentKind as K


def legacy_commands() -> list[Command]:
    return [
        AppCommand((K.PLAN,), "_handle_plan", takes_payload=True, legacy=True,
                   help="[legacy] append to spec draft"),
        AppCommand((K.PLAN_TEMPLATE,), "_handle_plan_template", takes_payload=True,
                   legacy=True, help="[legacy] load a spec template"),
        AppCommand((K.CLEAR_TEMPLATE,), "_handle_clear_template", legacy=True,
                   help="[legacy] unload template"),
        AppCommand((K.LOCK_SPEC,), "_handle_lock_spec", legacy=True,
                   help="[legacy] lock spec"),
        AppCommand((K.BUILD,), "_handle_build", legacy=True, help="[legacy] build mode"),
        AppCommand((K.SHOW_SPEC,), "_handle_show_spec", legacy=True,
                   help="[legacy] show spec draft"),
        # Chat is the fallback intent; uses the raw input text, not a payload.
        AppCommand((K.CHAT,), "_handle_chat", uses_text=True, legacy=True,
                   help="[legacy] chat via governor"),
    ]
