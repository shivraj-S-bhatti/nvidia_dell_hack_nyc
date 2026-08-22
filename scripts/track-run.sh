#!/usr/bin/env bash
# track-run.sh -- TRACK (#14): score Factory survivors on one frozen fixture.
#
#   bash scripts/track-run.sh [--survivors <manifest.json>] [extra args...]
#
# With no --survivors, Track generates its own stand-in candidate family so the
# stage is provable before Factory (#13) lands. Once Factory emits a
# track.survivor-manifest/1 document, pass it and nothing else changes.
#
# No network at any stage. Pure numpy/scipy, so this runs on ARM64/GB10 with no
# native build.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .artifacts/depgraph/mesh.json ]; then
  echo "==> depgraph artifacts missing; building them first"
  bash scripts/depgraph-build.sh
fi

echo "==> 1/3 evaluate"
python3 tools/track/evaluate.py --repeat 3 "$@"

echo
echo "==> 2/3 render evidence"
python3 tools/track/render.py 2>/dev/null || echo "    skipped (render.py unavailable)"

echo
echo "==> 3/3 verify"
python3 tools/track/check.py | tail -3

echo
echo "done."
echo "  .artifacts/track/track-report.json    every measurement, ranking, and gate record"
echo "  .artifacts/track/comparison.md        the table"
echo "  .artifacts/track/feedback-event.json  what goes back to Lab"
echo "  .artifacts/track/evidence.html        offline visual evidence sheet"
