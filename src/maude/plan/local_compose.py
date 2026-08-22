# SPDX-License-Identifier: Apache-2.0
"""Exact compiler for one closed disposable local-Compose workflow.

This is deliberately not a shell-plan compiler.  The only accepted workflow
has two closed actions (``qualify`` and ``teardown``), an exact container image,
an exact loopback port, and a fixed set of generated service artifacts.  All
deployment coordinates are explicit compiler inputs; prose in a PlanNode is
never interpreted.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from maude.plan.compiler import CompiledNodeBindingV1, CompilationResultV1
from maude.plan.document import PlanDocumentV1, canonical_json_bytes, content_digest

LOCAL_COMPOSE_INPUT_SCHEMA = "maude.local-compose-workflow-input/v1"
LOCAL_COMPOSE_COMPILER_ID = "maude.local-compose-workflow"
LOCAL_COMPOSE_COMPILER_VERSION = "1"
LOCAL_COMPOSE_EXECUTOR_PLAN_SCHEMA = "maude.local-compose.docket-executor-plan/v1"
LOCAL_COMPOSE_WORK_SCHEMA = "maude.local-compose-workflow/v1"
NIGHTSHIFT_PRECOMPILED_SCHEMA = "nightshift.precompiled_workflow_proposal.v2"
AG_PROPOSAL_SCHEMA = "ag.governed-loop.exact-work-proposal/v1"
AG_EXECUTOR_PLAN_DOMAIN = "ag-effectd.docket-executor-plan/v1"

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_PROJECT = re.compile(r"^maude-cache-[a-z0-9][a-z0-9-]{0,39}$")
_IMAGE = re.compile(r"^[a-z0-9][a-z0-9./_-]*:[a-zA-Z0-9._-]+@sha256:[0-9a-f]{64}$")
_NODE_ACTIONS = {
    "establish_workspace",
    "define_origin",
    "define_cache",
    "define_cache_a",
    "define_cache_b",
    "define_front_door",
    "validate_configuration",
    "start_platform",
    "verify_health",
    "verify_cache_behavior",
    "stop_cache_a",
    "verify_continued_service",
    "restore_cache_a",
    "final_acceptance",
    "teardown",
}


class LocalComposeCompilerError(ValueError):
    """The closed local-Compose input or its plan binding is invalid."""


def _digest(name: str, value: str) -> str:
    if not _DIGEST.fullmatch(value):
        raise LocalComposeCompilerError(f"{name} must use sha256:<64 lowercase hex>")
    return value


def _token(name: str, value: str) -> str:
    if (
        not value
        or value.strip() != value
        or any(character.isspace() for character in value)
    ):
        raise LocalComposeCompilerError(f"{name} must be a non-empty token")
    return value


def _ag_hash_domain(domain: str, payload: bytes) -> str:
    hasher = hashlib.sha256()
    encoded = domain.encode("utf-8")
    hasher.update(b"ag-ng\0digest\0v1\0")
    hasher.update(len(encoded).to_bytes(16, "big"))
    hasher.update(encoded)
    hasher.update(len(payload).to_bytes(16, "big"))
    hasher.update(payload)
    return "sha256:" + hasher.hexdigest()


def ag_executor_plan_identity(plan: Mapping[str, Any]) -> str:
    """Mirror Nightshift/AG's pinned exact executor-plan identity law."""
    return _ag_hash_domain(AG_EXECUTOR_PLAN_DOMAIN, canonical_json_bytes(plan))


ORIGIN_SOURCE = r"""#!/usr/bin/env python3
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

lock = threading.Lock()
requests = 0

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        return

    def do_GET(self):
        global requests
        if self.path == "/health":
            body = b"healthy\n"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/stats":
            with lock:
                count = requests
            body = json.dumps({"origin_requests": count}, sort_keys=True, separators=(",", ":")).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        with lock:
            requests += 1
            count = requests
        body = ("synthetic-origin:" + self.path + "\n").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("X-Origin-Count", str(count))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
"""

CACHE_SOURCE = r"""#!/usr/bin/env python3
import os
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

node = os.environ["CACHE_NODE"]
origin = os.environ.get("ORIGIN_URL", "http://origin:8080")
cache = {}
lock = threading.Lock()

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        return

    def do_GET(self):
        if self.path == "/health":
            body = (node + ":healthy\n").encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        cacheable = self.path != "/stats"
        with lock:
            stored = cache.get(self.path) if cacheable else None
        if stored is None:
            with urllib.request.urlopen(origin + self.path, timeout=2) as response:
                body = response.read()
                content_type = response.headers.get("Content-Type", "application/octet-stream")
                origin_count = response.headers.get("X-Origin-Count")
            stored = (body, content_type, origin_count)
            if cacheable:
                with lock:
                    cache[self.path] = stored
            status = "MISS"
        else:
            body, content_type, origin_count = stored
            status = "HIT"
        body, content_type, origin_count = stored
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("X-Cache", status)
        self.send_header("X-Cache-Node", node)
        if origin_count is not None:
            self.send_header("X-Origin-Count", origin_count)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
"""

