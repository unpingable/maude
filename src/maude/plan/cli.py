# SPDX-License-Identifier: Apache-2.0
"""Headless Plan Core CLI; structured output is suitable for future clients."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import Sequence

from maude.plan.compiler import CompilerRegistryV1, CompilerUnavailable
from maude.plan.diff import semantic_diff
from maude.plan.document import (
    PlanDocumentV1,
    PlanNodeV1,
    SubmitterV1,
    import_plan_envelope,
    new_node_id,
)
from maude.plan.envelope import parse_plan_envelope
from maude.plan.store import DraftRevisionV1, DraftStore, EditOrigin


def default_store_path() -> Path:
    configured = os.environ.get("MAUDE_PLAN_STORE")
    if configured:
        return Path(configured).expanduser()
    return Path.cwd() / ".maude" / "plans.sqlite"


def revision_payload(revision: DraftRevisionV1) -> dict:
    return {**revision.to_data(), "document": revision.document.to_data()}


def save_revision_bytes(
    store: DraftStore,
    draft_id: str,
    expected_revision_id: str,
    data: bytes,
    *,
    edit_origin: EditOrigin,
) -> DraftRevisionV1:
    """The sole human/agent document-write boundary."""
    document = PlanDocumentV1.parse(data)
    current = store.current(draft_id)
    if (
        current.revision_id == expected_revision_id
        and current.plan_digest == document.digest
    ):
        return current
    return store.save_successor(
        draft_id,
        expected_revision_id,
        document,
        edit_origin=edit_origin,
    )


def edit_with_editor(
    store: DraftStore,
    draft_id: str,
    *,
    editor: Sequence[str] | None = None,
    edit_origin: EditOrigin = EditOrigin.HUMAN,
) -> DraftRevisionV1:
    current = store.current(draft_id)
    command = (
        list(editor)
        if editor is not None
        else shlex.split(os.environ.get("EDITOR", "vi"))
    )
    if not command:
        raise ValueError("EDITOR command is empty")
    with tempfile.TemporaryDirectory(prefix="maude-plan-edit-") as directory:
        path = Path(directory) / f"{draft_id}.json"
        path.write_text(
            json.dumps(current.document.to_data(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        completed = subprocess.run([*command, str(path)], check=False)
        if completed.returncode != 0:
            raise RuntimeError(f"editor exited with status {completed.returncode}")
        return save_revision_bytes(
            store,
            draft_id,
            current.revision_id,
            path.read_bytes(),
            edit_origin=edit_origin,
        )


def _emit(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="maude-plan",
        description="Maude Plan Core: mutable design artifacts, not governed authority",
    )
    parser.add_argument("--store", type=Path, default=default_store_path())
    commands = parser.add_subparsers(dest="command", required=True)

    new = commands.add_parser("new", help="create a draft")
    new.add_argument("--goal", required=True)
    new.add_argument("--workspace", required=True)
    new.add_argument("--author", default=os.environ.get("USER", "operator"))
    new.add_argument(
        "--submitter-kind", choices=("human", "synthetic_agent"), default="human"
    )
    new.add_argument("--origin", default="human_written")
    new.add_argument("--draft-id")

    commands.add_parser("list", help="list current draft revisions")
    inspect = commands.add_parser(
        "inspect", help="inspect exact document/revision/receipts"
    )
    inspect.add_argument("draft_id")
    inspect.add_argument("--revision")

    check = commands.add_parser("check", help="run structural checks on exact bytes")
    check.add_argument("draft_id")
    check.add_argument("--revision")

    diff = commands.add_parser("diff", help="semantic diff between revisions")
    diff.add_argument("draft_id")
    diff.add_argument("--from-revision")
    diff.add_argument("--to-revision")
    diff.add_argument("--text", action="store_true")

    lock = commands.add_parser("lock", help="snapshot exact bytes; does not authorize")
    lock.add_argument("draft_id")
    lock.add_argument("--revision")

    edit = commands.add_parser(
        "edit", help="edit via $EDITOR and create a successor revision"
    )
    edit.add_argument("draft_id")

    save = commands.add_parser(
        "save", help="save supplied document as a successor revision"
    )
    save.add_argument("draft_id")
    save.add_argument("document", type=Path)
    save.add_argument("--expected-revision", required=True)
    save.add_argument(
        "--origin", choices=tuple(item.value for item in EditOrigin), required=True
    )

    imported = commands.add_parser(
        "import-envelope", help="explicitly import a PlanEnvelope"
    )
    imported.add_argument("path", type=Path)
    imported.add_argument("--draft-id")

    handoff = commands.add_parser(
        "handoff", help="compile a locked revision via an exact workflow"
    )
    handoff.add_argument("draft_id")
    handoff.add_argument("--workflow", required=True)
    return parser


def run(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = DraftStore(args.store)
    if args.command == "new":
        document = PlanDocumentV1(
            goal=args.goal,
            workspace=args.workspace,
            submitter=SubmitterV1(args.submitter_kind, args.origin, args.author),
            nodes=(PlanNodeV1(new_node_id(), args.goal),),
        )
        _emit(revision_payload(store.create(document, draft_id=args.draft_id)))
    elif args.command == "list":
        _emit({"drafts": [revision.to_data() for revision in store.list_drafts()]})
    elif args.command == "inspect":
        revision = (
            store.revision(args.revision)
            if args.revision
            else store.current(args.draft_id)
        )
        _emit(
            {
                **store.projection(args.draft_id).to_data(),
                "selected_revision": revision_payload(revision),
            }
        )
    elif args.command == "check":
        _emit(store.check(args.draft_id, args.revision).to_data())
    elif args.command == "diff":
        revisions = store.revisions(args.draft_id)
        if len(revisions) < 2 and not (args.from_revision and args.to_revision):
            raise RuntimeError("draft has only one revision; an exact diff needs two")
        before = (
            store.revision(args.from_revision) if args.from_revision else revisions[-2]
        )
        after = store.revision(args.to_revision) if args.to_revision else revisions[-1]
        result = semantic_diff(before.document, after.document)
        print(result.render()) if args.text else _emit(result.to_data())
    elif args.command == "lock":
        _emit(store.lock(args.draft_id, args.revision).to_data())
    elif args.command == "edit":
        _emit(revision_payload(edit_with_editor(store, args.draft_id)))
    elif args.command == "save":
        _emit(
            revision_payload(
                save_revision_bytes(
                    store,
                    args.draft_id,
                    args.expected_revision,
                    args.document.read_bytes(),
                    edit_origin=EditOrigin(args.origin),
                )
            )
        )
    elif args.command == "import-envelope":
        envelope = parse_plan_envelope(args.path.read_text(encoding="utf-8"))
        _emit(
            revision_payload(
                store.create(
                    import_plan_envelope(envelope),
                    draft_id=args.draft_id,
                    edit_origin=EditOrigin.IMPORT,
                )
            )
        )
    elif args.command == "handoff":
        current = store.current(args.draft_id)
        if not any(
            lock.revision_id == current.revision_id
            for lock in store.locks(args.draft_id)
        ):
            raise RuntimeError("current revision is not locked; handoff refuses")
        # No generic compiler is registered. Workflow packages add closed,
        # typed compilers; the CLI never interprets plan prose.
        registry = CompilerRegistryV1()
        try:
            registry.compile(args.workflow, current.document, _NoInputs())
        except CompilerUnavailable as error:
            _emit(
                {
                    "plan_digest": current.plan_digest,
                    "reason": str(error),
                    "result": "compiler_unavailable",
                    "workflow": args.workflow,
                }
            )
            return 2
    return 0


class _NoInputs:
    schema = "maude.compiler-input.none/v1"
    canonical_bytes = b'{"schema":"maude.compiler-input.none/v1"}'


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
