# PhysGen Hackathon  -  Complete Download & Setup Manifest

> **Current transport media:** The team has a USB-A external HDD, not an SSD.
> Use it for transport and recovery. Copy the selected checkpoint and
> latency-sensitive runtime files to the GB10 internal NVMe before serving when
> capacity permits, and measure that copy time during rehearsal.

**Target:** Dell Pro Max with GB10 / Grace Blackwell-class system
**Project:** PhysGen  -  generate engineering material topologies with AI, then verify/rank them with real physics
**Last verified:** 2026-08-22

> **Core rule:** The generative model proposes; the FEA solver decides.

---

## 0. What to download before arriving

### Download these first  -  required

| Priority | Item | Why |
|---|---|---|
| **P0** | `OpenTO/NFAE_L` | Large-latent autoencoder/decoder for OAT |
| **P0** | `OpenTO/LDM_L` | Large-latent conditional diffusion model for topology generation |
| **P0** | `ahnobari/OptimizeAnyTopology` | Official OAT inference + FEA/topology code |
| **P0** | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4` | Local OpenClaw/NemoClaw agent model |
| **P0** | OpenTO test data / dataset | Lets OAT examples run without depending on venue Wi-Fi |
| **P0** | NemoClaw | Required hackathon agent stack; provisions OpenClaw/OpenShell |
| **P1** | `scikit-topt` | Independent, simple physics/topology baseline/fallback |
| **P1** | DTU `topopt.py` | Tiny emergency fallback: NumPy + SciPy + Matplotlib only |

### Download only as fallbacks

| Priority | Item | When to use |
|---|---|---|
| **P1 fallback** | `OpenTO/NFAE` | If `_L` model pair gives integration problems |
| **P1 fallback** | `OpenTO/LDM` | If `_L` model pair gives integration problems |
| **P2 fallback** | NITO repo/checkpoints | If OAT inference itself becomes unusable |
| **P2 fallback** | Qwen local LLM | Only if Nemotron/local NemoClaw inference fails |

---

# 1. PRIMARY TOPOLOGY MODELS

## 1.1 OpenTO NFAE_L  -  REQUIRED

**Purpose:** Decodes the topology latent representation back into the material-density field.

- Hugging Face: https://huggingface.co/OpenTO/NFAE_L
- Files: https://huggingface.co/OpenTO/NFAE_L/tree/main
- Approximate download size: **232 MB**

```bash
hf download OpenTO/NFAE_L \
  --local-dir ~/physgen/models/OpenTO-NFAE_L
```

## 1.2 OpenTO LDM_L  -  REQUIRED

**Purpose:** Conditional latent-diffusion model that generates candidate topologies from structural conditions.

- Hugging Face: https://huggingface.co/OpenTO/LDM_L
- Files: https://huggingface.co/OpenTO/LDM_L/tree/main
- Direct weight page: https://huggingface.co/OpenTO/LDM_L/blob/main/diffusion_pytorch_model.safetensors
- Approximate download size: **2.71 GB**

```bash
hf download OpenTO/LDM_L \
  --local-dir ~/physgen/models/OpenTO-LDM_L
```

**Important:** do not rely on the generic Hugging Face `DiffusionPipeline` example on this model page. For PhysGen, use the **official OptimizeAnyTopology code**, which loads OAT's custom `CTOPUNET` and structural conditioning.

---

# 2. STANDARD OAT MODELS  -  FALLBACK

If `NFAE_L + LDM_L` causes compatibility/debugging issues, immediately switch to the smaller-latent pair.

## OpenTO NFAE

- Hugging Face: https://huggingface.co/OpenTO/NFAE
- Files: https://huggingface.co/OpenTO/NFAE/tree/main
- Approximate size: **236 MB**

```bash
hf download OpenTO/NFAE \
  --local-dir ~/physgen/models/OpenTO-NFAE
```

## OpenTO LDM

- Hugging Face: https://huggingface.co/OpenTO/LDM
- Files: https://huggingface.co/OpenTO/LDM/tree/main
- Approximate size: **2.71 GB**

```bash
hf download OpenTO/LDM \
  --local-dir ~/physgen/models/OpenTO-LDM
```

---

# 3. OAT / OpenTO CODE  -  REQUIRED

## Optimize Any Topology

**Official repo:** https://github.com/ahnobari/OptimizeAnyTopology

```bash
mkdir -p ~/physgen/repos
cd ~/physgen/repos

