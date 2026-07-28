# Commands

Maude uses a lightweight regex intent parser (`src/maude/intents.py`) to
classify input. Recognized commands are handled locally or relayed to the
governor daemon over RPC. The primary surface is the supervised-run loop;
the chat-era commands are legacy (see the last section).

## Supervised runs (primary)

### `supervised launch <task>` / `go <task>`

Launch a coding harness (Claude Code today) as a governed, supervised
session. Tool calls are intercepted by the governor; write-class tools wait
for operator approval.

### The tight loop: `y` / `n` / `p`

While a supervised session runs, Maude auto-polls pending interventions:

- `y` / `yes` / `approve` — approve the pending tool call
- `n` / `deny` — deny it
- `p` / `pending` — show pending interventions

Unanswered approvals time out and deny by default. COMMUNICATE-class tool
calls (external sends) render with a loud warning.

### Full supervised command set

| Command | What It Does |
|---------|-------------|
| `supervised launch [task]` | Launch a governed harness session |
| `supervised list` (or bare `supervised`) | List sessions |
| `supervised events <id>` | Canonical event stream |
| `supervised interventions <id>` | Pending tool approvals |
| `supervised approve <id> <tcid>` | Approve a tool call |
| `supervised deny <id> <tcid>` | Deny a tool call |
| `supervised promotion <id>` | Pending workspace changes |
| `supervised diff <id>` | Unified diff of changes |
| `supervised promote <id>` | Accept workspace changes |
| `supervised reject <id>` | Revert workspace changes |
| `supervised fork <id> [task]` | Fork from a promoted session |
| `supervised kill <id>` | Terminate session |

### `diff` / `apply` / `rollback`

Context-aware review verbs: with an active supervised session they act on
its promotion (diff / promote / reject); in a governance-violation context
they act on the pending commit (fix / revise / proceed flow via `why`).
`promote` and `accept` alias `apply`; `reject`, `revert`, and `undo` alias
`rollback`.

### `lineage` / `lineage tree` / `history`

Session lineage navigation: parent/child fork relationships (`lineage`,
`branch`), ASCII tree (`lineage tree`, `Ctrl+T`), and message history
(`history`, `log`).

### `snapshot` / `overview` / `wtf`

Operator overview: governor status, supervised sessions, context usage in
one screen.

### `context` / `ctx` / `usage` and `clear` / `reset`

Context-token usage display; `clear` starts a fresh session to reclaim
context.

## Governor queries

### `status` / `state`

Full governor status for the active context.

### `why` / `blocked`

Ask the governor why something is blocked (`governor.now` sentence +
suggested action).

## Session management

### `sessions` / `list sessions` / `ls`

Numbered session table (ID, title, message count, last updated).

### `switch <id>` / `session <id>` / `resume <id>`

Switch by ID or `#N` index.

### `delete session <id>` / `rm session <id>`

Delete by ID or index; deleting the active session creates a new one.

### `help` / `?`

List available commands.

## Keybindings

| Key | Action |
|-----|--------|
| `Ctrl+Y` | Approve pending tool call |
| `Ctrl+D` | Deny pending tool call |
| `Ctrl+T` | Lineage tree |
| `Ctrl+N` | New session |
| `Ctrl+Q` | Quit |
| `Ctrl+L` | Lock spec (legacy) |

## Status Bar

Updates every 5 seconds from `governor.now`; shows workflow mode, spec-lock
state (legacy), active session, active supervised session, context usage,
and governor status. Green = clear, yellow = degraded, red =
violations/blocked.

## Legacy: PLAN/BUILD and chat (unsupported, removal at GS-15)

These commands belong to the retired chat/spec-lock paradigm (ratified cut,
D-GS-2 — see [REPOSITIONING.md](REPOSITIONING.md)). They still parse, but
are unsupported and scheduled for deletion:

- `plan <text>` — append to the local spec draft
- `plan architecture` / `plan product` / `plan requirements` — load a spec
  template into guided mode; `clear template` unloads it
- `lock spec` / `freeze spec` — lock the draft (constraint submission is a
  stub; it does not reach the daemon)
- `build` / `implement` / `do it` — switch to BUILD mode (v2 run creation is
  a stub)
- `show spec` / `spec` — display the draft
- **free-text chat** — any input matching no command is streamed through the
  daemon's `chat.stream`. After GS-15, unmatched input will render
  unknown-command help instead.
