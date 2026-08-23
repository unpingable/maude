# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import hashlib
import json
import os
import stat
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from maude.custody import _canonical
from maude.plan.cross_probe import GovernedNodeBindingV1
from maude.plan.document import canonical_json_bytes, content_digest
from maude.plan.observation_acquisition import (
    AcquisitionError,
    AcquisitionEventV1,
    AcquisitionEventKind,
    AcquisitionReason,
    AcquisitionRequestV1,
    AcquisitionSourcesV1,
    AcquisitionStore,
    AcquisitionTriggerV1,
    CustodyOutcomeUnknown,
    CustodyRefused,
    LocalComposePostSettlementAdapter,
    LocalComposeSteadyStateAdapter,
    _stage_exact_handoff,
    build_post_settlement_trigger,
    build_reobserve_after_stale_trigger,
    run_acquisition,
)
from maude.plan.steady_state_observation import build_observation as build_steady
from maude.plan.world_observation import EVIDENCE_DOMAIN, PLAN_DOMAIN, _hash_domain


def digest(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode()).hexdigest()


def fixture() -> tuple[
    AcquisitionTriggerV1, AcquisitionRequestV1, AcquisitionSourcesV1
]:
    plan = {
        "schema": "maude.local-compose.docket-executor-plan/v1",
        "action": "qualify",
        "plan_document_digest": digest("plan"),
        "subject_digest": digest("subject"),
        "scope_digest": digest("scope"),
    }
    plan_bytes = _canonical(plan)
    work = _hash_domain(PLAN_DOMAIN, plan_bytes)
    attempt = digest("attempt")
    marker = digest("marker")
    evidence = {
        "dispatch": {
            "attempt": attempt,
            "marker": marker,
            "scope": plan["scope_digest"],
            "subject": plan["subject_digest"],
            "work": work,
            "work_schema": "maude.local-compose-workflow/v1",
        },
        "evidence": {
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
        },
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
    nodes = [
        "pn_health",
        "pn_cache_a",
        "pn_cache_b",
        "pn_cache_behavior",
        "pn_continued",
        "pn_restore",
    ]
    node_bindings = [
        {"node_id": node, "output_identity": digest("output:" + node)} for node in nodes
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
        "compiled_output_digest": digest("compiled-handoff"),
        "exact_work_identity": work,
        "node_bindings": node_bindings,
        "revision_id": digest("revision"),
    }
    compilation = {
        **compilation_unsigned,
        "compilation_id": content_digest(_canonical(compilation_unsigned)),
    }
    campaign = digest("campaign")
    occurrence = "00000000-0000-4000-8000-000000000000"
    proposal = digest("proposal")
    issuance = digest("issuance")
    settlement = digest("settlement")
    handoff = digest("authoring-handoff")
    provenance = digest("authoring-provenance")
    bindings = {
        "schema": "maude.plan-governed-cross-probe/v1",
        "bindings": [
            GovernedNodeBindingV1.create(
                draft_id="draft_synthetic",
                node_id=node["node_id"],
                plan_digest=plan["plan_document_digest"],
                compilation_id=compilation["compilation_id"],
                compiled_output_identity=node["output_identity"],
                exact_work_identity=work,
                authoring_provenance_id=provenance,
                handoff_id=handoff,
                campaign_id=campaign,
                occurrence_id=occurrence,
                proposal_id=proposal,
                issuance_id=issuance,
                docket_attempt_id=attempt,
                settlement_id=settlement,
                outcome="success",
                inspector_path=(
                    "/phosphor-ng/campaigns/"
                    + campaign.replace(":", "%3A")
                    + "/occurrences/"
                    + occurrence
                    + "/proposals/"
                    + proposal.replace(":", "%3A")
                ),
            ).to_data()
            for node in node_bindings
        ],
    }
    profile_unsigned = {
        "schema": "nightshift.external_evidence_profile.v1",
        "profile_id": "",
        "purpose": "post_settlement_successor",
        "expected_adapter_id": "maude.local-compose-observation-adapter",
        "expected_adapter_version": "1",
        "expected_producer_principal_id": "maude-observer:local",
        "expected_producer_key_id": "maude-observer-key:one",
        "expected_runtime_id": "nightshift:local",
        "required_action": "qualify",
        "required_claims": [
            "front_door_reachable",
            "cache_miss_then_hit",
            "single_cache_failure_survived",
            "cache_topology_restored",
        ],
        "max_age_ms": 120_000,
    }
    profile_preimage = dict(profile_unsigned)
    profile_preimage.pop("profile_id")
    profile = {
        **profile_unsigned,
        "profile_id": content_digest(_canonical(profile_preimage)),
    }
    settlement_time = evidence["observed_at_unix_ms"] + 100
    docket = {
        "schema": "docket.governed-loop.inspection/v1",
        "requested_issuance": issuance,
        "record": {
            "issuance": {
                "schema": "ag.governed-loop.issuance/v1",
                "issuance": issuance,
                "key": {"campaign": campaign, "occurrence": occurrence},
                "program": digest("program"),
                "proposal": proposal,
                "work_schema": "maude.local-compose-workflow/v1",
                "work": work,
                "subject": plan["subject_digest"],
                "scope": plan["scope_digest"],
                "observation": digest("nightshift-observation"),
                "standing_resolution": digest("standing"),
                "mandate": digest("mandate"),
                "spend": digest("spend"),
            },
            "authentication": {
                "issuer_principal": "ag:local",
                "signer_key_id": "ag-key:one",
                "signer_public_key": "AA==",
                "signature": "AA==",
            },
            "custody": {
                "schema": "ag.governed-loop.docket-custody/v1",
                "issuance": issuance,
                "ag_spend": digest("spend"),
                "execution_standing": digest("execution-standing"),
                "standing_currentness": digest("execution-currentness"),
                "attempt": attempt,
                "executor_marker": marker,
                "accepted_at_unix_ms": evidence["observed_at_unix_ms"] - 1,
            },
            "status": "settled",
            "settlement": {
                "schema": "ag.governed-loop.docket-settlement/v1",
                "settlement": settlement,
                "issuance": issuance,
                "attempt": attempt,
                "executor_marker": marker,
                "receipt": receipt,
                "outcome": "success",
                "settled_at_unix_ms": settlement_time,
            },
            "indeterminate": None,
            "executor_binding": digest("executor-binding"),
            "executor_program_digest": digest("executor-program"),
            "executor_plan": "/qualified/executor-plan.json",
        },
    }
    trigger = build_post_settlement_trigger(
        docket_inspection=docket,
        executor_plan=plan,
        compilation_receipt=compilation,
        governed_bindings=bindings,
        external_profile=profile,
        target_runtime_id="nightshift:local",
    )
    request = AcquisitionRequestV1.create(trigger)
    sources = AcquisitionSourcesV1(
        _canonical(docket),
        _canonical(evidence),
        plan_bytes,
        _canonical(compilation),
        _canonical(bindings),
        _canonical(profile),
    )
    return trigger, request, sources


class Custody:
    def __init__(self, *, unknown_once: bool = False, refuse: bool = False) -> None:
        self.calls = 0
        self.unknown_once = unknown_once
        self.refuse = refuse

    def import_handoff(self, handoff: bytes) -> dict:
        self.calls += 1
        if self.unknown_once and self.calls == 1:
            raise CustodyOutcomeUnknown("lost response after possible durable import")
        if self.refuse:
            raise CustodyRefused("credential mismatch")
        value = json.loads(handoff)
        return {
            "schema": "nightshift.external_observation_custody_provenance.v1",
            "custody_id": digest("custody:" + value["handoff_id"]),
            "handoff_id": value["handoff_id"],
            "observation_id": value["observation"]["observation_id"],
        }


class FailingAdapter:
    def acquire(self, request, trigger, sources):
        raise AcquisitionError("injected bounded adapter process failure")


def recorded(tmp_path):
    trigger, request, sources = fixture()
    store = AcquisitionStore(
        tmp_path / "acquisition.sqlite",
        now=lambda: datetime(2026, 8, 22, 19, 0, tzinfo=UTC),
    )
    store.record(trigger, request, sources)
    return store, trigger, request


def adapter() -> LocalComposePostSettlementAdapter:
    return LocalComposePostSettlementAdapter(
        producer_key=b"K" * 32,
        producer_principal_id="maude-observer:local",
        producer_key_id="maude-observer-key:one",
    )


def test_ledger_is_private_regular_service_owned_storage(tmp_path):
    path = tmp_path / "acquisition.sqlite"
    AcquisitionStore(path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600

    unsafe = tmp_path / "unsafe.sqlite"
    unsafe.write_bytes(b"")
    os.chmod(unsafe, 0o644)
    with pytest.raises(AcquisitionError, match="group or others"):
        AcquisitionStore(unsafe)

    target = tmp_path / "target.sqlite"
    target.write_bytes(b"")
    os.chmod(target, 0o600)
    link = tmp_path / "link.sqlite"
    link.symlink_to(target)
    with pytest.raises(AcquisitionError, match="non-symlink regular"):
        AcquisitionStore(link)


def test_exact_handoff_staging_is_private_idempotent_and_substitution_safe(tmp_path):
    path = tmp_path / "handoff.json"
    _stage_exact_handoff(path, b"exact")
    assert path.read_bytes() == b"exact"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    _stage_exact_handoff(path, b"exact")
    with pytest.raises(CustodyRefused, match="substitution"):
        _stage_exact_handoff(path, b"changed")

    other = tmp_path / "other.json"
    other.write_bytes(b"exact")
    os.chmod(other, 0o600)
    link = tmp_path / "handoff-link.json"
    link.symlink_to(other)
    with pytest.raises(CustodyRefused, match="regular file"):
        _stage_exact_handoff(link, b"exact")


def test_exact_settlement_records_one_durable_trigger_and_request(tmp_path):
    store, trigger, request = recorded(tmp_path)
    again = store.record(trigger, request, store.sources(trigger.trigger_id))
    assert again == request
    assert [event.kind for event in store.events(request.request_id)] == [
        AcquisitionEventKind.TRIGGER_RECORDED,
        AcquisitionEventKind.ACQUISITION_SCHEDULED,
    ]
    reopened = AcquisitionStore(store.path)
    assert reopened.trigger(trigger.trigger_id) == trigger
    assert reopened.request(request.request_id) == request
    history = reopened.export_occurrence(trigger.campaign_id, trigger.occurrence_id)
    assert history["schema"] == "maude.external-evidence-acquisition-history/v1"
    assert [item["request"]["request_id"] for item in history["acquisitions"]] == [
        request.request_id
    ]


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("record", "settlement", "settlement"), digest("other-settlement")),
        (("record", "custody", "attempt"), digest("other-attempt")),
        (
            ("record", "issuance", "key", "occurrence"),
            "00000000-0000-4000-8000-000000000002",
        ),
        (("record", "issuance", "proposal"), digest("other-proposal")),
        (("record", "issuance", "subject"), digest("other-subject")),
    ],
)
def test_trigger_substitution_refuses(path, replacement):
    trigger, _, sources = fixture()
    docket = json.loads(sources.docket_inspection)
    target = docket
    for component in path[:-1]:
        target = target[component]
    target[path[-1]] = replacement
    with pytest.raises(AcquisitionError):
        build_post_settlement_trigger(
            docket_inspection=docket,
            executor_plan=json.loads(sources.executor_plan),
            compilation_receipt=json.loads(sources.compilation_receipt),
            governed_bindings=json.loads(sources.governed_bindings),
            external_profile=json.loads(sources.external_profile),
            target_runtime_id=trigger.target_runtime_id,
        )


