# SPDX-License-Identifier: Apache-2.0
"""Closed read-only observation adapter for the synthetic local-Compose workflow.

The adapter performs fixed HTTP GETs and one fixed ``docker compose ps`` read.
It has no container lifecycle verb, configuration write, shell, Docket, AG, or
Nightshift-currentness surface.  It produces an authenticated candidate only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import hmac
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from maude.custody import _canonical, _read_exact_file, read_protected_key
from maude.plan.cross_probe import parse_cross_probe
from maude.plan.document import canonical_json_bytes, content_digest

EVIDENCE_SCHEMA_V1 = "maude.local-compose-steady-state-evidence/v1"
OBSERVATION_SCHEMA_V1 = "maude.local-compose-steady-state-observation/v1"
CLAIM_SCHEMA_V1 = "maude.local-compose-steady-state-claim/v1"
HANDOFF_SCHEMA_V1 = "nightshift.steady_state_observation_handoff.v1"
AUTH_SCHEMA_V1 = "maude.hmac_sha256.v1"
BASIS_SCHEMA_V1 = "nightshift.steady_state_reobservation_basis.v1"
PROFILE_SCHEMA_V1 = "nightshift.steady_state_evidence_profile.v1"
PLAN_SCHEMA_V1 = "maude.local-compose.docket-executor-plan/v1"
COMPILATION_SCHEMA_V1 = "maude.plan-compilation-receipt/v1"
ADAPTER_ID = "maude.local-compose-steady-state-observation-adapter"
ADAPTER_VERSION = "1"
EVIDENCE_DOMAIN = EVIDENCE_SCHEMA_V1
HANDOFF_AUTH_DOMAIN = b"nightshift-steady-state-observation-handoff/v1\0"
MAX_INPUT_BYTES = 16 * 1024 * 1024
MAX_OUTPUT_BYTES = 1024 * 1024

PASSIVE_HTTP_PROBE_SOURCE = """\
import hashlib,json,sys,urllib.request
base='http://127.0.0.1:8080'
def get(path):
    with urllib.request.urlopen(base+path,timeout=3) as response:
        body=response.read(65537)
        if len(body)>65536: raise RuntimeError('response bound')
        return {'status':response.status,'cache':response.headers.get('X-Cache'),'cache_node':response.headers.get('X-Cache-Node'),'front_backend':response.headers.get('X-Front-Backend'),'body_digest':'sha256:'+hashlib.sha256(body).hexdigest()}
