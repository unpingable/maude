# SPDX-License-Identifier: Apache-2.0
"""M-2 runner tests — `run <plan.md>` against fakes. Pins: refusals create no
session; the happy path maps M-1 fields to runtime.session.create verbatim;
governed candidates never execute."""

from __future__ import annotations

import asyncio
import hashlib
import json
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
        self.grant_calls: list[dict] = []

    async def runtime_session_create(self, **params):
        self.create_calls.append(params)
        return {"session_id": "sess-1"}

    async def runtime_session_launch(self, session_id: str):
        self.launch_calls.append(session_id)
        return {"status": "running", "pid": 4242}

    async def runtime_grant_activate(self, session_id, execution_request, witness_bytes=None):
        self.grant_calls.append({
            "session_id": session_id,
            "execution_request": execution_request,
            "witness_bytes": witness_bytes,
        })
        return {"grant_id": "sgr_test000000", "enforcement": "declared-effects-only"}


class FakeApp:
    def __init__(self) -> None:
        self.client = FakeClient()


def _ctx(app: FakeApp, log: FakeLog, text: str = "") -> CommandContext:
    return CommandContext(app=app, log=log, text=text)


HUMAN_PLAN = """\
---
plan_version: 1
goal: "Do the thing"
workspace: "/tmp/proj"
submitter_kind: human
plan_origin: human_written
provenance:
  author: "operator"
harness: claude_code
execution_request:
  write_paths: ["src/**"]
steps:
  - "step one"
stop_conditions:
  forbidden_paths: ["infra/**"]
---

Background prose.
"""


