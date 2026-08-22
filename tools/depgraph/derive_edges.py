"""derive_edges.py -- derive typed dependency edges from geometry.

No language model touches this file. Every edge is a geometric predicate with a
numeric tolerance and a reason string carrying the values that produced it, so any
edge can be refuted by hand.

FASTENS       a fastener shank collinear with a clearance hole on another part
CLAMPS        the ordered stack a fastener actually clamps, with grip length
INSTANCE_OF   occurrences sharing one part definition (a spec change hits all)
CONTAINS      the assembly tree, straight from NEXT_ASSEMBLY_USAGE_OCCURRENCE
"""
import math, json, struct, collections
from parse_step import apply_point, apply_dir, unit

# ---------------------------------------------------------------------------
# ISO 4762 socket head cap screw table. Head diameter dk is the classification key:
# it is the one dimension that separates threads unambiguously and survives any
# naming convention. M2.5 and M3 rows verified against the published standard
# (dk 4.32-4.50 and 5.32-5.50); the measured values in S500-C1_ASM.step land at
# r=2.150 and r=2.700, inside both bands.
#
# Larger rows are standard-table values and should be spot-checked before a demo
# claims a thread they produced.
# ---------------------------------------------------------------------------
ISO4762 = {
    #  M  : (shank r, head r nominal, head height k, hex drive)
    1.6: (0.80, 1.50, 1.6, 1.5),
    2.0: (1.00, 1.90, 2.0, 1.5),
    2.5: (1.25, 2.25, 2.5, 2.0),
    3.0: (1.50, 2.75, 3.0, 2.5),
    4.0: (2.00, 3.50, 4.0, 3.0),
    5.0: (2.50, 4.25, 5.0, 4.0),
    6.0: (3.00, 5.00, 6.0, 5.0),
    8.0: (4.00, 6.50, 8.0, 6.0),
    10.0: (5.00, 8.00, 10.0, 8.0),
    12.0: (6.00, 9.00, 12.0, 10.0),
}
SHANK_TOL_MM = 0.35   # modelled shanks sit at or slightly under nominal
HEAD_TOL_MM  = 0.30   # modelled heads sit at or slightly under dk max
HEAD_RATIO   = (1.5, 2.1)   # head_r / shank_r band for a cap-screw-like part
MAX_AXIS_LINES = 2          # a fastener is one body of revolution; a plate is not


def classify_fasteners(cyl_by_def, overrides=None):
    """Identify fastener definitions from CYLINDER GEOMETRY, not from part names.

    A cap screw presents two coaxial cylinder families: a dominant small-radius
    shank and a larger short head, with head/shank ratio in a narrow band. Matching
    the pair against the ISO 4762 table yields a candidate thread without relying
    on names. Each new assembly still needs an explicit recall/false-positive check.

    Returns {defName: {shank, M, len, std, confidence, basis}}.
    `overrides` (e.g. data/mfg/identity.json) always wins over inference.
    """
    out = {}
    for name, cyls in (cyl_by_def or {}).items():
        if not cyls:
            continue
        # A fastener is a SINGLE body of revolution: every cylinder it owns lies on
        # one axis line. A plate with a counterbored clearance hole presents the same
        # shank/head radius pair, but spread over many parallel axis lines -- one per
        # hole. Counting distinct axis lines is what separates a screw from a plate,
        # and it is the discriminator that keeps this working on an assembly whose
        # parts we have never seen.
        lines = set()
        for r, org, d in cyls:
            dn = unit(d)
            if dn[0] < 0 or (dn[0] == 0 and (dn[1] < 0 or (dn[1] == 0 and dn[2] < 0))):
                dn = [-c for c in dn]                       # canonical direction sign
            t = sum(org[k]*dn[k] for k in range(3))
            perp = tuple(round(org[k] - t*dn[k], 1) for k in range(3))   # point on axis
            lines.add((perp, tuple(round(c, 2) for c in dn)))
        if len(lines) > MAX_AXIS_LINES:
            continue
        radii = collections.Counter(round(r, 3) for r, _, _ in cyls)
        if len(radii) < 2:
            continue
        shank_r = radii.most_common(1)[0][0]                 # most faces = the shank
        bigger = [r for r in radii if r > shank_r]
        if not bigger:
            continue
        head_r = min(bigger, key=lambda r: abs(r - shank_r * 1.8))
        ratio = head_r / shank_r if shank_r else 0
        if not (HEAD_RATIO[0] <= ratio <= HEAD_RATIO[1]):
            continue
        best = None
        for M, (sr, hr, k, hexs) in ISO4762.items():
            ds, dh = abs(shank_r - sr), abs(head_r - hr)
            if ds <= SHANK_TOL_MM and dh <= HEAD_TOL_MM:
                score = ds + dh
                if best is None or score < best[0]:
                    best = (score, M, hexs)
        if best is None:
            continue
        _, M, hexs = best
        out[name] = {'shank': shank_r, 'M': M, 'len': None,
                     'std': f'ISO 4762 class (inferred), hex {hexs} mm',
                     'confidence': round(max(0.0, 1.0 - best[0]), 3),
                     'basis': f'shank r={shank_r}, head r={head_r}, ratio {ratio:.2f}'}
    for k, v in (overrides or {}).items():
        out[k] = {**out.get(k, {}), **v}
    return out


