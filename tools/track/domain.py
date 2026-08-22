"""domain.py -- the BOTTOM-PLATE-S500 design domain as a 2D grid, offline.

Turns one part of the tessellated S500 assembly into the two inputs a planar
solver needs: a material-coverage raster on the plate's design plane, and the
world positions of every fastener that clamps it.

Numpy + stdlib only. No OpenCascade, no FreeCAD, no native build, so this runs
unchanged on the ARM64 GB10 alongside tools/depgraph.

AXES. BOTTOM-PLATE-S500 is extruded along Y (measured mesh bbox
min [-95.5, -2, -59] max [100.5, 0.1, 59]), so its design plane is XZ. Throughout
this module the plane axes are called (x, z) and map to the grid as
grid-x <- model x, grid-y <- model z.

KNOWN LIMITS.
  - The rasterized footprint is the UNION of the triangles' XZ projections. That
    equals the true cross-section only for a prismatic extrusion along Y. Measured
    on this part: every vertex lies on exactly three Y planes -- y = -2.0 (1928
    verts), y = 0.0 (3238) and y = +0.1 (1310). The plate body y in [-2, 0] is a
    true 2 mm prismatic extrusion; the +0.1 mm layer is a raised pad region
    confined to x in [-93.5, 99.6], z in [-9.75, 26.75], i.e. strictly inside the
    plate silhouette. So the projection IS the plate cross-section here. On a part
    with draft, bosses or a non-constant section it would over-report material and
    this module would need a Y-slice instead.
  - Coverage is point-sampled on a supersample x supersample lattice per cell, so
    a feature thinner than one sample pitch can be missed entirely. At 240x144
    with supersample=2 the pitch is ~0.41 mm, comfortably under the M2.5/M3
    clearance holes (d >= 2.7 mm) but not under a hairline slot.
  - bolt_positions reports where a fastener's axis frame sits, not the footprint
    of its head. A washer/head bearing area is a separate calculation.
"""
import json, math, os, sys

import numpy as np

# tools/depgraph modules use absolute imports among themselves (derive_edges does
# `from parse_step import ...`), so the package dir has to be importable by name.
_HERE = os.path.dirname(os.path.abspath(__file__))
_DEPGRAPH = os.path.normpath(os.path.join(_HERE, '..', 'depgraph'))
_REPO = os.path.normpath(os.path.join(_HERE, '..', '..'))

DEFAULT_ARTIFACTS = os.path.join(_REPO, '.artifacts', 'depgraph')
DEFAULT_STEP = os.path.join(_REPO, 'S500-C1_ASM.step')
TARGET_PART = 'BOTTOM-PLATE-S500'

# 2*signed-area below which a projected triangle is treated as degenerate. Side
# walls of an extrusion project to a line and land here in bulk (2636 of the
# plate's 5484 triangles); they carry no footprint, so skipping them is both
# correct and where most of the rasterizer's speed comes from.
DEGENERATE_2A = 1e-12
# Edge-function slack, RELATIVE to the triangle's own 2*area, so it means the same
# thing for a 0.2 mm sliver and a 90 mm face. Keeps a sample sitting exactly on a
# shared edge inside both neighbours instead of leaking a one-sample crack.
EDGE_TOL = 1e-9


# ---------------------------------------------------------------------------
# mesh artifacts
# ---------------------------------------------------------------------------

def _mesh_manifest(artifacts_dir):
    with open(os.path.join(artifacts_dir, 'mesh.json'), encoding='utf-8') as fh:
        return json.load(fh)


