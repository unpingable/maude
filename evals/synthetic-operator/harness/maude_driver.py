#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Persistent headless driver for the real Maude public command surface.

The driver owns one real MaudeApp at a time, connected through the real
GovernorClient to the campaign's synthetic Unix socket.  A deliberately tiny
filesystem queue lets an isolated operator process submit commands without
receiving access to Maude source or evaluator-only scenario configuration.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any


# Run the exact checkout under evaluation, even when Maude is not installed as
# an editable package.  This path is evaluator-internal and is never returned
# through the public queue.
_REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO / "src"))

from textual.widgets import Input, RichLog, Static  # noqa: E402
from rich.markup import MarkupError  # noqa: E402
from rich.text import Text  # noqa: E402

from maude import __version__  # noqa: E402
from maude.app import MaudeApp  # noqa: E402
from maude.client.rpc import GovernorClient  # noqa: E402
from maude.config import Settings  # noqa: E402


QUEUE_SCHEMA = "maude.synthetic-operator.queue.v1"
RESPONSE_SCHEMA = "maude.synthetic-operator.response.v1"


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


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


def _logical_lines(log: RichLog) -> list[str]:
    return [strip.text.rstrip() for strip in log.lines]


def _static_text(app: MaudeApp) -> list[str]:
    """Best-effort plain projection of the currently active non-log screen."""

    items: list[str] = []
    for widget in app.screen.query(Static):
        if not widget.display:
            continue
        rendered = widget.render()
        plain = getattr(rendered, "plain", None)
        if isinstance(plain, str):
            text = plain
        else:
            content = str(widget.content)
            try:
                text = Text.from_markup(content).plain
            except MarkupError:
                text = content
        text = text.strip()
        if text and text not in items:
            items.append(text)
    return items


class AppHandle:
    """Manual async-context wrapper so an explicit restart can replace the app."""

    def __init__(self, *, socket: Path, workspace: Path, size: tuple[int, int]) -> None:
        self.socket = socket
        self.workspace = workspace
        self.size = size
        self.app: MaudeApp | None = None
        self.pilot = None
        self.context = None

    async def start(self) -> None:
        settings = Settings(
            governor_dir=str(self.workspace),
            socket_path=str(self.socket),
            context_id="synthetic-lab",
            governor_mode="code",
            label="synthetic-evaluation",
        )
        client = GovernorClient(socket_path=self.socket)
        self.app = MaudeApp(client=client, settings=settings)
        self.context = self.app.run_test(size=self.size)
        self.pilot = await self.context.__aenter__()
        await self.pilot.pause()

    async def stop(self) -> None:
        if self.context is not None:
            await self.context.__aexit__(None, None, None)
        self.context = None
        self.pilot = None
        self.app = None

    async def restart(self) -> None:
        await self.stop()
        await self.start()


