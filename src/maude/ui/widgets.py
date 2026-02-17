# SPDX-License-Identifier: Apache-2.0
"""Custom Textual widgets for Maude."""

from __future__ import annotations

from textual.widgets import Static


class GovernorStatusBar(Static):
    """Status bar showing governor state, mode, and spec lock status."""

    DEFAULT_CSS = """
    GovernorStatusBar {
        dock: top;
        height: 1;
        background: $surface;
        color: $text;
        padding: 0 1;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__("", **kwargs)

    def update_status(self, text: str, level: str = "ok") -> None:
        """Update status bar text and color level (ok/warning/violation)."""
        self.update(text)
        self.remove_class("ok", "warning", "violation")
        self.add_class(level)
