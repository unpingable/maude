# Connected-cache example operations

This page covers the public connected-cache development example. It does not
turn the example driver into a service, durable auto-resumer, production
Standing implementation, or source of authority. The driver performs two
occurrences: qualification first, then a local-successor occurrence whose
separately authorized action is teardown. Its authoring and Standing inputs are
synthetic fixtures.

Start with [CONNECTED_SUCCESSOR.md](CONNECTED_SUCCESSOR.md) and keep its exact
source, program, image, profile, and configuration pins. An accepted bundle is
a caller-supplied, byte-pinned input: the driver checks its bytes and locked-plan
continuity, but does not authenticate that a person accepted it.

## Owners and retained state

Choose one caller-owned absolute `ROOT`. Its `context.json` indexes disjoint
owners:

| Owner | Context coordinates and retained material |
| --- | --- |
| caller | `root`, `files`, `programs`, `identities`, and `runtime`; retain the context, setup/profile inputs, install manifest, exact source revision, and source-closure hashes |
| credential custodian | `credentials`; retain the three locator paths and keep key bytes out of logs and issue reports |
| NQ | `files.nq_config`, its declared state path, and the later `ROOT/result` configuration; retain databases, sidecars, admissions, exact artifacts, and provenance |
| Nightshift | `state.state_paths.nightshift_store`; retain cycles, observations, authoring context, and custody |
| AG | `state.state_paths.ag_database`, `files.ag_profile`, and `files.ag_enrollment`; retain history, decisions, issuance, refusals, and sealed profile |
| Docket | `state.state_paths.docket_directory`; retain issuance custody, attempts, settlement, reconciliation, and executor-evidence references |
| Maude | `state.state_paths.maude_store`; retain authored plan/session custody and exact compiler outputs |
| tutorial fixture | `state.state_paths.mandate_store`; this synthetic Standing input remains a fixture |
| driver | `ROOT/records/connected-run`; retain checkpoint, source pins, numbered stage records, owner exports, and terminal record |

The Docker project in `runtime.project` is state outside those databases. The
profile requires the exact project name documented in `CONNECTED_SUCCESSOR.md`;
never aim inspection or cleanup at another project.

Credential locators are configuration, but credential contents are not. Do not
paste keys, environment dumps, database rows, complete non-public paths, or
unredacted stderr into an issue. Report public revisions and hashes, schema
labels, stage name, bounded error classification, and redacted path roles.

## Start once

Preparation must have completed in a fresh root. An external durable manager
must own the whole driver process group; the raw Python driver does not resume
after manager loss. For a local user-systemd manager, choose a unique label:

```bash
ROOT=/absolute/fresh/run-root
MAUDE=/absolute/clean/pinned-maude
PYTHON=/absolute/copied-venv/bin/python
LABEL=connected-cache-example-unique-label

systemd-run --user --unit="$LABEL" --collect \
  --property=Type=oneshot \
  --property=TimeoutStartSec=2400 \
  --property=TimeoutStopSec=10 \
  --property=KillMode=control-group \
  --property=MemoryMax=2G \
  --property=TasksMax=256 \
  --property=Restart=no \
  "$PYTHON" "$MAUDE/qualification/synthetic_cache/run_connected_cache.py" \
  --context "$ROOT/context.json" --execute
```

Record the manager invocation ID and context hash. This is the manager envelope
used by the qualified local example, not a general deployment sizing rule.
Filesystem allocation and host reserve remain operator responsibilities.
Accepted mode adds all four accepted-bundle/store path and SHA-256 arguments
shown by `--help`; supplying them asserts a caller-owned reference and does not
create or prove acceptance.

The driver refuses pre-existing records or owner state and never retries a
stage. Its recovery entry point is
`records/connected-run/checkpoint.json`. Success requires terminal `exit_code: 0`,
phase `verified_local_composition`, and final exact-project absence. That is a
terminal example result, not current cache health or authority.

## Inspect without resubmission

Inspect the manager and stage records first. A missing terminal, an
`*.uncertain.json`, a started stage without a matching finish, or a nonzero
terminal is unresolved until its owner is read.

```bash
systemctl --user show "$LABEL.service" \
  --property=ActiveState,SubState,Result,ExecMainCode,ExecMainStatus,InvocationID
find "$ROOT/records/connected-run" -maxdepth 1 -type f \
  \( -name 'checkpoint.json' -o -name 'terminal.json' \
     -o -name '*.started.json' -o -name '*.finished.json' \
     -o -name '*.uncertain.json' \) -print | sort
```

Resolve programs and stores from the retained context; do not substitute a
same-named executable:

