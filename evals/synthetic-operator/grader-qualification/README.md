# Independent grader harness qualification

This area qualifies the measuring apparatus used by a future Maude synthetic
operator campaign. It is not a Maude operator campaign and it contains no Maude
UX or product finding.

The qualification is bounded to fixed evidence packets and, when provider
access is available, a small set of fresh grader-only probes. It does not rerun
or repair generation four, launch generation five, alter product behavior, or
authorize implementation.

## Frozen historical boundary

Generation four remains frozen at:

```text
evals/synthetic-operator/runs/maude-baseline-20260728T070428-0400/
```

Its Git subtree at the qualification starting commit
`52e4567412bc2fda252d099b404bcc6b8e97c083` is
`397e317d9c33d29a4aa0f25b7618507e84c420cc`. The campaign remains
`aborted-independent-grading-incomplete`: 35 operator sessions completed,
29 of 35 independent grades were accepted, and findings consolidation remains
prohibited.

Nothing under the frozen run directory is an input that this qualification may
rewrite.

## Contents

- `BOUNDARY_ASSESSMENT.md` records the pre-repair evaluator boundary.
- `QUALIFICATION.md` defines the normative qualification contract.
- `allowed-tool-roster.json` is the machine-readable intended grader roster.
- `fixtures/` contains deterministic evidence packets and raw streams.
- `expected/` contains fixture oracles withheld from live graders.
- `scripts/` contains the qualification runners.
- `tests/` contains provider-free qualification tests.
- `results/` contains machine-readable deterministic and live results.
- `FINAL_REPORT.md` records the earned qualification disposition.

The deterministic and live layers are separate. Deterministic success proves
only parser, state, and admission behavior. Live success cannot prove a
structurally absent provider capability when the provider runtime still exposes
one.

## Recorded result

The deterministic layer passed all 12 fixed fixtures. Five fresh live provider
attempts then failed before grader evidence access because the exact OpenAI
response-format surface rejected the frozen output schema. No live grader
verdict was accepted and no attempt was retried.

The final machine result is
[`results/qualification-result.json`](results/qualification-result.json). Its
verdict is:

```text
NOT-QUALIFIED-VERDICT-VALIDATION
```

The independently observed Codex resource-discovery capability outside the
declared roster remains a residual provider limitation. Generation five
therefore remains closed.

Authority effect: none.