def test_exact_acquisition_runs_adapter_and_accepts_custody(tmp_path):
    store, trigger, request = recorded(tmp_path)
    custody = Custody()
    export = run_acquisition(store, request.request_id, adapter(), custody)
    assert custody.calls == 1
    assert export["trigger"]["settlement_id"] == trigger.settlement_id
    assert export["events"][-1]["kind"] == "custody_accepted"
    assert (
        export["evidence"]["handoff"]["observation"]["observed_at_unix_ms"]
        == 1_787_420_745_776
    )


def test_response_loss_reuses_exact_artifact_and_never_refreshes_observed_time(
    tmp_path,
):
    store, _, request = recorded(tmp_path)
    with pytest.raises(CustodyOutcomeUnknown):
        run_acquisition(
            store, request.request_id, adapter(), Custody(), fault_after_handoff=True
        )
    first = store.handoff(request.request_id)
    assert first is not None
    old_observed_at = json.loads(first)["observation"]["observed_at_unix_ms"]
    result = run_acquisition(store, request.request_id, adapter(), Custody())
    assert store.handoff(request.request_id) == first
    assert (
        result["evidence"]["handoff"]["observation"]["observed_at_unix_ms"]
        == old_observed_at
    )
    assert (
        sum(
            event.kind == AcquisitionEventKind.ADAPTER_INVOCATION_STARTED
            for event in store.events(request.request_id)
        )
        == 1
    )


