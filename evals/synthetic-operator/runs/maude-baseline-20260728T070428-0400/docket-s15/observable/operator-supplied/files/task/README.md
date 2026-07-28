# Run a bounded worker deployment repair

**Task ID:** `ux-task-15`

## Situation

A worker deployment is still on image 4.2.0, and the service team has handed off a prepared repair packet.

## Supplied task

Use the supplied packet to change the worker image from 4.2.0 to 4.2.1 and report the resulting disposition.

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
