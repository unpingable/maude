# SPDX-License-Identifier: Apache-2.0
"""SQLite-backed immutable revision/receipt store for Plan Core artifacts."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from maude.plan.checks import (
    CHECKER_ID,
    CHECKER_VERSION,
    RULE_SET,
    CheckReceiptV1,
    run_checks,
)
from maude.plan.compiler import CompilationReceiptV1, CompilationResultV1
from maude.plan.document import PlanDocumentV1, canonical_json_bytes, content_digest

STORE_SCHEMA = "maude.plan-store/v1"
LOCK_RECEIPT_SCHEMA = "maude.plan-lock-receipt/v1"
ARTIFACT_REFERENCE_SCHEMA = "maude.plan-artifact-reference/v1"


class DraftConflict(RuntimeError):
    """The current revision changed; callers must reload instead of overwriting."""


class DraftNotFound(KeyError):
    pass


class EditOrigin(str, Enum):
    HUMAN = "human"
    AGENT = "agent"
    IMPORT = "import"


def _utc(now: Callable[[], datetime]) -> str:
    return now().astimezone(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class DraftRevisionV1:
    revision_id: str
    draft_id: str
    ordinal: int
    parent_revision_id: str | None
    plan_digest: str
    document: PlanDocumentV1
    edit_origin: EditOrigin
    created_at: str

    def to_data(self) -> dict[str, Any]:
        return {
            "created_at": self.created_at,
            "draft_id": self.draft_id,
            "edit_origin": self.edit_origin.value,
            "ordinal": self.ordinal,
            "parent_revision_id": self.parent_revision_id,
            "plan_digest": self.plan_digest,
            "revision_id": self.revision_id,
            "schema": "maude.plan-revision/v1",
        }


@dataclass(frozen=True)
class LockReceiptV1:
    lock_id: str
    draft_id: str
    revision_id: str
    plan_digest: str
    locked_at: str
    applicable_check_receipts: tuple[str, ...]
    schema: str = LOCK_RECEIPT_SCHEMA

    def unsigned_data(self) -> dict[str, Any]:
        return {
            "applicable_check_receipts": list(self.applicable_check_receipts),
            "draft_id": self.draft_id,
            "locked_at": self.locked_at,
            "plan_digest": self.plan_digest,
            "revision_id": self.revision_id,
            "schema": self.schema,
        }

    def to_data(self) -> dict[str, Any]:
        return {**self.unsigned_data(), "lock_id": self.lock_id}

    @classmethod
    def from_data(cls, raw: dict[str, Any]) -> LockReceiptV1:
        receipt = cls(
            lock_id=raw["lock_id"],
            draft_id=raw["draft_id"],
            revision_id=raw["revision_id"],
            plan_digest=raw["plan_digest"],
            locked_at=raw["locked_at"],
            applicable_check_receipts=tuple(raw["applicable_check_receipts"]),
            schema=raw["schema"],
        )
        if receipt.schema != LOCK_RECEIPT_SCHEMA:
            raise ValueError("unsupported lock receipt schema")
        if (
            content_digest(canonical_json_bytes(receipt.unsigned_data()))
            != receipt.lock_id
        ):
            raise ValueError("lock receipt identity does not bind its content")
        return receipt


class CheckApplicability(str, Enum):
    NEVER_CHECKED = "never_checked"
    CURRENT_PASS = "current_pass"
    CURRENT_FINDINGS = "current_findings"
    HISTORICAL_DIGEST = "historical_digest"
    RETIRED_CHECKER_OR_RULES = "retired_checker_or_rules"


@dataclass(frozen=True)
class CheckReceiptProjectionV1:
    receipt: CheckReceiptV1
    applicability: CheckApplicability

    def to_data(self) -> dict[str, Any]:
        return {
            "applicability": self.applicability.value,
            "receipt": self.receipt.to_data(),
        }


@dataclass(frozen=True)
class LockReceiptProjectionV1:
    receipt: LockReceiptV1
    applicability: str

    def to_data(self) -> dict[str, Any]:
        return {"applicability": self.applicability, "receipt": self.receipt.to_data()}


@dataclass(frozen=True)
class ExternalArtifactReferenceV1:
    """Owner-produced handoff/governed fact; Plan Core compares, never mints it."""

    kind: str
    reference_id: str
    plan_digest: str
    owner: str
    schema: str = ARTIFACT_REFERENCE_SCHEMA

    def __post_init__(self) -> None:
        if self.kind not in {"handoff", "governed"}:
            raise ValueError("artifact reference kind must be handoff or governed")

    def to_data(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "owner": self.owner,
            "plan_digest": self.plan_digest,
            "reference_id": self.reference_id,
            "schema": self.schema,
        }


@dataclass(frozen=True)
class DraftProjectionV1:
    current: DraftRevisionV1
    check_summary: CheckApplicability
    checks: tuple[CheckReceiptProjectionV1, ...]
    locks: tuple[LockReceiptProjectionV1, ...]
    compilations: tuple[CompilationReceiptV1, ...]
    external_references: tuple[ExternalArtifactReferenceV1, ...]

    def to_data(self) -> dict[str, Any]:
        current_digest = self.current.plan_digest
        last_applicable_check = next(
            (
                item.receipt.receipt_id
                for item in reversed(self.checks)
                if item.applicability
                in {
                    CheckApplicability.CURRENT_PASS,
                    CheckApplicability.CURRENT_FINDINGS,
                }
            ),
            None,
        )
        return {
            "checks": [item.to_data() for item in self.checks],
            "check_summary": self.check_summary.value,
            "compilations": [item.to_data() for item in self.compilations],
            "current_revision": self.current.to_data(),
            "external_references": [
                {
                    **item.to_data(),
                    "matches_working_revision": item.plan_digest == current_digest,
                }
                for item in self.external_references
            ],
            "last_applicable_check_receipt_id": last_applicable_check,
            "last_check_receipt_id": self.checks[-1].receipt.receipt_id
            if self.checks
            else None,
            "last_lock_receipt_id": self.locks[-1].receipt.lock_id
            if self.locks
            else None,
            "last_compilation_receipt_id": self.compilations[-1].compilation_id
            if self.compilations
            else None,
            "locks": [item.to_data() for item in self.locks],
            "schema": "maude.plan-lifecycle-projection/v1",
            "working_differs_from_governed": any(
                ref.kind == "governed" and ref.plan_digest != current_digest
                for ref in self.external_references
            ),
            "working_differs_from_handoff": any(
                ref.kind == "handoff" and ref.plan_digest != current_digest
                for ref in self.external_references
            ),
            "working_differs_from_locked": any(
                lock.receipt.plan_digest != current_digest for lock in self.locks
            ),
        }


def classify_check_receipts(
    current_digest: str, receipts: tuple[CheckReceiptV1, ...]
) -> tuple[CheckApplicability, tuple[CheckReceiptProjectionV1, ...]]:
    """Classify retained receipts without erasing historical/version facts."""
    checks: list[CheckReceiptProjectionV1] = []
    for receipt in receipts:
        if receipt.plan_digest != current_digest:
            applicability = CheckApplicability.HISTORICAL_DIGEST
        elif (
            receipt.checker_id != CHECKER_ID
            or receipt.checker_version != CHECKER_VERSION
            or receipt.rule_set != RULE_SET
        ):
            applicability = CheckApplicability.RETIRED_CHECKER_OR_RULES
        elif receipt.result == "passed":
            applicability = CheckApplicability.CURRENT_PASS
        else:
            applicability = CheckApplicability.CURRENT_FINDINGS
        checks.append(CheckReceiptProjectionV1(receipt, applicability))
    if any(
        item.applicability == CheckApplicability.CURRENT_FINDINGS for item in checks
    ):
        summary = CheckApplicability.CURRENT_FINDINGS
    elif any(item.applicability == CheckApplicability.CURRENT_PASS for item in checks):
        summary = CheckApplicability.CURRENT_PASS
    elif any(
        item.applicability == CheckApplicability.RETIRED_CHECKER_OR_RULES
        for item in checks
    ):
        summary = CheckApplicability.RETIRED_CHECKER_OR_RULES
    elif checks:
        summary = CheckApplicability.HISTORICAL_DIGEST
    else:
        summary = CheckApplicability.NEVER_CHECKED
    return summary, tuple(checks)


class DraftStore:
    def __init__(
        self,
        path: str | Path,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        read_only: bool = False,
        readonly: bool | None = None,
    ) -> None:
        self.path = Path(path)
        self._now = now
        if readonly is not None:
            if read_only and readonly != read_only:
                raise ValueError("conflicting Plan Core read-only options")
            read_only = readonly
        self._readonly = read_only
        if self._readonly:
            if not self.path.is_file():
                raise FileNotFoundError(f"read-only Plan Core store is absent: {self.path}")
            self._validate_read_only_schema()
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._initialize()

    @classmethod
    def open_readonly(
        cls,
        path: str | Path,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> DraftStore:
        """Open an existing Plan Core store without schema initialization or writes."""
        return cls(path, now=now, read_only=True)

    def _connect(self) -> sqlite3.Connection:
        if self._readonly:
            connection = sqlite3.connect(
                f"{self.path.resolve().as_uri()}?mode=ro", uri=True, timeout=10
            )
        else:
            connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _validate_read_only_schema(self) -> None:
        """Refuse a store whose existing metadata is not this closed schema."""
        with self._connect() as db:
            rows = db.execute(
                "SELECT schema FROM plan_store_meta ORDER BY schema LIMIT 2"
            ).fetchall()
        schemas = [row[0] for row in rows]
        if schemas != [STORE_SCHEMA]:
            raise ValueError(f"unsupported plan store schema(s): {schemas}")

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS plan_store_meta (
                    schema TEXT PRIMARY KEY
                );
                CREATE TABLE IF NOT EXISTS drafts (
                    draft_id TEXT PRIMARY KEY,
                    current_revision_id TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS revisions (
                    revision_id TEXT PRIMARY KEY,
                    draft_id TEXT NOT NULL REFERENCES drafts(draft_id),
                    ordinal INTEGER NOT NULL,
                    parent_revision_id TEXT,
                    plan_digest TEXT NOT NULL,
                    artifact BLOB NOT NULL,
                    edit_origin TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(draft_id, ordinal)
                );
                CREATE TABLE IF NOT EXISTS check_receipts (
                    receipt_id TEXT PRIMARY KEY,
                    draft_id TEXT NOT NULL REFERENCES drafts(draft_id),
                    revision_id TEXT NOT NULL REFERENCES revisions(revision_id),
                    plan_digest TEXT NOT NULL,
                    record BLOB NOT NULL
                );
                CREATE TABLE IF NOT EXISTS lock_receipts (
                    lock_id TEXT PRIMARY KEY,
                    draft_id TEXT NOT NULL REFERENCES drafts(draft_id),
                    revision_id TEXT NOT NULL REFERENCES revisions(revision_id),
                    plan_digest TEXT NOT NULL,
                    artifact BLOB NOT NULL,
                    record BLOB NOT NULL
                );
                CREATE TABLE IF NOT EXISTS compilation_receipts (
                    compilation_id TEXT PRIMARY KEY,
                    draft_id TEXT NOT NULL REFERENCES drafts(draft_id),
                    revision_id TEXT NOT NULL REFERENCES revisions(revision_id),
                    lock_id TEXT NOT NULL REFERENCES lock_receipts(lock_id),
                    plan_digest TEXT NOT NULL,
                    compiler_inputs BLOB NOT NULL,
                    compiled_output BLOB NOT NULL,
                    record BLOB NOT NULL,
                    UNIQUE(lock_id, compiler_inputs, compiled_output)
                );
                """
            )
            db.execute(
                "INSERT OR IGNORE INTO plan_store_meta(schema) VALUES (?)",
                (STORE_SCHEMA,),
            )
            rows = [row[0] for row in db.execute("SELECT schema FROM plan_store_meta")]
            if rows != [STORE_SCHEMA]:
                raise ValueError(f"unsupported plan store schema(s): {rows}")

    @staticmethod
    def _revision_id(
        draft_id: str,
        parent_revision_id: str | None,
        plan_digest: str,
        edit_origin: EditOrigin,
    ) -> str:
        return content_digest(
            canonical_json_bytes(
                {
                    "draft_id": draft_id,
                    "edit_origin": edit_origin.value,
                    "parent_revision_id": parent_revision_id,
                    "plan_digest": plan_digest,
                    "schema": "maude.plan-revision-identity/v1",
                }
            )
        )

    def create(
        self,
        document: PlanDocumentV1,
        *,
        draft_id: str | None = None,
        edit_origin: EditOrigin = EditOrigin.HUMAN,
    ) -> DraftRevisionV1:
        # Dataclass construction does not validate the closed wire schema.
        # Refuse invalid documents before a transaction can retain them.
        document = PlanDocumentV1.parse(document.canonical_bytes)
        draft_id = draft_id or "draft_" + uuid.uuid4().hex
        created_at = _utc(self._now)
        revision_id = self._revision_id(draft_id, None, document.digest, edit_origin)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO drafts(draft_id,current_revision_id,created_at) VALUES (?,?,?)",
                (draft_id, revision_id, created_at),
            )
            db.execute(
                "INSERT INTO revisions VALUES (?,?,?,?,?,?,?,?)",
                (
                    revision_id,
                    draft_id,
                    1,
                    None,
                    document.digest,
                    document.canonical_bytes,
                    edit_origin.value,
                    created_at,
                ),
            )
        return self.revision(revision_id)

    def list_drafts(self) -> tuple[DraftRevisionV1, ...]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT current_revision_id FROM drafts ORDER BY created_at,draft_id"
            ).fetchall()
        return tuple(self.revision(row[0]) for row in rows)

    def current(self, draft_id: str) -> DraftRevisionV1:
        with self._connect() as db:
            row = db.execute(
                "SELECT current_revision_id FROM drafts WHERE draft_id=?", (draft_id,)
            ).fetchone()
        if row is None:
            raise DraftNotFound(draft_id)
        return self.revision(row[0])

    def revision(self, revision_id: str) -> DraftRevisionV1:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM revisions WHERE revision_id=?", (revision_id,)
            ).fetchone()
        if row is None:
            raise DraftNotFound(revision_id)
        document = PlanDocumentV1.parse(bytes(row["artifact"]))
        if document.digest != row["plan_digest"]:
            raise ValueError("stored PlanDocument bytes do not match persisted digest")
        return DraftRevisionV1(
            revision_id=row["revision_id"],
            draft_id=row["draft_id"],
            ordinal=row["ordinal"],
            parent_revision_id=row["parent_revision_id"],
            plan_digest=row["plan_digest"],
            document=document,
            edit_origin=EditOrigin(row["edit_origin"]),
            created_at=row["created_at"],
        )

    def revisions(self, draft_id: str) -> tuple[DraftRevisionV1, ...]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT revision_id FROM revisions WHERE draft_id=? ORDER BY ordinal",
                (draft_id,),
            ).fetchall()
        return tuple(self.revision(row[0]) for row in rows)

    def save_successor(
        self,
        draft_id: str,
        expected_revision_id: str,
        document: PlanDocumentV1,
        *,
        edit_origin: EditOrigin,
    ) -> DraftRevisionV1:
        document = PlanDocumentV1.parse(document.canonical_bytes)
        revision_id = self._revision_id(
            draft_id, expected_revision_id, document.digest, edit_origin
        )
        created_at = _utc(self._now)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT current_revision_id FROM drafts WHERE draft_id=?", (draft_id,)
            ).fetchone()
            if row is None:
                raise DraftNotFound(draft_id)
            current = row[0]
            if current == revision_id:
                return self.revision(revision_id)
            if current != expected_revision_id:
                raise DraftConflict(
                    f"expected current revision {expected_revision_id}, found {current}"
                )
            ordinal = (
                db.execute(
                    "SELECT ordinal FROM revisions WHERE revision_id=?", (current,)
                ).fetchone()[0]
                + 1
            )
            db.execute(
                "INSERT INTO revisions VALUES (?,?,?,?,?,?,?,?)",
                (
                    revision_id,
                    draft_id,
                    ordinal,
                    current,
                    document.digest,
                    document.canonical_bytes,
                    edit_origin.value,
                    created_at,
                ),
            )
            changed = db.execute(
                "UPDATE drafts SET current_revision_id=? WHERE draft_id=? AND current_revision_id=?",
                (revision_id, draft_id, current),
            ).rowcount
            if changed != 1:
                raise DraftConflict("current revision advanced concurrently")
        return self.revision(revision_id)

    def check(self, draft_id: str, revision_id: str | None = None) -> CheckReceiptV1:
        revision = (
            self.current(draft_id)
            if revision_id is None
            else self.revision(revision_id)
        )
        if revision.draft_id != draft_id:
            raise DraftConflict("revision belongs to another draft")
        receipt = run_checks(revision.document, now=self._now)
        record = canonical_json_bytes(receipt.to_data())
        with self._connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO check_receipts VALUES (?,?,?,?,?)",
                (
                    receipt.receipt_id,
                    draft_id,
                    revision.revision_id,
                    revision.plan_digest,
                    record,
                ),
            )
        return receipt

    def check_receipts(
        self, draft_id: str, revision_id: str | None = None
    ) -> tuple[CheckReceiptV1, ...]:
        with self._connect() as db:
            if revision_id is None:
                rows = db.execute(
                    "SELECT receipt_id,revision_id,plan_digest,record FROM check_receipts "
                    "WHERE draft_id=? ORDER BY rowid",
                    (draft_id,),
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT receipt_id,revision_id,plan_digest,record FROM check_receipts "
                    "WHERE draft_id=? AND revision_id=? ORDER BY rowid",
                    (draft_id, revision_id),
                ).fetchall()
        receipts: list[CheckReceiptV1] = []
        for row in rows:
            receipt = CheckReceiptV1.from_data(json.loads(bytes(row["record"])))
            revision = self.revision(row["revision_id"])
            if (
                receipt.receipt_id != row["receipt_id"]
                or receipt.plan_digest != row["plan_digest"]
                or receipt.plan_digest != revision.plan_digest
                or revision.draft_id != draft_id
            ):
                raise ValueError("check receipt persistence binding is contradictory")
            receipts.append(receipt)
        return tuple(receipts)

    def lock(self, draft_id: str, revision_id: str | None = None) -> LockReceiptV1:
        revision = (
            self.current(draft_id)
            if revision_id is None
            else self.revision(revision_id)
        )
        if revision.draft_id != draft_id:
            raise DraftConflict("revision belongs to another draft")
        checks = tuple(
            receipt.receipt_id
            for receipt in self.check_receipts(draft_id)
            if receipt.plan_digest == revision.plan_digest
            and receipt.checker_id == CHECKER_ID
            and receipt.checker_version == CHECKER_VERSION
            and receipt.rule_set == RULE_SET
        )
        unsigned = {
            "applicable_check_receipts": list(checks),
            "draft_id": draft_id,
            "locked_at": _utc(self._now),
            "plan_digest": revision.plan_digest,
            "revision_id": revision.revision_id,
            "schema": LOCK_RECEIPT_SCHEMA,
        }
        lock = LockReceiptV1(
            lock_id=content_digest(canonical_json_bytes(unsigned)),
            draft_id=draft_id,
            revision_id=revision.revision_id,
            plan_digest=revision.plan_digest,
            locked_at=unsigned["locked_at"],
            applicable_check_receipts=checks,
        )
        with self._connect() as db:
            existing = db.execute(
                "SELECT record FROM lock_receipts WHERE draft_id=? AND revision_id=? ORDER BY rowid LIMIT 1",
                (draft_id, revision.revision_id),
            ).fetchone()
            if existing is not None:
                return LockReceiptV1.from_data(json.loads(bytes(existing[0])))
            db.execute(
                "INSERT INTO lock_receipts VALUES (?,?,?,?,?,?)",
                (
                    lock.lock_id,
                    draft_id,
                    revision.revision_id,
                    revision.plan_digest,
                    revision.document.canonical_bytes,
                    canonical_json_bytes(lock.to_data()),
                ),
            )
        return lock

    def locks(self, draft_id: str) -> tuple[LockReceiptV1, ...]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT lock_id,revision_id,artifact,record,plan_digest FROM lock_receipts "
                "WHERE draft_id=? ORDER BY rowid",
                (draft_id,),
            ).fetchall()
        locks: list[LockReceiptV1] = []
        for row in rows:
            artifact = bytes(row["artifact"])
            if content_digest(artifact) != row["plan_digest"]:
                raise ValueError("locked artifact bytes do not match persisted digest")
            receipt = LockReceiptV1.from_data(json.loads(bytes(row["record"])))
            revision = self.revision(row["revision_id"])
            if (
                receipt.lock_id != row["lock_id"]
                or receipt.plan_digest != revision.plan_digest
                or receipt.revision_id != revision.revision_id
                or revision.draft_id != draft_id
            ):
                raise ValueError("lock receipt persistence binding is contradictory")
            locks.append(receipt)
        return tuple(locks)

    def record_compilation(
        self,
        draft_id: str,
        lock_id: str,
        result: CompilationResultV1,
        *,
        compiler_inputs: bytes,
        exact_work_identity: str,
    ) -> CompilationReceiptV1:
        """Persist exact representation evidence for one immutable lock.

        This records no handoff and creates no owner-side lineage.  A later
        custody record may reference the compiled bytes; it cannot be inferred
        from this receipt.
        """
        lock = next((item for item in self.locks(draft_id) if item.lock_id == lock_id), None)
        if lock is None:
            raise DraftConflict("compilation requires an exact lock receipt")
        if (
            lock.plan_digest != result.source_plan_digest
            or content_digest(compiler_inputs) != result.compiler_inputs_digest
        ):
            raise DraftConflict("compilation input does not bind the exact locked artifact")
        compiled_at = _utc(self._now)
        receipt = CompilationReceiptV1.create(
            draft_id=draft_id,
            revision_id=lock.revision_id,
            lock_id=lock.lock_id,
            result=result,
            exact_work_identity=exact_work_identity,
            compiled_at=compiled_at,
        )
        with self._connect() as db:
            existing = db.execute(
                "SELECT record,compiler_inputs,compiled_output FROM compilation_receipts "
                "WHERE compilation_id=?",
                (receipt.compilation_id,),
            ).fetchone()
            if existing is not None:
                loaded = CompilationReceiptV1.from_data(json.loads(bytes(existing[0])))
                if (
                    loaded != receipt
                    or bytes(existing[1]) != compiler_inputs
                    or bytes(existing[2]) != result.handoff_bytes
                ):
                    raise ValueError("compilation identity collision")
                return loaded
            db.execute(
                "INSERT INTO compilation_receipts VALUES (?,?,?,?,?,?,?,?)",
                (
                    receipt.compilation_id,
                    draft_id,
                    lock.revision_id,
                    lock.lock_id,
                    lock.plan_digest,
                    compiler_inputs,
                    result.handoff_bytes,
                    canonical_json_bytes(receipt.to_data()),
                ),
            )
        return receipt

    def compilations(
        self, draft_id: str
    ) -> tuple[tuple[CompilationReceiptV1, bytes, bytes], ...]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT revision_id,lock_id,plan_digest,compiler_inputs,compiled_output,record "
                "FROM compilation_receipts WHERE draft_id=? ORDER BY rowid",
                (draft_id,),
            ).fetchall()
        values: list[tuple[CompilationReceiptV1, bytes, bytes]] = []
        locks = {item.lock_id: item for item in self.locks(draft_id)}
        for row in rows:
            inputs = bytes(row["compiler_inputs"])
            output = bytes(row["compiled_output"])
            receipt = CompilationReceiptV1.from_data(json.loads(bytes(row["record"])))
            lock = locks.get(row["lock_id"])
            if (
                lock is None
                or receipt.revision_id != row["revision_id"]
                or receipt.plan_digest != row["plan_digest"]
                or receipt.plan_digest != lock.plan_digest
                or receipt.compiler_inputs_digest != content_digest(inputs)
                or receipt.compiled_output_digest != content_digest(output)
            ):
                raise ValueError("compilation persistence binding is contradictory")
            values.append((receipt, inputs, output))
        return tuple(values)

    def projection(
        self,
        draft_id: str,
        *,
        external_references: tuple[ExternalArtifactReferenceV1, ...] = (),
    ) -> DraftProjectionV1:
        current = self.current(draft_id)
        receipts = self.check_receipts(draft_id)
        summary, checks = classify_check_receipts(current.plan_digest, receipts)
        return DraftProjectionV1(
            current=current,
            check_summary=summary,
            checks=checks,
            locks=tuple(
                LockReceiptProjectionV1(
                    lock,
                    "current_digest"
                    if lock.plan_digest == current.plan_digest
                    else "historical_digest",
                )
                for lock in self.locks(draft_id)
            ),
            compilations=tuple(item[0] for item in self.compilations(draft_id)),
            external_references=external_references,
        )
