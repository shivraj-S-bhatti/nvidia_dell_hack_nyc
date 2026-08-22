# Manufacturing side — build specification

Everything the manufacturing half of the two-agent system needs, and every point
where it must stay in sync with the design half already built in
`tools/depgraph/`.

Thesis and architecture: `docs/research/design-manufacturing-loop.md`.
Per `AGENTS.md` this is a specification, not a backlog — execution goes to issues.

**Current state: the design side is built; the manufacturing side does not exist.**
This file is the contract for building it without breaking the half that works.

---

## 1. What "in sync" means

Both agents read one graph and one revision. Sync is not a data feed — it is six
frozen contracts. Break any of these and the two sides silently disagree.

| # | Contract | Owner | Consumer |
|---|---|---|---|
| 1 | `corpusRevision` — sha256 prefix of the source STEP | design (`build_graph.py`) | every mfg record pins to it |
| 2 | Occurrence id — `PARENT/CHILD/LEAF` path string | design (`parse_step.py`) | mfg references parts by this, never by name |
| 3 | Definition name → **SKU** identity bridge | **manufacturing** (§4) | design reads lifecycle status back |
| 4 | Grip-stack schema — `gripMm`, `engagementMm`, `requiredLengthMm`, `members[]` | design (`derive_edges.py`) | mfg substitution solver |
| 5 | Units — **millimetres, always**; angles in degrees | both | both |
| 6 | Provenance `tier` on every node and edge | both | UI, work order, ECO draft |

**Rule:** manufacturing never mutates the geometric graph. It *annotates* it in
separate collections keyed by `corpusRevision` + occurrence id. If a substitution
is approved, the design side re-derives and issues a new `corpusRevision`. There
is exactly one writer of geometry.

### New provenance tiers

Existing: `authored` · `geometry` · `standard` · `catalog` · `assumption`.
Manufacturing adds two, ranked **below** `geometry` and **above** `assumption`:

- `inventory` — stock levels, lead times, cost, lifecycle. Volatile; always stamped
  with an observation timestamp.
- `tooling` — driver geometry, torque capability, fixture envelopes. Stable, but
  shop-specific and must never be presented as a property of the design.

---

## 2. What manufacturing contributes that design cannot derive

The STEP file cannot tell you any of this. That is the entire reason the second
agent exists.

| Knowledge | Example | Why geometry can't supply it |
|---|---|---|
| Stock on hand | 400× M3×8, 0× M3×21 | Not in the model |
| Lead time | M3×21 → 6 weeks | Not in the model |
| Lifecycle | This SKU is EOL / NRND | Not in the model |
| Tool inventory | 2.0 mm and 2.5 mm hex drivers, 90 mm shaft | Not in the model |
| Tool reach | Can a driver physically get on that head? | **Derivable — but only with the tool envelope, which is shop data** |
| Torque capability | Driver rated 0.2–2.0 N·m | Not in the model |
| Strip torque | Determined by drive-to-strip test on the real boss | Not in the model, and not in any table |
| Cost | Unit cost, setup cost | Not in the model |
| Process capability | Tolerances the shop can hold | Not in the model |

Note row 4: tool reach is a *geometric* question that cannot be asked until
manufacturing supplies the tool envelope. That is the cleanest illustration of why
one graph with two contributors beats two separate systems.

---

## 3. The constraint corpus

Small, hand-authorable, versioned in the repo. Not a research problem — a
sequence of small JSON files. Suggested location `data/mfg/`.

### 3.1 `stock.json` — `tier: inventory`

```json
{
  "observedAt": "2026-08-22T14:00:00Z",
  "site": "nyc-floor-1",
  "items": [
    {"sku":"SHCS-M2.5x6-A2","standard":"ISO 4762","thread":"M2.5","lengthMm":6,
     "drive":"hex","driveSizeMm":2.0,"material":"A2 stainless","pitchMm":0.45,
     "onHand":400,"leadTimeDays":3,"unitCost":0.04,"lifecycle":"active"},
    {"sku":"SHCS-M3x8-A2","standard":"ISO 4762","thread":"M3","lengthMm":8,
     "drive":"hex","driveSizeMm":2.5,"material":"A2 stainless","pitchMm":0.5,
     "onHand":600,"leadTimeDays":3,"unitCost":0.05,"lifecycle":"active"},
    {"sku":"SHCS-M3x21-A2","standard":"ISO 4762","thread":"M3","lengthMm":21,
     "drive":"hex","driveSizeMm":2.5,"material":"A2 stainless",
     "onHand":0,"leadTimeDays":42,"unitCost":0.09,"lifecycle":"NRND"}
  ]
}
```

