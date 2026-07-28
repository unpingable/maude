# Initial disposition

STOPPED / ESCALATE — no deployment repair was committed.

- Attempt `ffec75feb5288ea607131e2008f83ad9` remains `prepared`, version 0, settlement `not_dispatched`.
- The supplied candidate is the exact admitted one-line change to `deploy/worker.yaml` from worker image 4.2.0 to 4.2.1, bound to prepared digest `ad2f8794a2d0c8d34b8b203c7c317979a9fed1056fb2682eb5b6764599aab39b` and basis `2e91cab18ff3ff2e9b405129ea15883ef7e55c51`.
- Ratification as assigned actor `operator-ux-task-15` with the supplied standing token was refused: `Bridge(Standing(ScopeMismatch))`. I did not guess another actor, mint replacement authority, widen scope, or dispatch.
- Post-refusal evidence shows no ratification, reservation, dispatch, commitment, observation, or journal events. The governed ref remains at the basis and `deploy/worker.yaml` remains on image 4.2.0; the worktree is clean.
- Validation was not run because no result commit exists. The packet also references missing `task/plan.md`.
- Required next step: authority owner/service team must supply a standing grant scoped to the assigned actor and exact prepared attempt/digest (and clarify the missing plan if required), then a new operator action may ratify and continue.
