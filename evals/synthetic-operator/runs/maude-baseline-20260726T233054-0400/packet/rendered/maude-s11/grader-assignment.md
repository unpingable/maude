# Frozen grader assignment

**Campaign:** `maude-baseline-20260726T233054-0400`
**Run:** `maude-s11`
**Surface:** `maude`
**Rubric:** `maude-synthetic-operator-rubric-v1`
**Taxonomy:** `maude-synthetic-failure-taxonomy-v1`

## Assigned operator role

# Skeptical first-time user

```text
You are evaluating Maude for possible adoption by an operations team. Complete the supplied task without prior exposure to the constellation. Identify every concept the interface requires you to understand before it becomes useful, and distinguish necessary operational complexity from architecture leaking into the UX.
```

## Assigned realistic task

# Review a one-file menu image packet

**Task ID:** `ux-task-11`

## Situation

Store 17 needs a routine menu API patch, and the application team has handed off a prepared maintenance packet.

## Supplied task

Update apps/menu/deployment.yaml from menu-api:2.7.3 to menu-api:2.7.4.

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
