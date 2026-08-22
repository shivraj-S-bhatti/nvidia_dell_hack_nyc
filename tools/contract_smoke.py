#!/usr/bin/env python3
"""End-to-end smoke test for the two #43 contract adapters.

    python3 tools/contract_smoke.py

Proves the Factory -> Track contract wiring works on real emitted data, before
#46 starts producing compiled candidates. Nothing here mocks the adapters; both
are exercised through their public entry points.

WHAT IS REAL DATA AND WHAT IS A STUB
------------------------------------
* Factory half -- fully real. `tools/factory/fixtures/neoracer-verdicts.golden.json`
  is six verbatim FactoryVerdict/1 payloads from a real Factory run over
  `tools/factory/fixtures/neoracer-candidates.json` (the NeoRacer object). Three
  pass, three fail across three distinct reason codes, and the baseline carries
  unchecked checks. Three CHECK_MEASUREMENT branches a real run cannot reach
  from this family -- offLadder, ARTIFACT fail and INVENTORY fail -- are covered
  by constructed checks in section 6 instead.

* Track half -- real measurements. `tools/track/fixtures/track-results.golden.json`
  is four verbatim track.result/1 payloads from a real Track run on the frozen
  S500 fixture, plus the candidate the survivor gate rejected.

* The one stub: Factory and Track do not yet run on the same candidate family
  (Factory runs on the CAD assembly, Track on the density domain -- #46 is the
  bridge that will join them). So the Track half's *pass* verdicts are built by
  feeding a minimal FactoryVerdict/1 payload through the real Factory adapter.
  The measurements are real; only the pairing is synthetic, and it is reported
  as such below.

  The *boundary* half needs no stub at all: it uses the three genuinely failed
  NeoRacer verdicts, and asserts no TrackResult can be produced from them.

Exits non-zero if any check fails.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load(name, *parts):
    """The two adapters share a file name, so load each under an explicit
    module name instead of relying on sys.path order."""
    path = os.path.join(ROOT, *parts)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


factory_adapter = _load('factory_contract_adapter',
                        'tools', 'factory', 'contract_adapter.py')
track_adapter = _load('track_contract_adapter',
                      'tools', 'track', 'contract_adapter.py')

FACTORY_GOLDEN = os.path.join(ROOT, 'tools', 'factory', 'fixtures',
                              'neoracer-verdicts.golden.json')
CANDIDATES = os.path.join(ROOT, 'tools', 'factory', 'fixtures',
                          'neoracer-candidates.json')
TRACK_GOLDEN = os.path.join(ROOT, 'tools', 'track', 'fixtures',
                            'track-results.golden.json')

RUN_ID = 'run.contract-smoke-1'

failures = []


def ck(name, condition, detail=''):
    print('  %s  %s%s' % ('PASS' if condition else 'FAIL', name,
                          '  ' + str(detail) if detail else ''))
    if not condition:
        failures.append(name)
    return condition


def raises(exc_type, fn, *args, **kwargs):
    """Return the exception if fn raised exc_type, else None."""
    try:
        fn(*args, **kwargs)
    except exc_type as err:
        return err
    except Exception:                                  # noqa: BLE001
        return None
    return None


def load(path):
    with open(path) as fh:
        return json.load(fh)


ENVELOPE = ('schema_version', 'id', 'run_id', 'parent_ids', 'source_hashes',
            'units', 'creation_method', 'evidence_sources')


def check_envelope(prefix, record, fields):
    """Every #43 entity carries the same envelope; problem.py enforces it exactly."""
    missing = [slot for slot in ENVELOPE if fields[slot] not in record]
    ck('%s carries the full #43 envelope' % prefix, not missing,
       'missing: %s' % missing if missing else '8 fields')
    ck('%s declares the frozen unit system' % prefix,
       record[fields['units']] == factory_adapter.NIGHTSHIFT_UNITS)
    method = record[fields['creation_method']]
    ck('%s declares a deterministic creation method' % prefix,
       isinstance(method, dict) and method.get('deterministic') is True,
       method.get('kind') if isinstance(method, dict) else method)
    ck('%s references sources by hash' % prefix,
       bool(record[fields['source_hashes']])
       and all(len(s['sha256']) >= 16 for s in record[fields['source_hashes']]),
       '%d source hashes' % len(record[fields['source_hashes']]))
    ck('%s carries the run id it was told' % prefix,
       record[fields['run_id']] == RUN_ID)


