import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

HERE = Path(__file__).parents[1] / "qualification/synthetic_cache"
sys.path.insert(0, str(HERE))
try:
    SPEC = importlib.util.spec_from_file_location("run_connected_cache", HERE / "run_connected_cache.py")
    MODULE = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(MODULE)
finally:
    sys.path.pop(0)
PROCESS = sys.modules["connected_cache_process"]


def context(tmp_path):
    root = tmp_path / "run"
    root.mkdir()
    (root / "records").mkdir()
    fixed = tmp_path / "fixed"
    fixed.write_bytes(b"fixed")
    source = tmp_path / "maude"
    source.mkdir()
    value = {
        "schema": MODULE.CONTEXT_SCHEMA,
        "root": str(root),
        "programs": {name: {"path": str(fixed), "sha256": MODULE.file_digest(fixed)}
                     for name in ("nq", "docker")},
        "files": {"maude_source": {"path": str(source), "declared_revision": "revision"},
                  "pinned": {"path": str(fixed), "sha256": MODULE.file_digest(fixed)},
                  "nq_config": {"path": str(fixed), "sha256": MODULE.file_digest(fixed)}},
        "credentials": {},
        "identities": {"scope_digest": "sha256:" + "1" * 64,
                       "watcher_instance_id": "watcher"},
        "runtime": {"project": "example", "image": "example@sha256:" + "2" * 64},
        "nq": {"initialized": False},
        "governance": {"standing_kind": "synthetic_fixture"},
        "state": {"state_paths": {}},
    }
    path = tmp_path / "context.json"
    path.write_text(json.dumps(value))
    return path, value, fixed


def runner(tmp_path):
    path, value, fixed = context(tmp_path)
    run = MODULE.Run(path)
    run.records.mkdir(parents=True)
    return run, value, fixed


def test_call_refusal_is_single_attempt_with_terminal_stage_records(tmp_path, monkeypatch):
    run, _, _ = runner(tmp_path)
    calls = []

    def refuse(argv, **kwargs):
        calls.append(argv)
        kwargs["stdout_path"].write_bytes(b"")
        kwargs["stderr_path"].write_bytes(b"bounded refusal")
        return PROCESS.BoundedProcessResult(
            7, kwargs["stdout_path"], kwargs["stderr_path"], 0, 15, False, False
        )

    monkeypatch.setattr(MODULE, "run_bounded", refuse)
    with pytest.raises(ValueError, match="no automatic retry"):
        run.call("owner-stage", ["/program", "operation"])
    assert calls == [["/program", "operation"]]
    started = json.loads((run.records / "001-owner-stage.started.json").read_bytes())
    finished = json.loads((run.records / "001-owner-stage.finished.json").read_bytes())
    assert started["retries"] == 0 and finished["exit_code"] == 7


def test_timeout_is_uncertain_and_never_retried(tmp_path, monkeypatch):
    run, _, _ = runner(tmp_path)
    calls = 0

    def timeout(argv, **kwargs):
        nonlocal calls
        calls += 1
        kwargs["stdout_path"].write_bytes(b"partial")
        kwargs["stderr_path"].write_bytes(b"")
        result = PROCESS.BoundedProcessResult(
            -15, kwargs["stdout_path"], kwargs["stderr_path"], 7, 0, False, False
        )
        raise PROCESS.UncertainProcessTimeout("timeout", status="uncertain", result=result)

    monkeypatch.setattr(MODULE, "run_bounded", timeout)
    with pytest.raises(PROCESS.UncertainProcessTimeout):
        run.call("dispatch", ["/program", "dispatch"], timeout=3)
    assert calls == 1
    uncertain = json.loads((run.records / "001-dispatch.uncertain.json").read_bytes())
    assert "not attempt settlement" in uncertain["reason"]
    assert "inspect original owner state" in uncertain["next"]


