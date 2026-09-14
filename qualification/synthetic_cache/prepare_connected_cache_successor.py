#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Seal the explicit inputs for one connected-cache successor occurrence.

This preparation command performs no owner operation. It emits the closed stage
contract consumed by the bounded connected-cache driver after every named path
and byte pin has been checked.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat

SCHEMA = "maude.connected-cache-successor-preparation/v1"
PROGRAMS = ("nq", "pulse", "nightshift", "ag", "docket")
HELPERS = (
    "host_bootstrap",
    "proposal_attach",
    "family_check",
    "external_prepare",
    "external_attach",
    "result_config",
    "accepted_action_compile",
)
STAGES = ("nq_genesis", "initial_pulse_custody", "initial_nightshift",
          "initial_ag_docket_settlement", "external_acquisition",
          "result_owner_reconciliation", "nq_local_successor",
          "successor_family_check", "successor_pulse_custody",
          "successor_nightshift", "successor_ag_docket_settlement",
          "bounded_teardown", "owner_readback")
MAX_CONFIG = 32 * 1024
MAX_ENROLLED = 128 * 1024 * 1024


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def read_regular(path: Path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("config is not regular")
        raw = stream.read(MAX_CONFIG + 1)
    if not raw or len(raw) > MAX_CONFIG:
        raise ValueError("config is empty or too large")
    return raw


def hash_regular(path: Path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    digest = hashlib.sha256()
    total = 0
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("enrolled input is not regular")
        while chunk := stream.read(1024 * 1024):
            total += len(chunk)
            if total > MAX_ENROLLED:
                raise ValueError("enrolled input exceeds bound")
            digest.update(chunk)
    return digest.hexdigest()


def validate(config):
    if set(config) != {"files", "helpers", "identities", "mode", "programs", "schema"}:
        raise ValueError("config fields differ")
    if config["schema"] != SCHEMA or config["mode"] not in {"fixture", "accepted"}:
        raise ValueError("schema or mode differs")
    if set(config["programs"]) != set(PROGRAMS) or set(config["helpers"]) != set(HELPERS):
        raise ValueError("closed program/helper enrollment differs")
    for group in ("programs", "helpers", "files"):
        for name, item in config[group].items():
            if set(item) != {"path", "sha256"}:
                raise ValueError(f"{group}.{name} fields differ")
            path = Path(item["path"])
            if (not path.is_absolute() or len(item["sha256"]) != 64
                    or any(char not in "0123456789abcdef" for char in item["sha256"])):
                raise ValueError(f"{group}.{name} path or pin differs")
    identities = config["identities"]
    required = {"initial_occurrence", "successor_occurrence", "watcher_id",
                "local_acquisition_id", "generation", "configuration_version",
                "standing_kind"}
    if set(identities) != required or identities["initial_occurrence"] == identities["successor_occurrence"]:
        raise ValueError("identity enrollment differs")
    if identities["standing_kind"] != "synthetic_fixture":
        raise ValueError("Standing must remain explicitly synthetic")
    return config


def prepare(config):
    validate(config)
    enrolled = []
    for group in ("programs", "helpers", "files"):
        for name in sorted(config[group]):
            item = config[group][name]
            if hash_regular(Path(item["path"])) != item["sha256"]:
                raise ValueError(f"{group}.{name} bytes differ")
            enrolled.append({"kind": group, "name": name, **item})
    identities = config["identities"]
    return {"schema": SCHEMA, "mode": config["mode"], "enrolled": enrolled,
            "stages": list(STAGES), "identities": identities,
            "successor_rules": {
                "nq_config": "same_as_genesis",
                "watcher": identities["watcher_id"],
                "acquisition_id": identities["local_acquisition_id"],
                "repeat_genesis": False,
                "fresh_observation_before_successor_evaluation": True,
                "retain_qualification_bytes": True,
            },
            "authority": "none", "effects": False,
            "qualification_status": "not_yet_public_only_executed"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = prepare(json.loads(read_regular(args.config)))
    descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(canonical(result))
        stream.flush()
        os.fsync(stream.fileno())


if __name__ == "__main__":
    main()
