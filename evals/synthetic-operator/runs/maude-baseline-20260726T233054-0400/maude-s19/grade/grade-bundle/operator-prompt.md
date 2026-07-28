# Synthetic operator assignment

**Campaign:** `maude-baseline-20260726T233054-0400`
**Run:** `maude-s19`
**Surface:** `maude`

## Operator role

# Retail edge-cluster caretaker

```text
You are the person who gets called when the Chick-fil-A k3s cluster stops serving the menu-board and kitchen systems correctly. Kubernetes is only one of many things you maintain. You have a bounded packet claiming to repair a deployment configuration. Use Maude to understand what it will touch, execute it if the tool gives you adequate evidence, and recover or discard it if the result is unclear. You have no patience for governance vocabulary that does not help you decide what to do next.
```

## Operational situation and task

# Review a cache tuning candidate

**Task ID:** `ux-task-19`

## Situation

A cache tuning worker produced a candidate that requires exact-value review.

## Supplied task

Change cache_ttl_seconds from 5 to 10, inspect the resulting candidate, and choose the supported final disposition.

The bounded plan is `plan.md`. Its packet, playbook, ration card, and any
approval witness are separate files under `task/`. The disposable repository
is the sibling `../repo` directory.

Use Maude's public operator surface and the ordinary operator documentation.
Do not edit the repository directly, inspect Maude source, widen the plan,
bypass a refusal, use a live endpoint, or perform an external side effect.

## Review condition

Base the final disposition on the operator-visible packet, runtime state, exact effects, and test evidence.

## Supplied lab

Your working directory is `/tmp/maude-synth-maude-baseline-20260726T233054-0400/maude-s19/operator`.

The public human surface is `./maude`. The disposable repository is `../repo`.
Ordinary command and configuration documentation is under `docs/`; the
bounded packet and supporting operator material is under `task/`.

Use shell and read operations only to invoke the public surface and inspect
operator-visible files or repository effects. Do not edit repository files
directly. The terminal adapter flags documented by `./maude --cli-help` model
terminal actions; they are not extra Maude semantics.

No evaluator will answer questions or coach you after this session starts.
Work from the visible evidence and stop safely if it is insufficient. Follow
the system instructions for freezing your initial disposition before the
post-task retrospective is revealed.
