# Maude Plan Core

**Status:** Canonical pre-governed artifact contract, 2026-08-21.

Plan Core owns artifacts that remain editable before governed handoff. It does
not own facts established after handoff. The frozen ownership law is:

> Anything editable before governed handoff belongs to Maude's artifact
> toolchain. Anything established after governed handoff belongs to its
> canonical runtime owner and is inspected through Phosphor-ng.

Three further laws are load-bearing:

> Draft validity is not governed admissibility.

> Locking exact bytes does not authorize them.

> Human and agent edits produce the same kind of artifact.

## Artifact model

`maude.plan-document/v1` is an ordered semantic document with an implicit
dependency graph and initially untyped `depends on` edges. It contains:

- goal, workspace, and submitter/origin provenance;
- stable `PlanNode` IDs below campaign/occurrence identity;
- ordered nodes with descriptions, optional structured work, node acceptance
  and stop conditions, and narrow `depends_on` references;
- document constraints, acceptance criteria, and the existing envelope's
  optional document-wide execution request;
- optional exact source `PlanEnvelope.plan_ref` for explicit imports.

Order is semantic and participates in the digest. Reordering does not change a
node ID, so a semantic diff reports a reorder rather than delete/add. In v1 an
edge means only `depends on`. Edge kinds/attributes require a future schema
version; v1 has no graph DSL.

Campaign and occurrence are deliberately absent: they are governed-runtime
identities, not mutable design objects. Standing, currentness, admissibility,
authorization, spend, Docket custody, execution, and settlement are also
absent.

### Semantic state is not presentation state

Canvas coordinates, zoom, viewport, selection, collapsed state, visual groups,
and panel layout are not legal PlanDocument fields. The schema is closed so
such additions refuse. A future `PlanPresentation` sidecar may key layout by
document family/revision and stable PlanNode IDs without changing semantic
bytes. Moving a future box therefore cannot invalidate a check receipt. Node
order can, because order is semantic; node placement cannot.

### Declared world requirements

`constraints.world_requirements` records stable IDs and statements describing
desired external properties. These are design declarations, not observations.
The checker validates their structure and unique identity only. A declaration
that a service must remain available never proves that the service is currently
available; Nightshift evidence/currentness owns that evaluation.

## Exact serialization and identity

The semantic artifact is closed-schema JSON, canonicalized as UTF-8 with sorted
object keys, compact separators, no NaN/Infinity, and no trailing newline. Its
identity is `sha256(canonical bytes)`. Filename, path, CWD, CRLF formatting of an
editable JSON projection, and presentation state are not identity. Parsed
UTF-8 JSON is reserialized canonically before storage; canonical byte vectors
and CRLF/non-ASCII round trips are pinned by tests.

## Store and revisions

The local SQLite store defaults to `.maude/plans.sqlite` and may be selected by
`MAUDE_PLAN_STORE` or `maude-plan --store`. It persists immutable artifact
bytes in an append-only revision chain and a separate current-revision pointer.
Saving requires the expected current revision under `BEGIN IMMEDIATE`; a stale
writer refuses rather than overwriting. Exact duplicate saves converge. A
locked revision's bytes are retained forever; an edit creates a successor.

`edit_origin = human | agent | import` records provenance only. Human `$EDITOR`
edits and agent/file edits both call `save_revision_bytes` and create the same
`maude.plan-revision/v1` object. There is no model-only field, artifact, checker,
lock, or handoff route.

Agent/model output is first captured separately as immutable
`maude.plan-edit-proposal/v1`: an exact base-bound, scoped sequence of the same
closed operations used by a human. Only explicit acceptance invokes the
ordinary successor CAS. Multi-operation proposals form one in-memory candidate
and one successor revision or none. Provider provenance and rationale do not
alter document semantics or checker behavior. See
[Plan Edit Proposals](PLAN-EDIT-PROPOSALS.md).

## Checks and applicability

`maude.plan-rules/v1` checks structural/design facts: required document fields,
stable-ID uniqueness, reference existence, duplicate references/declarations,
dependency cycles, and positive declared budgets. It does not check runtime
truth or authority.

Every `maude.plan-check-receipt/v1` binds exact plan digest, checker identity and
version, rule-set version, result, individually identified findings and their
document/node targets, and time as evidence. The receipt is content-addressed.
Structured lifecycle projection preserves these distinct states:

1. `never_checked`;
2. `current_pass` for this exact digest/current checker/current rules;
3. `current_findings` for this exact digest/current checker/current rules;
4. `historical_digest` for a retained receipt on a superseded artifact;
5. `retired_checker_or_rules` for this digest under other checker/rule versions.

Receipts never disappear when the working draft advances. “Checked” is only a
convenience projection from these facts.

## Diff and lock

`maude.plan-diff/v1` distinguishes added, removed, field-changed, and reordered
nodes plus changes to document constraints, acceptance/stop material,
structured execution requests, goal/workspace, and provenance.

