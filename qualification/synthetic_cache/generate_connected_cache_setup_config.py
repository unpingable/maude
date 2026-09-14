#!/usr/bin/env python3
"""Measure explicit public prerequisites into one connected-cache setup config."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path


def load_setup():
    path = Path(__file__).with_name("prepare_connected_cache_run.py")
    spec = importlib.util.spec_from_file_location("connected_cache_setup", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SETUP = load_setup()


def pinned(path: Path, *, executable: bool = True) -> dict:
    if not path.is_absolute() or (executable and not os.access(path, os.X_OK)):
        raise ValueError(f"input must be an absolute regular file with the requested mode: {path}")
    return {"path": str(path), "sha256": SETUP.file_digest(path)}


def generate(args: argparse.Namespace) -> dict:
    programs = {name: pinned(getattr(args, name)) for name in SETUP.PROGRAMS}
    maude_source = args.maude_source
    build_plan = maude_source / "qualification/synthetic_cache/build_plan.py"
    executor = maude_source / "qualification/synthetic_cache/local_compose_executor.py"
    scope_digest = SETUP.expected_host_scope_digest(
        programs["nq"]["path"], args.nq_subject, args.nq_scope_id
    )
    config = {
        "schema": SETUP.SCHEMA, "root": str(args.root), "programs": programs,
        "files": {"pulse_launcher_sealer": pinned(args.pulse_launcher_sealer, executable=False)},
        "maude": {"source": str(maude_source), "source_revision": args.maude_source_revision,
                  "build_plan_sha256": SETUP.file_digest(build_plan),
                  "executor_sha256": SETUP.file_digest(executor)},
        "identities": {
            "campaign_id": args.campaign_id, "program_id": args.program_id,
            "subject_digest": args.subject_digest, "scope_digest": scope_digest,
            "qualification_occurrence_id": args.qualification_occurrence_id,
            "successor_occurrence_id": args.successor_occurrence_id,
            "watcher_instance_id": args.watcher_instance_id,
            "local_successor_acquisition_id": args.local_successor_acquisition_id,
            "runtime_id": args.runtime_id, "generation": args.generation,
            "configuration_version": args.configuration_version, "role_id": args.role_id,
            "role_version": args.role_version, "role_digest": args.role_digest,
            "qualification_schedule_id": args.qualification_schedule_id,
            "successor_schedule_id": args.successor_schedule_id,
            "qualification_attempt_id": args.qualification_attempt_id,
            "successor_attempt_id": args.successor_attempt_id,
            "scheduler_clock_id": args.scheduler_clock_id,
            "qualification_pulse_acquisition_id": args.qualification_pulse_acquisition_id,
            "successor_pulse_acquisition_id": args.successor_pulse_acquisition_id,
        },
        "nq": {"execution_account": args.execution_account, "subject": args.nq_subject,
               "scope_id": args.nq_scope_id, "working_directory": str(args.working_directory),
               "allow_same_identity_in_debug": args.allow_same_identity_in_debug},
        "runtime": {"image": args.image, "docker_client_version": args.docker_client_version,
                    "docker_server_version": args.docker_server_version,
                    "compose_version": args.compose_version, "project": args.project,
                    "front_port": args.front_port},
        "governance": {"profile_label": args.profile_label,
                       "observation_resolver_id": args.observation_resolver_id,
                       "standing_resolver_id": args.standing_resolver_id,
                       "issuer_principal": args.issuer_principal,
                       "issuer_key_id": args.issuer_key_id,
                       "observation_ttl_ms": args.observation_ttl_ms,
                       "standing_ttl_ms": args.standing_ttl_ms,
                       "docket_standing_ttl_ms": args.docket_standing_ttl_ms},
    }
    SETUP.validate(config)
    return config


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--output", type=Path, required=True)
    result.add_argument("--root", type=Path, required=True)
    for name in SETUP.PROGRAMS:
        result.add_argument("--" + name.replace("_", "-"), type=Path, required=True)
    result.add_argument("--pulse-launcher-sealer", type=Path, required=True)
    result.add_argument("--maude-source", type=Path, required=True)
    result.add_argument("--maude-source-revision", required=True)
    for name in ("campaign_id", "program_id", "subject_digest", "qualification_occurrence_id",
                 "successor_occurrence_id", "watcher_instance_id",
                 "local_successor_acquisition_id", "runtime_id", "generation",
                 "configuration_version", "role_id", "role_digest",
                 "qualification_schedule_id", "successor_schedule_id",
                 "qualification_attempt_id", "successor_attempt_id", "scheduler_clock_id",
                 "qualification_pulse_acquisition_id", "successor_pulse_acquisition_id"):
        result.add_argument("--" + name.replace("_", "-"), required=True)
    result.add_argument("--role-version", type=int, required=True)
    result.add_argument("--execution-account", required=True)
    result.add_argument("--nq-subject", required=True)
    result.add_argument("--nq-scope-id", required=True)
    result.add_argument("--working-directory", type=Path, required=True)
    result.add_argument("--allow-same-identity-in-debug", action="store_true")
    for name in ("image", "docker_client_version", "docker_server_version", "compose_version",
                 "project", "profile_label", "observation_resolver_id", "standing_resolver_id",
                 "issuer_principal", "issuer_key_id"):
        result.add_argument("--" + name.replace("_", "-"), required=True)
    result.add_argument("--front-port", type=int, required=True)
    result.add_argument("--observation-ttl-ms", type=int, default=120000)
    result.add_argument("--standing-ttl-ms", type=int, default=60000)
    result.add_argument("--docket-standing-ttl-ms", type=int, default=60000)
    return result


def main() -> None:
    args = parser().parse_args()
    if not args.output.is_absolute():
        raise ValueError("output must be absolute")
    SETUP.write_new(args.output, SETUP.canonical(generate(args)))


if __name__ == "__main__":
    main()