def no_machine_paths(record):
    """#43 rejects machine-specific artifact paths."""
    blob = json.dumps(record)
    return '/Users/' not in blob and '/home/' not in blob and 'C:\\' not in blob


# =========================================================================
print('=== 1/6 Factory: real NeoRacer verdicts -> nightshift.factory-verdict/v1 ===')

golden = load(FACTORY_GOLDEN)
family = load(CANDIDATES)
raw_verdicts = golden['verdicts']

ck('golden verdicts cover the committed NeoRacer candidate family',
   sorted(v['candidateId'] for v in raw_verdicts)
   == sorted(c['candidateId'] for c in family['candidates']),
   '%d candidates' % len(raw_verdicts))

FCM = factory_adapter.factory_creation_method(raw_verdicts[0]['checkSetVersion'])

verdict_records = {}
for raw in raw_verdicts:
    record = factory_adapter.to_factory_verdict(
        raw,
        run_id=RUN_ID,
        units=factory_adapter.NIGHTSHIFT_UNITS,
        creation_method=FCM,
        repo_root=ROOT,
        # The golden fixture stores evidencePath repo-relative and the run that
        # produced it is not on disk in CI, so supply the hash explicitly --
        # exactly the escape hatch the adapter demands instead of inventing one.
        evidence_sha256=raw['stepSha256'])
    verdict_records[record['candidate_id']] = record

ck('every NeoRacer verdict adapts', len(verdict_records) == len(raw_verdicts),
   '%d records' % len(verdict_records))

sample = verdict_records['neo-c-link-only']
check_envelope('FactoryVerdict', sample, factory_adapter.FIELDS)

ck('schema version is the frozen string',
   sample['schema_version'] == 'nightshift.factory-verdict/v1',
   sample['schema_version'])

ck('pass/fail outcomes survive the mapping unchanged',
   {c: verdict_records[c]['verdict'] for c in verdict_records}
   == {v['candidateId']: v['verdict'] for v in raw_verdicts})

ck('a rejected candidate reports its failure codes',
   verdict_records['neo-c-link-only']['failure_codes'] == ['FAC-LEN-001'],
   verdict_records['neo-c-link-only']['failure_codes'])
ck('a passing candidate reports no failure codes',
   verdict_records['neo-a-scoped-1mm']['failure_codes'] == [])

ck('no machine-specific path reaches the contract',
   all(no_machine_paths(r) for r in verdict_records.values()))


# =========================================================================
print()
print('=== 2/6 Factory: every check exposes what Issue 47 requires ===')

REQUIRED_CHECK_FIELDS = ('check_id', 'outcome', 'measured', 'operator', 'threshold',
                         'implicated_component_ids', 'evidence_source_ids')

all_checks = [c for r in verdict_records.values() for c in r['checks']]
ck('checks were emitted', len(all_checks) == 30, '%d checks over 6 candidates' % len(all_checks))

shape_ok = all(sorted(c.keys()) == sorted(REQUIRED_CHECK_FIELDS) for c in all_checks)
ck('every check exposes exactly the 7 required fields', shape_ok)

decided = [c for c in all_checks if c['outcome'] in ('pass', 'fail')]
measured_ok = all(c['measured'] is not None and c['operator'] is not None
                  for c in decided)
ck('every decided check has a measured value and an operator', measured_ok,
   '%d decided checks' % len(decided))

unchecked = [c for c in all_checks if c['outcome'] == 'unchecked']
ck('an unchecked check reports null rather than a fabricated zero',
   all(c['measured'] is None for c in unchecked),
   '%d unchecked' % len(unchecked))

# The real veto, carried end to end with its numbers intact.
clr = [c for c in verdict_records['neo-d-standardize-m3']['checks']
       if c['check_id'] == 'CLEARANCE'][0]
ck('the real clearance veto keeps measured vs threshold',
   clr['outcome'] == 'fail' and clr['operator'] == '<='
   and clr['measured'] > clr['threshold'],
   'measured %s %s threshold %s' % (clr['measured'], clr['operator'], clr['threshold']))
ck('the clearance veto names implicated components',
   len(clr['implicated_component_ids']) > 0,
   '%d components' % len(clr['implicated_component_ids']))

