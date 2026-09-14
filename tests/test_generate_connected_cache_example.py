import importlib.util
import json
from pathlib import Path
import sys

import pytest

HERE = Path(__file__).parents[1] / "qualification/synthetic_cache"
sys.path.insert(0, str(HERE))
try:
    spec = importlib.util.spec_from_file_location("connected_cache_example", HERE / "generate_connected_cache_example.py")
    MODULE = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(MODULE)
finally:
    sys.path.pop(0)


def inputs(tmp_path):
    programs = tmp_path / "programs"
    programs.mkdir()
    manifest_programs = {}
    for name in set(MODULE.SETUP.PROGRAMS) - {"python"}:
        path = programs / name.replace("_", "-")
        path.write_text("#!/bin/sh\nexit 0\n")
        path.chmod(0o700)
        manifest_programs[name] = {"filename": path.name, "sha256": MODULE.SETUP.file_digest(path)}
    python = tmp_path / "python"
    python.write_text("#!/bin/sh\nexit 0\n")
    python.chmod(0o700)
    sealer = tmp_path / "sealer.py"
    sealer.write_text("pass\n")
    source = tmp_path / "maude"
    utilities = source / "qualification/synthetic_cache"
    utilities.mkdir(parents=True)
    build_plan, executor = utilities / "build_plan.py", utilities / "local_compose_executor.py"
    build_plan.write_text("build\n"); executor.write_text("executor\n")
    manifest = {
        "schema": MODULE.INSTALL_SCHEMA, "maude_source_revision": "revision",
        "maude_build_plan_sha256": MODULE.SETUP.file_digest(build_plan),
        "maude_executor_sha256": MODULE.SETUP.file_digest(executor),
        "programs": manifest_programs, "python_sha256": MODULE.SETUP.file_digest(python),
        "pulse_launcher_sealer_sha256": MODULE.SETUP.file_digest(sealer),
        "source_revisions": {
            "nq_cli": "1" * 40, "nq_helpers": "2" * 40, "nightshift": "3" * 40,
            "ag": "4" * 40, "docket": "5" * 40, "pulse_integration": "6" * 40,
        },
    }
    digest = lambda value: "sha256:" + value * 64
    profile = {
        "schema": MODULE.PROFILE_SCHEMA,
        "identities": {"campaign_id": digest("a"), "program_id": digest("b"),
            "subject_digest": digest("c"), "qualification_occurrence_id": "10000000-0000-4000-8000-000000000001",
            "successor_occurrence_id": "10000000-0000-4000-8000-000000000002",
            "watcher_instance_id": "watcher", "local_successor_acquisition_id": "acquisition:successor",
            "runtime_id": "nightshift:synthetic-cache", "generation": "generation:synthetic-cache",
            "configuration_version": "configuration:synthetic-cache", "role_id": "nightshift-role:cache-bootstrap-host",
            "role_version": 1, "role_digest": digest("e"), "qualification_schedule_id": "schedule:q",
            "successor_schedule_id": "schedule:t", "qualification_attempt_id": "attempt:q",
            "successor_attempt_id": "attempt:t", "scheduler_clock_id": "clock:realtime",
            "qualification_pulse_acquisition_id": "acquisition:pulse:q",
            "successor_pulse_acquisition_id": "acquisition:pulse:t"},
        "nq": {"nq_subject": "host:synthetic-cache", "nq_scope_id": "synthetic-cache"},
        "runtime": {"image": "python:3.13-alpine@sha256:" + "f" * 64,
            "docker_client_version": "29.1.3", "docker_server_version": "29.1.3",
            "compose_version": "5.0.0", "project": "maude-cache-birthday", "front_port": 8080},
        "governance": {"profile_label": "synthetic-standing-cache-example",
            "observation_resolver_id": "nightshift-observation-resolver/v1",
            "standing_resolver_id": "ag-standing-resolver/integration-v1",
            "issuer_principal": "synthetic-cache-ag", "issuer_key_id": "synthetic-cache-key",
            "observation_ttl_ms": 120000, "standing_ttl_ms": 60000, "docket_standing_ttl_ms": 60000},
    }
    manifest_path, profile_path = tmp_path / "install.json", tmp_path / "profile.json"
    manifest_path.write_text(json.dumps(manifest)); profile_path.write_text(json.dumps(profile))
    args = MODULE.argparse.Namespace(output=tmp_path / "setup.json", root=tmp_path / "run",
        maude_source=source, program_dir=programs, python=python, pulse_launcher_sealer=sealer,
        install_manifest=manifest_path, profile=profile_path, execution_account="fixture",
        allow_same_identity_in_debug=True)
    return args, manifest_programs


