from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


class Mode(Enum):
    PLAN = auto()
    BUILD = auto()


@dataclass
class MaudeSession:
    mode: Mode = Mode.PLAN
    governor_session_id: str | None = None
    spec_draft: str = ""
    spec_locked: bool = False
    spec_template: str | None = None
    spec_template_content: str = ""
    last_governor_now: Any | None = None
    messages: list[dict[str, str]] = field(default_factory=list)

    def status_line(self) -> str:
        mode_str = self.mode.name
        spec_str = "LOCKED" if self.spec_locked else "UNLOCKED"
        session_str = self.governor_session_id or "none"
        tmpl_str = f"  TEMPLATE={self.spec_template}" if self.spec_template else ""
        gov_str = ""
        if self.last_governor_now is not None:
            gov_str = f" GOV={self.last_governor_now.status}"
        return f"MODE={mode_str}  SPEC={spec_str}{tmpl_str}  SESSION={session_str}{gov_str}"

    def add_message(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content})

    def load_template(self, name: str, content: str) -> None:
        self.spec_template = name
        self.spec_template_content = content

    def clear_template(self) -> None:
        self.spec_template = None
        self.spec_template_content = ""

    def lock_spec(self) -> str:
        self.spec_locked = True
        return self.spec_draft

    def unlock_spec(self) -> None:
        self.spec_locked = False

    def set_mode(self, mode: Mode) -> None:
        if mode == Mode.BUILD and not self.spec_locked:
            raise ValueError("Cannot enter BUILD mode without a locked spec")
        self.mode = mode
