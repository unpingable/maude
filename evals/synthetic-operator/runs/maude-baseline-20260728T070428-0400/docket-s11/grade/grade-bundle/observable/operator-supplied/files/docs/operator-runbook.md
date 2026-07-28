# Operator runbook

What each outcome establishes, what it does not, and what to do next. This is
presentation over the recorded evidence — nothing here adds policy to the runtime, and
nothing here discharges an obligation. The evidence surfaces are `docket list`,
`docket show` (the [dossier](attempt-dossier.md)), and `docket journal` (digest-verified
journal view); all three accept `--json`.

Recurring rules:

- **Retry is never a re-dispatch.** One dispatch identity exists per attempt, forever.
  Where "retry" is safe below, it always means *a new attempt* (new admission, new
  standing, new reservation) against the current basis.
- **Standing is consumed, not checked.** Any refusal that happened *before* consumption
  leaves the grant intact; after a successful ratification the grant is spent regardless
  of what happens later.
- **Recovery verdicts are premise-qualified.** `committed_via_recovery` and
  `proven_not_committed` are valid relative to asserted `ExclusiveRefCustody`
  ([trust model §2](trust-model.md)); the dossier's qualification block states this per
  attempt.
- **A checkout path is not repository identity.** Register a Docket-owned
  `RepositoryId` before creating new work, and pass both that ID and its current path
  locator. The complete contract and migration procedure are in
  [repository identity and ref continuity](repository-identity-and-ref-continuity.md).

## Repository setup and continuity handoff

For a new repository, run `docket repository register --repo <absolute-path>` in the
intended state directory. Keep the printed `repo-…` value and supply it to
`docket request create --repository-id <repo-id> --repo <absolute-path> …`. Docket
refuses an unregistered ID, a non-current path, a relative path, or a path/remote/Git
object presented as identity.

Opening an existing state store does not infer identities from paths. Register the old
path explicitly, then use
`docket repository migrate-attempt --repository-id <repo-id> --attempt <attempt-id>`.
The migration refuses unless that attempt's path is already a retained alias for the
named ID, and it cannot rebind a work request that already has another ID.

After relocating or recloning, run
`docket repository relocate --repository-id <repo-id> --repo <new-absolute-path>`.
`repository show --json` should then show the new path as current and the prior path as a
retained non-current alias. The logical ID does not change.

For an identified attempt with a normal result commitment,
`docket continuity subject --attempt <attempt-id> --json` emits
`gwr:ref-continuity-operation:v0`. Hand that complete operation to Continuity; do not
reconstruct its `gwr:ref-continuity:v0:<repo>#<ref>@<commit>` subject from the path or
from a familiar-looking endpoint. The command refuses legacy-unbound and uncommitted
attempts. It does not itself inspect Git or claim that continuity currently holds.

## 1. `committed` (normal settlement)

- **Established:** the broker acknowledged the atomic ref transition; the target ref
  moved basis → result commit exactly once. Evidence: dossier `execution.commitment`
  (result, journal digest); `docket journal` → `verified_complete` ending
  `acknowledged`.
- **Not established:** correctness, completion, merge safety, obligation discharge.
- **Retry:** nothing to retry. **New standing:** no. **Escalation:** no.
- **Next:** run `docket observe` if not yet observed; check
  `observation.residual_obligations` — `HumanReviewBeforeMerge` still stands.

## 2. `committed_via_recovery`

- **Established:** under the asserted custody premise, the effect landed exactly once;
  the observed ref held exactly the commit the digest-verified journal recorded
  creating, and resolution consumed *separate* recovery standing.
- **Not established:** anything beyond the Git-class claims; and the verdict is a ref
  reading, so it is premise-relative.
- **Retry:** no — the effect committed. **New standing:** none further. **Escalation:**
  only if the custody premise was not actually arranged in your deployment.
- **Next:** dossier `qualification` (`evidence_agrees` should be true, concordance
  `observed_matches_expected_result`); then proceed as for `committed`.

## 3. `proven_not_committed` (premise-qualified)

- **Established:** the effect is not presently reflected in the target ref; **under the
  asserted custody premise**, that it never committed.
- **Not established:** unconditional non-occurrence. External ref mutation between
  dispatch and the recovery observation makes the same evidence consistent with a
  landed-then-reverted effect.
- **Retry:** a *new attempt* is safe **only if the custody premise held**. If anything
  else can write the ref, treat the attempt as unresolved for any purpose that depends
  on non-occurrence.
- **New standing:** yes, for the new attempt. **Escalation:** yes if
  `qualification.evidence_agrees` is false (journal records an effect commit the ref
  does not hold) — a human must decide whether custody actually held.
- **Next:** dossier `qualification` (observed ref, expected result commit, concordance,
  owner); `docket journal` — a `verified_partial` journal with `ref_updated` present is
  exactly the disagreement case.

## 4. `indeterminate` / conflicting recovery evidence

- **Established:** a dispatch exists whose outcome is unknown; this is a positive,
  durable fact. Nothing else — no success or failure has been minted.
