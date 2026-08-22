"""check.py -- verification suite for the Track stage (issue #14).

    bash scripts/depgraph-build.sh && python3 tools/track/check.py

Every acceptance criterion in issue #14 has an assertion here:

  * Factory-rejected candidates cannot enter Track -- proved by exercising the
    guard AND by two adversarial manifests that try to get round it.
  * The baseline and every survivor use the same fixture and score definition.
  * At least one survivor performs worse than baseline and stays visible.
  * At least one survivor improves the metric / meets the displayed target.
  * Repeated runs agree within the declared tolerance.
  * Elapsed time is measured and the host is recorded.
  * One Track result goes back to Lab as actionable feedback.

Plus the two things the numbers rest on: the solver is validated against closed
forms, and no displayed claim escapes what the fixture actually measures.

Exits non-zero on any failure so it can gate a build. Writes nothing into the
repo -- every artifact it builds lives in a temp directory that is removed.
"""
import copy
import json
import os
import re
import shutil
import sys
import tempfile

import numpy as np

sys.path.insert(0, 'tools/track')
fail = []


def ck(name, cond, detail=''):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{'  '+str(detail) if detail else ''}")
    if not cond:
        fail.append(name)


def raises(exc, fn, *a, **kw):
    """(ok, detail) -- fn must raise exc. Reports what happened instead."""
    try:
        fn(*a, **kw)
    except exc as e:
        return True, f"{type(e).__name__}: {str(e).splitlines()[0][:96]}"
    except Exception as e:                                   # noqa: BLE001
        return False, f"wrong exception {type(e).__name__}: {str(e)[:80]}"
    return False, f"no exception raised (expected {exc.__name__})"


def summary_and_exit():
    print()
    print('ALL CHECKS PASSED' if not fail else f'{len(fail)} FAILURES: ' + ', '.join(fail))
    sys.exit(1 if fail else 0)


import candidates                                            # noqa: E402
import domain                                                # noqa: E402
import evaluate                                              # noqa: E402
import fea                                                   # noqa: E402
import fixture as fixture_mod                                # noqa: E402
import manifest as mf                                        # noqa: E402

TMP = tempfile.mkdtemp(prefix='track-check-')

print("=== solver validation ===")
cant = fea.validate_cantilever()
cant_err = abs(cant['relative_error_vs_timoshenko'])
ck('cantilever within 1% of Timoshenko', cant_err < 0.01,
   "%+.4f %% (%dx%d elements)" % (cant['relative_error_vs_timoshenko'] * 100,
                                  cant['nelx'], cant['nely']))
sym = fea.validate_symmetry()
ck('mirrored fixture reproduces compliance', sym < 1e-10, '%.3e relative difference' % sym)
patch = fea.validate_rigid_body()
ck('uniaxial patch test reproduces uniform strain', patch < 1e-10, '%.3e relative error' % patch)

k0 = fea.element_stiffness(0.8, 0.9, 2.0, 70000.0, 0.30)
ck('element stiffness is exactly symmetric', bool(np.array_equal(k0, k0.T)))
eig = np.linalg.eigvalsh(k0)
nzero = int((np.abs(eig) <= 1e-9 * np.abs(eig).max()).sum())
ck('element stiffness has exactly 3 rigid-body modes', nzero == 3,
   '%d zero eigenvalues, smallest non-zero %.4g' % (nzero, sorted(np.abs(eig))[3]))

# Energy consistency on the real fixture geometry, not a toy grid: the assembly,
# the SIMP interpolation and the reduction all have to agree for this to hold.
fx = fixture_mod.build()
base_mask = domain.occupancy(fx.baseline_coverage, fx.params['coverageThreshold'])
_r = fea.solve(base_mask, fx.hx, fx.hy, fx.params['thicknessMm'],
               fx.params['youngsModulusMPa'], fx.params['poissonRatio'],
               fx.fixed_dofs, fx.loads_for('+x'),
               penal=fx.params['penal'], void_ratio=fx.params['voidRatio'])
e_rel = abs(float(_r.element_energy.sum()) - _r.compliance) / abs(_r.compliance)
ck('sum(element_energy) == compliance on a real solve', e_rel < 1e-9,
   '%.2e relative, compliance %.6g N*mm over %d free DOF' % (e_rel, _r.compliance, _r.n_free))
ck('real solve is finite', _r.finite)

