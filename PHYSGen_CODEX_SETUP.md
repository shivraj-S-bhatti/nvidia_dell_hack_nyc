# PhysGen  -  Codex Setup & Installation Runbook

> **Current transport media:** The team has a USB-A external HDD, not an SSD.
> Use it for transport and recovery. Copy the selected checkpoint and
> latency-sensitive runtime files to the GB10 internal NVMe before serving when
> capacity permits, and measure that copy time during rehearsal.

> **Purpose:** Give this single file to Codex (or another local coding agent) on the Dell Pro Max / GB10 machine.
> Codex should use it to install, download, verify, and prepare the complete local PhysGen hackathon environment.
>
> **Project:** PhysGen  -  generative topology design with independent physics verification
> **Target machine:** Dell Pro Max with NVIDIA GB10 / Grace Blackwell, Linux ARM64
> **Primary path:** OpenTO OAT (`LDM_L + NFAE_L`) → FEA verification → rank candidates → local OpenClaw/NemoClaw agent
> **Core principle:** **Generate with AI. Verify with physics.**

---

# 0. INSTRUCTIONS TO CODEX

You are setting up the local development machine for a hackathon. Execute this runbook **in order**.

## Operating rules

1. **Do not assume x86_64.** This machine should be `aarch64`.
2. **Do not reinstall NVIDIA drivers, CUDA, Docker, or PyTorch blindly.** First detect what is already installed.
3. **Do not replace system CUDA** unless the user explicitly approves it.
4. **Do not delete existing environments, models, containers, or repositories.**
5. Create everything for this project under:

```bash
~/physgen
```

6. Prefer a Python virtual environment under:

```bash
~/physgen/.venv
```

7. Before a command that requires interactive `sudo`, authentication, accepting third-party terms, or a user credential, tell the user exactly what command is about to run and let them perform/approve the interactive portion.
8. If a step fails, diagnose it before changing unrelated packages.
9. Do not spend more than a few debugging attempts on optional performance libraries. The priority is a working demo.
10. **Never make OAT's Intel/MKL/CHOLMOD optimization path a blocker on GB10/ARM64.**
11. Save useful command output to:

```bash
~/physgen/setup-logs/
```

12. At the end, produce a compact summary:
   - what installed successfully;
   - model locations/cache status;
   - GPU/CUDA/PyTorch status;
   - OAT import/inference status;
   - FEA baseline status;
   - NemoClaw/OpenShell status;
   - unresolved warnings.

## Success criteria

Setup is considered ready when all **MUST PASS** items below work:

- [ ] Linux architecture identified.
- [ ] CUDA GPU visible to PyTorch.
- [ ] Python environment created.
- [ ] `OpenTO/NFAE_L` downloaded.
- [ ] `OpenTO/LDM_L` downloaded.
- [ ] `OptimizeAnyTopology` cloned and imports successfully.
- [ ] A traditional topology/FEA path works (`scikit-topt`, OAT FEA, or DTU fallback).
- [ ] NemoClaw/OpenShell environment launches.
- [ ] Local agent inference is available.
- [ ] At least one known topology can be generated or baseline-optimized and visualized.

Diffusion inference is high priority, but if OAT's large checkpoint path fails, use the standard OAT pair immediately.

---

# 1. TARGET ARCHITECTURE

PhysGen should eventually run:

```text
Natural-language engineering requirement
                |
                v
        OpenClaw / NemoClaw
                |
                v
       Local agent model
                |
                v
           DesignProblem
   (supports, loads, volume fraction)
                |
       +--------+---------+
       |                  |
       v                  v
 OpenTO LDM_L       SIMP baseline
       |
       v
 OpenTO NFAE_L
       |
       v
8–16 candidate density fields
       |
       v
 INDEPENDENT FEA VALIDATION
       |
 +-----+-----------+---------+
 |                 |         |
 v                 v         v
compliance      volume   displacement
 |                 |         |
 +-----------------+---------+
                   |
                   v
             filter + rank
                   |
                   v
          best physics-valid design
```

The LLM **must not invent physics outputs**. It orchestrates and explains. Numerical structural results come from the solver.

---

# 2. MODELS TO DOWNLOAD

## P0  -  PhysGen topology generator

These two checkpoints are the primary learned topology-generation system.

### 2.1 OpenTO/NFAE_L

Role: neural-field autoencoder/decoder for the large-latent OAT model.

- Model page: https://huggingface.co/OpenTO/NFAE_L
- Files: https://huggingface.co/OpenTO/NFAE_L/tree/main

Preferred cache command:

```bash
hf download OpenTO/NFAE_L
```

