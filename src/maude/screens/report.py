# SPDX-License-Identifier: Apache-2.0
"""Run-report view — reserved stub (GS-10 skeleton; filled by M-4).

This screen is the reviewable-result surface of the plan-executor spine: on
session end it renders the run report (plan ref + provenance, harness, tool
counts, diff stat, promotion status, receipt refs, and the acceptance-criteria
checklist rendered *unchecked* for the reviewer to judge). Reserved here so the
ScreenManager has the slot; composed from existing daemon reads only at M-4.
See docs/REPOSITIONING.md and ROADMAP.md (M-4).
"""

from __future__ import annotations

from maude.screens.base import DeskScreen


class ReportScreen(DeskScreen):
    SCREEN_NAME = "report"
    TITLE_TEXT = "RUN REPORT"
    EMPTY_TEXT = "No run report yet. (Composed at M-4.)"
