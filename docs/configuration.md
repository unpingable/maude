# Configuration

Maude is configured through environment variables and CLI flags. CLI flags take precedence.

## Settings

### `governor_dir`

Path to the governor directory (contains `proposals.json`, sessions, etc.). Used to derive the Unix socket path if no explicit socket is provided.

| Source | Value |
|--------|-------|
| Default | Current working directory (or `$CWD/.governor` if it exists) |
| Env var | `GOVERNOR_DIR` |
| CLI flag | `--governor-dir` |

```bash
# Environment
export GOVERNOR_DIR=/home/user/project/.governor
maude

# CLI
maude --governor-dir /home/user/project/.governor
```

### `socket_path`

Explicit path to the governor daemon's Unix socket. When set, bypasses the automatic socket path derivation from `governor_dir`.

| Source | Value |
|--------|-------|
| Default | Auto-derived from governor_dir: `$XDG_RUNTIME_DIR/governor-{hash}.sock` |
| Env var | `GOVERNOR_SOCKET` |
| CLI flag | `--socket` |

```bash
# Environment
export GOVERNOR_SOCKET=/run/user/1000/governor-abc123.sock
maude

# CLI
maude --socket /run/user/1000/governor-abc123.sock
```

The auto-derivation uses the same algorithm as `governor serve --print-socket-path`:

```
socket_path = $XDG_RUNTIME_DIR/governor-{sha256(governor_dir)[:12]}.sock
```

### `context_id`

The governor context to operate in. Contexts isolate decisions, constraints, and sessions from each other.

| Source | Value |
|--------|-------|
| Default | `default` |
| Env var | `GOVERNOR_CONTEXT_ID` |

```bash
GOVERNOR_CONTEXT_ID=my-project maude
```

### `governor_mode`

The governor's operating mode. Determines which constraint set applies.

| Source | Value |
|--------|-------|
| Default | `code` |
| Env var | `GOVERNOR_MODE` |

Available modes depend on the governor configuration: `code`, `fiction`, `nonfiction`, `research`, `general`.

## Socket Path Resolution

When no explicit `socket_path` is provided, `GovernorClient` resolves in this order:

1. `GOVERNOR_SOCKET` env var (if set)
2. `GOVERNOR_DIR` env var or `--governor-dir` flag → derive socket path
3. Current working directory → check for `.governor/` subdirectory → derive socket path

This means in most cases, just `cd` into your project directory and run `maude` — it finds the socket automatically.

## Typical Setups

### Local development (default)

Governor daemon and Maude on the same machine:

```bash
# Terminal 1: start governor daemon
cd my-project
governor serve

# Terminal 2: launch maude (auto-detects socket from cwd)
cd my-project
maude
```

### Explicit governor directory

When the governor directory is not the current working directory:

```bash
maude --governor-dir /home/user/project/.governor
```

### Explicit socket

When you know the socket path (e.g., from systemd service):

```bash
maude --socket /run/user/1000/governor-abc123.sock
```

### Multiple contexts

Switch between projects by pointing at different governor directories:

```bash
# Project A
maude --governor-dir ~/project-a/.governor

# Project B
maude --governor-dir ~/project-b/.governor
```

Each governor directory has its own sessions, decisions, and constraints.

## Governor Prerequisites

Maude requires a running governor daemon. It connects via Unix socket on startup and will error if the daemon is unreachable.

Start the daemon with:

```bash
governor serve                    # Default: Unix socket
governor serve --stdio            # Stdio mode (for Electron/Guvnah)
governor serve --mode fiction     # Set governor mode
```

The daemon must have:
- A backend configured (Anthropic, Ollama, Claude Code, or Codex)
- The context initialized (happens automatically on first use)

See the [Agent Governor documentation](https://github.com/unpingable/agent_governor) for setup instructions.

## Transport

Maude uses a pluggable `Transport` abstraction. The default is `UnixSocketTransport` which connects to the daemon over a Unix domain socket with Content-Length framed JSON-RPC 2.0.

For testing or custom integrations, inject a custom transport:

```python
from maude.client import GovernorClient, Transport

client = GovernorClient(transport=my_custom_transport)
```

See `src/maude/client/transport.py` for the protocol definition.
