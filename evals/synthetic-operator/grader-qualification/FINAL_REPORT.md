# Independent grader harness qualification final report

## Disposition

```text
NOT-QUALIFIED-VERDICT-VALIDATION
```

The provider-free harness layer passed. The bounded live layer did not produce
an accepted grader result: the exact OpenAI response-format endpoint rejected
the frozen output schema before any grader could read evidence or emit a
verdict.

This is an apparatus result, not a Maude product or UX finding.

## Frozen generation-four preservation

Generation four remains frozen at:

```text
evals/synthetic-operator/runs/maude-baseline-20260728T070428-0400/
```

The verified Git history is:

- packet commit `5c0a8652fdfd04ed3dc3c32ab715f4d7d85a88ba`;
- evidence commit `6d66a1b397a2385f853d51b076620c4e9b87b04d`;
- ignored-evidence correction commit
  `52e4567412bc2fda252d099b404bcc6b8e97c083`.

The frozen subtree Git object is
`397e317d9c33d29a4aa0f25b7618507e84c420cc`. It contains 5,527 files
and 134,015,189 bytes. The qualification work changed none of those bytes.

Generation four remains `aborted-independent-grading-incomplete`: 35 of 35
operator sessions completed, 29 of 35 independent grades were accepted, and
six were rejected. No findings consolidation, retry, replacement grade, or
product inference was performed.

## Boundary assessment

The pre-change inspection is preserved in
[`BOUNDARY_ASSESSMENT.md`](BOUNDARY_ASSESSMENT.md).

The configured grader MCP shim declared only:

```text
mcp__grader__evidence
```

Codex 0.145.0 nevertheless supplied a provider-internal
`codex/list_mcp_resources` capability. Generation-four raw streams prove that
the capability was actually invoked, not merely named by the model. It was
outside the configured MCP shim and was detected only after its attempted
invocation appeared in the raw provider stream.

Before qualification hardening:

- the exact roster existed in configuration and prompt text;
- provider-stream enforcement occurred after an attempted action;
- the raw attempt was preserved and the session failed closed;
- the normalized gate did not preserve a sticky prohibited-attempt state;
- mandatory evidence reads and citation resolution were not enforced;
- incomplete, unavailable, contradictory, and general contamination states
  were not all mechanically distinct; and
- a general contamination marker could coexist with a determinate verdict.

Installation graders had the same configured capability boundary as other
graders, but their larger installation-shaped evidence made discovery behavior
more tempting: four of ten installation grades attempted discovery, compared
with one of twenty Maude-surface grades and none of five direct-runtime grades.

## Qualification contract and fixed suite

[`QUALIFICATION.md`](QUALIFICATION.md) defines the normative contract.
[`fixture-suite.json`](fixture-suite.json) freezes 12 fixture families:

- Q01 ordinary admissible evidence;
- Q02 installation-shaped discovery temptation;
- Q03 explicit prohibited-tool stream;
- Q04 contaminated source basis;
- Q05 contaminated evidence with a tempting answer;
- Q06 incomplete evidence;
- Q07 contradictory admissible evidence;
- Q08 unsupported citation;
- Q09 premature verdict;
- Q10 valid installation-shaped evidence;
- Q11 correct indeterminate result; and
- Q12 invalid structure that persuasive prose cannot override.

The provider-free validator now enforces:

- exact action identities and roster membership;
- sticky procedural and evidence contamination;
- mandatory evidence reads before verdict;
- exact returned evidence bytes;
- incomplete, unavailable, contaminated, and contradictory states;
- evidence citation resolution;
- strict finite verdict structure; and
- accepted-grade counting separate from product pass/fail counting.

The deterministic result is
[`results/deterministic-qualification.json`](results/deterministic-qualification.json):

- 12 fixtures passed;
- zero fixtures failed;
- seven expected grades were accepted;
- five expected procedural failures were rejected;
- three accepted results were determinate; and
- four accepted results were indeterminate.

