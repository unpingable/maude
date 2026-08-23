# Post-settlement observation acquisition orchestration

Status: qualified for the closed local-Compose `qualify` workflow. This is an
observation-mechanics contract, not a monitoring or currentness service.

> Acquisition orchestration may cause the world to be observed. It does not
> decide what the observation means.

> Retrying delivery of old evidence does not make the evidence new.

## Owner and boundary

The owner is the Maude workflow-mechanics one-shot command
`maude-observation-acquisition`. It sits between exact Docket settlement and
Nightshift's existing external-observation ingress:

```text
Docket settled owner projection
  -> exact Maude trigger/request ledger
  -> closed local-Compose observation adapter
  -> authenticated exact-byte handoff
  -> Nightshift custody/composition/currentness
```

The command does not import AG, Nightshift, or Docket implementation code. It
invokes only Docket's exact `governed-loop inspect` read command and
Nightshift's exact `external-observation import` custody command. It cannot
construct currentness, standing, spend, Docket work, or a successor.

## Exact records

`maude.external-evidence-acquisition-trigger/v1` is content-addressed and
binds the source campaign, occurrence, proposal, work, issuance, attempt,
settlement and settlement receipt; locked PlanDocument and compilation;
workflow/compiler/adapter/profile identities; subject, scope, and target
Nightshift runtime. A `post_settlement` trigger is derived only from Docket's
settled owner projection. A process exit, file marker, timestamp, or UI action
cannot substitute for that fact.

`maude.external-evidence-acquisition-request/v1` binds one deterministic
logical acquisition to that trigger. A post-settlement request derives its
exact `not_before` from settlement. A passive stale re-observation derives it
from the Nightshift owner's exact basis-evaluation time. Real ledger record
time is retained by the first immutable event rather than changing
deterministic request identity during concurrent trigger discovery.

`maude.external-evidence-acquisition-event/v1` records immutable mechanics:

- `trigger_recorded`;
- `acquisition_scheduled`;
- `adapter_invocation_started`;
- `adapter_returned_evidence` or `adapter_failed`;
- `custody_accepted`, `custody_refused`, or `custody_outcome_unknown`;
- `reobservation_refused` when the workflow has no lawful acquisition
  contract.

The SQLite ledger is append-only at the API boundary and also retains the
exact Docket response and exact workflow artifacts. Reopening validates their
closed schemas and relationships before the adapter may use them.
The ledger and durable handoff staging file are service-owned, non-symlink
regular files with mode `0600`; unsafe reopen refuses.

These events deliberately do not collapse into `success`. Adapter return,
authenticated Nightshift custody, canonical observation composition,
currentness, adequacy, and governed continuation are different facts owned by
different contracts.

## Closed adapter selection

The v1 registry contains exactly two entries:

```text
maude.local-compose-workflow/v1
+ post_settlement
-> maude.local-compose-observation-adapter / version 1
-> exact nightshift.external_evidence_profile.v1

maude.local-compose-workflow/v1
+ reobserve_after_stale
-> maude.local-compose-steady-state-observation-adapter / version 1
-> exact nightshift.steady_state_evidence_profile.v1
```

The compiler identity is pinned to `maude.local-compose-workflow` version 1.
The profile pins expected adapter, producer, key, and runtime identities. No
PlanDocument field selects an executable. There is no shell adapter, command
string, cron expression, periodic reason, monitor registry, or fallback based
on prose or filenames.

The adapter packages already-acquired immutable executor evidence. Its
`observed_at_unix_ms` is the executor's actual world-acquisition time. Handoff
packaging uses the later settlement time only as transport creation evidence.
It never rewrites observation time.

The second adapter is a separate read-only implementation. It performs only
fixed HTTP GETs and one fixed `docker compose ps` query. It has no lifecycle
verb and can emit only front-door, cache-A, cache-B, and ordinary-cache-
behavior claims. It cannot emit `single_cache_failure_survived` or restoration
qualification. Its exact Nightshift-produced stale basis binds the historical
qualification, prior passive observation, profile, artifact, work, subject,
scope, horizon, and evaluation time.

## Retry, timeout, restart, and concurrency

