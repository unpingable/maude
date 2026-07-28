# Synthetic operator harness

This directory is evaluation infrastructure. It does not change Maude product
behavior and it does not provide governance authority.

The harness places the real Maude command parser, handlers, renderers, and
`GovernorClient` in front of a deterministic synthetic Agent Governor
Unix-socket service. It is intended only for fake repositories and frozen UX
campaign inputs.

## Components

- `synthetic_runtime.py` serves Content-Length framed JSON-RPC from a frozen
  scenario configuration. It persists runtime state, records exact request and
  response bodies, materializes configured worker-result bytes before
  promotion review, retains them when the operator keeps them, and restores
  configured base bytes when the operator discards them.
- `maude_driver.py` keeps one real `MaudeApp` alive in Textual's headless test
  driver. It submits input through the real `Input` widget and records logical
  `RichLog` output plus a full SVG screen after every action.
- `public_cli.py` is the thin Unix-socket client exposed to a synthetic
  operator. It cannot see the evaluator-private driver queue.
- `public_cli_broker.py` is the trusted boundary between that public socket
  and the private driver queue. It validates and correlates one bounded public
  request at a time and receives neither provider credentials nor model
  prompts.
- `maude` is the executable operator entry point.
- `freeze_campaign.py` renders every exact initial prompt and supplied-input
  manifest, records preflight facts, hashes all frozen inputs, and writes the
  immutable campaign manifest. A second `--write` is refused.
- `campaign_runner.py` materializes isolated labs, starts the synthetic runtime
  and persistent Maude driver, launches the exact provider assigned to each
  fresh operator and grader session, captures raw evidence, and verifies
  coverage and hashes.
- `grader_surface_probe.py` performs the non-campaign, pre-freeze
  provider/schema capability probes for both grading surfaces.
- `finalize_provider_assignments.py` derives the run matrix mechanically from
  the frozen capability evidence. It balances eligible providers, prefers an
  opposite-family grader, and mirrors each direct-runtime comparator's paired
  Maude assignment.
- `provider_assignment_selftest.py` exercises that derivation and its
  fail-closed evidence checks without starting a provider process.
- `claude_mcp_bridge.py` retains its historical filename but is the fixed
  provider-neutral MCP stdio shim. It exposes exactly one role-specific tool,
  preserves protocol and command correlations, and has no path that reads
  provider authentication.
- `operator_pty.py` is the neutral installation-track PTY adapter. Installation
  runs place its persistent broker in a separate no-network Bubblewrap
  namespace; model terminal actions still reach it only through disposable
  per-command namespaces.
- `campaign_common.py` contains the fixed campaign identity and shared
  validation helpers.

## Freeze and execution

The provider-capability policy is frozen before any provider call. Run each
capability kind once for the complete candidate set, validate the retained
evidence, and derive the matrix before freeze:

```text
python3 campaign_runner.py probe-auth-gate
python3 campaign_runner.py probe-installation-surface
python3 grader_surface_probe.py run
python3 grader_surface_probe.py validate --allow-provider-capability-unavailable
python3 provider_assignment_selftest.py
python3 finalize_provider_assignments.py --write
python3 finalize_provider_assignments.py --validate
python3 freeze_campaign.py --dry-run
python3 freeze_campaign.py --write
python3 freeze_campaign.py --validate
```

An unavailable provider/role is retained as evidence and excluded by the
deterministic assignment rule. A probe-integrity failure invalidates the
generation. Any retry after an attempted capability probe requires a new
campaign generation; probe evidence is append-only and never counts as an
operator run or independent grade.

After the frozen-input commit exists, validate or dry-run orchestration before
execution:

```text
python3 campaign_runner.py validate
python3 campaign_runner.py all --dry-run
python3 campaign_runner.py operators --jobs 2
python3 campaign_runner.py graders --jobs 2
python3 campaign_runner.py verify
```

`--run <run-id>` may be repeated for a selected subset. Completed sessions and
grades are skipped. Incomplete post-session evidence is never overwritten.
The runner must execute in an environment where Bubblewrap namespaces are
permitted; it fails closed when the isolation preflight cannot prove that the
host source tree is absent.

