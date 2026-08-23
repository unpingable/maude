# Synthetic cache governed qualification result

Qualified locally on 2026-08-22. This receipt records a disposable product
experiment, not production deployment qualification.

## Exact artifact lifecycle

- The first editable document had digest
  `sha256:d45e9248896310c882dac49fc5625c1f91b376295229812c5094850e11f4c451`.
- Its applicable check refused with one `plan.reference.unique` finding on
  `pn_continued`.
- Deterministic proposal
  `sha256:0a0922dca53b35cb73dff5c85a480a7a9489130ab40869fcb044be352cb5b92c`
  was scoped to that exact finding, node, field, and `update_node` operation.
  Explicit acceptance used the ordinary Plan Core CAS boundary.
- A separate human document edit produced the passing locked document:
  revision
  `sha256:933ef415b59cd2080a19a016f77845cbf15ae2c40e10720c829906ae403a4d93`,
  digest
  `sha256:1238a9ea461709d9755bc05a91db797bb02e1b521eed059ca0081248ecad5261`.
- Lock receipt:
  `sha256:5faf1d180e39e4c002dd3228e4105e2257266db338227288957ccc9a3b8f888a`.

The exact local-Compose compiler produced two intentional handoffs from those
same locked bytes. Qualification work was
`sha256:78614416d6d42f303d20f66b23493b7caa93c29d3925d87d87cea07b9dfe7dcd`;
teardown work was
`sha256:51d2bdc02144eb339442bed1fdf914f2237213ded1f6203bc8a10737482a7785`.
They have different explicit compiler inputs, compilation receipts, handoff
identities, proposals, occurrences, spends, and attempts. Identical artifact
bytes did not collapse intentional governed occurrences.

## Governed result

The clean run retained under `/tmp/ag-synthetic-cache-governed-v4` records:

- 2 authenticated Maude custody records;
- 2 exact Nightshift authoring-lineage records;
- 14 AG transitions;
- 2 one-use AG spends;
- 2 Docket attempts;
- 2 successful settlements;
- final program counter `SettledObservationRequired`.

Occurrence `00000000-0000-4000-8000-000000000000` qualified the platform.
The fresh authority-empty successor
`00000000-0000-4000-8000-000000000001` performed teardown under its own
proposal, standing, spend, issuance, custody, attempt, and settlement.

The qualification attempt observed exact MISS/MISS/HIT/HIT behavior across
cache A and cache B, origin counts 1 and 2 without increments on hits, four
requests served through cache B while cache A was stopped, both cache
identities after restoration, and zero host port bindings. A separate
post-teardown Docker project-label inventory observed zero containers and zero
networks.

## Failed cuts retained as evidence

The route to the clean run was not silently retried:

- a malformed precompiled mode wrapper refused before runtime effects;
- reuse of one execution-standing fact for teardown refused before a second
  dispatch;
- a later attempt against a retained workspace could not establish whether
  new mechanics occurred and became `ReconciliationRequired`; it did not
  repeat effects during reconciliation.

The indeterminate store and retained workspace were preserved separately for
inspection. The clean v4 run used fresh exact state rather than classifying
the unknown attempt by assertion.

## Cross-probe and drift

Owner read commands produced 15 content-bound
`maude.plan-node-governed-binding/v1` records. Each relates an exact stable
PlanNode to the applicable compilation, authoring lineage, AG coordinates,
work, and Docket result. No prose, filename, timestamp, or list position is a
join key.

After governance, an ordinary successor working revision was created:

- current revision
  `sha256:921acc03df236bb45fce24ea9b02dc7f93e03b5a82e354a8d9c5098b37b793ce`;
- current digest
  `sha256:f88abe6dc10ecb38d28b3e489b15271b49fdd8d06d19dcde852b2d7fad1901c6`.

Check, lock, compilation, handoff, and governed lineage remain pinned to the
locked digest. `/phosphor/design` displays the mismatch and does not rebind
runtime history.

