# SPDX-License-Identifier: Apache-2.0
"""Provider-free checks for qualification finalization."""

from __future__ import annotations

import json
import sys
from pathlib import Path


QUALIFICATION_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = QUALIFICATION_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import finalize_qualification  # noqa: E402


def test_provider_schema_error_is_extracted_without_message_copy(
    tmp_path: Path,
) -> None:
    raw = tmp_path / "raw.jsonl"
    message = json.dumps(
        {
            "type": "error",
            "error": {
                "type": "invalid_request_error",
                "code": "invalid_json_schema",
                "message": "provider prose is not copied",
                "param": "text.format.schema",
            },
            "status": 400,
        }
    )
    raw.write_text(
        json.dumps({"type": "error", "message": message}) + "\n",
        encoding="utf-8",
    )
    records = finalize_qualification.provider_terminal_errors(raw)
    assert records == [
        {
            "event_number": 1,
            "provider_error_type": "invalid_request_error",
            "provider_error_code": "invalid_json_schema",
            "provider_error_param": "text.format.schema",
            "provider_status": 400,
            "message_sha256": finalize_qualification.sha256_bytes(
                message.encode("utf-8")
            ),
            "raw_event_sha256": finalize_qualification.sha256_bytes(
                finalize_qualification.canonical_json_bytes(
                    {"type": "error", "message": message}
                )
            ),
        }
    ]


def test_schema_rejection_precedes_downstream_admission_noise() -> None:
    live = {
        "qualification_verdict": "NOT-QUALIFIED-EVIDENCE-DISCIPLINE",
        "probes": [
            {
                "admission_result": {
                    "violations": [
                        {"code": "PREMATURE_VERDICT"},
                        {"code": "INVALID_VERDICT_STRUCTURE"},
                    ]
                }
            }
        ],
    }
    verdict, _basis = finalize_qualification._select_verdict(
        live=live,
        terminal_errors=[
            {"provider_error_code": "invalid_json_schema"}
        ],
    )
    assert verdict == "NOT-QUALIFIED-VERDICT-VALIDATION"


def test_unrostered_attempt_remains_narrowest_failure() -> None:
    live = {
        "qualification_verdict": "NOT-QUALIFIED-EVIDENCE-DISCIPLINE",
        "probes": [
            {
                "admission_result": {
                    "violations": [
                        {"code": "UNROSTERED_TOOL_ATTEMPT"}
                    ]
                }
            }
        ],
    }
    verdict, _basis = finalize_qualification._select_verdict(
        live=live,
        terminal_errors=[
            {"provider_error_code": "invalid_json_schema"}
        ],
    )
    assert verdict == "NOT-QUALIFIED-TOOL-BOUNDARY"