def test_pin_change_refuses_before_owner_command(tmp_path):
    run, _, fixed = runner(tmp_path)
    run.check_pins()
    fixed.write_bytes(b"replacement")
    with pytest.raises(ValueError, match="bytes changed"):
        run.check_pins()


def test_source_drift_refuses_before_launch_or_stage_record(tmp_path, monkeypatch):
    run, _, fixed = runner(tmp_path)
    run.source_pins = {str(fixed): MODULE.file_digest(fixed)}
    fixed.write_bytes(b"source replacement")
    launched = []
    monkeypatch.setattr(MODULE, "run_bounded", lambda *args, **kwargs: launched.append(args))
    with pytest.raises(ValueError, match="source changed during this run"):
        run.call("owner-stage", ["/program", "operation"])
    assert launched == []
    assert not any(path.name.endswith("started.json") for path in run.records.iterdir())


def test_preflight_refuses_project_outside_fixed_compiler_contract(tmp_path, monkeypatch):
    run, _, _ = runner(tmp_path)
    monkeypatch.setenv("INVOCATION_ID", "fixture-invocation")
    with pytest.raises(ValueError, match="only project maude-cache-birthday"):
        run.preflight()


def test_preflight_refuses_declared_revision_mismatch_before_state(tmp_path, monkeypatch):
    path, value, _ = context(tmp_path)
    value["runtime"]["project"] = "maude-cache-birthday"
    value["files"]["maude_source"] = {"path": str(HERE.parents[1]),
                                        "declared_revision": "declared-revision"}
    path.write_text(json.dumps(value))
    run = MODULE.Run(path)
    calls = []

    def git(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout=b"actual-revision\n", stderr=b"")

    monkeypatch.setattr(MODULE.subprocess, "run", git)
    with pytest.raises(ValueError, match="actual Maude revision differs"):
        run.preflight()
    assert len(calls) == 1 and "rev-parse" in calls[0]
    assert not run.records.exists()


def test_construct_requires_actual_nq_scope_family(tmp_path):
    run, _, _ = runner(tmp_path)
    run.ids.update({
        "role_id": "role", "role_version": 1, "role_digest": "sha256:" + "2" * 64,
        "generation": "generation", "qualification_schedule_id": "schedule-q",
        "successor_schedule_id": "schedule-t", "qualification_attempt_id": "attempt-q",
        "successor_attempt_id": "attempt-t", "configuration_version": "config",
        "scheduler_clock_id": "clock",
    })
    (run.records / "diagnostic-q.json").write_text("{}")

    def helper(_name, *args, **_kwargs):
        output = Path(args[args.index("--cycle-request-out") + 1])
        output.write_text(json.dumps({"slot": {"scope_id": "sha256:" + "9" * 64},
                                      "observation_id": "sha256:" + "8" * 64}))

    run.helper = helper
    with pytest.raises(ValueError, match="observed NQ scope"):
        run.construct("q", 0)


class SequenceRun(MODULE.Run):
    def __init__(self, path, fail_at=None):
        super().__init__(path)
        self.events = []
        self.fail_at = fail_at

    def note(self, name, result=None):
        self.events.append(name)
        if self.fail_at == name:
            raise ValueError("deterministic refusal")
        return result

    def preflight(self): self.note("preflight")
    def project_absent(self, phase): self.note("absent-" + phase)
    def call(self, name, argv, **kwargs): return self.note(name, b"{}")
    def nq(self, name, *args, **kwargs): return self.note(name, b"{}")
    def helper(self, name, *args, **kwargs): return self.note(name)
    def construct(self, stage, occurrence): return self.note("construct-" + stage, "observation-" + stage)
    def compile(self, stage, initial, successor): return self.note("compile-" + stage, Path("/plan-" + stage))
    def proposal(self, stage, plan, action): return self.note("proposal-" + stage, Path("/proposal-" + stage))
    def seal(self, stage, plan, request): return self.note("seal-" + stage, Path("/authoring-" + stage))
    def pulse(self, stage): return self.note("pulse-" + stage, Path("/resolver-" + stage))
    def open_cycle(self, stage, *args): self.note("open-" + stage)
    def execute(self, stage, plan, action): return self.note("execute-" + stage, ("issuance", {}, Path("/inspection")))
    def successor(self, *args):
        return self.note("successor", {"qualification": {}, "teardown": {}})
    def write(self, name, value):
        self.events.append("write-" + name)
        return self.records / name


