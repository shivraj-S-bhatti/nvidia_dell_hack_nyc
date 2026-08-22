# Agent Orientation

This is a six-hour hackathon repository. GitHub issues are execution truth.
Read issue #1, then #7, then the active issue you own before changing code.

## Final Direction

Ship one private, local mechanical-design feedback loop on the Dell GB10:

**Object -> Lab -> Factory -> Track -> Lab revision -> human selection**

- **Object** supplies a recognizable multipart assembly, stable component
  identity, protected interfaces, and a dependency matrix.
- **Lab** proposes a small family of coherent design changes and preserves their
  ancestry.
- **Factory** compiles or loads each candidate and rejects invalid assemblies
  with concrete geometric or constraint evidence.
- **Track** applies one common measured task to Factory survivors and ranks them.
- **Feedback** from Factory or Track must visibly change one later Lab proposal.
- **Human selection** promotes the final revision. The system does not certify it.

The product claim is not prompt-to-pretty-CAD. It is generation corrected by
assembly truth and measured performance instead of another prompt.

`Lab`, `Factory`, and `Track` are functional stage names. The interface may show
concise, evidence-backed Claw handoffs between them. Do not add decorative
personas or roleplay until the complete loop works.

## The Six Active Issues

Only issues carrying the `active` label are on the execution path:

| Issue | Contract | Current owner |
|---|---|---|
| #10 `LOCAL` | Run the judged path on the GB10 without outbound networking | `Simardeep27` |
| #11 `OBJECT` | Prove the multipart object and dependency matrix | `justgoofingaround` |
| #12 `LAB` | Produce coherent candidate families and revise from feedback | `shivraj-S-bhatti` |
| #13 `FACTORY` | Compile candidates and reject invalid assemblies | unassigned |
| #14 `TRACK` | Measure and rank only Factory survivors | unassigned |
| #37 `FRONTEND` | Show Claw handoffs and join the stages into one demo | `justgoofingaround` |

Issue #1 is the epic, #7 is the product contract, and #35 is the provisional
story. They coordinate the work but are not extra implementation tracks.

Work only from an assigned or explicitly claimed active issue. Comment on the
issue when claiming unassigned work. Do not open another project attempt unless
the producer changes the active set.

## Stage Contracts

### Object

**Input:** a legally reusable local assembly.

**Output:** baseline artifact, component manifest, physical occurrences,
dependency evidence, protected interfaces, one bounded proposal, and known
good/bad fixtures for the next stages.

Repeated parts must remain distinct occurrences. Unknown relationships stay
unknown. The baseline must be restorable.

### Lab

**Input:** object contract, bounded goal, protected interfaces, candidate budget,
and optional Factory or Track feedback.

**Output:** candidate artifacts with parentage, changed components, state, and
the evidence that caused any revision.

Lab may be creative. It may not silently violate the request, erase failures, or
return one unexplained winner.

### Factory

**Input:** one Lab candidate plus the Object contract.

**Output:** reproducible `pass` or `fail`, implicated components, measured reason,
and replayable evidence.

Factory answers whether the candidate is a valid assembly under the displayed
checks. It does not rank performance. One candidate failing must not stop the
family.

### Track

**Input:** Factory survivors only.

**Output:** baseline-relative measurements, ranking, tolerance, elapsed time,
and actionable feedback for one poor candidate.

Every survivor faces the same fixture and score definition. Track may report
only what its selected test measures.

### Loop

**Input:** the four contracts above.

**Output:** one golden run containing a real Factory rejection, at least two
Track candidates, one feedback-driven Lab revision, a baseline comparison, and
a blocking human selection.

Precomputed artifacts and staged timing are encouraged for reliability. Fake
verdicts, invented metrics, and prerecorded outputs that do not correspond to a
real saved run are forbidden.

## Object Decision

Issue #11 owns the gate.

1. **NeoRacer** is the preferred race-object test. It publishes a complete
   FreeCAD vehicle and STEP under CERN-OHL-S-2.0:
   https://github.com/Neobotics-Foundation-Inc/neoracer-hardware-files