print("=== fixture is frozen and grounded ===")
fx2 = fixture_mod.build()
ck('build() is deterministic (identical hash)', fx.hash() == fx2.hash(), fx.hash()[:26])
for key, value in (('nelx', 241), ('youngsModulusMPa', 71000.0),
                   ('loadTotalN', 110.0), ('supportRadiusMm', 6.5)):
    h = fixture_mod.build(overrides={key: value}).hash()
    ck('hash changes when %s changes' % key, h != fx.hash(), h[:26])
ok, d = raises(fixture_mod.FixtureError, fixture_mod.build, overrides={'nolan': 1})
ck('unknown override key rejected', ok, d)

ck('4 arm-mount clusters', len(fx.clusters) == 4, str(len(fx.clusters)))
corners = sorted((round(c['x'], 3), round(c['z'], 3)) for c in fx.clusters)
ck('clusters at (+/-45.07, +/-45.07) mm within 0.1 mm',
   len(fx.clusters) == 4
   and all(abs(abs(c['x']) - 45.07) <= 0.1 and abs(abs(c['z']) - 45.07) <= 0.1
           for c in fx.clusters)
   and len({(np.sign(c['x']), np.sign(c['z'])) for c in fx.clusters}) == 4,
   str(corners))
ck('8 ARM-S500_ASM fasteners out of 20 that fasten the plate',
   fx.params['supportBoltCount'] == 8 and fx.params['plateFastenerCount'] == 20
   and all(b['occId'].startswith('ARM-S500_ASM') for b in fx.bolts),
   '%s of %s, defs %s' % (fx.params['supportBoltCount'], fx.params['plateFastenerCount'],
                          sorted({b['defName'] for b in fx.bolts})))
