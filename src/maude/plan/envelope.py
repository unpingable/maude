# SPDX-License-Identifier: Apache-2.0
"""Plan envelope v0 parser + execution admission (M-2, human path).

Implements ``docs/specs/plan-envelope-v0.md`` verbatim, including the CD-1a
governance binding (§7). Load-bearing disciplines:

- Format validation is NOT authority: a well-formed plan for a forbidden
  action passes here and is refused by AG at the gate.
- Unknown front-matter KEYS are ignored with a warning (forward compat);
  unknown ENUM VALUES refuse (an unrecognized submitter class is not guessed).
- ``governance_status`` is a record, never its own evidence: a written
  ``approved`` is prose until the act it names is independently witnessed.
  Governed execution requires every load-bearing citation VERIFIED against an
  externally produced artifact; the default (no witness resolver) fails
  closed — governed plans do not run.
- Maude manufactures candidate structure, never authority.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

import yaml

# --------------------------------------------------------------------------- #
# Refusal vocabulary (closed; defined by the M-1 spec §4 — never improvised).
# --------------------------------------------------------------------------- #

REFUSAL_INVALID_PLAN_ENVELOPE = "invalid_plan_envelope"
REFUSAL_SUBMITTER_LIMITS_MISSING = "submitter_limits_missing"
REFUSAL_GOVERNANCE_NOT_APPROVED = "governance_not_approved"
REFUSAL_GOVERNANCE_REF_MISMATCH = "governance_ref_mismatch"
REFUSAL_GOVERNANCE_APPROVAL_UNVERIFIED = "governance_approval_unverified"

REFUSAL_CLASSES = frozenset(
    {
        REFUSAL_INVALID_PLAN_ENVELOPE,
        REFUSAL_SUBMITTER_LIMITS_MISSING,
        REFUSAL_GOVERNANCE_NOT_APPROVED,
        REFUSAL_GOVERNANCE_REF_MISMATCH,
        REFUSAL_GOVERNANCE_APPROVAL_UNVERIFIED,
    }
)

SUBMITTER_KINDS = frozenset({"human", "synthetic_agent"})
PLAN_ORIGINS = frozenset(
    {"human_written", "agent_generated", "agent_revised", "imported_from_review"}
)
GOVERNANCE_STATUSES = frozenset({"candidate", "approved", "refused", "obstructed"})
AUTHORITY_SYSTEMS = frozenset({"ag"})

#: Envelope fields a governance projection may cite as its target (§7 —
#: exhaustive rule: an AG-originated enforced constraint missing from
#: ``projected`` is invalid; a projected key that names no enforceable
#: envelope field is equally invalid).
PROJECTABLE_FIELDS = frozenset(
    {
        "scope_allowlist",
        "stop_conditions.forbidden_paths",
        "stop_conditions.budget_tokens",
    }
)

_KNOWN_TOP_KEYS = frozenset(
    {
        "plan_version",
        "goal",
        "workspace",
        "submitter_kind",
        "plan_origin",
        "provenance",
        "harness",
        "autopilot_profile",
        "scope_allowlist",
        "steps",
        "acceptance_criteria",
        "stop_conditions",
        "governance",
    }
)

_GOVERNANCE_KEYS = frozenset(
    {
        "authority_system",
        "playbook_id",
        "playbook_digest",
        "ration_card_digest",
        "queued_playbook_ref",
        "review_packet_ref",
        "approval_ref",
        "governance_status",
        "projected",
    }
)

_SHA256_PREFIX = "sha256:"


class PlanRefusal(Exception):
    """A typed, client-side refusal. Explicitly NOT authority — AG's refusals
    pass through verbatim elsewhere; these are format/admission checks."""

    def __init__(self, refusal_class: str, detail: str) -> None:
        if refusal_class not in REFUSAL_CLASSES:
            raise ValueError(f"unknown refusal class {refusal_class!r}")
        self.refusal_class = refusal_class
        self.detail = detail
        super().__init__(f"[{refusal_class}] {detail}")


def _refuse(detail: str) -> PlanRefusal:
    return PlanRefusal(REFUSAL_INVALID_PLAN_ENVELOPE, detail)


def _is_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and value.startswith(_SHA256_PREFIX)
        and len(value) == len(_SHA256_PREFIX) + 64
        and all(c in "0123456789abcdef" for c in value[len(_SHA256_PREFIX):])
    )


def _str_list(value: object, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(
        isinstance(x, str) and x.strip() for x in value
    ):
        raise _refuse(f"{field_name} must be a list of non-empty strings")
    return tuple(value)


# --------------------------------------------------------------------------- #
# Envelope dataclasses (frozen; parsed once, never mutated).
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class GovernanceBinding:
    """§7 — binds the plan to AG playbook law BY DIGEST/REF ONLY. Maude never
    imports AG internals and never re-implements AG admissibility."""

    authority_system: str
    playbook_id: str
    playbook_digest: str
    ration_card_digest: str
    governance_status: str
    approval_ref: str | None = None
    queued_playbook_ref: str | None = None
    review_packet_ref: str | None = None
    projected: Mapping[str, str] = field(default_factory=dict)

    def load_bearing_citations(self) -> tuple[tuple[str, str], ...]:
        """(name, citation) pairs that governed EXECUTION must verify."""
        out: list[tuple[str, str]] = [
            ("playbook_digest", self.playbook_digest),
            ("ration_card_digest", self.ration_card_digest),
        ]
        if self.queued_playbook_ref is not None:
            out.append(("queued_playbook_ref", self.queued_playbook_ref))
        if self.approval_ref is not None:
            out.append(("approval_ref", self.approval_ref))
        return tuple(out)


@dataclass(frozen=True)
class PlanEnvelope:
    """A parsed, validated M-1 plan. ``plan_ref`` is the sha256 of the full
    submitted document bytes — the executed envelope is immutable and
    content-addressed; post-run certification lands in reports, never here."""

    plan_version: int
    goal: str
    workspace: str
    submitter_kind: str
    plan_origin: str
    provenance_author: str
    provenance_ref: str | None
    harness: str | None
    autopilot_profile: str | None
    scope_allowlist: tuple[str, ...]
    steps: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    stop_budget_tokens: int | None
    stop_forbidden_paths: tuple[str, ...]
    stop_halt_if: str | None
    governance: GovernanceBinding | None
    body: str
    plan_ref: str
    warnings: tuple[str, ...]


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #


def _split_front_matter(text: str) -> tuple[str, str]:
    if not text.startswith("---\n") and not text.startswith("---\r\n"):
        raise _refuse("plan must begin with a YAML front-matter block (---)")
    # find the closing delimiter on its own line
    lines = text.splitlines(keepends=True)
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "".join(lines[1:i]), "".join(lines[i + 1 :])
    raise _refuse("unterminated YAML front-matter block (no closing ---)")


def _parse_governance(raw: object, envelope_fields: dict[str, object]) -> GovernanceBinding:
    if not isinstance(raw, dict):
        raise _refuse("governance must be a map (§7)")
    unknown = set(raw) - _GOVERNANCE_KEYS
    if unknown:
        # Inside the governance block the key set is CLOSED — this is
        # authority-adjacent vocabulary, not forward-compat surface.
        raise _refuse(f"unknown governance key(s): {sorted(unknown)}")

    authority_system = raw.get("authority_system")
    if authority_system not in AUTHORITY_SYSTEMS:
        raise _refuse(
            f"governance.authority_system {authority_system!r} not in "
            f"{sorted(AUTHORITY_SYSTEMS)} (unknown authority systems are not guessed)"
        )
    status = raw.get("governance_status")
    if status not in GOVERNANCE_STATUSES:
        raise _refuse(
            f"governance.governance_status {status!r} not in {sorted(GOVERNANCE_STATUSES)}"
        )
    playbook_id = raw.get("playbook_id")
    if not isinstance(playbook_id, str) or not playbook_id.strip():
        raise _refuse("governance.playbook_id is required (non-empty string)")
    for digest_field in ("playbook_digest", "ration_card_digest"):
        if not _is_digest(raw.get(digest_field)):
            raise _refuse(
                f"governance.{digest_field} must be sha256:<64-hex> "
                f"(got {raw.get(digest_field)!r})"
            )
    queued_ref = raw.get("queued_playbook_ref")
    if queued_ref is not None and not _is_digest(queued_ref):
        raise _refuse("governance.queued_playbook_ref must be sha256:<64-hex> when present")
    if raw.get("review_packet_ref") is not None:
        raise _refuse(
            "governance.review_packet_ref must be null at submit — you cannot "
            "cite the review of a run that has not happened (§7)"
        )
    approval_ref = raw.get("approval_ref")
    if approval_ref is not None and (
        not isinstance(approval_ref, str) or not approval_ref.strip()
    ):
        raise _refuse("governance.approval_ref must be a non-empty string when present")
    if status == "approved" and approval_ref is None:
        raise _refuse("governance_status=approved requires approval_ref naming the act")

    projected_raw = raw.get("projected") or {}
    if not isinstance(projected_raw, dict):
        raise _refuse("governance.projected must be a map of field -> source ref")
    projected: dict[str, str] = {}
    for key, src in projected_raw.items():
        if key not in PROJECTABLE_FIELDS:
            raise _refuse(
                f"governance.projected key {key!r} is not a projectable envelope "
                f"field {sorted(PROJECTABLE_FIELDS)}"
            )
        if not isinstance(src, str) or not src.strip():
            raise _refuse(f"governance.projected[{key!r}] must be a non-empty source ref")
        # projection is copy-with-citation: the projected field must actually
        # be present in the envelope (you cannot cite a source for a value
        # you are not carrying).
        top = key.split(".", 1)[0]
        if top == "stop_conditions":
            stop = envelope_fields.get("stop_conditions") or {}
            sub = key.split(".", 1)[1]
            present = isinstance(stop, dict) and stop.get(sub) is not None
        else:
            present = envelope_fields.get(top) is not None
        if not present:
            raise _refuse(
                f"governance.projected cites {key!r} but the envelope does not "
                f"carry that field — projection is copy-with-citation"
            )
        projected[key] = src

    return GovernanceBinding(
        authority_system=authority_system,
        playbook_id=playbook_id.strip(),
        playbook_digest=raw["playbook_digest"],
        ration_card_digest=raw["ration_card_digest"],
        governance_status=status,
        approval_ref=approval_ref,
        queued_playbook_ref=queued_ref,
        review_packet_ref=None,
        projected=projected,
    )


def parse_plan_envelope(text: str) -> PlanEnvelope:
    """Parse + validate a plan document. Raises :class:`PlanRefusal` with a
    typed class; never returns a half-valid envelope."""

    front, body = _split_front_matter(text)
    try:
        data = yaml.safe_load(front)
    except yaml.YAMLError as exc:  # pragma: no cover - message varies by lib
        raise _refuse(f"front-matter is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise _refuse("front-matter must be a YAML map")

    warnings = tuple(
        f"unknown front-matter key ignored: {k!r}" for k in sorted(set(data) - _KNOWN_TOP_KEYS)
    )

    if data.get("plan_version") != 0:
        raise _refuse(f"unknown plan_version {data.get('plan_version')!r} (this contract is 0)")
    goal = data.get("goal")
    if not isinstance(goal, str) or not goal.strip():
        raise _refuse("goal is required (non-empty string)")
    workspace = data.get("workspace")
    if not isinstance(workspace, str) or not workspace.strip():
        raise _refuse("workspace is required (non-empty string)")
    submitter_kind = data.get("submitter_kind")
    if submitter_kind not in SUBMITTER_KINDS:
        raise _refuse(
            f"submitter_kind {submitter_kind!r} not in {sorted(SUBMITTER_KINDS)} "
            f"(an unrecognized submitter class is not guessed)"
        )
    plan_origin = data.get("plan_origin")
    if plan_origin not in PLAN_ORIGINS:
        raise _refuse(f"plan_origin {plan_origin!r} not in {sorted(PLAN_ORIGINS)}")
    provenance = data.get("provenance")
    if not isinstance(provenance, dict) or not isinstance(provenance.get("author"), str) \
            or not provenance["author"].strip():
        raise _refuse("provenance is required (map with non-empty author)")
    provenance_ref = provenance.get("ref")
    if provenance_ref is not None and not isinstance(provenance_ref, str):
        raise _refuse("provenance.ref must be a string or null")

    harness = data.get("harness")
    if harness is not None and (not isinstance(harness, str) or not harness.strip()):
        raise _refuse("harness must be a non-empty string when present")
    autopilot_profile = data.get("autopilot_profile")
    if autopilot_profile is not None and not isinstance(autopilot_profile, str):
        raise _refuse("autopilot_profile must be a string when present")

    scope_allowlist = _str_list(data.get("scope_allowlist"), "scope_allowlist")
    steps = _str_list(data.get("steps"), "steps")
    acceptance = _str_list(data.get("acceptance_criteria"), "acceptance_criteria")

    stop = data.get("stop_conditions")
    stop_budget: int | None = None
    stop_forbidden: tuple[str, ...] = ()
    stop_halt: str | None = None
    if stop is not None:
        if not isinstance(stop, dict):
            raise _refuse("stop_conditions must be a map")
        budget_raw = stop.get("budget_tokens")
        if budget_raw is not None:
            if not isinstance(budget_raw, int) or isinstance(budget_raw, bool) or budget_raw <= 0:
                raise _refuse("stop_conditions.budget_tokens must be a positive integer")
            stop_budget = budget_raw
        stop_forbidden = _str_list(
            stop.get("forbidden_paths"), "stop_conditions.forbidden_paths"
        )
        halt_raw = stop.get("halt_if")
        if halt_raw is not None:
            if not isinstance(halt_raw, str) or not halt_raw.strip():
                raise _refuse("stop_conditions.halt_if must be a non-empty string")
            stop_halt = halt_raw

    # §3 — synthetic submitters carry explicit limits or refuse.
    if submitter_kind == "synthetic_agent":
        if stop_budget is None or not (scope_allowlist or stop_forbidden):
            raise PlanRefusal(
                REFUSAL_SUBMITTER_LIMITS_MISSING,
                "synthetic_agent plans require explicit stop_conditions: "
                "budget_tokens AND (scope_allowlist OR forbidden_paths)",
            )

    governance = None
    if data.get("governance") is not None:
        governance = _parse_governance(data["governance"], data)

    plan_ref = _SHA256_PREFIX + hashlib.sha256(text.encode("utf-8")).hexdigest()

    return PlanEnvelope(
        plan_version=0,
        goal=goal.strip(),
        workspace=workspace.strip(),
        submitter_kind=submitter_kind,
        plan_origin=plan_origin,
        provenance_author=provenance["author"].strip(),
        provenance_ref=provenance_ref,
        harness=harness,
        autopilot_profile=autopilot_profile,
        scope_allowlist=scope_allowlist,
        steps=steps,
        acceptance_criteria=acceptance,
        stop_budget_tokens=stop_budget,
        stop_forbidden_paths=stop_forbidden,
        stop_halt_if=stop_halt,
        governance=governance,
        body=body,
        plan_ref=plan_ref,
        warnings=warnings,
    )


# --------------------------------------------------------------------------- #
# Execution admission (§7 — three-valued, strict for governed execution)
# --------------------------------------------------------------------------- #

#: A witness resolver maps a citation string to the bytes of an EXTERNALLY
#: produced artifact, or None when unresolvable. The default (None resolver)
#: fails closed: governed plans refuse. Semantics harden at CD-4 when the AG
#: conveyor projection surface is wired; tests inject fakes.
WitnessResolver = Callable[[str], bytes | None]


@dataclass(frozen=True)
class AdmissionRecord:
    """What execution admission established. ``verified`` lists
    (citation-name, status) where status ∈ {verified, not_applicable}. An
    executed governed run never contains an unverified load-bearing citation
    (§7 strict bar)."""

    plan_ref: str
    governed: bool
    verified: tuple[tuple[str, str], ...] = ()


def admit_for_execution(
    env: PlanEnvelope, *, witness_resolver: WitnessResolver | None = None
) -> AdmissionRecord:
    """Gate a parsed envelope for execution. Raises :class:`PlanRefusal`.

    Ungoverned plans admit (their approval is the human submitter's own act —
    M-2 is the human path). Governed plans require ``approved`` status AND
    every load-bearing citation verified against an external witness.
    """

    if env.governance is None:
        return AdmissionRecord(plan_ref=env.plan_ref, governed=False)

    gov = env.governance
    if gov.governance_status != "approved":
        raise PlanRefusal(
            REFUSAL_GOVERNANCE_NOT_APPROVED,
            f"governance_status={gov.governance_status!r}; candidate plans are "
            f"compilable and inspectable, never executable",
        )

    checked: list[tuple[str, str]] = []
    for name, citation in gov.load_bearing_citations():
        witness = witness_resolver(citation) if witness_resolver is not None else None
        if witness is None:
            raise PlanRefusal(
                REFUSAL_GOVERNANCE_APPROVAL_UNVERIFIED,
                f"{name} ({citation!r}) has no resolvable external witness — a "
                f"status field is never its own evidence; there is no "
                f"downgrade-to-ungoverned path",
            )
        if citation.startswith(_SHA256_PREFIX):
            actual = _SHA256_PREFIX + hashlib.sha256(witness).hexdigest()
            if actual != citation:
                raise PlanRefusal(
                    REFUSAL_GOVERNANCE_REF_MISMATCH,
                    f"{name}: cited {citation} but the resolved witness hashes "
                    f"to {actual}",
                )
        checked.append((name, "verified"))

    return AdmissionRecord(
        plan_ref=env.plan_ref, governed=True, verified=tuple(checked)
    )
