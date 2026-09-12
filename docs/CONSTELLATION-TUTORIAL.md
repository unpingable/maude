# Constellation synthetic-cache tutorial

This kit explains and checks the inputs for a governed synthetic-cache run. It
does not claim that the connected run has completed. So far, the checked result
is limited to the Maude plan generators and their source-level boundary tests.
The Nightshift/Constellation AG/Docket runtime test has not been run for this
tutorial, and the locked container image has not been pulled.

## What the example is meant to do

`qualification/synthetic_cache/build_plan.py` creates and locks the first plan
(C1), then emits exact inputs for qualification and teardown.
`build_requalification.py` reopens C1 and creates a changed, separately locked
successor (C2). The ignored Nightshift integration test consumes those files
and is intended to exercise this sequence:

```text
Maude plan and compiler output
  -> Nightshift custody and lineage
  -> Constellation AG decision and one-use authority
  -> Docket execution of a closed local-Compose plan
  -> qualification evidence and a fresh observation
  -> separately authorized teardown
```

The workload is a four-container local HTTP/cache example. It uses no model
provider credential. Its NQ admission port, standing issuer, and Docket
execution-standing resolver are deterministic test substitutions. They check
the serialized boundaries used by this qualification case; they are not NQ-NG
or a production standing service. No public `ag-shell-client` distribution is
assumed or required by this kit.

## Two Maude checkouts are currently required

Do not use one checkout for both roles:

- **Tutorial-kit checkout:** the campaign version containing this document,
  `scripts/run-constellation-tutorial.py` and the required `--docker-endpoint`
  option. The first kit commit, `f1b1150`, predates the source-path and local
  Docker binding repairs; it is not the corrected runner.
- **Frozen runtime-source checkout:** commit
  `145fc6b160a150ad18242b205ed95db422d4b308`. This is the Maude source revision
  recorded in `constellation-tutorial-input-lock.json` and is the source from
  which the locked generators and Python runtime must come.

The same lock requires these adjacent source revisions:

```text
Nightshift       2db475b0bb8be5e3afa7ac6c95e2ab1f73a9ceb4
Constellation AG 5c8b22b77193798f25298b02758ac3caa3a8fe24
Docket           c49ad8d0f26fb2a13b9dbafdde84d7abfe1f867b
```

Use absolute paths throughout. A clean Git checkout at the named revision is
required for each source tree; a dirty or unreadable checkout and a revision
mismatch are blockers. The adjacent executables must
already exist and be executable. This tutorial does not build or download
them.

## Read-only preflight

The preflight reads Git state, source files, existing artifacts, executable
metadata, and Docker state through an explicitly selected local Unix socket.
It does not create a workspace, pull an image, start a container, or install a
package. An inherited remote Docker context cannot select a different endpoint.
The deployment must ensure the local socket belongs to the intended local
daemon; a Unix socket name alone does not prove what lies behind it.

```bash
KIT=/absolute/path/to/maude-tutorial-kit
MAUDE_RUNTIME=/absolute/path/to/maude-at-145fc6b

python3 "$KIT/scripts/check-constellation-tutorial.py" \
  --maude-checkout "$MAUDE_RUNTIME" \
  --maude-revision 145fc6b160a150ad18242b205ed95db422d4b308 \
  --nightshift-checkout /absolute/path/to/nightshift \
  --nightshift-revision 2db475b0bb8be5e3afa7ac6c95e2ab1f73a9ceb4 \
  --ag-checkout /absolute/path/to/ag-ng \
  --ag-revision 5c8b22b77193798f25298b02758ac3caa3a8fe24 \
  --docket-checkout /absolute/path/to/docket/runtime \
  --docket-revision c49ad8d0f26fb2a13b9dbafdde84d7abfe1f867b \
  --artifact-root /absolute/path/to/existing-c1-c2-artifacts \
  --workspace-root /tmp/constellation-synthetic-cache-runtime \
  --ag-loopctl /absolute/path/to/ag-loopctl \
  --ag-standing-resolver /absolute/path/to/ag-standing-resolver \
  --ag-effectd /absolute/path/to/ag-effectd \
  --docket-bin /absolute/path/to/docket \
  --executor "$MAUDE_RUNTIME/qualification/synthetic_cache/local_compose_executor.py" \
  --docker-program /usr/bin/docker \
  --docker-endpoint unix:///var/run/docker.sock \
  --image python:3.13-alpine@sha256:46ee549c88617e9bc8acb843a326f1a5c0fa5608d7f9703509efe6d53b55f318
```

In its default `consume` mode, `--artifact-root` must already contain all C1
and C2 locked plans, handoffs, executor plans, and qualification compilation
receipts. Use `--artifact-mode generate` only to check a proposed absent output
root. A `BLOCK` result means the connected producer's exact inputs are not
ready; it is not a runtime qualification result.
Use the actual local daemon socket for your host, not the example socket by
assumption. All generated-output paths must be absent, including symlinks.

The checked source-only commands are:

