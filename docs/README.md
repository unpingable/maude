# Maude Documentation

## Guides

| Document | Contents |
|----------|----------|
| [architecture.md](architecture.md) | System design, component map, data flow, transport abstraction |
| [commands.md](commands.md) | Full command and intent reference, keybindings, status bar |
| [configuration.md](configuration.md) | Environment variables, CLI flags, typical setups |

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
plan <text>    Add to spec draft
lock spec      Lock the spec
build          Switch to BUILD mode
show spec      Display spec draft
status         Show governor status
why            Explain what's blocked
sessions       List sessions
switch #N      Switch to session by index
help           List commands
<anything>     Chat via governor
```

### Keybindings

```
Ctrl+L   Lock spec
Ctrl+N   New session
Ctrl+Q   Quit
```

---

For governor setup and configuration, see the [Agent Governor documentation](https://github.com/unpingable/agent_governor).
