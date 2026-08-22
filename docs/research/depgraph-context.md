# ATTEMPT#DEP_GRAPH — working context

Reference card for anyone (human or agent) executing #23 and its children
#24–#30. **Issues are execution truth.** This file holds verified constants,
invariants, and guardrails so they are not re-derived or drifted from. It is not
a backlog, a roadmap, or a task list — if you want to know what to do next, read
the issue.

---

## 1. What we are building, in one paragraph

A change-impact graph over a CAD corpus. A mechanic asks in plain language what
else must change, and gets a work order: affected parts at **occurrence** level,
a numbered teardown order, and substitution verdicts with numeric margins. Every
claim cites a derived edge. The demo asset is the Holybro S500 quadcopter
(`S500-C1_ASM.step`).

## 2. The one claim that must not be diluted

**We compute the graph. We do not extract it.**

Published GraphRAG asks a language model to read text and propose entities and
relations, inheriting every hallucination in that step. Here every structural
edge is a geometric predicate with a numeric tolerance and a reproducible reason
string, carrying the STEP entity ids that produced it. Any edge can be refuted by
hand.

The model is allowed in exactly two places:

1. **Front** — one sentence → one strict `ChangeRequest`, schema-validated.
2. **Back** — narrate a retrieved subgraph, every sentence carrying an edge id.

The model never proposes an edge, never ranks a consequence, never decides a
substitution is safe, and never names a part absent from the graph. If it emits an
unknown node id, reject the response and show the structured result instead.

## 3. Verified facts about `S500-C1_ASM.step`

Confirmed by parsing the actual file. Do not re-derive; do assert in tests.

| Measure | Value |
|---|---|
| Schema | `AUTOMOTIVE_DESIGN` (AP214), OCC 7.6 / FreeCAD export |
| `PRODUCT` (part definitions) | 38 |
| `NEXT_ASSEMBLY_USAGE_OCCURRENCE` | 125 |
| `ITEM_DEFINED_TRANSFORMATION` | 125 |
| `SHAPE_REPRESENTATION` | 101 |
| `ADVANCED_FACE` | 2,567 |
| `CYLINDRICAL_SURFACE` | 885 |
| `CIRCLE` | 1,209 |
| `CARTESIAN_POINT` | 44,959 |
| File size / lines | ~7 MB / 153,890 |

Assembly tree, four levels deep:

```text
S500-C1_ASM
├── ARM-S500_ASM ×4        -> S500-JIBI (SHELL + SOLID) + 5× GB70-M2.5-6
├── HANGER_ASM ×4          -> JIA-GUAN + HUAN-GUIJIAO + 2× GB70-M2.5-6
├── LANDING-GEAR-VERTICAL-POLE_ASM ×2
│                          -> GUAN-CHENG-S500 + JIA-LIANJIE + M3×25 + 4× M3×8 + nut
├── LANDING-GEAR-CROSS-BAR_ASM ×2
│                          -> tube + M3×21 + 2× M3×8 + 2× JIAO-EVA + JIAO-LIANJIE
│                             + 3× nut + 2× MAO-JIAO
├── TOP-PLATE-S500, BOTTOM-PLATE-S500 (PCB-POWER), BATTERY-MOUNTING-BOARD,
│   BATTERY-PAD, PYLONS ×2, CARBON-FIBER-TUBE ×4
└── loose: M2-5-GB819-8 ×4, NILONG-GB818-M3 ×4, NILONGZHU-M3-6 ×4, LM-M3-NILONG ×4
```

Occurrence counts per definition (top): `GB70-M2-5-6-DING` **28**,
`GB70-M3-8-DING` 12, `LM-M3-DING` 8, then `SOLID`/`SHELL`/`JIA-GUAN`/
`HUAN-GUIJIAO`/`CARBON-FIBER-TUBE`/`JIAO-EVA`/`MAO-JIAO`/`M2-5-GB819-8-DING`/
`NILONG-GB818-M3`/`NILONGZHU-M3-6`/`LM-M3-NILONG` at 4 each.

