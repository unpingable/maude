# SPDX-License-Identifier: Apache-2.0
"""M-2 runner tests — `run <plan.md>` against fakes. Pins: refusals create no
session; the happy path maps M-1 fields to runtime.session.create verbatim;
governed candidates never execute."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

from maude.commands.base import CommandContext
from maude.intents import IntentKind, parse_intent
from maude.plan.runner import RunPlanCommand, compose_task_text
from maude.plan import parse_plan_envelope


class FakeLog:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def write(self, line: str) -> None:
        self.lines.append(str(line))

    def text(self) -> str:
        return "\n".join(self.lines)


class FakeClient:
    def __init__(self) -> None:
        self.create_calls: list[dict] = []
        self.launch_calls: list[str] = []

    async def runtime_session_create(self, **params):
        self.create_calls.append(params)
        return {"session_id": "sess-1"}

    async def runtime_session_launch(self, session_id: str):
        self.launch_calls.append(session_id)
        return {"status": "running", "pid": 4242}


class FakeApp:
    def __init__(self) -> None:
        self.client = FakeClient()


def _ctx(app: FakeApp, log: FakeLog, text: str = "") -> CommandContext:
    return CommandContext(app=app, log=log, text=text)


HUMAN_PLAN = """\
---
plan_version: 0
goal: "Do the thing"
workspace: "/tmp/proj"
submitter_kind: human
plan_origin: human_written
provenance:
  author: "operator"
harness: claude_code
steps:
  - "step one"
stop_conditions:
  forbidden_paths: ["infra/**"]
---