# Measured fingerprints from S500-C1_ASM.step. These act as OVERRIDES on the
# geometric classifier -- they carry nominal lengths and the exact GB standard,
# which inference cannot recover. Any assembly without these still classifies.
FASTENERS = {
    'GB70-M2-5-6-DING':   {'shank': 1.200, 'M': 2.5, 'len': 6,  'std': 'GB/T 70 (~ISO 4762) socket head'},
    'GB70-M3-8-DING':     {'shank': 1.484, 'M': 3.0, 'len': 8,  'std': 'GB/T 70 (~ISO 4762) socket head'},
    'GB70-M3-21-DING':    {'shank': 1.484, 'M': 3.0, 'len': 21, 'std': 'GB/T 70 (~ISO 4762) socket head'},
    'GB70-M3-25-DING':    {'shank': 1.484, 'M': 3.0, 'len': 25, 'std': 'GB/T 70 (~ISO 4762) socket head'},
    'M2-5-GB819-8-DING':  {'shank': 1.150, 'M': 2.5, 'len': 8,  'std': 'GB/T 819 countersunk cross'},
    'NILONG-GB818-M3':    {'shank': 1.400, 'M': 3.0, 'len': 8,  'std': 'GB/T 818 pan head cross, nylon'},
}
# Preferred stock lengths, mm. Used to round a computed requirement up to a real part.
STOCK = {2.5: [4, 5, 6, 8, 10, 12, 16, 20, 25, 30],
         3.0: [4, 5, 6, 8, 10, 12, 16, 20, 25, 30, 35]}

FIT_MAX_MM   = 0.35   # r_hole - r_shank upper bound for "this is a fit, not a passage"
AXIS_OFF_MM  = 0.60   # max perpendicular distance between shank and hole axes
AXIS_ANG_DEG = 1.0    # max angle between the two axes
ENGAGE_D     = 1.5    # thread engagement multiple of nominal diameter (polyamide: 1.5-2.0 x D)


def _dot(a, b): return sum(a[k]*b[k] for k in range(3))
def _sub(a, b): return [a[k]-b[k] for k in range(3)]


