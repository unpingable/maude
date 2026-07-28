# Frozen grader assignment

**Campaign:** `maude-baseline-20260728T070428-0400`
**Run:** `install-i09`
**Surface:** `maude-installation`
**Rubric:** `maude-synthetic-installation-rubric-v1`
**Taxonomy:** `maude-synthetic-failure-taxonomy-v1`

## Assigned operator role

# Source-install developer

```text
You are a Python developer accustomed to virtual environments, editable
installs, build backends, entry points, and dependency resolution. Evaluate
the documented Maude source-install path in the supplied offline clean room.
Use only the approved local media. Do not inspect implementation source,
bypass package checks, or treat a mechanically successful install as proof
that the runtime is ready.
```

## Assigned realistic task

# Maude installation task

**Task ID:** `install-task-09`
**Component:** `Maude`

## Situation

A handoff record identifies a dedicated environment as Maude 2.3.0, while the supplied target package metadata names 2.4.0. Retained Governor state is externally owned and must remain intact.

## Goal

Determine whether the supplied documentation establishes a supported in-place upgrade and perform only actions justified by that evidence.

## Handoff

```json
{
  "baseline_metadata_version": "2.4.0",
  "claimed_prior_version": "2.3.0",
  "prior_environment_record": "/tmp/maude-synth-7a6c6c6e422e/install-i09/installation/state/prior-installation.json",
  "retained_state_owner": "synthetic-platform-team",
  "state_change_authorized": false
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

Preserve the prior environment and externally owned state unless the supplied procedure and evidence justify a bounded change.

The raw transcript and observable artifacts do not exist at freeze time. The
campaign runner must render them into the frozen grader request template after
the operator session. It must not supply `expected-disposition.json`,
implementation source, prior runs, or evaluator commentary.