def test_unknown_custody_response_converges_by_exact_resend(tmp_path):
    store, _, request = recorded(tmp_path)
    custody = Custody(unknown_once=True)
    with pytest.raises(CustodyOutcomeUnknown):
        run_acquisition(store, request.request_id, adapter(), custody)
    before = store.handoff(request.request_id)
    result = run_acquisition(store, request.request_id, adapter(), custody)
    assert custody.calls == 2
    assert store.handoff(request.request_id) == before
    assert result["events"][-1]["kind"] == "custody_accepted"


def test_concurrent_trigger_discovery_converges_and_adapter_has_one_claim(tmp_path):
    trigger, request, sources = fixture()
    store = AcquisitionStore(tmp_path / "acquisition.sqlite")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda _: store.record(trigger, request, sources), range(2))
        )
    assert results == [request, request]
    claims = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(
                store.claim_invocation, request.request_id, recover_incomplete=False
            )
            for _ in range(2)
        ]
        claims = [future.result() for future in futures]
    assert sum(claim is not None for claim in claims) == 1


def test_incomplete_invocation_requires_explicit_recovery_and_preserves_evidence_time(
    tmp_path,
):
    store, _, request = recorded(tmp_path)
    assert (
        store.claim_invocation(request.request_id, recover_incomplete=False) is not None
    )
    with pytest.raises(CustodyOutcomeUnknown):
        run_acquisition(store, request.request_id, adapter(), Custody())
    result = run_acquisition(
        store, request.request_id, adapter(), Custody(), recover_incomplete=True
    )
    assert (
        result["evidence"]["handoff"]["observation"]["observed_at_unix_ms"]
        == 1_787_420_745_776
    )


