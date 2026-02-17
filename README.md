# Maude

**Terminal UI for governed AI chat. Every mutation goes through the gate.**

Maude is a standalone TUI frontend for [Agent Governor](https://github.com/unpingable/agent_governor). It connects to the governor daemon over JSON-RPC and gives you a keyboard-driven chat experience where all model interactions are mediated by the constraint engine.

The model proposes. The governor gates. You decide.

---

## The Problem

You have a governor running. It enforces decisions, catches contradictions, blocks unverified writes. But the only way to talk to it is through a web browser or raw API calls.

**You want a terminal.**

A fast, keyboard-driven interface that shows you governor state at a glance, streams model responses, and puts an explicit gate between "the model said this" and "this actually happens."

## The Solution

Maude is that terminal. It connects to a running governor daemon over a Unix socket and gives you:

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

Maude wires 25 of the daemon's 36 RPC methods:

| Namespace | Methods | What It Does |
|-----------|---------|-------------|
| `governor.*` | hello, now, status | Health check, live status polling |
| `sessions.*` | list, create, get, delete | Session management |
| `chat.*` | send, stream, models, backend | Governed generation with streaming |
| `intent.*` | templates, schema, validate, compile, policy | Structured intent compilation |
| `receipts.*` | list, detail | Gate receipt browsing |
| `scars.*` | list, history | Failure history and active scars |
| `commit.*` | pending, fix, revise, proceed, exceptions | Violation resolution |

### Not Yet Wired

| Namespace | Methods | What It Would Show |
|-----------|---------|-------------------|
| `governor.selfcheck` | 1 | Deployment health checks |
| `correlator.*` | 3 | Capture detection: K-vector, regime, indicators |
| `scope.*` | 4 | Locality policy: grants, contracts, escalation |
| `stability.*` | 3 | Semantic stability: perturbation audits |

---

## Commands

| Command | What It Does |
|---------|-------------|
| `plan <text>` | Append to the spec draft |
| `lock spec` | Lock the spec (required before BUILD) |
| `build` | Switch to BUILD mode |
| `show spec` | Display the current spec draft |
| `status` | Fetch and display governor status |
| `why` | Show why something is blocked |
| `sessions` | List available sessions |
| `switch <id>` | Switch to a different session |
| `delete <id>` | Delete a session |
| `help` | Show available commands |
| *anything else* | Sent to the model via governor |

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
