# SPDX-License-Identifier: Apache-2.0
"""Maude TUI application - Textual frontend for the agent-governor."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, Input, RichLog

from maude import __version__
from maude.client.rpc import GovernorClient
from maude.client.models import SessionSummary
from maude.config import Settings
from maude.intents import IntentKind, parse_intent
from maude.session import MaudeSession, Mode
from maude.ui.widgets import GovernorStatusBar

_CSS_PATH = Path(__file__).parent / "ui" / "theme.tcss"
_TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "templates"
_TEMPLATE_MAP = {
    "architecture": "ARCHITECTURE_TEMPLATE.md",
    "arch": "ARCHITECTURE_TEMPLATE.md",
    "product": "PRODUCT_DESIGN_TEMPLATE.md",
    "product design": "PRODUCT_DESIGN_TEMPLATE.md",
    "requirements": "REQUIREMENTS_TEMPLATE.md",
    "reqs": "REQUIREMENTS_TEMPLATE.md",
}

_HELP_TEXT = """\
[bold]Available commands:[/bold]
  plan <text>   - Start planning (freeform)
  plan architecture / arch - Load architecture template
  plan product / product design - Load product design template
  plan requirements / reqs - Load requirements template
  clear template - Unload the current template
  lock spec     - Lock the current spec (submits constraint to governor)
  build         - Switch to BUILD mode (creates v2 run)
  show spec     - Show the current spec draft
  diff          - Show changes (supervised: workspace diff, governance: pending violation)
  apply/promote - Accept changes (supervised: promote, governance: proceed with override)
  rollback/reject - Revert (supervised: reject changes, governance: fix violation)
  why           - Show why something is blocked
  status        - Show governor status
  sessions      - List all sessions (also: ls, list sessions)
  switch <id>   - Switch to a session by ID or #N (also: session <id>, resume <id>)
  delete session <id> - Delete a session (also: rm session <id>)

