# SPDX-License-Identifier: Apache-2.0
from datetime import UTC, datetime
import json

import pytest

from maude.design.providers import DeterministicFixtureProvider
from maude.plan.document import DocumentConstraintsV1, PlanDocumentV1, PlanNodeV1, SubmitterV1
from maude.plan.proposal_service import ProposalService
from maude.plan.proposal_store import ProposalStore
from maude.plan.proposals import ProposalError, ProposalScopeV1
from maude.plan.store import DraftStore
from maude.plan.switchyard_provider import SwitchyardProposalProfileV1, SwitchyardProposalProvider


def test_maude_canonical_json_matches_switchyard_rfc8785_for_non_ascii_strings():
    direct = pytest.importorskip("switchyard.direct_api")
    from maude.plan.document import canonical_json_bytes
    value = {"message": "πlan 😀", "schema": "fixture/v1"}
    assert canonical_json_bytes(value) == direct._canonical(value)


NOW = lambda: datetime(2026, 9, 12, tzinfo=UTC)  # noqa: E731


def profile():
    return SwitchyardProposalProfileV1(
        "maude-profile-fixture", "openrouter", "openai/gpt-5.6-terra",
        "openrouter-account-fixture", 30, 3_000, 64 * 1024, 16 * 1024,
        4_000, 1_000, 5_000, 1, "maude-live-test-budget", 50_000, 5_000, 1, 1,
    )


def service(tmp_path):
    drafts = DraftStore(tmp_path / "plans.sqlite", now=NOW)
    base = drafts.create(PlanDocumentV1(
        goal="Review deployment design", workspace="/srv/demo",
        submitter=SubmitterV1("human", "human_written", "operator"),
        nodes=(PlanNodeV1("pn_verify", "Verify evidence"),),
        constraints=DocumentConstraintsV1(),
    ), draft_id="draft_demo")
    return ProposalService(drafts, ProposalStore(tmp_path / "proposals.sqlite", now=NOW), now=NOW), base


class FixtureApi:
    def __init__(self, *, state="PROVIDER_COMPLETED", usage=True):
        self.calls = []
        self.state = state
        self.usage = usage

    def run(self, request, admitted_input, owner_binding, *, cancellation_requested):
        self.calls.append((request, admitted_input, owner_binding, cancellation_requested))
        if cancellation_requested():
            return {"state": "CANCELLED_BEFORE_CONTACT", "acceptance_state": "NOT_EVALUATED_BY_SWITCHYARD"}
        proposal_request = json.loads(admitted_input)["proposal_request"]
        # The fixture only derives proposal bytes; it does not provide transport.
        from maude.plan.proposals import PlanEditProposalRequestV1
        output = DeterministicFixtureProvider("bounded_edit").generate(
            PlanEditProposalRequestV1.from_data(proposal_request)
        ).decode()
        result = {
            "state": self.state,
            "acceptance_state": "NOT_EVALUATED_BY_SWITCHYARD",
            "reported_execution": {"model_id": request["model_id"]},
            "worker_output": output,
        }
        if self.usage:
            result["usage"] = {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
        return result


def request_for(service, base, provider):
    return service.request(
        draft_id=base.draft_id, base_revision_id=base.revision_id, task="clarify selected work",
        scope=ProposalScopeV1("exact_nodes", ("update_node",), ("pn_verify",), ("description",)),
        findings=(), provider=provider, generation_id="generation-switchyard-fixture",
    )


def test_enrolled_provider_preserves_identity_limits_and_human_acceptance(tmp_path):
    api = FixtureApi()
    provider = SwitchyardProposalProvider(profile(), api)
    svc, base = service(tmp_path)
    request = request_for(svc, base, provider)
    proposal = svc.generate(request, provider)
    direct, admitted_input, binding, _ = api.calls[0]
    assert direct["schema"] == "switchyard.direct-api-request/v2"
    assert direct["request_id"] == request.request_id
    assert direct["maximum_total_tokens"] == 5_000
    assert direct["maximum_concurrent_requests"] == 1
    assert direct["reserved_spend_micros"] == 5_000
    assert binding["owner_id"] == "maude.proposal-service"
    assert binding["proposal_request_id"] == request.request_id
    assert b"maude.plan-edit-provider-output/v1" in admitted_input
    assert svc.project(proposal.proposal_id).lifecycle.value == "proposed"
    receipt = svc.accept(proposal.proposal_id, accepting_actor="operator")
    assert receipt.proposal_id == proposal.proposal_id


@pytest.mark.parametrize("state,usage", [("CANCELLED_AFTER_CONTACT_OUTCOME_UNKNOWN", True), ("PROVIDER_COMPLETED", False)])
def test_indeterminate_or_unmetered_provider_result_refuses_before_proposal(tmp_path, state, usage):
    api = FixtureApi(state=state, usage=usage)
    provider = SwitchyardProposalProvider(profile(), api)
    svc, base = service(tmp_path)
    request = request_for(svc, base, provider)
    with pytest.raises(ProposalError):
        svc.generate(request, provider)
    assert svc.proposals.proposal_for_request(request.request_id) is None


def test_precontact_cancellation_is_delegated_to_switchyard(tmp_path):
    api = FixtureApi()
    provider = SwitchyardProposalProvider(profile(), api, cancellation_requested=lambda: True)
    svc, base = service(tmp_path)
    request = request_for(svc, base, provider)
    # The injected API models Switchyard's claimed pre-contact cancellation.
    with pytest.raises(ProposalError):
        provider.generate(request)
    assert api.calls[0][3]() is True
