#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
core="$root/src/maude/plan"

if rg -n '^(from|import) (ag_|docket|nightshift)' "$core"; then
  echo "Plan Core must not import governed authority/runtime implementations" >&2
  exit 1
fi

if rg -n '(canvas_x|canvas_y|zoom|viewport|selection|panel_layout)' "$core/document.py"; then
  echo "presentation/layout state must not enter PlanDocument semantic identity" >&2
  exit 1
fi

if rg -n 'os\.|random\.|datetime|Path\.cwd|getcwd|environ' "$core/compiler.py"; then
  echo "compiler contract must not read ambient process state" >&2
  exit 1
fi

if rg -n '"plan\.[^"]*(authorization|standing|admissibility|currentness)' \
  "$core/checks.py"; then
  echo "Plan checker must not claim governed-runtime judgments" >&2
  exit 1
fi

echo "Plan Core boundary check passed"