nonce=sys.argv[1]
print(json.dumps({'front_door':get('/health'),'cache_behavior':{'requests':[get('/steady-'+nonce) for _ in range(4)]}},sort_keys=True,separators=(',',':')))
"""

NONCLAIMS = (
    "passive observation is not effectful qualification",
    "passive observation does not prove failure survival",
    "producer authentication is not currentness or authorization",
    "observation failure does not authorize remediation",
)


class SteadyStateObservationError(ValueError):
    """Fail-closed passive source, identity, or custody refusal."""


def _digest(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        raise SteadyStateObservationError(f"{name} must use sha256:<64 lowercase hex>")
    tail = value[7:]
    if len(tail) != 64 or any(
        character not in "0123456789abcdef" for character in tail
    ):
        raise SteadyStateObservationError(f"{name} must use sha256:<64 lowercase hex>")
    return value


def _token(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise SteadyStateObservationError(f"{name} must be a non-empty token")
    if any(character.isspace() for character in value):
        raise SteadyStateObservationError(f"{name} must be a non-empty token")
    return value


def _sha256(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _hash_domain(domain: str, payload: bytes) -> str:
    encoded = domain.encode()
    digest = hashlib.sha256()
    digest.update(b"ag-ng\0digest\0v1\0")
    digest.update(len(encoded).to_bytes(16, "big"))
    digest.update(encoded)
    digest.update(len(payload).to_bytes(16, "big"))
    digest.update(payload)
    return "sha256:" + digest.hexdigest()


def _object_id(value: dict[str, Any], field: str) -> str:
    preimage = dict(value)
    preimage.pop(field, None)
    return _sha256(_canonical(preimage))


def _semantic_id(value: dict[str, Any], field: str) -> str:
    preimage = dict(value)
    preimage.pop(field, None)
    preimage.pop("authentication", None)
    return _sha256(_canonical(preimage))


def _exact(path: Path, name: str) -> tuple[dict[str, Any], bytes]:
    raw = _read_exact_file(path, MAX_INPUT_BYTES, name)
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SteadyStateObservationError(f"malformed {name}") from error
    if not isinstance(value, dict) or _canonical(value) != raw:
        raise SteadyStateObservationError(f"{name} must be exact canonical JSON")
    return value, raw


def _timestamp(value: str) -> tuple[str, int]:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise SteadyStateObservationError("observed-at must be RFC3339 UTC")
    try:
        parsed = dt.datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise SteadyStateObservationError("observed-at must be RFC3339 UTC") from error
    if parsed.utcoffset() != dt.timedelta(0):
        raise SteadyStateObservationError("observed-at must be RFC3339 UTC")
    return value, int(parsed.timestamp() * 1000)


class PassiveProbe(Protocol):
    def acquire(self, plan: dict[str, Any], nonce: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class LocalComposePassiveProbe:
    docker_program: str = "docker"
    timeout_seconds: int = 10

    def acquire(self, plan: dict[str, Any], nonce: str) -> dict[str, Any]:
        workspace = Path(plan["workspace"])
        project = _token(plan.get("project_name"), "project_name")
        front_port = plan.get("front_port")
        if not workspace.is_absolute() or workspace.name != project:
            raise SteadyStateObservationError(
                "passive workspace/project binding failed"
            )
        if not isinstance(front_port, int) or not 1 <= front_port <= 65535:
            raise SteadyStateObservationError("front_port is invalid")
        compose = workspace / "compose.yaml"
        command = [
            self.docker_program,
            "compose",
            "--project-name",
            project,
            "--file",
            str(compose),
            "ps",
            "--format",
            "json",
        ]
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=self.timeout_seconds,
            check=False,
        )
        if completed.returncode != 0 or len(completed.stdout) > MAX_OUTPUT_BYTES:
            raise SteadyStateObservationError(
                "fixed docker compose ps observation failed"
            )
        try:
            decoded = json.loads(completed.stdout)
        except (UnicodeDecodeError, json.JSONDecodeError):
            try:
                lines = completed.stdout.decode("utf-8").splitlines()
                decoded = [json.loads(line) for line in lines if line]
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise SteadyStateObservationError(
                    "compose ps returned malformed JSON"
                ) from error
        rows = decoded if isinstance(decoded, list) else [decoded]
        services = {
            row.get("Service"): {
                "state": row.get("State"),
                "health": row.get("Health"),
            }
            for row in rows
            if isinstance(row, dict)
        }
        for service in ("cache-a", "cache-b", "front", "origin"):
            row = services.get(service)
            if not isinstance(row, dict) or row.get("state") != "running":
                raise SteadyStateObservationError(f"expected service absent: {service}")
        probe = subprocess.run(
            [
                self.docker_program,
                "compose",
                "--project-name",
                project,
                "--file",
                str(compose),
                "exec",
                "-T",
                "front",
                "python",
                "-c",
                PASSIVE_HTTP_PROBE_SOURCE,
                nonce,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=self.timeout_seconds,
            check=False,
        )
        if probe.returncode != 0 or len(probe.stdout) > MAX_OUTPUT_BYTES:
            raise SteadyStateObservationError("fixed passive HTTP observation failed")
        try:
            observations = json.loads(probe.stdout)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SteadyStateObservationError(
                "passive HTTP observation returned malformed JSON"
            ) from error
        if not isinstance(observations, dict):
            raise SteadyStateObservationError(
                "passive HTTP observation is not an object"
            )
        observations.update(
            {
                "cache_a": {"identity": "cache-a", **services["cache-a"]},
                "cache_b": {"identity": "cache-b", **services["cache-b"]},
            }
        )
        _validate_observations(observations)
        return observations


def _validate_observations(observations: dict[str, Any]) -> None:
    if set(observations) != {
        "front_door",
        "cache_a",
        "cache_b",
        "cache_behavior",
    }:
        raise SteadyStateObservationError("passive observation shape is not closed")
    front = observations.get("front_door")
    cache_a = observations.get("cache_a")
    cache_b = observations.get("cache_b")
    behavior = observations.get("cache_behavior")
    if not isinstance(front, dict) or front.get("status") != 200:
        raise SteadyStateObservationError("front door was not observed reachable")
    for expected, cache in (("cache-a", cache_a), ("cache-b", cache_b)):
        if (
            not isinstance(cache, dict)
            or cache.get("identity") != expected
            or cache.get("state") != "running"
        ):
            raise SteadyStateObservationError(
                f"expected passive cache identity absent: {expected}"
            )
    requests = behavior.get("requests") if isinstance(behavior, dict) else None
    if not isinstance(requests, list) or len(requests) != 4:
        raise SteadyStateObservationError("ordinary cache evidence is incomplete")
    sequence = tuple(
        (request.get("cache"), request.get("cache_node"))
        for request in requests
        if isinstance(request, dict)
    )
    if sequence not in {
        (
            ("MISS", "cache-a"),
            ("MISS", "cache-b"),
            ("HIT", "cache-a"),
            ("HIT", "cache-b"),
        ),
        (
            ("MISS", "cache-b"),
            ("MISS", "cache-a"),
            ("HIT", "cache-b"),
            ("HIT", "cache-a"),
        ),
    }:
        raise SteadyStateObservationError(
            "ordinary cache evidence contradicted profile"
        )


def build_observation(
    *,
    basis: dict[str, Any],
    plan: dict[str, Any],
    compilation: dict[str, Any],
    governed_bindings: dict[str, Any],
    observations: dict[str, Any],
    observed_at_unix_ms: int,
) -> dict[str, Any]:
    _validate_observations(observations)
    if basis.get("schema") != BASIS_SCHEMA_V1 or basis.get("requirement") not in {
        "absent",
        "stale",
    }:
        raise SteadyStateObservationError(
            "Nightshift basis does not require passive acquisition"
        )
    if (
        plan.get("schema") != PLAN_SCHEMA_V1
        or compilation.get("schema") != COMPILATION_SCHEMA_V1
    ):
        raise SteadyStateObservationError("unsupported local-Compose source contract")
    if (
        basis.get("plan_document_digest") != compilation.get("plan_digest")
        or basis.get("compilation_id") != compilation.get("compilation_id")
        or basis.get("exact_work_id") != compilation.get("exact_work_identity")
        or plan.get("plan_document_digest") != compilation.get("plan_digest")
        or basis.get("subject_digest") != plan.get("subject_digest")
        or basis.get("scope_digest") != plan.get("scope_digest")
    ):
        raise SteadyStateObservationError("basis/compiler/plan exact binding failed")
    bindings = {
        binding.node_id: binding.compiled_output_identity
        for items in parse_cross_probe(governed_bindings).values()
        for binding in items
        if binding.compilation_id == compilation.get("compilation_id")
    }
    specs = (
        ("front_door_reachable", "pn_health", "/observations/front_door"),
        ("cache_a_present", "pn_cache_a", "/observations/cache_a"),
        ("cache_b_present", "pn_cache_b", "/observations/cache_b"),
        (
            "ordinary_cache_behavior_observed",
            "pn_cache_behavior",
            "/observations/cache_behavior",
        ),
    )
    missing = sorted({node for _, node, _ in specs} - set(bindings))
    if missing:
        raise SteadyStateObservationError(
            "compilation lacks passive PlanNode bindings: " + ",".join(missing)
        )
    source = {
        "schema": EVIDENCE_SCHEMA_V1,
        "qualification_observation_id": _digest(
            basis.get("qualification_observation_id"), "qualification_observation_id"
        ),
        "observed_at_unix_ms": observed_at_unix_ms,
        "observations": observations,
    }
    source_bytes = canonical_json_bytes(source)
    claims = []
    for kind, node, path in specs:
        claim = {
            "schema": CLAIM_SCHEMA_V1,
            "claim_id": "",
            "kind": kind,
            "status": "satisfied",
            "plan_node_id": node,
            "compiled_output_identity": bindings[node],
            "evidence_paths": [path],
        }
        claim["claim_id"] = _object_id(claim, "claim_id")
        claims.append(claim)
    observation = {
        "schema": OBSERVATION_SCHEMA_V1,
        "observation_id": "",
        "adapter_id": ADAPTER_ID,
        "adapter_version": ADAPTER_VERSION,
        "qualification_observation_id": basis["qualification_observation_id"],
        "plan_document_digest": basis["plan_document_digest"],
        "compilation_id": basis["compilation_id"],
        "campaign_id": basis["campaign_id"],
        "occurrence_id": basis["occurrence_id"],
        "proposal_id": basis["proposal_id"],
        "exact_work_id": basis["exact_work_id"],
        "issuance_id": basis["issuance_id"],
        "attempt_id": basis["attempt_id"],
        "settlement_id": basis["settlement_id"],
        "subject_digest": basis["subject_digest"],
        "scope_digest": basis["scope_digest"],
        "evidence_receipt": _hash_domain(EVIDENCE_DOMAIN, source_bytes),
        "evidence_bytes": len(source_bytes),
        "observed_at_unix_ms": observed_at_unix_ms,
        "source_evidence": source,
        "claims": claims,
        "nonclaims": list(NONCLAIMS),
    }
    observation["observation_id"] = _object_id(observation, "observation_id")
    return observation


def seal_handoff(
    observation: dict[str, Any],
    *,
    producer_principal_id: str,
    producer_key_id: str,
    target_runtime_id: str,
    producer_key: bytes,
    created_at: str,
) -> dict[str, Any]:
    handoff = {
        "schema": HANDOFF_SCHEMA_V1,
        "handoff_id": "",
        "producer_principal_id": _token(producer_principal_id, "producer_principal_id"),
        "producer_key_id": _token(producer_key_id, "producer_key_id"),
        "target_runtime_id": _token(target_runtime_id, "target_runtime_id"),
        "observation": observation,
        "created_at": created_at,
        "authentication": {
            "schema": AUTH_SCHEMA_V1,
            "key_id": producer_key_id,
            "tag": "",
        },
    }
    handoff["handoff_id"] = _semantic_id(handoff, "handoff_id")
    unsigned = dict(handoff)
    unsigned.pop("authentication")
    tag = hmac.new(
        producer_key,
        HANDOFF_AUTH_DOMAIN + _canonical(unsigned),
        hashlib.sha256,
    ).hexdigest()
    handoff["authentication"]["tag"] = "hmac-sha256:" + tag
    return handoff


def acquire_handoff(
    *,
    basis: dict[str, Any],
    plan: dict[str, Any],
    compilation: dict[str, Any],
    governed_bindings: dict[str, Any],
    observed_at: str,
    probe: PassiveProbe,
    producer_principal_id: str,
    producer_key_id: str,
    target_runtime_id: str,
    producer_key: bytes,
) -> bytes:
    created_at, observed_at_ms = _timestamp(observed_at)
    nonce = content_digest(
        canonical_json_bytes(
            {
                "basis_id": basis.get("basis_id"),
                "observed_at_unix_ms": observed_at_ms,
            }
        )
    )[7:23]
    observations = probe.acquire(plan, nonce)
    observation = build_observation(
        basis=basis,
        plan=plan,
        compilation=compilation,
        governed_bindings=governed_bindings,
        observations=observations,
        observed_at_unix_ms=observed_at_ms,
    )
    return canonical_json_bytes(
        seal_handoff(
            observation,
            producer_principal_id=producer_principal_id,
            producer_key_id=producer_key_id,
            target_runtime_id=target_runtime_id,
            producer_key=producer_key,
            created_at=created_at,
        )
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only local-Compose observation adapter"
    )
    parser.add_argument("--basis", type=Path, required=True)
    parser.add_argument("--executor-plan", type=Path, required=True)
    parser.add_argument("--compilation-receipt", type=Path, required=True)
    parser.add_argument("--governed-bindings", type=Path, required=True)
    parser.add_argument("--observed-at", required=True)
    parser.add_argument("--producer-key", type=Path, required=True)
    parser.add_argument("--producer-principal-id", required=True)
    parser.add_argument("--producer-key-id", required=True)
    parser.add_argument("--target-runtime-id", required=True)
    parser.add_argument("--docker-program", default="docker")
    return parser


def main() -> int:
    args = _parser().parse_args()
    basis, _ = _exact(args.basis, "Nightshift re-observation basis")
    plan, _ = _exact(args.executor_plan, "executor plan")
    compilation, _ = _exact(args.compilation_receipt, "compilation receipt")
    bindings, _ = _exact(args.governed_bindings, "governed bindings")
    result = acquire_handoff(
        basis=basis,
        plan=plan,
        compilation=compilation,
        governed_bindings=bindings,
        observed_at=args.observed_at,
        probe=LocalComposePassiveProbe(args.docker_program),
        producer_principal_id=args.producer_principal_id,
        producer_key_id=args.producer_key_id,
        target_runtime_id=args.target_runtime_id,
        producer_key=read_protected_key(args.producer_key),
    )
    print(result.decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
