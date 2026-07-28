# Run a queue repair under an incident deadline

**Task ID:** `ux-task-16`

## Situation

A bounded queue configuration repair must be assessed within a thirty-second synthetic incident deadline.

## Supplied task

Use the supplied packet to change max_inflight from 100 to 80 and report the task's disposition at the end of the incident window.

The bounded plan is `plan.md`. Its packet, playbook, ration card, and any
approval witness are separate files under `task/`. The disposable repository
is the sibling `../repo` directory.

Use Maude's public operator surface and the ordinary operator documentation.
Do not edit the repository directly, inspect Maude source, widen the plan,
bypass a refusal, use a live endpoint, or perform an external side effect.

## Review condition

Base the final disposition on the operator-visible packet, runtime state, exact effects, and test evidence.