def derive(occurrences, cyl_by_def, mesh=None, vert_path=None, fasteners=None):
    """Derive edges. `fasteners` defaults to geometric classification with the
    measured S500 fingerprints applied as overrides. Geometry can identify
    candidates despite unfamiliar names; every new assembly still needs validation."""
    if fasteners is None:
        fasteners = classify_fasteners(cyl_by_def, overrides=FASTENERS)
    cos_tol = math.cos(math.radians(AXIS_ANG_DEG))

    world = {}
    for o in occurrences:
        cy = cyl_by_def.get(o['defName'], [])
        if cy:
            world[o['occId']] = [(r, apply_point(o['T'], org), unit(apply_dir(o['T'], d)))
                                 for r, org, d in cy]
    by_id = {o['occId']: o for o in occurrences}

    edges, stacks = [], {}
    for f in occurrences:
        spec = fasteners.get(f['defName'])
        if not spec:
            continue
        shanks = [c for c in world.get(f['occId'], []) if abs(c[0]-spec['shank']) < 0.02]
        if not shanks:
            continue
        _, org, axis = shanks[0]
        clamped = []
        for oid, holes in world.items():
            if oid == f['occId'] or by_id[oid]['defName'] in fasteners:
                continue
            hits = []
            for r2, o2, d2 in holes:
                dr = r2 - spec['shank']
                if not (0 <= dr <= FIT_MAX_MM):        continue
                if abs(_dot(axis, d2)) < cos_tol:      continue
                w = _sub(o2, org)
                perp = math.sqrt(max(_dot(w, w) - _dot(w, axis)**2, 0))
                if perp <= AXIS_OFF_MM:
                    hits.append((r2, dr, perp, _dot(w, axis)))
            if hits:
                best = min(hits, key=lambda h: h[2])
                clamped.append((oid, best))
                edges.append({
                    'type': 'FASTENS', 'from': f['occId'], 'to': oid, 'tier': 'geometry',
                    'fromDef': f['defName'], 'toDef': by_id[oid]['defName'],
                    'clearanceMm': round(2*best[1], 4), 'axisOffsetMm': round(best[2], 4),
                    'reason': (f"shank r={spec['shank']:.3f} collinear with hole r={best[0]:.3f} "
                               f"(diametral clearance {2*best[1]:.3f} mm, axis offset {best[2]:.3f} mm "
                               f"<= {AXIS_OFF_MM} mm, axes parallel within {AXIS_ANG_DEG} deg)"),
                })
        if clamped:
            stacks[f['occId']] = _grip(f, spec, org, axis, clamped, mesh, vert_path, by_id)
    return edges, stacks


# ---------------------------------------------------------------------------
# Shared swept-volume primitive.
#
# Three separate checks need "what occupies this cylinder in space":
#   - protrusion  (manufacturing: does a longer screw punch into something?)
#   - tool access (manufacturing: can a driver shaft reach the head?)
#   - BLOCKS_ACCESS (design: teardown order, issue #26)
# Built once here so the two workstreams cannot produce two subtly different
# versions. See docs/research/manufacturing-side-spec.md sections 5.1-5.3.
# ---------------------------------------------------------------------------

def load_vertex_cache(mesh, vert_path):
    """Decode mesh_vert.bin once into {partIndex: [(x,y,z), ...]}.

    swept_volume_hits re-reads and re-unpacks the whole vertex file on every call,
    which is fine for a handful of queries and wasteful for a check harness that
    sweeps every fastener in a candidate family. Pass the result as `verts=` to reuse
    the decode. Same bytes, same numbers -- this is a decode cache, not a second
    geometry implementation.
    """
    cache = {}
    with open(vert_path, 'rb') as fh:
        for part in mesh['parts']:
            fh.seek(part['vOff'])
            raw = fh.read(part['vCount'] * 12)
            cache[part['i']] = [struct.unpack_from('<fff', raw, k)
                                for k in range(0, len(raw), 12)]
    return cache


def swept_volume_hits(mesh, vert_path, org, axis, radius, t0, t1, exclude=(), verts=None):
    """Occurrences whose mesh vertices fall inside a cylinder along `axis`.

    org, axis  world-space origin and unit direction of the cylinder
    radius     cylinder radius, mm
    t0, t1     interval along the axis, mm (t1 may be less than t0)
    exclude    occurrence ids to skip (normally the fastener itself)
    verts      optional load_vertex_cache() result; avoids re-reading vert_path

    Returns [{occId, defName, hitCount, nearestMm}], nearest first. A conservative
    vertex test: a part is reported when any vertex lies inside the cylinder. It can
    miss a part whose surface passes through with no vertex inside, so callers must
    treat an empty result as "no evidence of collision", not "proven clear".

    The asymmetry is the point, and Factory depends on it: OCCT places triangulation
    nodes ON the exact surface, so a reported vertex is a real point of the real
    solid and a hit is sound evidence of interference. Sparse sampling can only hide
    a collision, never invent one. Reported penetration is therefore a LOWER BOUND.
    """
    lo, hi = (t0, t1) if t0 <= t1 else (t1, t0)
    out = []
    fh = None if verts is not None else open(vert_path, 'rb')
    try:
        for part in mesh['parts']:
            oid = part.get('occ')
            if not oid or oid in exclude:
                continue
            if verts is not None:
                pts = verts[part['i']]
            else:
                fh.seek(part['vOff'])
                raw = fh.read(part['vCount'] * 12)
                pts = (struct.unpack_from('<fff', raw, k) for k in range(0, len(raw), 12))
            hits, nearest = 0, None
            for v in pts:
                w = _sub(v, org)
                t = _dot(w, axis)
                if not (lo <= t <= hi):
                    continue
                if math.sqrt(max(_dot(w, w) - t*t, 0)) <= radius:
                    hits += 1
                    if nearest is None or abs(t) < abs(nearest):
                        nearest = t
            if hits:
                out.append({'occId': oid, 'defName': part['name'],
                            'hitCount': hits, 'nearestMm': round(nearest, 3)})
    finally:
        if fh is not None:
            fh.close()
    out.sort(key=lambda h: abs(h['nearestMm']))
    return out


