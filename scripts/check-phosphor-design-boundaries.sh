#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
design="$root/src/maude/design"
operations="$root/src/maude/plan/operations.py"
proposal_protocol="$root/src/maude/plan/proposals.py"
proposal_service="$root/src/maude/plan/proposal_service.py"
provider="$root/src/maude/design/providers.py"

if rg -n '^(from|import) (ag_|nightshift|docket)' "$design" "$operations"; then
  echo "/design must not import governed runtime implementations" >&2
  exit 1
fi

if rg -n '(submit-intervention|AGSpend|AuthorizationV|Docket|dispatch\(|governed_intervention)' \
  "$design" "$operations"; then
  echo "/design must not expose authority, execution, or intervention machinery" >&2
  exit 1
fi

if rg -n '(canvas_x|canvas_y|viewport|zoom|selection|outline_percent|collapsed_node)' \
  "$root/src/maude/plan/document.py"; then
  echo "presentation fields must not enter PlanDocument" >&2
  exit 1
fi

if rg -n '(health_score|plan_health|percent_valid|quality_score)' "$design"; then
  echo "/design must preserve exact findings and receipts instead of synthetic health" >&2
  exit 1
fi

if rg -n '(selected_object|active_casework|outline_percent|collapsed_node)' \
  "$root/src/maude/plan"; then
  echo "casework and selected-object presentation state must stay outside Plan Core" >&2
  exit 1
fi

if rg -n '(PATCH /document|do_PATCH.*apply|operation_type.*retry|operation_type.*execute|operation_type.*handoff)' \
  "$design"; then
  echo "/design may expose only closed Plan Core operations" >&2
  exit 1
fi

if rg -n '(CompilerRegistry|\.compile\(|handoff_bytes)' "$design/server.py" "$design/render.py"; then
  echo "/design must not invent a workflow compiler or handoff" >&2
  exit 1
fi

if rg -n '(DraftStore|ProposalStore|save_successor|\.create\(|\.lock\(|\.check\()' "$provider"; then
  echo "model/provider code may only return proposal bytes; it cannot persist or actuate" >&2
  exit 1
fi

if rg -n 'save_successor' "$proposal_protocol" "$provider"; then
  echo "proposal parsing/provider code must not save PlanDocument revisions" >&2
  exit 1
fi

if ! rg -q 'edit_origin=EditOrigin.AGENT' "$proposal_service"; then
  echo "accepted agent edits must use the ordinary Plan Core revision boundary" >&2
  exit 1
fi

if rg -n '(\.lock\(|\.check\(|CompilerRegistry|handoff|nightshift|docket|submit.intervention)' \
  "$proposal_service" "$proposal_protocol" "$provider"; then
  echo "agent proposal acceptance cannot check, lock, compile, hand off, or reach governance" >&2
  exit 1
fi

if rg -n '(ai_generated|model_confidence|agent_approved|autonomous_ready)' \
  "$root/src/maude/plan/document.py"; then
  echo "PlanDocument must not acquire agent-specific semantic fields" >&2
  exit 1
fi

if ! rg -q 'apply_plan_operation' "$design/server.py"; then
  echo "semantic browser writes must pass through typed Plan Core operations" >&2
  exit 1
fi

echo "Phosphor-ng /design boundary check passed"
