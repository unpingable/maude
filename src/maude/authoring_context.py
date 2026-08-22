# SPDX-License-Identifier: Apache-2.0
"""Read-only Nightshift authoring-context provenance projection.

The canonical relation is minted and persisted by Nightshift at exact proposal
preparation.  Maude can only query and display it.  A relationship is lineage,
not currentness, standing, authorization, execution status, or permission.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

EXPORT_SCHEMA_V1 = "nightshift.authoring_context_export.v1"
PROVENANCE_SCHEMA_V1 = "nightshift.authoring_context_provenance.v1"
PRODUCER_COMPONENT_V1 = "nightshift.canonical_runtime"
MAX_OUTPUT_BYTES = 16 * 1024 * 1024


class AuthoringContextReadError(ValueError):
    """A canonical read command or exact typed response refused."""


@dataclass(frozen=True)
class GovernedHandoffV1:
    provenance_id: str
    plan_ref: str
    session_id: str
    campaign_id: str
    occurrence_id: str
    proposal_id: str
    exact_work_id: str
    source_intent_id: str
    recorded_at: str
    phosphor_ng_url: str | None


@dataclass(frozen=True)
class AuthoringContextLookupV1:
    """Tri-state owner read: unavailable, available-empty, or exact matches."""

    available: bool
    matches: tuple[GovernedHandoffV1, ...] = ()
    detail: str | None = None


def _is_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and value.startswith("sha256:")
        and len(value) == 71
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _validate_base_url(base_url: str) -> str:
    parsed = urlsplit(base_url)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise AuthoringContextReadError(
            "Phosphor-ng base URL must be credential-free loopback HTTP(S)"
        )
    path = parsed.path.rstrip("/")
    if path.endswith("/phosphor-ng"):
        path = path[: -len("/phosphor-ng")]
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", "")).rstrip("/")


def _phosphor_ng_url(
    base_url: str,
    campaign_id: str,
    occurrence_id: str,
    proposal_id: str,
) -> str:
    """Construct the v1 navigation-only semantic link from exact IDs."""

    for name, value in (
        ("campaign_id", campaign_id),
        ("proposal_id", proposal_id),
    ):
        if not _is_digest(value):
            raise AuthoringContextReadError(f"{name} is not a canonical digest")
    if not occurrence_id or any(character.isspace() for character in occurrence_id):
        raise AuthoringContextReadError("occurrence_id is not a canonical token")
    root = _validate_base_url(base_url)
    return (
        f"{root}/phosphor-ng/campaigns/{quote(campaign_id, safe='')}"
        f"/occurrences/{quote(occurrence_id, safe='')}"
        f"/proposals/{quote(proposal_id, safe='')}"
    )


def parse_export(
    payload: bytes,
    *,
    expected_plan_ref: str,
    expected_session_id: str,
    phosphor_base_url: str | None = None,
) -> tuple[GovernedHandoffV1, ...]:
    """Parse one exact owner response without inferring missing relations."""

    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuthoringContextReadError(f"malformed Nightshift JSON: {exc}") from exc
    if not isinstance(value, dict) or set(value) != {"schema", "query", "matches"}:
        raise AuthoringContextReadError(
            "Nightshift export has missing or unknown fields"
        )
    if value["schema"] != EXPORT_SCHEMA_V1:
        raise AuthoringContextReadError(
            "unsupported Nightshift authoring-context schema"
        )
    query = value["query"]
    if not isinstance(query, dict) or query != {
        "by": "maude_context",
        "plan_ref": expected_plan_ref,
        "session_id": expected_session_id,
    }:
        raise AuthoringContextReadError(
            "Nightshift export substituted the exact Maude query"
        )
    records = value["matches"]
    if not isinstance(records, list):
        raise AuthoringContextReadError("Nightshift export matches must be a list")

    result: list[GovernedHandoffV1] = []
    required = {
        "schema",
        "provenance_id",
        "producer_component",
        "maude_plan_ref",
        "maude_session_id",
        "source_plan_bytes",
        "campaign_id",
        "occurrence_id",
        "proposal_id",
        "exact_work_id",
        "source_intent_id",
        "recorded_at",
    }
    for record in records:
        if not isinstance(record, dict) or set(record) != required:
            raise AuthoringContextReadError("authoring-context record has field drift")
        if (
            record["schema"] != PROVENANCE_SCHEMA_V1
            or record["producer_component"] != PRODUCER_COMPONENT_V1
            or record["maude_plan_ref"] != expected_plan_ref
            or record["maude_session_id"] != expected_session_id
            or not isinstance(record["source_plan_bytes"], int)
            or record["source_plan_bytes"] <= 0
        ):
            raise AuthoringContextReadError(
                "authoring-context record identity mismatch"
            )
        for field in (
            "provenance_id",
            "maude_plan_ref",
            "campaign_id",
            "proposal_id",
            "exact_work_id",
            "source_intent_id",
        ):
            if not _is_digest(record[field]):
                raise AuthoringContextReadError(f"invalid authoring-context {field}")
        preimage = dict(record)
        provenance_id = preimage.pop("provenance_id")
        expected = "sha256:" + hashlib.sha256(_canonical_bytes(preimage)).hexdigest()
        if provenance_id != expected:
            raise AuthoringContextReadError("authoring-context self-digest mismatch")
        url = (
            _phosphor_ng_url(
                phosphor_base_url,
                record["campaign_id"],
                record["occurrence_id"],
                record["proposal_id"],
            )
            if phosphor_base_url
            else None
        )
        result.append(
            GovernedHandoffV1(
                provenance_id=provenance_id,
                plan_ref=record["maude_plan_ref"],
                session_id=record["maude_session_id"],
                campaign_id=record["campaign_id"],
                occurrence_id=record["occurrence_id"],
                proposal_id=record["proposal_id"],
                exact_work_id=record["exact_work_id"],
                source_intent_id=record["source_intent_id"],
                recorded_at=record["recorded_at"],
                phosphor_ng_url=url,
            )
        )
    return tuple(result)


class NightshiftAuthoringContextReaderV1:
    """Closed subprocess adapter for one demonstrably read-only owner verb."""

    def __init__(
        self,
        program: str,
        store: str,
        *,
        phosphor_base_url: str | None = None,
    ) -> None:
        executable = Path(program)
        if not executable.is_absolute() or executable.name != "nightshift":
            raise AuthoringContextReadError(
                "authoring-context reader requires the absolute canonical nightshift binary"
            )
        if not store:
            raise AuthoringContextReadError("Nightshift store coordinate is absent")
        self._program = str(executable)
        self._store = store
        self._phosphor_base_url = phosphor_base_url or None
        if self._phosphor_base_url:
            _validate_base_url(self._phosphor_base_url)

    async def lookup(self, plan_ref: str, session_id: str) -> AuthoringContextLookupV1:
        if (
            not _is_digest(plan_ref)
            or not session_id
            or any(character.isspace() for character in session_id)
        ):
            return AuthoringContextLookupV1(
                available=False,
                detail="exact plan/session identity is malformed",
            )
        process = await asyncio.create_subprocess_exec(
            self._program,
            "--store",
            self._store,
            "cycle",
            "export-authoring-context",
            "--plan-ref",
            plan_ref,
            "--maude-session-id",
            session_id,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=5)
        except TimeoutError:
            process.kill()
            await process.wait()
            return AuthoringContextLookupV1(
                available=False,
                detail="Nightshift authoring-context read timed out",
            )
        if len(stdout) > MAX_OUTPUT_BYTES:
            return AuthoringContextLookupV1(
                available=False,
                detail="Nightshift authoring-context output exceeded 16 MiB",
            )
        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace").strip()
            return AuthoringContextLookupV1(
                available=False,
                detail=f"Nightshift authoring-context read refused: {detail}",
            )
        try:
            matches = parse_export(
                stdout,
                expected_plan_ref=plan_ref,
                expected_session_id=session_id,
                phosphor_base_url=self._phosphor_base_url,
            )
        except AuthoringContextReadError as exc:
            return AuthoringContextLookupV1(available=False, detail=str(exc))
        return AuthoringContextLookupV1(available=True, matches=matches)
