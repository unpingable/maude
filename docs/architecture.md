# Architecture

Maude is a Textual TUI that talks to a running Agent Governor daemon over JSON-RPC. It is a pure client — no governor code is imported, no models are shared, no state is coupled.

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

The JSON-RPC boundary is the contract. Maude depends on the governor daemon's RPC interface, not its Python packages.

## Components

### Client Layer (`client/`)

`GovernorClient` wraps a pluggable `Transport` with typed methods for every daemon RPC method:

- **Transport abstraction** (`transport.py`): `Transport` protocol + `UnixSocketTransport` implementation. The protocol defines `connect()`, `close()`, `read_message()`, `write_message()`, and `connected`. Future transports (TCP, etc.) implement the same interface.
- **RPC client** (`rpc.py`): `GovernorClient` accepts an optional `transport` parameter. When omitted, it creates a `UnixSocketTransport` from `socket_path` or `governor_dir`. All 25+ domain methods delegate to `_call()` / `_call_streaming()` which use the transport for framing.
- **Models** (`models.py`): Pydantic models that mirror the governor's response shapes. Derived from daemon output, not shared code.

**RPC methods by namespace:**

| Namespace | Methods |
|-----------|---------|
| `governor.*` | hello, now, status |
| `sessions.*` | list, create, get, delete |
| `intent.*` | templates, schema, validate, compile, policy |
| `receipts.*` | list, detail |
| `scars.*` | list, history |
| `commit.*` | pending, fix, revise, proceed, exceptions |
| `chat.*` | send, stream, models, backend |

### Intent Parser (`intents.py`)

Lightweight regex matching that classifies user input into intent types:

```
PLAN, LOCK_SPEC, BUILD, SHOW_SPEC, SHOW_DIFF,
APPLY, ROLLBACK, WHY, STATUS, HELP, CHAT,
SESSIONS, SWITCH_SESSION, DELETE_SESSION,
PLAN_TEMPLATE, CLEAR_TEMPLATE
```

`CHAT` is the default — anything that doesn't match a command goes to the model via the daemon's `chat.stream` RPC method.

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

**Status polling:** Every 5 seconds, Maude calls `governor.now` via RPC and updates the status bar. This gives you a live heartbeat of the governor's state without needing to ask.

## Data Flow

### Chat message

```
1. User types "explain decorators"
2. Intent parser → CHAT
3. Message appended to local history
4. chat.stream RPC sent to daemon (full history)
5. Daemon augments messages (system prompt, anchors, puppet)
6. Daemon streams to backend, relays chat.delta notifications
7. Maude yields deltas, renders to chat pane
8. Full response appended to local history
```

### Status command

```
1. User types "status"
2. Intent parser → STATUS
3. governor.status RPC sent to daemon
4. Response rendered to chat pane
```

### Governor status poll

```
1. Timer fires (every 5s)
2. governor.now RPC sent to daemon
3. Response cached in session.last_governor_now
4. Status bar updated with text + color level
```

## Transport Architecture

```
┌─────────────┐                        ┌──────────────────┐
│   Maude     │  Unix socket           │ Governor Daemon   │
│   (TUI)     │  Content-Length framing │ (governor serve)  │
│             │ ─────────────────────▶  │                   │
│ GovernorClient                        │ JSON-RPC 2.0      │
│   └─ Transport (pluggable)            │   └─ 25 methods   │
│       └─ UnixSocketTransport          │                   │
└─────────────┘                        └──────────────────┘
```

The `Transport` protocol is the extension point. To add a new transport:

1. Implement `Transport` protocol (connect, close, read_message, write_message, connected)
2. Pass instance to `GovernorClient(transport=my_transport)`
3. All domain methods work unchanged

### Content-Length framing

Same protocol as the daemon and MCP server:

```
Content-Length: 42\r\n
\r\n
{"jsonrpc":"2.0","method":"governor.now","id":1,"params":{}}
```

### Streaming

`chat.stream` uses JSON-RPC notifications (no `id` field) for content deltas:

```
→ {"jsonrpc":"2.0","method":"chat.stream","id":1,"params":{...}}
← {"jsonrpc":"2.0","method":"chat.delta","params":{"content":"Hello"}}
← {"jsonrpc":"2.0","method":"chat.delta","params":{"content":" world"}}
← {"jsonrpc":"2.0","id":1,"result":{"done":true}}
```

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