`maude.plan-lock-receipt/v1` stores and binds the exact immutable artifact,
draft/revision identity, digest, applicable check receipt identities, and time.
Current doctrine permits locking with findings or without a check: lock means
“these exact bytes were snapshotted,” not “may execute.” The receipt exposes
which checks, if any, applied.

## Lifecycle and drift

`Draft → Checked → Locked → Handed off → Governed` is presentation shorthand,
not a mutable status field. Plan Core projects current revision, all check and
lock receipts, and owner-produced external artifact references. Handoff and
governed references remain minted by Nightshift/runtime owners; Plan Core may
compare their pinned plan digests but cannot create them.

This permits the exact statement:

```text
working D3; historical check D2; lock D2; Nightshift handoff D2; governed D2
working_differs_from_handoff = true
working_differs_from_governed = true
```

Advancing a draft never rebinds historical custody or lineage.

## PlanEnvelope compatibility

`PlanEnvelope` remains the exact supervised-run ingress and historical wire
artifact. `import_plan_envelope` is an explicit one-time conversion: prose
steps receive deterministic stable node IDs derived from the frozen envelope
`plan_ref` and step index; useful constraints and acceptance/stop fields are
preserved. The envelope's aggregate execution request remains document-wide.
Conversion does not guess which prose step owns aggregate work and never
rewrites the historical artifact.

The new artifact lane is a narrow amendment to `REPOSITIONING.md`: retired
conversational PLAN/BUILD state stays retired. Plan Core is explicit artifact
authoring, not mutable chat memory.

## Compilation and handoff

Compilation is a closed workflow-specific interface:

```text
locked PlanDocument
  + compiler identity/version
  + explicit typed/versioned compiler inputs
  -> exact existing handoff bytes + optional PlanNode output bindings
```

For every implemented compiler, identical locked bytes, compiler version, and
explicit inputs must yield byte-identical output. The compiler contract cannot
read wall clock, CWD, environment, hostname, random state, home-directory state,
incidental filesystem order, or undeclared mutable files. An environmental fact
needed for compilation must become explicit typed/versioned input with
provenance. The registry executes twice and refuses nondeterminism defensively.

There is still no general operational compiler. `draft handoff` and
`maude-plan handoff` therefore return `compiler_unavailable` rather than infer
operations from prose. The first deliberately narrow implementation is
`maude.local-compose-workflow` version `1`: it accepts one closed set of typed
synthetic-cache actions and explicit Docker/runtime identities. It was added to
qualify the compiler boundary, not as a generic Compose or shell language.
Unsupported documents remain uncompileable.

That compiler emits the already-qualified precompiled authoring input and uses
the existing authenticated Maude → Nightshift custody path. Nightshift receives
exact precompiled structures and never interprets plan prose. Compilation
establishes representation, not freshness, standing, admissibility,
authorization, or execution permission. See the
[synthetic cache qualification](../qualification/synthetic_cache/README.md).

### Handoff identity is distinct from artifact identity

- Exact retransmission of one existing handoff/target request converges on the
  same custody record and cannot create another occurrence.
- A deliberate new supervised handoff of identical locked bytes has a distinct
  target-request/handoff identity (and, in the current custody model, distinct
  supervised session context). It may create a distinct occurrence only if the
  governed workflow accepts that new exact handoff.

Identical design bytes do not identify an occurrence. Duplicate transport does
not imply a new occurrence. Existing custody tests pin both cases.

## Client surfaces

The headless `maude-plan` CLI and the TUI `draft ...` commands are thin clients
of the same core. `$EDITOR` receives a pretty JSON projection; after exit the
bytes are parsed and stored as a successor revision under compare-and-swap.
Structured inspect/check/diff/lock output is ready for a future browser client.

The implemented local product boundary is:

```text
/phosphor/design -> Maude-owned mutable Plan Core service
existing /phosphor/inspect -> mechanically read-only ag-operator-ui
```

The Design workspace uses a separate `maude.plan-presentation/v2` sidecar
(with deterministic read compatibility for v1);
selection and collapsed sections never enter semantic identity. Browser edits
decode to the same closed typed operation and immutable revision boundary as
CLI/future agent edits. Stable node IDs let the UI cross-probe check findings
immediately. The synthetic local-Compose compiler now supplies the first exact
node bindings; a separately supplied, owner-verified
`maude.plan-governed-cross-probe/v1` projection lets `/design` navigate from
those nodes to exact governed occurrences without prose/timestamp matching.
The projection is read-only and cannot establish or alter authority.
When one node ID survives across design generations, each binding retains its
own PlanDocument and compilation identity; stable node identity is never
treated as artifact equivalence or qualification carry-forward.

## Explicit nonclaims

Plan Core does not prove external-world truth, currentness, standing,
admissibility, authorization, execution success, or settlement. It does not
provide a node canvas, generic graph language, universal prose compiler, or
alternate custody path. The separate local Design service mutates only
pre-governed Plan Core artifacts; it provides no governed-runtime mutation.