Optional explicit local copy:

```bash
hf download OpenTO/NFAE_L \
  --local-dir ~/physgen/models/OpenTO-NFAE_L
```

---

### 2.2 OpenTO/LDM_L

Role: conditional latent diffusion model for topology generation.

- Model page: https://huggingface.co/OpenTO/LDM_L
- Files: https://huggingface.co/OpenTO/LDM_L/tree/main
- Main safetensor page:
  https://huggingface.co/OpenTO/LDM_L/blob/main/diffusion_pytorch_model.safetensors

Preferred cache command:

```bash
hf download OpenTO/LDM_L
```

Optional explicit local copy:

```bash
hf download OpenTO/LDM_L \
  --local-dir ~/physgen/models/OpenTO-LDM_L
```

**Important:** Do not use the generic text-to-image `DiffusionPipeline` example shown by the automatically generated Hugging Face card. OAT uses custom structural conditioning and its own model classes/scripts from `OptimizeAnyTopology`.

---

# 3. OAT FALLBACK MODEL PAIR

If `_L` causes any compatibility or inference issue, switch quickly to:

### OpenTO/NFAE

- https://huggingface.co/OpenTO/NFAE

```bash
hf download OpenTO/NFAE
```

### OpenTO/LDM

- https://huggingface.co/OpenTO/LDM

```bash
hf download OpenTO/LDM
```

Do not burn hackathon time trying to force the `_L` pair if the standard pair works.

---

# 4. LOCAL AGENT MODEL

## Default: NVIDIA Qwen3.6-35B-A3B-NVFP4

Current NVIDIA NemoClaw Express Install on DGX Spark-class systems selects this model by default.

- Model: `nvidia/Qwen3.6-35B-A3B-NVFP4`
- Hugging Face:
  https://huggingface.co/nvidia/Qwen3.6-35B-A3B-NVFP4
- Files:
  https://huggingface.co/nvidia/Qwen3.6-35B-A3B-NVFP4/tree/main
- License: Apache 2.0
- Approximate repository size: 23.5 GB

For offline cache:

```bash
hf download nvidia/Qwen3.6-35B-A3B-NVFP4
```

Do **not** manually duplicate this checkpoint into several folders unless needed. Keep the Hugging Face cache so vLLM/NemoClaw can reuse it.

### Official DGX-Spark-oriented vLLM serving shape

If direct vLLM serving is required outside NemoClaw, start from the model-card recommendation rather than inventing settings:

```bash
vllm serve nvidia/Qwen3.6-35B-A3B-NVFP4 \
  --host 0.0.0.0 \
  --port 8000 \
  --tensor-parallel-size 1 \
  --trust-remote-code \
  --kv-cache-dtype fp8 \
  --attention-backend flashinfer \
  --moe-backend marlin \
  --gpu-memory-utilization 0.4 \
  --max-model-len 262144 \
  --max-num-seqs 4 \
  --max-num-batched-tokens 8192 \
  --enable-chunked-prefill \
  --async-scheduling \
  --enable-prefix-caching \
  --speculative-config '{"method":"mtp","num_speculative_tokens":3,"moe_backend":"triton"}' \
  --load-format fastsafetensors \
  --reasoning-parser qwen3 \
  --tool-call-parser qwen3_xml \
  --enable-auto-tool-choice
```

**Do not install a random vLLM release just to make this command run.** NemoClaw's managed local inference path is preferred.

---

# 5. OPTIONAL AGENT MODEL

## NVIDIA Nemotron 3 Nano 30B-A3B NVFP4

Only download this if the team explicitly wants to test it or the Qwen/NemoClaw path is unsuitable.

- Model:
  `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4`
- Hugging Face:
  https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4
- Files:
  https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4/tree/main
- Approximate size: 19.4 GB
- License: NVIDIA Nemotron Open Model License

```bash
hf download nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4
```

This is **optional**, not part of the minimum setup.

---

# 6. OPTIONAL GENERATIVE FALLBACK

## NITO  -  Neural Implicit Topology Optimization

Use only if OAT becomes unusable or the team wants a comparison model.

- GitHub:
  https://github.com/ahnobari/NITO_Public

```bash
cd ~/physgen/repos
git clone https://github.com/ahnobari/NITO_Public.git
cd NITO_Public
python download.py --checkpoints
```

For checkpoints plus data:

```bash
python download.py --all
```

Do not integrate NITO before the OAT + FEA MVP works.

---

# 7. OPEN SOURCE REPOSITORIES

## Required

### Optimize Any Topology / OAT

https://github.com/ahnobari/OptimizeAnyTopology

