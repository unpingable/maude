#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Finalize the frozen run matrix from exact provider capability evidence.

This evaluator-only step runs after the predeclared capability probes and
before campaign freeze. It never starts a provider or product process.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

from campaign_common import (
    AUTH_GATE_PROBE_PATH,
    CAMPAIGN_ID,
    DIRECT_RUN_IDS,
    INSTALL_RUN_IDS,
    INSTALL_SURFACE_PROBE_PATH,
    MANIFEST_PATH,
    MATRIX_PATH,
    PACKET_DIR,
    PROVIDER_CAPABILITY_POLICY_PATH,
    PROVIDER_MODEL_CONFIGS,
    SUPPORTED_PROVIDER_CONFIGS,
    CampaignError,
    file_record,
    load_json,
    validate_matrix,
    write_json,
)


ASSIGNMENT_ALGORITHM = "maude-synthetic-provider-assignment-v1"
GRADER_PROBE_PATH = PACKET_DIR / "grader-surface-probes" / "index.json"
ORDINARY_GRADER_PROBE_ID = "ordinary"
INSTALLATION_GRADER_PROBE_ID = "installation"
EXPECTED_PROVIDER_CAPABILITY_POLICY = {
    "schema": "maude.synthetic-operator.provider-capability-policy.v1",
    "campaign_id": CAMPAIGN_ID,
    "candidate_provider_configs": list(SUPPORTED_PROVIDER_CONFIGS),
    "decision_rule_frozen_before_provider_probes": True,
    "capability_rules": {
        "basic_operator_eligibility": (
            "The provider's fresh auth/isolation probe must pass with a fresh "
            "session identity and the exact bounded terminal-tool contract."
        ),
        "installation_operator_eligibility": (
            "The provider must satisfy basic operator eligibility and its "
            "fresh installation-surface probe must pass."
        ),
        "ordinary_grader_eligibility": (
            "The provider must satisfy its fresh auth/isolation probe and a "
            "fresh ordinary-grader schema/surface probe."
        ),
        "installation_grader_eligibility": (
            "The provider must satisfy its fresh auth/isolation probe and a "
            "fresh installation-grader schema/surface probe."
        ),
        "binary_or_credential_presence_is_not_capability": True,
        "a_provider_failure_does_not_imply_another_provider_passed": True,
        "a_probe_integrity_failure_invalidates_preparation": True,
        "a_capability_failure_excludes_only_the_unsupported_provider_role": True,
        "at_least_one_operator_and_grader_path_must_remain": True,
    },
    "assignment_rules": {
        "when_both_families_are_fully_eligible": {
            "use_both_families_for_representative_ordinary_and_installation_runs": True,
            "prefer_opposite_family_independent_grading": True,
            "balance_assignments_deterministically": True,
        },
        "when_capability_is_partial": {
            "assign_only_roles_proved_by_the_corresponding_probe": True,
            "record_same_family_grading_where_unavoidable": True,
            "make_no_unsupported_cross_family_claim": True,
        },
        "direct_runtime_comparators_mirror_paired_maude_operator_and_grader_configs": True,
    },
    "freshness_and_retry": {
        "every_probe_uses_a_fresh_provider_process": True,
        "a_session_counts_as_fresh_only_with_a_provider_session_identity": True,
        "no_resume_continuation_or_follow_up": True,
        "maximum_attempts_per_provider_and_probe_kind_in_this_campaign_id": 1,
        "failed_and_partial_attempts_must_be_preserved": True,
        "retry_after_any_attempt_requires_a_new_campaign_generation": True,
    },
    "network_and_effect_boundary": {
        "provider_network_permitted_for_capability_probes_and_later_fresh_campaign_sessions": True,
        "locally_configured_provider_credentials_permitted_only_for_provider_session_transport": True,
        "task_level_network_permitted": False,
        "production_task_systems_or_credentials_permitted": False,
        "external_operational_side_effects_permitted": False,
        "synthetic_local_fixture_effects_only": True,
    },
    "campaign_evidence_boundary": {
        "capability_probe_sessions_count_as_campaign_runs": False,
        "capability_probe_sessions_count_toward_role_or_scenario_coverage": False,
        "capability_probe_sessions_count_as_independent_grades": False,
    },
    "authority_effect": "none",
}


