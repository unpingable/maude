#!/usr/bin/env python3
"""Prepare or run the real host-input bootstrap without cache effects or AG.

The four explicit phases keep NQ acquisition/history, Pulse custody, and the
Nightshift posture-only cycle distinct. Output paths are create-only.  The
script never reads a Pulse signing key and never constructs semantic IDs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

MAX_OUTPUT = 16 * 1024 * 1024
HOST_PROFILE = "nq.host"
LOAD_QUESTION = "nq.host.load_pressure"
PULSE_CONFIG_SCHEMA = "pulse.nq_host_load_pressure_support_config.v1"
PULSE_FAMILY = "pulse.nq_host_load_pressure.v1"


def fail(message: str) -> "NoReturn":
    raise ValueError(message)


def read_json(path: Path) -> dict:
    if not path.is_absolute() or not path.is_file() or path.is_symlink():
        fail(f"input must be an absolute, regular, non-symlink path: {path}")
    raw = path.read_bytes()
    if not raw or len(raw) > MAX_OUTPUT:
        fail(f"input is empty or exceeds {MAX_OUTPUT} bytes: {path}")
    value = json.loads(raw)
    if not isinstance(value, dict):
        fail(f"input must contain one JSON object: {path}")
    return value


def write_new(path: Path, data: bytes) -> None:
    if not path.is_absolute():
        fail(f"output must be absolute: {path}")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def canonical(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def run(argv: list[str], *, env: dict[str, str] | None = None, stdin: bytes | None = None) -> bytes:
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        completed = subprocess.run(
            argv, input=stdin, stdout=stdout, stderr=stderr, env=env,
            check=False, timeout=60,
        )
        if stdout.tell() > MAX_OUTPUT or stderr.tell() > MAX_OUTPUT:
            fail("command output exceeded the bounded bootstrap limit")
        stdout.seek(0); stderr.seek(0)
        out = stdout.read(); error = stderr.read()
    if completed.returncode:
        fail(f"command refused with exit {completed.returncode}: " + error.decode("utf-8", "replace").strip())
    return out


def require_program(path: Path, basename: str) -> str:
    if not path.is_absolute() or path.name != basename:
        fail(f"expected exact {basename} executable path")
    resolved = path.resolve(strict=True)
    if not resolved.is_file():
        fail(f"expected exact {basename} executable path")
    return str(path)


def artifact_shape(artifact: dict) -> tuple[str, str]:
    if artifact.get("schema") != "nq.diagnostic_execution.v2":
        fail("NQ artifact is not diagnostic execution v2")
    if artifact.get("profile", {}).get("id") != HOST_PROFILE:
        fail("NQ artifact is not nq.host")
    if artifact.get("question", {}).get("id") != LOAD_QUESTION:
        fail("NQ artifact is not the host-load proposition")
    semantic = artifact.get("profile_semantic_id")
    artifact_id = artifact.get("artifact_id")
    for name, value in (("profile_semantic_id", semantic), ("artifact_id", artifact_id)):
        if not isinstance(value, str) or not value.startswith("sha256:") or len(value) != 71:
            fail(f"invalid {name}")
    return semantic, artifact_id


def object_id(value: dict, field: str) -> str:
    preimage = dict(value); preimage.pop(field, None)
    return "sha256:" + hashlib.sha256(canonical(preimage)).hexdigest()


def construct(args: argparse.Namespace) -> None:
    """Construct the closed host-only request; Nightshift remains its validator."""
    artifact = read_json(args.artifact)
    semantic, artifact_id = artifact_shape(artifact)
    claims = artifact.get("claims")
    primary_id = artifact.get("primary_claim_id")
    if not isinstance(claims, list) or not isinstance(primary_id, str):
        fail("initial host posture requires a primary claim")
    claim = next((item for item in claims if item.get("claim_id") == primary_id), None)
    if claim is None:
        fail("primary claim is absent")
    subject = artifact["subject"]
    key = {"profile_id": artifact["profile"]["id"], "question_id": artifact["question"]["id"],
           "subject_id": subject["id"], "vantage_id": artifact["vantage"]["id"]}
    binding = {
        "producer_node_id": artifact["producer"]["node_id"], "producer_build": artifact["producer"]["build"],
        "producer_cohort": artifact["producer"]["cohort"], "question": artifact["question"],
        "profile": artifact["profile"], "profile_semantic_id": semantic, "vantage": artifact["vantage"],
        "state_model": artifact["state_model"], "evaluator": artifact["evaluator"],
        "threshold_policy": artifact["threshold_policy"], "projection": artifact["projection"],
        "subject": subject, "claim_id": primary_id,
    }
    state_by_id = {item["binding_id"]: item for item in artifact.get("state_bindings", [])}
    required = [{"kind": state_by_id[item]["kind"], "value": state_by_id[item]["value"]}
                for item in claim.get("state_binding_ids", []) if item in state_by_id]
    required.sort(key=lambda item: (item["kind"], item["value"]))
    role = {"id": args.role_id, "version": args.role_version, "digest": args.role_digest}
    policy = {"schema": "nightshift.diagnostic_posture_policy.v2", "policy_id": "",
              "generation": args.generation, "subject": subject, "role": role,
              "delivery_required": False, "inventory": [{"binding": binding, "requirement": "mandatory",
              "required_state_bindings": required, "max_age_seconds": args.max_age_seconds}]}
    policy["policy_id"] = object_id(policy, "policy_id")
    inputs = {"schema": "nightshift.diagnostic_inputs.v2", "inputs_id": "",
              "inputs": [{"key": key, "status": "delivered", "artifact": artifact}]}
    inputs["inputs_id"] = object_id(inputs, "inputs_id")
    schedule = {"schedule_id": args.schedule_id, "first_due_at": artifact["started_at"],
                "cadence_seconds": args.cadence_seconds, "jitter_bound_seconds": 0,
                "max_execution_budget_seconds": args.execution_budget_seconds,
                "standing_window_seconds": args.max_age_seconds}
    run_slot = {"slot_id": "", "schedule_id": args.schedule_id, "occurrence": 0, "key": key,
                "due_at": artifact["started_at"], "budget_seconds": args.execution_budget_seconds}
    run_slot["slot_id"] = object_id(run_slot, "slot_id")
    dependency_ids = set(claim.get("dependency_input_ids", []))
    dependencies = [item["acquisition"] for item in artifact["inputs"].get("received", [])
                    if item.get("input_id") in dependency_ids]
    artifact_ref = {"contract_schema": artifact["schema"], "profile_semantic_id": semantic,
                    "artifact_id": artifact_id, "request_id": artifact["request_id"],
                    "run_id": artifact["run_id"], "attempt_interval": artifact["attempt_interval"],
                    "key": key, "claim_id": primary_id, "claim": claim,
                    "dependency_acquisitions": dependencies}
    recurrence = {"schema": "nightshift.recurrence_evidence.v2", "recurrence_id": "",
                  "obligations": [{"key": key, "policy": schedule}],
                  "records": [{"key": key, "policy": schedule, "slot": run_slot,
                    "evidence": {"kind": "completed", "attempt": {"attempt_id": args.attempt_id,
                    "slot_id": run_slot["slot_id"], "request_id": artifact["request_id"],
                    "started_at": artifact["started_at"]}, "completed_at": artifact["completed_at"],
                    "artifact": artifact_ref}}], "delivery": "not_required"}
    recurrence["recurrence_id"] = object_id(recurrence, "recurrence_id")
    slot = {"schema": "nightshift.recurrence_slot.v1", "slot_id": "", "policy_id": policy["policy_id"],
            "configuration_version": args.configuration_version, "subject_id": subject["id"],
            "scope_id": subject["scope"]["digest"], "scheduler_clock_id": args.scheduler_clock_id,
            "nominal_due_at": artifact["completed_at"], "latest_admissible": {
            "scheduler_clock_id": args.scheduler_clock_id, "at": artifact["completed_at"]},
            "occurrence": args.occurrence, "trigger": "manual"}
    slot["slot_id"] = object_id(slot, "slot_id")
    request = {"schema": "nightshift.canonical_cycle_request.v1", "request_id": "", "slot": slot,
               "scheduler_clock_id": args.scheduler_clock_id, "evaluated_at": artifact["completed_at"],
               "observation_id": "sha256:" + hashlib.sha256(canonical({"artifact_id": artifact_id})).hexdigest(),
               "policy": policy, "inputs": inputs, "recurrence": recurrence}
    request["request_id"] = object_id(request, "request_id")
    write_new(args.cycle_request_out, canonical(request))


def acquire(args: argparse.Namespace) -> None:
    if args.artifact_out.exists() or args.provenance_out.exists():
        fail("acquire outputs must be fresh before NQ history is changed")
    nq = require_program(args.nq, "nq")
    config = str(args.nq_config.resolve(strict=True))
    artifact_bytes = run([nq, "--config", config, "diagnostics", "execute", args.instance])
    artifact = json.loads(artifact_bytes)
    _, artifact_id = artifact_shape(artifact)
    exported = run([nq, "--config", config, "diagnostics", "export", artifact_id])
    if exported != artifact_bytes:
        fail("local-history export bytes differ from execute output")
    provenance = run([nq, "--config", config, "--json", "diagnostics", "qualify", artifact_id])
    json.loads(provenance)
    write_new(args.artifact_out, artifact_bytes)
    write_new(args.provenance_out, provenance)


def bind(args: argparse.Namespace) -> None:
    artifact = read_json(args.artifact)
    semantic, artifact_id = artifact_shape(artifact)
    request = read_json(args.cycle_request)
    if request.get("schema") != "nightshift.canonical_cycle_request.v1" or request.get("proposal") is not None:
        fail("cycle request must be sealed posture-only v1 with no proposal")
    inventory = request.get("policy", {}).get("inventory")
    inputs = request.get("inputs", {})
    if not isinstance(inventory, list) or len(inventory) != 1:
        fail("Nightshift policy must contain exactly one host inventory entry")
    binding = inventory[0].get("binding", {})
    if binding.get("profile", {}).get("id") != HOST_PROFILE or binding.get("question", {}).get("id") != LOAD_QUESTION:
        fail("Nightshift policy is not host-load-only")
    if binding.get("profile_semantic_id") != semantic:
        fail("Nightshift profile semantic ID does not match the NQ artifact")
    rows = inputs.get("inputs")
    if not isinstance(rows, list) or len(rows) != 1 or rows[0].get("artifact", {}).get("artifact_id") != artifact_id:
        fail("Nightshift inputs do not contain exactly the acquired NQ artifact")
    template = read_json(args.pulse_template)
    if template.get("schema") != PULSE_CONFIG_SCHEMA or template.get("support_family") != PULSE_FAMILY:
        fail("unsupported Pulse configuration template")
    if template.get("profile_semantic_id") != semantic:
        fail("Pulse profile semantic ID does not match the NQ artifact")
    if template.get("subject_id") != artifact["subject"]["id"] or template.get("scope_id") != artifact["subject"]["scope"]["digest"]:
        fail("Pulse subject/scope does not match the NQ artifact")
    template["expected_diagnostic"] = {
        "diagnostic_inputs_id": inputs.get("inputs_id"),
        "artifact_ids": [artifact_id],
        "expected_state": artifact.get("outcome", {}).get("condition"),
    }
    write_new(args.pulse_config_out, canonical(template))


def support(args: argparse.Namespace) -> None:
    pulse = require_program(args.pulse, "pulse-nq-load-support")
    config_path = args.pulse_config.resolve(strict=True)
    config_value = read_json(config_path)
    for field in ("outgoing_directory", "receipt_directory"):
        directory = Path(config_value.get(field, ""))
        if not directory.is_absolute() or not directory.is_dir() or any(directory.iterdir()):
            fail(f"initial Pulse {field} must be an existing empty absolute directory")
    config = str(config_path)
    run([pulse, "produce", "--config", config, "--acquisition-id", args.acquisition_id])
    run([pulse, "ingest", "--config", config, "--acquisition-id", args.acquisition_id])


def cycle(args: argparse.Namespace) -> None:
    if args.store.exists() or args.result_out.exists():
        fail("posture-only cycle store and result must be fresh")
    nightshift = require_program(args.nightshift, "nightshift")
    nq = require_program(args.nq, "nq")
    resolver = require_program(args.resolver, "pulse-support-resolver")
    env = dict(os.environ)
    env["PULSE_LOAD_SUPPORT_CONFIG"] = str(args.pulse_config.resolve(strict=True))
    output = run([
        nightshift, "--store", str(args.store), "cycle", "run",
        "--request", str(args.cycle_request.resolve(strict=True)),
        "--present-evidence-resolver", resolver,
        "--nq-program", nq, "--nq-config", str(args.nq_config.resolve(strict=True)),
        "--nq-source-id", args.nq_source_id,
    ], env=env)
    write_new(args.result_out, output)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    p = commands.add_parser("acquire")
    p.add_argument("--nq", type=Path, required=True); p.add_argument("--nq-config", type=Path, required=True)
    p.add_argument("--instance", required=True); p.add_argument("--artifact-out", type=Path, required=True)
    p.add_argument("--provenance-out", type=Path, required=True); p.set_defaults(func=acquire)
    p = commands.add_parser("bind")
    p.add_argument("--artifact", type=Path, required=True); p.add_argument("--cycle-request", type=Path, required=True)
    p.add_argument("--pulse-template", type=Path, required=True); p.add_argument("--pulse-config-out", type=Path, required=True)
    p.set_defaults(func=bind)
    p = commands.add_parser("construct")
    p.add_argument("--artifact", type=Path, required=True); p.add_argument("--role-id", required=True)
    p.add_argument("--role-version", required=True); p.add_argument("--role-digest", required=True)
    p.add_argument("--generation", required=True); p.add_argument("--schedule-id", required=True)
    p.add_argument("--attempt-id", required=True); p.add_argument("--configuration-version", required=True)
    p.add_argument("--scheduler-clock-id", required=True); p.add_argument("--cycle-request-out", type=Path, required=True)
    p.add_argument("--max-age-seconds", type=int, default=300); p.add_argument("--cadence-seconds", type=int, default=300)
    p.add_argument("--execution-budget-seconds", type=int, default=30); p.set_defaults(func=construct)
    p.add_argument("--occurrence", type=int, default=0)
    p = commands.add_parser("support")
    p.add_argument("--pulse", type=Path, required=True); p.add_argument("--pulse-config", type=Path, required=True)
    p.add_argument("--acquisition-id", required=True); p.set_defaults(func=support)
    p = commands.add_parser("cycle")
    p.add_argument("--nightshift", type=Path, required=True); p.add_argument("--store", type=Path, required=True)
    p.add_argument("--cycle-request", type=Path, required=True); p.add_argument("--resolver", type=Path, required=True)
    p.add_argument("--pulse-config", type=Path, required=True); p.add_argument("--nq", type=Path, required=True)
    p.add_argument("--nq-config", type=Path, required=True); p.add_argument("--nq-source-id", required=True)
    p.add_argument("--result-out", type=Path, required=True); p.set_defaults(func=cycle)
    return result


def main() -> int:
    try:
        args = parser().parse_args()
        args.func(args)
        return 0
    except (ValueError, OSError, json.JSONDecodeError, subprocess.TimeoutExpired) as error:
        print(error, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
