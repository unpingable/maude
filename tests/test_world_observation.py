# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import copy
import hashlib
import hmac

import pytest

from maude.custody import _canonical
from maude.plan.cross_probe import GovernedNodeBindingV1
from maude.plan.world_observation import (
    EVIDENCE_DOMAIN,
    HANDOFF_AUTH_DOMAIN,
    PLAN_DOMAIN,
    WorldObservationError,
    _hash_domain,
    build_observation,
    seal_handoff,
)


def digest(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode()).hexdigest()


def fixture(action: str = "qualify") -> tuple[dict, bytes, dict, bytes, dict, dict]:
    nodes = (
        ["pn_health", "pn_cache_behavior", "pn_continued", "pn_restore"]
        if action == "qualify"
        else ["pn_teardown"]
    )
    plan = {
        "schema": "maude.local-compose.docket-executor-plan/v1",
        "action": action,
        "plan_document_digest": digest("plan"),
        "subject_digest": digest("subject"),
        "scope_digest": digest("scope"),
    }
    plan_bytes = _canonical(plan)
    work = _hash_domain(PLAN_DOMAIN, plan_bytes)
    attempt = digest("attempt")
    marker = digest("marker")
    evidence_payload = (
        {
            "health": {"status": 200},
            "cache_sequence": [
                {"cache": "MISS", "cache_node": "cache-a"},
                {"cache": "MISS", "cache_node": "cache-b"},
                {"cache": "HIT", "cache_node": "cache-a"},
                {"cache": "HIT", "cache_node": "cache-b"},
            ],
            "failure_requests": [
                {"status": 200, "cache_node": "cache-b"},
                {"status": 200, "cache_node": "cache-b"},
            ],
            "restored_nodes": ["cache-a", "cache-b"],
            "restored_health": {"status": 200},
        }
        if action == "qualify"
        else {
            "campaign_containers_running": 0,
            "campaign_networks_remaining": 0,
            "workspace_retained_for_evidence": True,
        }
    )
    evidence = {
        "dispatch": {
            "attempt": attempt,
            "marker": marker,
            "scope": plan["scope_digest"],
            "subject": plan["subject_digest"],
            "work": work,
            "work_schema": "maude.local-compose-workflow/v1",
        },
        "evidence": evidence_payload,
        "evidence_schema": "maude.local-compose.executor-evidence/v1",
        "observed_at_unix_ms": 1_787_420_745_776,
        "outcome": "success",
    }
    receipt = _hash_domain(EVIDENCE_DOMAIN, _canonical(evidence))
    evidence["docket_outcome"] = {
        "attempt": attempt,
        "marker": marker,
        "outcome": "success",
        "receipt": receipt,
    }
    evidence_bytes = _canonical(evidence)
    node_bindings = [
        {"node_id": node, "output_identity": digest("output:" + node)}
        for node in nodes
    ]
    compilation_unsigned = {
        "schema": "maude.plan-compilation-receipt/v1",
        "compiled_at": "2026-08-22T18:00:00Z",
        "compiler_id": "maude.local-compose-workflow",
        "compiler_inputs_digest": digest("compiler-inputs"),
        "compiler_inputs_schema": "maude.local-compose-workflow-input/v1",
        "compiler_version": "1",
        "draft_id": "draft_synthetic",
        "lock_id": digest("lock"),
        "plan_digest": plan["plan_document_digest"],
        # The production receipt binds the complete handoff output here; the
        # executor plan is bound separately by exact_work_identity.
        "compiled_output_digest": digest("compiled-handoff"),
        "exact_work_identity": work,
        "node_bindings": node_bindings,
        "revision_id": digest("revision"),
    }
    compilation_id = "sha256:" + hashlib.sha256(
        _canonical(compilation_unsigned)
    ).hexdigest()
    compilation = {**compilation_unsigned, "compilation_id": compilation_id}
    common = {
        "campaign_id": digest("campaign"),
        "occurrence_id": "00000000-0000-4000-8000-000000000000",
        "proposal_id": digest("proposal"),
        "issuance_id": digest("issuance"),
        "docket_attempt_id": attempt,
        "settlement_id": digest("settlement"),
        "outcome": "success",
    }
    inspector_path = (
        "/phosphor-ng/campaigns/"
        + common["campaign_id"].replace(":", "%3A")
        + "/occurrences/"
        + common["occurrence_id"]
        + "/proposals/"
        + common["proposal_id"].replace(":", "%3A")
    )
    binding_values = [
        GovernedNodeBindingV1.create(
            draft_id="draft_synthetic",
            node_id=item["node_id"],
            plan_digest=plan["plan_document_digest"],
            compilation_id=compilation_id,
            compiled_output_identity=item["output_identity"],
            exact_work_identity=work,
            authoring_provenance_id=digest("authoring"),
            handoff_id=digest("handoff"),
            campaign_id=common["campaign_id"],
            occurrence_id=common["occurrence_id"],
            proposal_id=common["proposal_id"],
            issuance_id=common["issuance_id"],
            docket_attempt_id=common["docket_attempt_id"],
            settlement_id=common["settlement_id"],
            outcome=common["outcome"],
            inspector_path=inspector_path,
        ).to_data()
        for item in node_bindings
    ]
    bindings = {
        "schema": "maude.plan-governed-cross-probe/v1",
        "bindings": binding_values,
    }
    return evidence, evidence_bytes, plan, plan_bytes, compilation, bindings


