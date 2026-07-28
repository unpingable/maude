#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run the provider-free independent-grader qualification fixtures."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


QUALIFICATION_DIR = Path(__file__).resolve().parents[1]
HARNESS_DIR = QUALIFICATION_DIR.parent / "harness"
REPO_ROOT = QUALIFICATION_DIR.parents[2]
sys.path.insert(0, str(HARNESS_DIR))

from grader_admission import (  # noqa: E402
    VALIDATOR_VERSION,
    canonical_json_bytes,
    load_json,
    result_matches_expected,
    sha256_file,
    validate_fixture,
    validate_result_shape,
    verify_fixture_inventory,
)


def _git(*arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _record(path: Path, *, relative_to: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(relative_to).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def run() -> dict[str, Any]:
    fixture_root = QUALIFICATION_DIR / "fixtures"
    expected_root = QUALIFICATION_DIR / "expected"
    roster = QUALIFICATION_DIR / "allowed-tool-roster.json"
    schema = QUALIFICATION_DIR / "schemas" / "grader-output.schema.json"
    suite = QUALIFICATION_DIR / "fixture-suite.json"
    fixture_dirs = sorted(
        path for path in fixture_root.glob("Q*") if path.is_dir()
    )
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    for fixture_dir in fixture_dirs:
        fixture_id = fixture_dir.name
        inventory_errors = verify_fixture_inventory(fixture_dir)
        result = validate_fixture(
            fixture_dir,
            roster_path=roster,
            grade_schema_path=schema,
        )
        validate_result_shape(result)
        expected = load_json(expected_root / f"{fixture_id}.json")
        matched, comparison_errors = result_matches_expected(result, expected)
        current_errors = [
            *(f"inventory: {value}" for value in inventory_errors),
            *(f"oracle: {value}" for value in comparison_errors),
        ]
        results.append(
            {
                "fixture_id": fixture_id,
                "passed": not current_errors and matched,
                "errors": current_errors,
                "admission_result": result,
            }
        )
        errors.extend(f"{fixture_id}: {value}" for value in current_errors)

    suite_value = load_json(suite)
    declared_ids = suite_value.get("fixture_ids")
    actual_ids = [path.name for path in fixture_dirs]
    if declared_ids != actual_ids:
        errors.append(
            f"fixture suite IDs differ: declared={declared_ids!r} "
            f"actual={actual_ids!r}"
        )
    accepted = sum(
        value["admission_result"]["admission"] == "ACCEPTED"
        for value in results
    )
    rejected = len(results) - accepted
    expected_totals = suite_value.get("expected_totals", {})
    if accepted != expected_totals.get("accepted"):
        errors.append("accepted-grade aggregate differs from fixture suite")
    if rejected != expected_totals.get("rejected"):
        errors.append("rejected-grade aggregate differs from fixture suite")

    passed = len(results) == 12 and not errors and all(
        value["passed"] for value in results
    )
    prompt_system = QUALIFICATION_DIR / "prompts" / "grader-system.md"
    prompt_request = (
        QUALIFICATION_DIR / "prompts" / "grader-request-template.md"
    )
    policy = QUALIFICATION_DIR / "grader-admission-policy.json"
    harness = HARNESS_DIR / "grader_admission.py"
    return {
        "qualification_schema_version": (
            "maude.synthetic-operator.grader-qualification-result.v1"
        ),
        "layer": "deterministic",
        "harness_commit": _git("rev-parse", "HEAD"),
        "harness": _record(harness, relative_to=REPO_ROOT),
        "provider": None,
        "model": None,
        "reasoning_setting": None,
        "grader_prompt_digests": {
            "system": _record(prompt_system, relative_to=REPO_ROOT),
            "request_template": _record(prompt_request, relative_to=REPO_ROOT),
        },
        "allowed_tool_roster": _record(roster, relative_to=REPO_ROOT),
        "validator_version": VALIDATOR_VERSION,
        "validator_policy": _record(policy, relative_to=REPO_ROOT),
        "fixture_suite": _record(suite, relative_to=REPO_ROOT),
        "grader_output_schema": _record(schema, relative_to=REPO_ROOT),
        "fixture_count": len(results),
        "deterministic_test_totals": {
            "passed": sum(value["passed"] for value in results),
            "failed": sum(not value["passed"] for value in results),
            "total": len(results),
        },
        "grade_admission_totals": {
            "accepted": accepted,
            "rejected": rejected,
            "accepted_product_pass_or_fail": sum(
                value["admission_result"][
                    "counts_as_product_pass_or_fail"
                ]
                for value in results
            ),
            "accepted_indeterminate": sum(
                value["admission_result"][
                    "counts_as_accepted_independent_grade"
                ]
                and value["admission_result"]["substantive_verdict"]
                == "INDETERMINATE"
                for value in results
            ),
        },
        "fixtures": results,
        "violations": errors,
        "residual_limitations": [
            "Deterministic qualification does not prove provider capability restriction.",
            "Live provider/model behavior is not exercised by this layer.",
            "Session separation does not establish model-family independence.",
        ],
        "qualification_verdict": (
            "DETERMINISTICALLY-QUALIFIED-LIVE-PROBE-PENDING"
            if passed
            else "NOT-QUALIFIED-VERDICT-VALIDATION"
        ),
        "authority_effect": "none",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=(
            QUALIFICATION_DIR
            / "results"
            / "deterministic-qualification.json"
        ),
    )
    arguments = parser.parse_args()
    result = run()
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_bytes(canonical_json_bytes(result) + b"\n")
    print(json.dumps(result["deterministic_test_totals"], sort_keys=True))
    return 0 if result["qualification_verdict"].startswith(
        "DETERMINISTICALLY-QUALIFIED"
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
