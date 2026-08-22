"""Generational / genetic search (PhysGen-style).

The store never knows "generations" exist. The CALLER owns the outer `for gen`
loop, selection, and breeding. Steps are keyed by CONTENT (geometry hash), so an
elite carried into the next generation reuses its cached FEA for free — a cache
hit, zero recompute. `generation`/`parent` ride in opaque `meta`.
"""

from __future__ import annotations

import sys

from _common import fake_score, get_store  # type: ignore

RUN_ID = "physgen:bracket-A:demo"
GENERATIONS = 3
POP = 4


def geometry_hash(gen: int, idx: int, parent: str | None) -> str:
    # Elites (idx 0,1) keep a STABLE hash across generations -> cache hits.
    # Fresh children (idx 2,3) get a hash that varies by generation -> recompute.
    if idx < 2:
        return f"geo-elite-{idx}"
    return f"geo-g{gen}-{idx}"


def main() -> int:
    store, backend = get_store()
    print(f"backend={backend}  run_id={RUN_ID}\n")
    store.open_run(RUN_ID, request={"problem": "bracket-A", "method": "genetic"})

    fresh, hits = 0, 0
    population = [{"gh": geometry_hash(0, i, None), "parent": None, "score": None} for i in range(POP)]

    for gen in range(GENERATIONS):
        print(f"generation {gen}:")
        for indiv in population:
            key = f"physgen:{indiv['gh']}:fea"
            hit = store.begin(RUN_ID, key, meta={"generation": gen, "parent": indiv["parent"]})
            if hit is not None:
                indiv["score"] = hit.result["materialVolumeMm3"]
                hits += 1
                print(f"    {indiv['gh']:14} cached  (gen {gen})")
                continue
            result = fake_score(seed=key)
            store.complete(RUN_ID, key, result)
            indiv["score"] = result["materialVolumeMm3"]
            fresh += 1
            print(f"    {indiv['gh']:14} FEA solve -> {result['materialVolumeMm3']}mm3")

        # caller-owned selection + breeding (application logic, not the framework)
        population.sort(key=lambda x: x["score"])
        elites = population[:2]
        children = [{"gh": geometry_hash(gen + 1, 2 + j, elites[j]["gh"]), "parent": elites[j]["gh"], "score": None}
                    for j in range(2)]
        population = elites + children

    print(f"\nFEA solves run: {fresh}   cache hits (skipped recompute): {hits}")
    print("note: the store had no concept of generations — content keys did the deduping.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
