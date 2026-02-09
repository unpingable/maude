# Maude

**Terminal UI for governed AI chat. Every mutation goes through the gate.**

Maude is a standalone TUI frontend for [Agent Governor](https://github.com/unpingable/agent_governor). It gives you a Claude Code-like chat experience where all model interactions are mediated by a constraint engine over HTTP.

The model proposes. The governor gates. You decide.

---

## The Problem

You have a governor running. It enforces decisions, catches contradictions, blocks unverified writes. But the only way to talk to it is through a web browser or raw API calls.

**You want a terminal.**

A fast, keyboard-driven interface that shows you governor state at a glance, streams model responses, and puts an explicit gate between "the model said this" and "this actually happens."

## The Solution

Maude is that terminal. It connects to a running governor instance over HTTP and gives you:

- **Streaming chat** through the governor's OpenAI-compatible endpoint
- **Live governor status** in a persistent status bar (mode, regime, violations)
- **Intent-based commands** for plan/build/lock/apply workflows
- **Explicit apply gate** (TODO) — proposed changes require your approval before they touch disk

Maude never imports governor code. Two repos, one HTTP boundary.

---

## Quick Start

```bash
# Install
git clone <repo-url>
cd maude
python3 -m venv .venv
.venv/bin/pip install -e .

# Start governor (in another terminal)
cd ../agent_gov
bash start.sh

# Launch maude
maude --governor-url http://127.0.0.1:8000
```

Type `help` to see available commands. Type anything else to chat.

---

## Architecture

```
+--------------------------------------+
| Header (Maude v0.1.0)               |
+--------------------------------------+
| Status bar: MODE=PLAN  SPEC=UNLOCKED|
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
  ┌──────────┐         HTTP          ┌──────────────┐
  │  Maude   │ ──────────────────▶   │  Governor    │
  │  (TUI)   │  /v1/chat/completions │  (FastAPI)   │
  │          │  /governor/now        │              │
  │          │  /sessions/           │  ┌─────────┐ │
  │          │  /governor/status     │  │ Backend │ │
  │          │ ◀──────────────────── │  │(Ollama/ │ │
  │          │      SSE stream       │  │Claude/  │ │
  └──────────┘                       │  │Codex)   │ │
                                     │  └─────────┘ │
                                     └──────────────┘
```

Maude talks to governor. Governor talks to the model. Maude never talks to the model directly.

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

Maude reads from environment variables, CLI flags, or both:

| Setting | Env Var | CLI Flag | Default |
|---------|---------|----------|---------|
| Governor URL | `GOVERNOR_URL` | `--governor-url` | `http://127.0.0.1:8000` |
| Context ID | `GOVERNOR_CONTEXT_ID` | `--context-id` | `default` |
| Governor mode | `GOVERNOR_MODE` | — | `code` |

CLI flags override environment variables.

---

## Project Structure

```
src/maude/
  app.py              # Textual TUI application
  config.py           # Settings (env + CLI)
  intents.py          # Regex intent parser
  session.py          # Local state machine (PLAN/BUILD)
  client/
    http.py           # Async HTTP client (httpx)
    models.py         # Pydantic models matching governor API
  ui/
    widgets.py        # GovernorStatusBar
    theme.tcss        # Textual CSS layout
tests/
  test_intents.py     # Intent parsing (28 tests)
  test_session.py     # State machine (12 tests)
  test_client.py      # Model deserialization (13 tests)
```

---

## Development

```bash
# Setup
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# Tests
.venv/bin/python -m pytest tests/ -v

# Lint
.venv/bin/ruff check src/ tests/
```

---

## Roadmap

What's built:

- [x] Streaming chat via governor
- [x] Intent parser (plan/build/lock/status/why/help)
- [x] Session state machine (PLAN/BUILD, spec lock)
- [x] Live governor status polling
- [x] Session persistence (create/resume via governor API)
- [x] 52 unit tests

What's next:

- [ ] Apply gate — require explicit approval before file mutations
- [ ] Diff pane — right-side split showing proposed changes
- [ ] Spec draft/lock workflow wired through governor
- [ ] Session picker — list and switch sessions
- [ ] V2 run creation and event streaming
- [ ] Rollback support
- [ ] Mode switching (code/research/fiction)

---

## Documentation

| Document | Contents |
|----------|----------|
| [docs/architecture.md](docs/architecture.md) | System design, data flow, API mapping |
| [docs/commands.md](docs/commands.md) | Full command and intent reference |
| [docs/configuration.md](docs/configuration.md) | Environment, CLI, and runtime settings |

---

## License

Apache-2.0

---

*You talk. The governor listens. Maude is just the terminal.*
