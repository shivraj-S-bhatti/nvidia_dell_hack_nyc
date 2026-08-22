# track — one measured test, applied to every Factory survivor

Executes `TRACK` (#14). Track does not decide whether a candidate is *valid* —
that is Factory (#13). Track decides how the valid ones **score**, against the
baseline, on one frozen test that never changes between candidates.

Runs fully offline. numpy + scipy + stdlib only, no CAD kernel, no solver
binary, no native build anywhere on the path — so it runs unchanged on ARM64/GB10
alongside `tools/depgraph`.

## Run it

```bash
bash scripts/track-run.sh                       # evaluate, render, verify

python3 tools/track/evaluate.py --repeat 3      # measurements + repeatability
python3 tools/track/evaluate.py --survivors .artifacts/factory/survivors.json
python3 tools/track/check.py                    # the verification suite
python3 tools/track/render.py                   # offline visual evidence sheet
```

## The one test

**In-plane compliance of the `BOTTOM-PLATE-S500` footprint under a frozen
fixture** — a *stiffness proxy for material layout*.

| | |
|---|---|
| Domain | the real plate mesh projected onto its XZ design plane, 240 × 144 cells, 0.817 × 0.819 mm each |
| Model | 2D linear-elastic plane stress, Q4 bilinear elements, 2×2 Gauss, SIMP void floor 1e-9 |
| Supports | the four arm-to-plate bolted interfaces, both DOF held, 1376 fixed DOF |
| Load | 100 N spread over the central payload pad, two cases (+x, +z), 606 loaded nodes |
| Material | declared isotropic stand-in, E = 70 000 MPa, ν = 0.30, t = 2.0 mm |
| Solver | `scipy.sparse.linalg.spsolve` / SuperLU, 69 890 DOF, direct |
| Fixture hash | `sha256:8c4de1f737f9c821…` — carried on every result |

Compliance, peak displacement and material fraction come out; the ranking is
`specificStiffnessRatio = (C_base / C_cand) · (m_base / m_cand)`, stiffness per
unit material relative to baseline. Ties break on material ascending, then
compliance ascending, then id. Every displayed number is baseline-relative, so
the absolute load magnitude and the grid resolution cancel out of the comparison.

### The fixture is grounded in the assembly, not invented

`tools/depgraph` derives 20 fasteners clamping `BOTTOM-PLATE-S500`. Eight of them
belong to an `ARM-S500_ASM*` sub-assembly, and those cluster into exactly four
symmetric arm-to-plate interfaces at **(±45.07, ±45.07) mm**. Those are the
supports. Change the assembly and the fixture follows the geometry; if the
clusters stop resolving to four, `fixture.build()` raises rather than guessing.

The other twelve fasteners — landing-gear poles and nylon lock nuts — are real
and stay in the graph. They are not the arm load interface and are not used as
supports here. That is a declared modelling choice, not an oversight.

Two independent code paths agree on where those bolts are: **all 20 bolt centres,
placed from the STEP transform chain, land inside a void cell of the raster,
which is produced from the OCCT tessellation.** Each bolt sits in its own
clearance hole. Neither path knows about the other.

## Measured results

Baseline is the unmodified plate footprint on the identical domain and fixture.

| rank | candidate | compliance (N·mm) | vs base | material | vs base | specific stiffness | max disp (mm) | meets target |
|---|---|---|---|---|---|---|---|---|
| base | `baseline` | 0.23906 | 1.000× | 25056 cells | 1.000× | **1.000×** | 0.002345 | — |
| 1 | `cand-a-edge-scallops` | 0.25019 | 1.047× | 21918 cells | 0.875× | **1.092×** | 0.002414 | yes |
| 2 | `cand-c-diagonal-truss` | 0.72242 | 3.022× | 8612 cells | 0.344× | **0.963×** | 0.005494 | no |
| 3 | `cand-b-centre-window` | 0.31530 | 1.319× | 22372 cells | 0.893× | **0.849×** | 0.002626 | no |

Displayed target: material ≤ 0.90× baseline **and** compliance ≤ 1.25× baseline.

`cand-a` is **12.5 % lighter for 4.7 % more compliance** — better stiffness per
unit mass, and it meets the target. It is *not stiffer than the baseline*; it is
lighter for a small stiffness cost, and that is the whole claim.

`cand-b` removes slightly *less* material than `cand-a` and is **15 % worse per
unit mass**. It stays in the table. `cand-c` is the honest surprise: removing
66 % of the material tripled compliance, so aggressive lightening did not pay off
at this ratio.

**Gate.** `cand-d-severed-mount` is rejected upstream — `LOAD_PATH_DISCONNECTED`,
3 of 4 arm mounts reachable from the payload pad — and is never solved. That is
enforced in code, not assumed: `Manifest.assert_admissible` is called before
every solve, `Rejected` records carry no mask field at all, and `check.py`
includes adversarial tests that try to launder a rejected id into the survivor
list and to swap a mask's bytes.

**Repeatability.** 3 full runs, **max relative spread 0.0** across every
displayed measure, declared tolerance **1e-9**. The solve is a direct sparse
factorisation, so exact agreement is the expectation; the tolerance exists to
catch nondeterminism creeping in, not to absorb numerical noise.

**Timing.** Fixture build 1.59 s, evaluation 10.71 s for 5 candidates × 2 load
cases at 69 890 DOF, peak RSS 495 MB. Measured on **macOS arm64 / Python 3.9.6 —
this is a development laptop, not the GB10.** Every result stamps its own host
record, so a GB10 run is self-evidently a GB10 run. Re-measure there before
quoting a number on stage.

## Solver validation

The ranking is only worth as much as the solver, so the solver is checked against
closed-form answers rather than asserted to be correct.

| check | measured |
|---|---|
| Cantilever tip deflection vs Timoshenko (120×12) | **−0.513 %** |
| Uniform-strain patch test | **8.8e-15** relative |
| Mirrored-fixture symmetry | **3.1e-13** relative |
| `sum(element_energy)` vs `compliance` | **1.3e-12** relative |
| Element stiffness: symmetric, exactly 3 zero eigenvalues | yes |

The cantilever error is Q4 shear locking and converges monotonically
(40×4: −3.22 %, 120×12: −0.51 %, 400×40: −0.16 %).

**Known trap, documented not papered over:** SuperLU factors an under-constrained
system without complaint and returns a finite, meaningless answer. `fea.solve`'s
`finite` flag cannot see that. Track detects it separately — a candidate whose
compliance exceeds 1e6 × baseline is carrying load on the void floor, and its
state becomes `load_path_lost` rather than a number.

### The load path is where the physics says it is

The feedback below tells Lab to keep material on the payload-pad-to-arm-mount
paths. That is not an assertion about how plates ought to work — it falls out of
the baseline solve. Binning every solid cell by its distance to the nearest
payload-pad-to-mount line:

| distance from a load path | share of material | share of strain energy | energy density vs mean |
|---|---|---|---|
| 0 – 5 mm | 14.2 % | **55.0 %** | 3.86× |
| 5 – 10 mm | 15.1 % | 25.6 % | 1.70× |
| 10 – 20 mm | 25.5 % | 15.7 % | 0.62× |
| 20 – 40 mm | 27.9 % | 3.5 % | 0.13× |
| > 40 mm | 17.3 % | **0.2 %** | 0.01× |

The 17 % of the plate furthest from a load path carries two parts in a thousand
of the load. That is the material `cand-a` scallops away, and it is why it wins.

## Feedback to Lab

"It got worse" is not actionable. One Track result produces three measured things
Lab can use, written to `.artifacts/track/feedback-event.json`:

1. **A fair comparison.** `cand-a` removed 12.5 % of baseline mass for +4.7 %
   compliance; `cand-b` removed 10.7 % for +31.9 %. Per unit mass deleted,
   `cand-b` took out **4× as much load-carrying material** — same fixture, so the
   comparison is fair.
2. **Where the load went instead.** 6 764 cells that `cand-b` kept are now at
   ≥ 2× their baseline strain energy, centred at (−0.2, −38.1), (−0.4, +37.5) and
   (−22.1, 0.0) mm — the narrow webs left either side of the windows. This comes
   from the candidate's own solve, not from a first-order estimate.
3. **Where the mass was actually available.** 9.5 % of baseline mass sits in the
   lowest strain-energy decile and carries ~0 % of the load.

The first-order removal diagnosis (`payoffRatio`) is computed on the baseline
field and is labelled as first-order everywhere it appears, because removing
material redistributes load: it predicts the direction of a change well and its
magnitude only roughly.

## Files

| File | Role |
|---|---|
| `fea.py` | Q4 plane-stress solver on a regular grid, plus three closed-form validators. |
| `domain.py` | Part mesh → XZ occupancy raster; fastener world positions; clustering. |
| `fixture.py` | The frozen fixture: grid, material, supports from real bolts, loads, content hash. |
| `manifest.py` | `track.survivor-manifest/1` — the Factory → Track input contract, and the gate. |
| `candidates.py` | Track's stand-in candidate family, until Lab and Factory land. |
| `evaluate.py` | Solve, measure, rank, emit `TrackResult`s and the feedback event. |
| `render.py` | Occupancy, strain-energy and diff PNGs; one offline HTML evidence sheet. |
| `check.py` | The verification suite. Non-zero exit on any failure. |

## Input contract

Track reads exactly one document, `track.survivor-manifest/1`, and refuses
anything else — unknown keys included. `manifest.py`'s selftest prints the full
strictness matrix and `dump_manifest()` validates before writing, so a producer
cannot emit a manifest Track would later reject.

The hard invariant: **a Factory-rejected candidate cannot be evaluated.**
`Rejected` records have no mask field, so a vetoed candidate publishes no
geometry — there is nothing to measure even by accident.

Until Factory (#13) lands, `evaluate.py` with no `--survivors` generates the
stand-in family itself, labelled `producedBy: "track-fixture"` wherever it
appears. It runs exactly one check — load-path connectivity — so that the
rejection in the family is a real measurement rather than a line typed into JSON.

## What is deliberately not claimed

Track measures 2D linear-elastic plane-stress compliance, peak nodal
displacement, and material fraction on a frozen grid, under a fixture whose
supports, load magnitude, direction, and material are **declared demo test-fixture
assumptions, not sourced flight data**.

Not measured and therefore not claimed: strength, margin of safety, out-of-plane
bending, buckling, fatigue, flight loads, aerodynamic range, crash performance,
manufacturability, or certification. A candidate that scores better here has a
better material layout **for this test**. It is not "stronger", and nothing in
this pipeline says the S500 is airworthy.

Two further limits worth knowing before quoting a number:

- **Absolute compliance is resolution-dependent.** Only baseline-normalised
  comparisons at the frozen grid are claimed. Change `nelx`/`nely` and the
  fixture hash changes, which invalidates every retained result on purpose.
- **The projection is exact only for a prismatic extrusion.** Measured on this
  part: all 6 476 vertices lie on three Y planes, the body y ∈ [−2, 0] is a true
  2 mm extrusion, and the +0.1 mm raised pad sits strictly inside the silhouette
  — so the XZ projection *is* the cross-section here. A part with draft or bosses
  would need a Y-slice instead.

## See also

- `tools/depgraph/README.md` — the assembly graph this fixture is grounded in
- Issue #14 (TRACK), #13 (FACTORY), #12 (LAB), #1 (the epic and its boundary)
