# Agent Instructions

This is a multi-session hackathon repository. GitHub issues are execution truth.

## Route

1. Read issue #1 before starting work.
2. Work only from an assigned or explicitly claimed issue.
3. Keep no more than three child issues active under the epic.
4. Record new project ideas as separate queued experiment issues.
5. Put code review in pull requests and measurements in the owning issue.

Do not create local TODO or roadmap documents. Research notes may preserve
evidence, constraints, and source links, but may not create a parallel backlog.

## Experiment contract

Every project attempt needs:

- a five-minute demo moment
- a strict input and output contract
- a local dependency and model inventory
- a baseline or counterfactual
- one measurable success metric
- a 90-minute kill criterion
- an offline replay command
- captured latency, memory, and failure evidence when applicable

## System boundaries

- All inference and demo-critical tools run locally on the GB10.
- NemoClaw, OpenClaw, and OpenShell are required shared infrastructure.
- Share one model endpoint unless measurements justify additional residency.
- Prefer deterministic code for CAD, simulation, graph operations, retrieval,
  constraints, validation, and scoring.
- Treat language-model output as a proposal until deterministic checks accept it.
- Custom Triton or CUDA kernels require the entry evidence in issue #9.

## Hygiene

- Never commit models, container archives, generated traces, credentials, or
  venue-specific machine state.
- Never place secrets in issues, screenshots, source files, or command arguments.
- Keep large local artifacts under `.artifacts/`, which is gitignored.
- Preserve source links for externally derived claims.
- Do not claim a measured improvement without retaining the baseline output.

