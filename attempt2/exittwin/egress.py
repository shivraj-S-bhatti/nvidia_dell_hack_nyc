"""Deterministic egress metrics over the frozen layout graph.

This is the closed loop's "physics decides" half: given a layout plus a scenario
mutation (blocked exits, impassable edges, widened corridors, opened routes) it
returns the OutputContract. No language model is involved.

Metric definitions (all deterministic, all reproducible from the frozen geometry):
  reachableOccupants          occupants with a walkable path to any usable exit
  unservedOccupants           occupants with no such path
  routeRedundancy             min over occupied nodes of the number of
                              edge-disjoint routes to the set of usable exits
                              (each usable exit is one route endpoint; blocking
                              an exit removes an endpoint, so redundancy drops)
  minimumObservedClearanceMm  narrowest corridor on any used nearest-exit route
  maximumRouteLengthM         longest nearest-exit walk among occupied nodes
  relativeCongestionProxy     max over corridors of (occupants routed through it
                              / its width in m). A PROXY, never evacuation time.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

import networkx as nx

from .contracts import OutputContract
from .geometry import Layout

_SINK = "__usable_exit_sink__"


def _ekey(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a <= b else (b, a)


def _build_graph(
    layout: Layout,
    *,
    blocked_exits: frozenset[str],
    impassable_edges: frozenset[tuple[str, str]],
    clearance_overrides: dict[tuple[str, str], int],
    added_edges: Iterable[tuple[str, str, int]],
) -> nx.Graph:
    g = nx.Graph()
    for n in layout.nodes:
        g.add_node(n.id, type=n.type, occupants=n.occupants)
    for e in layout.edges:
        if not e.passable:
            continue
        key = _ekey(e.a, e.b)
        if key in impassable_edges:
            continue
        clearance = clearance_overrides.get(key, e.clearance_mm)
        g.add_edge(e.a, e.b, length=layout.edge_length(e), clearance_mm=clearance)
    for a, b, clearance in added_edges:
        # Opening a route by moving furniture: length from node positions.
        na, nb = layout.node(a), layout.node(b)
        length = ((na.x - nb.x) ** 2 + (na.y - nb.y) ** 2) ** 0.5
        g.add_edge(a, b, length=length, clearance_mm=clearance)
    return g


def compute(
    layout: Layout,
    *,
    blocked_exits: Iterable[str] = (),
    impassable_edges: Iterable[tuple[str, str]] = (),
    clearance_overrides: dict[tuple[str, str], int] | None = None,
    added_edges: Iterable[tuple[str, str, int]] = (),
    assumptions: list[str] | None = None,
    unknowns: list[str] | None = None,
    recommended_next_measurement: str = "",
) -> OutputContract:
    blocked = frozenset(blocked_exits)
    impassable = frozenset(_ekey(a, b) for a, b in impassable_edges)
    overrides = {_ekey(*k): v for k, v in (clearance_overrides or {}).items()}

    g = _build_graph(
        layout,
        blocked_exits=blocked,
        impassable_edges=impassable,
        clearance_overrides=overrides,
        added_edges=added_edges,
    )

    usable_exits = [
        n.id
        for n in layout.nodes
        if n.type == "exit" and n.usable and n.id not in blocked and n.id in g
    ]
    occupied = [(n.id, n.occupants) for n in layout.nodes if n.occupants > 0 and n.id in g]

    # Nearest-exit routing via one multi-source Dijkstra from every usable exit.
    if usable_exits:
        dist, paths = nx.multi_source_dijkstra(g, set(usable_exits), weight="length")
    else:
        dist, paths = {}, {}

    reachable = 0
    unserved = 0
    max_route = 0.0
    used_edges_per_node: dict[str, list[tuple[str, str]]] = {}
    for nid, cnt in occupied:
        if nid in dist:
            reachable += cnt
            route = paths[nid]  # nearest exit -> ... -> nid
            used_edges_per_node[nid] = list(zip(route, route[1:]))
            max_route = max(max_route, dist[nid])
        else:
            unserved += cnt

    # routeRedundancy: edge-disjoint routes from each occupied node to the exit set.
    redundancy: int | None = None
    if usable_exits:
        g_sink = g.copy()
        g_sink.add_node(_SINK)
        for ex in usable_exits:
            g_sink.add_edge(ex, _SINK, length=0.0, clearance_mm=10_000_000)
        for nid, _cnt in occupied:
            if nid not in dist:
                continue
            try:
                k = len(list(nx.edge_disjoint_paths(g_sink, nid, _SINK)))
            except (nx.NetworkXNoPath, nx.NetworkXError):
                k = 0
            redundancy = k if redundancy is None else min(redundancy, k)

    # minimumObservedClearanceMm along used routes.
    min_clearance: int | None = None
    for edges in used_edges_per_node.values():
        for a, b in edges:
            c = int(g[a][b]["clearance_mm"])
            min_clearance = c if min_clearance is None else min(min_clearance, c)

    # relativeCongestionProxy: peak occupants-per-metre-of-width across corridors.
    flow: dict[tuple[str, str], int] = defaultdict(int)
    for nid, cnt in occupied:
        for a, b in used_edges_per_node.get(nid, []):
            flow[_ekey(a, b)] += cnt
    congestion = 0.0
    for (a, b), routed in flow.items():
        width_m = g[a][b]["clearance_mm"] / 1000.0
        if width_m > 0:
            congestion = max(congestion, routed / width_m)

    return OutputContract(
        reachableOccupants=reachable,
        unservedOccupants=unserved,
        routeRedundancy=int(redundancy or 0),
        minimumObservedClearanceMm=int(min_clearance or 0),
        maximumRouteLengthM=round(max_route, 2),
        relativeCongestionProxy=round(congestion, 2),
        assumptions=list(assumptions or []),
        unknowns=list(unknowns or []),
        recommendedNextMeasurement=recommended_next_measurement,
    )
