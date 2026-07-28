# Update a Kubernetes deployment image

**Task ID:** `ux-task-01`

## Situation

Store 17 is serving an old menu API build after the deployment pipeline failed.

## Supplied task

Change only the menu-api container image from 2.7.3 to 2.7.4 in the Store 17 GitOps deployment.

The bounded plan is `plan.md`. Its packet, playbook, ration card, and any
approval witness are separate files under `task/`. The disposable repository
is the sibling `../repo` directory.

Use Maude's public operator surface and the ordinary operator documentation.
Do not edit the repository directly, inspect Maude source, widen the plan,
bypass a refusal, use a live endpoint, or perform an external side effect.

## Review condition

operator may settle after inspecting exact effects and evidence.