The operator-facing process needs only `./maude` and
`MAUDE_PUBLIC_SOCKET`. It does not need, and must not receive, the runtime
configuration, expected disposition, grading rubric, failure taxonomy, or
prior evidence. The raw driver request/response queue remains
evaluator-private behind the trusted public-CLI broker.

## Provider and session boundary

Every operator and every independent grader receives a separate genuinely
fresh process and session using the exact provider configuration recorded in
the frozen run matrix. The candidates are `openai-sol` (`gpt-5.6-sol`) and
`anthropic-sonnet` (Claude Sonnet). Binary or credential presence alone does
not establish capability: the predeclared role-specific probes decide which
assignments are admissible. The runner sends one initial assignment and permits
no follow-up, resume, continuation, or evaluator coaching. A grader never
shares the operator's process, session identity, or conversational state.

Provider network and locally configured provider credentials are permitted
only inside the provider-session transport. Task-level network, production
credentials, production systems, and external operational effects remain
prohibited. Every operator command crosses into a source-contained,
credential-free, prompt-free, no-network namespace.

The Codex provider transport uses a task-blind filesystem boundary: the
operator variant mounts no task paths, runtime sockets, repository source, or
operator HOME, while the grader variant mounts only the frozen grade bundle
read-only at `/evidence`. The provider still receives its one frozen assignment
through its normal input. It retains the provider authentication needed for
transport until that process exits; the private provider tree is then
destroyed. The trusted direct stdio MCP shim shares the provider transport
namespace and can access retained authentication by construction. Its
hash-pinned implementation has no auth-reading path and the runtime proof
records no auth read, but this is not a namespace-enforced auth boundary or an
auth-free shim claim.

The Claude provider transport is likewise task-blind and retains only its
private provider authentication and provider network. Its MCP proxy is a
separately sandboxed, credential-free, no-network process. Neither that proxy
nor the downstream command broker receives the semantic evaluator prompt.

Strict per-session configuration makes MCP the only model action surface:

- operators receive exactly the hash-pinned
  `mcp__operator__terminal` tool;
- graders receive exactly the hash-pinned
  `mcp__grader__evidence` tool;
- no provider built-in tools are enabled;
- Codex disables intrinsic and optional action features, uses
  `approval_policy="never"`, and pins MCP protocol `2025-06-18`;
- Claude uses strict MCP configuration, a new session UUID,
  `--no-session-persistence`, disabled slash/browser surfaces, and MCP protocol
  `2025-11-25`; and
- provider-specific action/result correlations must validate exactly before a
  capability or campaign session is accepted.

The operator terminal tool crosses into a credential-free, prompt-free trusted
broker. That broker launches each model-selected command in a fresh
source-contained Bubblewrap mount, network, and PID namespace with no network.
For Maude-surface runs, each command namespace receives only the public-CLI
socket; the public-CLI broker alone can access the driver queue. Graders receive
no terminal broker and can only list or read the frozen grade bundle through
the read-only evidence tool. Installation specimens additionally use a
separately sandboxed persistent PTY broker so an interactive child can survive
across model tool calls; each tool call remains a disposable command-sandbox
client operation.

Canonical long campaign and evidence paths remain unchanged in manifests,
transcripts, and reports. Short owner-private AF_UNIX socket arenas are an
internal transport indirection only. The runner checks the encoded address
length before every bind or connect, enforces a maximum of 100 bytes, and
records owner permissions and cleanup of the short arena without substituting
its path for the canonical evidence identity.

If a public request times out after it has been queued, the broker reports a
retained unknown and preserves the queue correlation; it does not imply that
the private request was cancelled or never executed.

The committed-evidence verifier re-derives every provider action from raw
JSONL, compares `action-accounting.json`, rejects duplicate or missing actions
and truncated command results, validates the retained-auth transport and exact
one-tool boundary, replays provider/shim/broker correlations and per-command
namespace proofs, checks normalized provider results against shim results,
checks public-CLI request/queue/response settlement, and verifies PTY and
short-socket cleanup. Run that verification again against the raw-evidence
commit; creating evidence files is not by itself a boundary proof. These are
boundary proofs, not claims that the provider API itself ran without network
access.

## Frozen runtime configuration

The accepted schema discriminator is:

```json
{"schema": "maude.synthetic-runtime.v1"}
```

The configuration is deliberately declarative. This is the complete supported
top-level shape:

```json
{
  "schema": "maude.synthetic-runtime.v1",
  "scenario_id": "s01-example",
  "clock_start": "2026-07-26T00:00:00Z",
  "workspace": {
    "path": "/absolute/materialized/operator-workspace",
    "base_files": {
      "deploy/app.yaml": "base UTF-8 bytes"
    }
  },
  "runtime": {
    "behavior": "normal",
    "timeout_seconds": 12,
    "session": {
      "session_id": "run-synthetic-001",
      "created_status": "created",
      "launch_status": "exited",
      "pid": 41001,
      "exit_code": 0
    },
    "after_intervention_status": "exited"
  },
  "create": {
    "behavior": "normal",
    "session_id": "run-synthetic-001",
    "error": {"code": -32040, "message": "refused", "data": {}}
  },
  "grant": {
    "behavior": "normal",
    "grant_id": "sgr-synthetic-001",
    "enforcement": "declared-effects-only",
    "state": "active",
    "unmet_axes": [],
    "recent_uses": [],
    "error": {"code": -32040, "message": "grant refused", "data": {}}
  },
  "launch": {
    "behavior": "normal",
    "status": "exited",
    "pid": 41001,
    "exit_code": 0,
    "timeout_seconds": 12,
    "error": {"code": -32040, "message": "launch refused", "data": {}}
  },
  "initial_sessions": [],
  "initial_state": {},
  "candidate": {
    "session_id": "run-synthetic-001",
    "promotion_id": "promotion-synthetic-001",
    "status": "pending",
    "changed_files": ["deploy/app.yaml"],
    "excluded_files": [],
    "diff_stat": "1 file changed",
    "diff_fixture": "--- a/deploy/app.yaml\n+++ b/deploy/app.yaml\n",
    "result_files": {
      "deploy/app.yaml": "candidate UTF-8 bytes",
      "obsolete.conf": null
    }
  },
  "events": [],
  "interventions": [],
  "governor": {
    "pill": "OK",
    "sentence": "Synthetic governor is running.",
    "mode": "code",
    "context_id": "synthetic-lab",
    "initialized": true
  },
  "operator_snapshot": {},
  "operator_decisions": [],
  "adapters": {},
  "faults": {
    "create": {"code": -32040, "message": "refused", "data": {}},
    "grant": {"code": -32040, "message": "refused", "data": {}},
    "launch": {"code": -32040, "message": "refused", "data": {}},
    "methods": {
      "runtime.promotion.get": {
        "code": -32041,
        "message": "read unavailable",
        "data": {}
      }
    }
  }
}
```

`runtime.behavior` accepts `normal`, `create_refusal`,
`launch_refusal`, `timeout`, or `disconnect_after_dispatch`. The more specific
`create.behavior` and
`launch.behavior` override it. `grant.behavior` accepts `normal`, `refusal`, or
`error`. A configured grant failure is returned from
`runtime.grant.activate`; the real Maude plan runner then follows its existing
fail-safe behavior and continues without an attached grant.

`launch.kind: "disconnect"` aliases `disconnect_after_dispatch`. The runtime
accepts the launch request and closes that client connection without a response
frame. It leaves the session's prior state intact; it does not fabricate a
terminal status.

`initial_state` may override the persisted runtime-only keys used for restart
and recovery specimens: `runtime_sessions`, `next_runtime_session`,
`pending_interventions`, `intervention_decisions`, `dynamic_events`,
`candidate_session_id`, `promotion_status`, `candidate_staged`,
`promotion_decision`, and `grant_by_session`.

For file values:

- a JSON string means its exact UTF-8 encoding;
- `null` means the file is absent;
- `{"text": "..."}` is an explicit UTF-8 form;
- `{"base64": "..."}` supplies arbitrary exact bytes.

Every path key must be relative and remain beneath `workspace.path`.

`promotion` may be used as an alias for candidate promotion metadata, and
top-level `base_files` / `result_files` are accepted for simple generated
fixtures. `candidate` values take precedence.

### Canonical event shape

Events retain the Agent Governor canonical envelope. Details stay under
`payload`; the harness does not copy them to renderer-specific top-level keys:

```json
{
  "event_id": "evt-synthetic-0001",
  "session_id": "run-synthetic-001",
  "seq": 1,
  "at": "2026-07-26T00:00:00Z",
  "kind": "tool_call_proposed",
  "source_layer": "adapter",
  "backend_kind": "claude_code",
  "correlation_id": null,
  "parent_event_id": null,
  "receipt_ids": [],
  "payload": {
    "tool_call_id": "tool-001",
    "tool_name": "Edit",
    "tool_input": {"file_path": "deploy/app.yaml"}
  },
  "lane": "governed"
}
```

Missing envelope fields receive deterministic synthetic defaults. Payload
fields are never promoted to the top level.

The harness also preserves these canonical response boundaries:

- `runtime.promotion.diff` returns only `promotion_id` and `diff`;
- `runtime.intervention.list` does not add `action_class` or
  `communication_warning`;
- the default `operator.snapshot` has no top-level `overall`.

Those details intentionally preserve compatibility gaps in the baseline Maude
renderers instead of repairing them inside the evaluation.

## Starting one isolated lab

Materialize an absolute fake repository workspace, an operator-visible command
directory, and three private directories: runtime state, driver control, and
evidence. The command directory may contain operator materials such as
`task/plan.md`; the repository workspace remains the governed execution
workspace.

Start the runtime:

```text
python3 synthetic_runtime.py \
  --config /campaign/private/runtime.json \
  --socket /campaign/private/runtime.sock \
  --state-dir /campaign/private/runtime-state
```

After `runtime-ready.json` appears, start the driver:

```text
python3 maude_driver.py \
  --control-dir /campaign/private/control \
  --socket /campaign/private/runtime.sock \
  --workspace /campaign/repo \
  --command-cwd /campaign/operator \
  --evidence-dir /campaign/evidence/interface
```

After `driver-ready.json` appears, start the trusted public-CLI broker outside
the operator namespace:

```text
python3 public_cli_broker.py \
  --control-dir /campaign/private/control \
  --socket /campaign/public/maude.sock \
  --trace /campaign/evidence/public-cli-broker.jsonl \
  --ready /campaign/evidence/public-cli-broker-ready.json \
  --cleanup /campaign/evidence/public-cli-broker-cleanup.json
```

After the broker-ready record appears, expose a copy or link named `maude` in
the operator-visible directory, bind only the public socket into that
namespace, and set:

```text
MAUDE_PUBLIC_SOCKET=/campaign/public/maude.sock
```

Operator examples:

```text
./maude help
./maude run task/plan.md
./maude supervised list
./maude supervised events run-synthetic-001
./maude --key ctrl+g
./maude --screen
./maude --wait 2
./maude --restart
```

`--restart` destroys the current `MaudeApp` and `GovernorClient`, then creates a
fresh app/client against the same persisted synthetic runtime. It does not
restart or erase the runtime.

## Evidence boundary

Raw evidence remains separate:

- `runtime-state/rpc-transcript.jsonl` contains every exact decoded JSON frame,
  its exact body as base64, and its SHA-256;
- evaluator-private `control/requests/` and `control/responses/` preserve the
  filesystem queue and are not operator-visible;
- `public-cli-broker.jsonl` correlates each bounded public request to its
  private queue request and, where observed, response digests; a public
  timeout retains an explicit unknown settlement and later queue evidence;
- `interface/driver-actions.jsonl` binds each input to its logical output and
  screen digest;
- `interface/screens/*.svg` contains full rendered screens.

The public CLI prints only the interface output. It never returns the scenario
configuration or any evaluator-only answer.

## Fidelity limitation

The driver is a headless adapter over the real Textual app. It exercises the
real Maude input, command, RPC, and rendering code but does not evaluate raw
PTY behavior such as terminal capability negotiation, cursor escape sequences,
keyboard latency, or alternate-screen restoration. Representative raw-terminal
specimens need a separate pexpect capture and must be labeled separately.

Candidate file bytes are staged into the disposable workspace when scripted
worker completion occurs: during launch when no intervention is pending, or
after the final scripted intervention is approved. `diff` then exposes the
frozen candidate, `keep` retains the staged result bytes, and `discard`
restores the base bytes. For a recovery fixture with `initial_sessions`, the
candidate defaults to already staged; `candidate.staged` or
`initial_state.candidate_staged` may make that explicit. This provides
deterministic, side-effect-free fixture custody; it is not testimony that a
real worker or Governor uses that exact staging mechanism.

Authority effect: none.