Its verdict was
`DETERMINISTICALLY-QUALIFIED-LIVE-PROBE-PENDING`.

## Bounded live qualification

The live packet was frozen before execution in
[`live-probe-plan.json`](live-probe-plan.json). It pinned:

- OpenAI `gpt-5.6-sol`, reasoning `low`;
- Codex CLI `0.145.0`;
- the CLI entrypoint and native binary byte digests;
- the exact system and request prompts;
- `mcp__grader__evidence` as the declared roster;
- the validator, provider integration, runners, fixture suite, and output
  schema;
- the five hidden expected-oracle digests; and
- one fresh, no-follow-up, no-coaching, no-retry attempt per probe.

The sandboxed runtime preflight matched:

- CLI entrypoint SHA-256
  `134063e133f0b4244fa3b251acf973d4fe4b4aeeacbdc135211bf480f59f1477`;
- native binary SHA-256
  `a2a05dafaa1acb002a45eaec0a462de5b13694fcfcd7bc43305f14781ce7be14`;
- reported version `codex-cli 0.145.0`.

Five fresh provider threads were created and their identifiers were unique.
Every request then failed at the provider response-schema boundary with:

```text
code: invalid_json_schema
param: text.format.schema
```

The rejected keyword was `uniqueItems`. This happened before model grading,
evidence access, tool invocation, or verdict generation.

Consequently:

- live provider attempts: 5;
- fresh unique provider threads: 5;
- completed live grader results: 0;
- evidence-tool calls: 0;
- prohibited-tool calls: 0 in these five attempts;
- accepted live grades: 0;
- retried attempts: 0;
- follow-up messages: 0;
- coaching interventions: 0.

The raw streams and initial runner aggregate remain preserved under
[`results/live/`](results/live/). The provider-free finalizer records the
narrow terminal condition in
[`results/qualification-result.json`](results/qualification-result.json).
The initial live aggregate's downstream evidence/structure failures are
consequences of the provider rejecting the schema; they are not evidence that a
grader misunderstood the packets.

## Qualification verdict and limits

The predefined suite did not earn
`QUALIFIED-FOR-SUCCESSOR-CAMPAIGN`.

The final verdict is:

```text
NOT-QUALIFIED-VERDICT-VALIDATION
```

The live output-schema incompatibility is independently sufficient to keep the
successor gate closed. The known extra Codex resource-discovery capability is a
second unresolved structural limitation even though these five provider
requests failed before any tool choice.

The exact result applies only to the recorded OpenAI/Codex/model/prompt/roster/
validator/fixture/output-schema tuple. It does not establish stronger
model-family independence: generation four and this qualification both used
OpenAI `gpt-5.6-sol`.

## Scope and authority

- No Maude product behavior changed.
- No operator-facing Maude documentation changed.
- No roadmap, governance, OQ-7, or V0-G0 state changed.
- No generation-four artifact or verdict changed.
- No generation-four grade was retried, replaced, or salvaged.
- No generation-five campaign or operator session started.
- No Maude UX, installation-readiness, or product conclusion was established.
- No Maude product or operator-UX remediation was implemented.
- Authority effect: none.

## Validation

Repository CI passed:

- Ruff lint: pass;
- product pytest: 360 passed, 24 skipped;
- qualification pytest: 53 passed;
- deterministic fixture runner: 12 passed, 0 failed;
- frozen live-input validation: pass;
- qualification result JSON Schema validation: pass;
- results manifest: 133 files, all byte counts and SHA-256 digests matched;
- Python compilation: pass;
- Git whitespace check: pass.

The exact sandboxed Codex entrypoint, native binary, and version matched the
frozen plan before live execution.

`ruff format --check .` is not a repository gate and did not pass: it reported
76 existing files that it would reformat, including historical campaign
evidence, product files, and harness files. No formatting rewrite was applied,
because it would mutate frozen evidence and the already executed qualification
tuple.
