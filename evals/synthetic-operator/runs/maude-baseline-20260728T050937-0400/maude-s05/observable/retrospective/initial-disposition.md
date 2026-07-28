# Initial disposition

SETTLED — ACCEPTED.

Authority provenance verified: the plan SHA-256 matches the approval witness; the playbook and ration-card SHA-256 values match the plan; policy reported approved with the single allowed write path config/payments.env, only git diff --check allowed for worker execution, and network/Git mutation denied.

Observed effect: Maude’s promotion diff showed exactly PAYMENTS_CONFIG_REF changing from config/payments/v18 to config/payments/v19 in config/payments.env; the adjacent LOG_LEVEL line was unchanged. No configuration object contents were retrieved or printed. Repository status showed only config/payments.env modified.

Evidence: the run recorded allowed/completed Edit and Bash calls, no pending interventions, and git diff --check exited 0 both before and after settlement. Maude kept the change and then reported no pending changes/promotion.

Operator-surface caveats: before settlement, supervised list incorrectly said “No workspace changes detected” while promotion and diff showed one pending changed file. The promotion_resolved event timestamp was earlier than the preceding run events, so event chronology is not reliable even though settlement state is clear from the promotion query.