con = [c for c in verdict_records['neo-e-thicker-bearing']['checks']
       if c['check_id'] == 'CONTRACT'][0]
ck('the protected-interface veto is carried as a contract violation',
   con['outcome'] == 'fail' and con['measured'] >= 1 and con['threshold'] == 0,
   'measured %s %s threshold %s' % (con['measured'], con['operator'], con['threshold']))

length = [c for c in verdict_records['neo-c-link-only']['checks']
          if c['check_id'] == 'FASTENER_LENGTH'][0]
ck('the engagement veto keeps its signed millimetre delta',
   length['outcome'] == 'fail' and length['operator'] == '>='
   and length['measured'] < length['threshold'],
   'measured %s %s threshold %s' % (length['measured'], length['operator'], length['threshold']))


# =========================================================================
print()
print('=== 3/6 Boundary: a Factory-rejected candidate CANNOT produce a TrackResult ===')

# Uses the three genuinely-failed NeoRacer verdicts. No stub is involved: the
# adapter must refuse before it reads a single measurement, so the probe payload
# never becomes a record.
probe = {'schemaVersion': 'track.result/1', 'candidateId': None,
         'measures': {'state': 'ok'}, 'relative': {'specificStiffnessRatio': 1.0},
         'fixtureHash': 'a' * 64}

rejected_ids = [cid for cid, r in verdict_records.items() if r['verdict'] == 'fail']
ck('the NeoRacer family really does contain rejections', len(rejected_ids) == 3,
   rejected_ids)

TCM = track_adapter.track_creation_method('track.result/1')


def emit(candidate_id, verdict):
    payload = dict(probe, candidateId=candidate_id)
    return track_adapter.to_track_result(
        payload, factory_verdict=verdict, run_id=RUN_ID,
        units=track_adapter.NIGHTSHIFT_UNITS, creation_method=TCM)


for cid in rejected_ids:
    err = raises(track_adapter.FactoryRejectedError, emit, cid, verdict_records[cid])
    ck('%s is refused at the boundary' % cid, err is not None,
       str(err).split(' -- ')[0] if err else 'NO EXCEPTION RAISED')

ck('a missing verdict is refused too (absence is not permission)',
   raises(track_adapter.FactoryRejectedError, emit, 'neo-a-scoped-1mm', None) is not None)

ck('a raw FactoryVerdict/1 is refused (must be adapted first)',
   raises(track_adapter.FactoryRejectedError, emit, 'neo-a-scoped-1mm',
          raw_verdicts[0]) is not None)

ck("one candidate's pass cannot clear a different candidate",
   raises(track_adapter.FactoryRejectedError, emit, 'neo-c-link-only',
          verdict_records['neo-a-scoped-1mm']) is not None)


# =========================================================================
print()
print('=== 4/6 Track: real measurements -> nightshift.track-result/v1 ===')

track_golden = load(TRACK_GOLDEN)
results = track_golden['results']

# The one stub, built through the real Factory adapter so even it goes through
# production code. Factory and Track do not yet share a candidate family; #46
# is the bridge that will join them.
def stub_pass_verdict(candidate_id):
    raw = {
        'schema': 'FactoryVerdict/1',
        'checkSetVersion': 'factory-checks/1.0.0',
        'candidateId': candidate_id,
        'parentId': None,
        'stepSha256': 'b' * 64,
        'corpusRevision': 'c' * 16,
        'verdict': 'pass',
        'reasonCode': 'FAC-000',
        'checks': [],
        'evidencePath': None,
        'elapsedMs': 0.0,
    }
    return factory_adapter.to_factory_verdict(
        raw, run_id=RUN_ID, units=factory_adapter.NIGHTSHIFT_UNITS,
        creation_method=FCM, repo_root=ROOT)


print('  note: Factory and Track do not yet run on one candidate family;')
print('        the pass verdicts below are stubs. The measurements are real.')

track_records = {}
for raw in results:
    record = track_adapter.to_track_result(
        raw,
        factory_verdict=stub_pass_verdict(raw['candidateId']),
        run_id=RUN_ID,
        units=track_adapter.NIGHTSHIFT_UNITS,
        creation_method=TCM)
    track_records[record['candidate_id']] = record

ck('every Track result adapts', len(track_records) == len(results),
   '%d records' % len(track_records))

check_envelope('TrackResult', track_records['cand-a-edge-scallops'], track_adapter.FIELDS)

