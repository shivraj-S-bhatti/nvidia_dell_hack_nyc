CLAUDE.md — Dell x NVIDIA "Local AI on Dell Pro Max with GB10" Hackathon
This file gives Claude full context for this project so it can act as a build partner for the rest of the day. Keep this file updated as decisions get locked in — treat it as the single source of truth for the team.

Event Snapshot
Event: Dell x NVIDIA Hackathon — Local AI on Dell Pro Max with GB10

Series: Same rules/stack/hardware run across SF (Jun 14), Seattle (Jul 26), and NYC (Aug 22) — this file is written for the NYC, Aug 22 event, using the official Seattle event page as the reference ruleset since the format is identical across cities.

Format: 40 teams, 40 Dell Pro Max w/ GB10 units, one-day build sprint, doors 9:00 AM → wrap ~9:00 PM.

Team size: 2–4 builders.

Submission: working demo submitted through the BuilderBase portal before the deadline. Top 8 teams selected for a live pitch to judges the same evening.

Prizes: 1st place — a Dell Pro Max with GB10p per team member. 2nd/3rd — a Dell laptop per team member.

The One Hard Rule
Build an always-on business/corporate AI agent that runs entirely locally on the Dell Pro Max with GB10 — no cloud API calls, ever. This is the actual judging criterion, not a style preference. Every design decision should be defensible against "why does this have to be local?"

Required Stack
OpenClaw — the agent framework/personality layer. Configured via SOUL.md / SKILL.md files rather than hand-rolled agent code. This is the interface the agent uses to talk to channels, tools, and the user.

NVIDIA NemoClaw — installs as an OpenClaw plugin. Bundles local model runtime (NIM/Ollama), Nemotron/Qwen-class models, and the inference pipeline. This is what makes inference actually happen on-device.

NVIDIA OpenShell — the sandboxing/security runtime sitting between the agent and the system. Controls what the agent can access, what tools it can call, and where inference is routed. This is also your answer to "how do you make an always-on agent safe to leave running."

Install path on the box: single installer script, express install, model auto-download. Pre-load any large models onto a USB/external drive before arriving — venue WiFi will not handle 40 teams pulling multi-GB models simultaneously.

Hardware Constraints to Design Around
Dell Pro Max with GB10: NVIDIA GB10 Grace Blackwell Superchip, 20-core Arm CPU, Blackwell GB20B GPU (6,144 CUDA cores), 128GB unified LPDDR5x memory, up to 4TB NVMe, runs NVIDIA DGX OS (Ubuntu-based).

Unified memory is the whole point — it's what lets a 30B+ param model run locally at usable speed. Design the agent to actually exploit this, not just call a tiny quantized model.

You develop on your own laptop; the demo must run on the GB10 box, not your laptop.

Bring a power strip — outlets are not 1:1 with attendees.

Chosen Project Direction
Idea: A CAD & code-compliance agent for engineering/construction teams — reads CAD/BIM assemblies (STEP/IGES), checks for clashes/clearance violations and out-of-spec components, flags issues with the offending geometry as evidence, and drafts the corrective note (RFI-style) for a human to approve.

Why this satisfies "why local":

CAD/engineering IP is proprietary — most firms contractually cannot send design files to third-party cloud APIs.

Sensitive compliance data (safety, code violations) often can't leave the device for liability reasons.

Real-world job sites / engineering floors frequently have poor or no connectivity anyway.

Demo asset: Holybro S500 quadcopter frame kit (S500-C1_ASM.step) — official manufacturer STEP assembly, free direct download, no account required. Fallback: GrabCAD "Q450 Quadcopter Frame" for a second, visually distinct assembly if we want to show generalization across designs.

Demo narrative:

Load the S500 STEP assembly into the agent.

Agent flags a motor-mount clearance issue or a swapped battery/component (e.g., from McMaster/Grainger catalog) that pushes the assembly's CG or bounding box out of spec.

Agent drafts a corrective note / RFI-style flag.

Prove locality on stage — disconnect the ethernet cable or show nvidia-smi / local inference logs mid-demo. This single visual moment is worth more than any slide claiming "runs locally."

Keep a human-in-the-loop approval step before any "action" — every past winning project (Guardian AI, RxGuardian, The Sentinel) kept a human decision point rather than fully autonomous action.

Reference: What Won This Series Before
RxGuardian (NYC, Dec 2025, overall champion) — SAM2 + OCR pipeline verifying pills against prescriptions.

Guardian AI (NYC, Dec 2025, Agentic AI winner) — multi-agent system detecting factory-floor safety violations with visual evidence.

Sentio (NYC, Dec 2025, runner-up) — on-device agentic visual RAG over CCTV/body-cam footage.

The Sentinel (SF, Jun 2026, winner) — always-on technician dispatch agent matching field techs to service requests by skill + real-world ETA, fully on-device.

Pattern across all winners: one narrow, high-stakes, real business problem → fully local end-to-end pipeline → human-in-the-loop decision point → visual proof/evidence shown live at demo time, not just a chat transcript.

Team Roles (fill in)
Agent/config owner: owns OpenClaw SOUL.md / SKILL.md, NemoClaw model selection, prompt design.

OpenShell/infra owner: owns sandboxing, tool permissions, local inference pipeline, offline verification.

Domain/data owner: owns CAD parsing (STEP/IGES via FreeCAD or OpenCascade Python APIs), clash/spec-check logic, test assets.

Demo/pitch owner: owns the 3-minute pitch script, live demo run-of-show, and the "proof of locality" moment.

Build Checklist
NemoClaw installed and model loaded from USB (not venue WiFi)

OpenClaw SOUL.md/SKILL.md written for the CAD-compliance persona

OpenShell sandbox configured with explicit, minimal tool permissions

CAD parser working end-to-end on the S500 STEP file

Clash/spec-check logic returns a concrete, demonstrable flag

Corrective-note/RFI draft generation working

Human-approval step visibly present in the flow

Offline proof step rehearsed (disconnect network / show local logs)

Demo rehearsed under 3 minutes

Submission uploaded to BuilderBase before deadline

Working Norms for Claude During the Build
Prioritize a narrow, fully-working vertical slice over broad, half-working scope. Get one clash detected and one corrective note drafted end-to-end before adding features.

Default to local-only solutions for every dependency (no cloud SDKs, no external API keys, no telemetry that phones home).

Prefer FreeCAD's Python API or OpenCascade (pythonocc) for parsing STEP/IGES files offline — do not reach for cloud CAD services.

When in doubt about scope, cut features that don't visibly show up in the 3-minute demo.

Log every agent decision/flag with the geometry or evidence that triggered it — this is what makes the pitch credible.