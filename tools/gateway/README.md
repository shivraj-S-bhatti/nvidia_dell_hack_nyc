# gateway — the OpenClaw-to-tool wiring for issue #10 (LOCAL)

Closes the gap README.md's "Verified GB10 model inference and harness boundary"
names: *"the OpenShell gateway is stopped and no NemoClaw/OpenShell sandbox has
been created. Therefore an OpenClaw-to-tool invocation and the network-disabled
end-to-end smoke test remain pending."*

This directory adds no new domain logic. `gateway_tools.py` shells out to (or,
for Track, reads the last stored output of) three already-verified CLIs:

| Tool | Wraps | Computes |
|---|---|---|
| `work_order` | `python3 tools/depgraph/work_order.py <part> [--thicker N] --json` | nothing new — parses that CLI's JSON |
| `factory_verdict` | `python3 tools/factory/validate.py [--candidate <id>] --json` | nothing new — Factory recomputes deterministically, this only parses it |
| `track_result` | reads `.artifacts/track/track-report.json` | nothing — no re-solve, matches `tools/track/render.py`'s own "read the last report" |

`mcp_server.py` exposes those three functions as read-only MCP tools, in the
same shape already proven by `attempt1/search/mcp_server.py`. Every tool
description tells the model the same thing the SKILL.md at
`openclaw/workspace/skills/night-shift-gateway/SKILL.md` tells it: translate
the request into one typed call, then explain the returned JSON in prose.
Never originate a number the tool did not return.

## What is verified right now (from this machine, no GB10 needed)

```bash
python3 tools/gateway/gateway_tools.py work_order BOTTOM-PLATE-S500 --thicker 1.0
python3 tools/gateway/gateway_tools.py factory_verdict --candidate cand-d-standardize-m25
python3 tools/gateway/gateway_tools.py track_result --candidate cand-a-edge-scallops
```

All three ran end-to-end against the real CLIs and real `.artifacts/` on
2026-08-22 and returned real JSON (blast radius, the CLEARANCE veto, and the
`cand-a-edge-scallops` ranking respectively). This proves the wiring, not the
GB10 endpoint or OpenShell enforcement — those still need the box.

## What still needs the actual GB10 (not done from this machine)

This machine has no path to the GB10 (no SSH/Tailscale config, no local
`nvidia-smi`, no local `attempt1-vllm` container) — the following steps must
run on the box itself, by whoever has hands on it.

**1. Confirm the endpoint** (already proven once; re-verify it's still up):

```bash
docker start attempt1-vllm
curl --fail -s http://127.0.0.1:8000/v1/models
```

**2. Register this MCP server with OpenClaw**, following the exact pattern
`attempt1/search/README.md` already proves works:

```bash
openclaw mcp add night-shift-gateway \
  --command "$(which python3)" \
  --arg "$PWD/tools/gateway/mcp_server.py" \
  --cwd "$PWD" \
  --include work_order,factory_verdict,track_result \
  --parallel

openclaw mcp probe night-shift-gateway --json
```

Point `agents.defaults.workspace` at `openclaw/workspace` (repo root) so the
`night-shift-gateway` skill above is visible, the same way
`attempt1/search/README.md` documents for its own skill.

**3. Create the OpenShell sandbox.** No sandbox-creation command syntax is
documented anywhere in this repo yet — the only OpenShell CLI verbs anyone has
recorded here are `openshell --help` and `openshell status`
(`PHYSGen_CODEX_SETUP.md`). Run `openshell --help` on the box first and use its
actual verbs; do not guess flags. Whatever the exact command turns out to be,
it must satisfy what's already true about this endpoint (README.md's verified
boundary table) and what NVIDIA's linked local-vLLM guidance requires:

- model route `http://host.openshell.internal:8000/v1` (already proven reachable
  from a bridge-attached container — see README.md)
- never bind or expose port 8000 on all host interfaces (already true today —
  `ss` showed no wildcard/LAN listener)
- no automatic cloud fallback configured
- tool allowlist limited to exactly `work_order`, `factory_verdict`,
  `track_result` — nothing else

**4. Prove one OpenClaw-to-tool invocation**, mirroring the harness-smoke
pattern `attempt1/search/README.md` already uses:

```bash
VLLM_API_KEY=vllm-local openclaw agent --local \
  --agent main \
  --session-key agent:main:night-shift-gateway-smoke \
  --model vllm/nvidia/Qwen3.6-35B-A3B-NVFP4 \
  --thinking off \
  --message "What else changes if BOTTOM-PLATE-S500 gets 1mm thicker?" \
  --json
```

Confirm the transcript shows one `work_order` tool call with `part:
"BOTTOM-PLATE-S500"` and `thicker_mm: 1`, and that every number in the model's
prose answer (occurrence counts, hop distances, length-action deltas) matches
the tool's returned JSON exactly.

**5. Disable outbound networking on the box and re-run the same invocation.**
Capture what changed (or didn't) and post versions plus a screenshot to issue
#10 — owned by `Simardeep27` per `AGENTS.md`; coordinate before posting so two
people don't duplicate the same evidence.

## Scope discipline this preserves

- No second model endpoint, no refactor of `tools/factory` or `tools/track`,
  no UI, no new dependency beyond the MCP Python SDK already used by
  `attempt1/search`.
- Every number surfaced to a user came from one of the three CLIs above,
  unmodified. If a demo answer ever contains a number that isn't in the
  corresponding tool's JSON, that's a bug in the model's prose, not this
  wiring.