ck('schema version is the frozen string',
   track_records['cand-a-edge-scallops']['schema_version'] == 'nightshift.track-result/v1')

statuses = {r['status'] for r in track_records.values()}
ck('status is the #43 vocabulary, not the solver state',
   bool(statuses) and statuses <= {'measured', 'solver_failed'}, sorted(statuses))

ck('a solved candidate is reported as measured',
   track_records['cand-a-edge-scallops']['status'] == 'measured')

ck('rank survives, and the baseline has none',
   track_records['cand-a-edge-scallops']['rank'] == 1
   and track_records['baseline']['rank'] is None)

by_id = {r['candidateId']: r for r in results}
ck('score is the documented ranking primary',
   track_records['cand-a-edge-scallops']['score']
   == by_id['cand-a-edge-scallops']['relative']['specificStiffnessRatio'],
   track_records['cand-a-edge-scallops']['score'])

metrics = track_records['cand-a-edge-scallops']['metrics']
ck('metrics carry both absolute and baseline-relative values',
   'compliance' in metrics and 'compliance_ratio_to_baseline' in metrics,
   '%d metrics' % len(metrics))

ck('measured numbers are unchanged by the adapter',
   metrics['compliance'] == by_id['cand-a-edge-scallops']['measures']['complianceNmm'],
   metrics['compliance'])

ck('the fixture hash is carried, so a ranking stays auditable',
   any(s['source_id'] == 'source.fixture'
       for s in track_records['cand-a-edge-scallops']['source_hashes']))

ck('a candidate that missed the target is flagged for feedback',
   track_records['cand-b-centre-window']['feedback_recommended'] is True)
ck('a candidate that met the target is not',
   track_records['cand-a-edge-scallops']['feedback_recommended'] is False)

ck('the result records which verdict cleared it',
   any(p.startswith('factory-verdict.')
       for p in track_records['cand-a-edge-scallops']['parent_ids']),
   track_records['cand-a-edge-scallops']['parent_ids'])

rejected_cid = track_golden['rejected'][0]['candidateId']
rejected_verdict = factory_adapter.to_factory_verdict(
    {'schema': 'FactoryVerdict/1', 'checkSetVersion': 'factory-checks/1.0.0',
     'candidateId': rejected_cid, 'stepSha256': 'b' * 64, 'corpusRevision': 'c' * 16,
     'verdict': 'fail', 'checks': [], 'evidencePath': None, 'elapsedMs': 0.0},
    run_id=RUN_ID, units=factory_adapter.NIGHTSHIFT_UNITS,
    creation_method=FCM, repo_root=ROOT)
ck('the gate-rejected candidate is refused a result, not merely absent',
   rejected_cid not in track_records
   and raises(track_adapter.FactoryRejectedError, track_adapter.to_track_result,
              dict(by_id['cand-a-edge-scallops'], candidateId=rejected_cid),
              factory_verdict=rejected_verdict, run_id=RUN_ID,
              units=track_adapter.NIGHTSHIFT_UNITS,
              creation_method=TCM) is not None, rejected_cid)


# =========================================================================
print()
print('=== 5/6 Required fields with no source fail loudly ===')

good = dict(run_id=RUN_ID, units=factory_adapter.NIGHTSHIFT_UNITS,
            creation_method=FCM, repo_root=ROOT, evidence_sha256='d' * 64)

for omitted in ('run_id', 'units', 'creation_method'):
    kwargs = dict(good)
    kwargs[omitted] = None
    ck('Factory refuses to invent %s' % omitted,
       raises(factory_adapter.ContractFieldError,
              factory_adapter.to_factory_verdict, raw_verdicts[0], **kwargs) is not None)

ck('Factory rejects a wrong unit VALUE (not just a missing key)',
   raises(factory_adapter.ContractFieldError,
          factory_adapter.to_factory_verdict, raw_verdicts[0],
          **dict(good, units=dict(factory_adapter.NIGHTSHIFT_UNITS,
                                  length='in'))) is not None)
ck('Factory rejects an incomplete unit system',
   raises(factory_adapter.ContractFieldError,
          factory_adapter.to_factory_verdict, raw_verdicts[0],
          **dict(good, units={'length': 'mm'})) is not None)