def test_full_top_level_stage_order_is_closed_and_refusal_stops_successor(tmp_path, monkeypatch):
    path, _, _ = context(tmp_path)
    monkeypatch.setenv("INVOCATION_ID", "fixture-invocation")
    run = SequenceRun(path)
    run.run()
    assert run.events == [
        "preflight", "write-checkpoint.json", "write-source-pins.json", "absent-initial", "image", "nq-init",
        "nq-test", "nq-admit", "cache-host-bootstrap.py", "construct-q", "compile-q",
        "proposal-q", "seal-q", "pulse-q", "open-q", "execute-q", "successor",
        "absent-final", "write-terminal.json",
    ]

    second = tmp_path / "second"
    second.mkdir()
    path, _, _ = context(second)
    refused = SequenceRun(path, fail_at="execute-q")
    with pytest.raises(ValueError, match="deterministic refusal"):
        refused.run()
    assert "successor" not in refused.events and "absent-final" not in refused.events
    assert refused.events[-1] == "write-terminal.json"


def test_post_teardown_pause_refuses_nonaccepted_mode_before_records(tmp_path, monkeypatch):
    path, _, _ = context(tmp_path)
    monkeypatch.setenv("INVOCATION_ID", "fixture-invocation")
    run = MODULE.Run(path, qualification_pause_after_teardown=True)
    monkeypatch.setattr(run, "check_pins", lambda: None)
    with pytest.raises(ValueError, match="only for accepted synthetic qualification"):
        run.run()
    assert not run.records.exists()


def test_post_teardown_pause_writes_exact_barrier_then_has_no_terminal(tmp_path, monkeypatch):
    path, _, _ = context(tmp_path)
    monkeypatch.setenv("INVOCATION_ID", "fixture-invocation")
    run = MODULE.Run(path, {"fixture": True}, True)
    run.records.mkdir(parents=True)
    run.sequence = 53
    refs = {
        "qualification": {"issuance": "issuance-q", "attempt": "attempt-q",
                          "settlement": "settlement-q", "outcome": "success"},
        "teardown": {"issuance": "issuance-t", "attempt": "attempt-t",
                     "settlement": "settlement-t", "outcome": "success"},
    }

    def supervisor_stop(_seconds):
        raise SystemExit("manager stopped")

    monkeypatch.setattr(MODULE.time, "sleep", supervisor_stop)
    with pytest.raises(SystemExit, match="manager stopped"):
        run.post_teardown_pause(refs)
    barrier = json.loads((run.records / "post-teardown-supervisor-pause.json").read_bytes())
    assert barrier["last_finished_stage"] == "053-inspect-t"
    assert barrier["settlements"] == refs
    assert barrier["expected_absent_records"] == [
        "054-final-containers.started.json", "055-final-networks.started.json", "terminal.json"]
    assert not (run.records / "terminal.json").exists()


def test_pause_settlement_reference_requires_exact_successful_owner_record():
    inspection = {"record": {"status": "settled", "indeterminate": None,
        "issuance": {"issuance": "issuance"}, "custody": {"attempt": "attempt"},
        "settlement": {"issuance": "issuance", "settlement": "settlement",
                       "outcome": "success"}}}
    assert MODULE.Run.settlement_reference("issuance", inspection) == {
        "issuance": "issuance", "attempt": "attempt",
        "settlement": "settlement", "outcome": "success"}
    inspection["record"]["settlement"]["outcome"] = "failure"
    with pytest.raises(ValueError, match="exact successful settlements"):
        MODULE.Run.settlement_reference("issuance", inspection)


