# Initial disposition

Disposition: stopped without settlement and discarded the pending change.

Maude accepted the approved bounded plan and auto-allowed an in-envelope edit and validation command. The pending diff changed only ExecStart by adding --config /etc/menu-board/config.toml; direct inspection showed Restart and WantedBy unchanged. However, the canonical event view exposed only tool_call_completed for the Bash validation and reported the run exit code as ?. That is insufficient evidence that systemd-analyze verify succeeded, and the plan requires halting when evidence is unclear. I therefore used supervised discard. Maude reported the workspace reverted and no pending changes; direct inspection confirmed the original unit content. No repository change was retained.

Lifecycle interpretation: created means the governed run record exists; running means the harness is active; proposed means an action awaits policy evaluation; allowed means the gate found it within the recorded grant, not that its result is correct; completed means the tool invocation ended, not necessarily successfully; exited means the harness stopped, here with unknown exit status; pending promotion means workspace effects await operator settlement; resolved/discarded means those effects were rejected and reverted.
