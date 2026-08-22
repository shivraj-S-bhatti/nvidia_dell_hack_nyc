"""check_factory.py -- verification suite for the Factory verdict harness.

    bash scripts/depgraph-build.sh && python3 tools/factory/check_factory.py

Asserts the properties issue #13 is accepted on: the baseline passes, a visually
plausible candidate fails a real check, repeated runs agree, every failure carries a
number and the parts it implicates, a rejected candidate cannot reach Track, and no
model sits anywhere on the verdict path.

Exits non-zero on any failure so it can gate a build.
"""
import sys, os, json, re, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, 'tools', 'depgraph'))
os.chdir(ROOT)

fail = []


def ck(name, cond, detail=''):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{'  ' + detail if detail else ''}")
    if not cond:
        fail.append(name)


from candidate import ObjectContract, Candidate, CHECK_SET_VERSION      # noqa: E402
from geometry import Assembly                                          # noqa: E402
import verdict as V                                                    # noqa: E402
import checks as C                                                     # noqa: E402
from derive_edges import swept_volume_hits, load_vertex_cache           # noqa: E402

FIX = os.path.join(HERE, 'fixtures')
OUT = os.path.join(ROOT, '.artifacts', 'factory')

print("=== fixtures load ===")
contract = ObjectContract.load(os.path.join(FIX, 'object-contract.json'))
family_raw, cands = Candidate.load_family(os.path.join(FIX, 'candidates.json'))
ck('contract + family load', len(cands) == 6, f'{len(cands)} candidates')
ck('contract pins a step hash', bool(contract.stepSha256))
ck('fixtures are labelled provisional',
   'PROVISIONAL' in family_raw['provenance'] and 'PROVISIONAL' in
   json.load(open(os.path.join(FIX, 'object-contract.json')))['provenance'])

print("=== assembly baseline ===")
asm = Assembly(os.path.join(ROOT, 'S500-C1_ASM.step'), os.path.join(ROOT, '.artifacts', 'depgraph'))
ck('125 occurrences', len(asm.occurrences) == 125, str(len(asm.occurrences)))
ck('52 grip stacks', len(asm.stacks) == 52, str(len(asm.stacks)))
ck('52 fastener sites resolved', len(asm.sites) == 52, str(len(asm.sites)))
ck('every site has an axis and a tip',
   all(s['axis'] and s['tipMm'] is not None for s in asm.sites.values()))
ck('artifact hash matches contract', asm.stepSha256 == contract.stepSha256)

print("=== vertex cache is a decode cache, not a second implementation ===")
site = asm.sites['ARM-S500_ASM/GB70-M2-5-6-DING002']
a_cached = swept_volume_hits(asm.mesh, asm.vert_path, site['org'], site['axis'],
                             site['shankR'], site['tipMm'], site['tipMm'] + 2.0,
                             exclude={site['occId']}, verts=asm.verts)
a_file = swept_volume_hits(asm.mesh, asm.vert_path, site['org'], site['axis'],
                           site['shankR'], site['tipMm'], site['tipMm'] + 2.0,
                           exclude={site['occId']})
ck('cached and file-read sweeps identical', a_cached == a_file,
   f'{len(a_cached)} vs {len(a_file)} hits')

print("=== family verdicts ===")
verdicts, feedback, survivors, run = V.run_family(asm, contract, cands, OUT)
by_id = {v['candidateId']: v for v in verdicts}
ck('one verdict per candidate', len(verdicts) == len(cands))
ck('baseline passes', by_id['baseline']['verdict'] == 'pass',
   by_id['baseline']['reasonCode'])
ck('at least two candidates pass',
   sum(1 for v in verdicts if v['verdict'] == 'pass') >= 2,
   str(sum(1 for v in verdicts if v['verdict'] == 'pass')))
ck('family continues past a failure', len(verdicts) == 6 and
   [v['verdict'] for v in verdicts].count('fail') == 3)

print("=== the real veto: interference ===")
d = by_id['cand-d-standardize-m25']
clr = next(c for c in d['checks'] if c['check'] == 'CLEARANCE')
ck('cand-d fails CLEARANCE', d['verdict'] == 'fail' and clr['status'] == 'fail')
ck('reason code FAC-CLR-001', clr['reasonCode'] == 'FAC-CLR-001')
ck('4 of 28 occurrences collide',
   clr['measured']['collidingOccurrences'] == 4 and clr['measured']['sweptOccurrences'] == 28,
   f"{clr['measured']['collidingOccurrences']}/{clr['measured']['sweptOccurrences']}")
ck('penetration is a positive measured number',
   isinstance(clr['measured']['maxPenetrationMm'], float) and
   clr['measured']['maxPenetrationMm'] > 0,
   f"{clr['measured']['maxPenetrationMm']} mm")
