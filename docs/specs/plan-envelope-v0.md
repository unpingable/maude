# Plan envelope v0 + submitter contracts

**Status:** CANDIDATE — **operator-approved 2026-07-04** (slice M-1). This is
candidate *Maude-side* law, **not** daemon law: it is ratified as the contract
M-2..M-7 build against, but it is NOT promoted to stable daemon law. Budget,
scope, and acceptance are enforced **Maude-side (client / autopilot profile)**
for now — the client-side version must prove shape against the real desk before
the daemon absorbs any of it. **CT-1 stays named as future AG support, not
built:** `plan_ref`, per-session budget, per-session scope (see §2). Any need
for a new plan field returns HERE for a version bump; downstream slices never
improvise plan vocabulary.

**Boundary law.** Planning happens *outside* Maude. Maude neither authors nor
edits nor completes plan content; it validates a plan's *shape* and maps it to a
supervised run. Format validation is **not** authority: a well-formed plan for a
forbidden action passes validation and is refused by AG at the gate. See
[../REPOSITIONING.md](../REPOSITIONING.md).

---

## 1. What a bounded plan is

A plan is a UTF-8 Markdown document with a YAML front-matter block. The prose
body is advisory context for the harness; the front-matter is the machine
contract Maude reads.

```yaml
---
plan_version: 0                 # required; this contract version
goal: "Add retry backoff to the ingest client and cover it with tests"  # required
workspace: "/home/me/proj"      # required; the run's cwd
submitter_kind: human           # required; human | synthetic_agent
plan_origin: human_written      # required; see §3
provenance:                     # required; who/what produced this plan
  author: "operator"            # e.g. operator | chatgpt | fable | codex | nightshift
  ref: null                     # optional upstream id (thread, ticket, receipt)
harness: claude_code            # optional; backend_kind hint (§2)
autopilot_profile: null         # optional; workspace autopilot profile hint (§2)
scope_allowlist:                # optional; advisory globs the run should stay within
  - "src/ingest/**"
  - "tests/**"
steps:                          # optional; ORDERED, ADVISORY — not enforced
  - "Add exponential backoff to IngestClient.retry"
  - "Add a test that asserts 3 retries then raise"
acceptance_criteria:            # optional but recommended; checkable statements
  - "IngestClient retries 3× with backoff before raising"
  - "New test passes; existing suite stays green"
stop_conditions:                # optional; when the run must halt
  budget_tokens: 200000
  forbidden_paths: ["infra/**", ".github/**"]
  halt_if: "a migration or schema change is required"
---

Free prose here: background, links, anything the harness should read. Not parsed.
```

### Field reference

| field | req | type | meaning |
|---|---|---|---|
| `plan_version` | ✔ | int | contract version; `0` for this spec |
| `goal` | ✔ | str | one-sentence outcome |
| `workspace` | ✔ | path | the run's working directory |
| `submitter_kind` | ✔ | enum | `human` \| `synthetic_agent` (§3) |
| `plan_origin` | ✔ | enum | how the plan was produced (§3) |
| `provenance` | ✔ | map | `author` (str) + optional `ref` |
| `harness` | – | str | backend hint, validated against `runtime.adapters.list` (M-3) |
| `autopilot_profile` | – | str | workspace autopilot profile hint (§2) |
| `scope_allowlist` | – | [glob] | advisory; rendered + carried, not daemon-enforced in v0 |
| `steps` | – | [str] | ordered, **advisory** — Maude never reorders or invents |
| `acceptance_criteria` | – | [str] | checkable statements; rendered **unchecked** in the run report (M-4) |
| `stop_conditions` | – | map | `budget_tokens` (int), `forbidden_paths` ([glob]), `halt_if` (str) |

---

## 2. Field → `runtime.session.create` mapping

The daemon's create surface today accepts: `backend_kind`, `cwd`, `task`,
`operator_mode`, `allow_dirty`. The mapping is deliberately honest about what
maps, what rides the autopilot profile, and what is client-side only.