baseline_raw = {r['candidateId']: r for r in results}['baseline']
tgood = dict(factory_verdict=stub_pass_verdict('baseline'), run_id=RUN_ID,
             units=track_adapter.NIGHTSHIFT_UNITS, creation_method=TCM)
for omitted in ('run_id', 'units', 'creation_method'):
    kwargs = dict(tgood)
    kwargs[omitted] = None
    ck('Track refuses to invent %s' % omitted,
       raises(track_adapter.ContractFieldError,
              track_adapter.to_track_result, baseline_raw, **kwargs) is not None)

ck('Track refuses an unmapped solver state',
   raises(track_adapter.ContractFieldError, track_adapter.to_track_result,
          dict(baseline_raw, measures=dict(baseline_raw['measures'], state='wat')),
          **tgood) is not None)

ck('Factory refuses a payload that is not FactoryVerdict/1',
   raises(factory_adapter.ContractFieldError, factory_adapter.to_factory_verdict,
          {'schema': 'SomethingElse/1'}, **good) is not None)

ck('adapting is byte-stable',
   factory_adapter.canonical_json(verdict_records['neo-c-link-only'])
   == factory_adapter.canonical_json(
       factory_adapter.to_factory_verdict(
           [v for v in raw_verdicts if v['candidateId'] == 'neo-c-link-only'][0],
           run_id=RUN_ID, units=factory_adapter.NIGHTSHIFT_UNITS,
           creation_method=FCM, repo_root=ROOT,
           evidence_sha256=[v for v in raw_verdicts
                            if v['candidateId'] == 'neo-c-link-only'][0]['stepSha256'])))


# =========================================================================
print()
print('=== 6/6 Regressions: branches a real run cannot reach from the fixtures ===')


def one_check(check_id, status, measured, tolerance):
    """Adapt a single constructed check and return its contract form."""
    raw = {
        'schema': 'FactoryVerdict/1', 'checkSetVersion': 'factory-checks/1.0.0',
        'candidateId': 'probe', 'stepSha256': 'b' * 64, 'corpusRevision': 'c' * 16,
        'verdict': 'fail' if status == 'fail' else 'pass',
        'checks': [{'check': check_id, 'status': status, 'reasonCode': 'FAC-XXX-001',
                    'reason': '', 'measured': measured, 'tolerance': tolerance,
                    'affectedOccurrences': [], 'affectedDefinitions': []}],
        'evidencePath': None, 'elapsedMs': 0.0,
    }
    return factory_adapter.to_factory_verdict(
        raw, run_id=RUN_ID, units=factory_adapter.NIGHTSHIFT_UNITS,
        creation_method=FCM, repo_root=ROOT)['checks'][0]

# A failing check must report the comparison that actually broke. ARTIFACT and
# INVENTORY can each fail on a value the first table rule does not look at.
art = one_check('ARTIFACT', 'fail',
                {'stepSha256': 'b' * 64, 'corpusRevision': 'c' * 16,
                 'checkSetVersion': 'factory-checks/1.0.0'},
                {'stepSha256': 'b' * 64, 'corpusRevision': 'c' * 16,
                 'checkSetVersion': 'factory-checks/9.9.9'})
ck('ARTIFACT fail reports the pin that broke, not a satisfied one',
   art['measured'] != art['threshold'],
   '%s != %s' % (art['measured'], art['threshold']))

inv = one_check('INVENTORY', 'fail', {'occurrences': 647, 'definitions': 100},
                {'expectedOccurrences': 647, 'expectedDefinitions': 99})
ck('INVENTORY fail reports the count that broke',
   inv['measured'] == 100 and inv['threshold'] == 99,
   'measured %s vs threshold %s' % (inv['measured'], inv['threshold']))

# checks.py writes expectedOccurrences unconditionally, sometimes as null.
# A present-but-null pin means "not pinned" and must not read as "== null".
unpinned = one_check('INVENTORY', 'pass', {'occurrences': 647, 'definitions': 100},
                     {'expectedOccurrences': None, 'expectedDefinitions': None})
ck('an unpinned tolerance falls through to the default, not null',
   unpinned['threshold'] == unpinned['measured'],
   'threshold %s' % unpinned['threshold'])

ladder = one_check('FASTENER_LENGTH', 'fail',
                   {'offLadder': [{'fastener': 'f', 'proposedLengthMm': 7}]},
                   {'note': 'stock ladder'})
