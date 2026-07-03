# Architecture

Maude is a terminal executor desk for governed agent runs, built on Textual.
It talks to a running Agent Governor daemon over JSON-RPC and is a pure
client — no governor code is imported, no models are shared, no state is
coupled. Maude drives supervised harness sessions over RPC and renders the
results; the daemon owns the harness adapters, the tool-interception point,
and all authority decisions.

## Separation of Concerns

```
  Maude (this repo)              Governor (agent_gov repo)
  ─────────────────              ────────────────────────
  Renders the desk               Runs policy pipeline
  Parses operator commands       Manages constraints
  Drives session lifecycle       Owns supervisor FSM + interception
  Tracks local view state        Stores sessions, event ledger
  Displays receipts + status     Produces receipts (sole writer)
```

The JSON-RPC boundary is the contract. Maude depends on the governor
daemon's RPC interface, not its Python packages. Maude mints no authority:
every approve/deny/promote is relayed to the daemon, which decides.

## Components

### Client Layer (`client/`)

`GovernorClient` wraps a pluggable `Transport` with typed methods for every
daemon RPC method Maude uses:

- **Transport abstraction** (`transport.py`): `Transport` protocol +
  `UnixSocketTransport` implementation. The protocol defines `connect()`,
  `close()`, `read_message()`, `write_message()`, and `connected`.
- **RPC client** (`rpc.py`): `GovernorClient` accepts an optional
  `transport` parameter. When omitted, it creates a `UnixSocketTransport`
  from `socket_path` or `governor_dir`. Domain methods delegate to
  `_call()` / `_call_streaming()`.
- **Models** (`models.py`): Pydantic models that mirror the governor's
  response shapes. Derived from daemon output, not shared code.

Planned (GS-9): this in-repo client is replaced by the
`ag_shell_client` package extracted in the agent_gov repo, which pins the
shell contract version and is CI-tested against the daemon.

**RPC methods by namespace:**

| Namespace | Methods |
|-----------|---------|
| `governor.*` | hello, now, status |
| `runtime.session.*` | create, launch, get, list, events, pause, resume, kill, fork |
| `runtime.intervention.*` | list, resolve |
| `runtime.promotion.*` | get, diff, resolve |
| `receipts.*` | list, detail |
| `scars.*` | list, history |
| `commit.*` | pending, fix, revise, proceed, exceptions |
| `sessions.*` | list, create, get, delete |
| `chat.*` (legacy) | send, stream, models, backend |
| `intent.*` (legacy) | templates, schema, validate, compile, policy |

### Intent Parser (`intents.py`)

Lightweight regex matching that classifies operator input: the supervised
command set (`supervised launch/list/events/approve/deny/kill/…`), the
tight-loop aliases (`y`/`n`/`p`/`go`), review verbs (`diff`/`apply`/
`rollback`), lineage (`lineage`/`history`), overview (`snapshot`/`context`/
`clear`), governor queries (`status`/`why`), session management, and the
legacy PLAN/BUILD + template intents.

No NLP. No LLM classification. Just patterns. Fast and predictable.

Legacy: `CHAT` is the current fallback — unmatched input streams through
the daemon's `chat.stream`. This is unsupported and scheduled for removal
at GS-15, after which unmatched input renders unknown-command help.

### Session State (`session.py`)

Local view state: the active governor session, context-usage accounting,
message history for display, and the legacy PLAN/BUILD mode + spec-draft
tracking (unsupported, removal at GS-15). This is Maude's state, not the
governor's — the governor has its own regime, decisions, and violations;
Maude just shows them.

### UI Layer (`ui/`, `app.py`)

Textual application: header, `GovernorStatusBar` (color-coded MODE / SPEC /
SESSION / GOV), a scrollable Rich log pane (supervised events, command
output, streams), input box, footer.

**Status polling:** every 5 seconds Maude calls `governor.now` and updates
the status bar — a live heartbeat of the governor's state.

**Current vs target shape:** today `app.py` is a single ~1,500-line module
holding all command handlers. The ratified target (maude-boundary.md,
agent_gov repo; built at GS-10) decomposes it into three seams:
**ScreenManager** (queue home · session view · sessions board · diff view +
overlay stack), **CommandRegistry** (command objects replacing the if/elif
dispatch), and **DecisionFeedController** (the one component that
understands the decision envelope). The legacy chat/PLAN/BUILD handlers are
quarantined into `commands/legacy.py` at GS-10 and deleted at GS-15.

## Data Flow

### Supervised run

```
1. Operator types "supervised launch add error handling to users.py"
2. Intent parser → SUPERVISED_LAUNCH
3. runtime.session.create + runtime.session.launch RPCs
4. Daemon starts the harness adapter; tool calls are intercepted daemon-side
5. Maude auto-polls runtime.intervention.list; pending approvals render
6. Operator answers y/n → runtime.intervention.resolve
7. Session exits → runtime.promotion.get/diff render the workspace changes
8. Operator promotes or rejects → runtime.promotion.resolve
9. Receipts land daemon-side; Maude renders them
```

### Status command

```
1. Operator types "status"
2. Intent parser → STATUS
3. governor.status RPC sent to daemon
4. Response rendered to the log pane
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
│   (desk)    │  Content-Length framing │ (governor serve)  │
│             │ ─────────────────────▶  │                   │
│ GovernorClient                        │ JSON-RPC 2.0      │
│   └─ Transport (pluggable)            │                   │
│       └─ UnixSocketTransport          │                   │
└─────────────┘                        └──────────────────┘
```

The `Transport` protocol is the extension point. To add a new transport:

1. Implement `Transport` protocol (connect, close, read_message,
   write_message, connected)
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

Streaming methods use JSON-RPC notifications (no `id` field) for deltas,
with a final response carrying the request `id`.

## Planned: the plan-executor spine

See [ROADMAP.md](../ROADMAP.md). After the GS-10 decomposition: bounded-plan
ingestion (`run <plan.md>`, M-2), harness selection via
`runtime.adapters.list` (M-3), run-report bundles (M-4), obstruction notes
(M-5), and the non-interactive ingress pair — headless human one-shot (M-6)
and the synthetic submitter contract (M-7). None of these exist yet; they
are labeled roadmap items, not current behavior.
