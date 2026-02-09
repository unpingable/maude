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
