from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, auto


class IntentKind(Enum):
    PLAN = auto()
    LOCK_SPEC = auto()
    BUILD = auto()
    SHOW_SPEC = auto()
    SHOW_DIFF = auto()
    APPLY = auto()
    ROLLBACK = auto()
    WHY = auto()
    STATUS = auto()
    HELP = auto()
    CHAT = auto()


@dataclass
class Intent:
    kind: IntentKind
    payload: str


_PATTERNS: list[tuple[re.Pattern[str], IntentKind]] = [
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
    (re.compile(r"^help$", re.IGNORECASE), IntentKind.HELP),
    (re.compile(r"^\?$"), IntentKind.HELP),
]


def parse_intent(text: str) -> Intent:
    stripped = text.strip()
    for pattern, kind in _PATTERNS:
        if pattern.search(stripped):
            return Intent(kind=kind, payload=stripped)
    return Intent(kind=IntentKind.CHAT, payload=stripped)