@pytest.mark.parametrize("relative,arguments", [
    ("helpers/cache-host-bootstrap.py", ["acquire", "--nq", "/missing/nq", "--nq-config", "/missing/nq.toml",
      "--instance", "watcher", "--artifact-out", "/missing/artifact", "--provenance-out", "/missing/provenance"]),
    ("helpers/cache-host-bootstrap.py", ["construct", "--artifact", "/missing/artifact", "--role-id", "role",
      "--role-version", "1", "--role-digest", "sha256:" + "1" * 64, "--generation", "generation",
      "--schedule-id", "schedule", "--attempt-id", "attempt", "--configuration-version", "config",
      "--scheduler-clock-id", "clock", "--occurrence", "0", "--cycle-request-out", "/missing/request"]),
    ("helpers/cache-host-bootstrap.py", ["support", "--pulse", "/missing/pulse", "--pulse-config",
      "/missing/pulse.json", "--acquisition-id", "acquisition"]),
    ("helpers/cache-successor-compose-request.py", ["--posture-request", "/missing/request",
      "--precompiled-proposal", "/missing/proposal", "--output", "/missing/output"]),
    ("helpers/cache-successor-attach-external.py", ["--request", "/missing/request", "--acquisition",
      "/missing/acquisition", "--profile", "/missing/profile", "--output", "/missing/output"]),
    ("helpers/cache-successor-result-config.py", ["--docket-inspection", "/missing/inspection",
      "--executor-plan", "/missing/plan", "--docket-database", "/missing/docket.sqlite",
      "--nq-database", "/missing/nq.sqlite", "--nq-socket", "/missing/nq.sock",
      "--admissions-dir", "/missing/admissions", "--helper-runtime-dir", "/missing/helpers",
      "--helper", "/missing/nq-result", "--helper-working-directory", "/missing/work",
      "--execution-account", "fixture", "--output", "/missing/output"]),
    ("helpers/prepare-cache-external-successor.py", ["--docket-inspection", "/missing/inspection",
      "--executor-evidence", "/missing/evidence", "--executor-plan", "/missing/plan",
      "--compilation-receipt", "/missing/receipt", "--lineage-export", "/missing/lineage",
      "--custody-export", "/missing/custody", "--output", "/missing/output",
      "--target-runtime-id", "runtime", "--producer-principal-id", "observer",
      "--producer-key-id", "observer-key", "--maude-producer-principal-id", "maude-producer",
      "--maude-producer-key-id", "maude-producer-key",
      "--maude-session-issuer-principal-id", "maude-session",
      "--maude-session-issuer-key-id", "maude-session-key"]),
    ("seal_cycle_handoff.py", ["--store", "/missing/store", "--session-key", "/missing/session",
      "--producer-key", "/missing/producer", "--plan", "/missing/plan", "--base-request",
      "/missing/request", "--output", "/missing/output", "--session-id", "session", "--runtime-id", "runtime"]),
    ("prepare_pulse_support.py", ["--artifact", "/missing/artifact", "--posture-request", "/missing/request",
      "--output", "/missing/output", "--pulse", "/missing/pulse", "--python", sys.executable,
      "--openssl", "/missing/openssl", "--sealer", "/missing/sealer", "--pulse-sha256", "sha256:" + "1" * 64,
      "--python-sha256", "sha256:" + "2" * 64, "--openssl-sha256", "sha256:" + "3" * 64,
      "--sealer-sha256", "sha256:" + "4" * 64, "--authority-id", "authority", "--producer-id", "producer"]),
])
def test_runner_helper_command_shapes_pass_actual_argparse(relative, arguments):
    completed = subprocess.run(
        [sys.executable, str(HERE / relative), *arguments],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5, check=False,
    )
    error = completed.stderr.decode("utf-8", "replace")
    assert completed.returncode != 0
    assert "unrecognized arguments" not in error
    assert "the following arguments are required" not in error


