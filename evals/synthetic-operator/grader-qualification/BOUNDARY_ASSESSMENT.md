# Generation-four independent-grader boundary assessment

Recorded before grader-harness changes. All code references in this assessment
refer to Maude commit
`52e4567412bc2fda252d099b404bcc6b8e97c083`.

## Disposition

Generation four failed closed for the six rejected grades, and its abort is
valid. The configured grader MCP shim exposed only the intended read-only
evidence tool, but the effective Codex model surface also exposed Codex's own
MCP resource-discovery tools. Five graders invoked
`codex/list_mcp_resources`. That action was not in the frozen roster.

The provider boundary was therefore broader than the declared one-tool
boundary. The harness preserved and rejected the attempts, but it did not
represent the violation as an explicit sticky contamination or procedure
state. Separately, ordinary grade admission did not require evidence-tool
reads, did not resolve citations, and did not mechanically distinguish all
non-determinate evidence conditions.

This is an evaluator-instrument result, not a Maude product result.

## End-to-end path before repair

1. **Grader-session construction.** `_grade_bundle` in
   `evals/synthetic-operator/harness/campaign_runner.py` selects the ordinary
   or installation rubric and schema, copies the permitted bundle, and embeds
   the assignment, rubric, taxonomy, operator prompts, numbered transcript,
   and observable-artifact index in the grader prompt. `run_grader` then
   creates a fresh private provider home, a fresh grader boundary, a read-only
   `/evidence` mount, and a new provider session.
2. **Provider capability declaration.** `CLAUDE_GRADER_TOOLS` declares
   `mcp__grader__evidence`. `_adapt_boundary_for_codex` configures the single
   MCP server `grader`, enables only its bare tool `evidence`, disables Codex
   shell and other optional action features, and records the configuration
   digest. Claude additionally receives an exact `--tools` value.
3. **Configured MCP exposure.** `claude_mcp_bridge.py` advertises only
   `evidence` in grader mode. It permits bounded `read` and `list` operations
   inside the read-only bundle, rejects traversal and symlinks, and has no
   command broker in grader mode.
4. **Invocation.** The provider receives the configured server plus the
   frozen prompts and output schema. The configured MCP shim receives the
   bundle but not provider credentials, source, shell, or network access.
5. **Raw-stream capture and action checking.** The Claude path validates the
   provider-reported roster and each `tool_use`. The Codex path writes and
   flushes provider JSONL, parses each event, permits only `mcp_tool_call`, and
   compares its server, tool, and arguments with the configured boundary.
6. **Admissibility validation.** Only after normal provider completion does
   `run_grader` normalize actions, parse the grade, validate its JSON schema,
   apply the limited contamination rules, write `grade.json`, and create the
   accepted-grade marker.
7. **Campaign acceptance.** The verifier rechecks completed grade markers,
   boundary records, action accounting, schemas, digests, and the source
   contamination rule. A failed provider attempt has no accepted grade and
   therefore cannot count toward campaign completion.

## What `codex/list_mcp_resources` was

It was actually exposed and invoked by the Codex runtime. It was not model
prose, a remembered name with no invocation, or a call routed through the
frozen grader shim.

The following frozen raw streams contain the out-of-roster request:

| Run | Raw event | Observed result |
|---|---|---|
| `maude-s11` | `grade/raw/grader.stdout.jsonl:3` | started; harness stopped the session |
| `install-i01` | `grade/raw/grader.stdout.jsonl:3-4` | completed with `{"resources":[]}` |
| `install-i04` | `grade/raw/grader.stdout.jsonl:3-4` | completed with `{"resources":[]}` |
| `install-i05` | `grade/raw/grader.stdout.jsonl:3-4` | completed with `{"resources":[]}` |
| `install-i07` | `grade/raw/grader.stdout.jsonl:3` | started; harness stopped the session |

For every one of those runs:

- `grade/raw/codex-mcp-boundary/proxy-ready.json` lists only `evidence`;
- `grade/raw/codex-mcp-boundary/proxy-trace.jsonl` has exactly the three MCP
  initialization and tool-list records and no resource or evidence call;
- `grade/raw/provider-auth-gate.json` records allowed server `grader`, allowed
  tool `evidence`, status `failed-closed`, and error
  `Codex MCP action differs from the exact roster`.

