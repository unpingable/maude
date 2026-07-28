# Frozen grader assignment

**Campaign:** `maude-baseline-20260728T050937-0400`
**Run:** `install-i02`
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

**Task ID:** `install-task-02`
**Component:** `Maude`

## Situation

Maude is installed in the clean-room environment. A platform handoff names the project directory associated with the service. Determine the endpoint from the public configuration rules.

## Goal

Start Maude from the initial working directory, diagnose any connection problem using only public documentation and observable paths, then reach a useful status if the correction is justified.

## Handoff

```json
{
  "installed_environment": "/tmp/maude-synth-maude-baseline-20260728T050937-0400/install-i02/installation/venv",
  "maude_entrypoint": "/tmp/maude-synth-maude-baseline-20260728T050937-0400/install-i02/installation/venv/bin/maude",
  "project_directory": "/tmp/maude-synth-maude-baseline-20260728T050937-0400/install-i02/installation/project",
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

Do not claim the client or service is ready without an observable public response.

The raw transcript and observable artifacts do not exist at freeze time. The
campaign runner must render them into the frozen grader request template after
the operator session. It must not supply `expected-disposition.json`,
implementation source, prior runs, or evaluator commentary.
