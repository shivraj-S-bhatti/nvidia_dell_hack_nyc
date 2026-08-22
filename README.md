# NVIDIA x Dell NYC Hackathon

Shared preparation and experiment repository for an offline demo on one Dell
GB10. The team may explore several ideas, but evidence converges in one place:
[issue #1](https://github.com/shivraj-S-bhatti/nvidia_dell_hack_nyc/issues/1).

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
   ./scripts/doctor.sh --external-root /path/to/hackathon-ssd \
     | tee gb10-doctor.md
   ```

3. Create a project attempt with the GitHub experiment issue template.
4. Stop at its 90-minute kill criterion and post evidence to the issue.
5. Use [issue #4](https://github.com/shivraj-S-bhatti/nvidia_dell_hack_nyc/issues/4)
   to select one build.

## Active route

- [#2: offline SSD kit](https://github.com/shivraj-S-bhatti/nvidia_dell_hack_nyc/issues/2)
- [#3: common GB10 runtime](https://github.com/shivraj-S-bhatti/nvidia_dell_hack_nyc/issues/3)
- [#4: experiment bake-off](https://github.com/shivraj-S-bhatti/nvidia_dell_hack_nyc/issues/4)

Candidate projects and custom-kernel work remain queued in GitHub. Issues are
the execution record; `docs/research/` holds evidence and constraints.

## Offline kit

Inventory an attached drive without exposing credentials:

```bash
./scripts/inventory-offline-kit.sh /path/to/hackathon-ssd ./kit-report
```

This produces a sorted file manifest, SHA-256 checksums, and a storage summary.
Do not place API tokens or credentials on the drive or in generated reports.

## Repository rules

- One experiment per issue and branch.
- One shared local model endpoint by default.
- Parallelize deterministic search, retrieval, simulation, and validation first.
- No performance or engineering claim without a baseline and captured output.
- No custom kernel before a profiler trace identifies an end-to-end bottleneck.
- No secrets in source, issues, screenshots, command arguments, or the SSD.

## Research

- [Prior winners and GB10 budget](docs/research/winner-patterns-and-gb10-budget.md)
- [Candidate map](docs/research/candidate-map.md)
- [Custom kernel boundary](docs/research/custom-kernels.md)