def _require_capability_policy() -> dict[str, Any]:
    policy = load_json(PROVIDER_CAPABILITY_POLICY_PATH)
    if policy != EXPECTED_PROVIDER_CAPABILITY_POLICY:
        raise CampaignError(
            "provider capability policy differs from the exact predeclared rule"
        )
    return policy


def _verified_file_record(
    record: Any,
    *,
    base: Path,
    label: str,
) -> Path:
    if not isinstance(record, dict) or not isinstance(record.get("path"), str):
        raise CampaignError(f"{label} file record is malformed")
    relative = Path(record["path"])
    if relative.is_absolute() or ".." in relative.parts:
        raise CampaignError(f"{label} file-record path is unsafe")
    path = base / relative
    if (
        not path.is_file()
        or path.is_symlink()
        or record != file_record(path, relative_to=base)
    ):
        raise CampaignError(f"{label} file record differs from exact bytes")
    return path


def _session_identity(
    value: Any,
    *,
    label: str,
) -> str:
    if not isinstance(value, dict):
        raise CampaignError(f"{label} provider session identity is malformed")
    identities = [
        candidate
        for candidate in (
            value.get("provider_session_id"),
            value.get("provider_thread_id"),
        )
        if isinstance(candidate, str) and candidate
    ]
    if len(identities) != 1:
        raise CampaignError(
            f"{label} must contain exactly one provider session identity"
        )
    return identities[0]


def _optional_session_identity(
    value: Any,
    *,
    label: str,
) -> str | None:
    if value in ({}, None):
        return None
    return _session_identity(value, label=label)


