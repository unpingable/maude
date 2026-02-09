# Architecture

Maude is a Textual TUI that talks to a running Agent Governor instance over HTTP. It is a pure client — no governor code is imported, no models are shared, no state is coupled.

## Separation of Concerns

```
  Maude (this repo)              Governor (agent_gov repo)
  ─────────────────              ────────────────────────
  Renders UI                     Runs policy pipeline
  Parses user intent             Manages constraints
  Tracks local state             Stores sessions
  Streams responses              Proxies to LLM backend
  Displays governor status       Produces receipts
```

The HTTP boundary is the contract. Maude depends on the governor's REST API, not its Python packages.

## Components

### Client Layer (`client/`)

`GovernorClient` wraps `httpx.AsyncClient` with typed methods for every governor endpoint:

- **V1 (MVP)**: health, sessions, chat completions (streaming), governor now/status
- **V2 (stubbed)**: runs, dashboard summary, run events (SSE)

`models.py` contains Pydantic models that mirror the governor's response shapes. These are derived from the governor's actual API output, not from shared code.

### Intent Parser (`intents.py`)

Lightweight regex matching that classifies user input into one of 11 intent types:

```
PLAN, LOCK_SPEC, BUILD, SHOW_SPEC, SHOW_DIFF,
APPLY, ROLLBACK, WHY, STATUS, HELP, CHAT
```

`CHAT` is the default — anything that doesn't match a command goes to the model via the governor's `/v1/chat/completions` endpoint.

No NLP. No LLM classification. Just patterns. Fast and predictable.

### Session State (`session.py`)

Local state machine tracking the user's workflow:

```
  PLAN ──(lock spec)──▶ PLAN (locked) ──(build)──▶ BUILD
   ▲                                                  │
   └──────────────────(set_mode PLAN)─────────────────┘
```

- `Mode.PLAN` — accumulating spec text, exploring
- `Mode.BUILD` — implementing (requires locked spec)
- `spec_draft` / `spec_locked` — local spec tracking
- `messages` — conversation history (for display and chat context)
- `last_governor_now` — cached status from polling

This is Maude's state, not the governor's. The governor has its own regime, decisions, and violations. Maude just shows them.

### UI Layer (`ui/`, `app.py`)

Textual application with five composed widgets:

```
Header          ─  App title
GovernorStatusBar ─  MODE / SPEC / SESSION / GOV status (color-coded)
RichLog         ─  Scrollable chat pane with Rich markup
Input           ─  User input box
Footer          ─  Keybinding hints
```

**Status bar colors:**
- Green — governor reports ok
- Yellow — warnings or degraded state
- Red — violations or blocked state

**Status polling:** Every 5 seconds, Maude calls `GET /governor/now` and updates the status bar. This gives you a live heartbeat of the governor's state without needing to ask.

## Data Flow

### Chat message

```
1. User types "explain decorators"
2. Intent parser → CHAT
3. Message appended to local history
4. POST /sessions/{id}/messages (persist user message)
5. POST /v1/chat/completions (stream=true, full history)
6. SSE stream parsed, deltas rendered to chat pane
7. Full response appended to local history
8. POST /sessions/{id}/messages (persist assistant message)
```

### Status command

```
1. User types "status"
2. Intent parser → STATUS
3. GET /governor/status
4. Response rendered to chat pane (context, mode, viewmodel summary)
```

### Governor status poll

```
1. Timer fires (every 5s)
2. GET /governor/now
3. Response cached in session.last_governor_now
4. Status bar updated with text + color level
```

## API Surface

Maude consumes these governor endpoints:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Startup connectivity check |
| `/sessions/` | GET | List sessions (resume latest) |
| `/sessions/` | POST | Create new session |
| `/sessions/{id}` | GET | Load session with messages |
| `/sessions/{id}` | DELETE | Delete session |
| `/sessions/{id}/messages` | POST | Persist a message |
| `/v1/chat/completions` | POST | Streaming chat (SSE) |
| `/governor/now` | GET | Glanceable status (polling) |
| `/governor/status` | GET | Full status with viewmodel |
| `/v2/runs` | GET | List runs (future) |
| `/v2/runs` | POST | Create run (future) |
| `/v2/runs/{id}/events` | GET | Stream run events (future) |
| `/v2/dashboard/summary` | GET | Dashboard stats (future) |

## Future: Apply Gate

The planned apply gate will intercept model output that proposes file changes:

```
1. Model streams response containing code changes
2. Maude detects proposed mutations (file writes, patches)
3. Changes displayed in diff pane (right split)
4. User must type "apply" to execute
5. Apply request goes through governor for policy check
6. Only if governor approves does the write happen
```

This is not yet implemented. Currently, Maude is chat-only — it displays model responses but does not execute file operations.
