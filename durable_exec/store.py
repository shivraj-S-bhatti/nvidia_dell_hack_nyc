"""Durable-execution state machine — a per-step EXECUTION journal.

Scope boundary (enforced by convention, checked in tests):

  * NO orchestration. This module never loops, fans out, enumerates, schedules,
    resolves dependencies, or decides flat-vs-generational. The caller drives.
    Keys are supplied by the caller.

  * NO application/domain logic. It never ranks, selects winners, filters by any
    domain notion of "validity", or renders evidence. It tracks only the EXECUTION
    lifecycle (RUNNING / DONE / FAILED) and stores an OPAQUE `result` blob it never
    reads.

The caller uses three verbs:

    ask     begin(run_id, key)   -> record if DONE (skip) else claims RUNNING (run it)
    record  complete / fail
    expose  context(run_id)      -> raw records grouped by execution state

`FAILED` means the step *threw* (execution error) and is retryable via begin().
A step that ran fine but produced a domain-"invalid" result is DONE — that
invalidity is just data inside `result`, which this module never inspects.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

# ── execution states (the only thing this module branches on) ────────────────
RUNNING = "RUNNING"
DONE = "DONE"
FAILED = "FAILED"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_ms() -> float:
    return time.time() * 1000.0


@dataclass
class StepRecord:
    """A read view over one step doc. `result`/`meta` are opaque caller payloads."""

    run_id: str
    key: str
    state: str
    result: Any = None
    error: Optional[str] = None
    meta: dict = field(default_factory=dict)
    attempt: int = 0
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    elapsed_ms: Optional[float] = None

    @property
    def is_done(self) -> bool:
        return self.state == DONE

    @classmethod
    def _from_doc(cls, doc: dict) -> "StepRecord":
        return cls(
            run_id=doc["runId"],
            key=doc["key"],
            state=doc["state"],
            result=doc.get("result"),
            error=doc.get("error"),
            meta=doc.get("meta") or {},
            attempt=doc.get("attempt", 0),
            started_at=doc.get("startedAt"),
            ended_at=doc.get("endedAt"),
            elapsed_ms=doc.get("elapsedMs"),
        )


@dataclass
class RunContext:
    """Raw records grouped by EXECUTION state only — no domain interpretation.

    There is deliberately no `valid`, `winner`, or `pending` bucket: those are
    application/orchestration concerns the caller derives itself. "pending" = the
    caller's universe of work minus what shows up here as DONE.
    """

    run_id: str
    done: list = field(default_factory=list)
    running: list = field(default_factory=list)
    failed: list = field(default_factory=list)

    @property
    def counts(self) -> dict:
        return {"done": len(self.done), "running": len(self.running), "failed": len(self.failed)}


class DurableStore:
    """The framework. Holds a backend; contains only execution-lifecycle logic.

    Default backend is a local standalone MongoDB (Community Edition, no auth, no
    API keys). Use `DurableStore.in_memory()` for tests/offline demos with no server.
    """

    def __init__(self, backend=None, *, uri: str = "mongodb://localhost:27017", db: str = "durable_exec"):
        if backend is None:
            from .backends import MongoBackend  # imported lazily so pymongo isn't needed for in-memory use

            backend = MongoBackend(uri=uri, db=db)
        self._backend = backend

    @classmethod
    def in_memory(cls) -> "DurableStore":
        from .backends import MemoryBackend

        return cls(backend=MemoryBackend())

    def ping(self) -> bool:
        return self._backend.ping()

    # ── ask ──────────────────────────────────────────────────────────────────
    def begin(self, run_id: str, key: str, meta: Optional[dict] = None) -> Optional[StepRecord]:
        """Return the record if `key` already completed (caller SKIPS the work),
        otherwise atomically claim it RUNNING and return None (caller RUNS it).

        A FAILED or stale-RUNNING step is reclaimable (returns None -> recompute);
        recomputation is safe because work is idempotent by key.
        """
        step_id = self._step_id(run_id, key)
        existing = self._backend.read_step(step_id)
        if existing is not None and existing["state"] == DONE:
            return StepRecord._from_doc(existing)
        self._backend.claim_step(step_id, run_id, key, meta or {}, _now_iso(), _now_ms())
        return None

    # ── record ─────────────────────────────────────────────────────────────────
    def complete(self, run_id: str, key: str, result: Any) -> None:
        """Close a step as DONE. `result` is stored verbatim and never inspected."""
        self._close(run_id, key, state=DONE, result=result, error=None)

    def fail(self, run_id: str, key: str, error: Any) -> None:
        """Close a step as FAILED (execution error). Re-begin() to retry."""
        self._close(run_id, key, state=FAILED, result=None, error=str(error))

    # ── expose ───────────────────────────────────────────────────────────────
    def get(self, run_id: str, key: str) -> Optional[StepRecord]:
        doc = self._backend.read_step(self._step_id(run_id, key))
        return StepRecord._from_doc(doc) if doc else None

    def context(self, run_id: str) -> RunContext:
        ctx = RunContext(run_id=run_id)
        for doc in self._backend.list_steps(run_id):
            rec = StepRecord._from_doc(doc)
            {DONE: ctx.done, RUNNING: ctx.running, FAILED: ctx.failed}[rec.state].append(rec)
        return ctx

    def open_run(self, run_id: str, request: Any = None, meta: Optional[dict] = None) -> None:
        """Register a run namespace. `request`/`meta` are opaque, stored for replay/audit."""
        self._backend.upsert_run(run_id, request, meta or {}, _now_iso())

    # ── internals ────────────────────────────────────────────────────────────
    @staticmethod
    def _step_id(run_id: str, key: str) -> str:
        return f"{run_id}::{key}"

    def _close(self, run_id: str, key: str, *, state: str, result: Any, error: Optional[str]) -> None:
        step_id = self._step_id(run_id, key)
        doc = self._backend.read_step(step_id)
        started_ms = doc.get("startedMs") if doc else None
        ended_ms = _now_ms()
        elapsed = (ended_ms - started_ms) if started_ms is not None else None
        self._backend.write_step(
            step_id,
            {"state": state, "result": result, "error": error, "endedAt": _now_iso(), "elapsedMs": elapsed},
        )
