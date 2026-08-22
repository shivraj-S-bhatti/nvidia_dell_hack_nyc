"""verdict.py -- run the check set over a candidate family and record the outcome.

Produces, per run:
  <out>/verdicts/<candidateId>.json   one FactoryVerdict, with every check's evidence
  <out>/survivors.json                the ONLY input Track is allowed to read
  <out>/feedback/<candidateId>.json   one FeedbackEvent per rejection
  <out>/check-set.json                the versioned check set, including what it skips
  <out>/run.json                      timing, peak RSS, and the family-level summary

A failing candidate never appears in survivors.json. That file is the mechanism by
which "a failed candidate must not reach Track" is enforced, rather than a promise.

Factory reports rejections. It does not revise designs -- that is Lab's job (#12),
and the FeedbackEvent is deliberately a constraint plus evidence, not a fix.
"""
import os, sys, json, time, resource, platform

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import checks as C                                                       # noqa: E402
from candidate import CHECK_SET_VERSION                                  # noqa: E402

VERDICT_SCHEMA = 'FactoryVerdict/1'
FEEDBACK_SCHEMA = 'FeedbackEvent/1'
# Demo order: the two checks that measure geometry are shown before the two that
# verify bookkeeping. Evaluation order differs -- CONTRACT gates the geometry checks,
# because an op Factory cannot resolve is an op it cannot sweep.
DISPLAY_ORDER = ['CLEARANCE', 'FASTENER_LENGTH', 'CONTRACT', 'ARTIFACT', 'INVENTORY']


def peak_rss_mb():
    """Peak resident set size. ru_maxrss is bytes on Darwin, kilobytes on Linux."""
    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(raw / (1024 * 1024 if platform.system() == 'Darwin' else 1024), 1)


def evaluate(asm, contract, cand, out_root):
    """One FactoryVerdict. Never raises for a bad candidate -- that is a verdict too."""
    t0 = time.perf_counter()
    evidence_path = os.path.join(out_root, 'verdicts', f'{cand.id or "unnamed"}.json')

    contract_r = C.check_contract(asm, contract, cand)
    artifact_r = C.check_artifact(asm, contract)
    inventory_r = C.check_inventory(asm, contract)

    # A candidate whose ops do not resolve cannot have its geometry measured. Say that
    # explicitly rather than sweeping a half-understood delta and reporting a pass.
    blocked = 'CONTRACT' if contract_r['status'] == 'fail' else None
    clearance_r = C.check_clearance(asm, cand, blocked)
    length_r = C.check_fastener_length(asm, cand, blocked)

    by_id = {r['check']: r for r in
             (clearance_r, length_r, contract_r, artifact_r, inventory_r)}
    ordered = [by_id[k] for k in DISPLAY_ORDER]

    failed = [r for r in ordered if r['status'] == 'fail']
    unchecked = [r for r in ordered if r['status'] == 'unchecked']
    affected, affected_defs = set(), set()
    for r in failed:
        affected.update(r['affectedOccurrences'])
        affected_defs.update(r['affectedDefinitions'])

    verdict = {
        'schema': VERDICT_SCHEMA,
        'checkSetVersion': CHECK_SET_VERSION,
        'objectId': contract.objectId,
        'corpusRevision': asm.corpusRevision,
        'stepSha256': asm.stepSha256,
        'candidateId': cand.id,
        'parentId': cand.parentId,
        'label': cand.label,
        'rationale': cand.rationale,
        'ops': cand.ops,
        'verdict': 'fail' if failed else 'pass',
        'reasonCode': failed[0]['reasonCode'] if failed else 'FAC-000',
        'reason': failed[0]['reason'] if failed else
                  f'{len(ordered) - len(unchecked)} checks passed, '
                  f'{len(unchecked)} not applicable',
        'failedChecks': [r['check'] for r in failed],
        'uncheckedChecks': [r['check'] for r in unchecked],
        'affectedOccurrences': sorted(affected),
        'affectedDefinitions': sorted(affected_defs),
        'checks': ordered,
        'evidencePath': evidence_path,
        'elapsedMs': None,     # filled below so it is the last field written
    }
    verdict['elapsedMs'] = round((time.perf_counter() - t0) * 1000, 1)
    return verdict


