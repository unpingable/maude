# Frozen grader assignment

**Campaign:** `maude-baseline-20260728T050937-0400`
**Run:** `install-i03`
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

**Task ID:** `install-task-03`
**Component:** `Maude`

## Situation

A clean Python 3.12 host has a filtered installable archive from the exact baseline Maude Git commit and no pre-populated Python package cache. Task network access is prohibited.

## Goal

Attempt the documented isolated source installation, determine whether it completed, and report the next safe operational action.

## Handoff

```json
{
  "baseline_source_archive": "/tmp/maude-synth-maude-baseline-20260728T050937-0400/install-i03/installation/media/maude-source.tar",
  "network_exception_available": false,
  "source_commit": "9d5a54f476a52826379a9ae8d6710551253a6493",
  "source_visibility_exception": "release-source"
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

A partial environment or an importable subset is not a completed installation.

The raw transcript and observable artifacts do not exist at freeze time. The
campaign runner must render them into the frozen grader request template after
the operator session. It must not supply `expected-disposition.json`,
implementation source, prior runs, or evaluator commentary.
