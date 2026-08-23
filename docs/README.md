# Maude Documentation

## Guides

| Document | Contents |
|----------|----------|
| [PLAN-CORE.md](PLAN-CORE.md) | Canonical mutable plan artifact, revisions, checks, locks, compiler boundary |
| [PHOSPHOR-DESIGN.md](PHOSPHOR-DESIGN.md) | Loopback browser board-file workspace, typed edits, presentation sidecar |
| [PLAN-EDIT-PROPOSALS.md](PLAN-EDIT-PROPOSALS.md) | Scoped immutable agent edit proposals and ordinary CAS acceptance |
| [OBSERVATION-ACQUISITION-ORCHESTRATION.md](OBSERVATION-ACQUISITION-ORCHESTRATION.md) | Exact one-shot post-settlement application-evidence acquisition and custody recovery |
| [Synthetic cache qualification](../qualification/synthetic_cache/README.md) | First exact PlanDocument → compiler → governed local deployment witness |
| [REPOSITIONING.md](REPOSITIONING.md) | The executor thesis, ingress contracts, boundary, do-not-build list |
| [specs/plan-envelope-v0.md](specs/plan-envelope-v0.md) | Plan envelope + submitter contracts (M-1, CANDIDATE) |
| [architecture.md](architecture.md) | System design, component map, data flow, transport abstraction |
| [commands.md](commands.md) | Full command and intent reference, keybindings, status bar |
| [configuration.md](configuration.md) | Environment variables, CLI flags, typical setups |
| [TODO_SESSION_LINEAGE.md](TODO_SESSION_LINEAGE.md) | Session lineage / typed-artifact promotion design |
| [archive/](archive/) | Chat-era documents (HISTORICAL — do not build from) |

## Quick Reference

### Start Maude

```bash
# One-time setup and Terminal 1
governor --root /path/to/project init
governor --root /path/to/project serve

# Terminal 2 (same project identity)
maude --governor-dir /path/to/.governor

# Explicit socket path
maude --socket /run/user/1000/governor-abc123.sock
```

Starting the daemon from an unrelated checkout produces a different socket.
Maude uses the Unix-socket daemon, not `governor serve --stdio` and not a direct
AG-NG connection.

### Commands

```
draft new <goal>           Create a durable Plan Core draft
draft edit/check/diff/lock Artifact-oriented design workflow (`help draft`)
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

### Browser design workspace

```bash
scripts/run-phosphor-design-demo.sh
# http://127.0.0.1:8427/phosphor/design
```

This separate Maude-owned process edits only pre-governed PlanDocuments. The
AG-owned Phosphor-ng inspector remains a different, read-only process.

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