FRONT_SOURCE = r"""#!/usr/bin/env python3
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

backends = ("http://cache-a:8080", "http://cache-b:8080")
counter = 0
lock = threading.Lock()

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        return

    def do_GET(self):
        global counter
        if self.path == "/health":
            path = "/health"
            start = 0
        else:
            path = self.path
            with lock:
                start = counter
                counter += 1
        failures = []
        for offset in range(len(backends)):
            backend = backends[(start + offset) % len(backends)]
            try:
                with urllib.request.urlopen(backend + path, timeout=1) as response:
                    body = response.read()
                    headers = response.headers
                self.send_response(200)
                for header in ("Content-Type", "X-Cache", "X-Cache-Node", "X-Origin-Count"):
                    value = headers.get(header)
                    if value is not None:
                        self.send_header(header, value)
                self.send_header("X-Front-Backend", headers.get("X-Cache-Node", backend))
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            except (OSError, urllib.error.URLError) as error:
                failures.append(type(error).__name__)
        body = ("no backend available:" + ",".join(failures) + "\n").encode()
        self.send_response(503)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
"""


def _service(image: str, source: str, command: str) -> dict[str, Any]:
    return {
        "cap_drop": ["ALL"],
        "command": ["python", f"/app/{command}"],
        "cpus": 0.5,
        "healthcheck": {
            "interval": "2s",
            "retries": 20,
            "start_period": "2s",
            "test": [
                "CMD",
                "python",
                "-c",
                "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/health',timeout=3).read()",
            ],
            "timeout": "8s",
        },
        "image": image,
        "mem_limit": "64m",
        "networks": ["cache-net"],
        "pids_limit": 64,
        "read_only": True,
        "tmpfs": ["/tmp:rw,noexec,nosuid,size=8m"],
        "user": "65534:65534",
        "volumes": [f"{source}:/app/{command}:ro"],
    }


def _compose_document(inputs: LocalComposeWorkflowInputsV1) -> dict[str, Any]:
    workspace = Path(inputs.workspace)
    origin = _service(inputs.image, str(workspace / "origin.py"), "origin.py")
    cache_a = _service(inputs.image, str(workspace / "cache.py"), "cache.py")
    cache_a.update(
        {
            "depends_on": {"origin": {"condition": "service_healthy"}},
            "environment": {
                "CACHE_NODE": "cache-a",
                "ORIGIN_URL": "http://origin:8080",
            },
        }
    )
    cache_b = _service(inputs.image, str(workspace / "cache.py"), "cache.py")
    cache_b.update(
        {
            "depends_on": {"origin": {"condition": "service_healthy"}},
            "environment": {
                "CACHE_NODE": "cache-b",
                "ORIGIN_URL": "http://origin:8080",
            },
        }
    )
    front = _service(inputs.image, str(workspace / "front.py"), "front.py")
    front.update(
        {
            "depends_on": {
                "cache-a": {"condition": "service_healthy"},
                "cache-b": {"condition": "service_healthy"},
            },
        }
    )
    return {
        "name": inputs.project_name,
        "networks": {"cache-net": {"internal": True}},
        "services": {
            "cache-a": cache_a,
            "cache-b": cache_b,
            "front": front,
            "origin": origin,
        },
    }


@dataclass(frozen=True)
class NodeActionV1:
    node_id: str
    action: str

    def to_data(self) -> dict[str, str]:
        return {"action": self.action, "node_id": self.node_id}


