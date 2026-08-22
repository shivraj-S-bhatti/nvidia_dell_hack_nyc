"""Semantics tests for DurableStore — run against the in-memory backend (no Mongo).

    python durable_exec/tests/test_store.py     # prints OK / raises on failure
    pytest durable_exec/tests/test_store.py      # also works

Includes a guard test that the framework holds no application/domain logic.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from durable_exec import DONE, FAILED, RUNNING, DurableStore  # noqa: E402


def test_begin_claims_then_completes_and_caches():
    s = DurableStore.in_memory()
    s.open_run("r", request={"x": 1})

    assert s.begin("r", "k") is None            # first begin claims RUNNING, returns None
    assert s.get("r", "k").state == RUNNING

    s.complete("r", "k", {"valid": True, "v": 42})
    hit = s.begin("r", "k")                       # second begin returns cached DONE -> skip
    assert hit is not None and hit.is_done
    assert hit.result == {"valid": True, "v": 42}


def test_done_is_opaque_not_domain_valid():
    # A step that ran fine but is domain-"invalid" is still DONE (execution succeeded).
    s = DurableStore.in_memory()
    s.begin("r", "k")
    s.complete("r", "k", {"valid": False})
    rec = s.get("r", "k")
    assert rec.state == DONE                      # execution state
    assert rec.result["valid"] is False           # domain judgment lives in opaque result


def test_fail_is_retryable():
    s = DurableStore.in_memory()
    s.begin("r", "k")
    s.fail("r", "k", "boom")
    assert s.get("r", "k").state == FAILED
    assert s.get("r", "k").error == "boom"

    assert s.begin("r", "k") is None              # FAILED is reclaimable -> claims RUNNING again
    assert s.get("r", "k").state == RUNNING
    assert s.get("r", "k").attempt == 2


def test_resume_skips_done_work():
    # Simulate a crash mid-sweep, then a resume pass over the SAME store (same process
    # == same persistence). Only the not-yet-DONE keys should be recomputed.
    s = DurableStore.in_memory()
    keys = [f"var-{i}" for i in range(10)]

    computed_pass1 = 0
    for k in keys:
        if s.begin("r", k) is None:
            if computed_pass1 == 6:               # "crash" after 6 fresh completions
                break
            s.complete("r", k, {"ok": True})
            computed_pass1 += 1
    assert computed_pass1 == 6
    assert s.context("r").counts["done"] == 6

    computed_pass2 = 0
    for k in keys:                                # re-drive the whole universe
        hit = s.begin("r", k)
        if hit is not None:
            continue                              # cached DONE -> skip
        s.complete("r", k, {"ok": True})
        computed_pass2 += 1
    # 1 key was left RUNNING by the crash (reclaimed) + 3 never begun = 4 recomputed.
    assert computed_pass2 == 4
    assert s.context("r").counts["done"] == 10


def test_context_groups_by_execution_state_only():
    s = DurableStore.in_memory()
    s.begin("r", "a"); s.complete("r", "a", {})
    s.begin("r", "b"); s.fail("r", "b", "err")
    s.begin("r", "c")                             # left RUNNING
    ctx = s.context("r")
    assert ctx.counts == {"done": 1, "running": 1, "failed": 1}
    # No 'valid'/'winner'/'pending' buckets exist — those are caller concerns.
    assert not hasattr(ctx, "valid") and not hasattr(ctx, "winner") and not hasattr(ctx, "pending")


def test_framework_has_no_domain_imports_and_never_reads_result():
    # Boundary guard: store/backends must not import domain modules, and the source
    # must not index into result[...] / meta[...] (i.e. never interpret payloads).
    import re
    from durable_exec import store as store_mod
    from durable_exec import backends as backends_mod

    for mod in (store_mod, backends_mod):
        src = open(mod.__file__).read()
        assert "import warp" not in src and "pybullet" not in src and "torch" not in src
        # the framework stores result/meta but never subscripts into them
        assert not re.search(r"\bresult\[", src), f"{mod.__name__} indexes into result"
        assert not re.search(r"\bmeta\[", src), f"{mod.__name__} indexes into meta"


ALL_TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]


def main() -> int:
    for t in ALL_TESTS:
        t()
        print(f"ok  {t.__name__}")
    print(f"\n{len(ALL_TESTS)} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