Background prose.
"""


def _run(cmd: RunPlanCommand, ctx: CommandContext, payload: str) -> None:
    asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
        cmd.execute(ctx, payload)
    )


class TestIntentParse:
    def test_run_plan_md_parses_to_run_plan(self):
        intent = parse_intent("run docs/plans/foo.md")
        assert intent.kind == IntentKind.RUN_PLAN
        assert intent.payload == "docs/plans/foo.md"

    def test_bare_run_prose_falls_through_to_chat(self):
        assert parse_intent("run the tests please").kind == IntentKind.CHAT


class TestRunPlanCommand:
    def test_happy_path_maps_fields_and_launches(self, tmp_path: Path):
        plan = tmp_path / "plan.md"
        plan.write_text(HUMAN_PLAN)
        app, log = FakeApp(), FakeLog()
        _run(RunPlanCommand(), _ctx(app, log), str(plan))

        assert len(app.client.create_calls) == 1
        call = app.client.create_calls[0]
        assert call["backend_kind"] == "claude_code"
        assert call["cwd"] == "/tmp/proj"
        assert call["operator_mode"] == "interactive"
        assert call["task"].startswith("Do the thing")
        assert "- step one" in call["task"]
        assert "Background prose." in call["task"]
        assert app.client.launch_calls == ["sess-1"]
        env = parse_plan_envelope(HUMAN_PLAN)
        assert env.plan_ref in log.text()

    def test_missing_file_no_session(self, tmp_path: Path):
        app, log = FakeApp(), FakeLog()
        _run(RunPlanCommand(), _ctx(app, log), str(tmp_path / "nope.md"))
        assert app.client.create_calls == []
        assert "not found" in log.text()

    def test_invalid_envelope_refused_no_session(self, tmp_path: Path):
        plan = tmp_path / "bad.md"
        plan.write_text("---\nplan_version: 0\n---\nno required fields\n")
        app, log = FakeApp(), FakeLog()
        _run(RunPlanCommand(), _ctx(app, log), str(plan))
        assert app.client.create_calls == []
        assert "invalid_plan_envelope" in log.text()

    def test_governed_candidate_never_executes(self, tmp_path: Path):
        d = "sha256:" + "a" * 64
        plan = tmp_path / "gov.md"
        plan.write_text(
            HUMAN_PLAN.replace(
                "---\n\nBackground prose.",
                "governance:\n"
                "  authority_system: ag\n"
                "  playbook_id: \"chore.x\"\n"
                f"  playbook_digest: \"{d}\"\n"
                f"  ration_card_digest: \"{d}\"\n"
                "  governance_status: candidate\n"
                "---\n\nBackground prose.",
            )
        )
        app, log = FakeApp(), FakeLog()
        _run(RunPlanCommand(), _ctx(app, log), str(plan))
        assert app.client.create_calls == []
        assert "governance_not_approved" in log.text()

    def test_governed_approved_with_witness_executes(self, tmp_path: Path):
        playbook = b"pb"
        ration = b"rc"
        d1 = "sha256:" + hashlib.sha256(playbook).hexdigest()
        d2 = "sha256:" + hashlib.sha256(ration).hexdigest()
        plan = tmp_path / "gov-ok.md"
        plan.write_text(
            HUMAN_PLAN.replace(
                "---\n\nBackground prose.",
                "governance:\n"
                "  authority_system: ag\n"
                "  playbook_id: \"chore.x\"\n"
                f"  playbook_digest: \"{d1}\"\n"
                f"  ration_card_digest: \"{d2}\"\n"
                "  approval_ref: \"operator:act\"\n"
                "  governance_status: approved\n"
                "---\n\nBackground prose.",
            )
        )
        store = {d1: playbook, d2: ration, "operator:act": b"act-record"}
        app, log = FakeApp(), FakeLog()
        _run(RunPlanCommand(witness_resolver=store.get), _ctx(app, log), str(plan))
        assert len(app.client.create_calls) == 1
        assert "witnessed citations" in log.text()

    def test_governed_approved_without_witness_fails_closed(self, tmp_path: Path):
        d = "sha256:" + "a" * 64
        plan = tmp_path / "gov-unwitnessed.md"
        plan.write_text(
            HUMAN_PLAN.replace(
                "---\n\nBackground prose.",
                "governance:\n"
                "  authority_system: ag\n"
                "  playbook_id: \"chore.x\"\n"
                f"  playbook_digest: \"{d}\"\n"
                f"  ration_card_digest: \"{d}\"\n"
                "  approval_ref: \"operator:act\"\n"
                "  governance_status: approved\n"
                "---\n\nBackground prose.",
            )
        )
        app, log = FakeApp(), FakeLog()
        _run(RunPlanCommand(), _ctx(app, log), str(plan))  # no resolver wired
        assert app.client.create_calls == []
        assert "governance_approval_unverified" in log.text()


def test_compose_task_text_never_invents_steps():
    env = parse_plan_envelope(HUMAN_PLAN)
    text = compose_task_text(env)
    assert text.count("- ") == 1  # exactly the one advisory step, verbatim


class TestFileWitnessResolver:
    def test_digest_resolved_by_content_not_filename(self, tmp_path: Path):
        from maude.plan.witness import file_witness_resolver

        artifact = b"queue-item-bytes"
        digest = "sha256:" + hashlib.sha256(artifact).hexdigest()
        (tmp_path / "arbitrary-name.json").write_bytes(artifact)
        resolve = file_witness_resolver(tmp_path)
        assert resolve(digest) == artifact
        assert resolve("sha256:" + "0" * 64) is None

    def test_ref_resolved_by_sanitized_filename(self, tmp_path: Path):
        from maude.plan.witness import file_witness_resolver, sanitize_ref

        ref = "operator:queued_playbook.operator_approved:2026-07-04"
        (tmp_path / sanitize_ref(ref)).write_bytes(b"act record")
        resolve = file_witness_resolver(tmp_path)
        assert resolve(ref) == b"act record"
        assert resolve("operator:unknown") is None

    def test_missing_directory_fails_closed(self, tmp_path: Path):
        from maude.plan.witness import file_witness_resolver

        resolve = file_witness_resolver(tmp_path / "does-not-exist")
        assert resolve("sha256:" + "a" * 64) is None