def _successful_provider_set(
    path: Path,
    *,
    expected_schema: str,
    label: str,
) -> tuple[set[str], dict[str, Any]]:
    index = load_json(path)
    candidates = list(SUPPORTED_PROVIDER_CONFIGS)
    probe_root = path.parent
    if (
        not isinstance(index, dict)
        or index.get("schema") != expected_schema
        or index.get("campaign_id") != CAMPAIGN_ID
        or index.get("campaign_run") is not False
        or index.get("requested_provider_configs") != candidates
        or index.get("not_requested_provider_configs") != []
        or index.get("all_requested_provider_attempts_recorded") is not True
        or index.get("capability_observation_valid") is not True
        or index.get("invalid_probe_provider_configs") != []
        or index.get("provider_model_configurations")
        != {
            provider: PROVIDER_MODEL_CONFIGS[provider]
            for provider in candidates
        }
        or index.get("provider_capability_policy")
        != file_record(
            PROVIDER_CAPABILITY_POLICY_PATH,
            relative_to=PACKET_DIR,
        )
        or index.get("authority_effect") != "none"
    ):
        raise CampaignError(f"{label} capability index is invalid")
    successful = index.get("successful_provider_configs")
    unavailable = index.get("unavailable_provider_configs")
    failed = index.get("failed_provider_configs")
    outcomes = index.get("provider_outcomes")
    providers = index.get("providers")
    if (
        not isinstance(successful, list)
        or not isinstance(unavailable, list)
        or not isinstance(outcomes, list)
        or not isinstance(providers, list)
        or failed != unavailable
        or set(successful) | set(unavailable) != set(candidates)
        or set(successful) & set(unavailable)
        or successful
        != [value for value in candidates if value in set(successful)]
        or unavailable
        != [value for value in candidates if value in set(unavailable)]
    ):
        raise CampaignError(f"{label} capability outcome partition differs")
    if (
        len(outcomes) != len(candidates)
        or not all(isinstance(outcome, dict) for outcome in outcomes)
        or [outcome.get("provider_config") for outcome in outcomes]
        != candidates
    ):
        raise CampaignError(f"{label} capability outcomes are incomplete")

    result_by_provider: dict[str, dict[str, Any]] = {}
    identities: set[str] = set()
    derived_successful: list[str] = []
    derived_unavailable: list[str] = []
    for outcome in outcomes:
        provider = str(outcome["provider_config"])
        status = outcome.get("status")
        if outcome.get("authority_effect") != "none":
            raise CampaignError(f"{label}/{provider} authority effect differs")
        if status == "available":
            if set(outcome) != {
                "provider_config",
                "status",
                "result",
                "session_identity",
                "authority_effect",
            }:
                raise CampaignError(
                    f"{label}/{provider} success outcome shape differs"
                )
            result_path = _verified_file_record(
                outcome["result"],
                base=probe_root,
                label=f"{label}/{provider} result",
            )
            result = load_json(result_path)
            identity = outcome.get("session_identity")
            identity_value = _session_identity(
                identity,
                label=f"{label}/{provider}",
            )
            if identity_value in identities:
                raise CampaignError(
                    f"{label} capability probes reused a session identity"
                )
            identities.add(identity_value)
            if (
                result.get("provider_config") != provider
                or result.get("status") != "available"
                or result.get("model_configuration")
                != PROVIDER_MODEL_CONFIGS[provider]
                or result.get("campaign_run") is not False
                or result.get("session_identity") != identity
                or result.get("authority_effect") != "none"
            ):
                raise CampaignError(
                    f"{label}/{provider} result identity differs"
                )
            result_by_provider[provider] = result
            derived_successful.append(provider)
        elif status == "provider-capability-unavailable":
            if set(outcome) != {
                "provider_config",
                "status",
                "failure",
                "session_identity",
                "authority_effect",
            }:
                raise CampaignError(
                    f"{label}/{provider} failure outcome shape differs"
                )
            failure_path = _verified_file_record(
                outcome["failure"],
                base=probe_root,
                label=f"{label}/{provider} failure",
            )
            failure = load_json(failure_path)
            if (
                failure.get("schema")
                != "maude.synthetic-operator.provider-capability-failure.v1"
                or failure.get("provider_config") != provider
                or failure.get("model_configuration")
                != PROVIDER_MODEL_CONFIGS[provider]
                or failure.get("campaign_run") is not False
                or failure.get("status") != status
                or failure.get("failure_classification") != status
                or failure.get("session_identity")
                != outcome.get("session_identity")
                or failure.get("partial_evidence_preserved") is not True
                or failure.get("authority_effect") != "none"
            ):
                raise CampaignError(
                    f"{label}/{provider} capability failure differs"
                )
            _optional_session_identity(
                outcome.get("session_identity"),
                label=f"{label}/{provider} failure",
            )
            derived_unavailable.append(provider)
        else:
            raise CampaignError(
                f"{label}/{provider} capability status is inadmissible"
            )
    provider_by_config = {
        result.get("provider_config"): result
        for result in providers
        if isinstance(result, dict)
    }
    if (
        len(provider_by_config) != len(providers)
        or provider_by_config != result_by_provider
        or successful != derived_successful
        or unavailable != derived_unavailable
        or index.get("all_passed") is not (not bool(derived_unavailable))
    ):
        raise CampaignError(f"{label} capability summaries contradict outcomes")
    return set(successful), index