```bash
cd "$KIT"
.venv/bin/pytest -q \
  tests/test_plan_core.py \
  tests/test_local_compose_workflow.py \
  tests/test_plan_design.py
```

The initial 2026-09-12 run reported 63 passing tests; the later plain-language
interface checks bring that selected source set to 65. They check plan
authoring, generation, compilation, and local boundary behavior. They do not
launch Docker or the connected governed runtime.

## Runner status

`scripts/run-constellation-tutorial.py` defaults to a read-only plan and needs
`--run` before it creates a fresh root below `/tmp`, generates C1 and C2, and
invokes the exact ignored Nightshift test. The runner now reads preflight code
from its own kit directory and generator/runtime code from the separately pinned
Maude checkout. Do not use the latest runtime source with an older revision in
the lock. Preflight compares each checkout's `git rev-parse HEAD` with the
corresponding revision in the input lock and refuses mismatches or dirty source
trees. Run the command without `--run` first and resolve every blocking result.
A plan-only invocation is not a successful runtime run.

The runner requires the same checkout and executable paths as preflight, plus
`--run-root`, `--maude-python`, and `--input-lock`. It does not take the preflight
artifact/workspace/revision arguments; it derives those from the run root and
lock. The Python executable must have the frozen Maude runtime's dependencies.
Run `python3 "$KIT/scripts/run-constellation-tutorial.py" --help` for the full
argument list. Retain the printed run coordinates and local Docker endpoint in
your execution checkpoint before a durable `--run` launch. This is a local text
file for the next operator: record the run ID, host, exact command, checkout
revisions, run root, Docker endpoint, supervising service name, log paths and
expected exit/terminal records. After interruption, inspect those original
records and the existing service before starting anything again. Do not store
provider credentials in the checkpoint.

It selects only this test, rather than every ignored test:

```text
cargo test -p nightshiftd --test ag_governed_integration \
  synthetic_cache_design_qualifies_and_tears_down_through_governed_runtime \
  -- --ignored
```

The runner supplies the required `SYNTHETIC_CACHE_*`, `AG_*`, `MAUDE_SRC`, and
`MAUDE_PYTHON` environment coordinates. Running the Cargo command by itself is
incomplete unless those exact coordinates are also supplied. Do not use
`--include-ignored`; that broader form can select unrelated ignored cases.

## Container prerequisite

The lock names this `linux/amd64` image:

```text
python:3.13-alpine@sha256:46ee549c88617e9bc8acb843a326f1a5c0fa5608d7f9703509efe6d53b55f318
```

That image was not present locally and was not pulled for this tutorial. The
lock also checks the Docker program digest, Docker client/server versions, and
Compose version. Pulling the image and admitting its storage are separate
runtime actions, subject to the campaign storage/reserve gate. A sandbox may
also be unable to query the Docker daemon even when Docker is installed.

## What to inspect after a future successful run

For a run root such as `/tmp/constellation-synthetic-cache-001`:

- `artifacts/` contains the C1 and C2 locked plans, executor plans, handoffs,
  compiler inputs, and compilation receipts.
- `governed/nightshift.sqlite` records Nightshift cycles and custody.
- `governed/ag.sqlite` records Constellation AG transitions and one-use spends.
- `governed/qualify-governed-cross-probe.json` binds Plan nodes to exact
  governed records.
- `governed/external-observation-qualify.json`,
  `external-composition.json`, and `synthetic-stale-resolution.json` show the
  post-qualification observation, its successor composition, and the expected
  stale result at the freshness boundary.
- Each executor plan names its runtime workspace. That workspace's
  `evidence/attempts/` directory contains the local-Compose attempt evidence.

Inspect JSON without changing it, for example:

```bash
python3 -m json.tool \
  /tmp/constellation-synthetic-cache-001/artifacts/plan-locked.json
python3 -m json.tool \
  /tmp/constellation-synthetic-cache-001/governed/qualify-governed-cross-probe.json
```

The integration test is designed to keep teardown within the governed
sequence. A future passing run would still need its terminal records reviewed
before anyone claims the connected demo qualified. Historical Phosphor pages
under `127.0.0.1:8427` display retained corpus files; opening them is not proof
that this tutorial launched a live chain.

## Unresolved prerequisites

The connected tutorial remains blocked until all of these are true:

1. Exact compatible AG and Docket executables exist for the revisions in the
   lock, along with Nightshift and the frozen Maude Python environment.
2. The pinned container image is locally available after explicit image and
   storage admission.
3. The explicitly selected local Docker socket is available to the runtime.
4. A fresh exclusive run root below `/tmp` is selected.

Preflight checks are point-in-time checks. Keep the source trees, executable
paths and runtime coordinates under exclusive campaign control through the run;
the script does not establish protection against concurrent pathname replacement.
For example, do not let another process replace a checked executable or modify
the source checkout or input lock while the run is in progress.

Until then, the accurate result is: generators and source boundaries checked;
full connected runtime not run; container image not pulled.
