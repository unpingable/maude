# Maude and Phosphor-ng

Status: operator-surface boundary. This document changes no authority or
runtime contract.

Maude and the governed runtime are related desks, not interchangeable
authorities. Phosphor-ng is the product family that presents those desks:

- **Maude `/design`** owns mutable pre-governed `PlanDocument` artifacts,
  checks, diffs, locks, and ordinary human/agent edit proposals. It also drives
  supervised sessions over the Governor RPC boundary and composes run
  testimony for review. It does not mint authority or compute AG-NG runtime
  status.
- **AG `/inspect`** is implemented by `ag_ng/crates/ag-operator-ui`. It reads
  canonical Nightshift, AG-NG, and Docket projections to inspect durable
  campaigns and occurrences. It remains mechanically GET/HEAD-only and has no
  Plan Core dependency.

The two processes may share Phosphor-ng navigation and presentation discipline,
but not a trust domain. Editing a pre-governed PlanDocument is not a governed
runtime mutation. `/design` cannot hand off without an exact workflow compiler;
`/inspect` cannot edit anything.

The shared operator language preserves proposal versus authorization,
authorization pending versus consumed, Docket accepted versus settled,
unknown versus failed, unavailable versus refused, settlement versus fresh
continuation authority, and retry versus successor occurrence. Both surfaces
show exact identities and honest absence before explanatory language.

Maude presents exact artifacts; the canonical owners judge them; `/inspect`
traces the resulting facts and witnesses. The editor/review surface never owns
a judgment merely because it produced the artifact. Agent suggestions remain
immutable proposals containing the same typed Plan Core operations as human
edits and require deliberate ordinary revision acceptance.

## Governed-intervention namespace boundary

Maude's existing `runtime.intervention.*` RPC names are supervised tool-call
approval records owned by the local Governor runtime. They are not
`ag.governed-loop.intervention-request/v1`, do not target an AG campaign state
digest, and must not be promoted into AG-NG intervention records by name or UI
state alone.

The canonical AG-NG contract has several exact classes—reconcile an existing
attempt, request a bounded read-only probe, open an authority-empty successor,
or halt future continuation—plus the separate typed human-disposition schema.
There is deliberately no generic retry/approve/continue request. A future
Maude adapter may author one exact record and send it through AG's authenticated
record-driven ingress, but Maude must not decide applicability, standing, or
authorization. No such write surface is added here.

AG-NG's loading dock now exposes separate one-shot commands to prepare a typed
request, inspect its exact bytes, package those unchanged bytes for one pinned
runtime, submit the signed envelope, and inspect immutable receipts. A future
bounded Maude adapter may invoke those owner commands; Maude must not
reimplement their schema/digest/signature rules or select a class from runtime
state. The submission credential authenticates Maude's delivery service. It is
not the requester's governed mandate and never authorizes AG. No Maude browser
control is added by this contract.

The authenticated requesting principal says who asked. It is not AG standing.
The resulting request says what was requested. It is not an AG authorization.
Authoring-context custody and lineage remain separate from both.

## Navigation contract

Phosphor-ng accepts versioned, read-only semantic paths:

```text
phosphor-ng.deep-link/v1

/phosphor-ng/campaigns/{campaign-id}/occurrences/{occurrence-id}
/phosphor-ng/campaigns/{campaign-id}/occurrences/{occurrence-id}/proposals/{proposal-id}
```

Campaign/proposal values are canonical `sha256:<64-lower-hex>` identities;
occurrence is a canonical lowercase hyphenated UUID. The URL is a human
locator. It contains no approval token, standing, spend, issuance, signature,
or secret, and possession grants nothing.

Nightshift now owns `nightshift.authoring_context_provenance.v1` at the exact
proposal-preparation boundary. It binds Maude `plan_ref` and session identity
to the final Nightshift intent and AG campaign, occurrence, proposal, and work.
The record is immutable lineage and is not passed to AG authorization logic.
For new handoffs, Nightshift also owns a separate authenticated custody record.
A Maude session issuer binds the exact supervised session to exact plan bytes;
a distinct handoff producer binds that receipt to one exact Nightshift request
and deployment identity. Phosphor-ng may display both identities, but custody
still supplies no governed authority. See
[`AUTHORING-CUSTODY.md`](AUTHORING-CUSTODY.md).

Maude's `report <session> <plan>` may query Nightshift by the exact plan/session
pair when `NIGHTSHIFT_READ_PROGRAM` and `NIGHTSHIFT_STORE` are configured. A
nonempty owner result can produce the proposal-bearing Phosphor-ng link when a
credential-free loopback `PHOSPHOR_NG_BASE_URL` is also configured. Empty means
`not recorded`; command/schema failure remains `unavailable`. Maude never
infers a link from workspace, goal, timestamps, prose, or digest similarity.
The report decodes the file's bytes without text-mode newline normalization, so
its `plan_ref` remains identical to the supervised execution path.

Phosphor-ng queries the same owner by exact campaign/occurrence and checks the
returned proposal/work against the selected AG snapshot. Maude has no stable
browser-addressed session page today, so Phosphor-ng shows exact plan/session
identities without fabricating a reverse URL. Historical rows are not
backfilled, and successors do not inherit predecessor context.

Authoring-context provenance establishes lineage, not permission. URL
possession grants nothing.

The complete shared vocabulary, historical-occurrence behavior, legacy
Phosphor disposition, and intervention seam are recorded in
`ag_ng/docs/operator-surface-convergence.md`.
