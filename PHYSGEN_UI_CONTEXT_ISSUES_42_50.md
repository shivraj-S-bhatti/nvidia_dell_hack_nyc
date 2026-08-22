# PhysGen UI context: Issues 42–50

Snapshot date: 2026-08-22 UTC

This document is a UI handoff for the current Night Shift / PhysGen execution path. It describes what is implemented in the local worktrees, what evidence already exists, and what the downstream stages are expected to expose.

> **Status boundary:** Issues 42–45 form the locally implemented foundation. Issue 46 is the overlap point between the completed foundation and the current downstream work. **Issues 46–50 are work in progress and are currently being worked through.** Only Issue 46 has active local implementation edits today; Issues 47–50 are defined and queued, so their UI states must be shown as pending/WIP rather than as completed results.

## Product story

The Night Shift is an offline mechanical-design workbench running on one Dell GB10. A user gives it an existing assembly and a bounded objective. The system selects a replaceable component, creates a constrained design domain, generates a family of alternatives, converts those alternatives back into real CAD, rejects invalid designs with deterministic checks, compares the survivors under one common physics test, revises one candidate from measured feedback, and waits for a human to choose the final design.

The end-to-end path is:

`Object intake → frozen contracts → Lab generation → CAD domain → CAD compilation → Factory veto → Track ranking → measured revision → product run + human selection`

The UI should make five facts obvious:

1. The selected part belongs to a larger assembly, so changing it can affect interfaces and neighboring components.
2. Lab creates a family of candidates, not one unexplained answer.
3. Factory can visibly reject an attractive-looking candidate for a measured reason.
4. Track compares only Factory survivors under identical conditions.
5. The machine proposes and validates; a human makes the final decision.

## Current repository and worktree reality

