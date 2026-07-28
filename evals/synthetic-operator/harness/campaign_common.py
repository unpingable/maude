#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Shared, evaluation-only utilities for the frozen synthetic UX campaign."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import mimetypes
import os
from pathlib import Path
from typing import Any, Iterable


CAMPAIGN_ID = "maude-baseline-20260728T050937-0400"
SUT_COMMIT = "9d5a54f476a52826379a9ae8d6710551253a6493"
PREPARATION_BASE_COMMIT = "9e366fae778602f1355e9467814c89b54832893f"
DOCKET_COMMIT = "9050a53cd8a4741d71f5334f90eb22dac52eeb62"

HARNESS_DIR = Path(__file__).resolve().parent
REPO_ROOT = HARNESS_DIR.parents[2]
EVAL_ROOT = REPO_ROOT / "evals" / "synthetic-operator"
SCENARIOS_DIR = EVAL_ROOT / "scenarios"
PERSONAS_DIR = EVAL_ROOT / "personas"
CAMPAIGN_DIR = EVAL_ROOT / "runs" / CAMPAIGN_ID
PACKET_DIR = CAMPAIGN_DIR / "packet"
MATRIX_PATH = PACKET_DIR / "run-matrix.json"
INSTALL_TRACK_PATH = PACKET_DIR / "installation-track.json"
MANIFEST_PATH = PACKET_DIR / "campaign-manifest.json"
PROVIDER_CAPABILITY_POLICY_PATH = (
    PACKET_DIR / "provider-capability-policy.json"
)
LAB_ROOT = Path("/tmp") / f"maude-synth-{CAMPAIGN_ID}"
PROVIDER_CAPABILITY_PROBE_ROOT = (
    PACKET_DIR / "provider-capability-probes"
)
AUTH_GATE_PROBE_PATH = (
    PROVIDER_CAPABILITY_PROBE_ROOT / "auth" / "index.json"
)
INSTALL_SURFACE_PROBE_PATH = (
    PROVIDER_CAPABILITY_PROBE_ROOT / "installation" / "index.json"
)

