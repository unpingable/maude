#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Deterministic, synthetic Agent Governor RPC surface for operator UX evals.

This is evaluation infrastructure, not a second implementation of Governor.
It speaks the real Content-Length framed JSON-RPC transport and returns the
canonical response shapes consumed by the Maude client.  All behavior comes
from a frozen JSON scenario file.  It never invokes a model, a network service,
or a production system.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import difflib
import hashlib
import json
import os
import signal
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCHEMA = "maude.synthetic-runtime.v1"
DEFAULT_AT = "2026-07-26T00:00:00Z"

# Frozen authority-critical contract.  These values and the helpers below
# mirror Agent Governor commit 485e55783f9e359965e3b736e1d610c4568d45f1;
# campaign execution deliberately does not import a mutable sibling checkout.
AG_AUTHORITY_CONTRACT_COMMIT = "485e55783f9e359965e3b736e1d610c4568d45f1"
APPROVAL_WITNESS_VERSION = "approval-witness/v1"
AUTHORIZING_DECISION = "approve"
EXECUTION_GRANT_DERIVATION_VERSION = "execution-grant/v1"
EXECUTION_GRANT_ENFORCEMENT = "declared-effects-only"
MAX_PLAN_BYTES = 1 << 20
MAX_WITNESS_BYTES = 1 << 16
_SHA256_PREFIX = "sha256:"


class RPCFault(Exception):
    """A scripted JSON-RPC error."""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = int(code)
        self.message = str(message)
        self.data = data


class DisconnectAfterDispatch(Exception):
    """Scripted transport loss after receipt of a request, before any reply."""


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def _canonical_json_bytes(value: Any) -> bytes:
    """AG gate-receipt canonical JSON used by execution-grant derivation."""
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def _sha256_ref(data: bytes) -> str:
    return _SHA256_PREFIX + hashlib.sha256(data).hexdigest()


def _normalize_sha256(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    candidate = value.strip().lower()
    if candidate.startswith(_SHA256_PREFIX):
        candidate = candidate[len(_SHA256_PREFIX) :]
    if len(candidate) != 64 or any(c not in "0123456789abcdef" for c in candidate):
        return ""
    return _SHA256_PREFIX + candidate


def _evidence_bytes(value: Any, field: str) -> bytes:
    if isinstance(value, str):
        return value.encode("utf-8")
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value)
    raise ValueError(f"{field} must be exact UTF-8/bytes evidence")


