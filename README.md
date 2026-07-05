# Maude

**Executor desk for governed agent runs. Every mutation goes through the gate.**

Plans are written outside Maude — by ChatGPT, Fable, Codex, or the operator. Maude runs them: launch a harness as a supervised process, watch every tool call go through the [Agent Governor](https://github.com/unpingable/agent_governor) gate, approve or deny, review the diff, promote or reject, keep the receipts.

The plan arrives. Maude runs it. The governor gates. You decide.

---

## Supervised Agent Sessions

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

Planned (see [ROADMAP.md](ROADMAP.md)): obstruction notes (M-5) and headless one-shot execution (M-6). Shipped: bounded-plan ingestion (`run <plan.md>`, M-2), harness selection (M-3), run-report bundles (`report <id>`, M-4).

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

## Where planning happens

Not here. Maude is the execution side of the loop: it consumes bounded plans, supervises the run, and returns a reviewable result. Spec authoring, hypothesis exploration, and "lock understanding before acting" live elsewhere — planning tools upstream, and the governor's admissibility gate at launch time (see the [Agent Governor](https://github.com/unpingable/agent_governor) governed-shell design). AG is one authority substrate Maude calls over RPC; Maude itself mints no authority and refuses nothing on its own behalf.

---

## Legacy: governed chat (unsupported)

Earlier versions framed Maude as a governed-chat client. That framing is retired (ratified decision D-GS-2 in the Agent Governor governed-shell campaign). The chat path — streaming model responses through the daemon's `chat.stream`, plus the PLAN/BUILD spec-lock workflow — still exists in the code but is **unsupported legacy**, scheduled for removal at the v3.0 release (GS-15). Do not build on it. If a chat lane is ever missed, it returns as its own recorded decision, not as a leftover.

Maude never imports governor code. Two repos, one RPC boundary.

---

## Quick Start

```bash
# Install
git clone https://github.com/unpingable/maude
cd maude
python3 -m venv .venv
.venv/bin/pip install -e .

# Start governor daemon (in another terminal)
cd ../agent_gov
pip install -e .
governor serve

# Launch maude (auto-discovers daemon socket)
maude --governor-dir /path/to/project/.governor
```

Type `help` to see available commands. `supervised launch <task>` (or `go <task>`) starts a governed run.

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
