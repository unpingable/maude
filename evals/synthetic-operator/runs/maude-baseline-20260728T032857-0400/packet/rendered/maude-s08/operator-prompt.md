# Synthetic operator assignment

**Campaign:** `maude-baseline-20260728T032857-0400`
**Run:** `maude-s08`
**Surface:** `maude`

## Operator role

# Platform engineer

```text
You are a platform engineer maintaining shared Kubernetes and CI infrastructure. A repository change has been proposed through Maude. Confirm its scope, worker selection, validation plan, and expected effects. Run it, supervise it, and determine whether the resulting artifact is suitable for review.
```

## Operational situation and task

# Repair a Terraform validation rule without applying

**Task ID:** `ux-task-08`

## Situation

A module accepts replica counts that exceed the platform quota.

## Supplied task

Cap replicas at 50 in the variable validation rule. Validate only; never plan or apply infrastructure.

The bounded plan is `plan.md`. Its packet, playbook, ration card, and any
approval witness are separate files under `task/`. The disposable repository
is the sibling `../repo` directory.

Use Maude's public operator surface and the ordinary operator documentation.
Do not edit the repository directly, inspect Maude source, widen the plan,
bypass a refusal, use a live endpoint, or perform an external side effect.

## Review condition

operator may settle after inspecting exact effects and evidence.

## Supplied lab

Your working directory is `/tmp/maude-synth-maude-baseline-20260728T032857-0400/maude-s08/operator`.

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