def _grader_provider_sets() -> tuple[dict[str, set[str]], dict[str, Any]]:
    index = load_json(GRADER_PROBE_PATH)
    candidates = list(SUPPORTED_PROVIDER_CONFIGS)
    probe_root = GRADER_PROBE_PATH.parent
    if (
        not isinstance(index, dict)
        or index.get("schema")
        != "maude.synthetic-operator.grader-surface-probes.v2"
        or index.get("campaign_id") != CAMPAIGN_ID
        or index.get("campaign_run") is not False
        or index.get("requested_provider_configs") != candidates
        or index.get("not_requested_provider_configs") != []
        or index.get(
            "all_requested_provider_probe_attempts_recorded"
        )
        is not True
        or index.get("capability_observation_valid") is not True
        or index.get("invalid_probe_pairs") != []
        or index.get("provider_model_configurations")
        != {
            provider: PROVIDER_MODEL_CONFIGS[provider]
            for provider in candidates
        }
        or index.get("provider_capability_policy")
        != file_record(
            PROVIDER_CAPABILITY_POLICY_PATH,
            relative_to=PACKET_DIR,
        )
        or index.get("authority_effect") != "none"
    ):
        raise CampaignError("grader capability index is invalid")
    outcomes = index.get("provider_probe_outcomes")
    if not isinstance(outcomes, list):
        raise CampaignError("grader capability outcomes are absent")
    expected_pair_order = [
        (provider, probe_id)
        for provider in candidates
        for probe_id in (
            ORDINARY_GRADER_PROBE_ID,
            INSTALLATION_GRADER_PROBE_ID,
        )
    ]
    expected_pairs = set(expected_pair_order)
    observed_pairs: list[tuple[Any, Any]] = []
    successful_pairs: list[str] = []
    unavailable_pairs: list[str] = []
    identities: set[str] = set()
    available = {
        ORDINARY_GRADER_PROBE_ID: set(),
        INSTALLATION_GRADER_PROBE_ID: set(),
    }
    for outcome in outcomes:
        if not isinstance(outcome, dict):
            raise CampaignError("grader capability outcome is malformed")
        pair = (
            outcome.get("provider_config"),
            outcome.get("probe_id"),
        )
        observed_pairs.append(pair)
        provider, probe_id = pair
        label = f"{provider}/{probe_id}"
        expected_surface = (
            "maude"
            if probe_id == ORDINARY_GRADER_PROBE_ID
            else "maude-installation"
        )
        if (
            provider not in candidates
            or probe_id not in available
            or outcome.get("surface") != expected_surface
            or outcome.get("campaign_run") is not False
            or outcome.get("authority_effect") != "none"
        ):
            raise CampaignError(f"grader capability outcome differs: {label}")
        if outcome.get("status") == "available":
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
                raise CampaignError(
                    f"grader capability success shape differs: {label}"
                )
            result_path = _verified_file_record(
                outcome["result"],
                base=probe_root,
                label=f"grader capability result {label}",
            )
            result = load_json(result_path)
            identity = outcome.get("session_identity")
            identity_value = _session_identity(
                identity,
                label=f"grader capability {label}",
            )
            if identity_value in identities:
                raise CampaignError(
                    "grader capability probes reused a session identity"
                )
            identities.add(identity_value)
            if (
                result.get("schema")
                != "maude.synthetic-operator.grader-surface-probe-result.v1"
                or result.get("campaign_id") != CAMPAIGN_ID
                or result.get("probe_id") != probe_id
                or result.get("provider_config") != provider
                or result.get("model_configuration")
                != PROVIDER_MODEL_CONFIGS[provider]
                or result.get("status") != "available"
                or result.get("campaign_run") is not False
                or result.get("session_identity") != identity
                or result.get("all_passed") is not True
                or result.get("authority_effect") != "none"
            ):
                raise CampaignError(
                    f"grader capability result identity differs: {label}"
                )
            available[str(probe_id)].add(str(provider))
            successful_pairs.append(label)
        elif outcome.get("status") == "provider-capability-unavailable":
            if set(outcome) != {
                "provider_config",
                "probe_id",
                "surface",
                "status",
                "failure",
                "session_identity",
                "campaign_run",
                "authority_effect",
            }:
                raise CampaignError(
                    f"grader capability failure shape differs: {label}"
                )
            failure_path = _verified_file_record(
                outcome["failure"],
                base=probe_root,
                label=f"grader capability failure {label}",
            )
            failure = load_json(failure_path)
            if (
                failure.get("schema")
                != "maude.synthetic-operator.grader-surface-probe-failure.v1"
                or failure.get("campaign_id") != CAMPAIGN_ID
                or failure.get("probe_id") != probe_id
                or failure.get("provider_config") != provider
                or failure.get("model_configuration")
                != PROVIDER_MODEL_CONFIGS[provider]
                or failure.get("campaign_run") is not False
                or failure.get("status")
                != "provider-capability-unavailable"
                or failure.get("failure_classification")
                != "provider-capability-unavailable"
                or failure.get("session_identity")
                != outcome.get("session_identity")
                or failure.get("partial_evidence_preserved") is not True
                or failure.get("all_passed") is not False
                or failure.get("authority_effect") != "none"
            ):
                raise CampaignError(
                    f"grader capability failure differs: {label}"
                )
            _optional_session_identity(
                outcome.get("session_identity"),
                label=f"grader capability failure {label}",
            )
            unavailable_pairs.append(label)
        else:
            raise CampaignError("grader capability failure is not admissible")
    if (
        observed_pairs != expected_pair_order
        or set(observed_pairs) != expected_pairs
        or index.get("successful_provider_probe_pairs")
        != successful_pairs
        or index.get("failed_provider_probe_pairs") != unavailable_pairs
        or index.get("unavailable_provider_probe_pairs")
        != unavailable_pairs
        or index.get("all_passed") is not (not bool(unavailable_pairs))
    ):
        raise CampaignError("grader capability outcome pairs differ")
    return available, index


