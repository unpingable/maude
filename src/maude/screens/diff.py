# SPDX-License-Identifier: Apache-2.0
"""Diff view — promotion review (GS-10 skeleton).

The only full-screen takeover, opt-in from a promotion queue item. GS-12/GS-11
fill it: syntax-colored unified diff + a receipt margin summarizing the
session's governance history, with ``y`` promote / ``n`` reject / ``w`` why
(loop-ux §2).
"""

from __future__ import annotations

from maude.screens.base import DeskScreen


class DiffScreen(DeskScreen):
    SCREEN_NAME = "diff"
    TITLE_TEXT = "DIFF"
    EMPTY_TEXT = "No promotion to review."
