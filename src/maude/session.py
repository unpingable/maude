# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


class Mode(Enum):
    PLAN = auto()
    BUILD = auto()


@dataclass
class ContextUsage:
    """Tracks cumulative context usage across a session."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    turns: int = 0
    baseline_input_tokens: int | None = None  # first turn's input tokens

    @property
    def context_tokens(self) -> int:
        """Current context size (input side only)."""
        return self.input_tokens

    @property
    def clearable_tokens(self) -> int:
        """Tokens reclaimable by starting fresh."""
        if self.baseline_input_tokens is None:
            return 0
        return max(0, self.input_tokens - self.baseline_input_tokens)

    def update(self, usage: dict[str, int]) -> None:
        """Update from a chat.stream result's usage dict."""
        if not usage:
            return
        self.turns += 1
        self.input_tokens = usage.get("input_tokens", self.input_tokens)
        self.output_tokens = usage.get("output_tokens", self.output_tokens)
        self.cache_creation_input_tokens = usage.get(
            "cache_creation_input_tokens", self.cache_creation_input_tokens,
        )
        self.cache_read_input_tokens = usage.get(
            "cache_read_input_tokens", self.cache_read_input_tokens,
        )
        if self.baseline_input_tokens is None:
            self.baseline_input_tokens = self.input_tokens

    def format_compact(self, model_context_window: int = 200_000) -> str:
        """Format as a compact status string: 'ctx: 48k/200k (24%)'."""
        if self.input_tokens == 0:
            return ""
        ctx_k = self.input_tokens / 1000
        window_k = model_context_window / 1000
        pct = (self.input_tokens / model_context_window) * 100
        if ctx_k >= 1000:
            ctx_str = f"{ctx_k / 1000:.1f}m"
        else:
            ctx_str = f"{ctx_k:.0f}k"
        if window_k >= 1000:
            win_str = f"{window_k / 1000:.0f}m"
        else:
            win_str = f"{window_k:.0f}k"
        return f"ctx: {ctx_str}/{win_str} ({pct:.0f}%)"

    def format_detail(self, model_context_window: int = 200_000) -> str:
        """Format detailed breakdown for 'context' command."""
        if self.input_tokens == 0:
            return "No usage data yet."
        lines = [
            f"Context tokens:    {self.input_tokens:,}",
            f"Output tokens:     {self.output_tokens:,}",
        ]
        if self.cache_creation_input_tokens:
            lines.append(f"Cache created:     {self.cache_creation_input_tokens:,}")
        if self.cache_read_input_tokens:
            lines.append(f"Cache read:        {self.cache_read_input_tokens:,}")
        lines.append(f"Turns:             {self.turns}")
        if self.baseline_input_tokens is not None:
            lines.append(f"Fresh baseline:    {self.baseline_input_tokens:,}")
            lines.append(f"Clearable:         {self.clearable_tokens:,}")
        pct = (self.input_tokens / model_context_window) * 100
        lines.append(f"Window:            {model_context_window:,} ({pct:.0f}% used)")
        return "\n".join(lines)


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
    project_name: str = ""
    backend_type: str = ""
    context_usage: ContextUsage = field(default_factory=ContextUsage)

    def status_line(self) -> str:
        mode_str = self.mode.name
        spec_str = "LOCKED" if self.spec_locked else "UNLOCKED"
        session_str = self.governor_session_id or "none"
        tmpl_str = f"  TEMPLATE={self.spec_template}" if self.spec_template else ""
        gov_str = ""
        if self.last_governor_now is not None:
            gov_str = f" GOV={self.last_governor_now.status}"
        parts = []
        if self.project_name:
            parts.append(self.project_name)
        if self.backend_type:
            parts.append(self.backend_type)
        ctx_str = self.context_usage.format_compact()
        if ctx_str:
            parts.append(ctx_str)
        parts.append(f"MODE={mode_str}")
        parts.append(f"SPEC={spec_str}{tmpl_str}")
        parts.append(f"SESSION={session_str}{gov_str}")
        return "  ".join(parts)

    def title_line(self) -> str:
        """Build terminal title showing stable session identity."""
        parts = ["maude"]
        if self.project_name:
            parts.append(self.project_name)
        if self.backend_type:
            parts.append(self.backend_type)
        return ": ".join(parts[:1]) + ((" — " + " | ".join(parts[1:])) if len(parts) > 1 else "")

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
