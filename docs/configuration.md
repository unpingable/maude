# Configuration

## Plan Core

`MAUDE_PLAN_STORE` selects the local Plan Core SQLite store. If unset,
`maude-plan` and the TUI use `<current-directory>/.maude/plans.sqlite`.
Filenames and store paths are operational locators and never participate in
PlanDocument semantic identity.

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

### Optional governed-handoff reads

`report <session_id> <plan.md>` can display Nightshift's immutable
authoring-context relation and an exact Phosphor-ng navigation link:

```bash
export NIGHTSHIFT_READ_PROGRAM=/absolute/path/to/nightshift
export NIGHTSHIFT_STORE=/var/lib/nightshift/nightshift.sqlite
export PHOSPHOR_NG_BASE_URL=http://127.0.0.1:8417
```

The first two values must appear together for the canonical read. The program
must be an absolute binary named `nightshift`; only
`cycle export-authoring-context --plan-ref ... --maude-session-id ...` is
invoked. The optional URL must be credential-free loopback HTTP(S). These
settings expose lineage only: they do not query or infer currentness, standing,
authorization, or execution state.

### Optional supervised-session custody

A complete four-value profile records the exact `runtime.session.create`
result and exact plan bytes before launch:

```bash
export MAUDE_CUSTODY_STORE=/var/lib/maude/authoring-custody.sqlite
export MAUDE_SESSION_CUSTODY_KEY_FILE=/run/credentials/maude-session-issuer.key
export MAUDE_SESSION_ISSUER_PRINCIPAL_ID=maude:supervisor
export MAUDE_SESSION_ISSUER_KEY_ID=maude-session-key:primary
```

Partial configuration refuses before launch. The separate
`maude-authoring-handoff` command uses its own producer credential to package
an existing signed session receipt for one exact sealed Nightshift base
request; it cannot mint a session receipt and does not submit the request.
See [`AUTHORING-CUSTODY.md`](AUTHORING-CUSTODY.md) for the command, replay law,
file custody, and environmental assumptions.

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
# One-time initialization
governor --root /absolute/path/to/my-project init

# Terminal 1: start the daemon for that exact project
governor --root /absolute/path/to/my-project serve

# Terminal 2: target the same .governor identity
maude --governor-dir /absolute/path/to/my-project/.governor
```

The explicit form is recommended for first launch because it makes a socket
mismatch visible. Once this works, running both commands from `my-project` and
launching bare `maude` is equivalent.

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
governor --root /path/to/project init    # Once, if not initialized
governor --root /path/to/project serve   # Unix socket used by Maude
```

The daemon must have:
- A backend configured (Anthropic, Ollama, Claude Code, or Codex)
- The target project initialized with `governor init`

Maude cannot attach to `governor serve --stdio`. The daemon and Maude must use
the same project-scoped `.governor` directory because that path determines the
default Unix socket.

See the [Agent Governor documentation](https://github.com/unpingable/agent_governor) for setup instructions.

## Transport

Maude uses a pluggable `Transport` abstraction. The default is `UnixSocketTransport` which connects to the daemon over a Unix domain socket with Content-Length framed JSON-RPC 2.0.

For testing or custom integrations, inject a custom transport:

```python
from maude.client import GovernorClient, Transport

client = GovernorClient(transport=my_custom_transport)
```

See `src/maude/client/transport.py` for the protocol definition.