MAUDE_RUN_IDS = tuple(f"maude-s{number:02d}" for number in range(1, 21))
DIRECT_RUN_IDS = (
    "docket-s01",
    "docket-s11",
    "docket-s15",
    "docket-s17",
    "docket-s20",
)
INSTALL_RUN_IDS = tuple(f"install-i{number:02d}" for number in range(1, 11))
REQUIRED_PERSONAS = {
    "senior-devops-engineer",
    "production-sre-on-call",
    "traditional-systems-administrator",
    "junior-on-call-operator",
    "platform-engineer",
    "retail-edge-cluster-caretaker",
    "security-conscious-operator",
    "sleep-deprived-incident-operator",
    "skeptical-first-time-user",
    "experienced-authority-description-record-operator",
}
REQUIRED_INSTALL_PERSONAS = {
    "installation-shortest-path-sre",
    "installation-terminology-new-sysadmin",
    "installation-source-install-developer",
    "installation-component-only-operator",
    "installation-literal-doc-operator",
}
REQUIRED_INSTALL_COVERAGE = {
    "discovery",
    "documented_install",
    "configuration",
    "first_meaningful_use",
    "packaging",
    "wrong_path",
    "missing_dependency",
    "unavailable_governor_or_sibling",
    "component_only_composability",
    "permissions",
    "malformed_config",
    "stale_state_or_schema",
    "occupied_endpoint_or_port",
    "upgrade_from_prior_state",
    "removal_reset_evidence",
    "copy_paste_examples_exactly_as_written",
}
ALLOWED_SURFACES = {"maude", "docket-gwr-direct", "maude-installation"}
SUPPORTED_PROVIDER_CONFIGS = ("openai-sol", "anthropic-sonnet")
CODEX_ONLY_MODEL_CONFIG = {
    "provider": "OpenAI",
    "cli": "codex",
    "model_argument": "gpt-5.6-sol",
    "expected_family": "GPT",
    "reasoning_effort": "low",
    "mcp_protocol_version": "2025-06-18",
    "operator_tools": ["mcp__operator__terminal"],
    "grader_tools": ["mcp__grader__evidence"],
    "operator_mcp_enabled_tools": ["terminal"],
    "grader_mcp_enabled_tools": ["evidence"],
    "built_in_tools": [],
    "intrinsic_action_features_explicitly_disabled": [
        "shell_tool",
        "unified_exec",
    ],
    "optional_features_explicitly_disabled": [
        "apps",
        "plugins",
        "remote_plugin",
        "browser_use",
        "browser_use_external",
        "browser_use_full_cdp_access",
        "computer_use",
        "image_generation",
        "multi_agent",
        "multi_agent_v2",
        "hooks",
        "skill_mcp_dependency_install",
        "tool_call_mcp_elicitation",
    ],
    "approval_policy": "never",
    "mcp_default_tools_approval_mode": "approve",
    "mcp_auto_approval_safety": {
        "mcp_config_hash_pinned": True,
        "exact_enabled_tool_count_per_role": 1,
        "operator_terminal_bounded_by_frozen_broker": True,
        "grader_evidence_tool_read_only": True,
    },
    "tool_boundary": (
        "Strict per-session direct stdio MCP. The operator receives only "
        "mcp__operator__terminal (enabled as terminal); the grader receives "
        "only mcp__grader__evidence (enabled as evidence). Codex built-in and "
        "intrinsic action features are disabled."
    ),
    "transport_boundary": (
        "Codex runs in a task-blind retained-auth transport namespace with no "
        "task paths or task sockets. A trusted direct stdio MCP shim shares "
        "that namespace and can read retained provider authentication until "
        "transport exit."
    ),
    "broker_boundary": (
        "The operator command broker receives neither provider credentials nor "
        "semantic prompts; each command executes in a fresh per-command "
        "no-network mount/PID namespace. The grader evidence tool is read-only."
    ),
    "boundary_limitation": (
        "The trusted direct stdio shim is part of the retained-auth transport "
        "boundary and can read provider authentication by construction; the "
        "campaign proves task paths and task sockets are absent, not "
        "provider-internal noninspection. Availability and cross-family "
        "comparison claims belong to the frozen campaign policy and observed "
        "capability evidence, not this provider configuration."
    ),
    "exact_provider_tool_allowlist_supported": True,
    "unexpected_intrinsic_action_policy": "fail-closed",
    "live_web_search_enabled": False,
    "user_mcp_and_connector_config_loaded": False,
    "freshness": [
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "fresh provider process",
        "no resume, continuation, or follow-up",
    ],
}
ANTHROPIC_SONNET_MODEL_CONFIG = {
    "provider": "Anthropic",
    "cli": "claude",
    "model_argument": "sonnet",
    "expected_family": "Claude",
    "reasoning_effort": "low",
    "mcp_protocol_version": "2025-11-25",
    "operator_tools": ["mcp__operator__terminal"],
    "grader_tools": ["mcp__grader__evidence"],
    "operator_mcp_enabled_tools": ["terminal"],
    "grader_mcp_enabled_tools": ["evidence"],
    "built_in_tools": [],
    "strict_mcp_config": True,
    "permission_mode": "bypassPermissions",
    "slash_commands_enabled": False,
    "browser_enabled": False,
    "session_persistence": False,
    "tool_boundary": (
        "Strict per-session MCP configuration. The operator receives only "
        "mcp__operator__terminal; the grader receives only "
        "mcp__grader__evidence. Built-in tools are excluded from the exact "
        "provider roster."
    ),
    "transport_boundary": (
        "Claude runs in a task-blind retained-auth transport with no task "
        "paths or task sockets. Its fixed MCP proxy and command broker receive "
        "neither provider credentials nor semantic evaluator prompts."
    ),
    "broker_boundary": (
        "Operator commands execute in a fresh source-free, auth-free, "
        "no-network mount/PID namespace. The grader evidence tool is read-only."
    ),
    "live_web_search_enabled": False,
    "user_mcp_and_connector_config_loaded": False,
    "freshness": [
        "--no-session-persistence",
        "new UUID session id",
        "fresh provider process",
        "no resume, continuation, or follow-up",
    ],
}
PROVIDER_MODEL_CONFIGS = {
    "openai-sol": CODEX_ONLY_MODEL_CONFIG,
    "anthropic-sonnet": ANTHROPIC_SONNET_MODEL_CONFIG,
}


class CampaignError(RuntimeError):
    """A campaign input, custody, or execution invariant failed."""


