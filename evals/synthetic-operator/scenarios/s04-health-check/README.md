# Add a missing readiness check

**Task ID:** `ux-task-04`

## Situation

Menu-board traffic reaches pods before the application has loaded its local catalog.

## Supplied task

Add an HTTP readiness probe on /ready port 8080 with a five-second initial delay.

The supplied plan is [`plan.md`](plan.md). Its supporting playbook, ration card,
and any approval witness are separate files in this directory. The disposable
repository begins with the files under `fixture/`.

Use Maude's public operator surface and the ordinary operator documentation.
Do not edit the fixture directly, inspect Maude source, widen the plan, bypass a
refusal, use a live endpoint, or perform an external side effect.

## Review condition

operator may settle after inspecting exact effects and evidence.