Author the full ladder for both threads so the solver has somewhere to go.
Verified against ISO 4762:
**M2.5** → 4, 5, 6, 8, 10, 12, 16, 20, 25, 30 mm.
**M3** → 4, 5, 6, 8, 10, 12, 16, 20, 25, 30, 35 mm.
These already exist as `STOCK` in `tools/depgraph/derive_edges.py`; that constant
should be **deleted and replaced by this file** once it lands, so there is one
source of truth for what is buyable.

### 3.2 `tooling.json` — `tier: tooling`

```json
{
  "site":"nyc-floor-1",
  "tools":[
    {"toolId":"hex-2.0","drive":"hex","driveSizeMm":2.0,
     "shaftDiameterMm":4.0,"shaftLengthMm":90,"handleDiameterMm":22,
     "torqueRangeNm":[0.1,1.0]},
    {"toolId":"hex-2.5","drive":"hex","driveSizeMm":2.5,
     "shaftDiameterMm":5.0,"shaftLengthMm":100,"handleDiameterMm":22,
     "torqueRangeNm":[0.2,2.0]},
    {"toolId":"ph1","drive":"phillips","driveSizeMm":1,
     "shaftDiameterMm":5.0,"shaftLengthMm":80,"handleDiameterMm":24,
     "torqueRangeNm":[0.1,1.2]}
  ]
}
```

`shaftDiameterMm` and `shaftLengthMm` are what make the access check possible.
`handleDiameterMm` matters for the last few centimetres and is the usual reason a
"reachable" screw is not reachable.

### 3.3 `joint_torque.json` — **not a lookup table**

The research changed the shape of this file, not just its values.

There is no universal torque table for a screw into plastic. Bossard's own
polyamide guide states it "does not replace calculations as defined in VDI 2230",
and the published guidance is consistent: torque into thermoplastic depends on the
specific formulation, boss geometry, screw type, thread engagement, and
temperature. A table lookup here is not a conservative approximation — it is the
wrong data structure, and shipping one would invite someone to strip a nylon boss
on our authority.

The correct model is the **1:3 strip ratio**: tightening torque ≈ ⅓ of the torque
that strips the plastic, where **strip torque is determined by test**, per joint
family, on the actual material.

```json
{
  "joints": [
    {"jointFamily": "M2.5-into-S500-arm-boss",
     "thread": "M2.5", "intoMaterial": "polyamide-nylon (carbon-rod reinforced)",
     "stripTorqueNm": null,
     "testMethod": "drive-to-strip on 5 sample bosses, record mean and min",
     "recommendedTorqueNm": null,
     "ratio": 0.33,
     "verified": false,
     "note": "no value until a strip test exists; the agent must refuse to state one"}
  ]
}
```

**Rule: with `stripTorqueNm: null` the agent returns "not determined — requires a
drive-to-strip test", never an inferred number.** This is the one place where
producing a plausible figure is worse than producing none.

## 4. The identity bridge — definition ↔ SKU

The single highest-risk piece. `GB70-M2-5-6-DING` in the STEP is
`SHCS-M2.5x6-A2` in the stockroom and `91290A102` in the supplier catalogue.

`data/mfg/identity.json`:

```json
{"map":[
  {"defName":"GB70-M2-5-6-DING","sku":"SHCS-M2.5x6-A2",
   "confidence":1.0,"method":"manual",
   "evidence":"shank r=1.200 (M2.5), head r=2.150, GB/T 70 ~ ISO 4762"}
]}
```

Resolution order, matching #25:

1. Manual map entry — always wins.
2. Exact geometric fingerprint (shank radius, head radius, measured length).
3. Normalised-name match.
4. **Anything else → `identity_review` queue in MongoDB. Never guessed.**

The fingerprints are already measured and in `derive_edges.FASTENERS`, and they
**check out against the published ISO 4762 dimensions** — which is what makes the
identity bridge trustworthy rather than a naming convention:

| Thread | ISO 4762 head dk | → radius | Measured in file | Hex drive | Head height k |
|---|---|---|---|---|---|
| M2.5 | 4.32 – 4.50 mm | 2.16 – 2.25 | **2.150** | 2.0 mm | 2.50 mm |
| M3   | 5.32 – 5.50 mm | 2.66 – 2.75 | **2.700** | 2.5 mm | 3.00 mm |

The M3 measurement lands mid-tolerance and M2.5 within 0.01 mm of the minimum.
The head-height column independently explains the measured-vs-nominal length gap
already recorded in the pipeline: M2.5×6 measured 8.1 mm ≈ 6 mm shank + 2.5 mm head.