## Nonclaims

The run used the existing test NQ admission port and integration standing
issuer. It does not qualify production principals, physical power loss, live
backup/restore, Docker host compromise, or the equivalence between the local
synthetic service and an external production workload. The executor evidence
remains a Docket result rather than currentness. A follow-on bounded adapter
now produces the workflow-specific `maude.local-compose-world-observation/v1`,
authenticates it to Nightshift, and persists it in a custody projection
separate from canonical observation cycles. This is deliberately not a
general world-observation language. A later Nightshift-owned composition may
use the custodied bytes as evidence, but only under an independent deployment
profile and ordinary consequence-time currentness evaluation.

## Follow-on observation-custody qualification

The retained executor records were subsequently passed through the closed
local-Compose observation adapter and authenticated into the same Nightshift
store. The exact candidates are:

- qualify observation
  `sha256:881c68eea6a9bce86cf9d4f022099f4e1a3c4bba5e2e645c621046c350ad081b`,
  custody
  `sha256:9740f6775e0b6e922d80de211485ee3e66d49ed59adf9c7e4f26afa478f4d92f`;
- teardown observation
  `sha256:ff01f8c2de40993be822adc273a8a3c3a4ef856c8e7723300d26fbfbc864d1e2`,
  custody
  `sha256:accf1275ac04b4d1dfd55eb3db40acac913d1270727a1289939c060724eb3fa9`.

The qualify candidate cross-probes four evidence claims to `pn_health`,
`pn_cache_behavior`, `pn_continued`, and `pn_restore`. The retained teardown
record predates the executor's direct network-inventory field, so its candidate
claims only the exact recorded zero-container fact at `pn_teardown`; the
separate qualification evidence still records the zero-network check. A future
execution under the hardened adapter will bind both fields.

Two imports left the canonical cycle count and cycle snapshots unchanged.
Exact resend after process restart returned the first custody receipt and
receipt time. Read-side age projection distinguished fresh, stale, and
not-yet-observed evidence without adding a `currentness` field or creating an
observation cycle.

## Epistemic feedback qualification

The uninterrupted follow-on run retained under
`/tmp/ag-synthetic-cache-feedback-v4` starts from the v9 exact Plan Core corpus
and closes the application-evidence feedback circuit:

```text
governed qualification O0
  -> Docket settlement
  -> exact local-Compose application observation
  -> authenticated Nightshift custody
  -> deployment-profile composition
  -> canonical Nightshift observation/currentness
  -> authority-empty successor O1
  -> separate AG standing/spend/dispatch
  -> governed teardown settlement
```

The source application observation is
`sha256:e92e58ea15ab27ecdf47a62f328bb0824a5bbff21356500da11739a947fdff55`.
Nightshift composed it as
`sha256:e50474f7e6498302490af8a72b809a87339475a75fb017b27540ad88253ef315`
into canonical observation
`sha256:c436fd58f3d7635ab1168ef2f245460b10727f568d1b87afa99f2959e9c9c9db`.
The deployment-owned 120-second profile produced the exclusive horizon
`1787437226280`; the ordinary observation resolver reported the object
`current` before that horizon and `stale` at the horizon without changing its
historical basis.

The exact application claims cross-probe through compilation output identities
to:

- `pn_health`: front door reachable;
- `pn_cache_behavior`: MISS then HIT;
- `pn_continued`: service survived the bounded cache-A stop;
- `pn_restore`: both cache identities were observed after restoration.

Thus the changed-world failure/restoration experiment is part of the exact
observation acquisition, not an inferred post-hoc label. Docket settlement
alone still cannot establish any of these claims.

The first recovery cut retained a successful qualification result after
observation packaging rejected a noncanonical timestamp. Recovery observed
that exact Docket result and never redispatched it. A first Nightshift
composition then closed without AG work because the diagnostic recurrence
basis was inadequate. A later diagnostic slot recomposed the same historical
source for the same O1 target after correcting that independent basis. The
source acquisition time and currentness horizon did not refresh. A conflicting
target remains forbidden. This pins the distinction between reusable evidence
for one exact question and one-use governed authority.