def _verify_approval_binding(
    *,
    plan_bytes: Any,
    witness_bytes: Any,
    source_plan_digest: Any,
    approval_witness_digest: Any,
) -> tuple[str, str]:
    """Frozen seam-B verifier matching AG 485e557's authority checks."""
    plan = _evidence_bytes(plan_bytes, "plan_bytes")
    witness_raw = _evidence_bytes(witness_bytes, "witness_bytes")
    if not plan:
        raise ValueError("plan_bytes absent/empty")
    if not witness_raw:
        raise ValueError("witness_bytes absent/empty")
    if len(plan) > MAX_PLAN_BYTES:
        raise ValueError(f"plan_bytes exceeds {MAX_PLAN_BYTES} bytes")
    if len(witness_raw) > MAX_WITNESS_BYTES:
        raise ValueError(f"witness_bytes exceeds {MAX_WITNESS_BYTES} bytes")

    actual_witness_digest = _sha256_ref(witness_raw)
    claimed_witness_digest = _normalize_sha256(approval_witness_digest)
    if not claimed_witness_digest or claimed_witness_digest != actual_witness_digest:
        raise ValueError(
            "approval_witness_digest does not match exact witness_bytes"
        )
    try:
        witness = json.loads(witness_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("witness_bytes must be a UTF-8 JSON object") from exc
    if not isinstance(witness, dict):
        raise ValueError("approval witness must be a JSON object")
    version = witness.get("witness_version")
    decision = witness.get("decision")
    witness_plan_ref = witness.get("plan_ref")
    if not all(
        isinstance(field, str)
        for field in (version, decision, witness_plan_ref)
    ):
        raise ValueError(
            "approval witness requires string witness_version, decision, and plan_ref"
        )
    if version != APPROVAL_WITNESS_VERSION:
        raise ValueError(f"unknown approval witness version: {version!r}")
    if decision != AUTHORIZING_DECISION:
        raise ValueError(f"approval witness decision does not authorize: {decision!r}")

    actual_plan_ref = _sha256_ref(plan)
    claimed_plan_ref = _normalize_sha256(source_plan_digest)
    normalized_witness_plan_ref = _normalize_sha256(witness_plan_ref)
    if not (
        claimed_plan_ref
        and normalized_witness_plan_ref
        and claimed_plan_ref == actual_plan_ref == normalized_witness_plan_ref
    ):
        raise ValueError(
            "approval witness does not bind the exact plan_bytes "
            "(source_plan_digest == sha256(plan_bytes) == witness.plan_ref required)"
        )
    return actual_plan_ref, actual_witness_digest


def _derive_execution_grant(execution_request: Any) -> dict[str, Any]:
    """Frozen canonical grant identity derivation matching AG 485e557."""
    if not isinstance(execution_request, dict):
        raise ValueError("execution_request must be an object")
    try:
        write_paths = frozenset(
            str(path) for path in execution_request.get("write_paths", [])
        )
        commands = tuple(
            (
                str(command["program"]),
                tuple(str(arg) for arg in command.get("argv_prefix", [])),
            )
            for command in execution_request.get("commands", [])
        )
    except (KeyError, TypeError) as exc:
        raise ValueError(f"malformed execution_request: {exc}") from exc
    source_plan_digest = str(execution_request.get("source_plan_digest", ""))
    approval_witness_digest = str(
        execution_request.get("approval_witness_digest", "")
    )
    horizon = str(execution_request.get("horizon", "run"))
    if not source_plan_digest or not approval_witness_digest:
        raise ValueError(
            "activation requires source_plan_digest and approval_witness_digest"
        )
    if horizon not in {"run", "session"}:
        raise ValueError(f"unknown execution-grant horizon: {horizon!r}")

    commands_json = [
        {"program": program, "argv_prefix": list(argv_prefix)}
        for program, argv_prefix in sorted(commands, key=lambda item: (item[0], item[1]))
    ]
    body = {
        "derivation_version": EXECUTION_GRANT_DERIVATION_VERSION,
        "source_plan_digest": source_plan_digest,
        "approval_witness_digest": approval_witness_digest,
        "horizon": horizon,
        "enforcement": EXECUTION_GRANT_ENFORCEMENT,
        "write_paths": sorted(write_paths),
        "commands": commands_json,
        "network": "denied",
        "git": "denied",
        "secrets": "denied",
        "privilege": "denied",
    }
    digest_hex = hashlib.sha256(_canonical_json_bytes(body)).hexdigest()
    unmet_axes = [
        axis
        for axis, requested in (
            ("network", bool(execution_request.get("network_requested", False))),
            ("git", bool(execution_request.get("git_requested", False))),
        )
        if requested
    ]
    return {
        "grant_id": f"sgr_{digest_hex[:12]}",
        "grant_digest": f"sha256:{digest_hex}",
        "derivation_version": EXECUTION_GRANT_DERIVATION_VERSION,
        "source_plan_digest": source_plan_digest,
        "approval_witness_digest": approval_witness_digest,
        "enforcement": EXECUTION_GRANT_ENFORCEMENT,
        "horizon": horizon,
        "write_paths": sorted(write_paths),
        "commands": commands_json,
        "unmet_axes": unmet_axes,
    }


def _validate_configured_grant(configured: dict[str, Any], derived: dict[str, Any]) -> None:
    """Refuse fixture drift instead of returning a plausible synthetic grant."""
    for field in (
        "grant_id",
        "grant_digest",
        "derivation_version",
        "source_plan_digest",
        "approval_witness_digest",
        "enforcement",
        "horizon",
        "write_paths",
        "commands",
        "unmet_axes",
    ):
        if configured.get(field) != derived[field]:
            raise ValueError(
                f"synthetic grant fixture mismatch for {field}: "
                f"configured {configured.get(field)!r}, derived {derived[field]!r}"
            )


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_bytes(_json_bytes(value) + b"\n")
    os.replace(tmp, path)


def _append_jsonl(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(
            json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        )
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _file_bytes(value: Any) -> bytes | None:
    """Decode a frozen file value.

    Strings are UTF-8 text.  ``null`` means absent.  An object may contain
    ``text`` or ``base64``; the latter is useful for byte fixtures.
    """

    if value is None:
        return None
    if isinstance(value, str):
        return value.encode("utf-8")
    if isinstance(value, dict):
        if set(value) == {"text"} and isinstance(value["text"], str):
            return value["text"].encode("utf-8")
        if set(value) == {"base64"} and isinstance(value["base64"], str):
            return base64.b64decode(value["base64"], validate=True)
    raise ValueError("file values must be UTF-8 strings, null, {text}, or {base64}")


def _workspace_parts(config: dict[str, Any]) -> tuple[Path, dict, dict]:
    workspace = config.get("workspace")
    if isinstance(workspace, str):
        root = Path(workspace)
        base_files = config.get("base_files") or {}
    elif isinstance(workspace, dict):
        root = Path(str(workspace.get("path") or ""))
        base_files = workspace.get("base_files") or {}
    else:
        raise ValueError("workspace must be an absolute path or an object with path")
    if not root.is_absolute():
        raise ValueError("workspace path must be absolute")
    candidate = config.get("candidate") or {}
    result_files = candidate.get("result_files")
    if result_files is None:
        result_files = config.get("result_files") or {}
    if not isinstance(base_files, dict) or not isinstance(result_files, dict):
        raise ValueError("base_files and candidate.result_files must be objects")
    return root.resolve(), base_files, result_files


def _safe_target(root: Path, rel: str) -> Path:
    if not isinstance(rel, str) or not rel or Path(rel).is_absolute():
        raise ValueError(f"fixture path must be non-empty and relative: {rel!r}")
    target = (root / rel).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"fixture path escapes workspace: {rel!r}") from exc
    return target


def _apply_file_map(
    root: Path,
    files: dict[str, Any],
    *,
    remove_paths: set[str] | None = None,
) -> None:
    for rel in sorted(remove_paths or set()):
        target = _safe_target(root, rel)
        if target.is_file() or target.is_symlink():
            target.unlink()
    for rel, encoded in sorted(files.items()):
        target = _safe_target(root, rel)
        data = _file_bytes(encoded)
        if data is None:
            if target.is_file() or target.is_symlink():
                target.unlink()
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def _canonical_event(
    raw: dict[str, Any],
    *,
    session_id: str,
    index: int,
    backend_kind: str,
) -> dict[str, Any]:
    """Fill required canonical envelope fields without moving payload fields."""

    if not isinstance(raw, dict):
        raise ValueError("events must be JSON objects")
    payload = raw.get("payload")
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ValueError("event.payload must be an object")
    return {
        "event_id": str(raw.get("event_id") or f"evt-synthetic-{index:04d}"),
        "session_id": str(raw.get("session_id") or session_id),
        "seq": int(raw.get("seq", index)),
        "at": str(raw.get("at") or DEFAULT_AT),
        "kind": str(raw.get("kind") or "runtime_protocol_error"),
        "source_layer": str(raw.get("source_layer") or "supervisor"),
        "backend_kind": str(raw.get("backend_kind") or backend_kind),
        "correlation_id": raw.get("correlation_id"),
        "parent_event_id": raw.get("parent_event_id"),
        "receipt_ids": list(raw.get("receipt_ids") or []),
        "payload": payload,
        "lane": raw.get("lane"),
    }


def _session_defaults(raw: dict[str, Any], *, index: int = 1) -> dict[str, Any]:
    sid = str(raw.get("session_id") or f"run-synthetic-{index:03d}")
    return {
        "session_id": sid,
        "backend_kind": str(raw.get("backend_kind") or "claude_code"),
        "cwd": str(raw.get("cwd") or ""),
        "status": str(raw.get("status") or "created"),
        "pid": raw.get("pid"),
        "task": raw.get("task"),
        "started_at": raw.get("started_at"),
        "updated_at": raw.get("updated_at") or DEFAULT_AT,
        "exit_code": raw.get("exit_code"),
        "parent_session_id": raw.get("parent_session_id"),
        "pending_interventions": int(raw.get("pending_interventions") or 0),
        "capabilities": raw.get("capabilities"),
        "input_capable": bool(raw.get("input_capable", False)),
        "lane": raw.get("lane") or "ungoverned",
    }


@dataclass
class RuntimePaths:
    config: Path
    socket: Path
    state_dir: Path
    trace: Path

    @property
    def state(self) -> Path:
        return self.state_dir / "state.json"

    @property
    def ready(self) -> Path:
        return self.state_dir / "runtime-ready.json"


class SyntheticRuntime:
    def __init__(self, config: dict[str, Any], paths: RuntimePaths) -> None:
        if config.get("schema") != SCHEMA:
            raise ValueError(f"runtime config schema must be {SCHEMA!r}")
        contract = config.get("authority_contract")
        if contract is not None:
            expected_contract = {
                "agent_gov_commit": AG_AUTHORITY_CONTRACT_COMMIT,
                "approval_witness_version": APPROVAL_WITNESS_VERSION,
                "execution_grant_derivation_version": EXECUTION_GRANT_DERIVATION_VERSION,
            }
            if contract != expected_contract:
                raise ValueError(
                    "runtime authority_contract does not match the frozen "
                    f"Agent Governor contract: {expected_contract!r}"
                )
        self.config = config
        self.paths = paths
        self.workspace, self.base_files, self.result_files = _workspace_parts(config)
        self.candidate = {
            **(config.get("promotion") or {}),
            **(config.get("candidate") or {}),
        }
        self.runtime_cfg = config.get("runtime") or {}
        self.create_cfg = config.get("create") or {}
        self.launch_cfg = config.get("launch") or {}
        self.grant_cfg = config.get("grant") or {}
        self.approval_binding_cfg = config.get("approval_binding")
        self.governor_cfg = config.get("governor") or {}
        self._lock = asyncio.Lock()
        self._connection_seq = 0
        self._trace_seq = 0
        self.state = self._load_or_initialize()

    # ------------------------------------------------------------------
    # State and fixture custody
    # ------------------------------------------------------------------

    def _load_or_initialize(self) -> dict[str, Any]:
        self.paths.state_dir.mkdir(parents=True, exist_ok=True)
        self.workspace.mkdir(parents=True, exist_ok=True)
        if self.paths.state.is_file():
            state = json.loads(self.paths.state.read_text(encoding="utf-8"))
            state["daemon_starts"] = int(state.get("daemon_starts", 0)) + 1
            _atomic_json(self.paths.state, state)
            return state

        _apply_file_map(
            self.workspace,
            self.base_files,
            remove_paths=set(self.result_files) - set(self.base_files),
        )
        initial_sessions = []
        for index, raw in enumerate(self.config.get("initial_sessions") or [], 1):
            if not isinstance(raw, dict):
                raise ValueError("initial_sessions entries must be objects")
            session = _session_defaults(raw, index=index)
            if not session["cwd"]:
                session["cwd"] = str(self.workspace)
            initial_sessions.append(session)

        raw_interventions = self.config.get("interventions")
        if raw_interventions is None and self.config.get("intervention") is not None:
            raw_interventions = [self.config["intervention"]]
        interventions = list(raw_interventions or [])
        for item in interventions:
            if not isinstance(item, dict):
                raise ValueError("interventions must be objects")

        state = {
            "schema": "maude.synthetic-runtime.state.v1",
            "scenario_id": self.config.get("scenario_id"),
            "daemon_starts": 1,
            "chat_sessions": [],
            "runtime_sessions": initial_sessions,
            "next_runtime_session": len(initial_sessions) + 1,
            "pending_interventions": interventions,
            "intervention_decisions": [],
            "dynamic_events": [],
            "candidate_session_id": (
                str(self.candidate.get("session_id"))
                if self.candidate.get("session_id")
                else (initial_sessions[0]["session_id"] if initial_sessions else None)
            ),
            "promotion_status": (
                str(self.candidate.get("status") or "pending")
                if self.candidate
                else None
            ),
            "candidate_staged": bool(
                self.candidate.get("staged", bool(initial_sessions))
            ),
            "promotion_decision": None,
            "grant_by_session": {},
        }
        initial_state = self.config.get("initial_state") or {}
        if not isinstance(initial_state, dict):
            raise ValueError("initial_state must be an object")
        for key in (
            "runtime_sessions",
            "next_runtime_session",
            "pending_interventions",
            "intervention_decisions",
            "dynamic_events",
            "candidate_session_id",
            "promotion_status",
            "candidate_staged",
            "promotion_decision",
            "grant_by_session",
        ):
            if key in initial_state:
                state[key] = initial_state[key]
        if state.get("candidate_staged"):
            self._stage_candidate(state=state)
        _atomic_json(self.paths.state, state)
        return state

    def _save(self) -> None:
        _atomic_json(self.paths.state, self.state)

    def _runtime_sessions(self) -> list[dict[str, Any]]:
        return self.state["runtime_sessions"]

    def _find_session(self, session_id: str) -> dict[str, Any] | None:
        for session in self._runtime_sessions():
            if session.get("session_id") == session_id:
                return session
        return None

    def _candidate_changed_files(self) -> list[str]:
        explicit = self.candidate.get("changed_files")
        if explicit is not None:
            return [str(item) for item in explicit]
        changed = []
        for rel in sorted(set(self.base_files) | set(self.result_files)):
            if _file_bytes(self.base_files.get(rel)) != _file_bytes(self.result_files.get(rel)):
                changed.append(rel)
        return changed

    def _candidate_diff(self) -> str:
        explicit = self.candidate.get("diff_fixture")
        if explicit is None:
            explicit = self.candidate.get("diff")
        if explicit is not None:
            return str(explicit)
        chunks: list[str] = []
        for rel in self._candidate_changed_files():
            before = _file_bytes(self.base_files.get(rel))
            after = _file_bytes(self.result_files.get(rel))
            before_text = (before or b"").decode("utf-8", errors="replace").splitlines(True)
            after_text = (after or b"").decode("utf-8", errors="replace").splitlines(True)
            chunks.extend(
                difflib.unified_diff(
                    before_text,
                    after_text,
                    fromfile=f"a/{rel}",
                    tofile=f"b/{rel}",
                )
            )
        return "".join(chunks)

    def _stage_candidate(self, *, state: dict[str, Any] | None = None) -> None:
        """Materialize scripted worker output before promotion review."""

        if not self.candidate:
            return
        _apply_file_map(
            self.workspace,
            self.result_files,
            remove_paths={
                rel for rel, value in self.result_files.items() if value is None
            },
        )
        (state if state is not None else self.state)["candidate_staged"] = True

    def _promotion(self, session_id: str) -> dict[str, Any] | None:
        if not self.candidate:
            return None
        if not self.state.get("candidate_staged"):
            return None
        if self.state.get("candidate_session_id") not in (None, session_id):
            return None
        if self.state.get("promotion_status") != "pending":
            return None
        changed = self._candidate_changed_files()
        return {
            "promotion_id": str(
                self.candidate.get("promotion_id") or "promotion-synthetic-001"
            ),
            "session_id": session_id,
            "created_at": str(self.candidate.get("created_at") or DEFAULT_AT),
            "status": "pending",
            "repo_path": str(self.workspace),
            "changed_files": changed,
            "diff_stat": str(
                self.candidate.get("diff_stat") or f"{len(changed)} file(s) changed"
            ),
            "decision_at": None,
            "decision_reason": None,
            "excluded_files": list(self.candidate.get("excluded_files") or []),
        }

    def _append_dynamic_event(
        self, session_id: str, kind: str, source_layer: str, payload: dict[str, Any]
    ) -> None:
        current = self._events_for(session_id)
        next_seq = max((int(e["seq"]) for e in current), default=-1) + 1
        session = self._find_session(session_id) or {}
        event = _canonical_event(
            {
                "kind": kind,
                "source_layer": source_layer,
                "payload": payload,
                "at": DEFAULT_AT,
            },
            session_id=session_id,
            index=next_seq,
            backend_kind=str(session.get("backend_kind") or "claude_code"),
        )
        self.state["dynamic_events"].append(event)

    def _events_for(self, session_id: str) -> list[dict[str, Any]]:
        session = self._find_session(session_id) or {}
        backend = str(session.get("backend_kind") or "claude_code")
        configured = [
            _canonical_event(raw, session_id=session_id, index=index, backend_kind=backend)
            for index, raw in enumerate(self.config.get("events") or [])
            if not raw.get("session_id") or raw.get("session_id") == session_id
        ]
        dynamic = [
            event
            for event in self.state.get("dynamic_events") or []
            if event.get("session_id") == session_id
        ]
        return sorted(configured + dynamic, key=lambda event: int(event.get("seq", 0)))

    # ------------------------------------------------------------------
    # Trace and framing
    # ------------------------------------------------------------------

    def _trace(
        self,
        *,
        connection_id: int,
        direction: str,
        body: bytes,
        frame: dict[str, Any],
    ) -> None:
        self._trace_seq += 1
        _append_jsonl(
            self.paths.trace,
            {
                "seq": self._trace_seq,
                "at": DEFAULT_AT,
                "connection_id": connection_id,
                "direction": direction,
                "body_sha256": hashlib.sha256(body).hexdigest(),
                "body_base64": base64.b64encode(body).decode("ascii"),
                "frame": frame,
            },
        )

    async def serve_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self._connection_seq += 1
        connection_id = self._connection_seq
        try:
            while True:
                body = await self._read_body(reader)
                if body is None:
                    return
                try:
                    request = json.loads(body.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    response = self._error_response(None, -32700, "Parse error")
                    await self._write_response(writer, connection_id, response)
                    continue
                self._trace(
                    connection_id=connection_id,
                    direction="request",
                    body=body,
                    frame=request,
                )
                try:
                    response = await self._handle_request(request)
                except DisconnectAfterDispatch:
                    # Deliberately no response frame. Closing the socket is the
                    # observable evidence; do not invent a terminal result.
                    return
                await self._write_response(writer, connection_id, response)
        except (ConnectionError, asyncio.IncompleteReadError):
            return
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    @staticmethod
    async def _read_body(reader: asyncio.StreamReader) -> bytes | None:
        length: int | None = None
        while True:
            line = await reader.readline()
            if not line:
                return None
            if line in (b"\r\n", b"\n"):
                break
            try:
                key, value = line.decode("ascii").split(":", 1)
            except (UnicodeDecodeError, ValueError):
                continue
            if key.strip().lower() == "content-length":
                length = int(value.strip())
        if length is None or length < 0:
            return None
        return await reader.readexactly(length)

    async def _write_response(
        self,
        writer: asyncio.StreamWriter,
        connection_id: int,
        response: dict[str, Any],
    ) -> None:
        body = _json_bytes(response)
        self._trace(
            connection_id=connection_id,
            direction="response",
            body=body,
            frame=response,
        )
        writer.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body)
        try:
            await writer.drain()
        except (ConnectionError, BrokenPipeError):
            # A scripted timeout deliberately leaves a poisoned client behind.
            pass

    @staticmethod
    def _error_response(
        request_id: Any, code: int, message: str, data: Any = None
    ) -> dict[str, Any]:
        error: dict[str, Any] = {"code": int(code), "message": str(message)}
        if data is not None:
            error["data"] = data
        return {"jsonrpc": "2.0", "id": request_id, "error": error}

    async def _handle_request(self, request: Any) -> dict[str, Any]:
        if not isinstance(request, dict):
            return self._error_response(None, -32600, "Invalid Request")
        request_id = request.get("id")
        method = request.get("method")
        params = request.get("params") or {}
        if request.get("jsonrpc") != "2.0" or not isinstance(method, str):
            return self._error_response(request_id, -32600, "Invalid Request")
        if not isinstance(params, dict):
            return self._error_response(request_id, -32602, "Invalid params")
        try:
            async with self._lock:
                result = await self.dispatch(method, params)
                self._save()
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except RPCFault as exc:
            return self._error_response(request_id, exc.code, exc.message, exc.data)
        except DisconnectAfterDispatch:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            return self._error_response(request_id, -32602, str(exc))
        except Exception as exc:
            return self._error_response(
                request_id, -32603, "Synthetic runtime internal error", str(exc)
            )

    # ------------------------------------------------------------------
    # RPC behavior
    # ------------------------------------------------------------------

    def _scripted_fault(self, name: str) -> RPCFault:
        faults = self.config.get("faults") or {}
        section = getattr(self, f"{name}_cfg", {})
        raw = (
            faults.get(name)
            or section.get("error")
            or section.get("refusal")
            or self.runtime_cfg.get(f"{name}_error")
            or {}
        )
        return RPCFault(
            int(raw.get("code", -32040)),
            str(raw.get("message") or f"synthetic {name} refusal"),
            raw.get("data"),
        )

    async def dispatch(self, method: str, params: dict[str, Any]) -> Any:
        method_faults = (self.config.get("faults") or {}).get("methods") or {}
        if method in method_faults:
            raw = method_faults[method] or {}
            raise RPCFault(
                int(raw.get("code", -32040)),
                str(raw.get("message") or "scripted method refusal"),
                raw.get("data"),
            )

        if method == "governor.hello":
            backend = self.governor_cfg.get("backend") or {
                "type": "synthetic",
                "connected": True,
            }
            return {
                "protocol_version": "1.0",
                "capabilities": {
                    "chat": False,
                    "streaming": False,
                    "fix_mode": "candidate_only",
                    "sessions": True,
                    "intent": False,
                    "receipts": True,
                    "scars": True,
                    "commit": True,
                    "signals_preflight": False,
                    "backend": backend,
                },
                "governor": {
                    "context_id": str(
                        self.governor_cfg.get("context_id") or "synthetic-lab"
                    ),
                    "mode": str(self.governor_cfg.get("mode") or "code"),
                    "initialized": bool(
                        self.governor_cfg.get("initialized", True)
                    ),
                    "session_id": "synthetic-daemon-session",
                },
                "session": {
                    "session_id": "synthetic-daemon-session",
                    "principal": None,
                    "principal_ref": None,
                    "auth_method": "local",
                    "session_token": None,
                },
                "standing": {
                    "required": False,
                    "secret_configured": False,
                    "audience": "synthetic",
                },
            }

        if method == "governor.now":
            return {
                "pill": str(self.governor_cfg.get("pill") or "OK"),
                "sentence": str(
                    self.governor_cfg.get("sentence") or "Synthetic governor is running."
                ),
                **(
                    {"regime": self.governor_cfg["regime"]}
                    if self.governor_cfg.get("regime") is not None
                    else {}
                ),
            }

        if method == "governor.status":
            return {
                "mode": str(self.governor_cfg.get("mode") or "code"),
                "envelope": str(self.governor_cfg.get("envelope") or "synthetic"),
                "context_id": str(
                    self.governor_cfg.get("context_id") or "synthetic-lab"
                ),
                "facts_count": int(self.governor_cfg.get("facts_count") or 0),
                "decisions_count": int(
                    self.governor_cfg.get("decisions_count") or 0
                ),
                "violations_count": int(
                    self.governor_cfg.get("violations_count") or 0
                ),
                "schema_version": "v2",
            }

        if method == "governor.methods":
            names = sorted(self._supported_methods())
            mutating = {
                "sessions.create",
                "sessions.delete",
                "runtime.session.create",
                "runtime.session.launch",
                "runtime.session.pause",
                "runtime.session.resume",
                "runtime.session.kill",
                "runtime.session.fork",
                "runtime.session.send_input",
                "runtime.intervention.resolve",
                "runtime.promotion.resolve",
                "runtime.grant.activate",
                "operator.decisions.resolve",
            }
            return {
                "methods": [
                    {
                        "method": name,
                        "classification": "mutating" if name in mutating else "read_only",
                    }
                    for name in names
                ],
                "count": len(names),
            }

        if method == "sessions.list":
            return list(self.state["chat_sessions"])

        if method == "sessions.create":
            index = len(self.state["chat_sessions"]) + 1
            capsule = {
                "metadata": {
                    "session_id": f"chat-synthetic-{index:03d}",
                    "context_id": str(
                        self.governor_cfg.get("context_id") or "synthetic-lab"
                    ),
                    "name": str(params.get("title") or "Untitled"),
                    "created_at": DEFAULT_AT,
                    "updated_at": DEFAULT_AT,
                }
            }
            self.state["chat_sessions"].insert(0, capsule)
            return capsule

        if method == "sessions.get":
            session_id = params["id"]
            for capsule in self.state["chat_sessions"]:
                if capsule.get("metadata", {}).get("session_id") == session_id:
                    return capsule
            return None

        if method == "sessions.delete":
            session_id = params["id"]
            before = len(self.state["chat_sessions"])
            self.state["chat_sessions"] = [
                item
                for item in self.state["chat_sessions"]
                if item.get("metadata", {}).get("session_id") != session_id
            ]
            return {"success": len(self.state["chat_sessions"]) != before}

        if method == "runtime.session.create":
            create_behavior = str(
                self.create_cfg.get("behavior")
                or self.runtime_cfg.get("behavior")
                or "normal"
            )
            if create_behavior in ("create_refusal", "refusal", "error"):
                raise self._scripted_fault("create")
            index = int(self.state["next_runtime_session"])
            template = dict(self.runtime_cfg.get("session") or {})
            template.update(self.create_cfg.get("session") or {})
            template.update(
                {
                    "session_id": self.create_cfg.get("session_id")
                    or template.get("session_id")
                    or f"run-synthetic-{index:03d}",
                    "backend_kind": params.get(
                        "backend_kind", template.get("backend_kind", "claude_code")
                    ),
                    "cwd": params.get("cwd") or str(self.workspace),
                    "status": template.get("created_status") or "created",
                    "task": params.get("task"),
                }
            )
            session = _session_defaults(template, index=index)
            self._runtime_sessions().append(session)
            self.state["next_runtime_session"] = index + 1
            if self.state.get("candidate_session_id") is None and self.candidate:
                self.state["candidate_session_id"] = session["session_id"]
            return {
                "session_id": session["session_id"],
                "backend_kind": session["backend_kind"],
                "cwd": session["cwd"],
                "status": session["status"],
                "task": session["task"],
            }

        if method == "runtime.session.launch":
            session = self._required_session(params["session_id"])
            specific_behavior = (
                self.launch_cfg.get("kind") or self.launch_cfg.get("behavior")
            )
            general_behavior = self.runtime_cfg.get("behavior")
            # Generated fixtures carry `launch.behavior: normal` for response
            # defaults while using runtime.behavior for timeout/refusal mode.
            if specific_behavior in (None, "normal") and general_behavior not in (
                None,
                "normal",
                "initial_state",
            ):
                behavior = str(general_behavior)
            else:
                behavior = str(specific_behavior or general_behavior or "normal")
            if behavior in ("disconnect", "disconnect_after_dispatch"):
                raise DisconnectAfterDispatch()
            if behavior in ("launch_refusal", "refusal", "error"):
                raise self._scripted_fault("launch")
            if behavior == "timeout":
                # The caller loses the terminal response. Preserve only a
                # non-terminal observed state; never invent a terminal verdict.
                session["status"] = "running"
                session["pid"] = self.launch_cfg.get("pid")
                session["started_at"] = session.get("started_at") or DEFAULT_AT
                session["updated_at"] = DEFAULT_AT
                delay = float(
                    self.launch_cfg.get(
                        "timeout_seconds",
                        self.runtime_cfg.get("timeout_seconds", 12.0),
                    )
                )
                await asyncio.sleep(max(0.0, min(delay, 30.0)))
                return {
                    "session_id": session["session_id"],
                    "status": session["status"],
                    "pid": session.get("pid"),
                }
            launch_status = (
                self.launch_cfg.get("status")
                or self.launch_cfg.get("launch_status")
                or (self.runtime_cfg.get("session") or {}).get("launch_status")
                or self.runtime_cfg.get("launch_status")
            )
            if not launch_status:
                if self.state["pending_interventions"]:
                    launch_status = "waiting_tool_decision"
                else:
                    launch_status = "exited"
            session["status"] = str(launch_status)
            session["pid"] = self.launch_cfg.get(
                "pid",
                (self.runtime_cfg.get("session") or {}).get(
                    "pid", self.runtime_cfg.get("pid", 41001)
                ),
            )
            session["started_at"] = session.get("started_at") or DEFAULT_AT
            session["updated_at"] = DEFAULT_AT
            configured_exit = self.launch_cfg.get("exit_code")
            if configured_exit is None:
                configured_exit = (self.runtime_cfg.get("session") or {}).get(
                    "exit_code"
                )
            if configured_exit is None:
                configured_exit = self.runtime_cfg.get("exit_code")
            if configured_exit is not None:
                session["exit_code"] = int(configured_exit)
            session["pending_interventions"] = len(self.state["pending_interventions"])
            if self.candidate and not self.state["pending_interventions"]:
                self._stage_candidate()
            return {
                "session_id": session["session_id"],
                "status": session["status"],
                "pid": session["pid"],
            }

        if method == "runtime.session.get":
            session = self._find_session(params["session_id"])
            if session is None:
                return None
            return {
                "session_id": session["session_id"],
                "backend_kind": session["backend_kind"],
                "cwd": session["cwd"],
                "status": session["status"],
                "pid": session.get("pid"),
                "task": session.get("task"),
                "started_at": session.get("started_at"),
                "updated_at": session.get("updated_at"),
                "exit_code": session.get("exit_code"),
                "pending_interventions": len(
                    [
                        item
                        for item in self.state["pending_interventions"]
                        if item.get("session_id")
                        in (None, session["session_id"])
                    ]
                ),
                "capabilities": session.get("capabilities"),
                "input_capable": bool(session.get("input_capable")),
                "lane": session.get("lane") or "ungoverned",
            }

        if method == "runtime.session.list":
            result = []
            for item in self._runtime_sessions():
                result.append(
                    {
                        "session_id": item["session_id"],
                        "backend_kind": item["backend_kind"],
                        "status": item["status"],
                        "task": item.get("task"),
                        "pid": item.get("pid"),
                        "started_at": item.get("started_at"),
                        "updated_at": item.get("updated_at"),
                        "parent_session_id": item.get("parent_session_id"),
                        "pending_interventions": len(
                            [
                                intervention
                                for intervention in self.state[
                                    "pending_interventions"
                                ]
                                if intervention.get("session_id")
                                in (None, item["session_id"])
                            ]
                        ),
                    }
                )
            return result

        if method == "runtime.session.events":
            session_id = params["session_id"]
            self._required_session(session_id)
            since_seq = int(params.get("since_seq", 0))
            limit = min(max(int(params.get("limit", 100)), 0), 1000)
            return [
                event
                for event in self._events_for(session_id)
                if int(event.get("seq", 0)) >= since_seq
            ][:limit]

        if method in ("runtime.session.pause", "runtime.session.resume"):
            session = self._required_session(params["session_id"])
            session["status"] = "paused" if method.endswith("pause") else "running"
            return {"session_id": session["session_id"], "status": session["status"]}

        if method == "runtime.session.send_input":
            session = self._required_session(params["session_id"])
            text = params.get("text")
            if not text:
                return {
                    "delivered": False,
                    "session_id": session["session_id"],
                    "error": "text must be non-empty",
                }
            return {
                "delivered": bool(session.get("input_capable")),
                "session_id": session["session_id"],
                "status": session["status"],
                **(
                    {}
                    if session.get("input_capable")
                    else {"error": "backend does not support input injection"}
                ),
            }

        if method == "runtime.session.kill":
            session = self._required_session(params["session_id"])
            if session["status"] not in ("exited", "failed"):
                session["status"] = "failed"
            session["updated_at"] = DEFAULT_AT
            return {
                "session_id": session["session_id"],
                "status": session["status"],
            }

        if method == "runtime.session.fork":
            parent = self._required_session(params["parent_session_id"])
            index = int(self.state["next_runtime_session"])
            child = _session_defaults(
                {
                    "session_id": f"run-synthetic-{index:03d}",
                    "backend_kind": params.get("backend_kind")
                    or parent["backend_kind"],
                    "cwd": parent["cwd"],
                    "status": "created",
                    "task": params.get("task"),
                    "parent_session_id": parent["session_id"],
                },
                index=index,
            )
            self._runtime_sessions().append(child)
            self.state["next_runtime_session"] = index + 1
            return {
                "session_id": child["session_id"],
                "parent_session_id": parent["session_id"],
                "status": child["status"],
                "cwd": child["cwd"],
                "task": child["task"],
            }

        if method == "runtime.intervention.list":
            session_id = params["session_id"]
            self._required_session(session_id)
            return [
                self._canonical_intervention(item, session_id)
                for item in self.state["pending_interventions"]
                if item.get("session_id") in (None, session_id)
            ]

        if method == "runtime.intervention.resolve":
            session = self._required_session(params["session_id"])
            tool_call_id = params["tool_call_id"]
            pending = self.state["pending_interventions"]
            match = next(
                (
                    item
                    for item in pending
                    if item.get("tool_call_id") == tool_call_id
                    and item.get("session_id") in (None, session["session_id"])
                ),
                None,
            )
            if match is None:
                return {
                    "resolved": False,
                    "error": "No pending intervention for tool_call_id",
                }
            pending.remove(match)
            decision = str(params["decision"])
            record = {
                "session_id": session["session_id"],
                "tool_call_id": tool_call_id,
                "decision": decision,
                "reason": params.get("reason"),
            }
            self.state["intervention_decisions"].append(record)
            session["pending_interventions"] = len(pending)
            after = self.runtime_cfg.get("after_intervention_status")
            if after:
                session["status"] = str(after)
            if decision == "approve" and not pending and self.candidate:
                self._stage_candidate()
            self._append_dynamic_event(
                session["session_id"],
                "operator_decision",
                "operator",
                record,
            )
            return {
                "resolved": True,
                "intervention_id": str(
                    match.get("intervention_id") or f"int-{tool_call_id}"
                ),
                "decision": decision,
            }

        if method == "runtime.promotion.get":
            self._required_session(params["session_id"])
            return self._promotion(params["session_id"])

        if method == "runtime.promotion.diff":
            promotion = self._promotion(params["session_id"])
            if promotion is None:
                return {"error": "No pending promotion"}
            # Canonical Governor response intentionally contains no files_changed.
            return {
                "promotion_id": promotion["promotion_id"],
                "diff": self._candidate_diff(),
            }

        if method == "runtime.promotion.resolve":
            session_id = params["session_id"]
            promotion = self._promotion(session_id)
            if promotion is None:
                return {"resolved": False, "error": "No pending promotion"}
            decision = str(params["decision"])
            if decision == "approve":
                # The scripted worker result is already in the disposable
                # workspace. Approval retains it.
                status = "approved"
            elif decision == "reject":
                _apply_file_map(
                    self.workspace,
                    self.base_files,
                    remove_paths=set(self.result_files) - set(self.base_files),
                )
                self.state["candidate_staged"] = False
                status = "rejected"
            else:
                raise ValueError("promotion decision must be approve or reject")
            self.state["promotion_status"] = status
            self.state["promotion_decision"] = {
                "decision": decision,
                "reason": params.get("reason"),
            }
            self._append_dynamic_event(
                session_id,
                "promotion_resolved",
                "operator",
                {
                    "promotion_id": promotion["promotion_id"],
                    "decision": status,
                    "changed_files": promotion["changed_files"],
                    "excluded_files": promotion["excluded_files"],
                    "reason": params.get("reason"),
                },
            )
            return {
                "resolved": True,
                "promotion_id": promotion["promotion_id"],
                "status": status,
            }

        if method == "runtime.grant.activate":
            session = self._required_session(params["session_id"])
            execution_request = params.get("execution_request") or {}
            actual_plan_ref, actual_witness_digest = _verify_approval_binding(
                plan_bytes=params.get("plan_bytes"),
                witness_bytes=params.get("witness_bytes"),
                source_plan_digest=execution_request.get("source_plan_digest"),
                approval_witness_digest=execution_request.get(
                    "approval_witness_digest"
                ),
            )
            if not isinstance(self.approval_binding_cfg, dict):
                raise ValueError(
                    "scenario has no independently approved plan binding"
                )
            expected_plan_ref = self.approval_binding_cfg.get(
                "source_plan_digest"
            )
            expected_witness_digest = self.approval_binding_cfg.get(
                "approval_witness_digest"
            )
            if expected_plan_ref != actual_plan_ref:
                raise ValueError(
                    "plan_bytes do not match the frozen scenario plan digest"
                )
            if expected_witness_digest != actual_witness_digest:
                raise ValueError(
                    "witness_bytes do not match the frozen scenario witness digest"
                )
            derived = _derive_execution_grant(execution_request)
            if derived["source_plan_digest"] != actual_plan_ref:
                raise ValueError(
                    "execution_request source_plan_digest is not canonical"
                )
            if derived["approval_witness_digest"] != actual_witness_digest:
                raise ValueError(
                    "execution_request approval_witness_digest is not canonical"
                )
            grant_behavior = str(self.grant_cfg.get("behavior") or "normal")
            if grant_behavior in ("refusal", "error") or self.grant_cfg.get(
                "error"
            ):
                raise self._scripted_fault("grant")
            configured = self.grant_cfg
            _validate_configured_grant(configured, derived)
            expires_after_ns = params.get("expires_after_ns")
            if expires_after_ns is not None and (
                not isinstance(expires_after_ns, int)
                or isinstance(expires_after_ns, bool)
                or expires_after_ns <= 0
            ):
                raise ValueError(
                    "expires_after_ns must be a positive integer (nanoseconds)"
                )
            grant = {
                "grant_id": derived["grant_id"],
                "grant_digest": derived["grant_digest"],
                "enforcement": derived["enforcement"],
                "horizon": derived["horizon"],
                "write_paths": derived["write_paths"],
                "commands": derived["commands"],
                "unmet_axes": derived["unmet_axes"],
                "recent_uses": list(configured.get("recent_uses") or []),
                "state": str(configured.get("state") or "active"),
                "revoked_reason": configured.get("revoked_reason"),
                "expires_after_ns": expires_after_ns,
                "plan_binding_verified": True,
            }
            self.state["grant_by_session"][session["session_id"]] = grant
            session["lane"] = "governed"
            # Canonical runtime.grant.activate response is narrower than
            # runtime.grant.get; do not add lease/detail fields here.
            return {
                "grant_id": grant["grant_id"],
                "grant_digest": grant["grant_digest"],
                "enforcement": grant["enforcement"],
                "horizon": grant["horizon"],
                "unmet_axes": grant["unmet_axes"],
                "plan_binding_verified": grant["plan_binding_verified"],
                "expires_after_ns": grant["expires_after_ns"],
            }

        if method == "runtime.grant.get":
            grant = self.state["grant_by_session"].get(params["session_id"])
            if grant is None:
                return None
            # Canonical lease read does not repeat plan_binding_verified.
            return {
                key: value
                for key, value in grant.items()
                if key != "plan_binding_verified"
            }

        if method == "runtime.adapters.list":
            return self.config.get("adapters") or {
                "adapters": [
                    {
                        "backend_kind": "claude_code",
                        "capabilities": {
                            "supports_pause": True,
                            "supports_resume": True,
                            "supports_input_injection": False,
                            "supports_native_tool_hooks": True,
                            "supports_structured_events": True,
                            "supports_graceful_shutdown": True,
                        },
                    }
                ],
                "count": 1,
            }

        if method == "operator.snapshot":
            if self.config.get("operator_snapshot") is not None:
                return self.config["operator_snapshot"]
            # Canonical shape: deliberately no synthetic top-level `overall`.
            return {
                "schema": "operator-snapshot/1",
                "generated_at": DEFAULT_AT,
                "backend": "daemon",
                "gov_dir": str(self.workspace),
                "rollup": {},
                "checks": [],
                "counts": {"ok": 0, "warn": 0, "fail": 0},
                "suggestions": [],
                "truncated": False,
                "limits": {"suggestions": 5, "receipt_items": 5},
            }

        if method == "operator.decisions.list":
            items = self.config.get("operator_decisions")
            if items is None:
                items = self._derived_decisions()
            kinds = params.get("kinds")
            if kinds is not None:
                items = [item for item in items if item.get("kind") in kinds]
            return {"items": items, "count": len(items), "feed_seq": 1}

        if method == "operator.decisions.resolve":
            decision_id = str(params["decision_id"])
            option_key = str(params["option_key"])
            if decision_id.startswith("intervention:"):
                return await self.dispatch(
                    "runtime.intervention.resolve",
                    {
                        "session_id": decision_id.split(":", 2)[1],
                        "tool_call_id": decision_id.split(":", 2)[2],
                        "decision": "approve" if option_key == "y" else "deny",
                    },
                )
            if decision_id.startswith("promotion:"):
                return await self.dispatch(
                    "runtime.promotion.resolve",
                    {
                        "session_id": decision_id.split(":", 1)[1],
                        "decision": "approve" if option_key == "k" else "reject",
                    },
                )
            return {"resolved": False, "error": "option_not_available"}

        if method == "commit.pending":
            return None
        if method in ("receipts.list", "commit.exceptions", "scars.history"):
            return []
        if method == "scars.list":
            return {"scars": [], "count": 0}
        if method == "why.chain":
            return {
                "requested_id": params.get("receipt_id"),
                "found": False,
                "depth": 0,
                "links": [],
            }

        raise RPCFault(-32601, f"Method not found: {method}")

    def _required_session(self, session_id: str) -> dict[str, Any]:
        session = self._find_session(str(session_id))
        if session is None:
            raise ValueError(f"Session not found: {session_id}")
        return session

    @staticmethod
    def _canonical_intervention(
        raw: dict[str, Any], session_id: str
    ) -> dict[str, Any]:
        tool_call_id = str(raw.get("tool_call_id") or "tool-call-synthetic-001")
        # Canonical Agent Governor shape intentionally has no action_class or
        # communication_warning extension.
        return {
            "intervention_id": str(
                raw.get("intervention_id") or f"int-{tool_call_id}"
            ),
            "tool_call_id": tool_call_id,
            "tool_name": str(raw.get("tool_name") or "Edit"),
            "tool_input": raw.get("tool_input") or {},
            "elapsed_seconds": float(raw.get("elapsed_seconds") or 0.0),
            "remaining_seconds": float(raw.get("remaining_seconds") or 300.0),
            "timed_out": bool(raw.get("timed_out", False)),
            **(
                {"session_id": raw["session_id"]}
                if raw.get("session_id") is not None
                else {}
            ),
        }

    def _derived_decisions(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        session_id = (
            self.state.get("candidate_session_id")
            or (
                self._runtime_sessions()[0]["session_id"]
                if self._runtime_sessions()
                else "run-unknown"
            )
        )
        for raw in self.state["pending_interventions"]:
            intervention = self._canonical_intervention(raw, session_id)
            sid = str(raw.get("session_id") or session_id)
            items.append(
                {
                    "decision_id": f"intervention:{sid}:{intervention['tool_call_id']}",
                    "kind": "intervention",
                    "session_ref": sid,
                    "created_at": DEFAULT_AT,
                    "urgency": "blocking",
                    "summary": f"{intervention['tool_name']} requires a decision",
                    "timeout_at": None,
                    "detail": {"tool_input": intervention["tool_input"]},
                    "options": [
                        {"key": "y", "label": "approve", "action": "approve"},
                        {"key": "n", "label": "deny", "action": "deny"},
                    ],
                    "receipt_refs": [],
                    "why_ref": None,
                    "refs": [],
                    "source": {"runtime": "synthetic"},
                }
            )
        promotion = (
            self._promotion(session_id) if self._find_session(session_id) else None
        )
        if promotion:
            items.append(
                {
                    "decision_id": f"promotion:{session_id}",
                    "kind": "promotion",
                    "session_ref": session_id,
                    "created_at": DEFAULT_AT,
                    "urgency": "normal",
                    "summary": f"{len(promotion['changed_files'])} file(s) await review",
                    "timeout_at": None,
                    "detail": {"changed_files": promotion["changed_files"]},
                    "options": [
                        {"key": "k", "label": "keep", "action": "approve"},
                        {"key": "d", "label": "discard", "action": "reject"},
                    ],
                    "receipt_refs": [],
                    "why_ref": None,
                    "refs": [],
                    "source": {"runtime": "synthetic"},
                }
            )
        return items

    @staticmethod
    def _supported_methods() -> set[str]:
        return {
            "governor.hello",
            "governor.now",
            "governor.status",
            "governor.methods",
            "sessions.list",
            "sessions.create",
            "sessions.get",
            "sessions.delete",
            "runtime.session.create",
            "runtime.session.launch",
            "runtime.session.get",
            "runtime.session.list",
            "runtime.session.events",
            "runtime.session.pause",
            "runtime.session.resume",
            "runtime.session.send_input",
            "runtime.session.kill",
            "runtime.session.fork",
            "runtime.intervention.list",
            "runtime.intervention.resolve",
            "runtime.promotion.get",
            "runtime.promotion.diff",
            "runtime.promotion.resolve",
            "runtime.grant.activate",
            "runtime.grant.get",
            "runtime.adapters.list",
            "operator.snapshot",
            "operator.decisions.list",
            "operator.decisions.resolve",
            "commit.pending",
            "receipts.list",
            "commit.exceptions",
            "scars.list",
            "scars.history",
            "why.chain",
        }


async def _run(args: argparse.Namespace) -> None:
    config_path = Path(args.config).resolve()
    socket_path = Path(args.socket).resolve()
    state_dir = Path(args.state_dir).resolve()
    trace_path = (
        Path(args.trace).resolve()
        if args.trace
        else state_dir / "rpc-transcript.jsonl"
    )
    config = json.loads(config_path.read_text(encoding="utf-8"))
    runtime = SyntheticRuntime(
        config,
        RuntimePaths(
            config=config_path,
            socket=socket_path,
            state_dir=state_dir,
            trace=trace_path,
        ),
    )

    socket_path.parent.mkdir(parents=True, exist_ok=True)
    if socket_path.exists() or socket_path.is_symlink():
        socket_path.unlink()
    server = await asyncio.start_unix_server(runtime.serve_connection, str(socket_path))
    _atomic_json(
        runtime.paths.ready,
        {
            "schema": "maude.synthetic-runtime.ready.v1",
            "scenario_id": config.get("scenario_id"),
            "socket": str(socket_path),
            "pid": os.getpid(),
            "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
        },
    )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass
    async with server:
        await stop.wait()
    if socket_path.exists() or socket_path.is_symlink():
        socket_path.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Synthetic Unix-socket Agent Governor runtime for Maude UX evals"
    )
    parser.add_argument("--config", required=True)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--trace")
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
