# SPDX-License-Identifier: Apache-2.0
"""Presentation-only state for the local PlanDocument workbench.

This store is intentionally separate from Plan Core's semantic SQLite store.
Its records may become stale or orphaned; they can never alter semantic bytes.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from maude.plan.document import PlanDocumentV1, canonical_json_bytes, content_digest

PLAN_PRESENTATION_V1_SCHEMA = "maude.plan-presentation/v1"
PLAN_PRESENTATION_SCHEMA = "maude.plan-presentation/v2"
PRESENTATION_STORE_SCHEMA = "maude.plan-presentation-store/v1"
DETAIL_TABS = frozenset({"node", "document", "raw"})
CASEWORK_TABS = frozenset(
    {"findings", "checks", "diff", "proposals", "receipts", "history"}
)
SELECTED_OBJECT_KINDS = frozenset(
    {"document", "node", "finding", "proposal", "diff", "receipt", "revision"}
)


class PresentationError(ValueError):
    pass


class PresentationConflict(RuntimeError):
    pass


def _strings(value: Any, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise PresentationError(f"{where} must be an array of strings")
    return tuple(value)


@dataclass(frozen=True)
class PlanPresentationV2:
    draft_id: str
    semantic_revision_id: str
    selected_node_id: str | None = None
    collapsed_node_ids: tuple[str, ...] = ()
    outline_percent: int = 36
    active_detail_tab: str = "node"
    active_casework_tab: str = "findings"
    selected_object_kind: str = "document"
    selected_object_id: str | None = None
    version: int = 1
    schema: str = PLAN_PRESENTATION_SCHEMA

    def __post_init__(self) -> None:
        if not self.draft_id or not self.semantic_revision_id:
            raise PresentationError(
                "presentation requires exact draft/revision identity"
            )
        if not 22 <= self.outline_percent <= 60:
            raise PresentationError("outline_percent must be between 22 and 60")
        if self.active_detail_tab not in DETAIL_TABS:
            raise PresentationError("unsupported presentation detail tab")
        if self.active_casework_tab not in CASEWORK_TABS:
            raise PresentationError("unsupported presentation casework tab")
        if self.selected_object_kind not in SELECTED_OBJECT_KINDS:
            raise PresentationError("unsupported selected object kind")
        if self.selected_object_kind == "document":
            if self.selected_object_id is not None:
                raise PresentationError("document selection must not have an object ID")
        elif not self.selected_object_id:
            raise PresentationError("selected object kind requires an exact object ID")
        if self.selected_object_kind == "node" and (
            self.selected_node_id != self.selected_object_id
        ):
            raise PresentationError(
                "selected node and selected object identities must agree"
            )
        if self.version < 0:
            raise PresentationError("presentation version must not be negative")

    def semantic_data(self) -> dict[str, Any]:
        """Return sidecar bytes. These are never included in PlanDocument."""
        return {
            "active_detail_tab": self.active_detail_tab,
            "active_casework_tab": self.active_casework_tab,
            "collapsed_node_ids": list(self.collapsed_node_ids),
            "draft_id": self.draft_id,
            "outline_percent": self.outline_percent,
            "schema": self.schema,
            "selected_node_id": self.selected_node_id,
            "selected_object_id": self.selected_object_id,
            "selected_object_kind": self.selected_object_kind,
            "semantic_revision_id": self.semantic_revision_id,
            "version": self.version,
        }

    @property
    def presentation_digest(self) -> str:
        return content_digest(canonical_json_bytes(self.semantic_data()))

    @classmethod
    def from_data(cls, value: Any) -> PlanPresentationV2:
        if not isinstance(value, dict):
            raise PresentationError("presentation must be an object")
        raw: Mapping[str, Any] = value
        expected_v1 = {
            "active_detail_tab",
            "collapsed_node_ids",
            "draft_id",
            "outline_percent",
            "schema",
            "selected_node_id",
            "semantic_revision_id",
            "version",
        }
        expected_v2 = expected_v1 | {
            "active_casework_tab",
            "selected_object_id",
            "selected_object_kind",
        }
        schema = raw.get("schema")
        if schema == PLAN_PRESENTATION_V1_SCHEMA and set(raw) == expected_v1:
            selected = raw.get("selected_node_id")
            raw = {
                **raw,
                "active_casework_tab": "findings",
                "schema": PLAN_PRESENTATION_SCHEMA,
                "selected_object_id": selected,
                "selected_object_kind": "node" if selected else "document",
            }
        elif schema != PLAN_PRESENTATION_SCHEMA or set(raw) != expected_v2:
            raise PresentationError("unsupported presentation schema")
        selected = raw.get("selected_node_id")
        if selected is not None and not isinstance(selected, str):
            raise PresentationError("selected_node_id must be a string or null")
        if not isinstance(raw.get("outline_percent"), int) or isinstance(
            raw.get("outline_percent"), bool
        ):
            raise PresentationError("outline_percent must be an integer")
        if not isinstance(raw.get("version"), int) or isinstance(
            raw.get("version"), bool
        ):
            raise PresentationError("version must be an integer")
        if not isinstance(raw.get("draft_id"), str) or not isinstance(
            raw.get("semantic_revision_id"), str
        ):
            raise PresentationError(
                "presentation draft/revision identities must be strings"
            )
        if not isinstance(raw.get("active_detail_tab"), str):
            raise PresentationError("active_detail_tab must be a string")
        if not isinstance(raw.get("active_casework_tab"), str):
            raise PresentationError("active_casework_tab must be a string")
        if not isinstance(raw.get("selected_object_kind"), str):
            raise PresentationError("selected_object_kind must be a string")
        object_id = raw.get("selected_object_id")
        if object_id is not None and not isinstance(object_id, str):
            raise PresentationError("selected_object_id must be a string or null")
        return cls(
            draft_id=raw["draft_id"],
            semantic_revision_id=raw["semantic_revision_id"],
            selected_node_id=selected,
            collapsed_node_ids=_strings(
                raw.get("collapsed_node_ids"), "collapsed_node_ids"
            ),
            outline_percent=raw["outline_percent"],
            active_detail_tab=raw["active_detail_tab"],
            active_casework_tab=raw["active_casework_tab"],
            selected_object_kind=raw["selected_object_kind"],
            selected_object_id=object_id,
            version=raw["version"],
        )


@dataclass(frozen=True)
class PresentationProjectionV2:
    presentation: PlanPresentationV2
    stale_revision: bool
    orphaned_node_ids: tuple[str, ...]

    def to_data(self) -> dict[str, Any]:
        return {
            "orphaned_node_ids": list(self.orphaned_node_ids),
            "presentation": self.presentation.semantic_data(),
            "schema": "maude.plan-presentation-projection/v2",
            "stale_revision": self.stale_revision,
        }


def project_presentation(
    presentation: PlanPresentationV2, document: PlanDocumentV1, revision_id: str
) -> PresentationProjectionV2:
    known = {node.node_id for node in document.nodes}
    references = set(presentation.collapsed_node_ids)
    if presentation.selected_node_id is not None:
        references.add(presentation.selected_node_id)
    return PresentationProjectionV2(
        presentation,
        presentation.semantic_revision_id != revision_id,
        tuple(sorted(references - known)),
    )


class PresentationStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS presentation_meta(schema TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS presentations(
                    draft_id TEXT PRIMARY KEY,
                    version INTEGER NOT NULL,
                    record BLOB NOT NULL
                );
                """
            )
            db.execute(
                "INSERT OR IGNORE INTO presentation_meta(schema) VALUES (?)",
                (PRESENTATION_STORE_SCHEMA,),
            )
            schemas = [
                row[0] for row in db.execute("SELECT schema FROM presentation_meta")
            ]
            if schemas != [PRESENTATION_STORE_SCHEMA]:
                raise PresentationError(
                    f"unsupported presentation store schemas: {schemas}"
                )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def load(self, draft_id: str) -> PlanPresentationV2 | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT version,record FROM presentations WHERE draft_id=?", (draft_id,)
            ).fetchone()
        if row is None:
            return None
        presentation = PlanPresentationV2.from_data(json.loads(bytes(row["record"])))
        if presentation.draft_id != draft_id or presentation.version != row["version"]:
            raise PresentationError("presentation persistence binding is contradictory")
        return presentation

    def save(
        self, presentation: PlanPresentationV2, *, expected_version: int | None
    ) -> PlanPresentationV2:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT version,record FROM presentations WHERE draft_id=?",
                (presentation.draft_id,),
            ).fetchone()
            actual = None if row is None else row["version"]
            if row is not None:
                current = PlanPresentationV2.from_data(json.loads(bytes(row["record"])))
                if (
                    actual == expected_version
                    and current.semantic_revision_id
                    == presentation.semantic_revision_id
                    and current.selected_node_id == presentation.selected_node_id
                    and current.collapsed_node_ids == presentation.collapsed_node_ids
                    and current.outline_percent == presentation.outline_percent
                    and current.active_detail_tab == presentation.active_detail_tab
                    and current.active_casework_tab == presentation.active_casework_tab
                    and current.selected_object_kind
                    == presentation.selected_object_kind
                    and current.selected_object_id == presentation.selected_object_id
                ):
                    return current
            if actual != expected_version:
                raise PresentationConflict(
                    f"expected presentation version {expected_version}, found {actual}"
                )
            next_record = PlanPresentationV2(
                draft_id=presentation.draft_id,
                semantic_revision_id=presentation.semantic_revision_id,
                selected_node_id=presentation.selected_node_id,
                collapsed_node_ids=presentation.collapsed_node_ids,
                outline_percent=presentation.outline_percent,
                active_detail_tab=presentation.active_detail_tab,
                active_casework_tab=presentation.active_casework_tab,
                selected_object_kind=presentation.selected_object_kind,
                selected_object_id=presentation.selected_object_id,
                version=1 if actual is None else actual + 1,
            )
            db.execute(
                "INSERT INTO presentations(draft_id,version,record) VALUES (?,?,?) "
                "ON CONFLICT(draft_id) DO UPDATE SET version=excluded.version,record=excluded.record",
                (
                    next_record.draft_id,
                    next_record.version,
                    canonical_json_bytes(next_record.semantic_data()),
                ),
            )
        return next_record