@dataclass(frozen=True)
class LocalComposeWorkflowInputsV1:
    action: str
    workspace: str
    project_name: str
    front_port: int
    image: str
    docker_program: str
    docker_program_identity: str
    docker_client_version: str
    docker_server_version: str
    compose_version: str
    campaign_id: str
    occurrence_id: str
    program_id: str
    observation_id: str
    subject_digest: str
    scope_digest: str
    proposal_class: str
    node_actions: tuple[NodeActionV1, ...]
    schema: str = LOCAL_COMPOSE_INPUT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != LOCAL_COMPOSE_INPUT_SCHEMA:
            raise LocalComposeCompilerError(
                "unsupported local Compose compiler input schema"
            )
        if self.action not in {"qualify", "teardown"}:
            raise LocalComposeCompilerError(
                "workflow action must be qualify or teardown"
            )
        workspace = Path(self.workspace)
        if not workspace.is_absolute() or workspace.name != self.project_name:
            raise LocalComposeCompilerError(
                "workspace must be an absolute project-name directory"
            )
        if not _PROJECT.fullmatch(self.project_name):
            raise LocalComposeCompilerError(
                "project_name is outside the closed local namespace"
            )
        if self.front_port != 8080:
            raise LocalComposeCompilerError(
                "the closed front service port must be 8080"
            )
        if not _IMAGE.fullmatch(self.image):
            raise LocalComposeCompilerError(
                "image must be an exact tag plus sha256 digest"
            )
        if not Path(self.docker_program).is_absolute():
            raise LocalComposeCompilerError("docker_program must be absolute")
        _digest("docker_program_identity", self.docker_program_identity)
        for name, value in (
            ("campaign_id", self.campaign_id),
            ("program_id", self.program_id),
            ("observation_id", self.observation_id),
            ("subject_digest", self.subject_digest),
            ("scope_digest", self.scope_digest),
        ):
            _digest(name, value)
        try:
            uuid.UUID(self.occurrence_id)
        except ValueError as error:
            raise LocalComposeCompilerError("occurrence_id must be a UUID") from error
        if self.proposal_class not in {"initial", "successor"}:
            raise LocalComposeCompilerError(
                "proposal_class must be initial or successor"
            )
        if self.proposal_class == "initial" and self.action != "qualify":
            raise LocalComposeCompilerError(
                "the initial synthetic occurrence must qualify"
            )
        for name, value in (
            ("docker_client_version", self.docker_client_version),
            ("docker_server_version", self.docker_server_version),
            ("compose_version", self.compose_version),
        ):
            _token(name, value)
        if not self.node_actions:
            raise LocalComposeCompilerError("node_actions must not be empty")
        if len({item.node_id for item in self.node_actions}) != len(self.node_actions):
            raise LocalComposeCompilerError(
                "node_actions must bind each PlanNode at most once"
            )
        if any(item.action not in _NODE_ACTIONS for item in self.node_actions):
            raise LocalComposeCompilerError(
                "node_actions contains an unsupported action"
            )
        if self.action == "teardown" and tuple(
            item.action for item in self.node_actions
        ) != ("teardown",):
            raise LocalComposeCompilerError(
                "teardown input may bind only the teardown node"
            )
        if self.action == "qualify" and any(
            item.action == "teardown" for item in self.node_actions
        ):
            raise LocalComposeCompilerError("qualify input cannot smuggle teardown")

    def to_data(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "campaign_id": self.campaign_id,
            "compose_version": self.compose_version,
            "docker_client_version": self.docker_client_version,
            "docker_program": self.docker_program,
            "docker_program_identity": self.docker_program_identity,
            "docker_server_version": self.docker_server_version,
            "image": self.image,
            "node_actions": [item.to_data() for item in self.node_actions],
            "observation_id": self.observation_id,
            "occurrence_id": self.occurrence_id,
            "program_id": self.program_id,
            "project_name": self.project_name,
            "proposal_class": self.proposal_class,
            "front_port": self.front_port,
            "schema": self.schema,
            "scope_digest": self.scope_digest,
            "subject_digest": self.subject_digest,
            "workspace": self.workspace,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_data())