**The headline case: `GB70-M2-5-6-DING` is one definition with 28 occurrences.**
Change the definition, touch 28 physical locations across four arms and four
hangers. This is the demo's surprise and the reason the definition/occurrence
split exists.

## 4. Fastener fingerprints — the derivation trick

Verified per-part cylinder radii. This is what makes `FASTENS` derivable.

| Part | Shank r | Head r | Reading |
|---|---|---|---|
| `GB70-M2-5-6-DING` | 1.200 | 2.150 | M2.5 SHCS (GB/T 70 ≈ ISO 4762) |
| `GB70-M3-8-DING` | 1.484 | 2.700 | M3 SHCS |
| `GB70-M3-21-DING`, `GB70-M3-25-DING` | 1.484 | 2.700 | M3 SHCS, longer |
| `M2-5-GB819-8-DING` | 1.150 | 2.100 | M2.5 countersunk (GB/T 819) |
| `NILONG-GB818-M3` | 1.400 | 2.250 | M3 nylon pan head (GB/T 818) |
| `LM-M3-DING` | 1.250 bore | — | M3 nut |
| `NILONGZHU-M3-6` | 1.250 bore | 1.450 | M3 nylon standoff |
| `CARBON-FIBER-TUBE` | 4.000 ID | 5.000 OD | Ø10 × Ø8 tube |

Clearance-hole radii across the file: `r=1.500` ×178, `r=1.550` ×78 (M3);
`r=1.250` ×54 (M2.5); `r=1.484` ×134 is screw shank, not a hole.

**Rule:** a shank collinear with a hole where `0 ≤ r_hole − r_shank ≤ 0.35 mm` is
a fastening. M3 SHCS in an `r=1.500` hole is 0.032 mm diametral clearance. Shank
vs. head is disambiguated by radius rank within the part — larger coaxial radius
is the head.

## 5. Corrections already made — do not reintroduce

- **`d=16.0` / `d=19.0` cylinders are NOT the 2216 motor bolt circle.** They are
  landing-gear foot bores on `JIAO-EVA`, `JIAO-LIANJIE`, `JIA-LIANJIE`, and
  `GUAN-CHENG-S500`. The 2216 pattern is 16×19 mm **hole-centre spacing**, not a
  hole diameter. Find it by pairwise centre distances, not radii.
- The arm body geometry lives in `SOLID` (205 cylinders, 50 distinct M3-class
  axes, includes a 16.00 mm centre-to-centre pair). `SHELL` and `S500-JIBI` have
  no cylinders of their own.
- `TOP-PLATE-S500` has a 6-axis `r=1.550` group at 30.0 / 32.21 mm spacing.
- **The motor mount pattern is a candidate, not a confirmed fact.** #26 must
  confirm it against the published Holybro drawing before the demo asserts it.

## 6. Provenance tiers — never present a lower tier as a higher one

| Tier | Meaning |
|---|---|
| `authored` | Read directly from AP242 semantic PMI / GD&T / kinematics |
| `geometry` | Computed from the STEP file with a stated tolerance and reason |
| `standard` | Fastener tables — GB/T 70, 818, 819; engagement 1.5–2.0×D in polyamide |
| `catalog` | Published S500 V2 spec: 2216 KV920, 1045 props, 480 mm wheelbase, 782 g, PDB 60 A cont. / 100 A burst, BLHeli-S 20 A ESC |
| `assumption` | Everything else. Rendered as an explicit unknown, never as a fact |

**Motors, ESCs, propellers and the battery are not in the STEP file.** They are
`catalog` nodes bound to the arm motor-mount pattern, and the demo says so out
loud. Every consequence we claim as real — the 28 screws, arm, clamps, plates,
standoffs — is `geometry` tier.

## 7. Decision record

