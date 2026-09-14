import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


HERE = Path(__file__).parents[1] / "qualification/synthetic_cache/helpers"


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PREPARE = load_module("cache_external_successor", "prepare-cache-external-successor.py")
RESULT = load_module("cache_successor_result", "cache-successor-result-config.py")
ATTACH = load_module("cache_successor_attach", "cache-successor-attach-external.py")


def write_json(path, value):
    path.write_text(json.dumps(value))
    return path


class TestExternalSuccessorPreparation(unittest.TestCase):
    def test_currentness_boundary_is_inclusive_then_refuses(self):
        observed = 1_000_000
        boundary = observed + PREPARE.HORIZON_MS - PREPARE.MIN_START_MARGIN_MS
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            inputs = self._inputs(root, observed)
            self._run(inputs, root / "at-boundary", boundary)
            recipe = json.loads((root / "at-boundary/recipe.json").read_text())
            self.assertTrue(recipe["launch_admissible"])
            self.assertEqual(recipe["successor_commands"][1][recipe["successor_commands"][1].index("--nq-config") + 1], "@ADMITTED_NQ_CONFIG")
            self.assertIn("same_owner_nq_local_successor_and_pulse", recipe["required_order"])
            self._run(inputs, root / "after-boundary", boundary + 1)
            self.assertFalse(json.loads((root / "after-boundary/recipe.json").read_text())["launch_admissible"])

    def test_malformed_matches_member_refuses_cleanly(self):
        with tempfile.TemporaryDirectory() as td:
            path = write_json(Path(td) / "lineage.json", {"matches": [None]})
            with self.assertRaises(ValueError):
                PREPARE.one_match(PREPARE.read_object(path), "nightshift.authoring_context_provenance.v1")

    def test_duplicate_distinct_records_refuse(self):
        value = {"records": [
            {"schema": "nightshift.authoring_context_provenance.v1", "proposal_id": "a"},
            {"schema": "nightshift.authoring_context_provenance.v1", "proposal_id": "b"},
        ]}
        with self.assertRaisesRegex(ValueError, "one distinct"):
            PREPARE.one_match(value, "nightshift.authoring_context_provenance.v1")

    def _inputs(self, root, observed):
        d = lambda name, value: write_json(root / name, value)
        work = "sha256:" + "1" * 64
        proposal = "sha256:" + "2" * 64
        occurrence = "occurrence-1"
        attempt = "sha256:" + "3" * 64
        receipt = d("compilation.json", {
            "exact_work_identity": work, "plan_digest": "plan-1", "draft_id": "draft-1",
            "compilation_id": "compile-1", "node_bindings": [{"node_id": "n1", "output_identity": "out-1"}],
        })
        return dict(
            docket_inspection=d("docket.json", {"schema": "docket.governed-loop.inspection/v1", "requested_issuance": "issue-1", "record": {
                "status": "settled", "issuance": {"key": {"campaign": "campaign-1", "occurrence": occurrence}, "proposal": proposal, "work": work, "issuance": "issue-1"},
                "custody": {"attempt": attempt}, "settlement": {"attempt": attempt, "settlement": "settle-1", "outcome": "success"},
            }}),
            executor_evidence=d("evidence.json", {"outcome": "success", "observed_at_unix_ms": observed, "dispatch": {"attempt": attempt, "work": work}}),
            executor_plan=d("plan.json", {"plan_document_digest": "plan-1"}),
            compilation_receipt=receipt,
            lineage_export=d("lineage.json", {"matches": [{"schema": "nightshift.authoring_context_provenance.v1", "proposal_id": proposal, "occurrence_id": occurrence, "exact_work_id": work, "maude_plan_ref": "plan-1", "provenance_id": "prov-1"}]}),
            custody_export=d("custody.json", {"matches": [{"schema": "nightshift.authoring_context_custody_provenance.v1", "proposal_id": proposal, "occurrence_id": occurrence, "exact_work_id": work, "handoff_id": "handoff-1"}]}),
        )

    def _run(self, inputs, output, evaluated):
        original = PREPARE.arguments
        PREPARE.arguments = lambda: SimpleNamespace(
            **inputs, output=output, target_runtime_id="runtime-1",
            producer_principal_id="principal-1", producer_key_id="key-1",
            maude_producer_principal_id="maude-principal",
            maude_producer_key_id="maude-key",
            maude_session_issuer_principal_id="session-principal",
            maude_session_issuer_key_id="session-key",
            evaluated_at_unix_ms=evaluated,
        )
        try:
            PREPARE.main()
        finally:
            PREPARE.arguments = original


