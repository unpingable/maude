# Agent guidance

Follow applicable workspace instructions. This guide describes this
repository's supported paths. Keep bounded edits on the ordinary workflow.
Maude's pre-alpha design flow is opt-in, not a routine-work prerequisite.

Use Plan Core when work benefits from durable revisions, structural checks,
semantic diff, and an exact lock receipt. Inspect the supported commands with
`maude-plan --help`; follow [`docs/PLAN-CORE.md`](docs/PLAN-CORE.md) and the
current [tutorial prerequisites](docs/CONSTELLATION-TUTORIAL.md). A valid,
locked, or accepted plan grants no authority. The classic supervised RPC path
is transitional and must not be represented as AG-NG compatibility.

For development, use `python3 -m venv .venv`, then
`.venv/bin/pip install -e ".[dev]"`. Run the default product suite with
`.venv/bin/python -m pytest`; it is scoped to `tests/`. The archived synthetic
operator fixtures under `evals/` are retained evidence and are not part of the
default product suite. Invoke an evaluation or its qualification checks only by
their explicitly documented path and prerequisites.

For prolonged qualification or capture work, use the campaign-approved durable
producer and recovery checkpoint; use a named transient user-systemd service
only when the campaign establishes that mechanism. After supervisor loss,
inspect and resume supervision of the original run before starting another.
Reconcile unclear execution or settlement with its owning runtime. If durable
custody is unavailable, use the documented fallback and state the evidence
limit. Tool or model availability never expands authorization.