**Superseded on the graph store:** Neo4j is dropped. Traversal runs in-process,
MongoDB stays the system of record, and `s500-impact.html` is the visual. The
traversal was benchmarked at 0.012 ms (126 nodes) and 27 ms (126k nodes), which
removed the case for a graph server. Full reasoning and revisit triggers in
`docs/research/graph-store-decision.md`.


- **Neo4j Community 5.x** + **NetworkX** co-primary; **MongoDB** unchanged as
  system of record per #1. Chosen on offline ARM64 install risk, typed
  variable-length path expressiveness, free Browser visual — **not throughput**,
  which is irrelevant at this scale.
- **`$graphLookup` is not the reasoning engine**: single-collection, untyped,
  returns no paths, 100 MB per-stage cap with no spill. Fine for a BOM tree.
- **Kùzu rejected** only because upstream archived Oct 2025 (Apple acquisition).
  It is the second fallback if Neo4j will not install on ARM64.
- **Memgraph / ArangoDB / TigerGraph rejected** — no advantage here, weaker
  offline ARM64 story.
- Derivation writes backend-agnostic `nodes.jsonl` + `edges.jsonl`; loaders are
  thin. **The store is swappable, not a bet.**
- `pythonocc-core` is **optional** and explicitly off the critical path. If it
  fails to build on ARM64, `CONTACTS` degrades to bbox + face-sample proximity
  and the edge records the reduced precision. Do not spend the day rescuing OCC.

## 8. Invariants — violating any of these is a bug, not a tradeoff

1. An edge without `reason`, `tolerance`, `stepEntityIds`, and `tier` is invalid.
2. Derivation is deterministic — same corpus revision, identical edge ids.
3. The derived edge set is **bit-identical with GPU broad-phase on and off**. The
   GPU chooses which pairs to test; it never decides an edge.
4. A change request lands on a `PartDefinition`; a work order lands on
   `PartOccurrence`. Conflating them loses 27 of the 28 screws.
5. Cypher and NetworkX must return identical impacted sets. Unexplained
   divergence is never shipped.
6. `unknowns` and `mustVerifyByHuman` are required output fields. Empty on a
   multi-tier query means the solver is not tracking what it does not know.
7. Zero parts may appear in an answer that are not in the corpus.
8. Ambiguous part identity goes to the `identity_review` queue. Never guessed.
9. Every record carries `corpusRevision` and replays identically against it.
10. The gold set is frozen **before** any measurement is run.

## 9. Scale tiers

| Tier | Shape | Purpose |
|---|---|---|
| T0 | 1 assembly, 125 occurrences, 885 cylinders | Correctness, verified by hand |
| T1 | 10–50 assemblies, 10³–10⁴ occurrences | Cross-assembly identity, shared-part blast radius |
| T2 | 10⁵–10⁶ features (synthesised) | Broad-phase, incremental update, query latency |
| T3 | 10⁷+ | **Named as design target. Not claimed, not attempted.** |

Synthetic T2 measures throughput only — never correctness. The number that
matters most is **incremental update time at T2**; if it is not sublinear in
corpus size, say so plainly.

## 9b. Frontend — measured, not assumed

OCCT tessellation of `S500-C1_ASM.step`: **6,386 ms**, 109 meshes, 221,680
triangles, 224,294 vertices. Rendering 221k triangles is free (three.js budget is
1–5 M). **All the cost is tessellation.** An in-browser CAD kernel re-paying that
on every load is what stalls; PartMode/Replicad additionally targets parametric
*single shapes*, not 125-occurrence assemblies whose solids interpenetrate by
design.

Decision: tessellate once offline via `tools/depgraph/step_to_mesh.mjs`
(`occt-import-js`, **pure WASM → no ARM64 build risk**), ship a GLB, no CAD kernel
at runtime. Verified: 7.75 MB / 3.62 MB gzipped, node names are occurrence ids
like `ARM-S500_ASM/GB70-M2-5-6-DING#3`, and **28 `GB70-M2-5-6-DING` nodes match
the 28 NAUO records from the Python parse** — independent cross-validation of the
extraction and the join key.

