"""Strict input/output contracts for ExitTwin, matching issue #15 verbatim.

Keeping these as dataclasses (stdlib only) rather than pydantic keeps the arm64
install footprint to a single dependency and makes the JSON boundary explicit.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class InputContract:
    """The request the deterministic core answers.

    Mirrors the ``Input`` block in issue #15. ``building`` carries the public-data
    join keys (BBL/BIN/floor); ``geometryRevision`` pins the frozen layout the
    scenario runs against so results are reproducible.
    """

    building: dict[str, Any]
    zoneId: str
    geometryRevision: str
    occupancy: dict[str, Any]
    exits: list[str] = field(default_factory=list)
    obstacles: list[str] = field(default_factory=list)
    scenario: str = "baseline"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "InputContract":
        return cls(
            building=d["building"],
            zoneId=d["zoneId"],
            geometryRevision=d.get("geometryRevision", ""),
            occupancy=d.get("occupancy", {}),
            exits=list(d.get("exits", [])),
            obstacles=list(d.get("obstacles", [])),
            scenario=d.get("scenario", "baseline"),
        )


@dataclass
class OutputContract:
    """The measured egress triage result for one scenario.

    Every numeric field is computed by a deterministic graph/geometry check —
    never asserted by the language model. ``assumptions``/``unknowns`` and
    ``recommendedNextMeasurement`` are what keep the UI honest per issue #15's
    acceptance ("label observations, assumptions, conflicts, and unknowns").
    """

    reachableOccupants: int
    unservedOccupants: int
    routeRedundancy: int
    minimumObservedClearanceMm: int
    maximumRouteLengthM: float
    relativeCongestionProxy: float
    assumptions: list[str] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    recommendedNextMeasurement: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
