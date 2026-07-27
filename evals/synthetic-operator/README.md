# Synthetic operator evaluation corpus

**Status:** Empty evaluation scaffold. No synthetic operator run has been
performed and no result, finding, or UX verdict is implied.

**Authority effect:** None. Files retained here are evaluation inputs and
observations. They do not authorize a Maude run, settle runtime state, approve a
change, or alter Agent Governor authority.

The evaluation method and acceptance criteria are defined in
[`../../docs/SYNTHETIC-OPERATOR-EVALUATION.md`](../../docs/SYNTHETIC-OPERATOR-EVALUATION.md).
This directory is the durable repository location for exact prompts, scenario
fixtures, captured interactions, and machine-readable run metadata.

## Intended layout

```text
evals/synthetic-operator/
├── README.md
├── personas/
│   └── <persona-id>.md
├── scenarios/
│   └── <scenario-id>/
│       ├── README.md
│       ├── fixture/
│       └── expected-disposition.json
└── runs/
    └── <campaign-id>/
        └── <run-id>/
            ├── operator-prompt.md
            ├── supplied-inputs.json
            ├── transcript.jsonl
            ├── transcript.txt
            ├── metadata.json
            └── summary.json
```

Directories are created only when their first real artifact is added. This
README does not claim that the harness, personas, scenarios, runs, or findings
already exist.

## Exact prompts

`personas/<persona-id>.md` stores a reusable role prompt. A run also stores the
exact rendered prompt actually supplied as `operator-prompt.md`; a template
reference alone is insufficient because substitutions and evaluator preamble
can change the task.

The prompt record must identify every operator-facing document, packet,
endpoint, repository path, and artifact supplied at the start. Evaluator-only
expectations and hidden classifications do not belong in the operator prompt.

## Scenario fixtures

`scenarios/<scenario-id>/` contains deterministic fake operations work and its
evaluator-only expected disposition. Fixtures must contain no production
credentials, live endpoints, or secret material.

`expected-disposition.json` records the safe conclusion expected from the
observable facts, such as launch, refusal, escalation, discard, or terminal
unknown. It must not prescribe a hidden command sequence or coach the operator.

## Captured runs

Each `runs/<campaign-id>/<run-id>/` directory represents one fresh model
context. Raw and derived evidence remain separate:

- `operator-prompt.md` is the exact prompt sent to the synthetic operator.
- `supplied-inputs.json` inventories every visible input with its media type,
  byte length, and digest.
- `transcript.jsonl` is the lossless event-oriented interaction record.
- `transcript.txt` is a human-readable rendering of the same interaction.
- `metadata.json` records reproducibility and evaluator-contamination facts.
- `summary.json` records measurements, classification, and final disposition.

Do not edit a raw transcript to improve the story. If redaction is required,
retain a digest of the original in an access-controlled evidence location,
record the redaction explicitly, and keep the curated finding separate.

## Minimum run metadata

`metadata.json` must record at least:

- campaign ID, run ID, persona ID, and scenario ID;
- model provider, model identifier, model version when available, and relevant
  configuration;
- fresh-context confirmation;
- start and completion timestamps;
- Maude version or commit;
- underlying runtime/interface version or commit;
- exact supplied-input manifest;
- interface surface made available;
- whether source, logs, architecture notes, or evaluator hints were exposed;
- evaluator interventions, including `none`;
- restart, timeout, recovery, and transport conditions;
- transcript byte length and digest; and
- any missing or unavailable evidence.

`summary.json` must contain the measurement fields and one or more failure
classes defined by the evaluation specification. Unknown values remain
explicitly unknown; they are not coerced to false, failure, or success.

## Campaign findings

Raw run evidence stays here. Consolidated interpretation belongs in
`docs/SYNTHETIC-OPERATOR-FINDINGS.md`, created only after the first campaign.
That findings document must cite exact run IDs and transcript digests. It must
distinguish observations, evaluator judgments, proposed repairs, and earned
verdicts.

No evaluation is run as part of creating this scaffold.