def build(action: str = "qualify") -> dict:
    evidence, evidence_bytes, plan, plan_bytes, compilation, bindings = fixture(action)
    return build_observation(
        executor_evidence=evidence,
        executor_evidence_bytes=evidence_bytes,
        executor_plan=plan,
        executor_plan_bytes=plan_bytes,
        compilation_receipt=compilation,
        governed_bindings=bindings,
    )


def test_exact_executor_evidence_becomes_bounded_plan_node_claims():
    observation = build()
    assert [claim["kind"] for claim in observation["claims"]] == [
        "front_door_reachable",
        "cache_miss_then_hit",
        "single_cache_failure_survived",
        "cache_topology_restored",
    ]
    assert {claim["plan_node_id"] for claim in observation["claims"]} == {
        "pn_health",
        "pn_cache_behavior",
        "pn_continued",
        "pn_restore",
    }
    assert observation["outcome"] == "success"
    assert "currentness" not in observation
    assert "authorization" not in observation


def test_teardown_projection_is_distinct_and_exact():
    observation = build("teardown")
    assert [(claim["kind"], claim["plan_node_id"]) for claim in observation["claims"]] == [
        ("campaign_resources_absent", "pn_teardown")
    ]


@pytest.mark.parametrize(
    ("part", "replacement", "message"),
    [
        ("evidence", digest("other-attempt"), "exact canonical JSON"),
        ("plan", digest("other-subject"), "dispatch does not bind"),
        ("binding", digest("other-proposal"), "invalid governed binding"),
    ],
)
def test_attempt_plan_and_governed_substitution_refuse(part, replacement, message):
    evidence, evidence_bytes, plan, plan_bytes, compilation, bindings = fixture()
    if part == "evidence":
        evidence["dispatch"]["attempt"] = replacement
    elif part == "plan":
        plan["subject_digest"] = replacement
        plan_bytes = _canonical(plan)
    else:
        bindings["bindings"][1]["proposal_id"] = replacement
    with pytest.raises(WorldObservationError, match=message):
        build_observation(
            executor_evidence=evidence,
            executor_evidence_bytes=evidence_bytes,
            executor_plan=plan,
            executor_plan_bytes=plan_bytes,
            compilation_receipt=compilation,
            governed_bindings=bindings,
        )


def test_recomputed_outer_observation_id_cannot_hide_changed_source():
    observation = build()
    substituted = copy.deepcopy(observation)
    substituted["source_evidence"]["evidence"]["health"]["status"] = 503
    substituted["observation_id"] = digest("attacker-recomputed-outer")
    # Resealing only checks a valid adapter-produced observation identity. The
    # hostile source has not passed build_observation and cannot be signed.
    with pytest.raises(WorldObservationError, match="identity mismatch"):
        seal_handoff(
            substituted,
            producer_principal_id="maude-observer:local",
            producer_key_id="maude-observer-key:one",
            target_runtime_id="nightshift:local",
            producer_key=bytes(range(32)),
            created_at="2026-08-22T20:00:00Z",
        )


def test_signed_handoff_binds_exact_observation_and_runtime():
    observation = build()
    key = bytes(range(32))
    handoff = seal_handoff(
        observation,
        producer_principal_id="maude-observer:local",
        producer_key_id="maude-observer-key:one",
        target_runtime_id="nightshift:local",
        producer_key=key,
        created_at="2026-08-22T20:00:00Z",
    )
    preimage = dict(handoff)
    authentication = preimage.pop("authentication")
    expected = hmac.new(
        key, HANDOFF_AUTH_DOMAIN + _canonical(preimage), hashlib.sha256
    ).hexdigest()
    assert authentication["tag"] == "hmac-sha256:" + expected
    assert handoff["observation"] == observation


def test_failed_result_does_not_become_satisfied_world_claims():
    evidence, _, plan, plan_bytes, compilation, bindings = fixture()
    evidence["outcome"] = "failure"
    evidence["docket_outcome"]["outcome"] = "failure"
    preimage = dict(evidence)
    preimage.pop("docket_outcome")
    evidence["docket_outcome"]["receipt"] = _hash_domain(
        EVIDENCE_DOMAIN, _canonical(preimage)
    )
    failed_bindings = []
    for binding in bindings["bindings"]:
        facts = dict(binding)
        facts.pop("binding_id")
        facts["outcome"] = "failure"
        failed_bindings.append(GovernedNodeBindingV1.create(**facts).to_data())
    observation = build_observation(
        executor_evidence=evidence,
        executor_evidence_bytes=_canonical(evidence),
        executor_plan=plan,
        executor_plan_bytes=plan_bytes,
        compilation_receipt=compilation,
        governed_bindings={
            **bindings,
            "bindings": failed_bindings,
        },
    )
    assert {claim["status"] for claim in observation["claims"]} == {"unknown"}
