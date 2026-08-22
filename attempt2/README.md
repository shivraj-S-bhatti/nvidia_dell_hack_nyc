# Attempt 2 — ExitTwin (issue #15)

Self-contained folder for Attempt 2. Privacy-preserving **egress-risk triage
twin**: a frozen 2D layout becomes a route graph; deterministic egress metrics
are computed for three scenarios (baseline, one exit blocked, furniture
rearranged) against the **same** geometry, backed by real NYC records with
provenance. The language model only parses intent and explains results — **it
never produces the egress numbers.** ("The model proposes; physics decides.")

Not a fire alarm, evacuation director, or code-compliance check. See issue #15
for the full guardrails.

## Pull-and-run on the GB10

Everything Attempt 2 needs is in this folder; the only hard dependency is
`networkx`. From a fresh checkout:

```bash
git pull                                   # get this branch on the box
cd attempt2
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                        # then edit .env for your environment
python run_demo.py                          # deterministic loop, no GPU, no network
```

`run_demo.py` seeds the NYC evidence + observations, freezes the geometry, runs
the three scenarios, proves issue #15's acceptance (blocking a route worsens
egress; a furniture move improves a proxy without regression; changing retrieved
evidence changes a recommendation), and persists `scenario_runs`.

## Switching to the harness sandbox (one file)

All environment config lives in **`.env`** (loaded by `exittwin/config.py`).
Moving from the host to the OpenShell sandbox is a single edit:

```ini
# host (default)
EXITTWIN_LLM_BASE_URL=http://127.0.0.1:8000/v1
# OpenShell harness sandbox — container must join the `openshell-docker` network
EXITTWIN_LLM_BASE_URL=http://host.openshell.internal:8000/v1
```

Compatibility contract (from the repo README's verified GB10 setup): served model
`nvidia/Qwen3.6-35B-A3B-NVFP4` (262k ctx), `--max-num-seqs 4` so keep concurrent
calls ≤ 4, **no cloud fallback ever**. Storage defaults to a zero-dep JSON store;
set `EXITTWIN_MONGODB_URI` to use the real MongoDB collections. Verify inference:

```bash
docker start attempt1-vllm        # start the shared model server
python check_endpoint.py          # /models + a READY smoke test
```

## Module map

| File | Role |
|---|---|
| `exittwin/config.py` | all env config; the one file to edit per environment |
| `exittwin/contracts.py` | strict input/output contracts (issue #15 JSON) |
| `exittwin/geometry.py` | frozen 2D layout + `geometryRevision` hash |
| `exittwin/egress.py` | deterministic metrics over the layout graph |
| `exittwin/scenarios.py` | baseline / blocked-route / rearranged-furniture |
| `exittwin/evidence.py` | seeded NYC records + observations + retrieval→recommendation rules |
| `exittwin/nyc_data.py` | live Socrata fetch + offline cache (refresh) |
| `exittwin/store.py` | `building_evidence`/`observations`/`scenario_runs` (JSON or MongoDB) |
| `exittwin/model_client.py` | OpenAI-compatible client for the GB10 endpoint |
| `fixtures/` | proxy layout for development (not the real floor plan) |

## Status / next

- [x] Phase 1 — deterministic egress backbone + 3 scenarios
- [x] Phase 2 — store (JSON/Mongo), seeded NYC evidence + observations with
      provenance, retrieval-changes-behavior rule
- [ ] Phase 3 — optional Warp geometry check on GB10 (fallback: Shapely/Python)
- [ ] Phase 4 — LLM intent parse → InputContract; plain-language explanation (uses the endpoint)
- [ ] Phase 5 — UI, offline (network-disabled) replay proof, evidence bundle
