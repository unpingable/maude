#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Provider-free independent-grader stream and admission validation.

The generation-four runner is preserved as historical apparatus.  This module
implements the stricter, opt-in admission protocol qualified by the fixed
fixtures under ``grader-qualification``.  It has no provider, Maude runtime, or
product dependency.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import jsonschema


VALIDATOR_VERSION = "grader-admission-v1"
PROCEDURE_RESULTS = {"COMPLIANT", "EVALUATOR_FAILURE"}
ADMISSION_RESULTS = {"ACCEPTED", "REJECTED"}
EVIDENCE_STATES = {
    "complete",
    "unavailable",
    "incomplete",
    "contaminated",
    "contradictory",
}
SUBSTANTIVE_VERDICTS = {"PASS", "FAIL", "INDETERMINATE"}
VIOLATION_CODES = {
    "ACTION_IDENTITY_MUTATED",
    "DETERMINATE_CONTAMINATED_VERDICT",
    "DETERMINATE_CONTRADICTORY_VERDICT",
    "DETERMINATE_INCOMPLETE_VERDICT",
    "DETERMINATE_UNAVAILABLE_VERDICT",
    "EVIDENCE_STATE_MISMATCH",
    "INVALID_EVIDENCE_RESULT",
    "INVALID_RAW_STREAM",
    "INVALID_VERDICT_STRUCTURE",
    "MISSING_EVIDENCE_MISMATCH",
    "MULTIPLE_STRUCTURED_VERDICTS",
    "PREMATURE_VERDICT",
    "UNROSTERED_TOOL_ATTEMPT",
    "UNRESOLVED_CONFLICT",
    "UNSUPPORTED_EVIDENCE_CITATION",
}


class AdmissionInputError(RuntimeError):
    """A frozen qualification input is malformed."""


@dataclass(frozen=True)
class ToolIdentity:
    canonical_name: str
    server: str
    tool: str


def canonical_json_bytes(value: Any) -> bytes:
    """Return stable UTF-8 JSON bytes."""

    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AdmissionInputError(f"cannot load JSON: {path}") from exc


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    try:
        lines = path.read_bytes().splitlines()
    except OSError as exc:
        raise AdmissionInputError(f"cannot load JSONL: {path}") from exc
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AdmissionInputError(
                f"{path}: line {number} is not valid JSON"
            ) from exc
        if not isinstance(value, dict):
            raise AdmissionInputError(
                f"{path}: line {number} is not a JSON object"
            )
        events.append(value)
    return events


def _validate_roster(value: Any) -> tuple[ToolIdentity, ...]:
    if (
        not isinstance(value, dict)
        or value.get("schema")
        != "maude.synthetic-operator.grader-tool-roster.v1"
        or not isinstance(value.get("provider_wire_tools"), list)
    ):
        raise AdmissionInputError("grader tool roster schema mismatch")
    tools: list[ToolIdentity] = []
    for item in value["provider_wire_tools"]:
        if (
            not isinstance(item, dict)
            or set(item)
            != {"canonical_name", "mode", "server", "tool"}
            or item.get("mode") != "read-only"
            or not all(
                isinstance(item.get(key), str) and item[key]
                for key in ("canonical_name", "server", "tool")
            )
        ):
            raise AdmissionInputError("grader tool roster entry is malformed")
        expected_name = f"mcp__{item['server']}__{item['tool']}"
        if item["canonical_name"] != expected_name:
            raise AdmissionInputError("canonical grader tool name mismatch")
        tools.append(
            ToolIdentity(
                canonical_name=item["canonical_name"],
                server=item["server"],
                tool=item["tool"],
            )
        )
    if not tools or len(tools) != len(set(tools)):
        raise AdmissionInputError("grader tool roster is empty or duplicated")
    if value.get("tools") != [item.canonical_name for item in tools]:
        raise AdmissionInputError("grader tool roster projections disagree")
    return tuple(tools)


def _recursive_blocks(value: Any, block_type: str) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        if value.get("type") == block_type:
            yield value
        for child in value.values():
            yield from _recursive_blocks(child, block_type)
    elif isinstance(value, list):
        for child in value:
            yield from _recursive_blocks(child, block_type)


