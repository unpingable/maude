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
git -C /tmp/switchyard-runtime checkout --detach e612e195bdafc193d022f99ce683cb73dfbd7287
python3 -m venv /tmp/maude-openrouter-venv
/tmp/maude-openrouter-venv/bin/python -m pip install -e /tmp/maude
/tmp/maude-openrouter-venv/bin/python -m pip install /tmp/switchyard-runtime
git -C /tmp/maude rev-parse HEAD
git -C /tmp/switchyard-runtime rev-parse HEAD
/tmp/maude-openrouter-venv/bin/switchyard-direct-api --help
```

The two `rev-parse` results must be, in order,
`8c943d77013b1916a157f32f0fccc0ed933be264` and
`e612e195bdafc193d022f99ce683cb73dfbd7287`. Maude's core install does not
require the transitional `classic-rpc` extra. Make both source roots explicit
when launching so an ambient package cannot be selected:

```sh
MAUDE_SRC=/tmp/maude
SWITCHYARD_SRC=/tmp/switchyard-runtime
PYTHONPATH="$MAUDE_SRC/src:$SWITCHYARD_SRC/src" \
  /tmp/maude-openrouter-venv/bin/phosphor-design \
  --switchyard-profile "$MAUDE_SRC/docs/examples/openrouter-authoring-profile.json" \
  --switchyard-state /absolute/private/path/switchyard.sqlite \
  --switchyard-credential-file /absolute/private/path/openrouter-key
```

This prepares the route only. Do not run it with a real credential until the
call has separate authorization.

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
Without them, only deterministic fixture scenarios are available. In the
authoring page, the operator must explicitly select `enrolled-switchyard` and
submit a bounded proposal request. Provider completion creates at most proposed
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
public-only fresh installation, or human interaction. Do not strip response
fences, retry a retained occurrence, or infer acceptance authority from provider
completion.

Provisioning and launching do not authorize a provider call. Before any live
qualification, record the exact source/profile/state coordinates and separately
authorize the one call. Do not put credential material in that record.
