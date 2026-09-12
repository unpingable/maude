# Bounded authoring walkthrough

This is a credential-free walkthrough of Maude's actual Plan Core proposal and
review surface. It uses the deterministic fixture provider; it does not contact
a model, read a credential file, accept a proposal, or authorize work.

## Prepare the isolated local screen

The capture owner starts this foreground command through the campaign's durable
producer and recovery checkpoint; do not run it as an unattended shell job:

```sh
PHOSPHOR_DESIGN_PORT=28427 scripts/run-phosphor-design-demo.sh /tmp/maude-authoring-walkthrough
```

Open `http://127.0.0.1:28427/phosphor/design`. The generated corpus contains
real PlanDocument revisions, checker findings, proposal requests, proposal
refusals, semantic diffs, and accepted/rejected/stale examples. For a newcomer
screen, select `draft_node_finding`, inspect the finding-scoped proposal, then
select `draft_dependency_chain` to compare its useful and cycle-producing
candidates. Do not press **Accept changes into draft** for the frozen capture.

At 1430px and 390px viewport widths, retain only screenshots that show the
exact base/scope, semantic diff, rationale, and explicit accept/reject boundary.
Do not retain browser storage, request headers, user home paths, credential
configuration, or a live-provider result.

## No-call enrolled-authoring recipe

The optional enrolled selector is absent unless both `--switchyard-profile` and
`--switchyard-state` are supplied. Before any provider contact, the operator
must create a nonsecret JSON profile with the exact selected model, byte/time,
token, concurrency, fixed-price, and reservation limits. The dedicated key,
when separately authorized, belongs only at
`~/.config/constellation/openrouter.env` (0600), and is not read until an
explicit enrolled proposal-generation POST. This walkthrough does not supply
those options and never reads that file.

Completion from an enrolled provider would still be hostile proposal bytes:
Maude validates them, shows the same diff, and requires an explicit human
acceptance action. Completion is neither acceptance nor execution authority.
