#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Freeze and verify the immutable inputs for one synthetic-operator campaign.

This program prepares prompts and manifests only.  It never starts Maude,
Docket, a model session, or a grader, and it has no authority effect.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import grader_surface_probe
import finalize_provider_assignments
from campaign_common import (
    AUTH_GATE_PROBE_PATH,
    CAMPAIGN_ID,
    DIRECT_RUN_IDS,
    DOCKET_COMMIT,
    EVAL_ROOT,
    HARNESS_DIR,
    INSTALL_SURFACE_PROBE_PATH,
    INSTALL_TRACK_PATH,
    LAB_ROOT,
    MANIFEST_PATH,
    MATRIX_PATH,
    PACKET_DIR,
    PERSONAS_DIR,
    PREPARATION_BASE_COMMIT,
    PROVIDER_CAPABILITY_POLICY_PATH,
    PROVIDER_MODEL_CONFIGS,
    REPO_ROOT,
    SCENARIOS_DIR,
    SUT_COMMIT,
    SUPPORTED_PROVIDER_CONFIGS,
    CampaignError,
    file_record,
    inventory_files,
    load_json,
    load_matrix,
    manifest_artifact_map,
    media_type_for_path,
    matrix_runs,
    sha256_file,
    validate_manifest_hashes,
    validate_matrix,
    write_json,
    write_text,
)


MANIFEST_SCHEMA = "maude.synthetic-operator.campaign-manifest.v1"
OPERATOR_DOC_SOURCES = (
    REPO_ROOT / "docs" / "commands.md",
    REPO_ROOT / "docs" / "configuration.md",
)
INSTALL_OPERATOR_DOC_SOURCES = (
    (REPO_ROOT / "README.md", Path("README.md")),
    (REPO_ROOT / "docs" / "README.md", Path("docs/README.md")),
    (REPO_ROOT / "docs" / "commands.md", Path("docs/commands.md")),
    (
        REPO_ROOT / "docs" / "configuration.md",
        Path("docs/configuration.md"),
    ),
    (REPO_ROOT / "pyproject.toml", Path("pyproject.toml")),
)
INSTALL_DOC_PACKET_DIR = PACKET_DIR / "installation-docs"
INSTALL_MEDIA_DIR = PACKET_DIR / "installation-media"
INITIAL_REPOSITORY_OBSERVATION = PACKET_DIR / "initial-repository-observation.json"
SUCCESSOR_LINEAGE = PACKET_DIR / "successor-lineage.json"
INSTALL_MEDIA_PROVENANCE = INSTALL_MEDIA_DIR / "provenance.json"
INSTALL_SOURCE_ARCHIVE = INSTALL_MEDIA_DIR / "sources" / "maude-2.4.0.tar"
OPERATOR_RETROSPECTIVE = HARNESS_DIR / "operator_retrospective.py"
OPERATOR_PTY = HARNESS_DIR / "operator_pty.py"
CLAUDE_MCP_BRIDGE = HARNESS_DIR / "claude_mcp_bridge.py"
PUBLIC_CLI_BROKER = HARNESS_DIR / "public_cli_broker.py"
FINALIZE_PROVIDER_ASSIGNMENTS = HARNESS_DIR / "finalize_provider_assignments.py"
PROVIDER_ASSIGNMENT_SELFTEST = HARNESS_DIR / "provider_assignment_selftest.py"
CLAUDE_MCP_PROTOCOL_VERSION = "2025-11-25"
CODEX_MCP_PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_MCP_PROTOCOL_VERSIONS = [
    CODEX_MCP_PROTOCOL_VERSION,
    CLAUDE_MCP_PROTOCOL_VERSION,
]
CLAUDE_OPERATOR_TOOLS = ["mcp__operator__terminal"]
CLAUDE_GRADER_TOOLS = ["mcp__grader__evidence"]
CODEX_OPERATOR_TOOLS = ["terminal"]
CODEX_GRADER_TOOLS = ["evidence"]
CODEX_DISABLED_INTRINSIC_ACTION_FEATURES = [
    "shell_tool",
    "unified_exec",
]
CODEX_DISABLED_OPTIONAL_FEATURES = [
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
]
CODEX_APPROVAL_POLICY = "never"
CODEX_APPROVAL_CONFIG = 'approval_policy="never"'
CODEX_APPROVAL_CONFIG_ARGV = ["--config", CODEX_APPROVAL_CONFIG]
CODEX_MCP_DEFAULT_TOOLS_APPROVAL_MODE = "approve"
CODEX_PROBE_TERMINAL_TIMEOUT_SECONDS = 30
CLAUDE_BRIDGE_SHA256 = (
    "bdcd2daa927e382ff3e9a82d9c2feaf384a0d157f255ffa4c9af6688a2e021b2"
)
CLAUDE_RUNNER_SHA256 = (
    "aa625db34bb6caf75830bfbb15af5f0b69fa91c127bc8809e06c66f3bb9f994f"
)
OPERATOR_PTY_SHA256 = "ea41701e54cc101aa44dba9b2d24382a6859847685051409defad6d414d0b46e"
PUBLIC_CLI_SHA256 = "d5dd589b11e42624466867dfc28e0c9663ebdcf345e6769cf6f59af080f2d0b6"
PUBLIC_CLI_BROKER_SHA256 = (
    "fafe3e530fa91ca0ec0e7164c1607ad76d53527d109375934139e36998eac575"
)
AUTH_GATE_SELFTEST_SHA256 = (
    "d09cdd0b06d59feabfe1216375cf8645bfa0ad585388c2faba38d319b0e53f7e"
)
CAMPAIGN_COMMON_SHA256 = (
    "234b32cb2d2a2f542184c0f1b247154033d184aa357cb1e825335e8108fca4a7"
)
GRADER_SURFACE_PROBE_SHA256 = (
    "7e28828f00a98333975ae5dfb9a42a0d8c8941ab332917185a617717b300e854"
)
FINALIZE_PROVIDER_ASSIGNMENTS_SHA256 = (
    "3c07353b33848694ca809e95e17f8a5bd8f9999c339f3e3529d53c338fd474b0"
)
PROVIDER_ASSIGNMENT_SELFTEST_SHA256 = (
    "62f69b5f7a124a6143fd927a425dc5aa70ec79b808791e172f93259159ae8387"
)
HOST_SOURCE_ROOT = Path("/home/jbeck/git/agent_gov_ui")
INSTALL_ENDPOINT_DIR = PACKET_DIR / "installation-endpoints"
INSTALL_ENDPOINT_SPECS = {
    "install-i01": ("compatible", "task_handoff", "0660"),
    "install-i02": ("compatible", "default_governor_dir", "0660"),
    "install-i03": ("none", "none", None),
    "install-i04": ("unavailable", "task_handoff", None),
    "install-i05": ("compatible", "task_handoff", "0000"),
    "install-i06": ("compatible", "task_handoff", "0660"),
    "install-i07": ("incompatible-schema", "task_handoff", "0660"),
    "install-i08": ("wrong-service", "task_handoff", "0660"),
    "install-i09": ("none", "none", None),
    "install-i10": ("none", "none", None),
}
INSTALL_FIXTURE_DESTINATIONS = {
    "handoff.json": "task/handoff.json",
    "media/release-handoff.json": "task/release-handoff.json",
    "config/settings.env": "config/settings.env",
    "state/ownership.json": "task/state-ownership.json",
    "state/prior-installation.json": "state/prior-installation.json",
    "run/endpoint-ownership.json": "task/endpoint-ownership.json",
    "project/ownership.json": "project/ownership.json",
    ("project/.governor/ownership.json"): "project/.governor/ownership.json",
}
VISIBLE_SCENARIO_NAMES = (
    "packet.json",
    "plan.md",
    "playbook.json",
    "ration-card.json",
)
BRIDGE_TASK_HINT_FRAGMENTS = (
    "task/plan.md",
    "run task/",
    "supervised launch",
    "supervised promote",
    "supervised reject",
)
GRADER_TEMPLATE = """\
# Independent grade request

Grade exactly one synthetic operator run. The campaign runner replaces every
bracketed marker below with frozen or captured evidence before invoking a fresh
evaluator session.

## Frozen assigned role and task

{{GRADER_ASSIGNMENT}}

## Surface

{{SURFACE}}

## Frozen rubric

{{GRADING_RUBRIC}}

## Frozen failure taxonomy

{{FAILURE_TAXONOMY_JSON}}

## Relevant operator-facing documentation

{{OPERATOR_DOCUMENTATION}}

## Exact operator prompt

### System

{{OPERATOR_SYSTEM_PROMPT}}

### User

{{OPERATOR_PROMPT}}

## Numbered raw transcript rendering

{{TRANSCRIPT_TEXT}}

## Externally observable artifacts and system responses

{{OBSERVABLE_ARTIFACT_INDEX}}

Return only the required JSON object. Do not inspect any path outside the
grade bundle. The hidden expected-disposition file is not supplied.
"""


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _direct_task_text(text: str) -> str:
    """Adapt only the named surface for an otherwise task-equivalent control."""

    replacements = (
        ("using Maude", "using the supplied Docket/GWR surface"),
        ("through Maude", "through the supplied Docket/GWR surface"),
        ("access to Maude", "access to the supplied Docket/GWR surface"),
        ("Use Maude", "Use the supplied Docket/GWR surface"),
        ("Maude commands", "Docket/GWR commands"),
        ("Maude help", "Docket/GWR help"),
        ("what Maude was", "what the supplied Docket/GWR surface was"),
        ("Maude was", "the supplied Docket/GWR surface was"),
        ("Maude", "the supplied Docket/GWR surface"),
    )
    for old, new in replacements:
        text = text.replace(old, new)
    return text


def _markdown_section(text: str, heading: str) -> str:
    marker = f"## {heading}\n"
    if marker not in text:
        raise CampaignError(f"scenario README lacks {marker.strip()!r}")
    tail = text.split(marker, 1)[1]
    return tail.split("\n## ", 1)[0].strip()


def _render_direct_task(scenario_id: str) -> str:
    source = _read(SCENARIOS_DIR / scenario_id / "README.md")
    title = source.splitlines()[0]
    task_id = f"ux-task-{scenario_id[1:3]}"
    situation = _markdown_section(source, "Situation")
    task_section = _markdown_section(source, "Supplied task")
    supplied_task = task_section.split("\n\n", 1)[0].strip()
    review = _markdown_section(source, "Review condition")
    if scenario_id == "s17-client-daemon-restart":
        situation = (
            "A prior direct-runtime client process ended after this synthetic "
            "attempt reached the reserved state. This is a new client process "
            "opening the same durable Docket state. The comparator does not "
            "claim that a daemon was recovered."
        )
    return f"""\
{title}

**Task ID:** `{task_id}`

## Situation

{situation}

## Supplied task

{supplied_task}

The equivalent direct-runtime materials are `control.json`, `candidate.patch`,
the synthetic repository named by the control, and the Docket/GWR operator
documents under `docs/`. The supplied packet description is `task/packet.json`.
No Maude plan, playbook, ration card, or approval witness is part of this
comparison surface.

Use only the supplied Docket/GWR public CLI. Do not edit the repository
directly, widen the admitted paths, bypass a refusal, use a live endpoint, or
perform an external side effect.

## Review condition

{review}
"""


def _render_maude_task(scenario_id: str) -> str:
    source = _read(SCENARIOS_DIR / scenario_id / "README.md")
    title = source.splitlines()[0]
    task_id = f"ux-task-{scenario_id[1:3]}"
    situation = _markdown_section(source, "Situation")
    task_section = _markdown_section(source, "Supplied task")
    supplied_task = task_section.split("\n\n", 1)[0].strip()
    review = _markdown_section(source, "Review condition")
    return f"""\
{title}

**Task ID:** `{task_id}`

## Situation

{situation}

## Supplied task

{supplied_task}

The bounded plan is `plan.md`. Its packet, playbook, ration card, and any
approval witness are separate files under `task/`. The disposable repository
is the sibling `../repo` directory.

Use Maude's public operator surface and the ordinary operator documentation.
Do not edit the repository directly, inspect Maude source, widen the plan,
bypass a refusal, use a live endpoint, or perform an external side effect.

## Review condition

{review}
"""


def _render_install_task(run: dict[str, Any]) -> str:
    """Render only fields in the neutral, operator-visible task document."""

    source = load_json(SCENARIOS_DIR / run["scenario_id"] / "task.json")
    if source.get("task_id") != run.get("task_id"):
        raise CampaignError(f"{run['run_id']}: installation task identity mismatch")
    handoff = json.dumps(
        source.get("handoff", {}),
        indent=2,
        ensure_ascii=False,
        sort_keys=True,
    )
    constraints = json.dumps(
        source.get("constraints", {}),
        indent=2,
        ensure_ascii=False,
        sort_keys=True,
    )
    evidence = "\n".join(f"- {item}" for item in source.get("evidence_requested", []))
    return f"""\
# Maude installation task

**Task ID:** `{source["task_id"]}`
**Component:** `{source["component"]}`

## Situation

{source["situation"]}

## Goal

{source["goal"]}

## Handoff

```json
{handoff}
```

## Constraints

```json
{constraints}
```

## Evidence requested

{evidence}

## Review condition

{source["review_condition"]}
"""


def _render_operator_task(run: dict[str, Any]) -> str:
    if run["surface"] == "docket-gwr-direct":
        return _render_direct_task(run["scenario_id"])
    if run["surface"] == "maude-installation":
        return _render_install_task(run)
    return _render_maude_task(run["scenario_id"])


def _scenario_approval(scenario: Path) -> Path | None:
    matches = sorted(scenario.glob("lab_approval_*"))
    if len(matches) > 1:
        raise CampaignError(f"multiple approval witnesses in {scenario}")
    return matches[0] if matches else None


def _visible_scenario_paths(scenario: Path) -> list[Path]:
    paths = [scenario / name for name in VISIBLE_SCENARIO_NAMES]
    approval = _scenario_approval(scenario)
    if approval is not None:
        paths.append(approval)
    return [path for path in paths if path.is_file()]


def _regular_files(root: Path, *, label: str) -> list[Path]:
    """Enumerate a visible input tree and fail closed on special entries."""

    if not root.is_dir():
        raise CampaignError(f"{label}: required directory is absent: {root}")
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise CampaignError(f"{label}: non-regular path is forbidden: {path}")
        if path.is_file():
            files.append(path)
    return files


def _install_fixture_pairs(
    scenario: Path,
) -> list[tuple[Path, str]]:
    fixture = scenario / "fixture"
    pairs: list[tuple[Path, str]] = []
    seen_destinations: set[str] = set()
    for path in _regular_files(fixture, label="installation fixture"):
        relative = path.relative_to(fixture).as_posix()
        destination = INSTALL_FIXTURE_DESTINATIONS.get(relative)
        if destination is None:
            raise CampaignError(
                f"installation fixture lacks neutral destination: {relative}"
            )
        if destination in seen_destinations:
            raise CampaignError(
                f"duplicate installation fixture destination: {destination}"
            )
        seen_destinations.add(destination)
        pairs.append((path, destination))
    return pairs


def _render_operator_prompt(run: dict[str, Any]) -> str:
    run_id = run["run_id"]
    persona = _read(PERSONAS_DIR / f"{run['persona_id']}.md").strip()
    task = _render_operator_task(run).strip()
    if run["surface"] == "docket-gwr-direct":
        persona = _direct_task_text(persona)
    run_root = LAB_ROOT / run_id
    operator_root = run_root / "operator"

    if run["surface"] == "maude":
        surface = f"""\
Your working directory is `{operator_root}`.

The public human surface is `./maude`. The disposable repository is `../repo`.
Ordinary command and configuration documentation is under `docs/`; the
bounded packet and supporting operator material is under `task/`.

Use shell and read operations only to invoke the public surface and inspect
operator-visible files or repository effects. Do not edit repository files
directly. The terminal adapter flags documented by `./maude --cli-help` model
terminal actions; they are not extra Maude semantics.
"""
    elif run["surface"] == "docket-gwr-direct":
        surface = f"""\
Your working directory is `{operator_root}`.

The direct comparison surface is the frozen `./bin/docket` CLI and its
operator runbook under `docs/`. The synthetic control identifiers and paths
you were handed are in `control.json`; the disposable repository and state
store are at the absolute paths named there. The bounded task material is
under `task/`.

Use shell and read operations only to invoke this direct public surface and
inspect operator-visible files or repository effects. Do not edit repository
files directly. Do not inspect the comparison implementation.
"""
    else:
        install_root = run_root / "installation"
        source_visibility = run["source_visibility"]
        if source_visibility == "installed-distribution":
            public_surface = (
                "A mechanically installed Maude console entry point is "
                "`../venv/bin/maude`."
            )
        elif source_visibility == "release-source":
            public_surface = (
                "No Maude executable is preinstalled. The handed-off filtered "
                "source archive is `../media/maude-source.tar`."
            )
        else:
            public_surface = (
                "No Maude source archive, installed distribution, or Maude "
                "executable is supplied."
            )
        surface = f"""\
Your working directory is `{install_root / "operator"}`.

{public_surface}

The exact baseline documents are `../README.md`, `../docs/README.md`,
`../docs/commands.md`, `../docs/configuration.md`, and `../pyproject.toml`.
The neutral assignment and handed-off inputs are under `../task/`.

The evaluator-only `./operator-pty` helper provides persistent PTY transport
because the provider shell has no human terminal. Use `./operator-pty --help`
to learn its generic start/read/send/status/stop syntax when an interactive
executable is needed. It permits adaptive interaction across provider tool
calls, preserves exact PTY bytes, and adds no Maude commands or workflow
semantics. Its wrapper is not an extra product command; the wrapped
operator-selected product command counts once.

Use the ordinary shell, system Python, pip, Git, supplied files, and any
installed Maude public entry point exactly as an operator would. Do not inspect
product internals merely to discover an expected answer. Do not use the
network, sudo, a sibling checkout, host configuration, production resources,
or evaluator-only files. Do not take ownership of a separately managed
Governor service or retained state.
"""

    return f"""\
# Synthetic operator assignment

**Campaign:** `{CAMPAIGN_ID}`
**Run:** `{run_id}`
**Surface:** `{run["surface"]}`

## Operator role

{persona}

## Operational situation and task

{task}

## Supplied lab

{surface.strip()}

No evaluator will answer questions or coach you after this session starts.
Work from the visible evidence and stop safely if it is insufficient. Follow
the system instructions for freezing your initial disposition before the
post-task retrospective is revealed.
"""


def _render_grader_assignment(run: dict[str, Any]) -> str:
    persona = _read(PERSONAS_DIR / f"{run['persona_id']}.md").strip()
    task = _render_operator_task(run).strip()
    if run["surface"] == "docket-gwr-direct":
        persona = _direct_task_text(persona)
    rubric_id = (
        "maude-synthetic-installation-rubric-v1"
        if run["surface"] == "maude-installation"
        else "maude-synthetic-operator-rubric-v1"
    )
    return f"""\
# Frozen grader assignment

**Campaign:** `{CAMPAIGN_ID}`
**Run:** `{run["run_id"]}`
**Surface:** `{run["surface"]}`
**Rubric:** `{rubric_id}`
**Taxonomy:** `maude-synthetic-failure-taxonomy-v1`

## Assigned operator role

{persona}

## Assigned realistic task

{task}

The raw transcript and observable artifacts do not exist at freeze time. The
campaign runner must render them into the frozen grader request template after
the operator session. It must not supply `expected-disposition.json`,
implementation source, prior runs, or evaluator commentary.
"""


def _copy_operator_docs() -> None:
    target = PACKET_DIR / "operator-docs"
    target.mkdir(parents=True, exist_ok=True)
    for source in OPERATOR_DOC_SOURCES:
        if not source.is_file():
            raise CampaignError(f"missing operator document: {source}")
        shutil.copyfile(source, target / source.name)


def _copy_install_operator_docs() -> None:
    for source, relative in INSTALL_OPERATOR_DOC_SOURCES:
        if not source.is_file():
            raise CampaignError(f"missing installation operator document: {source}")
        target = INSTALL_DOC_PACKET_DIR / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def _copy_linked_direct_docs() -> None:
    """Materialize the ordinary documents linked by the frozen runbook."""

    archive = PACKET_DIR / "direct-runtime" / "source-9050a53.tar"
    if not archive.is_file():
        raise CampaignError(f"missing frozen Docket source archive: {archive}")
    mapping = {
        "docs/governed-runtime/trust-model.md": (
            PACKET_DIR / "direct-runtime" / "docs" / "trust-model.md"
        ),
        "docs/governed-runtime/repository-identity-and-ref-continuity.md": (
            PACKET_DIR
            / "direct-runtime"
            / "docs"
            / "repository-identity-and-ref-continuity.md"
        ),
        "docs/governed-runtime/effect-classes.md": (
            PACKET_DIR / "direct-runtime" / "docs" / "effect-classes.md"
        ),
    }
    with tarfile.open(archive, "r") as handle:
        for member_name, target in mapping.items():
            try:
                member = handle.getmember(member_name)
            except KeyError as exc:
                raise CampaignError(
                    f"linked direct-runtime document absent from archive: {member_name}"
                ) from exc
            source = handle.extractfile(member)
            if source is None:
                raise CampaignError(
                    f"linked direct-runtime document is not a file: {member_name}"
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read())


def _installation_endpoint_plan(run: dict[str, Any]) -> dict[str, Any]:
    try:
        mode, socket_strategy, chmod = INSTALL_ENDPOINT_SPECS[run["run_id"]]
    except KeyError as exc:
        raise CampaignError(
            f"missing installation endpoint specification: {run['run_id']}"
        ) from exc
    if run.get("surface") != "maude-installation":
        raise CampaignError(
            f"endpoint plan requested for non-installation run: {run['run_id']}"
        )
    task = load_json(SCENARIOS_DIR / run["scenario_id"] / "task.json")
    if task.get("task_id") != run.get("task_id"):
        raise CampaignError(f"{run['run_id']}: endpoint plan task identity mismatch")
    generated_directories = (
        ["project/.governor"] if socket_strategy == "default_governor_dir" else []
    )
    governor_dir = (
        str(LAB_ROOT / run["run_id"] / "installation" / "project" / ".governor")
        if socket_strategy == "default_governor_dir"
        else None
    )
    return {
        "schema": "maude.synthetic-installation-endpoint-plan.v1",
        "campaign_id": CAMPAIGN_ID,
        "run_id": run["run_id"],
        "task_id": run["task_id"],
        "mode": mode,
        "socket_strategy": socket_strategy,
        "chmod": chmod,
        "generated_directories": generated_directories,
        "governor_dir": governor_dir,
        "authority_effect": "none",
    }


def _render_installation_endpoint_plans(matrix: dict[str, Any]) -> None:
    install_runs = [
        run for run in matrix_runs(matrix) if run["surface"] == "maude-installation"
    ]
    actual_ids = {run["run_id"] for run in install_runs}
    if actual_ids != set(INSTALL_ENDPOINT_SPECS):
        raise CampaignError(
            "installation endpoint plan run set differs from matrix: "
            f"expected={sorted(INSTALL_ENDPOINT_SPECS)!r} "
            f"actual={sorted(actual_ids)!r}"
        )
    INSTALL_ENDPOINT_DIR.mkdir(parents=True, exist_ok=True)
    for run in install_runs:
        write_json(
            INSTALL_ENDPOINT_DIR / f"{run['run_id']}.json",
            _installation_endpoint_plan(run),
        )


