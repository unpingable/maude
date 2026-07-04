# SPDX-License-Identifier: Apache-2.0
"""M-2 plan ingestion — the M-1 plan-envelope contract, executable.

Parses/validates plan envelopes per ``docs/specs/plan-envelope-v0.md``
(including the CD-1a governance binding, §7) and admits them for execution.
Format validation is not authority; governance admission reads recorded
status and witnesses — it never adjudicates.
"""

from maude.plan.envelope import (
    AdmissionRecord,
    GovernanceBinding,
    PlanEnvelope,
    PlanRefusal,
    REFUSAL_GOVERNANCE_APPROVAL_UNVERIFIED,
    REFUSAL_GOVERNANCE_NOT_APPROVED,
    REFUSAL_GOVERNANCE_REF_MISMATCH,
    REFUSAL_INVALID_PLAN_ENVELOPE,
    REFUSAL_SUBMITTER_LIMITS_MISSING,
    admit_for_execution,
    parse_plan_envelope,
)

__all__ = [
    "AdmissionRecord",
    "GovernanceBinding",
    "PlanEnvelope",
    "PlanRefusal",
    "REFUSAL_GOVERNANCE_APPROVAL_UNVERIFIED",
    "REFUSAL_GOVERNANCE_NOT_APPROVED",
    "REFUSAL_GOVERNANCE_REF_MISMATCH",
    "REFUSAL_INVALID_PLAN_ENVELOPE",
    "REFUSAL_SUBMITTER_LIMITS_MISSING",
    "admit_for_execution",
    "parse_plan_envelope",
]