The result came from Codex's provider-internal resource tool, which Codex makes
model-visible whenever an MCP server is configured. It is distinct from the
MCP protocol's automatic `tools/list` handshake.

Consequently, the pre-repair records
`exact_provider_tool_allowlist_supported: true` and
`per_session_exact_tool_roster_supported: true` overstate the effective Codex
boundary. They describe the supplied MCP configuration, not the complete tool
surface seen by the model.

## Enforcement timing

Calls that reach the configured grader shim are checked before that shim
executes them. The extra Codex-internal action cannot be intercepted by the
shim. The outer harness detects it only after Codex has emitted it in the
provider stream. In three runs Codex had already serviced the resource call
before the buffered stream was processed.

The outer validator then raises immediately, terminates the provider, destroys
the copied credential home, and withholds the grade-complete marker. A later
valid call or answer cannot repair the attempt because execution stops.

This behavior is fail-closed but incompletely represented:

- the exact action remains in raw JSONL;
- the gate records a generic roster error;
- the gate's normalized `tool_actions` remains empty because rejection occurs
  before the action is appended;
- there is no explicit `prohibited_tool_attempted` field, normalized violation
  record, or sticky evaluator-procedure state.

## Contamination behavior before repair

Operator source contamination and retrospective-separation contamination are
mechanically derived and frozen in the grade bundle. Later grader behavior
cannot clear those flags.

The exact mechanical indeterminacy rule is narrower:

```text
bundle-inventory.json.source_evaluator_contamination == true
    requires
grade.scenario_verdict == "indeterminate"
```

Aggregate contamination otherwise requires the `evaluator contamination`
failure class and an evidence-cited finding, but retrospective contamination
alone can coexist with a determinate scenario verdict. The generated prompt
tells the grader not to draw a clean UX or authority inference, but it does not
state the source-contamination terminal requirement as plainly as the
validator enforces it. The rejected `install-i10` grade was schema-valid and
determinate; the validator correctly rejected it under this mechanical rule.

An out-of-roster provider action is a terminal procedural failure rather than
an explicit contamination object. It is effectively sticky because the process
is stopped, not because the state model proves stickiness.

## Evidence-state distinctions before repair

| Condition | Pre-repair representation |
|---|---|
| unavailable evidence | evidence-tool error response; no explicit terminal class |
| incomplete evidence | rubric says absent is unknown; no mandatory-read ledger |
| contaminated evidence | explicit source/retrospective flags; only source forces indeterminacy |
| contradictory admissible evidence | no mechanical detector or precedence rule |
| grader procedural failure | raw stream plus failed-closed gate and absent grade marker |
| unsupported citation | nonempty schema string only; no reference resolution |
| premature verdict | allowed if schema-valid; zero evidence calls can be accepted |

Because substantive transcript and artifact material is embedded directly in
the prompt, the pre-repair harness does not enforce the rule that a verdict may
rely only on evidence returned through admitted grader tools.

## Installation-shaped evaluations

Installation and ordinary graders use the same provider, model, configured
tool, credential, network, and command boundaries. Installation graders do not
receive shell or a broader tool roster.

Installation bundles are nevertheless larger and more tempting to explore:
they use a larger schema and rubric, include the full operator-documentation
tree, and can include source-boundary and redaction records. Four of ten
installation graders attempted resource discovery, compared with one of
twenty Maude-surface graders and none of five direct-runtime controls. That
distribution supports treating installation-shaped evidence as an important
qualification specimen; it does not by itself prove causation.

The pre-freeze grader surface probe did not exercise this risk. Its prompt
named the sole tool, exact operation, and exact evidence path, then validated
actions after the session.

## Repair boundary

The qualification work may:

- add a pure raw-stream and grade-admission validator;
- record an exact machine-readable roster and its digest;
- normalize every out-of-roster attempt before failing closed;
- make procedure and contamination state explicit and sticky;
- require mandatory evidence reads and resolve citations;
- distinguish unavailable, incomplete, contaminated, contradictory, and
  procedural states;
- make finite verdict and admission classes structural;
- exercise those properties with fixed streams and bounded fresh grader-only
  probes;
- correct future harness claims about Codex's effective capability surface.

It may not alter generation-four bytes, retry or replace its grades, weaken its
acceptance rule, change Maude product behavior or operator documentation, infer
Maude UX findings, or launch generation five.

Authority effect: none.
