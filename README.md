# NVIDIA x Dell NYC Hackathon
<img width="1672" height="941" alt="image" src="https://github.com/user-attachments/assets/c6916dfc-42c2-4e24-abe3-41f4e19f39eb" />


Shared preparation and experiment repository for an offline demo on one Dell
GB10. The team may explore several ideas, but evidence converges in one place:
[issue #1](https://github.com/shivraj-S-bhatti/nvidia_dell_hack_nyc/issues/1).

Final UI and backend owners should start with
[FINAL_UI_BACKEND_INTEGRATION.md](FINAL_UI_BACKEND_INTEGRATION.md). It defines
the judged surface, artifact boundary, viewer bridge, human-selection gate, and
offline acceptance checks.

## Destination

Ship one five-minute demo that:

- runs locally with NemoClaw, OpenClaw, and OpenShell
- has a strict input and output contract
- closes a loop through deterministic validation or execution
- reports at least one measured outcome against a baseline
- can be replayed with venue networking disabled

## Start here

1. Read the [convergence epic](https://github.com/shivraj-S-bhatti/nvidia_dell_hack_nyc/issues/1).
2. Run the target-machine doctor and attach its output to
   [issue #3](https://github.com/shivraj-S-bhatti/nvidia_dell_hack_nyc/issues/3):

   ```bash
   ./scripts/doctor.sh --external-root /path/to/hackathon-hdd \
     | tee gb10-doctor.md
   ```

3. Create a project attempt with the GitHub experiment issue template.
4. Stop at its 90-minute kill criterion and post evidence to the issue.
5. Use [issue #4](https://github.com/shivraj-S-bhatti/nvidia_dell_hack_nyc/issues/4)
   to select one build.

## Active route

- [#2: offline HDD kit](https://github.com/shivraj-S-bhatti/nvidia_dell_hack_nyc/issues/2)
- [#3: common GB10 runtime](https://github.com/shivraj-S-bhatti/nvidia_dell_hack_nyc/issues/3)
- [#4: experiment bake-off](https://github.com/shivraj-S-bhatti/nvidia_dell_hack_nyc/issues/4)

Candidate projects and custom-kernel work remain queued in GitHub. Issues are
the execution record; `docs/research/` holds evidence and constraints.

## Verified GB10 model inference and harness boundary

This is the setup verified on the event GB10 on 2026-08-22. The measurements
and machine evidence are recorded in [issue #10](https://github.com/shivraj-S-bhatti/nvidia_dell_hack_nyc/issues/10).
It is a record of what passed, not a claim that every acceptance test in that
issue is complete.

| Component | Verified state |
|---|---|
| Host | Ubuntu 24.04.4 on `aarch64`; NVIDIA GB10; driver 580.173.02; driver CUDA 13.0 |
| Model | `nvidia/Qwen3.6-35B-A3B-NVFP4`, revision `491c2f1ea524c639598bf8fa787a93fed5a6fbce` |
| Checkpoint | 21.82 GiB loaded from the local kit and mounted read-only at `/models/qwen` |
| Server | NVIDIA vLLM release `26.05.post1`, vLLM `0.21.0+2325b6f0`, loaded ARM64 image ID `sha256:46591c6e4a018d8d197fa246b1e3d682c907654aab4e9402302abb3e6a7dd916` |
| API | OpenAI-compatible API from container `attempt1-vllm`; model context reported as 262,144 tokens |
| Host route | `http://127.0.0.1:8000/v1` |
| Sandbox route | `http://host.openshell.internal:8000/v1` through Docker network `openshell-docker` |
| Harness prerequisites | Node.js 22.23.2, OpenClaw 2026.7.1, and OpenShell 0.0.101 installed user-locally |

The verified container runs the following command with `/models/qwen` supplied
by a read-only bind mount:

```bash
vllm serve /models/qwen \
  --served-model-name nvidia/Qwen3.6-35B-A3B-NVFP4 \
  --host 0.0.0.0 \
  --port 8000 \
  --max-model-len 262144 \
  --gpu-memory-utilization 0.4 \
  --dtype auto \
  --quantization modelopt \
  --kv-cache-dtype fp8 \
  --attention-backend flashinfer \
  --moe-backend marlin \
  --max-num-seqs 4 \
  --max-num-batched-tokens 8192 \
  --enable-chunked-prefill \
  --async-scheduling \
  --enable-prefix-caching \
  --enable-auto-tool-choice \
  --tool-call-parser qwen3_coder \
  --reasoning-parser qwen3
```

`0.0.0.0` above is the address *inside the container*. Docker publishes it on
the host only at `127.0.0.1:8000` and the private OpenShell bridge gateway
`172.18.0.1:8000`; `ss` confirmed that there is no wildcard or LAN listener.
The container also uses all available NVIDIA GPUs, host IPC, 64 GiB shared
memory, unlimited locked memory, a 64 MiB stack ulimit, and restart policy
`unless-stopped`. Preserve those settings if the container is recreated.

On the existing GB10 installation, start and verify the endpoint with:

```bash
docker start attempt1-vllm

curl --fail --silent --show-error \
  http://127.0.0.1:8000/v1/models

curl --fail --silent --show-error \
  -H 'Content-Type: application/json' \
  -d '{"model":"nvidia/Qwen3.6-35B-A3B-NVFP4","messages":[{"role":"user","content":"Reply with exactly READY and no other text."}],"temperature":0,"max_tokens":256}' \
  http://127.0.0.1:8000/v1/chat/completions
```

The first check must report the exact model ID and a 262,144-token limit. Trim
leading whitespace before comparing the chat response content with `READY`.
Keep `max_tokens` large enough for the model's reasoning: a 64-token test used
its entire budget before emitting final content. A warm smoke test returned
HTTP 200, first token in 80.7 ms, and a complete response in 3.04 seconds. The
earlier retained run measured about 68 generated tokens/second; treat these as
single-run setup evidence, not a benchmark.

The private bridge itself also passed model discovery and chat generation from
a bridge-attached container. Follow NVIDIA's
[local-vLLM network guidance](https://docs.nvidia.com/nemoclaw/latest/user-guide/openclaw/inference/local-inference/set-up-vllm.html)
when wiring a sandbox: use `host.openshell.internal`, never expose port 8000 on
all host interfaces, and do not configure automatic cloud fallback.

Current boundary: the model server and sandbox-side network path are proven,
but the OpenShell gateway is stopped and no NemoClaw/OpenShell sandbox has been
created. Therefore an OpenClaw-to-tool invocation and the network-disabled
end-to-end smoke test remain pending; do not describe the full harness as
complete until those checks pass in issue #10. The pinned runtime also reports
Marlin weight-only FP4 rather than a native FP4 compute path, so retain that
warning with any performance result.

## Offline kit

Inventory an attached drive without exposing credentials:

```bash
./scripts/inventory-offline-kit.sh /path/to/hackathon-hdd ./kit-report
```

This produces a sorted file manifest, SHA-256 checksums, and a storage summary.
Do not place API tokens or credentials on the drive or in generated reports.

The available external drive is an HDD. Treat it as transport and recovery
storage. Copy the selected model checkpoint and latency-sensitive runtime files
to the GB10's internal NVMe before serving when capacity permits, and include
that copy time in the offline rehearsal.

## Repository rules

- One experiment per issue and branch.
- One shared local model endpoint by default.
- Parallelize deterministic search, retrieval, simulation, and validation first.
- No performance or engineering claim without a baseline and captured output.
- No custom kernel before a profiler trace identifies an end-to-end bottleneck.
- No secrets in source, issues, screenshots, command arguments, or the HDD.

## PhysGen setup

Simardeep's branch contributes two setup references:

- [Complete download manifest](PhysGen_Complete_Download_Setup_Manifest.md)
- [Codex setup and installation runbook](PHYSGen_CODEX_SETUP.md)

The runbook contains commands that install packages and pipe remote installers
to a shell. Review upstream URLs and current versions before execution; do not
run the document as an unattended shell script.

## Research

- [Prior winners and GB10 budget](docs/research/winner-patterns-and-gb10-budget.md)
- [Candidate map](docs/research/candidate-map.md)
- [Custom kernel boundary](docs/research/custom-kernels.md)

## Demo fixtures

- [Native PartMode turbofan](examples/turbofan/README.md): editable schema-5 project, compact BOM, backend-neutral graph, MongoDB JSONL, and a verified exploded render.
- [OpenBot-style Blocky rover](examples/openbot-rover/README.md): editable 65 mm and 82 mm wheel variants, bounded agent mutation contract, dependency graph, MongoDB JSONL, and reusable block-system parts.
