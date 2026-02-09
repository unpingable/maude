# Configuration

Maude is configured through environment variables and CLI flags. CLI flags take precedence.

## Settings

### `governor_url`

The base URL of the running governor instance.

| Source | Value |
|--------|-------|
| Default | `http://127.0.0.1:8000` |
| Env var | `GOVERNOR_URL` |
| CLI flag | `--governor-url` |

```bash
# Environment
export GOVERNOR_URL=http://192.168.1.50:8000
maude

# CLI
maude --governor-url http://192.168.1.50:8000
```

### `context_id`

The governor context to operate in. Contexts isolate decisions, constraints, and sessions from each other.

| Source | Value |
|--------|-------|
| Default | `default` |
| Env var | `GOVERNOR_CONTEXT_ID` |
| CLI flag | `--context-id` |

```bash
maude --context-id my-project
```

### `governor_mode`

The governor's operating mode. Determines which constraint set applies.

| Source | Value |
|--------|-------|
| Default | `code` |
| Env var | `GOVERNOR_MODE` |

Available modes depend on the governor configuration: `code`, `fiction`, `nonfiction`, `general`, `research`.

## Typical Setups

### Local development (default)

Governor and Maude on the same machine:

```bash
# Terminal 1: start governor
cd agent_gov && bash start.sh

# Terminal 2: launch maude
cd maude && maude
```

### Remote governor

Governor running on a server, Maude on your laptop:

```bash
export GOVERNOR_URL=http://my-server:8000
export GOVERNOR_CONTEXT_ID=project-alpha
maude
```

### Multiple contexts

Switch between projects by changing the context:

```bash
# Project A
maude --context-id frontend --governor-url http://localhost:8000

# Project B
maude --context-id backend --governor-url http://localhost:8000
```

Each context has its own sessions, decisions, and constraints.

## Governor Prerequisites

Maude requires a running governor instance. It checks connectivity on startup via `GET /health` and will warn if the governor is unreachable.

The governor must have:
- A backend configured (Ollama, Anthropic, Claude Code, or Codex)
- The context initialized (happens automatically on first use)

See the [Agent Governor documentation](https://github.com/unpingable/agent_governor) for setup instructions.
