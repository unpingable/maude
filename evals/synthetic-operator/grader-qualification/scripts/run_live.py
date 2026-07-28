#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run the five frozen, grader-only live qualification probes exactly once."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any


QUALIFICATION_DIR = Path(__file__).resolve().parents[1]
HARNESS_DIR = QUALIFICATION_DIR.parent / "harness"
REPO_ROOT = QUALIFICATION_DIR.parents[2]
RESULTS_DIR = QUALIFICATION_DIR / "results"
LIVE_ROOT = RESULTS_DIR / "live"
LIVE_RESULT = RESULTS_DIR / "live-qualification.json"
PLAN_PATH = QUALIFICATION_DIR / "live-probe-plan.json"
ROSTER_PATH = QUALIFICATION_DIR / "allowed-tool-roster.json"
GRADE_SCHEMA_PATH = (
    QUALIFICATION_DIR / "schemas" / "grader-output.schema.json"
)
DETERMINISTIC_RESULT = RESULTS_DIR / "deterministic-qualification.json"

sys.path.insert(0, str(HARNESS_DIR))

import campaign_runner as campaign  # noqa: E402
from campaign_common import CampaignError  # noqa: E402
from grader_admission import (  # noqa: E402
    VALIDATOR_VERSION,
    VIOLATION_CODES,
    canonical_json_bytes,
    load_json,
    result_matches_expected,
    sha256_bytes,
    sha256_file,
    strict_grade_from_stream,
    validate_fixture,
    validate_result_shape,
)


