# Repositioning — Maude as plan-only executor

**Status:** Operator-ruled 2026-07-03. Composes with the RATIFIED boundary in
`agent_gov/docs/design/governed-shell/maude-boundary.md` (2026-07-02) and the
governed-shell campaign (`agent_gov/docs/campaigns/governed-shell/`). This
document records the ruling, the boundary, and the do-not-build list; the
build sequence lives in [ROADMAP.md](../ROADMAP.md).

## The ruling

Maude is no longer framed as "the Governor TUI" or a chat client. Maude is
the **Codex-shaped executor for OpenClaw/Hermes-style harnesses**:

- Planning happens **outside** Maude — ChatGPT, Fable, Codex,
  operator-written plans.
- Maude **consumes bounded plans**, selects the appropriate harness, invokes
  it as a supervised session, supervises execution, captures
  transcripts/artifacts/receipts, enforces stop conditions, emits
  obstruction notes, and returns a reviewable result.
- **AG is one authority substrate Maude may call** — not Maude's product
  boundary. Maude mints no authority and refuses nothing on its own behalf
  (plan-format validation excepted).

> Maude runs the room. AG decides what the room is allowed to claim.
> (maude-boundary.md, RATIFIED 2026-07-02)

Chat and the PLAN/BUILD spec-lock paradigm are cut (ratified D-GS-2): "lock
understanding before acting" relocates to AG's admissibility moment; "plan
first" becomes an autopilot-profile property. The chat code is quarantined
legacy until its removal slice (GS-15); do not build on it.

## Two ingress workflows, one core (operator ruling, 2026-07-03)

Claude (and other agents) driving Maude is not dev scaffolding — it is a
preview of a real consumer class. The execution core does **not** split; the
**ingress contract** does:

```
same Maude core
same plan admission
same execution supervision
same transcript/artifact/receipt capture
same obstruction handling

different submitter contracts:
  human operator
  synthetic agent
```

- **Human operator workflow:** human intent → bounded plan → Maude
  executes/supervises → human reviews result.
- **Synthetic submitter workflow:** agent-generated plan → Maude
  admits/refuses by contract → Maude executes/supervises → receipts returned
  to the reviewer/orchestrator.

The risk shapes differ, so the contracts differ:

| axis | human path | synthetic path |
|---|---|---|
| submitter_kind | `human` | `synthetic_agent` |
| plan_origin | `human_written` (also `imported_from_review`) | `agent_generated`, `agent_revised` |
| admission posture | may allow interactive clarification | **fail closed on ambiguity** |
| authority | may approve or revise | may **propose only** — never self-authorize unless separately granted |
| interaction | conversational / preflight allowed | batch / plan-only / non-interactive by default |
| review | result returns to operator | receipts return to orchestrator/reviewer |
| limits | workspace defaults | tighter budgets, command allowlists, timeouts, write scope, transcript custody |

**The product law:**

> **Synthetic agent-led Maude is a first-class submitter path, not a
> separate authority path.**

It gets its own workflow because its failure modes are different. It does
not get standing because it is fluent. No "Claude mode" (`--claude` is the
anti-pattern); Claude, Codex, AG, nightshift are all particular submitters
under the one synthetic contract (`submit --submitter synthetic_agent`).
The vocabulary is minted once, at the plan-envelope spec (M-1); the
synthetic ingress ships as M-7 on the shared non-interactive machinery
(M-6).

## What Maude owns vs what AG owns

Settled by the ratified boundary doc (see it for the full table):

- **Maude owns:** operator interaction; decision-queue rendering + triage;
  session lifecycle *driving* over RPC; transcript/event *rendering*;
  branch/fork/promotion UX; steering UI; envelope display; refusal→route
  proposals; plan ingestion and format validation; run-report composition.
- **AG owns:** refusal semantics; the decision sources and the one mutation
  door; the supervisor FSM and tool interception; receipts and the event
  ledger (sole writer); promotion custody; **the harness/provider adapters**
  (below the authority gate — Maude gets `runtime.adapters.list`
  introspection and honest capability degradation, nothing more);
  scope.escalate, scars, budgets, timeouts.

Harness **selection** is Maude's (a `backend_kind` chosen at session
create, informed by adapter introspection). Harness **invocation and
interception** are AG's.

## Do-not-build

1. **No authority in Maude, ever** — no minting, no local refusal of gated
   actions, no approval synthesis, auto-answer, or cross-kind approval
   batching.
2. **No adapters in Maude** — settled (D-GS-5); introspection + honest
   degradation only.
3. **No planning surface** — no plan authoring, editing, or chat
   resurrection (D-GS-2). If chat returns, it returns as its own recorded
   decision.
4. **No multi-substrate authority abstraction** — "AG is one substrate" is a
   boundary statement, not a license to build a pluggable
   authority-provider layer. Named here; not built.
5. **No transcript/ledger store in Maude** — AG's EventBus is the sole
   writer; Maude renders and exports derived views only.
6. **No unattended auto-approve** — non-interactive runs halt at the first
   blocking decision; richer unattended behavior is AG autopilot-profile
   territory (GS-7), never Maude client code.
7. **No Maude-side acceptance judgment** — the run report renders acceptance
   criteria as an unchecked checklist; the reviewer judges.
8. **No per-agent special-casing** — no "Claude mode"; every agent is a
   submitter under the one synthetic contract.
9. **No standing by fluency** — the synthetic path is a submitter contract,
   never an authority upgrade.
10. **No mid-session envelope mutation; no ttl-less or automatic widening.**
11. **No feature growth ahead of the GS-9 client resync** beyond the Phase 0
    doc slices.

## Contract-touch flags (ratification gates)

- **CT-1 (M-1):** any plan-envelope field needing daemon persistence or
  enforcement (candidate: `plan_ref` on `runtime.session.create` so receipts
  cite the plan) → shell-contract version bump + operator ratification.
  v0 maps every field to existing create params or keeps it client-side.
- **CT-2 (M-5):** obstruction notes in AG's ledger = new canonical EventKind
  → contract bump + AG-side sandwich slice. v0 is client-side only.
- **CT-3 (GS-15):** COMPAT repin from Governor major.minor to
  shell-contract-v0 as the primary pin.
- **GS-8b:** ag_shell_client needs a live-socket client class before GS-9
  can consume it — AG-side lib slice, filed against the GS campaign capsule.

## Known flags (AG-side, not performed here)

- `agent_gov/docs/roadmaps/tools/maude.md` §0 still says "Maude owns
  model/runtime adapters" — reversed by the later-ratified boundary doc.
  Needs a one-line strike in the AG repo.

## Archive

Chat-era documents are preserved under [archive/](archive/) with HISTORICAL
headers: the context-UX and relational-role-induction TODOs (assumed a
long-lived conversational surface) and the `ingest/` design transcripts
(origin of the retired chat framing). `TODO_SESSION_LINEAGE.md` stays live —
its typed-artifacts + promotion-receipts shape feeds the run-report work
(M-4).
