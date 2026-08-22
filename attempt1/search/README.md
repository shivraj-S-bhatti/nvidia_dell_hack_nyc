# Attempt 1 Search: battery-tray variants

> The FS-AI CAD-backed successor is documented in
> [`../fsai/README.md`](../fsai/README.md). This S500 fixture remains unchanged
> as a deterministic regression baseline.

This implements GitHub issue #12's fixture-first Search slice. It normalizes one
strict request, enumerates a frozen three-by-three-by-three design space, assigns
stable IDs and baseline lineage, evaluates deterministic proxy metrics, and
persists the run in MongoDB. CAD, Warp, and an LLM are not used for candidate
enumeration, validation, or ranking. A separate optional harness smoke test
uses the local model only to translate natural language into typed reads.

## Agent retrieval surface

`mcp_server.py` exposes the stored experiment as seven read-only MCP tools:

- `get_ontology`
- `search_parts`
- `search_variants`
- `get_dependencies`
- `list_design_runs`
- `get_winner`
- `get_variant_lineage`

The ontology is also available as `ontology://attempt1/battery-tray`, alongside
an agent context resource, both frozen JSON Schemas, and the
`battery_tray_search_context` prompt. The server accepts no raw MongoDB filter
or write operation. `search_parts` alone provides deterministic fuzzy matching
over documented names and aliases; all IDs, dimensions, statuses, and graph
relations are validated typed filters.

The tracked OpenClaw workspace skill at
`openclaw/workspace/skills/attempt1-battery-search/SKILL.md` tells the harness
when to use each tool and preserves the fixture/CAD evidence boundary.

Run the MCP server directly over stdio with:

```bash
ATTEMPT1_MONGO_URI=mongodb://127.0.0.1:27017 \
  .artifacts/attempt1-search/venv/bin/python attempt1/search/mcp_server.py
```

Register it with OpenClaw from the repository root:

```bash
openclaw mcp add attempt1-search \
  --command "$PWD/.artifacts/attempt1-search/venv/bin/python" \
  --arg "$PWD/attempt1/search/mcp_server.py" \
  --cwd "$PWD" \
  --env ATTEMPT1_MONGO_URI=mongodb://127.0.0.1:27017 \
  --include get_ontology,search_parts,search_variants,get_dependencies,list_design_runs,get_winner,get_variant_lineage \
  --parallel

openclaw mcp probe attempt1-search --json
```

Point `agents.defaults.workspace` at `attempt1/search/openclaw/workspace` to
make the tracked Search skill visible. The stdio MCP registration is usable by
the host harness; routing that harness through an OpenShell/NemoClaw sandbox is
a separate infrastructure step and is not claimed by this Search slice.

## Frozen input

```json
{
  "assemblyId": "s500-battery-tray-v1",
  "objective": "maximize_clearance_then_minimize_material",
  "slots": {
    "trayWidthMm": [100, 105, 110],
    "boardThicknessMm": [2.0, 2.5, 3.0],
    "padThicknessMm": [2.0, 2.5, 3.0]
  },
  "constraints": {}
}
```

Input object order and choice order do not affect normalization. Unknown fields,
slots, choices, or constraints are rejected. The Cartesian-product order is
the slot and choice order shown above, producing exactly 27 unique variants.

The first combination is the baseline. The other 26 variants reference its
stable ID through `parentVariantId`.

## Fixture boundary and objective

The worker uses two explicitly synthetic outcome overrides to prove that one
build failure and one evaluation failure remain queryable. All fixture records
set `evidenceSource: fixture`. `partModeRevision` and `artifactPath` remain
explicitly null because CAD is not connected; no generated geometry is claimed.

The primary metric is `clearanceGainProxyMm = trayWidthMm - 100`. The secondary
metric is a material-volume proxy for the rectangular board minus its four
holes plus the rectangular pad. Constant screw material is omitted because it
cannot affect ordering. These are search demonstrations, not engineering or
simulation claims.

The winner is the valid variant with maximum clearance-gain proxy, then minimum
material-volume proxy, then lowest ordinal. A single MongoDB aggregation sorts
the winner and uses `$graphLookup` to recover its baseline ancestry.

## Persistence

The separate `attempt1_search` database contains exactly:

- `design_runs`
- `variants`

Each variant records its run and variant IDs, parent, parameters, nullable CAD
references, metrics, validity, failure stage and reason, fixture timing, and
ordinal.

## Local inventory

- Python 3.12 on Linux ARM64
- PyMongo 4.14.1
- MCP Python SDK 2.0.0
- MongoDB 8 in the loopback-only `attempt1-mongo` container
- no model, CAD kernel, PartMode, or Warp dependency

## Offline replay

After the pinned wheel is installed, this command needs no external network:

```bash
.artifacts/attempt1-search/venv/bin/python attempt1/search/search_worker.py \
  --request attempt1/search/fixtures/search-request.json \
  --outcomes attempt1/search/fixtures/outcomes.json \
  --output-root .artifacts/attempt1-search/output \
  --mongo-uri mongodb://127.0.0.1:27017 \
  --result-json .artifacts/attempt1-search/evidence/replay.json
```

Run fixture and MongoDB tests with:

```bash
TEST_MONGO_URI=mongodb://127.0.0.1:27017 \
  .artifacts/attempt1-search/venv/bin/python -m unittest discover \
  -s attempt1/search/tests -v
```

With local vLLM already running, replay the natural-language harness smoke with:

```bash
VLLM_API_KEY=vllm-local openclaw agent --local \
  --agent main \
  --session-key agent:main:attempt1-search-smoke \
  --model vllm/nvidia/Qwen3.6-35B-A3B-NVFP4 \
  --thinking off \
  --message-file attempt1/search/fixtures/harness-smoke.txt \
  --json
```

## Experiment evidence contract

The five-minute demo shows the normalized request, 27 stable candidates, two
retained fixture failures, the lexicographic winner, and its baseline ancestry.
The counterfactual is manual or LLM-selected candidate generation; the worker
must always return 27 unique candidates without model sampling.

Success is 27/27 unique deterministic IDs in stable order and one database query
recovering baseline -> winner. The 90-minute kill criterion is any duplicate or
unstable ID, any missing failure record, or failure to reconstruct winner
lineage from only the two frozen collections.
