# SPDX-License-Identifier: Apache-2.0
"""Docket transport-V1 executor for one sealed reviewed-local-copy plan.

The executor owns only a durable local attempt record and the exact creation of
``result.txt`` in a plan-bound scratch root.  It has no command language,
overwrite mode, provider, or recovery retry.  A separately built and pinned
qualification package can terminate after the result and directory are synced
but before the success record; the ordinary executor never selects that mode.
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
QUALIFICATION_CUT_EXIT_CODE = 75
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_DISPATCH = {"attempt", "marker", "work_schema", "work", "subject", "scope"}
_OUTCOME = {"attempt", "marker", "receipt", "outcome"}


class ExecutorRefusal(ValueError):
    pass


class QualificationInterruption(RuntimeError):
    """Stop only the separately enrolled uncertainty qualification program."""


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


def _open_directory(path: Path, where: str) -> int:
    """Open and pin a validated directory against later pathname replacement."""
    try:
        before = path.lstat()
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except (FileNotFoundError, NotADirectoryError) as error:
        raise ExecutorRefusal(f"{where} is absent or not a directory") from error
    after = os.fstat(descriptor)
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode) or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
        os.close(descriptor)
        raise ExecutorRefusal(f"{where} changed during validation")
    return descriptor


def _write_all(descriptor: int, raw: bytes) -> None:
    view = memoryview(raw)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("write made no progress")
        view = view[written:]


def _write_atomic(directory: int, name: str, raw: bytes) -> None:
    temp = name + ".new"
    descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600, dir_fd=directory)
    try:
        _write_all(descriptor, raw)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temp, name, src_dir_fd=directory, dst_dir_fd=directory)
    os.fsync(directory)


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


def _outcome(dispatch: dict[str, Any], receipt: str, outcome: str) -> bytes:
    value = {"attempt": dispatch["attempt"], "marker": dispatch["marker"], "outcome": outcome, "receipt": receipt}
    _closed(value, _OUTCOME, "outcome")
    return canonical_json_bytes(value) + b"\n"


def _record(dispatch: dict[str, Any], state: str, receipt: str | None = None) -> bytes:
    value: dict[str, Any] = {"dispatch": dispatch, "schema": RECEIPT_SCHEMA, "state": state}
    if receipt is not None:
        value["receipt"] = receipt
    return canonical_json_bytes(value)


def _read_record(directory: int) -> dict[str, Any]:
    try:
        descriptor = os.open("record.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory)
    except FileNotFoundError as error:
        raise ExecutorRefusal("attempt record is absent after reservation") from error
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ExecutorRefusal("attempt record must be a regular file")
        chunks: list[bytes] = []
        remaining = MAX_DOCUMENT_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
    finally:
        os.close(descriptor)
    return _json(b"".join(chunks), "attempt record")


def _terminal_from_record(record: dict[str, Any]) -> bytes | None:
    state = record.get("state")
    expected = {"dispatch", "schema", "state", "receipt"} if state == "success" else {"dispatch", "schema", "state"}
    _closed(record, expected, "attempt record")
    if record.get("schema") != RECEIPT_SCHEMA or state not in {"reserved", "indeterminate", "success"}:
        raise ExecutorRefusal("attempt record schema or state is invalid")
    if state == "success":
        receipt = _digest(record.get("receipt"), "attempt record.receipt")
        if receipt != content_digest(_record(record["dispatch"], "success")):
            raise ExecutorRefusal("attempt record receipt identity mismatch")
        return _outcome(record["dispatch"], receipt, "success")
    return None


def execute(config_path: Path, raw_dispatch: bytes) -> bytes:
    return _execute(config_path, raw_dispatch, qualification_cut=False)


def execute_interruption_qualification(config_path: Path, raw_dispatch: bytes) -> bytes:
    """Run the exact-copy mechanics with the one documented qualification cut."""
    return _execute(config_path, raw_dispatch, qualification_cut=True)


def _execute(config_path: Path, raw_dispatch: bytes, *, qualification_cut: bool) -> bytes:
    _, plan, scratch, state_root = _load_config(config_path)
    dispatch = _dispatch(raw_dispatch, plan)
    attempt_name = dispatch["attempt"].removeprefix("sha256:")
    state_descriptor = _open_directory(state_root, "state root")
    scratch_descriptor = _open_directory(scratch, "scratch root")
    try:
        try:
            os.mkdir(attempt_name, 0o700, dir_fd=state_descriptor)
            os.fsync(state_descriptor)
            attempt_descriptor = os.open(attempt_name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=state_descriptor)
            _write_atomic(attempt_descriptor, "record.json", _record(dispatch, "reserved"))
        except FileExistsError:
            attempt_descriptor = os.open(attempt_name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=state_descriptor)
            try:
                prior = _read_record(attempt_descriptor)
                if prior.get("dispatch") != dispatch:
                    raise ExecutorRefusal("attempt dispatch substitution")
                terminal = _terminal_from_record(prior)
                if terminal is not None:
                    return terminal
                return _outcome(dispatch, content_digest(canonical_json_bytes(prior)), "indeterminate")
            finally:
                os.close(attempt_descriptor)
        try:
            try:
                descriptor = os.open("result.txt", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=scratch_descriptor)
            except FileExistsError as error:
                _write_atomic(attempt_descriptor, "record.json", _record(dispatch, "indeterminate"))
                raise ExecutorRefusal("result.txt already exists; effect not retried") from error
            try:
                _write_all(descriptor, _decode_text(plan))
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            os.fsync(scratch_descriptor)
            if qualification_cut:
                raise QualificationInterruption(
                    "qualification interruption after result fsync before success record"
                )
            receipt = content_digest(_record(dispatch, "success"))
            _write_atomic(attempt_descriptor, "record.json", _record(dispatch, "success", receipt))
            return _outcome(dispatch, receipt, "success")
        finally:
            os.close(attempt_descriptor)
    finally:
        os.close(scratch_descriptor)
        os.close(state_descriptor)


def reconcile(config_path: Path, raw_dispatch: bytes) -> bytes:
    _, plan, _scratch, state_root = _load_config(config_path)
    dispatch = _dispatch(raw_dispatch, plan)
    state_descriptor = _open_directory(state_root, "state root")
    try:
        try:
            attempt_descriptor = os.open(dispatch["attempt"].removeprefix("sha256:"), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=state_descriptor)
        except FileNotFoundError as error:
            raise ExecutorRefusal("attempt evidence is absent") from error
        try:
            prior = _read_record(attempt_descriptor)
            if prior.get("dispatch") != dispatch:
                raise ExecutorRefusal("attempt dispatch substitution")
            terminal = _terminal_from_record(prior)
            if terminal is not None:
                return terminal
            return _outcome(dispatch, content_digest(canonical_json_bytes(prior)), "indeterminate")
        finally:
            os.close(attempt_descriptor)
    finally:
        os.close(state_descriptor)


def _main(argv: list[str] | None, *, qualification_interruption: bool) -> int:
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
            if args.operation == "execute":
                operation = (
                    execute_interruption_qualification
                    if qualification_interruption
                    else execute
                )
                result = operation(args.config, raw)
            else:
                result = reconcile(args.config, raw)
            sys.stdout.buffer.write(result)
    except QualificationInterruption as error:
        print(str(error), file=sys.stderr)
        return QUALIFICATION_CUT_EXIT_CODE
    except (OSError, ExecutorRefusal, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    return _main(argv, qualification_interruption=False)


def qualification_main(argv: list[str] | None = None) -> int:
    """CLI for the separately packaged interruption qualification program."""
    return _main(argv, qualification_interruption=True)


if __name__ == "__main__":
    raise SystemExit(main())
