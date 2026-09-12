# SPDX-License-Identifier: Apache-2.0
"""Bounded Maude proposal caller for Switchyard direct API v2.

This is an enrollment adapter, not a second transport.  Switchyard owns the
single claim/contact/inspection lifecycle; Maude owns prompt construction,
proposal-byte validation, preview, and explicit human acceptance.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from maude.plan.document import canonical_json_bytes, content_digest
from maude.plan.proposals import (
    PlanEditProposalRequestV1,
    ProposalError,
    ProviderDescriptorV1,
)

DIRECT_REQUEST_DOMAIN = b"switchyard.direct-api-request.digest/v1\0"
DIRECT_BINDING_DOMAIN = b"switchyard.direct-api-owner-binding.digest/v1\0"
OWNER_ID = "maude.proposal-service"
OWNER_PROFILE_SCHEMA = "maude.switchyard-proposal-profile/v1"
UPDATE_NODE_OPERATION_EXAMPLE = {
    "schema": "maude.plan-operation/v1",
    "operation": {
        "type": "update_node",
        "node": {
            "id": "pn_example",
            "description": "Replacement description",
            "depends_on": [],
            "work": None,
            "acceptance_criteria": [],
            "stop_conditions": [],
        },
    },
}


class SwitchyardDirectApi(Protocol):
    """The installed Switchyard v2 entry point; implementations retain custody."""

    def run(self, request: dict, admitted_input: bytes, owner_binding: dict, *,
            cancellation_requested: Callable[[], bool]) -> dict: ...


class SwitchyardAttemptError(ProposalError):
    """Stable retained-generation refusal coordinate for a nonproposal attempt."""
    def __init__(self, state: object, dispatch: str):
        super().__init__(f"Switchyard attempt state={state!s} dispatch={dispatch}")


@dataclass(frozen=True)
class SwitchyardProposalProfileV1:
    """Operator-selected, closed limits for one Maude proposal-service owner."""

    profile_id: str
    provider_id: str
    model_id: str
    account_id: str
    timeout_seconds: int
    maximum_input_bytes: int
    maximum_response_bytes: int
    maximum_output_bytes: int
    maximum_prompt_tokens: int
    maximum_completion_tokens: int
    maximum_total_tokens: int
    maximum_concurrent_requests: int
    spend_budget_id: str
    spend_budget_micros: int
    reserved_spend_micros: int
    prompt_token_price_micros: int
    completion_token_price_micros: int

    def __post_init__(self) -> None:
        if not self.profile_id or not self.provider_id or not self.model_id or not self.account_id:
            raise ProposalError("Switchyard profile identities must be non-empty")
        if self.provider_id != "openrouter":
            raise ProposalError("Maude enrollment supports only the Switchyard OpenRouter profile")
        for name, value, low, high in (
            ("timeout_seconds", self.timeout_seconds, 1, 300),
            ("maximum_input_bytes", self.maximum_input_bytes, 1, 1024 * 1024),
            ("maximum_response_bytes", self.maximum_response_bytes, 1024, 16 * 1024 * 1024),
            ("maximum_output_bytes", self.maximum_output_bytes, 1, 16 * 1024 * 1024),
            ("maximum_prompt_tokens", self.maximum_prompt_tokens, 1, 2_000_000),
            ("maximum_completion_tokens", self.maximum_completion_tokens, 1, 2_000_000),
            ("maximum_total_tokens", self.maximum_total_tokens, 1, 2_000_000),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
                raise ProposalError(f"invalid Switchyard profile {name}")
        if self.maximum_prompt_tokens + self.maximum_completion_tokens > self.maximum_total_tokens:
            raise ProposalError("prompt and completion token limits exceed total token limit")
        if self.maximum_input_bytes + 512 > self.maximum_prompt_tokens:
            raise ProposalError("input byte limit exceeds conservative prompt token limit")
        if not isinstance(self.maximum_concurrent_requests, int) or isinstance(self.maximum_concurrent_requests, bool) or not 1 <= self.maximum_concurrent_requests <= 64:
            raise ProposalError("invalid Switchyard profile maximum_concurrent_requests")
        if not self.spend_budget_id:
            raise ProposalError("Switchyard spend budget identity must be non-empty")
        for name, value in (("spend_budget_micros", self.spend_budget_micros),
                            ("reserved_spend_micros", self.reserved_spend_micros),
                            ("prompt_token_price_micros", self.prompt_token_price_micros),
                            ("completion_token_price_micros", self.completion_token_price_micros)):
            if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 10**12:
                raise ProposalError(f"invalid Switchyard profile {name}")
        if self.reserved_spend_micros > self.spend_budget_micros:
            raise ProposalError("Switchyard request reservation exceeds profile spend budget")
        if self.reserved_spend_micros != (self.maximum_prompt_tokens * self.prompt_token_price_micros
                                          + self.maximum_completion_tokens * self.completion_token_price_micros):
            raise ProposalError("Switchyard reservation is not the fixed-price token envelope")


class SwitchyardProposalProvider:
    """Turn one immutable Plan Core request into one owner-bound API attempt."""

    def __init__(self, profile: SwitchyardProposalProfileV1, api: SwitchyardDirectApi,
                 *, cancellation_requested: Callable[[], bool] = lambda: False) -> None:
        self.profile = profile
        self.api = api
        self.cancellation_requested = cancellation_requested
        self.descriptor = ProviderDescriptorV1(profile.provider_id, profile.model_id, "switchyard-direct-api-v2")

    @classmethod
    def from_switchyard_state(cls, profile: SwitchyardProposalProfileV1, state: Path,
                              *, cancellation_requested: Callable[[], bool] = lambda: False,
                              credential_source: Callable[[str], str | None] | None = None) -> "SwitchyardProposalProvider":
        """Opt-in local-service wiring; no default UI route selects it."""
        try:
            from switchyard.direct_api import DirectApiCaller
        except ImportError as error:
            raise ProposalError("installed Switchyard direct API v2 runtime is required") from error
        kwargs = {} if credential_source is None else {"credential_source": credential_source}
        return cls(profile, DirectApiCaller(state, **kwargs), cancellation_requested=cancellation_requested)

    def _input(self, proposal_request: PlanEditProposalRequestV1) -> bytes:
        operation_example = canonical_json_bytes(UPDATE_NODE_OPERATION_EXAMPLE).decode("utf-8")
        return canonical_json_bytes({
            "instruction": (
                "Return only one UTF-8 JSON maude.plan-edit-provider-output/v1 object. "
                "Required keys: schema, request_id, draft_id, base_revision_id, base_plan_digest, "
                "operations (one to 32 maude.plan-operation/v1 values), rationale. "
                f"Generic update_node operation example: {operation_example}. "
                "An update_node operation supplies the complete replacement node; preserve every field not selected for change. "
                "Copy every request/base binding exactly. Do not execute, accept, authorize, or describe an action outside scope."
            ),
            "proposal_request": proposal_request.to_data(),
            "schema": "maude.switchyard-proposal-input/v1",
        })

    def _records(self, proposal_request: PlanEditProposalRequestV1, admitted_input: bytes) -> tuple[dict, dict]:
        # These JSON values use only strings, booleans, and bounded integers, the
        # interoperable canonical subset required by Switchyard's RFC 8785 boundary.
        dispatch = "maude.dispatch." + proposal_request.request_id.removeprefix("sha256:")
        attempt = "maude.attempt." + proposal_request.generation_id
        request = {
            "schema": "switchyard.direct-api-request/v2",
            "request_id": proposal_request.request_id,
            "work_attempt_id": attempt,
            "dispatch_occurrence_id": dispatch,
            "admitted_input_sha256": content_digest(admitted_input),
            "provider_id": self.profile.provider_id,
            "model_id": self.profile.model_id,
            "account_id": self.profile.account_id,
            "credential_source": "maude-dedicated-config:OPENROUTER_API_KEY",
            "adapter_protocol": "switchyard.openrouter-chat-completions/v1",
            "endpoint": "https://openrouter.ai/api/v1/chat/completions",
            "timeout_seconds": self.profile.timeout_seconds,
            "maximum_input_bytes": self.profile.maximum_input_bytes,
            "maximum_response_bytes": self.profile.maximum_response_bytes,
            "maximum_output_bytes": self.profile.maximum_output_bytes,
            "maximum_prompt_tokens": self.profile.maximum_prompt_tokens,
            "maximum_completion_tokens": self.profile.maximum_completion_tokens,
            "maximum_total_tokens": self.profile.maximum_total_tokens,
            "maximum_concurrent_requests": self.profile.maximum_concurrent_requests,
            "spend_budget_id": self.profile.spend_budget_id,
            "spend_budget_micros": self.profile.spend_budget_micros,
            "reserved_spend_micros": self.profile.reserved_spend_micros,
            "prompt_token_price_micros": self.profile.prompt_token_price_micros,
            "completion_token_price_micros": self.profile.completion_token_price_micros,
            "internal_provider_retry_count": 0,
            "semantic_retry": False,
            "allow_provider_model_fallback": False,
            "authority_effect": "LOCAL_AGENT_COMPUTE_SCHEDULING_ONLY",
        }
        request["request_digest"] = content_digest(DIRECT_REQUEST_DOMAIN + canonical_json_bytes(request))
        binding = {
            "schema": "switchyard.direct-api-owner-binding/v2",
            **{key: request[key] for key in (
                "request_digest", "request_id", "work_attempt_id", "dispatch_occurrence_id",
                "admitted_input_sha256", "provider_id", "model_id", "account_id",
                "credential_source", "adapter_protocol", "endpoint", "authority_effect",
            )},
            "owner_id": OWNER_ID,
            "owner_profile_id": self.profile.profile_id,
            "proposal_request_id": proposal_request.request_id,
            "proposal_request_digest": content_digest(canonical_json_bytes(proposal_request.to_data())),
        }
        binding["binding_digest"] = content_digest(DIRECT_BINDING_DOMAIN + canonical_json_bytes(binding))
        return request, binding

    def generate(self, request: PlanEditProposalRequestV1) -> bytes:
        admitted_input = self._input(request)
        if len(admitted_input) > self.profile.maximum_input_bytes:
            raise ProposalError("Maude proposal input exceeds enrolled Switchyard byte limit")
        direct_request, binding = self._records(request, admitted_input)
        result = self.api.run(direct_request, admitted_input, binding,
                              cancellation_requested=self.cancellation_requested)
        if not isinstance(result, dict) or result.get("state") != "PROVIDER_COMPLETED":
            state = result.get("state") if isinstance(result, dict) else "INVALID_RESULT"
            raise SwitchyardAttemptError(state, direct_request["dispatch_occurrence_id"])
        if result.get("acceptance_state") != "NOT_EVALUATED_BY_SWITCHYARD":
            raise ProposalError("Switchyard result crossed the acceptance boundary")
        execution = result.get("reported_execution")
        if not isinstance(execution, dict) or execution.get("model_id") != self.profile.model_id:
            raise ProposalError("Switchyard response model does not match the enrolled profile")
        usage = result.get("usage")
        if not isinstance(usage, dict) or any(not isinstance(usage.get(key), int) for key in (
            "prompt_tokens", "completion_tokens", "total_tokens"
        )):
            raise ProposalError("Switchyard response lacks observable token usage for the enrolled budget")
        if (usage["prompt_tokens"] > self.profile.maximum_prompt_tokens
                or usage["completion_tokens"] > self.profile.maximum_completion_tokens
                or usage["total_tokens"] > self.profile.maximum_total_tokens):
            raise ProposalError("Switchyard response exceeds the enrolled token budget")
        output = result.get("worker_output")
        if not isinstance(output, str):
            raise ProposalError("Switchyard response has no proposal bytes")
        raw = output.encode("utf-8")
        if len(raw) > self.profile.maximum_output_bytes:
            raise ProposalError("Switchyard response exceeds the enrolled output byte limit")
        return raw
