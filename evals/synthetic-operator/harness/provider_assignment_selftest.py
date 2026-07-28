#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Provider-free regression checks for deterministic session assignment."""

from __future__ import annotations

import copy
import contextlib
import io
import json
import tempfile
from pathlib import Path
from typing import Any

import campaign_common
import finalize_provider_assignments as finalizer
from campaign_common import CampaignError, file_record


PROVIDERS = list(campaign_common.SUPPORTED_PROVIDER_CONFIGS)
OPENAI = "openai-sol"
ANTHROPIC = "anthropic-sonnet"


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _policy() -> dict[str, Any]:
    return copy.deepcopy(finalizer.EXPECTED_PROVIDER_CAPABILITY_POLICY)


def _surface_index(
    *,
    probe_root: Path,
    schema: str,
    successful: set[str],
    identity_prefix: str,
    policy_record: dict[str, Any],
) -> dict[str, Any]:
    unavailable = [provider for provider in PROVIDERS if provider not in successful]
    outcomes: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    for provider in PROVIDERS:
        provider_root = probe_root / provider
        if provider in successful:
            identity = {
                "provider_session_id": f"{identity_prefix}-{provider}",
            }
            result = {
                "provider_config": provider,
                "status": "available",
                "model_configuration": (
                    campaign_common.PROVIDER_MODEL_CONFIGS[provider]
                ),
                "campaign_run": False,
                "session_identity": identity,
                "authority_effect": "none",
            }
            result_path = provider_root / "result.json"
            _write_json(result_path, result)
            results.append(result)
            outcomes.append(
                {
                    "provider_config": provider,
                    "status": "available",
                    "result": file_record(
                        result_path,
                        relative_to=probe_root,
                    ),
                    "session_identity": identity,
                    "authority_effect": "none",
                }
            )
        else:
            failure = {
                "schema": (
                    "maude.synthetic-operator.provider-capability-failure.v1"
                ),
                "provider_config": provider,
                "model_configuration": (
                    campaign_common.PROVIDER_MODEL_CONFIGS[provider]
                ),
                "campaign_run": False,
                "status": "provider-capability-unavailable",
                "failure_classification": "provider-capability-unavailable",
                "session_identity": {},
                "partial_evidence_preserved": True,
                "authority_effect": "none",
            }
            failure_path = provider_root / "failure.json"
            _write_json(failure_path, failure)
            outcomes.append(
                {
                    "provider_config": provider,
                    "status": "provider-capability-unavailable",
                    "failure": file_record(
                        failure_path,
                        relative_to=probe_root,
                    ),
                    "session_identity": {},
                    "authority_effect": "none",
                }
            )
    return {
        "schema": schema,
        "campaign_id": campaign_common.CAMPAIGN_ID,
        "campaign_run": False,
        "requested_provider_configs": PROVIDERS,
        "not_requested_provider_configs": [],
        "successful_provider_configs": [
            provider for provider in PROVIDERS if provider in successful
        ],
        "unavailable_provider_configs": unavailable,
        "failed_provider_configs": unavailable,
        "invalid_probe_provider_configs": [],
        "provider_model_configurations": {
            provider: campaign_common.PROVIDER_MODEL_CONFIGS[provider]
            for provider in PROVIDERS
        },
        "all_requested_provider_attempts_recorded": True,
        "capability_observation_valid": True,
        "provider_capability_policy": policy_record,
        "providers": results,
        "provider_outcomes": outcomes,
        "all_passed": not unavailable,
        "authority_effect": "none",
    }


