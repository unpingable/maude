#!/usr/bin/env python3
"""Closed Docket executor for the disposable local cache qualification.

The adapter accepts no commands from PlanDocument prose or from the Docket
dispatch.  Its exact config selects one of two finite mechanics: qualify the
pinned cache topology, or tear down that exact Compose project.  Reconciliation
is observation-only and never repeats mechanics.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

PLAN_SCHEMA = "maude.local-compose.docket-executor-plan/v1"
WORK_SCHEMA = "maude.local-compose-workflow/v1"
PLAN_DOMAIN = "ag-effectd.docket-executor-plan/v1"
EVIDENCE_DOMAIN = "maude.local-compose.executor-evidence/v1"
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_PROJECT = re.compile(r"^maude-cache-[a-z0-9][a-z0-9-]{0,39}$")
MAX_CONFIG = 2 * 1024 * 1024
MAX_RESPONSE = 64 * 1024

PROBE_SOURCE = r"""import hashlib,json,sys,urllib.request
with urllib.request.urlopen(sys.argv[1],timeout=15) as response:
    body=response.read(65537)
    if len(body)>65536:
        raise RuntimeError("response_too_large")
    value={
        "body_sha256":"sha256:"+hashlib.sha256(body).hexdigest(),
        "cache":response.headers.get("X-Cache"),
        "cache_node":response.headers.get("X-Cache-Node"),
        "front_backend":response.headers.get("X-Front-Backend"),
        "origin_count":response.headers.get("X-Origin-Count"),
        "status":response.status,
    }
    sys.stdout.write(json.dumps(value,sort_keys=True,separators=(",",":")))
