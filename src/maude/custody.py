# SPDX-License-Identifier: Apache-2.0
"""Authority-neutral custody for Maude -> Nightshift authoring handoffs.

The TUI records an immutable exact session/plan receipt after the canonical
``runtime.session.create`` response.  This module's narrow CLI can later seal
that receipt to one already-sealed Nightshift base request.  It never invokes
Nightshift, AG, or Docket and carries no standing or authorization material.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import hmac
import json
import os
import sqlite3
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SESSION_SCHEMA_V1 = "maude.supervised_session_custody.v1"
HANDOFF_SCHEMA_V1 = "nightshift.maude_authoring_context_handoff.v1"
AUTHORING_INPUT_SCHEMA_V1 = "nightshift.maude_authoring_context_input.v1"
AUTH_SCHEMA_V1 = "maude.hmac_sha256.v1"
SESSION_AUTH_DOMAIN = b"maude-supervised-session-custody/v1\0"
HANDOFF_AUTH_DOMAIN = b"nightshift-authoring-context-handoff/v1\0"
MAX_PLAN_BYTES = 1024 * 1024
MAX_REQUEST_BYTES = 16 * 1024 * 1024


class CustodyError(ValueError):
    """Fail-closed custody validation or persistence refusal."""


@dataclass(frozen=True)
class SessionCustodyProfileV1:
    store: Path
    key_file: Path
    session_issuer_principal_id: str
    session_issuer_key_id: str

    def validate(self) -> None:
        _token("session issuer principal", self.session_issuer_principal_id)
        _token("session issuer key ID", self.session_issuer_key_id)


@dataclass(frozen=True)
class HandoffProducerProfileV1:
    store: Path
    key_file: Path
    producer_principal_id: str
    producer_key_id: str
    session_issuer_principal_id: str
    session_issuer_key_id: str

    def validate(self) -> None:
        _token("producer principal", self.producer_principal_id)
        _token("producer key ID", self.producer_key_id)
        _token("session issuer principal", self.session_issuer_principal_id)
        _token("session issuer key ID", self.session_issuer_key_id)
        if self.producer_key_id == self.session_issuer_key_id:
            raise CustodyError(
                "handoff producer and session issuer key identities must be distinct"
            )


def _token(name: str, value: object) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise CustodyError(f"{name} must be a non-empty token")
    if any(character.isspace() for character in value):
        raise CustodyError(f"{name} must be a non-empty token")
    return value


def _digest(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        raise CustodyError(f"{name} must use sha256:<64 lowercase hex>")
    tail = value.removeprefix("sha256:")
    if len(tail) != 64 or any(c not in "0123456789abcdef" for c in tail):
        raise CustodyError(f"{name} must use sha256:<64 lowercase hex>")
    return value


def _now() -> str:
    return (
        dt.datetime.now(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _canonical(value: object) -> bytes:
    # Every custody schema field is a string/integer/object with finite JSON
    # numbers. This is byte-identical to JCS for the closed schema and avoids a
    # dependency solely for canonical object-key ordering.
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _semantic_id(value: dict[str, Any], field: str) -> str:
    preimage = dict(value)
    preimage.pop(field, None)
    preimage.pop("authentication", None)
    return _sha256(_canonical(preimage))


def _authentication_preimage(value: dict[str, Any]) -> bytes:
    preimage = dict(value)
    preimage.pop("authentication", None)
    return _canonical(preimage)


def _tag(key: bytes, domain: bytes, value: dict[str, Any]) -> str:
    return (
        "hmac-sha256:"
        + hmac.new(
            key, domain + _authentication_preimage(value), hashlib.sha256
        ).hexdigest()
    )


def read_protected_key(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise CustodyError(
            f"cannot open Maude custody credential {path}: {error}"
        ) from error
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise CustodyError("Maude custody credential is not a regular file")
        if metadata.st_mode & 0o077:
            raise CustodyError(
                "Maude custody credential must not be accessible by group or others"
            )
        value = os.read(descriptor, 33)
        if len(value) != 32:
            raise CustodyError(
                "Maude custody credential must contain exactly 32 raw bytes"
            )
        return value
    finally:
        os.close(descriptor)


def _validate_store_path(path: Path, *, must_exist: bool) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        if must_exist:
            raise CustodyError("Maude supervised-session custody store does not exist")
        return
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise CustodyError("Maude custody store must be a non-symlink regular file")
    if hasattr(os, "geteuid") and metadata.st_uid != os.geteuid():
        raise CustodyError(
            "Maude custody store is not owned by the current service principal"
        )
    if metadata.st_mode & 0o027:
        raise CustodyError(
            "Maude custody store must not be group-writable/executable or accessible by others"
        )


def _strict_json(data: bytes, name: str) -> dict[str, Any]:
    try:
        text = data.decode("utf-8")
        decoder = json.JSONDecoder()
        value, end = decoder.raw_decode(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CustodyError(f"malformed {name}: {error}") from error
    if text[end:].strip():
        raise CustodyError(f"malformed {name}: trailing data")
    if not isinstance(value, dict):
        raise CustodyError(f"malformed {name}: expected an object")
    return value


def _read_exact_file(path: Path, maximum: int, name: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise CustodyError(f"cannot open exact {name} {path}: {error}") from error
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise CustodyError(f"exact {name} is not a regular file")
        if metadata.st_size > maximum:
            raise CustodyError(f"exact {name} exceeds {maximum} bytes")
        chunks: list[bytes] = []
        remaining = maximum + 1
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        value = b"".join(chunks)
        if len(value) > maximum:
            raise CustodyError(f"exact {name} exceeds {maximum} bytes")
        return value
    finally:
        os.close(descriptor)


def _timestamp(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise CustodyError(f"{name} must be an RFC3339 UTC timestamp")
    try:
        parsed = dt.datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as error:
        raise CustodyError(f"{name} must be an RFC3339 UTC timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() != dt.timedelta(0):
        raise CustodyError(f"{name} must be an RFC3339 UTC timestamp")
    return value


def _validate_authentication(
    value: dict[str, Any], key: bytes, domain: bytes, key_id: str
) -> None:
    authentication = value.get("authentication")
    if not isinstance(authentication, dict):
        raise CustodyError("custody authentication is absent")
    if set(authentication) != {"schema", "key_id", "tag"}:
        raise CustodyError("custody authentication has unknown or missing fields")
    if authentication["schema"] != AUTH_SCHEMA_V1:
        raise CustodyError("unsupported custody authentication schema")
    if authentication["key_id"] != key_id:
        raise CustodyError("custody authentication key identity mismatch")
    expected = _tag(key, domain, value)
    if not hmac.compare_digest(str(authentication["tag"]), expected):
        raise CustodyError("custody authentication failed")


def _validate_session_record_structure(
    value: dict[str, Any], issuer_principal_id: str, issuer_key_id: str
) -> None:
    expected_fields = {
        "schema",
        "session_record_id",
        "session_issuer_principal_id",
        "session_issuer_key_id",
        "maude_session_id",
        "maude_plan_ref",
        "source_plan_bytes",
        "recorded_at",
        "authentication",
    }
    if set(value) != expected_fields or value["schema"] != SESSION_SCHEMA_V1:
        raise CustodyError("malformed or unsupported supervised-session custody record")
    if value["session_issuer_principal_id"] != issuer_principal_id:
        raise CustodyError("session custody issuer principal mismatch")
    if value["session_issuer_key_id"] != issuer_key_id:
        raise CustodyError("session custody issuer key mismatch")
    _token("Maude session ID", value["maude_session_id"])
    _digest("Maude plan ref", value["maude_plan_ref"])
    _digest("session record ID", value["session_record_id"])
    length = value["source_plan_bytes"]
    if (
        not isinstance(length, int)
        or isinstance(length, bool)
        or not 1 <= length <= MAX_PLAN_BYTES
    ):
        raise CustodyError("session custody source plan length is invalid")
    _timestamp("session custody recorded_at", value["recorded_at"])
    if value["session_record_id"] != _semantic_id(value, "session_record_id"):
        raise CustodyError("session record identity does not bind exact custody facts")
    authentication = value.get("authentication")
    if not isinstance(authentication, dict) or set(authentication) != {
        "schema",
        "key_id",
        "tag",
    }:
        raise CustodyError("session custody authentication is malformed")
    if authentication.get("schema") != AUTH_SCHEMA_V1:
        raise CustodyError("unsupported session custody authentication schema")
    if authentication.get("key_id") != issuer_key_id:
        raise CustodyError("session custody authentication key identity mismatch")
    tag = authentication.get("tag")
    if (
        not isinstance(tag, str)
        or not tag.startswith("hmac-sha256:")
        or len(tag) != len("hmac-sha256:") + 64
        or any(
            character not in "0123456789abcdef"
            for character in tag.removeprefix("hmac-sha256:")
        )
    ):
        raise CustodyError("session custody authentication tag is malformed")


def _validate_session_record(
    value: dict[str, Any], key: bytes, profile: SessionCustodyProfileV1
) -> None:
    _validate_session_record_structure(
        value,
        profile.session_issuer_principal_id,
        profile.session_issuer_key_id,
    )
    _validate_authentication(
        value, key, SESSION_AUTH_DOMAIN, profile.session_issuer_key_id
    )


def _validate_handoff(
    value: dict[str, Any], key: bytes, profile: HandoffProducerProfileV1
) -> None:
    expected_fields = {
        "schema",
        "handoff_id",
        "producer_principal_id",
        "producer_key_id",
        "target_runtime_id",
        "target_request_id",
        "session_custody",
        "authoring_context",
        "created_at",
        "authentication",
    }
    if set(value) != expected_fields or value["schema"] != HANDOFF_SCHEMA_V1:
        raise CustodyError("malformed or unsupported authoring-context handoff")
    if value["producer_principal_id"] != profile.producer_principal_id:
        raise CustodyError("handoff producer principal mismatch")
    if value["producer_key_id"] != profile.producer_key_id:
        raise CustodyError("handoff producer key mismatch")
    _token("target Nightshift runtime ID", value["target_runtime_id"])
    _digest("target request ID", value["target_request_id"])
    _digest("handoff ID", value["handoff_id"])
    _timestamp("handoff created_at", value["created_at"])
    session = value["session_custody"]
    context = value["authoring_context"]
    if not isinstance(session, dict) or not isinstance(context, dict):
        raise CustodyError("handoff session/context binding is malformed")
    _validate_session_record_structure(
        session,
        profile.session_issuer_principal_id,
        profile.session_issuer_key_id,
    )
    if set(context) != {"schema", "plan_ref", "session_id", "plan_text"}:
        raise CustodyError("handoff authoring context has unknown or missing fields")
    if context["schema"] != AUTHORING_INPUT_SCHEMA_V1:
        raise CustodyError("unsupported authoring-context input schema")
    _token("Maude session ID", context["session_id"])
    _digest("Maude plan ref", context["plan_ref"])
    if not isinstance(context["plan_text"], str):
        raise CustodyError("Maude plan text must be UTF-8 text")
    plan_bytes = context["plan_text"].encode("utf-8")
    if not 1 <= len(plan_bytes) <= MAX_PLAN_BYTES:
        raise CustodyError("Maude plan must contain 1..=1048576 UTF-8 bytes")
    if context["plan_ref"] != _sha256(plan_bytes):
        raise CustodyError("Maude plan ref does not bind the exact plan bytes")
    if (
        session["maude_session_id"] != context["session_id"]
        or session["maude_plan_ref"] != context["plan_ref"]
        or session["source_plan_bytes"] != len(plan_bytes)
    ):
        raise CustodyError(
            "handoff does not bind its exact supervised session and plan"
        )
    if value["handoff_id"] != _semantic_id(value, "handoff_id"):
        raise CustodyError("handoff identity does not bind the exact custody facts")
    _validate_authentication(value, key, HANDOFF_AUTH_DOMAIN, profile.producer_key_id)


class MaudeCustodyStoreV1:
    """Append-only session and handoff custody facts."""

    def __init__(self, profile: SessionCustodyProfileV1) -> None:
        profile.validate()
        self.profile = profile
        parent = profile.store.parent
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        _validate_store_path(profile.store, must_exist=False)
        if not profile.store.exists():
            try:
                descriptor = os.open(
                    profile.store,
                    os.O_RDWR
                    | os.O_CREAT
                    | os.O_EXCL
                    | getattr(os, "O_CLOEXEC", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                )
            except FileExistsError:
                _validate_store_path(profile.store, must_exist=True)
            else:
                os.close(descriptor)
        self.connection = sqlite3.connect(profile.store, timeout=5.0)
        os.chmod(profile.store, 0o600)
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS supervised_session_custody (
                session_id TEXT PRIMARY KEY,
                plan_ref TEXT NOT NULL,
                session_record_id TEXT NOT NULL UNIQUE,
                record_json TEXT NOT NULL
            ) STRICT;
            CREATE TABLE IF NOT EXISTS authoring_handoffs (
                target_request_id TEXT PRIMARY KEY,
                handoff_id TEXT NOT NULL UNIQUE,
                session_id TEXT NOT NULL,
                plan_ref TEXT NOT NULL,
                record_json TEXT NOT NULL,
                UNIQUE(session_id, plan_ref),
                FOREIGN KEY(session_id) REFERENCES supervised_session_custody(session_id)
            ) STRICT;
            """
        )

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "MaudeCustodyStoreV1":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def record_session(
        self,
        session_id: str,
        plan_bytes: bytes,
        *,
        recorded_at: str | None = None,
    ) -> dict[str, Any]:
        _token("Maude session ID", session_id)
        if not 1 <= len(plan_bytes) <= MAX_PLAN_BYTES:
            raise CustodyError("Maude plan must contain 1..=1048576 UTF-8 bytes")
        try:
            plan_bytes.decode("utf-8")
        except UnicodeDecodeError as error:
            raise CustodyError("Maude plan bytes are not UTF-8") from error
        key = read_protected_key(self.profile.key_file)
        plan_ref = _sha256(plan_bytes)
        existing = self.connection.execute(
            "SELECT plan_ref, record_json FROM supervised_session_custody WHERE session_id=?",
            (session_id,),
        ).fetchone()
        if existing:
            if existing[0] != plan_ref:
                raise CustodyError(
                    "Maude session is already bound to a different exact plan"
                )
            value = json.loads(existing[1])
            _validate_session_record(value, key, self.profile)
            return value
        value: dict[str, Any] = {
            "schema": SESSION_SCHEMA_V1,
            "session_record_id": "",
            "session_issuer_principal_id": self.profile.session_issuer_principal_id,
            "session_issuer_key_id": self.profile.session_issuer_key_id,
            "maude_session_id": session_id,
            "maude_plan_ref": plan_ref,
            "source_plan_bytes": len(plan_bytes),
            "recorded_at": recorded_at or _now(),
            "authentication": {
                "schema": AUTH_SCHEMA_V1,
                "key_id": self.profile.session_issuer_key_id,
                "tag": "",
            },
        }
        value["session_record_id"] = _semantic_id(value, "session_record_id")
        value["authentication"]["tag"] = _tag(key, SESSION_AUTH_DOMAIN, value)
        _validate_session_record(value, key, self.profile)
        encoded = _canonical(value).decode("utf-8")
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            current = self.connection.execute(
                "SELECT plan_ref, record_json FROM supervised_session_custody WHERE session_id=?",
                (session_id,),
            ).fetchone()
            if current:
                if current[0] != plan_ref:
                    raise CustodyError(
                        "Maude session is concurrently bound to a different exact plan"
                    )
                self.connection.rollback()
                return json.loads(current[1])
            self.connection.execute(
                "INSERT INTO supervised_session_custody "
                "(session_id, plan_ref, session_record_id, record_json) VALUES (?, ?, ?, ?)",
                (session_id, plan_ref, value["session_record_id"], encoded),
            )
            self.connection.commit()
        except Exception:
            if self.connection.in_transaction:
                self.connection.rollback()
            raise
        return value

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT record_json FROM supervised_session_custody WHERE session_id=?",
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        value = json.loads(row[0])
        _validate_session_record(
            value, read_protected_key(self.profile.key_file), self.profile
        )
        return value


