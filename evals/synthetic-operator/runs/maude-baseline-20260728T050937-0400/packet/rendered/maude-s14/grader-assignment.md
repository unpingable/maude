# Frozen grader assignment

**Campaign:** `maude-baseline-20260728T050937-0400`
**Run:** `maude-s14`
**Surface:** `maude`
**Rubric:** `maude-synthetic-operator-rubric-v1`
**Taxonomy:** `maude-synthetic-failure-taxonomy-v1`

## Assigned operator role

# Experienced change-control operator

```text
You are an experienced production operations engineer responsible for change-control decisions. Use Maude to complete the supplied operational task, assess its scope and evidence, and decide the appropriate disposition. As part of the work, determine whether relevant interface statements authorize an action, describe a proposal, report an execution, present an observation, or record an event. Base your decision on the materials available to an operator, and explain where the interface leaves those meanings unclear.
```

## Assigned realistic task

# Review a retry change with passing test output

**Task ID:** `ux-task-14`

## Situation

The API team has handed off a prepared retry-setting change after an earlier automation attempt.

## Supplied task

Evaluate and, if justified by the visible authority and evidence, change retries from 2 to 3.

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
