"""The three scenarios issue #15 requires, all run against the SAME frozen geometry.

A scenario is just a set of mutations passed to ``egress.compute``:
  baseline              geometry as scanned
  blocked_route         one usable exit becomes unavailable
  rearranged_furniture  widen a used corridor and/or open a route by moving furniture

Each scenario also carries its own honest assumptions/unknowns and the single
next measurement that would most change the recommendation.
"""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import OutputContract
from .egress import compute
from .geometry import Layout


@dataclass
class ScenarioSpec:
    name: str
    blocked_exits: tuple[str, ...] = ()
    impassable_edges: tuple[tuple[str, str], ...] = ()
    clearance_overrides: tuple[tuple[tuple[str, str], int], ...] = ()
    added_edges: tuple[tuple[str, str, int], ...] = ()
    assumptions: tuple[str, ...] = ()
    unknowns: tuple[str, ...] = ()
    recommended_next_measurement: str = ""

    def run(self, layout: Layout) -> OutputContract:
        return compute(
            layout,
            blocked_exits=self.blocked_exits,
            impassable_edges=self.impassable_edges,
            clearance_overrides=dict(self.clearance_overrides),
            added_edges=self.added_edges,
            assumptions=list(self.assumptions),
            unknowns=list(self.unknowns),
            recommended_next_measurement=self.recommended_next_measurement,
        )


def baseline() -> ScenarioSpec:
    return ScenarioSpec(
        name="baseline",
        assumptions=(
            "Occupant counts are a manual observed snapshot, not a live feed.",
            "Corridor widths are the observed minimum clearance, not certified egress width.",
        ),
        unknowns=(
            "Actual door leaf widths and swing direction are unverified.",
            "Real occupant load limit for the zone is unknown pending building plans.",
        ),
        recommended_next_measurement=(
            "Measure the true clear width of the narrowest used corridor with a tape."
        ),
    )


def blocked_route(exit_id: str) -> ScenarioSpec:
    return ScenarioSpec(
        name=f"blocked_route:{exit_id}",
        blocked_exits=(exit_id,),
        assumptions=(
            f"Exit '{exit_id}' is treated as fully unavailable for this scenario.",
        ),
        unknowns=(
            "Whether the surviving exit's capacity can absorb the rerouted occupants.",
        ),
        recommended_next_measurement=(
            "Confirm the surviving exit's rated capacity with Fire and Life Safety."
        ),
    )


def rearranged_furniture(
    widen: dict[tuple[str, str], int],
    open_routes: tuple[tuple[str, str, int], ...] = (),
) -> ScenarioSpec:
    return ScenarioSpec(
        name="rearranged_furniture",
        clearance_overrides=tuple(widen.items()),
        added_edges=open_routes,
        assumptions=(
            "Furniture moves are reversible and do not alter building fabric "
            "(landmark-status friendly).",
        ),
        unknowns=(
            "Whether moved furniture creates a new obstruction elsewhere in the zone.",
        ),
        recommended_next_measurement=(
            "Re-scan the rearranged zone to confirm no new pinch point was introduced."
        ),
    )
