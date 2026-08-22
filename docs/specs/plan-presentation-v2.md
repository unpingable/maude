# `maude.plan-presentation/v2`

This sidecar is presentation-only. It is stored separately and never enters
`maude.plan-document/v1` identity, check applicability, lock identity,
compiler output, custody, or governed lineage.

Required closed fields:

```json
{
  "schema": "maude.plan-presentation/v2",
  "draft_id": "draft_...",
  "semantic_revision_id": "sha256:...",
  "selected_node_id": "pn_...",
  "selected_object_kind": "finding",
  "selected_object_id": "sha256:...",
  "collapsed_node_ids": ["pn_..."],
  "outline_percent": 36,
  "active_detail_tab": "node",
  "active_casework_tab": "findings",
  "version": 2
}
```

`active_casework_tab` is one of `findings`, `checks`, `diff`, `proposals`,
`receipts`, or `history`. A selected object is a presentation locator of kind
`document`, `node`, `finding`, `proposal`, `diff`, `receipt`, or `revision`.
Diff-record locators are deterministic presentation locators, not new Plan
Core semantic identities. A node selection must bind the same exact stable ID
in `selected_node_id` and `selected_object_id`.

A finding locator binds both the exact check receipt and finding identity as
`<receipt_id>/<finding_id>`. This prevents identical content-derived findings
that recur under current and historical receipts from collapsing into one UI
case.

The sidecar may select a finding while `selected_node_id` points at its exact
canonical target. This is cross-probing, not semantic mutation. Missing,
historical, or orphaned locators are reported or reset explicitly; they never
recreate objects and never retarget by prose or order.

No X/Y coordinates, zoom, viewport, graph-edge styling, activity feed, or
semantic health value exists in v2. V1 records are accepted only with their
original exact closed field set and gain deterministic default casework state
when loaded.

The corresponding structured read projection is
`maude.plan-presentation-projection/v2`. The design workspace projection is
`maude.plan-design-workspace/v2`. These versions make the selected-case and
persistent-pane additions explicit to clients rather than changing the prior
v1 projection in place.