```bash
mkdir -p ~/physgen/repos
cd ~/physgen/repos

if [ ! -d OptimizeAnyTopology/.git ]; then
  git clone https://github.com/ahnobari/OptimizeAnyTopology.git
else
  echo "OptimizeAnyTopology already exists; not overwriting."
fi
```

Repository includes:

- OAT model code
- NFAE
- conditional LDM / CTOPUNET
- generation scripts
- topology optimizer
- FEA/evaluation code
- OpenTO integration

Requirements file:

https://github.com/ahnobari/OptimizeAnyTopology/blob/master/requirements.txt

---

## Required fallback

### scikit-topt

- GitHub:
  https://github.com/kevin-tofu/scikit-topt
- Docs:
  https://scikit-topt.readthedocs.io/en/latest/
- License: Apache 2.0

Install in the PhysGen venv:

```bash
pip install scikit-topt
```

Optional source clone:

```bash
cd ~/physgen/repos
if [ ! -d scikit-topt/.git ]; then
  git clone https://github.com/kevin-tofu/scikit-topt.git
fi
```

---

## Emergency fallback

### DTU 2D Python topology optimization code

Official page:

https://www.topopt.mek.dtu.dk/apps-and-software/topology-optimization-codes-written-in-python1

This is intentionally tiny and should remain the emergency baseline if larger packages fail.

Dependencies:

```bash
pip install numpy scipy matplotlib
```

Example usage shown by DTU:

```bash
python topopt.py 180 60 0.4 5.4 3.0 1
```

If direct automated retrieval from the DTU page is inconvenient, tell the user to manually download `topopt.py` from the official page. Do not substitute an unverified fork.

---

# 8. OpenTO DATA

Dataset:

https://huggingface.co/datasets/OpenTO/OpenTO

Cache the dataset if bandwidth/storage allow:

```bash
hf download OpenTO/OpenTO --repo-type dataset
```

If time/bandwidth is tight, cache only the test parquet:

```bash
hf download OpenTO/OpenTO \
  --repo-type dataset \
  --include "data/test-00000-of-00001.parquet"
```

We are **not training OAT** during the hackathon. Data is for known test cases, validation, comparisons, and troubleshooting.

---

# 9. HOST PRE-FLIGHT  -  MUST RUN BEFORE INSTALLING

Create logs:

```bash
mkdir -p ~/physgen/setup-logs
```

Record system state:

```bash
{
  echo "=== DATE ==="
  date
  echo
  echo "=== ARCH ==="
  uname -a
  uname -m
  echo
  echo "=== OS ==="
  cat /etc/os-release 2>/dev/null || true
  echo
  echo "=== NVIDIA ==="
  nvidia-smi 2>/dev/null || true
  echo
  echo "=== CUDA ==="
  nvcc --version 2>/dev/null || true
  echo
  echo "=== PYTHON ==="
  python3 --version 2>/dev/null || true
  echo
  echo "=== DOCKER ==="
  docker --version 2>/dev/null || true
  echo
  echo "=== DISK ==="
  df -h ~
  echo
  echo "=== MEMORY ==="
  free -h
} | tee ~/physgen/setup-logs/preflight.txt
```

Expected architecture:

```text
aarch64
```

If architecture is not `aarch64`, do not blindly apply GB10-specific package substitutions. Report what machine is actually being used.

---

# 10. VERIFY EXISTING GPU/PYTORCH STACK

Try existing Python before changing it:

```bash
python3 - <<'PY'
try:
    import torch
    print("torch:", torch.__version__)
    print("torch CUDA:", torch.version.cuda)
    print("cuda available:", torch.cuda.is_available())
    if torch.cuda.is_available():
        print("device:", torch.cuda.get_device_name(0))
        print("device count:", torch.cuda.device_count())
except Exception as e:
    print("PYTORCH_CHECK_FAILED:", repr(e))
PY
```

If PyTorch with CUDA already works, do **not** replace it at the system level.

The PhysGen virtual environment may use system packages or install a compatible wheel/container path as needed.

---

# 11. CREATE PHYSGen WORKSPACE

```bash
mkdir -p \
  ~/physgen/models \
  ~/physgen/data \
  ~/physgen/repos \
  ~/physgen/app \
  ~/physgen/setup-logs \
  ~/physgen/outputs
```

---

# 12. CREATE PYTHON ENVIRONMENT

Prefer Python 3.11 or 3.12.

Inspect:

```bash
command -v python3.12 || true
command -v python3.11 || true
python3 --version
```

Create:

```bash
cd ~/physgen

if command -v python3.12 >/dev/null 2>&1; then
  python3.12 -m venv .venv
elif command -v python3.11 >/dev/null 2>&1; then
  python3.11 -m venv .venv
else
  python3 -m venv .venv
fi

source ~/physgen/.venv/bin/activate
python -m pip install -U pip setuptools wheel
```

Install basic tooling:

```bash
python -m pip install -U \
  "huggingface_hub[hf_xet]" \
  numpy \
  scipy \
  matplotlib \
  pandas \
  plotly \
  streamlit
```

Do not place secrets/tokens directly into this markdown file.

If Hugging Face auth is needed:

```bash
hf auth login
```

This should be an interactive user-controlled step.

---

# 13. DOWNLOAD THE REQUIRED MODELS

Run inside the activated environment.

## Primary topology models

```bash
hf download OpenTO/NFAE_L
hf download OpenTO/LDM_L
```

## Agent model for offline reliability

```bash
hf download nvidia/Qwen3.6-35B-A3B-NVFP4
```

## Cache test data

```bash
hf download OpenTO/OpenTO \
  --repo-type dataset \
  --include "data/test-00000-of-00001.parquet"
```

### Verify cache

```bash
du -sh ~/.cache/huggingface/hub 2>/dev/null || true
hf cache ls 2>/dev/null | grep -E 'OpenTO|Qwen3.6' || true
```

If `hf cache ls` syntax differs in the installed CLI, inspect `hf cache --help`.

---

# 14. OPTIONAL OFFLINE FALLBACK DOWNLOADS

Only after all P0 downloads complete:

```bash
hf download OpenTO/NFAE
hf download OpenTO/LDM
```

Optional Nemotron:

```bash
hf download nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4
```

Do not download multiple giant agent models if disk/bandwidth is constrained.

---

# 15. CLONE OAT

```bash
cd ~/physgen/repos

if [ ! -d OptimizeAnyTopology/.git ]; then
  git clone https://github.com/ahnobari/OptimizeAnyTopology.git
fi

cd OptimizeAnyTopology
git status
git log -1 --oneline
```

Save the revision:

```bash
git rev-parse HEAD | tee ~/physgen/setup-logs/oat-commit.txt
```

---

# 16. OAT + GB10 / CUDA COMPATIBILITY

The current OAT requirements may pin a CUDA-12 CuPy package such as:

```text
cupy_cuda12x
```

Current CuPy supports CUDA 13.x on Linux `aarch64` through:

```text
cupy-cuda13x
```

CuPy docs:

https://docs.cupy.dev/en/stable/install.html

First inspect the actual machine:

```bash
nvcc --version || true
nvidia-smi || true
```

Inspect OAT requirements:

```bash
cd ~/physgen/repos/OptimizeAnyTopology
grep -in "cupy" requirements.txt || true
```

## If machine CUDA is 13.x and OAT pins CUDA 12 CuPy

Do not edit the upstream file directly. Generate a local requirements file:

```bash
sed \
  -e 's/cupy_cuda12x/cupy-cuda13x/g' \
  -e 's/cupy-cuda12x/cupy-cuda13x/g' \
  requirements.txt \
  > requirements-gb10.txt
```

Then install:

```bash
source ~/physgen/.venv/bin/activate
pip install -r requirements-gb10.txt
```

## If dependency resolution fails on `scikit-sparse`, CHOLMOD, Intel MKL, or CPU-specific optimization

Do not turn these optional performance paths into blockers.

Actions:

1. Capture the exact error.
2. Determine whether the package is needed for **model inference** or only optimized FEA.
3. If only optimized FEA is blocked:
   - preserve OAT model dependencies;
   - install/use `scikit-topt` or the DTU fallback for physics;
   - continue.
4. Do not replace the host CUDA stack to satisfy an optional library.

Install fallback now:

```bash
pip install scikit-topt
```

---

# 17. VERIFY CuPy

If CuPy was installed:

```bash
python - <<'PY'
try:
    import cupy as cp
    print("cupy:", cp.__version__)
    x = cp.arange(8)
    print("cupy GPU result:", x)
    print("device:", cp.cuda.runtime.getDeviceProperties(0)["name"])
except Exception as e:
    print("CUPY_CHECK_FAILED:", repr(e))
PY
```

Failure here is not necessarily fatal if OAT generation can run via PyTorch and FEA is delegated to the fallback path.

---

# 18. VERIFY OAT IMPORTS

From the repository:

```bash
cd ~/physgen/repos/OptimizeAnyTopology
source ~/physgen/.venv/bin/activate

python - <<'PY'
import sys
from pathlib import Path
print("python:", sys.version)
print("cwd:", Path.cwd())

try:
    import torch
    print("torch:", torch.__version__)
    print("cuda:", torch.version.cuda)
    print("cuda available:", torch.cuda.is_available())
except Exception as e:
    print("TORCH:", repr(e))

try:
    from OAT.Models import NFAE, CTOPUNET
    print("OAT model imports: OK")
except Exception as e:
    print("OAT_IMPORT_FAILED:", repr(e))
    raise
PY
```

If import paths have changed upstream, inspect the repository rather than guessing:

```bash
find OAT -maxdepth 3 -type f | sort | head -200
grep -R "class NFAE" -n OAT .
grep -R "class CTOPUNET" -n OAT .
```

Update the import test to match the current source.

---

# 19. FIND THE OFFICIAL OAT INFERENCE PATH

Do not invent an inference API.

Inspect:

```bash
cd ~/physgen/repos/OptimizeAnyTopology

find scripts -maxdepth 2 -type f -print | sort
grep -R "GenerateSolutions" -n .
grep -R "from_pretrained" -n OAT scripts | head -100
grep -R "LDM_L" -n README.md scripts OAT
grep -R "NFAE_L" -n README.md scripts OAT
```

Read the repository README's inference/generation section.

Goal:

1. run a known OpenTO sample;
2. load `OpenTO/LDM_L`;
3. load `OpenTO/NFAE_L`;
4. generate one topology;
5. save it to `~/physgen/outputs/`.

Do not write application integration until this works.

If `_L` fails after reasonable diagnosis, retry with:

```text
OpenTO/LDM
OpenTO/NFAE
```

---

# 20. PHYSICS BASELINE  -  MUST WORK

Regardless of diffusion status, establish an independent topology/FEA baseline.

Install:

```bash
source ~/physgen/.venv/bin/activate
pip install scikit-topt
```

Inspect current docs/examples:

- https://scikit-topt.readthedocs.io/en/latest/
- https://github.com/kevin-tofu/scikit-topt

Goal problem:

```text
2D rectangular design domain
left edge fixed
downward load near far-right edge
volume fraction = 0.40
objective = minimize compliance
```

Produce:

```text
~/physgen/outputs/baseline-initial.png
~/physgen/outputs/baseline-final.png
~/physgen/outputs/baseline-metrics.json
```

Metrics should at least include:

```json
{
  "compliance": null,
  "volume_fraction": 0.40,
  "iterations": null,
  "runtime_seconds": null
}
```

Fill numerical values from the actual solver.

If `scikit-topt` blocks on dependencies, use DTU's official `topopt.py`.

---

# 21. NEMOCLAW / OPENCLAW / OPENSHELL

## Preferred path: official NemoClaw installer

Official repository:

https://github.com/NVIDIA/NemoClaw

Official docs:

https://docs.nvidia.com/nemoclaw/latest/

NemoClaw's maintained installer provisions OpenShell/OpenClaw components and on supported DGX Spark-class systems can offer Express Install with managed local vLLM.

Before running the interactive installer, tell the user that it will present a third-party software notice and may request privileged changes.

Set project sandbox name:

```bash
export NEMOCLAW_SANDBOX_NAME=physgen
```

Install:

```bash
curl -fsSL https://www.nvidia.com/nemoclaw.sh | bash
```

Prefer Express Install if the machine is recognized and the hackathon does not require custom inference configuration.

Current Express path uses:

```text
nvidia/Qwen3.6-35B-A3B-NVFP4
```

for DGX Spark-class local inference.

## Verify

If shell PATH does not immediately see the command:

```bash
source ~/.bashrc 2>/dev/null || true
source ~/.zshrc 2>/dev/null || true
export PATH="$HOME/.local/bin:$PATH"
```

Then:

```bash
nemoclaw --help
nemoclaw physgen status
```

Get dashboard URL:

```bash
nemoclaw physgen dashboard-url --quiet
```

Connect if appropriate:

```bash
nemoclaw physgen connect
```

Then inside the environment:

```bash
openclaw tui
```

Do not configure web search, messaging, or external integrations for the PhysGen MVP unless specifically needed.

---

# 22. OPENSHELL MANUAL FALLBACK

Only if NemoClaw's maintained install path does not successfully provision it.

- Repo:
  https://github.com/NVIDIA/OpenShell
- Docs:
  https://docs.nvidia.com/openshell/latest/

Installer:

```bash
curl -LsSf https://raw.githubusercontent.com/NVIDIA/OpenShell/main/install.sh | sh
```

Alternative:

