# Synthetic operator assignment

**Campaign:** `maude-baseline-20260728T070428-0400`
**Run:** `docket-s11`
**Surface:** `docket-gwr-direct`

## Operator role

# Skeptical first-time user

```text
You are evaluating the supplied Docket/GWR surface for possible adoption by an operations team. Complete the supplied task without prior exposure to the constellation. Identify every concept the interface requires you to understand before it becomes useful, and distinguish necessary operational complexity from architecture leaking into the UX.
```

## Operational situation and task

# Review a one-file menu image packet

**Task ID:** `ux-task-11`

## Situation

Store 17 needs a routine menu API patch, and the application team has handed off a prepared maintenance packet.

## Supplied task

Update apps/menu/deployment.yaml from menu-api:2.7.3 to menu-api:2.7.4.

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

Your working directory is `/tmp/maude-synth-7a6c6c6e422e/docket-s11/operator`.

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
