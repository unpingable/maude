# Maude installation lab specimen 01

**Task ID:** `install-task-01`

## Situation

A new disposable operator host has Python 3.12 and the baseline Maude documentation. A synthetic Governor service is already running at the socket named in the handoff. No product checkout or package cache is supplied.

## Supplied task

Discover the documented setup, install Maude into an isolated environment, configure the supplied endpoint, and complete one meaningful first interaction that proves the client can reach the synthetic service.

The clean-room handoff is `task.json`. Ordinary baseline Maude operator
documentation and packaging metadata are under `docs/`. Synthetic local media
and state, if supplied, use neutral paths under the per-run lab.

Use only public installation, package, shell, and Maude surfaces. Network and
production access are unavailable. Do not inspect implementation source,
install or repair an Agent Governor sibling, use sudo, or mutate anything
whose ownership is outside the handed-off Maude component.

## Review condition

Conclude only from command, package, executable, connection, and public interface evidence visible in the clean room.