ck('obstruction is named', all(
    h['defName'] == 'NILONGZHU-M3-6'
    for rec in clr['measured']['detail'] for h in rec['intersects']))
ck('the other 24 occurrences are NOT implicated',
   len([o for o in d['affectedOccurrences'] if 'GB70-M2-5-6' in o]) == 4,
   f"{len([o for o in d['affectedOccurrences'] if 'GB70-M2-5-6' in o])} implicated")
ck('every colliding record carries clearance and penetration',
   all(r['clearanceBeforeMm'] > 0 and r['penetrationMm'] > 0 and r['intersects']
       for r in clr['measured']['detail']))

print("=== the second veto: engagement ===")
c3 = by_id['cand-c-plate-2mm-only']
lenr = next(c for c in c3['checks'] if c['check'] == 'FASTENER_LENGTH')
ck('cand-c fails FASTENER_LENGTH', c3['verdict'] == 'fail' and lenr['status'] == 'fail')
ck('reason code FAC-LEN-001', lenr['reasonCode'] == 'FAC-LEN-001')
ck('20 fastener occurrences lose engagement',
   lenr['measured']['engagementLosses'] == 20, str(lenr['measured']['engagementLosses']))
ck('loss equals the declared thickness delta',
   lenr['measured']['worstEngagementDeltaMm'] == -2.0,
   str(lenr['measured']['worstEngagementDeltaMm']))
ck('absolute adequacy still not claimed', 'not claimed' in lenr['tolerance']['note'])

print("=== the third veto: protected interface ===")
e = by_id['cand-e-thicker-tube']
con = next(c for c in e['checks'] if c['check'] == 'CONTRACT')
ck('cand-e fails CONTRACT', e['verdict'] == 'fail' and con['reasonCode'] == 'FAC-CON-003')
ck('geometry checks are unchecked, not passed',
   all(next(c for c in e['checks'] if c['check'] == k)['status'] == 'unchecked'
       for k in ('CLEARANCE', 'FASTENER_LENGTH')))
ck('all 4 tube occurrences implicated', len(e['affectedOccurrences']) == 4)

print("=== nothing passes silently ===")
for v in verdicts:
    for c in v['checks']:
        if c['status'] == 'pass' and c['check'] == 'CLEARANCE':
            has_thickness = any(o.get('op') == 'thickness' for o in v['ops'])
            ck(f"{v['candidateId']}: clearance pass declares its unchecked thickness ops"
               if has_thickness else f"{v['candidateId']}: clearance pass states its limits",
               bool(c['measured'].get('unchecked')) if has_thickness
               else 'not proof of clearance' in c['tolerance'].get('note', ''))
ck('every failure implicates real occurrences',
   all(v['affectedOccurrences'] and
       all(o in asm.by_id for o in v['affectedOccurrences'])
       for v in verdicts if v['verdict'] == 'fail'))
ck('every failure cites the tolerance it broke',
   all(next(c for c in v['checks'] if c['status'] == 'fail')['tolerance']
       for v in verdicts if v['verdict'] == 'fail'))
# A geometric rejection that cannot show a number is an opinion. A contract rejection
# is categorical -- it cites a declared rule -- so it is held to the rule, not a
# measurement.
_geo = [v for v in verdicts if v['verdict'] == 'fail'
        and v['failedChecks'][0] in ('CLEARANCE', 'FASTENER_LENGTH')]
ck('every geometric failure carries a numeric measurement', _geo and all(
    any(isinstance(x, (int, float)) and not isinstance(x, bool) for x in
        next(c for c in v['checks'] if c['status'] == 'fail')['measured'].values())
    for v in _geo), f'{len(_geo)} geometric rejections')
ck('contract failures cite a declared rule and count violations', all(
    next(c for c in v['checks'] if c['status'] == 'fail')['measured'].get('violationCount', 0) > 0
    for v in verdicts if v['verdict'] == 'fail' and v['failedChecks'][0] == 'CONTRACT'))
ck('every check result carries a reason code',
   all(re.match(r'^FAC-[A-Z]{3}-[U0-9]\d{2}$', c['reasonCode'])
       for v in verdicts for c in v['checks']),
   sorted({c['reasonCode'] for v in verdicts for c in v['checks']})[0])
ck('check set declares what it does not check', len(C.NOT_CHECKED) >= 5)

print("=== a rejected candidate cannot reach Track ===")
sv = {s['candidateId'] for s in survivors['survivors']}
rj = {r['candidateId'] for r in survivors['rejected']}
ck('survivors are exactly the passing candidates',
   sv == {v['candidateId'] for v in verdicts if v['verdict'] == 'pass'}, str(sorted(sv)))