"""


class Refusal(RuntimeError):
    pass


class AcceptanceFailure(RuntimeError):
    pass


def canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def hash_domain(domain: str, payload: bytes) -> str:
    encoded = domain.encode("utf-8")
    digest = hashlib.sha256()
    digest.update(b"ag-ng\0digest\0v1\0")
    digest.update(len(encoded).to_bytes(16, "big"))
    digest.update(encoded)
    digest.update(len(payload).to_bytes(16, "big"))
    digest.update(payload)
    return "sha256:" + digest.hexdigest()


def strict_file(path: Path, maximum: int) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > maximum:
            raise Refusal("config_not_bounded_regular_file")
        data = b""
        while len(data) <= maximum:
            chunk = os.read(descriptor, min(64 * 1024, maximum + 1 - len(data)))
            if not chunk:
                break
            data += chunk
        if len(data) > maximum:
            raise Refusal("config_too_large")
        return data
    finally:
        os.close(descriptor)


def closed(value: dict[str, Any], expected: set[str], where: str) -> None:
    if set(value) != expected:
        raise Refusal(f"{where}_fields")


def digest(value: object, where: str) -> str:
    if not isinstance(value, str) or not _DIGEST.fullmatch(value):
        raise Refusal(f"{where}_digest")
    return value


def load_plan(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = strict_file(path, MAX_CONFIG)
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise Refusal("config_json") from error
    if not isinstance(value, dict) or canonical(value) != raw:
        raise Refusal("config_not_exact_canonical_json")
    closed(
        value,
        {
            "action",
            "artifacts",
            "compiler",
            "docker",
            "image",
            "node_actions",
            "plan_document_digest",
            "project_name",
            "front_port",
            "schema",
            "scope_digest",
            "subject_digest",
            "workspace",
        },
        "plan",
    )
    if value["schema"] != PLAN_SCHEMA or value["action"] not in {"qualify", "teardown"}:
        raise Refusal("plan_schema_or_action")
    digest(value["plan_document_digest"], "plan_document")
    digest(value["scope_digest"], "scope")
    digest(value["subject_digest"], "subject")
    project = value["project_name"]
    if not isinstance(project, str) or not _PROJECT.fullmatch(project):
        raise Refusal("project_name")
    workspace = Path(value["workspace"])
    if not workspace.is_absolute() or workspace.name != project:
        raise Refusal("workspace_binding")
    if value["front_port"] != 8080:
        raise Refusal("front_port")
    compiler = value["compiler"]
    docker = value["docker"]
    if not isinstance(compiler, dict) or not isinstance(docker, dict):
        raise Refusal("plan_nested_objects")
    closed(compiler, {"id", "inputs_digest", "version"}, "compiler")
    closed(
        docker,
        {
            "client_version",
            "compose_version",
            "program",
            "program_identity",
            "server_version",
        },
        "docker",
    )
    digest(compiler["inputs_digest"], "compiler_inputs")
    digest(docker["program_identity"], "docker_program")
    if not isinstance(value["artifacts"], list) or not value["artifacts"]:
        raise Refusal("artifacts")
    expected_paths = {"cache.py", "compose.yaml", "front.py", "origin.py"}
    observed_paths: set[str] = set()
    for artifact in value["artifacts"]:
        if not isinstance(artifact, dict):
            raise Refusal("artifact_object")
        closed(artifact, {"content_sha256", "content_utf8", "path"}, "artifact")
        relative = artifact["path"]
        if relative not in expected_paths or relative in observed_paths:
            raise Refusal("artifact_path")
        observed_paths.add(relative)
        content = artifact["content_utf8"]
        if not isinstance(content, str) or "\x00" in content:
            raise Refusal("artifact_content")
        if sha256(content.encode("utf-8")) != artifact["content_sha256"]:
            raise Refusal("artifact_digest")
    if observed_paths != expected_paths:
        raise Refusal("artifact_census")
    if not isinstance(value["node_actions"], list) or not value["node_actions"]:
        raise Refusal("node_actions")
    return value, raw


def exact_plan_id(plan_bytes: bytes) -> str:
    return hash_domain(PLAN_DOMAIN, plan_bytes)


def docker_environment(workspace: Path) -> dict[str, str]:
    config = workspace / ".docker"
    config.mkdir(mode=0o700, parents=True, exist_ok=True)
    return {
        "DOCKER_CONFIG": str(config),
        "HOME": str(workspace),
        "LANG": "C.UTF-8",
        "PATH": "/usr/bin:/bin:/snap/bin",
    }


def run(
    program: str,
    arguments: list[str],
    workspace: Path,
    *,
    timeout: int = 120,
) -> subprocess.CompletedProcess[bytes]:
    completed = subprocess.run(
        [program, *arguments],
        cwd=workspace,
        env=docker_environment(workspace),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", "replace")[-1000:]
        raise Refusal(f"docker_refused:{arguments!r}:{detail}")
    return completed


def verify_docker(plan: dict[str, Any], workspace: Path) -> str:
    docker = plan["docker"]
    program = Path(docker["program"])
    if not program.is_absolute():
        raise Refusal("docker_program_not_absolute")
    resolved = program.resolve(strict=True)
    if (
        not resolved.is_file()
        or sha256(resolved.read_bytes()) != docker["program_identity"]
    ):
        raise Refusal("docker_program_identity_changed")
    version = (
        run(
            str(program),
            ["version", "--format", "{{.Client.Version}} {{.Server.Version}}"],
            workspace,
        )
        .stdout.decode("utf-8")
        .strip()
    )
    expected = f"{docker['client_version']} {docker['server_version']}"
    if version != expected:
        raise Refusal("docker_version_changed")
    compose = (
        run(str(program), ["compose", "version", "--short"], workspace)
        .stdout.decode("utf-8")
        .strip()
    )
    if compose != docker["compose_version"]:
        raise Refusal("compose_version_changed")
    run(str(program), ["image", "inspect", plan["image"]], workspace)
    return str(program)


def write_artifacts(plan: dict[str, Any], workspace: Path) -> None:
    if workspace.exists():
        raise Refusal("qualify_workspace_already_exists_without_receipt")
    parent = workspace.parent
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if parent.is_symlink() or not parent.is_dir():
        raise Refusal("workspace_parent_not_directory")
    # Generated programs are immutable world-readable inputs for the explicit
    # non-root container user; the containing campaign root remains dedicated.
    workspace.mkdir(mode=0o755)
    for artifact in plan["artifacts"]:
        path = workspace / artifact["path"]
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        try:
            data = artifact["content_utf8"].encode("utf-8")
            view = memoryview(data)
            while view:
                view = view[os.write(descriptor, view) :]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def verify_artifacts(plan: dict[str, Any], workspace: Path) -> None:
    if not workspace.is_dir() or workspace.is_symlink():
        raise Refusal("workspace_absent_or_substituted")
    for artifact in plan["artifacts"]:
        path = workspace / artifact["path"]
        if path.is_symlink() or not path.is_file():
            raise Refusal("workspace_artifact_absent_or_substituted")
        if sha256(path.read_bytes()) != artifact["content_sha256"]:
            raise Refusal("workspace_artifact_digest_changed")


def request(
    plan: dict[str, Any], docker: str, workspace: Path, path: str
) -> dict[str, Any]:
    """Observe HTTP through a fixed in-container probe, never a host port."""
    base = compose_args(plan)
    try:
        output = run(
            docker,
            [
                *base,
                "exec",
                "--no-TTY",
                "front",
                "python",
                "-c",
                PROBE_SOURCE,
                f"http://127.0.0.1:{plan['front_port']}{path}",
            ],
            workspace,
            timeout=30,
        ).stdout
        value = json.loads(output)
        if not isinstance(value, dict) or canonical(value) != output:
            raise AcceptanceFailure("probe_output_not_exact_canonical_json")
        closed(
            value,
            {
                "body_sha256",
                "cache",
                "cache_node",
                "front_backend",
                "origin_count",
                "status",
            },
            "probe",
        )
        digest(value["body_sha256"], "probe_body")
        return value
    except (Refusal, json.JSONDecodeError) as error:
        raise AcceptanceFailure(f"http_probe_unavailable:{error}") from error


def wait_health(
    plan: dict[str, Any], docker: str, workspace: Path, *, timeout: float = 90
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last = "not_attempted"
    while time.monotonic() < deadline:
        try:
            result = request(plan, docker, workspace, "/health")
            if result["status"] == 200:
                return result
        except AcceptanceFailure as error:
            last = str(error)
        time.sleep(0.25)
    raise AcceptanceFailure(f"health_timeout:{last}")


def compose_args(plan: dict[str, Any]) -> list[str]:
    return [
        "compose",
        "--project-name",
        plan["project_name"],
        "--file",
        str(Path(plan["workspace"]) / "compose.yaml"),
    ]


def qualify(plan: dict[str, Any], docker: str, workspace: Path) -> dict[str, Any]:
    write_artifacts(plan, workspace)
    base = compose_args(plan)
    run(docker, [*base, "config", "--quiet"], workspace)
    run(docker, [*base, "up", "--detach", "--wait"], workspace, timeout=180)
    front_id = run(docker, [*base, "ps", "--quiet", "front"], workspace).stdout.strip()
    if not re.fullmatch(rb"[0-9a-f]{12,64}", front_id):
        raise AcceptanceFailure("front_container_identity_unavailable")
    ports = run(
        docker,
        ["inspect", "--format", "{{json .HostConfig.PortBindings}}", front_id.decode()],
        workspace,
    ).stdout.strip()
    if json.loads(ports) not in ({}, None):
        raise AcceptanceFailure("front_container_has_host_port_binding")
    health = wait_health(plan, docker, workspace)
    cache_sequence = [request(plan, docker, workspace, "/artifact") for _ in range(4)]
    pairs = [(item["cache"], item["cache_node"]) for item in cache_sequence]
    if pairs != [
        ("MISS", "cache-a"),
        ("MISS", "cache-b"),
        ("HIT", "cache-a"),
        ("HIT", "cache-b"),
    ]:
        raise AcceptanceFailure(f"cache_sequence:{pairs!r}")
    if {item["origin_count"] for item in cache_sequence[:2]} != {"1", "2"}:
        raise AcceptanceFailure(
            "origin_count_does_not_demonstrate_two_independent_fills"
        )
    run(docker, [*base, "stop", "cache-a"], workspace)
    failure_requests = [
        request(plan, docker, workspace, f"/failure-{index}") for index in range(4)
    ]
    if any(item["cache_node"] != "cache-b" for item in failure_requests):
        raise AcceptanceFailure("front_door_did_not_fail_over_to_cache_b")
    run(docker, [*base, "start", "cache-a"], workspace)
    restored_health = wait_health(plan, docker, workspace)
    restored_nodes: set[str | None] = set()
    deadline = time.monotonic() + 30
    index = 0
    while time.monotonic() < deadline and restored_nodes != {"cache-a", "cache-b"}:
        restored_nodes.add(
            request(plan, docker, workspace, f"/restored-{index}")["cache_node"]
        )
        index += 1
    if restored_nodes != {"cache-a", "cache-b"}:
        raise AcceptanceFailure(
            f"cache_topology_not_restored:{sorted(str(x) for x in restored_nodes)}"
        )
    containers = run(
        docker, [*base, "ps", "--format", "json"], workspace
    ).stdout.decode("utf-8", "replace")
    return {
        "cache_sequence": cache_sequence,
        "containers_sha256": sha256(containers.encode("utf-8")),
        "failure_requests": failure_requests,
        "health": health,
        "host_port_bindings": 0,
        "restored_health": restored_health,
        "restored_nodes": sorted(item for item in restored_nodes if item is not None),
    }


def teardown(plan: dict[str, Any], docker: str, workspace: Path) -> dict[str, Any]:
    if workspace.exists():
        verify_artifacts(plan, workspace)
        base = compose_args(plan)
        run(
            docker,
            [*base, "down", "--volumes", "--remove-orphans", "--timeout", "10"],
            workspace,
            timeout=120,
        )
    observation_directory = workspace if workspace.exists() else workspace.parent
    label = f"label=com.docker.compose.project={plan['project_name']}"
    remaining_containers = (
        run(
            docker,
            ["ps", "--all", "--filter", label, "--format", "{{.ID}}"],
            observation_directory,
        )
        .stdout.decode("utf-8", "strict")
        .splitlines()
    )
    if remaining_containers:
        raise AcceptanceFailure("teardown_left_campaign_containers")
    remaining_networks = (
        run(
            docker,
            ["network", "ls", "--filter", label, "--format", "{{.ID}}"],
            observation_directory,
        )
        .stdout.decode("utf-8", "strict")
        .splitlines()
    )
    if remaining_networks:
        raise AcceptanceFailure("teardown_left_campaign_networks")
    return {
        "campaign_containers_running": 0,
        "campaign_networks_remaining": 0,
        "workspace_retained_for_evidence": workspace.exists(),
    }


def attempt_path(workspace: Path, attempt: str) -> Path:
    directory = workspace / "evidence" / "attempts"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    return directory / f"{attempt.removeprefix('sha256:')}.json"


def write_once(path: Path, value: dict[str, Any]) -> None:
    encoded = canonical(value)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        view = memoryview(encoded)
        while view:
            view = view[os.write(descriptor, view) :]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def outcome(
    dispatch: dict[str, Any], result: str, evidence: dict[str, Any]
) -> dict[str, Any]:
    record = {
        "dispatch": dispatch,
        "evidence": evidence,
        "evidence_schema": "maude.local-compose.executor-evidence/v1",
        "observed_at_unix_ms": int(time.time() * 1000),
        "outcome": result,
    }
    receipt = hash_domain(EVIDENCE_DOMAIN, canonical(record))
    return {
        "attempt": dispatch["attempt"],
        "marker": dispatch["marker"],
        "outcome": result,
        "receipt": receipt,
    }, record


def validate_dispatch(
    plan: dict[str, Any], value: object, plan_id: str
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise Refusal("dispatch_object")
    closed(
        value,
        {"attempt", "marker", "scope", "subject", "work", "work_schema"},
        "dispatch",
    )
    digest(value["attempt"], "attempt")
    digest(value["marker"], "marker")
    if (
        value["work_schema"] != WORK_SCHEMA
        or value["work"] != plan_id
        or value["subject"] != plan["subject_digest"]
        or value["scope"] != plan["scope_digest"]
    ):
        raise Refusal("dispatch_binding")
    return value


def emit(value: dict[str, Any]) -> None:
    sys.stdout.buffer.write(canonical(value))


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in {"plan-id", "execute", "reconcile"}:
        print(
            "usage: local_compose_executor.py plan-id|execute|reconcile CONFIG",
            file=sys.stderr,
        )
        return 64
    operation = sys.argv[1]
    try:
        plan, plan_bytes = load_plan(Path(sys.argv[2]))
        plan_id = exact_plan_id(plan_bytes)
        if operation == "plan-id":
            print(plan_id)
            return 0
        try:
            request_value = json.load(sys.stdin)
        except json.JSONDecodeError as error:
            raise Refusal("dispatch_json") from error
        dispatch = validate_dispatch(plan, request_value, plan_id)
        workspace = Path(plan["workspace"])
        prior_path = (
            workspace
            / "evidence"
            / "attempts"
            / f"{dispatch['attempt'].removeprefix('sha256:')}.json"
        )
        if prior_path.exists():
            stored = json.loads(strict_file(prior_path, MAX_CONFIG))
            if stored.get("dispatch") != dispatch:
                raise Refusal("attempt_replay_substitution")
            emit(stored["docket_outcome"])
            return 0
        if operation == "reconcile":
            reconciled, evidence = outcome(
                dispatch,
                "indeterminate",
                {
                    "reason": "no durable executor evidence; reconciliation did not repeat mechanics"
                },
            )
            emit(reconciled)
            return 0
        docker = verify_docker(
            plan, workspace if workspace.exists() else workspace.parent
        )
        try:
            evidence = (
                qualify(plan, docker, workspace)
                if plan["action"] == "qualify"
                else teardown(plan, docker, workspace)
            )
            docket_outcome, record = outcome(dispatch, "success", evidence)
        except AcceptanceFailure as error:
            docket_outcome, record = outcome(
                dispatch, "failure", {"acceptance_failure": str(error)}
            )
        record["docket_outcome"] = docket_outcome
        path = attempt_path(workspace, dispatch["attempt"])
        write_once(path, record)
        emit(docket_outcome)
        return 0
    except (OSError, Refusal, subprocess.SubprocessError) as error:
        print(f"local-compose-executor-refused:{error}", file=sys.stderr)
        return 65


if __name__ == "__main__":
    raise SystemExit(main())
