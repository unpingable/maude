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
general world-observation language and is not consumed as Nightshift
currentness.

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
