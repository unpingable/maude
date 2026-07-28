# SPDX-License-Identifier: Apache-2.0
"""Provider-free checks for live qualification orchestration."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest


QUALIFICATION_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = QUALIFICATION_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import run_live  # noqa: E402


def _probe(
    *codes: str,
    expected_result_match: bool = True,
) -> dict[str, Any]:
    return {
        "admission_result": {
            "violations": [
                {"code": code, "detail": "fixed test violation"}
                for code in codes
            ]
        },
        "expected_result_match": expected_result_match,
    }


@pytest.mark.parametrize(
    ("code", "verdict"),
    (
        ("ACTION_IDENTITY_MUTATED", "NOT-QUALIFIED-TOOL-BOUNDARY"),
        ("UNROSTERED_TOOL_ATTEMPT", "NOT-QUALIFIED-TOOL-BOUNDARY"),
        (
            "DETERMINATE_CONTAMINATED_VERDICT",
            "NOT-QUALIFIED-CONTAMINATION-HANDLING",
        ),
        (
            "DETERMINATE_INCOMPLETE_VERDICT",
            "NOT-QUALIFIED-EVIDENCE-DISCIPLINE",
        ),
        (
            "DETERMINATE_CONTRADICTORY_VERDICT",
            "NOT-QUALIFIED-EVIDENCE-DISCIPLINE",
        ),
        (
            "DETERMINATE_UNAVAILABLE_VERDICT",
            "NOT-QUALIFIED-EVIDENCE-DISCIPLINE",
        ),
        (
            "INVALID_EVIDENCE_RESULT",
            "NOT-QUALIFIED-EVIDENCE-DISCIPLINE",
        ),
        ("INVALID_RAW_STREAM", "NOT-QUALIFIED-VERDICT-VALIDATION"),
        (
            "INVALID_VERDICT_STRUCTURE",
            "NOT-QUALIFIED-VERDICT-VALIDATION",
        ),
    ),
)
def test_live_failure_classifier_is_specific(
    code: str,
    verdict: str,
) -> None:
    assert run_live._narrow_failure_verdict([_probe(code)]) == verdict


def test_expected_oracle_mismatch_is_evidence_failure() -> None:
    assert (
        run_live._narrow_failure_verdict(
            [_probe(expected_result_match=False)]
        )
        == "NOT-QUALIFIED-EVIDENCE-DISCIPLINE"
    )


def test_validator_code_set_is_fully_classified() -> None:
    for code in run_live.VIOLATION_CODES:
        run_live._narrow_failure_verdict([_probe(code)])
