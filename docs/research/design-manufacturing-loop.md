# Closing the design ↔ manufacturing loop with two local agents

Product thesis and architecture for the next stage of `ATTEMPT#DEP_GRAPH` (#23).

Per `AGENTS.md` this is not a backlog. It records the problem, the evidence, the
architecture, and the design rationale. Executable work belongs in GitHub issues.

---

## 1. The problem

A design change and a manufacturing constraint are separated by email.

| Evidence | Figure |
|---|---|
| Average RFI turnaround | **8–10 days** |
| Schedule delay added per RFI | **10–14 days** |
| Cost per RFI (review + response) | **~$1,080**, ~8 hours |
| RFI density | ~9.9 per $1M, ~800 per average project |
| RFIs that never receive an official answer | **>20%** |
| Cost multiplier per phase a defect survives | **10×** (1-10-100 rule) |
| Product cost locked in during design | **70–80%** |

Sources in §10. Construction RFI data is the best-instrumented proxy; discrete
manufacturing ECO cycles behave the same way and are less publicly benchmarked.

Read those two rows together and the thesis falls out: a defect costs 10× more per
phase it survives, and the mechanism that lets it survive is **a 10-day email round
trip**. The industry's answer has been to review harder up front. The other answer
is to make the round trip take seconds.

## 2. The thesis

> **This is a latency problem, not an information problem.**

Nobody is missing knowledge. The engineer knows the design intent. The machinist
knows the stock, the tooling, and what a driver can reach. Each answer already
exists on someone's side of the wall. It just travels at 8–10 days per hop, and
one hop in five never arrives at all.

So do not build a smarter reviewer. **Put both sides' constraints into one graph
on one machine, and give each side an agent that can query the other's constraints
without asking a human to relay them.**

> **Two agents. One graph. One box. Two human gates.**

## 3. Why this has to be local — both halves

Unusually, both ends of this loop independently require on-device execution:

- **Design side.** The STEP file *is* the intellectual property. Aerospace,
  defence and automotive suppliers are contractually forbidden from uploading
  assemblies to third-party endpoints.
- **Manufacturing side.** Stock levels, tooling inventory, supplier lead times and
  unit costs are commercially sensitive — often more jealously guarded than the
  geometry. And the shop floor frequently has no usable connectivity.

A cloud service would have to be trusted by two parties who do not fully trust
each other. One box in one facility does not.

## 4. Architecture

```text
      DESIGN SIDE                                    MANUFACTURING SIDE
   ┌────────────────┐                             ┌────────────────────┐
   │  design-agent  │                             │     mfg-agent      │
   │  OpenClaw      │                             │     OpenClaw       │
   │  persona A     │                             │     persona B      │
   └───────┬────────┘                             └─────────┬──────────┘
           │        one shared local model endpoint         │
           │        (Qwen3.6-35B-A3B-NVFP4, GB10)           │
           └───────────────────┬───────────────────────────-┘
                               │
                 ┌─────────────▼──────────────┐
                 │   DERIVED DEPENDENCY GRAPH │
                 │   occurrences · FASTENS    │
                 │   grip stacks · access     │
                 │   revisions · provenance   │
                 └─────────────┬──────────────┘
                               │
                 ┌─────────────▼──────────────┐
                 │  MongoDB — system of record │
                 │  runs · lineage · evidence  │
                 │  proposals · approvals      │
                 └────────────────────────────┘
```

Both personas share **one resident model**, per the standing decision in #1 and #3.
Two agents here means two `SOUL.md` / `SKILL.md` personas and two tool allowlists,
not two model servers.

### The rule that keeps this from becoming a toy

> **The agents never negotiate in natural language with each other.**

Two language models talking to each other compounds error at every exchange, and
the failure is invisible because both sides sound confident. So:

- Agents exchange **strict typed messages** validated against a schema.
- Candidate resolutions are produced by a **deterministic solver** reading the graph.
- Each candidate is **checked against geometry**, not argued about.
- The model's only job is writing the **human-facing memo** at each gate.

The model writes the memo. The graph decides the facts. If a message fails schema
validation it is rejected, not re-prompted into compliance.

### Protocol

```text
mfg-agent observes a constraint violation
      │
      ▼  strict Issue{kind, partRef, constraint, evidence}
deterministic solver enumerates candidate resolutions from the graph
      │
      ▼  each candidate checked: grip, clearance, access, keep-out
design-agent validates survivors against design intent + tolerances
      │
      ▼  ECO draft with geometric proof and explicit unknowns
   ══ HUMAN GATE 1 — engineer approves ══
      │
      ▼  committed at a new corpusRevision
   ══ HUMAN GATE 2 — shop floor acknowledges ══
```

Two gates, one per team. Neither side can silently change the other's world. That
is what makes it deployable rather than a demo.

## 5. The loops this closes

Mapped honestly against what exists today.

### Loop 1 — Fastener substitution · **substrate built**

> *"M3×21 is out of stock, six week lead time."*

Today: RFI, 8–10 days, possibly a line stoppage.

With the graph: the fastener's grip stack is already measured. Required length =
grip + engagement. Check stock for the shortest length that satisfies it, verify
the extra protrusion clears the keep-out, propose with the arithmetic attached.

`derive_edges.py` already computes grip, engagement and required length, and
`work_order.py --thicker` already emits exactly this class of recommendation.
What is missing is a stock table and the protrusion check.

**8–10 days → target under 2 minutes.**

### Loop 2 — Silent break detection · **substrate built**

> *An engineer thickens a plate 1 mm and saves. Twenty fasteners are now too short.*

Today: discovered at assembly, at 100× the design-phase cost.

With the graph: the watcher re-derives the dirty subgraph on save and drafts the
ECO before the revision reaches the floor. Already demonstrable —
`work_order.py BOTTOM-PLATE-S500 --thicker 1.0` returns the 20 affected fasteners
with new lengths.

**Catches the defect at 1×, not 100×.**

### Loop 3 — Assembly access · **needs `BLOCKS_ACCESS` (#26)**

> *"I can't get a torque driver on that screw."*

The withdrawal-cone edge already specified in #26, extended with a tool envelope
(driver diameter and length) rather than just the fastener's own swept volume.
Answers it geometrically instead of by argument, and proposes a sequence change.

### Loop 4 — Supply blast radius · **built**

> *"Your supplier is discontinuing this fastener."*

Definition closure already answers this: one definition, 28 occurrences, four arms
and four hangers. Extends across a corpus to "which products ship this part" once
canonical identity lands (#25).

### Loop 5 — Revision skew · **partially built, highest novelty**

> *The floor is building rev B. Engineering is on rev D. What actually changed?*

A PLM diff says "the file changed." **A graph diff says what changed physically:**
three hole positions moved, one plate thickened, twenty fasteners now under-length.

Every record already carries `corpusRevision`. Diffing two derived graphs — nodes,
edges, grip stacks — is a set operation over data we already produce. This is the
capability with no obvious commercial equivalent and it is nearly free.

### Loop 6 — First-article verification · **future**

Measured CMM data against the model. Needs metrology input; named here so it is
not mistaken for something we claim.

## 6. What exists versus what is needed

| Capability | State |
|---|---|
| Occurrence graph, world transforms | **built** — 125 occurrences, verified |
| `FASTENS` from geometry | **built** — 72 edges, 52/52 fasteners, 0.000 mm axis offset |
| Grip stacks, required length | **built** — 52 stacks measured |
| Blast radius + length actions | **built** — `work_order.py` |
| Offline viewer | **built** — `s500-impact.html` |
| MongoDB system of record | **built** — `load_mongo.py` |
| `CLAMPS` / `CONTACTS` edges | **missing** — carbon tube is a dead end (#26) |
| `BLOCKS_ACCESS` + tool envelope | **missing** (#26) |
| Stock / tooling / lead-time table | **missing** — the manufacturing side's constraints |
| Graph diff between revisions | **missing** — cheap, high value |
| Watcher (always-on) | **missing** — the "always-on" requirement |
| OpenClaw personas + local model | **missing** — the hard rule |
| Two human gates | **missing** |

The honest read: the **design side is largely built; the manufacturing side does
not exist yet.** The manufacturing agent needs its own constraint corpus — stock,
tooling, access envelopes — and that is a small, authorable dataset, not a
research problem.

## 7. Sequencing rationale

Ordered by what a judge can see and what the rules demand, not by what is
interesting to build.

1. **Watcher + OpenClaw personas + local model.** Without these the project fails
   the one hard rule — an always-on local agent — regardless of graph quality.
2. **Stock table + Loop 1 end to end.** The substitution loop is the most legible
   business story and the substrate already exists.
3. **`CLAMPS` (#26).** Closes the one visible hole: the carbon tube currently
   returns only itself.
4. **Graph diff (Loop 5).** Cheapest genuinely novel capability we have.
5. **`BLOCKS_ACCESS` + tool envelope.** Unlocks Loop 3 and teardown order.
6. **Warp GPU broad-phase.** Earns the NVIDIA claim and the scale story.

## 8. Metric

> **Round-trip latency for one manufacturing constraint, measured end to end on
> the GB10, with networking disabled.**

Baseline: **8–10 days** (published RFI turnaround). Target: **under 2 minutes**,
excluding human approval time, which is reported separately and never hidden
inside the number.

Secondary: proportion of manufacturing issues resolved without a human relaying
information between teams. Humans still approve; they stop being the transport.

## 9. Guardrails

- This is a **triage and drafting aid**, not an approval authority. Both gates are
  human and both are blocking.
- No claim of airworthiness, structural adequacy, fatigue life, manufacturability
  certification, or fitness for flight.
- Derived edges are geometric inferences with stated tolerances, **not the original
  designer's intent**.
- Absolute fastener adequacy is not claimed — the threaded member is not derivable
  from the file. Relative deltas are sound. See `tools/depgraph/README.md`.
- A substitution the solver cannot verify is surfaced as an **explicit unknown**,
  never as a silent pass.
- Cost, lead-time and stock data are commercially sensitive and stay on the box.

## 10. Sources

- ECO cycle-time benchmarks — https://www.apqc.org/resources/benchmarking/open-standards-benchmarking/measures/engineering-change-order-eco-cycle-time
- RFI response-time benchmarks — https://helonic.com/blog/construction-rfi-response-time-benchmarks
- Navigant RFI study (1,362 projects, >1M RFIs) — https://track3d.ai/blog/rfi-in-construction-guide/
- RFI management and closure data — https://projul.com/blog/construction-rfi-management/
- 1-10-100 rule / cost of late change — https://en.wikipedia.org/wiki/Design_for_manufacturability
- DFM review timing and locked-in cost — https://www.bravoteam.tech/blog-design-for-manufacturability-decisions/

## 11. References

- Parent attempt: #23 · Ingest: #25 · Edges: #26 · Query modes: #27 · Viewer: #32
- Graph store decision: `docs/research/graph-store-decision.md`
- Verified facts and invariants: `docs/research/depgraph-context.md`
- Pipeline: `tools/depgraph/README.md`
- Runtime and model decisions: #1, #3
