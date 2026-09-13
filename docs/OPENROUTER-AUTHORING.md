# OpenRouter authoring enrollment

This is an opt-in local profile for one bounded Maude Plan Edit proposal call
through Switchyard. It does not enable a provider by default, accept a proposal,
or authorize any later action.

## Nonsecret profile

Use [`examples/openrouter-authoring-profile.json`](examples/openrouter-authoring-profile.json).
It selects `anthropic/claude-sonnet-4.5` with these closed limits:

- admitted input: 16,384 bytes;
- prompt: 16,896 tokens, including the 512-token wrapper reserve;
- completion: 2,048 tokens;
- total: 18,944 tokens;
- price envelope: 3 microdollars per prompt token and 15 microdollars per
  completion token;
- reservation: 81,408 microdollars within a 100,000-microdollar ($0.10)
  caller budget;
- concurrency one, timeout 60 seconds, no retry, and no model fallback.

The arithmetic is exact:
`16,896 * 3 + 2,048 * 15 = 81,408` microdollars. Pricing values are an
operator-verified point-in-time input; recheck them before any later call rather
than treating this example as a current price feed.

## Credential route

Choose an explicit private absolute path with `--switchyard-credential-file`.
The user provisions it outside the repository as a user-owned regular file,
mode `0600`, containing either a raw key or one assignment (one final newline
is accepted):

```text
OPENROUTER_API_KEY=USER_PROVIDED_VALUE
```

Do not commit, print, inspect, copy, log, or generate the value. Missing files,
symbolic links, FIFOs, wrong ownership/mode, oversized content, invalid UTF-8,
additional lines, or embedded carriage returns are refused. Credential loading is lazy:
starting the design server does not read the file; Switchyard requests the
named value only for an explicitly selected enrolled-provider call.

## Opt-in local launch

Use a clean public checkout at the exact reviewed Maude revision, then install
the public source-only Switchyard runtime at its reviewed revision. Both are
Python packages rooted at `src/`; do not substitute an unrelated distribution
with either import name:

```sh
git clone https://github.com/unpingable/maude.git /tmp/maude
git -C /tmp/maude checkout --detach 8c943d77013b1916a157f32f0fccc0ed933be264
git clone https://github.com/unpingable/switchyard-runtime.git /tmp/switchyard-runtime
git -C /tmp/switchyard-runtime checkout --detach 9ce03b158589ca4c73907b48cd9632762b2c15a2
python3 -m venv /tmp/maude-openrouter-venv
/tmp/maude-openrouter-venv/bin/python -m pip install -e /tmp/maude
/tmp/maude-openrouter-venv/bin/python -m pip install /tmp/switchyard-runtime
git -C /tmp/maude rev-parse HEAD
git -C /tmp/switchyard-runtime rev-parse HEAD
/tmp/maude-openrouter-venv/bin/switchyard-direct-api --help
```

The two `rev-parse` results must be, in order,
`8c943d77013b1916a157f32f0fccc0ed933be264` and
`9ce03b158589ca4c73907b48cd9632762b2c15a2`. Maude's core install does not
require the transitional `classic-rpc` extra. Make both source roots explicit
when launching so an ambient package cannot be selected. Create one fresh demo
store first; the server does not create these stores itself:

```sh
MAUDE_SRC=/tmp/maude
SWITCHYARD_SRC=/tmp/switchyard-runtime
DEMO=/tmp/maude-openrouter-demo
OPENROUTER_CREDENTIAL_FILE=/absolute/path/to/operator-provisioned-openrouter-key
test ! -e "$DEMO"
PYTHONPATH="$MAUDE_SRC/src" \
  /tmp/maude-openrouter-venv/bin/python -m maude.design.demo "$DEMO"
PYTHONPATH="$MAUDE_SRC/src:$SWITCHYARD_SRC/src" \
  /tmp/maude-openrouter-venv/bin/phosphor-design \
  --store "$DEMO/plans.sqlite" \
  --presentation-store "$DEMO/presentations.sqlite" \
  --proposal-store "$DEMO/proposals.sqlite" \
  --owner-facts "$DEMO/owner-facts.json" \
  --switchyard-profile "$MAUDE_SRC/docs/examples/openrouter-authoring-profile.json" \
  --switchyard-state "$DEMO/switchyard.sqlite" \
  --switchyard-credential-file "$OPENROUTER_CREDENTIAL_FILE" \
  --port 8427
```

