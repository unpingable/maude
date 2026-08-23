#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
compiler="$root/src/maude/plan/local_compose.py"
executor="$root/qualification/synthetic_cache/local_compose_executor.py"
qualification="$root/qualification/synthetic_cache"
observation="$root/src/maude/plan/world_observation.py"
requalification="$qualification/build_requalification.py"
qualification_contract="$qualification/QUALIFICATION.md"

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

if rg -n '(subprocess|os\.system|Popen|shell[[:space:]]*=)' "$requalification"; then
  echo "C2 Plan Core builder must not execute qualification or container mechanics" >&2
  exit 1
fi
for boundary in 'apply_plan_operation' 'save_successor' 'store.check' 'store.lock'; do
  if ! rg -Fq "$boundary" "$requalification"; then
    echo "C2 builder bypassed ordinary Plan Core boundary: $boundary" >&2
    exit 1
  fi
done
if rg -n '(equivalent_artifact|carry_forward_qualification|reuse_qualification)' \
  "$compiler" "$requalification"; then
  echo "synthetic workflow introduced forbidden qualification equivalence" >&2
  exit 1
fi

if ! rg -Fq 'It has no deploy-only' "$qualification_contract" || \
   ! rg -Fq 'does not claim that pre-Q2 C2 was deployed as' "$qualification_contract"; then
  echo "synthetic V1 deployment/qualification atomicity contract is missing" >&2
  exit 1
fi
if rg -n '(deploy_only|unqualified_observation_target|qualification_carry_forward)' \
  "$compiler" "$executor" "$requalification"; then
  echo "synthetic workflow introduced a deploy-only target or qualification carry-forward semantic" >&2
  exit 1
fi

if rg -n '(subprocess|docker|compose|Nightshift|Docket|AG)' \
  "$root/src/maude/design/providers.py"; then
  echo "agent proposal providers must not reach workflow or governed mechanics" >&2
  exit 1
fi

if rg -n 'subprocess|os\.system|Popen|urlopen|socket|submit.intervention|AGSpend' \
  "$observation"; then
  echo "world-observation adapter must only transform exact retained artifacts" >&2
  exit 1
fi

if ! rg -q 'build_observation\(' "$observation" || \
   ! rg -q 'seal_handoff\(' "$observation"; then
  echo "world-observation source validation and custody sealing must remain explicit" >&2
  exit 1
fi

if rg -n '"(currentness|standing|authorization|spend|capability)"[[:space:]]*:' \
  "$observation"; then
  echo "world-observation candidate must contain no governed authority fields" >&2
  exit 1
fi

if ! rg -q 'operation == "reconcile"' "$executor" || \
   rg -n 'operation == "reconcile".*qualify|operation == "reconcile".*teardown' "$executor"; then
  echo "executor reconciliation must remain observation-only" >&2
  exit 1
fi

echo "Synthetic local-Compose workflow boundary check passed"
