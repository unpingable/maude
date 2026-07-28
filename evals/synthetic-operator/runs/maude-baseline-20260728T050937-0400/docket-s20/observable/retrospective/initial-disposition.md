# Initial disposition

Disposition: **change is presently applied, but the Docket attempt remains operationally unresolved/indeterminate**. Do not retry or claim normal settlement. The visible evidence supports that the governed ref currently contains the intended effect; it does not supply a recorded recovery resolution or prove uninterrupted exclusive ref custody.

Evidence:

- Attempt `1e45170f58e5bdbc37c4a38b2180091b` is Docket state `indeterminate`, settlement `unresolved`, with no commitment, recovery fact, resolution, observation, or qualification.
- The digest-verified journal for dispatch `e12344ba9dc56b3813739263fdd5036e` is `verified_partial` and records `commit_created` plus `ref_updated` from basis `4da646e4f225c5a2d6ff3af554454232041088aa` to result `66406c7216ad8e5580770d332bd0b4416244d858`; it lacks a terminal acknowledgement.
- A direct read of `refs/gwr/target` returns exactly `66406c7216ad8e5580770d332bd0b4416244d858`.
- The basis-to-result diff changes only admitted path `deploy/api.yaml`, from image `9.0.0` to `9.0.1`, matching `candidate.patch`.
- `git diff --check` across the exact basis and result exits 0. This is test evidence for patch cleanliness only, not API health, merge safety, or Docket settlement.

Missing/retained unknowns: no supplied recovery standing and no recorded recovery resolution; exclusive ref custody is declared as a settlement premise but is not verified by the runtime. No live endpoint or external validation was permitted.

Fatigue hazards:

- The runbook spells read commands as `docket list/show/journal`, but the frozen executable requires the duplicated form `./bin/docket docket list/show/journal`; `./bin/docket --help` fails as `unknown command []`.
- `verified_partial` sounds broadly incomplete even when its events include `ref_updated`; meanwhile the headline state remains `indeterminate`. An exhausted operator could read only one of these and wrongly retry or wrongly declare normal success.
- The human-relevant actor label is rendered as an opaque hash, and millisecond timestamps are not rendered as readable dates.