def test_example_expands_pinned_install_into_existing_schema(tmp_path, monkeypatch):
    args, programs = inputs(tmp_path)
    monkeypatch.setattr(MODULE, "checked_source", lambda source, install: None)
    monkeypatch.setattr(MODULE.SETUP, "expected_host_scope_digest", lambda *unused: "sha256:" + "d" * 64)
    value = MODULE.generate(args)
    assert value["schema"] == MODULE.SETUP.SCHEMA
    assert value["root"] == str(args.root)
    assert value["nq"]["allow_same_identity_in_debug"] is True
    assert value["governance"]["profile_label"] == "synthetic-standing-cache-example"
    assert value["identities"]["scope_digest"] == "sha256:" + "d" * 64
    assert value["programs"]["nq"]["path"] == str(args.program_dir / programs["nq"]["filename"])


def test_example_output_prepares_fresh_owned_nq_working_directory(tmp_path, monkeypatch):
    args, _ = inputs(tmp_path)
    monkeypatch.setattr(MODULE, "checked_source", lambda source, install: None)
    scope = "sha256:" + "d" * 64
    monkeypatch.setattr(MODULE.SETUP, "expected_host_scope_digest", lambda *unused: scope)
    config = MODULE.generate(args)
    assert config["nq"]["working_directory"] == str(args.root / "nq-work")

    class ReachedBootstrap(Exception):
        pass

    def inspect_bootstrap(nq_args):
        assert nq_args.working_directory == args.root / "nq-work"
        assert nq_args.working_directory.is_dir()
        raise ReachedBootstrap

    monkeypatch.setattr(MODULE.SETUP.NQ_HOST, "prepare", inspect_bootstrap)
    with pytest.raises(ReachedBootstrap):
        MODULE.SETUP.prepare(config)


def test_example_pin_or_debug_omission_refuses_before_output(tmp_path, monkeypatch):
    args, _ = inputs(tmp_path)
    monkeypatch.setattr(MODULE, "checked_source", lambda source, install: None)
    args.allow_same_identity_in_debug = False
    with pytest.raises(ValueError, match="explicit debug"):
        MODULE.generate(args)
    assert not args.output.exists() and not args.root.exists()
    args.allow_same_identity_in_debug = True
    manifest = json.loads(args.install_manifest.read_text())
    manifest["programs"]["nq"]["sha256"] = "0" * 64
    args.install_manifest.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="installed program bytes"):
        MODULE.generate(args)
    assert not args.output.exists() and not args.root.exists()


def test_distributed_templates_are_closed_and_deliberately_non_runnable():
    install = json.loads((HERE / "connected-cache-install.example.json").read_text())
    profile = json.loads((HERE / "connected-cache-profile.example.json").read_text())
    assert install["schema"] == MODULE.INSTALL_SCHEMA
    assert set(install["programs"]) == set(MODULE.SETUP.PROGRAMS) - {"python"}
    assert set(install["source_revisions"]) == MODULE.SOURCE_NAMES
    assert profile["schema"] == MODULE.PROFILE_SCHEMA
    assert set(profile) == {"schema", "identities", "nq", "runtime", "governance"}
    assert profile["governance"]["profile_label"] == "synthetic-standing-cache-example"
    assert profile["runtime"]["project"] == "maude-cache-birthday"
    assert "REPLACE_WITH" in json.dumps(install) and "REPLACE_WITH" in json.dumps(profile)