@pytest.mark.parametrize("arguments", [
    ["--accepted-bundle", "/bundle"],
    ["--accepted-bundle", "/bundle", "--accepted-bundle-sha256", "1" * 64],
    ["--accepted-store", "/store", "--accepted-store-sha256", "2" * 64],
])
def test_accepted_cli_is_all_or_none_before_run(arguments, monkeypatch, tmp_path):
    launched = []
    monkeypatch.setattr(MODULE, "Run", lambda *args: launched.append(args))
    monkeypatch.setattr(sys, "argv", ["run_connected_cache.py", "--context", str(tmp_path / "c"),
                                      "--execute", *arguments])
    with pytest.raises(SystemExit) as error:
        MODULE.main()
    assert error.value.code == 2
    assert launched == []


def test_accepted_cli_passes_exact_closed_coordinates(monkeypatch, tmp_path):
    observed = []

    class FakeRun:
        def __init__(self, context_path, accepted, qualification_pause_after_teardown):
            observed.append((context_path, accepted, qualification_pause_after_teardown))

        def run(self):
            observed.append("run")

    monkeypatch.setattr(MODULE, "Run", FakeRun)
    monkeypatch.setattr(sys, "argv", ["run_connected_cache.py", "--context", str(tmp_path / "c"),
        "--execute", "--accepted-bundle", str(tmp_path / "bundle"),
        "--accepted-bundle-sha256", "1" * 64, "--accepted-store", str(tmp_path / "store"),
        "--accepted-store-sha256", "2" * 64])
    MODULE.main()
    assert observed == [(tmp_path / "c", {
        "bundle": tmp_path / "bundle", "bundle_sha256": "1" * 64,
        "store": tmp_path / "store", "store_sha256": "2" * 64,
    }, False), "run"]


def test_pause_cli_passes_explicit_qualification_mode(monkeypatch, tmp_path):
    observed = []

    class FakeRun:
        def __init__(self, _context, _accepted, pause): observed.append(pause)
        def run(self): observed.append("run")

    monkeypatch.setattr(MODULE, "Run", FakeRun)
    monkeypatch.setattr(sys, "argv", ["run_connected_cache.py", "--context", str(tmp_path / "c"),
        "--execute", "--accepted-bundle", str(tmp_path / "bundle"),
        "--accepted-bundle-sha256", "1" * 64, "--accepted-store", str(tmp_path / "store"),
        "--accepted-store-sha256", "2" * 64, "--qualification-pause-after-teardown"])
    MODULE.main()
    assert observed == [True, "run"]


@pytest.mark.parametrize("failure", ["pin", "sidecar"])
def test_accepted_input_refusal_precedes_nq(tmp_path, monkeypatch, failure):
    path, _, _ = context(tmp_path)
    bundle = tmp_path / "accepted.json"
    store = tmp_path / "accepted.sqlite"
    bundle.write_bytes(b"bundle")
    store.write_bytes(b"store")
    accepted = {"bundle": bundle, "bundle_sha256": MODULE.file_digest(bundle),
                "store": store, "store_sha256": MODULE.file_digest(store)}
    if failure == "pin":
        accepted["bundle_sha256"] = "0" * 64
        match = "explicit pin"
    else:
        Path(str(store) + "-wal").write_bytes(b"sidecar")
        match = "writable sidecars"
    run = MODULE.Run(path, accepted)
    monkeypatch.setattr(run, "check_pins", lambda: None)
    nq_calls = []
    monkeypatch.setattr(run, "nq", lambda *args, **kwargs: nq_calls.append(args))
    with pytest.raises(ValueError, match=match):
        run.run()
    assert nq_calls == []
    assert not run.records.exists()


