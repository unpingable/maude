# Bounded authoring walkthrough

This credential-free exercise uses Maude's deterministic fixture provider and
ordinary Plan Core proposal review. It contacts no model, reads no provider
credential, and grants no authority to execute work.

## Prerequisites

Use Python 3.11 or newer from a Maude checkout with its core dependencies
installed in `.venv`:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

Choose a new local corpus path. The demo generator refuses to overwrite an
existing path.

## Start the demo

```sh
PHOSPHOR_DESIGN_PORT=8427 scripts/run-phosphor-design-demo.sh /tmp/maude-authoring-walkthrough
```

Open <http://127.0.0.1:8427/phosphor/design>. Stop the foreground server with
Ctrl-C when finished.

The generated corpus is prepopulated with real Plan Core revisions, checks,
findings, proposal requests, usable proposals, provider refusals, semantic
diffs, and accepted, rejected, and stale examples. Those records demonstrate
past outcomes; they are not proof that a proposal attempted during this
walkthrough succeeded.

## Review and attempt one proposal

1. Select `draft_node_finding`. Inspect its current finding and saved
   finding-scoped proposal. Confirm that its base revision, exact scope,
   operations, checker result, semantic diff, and rationale are separate.
2. Select `draft_dependency_chain`, then node `pn_verify_health`.
3. In **Agent proposals**, enter `Clarify the verification step`, choose
   deterministic scenario `bounded_edit`, and press **Propose edit**. This is a
   new attempt against the displayed base revision, distinct from the proposal
   already present in the corpus.
4. Inspect validation, the exact operation, and semantic diff on the review
   page. Reject it with a short reason. Rejection records a disposition and
   creates no successor revision.
5. Generate scenario `cycle` for the same node. Its projected plan is refused
   by Plan Core validation. Then try `out_of_scope`; its response is refused
   before it can become a usable proposal. These are negative controls.

For an explicit acceptance-path test only, create another fresh demo corpus,
generate `bounded_edit` for `pn_verify_health`, review it, and press **Accept
changes into draft**. Acceptance performs one ordinary revision compare-and-swap
and should display a new revision with an agent-proposal receipt. It does not
run checks automatically: use **Check this revision** for the new contents.
This optional test does not authorize acceptance in another store.

## Expected boundary

A usable proposal remains proposed until explicit accept or reject. Validation
and diff are review information. Test acceptance creates only a Plan Core
successor; it does not lock, compile, hand off, authorize, or execute the plan.
A valid or checked revision likewise grants no authority.

## Recovery

The chosen path contains `plans.sqlite`, `presentations.sqlite`,
`proposals.sqlite`, and `owner-facts.json`. After interruption, restart the
server against those exact stores using `docs/PHOSPHOR-DESIGN.md`; do not rerun
the generator over the retained path. Inspect the current revision and saved
proposal disposition before retrying. If browser state and stores cannot be
reconciled, preserve the corpus and use a new path for a separate exercise.