class TestResultConfig(unittest.TestCase):
    def test_receipt_mismatch_refuses_before_output(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            args = self._args(root, evidence_receipt="sha256:" + "9" * 64)
            with self.assertRaisesRegex(ValueError, "bind Docket attempt/receipt"):
                RESULT.main(args)
            self.assertFalse(args.output.exists())

    def test_missing_required_directory_refuses_before_output(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            args = self._args(root)
            args.admissions_dir = root / "missing-admissions"
            with self.assertRaisesRegex(ValueError, "required result directory unavailable"):
                RESULT.main(args)
            self.assertFalse(args.output.exists())

    def test_valid_exact_paths_and_receipt_create_private_config(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            args = self._args(root)
            RESULT.main(args)
            self.assertEqual(args.output.stat().st_mode & 0o777, 0o600)
            text = args.output.read_text()
            self.assertIn(str(args.docket_database), text)
            self.assertIn("allow_same_identity_in_debug = true", text)

    def _args(self, root, evidence_receipt=None):
        digest = lambda c: "sha256:" + c * 64
        attempt, marker, receipt = digest("a"), digest("b"), digest("c")
        work, subject, scope, program, settlement = (digest(c) for c in "defgh")
        workspace = root / "workspace"
        record_dir = workspace / "evidence/attempts"
        record_dir.mkdir(parents=True)
        write_json(record_dir / (attempt.removeprefix("sha256:") + ".json"), {"dispatch": {"attempt": attempt}, "docket_outcome": {"receipt": evidence_receipt or receipt}})
        inspection = write_json(root / "inspection.json", {"schema": "docket.governed-loop.inspection/v1", "record": {
            "status": "settled", "executor_plan": work, "executor_program_digest": program,
            "issuance": {"work_schema": "maude.local-compose-workflow/v1", "work": work, "subject": subject, "scope": scope},
            "custody": {"attempt": attempt, "executor_marker": marker},
            "settlement": {"outcome": "success", "attempt": attempt, "executor_marker": marker, "settlement": settlement, "receipt": receipt},
        }})
        plan = write_json(root / "plan.json", {"workspace": str(workspace)})
        helper = root / "nq-synthetic-cache-result-helper"
        helper.write_text("fixture")
        dirs = [root / name for name in ("nq", "sock", "admissions", "runtime", "working")]
        for path in dirs:
            path.mkdir()
        return SimpleNamespace(docket_inspection=inspection, executor_plan=plan, docket_database=root / "docket.db", nq_database=dirs[0] / "nq.db", nq_socket=dirs[1] / "nq.sock", admissions_dir=dirs[2], helper_runtime_dir=dirs[3], helper=helper, helper_working_directory=dirs[4], output=root / "result.toml", execution_account="fixture", allow_same_identity_in_debug=True)


class TestSuccessorAttachment(unittest.TestCase):
    def test_attaches_only_accepted_custody_and_refuses_replacement(self):
        digest = lambda value: "sha256:" + value * 64
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            request = {"schema": "nightshift.canonical_cycle_request.v1",
                       "request_id": digest("1"), "proposal": {"mode": {"continuation": {}}},
                       "external_evidence": None, "decision_external_evidence": None}
            acquisition = {"schema": "maude.external-evidence-acquisition-export/v1",
                           "events": [{"kind": "custody_accepted", "custody_id": digest("2")}],
                           "evidence": {"handoff": {"observation": {"observation_id": digest("3")}}}}
            profile = {"profile_id": digest("4")}
            args = SimpleNamespace(
                request=write_json(root / "request.json", request),
                acquisition=write_json(root / "acquisition.json", acquisition),
                profile=write_json(root / "profile.json", profile),
                output=root / "attached.json",
            )
            ATTACH.main(args)
            attached = json.loads(args.output.read_bytes())
            self.assertEqual(attached["external_evidence"]["source_custody_id"], digest("2"))
            second = SimpleNamespace(**{**vars(args), "request": args.output,
                                        "output": root / "second.json"})
            with self.assertRaisesRegex(ValueError, "without external evidence"):
                ATTACH.main(second)


if __name__ == "__main__":
    unittest.main()