```bash
uv tool install -U openshell
```

Verify:

```bash
openshell --help
openshell status
```

Do not install this separately if NemoClaw already installed a working version.

---

# 23. OPENCLAW MANUAL FALLBACK

Only use if needed after NemoClaw diagnostics.

Repo:

https://github.com/openclaw/openclaw

Installer:

```bash
curl -fsSL https://openclaw.ai/install.sh | bash
```

Prefer the NemoClaw-managed OpenClaw path for the actual hackathon.

---

# 24. PROJECT CODE SCAFFOLD

After infrastructure is validated, create:

```bash
mkdir -p \
  ~/physgen/app/agent \
  ~/physgen/app/generation \
  ~/physgen/app/physics \
  ~/physgen/app/validation \
  ~/physgen/app/ui \
  ~/physgen/app/examples
```

Recommended modules:

```text
~/physgen/app/
|
+-- agent/
|   +-- intent_parser.py
|   +-- tools.py
|
+-- generation/
|   +-- oat_generator.py
|   +-- candidate_generator.py
|
+-- physics/
|   +-- problem.py
|   +-- solver.py
|   +-- simp_baseline.py
|   +-- metrics.py
|
+-- validation/
|   +-- validator.py
|   +-- ranker.py
|
+-- ui/
|   +-- app.py
|
+-- examples/
    +-- cantilever.json
```

Core interfaces:

```python
parse_requirement(text) -> DesignProblem

generate_candidates(problem, n_candidates=8) -> list[Topology]

simulate(topology, problem) -> SimulationResult

validate(result, problem) -> ValidationResult

rank(candidates) -> RankedCandidates
```

---

# 25. DESIGN PROBLEM SCHEMA

Use a structured schema rather than free-form text after the LLM parsing boundary.

Suggested shape:

```json
{
  "domain": {
    "width": 128,
    "height": 64
  },
  "volume_fraction": 0.40,
  "supports": [
    {
      "type": "edge",
      "edge": "left",
      "fix_x": true,
      "fix_y": true
    }
  ],
  "loads": [
    {
      "x": 127,
      "y": 32,
      "fx": 0.0,
      "fy": -1.0
    }
  ],
  "material": {
    "youngs_modulus": 1.0,
    "poisson_ratio": 0.3
  }
}
```

For the first demo, use normalized engineering units unless the chosen FEA implementation and boundary conditions are explicitly calibrated to real units.

Do not make unsupported claims about MPa, safety factors, or material strength unless the solver setup actually computes them correctly.

---

# 26. MVP INTEGRATION ORDER

Codex should implement in this order:

## Gate A  -  deterministic physics

Must work first:

```text
DesignProblem
   |
   v
SIMP / topology optimizer
   |
   v
FEA metrics + image
```

## Gate B  -  OAT generation

```text
DesignProblem / OpenTO condition
   |
   v
LDM_L
   |
   v
NFAE_L
   |
   v
density field
```

## Gate C  -  verification

```text
OAT topology
   |
   v
independent FEA
   |
   v
compliance / volume / displacement
```

## Gate D  -  multi-candidate generation

Generate:

```text
8 candidates
```

Then:

```text
FEA each candidate
-> reject invalid candidates
-> rank valid candidates
-> select best
```

If runtime is fast enough, increase to 16.

## Gate E  -  agent

Natural language:

```text
"Use 40% material, fix the left edge, and place a downward load on the far right."
```

Agent converts this into the structured `DesignProblem`, then calls tools.

## Gate F  -  UI

Only after the end-to-end loop works.

---

# 27. UI MVP

Use Streamlit unless there is a compelling reason not to.

Run:

```bash
pip install streamlit plotly
```

UI should show:

1. natural-language requirement;
2. parsed supports/load/volume;
3. generated candidate grid;
4. physics metrics per candidate;
5. rejected candidates visibly marked;
6. best valid design;
7. comparison against traditional SIMP;
8. local-model/runtime metadata.

Suggested visual:

```text
+--------------------------------------------------------+
| PHYSgen  -  Generate with AI. Verify with physics.       |
+--------------------------------------------------------+
| Requirement                                            |
| "Use <=40% material..."                                |
+----------------------+---------------------------------+
| Problem             | Geometry / Candidate             |
| fixed: left         |                                 |
| force: right/down   |        [ topology ]             |
| volume: 40%         |                                 |
+----------------------+---------------------------------+
| Candidate | Compliance | Volume | Displacement | Valid |
| A         | ...        | ...    | ...          | YES   |
| B         | ...        | ...    | ...          | NO    |
+--------------------------------------------------------+
| BEST PHYSICS-VALID DESIGN                              |
+--------------------------------------------------------+
```

