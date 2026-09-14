# Reviewed local-copy interface

`maude.reviewed-local-copy/v1` is a deliberately narrow compiler and
read-only validation interface. It describes exactly one executor operation:
copy at most 64 KiB of already selected reviewed text to `result.txt` within
an executor-owned exclusive scratch directory. It does not run that operation,
accept a review, grant authority, or select a scratch directory.

The compiler accepts closed versioned input and emits the existing
`nightshift.precompiled_workflow_proposal.v2` handoff shape plus an executor
plan. Its work identity uses the existing domain-separated AG executor-plan
identity law. The plan binds the campaign, occurrence, subject/scope,
PlanDocument/compiler coordinates, exact UTF-8 text, and scratch root; it has
no command field or alternate destination. The outer `maude.governed-plan-binding/v1` carries exact
bytes for the PlanDocument, lock, compiler inputs, handoff, compilation receipt,
and executor plan. Its identity excludes only `binding_id`; it does not include
later review results.

Validation opens the configured existing Plan Core SQLite store in read-only
mode. It requires the stored current revision, lock, applicable passing Plan
Core checks, compilation evidence, and an exact deterministic recompilation to
agree with the supplied binding. A lock by itself is insufficient. V1 Plan Core
records remain readable with their existing meaning.

This is a component interface, not an AG, Nightshift, Docket, provider, or
executor integration claim.

## Local Docket adapter

`maude.plan.reviewed_local_copy_executor` is the component-only executor for
the same sealed plan. It implements Docket's untagged
`docket.governed-executor-transport/v1` process operations: `plan-id`,
`execute`, and `reconcile`. Its executor-owned config carries canonical sealed
plan bytes and an isolated state directory. It accepts only the matching work,
subject, and scope bindings. At the effect boundary it creates `result.txt`
exclusively: any existing destination pathname causes refusal without opening
or overwriting that destination. It records a durable attempt before this
exclusive creation. Terminal replay returns the same outcome. A reserved but
unproven attempt reconciles as indeterminate and never repeats the copy.

This adapter has component tests only. It does not establish Docket custody,
AG authorization, a qualified runtime deployment, or a completed cross-system
integration.

## Closed component packages

`tools/build_reviewed_local_copy_validator.py` exports a deterministic Python
zipapp from a clean, pinned source revision. The default role remains the
validate-only package; callers that need the component executor must select
`--role executor` explicitly. Both package manifests record the source
revision, exact archive entries and digests, the fixed `/usr/bin/python3.12`
interpreter digest, and the deployment-trusted standard-library boundary.

The current builder is Linux/distribution-specific: it requires Git, the fixed
`/usr/bin/python3.12` interpreter, the distro PyYAML Python sources at
`/usr/lib/python3/dist-packages/yaml`, and their license notice at
`/usr/share/doc/python3-yaml/copyright`. Installing PyYAML only in a virtual
environment does not supply those paths. The component packages were reproduced
on Ubuntu 24.04 with Python 3.12.3 (`python3.12` package
`3.12.3-1ubuntu0.17`) and `python3-yaml` `6.0.1-2build2`. Provision the public
distribution packages `git`, `python3.12`, and `python3-yaml` before building;
another interpreter or dependency build changes the recorded hashes and is
not the same qualified artifact. Other distributions are not verified here.

Use a clean public checkout at an explicitly selected full commit ID. Create
the output parent directory first and keep it outside the checkout; both output
and manifest filenames must be absent. Record the emitted manifest alongside
each archive. No private repository, provider credential, or running service
is required to build these component packages.

```sh
REVISION=$(git rev-parse HEAD)
/usr/bin/python3.12 tools/build_reviewed_local_copy_validator.py \
  --output /absolute/path/reviewed-local-copy-validator.pyz \
  --manifest /absolute/path/reviewed-local-copy-validator.json \
  --source-revision "$REVISION"
/usr/bin/python3.12 tools/build_reviewed_local_copy_validator.py --role executor \
  --output /absolute/path/reviewed-local-copy-executor.pyz \
  --manifest /absolute/path/reviewed-local-copy-executor.json \
  --source-revision "$REVISION"
```

The validator zipapp accepts only `validate --config CONFIG --binding BINDING`;
it cannot compile or execute. The executor zipapp accepts only `plan-id CONFIG`,
`execute CONFIG` with one dispatch document on standard input, and `reconcile
CONFIG` with that same dispatch form. Its `execute` and `reconcile` operations
remain component-level behavior: exporting or testing them does not establish a
Docket transport qualification, an AG authorization, or a public release.
