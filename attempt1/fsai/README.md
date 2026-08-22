# Attempt 1 FS-AI: CAD-backed sensor-plate search

This adapts the existing deterministic CAD/search conventions to the official
2026 Formula Student AI vehicle. It is a Formula Student autonomous racecar,
not a Formula One team car. The full vehicle remains immutable context; the
only generated part is the named `Example Plate` in `Team Additional Sensor
Mounting`.

The downloaded source files stay under gitignored `.artifacts/`. The upstream
repository is copyrighted and asks that its CAD not be re-uploaded to other
public or cloud locations. This directory contains contracts and code, not the
source or derivative CAD files.

Source references:

- https://github.com/FS-AI/FS-AI_ADS-DV_CAD
- https://www.imeche.org/docs/default-source/1-oscar/formula-student/2026/rules/fs-ai-2026-rules-v1.pdf?sfvrsn=2

## Strict input and output contract

`requests/canary-27.json` defines a 27-candidate geometry canary.
`requests/long-4096.json` uses the same contract with a deterministic 4,096
candidate budget. Numeric ranges must contain the source baseline, stay inside
bounded limits, land exactly on their stop, and contain no unapproved fields.

Each run verifies the SHA-256 and geometry of the full assembly and three
connector STEP files. XCAF resolves the named plate and its 13-part mounting
subassembly. The source plate is reconstructed from measured local geometry:

- 350 x 350 x 3 mm bounding box
- six-sided outer profile with a 160 mm top edge
- four 6.5 mm holes at `(±150, ±100)`
- 338601.803131 mm³ source volume

The source profile is always candidate zero. Other candidates retain its ID as
their parent. Candidate selection is deterministic when a budget is smaller
than the full Cartesian product. A checkpoint is atomically retained after a
configurable number of candidates and `--resume` validates the saved IDs,
ordinals, and parameters before continuing.

The output directory contains the normalized request, source intake, all
variants, winner ancestry, and checkpoint. STEP/STL/manifest artifacts are
retained for the reconstructed source baseline and the three finalists, making
baseline-versus-change inspection direct. The separate
`attempt1_fsai_search` MongoDB database retains the same run/variant model
without altering the frozen S500 fixture database.
OpenCascade's wall-clock `FILE_NAME` timestamp is canonicalized in exported
STEP headers so identical finalist geometry also has a stable artifact hash.

## Evaluation boundary

Every candidate is a real CadQuery/OpenCascade solid. The evaluator checks
solid validity, four preserved mounts, the official 40 mm quick-release knob
envelope, and the 5 mm maximum plate thickness. Widths below 340 mm create real
knob-envelope failures and remain visible in the result.

Ranking minimizes measured CAD volume among geometrically valid candidates.
This is not FEA: material, payload, acceleration, displacement, safety factor,
and structural safety remain explicitly unevaluated as `physicsStatus:
not_run`.

## Local dependency and model inventory

- Python 3.12 on Linux ARM64
- CadQuery 2.8.0
- cadquery-ocp 7.9.3.1.1
- PyMongo 4.14.1
- MongoDB 8 in the loopback-only `attempt1-mongo` container
- no model, cloud service, PartMode, or Warp dependency in this path

## Offline replay

Canary:

```bash
.artifacts/attempt1-cad/venv/bin/python attempt1/fsai/fsai_plate_search.py \
  --request attempt1/fsai/requests/canary-27.json \
  --asset-root .artifacts/candidate-assets/fs-ai-ads-dv-2026 \
  --output-root .artifacts/attempt1-fsai/canary-output \
  --mongo-uri mongodb://127.0.0.1:27017 \
  --checkpoint-every 10 \
  --result-json .artifacts/attempt1-fsai/evidence/canary-replay.json
```

Long budget, after the canary passes:

```bash
.artifacts/attempt1-cad/venv/bin/python attempt1/fsai/fsai_plate_search.py \
  --request attempt1/fsai/requests/long-4096.json \
  --asset-root .artifacts/candidate-assets/fs-ai-ads-dv-2026 \
  --output-root .artifacts/attempt1-fsai/long-output \
  --mongo-uri mongodb://127.0.0.1:27017 \
  --checkpoint-every 50 \
  --result-json .artifacts/attempt1-fsai/evidence/long-replay.json
```

Add `--resume` to the same long command after an interruption. Tests run with:

```bash
FS_AI_ASSET_ROOT=.artifacts/candidate-assets/fs-ai-ads-dv-2026 \
  .artifacts/attempt1-cad/venv/bin/python -m unittest discover \
  -s attempt1/fsai/tests -v
```

## Experiment evidence contract

The five-minute demo loads the vehicle, identifies the plate and its mounting
hardware, shows 27 generated solids, preserves real clearance failures, and
opens the three finalist STEP files. The counterfactual is the unchanged
official `Example Plate`. The primary success metric is measured CAD volume
reduction while the same deterministic envelope checks pass.

The 90-minute kill criterion is any source hash/topology drift, unstable
candidate ID, missing failed candidate, failed finalist STEP round-trip,
checkpoint that resumes with different parameters, or unbounded peak-RSS
growth across repeated clean runs.
