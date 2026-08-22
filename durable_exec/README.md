# durable_exec — a durable-execution step journal

A tiny, self-contained framework that lets any multi-step pipeline **resume without
redoing work**. It records the outcome of each step so a re-run — after a crash, on stage,
or during frantic iteration — **skips everything already done** and computes only what's left.

Backed by a **local MongoDB Community Edition** (no auth, no API keys, no network) or an
**in-memory backend** for tests and offline demos.

## What it is — and deliberately is NOT

It is a **per-step EXECUTION state machine**. Three states: `RUNNING → DONE`, or `RUNNING →
FAILED` (retryable). That's it.

Two hard boundaries make it reusable across every project:

- **No orchestration.** It never loops, fans out, enumerates, schedules, or resolves
  dependencies. **The caller owns the loop and supplies the keys.** A flat sweep, a genetic
  search, a DAG, and an agent loop all use the *same* store, unchanged.
- **No application logic.** It never ranks, picks winners, or filters by any domain notion of
  "validity". `complete(key, result)` stores `result` as an **opaque blob it never reads**.
  Ranking / validity / winner selection live in *your* code.

> `FAILED` means the step *threw* (execution error). A step that runs fine but produces a
> domain-"invalid" result is `DONE` — the invalidity is just data inside `result`.

If you want the transparent, magic version of this, that's [Temporal](#relationship-to-temporal).
This is the ~250-line variant that drops Temporal's replay engine and server.

## Install

```bash
pip install -r durable_exec/requirements.txt          # just pymongo
```

Local MongoDB Community Edition (one-time, on the GB10 / your machine):

```bash
# macOS
brew tap mongodb/brew && brew install mongodb-community && brew services start mongodb-community
# Ubuntu / ARM64 (GB10): follow MongoDB's ARM64 Community package for your OS release,
# then:  sudo systemctl start mongod
```

No replica set, no auth, no API keys. The only atomicity we need — the `begin` claim — is a
single-document `find_one_and_update`, which is atomic on a plain standalone `mongod`.

## Quickstart

```python
from durable_exec import DurableStore

store = DurableStore()                 # mongodb://localhost:27017  (or .in_memory())
store.open_run("run-1", request={"objective": "..."})

for unit in my_orchestrator():         # YOUR loop — flat / GA / DAG / agent
    key = my_key(unit)                 # YOUR stable key
    hit = store.begin("run-1", key)
    if hit:                            # already DONE
        use(hit.result)                # ← no redo
        continue
    try:
        result = do_expensive_work(unit)          # Warp / FEA / LLM / PyBullet
        store.complete("run-1", key, result)      # result is opaque
    except Exception as e:
        store.fail("run-1", key, str(e))          # durable failure; re-begin to retry

# application logic is yours, reading raw records:
ctx = store.context("run-1")
winner = my_rank([r for r in ctx.done if r.result["valid"]])
```

## API

| Call | Does |
|---|---|
| `open_run(run_id, request=None, meta=None)` | Register a run namespace (opaque `request`/`meta`). |
| `begin(run_id, key, meta=None) -> StepRecord \| None` | `DONE` → return record (caller **skips**); else atomically claim `RUNNING`, return `None` (caller **runs**). |
| `complete(run_id, key, result)` | Close `DONE`. `result` opaque; timing auto-stamped. |
| `fail(run_id, key, error)` | Close `FAILED` (retryable via `begin`). |
| `get(run_id, key) -> StepRecord \| None` | Point lookup. |
| `context(run_id) -> RunContext` | Raw records grouped by execution state: `.done` / `.running` / `.failed` (+ `.counts`). |

`StepRecord`: `run_id, key, state, result, error, meta, attempt, started_at, ended_at, elapsed_ms, is_done`.

There is intentionally **no** `valid`, `winner`, or `pending` on `RunContext` — those are
caller concerns. "Pending" = your universe of work minus what shows up here as `DONE`.

## Data model (2 MongoDB collections)

- **`runs`** — `_id` = your run id; opaque `request`/`meta`; `status`; timestamps.
- **`steps`** — `_id = "<run_id>::<key>"`; `state` (RUNNING/DONE/FAILED — the only field we
  branch on); opaque `result`; `error`; opaque `meta` (put lineage / `parentVariantId` /
  `generation` here); `attempt`; auto `startedAt`/`endedAt`/`elapsedMs`.

Indexes: `_id` (begin/get), `{runId, state}` (context/resume).

## Examples

Run any of these (they prefer local Mongo, and fall back to in-memory with a warning; force
in-memory with `DUREXEC_MEMORY=1`):

```bash
python durable_exec/examples/flat_sweep.py        # PartMode: 27 variants, resume-safe
python durable_exec/examples/generational.py      # PhysGen: genetic search, elites reuse cache
python durable_exec/examples/dag.py               # DAG: caller resolves deps, store journals
python durable_exec/examples/agent_loop.py        # TaskForge: pin the one nondeterministic LLM step
```

**See resume in action** (needs Mongo, to persist across restarts):

```bash
CRASH_AT=15 python durable_exec/examples/flat_sweep.py    # dies after 15 fresh scores
python durable_exec/examples/flat_sweep.py                # resumes: skips 15, finishes the rest
```

Each example shows the framework staying agnostic while the *caller* owns the orchestration
shape and all domain decisions.

## Test

```bash
python durable_exec/tests/test_store.py     # in-memory, no Mongo needed
```

Covers: claim→complete→cache, `DONE` ≠ domain-valid, `FAILED` retry, resume-skips-done, and a
**boundary guard** that the framework imports no domain modules and never reads inside
`result`/`meta`.

## Relationship to Temporal

Temporal does durable execution by **event-sourced replay**: it re-runs your workflow from the
top after a crash, feeding back recorded activity results — reconstructing in-memory state by
re-execution. Powerful, but it forces your code to be deterministic and needs a server + task
queues + workers + a sharded DB.

The difference: Temporal identifies a step by its **position in a deterministic execution**;
we identify it by a **caller-supplied explicit key**. That one swap lets us keep the valuable
parts (persistent journal, at-most-once memoization, per-step state machine) and drop the heavy
parts (replay engine, determinism requirement, server, retry-timer engine). We are *"Temporal
minus replay minus server."* The cost: we don't restore your in-memory locals across a crash —
you re-drive from `context(run_id)`, which is cheap because work is idempotent by key.