| plan field | maps to | notes |
|---|---|---|
| `goal` (+ `steps`, prose) | `task` | Maude composes the task text from goal + advisory steps verbatim; it does not synthesize new steps |
| `workspace` | `cwd` | — |
| `harness` | `backend_kind` | validated against `runtime.adapters.list` first (M-3); unknown/incapable → `adapter_unavailable` before create |
| interaction posture (from `submitter_kind`, §3) | `operator_mode` | human → interactive; synthetic → non-interactive (exact enum validated at M-2) |
| `autopilot_profile` | `runtime.autopilot.set` (workspace) | GS-7 sets the workspace-default profile; profile carries approval posture + budget/scope defaults. Applied before launch, **not** a per-session create param |
| `stop_conditions.budget_tokens` | autopilot profile | budgets are AG's (below the gate); a per-session budget override is **CT-1** (not in create today) |
| `stop_conditions.forbidden_paths`, `scope_allowlist` | — (client-side advisory in v0) | Maude renders them and can refuse to submit a plan that names a forbidden path in its own steps; daemon-enforced scope is the autopilot profile / a **CT-1** per-session override |
| `stop_conditions.halt_if` | — (client-side) | a natural-language halt cue surfaced to the operator/report; not machine-enforced in v0 |
| `acceptance_criteria` | — (client-side) | rendered **unchecked** in the run report (M-4); the reviewer judges — Maude never auto-checks |
| `provenance`, `plan_origin`, `submitter_kind` | — (client-side) | stamped into the run report; a daemon-side `plan_ref` so **receipts cite the plan** is **CT-1** |

**CT-1 (ratification gate).** Three plan capabilities want daemon support that
does not exist at create today: (a) `plan_ref`/provenance on the session record
so receipts cite the plan; (b) a per-session budget override; (c) per-session
scope enforcement. Each is a shell-contract addition → version bump + operator
ratification. v0 avoids them by mapping to `task`/`cwd`/`backend_kind` + the
workspace autopilot profile, and keeping acceptance/scope/halt client-side. The
moment a mapping fails, return here — do not stretch `session.create`.

---

## 3. Submitter contracts — one core, two ingresses

> **Synthetic agent-led Maude is a first-class submitter path, not a separate
> authority path.** (operator ruling 2026-07-03)

Same execution core, same admission, same supervision, same receipts. The
*ingress contract* differs because the risk shape differs. No per-agent modes:
Claude, Codex, AG, nightshift are all submitters under the one synthetic
contract.

`plan_origin` ∈ `human_written` · `agent_generated` · `agent_revised` ·
`imported_from_review`.

| axis | `human` | `synthetic_agent` |
|---|---|---|
| admission posture | may clarify interactively | **fail closed on ambiguity** — a missing required field or an unresolved `halt_if` refuses admission, no session created |
| required fields | the §1 required set | the §1 set **plus** explicit `stop_conditions` (at least `budget_tokens` and either `scope_allowlist` or `forbidden_paths`) — absent → `submitter_limits_missing` |
| authority | may approve or revise inline | **propose only** — never self-authorizes a tool call or promotion; approvals require a human keystroke or a daemon-side autopilot verdict (the zero-resolve invariant, M-6/M-7) |
| interaction | conversational / preflight allowed | batch / plan-only / non-interactive by default |
| review | result returns to the operator | receipts + report return to the orchestrator via `--out` (never assumed reviewed) |

The synthetic path gets its own workflow because its failure modes differ. It
does **not** get standing because it is fluent.

---

## 4. Refusals this contract defines

Both are **format/admission** checks, client-side, explicitly NOT authority —
authority refusals stay AG's and pass through verbatim.

- `invalid_plan_envelope` — missing/unparseable required field, unknown
  `plan_version`, or a malformed value. No session created.
- `submitter_limits_missing` — a `synthetic_agent` plan without the required
  explicit limits (§3). No session created.

Forward-compat: unknown front-matter keys are ignored with a warning (a newer
plan author may add fields); unknown *enum values* for `submitter_kind` /
`plan_origin` refuse (an unrecognized submitter class is not guessed).

---

## 5. Out of scope for M-1

- The plan *runner* (parse → validate → create → launch) is **M-2**.
- Harness selection against `runtime.adapters.list` is **M-3**.
- The run-report format (acceptance checklist rendering) is **M-4**.
- The **obstruction-note** format is an **M-5** addendum to this spec (a run
  that can't proceed: plan ref, blocked step, refusal verbatim, route, what
  upstream must change). Reserved here; not defined yet.
- Headless (`--headless`, M-6) and synthetic ingress (`submit`, M-7) consume
  this contract; their exit-code vocabulary lives with those slices.

---

## 6. Examples

**Human plan** (`plan_origin: human_written`): the §1 example above.

**Synthetic plan** (note the mandatory explicit limits):

```yaml
---
plan_version: 0
goal: "Regenerate the OpenAPI client from the updated spec"
workspace: "/home/me/proj"
submitter_kind: synthetic_agent
plan_origin: agent_generated
provenance: { author: "codex", ref: "run_8f21" }
harness: codex
autopilot_profile: production
scope_allowlist: ["clients/openapi/**"]
stop_conditions:
  budget_tokens: 120000
  forbidden_paths: ["**/secrets/**", "infra/**"]
  halt_if: "the spec diff implies a breaking API change"
acceptance_criteria:
  - "Generated client compiles"
  - "No edits outside clients/openapi/**"
---
```