def test_adapter_process_recovery_has_a_closed_invocation_budget(tmp_path):
    store, _, request = recorded(tmp_path)
    first = store.claim_invocation(request.request_id, recover_incomplete=False)
    assert first is not None
    store.record_adapter_failure(request.request_id, "first process failed")
    second = store.claim_invocation(request.request_id, recover_incomplete=False)
    assert second is not None
    store.record_adapter_failure(request.request_id, "second process failed")
    with pytest.raises(AcquisitionError, match="budget exhausted"):
        store.claim_invocation(request.request_id, recover_incomplete=False)


def test_known_adapter_failure_fabricates_no_evidence_and_can_recover_once(tmp_path):
    store, _, request = recorded(tmp_path)
    with pytest.raises(AcquisitionError, match="injected bounded"):
        run_acquisition(store, request.request_id, FailingAdapter(), Custody())
    assert store.handoff(request.request_id) is None
    assert [event.kind for event in store.events(request.request_id)][-1] == (
        AcquisitionEventKind.ADAPTER_FAILED
    )


def test_profile_pins_the_observation_producer_before_evidence_packaging(tmp_path):
    store, _, request = recorded(tmp_path)
    substituted = LocalComposePostSettlementAdapter(
        producer_key=b"K" * 32,
        producer_principal_id="maude-observer:substituted",
        producer_key_id="maude-observer-key:one",
    )
    with pytest.raises(
        AcquisitionError, match="does not match exact Nightshift profile"
    ):
        run_acquisition(store, request.request_id, substituted, Custody())
    assert store.handoff(request.request_id) is None
    result = run_acquisition(store, request.request_id, adapter(), Custody())
    assert result["events"][-1]["kind"] == "custody_accepted"
    assert (
        sum(event["kind"] == "adapter_invocation_started" for event in result["events"])
        == 2
    )


def test_concurrent_exact_custody_recovery_records_one_terminal_receipt(tmp_path):
    store, _, request = recorded(tmp_path)
    with pytest.raises(CustodyOutcomeUnknown):
        run_acquisition(
            store, request.request_id, adapter(), Custody(), fault_after_handoff=True
        )
    custody = Custody()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: run_acquisition(
                    store, request.request_id, adapter(), custody
                ),
                range(2),
            )
        )
    assert all(result["events"][-1]["kind"] == "custody_accepted" for result in results)
    assert (
        sum(
            event.kind == AcquisitionEventKind.CUSTODY_ACCEPTED
            for event in store.events(request.request_id)
        )
        == 1
    )


