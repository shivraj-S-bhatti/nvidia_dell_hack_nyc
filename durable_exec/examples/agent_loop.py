"""Agent loop (TaskForge-style): pin the one nondeterministic step.

The LLM step is the only non-reproducible part. Pinning it under a stable key means
it runs exactly ONCE and is then frozen — so replays (including offline) reuse the
same spec and everything downstream is deterministic. That "pinning" is the caller's
choice; the framework's only mechanism is at-most-once + result reuse.
"""

from __future__ import annotations

import hashlib
import sys

from _common import fake_score, get_store  # type: ignore

RUN_ID = "taskforge:inspection-arm:demo"
USER_REQUEST = "inspection arm: reach 550mm through a 140mm opening, carry a 300g camera"


def _h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:8]


def llm_compile(request: str) -> dict:
    """Stand-in for a NONDETERMINISTIC LLM call (real one would vary run to run)."""
    print("    [llm] compiling TaskSpec (nondeterministic — runs once, then pinned)")
    return {"reachMm": 550, "openingMm": 140, "payloadG": 300, "variants": ["short-link", "long-link"]}


def main() -> int:
    store, backend = get_store()
    print(f"backend={backend}  run_id={RUN_ID}\n")
    store.open_run(RUN_ID, request={"userRequest": USER_REQUEST})

    # --- pin the nondeterministic step ---
    spec_key = f"taskforge:{_h(USER_REQUEST)}:taskspec"
    hit = store.begin(RUN_ID, spec_key)
    if hit is not None:
        task_spec = hit.result
        print(f"    [llm] TaskSpec cached -> reused (pinned): {task_spec['variants']}")
    else:
        task_spec = llm_compile(USER_REQUEST)
        store.complete(RUN_ID, spec_key, task_spec)

    # --- deterministic downstream, keyed off the pinned spec ---
    spec_h = _h(str(task_spec))
    scores = {}
    for variant in task_spec["variants"]:
        key = f"taskforge:{spec_h}:{variant}:sim"
        hit = store.begin(RUN_ID, key)
        if hit is not None:
            scores[variant] = hit.result
            print(f"    [sim] {variant:10} cached")
            continue
        result = fake_score(seed=key)   # PyBullet stand-in
        store.complete(RUN_ID, key, result)
        scores[variant] = result
        print(f"    [sim] {variant:10} valid={result['valid']} clr={result['minimumClearanceMm']}mm")

    ctx = store.context(RUN_ID)
    print(f"\nprogress: {ctx.counts}  (1 pinned LLM step + {len(task_spec['variants'])} sims)")
    print("re-run this script: the LLM step is reused from the journal, not recompiled.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
