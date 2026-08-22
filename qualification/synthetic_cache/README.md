# Synthetic local cache governed qualification

This is the first nontrivial disposable workload taken from a mutable
`maude.plan-document/v1` through an exact workflow compiler, authenticated
Maude/Nightshift custody, AG-NG governance, Docket execution, world
observation, settlement, successor authority, teardown, and Phosphor-ng read
inspection.

It proves more than “Docker Compose exited zero.” The executor records actual
HTTP/cache/topology evidence and the governed stores retain two distinct
settled attempts. It proves less than production deployment: the integration
uses the existing test NQ admission port and test standing issuer, and it does
not qualify physical power loss, real service-principal isolation, or an
external-world executor beyond local Docker.

The exact retained result, including failed cuts and nonclaims, is recorded in
[`QUALIFICATION.md`](QUALIFICATION.md).

## Topology and containment

```text
fixed in-container observer
          |
          v
        front  ---- bounded failover ----+
          |                               |
      cache-a                         cache-b
          |                               |
          +------------- origin ----------+
```

All four services use the exact pinned `python:3.13-alpine` image and generated
stdlib-only Python programs. The Compose project is
`maude-cache-birthday`. It has:

- one internal bridge and zero host-published ports;
- non-root UID/GID 65534;
- read-only root filesystems, all capabilities dropped, bounded PIDs/CPU/RAM,
  and no privileged or host-network mode;
- an exact dedicated workspace and exact project-scoped teardown;
- four health checks and an observer executed inside the already-declared
  front container.

Snap Docker on the qualified host refused both ordinary `/tmp` mounts and
`no-new-privileges`; the dedicated workspace is therefore below
`~/snap/docker/common/ag-synthetic-cache` and the other hardening controls are
retained. This is an environmental remainder, not silently reported as full
host isolation.

## Plan lifecycle

`build_plan.py` creates the plan before any container artifact is written. Its
15 stable nodes cover workspace, origin, shared cache implementation, two cache
instances, front door, validation, start, health, MISS/HIT, cache-A loss,
continued service, restoration, acceptance, and teardown.

The initial editable plan deliberately duplicates `pn_stop_a` in
`pn_continued.depends_on`. The ordinary checker emits
`plan.reference.unique`. A bounded deterministic agent proposal returns an
ordinary `update_node` operation scoped to that finding, and explicit
acceptance creates one successor through the normal CAS boundary. A separate
human `update_document` operation creates the final revision. The exact final
check passes and the exact bytes are locked.

The fixtures are not ceremonial. `plan-store.sqlite`, check receipts, proposal
request/proposal/acceptance, semantic diffs, lock receipt, compiler inputs,
compiler receipts, handoff bytes, and executor plans are all normal production
Plan Core artifacts.

## Exact compiler

`maude.local-compose-workflow-input/v1` is explicit and closed. It binds the
action, exact workspace/project, image digest, Docker launcher bytes and
versions, canonical AG identities, and a finite PlanNode/action list.

`maude.local-compose-workflow` version `1` accepts only the 15 supported
structured-work action names. It never interprets node descriptions or plan
prose. The output is byte-identical for the same PlanDocument bytes, compiler
version, and explicit inputs; tests vary CWD, HOME, and PATH. Unknown or
incomplete workflows refuse. There is still no generic operational prose
compiler.

Each `maude.plan-compilation-receipt/v1` binds the lock, input/output digests,
exact Docket executor-plan identity, and exact PlanNode/output identities.
Qualification and teardown intentionally compile identical locked plan bytes
under different explicit inputs into different handoffs and work identities.
Artifact digest is not occurrence identity.

## Closed executor

`local_compose_executor.py` implements the existing Docket executor protocol:

```text
plan-id CONFIG
execute CONFIG
reconcile CONFIG
```

It accepts only exact `qualify` or `teardown` plans. Dispatch supplies no
command vocabulary; work, schema, subject, scope, attempt, and marker must match
the exact plan. It uses no shell and cannot execute arbitrary plan prose.
Reconciliation reads a retained exact attempt result or reports indeterminate;
it never repeats mechanics. Attempt evidence is immutable and exact replay
returns the retained outcome.

