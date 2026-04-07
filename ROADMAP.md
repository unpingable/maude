# Maude Roadmap

## Shipped (2.4.0+)

- Context usage display (status bar gauge + `context` command)
- Violation review ergonomics (`diff` / `apply` / `rollback`)
- Tight supervised loop (`go` / `y` / `n` / `p` + auto-poll)
- Inline event streaming (tool proposals, completions, denials)
- Keyboard shortcuts (Ctrl+Y approve, Ctrl+D deny, Ctrl+T tree)
- Unified diff/promote/reject (context-aware for supervised + governance)
- COMMUNICATE action class display (loud warning for external sends)
- Auto-attach to running supervised session
- Auto-exit summary (file change count on session exit)
- Status + snapshot enrichment (context usage, supervised sessions inline)
- Clear/reset command (reclaim context tokens)
- Session lineage navigation (`lineage`, `lineage tree`, `history`)
- Daemon error handling (friendly messages, auto-reconnect)
- Status bar shows active supervised session ID

## Next (Maude polish)

- **Side-panel TUI for lineage** — split-pane tree view instead of inline text
- **Richer intervention preview** — show file content for Edit/Write, not just JSON blob
- **`lineage goto <id>`** — switch focus to a different session from the tree view
- **Intervention count in status bar** — show pending count without needing `p`

## Next (Governor integration)

- **Override pressure display** — needs daemon RPC; `compute_pressure()` exists but isn't exposed via RPC yet
- **Pattern-aware approval** — sequence governance visible in Maude when it ships in Governor
- **Standing integration** — when standing v1 ships, Maude becomes the operator surface for identity/grant visibility

## Deferred

- Local knowledge store integration (reduce web search context injection surface)
- Scope governor sandbox config visualization
- Multi-session split view
- Export session transcript
