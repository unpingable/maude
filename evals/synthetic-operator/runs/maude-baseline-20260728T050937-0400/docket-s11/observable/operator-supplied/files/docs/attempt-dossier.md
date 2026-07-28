# The canonical attempt dossier

The supported evidence/read surface for an attempt. Introduced after the first pilot
([`pilot-01.md`](../pilot-01.md)), whose central finding was that the runtime recorded
nearly everything and exposed nearly nothing (P-1), and displayed its one
premise-dependent verdict without the premise (P-2).

## One model, two renderings

`gwr_runtime::services::dossier` defines a single read model, `AttemptDossier`,
assembled from the store alone. Both operator surfaces are pure functions of the same
assembled value:

```bash
docket show --attempt <id>          # human rendering
docket show --attempt <id> --json   # versioned JSON rendering
```

There is no second assembly path, so the surfaces cannot drift. The JSON carries a
versioned `dossier_format`; any change to its key set or value encodings is a version
bump, not an edit. The current formats are v2 for a legacy work request without an
explicit repository binding and v3 for an identified work request. v1 is the earlier
closed format; v2 added upstream-authorization provenance. See
[`repository-identity-and-ref-continuity.md`](repository-identity-and-ref-continuity.md)
for the v2/v3 identity boundary and explicit migration.

## What it exposes

Only records the runtime already owns — the dossier manufactures no facts:

- **Identity and preparation** — goal, work request, Docket-owned `RepositoryId` and
  path locator in v3 (legacy path spelling only in v2), target ref, basis, exact
  ref-continuity subject when a matching result commitment exists, effect class and its
  declared settlement premises, admitted paths, candidate and preparation-run
  identities, candidate/patch/prepared-attempt digests, observation plan, and
  creation/admission timestamps.
- **Authority and reservation** — ratification receipt (actor, standing use, time), the
  ratifying grant's scope and exact digest binding, expiry and consumption status, the
  reservation and its consumption, the one dispatch identity, and — separately — the
  recovery grant where one was consumed. No token text, no MAC material: a grant row
  identifies authority, it does not confer it.
- **Execution and settlement** — lifecycle state, version, timestamped timeline,
  commitment (previous value → result commit, journal digest), dispatch refusal ground,
  indeterminacy record, recovery facts, resolution, and a derived `settlement`
  classification (`normal` / `refused` / `unresolved` / `recovered` / `not_dispatched`).
- **Observation and reliance** — full observation records, reliance admissions, reliance
  refusals **with their subject** (which observation, presented to which consumer, for
  which claim), residual obligations, and the reconciliation that retained them.
- **Qualification** — present exactly when a recovery resolution exists; see below.

Reads are total over honest stores and typed over broken ones: a malformed persisted
column surfaces as `StoreError::Corrupt`, a projection whose ledger record is missing as
`DossierError::MissingRecord` — never a panic, never a defaulted field. Records
persisted before newer columns existed read back with those fields absent, not invented
(e.g. pre-migration reliance refusals show *subject not recorded*).

## Qualified recovery verdicts

A recovery verdict is never rendered as unconditional history. The qualification block
carries:

- the verdict and its proof basis (the runtime's reading of the target ref plus the
  broker journal verified against the digest recorded at indeterminacy);
- the custody premise: `ExclusiveRefCustody`, **asserted by the deployment at
  resolution, not verified by the runtime**;
- the observed ref, the expected result commit from the digest-verified journal, and the
  commitment ledger's attribution of the observed commit;
- whether those records agree (`evidence_concordance` / `evidence_agrees`);
- fixed statements of what the verdict establishes and what it does not.

For `proven_not_committed` the surface states explicitly that external mutation of the
target ref between dispatch and the recovery observation would make the same evidence
consistent with an effect that landed and was reverted. When the digest-verified journal
records an effect commit that the observed ref does not hold, the disagreement is
rendered as disagreement — with both consistent histories stated — and never silently
resolved in either direction. The preserved custody-boundary specimen
(`crates/gwr-local/tests/ref_custody_boundary.rs`, pilot run C) renders exactly this
way; `crates/gwr-local/tests/dossier.rs` asserts it.

## Companion read surfaces

The same evidence model backs two further read-only surfaces; neither assembles facts
independently of the store's records:

- **`docket list [--json]`** — one canonical summary model
  (`gwr:attempt-list:v1`): identity, admission time, state, effect class, repository,
  target ref, concise admitted scope, settlement, premise qualification, and
  outstanding-obligation count. The human table truncates long values; the JSON carries
  them complete.
- **`docket journal (--attempt <id> | --dispatch <id>) [--json]`** — the broker journal
  for the attempt's one dispatch, rendered as evidence **only after its bytes hash to
  the digest the runtime persisted** with the outcome record. Statuses: `unavailable`,
  `missing`, `digest_mismatch`, `corrupt`, `verified_partial` (crash-shaped, no terminal
  phase), `verified_complete`. Unverified or out-of-vocabulary content is withheld with
  an explicit notice, never rendered. Format: `gwr:journal-view:v1`.

`docket show` and `docket journal` both resolve by attempt or by dispatch identity —
the dispatch id embedded in every governed commit subject (`gwr governed effect <id>`)
resolves to its attempt. Unknown, malformed, or doubly-given identifiers are typed
refusals.

## Stability

The JSON forms (`gwr:attempt-dossier:v2`, `gwr:attempt-dossier:v3`,
`gwr:attempt-list:v1`, `gwr:journal-view:v1`) are intended to be stable enough for later
ingestion by external tooling. The v3 dossier and
`gwr:ref-continuity-operation:v0` are now supported inputs to the continuity-aware
vertical; that support does not turn the other read formats into generic integration
APIs.
