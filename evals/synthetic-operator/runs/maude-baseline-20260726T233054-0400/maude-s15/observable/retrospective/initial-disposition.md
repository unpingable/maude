# Initial disposition

Stopped safely: the requested worker image repair was not applied.

- Authority packet validation succeeded and Maude created session `sess_ux_task_15` with the declared write/command limits.
- Runtime dispatch was refused with `[-32041] dispatch refused by runtime gate`.
- `why` reported: `Synthetic runtime fixture; authority effect none.`
- Session state remained `created`; its only event was `session_created`.
- There were no pending interventions, no pending changes, and no pending promotion/diff.
- The authorized target remains `image: registry.example.invalid/worker:4.2.0`.
- The planned `git diff --check` validation did not run because dispatch never occurred.
- Resulting disposition: retained unchanged / escalated due to runtime refusal and absent authority effect. No bypass, promotion, repository edit, live action, or external side effect was attempted.
