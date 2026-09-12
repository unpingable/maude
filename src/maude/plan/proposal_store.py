# SPDX-License-Identifier: Apache-2.0
"""Durable immutable storage for pre-governed plan-edit proposals."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from maude.plan.document import canonical_json_bytes, content_digest
from maude.plan.proposals import (
    PlanEditProposalRequestV1,
    PlanEditProposalV1,
    preview_operation_sequence,
)

PROPOSAL_STORE_SCHEMA = "maude.plan-edit-proposal-store/v1"
GENERATION_REFUSAL_SCHEMA = "maude.plan-edit-generation-refusal/v1"
ACCEPTANCE_RECEIPT_SCHEMA = "maude.plan-edit-proposal-acceptance/v1"
REJECTION_RECEIPT_SCHEMA = "maude.plan-edit-proposal-rejection/v1"


class ProposalStoreError(RuntimeError):
    pass


class ProposalDispositionConflict(ProposalStoreError):
    pass


class ProposalLifecycle(str, Enum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    STALE = "stale"


def _utc(now: Callable[[], datetime]) -> str:
    return now().astimezone(UTC).isoformat().replace("+00:00", "Z")


def _record_id(unsigned: dict[str, Any]) -> str:
    return content_digest(canonical_json_bytes(unsigned))


@dataclass(frozen=True)
class GenerationRefusalV1:
    refusal_id: str
    request_id: str
    provider_id: str
    model_id: str
    output_digest: str
    reason: str
    refused_at: str
    schema: str = GENERATION_REFUSAL_SCHEMA

    def unsigned_data(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "output_digest": self.output_digest,
            "provider_id": self.provider_id,
            "reason": self.reason,
            "refused_at": self.refused_at,
            "request_id": self.request_id,
            "schema": self.schema,
        }

    def to_data(self) -> dict[str, Any]:
        return {**self.unsigned_data(), "refusal_id": self.refusal_id}

    @classmethod
    def from_data(cls, raw: dict[str, Any]) -> GenerationRefusalV1:
        result = cls(
            raw["refusal_id"],
            raw["request_id"],
            raw["provider_id"],
            raw["model_id"],
            raw["output_digest"],
            raw["reason"],
            raw["refused_at"],
            raw["schema"],
        )
        if (
            result.schema != GENERATION_REFUSAL_SCHEMA
            or _record_id(result.unsigned_data()) != result.refusal_id
        ):
            raise ProposalStoreError("generation refusal identity is contradictory")
        return result


@dataclass(frozen=True)
class ProposalAcceptanceReceiptV1:
    receipt_id: str
    proposal_id: str
    operation_set_id: str
    draft_id: str
    base_revision_id: str
    base_plan_digest: str
    resulting_revision_id: str
    resulting_plan_digest: str
    accepting_actor: str
    accepted_at: str
    schema: str = ACCEPTANCE_RECEIPT_SCHEMA

    def unsigned_data(self) -> dict[str, Any]:
        return {
            "accepted_at": self.accepted_at,
            "accepting_actor": self.accepting_actor,
            "base_plan_digest": self.base_plan_digest,
            "base_revision_id": self.base_revision_id,
            "draft_id": self.draft_id,
            "operation_set_id": self.operation_set_id,
            "proposal_id": self.proposal_id,
            "resulting_plan_digest": self.resulting_plan_digest,
            "resulting_revision_id": self.resulting_revision_id,
            "schema": self.schema,
        }

    def to_data(self) -> dict[str, Any]:
        return {**self.unsigned_data(), "receipt_id": self.receipt_id}

    @classmethod
    def from_data(cls, raw: dict[str, Any]) -> ProposalAcceptanceReceiptV1:
        result = cls(
            raw["receipt_id"],
            raw["proposal_id"],
            raw["operation_set_id"],
            raw["draft_id"],
            raw["base_revision_id"],
            raw["base_plan_digest"],
            raw["resulting_revision_id"],
            raw["resulting_plan_digest"],
            raw["accepting_actor"],
            raw["accepted_at"],
            raw["schema"],
        )
        if (
            result.schema != ACCEPTANCE_RECEIPT_SCHEMA
            or _record_id(result.unsigned_data()) != result.receipt_id
        ):
            raise ProposalStoreError("acceptance receipt identity is contradictory")
        return result


@dataclass(frozen=True)
class ProposalRejectionReceiptV1:
    receipt_id: str
    proposal_id: str
    rejecting_actor: str
    reason: str
    rejected_at: str
    schema: str = REJECTION_RECEIPT_SCHEMA

    def unsigned_data(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "reason": self.reason,
            "rejected_at": self.rejected_at,
            "rejecting_actor": self.rejecting_actor,
            "schema": self.schema,
        }

    def to_data(self) -> dict[str, Any]:
        return {**self.unsigned_data(), "receipt_id": self.receipt_id}

    @classmethod
    def from_data(cls, raw: dict[str, Any]) -> ProposalRejectionReceiptV1:
        result = cls(
            raw["receipt_id"],
            raw["proposal_id"],
            raw["rejecting_actor"],
            raw["reason"],
            raw["rejected_at"],
            raw["schema"],
        )
        if (
            result.schema != REJECTION_RECEIPT_SCHEMA
            or _record_id(result.unsigned_data()) != result.receipt_id
        ):
            raise ProposalStoreError("rejection receipt identity is contradictory")
        return result


class ProposalStore:
    def __init__(
        self,
        path: str | Path,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._now = now
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS proposal_store_meta(schema TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS proposal_requests(
                    request_id TEXT PRIMARY KEY,
                    generation_id TEXT NOT NULL UNIQUE,
                    draft_id TEXT NOT NULL,
                    base_revision_id TEXT NOT NULL,
                    record BLOB NOT NULL
                );
                CREATE TABLE IF NOT EXISTS proposals(
                    proposal_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL UNIQUE REFERENCES proposal_requests(request_id),
                    draft_id TEXT NOT NULL,
                    base_revision_id TEXT NOT NULL,
                    record BLOB NOT NULL
                );
                CREATE TABLE IF NOT EXISTS generation_refusals(
                    refusal_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL UNIQUE REFERENCES proposal_requests(request_id),
                    record BLOB NOT NULL
                );
                CREATE TABLE IF NOT EXISTS generation_cancellations(
                    request_id TEXT PRIMARY KEY REFERENCES proposal_requests(request_id),
                    generation_id TEXT NOT NULL UNIQUE,
                    draft_id TEXT NOT NULL,
                    requested_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS proposal_dispositions(
                    proposal_id TEXT PRIMARY KEY REFERENCES proposals(proposal_id),
                    kind TEXT NOT NULL,
                    record BLOB NOT NULL
                );
                """
            )
            db.execute(
                "INSERT OR IGNORE INTO proposal_store_meta VALUES (?)",
                (PROPOSAL_STORE_SCHEMA,),
            )
            schemas = [
                row[0] for row in db.execute("SELECT schema FROM proposal_store_meta")
            ]
            if schemas != [PROPOSAL_STORE_SCHEMA]:
                raise ProposalStoreError(
                    f"unsupported proposal store schema(s): {schemas}"
                )

    def put_request(
        self, request: PlanEditProposalRequestV1
    ) -> PlanEditProposalRequestV1:
        record = canonical_json_bytes(request.to_data())
        with self._connect() as db:
            existing = db.execute(
                "SELECT record FROM proposal_requests WHERE request_id=?",
                (request.request_id,),
            ).fetchone()
            if existing is not None:
                loaded = PlanEditProposalRequestV1.from_data(
                    json.loads(bytes(existing[0]))
                )
                if loaded != request:
                    raise ProposalStoreError("request identity collision")
                return loaded
            try:
                db.execute(
                    "INSERT INTO proposal_requests VALUES (?,?,?,?,?)",
                    (
                        request.request_id,
                        request.generation_id,
                        request.draft_id,
                        request.base_revision_id,
                        record,
                    ),
                )
            except sqlite3.IntegrityError:
                pass
        existing_generation = self.request_for_generation(request.generation_id)
        if existing_generation is None:
            raise ProposalStoreError("request persistence did not converge")
        intended = request.unsigned_data().copy()
        persisted = existing_generation.unsigned_data().copy()
        intended.pop("created_at")
        persisted.pop("created_at")
        if intended != persisted:
            raise ProposalStoreError(
                "proposal generation identity acquired conflicting request content"
            )
        return existing_generation

    def request_for_generation(
        self, generation_id: str
    ) -> PlanEditProposalRequestV1 | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT record FROM proposal_requests WHERE generation_id=?",
                (generation_id,),
            ).fetchone()
        return (
            None
            if row is None
            else PlanEditProposalRequestV1.from_data(json.loads(bytes(row[0])))
        )

    def request(self, request_id: str) -> PlanEditProposalRequestV1:
        with self._connect() as db:
            row = db.execute(
                "SELECT record FROM proposal_requests WHERE request_id=?", (request_id,)
            ).fetchone()
        if row is None:
            raise ProposalStoreError(f"proposal request not found: {request_id}")
        return PlanEditProposalRequestV1.from_data(json.loads(bytes(row[0])))

    def request_cancellation(
        self, request_id: str, generation_id: str, draft_id: str
    ) -> dict[str, str]:
        request = self.request(request_id)
        if (request.generation_id, request.draft_id) != (generation_id, draft_id):
            raise ProposalStoreError("cancellation identity does not match proposal request")
        requested_at = _utc(self._now)
        with self._connect() as db:
            if db.execute(
                "SELECT 1 FROM proposals WHERE request_id=? UNION SELECT 1 FROM generation_refusals WHERE request_id=?",
                (request_id, request_id),
            ).fetchone() is not None:
                raise ProposalStoreError("completed generation cannot be cancelled")
            db.execute(
                "INSERT OR IGNORE INTO generation_cancellations VALUES (?,?,?,?)",
                (request_id, generation_id, draft_id, requested_at),
            )
            row = db.execute(
                "SELECT request_id,generation_id,draft_id,requested_at FROM generation_cancellations WHERE request_id=?",
                (request_id,),
            ).fetchone()
        if row is None or (row["generation_id"], row["draft_id"]) != (
            generation_id,
            draft_id,
        ):
            raise ProposalStoreError("cancellation persistence did not converge")
        return dict(row)

    def cancellation_requested(self, request_id: str) -> bool:
        with self._connect() as db:
            return db.execute(
                "SELECT 1 FROM generation_cancellations WHERE request_id=?", (request_id,)
            ).fetchone() is not None

    def generation_cancellations(self, draft_id: str) -> tuple[dict[str, str], ...]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT request_id,generation_id,draft_id,requested_at FROM generation_cancellations WHERE draft_id=? ORDER BY rowid",
                (draft_id,),
            ).fetchall()
        return tuple(dict(row) for row in rows)

    def put_proposal(self, proposal: PlanEditProposalV1) -> PlanEditProposalV1:
        request = self.request(proposal.request_id)
        if (
            proposal.draft_id,
            proposal.base_revision_id,
            proposal.base_plan_digest,
            proposal.scope,
        ) != (
            request.draft_id,
            request.base_revision_id,
            request.base_plan_digest,
            request.scope,
        ):
            raise ProposalStoreError("proposal contradicts its canonical request")
        preview_operation_sequence(
            request.document, proposal.operations, proposal.scope
        )
        record = canonical_json_bytes(proposal.to_data())
        with self._connect() as db:
            if db.execute(
                "SELECT 1 FROM generation_cancellations WHERE request_id=?",
                (proposal.request_id,),
            ).fetchone() is not None:
                raise ProposalStoreError("cancelled generation cannot persist a proposal")
            existing = db.execute(
                "SELECT record FROM proposals WHERE request_id=?",
                (proposal.request_id,),
            ).fetchone()
            if existing is not None:
                loaded = PlanEditProposalV1.from_data(json.loads(bytes(existing[0])))
                if loaded != proposal:
                    raise ProposalStoreError(
                        "one request cannot acquire a substituted proposal"
                    )
                return loaded
            try:
                db.execute(
                    "INSERT INTO proposals VALUES (?,?,?,?,?)",
                    (
                        proposal.proposal_id,
                        proposal.request_id,
                        proposal.draft_id,
                        proposal.base_revision_id,
                        record,
                    ),
                )
            except sqlite3.IntegrityError:
                pass
        persisted = self.proposal_for_request(proposal.request_id)
        if persisted is None:
            raise ProposalStoreError("proposal persistence did not converge")
        intended = proposal.unsigned_data().copy()
        existing_data = persisted.unsigned_data().copy()
        intended.pop("created_at")
        existing_data.pop("created_at")
        if intended != existing_data:
            raise ProposalStoreError(
                "one request acquired conflicting provider proposal content"
            )
        return persisted

    def proposal(self, proposal_id: str) -> PlanEditProposalV1:
        with self._connect() as db:
            row = db.execute(
                "SELECT record FROM proposals WHERE proposal_id=?", (proposal_id,)
            ).fetchone()
        if row is None:
            raise ProposalStoreError(f"proposal not found: {proposal_id}")
        return PlanEditProposalV1.from_data(json.loads(bytes(row[0])))

    def proposal_for_request(self, request_id: str) -> PlanEditProposalV1 | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT record FROM proposals WHERE request_id=?", (request_id,)
            ).fetchone()
        return (
            None
            if row is None
            else PlanEditProposalV1.from_data(json.loads(bytes(row[0])))
        )

    def proposals(self, draft_id: str) -> tuple[PlanEditProposalV1, ...]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT record FROM proposals WHERE draft_id=? ORDER BY rowid",
                (draft_id,),
            ).fetchall()
        return tuple(
            PlanEditProposalV1.from_data(json.loads(bytes(row[0]))) for row in rows
        )

    def refuse_generation(
        self,
        request_id: str,
        provider_id: str,
        model_id: str,
        output: bytes,
        reason: str,
    ) -> GenerationRefusalV1:
        unsigned = {
            "model_id": model_id,
            "output_digest": content_digest(output),
            "provider_id": provider_id,
            "reason": reason,
            "refused_at": _utc(self._now),
            "request_id": request_id,
            "schema": GENERATION_REFUSAL_SCHEMA,
        }
        refusal = GenerationRefusalV1(
            _record_id(unsigned),
            request_id,
            provider_id,
            model_id,
            unsigned["output_digest"],
            reason,
            unsigned["refused_at"],
        )
        with self._connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO generation_refusals VALUES (?,?,?)",
                (
                    refusal.refusal_id,
                    request_id,
                    canonical_json_bytes(refusal.to_data()),
                ),
            )
        with self._connect() as db:
            row = db.execute(
                "SELECT record FROM generation_refusals WHERE request_id=?",
                (request_id,),
            ).fetchone()
        if row is None:
            raise ProposalStoreError("generation refusal persistence did not converge")
        persisted = GenerationRefusalV1.from_data(json.loads(bytes(row[0])))
        if (
            persisted.provider_id,
            persisted.model_id,
            persisted.output_digest,
            persisted.reason,
        ) != (provider_id, model_id, content_digest(output), reason):
            raise ProposalStoreError(
                "one request acquired conflicting provider refusal evidence"
            )
        return persisted

    def generation_refusals(self, draft_id: str) -> tuple[GenerationRefusalV1, ...]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT f.record FROM generation_refusals f JOIN proposal_requests r ON r.request_id=f.request_id WHERE r.draft_id=? ORDER BY f.rowid",
                (draft_id,),
            ).fetchall()
        return tuple(
            GenerationRefusalV1.from_data(json.loads(bytes(row[0]))) for row in rows
        )

    def disposition(
        self, proposal_id: str
    ) -> ProposalAcceptanceReceiptV1 | ProposalRejectionReceiptV1 | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT kind,record FROM proposal_dispositions WHERE proposal_id=?",
                (proposal_id,),
            ).fetchone()
        if row is None:
            return None
        raw = json.loads(bytes(row["record"]))
        return (
            ProposalAcceptanceReceiptV1.from_data(raw)
            if row["kind"] == "accepted"
            else ProposalRejectionReceiptV1.from_data(raw)
        )

    def record_acceptance(
        self,
        proposal: PlanEditProposalV1,
        *,
        resulting_revision_id: str,
        resulting_plan_digest: str,
        accepting_actor: str,
    ) -> ProposalAcceptanceReceiptV1:
        existing = self.disposition(proposal.proposal_id)
        if existing is not None:
            if (
                isinstance(existing, ProposalAcceptanceReceiptV1)
                and existing.resulting_revision_id == resulting_revision_id
                and existing.resulting_plan_digest == resulting_plan_digest
            ):
                return existing
            raise ProposalDispositionConflict(
                "proposal already has another terminal disposition"
            )
        unsigned = {
            "accepted_at": _utc(self._now),
            "accepting_actor": accepting_actor,
            "base_plan_digest": proposal.base_plan_digest,
            "base_revision_id": proposal.base_revision_id,
            "draft_id": proposal.draft_id,
            "operation_set_id": proposal.operation_set_id,
            "proposal_id": proposal.proposal_id,
            "resulting_plan_digest": resulting_plan_digest,
            "resulting_revision_id": resulting_revision_id,
            "schema": ACCEPTANCE_RECEIPT_SCHEMA,
        }
        receipt = ProposalAcceptanceReceiptV1(
            _record_id(unsigned),
            proposal.proposal_id,
            proposal.operation_set_id,
            proposal.draft_id,
            proposal.base_revision_id,
            proposal.base_plan_digest,
            resulting_revision_id,
            resulting_plan_digest,
            accepting_actor,
            unsigned["accepted_at"],
        )
        try:
            with self._connect() as db:
                db.execute(
                    "INSERT INTO proposal_dispositions VALUES (?,?,?)",
                    (
                        proposal.proposal_id,
                        "accepted",
                        canonical_json_bytes(receipt.to_data()),
                    ),
                )
        except sqlite3.IntegrityError:
            return self.record_acceptance(
                proposal,
                resulting_revision_id=resulting_revision_id,
                resulting_plan_digest=resulting_plan_digest,
                accepting_actor=accepting_actor,
            )
        return receipt

    def reject(
        self, proposal: PlanEditProposalV1, *, rejecting_actor: str, reason: str
    ) -> ProposalRejectionReceiptV1:
        existing = self.disposition(proposal.proposal_id)
        if existing is not None:
            if isinstance(existing, ProposalRejectionReceiptV1):
                return existing
            raise ProposalDispositionConflict("accepted proposal cannot be rejected")
        unsigned = {
            "proposal_id": proposal.proposal_id,
            "reason": reason,
            "rejected_at": _utc(self._now),
            "rejecting_actor": rejecting_actor,
            "schema": REJECTION_RECEIPT_SCHEMA,
        }
        receipt = ProposalRejectionReceiptV1(
            _record_id(unsigned),
            proposal.proposal_id,
            rejecting_actor,
            reason,
            unsigned["rejected_at"],
        )
        try:
            with self._connect() as db:
                db.execute(
                    "INSERT INTO proposal_dispositions VALUES (?,?,?)",
                    (
                        proposal.proposal_id,
                        "rejected",
                        canonical_json_bytes(receipt.to_data()),
                    ),
                )
        except sqlite3.IntegrityError:
            existing = self.disposition(proposal.proposal_id)
            if isinstance(existing, ProposalRejectionReceiptV1):
                return existing
            raise ProposalDispositionConflict(
                "proposal acquired a conflicting disposition"
            )
        return receipt
