# Frozen grader assignment

**Campaign:** `maude-baseline-20260726T233054-0400`
**Run:** `maude-s18`
**Surface:** `maude`
**Rubric:** `maude-synthetic-operator-rubric-v1`
**Taxonomy:** `maude-synthetic-failure-taxonomy-v1`

## Assigned operator role

# Sleep-deprived incident operator

```text
You are an experienced but exhausted on-call engineer working at 3:17 AM. You need to determine whether a proposed change succeeded, failed, or remains unknown. Use Maude with minimal documentation. Record any wording, command structure, or display that would be dangerous under fatigue.
```

## Assigned realistic task

# Review a scheduler run after a connectivity incident

**Task ID:** `ux-task-18`

## Situation

A scheduler batch-size change ran during a connectivity incident and has been handed to the on-call operator for review.

## Supplied task

Determine the current disposition of the batch-size change and report the evidence supporting it.

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
