#!/usr/bin/env bash
# depgraph-build.sh -- ATTEMPT#DEP_GRAPH (#23) offline build, end to end.
#
#   bash scripts/depgraph-build.sh [input.step]
#
# No network at any stage. Tessellation is pure WASM, so this runs on ARM64/GB10
# with no native build. MongoDB load is skipped automatically if it is not running.
set -euo pipefail
STEP="${1:-S500-C1_ASM.step}"
ART=".artifacts/depgraph"
cd "$(dirname "$0")/.."
mkdir -p "$ART"

echo "==> 1/4 tessellate  $STEP"
[ -d tools/depgraph/node_modules ] || (cd tools/depgraph && npm install --silent)
node tools/depgraph/step_to_mesh.mjs "$STEP" "$ART"

echo "==> 2/4 derive graph + grip stacks"
python3 tools/depgraph/build_graph.py "$STEP" "$ART"

echo "==> 3/4 build offline viewer"
if [ ! -f tools/depgraph/viewer/three-bundle.js ]; then
  (cd tools/depgraph && npx --yes esbuild viewer/three-entry.js --bundle --format=iife \
     --global-name=THREE --minify --outfile=viewer/three-bundle.js)
fi
python3 tools/depgraph/build_viewer.py "$ART" s500-impact.html

echo "==> 4/4 load MongoDB (optional)"
python3 tools/depgraph/load_mongo.py "$ART" 2>/dev/null || echo "    skipped (MongoDB not reachable)"

echo "==> verify"
python3 tools/depgraph/check.py | tail -3

echo
echo "done. open s500-impact.html, or:"
echo "  python3 tools/depgraph/work_order.py BOTTOM-PLATE-S500 --thicker 1.0"
