# Review a cache tuning candidate

**Task ID:** `ux-task-19`

## Situation

A cache tuning worker produced a candidate that requires exact-value review.

## Supplied task

Change cache_ttl_seconds from 5 to 10, inspect the resulting candidate, and choose the supported final disposition.

The bounded plan is `plan.md`. Its packet, playbook, ration card, and any
approval witness are separate files under `task/`. The disposable repository
is the sibling `../repo` directory.

Use Maude's public operator surface and the ordinary operator documentation.
Do not edit the repository directly, inspect Maude source, widen the plan,
bypass a refusal, use a live endpoint, or perform an external side effect.

## Review condition

Base the final disposition on the operator-visible packet, runtime state, exact effects, and test evidence.
