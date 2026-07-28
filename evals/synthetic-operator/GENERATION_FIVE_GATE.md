# Synthetic operator generation-five gate

**Status:** closed

**Authority effect:** none

Generation four remains the preserved aborted measurement campaign at:

```text
evals/synthetic-operator/runs/maude-baseline-20260728T070428-0400/
```

Its governing result remains:

> Preserved aborted measurement campaign. No synthetic UX conclusion or installation-readiness conclusion was earned.

Generation five has not started. No generation-five operator session may run
until an acceptable independent-grader qualification result exists.

The current result is
[`grader-qualification/results/qualification-result.json`](grader-qualification/results/qualification-result.json):

```text
NOT-QUALIFIED-VERDICT-VALIDATION
```

The live qualification made five single-use provider attempts. The provider
rejected the frozen response schema before any grader read evidence or emitted
a verdict. Zero live grades were accepted. The attempts remain preserved and
will not be retried or salvaged.

Qualification is exact to its recorded tuple:

- live harness commit;
- result-finalization commit;
- provider and provider-runtime bytes;
- model and reasoning setting;
- grader prompts;
- declared tool roster;
- validator version;
- fixture suite and hidden oracles; and
- output schema.

A material change to any tuple member invalidates the result or requires a new
qualification generation. A new qualification result is not a generation-five
campaign and cannot reuse the five preserved attempts.

Even after an acceptable grader qualification exists, generation five is
eligible to run only when its result will bear on a real Maude decision. This
gate introduces no retry, replacement, quorum, or salvage policy for generation
four or generation five.

No Maude product behavior, UX conclusion, roadmap state, governance authority,
or implementation authorization follows from this gate.
