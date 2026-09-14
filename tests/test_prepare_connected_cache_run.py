import importlib.util
import json
from pathlib import Path

import pytest

SOURCE = Path(__file__).parents[1] / "qualification/synthetic_cache/prepare_connected_cache_run.py"
SPEC = importlib.util.spec_from_file_location("prepare_connected_cache_run", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def minimal_config(tmp_path):
    program = tmp_path / "program"
    program.write_text("#!/bin/sh\nexit 0\n")
    program.chmod(0o700)
    pin = MODULE.file_digest(program)
    source = tmp_path / "maude"
    utilities = source / "qualification/synthetic_cache"
    utilities.mkdir(parents=True)
    (utilities / "build_plan.py").write_text("build")
    (utilities / "local_compose_executor.py").write_text("executor")
    digest = lambda value: "sha256:" + value * 64
    return {
        "schema": MODULE.SCHEMA, "root": str(tmp_path / "run"),
        "programs": {name: {"path": str(program), "sha256": pin} for name in MODULE.PROGRAMS},
        "files": {"pulse_launcher_sealer": {"path": str(program), "sha256": pin}},
        "maude": {"source": str(source), "source_revision": "revision",
                  "build_plan_sha256": MODULE.file_digest(utilities / "build_plan.py"),
                  "executor_sha256": MODULE.file_digest(utilities / "local_compose_executor.py")},
        "identities": {
            "campaign_id": digest("a"), "program_id": digest("b"),
            "subject_digest": digest("c"), "scope_digest": digest("d"),
            "qualification_occurrence_id": "10000000-0000-4000-8000-000000000001",
            "successor_occurrence_id": "10000000-0000-4000-8000-000000000002",
            "watcher_instance_id": "public-cache-host", "local_successor_acquisition_id": "acquisition:successor",
            "runtime_id": "nightshift:public-cache", "generation": "generation:public-cache",
            "configuration_version": "configuration:public-cache",
            "role_id": "nightshift-role:cache-bootstrap-host", "role_version": 1,
            "role_digest": digest("e"), "qualification_schedule_id": "schedule:qualification",
            "successor_schedule_id": "schedule:successor",
            "qualification_attempt_id": "attempt:qualification",
            "successor_attempt_id": "attempt:successor", "scheduler_clock_id": "clock:realtime",
            "qualification_pulse_acquisition_id": "acquisition:pulse-qualification",
            "successor_pulse_acquisition_id": "acquisition:pulse-successor",
        },
        "nq": {"execution_account": "fixture", "subject": "host:host-scope", "scope_id": "host-scope",
               "working_directory": str(tmp_path), "allow_same_identity_in_debug": True},
        "runtime": {"image": "example.invalid/image@sha256:" + "e" * 64,
                    "docker_client_version": "1", "docker_server_version": "1",
                    "compose_version": "1", "project": "public-cache", "front_port": 8080},
        "governance": {"profile_label": "synthetic-cache-fixture",
                       "observation_resolver_id": "nightshift-observation-resolver/v1",
                       "standing_resolver_id": "ag-standing-resolver/integration-v1",
                       "issuer_principal": "synthetic-cache-ag", "issuer_key_id": "fixture-key-1",
                       "observation_ttl_ms": 120000, "standing_ttl_ms": 60000,
                       "docket_standing_ttl_ms": 60000},
    }


def test_missing_program_refuses_before_root_allocation(tmp_path):
    config = minimal_config(tmp_path)
    del config["programs"]["pulse"]
    with pytest.raises(ValueError, match="closed program"):
        MODULE.prepare(config)
    assert not Path(config["root"]).exists()


def test_reused_occurrence_or_boolean_port_refuses_before_root_allocation(tmp_path):
    second = tmp_path / "second"
    second.mkdir()
    config = minimal_config(second)
    config["identities"]["successor_occurrence_id"] = config["identities"]["qualification_occurrence_id"]
    with pytest.raises(ValueError, match="must differ"):
        MODULE.prepare(config)
    assert not Path(config["root"]).exists()
    config = minimal_config(tmp_path)
    config["runtime"]["front_port"] = True
    with pytest.raises(ValueError, match="runtime enrollment"):
        MODULE.prepare(config)
    assert not Path(config["root"]).exists()


def test_program_pin_mismatch_refuses_before_root_allocation(tmp_path):
    config = minimal_config(tmp_path)
    config["programs"]["nq"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="program nq bytes"):
        MODULE.prepare(config)
    assert not Path(config["root"]).exists()


def test_nq_host_subject_scope_mismatch_refuses_before_root_allocation(tmp_path):
    config = minimal_config(tmp_path)
    config["nq"]["subject"] = "host:another-scope"
    with pytest.raises(ValueError, match="do not correlate"):
        MODULE.prepare(config)
    assert not Path(config["root"]).exists()


def test_owned_nq_working_directory_is_created_before_bootstrap(tmp_path, monkeypatch):
    config = minimal_config(tmp_path)
    root = Path(config["root"])
    config["nq"]["working_directory"] = str(root / "nq-work")
    monkeypatch.setattr(MODULE, "expected_host_scope_digest",
                        lambda *unused: config["identities"]["scope_digest"])

    class ReachedBootstrap(Exception):
        pass

    def inspect_bootstrap(args):
        assert args.working_directory == root / "nq-work"
        assert args.working_directory.is_dir()
        assert args.working_directory.stat().st_mode & 0o777 == 0o700
        raise ReachedBootstrap

    monkeypatch.setattr(MODULE.NQ_HOST, "prepare", inspect_bootstrap)
    with pytest.raises(ReachedBootstrap):
        MODULE.prepare(config)


def test_absent_external_nq_working_directory_refuses_before_root(tmp_path):
    config = minimal_config(tmp_path)
    config["nq"]["working_directory"] = str(tmp_path / "absent-external")
    with pytest.raises(ValueError, match="must already exist"):
        MODULE.prepare(config)
    assert not Path(config["root"]).exists()


def test_existing_caller_nq_working_directory_is_preserved(tmp_path, monkeypatch):
    config = minimal_config(tmp_path)
    external = tmp_path / "caller-work"
    external.mkdir()
    external.chmod(0o750)
    config["nq"]["working_directory"] = str(external)
    monkeypatch.setattr(MODULE, "expected_host_scope_digest",
                        lambda *unused: config["identities"]["scope_digest"])

    class ReachedBootstrap(Exception):
        pass

    def inspect_bootstrap(args):
        assert args.working_directory == external
        assert external.stat().st_mode & 0o777 == 0o750
        raise ReachedBootstrap

    monkeypatch.setattr(MODULE.NQ_HOST, "prepare", inspect_bootstrap)
    with pytest.raises(ReachedBootstrap):
        MODULE.prepare(config)


def test_scope_digest_uses_exact_pinned_nq_profile(monkeypatch):
    digest = "sha256:" + "1" * 64
    monkeypatch.setattr(MODULE, "run", lambda argv: json.dumps([{
        "digest": digest, "family": "host", "id": "nq.host",
        "title": "Local host state", "version": 1,
    }]).encode())
    descriptor = {
        "schema": "nq.diagnostic_scope.v1", "subject": "host:local",
        "scope": {"kind": "host", "value": {"id": "local"}},
        "profile": {"id": "nq.host", "version": "1", "digest": digest},
    }
    expected = "sha256:" + MODULE.hashlib.sha256(MODULE.canonical(descriptor)).hexdigest()
    assert MODULE.expected_host_scope_digest("/nq", "host:local", "local") == expected
