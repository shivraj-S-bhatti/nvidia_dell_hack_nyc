"""fcstd_to_mesh.py -- build the pipeline's mesh artifacts from a FreeCAD source file.

    python3 tools/depgraph/fcstd_to_mesh.py model.FCStd model.step .artifacts/out

Produces the same `mesh.json` + `mesh_vert.bin` that `step_to_mesh.mjs` produces, so
everything downstream -- grip stacks, swept-volume clearance, the graph, Factory --
runs unchanged.

Why: some STEP files will not tessellate. occt-import-js reads
neoracer-full-vehicle.step well enough to report every face and then triangulates
none of them (1136 meshes, 0 vertices, exit code 0; four deflection configurations,
identical result). The same geometry is present in the FreeCAD source as one BREP
shape per component, and BREP meshes normally.

The division of labour is the useful part:

  FCStd  ->  per-DEFINITION geometry, in each definition's own frame
  STEP   ->  the assembly: which definitions occur, where, how many times

`parse_step` already resolves a world transform for every occurrence, so this applies
those transforms to the local vertices rather than trying to re-derive placement from
FreeCAD's link graph. The two sources are joined on the component name, which FreeCAD
carries as `Label` and STEP carries as PRODUCT name -- verified identical on
neoracer-full-vehicle (e.g. `CNS_4558_-_M3_X_10_1`, `BS_4168_-_M3_X_40`).

Offline, pure WASM tessellation, no native build.
"""
import os, sys, json, re, struct, zipfile, subprocess, shutil, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from parse_step import Step, apply_point                                 # noqa: E402

# <Property name="Shape" ...><Part ElementMap="0.4" file="Solid046.Shape.brp"/>
SHAPE_FILE = re.compile(r'<Property name="Shape".*?<Part[^>]*\bfile="([^"]+)"', re.S)
LABEL = re.compile(r'<Property name="Label".*?<String value="([^"]*)"', re.S)
OBJECT = re.compile(r'<Object name="([^"]+)"[^>]*>(.*?)</Object>', re.S)


def read_definitions(fcstd, work_dir):
    """[{def, path}] -- one BREP per named component that owns a shape.

    Only objects carrying their own `Shape` are taken. FreeCAD's App::Link and
    App::LinkGroup objects are instances and groupings of those shapes; the STEP
    assembly already tells us where each instance goes, so following FreeCAD's link
    graph as well would be a second, redundant source of placement truth.
    """
    z = zipfile.ZipFile(fcstd)
    doc = z.read('Document.xml').decode('utf-8', 'replace')
    os.makedirs(work_dir, exist_ok=True)
    out, seen = [], set()
    for name, body in OBJECT.findall(doc):
        mf = SHAPE_FILE.search(body)
        if not mf:
            continue
        ml = LABEL.search(body)
        label = ml.group(1) if ml else name
        if label in seen:
            continue
        seen.add(label)
        dest = os.path.join(work_dir, mf.group(1))
        with open(dest, 'wb') as fh:
            fh.write(z.read(mf.group(1)))
        out.append({'def': label, 'path': dest})
    return out


def compose(step_path, local_dir, out_dir):
    """Apply each occurrence's world transform to its definition's local vertices."""
    st = Step(step_path)
    occ = st.occurrences()
    local = json.load(open(os.path.join(local_dir, 'localmesh.json')))
    by_def = {d['def']: d for d in local['defs']}
    raw = open(os.path.join(local_dir, 'localmesh_vert.bin'), 'rb').read()

    parts, chunks, vOff = [], [], 0
    MN, MX = [1e30]*3, [-1e30]*3
    bound = 0
    for i, o in enumerate(occ):
        d = by_def.get(o['defName'])
        if not d:
            continue
        block = raw[d['vOff']: d['vOff'] + d['vCount']*12]
        pts = [struct.unpack_from('<fff', block, k) for k in range(0, len(block), 12)]
        world = [apply_point(o['T'], p) for p in pts]
        fv = struct.pack(f'<{len(world)*3}f', *[c for p in world for c in p])
        chunks.append(fv)
        mn, mx, ctr = [1e30]*3, [-1e30]*3, [0.0]*3
        for p in world:
            for a in range(3):
                mn[a] = min(mn[a], p[a]); mx[a] = max(mx[a], p[a]); ctr[a] += p[a]
        n = len(world)
        ctr = [c/n for c in ctr]
        for a in range(3):
            MN[a] = min(MN[a], mn[a]); MX[a] = max(MX[a], mx[a])
        parts.append({'i': len(parts), 'name': o['defName'], 'parent': o['defName'],
                      'pOff': 0, 'pCount': n, 'nrm': False, 'iOff': 0, 'iCount': 0,
                      'i32': False, 'vOff': vOff, 'vCount': n,
                      'min': [round(v, 4) for v in mn], 'max': [round(v, 4) for v in mx],
                      'centroid': [round(v, 4) for v in ctr],
                      'color': d.get('color', [0.6, 0.6, 0.6]),
                      'occ': o['occId']})
        vOff += len(fv)
        bound += 1

    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, 'mesh_vert.bin'), 'wb') as fh:
        for c in chunks:
            fh.write(c)
    scale = [(MX[a]-MN[a])/65534 if MX[a] > MN[a] else 1.0 for a in range(3)]
    json.dump({'min': MN, 'scale': scale, 'parts': parts},
              open(os.path.join(out_dir, 'mesh.json'), 'w'))
    return {'occurrences': len(occ), 'bound': bound,
            'definitionsWithGeometry': len(by_def),
            'vertices': sum(p['vCount'] for p in parts)}


def main():
    if len(sys.argv) < 3:
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        return 2
    fcstd, step_path = sys.argv[1], sys.argv[2]
    # node runs with cwd=tools/depgraph so `import 'occt-import-js'` resolves against
    # the bundled node_modules; every path handed to it must therefore be absolute.
    out_dir = os.path.abspath(sys.argv[3] if len(sys.argv) > 3 else '.artifacts/depgraph')
    work = os.path.join(out_dir, '_brep')
    t0 = time.time()

    print(f"==> 1/3 extract BREP shapes from {os.path.basename(fcstd)}")
    defs = read_definitions(fcstd, work)
    print(f"    {len(defs)} named components own a shape")
    manifest = os.path.join(out_dir, 'brep-manifest.json')
    json.dump(defs, open(manifest, 'w'))

    print("==> 2/3 tessellate BREP (pure WASM)")
    r = subprocess.run(['node', os.path.join(HERE, 'brep_to_mesh.mjs'), manifest, out_dir],
                       cwd=os.path.join(HERE))
    if r.returncode != 0:
        print("    tessellation failed", file=sys.stderr)
        return r.returncode

    print("==> 3/3 place each occurrence with its STEP world transform")
    info = compose(step_path, out_dir, out_dir)
    shutil.rmtree(work, ignore_errors=True)
    print(f"    definitions with geometry  {info['definitionsWithGeometry']}")
    print(f"    occurrences bound          {info['bound']}/{info['occurrences']}")
    print(f"    world vertices             {info['vertices']}")
    print(f"    {time.time()-t0:.1f} s")
    return 0


if __name__ == '__main__':
    sys.exit(main())
