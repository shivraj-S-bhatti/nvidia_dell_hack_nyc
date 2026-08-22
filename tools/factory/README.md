# factory — deterministic assembly verdicts

Executes **FACTORY (#13)**. Gives every Lab candidate a reproducible `pass`/`fail`
before Track sees it, with a measured reason and the parts it implicates.

No language model touches the verdict path. Every reason code below is arithmetic on
geometry measured from `S500-C1_ASM.step` and its tessellated mesh.

## Run it

```bash
bash scripts/depgraph-build.sh          # once — Factory measures these artifacts
bash scripts/factory-run.sh             # verdicts + evidence + 56 assertions

python3 tools/factory/validate.py --verbose
python3 tools/factory/validate.py --candidate cand-d-standardize-m25 --verbose
python3 tools/factory/validate.py --repeat 3          # prove the verdicts repeat
```

## The result

```
candidate                      verdict  reason code      why
baseline                       PASS     FAC-000          3 checks passed, 2 not applicable
cand-a-scoped-1mm              PASS     FAC-000          5 checks passed, 0 not applicable
cand-b-scoped-2mm              PASS     FAC-000          5 checks passed, 0 not applicable
cand-c-plate-2mm-only          FAIL     FAC-LEN-001      20 of 20 affected fastener occurrences lose thread engagement
cand-d-standardize-m25         FAIL     FAC-CLR-001      4 of 28 lengthened fastener occurrences sweep into material
cand-e-thicker-tube            FAIL     FAC-CON-003      'CARBON-FIBER-TUBE' is a protected interface

SURVIVORS -- 3 eligible for Track, 3 rejected
```

3/3 repeated runs produce an identical verdict digest, in-process and across separate
processes. Family wall time ~12 s, peak RSS ~94 MB.

## The veto worth showing

`cand-d` standardises every M2.5 cap screw at 8 mm — one part number instead of
several, more engagement everywhere. It is a normal thing for an engineer to propose,
and it is applied at the *definition*, so it reaches all 28 occurrences.

**24 of those occurrences are fine. 4 are not.** On each of the four arms, the
lengthened shank sweeps 0.156 mm into `NILONGZHU-M3-6`, a nylon standoff it does not
touch today:

```
GB70-M2-5-6-DING at ARM-S500_ASM/GB70-M2-5-6-DING002
  current tip 5.800 mm   grows 2.0 mm   only 1.844 mm free
  penetration 0.156 mm into NILONGZHU-M3-6 (7 vertices inside the swept volume)
```

The four numbers are identical across the four arms, which is what four-fold symmetry
should produce. The feedback event carries the ceiling — *this definition may grow at
most 1.844 mm* — and names the binding occurrence, not a fix.

This veto was **found by scanning the assembly, not designed**: every fastener was
swept against every longer stock length in `derive_edges.STOCK`, and these are the
collisions that exist.

## The check set — `factory-checks/1.0.0`

Shown in demo order, which is also confidence order: the checks that measure geometry
come before the ones that verify bookkeeping.

| Check | Fails when | Codes |
|---|---|---|
| `CLEARANCE` | a lengthened shank sweeps into material it does not touch today | `FAC-CLR-001` |
| `FASTENER_LENGTH` | a joint loses thread engagement relative to the current build | `FAC-LEN-001/002` |
| `CONTRACT` | the candidate is malformed, targets nothing real, or touches a protected interface | `FAC-CON-001..004` |
| `ARTIFACT` | the baseline hash, corpus revision, or check-set version drifts from the contract | `FAC-ART-001..003` |
| `INVENTORY` | the component population is not the one the contract pins | `FAC-INV-001` |

Every result carries a status, a deterministic reason code, the measured value, the
tolerance it was compared against, the implicated occurrences, and an evidence path.

## What is deliberately not claimed

- **Absolute fastener adequacy.** A tapped hole and a clearance hole are both
  `CYLINDRICAL_SURFACE`, and some mates go into parts outside the assembly. The
  threaded member is not derivable, so `FASTENER_LENGTH` is **purely relative** — it
  asks only whether a candidate preserves the engagement the current build has. That
  is what makes it sound without knowing which member is threaded.
  - This matters concretely: the measured grip of an M2.5×6 through the bottom plate
    is **6.2 mm against a 6 mm nominal length**, because grip is clipped to the
    fastener's whole span including its head. An *absolute* reach check would fail the
    released baseline. The relative check does not.
- **Clearance as proof.** A `CLEARANCE` pass is *"no evidence of interference at this
  sampling density"*, never *"proven clear"*: a surface can cross the swept volume
  without placing a vertex inside it. The asymmetry runs the safe way — OCCT puts
  triangulation nodes **on** the exact surface, so a reported vertex is a real point
  of a real solid. A reported collision is sound, and the penetration is a **lower
  bound**.
- **Thickness interference.** A scalar thickness delta does not say which face the
  material grows from, and the direction is not derivable from the baseline. Every
  affected verdict prints `NOT CHECKED:` next to the clearance result rather than
  passing quietly. The engagement consequence *is* measured.
- The five checks from #47 this set does not implement — B-rep validity, CAD
  round-trip, keep-outs, minimum feature size, connectivity — are listed with reasons
  in `check-set.json` under `notChecked`, so a pass cannot be read as a broader claim
  than it makes. Connectivity is excluded on purpose: no operation in the vocabulary
  can add or remove a component, so the check could not fail, and a check that cannot
  fail is not evidence.

## A rejected candidate cannot reach Track

`survivors.json` is the only file Track is meant to read, and it is built from the
verdicts rather than from a promise. Rejected ids appear in a separate `rejected[]`
array so failures stay visible without being eligible. `check_factory.py` asserts the
two sets never intersect.

## Feedback, not redesign

Each rejection emits one `FeedbackEvent` carrying the measured constraint, the
tolerance, the implicated occurrences and definitions, and the evidence path — for
example `max-fastener-growth: GB70-M2-5-6-DING may grow at most 1.844 mm`. Choosing
what to do about it is Lab's decision (#12). Factory does not revise designs.

## Inputs, and who owns them

| Input | Owner | Until then |
|---|---|---|
| `.artifacts/object/object-contract.json` | #11 OBJECT | `fixtures/object-contract.json`, labelled `PROVISIONAL` |
| `.artifacts/lab/candidates.json` | #12 LAB | `fixtures/candidates.json`, labelled `PROVISIONAL` |

`validate.py` prefers the real artifact the moment it exists and records which source
it used in `contractSource` on every verdict, so a replay cannot silently swap the
baseline. **The fixtures declare the input contract Lab writes to; the verdicts in
them are not authored — they are computed.**

## Files

| File | Role |
|---|---|
| `geometry.py` | Baseline measurements: fastener axes, tip ends, axial spans, existing mates. |
| `candidate.py` | The candidate/contract schema and the operation vocabulary. |
| `checks.py` | The five checks. Tolerances are named constants at the top. |
| `verdict.py` | Runner, `FactoryVerdict`, survivor manifest, `FeedbackEvent`, digest. |
| `validate.py` | CLI. |
| `check_factory.py` | 56 assertions gating all of the above. |

## Why a candidate is a declared delta, not a new STEP file

Factory can measure a declared delta exactly — a shank grows *n* mm along its own
axis; a clamped member grows *n* mm through every stack containing it. Re-authoring
B-rep without a CAD kernel would force Factory to infer what changed and then measure
its own inference. The operation vocabulary is deliberately small, and an op outside
it is a contract failure (`FAC-CON-004`), never a silent pass: an operation Factory
cannot measure is one it cannot clear.
