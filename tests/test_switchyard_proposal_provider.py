# SPDX-License-Identifier: Apache-2.0
from dataclasses import replace
from datetime import UTC, datetime
import json

import pytest

from maude.design.providers import DeterministicFixtureProvider
from maude.plan.document import (
    DocumentConstraintsV1, PlanDocumentV1, PlanNodeV1, SubmitterV1,
    canonical_json_bytes,
)
from maude.plan.operations import PlanOperationV1, UpdateNodeV1
from maude.plan.proposal_service import ProposalService
from maude.plan.proposal_store import ProposalStore
from maude.plan.proposals import (
    ProposalError, ProposalScopeV1, ProviderOutputV1,
    proposal_from_provider_output,
)
from maude.plan.store import DraftStore
from maude.plan.switchyard_provider import (
    UPDATE_NODE_OPERATION_EXAMPLE,
    SwitchyardProposalProfileV1,
    SwitchyardProposalProvider,
    provider_output_response_format,
)


def test_maude_canonical_json_matches_switchyard_rfc8785_for_non_ascii_strings():
    direct = pytest.importorskip("switchyard.direct_api")
    from maude.plan.document import canonical_json_bytes
    value = {"message": "πlan 😀", "schema": "fixture/v1"}
    assert canonical_json_bytes(value) == direct._canonical(value)


def test_generic_prompt_update_node_example_is_parseable_by_the_real_operation_contract():
    operation = PlanOperationV1.from_data(UPDATE_NODE_OPERATION_EXAMPLE)
    assert isinstance(operation.edit, UpdateNodeV1)
    assert operation.edit.node.node_id == "pn_example"


NOW = lambda: datetime(2026, 9, 12, tzinfo=UTC)  # noqa: E731


def profile():
    return SwitchyardProposalProfileV1(
        "maude-profile-fixture", "openrouter", "openai/gpt-5.6-terra",
        "openrouter-account-fixture", 30, 3_000, 64 * 1024, 16 * 1024,
        6_000, 1_000, 7_000, 1, "maude-live-test-budget", 50_000, 7_000, 1, 1,
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
    assert direct["schema"] == "switchyard.direct-api-request/v3"
    assert binding["schema"] == "switchyard.direct-api-owner-binding/v3"
    assert direct["request_id"] == request.request_id
    assert direct["maximum_total_tokens"] == 7_000
    assert direct["maximum_concurrent_requests"] == 1
    assert direct["reserved_spend_micros"] == 7_000
    assert binding["owner_id"] == "maude.proposal-service"
    assert binding["proposal_request_id"] == request.request_id
    response_format = direct["response_format"]
    assert response_format == provider_output_response_format(request)
    schema = response_format["json_schema"]["schema"]
    assert response_format["json_schema"]["strict"] is True
    assert schema["properties"]["request_id"]["const"] == request.request_id
    assert "authority" not in json.dumps(response_format)
    assert len(admitted_input) + len(canonical_json_bytes(response_format)) + 512 <= direct["maximum_prompt_tokens"]
    edit_variants = schema["properties"]["operations"]["items"]["properties"]["operation"]["anyOf"]
    assert [item["properties"]["type"]["const"] for item in edit_variants] == ["update_node"]
    assert b"maude.plan-edit-provider-output/v1" in admitted_input
    assert svc.project(proposal.proposal_id).lifecycle.value == "proposed"
    receipt = svc.accept(proposal.proposal_id, accepting_actor="operator")
    assert receipt.proposal_id == proposal.proposal_id


@pytest.mark.parametrize(
    "allowed_operation_types",
    [
        ("add_node",),
        ("update_node",),
        ("remove_node",),
        ("reorder_node",),
        ("update_document",),
    ],
)
def test_provider_response_format_uses_only_supported_array_and_union_forms(
    tmp_path, allowed_operation_types
):
    svc, base = service(tmp_path)
    request = request_for(
        svc, base, SwitchyardProposalProvider(profile(), FixtureApi())
    )
    if allowed_operation_types == ("update_document",):
        scope = ProposalScopeV1(
            "exact_document", allowed_operation_types, (), (), ("goal",)
        )
    else:
        scope = ProposalScopeV1(
            "exact_nodes", allowed_operation_types, ("pn_verify",), ("description",)
        )
    schema = provider_output_response_format(replace(request, scope=scope))["json_schema"][
        "schema"
    ]
    operations = schema["properties"]["operations"]
    operation = operations["items"]["properties"]["operation"]
    assert operations["minItems"] == 1
    assert "maxItems" not in operations
    assert "at most 32 operations" in operations["description"].lower()
    assert "oneOf" not in json.dumps(schema)
    assert [variant["properties"]["type"] for variant in operation["anyOf"]] == [
        {"type": "string", "const": item} for item in allowed_operation_types
    ]


def test_local_protocol_still_refuses_more_than_32_operations(tmp_path):
    svc, base = service(tmp_path)
    request = request_for(
        svc, base, SwitchyardProposalProvider(profile(), FixtureApi())
    )
    output = json.loads(DeterministicFixtureProvider("bounded_edit").generate(request))
    output["operations"] *= 33
    with pytest.raises(ProposalError, match="1..32 operations"):
        ProviderOutputV1.parse(json.dumps(output).encode("utf-8"))


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda output: output.__setitem__("request_id", "sha256:substituted"), "exact request/base binding"),
        (
            lambda output: output["operations"].__setitem__(
                0,
                {
                    "schema": "maude.plan-operation/v1",
                    "operation": {"type": "remove_node", "node_id": "pn_verify"},
                },
            ),
            "exceeds proposal scope",
        ),
    ],
)
def test_local_validation_keeps_immutable_bindings_and_scope_closed(
    tmp_path, mutation, message
):
    svc, base = service(tmp_path)
    request = request_for(
        svc, base, SwitchyardProposalProvider(profile(), FixtureApi())
    )
    output = json.loads(DeterministicFixtureProvider("bounded_edit").generate(request))
    mutation(output)
    with pytest.raises(ProposalError, match=message):
        proposal_from_provider_output(
            request,
            json.dumps(output).encode("utf-8"),
            provider_id="openrouter",
            model_id="openai/gpt-5.6-terra",
            model_version="switchyard-direct-api-v3",
            created_at="2026-09-12T00:00:00Z",
        )


def test_markdown_fenced_json_is_still_refused_without_lenient_repair(tmp_path):
    class FencedApi(FixtureApi):
        def run(self, *args, **kwargs):
            result = super().run(*args, **kwargs)
            result["worker_output"] = "```json\n" + result["worker_output"] + "\n```"
            return result
    provider = SwitchyardProposalProvider(profile(), FencedApi())
    svc, base = service(tmp_path)
    request = request_for(svc, base, provider)
    with pytest.raises(ProposalError, match="not exact UTF-8 JSON"):
        svc.generate(request, provider)
    assert svc.proposals.proposal_for_request(request.request_id) is None


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