- **Not established:** whether the effect landed.
- **Retry:** **never** under this attempt; do not prepare a new attempt against the same
  ref until this one resolves — the basis may or may not have moved.
- **New standing:** yes — resolution requires *recovery* standing
  (`--act resolve-recovery`), distinct from ratification standing.
- **Escalation:** if `recover fact` shows `observed_ref` matching neither the basis nor
  the expected result, or repeated resolution refuses `ConflictingEvidence`, stop and
  investigate by hand; the attempt legitimately stays indeterminate.
- **Next:** `docket journal` (how far did the broker get?); `docket recover fact`; then
  `docket recover resolve` under recovery standing.

## 5. `UnsupportedEffectClass` (and `BasisNotACommitHash`, `NoAdmittedPaths`, `PathNotAdmissible`)

- **Established:** the proposal is not expressible in the one admitted effect class
  (`git-ref-update:v1`). Nothing was created or spent — no request/attempt (depending on
  the gate), no standing, no reservation, no dispatch, no provider run.
- **Not established:** anything about the repository; nothing was interpreted.
- **Retry:** yes, freely — re-propose as a well-formed Git ref effect, or take the work
  somewhere that supports the needed effect kind ([effect classes](effect-classes.md)).
- **New standing:** none was consumed. **Escalation:** no.
- **Next:** nothing to inspect; the refusal names the offending field.

## 6. `dispatch_refused` ground `forbidden_path`

- **Established:** the broker refused before any ref update because the patch would
  touch a path outside the admitted set; no effect occurred. The dispatch (and its one
  reservation use) is spent.
- **Not established:** nothing about intent — only that the patch and the admitted scope
  disagree.
- **Retry:** new attempt, either with a corrected candidate or a deliberately widened
  `--allow` set. **New standing:** yes. **Escalation:** consider it if the provider
  produced a patch that reaches for paths it was not asked to touch.
- **Next:** dossier identity section (`allowed_path` lines) against the candidate patch;
  `docket journal` shows the refusal position.

## 7. `dispatch_refused` ground `basis_moved`

- **Established:** at dispatch the ref no longer held the admitted basis; the broker
  refused; no ref update occurred.
- **Not established:** who moved the ref or whether the candidate is still meaningful.
- **Retry:** new attempt against the *current* basis, usually with a re-prepared
  candidate. **New standing:** yes. **Escalation:** if nothing legitimate should have
  moved the ref, treat it as a custody question before re-attempting.
- **Next:** `git rev-parse <target-ref>` vs dossier `basis`; `docket list` to see
  whether a sibling attempt committed in between.

## 8. Expired or already-consumed standing (`StandingExpired`, `StandingAlreadyUsed`)

- **Established:** the presented grant is outside its window or already spent; the
  ratification (or resolution) did not happen; nothing was consumed by the refusal
  itself.
- **Not established:** nothing about the attempt, which stays exactly where it was.
- **Retry:** yes — same attempt, **new grant** (`docket grant standing …`); expired
  grants do not revive, ever.
- **New standing:** yes, that is the whole remedy. **Escalation:** only if a grant is
  reported consumed and no one recognizes the use — the dossier's authority section
  names the consuming use and time.
- **Next:** dossier `authority` (grant expiry, `consumed_by`, `used_at_ms`).

## 9. Missing observation / observation failure

- **Established:** if no observation exists, nothing was ever measured. If one exists
  with nonzero exit: the effect committed *and* the named command failed against it —
  commitment is never rewritten by observation.
- **Not established:** a failing observation does not un-commit anything; a missing one
  does not make the effect suspect.
- **Retry:** observations may be re-run freely (`docket observe`); the effect is never
  re-run.
- **New standing:** no. **Escalation:** treat repeated failures as a review question on
  the change itself.
- **Next:** dossier `observation` section (argv, exit status, result commit scope).

## 10. Inadmissible reliance claim (`ClaimNotAdmissible`, `ObservationOutOfScope`, `ObservationFailed`)

- **Established:** the bridge refused to let *this consumer* treat *this observation* as
  establishing *this claim*. The refusal is recorded with its subject; the source
  records are untouched.
- **Not established:** the refusal is not the claim's negation — nothing new is known
  about safety or correctness either way.
- **Retry:** present the one admissible claim (`effect-and-command`), or bring a
  correctly-scoped passing observation. **New standing:** no. **Escalation:** claims
  like `safe-to-merge` are permanently inadmissible here — that judgment belongs to
  human review, which is the escalation.
- **Next:** dossier `observation.reliance_refusals` (kind + subject).

## 11. Residual obligations

- **Established:** something is still owed after mechanical completion —
  `HumanReviewBeforeMerge` in v0. Reconciliation *retains* obligations; nothing in the
  runtime discharges them.
- **Not established:** that anyone has done the review; there is no discharge record to
  look for.
- **Retry:** n/a. **New standing:** no. **Escalation:** yes by definition — the
  obligation *is* the human step.
- **Next:** dossier `observation.residual_obligations`; `docket list` shows the
  outstanding count per attempt.
