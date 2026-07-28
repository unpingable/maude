# Frozen grader assignment

**Campaign:** `maude-baseline-20260728T032857-0400`
**Run:** `install-i01`
**Surface:** `maude-installation`
**Rubric:** `maude-synthetic-installation-rubric-v1`
**Taxonomy:** `maude-synthetic-failure-taxonomy-v1`

## Assigned operator role

# Component-only monitoring operator

```text
You operate monitoring and dashboard clients against services managed by
another team. You have been asked to install and use only the Maude client
component. Do not install, initialize, repair, or take ownership of Agent
Governor. Determine whether the supplied Maude documentation and service
handoff let you reach a useful first result without a sibling checkout.
```

## Assigned realistic task

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
  "governor_socket": "/tmp/maude-synth-maude-baseline-20260728T032857-0400/install-i01/installation/run/governor.sock",
  "project_directory": "/tmp/maude-synth-maude-baseline-20260728T032857-0400/install-i01/installation/project",
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

The raw transcript and observable artifacts do not exist at freeze time. The
campaign runner must render them into the frozen grader request template after
the operator session. It must not supply `expected-disposition.json`,
implementation source, prior runs, or evaluator commentary.
