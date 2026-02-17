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
  show diff     - Show diff (TODO)
  apply         - Apply changes (TODO)
  rollback      - Rollback changes (TODO)
  why           - Show why something is blocked
  status        - Show governor status
  sessions      - List all sessions (also: ls, list sessions)
  switch <id>   - Switch to a session by ID or #N (also: session <id>, resume <id>)
  delete session <id> - Delete a session (also: rm session <id>)
  help / ?      - Show this help
  [dim]anything else → sent to model via governor[/dim]
"""


class MaudeApp(App):
    """Maude TUI - Claude Code-like chat mediated by the governor."""

    TITLE = f"Maude v{__version__}"
    CSS_PATH = _CSS_PATH
    BINDINGS = [
        Binding("ctrl+l", "lock_spec", "Lock Spec"),
        Binding("ctrl+n", "new_session", "New Session"),
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
            log.write("[dim]# TODO: diff pane not yet implemented[/dim]")
        elif intent.kind == IntentKind.APPLY:
            log.write("[dim]# TODO: apply gate not yet implemented[/dim]")
        elif intent.kind == IntentKind.ROLLBACK:
            log.write("[dim]# TODO: rollback not yet implemented[/dim]")
        elif intent.kind == IntentKind.CHAT:
            await self._handle_chat(log, text)

    async def _handle_status(self, log: RichLog) -> None:
        try:
            status = await self.client.governor_status()
            log.write("[bold]Governor Status:[/bold]")
            log.write(f"  context: {status.get('context_id', '?')}")
            log.write(f"  mode: {status.get('mode', '?')}")
            log.write(f"  initialized: {status.get('initialized', '?')}")
            vm = status.get("viewmodel")
            if vm:
                log.write(f"  decisions: {len(vm.get('decisions', []))}")
                log.write(f"  violations: {len(vm.get('violations', []))}")
                log.write(f"  claims: {len(vm.get('claims', []))}")
        except Exception as e:
            log.write(f"[red]Status error:[/red] {e}")

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
            async for delta in self.client.chat_stream(messages, model=""):
                full_response += delta
                log.write(delta, end="")
            log.write("")  # newline after streaming
        except Exception as e:
            log.write(f"\n[red]Chat error:[/red] {e}")
            return

        self.session.add_message("assistant", full_response)

        # Accumulate response into spec draft when template is loaded
        if self.session.spec_template_content and full_response:
            self.session.spec_draft += full_response + "\n"
            log.write("[dim](appended to spec draft)[/dim]")

    async def action_lock_spec(self) -> None:
        log = self.query_one("#chat-log", RichLog)
        await self._handle_lock_spec(log)

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
