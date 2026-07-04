# SPDX-License-Identifier: Apache-2.0
"""Presentation layer — plain-ops rendering of the governance/cybernetics terms.

This module NEVER changes contract vocabulary. The wire/spec terms — refusal
class codes (``plan-envelope-v0`` §4), ``governance_status`` values (§7), field
names — stay exactly as the parser and daemon define them. What lives here is
only how those terms are *shown to a human operator*.

Three-layer disclosure (docs/candidates/WORK_CONTAINER.md):

* **surface** — plain ops words, the first thing an operator reads.
* **detail** — plain "what happened / what to do", still ops language.
* **law**    — the underlying contract/cybernetics term, shown only on a `why`
               drilldown for someone who wants the deep view.

Freight metaphor words (container/manifest/customs) are the *middle* teaching
layer and belong in docs/help, not on this surface — see the candidate note.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Explanation:
    """Three-layer rendering of one governed concept. ``law`` carries the raw
    contract term so `why` can disclose it without the surface ever showing it."""

    surface: str
    detail: str
    law: str


# refusal_class code (CONTRACT, unchanged) -> operator-facing explanation.
# Keys MUST stay byte-identical to envelope.REFUSAL_* — they are the wire codes.
REFUSAL_LABELS: dict[str, Explanation] = {
    "invalid_plan_envelope": Explanation(
        surface="Plan file is malformed",
        detail="The plan file didn't parse. Check the header block at the top and try again.",
        law="refusal_class=invalid_plan_envelope (plan-envelope-v0 §4)",
    ),
    "submitter_limits_missing": Explanation(
        surface="Automated plan is missing its limits",
        detail=(
            "A plan submitted by an automated agent must state a token budget and "
            "a path scope before it can run. Add both and resubmit."
        ),
        law="refusal_class=submitter_limits_missing (§3 — synthetic submitters carry explicit limits)",
    ),
    "governance_not_approved": Explanation(
        surface="Not approved yet",
        detail=(
            "This plan is still a draft. It needs an operator sign-off before it "
            "can run — drafts can be checked and inspected, but never executed."
        ),
        law="refusal_class=governance_not_approved; governance_status != approved (§7)",
    ),
    "governance_ref_mismatch": Explanation(
        surface="Approval doesn't match the files",
        detail=(
            "The approval points at a different version of the files than what's "
            "on disk now (content hash mismatch). Re-approve against the current files."
        ),
        law="refusal_class=governance_ref_mismatch (§7 — cited hash != resolved witness hash)",
    ),
    "governance_approval_unverified": Explanation(
        surface="Can't verify the approval",
        detail=(
            "There's no proof on file backing this approval. A status word by "
            "itself isn't proof — the approval act has to be independently recorded."
        ),
        law=(
            "refusal_class=governance_approval_unverified; a status field is never "
            "its own evidence, and there is no downgrade-to-ungoverned path (§7)"
        ),
    ),
}

_UNKNOWN_REFUSAL = Explanation(
    surface="Plan blocked",
    detail="The plan was refused before it could run.",
    law="",
)


def refusal_explanation(refusal_class: str, detail: str = "") -> Explanation:
    """Operator-facing rendering for a refusal class. Unknown codes degrade
    loudly (surfaced, never swallowed): the raw code + detail become the law
    line so nothing is hidden."""
    exp = REFUSAL_LABELS.get(refusal_class)
    if exp is not None:
        return exp
    law = f"refusal_class={refusal_class}"
    if detail:
        law += f" — {detail}"
    return Explanation(
        surface=_UNKNOWN_REFUSAL.surface,
        detail=detail or _UNKNOWN_REFUSAL.detail,
        law=law,
    )


# governance_status value (CONTRACT) -> plain surface word.
GOVERNANCE_STATUS_SURFACE: dict[str, str] = {
    "candidate": "draft",
    "approved": "approved",
    "refused": "blocked",
    "obstructed": "blocked",
}


def status_surface(governance_status: str) -> str:
    """Plain word for a governance_status value; unknown values pass through."""
    return GOVERNANCE_STATUS_SURFACE.get(governance_status, governance_status)