def _session_identity_values(index: dict[str, Any]) -> list[str]:
    identities: list[str] = []
    for key in ("provider_outcomes", "provider_probe_outcomes"):
        outcomes = index.get(key)
        if not isinstance(outcomes, list):
            continue
        for outcome in outcomes:
            if not isinstance(outcome, dict):
                continue
            label = (
                f"{outcome.get('provider_config')}/"
                f"{outcome.get('probe_id', 'operator')}"
            )
            identity = _optional_session_identity(
                outcome.get("session_identity"),
                label=label,
            )
            if outcome.get("status") == "available" and identity is None:
                raise CampaignError(
                    f"{label} successful probe lacks a session identity"
                )
            if identity is not None:
                identities.append(identity)
    return identities


def _ordered(values: set[str]) -> list[str]:
    return [
        provider
        for provider in SUPPORTED_PROVIDER_CONFIGS
        if provider in values
    ]


def _family(provider: str) -> str:
    return str(PROVIDER_MODEL_CONFIGS[provider]["expected_family"])


def _alternate(providers: list[str], ordinal: int) -> str:
    if not providers:
        raise CampaignError("no eligible provider remains for a run role")
    return providers[ordinal % len(providers)]


def _grader_for(
    operator: str,
    eligible: list[str],
    *,
    ordinal: int,
) -> str:
    cross_family = [
        provider
        for provider in eligible
        if _family(provider) != _family(operator)
    ]
    return _alternate(cross_family or eligible, ordinal)


def _limitation(
    eligibility: dict[str, dict[str, bool]],
    *,
    same_family_used: bool,
    cross_family_used: bool,
) -> str:
    missing = [
        f"{provider}:{role}"
        for provider in SUPPORTED_PROVIDER_CONFIGS
        for role, available in eligibility[provider].items()
        if not available
    ]
    if not missing and cross_family_used and not same_family_used:
        return (
            "Both provider families passed every required capability surface. "
            "Every run uses a separate fresh opposite-family grader."
        )
    details = ", ".join(missing) if missing else "none"
    return (
        "Provider eligibility is role-specific. Unsupported provider/role "
        f"pairs: {details}. Same-family grading used: "
        f"{str(same_family_used).lower()}; cross-family grading used: "
        f"{str(cross_family_used).lower()}. No unsupported family comparison "
        "is claimed."
    )


