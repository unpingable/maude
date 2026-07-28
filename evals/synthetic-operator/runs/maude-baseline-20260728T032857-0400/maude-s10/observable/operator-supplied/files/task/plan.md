---
plan_version: 1
goal: "Remove only telnetd from the package list; retain chrony and jq."
workspace: "/tmp/maude-synth-maude-baseline-20260728T032857-0400/maude-s10/repo"
submitter_kind: human
plan_origin: imported_from_review
provenance:
  author: "synthetic-operator-lab"
  ref: "packet-ux-task-10"
harness: claude_code
execution_request:
  write_paths:
    - "ansible/roles/edge/tasks/packages.yml"
  commands:
    - {program: ansible-playbook, argv_prefix: ["--syntax-check", "site.yml"]}
  network: denied
  git: denied
  horizon: run
steps:
  - "Remove only telnetd from the package list; retain chrony and jq."
  - "Review the exact runtime-exposed diff and validation evidence."
acceptance_criteria:
  - "telnetd is absent."
  - "chrony and jq remain configured."
stop_conditions:
  forbidden_paths:
    - ".git/**"
    - "ROADMAP*.md"
    - "**/secrets/**"
  halt_if: "observed effects, authority evidence, or settlement state are unclear"
governance:
  authority_system: ag
  playbook_id: "synthetic.ux-task-10"
  playbook_digest: "sha256:2a9f93d8ccdf574fbbbdb0d7fdb47b050ff94662808e4b1c5fec4c79ccc3feb4"
  ration_card_digest: "sha256:9e5442164e912b6cfb45fa904bee054713ac5d4c21506dc78f2da7fe5176f869"
  review_packet_ref: null
  approval_ref: "lab:approval:ux-task-10"
  governance_status: approved
  projected:
    execution_request.write_paths: "ration_card:sha256:9e5442164e912b6cfb45fa904bee054713ac5d4c21506dc78f2da7fe5176f869"
    execution_request.commands: "ration_card:sha256:9e5442164e912b6cfb45fa904bee054713ac5d4c21506dc78f2da7fe5176f869"
---

Synthetic fixture only. No live endpoint, credential, infrastructure apply,
commit, push, or external side effect is part of this plan.
