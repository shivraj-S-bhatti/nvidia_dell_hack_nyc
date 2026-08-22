# depgraph — CAD change-impact pipeline

Turns a STEP assembly into a dependency graph that answers **"if I change this
part, what else do I have to change?"** — with every claim traced to the geometry
that produced it.

Executes `ATTEMPT#DEP_GRAPH` (#23). Runs fully offline on ARM64/GB10: the STEP
parser is pure Python stdlib and tessellation is pure WASM, so there is no native
build anywhere on the path.

## Run it

```bash
bash scripts/depgraph-build.sh                       # full build, ~15 s
open s500-impact.html                                # 3D viewer

python3 tools/depgraph/work_order.py BOTTOM-PLATE-S500 --thicker 1.0
python3 tools/depgraph/work_order.py GB70-M2-5-6-DING
python3 tools/depgraph/work_order.py TOP-PLATE-S500 --thicker 0.5 --json
```

The viewer opens on a bounded demo change: increase the S500 bottom plate
thickness by 1 mm. **Preview change** applies a reversible local mesh delta,
focuses the selected plate, and shows the geometry-derived blast radius and
relative fastener actions. **Reset** restores the original mesh. This is a
candidate visualization, not a committed STEP/B-rep edit.

## What it produces

```
BLAST RADIUS -- 10 definitions, 62 occurrences, max hop 3
  hop  qty  part                 via        why
    0    1  BOTTOM-PLATE-S500    ANCHOR     selected for change
    1   28  GB70-M2-5-6-DING     FASTENS    shank r=1.200 collinear with hole r=1.500
    1   12  GB70-M3-8-DING       FASTENS    shank r=1.484 collinear with hole r=1.500
    ...
LENGTH ACTIONS -- 20 fasteners clamp BOTTOM-PLATE-S500, 20 need a longer part
  x8   GB70-M2-5-6-DING   lengthen M2.5x6 by 1 mm -> M2.5x8
  x8   GB70-M3-8-DING     lengthen M3x8 by 1 mm -> M3x10
```

## Files

| File | Role |
|---|---|
| `parse_step.py` | STEP AP203/214/242 → occurrences, world transforms, cylinders. Stdlib only. |
| `derive_edges.py` | `FASTENS` from geometry; measured grip stacks; length actions. |
| `build_graph.py` | Binds meshes to occurrences, writes `graph.json`. |
| `work_order.py` | Blast radius + length actions, human-readable or `--json`. |
| `build_viewer.py` | Inlines everything into one offline HTML file. |
| `load_mongo.py` | Persists to MongoDB (system of record). Traversal is *not* done here. |
| `step_to_mesh.mjs` | OCCT WASM tessellation, once, offline. |

## How an edge is derived

No language model touches the graph. A `FASTENS` edge exists when a fastener's
shank cylinder is collinear with a clearance hole on another part:

```
0 <= r_hole - r_shank <= 0.35 mm      a fit, not a through-passage
axis offset <= 0.60 mm                perpendicular distance between axis lines
axes parallel within 1.0 deg
```

Measured on `S500-C1_ASM.step`: M3 socket-head shanks sit at `r=1.484`, their
clearance holes at `r=1.500` — 0.032 mm diametral clearance, axis offset
**0.000 mm**. 72 edges, 52/52 fasteners matched.

Grip length comes from real mesh vertices inside a tolerance cylinder around the
fastener axis, clipped to the fastener's own axial span. Without that clip a screw
threading into a boss reports the full height of the part it enters (18 mm of arm
body for an M2.5×6), which is not grip — a fastener cannot clamp what it cannot reach.

## What is deliberately not claimed

- **Absolute fastener adequacy.** A tapped hole and a clearance hole are both
  `CYLINDRICAL_SURFACE`, and some mates go into parts outside the assembly
  (motors, nuts). The threaded member is not derivable, so no adequate/inadequate
  verdict is issued. **Relative length deltas are sound** and are what the work
  order reports.
- **Clamp joints.** The carbon tube is clamped by `JIA-GUAN`, not bolted, so it
  has no `FASTENS` edge and currently returns only itself. That is the `CLAMPS` /
  `CONTACTS` work in #26, not a bug being hidden.
- Anything about airworthiness, structural adequacy, thrust, or flight safety.

## Verified counts

| Measure | Value |
|---|---|
| Part definitions / occurrences | 38 leaf / **125** |
| `FASTENS` edges derived | **72** (52/52 fasteners) |
| Meshes bound to occurrences | **109 / 109** |
| `GB70-M2-5-6-DING` occurrences | **28** — agreed independently by the stdlib parser and OCCT |
| Propagation, 126 nodes | 0.012 ms |
| Propagation, 126k nodes | 27 ms, 153 MB |

## See also

- `docs/research/graph-store-decision.md` — why MongoDB + in-process, not Neo4j
- `docs/research/depgraph-context.md` — verified facts, invariants, guardrails
