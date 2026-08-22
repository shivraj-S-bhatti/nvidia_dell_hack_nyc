# frontend — The Night Shift workbench (issue #37 · execution path #39)

The integrated demo interface for the **PhysGen race-component optimizer**:

**Object → Design problem → Lab → Factory → Track → Feedback → Review → Approve → Export**

A NeoRacer suspension bracket is optimized by topology generation, corrected by
deterministic CAD/FEA checks, revised from measured feedback, and promoted by a
human — fully offline. Nine steps, mapped 1:1 to the requested demo flow.

## Run it

```bash
python3 frontend/build.py            # inlines run.sample.json -> frontend/index.html
open frontend/index.html             # opens offline, no CDN, ethernet-unplugged safe
```

Navigate with the left pipeline stepper, the **Back/Next** buttons, or **← / →**.

## The nine steps

| # | Step | Shows |
|---|------|-------|
| 1 | Assembly & target | NeoRacer in context + the isolated `BRK-SUS-07` bracket, material/units/hash |
| 2 | Design problem | `DesignProblem`: objective, SF constraint, protected interfaces, supports/loads, keep-outs |
| 3 | Generate candidates | Lab topology family as density fields, with parentage and method |
| 4 | Validate & veto | Factory passes two, **vetoes one** with the measured geometry reason on the field |
| 5 | Rank survivors | Track FEA table (mass / stress / safety factor / compliance) vs baseline |
| 6 | Revise weak candidate | One survivor revised from a `FeedbackEvent`, re-checked and re-scored |
| 7 | Compare lineage | Baseline · parent · failure · finalists side by side + a lineage tree |
| 8 | Approve design | Blocking `HumanSelection` |
| 9 | Export evidence | Hash-addressed `DesignRun` artifact trail + offline replay command; retain the bundle |

## Design system

One steel-neutral base, a single blue accent, and semantic pass/fail/warn only.
Stage hues (Lab/Factory/Track) are demoted to thin markers. 8px spacing grid,
fixed type scale, monospace for every numeric / ID / hash. Tokens live in the
`:root` block at the top of `index.template.html`; change them there, not inline.

Topology candidates are drawn as **density fields** rasterized deterministically
from a compact `topology` spec (struts / island / flaw) over the bracket domain —
the same shape a real `.density.npy` would render. Metrics never come from the
renderer; they come from the run.

## How it adapts to the real backend (issue #43 schema)

The UI is **100% data-driven** by one `DesignRun` object. It hard-codes nothing.

```
run.json  ──build.py──►  index.html   (run inlined into a <script>, offline-safe)
```

The backend's only frontend job is to emit `run.json` in the shape of
[`run.sample.json`](run.sample.json), whose keys are the frozen contracts:

| Key | Contract (#43) | Produced by |
|---|---|---|
| `object` | component manifest + target | Object (#42 / #11) |
| `problem` | `DesignProblem` | contract (#43) |
| `baseline`, `lab`, `revision` | `Candidate` | Lab (#44/#12) |
| `factory` | `FactoryVerdict` | Factory (#47/#13) |
| `track` | `TrackResult` | Track (#48/#14) |
| `feedback` | `FeedbackEvent` | feedback (#49) |
| `compare`, `selection` | `HumanSelection` + lineage | product (#50) |
| `evidenceTrail` | `DesignRun` | product (#50/#51) |

Wire-up when a stage lands: point its output at these fields, then
`python3 frontend/build.py path/to/run.json`. No UI change.

`run.sample.json` is a **fixture** (labelled as such in `meta.note`). Per the
Truth Rules in `AGENTS.md`, replace it with a real saved run before demoing — no
invented verdict, metric, or evidence.

## Files

| File | Role |
|---|---|
| `index.template.html` | the app: design tokens, layout, density renderer, 9 step renderers (`__RUN_JSON__` placeholder) |
| `run.sample.json` | the `DesignRun` data contract, filled with a placeholder NeoRacer run |
| `build.py` | inlines a run into the template → `index.html` |
| `index.html` | generated, self-contained, offline |
