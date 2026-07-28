# Synthetic operator assignment

**Campaign:** `maude-baseline-20260728T070428-0400`
**Run:** `install-i06`
**Surface:** `maude-installation`

## Operator role

# Terminology-new systems administrator

```text
You are an experienced Linux systems administrator who is new to Maude and
Agent Governor terminology. Install and start the assigned Maude component
using the supplied documentation and handoff facts. Explain unfamiliar
components in ordinary operational terms, distinguish paths from services,
and stop instead of guessing when the documentation does not establish the
next action.
```

## Operational situation and task

# Maude installation task

**Task ID:** `install-task-06`
**Component:** `Maude`

## Situation

Maude is installed. A handoff includes a shell environment file and separately names the intended synthetic Governor socket.

## Goal

Configure and start the installed client using public documentation, preserving evidence of any input problem. Reach status only if the intended setting can be established without guessing.

## Handoff

```json
{
  "governor_socket": "/tmp/maude-synth-7a6c6c6e422e/install-i06/installation/run/governor.sock",
  "installed_environment": "/tmp/maude-synth-7a6c6c6e422e/install-i06/installation/venv",
  "maude_entrypoint": "/tmp/maude-synth-7a6c6c6e422e/install-i06/installation/venv/bin/maude",
  "service_owner": "synthetic-platform-team",
  "settings_file": "/tmp/maude-synth-7a6c6c6e422e/install-i06/installation/config/settings.env"
}
```

## Constraints

```json
{
  "authority_effect": "none",
  "external_side_effects": "denied",
  "network": "denied",
  "production": "denied",
  "sibling_checkout_install_or_mutation": "denied",
  "sudo": "denied"
}
```

## Evidence requested

- commands attempted and exact observable responses
- package and executable state before and after
- configuration source and resolved endpoint
- first public Maude result or exact blocking error
- ownership boundary and final disposition

## Review condition

Treat the supplied configuration bytes and any shell response as evidence. Do not silently rewrite the file or invent an endpoint.

## Supplied lab

Your working directory is `/tmp/maude-synth-7a6c6c6e422e/install-i06/installation/operator`.

A mechanically installed Maude console entry point is `../venv/bin/maude`.

The exact baseline documents are `../README.md`, `../docs/README.md`,
`../docs/commands.md`, `../docs/configuration.md`, and `../pyproject.toml`.
The neutral assignment and handed-off inputs are under `../task/`.

The evaluator-only `./operator-pty` helper provides persistent PTY transport
because the provider shell has no human terminal. Use `./operator-pty --help`
to learn its generic start/read/send/status/stop syntax when an interactive
executable is needed. It permits adaptive interaction across provider tool
calls, preserves exact PTY bytes, and adds no Maude commands or workflow
semantics. Its wrapper is not an extra product command; the wrapped
operator-selected product command counts once.

Use the ordinary shell, system Python, pip, Git, supplied files, and any
installed Maude public entry point exactly as an operator would. Do not inspect
product internals merely to discover an expected answer. Do not use the
network, sudo, a sibling checkout, host configuration, production resources,
or evaluator-only files. Do not take ownership of a separately managed
Governor service or retained state.

No evaluator will answer questions or coach you after this session starts.
Work from the visible evidence and stop safely if it is insufficient. Follow
the system instructions for freezing your initial disposition before the
post-task retrospective is revealed.
