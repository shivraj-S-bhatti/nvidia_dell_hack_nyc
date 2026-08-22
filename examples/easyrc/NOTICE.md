# Provenance notice

## Source CAD geometry

The car part geometry (`viewer/assets/*.glb`, and the records in `viewer/parts.json` /
`db/ingest.py`) is derived from the **EasyRC** project:

- Repository: <https://github.com/TRD-B/EasyRC>
- License: **MIT** (preserved verbatim in `UPSTREAM-LICENSE-MIT.txt`)
- Original assets: per-part STEP (ISO 10303-21, AP214) files under `CAD files/Car`

The GLB meshes here are a tessellated conversion of those STEP solids; they are geometry
only (no design tree / parameters, which the upstream STEP files do not carry).

## Build tooling

- **occt-import-js** (<https://github.com/kovacsv/occt-import-js>) — WASM OpenCASCADE STEP
  reader used to tessellate STEP into meshes. Used at build time; not redistributed here.
- **three.js** (<https://threejs.org>, MIT) — bundled into `viewer/bundle.js` for rendering.

## Derived metadata

Subsystem grouping, material tag (PLA-rigid / TPU-flex), bounding boxes, triangle counts,
and variant families are derived mechanically from the STEP files and part names. They are
approximate demonstrator metadata, not manufacturer specifications.
