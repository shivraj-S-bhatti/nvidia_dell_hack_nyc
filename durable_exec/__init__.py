"""durable_exec — a self-contained durable-execution step journal.

A per-step EXECUTION state machine, backed by local MongoDB Community Edition
(no auth, no API keys) or an in-memory backend for tests/offline demos.

It is intentionally NOT an orchestrator and holds NO application logic: the caller
owns the loop and the keys; ranking / validity / winner selection are the caller's.

    from durable_exec import DurableStore

    store = DurableStore()                 # local mongod at mongodb://localhost:27017
    # store = DurableStore.in_memory()     # no server needed

    store.open_run(run_id, request=req)
    hit = store.begin(run_id, key)         # DONE -> record (skip); else claims RUNNING -> None
    if hit:
        use(hit.result)
    else:
        try:    store.complete(run_id, key, result)   # result is opaque
        except Exception as e: store.fail(run_id, key, str(e))
    ctx = store.context(run_id)            # raw records grouped by execution state
"""

from .store import DONE, FAILED, RUNNING, DurableStore, RunContext, StepRecord

__all__ = ["DurableStore", "StepRecord", "RunContext", "RUNNING", "DONE", "FAILED"]