def feedback_event(verdict):
    """One FeedbackEvent from a rejection: the measured bound, not a redesign.

    The `constraint` is the strongest statement Factory can defend from what it
    measured -- how far this candidate overshot, and at which occurrences. Choosing a
    different length, a different part, or a different approach is Lab's decision.
    """
    if verdict['verdict'] != 'fail':
        return None
    fail = next(c for c in verdict['checks'] if c['status'] == 'fail')
    constraint = None

    if fail['reasonCode'] == 'FAC-CLR-001':
        # Per definition, the tightest occurrence sets the ceiling for the whole
        # definition -- a definition-level substitution reaches every instance.
        per_def = {}
        for d in fail['measured']['detail']:
            k = d['definition']
            cur = per_def.get(k)
            if cur is None or d['clearanceBeforeMm'] < cur['maxGrowthMm']:
                per_def[k] = {'maxGrowthMm': d['clearanceBeforeMm'],
                              'bindingOccurrence': d['fastener'],
                              'currentLengthMm': d['currentLengthMm'],
                              'obstructedBy': sorted({h['defName'] for h in d['intersects']})}
        constraint = {
            'kind': 'max-fastener-growth',
            'perDefinition': per_def,
            'statement': '; '.join(
                f"{k}: may grow at most {v['maxGrowthMm']} mm past its current tip "
                f"(binding occurrence {v['bindingOccurrence']}, obstructed by "
                f"{', '.join(v['obstructedBy'])})" for k, v in sorted(per_def.items())),
        }
    elif fail['reasonCode'] == 'FAC-LEN-001':
        per_def = {}
        for d in fail['measured']['detail']:
            k = d['definition']
            need = round(-d['engagementDeltaMm'], 3)
            if k not in per_def or need > per_def[k]['minLengthIncreaseMm']:
                per_def[k] = {'minLengthIncreaseMm': need,
                              'bindingOccurrence': d['fastener'],
                              'currentLengthMm': d['currentLengthMm'],
                              'thickenedMembers': d['thickenedMembers']}
        constraint = {
            'kind': 'min-fastener-length-increase',
            'perDefinition': per_def,
            'statement': '; '.join(
                f"{k}: needs at least {v['minLengthIncreaseMm']} mm more nominal length "
                f"to preserve current engagement (binding occurrence "
                f"{v['bindingOccurrence']})" for k, v in sorted(per_def.items())),
        }
    elif fail['check'] == 'CONTRACT':
        constraint = {'kind': 'contract',
                      'statement': fail['reason'],
                      'violations': fail['measured'].get('violations', [])}

    return {
        'schema': FEEDBACK_SCHEMA,
        'emittedBy': 'factory',
        'checkSetVersion': verdict['checkSetVersion'],
        'corpusRevision': verdict['corpusRevision'],
        'candidateId': verdict['candidateId'],
        'parentId': verdict['parentId'],
        'label': verdict['label'],
        'check': fail['check'],
        'reasonCode': fail['reasonCode'],
        'reason': fail['reason'],
        'measured': fail['measured'],
        'tolerance': fail['tolerance'],
        'implicatedOccurrences': fail['affectedOccurrences'],
        'implicatedDefinitions': fail['affectedDefinitions'],
        'constraint': constraint,
        'evidencePath': verdict['evidencePath'],
        'note': 'Factory reports the measured constraint and the implicated parts. '
                'It does not revise the design; that is Lab (#12).',
    }


def run_family(asm, contract, candidates, out_root):
    """Evaluate every candidate. One failure never stops the family."""
    t0 = time.perf_counter()
    for sub in ('verdicts', 'feedback'):
        os.makedirs(os.path.join(out_root, sub), exist_ok=True)

    verdicts, feedback = [], []
    for cand in candidates:
        v = evaluate(asm, contract, cand, out_root)
        verdicts.append(v)
        _write(v['evidencePath'], v)
        fe = feedback_event(v)
        if fe:
            feedback.append(fe)
            _write(os.path.join(out_root, 'feedback', f'{v["candidateId"]}.json'), fe)

    survivors = {
        'schema': 'TrackInputManifest/1',
        'checkSetVersion': CHECK_SET_VERSION,
        'objectId': contract.objectId,
        'corpusRevision': asm.corpusRevision,
        'survivors': [{'candidateId': v['candidateId'], 'parentId': v['parentId'],
                       'label': v['label'], 'ops': v['ops'],
                       'verdictPath': v['evidencePath']}
                      for v in verdicts if v['verdict'] == 'pass'],
        'rejected': [{'candidateId': v['candidateId'], 'reasonCode': v['reasonCode'],
                      'check': v['failedChecks'][0]}
                     for v in verdicts if v['verdict'] == 'fail'],
        'note': 'Track reads survivors[] only. Rejected candidate ids appear here for '
                'visibility and are not eligible input.',
    }
    _write(os.path.join(out_root, 'survivors.json'), survivors)
    _write(os.path.join(out_root, 'check-set.json'), C.check_set_manifest())

    run = {
        'schema': 'FactoryRun/1',
        'checkSetVersion': CHECK_SET_VERSION,
        'objectId': contract.objectId,
        'corpusRevision': asm.corpusRevision,
        'stepSha256': asm.stepSha256,
        'contractSource': contract.source,
        'candidates': len(verdicts),
        'passed': sum(1 for v in verdicts if v['verdict'] == 'pass'),
        'failed': sum(1 for v in verdicts if v['verdict'] == 'fail'),
        'feedbackEvents': len(feedback),
        'elapsedMs': round((time.perf_counter() - t0) * 1000, 1),
        'peakRssMb': peak_rss_mb(),
        'samplingDensity': asm.sampling_density(),
    }
    _write(os.path.join(out_root, 'run.json'), run)
    return verdicts, feedback, survivors, run


def _write(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
        fh.write('\n')


def digest(verdicts):
    """Stable fingerprint of a family's outcome, for repeatability comparison.

    Deliberately covers the verdict, reason code, measured values, and implicated
    occurrences -- but not timing, which is expected to vary between runs.
    """
    import hashlib
    payload = [{k: v[k] for k in ('candidateId', 'verdict', 'reasonCode',
                                  'failedChecks', 'uncheckedChecks',
                                  'affectedOccurrences', 'affectedDefinitions')}
               | {'checks': [{'check': c['check'], 'status': c['status'],
                              'reasonCode': c['reasonCode'], 'measured': c['measured']}
                             for c in v['checks']]}
               for v in verdicts]
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
