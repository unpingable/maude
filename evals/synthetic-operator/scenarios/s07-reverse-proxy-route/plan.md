---
plan_version: 1
goal: "Point /order-history/ at order-history-v2:8080 while preserving path and headers."
workspace: "/tmp/maude-synth-7a6c6c6e422e/maude-s07/repo"
submitter_kind: human
plan_origin: imported_from_review
provenance:
  author: "synthetic-operator-lab"
  ref: "packet-ux-task-07"
harness: claude_code
execution_request:
  write_paths:
    - "nginx/routes.conf"
  commands:
    - {program: nginx, argv_prefix: ["-p", ".", "-t", "-c", "nginx/nginx.conf"]}
  network: denied
  git: denied
  horizon: run
steps:
  - "Point /order-history/ at order-history-v2:8080 while preserving path and headers."
  - "Review the exact runtime-exposed diff and validation evidence."
acceptance_criteria:
  - "Only the upstream service name changes."
  - "The route and request-ID header remain intact."
stop_conditions:
  forbidden_paths:
    - ".git/**"
    - "ROADMAP*.md"
    - "**/secrets/**"
  halt_if: "observed effects, authority evidence, or settlement state are unclear"
governance:
  authority_system: ag
  playbook_id: "synthetic.ux-task-07"
  playbook_digest: "sha256:4382c12bb8f4b86276501cb146c343927a46ff76e8dd9ae05193026767078a0d"
  ration_card_digest: "sha256:ec1da4f2988fc536920833f01ef68bd364bffdf88a33054c2397cbf2bf9088e4"
  review_packet_ref: null
  approval_ref: "lab:approval:ux-task-07"
  governance_status: approved
  projected:
    execution_request.write_paths: "ration_card:sha256:ec1da4f2988fc536920833f01ef68bd364bffdf88a33054c2397cbf2bf9088e4"
    execution_request.commands: "ration_card:sha256:ec1da4f2988fc536920833f01ef68bd364bffdf88a33054c2397cbf2bf9088e4"
---

Synthetic fixture only. No live endpoint, credential, infrastructure apply,
commit, push, or external side effect is part of this plan.
