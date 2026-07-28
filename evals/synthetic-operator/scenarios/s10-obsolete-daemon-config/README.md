# Remove an obsolete daemon package entry

**Task ID:** `ux-task-10`

## Situation

Edge hosts no longer run the legacy telnet diagnostic daemon, but its package remains in the base role.

## Supplied task

Remove only telnetd from the package list; retain chrony and jq.

The supplied plan is [`plan.md`](plan.md). Its supporting playbook, ration card,
and any approval witness are separate files in this directory. The disposable
repository begins with the files under `fixture/`.

Use Maude's public operator surface and the ordinary operator documentation.
Do not edit the fixture directly, inspect Maude source, widen the plan, bypass a
refusal, use a live endpoint, or perform an external side effect.

## Review condition

operator may settle after inspecting exact effects and evidence.
