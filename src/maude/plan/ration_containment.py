# SPDX-License-Identifier: Apache-2.0
"""Ration-citation containment (S7) — is an execution_request BOUNDED BY the
RationCard it cites, not merely citing it?

S6 made the request legible in the plan bytes and had the plan *cite* a
RationCard; it never checked that the declared effects are a SUBSET of what the
card allows. S7 makes the citation load-bearing:

    execution_request ⊆ cited_ration   on every dimension the card models.

Narrower requests admit; broader requests refuse.

**Cross-repo mirror (documented, not silent).** The authority these effects will
be USED under is AG's `governor.runtime.grant_use_gate`. Maude cannot import AG
internals (architectural boundary — Maude consumes serialized refs, never AG
code), so the containment semantics here are a DELIBERATE MIRROR of that gate:

  - the effect-escaping-flag denylist below mirrors
    `grant_use_gate._EFFECT_ESCAPING_FLAGS`;
  - command containment mirrors its structured `program + argv_prefix` match
    (a request command is contained iff its prefix STARTS WITH an allowed
    prefix — i.e. it is at least as specific — and carries no escape flag);
  - write-path subsumption is defined so that it is CONSISTENT with the gate's
    concrete `_path_within`: `R ⊆ A` means every concrete path the gate would
    admit under R it would also admit under A (property-tested).

If AG's list or matching changes, this mirror must change too. That coupling is
the honest cost of the boundary; it is named here and in the S7 design note, not
hidden. Dimensions the card does not model (horizon, task_kind, …) are reported
as NOT-MODELLED, never silently treated as contained.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

#: MIRROR of governor.runtime.grant_use_gate._EFFECT_ESCAPING_FLAGS (AG). Flags
#: that let an allowlisted program relocate its fs/config effects out of the
#: envelope. A request command whose argv carries one is NOT contained (the gate
#: would refuse it). Keep in sync with AG; see module docstring + S7 design note.
_EFFECT_ESCAPING_FLAGS = frozenset(
    {"-C", "--config", "--target-dir", "--out-dir", "--manifest-path", "--home"}
)

#: RationCard dimensions this predicate can compare against an execution_request.
MODELLED_DIMENSIONS = frozenset({"write_paths", "commands", "network", "git"})
#: execution_request / RationCard fields the card does NOT model as a comparable
#: ceiling — reported honestly, never silently "contained".
NOT_MODELLED = frozenset(
    {"horizon", "doctrine_writes_allowed", "output_is_observe_only", "task_kind"}
)


@dataclass(frozen=True)
class ParsedRation:
    """The comparable surface of a RationCard, parsed from its verified bytes."""

    allowed_write_paths: tuple[str, ...]
    allowed_commands: tuple[tuple[str, tuple[str, ...]], ...]  # (program, argv_prefix)
    network_allowed: bool
    git_allowed: bool


@dataclass(frozen=True)
class ContainmentResult:
    """Outcome of a containment check. ``ok`` iff every modelled dimension of the
    request is contained by the card. ``exceedances`` names each modelled
    dimension that broadened (empty iff ok)."""

    ok: bool
    exceedances: tuple[str, ...] = ()
    detail: str = ""
    not_modelled: tuple[str, ...] = field(default_factory=lambda: tuple(sorted(NOT_MODELLED)))


class RationParseError(ValueError):
    """The cited RationCard bytes could not be parsed into a comparable surface.
    Fail closed — containment cannot be established, so the caller must refuse."""


def _parse_command_string(cmd: str) -> tuple[str, tuple[str, ...]] | None:
    tokens = cmd.split()
    if not tokens:
        return None
    return (tokens[0], tuple(tokens[1:]))


def parse_ration(ration_bytes: bytes) -> ParsedRation:
    """Parse verified RationCard bytes into the comparable surface. Raises
    RationParseError on malformed input (fail closed)."""
    try:
        data = json.loads(ration_bytes)
    except (ValueError, TypeError) as exc:
        raise RationParseError(f"ration is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise RationParseError("ration is not a JSON object")

    raw_paths = data.get("allowed_write_paths", [])
    if not isinstance(raw_paths, (list, tuple)) or not all(
        isinstance(p, str) for p in raw_paths
    ):
        raise RationParseError("allowed_write_paths must be a list of strings")

    raw_cmds = data.get("allowed_shell_commands", [])
    if not isinstance(raw_cmds, (list, tuple)) or not all(
        isinstance(c, str) for c in raw_cmds
    ):
        raise RationParseError("allowed_shell_commands must be a list of strings")
    commands: list[tuple[str, tuple[str, ...]]] = []
    for c in raw_cmds:
        parsed = _parse_command_string(c)
        if parsed is not None:
            commands.append(parsed)

    return ParsedRation(
        allowed_write_paths=tuple(raw_paths),
        allowed_commands=tuple(commands),
        # absence of an axis flag is treated as DENIED (fail closed): a card that
        # does not affirmatively allow the network does not authorize it.
        network_allowed=bool(data.get("network_allowed", False)),
        git_allowed=bool(data.get("git_allowed", False)),
    )


# --------------------------------------------------------------------------- #
# write-path pattern subsumption (consistent with grant_use_gate._path_within)
# --------------------------------------------------------------------------- #


def _pattern_subsumes(allowed: str, requested: str) -> bool:
    """Does allow-pattern ``allowed`` subsume request-pattern ``requested`` —
    i.e. is every concrete path the gate would admit under ``requested`` also
    admitted under ``allowed``? Conservative: unknown shapes are NOT subsumed."""
    if allowed == requested:
        return True
    if allowed.endswith("/**"):
        # allowed matches any depth under its prefix. requested is subsumed iff
        # everything requested lives under that prefix — its shallowest concrete
        # directory prefix must sit under `allowed`'s.
        prefix = allowed[:-2]  # "P/**" -> "P/"
        return _min_concrete_prefix(requested).startswith(prefix)
    if allowed.endswith("/*"):
        # allowed matches exactly ONE level under its prefix. requested is
        # subsumed iff it is a concrete single-level path there (no wildcard, no
        # deeper slash) — `dir/**` and `dir/a/b` are NOT subsumed by `dir/*`.
        prefix = allowed[:-1]  # "P/*" -> "P/"
        if requested.startswith(prefix):
            rest = requested[len(prefix):]
            if rest and "/" not in rest and "*" not in rest:
                return True
        return False
    # allowed is a concrete path: subsumes only an exact match (handled above).
    return False


def _min_concrete_prefix(pattern: str) -> str:
    """The shallowest concrete directory prefix a pattern's matches all share.
    ``P/sub/**`` and ``P/sub/*`` -> ``P/sub/``; a concrete ``P/x`` -> ``P/x``."""
    if pattern.endswith("/**"):
        return pattern[:-2]
    if pattern.endswith("/*"):
        return pattern[:-1]
    return pattern


def write_path_subsumed(requested: str, allowed_patterns: tuple[str, ...]) -> bool:
    """A request write-path is contained iff SOME allowed pattern subsumes it.
    ``..`` traversal is never contained (mirrors the gate)."""
    if not requested or ".." in requested.split("/"):
        return False
    return any(_pattern_subsumes(a, requested) for a in allowed_patterns)


# --------------------------------------------------------------------------- #
# command containment (mirrors grant_use_gate structured match + escape flags)
# --------------------------------------------------------------------------- #


def _carries_escape_flag(argv_prefix: tuple[str, ...]) -> bool:
    return any(tok.split("=", 1)[0] in _EFFECT_ESCAPING_FLAGS for tok in argv_prefix)


def command_contained(
    program: str,
    argv_prefix: tuple[str, ...],
    allowed_commands: tuple[tuple[str, tuple[str, ...]], ...],
) -> bool:
    """A request command ``(program, argv_prefix)`` is contained iff it carries
    no effect-escaping flag AND its prefix STARTS WITH some allowed command's
    prefix (same program) — i.e. the request is at least as specific (narrower)
    as an allowed class. A shorter/other prefix broadens and is not contained."""
    if _carries_escape_flag(argv_prefix):
        return False
    for allowed_program, allowed_prefix in allowed_commands:
        n = len(allowed_prefix)
        if program == allowed_program and tuple(argv_prefix[:n]) == allowed_prefix:
            return True
    return False


# --------------------------------------------------------------------------- #
# the whole check
# --------------------------------------------------------------------------- #


def check_containment(
    write_paths: tuple[str, ...],
    commands: tuple[tuple[str, tuple[str, ...]], ...],  # (program, argv_prefix)
    network_requested: bool,
    git_requested: bool,
    ration: ParsedRation,
) -> ContainmentResult:
    """`execution_request ⊆ ration` across every modelled dimension. Returns the
    set of dimensions that BROADENED (empty iff contained)."""
    exceed: list[str] = []
    details: list[str] = []

    over_paths = [p for p in write_paths if not write_path_subsumed(p, ration.allowed_write_paths)]
    if over_paths:
        exceed.append("write_paths")
        details.append(f"write_paths not subsumed by the ration: {sorted(over_paths)}")

    over_cmds = [
        f"{p} {' '.join(pre)}".strip()
        for (p, pre) in commands
        if not command_contained(p, pre, ration.allowed_commands)
    ]
    if over_cmds:
        exceed.append("commands")
        details.append(f"commands not allowed by the ration: {sorted(over_cmds)}")

    if network_requested and not ration.network_allowed:
        exceed.append("network")
        details.append("network requested but the ration denies network")
    if git_requested and not ration.git_allowed:
        exceed.append("git")
        details.append("git requested but the ration denies git")

    return ContainmentResult(
        ok=not exceed,
        exceedances=tuple(exceed),
        detail="; ".join(details),
    )


__all__ = [
    "MODELLED_DIMENSIONS",
    "NOT_MODELLED",
    "ParsedRation",
    "ContainmentResult",
    "RationParseError",
    "parse_ration",
    "write_path_subsumed",
    "command_contained",
    "check_containment",
]