Qualification observes:

- all declared containers healthy and zero host port bindings;
- `MISS/cache-a/origin=1`, `MISS/cache-b/origin=2`, then corresponding HITs
  without incrementing the origin counter;
- four distinct requests served by cache B while cache A is stopped;
- both cache identities after restoration.

Teardown queries Docker's exact Compose-project labels after the bounded down
operation and observes no remaining containers or networks. The label
inventory is still required when the workspace is absent; workspace absence
is never treated as evidence of cleanup. Command success alone is not the
acceptance witness.

## Governed journey and cross-probe

The ignored Nightshift integration test consumes precompiled bytes only. For
each action it creates a separate authenticated supervised Maude session and
handoff, then uses the existing canonical path:

```text
Maude session/custody
  -> Nightshift lineage
  -> AG proposal / standing / decision / one-use authorization
  -> Docket custody / exact executor / settlement
```

Qualification settles occurrence `...0000`. A fresh Nightshift observation
opens authority-empty successor `...0001`; it receives its own standing,
spend, issuance, attempt, and settlement for teardown. The execution-standing
fixture is issuance-specific so consumed standing cannot be reused.

`record_results.py` invokes only owner read commands. It joins compilation,
Nightshift, AG history, and Docket inspection on exact plan/work/proposal/
occurrence identities. The resulting `maude.plan-governed-cross-probe/v1`
provides 15 content-bound PlanNode links to exact Phosphor-ng occurrence pages.
No prose, filename, timestamp, or display-order match participates.

The helper then creates an ordinary successor working revision with one future
acceptance criterion. Check, lock, handoff, governed lineage, and cross-probe
remain pinned to the old digest, so `/design` reports exact working/locked/
handoff/governed drift and never rebinds runtime history.

## Reproduce and inspect

The exact command arguments depend on pinned Docker and adjacent-repository
binary identities. `build_plan.py --help` lists every explicit compiler input;
there are no implicit defaults for runtime identity. The focused test is:

```bash
cd /home/jbeck/git/agent_gov_ui/maude
.venv/bin/pytest -q tests/test_local_compose_workflow.py
scripts/check-synthetic-cache-boundaries.sh
```

The governed journey is the ignored test
`synthetic_cache_design_qualifies_and_tears_down_through_governed_runtime` in
Nightshift's `ag_governed_integration` target. It requires the exact artifact
paths emitted by `build_plan.py` plus the four adjacent AG/Docket binaries.

To inspect the retained qualified design corpus from this run:

```bash
cd /home/jbeck/git/agent_gov_ui/maude
PYTHONPATH=src .venv/bin/python -m maude.design.server \
  --store /tmp/ag-synthetic-cache-evidence-v8/plan-store.sqlite \
  --presentation-store /tmp/ag-synthetic-cache-evidence-v8/presentations.sqlite \
  --proposal-store /tmp/ag-synthetic-cache-evidence-v8/proposal-store.sqlite \
  --owner-facts /tmp/ag-synthetic-cache-evidence-v8/owner-facts.json \
  --governed-cross-probe /tmp/ag-synthetic-cache-evidence-v8/governed-cross-probe.json
```

Open `http://127.0.0.1:8427/phosphor/design`.

For Phosphor-ng Inspect, place only the retained `ag.sqlite` in a dedicated
campaign-root directory and pass the Nightshift store and Docket state through
their existing read-only CLI coordinates. Do not point `--campaign-root` at a
mixed directory containing unrelated SQLite files.

## Cleanup

The governed teardown already removes all containers and the project network.
Verify without mutating anything:

```bash
docker ps -a \
  --filter label=com.docker.compose.project=maude-cache-birthday \
  --format '{{.ID}} {{.Names}} {{.Status}}'
```

The retained dedicated workspace contains only generated configuration and
attempt evidence. If deliberate manual cleanup is later desired, first verify
the label query above is empty, then remove only:

```text
/home/jbeck/snap/docker/common/ag-synthetic-cache/maude-cache-birthday
```

Evidence bundles under `/tmp/ag-synthetic-cache-*` are disposable. No source
file, credential, unrelated Docker resource, or repository history is part of
cleanup.
