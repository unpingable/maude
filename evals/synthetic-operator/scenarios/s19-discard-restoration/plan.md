---
plan_version: 1
goal: "Change cache_ttl_seconds from 5 to 10, inspect the resulting candidate, and choose the supported final disposition."
workspace: "/tmp/maude-synth-7a6c6c6e422e/maude-s19/repo"
submitter_kind: human
plan_origin: imported_from_review
provenance:
  author: "synthetic-operator-lab"
  ref: "packet-ux-task-19"
harness: claude_code
execution_request:
  write_paths:
    - "config/cache.yaml"
  commands:
    - {program: git, argv_prefix: ["diff", "--check"]}
  network: denied
  git: denied
  horizon: run
steps:
  - "Change cache_ttl_seconds from 5 to 10, inspect the resulting candidate, and choose the supported final disposition."
  - "Review the exact runtime-exposed diff and validation evidence."
acceptance_criteria:
  - "cache_ttl_seconds is exactly 10."
  - "Discard restores cache_ttl_seconds to 5."
stop_conditions:
  forbidden_paths:
    - ".git/**"
    - "ROADMAP*.md"
    - "**/secrets/**"
  halt_if: "observed effects, authority evidence, or settlement state are unclear"
governance:
  authority_system: ag
  playbook_id: "synthetic.ux-task-19"
  playbook_digest: "sha256:e583b98f8ee0e8e0a98a1cf8299caf25352ea095cc234aabd460a0ce3129963d"
  ration_card_digest: "sha256:3aa4ad30af8b17a585b79a688f232e6b5cf0a8a26439aaf3b85a6a223a2ff6da"
  review_packet_ref: null
  approval_ref: "lab:approval:ux-task-19"
  governance_status: approved
  projected:
    execution_request.write_paths: "ration_card:sha256:3aa4ad30af8b17a585b79a688f232e6b5cf0a8a26439aaf3b85a6a223a2ff6da"
    execution_request.commands: "ration_card:sha256:3aa4ad30af8b17a585b79a688f232e6b5cf0a8a26439aaf3b85a6a223a2ff6da"
---

Synthetic fixture only. No live endpoint, credential, infrastructure apply,
commit, push, or external side effect is part of this plan.
