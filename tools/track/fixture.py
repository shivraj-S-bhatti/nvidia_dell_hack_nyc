"""fixture.py -- the frozen Track test fixture.

Track's whole claim rests on one thing: the baseline and every survivor are
solved on the *same* domain, supports, loads, material, and solver settings. So
the fixture is a single immutable record with a content hash, and every
`TrackResult` carries that hash. `rank()` in evaluate.py refuses to rank results
whose fixture hashes differ, which makes "we accidentally moved the goalposts
between candidates" a loud failure instead of a silent one.

What the fixture models
-----------------------
A 2D linear-elastic plane-stress slab: the `BOTTOM-PLATE-S500` footprint
projected onto its XZ design plane, extruded to the plate thickness. The four
arm-mount bolt patterns are held; a declared in-plane load is introduced at the
central payload pad. Two load cases (+x and +z) are solved and their compliances
summed.

What it does NOT model
----------------------
Out-of-plane bending, the real flight loads of a quadcopter, contact at the bolt
faces, preload, laminate anisotropy of the actual carbon plate, buckling,
fatigue, or failure. Support and load values are **declared demo test-fixture
assumptions**, not sourced flight data (issue #45 requires them to be labelled as
such). Because every displayed claim is baseline-normalised, the absolute load
magnitude cancels out of the ranking -- it sets the scale of the numbers, not
their order.

Grounded, not invented
----------------------
The support locations are not made up. The depgraph pipeline derives 20
fasteners clamping `BOTTOM-PLATE-S500`; this fixture holds the eight of them
that belong to an `ARM-S500_ASM*` sub-assembly, which cluster into exactly four
symmetric arm-to-plate bolted interfaces at (+/-45.07, +/-45.07) mm. Change the
assembly and the fixture follows the geometry.

The remaining twelve fasteners -- landing-gear poles and nylon lock nuts -- are
real and stay in the graph, but they are not the arm load interface and are not
used as supports here. That is a declared modelling choice, not an oversight.
"""
import hashlib
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import domain  # noqa: E402

FIXTURE_VERSION = "track.fixture/1"

# --- frozen numbers -------------------------------------------------------
# Every value here is part of the fixture hash. Changing one invalidates every
# retained result, which is the point.
DEFAULTS = {
    "fixtureId": "s500-bottom-plate-inplane-v1",
    "fixtureVersion": FIXTURE_VERSION,
    "part": "BOTTOM-PLATE-S500",
    "designPlane": "XZ",          # the plate is extruded along model Y
    "nelx": 240,                  # along model x
    "nely": 144,                  # along model z
    "supersample": 2,             # rasteriser samples per cell per axis
    "coverageThreshold": 0.5,
    "thicknessMm": 2.0,           # measured plate extrusion, see mesh bbox y-span
    # Isotropic stand-in for the real quasi-isotropic CF laminate. Declared
    # assumption: this is NOT the plate's certified material card.
    "materialId": "declared-isotropic-cfrp-standin",
    "youngsModulusMPa": 70000.0,
    "poissonRatio": 0.30,
    "penal": 3.0,                 # SIMP exponent; masks are binary so this only
                                  # affects the void floor, not solid elements
    "voidRatio": 1e-9,            # stiffness floor keeps the system non-singular
    # Supports come from the arm-to-plate bolted interface only. The plate also
    # carries landing-gear and nut fasteners; those are not this load interface.
    "supportOccurrencePrefix": "ARM-S500_ASM",
    "supportClusterRadiusMm": 25.0,
    "supportRadiusMm": 6.0,       # nodes within this of a bolt centre are held
    "loadRadiusMm": 12.0,         # payload pad half-size for load introduction
    "loadTotalN": 100.0,          # declared unit-scale load, cancels in ratios
    "loadCases": ("+x", "+z"),
    "solver": "scipy.sparse.linalg.spsolve/SuperLU",
}

# Displayed target for the bounded goal: lighten the plate without paying for it
# in stiffness. Both halves must hold for a candidate to "meet the target".
TARGET = {
    "materialFractionRatioMax": 0.90,   # >=10% lighter than baseline
    "complianceRatioMax": 1.25,         # <=25% less stiff than baseline
}