backed = fixture_mod.nodes_on_material(base_mask)
ck('every fixed DOF sits on baseline material',
   bool(backed[np.unique(fx.fixed_dofs // 2)].all()),
   '%d DOF over %d nodes' % (fx.fixed_dofs.size, np.unique(fx.fixed_dofs // 2).size))
load_nodes = np.unique(np.concatenate([np.asarray(c['dofs'], dtype=np.int64) // 2
                                       for c in fx.load_cases]))
ck('every loaded node sits on baseline material', bool(backed[load_nodes].all()),
   '%d nodes, %d load cases' % (load_nodes.size, len(fx.load_cases)))

print("=== the Factory gate ===")
GATE = os.path.join(TMP, 'gate')
doc, man_path = candidates.stand_in_manifest(fx, GATE, 'track-check-gate')
man = mf.load_manifest(man_path)
rej_ids = sorted(man.rejected_ids)
rid = rej_ids[0] if rej_ids else '<none>'

ck('manifest contains at least one rejected candidate', len(doc['rejected']) >= 1,
   ', '.join(rej_ids))
r0 = doc['rejected'][0] if doc['rejected'] else {}
ck('rejection carries a real reason code and measured value',
   bool(re.match(r'^[A-Z][A-Z0-9]*\.[A-Z0-9_]+$', str(r0.get('reasonCode', ''))))
   and isinstance(r0.get('measured'), float) and isinstance(r0.get('tolerance'), float)
   and r0['measured'] < r0['tolerance'],
   '%s measured %s / %s %s' % (r0.get('reasonCode'), r0.get('measured'),
                               r0.get('tolerance'), r0.get('units')))
ok, d = raises(mf.RejectedCandidateError, man.assert_admissible, rid)
ck('assert_admissible raises RejectedCandidateError for a rejected id', ok, d)
ok, d = raises(mf.ManifestError, man.assert_admissible, 'cand-not-in-this-run')
ck('assert_admissible raises ManifestError for an unknown id', ok, d)
ok, d = raises(mf.RejectedCandidateError, man.entry, rid)
ck('entry() raises for a rejected id', ok, d)
ok, d = raises(mf.RejectedCandidateError, man.mask, rid)
ck('mask() raises for a rejected id', ok, d)
ck('rejected id is absent from all_entries()',
   rid not in [e.candidate_id for e in man.all_entries()],
   ', '.join(e.candidate_id for e in man.all_entries()))

# ADVERSARIAL 1 -- launder a rejected candidate into `survivors` while leaving it
# in `rejected`, pointing at its own real geometry with a correct sha256.
laundered = copy.deepcopy(doc)
victim = laundered['rejected'][0]
vmask = os.path.join(GATE, victim['evidencePath'])
laundered['survivors'].append({
    'candidateId': victim['candidateId'], 'parentId': 'baseline', 'verdict': 'pass',
    'mask': {'path': victim['evidencePath'], 'format': 'npy',
             'sha256': mf.sha256_file(vmask), 'shape': [fx.nely, fx.nelx]},
    'evidencePath': None, 'factoryChecks': [], 'notes': 'laundered by check.py'})
lpath = os.path.join(GATE, 'laundered.json')
with open(lpath, 'w') as fh:
    json.dump(laundered, fh)                       # bypass dump_manifest's validation
ok, d = raises(mf.ManifestError, mf.load_manifest, lpath)
ck('ADVERSARIAL: rejected id cannot launder itself into survivors', ok, d)

# ADVERSARIAL 2 -- swap the rejected candidate's geometry in under a survivor's
# name, after the manifest was written.
SWAP = os.path.join(TMP, 'swap')
shutil.copytree(GATE, SWAP)
swap_victim = doc['survivors'][0]['candidateId']
shutil.copyfile(os.path.join(SWAP, victim['evidencePath']),
                os.path.join(SWAP, doc['survivors'][0]['mask']['path']))
man_swap = mf.load_manifest(os.path.join(SWAP, 'survivors.json'))
ok, d = raises(mf.MaskIntegrityError, man_swap.mask, swap_victim)
ck('ADVERSARIAL: swapped mask bytes raise MaskIntegrityError', ok, d)

# The full run: the gate has to hold end to end, not just at the unit level.
RUN = os.path.join(TMP, 'run')
report = None
try:
    rc = evaluate.main(['--output-root', RUN, '--run-id', 'track-check-1',
                        '--repeat', '2', '--quiet'])
    with open(os.path.join(RUN, 'track-report.json')) as fh:
        report = json.load(fh)
    ck('evaluate.main exits 0 and writes a report', rc == 0 and report is not None)
except Exception as e:                                        # noqa: BLE001
    ck('evaluate.main exits 0 and writes a report', False, f'{type(e).__name__}: {e}')
if report is None:
    shutil.rmtree(TMP, ignore_errors=True)
    summary_and_exit()

gate = report['gate']
ck('rejected id appears in report gate.rejectedIds', rid in gate['rejectedIds'],
   str(gate['rejectedIds']))
ck('rejected id is NOT in gate.evaluatedIds', rid not in gate['evaluatedIds'],
   str(gate['evaluatedIds']))
ck('gate.rejectedEvaluated is empty', gate['rejectedEvaluated'] == [],
   str(gate['rejectedEvaluated']))
ck('the veto stays visible with its reason code',
   any(r['candidateId'] == rid and r['reasonCode'] and r['measured'] is not None
       for r in gate['rejected']))

print("=== one fixture for everyone ===")
hashes = {r['fixtureHash'] for r in report['results']}
ck('every result carries one fixture hash', len(hashes) == 1, str(sorted(hashes))[:60])
ck('that hash is fixture.hash()', hashes == {fx.hash()}, fx.hash()[:26])
ck('every result carries the same metric definition',
   {r['metric'] for r in report['results']} == {evaluate.METRIC})


def _fake(cid, h, role='survivor', ss=1.0):
    return {'candidateId': cid, 'fixtureHash': h, 'role': role,
            'measures': {'state': 'ok'},
            'relative': {'specificStiffnessRatio': ss, 'materialRatioToBaseline': 1.0,
                         'complianceRatioToBaseline': 1.0}}


mixed = [_fake('base', 'sha256:' + 'a' * 64, 'baseline'), _fake('x', 'sha256:' + 'b' * 64)]
ok, d = raises(ValueError, evaluate.rank, mixed)
ck('rank() refuses results from two different fixtures', ok, d)
same = [_fake('base', 'sha256:' + 'a' * 64, 'baseline'), _fake('x', 'sha256:' + 'a' * 64)]
ck('rank() accepts one fixture (control)', [r['candidateId'] for r in evaluate.rank(same)] == ['x'])

# A manifest compiled against a different grid must not be scored on this fixture.
SMALL = os.path.join(TMP, 'small')
os.makedirs(os.path.join(SMALL, 'masks'), exist_ok=True)
sref = mf.write_mask(np.ones((4, 6), np.uint8),
                     os.path.join(SMALL, 'masks', 'baseline.npy'), rel_to=SMALL)
small_doc = {
    'schemaVersion': mf.SCHEMA_VERSION, 'runId': 'wrong-domain',
    'producedBy': 'track-check', 'problemId': fx.params['fixtureId'],
    'problemHash': fx.hash(), 'domainShape': [4, 6], 'units': 'mm',
    'baseline': {'candidateId': 'baseline', 'parentId': None, 'verdict': 'pass',
                 'mask': sref.to_json(), 'evidencePath': None,
                 'factoryChecks': [], 'notes': None},
    'survivors': [], 'rejected': []}
mf.dump_manifest(small_doc, os.path.join(SMALL, 'survivors.json'))
man_small = mf.load_manifest(os.path.join(SMALL, 'survivors.json'), require_survivors=False)
ok, d = raises(ValueError, evaluate.run, fx, man_small, 'wrong-domain')
ck('run() refuses a manifest whose domainShape is not the fixture grid', ok, d)

print("=== measured outcomes required by #14 ===")
survivors = [r for r in report['results'] if r['role'] == 'survivor']
base = report['baseline']
ranked_ids = [r['candidateId'] for r in report['ranking']]
better = [r for r in survivors if r['relative']['specificStiffnessRatio'] > 1.0]
worse = [r for r in survivors if r['relative']['specificStiffnessRatio'] < 1.0]
ck('at least one survivor improves the metric (ratio > 1.0)', bool(better),
   ', '.join('%s %.3f' % (r['candidateId'], r['relative']['specificStiffnessRatio'])
             for r in better))
ck('at least one survivor is worse than baseline (ratio < 1.0)', bool(worse),
   ', '.join('%s %.3f' % (r['candidateId'], r['relative']['specificStiffnessRatio'])
             for r in worse))
ck('the worse survivor stays visible in the ranking',
   bool(worse) and all(r['candidateId'] in ranked_ids for r in worse),
   'ranking: ' + ', '.join(ranked_ids))
met = [r for r in survivors if r['meetsTarget'] is True]
ck('at least one survivor meets the displayed target', bool(met),
   ', '.join(r['candidateId'] for r in met) + '  target %s' % report['target'])
ck('baseline state is ok', base['measures']['state'] == 'ok', base['measures']['state'])
ck('baseline ratios are exactly 1.0',
   base['relative']['complianceRatioToBaseline'] == 1.0
   and base['relative']['materialRatioToBaseline'] == 1.0
   and base['relative']['specificStiffnessRatio'] == 1.0,
   str(base['relative']))
ck('every survivor solved to a usable state',
   all(r['measures']['state'] == 'ok' for r in survivors),
   ', '.join(sorted({r['measures']['state'] for r in survivors})))

again = [r['candidateId'] for r in evaluate.rank(copy.deepcopy(report['results']))]
ck('rank() is a strict deterministic order', again == ranked_ids and len(set(again)) == len(again),
   ' -> '.join(again))
ck('ranks are 1..n with no gaps',
   [r['rank'] for r in report['ranking']] == list(range(1, len(ranked_ids) + 1)))

fb = report.get('feedbackToLab') or {}
sids = {r['candidateId'] for r in survivors}
ck('feedbackToLab is present', isinstance(fb, dict) and bool(fb))
ck('feedback names a real survivor', fb.get('candidateId') in sids, fb.get('candidateId'))
cmpb = fb.get('comparedToBestSurvivor') or {}
ck('feedback compares against a different real survivor',
   cmpb.get('candidateId') in sids and cmpb.get('candidateId') != fb.get('candidateId'),
   '%s vs %s' % (fb.get('candidateId'), cmpb.get('candidateId')))
diag = fb.get('removalDiagnosis') or {}
ck('feedback carries an actionable recommendation and measured evidence',
   len(fb.get('recommendation', '')) > 80
   and (fb.get('measured') or {}).get('specificStiffnessRatio', 2.0) < 1.0
   and diag.get('massFractionRemoved', 0) > 0,
   'removed %s%% of mass carrying %s%% of strain energy'
   % (round(100 * diag.get('massFractionRemoved', 0), 1),
      round(100 * diag.get('strainEnergyFractionRemoved', 0), 1)))
ck('feedback-event.json written alongside the report',
   os.path.isfile(os.path.join(RUN, 'feedback-event.json')))
tim = report['timing']
ck('elapsed time is measured, not asserted',
   tim['evaluationWallSeconds'] > 0 and tim['totalWallSeconds'] > 0
   and all(r['timing']['solveSeconds'] > 0 for r in report['results']),
   'evaluate %.2fs, total %.2fs, peak RSS %.0f MB'
   % (tim['evaluationWallSeconds'], tim['totalWallSeconds'], tim['peakRssMb']))
ck('host is recorded for the elapsed-time claim',
   bool(report['host']['machine']) and bool(report['host']['platform']),
   '%s / %s' % (report['host']['machine'], report['host']['python']))

print("=== repeatability ===")
rep = report.get('repeatability') or {}
ck('the evaluation ran more than once', rep.get('runs', 0) >= 2, '%s runs' % rep.get('runs'))
ck('every displayed measure agrees within REPEAT_TOLERANCE',
   rep.get('maxRelativeSpread', 1.0) <= evaluate.REPEAT_TOLERANCE and rep.get('withinTolerance'),
   'max relative spread %.3g on %s (declared tolerance %.0e)'
   % (rep.get('maxRelativeSpread', float('nan')), rep.get('worstMeasure'),
      evaluate.REPEAT_TOLERANCE))
ck('the declared tolerance is the one in evaluate.py',
   rep.get('declaredTolerance') == evaluate.REPEAT_TOLERANCE, str(rep.get('declaredTolerance')))

print("=== scope boundary (issue #1) ===")
FORBIDDEN = ['lap time', 'downforce', 'aerodynamic', 'crash', 'fatigue life',
             'safety factor', 'airworthy', 'certified', 'manufacturable']
FORBIDDEN_WORD = [r'\bstronger\b', r'\bstrength\b']


def walk_strings(obj, path=''):
    """(dotted path, string) for every string leaf, so a hit can be located."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from walk_strings(v, '%s.%s' % (path, k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk_strings(v, '%s[%d]' % (path, i))
    elif isinstance(obj, str):
        yield path, obj


def scan(obj):
    """(claim hits, boundary hits, strings scanned). A hit is a forbidden term in
    a string value; `boundary` fields are where the vocabulary is DISCLAIMED, so
    they are separated out rather than dropped -- the disclaimer has to be there."""
    claims, disclaimers, n = [], [], 0
    for path, s in walk_strings(obj):
        n += 1
        low = s.lower()
        hits = [t for t in FORBIDDEN if t in low]
        hits += [w for w in FORBIDDEN_WORD if re.search(w, low)]
        if hits:
            (disclaimers if path.rsplit('.', 1)[-1] == 'boundary' else claims).append(
                (path, sorted(hits)))
    return claims, disclaimers, n


fb_doc = json.load(open(os.path.join(RUN, 'feedback-event.json')))
claims_r, disc_r, n_r = scan(report)
claims_f, disc_f, n_f = scan(fb_doc)
ck('track-report.json makes no out-of-scope claim', not claims_r, str(claims_r[:3]))
ck('feedback-event.json makes no out-of-scope claim', not claims_f, str(claims_f[:3]))
ck('the scan covered the whole report, not a stub', n_r + n_f >= 150,
   '%d strings scanned (%d report, %d feedback)' % (n_r + n_f, n_r, n_f))
ck('the excluded boundary fields are real disclaimers, not an empty carve-out',
   len(disc_r) >= 2 and len(disc_f) >= 1,
   ', '.join(p for p, _ in disc_r + disc_f))
# Positive control: the scanner must actually catch a planted claim, or every
# assertion above is vacuous.
planted = copy.deepcopy(report)
planted['results'][0]['notes'] = 'stronger, certified airworthy, better lap time'
p_claims, _, _ = scan(planted)
ck('positive control: the scanner catches a planted claim',
   len(p_claims) == 1 and p_claims[0][0].endswith('notes')
   and set(p_claims[0][1]) == {'airworthy', 'certified', 'lap time', r'\bstronger\b'},
   str(p_claims))
ck('boundary text is carried into both artifacts',
   report['boundary'] == evaluate.BOUNDARY and fb_doc['boundary'] == evaluate.BOUNDARY)
ck('metric is declared a proxy', 'proxy' in evaluate.METRIC.lower(), evaluate.METRIC)
ck('the report never claims what the fixture omits',
   'not measured and not claimed' in evaluate.BOUNDARY.lower())

shutil.rmtree(TMP, ignore_errors=True)
summary_and_exit()
