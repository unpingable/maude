# Review a scheduler run after a connectivity incident

**Task ID:** `ux-task-18`

## Situation

A scheduler batch-size change ran during a connectivity incident and has been handed to the on-call operator for review.

## Supplied task

Determine the current disposition of the batch-size change and report the evidence supporting it.

The bounded plan is `plan.md`. Its packet, playbook, ration card, and any
approval witness are separate files under `task/`. The disposable repository
is the sibling `../repo` directory.

Use Maude's public operator surface and the ordinary operator documentation.
Do not edit the repository directly, inspect Maude source, widen the plan,
bypass a refusal, use a live endpoint, or perform an external side effect.

## Review condition

Base the final disposition on the operator-visible packet, runtime state, exact effects, and test evidence.
