# SPDX-License-Identifier: Apache-2.0
"""Bounded authored-objective projection; neither assessment nor public export."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time

from maude.plan.document import PlanDocumentV1, PLAN_DOCUMENT_SCHEMA

SCHEMA = "maude.objective-source/v1"
MAX_DOCUMENT_BYTES = 1024 * 1024
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


def condition_id(plan_digest: str, index: int, text: str) -> str:
    """Index distinguishes repeated criteria within one exact authored revision."""
    raw = json.dumps({"plan_digest": plan_digest, "index": index, "text": text},
                     sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def read_objective(path: Path, expected_digest: str) -> dict:
    """Read one regular file without opening a store or following a final symlink.

    The expected content identity is the join key. The capture clock is not a
    currentness verdict, and a successful read says nothing about completion.
    Authored prose is operator-only even though operational locators are omitted.
    """
    base = {"schema": SCHEMA, "source": "maude", "publication": "operator_only",
            "captured_at_unix_ms": time.time_ns() // 1_000_000,
            "plan_schema": PLAN_DOCUMENT_SCHEMA, "plan_digest": expected_digest}

    def absent(code, availability="unavailable"):
        return {**base, "availability": availability, "error_code": code}

    if not DIGEST.fullmatch(expected_digest):
        return absent("invalid_expected_digest")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                return absent("not_regular_file")
            if before.st_size > MAX_DOCUMENT_BYTES:
                return absent("document_too_large")
            raw = stream.read(MAX_DOCUMENT_BYTES + 1)
            after = os.fstat(stream.fileno())
            if len(raw) > MAX_DOCUMENT_BYTES:
                return absent("document_too_large")
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                    after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                return absent("source_changed", "conflicting")
    except FileNotFoundError:
        return absent("missing")
    except OSError:
        return absent("unreadable")
    try:
        document = PlanDocumentV1.from_data(json.loads(raw, object_pairs_hook=_unique_object))
    except (ValueError, TypeError, UnicodeError):
        return absent("invalid_document")
    if document.digest != expected_digest:
        return absent("plan_digest_mismatch", "conflicting")
    return {**base, "availability": "available", "goal": document.goal,
            "acceptance_criteria": [
                {"condition_id": condition_id(expected_digest, index, text), "text": text}
                for index, text in enumerate(document.acceptance_criteria)]}
