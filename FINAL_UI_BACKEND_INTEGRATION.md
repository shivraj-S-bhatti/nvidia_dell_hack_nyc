# autoauto frontend and backend integration

This is the root handoff for connecting the final two-screen UI to the local pipeline.

## Judged surface

- Final application: `frontend/index.template.html`
- Built application: `frontend/index.html`
- Assembly renderer: `examples/easyrc/viewer/`
- Data fixture: `frontend/run.sample.json`
- Build command: `python3 frontend/build.py path/to/run.json`
- Local URL: `http://127.0.0.1:4414/frontend/`

The UI has two screens only:

1. **Object** shows the assembly, the selected component, the request, dependency propagation, and local stage activity.
2. **Simulation** shows Factory eligibility, Track measurements, critique, and the human choice.

Do not reintroduce the nine-step workbench, an architecture diagram, or a transcript dashboard into the judged path.

## Current demo shortcuts

The recording flow is deterministic and works now, but two pieces are fixtures:

- The activity sequence is replayed in `frontend/index.template.html`.
- Selecting a candidate updates the screen but does not persist a `HumanSelection`.

Keep this replay as the fallback. Replace a fixture only after its real artifact can complete the same two-minute flow offline.

## Canonical pipeline

```text
Object
  -> Lab
  -> CAD Compile
  -> Factory
  -> Track
  -> Revision
  -> Human Review
```

Stage ownership is strict:

- **Object** identifies the assembly and target component.
- **Lab** proposes candidates. It does not declare them valid.
- **CAD Compile** produces inspectable geometry and compile evidence.
- **Factory** emits deterministic pass or fail verdicts.
- **Track** evaluates only `Factory` survivors.
- **Revision** creates children from measured feedback.
- **Human Review** is the only stage allowed to select a final candidate.

## Backend artifact boundary

Every completed run must be materialized as one portable `run.json`. The frontend must not infer state from filenames, terminal output, or prose.

Use `frontend/run.sample.json` as the UI-facing envelope. Preserve these top-level keys:

```text
schemaVersion
meta
object
problem
baseline
lab
factory
track
feedback
revision
compare
selection
evidenceTrail
```

The pipeline may keep its frozen entities in separate files. A final adapter should normalize them into the envelope without changing measured values.

| UI data | Producer | Required source |
|---|---|---|
| Assembly and target | Object | target component, stable ID, units, source hash |
| Request and constraints | Object / request normalizer | objective, protected interfaces, keep-outs, supports, loads |
| Candidate family | Lab | candidate ID, role, parent IDs, method, seed, geometry reference |
| Compile state | CAD Compile | compiled artifact hash, preview reference, compile failure |
| Eligibility and veto | Factory | verdict, reason code, measured value, threshold, implicated components |
| Ranking | Track | status, metrics, baseline delta, score, rank, fixture hash |
| Bounded retry | Revision | parent, feedback event IDs, requested changes, resulting child |
| Final action | Human Review | candidate ID, human decision, timestamp, optional comment |

Unknown, missing, or non-finite measured values should fail the adapter. Do not replace a missing number with LLM text.

## Existing stage commands

Build the object graph first:

```bash
bash scripts/depgraph-build.sh
```

Run Factory:

```bash
bash scripts/factory-run.sh
```

Important Factory outputs:

```text
.artifacts/factory/verdicts/*.json
.artifacts/factory/feedback/*.json
.artifacts/factory/survivors.json
.artifacts/factory/run.json
```

`survivors.json` is the only candidate input Track may consume. A failed candidate stays visible in the UI but cannot acquire Track metrics.

Run Track against the survivor manifest:

```bash
bash scripts/track-run.sh --survivors .artifacts/factory/survivors.json
```

Important Track outputs:

```text
.artifacts/track/track-report.json
.artifacts/track/feedback-event.json
.artifacts/track/evidence.html
```

After the adapter writes the final envelope:

```bash
python3 frontend/build.py .artifacts/design-run/run.json
```

This produces a self-contained `frontend/index.html`. No CDN or web service is required for playback.

## Activity dock contract

For the recorded demo, inject a saved ordered event list into `run.json`. A minimal event is:

```json
{
  "stage": "factory",
  "status": "completed",
  "message": "Vetoed 1 disconnected load path.",
  "startedAt": "2026-08-22T21:00:00Z",
  "completedAt": "2026-08-22T21:00:03Z",
  "evidenceIds": ["factory-verdict:candidate-03"]
}
```

Allowed display states are `waiting`, `running`, `completed`, `failed`, and `blocked`.

The dock shows stage-level facts, not hidden reasoning or chain of thought. Messages must summarize artifact-backed events such as compilation, a measured veto, a solver result, or a persisted selection.

Live transport is optional. If used, it must replay the saved event list after refresh so the demo is resumable. A local file-backed replay is preferable to a fragile WebSocket for judging.

## Assembly viewer bridge

The final shell embeds `examples/easyrc/viewer/?embed=1`. It accepts same-origin messages:

```js
frame.contentWindow.postMessage({
  type: "autoauto:select",
  component: "Chassis bottom",
  mode: "focus"
}, location.origin)

frame.contentWindow.postMessage({
  type: "autoauto:mode",
  mode: "exploded"
}, location.origin)

frame.contentWindow.postMessage({
  type: "autoauto:pulse"
}, location.origin)
```

Supported modes are `assembled`, `focus`, and `exploded`. The pulse is intentionally one-shot. Do not add permanent blinking.

When real compiled candidate geometry is available, preserve the same camera and component selection while swapping only the affected artifact. The full assembly should not jump or reset between baseline and candidate.

## Human selection

The final candidate action must create a real record before the UI says `COMPLETE`:

```json
{
  "schemaVersion": "HumanSelection/1",
  "candidateId": "cand-a-edge-scallops",
  "decision": "selected",
  "actorType": "human",
  "selectedAt": "2026-08-22T21:02:00Z",
  "comment": null
}
```

Do not auto-select Track rank 1. The UI may recommend it, but completion requires the explicit click and a persisted record.

## Integration acceptance

The backend integration is ready when all of the following pass with networking disabled:

1. A fresh run writes a valid `run.json`.
2. Every displayed metric is traceable to a saved Factory or Track artifact.
3. A Factory-rejected candidate is visible but cannot be selected or ranked.
4. Refreshing the UI can replay or resume the run without recomputing completed stages.
5. `Review on object` preserves the selected component and dependency neighborhood.
6. Selecting a survivor persists a `HumanSelection` before showing `COMPLETE`.
7. `python3 frontend/build.py .artifacts/design-run/run.json` succeeds.
8. The complete recording flow remains under two minutes.

## Truth boundary

Say `local component-level comparison fixture`, not vehicle certification or recovered race performance. Loads, supports, and material values remain declared demo assumptions unless a sourced artifact says otherwise.

LLMs may normalize a request or explain evidence. They may not author verdicts, physics values, rankings, or selection records.