def _axial_span(fh, part, org, axis, band):
    """[min, max] projection onto the axis of vertices within `band` of the axis line."""
    fh.seek(part['vOff'])
    raw = fh.read(part['vCount']*12)
    ts = []
    for k in range(0, len(raw), 12):
        v = struct.unpack_from('<fff', raw, k)
        w = _sub(v, org); t = _dot(w, axis)
        if math.sqrt(max(_dot(w, w) - t*t, 0)) <= band:
            ts.append(t)
    return (min(ts), max(ts)) if ts else (None, None)


def _grip(f, spec, org, axis, clamped, mesh, vert_path, by_id):
    """Ordered clamped stack with grip length, measured along the fastener axis.

    Thickness comes from real mesh vertices inside a tolerance cylinder around the
    fastener axis -- a bounding box over-reports for anything that is not a flat plate.

    Critically, every clamped interval is clipped to the fastener's OWN axial span.
    Without that clip a screw threading into a boss reports the full height of the
    part it enters (18 mm of arm body for an M2.5x6), which is not grip -- a fastener
    cannot clamp material it does not reach.
    """
    members, grip, measured_len = [], None, None
    if mesh and vert_path:
        idx = {}
        for p in mesh['parts']:
            idx.setdefault(p.get('occ'), p)
        band = spec['shank'] * 3.0
        with open(vert_path, 'rb') as fh:
            fp = idx.get(f['occId'])
            f_lo, f_hi = _axial_span(fh, fp, org, axis, band * 2.2) if fp else (None, None)
            if f_lo is not None:
                measured_len = round(f_hi - f_lo, 3)
            lo, hi = None, None
            for oid, best in clamped:
                p = idx.get(oid)
                entry = exit_ = None
                if p:
                    a, b = _axial_span(fh, p, org, axis, band)
                    if a is not None and f_lo is not None:
                        a, b = max(a, f_lo), min(b, f_hi)     # clip to the fastener's reach
                        if b > a:
                            entry, exit_ = a, b
                            lo = entry if lo is None else min(lo, entry)
                            hi = exit_ if hi is None else max(hi, exit_)
                members.append({'occId': oid, 'defName': by_id[oid]['defName'],
                                'entryMm': None if entry is None else round(entry, 3),
                                'exitMm':  None if exit_ is None else round(exit_, 3),
                                'thicknessMm': None if entry is None else round(exit_-entry, 3)})
        if lo is not None:
            grip = round(hi - lo, 3)
    else:
        members = [{'occId': o, 'defName': by_id[o]['defName'],
                    'entryMm': None, 'exitMm': None, 'thicknessMm': None} for o, _ in clamped]

    members.sort(key=lambda m: (m['entryMm'] is None, m['entryMm']))
    nominal = spec.get('len')
    if nominal is None and measured_len is not None:
        # inferred fastener: recover nominal shank length as measured minus head height
        k = ISO4762.get(spec['M'], (0, 0, 0, 0))[2]
        nominal = round(measured_len - k, 1)
    engage = round(ENGAGE_D * spec['M'], 2)
    req = None if grip is None else round(grip + engage, 2)
    # An absolute adequate/inadequate verdict needs the THREADED member identified --
    # which part the screw actually bites into. Only clearance-fit holes are derivable
    # from this file (a tapped hole and a clearance hole are both cylinders), and some
    # mates are into parts not in the assembly at all (motors, nuts). So absolute
    # adequacy is reported as unknown. The RELATIVE claim is still sound and is what
    # the work order uses: if a clamped part gets t mm thicker, every fastener through
    # it needs t mm more length. See actions_for_thickness_change().
    threaded = None
    return {'fastener': f['occId'], 'defName': f['defName'], 'standard': spec['std'],
            'nominalM': spec['M'], 'nominalLengthMm': nominal,
            'identifiedBy': spec.get('basis', 'override'),
            'identityConfidence': spec.get('confidence', 1.0),
            'measuredLengthMm': measured_len,
            'gripMm': grip, 'engagementMm': engage, 'requiredLengthMm': req,
            'adequate': None, 'adequacyUnknownBecause':
                'threaded member not identified from geometry; a tapped hole and a '
                'clearance hole are both CYLINDRICAL_SURFACE, and some mates are into '
                'parts outside this assembly (motors, nuts)',
            'threadedMember': threaded,
            'members': members}


