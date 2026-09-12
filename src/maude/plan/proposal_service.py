# SPDX-License-Identifier: Apache-2.0
"""Canonical orchestration for proposal generation, preview, and acceptance."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable
import uuid

from maude.plan.proposal_store import (
    ProposalAcceptanceReceiptV1,
    ProposalLifecycle,
    ProposalRejectionReceiptV1,
    ProposalStore,
)
from maude.plan.proposals import (
    PlanEditProposalRequestV1,
    PlanEditProposalV1,
    PlanEditProvider,
    ProposalError,
    ProposalFindingContextV1,
    ProposalPreviewV1,
    ProposalScopeV1,
    preview_operation_sequence,
    proposal_from_provider_output,
)
from maude.plan.store import DraftConflict, DraftStore, EditOrigin


@dataclass(frozen=True)
class ProposalProjectionV1:
    proposal: PlanEditProposalV1
    lifecycle: ProposalLifecycle
    preview: ProposalPreviewV1
    disposition: ProposalAcceptanceReceiptV1 | ProposalRejectionReceiptV1 | None

    def to_data(self) -> dict[str, object]:
        return {
            "disposition": None
            if self.disposition is None
            else self.disposition.to_data(),
            "lifecycle": self.lifecycle.value,
            "preview": {
                "diff": self.preview.diff.to_data(),
                "resulting_plan_digest": self.preview.document.digest,
            },
            "proposal": self.proposal.to_data(),
            "schema": "maude.plan-edit-proposal-projection/v1",
        }


class ProposalService:
    """Only this acceptance boundary turns agent operations into a revision."""

    def __init__(
        self,
        drafts: DraftStore,
        proposals: ProposalStore,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.drafts = drafts
        self.proposals = proposals
        self._now = now

    def _time(self) -> str:
        return self._now().astimezone(UTC).isoformat().replace("+00:00", "Z")

    def request(
        self,
        *,
        draft_id: str,
        base_revision_id: str,
        task: str,
        scope: ProposalScopeV1,
        findings: tuple[ProposalFindingContextV1, ...],
        provider: PlanEditProvider,
        generation_id: str | None = None,
    ) -> PlanEditProposalRequestV1:
        revision = self.drafts.revision(base_revision_id)
        if revision.draft_id != draft_id:
            raise ProposalError("proposal base revision belongs to another draft")
        generation_id = generation_id or "generation_" + uuid.uuid4().hex
        existing = self.proposals.request_for_generation(generation_id)
        if existing is not None:
            expected = (
                draft_id,
                base_revision_id,
                revision.plan_digest,
                task,
                scope,
                findings,
                provider.descriptor.provider_id,
                provider.descriptor.model_id,
            )
            actual = (
                existing.draft_id,
                existing.base_revision_id,
                existing.base_plan_digest,
                existing.task,
                existing.scope,
                existing.findings,
                existing.requested_provider_id,
                existing.requested_model_id,
            )
            if actual != expected:
                raise ProposalError(
                    "proposal generation identity was reused with substituted request content"
                )
            return existing
        if self.drafts.current(draft_id).revision_id != base_revision_id:
            raise DraftConflict(
                "proposal request target is stale; it was not retargeted"
            )
        known = {node.node_id for node in revision.document.nodes}
        if (
            not set(scope.target_node_ids) <= known
            and "add_node" not in scope.allowed_operation_types
        ):
            raise ProposalError("proposal scope contains an unknown PlanNode")
        projection = self.drafts.projection(draft_id)
        canonical_findings = {
            finding.finding_id: ProposalFindingContextV1.from_finding(finding)
            for receipt in projection.checks
            if receipt.applicability.value in {"current_pass", "current_findings"}
            for finding in receipt.receipt.findings
        }
        if any(canonical_findings.get(item.finding_id) != item for item in findings):
            raise ProposalError(
                "proposal request contains a finding not established by the current applicable check"
            )
        if scope.kind == "exact_finding":
            selected = canonical_findings.get(scope.finding_id or "")
            if selected is None or selected not in findings:
                raise ProposalError(
                    "exact_finding scope must bind a current applicable finding"
                )
            expected_targets = (
                () if selected.target_node_id is None else (selected.target_node_id,)
            )
            if scope.target_node_ids != expected_targets:
                raise ProposalError(
                    "finding scope target contradicts the canonical finding"
                )
        request = PlanEditProposalRequestV1.create(
            draft_id=draft_id,
            generation_id=generation_id,
            base_revision_id=base_revision_id,
            document=revision.document,
            task=task,
            scope=scope,
            findings=findings,
            requested_provider_id=provider.descriptor.provider_id,
            requested_model_id=provider.descriptor.model_id,
            created_at=self._time(),
        )
        return self.proposals.put_request(request)

    def generate(
        self, request: PlanEditProposalRequestV1, provider: PlanEditProvider
    ) -> PlanEditProposalV1:
        if (provider.descriptor.provider_id, provider.descriptor.model_id) != (
            request.requested_provider_id,
            request.requested_model_id,
        ):
            raise ProposalError("provider identity does not match the exact request")
        existing = self.proposals.proposal_for_request(request.request_id)
        if existing is not None:
            return existing
        output = b""
        try:
            if self.proposals.cancellation_requested(request.request_id):
                raise ProposalError("proposal generation was cancelled")
            output = provider.generate(request)
            if self.proposals.cancellation_requested(request.request_id):
                raise ProposalError("proposal generation was cancelled")
            if not isinstance(output, bytes):
                raise ProposalError("provider output must be exact bytes")
            proposal = proposal_from_provider_output(
                request,
                output,
                provider_id=provider.descriptor.provider_id,
                model_id=provider.descriptor.model_id,
                model_version=provider.descriptor.model_version,
                created_at=self._time(),
            )
            return self.proposals.put_proposal(proposal)
        except (ProposalError, TypeError, ValueError) as exc:
            self.proposals.refuse_generation(
                request.request_id,
                provider.descriptor.provider_id,
                provider.descriptor.model_id,
                output,
                str(exc),
            )
            if isinstance(exc, ProposalError):
                raise
            raise ProposalError(str(exc)) from exc

    def project(self, proposal_id: str) -> ProposalProjectionV1:
        proposal = self.proposals.proposal(proposal_id)
        base = self.drafts.revision(proposal.base_revision_id)
        if (
            base.draft_id != proposal.draft_id
            or base.plan_digest != proposal.base_plan_digest
        ):
            raise ProposalError(
                "proposal base binding contradicts Plan Core persistence"
            )
        preview = preview_operation_sequence(
            base.document, proposal.operations, proposal.scope
        )
        disposition = self.proposals.disposition(proposal_id)
        if isinstance(disposition, ProposalAcceptanceReceiptV1):
            lifecycle = ProposalLifecycle.ACCEPTED
        elif isinstance(disposition, ProposalRejectionReceiptV1):
            lifecycle = ProposalLifecycle.REJECTED
        elif (
            self.drafts.current(proposal.draft_id).revision_id
            != proposal.base_revision_id
        ):
            lifecycle = ProposalLifecycle.STALE
        else:
            lifecycle = ProposalLifecycle.PROPOSED
        return ProposalProjectionV1(proposal, lifecycle, preview, disposition)

    def accept(
        self, proposal_id: str, *, accepting_actor: str
    ) -> ProposalAcceptanceReceiptV1:
        proposal = self.proposals.proposal(proposal_id)
        if self.proposals.cancellation_requested(proposal.request_id):
            raise ProposalError("cancelled proposal generation cannot be accepted")
        disposition = self.proposals.disposition(proposal_id)
        if isinstance(disposition, ProposalAcceptanceReceiptV1):
            return disposition
        if isinstance(disposition, ProposalRejectionReceiptV1):
            raise ProposalError("rejected proposal cannot be accepted")
        base = self.drafts.revision(proposal.base_revision_id)
        if (
            base.draft_id != proposal.draft_id
            or base.plan_digest != proposal.base_plan_digest
        ):
            raise ProposalError(
                "proposal base binding contradicts Plan Core persistence"
            )
        preview = preview_operation_sequence(
            base.document, proposal.operations, proposal.scope
        )
        saved = self.drafts.save_successor(
            proposal.draft_id,
            proposal.base_revision_id,
            preview.document,
            edit_origin=EditOrigin.AGENT,
        )
        return self.proposals.record_acceptance(
            proposal,
            resulting_revision_id=saved.revision_id,
            resulting_plan_digest=saved.plan_digest,
            accepting_actor=accepting_actor,
        )

    def reject(
        self, proposal_id: str, *, rejecting_actor: str, reason: str
    ) -> ProposalRejectionReceiptV1:
        proposal = self.proposals.proposal(proposal_id)
        return self.proposals.reject(
            proposal, rejecting_actor=rejecting_actor, reason=reason
        )
