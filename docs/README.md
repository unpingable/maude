# Maude Documentation

## Guides

| Document | Contents |
|----------|----------|
| [REPOSITIONING.md](REPOSITIONING.md) | The executor thesis, ingress contracts, boundary, do-not-build list |
| [architecture.md](architecture.md) | System design, component map, data flow, transport abstraction |
| [commands.md](commands.md) | Full command and intent reference, keybindings, status bar |
| [configuration.md](configuration.md) | Environment variables, CLI flags, typical setups |
| [TODO_SESSION_LINEAGE.md](TODO_SESSION_LINEAGE.md) | Session lineage / typed-artifact promotion design |
| [archive/](archive/) | Chat-era documents (HISTORICAL — do not build from) |

## Quick Reference

### Start Maude

```bash
# Default (auto-detects governor socket from cwd)
maude

# Explicit governor directory
maude --governor-dir /path/to/.governor

# Explicit socket path
maude --socket /run/user/1000/governor-abc123.sock
```

### Commands

```
supervised launch <task>   Launch a governed harness run  (alias: go <task>)
y / n / p                  Approve / deny / show pending tool calls
supervised diff <id>       Review workspace changes
supervised promote <id>    Accept changes (reject to revert)
lineage / history          Session lineage and history
snapshot                   Operator overview
status                     Governor status
why                        Explain what's blocked
help                       List commands
```

Legacy (unsupported, removal at GS-15): `plan`, `lock spec`, `build`, and
free-text chat via the governor.

### Keybindings

```
Ctrl+Y   Approve pending tool call
Ctrl+D   Deny pending tool call
Ctrl+T   Lineage tree
Ctrl+N   New session
Ctrl+Q   Quit
```

---

For governor setup and configuration, see the [Agent Governor documentation](https://github.com/unpingable/agent_governor).
