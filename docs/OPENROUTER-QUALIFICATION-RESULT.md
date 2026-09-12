# Bounded OpenRouter qualification result

On 2026-09-12, the separately authorized `openrouter-authoring-002` occurrence
contacted OpenRouter once through Maude's enrolled Switchyard v3 route. The
frozen request selected `anthropic/claude-sonnet-4.5`, allowed no provider/model
substitution or semantic retry, and reserved 81,408 microdollars within its new
100,000-microdollar occurrence allowance.

The provider returned HTTP 400. Switchyard recorded `PROVIDER_REFUSED`,
`RESPONSE_OBSERVED`, zero internal retries, no worker output, and no observable
provider/model execution identity, usage, or cost. Maude consequently recorded
`proposal-not-generated` with `SwitchyardAttemptError` and
`NOT_ACCEPTED_BY_PRODUCER`.

No proposal or semantic diff exists to review, because no provider output passed
the enrolled route. The original synthetic draft remains unchanged. This result
qualifies fail-closed refusal and single-contact custody; it does not qualify a
successful structured provider response. It grants no authority to retry,
accept, check, lock, compile, execute, or spend again.

The earlier occurrence 001 remains separate: it received HTTP 200 but its
Markdown-fenced JSON failed Maude's strict parser. Neither occurrence produced
an accepted proposal. Any successor call requires a new explicit authorization,
budget, occurrence identity, and human review boundary.
