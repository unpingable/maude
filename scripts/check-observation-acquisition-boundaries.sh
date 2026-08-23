#!/usr/bin/env bash
set -euo pipefail

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
orchestrator="$root/src/maude/plan/observation_acquisition.py"
passive="$root/src/maude/plan/steady_state_observation.py"

if rg -n '^(from|import) (ag_|nightshift|docket)' "$orchestrator"; then
  echo "acquisition orchestrator imports a governed authority implementation" >&2
  exit 1
fi

if rg -ni '(cron|periodic|monitor.registry|alert.routing|shell=True|os\.system|def (create|mint|seal)_currentness|AgSpend|DocketDispatch)' "$orchestrator"; then
  echo "acquisition orchestrator contains monitoring, shell, currentness, or authority surface" >&2
  exit 1
fi

if rg -n '^(from|import) (ag_|nightshift|docket)' "$passive" \
  || rg -n '(shell=True|os\.system|subprocess\.(Popen|call|check_call|check_output))' "$passive"; then
  echo "passive adapter imports authority or exposes a dynamic command surface" >&2
  exit 1
fi

if [[ $(rg -c 'subprocess\.run\(' "$passive") -ne 2 ]] \
  || ! rg -Fq '"ps",' "$passive" \
  || ! rg -Fq '"exec",' "$passive" \
  || ! rg -Fq 'PASSIVE_HTTP_PROBE_SOURCE' "$passive"; then
  echo "passive adapter must contain only fixed Compose ps and front HTTP probe reads" >&2
  exit 1
fi

if rg -n '"(stop|start|restart|down|up|kill|rm)"[),]' "$passive"; then
  echo "passive adapter contains an effectful container lifecycle verb" >&2
  exit 1
fi

if rg -n '"(single_cache_failure_survived|cache_topology_restored)"' "$passive"; then
  echo "passive adapter can emit effectful qualification claims" >&2
  exit 1
fi

for claim in front_door_reachable cache_a_present cache_b_present ordinary_cache_behavior_observed; do
  if ! rg -Fq "\"$claim\"" "$passive"; then
    echo "passive adapter lost closed claim $claim" >&2
    exit 1
  fi
done

if [[ $(rg -c 'subprocess\.run\(' "$orchestrator") -ne 2 ]] \
  || rg -n 'subprocess\.(Popen|call|check_call|check_output)' "$orchestrator"; then
  echo "acquisition orchestrator command surface is no longer the two fixed owner CLIs" >&2
  exit 1
fi

if rg -n '(fresh_until|evidence_ttl|currentness_status)[[:space:]]*=' "$orchestrator"; then
  echo "acquisition orchestrator appears to construct Nightshift currentness" >&2
  exit 1
fi

for law in \
  'post_settlement' \
  'reobserve_for_successor' \
  'reobserve_after_stale' \
  'transport replay does not refresh evidence time' \
  'local-Compose v1 adapter cannot re-observe' \
  'passive adapter accepts only bounded re-observation' \
  'basis_evaluated_at_unix_ms'; do
  if ! rg -Fq "$law" "$orchestrator"; then
    echo "acquisition contract lost law: $law" >&2
    exit 1
  fi
done

if ! rg -Fq 'class NightshiftCliCustodyPort' "$orchestrator" \
  || ! rg -Fq '"external-observation",' "$orchestrator" \
  || ! rg -Fq 'import_verb = "import"' "$orchestrator" \
  || ! rg -Fq 'import_verb = "import-steady-state"' "$orchestrator"; then
  echo "Nightshift custody invocation is no longer a fixed closed command" >&2
  exit 1
fi

if ! rg -Fq 'def inspect_docket(' "$orchestrator" \
  || ! rg -Fq '"governed-loop",' "$orchestrator" \
  || ! rg -Fq '"inspect",' "$orchestrator"; then
  echo "post-settlement trigger no longer comes from the closed Docket inspection command" >&2
  exit 1
fi

echo "Observation acquisition boundary check passed"
