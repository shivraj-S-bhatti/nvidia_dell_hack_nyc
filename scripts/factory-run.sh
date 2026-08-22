#!/usr/bin/env bash
# factory-run.sh -- FACTORY (#13): verdict the candidate family, then verify the harness.
#
#   bash scripts/factory-run.sh            # verdicts + evidence + verification
#   bash scripts/factory-run.sh --verbose  # per-check detail for every candidate
#
# Requires the depgraph artifacts (bash scripts/depgraph-build.sh) -- Factory measures
# the tessellated mesh and the derived grip stacks, it does not re-tessellate.
# No network at any stage. No model on the verdict path.
set -euo pipefail
cd "$(dirname "$0")/.."

ART=".artifacts/depgraph"
if [ ! -f "$ART/graph.json" ] || [ ! -f "$ART/mesh_vert.bin" ]; then
  echo "missing $ART -- run: bash scripts/depgraph-build.sh" >&2
  exit 1
fi

echo "==> 1/3 factory verdicts"
python3 tools/factory/validate.py --repeat 3 "$@"

echo
echo "==> 2/3 verify the harness"
python3 tools/factory/check_factory.py | tail -3

echo
echo "==> 3/3 verify the graph it measures"
python3 tools/depgraph/check.py | tail -1

echo
echo "evidence in .artifacts/factory/ -- verdicts/, feedback/, survivors.json"