class FixtureError(RuntimeError):
    pass


class Fixture:
    """Immutable, hashable description of the one test every candidate faces."""

    def __init__(self, params, transform, baseline_coverage, bolts, clusters,
                 fixed_dofs, load_cases, protected, support_pads=None,
                 load_pad=None):
        self.params = dict(params)
        self.transform = dict(transform)
        self.baseline_coverage = baseline_coverage
        self.bolts = bolts
        self.clusters = clusters
        self.fixed_dofs = np.asarray(fixed_dofs, dtype=np.int64)
        self.load_cases = load_cases          # [{'name','dofs','magnitudes'}]
        self.protected = protected            # boolean (nely,nelx) required-solid
        # Material under each interface, used as flood-fill seeds/targets. The
        # centre of a bolt pattern is a clearance hole, so a single "centre cell"
        # is the wrong handle for connectivity.
        self.support_pads = list(support_pads or [])
        self.load_pad = load_pad
        self._hash = None

    # -- geometry helpers --------------------------------------------------
    @property
    def nelx(self):
        return int(self.params["nelx"])

    @property
    def nely(self):
        return int(self.params["nely"])

    @property
    def shape(self):
        return (self.nely, self.nelx)

    @property
    def hx(self):
        return float(self.transform["hx"])

    @property
    def hy(self):
        # grid-y is model z; the rasteriser calls that pitch hz
        return float(self.transform["hz"])

    def loads_for(self, case_name):
        for c in self.load_cases:
            if c["name"] == case_name:
                return list(zip(c["dofs"], c["magnitudes"]))
        raise KeyError(case_name)

    # -- identity ----------------------------------------------------------
    def canonical(self):
        """The exact document that is hashed. Node/DOF lists are included, so a
        one-cell shift in a support pad changes the hash."""
        return {
            "fixtureVersion": FIXTURE_VERSION,
            "params": {k: (list(v) if isinstance(v, tuple) else v)
                       for k, v in sorted(self.params.items())},
            "transform": {k: round(float(v), 9) if isinstance(v, float) else v
                          for k, v in sorted(self.transform.items())},
            "target": dict(sorted(TARGET.items())),
            "fixedDofs": self.fixed_dofs.tolist(),
            "loadCases": [
                {"name": c["name"],
                 "dofs": list(map(int, c["dofs"])),
                 "magnitudes": [round(float(m), 9) for m in c["magnitudes"]]}
                for c in self.load_cases
            ],
            "boltClusters": [
                {"x": round(float(c["x"]), 6), "z": round(float(c["z"]), 6),
                 "n": int(c["n"])} for c in self.clusters
            ],
            "protectedCells": int(self.protected.sum()),
        }

    def hash(self):
        if self._hash is None:
            blob = json.dumps(self.canonical(), sort_keys=True,
                              separators=(",", ":")).encode("utf-8")
            self._hash = "sha256:" + hashlib.sha256(blob).hexdigest()
        return self._hash

    def summary(self):
        return {
            "fixtureId": self.params["fixtureId"],
            "fixtureHash": self.hash(),
            "grid": [self.nely, self.nelx],
            "cellSizeMm": [round(self.hx, 4), round(self.hy, 4)],
            "thicknessMm": self.params["thicknessMm"],
            "materialId": self.params["materialId"],
            "youngsModulusMPa": self.params["youngsModulusMPa"],
            "poissonRatio": self.params["poissonRatio"],
            "loadCases": [c["name"] for c in self.load_cases],
            "loadTotalN": self.params["loadTotalN"],
            "fixedDofCount": int(self.fixed_dofs.size),
            "loadedNodeCount": len(self.load_cases[0]["dofs"]),
            "supportBolts": self.params.get("supportBoltCount"),
            "plateFastenersTotal": self.params.get("plateFastenerCount"),
            "boltClusters": [
                {"x": round(float(c["x"]), 2), "z": round(float(c["z"]), 2),
                 "bolts": int(c["n"])} for c in self.clusters
            ],
            "solver": self.params["solver"],
            "assumptions": (
                "Supports, load magnitude, direction, and material are declared "
                "demo test-fixture assumptions, not sourced flight data."
            ),
        }