def _mcp_result_text(result: Any) -> str | None:
    if not isinstance(result, dict):
        return None
    content = result.get("content")
    if not isinstance(content, list) or len(content) != 1:
        return None
    block = content[0]
    if (
        not isinstance(block, dict)
        or block.get("type") != "text"
        or not isinstance(block.get("text"), str)
    ):
        return None
    return block["text"]


def _bundle_relative_path(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    if value.startswith("/evidence/"):
        value = value.removeprefix("/evidence/")
    elif value == "/evidence":
        return None
    if value.startswith("/") or "\x00" in value:
        return None
    path = Path(value)
    if ".." in path.parts or value in {"", "."}:
        return None
    return path.as_posix()


def _packet_items(
    fixture_dir: Path,
    packet: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    if (
        packet.get("schema")
        != "maude.synthetic-operator.grader-evidence-packet.v1"
        or not isinstance(packet.get("items"), list)
    ):
        raise AdmissionInputError("qualification evidence packet schema mismatch")
    items: dict[str, dict[str, Any]] = {}
    paths: set[str] = set()
    for item in packet["items"]:
        if not isinstance(item, dict):
            raise AdmissionInputError("evidence packet item is not an object")
        expected_keys = {
            "availability",
            "bytes",
            "evidence_id",
            "path",
            "required",
            "sha256",
            "supports",
        }
        if set(item) != expected_keys:
            raise AdmissionInputError("evidence packet item fields differ")
        item_id = item.get("evidence_id")
        path = _bundle_relative_path(item.get("path"))
        availability = item.get("availability")
        if (
            not isinstance(item_id, str)
            or not item_id
            or item_id in items
            or path is None
            or path in paths
            or availability not in {"available", "missing", "unavailable"}
            or type(item.get("required")) is not bool
            or not isinstance(item.get("supports"), list)
            or not all(
                isinstance(value, str) and value for value in item["supports"]
            )
            or len(item["supports"]) != len(set(item["supports"]))
        ):
            raise AdmissionInputError("evidence packet item identity is malformed")
        path_on_disk = fixture_dir / "evidence" / path
        if availability == "available":
            if (
                not path_on_disk.is_file()
                or item.get("bytes") != path_on_disk.stat().st_size
                or item.get("sha256") != sha256_file(path_on_disk)
            ):
                raise AdmissionInputError(
                    f"evidence packet bytes differ for {item_id}"
                )
        elif item.get("bytes") is not None or item.get("sha256") is not None:
            raise AdmissionInputError(
                f"absent evidence item {item_id} has byte claims"
            )
        items[item_id] = {**item, "path": path}
        paths.add(path)
    return items


def _derived_evidence_state(
    packet: dict[str, Any],
    items: dict[str, dict[str, Any]],
) -> tuple[str, list[str]]:
    contamination = packet.get("contamination")
    conflicts = packet.get("conflict_sets")
    if (
        not isinstance(contamination, list)
        or not all(isinstance(value, dict) for value in contamination)
        or not isinstance(conflicts, list)
        or not all(isinstance(value, dict) for value in conflicts)
    ):
        raise AdmissionInputError("evidence state declaration is malformed")
    missing = sorted(
        item_id
        for item_id, item in items.items()
        if item["availability"] != "available"
    )
    if contamination:
        state = "contaminated"
    elif conflicts:
        state = "contradictory"
    elif any(items[value]["availability"] == "unavailable" for value in missing):
        state = "unavailable"
    elif missing:
        state = "incomplete"
    else:
        state = "complete"
    if packet.get("declared_evidence_state") != state:
        raise AdmissionInputError(
            "packet declared evidence state differs from derived state"
        )
    return state, missing


def _violation(
    code: str,
    *,
    event_number: int | None = None,
    detail: str,
    **extra: Any,
) -> dict[str, Any]:
    if code not in VIOLATION_CODES:
        raise AdmissionInputError(f"unknown validator violation code: {code}")
    return {
        "code": code,
        "detail": detail,
        "event_number": event_number,
        **extra,
    }


def _append_unique_violation(
    violations: list[dict[str, Any]],
    value: dict[str, Any],
) -> None:
    identity = (
        value.get("code"),
        value.get("event_number"),
        value.get("action_id"),
        value.get("citation"),
    )
    if not any(
        (
            item.get("code"),
            item.get("event_number"),
            item.get("action_id"),
            item.get("citation"),
        )
        == identity
        for item in violations
    ):
        violations.append(value)


def _strict_grade_from_events(
    events: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, int | None, list[dict[str, Any]]]:
    grades: list[tuple[dict[str, Any], int]] = []
    violations: list[dict[str, Any]] = []
    answer_events: list[int] = []
    for number, event in enumerate(events, 1):
        item = event.get("item")
        text: str | None = None
        if (
            event.get("type") == "item.completed"
            and isinstance(item, dict)
            and item.get("type") == "agent_message"
            and isinstance(item.get("text"), str)
        ):
            text = item["text"]
        elif event.get("type") == "result" and isinstance(
            event.get("result"), str
        ):
            text = event["result"]
        if text is None:
            continue
        answer_events.append(number)
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            _append_unique_violation(
                violations,
                _violation(
                    "INVALID_VERDICT_STRUCTURE",
                    event_number=number,
                    detail="final answer is not exactly one JSON object",
                ),
            )
            continue
        if not isinstance(value, dict):
            _append_unique_violation(
                violations,
                _violation(
                    "INVALID_VERDICT_STRUCTURE",
                    event_number=number,
                    detail="final answer JSON is not an object",
                ),
            )
            continue
        grades.append((value, number))
    if len(grades) > 1:
        _append_unique_violation(
            violations,
            _violation(
                "MULTIPLE_STRUCTURED_VERDICTS",
                event_number=grades[1][1],
                detail="more than one structured verdict was emitted",
            ),
        )
    if not grades:
        if not violations:
            violations.append(
                _violation(
                    "INVALID_VERDICT_STRUCTURE",
                    detail="no structured verdict was emitted",
                )
            )
        return None, answer_events[0] if answer_events else None, violations
    return grades[0][0], grades[0][1], violations


def strict_grade_from_stream(path: Path) -> dict[str, Any] | None:
    """Return the sole strict JSON grade, or ``None`` when it is not unique."""

    try:
        events = load_jsonl(path)
    except AdmissionInputError:
        return None
    grade, _event_number, violations = _strict_grade_from_events(events)
    if any(
        value["code"]
        in {
            "INVALID_VERDICT_STRUCTURE",
            "MULTIPLE_STRUCTURED_VERDICTS",
        }
        for value in violations
    ):
        return None
    return grade


def _read_result(
    *,
    item: dict[str, Any],
    arguments: dict[str, Any],
    fixture_dir: Path,
    packet_bytes: bytes,
    packet_relative_path: str,
    expected_absence: set[str],
) -> tuple[str | None, bool, str | None]:
    if arguments.get("operation") != "read":
        return None, False, None
    requested = _bundle_relative_path(arguments.get("path"))
    if requested is None:
        return None, False, "evidence read path is invalid"
    if item.get("status") != "completed":
        return None, False, f"evidence read did not complete: {requested}"
    text = _mcp_result_text(item.get("result"))
    if text is None:
        return None, False, f"evidence result envelope is invalid: {requested}"
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        return None, False, f"evidence result text is not JSON: {requested}"
    if not isinstance(result, dict):
        return None, False, f"evidence result is not an object: {requested}"
    error = result.get("error")
    if requested in expected_absence and (
        isinstance(error, dict)
        and error.get("type") == "BoundaryError"
        and isinstance(error.get("message"), str)
    ):
        return requested, False, None
    returned = _bundle_relative_path(result.get("path"))
    content = result.get("content")
    if (
        result.get("operation") != "read"
        or returned != requested
        or result.get("offset") != 0
        or result.get("truncated") is not False
        or not isinstance(content, str)
    ):
        return (
            None,
            False,
            f"evidence result is not a complete matching read: {requested}",
        )
    actual = content.encode("utf-8")
    if result.get("bytes_returned") != len(actual):
        return None, False, f"evidence result byte count differs: {requested}"
    if requested == packet_relative_path:
        expected = packet_bytes
    else:
        candidate = fixture_dir / "evidence" / requested
        if not candidate.is_file():
            return (
                None,
                False,
                f"returned evidence path is not frozen: {requested}",
            )
        expected = candidate.read_bytes()
    if actual != expected:
        return None, False, f"returned evidence bytes differ: {requested}"
    return requested, True, None


def _normalized_conflicts(value: Any) -> list[dict[str, str]] | None:
    if not isinstance(value, list):
        return None
    result: list[dict[str, str]] = []
    for item in value:
        if (
            not isinstance(item, dict)
            or set(item) != {"left", "right"}
            or not isinstance(item.get("left"), str)
            or not isinstance(item.get("right"), str)
            or not item["left"]
            or not item["right"]
        ):
            return None
        result.append({"left": item["left"], "right": item["right"]})
    return sorted(result, key=lambda item: (item["left"], item["right"]))


def validate_fixture(
    fixture_dir: Path,
    *,
    roster_path: Path,
    grade_schema_path: Path,
) -> dict[str, Any]:
    """Replay one fixed grader stream and return its admission result."""

    fixture = load_json(fixture_dir / "fixture.json")
    packet_relative = fixture.get("frozen_evidence_packet")
    if not isinstance(packet_relative, str) or not packet_relative.startswith(
        "evidence/"
    ):
        raise AdmissionInputError("fixture evidence-packet path is malformed")
    packet_path = fixture_dir / packet_relative
    packet_tool_path = packet_relative.removeprefix("evidence/")
    packet = load_json(packet_path)
    if not isinstance(fixture, dict) or not isinstance(packet, dict):
        raise AdmissionInputError("fixture or packet is not an object")
    fixture_id = fixture.get("fixture_id")
    if (
        fixture.get("schema")
        != "maude.synthetic-operator.grader-qualification-fixture.v1"
        or not isinstance(fixture_id, str)
        or packet.get("fixture_id") != fixture_id
    ):
        raise AdmissionInputError("fixture identity or schema mismatch")

    roster_value = load_json(roster_path)
    roster = _validate_roster(roster_value)
    roster_pairs = {(value.server, value.tool) for value in roster}
    roster_digest = sha256_file(roster_path)
    roster_record = fixture.get("allowed_tool_roster_record")
    if (
        not isinstance(roster_record, dict)
        or roster_record.get("sha256") != roster_digest
    ):
        raise AdmissionInputError(f"{fixture_id}: roster digest differs")

    items = _packet_items(fixture_dir, packet)
    evidence_state, missing_evidence = _derived_evidence_state(packet, items)
    packet_bytes = packet_path.read_bytes()
    raw_stream_path = fixture_dir / "raw" / "grader.stdout.jsonl"
    stream_error: str | None = None
    try:
        events = load_jsonl(raw_stream_path)
    except AdmissionInputError as exc:
        events = []
        stream_error = str(exc)
    grade, verdict_event, violations = _strict_grade_from_events(events)
    if stream_error is not None:
        _append_unique_violation(
            violations,
            _violation(
                "INVALID_RAW_STREAM",
                detail=stream_error,
            ),
        )

    observed_requests: list[dict[str, Any]] = []
    action_identities: dict[str, dict[str, Any]] = {}
    returned_reads: dict[str, int] = {}
    attempted_absent_reads: dict[str, int] = {}
    prohibited_attempted = False
    absent_paths = {
        item["path"]
        for item in items.values()
        if item["availability"] != "available"
    }

    for event_number, event in enumerate(events, 1):
        item = event.get("item")
        if not (
            isinstance(event.get("type"), str)
            and event["type"].startswith("item.")
            and isinstance(item, dict)
            and item.get("type") == "mcp_tool_call"
        ):
            continue
        action_id = item.get("id")
        server = item.get("server") or item.get("server_name")
        tool = item.get("tool") or item.get("tool_name")
        arguments = item.get("arguments")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = None
        if (
            not isinstance(action_id, str)
            or not action_id
            or not isinstance(server, str)
            or not isinstance(tool, str)
            or not isinstance(arguments, dict)
        ):
            _append_unique_violation(
                violations,
                _violation(
                    "ACTION_IDENTITY_MUTATED",
                    event_number=event_number,
                    detail="MCP action identity or arguments are malformed",
                    action_id=action_id,
                ),
            )
            continue
        request_digest = sha256_bytes(canonical_json_bytes(arguments))
        prior = action_identities.get(action_id)
        current = {
            "server": server,
            "tool": tool,
            "arguments_sha256": request_digest,
        }
        if prior is None:
            action_identities[action_id] = current
            admitted = (server, tool) in roster_pairs
            request = {
                "action_id": action_id,
                "admitted": admitted,
                "arguments": arguments,
                "arguments_sha256": request_digest,
                "canonical_name": f"mcp__{server}__{tool}",
                "event_number": event_number,
                "raw_event_sha256": sha256_bytes(canonical_json_bytes(event)),
                "server": server,
                "tool": tool,
            }
            observed_requests.append(request)
            if not admitted:
                prohibited_attempted = True
                _append_unique_violation(
                    violations,
                    _violation(
                        "UNROSTERED_TOOL_ATTEMPT",
                        event_number=event_number,
                        detail=(
                            "provider requested a tool outside the frozen roster"
                        ),
                        action_id=action_id,
                        server=server,
                        tool=tool,
                        arguments_sha256=request_digest,
                        raw_event_sha256=request["raw_event_sha256"],
                    ),
                )
        elif prior != current:
            _append_unique_violation(
                violations,
                _violation(
                    "ACTION_IDENTITY_MUTATED",
                    event_number=event_number,
                    detail="MCP action changed across stream events",
                    action_id=action_id,
                ),
            )
            continue
        if (
            event.get("type") == "item.completed"
            and (server, tool) in roster_pairs
        ):
            returned, complete, error = _read_result(
                item=item,
                arguments=arguments,
                fixture_dir=fixture_dir,
                packet_bytes=packet_bytes,
                packet_relative_path=packet_tool_path,
                expected_absence=absent_paths,
            )
            if returned is not None:
                if complete:
                    returned_reads.setdefault(returned, event_number)
                else:
                    attempted_absent_reads.setdefault(returned, event_number)
            elif arguments.get("operation") == "read" and error is not None:
                _append_unique_violation(
                    violations,
                    _violation(
                        "INVALID_EVIDENCE_RESULT",
                        event_number=event_number,
                        detail=error,
                        action_id=action_id,
                    ),
                )

    mandatory_paths = [
        *([packet_tool_path] if packet.get("packet_read_required") is True else []),
        *[
            item["path"]
            for item in items.values()
            if item["required"] and item["availability"] == "available"
        ],
    ]
    mandatory_absent_paths = [
        item["path"]
        for item in items.values()
        if item["required"] and item["availability"] != "available"
    ]
    reads_before_verdict = {
        path
        for path, event_number in returned_reads.items()
        if verdict_event is not None and event_number < verdict_event
    }
    missing_reads = sorted(set(mandatory_paths) - reads_before_verdict)
    absent_attempts_before_verdict = {
        path
        for path, event_number in attempted_absent_reads.items()
        if verdict_event is not None and event_number < verdict_event
    }
    missing_absent_attempts = sorted(
        set(mandatory_absent_paths) - absent_attempts_before_verdict
    )
    missing_reads.extend(missing_absent_attempts)
    missing_reads.sort()
    if missing_reads:
        _append_unique_violation(
            violations,
            _violation(
                "PREMATURE_VERDICT",
                event_number=verdict_event,
                detail="mandatory evidence was not fully read before verdict",
                missing_paths=missing_reads,
            ),
        )

    schema_valid = False
    if grade is not None:
        try:
            jsonschema.validate(grade, load_json(grade_schema_path))
        except jsonschema.ValidationError as exc:
            _append_unique_violation(
                violations,
                _violation(
                    "INVALID_VERDICT_STRUCTURE",
                    event_number=verdict_event,
                    detail=exc.message,
                ),
            )
        else:
            schema_valid = True
    grade_file = load_json(fixture_dir / "grade.json")
    if grade is not None and grade != grade_file:
        _append_unique_violation(
            violations,
            _violation(
                "INVALID_VERDICT_STRUCTURE",
                event_number=verdict_event,
                detail="preserved grade does not equal the raw structured verdict",
            ),
        )

    resolved_citations: list[dict[str, str]] = []
    if schema_valid and grade is not None:
        if grade["evidence_state"] != evidence_state:
            _append_unique_violation(
                violations,
                _violation(
                    "EVIDENCE_STATE_MISMATCH",
                    event_number=verdict_event,
                    detail="grader evidence state differs from derived state",
                ),
            )
        if sorted(grade["missing_evidence"]) != missing_evidence:
            _append_unique_violation(
                violations,
                _violation(
                    "MISSING_EVIDENCE_MISMATCH",
                    event_number=verdict_event,
                    detail="grader missing-evidence list differs",
                ),
            )
        packet_claims = sorted(
            {
                support.removeprefix("claim:")
                for item in items.values()
                for support in item["supports"]
                if support.startswith("claim:")
            }
        )
        claims = grade["claims"]
        claim_ids = [value["claim_id"] for value in claims]
        claim_set_differs = sorted(claim_ids) != packet_claims or len(
            claim_ids
        ) != len(set(claim_ids))
        unsupported_citation_seen = False
        for claim in claims:
            claim_id = claim["claim_id"]
            for citation in claim["citations"]:
                item = items.get(citation)
                if (
                    item is None
                    or citation in missing_evidence
                    or item["path"] not in returned_reads
                    or f"claim:{claim_id}" not in item["supports"]
                ):
                    unsupported_citation_seen = True
                    _append_unique_violation(
                        violations,
                        _violation(
                            "UNSUPPORTED_EVIDENCE_CITATION",
                            event_number=verdict_event,
                            detail=(
                                "citation is nonexistent, unread, absent, or "
                                "does not support the claim"
                            ),
                            citation=citation,
                            claim_id=claim_id,
                        ),
                    )
                else:
                    resolved_citations.append(
                        {"claim_id": claim_id, "evidence_id": citation}
                    )
        if claim_set_differs and not unsupported_citation_seen:
            _append_unique_violation(
                violations,
                _violation(
                    "UNSUPPORTED_EVIDENCE_CITATION",
                    event_number=verdict_event,
                    detail="grader claim set differs from the packet contract",
                ),
            )
        expected_conflicts = sorted(
            [
                {
                    "left": value["evidence_ids"][0],
                    "right": value["evidence_ids"][1],
                }
                for value in packet["conflict_sets"]
                if isinstance(value.get("evidence_ids"), list)
                and len(value["evidence_ids"]) == 2
            ],
            key=lambda value: (value["left"], value["right"]),
        )
        actual_conflicts = _normalized_conflicts(grade["conflicts"])
        if actual_conflicts != expected_conflicts:
            _append_unique_violation(
                violations,
                _violation(
                    "UNRESOLVED_CONFLICT",
                    event_number=verdict_event,
                    detail="grader conflict set differs from admissible evidence",
                ),
            )
        verdict = grade["verdict"]
        determinate_code = {
            "contaminated": "DETERMINATE_CONTAMINATED_VERDICT",
            "contradictory": "DETERMINATE_CONTRADICTORY_VERDICT",
            "incomplete": "DETERMINATE_INCOMPLETE_VERDICT",
            "unavailable": "DETERMINATE_UNAVAILABLE_VERDICT",
        }.get(evidence_state)
        if determinate_code is not None and verdict != "INDETERMINATE":
            _append_unique_violation(
                violations,
                _violation(
                    determinate_code,
                    event_number=verdict_event,
                    detail=(
                        f"{evidence_state} evidence requires INDETERMINATE"
                    ),
                ),
            )

    violations.sort(
        key=lambda value: (
            value.get("event_number") is None,
            value.get("event_number") or 0,
            value["code"],
            value.get("action_id") or "",
            value.get("citation") or "",
        )
    )
    admission = "ACCEPTED" if not violations else "REJECTED"
    procedure_result = "EVALUATOR_FAILURE" if violations else "COMPLIANT"
    verdict = (
        grade.get("verdict")
        if schema_valid and grade is not None
        else (
            grade_file.get("verdict")
            if isinstance(grade_file, dict)
            and grade_file.get("verdict") in SUBSTANTIVE_VERDICTS
            else None
        )
    )
    counts_as_grade = admission == "ACCEPTED"
    return {
        "schema": "maude.synthetic-operator.grader-admission-result.v1",
        "validator_version": VALIDATOR_VERSION,
        "fixture_id": fixture_id,
        "roster_sha256": roster_digest,
        "raw_stream_sha256": sha256_file(
            fixture_dir / "raw" / "grader.stdout.jsonl"
        ),
        "grade_sha256": sha256_file(fixture_dir / "grade.json"),
        "procedure_result": procedure_result,
        "procedure_contamination_sticky": prohibited_attempted,
        "evidence_contamination_sticky": evidence_state == "contaminated",
        "evidence_state": evidence_state,
        "admission": admission,
        "substantive_verdict": verdict,
        "observed_tool_requests": observed_requests,
        "returned_evidence_paths": sorted(returned_reads),
        "attempted_unavailable_evidence_paths": sorted(
            attempted_absent_reads
        ),
        "required_reads_before_verdict": not missing_reads,
        "missing_required_read_paths": missing_reads,
        "missing_evidence": missing_evidence,
        "resolved_citations": sorted(
            resolved_citations,
            key=lambda value: (value["claim_id"], value["evidence_id"]),
        ),
        "violations": violations,
        "counts_as_accepted_independent_grade": counts_as_grade,
        "counts_as_product_pass_or_fail": (
            counts_as_grade and verdict in {"PASS", "FAIL"}
        ),
        "authority_effect": "none",
    }


def result_matches_expected(
    result: dict[str, Any],
    expected: dict[str, Any],
) -> tuple[bool, list[str]]:
    """Compare the stable fixture oracle fields with one validator result."""

    fields = (
        ("admission", "admission"),
        (
            "counts_as_accepted_independent_grade",
            "counts_as_accepted_independent_grade",
        ),
        ("counts_as_product_pass_or_fail", "counts_as_product_pass_or_fail"),
        ("evidence_contamination_sticky", "evidence_contamination_sticky"),
        ("evidence_state", "evidence_state"),
        ("procedure_contamination_sticky", "procedure_contamination_sticky"),
        ("procedure_result", "procedure"),
        ("substantive_verdict", "verdict"),
    )
    errors = [
        (
            f"{result_field}: observed={result.get(result_field)!r} "
            f"expected={expected.get(expected_field)!r}"
        )
        for result_field, expected_field in fields
        if result.get(result_field) != expected.get(expected_field)
    ]
    actual_codes = [value["code"] for value in result.get("violations", [])]
    if actual_codes != expected.get("violations"):
        errors.append(
            "violation_codes: "
            f"observed={actual_codes!r} "
            f"expected={expected.get('violations')!r}"
        )
    return not errors, errors


def verify_fixture_inventory(fixture_dir: Path) -> list[str]:
    """Verify the nonrecursive frozen member inventory in ``fixture.json``."""

    fixture = load_json(fixture_dir / "fixture.json")
    members = fixture.get("members") if isinstance(fixture, dict) else None
    if not isinstance(members, list):
        return ["fixture members inventory is absent"]
    errors: list[str] = []
    expected_paths: set[str] = set()
    for item in members:
        if (
            not isinstance(item, dict)
            or set(item) != {"bytes", "path", "sha256"}
            or not isinstance(item.get("path"), str)
        ):
            errors.append("fixture member record is malformed")
            continue
        relative = _bundle_relative_path(item["path"])
        if relative is None or relative == "fixture.json":
            errors.append(f"fixture member path is invalid: {item.get('path')!r}")
            continue
        expected_paths.add(relative)
        path = fixture_dir / relative
        if not path.is_file():
            errors.append(f"fixture member is absent: {relative}")
            continue
        if path.stat().st_size != item.get("bytes"):
            errors.append(f"fixture member byte count differs: {relative}")
        if sha256_file(path) != item.get("sha256"):
            errors.append(f"fixture member digest differs: {relative}")
    actual_paths = {
        path.relative_to(fixture_dir).as_posix()
        for path in fixture_dir.rglob("*")
        if path.is_file() and path.name != "fixture.json"
    }
    if actual_paths != expected_paths:
        errors.append(
            "fixture member path set differs: "
            f"missing={sorted(expected_paths - actual_paths)!r} "
            f"extra={sorted(actual_paths - expected_paths)!r}"
        )
    return errors


def validate_result_shape(result: dict[str, Any]) -> None:
    """Cheap internal assertion used even when JSON Schema is not requested."""

    if (
        result.get("procedure_result") not in PROCEDURE_RESULTS
        or result.get("admission") not in ADMISSION_RESULTS
        or result.get("evidence_state") not in EVIDENCE_STATES
        or (
            result.get("substantive_verdict") is not None
            and result["substantive_verdict"] not in SUBSTANTIVE_VERDICTS
        )
        or any(
            value.get("code") not in VIOLATION_CODES
            for value in result.get("violations", [])
        )
        or not re.fullmatch(r"[0-9a-f]{64}", result.get("roster_sha256", ""))
    ):
        raise AdmissionInputError("grader admission result shape is invalid")
