#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
compiler="$root/src/maude/plan/local_compose.py"
executor="$root/qualification/synthetic_cache/local_compose_executor.py"
qualification="$root/qualification/synthetic_cache"

if rg -n '^(from|import) (ag_|nightshift|docket)' "$compiler" "$qualification"; then
  echo "synthetic compiler/executor must use serialized owner boundaries" >&2
  exit 1
fi

if rg -n '(shell[[:space:]]*=[[:space:]]*True|os\.system|popen|eval\(|exec\()' "$executor"; then
  echo "closed local Compose executor must not invoke a shell or dynamic code" >&2
  exit 1
fi

if ! rg -q 'value\["action"\] not in \{"qualify", "teardown"\}' "$executor"; then
  echo "executor action vocabulary must remain qualify|teardown" >&2
  exit 1
fi

if rg -n '(authorization|standing|admissibility|AGSpend|capability|private_key)' \
  "$compiler" "$executor"; then
  echo "workflow representation/execution must not contain authority semantics" >&2
  exit 1
fi

if rg -n '(subprocess|docker|compose|Nightshift|Docket|AG)' \
  "$root/src/maude/design/providers.py"; then
  echo "agent proposal providers must not reach workflow or governed mechanics" >&2
  exit 1
fi

if ! rg -q 'operation == "reconcile"' "$executor" || \
   rg -n 'operation == "reconcile".*qualify|operation == "reconcile".*teardown' "$executor"; then
  echo "executor reconciliation must remain observation-only" >&2
  exit 1
fi

echo "Synthetic local-Compose workflow boundary check passed"