class MaudeHandoffStoreV1:
    """Append-only handoffs over existing supervisor-minted session receipts.

    This process has only the handoff producer credential. It can carry and
    bind a session receipt, but cannot authenticate or mint that receipt.
    Nightshift independently verifies the nested session issuer credential.
    """

    def __init__(self, profile: HandoffProducerProfileV1) -> None:
        profile.validate()
        self.profile = profile
        _validate_store_path(profile.store, must_exist=True)
        self.connection = sqlite3.connect(profile.store, timeout=5.0)
        self.connection.execute("PRAGMA foreign_keys=ON")

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "MaudeHandoffStoreV1":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT record_json FROM supervised_session_custody WHERE session_id=?",
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        value = json.loads(row[0])
        _validate_session_record_structure(
            value,
            self.profile.session_issuer_principal_id,
            self.profile.session_issuer_key_id,
        )
        return value

    def seal_handoff(
        self,
        session_id: str,
        plan_bytes: bytes,
        target_request_id: str,
        target_runtime_id: str,
        *,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        _digest("target request ID", target_request_id)
        _token("target Nightshift runtime ID", target_runtime_id)
        session = self.get_session(session_id)
        if session is None:
            raise CustodyError("Maude session has no canonical custody record")
        try:
            plan_text = plan_bytes.decode("utf-8")
        except UnicodeDecodeError as error:
            raise CustodyError("Maude plan bytes are not UTF-8") from error
        plan_ref = _sha256(plan_bytes)
        if session["maude_plan_ref"] != plan_ref or session["source_plan_bytes"] != len(
            plan_bytes
        ):
            raise CustodyError("exact plan bytes do not match the supervised session")
        key = read_protected_key(self.profile.key_file)
        existing = self.connection.execute(
            "SELECT session_id, plan_ref, record_json FROM authoring_handoffs "
            "WHERE target_request_id=? OR (session_id=? AND plan_ref=?)",
            (target_request_id, session_id, plan_ref),
        ).fetchone()
        if existing:
            value = json.loads(existing[2])
            if (
                existing[0] != session_id
                or existing[1] != plan_ref
                or value.get("target_request_id") != target_request_id
                or value.get("target_runtime_id") != target_runtime_id
            ):
                raise CustodyError("conflicting authoring handoff already exists")
            _validate_authentication(
                value, key, HANDOFF_AUTH_DOMAIN, self.profile.producer_key_id
            )
            _validate_handoff(value, key, self.profile)
            return value
        value: dict[str, Any] = {
            "schema": HANDOFF_SCHEMA_V1,
            "handoff_id": "",
            "producer_principal_id": self.profile.producer_principal_id,
            "producer_key_id": self.profile.producer_key_id,
            "target_runtime_id": target_runtime_id,
            "target_request_id": target_request_id,
            "session_custody": session,
            "authoring_context": {
                "schema": AUTHORING_INPUT_SCHEMA_V1,
                "plan_ref": plan_ref,
                "session_id": session_id,
                "plan_text": plan_text,
            },
            "created_at": created_at or _now(),
            "authentication": {
                "schema": AUTH_SCHEMA_V1,
                "key_id": self.profile.producer_key_id,
                "tag": "",
            },
        }
        value["handoff_id"] = _semantic_id(value, "handoff_id")
        value["authentication"]["tag"] = _tag(key, HANDOFF_AUTH_DOMAIN, value)
        _validate_handoff(value, key, self.profile)
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            conflict = self.connection.execute(
                "SELECT session_id, plan_ref, record_json FROM authoring_handoffs "
                "WHERE target_request_id=? OR (session_id=? AND plan_ref=?)",
                (target_request_id, session_id, plan_ref),
            ).fetchone()
            if conflict:
                self.connection.rollback()
                prior = json.loads(conflict[2])
                if (
                    conflict[0] == session_id
                    and conflict[1] == plan_ref
                    and prior.get("target_request_id") == target_request_id
                    and prior.get("target_runtime_id") == target_runtime_id
                ):
                    _validate_handoff(prior, key, self.profile)
                    return prior
                raise CustodyError("concurrent conflicting authoring handoff refused")
            self.connection.execute(
                "INSERT INTO authoring_handoffs "
                "(target_request_id, handoff_id, session_id, plan_ref, record_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    target_request_id,
                    value["handoff_id"],
                    session_id,
                    plan_ref,
                    _canonical(value).decode("utf-8"),
                ),
            )
            self.connection.commit()
        except Exception:
            if self.connection.in_transaction:
                self.connection.rollback()
            raise
        return value


