# Prior Winner Patterns and GB10 Budget

## Main finding

Prior public demos did not win by keeping many independent large models active.
They used a small number of reasoning agents around deterministic retrieval,
simulation, perception, anomaly detection, and policy tools.

## Public implementation evidence

### Simbiote, Seattle first place

Public event material describes an iPhone scan producing a simulation, robot
training in a digital twin, human correction through hand tracking, and
natural-language task planning. The named stack included Isaac Sim, Isaac Lab,
PhysX, Nemotron, MediaPipe/WiLoR, cuRobo, NemoClaw, OpenClaw, and OpenShell.

The public evidence supports a planning role surrounded by specialist robotics
and perception libraries. It does not establish separately loaded models for
every stage.

Sources: [event summary](https://se.linkedin.com/in/nate-rundberg),
[public demo](https://www.canva.com/design/DAHQibjOFkI/XGq3BRFiIqWYZCXJRjG40A/watch).

### Nazar, Seattle second place

Nazar used one serial diagnostic loop with a local Qwen model. Collection,
chunking, BM25 retrieval, graph construction, and evidence ranking were tools.
Its documentation says the application was two processes: Ollama plus a
FastAPI Brain. The agent performs at most five retrieval turns and one
concluding turn by default. Searches inside a turn may run concurrently.

Sources: [repository](https://github.com/Dhruv-0-Arora/Nazar),
[README](https://github.com/Dhruv-0-Arora/Nazar/blob/main/README.md),
[specification](https://github.com/Dhruv-0-Arora/Nazar/blob/main/SPEC.md).

### SquidWard, Seattle third place

SquidWard separated a business-agent sandbox from an always-on security agent.
Deterministic rules, rolling baselines, a CPU Isolation Forest, and an offline
PyTorch model produced evidence before the security agent investigated and
recommended a constrained action. Human approval guarded enforcement.

The repository's GB10 spike reports 119.7 GiB and an approximate fan-out ceiling
of four concurrent subagents. The product architecture required two. Names such
as finance-agent and support-agent also appear as synthetic traffic identities,
not separate resident LLM services.

Sources: [repository](https://github.com/ric03uec/squidward),
[deck](https://github.com/ric03uec/squidward/blob/main/deck/slides.md),
[GB10 spike](https://github.com/ric03uec/squidward/blob/main/docs/epics/bht-gb10-spike.md),
[event generator](https://github.com/ric03uec/squidward/blob/main/scripts/generate_dummy_events.py).

## Capacity planning

NVIDIA specifies 128 GB coherent unified memory and 273 GB/s bandwidth for the
GB10 platform. A vLLM recipe lists a 21 GB minimum for
Qwen3.6-35B-A3B-NVFP4 and 42 GB for its FP8 variant.

Sources: [DGX Spark hardware](https://docs.nvidia.com/dgx/dgx-spark/hardware.html),
[Qwen recipe](https://github.com/vllm-project/recipes/blob/main/models/Qwen/Qwen3.6-35B-A3B.yaml).

### Recommended envelope

| Resource | Initial target |
|---|---:|
| Shared LLM endpoints | 1 |
| Logical agent roles | 3 to 5 |
| Simultaneous LLM generations | 1, then measure 2 and 4 |
| Deterministic workers | Parallel within measured CPU and memory limits |
| Large resident model families | 1 |

A logical agent is instructions, context, tools, and state. Several logical
roles can share one loaded model. Unique weights, active KV caches, runtime
workspaces, and concurrent decoding create the meaningful resource cost.

## Design consequence

Use named roles when they clarify permissions or state, not to advertise agent
count. Keep one active reasoning path while CAD, simulation, retrieval, graph
queries, validation, and scoring run as deterministic work.