def load_part_triangles(artifacts_dir, part_name):
    """Read one part's mesh from the depgraph artifacts.

    Returns (verts, tris):
      verts : np.ndarray (N,3) float64, model-space mm
      tris  : np.ndarray (M,3) int32, indices into verts
    Raises KeyError if part_name is not present.

    mesh_vert.bin holds full-precision float32 xyz triples in WORLD space at byte
    offset part['vOff'] for part['vCount'] vertices -- the same convention
    derive_edges.swept_volume_hits reads with struct.unpack_from('<fff', ...).
    numpy reads the identical bytes here because a 5484-triangle part is 6476
    unpack calls otherwise.

    mesh_idx.bin indices are PART-LOCAL, verified two ways: step_to_mesh.mjs
    copies occt's per-mesh index array verbatim per part, and viewer/app.js binds
    each part's slice straight onto that part's own position attribute. Measured
    on BOTTOM-PLATE-S500: index range is [0, 6475] against vCount 6476.
    """
    mesh = _mesh_manifest(artifacts_dir)
    # An occurrence id is the more specific key (a definition can be instanced many
    # times); fall back to definition name and concatenate every instance.
    parts = [p for p in mesh['parts'] if p.get('occ') == part_name]
    if not parts:
        parts = [p for p in mesh['parts'] if p.get('name') == part_name]
    if not parts:
        raise KeyError(f"{part_name!r} not in {os.path.join(artifacts_dir, 'mesh.json')}")

    vpath = os.path.join(artifacts_dir, 'mesh_vert.bin')
    ipath = os.path.join(artifacts_dir, 'mesh_idx.bin')
    vchunks, ichunks, base = [], [], 0
    for p in parts:
        v = np.fromfile(vpath, dtype='<f4', count=p['vCount'] * 3, offset=p['vOff'])
        if v.size != p['vCount'] * 3:
            raise ValueError(f"{vpath}: short read for {part_name} (vOff {p['vOff']})")
        dt = '<u4' if p['i32'] else '<u2'
        n = p['iCount']
        if n % 3:
            raise ValueError(f"{ipath}: iCount {n} for {part_name} is not a triangle list")
        i = np.fromfile(ipath, dtype=dt, count=n, offset=p['iOff'])
        if i.size != n:
            raise ValueError(f"{ipath}: short read for {part_name} (iOff {p['iOff']})")
        vchunks.append(v.reshape(-1, 3).astype(np.float64))
        ichunks.append(i.reshape(-1, 3).astype(np.int64) + base)
        base += p['vCount']

    verts = np.concatenate(vchunks, axis=0)
    tris = np.concatenate(ichunks, axis=0)
    if tris.size and (tris.min() < 0 or tris.max() >= verts.shape[0]):
        raise ValueError(f"{part_name}: index out of range -- indices are not part-local")
    return verts, tris.astype(np.int32)


# ---------------------------------------------------------------------------
# rasterization
# ---------------------------------------------------------------------------

