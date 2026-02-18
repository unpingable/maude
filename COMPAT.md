# Compatibility

Maude is a Textual TUI client for Agent Governor.

## Version coupling

Tracks Governor **major.minor**. Client 2.3.x expects governor 2.3.x.
Patch versions are independent.

## Compatible Governor versions

- Required: `>=2.3.0 <2.4.0`

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
