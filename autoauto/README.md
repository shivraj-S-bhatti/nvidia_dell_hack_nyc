# autoauto · Issues #42–47

This folder hosts an isolated copy of the existing `autoauto` two-screen UI on
port **4514**. It builds from the real saved Object, contract, Lab, CAD-domain,
CAD-compile, and Factory artifacts under `.artifacts/attempt1-physgen/`.

The first view is the complete NeoRacer root assembly with all 647 physical
occurrences. Target isolation comes second. The BOM lists all 379 stable
component definitions and their occurrence counts. The opening assembly is a
local WebGL view: drag to rotate, scroll to zoom, right-drag to pan, and click
one of the 499 rendered leaf occurrences to select its stable Issue #42 ID.
The Assembled/Focus/Exploded control matches the other local viewer: Focus
isolates the selected target and Exploded animates the real occurrence meshes
apart without changing their saved source transforms.

The adapter validates artifact hashes, Issue #43 contracts, cross-stage IDs,
the complete four-record CAD family, the real Factory veto, and the survivor
boundary before it writes the UI. Track, revision, and human selection remain
explicitly pending because they are outside Issues #42–47.

Run from the repository root:

```bash
python3 autoauto/serve.py
```

Open `http://127.0.0.1:4514/`. The original `frontend/` UI can continue using
port 4414.

The checked interactive mesh is derived from the pinned NeoRacer STEP. Rebuild
it only when that source or its component manifest changes:

```bash
.artifacts/attempt1-cad/venv/bin/python autoauto/build_interactive_vehicle.py
```

Tests:

```bash
python3 -m unittest autoauto/test_integration.py
```
