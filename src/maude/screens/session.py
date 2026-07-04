# SPDX-License-Identifier: Apache-2.0
"""Session view — transcript + receipt rail + steering line (GS-10 skeleton).

GS-12 fills this: the canonical event stream on the left, the receipt rail in
the right margin, and a ``runtime.session.send_input`` steering line at the
bottom (disabled with a visible reason when the adapter lacks the capability).
"""

from __future__ import annotations

from maude.screens.base import DeskScreen


class SessionScreen(DeskScreen):
    SCREEN_NAME = "session"
    TITLE_TEXT = "SESSION"
    EMPTY_TEXT = "No session selected."