def derive_matrix(matrix: dict[str, Any]) -> dict[str, Any]:
    """Derive exact assignments from frozen capability indices."""

    _require_capability_policy()
    auth, auth_index = _successful_provider_set(
        AUTH_GATE_PROBE_PATH,
        expected_schema=(
            "maude.synthetic-operator.provider-auth-gate-probes.v2"
        ),
        label="auth/isolation",
    )
    installation, installation_index = _successful_provider_set(
        INSTALL_SURFACE_PROBE_PATH,
        expected_schema=(
            "maude.synthetic-operator.installation-surface-probes.v3"
        ),
        label="installation surface",
    )
    grader, grader_index = _grader_provider_sets()
    all_identities = [
        *_session_identity_values(auth_index),
        *_session_identity_values(installation_index),
        *_session_identity_values(grader_index),
    ]
    if len(all_identities) != len(set(all_identities)):
        raise CampaignError("provider capability probes reused a session identity")

    ordinary_operators = auth
    installation_operators = auth & installation
    ordinary_graders = auth & grader[ORDINARY_GRADER_PROBE_ID]
    installation_graders = (
        auth & grader[INSTALLATION_GRADER_PROBE_ID]
    )
    if not all(
        (
            ordinary_operators,
            installation_operators,
            ordinary_graders,
            installation_graders,
        )
    ):
        raise CampaignError(
            "no complete operator/grader path remains for every run surface"
        )

    result = copy.deepcopy(matrix)
    if (
        not isinstance(result, dict)
        or result.get("campaign_id") != CAMPAIGN_ID
        or not isinstance(result.get("runs"), list)
    ):
        raise CampaignError("run matrix template identity differs")
    runs = result["runs"]
    run_by_id = {
        run.get("run_id"): run
        for run in runs
        if isinstance(run, dict)
        and isinstance(run.get("run_id"), str)
    }
    if len(run_by_id) != len(runs):
        raise CampaignError("run matrix template has duplicate/malformed runs")

    ordinary_operator_order = _ordered(ordinary_operators)
    installation_operator_order = _ordered(installation_operators)
    ordinary_grader_order = _ordered(ordinary_graders)
    installation_grader_order = _ordered(installation_graders)

    ordinary_runs = sorted(
        (
            run
            for run in runs
            if run.get("surface") == "maude"
        ),
        key=lambda run: run["run_id"],
    )
    for ordinal, run in enumerate(ordinary_runs):
        operator = _alternate(ordinary_operator_order, ordinal)
        run["operator_model_config"] = operator
        run["grader_model_config"] = _grader_for(
            operator,
            ordinary_grader_order,
            ordinal=ordinal,
        )
    for direct_id in DIRECT_RUN_IDS:
        direct = run_by_id.get(direct_id)
        if not isinstance(direct, dict):
            raise CampaignError(f"direct comparator is absent: {direct_id}")
        peer = run_by_id.get(direct.get("compares_to_run_id"))
        if not isinstance(peer, dict) or peer.get("surface") != "maude":
            raise CampaignError(f"direct comparator peer differs: {direct_id}")
        direct["operator_model_config"] = peer["operator_model_config"]
        direct["grader_model_config"] = peer["grader_model_config"]

    installation_runs = sorted(
        (
            run
            for run in runs
            if run.get("surface") == "maude-installation"
        ),
        key=lambda run: run["run_id"],
    )
    if [run["run_id"] for run in installation_runs] != list(INSTALL_RUN_IDS):
        raise CampaignError("installation run order/coverage differs")
    for ordinal, run in enumerate(installation_runs):
        operator = _alternate(installation_operator_order, ordinal)
        run["operator_model_config"] = operator
        run["grader_model_config"] = _grader_for(
            operator,
            installation_grader_order,
            ordinal=ordinal,
        )

    operator_configs_used = _ordered(
        {
            str(run["operator_model_config"])
            for run in runs
        }
    )
    grader_configs_used = _ordered(
        {
            str(run["grader_model_config"])
            for run in runs
        }
    )
    campaign_configs = _ordered(
        set(operator_configs_used) | set(grader_configs_used)
    )
    same_configuration_used = any(
        run["operator_model_config"] == run["grader_model_config"]
        for run in runs
    )
    same_family_used = any(
        _family(str(run["operator_model_config"]))
        == _family(str(run["grader_model_config"]))
        for run in runs
    )
    cross_family_used = any(
        _family(str(run["operator_model_config"]))
        != _family(str(run["grader_model_config"]))
        for run in runs
    )
    eligibility = {
        provider: {
            "ordinary_operator": provider in ordinary_operators,
            "installation_operator": provider in installation_operators,
            "ordinary_grader": provider in ordinary_graders,
            "installation_grader": provider in installation_graders,
        }
        for provider in SUPPORTED_PROVIDER_CONFIGS
    }
    result["operator_model_configs"] = {
        provider: PROVIDER_MODEL_CONFIGS[provider]
        for provider in campaign_configs
    }
    result["model_family_policy"] = {
        "assignment_algorithm": ASSIGNMENT_ALGORITHM,
        "campaign_provider_configs": campaign_configs,
        "operator_model_configs_used": operator_configs_used,
        "grader_model_configs_used": grader_configs_used,
        "provider_role_eligibility": eligibility,
        "separate_fresh_sessions_required": True,
        "same_family_grading": same_family_used,
        "same_model_configuration_grading": same_configuration_used,
        "cross_family_grading_supported": cross_family_used,
        "cross_family_grading_used": cross_family_used,
        "claude_available": "anthropic-sonnet" in auth,
        "claude_sessions_permitted": "anthropic-sonnet" in campaign_configs,
        "claude_operator_sessions_assigned": (
            "anthropic-sonnet" in operator_configs_used
        ),
        "claude_grader_sessions_assigned": (
            "anthropic-sonnet" in grader_configs_used
        ),
        "capability_policy": file_record(
            PROVIDER_CAPABILITY_POLICY_PATH,
            relative_to=PACKET_DIR,
        ),
        "capability_evidence": {
            "auth_isolation": file_record(
                AUTH_GATE_PROBE_PATH,
                relative_to=PACKET_DIR,
            ),
            "installation_surface": file_record(
                INSTALL_SURFACE_PROBE_PATH,
                relative_to=PACKET_DIR,
            ),
            "grader_surfaces": file_record(
                GRADER_PROBE_PATH,
                relative_to=PACKET_DIR,
            ),
        },
        "limitation": _limitation(
            eligibility,
            same_family_used=same_family_used,
            cross_family_used=cross_family_used,
        ),
    }
    return result


