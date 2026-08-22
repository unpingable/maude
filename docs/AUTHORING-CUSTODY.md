# Maude authoring handoff custody

Status: optional deployment-qualified transport for new Nightshift authoring
handoffs. It is lineage custody, not permission.

## Session cut

With a complete session-custody profile, `run <plan>` records
`maude.supervised_session_custody.v1` immediately after the canonical
`runtime.session.create` response returns and before `runtime.session.launch`.
The append-only receipt binds the exact returned `session_id`, SHA-256 of the
exact UTF-8 plan bytes, byte length, configured Maude session-issuer identity,
record time, and a domain-separated HMAC. A custody failure leaves the created
session unlaunched; it never falls through to an unauthenticated handoff.

Configure the Maude session process with all four values or none:

```text
MAUDE_CUSTODY_STORE=/var/lib/maude/authoring-custody.sqlite
MAUDE_SESSION_CUSTODY_KEY_FILE=/run/credentials/maude-session-issuer.key
MAUDE_SESSION_ISSUER_PRINCIPAL_ID=maude:supervisor
MAUDE_SESSION_ISSUER_KEY_ID=maude-session-key:primary
```

The key contains exactly 32 raw bytes and must not be accessible by group or
others. The store is created 0600 and rejects a symlink, unsafe mode, wrong
owner, or a recorded session rebound to different plan bytes.

## Handoff packaging

`maude-authoring-handoff` is a separate one-shot packaging command. It does
not call Nightshift. It reads an existing session receipt, the exact plan file,
and an already-sealed Nightshift base request, then emits
`nightshift.maude_authoring_context_handoff.v1`:

```sh
maude-authoring-handoff \
  --store /var/lib/maude/authoring-custody.sqlite \
  --key-file /run/credentials/maude-handoff-producer.key \
  --producer-principal-id maude-handoff:local \
  --producer-key-id maude-handoff-key:primary \
  --session-issuer-principal-id maude:supervisor \
  --session-issuer-key-id maude-session-key:primary \
  --session-id sess_EXACT \
  --plan /path/to/exact-plan.md \
  --nightshift-request /path/to/sealed-base-request.json \
  --target-runtime-id nightshift:local-c1 \
  --out /run/nightshift/authoring-handoff.json
```

Equivalent environment names for the handoff side are
`MAUDE_CUSTODY_STORE`, `MAUDE_HANDOFF_PRODUCER_KEY_FILE`,
`MAUDE_CUSTODY_PRODUCER_PRINCIPAL_ID`,
`MAUDE_CUSTODY_PRODUCER_KEY_ID`, `MAUDE_SESSION_ISSUER_PRINCIPAL_ID`, and
`MAUDE_SESSION_ISSUER_KEY_ID`.

The handoff producer receives its own credential and the public identity of
the configured session issuer, but not the session-issuer credential. Its
store API can read a receipt and cannot mint one. The two key identities must
differ, and Nightshift also refuses identical key bytes. This is the narrow
entitlement proof: a producer credential alone cannot create an arbitrary
supervised-session claim.

Plan and request input are non-symlink regular files, read byte-exact with
1 MiB and 16 MiB bounds respectively. Output-to-file uses a 0600 temporary,
`fsync`, atomic rename, and directory `fsync`. CRLF is not normalized.

## Replay, restart, and concurrency

The SQLite relations are append-only. Exact session recording and exact
handoff retransmission return the first record. A session cannot be rebound to
another plan. One session/plan can target only one sealed base request, and one
request can carry only one relation. Concurrent conflicts yield one winner and
one deterministic refusal. A producer or Maude process restart reopens and
validates the same records; no relationship is reconstructed from filenames,
timestamps, process ancestry, or plan similarity.

Nightshift is the authority for reception, independent verification, durable
custody provenance, and the final governed relation. A timeout after packaging
therefore permits byte-identical resend; Nightshift's existing slot/occurrence
law prevents remint after its durable commit.

## Nonclaims

Producer authentication establishes custody of the authoring-context
assertion. It does not authorize governed work.

Authoring-context provenance establishes lineage, not permission.

Maude does not infer currentness, standing, admissibility, AG authorization,
execution, or runtime success from either receipt. The handoff command is not
a production submit action. Host service-principal isolation, key rotation,
key-file and store backup, executable integrity, and the honesty of the
session service remain deployment assumptions. The HMAC design authenticates
within one deployment and does not claim third-party non-repudiation.

Maude still has no stable browser-addressed plan/session page. That read-only
surface remains deferred; Phosphor-ng displays the exact recorded identities
without inventing a backlink.

The supervised-session receipt also is not browser-user authentication. It
proves that the configured Maude session issuer recorded an exact session and
plan, not which human held a browser session or which AG intervention mandate
that human possessed. Consequently it cannot be reused to justify a browser
writer. Until a canonical browser principal/mandate verifier is selected,
Maude may prepare local context and the authenticated one-shot AG submitter may
deliver an already exact request, but no web click is a governed identity.
