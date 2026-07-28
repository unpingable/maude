#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Finalize qualification from preserved deterministic and live evidence."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


QUALIFICATION_DIR = Path(__file__).resolve().parents[1]
HARNESS_DIR = QUALIFICATION_DIR.parent / "harness"
REPO_ROOT = QUALIFICATION_DIR.parents[2]
RESULTS_DIR = QUALIFICATION_DIR / "results"
DETERMINISTIC_RESULT = RESULTS_DIR / "deterministic-qualification.json"
LIVE_RESULT = RESULTS_DIR / "live-qualification.json"
FINAL_RESULT = RESULTS_DIR / "qualification-result.json"

sys.path.insert(0, str(HARNESS_DIR))

from grader_admission import (  # noqa: E402
    canonical_json_bytes,
    load_json,
    load_jsonl,
    sha256_bytes,
    sha256_file,
)


def _git(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _record(path: Path, *, relative_to: Path = REPO_ROOT) -> dict[str, Any]:
    return {
        "path": path.relative_to(relative_to).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(canonical_json_bytes(value) + b"\n")
    temporary.replace(path)


def provider_terminal_errors(path: Path) -> list[dict[str, Any]]:
    """Extract provider-declared terminal errors without interpreting prose."""

    records: list[dict[str, Any]] = []
    for event_number, event in enumerate(load_jsonl(path), 1):
        if event.get("type") != "error" or not isinstance(
            event.get("message"), str
        ):
            continue
        message = event["message"]
        try:
            envelope = json.loads(message)
        except json.JSONDecodeError:
            envelope = None
        provider_error = (
            envelope.get("error")
            if isinstance(envelope, dict)
            and isinstance(envelope.get("error"), dict)
            else {}
        )
        records.append(
            {
                "event_number": event_number,
                "provider_error_type": provider_error.get("type"),
                "provider_error_code": provider_error.get("code"),
                "provider_error_param": provider_error.get("param"),
                "provider_status": (
                    envelope.get("status")
                    if isinstance(envelope, dict)
                    else None
                ),
                "message_sha256": sha256_bytes(message.encode("utf-8")),
                "raw_event_sha256": sha256_bytes(
                    canonical_json_bytes(event)
                ),
            }
        )
    return records


def _select_verdict(
    *,
    live: dict[str, Any],
    terminal_errors: list[dict[str, Any]],
) -> tuple[str, str]:
    admission_codes = {
        value.get("code")
        for probe in live.get("probes", [])
        for value in probe.get("admission_result", {}).get("violations", [])
        if isinstance(value, dict)
    }
    if "UNROSTERED_TOOL_ATTEMPT" in admission_codes:
        return (
            "NOT-QUALIFIED-TOOL-BOUNDARY",
            "A live raw stream contains an unrostered tool attempt.",
        )
    if any(
        value.get("provider_error_code") == "invalid_json_schema"
        for value in terminal_errors
    ):
        return (
            "NOT-QUALIFIED-VERDICT-VALIDATION",
            (
                "The provider rejected the frozen output schema before any "
                "grader could read evidence or emit a verdict."
            ),
        )
    return (
        str(live["qualification_verdict"]),
        "No narrower provider terminal condition superseded the live result.",
    )


def finalize() -> dict[str, Any]:
    deterministic = load_json(DETERMINISTIC_RESULT)
    live = load_json(LIVE_RESULT)
    probes = live.get("probes")
    if not isinstance(probes, list) or len(probes) != 5:
        raise RuntimeError("live result does not contain exactly five probes")

    raw_records: list[dict[str, Any]] = []
    all_terminal_errors: list[dict[str, Any]] = []
    thread_ids: list[str] = []
    for probe in probes:
        probe_id = probe.get("probe_id")
        raw_record = probe.get("raw_stdout")
        if not isinstance(probe_id, str) or not isinstance(raw_record, dict):
            raise RuntimeError("live probe identity or raw record is malformed")
        raw_path = REPO_ROOT / str(raw_record.get("path"))
        if (
            not raw_path.is_file()
            or raw_path.stat().st_size != raw_record.get("bytes")
            or sha256_file(raw_path) != raw_record.get("sha256")
        ):
            raise RuntimeError(f"{probe_id}: preserved raw stream differs")
        errors = provider_terminal_errors(raw_path)
        raw_records.append(
            {
                "probe_id": probe_id,
                "raw_stdout": raw_record,
                "provider_terminal_errors": errors,
                "observed_tool_request_count": len(
                    probe.get("admission_result", {}).get(
                        "observed_tool_requests", []
                    )
                ),
                "accepted_grade": (
                    probe.get("admission_result", {}).get("admission")
                    == "ACCEPTED"
                ),
            }
        )
        all_terminal_errors.extend(
            {"probe_id": probe_id, **value} for value in errors
        )
        identity = probe.get("provider_session_identity", {}).get(
            "provider_thread_id"
        )
        if isinstance(identity, str) and identity:
            thread_ids.append(identity)

    session_separation = (
        len(thread_ids) == 5 and len(thread_ids) == len(set(thread_ids))
    )
    schema_rejections = [
        value
        for value in all_terminal_errors
        if value.get("provider_error_code") == "invalid_json_schema"
        and value.get("provider_error_param") == "text.format.schema"
    ]
    if len(schema_rejections) != 5:
        raise RuntimeError(
            "the preserved five-probe schema-rejection condition differs"
        )
    if any(value["observed_tool_request_count"] for value in raw_records):
        raise RuntimeError(
            "provider schema rejection unexpectedly coexists with tool calls"
        )
    if any(value["accepted_grade"] for value in raw_records):
        raise RuntimeError(
            "provider schema rejection unexpectedly coexists with acceptance"
        )

    verdict, basis = _select_verdict(
        live=live,
        terminal_errors=all_terminal_errors,
    )
    finalizer_path = Path(__file__).resolve()
    return {
        "qualification_schema_version": (
            "maude.synthetic-operator.grader-qualification-result.v1"
        ),
        "qualification_verdict": verdict,
        "qualification_verdict_basis": basis,
        "live_harness_commit": live["harness_commit"],
        "finalization_commit": _git("rev-parse", "HEAD"),
        "result_finalizer": _record(finalizer_path),
        "provider": live["provider"],
        "provider_config": live["provider_config"],
        "model": live["model"],
        "model_family": live["model_family"],
        "reasoning_setting": live["reasoning_setting"],
        "provider_runtime": live["provider_runtime"],
        "grader_prompt_digests": live["grader_prompt_digests"],
        "allowed_tool_roster": live["allowed_tool_roster"],
        "effective_tool_surface_equals_declared_roster": live[
            "effective_tool_surface_equals_declared_roster"
        ],
        "validator_version": live["validator_version"],
        "fixture_suite": live["fixture_suite"],
        "deterministic_result": _record(DETERMINISTIC_RESULT),
        "deterministic_test_totals": deterministic[
            "deterministic_test_totals"
        ],
        "source_live_result": _record(LIVE_RESULT),
        "live_probe_totals": live["live_probe_totals"],
        "live_provider_attempts": 5,
        "completed_live_grader_results": 0,
        "fresh_session_separation": {
            "provider_thread_ids": thread_ids,
            "all_present_and_unique": session_separation,
        },
        "provider_terminal_errors": all_terminal_errors,
        "raw_stream_assessments": raw_records,
        "violations": [
            {
                "code": "PROVIDER_OUTPUT_SCHEMA_REJECTED",
                "probe_id": value["probe_id"],
                "provider_error_code": value["provider_error_code"],
                "provider_error_param": value["provider_error_param"],
                "raw_event_sha256": value["raw_event_sha256"],
            }
            for value in schema_rejections
        ],
        "residual_limitations": [
            (
                "No live grader reached evidence reading or verdict "
                "generation because the frozen output schema was rejected."
            ),
            (
                "Codex 0.145.0 still exposes provider-internal resource "
                "discovery beyond the declared grader roster."
            ),
            (
                "Operator and grader remain in the same OpenAI model family; "
                "fresh threads do not establish model-family independence."
            ),
            (
                "Generation four remains aborted and generation five has not "
                "started."
            ),
        ],
        "no_retry_or_salvage": True,
        "generation_four_reinterpreted": False,
        "generation_five_started": False,
        "maude_product_finding": False,
        "authority_effect": "none",
        "self_exclusion": (
            "qualification-result.json excludes its own byte count and digest"
        ),
    }


def main() -> int:
    result = finalize()
    _write_json(FINAL_RESULT, result)
    print(
        json.dumps(
            {
                "qualification_verdict": result["qualification_verdict"],
                "live_provider_attempts": result["live_provider_attempts"],
                "completed_live_grader_results": result[
                    "completed_live_grader_results"
                ],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
