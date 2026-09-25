#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Write synthetic reviewed-local-copy fixtures for the clean-VM gate.

Runs on the qualification host with ``PYTHONPATH`` pointing at the pinned Maude
``src`` (d0f1375). The fixtures are synthetic test data. Every path they bind
is under ``--guest-root``, where the gate copies them. Nothing here is shipped.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from maude.plan.document import (
    DocumentConstraintsV1,
    PlanDocumentV1,
    PlanNodeV1,
    StructuredWorkV1,
    SubmitterV1,
    canonical_json_bytes,
    content_digest,
)
from maude.plan.local_compose import ag_executor_plan_identity
from maude.plan.reviewed_local_copy import (
    BINDING_SCHEMA,
    COMPILER_CONTRACT,
    ReviewedLocalCopyInputsV1,
    ReviewedLocalCopyValidatorConfigV1,
    compile_and_bind_reviewed_local_copy,
)
from maude.plan.store import DraftStore

TEXT = b"synthetic reviewed text for the Maude clean-VM gate\n"
OCCURRENCE = "0a1e0000-0000-4000-8000-000000000001"


def d(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode()).hexdigest()


def now() -> datetime:
    return datetime(2026, 9, 25, tzinfo=UTC)


def document(goal: str) -> PlanDocumentV1:
    return PlanDocumentV1(
        goal=goal,
        workspace="exclusive-scratch",
        submitter=SubmitterV1("synthetic_agent", "imported_from_review", "maude-vm-gate"),
        nodes=(PlanNodeV1("pn_copy", "Copy exact reviewed text", work=StructuredWorkV1(("result.txt",))),),
        constraints=DocumentConstraintsV1(declared_write_paths=("result.txt",)),
        acceptance_criteria=("result.txt equals reviewed source bytes",),
    )


def inputs(scratch: str, text: bytes = TEXT) -> ReviewedLocalCopyInputsV1:
    return ReviewedLocalCopyInputsV1(
        d("campaign"), OCCURRENCE, d("program"), d("subject"), d("scope"), scratch, d("observation"), text
    )


def bind(store: DraftStore, draft: str, goal: str, scratch: str) -> bytes:
    revision = store.create(document(goal), draft_id=draft)
    assert store.check(revision.draft_id).result == "passed"
    store.lock(revision.draft_id)
    return compile_and_bind_reviewed_local_copy(store, draft, inputs(scratch))


def rebind(binding: dict) -> bytes:
    unsigned = {key: value for key, value in binding.items() if key != "binding_id"}
    binding["binding_id"] = content_digest(BINDING_SCHEMA.encode() + b"\0" + canonical_json_bytes(unsigned))
    return canonical_json_bytes(binding) + b"\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--guest-root", default="/home/maudeacceptor/fx")
    args = parser.parse_args()
    out: Path = args.out
    out.mkdir(parents=True)
    root = args.guest_root
    store = DraftStore(out / "plans.sqlite", now=now)
    plans = {}
    for name, draft in (("main", "a"), ("existing", "b"), ("fresh", "c")):
        raw = bind(store, "draft_" + draft * 32, f"Copy reviewed synthetic text ({name})", f"{root}/scratch-{name}")
        plans[name] = json.loads(raw)
        if name == "main":
            (out / "binding.json").write_bytes(raw + b"\n")
    # A second store holding the same draft id with a different document.
    other = DraftStore(out / "other.sqlite", now=now)
    bind(other, "draft_" + "a" * 32, "A different synthetic plan", f"{root}/scratch-main")

    write = lambda name, data: (out / name).write_bytes(data)  # noqa: E731
    write("validator-config.json", ReviewedLocalCopyValidatorConfigV1(f"{root}/plans.sqlite").canonical_bytes + b"\n")
    write("validator-config-other-store.json",
          ReviewedLocalCopyValidatorConfigV1(f"{root}/other.sqlite").canonical_bytes + b"\n")

    main_binding = plans["main"]
    outer = json.loads(json.dumps(main_binding))
    outer["occurrence"] = "0a1e0000-0000-4000-8000-000000000002"  # binding_id left stale
    write("binding-outer-tampered.json", canonical_json_bytes(outer) + b"\n")
    inner = json.loads(json.dumps(main_binding))
    swapped = inputs(f"{root}/scratch-main", b"substituted text that was never reviewed\n").canonical_bytes
    inner["artifacts"]["compiler_inputs"] = {
        "sha256": content_digest(swapped), "byte_length": len(swapped),
        "bytes_base64": base64.b64encode(swapped).decode("ascii"),
    }
    write("binding-inner-tampered.json", rebind(inner))
    write("binding-noncanonical.json", json.dumps(main_binding, indent=1).encode() + b"\n")

    works = {}
    for name, binding in plans.items():
        plan_bytes = base64.b64decode(binding["artifacts"]["executor_plan"]["bytes_base64"])
        plan = json.loads(plan_bytes)
        works[name] = ag_executor_plan_identity(plan)
        assert works[name] == binding["work"]
        config = {"executor_plan_base64": base64.b64encode(plan_bytes).decode("ascii"),
                  "schema": "maude.reviewed-local-copy.executor-config/v1", "state_root": f"{root}/state"}
        write(f"executor-config-{name}.json", canonical_json_bytes(config) + b"\n")
        if name == "main":
            tampered = dict(plan)
            tampered["reviewed_text_base64"] = base64.b64encode(b"substituted text that was never reviewed\n").decode("ascii")
            config_t = dict(config, executor_plan_base64=base64.b64encode(canonical_json_bytes(tampered)).decode("ascii"))
            write("executor-config-tampered.json", canonical_json_bytes(config_t) + b"\n")

    def dispatch(name: str, attempt: str, work: str | None = None) -> bytes:
        binding = plans[name]
        return canonical_json_bytes({
            "attempt": d(f"attempt-{attempt}"), "marker": d(f"marker-{attempt}"),
            "scope": binding["scope"], "subject": binding["subject"],
            "work": work or works[name], "work_schema": COMPILER_CONTRACT,
        })

    write("dispatch-main-a.json", dispatch("main", "main-a"))
    write("dispatch-main-b.json", dispatch("main", "main-b"))
    write("dispatch-mismatch.json", dispatch("main", "mismatch", work=works["fresh"]))
    write("dispatch-existing.json", dispatch("existing", "existing"))
    write("dispatch-fresh.json", dispatch("fresh", "fresh"))
    facts = {"reviewed_text_sha256": hashlib.sha256(TEXT).hexdigest(), "reviewed_text_bytes": len(TEXT),
             "works": works, "binding_id": main_binding["binding_id"], "guest_root": root,
             "files": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(out.iterdir())}}
    write("FIXTURES.json", (json.dumps(facts, indent=2, sort_keys=True) + "\n").encode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