def rasterize_xz(verts, tris, nelx, nely, bounds=None, supersample=2):
    """Project triangles onto the XZ plane and rasterize the material footprint.

    bounds: optional (xmin, zmin, xmax, zmax); defaults to the projected bbox.
    supersample: integer >=1; each cell is tested on a supersample x supersample
      lattice of sample points and the cell's coverage FRACTION is returned.

    Returns (coverage, transform):
      coverage : np.ndarray (nely, nelx) float64 in [0,1]; coverage[ey, ex].
                 ey=0 is the zmin row, ex=0 is the xmin column.
      transform: dict with keys x0, z0, hx, hz, nelx, nely, xmax, zmax
                 where cell (ex,ey) CENTER is (x0+(ex+0.5)*hx, z0+(ey+0.5)*hz)

    The supersample lattice over the whole domain is itself a uniform grid of
    nelx*ss by nely*ss points, so this rasterizes once at sample resolution and
    block-averages down -- no per-cell work at all.

    Each triangle is tested only over the sample sub-block its bbox touches, with
    integer edge-function signs rather than divided barycentrics: a zero-area
    projected triangle is skipped outright, so there is no divide by zero and no
    NaN. Deterministic: fixed triangle order, fixed float64 ops, no reduction over
    an unordered set.
    """
    verts = np.asarray(verts, dtype=np.float64)
    tris = np.asarray(tris, dtype=np.int64)
    nelx, nely, ss = int(nelx), int(nely), int(supersample)
    if nelx < 1 or nely < 1:
        raise ValueError('nelx and nely must be >= 1')
    if ss < 1:
        raise ValueError('supersample must be >= 1')

    P = verts[:, (0, 2)]                      # design-plane coords: model (x, z)
    if bounds is None:
        if P.size == 0:
            raise ValueError('no vertices to rasterize and no explicit bounds')
        x0, z0 = float(P[:, 0].min()), float(P[:, 1].min())
        x1, z1 = float(P[:, 0].max()), float(P[:, 1].max())
    else:
        x0, z0, x1, z1 = (float(b) for b in bounds)
    if not (x1 > x0 and z1 > z0):
        raise ValueError(f'degenerate bounds ({x0}, {z0}) -> ({x1}, {z1})')

    hx, hz = (x1 - x0) / nelx, (z1 - z0) / nely
    sx, sz = hx / ss, hz / ss
    nx, nz = nelx * ss, nely * ss
    xs = x0 + (np.arange(nx, dtype=np.float64) + 0.5) * sx
    zs = z0 + (np.arange(nz, dtype=np.float64) + 0.5) * sz
    hit = np.zeros((nz, nx), dtype=bool)

    A, B, C = P[tris[:, 0]], P[tris[:, 1]], P[tris[:, 2]]
    # 2 * signed area of every projected triangle, computed once up front.
    two_area = ((B[:, 0] - A[:, 0]) * (C[:, 1] - A[:, 1])
                - (C[:, 0] - A[:, 0]) * (B[:, 1] - A[:, 1]))
    lo = np.minimum(np.minimum(A, B), C)
    hi = np.maximum(np.maximum(A, B), C)
    # Sample i covers x = x0 + (i+0.5)*sx, so the first sample at or past `lo` is
    # ceil((lo-x0)/sx - 0.5) and the last at or before `hi` is floor(...)+1 exclusive.
    i0 = np.clip(np.ceil((lo[:, 0] - x0) / sx - 0.5), 0, nx).astype(np.int64)
    i1 = np.clip(np.floor((hi[:, 0] - x0) / sx - 0.5) + 1, 0, nx).astype(np.int64)
    j0 = np.clip(np.ceil((lo[:, 1] - z0) / sz - 0.5), 0, nz).astype(np.int64)
    j1 = np.clip(np.floor((hi[:, 1] - z0) / sz - 0.5) + 1, 0, nz).astype(np.int64)

    for k in range(tris.shape[0]):
        d = two_area[k]
        if abs(d) < DEGENERATE_2A:
            continue
        a0, a1 = i0[k], i1[k]
        b0, b1 = j0[k], j1[k]
        if a1 <= a0 or b1 <= b0:
            continue                          # triangle falls between sample rows/cols
        px = xs[a0:a1][None, :]
        pz = zs[b0:b1][:, None]
        ax, az = A[k]; bx, bz = B[k]; cx, cz = C[k]
        e0 = (bx - px) * (cz - pz) - (cx - px) * (bz - pz)
        e1 = (cx - px) * (az - pz) - (ax - px) * (cz - pz)
        e2 = (ax - px) * (bz - pz) - (bx - px) * (az - pz)
        if d < 0:                             # normalise winding, not by dividing
            e0, e1, e2 = -e0, -e1, -e2
        tol = abs(d) * EDGE_TOL
        m = (e0 >= -tol) & (e1 >= -tol) & (e2 >= -tol)
        if m.any():
            hit[b0:b1, a0:a1] |= m

    coverage = hit.reshape(nely, ss, nelx, ss).mean(axis=(1, 3))
    transform = {'x0': x0, 'z0': z0, 'hx': hx, 'hz': hz,
                 'nelx': nelx, 'nely': nely, 'xmax': x1, 'zmax': z1}
    return coverage, transform


def occupancy(coverage, threshold=0.5):
    """coverage -> np.ndarray (nely,nelx) uint8 binary mask."""
    return (np.asarray(coverage, dtype=np.float64) >= threshold).astype(np.uint8)


def cell_of(transform, x, z):
    """Model-space (x,z) mm -> (ex, ey) integer cell. May return out-of-range values;
    caller clamps."""
    ex = int(math.floor((float(x) - transform['x0']) / transform['hx']))
    ey = int(math.floor((float(z) - transform['z0']) / transform['hz']))
    return ex, ey


def xz_of(transform, ex, ey):
    """(ex,ey) -> model-space (x,z) mm of the cell centre. Inverse of cell_of to
    within half a cell."""
    return (transform['x0'] + (int(ex) + 0.5) * transform['hx'],
            transform['z0'] + (int(ey) + 0.5) * transform['hz'])


# ---------------------------------------------------------------------------
# fasteners
# ---------------------------------------------------------------------------

