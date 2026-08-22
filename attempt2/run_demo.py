#!/usr/bin/env python3
"""Run ExitTwin's closed loop end-to-end, fully offline and GPU-free.

  1. seed NYC building evidence + local observations into the store (with provenance)
  2. freeze geometry (revision hash)
  3. run baseline / blocked-route / rearranged-furniture from the SAME geometry
  4. derive recommendations from the retrieved evidence, and DEMONSTRATE that
     changing an evidence record changes a recommendation (issue #15 acceptance)
  5. persist scenario_runs to the store (JSON by default, MongoDB if configured)

Nothing here calls the language model; every egress number is deterministic.
"""

from __future__ import annotations

import copy
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from exittwin import config, evidence, geometry_revision, load_layout  # noqa: E402
from exittwin.contracts import InputContract  # noqa: E402
from exittwin.scenarios import baseline, blocked_route, rearranged_furniture  # noqa: E402
from exittwin.store import get_store  # noqa: E402

FIXTURE = pathlib.Path(__file__).resolve().parent / "fixtures" / "starrett_floor10_zone1.json"

_METRICS = [
    ("reachableOccupants", "reachable occupants", ""),
    ("unservedOccupants", "unserved occupants", ""),
    ("routeRedundancy", "route redundancy", "routes"),
    ("minimumObservedClearanceMm", "min clearance", "mm"),
    ("maximumRouteLengthM", "max route length", "m"),
    ("relativeCongestionProxy", "congestion proxy", ""),
]


def _print_table(results: dict[str, dict]) -> None:
    names = list(results)
    width = 26
    header = "metric".ljust(width) + "".join(n[:16].rjust(16) for n in names)
    print(header)
    print("-" * len(header))
    for key, label, unit in _METRICS:
        row = label.ljust(width)
        for n in names:
            cell = f"{results[n][key]}{(' ' + unit) if unit else ''}"
            row += cell.rjust(16)
        print(row)


def main() -> int:
    print(f"ExitTwin config: {config.summary()}\n")
    store = get_store()

    # (1) Seed evidence + observations with provenance.
    building_evidence = evidence.seed_building_evidence()
    observations = evidence.seed_observations()
    store.replace("building_evidence", building_evidence)
    store.replace("observations", observations)
    print(f"[store={store.label()}] seeded {len(building_evidence)} evidence + "
          f"{len(observations)} observations")

    # (2) Freeze geometry.
    raw = json.loads(FIXTURE.read_text())
    revision = geometry_revision(raw)
    layout = load_layout(raw)
    total_occ = sum(n.occupants for n in layout.nodes)
    print(f"zone '{layout.zone_id}', geometryRevision {revision}, occupants {total_occ}\n")

    # (3) Three scenarios from the same frozen geometry.
    scenarios = {
        "baseline": baseline(),
        "blocked E2": blocked_route("E2"),
        "rearranged": rearranged_furniture(
            widen={("NJ1", "NJ2"): 1400},
            open_routes=(("NJ2", "SJ2", 1100),),
        ),
    }
    outputs = {name: spec.run(layout) for name, spec in scenarios.items()}
    results = {name: out.to_dict() for name, out in outputs.items()}
    _print_table(results)

    # (4) Evidence-driven recommendation + proof that retrieval changes behavior.
    guidance = evidence.derive_guidance(building_evidence, observations)
    print("\nRecommendation posture:", guidance["recommendation_posture"])
    print("  reason:", guidance["posture_reason"])
    for task in guidance["verification_tasks"]:
        print("  verification task:", task)
    if guidance["procedure_note"]:
        print("  procedure:", guidance["procedure_note"])

    # Counterfactual: drop the landmark record -> the recommendation must change.
    no_landmark = [e for e in building_evidence if e.get("category") != "landmark"]
    guidance_cf = evidence.derive_guidance(no_landmark, observations)
    retrieval_changes_behavior = (
        guidance_cf["recommendation_posture"] != guidance["recommendation_posture"]
    )
    print(f"\n[{'PASS' if retrieval_changes_behavior else 'FAIL'}] "
          f"removing landmark evidence changes the recommendation "
          f"({guidance['recommendation_posture']} -> {guidance_cf['recommendation_posture']})")

    # (5) Persist scenario_runs (raw video never enters the store).
    runs = []
    for name, spec in scenarios.items():
        inp = InputContract(
            building=raw["building"],
            zoneId=layout.zone_id,
            geometryRevision=revision,
            occupancy={"observed": total_occ, "confidence": "manual_count"},
            scenario=spec.name,
        )
        run_doc = {
            "id": f"{revision}:{spec.name}",
            "input": inp.to_dict(),
            "output": results[name],
            "guidance": guidance,
        }
        store.upsert("scenario_runs", run_doc)
        runs.append(run_doc)
    print(f"persisted {len(runs)} scenario_runs to {store.label()}")

    # Acceptance checks from issue #15.
    base, blocked, rearr = results["baseline"], results["blocked E2"], results["rearranged"]
    blocking_hurts = (
        blocked["routeRedundancy"] < base["routeRedundancy"]
        or blocked["unservedOccupants"] > base["unservedOccupants"]
        or blocked["maximumRouteLengthM"] > base["maximumRouteLengthM"]
    )
    improved = rearr["minimumObservedClearanceMm"] > base["minimumObservedClearanceMm"]
    no_regression = (
        rearr["reachableOccupants"] >= base["reachableOccupants"]
        and rearr["routeRedundancy"] >= base["routeRedundancy"]
        and rearr["maximumRouteLengthM"] <= base["maximumRouteLengthM"]
        and rearr["relativeCongestionProxy"] <= base["relativeCongestionProxy"]
    )
    print()
    print(f"[{'PASS' if blocking_hurts else 'FAIL'}] blocking E2 visibly worsens egress")
    print(f"[{'PASS' if improved and no_regression else 'FAIL'}] "
          "furniture move improves a proxy without worsening another")

    ok = blocking_hurts and improved and no_regression and retrieval_changes_behavior
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
