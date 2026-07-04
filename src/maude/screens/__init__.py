# SPDX-License-Identifier: Apache-2.0
"""Desk screens + ScreenManager (GS-10 skeleton).

The four desk screens (queue / session / board / diff) plus the reserved
run-report slot, per docs/design/governed-shell/loop-ux.md §2. Filled by
GS-11..GS-14 (and M-4 for the report). ``app.py`` migrates onto the
ScreenManager in GS-10b.
"""

from maude.screens.base import DeskScreen
from maude.screens.board import BoardScreen
from maude.screens.diff import DiffScreen
from maude.screens.manager import OVERLAY_NAMES, ScreenManager
from maude.screens.queue import QueueScreen
from maude.screens.report import ReportScreen
from maude.screens.session import SessionScreen

__all__ = [
    "DeskScreen",
    "QueueScreen",
    "SessionScreen",
    "BoardScreen",
    "DiffScreen",
    "ReportScreen",
    "ScreenManager",
    "OVERLAY_NAMES",
]
