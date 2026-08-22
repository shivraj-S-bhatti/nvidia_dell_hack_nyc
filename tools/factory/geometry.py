"""geometry.py -- the measured baseline every Factory check is evaluated against.

Loads the assembly once and resolves, per fastener occurrence, the numbers a
clearance or length check needs: shank axis in world space, which end is the tip,
how far the part already extends along that axis, and which occurrences its own
volume already overlaps (its mating boss and the parts it passes through).

Nothing here is a verdict. Verdicts live in checks.py, which compares these
measurements against a candidate's declared deltas.

No language model touches this file. Every number comes from the STEP file or the
tessellated mesh, and every tolerance is a named constant in depgraph/derive_edges.
"""
import sys, os, json, hashlib

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'depgraph'))
from parse_step import Step, apply_point, apply_dir, unit                      # noqa: E402
from derive_edges import (classify_fasteners, FASTENERS, derive, swept_volume_hits,  # noqa: E402
                          load_vertex_cache, _axial_span, _dot, _sub, _stock_ladder)

# A cylinder is "the shank" when its radius matches the classified shank radius to
# this tolerance. Same value derive() uses to pick shank faces, kept in one place.
SHANK_MATCH_MM = 0.02
# Band around the axis used to measure a fastener's own axial extent. derive._grip
# uses shank*3.0 for clamped members and shank*3.0*2.2 for the fastener itself --
# the fastener band must clear its own head, which is ~1.8x the shank radius.
FASTENER_BAND = 6.6
# A cylinder counts as "head" when it is meaningfully wider than the shank. Used
# only to decide which end of the part is the tip, never to classify the fastener.
HEAD_RATIO_MIN = 1.4


class Assembly:
    """Baseline geometry, parsed once and reused across every candidate.

    Parsing the STEP file costs several seconds; a candidate family re-uses the same
    baseline, so this is built once per run and passed to each verdict. That is also
    what makes repeated runs identical -- every candidate sees the same numbers.
    """

    def __init__(self, step_path, art_dir):
        self.step_path = step_path
        self.art_dir = art_dir
        self.stepSha256 = hashlib.sha256(open(step_path, 'rb').read()).hexdigest()

        st = Step(step_path)
        self.occurrences = st.occurrences()
        self.cylinders = st.cylinders_by_definition()
        self.mesh = json.load(open(os.path.join(art_dir, 'mesh.json')))
        self.vert_path = os.path.join(art_dir, 'mesh_vert.bin')
        self.graph = json.load(open(os.path.join(art_dir, 'graph.json')))
        self.corpusRevision = self.graph['corpusRevision']

        # One decode of mesh_vert.bin, reused by every swept-volume query below.
        self.verts = load_vertex_cache(self.mesh, self.vert_path)

        self.fasteners = classify_fasteners(self.cylinders, overrides=FASTENERS)
        _, self.stacks = derive(self.occurrences, self.cylinders, self.mesh, self.vert_path)

        self.by_id = {o['occId']: o for o in self.occurrences}
        self.defs = {}
        for o in self.occurrences:
            self.defs.setdefault(o['defName'], []).append(o['occId'])

        self._world = {}
        for o in self.occurrences:
            cy = self.cylinders.get(o['defName'], [])
            if cy:
                self._world[o['occId']] = [
                    (r, apply_point(o['T'], org), unit(apply_dir(o['T'], d)))
                    for r, org, d in cy]

        self.sites = self._resolve_fastener_sites()

    # ------------------------------------------------------------------
    def _resolve_fastener_sites(self):
        """Per fastener occurrence: axis, tip end, growth direction, existing mates.

        `mates` is every occurrence already overlapping the fastener's own swept
        volume -- the parts it passes through and the boss it threads into. A
        clearance check must exclude these, or every screw would report a collision
        with the hole it is supposed to sit in.
        """
        sites = {}
        for f in sorted(self.occurrences, key=lambda o: o['occId']):
            spec = self.fasteners.get(f['defName'])
            if not spec:
                continue
            shanks = [c for c in self._world.get(f['occId'], [])
                      if abs(c[0] - spec['shank']) < SHANK_MATCH_MM]
            part = next((p for p in self.mesh['parts'] if p.get('occ') == f['occId']), None)
            if not shanks or part is None:
                continue
            _, org, axis = shanks[0]

            f_lo, f_hi = _axial_span_cached(self.verts, part, org, axis,
                                            spec['shank'] * FASTENER_BAND)
            if f_lo is None:
                continue

            # The tip is the end away from the head. A cap screw's head is the only
            # cylinder family meaningfully wider than the shank, so its projection
            # onto the axis tells us which end the part grows from when it lengthens.
            heads = [c for c in self._world[f['occId']]
                     if c[0] > spec['shank'] * HEAD_RATIO_MIN]
            if heads:
                t_head = _dot(_sub(heads[0][1], org), axis)
                tip_at_hi = t_head < (f_lo + f_hi) / 2.0
            else:
                tip_at_hi = True
            tip = f_hi if tip_at_hi else f_lo
            direction = 1.0 if tip_at_hi else -1.0

            mates = {h['occId'] for h in swept_volume_hits(
                self.mesh, self.vert_path, org, axis, spec['shank'], f_lo, f_hi,
                exclude={f['occId']}, verts=self.verts)}

            sites[f['occId']] = {
                'occId': f['occId'], 'defName': f['defName'],
                'M': spec['M'], 'shankR': spec['shank'],
                'nominalLengthMm': spec.get('len'),
                'org': org, 'axis': axis,
                'spanLoMm': round(f_lo, 3), 'spanHiMm': round(f_hi, 3),
                'tipMm': round(tip, 3), 'direction': direction,
                'mates': sorted(mates),
            }
        return sites

    # ------------------------------------------------------------------
    def sweep_beyond_tip(self, site, growth_mm):
        """What the shank would occupy if it grew `growth_mm` past its current tip.

        Returns the swept_volume_hits list with the fastener's existing mates removed,
        so a hit means the growth reaches material the part does not touch today.
        """
        t0 = site['tipMm']
        t1 = t0 + site['direction'] * growth_mm
        hits = swept_volume_hits(self.mesh, self.vert_path, site['org'], site['axis'],
                                 site['shankR'], t0, t1,
                                 exclude={site['occId']}, verts=self.verts)
        return [h for h in hits if h['occId'] not in site['mates']]

    def stock_ladder(self, M):
        return _stock_ladder(M)

    def sampling_density(self):
        """Vertices per occurrence -- the resolution behind a 'no interference' result.

        A clearance pass is only ever "no evidence of interference at this sampling
        density". Reporting the density keeps that claim auditable.
        """
        counts = [p['vCount'] for p in self.mesh['parts']]
        return {'occurrencesSampled': len(counts), 'vertices': sum(counts),
                'minVerticesPerOccurrence': min(counts) if counts else 0}


def _axial_span_cached(verts, part, org, axis, band):
    """_axial_span over the decoded vertex cache. Same predicate, no file read."""
    ts = []
    for v in verts[part['i']]:
        w = _sub(v, org)
        t = _dot(w, axis)
        import math
        if math.sqrt(max(_dot(w, w) - t * t, 0)) <= band:
            ts.append(t)
    return (min(ts), max(ts)) if ts else (None, None)
