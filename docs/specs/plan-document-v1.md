# `maude.plan-document/v1`

The canonical semantics, lifecycle, and nonclaims are in
[Plan Core](../PLAN-CORE.md). This file pins the closed v1 JSON shape.

```json
{
  "schema": "maude.plan-document/v1",
  "goal": "Configure the service",
  "workspace": "/srv/example",
  "submitter": {
    "kind": "human",
    "origin": "human_written",
    "author": "operator-1",
    "reference": null
  },
  "nodes": [
    {
      "id": "pn_inspect",
      "description": "Inspect the target",
      "depends_on": [],
      "work": null,
      "acceptance_criteria": [],
      "stop_conditions": []
    },
    {
      "id": "pn_apply",
      "description": "Apply the exact change",
      "depends_on": ["pn_inspect"],
      "work": {
        "write_paths": ["config/service.toml"],
        "commands": [{"program": "tool", "argv_prefix": ["apply"]}]
      },
      "acceptance_criteria": ["change is observable"],
      "stop_conditions": ["target identity changes"]
    }
  ],
  "constraints": {
    "declared_write_paths": ["config/service.toml"],
    "forbidden_paths": ["secrets/**"],
    "budget_tokens": 1000,
    "halt_if": null,
    "world_requirements": [
      {"id": "wr_service_available", "statement": "service remains available"}
    ]
  },
  "acceptance_criteria": ["service responds"],
  "execution_request": null,
  "source_envelope_ref": null
}
```

Object key order and pretty-printing above are illustrative. Semantic bytes are
the deterministic compact/sorted UTF-8 serialization. Object fields are
closed. Node order is semantic; `depends_on` is the only v1 edge and carries no
attributes. Pure presentation/layout data is forbidden and belongs in a future
sidecar.
