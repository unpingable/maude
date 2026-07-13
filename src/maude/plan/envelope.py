# SPDX-License-Identifier: Apache-2.0
"""Plan envelope parser + execution admission (M-2, human path).

Implements ``docs/specs/plan-envelope-v1.md`` (the S6 versioned contract:
``plan_version`` is the schema discriminator; v1 carries a first-class
``execution_request`` block; v0 is retired for authorship and decodes only for a
frozen ``plan_ref``) plus the CD-1a governance binding (§7). Load-bearing
disciplines:

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
#: envelope field is equally invalid). ``execution_request.*`` are the v1
#: request block's citable sub-fields (S6); ``scope_allowlist`` is v0-only.
PROJECTABLE_FIELDS = frozenset(
    {
        "scope_allowlist",
        "stop_conditions.forbidden_paths",
        "stop_conditions.budget_tokens",
        "execution_request.write_paths",
        "execution_request.commands",
    }
)

#: S6 — the closed, explicit set of v0 ``plan_ref``s the retired v0 path still
#: decodes. NOT an unversioned fallback: a ``plan_version: 0`` plan whose hash
#: is absent here refuses. Sole member is the committed NS-1 candidate specimen
#: (docs/campaigns/nightshift-functional-mvp/specimens/ns-1-refusal-registry/
#: plan.md). Registered + adjudicated in AG's S6 design note
#: (design-s6-execution-request-schema.md). Growth is by explicit operator act
#: only. Doctrine: approval attaches to plan BYTES, not reconstructed intent —
#: schema migration creates a SUCCESSOR artifact, never revises a predecessor.
FROZEN_V0_PLAN_REFS = frozenset(
    {
        "sha256:da241bc77f8b209c3a25a21866fbde22f2a8b799d1ea3b61d588a727849a1b47",
    }
)

#: v1 ``execution_request`` axis values. ``requested`` never grants (activation
#: locks the axis and records it in ``unmet_axes``); it only makes the ask
#: legible. ``denied`` is the default.
AXIS_VALUES = frozenset({"denied", "requested"})
#: v1 horizons a plan may request (still validated/capped at mint).
REQUEST_HORIZONS = frozenset({"run", "session"})

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
        "execution_request",
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
class CommandRequest:
    """One structured command a v1 plan requests — a program + an argv prefix,
    never a shell string. ``"cargo test"`` → ``program="cargo",
    argv_prefix=("test",)``. The grant-use gate matches on parsed tokens; the
    plan declares them explicitly (S6) rather than the projector inferring them
    from a referenced RationCard digest (the retired v0 path)."""

    program: str
    argv_prefix: tuple[str, ...]


@dataclass(frozen=True)
class ExecutionRequestBlock:
    """v1 (S6) — the plan's first-class, in-artifact request for execution
    scope. Carries NO authority: a plan requests, only activation mints. This is
    what the operator's approval attaches to, made legible in the plan bytes
    instead of reconstructed from ``scope_allowlist`` + the RationCard.

    ``network``/``git`` are axis values (``denied`` default | ``requested``); a
    ``requested`` axis is still locked at mint and surfaced in ``unmet_axes`` —
    declaration is not grant."""

    write_paths: tuple[str, ...]
    commands: tuple[CommandRequest, ...]
    network: str = "denied"
    git: str = "denied"
    horizon: str = "run"


@dataclass(frozen=True)
class PlanEnvelope:
    """A parsed, validated M-1 plan. ``plan_ref`` is the sha256 of the full
    submitted document bytes — the executed envelope is immutable and
    content-addressed; post-run certification lands in reports, never here.

    ``scope_allowlist`` is the v0 write-scope field (frozen specimens only);
    ``execution_request`` is the v1 first-class request block (S6). Exactly one
    is populated per the plan's ``plan_version`` — never both."""

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
    execution_request: ExecutionRequestBlock | None = None


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
        elif top == "execution_request":
            er = envelope_fields.get("execution_request") or {}
            sub = key.split(".", 1)[1]
            present = isinstance(er, dict) and er.get(sub) is not None
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


