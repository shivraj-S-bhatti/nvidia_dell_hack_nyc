# Custom Kernel Boundary

## Can we write one?

Yes. The Dell GB10 supports custom CUDA C++ and Triton kernels. NVIDIA publishes
a kernel-development playbook for Blackwell systems, and the GB10 is an ARM64
host with compute capability 12.1. Verify the actual event machine with:

```bash
nvidia-smi --query-gpu=name,compute_cap --format=csv,noheader
nvcc --version
python3 -c 'import torch, triton; print(torch.__version__, torch.version.cuda, triton.__version__)'
```

Sources:

- [NVIDIA custom-kernel playbook](https://github.com/NVIDIA/dgx-spark-playbooks/tree/main/nvidia/station-kernel-dev-ft)
- [NCCL GB10 build target](https://github.com/NVIDIA/dgx-spark-playbooks/tree/main/nvidia/nccl)
- [CUDA compute capability guide](https://docs.nvidia.com/cuda/cuda-programming-guide/05-appendices/compute-capabilities.html)
- [DGX Spark hardware](https://docs.nvidia.com/dgx/dgx-spark/hardware.html)

## When it helps

A hackathon kernel is worthwhile when a profile shows a repeated operation that
is launch-bound, memory-traffic-bound, or materializes avoidable intermediate
tensors. Plausible examples for these projects include:

- fused score normalization or segmented reduction over candidate graphs
- fused gather, score, and top-k for graph-grounded retrieval
- fused constraint penalties over batches of topology or robot candidates
- a known fused activation path only when model inference dominates the demo

## Entry gate

Do not implement a kernel until there is:

1. a selected project
2. a correct stock implementation
3. a profiler trace identifying the bottleneck
4. an end-to-end metric the kernel could materially improve

The benchmark must include correctness, warmup, at least 100 timed iterations,
p50 and p95 latency, peak memory, and end-to-end impact. Keep the stock fallback.

Triton is the preferred first attempt because it JIT-compiles from Python.
CUDA/CUTLASS is justified when Triton cannot express the needed Blackwell
primitive or data layout. Issue #9 is the execution record for this work.