2. **S500** is the deadline-safe fallback. PR #36 already puts its verified
   assembly pipeline, stable occurrences, dependency graph, and reversible
   preview on `main`.
3. **CAD Power Animations F1** is visual inspiration only. Its repository has no
   declared license, so do not copy its code or assets without permission:
   https://github.com/GordenSun/cad-power-animations
4. **CADCLAW** is a permissively licensed reference for the Factory pattern, not
   a required dependency: https://github.com/sunnyday-technologies/CADCLAW

Adopt a new object only if it is offline, licensed, visually legible, preserves
component identity, and reproduces one useful good/bad check quickly. Otherwise
stop the asset search and use S500.

## Demo Story

The provisional wrapper is **The Night Shift: Lab -> Factory -> Track**.

> The Lab is allowed to be weird. The Factory is allowed to say no. The Track
> keeps score.

The three moments judges must remember are:

1. **Ripple:** one change propagates through dependent parts.
2. **Veto:** Factory rejects a plausible candidate and explains why.
3. **Revision:** evidence changes Lab's next proposal before Track ranks it.

The primary interface shows one object, one request, the three-stage rail,
concise clickable Claw handoffs, candidate states, a compact final comparison,
and one approval action. Hide setup logs, raw agent chat, architecture diagrams,
service names, and controls that do not affect the decision.

## Local And Model Boundary

- The demo-critical path runs locally on the GB10 with networking disabled.
- Use the single prepared local model endpoint and shared runtime. Do not start
  multiple heavyweight model servers for stage personas.
- Language-model output is always a proposal. Geometry, compilation,
  constraints, simulation, and scores produce the verdicts.
- MongoDB may retain candidate history and evidence, but the database is not the
  product story.
- A custom CUDA or Triton kernel enters only after issue #9's profiling gate and
  only if it improves the visible end-to-end path.

## Explicitly Discarded Paths

Do not resume these without a producer decision:

- Attempt 2 / ExitTwin / building evacuation.
- A separate task-specific robot product.
- A standalone GraphRAG, causal-DAG, or dependency-graph product.
- The design-to-manufacturing watcher, manufacturing constraint corpus,
  multi-day RFI thesis, or two-persona manufacturing simulation from commit
  `9f38b86`. That commit is intentionally absent from `main`.
- `durable_exec` from PR #33. Its Mongo claim semantics are unsafe under
  concurrent workers and it is unnecessary for the demo.
- Reskinning PartMode as the product.
- HydroGym, Isaac Sim, or another large simulation trajectory.
- Multiple resident heavyweight models.

Reuse a library, viewer, asset, or validation engine when it satisfies an active
contract. Do not rebuild mature infrastructure merely to make the stack look
more original.

## Truth Rules

- Keep failed candidates visible.
- Preserve source and license links for external assets.
- Retain baselines, fixtures, tolerances, elapsed time, and failure evidence.
- Label assumptions and unknowns explicitly.
- Do not claim safety, airworthiness, manufacturability, structural adequacy,
  aerodynamic range, or lap-time gains unless the displayed check measures it.
- Do not make agent count, architecture complexity, or tool count part of the pitch.

## Git And Handoff

- Keep code changes scoped to one active issue.
- Use a focused branch and pull request; include the owning issue in the PR.
- Review before merge. Do not merge failing or unreviewed work to `main`.
- Put measurements and screenshots in the owning issue or a gitignored
  `.artifacts/` directory, not in a parallel roadmap document.
- Never commit models, container archives, generated traces, secrets, or
  machine-specific venue state.
- Never place tokens or credentials in issues, screenshots, source files, or
  command arguments.
- Preserve unrelated worktree changes. Do not reset or rewrite another
  teammate's work.

## Definition Of Done

The project is done when one network-off run shows:

1. a recognizable baseline and bounded request;
2. a coherent Lab family;
3. a real Factory rejection;
4. at least two Track candidates under one test;
5. a feedback-driven Lab revision;
6. baseline-versus-finalist evidence; and
7. a human selecting the final revision.

Until that run exists, integration outranks new research.
