"""parse_step.py -- STEP AP203/AP214/AP242 -> occurrence graph + geometric features.

Pure Python standard library. No OpenCascade, no FreeCAD, no native build, so this
runs unchanged on the ARM64 GB10. It is the authoritative source for the assembly
tree: occurrences, composed world transforms, and cylindrical features.

Verified against S500-C1_ASM.step: 38 definitions, 125 occurrences,
125 ITEM_DEFINED_TRANSFORMATION, 885 CYLINDRICAL_SURFACE.
"""
import re, math, sys, collections

IDENT = ([[1,0,0],[0,1,0],[0,0,1]], [0,0,0])


def mul(A, B):
    Ra, ta = A; Rb, tb = B
    return ([[sum(Ra[i][k]*Rb[k][j] for k in range(3)) for j in range(3)] for i in range(3)],
            [sum(Ra[i][k]*tb[k] for k in range(3)) + ta[i] for i in range(3)])


def inv(A):
    R, t = A
    Ri = [[R[j][i] for j in range(3)] for i in range(3)]
    return (Ri, [-sum(Ri[i][k]*t[k] for k in range(3)) for i in range(3)])


def apply_point(A, v):
    R, t = A
    return [sum(R[i][k]*v[k] for k in range(3)) + t[i] for i in range(3)]


def apply_dir(A, v):
    R, _ = A
    return [sum(R[i][k]*v[k] for k in range(3)) for i in range(3)]


def unit(v):
    m = math.sqrt(sum(c*c for c in v)) or 1.0
    return [c/m for c in v]


class Step:
    def __init__(self, path):
        src = re.sub(r'\s*\n\s*', ' ', open(path, encoding='utf-8', errors='replace').read())
        self.ents = {}
        for m in re.finditer(r'#(\d+)\s*=\s*(.*?);', src):
            body = m.group(2).strip()
            mm = re.match(r'([A-Z_0-9]+)\s*\((.*)\)$', body, re.S)
            # AP214 uses complex-entity syntax: #N = ( TYPE_A(..) TYPE_B(..) ).
            # A parser that only matches NAME(...) silently drops these, which is
            # exactly where assembly placements live.
            self.ents[int(m.group(1))] = (mm.group(1), mm.group(2)) if mm else ('COMPLEX', body)
        self._index()

    def refs(self, a):
        return [int(x) for x in re.findall(r'#(\d+)', a)]

    def vec(self, i):
        a = self.ents[i][1]
        m = re.search(r'\(([-0-9.E+\-, ]+)\)\s*$', a)
        return [float(x) for x in m.group(1).split(',')]

    def _index(self):
        E, R = self.ents, self.refs
        self.prod = {i: a.split("'")[1] for i, (t, a) in E.items() if t == 'PRODUCT'}
        self.pdf  = {i: R(a)[-1] for i, (t, a) in E.items() if t == 'PRODUCT_DEFINITION_FORMATION'}
        self.pd   = {i: R(a)[0]  for i, (t, a) in E.items() if t == 'PRODUCT_DEFINITION'}
        self.pds  = {i: R(a)[-1] for i, (t, a) in E.items() if t == 'PRODUCT_DEFINITION_SHAPE'}
        self.rep2prod = {}
        for i, (t, a) in E.items():
            if t == 'SHAPE_DEFINITION_REPRESENTATION':
                r = R(a)
                self.rep2prod[r[1]] = self.def_name(self.pds.get(r[0]))

    def def_name(self, pd_id):
        return self.prod.get(self.pdf.get(self.pd.get(pd_id, -1), -1), '?')

    def axis(self, ap):
        r = self.refs(self.ents[ap][1])
        o = self.vec(r[0])
        z = unit(self.vec(r[1])) if len(r) > 1 else [0, 0, 1]
        x = unit(self.vec(r[2])) if len(r) > 2 else [1, 0, 0]
        d = sum(x[k]*z[k] for k in range(3))
        x = unit([x[k] - d*z[k] for k in range(3)])
        y = [z[1]*x[2]-z[2]*x[1], z[2]*x[0]-z[0]*x[2], z[0]*x[1]-z[1]*x[0]]
        return ([[x[0], y[0], z[0]], [x[1], y[1], z[1]], [x[2], y[2], z[2]]], o)

    def occurrences(self):
        """Occurrence tree with composed world transforms.

        Placement convention is A2 * inv(A1), where ITEM_DEFINED_TRANSFORMATION
        carries (transform_item_1 in the component frame, transform_item_2 in the
        parent frame). This was selected by testing all four candidate conventions
        against OCC's own world coordinates -- see docs/research/depgraph-context.md.
        """
        E, R = self.ents, self.refs
        nauo = {}
        for i, (t, a) in E.items():
            if t == 'NEXT_ASSEMBLY_USAGE_OCCURRENCE':
                p = a.split("'"); r = R(a)
                nauo[i] = {'occ': p[3], 'parent': r[0], 'child': r[1]}
        for i, (t, a) in E.items():
            if t != 'CONTEXT_DEPENDENT_SHAPE_REPRESENTATION':
                continue
            r = R(a)
            if len(r) < 2 or r[0] not in E:
                continue
            tgt = R(E[r[1]][1])
            if not tgt or tgt[0] not in nauo:
                continue
            idt = [x for x in R(E[r[0]][1]) if E.get(x, ('', ''))[0] == 'ITEM_DEFINED_TRANSFORMATION']
            if not idt:
                continue
            ax = R(E[idt[0]][1])
            nauo[tgt[0]]['T'] = mul(self.axis(ax[1]), inv(self.axis(ax[0])))

        kids = collections.defaultdict(list)
        for n, d in nauo.items():
            kids[d['parent']].append(n)
        roots = set(d['parent'] for d in nauo.values()) - set(d['child'] for d in nauo.values())

        out = []
        def walk(pdid, path, T):
            for n in sorted(kids.get(pdid, []), key=lambda x: nauo[x]['occ']):
                d = nauo[n]
                Tn = mul(T, d.get('T', IDENT))
                out.append({'occId': '/'.join(path + [d['occ']]), 'occName': d['occ'],
                            'defName': self.def_name(d['child']),
                            'parentOcc': path[-1] if path else None, 'T': Tn})
                walk(d['child'], path + [d['occ']], Tn)
        for r in roots:
            walk(r, [], IDENT)
        return out

    def cylinders_by_definition(self):
        """radius, axis origin, axis direction -- in each definition's local frame."""
        def collect(i, seen, out):
            if i in seen:
                return
            seen.add(i)
            t, a = self.ents.get(i, (None, ''))
            if t is None:
                return
            if t == 'CYLINDRICAL_SURFACE':
                rad = float(a.rsplit(',', 1)[1])
                r = self.refs(self.ents[self.refs(a)[0]][1])
                out.append((round(rad, 4), self.vec(r[0]),
                            self.vec(r[1]) if len(r) > 1 else [0, 0, 1]))
                return
            for x in self.refs(a):
                collect(x, seen, out)
        sys.setrecursionlimit(300000)
        res = {}
        for rep, name in self.rep2prod.items():
            if name in res:
                continue
            out = []
            collect(rep, set(), out)
            res[name] = out
        return res