git clone https://github.com/ahnobari/OptimizeAnyTopology.git
cd OptimizeAnyTopology
```

The repository includes OAT model classes, NFAE loading, conditional LDM / `CTOPUNET`, sample generation, topology optimization, FEA, GPU/CPU compliance evaluation, a `pyEDGE` fork, and OpenTO dataset integration.

**Requirements:** https://github.com/ahnobari/OptimizeAnyTopology/blob/master/requirements.txt

---

# 4. OpenTO DATASET  -  RECOMMENDED TO CACHE

- Dataset: https://huggingface.co/datasets/OpenTO/OpenTO
- Files: https://huggingface.co/datasets/OpenTO/OpenTO/tree/main
- Approximate converted dataset size: **2.21 GB**

You **do not need to train OAT** tomorrow. Cache it for known test cases and offline inference validation.

### Safest option  -  full dataset

```bash
hf download OpenTO/OpenTO \
  --repo-type dataset \
  --local-dir ~/physgen/data/OpenTO
```

### Minimum option  -  test parquet only

```bash
hf download OpenTO/OpenTO \
  --repo-type dataset \
  --include "data/test-00000-of-00001.parquet" \
  --local-dir ~/physgen/data/OpenTO-test
```

---

# 5. LOCAL AGENT MODEL  -  REQUIRED

## NVIDIA Nemotron 3 Nano 30B-A3B NVFP4

Use it for natural-language requirement parsing, building `DesignProblem`, tool calls, candidate ranking, and explanations.

**Do not use the LLM to calculate physics.**

- Hugging Face: https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4
- Files: https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4/tree/main
- NVIDIA Nemotron: https://developer.nvidia.com/topics/ai/nemotron
- Approximate checkpoint size: **19.4 GB**

```bash
hf download nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4 \
  --local-dir ~/physgen/models/Nemotron-3-Nano-30B-A3B-NVFP4
```

Why this version:

- 30B total / roughly 3–4B active parameters per token
- MoE architecture
- NVFP4 is targeted at Blackwell
- enough for structured parsing and agent/tool orchestration
- leaves substantially more headroom than a 120B agent model

---

# 6. BACKUP LOCAL LLM  -  OPTIONAL

## Qwen3 30B-A3B

Only use if Nemotron/local NemoClaw inference fails.

- Hugging Face: https://huggingface.co/Qwen/Qwen3-30B-A3B
- Files: https://huggingface.co/Qwen/Qwen3-30B-A3B/tree/main
- License: Apache 2.0
- Full checkpoint is large (~61 GB)

```bash
hf download Qwen/Qwen3-30B-A3B \
  --local-dir ~/physgen/models/Qwen3-30B-A3B
