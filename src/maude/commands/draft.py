# SPDX-License-Identifier: Apache-2.0
"""Thin TUI lane over the same headless Plan Core store."""

from __future__ import annotations

import asyncio
import os
import shlex
from pathlib import Path

from maude.commands.base import Command, CommandContext
from maude.intents import IntentKind
from maude.plan.cli import default_store_path, edit_with_editor
from maude.plan.compiler import CompilerUnavailable
from maude.plan.diff import semantic_diff
from maude.plan.document import PlanDocumentV1, PlanNodeV1, SubmitterV1, new_node_id
from maude.plan.store import DraftStore


class DraftCommand(Command):
    kinds = (IntentKind.DRAFT,)
    help = "artifact-oriented draft workflow"

    @staticmethod
    def _store(ctx: CommandContext) -> DraftStore:
        configured = getattr(ctx.app.settings, "plan_store", "")
        if configured:
            path = Path(configured).expanduser()
        elif getattr(ctx.app.settings, "governor_dir", ""):
            project = Path(ctx.app.settings.governor_dir).expanduser()
            if project.name == ".governor":
                project = project.parent
            path = project / ".maude" / "plans.sqlite"
        else:
            path = default_store_path()
        return DraftStore(path)

    @staticmethod
    def _workspace(ctx: CommandContext) -> str:
        configured = getattr(ctx.app.settings, "governor_dir", "")
        if not configured:
            return os.getcwd()
        project = Path(configured).expanduser()
        return str(project.parent if project.name == ".governor" else project)

    async def execute(self, ctx: CommandContext, payload: str) -> None:
        try:
            parts = shlex.split(payload)
        except ValueError as error:
            ctx.log.write(f"[red]Draft command error:[/red] {error}")
            return
        if not parts:
            ctx.log.write("[bold]Draft artifacts[/bold]")
            ctx.log.write("  draft new <goal> · list · inspect <id> · edit <id>")
            ctx.log.write(
                "  draft check <id> · diff <id> · lock <id> · handoff <id> <workflow>"
            )
            ctx.log.write("[dim]Draft validity is not governed admissibility.[/dim]")
            return
        operation, *arguments = parts
        try:
            store = self._store(ctx)
            if operation == "new":
                goal = " ".join(arguments).strip()
                if not goal:
                    raise ValueError("usage: draft new <goal>")
                workspace = self._workspace(ctx)
                revision = store.create(
                    PlanDocumentV1(
                        goal=goal,
                        workspace=workspace,
                        submitter=SubmitterV1(
                            "human", "human_written", os.environ.get("USER", "operator")
                        ),
                        nodes=(PlanNodeV1(new_node_id(), goal),),
                    )
                )
                ctx.log.write(f"[green]Draft created[/green] {revision.draft_id}")
                ctx.log.write(f"  revision {revision.ordinal} · {revision.plan_digest}")
                ctx.log.write(
                    "[dim]A stable initial PlanNode was created. Use draft edit, then draft check.[/dim]"
                )
            elif operation == "list":
                drafts = store.list_drafts()
                if not drafts:
                    ctx.log.write("[dim]No Plan Core drafts.[/dim]")
                for revision in drafts:
                    ctx.log.write(
                        f"  [bold]{revision.draft_id}[/bold] r{revision.ordinal} "
                        f"{revision.plan_digest[:19]}… · {revision.document.goal}"
                    )
            elif operation == "inspect" and len(arguments) == 1:
                projection = store.projection(arguments[0])
                current = projection.current
                ctx.log.write(
                    f"[bold]{current.draft_id}[/bold] revision {current.ordinal}"
                )
                ctx.log.write(f"  digest: {current.plan_digest}")
                ctx.log.write(f"  goal: {current.document.goal}")
                ctx.log.write(f"  nodes: {len(current.document.nodes)}")
                ctx.log.write(
                    f"  check applicability: {projection.check_summary.value}"
                )
                ctx.log.write(f"  locks retained: {len(projection.locks)}")
            elif operation == "edit" and len(arguments) == 1:
                revision = await asyncio.to_thread(
                    edit_with_editor, store, arguments[0]
                )
                ctx.log.write(
                    f"[green]Current revision[/green] r{revision.ordinal} · {revision.plan_digest}"
                )
            elif operation == "check" and len(arguments) == 1:
                receipt = store.check(arguments[0])
                tone = "green" if receipt.result == "passed" else "yellow"
                ctx.log.write(
                    f"[{tone}]Check {receipt.result}[/{tone}] · {receipt.plan_digest} · "
                    f"{len(receipt.findings)} finding(s)"
                )
                for finding in receipt.findings[:12]:
                    target = finding.target.node_id or "document"
                    ctx.log.write(f"  {finding.rule_id} [{target}] {finding.message}")
            elif operation == "diff" and len(arguments) == 1:
                revisions = store.revisions(arguments[0])
                if len(revisions) < 2:
                    raise ValueError("draft has only one revision")
                for line in (
                    semantic_diff(revisions[-2].document, revisions[-1].document)
                    .render()
                    .splitlines()
                ):
                    ctx.log.write(line)
            elif operation == "lock" and len(arguments) == 1:
                receipt = store.lock(arguments[0])
                ctx.log.write(f"[green]Locked exact bytes[/green] {receipt.lock_id}")
                ctx.log.write(f"  plan digest: {receipt.plan_digest}")
                ctx.log.write("[dim]Locking exact bytes does not authorize them.[/dim]")
            elif operation == "handoff" and len(arguments) == 2:
                current = store.current(arguments[0])
                if not any(
                    lock.revision_id == current.revision_id
                    for lock in store.locks(arguments[0])
                ):
                    raise ValueError("current revision is not locked")
                raise CompilerUnavailable(
                    f"compiler unavailable for workflow {arguments[1]!r}; no prose is inferred"
                )
            else:
                raise ValueError(
                    "usage: draft new <goal> | list | inspect/edit/check/diff/lock <id> | "
                    "handoff <id> <workflow>"
                )
        except (OSError, RuntimeError, ValueError, KeyError) as error:
            ctx.log.write(f"[red]Draft refused:[/red] {error}")
