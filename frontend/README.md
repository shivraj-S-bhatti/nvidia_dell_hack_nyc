# autoauto live design-loop UI

The frontend has three local screens:

1. **Object** shows the downloaded FS-AI Example Plate context.
2. **Request change** starts the bounded local pipeline immediately.
3. **Simulation** displays fresh candidate previews, STEP artifacts, Factory
   verdicts, Track measurements, revision ancestry, and the human choice.

The right-hand dock polls persisted backend status. Object, Lab, CAD Compile,
Factory, Revision, Track, and Human Review change only when the corresponding
worker stage updates the run artifact; the UI does not animate a synthetic
queue.

## Run

From the repository root:

```bash
python3 frontend/serve.py
```

Open `http://127.0.0.1:4414/frontend/`.

The live endpoints are:

- `GET /api/capabilities` reports the verified local adapter and runtime.
- `POST /api/runs` validates the request and starts one offline run.
- `GET /api/runs/<run-id>` returns persisted stage and result evidence.
- `GET /api/runs` lists recent runs.
- `POST /api/selections` accepts only a Factory/Track survivor and closes the
  human gate.

Each run is retained under `.artifacts/design-run/runs/<run-id>/`, including
the normalized request, candidate density fields and previews, generated STEP
files, logs, `status.json`, `run.json`, and (after review) `selection.json`.

## Verified scope

The live adapter currently supports only the downloaded **Example Plate** from
the FS-AI ADS-DV 2026 assembly. Its four mount interfaces are protected. The
request may choose a 20–80% material target; candidate generation and geometry
checks are deterministic.

Factory checks re-imported STEP validity, exactly one solid, protected mounts,
and a connected support-to-load path. Track evaluates only Factory survivors
with the same local OptimizeAnyTopology pyEDGE CPU plane-stress fixture. These
are comparative measurements, not vehicle certification.

`python3 frontend/build.py` still emits a standalone page with the explicitly
labelled fixture replay, but live execution and selection persistence require
`frontend/serve.py`.