Also measured, without a standard to check against here: M2.5 countersunk
`1.150 / 2.100` (GB/T 819) · M3 nylon pan head `1.400 / 2.250` (GB/T 818).

**An unresolved identity blocks a substitution proposal.** It does not downgrade
to a guess.

---

## 5. Geometric primitives to add

Two checks, one shared primitive. Both belong in `tools/depgraph/derive_edges.py`
next to `_axial_span`, which already does most of the work.

### 5.1 Swept-volume intersection

Given an axis, a radius, and a `[t0, t1]` interval along that axis, return every
occurrence whose mesh vertices fall inside that cylinder. `_axial_span()` already
projects vertices onto an axis with a radial band — this is the same loop with the
test inverted.

### 5.2 Protrusion check — gates every substitution

A longer screw sticks out the back. Sweep shank radius from the last clamped face
to `newLength`, and report anything hit.

```
protrusion = newLengthMm - gripMm - engagementMm
sweep: radius = shankR, interval = [exit_of_last_member, +protrusion]
hit => substitution REJECTED with the occurrence it collides with
```

Without this the solver will cheerfully recommend a screw that punches into the
PDB. **No substitution ships without it.**

### 5.3 Tool access check — Loop 3, and shared with `BLOCKS_ACCESS` (#26)

Sweep the driver shaft from the fastener head outward along `−axis`:

```
sweep: radius = shaftDiameterMm/2, interval = [head_face, head_face - shaftLengthMm]
hit => not reachable with that tool; try another, else flag to design
```

Run the handle diameter over the last 30 mm as a second, coarser sweep. This is
the same withdrawal-cone machinery #26 specifies for teardown order, so build it
once and let both consume it.

---

## 6. The solvers — deterministic, no model

`tools/mfg/solvers.py`. Every function returns candidates **with the arithmetic
attached**; none of them return prose.

### 6.1 `substitute_fastener(occId, reason)`

```
1. resolve occId -> defName -> SKU            (§4; unresolved => block)
2. load grip stack                            (already computed)
3. required = gripMm + engagementMm
   engagement is material-dependent, NOT a constant:
     standard metric thread in thermoplastic   1.5x D floor, 2.0x D high stress
     thread-forming / self-tapping into plastic 2.0-2.5x D (3.0x D heavy load)
     steel                                      1.0x D
   The S500 arms are polyamide, so the code now defaults to 2.0x D and reports
   `engagementBasis` on every stack. 1.5x D is the optimistic floor, not a default.
4. candidates = stock where thread matches, lifecycle active, onHand > 0,
                lengthMm >= required
5. for each: protrusion check (§5.2)          reject on hit
6. for each: tool access check (§5.3)         reject if no tool fits
7. rank: shortest adequate length, then lead time, then unit cost
8. return candidates with full arithmetic + rejected ones WITH their reason
```

Returning the **rejected** candidates and why is not optional. It is what makes
the engineer trust the accepted one.

### 6.2 `impact_of_stockout(sku)`

SKU → definition → occurrence closure → blast radius. `work_order.propagate()`
already does the traversal; this only adds the SKU→definition hop.

### 6.3 `graph_diff(revA, revB)` — Loop 5

Set operations over two derived graphs:

```
nodes added / removed / moved   (world transform delta > tolerance)
edges added / removed
grip stacks whose gripMm changed  ->  fasteners now under-length
```

A PLM diff says the file changed. This says **what changed physically**. Cheap,
and the most novel thing in the system.

---

## 7. The manufacturing agent

OpenClaw persona B. Shares the one resident model with the design persona, per #1
and #3 — **two personas, one endpoint, never two model servers.**

### Tool allowlist — deliberately narrow

| Tool | Deterministic | Notes |
|---|---|---|
| `lookup_stock(sku)` | yes | read-only |
| `resolve_identity(defName)` | yes | may return `unresolved` |
| `substitute_fastener(occId, reason)` | yes | §6.1 |
| `impact_of_stockout(sku)` | yes | §6.2 |
| `check_tool_access(occId, toolId)` | yes | §5.3 |
| `graph_diff(revA, revB)` | yes | §6.3 |
| `draft_issue(...)` | **model** | writes the human memo only |

The agent may not write geometry, approve anything, or invent a part number.

### SOUL.md posture

Shop-floor voice: terse, unit-aware, refuses to guess. Every output ends with what
a human must verify. When identity is unresolved or a check cannot run, it says so
and stops — it does not produce a "probably fine".

