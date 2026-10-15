# autoauto NeoRacer Demo

The demo loop is:

1. A human asks Lab for a bounded change.
2. OpenRouter normalizes the request and narrates three precompiled OAT candidates.
3. The UI shows one internally consistent NeoRacer artifact pack as the agents advance.
4. Factory replays its saved checks. The current ordering uses saved Lab evaluation;
   Track remains explicitly pending.
5. A human selects a survivor. The backend writes `selection.json` and closes the run.

OpenRouter supplies proposal language only. It cannot change geometry, measurements,
verdicts, ordering, or selection eligibility. The NeoRacer demo replays the saved pack
in `autoauto/run.integrated.json`; the UI labels this boundary.

## Laptop

```bash
AUTOAUTO_RUNNER=neoracer-demo python3 frontend/serve.py --host 127.0.0.1 --port 4414
```

Open `http://127.0.0.1:4414/frontend/`.

Without an OpenRouter key, the same endpoint flow uses a deterministic proposal
fallback. The geometry and metric fixture is unchanged.

## Dell GB10

Set the key in the Dell shell without putting it in Git, chat, command history, or
an issue. Then run:

```bash
export AUTOAUTO_RUNNER=neoracer-demo
export OPENROUTER_MODEL=openai/gpt-4.1-mini
python3 frontend/serve.py --host 0.0.0.0 --port 4414
```

The API contract used by the frontend is:

```text
GET  /api/capabilities
POST /api/runs
GET  /api/runs/<run-id>
POST /api/selections
```

Replace `NeoRacerDemoController` with the live geometry/simulation controller later.
Keep the response schema and persisted human gate unchanged.
