# SPDX-License-Identifier: Apache-2.0
"""Run-report view (GS-10 slot; filled by M-4).

The reviewable-result surface of the plan-executor spine: at session end it
renders a composed :class:`~maude.report.RunReport` — surface + detail — with the
acceptance criteria rendered UNCHECKED for the reviewer to judge, and the raw
law layer (the ReviewPacket verbatim) one `why` away.

*Displayed evidence, not adjudication.* The screen is NOT nav-promoted: it is an
end-of-run artifact, never a browse-to destination (promoting it into desk nav
is the "report starts sounding official" laundering the roadmap flags). When no
report has been composed it stays an honestly-labelled stub. Composition and the
reads live in :mod:`maude.report` / :mod:`maude.commands.report`; this screen
only renders what it is handed.
"""

from __future__ import annotations

from maude.report import RunReport, render_detail, render_surface
from maude.screens.base import DeskScreen


class ReportScreen(DeskScreen):
    SCREEN_NAME = "report"
    TITLE_TEXT = "RUN REPORT"
    EMPTY_TEXT = "No run report yet. Compose one with `report <session_id>`."

    def __init__(self, report: RunReport | None = None) -> None:
        super().__init__()
        self._report = report

    def body_lines(self) -> list[str]:
        """Surface + detail of the composed report; empty → the stub state.

        Renders only what the composer produced — no read, no RPC (the screen is
        handed an already-composed report). The base skeleton turns an empty
        list into the honest empty state."""
        if self._report is None:
            return []
        return [*render_surface(self._report), "", *render_detail(self._report)]
