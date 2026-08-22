"""DAG orchestration.

The CALLER topologically orders the nodes and resolves dependencies (pulling
upstream results via store.get). The store just journals each node's execution.
Dependency resolution is orchestration — not the framework's job.
"""

from __future__ import annotations

import hashlib
import json
import sys

from _common import get_store  # type: ignore

RUN_ID = "dag:pipeline:demo"

# node -> (deps, compute). compute receives upstream results, returns an opaque result.
DAG = {
    "extract":  ([],                    lambda up: {"n": 27}),
    "baseline": (["extract"],           lambda up: {"volume": 100000}),
    "score":    (["extract"],           lambda up: {"variants_scored": up["extract"]["n"]}),
    "rank":     (["baseline", "score"], lambda up: {"winner": "B2-U1-C3", "vs_baseline_pct": -22}),
}


def topo_order(dag):
    seen, order = set(), []

    def visit(name):
        if name in seen:
            return
        for dep in dag[name][0]:
            visit(dep)
        seen.add(name)
        order.append(name)

    for n in dag:
        visit(n)
    return order


def key_for(node: str, inputs: dict) -> str:
    h = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()[:8]
    return f"dag:{node}:{h}"


def main() -> int:
    store, backend = get_store()
    print(f"backend={backend}  run_id={RUN_ID}\n")
    store.open_run(RUN_ID, request={"pipeline": list(DAG)})

    results: dict = {}
    key_of: dict = {}
    for node in topo_order(DAG):
        deps, compute = DAG[node]
        inputs = {d: results[d] for d in deps}           # caller resolves dependencies
        key = key_for(node, inputs)
        key_of[node] = key

        hit = store.begin(RUN_ID, key, meta={"deps": deps})
        if hit is not None:
            results[node] = hit.result
            print(f"  {node:9} cached")
            continue
        out = compute(inputs)
        store.complete(RUN_ID, key, out)
        results[node] = out
        print(f"  {node:9} ran -> {out}")

    print(f"\nfinal: {results['rank']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
