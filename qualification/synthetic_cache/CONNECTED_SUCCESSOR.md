# Connected-cache successor: public prerequisites

This is a public, development-stage prerequisite guide for the connected
synthetic-cache tutorial. It describes how a caller can prepare a closed local
input set. It does not establish an end-to-end qualification, authority,
current cache health, a production Standing service, or permission to run the
workload.

The preparation helpers are public code in this directory:

- `public-nq-host-bootstrap.py` writes one fresh NQ host-watcher configuration.
- `prepare_pulse_support.py` creates fresh Pulse support credentials, config,
  and a sealed resolver launcher after it is given an exact NQ artifact and
  Nightshift posture request.
- `public-governance-bootstrap.py`,
  `generate_connected_cache_setup_config.py`, and
  `prepare_connected_cache_run.py` close and pin the caller's input boundary.
- `run_connected_cache.py` is the intended driver, but remains under separate
  public qualification. Its presence is not a claim that it is ready to run.

No helper discovers credentials, accepts an implicit identity, or reads a
campaign-owned record.

## Public source pins

Obtain sources only from the corresponding published component repository and
record the checked-out commit plus the executable and configuration digests in
the caller's preparation record. This tutorial's component compatibility set
is:

| Component | Public repository and source revision | Required surface |
| --- | --- | --- |
| NQ CLI | `https://github.com/unpingable/constellation-nq.git` at `d3089a9787a27c50faf1e3f393a88f8e64bd412d` | native `nq` and its compiled profile descriptors |
| NQ helpers | `https://github.com/unpingable/constellation-nq.git` at `ce0a04a175b6d87ac17395f08fd7bc70ddf1e7b3` | native `nq-host-helper` and `nq-synthetic-cache-result-helper` used by the tested mixed cohort |
| Nightshift | `https://github.com/unpingable/constellation-nightshift.git` at `2db475b0bb8be5e3afa7ac6c95e2ab1f73a9ceb4` | cycle, external-observation, and resolver CLI surfaces |
| AG | `https://github.com/unpingable/constellation-ag.git` at `5c8b22b77193798f25298b02758ac3caa3a8fe24` | governed-loop catalog, runtime-profile seal/verify, and standing resolver |
| Docket | `https://github.com/unpingable/constellation-docket.git` at `c49ad8d0f26fb2a13b9dbafdde84d7abfe1f867b` | exact executor custody, attempt, reconciliation, and inspection surfaces |
| Pulse support integration | `https://github.com/unpingable/constellation-nightshift.git` at `d91b214cd22afd5585fcd259d22463d08d606b58`, subtree `integrations/pulse-nq-load-support` | `LoadSupportConfigV1` and `seal-pulse-support-resolver-launcher.py` |

The older source-history NQ pin is intentional. It is the compatible source
for this tutorial's NQ104-era host profile, not a claim about a current NQ
release. Do not substitute a later component because its executable name or a
JSON field happens to match.

## Local toolchain and installation boundary

Use Python 3.11 or later. Create the Maude environment with copies, rather
than symlinks, because the Pulse support reader admits only a regular,
non-symlink Python interpreter path:

```bash
python3 -m venv --copies /absolute/path/to/maude-venv
/absolute/path/to/maude-venv/bin/python -m pip install -e /absolute/path/to/pinned-maude
```

Install Maude's core dependency set. Do not install or invoke the transitional
`classic-rpc` extra for this path; it is not AG-NG compatibility. Pin the
actual selected `python`, `openssl`, NQ, Pulse, Nightshift, AG, Docket, helper,
and resolver bytes before preparation. All caller-provided paths must be
absolute, regular files where a reader requires it, and inputs with a supplied
digest must match their digest before the fresh output root is allocated.

The locally qualified mixed cohort used `nq` and `nq-host-helper` with the
documented compatible NQ host profile, and used the separately pinned result
helper above. That qualification is evidence for those exact bytes; it is not
a general same-build compatibility claim. A future public-only reproduction
may instead build `nq`, `nq-host-helper`, and
`nq-synthetic-cache-result-helper` together from the NQ `d3089a9` source pin,
but must first verify the resulting profile identities and helper admission
rather than assuming source proximity preserves them. The public NQ host
configuration derives the profile descriptor from the selected NQ binary
(`nq --json profiles list`), then binds the resulting `nq.host/v1` digest into
the host scope. Do not paste a profile semantic/digest from an unrelated build:
the NQ104 profile namespace is a build-semantic input. Pulse prepares support
only for the exact supported NQ host/load-pressure identities defined by its
pinned integration.

