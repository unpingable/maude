# SPDX-License-Identifier: Apache-2.0
"""Component tests for portable accepted-cache compilation glue."""

import importlib.util
import json
from pathlib import Path
import sqlite3
import sys

import pytest

SOURCE = Path(__file__).parents[1] / "qualification" / "synthetic_cache" / "compile_accepted_cache_actions.py"
SPEC = importlib.util.spec_from_file_location("accepted_actions", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

PREPARE_SOURCE = SOURCE.with_name("prepare_connected_cache_successor.py")
PREPARE_SPEC = importlib.util.spec_from_file_location("prepare_successor", PREPARE_SOURCE)
PREPARE = importlib.util.module_from_spec(PREPARE_SPEC)
PREPARE_SPEC.loader.exec_module(PREPARE)


def test_bounded_regular_reader_refuses_symlink_and_oversize(tmp_path):
    target = tmp_path / "target"
    target.write_bytes(b"{}")
    alias = tmp_path / "alias"
    alias.symlink_to(target)
    with pytest.raises(OSError):
        MODULE.read_regular(alias, 32)
    target.write_bytes(b"x" * 33)
    with pytest.raises(ValueError, match="bounded regular"):
        MODULE.read_regular(target, 32)


def test_pins_are_exact_lowercase_sha256():
    raw = b"accepted bytes"
    MODULE.require_pin(raw, MODULE.sha256(raw), "fixture")
    with pytest.raises(ValueError, match="lowercase"):
        MODULE.require_pin(raw, "A" * 64, "fixture")
    with pytest.raises(ValueError, match="differ"):
        MODULE.require_pin(raw, "0" * 64, "fixture")


def test_store_snapshot_is_fresh_and_source_remains_unchanged(tmp_path):
    source = tmp_path / "source.sqlite"
    with sqlite3.connect(source) as database:
        database.execute("create table records(value text not null)")
        database.execute("insert into records values ('retained')")
    before = source.read_bytes()
    destination = tmp_path / "copy.sqlite"
    MODULE.snapshot_store(source, destination, MODULE.sha256(before))
    assert source.read_bytes() == before
    with sqlite3.connect(f"file:{destination}?mode=ro", uri=True) as database:
        assert database.execute("select value from records").fetchone() == ("retained",)
    with pytest.raises(FileExistsError):
        MODULE.snapshot_store(source, destination, MODULE.sha256(before))
    Path(str(source) + "-wal").write_bytes(b"sidecar")
    with pytest.raises(ValueError, match="sidecar"):
        MODULE.snapshot_store(source, tmp_path / "second.sqlite", MODULE.sha256(before))


def test_cli_requires_all_explicit_path_and_identity_inputs():
    help_text = MODULE.parser().format_help()
    for option in ("--maude-source", "--maude-local-compose-sha256",
                   "--accepted-store", "--accepted-store-sha256",
                   "--bundle", "--bundle-sha256", "--compiler-input",
                   "--compiler-input-sha256", "--output"):
        assert option in help_text
    for option in ("--prepare-input", "--context", "--context-sha256",
                   "--nq-observation", "--nq-observation-sha256"):
        assert option in help_text
    assert ".campaign-artifacts" not in SOURCE.read_text()


def _digest(value):
    return "sha256:" + MODULE.sha256(MODULE.canonical(value))


def _accepted_input_fixture(tmp_path):
    source = SOURCE.parents[2]
    sys.path.insert(0, str(source / "src"))
    try:
        from maude.plan.store import DraftStore
        spec = importlib.util.spec_from_file_location("fixture_build_plan",
                                                      source / "qualification/synthetic_cache/build_plan.py")
        build_plan = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(build_plan)
    finally:
        sys.path.pop(0)
    store_path = tmp_path / "accepted.sqlite"
    store = DraftStore(store_path)
    revision = store.create(build_plan.initial_document(), draft_id="accepted-cache")
    lock = store.lock("accepted-cache", revision.revision_id)
    bundle = tmp_path / "bundle.json"
    bundle_value = {"schema": MODULE.BUNDLE_SCHEMA, "acceptance_ref": "caller-record-001",
                    "draft_id": "accepted-cache", "lock_id": lock.lock_id,
                    "plan_digest": lock.plan_digest}
    bundle.write_bytes(MODULE.canonical(bundle_value))
    docker = tmp_path / "docker"
    docker.write_bytes(b"docker-bytes")
    build_path = source / "qualification/synthetic_cache/build_plan.py"
    compiler_path = source / "src/maude/plan/local_compose.py"
    workspace = tmp_path / "runtime/maude-cache-birthday"
    context = tmp_path / "context.json"
    context_value = {
        "schema": MODULE.CONTEXT_SCHEMA,
        "files": {"maude_source": {"path": str(source), "declared_revision": "fixture"},
                  "maude_build_plan": {"path": str(build_path),
                                       "sha256": MODULE.sha256(build_path.read_bytes())}},
        "programs": {"docker": {"path": str(docker), "sha256": MODULE.sha256(docker.read_bytes())}},
        "runtime": {"workspace": str(workspace), "project": "maude-cache-birthday",
                    "front_port": 8080,
                    "image": "python:3.13-alpine@sha256:" + "1" * 64,
                    "docker_client_version": "1", "docker_server_version": "1",
                    "compose_version": "1"},
        "identities": {"campaign_id": "sha256:" + "2" * 64,
                       "program_id": "sha256:" + "3" * 64,
                       "subject_digest": "sha256:" + "4" * 64,
                       "scope_digest": "sha256:" + "5" * 64,
                       "qualification_occurrence_id": "00000000-0000-4000-8000-000000000000",
                       "successor_occurrence_id": "00000000-0000-4000-8000-000000000001"},
        "nq": {"subject": "host:fixture"},
    }
    context.write_bytes(MODULE.canonical(context_value))
    observation = tmp_path / "observation.json"
    observation_value = {"schema": "nq.diagnostic_execution.v2",
                         "profile": {"id": "nq.host"},
                         "question": {"id": "nq.host.load_pressure"},
                         "artifact_id": "sha256:" + "6" * 64,
                         "subject": {"id": "host:fixture",
                                     "scope": {"digest": "sha256:" + "5" * 64}},
                         "outcome": {"condition": "explicitly_absent"}}
    observation.write_bytes(MODULE.canonical(observation_value))
    return {"source": source, "store": store_path, "bundle": bundle, "context": context,
            "observation": observation, "compiler": compiler_path, "document": revision.document,
            "bundle_value": bundle_value, "observation_value": observation_value}


def _prepare_args(fixture, output, action="qualify"):
    return type("Args", (), {
        "prepare_input": True, "action": action, "output": output,
        "context": fixture["context"], "context_sha256": MODULE.sha256(fixture["context"].read_bytes()),
        "accepted_store": fixture["store"],
        "accepted_store_sha256": MODULE.sha256(fixture["store"].read_bytes()),
        "bundle": fixture["bundle"], "bundle_sha256": MODULE.sha256(fixture["bundle"].read_bytes()),
        "nq_observation": fixture["observation"],
        "nq_observation_sha256": MODULE.sha256(fixture["observation"].read_bytes()),
        "maude_local_compose_sha256": MODULE.sha256(fixture["compiler"].read_bytes()),
    })()


def test_prepare_input_binds_pinned_context_lock_and_actual_nq_observation(tmp_path):
    fixture = _accepted_input_fixture(tmp_path)
    before = fixture["store"].read_bytes()
    output = tmp_path / "prepared"
    MODULE.prepare_compiler_input(_prepare_args(fixture, output))
    assert fixture["store"].read_bytes() == before
    prepared = json.loads((output / "preparation.json").read_bytes())
    assert prepared["locked_plan_digest"] == fixture["document"].digest
    assert prepared["acceptance_ref"] == "caller-record-001"
    assert prepared["acceptance_proof"] == "opaque_caller_reference_not_authenticated_by_draft_store"
    assert prepared["accepted_store_snapshot_sha256"] == "sha256:" + MODULE.sha256(
        (output / "accepted-plan.sqlite").read_bytes())
    assert (output / "accepted-bundle.json").read_bytes() == fixture["bundle"].read_bytes()
    assert json.loads((output / "plan-locked.json").read_bytes()) == fixture["document"].to_data()
    compiler_input = json.loads((output / "compiler-input-qualify.json").read_bytes())
    assert compiler_input["scope_digest"] == "sha256:" + "5" * 64
    assert compiler_input["observation_id"] == _digest({"artifact_id": "sha256:" + "6" * 64})
    assert (output / "accepted-plan.sqlite").is_file()


def test_prepare_input_refuses_substituted_nq_scope_before_output_allocation(tmp_path):
    fixture = _accepted_input_fixture(tmp_path)
    replaced = dict(fixture["observation_value"])
    replaced["subject"] = {"id": "host:fixture", "scope": {"digest": "sha256:" + "7" * 64}}
    fixture["observation"].write_bytes(MODULE.canonical(replaced))
    output = tmp_path / "must-not-exist"
    with pytest.raises(ValueError, match="subject or scope"):
        MODULE.prepare_compiler_input(_prepare_args(fixture, output))
    assert not output.exists()


def test_preparation_has_closed_owner_order_and_same_nq_owner(tmp_path):
    item = tmp_path / "item"
    item.write_bytes(b"fixed")
    pin = MODULE.sha256(b"fixed")
    entry = {"path": str(item), "sha256": pin}
    config = {"schema": PREPARE.SCHEMA, "mode": "fixture",
              "programs": {name: entry for name in PREPARE.PROGRAMS},
              "helpers": {name: entry for name in PREPARE.HELPERS},
              "files": {"nq_config": entry, "pulse_config": entry,
                        "nightshift_store": entry, "ag_runtime_profile": entry,
                        "docket_trust": entry, "accepted_bundle": entry},
              "identities": {"initial_occurrence": "occurrence-initial",
                             "successor_occurrence": "occurrence-successor",
                             "watcher_id": "watcher-local",
                             "local_acquisition_id": "acquisition-next",
                             "generation": "generation-one",
                             "configuration_version": "configuration-one",
                             "standing_kind": "synthetic_fixture"}}
    result = PREPARE.prepare(config)
    assert tuple(result["stages"]) == PREPARE.STAGES
    assert result["stages"].index("result_owner_reconciliation") < result["stages"].index("nq_local_successor")
    assert result["stages"].index("successor_family_check") < result["stages"].index("successor_nightshift")
    assert result["successor_rules"]["nq_config"] == "same_as_genesis"
    assert result["successor_rules"]["repeat_genesis"] is False
    assert result["authority"] == "none" and result["effects"] is False
    assert ".campaign-artifacts" not in PREPARE_SOURCE.read_text()


def test_preparation_refuses_identity_reuse_or_hidden_standing():
    base = {"schema": PREPARE.SCHEMA, "mode": "accepted",
            "programs": {}, "helpers": {}, "files": {},
            "identities": {"initial_occurrence": "same", "successor_occurrence": "same",
                           "watcher_id": "w", "local_acquisition_id": "a",
                           "generation": "g", "configuration_version": "c",
                           "standing_kind": "deployment"}}
    with pytest.raises(ValueError):
        PREPARE.validate(base)
