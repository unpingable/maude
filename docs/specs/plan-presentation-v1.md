# `maude.plan-presentation/v1` (historical input)

This original sidecar remains readable and is deterministically upgraded in
memory to [`maude.plan-presentation/v2`](plan-presentation-v2.md). New writes
use v2. V1 is retained here to document old local workspace records.

This sidecar is presentation-only and is not part of PlanDocument semantic
identity.

Required closed fields:

```json
{
  "schema": "maude.plan-presentation/v1",
  "draft_id": "draft_...",
  "semantic_revision_id": "sha256:...",
  "selected_node_id": "pn_...",
  "collapsed_node_ids": ["pn_..."],
  "outline_percent": 36,
  "active_detail_tab": "node",
  "version": 1
}
```

`selected_node_id` may be `null`. `active_detail_tab` is one of `node`,
`document`, or `raw`; `outline_percent` is bounded to 22–60. Store version is a
presentation-only compare-and-swap counter.

The draft/revision fields are locators, not authority or semantic identity. A
reference absent from the target PlanDocument is reported as orphaned. It is
never retargeted or used to create semantic state. No X/Y coordinates, zoom,
viewport, or visual edge types exist in v1.