The NQ watcher must name both a concrete `execution_account` and a concrete
host watcher binding (`instance_id`, `subject`, and scope ID). Debug use of an
execution account resolving to the caller's own identity requires the explicit
`--allow-same-identity-in-debug` option. That option is a local debug
exception; it neither changes the account binding nor qualifies a deployment
configuration.

## Prepare, inspect, then stop

Choose a fresh, caller-owned absolute root and all occurrence, acquisition,
runtime, role, and schedule identities before generating setup input. The
configuration generator computes the NQ host scope digest from the selected
NQ profile and writes a create-only setup configuration. The preparation
helper then makes only the following fresh local artifacts:

```text
<root>/
  credentials/                 fresh Maude session and producer key files
  governance/                  catalog, enrolled/sealed AG profile, resolver wrappers
  nq/                          generated NQ watcher config and uninitialized state path
  runtime/                     declared future project workspace; no containers yet
  records/                     reserved for driver terminal/recovery records
  context.json                 closed byte-pinned preparation context
```

`prepare_pulse_support.py` is deliberately later in the ordering: it needs the
actual, admitted NQ diagnostic artifact and the exact posture-only Nightshift
request. It writes a separate fresh root containing `producer.hex`, Pulse
configuration, outgoing/receipt directories, sealed resolver launcher,
enrollment, and `preparation.json`. It creates neither a measurement nor a
receipt, and it grants no runtime permission.

Inspect each preparation output and retain its exact bytes and hashes. A
partial root after a helper refusal is evidence to inspect, not a directory to
reuse or overwrite. Start again only with a fresh root after identifying the
retained terminal/refusal state. In particular, never rerun an uncertain NQ
acquisition, AG/Docket settlement, or teardown merely to obtain a later
timestamp; use that component's retained inspection/reconciliation interface.

## Intended stage order

The closed context fixes the intended order:

```text
NQ genesis and watcher admission
  -> initial NQ artifact custody in Pulse and Nightshift
  -> AG/Docket settlement of the qualification occurrence
  -> exact external-result reconciliation
  -> one fresh NQ local-successor acquisition in the same watcher/store/config
  -> exact observation-family comparison
  -> successor Pulse/Nightshift custody and separate AG/Docket settlement
  -> bounded exact-project teardown and owner readback
```

The successor must use its explicit, fresh local acquisition ID and must not
repeat genesis initialization or the genesis-only diagnostic request. The
qualification and successor have distinct occurrence, schedule, attempt, and
Pulse acquisition identities. The driver must retain initial and successor
artifacts, custody records, AG decisions/issuances, Docket attempts and
settlements, inspection/reconciliation outputs, and teardown inventory. A
failure, pending state, unknown state, or incomplete readback is a fail-closed
result, not permission to continue.

Synthetic Standing remains exactly that: a local fixture used to exercise the
published interfaces. It does not stand in for a deployment Standing service,
does not create authority outside the fixture, and does not imply a current
external observation.

## Invocation status

The commands below are accurate preparation interfaces, not an authorization
to execute the journey:

```bash
PYTHON=/absolute/path/to/maude-venv/bin/python
MAUDE=/absolute/path/to/pinned-maude

"$PYTHON" "$MAUDE/qualification/synthetic_cache/generate_connected_cache_setup_config.py" --help
"$PYTHON" "$MAUDE/qualification/synthetic_cache/prepare_connected_cache_run.py" --help
"$PYTHON" "$MAUDE/qualification/synthetic_cache/prepare_pulse_support.py" --help
"$PYTHON" "$MAUDE/qualification/synthetic_cache/run_connected_cache.py" --help
```

The final command currently exposes `--context` and `--execute`; do not invoke
it with `--execute` until its separate public qualification records an admitted
result and the operator has established the required local authority, resource,
and durable recovery boundary. No native build, provider action, container
launch, cache acquisition, public publication, or push is performed by this
guide.
