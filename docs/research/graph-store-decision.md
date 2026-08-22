# Graph store decision — ATTEMPT#DEP_GRAPH

Decision record for how `ATTEMPT#DEP_GRAPH` (#23) stores and traverses the derived
dependency graph. Written because the team split between MongoDB and Neo4j, and
neither answer turned out to be the right one.

**Status:** decided, with a measured revisit trigger.
**Supersedes:** the "Neo4j Community + NetworkX co-primary" line in #23. That
recommendation was made before the traversal was benchmarked. See §7.

---

## 1. Decision

> **Traversal runs in-process. MongoDB is the system of record. Neo4j is dropped.**

Confirmed by the team after the viewer was working: no Neo4j, MongoDB plus the
custom viewer. The viewer renders the graph *against the geometry*, which is
strictly more useful for the demo than a node-link diagram with no drone attached
to it, so the one real argument for Neo4j went away.

| Layer | Choice | Why |
|---|---|---|
| **Traversal / reasoning** | In-process graph in JS or Python (adjacency map + BFS) | Returns *paths*, not just reached nodes. Sub-millisecond at fixture scale, 27 ms at 126k nodes. No service to install. |
| **System of record** | **MongoDB**, unchanged per #1 | Runs, lineage, artifacts, evidence, the identity-review queue. Already committed, already on the HDD, one less ARM64 install. |
| **Visualisation** | `s500-impact.html`, built by `scripts/depgraph-build.sh` | Self-contained, offline, no CDN. Renders the graph against the actual geometry. |
| **Interchange** | `nodes.jsonl` + `edges.jsonl` | Backend-agnostic. The store stays a swappable decision rather than a bet. |

Nothing about this blocks adding Neo4j later. That is the point of §6.

---

## 2. The question that actually decides it

Not "which database is faster." The deciding question is:

> **Does the store return the path, or only the destination?**

Our product is the *why*. A work-order row reads "this M2.5 screw must change
because it fastens the arm body, which fastens the bottom plate" — that is a
path. CPM-style propagation risk is the product of edge weights **along a path**,
aggregated over all paths reaching a target. Reachability alone cannot produce it.

- **`$graphLookup` returns a set of reached documents, not paths.** It has
  `depthField`, so you learn *how far* a node was, but not *through what*. You
  cannot reconstruct the reason chain, and you cannot compute a path-product risk.
- That is a decisive argument against `$graphLookup` **as the reasoning engine**.
- **It is not an argument for Neo4j.** It is an argument for doing the traversal
  somewhere that hands you paths — and a 40-line BFS does that for free.

`$graphLookup` remains correct for what it is good at: walking the containment
tree, "give me everything under this subassembly." Use it there.

---

## 3. Measured: how big before in-process stops working

The whole debate assumed traversal is expensive. It is not. Benchmark of the
actual propagation (BFS over `FASTENS` + definition closure, `maxHops=3`), scaled
by replicating the real S500 graph N times:

| Copies | Nodes | Edges | Build | Query | Reached | Heap |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 126 | 197 | 0.1 ms | **0.012 ms** | 60 | 5 MB |
| 10 | 1,260 | 1,970 | 0.3 ms | 0.100 ms | 600 | 5 MB |
| 100 | 12,600 | 19,700 | 3.2 ms | 1.18 ms | 6,000 | 13 MB |
| 1,000 | 126,000 | 197,000 | 28 ms | 26.8 ms | 60,000 | 153 MB |
| 5,000 | 630,000 | 985,000 | 219 ms | 218 ms | 300,000 | 819 MB |

Read against the scale tiers in #23 and #29:

- **T0 fixture** (126 nodes) — 0.012 ms. A database here is pure overhead.
- **T1 product** (10³–10⁴) — ~1 ms. Still not a database problem.
- **T2 program** (10⁵–10⁶) — 27–218 ms, 153–819 MB. Comfortable on a 128 GB GB10.
- **T3 enterprise** (10⁷+) — **not measured. This is the revisit trigger.**

The binding constraint at T2 is **heap, not time**. 819 MB at 630k nodes is fine
on this hardware and would not be on a laptop.

### A real bug this benchmark caught

The first run showed query time going 0.018 → 1.56 → **273 ms** — superlinear.
Cause: the definition-closure step re-scanned the whole definition group for
*every* reached node, which is quadratic. Closing each definition at most once per
traversal fixed it and produced the linear table above.

Worth recording because it is the actual lesson: **at this scale the algorithm is
the performance story, not the store.** Picking a database would not have fixed a
quadratic loop; it would have hidden it behind a network hop.

The same fix has been applied to the shipped viewer (`s500-impact.html`).

---

## 4. Options considered

| Option | Verdict |
|---|---|
| **In-process (JS `Map` / Python `dict` / NetworkX)** | **Selected for traversal.** Returns paths and per-edge reasons natively. Zero install, zero ARM64 risk, zero network hop. Measured above. The CPM solver is ~40 lines. |
| **MongoDB as system of record** | **Selected for storage.** Already the #1 decision. Stores runs, lineage, evidence, review queue. `$graphLookup` is fine for containment-tree walks. |
| **MongoDB `$graphLookup` as the reasoning engine** | **Rejected.** Returns reachability, not paths — fatal for reason chains and path-product risk. Also single-collection, and capped at 100 MB per stage with no spill to disk. |
| **Neo4j Community 5.x** | **Dropped.** Cypher genuinely expresses typed variable-length traversal well and GDS supplies weighted pathfinding, but it is a JVM service to install offline on ARM64 to solve a 27 ms problem, and the custom viewer already beats Browser for this demo. Revisit only at T3 (§7). |
| **Kùzu** | **Rejected for now.** Best-in-class embedded Cypher engine and the strongest multi-hop numbers of the group. Upstream archived Oct 2025 after the Apple acquisition; community forks only. First choice if an embedded query engine is ever needed. |
| **Memgraph / ArangoDB / TigerGraph** | **Rejected.** No advantage at this scale, weaker offline ARM64 story than Neo4j. |

---

## 5. Why this is the right call *for a six-hour build*

- **One fewer thing that can fail on the GB10.** Every service installed offline
  on ARM64 is a risk with no upside here.
- **The demo already visualises the graph** against real geometry
  (`s500-impact.html`). Neo4j Browser would show *less*, not more — a node-link
  diagram with no drone attached to it.
- **It does not contradict the team.** MongoDB stays exactly where #1 put it.
- **Paths come free**, which is the thing the product is actually made of.

---

## 6. How to not paint into a corner

1. Derivation writes `nodes.jsonl` + `edges.jsonl`. Nothing downstream may depend
   on a specific backend.
2. Loaders are thin and separate: `load_mongo.py`, `load_neo4j.py`, `load_mem.py`.
3. The traversal API is one function — `propagate(anchor, maxHops) -> {hop, why, paths}`.
   Swapping the backend means reimplementing that one signature.
4. Keep the in-process implementation even after adding a server. It is the
   cross-check that catches a wrong traversal before a demo does, and it is what
   #27 means by "Cypher and NetworkX must return identical impacted sets."

---

## 7. What would change this decision

Any one of these flips it, and each is checkable rather than a matter of taste:

| Trigger | Move to |
|---|---|
| Corpus exceeds ~10⁶ nodes, or heap passes ~1 GB | Neo4j (or Kùzu) for traversal |
| Multiple processes need concurrent graph reads | Neo4j |
| Traversal needs to survive process restart without a rebuild | Neo4j |
| Queries become genuinely ad-hoc rather than three fixed modes | Cypher earns its keep |

None of these hold today. **Revisit at T2 with #29's measurements in hand.**

### Correction to #23

#23 originally recommended "Neo4j Community 5.x with NetworkX as in-process
co-primary." That was reasoned from install risk, Cypher expressiveness, and the
free visual — before anyone measured the traversal. The measurement inverts the
priority: in-process is primary, Neo4j is optional. The rejections of Kùzu and
Memgraph in #23 stand unchanged.

---

## 8. Sources

- `$graphLookup` semantics and limits — https://www.mongodb.com/docs/manual/reference/operator/aggregation/graphLookup/
- Cypher variable-length paths — https://neo4j.com/docs/cypher-manual/current/patterns/variable-length-paths/
- Neo4j GDS offline plugin install — https://neo4j.com/docs/graph-data-science/current/installation/installation-docker/
- Neo4j ARM64 images — https://hub.docker.com/r/arm64v8/neo4j/tags
- Kùzu status and embedded design — https://thedataquarry.com/blog/embedded-db-2/
- Clarkson et al., Change Prediction Method / DSM — https://strategic.mit.edu/docs/2_28_JMD_131_081010_ChangePropagation.pdf

## 9. References

- Parent attempt: #23 · Setup: #24 · Propagate: #27 · Scale: #29 · Viewer: #32
- Standing MongoDB decision: #1
- Working context: `docs/research/depgraph-context.md`
