# SPDX-License-Identifier: Apache-2.0
"""Closed post-settlement acquisition orchestration for local Compose.

This module owns mechanics only: it derives one exact trigger from Docket's
settled read model, durably records one logical acquisition, invokes the
qualified Maude adapter, and delivers its exact handoff to Nightshift.  It
does not construct currentness, adequacy, standing, authorization, Docket
work, or a recurring monitor.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import stat
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Protocol

from maude.custody import _read_exact_file, read_protected_key
from maude.plan.cross_probe import parse_cross_probe
from maude.plan.document import canonical_json_bytes, content_digest
from maude.plan.world_observation import (
    MAX_INPUT_BYTES,
    build_observation,
    seal_handoff,
)
from maude.plan.steady_state_observation import (
    HANDOFF_SCHEMA_V1 as STEADY_HANDOFF_SCHEMA_V1,
    LocalComposePassiveProbe,
    PassiveProbe,
    acquire_handoff as acquire_steady_state_handoff,
)

TRIGGER_SCHEMA_V1 = "maude.external-evidence-acquisition-trigger/v1"
REQUEST_SCHEMA_V1 = "maude.external-evidence-acquisition-request/v1"
EVENT_SCHEMA_V1 = "maude.external-evidence-acquisition-event/v1"
EXPORT_SCHEMA_V1 = "maude.external-evidence-acquisition-export/v1"
HISTORY_SCHEMA_V1 = "maude.external-evidence-acquisition-history/v1"
STORE_SCHEMA_V1 = "maude.external-evidence-acquisition-store/v1"
DOCKET_INSPECTION_SCHEMA_V1 = "docket.governed-loop.inspection/v1"
EXTERNAL_PROFILE_SCHEMA_V1 = "nightshift.external_evidence_profile.v1"
COMPILATION_SCHEMA_V1 = "maude.plan-compilation-receipt/v1"
LOCAL_COMPOSE_PLAN_SCHEMA_V1 = "maude.local-compose.docket-executor-plan/v1"
LOCAL_COMPOSE_WORK_SCHEMA_V1 = "maude.local-compose-workflow/v1"
LOCAL_COMPOSE_COMPILER_ID = "maude.local-compose-workflow"
LOCAL_COMPOSE_ADAPTER_ID = "maude.local-compose-observation-adapter"
LOCAL_COMPOSE_ADAPTER_VERSION = "1"
LOCAL_COMPOSE_STEADY_ADAPTER_ID = "maude.local-compose-steady-state-observation-adapter"
LOCAL_COMPOSE_STEADY_ADAPTER_VERSION = "1"
STEADY_PROFILE_SCHEMA_V1 = "nightshift.steady_state_evidence_profile.v1"
STEADY_BASIS_SCHEMA_V1 = "nightshift.steady_state_reobservation_basis.v1"
MAX_COMMAND_OUTPUT = 16 * 1024 * 1024
MAX_ADAPTER_INVOCATIONS = 2


class AcquisitionError(ValueError):
    """Fail-closed contract, persistence, adapter, or custody refusal."""


class AcquisitionConflict(AcquisitionError):
    """An exact identity is already bound to different content."""


class CustodyRefused(AcquisitionError):
    """Nightshift definitively refused the exact handoff."""


class CustodyOutcomeUnknown(AcquisitionError):
    """The handoff may have reached durable Nightshift custody."""


class AcquisitionReason(str, Enum):
    POST_SETTLEMENT = "post_settlement"
    REOBSERVE_FOR_SUCCESSOR = "reobserve_for_successor"
    REOBSERVE_AFTER_STALE = "reobserve_after_stale"


class AcquisitionEventKind(str, Enum):
    TRIGGER_RECORDED = "trigger_recorded"
    ACQUISITION_SCHEDULED = "acquisition_scheduled"
    ADAPTER_INVOCATION_STARTED = "adapter_invocation_started"
    ADAPTER_RETURNED_EVIDENCE = "adapter_returned_evidence"
    ADAPTER_FAILED = "adapter_failed"
    CUSTODY_ACCEPTED = "custody_accepted"
    CUSTODY_REFUSED = "custody_refused"
    CUSTODY_OUTCOME_UNKNOWN = "custody_outcome_unknown"
    REOBSERVATION_REFUSED = "reobservation_refused"


def _now() -> datetime:
    return datetime.now(UTC)


def _utc(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() != datetime.resolution * 0:
        raise AcquisitionError("event time must be timezone-aware UTC")
    return value.isoformat().replace("+00:00", "Z")


def _timestamp_from_ms(value: int) -> str:
    if not isinstance(value, int) or value < 0:
        raise AcquisitionError("canonical time must be non-negative Unix milliseconds")
    timestamp = datetime.fromtimestamp(value / 1000, UTC)
    timespec = "seconds" if value % 1000 == 0 else "milliseconds"
    return timestamp.isoformat(timespec=timespec).replace("+00:00", "Z")


def _digest(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 71
        or not value.startswith("sha256:")
    ):
        raise AcquisitionError(f"{name} must use sha256:<64 lowercase hex>")
    if any(character not in "0123456789abcdef" for character in value[7:]):
        raise AcquisitionError(f"{name} must use sha256:<64 lowercase hex>")
    return value


def _token(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise AcquisitionError(f"{name} must be a non-empty token")
    if any(character.isspace() for character in value):
        raise AcquisitionError(f"{name} must be a non-empty token")
    return value


def _closed(value: object, fields: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise AcquisitionError(f"{name} has unknown or missing fields")
    return value


def _record_id(value: dict[str, Any], identity: str) -> str:
    unsigned = dict(value)
    unsigned.pop(identity, None)
    return content_digest(canonical_json_bytes(unsigned))


def _strict_json_bytes(raw: bytes, name: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AcquisitionError(f"malformed {name}") from error
    if not isinstance(value, dict) or canonical_json_bytes(value) != raw:
        raise AcquisitionError(f"{name} must be exact canonical JSON")
    return value


def _owner_json_bytes(raw: bytes, name: str) -> dict[str, Any]:
    """Parse one exact owner response without pretending its wire is JCS."""
    try:
        text = raw.decode("utf-8")
        decoder = json.JSONDecoder()
        value, end = decoder.raw_decode(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AcquisitionError(f"malformed {name}") from error
    if not isinstance(value, dict) or text[end:].strip():
        raise AcquisitionError(f"{name} must contain exactly one JSON object")
    return value


@dataclass(frozen=True)
class AcquisitionTriggerV1:
    trigger_id: str
    reason: AcquisitionReason
    campaign_id: str
    occurrence_id: str
    proposal_id: str
    exact_work_id: str
    issuance_id: str
    attempt_id: str
    settlement_id: str
    settlement_receipt_id: str
    settled_at_unix_ms: int
    plan_document_digest: str
    compilation_id: str
    compiler_id: str
    compiler_version: str
    workflow_schema: str
    adapter_id: str
    adapter_version: str
    external_evidence_profile_id: str
    subject_digest: str
    scope_digest: str
    target_runtime_id: str
    source_observation_id: str | None = None
    currentness_basis_digest: str | None = None
    basis_evaluated_at_unix_ms: int | None = None
    target_occurrence_id: str | None = None
    schema: str = TRIGGER_SCHEMA_V1

    def unsigned_data(self) -> dict[str, Any]:
        return {
            "adapter_id": self.adapter_id,
            "adapter_version": self.adapter_version,
            "attempt_id": self.attempt_id,
            "basis_evaluated_at_unix_ms": self.basis_evaluated_at_unix_ms,
            "campaign_id": self.campaign_id,
            "compilation_id": self.compilation_id,
            "compiler_id": self.compiler_id,
            "compiler_version": self.compiler_version,
            "currentness_basis_digest": self.currentness_basis_digest,
            "exact_work_id": self.exact_work_id,
            "external_evidence_profile_id": self.external_evidence_profile_id,
            "issuance_id": self.issuance_id,
            "occurrence_id": self.occurrence_id,
            "plan_document_digest": self.plan_document_digest,
            "proposal_id": self.proposal_id,
            "reason": self.reason.value,
            "schema": self.schema,
            "scope_digest": self.scope_digest,
            "settled_at_unix_ms": self.settled_at_unix_ms,
            "settlement_id": self.settlement_id,
            "settlement_receipt_id": self.settlement_receipt_id,
            "source_observation_id": self.source_observation_id,
            "subject_digest": self.subject_digest,
            "target_occurrence_id": self.target_occurrence_id,
            "target_runtime_id": self.target_runtime_id,
            "workflow_schema": self.workflow_schema,
        }

    def to_data(self) -> dict[str, Any]:
        return {**self.unsigned_data(), "trigger_id": self.trigger_id}

    @classmethod
    def from_data(cls, value: dict[str, Any]) -> "AcquisitionTriggerV1":
        expected = {
            "adapter_id",
            "adapter_version",
            "attempt_id",
            "basis_evaluated_at_unix_ms",
            "campaign_id",
            "compilation_id",
            "compiler_id",
            "compiler_version",
            "currentness_basis_digest",
            "exact_work_id",
            "external_evidence_profile_id",
            "issuance_id",
            "occurrence_id",
            "plan_document_digest",
            "proposal_id",
            "reason",
            "schema",
            "scope_digest",
            "settled_at_unix_ms",
            "settlement_id",
            "settlement_receipt_id",
            "source_observation_id",
            "subject_digest",
            "target_occurrence_id",
            "target_runtime_id",
            "trigger_id",
            "workflow_schema",
        }
        if set(value) != expected or value.get("schema") != TRIGGER_SCHEMA_V1:
            raise AcquisitionError("unsupported acquisition trigger shape")
        try:
            trigger = cls(
                trigger_id=value["trigger_id"],
                reason=AcquisitionReason(value["reason"]),
                campaign_id=value["campaign_id"],
                occurrence_id=value["occurrence_id"],
                proposal_id=value["proposal_id"],
                exact_work_id=value["exact_work_id"],
                issuance_id=value["issuance_id"],
                attempt_id=value["attempt_id"],
                settlement_id=value["settlement_id"],
                settlement_receipt_id=value["settlement_receipt_id"],
                settled_at_unix_ms=value["settled_at_unix_ms"],
                plan_document_digest=value["plan_document_digest"],
                compilation_id=value["compilation_id"],
                compiler_id=value["compiler_id"],
                compiler_version=value["compiler_version"],
                workflow_schema=value["workflow_schema"],
                adapter_id=value["adapter_id"],
                adapter_version=value["adapter_version"],
                external_evidence_profile_id=value["external_evidence_profile_id"],
                subject_digest=value["subject_digest"],
                scope_digest=value["scope_digest"],
                target_runtime_id=value["target_runtime_id"],
                source_observation_id=value["source_observation_id"],
                currentness_basis_digest=value["currentness_basis_digest"],
                basis_evaluated_at_unix_ms=value["basis_evaluated_at_unix_ms"],
                target_occurrence_id=value["target_occurrence_id"],
            )
        except (KeyError, TypeError, ValueError) as error:
            raise AcquisitionError("malformed acquisition trigger") from error
        trigger.validate()
        return trigger

    def validate(self) -> None:
        for name, value in (
            ("trigger_id", self.trigger_id),
            ("campaign_id", self.campaign_id),
            ("proposal_id", self.proposal_id),
            ("exact_work_id", self.exact_work_id),
            ("issuance_id", self.issuance_id),
            ("attempt_id", self.attempt_id),
            ("settlement_id", self.settlement_id),
            ("settlement_receipt_id", self.settlement_receipt_id),
            ("plan_document_digest", self.plan_document_digest),
            ("compilation_id", self.compilation_id),
            ("external_evidence_profile_id", self.external_evidence_profile_id),
            ("subject_digest", self.subject_digest),
            ("scope_digest", self.scope_digest),
        ):
            _digest(value, name)
        for name, value in (
            ("occurrence_id", self.occurrence_id),
            ("compiler_id", self.compiler_id),
            ("compiler_version", self.compiler_version),
            ("workflow_schema", self.workflow_schema),
            ("adapter_id", self.adapter_id),
            ("adapter_version", self.adapter_version),
            ("target_runtime_id", self.target_runtime_id),
        ):
            _token(value, name)
        if not isinstance(self.settled_at_unix_ms, int) or self.settled_at_unix_ms < 0:
            raise AcquisitionError("settled_at_unix_ms must be non-negative")
        if (
            self.workflow_schema != LOCAL_COMPOSE_WORK_SCHEMA_V1
            or self.compiler_id != LOCAL_COMPOSE_COMPILER_ID
            or self.compiler_version != "1"
            or (
                self.reason == AcquisitionReason.POST_SETTLEMENT
                and (
                    self.adapter_id != LOCAL_COMPOSE_ADAPTER_ID
                    or self.adapter_version != LOCAL_COMPOSE_ADAPTER_VERSION
                )
            )
            or (
                self.reason != AcquisitionReason.POST_SETTLEMENT
                and (
                    self.adapter_id != LOCAL_COMPOSE_STEADY_ADAPTER_ID
                    or self.adapter_version != LOCAL_COMPOSE_STEADY_ADAPTER_VERSION
                )
            )
        ):
            raise AcquisitionError(
                "workflow/compiler/adapter is not in the closed v1 registry"
            )
        if self.reason == AcquisitionReason.POST_SETTLEMENT:
            if any(
                value is not None
                for value in (
                    self.source_observation_id,
                    self.currentness_basis_digest,
                    self.basis_evaluated_at_unix_ms,
                    self.target_occurrence_id,
                )
            ):
                raise AcquisitionError(
                    "post-settlement trigger cannot carry re-observation basis"
                )
        elif self.reason in {
            AcquisitionReason.REOBSERVE_FOR_SUCCESSOR,
            AcquisitionReason.REOBSERVE_AFTER_STALE,
        }:
            if (
                self.currentness_basis_digest is None
                or self.basis_evaluated_at_unix_ms is None
            ):
                raise AcquisitionError(
                    "re-observation trigger requires exact owner-produced basis"
                )
            if self.reason == AcquisitionReason.REOBSERVE_AFTER_STALE:
                _digest(self.source_observation_id, "source_observation_id")
            elif self.source_observation_id is not None:
                raise AcquisitionError(
                    "initial successor observation cannot name prior passive evidence"
                )
            _digest(self.currentness_basis_digest, "currentness_basis_digest")
            if (
                not isinstance(self.basis_evaluated_at_unix_ms, int)
                or self.basis_evaluated_at_unix_ms < 0
            ):
                raise AcquisitionError(
                    "basis_evaluated_at_unix_ms must be non-negative"
                )
        if self.trigger_id != _record_id(self.to_data(), "trigger_id"):
            raise AcquisitionError("acquisition trigger identity mismatch")


@dataclass(frozen=True)
class AcquisitionRequestV1:
    request_id: str
    trigger_id: str
    reason: AcquisitionReason
    adapter_id: str
    adapter_version: str
    target_runtime_id: str
    not_before_unix_ms: int
    deadline_unix_ms: int | None
    schema: str = REQUEST_SCHEMA_V1

    def unsigned_data(self) -> dict[str, Any]:
        return {
            "adapter_id": self.adapter_id,
            "adapter_version": self.adapter_version,
            "deadline_unix_ms": self.deadline_unix_ms,
            "not_before_unix_ms": self.not_before_unix_ms,
            "reason": self.reason.value,
            "schema": self.schema,
            "target_runtime_id": self.target_runtime_id,
            "trigger_id": self.trigger_id,
        }

    def to_data(self) -> dict[str, Any]:
        return {**self.unsigned_data(), "request_id": self.request_id}

    @classmethod
    def create(cls, trigger: AcquisitionTriggerV1) -> "AcquisitionRequestV1":
        not_before_unix_ms = (
            trigger.settled_at_unix_ms
            if trigger.reason == AcquisitionReason.POST_SETTLEMENT
            else trigger.basis_evaluated_at_unix_ms
        )
        if not_before_unix_ms is None:
            raise AcquisitionError("re-observation request lacks exact basis time")
        unsigned = {
            "adapter_id": trigger.adapter_id,
            "adapter_version": trigger.adapter_version,
            "deadline_unix_ms": None,
            "not_before_unix_ms": not_before_unix_ms,
            "reason": trigger.reason.value,
            "schema": REQUEST_SCHEMA_V1,
            "target_runtime_id": trigger.target_runtime_id,
            "trigger_id": trigger.trigger_id,
        }
        return cls(
            _record_id(unsigned, "request_id"),
            trigger.trigger_id,
            trigger.reason,
            trigger.adapter_id,
            trigger.adapter_version,
            trigger.target_runtime_id,
            not_before_unix_ms,
            None,
        )

    @classmethod
    def from_data(cls, value: dict[str, Any]) -> "AcquisitionRequestV1":
        expected = {
            "adapter_id",
            "adapter_version",
            "deadline_unix_ms",
            "not_before_unix_ms",
            "reason",
            "request_id",
            "schema",
            "target_runtime_id",
            "trigger_id",
        }
        if set(value) != expected or value.get("schema") != REQUEST_SCHEMA_V1:
            raise AcquisitionError("unsupported acquisition request shape")
        try:
            request = cls(
                value["request_id"],
                value["trigger_id"],
                AcquisitionReason(value["reason"]),
                value["adapter_id"],
                value["adapter_version"],
                value["target_runtime_id"],
                value["not_before_unix_ms"],
                value["deadline_unix_ms"],
            )
        except (TypeError, ValueError) as error:
            raise AcquisitionError("malformed acquisition request") from error
        request.validate()
        return request

    def validate(self) -> None:
        _digest(self.request_id, "request_id")
        _digest(self.trigger_id, "trigger_id")
        _token(self.adapter_id, "adapter_id")
        _token(self.adapter_version, "adapter_version")
        _token(self.target_runtime_id, "target_runtime_id")
        if not isinstance(self.not_before_unix_ms, int) or self.not_before_unix_ms < 0:
            raise AcquisitionError("not_before_unix_ms must be non-negative")
        if self.deadline_unix_ms is not None and (
            not isinstance(self.deadline_unix_ms, int)
            or self.deadline_unix_ms <= self.not_before_unix_ms
        ):
            raise AcquisitionError("deadline_unix_ms must follow not_before_unix_ms")
        if self.request_id != _record_id(self.to_data(), "request_id"):
            raise AcquisitionError("acquisition request identity mismatch")


@dataclass(frozen=True)
class AcquisitionEventV1:
    event_id: str
    request_id: str
    sequence: int
    kind: AcquisitionEventKind
    recorded_at: str
    invocation: int | None = None
    observation_id: str | None = None
    handoff_id: str | None = None
    custody_id: str | None = None
    observed_at_unix_ms: int | None = None
    reason: str | None = None
    error_digest: str | None = None
    schema: str = EVENT_SCHEMA_V1

    def unsigned_data(self) -> dict[str, Any]:
        return {
            "custody_id": self.custody_id,
            "error_digest": self.error_digest,
            "handoff_id": self.handoff_id,
            "invocation": self.invocation,
            "kind": self.kind.value,
            "observation_id": self.observation_id,
            "observed_at_unix_ms": self.observed_at_unix_ms,
            "reason": self.reason,
            "recorded_at": self.recorded_at,
            "request_id": self.request_id,
            "schema": self.schema,
            "sequence": self.sequence,
        }

    def to_data(self) -> dict[str, Any]:
        return {**self.unsigned_data(), "event_id": self.event_id}

    @classmethod
    def create(
        cls,
        *,
        request_id: str,
        sequence: int,
        kind: AcquisitionEventKind,
        recorded_at: str,
        invocation: int | None = None,
        observation_id: str | None = None,
        handoff_id: str | None = None,
        custody_id: str | None = None,
        observed_at_unix_ms: int | None = None,
        reason: str | None = None,
        error_digest: str | None = None,
    ) -> "AcquisitionEventV1":
        candidate = cls(
            "",
            request_id,
            sequence,
            kind,
            recorded_at,
            invocation,
            observation_id,
            handoff_id,
            custody_id,
            observed_at_unix_ms,
            reason,
            error_digest,
        )
        return cls(
            _record_id(candidate.to_data(), "event_id"),
            request_id,
            sequence,
            kind,
            recorded_at,
            invocation,
            observation_id,
            handoff_id,
            custody_id,
            observed_at_unix_ms,
            reason,
            error_digest,
        )

    @classmethod
    def from_data(cls, value: dict[str, Any]) -> "AcquisitionEventV1":
        expected = set(
            cls("", "", 0, AcquisitionEventKind.TRIGGER_RECORDED, "").to_data()
        )
        if set(value) != expected or value.get("schema") != EVENT_SCHEMA_V1:
            raise AcquisitionError("unsupported acquisition event shape")
        try:
            event = cls(
                value["event_id"],
                value["request_id"],
                value["sequence"],
                AcquisitionEventKind(value["kind"]),
                value["recorded_at"],
                value["invocation"],
                value["observation_id"],
                value["handoff_id"],
                value["custody_id"],
                value["observed_at_unix_ms"],
                value["reason"],
                value["error_digest"],
            )
        except (KeyError, TypeError, ValueError) as error:
            raise AcquisitionError("malformed acquisition event") from error
        event.validate()
        return event

    def validate(self) -> None:
        _digest(self.event_id, "event_id")
        _digest(self.request_id, "request_id")
        if not isinstance(self.sequence, int) or self.sequence < 1:
            raise AcquisitionError("event sequence must be positive")
        if not isinstance(self.recorded_at, str) or not self.recorded_at.endswith("Z"):
            raise AcquisitionError("event time must be RFC3339 UTC")
        try:
            datetime.fromisoformat(self.recorded_at.removesuffix("Z") + "+00:00")
        except ValueError as error:
            raise AcquisitionError("event time must be RFC3339 UTC") from error
        if self.invocation is not None and (
            not isinstance(self.invocation, int) or self.invocation < 1
        ):
            raise AcquisitionError("event invocation must be positive")
        if self.observed_at_unix_ms is not None and (
            not isinstance(self.observed_at_unix_ms, int)
            or self.observed_at_unix_ms < 0
        ):
            raise AcquisitionError("event evidence time must be non-negative")
        if self.reason is not None and (
            not isinstance(self.reason, str) or not 1 <= len(self.reason) <= 2048
        ):
            raise AcquisitionError("event reason must be bounded text")
        for name, value in (
            ("observation_id", self.observation_id),
            ("handoff_id", self.handoff_id),
            ("custody_id", self.custody_id),
            ("error_digest", self.error_digest),
        ):
            if value is not None:
                _digest(value, name)
        if self.kind == AcquisitionEventKind.ADAPTER_INVOCATION_STARTED and (
            self.invocation is None
            or any(
                value is not None
                for value in (
                    self.observation_id,
                    self.handoff_id,
                    self.custody_id,
                    self.observed_at_unix_ms,
                    self.reason,
                    self.error_digest,
                )
            )
        ):
            raise AcquisitionError("adapter-start event has contradictory facts")
        if self.kind == AcquisitionEventKind.ADAPTER_RETURNED_EVIDENCE and (
            self.observation_id is None
            or self.handoff_id is None
            or self.observed_at_unix_ms is None
            or self.invocation is not None
            or self.custody_id is not None
            or self.reason is not None
            or self.error_digest is not None
        ):
            raise AcquisitionError("adapter-return event lacks exact evidence facts")
        if self.kind == AcquisitionEventKind.CUSTODY_ACCEPTED and (
            self.observation_id is None
            or self.handoff_id is None
            or self.custody_id is None
            or self.invocation is not None
            or self.observed_at_unix_ms is not None
            or self.reason is not None
            or self.error_digest is not None
        ):
            raise AcquisitionError("custody-accepted event lacks exact custody facts")
        optional = (
            self.invocation,
            self.observation_id,
            self.handoff_id,
            self.custody_id,
            self.observed_at_unix_ms,
            self.reason,
            self.error_digest,
        )
        if self.kind in {
            AcquisitionEventKind.TRIGGER_RECORDED,
            AcquisitionEventKind.ACQUISITION_SCHEDULED,
        } and any(value is not None for value in optional):
            raise AcquisitionError("trigger/schedule event carries outcome facts")
        if self.kind == AcquisitionEventKind.ADAPTER_FAILED and (
            self.reason is None
            or self.error_digest is None
            or any(
                value is not None
                for value in (
                    self.invocation,
                    self.observation_id,
                    self.handoff_id,
                    self.custody_id,
                    self.observed_at_unix_ms,
                )
            )
        ):
            raise AcquisitionError("adapter-failure event has contradictory facts")
        if self.kind in {
            AcquisitionEventKind.CUSTODY_REFUSED,
            AcquisitionEventKind.CUSTODY_OUTCOME_UNKNOWN,
        } and (
            self.reason is None
            or self.error_digest is None
            or any(
                value is not None
                for value in (
                    self.invocation,
                    self.observation_id,
                    self.handoff_id,
                    self.custody_id,
                    self.observed_at_unix_ms,
                )
            )
        ):
            raise AcquisitionError("custody-outcome event has contradictory facts")
        if self.kind == AcquisitionEventKind.REOBSERVATION_REFUSED and (
            self.reason is None
            or any(
                value is not None
                for value in (
                    self.invocation,
                    self.observation_id,
                    self.handoff_id,
                    self.custody_id,
                    self.observed_at_unix_ms,
                    self.error_digest,
                )
            )
        ):
            raise AcquisitionError("re-observation refusal has contradictory facts")
        if self.event_id != _record_id(self.to_data(), "event_id"):
            raise AcquisitionError("acquisition event identity mismatch")


@dataclass(frozen=True)
class AcquisitionSourcesV1:
    docket_inspection: bytes
    executor_evidence: bytes
    executor_plan: bytes
    compilation_receipt: bytes
    governed_bindings: bytes
    external_profile: bytes
    reobservation_basis: bytes | None = None


def _validate_sources_for_trigger(
    trigger: AcquisitionTriggerV1, sources: AcquisitionSourcesV1
) -> None:
    values = [_owner_json_bytes(sources.docket_inspection, "Docket inspection")]
    values.extend(
        _strict_json_bytes(raw, name)
        for raw, name in (
            (sources.executor_evidence, "executor evidence"),
            (sources.executor_plan, "executor plan"),
            (sources.compilation_receipt, "compilation receipt"),
            (sources.governed_bindings, "governed bindings"),
            (sources.external_profile, "external profile"),
        )
    )
    if trigger.reason == AcquisitionReason.POST_SETTLEMENT:
        if sources.reobservation_basis is not None:
            raise AcquisitionError(
                "post-settlement source cannot carry re-observation basis"
            )
        rebuilt = build_post_settlement_trigger(
            docket_inspection=values[0],
            executor_plan=values[2],
            compilation_receipt=values[3],
            governed_bindings=values[4],
            external_profile=values[5],
            target_runtime_id=trigger.target_runtime_id,
        )
    else:
        if sources.reobservation_basis is None:
            raise AcquisitionError("passive acquisition lacks owner-produced basis")
        basis = _strict_json_bytes(
            sources.reobservation_basis, "steady-state re-observation basis"
        )
        rebuilt = build_reobserve_after_stale_trigger(
            docket_inspection=values[0],
            executor_plan=values[2],
            compilation_receipt=values[3],
            governed_bindings=values[4],
            steady_profile=values[5],
            reobservation_basis=basis,
            target_runtime_id=trigger.target_runtime_id,
            reason=trigger.reason,
        )
    if rebuilt != trigger:
        raise AcquisitionError("source bundle does not reproduce acquisition trigger")


def build_post_settlement_trigger(
    *,
    docket_inspection: dict[str, Any],
    executor_plan: dict[str, Any],
    compilation_receipt: dict[str, Any],
    governed_bindings: dict[str, Any],
    external_profile: dict[str, Any],
    target_runtime_id: str,
) -> AcquisitionTriggerV1:
    """Derive one trigger from Docket's exact settled owner projection."""
    if docket_inspection.get("schema") != DOCKET_INSPECTION_SCHEMA_V1:
        raise AcquisitionError("unsupported Docket inspection schema")
    if docket_inspection.get("requested_issuance") is None:
        raise AcquisitionError("Docket inspection lacks exact issuance query")
    record = docket_inspection.get("record")
    if not isinstance(record, dict) or record.get("status") != "settled":
        raise AcquisitionError(
            "post-settlement acquisition requires exact Docket settlement"
        )
    issuance = record.get("issuance")
    custody = record.get("custody")
    settlement = record.get("settlement")
    if not all(isinstance(item, dict) for item in (issuance, custody, settlement)):
        raise AcquisitionError("Docket settled record is incomplete")
    if (
        docket_inspection["requested_issuance"] != issuance.get("issuance")
        or custody.get("issuance") != issuance.get("issuance")
        or settlement.get("issuance") != issuance.get("issuance")
        or settlement.get("attempt") != custody.get("attempt")
        or settlement.get("executor_marker") != custody.get("executor_marker")
    ):
        raise AcquisitionError("Docket settlement/custody/issuance binding mismatch")
    if issuance.get("work_schema") != LOCAL_COMPOSE_WORK_SCHEMA_V1:
        raise AcquisitionError("workflow has no qualified acquisition adapter")
    if executor_plan.get("schema") != LOCAL_COMPOSE_PLAN_SCHEMA_V1:
        raise AcquisitionError("unsupported local-Compose executor plan")
    if compilation_receipt.get("schema") != COMPILATION_SCHEMA_V1:
        raise AcquisitionError("unsupported compilation receipt")
    if (
        compilation_receipt.get("compiler_id") != LOCAL_COMPOSE_COMPILER_ID
        or compilation_receipt.get("compiler_version") != "1"
        or compilation_receipt.get("plan_digest")
        != executor_plan.get("plan_document_digest")
        or compilation_receipt.get("exact_work_identity") != issuance.get("work")
        or executor_plan.get("subject_digest") != issuance.get("subject")
        or executor_plan.get("scope_digest") != issuance.get("scope")
    ):
        raise AcquisitionError("compiler/work/issuance binding mismatch")
    if external_profile.get("schema") != EXTERNAL_PROFILE_SCHEMA_V1:
        raise AcquisitionError("unsupported external-evidence profile")
    _closed(
        external_profile,
        {
            "schema",
            "profile_id",
            "purpose",
            "expected_adapter_id",
            "expected_adapter_version",
            "expected_producer_principal_id",
            "expected_producer_key_id",
            "expected_runtime_id",
            "required_action",
            "required_claims",
            "max_age_ms",
        },
        "external-evidence profile",
    )
    profile_preimage = dict(external_profile)
    profile_preimage.pop("profile_id", None)
    if external_profile.get("profile_id") != content_digest(
        canonical_json_bytes(profile_preimage)
    ):
        raise AcquisitionError("external-evidence profile identity mismatch")
    if (
        external_profile.get("expected_adapter_id") != LOCAL_COMPOSE_ADAPTER_ID
        or external_profile.get("expected_adapter_version")
        != LOCAL_COMPOSE_ADAPTER_VERSION
        or external_profile.get("expected_runtime_id") != target_runtime_id
    ):
        raise AcquisitionError("external-evidence profile/adapter/runtime mismatch")
    for field in (
        "expected_producer_principal_id",
        "expected_producer_key_id",
    ):
        _token(external_profile.get(field), field)
    if (
        external_profile.get("purpose") != "post_settlement_successor"
        or external_profile.get("required_action") != "qualify"
        or external_profile.get("required_claims")
        != [
            "front_door_reachable",
            "cache_miss_then_hit",
            "single_cache_failure_survived",
            "cache_topology_restored",
        ]
        or not isinstance(external_profile.get("max_age_ms"), int)
        or external_profile["max_age_ms"] <= 0
    ):
        raise AcquisitionError(
            "external-evidence profile is not the closed successor profile"
        )
    bindings = [
        binding
        for items in parse_cross_probe(governed_bindings).values()
        for binding in items
        if binding.compilation_id == compilation_receipt.get("compilation_id")
    ]
    if not bindings:
        raise AcquisitionError("no governed PlanNode binding for exact compilation")
    expected = {
        "campaign_id": issuance["key"]["campaign"],
        "occurrence_id": issuance["key"]["occurrence"],
        "proposal_id": issuance["proposal"],
        "exact_work_identity": issuance["work"],
        "issuance_id": issuance["issuance"],
        "docket_attempt_id": custody["attempt"],
        "settlement_id": settlement["settlement"],
        "outcome": settlement["outcome"],
    }
    for binding in bindings:
        data = binding.to_data()
        if any(data[key] != value for key, value in expected.items()):
            raise AcquisitionError(
                "governed binding does not match Docket settled record"
            )
    unsigned = {
        "adapter_id": LOCAL_COMPOSE_ADAPTER_ID,
        "adapter_version": LOCAL_COMPOSE_ADAPTER_VERSION,
        "attempt_id": custody["attempt"],
        "basis_evaluated_at_unix_ms": None,
        "campaign_id": issuance["key"]["campaign"],
        "compilation_id": compilation_receipt["compilation_id"],
        "compiler_id": compilation_receipt["compiler_id"],
        "compiler_version": compilation_receipt["compiler_version"],
        "currentness_basis_digest": None,
        "exact_work_id": issuance["work"],
        "external_evidence_profile_id": external_profile["profile_id"],
        "issuance_id": issuance["issuance"],
        "occurrence_id": issuance["key"]["occurrence"],
        "plan_document_digest": compilation_receipt["plan_digest"],
        "proposal_id": issuance["proposal"],
        "reason": AcquisitionReason.POST_SETTLEMENT.value,
        "schema": TRIGGER_SCHEMA_V1,
        "scope_digest": issuance["scope"],
        "settled_at_unix_ms": settlement["settled_at_unix_ms"],
        "settlement_id": settlement["settlement"],
        "settlement_receipt_id": settlement["receipt"],
        "source_observation_id": None,
        "subject_digest": issuance["subject"],
        "target_occurrence_id": None,
        "target_runtime_id": target_runtime_id,
        "workflow_schema": issuance["work_schema"],
    }
    trigger = AcquisitionTriggerV1(
        trigger_id=_record_id(unsigned, "trigger_id"),
        reason=AcquisitionReason.POST_SETTLEMENT,
        campaign_id=unsigned["campaign_id"],
        occurrence_id=unsigned["occurrence_id"],
        proposal_id=unsigned["proposal_id"],
        exact_work_id=unsigned["exact_work_id"],
        issuance_id=unsigned["issuance_id"],
        attempt_id=unsigned["attempt_id"],
        settlement_id=unsigned["settlement_id"],
        settlement_receipt_id=unsigned["settlement_receipt_id"],
        settled_at_unix_ms=unsigned["settled_at_unix_ms"],
        plan_document_digest=unsigned["plan_document_digest"],
        compilation_id=unsigned["compilation_id"],
        compiler_id=unsigned["compiler_id"],
        compiler_version=unsigned["compiler_version"],
        workflow_schema=unsigned["workflow_schema"],
        adapter_id=unsigned["adapter_id"],
        adapter_version=unsigned["adapter_version"],
        external_evidence_profile_id=unsigned["external_evidence_profile_id"],
        subject_digest=unsigned["subject_digest"],
        scope_digest=unsigned["scope_digest"],
        target_runtime_id=target_runtime_id,
    )
    trigger.validate()
    return trigger


