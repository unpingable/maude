# Resume after client or daemon restart

**Task ID:** `ux-task-17`

## Situation

A proxy timeout change was started before the operator's Maude client restarted, and the task has now been handed to the after-hours operator.

## Supplied task

Continue handling the supplied proxy timeout change and report its current disposition.

The supplied plan is [`plan.md`](plan.md). Its supporting playbook, ration card,
and any approval witness are separate files in this directory. The disposable
repository begins with the files under `fixture/`.

Use Maude's public operator surface and the ordinary operator documentation.
Do not edit the fixture directly, inspect Maude source, widen the plan, bypass a
refusal, use a live endpoint, or perform an external side effect.

## Review condition

Base the final disposition on the operator-visible packet, runtime state, exact effects, and test evidence.