The final v4 replay contains 14 AG transitions, two one-use spends, two Docket
attempts, two settlements, two authenticated authoring-custody records, and no
remaining project containers or networks. Diagnostic recurrence slots and AG
governed occurrence identities remain separate identities; neither is inferred
from the other.

## Post-settlement acquisition orchestration

The fresh ledger/store run retained under `/tmp/ag-acquisition-qualified-v3`
used the single `orchestrate-post-settlement` process against the exact Docket
qualification settlement. It recorded one exact trigger and request, invoked
only `maude.local-compose-observation-adapter` version 1, persisted the exact
handoff before custody, and received Nightshift custody. Repeating the complete
one-shot command left exactly five events and the original
`observed_at_unix_ms = 1787437106280`; it neither reran the adapter nor refreshed
the evidence.

An earlier v2 cut demonstrated Nightshift custody becoming durable before the
orchestrator could parse/finalize its response. Exact rerun converged on the
same custody record and then appended the missing local terminal receipt. The
local-Compose adapter's two-invocation recovery budget, SQLite invocation
claim, concurrent exact-custody convergence, source substitution, and
recomputed-digest hostile cases are covered by focused tests.

The strong v1 profile still cannot lawfully re-observe after staleness: one
required claim is the effectful cache-stop/restoration experiment. Repeating
that action outside governed work would bypass AG, while replaying its old
evidence would create a false refresh. It still refuses. A separate closed
passive profile now refreshes only what can be learned without another fault
test. No recurring scheduler or monitoring abstraction was introduced.

## Historical qualification plus passive re-observation

The 2026-08-22 full run retained under
`/tmp/ag-synthetic-cache-passive-v5` exercised the decision-relative split
with the real Docker world and the ordinary governed successor:

```text
effectful governed qualification Q1
  -> passive first observation S1
  -> exact exclusive stale boundary
  -> passive re-observation S2
  -> Nightshift v4 composition of unchanged Q1 + fresh S2
  -> ordinary authority-empty governed O1
  -> governed teardown
```

The historical qualification source is
`sha256:110d803bbbffcba309ae005da58d9db2294ba560ecbd09ece2ffe14d9dd7d4e5`.
Its content-derived qualification relation is
`sha256:b853e90d0a815ac78971907ab7e0c5d14f445ba903f87417d5e8e04ef784bbb7`
and retains acquisition time `1787450840063`.

The first passive acquisition used reason `reobserve_for_successor` and
produced observation
`sha256:99e55adce30f4270eb8918cb4c603ee84d1f538cdcedbbb12f23d722daff2a43`
at `1787450843101`. Nightshift's exact stale basis
`sha256:0748e545669e2a16dc26d36696448e00d5071ea81ae8694ff58ede2c92eab84b`
evaluated it stale at the exclusive horizon `1787450848101`.

The orchestrated `reobserve_after_stale` acquisition then produced distinct
observation
`sha256:e707caa039b845c6e69073c89bc542c4702591c27834c83d08a0ee3ef3363c26`
at `1787450848525`. It contains only the closed passive claims for
`pn_health`, `pn_cache_a`, `pn_cache_b`, and `pn_cache_behavior`; it contains
no failure-survival or restoration claim. The passive adapter performed only
fixed Compose inspection and fixed HTTP GETs from the already-running front
container. It never stopped, started, restored, or repaired a service.

Nightshift composed Q1 and S2 as
`sha256:e09233fe9833a07dd78ce4e2710003a5eddc5f79ce185946946b2964ab8b5314`
with passive exclusive horizon `1787450853525`. O1 then received ordinary
fresh standing, a distinct one-use spend, Docket attempt, and settlement.
Final replay records 14 AG transitions, two spends, two attempts, and two
settlements. Teardown left no Compose containers or network.