def bolt_positions(step_path, artifacts_dir, part_name):
    """World-space positions of every fastener occurrence that FASTENS part_name.

    Uses tools/depgraph (parse_step.Step + derive_edges.derive) READ-ONLY: the
    FASTENS predicate stays in one place, so a tolerance change over there moves
    the load points here too instead of silently disagreeing.

    Returns a list of dicts sorted deterministically by (x, z, occId):
      {'occId': str, 'defName': str, 'x': float, 'y': float, 'z': float}

    parse_step.occurrences() ACCUMULATES the placement chain during its tree walk
    (`Tn = mul(T, d.get('T', IDENT))`), so occ['T'] is already the world transform
    and its translation column is the world position -- re-composing parentOcc
    here would double-transform every nested fastener. Verified against the
    independent OCC world-space mesh: for every GB70 screw the tessellated
    centroid lies 0.041 mm or less off the axis line through occ['T'] translation.
    """
    if _DEPGRAPH not in sys.path:
        sys.path.insert(0, _DEPGRAPH)
    from parse_step import Step
    from derive_edges import derive

    st = Step(step_path)
    occ = st.occurrences()
    cyl = st.cylinders_by_definition()
    # Feed the mesh when it is there so the edge set is byte-for-byte what
    # build_graph.py wrote into graph.json; derive() degrades to a no-mesh path
    # (same edges, no grip stacks) when the artifacts are missing.
    mesh_json = os.path.join(artifacts_dir, 'mesh.json')
    vert_bin = os.path.join(artifacts_dir, 'mesh_vert.bin')
    mesh = None
    if os.path.exists(mesh_json) and os.path.exists(vert_bin):
        mesh = _mesh_manifest(artifacts_dir)
    edges, _ = derive(occ, cyl, mesh, vert_bin if mesh else None)

    by_id = {o['occId']: o for o in occ}
    out, seen = [], set()
    for e in edges:
        if e['type'] != 'FASTENS':
            continue
        tgt = by_id.get(e['to'])
        if tgt is None or (tgt['defName'] != part_name and e['to'] != part_name):
            continue
        fid = e['from']
        if fid in seen:                       # one screw can hit two holes in one part
            continue
        seen.add(fid)
        f = by_id[fid]
        t = f['T'][1]
        out.append({'occId': fid, 'defName': f['defName'],
                    'x': float(t[0]), 'y': float(t[1]), 'z': float(t[2])})
    out.sort(key=lambda b: (b['x'], b['z'], b['occId']))
    return out


def cluster_positions(points, radius):
    """Simple deterministic single-linkage clustering of (x,z) points.

    points: list of dicts with 'x','z' (or an (N,2) array).
    Returns list of clusters, each {'x':cx,'z':cz,'n':count,'members':[...]},
    sorted by (cx, cz). Deterministic -- no randomness, no sklearn.

    Union-find over every pair within `radius`; N is a bolt count, so the O(N^2)
    distance matrix is the cheap and obviously-correct choice. Ties cannot change
    the result: single linkage is the transitive closure of one symmetric
    relation, so the partition does not depend on merge order.
    """
    if isinstance(points, np.ndarray) or (points and not isinstance(points[0], dict)):
        arr = np.asarray(points, dtype=np.float64).reshape(-1, 2)
        items = [{'x': float(p[0]), 'z': float(p[1])} for p in arr]
    else:
        items = list(points)
        arr = np.array([[float(p['x']), float(p['z'])] for p in items],
                       dtype=np.float64).reshape(-1, 2)
    n = arr.shape[0]
    if n == 0:
        return []

    parent = list(range(n))
    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    d2 = ((arr[:, None, :] - arr[None, :, :]) ** 2).sum(axis=2)
    near = d2 <= float(radius) ** 2
    for i in range(n):
        for j in range(i + 1, n):
            if near[i, j]:
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[max(ri, rj)] = min(ri, rj)

    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    out = []
    for root in sorted(groups):
        idx = groups[root]
        out.append({'x': float(arr[idx, 0].mean()), 'z': float(arr[idx, 1].mean()),
                    'n': len(idx), 'members': [items[i] for i in idx]})
    out.sort(key=lambda c: (c['x'], c['z']))
    return out


# ---------------------------------------------------------------------------
# self-check / preview
# ---------------------------------------------------------------------------

RAMP = ' .:-=+*#%@'