def _grader_index(
    *,
    probe_root: Path,
    ordinary: set[str],
    installation: set[str],
    policy_record: dict[str, Any],
) -> dict[str, Any]:
    outcomes: list[dict[str, Any]] = []
    successful_pairs: list[str] = []
    unavailable_pairs: list[str] = []
    for provider in PROVIDERS:
        for probe_id, successful in (
            (finalizer.ORDINARY_GRADER_PROBE_ID, ordinary),
            (finalizer.INSTALLATION_GRADER_PROBE_ID, installation),
        ):
            surface = (
                "maude"
                if probe_id == finalizer.ORDINARY_GRADER_PROBE_ID
                else "maude-installation"
            )
            provider_root = probe_root / provider / probe_id
            if provider in successful:
                identity = {
                    "provider_session_id": (
                        f"grader-{probe_id}-{provider}"
                    ),
                }
                result = {
                    "schema": (
                        "maude.synthetic-operator."
                        "grader-surface-probe-result.v1"
                    ),
                    "campaign_id": campaign_common.CAMPAIGN_ID,
                    "provider_config": provider,
                    "probe_id": probe_id,
                    "status": "available",
                    "model_configuration": (
                        campaign_common.PROVIDER_MODEL_CONFIGS[provider]
                    ),
                    "campaign_run": False,
                    "session_identity": identity,
                    "all_passed": True,
                    "authority_effect": "none",
                }
                result_path = provider_root / "result.json"
                _write_json(result_path, result)
                outcomes.append(
                    {
                        "provider_config": provider,
                        "probe_id": probe_id,
                        "surface": surface,
                        "status": "available",
                        "session_identity": identity,
                        "result": file_record(
                            result_path,
                            relative_to=probe_root,
                        ),
                        "campaign_run": False,
                        "authority_effect": "none",
                    }
                )
                successful_pairs.append(f"{provider}/{probe_id}")
            else:
                failure = {
                    "schema": (
                        "maude.synthetic-operator."
                        "grader-surface-probe-failure.v1"
                    ),
                    "campaign_id": campaign_common.CAMPAIGN_ID,
                    "probe_id": probe_id,
                    "provider_config": provider,
                    "model_configuration": (
                        campaign_common.PROVIDER_MODEL_CONFIGS[provider]
                    ),
                    "campaign_run": False,
                    "status": "provider-capability-unavailable",
                    "failure_classification": (
                        "provider-capability-unavailable"
                    ),
                    "session_identity": {},
                    "partial_evidence_preserved": True,
                    "all_passed": False,
                    "authority_effect": "none",
                }
                failure_path = provider_root / "failure.json"
                _write_json(failure_path, failure)
                outcomes.append(
                    {
                        "provider_config": provider,
                        "probe_id": probe_id,
                        "surface": surface,
                        "status": "provider-capability-unavailable",
                        "session_identity": {},
                        "failure": file_record(
                            failure_path,
                            relative_to=probe_root,
                        ),
                        "campaign_run": False,
                        "authority_effect": "none",
                    }
                )
                unavailable_pairs.append(f"{provider}/{probe_id}")
    return {
        "schema": "maude.synthetic-operator.grader-surface-probes.v2",
        "campaign_id": campaign_common.CAMPAIGN_ID,
        "campaign_run": False,
        "requested_provider_configs": PROVIDERS,
        "not_requested_provider_configs": [],
        "all_requested_provider_probe_attempts_recorded": True,
        "capability_observation_valid": True,
        "invalid_probe_pairs": [],
        "provider_model_configurations": {
            provider: campaign_common.PROVIDER_MODEL_CONFIGS[provider]
            for provider in PROVIDERS
        },
        "provider_capability_policy": policy_record,
        "provider_probe_outcomes": outcomes,
        "successful_provider_probe_pairs": successful_pairs,
        "failed_provider_probe_pairs": unavailable_pairs,
        "unavailable_provider_probe_pairs": unavailable_pairs,
        "all_passed": not unavailable_pairs,
        "authority_effect": "none",
    }


def _configure_case(
    root: Path,
    *,
    auth: set[str],
    installation: set[str],
    ordinary_graders: set[str],
    installation_graders: set[str],
) -> dict[str, Any]:
    packet = root / "packet"
    policy_path = packet / "provider-capability-policy.json"
    auth_path = packet / "provider-capability-probes" / "auth" / "index.json"
    install_path = (
        packet
        / "provider-capability-probes"
        / "installation"
        / "index.json"
    )
    grader_path = packet / "grader-surface-probes" / "index.json"
    _write_json(policy_path, _policy())
    policy_record = file_record(policy_path, relative_to=packet)
    _write_json(
        auth_path,
        _surface_index(
            probe_root=auth_path.parent,
            schema="maude.synthetic-operator.provider-auth-gate-probes.v2",
            successful=auth,
            identity_prefix="auth",
            policy_record=policy_record,
        ),
    )
    _write_json(
        install_path,
        _surface_index(
            probe_root=install_path.parent,
            schema="maude.synthetic-operator.installation-surface-probes.v3",
            successful=installation,
            identity_prefix="installation",
            policy_record=policy_record,
        ),
    )
    _write_json(
        grader_path,
        _grader_index(
            probe_root=grader_path.parent,
            ordinary=ordinary_graders,
            installation=installation_graders,
            policy_record=policy_record,
        ),
    )
    finalizer.PACKET_DIR = packet
    finalizer.PROVIDER_CAPABILITY_POLICY_PATH = policy_path
    finalizer.AUTH_GATE_PROBE_PATH = auth_path
    finalizer.INSTALL_SURFACE_PROBE_PATH = install_path
    finalizer.GRADER_PROBE_PATH = grader_path
    return {
        "auth": json.loads(auth_path.read_text(encoding="utf-8")),
        "installation": json.loads(install_path.read_text(encoding="utf-8")),
        "grader": json.loads(grader_path.read_text(encoding="utf-8")),
    }