This prepares the route only. Do not run it with a real credential until the
call has separate authorization. Credential loading is lazy: a nonexistent
absolute credential path is sufficient to inspect that the enrolled selector is
present, but submitting it refuses without a valid operator-provisioned key.

Open `http://127.0.0.1:8427/phosphor/design/drafts/draft_dependency_chain`,
select node `pn_verify_health`, then open **Agent proposals**. The selector
includes `enrolled-switchyard` only because the profile and state flags above
are both present. A suitable bounded task is: "Clarify this step's description:
verify the service evidence; do not change dependencies or add work." Review
the displayed exact node scope and select `enrolled-switchyard`. Submit only
after the operator has authorized this task and the profile's one-call budget;
starting the server alone is not that authorization. Maude and Switchyard bind
and track the request through the enrolled path—there is no separate manual
admission command in this walkthrough. Inspect the resulting request identity,
before/after values, exact operation, semantic diff, base revision and scope.
If a call times out or refuses, inspect its recorded state before considering
another separately authorized request; do not resubmit automatically.
If a result is proposed, an explicit later
**Accept changes into draft** creates a Plan Core successor. Open **Checks** and
use **Check this revision** separately; acceptance and checking do not lock,
hand off, authorize, or execute anything.

## Credential-free review walkthrough

The following creates an absent local fixture directory with deterministic Plan
Core drafts. It contacts no provider and does not use the enrolled route:

```sh
DEMO=/tmp/maude-plan-core-demo
test ! -e "$DEMO"
PYTHONPATH=/tmp/maude/src \
  /tmp/maude-openrouter-venv/bin/python -m maude.design.demo "$DEMO"
PYTHONPATH=/tmp/maude/src \
  /tmp/maude-openrouter-venv/bin/phosphor-design \
  --store "$DEMO/plans.sqlite" \
  --presentation-store "$DEMO/presentations.sqlite" \
  --proposal-store "$DEMO/proposals.sqlite" \
  --owner-facts "$DEMO/owner-facts.json" \
  --port 8427
```

Open `http://127.0.0.1:8427/phosphor/design/drafts/draft_dependency_chain`.
Choose **Propose edit**, select a deterministic fixture scenario, and review the
before/after values and exact semantic diff. **Accept changes into draft** is a
separate deliberate local CAS action: it creates one successor in that local
fixture store. It is not a human acceptance of any retained provider proposal,
and it does not check, lock, compile, hand off, authorize, or execute a plan.

Both `--switchyard-profile` and `--switchyard-state` are required together.
Without them, only deterministic fixture scenarios are available. Provider
completion creates at most proposed
bytes for validation and ordinary diff review. Only a later explicit human
accept action can create a Plan Core successor; it still does not check, lock,
compile, hand off, authorize, or execute the plan.

While an enrolled generation is in flight, open **Active proposal generation**
from the draft in a second same-origin browser request to inspect its exact
generation and request identities or request local cancellation. Cancellation
is recorded before Maude signals its caller. It prevents a late result from
becoming an acceptable proposal, but does not claim that an already-contacted
provider stopped work. A completed generation and a previously human-accepted
revision cannot be cancelled.

The direct route applies one parent total deadline around the canonical
transport child and polls the request-local cancellation callback while that
child is running. A deadline or local cancellation bounds Maude's wait and
fails closed for proposal acceptance; it does not prove that an already-sent
remote request stopped, and the remote outcome may remain unknown.

The enrolled caller binds a strict public JSON Schema response format into the
v3 request digest. Switchyard validates and forwards that format exactly with
required-parameter routing, no model fallback, and no retry. Maude still parses
the returned bytes against its closed proposal and operation contracts; it does
not remove Markdown fences or repair malformed provider output.

The first authorized live call completed HTTP 200 but returned Markdown-fenced
JSON. Maude's strict parser refused it, and no proposal was accepted. After the
v3 structured-output compatibility repair, a separately authorized 003 call
returned one HTTP 200 result that Maude validated as a proposed, scope-bound
description-only edit. It remains unaccepted: it made no Plan Core successor,
check, lock, handoff, authorization, or execution. This is one bounded live
proposal/diff result, not a qualification of every provider/model/schema, a
public-only fresh installation, human interaction, or the synthetic-cache
workflow. Do not strip response fences, retry a retained occurrence, or infer
acceptance authority from provider completion.

Provisioning and launching do not authorize a provider call. Before any live
qualification, record the exact source/profile/state coordinates and separately
authorize the one call. Do not put credential material in that record.