---

## 8. Protocol schemas

Strict, validated, rejected on failure — **never re-prompted into compliance**.

```json
{
  "issueId": "...", "corpusRevision": "c8d3bc53168bbfe2",
  "kind": "stockout|no_tool_access|lead_time|eol|revision_skew",
  "occId": "ARM-S500_ASM/GB70-M2-5-6-DING007",
  "defName": "GB70-M2-5-6-DING", "sku": "SHCS-M2.5x6-A2",
  "constraint": {"onHand": 0, "leadTimeDays": 42},
  "observedAt": "...", "tier": "inventory"
}
```

```json
{
  "proposalId": "...", "issueId": "...", "corpusRevision": "...",
  "candidates": [
    {"sku":"SHCS-M3x25-A2","lengthMm":25,"requiredLengthMm":20.2,
     "marginMm":4.8,"protrusionMm":4.8,"protrusionClear":true,
     "toolId":"hex-2.5","toolClear":true,"leadTimeDays":3,"onHand":250,
     "arithmetic":"grip 14.2 + engagement 6.0 (2.0x D into polyamide) = 20.2 required; 25 >= 20.2, margin 4.8"}
  ],
  "rejected": [
    {"sku":"SHCS-M3x20-A2","reason":"20 mm < 20.2 mm required (grip 14.2 + engagement 6.0)"},
    {"sku":"SHCS-M3x30-A2","reason":"protrusion 9.8 mm collides with occurrence PCB-POWER"}
  ],
  "unknowns": ["torque into polyamide unverified"],
  "mustVerifyByHuman": ["confirm thread engagement into nylon boss"]
}
```

Approval records both gates, with who and when. An unapproved proposal never
reaches the floor.

---

## 9. MongoDB collections

Manufacturing writes only to its own collections. Design's `graph_nodes`,
`graph_edges`, `grip_stacks` stay read-only to this side.

| Collection | Contents |
|---|---|
| `mfg_stock` | stock snapshots, stamped `observedAt` |
| `mfg_tooling` | tool inventory |
| `mfg_identity` | definition ↔ SKU map, with confidence and method |
| `identity_review` | ambiguous matches awaiting a human |
| `mfg_issues` | raised constraints |
| `mfg_proposals` | candidates, accepted and rejected, with arithmetic |
| `approvals` | both gates, with actor and timestamp |

Index every one on `corpusRevision`.

---

## 10. Acceptance

- A stockout on `SHCS-M3x21-A2` produces a ranked proposal with arithmetic,
  and lists rejected candidates **with reasons**.
- Every proposal passes the protrusion check; a colliding candidate is rejected
  and names the occurrence it hits.
- Tool access is checked against real tool geometry; an unreachable fastener is
  reported, not silently passed.
- An unresolved identity **blocks** the proposal and lands in `identity_review`.
- `graph_diff` between two revisions of the S500 lists moved holes, changed
  thicknesses, and fasteners that became under-length.
- Both human gates are present and blocking.
- Every record carries `corpusRevision` and replays identically against it.
- The whole path runs with outbound networking disabled.
- Unverified torque values are never displayed as specifications.

## 11. Guardrails

- Manufacturing **never mutates the geometric graph**. One writer of geometry.
- Absolute fastener adequacy is still not claimed — the threaded member is not
  derivable. Substitutions are relative to today's build.
- Stock, cost and lead-time data are commercially sensitive and stay on the box.
- No claim of airworthiness, structural adequacy, fatigue life, or process
  qualification.
- A check that cannot run is an **explicit unknown**, never a silent pass.

## 12. Build order

1. `stock.json`, `tooling.json`, `identity.json` for the S500's nine fastener
   families. Hand-authored, one sitting.
2. Swept-volume primitive (§5.1) — unblocks everything geometric.
3. Protrusion check (§5.2) — gates every substitution.
4. `substitute_fastener` (§6.1) end to end, CLI first.
5. Tool access (§5.3).
6. `graph_diff` (§6.3).
7. OpenClaw persona B + tool allowlist.
8. Both human gates in the viewer.

Steps 1–4 are the demo. Everything after is depth.

## 13. References

- Thesis: `docs/research/design-manufacturing-loop.md`
- Design side: `tools/depgraph/README.md`
- Store decision: `docs/research/graph-store-decision.md`
- Facts and invariants: `docs/research/depgraph-context.md`
- Issues: #23 parent · #25 identity · #26 edges/access · #27 query modes · #32 viewer
- Runtime/model decisions: #1, #3
