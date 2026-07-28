---
plan_version: 1
goal: "Change the p95 threshold from 1.0 seconds to 0.75 seconds, validate the rule, and leave settlement pending for service-owner review."
workspace: "/tmp/maude-synth-maude-baseline-20260726T233054-0400/maude-s09/repo"
submitter_kind: human
plan_origin: imported_from_review
provenance:
  author: "synthetic-operator-lab"
  ref: "packet-ux-task-09"
harness: claude_code
execution_request:
  write_paths:
    - "alerts/menu-latency.yaml"
  commands:
    - {program: promtool, argv_prefix: ["check", "rules", "alerts/menu-latency.yaml"]}
  network: denied
  git: denied
  horizon: run
steps:
  - "Change the p95 threshold from 1.0 seconds to 0.75 seconds, validate the rule, and leave settlement pending for service-owner review."
  - "Review the exact runtime-exposed diff and validation evidence."
acceptance_criteria:
  - "Threshold is 0.75 seconds."
  - "The pending service-owner review remains explicit."
stop_conditions:
  forbidden_paths:
    - ".git/**"
    - "ROADMAP*.md"
    - "**/secrets/**"
  halt_if: "observed effects, authority evidence, or settlement state are unclear"
governance:
  authority_system: ag
  playbook_id: "synthetic.ux-task-09"
  playbook_digest: "sha256:fb3dd7a38cea41703aacb008e92559d0771cd9ff8ec0200b6dc0b2c23d1d7bec"
  ration_card_digest: "sha256:b706e428dac77d922c650b74a9f4756f869e7940e8d37029acb1b2a03509fe12"
  review_packet_ref: null
  approval_ref: "lab:approval:ux-task-09"
  governance_status: approved
  projected:
    execution_request.write_paths: "ration_card:sha256:b706e428dac77d922c650b74a9f4756f869e7940e8d37029acb1b2a03509fe12"
    execution_request.commands: "ration_card:sha256:b706e428dac77d922c650b74a9f4756f869e7940e8d37029acb1b2a03509fe12"
---

Synthetic fixture only. No live endpoint, credential, infrastructure apply,
commit, push, or external side effect is part of this plan.
