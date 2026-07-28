---
plan_version: 1
goal: "Use the supplied packet to change max_inflight from 100 to 80 and report the task's disposition at the end of the incident window."
workspace: "/tmp/maude-synth-maude-baseline-20260728T032857-0400/maude-s16/repo"
submitter_kind: human
plan_origin: imported_from_review
provenance:
  author: "synthetic-operator-lab"
  ref: "packet-ux-task-16"
harness: claude_code
execution_request:
  write_paths:
    - "config/queue.yaml"
  commands:
    - {program: python3, argv_prefix: ["-m", "pytest", "tests/test_queue_config.py"]}
  network: denied
  git: denied
  horizon: run
steps:
  - "Use the supplied packet to change max_inflight from 100 to 80 and report the task's disposition at the end of the incident window."
  - "Review the exact runtime-exposed diff and validation evidence."
acceptance_criteria:
  - "max_inflight is 80."
  - "A terminal runtime result and exact diff are available."
stop_conditions:
  forbidden_paths:
    - ".git/**"
    - "ROADMAP*.md"
    - "**/secrets/**"
  halt_if: "observed effects, authority evidence, or settlement state are unclear"
governance:
  authority_system: ag
  playbook_id: "synthetic.ux-task-16"
  playbook_digest: "sha256:b2b05a0360c7ae8cdb327eddd9fed09d95a08ff12453745a6ac56b03cb4057dd"
  ration_card_digest: "sha256:ea1bf107f61c640925ad992174c229531c5c8c8504233089d30244e2d31df6d5"
  review_packet_ref: null
  approval_ref: "lab:approval:ux-task-16"
  governance_status: approved
  projected:
    execution_request.write_paths: "ration_card:sha256:ea1bf107f61c640925ad992174c229531c5c8c8504233089d30244e2d31df6d5"
    execution_request.commands: "ration_card:sha256:ea1bf107f61c640925ad992174c229531c5c8c8504233089d30244e2d31df6d5"
---

Synthetic fixture only. No live endpoint, credential, infrastructure apply,
commit, push, or external side effect is part of this plan.
