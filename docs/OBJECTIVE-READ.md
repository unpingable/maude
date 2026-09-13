# Read an authored objective

`maude-plan objective-read --plan plan.json --expected-plan-digest sha256:…`
reads one exact `maude.plan-document/v1` file and emits
`maude.objective-source/v1`. Use the real plan digest from its authoring/lock
record. This command never initializes a Plan Core store or invokes a provider.

An available result contains the exact plan digest, authored goal and criteria.
Each criterion ID hashes canonical UTF-8 JSON with `plan_digest`, zero-based
`index`, and `text` (sorted keys, compact separators, unescaped Unicode).
Repeated text therefore remains distinct. The result groups only this exact
plan revision; it does not invent a cross-revision objective identity.

Missing, unreadable, oversized or invalid sources return `unavailable`; a changed
file or digest mismatch returns `conflicting`. These results omit authored
fields and use bounded error codes, without operational paths. Exit status zero
means a structured response was emitted, including unavailable or conflicting
results; inspect `availability`, not the process status. Argument or process
failure remains nonzero. The one-MiB input limit and regular-file
check refuse special files and final-component symlinks. The capture timestamp
is not evidence freshness or a claim about the running system.

Goal and criteria remain operator-only prose. Omitting workspace, submitter,
nodes and raw source does not make that prose public-safe. Public presentation
needs its own explicit approved-field projection. Read access, a matching
digest, or authored criteria establish neither legitimate reliance, completion,
acceptance nor execution permission. Condition assessments must come from their
actual owner; an absent assessment stays unknown.

Phosphor may join this source with exact Nightshift authoring provenance and
existing AG occurrence projections. A matching title, timestamp or pathname is
not a join key. The multi-component objective profile requires separate
qualification; this command alone is not a released end-to-end workflow.