def validate_finalized_matrix() -> list[str]:
    try:
        actual = load_json(MATRIX_PATH)
        expected = derive_matrix(actual)
    except CampaignError as exc:
        return [str(exc)]
    errors: list[str] = []
    if actual != expected:
        errors.append("run matrix provider assignments are not deterministic")
    errors.extend(validate_matrix(actual))
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--validate", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.write:
            if MANIFEST_PATH.exists():
                raise CampaignError(
                    "campaign manifest exists; provider assignments are frozen"
                )
            matrix = load_json(MATRIX_PATH)
            policy = matrix.get("model_family_policy")
            if (
                isinstance(policy, dict)
                and policy.get("assignment_algorithm")
                == ASSIGNMENT_ALGORITHM
            ):
                raise CampaignError(
                    "provider assignments already finalized; refusing overwrite"
                )
            finalized = derive_matrix(matrix)
            prewrite_errors = validate_matrix(finalized)
            if prewrite_errors:
                raise CampaignError(
                    "derived provider assignments failed shared validation "
                    "before write: "
                    + "; ".join(prewrite_errors)
                )
            if derive_matrix(finalized) != finalized:
                raise CampaignError(
                    "derived provider assignments are not deterministic "
                    "before write"
                )
            write_json(MATRIX_PATH, finalized)
        errors = validate_finalized_matrix()
        if errors:
            raise CampaignError("; ".join(errors))
        matrix = load_json(MATRIX_PATH)
        print(
            json.dumps(
                {
                    "schema": (
                        "maude.synthetic-operator."
                        "provider-assignment-finalization.v1"
                    ),
                    "campaign_id": CAMPAIGN_ID,
                    "matrix": file_record(
                        MATRIX_PATH,
                        relative_to=PACKET_DIR,
                    ),
                    "model_family_policy": matrix["model_family_policy"],
                    "run_count": len(matrix["runs"]),
                    "provider_sessions_started": 0,
                    "task_network_used": False,
                    "authority_effect": "none",
                    "valid": True,
                },
                indent=2,
                sort_keys=True,
            )
        )
    except CampaignError as exc:
        print(f"provider assignment finalization failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
