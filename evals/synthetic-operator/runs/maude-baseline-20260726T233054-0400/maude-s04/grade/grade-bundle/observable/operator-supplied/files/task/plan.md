---
plan_version: 1
goal: "Add an HTTP readiness probe on /ready port 8080 with a five-second initial delay."
workspace: "/tmp/maude-synth-maude-baseline-20260726T233054-0400/maude-s04/repo"
submitter_kind: human
plan_origin: imported_from_review
provenance:
  author: "synthetic-operator-lab"
  ref: "packet-ux-task-04"
harness: claude_code
execution_request:
  write_paths:
    - "deploy/menu-board/deployment.yaml"
  commands:
    - {program: kustomize, argv_prefix: ["build", "deploy/menu-board"]}
  network: denied
  git: denied
  horizon: run
steps:
  - "Add an HTTP readiness probe on /ready port 8080 with a five-second initial delay."
  - "Review the exact runtime-exposed diff and validation evidence."
acceptance_criteria:
  - "The readiness probe uses /ready on port 8080."
  - "The image and exposed port do not change."
stop_conditions:
  forbidden_paths:
    - ".git/**"
    - "ROADMAP*.md"
    - "**/secrets/**"
  halt_if: "observed effects, authority evidence, or settlement state are unclear"
governance:
  authority_system: ag
  playbook_id: "synthetic.ux-task-04"
  playbook_digest: "sha256:481a349972676e409e972b0b7d63ee34f6c27ea6d1afd563da5770d4ca1f1778"
  ration_card_digest: "sha256:77b144769a1bf3debf06c8252f9b0f05af5ec87f6bb96b8b7bd0435d0294169d"
  review_packet_ref: null
  approval_ref: "lab:approval:ux-task-04"
  governance_status: approved
  projected:
    execution_request.write_paths: "ration_card:sha256:77b144769a1bf3debf06c8252f9b0f05af5ec87f6bb96b8b7bd0435d0294169d"
    execution_request.commands: "ration_card:sha256:77b144769a1bf3debf06c8252f9b0f05af5ec87f6bb96b8b7bd0435d0294169d"
---

Synthetic fixture only. No live endpoint, credential, infrastructure apply,
commit, push, or external side effect is part of this plan.