def nodes_on_material(mask):
    """A node is backed by material if any of its (up to four) incident elements
    is solid. Pinning or loading an unbacked node drives the load into a
    void-floor element and produces a meaningless compliance, so the fixture
    filters both sets through this."""
    nely, nelx = mask.shape
    solid = mask.astype(bool)
    backed = np.zeros((nely + 1, nelx + 1), dtype=bool)
    backed[:-1, :-1] |= solid
    backed[:-1, 1:] |= solid
    backed[1:, :-1] |= solid
    backed[1:, 1:] |= solid
    return backed.reshape(-1)


def _nodes_within(transform, cx, cz, radius_mm):
    """Grid node ids whose model-space position lies within radius of (cx, cz)."""
    nelx, nely = int(transform["nelx"]), int(transform["nely"])
    x0, z0 = float(transform["x0"]), float(transform["z0"])
    hx, hz = float(transform["hx"]), float(transform["hz"])
    ix = np.arange(nelx + 1)
    iy = np.arange(nely + 1)
    xs = x0 + ix * hx                       # node positions, not cell centres
    zs = z0 + iy * hz
    dx = xs[None, :] - cx
    dz = zs[:, None] - cz
    inside = (dx * dx + dz * dz) <= radius_mm * radius_mm
    iy_i, ix_i = np.nonzero(inside)
    return (iy_i * (nelx + 1) + ix_i).astype(np.int64)


def _cells_within(transform, cx, cz, radius_mm):
    """Element cells whose centre lies within radius of (cx, cz)."""
    nelx, nely = int(transform["nelx"]), int(transform["nely"])
    x0, z0 = float(transform["x0"]), float(transform["z0"])
    hx, hz = float(transform["hx"]), float(transform["hz"])
    xs = x0 + (np.arange(nelx) + 0.5) * hx
    zs = z0 + (np.arange(nely) + 0.5) * hz
    dx = xs[None, :] - cx
    dz = zs[:, None] - cz
    return (dx * dx + dz * dz) <= radius_mm * radius_mm


