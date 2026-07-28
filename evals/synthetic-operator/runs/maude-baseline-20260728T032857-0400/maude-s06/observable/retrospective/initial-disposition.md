Disposition: settled with a retained validation-evidence limitation.

Maude accepted task/plan.md as approved and reported verified playbook, ration-card, and approval references. Supervised session sess_ux_task_06 completed one Edit and one Bash tool call under the in-envelope grant. The pending promotion named only systemd/menu-board.service, and its unified diff changed only ExecStart by appending `--config /etc/menu-board/config.toml`. I kept the promotion.

Post-settlement inspection of the repository shows:
`ExecStart=/usr/bin/env menu-board --foreground --config /etc/menu-board/config.toml`
with `Restart=on-failure` and `WantedBy=multi-user.target` unchanged. Maude reports no pending changes and records `promotion_resolved`.

Lifecycle interpretation: launch creates the bounded supervised run; allowed/completed events mean the governor admitted and the harness finished the displayed action within the declared envelope; pending promotion means changes are proposed but not yet settled; keep resolves the reviewed promotion into the disposable repository. These states do not independently prove semantic correctness.

Evidence limitation: the canonical event stream shows the Bash validation tool call as allowed and completed, but the public output inspected did not expose its command stdout, exit status, or a detailed validation result. I therefore do not claim independently observed successful `systemd-analyze verify`; I claim only the exact settled file effect and Maude completed validation-action event.
