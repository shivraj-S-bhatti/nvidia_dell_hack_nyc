# autoauto final demo

The recording surface is a two-screen local application:

1. **Object** selects the EasyRC chassis plate, starts a scripted local design loop, and shows dependency propagation in the assembled viewer.
2. **Simulation** presents the frozen Factory and Track evidence, including the rejected load path and the winning material layout.

The Object toolbar preserves direct `Assembled`, `Focus`, and `Exploded` views. Its BOM drawer reads the real 46-part catalog, groups it by subsystem, and focuses a rendered component when selected.

`Review on object` returns to the affected subassembly. The operator then promotes one Factory survivor and the dependency graph pulses once more.

## Run

From the repository root:

```bash
python3 frontend/build.py
python3 -m http.server 4414
```

Open `http://127.0.0.1:4414/frontend/`.

## Recording path

1. Hold on the assembled car and the `The object improves itself.` claim.
2. Click `Run iteration`.
3. Let the app transition to Simulation without interruption.
4. Click `Review on object`.
5. Choose `Edge scallops`.

The run is deterministic and intentionally compact. `frontend/nightshift.html` is not part of the judged path. The previous nine-step workbench remains available in git history at commit `3ed7f6c`.

## Data

`frontend/build.py` validates and inlines `run.sample.json`. The visible decision numbers are the merged Track evidence from `tools/track/README.md`, and the veto language follows the deterministic Factory and Track checks on `main`.

The EasyRC assembly is rendered by `examples/easyrc/viewer/`. Its embedded mode accepts a narrow `postMessage` interface for selection, view mode, and one-shot dependency pulses.
