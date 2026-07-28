---
plan_version: 1
goal: "Correct the indentation of the Python setup step without changing triggers, permissions, or third-party action versions."
workspace: "/tmp/maude-synth-maude-baseline-20260728T032857-0400/maude-s02/repo"
submitter_kind: human
plan_origin: imported_from_review
provenance:
  author: "synthetic-operator-lab"
  ref: "packet-ux-task-02"
harness: claude_code
execution_request:
  write_paths:
    - ".github/workflows/verify.yml"
  commands:
    - {program: git, argv_prefix: ["diff", "--check"]}
  network: denied
  git: denied
  horizon: run
steps:
  - "Correct the indentation of the Python setup step without changing triggers, permissions, or third-party action versions."
  - "Review the exact runtime-exposed diff and validation evidence."
acceptance_criteria:
  - "Workflow YAML indentation is valid."
  - "Triggers, permissions, and action versions are unchanged."
stop_conditions:
  forbidden_paths:
    - ".git/**"
    - "ROADMAP*.md"
    - "**/secrets/**"
  halt_if: "observed effects, authority evidence, or settlement state are unclear"
governance:
  authority_system: ag
  playbook_id: "synthetic.ux-task-02"
  playbook_digest: "sha256:652f04a8cd1b6dc4b669c6e70d1c36f90d4a4ed87a907a0de13416d14ebb31f7"
  ration_card_digest: "sha256:67e96d3dd5632a9883bbc60ecad86c3aebd2a203afa59e3ea62e35143a2960f8"
  review_packet_ref: null
  approval_ref: "lab:approval:ux-task-02"
  governance_status: approved
  projected:
    execution_request.write_paths: "ration_card:sha256:67e96d3dd5632a9883bbc60ecad86c3aebd2a203afa59e3ea62e35143a2960f8"
    execution_request.commands: "ration_card:sha256:67e96d3dd5632a9883bbc60ecad86c3aebd2a203afa59e3ea62e35143a2960f8"
---

Synthetic fixture only. No live endpoint, credential, infrastructure apply,
commit, push, or external side effect is part of this plan.