---

# 28. WHAT NOT TO BUILD DURING SETUP

Do not install or integrate these into the MVP unless everything above is already working:

- Stable Diffusion / SDXL
- Gaussian splatting
- Cosmos
- Isaac Sim
- arbitrary 3D CAD generation
- full FEniCS stack
- CalculiX
- CFD
- fracture simulation
- custom diffusion training
- custom surrogate model
- TopoDiff
- TopoTransformer
- PETSc unless genuinely needed
- MKL-specific optimization
- CHOLMOD tuning
- 120B agent model

The hackathon path is intentionally 2D and constrained.

---

# 29. MODEL/REPO DOWNLOAD PRIORITY

If network is weak, follow this exact order.

## Tier 1  -  must have

1. `OpenTO/NFAE_L`
2. `OpenTO/LDM_L`
3. `ahnobari/OptimizeAnyTopology`
4. `nvidia/Qwen3.6-35B-A3B-NVFP4` / NemoClaw managed cache
5. OpenTO test data
6. NemoClaw
7. Python/Hugging Face tooling

## Tier 2  -  fallback

8. `scikit-topt`
9. DTU `topopt.py`
10. `OpenTO/NFAE`
11. `OpenTO/LDM`

## Tier 3  -  optional

12. NITO checkpoints
13. Nemotron 3 Nano NVFP4

---

# 30. LICENSING / ATTRIBUTION CHECK

Before final submission, record the license/attribution status of everything actually used.

Known important points:

- `nvidia/Qwen3.6-35B-A3B-NVFP4`: Apache 2.0
- `scikit-topt`: Apache 2.0
- NemoClaw/OpenShell: verify current repository licenses at install time
- Nemotron checkpoint: NVIDIA Nemotron Open Model License
- OpenTO/OAT checkpoint model cards may not clearly surface an explicit model license

Codex should **not invent or assume a license**.

Create:

```text
~/physgen/LICENSE_NOTES.md
```

containing:
- component;
- source URL;
- license shown upstream;
- commit/revision/model revision used.

If the hackathon's “open source” rule requires explicit permissive licensing for all checkpoints, flag the OAT checkpoint status to the user immediately rather than making a legal conclusion.

---

# 31. COMPLETE LINK INDEX

## Primary models

OpenTO NFAE_L
https://huggingface.co/OpenTO/NFAE_L

OpenTO LDM_L
https://huggingface.co/OpenTO/LDM_L

NVIDIA Qwen3.6-35B-A3B-NVFP4
https://huggingface.co/nvidia/Qwen3.6-35B-A3B-NVFP4

## OAT fallback models

OpenTO NFAE
https://huggingface.co/OpenTO/NFAE

OpenTO LDM
https://huggingface.co/OpenTO/LDM

## Optional agent model

NVIDIA Nemotron 3 Nano 30B-A3B NVFP4
https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4

## Dataset

OpenTO
https://huggingface.co/datasets/OpenTO/OpenTO

## Repositories

Optimize Any Topology
https://github.com/ahnobari/OptimizeAnyTopology

Scikit-Topt
https://github.com/kevin-tofu/scikit-topt

NITO
https://github.com/ahnobari/NITO_Public

NemoClaw
https://github.com/NVIDIA/NemoClaw

OpenShell
https://github.com/NVIDIA/OpenShell

OpenClaw
https://github.com/openclaw/openclaw

CuPy
https://github.com/cupy/cupy

## Documentation / downloads

DTU Python TopOpt
https://www.topopt.mek.dtu.dk/apps-and-software/topology-optimization-codes-written-in-python1

CuPy install
https://docs.cupy.dev/en/stable/install.html

NemoClaw docs
https://docs.nvidia.com/nemoclaw/latest/

OpenShell docs
https://docs.nvidia.com/openshell/latest/

DGX Spark / Grace Blackwell docs
https://docs.nvidia.com/dgx/dgx-spark/

DGX Spark software stack
https://docs.nvidia.com/dgx/dgx-spark/software.html

---

# 32. FINAL VALIDATION SCRIPT

At the end, create and run:

```bash
cat > ~/physgen/verify_setup.sh <<'SH'
#!/usr/bin/env bash
set -u

echo "=== PHYSgen setup verification ==="
echo

echo "[HOST]"
uname -m
python3 --version
echo

echo "[DISK]"
df -h ~ | tail -1
echo

echo "[NVIDIA]"
nvidia-smi 2>/dev/null || echo "nvidia-smi unavailable"
echo

echo "[PYTHON ENV]"
if [ -f "$HOME/physgen/.venv/bin/activate" ]; then
  source "$HOME/physgen/.venv/bin/activate"
fi

python - <<'PY'
print("Python import checks:")
mods = ["numpy", "scipy", "matplotlib", "torch"]
for m in mods:
    try:
        mod = __import__(m)
        print(f"  {m}: OK ({getattr(mod, '__version__', 'unknown')})")
    except Exception as e:
        print(f"  {m}: FAIL ({e})")

try:
    import torch
    print("  torch CUDA:", torch.version.cuda)
    print("  CUDA available:", torch.cuda.is_available())
    if torch.cuda.is_available():
        print("  GPU:", torch.cuda.get_device_name(0))
except Exception:
    pass

try:
    import cupy as cp
    print("  cupy: OK", cp.__version__)
except Exception as e:
    print("  cupy: WARN", e)
PY

echo
echo "[REPOS]"
for r in OptimizeAnyTopology scikit-topt NITO_Public; do
  if [ -d "$HOME/physgen/repos/$r" ]; then
    echo "  $r: present"
  else
    echo "  $r: absent"
  fi
done

echo
echo "[HF CACHE]"
if command -v hf >/dev/null 2>&1; then
  hf cache ls 2>/dev/null | grep -E 'OpenTO|Qwen3.6|Nemotron' || true
else
  echo "  hf CLI not found"
fi

echo
echo "[NEMOCLAW]"
if command -v nemoclaw >/dev/null 2>&1; then
  nemoclaw --help >/dev/null 2>&1 && echo "  nemoclaw CLI: OK"
  nemoclaw physgen status 2>/dev/null || true
else
  echo "  nemoclaw CLI: not found"
fi

echo
echo "[OPENSHELL]"
if command -v openshell >/dev/null 2>&1; then
  openshell --help >/dev/null 2>&1 && echo "  openshell CLI: OK"
  openshell status 2>/dev/null || true
else
  echo "  openshell CLI: not found"
fi

echo
echo "=== verification complete ==="
SH

chmod +x ~/physgen/verify_setup.sh
~/physgen/verify_setup.sh | tee ~/physgen/setup-logs/final-verification.txt
```

---

# 33. FINAL HANDOFF REPORT CODEX MUST PRODUCE

When finished, respond to the user in this format:

```text
PHYSgen setup status

Host:
- Architecture:
- GPU:
- CUDA:
- Python:
- PyTorch:

Models:
- OpenTO/NFAE_L: READY / FAILED
- OpenTO/LDM_L: READY / FAILED
- Qwen3.6-35B-A3B-NVFP4: READY / MANAGED BY NEMOCLAW / FAILED
- fallback OAT pair: CACHED / NOT CACHED
- optional Nemotron: CACHED / NOT CACHED

Physics:
- OAT imports:
- OAT sample inference:
- baseline FEA:
- baseline topology optimization:

Agent stack:
- NemoClaw:
- OpenShell:
- OpenClaw:
- local inference:

Outputs created:
- ...

Warnings:
- ...

Next recommended action:
- ...
```

Do not declare success unless actual commands/tests confirm it.

---

# 34. BUILD PLAN AFTER INSTALLATION

Once the environment passes verification, build in this order:

```text
1. Known 2D SIMP/FEA problem
2. OAT single-candidate generation
3. Independent FEA on OAT candidate
4. 8-candidate batch
5. filtering + ranking
6. DesignProblem schema
7. agent tool wrappers
8. natural-language -> DesignProblem
9. Streamlit UI
10. polish + telemetry
```

Do not reverse this order.

---

# 35. PHYSGen DEMO TARGET

Final demo path:

```text
User:
"Use no more than 40% material.
Fix the left edge.
Put a downward load on the far right."

                    |
                    v

Agent parses engineering intent

                    |
                    v

OpenTO generates 8 candidate structures

 [A] [B] [C] [D] [E] [F] [G] [H]

                    |
                    v

Real FEA evaluates every candidate

                    |
          +---------+----------+
          |                    |
       REJECT               VALID
          |                    |
          +---------+----------+
                    |
                    v

Rank valid designs by compliance / constraints

                    |
                    v

BEST PHYSICS-VALID DESIGN

                    |
                    v

Compare against traditional SIMP baseline
```

The message to judges:

> **PhysGen does not trust the generative model. It uses AI to explore the design space quickly, then lets deterministic physics decide which designs are actually valid.**

---

# 36. ONE-LINE PROJECT PRINCIPLE

> **The model proposes. Physics decides.**
