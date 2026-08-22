# Phosphor-ng Design Workspace

**Status:** local product experiment over qualified Maude Plan Core, 2026-08-21.

`/phosphor/design` is a Maude-owned, loopback-only workspace for mutable,
pre-governed `maude.plan-document/v1` artifacts. It exists to evaluate whether
PlanDocument is the right operational board file. It is not a governed-runtime
console and contains no intervention, authorization, handoff, or execution
path.

## Product and trust architecture

Phosphor-ng is a product family with separate trust domains:

```text
/phosphor/design -> separate Python process -> Maude Plan Core -> local draft store
/phosphor/inspect -> ag-operator-ui          -> owner read commands -> governed facts
```

The Design link to Inspect is navigation only and is configurable with
`--inspect-url`. The mutable service is not imported into `ag-operator-ui`.
The inspector remains mechanically GET/HEAD-only and has no Plan Core
dependency. Design imports no AG, Nightshift, or Docket implementation and
does not interpret their databases.

## Editing model

Browser forms decode into the closed `maude.plan-operation/v1` union:

- `add_node`;
- `update_node`;
- `remove_node`;
- `reorder_node`;
- `update_document`.

There is no arbitrary document PATCH. Node and document editors construct
typed Plan Core values, including closed structured-work, constraint,
world-requirement, and execution-request values. Dependency editing uses exact
stable PlanNode IDs; v1 edges still mean only `depends on`.

Every semantic mutation follows:

```text
load exact immutable revision
-> apply one typed operation
-> show semantic diff and proposed digest
-> authenticate the exact preview token
-> save successor under expected-revision CAS
```

A stale page, concurrent tab, or external CLI edit receives a visible conflict.
The operation is not rebased or retargeted. Repeating the same reviewed preview
after an uncertain response converges on the already-created exact successor;
a distinct conflicting edit does not.

Human browser edits use the same `DraftStore.save_successor` boundary and
`maude.plan-revision/v1` artifact as CLI and future agent edits. There is no
browser-only semantic field or revision type.

## Presentation sidecar

`maude.plan-presentation/v2` is stored in a separate SQLite file. V1 sidecars
remain readable and upgrade deterministically. V2 contains:

- exact draft and semantic-revision locator;
- selected PlanNode ID;
- collapsed PlanNode sections;
- outline pane percentage;
- active detail tab;
- active persistent casework tab;
- selected object kind and exact presentation locator;
- sidecar CAS version.

It contains no semantic node fields and never participates in PlanDocument
digest, check receipt, lock receipt, compiler output, or handoff identity.
Selection/collapse changes do not create PlanDocument revisions.

Presentation state is subordinate and may become stale. When a successor
revision removes a selected/collapsed node, the workspace explicitly reports
the orphaned stable ID. It does not recreate the node, choose a similar node,
or mutate the PlanDocument. A malformed or conflicting sidecar fails
independently of semantic storage.

## Workspace, casework, and cross-probing

The workspace has an ordered outline, a typed selected-object inspector, and a
permanent lower casework pane. The pane retains bounded Findings, Checks,
Diff, Agent proposals, Receipts, and Revision history tabs. It is not an
activity feed and computes no health score. Reorder changes semantic order
while preserving node IDs; selection and tab changes do not.

The selected object determines a small list of contextual editor or read
moves. A node offers edit, propose, finding, dependency, diff, and history
inspection. A finding keeps the finding active while cross-probing to its
exact node/document target. Proposals, receipts, diff records, and revisions
remain separate inspectable cases. These moves expose only operations that
already exist; they do not invent runtime legal moves.

Current applicable findings link by exact `CheckTargetV1.node_id`:

- finding -> exact PlanNode and finding highlight;
- PlanNode -> exactly its current applicable findings;
- document finding -> document inspector;
- predecessor semantic diff -> structured stable-ID changes.
- proposal -> exact affected stable PlanNode IDs;
- revision/receipt -> exact retained artifact facts.
- owner-verified compiler/lineage binding -> exact governed occurrence and
  proposal in the separate read-only inspector.

No prose, display position, title, or timestamp matching occurs. Removed-node
findings remain historical with their old receipt; they are not retargeted.
Selection redirects to a focusable active-case anchor; pane switches return to
the focusable persistent casework pane. This keeps keyboard and narrow-screen
navigation attached to the object or evidence the operator deliberately chose.

Human-distinguishing goal, description, source, and occurrence context lead
ordinary views. Full canonical digests remain selectable in raw/details and
title text, but are secondary typography. Current applicability and historical
receipt facts stay separate rather than collapsing into a dashboard score.

## Checks, locks, and drift

The UI retains all receipt applicability classes verbatim:

- `never_checked`;
- `current_pass`;
- `current_findings`;
- `historical_digest`;
- `retired_checker_or_rules`.

Historical receipts stay visible after edits. A prior pass therefore never
makes modified bytes look checked.

Locking records an immutable exact snapshot even with findings or without a
check, as existing doctrine allows. The UI states plainly:

> Locking snapshots exact plan bytes. It does not authorize execution.

