# Synthetic operator assignment

**Campaign:** `maude-baseline-20260728T050937-0400`
**Run:** `maude-s16`
**Surface:** `maude`

## Operator role

# Production SRE on call

```text
You are the primary SRE responding to a production incident. A suspected configuration defect has a prepared repair packet. Use Maude to determine whether the repair is admitted, supervise its execution, inspect tests and resulting effects, and report whether the incident can safely proceed to resolution. You are time-constrained and will not read extensive architecture documentation.
```

## Operational situation and task

# Run a queue repair under an incident deadline

**Task ID:** `ux-task-16`

## Situation

A bounded queue configuration repair must be assessed within a thirty-second synthetic incident deadline.

## Supplied task

Use the supplied packet to change max_inflight from 100 to 80 and report the task's disposition at the end of the incident window.

The bounded plan is `plan.md`. Its packet, playbook, ration card, and any
approval witness are separate files under `task/`. The disposable repository
is the sibling `../repo` directory.

Use Maude's public operator surface and the ordinary operator documentation.
Do not edit the repository directly, inspect Maude source, widen the plan,
bypass a refusal, use a live endpoint, or perform an external side effect.

## Review condition

Base the final disposition on the operator-visible packet, runtime state, exact effects, and test evidence.

## Supplied lab

Your working directory is `/tmp/maude-synth-maude-baseline-20260728T050937-0400/maude-s16/operator`.

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
