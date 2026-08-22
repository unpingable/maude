# SPDX-License-Identifier: Apache-2.0
"""Exact, read-only Maude consumption of Nightshift handoff provenance."""

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from maude.authoring_context import (
    AuthoringContextReadError,
    EXPORT_SCHEMA_V1,
    NightshiftAuthoringContextReaderV1,
    PROVENANCE_SCHEMA_V1,
    parse_export,
)


def _digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _export(plan: bytes = b"exact plan", session: str = "sess_0123456789ab") -> dict:
    plan_ref = _digest(plan)
    record = {
        "schema": PROVENANCE_SCHEMA_V1,
        "provenance_id": "",
        "producer_component": "nightshift.canonical_runtime",
        "maude_plan_ref": plan_ref,
        "maude_session_id": session,
        "source_plan_bytes": len(plan),
        "campaign_id": _digest(b"campaign"),
        "occurrence_id": "00000000-0000-0000-0000-000000000001",
        "proposal_id": _digest(b"proposal"),
        "exact_work_id": _digest(b"work"),
        "source_intent_id": _digest(b"intent"),
        "recorded_at": "2026-08-21T12:00:00Z",
    }
    preimage = dict(record)
    preimage.pop("provenance_id")
    record["provenance_id"] = _digest(
        json.dumps(
            preimage, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    )
    return {
        "schema": EXPORT_SCHEMA_V1,
        "query": {
            "by": "maude_context",
            "plan_ref": plan_ref,
            "session_id": session,
        },
        "matches": [record],
    }


def _bytes(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode()


def test_exact_owner_record_builds_exact_phosphor_link():
    value = _export()
    matches = parse_export(
        _bytes(value),
        expected_plan_ref=value["query"]["plan_ref"],
        expected_session_id=value["query"]["session_id"],
        phosphor_base_url="http://127.0.0.1:8417/phosphor-ng",
    )
    assert len(matches) == 1
    assert matches[0].proposal_id == value["matches"][0]["proposal_id"]
    assert matches[0].phosphor_ng_url == (
        "http://127.0.0.1:8417/phosphor-ng/campaigns/"
        + value["matches"][0]["campaign_id"].replace(":", "%3A")
        + "/occurrences/00000000-0000-0000-0000-000000000001/proposals/"
        + value["matches"][0]["proposal_id"].replace(":", "%3A")
    )


def test_empty_owner_result_remains_unlinked():
    value = _export()
    value["matches"] = []
    assert (
        parse_export(
            _bytes(value),
            expected_plan_ref=value["query"]["plan_ref"],
            expected_session_id=value["query"]["session_id"],
        )
        == ()
    )


def test_malformed_or_unsupported_owner_projection_is_unavailable_not_linked():
    value = _export()
    with pytest.raises(AuthoringContextReadError, match="malformed"):
        parse_export(
            b"not-json",
            expected_plan_ref=value["query"]["plan_ref"],
            expected_session_id=value["query"]["session_id"],
        )
    value["schema"] = "nightshift.authoring_context_export.v2"
    with pytest.raises(AuthoringContextReadError, match="unsupported"):
        parse_export(
            _bytes(value),
            expected_plan_ref=value["query"]["plan_ref"],
            expected_session_id=value["query"]["session_id"],
        )


@pytest.mark.parametrize("field", ["maude_plan_ref", "maude_session_id"])
def test_plan_or_session_substitution_refuses(field):
    value = _export()
    value["matches"][0][field] = "substituted"
    with pytest.raises(AuthoringContextReadError):
        parse_export(
            _bytes(value),
            expected_plan_ref=value["query"]["plan_ref"],
            expected_session_id=value["query"]["session_id"],
        )


def test_self_digest_substitution_refuses():
    value = _export()
    value["matches"][0]["proposal_id"] = _digest(b"proposal-b")
    with pytest.raises(AuthoringContextReadError, match="self-digest"):
        parse_export(
            _bytes(value),
            expected_plan_ref=value["query"]["plan_ref"],
            expected_session_id=value["query"]["session_id"],
        )


def test_link_is_locator_only_and_rejects_credentials():
    value = _export()
    matches = parse_export(
        _bytes(value),
        expected_plan_ref=value["query"]["plan_ref"],
        expected_session_id=value["query"]["session_id"],
        phosphor_base_url="http://localhost:8417",
    )
    link = matches[0].phosphor_ng_url
    assert link is not None
    assert all(
        word not in link for word in ("authorization", "spend", "signature", "secret")
    )
    with pytest.raises(AuthoringContextReadError):
        parse_export(
            _bytes(value),
            expected_plan_ref=value["query"]["plan_ref"],
            expected_session_id=value["query"]["session_id"],
            phosphor_base_url="http://user:secret@localhost:8417",
        )


@pytest.mark.asyncio
async def test_reader_invokes_only_the_exact_owner_read_command(
    monkeypatch, tmp_path: Path
):
    value = _export()
    captured: tuple[object, ...] = ()

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            return _bytes(value), b""

    async def fake_create_subprocess_exec(*args, **kwargs):
        nonlocal captured
        captured = args
        assert kwargs == {
            "stdin": asyncio.subprocess.DEVNULL,
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
        }
        return FakeProcess()

    monkeypatch.setattr(
        "maude.authoring_context.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )
    reader = NightshiftAuthoringContextReaderV1(
        "/opt/nightshift",
        str(tmp_path / "nightshift.sqlite"),
        phosphor_base_url="http://127.0.0.1:8417",
    )
    lookup = await reader.lookup(
        value["query"]["plan_ref"], value["query"]["session_id"]
    )

    assert lookup.available
    assert len(lookup.matches) == 1
    assert captured == (
        "/opt/nightshift",
        "--store",
        str(tmp_path / "nightshift.sqlite"),
        "cycle",
        "export-authoring-context",
        "--plan-ref",
        value["query"]["plan_ref"],
        "--maude-session-id",
        value["query"]["session_id"],
    )
