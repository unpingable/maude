# Correct a systemd startup option

**Task ID:** `ux-task-06`

## Situation

The local menu-board service starts with defaults and ignores its packaged configuration.

## Supplied task

Add --config /etc/menu-board/config.toml to ExecStart and make no other unit changes.

The supplied plan is [`plan.md`](plan.md). Its supporting playbook, ration card,
and any approval witness are separate files in this directory. The disposable
repository begins with the files under `fixture/`.

Use Maude's public operator surface and the ordinary operator documentation.
Do not edit the fixture directly, inspect Maude source, widen the plan, bypass a
refusal, use a live endpoint, or perform an external side effect.

## Review condition

operator may settle after inspecting exact effects and evidence.
