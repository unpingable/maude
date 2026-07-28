#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Freeze the five bounded grader-only live-probe inputs."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


QUALIFICATION_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = QUALIFICATION_DIR.parents[2]
INPUTS = QUALIFICATION_DIR / "live-inputs"
PLAN = QUALIFICATION_DIR / "live-probe-plan.json"
PROBES = (
    ("L01", "Q01", "ordinary-admissible"),
    ("L02", "Q02", "installation-tool-discovery-temptation"),
    ("L03", "Q04", "contamination-requires-indeterminate"),
    ("L04", "Q06", "incomplete-evidence"),
    ("L05", "Q07", "contradictory-admissible-evidence"),
)
CODEX_HOST_ROOT = Path("/home/jbeck/.nvm/versions/node/v24.13.0")
CODEX_HOST_ENTRYPOINT = CODEX_HOST_ROOT / "bin" / "codex"
CODEX_HOST_NATIVE = (
    CODEX_HOST_ROOT
    / "lib/node_modules/@openai/codex/node_modules/@openai/"
    "codex-linux-x64/vendor/x86_64-unknown-linux-musl/bin/codex"
)
CODEX_EXPECTED_VERSION = "codex-cli 0.145.0"


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _pretty_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _record(path: Path, *, relative_to: Path = REPO_ROOT) -> dict[str, Any]:
    return {
        "path": path.relative_to(relative_to).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _external_record(path: Path) -> dict[str, Any]:
    resolved = path.resolve(strict=True)
    return {
        "path": str(path),
        "resolved_path": str(resolved),
        "bytes": resolved.stat().st_size,
        "sha256": _sha256(resolved),
    }


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    target.chmod(0o644)


def _git(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def build() -> dict[str, Any]:
    roster = QUALIFICATION_DIR / "allowed-tool-roster.json"
    schema = QUALIFICATION_DIR / "schemas" / "grader-output.schema.json"
    system_prompt = QUALIFICATION_DIR / "prompts" / "grader-system.md"
    request_template = (
        QUALIFICATION_DIR / "prompts" / "grader-request-template.md"
    )
    validator = (
        QUALIFICATION_DIR.parent / "harness" / "grader_admission.py"
    )
    provider_integration = (
        QUALIFICATION_DIR.parent / "harness" / "campaign_runner.py"
    )
    live_runner = QUALIFICATION_DIR / "scripts" / "run_live.py"
    input_builder = QUALIFICATION_DIR / "scripts" / "build_live_inputs.py"
    fixture_suite = QUALIFICATION_DIR / "fixture-suite.json"
    request_source = request_template.read_text(encoding="utf-8")
    version_probe = subprocess.run(
        [str(CODEX_HOST_ENTRYPOINT), "--version"],
        check=False,
        capture_output=True,
        text=True,
    )
    reported_version = version_probe.stdout.strip()
    if (
        version_probe.returncode != 0
        or reported_version != CODEX_EXPECTED_VERSION
    ):
        raise RuntimeError(
            "the frozen Codex runtime is unavailable or has changed: "
            f"returncode={version_probe.returncode} "
            f"stdout={reported_version!r}"
        )
    records: list[dict[str, Any]] = []
    for probe_id, fixture_id, purpose in PROBES:
        source_fixture = QUALIFICATION_DIR / "fixtures" / fixture_id
        expected = _load(QUALIFICATION_DIR / "expected" / f"{fixture_id}.json")
        root = INPUTS / probe_id
        bundle = root / "bundle"
        packet_source = (
            source_fixture / "evidence" / "evidence-packet.json"
        )
        packet = _load(packet_source)
        _copy(packet_source, bundle / "evidence-packet.json")
        for item in packet["items"]:
            if item["availability"] != "available":
                continue
            _copy(
                source_fixture / "evidence" / item["path"],
                bundle / item["path"],
            )
        _copy(schema, bundle / schema.name)
        _copy(system_prompt, root / "grader-system.md")
        request = request_source.replace("{{FIXTURE_ID}}", fixture_id)
        _write(root / "grader-request.md", request.encode("utf-8"))
        members = [
            _record(path, relative_to=root)
            for path in sorted(root.rglob("*"))
            if path.is_file() and path.name != "input-manifest.json"
        ]
        manifest = {
            "schema": (
                "maude.synthetic-operator.grader-live-probe-input.v1"
            ),
            "probe_id": probe_id,
            "fixture_id": fixture_id,
            "purpose": purpose,
            "expected_substantive_verdict": expected["verdict"],
            "expected_evidence_state": expected["evidence_state"],
            "expected_admission_if_procedure_compliant": "ACCEPTED",
            "model_visible_materials": [
                "grader-system.md",
                "grader-request.md",
                "bundle/evidence-packet.json",
                "bundle/items/* present files",
                "bundle/grader-output.schema.json",
            ],
            "deliberately_withheld": [
                "fixture.json",
                "grade.json",
                "expected oracle",
                "fixed raw stream",
                "fixture purpose beyond the live request",
                "Maude source",
                "campaign outputs",
                "repository access",
            ],
            "fresh_session_required": True,
            "follow_up_messages_permitted": False,
            "retry_permitted": False,
            "task_level_network_permitted": False,
            "authority_effect": "none",
            "members": members,
            "self_exclusion": (
                "input-manifest.json is excluded to avoid a recursive digest"
            ),
        }
        _write(root / "input-manifest.json", _pretty_bytes(manifest))
        records.append(
            {
                "probe_id": probe_id,
                "fixture_id": fixture_id,
                "purpose": purpose,
                "input_manifest": _record(root / "input-manifest.json"),
                "expected_substantive_verdict": expected["verdict"],
                "expected_evidence_state": expected["evidence_state"],
            }
        )
    plan = {
        "schema": "maude.synthetic-operator.grader-live-probe-plan.v1",
        "preparation_base_commit": _git("rev-parse", "HEAD"),
        "provider_config": "openai-sol",
        "provider": "OpenAI",
        "model": "gpt-5.6-sol",
        "model_family": "OpenAI",
        "reasoning_setting": "low",
        "provider_runtime": {
            "name": "codex-cli",
            "reported_version": reported_version,
            "host_entrypoint": _external_record(CODEX_HOST_ENTRYPOINT),
            "host_native_binary": _external_record(CODEX_HOST_NATIVE),
            "sandbox_entrypoint": "/opt/node/bin/codex",
            "sandbox_native_binary": (
                "/opt/node/lib/node_modules/@openai/codex/node_modules/"
                "@openai/codex-linux-x64/vendor/"
                "x86_64-unknown-linux-musl/bin/codex"
            ),
            "version_probe": {
                "argv": [str(CODEX_HOST_ENTRYPOINT), "--version"],
                "returncode": version_probe.returncode,
                "stdout": reported_version,
                "stderr_sha256": hashlib.sha256(
                    version_probe.stderr.encode("utf-8")
                ).hexdigest(),
            },
        },
        "mcp_protocol_version": "2025-06-18",
        "allowed_tool_roster": _record(roster),
        "grader_system_prompt": _record(system_prompt),
        "grader_request_template": _record(request_template),
        "grader_output_schema": _record(schema),
        "validator": _record(validator),
        "provider_integration": _record(provider_integration),
        "qualification_runner": _record(live_runner),
        "input_builder": _record(input_builder),
        "fixture_suite": _record(fixture_suite),
        "expected_oracles": [
            {
                "fixture_id": fixture_id,
                "record": _record(
                    QUALIFICATION_DIR / "expected" / f"{fixture_id}.json"
                ),
            }
            for _probe_id, fixture_id, _purpose in PROBES
        ],
        "probe_count": len(records),
        "timeout_seconds_per_probe": 600,
        "probes": records,
        "session_policy": {
            "genuinely_fresh": True,
            "one_session_per_probe": True,
            "no_resume": True,
            "no_follow_up": True,
            "no_coaching": True,
            "no_retry": True,
        },
        "network_scope": {
            "provider_transport_only": True,
            "grader_evidence_tool_network": False,
            "task_level_network": False,
            "external_operational_side_effects": False,
        },
        "known_provider_limitation": {
            "effective_tool_surface_equals_declared_roster": False,
            "observed_extra_capability": "codex/list_mcp_resources",
            "basis": (
                "Generation-four raw streams show the Codex-internal tool "
                "executed outside the configured grader MCP shim."
            ),
            "nonuse_in_live_sample_cannot_prove_absence": True,
        },
        "same_model_family_limitation": (
            "OpenAI gpt-5.6-sol is the frozen grader configuration; session "
            "freshness does not establish model-family independence."
        ),
        "generation_four_input": False,
        "generation_five_campaign": False,
        "maude_product_evaluation": False,
        "authority_effect": "none",
        "canonical_plan_sha256_basis": (
            "The plan excludes its own digest; all referenced inputs have "
            "independent byte counts and SHA-256 digests."
        ),
    }
    _write(PLAN, _pretty_bytes(plan))
    return plan


def main() -> int:
    plan = build()
    print(
        _canonical_bytes(
            {
                "probe_count": plan["probe_count"],
                "provider": plan["provider"],
                "model": plan["model"],
                "authority_effect": "none",
            }
        ).decode("utf-8")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