# S7: a RationCard that CONTAINS HUMAN_PLAN's execution_request (src/**) and the
# cargo commands, plus the projected citation binding the request to it. A
# governed v1 plan is admitted only if its request is cited AND contained.
S7_RATION_SRC = json.dumps(
    {"allowed_write_paths": ["src/**"], "allowed_shell_commands": ["cargo test", "cargo build"]}
).encode()
_S7_PROJECTED_WRITE = (
    '  projected:\n    execution_request.write_paths: "ration_card:{d2}"\n'
)


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

    def test_run_plan_with_model_flag_routes_and_forwards(self):
        # NS-0 coverage gap: the runner learned --model but the classifier
        # regex ended at .md, so `run <plan.md> --model X` fell through to
        # chat and the pin never reached the runner. The trailing flag must
        # route to RUN_PLAN and be forwarded verbatim.
        intent = parse_intent("run docs/plans/foo.md --model claude-haiku-4-5")
        assert intent.kind == IntentKind.RUN_PLAN
        assert intent.payload == "docs/plans/foo.md --model claude-haiku-4-5"

    def test_run_plan_missing_model_value_still_routes_to_runner(self):
        # A malformed flag still routes to the runner, which owns validation
        # (it refuses "--model needs a value") — better than a silent chat.
        intent = parse_intent("run docs/plans/foo.md --model")
        assert intent.kind == IntentKind.RUN_PLAN
        assert intent.payload == "docs/plans/foo.md --model"


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

    def test_model_flag_pins_harness_args(self, tmp_path: Path):
        """NS-0: `run <plan> --model X` threads the operator's model choice as
        harness_args; the plan envelope itself never dictates spend."""
        plan = tmp_path / "plan.md"
        plan.write_text(HUMAN_PLAN)
        app, log = FakeApp(), FakeLog()
        _run(RunPlanCommand(), _ctx(app, log), f"{plan} --model claude-haiku-4-5")
        call = app.client.create_calls[0]
        assert call["harness_args"] == ["--model", "claude-haiku-4-5"]
        assert "model pinned: claude-haiku-4-5" in log.text()

    def test_no_model_flag_no_harness_args(self, tmp_path: Path):
        plan = tmp_path / "plan.md"
        plan.write_text(HUMAN_PLAN)
        app, log = FakeApp(), FakeLog()
        _run(RunPlanCommand(), _ctx(app, log), str(plan))
        assert app.client.create_calls[0].get("harness_args", []) == []

    def test_model_flag_missing_value_refuses_before_session(self, tmp_path: Path):
        plan = tmp_path / "plan.md"
        plan.write_text(HUMAN_PLAN)
        app, log = FakeApp(), FakeLog()
        _run(RunPlanCommand(), _ctx(app, log), f"{plan} --model")
        assert app.client.create_calls == []
        assert "--model needs a value" in log.text()

    def test_ungoverned_launch_does_not_fence_dirty(self, tmp_path: Path):
        # An ungoverned plan carries no approval acts to fence; the workspace
        # baseline is the operator's own, not the run's. allow_dirty stays off
        # (default behaviour preserved).
        plan = tmp_path / "plan.md"
        plan.write_text(HUMAN_PLAN)
        app, log = FakeApp(), FakeLog()
        _run(RunPlanCommand(), _ctx(app, log), str(plan))
        assert app.client.create_calls[0].get("allow_dirty", False) is False

    def test_missing_file_no_session(self, tmp_path: Path):
        app, log = FakeApp(), FakeLog()
        _run(RunPlanCommand(), _ctx(app, log), str(tmp_path / "nope.md"))
        assert app.client.create_calls == []
        assert "not found" in log.text()

    def test_invalid_envelope_refused_no_session(self, tmp_path: Path):
        plan = tmp_path / "bad.md"
        plan.write_text("---\nplan_version: 1\n---\nno required fields\n")
        app, log = FakeApp(), FakeLog()
        _run(RunPlanCommand(), _ctx(app, log), str(plan))
        assert app.client.create_calls == []
        # Surface is plain-ops; the raw refusal code moves to the `why` stash.
        assert "malformed" in log.text()
        assert app._last_plan_block[0] == "invalid_plan_envelope"

    def test_crlf_copy_of_frozen_plan_not_aliased(self, tmp_path: Path, monkeypatch):
        # The frozen membership check is byte-exact: the runner reads true file
        # bytes (not universal-newline-normalized), so a CRLF copy of a frozen
        # LF specimen hashes differently and refuses as retired v0 — it does not
        # alias to the frozen LF hash. Approval attaches to bytes.
        lf = (
            "---\nplan_version: 0\ngoal: \"x\"\nworkspace: \"/tmp/p\"\n"
            "submitter_kind: human\nplan_origin: human_written\n"
            "provenance:\n  author: \"op\"\nscope_allowlist: [\"src/**\"]\n---\n\nbody\n"
        )
        lf_ref = "sha256:" + hashlib.sha256(lf.encode()).hexdigest()
        monkeypatch.setattr(
            "maude.plan.envelope.FROZEN_V0_PLAN_REFS", frozenset({lf_ref})
        )
        # the LF bytes ARE the frozen specimen and parse as v0
        assert parse_plan_envelope(lf).plan_version == 0
        # a CRLF copy on disk is different bytes -> not frozen -> refuses
        crlf_path = tmp_path / "crlf.md"
        crlf_path.write_bytes(lf.replace("\n", "\r\n").encode())
        app, log = FakeApp(), FakeLog()
        _run(RunPlanCommand(), _ctx(app, log), str(crlf_path))
        assert app.client.create_calls == []
        assert app._last_plan_block[0] == "invalid_plan_envelope"

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
        assert "Not approved" in log.text()
        assert app._last_plan_block[0] == "governance_not_approved"

    def test_governed_approved_with_witness_executes(self, tmp_path: Path):
        playbook = b"pb"
        ration = S7_RATION_SRC
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
                + _S7_PROJECTED_WRITE.format(d2=d2)
                + "---\n\nBackground prose.",
            )
        )
        store = {d1: playbook, d2: ration, "operator:act": b"act-record"}
        app, log = FakeApp(), FakeLog()
        _run(RunPlanCommand(witness_resolver=store.get), _ctx(app, log), str(plan))
        assert len(app.client.create_calls) == 1
        assert "verified references" in log.text()
        # A governed plan's flip (queue latch + approval-witness file + plan
        # promotion) dirties the workspace before the run; those edits are the
        # citations admission just verified. Launch fences them (GAP-N) so the
        # run refuses nothing on their account and discard can't revert them.
        assert app.client.create_calls[0].get("allow_dirty") is True
        assert "fenced from this run's" in log.text()

    def test_governed_approved_attaches_execution_grant(self, tmp_path: Path):
        # S4/S6: an approved run projects the first-class execution_request block
        # into a grant and attaches it, so in-envelope actions won't re-prompt.
        d1 = "sha256:" + hashlib.sha256(b"pb").hexdigest()
        # S7: a RationCard that contains the request, and both dimensions cited.
        ration = json.dumps(
            {
                "allowed_write_paths": ["crates/nightshiftd/src/**"],
                "allowed_shell_commands": ["cargo test", "cargo build"],
            }
        ).encode()
        d2 = "sha256:" + hashlib.sha256(ration).hexdigest()
        plan = tmp_path / "gov-grant.md"
        plan.write_text(
            "---\n"
            "plan_version: 1\n"
            'goal: "x"\n'
            'workspace: "/tmp/proj"\n'
            "submitter_kind: human\n"
            "plan_origin: human_written\n"
            "provenance:\n"
            '  author: "operator"\n'
            "harness: claude_code\n"
            "execution_request:\n"
            "  write_paths:\n"
            '    - "crates/nightshiftd/src/**"\n'
            "  commands:\n"
            "    - {program: cargo, argv_prefix: [test]}\n"
            "    - {program: cargo, argv_prefix: [build]}\n"
            "steps:\n"
            '  - "step one"\n'
            "governance:\n"
            "  authority_system: ag\n"
            '  playbook_id: "chore.x"\n'
            f'  playbook_digest: "{d1}"\n'
            f'  ration_card_digest: "{d2}"\n'
            '  approval_ref: "operator_plan_approved"\n'
            "  governance_status: approved\n"
            "  projected:\n"
            f'    execution_request.write_paths: "ration_card:{d2}"\n'
            f'    execution_request.commands: "ration_card:{d2}"\n'
            "---\n\nprose.\n"
        )
        witness = b"operator approved"
        store = {d1: b"pb", d2: ration, "operator_plan_approved": witness}
        app, log = FakeApp(), FakeLog()
        _run(RunPlanCommand(witness_resolver=store.get), _ctx(app, log), str(plan))
        assert len(app.client.grant_calls) == 1
        req = app.client.grant_calls[0]["execution_request"]
        assert req["write_paths"] == ["crates/nightshiftd/src/**"]
        assert req["commands"] == [
            {"program": "cargo", "argv_prefix": ["test"]},
            {"program": "cargo", "argv_prefix": ["build"]},
        ]
        assert app.client.grant_calls[0]["witness_bytes"] == witness.decode()
        assert "grant sgr_" in log.text()

    def test_ungoverned_run_attaches_no_grant(self, tmp_path: Path):
        plan = tmp_path / "plain.md"
        plan.write_text(HUMAN_PLAN)
        app, log = FakeApp(), FakeLog()
        _run(RunPlanCommand(), _ctx(app, log), str(plan))
        assert app.client.grant_calls == []

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
        assert "verify the approval" in log.text()
        assert app._last_plan_block[0] == "governance_approval_unverified"


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

    def test_colocated_witnesses_admit_without_explicit_resolver(self, tmp_path: Path):
        """Default resolver = the plan file's own directory (CD-4 layout)."""
        playbook = b"pb-bytes"
        ration = S7_RATION_SRC
        d1 = "sha256:" + hashlib.sha256(playbook).hexdigest()
        d2 = "sha256:" + hashlib.sha256(ration).hexdigest()
        (tmp_path / "playbook.yaml").write_bytes(playbook)
        (tmp_path / "ration_card.json").write_bytes(ration)
        from maude.plan.witness import sanitize_ref

        (tmp_path / sanitize_ref("operator:act")).write_bytes(b"act record")
        plan = tmp_path / "gov-colocated.md"
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
                + _S7_PROJECTED_WRITE.format(d2=d2)
                + "---\n\nBackground prose.",
            )
        )
        app, log = FakeApp(), FakeLog()
        _run(RunPlanCommand(), _ctx(app, log), str(plan))  # no resolver injected
        assert len(app.client.create_calls) == 1
        assert "verified references" in log.text()
