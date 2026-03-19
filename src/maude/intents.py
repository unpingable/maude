# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, auto


class IntentKind(Enum):
    PLAN = auto()
    PLAN_TEMPLATE = auto()
    CLEAR_TEMPLATE = auto()
    LOCK_SPEC = auto()
    BUILD = auto()
    SHOW_SPEC = auto()
    SHOW_DIFF = auto()
    APPLY = auto()
    ROLLBACK = auto()
    WHY = auto()
    STATUS = auto()
    SESSIONS = auto()
    SWITCH_SESSION = auto()
    DELETE_SESSION = auto()
    # Runtime supervisor
    SUPERVISED_LAUNCH = auto()
    SUPERVISED_LIST = auto()
    SUPERVISED_EVENTS = auto()
    SUPERVISED_APPROVE = auto()
    SUPERVISED_DENY = auto()
    SUPERVISED_KILL = auto()
    SUPERVISED_INTERVENTIONS = auto()
    SUPERVISED_PROMOTION = auto()
    SUPERVISED_DIFF = auto()
    SUPERVISED_PROMOTE = auto()
    SUPERVISED_REJECT = auto()
    SUPERVISED_FORK = auto()
    SNAPSHOT = auto()
    HELP = auto()
    CHAT = auto()


@dataclass
class Intent:
    kind: IntentKind
    payload: str