def build_reobserve_after_stale_trigger(
    *,
    docket_inspection: dict[str, Any],
    executor_plan: dict[str, Any],
    compilation_receipt: dict[str, Any],
    governed_bindings: dict[str, Any],
    steady_profile: dict[str, Any],
    reobservation_basis: dict[str, Any],
    target_runtime_id: str,
    reason: AcquisitionReason = AcquisitionReason.REOBSERVE_AFTER_STALE,
) -> AcquisitionTriggerV1:
    """Bind an owner-produced absent/stale basis to the passive adapter."""
    if reason not in {
        AcquisitionReason.REOBSERVE_FOR_SUCCESSOR,
        AcquisitionReason.REOBSERVE_AFTER_STALE,
    }:
        raise AcquisitionError("unsupported passive acquisition reason")
    expected_requirement = (
        "absent" if reason == AcquisitionReason.REOBSERVE_FOR_SUCCESSOR else "stale"
    )
    if steady_profile.get("schema") != STEADY_PROFILE_SCHEMA_V1:
        raise AcquisitionError("unsupported steady-state profile")
    profile_preimage = dict(steady_profile)
    profile_preimage.pop("profile_id", None)
    if steady_profile.get("profile_id") != content_digest(
        canonical_json_bytes(profile_preimage)
    ):
        raise AcquisitionError("steady-state profile identity mismatch")
    expected_profile_fields = {
        "schema",
        "profile_id",
        "purpose",
        "qualification_profile",
        "expected_adapter_id",
        "expected_adapter_version",
        "expected_producer_principal_id",
        "expected_producer_key_id",
        "expected_runtime_id",
        "required_qualification_claims",
        "required_steady_state_claims",
        "max_age_ms",
    }
    _closed(steady_profile, expected_profile_fields, "steady-state profile")
    if (
        steady_profile.get("purpose") != "routine_continuation"
        or steady_profile.get("expected_adapter_id") != LOCAL_COMPOSE_STEADY_ADAPTER_ID
        or steady_profile.get("expected_adapter_version")
        != LOCAL_COMPOSE_STEADY_ADAPTER_VERSION
        or steady_profile.get("expected_runtime_id") != target_runtime_id
        or steady_profile.get("required_steady_state_claims")
        != [
            "front_door_reachable",
            "cache_a_present",
            "cache_b_present",
            "ordinary_cache_behavior_observed",
        ]
        or steady_profile.get("required_qualification_claims")
        != [
            "front_door_reachable",
            "cache_miss_then_hit",
            "single_cache_failure_survived",
            "cache_topology_restored",
        ]
        or not isinstance(steady_profile.get("max_age_ms"), int)
        or steady_profile["max_age_ms"] <= 0
    ):
        raise AcquisitionError("profile is not the closed passive continuation profile")
    qualification_profile = steady_profile.get("qualification_profile")
    if not isinstance(qualification_profile, dict):
        raise AcquisitionError(
            "steady-state profile lacks strong qualification profile"
        )
    strong = build_post_settlement_trigger(
        docket_inspection=docket_inspection,
        executor_plan=executor_plan,
        compilation_receipt=compilation_receipt,
        governed_bindings=governed_bindings,
        external_profile=qualification_profile,
        target_runtime_id=target_runtime_id,
    )
    if (
        reobservation_basis.get("schema") != STEADY_BASIS_SCHEMA_V1
        or reobservation_basis.get("requirement") != expected_requirement
        or reobservation_basis.get("profile_id") != steady_profile["profile_id"]
        or reobservation_basis.get("qualification_observation_id") is None
    ):
        raise AcquisitionError(
            "Nightshift basis does not require the requested passive acquisition"
        )
    if reason == AcquisitionReason.REOBSERVE_AFTER_STALE:
        if (
            reobservation_basis.get("source_observation_id") is None
            or reobservation_basis.get("source_custody_id") is None
            or reobservation_basis.get("prior_fresh_until_unix_ms") is None
            or reobservation_basis.get("evaluated_at_unix_ms", -1)
            < reobservation_basis["prior_fresh_until_unix_ms"]
        ):
            raise AcquisitionError(
                "Nightshift basis does not require stale re-observation"
            )
    elif any(
        reobservation_basis.get(field) is not None
        for field in (
            "source_observation_id",
            "source_custody_id",
            "prior_fresh_until_unix_ms",
        )
    ):
        raise AcquisitionError("absent basis cannot name prior passive evidence")
    basis_preimage = dict(reobservation_basis)
    basis_preimage.pop("basis_id", None)
    if reobservation_basis.get("basis_id") != content_digest(
        canonical_json_bytes(basis_preimage)
    ):
        raise AcquisitionError("re-observation basis identity mismatch")
    exact = {
        "campaign_id": strong.campaign_id,
        "occurrence_id": strong.occurrence_id,
        "proposal_id": strong.proposal_id,
        "exact_work_id": strong.exact_work_id,
        "issuance_id": strong.issuance_id,
        "attempt_id": strong.attempt_id,
        "settlement_id": strong.settlement_id,
        "plan_document_digest": strong.plan_document_digest,
        "compilation_id": strong.compilation_id,
        "subject_digest": strong.subject_digest,
        "scope_digest": strong.scope_digest,
    }
    if any(reobservation_basis.get(name) != value for name, value in exact.items()):
        raise AcquisitionError(
            "re-observation basis does not bind exact qualified artifact"
        )
    unsigned = {
        **strong.unsigned_data(),
        "adapter_id": LOCAL_COMPOSE_STEADY_ADAPTER_ID,
        "adapter_version": LOCAL_COMPOSE_STEADY_ADAPTER_VERSION,
        "basis_evaluated_at_unix_ms": reobservation_basis["evaluated_at_unix_ms"],
        "currentness_basis_digest": reobservation_basis["basis_id"],
        "external_evidence_profile_id": steady_profile["profile_id"],
        "reason": reason.value,
        "source_observation_id": reobservation_basis["source_observation_id"],
    }
    trigger = AcquisitionTriggerV1(
        trigger_id=_record_id(unsigned, "trigger_id"),
        reason=reason,
        campaign_id=strong.campaign_id,
        occurrence_id=strong.occurrence_id,
        proposal_id=strong.proposal_id,
        exact_work_id=strong.exact_work_id,
        issuance_id=strong.issuance_id,
        attempt_id=strong.attempt_id,
        settlement_id=strong.settlement_id,
        settlement_receipt_id=strong.settlement_receipt_id,
        settled_at_unix_ms=strong.settled_at_unix_ms,
        plan_document_digest=strong.plan_document_digest,
        compilation_id=strong.compilation_id,
        compiler_id=strong.compiler_id,
        compiler_version=strong.compiler_version,
        workflow_schema=strong.workflow_schema,
        adapter_id=LOCAL_COMPOSE_STEADY_ADAPTER_ID,
        adapter_version=LOCAL_COMPOSE_STEADY_ADAPTER_VERSION,
        external_evidence_profile_id=steady_profile["profile_id"],
        subject_digest=strong.subject_digest,
        scope_digest=strong.scope_digest,
        target_runtime_id=target_runtime_id,
        source_observation_id=reobservation_basis["source_observation_id"],
        currentness_basis_digest=reobservation_basis["basis_id"],
        basis_evaluated_at_unix_ms=reobservation_basis["evaluated_at_unix_ms"],
    )
    trigger.validate()
    return trigger


