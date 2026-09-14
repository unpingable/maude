from __future__ import annotations

import json
import importlib.util
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "qualification/synthetic_cache/helpers/cache-host-bootstrap.py"
OLD_PULSE_SEMANTIC = "sha256:382b8dac14ef9353a3603757d60fc8fbc727e1bcaf088c9aab4bdf895d3f6ab1"
NEW_NQ_SEMANTIC = "sha256:2b5dbf039810736dad72d6c040c310d9bb47e248c5c6432244b23e1554fe8ba9"
ARTIFACT_ID = "sha256:" + "a" * 64
INPUTS_ID = "sha256:" + "b" * 64
SCOPE_ID = "sha256:" + "c" * 64


def dump(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def module():
    spec = importlib.util.spec_from_file_location("cache_host_bootstrap", SCRIPT)
    value = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(value)
    return value


def values(root: Path, semantic: str) -> tuple[Path, Path, Path, Path]:
    artifact = root / "artifact.json"
    request = root / "request.json"
    template = root / "pulse-template.json"
    output = root / "pulse.json"
    dump(artifact, {
        "schema": "nq.diagnostic_execution.v2", "artifact_id": ARTIFACT_ID,
        "profile": {"id": "nq.host"}, "question": {"id": "nq.host.load_pressure"},
        "profile_semantic_id": semantic, "subject": {"id": "host:cache", "scope": {"digest": SCOPE_ID}},
        "outcome": {"condition": "explicitly_absent"},
    })
    dump(request, {
        "schema": "nightshift.canonical_cycle_request.v1", "request_id": "sha256:" + "d" * 64,
        "policy": {"inventory": [{"binding": {"profile": {"id": "nq.host"},
            "question": {"id": "nq.host.load_pressure"}, "profile_semantic_id": semantic}}]},
        "inputs": {"inputs_id": INPUTS_ID, "inputs": [{"artifact": {"artifact_id": ARTIFACT_ID}}]},
    })
    dump(template, {
        "schema": "pulse.nq_host_load_pressure_support_config.v1",
        "support_family": "pulse.nq_host_load_pressure.v1", "profile_semantic_id": OLD_PULSE_SEMANTIC,
        "subject_id": "host:cache", "scope_id": SCOPE_ID,
    })
    return artifact, request, template, output


def invoke(paths: tuple[Path, Path, Path, Path]) -> subprocess.CompletedProcess[str]:
    artifact, request, template, output = paths
    return subprocess.run([
        sys.executable, str(SCRIPT), "bind", "--artifact", str(artifact.resolve()),
        "--cycle-request", str(request.resolve()), "--pulse-template", str(template.resolve()),
        "--pulse-config-out", str(output.resolve()),
    ], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def test_bind_derives_only_the_exact_diagnostic_binding(tmp_path: Path) -> None:
    paths = values(tmp_path, OLD_PULSE_SEMANTIC)
    result = invoke(paths)
    assert result.returncode == 0, result.stderr
    bound = json.loads(paths[3].read_text())
    assert bound["expected_diagnostic"] == {
        "diagnostic_inputs_id": INPUTS_ID,
        "artifact_ids": [ARTIFACT_ID],
        "expected_state": "explicitly_absent",
    }


def test_current_nq_semantic_refuses_stale_pulse_pin(tmp_path: Path) -> None:
    result = invoke(values(tmp_path, NEW_NQ_SEMANTIC))
    assert result.returncode == 2
    assert "Pulse profile semantic ID does not match" in result.stderr


def test_proposal_bearing_cycle_is_not_an_initial_host_bootstrap(tmp_path: Path) -> None:
    paths = values(tmp_path, OLD_PULSE_SEMANTIC)
    request = json.loads(paths[1].read_text())
    request["proposal"] = {"not": "allowed"}
    dump(paths[1], request)
    result = invoke(paths)
    assert result.returncode == 2
    assert "posture-only" in result.stderr


def test_role_symlink_keeps_supported_argv_zero_basename(tmp_path: Path) -> None:
    binary = tmp_path / "pulse-nq-load-support"
    binary.write_text("binary", encoding="utf-8")
    resolver = tmp_path / "pulse-support-resolver"
    resolver.symlink_to(binary)
    assert module().require_program(resolver.resolve().parent / resolver.name, "pulse-support-resolver") == str(resolver)
