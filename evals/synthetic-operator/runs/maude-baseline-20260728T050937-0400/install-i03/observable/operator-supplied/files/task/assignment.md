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
