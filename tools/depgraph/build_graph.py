"""build_graph.py -- STEP + tessellated mesh -> graph.json for the viewer and MongoDB.

  python3 tools/depgraph/build_graph.py S500-C1_ASM.step .artifacts/depgraph
"""
import json, sys, os, collections, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from parse_step import Step
from derive_edges import derive, FASTENERS

def bind_meshes(mesh, occurrences):
    """Bind OCC meshes to occurrences by definition name.

    Every LEAF definition has equal counts in both toolchains (subassemblies
    legitimately carry no mesh). Within a definition group, remove the group mean
    from both sides -- this cancels the systematic offset between an axis-origin
    translation and a mesh-vertex centroid -- then greedily pair nearest.
    """
    og, pg = collections.defaultdict(list), collections.defaultdict(list)
    # A part with no vertices has no centroid, and a part with no name cannot be
    # matched to a definition. Both occur in the wild -- neoracer-full-vehicle.step
    # yields 1136 parts, all empty and 671 of them unnamed -- and both used to reach
    # the centroid arithmetic below and raise TypeError on None. Bad input should
    # produce a reported count, not a traceback.
    skipped = 0
    for p in mesh['parts']:
        if not p.get('name') or not p.get('vCount') or \
                not p.get('centroid') or any(c is None for c in p['centroid']):
            skipped += 1
            continue
        og[p['name']].append(p)
    for o in occurrences:   pg[o['defName']].append(o)
    mapped, unmapped = {}, skipped
    for name, om in og.items():
        pm = pg.get(name, [])
        if len(pm) != len(om):
            unmapped += len(om); continue
        if len(om) == 1:
            mapped[om[0]['i']] = pm[0]['occId']; continue
        oc = [q['centroid'] for q in om]; pc = [o['T'][1] for o in pm]
        omu = [sum(c[k] for c in oc)/len(oc) for k in range(3)]
        pmu = [sum(c[k] for c in pc)/len(pc) for k in range(3)]
        used = set()
        for a, q in enumerate(om):
            va = [oc[a][k]-omu[k] for k in range(3)]
            best = None
            for b in range(len(pm)):
                if b in used: continue
                vb = [pc[b][k]-pmu[k] for k in range(3)]
                dd = sum((va[k]-vb[k])**2 for k in range(3))
                if best is None or dd < best[0]: best = (dd, b)
            used.add(best[1]); mapped[q['i']] = pm[best[1]]['occId']
    return mapped, unmapped


def main(step_path, out_dir):
    st = Step(step_path)
    occ = st.occurrences()
    cyl = st.cylinders_by_definition()
    mesh = json.load(open(os.path.join(out_dir, 'mesh.json')))
    vert = os.path.join(out_dir, 'mesh_vert.bin')

    mapped, unmapped = bind_meshes(mesh, occ)
    for p in mesh['parts']:
        p['occ'] = mapped.get(p['i'])
    json.dump(mesh, open(os.path.join(out_dir, 'mesh.json'), 'w'))

    fast_edges, stacks = derive(occ, cyl, mesh, vert)

    defs = collections.defaultdict(list)
    for o in occ: defs[o['defName']].append(o['occId'])

    nodes = {'S500-C1_ASM': {'id': 'S500-C1_ASM', 'name': 'S500-C1_ASM',
                             'def': 'S500-C1_ASM', 'parent': None, 'meshes': []}}
    o2m = collections.defaultdict(list)
    for mi, oid in mapped.items(): o2m[oid].append(mi)
    for o in occ:
        nodes[o['occId']] = {'id': o['occId'], 'name': o['occName'], 'def': o['defName'],
                             'parent': '/'.join(o['occId'].split('/')[:-1]) or 'S500-C1_ASM',
                             'meshes': o2m.get(o['occId'], []),
                             'isFastener': o['defName'] in FASTENERS}
    E = [{'t': 'CONTAINS', 'a': '/'.join(o['occId'].split('/')[:-1]) or 'S500-C1_ASM',
          'b': o['occId'], 'tier': 'geometry',
          'why': 'NEXT_ASSEMBLY_USAGE_OCCURRENCE'} for o in occ]
    for e in fast_edges:
        E.append({'t': 'FASTENS', 'a': e['from'], 'b': e['to'], 'tier': 'geometry',
                  'why': e['reason'], 'clr': e['clearanceMm'], 'off': e['axisOffsetMm']})

    rev = hashlib.sha256(open(step_path, 'rb').read()).hexdigest()[:16]
    payload = {'corpusRevision': rev, 'source': os.path.basename(step_path),
               'nodes': list(nodes.values()), 'edges': E,
               'defs': dict(defs), 'stacks': stacks}
    json.dump(payload, open(os.path.join(out_dir, 'graph.json'), 'w'))

    ns = len(stacks); grips = [s for s in stacks.values() if s['gripMm'] is not None]
    lens = [s for s in grips if s.get('measuredLengthMm')]
    print(f"corpusRevision   {rev}")
    print(f"definitions      {len(defs)}")
    print(f"occurrences      {len(occ)}")
    print(f"meshes bound     {len(mapped)}/{len(mesh['parts'])}  (unmapped {unmapped})")
    print(f"FASTENS edges    {len(fast_edges)}")
    print(f"CONTAINS edges   {len(occ)}")
    print(f"grip stacks      {ns}  ({len(grips)} with measured grip)")
    print(f"absolute adequacy  not claimed (threaded member not derivable) -- "
          f"relative length deltas are)")
    if grips:
        ex = grips[0]
        print(f"\nexample stack -- {ex['defName']}  M{ex['nominalM']:g}x{ex['nominalLengthMm']:g}")
        print(f"  measured length {ex.get('measuredLengthMm')} mm (nominal {ex['nominalLengthMm']} mm)")
        print(f"  grip {ex['gripMm']} mm + engagement {ex['engagementMm']} mm "
              f"= required {ex['requiredLengthMm']} mm")
        for m in ex['members']:
            print(f"    {m['defName']:22s} thickness={m['thicknessMm']}")


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'S500-C1_ASM.step',
         sys.argv[2] if len(sys.argv) > 2 else '.artifacts/depgraph')
