# SPDX-License-Identifier: Apache-2.0
"""M-2 `run <plan.md>` — parse, validate, admit, map to a supervised run.

The human ingress path. Maude validates a plan's SHAPE and maps it to a
supervised session; format validation is not authority — AG's gates refuse
forbidden actions regardless of how well-formed the plan is. Synthetic-agent
envelopes parse here but ride the same mapping with a non-interactive
posture; their dedicated batch ingress (exit codes, ``--out``) is M-7.

Governed plans admit only per §7 (approved + every load-bearing citation
witnessed). v0 ships with NO witness resolver wired: governed plans refuse
fail-closed until the AG conveyor projection surface lands (CD-4 wires it).
"""

from __future__ import annotations

from pathlib import Path

from maude.commands.base import Command, CommandContext
from maude.intents import IntentKind
from maude.labels import refusal_explanation
from maude.plan.envelope import (
    PlanEnvelope,
    PlanRefusal,
    WitnessResolver,
    admit_for_execution,
    parse_plan_envelope,
)


def compose_task_text(env: PlanEnvelope) -> str:
    """Goal + advisory steps + prose body, verbatim — Maude never reorders or
    invents steps (M-1 §2)."""
    parts = [env.goal]
    if env.steps:
        parts.append("Steps (advisory, ordered):\n" + "\n".join(f"- {s}" for s in env.steps))
    body = env.body.strip()
    if body:
        parts.append(body)
    return "\n\n".join(parts)


class RunPlanCommand(Command):
    """``run <plan.md>`` — the M-2 plan runner (human path)."""

    kinds = (IntentKind.RUN_PLAN,)
    help = "run a plan file"

    def __init__(self, witness_resolver: WitnessResolver | None = None) -> None:
        # Injected for tests; when absent, execute() defaults to a file
        # resolver over the PLAN FILE'S OWN DIRECTORY — witnesses co-located
        # with the plan (the CD-4 specimen layout). Fail-closed is preserved:
        # a directory with no matching artifacts resolves nothing and governed
        # plans refuse (a status field is never its own evidence).
        self._witness_resolver = witness_resolver

    async def execute(self, ctx: CommandContext, payload: str) -> None:
        log = ctx.log
        # Reset the `why` law-view stash per run; set again only if this run blocks.
        ctx.app._last_plan_block = None
        # ``run <plan.md> [--model <name>]`` — the model pin is the OPERATOR'S
        # spend choice at run time; it never lives in the plan envelope (a plan
        # must not dictate spend). NS-0, nightshift-functional-mvp.
        tokens = payload.strip().split()
        model: str | None = None
        if "--model" in tokens:
            i = tokens.index("--model")
            if i + 1 >= len(tokens):
                log.write("[red]--model needs a value[/red] (e.g. --model claude-haiku-4-5)")
                return
            model = tokens[i + 1]
            del tokens[i : i + 2]
        path = Path(" ".join(tokens)).expanduser()
        if not path.is_file():
            log.write(f"[red]Plan file not found:[/red] {path}")
            return
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            log.write(f"[red]Cannot read plan:[/red] {exc}")
            return

        resolver = self._witness_resolver
        if resolver is None:
            from maude.plan.witness import file_witness_resolver

            resolver = file_witness_resolver(path.parent)

        try:
            env = parse_plan_envelope(text)
            admission = admit_for_execution(env, witness_resolver=resolver)
        except PlanRefusal as refusal:
            # Typed, client-side, NOT authority. No session created. The surface
            # stays plain-ops; the raw refusal code is stashed for the `why`
            # law-view drilldown (progressive disclosure).
            exp = refusal_explanation(refusal.refusal_class, refusal.detail)
            log.write(f"[red]Blocked:[/red] {exp.surface}")
            log.write(f"  {exp.detail}")
            log.write("  [dim]type 'why' for the policy detail[/dim]")
            ctx.app._last_plan_block = (refusal.refusal_class, refusal.detail, exp)
            return

        for w in env.warnings:
            log.write(f"[yellow]note:[/yellow] {w}")

        backend_kind = env.harness or "claude_code"
        operator_mode = "interactive" if env.submitter_kind == "human" else "autonomous"
        task = compose_task_text(env)

        log.write(f"[bold]OK — starting run[/bold]  (plan {env.plan_ref[:14]}…)")
        if admission.governed:
            log.write(
                "  policy: approved; verified references: "
                + ", ".join(name for name, _ in admission.verified)
            )
            for fld, src in (env.governance.projected or {}).items():
                log.write(f"  limit '{fld}' enforced from {src}")
        else:
            log.write("  policy: none (plain run, no sign-off attached)")
        if env.stop_forbidden_paths:
            log.write(
                "  local guard — off-limits paths: "
                + ", ".join(env.stop_forbidden_paths)
            )
        if env.stop_halt_if:
            log.write(
                f"  stop if: {env.stop_halt_if}  "
                "[dim](a reminder for you, not auto-enforced)[/dim]"
            )

        # A governed plan's flip (queue latch, approval-witness file, plan
        # promotion) inherently dirties the workspace before the run — those
        # edits ARE the citations the admission just verified. Launch with the
        # pre-existing dirty set FENCED (session-attributable promotion, GAP-N):
        # the run refuses nothing on account of them, and they stay excluded
        # from the run's promote/discard, so a discard can never revert the
        # operator's own approval acts.
        allow_dirty = admission.governed
        if allow_dirty:
            log.write(
                "  [dim]pre-existing changes are fenced from this run's "
                "keep/discard (they include your approval acts)[/dim]"
            )

        try:
            harness_args = ["--model", model] if model else []
            if model:
                log.write(f"  model pinned: {model} (operator's choice, not the plan's)")
            result = await ctx.app.client.runtime_session_create(
                backend_kind=backend_kind,
                cwd=env.workspace,
                task=task,
                operator_mode=operator_mode,
                allow_dirty=allow_dirty,
                harness_args=harness_args,
            )
            session_id = result["session_id"]
            log.write(f"[green]Run started:[/green] {session_id}")
            launch = await ctx.app.client.runtime_session_launch(session_id)
            log.write(f"  Status: {launch['status']}  PID: {launch.get('pid', '?')}")
            log.write(f"  plan_ref recorded: {env.plan_ref}")
            log.write(
                "[dim]Acceptance criteria render UNCHECKED in the run report "
                "(M-4); the reviewer judges.[/dim]"
            )
        except Exception as exc:  # daemon/transport errors surface verbatim
            log.write(f"[red]Launch error:[/red] {exc}")
            return

        # Same bookkeeping as supervised launch (best-effort on fakes).
        app = ctx.app
        if hasattr(app, "_active_supervised_session"):
            app._active_supervised_session = session_id
        session = getattr(app, "session", None)
        if session is not None and hasattr(session, "active_supervised_id"):
            session.active_supervised_id = session_id
        for hook in ("_update_status_bar", "_start_intervention_poll"):
            fn = getattr(app, hook, None)
            if callable(fn):
                fn()
