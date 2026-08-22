# EasyRC parts explorer + agent DB

A real, MIT-licensed vehicle (the [EasyRC](https://github.com/TRD-B/EasyRC) 1:16 RC car)
turned into three deliverables for the CAD + agent demo:

1. **A 3D viewer** (three.js) of all 46 car parts, grouped by subsystem, click-to-inspect.
2. **A MongoDB parts database** the agent queries to pick parts.
3. **Plain Python query functions** to wire into OpenClaw/NemoClaw as tools.

> The parts are real STEP (B-rep) geometry — **not parametric**. You can't pass a
> parameter and re-model; instead the car ships discrete **variants** (10T/15T crown gear,
> 16/24/25T spur gears, front/rear rim) the agent selects among. Metadata is derived
> (subsystem, material, bounding box, triangle count, variant family) — no hand-authoring.

## Layout

```
examples/easyrc/
  viewer/        index.html + app.js + bundle.js + parts.json + assets/*.glb  (runnable as-is)
  db/            ingest.py (STEP manifest -> Mongo) + part_db.py (agent query functions)
  convert/       convert.mjs (STEP -> GLB via occt-import-js) + package.json  (regeneration only)
  requirements.txt, UPSTREAM-LICENSE-MIT.txt, NOTICE.md
```

## 1. View the parts (no build needed)

The `viewer/` GLBs + `parts.json` are committed, so just serve the folder:

```bash
cd examples/easyrc/viewer
python3 -m http.server 8787
# open http://localhost:8787/index.html
```

Colored by subsystem, sidebar navigator, click any part for size / material / triangle count.

## 2. Load the parts database (MongoDB Community, local, no keys)

```bash
# start a local mongod (Community Edition) — macOS example:
mongod --dbpath /tmp/easyrc-mongo --port 27017        # or: brew services start mongodb-community

pip install -r requirements.txt
python db/ingest.py           # -> easyrc.parts (46 docs, indexed). MONGO_URI overrides host.
```

## 3. Agent query functions

`db/part_db.py` is a plain importable module — wire it into OpenClaw however you register tools:

```python
from part_db import query_parts, get_part, list_variants, list_subsystems

query_parts(text="gear", subsystem="drivetrain")   # filtered part records
query_parts(material="TPU-flex")                    # all flexible (printed-rubber) parts
list_variants("crown-gear")                         # interchangeable options + params
get_part("part-easyrc-24-teeth-gear")               # one full record
```

Each returns plain JSON-serializable dicts: `partId, name, subsystem, material, bboxMm,
longestMm, triangles, variantFamily, variantParams, glb, stepFile`.

Run `python db/part_db.py` for a live demo of all four functions against Mongo.

## 4. Regenerate the GLBs (optional)

Only needed if you change the source parts. Clone the upstream repo and run the converter:

```bash
git clone https://github.com/TRD-B/EasyRC.git    # STEP files live in "CAD files/Car"
cd examples/easyrc/convert && npm install
EASYRC_CAR="/path/to/EasyRC/CAD files/Car" node convert.mjs   # -> ../viewer/assets/*.glb + parts.json
```

Rebuild the viewer bundle (three.js) only if you edit `viewer/app.js`:

```bash
npm install three esbuild
npx esbuild viewer/app.js --bundle --format=iife --outfile=viewer/bundle.js
```

## Provenance & license

Car geometry is from **[TRD-B/EasyRC](https://github.com/TRD-B/EasyRC)** under the **MIT license**
(preserved in `UPSTREAM-LICENSE-MIT.txt`). See `NOTICE.md` for full attribution including the
[occt-import-js](https://github.com/kovacsv/occt-import-js) and [three.js](https://threejs.org)
tooling used to build the viewer.
