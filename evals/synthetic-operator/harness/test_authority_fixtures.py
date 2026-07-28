#!/usr/bin/env python3
"""Mechanical seam-B checks for the frozen synthetic operator corpus.

Stdlib-only by design.  The campaign must be reproducible without importing a
mutable Agent Governor sibling checkout.  The independent vectors here pin the
contract audited at Agent Governor commit
485e55783f9e359965e3b736e1d610c4568d45f1.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import synthetic_runtime


HERE = Path(__file__).resolve().parent
SCENARIOS = HERE.parent / "scenarios"
AG_COMMIT = "485e55783f9e359965e3b736e1d610c4568d45f1"
SHA256_PREFIX = "sha256:"


def sha256_ref(data: bytes) -> str:
    return SHA256_PREFIX + hashlib.sha256(data).hexdigest()


def reference_witness(plan_bytes: bytes, decision: str = "approve") -> bytes:
    """Independent copy of AG 485e557 approval-witness/v1 serialization."""
    return json.dumps(
        {
            "witness_version": "approval-witness/v1",
            "decision": decision,
            "plan_ref": sha256_ref(plan_bytes),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def reference_grant_identity(request: dict) -> tuple[str, str]:
    """Independent copy of AG 485e557 execution-grant/v1 identity."""
    commands = sorted(
        [
            {
                "program": str(command["program"]),
                "argv_prefix": [
                    str(argument) for argument in command.get("argv_prefix", [])
                ],
            }
            for command in request["commands"]
        ],
        key=lambda command: (command["program"], tuple(command["argv_prefix"])),
    )
    body = {
        "derivation_version": "execution-grant/v1",
        "source_plan_digest": request["source_plan_digest"],
        "approval_witness_digest": request["approval_witness_digest"],
        "horizon": request.get("horizon", "run"),
        "enforcement": "declared-effects-only",
        "write_paths": sorted(set(request["write_paths"])),
        "commands": commands,
        "network": "denied",
        "git": "denied",
        "secrets": "denied",
        "privilege": "denied",
    }
    encoded = json.dumps(
        body,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    digest_hex = hashlib.sha256(encoded).hexdigest()
    return f"sgr_{digest_hex[:12]}", f"sha256:{digest_hex}"


class ApprovalBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plan = b"# exact plan bytes\nplan_version: 1\n"
        self.witness = reference_witness(self.plan)
        self.plan_ref = sha256_ref(self.plan)
        self.witness_digest = sha256_ref(self.witness)

    def verify(self, **overrides: object) -> tuple[str, str]:
        arguments = {
            "plan_bytes": self.plan,
            "witness_bytes": self.witness,
            "source_plan_digest": self.plan_ref,
            "approval_witness_digest": self.witness_digest,
        }
        arguments.update(overrides)
        return synthetic_runtime._verify_approval_binding(**arguments)

    def test_valid_exact_bytes_round_trip(self) -> None:
        self.assertEqual(self.verify(), (self.plan_ref, self.witness_digest))

    def test_absent_evidence_refuses(self) -> None:
        for field, value in (("plan_bytes", None), ("witness_bytes", None)):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.verify(**{field: value})

    def test_malformed_witness_refuses(self) -> None:
        malformed = b"{not-json"
        with self.assertRaises(ValueError):
            self.verify(
                witness_bytes=malformed,
                approval_witness_digest=sha256_ref(malformed),
            )

    def test_missing_or_unknown_witness_fields_refuse(self) -> None:
        invalid_objects = (
            {"decision": "approve", "plan_ref": self.plan_ref},
            {
                "witness_version": "approval-witness/future",
                "decision": "approve",
                "plan_ref": self.plan_ref,
            },
        )
        for witness_object in invalid_objects:
            with self.subTest(witness=witness_object):
                encoded = json.dumps(
                    witness_object, sort_keys=True, separators=(",", ":")
                ).encode("utf-8")
                with self.assertRaises(ValueError):
                    self.verify(
                        witness_bytes=encoded,
                        approval_witness_digest=sha256_ref(encoded),
                    )

    def test_deny_witness_refuses(self) -> None:
        denied = reference_witness(self.plan, decision="deny")
        with self.assertRaises(ValueError):
            self.verify(
                witness_bytes=denied,
                approval_witness_digest=sha256_ref(denied),
            )

    def test_mismatched_plan_bytes_refuse(self) -> None:
        with self.assertRaises(ValueError):
            self.verify(plan_bytes=self.plan + b"changed")

    def test_mismatched_witness_digest_refuses(self) -> None:
        with self.assertRaises(ValueError):
            self.verify(approval_witness_digest=SHA256_PREFIX + "0" * 64)


class GrantDerivationTests(unittest.TestCase):
    def test_pinned_agent_governor_vector(self) -> None:
        request = {
            "write_paths": ["z/**", "a.txt"],
            "commands": [
                {"program": "cargo", "argv_prefix": ["test"]},
                {"program": "git", "argv_prefix": ["diff", "--check"]},
            ],
            "source_plan_digest": SHA256_PREFIX + "a" * 64,
            "approval_witness_digest": SHA256_PREFIX + "b" * 64,
            "horizon": "run",
        }
        derived = synthetic_runtime._derive_execution_grant(request)
        self.assertEqual(derived["grant_id"], "sgr_8ad1b793ecb0")
        self.assertEqual(
            derived["grant_digest"],
            "sha256:8ad1b793ecb014994c9925f8411eb1b5b17adcc318cae26eae5cdd195b40a32a",
        )

    def test_derivation_is_order_independent(self) -> None:
        request = {
            "write_paths": ["z/**", "a.txt", "z/**"],
            "commands": [
                {"program": "git", "argv_prefix": ["diff", "--check"]},
                {"program": "cargo", "argv_prefix": ["test"]},
            ],
            "source_plan_digest": SHA256_PREFIX + "a" * 64,
            "approval_witness_digest": SHA256_PREFIX + "b" * 64,
            "horizon": "run",
        }
        expected = reference_grant_identity(request)
        derived = synthetic_runtime._derive_execution_grant(request)
        self.assertEqual(
            (derived["grant_id"], derived["grant_digest"]),
            expected,
        )


class SyntheticActivationTests(unittest.TestCase):
    def test_rpc_dispatch_rechecks_bytes_and_attaches_derived_grant(self) -> None:
        scenario = SCENARIOS / "s01-kubernetes-image-update"
        config = json.loads((scenario / "runtime.json").read_text(encoding="utf-8"))
        plan_text = (scenario / "plan.md").read_text(encoding="utf-8")
        witness_text = next(scenario.glob("lab_approval_*")).read_text(
            encoding="utf-8"
        )
        configured = config["grant"]
        request = {
            field: configured[field]
            for field in (
                "write_paths",
                "commands",
                "source_plan_digest",
                "approval_witness_digest",
                "horizon",
            )
        }

        async def exercise(temp: Path) -> None:
            config["workspace"]["path"] = str(temp / "workspace")
            runtime = synthetic_runtime.SyntheticRuntime(
                config,
                synthetic_runtime.RuntimePaths(
                    config=scenario / "runtime.json",
                    socket=temp / "runtime.sock",
                    state_dir=temp / "state",
                    trace=temp / "trace.jsonl",
                ),
            )
            created = await runtime.dispatch(
                "runtime.session.create",
                {
                    "backend_kind": "claude_code",
                    "cwd": str(temp / "workspace"),
                    "task": "authority contract test",
                },
            )
            params = {
                "session_id": created["session_id"],
                "execution_request": request,
                "plan_bytes": plan_text,
                "witness_bytes": witness_text,
            }
            activated = await runtime.dispatch("runtime.grant.activate", params)
            self.assertEqual(
                activated["grant_digest"], configured["grant_digest"]
            )
            self.assertTrue(activated["plan_binding_verified"])
            attached = await runtime.dispatch(
                "runtime.grant.get", {"session_id": created["session_id"]}
            )
            self.assertEqual(attached["grant_id"], configured["grant_id"])

            with self.assertRaises(ValueError):
                await runtime.dispatch(
                    "runtime.grant.activate",
                    {**params, "plan_bytes": plan_text + "\nmutated"},
                )

        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(exercise(Path(directory)))


class CorpusCrossCheckTests(unittest.TestCase):
    def test_all_operational_authority_fixtures_cross_check(self) -> None:
        runtime_paths = sorted(SCENARIOS.glob("s*/runtime.json"))
        self.assertEqual(len(runtime_paths), 20)
        for runtime_path in runtime_paths:
            scenario = runtime_path.parent
            runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
            with self.subTest(scenario=runtime["scenario_id"]):
                self.assertEqual(
                    runtime["authority_contract"]["agent_gov_commit"], AG_COMMIT
                )
                self.assertEqual(
                    runtime["authority_contract"]["approval_witness_version"],
                    "approval-witness/v1",
                )
                self.assertEqual(
                    runtime["authority_contract"][
                        "execution_grant_derivation_version"
                    ],
                    "execution-grant/v1",
                )

                plan_bytes = (scenario / "plan.md").read_bytes()
                witnesses = sorted(scenario.glob("lab_approval_*"))
                grant = runtime["grant"]
                if runtime["scenario_id"] == "s14-tests-pass-unauthorized":
                    self.assertEqual(witnesses, [])
                    self.assertIsNone(runtime["approval_binding"])
                    self.assertIn(b"governance_status: candidate", plan_bytes)
                    self.assertNotIn(b"approval_ref:", plan_bytes)
                    for authority_field in (
                        "grant_id",
                        "grant_digest",
                        "source_plan_digest",
                        "approval_witness_digest",
                    ):
                        self.assertNotIn(authority_field, grant)
                    self.assertEqual(grant["kind"], "absent")
                    continue

                self.assertEqual(len(witnesses), 1)
                expected_witness = reference_witness(plan_bytes)
                witness_bytes = witnesses[0].read_bytes()
                self.assertEqual(witness_bytes, expected_witness)
                witness_digest = sha256_ref(witness_bytes)
                plan_ref = sha256_ref(plan_bytes)
                witness = json.loads(witness_bytes.decode("utf-8"))
                self.assertEqual(witness["plan_ref"], plan_ref)
                self.assertEqual(
                    runtime["approval_binding"],
                    {
                        "source_plan_digest": plan_ref,
                        "approval_witness_digest": witness_digest,
                    },
                )

                if runtime["scenario_id"] == "s12-governance-file-mutation":
                    self.assertEqual(grant["kind"], "absent")
                    self.assertNotIn("grant_id", grant)
                    self.assertNotIn("grant_digest", grant)
                    continue

                request = {
                    "write_paths": grant["write_paths"],
                    "commands": grant["commands"],
                    "source_plan_digest": plan_ref,
                    "approval_witness_digest": witness_digest,
                    "horizon": grant["horizon"],
                }
                self.assertEqual(grant["source_plan_digest"], plan_ref)
                self.assertEqual(
                    grant["approval_witness_digest"], witness_digest
                )
                self.assertEqual(
                    (grant["grant_id"], grant["grant_digest"]),
                    reference_grant_identity(request),
                )
                self.assertNotEqual(grant["grant_digest"], SHA256_PREFIX + "0" * 64)
                synthetic_runtime._validate_configured_grant(
                    grant,
                    synthetic_runtime._derive_execution_grant(request),
                )


if __name__ == "__main__":
    unittest.main()
