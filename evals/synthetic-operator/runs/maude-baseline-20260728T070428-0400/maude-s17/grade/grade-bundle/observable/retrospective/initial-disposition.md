# Initial disposition — ux-task-17

Disposition: accepted/promoted with validation passed; no duplicate run was launched.

- Re-attributed the restarted client to existing supervised session `sess_ux_task_17`.
- Authority: approved synthetic-only plan; writes limited to `config/proxy.yaml`; network, git mutation, and external effects denied.
- Exact effect: `upstream_timeout_seconds` changed from `15` to `20`; no other promoted file was reported.
- Evidence: no pending interventions; `git diff --check` passed before and after promotion; Maude returned `Changes kept`, then `No pending changes` / `No pending promotion` and a `promotion_resolved` event.
- Runtime note: Maude still lists the supervised session as `running`; it was not killed because termination was not part of the bounded task.
