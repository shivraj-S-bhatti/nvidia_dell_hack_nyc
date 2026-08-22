# Attempt 1 CAD: S500 battery tray

> The FS-AI full-assembly intake and generated sensor-plate search are
> documented in [`../fsai/README.md`](../fsai/README.md). This bounded S500
> generator remains unchanged as a regression baseline.

This implements the final, superseding scope in GitHub issue #11: one
deterministic six-part battery-tray proxy, not a parser or editor for the full
S500 assembly.

## Contract and provenance

The only accepted request is:

```json
{"parameter": "trayWidthMm", "deltaMm": 10}
```

The generator produces a baseline revision and a changed revision. Each
revision has one six-solid STEP assembly for PartMode, one combined STL for a
web viewer, a manifest, stable part IDs, and a content-derived revision ID.

No vendor-native feature history or mates are claimed. Baseline dimensions are
measured in millimetres from the checked-in `S500-C1_ASM.step` whose verified
SHA-256 is
`c8d3bc53168bbfe29d7c49cfe49f8523844c5c12d6431a4ea0c30e8b2d851c36`:

- board envelope: 100 x 40.3 x 2
- pad envelope: 78.551819982 x 24 x 2
- screw columns: +/-35; screw rows: +/-12.5
- screw-head display envelope: 4.2 diameter x 1.3 high

The nominal M2.5 x 6 screw size and battery-mount relationship come from the
[PX4/Holybro S500 assembly guide](https://github.com/PX4/PX4-user_guide/blob/main/en/frames_multicopter/holybro_s500_v2_pixhawk4.md).
The screw thread is deliberately represented by its nominal cylindrical
envelope; cosmetic threads are outside this bounded contract.

The deterministic propagation is board width +10, pad width +10, both left
screws -5 on X, both right screws +5 on X, and matching board-hole movement.
MongoDB stores six stable part nodes, six `parameter_drives` edges, one request,
old/new values, and two revision records.

Schemas are in `schemas/`. Generated artifacts and retained measurements stay
under the gitignored `.artifacts/` directory.

## Local dependency and model inventory

- Python 3.12 on Linux ARM64
- CadQuery 2.8.0
- cadquery-ocp 7.9.3.1.1 (resolved ARM64 wheel)
- PyMongo 4.14.1
- MongoDB 8 in the local `attempt1-mongo` container
- no model is used in the geometry, propagation, validation, or persistence path

## Offline replay

After the pinned wheels have been installed into the local environment, the
demo-critical command needs no network:

```bash
.artifacts/attempt1-cad/venv/bin/python attempt1/cad/battery_tray.py \
  --request attempt1/cad/requests/widen-10mm.json \
  --output-root .artifacts/attempt1-cad/build \
  --mongo-uri mongodb://127.0.0.1:27017 \
  --result-json .artifacts/attempt1-cad/evidence/replay.json
```

Geometry-only replay omits `--mongo-uri`. Tests run with:

```bash
.artifacts/attempt1-cad/venv/bin/python -m unittest discover \
  -s attempt1/cad/tests -v
```

## Experiment evidence contract

The five-minute demo shows the baseline, applies the fixed request, and opens
the changed revision with a wider board and pad and four aligned screws. The
counterfactual is the unmodified 100 mm tray. Success is 6/6 valid closed
solids surviving STEP round-trip and 4/4 screw axes aligned after propagation;
wall-clock latency and peak resident memory are retained with the replay.

The 90-minute kill criterion is failure to export and re-import six valid
closed solids or failure of any of the four screw positions to match its board
hole without manual repair.
