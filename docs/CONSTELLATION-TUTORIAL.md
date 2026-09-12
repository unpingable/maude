# Constellation synthetic-cache tutorial baseline

This document describes the current connected qualification truthfully. It is
not yet a newcomer-runner and does not claim that a local Phosphor design demo
is a live governed stack.

## What already connects

The checked-in synthetic-cache source has a bounded, credential-free local
workload. `qualification/synthetic_cache/build_plan.py` creates a Plan Core
document, records a deterministic repair proposal and explicit acceptance,
checks and locks the result, then emits exact local-Compose qualify and
teardown handoffs. `build_requalification.py` creates the C2 successor through
ordinary typed operations and revision CAS.

Nightshift's ignored
`crates/nightshiftd/tests/ag_governed_integration.rs::synthetic_cache_design_qualifies_and_tears_down_through_governed_runtime`
consumes those artifacts. With exact adjacent binaries it exercises this
connected path:

```text
Maude Plan Core + exact compiler
  -> authenticated Maude/Nightshift custody
  -> Nightshift currentness and lineage
  -> Constellation AG decision and one-use authority
  -> Docket custody + closed local-Compose executor
  -> settled qualification evidence
  -> fresh observation and separately authorized teardown
  -> read-only Maude/Phosphor projection
```

The local workload is intentionally a substitution fixture. It uses a
deterministic NQ admission port, a test standing issuer, and a controlled
Docket execution-standing resolver. Those fixtures demonstrate their boundary
contracts; they are not an installation of NQ-NG or a production standing
service. The container workload itself is a four-container synthetic HTTP/cache
platform. No model-provider credential is used.

## Read-only preflight

Before any producer, use the checked-in preflight with absolute paths. It
reads source, artifacts, binary metadata and Docker's local state only. It
does not create the supplied workspace, pull an image, start a container,
install a package, or contact a network endpoint.

```bash
cd /path/to/maude
python3 scripts/check-constellation-tutorial.py \
  --maude-checkout "$PWD" \
  --nightshift-checkout /path/to/nightshift \
  --ag-checkout /path/to/ag-ng \
  --docket-checkout /path/to/docket/runtime \
  --artifact-root /path/to/generated-synthetic-cache-artifacts \
  --workspace-root /tmp/constellation-synthetic-cache-runtime \
  --ag-loopctl /path/to/ag-ng/target/debug/ag-loopctl \
  --ag-standing-resolver /path/to/ag-ng/target/debug/ag-standing-resolver \
  --ag-effectd /path/to/ag-ng/target/debug/ag-effectd \
  --docket-bin /path/to/docket/runtime/target/debug/docket \
  --executor "$PWD/qualification/synthetic_cache/local_compose_executor.py" \
  --docker-program /usr/bin/docker
```

Pass `--*-revision <full commit>` in a tutorial lock manifest once compatible
public revisions are selected. Without those flags the preflight reports each
observed revision but treats it as unpinned. The artifact root must contain the
C1 and C2 locked plans, handoffs, executor plans, and compilation receipts
emitted by the two existing builder scripts. The preflight names every required
file and refuses missing or malformed inputs.

The existing source-only qualification check is safe to run without Docker:

```bash
cd /path/to/maude
.venv/bin/pytest -q tests/test_plan_core.py tests/test_local_compose_workflow.py tests/test_plan_design.py
scripts/check-synthetic-cache-boundaries.sh
```

The 2026-09-12 baseline recorded 63 passing selected Plan Core/design/local-
Compose tests after the optional classic RPC client import became lazy. This
checks authoring and closed compilation behavior; it does not launch Docker or
the governed chain.

## Generator procedure and current setup gap

The checked-in generators are `build_plan.py` for C1 and
`build_requalification.py` for C2. The companion
`qualification/synthetic_cache/constellation-tutorial-input-lock.json` records
the test-compatible campaign, program, subject, scope, occurrence, observation,
runtime-version, and C1/C2 environment-file mapping. The new
`scripts/run-constellation-tutorial.py` packages their procedure and invokes
the existing ignored Nightshift target; it adds no authority semantics.

Its default is a read-only plan plus preflight. `--run` is required before it
creates one absent `/tmp` root, generates the C1/C2 artifacts, and starts the
existing test. The test keeps teardown inside its governed sequence; the driver
does no broad cleanup and refuses an existing root.

```bash
python3 scripts/run-constellation-tutorial.py \
  --run-root /tmp/constellation-synthetic-cache-001 \
  --maude-checkout "$PWD" --nightshift-checkout /path/to/nightshift \
  --ag-checkout /path/to/ag-ng --docket-checkout /path/to/docket/runtime \
  --ag-loopctl /path/to/ag-loopctl --ag-standing-resolver /path/to/ag-standing-resolver \
  --ag-effectd /path/to/ag-effectd --docket-bin /path/to/docket \
  --docker-program /usr/bin/docker --maude-python /path/to/maude/.venv/bin/python \
  --input-lock qualification/synthetic_cache/constellation-tutorial-input-lock.json
```

The checked-in lock pins the official `linux/amd64`
`python:3.13-alpine` registry manifest as
`sha256:46ee549c88617e9bc8acb843a326f1a5c0fa5608d7f9703509efe6d53b55f318`.
It is not present locally and has not been used for this tutorial occurrence.
The pinned current registry artifact must not be described as the image used by
an older qualification record. Image pull and storage admission remain a
separate governed runtime action.

The remaining distribution work is to publish a reviewed image pin and lock
the compatible adjacent source/binary revisions. It must retain existing owner
boundaries rather than turn Maude, Phosphor, or a browser screen into an
authorization or execution path.

In the ordinary sandboxed shell, Docker daemon queries are denied. A scoped
read-only host check confirms the daemon is available, its root is
`/var/lib/docker` (a different filesystem from `/data`), and the
`python:3.13-alpine` tag is absent. This is an execution-permission boundary
plus an image-distribution gap, not evidence that the host lacks Docker. Any
later container occurrence needs the campaign storage/reserve gate before
allocation.

The historical commands that open `127.0.0.1:8427/phosphor/design` read retained
local corpus files. They are useful design/inspection specimens, but are not
evidence that this tutorial has launched a live Maude → Nightshift → AG →
Docket chain.

## Existing full-chain test interface

Once the missing tutorial kit supplies an exact compatible tuple and a fresh
root, the existing Nightshift test is the supported integration target:

```bash
AG_LOOPCTL_BIN=/absolute/path/ag-loopctl \
AG_STANDING_RESOLVER_BIN=/absolute/path/ag-standing-resolver \
AG_DOCKET_BIN=/absolute/path/docket \
AG_EFFECTD_BIN=/absolute/path/ag-effectd \
cargo test -p nightshiftd --test ag_governed_integration -- --include-ignored
```

That command alone is intentionally incomplete: the test also requires the
exact `SYNTHETIC_CACHE_*` artifact and fresh-root coordinates documented in its
source. The preflight is the authoritative list of the corresponding C1/C2
artifact and binary inputs; it does not manufacture them.
