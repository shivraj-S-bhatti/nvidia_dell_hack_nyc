# Candidate Map

This document preserves the current technical options and claim boundaries.
GitHub issues own experiments, decisions, and next actions.

## TaskForge

Compile a physical task into a strict specification, choose a validated robot
family, generate bounded morphology variants, simulate them, rank measured
outcomes, and present the winning assembly.

The proposed first task is an inspection arm that reaches 550 mm through a
140 mm opening while carrying a 300 g camera. These are proposed constraints,
not achieved results.

Useful components:

- [PyBullet](https://github.com/bulletphysics/bullet3) for URDF, IK, collision,
  and task simulation
- [text-to-cad](https://github.com/earthtojake/text-to-cad) for CAD and robot
  artifact formats
- [gesture-lab](https://github.com/quiet-node/gesture-lab) for an optional local
  MediaPipe and Three.js presentation layer

## PhysGen

Translate requirements into a bounded structural problem, generate a baseline
and alternatives, then validate every candidate through the same finite-element
path. The credible output is a comparison of material, compliance, and
constraint status.

[OptimizeAnyTopology](https://github.com/ahnobari/OptimizeAnyTopology) is an
optional generator. Its repository license and ARM64 sparse-solver dependencies
must be verified before it enters the critical path. Generated geometry never
counts as improved without independent revalidation.

## VibeCAD

Use text-to-CAD and an exploded assembly viewer as a visual interface for a
measured task. Hand gestures are presentation polish after local asset loading
and stable mouse or touch controls work.

The viewer by itself is not a closed loop. Bind selected parts to constraints,
failures, scores, evidence, or a simulation result.

## Graph-grounded reasoning

Represent claims, evidence, actions, outcomes, and contradictions as typed
nodes. Retrieval returns the smallest evidence subgraph needed for a decision.
Causal or stochastic edges must affect an observable next action or remain an
internal orchestration technique.

This direction best matches the team's graph, search, retrieval, and agentic
orchestration strengths. Its risk is demo legibility, so the graph must change a
visible project decision within the bounded experiment.

## HydroGym boundary

[HydroGym](https://github.com/dynamicslab/hydrogym) is a substantial fluid-flow
control platform. Its published wing result cannot support a claim that an
F-150 body redesign improves vehicle range by 15 percent. Any use in the demo
needs a locally reproduced metric or must be labeled as visual inspiration.

Source: [Nature paper](https://www.nature.com/articles/s41586-026-10917-6).

## Selection

Use [issue #4](https://github.com/shivraj-S-bhatti/nvidia_dell_hack_nyc/issues/4)
for the scorecard. The recommended initial route is TaskForge, with PhysGen as
the deterministic fallback and VibeCAD as a reusable presentation layer.

