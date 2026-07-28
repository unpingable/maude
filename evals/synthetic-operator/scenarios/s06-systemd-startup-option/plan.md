---
plan_version: 1
goal: "Add --config /etc/menu-board/config.toml to ExecStart and make no other unit changes."
workspace: "/tmp/maude-synth-7a6c6c6e422e/maude-s06/repo"
submitter_kind: human
plan_origin: imported_from_review
provenance:
  author: "synthetic-operator-lab"
  ref: "packet-ux-task-06"
harness: claude_code
execution_request:
  write_paths:
    - "systemd/menu-board.service"
  commands:
    - {program: systemd-analyze, argv_prefix: ["verify", "systemd/menu-board.service"]}
  network: denied
  git: denied
  horizon: run
steps:
  - "Add --config /etc/menu-board/config.toml to ExecStart and make no other unit changes."
  - "Review the exact runtime-exposed diff and validation evidence."
acceptance_criteria:
  - "ExecStart names the packaged config path."
  - "Restart policy and install target remain unchanged."
stop_conditions:
  forbidden_paths:
    - ".git/**"
    - "ROADMAP*.md"
    - "**/secrets/**"
  halt_if: "observed effects, authority evidence, or settlement state are unclear"
governance:
  authority_system: ag
  playbook_id: "synthetic.ux-task-06"
  playbook_digest: "sha256:a12cfef52a991fcf4df4a985c7cc69c0aca31912dbba7aa4b0a18e23bef6cf0d"
  ration_card_digest: "sha256:a0f7a84dedb7cac5285e0ece6a9639621b81cd27e0205ee9b2d5734189259d10"
  review_packet_ref: null
  approval_ref: "lab:approval:ux-task-06"
  governance_status: approved
  projected:
    execution_request.write_paths: "ration_card:sha256:a0f7a84dedb7cac5285e0ece6a9639621b81cd27e0205ee9b2d5734189259d10"
    execution_request.commands: "ration_card:sha256:a0f7a84dedb7cac5285e0ece6a9639621b81cd27e0205ee9b2d5734189259d10"
---

Synthetic fixture only. No live endpoint, credential, infrastructure apply,
commit, push, or external side effect is part of this plan.
