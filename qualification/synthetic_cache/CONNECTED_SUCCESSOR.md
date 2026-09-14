# Portable connected-cache successor preparation

This development helper exposes the accepted-plan compilation boundary without
embedding a campaign checkout, retained record, executable, configuration, or
credential path. It does not run the connected cache journey.

`compile_accepted_cache_actions.py` accepts an explicit Maude source tree and
the SHA-256 of its `src/maude/plan/local_compose.py`, an
immutable accepted Plan Core store and its SHA-256, a small caller-owned
`maude.accepted-cache-plan-bundle/v1`, and one closed action-specific compiler
input plus its SHA-256. The bundle fields are exactly:

```json
{"acceptance_ref":"application-owned opaque reference","draft_id":"draft id","lock_id":"sha256:...","plan_digest":"sha256:...","schema":"maude.accepted-cache-plan-bundle/v1"}
```

Run `qualify` first against a fresh output directory. After qualification has
settled and the retained-result owner has admitted its result, acquire one NQ
local successor through the same admitted watcher/store/config and a fresh
caller-owned acquisition ID. Do not repeat `init`, watcher admission, or the
genesis-only diagnostic request. After the fresh successor observation passes
the exact Nightshift family check, run `teardown` with its distinct explicit
compiler input. Preserve the qualification handoff and receipt bytes; never
recompile them merely to obtain a later timestamp.

Each helper invocation refuses a source store with WAL/SHM sidecars, then uses
SQLite's read-only backup interface to create a
fresh private store copy and records compilation custody only in that copy.
Inputs are bounded, regular, non-symlink files and outputs are create-only.
Pathname pins assume the operator keeps the supplied source and inputs quiescent
for the bounded invocation; they are not authenticated execution provenance.

The surrounding recipe must supply pinned NQ, Pulse, Nightshift, AG and Docket
programs and their closed configurations explicitly. The preparation command
checks every file the caller lists, but does not discover inputs or establish
that the list is complete. The eventual driver must define that closed list. It
must retain owner
acquisition/result/reconciliation records, use distinct qualification and
successor occurrence identities, and plan bounded exact-project teardown.
Synthetic Standing must remain labeled as a fixture and does not qualify a
deployment Standing service. A plan lock, compilation, result, or successor
observation grants no authority and does not imply current cache health.

This is development-stage component glue. Public-only end-to-end qualification
and release-profile integration remain separate evidence.

`prepare_connected_cache_successor.py` seals the complete caller boundary for
the eventual bounded driver. Its closed enrollment requires exact paths and
SHA-256 pins for NQ, Pulse, Nightshift, AG and Docket; the seven narrow public
helpers, including the proposal binder; and the caller-enrolled owner
configuration/input files. Its stage contract fixes the
owner ordering from NQ genesis through initial custody and settlement, external
acquisition, result-owner reconciliation, same-owner NQ local successor, exact
family comparison, successor custody/settlement, bounded teardown and owner
readback. It explicitly forbids a repeated genesis request and labels Standing
as `synthetic_fixture`.

The preparation output is not itself an executor and has `authority: none` and
`effects: false`. Until the exact driver consuming this closed preparation is
published and qualified, do not describe it as a runnable end-to-end recipe.

## Public helper invocation

Run helpers from a pinned Maude checkout with an explicitly selected Python:

```bash
MAUDE=/absolute/path/to/pinned-maude
PYTHON=/absolute/path/to/python3

"$PYTHON" "$MAUDE/qualification/synthetic_cache/helpers/cache-successor-compose-request.py" \
  --posture-request /absolute/run/initial-posture.json \
  --precompiled-proposal /absolute/run/plan/handoff-qualify.json \
  --output /absolute/run/initial-proposed.json

"$PYTHON" "$MAUDE/qualification/synthetic_cache/helpers/verify-cache-observation-family.py" \
  --predecessor /absolute/run/initial-posture.json \
  --successor /absolute/run/successor-posture.json
```

The first command refuses a proposal that does not bind the request's exact
observation, scope, and `maude.local-compose-workflow/v1` schema. The second
checks that the later request retains the exact Nightshift observation family.
It does not acquire the later observation. Use NQ's supported same-watcher,
same-store, same-config local-successor command only after the first settlement
and retained-result qualification; do not repeat genesis initialization or its
state-changing diagnostic request.

Every helper provides `--help`. Callers must use absolute paths and fresh
create-only outputs. `compile_accepted_cache_actions.py` is required only for
accepted mode; fixture mode remains explicitly synthetic. Neither mode supplies
a Standing service. The still-missing public end-to-end driver must create and
pin owner configurations and credentials, invoke the owner CLIs in the declared
stage order, retain terminal/recovery evidence, and perform bounded teardown.