The viewer derives nothing. #25's parse owns the authoritative 4-level tree and
125 occurrences; the GLB owns pixels. Join on
`(parentOccurrence, definitionName, ordinal)`, asserted in a test.

PartMode stays on Attempt 1 (#7 / #11) where typed mutation is the point. Note it
is **AGPL-3.0** (network copyleft) — fine for a demo, relevant before anything is
distributed.

## 10. Guardrails

This is a change-impact triage aid for a human mechanic. It does **not** certify
airworthiness, structural adequacy, thrust, flight time, fatigue life, or that a
modified aircraft is safe to fly. It claims no FEA or CFD it did not run. Derived
edges are geometric inferences with stated tolerances, not the original
designer's intent. Every output ends with what a human must verify, and a human
approval step gates the work order.

## 11. Kill criteria, consolidated

| If | Then |
|---|---|
| Neo4j will not install on ARM64 in 30 min | NetworkX loader, lose the Browser visual, keep correctness. Kùzu second |
| `FASTENS` stacks wrong for the arm joint in 45 min | `COAXIAL_WITH` + hand-authored joints for six demo joints, marked `assumption`, said on stage |
| `BLOCKS_ACCESS` not working in 30 min | Drop teardown order; keep blast radius + substitution |
| `CONTACTS` not working in 30 min | Drop it. The demo claim does not depend on it |
| GPU broad-phase not working in 30 min | CPU spatial hash; **remove** the Warp claim rather than weaken it |
| CPM weights not groundable in geometry in 30 min | Uniform weights, rank by hops, state that ranking is unweighted |
| Cross-file identity not working in 45 min | Single-corpus; record cross-assembly as unproven |
| Graph does not beat flat RAG at hops ≥ 2 | **It is internal tooling for #7 / #16 and is not pitched as the product** |
| Live integration unstable 90 min before lock | Run recorded fixtures end to end; state on stage what is live vs replayed |

## 12. Demo run-of-show — the two moments that matter

Full sequence is in #30. If short on time, cut steps 8 and 10 first. **Never cut:**

- **The surprise** — one definition, 28 screws, with the geometry shown behind it.
- **The offline proof** — pull the ethernet, re-run, identical output.

## 13. Sources

- Cypher variable-length paths — https://neo4j.com/docs/cypher-manual/current/patterns/variable-length-paths/
- Neo4j GDS offline plugin install — https://neo4j.com/docs/graph-data-science/current/installation/installation-docker/
- Neo4j ARM64 images — https://hub.docker.com/r/arm64v8/neo4j/tags
- MongoDB `$graphLookup` limits — https://www.mongodb.com/docs/manual/reference/operator/aggregation/graphLookup/
- Kùzu status / embedded design — https://thedataquarry.com/blog/embedded-db-2/
- Clarkson et al., Change Prediction Method / DSM — https://strategic.mit.edu/docs/2_28_JMD_131_081010_ChangePropagation.pdf
- KG construction from CAD repositories — https://dl.acm.org/doi/10.1016/j.aei.2022.101680
- AutoMate, learned CAD mating (prior art only) — https://arxiv.org/pdf/2105.12238
- Contact relation analysis for assembly — https://www.cad-journal.net/files/vol_14/CAD_14(6)_2017_720-733.pdf
- RAG vs GraphRAG systematic evaluation — https://arxiv.org/html/2502.11371v3
- AP203 vs AP214 vs AP242 — https://www.capvidia.com/blog/best-step-file-to-use-ap203-vs-ap214-vs-ap242
- Holybro S500 V2 spec — https://holybro.com/products/s500-v2-kit
- Thread engagement rules of thumb — https://blog.fieldfastener.com/2018/03/13/rules-of-thumb-for-thread-engagement
