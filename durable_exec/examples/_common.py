"""Shared helpers for the examples: backend selection + fake deterministic "work".

None of this is part of the framework — it stands in for the real expensive steps
(Warp scoring, FEA, LLM, PyBullet) so the examples run anywhere with no GPU/models.
"""

from __future__ import annotations

import hashlib
import os
import sys
import time

# Make `durable_exec` importable when a script is run directly (python path/to/example.py).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from durable_exec import DurableStore  # noqa: E402


def get_store():
    """Prefer local Mongo (the real target); fall back to in-memory with a warning.

    Set DUREXEC_MEMORY=1 to force in-memory (no cross-process resume).
    """
    if os.environ.get("DUREXEC_MEMORY") == "1":
        return DurableStore.in_memory(), "memory"
    try:
        store = DurableStore()  # mongodb://localhost:27017, no auth
        store.ping()
        return store, "mongo"
    except Exception as exc:  # pragma: no cover - depends on local env
        print(f"[warn] local Mongo not reachable ({exc.__class__.__name__}); "
              f"using in-memory backend — cross-process resume won't persist.\n")
        return DurableStore.in_memory(), "memory"


def _hash_ints(seed: str, n: int = 3) -> list[int]:
    digest = hashlib.sha256(seed.encode()).digest()
    return [digest[i] for i in range(n)]


def fake_score(seed: str, work_ms: int = 40) -> dict:
    """Deterministic stand-in for an expensive validation (same seed -> same result)."""
    time.sleep(work_ms / 1000.0)  # simulate GPU/solver time
    a, b, c = _hash_ints(seed)
    collisions = a % 3 == 0  # ~1/3 "invalid" to show that DONE != domain-valid
    return {
        "valid": not collisions,
        "collisionCount": 0 if not collisions else 1 + (a % 3),
        "minimumClearanceMm": round(5 + b / 10, 1),
        "materialVolumeMm3": 80000 + c * 100,
        "device": "cpu",  # would be "cuda:0" under real Warp
    }
