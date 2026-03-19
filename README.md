# Maude

**Terminal UI for governed AI chat. Every mutation goes through the gate.**

Maude is a standalone TUI frontend for [Agent Governor](https://github.com/unpingable/agent_governor). It connects to the governor daemon over JSON-RPC and gives you a keyboard-driven chat experience where all model interactions are mediated by the constraint engine.

The model proposes. The governor gates. You decide.

---

## Supervised Agent Sessions

Maude can launch and supervise Claude Code as a governed process. You see every tool call. You approve or deny. When the session ends, you review the diff and promote or reject the changes.

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

### Supervised Commands

| Command | What It Does |
|---------|-------------|
| `supervised launch [task]` | Launch a governed Claude Code session |
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

## Governed Chat

Maude also provides governed chat — streaming model responses through the governor's constraint engine:

- **Streaming chat** through the governor daemon's `chat.stream` RPC method
- **Live governor status** in a persistent status bar (mode, regime, violations)
- **Intent-based commands** for plan/build/lock/apply workflows
- **Intent compiler** — structured hypothesis-collapse via governor templates
- **Violation resolution** — fix/revise/proceed when the governor blocks
- **Session management** — list, switch, create, delete governance sessions
- **Receipts and scars** — browse gate receipts, failure history

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

Type `help` to see available commands. Type anything else to chat.

---

## Architecture

```
+--------------------------------------+
| Header (maude — project | backend)   |
+--------------------------------------+
| Status bar: project  backend  MODE=  |
+--------------------------------------+
|                                      |
| Chat pane (streaming, scrollable)    |
|                                      |
+--------------------------------------+
| Input box                            |
+--------------------------------------+
| Footer (keybindings)                 |
+--------------------------------------+
```

```
┌──────────┐   Unix socket (JSON-RPC)   ┌──────────────┐
│  Maude   │ ──────────────────────────▶ │  Governor    │
│  (TUI)   │  Content-Length framing     │  Daemon      │
│          │                             │              │
│ Governor │  governor.now               │  ┌─────────┐ │
│  Client  │  sessions.*                 │  │ Backend │ │
│          │  chat.stream → chat.delta   │  │(Claude/ │ │
│          │  intent.*                   │  │ Codex/  │ │
│          │  receipts.*, scars.*        │  │ Ollama) │ │
│          │  commit.*                   │  └─────────┘ │
└──────────┘ ◀──────────────────────────┘──────────────┘
```

Maude talks to the daemon. The daemon talks to the model. Maude never talks to the model directly.

**Transport**: JSON-RPC 2.0 with Content-Length framing over Unix socket. Same protocol as MCP servers and VS Code language servers. Pluggable `Transport` interface for future TCP support.

---

## RPC Methods Wired

Maude wires 44 of the daemon's 79 RPC methods:

| Namespace | Methods | What It Does |
|-----------|---------|-------------|
| `governor.*` | hello, now, status | Health check, live status polling |
| `sessions.*` | list, create, get, delete | Session management |
| `chat.*` | send, stream, models, backend | Governed generation with streaming |
| `intent.*` | templates, schema, validate, compile, policy | Structured intent compilation |
| `receipts.*` | list, detail | Gate receipt browsing |
| `scars.*` | list, history | Failure history and active scars |
| `commit.*` | pending, fix, revise, proceed, exceptions | Violation resolution |
| `runtime.session.*` | create, launch, get, list, events, pause, resume, kill | Supervised sessions |
| `runtime.intervention.*` | list, resolve | Tool approval/denial |
| `runtime.promotion.*` | get, diff, resolve | Workspace change review |

---

## Commands

| Command | What It Does |
|---------|-------------|
| `supervised launch [task]` | Launch governed Claude Code session |
| `supervised list` | List supervised sessions |
| `supervised events <id>` | Show event stream |
| `supervised interventions <id>` | Show pending approvals |
| `supervised approve <id> <tcid>` | Approve tool call |
| `supervised deny <id> <tcid>` | Deny tool call |
| `supervised promotion <id>` | Show workspace changes |
| `supervised diff <id>` | Show unified diff |
| `supervised promote <id>` | Accept changes |
| `supervised reject <id>` | Revert changes |
| `supervised fork <id> [task]` | Fork from promoted session |
| `supervised kill <id>` | Kill session |
| `snapshot` / `wtf` | Operator overview |
| `plan <text>` | Append to spec draft |
| `lock spec` | Lock the spec (required before BUILD) |
| `build` | Switch to BUILD mode |
| `show spec` | Display current spec draft |
| `status` | Governor status |
| `why` | Show why something is blocked |
| `sessions` | List governance sessions |
| `switch <id>` | Switch session |
| `help` | Show commands |
| *anything else* | Chat via governor |

### Keybindings

| Key | Action |
|-----|--------|
| `Ctrl+L` | Lock spec |
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
  app.py              # Textual TUI application
  config.py           # Settings (env + CLI)
  intents.py          # Regex intent parser (15 intent types)
  session.py          # Local state machine (PLAN/BUILD)
  client/
    __init__.py       # Public exports (GovernorClient, Transport, models)
    rpc.py            # JSON-RPC 2.0 client over pluggable transport
    transport.py      # Transport protocol + UnixSocketTransport
    models.py         # Pydantic models matching daemon response shapes
    http.py           # Legacy HTTP client (reference only, unwired)
  ui/
    widgets.py        # GovernorStatusBar
    theme.tcss        # Textual CSS layout
tests/
  test_intents.py     # Intent parsing (28 tests)
  test_session.py     # State machine + project name (25 tests)
  test_client.py      # Model deserialization (13 tests)
  test_integration.py # Live daemon integration (24 tests, skip without daemon)
  test_transport.py   # Transport protocol + mock transport (10 tests)
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

- [x] Streaming chat via governor daemon (JSON-RPC + chat.delta notifications)
- [x] Intent parser (plan/build/lock/status/why/help/sessions/switch/delete)
- [x] Session state machine (PLAN/BUILD, spec lock)
- [x] Live governor status polling (5s interval)
- [x] Session management (create/resume/switch/delete)
- [x] Intent compiler (template selection, form rendering, compilation)
- [x] Violation resolution (fix/revise/proceed)
- [x] Gate receipt browsing
- [x] Scar history
- [x] Pluggable transport (Unix socket now, TCP later)
- [x] Project name + backend type in status bar and terminal title
- [x] 112 unit tests + 24 integration tests (skipped without daemon)

## What's Next

- [ ] Apply gate — require explicit approval before file mutations
- [ ] Diff pane — right-side split showing proposed changes
- [ ] Correlator telemetry — K-vector display, capture alerts
- [ ] Scope view — locality policy visualization
- [ ] Mode switching (code/research/fiction)

---

## Documentation

| Document | Contents |
|----------|----------|
| [docs/architecture.md](docs/architecture.md) | System design, transport, data flow, RPC mapping |
| [docs/commands.md](docs/commands.md) | Full command and intent reference |
| [docs/configuration.md](docs/configuration.md) | Environment, CLI, and runtime settings |

---

## Related Projects

| Project | What It Is |
|---------|-----------|
| [Agent Governor](https://github.com/unpingable/agent_governor) | The constraint system (Python, 11k+ tests) |
| [Guvnah](https://github.com/unpingable/guvnah) | Electron desktop cockpit (Svelte 5, same daemon RPC) |
| [Governor WebUI](https://github.com/unpingable/governor_webui) | Web-based chat + governance dashboard (FastAPI) |
| [VS Code Extension](https://github.com/unpingable/vscode-governor) | IDE integration — preflight, correlator, file checking |

---

## License

Apache-2.0

---

*You talk. The governor listens. Maude is just the terminal.*