class LocalComposeWorkflowCompilerV1:
    compiler_id = LOCAL_COMPOSE_COMPILER_ID
    compiler_version = LOCAL_COMPOSE_COMPILER_VERSION

    def compile(
        self, document: PlanDocumentV1, inputs: LocalComposeWorkflowInputsV1
    ) -> CompilationResultV1:
        known = {node.node_id for node in document.nodes}
        nodes = {node.node_id: node for node in document.nodes}
        missing = [
            item.node_id for item in inputs.node_actions if item.node_id not in known
        ]
        if missing:
            raise LocalComposeCompilerError(
                f"workflow input binds unknown PlanNode(s): {sorted(missing)}"
            )
        for item in inputs.node_actions:
            work = nodes[item.node_id].work
            if (
                work is None
                or len(work.commands) != 1
                or work.commands[0].program != "maude-local-compose"
                or work.commands[0].argv_prefix != (item.action,)
            ):
                raise LocalComposeCompilerError(
                    f"PlanNode {item.node_id} lacks exact structured work for {item.action}"
                )
        input_digest = content_digest(inputs.canonical_bytes)
        compose = canonical_json_bytes(_compose_document(inputs)).decode("utf-8") + "\n"
        artifacts = (
            ("cache.py", CACHE_SOURCE),
            ("compose.yaml", compose),
            ("front.py", FRONT_SOURCE),
            ("origin.py", ORIGIN_SOURCE),
        )
        actions = tuple(item.to_data() for item in inputs.node_actions)
        executor_plan: dict[str, Any] = {
            "action": inputs.action,
            "artifacts": [
                {
                    "content_sha256": content_digest(content.encode("utf-8")),
                    "content_utf8": content,
                    "path": path,
                }
                for path, content in artifacts
            ],
            "compiler": {
                "id": self.compiler_id,
                "inputs_digest": input_digest,
                "version": self.compiler_version,
            },
            "docker": {
                "client_version": inputs.docker_client_version,
                "compose_version": inputs.compose_version,
                "program": inputs.docker_program,
                "program_identity": inputs.docker_program_identity,
                "server_version": inputs.docker_server_version,
            },
            "image": inputs.image,
            "node_actions": list(actions),
            "plan_document_digest": document.digest,
            "project_name": inputs.project_name,
            "front_port": inputs.front_port,
            "schema": LOCAL_COMPOSE_EXECUTOR_PLAN_SCHEMA,
            "scope_digest": inputs.scope_digest,
            "subject_digest": inputs.subject_digest,
            "workspace": inputs.workspace,
        }
        exact_work = ag_executor_plan_identity(executor_plan)
        if inputs.proposal_class == "initial":
            mode = {
                "genesis": {
                    "genesis": {
                        "budget": {
                            "escalation_limit": 1,
                            "escalations_used": 0,
                            "probe_limit": 1,
                            "probes_used": 0,
                            "retries_used": 0,
                            "retry_limit": 1,
                        },
                        "campaign": inputs.campaign_id,
                        "expected_ag_work": exact_work,
                        "occurrence": inputs.occurrence_id,
                        "program": inputs.program_id,
                        "residuals": [],
                    }
                }
            }
        else:
            mode = {
                "continuation": {
                    "continuation": {
                        "expected_ag_work": exact_work,
                        "occurrence": inputs.occurrence_id,
                    }
                }
            }
        handoff = {
            "ag_executor_plan": executor_plan,
            "campaign_id": inputs.campaign_id,
            "immutable_parameters": {
                "compiler_inputs": input_digest,
                "plan_document": document.digest,
                "workflow_action": inputs.action,
            },
            "intent_kind": f"local_compose_{inputs.action}",
            "mode": mode,
            "occurrence_id": inputs.occurrence_id,
            "proposal_input": {
                "class": inputs.proposal_class,
                "observation": inputs.observation_id,
                "proposal": {
                    "campaign": inputs.campaign_id,
                    "repair": None,
                    "schema": AG_PROPOSAL_SCHEMA,
                    "scope": inputs.scope_digest,
                    "subject": inputs.subject_digest,
                    "work": exact_work,
                    "work_schema": LOCAL_COMPOSE_WORK_SCHEMA,
                },
            },
            "schema": NIGHTSHIFT_PRECOMPILED_SCHEMA,
            "subject_digest": inputs.subject_digest,
            "workflow_id": LOCAL_COMPOSE_WORK_SCHEMA,
        }
        bindings = tuple(
            CompiledNodeBindingV1(
                item.node_id,
                content_digest(canonical_json_bytes(item.to_data())),
            )
            for item in inputs.node_actions
        )
        return CompilationResultV1(
            compiler_id=self.compiler_id,
            compiler_version=self.compiler_version,
            source_plan_digest=document.digest,
            compiler_inputs_schema=inputs.schema,
            compiler_inputs_digest=input_digest,
            handoff_bytes=canonical_json_bytes(handoff),
            node_bindings=bindings,
        )


def executor_plan_from_handoff(handoff_bytes: bytes) -> dict[str, Any]:
    """Extract the exact executor plan from one compiler-produced handoff."""
    try:
        value = json.loads(handoff_bytes)
        plan = value["ag_executor_plan"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise LocalComposeCompilerError(
            "compiled handoff has no exact executor plan"
        ) from error
    if (
        not isinstance(plan, dict)
        or plan.get("schema") != LOCAL_COMPOSE_EXECUTOR_PLAN_SCHEMA
    ):
        raise LocalComposeCompilerError("compiled executor plan schema is unsupported")
    if canonical_json_bytes(value) != handoff_bytes:
        raise LocalComposeCompilerError("compiled handoff bytes are not canonical")
    return plan
