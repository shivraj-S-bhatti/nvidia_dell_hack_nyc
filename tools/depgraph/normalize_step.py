"""normalize_step.py -- fold geometry a product owns but does not contain back into it.

    python3 tools/depgraph/normalize_step.py in.step out.step

Some CAD writers put a component's solid in a separate
ADVANCED_BREP_SHAPE_REPRESENTATION and tie it to the product with a
SHAPE_REPRESENTATION_RELATIONSHIP, leaving the SHAPE_REPRESENTATION that
SHAPE_DEFINITION_REPRESENTATION names holding nothing but a placement.

A reader that descends only from the product's own representation then sees parts with
no faces -- silently, because every entity is present and well formed, they are simply
empty. This is not a hypothetical: on neoracer-full-vehicle.step it makes OCCT return
1136 meshes containing zero vertices while reporting success, and it hid 3951 of the
file's 7273 CYLINDRICAL_SURFACE entities from parse_step.

This tool appends each orphaned representation's items into the product representation
that owns it. Nothing is deleted, no entity is renumbered, and no reference is
rewritten, so every placement, transform and assembly edge keeps pointing where it did.
Files that already carry their geometry inline are passed through byte-identical in
content -- S500-C1_ASM.step, neoracer-printed-parts.step and
neoracer-oscore-board.step all have zero such links.

Deterministic, offline, no CAD kernel: it is a text transform over STEP entities.
"""
import re, sys, os, collections


def find_links(src, ents):
    """{productRep: [orphan geometry reps]} -- the same rule parse_step._index uses.

    Only product-representation -> orphan-representation edges qualify. The same
    relationship type also places one component representation inside another, with a
    transformation operator; folding those in would merge an entire assembly's
    geometry into each of its parts. Requiring the far end to be a representation that
    no product claims separates the two uses.
    """
    prod_reps = set()
    for i, (t, a) in ents.items():
        if t == 'SHAPE_DEFINITION_REPRESENTATION':
            r = [int(x) for x in re.findall(r'#(\d+)', a)]
            if len(r) >= 2:
                prod_reps.add(r[1])
    links = collections.defaultdict(list)
    for i, (t, a) in ents.items():
        if t.endswith('REPRESENTATION_RELATIONSHIP'):
            rs = [int(x) for x in re.findall(r'#(\d+)', a)]
        elif t == 'COMPLEX' and 'REPRESENTATION_RELATIONSHIP' in a:
            m = re.search(r'\bREPRESENTATION_RELATIONSHIP\s*\(([^()]*)\)', a)
            rs = [int(x) for x in re.findall(r'#(\d+)', m.group(1))] if m else []
        else:
            continue
        if len(rs) < 2:
            continue
        for src_id, dst in ((rs[0], rs[1]), (rs[1], rs[0])):
            if src_id in prod_reps and dst not in prod_reps and dst in ents:
                links[src_id].append(dst)
    return {k: sorted(set(v)) for k, v in links.items()}


# name/description , ( items ) , context
BODY = re.compile(r"^\s*(.*?)\s*,\s*\((.*)\)\s*,\s*(#\d+)\s*$", re.S)


def normalize(in_path, out_path):
    src = re.sub(r'\s*\n\s*', ' ', open(in_path, encoding='utf-8', errors='replace').read())
    ents = {}
    for m in re.finditer(r'#(\d+)\s*=\s*(.*?);', src):
        body = m.group(2).strip()
        mm = re.match(r'([A-Z_0-9]+)\s*\((.*)\)$', body, re.S)
        ents[int(m.group(1))] = (mm.group(1), mm.group(2)) if mm else ('COMPLEX', body)

    links = find_links(src, ents)
    folded, moved_items = 0, 0
    for rep, geoms in sorted(links.items()):
        t, a = ents.get(rep, (None, None))
        if t != 'SHAPE_REPRESENTATION':
            continue
        host = BODY.match(a)
        if not host:
            continue
        extra = []
        for g in geoms:
            gt, ga = ents.get(g, (None, None))
            gm = BODY.match(ga) if ga else None
            if gm:
                extra += [x.strip() for x in gm.group(2).split(',') if x.strip()]
        extra = [x for x in extra if x not in
                 {y.strip() for y in host.group(2).split(',')}]
        if not extra:
            continue
        new_items = host.group(2).strip()
        new_items = f"{new_items},{','.join(extra)}" if new_items else ','.join(extra)
        new_body = f"{host.group(1)},({new_items}),{host.group(3)}"
        old = f"#{rep} = SHAPE_REPRESENTATION({a});"
        # The collapsed source may space the assignment differently; match on the id.
        pat = re.compile(rf"#{rep}\s*=\s*SHAPE_REPRESENTATION\s*\(.*?\)\s*;", re.S)
        new = f"#{rep} = SHAPE_REPRESENTATION({new_body});"
        src, n = pat.subn(lambda _: new, src, count=1)
        if n:
            folded += 1
            moved_items += len(extra)

    with open(out_path, 'w') as fh:
        fh.write(src)
    return {'productRepresentations': len({r for r in links}),
            'folded': folded, 'itemsMoved': moved_items,
            'bytesIn': os.path.getsize(in_path), 'bytesOut': os.path.getsize(out_path)}


def main():
    if len(sys.argv) < 3:
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        return 2
    r = normalize(sys.argv[1], sys.argv[2])
    if r['folded'] == 0:
        print(f"geometry already inline -- nothing to fold ({r['bytesOut']/1e6:.1f} MB out)")
    else:
        print(f"folded {r['folded']} orphaned geometry representations "
              f"({r['itemsMoved']} items) into their product representations")
        print(f"  {r['bytesIn']/1e6:.1f} MB -> {r['bytesOut']/1e6:.1f} MB")
    return 0


if __name__ == '__main__':
    sys.exit(main())
