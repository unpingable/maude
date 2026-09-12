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

Install the public source-only Switchyard runtime at the exact reviewed
revision. It is a Python package rooted at `src/` and exposes
`switchyard-direct-api`; do not substitute an unrelated distribution with the
same import name:

```sh
git clone https://github.com/unpingable/switchyard-runtime.git /tmp/switchyard-runtime
git -C /tmp/switchyard-runtime checkout --detach b8f188f881f18a658860d34bc4f7b6b689f2025b
python3 -m venv /tmp/maude-openrouter-venv
/tmp/maude-openrouter-venv/bin/python -m pip install -e /absolute/path/to/maude
/tmp/maude-openrouter-venv/bin/python -m pip install /tmp/switchyard-runtime
git -C /tmp/switchyard-runtime rev-parse HEAD
/tmp/maude-openrouter-venv/bin/switchyard-direct-api --help
```

The `rev-parse` result must be
`b8f188f881f18a658860d34bc4f7b6b689f2025b`. Maude's core install does not
require the transitional `classic-rpc` extra. Make both source roots explicit
when launching so an ambient Switchyard package cannot be selected:

```sh
MAUDE_SRC=/absolute/path/to/maude
SWITCHYARD_SRC=/tmp/switchyard-runtime
PYTHONPATH="$MAUDE_SRC/src:$SWITCHYARD_SRC/src" \
  /tmp/maude-openrouter-venv/bin/phosphor-design \
  --switchyard-profile "$MAUDE_SRC/docs/examples/openrouter-authoring-profile.json" \
  --switchyard-state /absolute/private/path/switchyard.sqlite \
  --switchyard-credential-file /absolute/private/path/openrouter-key
```

This prepares the route only. Do not run it with a real credential until the
call has separate authorization.

Both `--switchyard-profile` and `--switchyard-state` are required together.
Without them, only deterministic fixture scenarios are available. In the
authoring page, the operator must explicitly select `enrolled-switchyard` and
submit a bounded proposal request. Provider completion creates at most proposed
bytes for validation and ordinary diff review. Only a later explicit human
accept action can create a Plan Core successor; it still does not check, lock,
compile, hand off, authorize, or execute the plan.

The enrolled caller binds a strict public JSON Schema response format into the
v3 request digest. Switchyard validates and forwards that format exactly with
required-parameter routing, no model fallback, and no retry. Maude still parses
the returned bytes against its closed proposal and operation contracts; it does
not remove Markdown fences or repair malformed provider output.

The first authorized live call completed HTTP 200 but returned Markdown-fenced
JSON. Maude's strict parser refused it, and no proposal was accepted. The
subsequent direct-request v3 structured-output repair has deterministic local
coverage but no successful live provider qualification. Do not describe v3 as
live-verified, strip response fences, retry that occurrence, or infer acceptance
authority from provider completion.

Provisioning and launching do not authorize a provider call. Before any live
qualification, record the exact source/profile/state coordinates and separately
authorize the one call. Do not put credential material in that record.
