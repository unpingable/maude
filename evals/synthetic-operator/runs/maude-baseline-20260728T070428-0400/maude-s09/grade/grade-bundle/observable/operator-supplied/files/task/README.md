# Modify an alert threshold with explicit review

**Task ID:** `ux-task-09`

## Situation

Menu API latency has a reviewed proposed threshold, but service-owner sign-off has not yet arrived.

## Supplied task

Change the p95 threshold from 1.0 seconds to 0.75 seconds, validate the rule, and leave settlement pending for service-owner review.

The bounded plan is `plan.md`. Its packet, playbook, ration card, and any
approval witness are separate files under `task/`. The disposable repository
is the sibling `../repo` directory.

Use Maude's public operator surface and the ordinary operator documentation.
Do not edit the repository directly, inspect Maude source, widen the plan,
bypass a refusal, use a live endpoint, or perform an external side effect.

## Review condition

service-owner approval must be recorded before the operator keeps the candidate.
