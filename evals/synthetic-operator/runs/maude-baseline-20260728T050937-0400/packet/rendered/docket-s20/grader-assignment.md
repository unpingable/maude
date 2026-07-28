# Frozen grader assignment

**Campaign:** `maude-baseline-20260728T050937-0400`
**Run:** `docket-s20`
**Surface:** `docket-gwr-direct`
**Rubric:** `maude-synthetic-operator-rubric-v1`
**Taxonomy:** `maude-synthetic-failure-taxonomy-v1`

## Assigned operator role

# Sleep-deprived incident operator

```text
You are an experienced but exhausted on-call engineer working at 3:17 AM. You need to determine whether a proposed change succeeded, failed, or remains unknown. Use the supplied Docket/GWR surface with minimal documentation. Record any wording, command structure, or display that would be dangerous under fatigue.
```

## Assigned realistic task

# Review an API repair after transport loss

**Task ID:** `ux-task-20`

## Situation

An API image repair was initiated during unstable client connectivity and has been handed to the on-call operator for status review.

## Supplied task

Determine the current disposition of the API image change and report the evidence supporting it.

The equivalent direct-runtime materials are `control.json`, `candidate.patch`,
the synthetic repository named by the control, and the Docket/GWR operator
documents under `docs/`. The supplied packet description is `task/packet.json`.
No Maude plan, playbook, ration card, or approval witness is part of this
comparison surface.

Use only the supplied Docket/GWR public CLI. Do not edit the repository
directly, widen the admitted paths, bypass a refusal, use a live endpoint, or
perform an external side effect.

## Review condition

Base the final disposition on the operator-visible packet, runtime state, exact effects, and test evidence.

The raw transcript and observable artifacts do not exist at freeze time. The
campaign runner must render them into the frozen grader request template after
the operator session. It must not supply `expected-disposition.json`,
implementation source, prior runs, or evaluator commentary.
