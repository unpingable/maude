# SPDX-License-Identifier: Apache-2.0
"""S4c — ``grant [session_id]`` — a crude READ-ONLY grant-lease diagnostic.

Instrumentation, not the UX cathedral: it shows the lease so an operator can see
whether a run's grant is active / revoked / expired and how it's been used,
while the semantics are fresh. No lease panel, no button taxonomy. One RPC
(``runtime.grant.get``); writes nothing.
"""

from __future__ import annotations

from maude.commands.base import Command, CommandContext
from maude.intents import IntentKind


class GrantStatusCommand(Command):
    """``grant [session_id]`` — grant-lease state + recent dispositions."""

    kinds = (IntentKind.GRANT_STATUS,)
    help = "grant-lease diagnostic for a session"

    async def execute(self, ctx: CommandContext, payload: str) -> None:
        log = ctx.log
        arg = payload.strip()
        session_id = arg if arg and arg.lower() != "grant" else None
        if session_id is None:
            session_id = getattr(ctx.app, "_active_supervised_session", None)
        if not session_id:
            log.write("[yellow]Usage: grant <session_id>  (or 'grant' during an active run)[/yellow]")
            return

        try:
            g = await ctx.app.client.runtime_grant_get(session_id)
        except Exception as exc:  # surface, never swallow
            log.write(f"[red]grant read unavailable:[/red] {exc}")
            return
        if not g:
            log.write(f"[dim]no execution grant attached to {session_id}[/dim]")
            return

        state = g.get("state", "active")
        colour = "green" if state == "active" else "red"
        log.write(
            f"grant [bold]{g.get('grant_id', '?')}[/bold]  "
            f"state: [{colour}]{state}[/{colour}]  ({g.get('enforcement', '?')})"
        )
        if g.get("revoked_reason"):
            log.write(f"  reason: {g['revoked_reason']}")

        writes = g.get("write_paths") or []
        cmds = [
            " ".join([c.get("program", "?"), *c.get("argv_prefix", [])])
            for c in (g.get("commands") or [])
        ]
        log.write(f"  scope: writes {', '.join(writes) or '—'}")
        log.write(f"         cmds {', '.join(cmds) or '—'}")
        exp = g.get("expires_after_ns")
        log.write(f"  horizon: {g.get('horizon', '?')}   expires_after_ns: {exp if exp is not None else '—'}")

        counts: dict[str, int] = {}
        for u in g.get("recent_uses") or []:
            key = u.get("disposition", "?")
            if key == "widens":
                key = f"widens:{u.get('axis', '?')}"
            elif key == "unverifiable":
                key = f"unverifiable:{u.get('reason', '?')}"
            counts[key] = counts.get(key, 0) + 1
        if counts:
            log.write("  recent uses: " + ", ".join(f"{k}×{v}" for k, v in counts.items()))
        else:
            log.write("  recent uses: none yet")
        log.write("  [dim](declared scope enforced by gate; substrate effects not yet armed)[/dim]")