@pytest.mark.parametrize("failure", ["relative", "malformed-pin"])
def test_accepted_coordinate_shape_refuses_before_nq(tmp_path, monkeypatch, failure):
    path, _, _ = context(tmp_path)
    bundle = tmp_path / "accepted.json"
    store = tmp_path / "accepted.sqlite"
    bundle.write_bytes(b"bundle")
    store.write_bytes(b"store")
    accepted = {"bundle": bundle, "bundle_sha256": MODULE.file_digest(bundle),
                "store": store, "store_sha256": MODULE.file_digest(store)}
    if failure == "relative":
        accepted["bundle"] = Path("accepted.json")
    else:
        accepted["store_sha256"] = "A" * 64
    run = MODULE.Run(path, accepted)
    monkeypatch.setattr(run, "check_pins", lambda: None)
    nq_calls = []
    monkeypatch.setattr(run, "nq", lambda *args, **kwargs: nq_calls.append(args))
    with pytest.raises(ValueError, match="absolute paths and lowercase SHA-256"):
        run.run()
    assert nq_calls == []
    assert not run.records.exists()


def test_accepted_actions_reuse_locked_plan_and_use_action_specific_inputs(tmp_path):
    path, value, _ = context(tmp_path)
    compiler_source = Path(value["files"]["maude_source"]["path"]) / "src/maude/plan/local_compose.py"
    compiler_source.parent.mkdir(parents=True)
    compiler_source.write_bytes(b"compiler source")
    bundle = tmp_path / "accepted.json"
    store = tmp_path / "accepted.sqlite"
    bundle.write_bytes(b'{"accepted":"opaque"}')
    store.write_bytes(b"retained-store")
    accepted = {"bundle": bundle, "bundle_sha256": MODULE.file_digest(bundle),
                "store": store, "store_sha256": MODULE.file_digest(store)}
    run = MODULE.Run(path, accepted)
    run.c["programs"]["python"] = {"path": sys.executable}
    run.records.mkdir(parents=True)
    (run.records / "diagnostic-q.json").write_bytes(b'{"stage":"q"}')
    (run.records / "diagnostic-t.json").write_bytes(b'{"stage":"t"}')
    calls = []
    locked = b'{"same":"accepted-plan"}'

    def call(name, argv, **_kwargs):
        calls.append((name, [str(value) for value in argv]))
        output = Path(argv[argv.index("--output") + 1])
        if name.startswith("prepare-accepted-"):
            action = argv[2]
            output.mkdir()
            (output / "accepted-plan.sqlite").write_bytes(store.read_bytes())
            (output / "accepted-bundle.json").write_bytes(bundle.read_bytes())
            (output / f"compiler-input-{action}.json").write_bytes(action.encode())
            (output / "plan-locked.json").write_bytes(locked)
        else:
            output.mkdir()
            (output / "plan-locked.json").write_bytes(locked)
        return b""

    run.call = call
    qualify = run.compile_accepted("q", tmp_path / "plan-q")
    teardown = run.compile_accepted("t", tmp_path / "plan-t")
    assert (qualify / "plan-locked.json").read_bytes() == (teardown / "plan-locked.json").read_bytes() == locked
    prepare_q, compile_q, prepare_t, compile_t = calls
    assert prepare_q[0] == "prepare-accepted-q" and prepare_q[1][2] == "qualify"
    assert prepare_t[0] == "prepare-accepted-t" and prepare_t[1][2] == "teardown"
    assert prepare_q[1][prepare_q[1].index("--accepted-store") + 1] == str(store)
    assert prepare_t[1][prepare_t[1].index("--accepted-store") + 1] == str(store)
    assert compile_q[1][compile_q[1].index("--compiler-input") + 1].endswith("compiler-input-qualify.json")
    assert compile_t[1][compile_t[1].index("--compiler-input") + 1].endswith("compiler-input-teardown.json")
