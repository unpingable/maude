---
plan_version: 1
goal: "Update apps/menu/deployment.yaml from menu-api:2.7.3 to menu-api:2.7.4."
workspace: "/tmp/maude-synth-maude-baseline-20260728T050937-0400/maude-s11/repo"
submitter_kind: human
plan_origin: imported_from_review
provenance:
  author: "synthetic-operator-lab"
  ref: "packet-ux-task-11"
harness: claude_code
execution_request:
  write_paths:
    - "apps/**"
  commands:
    - {program: git, argv_prefix: ["diff", "--check"]}
  network: denied
  git: denied
  horizon: run
steps:
  - "Update apps/menu/deployment.yaml from menu-api:2.7.3 to menu-api:2.7.4."
  - "Review the exact runtime-exposed diff and validation evidence."
acceptance_criteria:
  - "The described menu image is updated."
  - "No other application manifest changes."
stop_conditions:
  forbidden_paths:
    - ".git/**"
    - "ROADMAP*.md"
    - "**/secrets/**"
  halt_if: "observed effects, authority evidence, or settlement state are unclear"
governance:
  authority_system: ag
  playbook_id: "synthetic.ux-task-11"
  playbook_digest: "sha256:63e284a0cee639596b7558c53292edd03e7c1aafb2a7c11cd66f436d86a65ea3"
  ration_card_digest: "sha256:3bc911fc52d4623ea579900126cd680c5eccd7dcce638ae9173fb57944c5e64d"
  review_packet_ref: null
  approval_ref: "lab:approval:ux-task-11"
  governance_status: approved
  projected:
    execution_request.write_paths: "ration_card:sha256:3bc911fc52d4623ea579900126cd680c5eccd7dcce638ae9173fb57944c5e64d"
    execution_request.commands: "ration_card:sha256:3bc911fc52d4623ea579900126cd680c5eccd7dcce638ae9173fb57944c5e64d"
---

Synthetic fixture only. No live endpoint, credential, infrastructure apply,
commit, push, or external side effect is part of this plan.
