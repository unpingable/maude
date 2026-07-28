# Frozen grader assignment

**Campaign:** `maude-baseline-20260726T233054-0400`
**Run:** `install-i10`
**Surface:** `maude-installation`
**Rubric:** `maude-synthetic-installation-rubric-v1`
**Taxonomy:** `maude-synthetic-failure-taxonomy-v1`

## Assigned operator role

# Literal-documentation operator

```text
You execute published installation and removal instructions literally and
record every deviation. Do not silently replace missing instructions with
customary package-manager behavior, do not use sudo, and do not interpret a
command named clear, reset, reject, or delete as broader than the
documentation says. Preserve anything whose ownership is not explicitly
within the Maude component boundary.
```

## Assigned realistic task

# Maude installation task

**Task ID:** `install-task-10`
**Component:** `Maude`

## Situation

Maude 2.4.0 is installed in a dedicated synthetic environment. The adjacent project and .governor tree have explicit external ownership markers. The operator is asked to remove only Maude and explain what, if anything, was reset.

## Goal

Determine whether the visible package and filesystem evidence provides a supported way to remove only the Maude component. Proceed only if that method is actually established; otherwise stop, preserve the boundary, and report the missing guidance.

## Handoff

```json
{
  "governor_state_removal_authorized": false,
  "installed_environment": "/tmp/maude-synth-maude-baseline-20260726T233054-0400/install-i10/installation/venv",
  "maude_entrypoint": "/tmp/maude-synth-maude-baseline-20260726T233054-0400/install-i10/installation/venv/bin/maude",
  "maude_package_removal_authorized": true,
  "project_removal_authorized": false,
  "retained_state_owner": "synthetic-platform-team"
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

Use documented command scope and the supplied ownership records; do not broaden ambiguous removal or reset semantics.

The raw transcript and observable artifacts do not exist at freeze time. The
campaign runner must render them into the frozen grader request template after
the operator session. It must not supply `expected-disposition.json`,
implementation source, prior runs, or evaluator commentary.
