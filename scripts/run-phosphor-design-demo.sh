#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
demo_root="${1:-$(mktemp -d /tmp/phosphor-design-demo.XXXXXX)}"
port="${PHOSPHOR_DESIGN_PORT:-8427}"

PYTHONPATH="$root/src" "$root/.venv/bin/python" -m maude.design.demo "$demo_root"

echo
echo "Open: http://127.0.0.1:${port}/phosphor/design"
exec env PYTHONPATH="$root/src" "$root/.venv/bin/python" -m maude.design.server \
  --store "$demo_root/plans.sqlite" \
  --presentation-store "$demo_root/presentations.sqlite" \
  --proposal-store "$demo_root/proposals.sqlite" \
  --owner-facts "$demo_root/owner-facts.json" \
  --port "$port"
