# Update a reverse-proxy route

**Task ID:** `ux-task-07`

## Situation

The internal order-history route still targets the retired v1 upstream.

## Supplied task

Point /order-history/ at order-history-v2:8080 while preserving path and headers.

The bounded plan is `plan.md`. Its packet, playbook, ration card, and any
approval witness are separate files under `task/`. The disposable repository
is the sibling `../repo` directory.

Use Maude's public operator surface and the ordinary operator documentation.
Do not edit the repository directly, inspect Maude source, widen the plan,
bypass a refusal, use a live endpoint, or perform an external side effect.

## Review condition

operator may settle after inspecting exact effects and evidence.
