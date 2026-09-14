import importlib.util
import json
import os
from pathlib import Path

import pytest

SOURCE = Path(__file__).parents[1] / "qualification/synthetic_cache/public-governance-bootstrap.py"
SPEC = importlib.util.spec_from_file_location("public_governance_bootstrap", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def fixture_config(tmp_path):
    program = tmp_path / "program"
    program.write_text("#!/bin/sh\nexit 0\n")
    program.chmod(0o700)
    pin = MODULE.sha256(program)
    catalog = tmp_path / "catalog.json"
    catalog.write_text("{}")
    return {
        "schema": MODULE.SCHEMA, "output_root": str(tmp_path / "output"),
        "programs": {name: {"path": str(program), "sha256": pin}
                     for name in MODULE.PROGRAM_NAMES},
        "catalog": {"path": str(catalog), "sha256": MODULE.sha256(catalog)},
        "identities": {"profile_label": "synthetic-cache-fixture",
                       "observation_resolver_id": "nightshift-observation-resolver/v1",
                       "standing_resolver_id": "ag-standing-resolver/integration-v1",
                       "issuer_principal": "synthetic-cache-ag", "issuer_key_id": "fixture-key-1"},
        "limits": {"observation_ttl_ms": 120000, "standing_ttl_ms": 60000,
                   "docket_standing_ttl_ms": 60000},
    }


def test_missing_or_wrong_typed_field_refuses_before_allocation(tmp_path):
    config = fixture_config(tmp_path)
    del config["identities"]["issuer_key_id"]
    with pytest.raises(ValueError, match="identity fields"):
        MODULE.build(config)
    assert not Path(config["output_root"]).exists()

    config = fixture_config(tmp_path)
    config["limits"]["standing_ttl_ms"] = True
    with pytest.raises(ValueError, match="limit fields"):
        MODULE.build(config)
    assert not Path(config["output_root"]).exists()


def test_duplicate_output_refuses_before_key_generation(tmp_path):
    config = fixture_config(tmp_path)
    output = Path(config["output_root"])
    output.mkdir()
    with pytest.raises(ValueError, match="absent absolute"):
        MODULE.build(config)
    assert list(output.iterdir()) == []


def test_shell_wrapper_quotes_exact_paths():
    wrapper = MODULE.shell_wrapper("/a path/program", ["--store", "/some path/store"])
    assert wrapper == b"#!/bin/sh\nexec '/a path/program' --store '/some path/store'\n"