def test_local_compose_reobservation_refuses_instead_of_repeating_fault_injection():
    trigger, request, sources = fixture()
    reobserve_trigger = replace(
        trigger,
        trigger_id="",
        reason=AcquisitionReason.REOBSERVE_AFTER_STALE,
        source_observation_id=digest("old-observation"),
        currentness_basis_digest=digest("stale-resolution"),
        basis_evaluated_at_unix_ms=1_700_000_060_000,
    )
    reobserve_trigger = replace(
        reobserve_trigger,
        trigger_id=content_digest(
            canonical_json_bytes(reobserve_trigger.unsigned_data())
        ),
    )
    reobserve_request = AcquisitionRequestV1.create(reobserve_trigger)
    with pytest.raises(AcquisitionError, match="cannot re-observe"):
        adapter().acquire(reobserve_request, reobserve_trigger, sources)


def test_recomputed_outer_trigger_digest_cannot_hide_semantic_substitution():
    trigger, _, _ = fixture()
    value = trigger.to_data()
    value["adapter_id"] = "maude.substituted-adapter"
    value["trigger_id"] = content_digest(
        canonical_json_bytes(
            {key: item for key, item in value.items() if key != "trigger_id"}
        )
    )
    with pytest.raises(AcquisitionError, match="adapter"):
        # Content addressing alone is insufficient: the closed workflow registry wins.
        AcquisitionTriggerV1.from_data(value)


def test_recomputed_event_digest_cannot_hide_contradictory_event_facts(tmp_path):
    store, _, request = recorded(tmp_path)
    value = store.events(request.request_id)[0].to_data()
    value["observed_at_unix_ms"] = 1_787_420_745_776
    value["event_id"] = content_digest(
        canonical_json_bytes(
            {key: item for key, item in value.items() if key != "event_id"}
        )
    )
    with pytest.raises(AcquisitionError, match="outcome facts"):
        AcquisitionEventV1.from_data(value)


def test_custody_refusal_is_distinct_from_adapter_evidence(tmp_path):
    store, _, request = recorded(tmp_path)
    result = run_acquisition(store, request.request_id, adapter(), Custody(refuse=True))
    assert result["evidence"] is not None
    assert result["events"][-1]["kind"] == "custody_refused"
    assert not any(event["kind"] == "custody_accepted" for event in result["events"])


def test_source_bytes_are_immutable_and_restart_safe(tmp_path):
    store, trigger, request = recorded(tmp_path)
    sources = store.sources(trigger.trigger_id)
    with store._connect() as db:
        db.execute(
            "UPDATE acquisition_triggers SET executor_evidence=? WHERE trigger_id=?",
            (canonical_json_bytes({"substituted": True}), trigger.trigger_id),
        )
    reopened = AcquisitionStore(store.path)
    with pytest.raises(ValueError):
        run_acquisition(reopened, request.request_id, adapter(), Custody())
    assert (
        sources.executor_evidence
        != reopened.sources(trigger.trigger_id).executor_evidence
    )


def test_profile_source_substitution_is_revalidated_before_adapter_invocation(tmp_path):
    store, trigger, request = recorded(tmp_path)
    profile = json.loads(store.sources(trigger.trigger_id).external_profile)
    profile["expected_runtime_id"] = "nightshift:substituted"
    preimage = dict(profile)
    preimage.pop("profile_id")
    profile["profile_id"] = content_digest(canonical_json_bytes(preimage))
    with store._connect() as db:
        db.execute(
            "UPDATE acquisition_triggers SET external_profile=? WHERE trigger_id=?",
            (canonical_json_bytes(profile), trigger.trigger_id),
        )
    with pytest.raises(AcquisitionError, match="profile"):
        run_acquisition(store, request.request_id, adapter(), Custody())
    assert not any(
        event.kind == AcquisitionEventKind.ADAPTER_INVOCATION_STARTED
        for event in store.events(request.request_id)
    )


class PassiveProbeFixture:
    def __init__(self, *, changed: bool = False, fail: bool = False) -> None:
        self.changed = changed
        self.fail = fail
        self.calls = 0

    def acquire(self, _plan: dict, _nonce: str) -> dict:
        self.calls += 1
        if self.fail:
            raise AcquisitionError("front door unavailable")
        suffix = "changed" if self.changed else "ordinary"
        return {
            "front_door": {"status": 200, "body_digest": digest("health:" + suffix)},
            "cache_a": {"identity": "cache-a", "state": "running", "health": "healthy"},
            "cache_b": {"identity": "cache-b", "state": "running", "health": "healthy"},
            "cache_behavior": {
                "requests": [
                    {"cache": "MISS", "cache_node": "cache-a"},
                    {"cache": "MISS", "cache_node": "cache-b"},
                    {"cache": "HIT", "cache_node": "cache-a"},
                    {"cache": "HIT", "cache_node": "cache-b"},
                ],
                "variant": suffix,
            },
        }