class Driver:
    def __init__(self, args: argparse.Namespace) -> None:
        self.control = Path(args.control_dir).resolve()
        self.workspace = Path(args.workspace).resolve()
        self.command_cwd = Path(args.command_cwd).resolve()
        self.socket = Path(args.socket).resolve()
        self.evidence = Path(args.evidence_dir).resolve()
        self.poll_interval = float(args.poll_interval)
        self.size = (int(args.columns), int(args.rows))
        self.requests = self.control / "requests"
        self.responses = self.control / "responses"
        self.ready = self.control / "driver-ready.json"
        self.actions = self.evidence / "driver-actions.jsonl"
        self.screens = self.evidence / "screens"
        self.handle = AppHandle(
            socket=self.socket, workspace=self.workspace, size=self.size
        )
        self.action_seq = 0
        self.restart_count = 0

    async def run(self) -> None:
        self.requests.mkdir(parents=True, exist_ok=True)
        self.responses.mkdir(parents=True, exist_ok=True)
        self.screens.mkdir(parents=True, exist_ok=True)
        os.chdir(self.command_cwd)
        await self.handle.start()
        _atomic_json(
            self.ready,
            {
                "schema": "maude.synthetic-operator.driver-ready.v1",
                "pid": os.getpid(),
                "maude_version": __version__,
                "socket": str(self.socket),
                "workspace": str(self.workspace),
                "command_cwd": str(self.command_cwd),
                "columns": self.size[0],
                "rows": self.size[1],
            },
        )

        try:
            keep_running = True
            while keep_running:
                pending = [
                    path
                    for path in sorted(self.requests.glob("*.json"))
                    if not (self.responses / path.name).exists()
                ]
                if not pending:
                    await asyncio.sleep(self.poll_interval)
                    continue
                for request_path in pending:
                    keep_running = await self._process(request_path)
                    if not keep_running:
                        break
        finally:
            await self.handle.stop()
            if self.ready.exists():
                self.ready.unlink()

    async def _process(self, request_path: Path) -> bool:
        self.action_seq += 1
        response_path = self.responses / request_path.name
        request_bytes = request_path.read_bytes()
        try:
            request = json.loads(request_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            response = self._failure(None, f"invalid request JSON: {exc}")
            _atomic_json(response_path, response)
            return True

        request_id = request.get("request_id")
        if request.get("schema") != QUEUE_SCHEMA or not isinstance(request_id, str):
            response = self._failure(request_id, "invalid queue schema or request_id")
            _atomic_json(response_path, response)
            return True

        app = self.handle.app
        pilot = self.handle.pilot
        if app is None or pilot is None:
            response = self._failure(request_id, "Maude driver is not running")
            _atomic_json(response_path, response)
            return False

        before = _logical_lines(app.query_one("#chat-log", RichLog))
        action = str(request.get("action") or "command")
        error: str | None = None
        keep_running = True
        try:
            if action == "command":
                text = request.get("text")
                if not isinstance(text, str) or not text.strip():
                    raise ValueError("command text must be a non-empty string")
                if len(text) > 32768:
                    raise ValueError("command text exceeds 32768 characters")
                input_box = app.query_one("#input-box", Input)
                input_box.focus()
                await pilot.pause()
                input_box.value = text
                await pilot.press("enter")
                await pilot.pause()
            elif action == "key":
                key = request.get("key")
                if not isinstance(key, str) or not key:
                    raise ValueError("key action requires a key")
                await pilot.press(key)
                await pilot.pause()
            elif action == "wait":
                seconds = float(request.get("seconds", 0.5))
                if seconds < 0 or seconds > 15:
                    raise ValueError("wait must be between 0 and 15 seconds")
                await asyncio.sleep(seconds)
                await pilot.pause()
            elif action == "screen":
                await pilot.pause()
            elif action == "restart":
                await self.handle.restart()
                self.restart_count += 1
                app = self.handle.app
                pilot = self.handle.pilot
                assert app is not None and pilot is not None
                before = []
                await pilot.pause()
            elif action == "quit":
                keep_running = False
            else:
                raise ValueError(f"unknown driver action: {action}")
        except Exception as exc:  # Evidence must preserve a failed interface action.
            error = f"{type(exc).__name__}: {exc}"

        app = self.handle.app
        if app is None:
            response = self._failure(request_id, error or "Maude app stopped")
            _atomic_json(response_path, response)
            return keep_running

        after = _logical_lines(app.query_one("#chat-log", RichLog))
        new_lines = after[len(before) :] if len(after) >= len(before) else after
        visible = new_lines if new_lines else _static_text(app)
        screen_name, screen_sha = self._save_screen(app)
        response = {
            "schema": RESPONSE_SCHEMA,
            "request_id": request_id,
            "ok": error is None,
            "action": action,
            "output": "\n".join(visible).rstrip(),
            "screen_evidence": screen_name,
            "screen_sha256": screen_sha,
            "restart_count": self.restart_count,
            **({"error": error} if error is not None else {}),
        }
        _atomic_json(response_path, response)
        _append_jsonl(
            self.actions,
            {
                "seq": self.action_seq,
                "request_file": request_path.name,
                "request_sha256": hashlib.sha256(request_bytes).hexdigest(),
                "request": request,
                "response_file": response_path.name,
                "response": response,
            },
        )
        return keep_running

    def _save_screen(self, app: MaudeApp) -> tuple[str, str]:
        name = f"{self.action_seq:04d}.svg"
        path = self.screens / name
        svg = app.export_screenshot(
            title=f"Maude synthetic operator action {self.action_seq}",
            simplify=False,
        )
        path.write_text(svg, encoding="utf-8", newline="\n")
        return str(Path("screens") / name), hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def _failure(request_id: Any, error: str) -> dict[str, Any]:
        return {
            "schema": RESPONSE_SCHEMA,
            "request_id": request_id,
            "ok": False,
            "action": "invalid",
            "output": "",
            "error": error,
        }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Persistent real-Maude headless driver for synthetic UX runs"
    )
    parser.add_argument("--control-dir", required=True)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--command-cwd", required=True)
    parser.add_argument("--evidence-dir", required=True)
    parser.add_argument("--poll-interval", default="0.05")
    parser.add_argument("--columns", default="120")
    parser.add_argument("--rows", default="40")
    args = parser.parse_args()
    asyncio.run(Driver(args).run())


if __name__ == "__main__":
    main()
