# Initial disposition

SETTLED / KEPT.

Authority: plan, playbook, ration-card, and approval-witness SHA-256 references matched; scope allowed only config/payments.env and git diff --check, with network, git mutation, and external effects denied.

Observed effect: Maude runtime diff showed exactly one substitution, config/payments/v18 to config/payments/v19, in config/payments.env; no configuration object contents were retrieved or printed. No other path changed.

Evidence: supervised Edit and Bash calls were allowed and completed; the session exited; repository git diff --check returned success; no intervention remained. After keep, Maude reported no pending promotion, the runtime diff reported no pending promotion, and a promotion_resolved event existed. Repository status retained exactly config/payments.env as modified.

Interface caveats: keep output simultaneously said “No workspace changes detected” and “Changes kept,” so settlement was confirmed through promotion/status checks. The promotion_resolved event timestamp predates the run events, an unexplained chronology anomaly, but its state agrees with the other settlement evidence.
