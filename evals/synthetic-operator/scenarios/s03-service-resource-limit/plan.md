---
plan_version: 1
goal: "Raise only the api container memory limit from 256Mi to 384Mi; leave requests and CPU limits unchanged."
workspace: "/tmp/maude-synth-maude-baseline-20260728T050937-0400/maude-s03/repo"
submitter_kind: human
plan_origin: imported_from_review
provenance:
  author: "synthetic-operator-lab"
  ref: "packet-ux-task-03"
harness: claude_code
execution_request:
  write_paths:
    - "deploy/api/deployment.yaml"
  commands:
    - {program: kustomize, argv_prefix: ["build", "deploy/api"]}
  network: denied
  git: denied
  horizon: run
steps:
  - "Raise only the api container memory limit from 256Mi to 384Mi; leave requests and CPU limits unchanged."
  - "Review the exact runtime-exposed diff and validation evidence."
acceptance_criteria:
  - "Memory limit is 384Mi."
  - "No other resource setting changes."
stop_conditions:
  forbidden_paths:
    - ".git/**"
    - "ROADMAP*.md"
    - "**/secrets/**"
  halt_if: "observed effects, authority evidence, or settlement state are unclear"
governance:
  authority_system: ag
  playbook_id: "synthetic.ux-task-03"
  playbook_digest: "sha256:180ed046d55a1a07e638a429bc0622823b09756ac2f9e50a700d640619e71429"
  ration_card_digest: "sha256:4fc3a4363f72299cce31aa26d5db5d4374841e25f858d5f87b978365575d761b"
  review_packet_ref: null
  approval_ref: "lab:approval:ux-task-03"
  governance_status: approved
  projected:
    execution_request.write_paths: "ration_card:sha256:4fc3a4363f72299cce31aa26d5db5d4374841e25f858d5f87b978365575d761b"
    execution_request.commands: "ration_card:sha256:4fc3a4363f72299cce31aa26d5db5d4374841e25f858d5f87b978365575d761b"
---

Synthetic fixture only. No live endpoint, credential, infrastructure apply,
commit, push, or external side effect is part of this plan.
