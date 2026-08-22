"""check.py -- verification suite for the depgraph pipeline.

    bash scripts/depgraph-build.sh && python3 tools/depgraph/check.py

Asserts the invariants that must not silently drift: parser counts, geometric
fastener classification (recall AND false positives), edge/grip derivation, the
no-mesh fallback path, action arithmetic, stock ladder precedence, CLI contracts,
and that the viewer fetches nothing over the network.

Exits non-zero on any failure so it can gate a build.
"""
import sys, json, subprocess, os, re
sys.path.insert(0,'tools/depgraph')
fail=[]
def ck(name, cond, detail=''):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{'  '+detail if detail else ''}")
    if not cond: fail.append(name)

from parse_step import Step
from derive_edges import classify_fasteners, FASTENERS, derive, actions_for_thickness_change, next_stock, swept_volume_hits

print("=== parser invariants ===")
st=Step('S500-C1_ASM.step'); occ=st.occurrences(); cyl=st.cylinders_by_definition()
ck('125 occurrences', len(occ)==125, str(len(occ)))
ck('885 cylinders', sum(len(v) for v in cyl.values())==885)
ck('28 GB70-M2-5-6-DING', sum(1 for o in occ if o['defName']=='GB70-M2-5-6-DING')==28)

print("=== classifier ===")
auto=classify_fasteners(cyl)
ck('6/6 recall, 0 FP', set(auto)==set(FASTENERS), f"{len(auto)} found")
ck('empty input safe', classify_fasteners({})=={} and classify_fasteners(None)=={})
ck('overrides applied', classify_fasteners(cyl, overrides={'ZZZ':{'M':9.9}}).get('ZZZ',{}).get('M')==9.9)

print("=== derive + grip ===")
mesh=json.load(open('.artifacts/depgraph/mesh.json'))
edges,stacks=derive(occ,cyl,mesh,'.artifacts/depgraph/mesh_vert.bin')
ck('72 FASTENS edges', len(edges)==72, str(len(edges)))
ck('52 grip stacks', len(stacks)==52, str(len(stacks)))
ck('all stacks have grip', all(s['gripMm'] is not None for s in stacks.values()))
ck('all stacks have nominal length', all(s['nominalLengthMm'] is not None for s in stacks.values()))
ck('adequacy never asserted', all(s['adequate'] is None for s in stacks.values()))
ck('every edge has reason+tolerance', all(e.get('reason') and 'axisOffsetMm' in e for e in edges))

print("=== derive WITHOUT mesh (fallback path) ===")
e2,s2=derive(occ,cyl)
ck('no-mesh derive does not crash', len(e2)==72)
ck('no-mesh stacks have null grip', all(x['gripMm'] is None for x in s2.values()))
try:
    a=actions_for_thickness_change(s2,'BOTTOM-PLATE-S500',1.0)
    ck('actions on null-grip stacks safe', a==[], f"{len(a)} actions")
except Exception as ex:
    ck('actions on null-grip stacks safe', False, repr(ex))

print("=== actions ===")
acts=actions_for_thickness_change(stacks,'BOTTOM-PLATE-S500',1.0)
ck('20 fasteners clamp bottom plate', len(acts)==20, str(len(acts)))
ck('all actions have recommendation', all(x['recommendedLengthMm'] for x in acts))
def action_target(action):
    match=re.search(r'-> M[0-9.]+x([0-9.]+)$', action)
    return float(match.group(1)) if match else None
ck('action target matches recommendation',
   all(action_target(x['action'])==x['recommendedLengthMm'] for x in acts))
ck('relative requirement preserves current engagement',
   all(x['requiredLengthMm']==x['currentLengthMm']+1.0 for x in acts))
neg=actions_for_thickness_change(stacks,'BOTTOM-PLATE-S500',-1.0)
ck('negative delta -> no lengthening', all(x['stillAdequate'] for x in neg))
ck('unknown part -> no actions', actions_for_thickness_change(stacks,'NOPE',1.0)==[])

print("=== stock ladder ===")
ck('ISO fallback M3', next_stock(3.0,9.0)==10, str(next_stock(3.0,9.0)))
ck('M2.5 gains 30', next_stock(2.5,26)==30)
ck('beyond ladder -> None', next_stock(3.0,999) is None)

print("=== swept volume ===")
h=swept_volume_hits(mesh,'.artifacts/depgraph/mesh_vert.bin',[0,0,0],[0,1,0],2.0,-5,5)
ck('swept volume returns list', isinstance(h,list))

print("=== work_order CLI ===")
r=subprocess.run([sys.executable,'tools/depgraph/work_order.py','BOTTOM-PLATE-S500','--thicker','1.0','--json'],capture_output=True,text=True)
ck('CLI --json exits 0', r.returncode==0, r.stderr[-200:] if r.returncode else '')
try:
    j=json.loads(r.stdout); ck('CLI emits valid JSON', j['anchorOccurrences']==1 and len(j['lengthActions'])==20)
except Exception as ex: ck('CLI emits valid JSON', False, repr(ex))
r2=subprocess.run([sys.executable,'tools/depgraph/work_order.py','DOES-NOT-EXIST'],capture_output=True,text=True)
ck('unknown part exits nonzero', r2.returncode==2)

print("=== viewer ===")
html=open('s500-impact.html').read()
ck('viewer has title', '<title>' in html)
import re as _re
_ext={u for u in _re.findall(r'https?://[^\s"\')]+', html) if not u.startswith('http://127.0.0.1')}
_net={u for u in _ext if 'w3.org' not in u and 'jcgt.org' not in u}
ck('no network-fetching URLs', not _net, str(sorted(_net)[:3]))
ck('fonts inlined (offline-identical)', html.count('@font-face')>=5, str(html.count('@font-face')))
ck('teammate PR34 preview retained', 'preview' in open('tools/depgraph/viewer/app.js').read().lower())
print()
print(('ALL CHECKS PASSED' if not fail else f'{len(fail)} FAILURES: '+', '.join(fail)))
sys.exit(1 if fail else 0)
