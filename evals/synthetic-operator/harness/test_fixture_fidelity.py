#!/usr/bin/env python3
"""Mechanical checks for the frozen operational scenario fixtures."""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / "scenarios"
GENERATOR = SCENARIOS / "_build_corpus.py"

_SPEC = importlib.util.spec_from_file_location("synthetic_operator_corpus", GENERATOR)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"cannot import scenario generator: {GENERATOR}")
_CORPUS = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_CORPUS)


REQUIRED_SUPPORT = {
    "s01-kubernetes-image-update": {
        "clusters/store-17/kustomization.yaml",
    },
    "s03-service-resource-limit": {
        "deploy/api/kustomization.yaml",
    },
    "s04-health-check": {
        "deploy/menu-board/kustomization.yaml",
    },
    "s07-reverse-proxy-route": {
        "nginx/nginx.conf",
    },
    "s10-obsolete-daemon-config": {
        "ansible.cfg",
        "ansible/roles/edge/tasks/main.yml",
        "inventory.ini",
        "site.yml",
    },
    "s13-worker-out-of-scope": {
        "deploy/base/kustomization.yaml",
        "deploy/overlays/store-17/kustomization.yaml",
    },
    "s14-tests-pass-unauthorized": {
        "tests/test_config.py",
    },
    "s16-execution-timeout": {
        "tests/test_queue_config.py",
    },
}


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class FixtureFidelityTests(unittest.TestCase):
    def test_declared_validator_contexts_are_complete(self) -> None:
        _CORPUS.validate_fixture_contexts()
        by_id = {scenario["id"]: scenario for scenario in _CORPUS.SCENARIO_SPECS}
        self.assertEqual(set(REQUIRED_SUPPORT), set(by_id) & set(REQUIRED_SUPPORT))
        for scenario_id, expected_paths in REQUIRED_SUPPORT.items():
            self.assertEqual(
                expected_paths,
                set(by_id[scenario_id]["support_files"]),
                scenario_id,
            )

    def test_support_files_are_unchanged_and_outside_task_effects(self) -> None:
        for scenario in _CORPUS.SCENARIO_SPECS:
            with self.subTest(scenario=scenario["id"]):
                changed = {
                    path
                    for path in scenario["result_files"]
                    if scenario["base_files"][path] != scenario["result_files"][path]
                }
                support = set(scenario["support_files"])
                self.assertTrue(changed.isdisjoint(support))
                for path in support:
                    self.assertEqual(
                        scenario["base_files"][path],
                        scenario["result_files"][path],
                    )

    def test_generated_fixture_bytes_match_specs_exactly(self) -> None:
        for scenario in _CORPUS.SCENARIO_SPECS:
            with self.subTest(scenario=scenario["id"]):
                fixture = SCENARIOS / scenario["id"] / "fixture"
                actual_paths = {
                    path.relative_to(fixture).as_posix()
                    for path in fixture.rglob("*")
                    if path.is_file()
                }
                self.assertEqual(set(scenario["base_files"]), actual_paths)
                for path, content in scenario["base_files"].items():
                    self.assertEqual(
                        content.encode("utf-8"),
                        (fixture / path).read_bytes(),
                        path,
                    )

    def test_patch_packet_and_runtime_candidate_match_specs(self) -> None:
        for scenario in _CORPUS.SCENARIO_SPECS:
            with self.subTest(scenario=scenario["id"]):
                root = SCENARIOS / scenario["id"]
                expected_patch = _CORPUS.make_patch(
                    scenario["base_files"], scenario["result_files"]
                )
                self.assertEqual(
                    expected_patch,
                    (root / "patch.diff").read_text(encoding="utf-8"),
                )
                packet = _load_json(root / "packet.json")
                self.assertEqual(
                    [
                        {"argv": [program, *argv], "program": program}
                        for program, argv in scenario["commands"]
                    ],
                    packet["validation_plan"],
                )
                runtime = _load_json(root / "runtime.json")
                self.assertEqual(scenario["base_files"], runtime["workspace"]["base_files"])
                if runtime["candidate"] is not None:
                    self.assertEqual(
                        scenario["result_files"],
                        runtime["candidate"]["result_files"],
                    )

    def test_validation_evidence_binds_command_and_candidate_bytes(self) -> None:
        outputs: set[str] = set()
        for scenario in _CORPUS.SCENARIO_SPECS:
            with self.subTest(scenario=scenario["id"]):
                runtime = _load_json(SCENARIOS / scenario["id"] / "runtime.json")
                expected = [
                    _CORPUS.validation_evidence(scenario, index)
                    for index in range(len(scenario["commands"]))
                ]
                self.assertEqual(expected, runtime["validation_evidence"])

                completed = [
                    event["payload"]
                    for event in runtime["events"]
                    if event["kind"] == "tool_call_completed"
                    and event["payload"].get("tool_name") == "Bash"
                ]
                status = scenario["initial_state"] or (
                    "running"
                    if scenario["runtime_behavior"]
                    in {"timeout", "disconnect_after_dispatch"}
                    else "exited"
                )
                should_emit = (
                    bool(scenario["commands"])
                    and status == "exited"
                    and scenario["id"]
                    not in {
                        "s12-governance-file-mutation",
                        "s13-worker-out-of-scope",
                        "s14-tests-pass-unauthorized",
                        "s15-runtime-refusal-before-dispatch",
                    }
                    and scenario["runtime_behavior"] != "disconnect_after_dispatch"
                )
                self.assertEqual(1 if should_emit else 0, len(completed))
                for payload in completed:
                    evidence = payload["validation_evidence"]
                    self.assertEqual(expected[0], evidence)
                    rendered = _CORPUS.render_validation_evidence(evidence)
                    self.assertEqual(rendered, payload["stdout"])
                    self.assertIn(
                        _CORPUS.tree_digest(scenario["result_files"]), rendered
                    )
                    self.assertIn(
                        evidence["command"]["program"],
                        rendered,
                    )
                    outputs.add(rendered)

        # Every executed scenario carries its own command/candidate observation;
        # no generic shared success string is accepted as evidence.
        self.assertEqual(13, len(outputs))


if __name__ == "__main__":
    unittest.main()
