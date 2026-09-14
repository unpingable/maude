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
programs and their closed configurations explicitly. It must retain owner
acquisition/result/reconciliation records, use distinct qualification and
successor occurrence identities, and plan bounded exact-project teardown.
Synthetic Standing must remain labeled as a fixture and does not qualify a
deployment Standing service. A plan lock, compilation, result, or successor
observation grants no authority and does not imply current cache health.

This is development-stage component glue. Public-only end-to-end qualification
and release-profile integration remain separate evidence.
