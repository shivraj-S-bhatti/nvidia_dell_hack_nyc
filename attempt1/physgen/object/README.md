# NeoRacer object gate

This directory implements Issue #42's offline object-intake gate. The selected
target is the uniquely named `WING-MOUNT-L:1` occurrence in NeoRacer's rear-wing
subassembly. OpenCascade resolves it to one valid solid; its component and
occurrence IDs come from the source STEP hierarchy rather than mesh order.
This is the focused identity path required after the earlier whole-vehicle mesh
conversion left 671 of 1,136 render meshes unnamed (recorded in Issue #11).

Large upstream and derived CAD files remain under
`.artifacts/attempt1-physgen/object/`. Git tracks only strict schemas, manifests,
tests, hashes, and this replay code.

## Offline replay

From the repository root, after the pinned LFS object and local environment have
been cached:

```bash
.artifacts/attempt1-physgen/object/venv/bin/python \
  -m attempt1.physgen.object.prepare \
  --asset-manifest attempt1/physgen/object/fixtures/asset-manifest.json \
  --output-root .artifacts/attempt1-physgen/object \
  --offline
```

The command performs three full XCAF loads without repair, regenerates and
compares the 379-definition/647-occurrence identity manifest, loads the isolated
baseline component, verifies every recorded SHA-256, and writes
`evidence/replay.json`. It does not import a network client.

## Cache layout

The asset manifest pins upstream commit
`05d9c69a82f2867f2729125292c53cf93e8d3d08` and the 100,519,607-byte LFS STEP
object. Its offline location is:

```text
.artifacts/attempt1-physgen/object/
├── source/neoracer-hardware-files/
│   ├── LICENSE
│   └── full-vehicle/neoracer-full-vehicle.step
├── artifacts/sha256/<isolated-component-hash>.step
├── artifacts/sha256/<assembly-screenshot-hash>.png
├── evidence/
└── venv/
```

The source license is CERN-OHL-S-2.0. The selected support and load regions are
explicit demo test-fixture assumptions; they are not recovered vehicle loads and
do not support safety, aerodynamic, fatigue, or manufacturing claims.

## Fallback gate

The exact fallback is the verified S500 `BOTTOM-PLATE-S500` fixture from PR #36.
Select it if, within 90 minutes, a required NeoRacer LFS object is not available
offline, the STEP needs manual repair, target identity changes across three
loads, the target is not one valid solid, or its protected interfaces cannot be
isolated. The current pinned NeoRacer artifact passes those checks, so fallback
is retained but not selected.