def _axis_value(value: object, name: str) -> str:
    """v1 axis field → ``denied`` (default) | ``requested``. ``requested`` is a
    legible ask, never a grant — activation locks the axis regardless."""
    if value is None:
        return "denied"
    if value not in AXIS_VALUES:
        raise _refuse(
            f"execution_request.{name} {value!r} not in {sorted(AXIS_VALUES)}"
        )
    return value


def _parse_command_requests(raw: object) -> tuple[CommandRequest, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, (list, tuple)):
        raise _refuse("execution_request.commands must be a list of {program, argv_prefix} maps")
    out: list[CommandRequest] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise _refuse(
                f"execution_request.commands[{i}] must be a map {{program, argv_prefix}} "
                "(structured tokens, never a shell string)"
            )
        unknown = set(item) - {"program", "argv_prefix"}
        if unknown:
            raise _refuse(f"execution_request.commands[{i}] has unknown keys {sorted(unknown)}")
        program = item.get("program")
        if not isinstance(program, str) or not program.strip():
            raise _refuse(f"execution_request.commands[{i}].program must be a non-empty string")
        argv_raw = item.get("argv_prefix", [])
        if not isinstance(argv_raw, (list, tuple)) or not all(
            isinstance(a, str) for a in argv_raw
        ):
            raise _refuse(
                f"execution_request.commands[{i}].argv_prefix must be a list of strings"
            )
        out.append(CommandRequest(program=program.strip(), argv_prefix=tuple(argv_raw)))
    return tuple(out)


def _parse_execution_request(raw: object) -> ExecutionRequestBlock:
    """v1 (S6) — parse the first-class request block. Structure only; the
    §7 copy-with-citation check against AG source objects happens at admission,
    exactly as the v0 scope_allowlist projection did."""
    if not isinstance(raw, dict):
        raise _refuse("execution_request must be a map (v1 first-class request block)")
    unknown = set(raw) - {"write_paths", "commands", "network", "git", "horizon"}
    if unknown:
        raise _refuse(f"execution_request has unknown keys {sorted(unknown)}")
    write_paths = _str_list(raw.get("write_paths"), "execution_request.write_paths")
    commands = _parse_command_requests(raw.get("commands"))
    if not write_paths and not commands:
        raise _refuse(
            "execution_request must declare at least one of write_paths or commands "
            "(an empty request grants nothing — omit the governance block instead)"
        )
    horizon = raw.get("horizon", "run")
    if horizon not in REQUEST_HORIZONS:
        raise _refuse(
            f"execution_request.horizon {horizon!r} not in {sorted(REQUEST_HORIZONS)}"
        )
    return ExecutionRequestBlock(
        write_paths=write_paths,
        commands=commands,
        network=_axis_value(raw.get("network"), "network"),
        git=_axis_value(raw.get("git"), "git"),
        horizon=horizon,
    )


def _parse_common(data: dict) -> dict:
    """Fields shared by every plan version (goal … stop_conditions). Version
    dispatch adds the write-scope surface (v0 scope_allowlist / v1
    execution_request) and the synthetic-limits check on top."""
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

    return {
        "goal": goal.strip(),
        "workspace": workspace.strip(),
        "submitter_kind": submitter_kind,
        "plan_origin": plan_origin,
        "provenance_author": provenance["author"].strip(),
        "provenance_ref": provenance_ref,
        "harness": harness,
        "autopilot_profile": autopilot_profile,
        "steps": steps,
        "acceptance_criteria": acceptance,
        "stop_budget_tokens": stop_budget,
        "stop_forbidden_paths": stop_forbidden,
        "stop_halt_if": stop_halt,
    }


