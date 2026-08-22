"""Frozen 2D layout: the primary geometry representation for ExitTwin.

Per issue #15 the demo defaults to a stable 2D graph ("a stable 2D graph beats a
broken splat"). A layout is a set of nodes (seats/exits/aisle junctions) and
undirected edges (walkable segments carrying a clearance width). Positions are in
metres; clearance is in millimetres.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Node:
    id: str
    type: str  # "seat" | "exit" | "junction" | "door"
    x: float
    y: float
    occupants: int = 0
    usable: bool = True  # meaningful for type == "exit"


@dataclass
class Edge:
    a: str
    b: str
    clearance_mm: int
    passable: bool = True
    length_m: float | None = None  # euclidean from node positions when omitted


@dataclass
class Layout:
    zone_id: str
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)

    def node(self, node_id: str) -> Node:
        for n in self.nodes:
            if n.id == node_id:
                return n
        raise KeyError(node_id)

    def edge_length(self, e: Edge) -> float:
        if e.length_m is not None:
            return e.length_m
        a, b = self.node(e.a), self.node(e.b)
        return math.hypot(a.x - b.x, a.y - b.y)


def load_layout(d: dict[str, Any]) -> Layout:
    nodes = [
        Node(
            id=n["id"],
            type=n["type"],
            x=float(n["x"]),
            y=float(n["y"]),
            occupants=int(n.get("occupants", 0)),
            usable=bool(n.get("usable", True)),
        )
        for n in d["nodes"]
    ]
    edges = [
        Edge(
            a=e["a"],
            b=e["b"],
            clearance_mm=int(e["clearance_mm"]),
            passable=bool(e.get("passable", True)),
            length_m=(float(e["length_m"]) if "length_m" in e else None),
        )
        for e in d["edges"]
    ]
    return Layout(zone_id=d.get("zoneId", d.get("zone_id", "")), nodes=nodes, edges=edges)


def geometry_revision(d: dict[str, Any]) -> str:
    """Stable content hash of the raw layout dict.

    This is the ``geometryRevision`` in the contract: freeze it once the scan is
    approved so every scenario run is provably against the same geometry.
    """

    canonical = json.dumps(d, sort_keys=True, separators=(",", ":"))
    return "geo-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