Transport/custody recovery resends the same stored handoff bytes under the
same request identity. It cannot call the adapter again once those bytes are
durable. Therefore a timeout after evidence production or Nightshift durable
custody does not create another logical observation. Nightshift's exact
idempotent custody slot converges, and the Maude ledger records one terminal
custody receipt.

An adapter invocation that ended without a durable artifact is outcome
unknown. Recovery requires the explicit `--recover-incomplete` flag. This is
safe for the post-settlement adapter because it reconstructs a handoff from
immutable Docket evidence; it does not reacquire the world. The passive
adapter refuses incomplete invocation recovery under the same identity,
because another call would be a genuinely new observation with a new
`observed_at`. Its operator must first reconcile the exact process/custody
outcome, then obtain a new owner basis and logical acquisition when lawful.
Adapter process attempts are bounded. Exhaustion fails closed.

SQLite `BEGIN IMMEDIATE`, unique trigger/request/artifact relationships, and
one invocation claim ensure that simultaneous settlement discovery converges
and at most one worker packages evidence. Exact source or trigger substitution
refuses even when an outer digest is recomputed.

After restart, the ledger distinguishes trigger recorded, invocation started,
evidence durable, custody outcome unknown, and custody terminal. It never
reconstructs a Nightshift observation or currentness result from mechanics.

## Acquisition reasons and re-observation boundary

The closed taxonomy is:

- `post_settlement`;
- `reobserve_for_successor`;
- `reobserve_after_stale`.

All three names remain distinct. `post_settlement` uses the strong historical
packager. `reobserve_for_successor` accepts only Nightshift's owner-produced
`absent` passive basis for the first S acquisition. `reobserve_after_stale`
accepts only the exact `stale` basis naming the prior S and its exclusive
horizon. The latter two share the same closed read-only adapter but never the
same trigger/request identity.

The existing cache profile requires the claim
`single_cache_failure_survived`. Acquiring that claim genuinely requires
stopping and restoring a cache. Repeating it outside AG would be an effectful
authority bypass. Packaging the old result would falsely refresh history.
Consequently the strong local-Compose adapter still refuses stale
re-observation.

Nightshift now owns a narrow decision-relative contract that combines the
unchanged historical strong qualification with fresh passive evidence for the
exact same artifact. `reobserve_after_stale` accepts only Nightshift's
content-bound `stale` basis for that profile. It creates a new acquisition,
evidence time, custody, and observation identity; it does not renew the old
qualification or claim that another fault test occurred.

A decision that requires a newly asserted failure-survival claim still needs
new governed exact work. Missing or inapplicable qualification is never an
observation retry. There remains no recurring timer, profile-driven loop, or
continuous monitor.

## One-shot operation

`orchestrate-post-settlement` performs exact discovery, durable recording,
adapter invocation, and Nightshift custody in one ordinary process. Re-running
the same command is exact transport recovery, not a new observation:

```sh
maude-observation-acquisition orchestrate-post-settlement \
  --ledger /var/lib/maude/observation-acquisition.sqlite \
  --docket-program /usr/libexec/docket \
  --docket-state /var/lib/docket/governed-loop \
  --issuance sha256:EXACT_ISSUANCE \
  --executor-evidence /var/lib/docket/evidence/EXACT_ATTEMPT.json \
  --executor-plan /var/lib/maude/compiled/EXACT_PLAN.json \
  --compilation-receipt /var/lib/maude/compiled/EXACT_RECEIPT.json \
  --governed-bindings /var/lib/maude/lineage/EXACT_BINDINGS.json \
  --external-profile /etc/nightshift/external-evidence-profile.json \
  --target-runtime-id nightshift:designated \
  --producer-key /run/credentials/maude-observer.key \
  --producer-principal-id maude-observer:designated \
  --producer-key-id maude-observer-key:primary \
  --nightshift-program /usr/libexec/nightshift \
  --nightshift-store /var/lib/nightshift/canonical.sqlite \
  --nightshift-credential /run/credentials/maude-observer.key \
  --nightshift-runtime-id nightshift:designated
```

