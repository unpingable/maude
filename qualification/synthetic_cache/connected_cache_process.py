#!/usr/bin/env python3
"""Bound one local tutorial subprocess while retaining bounded stream prefixes."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import signal
import subprocess
import threading
import time

MAX_STREAM_BYTES = 16 * 1024 * 1024
READ_CHUNK = 64 * 1024
POLL_SECONDS = 0.01
TERMINATE_GRACE_SECONDS = 1.0


@dataclass(frozen=True)
class BoundedProcessResult:
    returncode: int
    stdout_path: Path
    stderr_path: Path
    stdout_bytes: int
    stderr_bytes: int
    stdout_truncated: bool
    stderr_truncated: bool


class BoundedProcessError(RuntimeError):
    def __init__(self, message: str, *, status: str, result: BoundedProcessResult):
        super().__init__(message)
        self.status = status
        self.result = result


class BoundedOutputExceeded(BoundedProcessError):
    """The retained prefix is complete to its bound; command settlement is unknown."""


class UncertainProcessTimeout(BoundedProcessError):
    """The command exceeded its wait bound; owner settlement must be inspected."""


class UncertainDrainLoss(BoundedProcessError):
    """The leader exited while a process-group member retained an output pipe."""


class _StreamCapture:
    def __init__(self, source, destination, maximum: int, cancel: threading.Event):
        self.source = source
        self.destination = destination
        self.maximum = maximum
        self.cancel = cancel
        self.total = 0
        self.truncated = False
        self.error: BaseException | None = None

    def run(self) -> None:
        try:
            with self.source, self.destination.open("xb") as output:
                while chunk := os.read(self.source.fileno(), READ_CHUNK):
                    before = self.total
                    self.total += len(chunk)
                    retained = max(0, min(len(chunk), self.maximum - before))
                    if retained:
                        output.write(chunk[:retained])
                    if self.total > self.maximum:
                        self.truncated = True
                        self.cancel.set()
                output.flush()
                os.fsync(output.fileno())
        except BaseException as error:
            self.error = error
            self.cancel.set()


def _group_exists(process_group: int) -> bool:
    try:
        os.killpg(process_group, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _stop_group(process: subprocess.Popen, process_group: int) -> None:
    # The leader may already be reaped while a descendant still owns the
    # inherited pipes. Address the process group independently of leader state.
    try:
        os.killpg(process_group, signal.SIGTERM)
    except ProcessLookupError:
        pass
    deadline = time.monotonic() + TERMINATE_GRACE_SECONDS
    while _group_exists(process_group) and time.monotonic() < deadline:
        time.sleep(POLL_SECONDS)
    if _group_exists(process_group):
        try:
            os.killpg(process_group, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.returncode is None:
        process.wait(timeout=TERMINATE_GRACE_SECONDS)


def run_bounded(
    argv: list[str], *, stdout_path: Path, stderr_path: Path,
    timeout: float, env: dict[str, str] | None = None,
    max_stream_bytes: int = MAX_STREAM_BYTES,
) -> BoundedProcessResult:
    if not argv or not all(isinstance(item, str) and item for item in argv):
        raise ValueError("a nonempty direct argv is required")
    if timeout <= 0 or max_stream_bytes <= 0:
        raise ValueError("positive timeout and stream bound required")
    for path in (stdout_path, stderr_path):
        if not path.is_absolute() or path.exists() or path.is_symlink() or not path.parent.is_dir():
            raise ValueError("stream output must be a fresh absolute path below an existing directory")

    process = subprocess.Popen(
        argv, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, start_new_session=True,
    )
    assert process.stdout is not None and process.stderr is not None
    process_group = process.pid
    cancel = threading.Event()
    stdout = _StreamCapture(process.stdout, stdout_path, max_stream_bytes, cancel)
    stderr = _StreamCapture(process.stderr, stderr_path, max_stream_bytes, cancel)
    threads = [threading.Thread(target=item.run, daemon=True) for item in (stdout, stderr)]
    for thread in threads:
        thread.start()

    deadline = time.monotonic() + timeout
    reason = None
    while process.poll() is None:
        if cancel.is_set():
            reason = "output"
            break
        if time.monotonic() >= deadline:
            reason = "timeout"
            break
        time.sleep(POLL_SECONDS)
    if reason is not None:
        _stop_group(process, process_group)
    else:
        process.wait()
    for thread in threads:
        thread.join(timeout=TERMINATE_GRACE_SECONDS)
    drain_loss = any(thread.is_alive() for thread in threads)
    if drain_loss:
        _stop_group(process, process_group)
        for thread in threads:
            thread.join(timeout=TERMINATE_GRACE_SECONDS)
    if stdout.error is not None:
        raise RuntimeError("stdout capture failed") from stdout.error
    if stderr.error is not None:
        raise RuntimeError("stderr capture failed") from stderr.error

    result = BoundedProcessResult(
        returncode=process.returncode, stdout_path=stdout_path, stderr_path=stderr_path,
        stdout_bytes=stdout.total, stderr_bytes=stderr.total,
        stdout_truncated=stdout.truncated, stderr_truncated=stderr.truncated,
    )
    if drain_loss:
        raise UncertainDrainLoss(
            "leader exited while a descendant retained an output pipe; process group stopped",
            status="uncertain", result=result,
        )
    if reason == "timeout":
        raise UncertainProcessTimeout(
            "command timed out; process group stopped, but owner settlement is uncertain",
            status="uncertain", result=result,
        )
    if reason == "output" or stdout.truncated or stderr.truncated:
        raise BoundedOutputExceeded(
            "command stream exceeded its retained prefix bound; owner settlement is uncertain",
            status="uncertain", result=result,
        )
    return result
