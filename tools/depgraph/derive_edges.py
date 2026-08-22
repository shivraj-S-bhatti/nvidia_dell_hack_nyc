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

# Shank radius fingerprints, measured from S500-C1_ASM.step. A fastener is
# identified by geometry, not by trusting its name.
FASTENERS = {
    'GB70-M2-5-6-DING':   {'shank': 1.200, 'M': 2.5, 'len': 6,  'std': 'GB/T 70 (~ISO 4762) socket head'},
    'GB70-M3-8-DING':     {'shank': 1.484, 'M': 3.0, 'len': 8,  'std': 'GB/T 70 (~ISO 4762) socket head'},
    'GB70-M3-21-DING':    {'shank': 1.484, 'M': 3.0, 'len': 21, 'std': 'GB/T 70 (~ISO 4762) socket head'},
    'GB70-M3-25-DING':    {'shank': 1.484, 'M': 3.0, 'len': 25, 'std': 'GB/T 70 (~ISO 4762) socket head'},
    'M2-5-GB819-8-DING':  {'shank': 1.150, 'M': 2.5, 'len': 8,  'std': 'GB/T 819 countersunk cross'},
    'NILONG-GB818-M3':    {'shank': 1.400, 'M': 3.0, 'len': 8,  'std': 'GB/T 818 pan head cross, nylon'},
}
# Preferred stock lengths, mm. Used to round a computed requirement up to a real part.
STOCK = {2.5: [4, 5, 6, 8, 10, 12, 16, 20, 25], 3.0: [5, 6, 8, 10, 12, 16, 20, 25, 30, 35]}

FIT_MAX_MM   = 0.35   # r_hole - r_shank upper bound for "this is a fit, not a passage"
AXIS_OFF_MM  = 0.60   # max perpendicular distance between shank and hole axes
AXIS_ANG_DEG = 1.0    # max angle between the two axes
ENGAGE_D     = 1.5    # thread engagement multiple of nominal diameter (polyamide: 1.5-2.0 x D)


def _dot(a, b): return sum(a[k]*b[k] for k in range(3))
def _sub(a, b): return [a[k]-b[k] for k in range(3)]


def derive(occurrences, cyl_by_def, mesh=None, vert_path=None):
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
        spec = FASTENERS.get(f['defName'])
        if not spec:
            continue
        shanks = [c for c in world.get(f['occId'], []) if abs(c[0]-spec['shank']) < 0.02]
        if not shanks:
            continue
        _, org, axis = shanks[0]
        clamped = []
        for oid, holes in world.items():
            if oid == f['occId'] or by_id[oid]['defName'] in FASTENERS:
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
            'nominalM': spec['M'], 'nominalLengthMm': spec['len'],
            'measuredLengthMm': measured_len,
            'gripMm': grip, 'engagementMm': engage, 'requiredLengthMm': req,
            'adequate': None, 'adequacyUnknownBecause':
                'threaded member not identified from geometry; a tapped hole and a '
                'clearance hole are both CYLINDRICAL_SURFACE, and some mates are into '
                'parts outside this assembly (motors, nuts)',
            'threadedMember': threaded,
            'members': members}


def next_stock(M, need):
    for L in STOCK.get(M, []):
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
        need = round(new_grip + s['engagementMm'], 2)
        pick = next_stock(s['nominalM'], need)
        # relative verdict only: does this change require MORE length than today?
        ok = delta_mm <= 0
        out.append({
            'fastener': fid, 'defName': s['defName'], 'currentLengthMm': s['nominalLengthMm'],
            'gripMm': s['gripMm'], 'newGripMm': new_grip, 'engagementMm': s['engagementMm'],
            'requiredLengthMm': need, 'recommendedLengthMm': pick, 'stillAdequate': ok,
            'action': ('no length change required' if ok else
                       (f"lengthen M{s['nominalM']:g}x{s['nominalLengthMm']:g} by "
                        f"{delta_mm:g} mm -> M{s['nominalM']:g}x"
                        f"{next_stock(s['nominalM'], s['nominalLengthMm']+delta_mm) or '?':g}"
                        if pick else f"needs >= {need} mm -- no stock length available")),
            'reason': (f"grip {s['gripMm']} mm {'+' if delta_mm>=0 else ''}{delta_mm} mm -> {new_grip} mm; "
                       f"plus {s['engagementMm']} mm engagement ({ENGAGE_D}x D) = {need} mm required"),
        })
    return out