ck('the off-ladder branch counts the offenders',
   ladder['measured'] == 1 and ladder['operator'] == '==' and ladder['threshold'] == 0,
   'measured %s' % ladder['measured'])

ck('a check with no mapping rule fails loudly rather than emitting null',
   raises(factory_adapter.ContractFieldError, one_check,
          'UNMAPPED', 'fail', {'x': 1}, {}) is not None)

# The record must not depend on the caller's working directory.
here = os.getcwd()
try:
    os.chdir(os.path.dirname(ROOT))
    moved = factory_adapter.to_factory_verdict(
        raw_verdicts[0], run_id=RUN_ID, units=factory_adapter.NIGHTSHIFT_UNITS,
        creation_method=FCM, repo_root=ROOT,
        evidence_sha256=raw_verdicts[0]['stepSha256'])
finally:
    os.chdir(here)
ck('adapting is independent of the working directory',
   factory_adapter.canonical_json(moved)
   == factory_adapter.canonical_json(verdict_records[raw_verdicts[0]['candidateId']]))

# A solver failure is a fact the run must carry, so the record has to exist.
failed_raw = dict(baseline_raw,
                  measures=dict(baseline_raw['measures'], state='non_finite',
                                complianceNmm=float('inf')),
                  relative=dict(baseline_raw.get('relative') or {}))
failed = track_adapter.to_track_result(
    failed_raw, factory_verdict=stub_pass_verdict('baseline'), run_id=RUN_ID,
    units=track_adapter.NIGHTSHIFT_UNITS, creation_method=TCM)
ck('a solver failure produces a record, not an exception',
   failed['status'] == 'solver_failed', failed['status'])
ck('a solver failure is given no score', failed['score'] is None)
ck('a solver failure is flagged for feedback',
   failed['feedback_recommended'] is True)
ck('the non-finite number is dropped, not emitted',
   'compliance' not in failed['metrics'])
ck('the solver-failure record is still serializable as strict JSON',
   json.loads(track_adapter.canonical_json(failed))['status'] == 'solver_failed')

# The gate does not take the top-level string on trust.
contradictory = dict(verdict_records['neo-a-scoped-1mm'],
                     failure_codes=['FAC-CON-003'])
ck('a verdict that says pass while reporting failure codes is refused',
   raises(track_adapter.FactoryRejectedError, track_adapter.to_track_result,
          dict(baseline_raw, candidateId='neo-a-scoped-1mm'),
          factory_verdict=contradictory, run_id=RUN_ID,
          units=track_adapter.NIGHTSHIFT_UNITS, creation_method=TCM) is not None)

contradictory2 = dict(
    verdict_records['neo-a-scoped-1mm'],
    checks=[dict(verdict_records['neo-a-scoped-1mm']['checks'][0], outcome='fail')])
ck('a verdict that says pass while carrying a failing check is refused',
   raises(track_adapter.FactoryRejectedError, track_adapter.to_track_result,
          dict(baseline_raw, candidateId='neo-a-scoped-1mm'),
          factory_verdict=contradictory2, run_id=RUN_ID,
          units=track_adapter.NIGHTSHIFT_UNITS, creation_method=TCM) is not None)

ck('a non-string candidate id cannot satisfy the identity check',
   raises(track_adapter.FactoryRejectedError, track_adapter.to_track_result,
          dict(baseline_raw, candidateId=True),
          factory_verdict=dict(verdict_records['neo-a-scoped-1mm'], candidate_id=1),
          run_id=RUN_ID, units=track_adapter.NIGHTSHIFT_UNITS,
          creation_method=TCM) is not None)

ck('a digest with a trailing newline is refused',
   raises(factory_adapter.ContractFieldError, factory_adapter._hex_digest,
          'a' * 64 + chr(10), 'probe') is not None)

ck('canonical_json refuses to write a bare NaN literal',
   raises(ValueError, factory_adapter.canonical_json,
          {'x': float('nan')}) is not None)

ck('factory_adapter.passed agrees with the Track gate on every golden verdict',
   all(factory_adapter.passed(r)
       == (r['candidate_id'] not in rejected_ids) for r in verdict_records.values()))


# =========================================================================
print()
if failures:
    print('FAILED: %d' % len(failures))
    for name in failures:
        print('  - %s' % name)
    sys.exit(1)
print('ALL CHECKS PASSED')