class AcquisitionStore:
    """Append-only SQLite trigger/request/event ledger plus exact source bytes."""

    def __init__(self, path: str | Path, *, now: Callable[[], datetime] = _now) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._now = now
        self._prepare_path()
        self._initialize()

    def now_unix_ms(self) -> int:
        return int(self._now().timestamp() * 1000)

    def _prepare_path(self) -> None:
        try:
            metadata = self.path.lstat()
        except FileNotFoundError:
            try:
                descriptor = os.open(
                    self.path,
                    os.O_RDWR
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_CLOEXEC", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                )
            except FileExistsError:
                self._prepare_path()
                return
            else:
                os.close(descriptor)
                return
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise AcquisitionError(
                "acquisition ledger must be a non-symlink regular file"
            )
        if hasattr(os, "geteuid") and metadata.st_uid != os.geteuid():
            raise AcquisitionError(
                "acquisition ledger is not owned by the service principal"
            )
        if metadata.st_mode & 0o077:
            raise AcquisitionError(
                "acquisition ledger must not be accessible by group or others"
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS acquisition_store_meta(schema TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS acquisition_triggers(
                    trigger_id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL,
                    occurrence_id TEXT NOT NULL, record BLOB NOT NULL,
                    docket_inspection BLOB NOT NULL, executor_evidence BLOB NOT NULL,
                    executor_plan BLOB NOT NULL, compilation_receipt BLOB NOT NULL,
                    governed_bindings BLOB NOT NULL, external_profile BLOB NOT NULL,
                    reobservation_basis BLOB
                );
                CREATE TABLE IF NOT EXISTS acquisition_requests(
                    request_id TEXT PRIMARY KEY, trigger_id TEXT NOT NULL UNIQUE
                        REFERENCES acquisition_triggers(trigger_id), record BLOB NOT NULL
                );
                CREATE TABLE IF NOT EXISTS acquisition_events(
                    event_id TEXT PRIMARY KEY, request_id TEXT NOT NULL
                        REFERENCES acquisition_requests(request_id), sequence INTEGER NOT NULL,
                    kind TEXT NOT NULL, record BLOB NOT NULL, UNIQUE(request_id,sequence)
                );
                CREATE TABLE IF NOT EXISTS acquisition_artifacts(
                    request_id TEXT PRIMARY KEY REFERENCES acquisition_requests(request_id),
                    observation_id TEXT NOT NULL UNIQUE, handoff_id TEXT NOT NULL UNIQUE,
                    observed_at_unix_ms INTEGER NOT NULL, handoff BLOB NOT NULL
                );
            """)
            columns = {
                row[1] for row in db.execute("PRAGMA table_info(acquisition_triggers)")
            }
            if "reobservation_basis" not in columns:
                db.execute(
                    "ALTER TABLE acquisition_triggers ADD COLUMN reobservation_basis BLOB"
                )
            db.execute(
                "INSERT OR IGNORE INTO acquisition_store_meta VALUES (?)",
                (STORE_SCHEMA_V1,),
            )
            schemas = [
                row[0]
                for row in db.execute("SELECT schema FROM acquisition_store_meta")
            ]
            if schemas != [STORE_SCHEMA_V1]:
                raise AcquisitionError(
                    f"unsupported acquisition store schema(s): {schemas}"
                )
        os.chmod(self.path, 0o600)

    def record(
        self,
        trigger: AcquisitionTriggerV1,
        request: AcquisitionRequestV1,
        sources: AcquisitionSourcesV1,
    ) -> AcquisitionRequestV1:
        trigger.validate()
        request.validate()
        if (
            request.trigger_id != trigger.trigger_id
            or request.reason != trigger.reason
            or request.adapter_id != trigger.adapter_id
            or request.adapter_version != trigger.adapter_version
            or request.target_runtime_id != trigger.target_runtime_id
        ):
            raise AcquisitionError("acquisition request contradicts trigger")
        _validate_sources_for_trigger(trigger, sources)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT record FROM acquisition_triggers WHERE trigger_id=?",
                (trigger.trigger_id,),
            ).fetchone()
            if existing is not None:
                persisted = AcquisitionTriggerV1.from_data(
                    json.loads(bytes(existing[0]))
                )
                if persisted != trigger:
                    raise AcquisitionConflict("trigger identity collision")
                prior = db.execute(
                    "SELECT record FROM acquisition_requests WHERE trigger_id=?",
                    (trigger.trigger_id,),
                ).fetchone()
                if prior is None:
                    raise AcquisitionError("trigger exists without request")
                persisted_request = AcquisitionRequestV1.from_data(
                    json.loads(bytes(prior[0]))
                )
                if persisted_request != request:
                    raise AcquisitionConflict(
                        "trigger is already bound to another request"
                    )
            else:
                db.execute(
                    "INSERT INTO acquisition_triggers "
                    "(trigger_id,campaign_id,occurrence_id,record,docket_inspection,"
                    "executor_evidence,executor_plan,compilation_receipt,governed_bindings,"
                    "external_profile,reobservation_basis) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        trigger.trigger_id,
                        trigger.campaign_id,
                        trigger.occurrence_id,
                        canonical_json_bytes(trigger.to_data()),
                        sources.docket_inspection,
                        sources.executor_evidence,
                        sources.executor_plan,
                        sources.compilation_receipt,
                        sources.governed_bindings,
                        sources.external_profile,
                        sources.reobservation_basis,
                    ),
                )
                db.execute(
                    "INSERT INTO acquisition_requests VALUES (?,?,?)",
                    (
                        request.request_id,
                        trigger.trigger_id,
                        canonical_json_bytes(request.to_data()),
                    ),
                )
        self._append_once(request.request_id, AcquisitionEventKind.TRIGGER_RECORDED)
        self._append_once(
            request.request_id, AcquisitionEventKind.ACQUISITION_SCHEDULED
        )
        return request

    def request(self, request_id: str) -> AcquisitionRequestV1:
        with self._connect() as db:
            row = db.execute(
                "SELECT record FROM acquisition_requests WHERE request_id=?",
                (request_id,),
            ).fetchone()
        if row is None:
            raise AcquisitionError(f"acquisition request not found: {request_id}")
        return AcquisitionRequestV1.from_data(json.loads(bytes(row[0])))

    def trigger(self, trigger_id: str) -> AcquisitionTriggerV1:
        with self._connect() as db:
            row = db.execute(
                "SELECT record FROM acquisition_triggers WHERE trigger_id=?",
                (trigger_id,),
            ).fetchone()
        if row is None:
            raise AcquisitionError(f"acquisition trigger not found: {trigger_id}")
        return AcquisitionTriggerV1.from_data(json.loads(bytes(row[0])))

    def sources(self, trigger_id: str) -> AcquisitionSourcesV1:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM acquisition_triggers WHERE trigger_id=?", (trigger_id,)
            ).fetchone()
        if row is None:
            raise AcquisitionError(f"acquisition trigger not found: {trigger_id}")
        return AcquisitionSourcesV1(
            docket_inspection=bytes(row["docket_inspection"]),
            executor_evidence=bytes(row["executor_evidence"]),
            executor_plan=bytes(row["executor_plan"]),
            compilation_receipt=bytes(row["compilation_receipt"]),
            governed_bindings=bytes(row["governed_bindings"]),
            external_profile=bytes(row["external_profile"]),
            reobservation_basis=None
            if row["reobservation_basis"] is None
            else bytes(row["reobservation_basis"]),
        )

    def events(self, request_id: str) -> tuple[AcquisitionEventV1, ...]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT record FROM acquisition_events WHERE request_id=? ORDER BY sequence",
                (request_id,),
            ).fetchall()
        return tuple(
            AcquisitionEventV1.from_data(json.loads(bytes(row[0]))) for row in rows
        )

    def _append(
        self, request_id: str, kind: AcquisitionEventKind, **facts: Any
    ) -> AcquisitionEventV1:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            sequence = db.execute(
                "SELECT COALESCE(MAX(sequence),0)+1 FROM acquisition_events WHERE request_id=?",
                (request_id,),
            ).fetchone()[0]
            event = AcquisitionEventV1.create(
                request_id=request_id,
                sequence=sequence,
                kind=kind,
                recorded_at=_utc(self._now()),
                **facts,
            )
            db.execute(
                "INSERT INTO acquisition_events VALUES (?,?,?,?,?)",
                (
                    event.event_id,
                    request_id,
                    sequence,
                    kind.value,
                    canonical_json_bytes(event.to_data()),
                ),
            )
        return event

    def _append_once(
        self, request_id: str, kind: AcquisitionEventKind, **facts: Any
    ) -> AcquisitionEventV1:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT record FROM acquisition_events WHERE request_id=? AND kind=? ORDER BY sequence LIMIT 1",
                (request_id, kind.value),
            ).fetchone()
            if row is not None:
                return AcquisitionEventV1.from_data(json.loads(bytes(row[0])))
            sequence = db.execute(
                "SELECT COALESCE(MAX(sequence),0)+1 FROM acquisition_events WHERE request_id=?",
                (request_id,),
            ).fetchone()[0]
            event = AcquisitionEventV1.create(
                request_id=request_id,
                sequence=sequence,
                kind=kind,
                recorded_at=_utc(self._now()),
                **facts,
            )
            db.execute(
                "INSERT INTO acquisition_events VALUES (?,?,?,?,?)",
                (
                    event.event_id,
                    request_id,
                    sequence,
                    kind.value,
                    canonical_json_bytes(event.to_data()),
                ),
            )
        return event

    def claim_invocation(
        self, request_id: str, *, recover_incomplete: bool
    ) -> AcquisitionEventV1 | None:
        """Claim one adapter invocation without letting concurrent workers race.

        An incomplete prior invocation is outcome-unknown.  Only an explicit
        recovery may claim again, and v1 permits that solely because this
        adapter packages immutable Docket executor evidence rather than
        reacquiring the world.
        """
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute(
                "SELECT 1 FROM acquisition_artifacts WHERE request_id=?", (request_id,)
            ).fetchone():
                return None
            rows = db.execute(
                "SELECT kind,record FROM acquisition_events WHERE request_id=? ORDER BY sequence",
                (request_id,),
            ).fetchall()
            events = [
                AcquisitionEventV1.from_data(json.loads(bytes(row["record"])))
                for row in rows
            ]
            starts = [
                event
                for event in events
                if event.kind == AcquisitionEventKind.ADAPTER_INVOCATION_STARTED
            ]
            request = self.request(request_id)
            if starts and request.reason != AcquisitionReason.POST_SETTLEMENT:
                # A passive adapter reacquires the world. Re-invoking it under
                # the same identity could silently change observed_at/claims.
                # A later owner-produced basis must create a new acquisition.
                return None
            if len(starts) >= MAX_ADAPTER_INVOCATIONS:
                raise AcquisitionError(
                    "bounded adapter invocation budget exhausted for exact acquisition"
                )
            last_start = starts[-1] if starts else None
            completed_after = last_start is None or any(
                event.sequence > last_start.sequence
                and event.kind
                in {
                    AcquisitionEventKind.ADAPTER_RETURNED_EVIDENCE,
                    AcquisitionEventKind.ADAPTER_FAILED,
                }
                for event in events
            )
            if (
                last_start is not None
                and not completed_after
                and not recover_incomplete
            ):
                return None
            sequence = (events[-1].sequence if events else 0) + 1
            event = AcquisitionEventV1.create(
                request_id=request_id,
                sequence=sequence,
                kind=AcquisitionEventKind.ADAPTER_INVOCATION_STARTED,
                recorded_at=_utc(self._now()),
                invocation=len(starts) + 1,
            )
            db.execute(
                "INSERT INTO acquisition_events VALUES (?,?,?,?,?)",
                (
                    event.event_id,
                    request_id,
                    sequence,
                    event.kind.value,
                    canonical_json_bytes(event.to_data()),
                ),
            )
            return event

    def record_adapter_failure(self, request_id: str, error: str) -> AcquisitionEventV1:
        return self._append(
            request_id,
            AcquisitionEventKind.ADAPTER_FAILED,
            reason="qualified adapter refused or failed",
            error_digest=content_digest(error.encode("utf-8")),
        )

    def put_handoff(self, request_id: str, handoff: bytes) -> dict[str, Any]:
        value = _strict_json_bytes(handoff, "external observation handoff")
        observation = value.get("observation")
        if not isinstance(observation, dict):
            raise AcquisitionError("handoff lacks exact observation")
        observation_id = _digest(observation.get("observation_id"), "observation_id")
        handoff_id = _digest(value.get("handoff_id"), "handoff_id")
        observed_at = observation.get("observed_at_unix_ms")
        if not isinstance(observed_at, int):
            raise AcquisitionError("handoff lacks exact acquisition time")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT handoff FROM acquisition_artifacts WHERE request_id=?",
                (request_id,),
            ).fetchone()
            if existing is not None:
                if bytes(existing[0]) != handoff:
                    raise AcquisitionConflict(
                        "one acquisition produced substituted evidence"
                    )
                return _strict_json_bytes(bytes(existing[0]), "stored handoff")
            db.execute(
                "INSERT INTO acquisition_artifacts VALUES (?,?,?,?,?)",
                (
                    request_id,
                    observation_id,
                    handoff_id,
                    observed_at,
                    handoff,
                ),
            )
        self._append(
            request_id,
            AcquisitionEventKind.ADAPTER_RETURNED_EVIDENCE,
            observation_id=observation_id,
            handoff_id=handoff_id,
            observed_at_unix_ms=observed_at,
        )
        return value

    def handoff(self, request_id: str) -> bytes | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT handoff FROM acquisition_artifacts WHERE request_id=?",
                (request_id,),
            ).fetchone()
        return None if row is None else bytes(row[0])

    def terminal(self, request_id: str) -> AcquisitionEventV1 | None:
        terminal = {
            AcquisitionEventKind.CUSTODY_ACCEPTED,
            AcquisitionEventKind.CUSTODY_REFUSED,
            AcquisitionEventKind.REOBSERVATION_REFUSED,
        }
        return next(
            (
                event
                for event in reversed(self.events(request_id))
                if event.kind in terminal
            ),
            None,
        )

    def export(self, request_id: str) -> dict[str, Any]:
        request = self.request(request_id)
        trigger = self.trigger(request.trigger_id)
        handoff = self.handoff(request_id)
        events = self.events(request_id)
        return {
            "schema": EXPORT_SCHEMA_V1,
            "request": request.to_data(),
            "trigger": trigger.to_data(),
            "events": [event.to_data() for event in events],
            "evidence": None
            if handoff is None
            else {
                "handoff_digest": content_digest(handoff),
                "handoff": json.loads(handoff),
            },
            "nonclaims": [
                "adapter success is not Nightshift currentness",
                "custody acceptance is not decision adequacy",
                "transport replay does not refresh evidence time",
                "acquisition orchestration creates no standing or authorization",
            ],
        }

    def export_occurrence(self, campaign_id: str, occurrence_id: str) -> dict[str, Any]:
        _digest(campaign_id, "campaign_id")
        _token(occurrence_id, "occurrence_id")
        with self._connect() as db:
            rows = db.execute(
                "SELECT r.request_id FROM acquisition_requests r "
                "JOIN acquisition_triggers t ON t.trigger_id=r.trigger_id "
                "WHERE t.campaign_id=? AND t.occurrence_id=? ORDER BY r.rowid",
                (campaign_id, occurrence_id),
            ).fetchall()
        return {
            "schema": HISTORY_SCHEMA_V1,
            "campaign_id": campaign_id,
            "occurrence_id": occurrence_id,
            "acquisitions": [self.export(row[0]) for row in rows],
        }


class CustodyPort(Protocol):
    def import_handoff(self, handoff: bytes) -> dict[str, Any]: ...


class LocalComposePostSettlementAdapter:
    """The sole v1 registry entry; packages immutable settled evidence."""

    def __init__(
        self, *, producer_key: bytes, producer_principal_id: str, producer_key_id: str
    ) -> None:
        self.key = producer_key
        self.principal = producer_principal_id
        self.key_id = producer_key_id

    def acquire(
        self,
        request: AcquisitionRequestV1,
        trigger: AcquisitionTriggerV1,
        sources: AcquisitionSourcesV1,
    ) -> bytes:
        if request.reason != AcquisitionReason.POST_SETTLEMENT:
            raise AcquisitionError(
                "local-Compose v1 adapter cannot re-observe its governed fault-injection claim set; "
                "new governed work or a new Nightshift adequacy profile is required"
            )
        evidence = _strict_json_bytes(sources.executor_evidence, "executor evidence")
        plan = _strict_json_bytes(sources.executor_plan, "executor plan")
        compilation = _strict_json_bytes(
            sources.compilation_receipt, "compilation receipt"
        )
        bindings = _strict_json_bytes(sources.governed_bindings, "governed bindings")
        profile = _strict_json_bytes(sources.external_profile, "external profile")
        if (
            profile.get("expected_producer_principal_id") != self.principal
            or profile.get("expected_producer_key_id") != self.key_id
        ):
            raise AcquisitionError(
                "configured observation producer does not match exact Nightshift profile"
            )
        observation = build_observation(
            executor_evidence=evidence,
            executor_evidence_bytes=sources.executor_evidence,
            executor_plan=plan,
            executor_plan_bytes=sources.executor_plan,
            compilation_receipt=compilation,
            governed_bindings=bindings,
        )
        if (
            observation["campaign_id"] != trigger.campaign_id
            or observation["occurrence_id"] != trigger.occurrence_id
            or observation["proposal_id"] != trigger.proposal_id
            or observation["exact_work_id"] != trigger.exact_work_id
            or observation["attempt_id"] != trigger.attempt_id
            or observation["settlement_id"] != trigger.settlement_id
        ):
            raise AcquisitionError(
                "adapter output contradicts exact acquisition trigger"
            )
        # Deterministic evidence packaging time: the Docket settlement is the
        # latest source fact. Exact transport recovery reproduces these bytes.
        created_at = _timestamp_from_ms(trigger.settled_at_unix_ms)
        handoff = seal_handoff(
            observation,
            producer_principal_id=self.principal,
            producer_key_id=self.key_id,
            target_runtime_id=trigger.target_runtime_id,
            producer_key=self.key,
            created_at=created_at,
        )
        return canonical_json_bytes(handoff)


class LocalComposeSteadyStateAdapter:
    """Closed passive registry entry; it cannot emit qualification claims."""

    def __init__(
        self,
        *,
        producer_key: bytes,
        producer_principal_id: str,
        producer_key_id: str,
        probe: PassiveProbe | None = None,
        observed_at: Callable[[], datetime] = _now,
    ) -> None:
        self.key = producer_key
        self.principal = producer_principal_id
        self.key_id = producer_key_id
        self.probe = probe or LocalComposePassiveProbe()
        self.observed_at = observed_at

    def acquire(
        self,
        request: AcquisitionRequestV1,
        trigger: AcquisitionTriggerV1,
        sources: AcquisitionSourcesV1,
    ) -> bytes:
        if request.reason not in {
            AcquisitionReason.REOBSERVE_FOR_SUCCESSOR,
            AcquisitionReason.REOBSERVE_AFTER_STALE,
        }:
            raise AcquisitionError(
                "passive adapter accepts only bounded re-observation"
            )
        if sources.reobservation_basis is None:
            raise AcquisitionError("passive adapter lacks owner-produced basis")
        basis = _strict_json_bytes(
            sources.reobservation_basis, "steady-state re-observation basis"
        )
        plan = _strict_json_bytes(sources.executor_plan, "executor plan")
        compilation = _strict_json_bytes(
            sources.compilation_receipt, "compilation receipt"
        )
        bindings = _strict_json_bytes(sources.governed_bindings, "governed bindings")
        profile = _strict_json_bytes(sources.external_profile, "steady-state profile")
        if (
            trigger.currentness_basis_digest != basis.get("basis_id")
            or trigger.source_observation_id != basis.get("source_observation_id")
            or trigger.external_evidence_profile_id != profile.get("profile_id")
            or profile.get("expected_producer_principal_id") != self.principal
            or profile.get("expected_producer_key_id") != self.key_id
        ):
            raise AcquisitionError(
                "passive adapter source/profile/producer binding failed"
            )
        return acquire_steady_state_handoff(
            basis=basis,
            plan=plan,
            compilation=compilation,
            governed_bindings=bindings,
            observed_at=_utc(self.observed_at()),
            probe=self.probe,
            producer_principal_id=self.principal,
            producer_key_id=self.key_id,
            target_runtime_id=trigger.target_runtime_id,
            producer_key=self.key,
        )


class NightshiftCliCustodyPort:
    """Fixed Nightshift import command; never a generic subprocess surface."""

    def __init__(
        self,
        *,
        program: Path,
        store: Path,
        credential: Path,
        producer_principal_id: str,
        producer_key_id: str,
        runtime_id: str,
        received_at: Callable[[], datetime] = _now,
        timeout_seconds: int = 30,
    ) -> None:
        self.program = program
        self.store = store
        self.credential = credential
        self.principal = producer_principal_id
        self.key_id = producer_key_id
        self.runtime_id = runtime_id
        self.received_at = received_at
        self.timeout_seconds = timeout_seconds

    def import_handoff(self, handoff: bytes) -> dict[str, Any]:
        decoded = _strict_json_bytes(handoff, "external observation handoff")
        schema = decoded.get("schema")
        if schema == "nightshift.external_observation_handoff.v1":
            import_verb = "import"
        elif schema == STEADY_HANDOFF_SCHEMA_V1:
            import_verb = "import-steady-state"
        else:
            raise CustodyRefused("unsupported observation handoff schema")
        temporary = self.store.parent / (
            ".acquisition-handoff-" + content_digest(handoff)[7:] + ".json"
        )
        _stage_exact_handoff(temporary, handoff)
        arguments = [
            str(self.program),
            "--store",
            str(self.store),
            "external-observation",
            import_verb,
            "--handoff",
            str(temporary),
            "--credential",
            str(self.credential),
            "--producer-principal-id",
            self.principal,
            "--producer-key-id",
            self.key_id,
            "--nightshift-runtime-id",
            self.runtime_id,
            "--received-at",
            _utc(self.received_at()),
        ]
        try:
            completed = subprocess.run(
                arguments,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise CustodyOutcomeUnknown(
                "Nightshift import response timed out"
            ) from error
        if (
            len(completed.stdout) > MAX_COMMAND_OUTPUT
            or len(completed.stderr) > MAX_COMMAND_OUTPUT
        ):
            raise CustodyOutcomeUnknown("Nightshift import response exceeded bound")
        if completed.returncode != 0:
            raise CustodyRefused(completed.stderr.decode("utf-8", "replace")[-1000:])
        return _owner_json_bytes(completed.stdout, "Nightshift custody receipt")


def _stage_exact_handoff(path: Path, handoff: bytes) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            descriptor = os.open(path, flags, 0o600)
        except FileExistsError:
            _stage_exact_handoff(path, handoff)
            return
        try:
            remaining = memoryview(handoff)
            while remaining:
                written = os.write(descriptor, remaining)
                if written == 0:
                    raise CustodyRefused("short write while staging exact handoff")
                remaining = remaining[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise CustodyRefused("handoff staging path is not a regular file")
    if hasattr(os, "geteuid") and metadata.st_uid != os.geteuid():
        raise CustodyRefused("handoff staging path has another owner")
    if metadata.st_mode & 0o077:
        raise CustodyRefused("handoff staging path is accessible by group or others")
    if _read_exact_file(path, MAX_INPUT_BYTES, "staged handoff") != handoff:
        raise CustodyRefused("handoff staging path substitution")


def run_acquisition(
    store: AcquisitionStore,
    request_id: str,
    adapter: LocalComposePostSettlementAdapter | LocalComposeSteadyStateAdapter,
    custody: CustodyPort,
    *,
    fault_after_handoff: bool = False,
    recover_incomplete: bool = False,
) -> dict[str, Any]:
    request = store.request(request_id)
    trigger = store.trigger(request.trigger_id)
    terminal = store.terminal(request_id)
    if terminal is not None:
        return store.export(request_id)
    handoff = store.handoff(request_id)
    if handoff is None:
        if store.now_unix_ms() < request.not_before_unix_ms:
            raise AcquisitionError("acquisition request is not yet eligible")
        sources = store.sources(trigger.trigger_id)
        _validate_sources_for_trigger(trigger, sources)
        claim = store.claim_invocation(
            request_id, recover_incomplete=recover_incomplete
        )
        if claim is None:
            raise CustodyOutcomeUnknown(
                "an adapter invocation is already in progress or ended without a durable result; "
                "reconcile that exact acquisition before recovery"
            )
        try:
            handoff = adapter.acquire(request, trigger, sources)
            store.put_handoff(request_id, handoff)
        except Exception as error:
            store.record_adapter_failure(request_id, str(error))
            raise
    if fault_after_handoff:
        raise CustodyOutcomeUnknown("injected response-loss cut after durable evidence")
    try:
        receipt = custody.import_handoff(handoff)
    except CustodyOutcomeUnknown as error:
        store._append(
            request_id,
            AcquisitionEventKind.CUSTODY_OUTCOME_UNKNOWN,
            reason=str(error),
            error_digest=content_digest(str(error).encode()),
        )
        raise
    except CustodyRefused as error:
        store._append_once(
            request_id,
            AcquisitionEventKind.CUSTODY_REFUSED,
            reason=str(error),
            error_digest=content_digest(str(error).encode()),
        )
        return store.export(request_id)
    store._append_once(
        request_id,
        AcquisitionEventKind.CUSTODY_ACCEPTED,
        observation_id=receipt.get("observation_id"),
        handoff_id=receipt.get("handoff_id"),
        custody_id=receipt.get("custody_id"),
    )
    return store.export(request_id)


def inspect_docket(
    program: Path, state: Path, issuance: str
) -> tuple[dict[str, Any], bytes]:
    _digest(issuance, "issuance")
    completed = subprocess.run(
        [
            str(program),
            "governed-loop",
            "inspect",
            "--state",
            str(state),
            "--issuance",
            issuance,
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        raise AcquisitionError(
            "Docket inspection refused: "
            + completed.stderr.decode("utf-8", "replace")[-1000:]
        )
    if len(completed.stdout) > MAX_COMMAND_OUTPUT:
        raise AcquisitionError("Docket inspection exceeded response bound")
    raw = completed.stdout
    value = _owner_json_bytes(raw, "Docket inspection")
    return value, raw


def _read(path: Path, name: str) -> tuple[dict[str, Any], bytes]:
    raw = _read_exact_file(path, MAX_INPUT_BYTES, name)
    return _strict_json_bytes(raw, name), raw


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="One-shot exact post-settlement evidence acquisition"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("record-post-settlement")
    _add_record_arguments(create)
    orchestrate = sub.add_parser("orchestrate-post-settlement")
    _add_record_arguments(orchestrate)
    _add_custody_arguments(orchestrate, request_id=False)
    reobserve = sub.add_parser("record-reobserve-after-stale")
    _add_record_arguments(reobserve)
    reobserve.add_argument("--reobservation-basis", type=Path, required=True)
    orchestrate_reobserve = sub.add_parser("orchestrate-reobserve-after-stale")
    _add_record_arguments(orchestrate_reobserve)
    orchestrate_reobserve.add_argument(
        "--reobservation-basis", type=Path, required=True
    )
    _add_custody_arguments(orchestrate_reobserve, request_id=False)
    successor = sub.add_parser("record-reobserve-for-successor")
    _add_record_arguments(successor)
    successor.add_argument("--reobservation-basis", type=Path, required=True)
    orchestrate_successor = sub.add_parser("orchestrate-reobserve-for-successor")
    _add_record_arguments(orchestrate_successor)
    orchestrate_successor.add_argument(
        "--reobservation-basis", type=Path, required=True
    )
    _add_custody_arguments(orchestrate_successor, request_id=False)
    run = sub.add_parser("run")
    _add_custody_arguments(run, request_id=True)
    show = sub.add_parser("show")
    show.add_argument("--ledger", type=Path, required=True)
    show.add_argument("--request-id", required=True)
    history = sub.add_parser("export-occurrence")
    history.add_argument("--ledger", type=Path, required=True)
    history.add_argument("--campaign-id", required=True)
    history.add_argument("--occurrence-id", required=True)
    return parser


def _add_record_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--docket-program", type=Path, required=True)
    parser.add_argument("--docket-state", type=Path, required=True)
    parser.add_argument("--issuance", required=True)
    for name in (
        "executor-evidence",
        "executor-plan",
        "compilation-receipt",
        "governed-bindings",
        "external-profile",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--target-runtime-id", required=True)


def _add_custody_arguments(
    parser: argparse.ArgumentParser, *, request_id: bool
) -> None:
    if request_id:
        parser.add_argument("--ledger", type=Path, required=True)
        parser.add_argument("--request-id", required=True)
    parser.add_argument("--producer-key", type=Path, required=True)
    parser.add_argument("--producer-principal-id", required=True)
    parser.add_argument("--producer-key-id", required=True)
    parser.add_argument("--nightshift-program", type=Path, required=True)
    parser.add_argument("--nightshift-store", type=Path, required=True)
    parser.add_argument("--nightshift-credential", type=Path, required=True)
    parser.add_argument("--nightshift-runtime-id", required=True)
    parser.add_argument("--recover-incomplete", action="store_true")


def _record_post_settlement(
    store: AcquisitionStore, args: argparse.Namespace
) -> AcquisitionRequestV1:
    docket, docket_raw = inspect_docket(
        args.docket_program, args.docket_state, args.issuance
    )
    plan, plan_raw = _read(args.executor_plan, "executor plan")
    compilation, compilation_raw = _read(
        args.compilation_receipt, "compilation receipt"
    )
    bindings, bindings_raw = _read(args.governed_bindings, "governed bindings")
    profile, profile_raw = _read(args.external_profile, "external profile")
    _, evidence_raw = _read(args.executor_evidence, "executor evidence")
    trigger = build_post_settlement_trigger(
        docket_inspection=docket,
        executor_plan=plan,
        compilation_receipt=compilation,
        governed_bindings=bindings,
        external_profile=profile,
        target_runtime_id=args.target_runtime_id,
    )
    request = AcquisitionRequestV1.create(trigger)
    return store.record(
        trigger,
        request,
        AcquisitionSourcesV1(
            docket_raw,
            evidence_raw,
            plan_raw,
            compilation_raw,
            bindings_raw,
            profile_raw,
        ),
    )


def _record_passive_reobservation(
    store: AcquisitionStore,
    args: argparse.Namespace,
    reason: AcquisitionReason,
) -> AcquisitionRequestV1:
    docket, docket_raw = inspect_docket(
        args.docket_program, args.docket_state, args.issuance
    )
    plan, plan_raw = _read(args.executor_plan, "executor plan")
    compilation, compilation_raw = _read(
        args.compilation_receipt, "compilation receipt"
    )
    bindings, bindings_raw = _read(args.governed_bindings, "governed bindings")
    profile, profile_raw = _read(args.external_profile, "steady-state profile")
    basis, basis_raw = _read(
        args.reobservation_basis, "steady-state re-observation basis"
    )
    _, evidence_raw = _read(args.executor_evidence, "historical executor evidence")
    trigger = build_reobserve_after_stale_trigger(
        docket_inspection=docket,
        executor_plan=plan,
        compilation_receipt=compilation,
        governed_bindings=bindings,
        steady_profile=profile,
        reobservation_basis=basis,
        target_runtime_id=args.target_runtime_id,
        reason=reason,
    )
    request = AcquisitionRequestV1.create(trigger)
    return store.record(
        trigger,
        request,
        AcquisitionSourcesV1(
            docket_raw,
            evidence_raw,
            plan_raw,
            compilation_raw,
            bindings_raw,
            profile_raw,
            basis_raw,
        ),
    )


def _run_from_args(
    store: AcquisitionStore, request_id: str, args: argparse.Namespace
) -> dict[str, Any]:
    request = store.request(request_id)
    adapter: LocalComposePostSettlementAdapter | LocalComposeSteadyStateAdapter
    if request.reason == AcquisitionReason.POST_SETTLEMENT:
        adapter = LocalComposePostSettlementAdapter(
            producer_key=read_protected_key(args.producer_key),
            producer_principal_id=args.producer_principal_id,
            producer_key_id=args.producer_key_id,
        )
    else:
        adapter = LocalComposeSteadyStateAdapter(
            producer_key=read_protected_key(args.producer_key),
            producer_principal_id=args.producer_principal_id,
            producer_key_id=args.producer_key_id,
        )
    custody = NightshiftCliCustodyPort(
        program=args.nightshift_program,
        store=args.nightshift_store,
        credential=args.nightshift_credential,
        producer_principal_id=args.producer_principal_id,
        producer_key_id=args.producer_key_id,
        runtime_id=args.nightshift_runtime_id,
    )
    return run_acquisition(
        store,
        request_id,
        adapter,
        custody,
        recover_incomplete=args.recover_incomplete,
    )


def main() -> int:
    args = _parser().parse_args()
    store = AcquisitionStore(args.ledger)
    if args.command in {"record-post-settlement", "orchestrate-post-settlement"}:
        request = _record_post_settlement(store, args)
        if args.command == "orchestrate-post-settlement":
            print(
                canonical_json_bytes(
                    _run_from_args(store, request.request_id, args)
                ).decode()
            )
            return 0
        print(canonical_json_bytes(request.to_data()).decode())
        return 0
    if args.command in {
        "record-reobserve-after-stale",
        "orchestrate-reobserve-after-stale",
        "record-reobserve-for-successor",
        "orchestrate-reobserve-for-successor",
    }:
        reason = (
            AcquisitionReason.REOBSERVE_FOR_SUCCESSOR
            if args.command.endswith("for-successor")
            else AcquisitionReason.REOBSERVE_AFTER_STALE
        )
        request = _record_passive_reobservation(store, args, reason)
        if args.command.startswith("orchestrate-"):
            print(
                canonical_json_bytes(
                    _run_from_args(store, request.request_id, args)
                ).decode()
            )
            return 0
        print(canonical_json_bytes(request.to_data()).decode())
        return 0
    if args.command == "run":
        print(
            canonical_json_bytes(_run_from_args(store, args.request_id, args)).decode()
        )
        return 0
    if args.command == "show":
        print(canonical_json_bytes(store.export(args.request_id)).decode())
    else:
        print(
            canonical_json_bytes(
                store.export_occurrence(args.campaign_id, args.occurrence_id)
            ).decode()
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