_PATTERNS: list[tuple[re.Pattern[str], IntentKind]] = [
    # Template-specific plan commands (must come before generic ^plan\b)
    (re.compile(r"^plan\s+(architecture|arch)$", re.IGNORECASE), IntentKind.PLAN_TEMPLATE),
    (re.compile(r"^plan\s+(product design|product)$", re.IGNORECASE), IntentKind.PLAN_TEMPLATE),
    (re.compile(r"^plan\s+(requirements|reqs)$", re.IGNORECASE), IntentKind.PLAN_TEMPLATE),
    (re.compile(r"^clear template$", re.IGNORECASE), IntentKind.CLEAR_TEMPLATE),
    # Generic plan
    (re.compile(r"^plan\b", re.IGNORECASE), IntentKind.PLAN),
    (re.compile(r"^let'?s plan\b", re.IGNORECASE), IntentKind.PLAN),
    (re.compile(r"^lock spec$", re.IGNORECASE), IntentKind.LOCK_SPEC),
    (re.compile(r"^freeze spec$", re.IGNORECASE), IntentKind.LOCK_SPEC),
    (re.compile(r"^build$", re.IGNORECASE), IntentKind.BUILD),
    (re.compile(r"^implement$", re.IGNORECASE), IntentKind.BUILD),
    (re.compile(r"^do it$", re.IGNORECASE), IntentKind.BUILD),
    (re.compile(r"^show spec$", re.IGNORECASE), IntentKind.SHOW_SPEC),
    (re.compile(r"^spec$", re.IGNORECASE), IntentKind.SHOW_SPEC),
    (re.compile(r"^show diff$", re.IGNORECASE), IntentKind.SHOW_DIFF),
    (re.compile(r"^diff$", re.IGNORECASE), IntentKind.SHOW_DIFF),
    (re.compile(r"^apply$", re.IGNORECASE), IntentKind.APPLY),
    (re.compile(r"^merge$", re.IGNORECASE), IntentKind.APPLY),
    (re.compile(r"^rollback$", re.IGNORECASE), IntentKind.ROLLBACK),
    (re.compile(r"^undo$", re.IGNORECASE), IntentKind.ROLLBACK),
    (re.compile(r"^why\b", re.IGNORECASE), IntentKind.WHY),
    (re.compile(r"^blocked$", re.IGNORECASE), IntentKind.WHY),
    (re.compile(r"^status$", re.IGNORECASE), IntentKind.STATUS),
    (re.compile(r"^state$", re.IGNORECASE), IntentKind.STATUS),
    (re.compile(r"^sessions$", re.IGNORECASE), IntentKind.SESSIONS),
    (re.compile(r"^list sessions$", re.IGNORECASE), IntentKind.SESSIONS),
    (re.compile(r"^ls$", re.IGNORECASE), IntentKind.SESSIONS),
    (re.compile(r"^switch\s+(\S+)", re.IGNORECASE), IntentKind.SWITCH_SESSION),
    (re.compile(r"^session\s+(\S+)", re.IGNORECASE), IntentKind.SWITCH_SESSION),
    (re.compile(r"^resume\s+(\S+)", re.IGNORECASE), IntentKind.SWITCH_SESSION),
    (re.compile(r"^delete session\s+(\S+)", re.IGNORECASE), IntentKind.DELETE_SESSION),
    (re.compile(r"^rm session\s+(\S+)", re.IGNORECASE), IntentKind.DELETE_SESSION),
    # Runtime supervisor commands
    (re.compile(r"^supervised launch\s*(.*)", re.IGNORECASE), IntentKind.SUPERVISED_LAUNCH),
    (re.compile(r"^supervised list$", re.IGNORECASE), IntentKind.SUPERVISED_LIST),
    (re.compile(r"^supervised events\s+(\S+)", re.IGNORECASE), IntentKind.SUPERVISED_EVENTS),
    (re.compile(r"^supervised approve\s+(\S+)\s+(\S+)", re.IGNORECASE), IntentKind.SUPERVISED_APPROVE),
    (re.compile(r"^supervised deny\s+(\S+)\s+(\S+)", re.IGNORECASE), IntentKind.SUPERVISED_DENY),
    (re.compile(r"^supervised kill\s+(\S+)", re.IGNORECASE), IntentKind.SUPERVISED_KILL),
    (re.compile(r"^supervised interventions\s+(\S+)", re.IGNORECASE), IntentKind.SUPERVISED_INTERVENTIONS),
    (re.compile(r"^supervised promotion\s+(\S+)", re.IGNORECASE), IntentKind.SUPERVISED_PROMOTION),
    (re.compile(r"^supervised diff\s+(\S+)", re.IGNORECASE), IntentKind.SUPERVISED_DIFF),
    (re.compile(r"^supervised promote\s+(\S+)", re.IGNORECASE), IntentKind.SUPERVISED_PROMOTE),
    (re.compile(r"^supervised reject\s+(\S+)", re.IGNORECASE), IntentKind.SUPERVISED_REJECT),
    (re.compile(r"^supervised fork\s+(\S+)\s*(.*)", re.IGNORECASE), IntentKind.SUPERVISED_FORK),
    (re.compile(r"^supervised$", re.IGNORECASE), IntentKind.SUPERVISED_LIST),
    (re.compile(r"^snapshot$", re.IGNORECASE), IntentKind.SNAPSHOT),
    (re.compile(r"^overview$", re.IGNORECASE), IntentKind.SNAPSHOT),
    (re.compile(r"^wtf$", re.IGNORECASE), IntentKind.SNAPSHOT),
    (re.compile(r"^help$", re.IGNORECASE), IntentKind.HELP),
    (re.compile(r"^\?$"), IntentKind.HELP),
]


def parse_intent(text: str) -> Intent:
    stripped = text.strip()
    for pattern, kind in _PATTERNS:
        m = pattern.search(stripped)
        if m:
            # For multi-group patterns (e.g. approve <session> <tool>), join with space
            if m.lastindex and m.lastindex >= 2:
                payload = " ".join(m.group(i) for i in range(1, m.lastindex + 1) if m.group(i))
            elif m.lastindex and m.lastindex >= 1:
                payload = m.group(1) if m.group(1) else stripped
            else:
                payload = stripped
            return Intent(kind=kind, payload=payload)
    return Intent(kind=IntentKind.CHAT, payload=stripped)
