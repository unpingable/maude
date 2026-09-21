# Maude

Maude is the authoring and review desk for bounded plans. Create a draft, check
its dependencies, inspect changes, and lock an exact revision. Human edits and
accepted model proposals create a new [Plan Core revision](docs/PLAN-CORE.md). A valid or
locked plan does not authorize execution.

For a read-only external caller, [read an exact authored objective](docs/OBJECTIVE-READ.md)
without opening a draft store. This exports goal and criteria for operator use;
it does not assess completion or make private prose public-safe.

**Design-flow status: pre-alpha.** For a credential-free first exercise, start
with the [bounded authoring walkthrough](docs/BOUNDED-AUTHORING-WALKTHROUGH.md).
Then consult [Plan Core](docs/PLAN-CORE.md), [the design workbench](docs/PHOSPHOR-DESIGN.md),
and the [connected tutorial baseline and prerequisites](docs/CONSTELLATION-TUTORIAL.md).
For the implemented local cache composition, see
[connected setup, source pins, and recovery boundaries](qualification/synthetic_cache/CONNECTED_SUCCESSOR.md).
Its native local run is qualified; public-only reproduction and the composed
release remain separate checks. This profile uses explicitly synthetic Standing.
The default browser proposal examples use deterministic fixtures. An opt-in
[OpenRouter route](docs/OPENROUTER-AUTHORING.md) uses Switchyard's bounded provider
path; one live description-only proposal and its semantic diff have been
verified. Provider completion does not accept a plan. One closed synthetic-cache
compiler exists; there is no generic
compiler from operational prose or generic browser handoff.

