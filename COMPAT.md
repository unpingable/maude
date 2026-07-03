# Compatibility

Maude is a terminal executor client of the Agent Governor daemon.

## Version coupling

Tracks Governor **major.minor**. Client 2.3.x expects governor 2.3.x.
Patch versions are independent.

## Compatible Governor versions

- Required: `>=2.3.1 <2.4.0`

## Planned: contract pin (v3.0, GS-15)

At the v3.0 release Maude's primary compatibility pin becomes the
**shell-contract version**, pinned via the `ag_shell_client` package
(agent_gov `libs/ag_shell_client`, CI-tested against the daemon); the
governor version becomes advisory. Until then the Governor version pin
above remains authoritative, and the GS-9 live-daemon smoke test is the
real compatibility check while the daemon evolves.

## Contract versions (wire / JSON)

| Contract | Version | Used For |
|----------|---------|----------|
| RPC protocol | 1.0 | Daemon communication (Unix socket, Content-Length framing) |
| StatusRollup schema | 1 | Governor status display |
| ViewModel schema | v2 | State queries |
| Receipt schema | 2 | Receipt display |

## Feature negotiation

Maude connects to the governor daemon via Unix socket JSON-RPC. If the socket
is unavailable, the app starts in degraded mode (health shows "unavailable").

Shape adapters (`_adapt_health`, `_adapt_session_summary`, etc.) normalize
daemon responses to Pydantic models. If a field is missing, adapters provide
safe defaults rather than crashing.

Maude never scrapes CLI text output. All data comes from daemon RPC responses.