```

**Recommendation:** don't download this by default unless you have plenty of SSD space/bandwidth.

---

# 7. PHYSICS / TOPOLOGY OPTIMIZATION

## 7.1 Scikit-Topt  -  REQUIRED FALLBACK

Use for an independent FEA + traditional topology-optimization baseline.

- GitHub: https://github.com/kevin-tofu/scikit-topt
- Docs: https://scikit-topt.readthedocs.io/en/latest/
- License: Apache 2.0

```bash
pip install scikit-topt
```

For the hackathon, don't start with PETSc.

## 7.2 DTU Python TopOpt  -  EMERGENCY FALLBACK

Official page:
https://www.topopt.mek.dtu.dk/apps-and-software/topology-optimization-codes-written-in-python1

Requires essentially:

```bash
pip install numpy scipy matplotlib
```

Example from DTU:

```bash
python topopt.py 180 60 0.4 5.4 3.0 1
```

This is the last-resort baseline that should still give the team a working traditional topology optimizer.

---

# 8. OPTIONAL ALTERNATIVE TOPOLOGY MODEL

## NITO

Only download if you want an OAT fallback/comparison.

- GitHub: https://github.com/ahnobari/NITO_Public

```bash
git clone https://github.com/ahnobari/NITO_Public.git
cd NITO_Public
python download.py --checkpoints
```

Dataset + checkpoints:

```bash
python download.py --all
```

Do not make NITO part of the initial MVP.

---

# 9. HACKATHON AGENT STACK  -  REQUIRED

## 9.1 NemoClaw

- GitHub: https://github.com/NVIDIA/NemoClaw
- Docs: https://docs.nvidia.com/nemoclaw/latest/

Recommended installer:

```bash
curl -fsSL https://www.nvidia.com/nemoclaw.sh | bash
```

NemoClaw composes the model, OpenClaw harness, and OpenShell sandbox.

**Do not separately install OpenClaw and OpenShell first unless debugging/manual setup requires it.**

## 9.2 OpenShell  -  manual/troubleshooting path

- GitHub: https://github.com/NVIDIA/OpenShell
- Docs: https://docs.nvidia.com/openshell/latest/

```bash
curl -LsSf https://raw.githubusercontent.com/NVIDIA/OpenShell/main/install.sh | sh
```

Alternative:

```bash
uv tool install -U openshell
```

## 9.3 OpenClaw  -  manual/troubleshooting path

- GitHub: https://github.com/openclaw/openclaw

```bash
curl -fsSL https://openclaw.ai/install.sh | bash
```

Prefer NemoClaw onboarding for the actual hackathon stack.

---

# 10. HUGGING FACE DOWNLOADER  -  REQUIRED

```bash
python -m pip install -U "huggingface_hub[hf_xet]"
hf auth login
hf auth whoami
```

Use `hf download` rather than grabbing one `.safetensors` file manually, because the model repository also contains config/metadata/index files.

---

# 11. GB10 / GRACE BLACKWELL ENVIRONMENT

The GB10 platform is **ARM64/aarch64**, not x86_64.

Verify:

```bash
uname -m
```

Expected:

```text
aarch64
```

Verify PyTorch/CUDA:

```bash
python - <<'PY'
import torch
print("torch:", torch.__version__)
print("cuda:", torch.version.cuda)
print("cuda available:", torch.cuda.is_available())
if torch.cuda.is_available():
    print("device:", torch.cuda.get_device_name(0))
PY
```

Grace Blackwell/DGX-Spark-class systems ship with CUDA, PyTorch/Jupyter, Docker and NVIDIA Container Runtime, so **verify before reinstalling anything**.

References:

- https://docs.nvidia.com/dgx/dgx-spark/
- https://docs.nvidia.com/dgx/dgx-spark/software.html
- https://docs.nvidia.com/dgx/dgx-spark/nvidia-container-runtime-for-docker.html

---

# 12. IMPORTANT OAT + CUDA 13 FIX

OAT's current `requirements.txt` lists:

```text
cupy_cuda12x
```

The current Grace Blackwell software stack is CUDA 13.x. CuPy publishes CUDA-13 wheels for Linux **aarch64**.

Official CuPy docs: https://docs.cupy.dev/en/stable/install.html
CuPy GitHub: https://github.com/cupy/cupy

Install:

```bash
pip install cupy-cuda13x
```

If OAT install tries CUDA 12 CuPy:

```bash
pip uninstall -y cupy cupy-cuda12x cupy_cuda12x
pip install -U cupy-cuda13x
```

Or create a GB10 requirements file:

```bash
sed 's/cupy_cuda12x/cupy-cuda13x/' requirements.txt > requirements-gb10.txt
pip install -r requirements-gb10.txt
```

---

# 13. PYTHON ENVIRONMENT

Recommended: **Python 3.11 or 3.12**.

```bash
mkdir -p ~/physgen
cd ~/physgen

python3 -m venv .venv
source .venv/bin/activate

python -m pip install -U pip setuptools wheel
python -m pip install -U "huggingface_hub[hf_xet]"
```

Then:

```bash
cd ~/physgen/repos/OptimizeAnyTopology
grep cupy requirements.txt
sed 's/cupy_cuda12x/cupy-cuda13x/' requirements.txt > requirements-gb10.txt
pip install -r requirements-gb10.txt