def _validate_installation_endpoint_plans(
    matrix: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    expected_names = {f"{run_id}.json" for run_id in INSTALL_ENDPOINT_SPECS}
    if not INSTALL_ENDPOINT_DIR.is_dir():
        return [f"installation endpoint-plan directory absent: {INSTALL_ENDPOINT_DIR}"]
    try:
        paths = _regular_files(
            INSTALL_ENDPOINT_DIR, label="installation endpoint plans"
        )
    except CampaignError as exc:
        return [str(exc)]
    actual_names = {path.name for path in paths}
    if actual_names != expected_names:
        errors.append(
            "installation endpoint-plan file set differs: "
            f"expected={sorted(expected_names)!r} "
            f"actual={sorted(actual_names)!r}"
        )
    by_id = {run["run_id"]: run for run in matrix_runs(matrix)}
    for run_id in sorted(INSTALL_ENDPOINT_SPECS):
        path = INSTALL_ENDPOINT_DIR / f"{run_id}.json"
        if not path.is_file():
            continue
        try:
            actual = load_json(path)
            expected = _installation_endpoint_plan(by_id[run_id])
        except (CampaignError, KeyError) as exc:
            errors.append(str(exc))
            continue
        if actual != expected:
            errors.append(f"installation endpoint plan differs: {run_id}")
    return errors


def _render_prompts(matrix: dict[str, Any]) -> None:
    prompt_root = PACKET_DIR / "rendered"
    for run in matrix_runs(matrix):
        target = prompt_root / run["run_id"]
        operator_system = _read(PACKET_DIR / "prompts" / "operator-system.md")
        if run["surface"] == "maude-installation":
            operator_system = _read(
                PACKET_DIR / "prompts" / "installation-operator-system.md"
            )
        elif run["surface"] == "docket-gwr-direct":
            operator_system = _direct_task_text(operator_system)
            source_control = load_json(
                PACKET_DIR / "direct-runtime" / "fixtures" / f"{run['run_id']}.json"
            )
            allowed_control_fields = (
                "surface",
                "state_path",
                "repository_path",
                "repository_id",
                "target_ref",
                "basis_commit",
                "work_request_id",
                "candidate_id",
                "candidate_digest",
                "attempt_id",
                "prepared_attempt_digest",
                "standing_grant_id",
                "standing_token",
                "standing_actor",
                "assigned_actor",
                "allowed_paths",
                "candidate_patch",
                "standing_ttl_ms",
                "setup_reservation_ttl_ms",
                "authority_effect",
            )
            write_json(
                target / "direct-control.json",
                {
                    "schema": "maude.synthetic-docket-operator-control.v1",
                    "campaign_id": CAMPAIGN_ID,
                    "run_id": run["run_id"],
                    "task_id": f"ux-task-{run['scenario_id'][1:3]}",
                    **{
                        key: source_control[key]
                        for key in allowed_control_fields
                        if key in source_control
                    },
                },
            )
        write_text(target / "operator-task.md", _render_operator_task(run))
        write_text(target / "operator-system.md", operator_system)
        write_text(target / "operator-prompt.md", _render_operator_prompt(run))
        write_text(target / "grader-assignment.md", _render_grader_assignment(run))
        write_json(target / "supplied-inputs.json", _frozen_supplied_inputs(run))
        write_json(target / "session-config.json", _frozen_session_config(run, matrix))
    write_text(PACKET_DIR / "prompts" / "grader-request-template.md", GRADER_TEMPLATE)


def _forbidden_scenario_slugs(matrix: dict[str, Any]) -> tuple[bytes, ...]:
    return tuple(
        value.encode("utf-8")
        for value in sorted(
            {
                run["scenario_id"]
                for run in matrix_runs(matrix)
                if isinstance(run.get("scenario_id"), str)
            }
        )
    )


def _scan_visible_file(
    path: Path,
    forbidden: tuple[bytes, ...],
    *,
    label: str,
) -> list[str]:
    errors: list[str] = []
    name = path.name.encode("utf-8")
    data = path.read_bytes()
    for slug in forbidden:
        decoded = slug.decode("utf-8")
        if slug in name:
            errors.append(f"{label}: internal scenario slug in filename: {decoded}")
        if slug in data:
            errors.append(f"{label}: internal scenario slug in file bytes: {decoded}")
    return errors


def _validate_operator_surface_sanitization(
    matrix: dict[str, Any],
    *,
    include_rendered: bool,
) -> list[str]:
    """Reject evaluator-internal scenario labels from every operator surface."""

    errors: list[str] = []
    forbidden = _forbidden_scenario_slugs(matrix)
    direct = PACKET_DIR / "direct-runtime"
    common_direct_files = [
        direct / "bin" / "docket",
        direct / "bin" / "gwr-git-broker",
        *sorted((direct / "docs").glob("*.md")),
    ]
    for run in matrix_runs(matrix):
        scenario = SCENARIOS_DIR / run["scenario_id"]
        try:
            visible = _regular_files(
                scenario / "fixture",
                label=f"{run['run_id']} visible fixture",
            )
        except CampaignError as exc:
            errors.append(str(exc))
            visible = []
        if run["surface"] == "maude":
            visible.extend(_visible_scenario_paths(scenario))
            visible.extend(
                [
                    HARNESS_DIR / "maude",
                    HARNESS_DIR / "public_cli.py",
                    OPERATOR_RETROSPECTIVE,
                    *OPERATOR_DOC_SOURCES,
                ]
            )
        elif run["surface"] == "docket-gwr-direct":
            visible.extend(
                [
                    scenario / "packet.json",
                    scenario / "patch.diff",
                    OPERATOR_RETROSPECTIVE,
                    *common_direct_files,
                ]
            )
        else:
            visible.extend(
                [
                    scenario / "task.json",
                    OPERATOR_RETROSPECTIVE,
                    OPERATOR_PTY,
                    *(source for source, _relative in INSTALL_OPERATOR_DOC_SOURCES),
                ]
            )
            if run["source_visibility"] == "release-source":
                visible.append(INSTALL_SOURCE_ARCHIVE)
        if include_rendered:
            rendered = PACKET_DIR / "rendered" / run["run_id"]
            visible.extend(
                [
                    rendered / "operator-task.md",
                    rendered / "operator-system.md",
                    rendered / "operator-prompt.md",
                    rendered / "grader-assignment.md",
                ]
            )
            if run["surface"] == "docket-gwr-direct":
                visible.append(rendered / "direct-control.json")
        for path in visible:
            if not path.is_file():
                errors.append(f"{run['run_id']}: visible file is absent: {path}")
                continue
            errors.extend(
                _scan_visible_file(
                    path,
                    forbidden,
                    label=f"{run['run_id']}:{path.name}",
                )
            )

        if run["surface"] != "docket-gwr-direct":
            continue
        archive = direct / "fixtures" / f"{run['run_id']}.tar"
        try:
            with tarfile.open(archive, "r") as handle:
                for member in handle.getmembers():
                    member_name = member.name.encode("utf-8")
                    for slug in forbidden:
                        if slug in member_name:
                            errors.append(
                                f"{run['run_id']}:{archive.name}: internal scenario "
                                f"slug in member path: {slug.decode('utf-8')}"
                            )
                    if not member.isfile():
                        continue
                    source = handle.extractfile(member)
                    if source is None:
                        errors.append(
                            f"{run['run_id']}:{archive.name}: unreadable regular "
                            f"member {member.name}"
                        )
                        continue
                    data = source.read()
                    for slug in forbidden:
                        if slug in data:
                            errors.append(
                                f"{run['run_id']}:{archive.name}:{member.name}: "
                                "internal scenario slug in archive member bytes: "
                                f"{slug.decode('utf-8')}"
                            )
        except (OSError, tarfile.TarError) as exc:
            errors.append(f"{run['run_id']}: cannot scan direct archive: {exc}")
    return errors


def _frozen_supplied_inputs(run: dict[str, Any]) -> dict[str, Any]:
    scenario = SCENARIOS_DIR / run["scenario_id"]
    operator_task = PACKET_DIR / "rendered" / run["run_id"] / "operator-task.md"
    task_record = file_record(operator_task)
    task_record["destination"] = (
        "task/assignment.md"
        if run["surface"] == "maude-installation"
        else "task/README.md"
    )
    files: list[dict[str, Any]] = [task_record]
    if run["surface"] == "maude":
        for path in _visible_scenario_paths(scenario):
            record = file_record(path)
            record["destination"] = f"task/{path.name}"
            files.append(record)
        fixture_pairs = [
            (
                path,
                str(Path("../repo") / path.relative_to(scenario / "fixture")),
            )
            for path in _regular_files(
                scenario / "fixture",
                label=f"{run['run_id']} Maude fixture",
            )
        ]
    elif run["surface"] == "docket-gwr-direct":
        record = file_record(scenario / "packet.json")
        record["destination"] = "task/packet.json"
        files.append(record)
        fixture_pairs = [
            (
                path,
                str(Path("../repo") / path.relative_to(scenario / "fixture")),
            )
            for path in _regular_files(
                scenario / "fixture",
                label=f"{run['run_id']} direct fixture",
            )
        ]
    else:
        record = file_record(scenario / "task.json")
        record["destination"] = "task/task.json"
        files.append(record)
        fixture_pairs = _install_fixture_pairs(scenario)
    for path, destination in fixture_pairs:
        record = file_record(path)
        record["destination"] = destination
        files.append(record)

    retrospective_record = file_record(OPERATOR_RETROSPECTIVE)
    retrospective_record["destination"] = (
        "operator/operator-retrospective"
        if run["surface"] == "maude-installation"
        else "operator-retrospective"
    )
    retrospective_record["media_type"] = media_type_for_path(
        Path(retrospective_record["destination"]),
        OPERATOR_RETROSPECTIVE.read_bytes(),
    )
    files.append(retrospective_record)

    generated_visible_state: dict[str, Any] | None = None
    if run["surface"] == "maude":
        for path, destination in (
            (HARNESS_DIR / "maude", "maude"),
            (HARNESS_DIR / "public_cli.py", "public_cli.py"),
            (PACKET_DIR / "operator-docs" / "commands.md", "docs/commands.md"),
            (
                PACKET_DIR / "operator-docs" / "configuration.md",
                "docs/configuration.md",
            ),
        ):
            record = file_record(path)
            record["destination"] = destination
            files.append(record)
        fixture_archive = None
    elif run["surface"] == "docket-gwr-direct":
        direct = PACKET_DIR / "direct-runtime"
        pairs = [
            (direct / "bin" / "docket", "bin/docket"),
            (direct / "bin" / "gwr-git-broker", "bin/gwr-git-broker"),
            (
                PACKET_DIR / "rendered" / run["run_id"] / "direct-control.json",
                "control.json",
            ),
            (SCENARIOS_DIR / run["scenario_id"] / "patch.diff", "candidate.patch"),
        ]
        pairs.extend(
            (path, f"docs/{path.name}")
            for path in sorted((direct / "docs").glob("*.md"))
        )
        for path, destination in pairs:
            record = file_record(path)
            record["destination"] = destination
            files.append(record)
        fixture_archive = file_record(direct / "fixtures" / f"{run['run_id']}.tar")
    else:
        pty_record = file_record(OPERATOR_PTY)
        pty_record["destination"] = "operator/operator-pty"
        pty_record["media_type"] = media_type_for_path(
            Path(pty_record["destination"]),
            OPERATOR_PTY.read_bytes(),
        )
        files.append(pty_record)
        for _source, relative in INSTALL_OPERATOR_DOC_SOURCES:
            path = INSTALL_DOC_PACKET_DIR / relative
            record = file_record(path)
            record["destination"] = relative.as_posix()
            files.append(record)
        if run["source_visibility"] == "release-source":
            record = file_record(INSTALL_SOURCE_ARCHIVE)
            record["destination"] = "media/maude-source.tar"
            files.append(record)
        fixture_archive = file_record(INSTALL_MEDIA_PROVENANCE)
        generated_visible_state = {
            "kind": (
                "fresh offline installed distribution"
                if run["source_visibility"] == "installed-distribution"
                else "none"
            ),
            "destination": (
                "venv" if run["source_visibility"] == "installed-distribution" else None
            ),
            "materializer": (
                "literal system venv and pip --no-index --require-hashes"
                if run["source_visibility"] == "installed-distribution"
                else None
            ),
            "installation_media_provenance": file_record(INSTALL_MEDIA_PROVENANCE),
            "wheelhouse_mounted_for_operator": False,
            "setup_transcript_mounted_for_operator": False,
        }
    system = PACKET_DIR / "rendered" / run["run_id"] / "operator-system.md"
    prompt = PACKET_DIR / "rendered" / run["run_id"] / "operator-prompt.md"
    return {
        "schema": "maude.synthetic-operator.frozen-supplied-inputs.v1",
        "campaign_id": CAMPAIGN_ID,
        "run_id": run["run_id"],
        "surface": run["surface"],
        "system_prompt": file_record(system),
        "user_prompt": file_record(prompt),
        "visible_files": sorted(files, key=lambda item: item["destination"]),
        "evaluator_materialization_source": fixture_archive,
        "archive_mounted_for_operator": False,
        "setup_transcript_mounted_for_operator": False,
        "generated_visible_state": generated_visible_state,
        "terminal_bridge_disclosure": (
            {
                "implementation_visible": True,
                "artifact": "public_cli.py",
                "purpose": (
                    "evaluation-only public Unix-socket client; it exposes no "
                    "driver queue and adds no Maude commands or product semantics"
                ),
                "maude_or_runtime_implementation_source": False,
            }
            if run["surface"] == "maude"
            else None
        ),
        "withheld": _run_supplied_material(run)["deliberately_withheld"],
    }


def _session_provider_boundary(
    *,
    provider_config: str,
    role: str,
    execution_config: dict[str, Any],
) -> dict[str, Any]:
    if role not in {"operator", "grader"}:
        raise CampaignError(f"unknown provider session role: {role}")
    tool_key = "operator_tools" if role == "operator" else "grader_tools"
    boundary = {
        "provider_config": provider_config,
        "provider": execution_config["provider"],
        "role": role,
        "tools": execution_config[tool_key],
        "built_in_tools": execution_config["built_in_tools"],
        "mcp_protocol_version": execution_config["mcp_protocol_version"],
        "provider_network_permitted_for_session_transport": True,
        "locally_configured_provider_credentials_permitted_only_for_session_transport": (
            True
        ),
        "task_paths_or_task_sockets_visible_to_provider_transport": False,
        "task_level_network_permitted": False,
        "production_task_systems_or_credentials_permitted": False,
        "external_operational_effect_permitted": False,
        "fresh_process": True,
        "resume_continuation_or_follow_up": False,
    }
    if provider_config == "openai-sol":
        boundary.update(
            {
                "kind": (
                    "task-blind-retained-auth-codex-transport-with-"
                    "hash-pinned-stdio-mcp"
                ),
                "bare_mcp_tools": (
                    CODEX_OPERATOR_TOOLS if role == "operator" else CODEX_GRADER_TOOLS
                ),
                "intrinsic_action_features_disabled": (
                    CODEX_DISABLED_INTRINSIC_ACTION_FEATURES
                ),
                "optional_features_disabled": (CODEX_DISABLED_OPTIONAL_FEATURES),
                "approval_policy": CODEX_APPROVAL_POLICY,
                "mcp_default_tools_approval_mode": (
                    CODEX_MCP_DEFAULT_TOOLS_APPROVAL_MODE
                ),
                "trusted_stdio_shim_shares_retained_auth_transport": True,
                "trusted_stdio_shim_auth_read_observed": False,
            }
        )
    else:
        boundary.update(
            {
                "kind": (
                    "task-blind-retained-auth-claude-transport-with-"
                    "credential-free-mcp-proxy"
                ),
                "strict_mcp_config": True,
                "permission_mode": "bypassPermissions",
                "slash_commands_enabled": False,
                "browser_enabled": False,
                "session_persistence": False,
                "mcp_proxy_receives_provider_credentials": False,
                "mcp_proxy_has_external_network": False,
            }
        )
    if role == "operator":
        boundary.update(
            {
                "command_broker_receives_provider_credentials": False,
                "command_broker_receives_semantic_prompt": False,
                "each_command_uses_fresh_no_network_mount_pid_namespace": True,
            }
        )
    else:
        boundary.update(
            {
                "evidence_bundle_read_only": True,
                "command_broker_present": False,
            }
        )
    return boundary


def _frozen_session_config(
    run: dict[str, Any], matrix: dict[str, Any]
) -> dict[str, Any]:
    configs = _model_execution_configs(matrix)
    operator_config = json.loads(json.dumps(configs[run["operator_model_config"]]))
    grader_config = json.loads(json.dumps(configs[run["grader_model_config"]]))
    installation_socket = (
        _installation_socket_path(run)
        if run["surface"] == "maude-installation"
        else None
    )
    result = {
        "schema": "maude.synthetic-operator.frozen-session-config.v1",
        "campaign_id": CAMPAIGN_ID,
        "run_id": run["run_id"],
        "operator": operator_config,
        "grader": grader_config,
        "fresh_operator_process": True,
        "fresh_grader_process": True,
        "follow_up_messages": 0,
        "coaching": "none",
        "filesystem_isolation": (
            "task-blind provider transport plus an exact one-tool MCP "
            "surface; every operator command uses a fresh source-free, "
            "credential-free, no-network Bubblewrap namespace"
        ),
        "provider_transport_task_paths": [],
        "operator_command_mounts": (
            ["../repo"]
            if run["surface"] == "maude"
            else (
                ["../state", "../repo"]
                if run["surface"] == "docket-gwr-direct"
                else [
                    "../home",
                    "../work",
                    "../run",
                    "../project",
                    *(
                        ["../venv"]
                        if run["source_visibility"] == "installed-distribution"
                        else []
                    ),
                    "../task",
                ]
            )
        ),
        "operator_home_mount": "/home/operator",
        "operator_home_host_path": (
            str(LAB_ROOT / run["run_id"] / "installation" / "home")
            if run["surface"] == "maude-installation"
            else str(LAB_ROOT / run["run_id"] / "private-operator-home")
        ),
        "provider_auth_config_separate_from_operator_home": True,
        "public_cli_boundary": (
            {
                "client": "public_cli.py",
                "transport": "one evaluator-owned Unix socket",
                "operator_socket_path": "/run/maude-public/broker.sock",
                "raw_driver_queue_visible": False,
                "trusted_broker": "public_cli_broker.py",
                "broker_receives_provider_credentials": False,
                "broker_receives_semantic_prompt": False,
            }
            if run["surface"] == "maude"
            else None
        ),
        "provider_boundaries": {
            "operator": _session_provider_boundary(
                provider_config=run["operator_model_config"],
                role="operator",
                execution_config=operator_config,
            ),
            "grader": _session_provider_boundary(
                provider_config=run["grader_model_config"],
                role="grader",
                execution_config=grader_config,
            ),
        },
    }
    if run["surface"] == "maude-installation":
        endpoint_plan = INSTALL_ENDPOINT_DIR / f"{run['run_id']}.json"
        result["installation_endpoint_plan"] = file_record(endpoint_plan)
        socket_path = installation_socket
        result["installation_socket_path"] = (
            str(socket_path) if socket_path is not None else None
        )
        result["installation_socket_boundary"] = (
            "socket is present only in the per-command policy and persistent "
            "PTY broker namespace; it is never added to provider transport"
            if socket_path is not None
            else "no runtime socket is supplied"
        )
        result["operator_task_network"] = "denied"
    return result


def _installation_socket_path(run: dict[str, Any]) -> Path | None:
    mode, strategy, _chmod = INSTALL_ENDPOINT_SPECS[run["run_id"]]
    if mode == "none":
        return None
    task = load_json(SCENARIOS_DIR / run["scenario_id"] / "task.json")
    handoff = task.get("handoff")
    if not isinstance(handoff, dict):
        raise CampaignError(f"{run['run_id']}: task handoff is malformed")
    if strategy == "task_handoff":
        value = handoff.get("governor_socket")
        if not isinstance(value, str) or not value:
            raise CampaignError(f"{run['run_id']}: task handoff socket is absent")
        socket_path = Path(value)
        expected_parent = LAB_ROOT / run["run_id"] / "installation" / "run"
        if socket_path.parent != expected_parent:
            raise CampaignError(
                f"{run['run_id']}: task socket escapes the owned run directory"
            )
        return socket_path
    if strategy == "default_governor_dir":
        governor_dir = handoff.get("project_directory")
        if not isinstance(governor_dir, str) or not governor_dir:
            raise CampaignError(
                f"{run['run_id']}: default governor directory is absent"
            )
        runtime_dir = LAB_ROOT / run["run_id"] / "installation" / "run" / "xdg"
        governor_path = Path(governor_dir).resolve() / ".governor"
        digest = hashlib.sha256(str(governor_path).encode("utf-8")).hexdigest()[:12]
        return runtime_dir / f"governor-{digest}.sock"
    raise CampaignError(
        f"{run['run_id']}: unknown endpoint socket strategy {strategy!r}"
    )


def _direct_commands(run: dict[str, Any]) -> list[dict[str, Any]]:
    metadata_path = PACKET_DIR / "direct-runtime" / "fixtures" / f"{run['run_id']}.json"
    control = load_json(metadata_path)
    binary = "./bin/docket"
    state = control["state_path"]
    attempt = control["attempt_id"]
    common = ["--state", state, "--attempt", attempt]
    commands: list[dict[str, Any]] = [
        {
            "purpose": "surface discovery",
            "argv": [binary, "--help"],
        },
        {
            "purpose": "inspect the exact attempt dossier",
            "argv": [binary, "docket", "show", *common, "--json"],
        },
        {
            "purpose": "inspect the digest-verified journal",
            "argv": [binary, "docket", "journal", *common, "--json"],
        },
    ]
    setup_state = control["setup_state"]
    if setup_state == "prepared":
        commands.extend(
            [
                {
                    "purpose": "present frozen standing to ratification boundary",
                    "argv": [
                        binary,
                        "ratify",
                        *common,
                        "--token",
                        control["standing_token"],
                        "--actor",
                        control["assigned_actor"],
                        "--digest",
                        control["prepared_attempt_digest"],
                        "--basis",
                        control["basis_commit"],
                    ],
                },
                {
                    "purpose": "reserve the ratified attempt if ratification succeeds",
                    "argv": [binary, "reserve", *common],
                },
                {
                    "purpose": "dispatch the reserved synthetic Git effect",
                    "argv": [binary, "dispatch", *common],
                },
            ]
        )
    elif setup_state == "reserved":
        commands.append(
            {
                "purpose": "dispatch the already reserved synthetic Git effect",
                "argv": [binary, "dispatch", *common],
            }
        )
    elif setup_state == "indeterminate":
        commands.append(
            {
                "purpose": "inspect recovery facts without claiming a verdict",
                "argv": [binary, "recover", "fact", *common, "--json"],
            }
        )
    return commands


def _artifact_candidates() -> Iterable[Path]:
    explicit_docs = (
        REPO_ROOT / "docs" / "SYNTHETIC-OPERATOR-EVALUATION.md",
        EVAL_ROOT / "README.md",
        *OPERATOR_DOC_SOURCES,
        *(source for source, _relative in INSTALL_OPERATOR_DOC_SOURCES),
    )
    for path in explicit_docs:
        yield path
    for root in (HARNESS_DIR, PERSONAS_DIR, SCENARIOS_DIR, PACKET_DIR):
        for path in sorted(root.rglob("*")):
            if path.is_symlink() or not (path.is_file() or path.is_dir()):
                raise CampaignError(
                    f"frozen input tree contains a non-regular path: {path}"
                )
            if path.is_dir():
                continue
            if "__pycache__" in path.parts or path.suffix == ".pyc":
                raise CampaignError(
                    f"generated Python cache is forbidden in frozen inputs: {path}"
                )
            if path in {
                MANIFEST_PATH,
                PACKET_DIR / "manifest.md",
            }:
                continue
            yield path


def _frozen_artifacts() -> list[dict[str, Any]]:
    seen: set[Path] = set()
    records: list[dict[str, Any]] = []
    for path in _artifact_candidates():
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if not path.is_file():
            raise CampaignError(f"required frozen artifact is absent: {path}")
        records.append(file_record(path))
    return sorted(records, key=lambda item: item["path"])


def _run_supplied_material(run: dict[str, Any]) -> dict[str, Any]:
    scenario = SCENARIOS_DIR / run["scenario_id"]
    if run["surface"] == "maude":
        visible = [
            str(
                (
                    PACKET_DIR / "rendered" / run["run_id"] / "operator-task.md"
                ).relative_to(REPO_ROOT)
            )
        ] + [
            str(path.relative_to(REPO_ROOT))
            for path in _visible_scenario_paths(scenario)
        ]
        visible.extend(
            [
                "evals/synthetic-operator/harness/maude",
                "evals/synthetic-operator/harness/public_cli.py",
                "evals/synthetic-operator/harness/operator_retrospective.py",
                f"evals/synthetic-operator/runs/{CAMPAIGN_ID}/packet/operator-docs/commands.md",
                f"evals/synthetic-operator/runs/{CAMPAIGN_ID}/packet/operator-docs/configuration.md",
            ]
        )
        withheld = [
            str((scenario / "runtime.json").relative_to(REPO_ROOT)),
            str((scenario / "patch.diff").relative_to(REPO_ROOT)),
            str((scenario / "expected-disposition.json").relative_to(REPO_ROOT)),
            "Maude and runtime implementation source",
            "runtime RPC transcript and private state during the run",
        ]
    elif run["surface"] == "docket-gwr-direct":
        run_id = run["run_id"]
        visible = [
            str(
                (PACKET_DIR / "rendered" / run_id / "operator-task.md").relative_to(
                    REPO_ROOT
                )
            ),
            str((scenario / "packet.json").relative_to(REPO_ROOT)),
            "evals/synthetic-operator/harness/operator_retrospective.py",
            *[
                f"evals/synthetic-operator/runs/{CAMPAIGN_ID}/packet/direct-runtime/bin/docket",
                f"evals/synthetic-operator/runs/{CAMPAIGN_ID}/packet/direct-runtime/bin/gwr-git-broker",
                str(
                    (
                        PACKET_DIR / "rendered" / run_id / "direct-control.json"
                    ).relative_to(REPO_ROOT)
                ),
                str((scenario / "patch.diff").relative_to(REPO_ROOT)),
            ],
            *[
                str(path.relative_to(REPO_ROOT))
                for path in sorted(
                    (PACKET_DIR / "direct-runtime" / "docs").glob("*.md")
                )
            ],
        ]
        withheld = [
            str((scenario / "expected-disposition.json").relative_to(REPO_ROOT)),
            "Docket/GWR implementation source",
            "fixture setup transcript",
            "historical internal pilot material linked from the dossier",
            "other comparison runs",
        ]
    else:
        run_id = run["run_id"]
        visible = [
            str(
                (PACKET_DIR / "rendered" / run_id / "operator-task.md").relative_to(
                    REPO_ROOT
                )
            ),
            str((scenario / "task.json").relative_to(REPO_ROOT)),
            "evals/synthetic-operator/harness/operator_retrospective.py",
            "evals/synthetic-operator/harness/operator_pty.py",
            *[
                str(path.relative_to(REPO_ROOT))
                for path, _destination in _install_fixture_pairs(scenario)
            ],
            *[
                str((INSTALL_DOC_PACKET_DIR / relative).relative_to(REPO_ROOT))
                for _source, relative in INSTALL_OPERATOR_DOC_SOURCES
            ],
        ]
        if run["source_visibility"] == "release-source":
            visible.append(str(INSTALL_SOURCE_ARCHIVE.relative_to(REPO_ROOT)))
        withheld = [
            str((scenario / "README.md").relative_to(REPO_ROOT)),
            str((scenario / "environment.json").relative_to(REPO_ROOT)),
            str((scenario / "expected-disposition.json").relative_to(REPO_ROOT)),
            *run["deliberately_withheld"],
            "installation wheelhouse, build transcript, and materializer logs",
            "other installation runs and setup evidence",
        ]
    withheld.extend(
        [
            "grading rubric and failure taxonomy",
            "expected answers or expected refusal points",
            "prior run transcripts and grades",
            "evaluator commentary and campaign findings",
        ]
    )
    result = {
        "visible_source_artifacts": sorted(visible),
        "deliberately_withheld": withheld,
    }
    if run["surface"] == "maude":
        result["terminal_bridge_disclosure"] = {
            "artifact": "evals/synthetic-operator/harness/public_cli.py",
            "implementation_visible": True,
            "purpose": (
                "evaluation-only terminal transport; no Maude or runtime "
                "implementation source and no product command semantics"
            ),
        }
    elif run["surface"] == "maude-installation":
        result["installation_materialization"] = {
            "literal_public_commands_only": True,
            "package_command_wrapper": False,
            "mirror_rewrite": False,
            "hidden_pip_configuration": False,
            "simulated_installation": False,
            "source_visibility": run["source_visibility"],
            "generic_pty_adapter": {
                "artifact": ("evals/synthetic-operator/harness/operator_pty.py"),
                "destination": "operator-pty",
                "purpose": (
                    "neutral persistent PTY transport for an arbitrary "
                    "executable; start/read/send/status/stop permit adaptive "
                    "interaction across provider tool calls, preserve the "
                    "exact PTY transcript, and add no Maude command semantics"
                ),
            },
            "media_provenance": str(INSTALL_MEDIA_PROVENANCE.relative_to(REPO_ROOT)),
        }
    result["post_task_retrospective"] = {
        "artifact": ("evals/synthetic-operator/harness/operator_retrospective.py"),
        "destination": "operator-retrospective",
        "questions_hidden_until_initial_disposition": True,
        "invocation_excluded_from_product_command_counts": True,
    }
    return result


def _model_execution_configs(matrix: dict[str, Any]) -> dict[str, Any]:
    declared = matrix["operator_model_configs"]
    used_set = {
        str(run[field])
        for run in matrix_runs(matrix)
        for field in ("operator_model_config", "grader_model_config")
    }
    used = [provider for provider in SUPPORTED_PROVIDER_CONFIGS if provider in used_set]
    if (
        not isinstance(declared, dict)
        or list(declared) != used
        or any(
            declared[provider] != PROVIDER_MODEL_CONFIGS[provider] for provider in used
        )
    ):
        raise CampaignError(
            "matrix provider configurations differ from the exact frozen "
            "provider configurations actually used by campaign runs"
        )
    result: dict[str, Any] = {}
    for provider in used:
        config = json.loads(json.dumps(declared[provider]))
        common = {
            **config,
            "provider_network_scope": (
                "permitted only for the provider transport used by capability "
                "probes and fresh operator/grader sessions"
            ),
            "locally_configured_provider_credentials_scope": (
                "permitted only for provider-session transport"
            ),
            "task_level_network": False,
            "production_task_systems_or_credentials": False,
            "external_operational_effect": False,
            "operator_boundary": (
                "one bounded terminal MCP tool backed by a credential-free, "
                "prompt-free command broker and source-free no-network "
                "command namespace"
            ),
            "grader_boundary": (
                "one read-only evidence MCP tool over the frozen grade bundle; "
                "no operator command broker"
            ),
        }
        if provider == "openai-sol":
            common.update(
                {
                    "resolved_executable": "/opt/node/bin/codex",
                    "operator_invocation_contract": (
                        "fresh ephemeral strict-config Codex exec; exact "
                        "role-specific MCP configuration; all intrinsic and "
                        "optional action features disabled; combined prompt "
                        "delivered through closed stdin"
                    ),
                    "grader_invocation_contract": (
                        "fresh ephemeral strict-config Codex exec with one "
                        "read-only evidence MCP tool and exact output schema"
                    ),
                    "trusted_transport_component_limitation": (
                        "the hash-pinned direct stdio MCP shim shares the "
                        "retained-auth provider transport and is proved not "
                        "to read provider authentication"
                    ),
                }
            )
        else:
            common.update(
                {
                    "resolved_executable": (
                        "/home/jbeck/.local/share/claude/versions/2.1.220"
                    ),
                    "operator_invocation_contract": (
                        "fresh no-persistence Claude session with strict MCP "
                        "configuration, exact terminal-tool allowlist, disabled "
                        "slash/browser surfaces, and a new session UUID"
                    ),
                    "grader_invocation_contract": (
                        "fresh no-persistence Claude session with strict MCP "
                        "configuration, one read-only evidence tool, and the "
                        "exact JSON schema"
                    ),
                    "trusted_transport_component_limitation": (
                        "provider authentication remains only in the "
                        "task-blind transport; the separately sandboxed MCP "
                        "proxy and command broker receive no credentials"
                    ),
                }
            )
        result[provider] = common
    return result


def _build_manifest(matrix: dict[str, Any], *, frozen_at: str) -> dict[str, Any]:
    run_records: list[dict[str, Any]] = []
    for run in matrix_runs(matrix):
        scenario = SCENARIOS_DIR / run["scenario_id"]
        fixture_records = [
            file_record(path)
            for path in _regular_files(
                scenario / "fixture",
                label=f"{run['run_id']} manifest fixture",
            )
        ]
        operator_working_directory = (
            LAB_ROOT / run["run_id"] / "installation" / "operator"
            if run["surface"] == "maude-installation"
            else LAB_ROOT / run["run_id"] / "operator"
        )
        record = {
            **run,
            "lab_root": str(LAB_ROOT / run["run_id"]),
            "operator_working_directory": str(operator_working_directory),
            "rendered_operator_prompt": str(
                (
                    PACKET_DIR / "rendered" / run["run_id"] / "operator-prompt.md"
                ).relative_to(REPO_ROOT)
            ),
            "rendered_grader_assignment": str(
                (
                    PACKET_DIR / "rendered" / run["run_id"] / "grader-assignment.md"
                ).relative_to(REPO_ROOT)
            ),
            "rendered_supplied_inputs": str(
                (
                    PACKET_DIR / "rendered" / run["run_id"] / "supplied-inputs.json"
                ).relative_to(REPO_ROOT)
            ),
            "rendered_session_config": str(
                (
                    PACKET_DIR / "rendered" / run["run_id"] / "session-config.json"
                ).relative_to(REPO_ROOT)
            ),
            "fixture_identity": {
                "scenario_id": run["scenario_id"],
                "fixture_files": fixture_records,
                "expected_disposition_sha256": sha256_file(
                    scenario / "expected-disposition.json"
                ),
            },
            "materials": _run_supplied_material(run),
        }
        if run["surface"] == "docket-gwr-direct":
            direct_metadata = load_json(
                PACKET_DIR / "direct-runtime" / "fixtures" / f"{run['run_id']}.json"
            )
            record["direct_runtime_fixture"] = {
                "archive": direct_metadata["archive"],
                "archive_bytes": direct_metadata["archive_bytes"],
                "archive_sha256": direct_metadata["archive_sha256"],
                "docket_commit": direct_metadata["docket_commit"],
                "dossier_format": direct_metadata["dossier_format"],
                "setup_state": direct_metadata["setup_state"],
                "standing_ttl_ms": direct_metadata["standing_ttl_ms"],
                "setup_reservation_ttl_ms": direct_metadata["setup_reservation_ttl_ms"],
                "comparison_scope": run["comparison_scope"],
            }
            record["direct_runtime_comparator_commands"] = _direct_commands(run)
        elif run["surface"] == "maude-installation":
            record["installation_fixture"] = {
                "track_id": run["track_id"],
                "task_id": run["task_id"],
                "source_visibility": run["source_visibility"],
                "neutral_fixture_destinations": [
                    {
                        "source": str(path.relative_to(REPO_ROOT)),
                        "destination": destination,
                        "bytes": path.stat().st_size,
                        "sha256": sha256_file(path),
                    }
                    for path, destination in _install_fixture_pairs(scenario)
                ],
                "operator_documents": [
                    {
                        **file_record(INSTALL_DOC_PACKET_DIR / relative),
                        "destination": relative.as_posix(),
                    }
                    for _source, relative in INSTALL_OPERATOR_DOC_SOURCES
                ],
                "source_archive": (
                    {
                        **file_record(INSTALL_SOURCE_ARCHIVE),
                        "destination": "media/maude-source.tar",
                    }
                    if run["source_visibility"] == "release-source"
                    else None
                ),
                "installed_state_materialization": (
                    "fresh literal offline venv installation from the frozen "
                    "hash-locked wheel closure"
                    if run["source_visibility"] == "installed-distribution"
                    else "none"
                ),
                "media_provenance": file_record(INSTALL_MEDIA_PROVENANCE),
                "endpoint_plan": file_record(
                    INSTALL_ENDPOINT_DIR / f"{run['run_id']}.json"
                ),
                "wheelhouse_operator_visible": False,
                "setup_transcript_operator_visible": False,
            }
        run_records.append(record)

    assignments = _provider_role_assignments(matrix)
    run_pairs = [
        (run["operator_model_config"], run["grader_model_config"])
        for run in matrix_runs(matrix)
    ]
    same_config_used = any(operator == grader for operator, grader in run_pairs)
    same_family_used = any(
        PROVIDER_MODEL_CONFIGS[operator]["expected_family"]
        == PROVIDER_MODEL_CONFIGS[grader]["expected_family"]
        for operator, grader in run_pairs
    )
    cross_family_runs = sorted(
        run["run_id"]
        for run in matrix_runs(matrix)
        if PROVIDER_MODEL_CONFIGS[run["operator_model_config"]]["expected_family"]
        != PROVIDER_MODEL_CONFIGS[run["grader_model_config"]]["expected_family"]
    )
    used_provider_set = set(assignments["all_operator_provider_configs"]) | set(
        assignments["all_grader_provider_configs"]
    )
    providers_used = [
        provider
        for provider in SUPPORTED_PROVIDER_CONFIGS
        if provider in used_provider_set
    ]
    family_policy = matrix["model_family_policy"]
    if (
        family_policy.get("same_model_configuration_grading") is not same_config_used
        or family_policy.get("same_family_grading") is not same_family_used
        or family_policy.get("cross_family_grading_used") is not bool(cross_family_runs)
    ):
        raise CampaignError(
            "manifest model-family incidence differs from the finalized matrix"
        )
    return {
        "schema": MANIFEST_SCHEMA,
        "campaign_id": CAMPAIGN_ID,
        "frozen_at": frozen_at,
        "authority_effect": "none",
        "observation_custody": (
            "initial clean-state facts are exact observations recorded at the "
            "separate preparation-base commit before successor input or "
            "evaluator changes; provider/isolation probes are exact later "
            "pre-freeze observations and live Git identity fields are "
            "rechecked by this freezer"
        ),
        "repository": {
            "identity": "github-unpingable:unpingable/maude.git",
            "system_under_test_commit": SUT_COMMIT,
            "scaffold_baseline_commit": SUT_COMMIT,
            "preparation_base_commit": PREPARATION_BASE_COMMIT,
            "successor_lineage": file_record(SUCCESSOR_LINEAGE),
            "existing_working_line": "main",
            "packet_commit": "to be recorded by commit; not a SUT behavior change",
        },
        "preparation_history": {
            "successor_lineage": file_record(SUCCESSOR_LINEAGE),
            "prior_generations_count_as_campaign_evidence": False,
            "prior_generations_count_toward_campaign_completion": False,
            "current_generation_full_matrix_rerun_required": True,
        },
        "provider_capability_policy": (_provider_capability_policy_record()),
        "system_under_test": {
            "name": "Maude",
            "surface": (
                "exact baseline command parser, handlers, renderers, and "
                "GovernorClient exercised through a persistent headless "
                "Textual app, plus exact baseline installation documentation, "
                "package metadata, filtered installable archive, and ordinary "
                "installed console entry point for the installation track"
            ),
            "commit": SUT_COMMIT,
            "runtime": (
                "deterministic synthetic Content-Length JSON-RPC service; no "
                "production system or external effect"
            ),
            "evaluation_transport": (
                "operator-visible public_cli.py talks only to one synthetic "
                "Unix socket; evaluator-private public_cli_broker.py validates "
                "and correlates requests while alone retaining access to the "
                "raw driver queue"
            ),
            "evaluation_transport_artifacts": {
                "client": file_record(HARNESS_DIR / "public_cli.py"),
                "trusted_broker": file_record(PUBLIC_CLI_BROKER),
                "operator_socket_path": "/run/maude-public/broker.sock",
                "raw_driver_queue_exposed_to_operator": False,
                "broker_receives_provider_credentials": False,
                "broker_receives_semantic_prompt": False,
                "public_timeout_settlement": (
                    "retained unknown; the queued request is not claimed "
                    "cancelled or unexecuted"
                ),
            },
            "direct_comparator": {
                "name": "Docket/GWR direct CLI",
                "docket_commit": DOCKET_COMMIT,
                "frozen_binaries": True,
            },
        },
        "coverage_interpretation": matrix["interpretation"],
        "round": matrix["round"],
        "run_matrix": str(MATRIX_PATH.relative_to(REPO_ROOT)),
        "installation_track": str(INSTALL_TRACK_PATH.relative_to(REPO_ROOT)),
        "runs": run_records,
        "model_session_configs": _model_execution_configs(matrix),
        "model_family_policy": matrix["model_family_policy"],
        "provider_role_assignments": assignments,
        "audited_campaign_boundary_artifacts": [
            file_record(path)
            for path in (
                HARNESS_DIR / "campaign_runner.py",
                HARNESS_DIR / "claude_mcp_bridge.py",
                HARNESS_DIR / "operator_pty.py",
                HARNESS_DIR / "public_cli.py",
                HARNESS_DIR / "public_cli_broker.py",
                HARNESS_DIR / "grader_surface_probe.py",
                HARNESS_DIR / "auth_gate_selftest.py",
                HARNESS_DIR / "campaign_common.py",
                FINALIZE_PROVIDER_ASSIGNMENTS,
                PROVIDER_ASSIGNMENT_SELFTEST,
            )
        ],
        "fresh_session_contract": {
            "one_new_provider_process_per_run": True,
            "no_resume_or_continue": True,
            "no_follow_up_messages": True,
            "same_family_grading_used": same_family_used,
            "same_model_configuration_grading_used": same_config_used,
            "cross_family_run_ids": cross_family_runs,
            "independent_fresh_grader_session_required": True,
            "cross_family_coverage_available": bool(cross_family_runs),
            "raw_provider_jsonl_and_stderr_preserved": True,
            "provider_configs_used": providers_used,
            "provider_specific_boundaries": {
                provider: {
                    "operator_tools": PROVIDER_MODEL_CONFIGS[provider][
                        "operator_tools"
                    ],
                    "grader_tools": PROVIDER_MODEL_CONFIGS[provider]["grader_tools"],
                    "built_in_tools": PROVIDER_MODEL_CONFIGS[provider][
                        "built_in_tools"
                    ],
                    "mcp_protocol_version": PROVIDER_MODEL_CONFIGS[provider][
                        "mcp_protocol_version"
                    ],
                }
                for provider in providers_used
            },
        },
        "filesystem_isolation": {
            "mechanism": "bubblewrap",
            "required": True,
            "namespaces": (
                "Each provider uses its audited task-blind transport and exact "
                "role-specific MCP boundary. Every brokered operator command "
                "uses a further fresh source-free, credential-free "
                "mount/PID/no-network namespace. Provider network is permitted "
                "only to the provider session transport."
            ),
            "mount_policy": [
                "read-only /usr, /bin, /lib, /lib64, /etc",
                "read-only /run/systemd/resolve only; no other host /run sockets",
                "private /tmp containing only the selected run bindings",
                "private provider auth is retained only by the task-blind "
                "provider transport until exit and then destroyed",
                "provider-specific MCP boundaries expose exactly one "
                "role-specific tool and no built-in action surface",
                "Codex uses a hash-pinned direct stdio shim whose non-use of "
                "provider auth is verified; Claude uses a separately sandboxed "
                "credential-free and no-network MCP proxy",
                "operator commands receive a fresh no-network mount/PID namespace "
                "through a credential-free, prompt-free broker",
                "distinct per-run writable operator HOME, XDG, cache, state, and tmp",
                "read-only provider executable and dependencies",
                "read-only task, docs, and repository for Maude operators",
                "Maude operators receive only a synthetic public Unix socket; "
                "a prompt/auth-free trusted broker alone sees the private driver queue",
                "read-write Docket state and repository for direct-runtime operators",
                "installation runs expose only declared docs, neutral task files, "
                "real installed distribution or filtered archive, and owned lab paths",
                "read-only grade bundle for independent evaluators",
                "no bind for /home/jbeck/git/agent_gov_ui or Maude source",
            ],
            "network_policy": (
                "Provider network is authorized only for the pre-freeze "
                "capability probes and later fresh model sessions. No operator "
                "task, command broker, persistent PTY, synthetic runtime, or "
                "grader evidence tool receives task-level external network; "
                "production systems and external operational effects remain "
                "prohibited."
            ),
            "preflight": (
                "campaign_runner must prove each assigned provider's exact "
                "role-specific MCP roster and readiness, authentication "
                "custody, source/task-path absence, provider/proxy/broker "
                "correlations, per-command namespaces and descriptors, "
                "broker/PTY correlations, and graceful or forced cleanup"
            ),
            "unix_socket_addressing": {
                "encoded_path_budget_bytes": 100,
                "owner_private_short_host_arenas": True,
                "checked_before_bind_or_connect": True,
                "private_arena_cleanup_required": True,
                "canonical_long_lab_and_evidence_paths_preserved": True,
                "evidence_paths_used_as_socket_addresses": False,
            },
        },
        "grading": {
            "rubric_id": "maude-synthetic-operator-rubric-v1",
            "failure_taxonomy_id": "maude-synthetic-failure-taxonomy-v1",
            "rubric": str((PACKET_DIR / "grading-rubric.md").relative_to(REPO_ROOT)),
            "taxonomy": str(
                (PACKET_DIR / "failure-taxonomy.json").relative_to(REPO_ROOT)
            ),
            "schema": str(
                (PACKET_DIR / "grader-output.schema.json").relative_to(REPO_ROOT)
            ),
            "installation_rubric_id": ("maude-synthetic-installation-rubric-v1"),
            "installation_rubric": str(
                (PACKET_DIR / "installation-grading-rubric.md").relative_to(REPO_ROOT)
            ),
            "installation_schema": str(
                (PACKET_DIR / "installation-grader-output.schema.json").relative_to(
                    REPO_ROOT
                )
            ),
            "grader_request_template": str(
                (PACKET_DIR / "prompts" / "grader-request-template.md").relative_to(
                    REPO_ROOT
                )
            ),
            "expected_dispositions_deliberately_withheld": True,
        },
        "committed_evidence_boundary_verification": {
            "required_after_raw_evidence_commit": True,
            "rederive_actions_from_raw_provider_stream": True,
            "reject_unrepresented_or_duplicate_provider_actions": True,
            "reject_truncated_command_output": True,
            "verify_provider_specific_auth_boundary": True,
            "verify_codex_tool_proxy_broker_correlations": True,
            "verify_codex_normalized_result_correlations": True,
            "verify_codex_per_command_namespace_and_descriptor_proofs": True,
            "verify_claude_tool_proxy_broker_correlations": True,
            "verify_claude_per_command_namespace_and_descriptor_proofs": True,
            "verify_public_cli_request_queue_response_correlations": True,
            "preserve_public_timeout_as_retained_unknown": True,
            "verify_boundary_cleanup_and_no_orphans": True,
            "provider_exact_one_role_specific_tool_roster_proved": True,
            "provider_per_command_namespace_claim": True,
        },
        "measurement_definitions": {
            "elapsed_interaction_steps": (
                "Count one step for each completed provider tool action in the "
                "operator attempt, including document/help reads and failed "
                "actions. Exclude only actions whose whole effect is writing "
                "/home/operator/initial-disposition.md and/or invoking the "
                "operator-retrospective helper. A PTY adapter wrapper and its "
                "wrapped operator-selected product command are not double "
                "counted on start; every later PTY read/send/status/stop tool "
                "action remains a separate interaction step. "
                "Do not use model wall-clock latency as a UX measure."
            ),
            "command_attempts": (
                "Grader-classified operator command or interface attempts under "
                "the frozen rubric; evaluator-protocol disposition and "
                "retrospective actions are excluded."
            ),
        },
        "known_campaign_limitations": [
            "Generation 1 (`maude-baseline-20260726T233054-0400`) is preserved as aborted evaluator-infrastructure history. Its 25 operator sessions, 24 failed grader-provider sessions, and 10 pre-provider installation failures do not count as successor evidence or completion; this generation reruns the full 35-run matrix.",
            "Generation 2 (`maude-baseline-20260728T032857-0400`) is preserved as aborted evaluator-infrastructure history. Its 15 completed operator sessions, 2 interrupted provider sessions, 18 unstarted runs, and 0 grades do not count as successor evidence or completion because the frozen verifier accepted missing or semantically invalid command-broker evidence and the retrospective wrapper misclassified all 15 completed runs; this generation reruns the full 35-run matrix.",
            "Generation 3 (`maude-baseline-20260728T050937-0400`) is preserved as aborted evaluator-infrastructure history. Its 30 completed operator sessions, five pre-session installation failures, and 0 grades do not count as successor evidence or completion because the evaluator declared nonexistent installation venv and unavailable-endpoint socket mounts, and its lab root exceeded the conservative Unix-socket budget; this generation reruns the full 35-run matrix.",
            "This campaign is Round A baseline only. Product and documentation repair is prohibited, so no Round B post-repair comparison or changed-command/display example can be produced in this campaign; those absences must remain explicit in findings.",
            "The Agent Governor service is deterministic synthetic protocol state, not a live daemon.",
            "The Maude terminal is driven headlessly at 120x40; terminal adapter actions are recorded.",
            "The evaluation-only public_cli.py Unix-socket client is operator-visible because it transports terminal actions; it contains no Maude/runtime implementation or task-specific workflow help. The evaluator-private public_cli_broker.py alone sees the raw driver queue and receives neither provider credentials nor semantic prompts.",
            "Every run receives an evaluator-only retrospective helper. Its fixed questions are revealed only after the operator writes a nonempty initial disposition; the disposition write and one helper invocation are evaluator protocol, excluded from product command counts. The readable helper cannot mechanically prevent a disobedient operator from inspecting it early, so early inspection is evaluator contamination.",
            "Installation runs receive an evaluation-only generic persistent PTY adapter because provider tools do not supply an interactive PTY. Its start/read/send/status/stop surface lets the operator adapt across provider tool calls while one arbitrary operator-selected command remains alive, records the exact PTY transcript, and contains no Maude commands or workflow hints. The adapter wrapper is not counted as an extra product command; its wrapped product command counts once.",
            "The direct comparator is a frozen Docket/GWR historical build, not a claim of correctness.",
            "The installation track has no direct-runtime control because installing Docket/GWR is not task-equivalent to installing the Maude component.",
            "Frozen third-party wheel bodies are self-describing and hash-pinned local cache bytes, not an authenticated upstream index, signature, or TUF proof.",
            "First-party wheel byte reproducibility is proven for two builds under the same inputs; temporary path strings in build and verifier transcripts are not claimed reproducible.",
            "Offline pip preparation uses --no-index with no intentional network operation, but packet preparation did not run in an OS-level network namespace.",
            "Installed-state operator runs receive real per-run venv bytes generated from the frozen closure; wheelhouse and setup transcripts remain evaluator-only.",
            "A Python installed distribution necessarily exposes readable module files inside its venv. Operators are prohibited from inspecting those internals; every installed-state run receives the same preserve-raw, mechanically linked redacted-grade, and evaluator-contamination boundary if source inspection or source bytes occur.",
            "The hard no-network boundary and current documented clone/editable-install path provide no documented offline route from nothing installed to a successful Maude public result. install-i01 tests that path without injecting an undocumented mirror or cache; a safe stop and null time-to-first-success remain possible evidence rather than a manufactured pass.",
            "The required developer-installing-from-source specimen conflicts with the general source-withholding rule. install-i03 therefore receives an exact filtered release-source archive as an explicit exception; implementation inspection is prohibited but cannot be mechanically hidden from that operator, and any such inspection is evaluator contamination.",
            "Graders normally receive the exact raw transcript. If install-i03 prints mounted implementation-source bytes, the untouched raw transcript remains campaign evidence but the grader receives a mechanically redacted, byte-linked copy under the scaffold redaction rule; that grade must report missing evidence and evaluator contamination because exact-raw exposure and no-source exposure cannot both be satisfied.",
            "Docket/GWR does not expose Maude's post-worker keep/discard promotion surface; that absence is a comparator capability difference.",
            "Frozen Docket standing and pre-reservation are time-bounded to 30 days from fixture generation; later reproduction requires a new packet rather than reuse of expired authority bytes.",
            "Provider API calls are necessary to create model sessions; operator tasks have no live endpoints.",
            "Codex exec exposes a single initial prompt, so the preserved system text is concatenated before the user assignment.",
            (
                "The provider capability and assignment decision was frozen "
                "before campaign sessions. Candidate capability failures are "
                "preserved and exclude only unsupported provider roles; the "
                "final matrix uses operator providers "
                f"{assignments['all_operator_provider_configs']!r} and grader "
                f"providers {assignments['all_grader_provider_configs']!r}."
            ),
            (
                "Every independent grade uses a separate genuinely fresh "
                "provider session. Actual same-family, same-configuration, "
                "cross-family support, and cross-family use are exactly those "
                "recorded in the frozen model_family_policy; findings must not "
                "generalize beyond that incidence."
            ),
            (
                "Locally configured provider credentials and provider network "
                "are permitted only inside task-blind provider-session "
                "transports. No operator command, grader evidence tool, "
                "synthetic task, or runtime receives task-level network, "
                "production credentials, or external operational authority."
            ),
            (
                "Codex uses a hash-pinned direct stdio shim inside its retained-"
                "auth transport; Claude uses a separately sandboxed credential-"
                "free MCP proxy. Both expose exactly one role-specific tool, "
                "run operator commands in source/auth-free no-network mount/PID "
                "namespaces, and expose graders only to read-only evidence. "
                "Installation capability probes add a separately sandboxed "
                "persistent PTY broker."
            ),
            "Evaluation-only Unix sockets use owner-private short host arenas and reject encoded paths over 100 bytes before bind or connect. This transport indirection does not relocate or shorten canonical lab, transcript, or evidence paths, and every arena must be removed after use.",
            "The campaign records provider-specific MCP readiness, exact tool rosters, transport/proxy/broker correlations, normalized result equality, per-command namespace and descriptor proofs, and cleanup. Provider-session transport is deliberately network-capable; task operations are not.",
            "Provider-reported model version and session identity are observable only after a session starts.",
            "Synthetic model latency is excluded from UX grading.",
        ],
        "frozen_artifacts": _frozen_artifacts(),
    }


def _command_output(argv: list[str], *, cwd: Path | None = None) -> dict[str, Any]:
    completed = subprocess.run(
        argv,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    return {
        "argv": argv,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _initial_repository_observation() -> dict[str, Any]:
    if not INITIAL_REPOSITORY_OBSERVATION.is_file():
        raise CampaignError("initial repository observation is absent")
    observation = load_json(INITIAL_REPOSITORY_OBSERVATION)
    if (
        observation.get("schema")
        != "maude.synthetic-operator.initial-repository-observation.v1"
        or observation.get("campaign_id") != CAMPAIGN_ID
        or observation.get("authority_effect") != "none"
        or observation.get("repository_path") != str(REPO_ROOT)
    ):
        raise CampaignError("initial repository observation identity is wrong")
    expected = {
        "repository_root": (
            ["git", "rev-parse", "--show-toplevel"],
            f"{REPO_ROOT}\n",
        ),
        "status_short": (
            ["git", "status", "--short"],
            "",
        ),
        "branch": (
            ["git", "branch", "--show-current"],
            "main\n",
        ),
        "head": (
            ["git", "rev-parse", "HEAD"],
            f"{PREPARATION_BASE_COMMIT}\n",
        ),
        "upstream": (
            ["git", "rev-parse", "--abbrev-ref", "@{upstream}"],
            "origin/main\n",
        ),
        "upstream_head": (
            ["git", "rev-parse", "@{upstream}"],
            "e5fd7f1c41b7b8dd66dc5db9ee4584bee8ebe71c\n",
        ),
        "origin": (
            ["git", "remote", "get-url", "origin"],
            "github-unpingable:unpingable/maude.git\n",
        ),
    }
    observations = observation.get("observations")
    if not isinstance(observations, dict):
        raise CampaignError("initial repository command observations are absent")
    for name, (argv, stdout) in expected.items():
        record = observations.get(name)
        if (
            not isinstance(record, dict)
            or record.get("argv") != argv
            or record.get("returncode") != 0
            or record.get("stdout") != stdout
            or record.get("stderr") != ""
        ):
            raise CampaignError(f"initial repository observation differs for {name}")
    custody = observation.get("custody")
    if (
        not isinstance(custody, dict)
        or custody.get("artifact_serialized_immediately_after_initial_inspection")
        is not True
        or not isinstance(custody.get("wall_clock_captured"), str)
        or not custody["wall_clock_captured"]
    ):
        raise CampaignError("initial repository observation custody is incomplete")
    return observation


def _provider_capability_policy() -> dict[str, Any]:
    """Load the exact predeclared provider capability and assignment rule."""

    if (
        not PROVIDER_CAPABILITY_POLICY_PATH.is_file()
        or PROVIDER_CAPABILITY_POLICY_PATH.is_symlink()
    ):
        raise CampaignError("provider capability policy is absent or unsafe")
    expected = {
        "schema": ("maude.synthetic-operator.provider-capability-policy.v1"),
        "campaign_id": CAMPAIGN_ID,
        "candidate_provider_configs": list(SUPPORTED_PROVIDER_CONFIGS),
        "decision_rule_frozen_before_provider_probes": True,
        "capability_rules": {
            "basic_operator_eligibility": (
                "The provider's fresh auth/isolation probe must pass with a "
                "fresh session identity and the exact bounded terminal-tool "
                "contract."
            ),
            "installation_operator_eligibility": (
                "The provider must satisfy basic operator eligibility and "
                "its fresh installation-surface probe must pass."
            ),
            "ordinary_grader_eligibility": (
                "The provider must satisfy its fresh auth/isolation probe "
                "and a fresh ordinary-grader schema/surface probe."
            ),
            "installation_grader_eligibility": (
                "The provider must satisfy its fresh auth/isolation probe "
                "and a fresh installation-grader schema/surface probe."
            ),
            "binary_or_credential_presence_is_not_capability": True,
            "a_provider_failure_does_not_imply_another_provider_passed": True,
            "a_probe_integrity_failure_invalidates_preparation": True,
            "a_capability_failure_excludes_only_the_unsupported_provider_role": (True),
            "at_least_one_operator_and_grader_path_must_remain": True,
        },
        "assignment_rules": {
            "when_both_families_are_fully_eligible": {
                "use_both_families_for_representative_ordinary_and_installation_runs": (
                    True
                ),
                "prefer_opposite_family_independent_grading": True,
                "balance_assignments_deterministically": True,
            },
            "when_capability_is_partial": {
                "assign_only_roles_proved_by_the_corresponding_probe": True,
                "record_same_family_grading_where_unavoidable": True,
                "make_no_unsupported_cross_family_claim": True,
            },
            "direct_runtime_comparators_mirror_paired_maude_operator_and_grader_configs": (
                True
            ),
        },
        "freshness_and_retry": {
            "every_probe_uses_a_fresh_provider_process": True,
            "a_session_counts_as_fresh_only_with_a_provider_session_identity": (True),
            "no_resume_continuation_or_follow_up": True,
            "maximum_attempts_per_provider_and_probe_kind_in_this_campaign_id": (1),
            "failed_and_partial_attempts_must_be_preserved": True,
            "retry_after_any_attempt_requires_a_new_campaign_generation": True,
        },
        "network_and_effect_boundary": {
            "provider_network_permitted_for_capability_probes_and_later_fresh_campaign_sessions": (
                True
            ),
            "locally_configured_provider_credentials_permitted_only_for_provider_session_transport": (
                True
            ),
            "task_level_network_permitted": False,
            "production_task_systems_or_credentials_permitted": False,
            "external_operational_side_effects_permitted": False,
            "synthetic_local_fixture_effects_only": True,
        },
        "campaign_evidence_boundary": {
            "capability_probe_sessions_count_as_campaign_runs": False,
            "capability_probe_sessions_count_toward_role_or_scenario_coverage": (False),
            "capability_probe_sessions_count_as_independent_grades": False,
        },
        "authority_effect": "none",
    }
    policy = load_json(PROVIDER_CAPABILITY_POLICY_PATH)
    if policy != expected:
        raise CampaignError(
            "provider capability policy differs from the exact predeclared rule"
        )
    return policy


def _provider_capability_policy_record(
    *,
    relative_to: Path = REPO_ROOT,
) -> dict[str, Any]:
    _provider_capability_policy()
    return file_record(
        PROVIDER_CAPABILITY_POLICY_PATH,
        relative_to=relative_to,
    )


def _provider_role_assignments(
    matrix: dict[str, Any],
) -> dict[str, Any]:
    runs = matrix_runs(matrix)
    ordinary = [run for run in runs if run["surface"] != "maude-installation"]
    installation = [run for run in runs if run["surface"] == "maude-installation"]

    def providers(selected: list[dict[str, Any]], field: str) -> list[str]:
        used = {str(run[field]) for run in selected}
        return [provider for provider in SUPPORTED_PROVIDER_CONFIGS if provider in used]

    per_provider: dict[str, dict[str, Any]] = {}
    for provider in SUPPORTED_PROVIDER_CONFIGS:
        per_provider[provider] = {
            "ordinary_operator_run_ids": sorted(
                run["run_id"]
                for run in ordinary
                if run["operator_model_config"] == provider
            ),
            "installation_operator_run_ids": sorted(
                run["run_id"]
                for run in installation
                if run["operator_model_config"] == provider
            ),
            "ordinary_grader_run_ids": sorted(
                run["run_id"]
                for run in ordinary
                if run["grader_model_config"] == provider
            ),
            "installation_grader_run_ids": sorted(
                run["run_id"]
                for run in installation
                if run["grader_model_config"] == provider
            ),
        }
    return {
        "ordinary_operator_provider_configs": providers(
            ordinary, "operator_model_config"
        ),
        "installation_operator_provider_configs": providers(
            installation, "operator_model_config"
        ),
        "ordinary_grader_provider_configs": providers(ordinary, "grader_model_config"),
        "installation_grader_provider_configs": providers(
            installation, "grader_model_config"
        ),
        "all_operator_provider_configs": providers(runs, "operator_model_config"),
        "all_grader_provider_configs": providers(runs, "grader_model_config"),
        "per_provider": per_provider,
    }


def _validate_capability_assignment(
    *,
    matrix: dict[str, Any],
    auth_successes: set[str],
    installation_successes: set[str],
    ordinary_grader_successes: set[str],
    installation_grader_successes: set[str],
) -> dict[str, Any]:
    assignments = _provider_role_assignments(matrix)
    required = {
        "auth": set(assignments["all_operator_provider_configs"])
        | set(assignments["all_grader_provider_configs"]),
        "installation_operator": set(
            assignments["installation_operator_provider_configs"]
        ),
        "ordinary_grader": set(assignments["ordinary_grader_provider_configs"]),
        "installation_grader": set(assignments["installation_grader_provider_configs"]),
    }
    observed = {
        "auth": auth_successes,
        "installation_operator": installation_successes,
        "ordinary_grader": ordinary_grader_successes,
        "installation_grader": installation_grader_successes,
    }
    expected_eligibility = {
        provider: {
            "ordinary_operator": provider in auth_successes,
            "installation_operator": (
                provider in auth_successes and provider in installation_successes
            ),
            "ordinary_grader": (
                provider in auth_successes and provider in ordinary_grader_successes
            ),
            "installation_grader": (
                provider in auth_successes and provider in installation_grader_successes
            ),
        }
        for provider in SUPPORTED_PROVIDER_CONFIGS
    }
    if (
        matrix.get("model_family_policy", {}).get("provider_role_eligibility")
        != expected_eligibility
    ):
        raise CampaignError(
            "matrix provider-role eligibility differs from exact capability "
            "probe evidence"
        )
    errors = {
        role: sorted(providers - observed[role])
        for role, providers in required.items()
        if providers - observed[role]
    }
    if errors:
        raise CampaignError(
            "matrix assigns provider roles without passing capability "
            f"evidence: {errors}"
        )
    if not required["auth"] or not (
        required["ordinary_grader"] | required["installation_grader"]
    ):
        raise CampaignError("matrix leaves no proved operator and grader path")
    return {
        "assignments": assignments,
        "required_capabilities": {
            key: [
                provider for provider in SUPPORTED_PROVIDER_CONFIGS if provider in value
            ]
            for key, value in required.items()
        },
        "proved_capabilities": {
            key: [
                provider for provider in SUPPORTED_PROVIDER_CONFIGS if provider in value
            ]
            for key, value in observed.items()
        },
        "provider_role_eligibility": expected_eligibility,
        "unsupported_candidate_roles_excluded": True,
        "all_assigned_roles_capability_proved": True,
        "authority_effect": "none",
    }


def _validate_operator_capability_index(
    *,
    index_path: Path,
    expected_schema: str,
    label: str,
) -> dict[str, Any]:
    """Validate one append-only operator capability observation.

    Provider unavailability is admissible evidence. Probe-invalid is not.
    The matrix-role check separately proves that no unavailable capability is
    assigned to a campaign run.
    """

    if not index_path.is_file() or index_path.is_symlink():
        raise CampaignError(f"{label} index is absent or unsafe")
    probe_root = index_path.parent
    if not probe_root.is_dir() or probe_root.is_symlink():
        raise CampaignError(f"{label} root is unsafe")
    index = load_json(index_path)
    expected_runner = file_record(HARNESS_DIR / "campaign_runner.py")
    if expected_runner["sha256"] != CLAUDE_RUNNER_SHA256:
        raise CampaignError(
            "current campaign_runner.py bytes differ from the audited boundary"
        )
    candidates = list(SUPPORTED_PROVIDER_CONFIGS)
    if (
        index.get("schema") != expected_schema
        or index.get("campaign_id") != CAMPAIGN_ID
        or index.get("campaign_run") is not False
        or index.get("campaign_runner") != expected_runner
        or index.get("provider_capability_policy")
        != _provider_capability_policy_record(relative_to=PACKET_DIR)
        or index.get("requested_provider_configs") != candidates
        or index.get("not_requested_provider_configs") != []
        or index.get("all_requested_provider_attempts_recorded") is not True
        or index.get("capability_observation_valid") is not True
        or index.get("invalid_probe_provider_configs") != []
        or index.get("raw_evidence_committed") is not False
        or index.get("authority_effect") != "none"
    ):
        raise CampaignError(f"{label} identity, policy, scope, or validity differs")
    attempt_id = index.get("attempt_id")
    if (
        not isinstance(attempt_id, str)
        or not attempt_id
        or Path(attempt_id).name != attempt_id
        or not isinstance(index.get("completed_at"), str)
        or not index["completed_at"]
    ):
        raise CampaignError(f"{label} attempt identity is unsafe")
    attempt_root = probe_root / "attempts" / attempt_id
    if (
        index.get("raw_evidence_location") != str(attempt_root)
        or (probe_root / "attempts").is_symlink()
        or not attempt_root.is_dir()
        or attempt_root.is_symlink()
    ):
        raise CampaignError(f"{label} raw evidence location differs")
    attempt_index = attempt_root / "index.json"
    if (
        not attempt_index.is_file()
        or attempt_index.is_symlink()
        or load_json(attempt_index) != index
    ):
        raise CampaignError(f"{label} immutable attempt index differs")
    catalog_path = probe_root / "attempt-index.jsonl"
    catalog = _load_jsonl_records(catalog_path, label=f"{label} attempt catalog")
    if len(catalog) != 1:
        raise CampaignError(f"{label} must contain exactly one pre-freeze attempt")
    catalog_record = catalog[0]
    if (
        catalog_record.get("schema")
        != "maude.synthetic-operator.probe-attempt-catalog.v1"
        or catalog_record.get("attempt_id") != attempt_id
        or catalog_record.get("attempt_index")
        != file_record(attempt_index, relative_to=probe_root)
        or catalog_record.get("requested_provider_configs") != candidates
        or catalog_record.get("capability_observation_valid") is not True
        or catalog_record.get("authority_effect") != "none"
    ):
        raise CampaignError(f"{label} attempt catalog differs")

    providers = index.get("providers")
    outcomes = index.get("provider_outcomes")
    if not isinstance(providers, list) or not isinstance(outcomes, list):
        raise CampaignError(f"{label} provider records are malformed")
    if len(outcomes) != len(candidates) or not all(
        isinstance(value, dict) for value in outcomes
    ):
        raise CampaignError(f"{label} provider outcomes are incomplete")
    outcome_configs = [value.get("provider_config") for value in outcomes]
    if outcome_configs != candidates or len(set(outcome_configs)) != len(
        outcome_configs
    ):
        raise CampaignError(f"{label} provider outcome order or set differs")

    available: dict[str, dict[str, Any]] = {}
    unavailable: dict[str, dict[str, Any]] = {}
    identities: set[str] = set()
    for outcome in outcomes:
        provider = str(outcome["provider_config"])
        status = outcome.get("status")
        provider_root = attempt_root / provider
        if not provider_root.is_dir() or provider_root.is_symlink():
            raise CampaignError(f"{label} {provider} evidence directory is unsafe")
        if outcome.get("authority_effect") != "none" or status not in {
            "available",
            "provider-capability-unavailable",
        }:
            raise CampaignError(f"{label} {provider} outcome is invalid")
        if status == "available":
            if set(outcome) != {
                "provider_config",
                "status",
                "result",
                "session_identity",
                "authority_effect",
            }:
                raise CampaignError(f"{label} {provider} success outcome shape differs")
            result_path = _exact_external_probe_record(
                outcome["result"],
                base=probe_root,
                label=f"{label} {provider} result",
            )
            if result_path != provider_root / "result.json":
                raise CampaignError(f"{label} {provider} result path differs")
            result = load_json(result_path)
            identity = outcome.get("session_identity")
            if (
                result.get("provider_config") != provider
                or result.get("status") != "available"
                or result.get("model_configuration") != PROVIDER_MODEL_CONFIGS[provider]
                or result.get("campaign_run") is not False
                or result.get("session_identity") != identity
                or result.get("authority_effect") != "none"
                or not isinstance(identity, dict)
            ):
                raise CampaignError(f"{label} {provider} result identity differs")
            identity_value = _probe_identity(identity)
            if identity_value in identities:
                raise CampaignError(f"{label} reused a provider session identity")
            identities.add(identity_value)
            available[provider] = result
            continue
        if set(outcome) != {
            "provider_config",
            "status",
            "failure",
            "session_identity",
            "authority_effect",
        }:
            raise CampaignError(f"{label} {provider} failure outcome shape differs")
        failure_path = _exact_external_probe_record(
            outcome["failure"],
            base=probe_root,
            label=f"{label} {provider} failure",
        )
        if failure_path != provider_root / "failure.json":
            raise CampaignError(f"{label} {provider} failure path differs")
        failure = load_json(failure_path)
        failure_identity = _optional_probe_identity(
            outcome.get("session_identity"),
            label=f"{label} {provider} capability failure",
        )
        if (
            failure.get("schema")
            != "maude.synthetic-operator.provider-capability-failure.v1"
            or failure.get("provider_config") != provider
            or failure.get("model_configuration") != PROVIDER_MODEL_CONFIGS[provider]
            or failure.get("campaign_run") is not False
            or failure.get("status") != status
            or failure.get("failure_classification") != status
            or failure.get("session_identity") != outcome.get("session_identity")
            or failure.get("provider_session_identity_observed")
            is not (failure_identity is not None)
            or failure.get("partial_evidence_preserved") is not True
            or failure.get("retry_or_provider_selection_decision_made") is not False
            or failure.get("task_level_network_or_external_operational_effect")
            is not False
            or failure.get("authority_effect") != "none"
            or not _is_sha256(failure.get("diagnostic_sha256"))
        ):
            raise CampaignError(f"{label} {provider} capability failure differs")
        if failure_identity is not None:
            if failure_identity in identities:
                raise CampaignError(f"{label} reused a provider session identity")
            identities.add(failure_identity)
        unavailable[provider] = failure

    provider_by_config = {
        value.get("provider_config"): value
        for value in providers
        if isinstance(value, dict)
    }
    if (
        len(provider_by_config) != len(providers)
        or set(provider_by_config) != set(available)
        or any(
            provider_by_config[provider] != result
            for provider, result in available.items()
        )
    ):
        raise CampaignError(f"{label} successful provider records differ from outcomes")
    successful = [provider for provider in candidates if provider in available]
    failed = [provider for provider in candidates if provider in unavailable]
    if (
        index.get("successful_provider_configs") != successful
        or index.get("failed_provider_configs") != failed
        or index.get("unavailable_provider_configs") != failed
        or index.get("all_passed") is not (not bool(failed))
        or catalog_record.get("successful_provider_configs") != successful
        or catalog_record.get("failed_provider_configs") != failed
        or catalog_record.get("unavailable_provider_configs") != failed
        or catalog_record.get("invalid_probe_provider_configs") != []
        or catalog_record.get("all_passed") is not (not bool(failed))
    ):
        raise CampaignError(f"{label} capability outcome summaries differ")
    return {
        "index": index,
        "attempt_root": attempt_root,
        "expected_runner": expected_runner,
        "available": available,
        "unavailable": unavailable,
        "successful_provider_configs": successful,
        "unavailable_provider_configs": failed,
        "session_identities": identities,
    }


def _provider_probe_summary() -> dict[str, Any]:
    observation = _validate_operator_capability_index(
        index_path=AUTH_GATE_PROBE_PATH,
        expected_schema=("maude.synthetic-operator.provider-auth-gate-probes.v2"),
        label="provider auth/isolation probe",
    )
    index = observation["index"]
    expected_runner = observation["expected_runner"]
    probe_root = AUTH_GATE_PROBE_PATH.parent
    attempt_root = observation["attempt_root"]
    providers = list(observation["available"].values())

    sanitized: list[dict[str, Any]] = []
    identities: set[str] = set()
    for item in sorted(
        providers,
        key=lambda value: list(SUPPORTED_PROVIDER_CONFIGS).index(
            value["provider_config"]
        ),
    ):
        provider = item["provider_config"]
        provider_root = attempt_root / provider
        if not provider_root.is_dir() or provider_root.is_symlink():
            raise CampaignError(f"{provider}: raw auth-probe directory is unsafe")
        process = item.get("process")
        identity = item.get("session_identity")
        safety = item.get("safety_audit")
        delivery = item.get("delivery")
        if not all(
            isinstance(value, dict) for value in (process, identity, safety, delivery)
        ):
            raise CampaignError(f"{provider}: malformed probe result")
        gate = process.get("provider_auth_gate")
        if not isinstance(gate, dict):
            raise CampaignError(f"{provider}: missing provider auth gate")
        identity_value = identity.get("provider_session_id") or identity.get(
            "provider_thread_id"
        )
        if not isinstance(identity_value, str) or not identity_value:
            raise CampaignError(f"{provider}: fresh session identity absent")
        if identity_value in identities:
            raise CampaignError("provider probes reused a session identity")
        identities.add(identity_value)
        auth_absence_check = item.get("authorized_codex_auth_absence_check")
        codex_absence_facts = (
            isinstance(auth_absence_check, dict)
            and auth_absence_check.get("accepted_argument_key_sets")
            == [["command"], ["command", "timeout_seconds"]]
            and auth_absence_check.get("optional_explicit_timeout_seconds")
            == CODEX_PROBE_TERMINAL_TIMEOUT_SECONDS
            and _is_sha256(auth_absence_check.get("command_sha256"))
            if provider == "openai-sol"
            else auth_absence_check is None
        )
        common_facts = (
            process.get("returncode") == 0,
            process.get("timed_out") is False,
            process.get("fresh_process") is True,
            process.get("follow_up_messages") == 0,
            process.get("coaching") == "none",
            item.get("campaign_run") is False,
            item.get("fresh_process") is True,
            item.get("tool_actions_after_gate") == 2,
            len(item.get("distinct_completed_action_event_numbers") or []) == 2,
            isinstance(item.get("completed_action_events"), list),
            len(item.get("completed_action_events") or []) == 2,
            item.get("completed_action_events")
            == item.get("successful_completed_action_events"),
            item.get("final_marker_present") is True,
            item.get("final_marker_after_second_tool_result") is True,
            set(item.get("required_clean_home_markers") or [])
            == {
                "HOME=/home/operator",
                "CLEAN_HOME_WRITE_OK",
                "PROVIDER_AUTH_ABSENT_OK",
            },
            item.get("missing_clean_home_markers") == [],
            item.get("authorized_auth_path_absence_checks_only") is True,
            codex_absence_facts,
            item.get("unauthorized_auth_probe_reads") == [],
            safety.get("environment_read_attempts") == [],
            safety.get("network_command_attempts") == [],
            safety.get("host_source_read_attempts") == [],
            item.get("authority_effect") == "none",
        )
        if not all(common_facts):
            raise CampaignError(
                f"{provider}: provider auth/isolation proof facts are incomplete"
            )
        config = PROVIDER_MODEL_CONFIGS[provider]
        expected_delivery_provider = config["provider"]
        expected_model = config["model_argument"]
        if (
            delivery.get("provider") != expected_delivery_provider
            or delivery.get("requested_model") != expected_model
        ):
            raise CampaignError(f"{provider}: auth-probe delivery differs")
        gate_actions = gate.get("tool_actions")
        if provider == "openai-sol":
            if (
                not _is_sha256(delivery.get("delivered_prompt_sha256"))
                or delivery.get("allowed_unix_sockets") != []
                or delivery.get("intrinsic_action_features_explicitly_disabled")
                != CODEX_DISABLED_INTRINSIC_ACTION_FEATURES
                or delivery.get("optional_features_explicitly_disabled")
                != CODEX_DISABLED_OPTIONAL_FEATURES
                or delivery.get("live_web_search_enabled") is not False
                or delivery.get("provider_task_paths_added") != []
                or delivery.get("user_mcp_and_connector_config_loaded") is not False
                or delivery.get("mcp_server") != "operator"
                or delivery.get("mcp_protocol_version") != CODEX_MCP_PROTOCOL_VERSION
                or delivery.get("mcp_config_sha256") != gate.get("mcp_config_sha256")
                or delivery.get("mcp_enabled_tools") != CODEX_OPERATOR_TOOLS
                or delivery.get("codex_approval_argv") != CODEX_APPROVAL_CONFIG_ARGV
                or delivery.get("codex_approval_config_override")
                != CODEX_APPROVAL_CONFIG
                or delivery.get("codex_approval_policy") != CODEX_APPROVAL_POLICY
                or delivery.get("noninteractive_approval_safety_basis")
                != _codex_approval_safety_basis(tool="terminal")
                or delivery.get("codex_mcp_default_tools_approval_mode")
                != CODEX_MCP_DEFAULT_TOOLS_APPROVAL_MODE
                or delivery.get("codex_mcp_approval_config_override")
                != ('mcp_servers.operator.default_tools_approval_mode="approve"')
                or delivery.get("mcp_tool_approval_safety_basis")
                != _codex_mcp_tool_approval_safety_basis(tool="terminal")
                or delivery.get("exact_provider_tool_allowlist_supported") is not True
                or delivery.get("unexpected_intrinsic_action_policy") != "fail-closed"
            ):
                raise CampaignError(f"{provider}: auth-probe Codex delivery differs")
            _validate_codex_provider_boundary(
                provider=provider,
                process=process,
                gate=gate,
                provider_root=provider_root,
                expected_tool_actions=2,
                expect_pty_broker=False,
            )
            absence_arguments = (
                gate_actions[1].get("arguments")
                if isinstance(gate_actions, list)
                and len(gate_actions) == 2
                and isinstance(gate_actions[1], dict)
                else None
            )
            if (
                not isinstance(absence_arguments, dict)
                or hashlib.sha256(
                    absence_arguments["command"].encode("utf-8")
                ).hexdigest()
                != auth_absence_check["command_sha256"]
            ):
                raise CampaignError(
                    f"{provider}: auth-absence command evidence differs"
                )
            boundary_identity = gate.get("identity", {}).get("provider_thread_id")
            boundary_kind = (
                "task-blind-retained-auth-codex-transport-with-exact-"
                "stdio-mcp-and-per-command-sandbox"
            )
        else:
            if (
                not isinstance(delivery.get("requested_session_id"), str)
                or not delivery["requested_session_id"]
                or delivery.get("system_prompt_delivery") != "system"
                or delivery.get("user_prompt_delivery")
                != (
                    "single stream-json user event after flushed MCP "
                    "tools/list readiness; stdin then closed"
                )
                or not _is_sha256(delivery.get("user_prompt_sha256"))
                or delivery.get("mcp_protocol_version") != CLAUDE_MCP_PROTOCOL_VERSION
                or delivery.get("mcp_config_sha256") != gate.get("mcp_config_sha256")
                or delivery.get("allowed_tools") != CLAUDE_OPERATOR_TOOLS
                or delivery.get("built_in_tools") != []
                or delivery.get("provider_task_paths_added") != []
                or delivery.get("provider_unix_sockets_added") != []
            ):
                raise CampaignError(f"{provider}: auth-probe Claude delivery differs")
            _validate_claude_boundary(
                provider=provider,
                process=process,
                gate=gate,
                provider_root=provider_root,
                expected_tool_actions=2,
                expect_pty_broker=False,
            )
            boundary_identity = gate.get("identity", {}).get("provider_session_id")
            boundary_kind = (
                "task-blind-retained-auth-claude-transport-with-"
                "credential-free-mcp-proxy-and-per-command-sandbox"
            )
        if boundary_identity != identity_value:
            raise CampaignError(f"{provider}: auth-probe boundary identity differs")
        gate_path = _exact_external_probe_record(
            item.get("gate_record"),
            base=probe_root,
            label=f"{provider} auth-probe gate",
        )
        if gate_path != provider_root / "auth-gate.json":
            raise CampaignError(f"{provider}: auth-probe gate path differs")
        if load_json(gate_path) != gate:
            raise CampaignError(f"{provider}: raw auth-probe gate differs")
        for field, name in (
            ("raw_transcript", "transcript.jsonl"),
            ("raw_stderr", "provider.stderr"),
        ):
            path = _exact_external_probe_record(
                item.get(field),
                base=probe_root,
                label=f"{provider} auth-probe {field}",
            )
            if path != provider_root / name:
                raise CampaignError(f"{provider}: auth-probe {field} path differs")
        result_path = provider_root / "result.json"
        if (
            not result_path.is_file()
            or result_path.is_symlink()
            or load_json(result_path) != item
        ):
            raise CampaignError(f"{provider}: raw auth-probe result differs")
        expected_files = {
            "auth-gate.json",
            "isolation.json",
            "provider.stderr",
            "result.json",
            "system-prompt.md",
            "transcript.jsonl",
            "user-prompt.md",
        }
        expected_files |= (
            _codex_boundary_files(include_pty=False)
            if provider == "openai-sol"
            else _claude_boundary_files(include_pty=False)
        )
        actual_files = {
            path.relative_to(provider_root).as_posix()
            for path in provider_root.rglob("*")
            if path.is_file() and not path.is_symlink()
        }
        if actual_files != expected_files or any(
            path.is_symlink() for path in provider_root.rglob("*")
        ):
            raise CampaignError(f"{provider}: raw auth-probe file set differs")
        sanitized.append(
            {
                "provider_config": provider,
                "session_identity": identity,
                "returncode": 0,
                "timed_out": False,
                "fresh_process": True,
                "tool_actions_after_gate": item["tool_actions_after_gate"],
                "successful_action_results": len(
                    item.get("successful_completed_action_events") or []
                ),
                "clean_home_write_and_read_proved": True,
                "operator_action_boundary_provider_auth_absence_proved": True,
                "provider_boundary_kind": boundary_kind,
                "provider_auth_retained_until_transport_exit": True,
                "trusted_stdio_shim_auth_read_observed": False,
                "strict_mcp_and_per_command_sandbox_proved": True,
                "final_marker_after_tool_results": True,
                "raw_transcript": {
                    key: item["raw_transcript"][key] for key in ("bytes", "sha256")
                },
                "raw_stderr": {
                    key: item["raw_stderr"][key] for key in ("bytes", "sha256")
                },
                "gate_record": {
                    key: item["gate_record"][key] for key in ("bytes", "sha256")
                },
            }
        )
    return {
        "schema": "maude.synthetic-operator.provider-probe-summary.v1",
        "attempt_id": index.get("attempt_id"),
        "completed_at": index.get("completed_at"),
        "probe_index": {
            "bytes": AUTH_GATE_PROBE_PATH.stat().st_size,
            "sha256": sha256_file(AUTH_GATE_PROBE_PATH),
        },
        "campaign_runner": expected_runner,
        "mcp_stdio_shim": file_record(CLAUDE_MCP_BRIDGE),
        "providers": sanitized,
        "successful_provider_configs": observation["successful_provider_configs"],
        "unavailable_provider_configs": observation["unavailable_provider_configs"],
        "all_observed_session_identities": sorted(observation["session_identities"]),
        "unavailable_provider_failures": {
            provider: {
                "failure_stage": failure["failure_stage"],
                "failure_classification": failure["failure_classification"],
                "provider_process_launch_state": failure[
                    "provider_process_launch_state"
                ],
                "provider_session_identity_observed": failure[
                    "provider_session_identity_observed"
                ],
                "provider_network_attempted": failure["provider_network_attempted"],
                "provider_network_use_observed": failure[
                    "provider_network_use_observed"
                ],
            }
            for provider, failure in sorted(observation["unavailable"].items())
        },
        "capability_observation_valid": True,
        "raw_probe_evidence_committed": False,
        "all_passed": index["all_passed"],
        "authority_effect": "none",
    }


def _grader_surface_probe_summary() -> dict[str, Any]:
    """Validate and summarize provider-scoped pre-freeze grader probes.

    A stable provider-capability failure is admissible evidence.  An invalid
    probe is not.  The later role-assignment check proves that the frozen
    matrix does not assign a grader role to an unavailable provider/probe
    pair.
    """

    errors = grader_surface_probe.validate_probes(require_all_passed=False)
    if errors:
        raise CampaignError(
            "grader-surface capability probes are incomplete: " + "; ".join(errors)
        )
    index_path = grader_surface_probe.OUTPUT_ROOT / "index.json"
    index = load_json(index_path)
    expected_runner = file_record(HARNESS_DIR / "campaign_runner.py")
    expected_probe_runner = file_record(HARNESS_DIR / "grader_surface_probe.py")
    if (
        expected_runner["sha256"] != CLAUDE_RUNNER_SHA256
        or index.get("campaign_runner") != expected_runner
    ):
        raise CampaignError(
            "grader-surface probes do not bind the final audited "
            "campaign_runner.py bytes"
        )
    if (
        expected_probe_runner["sha256"] != GRADER_SURFACE_PROBE_SHA256
        or index.get("probe_runner") != expected_probe_runner
    ):
        raise CampaignError(
            "grader-surface probes do not bind the final audited probe-runner bytes"
        )
    candidates = list(SUPPORTED_PROVIDER_CONFIGS)
    expected_probe_ids = ("ordinary", "installation")
    if (
        index.get("schema") != "maude.synthetic-operator.grader-surface-probes.v2"
        or index.get("campaign_id") != CAMPAIGN_ID
        or index.get("campaign_run") is not False
        or index.get("requested_provider_configs") != candidates
        or index.get("not_requested_provider_configs") != []
        or index.get("provider_model_configurations")
        != {provider: PROVIDER_MODEL_CONFIGS[provider] for provider in candidates}
        or index.get("provider_capability_policy")
        != _provider_capability_policy_record(relative_to=PACKET_DIR)
        or index.get("all_requested_provider_probe_attempts_recorded") is not True
        or index.get("capability_observation_valid") is not True
        or index.get("invalid_probe_pairs") != []
        or index.get("distinct_fresh_session_identities") is not True
        or index.get("provider_network_permitted_for_probe_sessions") is not True
        or index.get("task_level_network_or_external_operational_effect") is not False
        or index.get("raw_evidence_committed") is not False
        or index.get("authority_effect") != "none"
    ):
        raise CampaignError(
            "grader-surface probe identity, policy, scope, or validity differs"
        )
    attempt_id = index.get("attempt_id")
    if (
        not isinstance(attempt_id, str)
        or not attempt_id
        or Path(attempt_id).name != attempt_id
        or not isinstance(index.get("completed_at"), str)
        or not index["completed_at"]
    ):
        raise CampaignError("grader-surface attempt identity is unsafe")
    probe_root = grader_surface_probe.OUTPUT_ROOT
    attempt_root = probe_root / "attempts" / attempt_id
    if (
        index.get("raw_evidence_location") != str(attempt_root)
        or not attempt_root.is_dir()
        or attempt_root.is_symlink()
    ):
        raise CampaignError("grader-surface raw evidence location differs")
    attempt_index = attempt_root / "index.json"
    if (
        not attempt_index.is_file()
        or attempt_index.is_symlink()
        or load_json(attempt_index) != index
    ):
        raise CampaignError("grader-surface immutable attempt index differs")
    catalog = _load_jsonl_records(
        probe_root / "attempt-index.jsonl",
        label="grader-surface attempt catalog",
    )
    if len(catalog) != 1:
        raise CampaignError(
            "grader-surface probes must contain exactly one pre-freeze attempt"
        )
    catalog_record = catalog[0]
    if (
        catalog_record.get("schema")
        != ("maude.synthetic-operator.grader-surface-probe-attempt-catalog.v1")
        or catalog_record.get("attempt_id") != attempt_id
        or catalog_record.get("attempt_index")
        != file_record(attempt_index, relative_to=probe_root)
        or catalog_record.get("requested_provider_configs") != candidates
        or catalog_record.get("invalid_probe_pairs") != []
        or catalog_record.get("capability_observation_valid") is not True
        or catalog_record.get("authority_effect") != "none"
    ):
        raise CampaignError("grader-surface attempt catalog differs")

    outcomes = index.get("provider_probe_outcomes")
    expected_pairs = [
        (provider, probe_id)
        for provider in candidates
        for probe_id in expected_probe_ids
    ]
    if (
        not isinstance(outcomes, list)
        or not all(isinstance(value, dict) for value in outcomes)
        or [(value.get("provider_config"), value.get("probe_id")) for value in outcomes]
        != expected_pairs
    ):
        raise CampaignError(
            "grader-surface provider/probe outcome order or set differs"
        )

    summarized: list[dict[str, Any]] = []
    unavailable: list[dict[str, Any]] = []
    identities: set[str] = set()
    identity_records: list[dict[str, str]] = []
    successful_pairs: list[str] = []
    failed_pairs: list[str] = []
    unavailable_pairs: list[str] = []
    for outcome in outcomes:
        provider = str(outcome["provider_config"])
        probe_id = str(outcome["probe_id"])
        pair = f"{provider}/{probe_id}"
        status = outcome.get("status")
        expected_surface = "maude" if probe_id == "ordinary" else "maude-installation"
        if (
            outcome.get("surface") != expected_surface
            or outcome.get("campaign_run") is not False
            or outcome.get("authority_effect") != "none"
            or status not in {"available", "provider-capability-unavailable"}
        ):
            raise CampaignError(f"{pair}: grader outcome differs")
        provider_probe_root = attempt_root / provider / probe_id
        if not provider_probe_root.is_dir() or provider_probe_root.is_symlink():
            raise CampaignError(f"{pair}: grader evidence root is unsafe")
        if status != "available":
            if set(outcome) != {
                "provider_config",
                "probe_id",
                "surface",
                "status",
                "session_identity",
                "failure",
                "campaign_run",
                "authority_effect",
            }:
                raise CampaignError(f"{pair}: grader failure outcome shape differs")
            failed_pairs.append(pair)
            unavailable_pairs.append(pair)
            failure_path = _exact_external_probe_record(
                outcome.get("failure"),
                base=probe_root,
                label=f"{pair} grader capability failure",
            )
            if failure_path != provider_probe_root / "failure.json":
                raise CampaignError(f"{pair}: grader failure path differs")
            failure = load_json(failure_path)
            failure_identity = _optional_probe_identity(
                outcome.get("session_identity"),
                label=f"{pair} grader capability failure",
            )
            if (
                failure.get("schema")
                != ("maude.synthetic-operator.grader-surface-probe-failure.v1")
                or failure.get("campaign_id") != CAMPAIGN_ID
                or failure.get("probe_id") != probe_id
                or failure.get("provider_config") != provider
                or failure.get("model_configuration")
                != PROVIDER_MODEL_CONFIGS[provider]
                or failure.get("campaign_run") is not False
                or failure.get("status") != status
                or failure.get("failure_classification") != status
                or failure.get("session_identity") != outcome.get("session_identity")
                or failure.get("partial_evidence_preserved") is not True
                or failure.get("task_level_network_or_external_operational_effect")
                is not False
                or failure.get("all_passed") is not False
                or failure.get("authority_effect") != "none"
                or not _is_sha256(failure.get("diagnostic_sha256"))
            ):
                raise CampaignError(f"{pair}: grader capability failure differs")
            if failure_identity is not None:
                if failure_identity in identities:
                    raise CampaignError(
                        "grader capability probes reused a session identity"
                    )
                identities.add(failure_identity)
                identity_records.append(
                    {
                        "provider_config": provider,
                        "probe_id": probe_id,
                        "identity": failure_identity,
                    }
                )
            unavailable.append(
                {
                    "provider_config": provider,
                    "probe_id": probe_id,
                    "failure_stage": failure["failure_stage"],
                    "failure_classification": status,
                    "session_identity": outcome["session_identity"],
                    "provider_process_launch_state": failure[
                        "provider_process_launch_state"
                    ],
                    "provider_network_attempted": failure["provider_network_attempted"],
                    "provider_network_use_observed": failure[
                        "provider_network_use_observed"
                    ],
                    "failure": {
                        key: outcome["failure"][key] for key in ("bytes", "sha256")
                    },
                }
            )
            continue

        if set(outcome) != {
            "provider_config",
            "probe_id",
            "surface",
            "status",
            "session_identity",
            "result",
            "campaign_run",
            "authority_effect",
        }:
            raise CampaignError(f"{pair}: grader success outcome shape differs")
        successful_pairs.append(pair)
        result_path = _exact_external_probe_record(
            outcome.get("result"),
            base=probe_root,
            label=f"{pair} grader result",
        )
        if result_path != provider_probe_root / "result.json":
            raise CampaignError(f"{pair}: grader result path differs")
        result = load_json(result_path)
        delivery = result.get("prompt_delivery")
        boundary = result.get("action_boundary")
        identity = result.get("session_identity")
        validation = result.get("schema_validation")
        if not all(
            isinstance(value, dict)
            for value in (delivery, boundary, identity, validation)
        ):
            raise CampaignError(f"{pair}: grader-surface result is malformed")
        if (
            result.get("schema")
            != "maude.synthetic-operator.grader-surface-probe-result.v1"
            or result.get("campaign_id") != CAMPAIGN_ID
            or result.get("probe_id") != probe_id
            or result.get("provider_config") != provider
            or result.get("model_configuration") != PROVIDER_MODEL_CONFIGS[provider]
            or result.get("status") != "available"
            or delivery.get("exceeds_131072_bytes") is not True
            or not _is_sha256(delivery.get("semantic_prompt_sha256"))
            or boundary.get("all_actions_read_only_evidence") is not True
            or boundary.get("all_provider_actions_represented_once") is not True
            or boundary.get("zero_auth_env_network_source_attempts") is not True
            or validation.get("jsonschema_passed") is not True
            or validation.get("local_failure_classes_uniqueness_passed") is not True
            or validation.get("successor_schema_has_no_uniqueItems") is not True
            or result.get("campaign_run") is not False
            or result.get("task_level_network_or_external_operational_effect")
            is not False
            or result.get("all_passed") is not True
            or result.get("authority_effect") != "none"
        ):
            raise CampaignError(f"{pair}: grader-surface capability predicates differ")
        identity_value = _probe_identity(identity)
        if identity_value in identities:
            raise CampaignError(
                f"{pair}: grader-surface fresh session identity was reused"
            )
        identities.add(identity_value)
        identity_records.append(
            {
                "provider_config": provider,
                "probe_id": probe_id,
                "identity": identity_value,
            }
        )
        if outcome.get("session_identity") != identity:
            raise CampaignError(f"{pair}: grader outcome identity differs")
        if provider == "openai-sol":
            if (
                delivery.get("method") != "closed-stdin"
                or delivery.get("stdin_used") is not True
                or delivery.get("stdin_closed_after_single_write") is not True
                or delivery.get("semantic_prompt_bytes_in_argv") is not False
                or delivery.get("provider_argv_final_argument") != "-"
            ):
                raise CampaignError(f"{pair}: Codex grader prompt transport differs")
        elif (
            delivery.get("method") != "stream-json-user-event"
            or delivery.get("stdin_used") is not False
            or delivery.get("stream_json_user_event_used") is not True
            or delivery.get("user_assignment_bytes_in_argv") is not False
        ):
            raise CampaignError(f"{pair}: Claude grader prompt transport differs")
        summarized.append(
            {
                "provider_config": provider,
                "probe_id": probe_id,
                "surface": expected_surface,
                "session_identity": identity,
                "schema": validation["source"],
                "semantic_prompt_bytes": delivery["semantic_prompt_bytes"],
                "semantic_prompt_sha256": delivery["semantic_prompt_sha256"],
                "read_only_evidence_actions": boundary["action_count"],
                "prompt_transport_method": delivery["method"],
                "result": file_record(result_path, relative_to=probe_root),
                "all_passed": True,
            }
        )
    successful_by_probe = {
        probe_id: [
            provider
            for provider in candidates
            if f"{provider}/{probe_id}" in successful_pairs
        ]
        for probe_id in expected_probe_ids
    }
    unavailable_by_probe = {
        probe_id: [
            provider
            for provider in candidates
            if f"{provider}/{probe_id}" in unavailable_pairs
        ]
        for probe_id in expected_probe_ids
    }
    if (
        index.get("successful_provider_probe_pairs") != successful_pairs
        or index.get("failed_provider_probe_pairs") != failed_pairs
        or index.get("unavailable_provider_probe_pairs") != unavailable_pairs
        or catalog_record.get("successful_provider_probe_pairs") != successful_pairs
        or catalog_record.get("failed_provider_probe_pairs") != failed_pairs
        or catalog_record.get("all_passed") is not (not bool(failed_pairs))
        or index.get("all_passed") is not (not bool(failed_pairs))
    ):
        raise CampaignError("grader-surface capability outcome summaries differ")
    if index.get("provider_session_identities") != identity_records:
        raise CampaignError("grader-surface capability identity index differs")
    return {
        "schema": ("maude.synthetic-operator.grader-surface-probe-summary.v2"),
        "attempt_id": attempt_id,
        "completed_at": index["completed_at"],
        "probe_index": file_record(index_path),
        "campaign_runner": expected_runner,
        "probe_runner": expected_probe_runner,
        "probes": sorted(
            summarized,
            key=lambda value: (
                candidates.index(value["provider_config"]),
                expected_probe_ids.index(value["probe_id"]),
            ),
        ),
        "unavailable_probes": unavailable,
        "successful_provider_configs_by_probe": successful_by_probe,
        "unavailable_provider_configs_by_probe": unavailable_by_probe,
        "all_observed_session_identities": sorted(identities),
        "distinct_fresh_session_identities": True,
        "exact_successor_schemas_accepted": True,
        "large_prompts_delivered_by_provider_transport": True,
        "semantic_user_assignment_bytes_in_argv": False,
        "read_only_evidence_boundary": True,
        "campaign_run": False,
        "provider_network_permitted": True,
        "task_level_network_or_external_operational_effect": False,
        "raw_probe_evidence_frozen_in_packet": True,
        "capability_observation_valid": True,
        "all_passed": index["all_passed"],
        "authority_effect": "none",
    }


def _probe_identity(value: dict[str, Any]) -> str:
    identity = value.get("provider_session_id") or value.get("provider_thread_id")
    if not isinstance(identity, str) or not identity:
        raise CampaignError("provider probe session identity is absent")
    return identity


def _optional_probe_identity(value: Any, *, label: str) -> str | None:
    if value == {}:
        return None
    if not isinstance(value, dict):
        raise CampaignError(f"{label}: provider session identity is malformed")
    values = [
        identity
        for identity in (
            value.get("provider_session_id"),
            value.get("provider_thread_id"),
        )
        if isinstance(identity, str) and identity
    ]
    if len(values) != 1:
        raise CampaignError(
            f"{label}: provider session identity is ambiguous or malformed"
        )
    return values[0]


def _is_sha256(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64 or value != value.lower():
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _exact_external_probe_record(
    record: Any,
    *,
    base: Path,
    label: str,
) -> Path:
    if not isinstance(record, dict) or not isinstance(record.get("path"), str):
        raise CampaignError(f"{label}: external file record is malformed")
    relative = Path(record["path"])
    if (
        relative.is_absolute()
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise CampaignError(f"{label}: unsafe external record path")
    if not base.is_dir() or base.is_symlink():
        raise CampaignError(f"{label}: external record base is unsafe")
    current = base
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise CampaignError(f"{label}: external record traverses a symlink")
    if not current.is_file():
        raise CampaignError(f"{label}: external record file is absent")
    actual = file_record(current, relative_to=base)
    if actual != record:
        raise CampaignError(f"{label}: external file record differs")
    return current


def _canonical_json_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _load_jsonl_records(path: Path, *, label: str) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        records = [json.loads(line) for line in lines if line]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CampaignError(f"{label}: malformed JSONL evidence: {exc}") from exc
    if not all(isinstance(value, dict) for value in records):
        raise CampaignError(f"{label}: JSONL evidence contains a non-object")
    return records


def _record_bytes_match_copy(record: Any, copied: Path, *, label: str) -> None:
    if not isinstance(record, dict):
        raise CampaignError(f"{label}: source file record is malformed")
    actual = file_record(copied, relative_to=copied.parent)
    for key in ("media_type", "bytes", "sha256", "mode"):
        if record.get(key) != actual.get(key):
            raise CampaignError(f"{label}: copied bytes differ for record field {key}")


def _codex_approval_safety_basis(*, tool: str) -> dict[str, Any]:
    return {
        "intrinsic_action_features_disabled": (
            CODEX_DISABLED_INTRINSIC_ACTION_FEATURES
        ),
        "single_enabled_mcp_tool": tool,
        "operator_terminal_bounded_by_frozen_broker": tool == "terminal",
        "grader_evidence_tool_read_only": tool == "evidence",
        "rationale": (
            "Non-interactive approval is safe here only because Codex intrinsic "
            "action features are disabled and operator sessions expose exactly "
            "one MCP terminal bounded by the frozen broker; grader sessions "
            "expose exactly one read-only evidence tool."
        ),
    }


def _codex_mcp_tool_approval_safety_basis(*, tool: str) -> dict[str, Any]:
    return {
        "mcp_config_hash_pinned": True,
        "exact_enabled_tool_count": 1,
        "single_enabled_mcp_tool": tool,
        "operator_terminal_bounded_by_frozen_broker": tool == "terminal",
        "grader_evidence_tool_read_only": tool == "evidence",
        "rationale": (
            "MCP tool auto-approval is safe here only because the hash-pinned "
            "server exposes exactly one tool: the operator terminal is bounded "
            "by the frozen broker, while the grader evidence tool is read-only."
        ),
    }


def _codex_normalized_mcp_result_text(result: Any) -> str:
    if (
        not isinstance(result, dict)
        or set(result) != {"content", "structured_content"}
        or result.get("structured_content") is not None
    ):
        raise CampaignError(
            "Codex MCP result is not the exact normalized result envelope"
        )
    content = result.get("content")
    if not isinstance(content, list) or len(content) != 1:
        raise CampaignError(
            "Codex MCP result does not contain exactly one content block"
        )
    block = content[0]
    if (
        not isinstance(block, dict)
        or set(block) != {"type", "text"}
        or block.get("type") != "text"
        or not isinstance(block.get("text"), str)
    ):
        raise CampaignError("Codex MCP result content is not one exact text block")
    return block["text"]


_COMMAND_BROKER_RESULT_KEYS = {
    "command",
    "cwd",
    "returncode",
    "stderr",
    "stderr_truncated",
    "stdout",
    "stdout_truncated",
    "timed_out",
}
_PTY_STATE_KEYS = {
    "captured_bytes",
    "child_pid",
    "command",
    "daemon_pid",
    "exit_code",
    "output",
    "schema",
    "status",
    "updated_at",
}
_PTY_READ_KEYS = {
    "bytes_read",
    "from_offset",
    "next_offset",
    "status",
}
_PTY_ACK_KEYS = {
    "accepted",
    "acknowledged_at",
    "error",
    "inputs_sent",
    "operation",
    "request_id",
    "schema",
    "state",
}


def _exact_json_object(text: str, *, label: str) -> dict[str, Any]:
    def reject_duplicates(
        pairs: list[tuple[str, Any]],
    ) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise CampaignError(f"{label} contains duplicate JSON keys")
            value[key] = item
        return value

    try:
        value = json.loads(text, object_pairs_hook=reject_duplicates)
    except json.JSONDecodeError as exc:
        raise CampaignError(f"{label} is not one exact JSON object") from exc
    if not isinstance(value, dict):
        raise CampaignError(f"{label} is not a JSON object")
    return value


def _validate_installation_pty_state(value: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _PTY_STATE_KEYS:
        raise CampaignError(f"{label} PTY state key set differs")
    if (
        value.get("schema") != "maude.synthetic-operator.stateful-pty.v1"
        or type(value.get("daemon_pid")) is not int
        or value["daemon_pid"] <= 0
        or type(value.get("child_pid")) is not int
        or value["child_pid"] <= 0
        or type(value.get("captured_bytes")) is not int
        or value["captured_bytes"] < 0
        or not isinstance(value.get("command"), list)
        or not value["command"]
        or not all(isinstance(item, str) for item in value["command"])
        or not isinstance(value.get("output"), str)
        or not value["output"]
        or value.get("status") not in {"running", "completed"}
        or (
            value.get("exit_code") is not None
            and type(value.get("exit_code")) is not int
        )
        or not isinstance(value.get("updated_at"), str)
        or not value["updated_at"]
    ):
        raise CampaignError(f"{label} PTY state field contract differs")
    return value


def _parse_installation_broker_result(
    output: str,
    *,
    expected_command: str,
    expected_cwd: Path,
    payload_kind: str,
) -> dict[str, Any]:
    if payload_kind not in {"state", "read", "ack"}:
        raise CampaignError(
            f"unsupported installation-probe payload kind: {payload_kind}"
        )
    broker_result = _exact_json_object(
        output, label="installation-probe command-broker result"
    )
    if (
        set(broker_result) != _COMMAND_BROKER_RESULT_KEYS
        or broker_result.get("command") != expected_command
        or broker_result.get("cwd") != str(expected_cwd)
        or type(broker_result.get("returncode")) is not int
        or broker_result["returncode"] != 0
        or broker_result.get("timed_out") is not False
        or broker_result.get("stdout_truncated") is not False
        or broker_result.get("stderr_truncated") is not False
        or not isinstance(broker_result.get("stdout"), str)
        or not isinstance(broker_result.get("stderr"), str)
    ):
        raise CampaignError("installation-probe command-broker result contract differs")
    metadata_stream = "stdout" if payload_kind == "state" else "stderr"
    payload = _exact_json_object(
        broker_result[metadata_stream],
        label=f"installation-probe {payload_kind} payload",
    )
    if payload_kind == "state":
        _validate_installation_pty_state(payload, label="installation-probe state")
        if broker_result["stderr"] != "":
            raise CampaignError("installation-probe state result has unexpected stderr")
    elif payload_kind == "read":
        if (
            set(payload) != _PTY_READ_KEYS
            or type(payload.get("bytes_read")) is not int
            or payload["bytes_read"] <= 0
            or type(payload.get("from_offset")) is not int
            or payload["from_offset"] < 0
            or type(payload.get("next_offset")) is not int
            or payload["next_offset"] <= payload["from_offset"]
            or payload["next_offset"] - payload["from_offset"] != payload["bytes_read"]
            or payload.get("status") not in {"running", "completed"}
            or not broker_result["stdout"]
        ):
            raise CampaignError("installation-probe PTY read payload contract differs")
    else:
        if (
            set(payload) != _PTY_ACK_KEYS
            or payload.get("schema") != "maude.synthetic-operator.stateful-pty-ack.v1"
            or payload.get("accepted") is not True
            or payload.get("error") is not None
            or type(payload.get("inputs_sent")) is not int
            or payload["inputs_sent"] <= 0
            or payload.get("operation") not in {"send", "stop"}
            or not isinstance(payload.get("request_id"), str)
            or not payload["request_id"]
            or not isinstance(payload.get("acknowledged_at"), str)
            or not payload["acknowledged_at"]
            or broker_result["stdout"] != ""
        ):
            raise CampaignError(
                "installation-probe PTY acknowledgement contract differs"
            )
        _validate_installation_pty_state(
            payload.get("state"), label="installation-probe acknowledgement"
        )
    return {
        "broker_result": broker_result,
        "metadata_stream": metadata_stream,
        "payload": payload,
    }


def _validate_codex_provider_boundary(
    *,
    provider: str,
    process: dict[str, Any],
    gate: dict[str, Any],
    provider_root: Path,
    expected_tool_actions: int,
    expect_pty_broker: bool,
) -> None:
    label = f"{provider}: Codex strict MCP retained-auth boundary"
    expected_tool = "terminal"
    expected_server = "operator"
    expected_mcp_approval_config = (
        'mcp_servers.operator.default_tools_approval_mode="approve"'
    )
    boundary_root = provider_root / "codex-mcp-boundary"
    if not boundary_root.is_dir() or boundary_root.is_symlink():
        raise CampaignError(f"{label} raw evidence directory is absent")
    boundary = load_json(boundary_root / "declared-boundary.json")
    facts = (
        gate.get("schema")
        == "maude.synthetic-operator.codex-retained-provider-boundary.v1",
        gate.get("provider_config") == "openai-sol",
        gate.get("status") == "complete",
        process.get("returncode") == 0,
        process.get("timed_out") is False,
        process.get("fresh_process") is True,
        process.get("follow_up_messages") == 0,
        process.get("coaching") == "none",
        gate.get("provider_auth_retained_until_transport_exit") is True,
        gate.get("provider_auth_values_recorded") is False,
        gate.get("provider_auth_output_scan_hits") == [],
        gate.get("provider_auth_destroyed") is True,
        gate.get("provider_transport_cwd_is_neutral") is True,
        gate.get("provider_task_paths_mounted") == [],
        gate.get("intrinsic_action_features_disabled")
        == CODEX_DISABLED_INTRINSIC_ACTION_FEATURES,
        gate.get("optional_features_disabled") == CODEX_DISABLED_OPTIONAL_FEATURES,
        gate.get("codex_approval_argv") == CODEX_APPROVAL_CONFIG_ARGV,
        gate.get("codex_approval_config_override") == CODEX_APPROVAL_CONFIG,
        gate.get("codex_approval_policy") == CODEX_APPROVAL_POLICY,
        gate.get("noninteractive_approval_safety_basis")
        == _codex_approval_safety_basis(tool=expected_tool),
        gate.get("codex_mcp_default_tools_approval_mode")
        == CODEX_MCP_DEFAULT_TOOLS_APPROVAL_MODE,
        gate.get("codex_mcp_approval_config_override") == expected_mcp_approval_config,
        gate.get("mcp_tool_approval_safety_basis")
        == _codex_mcp_tool_approval_safety_basis(tool=expected_tool),
        gate.get("unexpected_intrinsic_action_policy") == "fail-closed",
        gate.get("per_session_exact_tool_roster_supported") is True,
        gate.get("allowed_mcp_server") == expected_server,
        gate.get("allowed_mcp_tools") == [expected_tool],
        gate.get("mcp_protocol_version") == CODEX_MCP_PROTOCOL_VERSION,
        gate.get("exact_correlation_proved") is True,
        gate.get("proxy_tool_call_count") == expected_tool_actions,
        gate.get("broker_command_count") == expected_tool_actions,
        gate.get("provider_returncode") == 0,
        gate.get("provider_timed_out") is False,
        gate.get("provider_processes_remaining") == [],
        isinstance(boundary, dict),
    )
    if not all(facts):
        raise CampaignError(f"{label} lifecycle or exact-tool facts are incomplete")
    assert isinstance(boundary, dict)
    broker = boundary.get("command_broker")
    pty_broker = boundary.get("pty_broker")
    socket_contract = boundary.get("unix_socket_contract")
    command_socket_host = (
        socket_contract.get("command_socket_host")
        if isinstance(socket_contract, dict)
        else None
    )
    pty_socket_host = (
        socket_contract.get("pty_socket_host")
        if isinstance(socket_contract, dict)
        else None
    )
    if (
        boundary.get("schema")
        != "maude.synthetic-operator.codex-strict-mcp-boundary.v1"
        or boundary.get("provider_config") != "openai-sol"
        or boundary.get("mode") != "operator"
        or boundary.get("mcp_protocol_version") != CODEX_MCP_PROTOCOL_VERSION
        or boundary.get("mcp_server") != expected_server
        or boundary.get("allowed_tools") != CLAUDE_OPERATOR_TOOLS
        or boundary.get("built_in_tools") != []
        or boundary.get("mcp_config_sha256") != gate.get("mcp_config_sha256")
        or boundary.get("bridge_sha256") != CLAUDE_BRIDGE_SHA256
        or boundary.get("codex_approval_argv") != CODEX_APPROVAL_CONFIG_ARGV
        or boundary.get("codex_approval_config_override") != CODEX_APPROVAL_CONFIG
        or boundary.get("codex_approval_policy") != CODEX_APPROVAL_POLICY
        or boundary.get("noninteractive_approval_safety_basis")
        != _codex_approval_safety_basis(tool=expected_tool)
        or boundary.get("codex_mcp_default_tools_approval_mode")
        != CODEX_MCP_DEFAULT_TOOLS_APPROVAL_MODE
        or boundary.get("codex_mcp_approval_config_override")
        != expected_mcp_approval_config
        or boundary.get("mcp_tool_approval_safety_basis")
        != _codex_mcp_tool_approval_safety_basis(tool=expected_tool)
        or boundary.get("provider_transport_outside_task_sandbox") is not True
        or boundary.get("provider_auth_mounted_in_proxy_or_command") is not True
        or boundary.get("provider_auth_visible_to_trusted_stdio_shim") is not True
        or boundary.get("trusted_stdio_shim_reads_provider_auth") is not False
        or boundary.get("provider_auth_mounted_in_command") is not False
        or boundary.get("host_source_mounted_in_proxy_or_command") is not False
        or boundary.get("external_network_available_to_proxy_or_command") is not True
        or boundary.get("external_network_available_to_command") is not False
        or boundary.get("proxy_bwrap_argv") != []
        or not isinstance(socket_contract, dict)
        or socket_contract.get("path_budget_bytes") != 100
        or not isinstance(socket_contract.get("private_arena_root"), str)
        or not socket_contract["private_arena_root"].startswith("/tmp/maude-sock-")
        or not isinstance(command_socket_host, str)
        or socket_contract.get("command_socket_host_bytes")
        != len(command_socket_host.encode())
        or len(command_socket_host.encode()) > 100
        or not command_socket_host.startswith(
            socket_contract["private_arena_root"] + "/"
        )
        or socket_contract.get("command_socket_proxy")
        != "/run/maude-eval-broker/broker.sock"
        or (
            expect_pty_broker
            and (
                not isinstance(pty_socket_host, str)
                or socket_contract.get("pty_socket_host_bytes")
                != len(pty_socket_host.encode())
                or len(pty_socket_host.encode()) > 100
                or not pty_socket_host.startswith(
                    socket_contract["private_arena_root"] + "/"
                )
                or socket_contract.get("pty_socket_client")
                != "/run/operator-pty/broker.sock"
                or socket_contract.get("pty_socket_server")
                != "/run/operator-pty-private/broker.sock"
            )
        )
        or (
            not expect_pty_broker
            and any(
                key in socket_contract
                for key in (
                    "pty_socket_client",
                    "pty_socket_host",
                    "pty_socket_host_bytes",
                    "pty_socket_server",
                )
            )
        )
        or not isinstance(broker, dict)
        or broker.get("provider_credentials_received") is not False
        or broker.get("semantic_prompt_received") is not False
        or broker.get("per_command_bubblewrap") is not True
        or (isinstance(pty_broker, dict) is not expect_pty_broker)
    ):
        raise CampaignError(f"{label} declaration differs")

    identity = gate.get("identity")
    if (
        not isinstance(identity, dict)
        or not isinstance(identity.get("event_number"), int)
        or not isinstance(identity.get("provider_thread_id"), str)
        or not identity["provider_thread_id"]
    ):
        raise CampaignError(f"{label} provider identity proof differs")
    actions = gate.get("tool_actions")
    correlations = gate.get("normalized_result_correlations")
    if (
        not isinstance(actions, list)
        or len(actions) != expected_tool_actions
        or not isinstance(correlations, list)
        or len(correlations) != expected_tool_actions
    ):
        raise CampaignError(f"{label} action/correlation count differs")

    declared = load_json(boundary_root / "declared-boundary.json")
    if declared != boundary:
        raise CampaignError(f"{label} copied declaration differs")
    ready = load_json(boundary_root / "proxy-ready.json")
    proxy_trace = _load_jsonl_records(
        boundary_root / "proxy-trace.jsonl", label=f"{label} proxy trace"
    )
    initialize = [
        value
        for value in proxy_trace
        if value.get("protocol_event") == "initialize-response-flushed"
    ]
    initialized = [
        value
        for value in proxy_trace
        if value.get("protocol_event") == "notifications/initialized"
    ]
    tools_list = [
        value
        for value in proxy_trace
        if value.get("protocol_event") == "tools-list-response-flushed"
    ]
    proxy_calls = [value for value in proxy_trace if "tool" in value]
    if (
        ready.get("schema") != "maude.synthetic-operator.claude-mcp-ready.v1"
        or ready.get("protocol_version_requested") != CODEX_MCP_PROTOCOL_VERSION
        or ready.get("protocol_version_negotiated") != CODEX_MCP_PROTOCOL_VERSION
        or ready.get("tools") != [expected_tool]
        or len(initialize) != 1
        or len(initialized) != 1
        or len(tools_list) != 1
        or len(proxy_calls) != expected_tool_actions
        or initialize[0].get("initialize_accepted") is not True
        or initialize[0].get("protocol_version_requested") != CODEX_MCP_PROTOCOL_VERSION
        or initialize[0].get("protocol_version_negotiated")
        != CODEX_MCP_PROTOCOL_VERSION
        or initialized[0].get("protocol_version") != CODEX_MCP_PROTOCOL_VERSION
        or tools_list[0].get("protocol_version") != CODEX_MCP_PROTOCOL_VERSION
        or ready.get("initialize_message_ordinal")
        != initialize[0].get("message_ordinal")
        or ready.get("tools_list_message_ordinal")
        != tools_list[0].get("message_ordinal")
        or ready.get("tools_list_response_sha256")
        != tools_list[0].get("response_sha256")
    ):
        raise CampaignError(f"{label} MCP readiness or negotiation differs")

    recomputed: list[dict[str, Any]] = []
    action_ids: set[str] = set()
    for ordinal, (action, proxy_call) in enumerate(
        zip(actions, proxy_calls, strict=True), 1
    ):
        if not isinstance(action, dict) or not isinstance(proxy_call, dict):
            raise CampaignError(f"{label} action {ordinal} is malformed")
        expected_action_keys = {
            "action_id",
            "event_numbers",
            "server",
            "tool",
            "arguments",
            "arguments_sha256",
            "status",
            "result",
            "error",
            "completed",
        }
        action_id = action.get("action_id")
        event_numbers = action.get("event_numbers")
        arguments = action.get("arguments")
        if (
            set(action) != expected_action_keys
            or not isinstance(action_id, str)
            or not action_id
            or action_id in action_ids
            or not isinstance(event_numbers, list)
            or len(event_numbers) != 2
            or not all(
                type(event_number) is int and event_number > 0
                for event_number in event_numbers
            )
            or event_numbers != sorted(set(event_numbers))
            or not isinstance(arguments, dict)
            or set(arguments) not in ({"command"}, {"command", "timeout_seconds"})
            or not isinstance(arguments.get("command"), str)
            or not arguments["command"]
            or (
                "timeout_seconds" in arguments
                and type(arguments["timeout_seconds"]) is not int
            )
            or (
                "timeout_seconds" in arguments
                and arguments["timeout_seconds"] != CODEX_PROBE_TERMINAL_TIMEOUT_SECONDS
            )
            or action.get("status") != "completed"
            or action.get("error") is not None
        ):
            raise CampaignError(
                f"{label} action {ordinal} identity or arguments differ"
            )
        action_ids.add(action_id)
        result_text = _codex_normalized_mcp_result_text(action.get("result"))
        result_digest = hashlib.sha256(result_text.encode("utf-8")).hexdigest()
        if (
            action.get("server") != expected_server
            or action.get("tool") != expected_tool
            or action.get("tool") != proxy_call.get("tool")
            or action.get("arguments_sha256")
            != _canonical_json_sha256(action.get("arguments"))
            or action.get("arguments_sha256") != proxy_call.get("arguments_sha256")
            or proxy_call.get("arguments_sha256")
            != _canonical_json_sha256(proxy_call.get("arguments"))
            or action.get("completed") is not True
            or proxy_call.get("result_text") != result_text
            or proxy_call.get("result_text_sha256") != result_digest
            or type(proxy_call.get("is_error")) is not bool
        ):
            raise CampaignError(f"{label} action {ordinal} differs")
        recomputed.append(
            {
                "action_id": action.get("action_id"),
                "tool": action.get("tool"),
                "arguments_sha256": action.get("arguments_sha256"),
                "provider_normalized_result_text_sha256": result_digest,
                "proxy_result_text_sha256": result_digest,
                "proxy_is_error": proxy_call.get("is_error"),
            }
        )
    if correlations != recomputed:
        raise CampaignError(f"{label} normalized result correlations differ")

    broker_trace = _load_jsonl_records(
        boundary_root / "command-broker-trace.jsonl",
        label=f"{label} command-broker trace",
    )
    if len(broker_trace) != expected_tool_actions:
        raise CampaignError(f"{label} broker command count differs")
    for ordinal, (proxy_call, broker_call) in enumerate(
        zip(proxy_calls, broker_trace, strict=True), 1
    ):
        broker_result = broker_call.get("result")
        if (
            broker_call.get("schema")
            != "maude.synthetic-operator.command-broker-event.v1"
            or broker_call.get("ordinal") != ordinal
            or broker_call.get("request_id") != proxy_call.get("correlation_id")
            or broker_call.get("result_sha256") != _canonical_json_sha256(broker_result)
            or proxy_call.get("result_text_sha256")
            != _canonical_json_sha256(broker_result)
            or not isinstance(broker_result, dict)
            or broker_result.get("returncode") != 0
            or broker_result.get("timed_out") is not False
            or broker_result.get("stdout_truncated") is not False
            or broker_result.get("stderr_truncated") is not False
        ):
            raise CampaignError(f"{label} broker correlation {ordinal} differs")
        _validate_command_namespace_proof(
            broker_call.get("namespace_and_mount_proof"),
            provider=provider,
            ordinal=ordinal,
        )

    isolation = load_json(provider_root / "isolation.json")
    policy_validation = isolation.get("command_broker_policy_validation")
    if (
        isolation.get("schema")
        != "maude.synthetic-operator.codex-mcp-isolation-result.v1"
        or isolation.get("source_root_absent") is not True
        or isolation.get("provider_auth_present_only_for_transport_and_trusted_shim")
        is not True
        or isolation.get("provider_task_paths_mounted") != []
        or isolation.get("intrinsic_action_features_disabled")
        != CODEX_DISABLED_INTRINSIC_ACTION_FEATURES
        or isolation.get("unexpected_intrinsic_action_policy") != "fail-closed"
        or isolation.get("mcp_server") != expected_server
        or isolation.get("mcp_protocol_version") != CODEX_MCP_PROTOCOL_VERSION
        or isolation.get("mcp_enabled_tools") != [expected_tool]
        or isolation.get("mcp_config_sha256") != gate.get("mcp_config_sha256")
        or not isinstance(policy_validation, dict)
        or policy_validation.get("schema")
        != "maude.synthetic-operator.command-broker-policy.v1"
        or policy_validation.get("external_network") is not False
        or policy_validation.get("per_command_pid_namespace") is not True
        or policy_validation.get("provider_auth_received") is not False
        or policy_validation.get("semantic_prompt_received") is not False
    ):
        raise CampaignError(f"{label} isolation preflight differs")

    cleanup = load_json(boundary_root / "cleanup.json")
    command_cleanup = cleanup.get("command_broker")
    socket_cleanup = cleanup.get("private_socket_arena")
    if (
        cleanup.get("schema") != "maude.synthetic-operator.codex-boundary-cleanup.v1"
        or cleanup.get("provider_auth_destroyed") is not True
        or cleanup.get("provider_processes_remaining") != []
        or cleanup.get("cleanup_errors") != []
        or not isinstance(command_cleanup, dict)
        or command_cleanup.get("exit_code") != 0
        or command_cleanup.get("graceful_exit_requested") is not False
        or command_cleanup.get("forced_after_graceful_timeout") is not False
        or command_cleanup.get("remaining_processes") != []
        or not isinstance(command_cleanup.get("observed_processes"), list)
        or not command_cleanup["observed_processes"]
        or not isinstance(socket_cleanup, dict)
        or socket_cleanup.get("path_budget_bytes") != 100
        or socket_cleanup.get("all_removed") is not True
        or not isinstance(socket_cleanup.get("root"), str)
        or not socket_cleanup["root"].startswith("/tmp/maude-sock-")
        or not isinstance(socket_cleanup.get("directories"), list)
        or not socket_cleanup["directories"]
        or any(
            not isinstance(record, dict)
            or record.get("removed") is not True
            or record.get("remaining_entries") != []
            for record in socket_cleanup.get("directories", [])
        )
        or gate.get("broker_cleanup")
        != {
            key: value
            for key, value in cleanup.items()
            if key
            not in {
                "schema",
                "provider_auth_destroyed",
                "provider_processes_remaining",
                "cleanup_errors",
            }
        }
    ):
        raise CampaignError(f"{label} cleanup differs")
    boundary_record = gate.get("boundary_evidence")
    cleanup_path = _exact_external_probe_record(
        boundary_record, base=provider_root, label=f"{label} cleanup record"
    )
    if cleanup_path != boundary_root / "cleanup.json":
        raise CampaignError(f"{label} cleanup record points elsewhere")

    if expect_pty_broker:
        pty_cleanup = load_json(boundary_root / "pty-broker-cleanup.json")
        pty_invocation = load_json(boundary_root / "pty-broker-invocation.json")
        pty_ready = load_json(boundary_root / "pty-broker-ready.json")
        managed = cleanup.get("pty_broker")
        request = (
            managed.get("graceful_shutdown_request")
            if isinstance(managed, dict)
            else None
        )
        cleanup_record = (
            managed.get("cleanup_report") if isinstance(managed, dict) else None
        )
        invocation_argv = pty_invocation.get("argv")
        shutdown_pairs = (
            [
                invocation_argv[index : index + 2]
                for index, value in enumerate(invocation_argv[:-1])
                if value == "--shutdown-request"
            ]
            if isinstance(invocation_argv, list)
            else []
        )
        copied_cleanup_path = boundary_root / "pty-broker-cleanup.json"
        if (
            pty_ready.get("schema") != "maude.synthetic-operator.pty-broker-ready.v1"
            or pty_ready.get("operations")
            != ["start", "read", "send", "stop", "status"]
            or pty_cleanup.get("schema")
            != "maude.synthetic-operator.pty-broker-cleanup.v1"
            or pty_cleanup.get("handled_requests") != expected_tool_actions
            or pty_cleanup.get("all_tracked_ptys_stopped") is not True
            or pty_cleanup.get("shutdown_mode") != "request-file"
            or pty_cleanup.get("shutdown_signal") is not None
            or pty_cleanup.get("shutdown_request") != request
            or pty_cleanup.get("shutdown_request_removed") is not True
            or pty_cleanup.get("socket_removed") is not True
            or any(
                not isinstance(value, dict) or value.get("remaining") is not False
                for value in pty_cleanup.get("tracked_ptys", [])
            )
            or cleanup.get("pty_cleanup") != pty_cleanup
            or not isinstance(managed, dict)
            or managed.get("exit_code") != 0
            or managed.get("graceful_exit_requested") is not True
            or managed.get("forced_after_graceful_timeout") is not False
            or managed.get("remaining_processes") != []
            or managed.get("socket_removed") is not True
            or managed.get("shutdown_control_boundary")
            != {
                "path_visibility": "shared-persistent-pty-namespace",
                "created_after_provider_absent_or_exited": True,
                "contains_authority_or_secret": False,
                "request_fields": ["request_id", "requested_at", "schema"],
                "tamper_or_preexistence_policy": ("fail-closed-then-force-stop"),
            }
            or not isinstance(managed.get("observed_processes"), list)
            or not managed["observed_processes"]
            or not isinstance(request, dict)
            or set(request) != {"schema", "request_id", "requested_at"}
            or request.get("schema")
            != "maude.synthetic-operator.pty-broker-shutdown-request.v1"
            or not isinstance(request.get("request_id"), str)
            or not request["request_id"]
            or not isinstance(request.get("requested_at"), str)
            or not request["requested_at"]
            or not isinstance(cleanup_record, dict)
            or cleanup_record.get("bytes") != copied_cleanup_path.stat().st_size
            or cleanup_record.get("sha256") != sha256_file(copied_cleanup_path)
            or pty_invocation.get("provider_auth_mounted") is not False
            or pty_invocation.get("host_source_mounted") is not False
            or pty_invocation.get("external_network") is not False
            or not isinstance(invocation_argv, list)
            or "--unshare-net" not in invocation_argv
            or shutdown_pairs
            != [
                [
                    "--shutdown-request",
                    "/run/operator-pty/shutdown-request.json",
                ]
            ]
        ):
            raise CampaignError(f"{label} persistent PTY cleanup differs")
    elif (
        cleanup.get("pty_broker") is not None or cleanup.get("pty_cleanup") is not None
    ):
        raise CampaignError(f"{label} unexpectedly contains a PTY broker")


def _validate_command_namespace_proof(
    proof: Any, *, provider: str, ordinal: int
) -> None:
    label = f"{provider}: command {ordinal} namespace proof"
    if not isinstance(proof, dict):
        raise CampaignError(f"{label} is malformed")
    namespaces = proof.get("namespaces")
    if (
        not isinstance(namespaces, dict)
        or set(namespaces) != {"mnt", "net", "pid"}
        or any(
            not isinstance(value, dict)
            or value.get("distinct") is not True
            or not isinstance(value.get("broker"), str)
            or not isinstance(value.get("sandbox"), str)
            or value["broker"] == value["sandbox"]
            for value in namespaces.values()
        )
        or proof.get("forbidden_paths_visible") != []
        or proof.get("provider_auth_mount_visible") is not False
        or proof.get("pre_exec_forbidden_descriptor_targets") != []
        or proof.get("external_network_namespace") != "unshared"
        or not _is_sha256(proof.get("mountinfo_sha256"))
    ):
        raise CampaignError(f"{label} lacks mount/network/PID separation")
    inside_fds = proof.get("inside_pre_exec_file_descriptors")
    if (
        not isinstance(inside_fds, list)
        or [value.get("fd") for value in inside_fds] != [0, 1, 2]
        or any(not isinstance(value.get("target"), str) for value in inside_fds)
    ):
        raise CampaignError(f"{label} lacks the exact inside FD 0/1/2 proof")
    host_fds = proof.get("pre_exec_file_descriptors")
    if (
        not isinstance(host_fds, list)
        or not {0, 1, 2}
        <= {value.get("fd") for value in host_fds if isinstance(value, dict)}
        or any(
            not isinstance(value, dict)
            or not isinstance(value.get("fd"), int)
            or not isinstance(value.get("target"), str)
            for value in host_fds
        )
    ):
        raise CampaignError(f"{label} lacks the host FD setup proof")
    environment_names = proof.get("inside_environment_names")
    if (
        not isinstance(environment_names, list)
        or environment_names != sorted(set(environment_names))
        or "PWD" not in environment_names
        or any(
            name.startswith(("CLAUDE_", "ANTHROPIC_", "CODEX_"))
            for name in environment_names
        )
    ):
        raise CampaignError(f"{label} has an unsafe command environment")
    contract = proof.get("command_fd_contract")
    if (
        not isinstance(contract, str)
        or "close_fds=True" not in contract
        or "os.closerange(3,1048576)" not in contract
        or "stdin is replaced with /dev/null" not in contract
    ):
        raise CampaignError(f"{label} lacks the declared descriptor contract")


def _validate_claude_boundary(
    *,
    provider: str,
    process: dict[str, Any],
    gate: dict[str, Any],
    provider_root: Path,
    expected_tool_actions: int,
    expect_pty_broker: bool,
) -> None:
    label = f"{provider}: Claude MCP boundary"
    boundary = process.get("claude_mcp_boundary")
    expected_bridge = sha256_file(CLAUDE_MCP_BRIDGE)
    if expected_bridge != CLAUDE_BRIDGE_SHA256:
        raise CampaignError(
            "current claude_mcp_bridge.py bytes differ from the audited boundary"
        )
    common_facts = (
        process.get("returncode") == 0,
        process.get("timed_out") is False,
        process.get("fresh_process") is True,
        process.get("follow_up_messages") == 0,
        process.get("coaching") == "none",
        isinstance(boundary, dict),
        gate.get("schema") == "maude.synthetic-operator.claude-provider-boundary.v1",
        gate.get("provider_config") == "anthropic-sonnet",
        gate.get("status") == "complete",
        gate.get("provider_transport_outside_task_sandbox") is True,
        gate.get("provider_auth_retained_until_transport_exit") is True,
        gate.get("provider_auth_mounted_in_mcp_or_command") is False,
        gate.get("host_source_mounted_in_mcp_or_command") is False,
        gate.get("allowed_tools") == CLAUDE_OPERATOR_TOOLS,
        gate.get("built_in_tools_allowed") == [],
        gate.get("mcp_protocol_version") == CLAUDE_MCP_PROTOCOL_VERSION,
        _is_sha256(gate.get("mcp_config_sha256")),
        isinstance(gate.get("provider_auth_files"), list),
        bool(gate.get("provider_auth_files")),
        gate.get("provider_auth_values_recorded") is False,
        gate.get("prompt_sent_after_tools_list_flush") is True,
        _is_sha256(gate.get("prompt_event_sha256")),
        gate.get("provider_auth_destroyed") is True,
        gate.get("provider_returncode") == 0,
        gate.get("provider_timed_out") is False,
        gate.get("exact_correlation_proved") is True,
        gate.get("proxy_tool_call_count") == expected_tool_actions,
        gate.get("broker_command_count") == expected_tool_actions,
    )
    if not all(common_facts):
        raise CampaignError(f"{label} lifecycle facts are incomplete")
    assert isinstance(boundary, dict)
    broker = boundary.get("command_broker")
    pty_broker = boundary.get("pty_broker")
    proxy_argv = boundary.get("proxy_bwrap_argv")
    if (
        boundary.get("schema") != "maude.synthetic-operator.claude-mcp-boundary.v1"
        or boundary.get("mode") != "operator"
        or boundary.get("bridge_sha256") != expected_bridge
        or boundary.get("mcp_protocol_version") != CLAUDE_MCP_PROTOCOL_VERSION
        or boundary.get("mcp_server") != "operator"
        or boundary.get("allowed_tools") != CLAUDE_OPERATOR_TOOLS
        or boundary.get("built_in_tools") != []
        or boundary.get("mcp_config_sha256") != gate.get("mcp_config_sha256")
        or boundary.get("provider_transport_outside_task_sandbox") is not True
        or boundary.get("provider_auth_mounted_in_proxy_or_command") is not False
        or boundary.get("host_source_mounted_in_proxy_or_command") is not False
        or boundary.get("external_network_available_to_proxy_or_command") is not False
        or not isinstance(proxy_argv, list)
        or not {"--unshare-pid", "--unshare-net", "--clearenv"} <= set(proxy_argv)
        or any(str(HOST_SOURCE_ROOT) in value for value in proxy_argv)
        or any("/run/provider-auth" in value for value in proxy_argv)
        or not isinstance(broker, dict)
        or broker.get("provider_credentials_received") is not False
        or broker.get("semantic_prompt_received") is not False
        or broker.get("per_command_bubblewrap") is not True
        or (isinstance(pty_broker, dict) is not expect_pty_broker)
    ):
        raise CampaignError(f"{label} declaration differs")
    identity = gate.get("identity")
    if (
        not isinstance(identity, dict)
        or not isinstance(identity.get("event_number"), int)
        or not isinstance(identity.get("provider_session_id"), str)
        or not identity["provider_session_id"]
        or not isinstance(identity.get("provider_reported_model"), str)
        or not identity["provider_reported_model"]
        or identity.get("provider_reported_tools") != CLAUDE_OPERATOR_TOOLS
        or identity.get("auth_files_present_at_identity") is not True
    ):
        raise CampaignError(f"{label} provider identity proof differs")
    actions = gate.get("tool_actions")
    results = gate.get("tool_results")
    runtime_proofs = gate.get("proxy_runtime_proofs")
    if (
        not isinstance(actions, list)
        or len(actions) != expected_tool_actions
        or not isinstance(results, list)
        or len(results) != expected_tool_actions
        or not isinstance(runtime_proofs, list)
        or len(runtime_proofs) != expected_tool_actions
    ):
        raise CampaignError(f"{label} action/result proof count differs")
    result_by_id = {
        value.get("tool_use_id"): value for value in results if isinstance(value, dict)
    }
    if len(result_by_id) != expected_tool_actions:
        raise CampaignError(f"{label} result identities are not unique")
    prior_action_event = 0
    prior_result_event = 0
    for ordinal, action in enumerate(actions, 1):
        if (
            not isinstance(action, dict)
            or action.get("tool") != CLAUDE_OPERATOR_TOOLS[0]
            or not isinstance(action.get("event_number"), int)
            or action["event_number"] <= prior_action_event
            or not isinstance(action.get("tool_use_id"), str)
            or not isinstance(action.get("arguments"), dict)
            or set(action["arguments"]) - {"command", "timeout_seconds"}
            or not isinstance(action["arguments"].get("command"), str)
            or not action["arguments"]["command"].strip()
            or (
                "timeout_seconds" in action["arguments"]
                and (
                    not isinstance(action["arguments"]["timeout_seconds"], int)
                    or isinstance(action["arguments"]["timeout_seconds"], bool)
                    or not 1 <= action["arguments"]["timeout_seconds"] <= 600
                )
            )
            or action.get("arguments_sha256")
            != _canonical_json_sha256(action["arguments"])
        ):
            raise CampaignError(f"{label} action {ordinal} differs")
        result = result_by_id.get(action["tool_use_id"])
        if (
            not isinstance(result, dict)
            or not isinstance(result.get("event_number"), int)
            or result["event_number"] <= action["event_number"]
            or result["event_number"] <= prior_result_event
            or result.get("is_error") is not False
            or not isinstance(result.get("result_text"), str)
            or result.get("result_text_sha256")
            != hashlib.sha256(result["result_text"].encode("utf-8")).hexdigest()
        ):
            raise CampaignError(f"{label} result {ordinal} differs")
        prior_action_event = action["event_number"]
        prior_result_event = result["event_number"]
        runtime_proof = runtime_proofs[ordinal - 1]
        proxy_processes = (
            runtime_proof.get("proxy_processes")
            if isinstance(runtime_proof, dict)
            else None
        )
        monitor_proofs = (
            runtime_proof.get("outer_bubblewrap_monitor_proofs")
            if isinstance(runtime_proof, dict)
            else None
        )
        if (
            not isinstance(runtime_proof, dict)
            or runtime_proof.get("allowed_tools") != CLAUDE_OPERATOR_TOOLS
            or not isinstance(proxy_processes, list)
            or len(proxy_processes) != 1
            or not isinstance(monitor_proofs, list)
            or not monitor_proofs
            or any(
                not isinstance(value, dict)
                or value.get("retained_provider_auth_descriptors") != []
                for value in monitor_proofs
            )
        ):
            raise CampaignError(f"{label} live proxy proof {ordinal} differs")
        proxy = proxy_processes[0]
        if (
            proxy.get("network_namespace_distinct") is not True
            or proxy.get("provider_auth_visible") is not False
            or proxy.get("host_source_visible") is not False
            or proxy.get("provider_private_home_visible") is not False
            or proxy.get("forbidden_environment_names") != []
            or proxy.get("retained_provider_auth_descriptors") != []
        ):
            raise CampaignError(f"{label} live proxy isolation {ordinal} differs")

    boundary_root = provider_root / "claude-mcp-boundary"
    if not boundary_root.is_dir() or boundary_root.is_symlink():
        raise CampaignError(f"{label} raw evidence directory is absent")
    isolation = load_json(provider_root / "isolation.json")
    policy_validation = isolation.get("command_broker_policy_validation")
    if (
        isolation.get("schema")
        != "maude.synthetic-operator.claude-mcp-isolation-result.v1"
        or isolation.get("source_root_absent") is not True
        or isolation.get("provider_auth_mount_absent") is not True
        or isolation.get("provider_transport_inside_task_namespace") is not False
        or isolation.get("proxy_external_network_absent") is not True
        or isolation.get("proxy_environment_missing_entries") != []
        or isolation.get("proxy_environment_secret_or_task_entries") != []
        or isolation.get("bare_tool_roster") != ["terminal"]
        or isolation.get("provider_reported_tool_roster_required")
        != CLAUDE_OPERATOR_TOOLS
        or isolation.get("built_in_tools_allowed") != []
        or isolation.get("mcp_protocol_version") != CLAUDE_MCP_PROTOCOL_VERSION
        or isolation.get("bridge_sha256") != expected_bridge
        or not isinstance(policy_validation, dict)
        or policy_validation.get("schema")
        != "maude.synthetic-operator.command-broker-policy.v1"
        or policy_validation.get("external_network") is not False
        or policy_validation.get("per_command_pid_namespace") is not True
        or policy_validation.get("provider_auth_received") is not False
        or policy_validation.get("semantic_prompt_received") is not False
    ):
        raise CampaignError(f"{label} isolation preflight differs")
    declared_path = boundary_root / "declared-boundary.json"
    if load_json(declared_path) != boundary:
        raise CampaignError(f"{label} copied declaration differs")
    copied_policy = boundary_root / "command-policy.json"
    _record_bytes_match_copy(
        broker.get("policy"), copied_policy, label=f"{label} broker policy"
    )
    policy = load_json(copied_policy)
    forbidden = policy.get("forbidden_prefixes")
    provider_forbidden = (
        [
            value
            for value in forbidden
            if isinstance(value, str) and "private-provider-home" in value
        ]
        if isinstance(forbidden, list)
        else []
    )
    serialized_policy = json.dumps(policy, sort_keys=True)
    if (
        policy.get("schema") != "maude.synthetic-operator.command-broker-policy.v1"
        or policy.get("bwrap") != "/usr/bin/bwrap"
        or policy.get("home") != "/home/operator"
        or not isinstance(policy.get("cwd"), str)
        or not isinstance(policy.get("mounts"), list)
        or not isinstance(policy.get("sockets"), list)
        or not isinstance(policy.get("environment"), dict)
        or policy["environment"].get("HOME") != "/home/operator"
        or forbidden is None
        or str(HOST_SOURCE_ROOT) not in forbidden
        or "/run/provider-auth" not in forbidden
        or len(provider_forbidden) != 1
        or any(
            name.startswith(("CLAUDE_", "ANTHROPIC_", "CODEX_"))
            for name in policy["environment"]
        )
        or str(HOST_SOURCE_ROOT) in json.dumps(policy.get("mounts"))
        or "/run/provider-auth" in json.dumps(policy.get("mounts"))
        or "provider-auth" in json.dumps(policy.get("sockets"))
        or "credentials" in serialized_policy.casefold()
    ):
        raise CampaignError(f"{label} command policy differs")
    ready = load_json(boundary_root / "proxy-ready.json")
    if (
        ready.get("schema") != "maude.synthetic-operator.claude-mcp-ready.v1"
        or ready.get("mode") != "operator"
        or ready.get("tools") != ["terminal"]
        or ready.get("protocol_version_requested") != CLAUDE_MCP_PROTOCOL_VERSION
        or ready.get("protocol_version_negotiated") != CLAUDE_MCP_PROTOCOL_VERSION
        or not isinstance(ready.get("initialize_message_ordinal"), int)
        or not isinstance(ready.get("tools_list_message_ordinal"), int)
        or ready["initialize_message_ordinal"] < 1
        or ready["tools_list_message_ordinal"] <= ready["initialize_message_ordinal"]
        or not _is_sha256(ready.get("tools_list_response_sha256"))
        or not isinstance(ready.get("pid"), int)
        or ready["pid"] <= 0
    ):
        raise CampaignError(f"{label} MCP readiness differs")
    proxy_trace = _load_jsonl_records(
        boundary_root / "proxy-trace.jsonl", label=f"{label} proxy trace"
    )
    if len(proxy_trace) != 3 + expected_tool_actions:
        raise CampaignError(f"{label} proxy trace count differs")
    protocol_events = [
        "initialize-response-flushed",
        "notifications/initialized",
        "tools-list-response-flushed",
    ]
    for record, event in zip(proxy_trace[:3], protocol_events, strict=True):
        if (
            record.get("schema") != "maude.synthetic-operator.mcp-correlation-event.v1"
            or record.get("protocol_event") != event
            or not isinstance(record.get("message_ordinal"), int)
        ):
            raise CampaignError(f"{label} MCP protocol ordering differs")
    protocol_ordinals = [record["message_ordinal"] for record in proxy_trace[:3]]
    if (
        protocol_ordinals != sorted(set(protocol_ordinals))
        or proxy_trace[0].get("message_ordinal") != ready["initialize_message_ordinal"]
        or proxy_trace[2].get("message_ordinal") != ready["tools_list_message_ordinal"]
        or proxy_trace[0].get("protocol_version_requested")
        != CLAUDE_MCP_PROTOCOL_VERSION
        or proxy_trace[0].get("protocol_version_negotiated")
        != CLAUDE_MCP_PROTOCOL_VERSION
        or proxy_trace[1].get("protocol_version") != CLAUDE_MCP_PROTOCOL_VERSION
        or proxy_trace[2].get("protocol_version") != CLAUDE_MCP_PROTOCOL_VERSION
        or proxy_trace[2].get("tools") != ["terminal"]
        or proxy_trace[2].get("response_sha256") != ready["tools_list_response_sha256"]
    ):
        raise CampaignError(f"{label} MCP protocol facts differ")
    proxy_calls = proxy_trace[3:]
    for ordinal, (action, proxy_call) in enumerate(
        zip(actions, proxy_calls, strict=True), 1
    ):
        result = result_by_id[action["tool_use_id"]]
        if (
            proxy_call.get("schema")
            != "maude.synthetic-operator.mcp-correlation-event.v1"
            or proxy_call.get("ordinal") != ordinal
            or proxy_call.get("mode") != "operator"
            or proxy_call.get("tool") != "terminal"
            or proxy_call.get("arguments") != action["arguments"]
            or proxy_call.get("arguments_sha256") != action["arguments_sha256"]
            or proxy_call.get("result_text") != result["result_text"]
            or proxy_call.get("result_text_sha256") != result["result_text_sha256"]
            or proxy_call.get("is_error") is not False
            or not isinstance(proxy_call.get("correlation_id"), str)
            or not proxy_call["correlation_id"]
            or not isinstance(proxy_call.get("mcp_request_id"), (int, str))
        ):
            raise CampaignError(f"{label} MCP correlation {ordinal} differs")
    broker_ready = load_json(boundary_root / "command-broker-ready.json")
    if (
        broker_ready.get("schema") != "maude.synthetic-operator.command-broker-ready.v1"
        or broker_ready.get("policy_sha256") != sha256_file(copied_policy)
        or not _is_sha256(broker_ready.get("token_sha256"))
        or not isinstance(broker_ready.get("pid"), int)
        or broker_ready["pid"] <= 0
    ):
        raise CampaignError(f"{label} command-broker readiness differs")
    broker_trace = _load_jsonl_records(
        boundary_root / "command-broker-trace.jsonl",
        label=f"{label} command-broker trace",
    )
    if len(broker_trace) != expected_tool_actions:
        raise CampaignError(f"{label} command-broker trace count differs")
    for ordinal, (action, proxy_call, broker_call) in enumerate(
        zip(actions, proxy_calls, broker_trace, strict=True), 1
    ):
        command = action["arguments"].get("command")
        bwrap_argv = broker_call.get("bwrap_argv")
        broker_result = broker_call.get("result")
        if (
            broker_call.get("schema")
            != "maude.synthetic-operator.command-broker-event.v1"
            or broker_call.get("ordinal") != ordinal
            or broker_call.get("request_id") != proxy_call.get("correlation_id")
            or not isinstance(command, str)
            or broker_call.get("command") != command
            or broker_call.get("result_sha256") != _canonical_json_sha256(broker_result)
            or not _is_sha256(broker_call.get("request_sha256"))
            or not isinstance(broker_result, dict)
            or broker_result.get("returncode") != 0
            or broker_result.get("timed_out") is not False
            or broker_result.get("stdout_truncated") is not False
            or broker_result.get("stderr_truncated") is not False
            or proxy_call.get("result_text_sha256")
            != hashlib.sha256(
                json.dumps(
                    broker_result,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest()
            or not isinstance(bwrap_argv, list)
            or not {"--unshare-pid", "--unshare-net", "--clearenv"} <= set(bwrap_argv)
            or any(str(HOST_SOURCE_ROOT) in value for value in bwrap_argv)
            or any("/run/provider-auth" in value for value in bwrap_argv)
        ):
            raise CampaignError(f"{label} command correlation {ordinal} differs")
        _validate_command_namespace_proof(
            broker_call.get("namespace_and_mount_proof"),
            provider=provider,
            ordinal=ordinal,
        )
    cleanup = load_json(boundary_root / "cleanup.json")
    command_cleanup = cleanup.get("command_broker")
    if (
        cleanup.get("schema") != "maude.synthetic-operator.claude-boundary-cleanup.v1"
        or cleanup.get("provider_auth_destroyed") is not True
        or cleanup.get("provider_processes_remaining") != []
        or cleanup.get("cleanup_errors") != []
        or not isinstance(command_cleanup, dict)
        or command_cleanup.get("exit_code") != 0
        or command_cleanup.get("remaining_processes") != []
        or gate.get("broker_cleanup", {}).get("command_broker") != command_cleanup
    ):
        raise CampaignError(f"{label} cleanup differs")
    boundary_record = gate.get("boundary_evidence")
    cleanup_path = _exact_external_probe_record(
        boundary_record, base=provider_root, label=f"{label} cleanup record"
    )
    if cleanup_path != boundary_root / "cleanup.json":
        raise CampaignError(f"{label} cleanup record points elsewhere")
    if expect_pty_broker:
        assert isinstance(pty_broker, dict)
        invocation = load_json(boundary_root / "pty-broker-invocation.json")
        pty_argv = invocation.get("argv")
        pty_ready = load_json(boundary_root / "pty-broker-ready.json")
        pty_cleanup = load_json(boundary_root / "pty-broker-cleanup.json")
        managed_pty_cleanup = cleanup.get("pty_broker")
        if (
            not isinstance(pty_argv, list)
            or not {"--unshare-pid", "--unshare-net", "--clearenv"} <= set(pty_argv)
            or any(str(HOST_SOURCE_ROOT) in value for value in pty_argv)
            or any("/run/provider-auth" in value for value in pty_argv)
            or invocation.get("provider_auth_mounted") is not False
            or invocation.get("host_source_mounted") is not False
            or invocation.get("external_network") is not False
            or pty_ready.get("schema") != "maude.synthetic-operator.pty-broker-ready.v1"
            or pty_ready.get("operations")
            != ["start", "read", "send", "stop", "status"]
            or pty_cleanup.get("schema")
            != "maude.synthetic-operator.pty-broker-cleanup.v1"
            or pty_cleanup.get("handled_requests") != expected_tool_actions
            or pty_cleanup.get("all_tracked_ptys_stopped") is not True
            or pty_cleanup.get("socket_removed") is not True
            or any(
                not isinstance(value, dict) or value.get("remaining") is not False
                for value in pty_cleanup.get("tracked_ptys", [])
            )
            or cleanup.get("pty_cleanup") != pty_cleanup
            or gate.get("broker_cleanup", {}).get("pty_cleanup") != pty_cleanup
            or not isinstance(managed_pty_cleanup, dict)
            or managed_pty_cleanup.get("exit_code") != 0
            or managed_pty_cleanup.get("remaining_processes") != []
        ):
            raise CampaignError(f"{label} persistent PTY boundary differs")
    elif (
        cleanup.get("pty_broker") is not None or cleanup.get("pty_cleanup") is not None
    ):
        raise CampaignError(f"{label} unexpectedly contains a PTY broker")


def _claude_boundary_files(*, include_pty: bool) -> set[str]:
    result = {
        "claude-mcp-boundary/cleanup.json",
        "claude-mcp-boundary/command-broker-ready.json",
        "claude-mcp-boundary/command-broker-trace.jsonl",
        "claude-mcp-boundary/command-broker.stderr",
        "claude-mcp-boundary/command-broker.stdout",
        "claude-mcp-boundary/command-policy.json",
        "claude-mcp-boundary/declared-boundary.json",
        "claude-mcp-boundary/proxy-ready.json",
        "claude-mcp-boundary/proxy-trace.jsonl",
    }
    if include_pty:
        result.update(
            {
                "claude-mcp-boundary/pty-broker-cleanup.json",
                "claude-mcp-boundary/pty-broker-invocation.json",
                "claude-mcp-boundary/pty-broker-ready.json",
                "claude-mcp-boundary/pty-broker.stderr",
                "claude-mcp-boundary/pty-broker.stdout",
            }
        )
    return result


def _codex_boundary_files(*, include_pty: bool) -> set[str]:
    result = {
        "codex-mcp-boundary/cleanup.json",
        "codex-mcp-boundary/command-broker-ready.json",
        "codex-mcp-boundary/command-broker-trace.jsonl",
        "codex-mcp-boundary/command-broker.stderr",
        "codex-mcp-boundary/command-broker.stdout",
        "codex-mcp-boundary/command-policy.json",
        "codex-mcp-boundary/declared-boundary.json",
        "codex-mcp-boundary/proxy-ready.json",
        "codex-mcp-boundary/proxy-trace.jsonl",
    }
    if include_pty:
        result.update(
            {
                "codex-mcp-boundary/pty-broker-cleanup.json",
                "codex-mcp-boundary/pty-broker-invocation.json",
                "codex-mcp-boundary/pty-broker-ready.json",
                "codex-mcp-boundary/pty-broker.stderr",
                "codex-mcp-boundary/pty-broker.stdout",
            }
        )
    return result


def _installation_surface_probe_summary(
    provider_probe_summary: dict[str, Any],
) -> dict[str, Any]:
    observation = _validate_operator_capability_index(
        index_path=INSTALL_SURFACE_PROBE_PATH,
        expected_schema=("maude.synthetic-operator.installation-surface-probes.v3"),
        label="installation-surface probe",
    )
    index = observation["index"]
    probe_root = INSTALL_SURFACE_PROBE_PATH.parent
    expected_runner = observation["expected_runner"]
    expected_adapter = file_record(OPERATOR_PTY)
    if expected_adapter["sha256"] != OPERATOR_PTY_SHA256:
        raise CampaignError(
            "current operator_pty.py bytes differ from the audited boundary"
        )
    expected_provenance = file_record(INSTALL_MEDIA_PROVENANCE)
    if index.get("installation_media_provenance") != expected_provenance:
        raise CampaignError(
            "installation-surface probes do not bind current media provenance"
        )
    provenance = load_json(INSTALL_MEDIA_PROVENANCE)
    maude_wheels = [
        record
        for record in provenance.get("wheels", [])
        if isinstance(record, dict)
        and isinstance(record.get("distribution"), dict)
        and str(record["distribution"].get("name")).casefold() == "maude"
    ]
    if len(maude_wheels) != 1:
        raise CampaignError("frozen installation media has no unique Maude wheel")
    maude_wheel = maude_wheels[0]
    expected_wheel = {
        key: maude_wheel[key] for key in ("path", "bytes", "sha256", "distribution")
    }
    if (
        index.get("maude_wheel") != expected_wheel
        or maude_wheel.get("source_commit") != SUT_COMMIT
        or maude_wheel.get("editable") is not False
        or maude_wheel.get("double_build_byte_reproducible") is not True
        or maude_wheel["distribution"].get("version") != "2.4.0"
    ):
        raise CampaignError("installation-surface Maude wheel binding is wrong")
    wheel_relative = Path(str(maude_wheel["path"]))
    if wheel_relative.is_absolute() or any(
        part in {"", ".", ".."} for part in wheel_relative.parts
    ):
        raise CampaignError("installation-surface Maude wheel path is unsafe")
    wheel_path = REPO_ROOT / wheel_relative
    if (
        not wheel_path.is_file()
        or wheel_path.is_symlink()
        or wheel_path.stat().st_size != maude_wheel["bytes"]
        or sha256_file(wheel_path) != maude_wheel["sha256"]
    ):
        raise CampaignError("installation-surface Maude wheel bytes differ")
    contract = index.get("stateful_pty_contract")
    if contract != {
        "exact_operation_sequence_proved": [
            "start",
            "read",
            "send-tab-focus",
            "send-status-command",
            "read",
            "stop",
            "read",
            "status",
        ],
        "one_child_across_separate_provider_tool_actions": True,
        ("separate_read_focus_send_command_send_read_stop_read_order_proved"): True,
        "typed_status_rpc_sequence_proved": True,
        "predeclared_command_sequence": True,
        "claim_scope": (
            "Proves cross-call PTY persistence and application handling of the "
            "predeclared status command after explicit input focus; it does not "
            "claim the probe model chose an unplanned input."
        ),
        "exact_pty_bytes_preserved": True,
    }:
        raise CampaignError("installation-surface stateful PTY contract is wrong")
    attempt_id = index["attempt_id"]
    attempt_root = observation["attempt_root"]
    auth_identities = set(
        provider_probe_summary.get("all_observed_session_identities", [])
    )
    if len(auth_identities) != len(
        provider_probe_summary.get("all_observed_session_identities", [])
    ):
        raise CampaignError("provider auth-probe identities are incomplete")
    if auth_identities & observation["session_identities"]:
        raise CampaignError("installation probe reused an auth-probe session identity")
    providers = list(observation["available"].values())

    identities: set[str] = set()
    sanitized: list[dict[str, Any]] = []
    for item in sorted(
        providers,
        key=lambda value: list(SUPPORTED_PROVIDER_CONFIGS).index(
            value["provider_config"]
        ),
    ):
        provider = item["provider_config"]
        provider_root = attempt_root / provider
        if not provider_root.is_dir() or provider_root.is_symlink():
            raise CampaignError(f"{provider}: raw probe directory is unsafe")
        identity = item.get("session_identity")
        process = item.get("process")
        safety = item.get("safety_audit")
        delivery = item.get("delivery")
        if not all(
            isinstance(value, dict) for value in (identity, process, safety, delivery)
        ):
            raise CampaignError(f"{provider}: installation probe is malformed")
        identity_value = _probe_identity(identity)
        config = PROVIDER_MODEL_CONFIGS[provider]
        expected_model = config["model_argument"]
        if (
            identity.get("configured_model") != expected_model
            or identity_value in identities
            or identity_value in auth_identities
        ):
            raise CampaignError(f"{provider}: installation probe session is not fresh")
        identities.add(identity_value)
        expected_delivery_provider = config["provider"]
        if (
            delivery.get("provider") != expected_delivery_provider
            or delivery.get("requested_model") != expected_model
        ):
            raise CampaignError(
                f"{provider}: installation probe model delivery differs"
            )
        gate = process.get("provider_auth_gate")
        if not isinstance(gate, dict):
            raise CampaignError(f"{provider}: installation probe gate is absent")
        if provider == "openai-sol":
            if (
                not _is_sha256(delivery.get("delivered_prompt_sha256"))
                or delivery.get("allowed_unix_sockets") != []
                or delivery.get("intrinsic_action_features_explicitly_disabled")
                != CODEX_DISABLED_INTRINSIC_ACTION_FEATURES
                or delivery.get("optional_features_explicitly_disabled")
                != CODEX_DISABLED_OPTIONAL_FEATURES
                or delivery.get("live_web_search_enabled") is not False
                or delivery.get("provider_task_paths_added") != []
                or delivery.get("user_mcp_and_connector_config_loaded") is not False
                or delivery.get("mcp_server") != "operator"
                or delivery.get("mcp_protocol_version") != CODEX_MCP_PROTOCOL_VERSION
                or delivery.get("mcp_config_sha256") != gate.get("mcp_config_sha256")
                or delivery.get("mcp_enabled_tools") != CODEX_OPERATOR_TOOLS
                or delivery.get("codex_approval_argv") != CODEX_APPROVAL_CONFIG_ARGV
                or delivery.get("codex_approval_config_override")
                != CODEX_APPROVAL_CONFIG
                or delivery.get("codex_approval_policy") != CODEX_APPROVAL_POLICY
                or delivery.get("noninteractive_approval_safety_basis")
                != _codex_approval_safety_basis(tool="terminal")
                or delivery.get("codex_mcp_default_tools_approval_mode")
                != CODEX_MCP_DEFAULT_TOOLS_APPROVAL_MODE
                or delivery.get("codex_mcp_approval_config_override")
                != ('mcp_servers.operator.default_tools_approval_mode="approve"')
                or delivery.get("mcp_tool_approval_safety_basis")
                != _codex_mcp_tool_approval_safety_basis(tool="terminal")
                or delivery.get("exact_provider_tool_allowlist_supported") is not True
                or delivery.get("unexpected_intrinsic_action_policy") != "fail-closed"
            ):
                raise CampaignError(f"{provider}: installation Codex delivery differs")
            _validate_codex_provider_boundary(
                provider=provider,
                process=process,
                gate=gate,
                provider_root=provider_root,
                expected_tool_actions=8,
                expect_pty_broker=True,
            )
            boundary_identity = gate.get("identity", {}).get("provider_thread_id")
            boundary_kind = (
                "task-blind-retained-auth-codex-transport-with-exact-"
                "stdio-mcp-per-command-sandbox-and-pty-broker"
            )
        else:
            if (
                not isinstance(delivery.get("requested_session_id"), str)
                or not delivery["requested_session_id"]
                or delivery.get("system_prompt_delivery") != "system"
                or delivery.get("user_prompt_delivery")
                != (
                    "single stream-json user event after flushed MCP "
                    "tools/list readiness; stdin then closed"
                )
                or not _is_sha256(delivery.get("user_prompt_sha256"))
                or delivery.get("mcp_protocol_version") != CLAUDE_MCP_PROTOCOL_VERSION
                or delivery.get("mcp_config_sha256") != gate.get("mcp_config_sha256")
                or delivery.get("allowed_tools") != CLAUDE_OPERATOR_TOOLS
                or delivery.get("built_in_tools") != []
                or delivery.get("provider_task_paths_added") != []
                or delivery.get("provider_unix_sockets_added") != []
            ):
                raise CampaignError(f"{provider}: installation Claude delivery differs")
            _validate_claude_boundary(
                provider=provider,
                process=process,
                gate=gate,
                provider_root=provider_root,
                expected_tool_actions=8,
                expect_pty_broker=True,
            )
            boundary_identity = gate.get("identity", {}).get("provider_session_id")
            boundary_kind = (
                "task-blind-retained-auth-claude-transport-with-"
                "credential-free-mcp-proxy-per-command-sandbox-and-"
                "pty-broker"
            )
        if boundary_identity != identity_value:
            raise CampaignError(f"{provider}: installation boundary identity differs")
        gate_path = _exact_external_probe_record(
            item.get("gate_record"),
            base=probe_root,
            label=f"{provider} gate",
        )
        if (
            gate_path != provider_root / "auth-gate.json"
            or load_json(gate_path) != gate
        ):
            raise CampaignError(f"{provider}: raw auth-gate record differs")
        safety_lists = (
            safety.get("auth_read_attempts"),
            safety.get("environment_read_attempts"),
            safety.get("network_command_attempts"),
            safety.get("host_source_read_attempts"),
        )
        if (
            any(value != [] for value in safety_lists)
            or safety.get("zero_auth_env_network_source_attempts") is not True
        ):
            raise CampaignError(f"{provider}: installation probe has a safety attempt")
        expected_values = {
            "status": "available",
            "campaign_run": False,
            "fresh_process": True,
            "exact_terminal_commands_match_positionally": True,
            "read_before_input_proved": True,
            "tab_focus_send_proved": True,
            "status_command_send_proved": True,
            "read_after_input_proved": True,
            "read_after_status_input_proved": True,
            "read_after_stop_proved": True,
            "all_read_results_nonempty": True,
            "read_focus_send_command_send_read_stop_read_order_proved": True,
            "same_pty_process_across_provider_tool_actions": True,
            "real_governor_hello_request_response": True,
            "real_sessions_list_request_response": True,
            "real_sessions_create_request_response": True,
            "real_governor_now_request_response": True,
            "real_governor_status_request_response": True,
            "command_linked_runtime_session_list_request_response": True,
            "typed_status_rpc_sequence_in_order": True,
            "installed_distribution_mounted": True,
            "installed_python_module_source_readable": True,
            "host_repository_checkout_mounted": False,
            "release_source_archive_mounted": False,
            "installation_media_mounted": False,
            "expected_answer_or_task_supplied": False,
            "task_level_network_or_external_operational_effect": False,
            "final_marker_present": True,
        }
        differing = [
            key
            for key, expected in expected_values.items()
            if type(item.get(key)) is not type(expected) or item.get(key) != expected
        ]
        if differing:
            raise CampaignError(
                f"{provider}: installation probe facts differ: {differing!r}"
            )
        if (
            item.get("authority_effect") != "none"
            or item.get("tool_actions_after_gate") != 8
            or item.get("stateful_pty_actions") != 8
            or item.get("pty_command_returncode") != 0
        ):
            raise CampaignError(f"{provider}: installation PTY action result differs")
        command_digests = item.get("exact_pty_command_sha256")
        output_digests = item.get("successful_action_output_sha256")
        gate_actions = gate.get("tool_actions")
        gate_results = gate.get("tool_results")
        if (
            not isinstance(command_digests, list)
            or len(command_digests) != 8
            or not all(_is_sha256(value) for value in command_digests)
            or not isinstance(output_digests, list)
            or len(output_digests) != 8
            or not all(_is_sha256(value) for value in output_digests)
            or not isinstance(gate_actions, list)
            or len(gate_actions) != 8
            or (
                provider == "anthropic-sonnet"
                and (not isinstance(gate_results, list) or len(gate_results) != 8)
            )
        ):
            raise CampaignError(f"{provider}: installation PTY action digests differ")
        completed = item.get("completed_action_events")
        successful = item.get("successful_completed_action_events")
        if (
            not isinstance(completed, list)
            or len(completed) != 8
            or completed != successful
            or not all(
                isinstance(value, dict)
                and value.get("succeeded") is True
                and isinstance(value.get("event_number"), int)
                for value in completed
            )
            or [value["event_number"] for value in completed]
            != sorted({value["event_number"] for value in completed})
        ):
            raise CampaignError(f"{provider}: completed installation actions differ")
        if provider == "openai-sol":
            expected_completed_actions = [
                {
                    "event_number": action["event_numbers"][-1],
                    "provider": "codex",
                    "action_id": action["action_id"],
                    "tool": "mcp__operator__terminal",
                    "completion_kind": "item.completed",
                    "status": "completed",
                    "exit_code": None,
                    "succeeded": True,
                }
                for action in gate_actions
            ]
        else:
            assert isinstance(gate_results, list)
            completed_result_by_id = {
                result.get("tool_use_id"): result
                for result in gate_results
                if isinstance(result, dict)
            }
            if len(completed_result_by_id) != 8:
                raise CampaignError(
                    f"{provider}: completed installation result identities differ"
                )
            expected_completed_actions = [
                {
                    "event_number": completed_result_by_id[action["tool_use_id"]][
                        "event_number"
                    ],
                    "provider": "claude",
                    "action_id": action["tool_use_id"],
                    "tool": "mcp__operator__terminal",
                    "completion_kind": "tool_result",
                    "is_error": False,
                    "succeeded": True,
                }
                for action in gate_actions
            ]
        if completed != expected_completed_actions:
            raise CampaignError(
                f"{provider}: completed installation action identity differs"
            )
        process_pairs = item.get("process_identity_pairs")
        pty_state = item.get("pty_state")
        if (
            not isinstance(process_pairs, list)
            or len(process_pairs) != 1
            or not isinstance(process_pairs[0], dict)
            or not isinstance(pty_state, dict)
            or pty_state.get("schema") != "maude.synthetic-operator.stateful-pty.v1"
            or pty_state.get("status") != "completed"
            or pty_state.get("exit_code") != 0
            or process_pairs[0].get("daemon_pid") != pty_state.get("daemon_pid")
            or process_pairs[0].get("child_pid") != pty_state.get("child_pid")
            or not isinstance(pty_state.get("daemon_pid"), int)
            or not isinstance(pty_state.get("child_pid"), int)
            or pty_state["daemon_pid"] <= 0
            or pty_state["child_pid"] <= 0
            or pty_state["daemon_pid"] == pty_state["child_pid"]
        ):
            raise CampaignError(f"{provider}: persistent PTY process identity differs")
        entrypoint = item.get("entrypoint")
        if (
            not isinstance(entrypoint, dict)
            or entrypoint.get("version") != "2.4.0"
            or entrypoint.get("module_inside_venv") is not True
            or not _is_sha256(entrypoint.get("sha256"))
            or not isinstance(entrypoint.get("path"), str)
            or not entrypoint["path"].startswith(
                f"{LAB_ROOT}/_install-surface-{provider}-"
            )
            or not entrypoint["path"].endswith("/installation/venv/bin/maude")
            or pty_state.get("command") != [entrypoint["path"]]
        ):
            raise CampaignError(
                f"{provider}: installed Maude entrypoint evidence differs"
            )
        expected_cwd = Path(entrypoint["path"]).parents[2] / "work"
        payload_kinds = (
            "state",
            "read",
            "ack",
            "ack",
            "read",
            "ack",
            "read",
            "state",
        )
        parsed_broker_results: list[dict[str, Any]] = []
        action_commands: list[str] = []
        action_outputs: list[str] = []
        claude_result_by_id = (
            {
                result.get("tool_use_id"): result
                for result in gate_results
                if isinstance(result, dict)
            }
            if isinstance(gate_results, list)
            else {}
        )
        expected_terminal_action_records: list[dict[str, Any]] = []
        for ordinal, (action, payload_kind) in enumerate(
            zip(gate_actions, payload_kinds, strict=True), 1
        ):
            arguments = action.get("arguments") if isinstance(action, dict) else None
            command = arguments.get("command") if isinstance(arguments, dict) else None
            if not isinstance(command, str) or not command:
                raise CampaignError(
                    f"{provider}: installation command {ordinal} is absent"
                )
            if provider == "openai-sol":
                output = _codex_normalized_mcp_result_text(action.get("result"))
                expected_terminal_action_records.append(
                    {
                        "position": ordinal,
                        "provider": "codex",
                        "action_reference": (f"codex:{action['action_id']}"),
                        "event_numbers": action["event_numbers"],
                        "command_sha256": command_digests[ordinal - 1],
                        "argument_keys": sorted(action["arguments"]),
                        "explicit_timeout_seconds": action["arguments"].get(
                            "timeout_seconds"
                        ),
                        "same_command_in_started_and_completed": True,
                    }
                )
            else:
                result = claude_result_by_id.get(action.get("tool_use_id"))
                if not isinstance(result, dict) or not isinstance(
                    result.get("result_text"), str
                ):
                    raise CampaignError(
                        f"{provider}: installation result {ordinal} is absent"
                    )
                output = result["result_text"]
                expected_terminal_action_records.append(
                    {
                        "position": ordinal,
                        "provider": "claude",
                        "action_reference": (f"claude:{action['tool_use_id']}"),
                        "event_numbers": [action["event_number"]],
                        "command_sha256": command_digests[ordinal - 1],
                        "argument_keys": sorted(action["arguments"]),
                        "explicit_timeout_seconds": action["arguments"].get(
                            "timeout_seconds"
                        ),
                        "same_command_in_started_and_completed": None,
                    }
                )
            parsed_broker_results.append(
                _parse_installation_broker_result(
                    output,
                    expected_command=command,
                    expected_cwd=expected_cwd,
                    payload_kind=payload_kind,
                )
            )
            action_commands.append(command)
            action_outputs.append(output)
        if command_digests != [
            hashlib.sha256(command.encode("utf-8")).hexdigest()
            for command in action_commands
        ] or output_digests != [
            hashlib.sha256(output.encode("utf-8")).hexdigest()
            for output in action_outputs
        ]:
            raise CampaignError(
                f"{provider}: nested broker evidence differs from action digests"
            )
        terminal_action_records = item.get("terminal_action_records")
        if terminal_action_records != expected_terminal_action_records:
            raise CampaignError(
                f"{provider}: positional terminal action evidence differs"
            )
        parsed_payloads = [record["payload"] for record in parsed_broker_results]
        state_payloads = [
            parsed_payloads[0],
            parsed_payloads[2]["state"],
            parsed_payloads[3]["state"],
            parsed_payloads[5]["state"],
            parsed_payloads[7],
        ]
        if (
            {(value["daemon_pid"], value["child_pid"]) for value in state_payloads}
            != {
                (
                    process_pairs[0]["daemon_pid"],
                    process_pairs[0]["child_pid"],
                )
            }
            or parsed_payloads[2].get("operation") != "send"
            or parsed_payloads[3].get("operation") != "send"
            or parsed_payloads[5].get("operation") != "stop"
            or parsed_payloads[7] != pty_state
        ):
            raise CampaignError(f"{provider}: nested PTY payload sequence differs")
        adapter_record = item.get("pty_adapter")
        expected_provider_adapter = {
            **expected_adapter,
            "path": "installation/work/operator-pty",
            "media_type": "text/plain",
        }
        if adapter_record != expected_provider_adapter:
            raise CampaignError(f"{provider}: PTY adapter does not match current bytes")
        typescript_path = _exact_external_probe_record(
            item.get("pty_typescript"),
            base=probe_root,
            label=f"{provider} PTY transcript",
        )
        if (
            typescript_path.stat().st_size <= 0
            or pty_state.get("captured_bytes") != typescript_path.stat().st_size
            or pty_state.get("output") is None
            or not str(pty_state["output"]).endswith(
                "/installation/work/pty.typescript"
            )
        ):
            raise CampaignError(f"{provider}: exact PTY transcript evidence differs")
        state_root = provider_root / "pty-state"
        state_records = item.get("pty_state_artifacts")
        if (
            not state_root.is_dir()
            or state_root.is_symlink()
            or not isinstance(state_records, list)
            or inventory_files(state_root) != state_records
        ):
            raise CampaignError(f"{provider}: PTY state artifact inventory differs")
        for record in state_records:
            _exact_external_probe_record(
                record,
                base=state_root,
                label=f"{provider} PTY state",
            )
        state_paths = {record["path"] for record in state_records}
        required_state_paths = {
            "read-offset",
            "ready.json",
            "requests.jsonl",
            "state.json",
        }
        ack_paths = sorted(
            path
            for path in state_paths
            if path.startswith("acks/") and path.endswith(".json")
        )
        if (
            not required_state_paths <= state_paths
            or len(ack_paths) != 3
            or state_paths != required_state_paths | set(ack_paths)
            or load_json(state_root / "state.json") != pty_state
        ):
            raise CampaignError(f"{provider}: PTY state artifact set differs")
        ready = load_json(state_root / "ready.json")
        if (
            ready.get("schema") != "maude.synthetic-operator.stateful-pty-ready.v1"
            or ready.get("daemon_pid") != pty_state["daemon_pid"]
            or ready.get("child_pid") != pty_state["child_pid"]
        ):
            raise CampaignError(f"{provider}: PTY ready record differs")
        request_lines = [
            json.loads(line)
            for line in (state_root / "requests.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line
        ]
        if (
            len(request_lines) != 3
            or [value.get("kind") for value in request_lines]
            != ["send", "send", "stop"]
            or [value.get("inputs_base64") for value in request_lines]
            != [["CQ=="], ["c3RhdHVzDQ=="], ["EQ=="]]
            or [value.get("grace_seconds") for value in request_lines]
            != [0.0, 0.0, 5.0]
        ):
            raise CampaignError(f"{provider}: PTY request sequence differs")
        acknowledgements = [load_json(state_root / path) for path in ack_paths]
        if (
            {value.get("request_id") for value in acknowledgements}
            != {value.get("id") for value in request_lines}
            or any(
                value.get("schema") != "maude.synthetic-operator.stateful-pty-ack.v1"
                or value.get("accepted") is not True
                or value.get("error") is not None
                for value in acknowledgements
            )
            or int((state_root / "read-offset").read_text(encoding="ascii").strip())
            != typescript_path.stat().st_size
        ):
            raise CampaignError(f"{provider}: PTY request acknowledgement differs")
        runtime_pairs = item.get("runtime_trace_pairs")
        status_attribution = (
            "Maude polls governor.now. In this isolated probe, the separately "
            "focused literal status input is the only trigger for "
            "governor.status followed by runtime.session.list; their ordered "
            "successful responses prove application handling beyond PTY byte "
            "acknowledgement."
        )
        expected_trace_predicates = {
            "runtime_trace_nonempty": True,
            "all_runtime_trace_responses_are_results": True,
            "startup_rpc_sequence_exact_prefix": True,
            "startup_governor_hello_observed": True,
            "startup_chat_sessions_list_observed": True,
            "empty_startup_chat_session_create_observed": True,
            "scheduled_governor_now_poll_observed": True,
            "typed_status_governor_status_observed": True,
            "typed_status_runtime_session_list_observed": True,
            "typed_status_rpc_sequence_in_order": True,
        }
        methods = (
            [pair.get("method") for pair in runtime_pairs]
            if isinstance(runtime_pairs, list)
            else []
        )
        status_method_index = (
            methods.index("governor.status") if "governor.status" in methods else -1
        )
        runtime_list_method_index = (
            methods.index("runtime.session.list", status_method_index + 1)
            if status_method_index >= 0
            and "runtime.session.list" in methods[status_method_index + 1 :]
            else -1
        )
        if (
            not runtime_pairs
            or methods[:3] != ["governor.hello", "sessions.list", "sessions.create"]
            or "governor.now" not in methods
            or item.get("runtime_trace_contract_predicates")
            != expected_trace_predicates
            or item.get("governor_status_attribution") != status_attribution
            or status_method_index < 0
            or runtime_list_method_index <= status_method_index
            or any(
                not isinstance(pair, dict)
                or pair.get("response_kind") != "result"
                or not _is_sha256(pair.get("request_body_sha256"))
                or not _is_sha256(pair.get("response_body_sha256"))
                or not _is_sha256(pair.get("result_or_error_sha256"))
                for pair in runtime_pairs
            )
        ):
            raise CampaignError(
                f"{provider}: Governor/command RPC trace evidence differs"
            )
        _exact_external_probe_record(
            item.get("rpc_transcript"),
            base=probe_root,
            label=f"{provider} RPC transcript",
        )
        before_path = _exact_external_probe_record(
            item.get("clean_home_before"),
            base=probe_root,
            label=f"{provider} clean HOME before",
        )
        after_path = _exact_external_probe_record(
            item.get("clean_home_after"),
            base=probe_root,
            label=f"{provider} clean HOME after",
        )
        clean_before = load_json(before_path)
        clean_after = load_json(after_path)
        required_home_dirs = {
            ".cache",
            ".config",
            ".local",
            ".local/share",
            ".local/state",
            "tmp",
        }
        if (
            clean_before != clean_after
            or clean_before.get("schema")
            != "maude.synthetic-operator.clean-home-inventory.v1"
            or clean_before.get("mount_path") != "/home/operator"
            or clean_before.get("files") != []
            or clean_before.get("symlinks") != []
            or set(clean_before.get("directories", [])) != required_home_dirs
        ):
            raise CampaignError(f"{provider}: clean operator HOME evidence differs")
        _exact_external_probe_record(
            item.get("raw_transcript"),
            base=probe_root,
            label=f"{provider} raw transcript",
        )
        _exact_external_probe_record(
            item.get("raw_stderr"),
            base=probe_root,
            label=f"{provider} raw stderr",
        )
        result_path = provider_root / "result.json"
        if (
            not result_path.is_file()
            or result_path.is_symlink()
            or load_json(result_path) != item
        ):
            raise CampaignError(f"{provider}: raw result record differs")
        isolation_path = provider_root / "isolation.json"
        system_prompt_path = provider_root / "system-prompt.md"
        user_prompt_path = provider_root / "user-prompt.md"
        if not all(
            path.is_file() and not path.is_symlink()
            for path in (
                isolation_path,
                system_prompt_path,
                user_prompt_path,
            )
        ):
            raise CampaignError(
                f"{provider}: raw probe input/isolation record is absent"
            )
        isolation = load_json(isolation_path)
        if provider == "openai-sol":
            if (
                isolation.get("schema")
                != "maude.synthetic-operator.codex-mcp-isolation-result.v1"
                or isolation.get("source_root_absent") is not True
                or isolation.get(
                    "provider_auth_present_only_for_transport_and_trusted_shim"
                )
                is not True
                or isolation.get("provider_task_paths_mounted") != []
                or isolation.get("intrinsic_action_features_disabled")
                != CODEX_DISABLED_INTRINSIC_ACTION_FEATURES
                or isolation.get("unexpected_intrinsic_action_policy") != "fail-closed"
                or isolation.get("mcp_server") != "operator"
                or isolation.get("mcp_protocol_version") != CODEX_MCP_PROTOCOL_VERSION
                or isolation.get("mcp_enabled_tools") != CODEX_OPERATOR_TOOLS
                or isolation.get("mcp_config_sha256") != gate.get("mcp_config_sha256")
            ):
                raise CampaignError(
                    f"{provider}: Codex clean-room isolation evidence differs"
                )
        elif (
            isolation.get("schema")
            != "maude.synthetic-operator.claude-mcp-isolation-result.v1"
            or isolation.get("source_root_absent") is not True
            or isolation.get("provider_auth_mount_absent") is not True
            or isolation.get("provider_transport_inside_task_namespace") is not False
            or isolation.get("proxy_external_network_absent") is not True
            or isolation.get("bare_tool_roster") != ["terminal"]
            or isolation.get("provider_reported_tool_roster_required")
            != CLAUDE_OPERATOR_TOOLS
            or isolation.get("built_in_tools_allowed") != []
            or isolation.get("mcp_protocol_version") != CLAUDE_MCP_PROTOCOL_VERSION
        ):
            raise CampaignError(
                f"{provider}: Claude clean-room isolation evidence differs"
            )
        expected_files = {
            "auth-gate.json",
            "clean-home-after.json",
            "clean-home-before.json",
            "isolation.json",
            "provider.stderr",
            "pty.typescript",
            "result.json",
            "rpc-transcript.jsonl",
            "system-prompt.md",
            "transcript.jsonl",
            "user-prompt.md",
            *{f"pty-state/{path}" for path in state_paths},
        }
        expected_files |= (
            _codex_boundary_files(include_pty=True)
            if provider == "openai-sol"
            else _claude_boundary_files(include_pty=True)
        )
        actual_files = {
            path.relative_to(provider_root).as_posix()
            for path in provider_root.rglob("*")
            if path.is_file() and not path.is_symlink()
        }
        symlinks = [path for path in provider_root.rglob("*") if path.is_symlink()]
        if actual_files != expected_files or symlinks:
            raise CampaignError(f"{provider}: raw probe file set differs")
        sanitized.append(
            {
                "provider_config": provider,
                "session_identity": identity,
                "delivery": delivery,
                "returncode": 0,
                "timed_out": False,
                "fresh_process": True,
                "stateful_pty_actions": 8,
                "persistent_child_identity": process_pairs[0],
                "exact_installed_entrypoint": entrypoint,
                "installed_distribution_mounted": True,
                "installed_python_module_source_readable": True,
                "host_checkout_release_source_and_media_absent": True,
                "startup_scheduled_and_typed_status_rpc_contract_proved": True,
                "runtime_trace_contract_predicates": (expected_trace_predicates),
                "governor_status_attribution": status_attribution,
                "clean_home_before_and_after": True,
                "provider_boundary_kind": boundary_kind,
                "provider_auth_retained_until_transport_exit": True,
                "trusted_stdio_shim_auth_read_observed": False,
                "strict_mcp_per_command_and_pty_sandboxes_proved": True,
                "zero_safety_attempts": True,
                "raw_result": {
                    key: file_record(result_path, relative_to=probe_root)[key]
                    for key in ("bytes", "sha256")
                },
                "raw_transcript": {
                    key: item["raw_transcript"][key] for key in ("bytes", "sha256")
                },
                "raw_stderr": {
                    key: item["raw_stderr"][key] for key in ("bytes", "sha256")
                },
                "pty_transcript": {
                    key: item["pty_typescript"][key] for key in ("bytes", "sha256")
                },
                "rpc_transcript": {
                    key: item["rpc_transcript"][key] for key in ("bytes", "sha256")
                },
                "isolation_record": {
                    key: file_record(isolation_path, relative_to=probe_root)[key]
                    for key in ("bytes", "sha256")
                },
                "system_prompt": {
                    key: file_record(system_prompt_path, relative_to=probe_root)[key]
                    for key in ("bytes", "sha256")
                },
                "user_prompt": {
                    key: file_record(user_prompt_path, relative_to=probe_root)[key]
                    for key in ("bytes", "sha256")
                },
                "authority_effect": "none",
            }
        )
    if len(identities) != len(providers):
        raise CampaignError("installation-surface probes reused a session identity")
    return {
        "schema": ("maude.synthetic-operator.installation-surface-probe-summary.v1"),
        "attempt_id": attempt_id,
        "completed_at": index.get("completed_at"),
        "probe_index": {
            "bytes": INSTALL_SURFACE_PROBE_PATH.stat().st_size,
            "sha256": sha256_file(INSTALL_SURFACE_PROBE_PATH),
        },
        "campaign_runner": expected_runner,
        "mcp_stdio_shim": file_record(CLAUDE_MCP_BRIDGE),
        "operator_pty": expected_adapter,
        "installation_media_provenance": expected_provenance,
        "maude_wheel": expected_wheel,
        "stateful_pty_contract": contract,
        "providers": sanitized,
        "successful_provider_configs": observation["successful_provider_configs"],
        "unavailable_provider_configs": observation["unavailable_provider_configs"],
        "all_observed_session_identities": sorted(observation["session_identities"]),
        "unavailable_provider_failures": {
            provider: {
                "failure_stage": failure["failure_stage"],
                "failure_classification": failure["failure_classification"],
                "provider_process_launch_state": failure[
                    "provider_process_launch_state"
                ],
                "provider_session_identity_observed": failure[
                    "provider_session_identity_observed"
                ],
                "provider_network_attempted": failure["provider_network_attempted"],
                "provider_network_use_observed": failure[
                    "provider_network_use_observed"
                ],
            }
            for provider, failure in sorted(observation["unavailable"].items())
        },
        "session_identities_distinct_from_auth_probes": True,
        "raw_probe_evidence_verified_in_tmp": True,
        "raw_probe_evidence_committed": False,
        "installed_distribution_exception": (
            "The exact installed Python distribution is mounted and its module "
            "source is readable; no host checkout, release-source archive, or "
            "installation media is mounted."
        ),
        "capability_observation_valid": True,
        "all_passed": index["all_passed"],
        "authority_effect": "none",
    }


def _auth_gate_selftest_summary() -> dict[str, Any]:
    script = HARNESS_DIR / "auth_gate_selftest.py"
    completed = subprocess.run(
        ["python3", "-B", str(script)],
        cwd=HARNESS_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if completed.returncode != 0 or not lines:
        raise CampaignError(
            "provider auth-gate fake-process self-test failed: "
            f"{completed.stderr.strip()}"
        )
    result_path = Path(lines[-1])
    try:
        result_path.relative_to(Path("/tmp"))
    except ValueError as exc:
        raise CampaignError(
            "provider auth-gate self-test result was not isolated under /tmp"
        ) from exc
    result = load_json(result_path)
    checks = result.get("checks")
    if (
        result.get("all_passed") is not True
        or result.get("authority_effect") != "none"
        or not isinstance(checks, list)
        or not checks
        or not all(
            isinstance(item, dict) and item.get("passed") is True for item in checks
        )
    ):
        raise CampaignError("provider auth-gate fake-process self-test did not pass")
    return {
        "schema": "maude.synthetic-operator.auth-gate-selftest-summary.v1",
        "source": file_record(script),
        "campaign_runner": file_record(HARNESS_DIR / "campaign_runner.py"),
        "result": {
            "bytes": result_path.stat().st_size,
            "sha256": sha256_file(result_path),
        },
        "checks": [{"name": item.get("name"), "passed": True} for item in checks],
        "raw_result_committed": False,
        "all_passed": True,
        "authority_effect": "none",
    }


def _provider_assignment_selftest_summary() -> dict[str, Any]:
    completed = subprocess.run(
        ["python3", "-B", str(PROVIDER_ASSIGNMENT_SELFTEST)],
        cwd=HARNESS_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    try:
        result = json.loads(completed.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CampaignError(
            "provider assignment self-test did not emit exact JSON"
        ) from exc
    if (
        completed.returncode != 0
        or not isinstance(result, dict)
        or result.get("schema")
        != ("maude.synthetic-operator.provider-assignment-selftest-result.v1")
        or result.get("campaign_id") != CAMPAIGN_ID
        or not isinstance(result.get("checks_passed"), int)
        or isinstance(result.get("checks_passed"), bool)
        or result["checks_passed"] < 11
        or result.get("provider_sessions_started") != 0
        or result.get("task_network_used") is not False
        or result.get("authority_effect") != "none"
        or result.get("valid") is not True
    ):
        raise CampaignError(
            "provider assignment provider-free self-test failed: "
            f"{completed.stderr.strip()}"
        )
    return {
        "schema": ("maude.synthetic-operator.provider-assignment-selftest-summary.v1"),
        "finalizer": file_record(FINALIZE_PROVIDER_ASSIGNMENTS),
        "selftest": file_record(PROVIDER_ASSIGNMENT_SELFTEST),
        "result": result,
        "provider_sessions_started": 0,
        "task_network_used": False,
        "all_passed": True,
        "authority_effect": "none",
    }


def _write_preflight(*, frozen_at: str) -> None:
    initial_observation = _initial_repository_observation()
    git_head = _command_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT)
    git_branch = _command_output(["git", "branch", "--show-current"], cwd=REPO_ROOT)
    git_upstream = _command_output(
        ["git", "rev-parse", "--abbrev-ref", "@{upstream}"], cwd=REPO_ROOT
    )
    upstream_head = _command_output(["git", "rev-parse", "@{upstream}"], cwd=REPO_ROOT)
    origin = _command_output(["git", "remote", "get-url", "origin"], cwd=REPO_ROOT)
    for label, result in (
        ("HEAD", git_head),
        ("branch", git_branch),
        ("upstream", git_upstream),
        ("upstream HEAD", upstream_head),
        ("origin", origin),
    ):
        if result["returncode"] != 0:
            raise CampaignError(
                f"cannot observe repository {label}: {result['stderr'].strip()}"
            )
    source_archive = PACKET_DIR / "direct-runtime" / "source-9050a53.tar"
    tar_commit_process = subprocess.run(
        ["git", "get-tar-commit-id"],
        input=source_archive.read_bytes(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    tar_commit = tar_commit_process.stdout.decode("utf-8", errors="replace").strip()
    if tar_commit_process.returncode != 0 or tar_commit != DOCKET_COMMIT:
        raise CampaignError(
            f"frozen Docket source archive commit ID mismatch: {tar_commit!r}"
        )
    versions = {
        "python": platform.python_version(),
        "maude": "2.4.0",
        "codex": _command_output(["codex", "--version"]),
        "claude": _command_output(["claude", "--version"]),
        "frozen_docket": _command_output(
            [str(PACKET_DIR / "direct-runtime" / "bin" / "docket"), "--version"]
        ),
        "synthetic_runtime_schema": "maude.synthetic-runtime.v1",
    }
    provider_probes = _provider_probe_summary()
    installation_surface_probes = _installation_surface_probe_summary(provider_probes)
    grader_surface_probes = _grader_surface_probe_summary()
    auth_gate_selftest = _auth_gate_selftest_summary()
    assignment_selftest = _provider_assignment_selftest_summary()
    finalization_errors = finalize_provider_assignments.validate_finalized_matrix()
    if finalization_errors:
        raise CampaignError(
            "provider assignment finalization is not exact: "
            + "; ".join(finalization_errors)
        )
    matrix = load_matrix()
    capability_assignment = _validate_capability_assignment(
        matrix=matrix,
        auth_successes=set(provider_probes["successful_provider_configs"]),
        installation_successes=set(
            installation_surface_probes["successful_provider_configs"]
        ),
        ordinary_grader_successes=set(
            grader_surface_probes["successful_provider_configs_by_probe"]["ordinary"]
        ),
        installation_grader_successes=set(
            grader_surface_probes["successful_provider_configs_by_probe"][
                "installation"
            ]
        ),
    )
    auth_identities = set(provider_probes["all_observed_session_identities"])
    installation_identities = set(
        installation_surface_probes["all_observed_session_identities"]
    )
    grader_identities = set(grader_surface_probes["all_observed_session_identities"])
    if (
        auth_identities & installation_identities
        or auth_identities & grader_identities
        or installation_identities & grader_identities
    ):
        raise CampaignError(
            "capability probes reused an identity across auth, installation, "
            "or grader surfaces"
        )
    provider_boundary_summaries = {
        value["provider_config"]: {
            "provider_boundary_kind": value["provider_boundary_kind"],
            "operator_tools": PROVIDER_MODEL_CONFIGS[value["provider_config"]][
                "operator_tools"
            ],
            "grader_tools": PROVIDER_MODEL_CONFIGS[value["provider_config"]][
                "grader_tools"
            ],
            "built_in_tools": PROVIDER_MODEL_CONFIGS[value["provider_config"]][
                "built_in_tools"
            ],
            "mcp_protocol_version": PROVIDER_MODEL_CONFIGS[value["provider_config"]][
                "mcp_protocol_version"
            ],
            "provider_auth_retained_until_transport_exit": True,
            "operator_command_broker_receives_credentials": False,
            "operator_command_broker_receives_semantic_prompt": False,
            "operator_command_task_level_network": False,
            "grader_evidence_surface_read_only": True,
        }
        for value in provider_probes["providers"]
    }
    preflight = {
        "schema": "maude.synthetic-operator.preflight.v1",
        "campaign_id": CAMPAIGN_ID,
        "observed_at": frozen_at,
        "authority_effect": "none",
        "observation_custody": (
            "Initial Git facts are preserved in a separately pinned command "
            "record captured at the clean preparation-base commit before "
            "successor inputs or evaluator code changed. Provider/isolation "
            "and installed-surface probes are exact later pre-freeze "
            "observations, and live Git identity fields are rechecked by this "
            "freezer."
        ),
        "repository": {
            "path": str(REPO_ROOT),
            "origin": origin["stdout"].strip(),
            "branch": git_branch["stdout"].strip(),
            "head": git_head["stdout"].strip(),
            "preparation_base_commit": PREPARATION_BASE_COMMIT,
            "upstream": git_upstream["stdout"].strip(),
            "upstream_head": upstream_head["stdout"].strip(),
            "initial_observation": file_record(INITIAL_REPOSITORY_OBSERVATION),
            "clean_at_campaign_start": (
                initial_observation["observations"]["status_short"]["stdout"] == ""
            ),
            "initial_git_status_short": initial_observation["observations"][
                "status_short"
            ]["stdout"],
            "initial_state_observed_before_campaign_artifact_creation": True,
            "initial_observation_wall_clock_captured": True,
            "live_recheck_commands": {
                "head": git_head,
                "branch": git_branch,
                "upstream": git_upstream,
                "upstream_head": upstream_head,
                "origin": origin,
            },
        },
        "required_baseline": SUT_COMMIT,
        "required_preparation_base": PREPARATION_BASE_COMMIT,
        "successor_lineage": file_record(SUCCESSOR_LINEAGE),
        "versions": versions,
        "provider_session_capability_probes": provider_probes,
        "installation_surface_capability_probes": (installation_surface_probes),
        "grader_surface_capability_probes": grader_surface_probes,
        "provider_auth_gate_fake_process_selftest": auth_gate_selftest,
        "provider_assignment_provider_free_selftest": assignment_selftest,
        "deterministic_provider_assignment_validation": {
            "algorithm": "maude-synthetic-provider-assignment-v1",
            "finalizer": file_record(FINALIZE_PROVIDER_ASSIGNMENTS),
            "validation_errors": [],
            "valid": True,
            "authority_effect": "none",
        },
        "provider_capability_policy": (_provider_capability_policy_record()),
        "model_family_policy": matrix["model_family_policy"],
        "role_assignment_capability_validation": capability_assignment,
        "all_capability_probe_session_identities_distinct": True,
        "isolation_capability_probe": {
            "mechanism": "bubblewrap",
            "result": (
                "passed for every provider role assigned by the final matrix; "
                "stable provider-capability-unavailable observations remain "
                "recorded for any excluded candidate role"
            ),
            "repository_source_absent": True,
            "provider_cli_startup_passed_provider_configs": provider_probes[
                "successful_provider_configs"
            ],
            "provider_capability_unavailable_configs": provider_probes[
                "unavailable_provider_configs"
            ],
            "provider_role_assignments": capability_assignment["assignments"],
            "provider_boundaries": provider_boundary_summaries,
            "provider_network_permitted_only_for_provider_session_transport": (True),
            "locally_configured_provider_credentials_permitted_only_for_provider_session_transport": (
                True
            ),
            "task_level_network_permitted": False,
            "production_task_systems_or_credentials_permitted": False,
            "external_operational_side_effects_permitted": False,
            "limitation": (matrix["model_family_policy"]["limitation"]),
            "resolver_mount": (
                "Each task-blind provider transport may retain resolver access "
                "needed only for provider traffic. Per-command and persistent-"
                "PTY task namespaces have no external network; only explicitly "
                "declared synthetic Unix sockets may be bound."
            ),
        },
        "related_runtime_repositories": {
            "agent_governor": {
                "head": "485e55783f9e359965e3b736e1d610c4568d45f1",
                "version": "2.8.1",
                "state": "clean when inspected",
                "role": "protocol reference only; not written by campaign",
            },
            "docket": {
                "initial_observed_head": "6349b5c1e03b91137d5978bcc127900411bc1588",
                "initial_observed_state": "dirty",
                "frozen_head_after_external_transition": DOCKET_COMMIT,
                "state_at_fixture_freeze": (
                    "clean local main, then one commit ahead of upstream"
                ),
                "later_external_state": (
                    "origin/main advanced to the same 9050a53 commit; local and "
                    "upstream now agree"
                ),
                "transition_attribution": (
                    "all Docket worktree and remote transitions were external to "
                    "this campaign"
                ),
                "frozen_binary_sha256": sha256_file(
                    PACKET_DIR / "direct-runtime" / "bin" / "docket"
                ),
                "broker_binary_sha256": sha256_file(
                    PACKET_DIR / "direct-runtime" / "bin" / "gwr-git-broker"
                ),
                "source_archive_sha256": sha256_file(source_archive),
                "source_archive_git_commit_id": tar_commit,
                "cargo_lock_sha256": "5c38063663027eb81c1098e91a46008e53ed7b8feb55bd440c22a4b7c785a373",
                "build_toolchain": "Rust 1.94.0; cargo --locked --offline --release",
                "role": "frozen direct-runtime comparator; not written by campaign",
            },
        },
        "write_scope": {
            "repository_writes": str(REPO_ROOT),
            "persistent_writes_outside_repository": False,
            "ephemeral_synthetic_tmp_writes": True,
            "ephemeral_synthetic_tmp_root": str(LAB_ROOT),
            "other_repository_writes": False,
            "remote_writes": False,
        },
    }
    if preflight["repository"]["head"] != PREPARATION_BASE_COMMIT:
        raise CampaignError(
            "preflight HEAD "
            f"{preflight['repository']['head']} != "
            f"{PREPARATION_BASE_COMMIT}"
        )
    if preflight["repository"]["branch"] != "main":
        raise CampaignError("campaign is no longer on existing main working line")
    write_json(PACKET_DIR / "preflight.json", preflight)


def _write_hash_inventory() -> None:
    excluded = {
        MANIFEST_PATH,
        PACKET_DIR / "manifest.md",
        PACKET_DIR / "hash-inventory.json",
    }
    records = [
        file_record(path) for path in _artifact_candidates() if path not in excluded
    ]
    write_json(
        PACKET_DIR / "hash-inventory.json",
        {
            "schema": "maude.synthetic-operator.hash-inventory.v1",
            "campaign_id": CAMPAIGN_ID,
            "authority_effect": "none",
            "self_exclusion": (
                "hash-inventory.json and the two manifest renderings are excluded "
                "to avoid recursive digests"
            ),
            "artifacts": sorted(records, key=lambda item: item["path"]),
        },
    )


def _manifest_markdown(manifest: dict[str, Any]) -> str:
    runs = manifest["runs"]
    lines = [
        "# Frozen synthetic operator campaign manifest",
        "",
        f"**Campaign ID:** `{CAMPAIGN_ID}`",
        f"**Frozen at:** `{manifest['frozen_at']}`",
        f"**System under test commit:** `{SUT_COMMIT}`",
        f"**Preparation base commit:** `{PREPARATION_BASE_COMMIT}`",
        (
            "**Superseded generations:** "
            "`maude-baseline-20260726T233054-0400` and "
            "`maude-baseline-20260728T032857-0400`, and "
            "`maude-baseline-20260728T050937-0400` (all aborted for "
            "evaluator-infrastructure defects; none of their sessions, "
            "grades, or artifacts count as evidence or completion here)"
        ),
        "**Authority effect:** None.",
        "",
        "The scaffold does not require a role-by-scenario cross product. The",
        "twenty Maude specimens cover each required scenario once; the ten",
        "personas are coverage constraints. Five Docket/GWR runs are",
        "task-equivalent direct-runtime controls; the client-restart control is",
        "capability-limited because that surface cannot reproduce Maude daemon",
        "recovery. Ten installation and first-use",
        "specimens cover the five installation backgrounds twice each; those",
        "backgrounds are also coverage constraints, not a cross product.",
        "",
        "## Run matrix",
        "",
        "| Run | Surface | Scenario | Persona | Operator | Grader |",
        "|---|---|---|---|---|---|",
    ]
    for run in runs:
        lines.append(
            f"| `{run['run_id']}` | `{run['surface']}` | "
            f"`{run['scenario_id']}` | `{run['persona_id']}` | "
            f"`{run['operator_model_config']}` | "
            f"`{run['grader_model_config']}` |"
        )
    lines.extend(
        [
            "",
            "## Custody",
            "",
            f"The machine-readable manifest pins {len(manifest['frozen_artifacts'])} "
            "prompt, fixture, harness, binary, rubric, taxonomy, and supplied-document "
            "artifacts by byte count and SHA-256. Raw evidence and grades are written "
            "outside `packet/`; interpretations never overwrite transcripts.",
            "",
            "The campaign runner must pass Bubblewrap isolation preflight before any",
            "operator or grader session. It does not bind the Maude repository into",
            "the model-visible filesystem.",
            "",
        ]
    )
    return "\n".join(lines)


def _required_direct_inputs() -> list[Path]:
    result = [
        PACKET_DIR / "direct-runtime" / "bin" / "docket",
        PACKET_DIR / "direct-runtime" / "bin" / "gwr-git-broker",
        PACKET_DIR / "direct-runtime" / "docs" / "operator-runbook.md",
        PACKET_DIR / "direct-runtime" / "docs" / "attempt-dossier.md",
        PACKET_DIR / "direct-runtime" / "fixtures" / "index.json",
    ]
    for run_id in DIRECT_RUN_IDS:
        result.extend(
            [
                PACKET_DIR / "direct-runtime" / "fixtures" / f"{run_id}.json",
                PACKET_DIR / "direct-runtime" / "fixtures" / f"{run_id}.tar",
            ]
        )
    return result


def _validate_static_inputs() -> list[str]:
    errors = validate_matrix()
    required = [
        MATRIX_PATH,
        PROVIDER_CAPABILITY_POLICY_PATH,
        INSTALL_TRACK_PATH,
        INITIAL_REPOSITORY_OBSERVATION,
        SUCCESSOR_LINEAGE,
        PACKET_DIR / "grading-rubric.md",
        PACKET_DIR / "installation-grading-rubric.md",
        PACKET_DIR / "failure-taxonomy.json",
        PACKET_DIR / "grader-output.schema.json",
        PACKET_DIR / "installation-grader-output.schema.json",
        PACKET_DIR / "prompts" / "operator-system.md",
        PACKET_DIR / "prompts" / "installation-operator-system.md",
        PACKET_DIR / "prompts" / "grader-system.md",
        HARNESS_DIR / "maude",
        HARNESS_DIR / "public_cli.py",
        PUBLIC_CLI_BROKER,
        OPERATOR_RETROSPECTIVE,
        OPERATOR_PTY,
        CLAUDE_MCP_BRIDGE,
        HARNESS_DIR / "maude_driver.py",
        HARNESS_DIR / "synthetic_runtime.py",
        HARNESS_DIR / "prepare_installation_media.py",
        HARNESS_DIR / "grader_surface_probe.py",
        HARNESS_DIR / "auth_gate_selftest.py",
        FINALIZE_PROVIDER_ASSIGNMENTS,
        PROVIDER_ASSIGNMENT_SELFTEST,
        AUTH_GATE_PROBE_PATH,
        INSTALL_SURFACE_PROBE_PATH,
        grader_surface_probe.OUTPUT_ROOT / "index.json",
        HARNESS_DIR / "test_authority_fixtures.py",
        HARNESS_DIR / "test_fixture_fidelity.py",
        SCENARIOS_DIR / "_build_corpus.py",
        SCENARIOS_DIR / "_build_install_track.py",
        INSTALL_MEDIA_PROVENANCE,
        INSTALL_SOURCE_ARCHIVE,
        INSTALL_MEDIA_DIR / "runtime-requirements.txt",
        INSTALL_MEDIA_DIR / "clean-install-validation.json",
        *_required_direct_inputs(),
        *OPERATOR_DOC_SOURCES,
        *(source for source, _relative in INSTALL_OPERATOR_DOC_SOURCES),
    ]
    for path in required:
        if not path.is_file():
            errors.append(f"missing required campaign input: {path}")
    try:
        _provider_capability_policy()
    except CampaignError as exc:
        errors.append(str(exc))
    errors.extend(finalize_provider_assignments.validate_finalized_matrix())
    errors.extend(_validate_successor_lineage())
    for path in (
        HARNESS_DIR / "maude",
        HARNESS_DIR / "public_cli.py",
        OPERATOR_RETROSPECTIVE,
        OPERATOR_PTY,
    ):
        if path.is_file() and f"{path.stat().st_mode & 0o777:04o}" != "0755":
            errors.append(f"campaign helper must have mode 0755: {path}")
    errors.extend(_validate_final_boundary_bytes())
    errors.extend(_validate_provider_boundary_declarations())
    errors.extend(_validate_bridge_help_neutrality())
    errors.extend(_validate_public_cli_boundary_declarations())
    for argv, label in (
        (
            [
                "python3",
                "-B",
                str(SCENARIOS_DIR / "_build_corpus.py"),
                "--validate",
            ],
            "operational corpus",
        ),
        (
            [
                "python3",
                "-B",
                str(SCENARIOS_DIR / "_build_install_track.py"),
                "--validate",
            ],
            "installation corpus",
        ),
        (
            [
                "python3",
                "-B",
                str(HARNESS_DIR / "prepare_installation_media.py"),
                "--validate",
            ],
            "installation media",
        ),
        (
            [
                "python3",
                "-B",
                str(HARNESS_DIR / "grader_surface_probe.py"),
                "validate",
                "--allow-provider-capability-unavailable",
            ],
            "grader-surface capability probes",
        ),
        (
            [
                "python3",
                "-B",
                str(HARNESS_DIR / "test_authority_fixtures.py"),
            ],
            "authority fixture cross-check",
        ),
        (
            [
                "python3",
                "-B",
                str(HARNESS_DIR / "test_fixture_fidelity.py"),
            ],
            "operational fixture fidelity",
        ),
        (
            [
                "python3",
                "-B",
                str(PROVIDER_ASSIGNMENT_SELFTEST),
            ],
            "provider assignment provider-free regression",
        ),
        (
            [
                "python3",
                "-B",
                str(PACKET_DIR / "direct-runtime" / "prepare_controls.py"),
                "--validate",
            ],
            "direct-runtime controls",
        ),
    ):
        completed = subprocess.run(
            argv,
            cwd=REPO_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if completed.returncode != 0:
            errors.append(
                f"{label} validation failed: "
                f"{completed.stdout.decode(errors='replace')}"
                f"{completed.stderr.decode(errors='replace')}"
            )
    for run in matrix_runs(load_matrix()) if not errors else []:
        try:
            _regular_files(
                SCENARIOS_DIR / run["scenario_id"] / "fixture",
                label=f"{run['run_id']} visible fixture",
            )
        except CampaignError as exc:
            errors.append(str(exc))
    if not errors:
        errors.extend(
            _validate_operator_surface_sanitization(
                load_matrix(), include_rendered=False
            )
        )
    try:
        list(_artifact_candidates())
    except CampaignError as exc:
        errors.append(str(exc))
    return errors


def _validate_successor_lineage() -> list[str]:
    """Bind three discarded generations without importing their evidence."""

    if not SUCCESSOR_LINEAGE.is_file() or SUCCESSOR_LINEAGE.is_symlink():
        return ["successor lineage record is absent or unsafe"]
    generation_1_root = EVAL_ROOT / "runs" / "maude-baseline-20260726T233054-0400"
    generation_2_root = EVAL_ROOT / "runs" / "maude-baseline-20260728T032857-0400"
    generation_1_manifest = generation_1_root / "packet" / "campaign-manifest.json"
    generation_1_abort = generation_1_root / "campaign-abort.json"
    generation_2_manifest = generation_2_root / "packet" / "campaign-manifest.json"
    generation_2_abort = generation_2_root / "campaign-abort.json"
    generation_2_verifier_gap = generation_2_root / "verifier-gap-reproduction.json"
    generation_3_root = EVAL_ROOT / "runs" / "maude-baseline-20260728T050937-0400"
    generation_3_manifest = generation_3_root / "packet" / "campaign-manifest.json"
    generation_3_abort = generation_3_root / "campaign-abort.json"
    generation_3_preservation_inventory = (
        generation_3_root / "commit-artifact-inventory.json"
    )
    expected = {
        "schema": "maude.synthetic-operator.successor-lineage.v3",
        "campaign_id": CAMPAIGN_ID,
        "generation": 4,
        "preparation_base_commit": PREPARATION_BASE_COMMIT,
        "system_under_test_commit": SUT_COMMIT,
        "prior_generations": [
            {
                "generation": 1,
                "campaign_id": ("maude-baseline-20260726T233054-0400"),
                "campaign_manifest": {
                    "path": str(generation_1_manifest.relative_to(REPO_ROOT)),
                    "bytes": 425984,
                    "sha256": (
                        "58622e506773edb1a767dfc260fdfc0ff6a82e106550dc"
                        "96d9d5893729f3e17d"
                    ),
                },
                "packet_commit": ("f9e8caadf194c38384e981baa7cd0b6a5dcac9b1"),
                "abort_record": {
                    "path": str(generation_1_abort.relative_to(REPO_ROOT)),
                    "bytes": 3735,
                    "sha256": (
                        "984e165b7472139e770c18cba04a855f8cb2d34c9af93"
                        "ae600b92d49dfe2f129"
                    ),
                },
                "preservation_commit": ("09af081fbd1326bf4a76d22b19de0aa03663c8f8"),
                "campaign_disposition": ("aborted-evaluator-infrastructure"),
                "operator_stage": {
                    "declared_runs": 35,
                    "completion_markers": 25,
                    "unique_provider_session_identities": 25,
                    "coached_sessions": 0,
                    "installation_runs_failed_pre_provider": 10,
                    "installation_provider_sessions_started": 0,
                },
                "grading_stage": {
                    "provider_sessions_started": 24,
                    "completed_grades": 0,
                },
                "failure_summary": (
                    "Installation materialization and grader schema, "
                    "argument-size, and evaluator-validation defects "
                    "invalidated the generation."
                ),
                "counts_as_current_campaign_evidence": False,
                "counts_toward_current_campaign_completion": False,
            },
            {
                "generation": 2,
                "campaign_id": ("maude-baseline-20260728T032857-0400"),
                "campaign_manifest": {
                    "path": str(generation_2_manifest.relative_to(REPO_ROOT)),
                    "bytes": 460487,
                    "sha256": (
                        "f9bb0a0c079adf85942a0c9fd1905abcf0833d747ee64"
                        "f283f3f5322a1ce8ef4"
                    ),
                },
                "packet_commit": ("47f21ca3cca08e93a8428ce8b8f91c4e74cfac3d"),
                "abort_record": {
                    "path": str(generation_2_abort.relative_to(REPO_ROOT)),
                    "bytes": 3957,
                    "sha256": (
                        "5abf3a384dfa11d8c7d7e2b270f2957b41c48c5698bd"
                        "66afae9705ead84b95e1"
                    ),
                },
                "verifier_gap_record": {
                    "path": str(generation_2_verifier_gap.relative_to(REPO_ROOT)),
                    "bytes": 3917,
                    "sha256": (
                        "7865bad16fa8611b670143313ab8f3e77b2188f7283fd"
                        "3fcd8c42f24a2d378f2"
                    ),
                },
                "preservation_commit": ("d76b90a0c990016354bb44ff2ab97e4675f7199a"),
                "campaign_disposition": ("aborted-evaluator-infrastructure"),
                "operator_stage": {
                    "declared_runs": 35,
                    "materialized_runs": 35,
                    "provider_sessions_started": 17,
                    "completion_markers": 15,
                    "completed_unique_provider_session_identities": 15,
                    "interrupted_provider_session_identities": 2,
                    "runs_not_started": 18,
                    "coached_sessions": 0,
                },
                "grading_stage": {
                    "provider_sessions_started": 0,
                    "completed_grades": 0,
                },
                "failure_summary": (
                    "The frozen verifier accepted missing or semantically "
                    "invalid command-broker evidence, and a retrospective "
                    "result-wrapper defect misclassified all 15 completed "
                    "runs."
                ),
                "counts_as_current_campaign_evidence": False,
                "counts_toward_current_campaign_completion": False,
            },
            {
                "generation": 3,
                "campaign_id": ("maude-baseline-20260728T050937-0400"),
                "campaign_manifest": {
                    "path": str(generation_3_manifest.relative_to(REPO_ROOT)),
                    "bytes": 497806,
                    "sha256": (
                        "ac342a7005e252c979657c1105123cd4614d85e63dcd37"
                        "d604f3bc55e79e9cac"
                    ),
                },
                "packet_commit": ("bba7875b3448a21586fe7cf1cd4ab7dd223d3782"),
                "abort_record": {
                    "path": str(generation_3_abort.relative_to(REPO_ROOT)),
                    "bytes": 5473,
                    "sha256": (
                        "9ec8d8ed1115e220c177231dbb00d13f0d56597a4eaf64"
                        "ace6390ebcda994f7d"
                    ),
                },
                "preservation_inventory": {
                    "path": str(
                        generation_3_preservation_inventory.relative_to(REPO_ROOT)
                    ),
                    "bytes": 651898,
                    "sha256": (
                        "22108c597b63937b4361ff49f5d4abae4cea9c17031bfd20"
                        "af96fd204b3347a3"
                    ),
                },
                "preservation_commit": ("631302ff5c690a47eba8c2808044451aecba0bea"),
                "campaign_disposition": ("aborted-evaluator-infrastructure"),
                "operator_stage": {
                    "declared_runs": 35,
                    "materialized_runs": 35,
                    "provider_sessions_started": 30,
                    "completion_markers": 30,
                    "completed_unique_provider_session_identities": 30,
                    "pre_session_failures": 5,
                    "pre_session_failure_provider_identities": 0,
                    "coached_sessions": 0,
                },
                "grading_stage": {
                    "provider_sessions_started": 0,
                    "completed_grades": 0,
                },
                "failure_summary": (
                    "The evaluator declared nonexistent installation venv and "
                    "unavailable-endpoint socket mounts, and its lab root "
                    "exceeded the conservative Unix-socket budget; all "
                    "generation-3 evidence is non-counting."
                ),
                "counts_as_current_campaign_evidence": False,
                "counts_toward_current_campaign_completion": False,
            },
        ],
        "evidence_boundary": {
            "prior_generations_count_as_campaign_evidence": False,
            "prior_generations_count_toward_campaign_completion": False,
            "current_generation_full_matrix_rerun_required": True,
            "required_current_generation_run_count": 35,
            "statement": (
                "Generations 1, 2, and 3 are immutable preservation and "
                "preparation history only. Their sessions, failures, grades, "
                "artifacts, and findings do not count as evidence or "
                "completion for generation 4; all 35 runs require new fresh "
                "operator and independent-grader sessions."
            ),
        },
        "authority_effect": "none",
    }
    try:
        actual = load_json(SUCCESSOR_LINEAGE)
    except CampaignError as exc:
        return [str(exc)]
    errors: list[str] = []
    if actual != expected:
        errors.append("successor lineage record differs from the exact history")
    history = [
        (
            generation_1_manifest,
            expected["prior_generations"][0]["campaign_manifest"],
            "generation-1 manifest",
            expected["prior_generations"][0]["packet_commit"],
        ),
        (
            generation_1_abort,
            expected["prior_generations"][0]["abort_record"],
            "generation-1 abort record",
            None,
        ),
        (
            generation_2_manifest,
            expected["prior_generations"][1]["campaign_manifest"],
            "generation-2 manifest",
            expected["prior_generations"][1]["packet_commit"],
        ),
        (
            generation_2_abort,
            expected["prior_generations"][1]["abort_record"],
            "generation-2 abort record",
            None,
        ),
        (
            generation_2_verifier_gap,
            expected["prior_generations"][1]["verifier_gap_record"],
            "generation-2 verifier-gap record",
            None,
        ),
        (
            generation_3_manifest,
            expected["prior_generations"][2]["campaign_manifest"],
            "generation-3 manifest",
            expected["prior_generations"][2]["packet_commit"],
        ),
        (
            generation_3_abort,
            expected["prior_generations"][2]["abort_record"],
            "generation-3 abort record",
            None,
        ),
        (
            generation_3_preservation_inventory,
            expected["prior_generations"][2]["preservation_inventory"],
            "generation-3 preservation inventory",
            None,
        ),
    ]
    for path, record, label, packet_commit in history:
        if (
            not path.is_file()
            or path.is_symlink()
            or path.stat().st_size != record["bytes"]
            or sha256_file(path) != record["sha256"]
        ):
            errors.append(f"{label} bytes differ from successor lineage")
            continue
        preservation_commit = next(
            generation["preservation_commit"]
            for generation in expected["prior_generations"]
            if path.is_relative_to(
                REPO_ROOT
                / "evals"
                / "synthetic-operator"
                / "runs"
                / generation["campaign_id"]
            )
        )
        for commit, commit_label in (
            (preservation_commit, "preservation commit"),
            (packet_commit, "packet commit"),
        ):
            if commit is None:
                continue
            observed_bytes = subprocess.run(
                ["git", "show", f"{commit}:{record['path']}"],
                cwd=REPO_ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            if (
                observed_bytes.returncode != 0
                or len(observed_bytes.stdout) != record["bytes"]
                or hashlib.sha256(observed_bytes.stdout).hexdigest() != record["sha256"]
            ):
                errors.append(f"{label} is not exact at its {commit_label}")
    for generation in expected["prior_generations"]:
        packet_commit = generation["packet_commit"]
        preservation_commit = generation["preservation_commit"]
        for commit, label in (
            (packet_commit, "packet commit"),
            (preservation_commit, "preservation commit"),
        ):
            observed = subprocess.run(
                ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
                cwd=REPO_ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            if observed.returncode != 0:
                errors.append(
                    f"generation-{generation['generation']} {label} is absent"
                )
        for ancestor, descendant, label in (
            (
                packet_commit,
                preservation_commit,
                "packet commit is not an ancestor of preservation commit",
            ),
            (
                preservation_commit,
                PREPARATION_BASE_COMMIT,
                "preservation commit is not an ancestor of preparation base",
            ),
        ):
            observed = subprocess.run(
                ["git", "merge-base", "--is-ancestor", ancestor, descendant],
                cwd=REPO_ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            if observed.returncode != 0:
                errors.append(f"generation-{generation['generation']} {label}")
    return errors


def _validate_final_boundary_bytes() -> list[str]:
    """Fail closed if any audited runner/boundary byte changes."""

    expected = {
        HARNESS_DIR / "campaign_runner.py": (
            631228,
            CLAUDE_RUNNER_SHA256,
        ),
        CLAUDE_MCP_BRIDGE: (56742, CLAUDE_BRIDGE_SHA256),
        OPERATOR_PTY: (32867, OPERATOR_PTY_SHA256),
        HARNESS_DIR / "public_cli.py": (6047, PUBLIC_CLI_SHA256),
        PUBLIC_CLI_BROKER: (16736, PUBLIC_CLI_BROKER_SHA256),
        HARNESS_DIR / "auth_gate_selftest.py": (
            172944,
            AUTH_GATE_SELFTEST_SHA256,
        ),
        HARNESS_DIR / "grader_surface_probe.py": (
            76821,
            GRADER_SURFACE_PROBE_SHA256,
        ),
        HARNESS_DIR / "campaign_common.py": (
            39235,
            CAMPAIGN_COMMON_SHA256,
        ),
        FINALIZE_PROVIDER_ASSIGNMENTS: (
            33348,
            FINALIZE_PROVIDER_ASSIGNMENTS_SHA256,
        ),
        PROVIDER_ASSIGNMENT_SELFTEST: (
            26215,
            PROVIDER_ASSIGNMENT_SELFTEST_SHA256,
        ),
    }
    errors: list[str] = []
    for path, (byte_count, digest) in expected.items():
        if not path.is_file() or path.is_symlink():
            errors.append(f"audited campaign boundary file is absent: {path}")
            continue
        if path.stat().st_size != byte_count or sha256_file(path) != digest:
            errors.append(
                "audited campaign boundary bytes changed: "
                f"{path} expected_bytes={byte_count} "
                f"expected_sha256={digest}"
            )
    return errors


def _validate_provider_boundary_declarations() -> list[str]:
    """Reject stale tool rosters or ambiguous provider-boundary metadata."""

    errors: list[str] = []
    try:
        matrix = load_matrix()
    except CampaignError as exc:
        return [str(exc)]
    try:
        _model_execution_configs(matrix)
        _provider_capability_policy()
    except CampaignError as exc:
        errors.append(str(exc))
    policy = matrix.get("model_family_policy")
    if (
        not isinstance(policy, dict)
        or policy.get("assignment_algorithm")
        != "maude-synthetic-provider-assignment-v1"
        or policy.get("separate_fresh_sessions_required") is not True
        or not isinstance(policy.get("provider_role_eligibility"), dict)
    ):
        errors.append(
            "matrix model-family policy does not declare the finalized "
            "provider-role assignment and separate-session boundary"
        )
    if CLAUDE_MCP_BRIDGE.is_file():
        for mode, expected in (
            (
                "operator",
                {
                    "command_execution": True,
                    "grader_read_only": False,
                    "mode": "operator",
                    "server": "maude-synthetic-operator-cleanroom",
                    "supported_mcp_protocol_versions": (
                        SUPPORTED_MCP_PROTOCOL_VERSIONS
                    ),
                    "tools": ["terminal"],
                    "version": "2",
                },
            ),
            (
                "grader",
                {
                    "command_execution": False,
                    "grader_read_only": True,
                    "mode": "grader",
                    "server": "maude-synthetic-operator-cleanroom",
                    "supported_mcp_protocol_versions": (
                        SUPPORTED_MCP_PROTOCOL_VERSIONS
                    ),
                    "tools": ["evidence"],
                    "version": "2",
                },
            ),
        ):
            completed = subprocess.run(
                [
                    "python3",
                    "-I",
                    "-B",
                    str(CLAUDE_MCP_BRIDGE),
                    "self-test",
                    "--mode",
                    mode,
                ],
                cwd=HARNESS_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            try:
                observed = json.loads(completed.stdout)
            except (UnicodeDecodeError, json.JSONDecodeError):
                observed = None
            if (
                completed.returncode != 0
                or completed.stderr != b""
                or observed != expected
            ):
                errors.append(
                    f"direct stdio MCP shim {mode} self-test differs from the "
                    "frozen one-tool contract"
                )
    return errors


def _validate_bridge_help_neutrality() -> list[str]:
    """Keep the evaluation-only terminal bridge from coaching task workflow."""

    errors: list[str] = []
    bridge = HARNESS_DIR / "maude"
    implementation = HARNESS_DIR / "public_cli.py"
    if not bridge.is_file() or not implementation.is_file():
        return errors
    completed = subprocess.run(
        ["python3", "-B", str(bridge), "--cli-help"],
        cwd=HARNESS_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        return [
            "terminal bridge --cli-help failed during neutrality validation: "
            + completed.stderr.decode("utf-8", errors="replace").strip()
        ]
    try:
        help_text = completed.stdout.decode("utf-8")
        source_text = implementation.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [f"cannot inspect terminal bridge help/source: {exc}"]
    if "./maude '<Maude command>'" not in help_text or "./maude help" not in help_text:
        errors.append(
            "terminal bridge help must explain generic command submission and "
            "delegate command discovery to Maude help"
        )
    lowered_help = help_text.casefold()
    lowered_source = source_text.casefold()
    if "maude_public_socket" not in lowered_source:
        errors.append("terminal bridge must use only the declared public Unix socket")
    for private_fragment in (
        "maude_lab_control_dir",
        "control/requests",
        "control/responses",
    ):
        if private_fragment in lowered_source:
            errors.append(
                "operator-visible terminal bridge references evaluator-private "
                f"queue material: {private_fragment!r}"
            )
    for fragment in BRIDGE_TASK_HINT_FRAGMENTS:
        if fragment.casefold() in lowered_help:
            errors.append(
                f"terminal bridge help contains task-workflow hint {fragment!r}"
            )
        if fragment.casefold() in lowered_source:
            errors.append(
                f"terminal bridge source contains task-workflow hint {fragment!r}"
            )
    matrix = load_matrix()
    forbidden_identities = {
        str(value)
        for run in matrix_runs(matrix)
        for value in (
            run.get("run_id"),
            run.get("scenario_id"),
            run.get("task_id"),
        )
        if isinstance(value, str) and value
    }
    for identity in sorted(forbidden_identities):
        if identity.casefold() in lowered_help:
            errors.append(
                f"terminal bridge help contains campaign/task identity {identity!r}"
            )
        if identity.casefold() in lowered_source:
            errors.append(
                f"terminal bridge source contains campaign/task identity {identity!r}"
            )
    return errors


def _validate_public_cli_boundary_declarations() -> list[str]:
    """Bind the public socket/private queue split before any campaign run."""

    if not PUBLIC_CLI_BROKER.is_file():
        return []
    try:
        source = PUBLIC_CLI_BROKER.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [f"cannot inspect public-CLI broker source: {exc}"]
    required_fragments = (
        "maude.synthetic-operator.public-cli-request.v1",
        "maude.synthetic-operator.public-cli-broker-event.v1",
        "maude.synthetic-operator.public-cli-broker-ready.v1",
        "maude.synthetic-operator.public-cli-broker-cleanup.v1",
        '"raw_control_dir_exposed_to_client": False',
    )
    missing = [value for value in required_fragments if value not in source]
    errors = [
        f"public-CLI broker declaration is absent: {value!r}" for value in missing
    ]
    completed = subprocess.run(
        ["python3", "-I", "-B", str(PUBLIC_CLI_BROKER), "--help"],
        cwd=HARNESS_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    help_text = completed.stdout.decode("utf-8", errors="replace")
    if (
        completed.returncode != 0
        or completed.stderr
        or any(
            option not in help_text
            for option in (
                "--control-dir",
                "--socket",
                "--trace",
                "--ready",
                "--cleanup",
            )
        )
    ):
        errors.append(
            "public-CLI broker help does not expose its complete trusted "
            "boundary configuration"
        )
    return errors


def _git_blob_at_baseline(path: Path) -> bytes:
    rel = str(path.relative_to(REPO_ROOT))
    completed = subprocess.run(
        ["git", "show", f"{SUT_COMMIT}:{rel}"],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise CampaignError(
            f"cannot read baseline blob {rel}: "
            f"{completed.stderr.decode(errors='replace').strip()}"
        )
    return completed.stdout


def _validate_sut_bytes() -> list[str]:
    errors: list[str] = []
    diff = subprocess.run(
        [
            "git",
            "diff",
            "--exit-code",
            SUT_COMMIT,
            "--",
            "src",
            "pyproject.toml",
            "README.md",
            "docs/README.md",
            "docs/commands.md",
            "docs/configuration.md",
        ],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if diff.returncode != 0:
        errors.append("system-under-test tree differs from baseline commit")
    for path in (
        REPO_ROOT / "src",
        REPO_ROOT / "pyproject.toml",
        REPO_ROOT / "README.md",
        REPO_ROOT / "docs" / "README.md",
        REPO_ROOT / "docs" / "commands.md",
        REPO_ROOT / "docs" / "configuration.md",
    ):
        candidates = sorted(path.rglob("*")) if path.is_dir() else [path]
        for candidate in candidates:
            if not candidate.is_file() or candidate.is_symlink():
                continue
            if "__pycache__" in candidate.parts or candidate.suffix == ".pyc":
                continue
            try:
                baseline = _git_blob_at_baseline(candidate)
            except CampaignError as exc:
                errors.append(str(exc))
                continue
            if candidate.read_bytes() != baseline:
                errors.append(
                    f"system-under-test bytes differ from baseline commit: "
                    f"{candidate.relative_to(REPO_ROOT)}"
                )
    return errors


def freeze(*, dry_run: bool) -> dict[str, Any]:
    errors = _validate_static_inputs() + _validate_sut_bytes()
    if errors:
        raise CampaignError("\n".join(errors))
    matrix = load_matrix()
    if dry_run:
        return {
            "campaign_id": CAMPAIGN_ID,
            "would_copy_operator_docs": [
                str(path.relative_to(REPO_ROOT)) for path in OPERATOR_DOC_SOURCES
            ],
            "would_copy_installation_docs": [
                {
                    "source": str(source.relative_to(REPO_ROOT)),
                    "destination": relative.as_posix(),
                }
                for source, relative in INSTALL_OPERATOR_DOC_SOURCES
            ],
            "would_render_runs": [item["run_id"] for item in matrix_runs(matrix)],
            "would_freeze_installation_endpoint_plans": sorted(INSTALL_ENDPOINT_SPECS),
            "would_write": [
                str(MANIFEST_PATH.relative_to(REPO_ROOT)),
                str((PACKET_DIR / "manifest.md").relative_to(REPO_ROOT)),
            ],
        }
    _copy_operator_docs()
    _copy_install_operator_docs()
    _copy_linked_direct_docs()
    _render_installation_endpoint_plans(matrix)
    _render_prompts(matrix)
    endpoint_errors = _validate_installation_endpoint_plans(matrix)
    if endpoint_errors:
        raise CampaignError("\n".join(endpoint_errors))
    sanitization_errors = _validate_operator_surface_sanitization(
        matrix, include_rendered=True
    )
    if sanitization_errors:
        raise CampaignError("\n".join(sanitization_errors))
    frozen_at = (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    _write_preflight(frozen_at=frozen_at)
    _write_hash_inventory()
    manifest = _build_manifest(matrix, frozen_at=frozen_at)
    write_text(PACKET_DIR / "manifest.md", _manifest_markdown(manifest))
    # The immutable JSON manifest is the final write. Its presence locks the
    # packet against a second generation.
    write_json(MANIFEST_PATH, manifest)
    return manifest


def validate_frozen() -> list[str]:
    errors = _validate_static_inputs() + _validate_sut_bytes()
    if not MANIFEST_PATH.is_file():
        errors.append(f"campaign manifest is absent: {MANIFEST_PATH}")
        return errors
    try:
        manifest = load_json(MANIFEST_PATH)
        errors.extend(_validate_installation_endpoint_plans(load_matrix()))
        errors.extend(
            _validate_operator_surface_sanitization(
                load_matrix(), include_rendered=True
            )
        )
        if manifest.get("schema") != MANIFEST_SCHEMA:
            errors.append("campaign manifest schema is wrong")
        if manifest.get("campaign_id") != CAMPAIGN_ID:
            errors.append("campaign manifest ID is wrong")
        errors.extend(validate_manifest_hashes(manifest))
        expected_paths = {record["path"] for record in _frozen_artifacts()}
        actual_paths = set(manifest_artifact_map(manifest))
        if expected_paths != actual_paths:
            errors.append(
                "campaign artifact path set changed: "
                f"added={sorted(expected_paths - actual_paths)!r} "
                f"removed={sorted(actual_paths - expected_paths)!r}"
            )
    except CampaignError as exc:
        errors.append(str(exc))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Freeze or validate the synthetic operator campaign packet"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--validate", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        if args.validate:
            errors = validate_frozen()
            if errors:
                print(json.dumps({"ok": False, "errors": errors}, indent=2))
                return 1
            manifest = load_json(MANIFEST_PATH)
            print(
                json.dumps(
                    {
                        "ok": True,
                        "campaign_id": CAMPAIGN_ID,
                        "runs": len(manifest["runs"]),
                        "frozen_artifacts": len(manifest["frozen_artifacts"]),
                        "manifest_sha256": sha256_file(MANIFEST_PATH),
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        if args.write and MANIFEST_PATH.exists():
            raise CampaignError(
                "campaign-manifest.json already exists; frozen campaign inputs "
                "are immutable (use --validate)"
            )
        result = freeze(dry_run=args.dry_run)
        if args.dry_run:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            print(
                json.dumps(
                    {
                        "ok": True,
                        "campaign_id": CAMPAIGN_ID,
                        "runs": len(result["runs"]),
                        "frozen_artifacts": len(result["frozen_artifacts"]),
                        "manifest": str(MANIFEST_PATH.relative_to(REPO_ROOT)),
                        "manifest_sha256": sha256_file(MANIFEST_PATH),
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        return 0
    except (CampaignError, OSError, KeyError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
