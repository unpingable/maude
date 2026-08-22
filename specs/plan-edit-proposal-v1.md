# `maude.plan-edit-proposal/v1`

The closed implementation is `maude.plan.proposals`. Proposal content binds:

- exact request, draft, base revision, and PlanDocument digest;
- exact generation identity for duplicate form/request convergence;
- provider/model/version identity;
- exact-document, exact-node, or exact-finding editing scope;
- 1–32 ordered `maude.plan-operation/v1` values;
- optional nonsemantic rationale and creation time.

`maude.plan-operation-set/v1` binds exact operation order. Provider output is
`maude.plan-edit-provider-output/v1`, bounded to 128 KiB, with exact repeated
request/base binding.

Immutable receipts are `maude.plan-edit-proposal-acceptance/v1`,
`maude.plan-edit-proposal-rejection/v1`, and
`maude.plan-edit-generation-refusal/v1`. Persistence is separate from
PlanDocument, PlanPresentation, workflow compilation, handoff, and runtime.