| Issue | Pipeline step | GitHub state | Local worktree state | UI interpretation |
|---|---|---:|---|---|
| [#42](https://github.com/shivraj-S-bhatti/nvidia_dell_hack_nyc/issues/42) | 01 — Object | Closed | Committed, clean worktree | Implemented; runtime evidence exists |
| [#43](https://github.com/shivraj-S-bhatti/nvidia_dell_hack_nyc/issues/43) | 02 — Contract | Closed | Committed, clean worktree | Implemented; schema/test evidence exists |
| [#44](https://github.com/shivraj-S-bhatti/nvidia_dell_hack_nyc/issues/44) | 03 — Lab runtime | Closed | Committed, clean worktree | Implemented; offline OAT run evidence exists |
| [#45](https://github.com/shivraj-S-bhatti/nvidia_dell_hack_nyc/issues/45) | 04 — Bridge in | Open/queued | Committed, clean worktree | Locally implemented and evidenced, but not closed/integrated |
| [#46](https://github.com/shivraj-S-bhatti/nvidia_dell_hack_nyc/issues/46) | 05 — Bridge out | Open/queued | **Active WIP with uncommitted edits** | Show as running/in progress, not complete |
| [#47](https://github.com/shivraj-S-bhatti/nvidia_dell_hack_nyc/issues/47) | 06 — Factory | Open/queued | No dedicated local worktree/output | Pending WIP stage |
| [#48](https://github.com/shivraj-S-bhatti/nvidia_dell_hack_nyc/issues/48) | 07 — Track | Open/queued | No dedicated local worktree/output | Pending WIP stage |
| [#49](https://github.com/shivraj-S-bhatti/nvidia_dell_hack_nyc/issues/49) | 08 — Feedback | Open/queued | No dedicated local worktree/output | Pending WIP stage |
| [#50](https://github.com/shivraj-S-bhatti/nvidia_dell_hack_nyc/issues/50) | 09 — Product | Open/queued | No dedicated local worktree/output | Pending WIP integration stage |

The combined committed foundation is easiest to inspect in `.artifacts/worktrees/issue45/attempt1/physgen/`. The newest code, including Issue 46 WIP, is in `.artifacts/worktrees/issue46/attempt1/physgen/`. Runtime evidence is shared under `.artifacts/attempt1-physgen/`. These changes are not all present on `origin/main`, so the UI developer should not use the main branch alone as the source of truth for this handoff.

## Issues 42–46: implemented foundation and current boundary

### Issue 42 / Step 01 — Object intake and target selection

Purpose: turn a large upstream race-car assembly into one stable, offline, hash-addressed target-component handoff.

What it currently does:

- Caches the NeoRacer STEP assembly locally and pins its upstream commit, license, size, and SHA-256.
- Loads the assembly three times without repair and verifies stable component/occurrence identity.
- Enumerates 379 component definitions and 647 occurrences.
- Selects exactly one target: `WING-MOUNT-L`, occurrence `WING-MOUNT-L:1`.
- Confirms that the target is one valid, mostly planar thin-wall solid with a nominal 5 mm extrusion thickness.
- Records four protected mounting interfaces, neighboring keep-out envelopes, a component-local frame, and the original assembly transform.
- Keeps the verified S500 bottom plate as a fallback, but the fallback is not selected.

Stable UI identifiers:

- Component ID: `component-651d2501fdff2aa4f1cd`
- Occurrence ID: `occurrence-356ea2a4ca15007f265a`
- Occurrence path: `SST000_ASM (1):1/WING-MOUNT-L:1`
- Baseline component SHA-256: `0b7a0a9785a8723db1167466cd617f7e93cb4b66be0501fb9ff337e511ad7cd9`
- Source assembly SHA-256: `73d18cf9104c93177495f09f1aa4569c887c089ce0c9d0ddf4a97d1f26fc7c73`

Current evidence:

- Status: pass, offline, no network access.
- Three successful loads with stable identity and geometry.
- Total replay time: about 65.95 seconds.
- Peak process RSS: 1,470,344 KiB.
- Assembly-context screenshot exists and should be the opening visual for the UI.

Useful UI treatment:

- Show the whole NeoRacer assembly first, then isolate/highlight the left wing mount.
- Display the component name, stable ID, source hash, units, and “offline verified” badge.
- Mark all loads and supports as **demo test-fixture assumptions**, not recovered vehicle specifications.

Primary artifacts:

- `.artifacts/attempt1-physgen/object/target-component.json`
- `.artifacts/attempt1-physgen/object/evidence/replay.json`
- `.artifacts/attempt1-physgen/object/artifacts/sha256/425cc02758671dbb20391dbd14337bc43a31940c2ab0a20cfb2f073249eb97ba.png`

### Issue 43 / Step 02 — Frozen data contracts

Purpose: give every stage a strict, versioned handoff so the UI and pipeline do not need to infer state from filenames or prose.

The seven frozen entities are:

- `DesignProblem`
- `Candidate`
- `FactoryVerdict`
- `TrackResult`
- `FeedbackEvent`
- `DesignRun`
- `HumanSelection`

Every entity includes a schema version, stable ID, run/parent references, source hashes, declared units, creation method, and evidence sources. Unknown fields, duplicate JSON keys, non-finite numbers, unsupported schema versions, and machine-specific artifact paths are rejected. Large CAD, density arrays, images, and solver traces are referenced by SHA-256 instead of embedded in records.

Important UI state values:

- Candidate role: `baseline`, `proposal`, or `revision`.
- Candidate state: `proposed`, `factory_rejected`, `factory_passed`, `track_evaluated`, `finalist`, or `selected`.
- Factory verdict: `pass` or `fail`.
- Track status: `measured` or `solver_failed`.
- Design-run state: `awaiting_human_selection`, `completed`, or `failed`.
- Human decision: `selected`, `rejected`, or `deferred`; actor type must be `human`.

Hard transition rule: a candidate with a failed Factory verdict cannot have a Track result. The UI should keep rejected candidates visible, but visually block them from advancing to Track.

Current evidence: 17 contract/lineage/normalization tests pass. Normalized JSON and hashes are byte-stable across repeated runs.

Primary source:

- `.artifacts/worktrees/issue43/attempt1/physgen/contracts/`

### Issue 44 / Step 03 — Offline Lab generation and deterministic baseline

Purpose: prove that the GB10 can generate a seeded topology family locally and evaluate it against a deterministic counterfactual.

What it currently does:

- Runs cached `OpenTO/NFAE_L` and `OpenTO/LDM_L` through OptimizeAnyTopology's native conditioning path.
- Forces offline model loading and records exact model revisions and weight hashes.
- Generates three seeded `float32` density fields with values in `[0, 1]`.
- Evaluates every field with OAT's deterministic pyEDGE evaluator.
- Produces a 50-step deterministic SIMP/OC baseline under the same domain, supports, loads, material, and material-fraction target.
- Emits contract-valid Candidate records, PNG density previews, arrays, evaluations, inventory, replay evidence, and a complete hash manifest.

Current real-target run:

- Run ID: `run.neoracer-wing-mount-l-seed-7`
- Design problem: `design-problem.neoracer-wing-mount-l`
- Candidate IDs:
  - `candidate.neoracer-wing-mount-l-s7-00`
  - `candidate.neoracer-wing-mount-l-s7-01`
  - `candidate.neoracer-wing-mount-l-s7-02`
- Baseline ID: `candidate.neoracer-wing-mount-l-simp-baseline`
- Grid: 124 rows × 109 columns, converted correctly between the bridge's row/column layout and pyEDGE's x/y layout.
- Run status: passed; all five runtime success criteria are true.
- Total wall time: about 56.91 seconds.
- Model load: about 0.64 seconds; cold generation: about 3.30 seconds; warm replay: about 2.15 seconds.
- Peak OAT-process GPU allocation: about 2.86 GB; peak CPU RSS: about 3.74 GB.

The current numerical results are Lab runtime evidence, not the final Track ranking:

| Design | Compliance (N·mm) | Material fraction | UI label |
|---|---:|---:|---|
| SIMP baseline | 0.6214 | 0.3499 | Deterministic counterfactual |
| OAT candidate 00 | 7,283.8905 | 0.3516 | Proposal; not Factory-checked |
| OAT candidate 01 | 1.1792 | 0.3504 | Proposal; not Factory-checked |
| OAT candidate 02 | 9,863.5941 | 0.3527 | Proposal; not Factory-checked |

Do not crown a winner from this table. The SIMP baseline was finite and deterministically replayable but had not converged at the fixed 50-step demo cutoff. Factory and Track still own acceptance and ranking.

Useful UI treatment:

- Show a four-card family: one baseline plus three generated proposals.
- Give each proposal its seed, density preview, material fraction, generation method, and evidence status.
- Use “generated” or “evaluated in Lab,” never “approved,” “safe,” or “winner.”
- Keep the deterministic baseline visually distinct from the learned proposals.

Primary artifacts:

- `.artifacts/attempt1-physgen/lab-runtime/run.json`
- `.artifacts/attempt1-physgen/lab-runtime/candidates.json`
- `.artifacts/attempt1-physgen/lab-runtime/evaluations.json`
- `.artifacts/attempt1-physgen/lab-runtime/candidates/*.png`
- `.artifacts/attempt1-physgen/lab-runtime/baseline/simp-baseline.png`

### Issue 45 / Step 04 — CAD-to-PhysGen bridge (“bridge in”)

Purpose: convert the actual selected CAD part into the exact bounded grid consumed by Lab and the common structural evaluator.

What it currently does:

- Projects the component-local XY design plane with +Z as the extrusion direction.
- Uses a 0.5 mm cell size over a 124 × 109 grid.
- Rasterizes the allowed-material region, source projection, protected solid, required void, support, load, and keep-out masks.
- Keeps the canted upper interfaces as protected source-CAD interfaces instead of flattening or silently remodeling them.
- Emits the frozen `nightshift.design-problem/v1` contract and hash-addressed Boolean NumPy masks.
- Creates an overlay showing mounts, supports, loads, protected regions, and keep-outs.
- Validates grid-to-CAD round trips, interface alignment, mask overlap, units, orientation, and three-build determinism.

Current evidence:

- Status: passed, offline, no network access.
- Four protected interfaces align within one grid cell.
- Maximum coordinate round-trip error: 0 cells.
- All core artifact hashes are identical across three builds.
- Total replay time: about 13.45 seconds; peak RSS: about 579 MB.
- The keep-out mask is intentionally empty because the recorded neighboring envelopes do not intersect this part's local design slab; the non-intersection evidence is retained.

Useful UI treatment:

- Use the overlay as the transition from “physical part” to “design problem.”
- Suggested legend: source/allowed material, protected interfaces, required voids, blue support rings, red load rings, and keep-outs.
- Show the exact 100 N total demo comparison load as two −Y 50 N loads on the upper mounts.
- State that the load, material, solver, and search budget are explicit comparison fixtures rather than recovered NeoRacer specifications.

Primary artifacts:

- `.artifacts/attempt1-physgen/design-problem/design-problem.json`
- `.artifacts/attempt1-physgen/design-problem/evidence/replay.json`
- `.artifacts/attempt1-physgen/design-problem/artifacts/sha256/5eedf8cf438cf2541422c844e7a18baaa81e8f7a1ca0d7946106ef943b08d608.png`

### Issue 46 / Step 05 — Density-to-CAD compiler (“bridge out”) — WIP

Purpose: turn the baseline and three Lab density fields into reproducible, loadable CAD candidates placed back in the source assembly.

Current local WIP includes:

- A new `problem_to_cad.py` compiler.
- A strict `nightshift.cad-compile-policy/v1` policy.
- A strict `nightshift.compiled-candidate/v1` metadata schema.
- Updates to the Lab adapter so the real Step 04 domain can feed Step 03 and emit a domain-bound `candidates.json` handoff.
- A passing adapter unit test for row/column ↔ pyEDGE x/y mapping.

The frozen compiler behavior is:

- Threshold density at `>= 0.5`.
- Clip to allowed material.
- Force protected-solid cells to material and required-void/keep-out cells to void.
- Use no smoothing, filtering, or invented load-bearing cleanup.
- Convert occupied cells through deterministic maximal-row rectangle decomposition.
- Extrude to the Step 04 thickness.
- Rebuild the four protected mounting rings and source-sized holes analytically.
- Export both component-local STEP and assembly-placed STEP files.
- Re-import exported STEP files and verify valid geometry, volume round trip, protected holes, and assembly placement.
- Generate a fixed-camera PNG viewer artifact and hash every output.
- Rebuild the baseline and all three candidates three times and require identical core hashes.

The planned four compiled records are:

- One source baseline.
- Candidate 00, intended to exercise common downstream checks.
- Candidate 01, intentionally tagged as the planned Factory-failure exercise.
- Candidate 02, intended to exercise common downstream checks.

The “planned Factory-failure exercise” tag is not a verdict. The compiler only records geometry/connectivity/feature observations. Factory must independently run its checks and may pass or reject any candidate based on the measured result.

Current completion caveat:

- The Issue 46 worktree contains five modified tracked files and three new untracked files.
- The updated Lab adapter tests pass 8/8.
- There is not yet an accepted `.artifacts/attempt1-physgen/cad-candidates/compile-run.json` handoff in the shared artifact tree.
- The compiler has no retained completion/test evidence yet, so the UI must show this stage as **in progress**.

Expected outputs when this WIP stage completes:

- `compile-run.json`
- One compiled-candidate JSON record per baseline/proposal
- Component-local STEP
- Assembly-placed STEP
- Final occupancy mask
- Fixed-camera PNG render
- Compile time, peak RSS, warnings, hashes, and three-run determinism evidence

## Issues 46–50: current downstream WIP

This section describes the UI contract for the active downstream band. Issue 46 is under implementation; Issues 47–50 are queued and do not yet have real local stage outputs.

### Issue 47 / Step 06 — Factory deterministic veto — pending WIP

Purpose: give every compiled candidate a deterministic pass/fail verdict before physics ranking.

Factory will apply the same versioned checks to the baseline and every candidate:

- Contract and artifact-hash integrity.
- CAD load/export round trip.
- Valid closed solid/B-rep.
- Allowed body/component count.
- Protected-interface coverage and placement tolerance.
- Connectivity between load regions and supports/mounts.
- Required-void and keep-out compliance.
- Minimum-thickness/feature rule.
- Original assembly transform and selected neighbor interference/clearance checks.

Every check must expose a check ID, outcome, measured value, operator, threshold, implicated components, and evidence links. The baseline must pass. At least one real, reproducible veto should remain visible, and rejected candidates must not enter Track.

Useful UI treatment:

- Show a compact check matrix per candidate.
- Use a clear `pass`/`fail` badge and deterministic reason code.
- On failure, show “measured vs tolerance,” the affected interface/component, and a link to evidence.
- Keep the failed card in the family with a stopped rail between Factory and Track.

No real Factory verdict currently exists; use a pending state, not a fabricated failure.

### Issue 48 / Step 07 — Track common FEA and ranking — pending WIP

Purpose: apply one common structural test to the baseline and every Factory survivor, then rank the results deterministically.

Track will:

- Read candidates only from Factory's survivor manifest.
- Use the compiled occupancy mask, never a raw generator preview.
- Freeze the mesh/grid, supports, loads, material, solver settings, convergence criteria, and units.
- Record compliance, baseline-normalized compliance, maximum displacement/location when supported, material fraction, convergence/failure state, elapsed time, and memory.
- Rank by a documented objective and tie-breaker.
- Keep a known-poor survivor visible and produce a measured feedback event.

Useful UI treatment:

- Show a baseline-relative comparison table or bars.
- Make solver failure different from Factory rejection.
- Keep the exact fixture and units visible near the comparison.
- Show rank only after Track has emitted a real `TrackResult`.

The UI must not turn these component-level comparison results into claims about lap time, downforce, crash performance, fatigue life, safety, or manufacturing readiness.

### Issue 49 / Step 08 — Measured feedback revision — pending WIP

Purpose: turn one real Factory or Track result into a supported problem change, generate child candidates, and prove lineage.

Feedback will:

- Accept only a schema-valid `FeedbackEvent` linked to retained evidence.
- Map a deterministic reason code into supported changes such as interface correction, local density/member width, clearance, material fraction, or load-path correction.
- Reject unsupported prose-only feedback.
- Persist the revised problem, policy version, parent candidate, child candidates, seeds, hashes, Factory verdicts, and Track results.
- Retain losing children and failures.
- Promote a child only when it resolves the triggering Factory reason or improves the exact triggering Track metric.

Useful UI treatment:

- Show a parent → child lineage connection.
- Present the triggering measurement, the bounded requested change, and the before/after result.
- Label deterministic fallback honestly if OAT cannot consume the revision; do not call fallback output diffusion-generated.

### Issue 50 / Step 09 — Product run and human gate — pending WIP

Purpose: integrate Object, Lab, Factory, Track, feedback, and selection into one resumable `DesignRun`.

The integrated product will provide:

- One explicit stage runner/state machine with resumable transitions.
- Stable run, candidate, verdict, result, feedback, and selection records persisted in MongoDB with artifact hashes.
- Typed reads for the current stage, family/lineage, Factory verdicts, Track comparison, revision, and pending/final selection.
- Failed candidates that remain queryable.
- One offline command that creates or resumes a frozen run without recomputing completed immutable stages.
- A final blocking human decision before a revision can become the selected design.

NemoClaw, OpenClaw, and OpenShell are shared orchestration infrastructure. The single local language-model endpoint is limited to bounded request normalization and evidence explanation. Numerical values, physics results, verdicts, and rankings must come from deterministic artifacts.

## Recommended primary UI surface

Issue 50 deliberately asks for a compact product surface rather than a service-architecture or agent-transcript dashboard.

### 1. Header / run summary

Show:

- Run ID and offline/local badge.
- User request/objective in one sentence.
- Selected object and component.
- Current stage and run state.
- Resume/replay status.

### 2. Main object viewport

Support three useful modes:

- Whole assembly with the target highlighted.
- Isolated component.
- Constraint/domain overlay or compiled candidate.

### 3. Stage rail

Use these user-facing labels:

`Object → Lab → CAD Compile → Factory → Track → Revision → Human Review`

Contracts are infrastructure and can appear as an evidence/health indicator rather than a full visual stage. Bridge-in can be represented as the transition from Object to Lab.

Each stage needs a state such as `pending`, `running`, `passed`, `failed`, or `blocked`. Preserve the actual stage boundary: Lab proposes, CAD Compile builds geometry, Factory accepts/rejects, Track measures/ranks, Revision creates children, and Human Review selects.

### 4. Candidate family

Each card should be keyed by stable candidate ID and include:

- Baseline/proposal/revision role.
- Parent/family/generation information.
- Generation method and seed.
- Density preview and, once available, compiled 3D render.
- Material fraction.
- Factory state/reason.
- Track metrics/rank only when eligible.
- Evidence status and artifact links.

Rejected and losing candidates stay visible. Never delete them from the family to create a cleaner story.

### 5. Evidence drawer

The evidence drawer should expose:

- Source and artifact hashes.
- Schema version and validation status.
- Measured value, tolerance/operator, and implicated region for a Factory failure.
- Solver state, exact fixture, units, and baseline delta for Track.
- Latency/memory and offline/network-use proof.
- Replay command or saved replay record.

### 6. Comparison and approval

The comparison should be compact and baseline-relative. The primary action appears only in `awaiting_human_selection` and creates an explicit `HumanSelection` of `selected`, `rejected`, or `deferred`. Do not auto-promote the top-ranked candidate.

## Contract-to-UI mapping

| UI concern | Contract/source fields |
|---|---|
| Run header | `DesignRun.id`, `run_id`, `state`, `timing`, `peak_memory`, `replay` |
| Object identity | `DesignProblem.assembly`, `target_component`, `source_hashes`, `units` |
| Constraint overlay | `design_domain`, `coordinate_transform`, `protected_interfaces`, `keep_outs`, `supports`, `loads` |
| Candidate card | `Candidate.id`, `family_id`, `generation`, `role`, `state`, `seed`, `geometry` |
| Lineage | `Candidate.parent_ids`, `feedback_event_ids`, `DesignRun.lineage_edges` |
| Factory badge/details | `FactoryVerdict.verdict`, `checks`, `failure_codes`, `elapsed_ms` |
| Track comparison | `TrackResult.status`, `metrics`, `score`, `rank`, `feedback_recommended` |
| Revision explanation | `FeedbackEvent.reason_code`, `measured`, `threshold`, `implicated_component_ids`, `requested_changes` |
| Finalists | `DesignRun.rankings`, `finalist_candidate_ids` |
| Human gate | `HumanSelection.candidate_id`, `decision`, `actor_type`, `rationale_codes`, `comment`, `selected_at` |

## Five-minute demo sequence

1. Open the full NeoRacer assembly and isolate `WING-MOUNT-L`.
2. Transition to the grid overlay and point out protected holes, supports, loads, and the bounded design region.
3. Show the baseline plus three seeded Lab proposals and their evidence-backed identities.
4. Show each proposal compiling into a real component and assembly-placed CAD artifact once Issue 46 completes.
5. Keep one plausible candidate visible as Factory rejects it for a measured reason.
6. Compare only the survivors against the baseline in Track.
7. Follow one poor result through a parent-to-child revision.
8. End at the human-review gate with up to three finalists and an explicit selection action.

Until Issues 46–50 have real outputs, steps 4–8 must be visibly marked WIP/pending in any live or recorded UI.

## Current validation snapshot

Fast tests run against the local worktrees at this snapshot:

- Issue 42 Object: 7/7 passing.
- Issue 43 Contracts: 17/17 passing.
- Issue 44 Lab: 7/7 passing.
- Issue 45 Bridge-in: 6/6 passing.
- Issue 46 updated Lab/domain adapter: 8/8 passing.

These test counts verify the focused code paths only. They do not imply that Issues 46–50 have completed end-to-end acceptance evidence.

## Claims and visual-language guardrails

- Say “offline/local run,” because the recorded paths force local models and record no network use.
- Say “component-level comparison fixture,” not recovered vehicle behavior.
- Say “proposal” before Factory, “Factory survivor” after a pass, “ranked” only after Track, and “selected” only after the human gate.
- Do not imply safety, certification, manufacturing readiness, aero performance, fatigue life, crash performance, or lap-time improvement.
- Do not let an LLM-authored explanation replace the measured artifact, threshold, verdict, or score.
- Keep failures and counterfactuals visible; they are part of the proof, not error states to hide.