def _stock_ladder(M):
    """Available lengths for thread M.

    data/mfg/stock.json is authoritative when present -- it knows what is actually
    buyable and in stock. STOCK is the ISO 4762 fallback for when the manufacturing
    corpus has not been authored yet. One source of truth, with a defined precedence,
    so the two sides cannot drift.
    """
    import json, os
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        '..', '..', 'data', 'mfg', 'stock.json')
    try:
        items = json.load(open(path))['items']
        ls = sorted({i['lengthMm'] for i in items
                     if abs(float(str(i['thread']).lstrip('Mm')) - M) < 1e-6
                     and i.get('lifecycle') == 'active' and i.get('onHand', 0) > 0})
        if ls:
            return ls
    except Exception:
        pass
    return STOCK.get(M, [])


def next_stock(M, need):
    for L in _stock_ladder(M):
        if L >= need - 1e-6:
            return L
    return None


def actions_for_thickness_change(stacks, changed_def, delta_mm):
    """Concrete edits when one part's thickness changes by delta_mm.

    Every fastener clamping that part sees its grip change by the same delta, so its
    required length moves with it. Rounded up to the nearest stock length.
    """
    out = []
    for fid, s in stacks.items():
        if not any(m['defName'] == changed_def for m in s['members']):
            continue
        if s['gripMm'] is None:
            continue
        new_grip = round(s['gripMm'] + delta_mm, 3)
        assumed_need = round(new_grip + s['engagementMm'], 2)
        # The threaded member is unknown, so the only defensible recommendation is
        # relative: preserve today's engagement by carrying the thickness delta into
        # the nominal fastener length. Keep the assumption-based figure as evidence,
        # but never let it silently drive the work order.
        relative_need = round(s['nominalLengthMm'] + max(delta_mm, 0), 2)
        pick = next_stock(s['nominalM'], relative_need)
        ok = delta_mm <= 0
        out.append({
            'fastener': fid, 'defName': s['defName'], 'currentLengthMm': s['nominalLengthMm'],
            'gripMm': s['gripMm'], 'newGripMm': new_grip, 'engagementMm': s['engagementMm'],
            'requiredLengthMm': relative_need,
            'assumptionBasedRequiredLengthMm': assumed_need,
            'recommendedLengthMm': pick, 'stillAdequate': ok,
            'action': ('no length change required' if ok else
                       (f"lengthen M{s['nominalM']:g}x{s['nominalLengthMm']:g} by "
                        f"{delta_mm:g} mm -> M{s['nominalM']:g}x"
                        f"{pick:g}"
                        if pick else f"needs >= {relative_need} mm -- no stock length available")),
            'reason': (f"grip {s['gripMm']} mm {'+' if delta_mm>=0 else ''}{delta_mm} mm -> {new_grip} mm; "
                       f"preserve current engagement by adding the same thickness delta to "
                       f"the current {s['nominalLengthMm']:g} mm nominal length; "
                       f"{assumed_need} mm is the separate {ENGAGE_D}x D assumption-based estimate"),
        })
    return out
