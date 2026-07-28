---
plan_version: 1
goal: "Use the supplied packet to change the worker image from 4.2.0 to 4.2.1 and report the resulting disposition."
workspace: "/tmp/maude-synth-maude-baseline-20260728T050937-0400/maude-s15/repo"
submitter_kind: human
plan_origin: imported_from_review
provenance:
  author: "synthetic-operator-lab"
  ref: "packet-ux-task-15"
harness: claude_code
execution_request:
  write_paths:
    - "deploy/worker.yaml"
  commands:
    - {program: git, argv_prefix: ["diff", "--check"]}
  network: denied
  git: denied
  horizon: run
steps:
  - "Use the supplied packet to change the worker image from 4.2.0 to 4.2.1 and report the resulting disposition."
  - "Review the exact runtime-exposed diff and validation evidence."
acceptance_criteria:
  - "The runtime admits dispatch."
  - "Only the image tag changes."
stop_conditions:
  forbidden_paths:
    - ".git/**"
    - "ROADMAP*.md"
    - "**/secrets/**"
  halt_if: "observed effects, authority evidence, or settlement state are unclear"
governance:
  authority_system: ag
  playbook_id: "synthetic.ux-task-15"
  playbook_digest: "sha256:d2b8fc602a4e926dc1cfaab2316f8bc9053bbf18a341bddd6d4456673ddbcd30"
  ration_card_digest: "sha256:d03b52b0c2ec32e434687e4fdd39625d54402b059482b559717010431df13ed6"
  review_packet_ref: null
  approval_ref: "lab:approval:ux-task-15"
  governance_status: approved
  projected:
    execution_request.write_paths: "ration_card:sha256:d03b52b0c2ec32e434687e4fdd39625d54402b059482b559717010431df13ed6"
    execution_request.commands: "ration_card:sha256:d03b52b0c2ec32e434687e4fdd39625d54402b059482b559717010431df13ed6"
---

Synthetic fixture only. No live endpoint, credential, infrastructure apply,
commit, push, or external side effect is part of this plan.