The drift projection compares exact current, last-check, lock, handoff-owner,
and governed-owner digests. Owner facts are read-only inputs; the demo corpus
labels its synthetic owner facts as fixtures. Absence remains `not recorded`.

## Handoff and governed cross-probe boundary

There is no generic workflow compiler and no browser handoff. For ordinary
documents the workspace exposes the boundary rather than a disabled fiction:

> No exact workflow compiler, no governed handoff.

Plan Core cannot derive governed operational work from prose or ambient
context. There is no Submit, Run, or heuristic PlanEnvelope escape hatch.

The synthetic cache qualification registers one closed local-Compose compiler
outside the browser service. For its retained Plan Core store, `/design` can
display historical compilation receipts and consume an independently generated
`maude.plan-governed-cross-probe/v1` file. Each binding joins an exact stable
PlanNode/compiler output to Nightshift plan/work lineage, AG occurrence and
proposal, and Docket settled attempt. Selecting the node offers a navigation
link to that exact `/inspect` occurrence. The browser neither constructs these
bindings nor queries owner databases; malformed, substituted, or retargeted
bindings refuse at startup.

Configure the optional projection with `--governed-cross-probe PATH`. It is a
read-only locator/audit projection and contains no spend, signature, credential,
capability, or authorization material.

## Local security

The service binds only an IP address classified as loopback. It enforces:

- exact local Host and same-origin checks;
- an HMAC-derived CSRF token on all POSTs;
- authenticated, tamper-evident semantic preview tokens;
- form-only closed mutation endpoints;
- a 128 KiB request bound;
- HTML escaping and a no-script CSP;
- no filesystem path supplied by browser fields;
- no subprocess or shell interpolation;
- explicit rejection of PUT/PATCH/DELETE.

This is local artifact custody, not enterprise user authentication. The
process has write access only to the configured plan, presentation, and
pre-governed edit-proposal stores.

## Agent edit proposals

The contextual, non-chat proposal workflow uses
`maude.plan-edit-proposal/v1`. A deterministic fixture provider (or future
provider-neutral adapter) receives an exact bounded request and returns hostile
bytes containing only ordinary `maude.plan-operation/v1` candidates. Scope,
targets, fields, base revision/digest, and output size are validated before a
preview exists.

Review uses the ordinary semantic diff, with rationale separate and explicitly
nonsemantic. Accept is always deliberate and calls the same revision CAS once,
producing one successor or none. Reject, accept, provider refusal, and stale
state remain immutable evidence. V1 has no auto-accept or partial acceptance.
See [Plan Edit Proposals](PLAN-EDIT-PROPOSALS.md).

## Run the deterministic corpus

From the Maude repository:

```bash
scripts/run-phosphor-design-demo.sh
```

Then open <http://127.0.0.1:8427/phosphor/design>. The generator refuses to
overwrite an existing corpus. Pass an empty destination as the first argument
to retain the generated store.

For an existing Plan Core store:

```bash
PYTHONPATH=src .venv/bin/python -m maude.design.server \
  --store <data-directory>/plans.sqlite \
  --presentation-store <data-directory>/plan-presentations.sqlite \
  --proposal-store <data-directory>/plan-edit-proposals.sqlite \
  --owner-facts <data-directory>/owner-facts.json \
  --governed-cross-probe <data-directory>/governed-cross-probe.json
```

Replace `<data-directory>` with a real directory on the local machine, for
example `/tmp/phosphor-design-data`; angle-bracketed names in documentation are
placeholders, not literal paths.

The deterministic corpus contains valid, dependent, broken-reference, cycle,
node/document finding, current/historical/retired-checker, lock/drift,
owner-fact drift, imported-envelope, structured-work, long-content, orphaned
presentation, 24-node density, and useful/debatable/stale/invalid/accepted
proposal cases. All semantic objects are real Plan Core artifacts rather than
browser-only shapes.

## Human evaluation path

The shortest useful casework review is:

1. Open **Investigate current and historical findings** and select each
   current finding. Confirm that the exact target remains selected while the
   finding stays the active case.
2. Use **Propose fix**, review scope and semantic diff before rationale, then
   reject or accept the deterministic proposal and rerun the checker.
3. Open **Working successor after governed lineage** and explain the Working,
   Locked, Handed off, and Governed mismatch without opening raw JSON.
4. Open **Twenty-four node density qualification** at a narrow window and
   inspect dependencies and reverse dependencies.
5. In the persistent pane, compare a historical passing check with the current
   receipt, inspect a proposal, and follow its affected PlanNode links.

The remaining evaluation questions are whether the persistent pane is useful
rather than noisy, whether contextual moves are discoverable, and whether the
proposal rationale contributes anything beyond the exact scope and diff.

## Future edits and nonclaims

An agent now proposes ordinary PlanDocument edits through the same revision
boundary as a human, but cannot save until an operator explicitly accepts the
immutable proposal. There is no agent chat, auto-accept, canvas, typed edge,
generic workflow compiler, browser handoff, intervention control, or governed
write. Governed cross-probing exists only where exact compiler/lineage/
execution bindings were recorded; this workspace never infers them.
