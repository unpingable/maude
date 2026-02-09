# Commands

Maude uses a lightweight intent parser to classify user input. Recognized commands are handled locally. Everything else goes to the model through the governor.

## Intent Commands

### `plan <text>`

Append text to the local spec draft. Used during the PLAN phase to accumulate requirements before building.

```
> plan REST API with JWT auth and role-based access
Added to spec draft (47 chars)

> plan PostgreSQL for storage, Redis for caching
Added to spec draft (95 chars)

> show spec
Spec Draft (UNLOCKED):
REST API with JWT auth and role-based access
PostgreSQL for storage, Redis for caching
```

Also recognized: `let's plan`

### `lock spec` / `freeze spec`

Lock the current spec draft. Required before switching to BUILD mode. This is a local state transition — it signals that you're done planning and ready to implement.

```
> lock spec
Spec locked.
```

Keybinding: `Ctrl+L`

### `build` / `implement` / `do it`

Switch to BUILD mode. Requires a locked spec.

```
> build
Switched to BUILD mode.
```

If the spec isn't locked:

```
> build
Cannot enter BUILD mode without a locked spec
```

### `show spec` / `spec`

Display the current spec draft and its lock status.

### `show diff` / `diff`

*(Not yet implemented.)* Will show proposed file changes in a side pane.

### `apply` / `merge`

*(Not yet implemented.)* Will apply proposed changes through the governor's policy gate.

### `rollback` / `undo`

*(Not yet implemented.)* Will revert the last applied change set.

### `why` / `why blocked` / `blocked`

Ask the governor why something is blocked. Fetches `GET /governor/now` and displays the status sentence and suggested action.

```
> why
Why: 1 violation pending — anchor 'no-eval' triggered.
Suggested: Review violation and choose fix/revise/proceed.
```

### `status` / `state`

Fetch and display the full governor status for the active context.

```
> status
Governor Status:
  context: default
  mode: code
  initialized: true
  decisions: 3
  violations: 0
  claims: 12
```

### `help` / `?`

Show the list of available commands.

### `sessions` / `list sessions` / `ls`

List all sessions as a numbered table showing ID, title, message count, and last-updated date. The active session is marked.

```
> sessions
Sessions:
  #    ID               TITLE                    MSGS  UPDATED
  1    abc123def456     Maude session               12  2025-01-15  *active*
  2    789xyz000111     Auth planning                4  2025-01-14
  3    fedcba654321     Debug logging                8  2025-01-13
```

### `switch <id>` / `session <id>` / `resume <id>`

Switch to a session by its ID or by `#N` index from the last `sessions` listing. Loads the session's message history and resets local PLAN/BUILD state.

```
> switch #2
Switched to session: Auth planning (789xyz000111) — 4 messages

> switch abc123
Switched to session: Maude session (abc123def456) — 12 messages
```

### `delete session <id>` / `rm session <id>`

Delete a session by ID or `#N` index. If deleting the active session, a new session is created automatically.

```
> delete session #3
Deleted session: fedcba654321

> rm session abc123
Deleted session: abc123def456
Created new session: newid789
```

## Chat (Default)

Any input that doesn't match a command is treated as a chat message. It's sent to the governor's `/v1/chat/completions` endpoint with the full conversation history, and the response is streamed back to the chat pane.

```
> explain Python decorators
You: explain Python decorators
Assistant: A decorator is a function that takes another function...
```

The governor mediates this — your message goes through the policy pipeline before reaching the model backend, and the response is checked for violations before being returned.

## Keybindings

| Key | Action |
|-----|--------|
| `Ctrl+L` | Lock spec |
| `Ctrl+N` | New session |
| `Ctrl+Q` | Quit |

## Status Bar

The status bar at the top of the screen updates every 5 seconds:

```
MODE=PLAN  SPEC=UNLOCKED  SESSION=abc123  GOV=ok
```

- **MODE** — Current workflow mode (PLAN or BUILD)
- **SPEC** — Whether the spec draft is locked
- **SESSION** — Active governor session ID
- **GOV** — Governor status from `/governor/now`

Color coding:
- **Green** — All clear
- **Yellow** — Warnings or degraded state
- **Red** — Violations or blocked
