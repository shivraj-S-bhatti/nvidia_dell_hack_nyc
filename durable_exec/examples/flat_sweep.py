"""Flat sweep (PartMode / Attempt 1): score 27 variants, resume-safe.

The framework is agnostic to the fan-out. The CALLER enumerates the 27 variants,
builds keys, and ranks the winner. The store only journals execution.

Demo the resume: run once with a mid-sweep crash, then run again — the second run
skips everything already DONE and finishes the rest.

    # first run crashes after 15 scores (needs Mongo to persist across restarts):
    CRASH_AT=15 python durable_exec/examples/flat_sweep.py
    # second run resumes and completes:
    python durable_exec/examples/flat_sweep.py
"""

from __future__ import annotations

import os
import sys

from _common import fake_score, get_store  # type: ignore

RUN_ID = "partmode:vehicle-module-v1:demo"
SLOTS = {
    "bracketFamily": ["B1", "B2", "B3"],
    "underbody": ["U1", "U2", "U3"],
    "clearance": ["C1", "C2", "C3"],
}


def enumerate_variants():
    """Caller-owned orchestration: the Cartesian 3x3x3 = 27 product."""
    for b in SLOTS["bracketFamily"]:
        for u in SLOTS["underbody"]:
            for c in SLOTS["clearance"]:
                vid = f"{b}-{u}-{c}"
                yield {"id": vid, "params": {"bracketFamily": b, "underbody": u, "clearance": c}}


def main() -> int:
    store, backend = get_store()
    crash_at = int(os.environ.get("CRASH_AT", "0"))
    print(f"backend={backend}  run_id={RUN_ID}  crash_at={crash_at or 'none'}\n")

    store.open_run(RUN_ID, request={"objective": "maximize_clearance_then_minimize_material", "slots": SLOTS})

    computed = 0
    for i, v in enumerate(enumerate_variants()):
        rev = f"rev_{v['id']}"  # a real build step would produce this; keep it simple here
        key = f"partmode:{v['id']}@{rev}:warp_score"

        hit = store.begin(RUN_ID, key, meta={"parentVariantId": "baseline", "params": v["params"]})
        if hit is not None:
            print(f"  [{i:2}] {v['id']:9} cached   -> skip")
            continue

        if crash_at and computed >= crash_at:
            print(f"\n[crash] simulated failure after {computed} fresh scores. Re-run to resume.")
            return 1

        try:
            result = fake_score(seed=key)          # expensive step; result is opaque to the store
            store.complete(RUN_ID, key, result)
            computed += 1
            print(f"  [{i:2}] {v['id']:9} scored   valid={result['valid']} clr={result['minimumClearanceMm']}mm")
        except Exception as exc:                    # pragma: no cover
            store.fail(RUN_ID, key, str(exc))
            print(f"  [{i:2}] {v['id']:9} FAILED   {exc}")

    # ---- application logic lives HERE, in the caller, reading raw records ----
    ctx = store.context(RUN_ID)
    valid = [r for r in ctx.done if r.result["valid"]]
    winner = min(valid, key=lambda r: r.result["materialVolumeMm3"]) if valid else None
    print(f"\nprogress: {ctx.counts}")
    if winner:
        print(f"winner:   {winner.key.split(':')[1]}  "
              f"material={winner.result['materialVolumeMm3']}mm3  clearance={winner.result['minimumClearanceMm']}mm")
    return 0


if __name__ == "__main__":
    sys.exit(main())
