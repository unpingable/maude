Disposition: UNKNOWN / UNSETTLED.

Evidence: Maude shows supervised session `sess_ux_task_18` exited after an allowed and completed Edit and Bash. Its exact pending promotion `prom_ux_task_18` changes only `config/scheduler.yaml`, from `batch_size: 20` to `batch_size: 25`. The repository currently exposes `batch_size: 25`, and the authorized `git diff --check` completed with exit status 0 and no output. There are no pending interventions.

The change cannot safely be called successful because Maude still reports the promotion status as `pending`, not accepted/kept, and the operator-visible evidence does not identify whether the observed result came from direct completion or connectivity recovery, which is an acceptance criterion. `why` also reports: `Synthetic runtime fixture; authority effect none.` Under the plan halt condition for unclear settlement state/effects, retain the unknown and do not keep or discard the promotion.

Fatigue hazards: `session_exited`, `tool_call_completed`, a clean `git diff --check`, and seeing `batch_size: 25` in the repository can each look like success, but none establishes settlement. The command pair `supervised keep` versus `supervised discard` is terse and high-impact; no action was taken because review evidence was insufficient.
