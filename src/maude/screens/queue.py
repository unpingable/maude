# SPDX-License-Identifier: Apache-2.0
"""Queue home — "the desk" (GS-10 skeleton; GS-11 fills the cards).

Renders the unified decision feed from a :class:`~maude.feed.DecisionFeedController`.
At the skeleton stage it lists one summary line per item (or the empty state);
GS-11 replaces these with decision cards whose keys come from the envelope's
``options[].key`` (loop-ux §1-4).
"""

from __future__ import annotations

from maude.feed import DecisionFeedController
from maude.screens.base import DeskScreen


class QueueScreen(DeskScreen):
    SCREEN_NAME = "queue"
    TITLE_TEXT = "QUEUE"
    EMPTY_TEXT = "No pending decisions."

    def __init__(self, feed: DecisionFeedController | None = None) -> None:
        super().__init__()
        self._feed = feed or DecisionFeedController()

    @property
    def feed(self) -> DecisionFeedController:
        return self._feed

    def body_lines(self) -> list[str]:
        # Interrupts first (blocking/expiring), then the accumulated rest —
        # obligations before ambitions (D-GS-1 queue-first ordering).
        ordered = self._feed.interrupts() + self._feed.accumulated()
        return [f"{item.kind}  {item.summary}" for item in ordered]
