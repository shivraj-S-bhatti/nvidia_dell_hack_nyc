#!/usr/bin/env bash
# neoracer-build.sh -- fetch NeoRacer and build the pipeline artifacts for it.
#
#   bash scripts/neoracer-build.sh
#
# NeoRacer is published by the Neobotics Foundation under CERN-OHL-S-2.0:
#   https://github.com/Neobotics-Foundation-Inc/neoracer-hardware-files
# The source files are large (96 MB STEP, 160 MB FreeCAD) and are NOT committed --
# GitHub rejects files over 100 MB without LFS, and AGENTS.md keeps generated and
# fetched assets in .artifacts/. This script reproduces them.
#
# Fetched through the Git-LFS media endpoint, so no `git lfs` install is required.
#
# Mesh comes from the FreeCAD source, not the STEP: occt-import-js reads
# neoracer-full-vehicle.step well enough to report every face and then triangulates
# none of them (1136 meshes, 0 vertices, exit code 0 -- four deflection
# configurations, identical result). The same geometry meshes normally as BREP.
set -euo pipefail
cd "$(dirname "$0")/.."

ART=".artifacts/neoracer"
OUT="$ART/fc"
BASE="https://media.githubusercontent.com/media/Neobotics-Foundation-Inc/neoracer-hardware-files/HEAD"
mkdir -p "$ART"

echo "==> 1/3 fetch NeoRacer (CERN-OHL-S-2.0)"
for f in full-vehicle/neoracer-full-vehicle.step full-vehicle/neoracer-full-vehicle.FCStd; do
  dest="$ART/$(basename "$f")"
  if [ -s "$dest" ]; then
    echo "    have $(basename "$f")"
  else
    echo "    downloading $(basename "$f")"
    curl -fsSL "$BASE/$f" -o "$dest"
  fi
done
head -c 21 "$ART/neoracer-full-vehicle.step" | grep -q 'ISO-10303-21' \
  || { echo "STEP looks like an LFS pointer, not content" >&2; exit 1; }

echo "==> 2/3 tessellate from the FreeCAD source + place with STEP transforms"
python3 tools/depgraph/fcstd_to_mesh.py \
  "$ART/neoracer-full-vehicle.FCStd" "$ART/neoracer-full-vehicle.step" "$OUT"

echo "==> 3/3 derive graph + grip stacks"
python3 tools/depgraph/build_graph.py "$ART/neoracer-full-vehicle.step" "$OUT"

echo
echo "done. Factory verdicts for this object:"
echo "  python3 tools/factory/validate.py \\"
echo "      --step $ART/neoracer-full-vehicle.step --art $OUT \\"
echo "      --contract tools/factory/fixtures/neoracer-object-contract.json \\"
echo "      --candidates tools/factory/fixtures/neoracer-candidates.json \\"
echo "      --out .artifacts/factory-neoracer"
