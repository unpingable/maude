"""Maude TUI application - Textual frontend for the agent-governor."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, Input, RichLog

from maude import __version__
from maude.client.http import GovernorClient
from maude.config import Settings
from maude.intents import IntentKind, parse_intent
from maude.session import MaudeSession, Mode
from maude.ui.widgets import GovernorStatusBar

_CSS_PATH = Path(__file__).parent / "ui" / "theme.tcss"

_HELP_TEXT = """\
[bold]Available commands:[/bold]
  plan <text>   - Start planning
  lock spec     - Lock the current spec
  build         - Switch to BUILD mode (requires locked spec)
  show spec     - Show the current spec draft
  show diff     - Show diff (TODO)
  apply         - Apply changes (TODO)
  rollback      - Rollback changes (TODO)
  why           - Show why something is blocked
  status        - Show governor status
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
        self.session = MaudeSession()
        self._polling_task: asyncio.Task | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield GovernorStatusBar(id="status-bar")
        yield RichLog(id="chat-log", highlight=True, markup=True, wrap=True)
        yield Input(placeholder="Type a message or command...", id="input-box")
        yield Footer()

    async def on_mount(self) -> None:
        log = self.query_one("#chat-log", RichLog)
        log.write(f"[bold]Maude v{__version__}[/bold] — governor TUI")
        log.write(f"Governor: {self.settings.governor_url}")
        log.write("")

        # Check governor health
        try:
            health = await self.client.health()
            log.write(
                f"[green]Connected[/green] — backend={health.backend.type} "
                f"mode={health.governor.mode} context={health.governor.context_id}"
            )
        except Exception as e:
            log.write(f"[red]Governor unreachable:[/red] {e}")
            log.write("[dim]Chat commands will fail until governor is available.[/dim]")

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
        intent = parse_intent(text)

        if intent.kind == IntentKind.HELP:
            log.write(_HELP_TEXT)
        elif intent.kind == IntentKind.STATUS:
            await self._handle_status(log)
        elif intent.kind == IntentKind.PLAN:
            self._handle_plan(log, intent.payload)
        elif intent.kind == IntentKind.LOCK_SPEC:
            self._handle_lock_spec(log)
        elif intent.kind == IntentKind.BUILD:
            self._handle_build(log)
        elif intent.kind == IntentKind.SHOW_SPEC:
            self._handle_show_spec(log)
        elif intent.kind == IntentKind.WHY:
            await self._handle_why(log)
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

    def _handle_lock_spec(self, log: RichLog) -> None:
        if not self.session.spec_draft:
            log.write("[yellow]No spec draft to lock. Use 'plan <text>' first.[/yellow]")
            return
        self.session.lock_spec()
        log.write("[green]Spec locked.[/green]")
        self._update_status_bar()

    def _handle_build(self, log: RichLog) -> None:
        try:
            self.session.set_mode(Mode.BUILD)
            log.write("[green]Switched to BUILD mode.[/green]")
            self._update_status_bar()
        except ValueError as e:
            log.write(f"[yellow]{e}[/yellow]")

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

    async def _handle_chat(self, log: RichLog, text: str) -> None:
        log.write(f"\n[bold cyan]You:[/bold cyan] {text}")

        self.session.add_message("user", text)

        # Persist user message to session
        if self.session.governor_session_id:
            try:
                await self.client.append_message(
                    self.session.governor_session_id, "user", text
                )
            except Exception:
                pass

        # Stream response
        log.write("[bold green]Assistant:[/bold green] ", end="")
        full_response = ""
        try:
            async for delta in self.client.chat_stream(
                self.session.messages, model=""
            ):
                full_response += delta
                log.write(delta, end="")
            log.write("")  # newline after streaming
        except Exception as e:
            log.write(f"\n[red]Chat error:[/red] {e}")
            return

        self.session.add_message("assistant", full_response)

        # Persist assistant message to session
        if self.session.governor_session_id:
            try:
                await self.client.append_message(
                    self.session.governor_session_id, "assistant", full_response
                )
            except Exception:
                pass

    async def action_lock_spec(self) -> None:
        log = self.query_one("#chat-log", RichLog)
        self._handle_lock_spec(log)

    async def action_new_session(self) -> None:
        log = self.query_one("#chat-log", RichLog)
        try:
            new = await self.client.create_session(title="Maude session")
            self.session = MaudeSession(governor_session_id=new.id)
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
        "--governor-url",
        default=None,
        help="Governor API URL (default: from GOVERNOR_URL env or http://127.0.0.1:8000)",
    )
    parser.add_argument(
        "--context-id",
        default=None,
        help="Governor context ID (default: from GOVERNOR_CONTEXT_ID env or 'default')",
    )
    args = parser.parse_args()

    settings = Settings()
    if args.governor_url:
        settings.governor_url = args.governor_url
    if args.context_id:
        settings.context_id = args.context_id

    client = GovernorClient(base_url=settings.governor_url)
    app = MaudeApp(client=client, settings=settings)
    app.run()


if __name__ == "__main__":
    main()
