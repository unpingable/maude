# SPDX-License-Identifier: Apache-2.0
"""Sessions board — N sessions as rows (GS-10 skeleton).

GS-12 fills this: status glyph · current-activity one-liner · pending-decision
count · budget bar, with waiting-on-you sorted to the top (loop-ux §2).
"""

from __future__ import annotations

from maude.screens.base import DeskScreen


class BoardScreen(DeskScreen):
    SCREEN_NAME = "board"
    TITLE_TEXT = "SESSIONS"
    EMPTY_TEXT = "No active sessions."