For the current public composed path, start with the immutable
[Constellation 0.1.0-alpha.6 walkthrough](https://unpingable.com/constellation/releases/0.1.0-alpha.6/guide.html).
Its `reviewed-local-copy/v1` profile used Maude's exact plan validation and
authority-neutral executor to complete one reviewed, authorized-once local
effect under Docket custody. Public newcomers reproduced the retained evidence
without repeating the provider call or effect. It is a narrow integration
profile, not a claim that the pre-alpha design workspace is ready for general
ECAD/design-flow use.

Phosphor inspection is a separate read-only process hosted by Constellation AG.
Nightshift, Constellation AG, Docket, and the executor own the post-handoff
facts and effects. See
[the surface boundaries](docs/PHOSPHOR-NG-CONVERGENCE.md).

---

## Transitional supervised agent sessions (classic RPC)

The commands in this section use classic Governor's session RPC. They are not
the Constellation AG campaign interface and are not the starting point for new successor
integrations. Their continued packaging dependency is tracked separately from
Plan Core; do not infer Constellation AG compatibility from a shared “governor” label.

Install this transitional interface explicitly:

```bash
.venv/bin/pip install -e '.[classic-rpc]'
```

The extra pins `ag-shell-client` to the public classic Agent Governor source
revision used by this checkout. A base Maude install supports Plan Core and
authoring without installing the classic RPC transport. Launching `maude`
without the extra exits with an installation instruction; it does not silently
fall back to another transport.

Maude launches and supervises a coding harness (Claude Code today) as a governed process. You see every tool call. You approve or deny. When the session ends, you review the diff and promote or reject the changes.

```
supervised launch Add error handling to users.py and write tests

  [ 14s] Approved: Edit — users.py
  [ 16s] Approved: Write — test_users.py
  [ 18s] Approved: Edit — README.md
  [ 22s] Approved: Bash — pytest (adapted python → python3)

  Session exited (exit=0), 5 tools approved

supervised promotion sess_cfa8ab1ebb75

  Promotion: prom_e72576d3798f
  Files: users.py, test_users.py, README.md
  Diff stat:
    README.md | 15 +++++++++++++
    users.py  |  5 +++-
    test_users.py (new file)

supervised promote sess_cfa8ab1ebb75

  Promoted — changes accepted
  5 tests pass
```

**The full loop:** launch → tool interception → approve/deny → session exit → review diff → promote or reject.

Read-only tools (Read, Glob, Grep) are auto-approved. Write tools (Bash, Write, Edit) require operator approval. Unanswered approvals time out and deny by default. Rejected promotions revert the workspace.

Planned (see [ROADMAP.md](ROADMAP.md)): harness selection (M-3), obstruction notes (M-5), and headless one-shot execution (M-6). Shipped: bounded-plan ingestion (`run <plan.md>`, M-2) and run-report bundles (`report <id>`, M-4).

### Supervised Commands

| Command | What It Does |
|---------|-------------|
| `supervised launch [task]` | Launch a governed harness session |
| `supervised list` | List active/completed sessions |
| `supervised events <id>` | Show canonical event stream |
| `supervised interventions <id>` | Show pending tool approvals |
| `supervised approve <id> <tcid>` | Approve a tool call |
| `supervised deny <id> <tcid>` | Deny a tool call |
| `supervised promotion <id>` | Show pending workspace changes |
| `supervised diff <id>` | Show unified diff of changes |
| `supervised promote <id>` | Accept workspace changes |
| `supervised reject <id>` | Revert workspace changes |
| `supervised fork <id> [task]` | Fork from promoted session |
| `supervised kill <id>` | Terminate session |

---

## Plan Core and where planning happens

Maude now owns the explicit pre-governed PlanDocument artifact toolchain. The
headless `maude-plan` CLI and TUI `draft` commands create durable revisions,
structural check receipts, semantic diffs, and immutable lock receipts. Rich
authoring and hypothesis exploration may still live in external tools; human
and agent changes enter through the same revision boundary. The retired
conversational PLAN/BUILD state remains retired.

Draft validity is not governed admissibility, and locking exact bytes does not
authorize them. See [Plan Core](docs/PLAN-CORE.md). The separate transitional
classic-RPC commands supervise a coding harness. They are not the successor
governed execution path: AG owns authorization, Docket owns attempt custody and
settlement, and the selected executor performs the authorized work.

For an existing local Plan Core database, `maude-plan --read-only list` and
`maude-plan --read-only inspect DRAFT_ID` provide observation-only CLI access.
They refuse an absent, malformed, or incompatible store and do not initialize
or modify its database contents. `inspect` assembles an aggregate through
separate reads, so concurrent writers can make even one command mixed-time;
use quiescent writers for a consistent aggregate. `mode=ro` does not promise
the absence of all SQLite sidecar activity. Mutating commands refuse with
`--read-only`.

For a supported external-caller walkthrough, use the current
[alpha.6 integration guide](https://unpingable.com/constellation/releases/0.1.0-alpha.6/guide.html)
and its [Constellation integration map](https://unpingable.com/constellation/integration.html).
The earlier Maude-only alpha.1 consultation profile remains a historical,
read-only example; it does not compose with AG, grant permission, or dispatch
an effect.

## Relationship to Phosphor-ng

Maude is the bounded-plan and supervised-session desk. Phosphor (the
operator-facing identity of `constellation-ag`'s `ag-operator-ui`) is the
separate, read-only Nightshift → Constellation AG → Docket campaign inspector. The two surfaces
share canonical language, exact identity presentation, honest absence, and a
navigation-only deep-link contract; they do not share authority or state
machines. Nightshift now owns an optional immutable plan/session → exact
proposal/occurrence/work relation at proposal preparation. Maude queries it
read-only before emitting a Phosphor-ng link; an absent or unavailable owner
record remains visibly unlinked. See
[`docs/PHOSPHOR-NG-CONVERGENCE.md`](docs/PHOSPHOR-NG-CONVERGENCE.md).
Optional authenticated custody for a new plan/session handoff is documented in
[`docs/AUTHORING-CUSTODY.md`](docs/AUTHORING-CUSTODY.md). It uses distinct
session-issuer and handoff-producer credentials and does not submit or
authorize work.

Phosphor-ng now also has a separate Maude-owned `/design` process for mutable
pre-governed PlanDocuments. It shares product navigation with the inspector,
not its trust domain: `ag-operator-ui` remains read-only and imports no Plan
Core machinery. See [Phosphor-ng Design](docs/PHOSPHOR-DESIGN.md).

The Design process also supports immutable, scope-bounded agent edit proposals.
Provider output is proposed structured data containing only ordinary Plan Core
operations. Maude validates and retains proposals for review; only an explicit
accept action creates a draft successor through the same revision CAS used for
human edits. There is no auto-accept, generic compiler, or browser
handoff path. One closed local-Compose compiler exists solely for the
disposable synthetic cache qualification and remains outside `/design`. See
[Plan Edit Proposals](docs/PLAN-EDIT-PROPOSALS.md).

The [synthetic cache qualification](qualification/synthetic_cache/README.md)
is the first exact PlanNode → compiler → Nightshift/AG/Docket execution witness.
It supplies `/design` a read-only cross-probe projection; it does not make the
browser a runtime owner.

---

## Legacy: governed chat (unsupported)

Earlier versions framed Maude as a governed-chat client. That framing is retired (ratified decision D-GS-2 in the Agent Governor governed-shell campaign). The chat path — streaming model responses through the daemon's `chat.stream`, plus the PLAN/BUILD spec-lock workflow — still exists in the code but is **unsupported legacy**, scheduled for removal at the v3.0 release (GS-15). Do not build on it. If a chat lane is ever missed, it returns as its own recorded decision, not as a leftover.

Terminology note: Maude's current `runtime.intervention.*` calls are local
supervised tool-approval records. They are not Constellation AG governed-intervention
requests and confer no AG standing or authorization. The exact cross-surface
namespace and future authoring boundary are documented in
[`docs/PHOSPHOR-NG-CONVERGENCE.md`](docs/PHOSPHOR-NG-CONVERGENCE.md).

Maude never imports governor code. Two repos, one RPC boundary.

---

## Quick Start

```bash
# Install
git clone https://github.com/unpingable/maude
cd maude
python3 -m venv .venv
.venv/bin/pip install -e '.[classic-rpc]'

# Initialize the project Maude will supervise (once)
governor --root /path/to/project init

# Terminal 1: keep this project-scoped daemon running
governor --root /path/to/project serve

# Terminal 2: target the same initialized project
maude --governor-dir /path/to/project/.governor
```

Governor and Maude must name the same project: the Unix socket identity is
derived from the exact `.governor` path. Starting `governor serve` from the
Governor source checkout while Maude targets another project starts a healthy
daemon on the wrong socket. `governor serve --stdio` is for other clients and
cannot accept Maude's Unix-socket connection.

This local Governor daemon supervises Maude sessions. It is not Constellation AG, and
Maude does not maintain a direct interactive socket to Constellation AG. Governed work
reaches Constellation AG only through the separately documented exact Nightshift handoff
and authenticated intervention ingress.

Type `help` for a one-screen orientation or `help all` for the complete
reference. `supervised launch <task>` (or `go <task>`) starts a governed run.
`draft new <goal>` starts an artifact draft; `help draft` shows its compact
workflow. The equivalent headless surface is `maude-plan --help`.

To evaluate the browser board-file workspace against its deterministic corpus:

```bash
scripts/run-phosphor-design-demo.sh
# open http://127.0.0.1:8427/phosphor/design
```

---

## Architecture

```
+--------------------------------------+
| Header (maude — project | backend)   |
+--------------------------------------+
| Status bar: project  backend  MODE=  |
+--------------------------------------+
|                                      |
| Log pane (events, streaming,         |
|           scrollable)                |
+--------------------------------------+
| Input box                            |
+--------------------------------------+
| Footer (keybindings)                 |
+--------------------------------------+
```

```
┌──────────┐   Unix socket (JSON-RPC)   ┌──────────────┐
│  Maude   │ ──────────────────────────▶ │  Governor    │
│  (desk)  │  Content-Length framing     │  Daemon      │
│          │                             │              │
│ Governor │  governor.now               │  ┌─────────┐ │
│  Client  │  runtime.session.*          │  │ Harness │ │
│          │  runtime.intervention.*     │  │ adapter │ │
│          │  runtime.promotion.*        │  │(Claude/ │ │
│          │  receipts.*, commit.*       │  │ Codex/…)│ │
└──────────┘ ◀──────────────────────────┘──────────────┘
```

Maude talks to the daemon. The daemon owns the harness adapters and the interception point. Maude never talks to the model directly, and adapter selection is introspection-informed, never adapter ownership.

**Transport**: JSON-RPC 2.0 with Content-Length framing over Unix socket. Same protocol as MCP servers and VS Code language servers. Pluggable `Transport` interface for future TCP support.

---

## RPC Methods Wired

Maude wires 44 of the daemon's RPC methods:

| Namespace | Methods | What It Does |
|-----------|---------|-------------|
| `governor.*` | hello, now, status | Health check, live status polling |
| `runtime.session.*` | create, launch, get, list, events, pause, resume, kill | Supervised sessions |
| `runtime.intervention.*` | list, resolve | Tool approval/denial |
| `runtime.promotion.*` | get, diff, resolve | Workspace change review |
| `receipts.*` | list, detail | Gate receipt browsing |
| `scars.*` | list, history | Failure history and active scars |
| `commit.*` | pending, fix, revise, proceed, exceptions | Violation resolution |
| `sessions.*` | list, create, get, delete | Session management |
| `chat.*` (legacy) | send, stream, models, backend | Governed generation (unsupported, removal at GS-15) |
| `intent.*` (legacy) | templates, schema, validate, compile, policy | Structured intent compilation |

---

## Commands

| Command | What It Does |
|---------|-------------|
| `draft new/list/inspect/edit/check/diff/lock/handoff` | Plan Core artifact workflow |
| `supervised launch [task]` / `go [task]` | Launch governed harness session |
| `supervised list` | List supervised sessions |
| `supervised events <id>` | Show event stream |
| `supervised interventions <id>` | Show pending approvals |
| `supervised approve <id> <tcid>` / `y` | Approve tool call |
| `supervised deny <id> <tcid>` / `n` | Deny tool call |
| `supervised promotion <id>` | Show workspace changes |
| `supervised diff <id>` | Show unified diff |
| `supervised promote <id>` | Accept changes |
| `supervised reject <id>` | Revert changes |
| `supervised fork <id> [task]` | Fork from promoted session |
| `supervised kill <id>` | Kill session |
| `report <id> [plan.md]` | Run report — three-layer disclosure (surface / detail / law) |
| `snapshot` / `wtf` | Operator overview |
| `lineage` / `lineage tree` / `history` | Session lineage navigation |
| `status` | Governor status |
| `why` | Show why something is blocked |
| `context` / `clear` | Context usage / reset |
| `help` | Show commands |

Legacy (unsupported, removal at GS-15): `plan <text>`, `lock spec`, `build`, `show spec`, and free-text chat via the governor.

### Keybindings

| Key | Action |
|-----|--------|
| `Ctrl+Y` | Approve pending tool call |
| `Ctrl+D` | Deny pending tool call |
| `Ctrl+T` | Lineage tree |
| `Ctrl+N` | New session |
| `Ctrl+Q` | Quit |

---

## Configuration

| Setting | Env Var | CLI Flag | Default |
|---------|---------|----------|---------|
| Governor dir | `GOVERNOR_DIR` | `--governor-dir` | Current directory |
| Socket path | `GOVERNOR_SOCKET` | `--socket` | Auto-derived from governor dir |
| Context ID | `GOVERNOR_CONTEXT_ID` | `--context-id` | `default` |
| Governor mode | `GOVERNOR_MODE` | — | `code` |
| Session label | `MAUDE_LABEL` | `--label` | (none) |
| Nightshift read binary | `NIGHTSHIFT_READ_PROGRAM` | — | (not configured) |
| Nightshift canonical store | `NIGHTSHIFT_STORE` | — | (not configured) |
| Phosphor-ng loopback URL | `PHOSPHOR_NG_BASE_URL` | — | (links omitted) |
| Maude custody store | `MAUDE_CUSTODY_STORE` | — | (custody disabled) |
| Session issuer key file | `MAUDE_SESSION_CUSTODY_KEY_FILE` | — | (custody disabled) |
| Session issuer principal | `MAUDE_SESSION_ISSUER_PRINCIPAL_ID` | — | (custody disabled) |
| Session issuer key identity | `MAUDE_SESSION_ISSUER_KEY_ID` | — | (custody disabled) |

CLI flags override environment variables. Socket path is auto-derived from governor dir using the same algorithm as `governor serve`.

---

## Project Structure

```
src/maude/
  app.py              # Textual TUI application (monolith; decomposition planned at GS-10)
  config.py           # Settings (env + CLI)
  intents.py          # Regex intent parser
  session.py          # Local state machine
  client/
    __init__.py       # Public exports (GovernorClient, Transport, models)
    rpc.py            # JSON-RPC 2.0 client over pluggable transport
    transport.py      # Transport protocol + UnixSocketTransport
    models.py         # Pydantic models matching daemon response shapes
  ui/
    widgets.py        # GovernorStatusBar
tests/
  test_intents.py     # Intent parsing
  test_session.py     # State machine + project name
  test_client.py      # Model deserialization
  test_integration.py # Live daemon integration (skip without daemon)
  test_transport.py   # Transport protocol + mock transport
  conftest.py         # Shared fixtures
```

---

## Development

```bash
# Setup
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# Tests
.venv/bin/python -m pytest tests/ -v

# Integration tests (requires running governor daemon)
bash test-with-governor.sh

# Lint
.venv/bin/ruff check src/ tests/
```

---

## What's Built

- [x] Supervised harness sessions (launch, tool interception, approve/deny, kill)
- [x] Promotion review (diff, promote, reject; rejected promotions revert)
- [x] Session fork from promoted baseline
- [x] Session lineage navigation (`lineage`, `lineage tree`, `history`)
- [x] Inline event streaming (tool proposals, completions, denials)
- [x] Tight supervised loop (`go` / `y` / `n` / `p` + auto-poll)
- [x] COMMUNICATE-class loud warning (external sends)
- [x] Run reports (`report <session_id> [plan.md]`) — composes from daemon reads (no new RPC); three-layer disclosure: plain surface (outcome, files, tool counts), expandable detail (authority block, acceptance criteria), raw law one `why` away (ReviewPacket verbatim). Honest-absence discipline: reads that fail surface as notes, nothing inferred. Testimony-not-admission: exit 0 is "the run reports it ended," never upgraded to a verdict; `used ≤ granted` is operator-visible, overruns flagged.
- [x] Gate receipt browsing, scar history, violation resolution (fix/revise/proceed)
- [x] Live governor status polling; context usage gauge
- [x] Pluggable transport (Unix socket now, TCP later)
- [x] Legacy: streaming chat + PLAN/BUILD spec workflow (unsupported, removal at GS-15)

## What's Next

See [ROADMAP.md](ROADMAP.md) — the repositioning roadmap: foundation refactor (GS-9/GS-10), the decision-queue desk (GS-11..GS-14), the plan-executor spine (M-1..M-5: plan envelope, plan ingestion, harness selection, run reports, obstruction notes), the v3.0 chat cut (GS-15), and headless one-shot execution (M-6).

---

## Documentation

| Document | Contents |
|----------|----------|
| [docs/REPOSITIONING.md](docs/REPOSITIONING.md) | The executor thesis, boundary, do-not-build list |
| [docs/architecture.md](docs/architecture.md) | System design, transport, data flow, RPC mapping |
| [docs/commands.md](docs/commands.md) | Full command and intent reference |
| [docs/configuration.md](docs/configuration.md) | Environment, CLI, and runtime settings |

---

## Related Projects

| Project | What It Is |
|---------|-----------|
| [Agent Governor](https://github.com/unpingable/agent_governor) | The constraint system (Python, 11k+ tests) |
| [Guvnah](https://github.com/unpingable/guvnah) | Electron desktop cockpit (Svelte 5, same daemon RPC) |
| [Governor WebUI](https://github.com/unpingable/governor_webui) | Web-based governance dashboard (FastAPI) |
| [VS Code Extension](https://github.com/unpingable/vscode-governor) | IDE integration — preflight, correlator, file checking |

---

## License

Apache-2.0

---

*The plan arrives. Maude runs it. The governor gates. You review the diff.*
