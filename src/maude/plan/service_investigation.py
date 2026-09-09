# SPDX-License-Identifier: Apache-2.0
"""Closed compiler and handoff ledger for one bounded service investigation.

Maude owns the PlanDocument-to-diagnostic compilation and submission intent. It
does not acquire observations, decide Standing mandate, or own Nightshift state.
Those facts enter only through an exact receipt returned by a configured owner.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from maude.plan.document import canonical_json_bytes, content_digest
from maude.plan.store import DraftRevisionV1

PROFILE_SCHEMA = "maude.service-investigation-profile/v1"
HANDOFF_SCHEMA = "maude.service-investigation-handoff/v1"
SUBMISSION_SCHEMA = "nightshift.service-investigation-submission/v1"
LEDGER_SCHEMA = "maude.service-investigation-ledger/v1"
PROFILES = ("nq.systemd_unit/v1", "nq.http_endpoint/v1")
MAX_OWNER_OUTPUT = 128 * 1024


class ServiceInvestigationError(ValueError):
    pass


def _closed(raw: dict[str, Any], names: set[str], where: str) -> None:
    extra = set(raw) - names
    missing = names - set(raw)
    if extra or missing:
        raise ServiceInvestigationError(
            f"{where} fields differ: missing={sorted(missing)}, unknown={sorted(extra)}"
        )


def _digest(value: str, where: str) -> str:
    if not (
        isinstance(value, str)
        and value.startswith("sha256:")
        and len(value) == 71
        and all(c in "0123456789abcdef" for c in value[7:])
    ):
        raise ServiceInvestigationError(f"{where} must be a lowercase sha256 digest")
    return value


def _token(value: str, where: str) -> str:
    if not value or len(value) > 128 or not all(c.isalnum() or c in "_.:-/" for c in value):
        raise ServiceInvestigationError(f"{where} is malformed")
    return value


@dataclass(frozen=True)
class DiagnosticBindingV1:
    node_id: str
    profile: str
    scope: str
    config_digest: str
    profile_digest: str
    question_digest: str
    threshold_policy_digest: str
    instance: str
    vantage: str
    vantage_digest: str

    @classmethod
    def from_data(cls, raw: dict[str, Any]) -> "DiagnosticBindingV1":
        _closed(
            raw,
            {"node_id", "profile", "scope", "config_digest", "profile_digest", "question_digest", "threshold_policy_digest", "instance", "vantage", "vantage_digest"},
            "diagnostic binding",
        )
        result = cls(
            _token(raw["node_id"], "node_id"),
            raw["profile"],
            _digest(raw["scope"], "scope"),
            _digest(raw["config_digest"], "config_digest"),
            _digest(raw["profile_digest"], "profile_digest"),
            _digest(raw["question_digest"], "question_digest"),
            _digest(raw["threshold_policy_digest"], "threshold_policy_digest"),
            _token(raw["instance"], "instance"),
            _token(raw["vantage"], "vantage"),
            _digest(raw["vantage_digest"], "vantage_digest"),
        )
        if result.profile not in PROFILES:
            raise ServiceInvestigationError("unsupported diagnostic profile")
        return result

    def to_data(self) -> dict[str, str]:
        return {
            "config_digest": self.config_digest,
            "instance": self.instance,
            "node_id": self.node_id,
            "profile": self.profile,
            "profile_digest": self.profile_digest,
            "question_digest": self.question_digest,
            "scope": self.scope,
            "threshold_policy_digest": self.threshold_policy_digest,
            "vantage": self.vantage,
            "vantage_digest": self.vantage_digest,
        }


@dataclass(frozen=True)
class ServiceInvestigationProfileV1:
    profile_id: str
    audience: str
    subject_label: str
    subject: str
    diagnostics: tuple[DiagnosticBindingV1, ...]
    schema: str = PROFILE_SCHEMA

    @classmethod
    def from_data(cls, raw: dict[str, Any]) -> "ServiceInvestigationProfileV1":
        _closed(raw, {"schema", "profile_id", "audience", "subject_label", "subject", "diagnostics"}, "profile")
        if raw["schema"] != PROFILE_SCHEMA:
            raise ServiceInvestigationError("unsupported service investigation profile")
        result = cls(
            _token(raw["profile_id"], "profile_id"),
            _token(raw["audience"], "audience"),
            str(raw["subject_label"]).strip(),
            _digest(raw["subject"], "subject"),
            tuple(DiagnosticBindingV1.from_data(item) for item in raw["diagnostics"]),
        )
        if not result.subject_label or len(result.subject_label) > 256:
            raise ServiceInvestigationError("subject_label is malformed")
        if tuple(item.profile for item in result.diagnostics) != PROFILES:
            raise ServiceInvestigationError("profile must bind systemd then HTTP exactly once")
        if len({item.node_id for item in result.diagnostics}) != 2:
            raise ServiceInvestigationError("diagnostics must bind distinct PlanNodes")
        return result

    @classmethod
    def load(cls, path: Path) -> "ServiceInvestigationProfileV1":
        raw = path.read_bytes()
        if len(raw) > MAX_OWNER_OUTPUT:
            raise ServiceInvestigationError("service investigation profile is oversized")
        return cls.from_data(json.loads(raw))

    def to_data(self) -> dict[str, Any]:
        return {
            "audience": self.audience,
            "diagnostics": [item.to_data() for item in self.diagnostics],
            "profile_id": self.profile_id,
            "schema": self.schema,
            "subject": self.subject,
            "subject_label": self.subject_label,
        }


@dataclass(frozen=True)
class CompiledServiceInvestigationV1:
    investigation_id: str
    draft_id: str
    revision_id: str
    plan_digest: str
    profile: ServiceInvestigationProfileV1
    handoff_digest: str
    schema: str = HANDOFF_SCHEMA

    def unsigned_data(self) -> dict[str, Any]:
        return {
            "draft_id": self.draft_id,
            "investigation_id": self.investigation_id,
            "plan_digest": self.plan_digest,
            "profile": self.profile.to_data(),
            "revision_id": self.revision_id,
            "schema": self.schema,
        }

    def to_data(self) -> dict[str, Any]:
        return {**self.unsigned_data(), "handoff_digest": self.handoff_digest}


def compile_service_investigation(
    revision: DraftRevisionV1, profile: ServiceInvestigationProfileV1
) -> CompiledServiceInvestigationV1:
    nodes = {item.node_id: item for item in revision.document.nodes}
    for binding in profile.diagnostics:
        node = nodes.get(binding.node_id)
        if node is None:
            raise ServiceInvestigationError(
                f"diagnostic binding references absent PlanNode {binding.node_id}"
            )
        if node.work is not None and (node.work.commands or node.work.write_paths):
            raise ServiceInvestigationError(
                f"diagnostic PlanNode {binding.node_id} must not encode target mutation"
            )
    seed = {
        "draft_id": revision.draft_id,
        "plan_digest": revision.plan_digest,
        "profile_id": profile.profile_id,
        "revision_id": revision.revision_id,
        "schema": "maude.service-investigation-identity/v1",
    }
    investigation_id = content_digest(canonical_json_bytes(seed))
    partial = CompiledServiceInvestigationV1(
        investigation_id,
        revision.draft_id,
        revision.revision_id,
        revision.plan_digest,
        profile,
        "",
    )
    return CompiledServiceInvestigationV1(
        investigation_id,
        revision.draft_id,
        revision.revision_id,
        revision.plan_digest,
        profile,
        content_digest(canonical_json_bytes(partial.unsigned_data())),
    )


@dataclass(frozen=True)
class SubmissionReceiptV1:
    investigation_id: str
    handoff_digest: str
    plan_digest: str
    revision_id: str
    run_id: str
    state: str
    inspector_path: str
    receipt_path: str
    schema: str = SUBMISSION_SCHEMA

    @classmethod
    def from_data(cls, raw: dict[str, Any]) -> "SubmissionReceiptV1":
        names = {"schema", "investigation_id", "handoff_digest", "plan_digest", "revision_id", "run_id", "state", "inspector_path", "receipt_path"}
        _closed(raw, names, "Nightshift submission receipt")
        if raw["schema"] != SUBMISSION_SCHEMA or raw["state"] != "accepted":
            raise ServiceInvestigationError("Nightshift did not accept the handoff")
        result = cls(**{name: raw[name] for name in names})
        _digest(result.investigation_id, "investigation_id")
        _digest(result.handoff_digest, "handoff_digest")
        _digest(result.plan_digest, "plan_digest")
        _token(result.run_id, "run_id")
        if not result.inspector_path.startswith("/phosphor-ng/investigations/"):
            raise ServiceInvestigationError("submission inspector path is outside the investigation surface")
        if not result.receipt_path.startswith("/"):
            raise ServiceInvestigationError("submission receipt path must be absolute")
        return result

    def to_data(self) -> dict[str, str]:
        return self.__dict__.copy()


class ServiceInvestigationLedger:
    """Maude-owned idempotent handoff intent; Nightshift remains lifecycle owner."""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.artifacts = path.with_name(path.stem + "-artifacts")
        self.artifacts.mkdir(mode=0o700, exist_ok=True)
        with sqlite3.connect(path) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            db.execute("INSERT OR IGNORE INTO meta VALUES ('schema', ?)", (LEDGER_SCHEMA,))
            db.execute("""CREATE TABLE IF NOT EXISTS handoffs (
                investigation_id TEXT PRIMARY KEY, handoff BLOB NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('dispatching','accepted','indeterminate')),
                receipt BLOB, error TEXT)""")

    @staticmethod
    def _owner_receipt(
        compiled: CompiledServiceInvestigationV1,
        command: tuple[str, ...],
        artifact: Path,
    ) -> SubmissionReceiptV1:
        if not command or not Path(command[0]).is_absolute():
            raise ServiceInvestigationError("Nightshift submission program must be an absolute configured path")
        process = subprocess.run(
            [*command, "--handoff", str(artifact)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if len(process.stdout) > MAX_OWNER_OUTPUT or len(process.stderr) > MAX_OWNER_OUTPUT:
            raise ServiceInvestigationError("Nightshift submission response is oversized")
        if process.returncode != 0:
            raise ServiceInvestigationError(
                "Nightshift submission refused: "
                + process.stderr.decode("utf-8", "replace")
            )
        receipt = SubmissionReceiptV1.from_data(json.loads(process.stdout))
        if (
            receipt.investigation_id != compiled.investigation_id
            or receipt.handoff_digest != compiled.handoff_digest
            or receipt.plan_digest != compiled.plan_digest
            or receipt.revision_id != compiled.revision_id
        ):
            raise ServiceInvestigationError(
                "Nightshift receipt does not bind the exact Maude handoff"
            )
        return receipt

    def submit(self, compiled: CompiledServiceInvestigationV1, command: tuple[str, ...]) -> SubmissionReceiptV1:
        handoff = canonical_json_bytes(compiled.to_data())
        artifact = self.artifacts / f"{compiled.investigation_id[7:]}.handoff.json"
        try:
            fd = os.open(artifact, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(handoff)
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError:
            if artifact.read_bytes() != handoff:
                raise ServiceInvestigationError("existing handoff artifact has different bytes")
        with sqlite3.connect(self.path) as db:
            try:
                db.execute("INSERT INTO handoffs VALUES (?, ?, 'dispatching', NULL, NULL)", (compiled.investigation_id, handoff))
                db.commit()
            except sqlite3.IntegrityError as exc:
                row = db.execute("SELECT state, receipt FROM handoffs WHERE investigation_id=?", (compiled.investigation_id,)).fetchone()
                if row and row[0] == "accepted":
                    return SubmissionReceiptV1.from_data(json.loads(row[1]))
                raise ServiceInvestigationError(
                    "handoff already dispatched; reconcile its Nightshift run instead of reacquiring"
                ) from exc
        try:
            receipt = self._owner_receipt(compiled, command, artifact)
        except Exception as exc:
            with sqlite3.connect(self.path) as db:
                db.execute("UPDATE handoffs SET state='indeterminate', error=? WHERE investigation_id=?", (str(exc), compiled.investigation_id))
            raise
        raw = canonical_json_bytes(receipt.to_data())
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE handoffs SET state='accepted', receipt=?, error=NULL WHERE investigation_id=? AND state='dispatching'", (raw, compiled.investigation_id))
        return receipt

    def reconcile(
        self,
        compiled: CompiledServiceInvestigationV1,
        command: tuple[str, ...],
    ) -> SubmissionReceiptV1:
        artifact = self.artifacts / f"{compiled.investigation_id[7:]}.handoff.json"
        with sqlite3.connect(self.path) as db:
            row = db.execute(
                "SELECT handoff, state, receipt FROM handoffs WHERE investigation_id=?",
                (compiled.investigation_id,),
            ).fetchone()
        if row is None:
            raise ServiceInvestigationError("no prior handoff to reconcile")
        if row[1] == "accepted":
            return SubmissionReceiptV1.from_data(json.loads(row[2]))
        if row[1] != "indeterminate" or row[0] != canonical_json_bytes(compiled.to_data()):
            raise ServiceInvestigationError("only the exact indeterminate handoff may be reconciled")
        receipt = self._owner_receipt(compiled, command, artifact)
        with sqlite3.connect(self.path) as db:
            db.execute(
                "UPDATE handoffs SET state='accepted', receipt=?, error=NULL WHERE investigation_id=? AND state='indeterminate'",
                (canonical_json_bytes(receipt.to_data()), compiled.investigation_id),
            )
        return receipt

    def projection(self, investigation_id: str) -> dict[str, Any] | None:
        with sqlite3.connect(f"file:{self.path}?mode=ro", uri=True) as db:
            row = db.execute("SELECT handoff, state, receipt, error FROM handoffs WHERE investigation_id=?", (investigation_id,)).fetchone()
        if row is None:
            return None
        return {
            "error": row[3],
            "handoff": json.loads(row[0]),
            "receipt": None if row[2] is None else json.loads(row[2]),
            "schema": "maude.service-investigation-projection/v1",
            "state": row[1],
        }

    def projections(self) -> tuple[dict[str, Any], ...]:
        with sqlite3.connect(f"file:{self.path}?mode=ro", uri=True) as db:
            ids = [row[0] for row in db.execute("SELECT investigation_id FROM handoffs ORDER BY rowid DESC")]
        return tuple(item for key in ids if (item := self.projection(key)) is not None)