def _parse_v0(data: dict, body: str, plan_ref: str, warnings: tuple[str, ...]) -> PlanEnvelope:
    """Retired v0 decoder — reached ONLY for a frozen ``plan_ref`` (S6). Top-level
    ``scope_allowlist`` is the write scope; no execution_request block."""
    common = _parse_common(data)
    scope_allowlist = _str_list(data.get("scope_allowlist"), "scope_allowlist")
    if common["submitter_kind"] == "synthetic_agent":  # §3
        if common["stop_budget_tokens"] is None or not (scope_allowlist or common["stop_forbidden_paths"]):
            raise PlanRefusal(
                REFUSAL_SUBMITTER_LIMITS_MISSING,
                "synthetic_agent plans require explicit stop_conditions: "
                "budget_tokens AND (scope_allowlist OR forbidden_paths)",
            )
    governance = None
    if data.get("governance") is not None:
        governance = _parse_governance(data["governance"], data)
    return PlanEnvelope(
        plan_version=0,
        scope_allowlist=scope_allowlist,
        execution_request=None,
        governance=governance,
        body=body,
        plan_ref=plan_ref,
        warnings=warnings,
        **common,
    )


def _parse_v1(data: dict, body: str, plan_ref: str, warnings: tuple[str, ...]) -> PlanEnvelope:
    """v1 (S6) — first-class ``execution_request`` block is the write/command
    scope. Legacy top-level ``scope_allowlist`` is FORBIDDEN (no two sources)."""
    common = _parse_common(data)
    if "scope_allowlist" in data:
        raise _refuse(
            "plan_version 1 forbids top-level scope_allowlist (legacy_field_under_v1): "
            "declare write_paths inside execution_request — one source of truth, no precedence rules"
        )
    governed = data.get("governance") is not None
    # A GOVERNED v1 plan must carry the first-class request — that is the S6
    # legibility win: the operator approves a plan whose request is IN the bytes,
    # not reconstructed. An ungoverned plan mints no grant, so the block is moot.
    if governed and data.get("execution_request") is None:
        raise _refuse(
            "a governed plan_version 1 plan requires an execution_request block "
            "(the first-class request the approval attaches to — no inferred boundary)"
        )
    request = (
        _parse_execution_request(data["execution_request"])
        if data.get("execution_request") is not None
        else None
    )
    if common["submitter_kind"] == "synthetic_agent":  # §3
        req_write_paths = request.write_paths if request is not None else ()
        if common["stop_budget_tokens"] is None or not (
            req_write_paths or common["stop_forbidden_paths"]
        ):
            raise PlanRefusal(
                REFUSAL_SUBMITTER_LIMITS_MISSING,
                "synthetic_agent plans require explicit stop_conditions: budget_tokens "
                "AND (execution_request.write_paths OR forbidden_paths)",
            )
    governance = None
    if data.get("governance") is not None:
        governance = _parse_governance(data["governance"], data)
    return PlanEnvelope(
        plan_version=1,
        scope_allowlist=(),
        execution_request=request,
        governance=governance,
        body=body,
        plan_ref=plan_ref,
        warnings=warnings,
        **common,
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

    plan_ref = _SHA256_PREFIX + hashlib.sha256(text.encode("utf-8")).hexdigest()

    # S6 — version is the schema discriminator. v1 is the only authoring
    # surface; v0 decodes ONLY for an explicitly frozen pre-v1 specimen;
    # missing/unknown always refuses. "Unversioned means legacy" — the
    # permanent ambiguity generator — is closed by construction.
    version = data.get("plan_version")
    if version == 1:
        return _parse_v1(data, body, plan_ref, warnings)
    if version == 0:
        if plan_ref not in FROZEN_V0_PLAN_REFS:
            raise _refuse(
                "plan_version 0 is retired (plan_version_retired): author at "
                "plan_version 1 with an execution_request block. Only frozen "
                "pre-v1 specimens decode via the legacy path."
            )
        return _parse_v0(data, body, plan_ref, warnings)
    if version is None:
        raise _refuse(
            "plan_version is required (plan_version_missing) — it is the schema "
            "discriminator; there is no unversioned/legacy default"
        )
    raise _refuse(
        f"unknown plan_version {version!r} (plan_version_unknown); "
        "this contract knows 0 (frozen specimens only) and 1"
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
