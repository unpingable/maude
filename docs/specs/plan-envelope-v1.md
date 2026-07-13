# Plan envelope v1 — first-class `execution_request` (S6)

> v1 is the **authoring surface**. It is a delta over `plan-envelope-v0.md`:
> every field there still applies EXCEPT the request surface. This spec defines
> only what S6 changed. The adjudication + migration ruling lives in the AG
> campaign note `agent_gov/docs/campaigns/nightshift-functional-mvp/
> design-s6-execution-request-schema.md`.

## Why

In v0 the execution request was *inferred*: write scope from the top-level
`scope_allowlist`, and shell commands pulled out of the referenced RationCard
digest at projection time. Neither named itself "the request", and the commands
never appeared in the plan the operator approved. v1 makes the request
**first-class and legible in the plan bytes** — because approval attaches to
plan bytes, not to a reconstruction.

## `plan_version` is the schema discriminator

| value | behavior |
|-------|----------|
| `1` | v1 path. `execution_request:` block is the request; top-level `scope_allowlist` **forbidden**. |
| `0` | retired. Decodes via the v0 path **iff** the plan's `plan_ref` is in the frozen allowlist; otherwise refuses. New v0 authorship is impossible. |
| missing | **refuses** — there is no "unversioned means legacy" default. |
| other | **refuses** (unknown version). |

All refusals use the existing `invalid_plan_envelope` class with a
discriminating detail token (`plan_version_missing` / `_unknown` / `_retired` /
`legacy_field_under_v1`). No new refusal vocabulary.

### Frozen v0 allowlist (the microscopic aperture)

`FROZEN_V0_PLAN_REFS` is a closed, explicit set of pre-v1 `plan_ref`s the retired
decoder still recognizes. Its sole member is the committed NS-1 candidate
specimen. Growth is by explicit operator act only — never by an unversioned
fallback. Registered + adjudicated in the AG S6 design note.

## The `execution_request:` block (v1)

```yaml
plan_version: 1
# … all v0 common fields (goal, workspace, submitter_kind, plan_origin,
#   provenance, harness, steps, acceptance_criteria, stop_conditions) …
execution_request:            # required IFF a governance block is present
  write_paths:                # [glob] — the write scope (replaces scope_allowlist)
    - "crates/nightshiftd/src/**"
    - "crates/nightshiftd/tests/**"
  commands:                   # [structured] — never shell strings
    - {program: cargo, argv_prefix: [test]}
    - {program: cargo, argv_prefix: [build]}
  network: denied             # denied (default) | requested — requested never grants
  git: denied                 # denied (default) | requested
  horizon: run                # run (default) | session — request; capped at mint
```

### Field rules

| field | req | type | rule |
|-------|-----|------|------|
| `write_paths` | – | [glob] | the write scope. At least one of `write_paths`/`commands` must be non-empty. |
| `commands` | – | [{program, argv_prefix}] | structured tokens only; a bare shell string refuses. `argv_prefix` defaults to `[]`. |
| `network` | – | enum | `denied`\|`requested`. `requested` is a legible ask, never a grant — activation locks the axis and records it in `unmet_axes`. |
| `git` | – | enum | as `network`. |
| `horizon` | – | enum | `run`\|`session`. A request; validated/capped at mint. |

- **Presence rule.** `execution_request` is **required when a `governance` block
  is present** (a governed plan's request must be legible in what the operator
  approves) and **optional otherwise** (an ungoverned plan mints no grant; an
  absent block means an uncompressed run, exactly as an absent v0
  `scope_allowlist` did).
- **No two sources.** A `plan_version: 1` plan carrying top-level
  `scope_allowlist` refuses (`legacy_field_under_v1`). There is exactly one
  request surface; no precedence rules.
- **An empty block refuses.** `execution_request` with neither `write_paths` nor
  `commands` grants nothing — omit the block (or the governance) instead.

## §7 governance binding — unchanged discipline, new citable fields

The copy-with-citation rule (`plan-envelope-v0.md` §7) is preserved verbatim. An
`execution_request` value that originates in an AG object is still recorded in
`governance.projected` and verified three-valued. The citable projection targets
gain the v1 fields:

- `execution_request.write_paths`
- `execution_request.commands`

`scope_allowlist` remains projectable for the frozen v0 path only. Everything
else in §7 (three-valued verification, strict bar for governed execution, two
receipt surfaces, `review_packet_ref` back-fill) is identical.

## Projection (S4a → S6)

`project_execution_request` reads the block directly for v1
(`execution_request.write_paths → write_paths`, `commands → commands`,
`network/git → network_requested/git_requested`, `horizon → horizon`). The v0
inference (`scope_allowlist` + ration commands) survives only as the frozen
decoder. The daemon `runtime.grant.activate` wire request is **unchanged** — S6
changes how the request becomes explicit, not what the daemon receives.

## Out of scope for v1

Arming substrate effects (`enforcement: declared-effects-only` stays), multi-actor
attribution, blanket v0→v1 corpus migration.
