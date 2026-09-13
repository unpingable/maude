# Reviewed local-copy interface

`maude.reviewed-local-copy/v1` is a deliberately narrow compiler and
read-only validation interface. It describes exactly one executor operation:
copy at most 64 KiB of already selected reviewed text to `result.txt` within
an executor-owned exclusive scratch directory. It does not run that operation,
accept a review, grant authority, or select a scratch directory.

The compiler accepts closed versioned input and emits the existing
`nightshift.precompiled_workflow_proposal.v2` handoff shape plus an executor
plan. Its work identity uses the existing domain-separated AG executor-plan
identity law. The plan binds the campaign, occurrence, subject/scope,
PlanDocument/compiler coordinates, exact UTF-8 text, and scratch root; it has
no command field or alternate destination. The outer `maude.governed-plan-binding/v1` carries exact
bytes for the PlanDocument, lock, compiler inputs, handoff, compilation receipt,
and executor plan. Its identity excludes only `binding_id`; it does not include
later review results.

Validation opens the configured existing Plan Core SQLite store in read-only
mode. It requires the stored current revision, lock, applicable passing Plan
Core checks, compilation evidence, and an exact deterministic recompilation to
agree with the supplied binding. A lock by itself is insufficient. V1 Plan Core
records remain readable with their existing meaning.

This is a component interface, not an AG, Nightshift, Docket, provider, or
executor integration claim.

## Local Docket adapter

`maude.plan.reviewed_local_copy_executor` is the component-only executor for
the same sealed plan. It implements Docket's untagged
`docket.governed-executor-transport/v1` process operations: `plan-id`,
`execute`, and `reconcile`. Its executor-owned config carries canonical sealed
plan bytes and an isolated state directory. It accepts only the matching work,
subject, and scope bindings, creates only a previously absent `result.txt`,
and records a durable attempt before writing. Terminal replay returns the same
outcome. A reserved but unproven attempt reconciles as indeterminate and never
repeats the copy.

This adapter has component tests only. It does not establish Docket custody,
AG authorization, a qualified runtime deployment, or a completed cross-system
integration.