def record_supervised_session_if_configured(
    settings: object, session_id: str, plan_bytes: bytes
) -> dict[str, Any] | None:
    configuration_reader = getattr(settings, "custody_configuration", None)
    if not callable(configuration_reader):
        return None
    configuration = configuration_reader()
    if configuration is None:
        return None
    store, key, principal, key_id = configuration
    profile = SessionCustodyProfileV1(Path(store), Path(key), principal, key_id)
    with MaudeCustodyStoreV1(profile) as custody:
        return custody.record_session(session_id, plan_bytes)


def _profile_from_args(args: argparse.Namespace) -> HandoffProducerProfileV1:
    return HandoffProducerProfileV1(
        Path(args.store),
        Path(args.key_file),
        args.producer_principal_id,
        args.producer_key_id,
        args.session_issuer_principal_id,
        args.session_issuer_key_id,
    )


def _write_output(value: dict[str, Any], path: str | None) -> None:
    encoded = _canonical(value) + b"\n"
    if path is None or path == "-":
        sys.stdout.buffer.write(encoded)
        return
    target = Path(path)
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        view = memoryview(encoded)
        while view:
            written = os.write(descriptor, view)
            if written == 0:
                raise CustodyError("short write while persisting exact handoff")
            view = view[written:]
        os.fsync(descriptor)
    except Exception:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise
    finally:
        os.close(descriptor)
    os.replace(temporary, target)
    directory = os.open(target.parent, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seal one authority-neutral Maude authoring handoff for Nightshift"
    )
    parser.add_argument("--store", default=os.environ.get("MAUDE_CUSTODY_STORE", ""))
    parser.add_argument(
        "--key-file", default=os.environ.get("MAUDE_HANDOFF_PRODUCER_KEY_FILE", "")
    )
    parser.add_argument(
        "--producer-principal-id",
        default=os.environ.get("MAUDE_CUSTODY_PRODUCER_PRINCIPAL_ID", ""),
    )
    parser.add_argument(
        "--producer-key-id",
        default=os.environ.get("MAUDE_CUSTODY_PRODUCER_KEY_ID", ""),
    )
    parser.add_argument(
        "--session-issuer-principal-id",
        default=os.environ.get("MAUDE_SESSION_ISSUER_PRINCIPAL_ID", ""),
    )
    parser.add_argument(
        "--session-issuer-key-id",
        default=os.environ.get("MAUDE_SESSION_ISSUER_KEY_ID", ""),
    )
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--nightshift-request", required=True)
    parser.add_argument("--target-runtime-id", required=True)
    parser.add_argument("--out", default="-")
    args = parser.parse_args()
    try:
        if not all(
            (
                args.store,
                args.key_file,
                args.producer_principal_id,
                args.producer_key_id,
                args.session_issuer_principal_id,
                args.session_issuer_key_id,
            )
        ):
            raise CustodyError("complete Maude custody configuration is required")
        request = _strict_json(
            _read_exact_file(
                Path(args.nightshift_request), MAX_REQUEST_BYTES, "Nightshift request"
            ),
            "Nightshift request",
        )
        if request.get("schema") != "nightshift.canonical_cycle_request.v1":
            raise CustodyError("unsupported Nightshift cycle request schema")
        if request.get("authoring_context") is not None:
            raise CustodyError("Nightshift request already contains authoring context")
        target_request_id = _digest("Nightshift request ID", request.get("request_id"))
        profile = _profile_from_args(args)
        with MaudeHandoffStoreV1(profile) as custody:
            handoff = custody.seal_handoff(
                args.session_id,
                _read_exact_file(Path(args.plan), MAX_PLAN_BYTES, "Maude plan"),
                target_request_id,
                args.target_runtime_id,
            )
        _write_output(handoff, args.out)
    except (CustodyError, OSError, sqlite3.Error) as error:
        parser.exit(2, f"maude-authoring-handoff: {error}\n")


if __name__ == "__main__":
    main()
