# Initial disposition

Discarded the run changes.

- Authority verified: plan, playbook, ration-card, and approval-witness digests matched; scope allowed only nginx/routes.conf and the nginx configuration test, with network and Git denied.
- Exact effect inspected: the sole diff changed proxy_pass from order-history-v1:8080 to order-history-v2:8080; /order-history/ and X-Request-ID were preserved.
- Validation evidence was insufficient to settle: the event stream showed a Bash call completed, but did not expose its exact command, exit status, or output, and the run screen reported an unknown exit code.
- In accordance with the plan stop condition, I discarded the pending promotion. Maude reported the workspace reverted; repository status/diff were clean and routes.conf again targets v1.
