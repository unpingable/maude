# Maude Documentation

## Guides

| Document | Contents |
|----------|----------|
| [architecture.md](architecture.md) | System design, component map, data flow, API surface |
| [commands.md](commands.md) | Full command and intent reference, keybindings, status bar |
| [configuration.md](configuration.md) | Environment variables, CLI flags, typical setups |

## Quick Reference

### Start Maude

```bash
# Default (governor at localhost:8000)
maude

# Custom governor URL
maude --governor-url http://my-server:8000 --context-id my-project
```

### Commands

```
plan <text>    Add to spec draft
lock spec      Lock the spec
build          Switch to BUILD mode
show spec      Display spec draft
status         Show governor status
why            Explain what's blocked
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
