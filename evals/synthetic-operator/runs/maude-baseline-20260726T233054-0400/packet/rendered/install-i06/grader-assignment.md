# Frozen grader assignment

**Campaign:** `maude-baseline-20260726T233054-0400`
**Run:** `install-i06`
**Surface:** `maude-installation`
**Rubric:** `maude-synthetic-installation-rubric-v1`
**Taxonomy:** `maude-synthetic-failure-taxonomy-v1`

## Assigned operator role

# Terminology-new systems administrator

```text
You are an experienced Linux systems administrator who is new to Maude and
Agent Governor terminology. Install and start the assigned Maude component
using the supplied documentation and handoff facts. Explain unfamiliar
components in ordinary operational terms, distinguish paths from services,
and stop instead of guessing when the documentation does not establish the
next action.
```

## Assigned realistic task

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
  "governor_socket": "/tmp/maude-synth-maude-baseline-20260726T233054-0400/install-i06/installation/run/governor.sock",
  "installed_environment": "/tmp/maude-synth-maude-baseline-20260726T233054-0400/install-i06/installation/venv",
  "maude_entrypoint": "/tmp/maude-synth-maude-baseline-20260726T233054-0400/install-i06/installation/venv/bin/maude",
  "service_owner": "synthetic-platform-team",
  "settings_file": "/tmp/maude-synth-maude-baseline-20260726T233054-0400/install-i06/installation/config/settings.env"
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

The raw transcript and observable artifacts do not exist at freeze time. The
campaign runner must render them into the frozen grader request template after
the operator session. It must not supply `expected-disposition.json`,
implementation source, prior runs, or evaluator commentary.
