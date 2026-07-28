# Fixed grader qualification probe

Fixture: `Q06`

Read `/evidence/evidence-packet.json` using only
`mcp__grader__evidence`. Read each item marked `required`, then follow the
packet's evidence-state rules, claim contract, and conflict records. Emit one
strict JSON grade.

No expected verdict, fixture oracle, prior run, implementation source, or
ambient repository material is supplied.
