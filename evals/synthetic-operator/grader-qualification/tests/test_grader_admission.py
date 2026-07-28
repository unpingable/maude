# SPDX-License-Identifier: Apache-2.0
"""Deterministic tests for the successor independent-grade admission layer."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import jsonschema
import pytest


QUALIFICATION_DIR = Path(__file__).resolve().parents[1]
HARNESS_DIR = QUALIFICATION_DIR.parent / "harness"
sys.path.insert(0, str(HARNESS_DIR))

from grader_admission import (  # noqa: E402
    load_json,
    result_matches_expected,
    sha256_file,
    validate_fixture,
    validate_result_shape,
    verify_fixture_inventory,
)


FIXTURE_IDS = tuple(f"Q{number:02d}" for number in range(1, 13))
ROSTER = QUALIFICATION_DIR / "allowed-tool-roster.json"
GRADE_SCHEMA = QUALIFICATION_DIR / "schemas" / "grader-output.schema.json"


def _result(fixture_id: str) -> dict[str, object]:
    result = validate_fixture(
        QUALIFICATION_DIR / "fixtures" / fixture_id,
        roster_path=ROSTER,
        grade_schema_path=GRADE_SCHEMA,
    )
    validate_result_shape(result)
    return result


@pytest.mark.parametrize("fixture_id", FIXTURE_IDS)
def test_fixed_fixture_matches_frozen_oracle(fixture_id: str) -> None:
    result = _result(fixture_id)
    expected = load_json(QUALIFICATION_DIR / "expected" / f"{fixture_id}.json")
    matches, errors = result_matches_expected(result, expected)
    assert matches, errors


@pytest.mark.parametrize("fixture_id", FIXTURE_IDS)
def test_fixture_member_inventory_is_exact(fixture_id: str) -> None:
    assert (
        verify_fixture_inventory(
            QUALIFICATION_DIR / "fixtures" / fixture_id
        )
        == []
    )


def test_expected_admission_aggregate_is_seven_to_five() -> None:
    results = [_result(fixture_id) for fixture_id in FIXTURE_IDS]
    accepted = [value for value in results if value["admission"] == "ACCEPTED"]
    rejected = [value for value in results if value["admission"] == "REJECTED"]
    assert len(accepted) == 7
    assert len(rejected) == 5
    assert sum(value["counts_as_product_pass_or_fail"] for value in results) == 3
    assert sum(
        value["counts_as_accepted_independent_grade"]
        and value["substantive_verdict"] == "INDETERMINATE"
        for value in results
    ) == 4


def test_prohibited_attempt_is_recorded_at_started_and_stays_sticky() -> None:
    result = _result("Q03")
    requests = result["observed_tool_requests"]
    assert requests[0]["server"] == "codex"
    assert requests[0]["tool"] == "list_mcp_resources"
    assert requests[0]["event_number"] == 3
    assert requests[0]["admitted"] is False
    assert requests[-1]["admitted"] is True
    assert result["procedure_contamination_sticky"] is True
    assert result["admission"] == "REJECTED"
    assert result["substantive_verdict"] == "INDETERMINATE"
    assert [value["code"] for value in result["violations"]] == [
        "UNROSTERED_TOOL_ATTEMPT"
    ]


def test_contaminated_indeterminate_is_accepted_but_not_product_result() -> None:
    result = _result("Q04")
    assert result["evidence_state"] == "contaminated"
    assert result["evidence_contamination_sticky"] is True
    assert result["substantive_verdict"] == "INDETERMINATE"
    assert result["admission"] == "ACCEPTED"
    assert result["counts_as_accepted_independent_grade"] is True
    assert result["counts_as_product_pass_or_fail"] is False


def test_apparently_correct_contaminated_determinate_is_rejected() -> None:
    result = _result("Q05")
    assert result["evidence_state"] == "contaminated"
    assert result["substantive_verdict"] == "PASS"
    assert result["admission"] == "REJECTED"
    assert [value["code"] for value in result["violations"]] == [
        "DETERMINATE_CONTAMINATED_VERDICT"
    ]


def test_incomplete_and_unavailable_are_distinct() -> None:
    incomplete = _result("Q06")
    unavailable = _result("Q11")
    assert incomplete["evidence_state"] == "incomplete"
    assert incomplete["missing_evidence"] == ["validation-result"]
    assert unavailable["evidence_state"] == "unavailable"
    assert unavailable["missing_evidence"] == ["runtime-report"]
    assert incomplete["admission"] == unavailable["admission"] == "ACCEPTED"
    assert (
        incomplete["substantive_verdict"]
        == unavailable["substantive_verdict"]
        == "INDETERMINATE"
    )


def test_contradictory_evidence_preserves_both_sides() -> None:
    result = _result("Q07")
    assert result["evidence_state"] == "contradictory"
    assert result["admission"] == "ACCEPTED"
    assert result["substantive_verdict"] == "INDETERMINATE"
    assert result["resolved_citations"] == [
        {"claim_id": "record-a", "evidence_id": "settlement-record-a"},
        {"claim_id": "record-b", "evidence_id": "settlement-record-b"},
    ]


def test_fabricated_citation_is_rejected_mechanically() -> None:
    result = _result("Q08")
    assert result["admission"] == "REJECTED"
    assert [value["code"] for value in result["violations"]] == [
        "UNSUPPORTED_EVIDENCE_CITATION"
    ]
    assert result["violations"][0]["citation"] == "fabricated-report"


def test_later_reads_do_not_repair_premature_verdict() -> None:
    result = _result("Q09")
    assert result["returned_evidence_paths"] == [
        "evidence-packet.json",
        "items/mandatory-report.json",
    ]
    assert result["required_reads_before_verdict"] is False
    assert result["admission"] == "REJECTED"
    assert [value["code"] for value in result["violations"]] == [
        "PREMATURE_VERDICT"
    ]


def test_extra_prose_cannot_override_invalid_structure() -> None:
    result = _result("Q12")
    assert result["substantive_verdict"] == "PASS"
    assert result["admission"] == "REJECTED"
    assert result["procedure_result"] == "EVALUATOR_FAILURE"
    assert [value["code"] for value in result["violations"]] == [
        "INVALID_VERDICT_STRUCTURE"
    ]


def test_fixture_inventory_detects_byte_drift(tmp_path: Path) -> None:
    source = QUALIFICATION_DIR / "fixtures" / "Q01"
    target = tmp_path / "Q01"
    shutil.copytree(source, target)
    path = target / "evidence" / "items" / "scope-record.json"
    path.write_bytes(path.read_bytes() + b" ")
    errors = verify_fixture_inventory(target)
    assert any("byte count differs" in value for value in errors)
    assert any("digest differs" in value for value in errors)


def test_fixture_suite_records_resolve_and_match() -> None:
    suite = load_json(QUALIFICATION_DIR / "fixture-suite.json")
    assert suite["fixture_ids"] == list(FIXTURE_IDS)
    assert suite["expected_totals"]["accepted"] == 7
    assert suite["expected_totals"]["rejected"] == 5
    for fixture in suite["fixtures"]:
        for field in (
            "fixture",
            "evidence_packet",
            "raw_stream",
            "grade",
            "expected",
        ):
            record = fixture[field]
            path = QUALIFICATION_DIR / record["path"]
            assert path.is_file()
            assert path.stat().st_size == record["bytes"]
            assert sha256_file(path) == record["sha256"]


def test_only_q12_is_intentionally_schema_invalid() -> None:
    schema = load_json(GRADE_SCHEMA)
    invalid: list[str] = []
    for fixture_id in FIXTURE_IDS:
        grade = load_json(
            QUALIFICATION_DIR / "fixtures" / fixture_id / "grade.json"
        )
        try:
            jsonschema.validate(grade, schema)
        except jsonschema.ValidationError:
            invalid.append(fixture_id)
    assert invalid == ["Q12"]


def test_machine_roster_has_one_read_only_evidence_tool() -> None:
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))
    assert roster["tools"] == ["mcp__grader__evidence"]
    assert roster["provider_wire_tools"] == [
        {
            "canonical_name": "mcp__grader__evidence",
            "mode": "read-only",
            "server": "grader",
            "tool": "evidence",
        }
    ]