`record-post-settlement`, `run`, `show`, and the read-only
`export-occurrence` remain available for explicit cut/recovery qualification.

Demand-driven passive re-observation uses a Nightshift owner-produced stale
basis. The exact command remains one-shot:

```sh
maude-observation-acquisition orchestrate-reobserve-after-stale \
  --ledger /var/lib/maude/observation-acquisition.sqlite \
  --reobservation-basis /bounded/nightshift-stale-basis.jcs.json \
  --external-profile /etc/nightshift/steady-state-evidence-profile.jcs.json \
  ...the same exact Docket settlement, compilation, bindings, adapter key, \
  and Nightshift receiver coordinates...
```

The trigger's `basis_evaluated_at_unix_ms` becomes the deterministic request
`not_before`. A new basis produces a new logical acquisition. Resending an
already durable passive handoff is transport recovery and retains its original
observation time.

> Re-observation may refresh what can be learned by looking. It may not
> refresh what can only be learned by intervening.

> A qualification remains evidence of the test that occurred. It does not
> become a fresh observation merely because the deployed system has not
> changed.

## Credential and deployment custody

The producer credential reuses the qualified 32-byte protected-key pattern.
It must be a regular non-symlink file owned by the service user and inaccessible
to group or others. The orchestration service needs read access to exact
compiler/binding/evidence artifacts, execute access to the two pinned owner
CLIs, write access to only its ledger/staging directory, and the configured
Nightshift receiver key. It does not need AG issuer keys, spend material,
Docket executor capabilities, or Plan Core write access.

Recommended startup ordering is Docket store available, Nightshift store and
receiver configured, then an issuance-specific one-shot acquisition. Back up
the acquisition SQLite database together with its WAL/SHM files or from a
coherent SQLite snapshot. Key rotation requires Nightshift receiver overlap
for the pinned old/new key identities; a previously sealed handoff remains
bound to its original key ID.

The local qualification verifies protected key mode, exact CLI identities,
SQLite restart, concurrent discovery, exact resend, and the custody-finalized
after-response-loss cut. Real OS-principal separation, service-manager
sandboxing, live key rotation/revocation, disk-full behavior, coherent live
backup/restore, and physical power-loss behavior remain designated-host gates.

## End-to-end qualified run

The ignored Nightshift synthetic-cache integration test now invokes this
one-shot command directly between the O0 Docket settlement and Nightshift's
external-evidence composition. The retained 2026-08-22 run is
`/tmp/ag-synthetic-cache-orchestrated-v3`:

- trigger `sha256:302ebefe28e704427231d54a7a49f4420fac87af1bd46179f840fe8009ed43d9`;
- request `sha256:5d35fe258770b83c8cd8a570d19784f7f9a88858e04aa85c1c4dfd03d19f4598`;
- handoff `sha256:ae98930514d3cf64d8322823e93fbd645f0b4a7ff09498c19d611cbcc2799321`;
- evidence `sha256:b619b7fef7460326f5d70d13397cd7d147b1727630d9cbe58f6d6a4e33fae81d`;
- Nightshift custody `sha256:4399fd562941ed3c5fa3cb53465733e78cd9c7dcb77d53b88d5e33b578076c60`.

The ledger contains exactly one each of `trigger_recorded`,
`acquisition_scheduled`, `adapter_invocation_started`,
`adapter_returned_evidence`, and `custody_accepted`. The canonical observation
then opened O1 through ordinary standing and one-use authorization, and O1's
governed teardown left no Compose containers or network. Re-running the exact
one-shot command after completion retained those same five events and the
original `observed_at_unix_ms`; transport replay created no new acquisition.

## Read-only inspection

Phosphor-ng may call only `export-occurrence` with exact campaign/occurrence
coordinates. It renders trigger, request, adapter, settlement, evidence, and
immutable stage sequence as mechanics provenance. It separately renders
Nightshift custody/composition/currentness. Display age cannot satisfy
currentness. `/phosphor/design` gains no runtime mutation path.

This orchestration is bounded work caused by one exact settlement. It neither
runs forever nor accumulates an arbitrary monitoring configuration. Continuous
monitoring remains out of scope.