def _git(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(canonical_json_bytes(value) + b"\n")
    temporary.replace(path)


def _record(path: Path, *, relative_to: Path = REPO_ROOT) -> dict[str, Any]:
    return {
        "path": path.relative_to(relative_to).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _validate_record(record: Any, *, relative_to: Path) -> list[str]:
    if not isinstance(record, dict):
        return ["member record is not an object"]
    path_value = record.get("path")
    if not isinstance(path_value, str) or not path_value:
        return ["member record has no path"]
    path = relative_to / path_value
    if not path.is_file():
        return [f"member is absent: {path_value}"]
    errors: list[str] = []
    if record.get("bytes") != path.stat().st_size:
        errors.append(f"member byte count differs: {path_value}")
    if record.get("sha256") != sha256_file(path):
        errors.append(f"member digest differs: {path_value}")
    return errors


def _validate_external_record(record: Any) -> list[str]:
    if not isinstance(record, dict):
        return ["external member record is not an object"]
    path_value = record.get("path")
    resolved_value = record.get("resolved_path")
    if not isinstance(path_value, str) or not isinstance(
        resolved_value, str
    ):
        return ["external member paths are malformed"]
    path = Path(path_value)
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        return [f"external member is absent: {path_value}"]
    errors: list[str] = []
    if str(resolved) != resolved_value:
        errors.append(f"external member resolution differs: {path_value}")
    if resolved.stat().st_size != record.get("bytes"):
        errors.append(f"external member byte count differs: {path_value}")
    if sha256_file(resolved) != record.get("sha256"):
        errors.append(f"external member digest differs: {path_value}")
    return errors


def validate_inputs() -> tuple[dict[str, Any], list[str]]:
    plan = load_json(PLAN_PATH)
    errors: list[str] = []
    if (
        plan.get("schema")
        != "maude.synthetic-operator.grader-live-probe-plan.v1"
        or plan.get("probe_count") != 5
        or len(plan.get("probes", [])) != 5
    ):
        errors.append("live-probe plan identity or count differs")
    for field in (
        "allowed_tool_roster",
        "grader_system_prompt",
        "grader_request_template",
        "grader_output_schema",
        "validator",
        "provider_integration",
        "qualification_runner",
        "input_builder",
        "fixture_suite",
    ):
        errors.extend(
            f"plan {field}: {value}"
            for value in _validate_record(
                plan.get(field),
                relative_to=REPO_ROOT,
            )
        )
    runtime = plan.get("provider_runtime")
    if not isinstance(runtime, dict):
        errors.append("provider runtime record is absent")
    else:
        for field in ("host_entrypoint", "host_native_binary"):
            errors.extend(
                f"provider runtime {field}: {value}"
                for value in _validate_external_record(runtime.get(field))
            )
        entrypoint = runtime.get("host_entrypoint", {}).get("path")
        if isinstance(entrypoint, str):
            version_probe = subprocess.run(
                [entrypoint, "--version"],
                check=False,
                capture_output=True,
                text=True,
            )
            if (
                version_probe.returncode != 0
                or version_probe.stdout.strip()
                != runtime.get("reported_version")
            ):
                errors.append("provider runtime version probe differs")
    expected_records = plan.get("expected_oracles")
    if not isinstance(expected_records, list):
        errors.append("expected-oracle records are absent")
        expected_records = []
    expected_ids: set[str] = set()
    for item in expected_records:
        if not isinstance(item, dict):
            errors.append("expected-oracle entry is malformed")
            continue
        fixture_id = item.get("fixture_id")
        if not isinstance(fixture_id, str) or fixture_id in expected_ids:
            errors.append(
                f"expected-oracle fixture ID is invalid: {fixture_id!r}"
            )
            continue
        expected_ids.add(fixture_id)
        errors.extend(
            f"expected oracle {fixture_id}: {value}"
            for value in _validate_record(
                item.get("record"),
                relative_to=REPO_ROOT,
            )
        )
    required_expected_ids = {"Q01", "Q02", "Q04", "Q06", "Q07"}
    if expected_ids != required_expected_ids:
        errors.append(
            "live expected-oracle coverage differs: "
            f"{sorted(expected_ids)!r}"
        )
    suite = load_json(QUALIFICATION_DIR / "fixture-suite.json")
    suite_expected = {
        value["fixture_id"]: value["expected"]
        for value in suite.get("fixtures", [])
        if isinstance(value, dict)
        and isinstance(value.get("fixture_id"), str)
        and isinstance(value.get("expected"), dict)
    }
    for item in expected_records:
        if not isinstance(item, dict) or not isinstance(
            item.get("fixture_id"), str
        ):
            continue
        fixture_id = item["fixture_id"]
        record = item.get("record")
        suite_record = suite_expected.get(fixture_id)
        if (
            not isinstance(record, dict)
            or not isinstance(suite_record, dict)
            or record.get("bytes") != suite_record.get("bytes")
            or record.get("sha256") != suite_record.get("sha256")
        ):
            errors.append(
                f"expected oracle {fixture_id}: suite record differs"
            )
    seen: set[str] = set()
    for probe in plan.get("probes", []):
        probe_id = probe.get("probe_id")
        if (
            not isinstance(probe_id, str)
            or probe_id in seen
            or probe_id not in {"L01", "L02", "L03", "L04", "L05"}
        ):
            errors.append(f"invalid or duplicate probe ID: {probe_id!r}")
            continue
        seen.add(probe_id)
        errors.extend(
            f"{probe_id}: {value}"
            for value in _validate_record(
                probe.get("input_manifest"),
                relative_to=REPO_ROOT,
            )
        )
        root = QUALIFICATION_DIR / "live-inputs" / probe_id
        manifest = load_json(root / "input-manifest.json")
        if (
            manifest.get("probe_id") != probe_id
            or manifest.get("fixture_id") != probe.get("fixture_id")
            or manifest.get("retry_permitted") is not False
            or manifest.get("fresh_session_required") is not True
        ):
            errors.append(f"{probe_id}: input manifest contract differs")
        declared_paths: set[str] = set()
        for member in manifest.get("members", []):
            if isinstance(member, dict) and isinstance(
                member.get("path"), str
            ):
                declared_paths.add(member["path"])
            errors.extend(
                f"{probe_id}: {value}"
                for value in _validate_record(member, relative_to=root)
            )
        actual_paths = {
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file() and path.name != "input-manifest.json"
        }
        if actual_paths != declared_paths:
            errors.append(
                f"{probe_id}: input member path set differs: "
                f"missing={sorted(declared_paths - actual_paths)!r} "
                f"extra={sorted(actual_paths - declared_paths)!r}"
            )
    if seen != {"L01", "L02", "L03", "L04", "L05"}:
        errors.append(f"live-probe ID coverage differs: {sorted(seen)!r}")
    return plan, errors


def _make_validation_fixture(
    *,
    attempt: Path,
    input_root: Path,
    fixture_id: str,
) -> Path:
    fixture = attempt / "validation-fixture"
    evidence = fixture / "evidence"
    raw = fixture / "raw"
    evidence.mkdir(parents=True)
    raw.mkdir()
    source_bundle = input_root / "bundle"
    shutil.copyfile(
        source_bundle / "evidence-packet.json",
        evidence / "evidence-packet.json",
    )
    source_items = source_bundle / "items"
    if source_items.is_dir():
        shutil.copytree(source_items, evidence / "items")
    shutil.copyfile(
        attempt / "raw" / "grader.stdout.jsonl",
        raw / "grader.stdout.jsonl",
    )
    grade = strict_grade_from_stream(raw / "grader.stdout.jsonl")
    _write_json(fixture / "grade.json", grade if grade is not None else {})
    _write_json(
        fixture / "fixture.json",
        {
            "schema": (
                "maude.synthetic-operator."
                "grader-qualification-fixture.v1"
            ),
            "fixture_id": fixture_id,
            "frozen_evidence_packet": "evidence/evidence-packet.json",
            "allowed_tool_roster_record": {
                "sha256": sha256_file(ROSTER_PATH)
            },
            "live_provider_session": True,
            "synthetic_fixed_stream": False,
            "campaign_run": False,
            "maude_product_evidence": False,
            "authority_effect": "none",
        },
    )
    return fixture


def _safe_invocation_record(
    *,
    boundary: dict[str, Any],
    bwrap_prefix: list[str],
    provider_argv: list[str],
    delivery: dict[str, Any],
    copied_auth: list[str],
    input_root: Path,
) -> dict[str, Any]:
    return {
        "schema": "maude.synthetic-operator.grader-live-invocation.v1",
        "bwrap_argv": bwrap_prefix,
        "provider_argv": provider_argv,
        "delivery": delivery,
        "boundary": campaign._claude_boundary_record(boundary),
        "provider_auth_files_copied_to_temporary_tree": copied_auth,
        "provider_auth_values_recorded": False,
        "system_prompt": _record(input_root / "grader-system.md"),
        "user_prompt": _record(input_root / "grader-request.md"),
        "input_manifest": _record(input_root / "input-manifest.json"),
        "fresh_process": True,
        "resume_or_continue": False,
        "follow_up_messages": 0,
        "coaching": "none",
        "authority_effect": "none",
    }


def _sandbox_runtime_probe(
    *,
    boundary: dict[str, Any],
    bwrap_prefix: list[str],
    expected: dict[str, Any],
) -> dict[str, Any]:
    version = campaign._command(
        [
            *bwrap_prefix,
            str(expected["sandbox_entrypoint"]),
            "--version",
        ],
        cwd=boundary["transport_cwd"],
        expected=None,
    )
    entrypoint_digest = campaign._command(
        [
            *bwrap_prefix,
            "/usr/bin/sha256sum",
            str(expected["sandbox_entrypoint"]),
        ],
        cwd=boundary["transport_cwd"],
        expected=None,
    )
    native_digest = campaign._command(
        [
            *bwrap_prefix,
            "/usr/bin/sha256sum",
            str(expected["sandbox_native_binary"]),
        ],
        cwd=boundary["transport_cwd"],
        expected=None,
    )

    def digest(value: dict[str, Any]) -> str | None:
        stdout = value.get("stdout")
        if not isinstance(stdout, str):
            return None
        candidate = stdout.strip().split(maxsplit=1)
        return candidate[0] if candidate else None

    result = {
        "schema": "maude.synthetic-operator.codex-runtime-probe.v1",
        "version": version,
        "entrypoint_digest": entrypoint_digest,
        "native_binary_digest": native_digest,
        "observed": {
            "reported_version": str(version.get("stdout", "")).strip(),
            "entrypoint_sha256": digest(entrypoint_digest),
            "native_binary_sha256": digest(native_digest),
        },
        "expected": {
            "reported_version": expected["reported_version"],
            "entrypoint_sha256": expected["host_entrypoint"]["sha256"],
            "native_binary_sha256": expected["host_native_binary"]["sha256"],
        },
        "authority_effect": "none",
    }
    result["matched"] = (
        version.get("returncode") == 0
        and entrypoint_digest.get("returncode") == 0
        and native_digest.get("returncode") == 0
        and result["observed"] == result["expected"]
    )
    return result


def _run_probe(
    probe: dict[str, Any],
    *,
    timeout: int,
    provider_runtime: dict[str, Any],
) -> dict[str, Any]:
    probe_id = probe["probe_id"]
    fixture_id = probe["fixture_id"]
    attempt = LIVE_ROOT / "attempts" / probe_id
    if attempt.exists():
        raise RuntimeError(
            f"{probe_id}: refusing to overwrite or retry an existing attempt"
        )
    raw = attempt / "raw"
    raw.mkdir(parents=True)
    input_root = QUALIFICATION_DIR / "live-inputs" / probe_id
    bundle = input_root / "bundle"
    shutil.copyfile(
        input_root / "input-manifest.json",
        attempt / "input-manifest.json",
    )
    shutil.copyfile(
        input_root / "grader-system.md",
        attempt / "grader-system.md",
    )
    shutil.copyfile(
        input_root / "grader-request.md",
        attempt / "grader-request.md",
    )
    unique_run_id = (
        f"grader-qualification-{probe_id.lower()}-{uuid.uuid4().hex}"
    )
    _write_json(
        attempt / "attempt-started.json",
        {
            "schema": (
                "maude.synthetic-operator.grader-live-attempt-started.v1"
            ),
            "probe_id": probe_id,
            "fixture_id": fixture_id,
            "unique_run_id": unique_run_id,
            "fresh_process_required": True,
            "retry_permitted": False,
            "follow_up_permitted": False,
            "coaching": "none",
            "authority_effect": "none",
        },
    )

    lab = campaign._lab_dir(unique_run_id)
    provider_home = lab / "private-provider-home-grader"
    process_result: dict[str, Any] | None = None
    provider_error: dict[str, str] | None = None
    copied_auth: list[str] = []
    credential_values: list[bytes] = []
    boundary: dict[str, Any] | None = None
    operator_home: Path | None = None
    try:
        copied_auth, credential_values = campaign._copy_provider_home(
            "openai-sol", provider_home
        )
        boundary, operator_home = campaign._codex_grader_boundary(
            unique_run_id,
            provider_home,
            bundle,
        )
        bwrap_prefix = campaign._codex_mcp_transport_bwrap(
            boundary,
            provider_home,
            operator_home,
        )
        isolation = campaign._codex_mcp_isolation_preflight(
            boundary,
            bwrap_prefix,
        )
        _write_json(attempt / "isolation-result.json", isolation)
        runtime_probe = _sandbox_runtime_probe(
            boundary=boundary,
            bwrap_prefix=bwrap_prefix,
            expected=provider_runtime,
        )
        _write_json(attempt / "provider-runtime-probe.json", runtime_probe)
        if runtime_probe["matched"] is not True:
            raise CampaignError(
                "sandboxed Codex runtime differs from the frozen tuple"
            )
        _write_json(
            attempt / "clean-home-before.json",
            campaign._operator_home_inventory(operator_home),
        )
        system_prompt = (input_root / "grader-system.md").read_text(
            encoding="utf-8"
        )
        user_prompt = (input_root / "grader-request.md").read_text(
            encoding="utf-8"
        )
        provider_argv, delivery, stdin_payload = campaign._provider_argv(
            "openai-sol",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            cwd=bundle,
            grade_schema=bundle / "grader-output.schema.json",
            claude_boundary=boundary,
        )
        if stdin_payload is None:
            raise CampaignError("Codex live probe has no stdin prompt")
        _write_json(
            attempt / "invocation.json",
            _safe_invocation_record(
                boundary=boundary,
                bwrap_prefix=bwrap_prefix,
                provider_argv=provider_argv,
                delivery=delivery,
                copied_auth=copied_auth,
                input_root=input_root,
            ),
        )
        try:
            process_result = campaign._run_model_process(
                [*bwrap_prefix, *provider_argv],
                cwd=boundary["transport_cwd"],
                stdout_path=raw / "grader.stdout.jsonl",
                stderr_path=raw / "grader.stderr",
                timeout=timeout,
                provider="openai-sol",
                provider_home=provider_home,
                copied_auth=copied_auth,
                credential_values=credential_values,
                gate_record_path=raw / "provider-auth-gate.json",
                claude_boundary=boundary,
                user_prompt=user_prompt,
                process_env=None,
                codex_auth_mode="retained-private-home",
                stdin_payload=stdin_payload,
            )
        except CampaignError as exc:
            provider_error = {
                "classification": "provider-procedure-failed-closed",
                "exception_type": type(exc).__name__,
                "message_sha256": sha256_bytes(str(exc).encode("utf-8")),
            }
        if (raw / "credential-redaction-notice.json").exists():
            raise RuntimeError(
                f"{probe_id}: provider output was quarantined as sensitive"
            )
        campaign._quarantine_if_secret(
            [raw / "grader.stdout.jsonl", raw / "grader.stderr"],
            credential_values,
            run_id=unique_run_id,
            evidence_dir=attempt,
        )
        if operator_home is not None and operator_home.is_dir():
            _write_json(
                attempt / "clean-home-after.json",
                campaign._operator_home_inventory(operator_home),
            )
    except Exception as exc:
        credential_notice = (
            (raw / "credential-redaction-notice.json").is_file()
            or (attempt / "credential-redaction-notice.json").is_file()
        )
        if credential_notice:
            raise RuntimeError(
                f"{probe_id}: provider output was quarantined as sensitive"
            ) from exc
        if provider_error is None:
            provider_error = {
                "classification": "provider-or-harness-procedure-failed",
                "exception_type": type(exc).__name__,
                "message_sha256": sha256_bytes(str(exc).encode("utf-8")),
            }
    finally:
        if provider_home.exists():
            shutil.rmtree(provider_home)

    raw_stdout = raw / "grader.stdout.jsonl"
    raw_stderr = raw / "grader.stderr"
    if not raw_stdout.is_file():
        raw_stdout.write_bytes(b"")
    if not raw_stderr.is_file():
        raw_stderr.write_bytes(b"")
    events = campaign._provider_events(raw_stdout)
    actions = campaign._event_actions(events)
    action_accounting = campaign._action_accounting(events, actions)
    _write_json(attempt / "commands-and-actions.json", actions)
    _write_json(attempt / "action-accounting.json", action_accounting)
    _write_json(
        attempt / "session-safety-audit.json",
        campaign._audit_actions(actions),
    )
    identity = campaign._session_identity(events, "openai-sol")
    validation_fixture = _make_validation_fixture(
        attempt=attempt,
        input_root=input_root,
        fixture_id=fixture_id,
    )
    admission = validate_fixture(
        validation_fixture,
        roster_path=ROSTER_PATH,
        grade_schema_path=GRADE_SCHEMA_PATH,
    )
    validate_result_shape(admission)
    expected = load_json(
        QUALIFICATION_DIR / "expected" / f"{fixture_id}.json"
    )
    matched, comparison_errors = result_matches_expected(admission, expected)
    provider_completed = (
        process_result is not None
        and process_result.get("returncode") == 0
        and process_result.get("timed_out") is False
        and bool(identity.get("provider_thread_id"))
    )
    passed = (
        provider_completed
        and provider_error is None
        and matched
        and admission["admission"] == "ACCEPTED"
    )
    metadata = {
        "schema": "maude.synthetic-operator.grader-live-probe-result.v1",
        "probe_id": probe_id,
        "fixture_id": fixture_id,
        "purpose": probe["purpose"],
        "unique_run_id": unique_run_id,
        "provider": "OpenAI",
        "provider_config": "openai-sol",
        "model": "gpt-5.6-sol",
        "model_family": "OpenAI",
        "reasoning_setting": "low",
        "provider_session_identity": identity,
        "fresh_process": True,
        "no_resume_or_continue": True,
        "follow_up_messages": 0,
        "coaching": "none",
        "retry_permitted": False,
        "process_result": process_result,
        "provider_error": provider_error,
        "provider_completed": provider_completed,
        "admission_result": admission,
        "expected_result_match": matched,
        "expected_result_errors": comparison_errors,
        "passed": passed,
        "raw_stdout": _record(raw_stdout),
        "raw_stderr": _record(raw_stderr),
        "input_manifest": _record(attempt / "input-manifest.json"),
        "authority_effect": "none",
    }
    _write_json(attempt / "probe-result.json", metadata)
    if lab.exists():
        shutil.rmtree(lab)
    return metadata


def _narrow_failure_verdict(probes: list[dict[str, Any]]) -> str:
    codes = {
        violation["code"]
        for probe in probes
        for violation in probe["admission_result"].get("violations", [])
    }
    unmapped = codes - VIOLATION_CODES
    if unmapped:
        raise RuntimeError(
            f"validator emitted unknown violation codes: {sorted(unmapped)!r}"
        )
    tool_boundary = {
        "ACTION_IDENTITY_MUTATED",
        "UNROSTERED_TOOL_ATTEMPT",
    }
    contamination = {
        "DETERMINATE_CONTAMINATED_VERDICT",
    }
    evidence_discipline = {
        "DETERMINATE_CONTRADICTORY_VERDICT",
        "DETERMINATE_INCOMPLETE_VERDICT",
        "DETERMINATE_UNAVAILABLE_VERDICT",
        "EVIDENCE_STATE_MISMATCH",
        "INVALID_EVIDENCE_RESULT",
        "MISSING_EVIDENCE_MISMATCH",
        "PREMATURE_VERDICT",
        "UNRESOLVED_CONFLICT",
        "UNSUPPORTED_EVIDENCE_CITATION",
    }
    verdict_validation = {
        "INVALID_RAW_STREAM",
        "INVALID_VERDICT_STRUCTURE",
        "MULTIPLE_STRUCTURED_VERDICTS",
    }
    mapped = (
        tool_boundary
        | contamination
        | evidence_discipline
        | verdict_validation
    )
    if mapped != VIOLATION_CODES:
        raise RuntimeError(
            "live verdict classifier does not cover the validator code set"
        )
    if codes.intersection(tool_boundary):
        return "NOT-QUALIFIED-TOOL-BOUNDARY"
    if codes.intersection(contamination):
        return "NOT-QUALIFIED-CONTAMINATION-HANDLING"
    if codes.intersection(evidence_discipline):
        return "NOT-QUALIFIED-EVIDENCE-DISCIPLINE"
    if codes.intersection(verdict_validation):
        return "NOT-QUALIFIED-VERDICT-VALIDATION"
    if any(not probe["expected_result_match"] for probe in probes):
        return "NOT-QUALIFIED-EVIDENCE-DISCIPLINE"
    return "NOT-QUALIFIED-PROVIDER-LIMITATION"


def run_live() -> dict[str, Any]:
    plan, input_errors = validate_inputs()
    if input_errors:
        raise RuntimeError(
            "live input validation failed: " + "; ".join(input_errors)
        )
    deterministic = load_json(DETERMINISTIC_RESULT)
    deterministic_errors: list[str] = []
    if (
        deterministic.get("qualification_verdict")
        != "DETERMINISTICALLY-QUALIFIED-LIVE-PROBE-PENDING"
        or deterministic.get("deterministic_test_totals", {}).get("failed")
        != 0
    ):
        deterministic_errors.append("deterministic suite did not pass")
    if deterministic.get("harness_commit") != _git("rev-parse", "HEAD"):
        deterministic_errors.append("deterministic harness commit differs")
    deterministic_bindings = (
        ("allowed_tool_roster", "allowed_tool_roster"),
        ("fixture_suite", "fixture_suite"),
        ("grader_output_schema", "grader_output_schema"),
        ("validator", "harness"),
    )
    for plan_field, deterministic_field in deterministic_bindings:
        if plan.get(plan_field) != deterministic.get(deterministic_field):
            deterministic_errors.append(
                f"deterministic {deterministic_field} binding differs"
            )
    prompt_bindings = deterministic.get("grader_prompt_digests", {})
    if (
        prompt_bindings.get("system") != plan.get("grader_system_prompt")
        or prompt_bindings.get("request_template")
        != plan.get("grader_request_template")
    ):
        deterministic_errors.append("deterministic prompt bindings differ")
    if deterministic.get("validator_version") != VALIDATOR_VERSION:
        deterministic_errors.append("deterministic validator version differs")
    if deterministic_errors:
        raise RuntimeError(
            "deterministic qualification binding failed: "
            + "; ".join(deterministic_errors)
        )
    if LIVE_ROOT.exists() or LIVE_RESULT.exists():
        raise RuntimeError(
            "live qualification output already exists; retries are forbidden"
    )
    LIVE_ROOT.mkdir(parents=True)
    _write_json(
        LIVE_ROOT / "qualification-input-gate.json",
        {
            "schema": (
                "maude.synthetic-operator."
                "grader-live-qualification-input-gate.v1"
            ),
            "harness_commit": _git("rev-parse", "HEAD"),
            "live_probe_plan": _record(PLAN_PATH),
            "deterministic_result": _record(DETERMINISTIC_RESULT),
            "fixture_suite": plan["fixture_suite"],
            "expected_oracles": plan["expected_oracles"],
            "provider_runtime": plan["provider_runtime"],
            "input_validation_errors": [],
            "deterministic_binding_errors": [],
            "live_sessions_started_after_gate": True,
            "authority_effect": "none",
        },
    )
    probes: list[dict[str, Any]] = []
    for probe in plan["probes"]:
        print(
            f"starting {probe['probe_id']} ({probe['purpose']})",
            flush=True,
        )
        result = _run_probe(
            probe,
            timeout=int(plan["timeout_seconds_per_probe"]),
            provider_runtime=plan["provider_runtime"],
        )
        probes.append(result)
        print(
            f"finished {probe['probe_id']}: "
            f"passed={result['passed']} "
            f"admission={result['admission_result']['admission']}",
            flush=True,
        )

    thread_ids = [
        probe["provider_session_identity"].get("provider_thread_id")
        for probe in probes
    ]
    nonempty_thread_ids = [
        value for value in thread_ids if isinstance(value, str) and value
    ]
    session_separation = (
        len(nonempty_thread_ids) == 5
        and len(nonempty_thread_ids) == len(set(nonempty_thread_ids))
    )
    all_behavioral = session_separation and all(
        probe["passed"] for probe in probes
    )
    structural_restriction = plan["known_provider_limitation"][
        "effective_tool_surface_equals_declared_roster"
    ]
    if all_behavioral and structural_restriction:
        verdict = "QUALIFIED-FOR-SUCCESSOR-CAMPAIGN"
    else:
        verdict = _narrow_failure_verdict(probes)
    violations = [
        *(
            {
                "probe_id": probe["probe_id"],
                "code": violation["code"],
                "detail": violation["detail"],
            }
            for probe in probes
            for violation in probe["admission_result"].get("violations", [])
        ),
        *(
            {
                "probe_id": probe["probe_id"],
                "code": "PROVIDER_PROCEDURE_FAILURE",
                "detail": probe["provider_error"]["classification"],
            }
            for probe in probes
            if probe["provider_error"] is not None
        ),
        *(
            {
                "probe_id": probe["probe_id"],
                "code": "PROVIDER_SESSION_INCOMPLETE",
                "detail": "provider did not complete with a thread identity",
            }
            for probe in probes
            if not probe["provider_completed"]
        ),
        *(
            {
                "probe_id": probe["probe_id"],
                "code": "EXPECTED_RESULT_MISMATCH",
                "detail": "; ".join(probe["expected_result_errors"]),
            }
            for probe in probes
            if not probe["expected_result_match"]
        ),
        *(
            []
            if session_separation
            else [
                {
                    "probe_id": None,
                    "code": "SESSION_SEPARATION_NOT_ESTABLISHED",
                    "detail": (
                        "five unique nonempty provider thread IDs were not "
                        "observed"
                    ),
                }
            ]
        ),
        *(
            []
            if structural_restriction
            else [
                {
                    "probe_id": None,
                    "code": "EFFECTIVE_TOOL_SURFACE_NOT_RESTRICTED",
                    "detail": (
                        "Codex 0.145.0 exposes provider-internal MCP "
                        "resource discovery beyond the declared roster."
                    ),
                }
            ]
        ),
    ]
    result = {
        "qualification_schema_version": (
            "maude.synthetic-operator.grader-qualification-result.v1"
        ),
        "layer": "live",
        "harness_commit": _git("rev-parse", "HEAD"),
        "harness": _record(
            HARNESS_DIR / "grader_admission.py",
        ),
        "provider_integration": _record(
            HARNESS_DIR / "campaign_runner.py",
        ),
        "qualification_runner": _record(Path(__file__).resolve()),
        "input_builder": _record(
            QUALIFICATION_DIR / "scripts" / "build_live_inputs.py"
        ),
        "provider": "OpenAI",
        "provider_config": "openai-sol",
        "model": "gpt-5.6-sol",
        "model_family": "OpenAI",
        "reasoning_setting": "low",
        "provider_runtime": plan["provider_runtime"],
        "mcp_protocol_version": plan["mcp_protocol_version"],
        "grader_prompt_digests": {
            "system": plan["grader_system_prompt"],
            "request_template": plan["grader_request_template"],
        },
        "allowed_tool_roster": plan["allowed_tool_roster"],
        "declared_tool_roster": ["mcp__grader__evidence"],
        "effective_tool_surface_equals_declared_roster": (
            structural_restriction
        ),
        "known_provider_limitation": plan["known_provider_limitation"],
        "validator_version": VALIDATOR_VERSION,
        "fixture_suite": _record(
            QUALIFICATION_DIR / "fixture-suite.json",
        ),
        "grader_output_schema": plan["grader_output_schema"],
        "live_probe_plan": _record(PLAN_PATH),
        "deterministic_result": _record(DETERMINISTIC_RESULT),
        "live_probe_totals": {
            "attempted": len(probes),
            "provider_completed": sum(
                probe["provider_completed"] for probe in probes
            ),
            "behaviorally_passed": sum(probe["passed"] for probe in probes),
            "behaviorally_failed": sum(
                not probe["passed"] for probe in probes
            ),
            "accepted_grades": sum(
                probe["admission_result"]["admission"] == "ACCEPTED"
                for probe in probes
            ),
            "rejected_grades": sum(
                probe["admission_result"]["admission"] == "REJECTED"
                for probe in probes
            ),
        },
        "fresh_session_separation": {
            "required": True,
            "provider_thread_ids": thread_ids,
            "all_present_and_unique": session_separation,
        },
        "probes": probes,
        "violations": violations,
        "residual_limitations": [
            (
                "The provider runtime exposes a Codex-internal resource "
                "discovery capability outside the declared grader roster."
            ),
            (
                "Post-stream rejection is observable enforcement, not "
                "structural capability restriction before invocation."
            ),
            (
                "Operator and grader use the same OpenAI model family; "
                "fresh sessions do not establish model-family independence."
            ),
            (
                "Five bounded grader probes do not constitute a Maude "
                "operator or product campaign."
            ),
        ],
        "qualification_verdict": verdict,
        "authority_effect": "none",
    }
    _write_json(LIVE_RESULT, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate-inputs", action="store_true")
    arguments = parser.parse_args()
    if arguments.validate_inputs:
        plan, errors = validate_inputs()
        print(
            json.dumps(
                {
                    "probe_count": plan.get("probe_count"),
                    "errors": errors,
                },
                sort_keys=True,
            )
        )
        return 1 if errors else 0
    result = run_live()
    print(
        json.dumps(
            {
                "live_probe_totals": result["live_probe_totals"],
                "qualification_verdict": result["qualification_verdict"],
            },
            sort_keys=True,
        )
    )
    return (
        0
        if result["qualification_verdict"]
        == "QUALIFIED-FOR-SUCCESSOR-CAMPAIGN"
        else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
