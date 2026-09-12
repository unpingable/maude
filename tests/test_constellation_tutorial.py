"""Unit checks for the local-only tutorial runner boundary.

These tests mock subprocesses; they never invoke Docker or contact an endpoint.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
INPUT_LOCK = Path(__file__).resolve().parents[1] / "qualification/synthetic_cache/constellation-tutorial-input-lock.json"


def module(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


def test_tutorial_observation_coordinates_match_the_connected_nightshift_fixture():
    # Pinned Nightshift ag_governed_integration.rs constructs the C1 qualify and
    # teardown requests with digest('d')/digest('e'), then C2 with digest('6')/
    # digest('7'). The compiled proposal must bind those same observation bases.
    identity = json.loads(INPUT_LOCK.read_bytes())["identity"]
    assert [identity[name] for name in (
        "qualify_observation_id", "teardown_observation_id",
        "c2_qualify_observation_id", "c2_teardown_observation_id",
    )] == ["sha256:" + character * 64 for character in "de67"]


def test_tutorial_lock_pins_the_slot_safe_nightshift_fixture():
    source = json.loads(INPUT_LOCK.read_bytes())["source"]
    assert source["nightshift_revision"] == "eb20a7fe7d3efc478fa17c0e351e2e20febddf5b"


def test_runner_preflight_uses_kit_script_and_sanitized_endpoint(monkeypatch, tmp_path):
    runner = module("run-constellation-tutorial")
    lock = tmp_path / "lock.json"
    lock.write_text(
        '{"schema":"constellation.synthetic-cache-tutorial-input-lock/v1","runtime":{"image":"x@sha256:y"},"source":{"maude_revision":"m","nightshift_revision":"n","ag_revision":"a","docket_revision":"d"},"identity":{},"artifact_environment":{}}'
    )
    paths = {
        name: tmp_path / name
        for name in (
            "maude",
            "nightshift",
            "ag",
            "docket",
            "loop",
            "resolver",
            "effect",
            "docket-bin",
            "docker",
            "python",
        )
    }
    for path in paths.values():
        path.touch()
    captured = {}
    monkeypatch.setenv("DOCKER_CONTEXT", "ambient-remote")
    monkeypatch.setattr(
        runner,
        "args",
        lambda: __import__("argparse").Namespace(
            run=False,
            run_root=tmp_path / "fresh",
            input_lock=lock,
            docker_endpoint="unix:///tmp/docker.sock",
            maude_checkout=paths["maude"],
            nightshift_checkout=paths["nightshift"],
            ag_checkout=paths["ag"],
            docket_checkout=paths["docket"],
            ag_loopctl=paths["loop"],
            ag_standing_resolver=paths["resolver"],
            ag_effectd=paths["effect"],
            docket_bin=paths["docket-bin"],
            docker_program=paths["docker"],
            maude_python=paths["python"],
        ),
    )
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda command, **kwargs: (
            captured.update(command=command, env=kwargs["env"])
            or __import__("types").SimpleNamespace(returncode=0)
        ),
    )
    assert runner.main() == 0
    assert captured["command"][1] == str(SCRIPTS / "check-constellation-tutorial.py")
    assert captured["env"]["DOCKER_HOST"] == "unix:///tmp/docker.sock"
    assert "DOCKER_CONTEXT" not in captured["env"]


def test_runtime_handoff_helper_is_bound_to_selected_source(tmp_path):
    runner = module("run-constellation-tutorial")
    checkout = tmp_path / "frozen-maude"
    python = tmp_path / "venv/bin/python"
    env = runner.maude_environment(
        {"MAUDE_SYNTHETIC_HANDOFF_HELPER": "/unselected/helper.py"}, checkout, python
    )
    assert env["MAUDE_SYNTHETIC_HANDOFF_HELPER"] == str(
        checkout / "qualification/synthetic_cache/seal_cycle_handoff.py"
    )
    assert env["MAUDE_SRC"] == env["PYTHONPATH"] == str(checkout / "src")
    assert env["MAUDE_PYTHON"] == str(python)


def test_runner_rejects_unsafe_endpoint_before_subprocess(monkeypatch, tmp_path):
    runner = module("run-constellation-tutorial")
    monkeypatch.setattr(
        runner,
        "args",
        lambda: __import__("argparse").Namespace(
            run_root=tmp_path / "fresh",
            input_lock=tmp_path / "missing",
            docker_endpoint="tcp://example.invalid:2376",
        ),
    )
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("subprocess called"),
    )
    with pytest.raises(SystemExit, match="unix://"):
        runner.main()


def test_preflight_dirty_checkout_blocks(monkeypatch, tmp_path):
    checker = module("check-constellation-tutorial")
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / "needed").touch()
    responses = iter([(0, "abc"), (0, " changed")])
    monkeypatch.setattr(checker, "command", lambda *args, **kwargs: next(responses))
    findings = []
    checker.checkout(
        findings,
        "fixture",
        checkout,
        ("needed",),
        "abc",
        {"DOCKER_HOST": "unix:///tmp/x"},
    )
    assert any(item.level == "BLOCK" and "dirty" in item.detail for item in findings)


def test_generate_roots_must_be_absent_including_symlink(tmp_path):
    checker = module("check-constellation-tutorial")
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "artifact-link"
    link.symlink_to(target, target_is_directory=True)
    findings = []
    checker.artifacts(findings, link, "generate")
    checker.workspace(findings, link, "generate")
    assert len([item for item in findings if item.level == "BLOCK"]) == 2


@pytest.mark.parametrize(
    "endpoint",
    [
        "tcp://example.invalid:2376",
        "ssh://example.invalid",
        "unix://relative",
        "unix:///",
        "unix:///tmp/socket?host=x",
        "unix:///tmp/socket\n",
    ],
)
def test_endpoint_rejection_precedes_docker_process(monkeypatch, endpoint):
    checker = module("check-constellation-tutorial")
    monkeypatch.setattr(
        checker, "command", lambda *a, **kw: pytest.fail("Docker invoked")
    )
    findings = []
    checker.docker_runtime(
        findings,
        Path("/not-invoked/docker"),
        "image",
        checker.docker_environment(endpoint),
    )
    assert findings[0].level == "BLOCK"


def test_executable_symlink_keeps_its_invocation_path(tmp_path):
    runner = module("run-constellation-tutorial")
    checker = module("check-constellation-tutorial")
    binary = tmp_path / "system-python"
    binary.touch()
    venv_python = tmp_path / "venv-python"
    venv_python.symlink_to(binary)
    assert runner.absolute_path(venv_python, "Maude Python") == venv_python
    assert checker.absolute_path(venv_python, "Maude Python", []) == venv_python


def test_runner_rejects_dangling_run_root(monkeypatch, tmp_path):
    runner = module("run-constellation-tutorial")
    root = tmp_path / "occupied"
    root.symlink_to(tmp_path / "absent")
    monkeypatch.setattr(
        runner, "args", lambda: __import__("argparse").Namespace(run_root=root)
    )
    with pytest.raises(SystemExit, match="absent and exclusive"):
        runner.main()
