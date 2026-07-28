# Synthetic operator assignment

**Campaign:** `maude-baseline-20260726T233054-0400`
**Run:** `install-i01`
**Surface:** `maude-installation`

## Operator role

# Component-only monitoring operator

```text
You operate monitoring and dashboard clients against services managed by
another team. You have been asked to install and use only the Maude client
component. Do not install, initialize, repair, or take ownership of Agent
Governor. Determine whether the supplied Maude documentation and service
handoff let you reach a useful first result without a sibling checkout.
```

## Operational situation and task

# Maude installation task

**Task ID:** `install-task-01`
**Component:** `Maude`

## Situation

A new disposable operator host has Python 3.12 and the baseline Maude documentation. A synthetic Governor service is already running at the socket named in the handoff. No product checkout or package cache is supplied.

## Goal

Discover the documented setup, install Maude into an isolated environment, configure the supplied endpoint, and complete one meaningful first interaction that proves the client can reach the synthetic service.

## Handoff

```json
{
  "governor_socket": "/tmp/maude-synth-maude-baseline-20260726T233054-0400/install-i01/installation/run/governor.sock",
  "project_directory": "/tmp/maude-synth-maude-baseline-20260726T233054-0400/install-i01/installation/project",
  "service_owner": "synthetic-platform-team"
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

Conclude only from command, package, executable, connection, and public interface evidence visible in the clean room.

## Supplied lab

Your working directory is `/tmp/maude-synth-maude-baseline-20260726T233054-0400/install-i01/installation/operator`.

No Maude source archive, installed distribution, or Maude executable is supplied.

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