def passive_fixture() -> tuple[
    AcquisitionTriggerV1,
    AcquisitionRequestV1,
    AcquisitionSourcesV1,
    dict,
]:
    strong_trigger, _, strong_sources = fixture()
    qualification_handoff = json.loads(
        LocalComposePostSettlementAdapter(
            producer_key=b"k" * 32,
            producer_principal_id="maude-observer:local",
            producer_key_id="maude-observer-key:one",
        ).acquire(
            AcquisitionRequestV1.create(strong_trigger),
            strong_trigger,
            strong_sources,
        )
    )
    qualification_observation_id = qualification_handoff["observation"][
        "observation_id"
    ]
    strong_profile = json.loads(strong_sources.external_profile)
    profile_unsigned = {
        "schema": "nightshift.steady_state_evidence_profile.v1",
        "profile_id": "",
        "purpose": "routine_continuation",
        "qualification_profile": strong_profile,
        "expected_adapter_id": "maude.local-compose-steady-state-observation-adapter",
        "expected_adapter_version": "1",
        "expected_producer_principal_id": "maude-observer:local",
        "expected_producer_key_id": "maude-observer-key:one",
        "expected_runtime_id": "nightshift:local",
        "required_qualification_claims": strong_profile["required_claims"],
        "required_steady_state_claims": [
            "front_door_reachable",
            "cache_a_present",
            "cache_b_present",
            "ordinary_cache_behavior_observed",
        ],
        "max_age_ms": 5_000,
    }
    profile_preimage = dict(profile_unsigned)
    profile_preimage.pop("profile_id")
    profile = {
        **profile_unsigned,
        "profile_id": content_digest(canonical_json_bytes(profile_preimage)),
    }
    basis_unsigned = {
        "schema": "nightshift.steady_state_reobservation_basis.v1",
        "basis_id": "",
        "requirement": "stale",
        "profile_id": profile["profile_id"],
        "qualification_id": digest("qualification"),
        "qualification_observation_id": qualification_observation_id,
        "source_observation_id": digest("passive-s1"),
        "source_custody_id": digest("passive-s1-custody"),
        "plan_document_digest": strong_trigger.plan_document_digest,
        "compilation_id": strong_trigger.compilation_id,
        "exact_work_id": strong_trigger.exact_work_id,
        "campaign_id": strong_trigger.campaign_id,
        "occurrence_id": strong_trigger.occurrence_id,
        "proposal_id": strong_trigger.proposal_id,
        "issuance_id": strong_trigger.issuance_id,
        "attempt_id": strong_trigger.attempt_id,
        "settlement_id": strong_trigger.settlement_id,
        "subject_digest": strong_trigger.subject_digest,
        "scope_digest": strong_trigger.scope_digest,
        "evaluated_at_unix_ms": 50_000,
        "prior_fresh_until_unix_ms": 50_000,
    }
    basis_preimage = dict(basis_unsigned)
    basis_preimage.pop("basis_id")
    basis = {
        **basis_unsigned,
        "basis_id": content_digest(canonical_json_bytes(basis_preimage)),
    }
    docket = json.loads(strong_sources.docket_inspection)
    plan = json.loads(strong_sources.executor_plan)
    compilation = json.loads(strong_sources.compilation_receipt)
    bindings = json.loads(strong_sources.governed_bindings)
    trigger = build_reobserve_after_stale_trigger(
        docket_inspection=docket,
        executor_plan=plan,
        compilation_receipt=compilation,
        governed_bindings=bindings,
        steady_profile=profile,
        reobservation_basis=basis,
        target_runtime_id="nightshift:local",
    )
    request = AcquisitionRequestV1.create(trigger)
    return (
        trigger,
        request,
        AcquisitionSourcesV1(
            strong_sources.docket_inspection,
            strong_sources.executor_evidence,
            strong_sources.executor_plan,
            strong_sources.compilation_receipt,
            strong_sources.governed_bindings,
            canonical_json_bytes(profile),
            canonical_json_bytes(basis),
        ),
        basis,
    )


