# Repository identity and the ref-continuity subject

Docket needs a logical repository identity that survives moving or recloning a
working tree. Git does not supply one. A filesystem path, remote URL, commit, tree, and
checkout location each describe a useful fact, but none canonically identifies a
repository.

The runtime therefore owns an explicit, persistent `RepositoryId` registry. The
identifier is opaque:

```text
repo-11111111111111111111111111111111
```

The suffix is 16 identity bytes rendered as 32 lowercase hexadecimal digits. It is not a
Git object name. `docket repository register` mints an identifier by default; an
operator may instead register a previously allocated opaque `repo-…` value. The latter
must already have been selected as an identity: prefixing or hashing a path, remote, or
Git object does not make it canonical.

## Registry and locators

A repository registration contains the `RepositoryId`, its registration time, and
operator-declared aliases:

- `path` — an operational working-tree locator. Exactly one registered path can be
  current for an identity.
- `remote` — a retained spelling supplied by the operator. Docket neither normalizes it
  nor treats equivalent-looking URLs as the same repository.

Aliases are unique registry entries and cannot be rebound to another `RepositoryId`.
That constraint protects Docket's registry; it does not prove that a path or remote has
any globally unique meaning.

Register the current absolute path before creating work:

```bash
docket repository register \
  --state /var/lib/docket/example \
  --repo /work/example
```

The command prints the minted `repository_id`. `request create` requires that identifier
and the current registered path:

```bash
docket request create \
  --state /var/lib/docket/example \
  --repository-id repo-11111111111111111111111111111111 \
  --repo /work/example \
  --target-ref refs/heads/main \
  --goal "apply the reviewed change"
```

Supplying only `--repo` is not an identity lookup. A historical path alias also cannot
authorize a new request; `--repo` must equal the registration's current path. These
checks prevent checkout discovery and a familiar-looking path from silently selecting
logical identity.

An additional non-current alias can be recorded explicitly:

```bash
docket repository alias \
  --state /var/lib/docket/example \
  --repository-id repo-11111111111111111111111111111111 \
  --kind remote \
  --value ssh://git.example.invalid/team/example
```

`repository show --json` renders `gwr:repository-registration:v0`, including every
alias, its registration time, and whether it is current.

## Relocation and recloning

Moving or recloning changes a locator, not identity. Register the new absolute path as
current:

```bash
docket repository relocate \
  --state /var/lib/docket/example \
  --repository-id repo-11111111111111111111111111111111 \
  --repo /srv/recloned/example
```

The old path remains a non-current alias. New requests must name the new current path;
historical attempts continue to resolve through their retained old path and the same
`RepositoryId`. Their dossier locator remains the path used for that attempt rather than
being rewritten to look current.

Relocation does not prove that the new working tree has the expected objects, remotes, or
history, and it does not rewrite an in-flight attempt to execute at the new path. If an
old attempt's recorded locator is no longer operational, registering a relocation does
not make that attempt dispatchable there. The ordinary dispatch and observation
mechanisms remain responsible for the Git facts they check.

## Existing stores and explicit migration

The store migration creates the registry and a nullable repository-identity binding on
work requests. It deliberately does not populate that binding from stored paths.
Opening an old store and even registering its path leaves existing work requests and
their dossiers unbound.

Migration is two explicit decisions:

```bash
docket repository register \
  --state /var/lib/docket/example \
  --repo /old/work/example

docket repository migrate-attempt \
  --state /var/lib/docket/example \
  --repository-id repo-11111111111111111111111111111111 \
  --attempt <attempt-id>
```

`migrate-attempt` uses the selected attempt to find its work request. It proceeds only
when that request's stored path is already a retained path alias for the named
`RepositoryId`; it never turns the path into identity. The binding is immutable:
repeating the same binding is harmless, while rebinding to another identifier refuses.
Because identity is stored on the work request, other attempts created from that same
request acquire the same explicit binding.

If the historical path cannot safely be registered to the selected identifier, stop.
There is no remote-discovery, checkout-discovery, commit-derived, or best-effort fallback
migration.

## Dossier v2 and v3

An unbound legacy work request continues to render as
`gwr:attempt-dossier:v2`. Its `identity.repository` field is the historical path spelling
and has only legacy locator meaning.

A newly created or explicitly migrated work request renders as
`gwr:attempt-dossier:v3`. In v3, the identity section replaces that ambiguous field with:

```json
{
  "repository_id": "repo-11111111111111111111111111111111",
  "repository_locator": {
    "kind": "path",
    "value": "/work/example"
  },
  "ref_continuity_subject": "gwr:ref-continuity:v0:repo-11111111111111111111111111111111#refs/heads/main@0123456789abcdef0123456789abcdef01234567"
}
```

`ref_continuity_subject` is `null` until the attempt has an exact result commitment for
its governed target ref. v1 remains the earlier closed dossier schema; v2 added upstream
authorization provenance, and v3 adds the explicit repository contract. A previously
exported v2 artifact is not rewritten. After an explicit binding, a fresh projection is
v3.

## Exact ref-continuity subject

For an identified attempt with a matching full result commitment, Docket binds:

```text
gwr:ref-continuity:v0:<repository_id>#<target_ref>@<result_commit>
```

The target is the exact governed ref, and the result is a full 40- or 64-character
lowercase hexadecimal commit spelling. The repository component is always the typed
`RepositoryId`; the constructor has no path or remote input.

The supported machine handoff is:

```bash
docket continuity subject \
  --state /var/lib/docket/example \
  --attempt <attempt-id> \
  --json
```

It can also resolve `--dispatch <dispatch-id>`. The
`gwr:ref-continuity-operation:v0` response carries the complete subject alongside its
independent components: repository ID, target ref, result commit, Docket attempt,
dossier projection version, prepared-attempt digest, and the attempt's path locator. An
unbound legacy attempt or an attempt without an exact committed result refuses instead
of guessing.

This command reads Docket's records. It does not inspect Git, execute Continuity, or
derive repository identity. Continuity receives the complete supplied subject and checks
the separately supplied ref and commit against that binding exactly; it does not probe
Git to re-establish their current relation.

## Ownership and nonclaims

Docket owns the repository registration and the primary subject spelling. The registry
and subject establish only that Docket explicitly bound these recorded components.
They do not establish:

- that Git has a canonical repository identity;
- that a path or remote alias is identity, globally unique, or currently reachable;
- that two clones or URLs denote the same repository;
- that the result commit remains incorporated in the target ref now;
- that Continuity accepted, committed, or relied on the working assumption;
- that NQ admitted supporting testimony or issued a disposition;
- that Nightshift responded or independently derived any upstream judgment; or
- any authority, correctness, merge safety, or discharge of residual obligations.

Those questions remain with the components that own them. In particular, Docket supplies
the subject, Continuity owns current continuity evidence, NQ owns reliance and
disposition semantics, and downstream receivers own only their receipt and custody
records.
