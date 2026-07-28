#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Local fake-process self-test for the provider-specific auth boundaries.

This test never invokes a model provider, Bubblewrap, the network, or real
credentials.  Codex cases exercise the early-scrub gate with a synthetic
``/proc/*/mountinfo`` view.  Claude cases exercise retained-through-transport
auth destruction, exact MCP roster enforcement, delayed prompt delivery, and
tool/result correlation with disposable local Python processes.  All
diagnostics and fake secrets live under one fresh directory in ``/tmp``.
"""

from __future__ import annotations

import contextlib
import json
import os
import signal
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import campaign_common as common
import campaign_runner as runner
import operator_pty as pty_adapter


ConcretePath = type(Path())


class AuditPath(ConcretePath):
    """Real paths with controlled auth-tree and clean-HOME mountinfo lines."""

    mount_read_only = False

    def read_text(self, *args: Any, **kwargs: Any) -> str:
        if (
            self.name == "mountinfo"
            and self.parent.name.isdigit()
            and self.parent.parent == AuditPath("/proc")
        ):
            auth_options = (
                "ro,nosuid,nodev" if self.mount_read_only else "rw"
            )
            return (
                "123 45 0:1 / /run/provider-auth "
                f"{auth_options} - bind fake-provider-auth rw\n"
                "124 45 0:2 / /home/operator rw,nosuid,nodev "
                "- bind fake-clean-home rw\n"
            )
        return super().read_text(*args, **kwargs)


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def event(value: dict[str, Any]) -> str:
    return json.dumps(value, separators=(",", ":"))


def process_state(pid: int) -> str | None:
    try:
        raw = (Path("/proc") / str(pid) / "stat").read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    return raw[raw.rfind(")") + 2 :].split()[0]


def kill_test_process(pid: int) -> None:
    """Best-effort cleanup for a test-owned child if an invariant fails."""

    if process_state(pid) in {None, "Z"}:
        return
    try:
        pidfd = os.pidfd_open(pid)
    except (ProcessLookupError, PermissionError, OSError):
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)
        return
    try:
        with contextlib.suppress(ProcessLookupError):
            signal.pidfd_send_signal(pidfd, signal.SIGKILL)
    finally:
        os.close(pidfd)


def run_gate_case(
    diagnostics_root: Path,
    *,
    name: str,
    provider: str,
    source: str,
    expect_success: bool,
    read_only_home: bool = False,
    expected_gate_status: str | None = None,
    expected_remaining_files: list[str] | None = None,
) -> dict[str, Any]:
    case_root = diagnostics_root / "cases" / name
    case_root.mkdir(parents=True)
    provider_home = case_root / "provider-home"
    provider_home.mkdir()
    auth_path = provider_home / "auth.json"
    secret = f"fake-auth-material-{name}-123456789".encode("utf-8")
    auth_path.write_bytes(secret)
    stdout_path = case_root / "stdout.jsonl"
    stderr_path = case_root / "stderr"
    gate_path = case_root / "gate.json"
    AuditPath.mount_read_only = read_only_home
    source = source.replace("__AUTH_PATH__", str(auth_path)).replace(
        "__SECRET__", secret.decode("utf-8")
    ).replace(
        "__PROVIDER_HOME__", str(provider_home)
    )
    # The production Codex argv has an outer Bubblewrap monitor and an inner
    # provider process in the same process group.  Reproduce that process-tree
    # shape locally so the gate proves mounts for an isolated member rather
    # than incorrectly treating the host-side monitor as the model process.
    monitor_source = (
        "import subprocess;"
        f"child=subprocess.Popen(['/usr/bin/python3','-c',{source!r}]);"
        "raise SystemExit(child.wait())"
    )

    observed: dict[str, Any]
    process_result: dict[str, Any] | None = None
    try:
        process_result = runner._run_model_process(
            ["/usr/bin/python3", "-c", monitor_source],
            cwd=case_root,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            timeout=15,
            provider=provider,
            provider_home=provider_home,
            copied_auth=["auth.json"],
            credential_values=[secret],
            gate_record_path=gate_path,
        )
    except BaseException as exc:
        observed = {"type": type(exc).__name__, "message": str(exc)}
    else:
        observed = {"type": "returned", "message": None}

    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    if expect_success:
        assert observed["type"] == "returned", observed
        assert process_result is not None
        assert process_result["returncode"] == 0
        assert not process_result["timed_out"]
        assert gate["resumed_after_proof"] is True
        assert (
            gate["provider_auth_tree_remained_credential_free_through_exit"]
            is True
        )
        assert gate["retained_auth_file_descriptors"] == []
        assert gate["auth_paths_visible_after_scrub"] == []
        milestone_names = [item["name"] for item in gate["milestones"]]
        assert milestone_names.index("sigcont_sent") < milestone_names.index(
            "first_post_scrub_semantic_event"
        )
    else:
        assert observed["type"] == "CampaignError", observed
        assert gate["resumed_after_proof"] is False
        if expected_gate_status is not None:
            assert gate["status"] == expected_gate_status
        if "provider_tree_remaining_after_cleanup" in gate:
            assert gate["provider_tree_remaining_after_cleanup"] == []

    assert not auth_path.exists()
    remaining_files = sorted(
        str(path.relative_to(provider_home))
        for path in provider_home.rglob("*")
        if path.is_file()
    )
    assert remaining_files == (expected_remaining_files or [])
    return {
        "name": name,
        "provider": provider,
        "expected": "success" if expect_success else "failed_closed",
        "observed": observed,
        "gate_status": gate.get("status", "completed"),
        "auth_path_absent": not auth_path.exists(),
        "provider_home_remaining_files": remaining_files,
        "gate_path": str(gate_path),
        "stdout_path": str(stdout_path) if stdout_path.exists() else None,
        "stderr_path": str(stderr_path) if stderr_path.exists() else None,
        "quarantine": gate.get("quarantine"),
    }


def baseline_gate_cases(diagnostics_root: Path) -> dict[str, Any]:
    codex_identity = event({"type": "thread.started", "thread_id": "fake-codex-thread"})
    assistant = event({"type": "assistant", "text": "ok"})
    codex_events = [
        event({"type": "turn.started"}),
        event(
            {
                "type": "item.started",
                "item": {
                    "id": "fake-item",
                    "type": "command_execution",
                    "command": "/usr/bin/true",
                    "status": "in_progress",
                },
            }
        ),
        event(
            {
                "type": "item.completed",
                "item": {
                    "id": "fake-item",
                    "type": "command_execution",
                    "command": "/usr/bin/true",
                    "status": "completed",
                    "exit_code": 0,
                },
            }
        ),
        event({"type": "turn.completed"}),
    ]
    credential_assistant = event({"type": "assistant", "text": "__SECRET__"})
    cases = [
        run_gate_case(
            diagnostics_root,
            name="normal-codex-simple",
            provider="openai-sol",
            source=(
                "import time;"
                f"print({codex_identity!r},flush=True);"
                "time.sleep(0.4);"
                f"print({assistant!r},flush=True)"
            ),
            expect_success=True,
        ),
        run_gate_case(
            diagnostics_root,
            name="normal-codex",
            provider="openai-sol",
            source=(
                "import time;"
                f"print({codex_identity!r},flush=True);"
                "time.sleep(0.4);"
                + "".join(f"print({value!r},flush=True);" for value in codex_events)
            ),
            expect_success=True,
        ),
        run_gate_case(
            diagnostics_root,
            name="noncredential-provider-state",
            provider="openai-sol",
            source=(
                "import pathlib,time;"
                "state=pathlib.Path('__PROVIDER_HOME__/.codex/state.bin');"
                "state.parent.mkdir(parents=True,exist_ok=True);"
                "state.write_text('disposable noncredential state');"
                f"print({codex_identity!r},flush=True);"
                "time.sleep(0.4);"
                f"print({assistant!r},flush=True)"
            ),
            expect_success=True,
            expected_remaining_files=[".codex/state.bin"],
        ),
        run_gate_case(
            diagnostics_root,
            name="credential-in-provider-state",
            provider="openai-sol",
            source=(
                "import pathlib,time;"
                "state=pathlib.Path('__PROVIDER_HOME__/.codex/state.bin');"
                "state.parent.mkdir(parents=True,exist_ok=True);"
                "state.write_text('__SECRET__');"
                f"print({codex_identity!r},flush=True);"
                "time.sleep(5)"
            ),
            expect_success=False,
            expected_gate_status="failed_closed",
            expected_remaining_files=[".codex/state.bin"],
        ),
        run_gate_case(
            diagnostics_root,
            name="identity-assistant-one-write",
            provider="openai-sol",
            source=(
                "import os,time;"
                f"os.write(1,({codex_identity!r}+'\\n'+"
                f"{assistant!r}+'\\n').encode());"
                "time.sleep(5)"
            ),
            expect_success=False,
            expected_gate_status="failed_closed",
        ),
        run_gate_case(
            diagnostics_root,
            name="identity-partial-non-json",
            provider="openai-sol",
            source=(
                "import os,time;"
                f"os.write(1,({codex_identity!r}+'\\n'+"
                "'not-json-partial').encode());"
                "time.sleep(5)"
            ),
            expect_success=False,
            expected_gate_status="failed_closed",
        ),
        run_gate_case(
            diagnostics_root,
            name="retained-auth-fd",
            provider="openai-sol",
            source=(
                "import time;"
                "held=open('__AUTH_PATH__','rb');"
                f"print({codex_identity!r},flush=True);"
                "time.sleep(5)"
            ),
            expect_success=False,
            expected_gate_status="failed_closed",
        ),
        run_gate_case(
            diagnostics_root,
            name="read-only-provider-home",
            provider="openai-sol",
            source=(f"import time;print({codex_identity!r},flush=True);time.sleep(5)"),
            expect_success=False,
            read_only_home=True,
            expected_gate_status="failed_closed",
        ),
        run_gate_case(
            diagnostics_root,
            name="non-json-before-identity",
            provider="openai-sol",
            source="print('not-json',flush=True)",
            expect_success=False,
            expected_gate_status="failed_closed",
        ),
        run_gate_case(
            diagnostics_root,
            name="credential-output-quarantine",
            provider="openai-sol",
            source=(
                "import os,time;"
                f"os.write(1,({codex_identity!r}+'\\n'+"
                f"{credential_assistant!r}+'\\n').encode());"
                "time.sleep(5)"
            ),
            expect_success=False,
            expected_gate_status="failed_closed_secret_quarantine",
        ),
    ]
    return {"cases": cases, "all_passed": len(cases) == 10}


def stop_before_persistence(diagnostics_root: Path) -> dict[str, Any]:
    trace: list[str] = []
    original_write_json = runner.write_json
    original_killpg = runner.os.killpg
    case_root = diagnostics_root / "cases" / "stop-before-persistence"
    gate_path = case_root / "gate.json"

    def traced_write_json(*args: Any, **kwargs: Any) -> None:
        trace.append("write_json")
        original_write_json(*args, **kwargs)

    def traced_killpg(pid: int, requested_signal: int) -> None:
        if requested_signal == signal.SIGSTOP:
            trace.append(
                "killpg_SIGSTOP_gate_absent"
                if not gate_path.exists()
                else "killpg_SIGSTOP_gate_present"
            )
        else:
            trace.append(f"killpg_{int(requested_signal)}")
        original_killpg(pid, requested_signal)

    runner.write_json = traced_write_json
    runner.os.killpg = traced_killpg
    identity = event({"type": "thread.started", "thread_id": "ordering"})
    assistant = event({"type": "assistant", "text": "ok"})
    try:
        result = run_gate_case(
            diagnostics_root,
            name="stop-before-persistence",
            provider="openai-sol",
            source=(
                "import time;"
                f"print({identity!r},flush=True);"
                "time.sleep(0.4);"
                f"print({assistant!r},flush=True)"
            ),
            expect_success=True,
        )
    finally:
        runner.write_json = original_write_json
        runner.os.killpg = original_killpg
    assert trace
    assert trace[0] == "killpg_SIGSTOP_gate_absent", trace
    assert "write_json" in trace[1:], trace
    return {"trace": trace, "case": result, "all_passed": True}


def action_and_marker_matrix() -> dict[str, Any]:
    def claude_use(identity: str) -> dict[str, Any]:
        return {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": identity,
                        "name": "mcp__operator__terminal",
                        "input": {"operation": "exec", "argv": ["/usr/bin/true"]},
                    }
                ]
            },
        }

    def claude_result(identity: str, *, is_error: bool = False) -> dict[str, Any]:
        return {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": identity,
                        "is_error": is_error,
                    }
                ]
            },
        }

    def codex_result(identity: str, exit_code: int = 0) -> dict[str, Any]:
        return {
            "type": "item.completed",
            "item": {
                "id": identity,
                "type": "command_execution",
                "status": "completed",
                "exit_code": exit_code,
            },
        }

    claude_marker = {"type": "result", "result": "AUTH_GATE_PROBE_OK"}
    codex_marker = {
        "type": "item.completed",
        "item": {
            "id": "marker",
            "type": "agent_message",
            "text": "AUTH_GATE_PROBE_OK",
        },
    }

    def accepted(events: list[dict[str, Any]]) -> bool:
        completed = runner._completed_action_event_records(events)
        successful = [item for item in completed if item["succeeded"]]
        markers = [
            item
            for item in runner._final_answer_records(events)
            if "AUTH_GATE_PROBE_OK" in item["text"]
        ]
        return bool(
            len(successful) >= 2
            and len({item["event_number"] for item in successful}) >= 2
            and markers
            and min(item["event_number"] for item in markers)
            > max(item["event_number"] for item in successful)
        )

    observed = {
        "claude_good": accepted(
            [
                claude_use("a"),
                claude_result("a"),
                claude_use("b"),
                claude_result("b"),
                claude_marker,
            ]
        ),
        "claude_no_results": accepted(
            [claude_use("a"), claude_use("b"), claude_marker]
        ),
        "claude_error": accepted(
            [
                claude_use("a"),
                claude_result("a"),
                claude_use("b"),
                claude_result("b", is_error=True),
                claude_marker,
            ]
        ),
        "codex_good": accepted([codex_result("a"), codex_result("b"), codex_marker]),
        "codex_nonzero": accepted(
            [codex_result("a"), codex_result("b", 1), codex_marker]
        ),
        "codex_marker_early": accepted(
            [codex_result("a"), codex_marker, codex_result("b")]
        ),
    }
    expected = {
        "claude_good": True,
        "claude_no_results": False,
        "claude_error": False,
        "codex_good": True,
        "codex_nonzero": False,
        "codex_marker_early": False,
    }
    assert observed == expected, observed
    codex_action_events = [
        {
            "type": "item.started",
            "item": {
                "id": "cmd-1",
                "type": "command_execution",
                "command": "./maude status",
                "status": "in_progress",
            },
        },
        {
            "type": "item.completed",
            "item": {
                "id": "cmd-1",
                "type": "command_execution",
                "command": "./maude status",
                "status": "completed",
                "exit_code": 0,
            },
        },
        {
            "type": "item.started",
            "item": {
                "id": "patch-1",
                "type": "file_change",
                "changes": [{"path": "synthetic.txt", "kind": "update"}],
                "status": "in_progress",
            },
        },
        {
            "type": "item.completed",
            "item": {
                "id": "patch-1",
                "type": "file_change",
                "changes": [{"path": "synthetic.txt", "kind": "update"}],
                "status": "completed",
            },
        },
        {
            "type": "item.completed",
            "item": {
                "id": "future-1",
                "type": "future_action_type",
                "payload": {"bounded": True},
                "status": "completed",
            },
        },
        {
            "type": "item.completed",
            "item": {
                "id": "message-1",
                "type": "agent_message",
                "text": "done",
            },
        },
    ]
    captured = runner._event_actions(codex_action_events)
    accounting = runner._action_accounting(codex_action_events, captured)
    assert len(captured) == 3
    assert captured[1]["tool"] == "file_change/apply_patch"
    assert captured[2]["classification"] == "unexpected_action"
    assert accounting["all_provider_actions_represented_once"] is True
    assert accounting["unexpected_action_types"] == ["future_action_type"]
    tampered = runner._action_accounting(codex_action_events, captured[:-1])
    assert tampered["all_provider_actions_represented_once"] is False
    assert tampered["unrepresented_action_references"] == [
        "codex:future-1"
    ]
    return {
        "observed": observed,
        "expected": expected,
        "codex_action_types_captured": [
            value["tool"] for value in captured
        ],
        "action_accounting": accounting,
        "tamper_detected": True,
        "all_passed": True,
    }


def _prepare_local_claude_case(
    diagnostics_root: Path,
    name: str,
) -> dict[str, Any]:
    """Create fake private transport state without copying host credentials."""

    case_root = diagnostics_root / "claude-cases" / name
    case_root.mkdir(parents=True)
    provider_home = case_root / "provider-home"
    provider_home.mkdir()
    (provider_home / "tmp").mkdir()
    secret = f"fake-claude-auth-material-{name}-123456789".encode("utf-8")
    (provider_home / "auth.json").write_bytes(secret)
    transport_cwd = case_root / "transport-cwd"
    transport_cwd.mkdir()
    private_state = case_root / "private-mcp-state"
    private_state.mkdir()
    proxy_ready = private_state / "proxy-ready.json"
    proxy_trace = private_state / "proxy-trace.jsonl"
    prompt_probe = private_state / "prompt-probe.json"
    mcp_config = {
        "mcpServers": {
            "grader": {
                "command": "/usr/bin/false",
                "args": ["synthetic-selftest-never-executed"],
            }
        }
    }
    provider_environment = {
        "HOME": str(provider_home),
        "TMPDIR": str(provider_home / "tmp"),
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
    }
    boundary = {
        "schema": "maude.synthetic-operator.claude-mcp-boundary.v1",
        "label": f"local-selftest-{name}",
        "mode": "grader",
        "private_state": private_state,
        "bridge": runner.CLAUDE_MCP_BRIDGE_SOURCE,
        "bridge_sha256": runner.sha256_file(
            runner.CLAUDE_MCP_BRIDGE_SOURCE
        ),
        "transport_cwd": transport_cwd,
        "proxy_bwrap_argv": [
            str(runner.BWRAP),
            "--synthetic-selftest-never-executed",
        ],
        "proxy_ready": proxy_ready,
        "proxy_trace": proxy_trace,
        "mcp_protocol_version": runner.CLAUDE_MCP_PROTOCOL_VERSION,
        "mcp_config": mcp_config,
        "mcp_config_sha256": runner.sha256_bytes(
            runner._canonical_json_bytes(mcp_config)
        ),
        "allowed_tools": list(runner.CLAUDE_GRADER_TOOLS),
        "server": runner.CLAUDE_GRADER_SERVER,
        "provider_environment": provider_environment,
        "provider_home": provider_home,
        "operator_home": None,
        "command_broker": None,
        "pty_broker": None,
        "private_socket_directories": [],
        "unix_socket_contract": {
            "path_budget_bytes": runner.UNIX_SOCKET_PATH_BUDGET,
            "private_arena_root": str(runner.PRIVATE_SOCKET_ROOT),
            "command_socket_host": None,
            "command_socket_host_bytes": None,
            "command_socket_proxy": None,
        },
    }
    return {
        "case_root": case_root,
        "provider_home": provider_home,
        "secret": secret,
        "stdout_path": case_root / "stdout.jsonl",
        "stderr_path": case_root / "stderr",
        "gate_path": case_root / "gate.json",
        "boundary": boundary,
        "prompt_probe": prompt_probe,
    }


def _local_claude_transport_source(
    *,
    boundary: dict[str, Any],
    prompt_probe: Path,
    user_prompt: str,
    reported_tools: list[str],
    emit_tool_exchange: bool,
) -> str:
    """Return a provider-free stream-json transport fixture."""

    bare_tools = [
        value.rsplit("__", 1)[-1] for value in boundary["allowed_tools"]
    ]
    tools_list_digest = runner.sha256_bytes(
        runner._canonical_json_bytes(
            {"tools": [{"name": value} for value in bare_tools]}
        )
    )
    ready = {
        "schema": "maude.synthetic-operator.claude-mcp-ready.v1",
        "mode": "grader",
        "protocol_version_requested": runner.CLAUDE_MCP_PROTOCOL_VERSION,
        "protocol_version_negotiated": runner.CLAUDE_MCP_PROTOCOL_VERSION,
        "tools": bare_tools,
        "tools_list_response_sha256": tools_list_digest,
        "initialize_message_ordinal": 2,
        "tools_list_message_ordinal": 4,
    }
    initialize_trace = {
        "schema": "maude.synthetic-operator.mcp-correlation-event.v1",
        "message_ordinal": 2,
        "protocol_event": "initialize-response-flushed",
        "protocol_version_requested": runner.CLAUDE_MCP_PROTOCOL_VERSION,
        "protocol_version_negotiated": runner.CLAUDE_MCP_PROTOCOL_VERSION,
        "initialize_accepted": True,
        "response_sha256": "1" * 64,
    }
    initialized_trace = {
        "schema": "maude.synthetic-operator.mcp-correlation-event.v1",
        "message_ordinal": 3,
        "protocol_event": "notifications/initialized",
        "protocol_version": runner.CLAUDE_MCP_PROTOCOL_VERSION,
    }
    tools_list_trace = {
        "schema": "maude.synthetic-operator.mcp-correlation-event.v1",
        "message_ordinal": 4,
        "protocol_event": "tools-list-response-flushed",
        "protocol_version": runner.CLAUDE_MCP_PROTOCOL_VERSION,
        "tools": bare_tools,
        "response_sha256": tools_list_digest,
    }
    init = {
        "type": "system",
        "subtype": "init",
        "session_id": "local-fake-claude-session",
        "model": "sonnet",
        "tools": reported_tools,
        "cwd": str(boundary["provider_home"]),
    }
    expected_prompt = {
        "type": "user",
        "message": {"role": "user", "content": user_prompt},
    }
    arguments = {"operation": "read", "path": "evidence.txt"}
    result_text = json.dumps(
        {"content": "synthetic evidence", "status": "ok"},
        separators=(",", ":"),
        sort_keys=True,
    )
    trace = {
        "tool": "evidence",
        "arguments": arguments,
        "arguments_sha256": runner.sha256_bytes(
            runner._canonical_json_bytes(arguments)
        ),
        "result_text": result_text,
        "result_text_sha256": runner.sha256_bytes(
            result_text.encode("utf-8")
        ),
        "is_error": False,
    }
    tool_use = {
        "type": "assistant",
        "message": {
            "content": [
                {
                    "type": "tool_use",
                    "id": "local-tool-1",
                    "name": "mcp__grader__evidence",
                    "input": arguments,
                }
            ]
        },
    }
    tool_result = {
        "type": "user",
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "local-tool-1",
                    "is_error": False,
                    "content": result_text,
                }
            ]
        },
    }
    final_result = {
        "type": "result",
        "result": "AUTH_PRESENT_BEFORE_TRANSPORT_EXIT",
    }
    lines = [
        "import json,os,pathlib,select,sys,time",
        f"ready_path=pathlib.Path({str(boundary['proxy_ready'])!r})",
        f"trace_path=pathlib.Path({str(boundary['proxy_trace'])!r})",
        f"probe_path=pathlib.Path({str(prompt_probe)!r})",
        f"ready={ready!r}",
        f"initialize_trace={initialize_trace!r}",
        f"initialized_trace={initialized_trace!r}",
        f"tools_list_trace={tools_list_trace!r}",
        f"init={init!r}",
        f"expected_prompt={expected_prompt!r}",
        "premature=bool(select.select([sys.stdin.buffer],[],[],0.15)[0])",
        (
            "probe_path.write_text("
            "json.dumps({'withheld_before_ready':not premature})+'\\n',"
            "encoding='utf-8')"
        ),
        "if premature: raise SystemExit(41)",
        (
            "trace_path.write_text("
            "json.dumps(initialize_trace,separators=(',',':'),sort_keys=True)+"
            "'\\n'+json.dumps(initialized_trace,separators=(',',':'),"
            "sort_keys=True)+'\\n'+json.dumps(tools_list_trace,separators=(',',':'),"
            "sort_keys=True)+'\\n',encoding='utf-8')"
        ),
        (
            "ready_path.write_text("
            "json.dumps(ready,separators=(',',':'),sort_keys=True)+'\\n',"
            "encoding='utf-8')"
        ),
        "print(json.dumps(init,separators=(',',':')),flush=True)",
    ]
    if emit_tool_exchange:
        lines.extend(
            [
                "received=json.loads(sys.stdin.buffer.readline())",
                "if received != expected_prompt: raise SystemExit(42)",
                (
                    "auth_present=(pathlib.Path(os.environ['HOME'])/"
                    "'auth.json').is_file()"
                ),
                "if not auth_present: raise SystemExit(43)",
                (
                    "probe_path.write_text(json.dumps({"
                    "'withheld_before_ready':True,"
                    "'delivered_after_ready':True,"
                    "'auth_present_before_exit':True})+'\\n',"
                    "encoding='utf-8')"
                ),
                f"trace={trace!r}",
                (
                    "trace_file=trace_path.open('a',encoding='utf-8');"
                    "trace_file.write("
                    "json.dumps(trace,separators=(',',':'),sort_keys=True)+'\\n',"
                    ");trace_file.close()"
                ),
                f"print({event(tool_use)!r},flush=True)",
                f"print({event(tool_result)!r},flush=True)",
                f"print({event(final_result)!r},flush=True)",
            ]
        )
    else:
        lines.append("time.sleep(30)")
    return "\n".join(lines)


def _run_local_claude_case(
    diagnostics_root: Path,
    *,
    name: str,
    reported_tools: list[str],
    expect_success: bool,
) -> dict[str, Any]:
    prepared = _prepare_local_claude_case(diagnostics_root, name)
    boundary = prepared["boundary"]
    provider_home = prepared["provider_home"]
    auth_path = provider_home / "auth.json"
    secret = prepared["secret"]
    user_prompt = (
        "Read the supplied synthetic evidence and report its disposition."
    )
    source = _local_claude_transport_source(
        boundary=boundary,
        prompt_probe=prepared["prompt_probe"],
        user_prompt=user_prompt,
        reported_tools=reported_tools,
        emit_tool_exchange=expect_success,
    )
    original_binary = runner.CLAUDE_HOST_BINARY
    original_proxy_proof = runner._claude_proxy_runtime_proof
    proof_calls: list[dict[str, Any]] = []

    def local_proxy_proof(
        provider_pid: int,
        observed_boundary: dict[str, Any],
        auth_inodes: set[tuple[int, int]],
    ) -> dict[str, Any]:
        assert provider_pid > 0
        assert observed_boundary is boundary
        assert auth_inodes == {
            (auth_path.stat().st_dev, auth_path.stat().st_ino)
        }
        proof = {
            "observed_at": utc_now(),
            "synthetic_local_proxy": True,
            "provider_pid": provider_pid,
            "auth_inode_count": len(auth_inodes),
            "allowed_tools": boundary["allowed_tools"],
        }
        proof_calls.append(proof)
        return proof

    observed: dict[str, Any]
    process_result: dict[str, Any] | None = None
    runner.CLAUDE_HOST_BINARY = Path("/usr/bin/python3")
    runner._claude_proxy_runtime_proof = local_proxy_proof
    try:
        try:
            process_result = runner._run_model_process(
                ["/usr/bin/python3", "-c", source],
                cwd=boundary["transport_cwd"],
                stdout_path=prepared["stdout_path"],
                stderr_path=prepared["stderr_path"],
                timeout=10,
                provider="anthropic-sonnet",
                provider_home=provider_home,
                copied_auth=["auth.json"],
                credential_values=[secret],
                gate_record_path=prepared["gate_path"],
                claude_boundary=boundary,
                user_prompt=user_prompt,
                process_env=boundary["provider_environment"],
            )
        except BaseException as exc:
            observed = {"type": type(exc).__name__, "message": str(exc)}
        else:
            observed = {"type": "returned", "message": None}
    finally:
        runner.CLAUDE_HOST_BINARY = original_binary
        runner._claude_proxy_runtime_proof = original_proxy_proof

    gate = json.loads(prepared["gate_path"].read_text(encoding="utf-8"))
    stdout_bytes = prepared["stdout_path"].read_bytes()
    stderr_bytes = prepared["stderr_path"].read_bytes()
    assert not provider_home.exists()
    assert not auth_path.exists()
    assert secret not in stdout_bytes
    assert secret not in stderr_bytes
    assert str(provider_home).encode("utf-8") in stdout_bytes
    assert str(provider_home).encode("utf-8") not in stderr_bytes
    assert gate["provider_auth_retained_until_transport_exit"] is True
    assert gate["provider_auth_destroyed"] is True
    assert gate["provider_auth_mounted_in_mcp_or_command"] is False
    assert gate["host_source_mounted_in_mcp_or_command"] is False
    assert gate["allowed_tools"] == list(runner.CLAUDE_GRADER_TOOLS)
    assert gate["built_in_tools_allowed"] == []
    assert gate["transport_metadata_path_disclosures"] == [
        {
            "event_number": 1,
            "event_type": "system",
            "event_subtype": "init",
            "json_pointer": "/cwd",
            "path_kind": "provider_private_home",
            "path_sha256": runner.sha256_bytes(
                str(provider_home).encode("utf-8")
            ),
        }
    ]

    if expect_success:
        assert gate["prompt_sent_after_tools_list_flush"] is True
        assert observed == {"type": "returned", "message": None}, observed
        assert process_result is not None
        assert process_result["returncode"] == 0
        assert process_result["timed_out"] is False
        assert gate["status"] == "complete"
        assert gate["identity"]["auth_files_present_at_identity"] is True
        assert len(gate["tool_actions"]) == 1
        assert len(gate["tool_results"]) == 1
        assert len(gate["proxy_runtime_proofs"]) == 1
        assert proof_calls == gate["proxy_runtime_proofs"]
        trace_records = [
            json.loads(line)
            for line in boundary["proxy_trace"].read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip()
        ]
        trace_records = [
            value for value in trace_records if "tool" in value
        ]
        assert len(trace_records) == 1
        action = gate["tool_actions"][0]
        result = gate["tool_results"][0]
        trace = trace_records[0]
        assert action["tool_use_id"] == result["tool_use_id"]
        assert trace["tool"] == action["tool"].rsplit("__", 1)[-1]
        assert trace["arguments_sha256"] == action["arguments_sha256"]
        assert trace["result_text_sha256"] == result["result_text_sha256"]
        prompt_probe = json.loads(
            prepared["prompt_probe"].read_text(encoding="utf-8")
        )
        assert prompt_probe == {
            "withheld_before_ready": True,
            "delivered_after_ready": True,
            "auth_present_before_exit": True,
        }
        assert b"AUTH_PRESENT_BEFORE_TRANSPORT_EXIT" in stdout_bytes
        correlation_proved = True
    else:
        assert observed["type"] == "CampaignError", observed
        assert "tool roster differs from the exact MCP boundary" in str(
            observed["message"]
        )
        assert process_result is None
        assert gate["status"] == "failed-closed"
        assert gate["identity"] is None
        assert gate["tool_actions"] == []
        assert gate["tool_results"] == []
        assert proof_calls == []
        prompt_probe = json.loads(
            prepared["prompt_probe"].read_text(encoding="utf-8")
        )
        assert prompt_probe["withheld_before_ready"] is True
        correlation_proved = False

    return {
        "name": name,
        "expected": "success" if expect_success else "failed_closed",
        "observed": observed,
        "gate_status": gate["status"],
        "provider_home_absent": not provider_home.exists(),
        "fake_auth_absent": not auth_path.exists(),
        "prompt_sent_after_tools_list_flush": gate[
            "prompt_sent_after_tools_list_flush"
        ],
        "allowed_tools": gate["allowed_tools"],
        "built_in_tools_allowed": gate["built_in_tools_allowed"],
        "local_proxy_proof_calls": len(proof_calls),
        "exact_tool_result_correlation_proved": correlation_proved,
        "gate_path": str(prepared["gate_path"]),
        "stdout_path": str(prepared["stdout_path"]),
        "stderr_path": str(prepared["stderr_path"]),
    }


def claude_retained_boundary_cases(diagnostics_root: Path) -> dict[str, Any]:
    cases = [
        _run_local_claude_case(
            diagnostics_root,
            name="retained-through-transport-success",
            reported_tools=list(runner.CLAUDE_GRADER_TOOLS),
            expect_success=True,
        ),
        _run_local_claude_case(
            diagnostics_root,
            name="undeclared-built-in-roster-fails-closed",
            reported_tools=["Bash"],
            expect_success=False,
        ),
    ]
    synthetic_home = diagnostics_root / "private-provider-home"
    assistant_disclosure = runner._claude_event_path_disclosures(
        {
            "type": "assistant",
            "message": {"content": f"read {synthetic_home}"},
        },
        provider_home=synthetic_home,
        event_number=3,
    )
    init_source_disclosure = runner._claude_event_path_disclosures(
        {
            "type": "system",
            "subtype": "init",
            "cwd": str(runner.HOST_SOURCE_ROOT),
        },
        provider_home=synthetic_home,
        event_number=1,
    )
    assert assistant_disclosure["allowed"] == []
    assert len(assistant_disclosure["forbidden"]) == 1
    assert (
        assistant_disclosure["forbidden"][0]["path_kind"]
        == "provider_private_home"
    )
    assert init_source_disclosure["allowed"] == []
    assert len(init_source_disclosure["forbidden"]) == 1
    assert (
        init_source_disclosure["forbidden"][0]["path_kind"]
        == "host_source_root"
    )
    return {
        "cases": cases,
        "assistant_private_path_rejected": True,
        "system_init_source_path_rejected": True,
        "all_passed": len(cases) == 2,
    }


def _run_bridge_protocol_case(
    diagnostics_root: Path,
    *,
    protocol_version: str,
    expect_accepted: bool,
) -> dict[str, Any]:
    """Exercise one exact MCP initialize sequence without a provider."""

    case_root = (
        diagnostics_root
        / "mcp-protocol-cases"
        / protocol_version.replace("/", "-")
    )
    case_root.mkdir(parents=True)
    evidence_root = case_root / "evidence"
    evidence_root.mkdir()
    trace_path = case_root / "proxy-trace.jsonl"
    ready_path = case_root / "proxy-ready.json"
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": protocol_version,
                "capabilities": {},
                "clientInfo": {
                    "name": "maude-provider-free-selftest",
                    "version": "1",
                },
            },
        }
    ]
    if expect_accepted:
        messages.extend(
            [
                {
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                },
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/list",
                    "params": {},
                },
            ]
        )
    completed = subprocess.run(
        [
            "/usr/bin/python3",
            "-I",
            "-B",
            str(runner.CLAUDE_MCP_BRIDGE_SOURCE),
            "mcp",
            "--mode",
            "grader",
            "--trace",
            str(trace_path),
            "--ready",
            str(ready_path),
            "--root",
            str(evidence_root),
        ],
        cwd=case_root,
        env={
            "HOME": str(case_root),
            "PATH": "/usr/bin:/bin",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
        },
        input=b"".join(
            runner._canonical_json_bytes(message) + b"\n"
            for message in messages
        ),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr.decode(
        errors="replace"
    )
    assert completed.stderr == b""
    responses = [
        json.loads(line)
        for line in completed.stdout.splitlines()
        if line.strip()
    ]
    trace = [
        json.loads(line)
        for line in trace_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(trace) >= 1
    initialize_trace = trace[0]
    assert initialize_trace["protocol_event"] == (
        "initialize-response-flushed"
    )
    assert initialize_trace["protocol_version_requested"] == protocol_version
    assert initialize_trace["initialize_accepted"] is expect_accepted
    if expect_accepted:
        assert len(responses) == 2
        initialize_result = responses[0]["result"]
        assert initialize_result["protocolVersion"] == protocol_version
        assert initialize_result["capabilities"] == {
            "tools": {"listChanged": False}
        }
        assert initialize_result["serverInfo"] == {
            "name": "maude-synthetic-operator-cleanroom",
            "title": "Maude Synthetic Operator Cleanroom",
            "version": "2",
        }
        assert responses[1]["result"]["tools"][0]["name"] == "evidence"
        assert initialize_trace["protocol_version_negotiated"] == (
            protocol_version
        )
        assert [value.get("protocol_event") for value in trace] == [
            "initialize-response-flushed",
            "notifications/initialized",
            "tools-list-response-flushed",
        ]
        ready = json.loads(ready_path.read_text(encoding="utf-8"))
        assert ready["protocol_version_requested"] == protocol_version
        assert ready["protocol_version_negotiated"] == protocol_version
        assert ready["tools"] == ["evidence"]
    else:
        assert len(responses) == 1
        assert responses[0]["error"]["code"] == -32602
        assert "unsupported MCP protocol version" in (
            responses[0]["error"]["message"]
        )
        assert initialize_trace["protocol_version_negotiated"] is None
        assert not ready_path.exists()
    return {
        "protocol_version": protocol_version,
        "accepted": expect_accepted,
        "response_count": len(responses),
        "trace_events": [
            value.get("protocol_event") for value in trace
        ],
        "ready": ready_path.is_file(),
    }


def mcp_protocol_negotiation_cases(
    diagnostics_root: Path,
) -> dict[str, Any]:
    supported = list(runner.SUPPORTED_MCP_PROTOCOL_VERSIONS)
    assert supported == ["2025-06-18", "2025-11-25"]
    cases = [
        _run_bridge_protocol_case(
            diagnostics_root,
            protocol_version=protocol_version,
            expect_accepted=True,
        )
        for protocol_version in supported
    ]
    cases.append(
        _run_bridge_protocol_case(
            diagnostics_root,
            protocol_version="2024-11-05",
            expect_accepted=False,
        )
    )
    return {
        "supported_versions": supported,
        "cases": cases,
        "all_passed": len(cases) == 3,
    }


def codex_auth_absence_audit_cases() -> dict[str, Any]:
    command = runner.CODEX_AUTH_GATE_ABSENCE_CHECK_COMMAND

    def observation(
        event_number: int,
        event_type: str,
        *,
        include_timeout: bool,
    ) -> dict[str, Any]:
        arguments: dict[str, Any] = {"command": command}
        if include_timeout:
            arguments["timeout_seconds"] = (
                runner.CODEX_AUTH_GATE_ABSENCE_TIMEOUT_SECONDS
            )
        return {
            "event_number": event_number,
            "event_type": event_type,
            "item_sha256": str(event_number) * 64,
            "item": {
                "id": "auth-absence-1",
                "type": "mcp_tool_call",
                "server": "operator",
                "tool": "terminal",
                "arguments": arguments,
            },
        }

    def allowed_value(*, include_timeout: bool) -> dict[str, Any]:
        return {
            "observations": [
                observation(
                    1,
                    "item.started",
                    include_timeout=include_timeout,
                ),
                observation(
                    2,
                    "item.completed",
                    include_timeout=include_timeout,
                ),
            ]
        }

    with_timeout = allowed_value(include_timeout=True)
    without_timeout = allowed_value(include_timeout=False)
    for value in (with_timeout, without_timeout):
        serialized = json.dumps(value, sort_keys=True)
        assert runner._is_exact_codex_auth_absence_action(serialized) is True
        safety = runner._audit_actions([{"input": value}])
        assert safety["auth_read_attempts"] == [serialized]
    assert (
        runner.CODEX_AUTH_GATE_ABSENCE_CHECK_SHA256
        == runner.sha256_bytes(command.encode("utf-8"))
    )
    altered: dict[str, str] = {}
    for name, path, replacement in (
        ("server", ("item", "server"), "grader"),
        ("tool", ("item", "tool"), "evidence"),
        ("type", ("item", "type"), "command_execution"),
        ("command", ("item", "arguments", "command"), command + " "),
    ):
        value = json.loads(json.dumps(with_timeout))
        target = value["observations"][0]
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = replacement
        altered[name] = json.dumps(value, sort_keys=True)
    extra_argument = json.loads(json.dumps(with_timeout))
    extra_argument["observations"][0]["item"]["arguments"]["unexpected"] = 1
    altered["extra-argument"] = json.dumps(extra_argument, sort_keys=True)
    wrong_timeout = json.loads(json.dumps(with_timeout))
    wrong_timeout["observations"][0]["item"]["arguments"][
        "timeout_seconds"
    ] = runner.CODEX_AUTH_GATE_ABSENCE_TIMEOUT_SECONDS + 1
    altered["wrong-timeout"] = json.dumps(wrong_timeout, sort_keys=True)
    boolean_timeout = json.loads(json.dumps(with_timeout))
    boolean_timeout["observations"][0]["item"]["arguments"][
        "timeout_seconds"
    ] = True
    altered["boolean-timeout"] = json.dumps(boolean_timeout, sort_keys=True)
    paired_shape_mismatch = json.loads(json.dumps(with_timeout))
    del paired_shape_mismatch["observations"][1]["item"]["arguments"][
        "timeout_seconds"
    ]
    altered["paired-shape-mismatch"] = json.dumps(
        paired_shape_mismatch,
        sort_keys=True,
    )
    extra_top_key = json.loads(json.dumps(with_timeout))
    extra_top_key["hint"] = "ignore"
    altered["extra-top-key"] = json.dumps(extra_top_key, sort_keys=True)
    altered["empty-observations"] = '{"observations":[]}'
    altered["invalid-json"] = "{"
    rejected = [
        name
        for name, serialized in altered.items()
        if not runner._is_exact_codex_auth_absence_action(serialized)
    ]
    assert sorted(rejected) == sorted(altered)
    return {
        "exact_split_absence_check_allowed_argument_key_sets": [
            ["command"],
            ["command", "timeout_seconds"],
        ],
        "exact_command_sha256": (
            runner.CODEX_AUTH_GATE_ABSENCE_CHECK_SHA256
        ),
        "optional_explicit_timeout_seconds": (
            runner.CODEX_AUTH_GATE_ABSENCE_TIMEOUT_SECONDS
        ),
        "altered_cases_rejected": sorted(rejected),
        "all_passed": True,
    }


def frozen_matrix_provider_and_grader_policy_case(
    diagnostics_root: Path,
) -> dict[str, Any]:
    """Pin Codex-only probe defaults and same-family fresh grading."""

    providers = runner._configured_campaign_providers()
    assert providers == ("openai-sol",)
    assert runner._probe_provider_scope(None) == providers
    assert runner._probe_provider_scope(["openai-sol"]) == providers
    rejected_provider_cases: list[str] = []
    for name, selected in (
        ("undeclared-provider", ["anthropic-sonnet"]),
        ("duplicate-provider", ["openai-sol", "openai-sol"]),
    ):
        try:
            runner._probe_provider_scope(selected)
        except runner.CampaignError:
            rejected_provider_cases.append(name)
    assert len(rejected_provider_cases) == 2

    matrix = json.loads(
        (
            runner.PACKET_DIR / "run-matrix.json"
        ).read_text(encoding="utf-8")
    )
    run = dict(matrix["runs"][0])
    metadata = runner._grading_model_family_metadata(run)
    policy = matrix["model_family_policy"]
    assert metadata == {
        "separate_fresh_session_required": True,
        "same_family_grading": True,
        "same_model_configuration_grading": True,
        "cross_family_grading_supported": False,
        "same_family_limitation": policy["limitation"],
    }
    assert "opposite_model_family" not in metadata

    mismatched_run = dict(run)
    mismatched_run["grader_model_config"] = "anthropic-sonnet"
    mismatch_rejected = False
    try:
        runner._grading_model_family_metadata(mismatched_run)
    except runner.CampaignError:
        mismatch_rejected = True
    assert mismatch_rejected

    expected_tools = list(runner.CLAUDE_GRADER_TOOLS)
    assert expected_tools == ["mcp__grader__evidence"]
    errors: list[str] = []
    runner._verify_session_boundary(
        label="synthetic grader",
        config_id="openai-sol",
        raw=diagnostics_root / "missing-boundary",
        transcript=diagnostics_root / "missing-transcript",
        metadata={"tools": ["read-only Codex shell surface"]},
        expected_tools=expected_tools,
        expected_mode="grader",
        errors=errors,
    )
    assert "synthetic grader: declared tool roster differs" in errors
    exact_errors: list[str] = []
    runner._verify_session_boundary(
        label="synthetic grader",
        config_id="openai-sol",
        raw=diagnostics_root / "missing-boundary",
        transcript=diagnostics_root / "missing-transcript",
        metadata={"tools": expected_tools},
        expected_tools=expected_tools,
        expected_mode="grader",
        errors=exact_errors,
    )
    assert "synthetic grader: declared tool roster differs" not in exact_errors
    return {
        "configured_probe_providers": list(providers),
        "undeclared_or_duplicate_provider_cases_rejected": (
            rejected_provider_cases
        ),
        "grader_model_family_metadata": metadata,
        "same_family_mismatch_rejected": mismatch_rejected,
        "exact_grader_tools": expected_tools,
        "stale_shell_label_rejected": True,
        "all_passed": True,
    }


def codex_offline_prompt_input_case(
    diagnostics_root: Path,
) -> dict[str, Any]:
    """Prove installed Codex reaches tools/list without model inference."""

    codex = shutil.which("codex")
    assert codex is not None, "installed Codex CLI is unavailable"
    case_root = diagnostics_root / "codex-offline-prompt-input"
    codex_home = case_root / "codex-home"
    evidence_root = case_root / "evidence"
    work = case_root / "work"
    for path in (codex_home, evidence_root, work):
        path.mkdir(parents=True)
    trace_path = case_root / "proxy-trace.jsonl"
    ready_path = case_root / "proxy-ready.json"
    bridge_args = [
        "-B",
        str(runner.CLAUDE_MCP_BRIDGE_SOURCE),
        "mcp",
        "--mode",
        "grader",
        "--trace",
        str(trace_path),
        "--ready",
        str(ready_path),
        "--root",
        str(evidence_root),
    ]
    environment = {
        "HOME": str(codex_home),
        "CODEX_HOME": str(codex_home),
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
    }
    completed = subprocess.run(
        [
            codex,
            "--config",
            'mcp_servers.operator.command="/usr/bin/python3"',
            "--config",
            (
                "mcp_servers.operator.args="
                + json.dumps(bridge_args, separators=(",", ":"))
            ),
            "--config",
            'mcp_servers.operator.enabled_tools=["evidence"]',
            "-C",
            str(work),
            "debug",
            "prompt-input",
            "provider-free MCP compatibility probe",
        ],
        cwd=case_root,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr.decode(
        errors="replace"
    )
    prompt_input = json.loads(completed.stdout)
    assert isinstance(prompt_input, list)
    trace = [
        json.loads(line)
        for line in trace_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [value.get("protocol_event") for value in trace] == [
        "initialize-response-flushed",
        "notifications/initialized",
        "tools-list-response-flushed",
    ]
    assert trace[0]["initialize_accepted"] is True
    assert trace[0]["protocol_version_requested"] == (
        runner.CODEX_MCP_PROTOCOL_VERSION
    )
    assert trace[0]["protocol_version_negotiated"] == (
        runner.CODEX_MCP_PROTOCOL_VERSION
    )
    assert trace[2]["protocol_version"] == runner.CODEX_MCP_PROTOCOL_VERSION
    assert trace[2]["tools"] == ["evidence"]
    ready: dict[str, Any] | None = None
    if ready_path.is_file():
        ready = json.loads(ready_path.read_text(encoding="utf-8"))
        assert ready["protocol_version_requested"] == (
            runner.CODEX_MCP_PROTOCOL_VERSION
        )
        assert ready["protocol_version_negotiated"] == (
            runner.CODEX_MCP_PROTOCOL_VERSION
        )
        assert ready["tools"] == ["evidence"]
    return {
        "codex_binary": codex,
        "protocol_version": runner.CODEX_MCP_PROTOCOL_VERSION,
        "tools": trace[2]["tools"],
        "trace_events": [
            value["protocol_event"] for value in trace
        ],
        # `codex debug prompt-input` may terminate its MCP child immediately
        # after receiving tools/list.  The flushed trace proves client
        # compatibility; the direct handshake cases separately require and
        # validate the atomic readiness file.
        "readiness_file_published_before_client_shutdown": ready is not None,
        "prompt_input_sha256": runner.sha256_bytes(completed.stdout),
        "provider_invoked": False,
        "network_invoked": False,
        "all_passed": True,
    }


def _run_local_codex_mcp_case(
    diagnostics_root: Path,
    *,
    name: str,
    forbidden_intrinsic_action: bool,
) -> dict[str, Any]:
    """Exercise the retained Codex gate with a local JSONL fixture only."""

    case_root = diagnostics_root / "codex-mcp-cases" / name
    case_root.mkdir(parents=True)
    provider_home = case_root / "provider-home"
    auth_path = provider_home / ".codex" / "auth.json"
    auth_path.parent.mkdir(parents=True)
    secret = f"fake-codex-mcp-secret-{name}-123456789".encode()
    auth_path.write_bytes(secret)
    operator_home = case_root / "operator-home"
    runner._prepare_clean_operator_home(operator_home)
    bundle = case_root / "bundle"
    bundle.mkdir()
    (bundle / "evidence.txt").write_text("synthetic\n", encoding="utf-8")
    boundary = runner._adapt_boundary_for_codex(
        runner._build_claude_boundary(
            label=f"local-codex-{name}",
            lab=case_root,
            mode="grader",
            provider_home=provider_home,
            cwd=Path("/evidence"),
            operator_home=operator_home,
            grader_bundle=bundle,
        )
    )
    bwrap = runner._codex_mcp_transport_bwrap(
        boundary, provider_home, operator_home
    )
    assert bwrap[0] == str(runner.BWRAP)
    assert str(runner.HOST_SOURCE_ROOT) not in bwrap
    assert "--chdir" in bwrap
    large_user_prompt = "synthetic task\n" + ("x" * 200_000)
    codex_argv, delivery, stdin_payload = runner._provider_argv(
        "openai-sol",
        system_prompt="synthetic system",
        user_prompt=large_user_prompt,
        cwd=bundle,
        grade_schema=bundle / "schema.json",
        claude_boundary=boundary,
    )
    disabled = [
        codex_argv[index + 1]
        for index, value in enumerate(codex_argv[:-1])
        if value == "--disable"
    ]
    assert set(runner.CODEX_DISABLED_INTRINSIC_ACTION_FEATURES).issubset(
        disabled
    )
    approval_indexes = [
        index
        for index, value in enumerate(codex_argv[:-1])
        if value == "--config"
        and codex_argv[index + 1] == 'approval_policy="never"'
    ]
    assert len(approval_indexes) == 1
    approval_index = approval_indexes[0]
    assert codex_argv[approval_index : approval_index + 2] == [
        "--config",
        'approval_policy="never"',
    ]
    mcp_approval_override = (
        f"mcp_servers.{boundary['server']}."
        'default_tools_approval_mode="approve"'
    )
    mcp_approval_indexes = [
        index
        for index, value in enumerate(codex_argv[:-1])
        if value == "--config"
        and codex_argv[index + 1] == mcp_approval_override
    ]
    assert len(mcp_approval_indexes) == 1
    mcp_approval_index = mcp_approval_indexes[0]
    assert "use_legacy_landlock" not in codex_argv
    assert str(bundle) not in codex_argv
    assert codex_argv[-1] == "-"
    assert stdin_payload is not None
    assert len(stdin_payload) > 131_072
    assert all(large_user_prompt not in value for value in codex_argv)
    assert delivery["semantic_prompt_bytes_in_argv"] is False
    assert delivery["delivered_prompt_bytes"] == len(stdin_payload)
    assert delivery["delivered_prompt_sha256"] == runner.sha256_bytes(
        stdin_payload
    )
    assert delivery["mcp_enabled_tools"] == ["evidence"]
    assert delivery["mcp_protocol_version"] == (
        runner.CODEX_MCP_PROTOCOL_VERSION
    )
    assert delivery["exact_provider_tool_allowlist_supported"] is True
    assert delivery["codex_approval_argv"] == [
        "--config",
        'approval_policy="never"',
    ]
    assert (
        delivery["codex_approval_config_override"]
        == 'approval_policy="never"'
    )
    assert delivery["codex_approval_policy"] == "never"
    assert delivery["codex_mcp_default_tools_approval_mode"] == "approve"
    assert (
        delivery["codex_mcp_approval_config_override"]
        == mcp_approval_override
    )
    assert boundary["mcp_protocol_version"] == (
        runner.CODEX_MCP_PROTOCOL_VERSION
    )
    assert boundary["codex_approval_argv"] == [
        "--config",
        'approval_policy="never"',
    ]
    assert (
        boundary["codex_approval_config_override"]
        == 'approval_policy="never"'
    )
    assert boundary["codex_approval_policy"] == "never"
    assert boundary["codex_mcp_default_tools_approval_mode"] == "approve"
    assert (
        boundary["codex_mcp_approval_config_override"]
        == mcp_approval_override
    )
    expected_approval_safety_basis = {
        "intrinsic_action_features_disabled": list(
            runner.CODEX_DISABLED_INTRINSIC_ACTION_FEATURES
        ),
        "single_enabled_mcp_tool": "evidence",
        "operator_terminal_bounded_by_frozen_broker": False,
        "grader_evidence_tool_read_only": True,
        "rationale": (
            "Non-interactive approval is safe here only because Codex "
            "intrinsic action features are disabled and operator sessions "
            "expose exactly one MCP terminal bounded by the frozen broker; "
            "grader sessions expose exactly one read-only evidence tool."
        ),
    }
    assert (
        delivery["noninteractive_approval_safety_basis"]
        == expected_approval_safety_basis
    )
    assert (
        boundary["noninteractive_approval_safety_basis"]
        == expected_approval_safety_basis
    )
    expected_mcp_tool_approval_safety_basis = {
        "mcp_config_hash_pinned": True,
        "exact_enabled_tool_count": 1,
        "single_enabled_mcp_tool": "evidence",
        "operator_terminal_bounded_by_frozen_broker": False,
        "grader_evidence_tool_read_only": True,
        "rationale": (
            "MCP tool auto-approval is safe here only because the "
            "hash-pinned server exposes exactly one tool: the operator "
            "terminal is bounded by the frozen broker, while the grader "
            "evidence tool is read-only."
        ),
    }
    assert (
        delivery["mcp_tool_approval_safety_basis"]
        == expected_mcp_tool_approval_safety_basis
    )
    assert (
        boundary["mcp_tool_approval_safety_basis"]
        == expected_mcp_tool_approval_safety_basis
    )
    boundary_record = runner._claude_boundary_record(boundary)
    assert boundary_record["codex_approval_argv"] == [
        "--config",
        'approval_policy="never"',
    ]
    assert (
        boundary_record["codex_approval_config_override"]
        == 'approval_policy="never"'
    )
    assert boundary_record["codex_approval_policy"] == "never"
    assert (
        boundary_record["codex_mcp_default_tools_approval_mode"]
        == "approve"
    )
    assert (
        boundary_record["codex_mcp_approval_config_override"]
        == mcp_approval_override
    )
    assert (
        boundary_record["noninteractive_approval_safety_basis"]
        == expected_approval_safety_basis
    )
    assert (
        boundary_record["mcp_tool_approval_safety_basis"]
        == expected_mcp_tool_approval_safety_basis
    )
    invoked_mcp_config = {
        "mcp_servers": {
            boundary["server"]: {
                "command": boundary["codex_mcp_command"],
                "args": boundary["codex_mcp_args"],
                "enabled_tools": boundary["codex_enabled_tools"],
                "default_tools_approval_mode": "approve",
            }
        }
    }
    assert boundary["mcp_config"] == invoked_mcp_config
    assert boundary["mcp_config_sha256"] == runner.sha256_bytes(
        runner._canonical_json_bytes(invoked_mcp_config)
    )
    assert delivery["mcp_config_sha256"] == boundary["mcp_config_sha256"]
    runner._validate_codex_strict_argv([*bwrap, *codex_argv], boundary)
    approval_tamper_cases: dict[str, list[str]] = {}
    without_approval = list(codex_argv)
    del without_approval[approval_index : approval_index + 2]
    approval_tamper_cases["missing"] = without_approval
    wrong_approval = list(codex_argv)
    wrong_approval[approval_index + 1] = 'approval_policy="on-request"'
    approval_tamper_cases["wrong"] = wrong_approval
    duplicate_approval = list(codex_argv)
    duplicate_approval[approval_index:approval_index] = [
        "--config",
        'approval_policy="never"',
    ]
    approval_tamper_cases["duplicate"] = duplicate_approval
    for tamper_name, tampered_argv in approval_tamper_cases.items():
        try:
            runner._validate_codex_strict_argv(
                [*bwrap, *tampered_argv], boundary
            )
        except runner.CampaignError:
            pass
        else:
            raise AssertionError(
                f"Codex approval tamper did not fail closed: {tamper_name}"
            )
    mcp_approval_tamper_cases: dict[str, list[str]] = {}
    without_mcp_approval = list(codex_argv)
    del without_mcp_approval[
        mcp_approval_index : mcp_approval_index + 2
    ]
    mcp_approval_tamper_cases["missing"] = without_mcp_approval
    wrong_mcp_approval = list(codex_argv)
    wrong_mcp_approval[mcp_approval_index + 1] = (
        f"mcp_servers.{boundary['server']}."
        'default_tools_approval_mode="prompt"'
    )
    mcp_approval_tamper_cases["wrong"] = wrong_mcp_approval
    duplicate_mcp_approval = list(codex_argv)
    duplicate_mcp_approval[
        mcp_approval_index:mcp_approval_index
    ] = ["--config", mcp_approval_override]
    mcp_approval_tamper_cases["duplicate"] = duplicate_mcp_approval
    for tamper_name, tampered_argv in mcp_approval_tamper_cases.items():
        try:
            runner._validate_codex_strict_argv(
                [*bwrap, *tampered_argv], boundary
            )
        except runner.CampaignError:
            pass
        else:
            raise AssertionError(
                "Codex MCP approval-mode tamper did not fail closed: "
                f"{tamper_name}"
            )
    arguments = {"operation": "read", "path": "evidence.txt"}
    result_text = json.dumps(
        {"content": "synthetic", "status": "ok"},
        separators=(",", ":"),
        sort_keys=True,
    )
    bridge_mcp_result = {
        "content": [{"type": "text", "text": result_text}],
        "isError": False,
    }
    normalized_provider_result = {
        "content": [{"type": "text", "text": result_text}],
        "structured_content": None,
    }
    ready = {
        "protocol_version_requested": runner.CODEX_MCP_PROTOCOL_VERSION,
        "protocol_version_negotiated": runner.CODEX_MCP_PROTOCOL_VERSION,
        "tools": ["evidence"],
        "initialize_message_ordinal": 1,
        "tools_list_message_ordinal": 3,
        "tools_list_response_sha256": "3" * 64,
    }
    protocol_trace = [
        {
            "message_ordinal": 1,
            "protocol_event": "initialize-response-flushed",
            "protocol_version_requested": runner.CODEX_MCP_PROTOCOL_VERSION,
            "protocol_version_negotiated": runner.CODEX_MCP_PROTOCOL_VERSION,
            "initialize_accepted": True,
        },
        {
            "message_ordinal": 2,
            "protocol_event": "notifications/initialized",
            "protocol_version": runner.CODEX_MCP_PROTOCOL_VERSION,
        },
        {
            "message_ordinal": 3,
            "protocol_event": "tools-list-response-flushed",
            "protocol_version": runner.CODEX_MCP_PROTOCOL_VERSION,
            "response_sha256": ready["tools_list_response_sha256"],
        },
    ]
    proxy_call = {
        "tool": "evidence",
        "arguments": arguments,
        "arguments_sha256": runner.sha256_bytes(
            runner._canonical_json_bytes(arguments)
        ),
        "result_text": result_text,
        "result_text_sha256": runner.sha256_bytes(result_text.encode()),
        "mcp_result_sha256": runner.sha256_bytes(
            runner._canonical_json_bytes(bridge_mcp_result)
        ),
        "is_error": False,
    }
    thread = event(
        {"type": "thread.started", "thread_id": f"local-{name}"}
    )
    if forbidden_intrinsic_action:
        provider_events = [
            thread,
            event(
                {
                    "type": "item.started",
                    "item": {
                        "id": "bad-1",
                        "type": "command_execution",
                        "command": "/usr/bin/true",
                    },
                }
            ),
        ]
        trace_setup = ""
    else:
        provider_events = [
            thread,
            event(
                {
                    "type": "item.started",
                    "item": {
                        "id": "mcp-1",
                        "type": "mcp_tool_call",
                        "server": "grader",
                        "tool": "evidence",
                        "arguments": arguments,
                    },
                }
            ),
            event(
                {
                    "type": "item.completed",
                    "item": {
                        "id": "mcp-1",
                        "type": "mcp_tool_call",
                        "server": "grader",
                        "tool": "evidence",
                        "arguments": arguments,
                        "result": normalized_provider_result,
                    },
                }
            ),
            event(
                {
                    "type": "item.completed",
                    "item": {
                        "id": "message-1",
                        "type": "agent_message",
                        "text": "done",
                    },
                }
            ),
        ]
        ready_path = boundary["proxy_ready"]
        trace_path = boundary["proxy_trace"]
        trace_setup = (
            f"pathlib.Path({str(ready_path)!r}).write_text("
            f"json.dumps({ready!r})+'\\n',encoding='utf-8');"
            f"pathlib.Path({str(trace_path)!r}).write_text("
            f"''.join(json.dumps(value)+'\\n' for value in "
            f"{[*protocol_trace, proxy_call]!r}),encoding='utf-8');"
        )
    stdin_probe = case_root / "stdin-probe.json"
    source = (
        "import hashlib,json,pathlib,sys;"
        "prompt=sys.stdin.buffer.read();"
        f"pathlib.Path({str(stdin_probe)!r}).write_text("
        "json.dumps({'bytes':len(prompt),"
        "'sha256':hashlib.sha256(prompt).hexdigest()})+'\\n',"
        "encoding='utf-8');"
        + trace_setup
        + "".join(f"print({line!r},flush=True);" for line in provider_events)
    )
    stdout_path = case_root / "stdout.jsonl"
    stderr_path = case_root / "stderr"
    gate_path = case_root / "gate.json"
    observed: dict[str, Any]
    original_bwrap = runner.BWRAP
    original_argv_validator = runner._validate_codex_strict_argv
    runner.BWRAP = Path("/usr/bin/python3")
    runner._validate_codex_strict_argv = lambda _argv, _boundary: None
    try:
        try:
            runner._run_codex_retained_process(
                ["/usr/bin/python3", "-c", source],
                cwd=boundary["transport_cwd"],
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                timeout=15,
                provider_home=provider_home,
                copied_auth=[".codex/auth.json"],
                credential_values=[secret],
                gate_record_path=gate_path,
                boundary=boundary,
                stdin_payload=stdin_payload,
            )
        except BaseException as exc:
            observed = {"type": type(exc).__name__, "message": str(exc)}
        else:
            observed = {"type": "returned", "message": None}
    finally:
        runner.BWRAP = original_bwrap
        runner._validate_codex_strict_argv = original_argv_validator
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    assert not provider_home.exists()
    assert secret not in stdout_path.read_bytes()
    assert secret not in stderr_path.read_bytes()
    assert gate["provider_auth_destroyed"] is True
    stdin_observation = json.loads(stdin_probe.read_text(encoding="utf-8"))
    assert stdin_observation == {
        "bytes": len(stdin_payload),
        "sha256": runner.sha256_bytes(stdin_payload),
    }
    assert gate["codex_approval_argv"] == [
        "--config",
        'approval_policy="never"',
    ]
    assert (
        gate["codex_approval_config_override"]
        == 'approval_policy="never"'
    )
    assert gate["codex_approval_policy"] == "never"
    assert gate["codex_mcp_default_tools_approval_mode"] == "approve"
    assert gate["codex_mcp_approval_config_override"] == mcp_approval_override
    assert (
        gate["noninteractive_approval_safety_basis"]
        == expected_approval_safety_basis
    )
    assert (
        gate["mcp_tool_approval_safety_basis"]
        == expected_mcp_tool_approval_safety_basis
    )
    if forbidden_intrinsic_action:
        assert observed["type"] == "CampaignError", observed
        assert "forbidden intrinsic/non-MCP action" in str(observed["message"])
        assert gate["status"] == "failed-closed"
    else:
        assert observed == {"type": "returned", "message": None}, observed
        assert gate["status"] == "complete"
        assert gate["exact_correlation_proved"] is True
        assert gate["proxy_tool_call_count"] == 1
        assert len(gate["tool_actions"]) == 1
        assert gate["normalized_result_correlations"] == [
            {
                "action_id": "mcp-1",
                "tool": "evidence",
                "arguments_sha256": proxy_call["arguments_sha256"],
                "provider_normalized_result_text_sha256": proxy_call[
                    "result_text_sha256"
                ],
                "proxy_result_text_sha256": proxy_call[
                    "result_text_sha256"
                ],
                "proxy_is_error": False,
            }
        ]
    return {
        "name": name,
        "observed": observed,
        "gate_status": gate["status"],
        "provider_home_destroyed": not provider_home.exists(),
        "strict_roster": gate["allowed_mcp_tools"],
        "approval_policy": gate["codex_approval_policy"],
        "approval_tamper_cases_rejected": sorted(approval_tamper_cases),
        "mcp_default_tools_approval_mode": gate[
            "codex_mcp_default_tools_approval_mode"
        ],
        "mcp_approval_tamper_cases_rejected": sorted(
            mcp_approval_tamper_cases
        ),
        "all_passed": True,
    }


def codex_normalized_mcp_result_shape_cases() -> dict[str, Any]:
    result_text = '{"status":"ok"}'
    valid = {
        "content": [{"type": "text", "text": result_text}],
        "structured_content": None,
    }
    assert runner._codex_normalized_mcp_result_text(valid) == result_text
    invalid = {
        "bridge-envelope-extra-key": {
            "content": [{"type": "text", "text": result_text}],
            "structured_content": None,
            "isError": False,
        },
        "structured-content-not-null": {
            "content": [{"type": "text", "text": result_text}],
            "structured_content": {},
        },
        "multiple-content-blocks": {
            "content": [
                {"type": "text", "text": result_text},
                {"type": "text", "text": result_text},
            ],
            "structured_content": None,
        },
        "content-block-extra-key": {
            "content": [
                {"type": "text", "text": result_text, "extra": False}
            ],
            "structured_content": None,
        },
        "content-block-wrong-type": {
            "content": [{"type": "image", "text": result_text}],
            "structured_content": None,
        },
        "content-block-non-text-value": {
            "content": [{"type": "text", "text": 1}],
            "structured_content": None,
        },
    }
    rejected: list[str] = []
    for name, value in invalid.items():
        try:
            runner._codex_normalized_mcp_result_text(value)
        except runner.CampaignError:
            rejected.append(name)
        else:
            raise AssertionError(
                f"Codex normalized MCP result accepted invalid shape: {name}"
            )
    return {
        "valid_shape_accepted": True,
        "invalid_shapes_rejected": sorted(rejected),
        "all_passed": len(rejected) == len(invalid),
    }


def codex_strict_mcp_boundary_cases(
    diagnostics_root: Path,
) -> dict[str, Any]:
    cases = [
        _run_local_codex_mcp_case(
            diagnostics_root,
            name="exact-mcp-action",
            forbidden_intrinsic_action=False,
        ),
        _run_local_codex_mcp_case(
            diagnostics_root,
            name="intrinsic-action-fails-closed",
            forbidden_intrinsic_action=True,
        ),
    ]
    normalization = codex_normalized_mcp_result_shape_cases()
    return {
        "cases": cases,
        "normalization": normalization,
        "all_passed": len(cases) == 2 and normalization["all_passed"],
    }


def public_cli_broker_case(diagnostics_root: Path) -> dict[str, Any]:
    """Exercise the socket facade without exposing its fake private queue."""

    case_root = diagnostics_root / "public-cli-broker"
    control = case_root / "private-control"
    requests = control / "requests"
    responses = control / "responses"
    requests.mkdir(parents=True)
    responses.mkdir()
    (control / "driver-ready.json").write_text("{}\n", encoding="utf-8")
    socket_path = case_root / "public" / "broker.sock"
    trace_path = case_root / "evidence" / "broker.jsonl"
    ready_path = case_root / "evidence" / "broker-ready.json"
    cleanup_path = case_root / "evidence" / "broker-cleanup.json"
    home = case_root / "broker-home"
    home.mkdir()
    stopped = threading.Event()
    seen: set[str] = set()

    def fake_driver() -> None:
        while not stopped.is_set():
            for request_path in sorted(requests.glob("*.json")):
                if request_path.name in seen:
                    continue
                seen.add(request_path.name)
                request = json.loads(request_path.read_text(encoding="utf-8"))
                if request.get("action") != "screen":
                    continue
                response = {
                    "schema": "maude.synthetic-operator.response.v1",
                    "request_id": request["request_id"],
                    "ok": True,
                    "action": "screen",
                    "output": "PUBLIC_CLI_BROKER_OK",
                    "restart_count": 0,
                }
                (responses / request_path.name).write_bytes(
                    runner._canonical_json_bytes(response) + b"\n"
                )
            time.sleep(0.01)

    driver_thread = threading.Thread(target=fake_driver, daemon=True)
    driver_thread.start()
    broker = subprocess.Popen(
        [
            "/usr/bin/python3",
            "-I",
            "-B",
            str(runner.PUBLIC_CLI_BROKER_SOURCE),
            "--control-dir",
            str(control),
            "--socket",
            str(socket_path),
            "--trace",
            str(trace_path),
            "--ready",
            str(ready_path),
            "--cleanup",
            str(cleanup_path),
        ],
        cwd=case_root,
        env={
            "HOME": str(home),
            "PATH": "/usr/bin:/bin",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
        },
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 5
        while not ready_path.is_file() and time.monotonic() < deadline:
            if broker.poll() is not None:
                break
            time.sleep(0.02)
        assert ready_path.is_file()
        client_env = {
            "HOME": str(case_root / "client-home"),
            "PATH": "/usr/bin:/bin",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "MAUDE_PUBLIC_SOCKET": str(socket_path),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
        }
        success = subprocess.run(
            [
                "/usr/bin/python3",
                "-I",
                "-B",
                str(runner.HARNESS_DIR / "public_cli.py"),
                "--screen",
            ],
            cwd=case_root,
            env=client_env,
            check=False,
            capture_output=True,
            timeout=5,
        )
        timed_out = subprocess.run(
            [
                "/usr/bin/python3",
                "-I",
                "-B",
                str(runner.HARNESS_DIR / "public_cli.py"),
                "--timeout",
                "0.1",
                "--wait",
                "0",
            ],
            cwd=case_root,
            env=client_env,
            check=False,
            capture_output=True,
            timeout=5,
        )
    finally:
        if broker.poll() is None:
            os.killpg(broker.pid, signal.SIGTERM)
        broker_stdout, broker_stderr = broker.communicate(timeout=5)
        stopped.set()
        driver_thread.join(timeout=2)

    assert broker.returncode == 0, broker_stderr.decode(errors="replace")
    assert broker_stdout == b""
    assert success.returncode == 0
    assert success.stdout == b"PUBLIC_CLI_BROKER_OK\n"
    assert success.stderr == b""
    assert timed_out.returncode == 1
    assert b"retained unknown settlement" in timed_out.stderr
    traces = [
        json.loads(line)
        for line in trace_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(traces) == 2
    assert traces[0]["settlement"] == "completed"
    assert traces[0]["correlation_complete"] is True
    assert traces[1]["settlement"] == (
        "retained-unknown-after-public-timeout"
    )
    assert traces[1]["queue_request_retained"] is True
    assert traces[1]["correlation_complete"] is False
    assert traces[1]["queue_response_observed_at_return"] is False
    assert traces[1]["public_response"]["terminal_state"] == "unknown"
    assert str(control) not in trace_path.read_text(encoding="utf-8")
    cleanup = json.loads(cleanup_path.read_text(encoding="utf-8"))
    assert cleanup["no_request_in_flight"] is True
    assert cleanup["public_socket_removed"] is True
    assert cleanup["raw_control_dir_exposed_to_client"] is False
    assert not socket_path.exists()
    return {
        "success_returncode": success.returncode,
        "timeout_returncode": timed_out.returncode,
        "trace_records": len(traces),
        "completed_rpc_correlated": True,
        "timeout_preserved_as_retained_unknown": True,
        "raw_control_path_absent_from_public_trace": True,
        "cleanup": cleanup,
        "all_passed": True,
    }


def installation_static_visible_paths_case(
    diagnostics_root: Path,
) -> dict[str, Any]:
    """Keep supplied operator helpers static while ignoring generated trees."""

    install_root = diagnostics_root / "installation-static-visible-paths"
    static_files = {
        "operator/operator-pty": "#!/usr/bin/env python3\n",
        "operator/operator-retrospective": "#!/usr/bin/env python3\n",
        "docs/commands.md": "# Commands\n",
        "task/task.json": "{}\n",
    }
    generated_files = {
        "work/generated.txt": "work\n",
        "home/.config/maude/state": "home\n",
        "run/xdg/runtime-state": "run\n",
        "venv/lib/python/site-packages/generated.py": "venv\n",
    }
    for relative, content in {**static_files, **generated_files}.items():
        path = install_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    observed = runner._installation_static_visible_paths(install_root)
    assert observed == set(static_files)
    assert "operator/operator-pty" in observed
    assert "operator/operator-retrospective" in observed
    assert not observed.intersection(generated_files)
    return {
        "static_visible_paths": sorted(observed),
        "generated_paths_excluded": sorted(generated_files),
        "operator_helpers_retained": [
            "operator/operator-pty",
            "operator/operator-retrospective",
        ],
        "all_passed": True,
    }


def retrospective_action_deduplication_case() -> dict[str, Any]:
    """Count one helper command, never a helper name printed in output."""

    helper_command = (
        "./operator-retrospective --disposition-file "
        "/home/operator/initial-disposition.md"
    )
    paired_events = [
        {
            "type": "item.started",
            "item": {
                "id": "retrospective-action",
                "type": "command_execution",
                "command": helper_command,
                "status": "in_progress",
            },
        },
        {
            "type": "item.completed",
            "item": {
                "id": "retrospective-action",
                "type": "command_execution",
                "command": helper_command,
                "status": "completed",
                "exit_code": 0,
                "aggregated_output": (
                    "operator-retrospective completed successfully\n"
                ),
            },
        },
    ]
    paired_actions = runner._event_actions(paired_events)
    assert len(paired_actions) == 1
    assert paired_actions[0]["event_numbers"] == [1, 2]
    paired_analysis = runner._retrospective_action_analysis(
        paired_actions[0]
    )
    assert len(paired_analysis["invocations"]) == 1
    assert paired_analysis["mentions_helper"] is True

    result_only_events = [
        {
            "type": "item.completed",
            "item": {
                "id": "ordinary-action",
                "type": "command_execution",
                "command": "/usr/bin/printf done",
                "status": "completed",
                "exit_code": 0,
                "aggregated_output": (
                    "operator-retrospective --disposition-file "
                    "/home/operator/initial-disposition.md\n"
                ),
            },
        }
    ]
    result_only_actions = runner._event_actions(result_only_events)
    assert len(result_only_actions) == 1
    result_only_analysis = runner._retrospective_action_analysis(
        result_only_actions[0]
    )
    assert result_only_analysis["invocations"] == []
    assert result_only_analysis["mentions_helper"] is False
    assert result_only_analysis["retrospective_related"] is False
    return {
        "paired_event_count": len(paired_events),
        "deduplicated_action_count": len(paired_actions),
        "helper_invocation_count": len(paired_analysis["invocations"]),
        "helper_name_in_result_only_counted": False,
        "all_passed": True,
    }


def public_socket_policy_case() -> dict[str, Any]:
    """Accept only one declared public socket and reject raw queue exposure."""

    target = str(runner.PUBLIC_CLI_SOCKET_MOUNT)
    exact_policy = {
        "environment": {"MAUDE_PUBLIC_SOCKET": target},
        "sockets": [
            {
                "source": "/tmp/synthetic-public-cli.sock",
                "target": target,
            }
        ],
        "mounts": [],
    }
    observed = runner._public_cli_boundary_from_policy(
        exact_policy,
        label="exact-policy",
    )
    assert observed == {
        "raw_driver_queue_exposed": False,
        "environment_variable": "MAUDE_PUBLIC_SOCKET",
        "socket_target": target,
        "exact_socket_count": 1,
    }

    invalid_policies = {
        "raw-control-environment": {
            **exact_policy,
            "environment": {
                **exact_policy["environment"],
                "MAUDE_LAB_CONTROL_DIR": "/private/control",
            },
        },
        "raw-control-mount": {
            **exact_policy,
            "mounts": [
                {
                    "source": "/tmp/private-control",
                    "target": "/private/control",
                    "mode": "rw",
                }
            ],
        },
        "duplicate-public-socket": {
            **exact_policy,
            "sockets": [
                *exact_policy["sockets"],
                {
                    "source": "/tmp/duplicate-public-cli.sock",
                    "target": target,
                },
            ],
        },
    }
    rejected: list[str] = []
    for name, policy in invalid_policies.items():
        try:
            runner._public_cli_boundary_from_policy(
                policy,
                label=name,
            )
        except runner.CampaignError:
            rejected.append(name)
        else:
            raise AssertionError(f"invalid public socket policy accepted: {name}")
    assert sorted(rejected) == sorted(invalid_policies)
    return {
        "exact_policy": observed,
        "invalid_policies_rejected": sorted(rejected),
        "all_passed": True,
    }


def suffixless_operator_helper_media_type_case() -> dict[str, Any]:
    """Derive media type from each operator-visible destination."""

    helper_bytes = b"#!/usr/bin/env python3\nprint('synthetic helper')\n"
    observed = {
        destination: common.media_type_for_path(
            Path(destination),
            helper_bytes,
        )
        for destination in (
            "operator/operator-pty",
            "operator/operator-retrospective",
        )
    }
    assert set(observed.values()) == {"text/plain"}
    assert (
        common.media_type_for_path(
            Path("operator/suffixless-binary"),
            b"\x00\xff",
        )
        == "application/octet-stream"
    )
    return {
        "destination_media_types": observed,
        "suffixless_binary_media_type": "application/octet-stream",
        "all_passed": True,
    }


def grade_failure_class_uniqueness_case() -> dict[str, Any]:
    """Accept unique failure classes and reject duplicate classifications."""

    unique = {
        "failure_classes": [
            "command discoverability failure",
            "documentation defect",
        ]
    }
    runner._validate_grade_local_invariants(unique)

    duplicate = {
        "failure_classes": [
            "documentation defect",
            "documentation defect",
        ]
    }
    duplicate_rejected = False
    try:
        runner._validate_grade_local_invariants(duplicate)
    except runner.CampaignError:
        duplicate_rejected = True
    assert duplicate_rejected
    return {
        "unique_failure_classes_accepted": unique["failure_classes"],
        "duplicate_failure_classes_rejected": duplicate_rejected,
        "all_passed": True,
    }


def installation_terminal_action_sequence_case() -> dict[str, Any]:
    """Require exact positional commands while permitting repeated values."""

    exact_commands = runner._installation_pty_commands(
        adapter=Path("/synthetic/operator-pty"),
        pty_state=Path("/synthetic/state"),
        typescript=Path("/synthetic/typescript"),
        maude=Path("/synthetic/venv/bin/maude"),
    )

    def events_for(
        commands: list[str],
        *,
        completed_commands: list[str] | None = None,
        second_event_type: str = "item.completed",
        include_timeout: bool = False,
        completed_include_timeout: bool | None = None,
    ) -> list[dict[str, Any]]:
        completed_values = (
            commands if completed_commands is None else completed_commands
        )
        completed_timeout = (
            include_timeout
            if completed_include_timeout is None
            else completed_include_timeout
        )
        assert len(commands) == len(completed_values)
        events: list[dict[str, Any]] = []
        for index, (started_command, completed_command) in enumerate(
            zip(commands, completed_values, strict=True),
            1,
        ):
            started_arguments = {"command": started_command}
            completed_arguments = {"command": completed_command}
            if include_timeout:
                started_arguments["timeout_seconds"] = (
                    runner.PROVIDER_PROBE_TERMINAL_TIMEOUT_SECONDS
                )
            if completed_timeout:
                completed_arguments["timeout_seconds"] = (
                    runner.PROVIDER_PROBE_TERMINAL_TIMEOUT_SECONDS
                )
            common = {
                "id": f"installation-action-{index}",
                "type": "mcp_tool_call",
                "server": "operator",
                "tool": "terminal",
                "error": None,
            }
            events.append(
                {
                    "type": "item.started",
                    "item": {
                        **common,
                        "arguments": started_arguments,
                        "result": None,
                        "status": "in_progress",
                    },
                }
            )
            events.append(
                {
                    "type": second_event_type,
                    "item": {
                        **common,
                        "arguments": completed_arguments,
                        "result": {"content": []},
                        "status": "completed",
                    },
                }
            )
        return events

    actions = runner._event_actions(events_for(exact_commands))
    records = runner._installation_terminal_action_commands(
        actions,
        provider="openai-sol",
        expected_commands=exact_commands,
    )
    observed_commands = [record["command"] for record in records]
    assert observed_commands == exact_commands
    assert [record["position"] for record in records] == list(range(1, 9))
    assert all(
        record["same_command_in_started_and_completed"] is True
        for record in records
    )
    assert exact_commands[1] == exact_commands[4] == exact_commands[6]
    assert observed_commands.count(exact_commands[1]) == 3
    assert all(record["argument_keys"] == ["command"] for record in records)

    timeout_actions = runner._event_actions(
        events_for(exact_commands, include_timeout=True)
    )
    timeout_records = runner._installation_terminal_action_commands(
        timeout_actions,
        provider="openai-sol",
        expected_commands=exact_commands,
    )
    assert [record["command"] for record in timeout_records] == exact_commands
    assert all(
        record["argument_keys"] == ["command", "timeout_seconds"]
        and record["explicit_timeout_seconds"]
        == runner.PROVIDER_PROBE_TERMINAL_TIMEOUT_SECONDS
        for record in timeout_records
    )

    rejected: list[str] = []

    def reject(name: str, malformed_actions: list[dict[str, Any]]) -> None:
        try:
            runner._installation_terminal_action_commands(
                malformed_actions,
                provider="openai-sol",
                expected_commands=exact_commands,
            )
        except runner.CampaignError:
            rejected.append(name)
        else:
            raise AssertionError(
                f"malformed installation action accepted: {name}"
            )

    reordered_actions = list(actions)
    reordered_actions[1], reordered_actions[2] = (
        reordered_actions[2],
        reordered_actions[1],
    )
    reject("out-of-order-actions", reordered_actions)
    changed_completion = list(exact_commands)
    changed_completion[1] += " "
    reject(
        "started-completed-command-mismatch",
        runner._event_actions(
            events_for(
                exact_commands,
                completed_commands=changed_completion,
            )
        ),
    )
    reject(
        "started-completed-argument-shape-mismatch",
        runner._event_actions(
            events_for(
                exact_commands,
                include_timeout=True,
                completed_include_timeout=False,
            )
        ),
    )
    reject(
        "completed-observation-reported-as-started",
        runner._event_actions(
            events_for(
                exact_commands,
                second_event_type="item.started",
            )
        ),
    )
    extra_argument = json.loads(json.dumps(actions))
    extra_argument[0]["input"]["observations"][0]["item"]["arguments"][
        "unexpected"
    ] = True
    extra_argument[0]["input"]["observations"][0]["item_sha256"] = (
        runner.sha256_bytes(
            runner._canonical_json_bytes(
                extra_argument[0]["input"]["observations"][0]["item"]
            )
        )
    )
    reject("extra-terminal-argument", extra_argument)
    wrong_timeout = json.loads(json.dumps(timeout_actions))
    for observation in wrong_timeout[0]["input"]["observations"]:
        observation["item"]["arguments"]["timeout_seconds"] = (
            runner.PROVIDER_PROBE_TERMINAL_TIMEOUT_SECONDS + 1
        )
        observation["item_sha256"] = runner.sha256_bytes(
            runner._canonical_json_bytes(observation["item"])
        )
    reject("wrong-terminal-timeout", wrong_timeout)
    digest_tamper = json.loads(json.dumps(actions))
    digest_tamper[0]["input"]["observations"][0]["item_sha256"] = "0" * 64
    reject("observation-digest-tamper", digest_tamper)
    assert sorted(rejected) == [
        "completed-observation-reported-as-started",
        "extra-terminal-argument",
        "observation-digest-tamper",
        "out-of-order-actions",
        "started-completed-argument-shape-mismatch",
        "started-completed-command-mismatch",
        "wrong-terminal-timeout",
    ]
    return {
        "exact_command_count": len(exact_commands),
        "repeated_read_command_positions": [2, 5, 7],
        "repeated_values_accepted_positionally": True,
        "accepted_terminal_argument_key_sets": [
            ["command"],
            ["command", "timeout_seconds"],
        ],
        "out_of_order_actions_rejected": True,
        "strict_action_tampers_rejected": sorted(rejected),
        "all_passed": True,
    }


def installation_broker_result_parser_case() -> dict[str, Any]:
    """Reject anything except the exact nested broker/PTY result contract."""

    command = "'/synthetic/operator-pty' status --state '/synthetic/state'"
    cwd = Path("/synthetic/work")
    exact_commands = runner._installation_pty_commands(
        adapter=Path("/synthetic/operator-pty"),
        pty_state=Path("/synthetic/state"),
        typescript=Path("/synthetic/typescript"),
        maude=Path("/synthetic/venv/bin/maude"),
    )
    assert len(exact_commands) == 8
    assert exact_commands[2].endswith("--input hex:09")
    assert exact_commands[3].endswith("--input hex:7374617475730d")
    assert "hex:09 " not in exact_commands[3]
    assert exact_commands[5].endswith("--input hex:11 --wait 5")
    state = {
        "captured_bytes": 42,
        "child_pid": 5,
        "command": ["/synthetic/maude"],
        "daemon_pid": 4,
        "exit_code": None,
        "output": "/synthetic/typescript",
        "schema": "maude.synthetic-operator.stateful-pty.v1",
        "status": "running",
        "updated_at": "2026-07-28T00:00:00Z",
    }
    read = {
        "bytes_read": 42,
        "from_offset": 0,
        "next_offset": 42,
        "status": "running",
    }
    ack = {
        "accepted": True,
        "acknowledged_at": "2026-07-28T00:00:01Z",
        "error": None,
        "inputs_sent": 1,
        "operation": "send",
        "request_id": "synthetic-request",
        "schema": "maude.synthetic-operator.stateful-pty-ack.v1",
        "state": state,
    }

    def envelope(*, stdout: str, stderr: str) -> dict[str, Any]:
        return {
            "command": command,
            "cwd": str(cwd),
            "returncode": 0,
            "stderr": stderr,
            "stderr_truncated": False,
            "stdout": stdout,
            "stdout_truncated": False,
            "timed_out": False,
        }

    def encoded(value: Any) -> str:
        return json.dumps(value, separators=(",", ":"), sort_keys=True)

    parsed_state = runner._parse_installation_broker_result(
        encoded(envelope(stdout=encoded(state) + "\n", stderr="")),
        expected_command=command,
        expected_cwd=cwd,
        payload_kind="state",
    )
    parsed_read = runner._parse_installation_broker_result(
        encoded(envelope(stdout="terminal bytes", stderr=encoded(read) + "\n")),
        expected_command=command,
        expected_cwd=cwd,
        payload_kind="read",
    )
    parsed_ack = runner._parse_installation_broker_result(
        encoded(envelope(stdout="", stderr=encoded(ack) + "\n")),
        expected_command=command,
        expected_cwd=cwd,
        payload_kind="ack",
    )
    assert parsed_state["payload"] == state
    assert parsed_state["metadata_stream"] == "stdout"
    assert parsed_read["payload"] == read
    assert parsed_read["metadata_stream"] == "stderr"
    assert parsed_ack["payload"] == ack

    stop_ack = dict(ack)
    stop_ack["operation"] = "stop"
    stop_ack["request_id"] = "synthetic-stop-request"
    eight_action_payload_kinds = (
        "state",
        "read",
        "ack",
        "ack",
        "read",
        "ack",
        "read",
        "state",
    )
    eight_action_outputs = (
        envelope(stdout=encoded(state), stderr=""),
        envelope(stdout="initial terminal bytes", stderr=encoded(read)),
        envelope(stdout="", stderr=encoded(ack)),
        envelope(stdout="", stderr=encoded(ack)),
        envelope(stdout="status terminal bytes", stderr=encoded(read)),
        envelope(stdout="", stderr=encoded(stop_ack)),
        envelope(stdout="final terminal bytes", stderr=encoded(read)),
        envelope(stdout=encoded(state), stderr=""),
    )
    parsed_sequence = [
        runner._parse_installation_broker_result(
            encoded(output),
            expected_command=command,
            expected_cwd=cwd,
            payload_kind=payload_kind,
        )
        for output, payload_kind in zip(
            eight_action_outputs,
            eight_action_payload_kinds,
            strict=True,
        )
    ]
    assert len(parsed_sequence) == 8
    assert [
        value["metadata_stream"] for value in parsed_sequence
    ] == [
        "stdout",
        "stderr",
        "stderr",
        "stderr",
        "stderr",
        "stderr",
        "stderr",
        "stdout",
    ]
    assert [
        parsed_sequence[index]["payload"]["operation"]
        for index in (2, 3, 5)
    ] == ["send", "send", "stop"]

    rejected: list[str] = []

    def reject(
        name: str,
        output: str,
        *,
        payload_kind: str = "state",
        expected_command: str = command,
        expected_cwd: Path = cwd,
    ) -> None:
        try:
            runner._parse_installation_broker_result(
                output,
                expected_command=expected_command,
                expected_cwd=expected_cwd,
                payload_kind=payload_kind,
            )
        except runner.CampaignError:
            rejected.append(name)
        else:
            raise AssertionError(f"malformed broker result accepted: {name}")

    extra_outer = envelope(stdout=encoded(state), stderr="")
    extra_outer["schema"] = "invented"
    reject("extra-outer-key", encoded(extra_outer))
    reject(
        "wrong-command",
        encoded(envelope(stdout=encoded(state), stderr="")),
        expected_command="different",
    )
    reject(
        "wrong-cwd",
        encoded(envelope(stdout=encoded(state), stderr="")),
        expected_cwd=Path("/different"),
    )
    for field, value in (
        ("returncode", False),
        ("returncode", 1),
        ("timed_out", True),
        ("stdout_truncated", True),
        ("stderr_truncated", True),
    ):
        invalid = envelope(stdout=encoded(state), stderr="")
        invalid[field] = value
        reject(f"invalid-{field}-{value!r}", encoded(invalid))
    valid_state_result = encoded(envelope(stdout=encoded(state), stderr=""))
    reject(
        "concatenated-outer-json",
        valid_state_result + "\n" + valid_state_result,
    )
    reject(
        "duplicate-outer-key",
        valid_state_result[:-1] + ',"returncode":0}',
    )
    reject(
        "concatenated-inner-json",
        encoded(
            envelope(
                stdout=encoded(state) + "\n" + encoded(state),
                stderr="",
            )
        ),
    )
    reject(
        "duplicate-inner-key",
        encoded(
            envelope(
                stdout=encoded(state)[:-1] + ',"daemon_pid":4}',
                stderr="",
            )
        ),
    )
    extra_state = dict(state)
    extra_state["invented"] = True
    reject(
        "extra-state-key",
        encoded(envelope(stdout=encoded(extra_state), stderr="")),
    )
    wrong_state_schema = dict(state)
    wrong_state_schema["schema"] = "wrong"
    reject(
        "wrong-state-schema",
        encoded(envelope(stdout=encoded(wrong_state_schema), stderr="")),
    )
    reject(
        "state-unexpected-stderr",
        encoded(envelope(stdout=encoded(state), stderr="unexpected")),
    )
    extra_read = dict(read)
    extra_read["invented"] = True
    reject(
        "extra-read-key",
        encoded(
            envelope(stdout="terminal bytes", stderr=encoded(extra_read))
        ),
        payload_kind="read",
    )
    reject(
        "empty-read-stdout",
        encoded(envelope(stdout="", stderr=encoded(read))),
        payload_kind="read",
    )
    reject(
        "ack-on-wrong-stream",
        encoded(envelope(stdout=encoded(ack), stderr="")),
        payload_kind="ack",
    )
    reject(
        "ack-unexpected-stdout",
        encoded(envelope(stdout="unexpected", stderr=encoded(ack))),
        payload_kind="ack",
    )
    extra_ack = dict(ack)
    extra_ack["invented"] = True
    reject(
        "extra-ack-key",
        encoded(envelope(stdout="", stderr=encoded(extra_ack))),
        payload_kind="ack",
    )
    reject(
        "inner-non-object",
        encoded(envelope(stdout="[]", stderr="")),
    )
    reject(
        "unsupported-payload-kind",
        valid_state_result,
        payload_kind="invented",
    )
    assert len(rejected) == 22
    return {
        "valid_contracts": ["state", "read", "ack"],
        "exact_focus_aware_command_count": len(exact_commands),
        "tab_and_status_are_separate_actions": True,
        "exact_eight_action_payload_kinds": list(
            eight_action_payload_kinds
        ),
        "malformed_or_ambiguous_results_rejected": rejected,
        "all_passed": True,
    }


def installation_rpc_contract_case() -> dict[str, Any]:
    """Pin startup/poll evidence separately from typed-status evidence."""

    captured_methods = [
        "governor.hello",
        "sessions.list",
        "sessions.create",
        "governor.now",
        "governor.status",
        "runtime.session.list",
        "governor.now",
    ]

    def pairs(
        methods: list[str],
        *,
        error_at: int | None = None,
    ) -> list[dict[str, Any]]:
        return [
            {
                "method": method,
                "response_kind": (
                    "error" if index == error_at else "result"
                ),
            }
            for index, method in enumerate(methods)
        ]

    captured = runner._installation_rpc_contract_predicates(
        pairs(captured_methods)
    )
    assert captured
    assert all(captured.values())

    startup_only = runner._installation_rpc_contract_predicates(
        pairs(
            [
                "governor.hello",
                "sessions.list",
                "sessions.create",
                "governor.now",
            ]
        )
    )
    assert startup_only["startup_governor_hello_observed"] is True
    assert startup_only["startup_chat_sessions_list_observed"] is True
    assert (
        startup_only["empty_startup_chat_session_create_observed"]
        is True
    )
    assert startup_only["scheduled_governor_now_poll_observed"] is True
    assert startup_only["startup_rpc_sequence_exact_prefix"] is True
    assert startup_only["typed_status_governor_status_observed"] is False
    assert (
        startup_only["typed_status_runtime_session_list_observed"]
        is False
    )
    assert startup_only["typed_status_rpc_sequence_in_order"] is False

    wrong_order = runner._installation_rpc_contract_predicates(
        pairs(
            [
                "governor.hello",
                "sessions.list",
                "sessions.create",
                "governor.now",
                "runtime.session.list",
                "governor.status",
            ]
        )
    )
    assert wrong_order["startup_rpc_sequence_exact_prefix"] is True
    assert wrong_order["typed_status_governor_status_observed"] is True
    assert (
        wrong_order["typed_status_runtime_session_list_observed"] is False
    )
    assert wrong_order["typed_status_rpc_sequence_in_order"] is False

    errored = runner._installation_rpc_contract_predicates(
        pairs(captured_methods, error_at=4)
    )
    assert errored["all_runtime_trace_responses_are_results"] is False
    assert errored["typed_status_governor_status_observed"] is False
    assert errored["typed_status_rpc_sequence_in_order"] is False

    empty = runner._installation_rpc_contract_predicates([])
    assert empty
    assert not any(empty.values())
    return {
        "captured_contract_predicates": captured,
        "startup_only_does_not_prove_typed_status": True,
        "typed_status_wrong_order_rejected": True,
        "error_response_rejected": True,
        "empty_trace_rejected": True,
        "typed_input_rpc_attribution_requires_ordered_pair": True,
        "all_passed": True,
    }


def pty_graceful_cleanup_case(
    diagnostics_root: Path,
) -> dict[str, Any]:
    """Prove correlated request-file shutdown without process-group signals."""

    case_root = diagnostics_root / "pty-graceful-cleanup"
    case_root.mkdir(parents=True)
    shutdown_path = case_root / "shutdown-request.json"
    cleanup_path = case_root / "cleanup.json"
    socket_path = case_root / "broker.sock"
    socket_path.write_text("synthetic socket placeholder\n", encoding="utf-8")
    child_source = (
        "import json,pathlib,time;"
        f"shutdown=pathlib.Path({str(shutdown_path)!r});"
        f"cleanup=pathlib.Path({str(cleanup_path)!r});"
        f"socket_path=pathlib.Path({str(socket_path)!r});"
        "\nwhile not shutdown.is_file(): time.sleep(0.01)"
        "\nrequest=json.loads(shutdown.read_text(encoding='utf-8'))"
        "\nsocket_path.unlink()"
        "\nshutdown.unlink()"
        "\nvalue={"
        "'schema':'maude.synthetic-operator.pty-broker-cleanup.v1',"
        "'broker_pid':0,'handled_requests':0,'tracked_ptys':[],"
        "'all_tracked_ptys_stopped':True,'socket_removed':True,"
        "'shutdown_request':request,'shutdown_request_removed':True,"
        "'shutdown_mode':'request-file','shutdown_signal':None,"
        "'completed_at':'synthetic'}"
        "\ncleanup.write_text(json.dumps(value,sort_keys=True)+'\\n',"
        "encoding='utf-8')"
    )
    process = runner.ManagedProcess(
        ["/usr/bin/python3", "-c", child_source],
        cwd=case_root,
        stdout_path=case_root / "broker.stdout",
        stderr_path=case_root / "broker.stderr",
    )
    process_record, cleanup = runner._stop_pty_boundary_process(
        process,
        label="synthetic PTY broker",
        pty={
            "shutdown_host": shutdown_path,
            "cleanup_host": cleanup_path,
            "socket_host": socket_path,
        },
        provider_absent_or_exited=True,
    )
    request = process_record["graceful_shutdown_request"]
    parsed_request_path = case_root / "parse-request.json"
    parsed_request_path.write_text(
        json.dumps(request, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    assert pty_adapter._load_shutdown_request(parsed_request_path) == request
    invalid_request_path = case_root / "invalid-request.json"
    invalid_request_path.write_text(
        '{"schema":"wrong","request_id":"x","requested_at":"synthetic"}\n',
        encoding="utf-8",
    )
    invalid_rejected = False
    try:
        pty_adapter._load_shutdown_request(invalid_request_path)
    except RuntimeError:
        invalid_rejected = True
    assert invalid_rejected
    assert process_record["exit_code"] == 0
    assert process_record["graceful_exit_requested"] is True
    assert process_record["forced_after_graceful_timeout"] is False
    assert process_record["remaining_processes"] == []
    assert process_record["shutdown_control_boundary"] == {
        "path_visibility": "shared-persistent-pty-namespace",
        "created_after_provider_absent_or_exited": True,
        "contains_authority_or_secret": False,
        "request_fields": ["request_id", "requested_at", "schema"],
        "tamper_or_preexistence_policy": "fail-closed-then-force-stop",
    }
    assert cleanup["shutdown_request"] == request
    assert cleanup["shutdown_mode"] == "request-file"
    assert cleanup["shutdown_request_removed"] is True
    assert cleanup["socket_removed"] is True
    assert not shutdown_path.exists()
    assert not socket_path.exists()
    failure_root = case_root / "preexisting-evidence-failure"
    failure_root.mkdir()
    failure_shutdown = failure_root / "shutdown-request.json"
    failure_shutdown.write_text("{}\n", encoding="utf-8")
    failure_process = runner.ManagedProcess(
        ["/usr/bin/python3", "-c", "import time;time.sleep(60)"],
        cwd=failure_root,
        stdout_path=failure_root / "broker.stdout",
        stderr_path=failure_root / "broker.stderr",
    )
    fallback_stopped_process = False
    try:
        runner._stop_pty_boundary_process(
            failure_process,
            label="synthetic invalid PTY broker",
            pty={
                "shutdown_host": failure_shutdown,
                "cleanup_host": failure_root / "cleanup.json",
                "socket_host": failure_root / "broker.sock",
            },
            provider_absent_or_exited=True,
        )
    except runner.CampaignError:
        fallback_stopped_process = failure_process.process.poll() is not None
    assert fallback_stopped_process
    return {
        "graceful_shutdown_request_correlated": True,
        "process_exit_code": process_record["exit_code"],
        "forced_signal_used": False,
        "remaining_processes": [],
        "socket_removed": True,
        "shutdown_request_removed": True,
        "invalid_request_rejected": invalid_rejected,
        "failed_graceful_request_forced_safe_stop": (
            fallback_stopped_process
        ),
        "all_passed": True,
    }


def pty_real_bwrap_graceful_cleanup_case(
    diagnostics_root: Path,
) -> dict[str, Any]:
    """Exercise graceful teardown through the real Bubblewrap PID namespace."""

    case_root = diagnostics_root / "pty-real-bwrap-cleanup"
    work = case_root / "work"
    operator_home = case_root / "operator-home"
    provider_home = case_root / "provider-home"
    for path in (work, operator_home, provider_home):
        path.mkdir(parents=True)
    runner._prepare_clean_operator_home(operator_home)
    adapter = work / "operator-pty"
    shutil.copy2(runner.HARNESS_DIR / "operator_pty.py", adapter)
    adapter.chmod(0o755)
    boundary = runner._build_claude_boundary(
        label="real-bwrap-pty-cleanup",
        lab=case_root,
        mode="operator",
        provider_home=provider_home,
        cwd=work,
        operator_home=operator_home,
        mounts=[
            {"source": str(work), "target": str(work), "mode": "rw"},
            {
                "source": str(operator_home),
                "target": str(runner.OPERATOR_HOME_MOUNT),
                "mode": "rw",
            },
        ],
        sockets=[],
        environment=runner._claude_clean_environment(operator_home),
        pty_adapter=adapter,
    )
    pty = boundary["pty_broker"]
    assert isinstance(pty, dict)
    process: runner.ManagedProcess | None = None
    cleanup: dict[str, Any] | None = None
    process_record: dict[str, Any] | None = None
    try:
        process = runner.ManagedProcess(
            runner._pty_broker_bwrap_argv(boundary),
            cwd=boundary["transport_cwd"],
            stdout_path=pty["private_state"] / "broker.stdout",
            stderr_path=pty["private_state"] / "broker.stderr",
            env=runner._clean_boundary_process_environment(
                boundary["private_state"] / "pty-broker-test-home"
            ),
        )
        runner._wait_path_with_process(pty["ready_host"], process)
        state = work / "state"
        transcript = work / "typescript"
        environment = dict(os.environ)
        environment[pty_adapter.BROKER_ENV] = str(pty["socket_host"])
        started = subprocess.run(
            [
                "/usr/bin/python3",
                "-I",
                "-B",
                str(adapter),
                "start",
                "--state",
                str(state),
                "--output",
                str(transcript),
                "--",
                "/usr/bin/sleep",
                "60",
            ],
            cwd=work,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=10,
        )
        assert started.returncode == 0, started.stderr.decode(
            errors="replace"
        )
        process_record, cleanup = runner._stop_pty_boundary_process(
            process,
            label="real Bubblewrap PTY broker",
            pty=pty,
            provider_absent_or_exited=True,
        )
        process = None
        assert process_record["exit_code"] == 0
        assert process_record["forced_after_graceful_timeout"] is False
        assert process_record["remaining_processes"] == []
        assert cleanup["all_tracked_ptys_stopped"] is True
        assert len(cleanup["tracked_ptys"]) == 1
        assert cleanup["tracked_ptys"][0]["remaining"] is False
        assert cleanup["shutdown_mode"] == "request-file"
        assert cleanup["socket_removed"] is True
        assert cleanup["shutdown_request_removed"] is True
    finally:
        if process is not None:
            process.stop()
        arena_cleanup = runner._release_private_socket_directories(boundary)
    assert arena_cleanup["all_removed"] is True
    assert process_record is not None
    assert cleanup is not None
    return {
        "real_bubblewrap_invoked": True,
        "tracked_pty_count": len(cleanup["tracked_ptys"]),
        "all_tracked_ptys_stopped": cleanup[
            "all_tracked_ptys_stopped"
        ],
        "broker_exit_code": process_record["exit_code"],
        "forced_after_graceful_timeout": process_record[
            "forced_after_graceful_timeout"
        ],
        "remaining_processes": process_record["remaining_processes"],
        "socket_arena_removed": arena_cleanup["all_removed"],
        "provider_invoked": False,
        "network_invoked": False,
        "all_passed": True,
    }


def unix_socket_path_budget_case(
    diagnostics_root: Path,
) -> dict[str, Any]:
    """Prove long evidence trees use short private sockaddr_un addresses."""

    case_root = (
        diagnostics_root
        / "unix-socket-budget"
        / ("deliberately-long-evidence-segment-" * 5)
    )
    operator = case_root / "operator"
    operator_home = case_root / "operator-home"
    provider_home = case_root / "provider-home"
    for path in (operator, operator_home, provider_home):
        path.mkdir(parents=True)
    runner._prepare_clean_operator_home(operator_home)
    boundary = runner._build_claude_boundary(
        label="deliberately-long-boundary-label-" + ("z" * 160),
        lab=case_root,
        mode="operator",
        provider_home=provider_home,
        cwd=operator,
        operator_home=operator_home,
        mounts=[
            {
                "source": str(operator),
                "target": str(operator),
                "mode": "ro",
            },
            {
                "source": str(operator_home),
                "target": str(runner.OPERATOR_HOME_MOUNT),
                "mode": "rw",
            },
        ],
        sockets=[],
        environment=runner._claude_clean_environment(operator_home),
        pty_adapter=runner.HARNESS_DIR / "operator_pty.py",
    )
    broker = boundary["command_broker"]
    pty = boundary["pty_broker"]
    assert isinstance(broker, dict)
    assert isinstance(pty, dict)
    hypothetical_old_path = (
        boundary["private_state"] / "command-broker.sock"
    )
    assert len(os.fsencode(str(hypothetical_old_path))) > 107
    actual_paths = [
        Path(broker["socket"]),
        Path(pty["socket_host"]),
        runner.CLAUDE_COMMAND_SOCKET_MOUNT,
        Path(pty["socket_sandbox"]),
        Path(pty["server_socket_sandbox"]),
    ]
    assert all(
        len(os.fsencode(str(path))) <= runner.UNIX_SOCKET_PATH_BUDGET
        for path in actual_paths
    )
    assert str(broker["socket"]).startswith(
        str(runner.PRIVATE_SOCKET_ROOT) + os.sep
    )
    assert str(pty["socket_host"]).startswith(
        str(runner.PRIVATE_SOCKET_ROOT) + os.sep
    )
    serialized_proxy = json.dumps(boundary["proxy_bwrap_argv"])
    assert str(runner.CLAUDE_COMMAND_SOCKET_MOUNT.parent) in serialized_proxy

    long_rejected = False
    try:
        runner._checked_unix_socket_path(
            Path("/tmp") / ("x" * 200),
            label="deliberately over-budget self-test",
        )
    except runner.CampaignError:
        long_rejected = True
    assert long_rejected

    pty_listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    command_process: runner.ManagedProcess | None = None
    try:
        pty_listener.bind(str(pty["socket_host"]))
        pty_listener.listen(1)
        command_process = runner.ManagedProcess(
            broker["argv"],
            cwd=boundary["transport_cwd"],
            stdout_path=broker["stdout"],
            stderr_path=broker["stderr"],
            env=runner._clean_boundary_process_environment(
                boundary["private_state"] / "selftest-command-home"
            ),
        )
        runner._wait_ready(broker["ready"], command_process)
        ready = json.loads(
            Path(broker["ready"]).read_text(encoding="utf-8")
        )
        assert ready["socket"] == str(broker["socket"])
    finally:
        if command_process is not None:
            assert command_process.stop() == 0
        pty_listener.close()
        with contextlib.suppress(FileNotFoundError):
            Path(pty["socket_host"]).unlink()
    cleanup = runner._release_private_socket_directories(boundary)
    assert cleanup["all_removed"] is True
    assert all(
        record["remaining_entries"] == []
        for record in cleanup["directories"]
    )
    return {
        "hypothetical_old_path_bytes": len(
            os.fsencode(str(hypothetical_old_path))
        ),
        "path_budget_bytes": runner.UNIX_SOCKET_PATH_BUDGET,
        "actual_socket_paths": [
            {
                "path": str(path),
                "bytes": len(os.fsencode(str(path))),
            }
            for path in actual_paths
        ],
        "over_budget_path_rejected": long_rejected,
        "real_command_broker_bind_succeeded": True,
        "real_pty_socket_bind_succeeded": True,
        "private_socket_arenas_removed": cleanup["all_removed"],
        "all_passed": True,
    }


def injected_exception_case(diagnostics_root: Path, kind: str) -> dict[str, Any]:
    case_root = diagnostics_root / "exceptions" / kind
    case_root.mkdir(parents=True)
    provider_home = case_root / "provider-home"
    provider_home.mkdir()
    auth_path = provider_home / "auth.json"
    secret = f"fake-exception-secret-{kind}-123456789".encode("utf-8")
    auth_path.write_bytes(secret)
    stdout_path = case_root / "stdout.jsonl"
    stderr_path = case_root / "stderr"
    gate_path = case_root / "gate.json"
    child_pid_path = case_root / "child.pid"
    identity = event({"type": "thread.started", "thread_id": f"injected-{kind}"})
    assistant_secret = event({"type": "assistant", "text": secret.decode("utf-8")})
    assistant_next = event({"type": "assistant", "text": "after-secret"})
    provider_source = (
        "import subprocess,time;"
        "child=subprocess.Popen("
        "['/usr/bin/python3','-c','import time;time.sleep(30)'],"
        "start_new_session=True,stdout=subprocess.DEVNULL,"
        "stderr=subprocess.DEVNULL);"
        f"open({str(child_pid_path)!r},'w').write(str(child.pid));"
        f"print({identity!r},flush=True);"
        "time.sleep(0.4);"
        f"print({assistant_secret!r},flush=True);"
        "time.sleep(0.3);"
        f"print({assistant_next!r},flush=True);"
        "time.sleep(0.1)"
    )

    original_selector = runner.selectors.DefaultSelector
    original_read = runner.os.read
    original_wait = runner.subprocess.Popen.wait
    wait_failed = False

    if kind == "selector":

        class InjectedSelector:
            def __init__(self) -> None:
                self.inner = original_selector()

            def register(self, *args: Any, **kwargs: Any) -> Any:
                return self.inner.register(*args, **kwargs)

            def close(self) -> None:
                self.inner.close()

            def select(self, *args: Any, **kwargs: Any) -> Any:
                if stdout_path.is_file() and secret in stdout_path.read_bytes():
                    raise OSError("injected selector failure")
                return self.inner.select(*args, **kwargs)

        runner.selectors.DefaultSelector = InjectedSelector
    elif kind == "read":

        def injected_read(fd: int, count: int) -> bytes:
            if stdout_path.is_file() and secret in stdout_path.read_bytes():
                raise OSError("injected read failure")
            return original_read(fd, count)

        runner.os.read = injected_read
    elif kind == "wait":

        def injected_wait(
            process: subprocess.Popen[bytes], *args: Any, **kwargs: Any
        ) -> int:
            nonlocal wait_failed
            if (
                not wait_failed
                and stdout_path.is_file()
                and secret in stdout_path.read_bytes()
            ):
                wait_failed = True
                raise OSError("injected wait failure")
            return original_wait(process, *args, **kwargs)

        runner.subprocess.Popen.wait = injected_wait
    else:
        raise AssertionError(f"unknown injected exception kind: {kind}")

    observed: dict[str, Any] | None = None
    child_pid: int | None = None
    try:
        try:
            runner._run_model_process(
                ["/usr/bin/python3", "-c", provider_source],
                cwd=case_root,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
                timeout=15,
                provider="openai-sol",
                provider_home=provider_home,
                copied_auth=["auth.json"],
                credential_values=[secret],
                gate_record_path=gate_path,
            )
        except BaseException as exc:
            observed = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        runner.selectors.DefaultSelector = original_selector
        runner.os.read = original_read
        runner.subprocess.Popen.wait = original_wait
        if child_pid_path.is_file():
            child_pid = int(child_pid_path.read_text(encoding="utf-8"))

    try:
        assert observed == {
            "type": "OSError",
            "message": f"injected {kind} failure",
        }
        assert child_pid is not None
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
        assert not auth_path.exists()
        assert not stdout_path.exists()
        assert not stderr_path.exists()
        assert gate["status"] == "failed_closed_secret_quarantine"
        assert gate["raw_output_committable"] is False
        assert gate["resumed_after_proof"] is True
        assert gate["error"] == f"injected {kind} failure"
        assert gate["exception_type"] == "OSError"
        assert gate["provider_tree_remaining_after_cleanup"] == []
        assert process_state(child_pid) in {None, "Z"}
        quarantine = Path(gate["quarantine"])
        quarantined_stdout = quarantine / stdout_path.name
        quarantined_stderr = quarantine / stderr_path.name
        assert quarantined_stdout.is_file()
        assert quarantined_stderr.is_file()
        assert secret in quarantined_stdout.read_bytes()
        return {
            "kind": kind,
            "observed": observed,
            "auth_path_absent": not auth_path.exists(),
            "raw_original_paths_absent": (
                not stdout_path.exists() and not stderr_path.exists()
            ),
            "child_pid": child_pid,
            "child_state": process_state(child_pid),
            "gate_path": str(gate_path),
            "gate_status": gate["status"],
            "resumed_after_proof": gate["resumed_after_proof"],
            "error": gate["error"],
            "exception_type": gate["exception_type"],
            "provider_tree_remaining_after_cleanup": gate[
                "provider_tree_remaining_after_cleanup"
            ],
            "quarantine": str(quarantine),
        }
    finally:
        if child_pid is not None:
            kill_test_process(child_pid)


def injected_exception_matrix(diagnostics_root: Path) -> dict[str, Any]:
    cases = [
        injected_exception_case(diagnostics_root, kind)
        for kind in ("selector", "read", "wait")
    ]
    return {"cases": cases, "all_passed": len(cases) == 3}


def write_result(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    diagnostics_root = Path(tempfile.mkdtemp(prefix="maude-auth-gate-selftest-"))
    result_path = diagnostics_root / "selftest-result.json"
    original_path = runner.Path
    original_quarantine_root = runner.QUARANTINE_ROOT
    runner.Path = AuditPath
    runner.QUARANTINE_ROOT = diagnostics_root / "quarantine"
    checks: list[dict[str, Any]] = []

    check_functions: list[tuple[str, Callable[[], dict[str, Any]]]] = [
        (
            "baseline-gate-cases",
            lambda: baseline_gate_cases(diagnostics_root),
        ),
        (
            "stop-before-persistence",
            lambda: stop_before_persistence(diagnostics_root),
        ),
        ("action-and-marker-matrix", action_and_marker_matrix),
        (
            "claude-retained-boundary-cases",
            lambda: claude_retained_boundary_cases(diagnostics_root),
        ),
        (
            "mcp-protocol-negotiation-cases",
            lambda: mcp_protocol_negotiation_cases(diagnostics_root),
        ),
        (
            "codex-auth-absence-audit-cases",
            codex_auth_absence_audit_cases,
        ),
        (
            "frozen-matrix-provider-and-grader-policy",
            lambda: frozen_matrix_provider_and_grader_policy_case(
                diagnostics_root
            ),
        ),
        (
            "codex-offline-prompt-input",
            lambda: codex_offline_prompt_input_case(diagnostics_root),
        ),
        (
            "codex-strict-mcp-boundary-cases",
            lambda: codex_strict_mcp_boundary_cases(diagnostics_root),
        ),
        (
            "public-cli-broker-case",
            lambda: public_cli_broker_case(diagnostics_root),
        ),
        (
            "installation-static-visible-paths",
            lambda: installation_static_visible_paths_case(
                diagnostics_root
            ),
        ),
        (
            "retrospective-action-deduplication",
            retrospective_action_deduplication_case,
        ),
        (
            "public-socket-policy",
            public_socket_policy_case,
        ),
        (
            "suffixless-operator-helper-media-type",
            suffixless_operator_helper_media_type_case,
        ),
        (
            "grade-failure-class-uniqueness",
            grade_failure_class_uniqueness_case,
        ),
        (
            "installation-terminal-action-sequence",
            installation_terminal_action_sequence_case,
        ),
        (
            "installation-broker-result-parser",
            installation_broker_result_parser_case,
        ),
        (
            "installation-rpc-contract",
            installation_rpc_contract_case,
        ),
        (
            "pty-graceful-cleanup",
            lambda: pty_graceful_cleanup_case(diagnostics_root),
        ),
        (
            "unix-socket-path-budget",
            lambda: unix_socket_path_budget_case(diagnostics_root),
        ),
        (
            "injected-exception-matrix",
            lambda: injected_exception_matrix(diagnostics_root),
        ),
    ]
    try:
        for name, function in check_functions:
            started_at = utc_now()
            try:
                details = function()
            except BaseException as exc:
                checks.append(
                    {
                        "name": name,
                        "passed": False,
                        "started_at": started_at,
                        "completed_at": utc_now(),
                        "error": str(exc),
                        "exception_type": type(exc).__name__,
                        "traceback": traceback.format_exc(),
                    }
                )
            else:
                checks.append(
                    {
                        "name": name,
                        "passed": True,
                        "started_at": started_at,
                        "completed_at": utc_now(),
                        "details": details,
                    }
                )
    finally:
        runner.Path = original_path
        runner.QUARANTINE_ROOT = original_quarantine_root

    result = {
        "schema": "maude.synthetic-operator.auth-gate-selftest.v2",
        "completed_at": utc_now(),
        "diagnostics_root": str(diagnostics_root),
        "all_passed": all(item["passed"] for item in checks),
        "checks": checks,
        "constraints": {
            "real_provider_invoked": False,
            "network_invoked": False,
            "bubblewrap_invoked": False,
            "real_credentials_read_or_copied": False,
            "only_local_or_offline_cli_processes": True,
            "mountinfo_is_synthetic": True,
            "codex_early_scrub_contract_exercised": True,
            "claude_retained_transport_contract_exercised": True,
            "claude_mcp_boundary_simulated_locally": True,
            "codex_strict_mcp_boundary_simulated_locally": True,
            "codex_offline_prompt_input_invoked": True,
            "mcp_protocol_negotiation_exercised": True,
            "public_cli_broker_simulated_locally": True,
        },
        "authority_effect": "none",
    }
    write_result(result_path, result)
    print(result_path)
    return 0 if result["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
