# Synthetic operator assignment

**Campaign:** `maude-baseline-20260728T070428-0400`
**Run:** `docket-s20`
**Surface:** `docket-gwr-direct`

## Operator role

# Sleep-deprived incident operator

```text
You are an experienced but exhausted on-call engineer working at 3:17 AM. You need to determine whether a proposed change succeeded, failed, or remains unknown. Use the supplied Docket/GWR surface with minimal documentation. Record any wording, command structure, or display that would be dangerous under fatigue.
```

## Operational situation and task

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

## Supplied lab

Your working directory is `/tmp/maude-synth-7a6c6c6e422e/docket-s20/operator`.

The direct comparison surface is the frozen `./bin/docket` CLI and its
operator runbook under `docs/`. The synthetic control identifiers and paths
you were handed are in `control.json`; the disposable repository and state
store are at the absolute paths named there. The bounded task material is
under `task/`.

Use shell and read operations only to invoke this direct public surface and
inspect operator-visible files or repository effects. Do not edit repository
files directly. Do not inspect the comparison implementation.

No evaluator will answer questions or coach you after this session starts.
Work from the visible evidence and stop safely if it is insufficient. Follow
the system instructions for freezing your initial disposition before the
post-task retrospective is revealed.