ck('no rejected id appears in the Track input', not (sv & rj), str(sorted(sv & rj)))
ck('rejections stay visible', rj == {'cand-c-plate-2mm-only', 'cand-d-standardize-m25',
                                     'cand-e-thicker-tube'})

print("=== feedback to lab ===")
fb = {f['candidateId']: f for f in feedback}
ck('one feedback event per rejection', len(feedback) == 3)
ck('clearance feedback carries a growth ceiling',
   fb['cand-d-standardize-m25']['constraint']['kind'] == 'max-fastener-growth' and
   fb['cand-d-standardize-m25']['constraint']['perDefinition']
   ['GB70-M2-5-6-DING']['maxGrowthMm'] > 0,
   str(fb['cand-d-standardize-m25']['constraint']['perDefinition']
       ['GB70-M2-5-6-DING']['maxGrowthMm']) + ' mm')
ck('length feedback carries a minimum increase',
   fb['cand-c-plate-2mm-only']['constraint']['kind'] == 'min-fastener-length-increase')
ck('feedback implicates parts', all(f['implicatedOccurrences'] and f['implicatedDefinitions']
                                    for f in feedback))
ck('factory does not revise the design',
   all('does not revise' in f['note'] for f in feedback))

print("=== repeatability ===")
digests = [V.digest(V.run_family(asm, contract, cands, OUT)[0]) for _ in range(3)]
ck('3/3 in-process runs agree', len(set(digests)) == 1, digests[0])
r = subprocess.run([sys.executable, os.path.join(HERE, 'validate.py'), '--json'],
                   capture_output=True, text=True)
ck('separate process exits 0', r.returncode == 0, r.stderr[-200:] if r.returncode else '')
try:
    ck('separate process agrees', json.loads(r.stdout)['verdictDigests'][0] == digests[0])
except Exception as ex:
    ck('separate process agrees', False, repr(ex))

print("=== replay from saved evidence ===")
replay = [json.load(open(os.path.join(OUT, 'verdicts', f'{c.id}.json'))) for c in cands]
ck('saved verdicts reproduce the digest', V.digest(replay) == digests[0])
ck('every verdict names its own evidence path',
   all(os.path.exists(v['evidencePath']) for v in verdicts))
ck('run record has timing and peak RSS',
   run['elapsedMs'] > 0 and run['peakRssMb'] > 0,
   f"{run['elapsedMs']:.0f} ms, {run['peakRssMb']} MB")

print("=== malformed candidates are verdicts, not crashes ===")
bad = Candidate({'candidateId': 'bad-unknown-target', 'ops': [
    {'op': 'thickness', 'target': 'NO-SUCH-PART', 'deltaMm': 1.0}]})
vb = V.evaluate(asm, contract, bad, OUT)
ck('unknown target -> FAC-CON-002', vb['verdict'] == 'fail' and
   vb['reasonCode'] == 'FAC-CON-002', vb['reasonCode'])
bad2 = Candidate({'candidateId': 'bad-unknown-op', 'ops': [
    {'op': 'teleport', 'target': 'BOTTOM-PLATE-S500'}]})
v2 = V.evaluate(asm, contract, bad2, OUT)
ck('op outside the vocabulary -> FAC-CON-004', v2['reasonCode'] == 'FAC-CON-004')
bad3 = Candidate({'ops': 'not-a-list'})
v3 = V.evaluate(asm, contract, bad3, OUT)
ck('malformed ops -> FAC-CON-001 not an exception', v3['reasonCode'] == 'FAC-CON-001')
ck('blocked candidates never report a geometry pass',
   all(next(c for c in v['checks'] if c['check'] == 'CLEARANCE')['status'] == 'unchecked'
       for v in (vb, v2, v3)))

print("=== no model on the verdict path ===")
srcs = ([os.path.join(HERE, f) for f in os.listdir(HERE) if f.endswith('.py')] +
        [os.path.join(ROOT, 'tools', 'depgraph', f)
         for f in os.listdir(os.path.join(ROOT, 'tools', 'depgraph')) if f.endswith('.py')])
banned = re.compile(r'^\s*(?:import|from)\s+(openai|anthropic|requests|urllib|http|'
                    r'socket|torch|transformers|ollama|llama_cpp|httpx|aiohttp)\b', re.M)
offenders = [os.path.relpath(p, ROOT) for p in srcs if banned.search(open(p).read())]
ck('no model or network import anywhere on the path', not offenders, str(offenders))

print()
print('ALL CHECKS PASSED' if not fail else f'{len(fail)} FAILURES: ' + ', '.join(fail))
sys.exit(1 if fail else 0)