pip install scikit-topt
```

### If `scikit-sparse` / CHOLMOD becomes a time sink

Do not burn hackathon time on Intel/MKL/CHOLMOD optimizations.

Priority:

1. OAT model inference works.
2. Any real FEA path works.
3. Use Scikit-Topt/DTU if OAT's optimized FEA dependencies fight ARM64.
4. Optimize only after the demo works.

---

# 14. OPTIONAL UI PACKAGES

Fastest path:

```bash
pip install streamlit plotly pandas
```

Suggested view:

```text
┌────────────────────────────────────────────┐
│ PHYSgen                                    │
├────────────────────────────────────────────┤
│ Natural-language engineering requirement  │
├────────────────────────────────────────────┤
│ [A] [B] [C] [D] [E] [F] [G] [H]          │
├────────────────────────────────────────────┤
│ compliance | volume | displacement | pass  │
├────────────────────────────────────────────┤
│ BEST PHYSICS-VALID DESIGN                  │
└────────────────────────────────────────────┘
```

---

# 15. RECOMMENDED DIRECTORY LAYOUT

```text
~/physgen/
│
├── .venv/
├── models/
│   ├── OpenTO-NFAE_L/
│   ├── OpenTO-LDM_L/
│   ├── OpenTO-NFAE/              # fallback
│   ├── OpenTO-LDM/               # fallback
│   └── Nemotron-3-Nano-30B-A3B-NVFP4/
│
├── data/
│   ├── OpenTO/
│   └── OpenTO-test/
│
├── repos/
│   ├── OptimizeAnyTopology/
│   ├── scikit-topt/
│   └── NITO_Public/              # optional
│
└── app/
    ├── agent/
    ├── generation/
    ├── physics/
    ├── validation/
    └── ui/
```

---

# 16. COPY/PASTE MODEL DOWNLOAD BLOCK

```bash
mkdir -p ~/physgen/models ~/physgen/data ~/physgen/repos

# PRIMARY OAT LARGE-LATENT PAIR
hf download OpenTO/NFAE_L \
  --local-dir ~/physgen/models/OpenTO-NFAE_L

hf download OpenTO/LDM_L \
  --local-dir ~/physgen/models/OpenTO-LDM_L

# PRIMARY LOCAL AGENT
hf download nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4 \
  --local-dir ~/physgen/models/Nemotron-3-Nano-30B-A3B-NVFP4

# CACHE DATASET
hf download OpenTO/OpenTO \
  --repo-type dataset \
  --local-dir ~/physgen/data/OpenTO

# FALLBACK OAT PAIR
hf download OpenTO/NFAE \
  --local-dir ~/physgen/models/OpenTO-NFAE

hf download OpenTO/LDM \
  --local-dir ~/physgen/models/OpenTO-LDM
```

---

# 17. COPY/PASTE REPO CLONE BLOCK

```bash
mkdir -p ~/physgen/repos
cd ~/physgen/repos

git clone https://github.com/ahnobari/OptimizeAnyTopology.git
git clone https://github.com/kevin-tofu/scikit-topt.git

# Optional fallback
git clone https://github.com/ahnobari/NITO_Public.git