def json_bytes(value: Any, *, pretty: bool = True) -> bytes:
    if pretty:
        encoded = json.dumps(
            value, indent=2, ensure_ascii=False, sort_keys=True
        ).encode("utf-8")
    else:
        encoded = json.dumps(
            value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
    return encoded + b"\n"


def write_json(path: Path, value: Any, *, pretty: bool = True) -> None:
    """Atomically write JSON generated by campaign machinery."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(json_bytes(value, pretty=pretty))
    os.replace(temporary, path)


def write_text(path: Path, text: str) -> None:
    """Atomically write normalized UTF-8 campaign text."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def append_jsonl(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as handle:
        handle.write(json_bytes(value, pretty=False))
        handle.flush()
        os.fsync(handle.fileno())


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def media_type_for_path(path: Path, data: bytes) -> str:
    media_type = {
        ".json": "application/json",
        ".jsonl": "application/x-ndjson",
        ".md": "text/markdown",
        ".diff": "text/x-diff",
        ".patch": "text/x-diff",
        ".yaml": "application/yaml",
        ".yml": "application/yaml",
        ".toml": "application/toml",
        ".svg": "image/svg+xml",
        ".txt": "text/plain",
    }.get(path.suffix.lower())
    if media_type is None:
        media_type = mimetypes.guess_type(path.name)[0]
    if media_type is None:
        try:
            data.decode("utf-8")
            media_type = "text/plain"
        except UnicodeDecodeError:
            media_type = "application/octet-stream"
    return media_type


def file_record(path: Path, *, relative_to: Path = REPO_ROOT) -> dict[str, Any]:
    data = path.read_bytes()
    try:
        display_path = str(path.relative_to(relative_to))
    except ValueError:
        display_path = str(path)
    return {
        "path": display_path,
        "media_type": media_type_for_path(path, data),
        "bytes": len(data),
        "sha256": sha256_bytes(data),
        "mode": f"{path.stat().st_mode & 0o777:04o}",
    }


def inventory_files(
    root: Path,
    *,
    exclude_names: Iterable[str] = (),
) -> list[dict[str, Any]]:
    excluded = set(exclude_names)
    records: list[dict[str, Any]] = []
    if not root.exists():
        return records
    for path in sorted(root.rglob("*")):
        if (
            not path.is_file()
            or path.is_symlink()
            or any(part in excluded for part in path.relative_to(root).parts)
        ):
            continue
        records.append(file_record(path, relative_to=root))
    return records


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CampaignError(f"cannot load JSON {path}: {exc}") from exc


def load_matrix() -> dict[str, Any]:
    matrix = load_json(MATRIX_PATH)
    if not isinstance(matrix, dict) or matrix.get("campaign_id") != CAMPAIGN_ID:
        raise CampaignError("run matrix has the wrong campaign identity")
    return matrix


def matrix_runs(matrix: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    matrix = matrix or load_matrix()
    runs = matrix.get("runs")
    if not isinstance(runs, list) or not all(isinstance(item, dict) for item in runs):
        raise CampaignError("run matrix runs must be an array of objects")
    return runs


def run_index(matrix: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    runs = matrix_runs(matrix)
    index: dict[str, dict[str, Any]] = {}
    for item in runs:
        run_id = item.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            raise CampaignError("every matrix run needs a non-empty run_id")
        if run_id in index:
            raise CampaignError(f"duplicate matrix run_id: {run_id}")
        index[run_id] = item
    return index


def validate_matrix(matrix: dict[str, Any] | None = None) -> list[str]:
    matrix = matrix or load_matrix()
    errors: list[str] = []
    if matrix.get("schema") != "maude.synthetic-operator.run-matrix.v2":
        errors.append("run matrix schema must be maude.synthetic-operator.run-matrix.v2")
    interpretation = matrix.get("interpretation")
    if not isinstance(interpretation, str) or "10 installation" not in interpretation:
        errors.append("run matrix interpretation omits the installation track")
    expected_helpers = {
        "destination_scope": "operator working directory",
        "all_runs": [
            {
                "destination": "operator-retrospective",
                "source": (
                    "evals/synthetic-operator/harness/"
                    "operator_retrospective.py"
                ),
                "purpose": (
                    "reveal the fixed questionnaire only after a nonempty "
                    "initial disposition"
                ),
            }
        ],
        "installation_runs": [
            {
                "destination": "operator-pty",
                "source": (
                    "evals/synthetic-operator/harness/operator_pty.py"
                ),
                "purpose": (
                    "provide neutral persistent PTY transport for an arbitrary "
                    "operator-selected command across start/read/send/status/"
                    "stop calls while preserving exact PTY bytes"
                ),
            }
        ],
        "product_command_count_exclusions": [
            "writing /home/operator/initial-disposition.md",
            "one operator-retrospective invocation",
            (
                "do not double-count a PTY start and its wrapped product "
                "executable; every adapter provider action remains an "
                "interaction step"
            ),
        ],
    }
    if matrix.get("evaluation_helpers") != expected_helpers:
        errors.append("run matrix evaluation-helper declaration differs")
    try:
        index = run_index(matrix)
    except CampaignError as exc:
        return [str(exc)]

    actual_maude = {
        item["run_id"] for item in index.values() if item.get("surface") == "maude"
    }
    if actual_maude != set(MAUDE_RUN_IDS):
        errors.append(
            "Maude run IDs must be exactly "
            f"{list(MAUDE_RUN_IDS)!r}; got {sorted(actual_maude)!r}"
        )
    actual_direct = {
        item["run_id"]
        for item in index.values()
        if item.get("surface") == "docket-gwr-direct"
    }
    if actual_direct != set(DIRECT_RUN_IDS):
        errors.append(
            "direct comparator run IDs must be exactly "
            f"{list(DIRECT_RUN_IDS)!r}; got {sorted(actual_direct)!r}"
        )
    actual_install = {
        item["run_id"]
        for item in index.values()
        if item.get("surface") == "maude-installation"
    }
    if actual_install != set(INSTALL_RUN_IDS):
        errors.append(
            "installation run IDs must be exactly "
            f"{list(INSTALL_RUN_IDS)!r}; got {sorted(actual_install)!r}"
        )

    unexpected_surfaces = {
        str(item.get("surface"))
        for item in index.values()
        if item.get("surface") not in ALLOWED_SURFACES
    }
    if unexpected_surfaces:
        errors.append(f"unknown run surfaces: {sorted(unexpected_surfaces)!r}")
    expected_total = len(MAUDE_RUN_IDS) + len(DIRECT_RUN_IDS) + len(INSTALL_RUN_IDS)
    if len(index) != expected_total:
        errors.append(
            f"run matrix must declare exactly {expected_total} runs; got {len(index)}"
        )

    scenarios = {
        item.get("scenario_id")
        for item in index.values()
        if item.get("surface") == "maude"
    }
    expected_scenarios = {
        path.name
        for path in SCENARIOS_DIR.iterdir()
        if path.is_dir() and path.name.startswith("s")
    } if SCENARIOS_DIR.is_dir() else set()
    if len(scenarios) != 20 or scenarios != expected_scenarios:
        errors.append(
            "the matrix must cover every one of the 20 scenario directories once"
        )

    personas = {
        item.get("persona_id")
        for item in index.values()
        if item.get("surface") == "maude"
    }
    if not REQUIRED_PERSONAS.issubset(personas):
        errors.append(
            f"required persona coverage missing: {sorted(REQUIRED_PERSONAS - personas)}"
        )

    install_scenarios = {
        item.get("scenario_id")
        for item in index.values()
        if item.get("surface") == "maude-installation"
    }
    expected_install_scenarios = {
        path.name
        for path in SCENARIOS_DIR.iterdir()
        if path.is_dir()
        and len(path.name) >= 4
        and path.name[0] == "i"
        and path.name[1:3].isdigit()
        and path.name[3] == "-"
    } if SCENARIOS_DIR.is_dir() else set()
    if (
        len(install_scenarios) != len(INSTALL_RUN_IDS)
        or install_scenarios != expected_install_scenarios
    ):
        errors.append(
            "the matrix must cover every one of the 10 installation scenario "
            "directories once"
        )

    install_personas = {
        item.get("persona_id")
        for item in index.values()
        if item.get("surface") == "maude-installation"
    }
    if not REQUIRED_INSTALL_PERSONAS.issubset(install_personas):
        errors.append(
            "required installation persona coverage missing: "
            f"{sorted(REQUIRED_INSTALL_PERSONAS - install_personas)}"
        )
    install_coverage = {
        str(category)
        for item in index.values()
        if item.get("surface") == "maude-installation"
        for category in (
            item.get("coverage")
            if isinstance(item.get("coverage"), list)
            else []
        )
    }
    if not REQUIRED_INSTALL_COVERAGE.issubset(install_coverage):
        errors.append(
            "required installation condition coverage missing: "
            f"{sorted(REQUIRED_INSTALL_COVERAGE - install_coverage)}"
        )
    if install_coverage != REQUIRED_INSTALL_COVERAGE:
        errors.append(
            "installation matrix has undeclared condition coverage: "
            f"{sorted(install_coverage - REQUIRED_INSTALL_COVERAGE)}"
        )
    literal_copy_runs = [
        item
        for item in index.values()
        if item.get("surface") == "maude-installation"
        and item.get("persona_id") == "installation-literal-doc-operator"
        and "copy_paste_examples_exactly_as_written"
        in (
            item.get("coverage")
            if isinstance(item.get("coverage"), list)
            else []
        )
    ]
    if not literal_copy_runs:
        errors.append(
            "copy/paste-exactly coverage must be exercised by a "
            "literal-documentation installation operator"
        )

    configs = matrix.get("operator_model_configs")
    if not isinstance(configs, dict):
        errors.append("operator_model_configs must be an object")
        configs = {}
    if (
        not configs
        or any(
            key not in PROVIDER_MODEL_CONFIGS
            or value != PROVIDER_MODEL_CONFIGS[key]
            for key, value in configs.items()
        )
    ):
        errors.append(
            "operator_model_configs contains an unknown or changed provider "
            "configuration"
        )
    policy = matrix.get("model_family_policy")
    if not isinstance(policy, dict):
        errors.append("model_family_policy must be an object")
        policy = {}
    campaign_providers = policy.get("campaign_provider_configs")
    operator_config_set = {
        str(item.get("operator_model_config"))
        for item in index.values()
        if item.get("operator_model_config") in configs
    }
    grader_config_set = {
        str(item.get("grader_model_config"))
        for item in index.values()
        if item.get("grader_model_config") in configs
    }
    operator_configs_used = [
        provider
        for provider in SUPPORTED_PROVIDER_CONFIGS
        if provider in operator_config_set
    ]
    grader_configs_used = [
        provider
        for provider in SUPPORTED_PROVIDER_CONFIGS
        if provider in grader_config_set
    ]
    providers_used = [
        provider
        for provider in SUPPORTED_PROVIDER_CONFIGS
        if provider in operator_config_set | grader_config_set
    ]
    eligibility = policy.get("provider_role_eligibility")
    role_names = {
        "ordinary_operator",
        "installation_operator",
        "ordinary_grader",
        "installation_grader",
    }
    if (
        not isinstance(campaign_providers, list)
        or campaign_providers != providers_used
        or any(value not in configs for value in campaign_providers)
        or policy.get("operator_model_configs_used")
        != operator_configs_used
        or policy.get("grader_model_configs_used")
        != grader_configs_used
        or policy.get("assignment_algorithm")
        != "maude-synthetic-provider-assignment-v1"
        or policy.get("separate_fresh_sessions_required") is not True
        or not isinstance(eligibility, dict)
        or set(eligibility) != set(SUPPORTED_PROVIDER_CONFIGS)
        or any(
            not isinstance(roles, dict)
            or set(roles) != role_names
            or any(type(roles.get(role)) is not bool for role in role_names)
            for roles in eligibility.values()
        )
        or type(policy.get("same_family_grading")) is not bool
        or type(policy.get("same_model_configuration_grading")) is not bool
        or type(policy.get("cross_family_grading_supported")) is not bool
        or type(policy.get("cross_family_grading_used")) is not bool
        or type(policy.get("claude_available")) is not bool
        or type(policy.get("claude_sessions_permitted")) is not bool
        or type(policy.get("claude_operator_sessions_assigned")) is not bool
        or type(policy.get("claude_grader_sessions_assigned")) is not bool
        or not isinstance(policy.get("limitation"), str)
        or not policy.get("limitation")
    ):
        errors.append("run matrix model-family policy shape or derivation differs")
    same_config_used = any(
        item.get("operator_model_config")
        == item.get("grader_model_config")
        for item in index.values()
    )
    same_family_used = any(
        (
            PROVIDER_MODEL_CONFIGS.get(
                str(item.get("operator_model_config")),
                {},
            ).get("expected_family")
            == PROVIDER_MODEL_CONFIGS.get(
                str(item.get("grader_model_config")),
                {},
            ).get("expected_family")
        )
        for item in index.values()
    )
    cross_family_used = any(
        (
            PROVIDER_MODEL_CONFIGS.get(
                str(item.get("operator_model_config")),
                {},
            ).get("expected_family")
            != PROVIDER_MODEL_CONFIGS.get(
                str(item.get("grader_model_config")),
                {},
            ).get("expected_family")
        )
        for item in index.values()
    )
    cross_family_supported = bool(
        isinstance(eligibility, dict)
        and any(
            eligibility.get(operator, {}).get(operator_role) is True
            and eligibility.get(grader, {}).get(grader_role) is True
            and PROVIDER_MODEL_CONFIGS[operator]["expected_family"]
            != PROVIDER_MODEL_CONFIGS[grader]["expected_family"]
            for operator_role, grader_role in (
                ("ordinary_operator", "ordinary_grader"),
                ("installation_operator", "installation_grader"),
            )
            for operator in providers_used
            for grader in providers_used
        )
    )
    claude_available = bool(
        isinstance(eligibility, dict)
        and isinstance(eligibility.get("anthropic-sonnet"), dict)
        and any(eligibility["anthropic-sonnet"].values())
    )
    if (
        policy.get("same_model_configuration_grading")
        is not same_config_used
        or policy.get("same_family_grading") is not same_family_used
        or policy.get("cross_family_grading_used")
        is not cross_family_used
        or policy.get("cross_family_grading_supported")
        is not cross_family_supported
        or policy.get("claude_available") is not claude_available
        or policy.get("claude_sessions_permitted") is not claude_available
        or policy.get("claude_operator_sessions_assigned")
        is not ("anthropic-sonnet" in operator_configs_used)
        or policy.get("claude_grader_sessions_assigned")
        is not ("anthropic-sonnet" in grader_configs_used)
    ):
        errors.append("run matrix model-family policy facts differ from runs")
    for item in index.values():
        operator = item.get("operator_model_config")
        grader = item.get("grader_model_config")
        if operator not in configs:
            errors.append(f"{item['run_id']}: unknown operator model config {operator!r}")
        if grader not in configs:
            errors.append(f"{item['run_id']}: unknown grader model config {grader!r}")
        surface = item.get("surface")
        operator_role = (
            "installation_operator"
            if surface == "maude-installation"
            else "ordinary_operator"
        )
        grader_role = (
            "installation_grader"
            if surface == "maude-installation"
            else "ordinary_grader"
        )
        if (
            isinstance(eligibility, dict)
            and isinstance(eligibility.get(operator), dict)
            and eligibility[operator].get(operator_role) is not True
        ):
            errors.append(
                f"{item['run_id']}: operator provider lacks {operator_role} "
                "eligibility"
            )
        if (
            isinstance(eligibility, dict)
            and isinstance(eligibility.get(grader), dict)
            and eligibility[grader].get(grader_role) is not True
        ):
            errors.append(
                f"{item['run_id']}: grader provider lacks {grader_role} "
                "eligibility"
            )
        scenario = SCENARIOS_DIR / str(item.get("scenario_id"))
        persona = PERSONAS_DIR / f"{item.get('persona_id')}.md"
        if not scenario.is_dir():
            errors.append(f"{item['run_id']}: scenario directory missing: {scenario}")
        if not persona.is_file():
            errors.append(f"{item['run_id']}: persona prompt missing: {persona}")
        if item.get("surface") == "maude-installation":
            task_id = item.get("task_id")
            expected_task_id = (
                "install-task-" + str(item["run_id"]).removeprefix("install-i")
            )
            if task_id != expected_task_id:
                errors.append(
                    f"{item['run_id']}: installation task ID {task_id!r} "
                    f"!= {expected_task_id!r}"
                )
            for name in (
                "README.md",
                "task.json",
                "environment.json",
                "expected-disposition.json",
            ):
                if not (scenario / name).is_file():
                    errors.append(
                        f"{item['run_id']}: installation input missing: "
                        f"{scenario / name}"
                    )
            if not (scenario / "fixture").is_dir():
                errors.append(
                    f"{item['run_id']}: installation fixture directory missing"
                )

    for run_id in DIRECT_RUN_IDS:
        item = index.get(run_id)
        if item is None:
            continue
        peer = item.get("compares_to_run_id")
        peer_item = index.get(peer, {})
        if (
            peer not in index
            or peer_item.get("surface") != "maude"
            or peer_item.get("scenario_id") != item.get("scenario_id")
        ):
            errors.append(f"{run_id}: comparator peer is absent or scenario-mismatched")
        else:
            for field in (
                "persona_id",
                "operator_model_config",
                "grader_model_config",
            ):
                if item.get(field) != peer_item.get(field):
                    errors.append(
                        f"{run_id}: direct comparator {field} differs from peer"
                    )
            if peer_item.get("direct_comparator_run_id") != run_id:
                errors.append(
                    f"{run_id}: Maude comparator link is not reciprocal"
                )
            scenario = SCENARIOS_DIR / str(item.get("scenario_id"))
            control_path = (
                PACKET_DIR / "direct-runtime" / "fixtures" / f"{run_id}.json"
            )
            packet_path = scenario / "packet.json"
            patch_path = scenario / "patch.diff"
            if not all(
                path.is_file()
                for path in (control_path, packet_path, patch_path)
            ):
                errors.append(
                    f"{run_id}: direct-pair task-material linkage files missing"
                )
            else:
                control = load_json(control_path)
                packet = load_json(packet_path)
                ration = load_json(scenario / "ration-card.json")
                expected_task_id = str(packet.get("packet_id") or "").removeprefix(
                    "packet-"
                )
                patch_paths = {
                    line[6:]
                    for line in patch_path.read_text(
                        encoding="utf-8"
                    ).splitlines()
                    if line.startswith("+++ b/") and line != "+++ /dev/null"
                }
                direct_paths = set(control.get("allowed_paths") or [])
                declared_patterns = ration.get("allowed_write_paths") or []
                if (
                    control.get("run_id") != run_id
                    or control.get("task_id") != expected_task_id
                    or not patch_paths.issubset(direct_paths)
                    or any(
                        not any(
                            fnmatch.fnmatchcase(path, pattern)
                            for pattern in declared_patterns
                        )
                        for path in direct_paths
                    )
                    or control.get("candidate_patch") != "candidate.patch"
                ):
                    errors.append(
                        f"{run_id}: direct fixture is not linked to the peer's "
                        "exact task packet/patch material"
                    )
        expected_scope = (
            "capability-limited: preserves the client-restart and durable-state "
            "question, but the direct surface cannot reproduce or claim Maude "
            "daemon recovery"
            if run_id == "docket-s17"
            else "task-equivalent"
        )
        if item.get("comparison_scope") != expected_scope:
            errors.append(
                f"{run_id}: comparison scope is absent or inaccurate"
            )

    try:
        track = load_json(INSTALL_TRACK_PATH)
    except CampaignError as exc:
        errors.append(str(exc))
        track = {}
    if track.get("schema") != "maude.synthetic-install-track.v1":
        errors.append("installation track schema is absent or wrong")
    install_rows = [
        item
        for item in matrix_runs(matrix)
        if item.get("surface") == "maude-installation"
    ]
    if track.get("run_ids") != [item["run_id"] for item in install_rows]:
        errors.append("installation track run order differs from the matrix")
    derived_roles: dict[str, list[str]] = {}
    derived_coverage: dict[str, list[str]] = {}
    for item in install_rows:
        derived_roles.setdefault(str(item.get("persona_id")), []).append(
            item["run_id"]
        )
        for category in item.get("coverage", []):
            derived_coverage.setdefault(str(category), []).append(item["run_id"])
    if track.get("role_mapping") != derived_roles:
        errors.append("installation track role mapping differs from the matrix")
    if track.get("coverage_mapping") != derived_coverage:
        errors.append("installation track coverage mapping differs from the matrix")
    for item in install_rows:
        scenario = SCENARIOS_DIR / item["scenario_id"]
        try:
            task = load_json(scenario / "task.json")
            environment = load_json(scenario / "environment.json")
            expected = load_json(scenario / "expected-disposition.json")
        except CampaignError as exc:
            errors.append(str(exc))
            continue
        for source, field, expected_value in (
            (task, "task_id", item.get("task_id")),
            (environment, "task_id", item.get("task_id")),
            (expected, "task_id", item.get("task_id")),
            (environment, "source_visibility", item.get("source_visibility")),
            (expected, "coverage", item.get("coverage")),
        ):
            if source.get(field) != expected_value:
                errors.append(
                    f"{item['run_id']}: {field} differs between matrix and "
                    "installation corpus"
                )
        declared_materials = item.get("visible_materials")
        if (
            not isinstance(declared_materials, list)
            or not all(
                isinstance(value, str) and value
                for value in declared_materials
            )
            or len(declared_materials) != len(set(declared_materials))
        ):
            errors.append(
                f"{item['run_id']}: visible-material declaration is malformed"
            )
            continue
        fixture_destinations = {
            "handoff.json": "task/handoff.json",
            "media/release-handoff.json": "task/release-handoff.json",
            "config/settings.env": "config/settings.env",
            "state/ownership.json": "task/state-ownership.json",
            "state/prior-installation.json": "state/prior-installation.json",
            "run/endpoint-ownership.json": "task/endpoint-ownership.json",
            "project/ownership.json": "project/ownership.json",
            (
                "project/.governor/ownership.json"
            ): "project/.governor/ownership.json",
        }
        expected_materials = {
            "README.md",
            "operator-pty",
            "operator-retrospective",
            "docs/README.md",
            "docs/commands.md",
            "docs/configuration.md",
            "pyproject.toml",
            "task/assignment.md",
            "task/task.json",
        }
        for path in sorted((scenario / "fixture").rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(scenario / "fixture").as_posix()
            destination = fixture_destinations.get(relative)
            if destination is None:
                errors.append(
                    f"{item['run_id']}: visible fixture destination is "
                    f"undeclared for {relative}"
                )
            else:
                expected_materials.add(destination)
        if item.get("source_visibility") == "installed-distribution":
            expected_materials.add(
                "frozen installed Maude distribution and console entry point"
            )
        elif item.get("source_visibility") == "release-source":
            expected_materials.add(
                "frozen baseline release-source archive"
            )
        if set(declared_materials) != expected_materials:
            errors.append(
                f"{item['run_id']}: visible-material declaration differs: "
                f"missing={sorted(expected_materials - set(declared_materials))!r} "
                f"extra={sorted(set(declared_materials) - expected_materials)!r}"
            )
    for persona in REQUIRED_INSTALL_PERSONAS:
        family_configs = {
            item["operator_model_config"]
            for item in install_rows
            if item.get("persona_id") == persona
        }
        if not family_configs or not family_configs.issubset(
            set(operator_configs_used)
        ):
            errors.append(
                f"{persona}: installation operator provider coverage differs"
            )
    return errors


def selected_runs(
    requested: list[str] | None,
    *,
    surfaces: set[str] | None = None,
) -> list[dict[str, Any]]:
    index = run_index()
    if requested:
        unknown = set(requested) - set(index)
        if unknown:
            raise CampaignError(f"unknown run IDs: {sorted(unknown)}")
        items = [index[run_id] for run_id in requested]
    else:
        items = list(index.values())
    if surfaces is not None:
        items = [item for item in items if item.get("surface") in surfaces]
    return items


def ensure_safe_lab_path(path: Path) -> None:
    resolved = path.resolve()
    root = LAB_ROOT.resolve()
    if resolved == root or root not in resolved.parents:
        raise CampaignError(f"refusing path outside per-run synthetic lab: {path}")


def manifest_artifact_map(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    artifacts = manifest.get("frozen_artifacts")
    if not isinstance(artifacts, list):
        raise CampaignError("manifest frozen_artifacts is not an array")
    result: dict[str, dict[str, Any]] = {}
    for record in artifacts:
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            raise CampaignError("manifest contains an invalid artifact record")
        if record["path"] in result:
            raise CampaignError(f"duplicate manifest artifact: {record['path']}")
        result[record["path"]] = record
    return result


def validate_manifest_hashes(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for rel, expected in manifest_artifact_map(manifest).items():
        path = REPO_ROOT / rel
        if not path.is_file():
            errors.append(f"missing frozen artifact: {rel}")
            continue
        actual = file_record(path)
        if actual["bytes"] != expected.get("bytes"):
            errors.append(
                f"byte mismatch for {rel}: {actual['bytes']} != {expected.get('bytes')}"
            )
        if actual["sha256"] != expected.get("sha256"):
            errors.append(
                f"SHA-256 mismatch for {rel}: "
                f"{actual['sha256']} != {expected.get('sha256')}"
            )
    return errors