Hostile fixtures additionally establish that a changed
PlanDocument/compilation cannot inherit Q1, a passive observation cannot
repair that absence, failed passive acquisition fabricates no evidence or
remediation, and exact transport replay retains the original passive
observation time.

## C1 to C2 requalification result

The clean 2026-08-23 lifecycle is retained at
`/tmp/ag-synthetic-cache-requalification-v6`; its deterministic Plan Core and
compiler corpus is `/tmp/ag-synthetic-cache-requalification-plan-v3`.

The V1 workflow has an explicit atomicity boundary: its authorized
qualification action both applies the operational artifact and performs the
bounded fault qualification for that exact artifact. It has no deploy-only
action and no separately governed state in which C2 is an active passive
observation target while C2 lacks applicable qualification. This is a
negative-reachability result, not an assertion that deploy-before-qualify is
wrong. A future deploy-only, canary, or staging contract would need explicit
authority, rollback, custody, restart, concurrency, and qualification rules.

C2 was created by 16 ordinary typed Plan Core operations. The first updates
the semantic workspace, declared write scope, and acceptance criteria; the
remaining 15 update each surviving node's structured-work write path. All
PlanNode IDs and presentation order remain stable. C2 check receipt
`sha256:1fbef89a2b9a25b2b17329d86d97bf26aba514224abb6c6afa44d1ca880dfc00`
passes and lock
`sha256:4f764a94f27c50a023c6bd2b02e87c9dbd316a9081dbd1d14cfee72776806bc4`
binds exact C2 bytes.

The C1 and C2 PlanDocument digests are, respectively,
`sha256:1238a9ea461709d9755bc05a91db797bb02e1b521eed059ca0081248ecad5261`
and
`sha256:c7baabf37ce84cfefbd1a34f3ab410ae9f2fbb3911fa0f6f50e860d342fa647c`.
C2 qualification compilation
`sha256:42786faf82ad65d8610262b73540c362acd0ca1f1ff003ef4cf2d57f213e3e99`
produces exact work
`sha256:325c4755fffb077218e42d86fb51fb8f7aa6d9f4a49781bddeb0ed1f53266b47`.

Nightshift refused Q1 for C2 by exact target PlanDocument mismatch before a
C2 occurrence or spend. The explicit C2 qualification then traversed ordinary
Maude custody, Nightshift proposal construction, AG standing/admissibility,
fresh one-use authorization, Docket custody/execution, settlement, and
post-settlement evidence acquisition. It produced Q2 observation
`sha256:4bf5454f225ff6fb59862c85df5ea148597f2d5c4e40c2633e2f1ad36f2f1c8a`.

Passive S3
`sha256:913f6896b5249c0c3cc1dfd85da0b6bcabfc3627b1176490adf594453867d468`
contains only the closed read-only claims and was acquired after Q2. Combining
S3 with Q1 is a model-level substitution witness: it still refused for the
same exact C1/C2 mismatch, but it does not claim that pre-Q2 C2 was deployed as
a passive target. Combining Q2 with S3 produced composition
`sha256:89cb17e3be108ec3411e849fedcb2fb3c23dba7b1d4534e2bc7f16b7b0dbaa28`
and opened ordinary C2 routine-continuation/teardown work under a fourth fresh
spend. Final replay records 28 transitions, four spends, four attempts, and
four settlements. Exact Docker label inventory was empty for both projects.

The run encountered and preserved two ordinary fail-closed cuts while being
qualified: one reused Nightshift recurrence slot, and one prior designated
Snap workspace. Neither was reclassified as success. The final harness now
selects the next unoccupied canonical slot far enough past its exact due time
for retained evidence to remain in-budget. Historical workspaces were moved to
explicit evidence names rather than overwritten.

Q1 and Q2 are append-only evidence of particular governed qualification
occurrences concerning exact artifacts. They are not mutable
`qualified(artifact)` attributes. Stable PlanNode continuity across C1 and C2
does not carry either qualification across the artifact boundary.