def passive_adapter(
    probe: PassiveProbeFixture | None = None,
) -> LocalComposeSteadyStateAdapter:
    return LocalComposeSteadyStateAdapter(
        producer_key=b"k" * 32,
        producer_principal_id="maude-observer:local",
        producer_key_id="maude-observer-key:one",
        probe=probe or PassiveProbeFixture(),
        observed_at=lambda: datetime(1970, 1, 1, 0, 1, tzinfo=UTC),
    )


def test_passive_stale_trigger_produces_only_read_only_claims(tmp_path):
    trigger, request, sources, basis = passive_fixture()
    assert request.not_before_unix_ms == basis["evaluated_at_unix_ms"]
    store = AcquisitionStore(tmp_path / "passive.sqlite")
    store.record(trigger, request, sources)
    result = run_acquisition(store, request.request_id, passive_adapter(), Custody())
    observation = result["evidence"]["handoff"]["observation"]
    assert observation["observed_at_unix_ms"] == 60_000
    assert (
        observation["qualification_observation_id"]
        == basis["qualification_observation_id"]
    )
    assert [claim["kind"] for claim in observation["claims"]] == [
        "front_door_reachable",
        "cache_a_present",
        "cache_b_present",
        "ordinary_cache_behavior_observed",
    ]
    assert "single_cache_failure_survived" not in json.dumps(observation)


def test_terminal_replay_reconciles_before_not_before_clock_check(tmp_path):
    trigger, request, sources, _ = passive_fixture()
    path = tmp_path / "passive.sqlite"
    store = AcquisitionStore(path)
    store.record(trigger, request, sources)
    first = run_acquisition(store, request.request_id, passive_adapter(), Custody())
    event_count = len(first["events"])

    reopened = AcquisitionStore(
        path, now=lambda: datetime(1970, 1, 1, 0, 0, 1, tzinfo=UTC)
    )
    replay = run_acquisition(reopened, request.request_id, passive_adapter(), Custody())
    assert replay == first
    assert len(replay["events"]) == event_count


def test_absent_basis_gets_one_passive_successor_acquisition(tmp_path):
    stale_trigger, _, stale_sources, _ = passive_fixture()
    basis = json.loads(stale_sources.reobservation_basis or b"{}")
    basis.update(
        {
            "requirement": "absent",
            "source_observation_id": None,
            "source_custody_id": None,
            "prior_fresh_until_unix_ms": None,
        }
    )
    preimage = dict(basis)
    preimage.pop("basis_id")
    basis["basis_id"] = content_digest(canonical_json_bytes(preimage))
    trigger = build_reobserve_after_stale_trigger(
        docket_inspection=json.loads(stale_sources.docket_inspection),
        executor_plan=json.loads(stale_sources.executor_plan),
        compilation_receipt=json.loads(stale_sources.compilation_receipt),
        governed_bindings=json.loads(stale_sources.governed_bindings),
        steady_profile=json.loads(stale_sources.external_profile),
        reobservation_basis=basis,
        target_runtime_id=stale_trigger.target_runtime_id,
        reason=AcquisitionReason.REOBSERVE_FOR_SUCCESSOR,
    )
    request = AcquisitionRequestV1.create(trigger)
    store = AcquisitionStore(tmp_path / "passive.sqlite")
    store.record(
        trigger,
        request,
        replace(
            stale_sources,
            reobservation_basis=canonical_json_bytes(basis),
        ),
    )
    result = run_acquisition(store, request.request_id, passive_adapter(), Custody())
    assert trigger.source_observation_id is None
    assert request.reason == AcquisitionReason.REOBSERVE_FOR_SUCCESSOR
    assert result["events"][-1]["kind"] == "custody_accepted"


def test_passive_changed_world_gets_distinct_evidence_without_repair(tmp_path):
    trigger, request, sources, _ = passive_fixture()
    store = AcquisitionStore(tmp_path / "passive.sqlite")
    store.record(trigger, request, sources)
    probe = PassiveProbeFixture(changed=True)
    result = run_acquisition(
        store, request.request_id, passive_adapter(probe), Custody()
    )
    assert probe.calls == 1
    assert (
        result["evidence"]["handoff"]["observation"]["source_evidence"]["observations"][
            "cache_behavior"
        ]["variant"]
        == "changed"
    )


