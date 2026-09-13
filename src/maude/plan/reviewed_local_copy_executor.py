# SPDX-License-Identifier: Apache-2.0
"""Docket transport-V1 executor for one sealed reviewed-local-copy plan.

The executor owns only a durable local attempt record and the exact creation of
``result.txt`` in a plan-bound scratch root.  It has no command language,
overwrite mode, provider, or recovery retry.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any

from maude.plan.document import canonical_json_bytes, content_digest
from maude.plan.local_compose import ag_executor_plan_identity
from maude.plan.reviewed_local_copy import COMPILER_CONTRACT, EXECUTOR_PLAN_SCHEMA, MAX_REVIEWED_TEXT_BYTES


CONFIG_SCHEMA = "maude.reviewed-local-copy.executor-config/v1"
RECEIPT_SCHEMA = "maude.reviewed-local-copy.executor-receipt/v1"
MAX_DOCUMENT_BYTES = 1024 * 1024
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_DISPATCH = {"attempt", "marker", "work_schema", "work", "subject", "scope"}
_OUTCOME = {"attempt", "marker", "receipt", "outcome"}


class ExecutorRefusal(ValueError):
    pass


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ExecutorRefusal("duplicate JSON member")
        result[key] = value
    return result


def _json(raw: bytes, where: str) -> dict[str, Any]:
    if len(raw) > MAX_DOCUMENT_BYTES:
        raise ExecutorRefusal(f"{where} exceeds transport bound")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ExecutorRefusal(f"{where} is not UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise ExecutorRefusal(f"{where} must be an object")
    return value


def _digest(value: Any, where: str) -> str:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise ExecutorRefusal(f"{where} must be a canonical digest")
    return value


def _closed(value: dict[str, Any], fields: set[str], where: str) -> None:
    if set(value) != fields:
        raise ExecutorRefusal(f"{where} has unsupported or missing fields")


def _regular_directory(path: Path, where: str) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError as error:
        raise ExecutorRefusal(f"{where} is absent") from error
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        raise ExecutorRefusal(f"{where} must be a non-symlink directory")


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_atomic(path: Path, raw: bytes) -> None:
    parent = path.parent
    _regular_directory(parent, "attempt directory")
    temp = parent / (path.name + ".new")
    descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    try:
        os.write(descriptor, raw)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temp, path)
    _fsync_directory(parent)


def _decode_text(plan: dict[str, Any]) -> bytes:
    encoded = plan.get("reviewed_text_base64")
    length = plan.get("reviewed_text_byte_length")
    if isinstance(length, bool) or not isinstance(length, int) or length < 0 or length > MAX_REVIEWED_TEXT_BYTES or not isinstance(encoded, str):
        raise ExecutorRefusal("sealed text exceeds bound")
    try:
        raw = base64.b64decode(encoded, validate=True)
        raw.decode("utf-8")
    except (ValueError, UnicodeDecodeError) as error:
        raise ExecutorRefusal("sealed text must be strict UTF-8 standard base64") from error
    if base64.b64encode(raw).decode("ascii") != encoded or len(raw) != length or content_digest(raw) != plan.get("reviewed_text_digest"):
        raise ExecutorRefusal("sealed text identity mismatch")
    return raw


def _load_config(path: Path) -> tuple[dict[str, Any], dict[str, Any], Path, Path]:
    config = _json(path.read_bytes(), "executor config")
    _closed(config, {"schema", "executor_plan_base64", "state_root"}, "executor config")
    if config["schema"] != CONFIG_SCHEMA or not isinstance(config["executor_plan_base64"], str) or not isinstance(config["state_root"], str):
        raise ExecutorRefusal("unsupported executor config")
    try:
        plan_raw = base64.b64decode(config["executor_plan_base64"], validate=True)
    except ValueError as error:
        raise ExecutorRefusal("executor plan is not standard base64") from error
    plan = _json(plan_raw, "executor plan")
    if canonical_json_bytes(plan) != plan_raw:
        raise ExecutorRefusal("executor plan must retain canonical sealed bytes")
    fields = {"schema", "action", "campaign", "compiler", "destination", "occurrence", "plan_document_digest", "program_basis", "reviewed_text_base64", "reviewed_text_byte_length", "reviewed_text_digest", "scope_digest", "scratch_root", "subject_digest"}
    _closed(plan, fields, "executor plan")
    if plan["schema"] != EXECUTOR_PLAN_SCHEMA or plan["action"] != "copy_reviewed_text" or plan["destination"] != "result.txt":
        raise ExecutorRefusal("unsupported executor plan")
    for name in ("campaign", "subject_digest", "scope_digest", "program_basis", "plan_document_digest"):
        _digest(plan[name], f"executor plan.{name}")
    if not isinstance(plan["occurrence"], str) or not isinstance(plan["scratch_root"], str):
        raise ExecutorRefusal("executor plan coordinates are invalid")
    compiler = plan["compiler"]
    if compiler != {"id": COMPILER_CONTRACT, "inputs_digest": compiler.get("inputs_digest") if isinstance(compiler, dict) else None, "version": "1"}:
        raise ExecutorRefusal("executor plan compiler differs")
    _digest(compiler["inputs_digest"], "executor plan.compiler.inputs_digest")
    scratch = Path(plan["scratch_root"])
    state_root = Path(config["state_root"])
    if not scratch.is_absolute() or not state_root.is_absolute():
        raise ExecutorRefusal("scratch and state roots must be absolute")
    _regular_directory(scratch, "scratch root")
    _regular_directory(state_root, "state root")
    _decode_text(plan)
    return config, plan, scratch, state_root


def _dispatch(raw: bytes, plan: dict[str, Any]) -> dict[str, Any]:
    dispatch = _json(raw, "dispatch")
    _closed(dispatch, _DISPATCH, "dispatch")
    for name in ("attempt", "marker", "work", "subject", "scope"):
        _digest(dispatch[name], f"dispatch.{name}")
    if not isinstance(dispatch["work_schema"], str) or not dispatch["work_schema"]:
        raise ExecutorRefusal("dispatch.work_schema is invalid")
    expected = ag_executor_plan_identity(plan)
    if (dispatch["work_schema"], dispatch["work"], dispatch["subject"], dispatch["scope"]) != (COMPILER_CONTRACT, expected, plan["subject_digest"], plan["scope_digest"]):
        raise ExecutorRefusal("dispatch differs from sealed executor plan")
    return dispatch


def _attempt_directory(state_root: Path, attempt: str) -> Path:
    return state_root / attempt.removeprefix("sha256:")


def _outcome(dispatch: dict[str, Any], receipt: str, outcome: str) -> bytes:
    value = {"attempt": dispatch["attempt"], "marker": dispatch["marker"], "outcome": outcome, "receipt": receipt}
    _closed(value, _OUTCOME, "outcome")
    return canonical_json_bytes(value) + b"\n"


def _record(dispatch: dict[str, Any], state: str, receipt: str | None = None) -> bytes:
    value: dict[str, Any] = {"dispatch": dispatch, "schema": RECEIPT_SCHEMA, "state": state}
    if receipt is not None:
        value["receipt"] = receipt
    return canonical_json_bytes(value)


def _read_record(path: Path) -> dict[str, Any]:
    return _json(path.read_bytes(), "attempt record")


def _terminal_from_record(record: dict[str, Any]) -> bytes | None:
    if record.get("state") == "success" and isinstance(record.get("receipt"), str):
        return _outcome(record["dispatch"], record["receipt"], "success")
    return None


def execute(config_path: Path, raw_dispatch: bytes) -> bytes:
    _, plan, scratch, state_root = _load_config(config_path)
    dispatch = _dispatch(raw_dispatch, plan)
    directory = _attempt_directory(state_root, dispatch["attempt"])
    record_path = directory / "record.json"
    try:
        os.mkdir(directory, 0o700)
        _fsync_directory(state_root)
        _write_atomic(record_path, _record(dispatch, "reserved"))
    except FileExistsError:
        _regular_directory(directory, "attempt directory")
        prior = _read_record(record_path)
        if prior.get("dispatch") != dispatch:
            raise ExecutorRefusal("attempt dispatch substitution")
        terminal = _terminal_from_record(prior)
        if terminal is not None:
            return terminal
        return _outcome(dispatch, content_digest(canonical_json_bytes(prior)), "indeterminate")
    result = scratch / "result.txt"
    try:
        descriptor = os.open(result, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    except FileExistsError as error:
        _write_atomic(record_path, _record(dispatch, "indeterminate"))
        raise ExecutorRefusal("result.txt already exists; effect not retried") from error
    text = _decode_text(plan)
    try:
        os.write(descriptor, text)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    _fsync_directory(scratch)
    receipt = content_digest(_record(dispatch, "success"))
    _write_atomic(record_path, _record(dispatch, "success", receipt))
    return _outcome(dispatch, receipt, "success")


def reconcile(config_path: Path, raw_dispatch: bytes) -> bytes:
    _, plan, _scratch, state_root = _load_config(config_path)
    dispatch = _dispatch(raw_dispatch, plan)
    record_path = _attempt_directory(state_root, dispatch["attempt"]) / "record.json"
    if not record_path.is_file():
        raise ExecutorRefusal("attempt evidence is absent")
    prior = _read_record(record_path)
    if prior.get("dispatch") != dispatch:
        raise ExecutorRefusal("attempt dispatch substitution")
    terminal = _terminal_from_record(prior)
    if terminal is not None:
        return terminal
    return _outcome(dispatch, content_digest(canonical_json_bytes(prior)), "indeterminate")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="maude-reviewed-local-copy-executor")
    parser.add_argument("operation", choices=("plan-id", "execute", "reconcile"))
    parser.add_argument("config", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.operation == "plan-id":
            _, plan, _, _ = _load_config(args.config)
            print(ag_executor_plan_identity(plan))
        else:
            raw = sys.stdin.buffer.read(MAX_DOCUMENT_BYTES + 1)
            if len(raw) > MAX_DOCUMENT_BYTES:
                raise ExecutorRefusal("dispatch exceeds transport bound")
            result = execute(args.config, raw) if args.operation == "execute" else reconcile(args.config, raw)
            sys.stdout.buffer.write(result)
    except (OSError, ExecutorRefusal, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
