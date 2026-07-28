# Change a service memory limit

**Task ID:** `ux-task-03`

## Situation

The API deployment is repeatedly OOM-killed at its measured steady-state load.

## Supplied task

Raise only the api container memory limit from 256Mi to 384Mi; leave requests and CPU limits unchanged.

The bounded plan is `plan.md`. Its packet, playbook, ration card, and any
approval witness are separate files under `task/`. The disposable repository
is the sibling `../repo` directory.

Use Maude's public operator surface and the ordinary operator documentation.
Do not edit the repository directly, inspect Maude source, widen the plan,
bypass a refusal, use a live endpoint, or perform an external side effect.

## Review condition

operator may settle after inspecting exact effects and evidence.
