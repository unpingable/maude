#!/usr/bin/env python3
"""Prepare fresh, authority-empty files for one connected-cache example run."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import stat
import subprocess
import tempfile
import uuid

SCHEMA = "maude.connected-cache-run-preparation/v1"
CONTEXT_SCHEMA = "maude.connected-cache-run-context/v1"
MAX_CONFIG = 32 * 1024
MAX_FILE = 128 * 1024 * 1024
PROGRAMS = (
    "nq", "nq_host_helper", "nq_result_helper", "pulse", "nightshift",
    "nightshift_observation_resolver", "ag", "ag_standing_resolver",
    "docket", "python", "openssl", "docker",
)
IDENTITIES = (
    "campaign_id", "program_id", "subject_digest", "scope_digest",
    "qualification_occurrence_id", "successor_occurrence_id",
    "watcher_instance_id", "local_successor_acquisition_id", "runtime_id",
    "generation", "configuration_version",
    "role_id", "role_version", "role_digest", "qualification_schedule_id",
    "successor_schedule_id", "qualification_attempt_id", "successor_attempt_id",
    "scheduler_clock_id", "qualification_pulse_acquisition_id",
    "successor_pulse_acquisition_id",
)
DIGEST_IDENTITIES = ("campaign_id", "program_id", "subject_digest", "scope_digest", "role_digest")


def load_sibling(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GOVERNANCE = load_sibling("public_governance_bootstrap", "public-governance-bootstrap.py")
NQ_HOST = load_sibling("public_nq_host_bootstrap", "public-nq-host-bootstrap.py")


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def read_regular(path: Path, limit: int) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("input must be a regular non-symlink file")
        raw = stream.read(limit + 1)
    if not raw or len(raw) > limit:
        raise ValueError("input is empty or oversized")
    return raw


def file_digest(path: Path) -> str:
    return hashlib.sha256(read_regular(path, MAX_FILE)).hexdigest()


def is_digest(value: object) -> bool:
    return (isinstance(value, str) and value.startswith("sha256:") and len(value) == 71
            and all(character in "0123456789abcdef" for character in value[7:]))


def is_pin(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(character in "0123456789abcdef" for character in value))


def validate(config: dict) -> dict:
    fields = {"schema", "root", "programs", "files", "maude", "identities", "nq", "runtime",
              "governance"}
    if not isinstance(config, dict) or set(config) != fields or config.get("schema") != SCHEMA:
        raise ValueError("configuration fields or schema differ")
    root = Path(config["root"])
    if not root.is_absolute() or root.exists():
        raise ValueError("root must be an absent absolute path")
    programs = config["programs"]
    if not isinstance(programs, dict) or set(programs) != set(PROGRAMS):
        raise ValueError("closed program enrollment differs")
    for name, item in programs.items():
        if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
            raise ValueError(f"program {name} fields differ")
        if not isinstance(item["path"], str) or not Path(item["path"]).is_absolute() \
                or not is_pin(item["sha256"]):
            raise ValueError(f"program {name} coordinate differs")
    files = config["files"]
    if not isinstance(files, dict) or set(files) != {"pulse_launcher_sealer"}:
        raise ValueError("closed file enrollment differs")
    sealer = files["pulse_launcher_sealer"]
    if not isinstance(sealer, dict) or set(sealer) != {"path", "sha256"} \
            or not isinstance(sealer["path"], str) or not Path(sealer["path"]).is_absolute() \
            or not is_pin(sealer["sha256"]):
        raise ValueError("Pulse launcher sealer coordinate differs")
    maude = config["maude"]
    if not isinstance(maude, dict) or set(maude) != {
        "source", "source_revision", "build_plan_sha256", "executor_sha256"
    } or not isinstance(maude["source"], str) or not Path(maude["source"]).is_absolute() \
            or any(not isinstance(maude[name], str) or not maude[name]
                   for name in ("source_revision",)) \
            or not all(is_pin(maude[name]) for name in ("build_plan_sha256", "executor_sha256")):
        raise ValueError("Maude coordinate differs")
    identities = config["identities"]
    if not isinstance(identities, dict) or set(identities) != set(IDENTITIES):
        raise ValueError("identity fields differ")
    if not all(is_digest(identities[name]) for name in DIGEST_IDENTITIES):
        raise ValueError("content identity differs")
    for name in ("qualification_occurrence_id", "successor_occurrence_id"):
        try:
            parsed = uuid.UUID(identities[name])
        except (ValueError, TypeError, AttributeError) as error:
            raise ValueError("occurrence identity differs") from error
        if parsed.version != 4 or str(parsed) != identities[name]:
            raise ValueError("occurrence identity differs")
    if identities["qualification_occurrence_id"] == identities["successor_occurrence_id"]:
        raise ValueError("occurrence identities must differ")
    if not isinstance(identities["role_version"], int) or isinstance(identities["role_version"], bool) \
            or identities["role_version"] <= 0:
        raise ValueError("role version differs")
    for name in set(IDENTITIES) - set(DIGEST_IDENTITIES) \
            - {"role_version"} \
            - {"qualification_occurrence_id", "successor_occurrence_id"}:
        value = identities[name]
        if not isinstance(value, str) or not value or len(value) > 256 or any(c.isspace() for c in value):
            raise ValueError(f"identity {name} differs")
    nq = config["nq"]
    if not isinstance(nq, dict) or set(nq) != {
        "execution_account", "subject", "scope_id", "working_directory",
        "allow_same_identity_in_debug"
    } or any(not isinstance(nq[name], str) or not nq[name]
             for name in ("execution_account", "subject", "scope_id", "working_directory")) \
            or not Path(nq["working_directory"]).is_absolute() \
            or not isinstance(nq["allow_same_identity_in_debug"], bool):
        raise ValueError("NQ enrollment differs")
    if nq["subject"] != "host:" + nq["scope_id"]:
        raise ValueError("NQ host subject and scope do not correlate")
    runtime = config["runtime"]
    if not isinstance(runtime, dict) or set(runtime) != {
        "image", "docker_client_version", "docker_server_version", "compose_version",
        "project", "front_port"
    } or any(not isinstance(runtime[name], str) or not runtime[name]
             for name in ("image", "docker_client_version", "docker_server_version",
                          "compose_version", "project")) \
            or not isinstance(runtime["front_port"], int) or isinstance(runtime["front_port"], bool) \
            or not 1 <= runtime["front_port"] <= 65535:
        raise ValueError("runtime enrollment differs")
    governance = config["governance"]
    if not isinstance(governance, dict) or set(governance) != {
        "profile_label", "observation_resolver_id", "standing_resolver_id",
        "issuer_principal", "issuer_key_id", "observation_ttl_ms",
        "standing_ttl_ms", "docket_standing_ttl_ms"
    }:
        raise ValueError("governance enrollment differs")
    if any(not isinstance(governance[name], str) or not governance[name]
           for name in ("profile_label", "observation_resolver_id", "standing_resolver_id",
                        "issuer_principal", "issuer_key_id")) \
            or any(not isinstance(governance[name], int) or isinstance(governance[name], bool)
                   or governance[name] <= 0 for name in
                   ("observation_ttl_ms", "standing_ttl_ms", "docket_standing_ttl_ms")) \
            or any(governance[name] > 300000 for name in
                   ("observation_ttl_ms", "standing_ttl_ms", "docket_standing_ttl_ms")) \
            or governance["docket_standing_ttl_ms"] != 60000:
        raise ValueError("governance value differs")
    return config


def run(argv: list[str]) -> bytes:
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        completed = subprocess.run(argv, stdout=stdout, stderr=stderr, timeout=8, check=False)
        if stdout.tell() > 1024 * 1024 or stderr.tell() > 1024 * 1024:
            raise ValueError("configuration command output exceeded bound")
        stdout.seek(0)
        stderr.seek(0)
        output, error = stdout.read(), stderr.read()
    if completed.returncode:
        raise ValueError(f"configuration command refused with exit {completed.returncode}: "
                         + error.decode("utf-8", "replace")[:256])
    return output


def expected_host_scope_digest(nq_program: str, subject: str, scope_id: str) -> str:
    profiles = json.loads(run([nq_program, "--json", "profiles", "list"]))
    matches = [item for item in profiles if isinstance(item, dict) and item.get("id") == "nq.host"]
    if len(matches) != 1 or set(matches[0]) != {"digest", "family", "id", "title", "version"} \
            or matches[0]["family"] != "host" or matches[0]["version"] != 1 \
            or not is_digest(matches[0]["digest"]):
        raise ValueError("pinned NQ does not expose the exact nq.host/v1 descriptor")
    descriptor = {
        "schema": "nq.diagnostic_scope.v1", "subject": subject,
        "scope": {"kind": "host", "value": {"id": scope_id}},
        "profile": {"id": "nq.host", "version": "1", "digest": matches[0]["digest"]},
    }
    return "sha256:" + hashlib.sha256(canonical(descriptor)).hexdigest()


def write_new(path: Path, data: bytes, mode: int = 0o600) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def prepare(config: dict) -> dict:
    validate(config)
    enrolled = {}
    for name, item in config["programs"].items():
        path = Path(item["path"])
        if file_digest(path) != item["sha256"] or not os.access(path, os.X_OK):
            raise ValueError(f"program {name} bytes or executable mode differ")
        enrolled[name] = {"path": str(path), "sha256": item["sha256"]}
    pulse_launcher_sealer = Path(config["files"]["pulse_launcher_sealer"]["path"])
    if file_digest(pulse_launcher_sealer) != config["files"]["pulse_launcher_sealer"]["sha256"]:
        raise ValueError("Pulse launcher sealer bytes differ")
    source = Path(config["maude"]["source"])
    build_plan = source / "qualification/synthetic_cache/build_plan.py"
    executor = source / "qualification/synthetic_cache/local_compose_executor.py"
    if file_digest(build_plan) != config["maude"]["build_plan_sha256"] \
            or file_digest(executor) != config["maude"]["executor_sha256"]:
        raise ValueError("Maude public utility bytes differ")
    expected_scope = expected_host_scope_digest(
        enrolled["nq"]["path"], config["nq"]["subject"], config["nq"]["scope_id"]
    )
    if config["identities"]["scope_digest"] != expected_scope:
        raise ValueError("caller scope digest differs from the pinned NQ host artifact identity")
    if enrolled["docker"]["path"] != str(Path(enrolled["docker"]["path"])):
        raise ValueError("Docker path differs")

    root = Path(config["root"])
    root.mkdir(mode=0o700)
    for name in ("credentials", "governance", "nq", "runtime", "records"):
        (root / name).mkdir(mode=0o700)
    session_key, producer_key = root / "credentials/maude-session.key", root / "credentials/maude-producer.key"
    write_new(session_key, secrets.token_bytes(32))
    write_new(producer_key, secrets.token_bytes(32))

    catalog = root / "governance/exact-work-catalog.json"
    ids = config["identities"]
    write_new(catalog, canonical({
        "entries": {"maude.local-compose-workflow/v1": {
            "precondition": {"forbidden": [], "required": ["condition.clean"]},
            "scope": ids["scope_digest"], "subject": ids["subject_digest"],
            "work_schema": "maude.local-compose-workflow/v1",
        }}, "schema": "ag.governed-loop.exact-work-catalog/v1",
    }))

    nq_args = argparse.Namespace(
        output=root / "nq/nq-host.toml", state_root=root / "nq/state",
        helper=Path(enrolled["nq_host_helper"]["path"]),
        working_directory=Path(config["nq"]["working_directory"]),
        instance=ids["watcher_instance_id"], execution_account=config["nq"]["execution_account"],
        subject=config["nq"]["subject"], scope_id=config["nq"]["scope_id"],
        allow_same_identity_in_debug=config["nq"]["allow_same_identity_in_debug"],
    )
    nq_result = NQ_HOST.prepare(nq_args)

    gov = config["governance"]
    gov_config = {
        "schema": GOVERNANCE.SCHEMA, "output_root": str(root / "governance/runtime"),
        "programs": {
            "ag": enrolled["ag"], "docket": enrolled["docket"],
            "executor_adapter": {"path": str(executor), "sha256": config["maude"]["executor_sha256"]},
            "nightshift_observation_resolver": enrolled["nightshift_observation_resolver"],
            "ag_standing_resolver": enrolled["ag_standing_resolver"],
            "openssl": enrolled["openssl"],
        },
        "catalog": {"path": str(catalog), "sha256": file_digest(catalog)},
        "identities": {name: gov[name] for name in
                       ("profile_label", "observation_resolver_id", "standing_resolver_id",
                        "issuer_principal", "issuer_key_id")},
        "limits": {name: gov[name] for name in
                   ("observation_ttl_ms", "standing_ttl_ms", "docket_standing_ttl_ms")},
    }
    governance_result = GOVERNANCE.build(gov_config)
    enrollment = Path(governance_result["enrollment"])
    profile = root / "governance/runtime-profile.json"
    ag = enrolled["ag"]["path"]
    seal = run([ag, "seal-runtime-profile", "--enrollment", str(enrollment), "--output", str(profile)])
    receipt = root / "governance/runtime-profile-seal-receipt.json"
    write_new(receipt, seal)
    verified = run([ag, "verify-runtime-profile", "--runtime-profile", str(profile)])
    if json.loads(seal) != json.loads(verified):
        raise ValueError("AG runtime-profile seal and verification receipts differ")

    runtime = config["runtime"]
    def coordinate(path: Path) -> dict:
        return {"path": str(path), "sha256": file_digest(path)}
    context = {
        "schema": CONTEXT_SCHEMA, "root": str(root), "programs": enrolled,
        "files": {
            "maude_source": {"path": str(source),
                             "declared_revision": config["maude"]["source_revision"]},
            "maude_build_plan": coordinate(build_plan), "maude_executor": coordinate(executor),
            "nq_config": coordinate(Path(nq_result["nq_config"])), "ag_catalog": coordinate(catalog),
            "ag_enrollment": coordinate(enrollment), "ag_profile": coordinate(profile),
            "ag_seal_receipt": coordinate(receipt),
            "observation_resolver": coordinate(root / "governance/runtime/observation-resolver.sh"),
            "standing_resolver": coordinate(root / "governance/runtime/standing-resolver.sh"),
            "docket_standing_resolver": coordinate(root / "governance/runtime/docket-standing.py"),
            "docket_trust": coordinate(root / "governance/runtime/docket-trust.json"),
            "pulse_launcher_sealer": coordinate(pulse_launcher_sealer),
        },
        "credentials": {"maude_session": str(session_key),
                        "maude_producer": str(producer_key),
                        "ag_issuer": str(root / "governance/runtime/issuer.pk8")},
        "identities": ids,
        "runtime": {**runtime, "runtime_root": str(root / "runtime"),
                    "workspace": str(root / "runtime" / runtime["project"])},
        "nq": {"initialized": False, "subject": config["nq"]["subject"],
               "scope_id": config["nq"]["scope_id"],
               "expected_artifact_scope_digest": expected_scope,
               "runner_must_match_artifact_subject_scope": True},
        "governance": {"sealed_verified": True, "standing_kind": "synthetic_fixture",
                       "mandate_store_initially_empty": True, "authority": "none"},
        "state": {"prepared": True, "effects": False, "state_paths": {
            "nightshift_store": str(root / "governance/runtime/nightshift.sqlite"),
            "ag_database": str(root / "governance/ag.sqlite"),
            "docket_directory": str(root / "governance/runtime/docket-state"),
            "maude_store": str(root / "maude-custody.sqlite"),
            "mandate_store": str(root / "governance/runtime/synthetic-mandates.json"),
        }},
    }
    context_path = root / "context.json"
    write_new(context_path, canonical(context))
    return context


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--config", type=Path, required=True)
    return result


def main() -> None:
    args = parser().parse_args()
    config = json.loads(read_regular(args.config, MAX_CONFIG))
    print(json.dumps(prepare(config), sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
