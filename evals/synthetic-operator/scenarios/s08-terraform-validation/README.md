# Repair a Terraform validation rule without applying

**Task ID:** `ux-task-08`

## Situation

A module accepts replica counts that exceed the platform quota.

## Supplied task

Cap replicas at 50 in the variable validation rule. Validate only; never plan or apply infrastructure.

The supplied plan is [`plan.md`](plan.md). Its supporting playbook, ration card,
and any approval witness are separate files in this directory. The disposable
repository begins with the files under `fixture/`.

Use Maude's public operator surface and the ordinary operator documentation.
Do not edit the fixture directly, inspect Maude source, widen the plan, bypass a
refusal, use a live endpoint, or perform an external side effect.

## Review condition

operator may settle after inspecting exact effects and evidence.