def build(artifacts_dir=".artifacts/depgraph", step_path="S500-C1_ASM.step",
          overrides=None):
    """Rasterise the real part, derive supports from real bolt positions, and
    freeze the result. Deterministic: same inputs -> same fixture hash."""
    p = dict(DEFAULTS)
    if overrides:
        unknown = set(overrides) - set(p)
        if unknown:
            raise FixtureError("unknown fixture override(s): %s" % sorted(unknown))
        p.update(overrides)

    verts, tris = domain.load_part_triangles(artifacts_dir, p["part"])
    coverage, transform = domain.rasterize_xz(
        verts, tris, p["nelx"], p["nely"], supersample=p["supersample"])
    baseline = domain.occupancy(coverage, p["coverageThreshold"])
    if baseline.sum() == 0:
        raise FixtureError("rasterised baseline is empty -- projection is wrong")

    all_bolts = domain.bolt_positions(step_path, artifacts_dir, p["part"])
    if not all_bolts:
        raise FixtureError("no fasteners derived for %s; cannot ground supports"
                           % p["part"])
    prefix = p["supportOccurrencePrefix"]
    bolts = [b for b in all_bolts if b["occId"].startswith(prefix)]
    if not bolts:
        raise FixtureError(
            "none of the %d fasteners clamping %s belong to a %r sub-assembly; "
            "the fixture is grounded in the assembly structure and will not "
            "substitute an arbitrary bolt set"
            % (len(all_bolts), p["part"], prefix))
    # Bolts inside one arm mount sit ~20 mm apart; separate mounts are ~90 mm
    # apart, so single-linkage separates the patterns without tuning.
    clusters = domain.cluster_positions(bolts, radius=p["supportClusterRadiusMm"])
    if len(clusters) != 4:
        raise FixtureError(
            "expected 4 arm-mount bolt clusters for %s, found %d at %s -- the "
            "fixture is grounded in geometry and will not guess"
            % (p["part"], len(clusters),
               [(round(c["x"], 1), round(c["z"], 1)) for c in clusters]))

    # Supports: hold both DOF at every node inside each arm-mount pad that is
    # actually backed by material. A node in the middle of a bolt clearance hole
    # is inside the pad radius and is not on the plate.
    backed = nodes_on_material(baseline)
    fixed = []
    support_pads = []
    pad_cells = np.zeros((p["nely"], p["nelx"]), dtype=bool)
    cell_pad = max(float(transform["hx"]), float(transform["hz"]))
    for c in clusters:
        nodes = _nodes_within(transform, c["x"], c["z"], p["supportRadiusMm"])
        nodes = nodes[backed[nodes]]
        if nodes.size < 4:
            raise FixtureError(
                "arm mount at (%.1f, %.1f) captured only %d material-backed "
                "nodes at radius %.1f mm -- widen supportRadiusMm or refine the "
                "grid rather than pinning void"
                % (c["x"], c["z"], nodes.size, p["supportRadiusMm"]))
        fixed.extend(np.concatenate([2 * nodes, 2 * nodes + 1]).tolist())
        pad = _cells_within(transform, c["x"], c["z"],
                            p["supportRadiusMm"] + cell_pad)
        support_pads.append(pad)
        pad_cells |= pad
    fixed_dofs = np.array(sorted(set(fixed)), dtype=np.int64)

    # Load: introduced over the central payload pad. The pad centre is the
    # centroid of the four arm mounts, which is the plate's structural centre
    # rather than an arbitrary origin.
    cx = float(np.mean([c["x"] for c in clusters]))
    cz = float(np.mean([c["z"] for c in clusters]))
    pad_nodes = _nodes_within(transform, cx, cz, p["loadRadiusMm"])
    pad_nodes = pad_nodes[backed[pad_nodes]]
    if pad_nodes.size < 4:
        raise FixtureError(
            "payload pad at (%.1f, %.1f) captured only %d material-backed nodes"
            % (cx, cz, pad_nodes.size))
    load_pad = _cells_within(transform, cx, cz, p["loadRadiusMm"])
    pad_cells |= load_pad
    share = float(p["loadTotalN"]) / float(pad_nodes.size)

    load_cases = []
    for name in p["loadCases"]:
        axis = {"+x": 0, "+z": 1}[name]     # grid-y is model z
        load_cases.append({
            "name": name,
            "dofs": (2 * pad_nodes + axis).astype(np.int64).tolist(),
            "magnitudes": [share] * int(pad_nodes.size),
        })
    p["payloadPadMm"] = [round(cx, 4), round(cz, 4)]

    # Required-solid = the material the baseline actually has under the pads.
    # The clearance holes inside a pad are legitimately void; a candidate must
    # not remove the metal around them.
    protected = pad_cells & baseline.astype(bool)
    if not protected.any():
        raise FixtureError("no protected material under the support/load pads")

    p["supportBoltCount"] = len(bolts)
    p["plateFastenerCount"] = len(all_bolts)
    solid = baseline.astype(bool)
    support_pads = [pad & solid for pad in support_pads]
    load_pad = load_pad & solid
    for c, pad in zip(clusters, support_pads):
        if not pad.any():
            raise FixtureError("arm mount at (%.1f, %.1f) has no material under "
                               "its pad" % (c["x"], c["z"]))
    if not load_pad.any():
        raise FixtureError("payload pad has no material under it")

    return Fixture(p, transform, coverage, bolts, clusters, fixed_dofs,
                   load_cases, protected, support_pads, load_pad)


if __name__ == "__main__":
    fx = build()
    print(json.dumps(fx.summary(), indent=2))
    print("\nprotected (required-solid) cells: %d / %d"
          % (int(fx.protected.sum()), fx.protected.size))
    print("baseline material fraction: %.4f"
          % (domain.occupancy(fx.baseline_coverage).mean()))