# Hackathon stack source for offline inspection/debugging
git clone https://github.com/NVIDIA/NemoClaw.git
git clone https://github.com/NVIDIA/OpenShell.git
git clone https://github.com/openclaw/openclaw.git
```

Cloning all three agent-stack repos is not required to *use* NemoClaw; it is useful if venue networking is poor or you need source locally.

---

# 18. SANITY CHECKS BEFORE LEAVING

## Models

```bash
du -sh ~/physgen/models/*
```

Must have:

```text
OpenTO-NFAE_L
OpenTO-LDM_L
Nemotron-3-Nano-30B-A3B-NVFP4
```

## OAT

```bash
python - <<'PY'
import torch
print("Torch:", torch.__version__)
print("CUDA:", torch.version.cuda)
print("CUDA available:", torch.cuda.is_available())

from OAT.Models import NFAE, CTOPUNET
print("OAT models import: OK")
PY
```

## CuPy

```bash
python - <<'PY'
import cupy as cp
print("CuPy:", cp.__version__)
print(cp.arange(5))
PY
```

## NemoClaw/OpenShell

```bash
nemoclaw --help
openshell status
```

---

# 19. WHAT NOT TO DOWNLOAD FOR THE MVP

Do **not** add these until the core demo works:

- Stable Diffusion / SDXL
- Gaussian-splatting models
- Cosmos
- Isaac Sim
- FEniCS
- CalculiX
- custom diffusion training checkpoints
- custom compliance surrogate
- TopoDiff
- TopoTransformer
- 120B Nemotron
- arbitrary 3D CAD generation stack
- PETSc
- MKL-specific OAT acceleration

The MVP is:

```text
Natural language
        ↓
Nemotron / OpenClaw
        ↓
DesignProblem
        ↓
OpenTO LDM_L
        ↓
OpenTO NFAE_L
        ↓
8–16 generated topologies
        ↓
real FEA
        ↓
physics filtering + ranking
        ↓
best valid design
```

---

# 20. DOWNLOAD PRIORITY IF INTERNET/TIME IS BAD

### Tier 1  -  must have

1. `OpenTO/NFAE_L`
2. `OpenTO/LDM_L`
3. `OptimizeAnyTopology`
4. `Nemotron-3-Nano-30B-A3B-NVFP4`
5. OpenTO test split
6. NemoClaw
7. HF/Python tooling

### Tier 2  -  strongly recommended

8. Scikit-Topt
9. DTU `topopt.py`
10. standard `OpenTO/NFAE + OpenTO/LDM`

### Tier 3  -  only if spare storage/time

11. full OpenTO dataset
12. NITO checkpoints
13. Qwen backup LLM

---

# 21. LICENSING WARNING

Because the project constraint is open/local tooling, verify the event's exact licensing definition.

Current status:

- **Scikit-Topt:** Apache 2.0
- **NemoClaw:** Apache 2.0
- **OpenShell:** Apache 2.0
- **Qwen3:** Apache 2.0
- **Nemotron:** NVIDIA Nemotron Open Model License
- **OAT/OpenTO checkpoints:** publicly downloadable, but the current Hugging Face cards do **not clearly declare a model license**
- **OptimizeAnyTopology:** public source, but a clearly surfaced repository license is not obvious on the current repo page

This does not automatically prevent OAT usage; it means don't claim an OSI/permissive license for OAT unless the organizer confirms the requirement and the model authors clarify licensing.

---

# 22. MASTER LINK LIST

## Models

- OpenTO NFAE_L  -  https://huggingface.co/OpenTO/NFAE_L
- OpenTO LDM_L  -  https://huggingface.co/OpenTO/LDM_L
- OpenTO NFAE  -  https://huggingface.co/OpenTO/NFAE
- OpenTO LDM  -  https://huggingface.co/OpenTO/LDM
- Nemotron 3 Nano NVFP4  -  https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-NVFP4
- Qwen3 30B-A3B  -  https://huggingface.co/Qwen/Qwen3-30B-A3B

## Dataset

- OpenTO  -  https://huggingface.co/datasets/OpenTO/OpenTO

## GitHub

- OAT  -  https://github.com/ahnobari/OptimizeAnyTopology
- Scikit-Topt  -  https://github.com/kevin-tofu/scikit-topt
- NITO  -  https://github.com/ahnobari/NITO_Public
- NemoClaw  -  https://github.com/NVIDIA/NemoClaw
- OpenShell  -  https://github.com/NVIDIA/OpenShell
- OpenClaw  -  https://github.com/openclaw/openclaw
- CuPy  -  https://github.com/cupy/cupy

## Other downloads/docs

- DTU TopOpt  -  https://www.topopt.mek.dtu.dk/apps-and-software/topology-optimization-codes-written-in-python1
- CuPy install  -  https://docs.cupy.dev/en/stable/install.html
- NemoClaw docs  -  https://docs.nvidia.com/nemoclaw/latest/
- OpenShell docs  -  https://docs.nvidia.com/openshell/latest/
- DGX Spark / Grace Blackwell  -  https://docs.nvidia.com/dgx/dgx-spark/
- GB10 software  -  https://docs.nvidia.com/dgx/dgx-spark/software.html

---

# 23. FINAL STACK

```text
                        USER
                          │
                          ▼
              Nemotron 3 Nano NVFP4
                 OpenClaw / NemoClaw
                          │
                          ▼
                    DesignProblem
                          │
            ┌─────────────┴─────────────┐
            │                           │
            ▼                           ▼
      OpenTO LDM_L               SIMP baseline
            │
            ▼
      OpenTO NFAE_L
            │
            ▼
     8–16 candidates
            │
            ▼
     REAL FEA VALIDATION
            │
      ┌─────┼──────────┐
      ▼     ▼          ▼
 compliance volume displacement
      │     │          │
      └─────┼──────────┘
            ▼
       filter + rank
            │
            ▼
      BEST VALID DESIGN
```

> **Generate with AI. Verify with physics.**
