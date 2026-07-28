---
plan_version: 1
goal: "Change only the menu-api container image from 2.7.3 to 2.7.4 in the Store 17 GitOps deployment."
workspace: "/tmp/maude-synth-maude-baseline-20260726T233054-0400/maude-s01/repo"
submitter_kind: human
plan_origin: imported_from_review
provenance:
  author: "synthetic-operator-lab"
  ref: "packet-ux-task-01"
harness: claude_code
execution_request:
  write_paths:
    - "clusters/store-17/apps/menu/deployment.yaml"
  commands:
    - {program: kustomize, argv_prefix: ["build", "clusters/store-17"]}
  network: denied
  git: denied
  horizon: run
steps:
  - "Change only the menu-api container image from 2.7.3 to 2.7.4 in the Store 17 GitOps deployment."
  - "Review the exact runtime-exposed diff and validation evidence."
acceptance_criteria:
  - "The only semantic change is image tag 2.7.3 to 2.7.4."
  - "The rendered manifests remain valid."
stop_conditions:
  forbidden_paths:
    - ".git/**"
    - "ROADMAP*.md"
    - "**/secrets/**"
  halt_if: "observed effects, authority evidence, or settlement state are unclear"
governance:
  authority_system: ag
  playbook_id: "synthetic.ux-task-01"
  playbook_digest: "sha256:6a8f8bdbb4c08ab9adf7bc6b05c14d6d1f173839c0d62a5bd8c3f0ff15fda84e"
  ration_card_digest: "sha256:9f5e92ab790a1bd12fb009ce52b3a4bfb2d4151a24d0ab18c6505ae6f354635a"
  review_packet_ref: null
  approval_ref: "lab:approval:ux-task-01"
  governance_status: approved
  projected:
    execution_request.write_paths: "ration_card:sha256:9f5e92ab790a1bd12fb009ce52b3a4bfb2d4151a24d0ab18c6505ae6f354635a"
    execution_request.commands: "ration_card:sha256:9f5e92ab790a1bd12fb009ce52b3a4bfb2d4151a24d0ab18c6505ae6f354635a"
---

Synthetic fixture only. No live endpoint, credential, infrastructure apply,
commit, push, or external side effect is part of this plan.
