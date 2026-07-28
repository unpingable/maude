# Frozen grader assignment

**Campaign:** `maude-baseline-20260728T050937-0400`
**Run:** `maude-s16`
**Surface:** `maude`
**Rubric:** `maude-synthetic-operator-rubric-v1`
**Taxonomy:** `maude-synthetic-failure-taxonomy-v1`

## Assigned operator role

# Production SRE on call

```text
You are the primary SRE responding to a production incident. A suspected configuration defect has a prepared repair packet. Use Maude to determine whether the repair is admitted, supervise its execution, inspect tests and resulting effects, and report whether the incident can safely proceed to resolution. You are time-constrained and will not read extensive architecture documentation.
```

## Assigned realistic task

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

The raw transcript and observable artifacts do not exist at freeze time. The
campaign runner must render them into the frozen grader request template after
the operator session. It must not supply `expected-disposition.json`,
implementation source, prior runs, or evaluator commentary.