def test_passive_failure_fabricates_no_evidence_or_remediation(tmp_path):
    trigger, request, sources, _ = passive_fixture()
    store = AcquisitionStore(tmp_path / "passive.sqlite")
    store.record(trigger, request, sources)
    with pytest.raises(AcquisitionError, match="front door unavailable"):
        run_acquisition(
            store,
            request.request_id,
            passive_adapter(PassiveProbeFixture(fail=True)),
            Custody(),
        )
    assert store.handoff(request.request_id) is None
    assert (
        store.events(request.request_id)[-1].kind == AcquisitionEventKind.ADAPTER_FAILED
    )


def test_artifact_change_cannot_recompute_passive_trigger():
    trigger, _, sources, _ = passive_fixture()
    basis = json.loads(sources.reobservation_basis or b"{}")
    basis["plan_document_digest"] = digest("changed-plan")
    preimage = dict(basis)
    preimage.pop("basis_id")
    basis["basis_id"] = content_digest(canonical_json_bytes(preimage))
    with pytest.raises(AcquisitionError, match="exact qualified artifact"):
        build_reobserve_after_stale_trigger(
            docket_inspection=json.loads(sources.docket_inspection),
            executor_plan=json.loads(sources.executor_plan),
            compilation_receipt=json.loads(sources.compilation_receipt),
            governed_bindings=json.loads(sources.governed_bindings),
            steady_profile=json.loads(sources.external_profile),
            reobservation_basis=basis,
            target_runtime_id=trigger.target_runtime_id,
        )


def test_build_steady_rejects_effectful_node_substitution():
    _, _, sources, basis = passive_fixture()
    bindings = json.loads(sources.governed_bindings)
    bindings["bindings"] = [
        item for item in bindings["bindings"] if item["node_id"] != "pn_cache_a"
    ]
    with pytest.raises(ValueError, match="passive PlanNode"):
        build_steady(
            basis=basis,
            plan=json.loads(sources.executor_plan),
            compilation=json.loads(sources.compilation_receipt),
            governed_bindings=bindings,
            observations=PassiveProbeFixture().acquire({}, "nonce"),
            observed_at_unix_ms=60_000,
        )


def test_passive_response_loss_resends_exact_evidence_without_false_refresh(tmp_path):
    trigger, request, sources, _ = passive_fixture()
    store = AcquisitionStore(tmp_path / "passive.sqlite")
    store.record(trigger, request, sources)
    first_probe = PassiveProbeFixture()
    with pytest.raises(CustodyOutcomeUnknown):
        run_acquisition(
            store,
            request.request_id,
            passive_adapter(first_probe),
            Custody(),
            fault_after_handoff=True,
        )
    first = json.loads(store.handoff(request.request_id) or b"{}")
    later_probe = PassiveProbeFixture(changed=True)
    result = run_acquisition(
        store,
        request.request_id,
        LocalComposeSteadyStateAdapter(
            producer_key=b"k" * 32,
            producer_principal_id="maude-observer:local",
            producer_key_id="maude-observer-key:one",
            probe=later_probe,
            observed_at=lambda: datetime(1970, 1, 1, 0, 5, tzinfo=UTC),
        ),
        Custody(),
    )
    assert first_probe.calls == 1
    assert later_probe.calls == 0
    assert result["evidence"]["handoff"] == first
    assert result["evidence"]["handoff"]["observation"]["observed_at_unix_ms"] == 60_000


def test_incomplete_passive_invocation_cannot_reacquire_under_same_identity(tmp_path):
    trigger, request, sources, _ = passive_fixture()
    store = AcquisitionStore(tmp_path / "passive.sqlite")
    store.record(trigger, request, sources)
    assert store.claim_invocation(request.request_id, recover_incomplete=False)
    probe = PassiveProbeFixture()
    with pytest.raises(CustodyOutcomeUnknown, match="reconcile"):
        run_acquisition(
            store,
            request.request_id,
            passive_adapter(probe),
            Custody(),
            recover_incomplete=True,
        )
    assert probe.calls == 0


def test_concurrent_stale_trigger_recording_converges(tmp_path):
    trigger, request, sources, _ = passive_fixture()
    path = tmp_path / "passive.sqlite"
    AcquisitionStore(path)

    def record_once(_index: int) -> str:
        return AcquisitionStore(path).record(trigger, request, sources).request_id

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(record_once, range(2))) == [
            request.request_id,
            request.request_id,
        ]
    store = AcquisitionStore(path)
    assert [event.kind for event in store.events(request.request_id)].count(
        AcquisitionEventKind.TRIGGER_RECORDED
    ) == 1
