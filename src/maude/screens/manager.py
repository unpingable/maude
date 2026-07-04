# SPDX-License-Identifier: Apache-2.0
"""ScreenManager — the desk's screen registry (GS-10 skeleton).

Maps logical screen names to factories so ``app.py`` (GS-10b) can push/switch
without hard-coding classes. The four desk screens plus the reserved run-report
slot register here. Overlays (why / help / command palette — loop-ux §2, "never
steal the screen") arrive with GS-13; their names are reserved below but not yet
built, so the registry doesn't claim to have what it doesn't.
"""

from __future__ import annotations

from typing import Callable

from textual.screen import Screen

from maude.screens.board import BoardScreen
from maude.screens.diff import DiffScreen
from maude.screens.queue import QueueScreen
from maude.screens.report import ReportScreen
from maude.screens.session import SessionScreen

ScreenFactory = Callable[[], Screen]

#: Overlay names reserved for GS-13 (why / help / palette). Not yet built.
OVERLAY_NAMES: tuple[str, ...] = ("why", "help", "palette")


class ScreenManager:
    """A name→factory registry for the desk screens.

    Navigation (push/switch/overlay stack) is driven by the app in GS-10b; this
    is the registry that makes the screens addressable by name.
    """

    def __init__(self) -> None:
        self._factories: dict[str, ScreenFactory] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        for screen_cls in (
            QueueScreen,
            SessionScreen,
            BoardScreen,
            DiffScreen,
            ReportScreen,
        ):
            self.register(screen_cls.SCREEN_NAME, screen_cls)

    def register(self, name: str, factory: ScreenFactory) -> None:
        if name in self._factories:
            raise ValueError(f"screen {name!r} already registered")
        self._factories[name] = factory

    def create(self, name: str) -> Screen:
        """Instantiate the screen registered under ``name``."""
        try:
            factory = self._factories[name]
        except KeyError:
            raise KeyError(f"no screen registered as {name!r}") from None
        return factory()

    def names(self) -> list[str]:
        """Registered screen names, in registration order."""
        return list(self._factories)
