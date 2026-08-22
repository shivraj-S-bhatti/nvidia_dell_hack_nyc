# Issue #44 — local OAT runtime proof

This slice uses the cached `OpenTO/NFAE_L` and `OpenTO/LDM_L` checkpoints
through [OptimizeAnyTopology](https://github.com/ahnobari/OptimizeAnyTopology)'s
native structural-conditioning API. The standard
checkpoint pair is attempted only if the large-latent pair fails. OAT's pyEDGE
CPU solver evaluates every generated density, and pyEDGE's deterministic
SIMP/OC optimizer produces the baseline under the same domain, supports,
loads, material, filter, and target material fraction.

The model sources are [OpenTO/NFAE_L](https://huggingface.co/OpenTO/NFAE_L)
and [OpenTO/LDM_L](https://huggingface.co/OpenTO/LDM_L). Exact cached revisions
and weight hashes are recorded in every run.

The canonical fixture is copied exactly from cached OpenTO test row 0. Its
small numerical units make it a runtime fixture, not a real component or a
vehicle-performance claim.

Run the issue's offline replay command from the repository root:

```bash
python -m attempt1.physgen.lab.generate \
  --problem attempt1/physgen/fixtures/canonical-problem.json \
  --output-root .artifacts/attempt1-physgen/lab-runtime \
  --offline --seed 7
```

The output contains density arrays/previews, Candidate records, independent
evaluations, a deterministic baseline, exact source/model hashes, package and
hardware inventory, cold/warm latency, CPU RSS, OAT-process GPU allocation,
fallback evidence, and a top-level `run.json` verdict.

The baseline is intentionally a fixed 50-step deterministic run for demo
latency. Its actual OAT convergence flag is retained in `evaluations.json`; a
finite result is not relabeled as converged.

Run the fast contract and artifact tests with:

```bash
.artifacts/attempt1-physgen/venv/bin/python -m unittest discover \
  -s attempt1/physgen/lab/tests -v
```

STEP 02 owns the shared schemas. When its DesignProblem schema is present at
the contracts path, the replay command validates this fixture against it before
loading either checkpoint.