def ascii_preview(mask, cols=60, rows=None):
    """Block-average `mask` down to a terminal-sized picture, zmax row first.

    Rows default to half the square count so the picture reads square in a
    terminal cell that is about twice as tall as it is wide.
    """
    nely, nelx = mask.shape
    cols = max(1, min(cols, nelx))
    bx = max(1, nelx // cols)
    if rows is None:
        rows = max(1, int(round(nely / (2.0 * bx))))
    bz = max(1, nely // rows)
    cols, rows = nelx // bx, nely // bz
    blk = mask[:rows * bz, :cols * bx].astype(np.float64)
    blk = blk.reshape(rows, bz, cols, bx).mean(axis=(1, 3))
    top = len(RAMP) - 1
    lines = []
    for ey in range(rows - 1, -1, -1):        # print zmax first: a top view
        # Only a 100%-solid block earns the top glyph. Rounding instead would paint
        # a block that is 97% material as solid, which is exactly the case a hole
        # smaller than one preview block produces -- and hiding those would hide
        # the feature this preview exists to show.
        lines.append(''.join(' ' if v <= 0 else
                             (RAMP[top] if v >= 1.0 else RAMP[max(1, int(v * top))])
                             for v in blk[ey]))
    return '\n'.join(lines)


def main():
    import time
    art, step = DEFAULT_ARTIFACTS, DEFAULT_STEP
    nelx, nely = 240, 144

    verts, tris = load_part_triangles(art, TARGET_PART)
    print(f"part          {TARGET_PART}")
    print(f"vertices      {verts.shape[0]}")
    print(f"triangles     {tris.shape[0]}")
    print(f"model bbox    min {np.round(verts.min(axis=0), 3).tolist()}  "
          f"max {np.round(verts.max(axis=0), 3).tolist()}")

    t0 = time.time()
    cov, tf = rasterize_xz(verts, tris, nelx, nely, supersample=2)
    dt = time.time() - t0
    mask = occupancy(cov)
    print(f"projected XZ  x [{tf['x0']:.3f}, {tf['xmax']:.3f}]  "
          f"z [{tf['z0']:.3f}, {tf['zmax']:.3f}]")
    print(f"grid          {nelx} x {nely}   cell {tf['hx']:.4f} x {tf['hz']:.4f} mm")
    print(f"rasterize     {dt*1000:.0f} ms  (supersample=2)")
    print(f"material      {mask.mean():.4f} of the bounding box "
          f"({int(mask.sum())} / {mask.size} cells)")
    print()
    print(ascii_preview(mask, cols=60))
    print()

    bolts = bolt_positions(step, art, TARGET_PART)
    # Cross-frame check: the fastener world positions come from the STEP placement
    # chain, the raster comes from the OCC tessellation. If both are in the same
    # frame every bolt centre must land in a clearance hole, i.e. an EMPTY cell.
    on_hole = sum(1 for b in bolts
                  if 0 <= cell_of(tf, b['x'], b['z'])[0] < nelx
                  and 0 <= cell_of(tf, b['x'], b['z'])[1] < nely
                  and mask[cell_of(tf, b['x'], b['z'])[1], cell_of(tf, b['x'], b['z'])[0]] == 0)
    # 26.5 mm sits inside the [26.3, 27.0) window that separates the four quadrant
    # mount groups: the widest within-group gap is 26.28 mm (the left arm screw at
    # (-38, -52.14) to the landing-gear screw at (-12, -56)) and the narrowest
    # between-group gap is 27.00 mm (x = -12 to x = +15 at z = -31 and z = -56).
    # A narrow window, so it is stated rather than tuned silently.
    radius = 26.5
    clusters = cluster_positions(bolts, radius)
    print(f"fasteners     {len(bolts)} occurrences FASTEN {TARGET_PART}")
    print(f"frame check   {on_hole}/{len(bolts)} bolt centres land in an empty "
          f"(clearance-hole) cell")
    print(f"clusters      {len(clusters)} at single-linkage radius {radius:g} mm")
    for c in clusters:
        ex, ey = cell_of(tf, c['x'], c['z'])
        kinds = sorted({m['defName'] for m in c['members']})
        print(f"  ({c['x']:8.2f}, {c['z']:8.2f}) mm  n={c['n']}  cell=({ex:3d},{ey:3d})  "
              f"{', '.join(kinds)}")
        for m in sorted(c['members'], key=lambda m: (m['x'], m['z'], m['occId'])):
            print(f"        {m['x']:8.2f} {m['y']:7.2f} {m['z']:8.2f}   {m['occId']}")

    # The arm-mount screws on their own separate far more robustly (any radius in
    # [21, 76) mm), because the other 12 fasteners are landing-gear and standoff
    # hardware that sits between the arms rather than at them.
    arms = [b for b in bolts if b['defName'] == 'GB70-M2-5-6-DING']
    ac = cluster_positions(arms, 21.0)
    print(f"arm mounts    {len(ac)} clusters of "
          f"{sorted({c['n'] for c in ac})} from {len(arms)} M2.5 screws (radius 21 mm): "
          + '  '.join(f"({c['x']:.2f}, {c['z']:.2f})" for c in ac))
    return 0


if __name__ == '__main__':
    sys.exit(main())
