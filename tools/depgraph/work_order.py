"""work_order.py -- turn a change request into a concrete, ordered work order.

  python3 tools/depgraph/work_order.py BOTTOM-PLATE-S500 --thicker 1.0
  python3 tools/depgraph/work_order.py GB70-M2-5-6-DING

Blast radius comes from the derived graph; length actions come from measured grip
stacks. Absolute fastener adequacy is never claimed -- see derive_edges._grip.
"""
import json, sys, os, collections, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from derive_edges import actions_for_thickness_change


def propagate(G, seed, max_hops=3):
    nodes = {n['id']: n for n in G['nodes']}
    adj = collections.defaultdict(list)
    for e in G['edges']:
        if e['t'] == 'FASTENS':
            adj[e['a']].append(e); adj[e['b']].append(e)
    hop, why = {o: 0 for o in seed}, {o: ('ANCHOR', 'selected for change') for o in seed}
    closed, frontier = set(), list(seed)
    for h in range(1, max_hops + 1):
        nxt = []
        for a in frontier:
            for e in adj.get(a, []):
                b = e['b'] if e['a'] == a else e['a']
                if b in hop: continue
                hop[b] = h; why[b] = ('FASTENS', e['why']); nxt.append(b)
        # close each definition once -- rescanning per node is quadratic at corpus scale
        i = 0
        while i < len(nxt):
            d = nodes.get(nxt[i], {}).get('def')
            if d and d not in closed:
                closed.add(d)
                for s in G['defs'].get(d, []):
                    if s in hop: continue
                    hop[s] = h
                    why[s] = ('INSTANCE_OF',
                              f"shared part definition {d} -- a spec change applies to "
                              f"all {len(G['defs'][d])} occurrences")
                    nxt.append(s)
            i += 1
        frontier = nxt
        if not nxt: break
    return hop, why


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('part')
    ap.add_argument('--thicker', type=float, default=None, help='thickness change in mm')
    ap.add_argument('--hops', type=int, default=3)
    ap.add_argument('--dir', default='.artifacts/depgraph')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()

    G = json.load(open(os.path.join(a.dir, 'graph.json')))
    nodes = {n['id']: n for n in G['nodes']}
    seed = G['defs'].get(a.part)
    if not seed:
        print(f"unknown part '{a.part}'. known definitions:")
        for d in sorted(G['defs']): print('  ', d)
        return 2

    hop, why = propagate(G, seed, a.hops)
    by_def = collections.defaultdict(lambda: {'hop': 99, 'occs': [], 'why': None})
    for o, h in hop.items():
        d = nodes[o]['def']; g = by_def[d]
        g['occs'].append(o); g['hop'] = min(g['hop'], h)
        if g['why'] is None: g['why'] = why[o]
    rows = sorted(by_def.items(), key=lambda kv: (kv[1]['hop'], -len(kv[1]['occs'])))

    actions = actions_for_thickness_change(G['stacks'], a.part, a.thicker) if a.thicker else []

    if a.json:
        print(json.dumps({'corpusRevision': G['corpusRevision'], 'anchor': a.part,
                          'anchorOccurrences': len(seed), 'maxHops': a.hops,
                          'impacted': [{'def': d, 'hop': v['hop'], 'count': len(v['occs']),
                                        'edge': v['why'][0], 'why': v['why'][1]}
                                       for d, v in rows],
                          'lengthActions': actions}, indent=2))
        return 0

    print(f"\nWORK ORDER   corpus {G['corpusRevision']}   source {G['source']}")
    print(f"anchor: {a.part}  ({len(seed)} occurrence{'s' if len(seed)!=1 else ''})"
          + (f"   change: thickness {a.thicker:+g} mm" if a.thicker else ""))
    print(f"\nBLAST RADIUS -- {len(rows)} definitions, {len(hop)} occurrences, max hop {max(hop.values())}\n")
    print(f"  {'hop':>3} {'qty':>4}  {'part':26s} {'via':12s} why")
    print(f"  {'-'*3} {'-'*4}  {'-'*26} {'-'*12} {'-'*44}")
    for d, v in rows:
        w = (v['why'][1] or '')[:44]
        print(f"  {v['hop']:>3} {len(v['occs']):>4}  {d[:26]:26s} {v['why'][0][:12]:12s} {w}")

    if actions:
        need = [x for x in actions if not x['stillAdequate']]
        print(f"\nLENGTH ACTIONS -- {len(actions)} fasteners clamp {a.part}, "
              f"{len(need)} need a longer part\n")
        agg = collections.defaultdict(list)
        for x in actions: agg[(x['defName'], x['action'])].append(x)
        for (dn, act), xs in sorted(agg.items()):
            print(f"  x{len(xs):<3} {dn:22s} {act}")
            print(f"        {xs[0]['reason']}")
    elif a.thicker:
        print(f"\nLENGTH ACTIONS -- no measured grip stack clamps {a.part}")

    print("\nMUST VERIFY BY HUMAN")
    print("  - absolute fastener adequacy is NOT claimed: the threaded member is not")
    print("    derivable from this file. Length deltas are relative to today's build.")
    print("  - clamp-type joints (carbon tube in JIA-GUAN) have no FASTENS edge yet.")
    print("  - derived edges are geometric inferences with stated tolerances, not")
    print("    the original designer's intent.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