def _ordinary_runs(matrix: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(
        (
            run
            for run in matrix["runs"]
            if run.get("surface") == "maude"
        ),
        key=lambda run: run["run_id"],
    )


def _installation_runs(matrix: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(
        (
            run
            for run in matrix["runs"]
            if run.get("surface") == "maude-installation"
        ),
        key=lambda run: run["run_id"],
    )


def _assert_raises(action: Any, expected: str) -> None:
    try:
        action()
    except CampaignError as exc:
        if expected not in str(exc):
            raise AssertionError(
                f"expected error containing {expected!r}, got {exc!r}"
            ) from exc
    else:
        raise AssertionError(f"expected CampaignError containing {expected!r}")


def _assert_matrix_valid(matrix: dict[str, Any]) -> None:
    errors = campaign_common.validate_matrix(matrix)
    if errors:
        raise AssertionError(
            "derived matrix failed shared validation: " + "; ".join(errors)
        )


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _rewrite_surface_success_identity(
    *,
    index_path: Path,
    index: dict[str, Any],
    provider: str,
    identity: dict[str, str],
) -> None:
    outcome = next(
        value
        for value in index["provider_outcomes"]
        if value["provider_config"] == provider
    )
    result_path = index_path.parent / outcome["result"]["path"]
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["session_identity"] = identity
    _write_json(result_path, result)
    outcome["session_identity"] = identity
    outcome["result"] = file_record(
        result_path,
        relative_to=index_path.parent,
    )
    provider_result = next(
        value
        for value in index["providers"]
        if value["provider_config"] == provider
    )
    provider_result["session_identity"] = identity
    _write_json(index_path, index)


def _rewrite_surface_failure_identity(
    *,
    index_path: Path,
    index: dict[str, Any],
    provider: str,
    identity: dict[str, str],
) -> None:
    outcome = next(
        value
        for value in index["provider_outcomes"]
        if value["provider_config"] == provider
    )
    failure_path = index_path.parent / outcome["failure"]["path"]
    failure = json.loads(failure_path.read_text(encoding="utf-8"))
    failure["session_identity"] = identity
    _write_json(failure_path, failure)
    outcome["session_identity"] = identity
    outcome["failure"] = file_record(
        failure_path,
        relative_to=index_path.parent,
    )
    _write_json(index_path, index)


def main() -> int:
    template = campaign_common.load_json(campaign_common.MATRIX_PATH)
    checks = 0
    with tempfile.TemporaryDirectory(
        prefix="maude-provider-assignment-selftest-"
    ) as temp:
        root = Path(temp)

        _configure_case(
            root / "all-capable",
            auth=set(PROVIDERS),
            installation=set(PROVIDERS),
            ordinary_graders=set(PROVIDERS),
            installation_graders=set(PROVIDERS),
        )
        all_capable = finalizer.derive_matrix(copy.deepcopy(template))
        _assert_matrix_valid(all_capable)
        ordinary = _ordinary_runs(all_capable)
        installation = _installation_runs(all_capable)
        _require(
            [
                run["operator_model_config"] for run in ordinary[:4]
            ]
            == [OPENAI, ANTHROPIC, OPENAI, ANTHROPIC],
            "all-capable operator assignments do not alternate",
        )
        _require(
            all(
                run["operator_model_config"] != run["grader_model_config"]
                for run in ordinary + installation
            ),
            "all-capable assignments do not use opposite-family graders",
        )
        by_id = {run["run_id"]: run for run in all_capable["runs"]}
        for direct_id in campaign_common.DIRECT_RUN_IDS:
            direct = by_id[direct_id]
            peer = by_id[direct["compares_to_run_id"]]
            _require(
                direct["operator_model_config"]
                == peer["operator_model_config"],
                f"{direct_id}: operator assignment does not mirror peer",
            )
            _require(
                direct["grader_model_config"] == peer["grader_model_config"],
                f"{direct_id}: grader assignment does not mirror peer",
            )
        _require(
            all_capable["model_family_policy"]["cross_family_grading_used"]
            is True,
            "all-capable policy omits cross-family grading",
        )
        _require(
            all_capable["model_family_policy"]["same_family_grading"]
            is False,
            "all-capable policy incorrectly records same-family grading",
        )
        checks += 1

        _configure_case(
            root / "openai-only",
            auth={OPENAI},
            installation={OPENAI},
            ordinary_graders={OPENAI},
            installation_graders={OPENAI},
        )
        openai_only = finalizer.derive_matrix(copy.deepcopy(template))
        _assert_matrix_valid(openai_only)
        _require(
            all(
                run["operator_model_config"] == OPENAI
                and run["grader_model_config"] == OPENAI
                for run in openai_only["runs"]
            ),
            "single-provider assignments used an unavailable provider",
        )
        _require(
            openai_only["model_family_policy"][
                "same_model_configuration_grading"
            ]
            is True,
            "single-provider policy omits same-configuration grading",
        )
        _require(
            openai_only["model_family_policy"]["cross_family_grading_used"]
            is False,
            "single-provider policy claims cross-family grading",
        )
        checks += 1

        _configure_case(
            root / "role-specific",
            auth=set(PROVIDERS),
            installation={OPENAI},
            ordinary_graders=set(PROVIDERS),
            installation_graders={ANTHROPIC},
        )
        role_specific = finalizer.derive_matrix(copy.deepcopy(template))
        _assert_matrix_valid(role_specific)
        _require(
            all(
                run["operator_model_config"] == OPENAI
                and run["grader_model_config"] == ANTHROPIC
                for run in _installation_runs(role_specific)
            ),
            "role-specific installation assignments differ",
        )
        eligibility = role_specific["model_family_policy"][
            "provider_role_eligibility"
        ]
        _require(
            eligibility[ANTHROPIC]["installation_operator"] is False,
            "unproved Anthropic installation-operator role was admitted",
        )
        _require(
            eligibility[OPENAI]["installation_grader"] is False,
            "unproved OpenAI installation-grader role was admitted",
        )
        checks += 1

        indices = _configure_case(
            root / "invalid",
            auth=set(PROVIDERS),
            installation=set(PROVIDERS),
            ordinary_graders=set(PROVIDERS),
            installation_graders=set(PROVIDERS),
        )
        invalid = indices["auth"]
        invalid["invalid_probe_provider_configs"] = [ANTHROPIC]
        _write_json(finalizer.AUTH_GATE_PROBE_PATH, invalid)
        _assert_raises(
            lambda: finalizer.derive_matrix(copy.deepcopy(template)),
            "auth/isolation capability index is invalid",
        )
        checks += 1

        indices = _configure_case(
            root / "reused-session",
            auth=set(PROVIDERS),
            installation=set(PROVIDERS),
            ordinary_graders=set(PROVIDERS),
            installation_graders=set(PROVIDERS),
        )
        install_index = indices["installation"]
        reused_identity = copy.deepcopy(
            indices["auth"]["provider_outcomes"][0]["session_identity"]
        )
        _rewrite_surface_success_identity(
            index_path=finalizer.INSTALL_SURFACE_PROBE_PATH,
            index=install_index,
            provider=OPENAI,
            identity=reused_identity,
        )
        _assert_raises(
            lambda: finalizer.derive_matrix(copy.deepcopy(template)),
            "reused a session identity",
        )
        checks += 1

        indices = _configure_case(
            root / "missing-session",
            auth=set(PROVIDERS),
            installation=set(PROVIDERS),
            ordinary_graders=set(PROVIDERS),
            installation_graders=set(PROVIDERS),
        )
        _rewrite_surface_success_identity(
            index_path=finalizer.AUTH_GATE_PROBE_PATH,
            index=indices["auth"],
            provider=OPENAI,
            identity={},
        )
        _assert_raises(
            lambda: finalizer.derive_matrix(copy.deepcopy(template)),
            "must contain exactly one provider session identity",
        )
        checks += 1

        indices = _configure_case(
            root / "summary-contradiction",
            auth=set(PROVIDERS),
            installation=set(PROVIDERS),
            ordinary_graders=set(PROVIDERS),
            installation_graders=set(PROVIDERS),
        )
        contradiction = indices["auth"]
        contradiction["successful_provider_configs"] = [OPENAI]
        contradiction["unavailable_provider_configs"] = [ANTHROPIC]
        contradiction["failed_provider_configs"] = [ANTHROPIC]
        _write_json(finalizer.AUTH_GATE_PROBE_PATH, contradiction)
        _assert_raises(
            lambda: finalizer.derive_matrix(copy.deepcopy(template)),
            "capability summaries contradict outcomes",
        )
        checks += 1

        _configure_case(
            root / "incomplete-policy",
            auth=set(PROVIDERS),
            installation=set(PROVIDERS),
            ordinary_graders=set(PROVIDERS),
            installation_graders=set(PROVIDERS),
        )
        incomplete_policy = _policy()
        del incomplete_policy["capability_rules"]
        _write_json(
            finalizer.PROVIDER_CAPABILITY_POLICY_PATH,
            incomplete_policy,
        )
        _assert_raises(
            lambda: finalizer.derive_matrix(copy.deepcopy(template)),
            "differs from the exact predeclared rule",
        )
        checks += 1

        _configure_case(
            root / "deterministic-tamper",
            auth=set(PROVIDERS),
            installation=set(PROVIDERS),
            ordinary_graders=set(PROVIDERS),
            installation_graders=set(PROVIDERS),
        )
        tampered = finalizer.derive_matrix(copy.deepcopy(template))
        tampered_by_id = {
            run["run_id"]: run for run in tampered["runs"]
        }
        tampered_by_id["maude-s01"]["grader_model_config"] = OPENAI
        direct_peer = next(
            run
            for run in tampered["runs"]
            if run.get("compares_to_run_id") == "maude-s01"
        )
        direct_peer["grader_model_config"] = OPENAI
        tampered["model_family_policy"]["same_family_grading"] = True
        tampered["model_family_policy"][
            "same_model_configuration_grading"
        ] = True
        _assert_matrix_valid(tampered)
        tampered_path = finalizer.PACKET_DIR / "tampered-matrix.json"
        _write_json(tampered_path, tampered)
        finalizer.MATRIX_PATH = tampered_path
        errors = finalizer.validate_finalized_matrix()
        _require(
            errors
            == ["run matrix provider assignments are not deterministic"],
            f"deterministic tamper returned unexpected errors: {errors!r}",
        )
        checks += 1

        _configure_case(
            root / "prewrite-failure",
            auth=set(PROVIDERS),
            installation=set(PROVIDERS),
            ordinary_graders=set(PROVIDERS),
            installation_graders=set(PROVIDERS),
        )
        invalid_template = copy.deepcopy(template)
        invalid_template["interpretation"] = "invalid on purpose"
        invalid_template["model_family_policy"] = {}
        prewrite_path = finalizer.PACKET_DIR / "prewrite-matrix.json"
        _write_json(prewrite_path, invalid_template)
        before = prewrite_path.read_bytes()
        finalizer.MATRIX_PATH = prewrite_path
        finalizer.MANIFEST_PATH = finalizer.PACKET_DIR / "absent-manifest.json"
        diagnostic = io.StringIO()
        with contextlib.redirect_stderr(diagnostic):
            write_status = finalizer.main(["--write"])
        _require(write_status == 1, "invalid matrix prewrite was accepted")
        _require(
            "failed shared validation before write" in diagnostic.getvalue(),
            "prewrite rejection diagnostic differs",
        )
        _require(
            prewrite_path.read_bytes() == before,
            "failed finalization modified the matrix",
        )
        checks += 1

        indices = _configure_case(
            root / "failed-session-reuse",
            auth=set(PROVIDERS),
            installation={ANTHROPIC},
            ordinary_graders=set(PROVIDERS),
            installation_graders=set(PROVIDERS),
        )
        failed_reused_identity = copy.deepcopy(
            indices["auth"]["provider_outcomes"][0]["session_identity"]
        )
        _rewrite_surface_failure_identity(
            index_path=finalizer.INSTALL_SURFACE_PROBE_PATH,
            index=indices["installation"],
            provider=OPENAI,
            identity=failed_reused_identity,
        )
        _assert_raises(
            lambda: finalizer.derive_matrix(copy.deepcopy(template)),
            "reused a session identity",
        )
        checks += 1

    print(
        json.dumps(
            {
                "schema": (
                    "maude.synthetic-operator."
                    "provider-assignment-selftest-result.v1"
                ),
                "campaign_id": campaign_common.CAMPAIGN_ID,
                "checks_passed": checks,
                "provider_sessions_started": 0,
                "task_network_used": False,
                "authority_effect": "none",
                "valid": True,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