[bold]Supervised agent sessions:[/bold]
  supervised launch [task]        - Launch a supervised Claude session
  supervised list                 - List supervised sessions
  supervised events <id>          - Show session events
  supervised interventions <id>   - Show pending approvals
  supervised approve <id> <tcid>  - Approve a tool call
  supervised deny <id> <tcid>     - Deny a tool call
  supervised kill <id>            - Kill a session
  supervised promotion <id>       - Show pending promotion (changed files)
  supervised diff <id>            - Show unified diff of changes
  supervised promote <id>         - Accept workspace changes
  supervised reject <id>          - Revert workspace changes
  supervised fork <id> [task]     - Fork new session from promoted parent

  snapshot / overview / wtf       - Operator snapshot (what's happening now?)
  context / ctx / usage           - Context window usage breakdown
  clear / reset                   - Start fresh session, reclaim context tokens
  lineage / branch                - Where am I? Parent chain, children, siblings
  lineage tree                    - Full session fork tree
  history / log                   - Recent message history (last 20)

[bold]Quick supervised loop:[/bold]
  go <task>     - Launch a supervised session (short for 'supervised launch')
  y / yes       - Approve next pending tool call
  n / deny      - Deny next pending tool call
  p / pending   - Show pending interventions
  [dim](interventions auto-appear when a supervised session is active)[/dim]

  help / ?      - Show this help
  [dim]anything else → sent to model via governor[/dim]
"""


class MaudeApp(App):
    """Maude TUI - Claude Code-like chat mediated by the governor."""

    TITLE = f"Maude v{__version__}"
    CSS_PATH = _CSS_PATH
    BINDINGS = [
        Binding("ctrl+l", "lock_spec", "Lock Spec"),
        Binding("ctrl+y", "approve_next", "Approve", show=False),
        Binding("ctrl+d", "deny_next", "Deny", show=False),
        Binding("ctrl+q", "quit", "Quit"),
    ]

    def __init__(
        self,
        client: GovernorClient,
        settings: Settings,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.client = client
        self.settings = settings
        self.session = MaudeSession(project_name=settings.project_name)
        self._polling_task: asyncio.Task | None = None
        self._last_session_list: list[SessionSummary] = []
        self._pending_template: str | None = None
        self._pending_rollback_anchor: str | None = None
        self._active_supervised_session: str | None = None
        self._intervention_poll_task: asyncio.Task | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield GovernorStatusBar(id="status-bar")
        yield RichLog(id="chat-log", highlight=True, markup=True, wrap=True)
        yield Input(placeholder="Type a message or command...", id="input-box")
        yield Footer()

    async def on_mount(self) -> None:
        log = self.query_one("#chat-log", RichLog)
        log.write(f"[bold]Maude v{__version__}[/bold] — governor TUI")
        log.write(f"Governor: {self.client.socket_path}")
        log.write("")

        # Check governor health
        try:
            health = await self.client.health()
            self.session.backend_type = health.backend.type
            log.write(
                f"[green]Connected[/green] — backend={health.backend.type} "
                f"mode={health.governor.mode} context={health.governor.context_id}"
            )
        except Exception as e:
            log.write(f"[red]Governor unreachable:[/red] {e}")
            log.write("[dim]Chat commands will fail until governor is available.[/dim]")

        # Set terminal title to stable session identity
        self._update_title()

        # Create or resume session
        try:
            sessions = await self.client.list_sessions()
            if sessions:
                latest = sessions[0]
                self.session.governor_session_id = latest.id
                log.write(f"[dim]Resumed session: {latest.title} ({latest.id})[/dim]")
            else:
                new = await self.client.create_session(title="Maude session")
                self.session.governor_session_id = new.id
                log.write(f"[dim]Created session: {new.id}[/dim]")
        except Exception as e:
            log.write(f"[yellow]Session init failed:[/yellow] {e}")

        log.write("")
        log.write('[dim]Type "help" for available commands.[/dim]')

        self._update_status_bar()

        # Start status polling
        self._polling_task = asyncio.create_task(self._poll_status())

    async def _poll_status(self) -> None:
        """Poll governor status every 5 seconds."""
        while True:
            await asyncio.sleep(5)
            try:
                now = await self.client.governor_now()
                self.session.last_governor_now = now
                self._update_status_bar()
            except Exception:
                pass

    def _start_intervention_poll(self) -> None:
        """Start polling for pending interventions on the active supervised session."""
        if self._intervention_poll_task is not None:
            self._intervention_poll_task.cancel()
        self._intervention_poll_task = asyncio.create_task(self._poll_interventions())

    async def _poll_interventions(self) -> None:
        """Poll for events and interventions, surface them inline."""
        _seen_interventions: set[str] = set()
        _event_cursor: int = 0
        while True:
            await asyncio.sleep(2)
            sid = self._active_supervised_session
            if not sid:
                return
            log = self.query_one("#chat-log", RichLog)

            # Poll events (show what the agent is doing)
            try:
                events = await self.client.runtime_session_events(
                    sid, since_seq=_event_cursor, limit=20,
                )
                for ev in events:
                    seq = ev.get("seq", 0)
                    if seq > _event_cursor:
                        _event_cursor = seq
                    kind = ev.get("kind", "")
                    self._render_event(log, ev, kind)
            except Exception:
                pass

            # Poll interventions
            try:
                interventions = await self.client.runtime_intervention_list(sid)
                for i in interventions:
                    tcid = i["tool_call_id"]
                    if tcid in _seen_interventions:
                        continue
                    _seen_interventions.add(tcid)
                    tool = i["tool_name"]
                    remaining = i.get("remaining_seconds", 0)
                    inp = ""
                    if i.get("tool_input"):
                        import json as _json
                        inp = _json.dumps(i["tool_input"])
                        if len(inp) > 80:
                            inp = inp[:77] + "..."
                        inp = f"  [dim]{inp}[/dim]"
                    # Communication gets a louder warning
                    action_class = i.get("action_class", "write")
                    is_comm = i.get("communication_warning") or action_class == "communicate"
                    if is_comm:
                        log.write(
                            f"\n[bold red]📡 COMMUNICATE: {tool}[/bold red] wants to send "
                            f"externally ({remaining:.0f}s remaining){inp}"
                        )
                    else:
                        log.write(
                            f"\n[yellow]⚡ {tool}[/yellow] wants to run "
                            f"({remaining:.0f}s remaining){inp}"
                        )
                    log.write("[dim]  y = approve, n = deny, p = show all pending[/dim]")
            except Exception:
                pass

    def _render_event(self, log: RichLog, ev: dict, kind: str) -> None:
        """Render a supervised session event inline."""
        # Filter to interesting events — skip noise
        if kind in ("session_created", "launching", "attaching"):
            return  # already shown at launch time

        if kind == "tool_call_proposed":
            tool = ev.get("tool_name", "?")
            log.write(f"  [cyan]→ {tool}[/cyan]", end="")
            inp = ev.get("tool_input")
            if inp:
                import json as _json
                summary = _json.dumps(inp) if isinstance(inp, dict) else str(inp)
                if len(summary) > 60:
                    summary = summary[:57] + "..."
                log.write(f"  [dim]{summary}[/dim]")
            else:
                log.write("")

        elif kind == "tool_call_completed":
            tool = ev.get("tool_name", "?")
            log.write(f"  [green]✓ {tool}[/green]")

        elif kind == "tool_call_denied":
            tool = ev.get("tool_name", "?")
            log.write(f"  [red]✗ {tool} denied[/red]")

        elif kind == "agent_output":
            content = ev.get("content", "")
            if content:
                # Show a brief excerpt
                excerpt = content[:120]
                if len(content) > 120:
                    excerpt += "..."
                log.write(f"  [dim]{excerpt}[/dim]")

        elif kind == "session_exited":
            exit_code = ev.get("exit_code", "?")
            log.write(f"\n[bold]Session exited[/bold] (code {exit_code})")
            log.write("[dim]  diff = review changes, promote = accept, reject = revert[/dim]")
            # Auto-show file summary if we can
            sid = self._active_supervised_session
            if sid:
                try:
                    import asyncio
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.ensure_future(self._auto_show_exit_summary(log, sid))
                except Exception:
                    pass

        elif kind == "session_failed":
            error = ev.get("error", "unknown")
            log.write(f"\n[red]Session failed:[/red] {error}")

    async def _auto_show_exit_summary(self, log: RichLog, sid: str) -> None:
        """Auto-show a brief summary when a supervised session exits."""
        try:
            diff_result = await self.client.runtime_promotion_diff(sid)
            files = diff_result.get("files_changed", [])
            if files:
                log.write(f"\n  [bold]{len(files)} file(s) changed:[/bold]")
                for f in files[:5]:
                    log.write(f"    {f}")
                if len(files) > 5:
                    log.write(f"    ... and {len(files) - 5} more")
            else:
                log.write("\n  [dim]No workspace changes detected.[/dim]")
        except Exception:
            pass  # Promotion may not be available yet

    def _update_title(self) -> None:
        """Set terminal title to stable session identity (slow loop)."""
        title = self.session.title_line()
        if self.settings.label:
            title += f" [{self.settings.label}]"
        self.title = title

    def _update_status_bar(self) -> None:
        bar = self.query_one("#status-bar", GovernorStatusBar)
        text = self.session.status_line()
        level = "ok"
        gov = self.session.last_governor_now
        if gov is not None:
            status = gov.status.lower() if isinstance(gov.status, str) else "ok"
            if "violation" in status or "blocked" in status:
                level = "violation"
            elif "warn" in status or "degraded" in status:
                level = "warning"
        bar.update_status(text, level)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return

        input_box = self.query_one("#input-box", Input)
        input_box.value = ""

        log = self.query_one("#chat-log", RichLog)

        # Confirmation flow for pending template load
        if self._pending_template is not None:
            if text.lower() in ("yes", "y"):
                self._load_template(log, self._pending_template)
            else:
                log.write("[dim]Template load cancelled.[/dim]")
            self._pending_template = None
            return

        # Rollback follow-up flow
        if self._pending_rollback_anchor is not None:
            await self._handle_rollback_response(log, text)
            return

        intent = parse_intent(text)

        if intent.kind == IntentKind.HELP:
            log.write(_HELP_TEXT)
        elif intent.kind == IntentKind.STATUS:
            await self._handle_status(log)
        elif intent.kind == IntentKind.PLAN_TEMPLATE:
            self._handle_plan_template(log, intent.payload)
        elif intent.kind == IntentKind.CLEAR_TEMPLATE:
            self._handle_clear_template(log)
        elif intent.kind == IntentKind.PLAN:
            self._handle_plan(log, intent.payload)
        elif intent.kind == IntentKind.LOCK_SPEC:
            await self._handle_lock_spec(log)
        elif intent.kind == IntentKind.BUILD:
            await self._handle_build(log)
        elif intent.kind == IntentKind.SHOW_SPEC:
            self._handle_show_spec(log)
        elif intent.kind == IntentKind.WHY:
            await self._handle_why(log)
        elif intent.kind == IntentKind.SESSIONS:
            await self._handle_sessions(log)
        elif intent.kind == IntentKind.SWITCH_SESSION:
            await self._handle_switch_session(log, intent.payload)
        elif intent.kind == IntentKind.DELETE_SESSION:
            await self._handle_delete_session(log, intent.payload)
        elif intent.kind == IntentKind.SHOW_DIFF:
            await self._handle_diff(log)
        elif intent.kind == IntentKind.APPLY:
            await self._handle_apply(log)
        elif intent.kind == IntentKind.ROLLBACK:
            await self._handle_rollback(log)
        elif intent.kind == IntentKind.SUPERVISED_LAUNCH:
            await self._handle_supervised_launch(log, intent.payload)
        elif intent.kind == IntentKind.SUPERVISED_LIST:
            await self._handle_supervised_list(log)
        elif intent.kind == IntentKind.SUPERVISED_EVENTS:
            await self._handle_supervised_events(log, intent.payload)
        elif intent.kind == IntentKind.SUPERVISED_APPROVE:
            await self._handle_supervised_approve(log, intent.payload)
        elif intent.kind == IntentKind.SUPERVISED_DENY:
            await self._handle_supervised_deny(log, intent.payload)
        elif intent.kind == IntentKind.SUPERVISED_KILL:
            await self._handle_supervised_kill(log, intent.payload)
        elif intent.kind == IntentKind.SUPERVISED_INTERVENTIONS:
            await self._handle_supervised_interventions(log, intent.payload)
        elif intent.kind == IntentKind.SUPERVISED_PROMOTION:
            await self._handle_supervised_promotion(log, intent.payload)
        elif intent.kind == IntentKind.SUPERVISED_DIFF:
            await self._handle_supervised_diff(log, intent.payload)
        elif intent.kind == IntentKind.SUPERVISED_PROMOTE:
            await self._handle_supervised_promote(log, intent.payload)
        elif intent.kind == IntentKind.SUPERVISED_REJECT:
            await self._handle_supervised_reject(log, intent.payload)
        elif intent.kind == IntentKind.SUPERVISED_FORK:
            await self._handle_supervised_fork(log, intent.payload)
        elif intent.kind == IntentKind.SNAPSHOT:
            await self._handle_snapshot(log)
        elif intent.kind == IntentKind.CONTEXT:
            self._handle_context(log)
        elif intent.kind == IntentKind.CLEAR:
            await self._handle_clear(log)
        elif intent.kind == IntentKind.LINEAGE:
            await self._handle_lineage(log)
        elif intent.kind == IntentKind.LINEAGE_TREE:
            await self._handle_lineage_tree(log)
        elif intent.kind == IntentKind.HISTORY:
            self._handle_history(log)
        elif intent.kind == IntentKind.QUICK_APPROVE:
            await self._handle_quick_approve(log)
        elif intent.kind == IntentKind.QUICK_DENY:
            await self._handle_quick_deny(log)
        elif intent.kind == IntentKind.QUICK_PENDING:
            await self._handle_quick_pending(log)
        elif intent.kind == IntentKind.QUICK_LAUNCH:
            await self._handle_supervised_launch(log, intent.payload)
        elif intent.kind == IntentKind.CHAT:
            await self._handle_chat(log, text)

    async def _handle_status(self, log: RichLog) -> None:
        try:
            status = await self.client.governor_status()
            log.write("[bold]Governor Status:[/bold]")
            log.write(f"  context: {status.get('context_id', '?')}")
            log.write(f"  mode: {status.get('mode', '?')}")
            vm = status.get("viewmodel")
            if vm:
                log.write(f"  decisions: {len(vm.get('decisions', []))}")
                log.write(f"  violations: {len(vm.get('violations', []))}")
                log.write(f"  claims: {len(vm.get('claims', []))}")
        except Exception as e:
            log.write(f"[red]Status error:[/red] {e}")

        # Context usage
        ctx = self.session.context_usage.format_compact()
        if ctx:
            log.write(f"\n[bold]Context:[/bold] {ctx}")

        # Supervised sessions
        try:
            sessions = await self.client.runtime_session_list()
            if sessions:
                active_sid = self._active_supervised_session
                log.write(f"\n[bold]Supervised Sessions ({len(sessions)}):[/bold]")
                for s in sessions[:5]:
                    sid = s.get("session_id", "?")
                    st = s.get("status", "?")
                    task = (s.get("task") or "")[:35]
                    pending = s.get("pending_interventions", 0)
                    marker = " *" if sid == active_sid else ""
                    parts = [f"  {sid[:8]}  {st:12s}"]
                    if task:
                        parts.append(task)
                    if pending:
                        parts.append(f"[yellow][{pending} pending][/yellow]")
                    if marker:
                        parts.append("[green](active)[/green]")
                    log.write("  ".join(parts))
                if len(sessions) > 5:
                    log.write(f"  ... and {len(sessions) - 5} more")
        except Exception:
            pass

    def _handle_plan(self, log: RichLog, payload: str) -> None:
        # Strip "plan" prefix from payload
        spec_text = payload
        for prefix in ("plan ", "let's plan "):
            if spec_text.lower().startswith(prefix):
                spec_text = spec_text[len(prefix):]
                break
        if spec_text:
            self.session.spec_draft += spec_text + "\n"
            log.write(f"[dim]Added to spec draft ({len(self.session.spec_draft)} chars)[/dim]")
        else:
            log.write("[dim]Usage: plan <description>[/dim]")

    async def _handle_lock_spec(self, log: RichLog) -> None:
        if not self.session.spec_draft:
            log.write("[yellow]No spec draft to lock. Use 'plan <text>' first.[/yellow]")
            return
        draft = self.session.lock_spec()
        log.write("[green]Spec locked.[/green]")
        self._update_status_bar()

        # Submit spec as constraint to governor
        try:
            await self.client.add_constraint(draft)
            log.write("[dim]Constraint submitted to governor.[/dim]")
        except Exception as e:
            log.write(f"[dim]Governor constraint submission failed (spec still locked locally): {e}[/dim]")

    async def _handle_build(self, log: RichLog) -> None:
        try:
            self.session.set_mode(Mode.BUILD)
            log.write("[green]Switched to BUILD mode.[/green]")
            self._update_status_bar()
        except ValueError as e:
            log.write(f"[yellow]{e}[/yellow]")
            return

        # Create a v2 run
        try:
            result = await self.client.create_run(task=self.session.spec_draft)
            run_id = result.get("id", result.get("run_id", "?"))
            log.write(f"[dim]v2 run created: {run_id}[/dim]")
        except Exception as e:
            log.write(f"[dim]v2 run creation failed (BUILD mode set locally): {e}[/dim]")

    def _handle_plan_template(self, log: RichLog, payload: str) -> None:
        """Handle 'plan architecture', 'plan product', etc."""
        key = payload.lower()
        if key not in _TEMPLATE_MAP:
            log.write(f"[yellow]Unknown template: {key}[/yellow]")
            return
        if self.session.spec_draft:
            self._pending_template = key
            log.write(
                "[yellow]Spec draft has content. Loading a template will NOT erase it,[/yellow]"
            )
            log.write("[yellow]but guided chat will append to the existing draft.[/yellow]")
            log.write("[yellow]Type 'yes' to confirm, anything else to cancel.[/yellow]")
            return
        self._load_template(log, key)

    def _load_template(self, log: RichLog, key: str) -> None:
        """Load a template file into the session."""
        filename = _TEMPLATE_MAP[key]
        # Normalise alias to canonical name
        canonical = key
        if key == "arch":
            canonical = "architecture"
        elif key == "reqs":
            canonical = "requirements"
        elif key == "product design":
            canonical = "product"
        path = _TEMPLATES_DIR / filename
        try:
            content = path.read_text()
        except FileNotFoundError:
            log.write(f"[red]Template file not found: {path}[/red]")
            return
        self.session.load_template(canonical, content)
        log.write(f"[green]Loaded template: {canonical}[/green]")
        log.write("[dim]Chat is now in guided mode — responses will fill the template.[/dim]")
        self._update_status_bar()

    def _handle_clear_template(self, log: RichLog) -> None:
        if not self.session.spec_template:
            log.write("[dim]No template loaded.[/dim]")
            return
        name = self.session.spec_template
        self.session.clear_template()
        log.write(f"[green]Template '{name}' cleared.[/green]")
        self._update_status_bar()

    def _handle_show_spec(self, log: RichLog) -> None:
        if not self.session.spec_draft:
            log.write("[dim]No spec draft yet. Use 'plan <text>' to start.[/dim]")
            return
        locked = " [green](LOCKED)[/green]" if self.session.spec_locked else " [yellow](UNLOCKED)[/yellow]"
        log.write(f"[bold]Spec Draft{locked}:[/bold]")
        log.write(self.session.spec_draft)

    async def _handle_why(self, log: RichLog) -> None:
        try:
            now = await self.client.governor_now()
            log.write(f"[bold]Why:[/bold] {now.sentence}")
            if now.suggested_action:
                log.write(f"[dim]Suggested: {now.suggested_action}[/dim]")
        except Exception as e:
            log.write(f"[red]Why error:[/red] {e}")

    async def _handle_diff(self, log: RichLog) -> None:
        """Show diff — promotion diff for supervised sessions, violation for governance."""
        # If we have an active supervised session, show promotion diff
        sid = self._active_supervised_session
        if sid:
            try:
                diff_result = await self.client.runtime_promotion_diff(sid)
                diff_text = diff_result.get("diff", "")
                files = diff_result.get("files_changed", [])
                if not diff_text and not files:
                    log.write("[dim]No workspace changes in supervised session.[/dim]")
                    return
                log.write(f"[bold]Workspace Changes ({sid[:8]})[/bold]")
                if files:
                    log.write(f"  {len(files)} file(s) changed:")
                    for f in files[:15]:
                        log.write(f"    {f}")
                    if len(files) > 15:
                        log.write(f"    ... and {len(files) - 15} more")
                if diff_text:
                    # Show abbreviated diff
                    lines = diff_text.splitlines()
                    for line in lines[:40]:
                        if line.startswith("+") and not line.startswith("+++"):
                            log.write(f"  [green]{line}[/green]")
                        elif line.startswith("-") and not line.startswith("---"):
                            log.write(f"  [red]{line}[/red]")
                        elif line.startswith("@@"):
                            log.write(f"  [cyan]{line}[/cyan]")
                        else:
                            log.write(f"  [dim]{line}[/dim]")
                    if len(lines) > 40:
                        log.write(f"  [dim]... {len(lines) - 40} more lines[/dim]")
                log.write("")
                log.write("[dim]promote = accept, reject = revert, or keep reviewing[/dim]")
                return
            except Exception as e:
                log.write(f"[yellow]Promotion diff unavailable:[/yellow] {e}")
                # Fall through to governance diff

        # Governance violation flow
        try:
            pending = await self.client.commit_pending()
            if pending is None:
                log.write("[green]No pending violations.[/green]")
                try:
                    receipts = await self.client.receipts_list(last=3)
                    if receipts:
                        log.write("\n[bold]Recent receipts:[/bold]")
                        for r in receipts:
                            verdict = r.get("verdict", "?")
                            gate = r.get("gate", "?")
                            rid = r.get("receipt_id", "?")[:12]
                            color = "green" if verdict == "pass" else "red" if verdict == "fail" else "yellow"
                            log.write(f"  [{color}]{verdict:5s}[/{color}]  {gate}  {rid}")
                except Exception:
                    pass
                return

            log.write("[bold]Pending Violation[/bold]")
            anchor = pending.get("anchor_id", "?")
            pattern = pending.get("pattern", "")
            text = pending.get("text_excerpt", "")[:80]
            log.write(f"  Anchor:  {anchor}")
            if pattern:
                log.write(f"  Pattern: {pattern}")
            if text:
                log.write(f"  Text:    {text}")
            log.write("")
            log.write("[dim]Resolve with: apply (proceed), rollback (fix), or 'why' for details[/dim]")
        except Exception as e:
            log.write(f"[red]Diff error:[/red] {e}")

    async def _handle_apply(self, log: RichLog) -> None:
        """Apply: promote supervised changes, or proceed past governance violation."""
        # If supervised session is active, apply = promote
        sid = self._active_supervised_session
        if sid:
            await self._handle_promote_active(log)
            return

        # Otherwise: governance violation proceed
        try:
            pending = await self.client.commit_pending()
            if pending is None:
                log.write("[dim]Nothing to apply — no pending violations.[/dim]")
                return

            anchor = pending.get("anchor_id", "?")
            result = await self.client.commit_proceed(
                scope="session",
                expiry="2h",
            )
            log.write(
                f"[green]Proceeded past violation:[/green] {anchor}"
            )
            if result.get("exception_id"):
                log.write(f"  Exception logged: {result['exception_id']}")
            log.write("[dim]Override expires in 2h. Use 'why' to inspect.[/dim]")
            self._update_status_bar()
        except Exception as e:
            log.write(f"[red]Apply error:[/red] {e}")

    async def _handle_promote_active(self, log: RichLog) -> None:
        """Promote (accept) workspace changes from the active supervised session."""
        sid = self._active_supervised_session
        if not sid:
            log.write("[yellow]No active supervised session.[/yellow]")
            return
        try:
            result = await self.client.runtime_promotion_resolve(sid, "approve")
            if result.get("resolved"):
                log.write(f"[green]Changes promoted[/green] from session {sid[:8]}")
            else:
                log.write(f"[yellow]{result.get('error', 'Promotion not available')}[/yellow]")
        except Exception as e:
            log.write(f"[red]Promote error:[/red] {e}")

    async def _handle_rollback(self, log: RichLog) -> None:
        """Rollback: reject supervised changes, or fix governance violation."""
        # If supervised session is active, rollback = reject
        sid = self._active_supervised_session
        if sid:
            try:
                result = await self.client.runtime_promotion_resolve(sid, "reject")
                if result.get("resolved"):
                    log.write(f"[red]Changes reverted[/red] from session {sid[:8]}")
                else:
                    log.write(f"[yellow]{result.get('error', 'Rejection not available')}[/yellow]")
            except Exception as e:
                log.write(f"[red]Reject error:[/red] {e}")
            return

        # Governance violation fix flow
        try:
            pending = await self.client.commit_pending()
            if pending is None:
                log.write("[dim]Nothing to rollback — no pending violations.[/dim]")
                return

            anchor = pending.get("anchor_id", "?")
            log.write(f"[bold]Rolling back violation:[/bold] {anchor}")
            log.write("")
            log.write("Options:")
            log.write("  1. Type a corrected response to replace the violating text")
            log.write("  2. Type 'revise' to update the anchor instead")
            log.write("  3. Type 'cancel' to leave the violation pending")
            log.write("")
            log.write("[dim]Enter corrected text, 'revise', or 'cancel':[/dim]")
            # Set a flag so the next input is treated as the fix
            self._pending_rollback_anchor = anchor
        except Exception as e:
            log.write(f"[red]Rollback error:[/red] {e}")

    async def _handle_rollback_response(self, log: RichLog, text: str) -> None:
        """Handle follow-up input for rollback flow."""
        anchor = self._pending_rollback_anchor
        self._pending_rollback_anchor = None

        lower = text.strip().lower()
        if lower == "cancel":
            log.write("[dim]Rollback cancelled. Violation still pending.[/dim]")
            return

        try:
            if lower == "revise":
                await self.client.commit_revise()
                log.write(f"[green]Anchor revised:[/green] {anchor}")
            else:
                await self.client.commit_fix(corrected_text=text)
                log.write(f"[green]Fixed violation:[/green] {anchor}")
                log.write("[dim]Corrected text submitted.[/dim]")
            self._update_status_bar()
        except Exception as e:
            log.write(f"[red]Rollback resolve error:[/red] {e}")

    def _resolve_session_id(self, ref: str) -> str | None:
        """Resolve a session reference — either a #N index or a raw ID."""
        if ref.startswith("#"):
            try:
                idx = int(ref[1:]) - 1
            except ValueError:
                return None
            if 0 <= idx < len(self._last_session_list):
                return self._last_session_list[idx].id
            return None
        # Exact or prefix match against cached list
        for s in self._last_session_list:
            if s.id == ref or s.id.startswith(ref):
                return s.id
        # Fall through: treat as raw ID (server will 404 if invalid)
        return ref

    async def _handle_sessions(self, log: RichLog) -> None:
        try:
            sessions = await self.client.list_sessions()
            self._last_session_list = sessions
            if not sessions:
                log.write("[dim]No sessions found.[/dim]")
                return
            log.write("[bold]Sessions:[/bold]")
            log.write(f"  {'#':<4} {'ID':<16} {'TITLE':<24} {'MSGS':>5}  {'UPDATED':<12}")
            for i, s in enumerate(sessions, 1):
                updated = s.updated_at[:10] if len(s.updated_at) >= 10 else s.updated_at
                active = "  *active*" if s.id == self.session.governor_session_id else ""
                log.write(
                    f"  {i:<4} {s.id[:14]:<16} {s.title[:22]:<24} "
                    f"{s.message_count:>5}  {updated:<12}{active}"
                )
        except Exception as e:
            log.write(f"[red]Session list error:[/red] {e}")

    async def _handle_switch_session(self, log: RichLog, ref: str) -> None:
        session_id = self._resolve_session_id(ref)
        if session_id is None:
            log.write(f"[yellow]Cannot resolve session: {ref}[/yellow]")
            return
        try:
            full = await self.client.get_session(session_id)
            self.session = MaudeSession(
                governor_session_id=full.id,
                project_name=self.session.project_name,
                backend_type=self.session.backend_type,
            )
            for msg in full.messages:
                self.session.add_message(msg.role, msg.content)
            log.write(
                f"[green]Switched to session:[/green] {full.title} "
                f"({full.id}) — {len(full.messages)} messages"
            )
            self._update_status_bar()
        except Exception as e:
            log.write(f"[red]Switch session error:[/red] {e}")

    async def _handle_delete_session(self, log: RichLog, ref: str) -> None:
        session_id = self._resolve_session_id(ref)
        if session_id is None:
            log.write(f"[yellow]Cannot resolve session: {ref}[/yellow]")
            return
        try:
            ok = await self.client.delete_session(session_id)
            if ok:
                log.write(f"[green]Deleted session:[/green] {session_id}")
                if session_id == self.session.governor_session_id:
                    new = await self.client.create_session(title="Maude session")
                    self.session = MaudeSession(
                        governor_session_id=new.id,
                        project_name=self.session.project_name,
                        backend_type=self.session.backend_type,
                    )
                    log.write(f"[dim]Created new session: {new.id}[/dim]")
                    self._update_status_bar()
            else:
                log.write(f"[red]Failed to delete session:[/red] {session_id}")
        except Exception as e:
            log.write(f"[red]Delete session error:[/red] {e}")

    async def _handle_chat(self, log: RichLog, text: str) -> None:
        log.write(f"\n[bold cyan]You:[/bold cyan] {text}")

        self.session.add_message("user", text)

        # Build messages for the API call
        messages = list(self.session.messages)

        # Inject template context as system message when a template is loaded
        if self.session.spec_template_content:
            draft_section = ""
            if self.session.spec_draft:
                draft_section = f"\n\n## Current Draft\n{self.session.spec_draft}"
            system_msg = {
                "role": "system",
                "content": (
                    "You are helping the user fill out a structured spec template "
                    "section by section. Guide them through each section, ask "
                    "clarifying questions, and produce well-structured content "
                    "that fits the template format.\n\n"
                    f"## Template\n{self.session.spec_template_content}"
                    f"{draft_section}"
                ),
            }
            messages.insert(0, system_msg)

        # Stream response
        log.write("[bold green]Assistant:[/bold green] ", end="")
        full_response = ""
        try:
            async for delta in self.client.chat_stream(messages, model="", use_lanes=True):
                full_response += delta
                log.write(delta, end="")
            log.write("")  # newline after streaming
        except Exception as e:
            log.write(f"\n[red]Chat error:[/red] {e}")
            return

        # Update context usage from stream result
        usage = self.client.last_stream_usage
        if usage:
            self.session.context_usage.update(usage)
            self._update_status_bar()

        self.session.add_message("assistant", full_response)

        # Accumulate response into spec draft when template is loaded
        if self.session.spec_template_content and full_response:
            self.session.spec_draft += full_response + "\n"
            log.write("[dim](appended to spec draft)[/dim]")

    async def action_lock_spec(self) -> None:
        log = self.query_one("#chat-log", RichLog)
        await self._handle_lock_spec(log)

    async def action_approve_next(self) -> None:
        log = self.query_one("#chat-log", RichLog)
        await self._handle_quick_approve(log)

    async def action_deny_next(self) -> None:
        log = self.query_one("#chat-log", RichLog)
        await self._handle_quick_deny(log)

    async def action_new_session(self) -> None:
        log = self.query_one("#chat-log", RichLog)
        try:
            new = await self.client.create_session(title="Maude session")
            self.session = MaudeSession(
                governor_session_id=new.id,
                project_name=self.session.project_name,
                backend_type=self.session.backend_type,
            )
            log.write(f"\n[dim]New session: {new.id}[/dim]")
            self._update_status_bar()
        except Exception as e:
            log.write(f"[red]New session error:[/red] {e}")

    # --- Supervised Runtime Handlers ---

    async def _handle_supervised_launch(self, log: RichLog, payload: str) -> None:
        task = payload.strip() if payload.strip() else None
        try:
            result = await self.client.runtime_session_create(task=task)
            session_id = result["session_id"]
            log.write(f"[green]Session created:[/green] {session_id}")
            if task:
                log.write(f"  Task: {task}")

            launch = await self.client.runtime_session_launch(session_id)
            log.write(f"  Status: {launch['status']}  PID: {launch.get('pid', '?')}")
            log.write(f"[dim]Use 'supervised events {session_id}' to see activity[/dim]")
            log.write(f"[dim]Use 'supervised interventions {session_id}' to see pending approvals[/dim]")

            # Store for convenience and start polling interventions
            self._active_supervised_session = session_id
            self._start_intervention_poll()
        except Exception as e:
            log.write(f"[red]Launch error:[/red] {e}")

    async def _handle_supervised_list(self, log: RichLog) -> None:
        try:
            sessions = await self.client.runtime_session_list()
            if not sessions:
                log.write("[dim]No supervised sessions.[/dim]")
                return
            log.write("[bold]Supervised Sessions:[/bold]")
            for s in sessions:
                task_str = f" — {s['task']}" if s.get("task") else ""
                pending = s.get("pending_interventions", 0)
                pending_str = f" [yellow][{pending} pending][/yellow]" if pending else ""
                log.write(f"  {s['session_id']}  {s['status']:20s}  {s['backend_kind']}{task_str}{pending_str}")
        except Exception as e:
            log.write(f"[red]List error:[/red] {e}")

    async def _handle_supervised_events(self, log: RichLog, session_id: str) -> None:
        try:
            events = await self.client.runtime_session_events(session_id.strip(), limit=30)
            if not events:
                log.write("[dim]No events.[/dim]")
                return
            log.write(f"[bold]Events for {session_id}:[/bold]")
            for e in events:
                tool_info = ""
                payload = e.get("payload", {})
                if "tool_name" in payload:
                    tool_info = f" [{payload['tool_name']}]"
                log.write(f"  {e['seq']:4d}  {e['at']}  {e['kind']:30s}{tool_info}")
        except Exception as e:
            log.write(f"[red]Events error:[/red] {e}")

    async def _handle_supervised_interventions(self, log: RichLog, session_id: str) -> None:
        try:
            interventions = await self.client.runtime_intervention_list(session_id.strip())
            if not interventions:
                log.write("[dim]No pending interventions.[/dim]")
                return
            log.write(f"[bold]Pending Interventions ({session_id}):[/bold]")
            for i in interventions:
                log.write(
                    f"  [yellow]{i['tool_name']}[/yellow]  "
                    f"tool_call_id={i['tool_call_id']}  "
                    f"remaining={i['remaining_seconds']:.0f}s"
                )
                if i.get("tool_input"):
                    import json
                    inp = json.dumps(i["tool_input"])
                    if len(inp) > 100:
                        inp = inp[:97] + "..."
                    log.write(f"    [dim]{inp}[/dim]")
                log.write(f"    [dim]→ supervised approve {session_id} {i['tool_call_id']}[/dim]")
                log.write(f"    [dim]→ supervised deny {session_id} {i['tool_call_id']}[/dim]")
        except Exception as e:
            log.write(f"[red]Interventions error:[/red] {e}")

    async def _handle_supervised_approve(self, log: RichLog, payload: str) -> None:
        parts = payload.strip().split()
        if len(parts) < 2:
            log.write("[yellow]Usage: supervised approve <session_id> <tool_call_id>[/yellow]")
            return
        session_id, tool_call_id = parts[0], parts[1]
        try:
            result = await self.client.runtime_intervention_resolve(session_id, tool_call_id, "approve")
            if result.get("resolved"):
                log.write(f"[green]Approved[/green] {tool_call_id}")
            else:
                log.write(f"[yellow]{result.get('error', 'Not found')}[/yellow]")
        except Exception as e:
            log.write(f"[red]Approve error:[/red] {e}")

    async def _handle_supervised_deny(self, log: RichLog, payload: str) -> None:
        parts = payload.strip().split()
        if len(parts) < 2:
            log.write("[yellow]Usage: supervised deny <session_id> <tool_call_id>[/yellow]")
            return
        session_id, tool_call_id = parts[0], parts[1]
        try:
            result = await self.client.runtime_intervention_resolve(
                session_id, tool_call_id, "deny", reason="Denied by operator"
            )
            if result.get("resolved"):
                log.write(f"[red]Denied[/red] {tool_call_id}")
            else:
                log.write(f"[yellow]{result.get('error', 'Not found')}[/yellow]")
        except Exception as e:
            log.write(f"[red]Deny error:[/red] {e}")

    async def _handle_supervised_kill(self, log: RichLog, session_id: str) -> None:
        try:
            result = await self.client.runtime_session_kill(session_id.strip())
            log.write(f"[red]Killed[/red] {session_id}: {result['status']}")
        except Exception as e:
            log.write(f"[red]Kill error:[/red] {e}")

    async def _handle_supervised_promotion(self, log: RichLog, session_id: str) -> None:
        try:
            p = await self.client.runtime_promotion_get(session_id.strip())
            if not p:
                log.write("[dim]No pending promotion.[/dim]")
                return
            log.write(f"[bold]Promotion: {p['promotion_id']}[/bold]")
            log.write(f"  Status: {p['status']}")
            log.write(f"  Files:  {len(p['changed_files'])}")
            for f in p["changed_files"]:
                log.write(f"    {f}")
            log.write(f"\n{p.get('diff_stat', '')}")
            log.write(f"\n[dim]→ supervised diff {session_id}[/dim]")
            log.write(f"[dim]→ supervised promote {session_id}[/dim]")
            log.write(f"[dim]→ supervised reject {session_id}[/dim]")
        except Exception as e:
            log.write(f"[red]Promotion error:[/red] {e}")

    async def _handle_supervised_diff(self, log: RichLog, session_id: str) -> None:
        try:
            result = await self.client.runtime_promotion_diff(session_id.strip())
            if "error" in result:
                log.write(f"[dim]{result['error']}[/dim]")
                return
            diff = result.get("diff", "")
            if diff:
                log.write(f"[bold]Diff for {result.get('promotion_id', '?')}:[/bold]\n")
                log.write(diff)
            else:
                log.write("[dim](no diff available)[/dim]")
        except Exception as e:
            log.write(f"[red]Diff error:[/red] {e}")

    async def _handle_supervised_promote(self, log: RichLog, session_id: str) -> None:
        try:
            result = await self.client.runtime_promotion_resolve(session_id.strip(), "approve")
            if result.get("resolved"):
                log.write("[green]Promoted[/green] — changes accepted")
            else:
                log.write(f"[yellow]{result.get('error', 'No pending promotion')}[/yellow]")
        except Exception as e:
            log.write(f"[red]Promote error:[/red] {e}")

    async def _handle_supervised_reject(self, log: RichLog, session_id: str) -> None:
        try:
            result = await self.client.runtime_promotion_resolve(session_id.strip(), "reject")
            if result.get("resolved"):
                log.write("[red]Rejected[/red] — workspace changes reverted")
            else:
                log.write(f"[yellow]{result.get('error', 'No pending promotion')}[/yellow]")
        except Exception as e:
            log.write(f"[red]Reject error:[/red] {e}")

    async def _auto_attach_session(self, log: RichLog) -> str | None:
        """If no active session, try to auto-attach to the only running one."""
        if self._active_supervised_session:
            return self._active_supervised_session
        try:
            sessions = await self.client.runtime_session_list()
            running = [s for s in sessions if s.get("status") in ("running", "waiting_tool_decision")]
            if len(running) == 1:
                sid = running[0]["session_id"]
                self._active_supervised_session = sid
                self._start_intervention_poll()
                log.write(f"[dim]Auto-attached to session {sid[:8]}[/dim]")
                return sid
        except Exception:
            pass
        return None

    async def _handle_lineage(self, log: RichLog) -> None:
        """Show current session lineage: where am I, where did I come from."""
        try:
            sessions = await self.client.runtime_session_list()
            if not sessions:
                log.write("[dim]No supervised sessions.[/dim]")
                return

            # Build lookup
            by_id = {s["session_id"]: s for s in sessions}
            active_sid = self._active_supervised_session

            # Find the active session or the most recent one
            current = by_id.get(active_sid) if active_sid else None
            if not current and sessions:
                current = sessions[0]

            if not current:
                log.write("[dim]No session to show lineage for.[/dim]")
                return

            sid = current["session_id"]
            log.write("[bold]Session Lineage[/bold]")
            log.write(f"  Current:  {sid[:8]}  {current['status']}")
            if current.get("task"):
                log.write(f"  Task:     {current['task'][:60]}")
            if current.get("started_at"):
                log.write(f"  Started:  {current['started_at'][:19]}")

            # Walk parent chain
            chain: list[dict] = []
            node = current
            while node and node.get("parent_session_id"):
                parent = by_id.get(node["parent_session_id"])
                if parent:
                    chain.append(parent)
                    node = parent
                else:
                    chain.append({"session_id": node["parent_session_id"], "status": "?", "task": None})
                    break

            if chain:
                log.write("\n[bold]Parent chain:[/bold]")
                for i, ancestor in enumerate(reversed(chain)):
                    indent = "  " + "  " * i
                    aid = ancestor["session_id"][:8] if len(ancestor.get("session_id", "")) >= 8 else ancestor.get("session_id", "?")
                    task = (ancestor.get("task") or "")[:40]
                    log.write(f"{indent}└─ {aid}  {ancestor['status']}  {task}")
                indent = "  " + "  " * len(chain)
                marker = " [green](current)[/green]"
                log.write(f"{indent}└─ {sid[:8]}  {current['status']}{marker}")

            # Find children
            children = [s for s in sessions if s.get("parent_session_id") == sid]
            if children:
                log.write(f"\n[bold]Children ({len(children)}):[/bold]")
                for c in children[:5]:
                    cid = c["session_id"][:8]
                    task = (c.get("task") or "")[:40]
                    log.write(f"  └─ {cid}  {c['status']}  {task}")

            # Find siblings
            parent_id = current.get("parent_session_id")
            if parent_id:
                siblings = [
                    s for s in sessions
                    if s.get("parent_session_id") == parent_id and s["session_id"] != sid
                ]
                if siblings:
                    log.write(f"\n[bold]Siblings ({len(siblings)}):[/bold]")
                    for s in siblings[:5]:
                        sid_s = s["session_id"][:8]
                        task = (s.get("task") or "")[:40]
                        log.write(f"  ── {sid_s}  {s['status']}  {task}")

        except Exception as e:
            log.write(f"[red]Lineage error:[/red] {e}")

    async def _handle_lineage_tree(self, log: RichLog) -> None:
        """Show full session tree."""
        try:
            sessions = await self.client.runtime_session_list()
            if not sessions:
                log.write("[dim]No supervised sessions.[/dim]")
                return

            active_sid = self._active_supervised_session

            # Build parent→children map
            children_of: dict[str | None, list[dict]] = {}
            for s in sessions:
                parent = s.get("parent_session_id")
                children_of.setdefault(parent, []).append(s)

            # Find roots (no parent or parent not in our set)
            known_ids = {s["session_id"] for s in sessions}
            roots = [
                s for s in sessions
                if not s.get("parent_session_id") or s["parent_session_id"] not in known_ids
            ]

            if not roots:
                roots = sessions[:1]

            log.write("[bold]Session Tree[/bold]")

            def render_node(node: dict, prefix: str, is_last: bool) -> None:
                sid = node["session_id"]
                short = sid[:8]
                status = node["status"]
                task = (node.get("task") or "")[:35]
                marker = " [green]*[/green]" if sid == active_sid else ""
                connector = "└─ " if is_last else "├─ "
                log.write(f"{prefix}{connector}{short}  {status:12s}  {task}{marker}")

                kids = children_of.get(sid, [])
                for i, kid in enumerate(kids):
                    child_prefix = prefix + ("   " if is_last else "│  ")
                    render_node(kid, child_prefix, i == len(kids) - 1)

            for i, root in enumerate(roots):
                render_node(root, "  ", i == len(roots) - 1)

        except Exception as e:
            log.write(f"[red]Lineage tree error:[/red] {e}")

    def _handle_history(self, log: RichLog) -> None:
        """Show message history for the current session."""
        messages = self.session.messages
        if not messages:
            log.write("[dim]No messages in current session.[/dim]")
            return
        log.write(f"[bold]Message History ({len(messages)} messages):[/bold]")
        for i, msg in enumerate(messages[-20:], max(1, len(messages) - 19)):
            role = msg["role"]
            content = msg["content"]
            if len(content) > 100:
                content = content[:97] + "..."
            if role == "user":
                log.write(f"  {i:3d}  [cyan]You:[/cyan] {content}")
            else:
                log.write(f"  {i:3d}  [green]Asst:[/green] {content}")

    async def _handle_clear(self, log: RichLog) -> None:
        """Clear context: reset messages, create fresh session."""
        old_usage = self.session.context_usage
        clearable = old_usage.clearable_tokens
        turns = old_usage.turns

        # Reset session state but preserve project/backend info
        project = self.session.project_name
        backend = self.session.backend_type
        self.session = MaudeSession(
            project_name=project,
            backend_type=backend,
        )

        # Create a fresh governor session
        try:
            new = await self.client.create_session(title="Maude session")
            self.session.governor_session_id = new.id
        except Exception:
            pass

        self._update_status_bar()

        if clearable > 0:
            k = clearable / 1000
            log.write(f"[green]Cleared.[/green] ~{k:.0f}k tokens reclaimed ({turns} turns reset).")
        else:
            log.write("[green]Cleared.[/green] Fresh session started.")

    async def _handle_quick_approve(self, log: RichLog) -> None:
        """Approve the next pending intervention on the active supervised session."""
        sid = await self._auto_attach_session(log)
        if not sid:
            log.write("[yellow]No active supervised session. Use 'go <task>' to launch one.[/yellow]")
            return
        try:
            interventions = await self.client.runtime_intervention_list(sid)
            if not interventions:
                log.write("[dim]No pending interventions.[/dim]")
                return
            i = interventions[0]
            tcid = i["tool_call_id"]
            tool = i["tool_name"]
            result = await self.client.runtime_intervention_resolve(sid, tcid, "approve")
            if result.get("resolved"):
                log.write(f"[green]Approved[/green] {tool} ({tcid[:8]})")
            else:
                log.write(f"[yellow]{result.get('error', 'Not found')}[/yellow]")
        except Exception as e:
            log.write(f"[red]Approve error:[/red] {e}")

    async def _handle_quick_deny(self, log: RichLog) -> None:
        """Deny the next pending intervention on the active supervised session."""
        sid = await self._auto_attach_session(log)
        if not sid:
            log.write("[yellow]No active supervised session. Use 'go <task>' to launch one.[/yellow]")
            return
        try:
            interventions = await self.client.runtime_intervention_list(sid)
            if not interventions:
                log.write("[dim]No pending interventions.[/dim]")
                return
            i = interventions[0]
            tcid = i["tool_call_id"]
            tool = i["tool_name"]
            result = await self.client.runtime_intervention_resolve(
                sid, tcid, "deny", reason="Denied by operator",
            )
            if result.get("resolved"):
                log.write(f"[red]Denied[/red] {tool} ({tcid[:8]})")
            else:
                log.write(f"[yellow]{result.get('error', 'Not found')}[/yellow]")
        except Exception as e:
            log.write(f"[red]Deny error:[/red] {e}")

    async def _handle_quick_pending(self, log: RichLog) -> None:
        """Show pending interventions for the active supervised session."""
        sid = await self._auto_attach_session(log)
        if not sid:
            log.write("[yellow]No active supervised session. Use 'go <task>' to launch one.[/yellow]")
            return
        await self._handle_supervised_interventions(log, sid)

    def _handle_context(self, log: RichLog) -> None:
        """Show context usage breakdown."""
        detail = self.session.context_usage.format_detail()
        log.write("[bold]Context Usage[/bold]")
        log.write(detail)
        if self.session.context_usage.clearable_tokens > 5000:
            clearable_k = self.session.context_usage.clearable_tokens / 1000
            log.write(f"\n[yellow]Tip: /clear to reclaim ~{clearable_k:.0f}k tokens[/yellow]")

    async def _handle_snapshot(self, log: RichLog) -> None:
        """Show operator snapshot — the 'what the hell is happening' view."""
        try:
            snap = await self.client.operator_snapshot()

            # Overall health
            overall = snap.get("overall", "?")
            level = "green" if overall == "ok" else "yellow" if overall == "degraded" else "red"
            log.write(f"[bold]Operator Snapshot[/bold]  [{level}]{overall}[/{level}]")

            # Doctor checks
            checks = snap.get("checks", [])
            if checks:
                for c in checks[:10]:
                    status = c.get("status", "?")
                    color = "green" if status == "ok" else "yellow" if status == "warn" else "red"
                    log.write(f"  [{color}]{status:5s}[/{color}]  {c.get('label', '?')}")

            # Suggestions
            suggestions = snap.get("suggestions", [])
            if suggestions:
                log.write("\n[bold]Suggestions:[/bold]")
                for s in suggestions[:5]:
                    log.write(f"  {s}")

            # Context usage
            ctx = self.session.context_usage.format_compact()
            if ctx:
                log.write(f"\n[bold]Context:[/bold] {ctx}")

            # Supervised sessions summary
            try:
                sessions = await self.client.runtime_session_list()
                if sessions:
                    active_sid = self._active_supervised_session
                    log.write(f"\n[bold]Supervised Sessions ({len(sessions)}):[/bold]")
                    for s in sessions:
                        sid = s.get("session_id", "?")
                        pending = s.get("pending_interventions", 0)
                        task = (s.get("task") or "")[:40]
                        pending_str = f" [yellow][{pending} pending][/yellow]" if pending else ""
                        active_str = " [green](active)[/green]" if sid == active_sid else ""
                        log.write(f"  {sid[:8]}  {s['status']:12s}  {task}{pending_str}{active_str}")
            except Exception:
                pass  # Supervised sessions are optional

        except Exception as e:
            log.write(f"[red]Snapshot error:[/red] {e}")

    async def _handle_supervised_fork(self, log: RichLog, payload: str) -> None:
        parts = payload.strip().split(None, 1)
        if not parts:
            log.write("[yellow]Usage: supervised fork <parent_session_id> [task][/yellow]")
            return
        parent_id = parts[0]
        task = parts[1] if len(parts) > 1 else None
        try:
            result = await self.client.runtime_session_fork(parent_id, task=task)
            session_id = result["session_id"]
            log.write(f"[green]Forked from {parent_id}:[/green] {session_id}")
            if task:
                log.write(f"  Task: {task}")
            log.write(f"  CWD: {result.get('cwd', '?')}")

            launch = await self.client.runtime_session_launch(session_id)
            log.write(f"  Status: {launch['status']}  PID: {launch.get('pid', '?')}")
        except Exception as e:
            log.write(f"[red]Fork error:[/red] {e}")

    async def on_unmount(self) -> None:
        if self._polling_task:
            self._polling_task.cancel()
        await self.client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Maude - Governor TUI")
    parser.add_argument(
        "--governor-dir",
        default=None,
        help="Governor directory (default: from GOVERNOR_DIR env or cwd)",
    )
    parser.add_argument(
        "--socket",
        default=None,
        help="Governor daemon socket path (default: from GOVERNOR_SOCKET env or auto-derived)",
    )
    parser.add_argument(
        "--context-id",
        default=None,
        help="Governor context ID (default: from GOVERNOR_CONTEXT_ID env or 'default')",
    )
    parser.add_argument(
        "--label",
        default=None,
        help="Session label shown in terminal title (default: from MAUDE_LABEL env)",
    )
    args = parser.parse_args()

    settings = Settings()
    if args.governor_dir:
        settings.governor_dir = args.governor_dir
    if args.socket:
        settings.socket_path = args.socket
    if args.context_id:
        settings.context_id = args.context_id
    if args.label:
        settings.label = args.label

    client = GovernorClient(
        socket_path=settings.socket_path or None,
        governor_dir=settings.governor_dir or None,
    )
    app = MaudeApp(client=client, settings=settings)
    app.run()


if __name__ == "__main__":
    main()