```bash
eval "$("$PYTHON" - "$ROOT/context.json" <<'PY'
import json, shlex, sys
c = json.load(open(sys.argv[1], encoding='utf-8'))
values = {
    'NQ': c['programs']['nq']['path'],
    'NQ_CONFIG': c['files']['nq_config']['path'],
    'NIGHTSHIFT': c['programs']['nightshift']['path'],
    'NS_STORE': c['state']['state_paths']['nightshift_store'],
    'AG': c['programs']['ag']['path'],
    'AG_DB': c['state']['state_paths']['ag_database'],
    'DOCKET': c['programs']['docket']['path'],
    'DOCKET_STATE': c['state']['state_paths']['docket_directory'],
}
for name, value in values.items():
    print(f'{name}={shlex.quote(value)}')
PY
)"
```

These owner queries are read-only. Their identifiers come from retained
records; they create no acquisition, evaluation, decision, issuance, attempt,
or teardown:

```bash
ARTIFACT_Q=$("$PYTHON" -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["artifact_id"])' \
  "$ROOT/records/connected-run/diagnostic-q.json")
ARTIFACT_T=$("$PYTHON" -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["artifact_id"])' \
  "$ROOT/records/connected-run/diagnostic-t.json")
"$NQ" --config "$NQ_CONFIG" diagnostics inspect "$ARTIFACT_Q"
"$NQ" --config "$NQ_CONFIG" diagnostics inspect "$ARTIFACT_T"
"$NIGHTSHIFT" --store "$NS_STORE" cycle list
"$AG" inspect --database "$AG_DB"

ISSUANCE_Q=$("$PYTHON" -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["record"]["issuance"]["issuance"])' \
  "$ROOT/records/connected-run/docket-q.json")
ISSUANCE_T=$("$PYTHON" -c \
  'import json,sys; print(json.load(open(sys.argv[1]))["record"]["issuance"]["issuance"])' \
  "$ROOT/records/connected-run/docket-t.json")
"$DOCKET" governed-loop inspect --state "$DOCKET_STATE" --issuance "$ISSUANCE_Q"
"$DOCKET" governed-loop inspect --state "$DOCKET_STATE" --issuance "$ISSUANCE_T"
```

If result admission was reached, inspect its separate NQ owner:

```bash
RESULT_ID=$("$PYTHON" - "$ROOT/records/connected-run" <<'PY'
import json, os, pathlib, stat, sys
records = pathlib.Path(sys.argv[1])
matches = list(records.glob('[0-9][0-9][0-9]-result-diagnostic.stdout'))
if len(matches) != 1:
    raise SystemExit('expected exactly one retained result-diagnostic output')
metadata = os.lstat(matches[0])
if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 16 * 1024 * 1024:
    raise SystemExit('result-diagnostic output is not one bounded regular file')
with matches[0].open('rb') as stream:
    result = json.load(stream)
print(result['artifact_id'])
PY
)
"$NQ" --config "$ROOT/result/nq.toml" diagnostics inspect "$RESULT_ID"
```

Absence of a later record does not settle an earlier attempt. Inspect the last
started stage and its NQ, AG, or Docket owner. Do not substitute a fresh
acquisition, occurrence, or repeated teardown for that readback. Docker
`ps -a` and `network ls`, filtered by the exact Compose project label, are
inspection only; a clean result supports exact-project absence, not absence of
unrelated Docker state.

## Stop, restart, backup, and cleanup

The normal stop is the governed teardown already in the driver. After a success
terminal there is nothing to restart in that root. Reuse intentionally refuses.

If interruption is necessary, stop the manager unit rather than one child:

```bash
systemctl --user stop "$LABEL.service"
```

Process-group termination is not Docket settlement or governed teardown. Treat
the result as uncertain, preserve the root, and inspect the original owners.
Only after every submitted attempt is reconciled and exact project state is
known may an operator choose a fresh root with fresh occurrence and acquisition
identities. There is no supported resume command for the old invocation.

Stop writers and establish quiescence before a filesystem snapshot. An
unchanged SQLite main-file hash establishes only that those main-file bytes did
not change during inspection; it says nothing about the owner's complete state.
A main file copied while its WAL is active is incomplete. Capture the owner's
whole declared state location, sidecars and referenced executor evidence, with
an inventory and hashes. Also retain context, revisions, program hashes,
manager terminal state, and Docker project inspection.

There is no verified cross-owner restore, migration, or rollback procedure for
this example. A byte copy is an unverified backup until compatible owner readers
open and replay it in a disposable environment. NQ archive/rollover applies only
to NQ state; it does not migrate Nightshift, AG, Docket, Maude, credentials, or
Docker state, and it supplies no transparent cross-store lookup.

Cleanup is appropriate only for a disposable root with a terminal manager,
settled attempts, and an absent exact Docker project or completed authorized
teardown. Preserve unresolved roots. Remove only the exact caller-owned root
under its retention policy; no broad cleanup command is provided here.

## Support

This is experimental alpha support, provided on a best-effort basis with no
response-time commitment. Use <https://github.com/unpingable/maude/issues>.
Include environment and toolchain versions, the exact command, expected and
observed result, profile version (or say `unreleased`), public component source
pins and program hashes, schemas, stage name, terminal state, and redacted run
or attempt identifiers when needed for correlation. Include only a minimal
redacted error; keep credentials and non-public owner records private.
