"""checks.py -- the versioned Factory check set.

Every check returns the same shape: a status, a deterministic reason code, the
measured value, the tolerance it was compared against, and the occurrences
implicated. A check that cannot evaluate a candidate returns `unchecked` with a
reason. It never returns `pass` for something it did not measure -- an unverifiable
candidate is an unverified candidate, and the verdict says so out loud.

No language model is consulted anywhere in this file. Each verdict is arithmetic on
measurements from geometry.py against constants declared here.

Check order below is demo order, which is also confidence order: the two checks that
measure real geometry come before the two that verify bookkeeping.
"""
from candidate import CHECK_SET_VERSION, OPS

# Any loss of thread engagement relative to the current build is a rejection. The
# absolute adequacy of the current build is NOT claimed -- see the scope note in
# depgraph/derive_edges._grip. This check is purely relative, which is exactly what
# makes it sound: it needs no knowledge of which member is threaded.
ENGAGEMENT_TOL_MM = 0.0
# Resolution of the bisection that recovers how much free space a fastener had
# before it collided. Reported as the constraint Lab must respect.
CLEARANCE_RESOLUTION_MM = 0.05

# Checks issue #47 lists that this set does NOT implement. Declared so that a
# passing verdict cannot be mistaken for a broader claim than it makes.
NOT_CHECKED = [
    {'check': 'CAD load/export round-trip', 'reason':
        'candidates are declared parametric deltas, not re-authored STEP files, so '
        'there is no export to round-trip. Adding one requires a B-rep kernel.'},
    {'check': 'closed-solid / B-rep validity', 'reason':
        'the pipeline reads STEP topology and a tessellated mesh, not a solid modelling '
        'kernel; solid validity is not derivable from either.'},
    {'check': 'required-void and keep-out compliance', 'reason':
        'no keep-out volumes are declared in the object contract for this fixture.'},
    {'check': 'thickness / minimum-feature rule', 'reason':
        'no minimum-feature rule is declared in the object contract for this fixture.'},
    {'check': 'connectivity from load regions to supports', 'reason':
        'no operation in the '
        + CHECK_SET_VERSION +
        ' vocabulary can add or remove a component, so connectivity cannot change. '
        'A check that cannot fail is not evidence; it is reinstated when an op that '
        'removes or relocates a component is added.'},
]


def check_set_manifest():
    return {'checkSetVersion': CHECK_SET_VERSION,
            'checks': ['CLEARANCE', 'FASTENER_LENGTH', 'CONTRACT', 'ARTIFACT', 'INVENTORY'],
            'operationVocabulary': {k: v['doc'] for k, v in sorted(OPS.items())},
            'tolerances': {'engagementToleranceMm': ENGAGEMENT_TOL_MM,
                           'clearanceResolutionMm': CLEARANCE_RESOLUTION_MM},
            'notChecked': NOT_CHECKED}


def _result(cid, status, code, reason, measured=None, tolerance=None,
            affected=(), affectedDefs=()):
    return {'check': cid, 'status': status, 'reasonCode': code, 'reason': reason,
            'measured': measured or {}, 'tolerance': tolerance or {},
            'affectedOccurrences': sorted(affected),
            'affectedDefinitions': sorted(affectedDefs)}


# ---------------------------------------------------------------------------
# op resolution
# ---------------------------------------------------------------------------

def resolve_fastener_ops(asm, cand):
    """[(site, currentLengthMm, newLengthMm)] for every fastener occurrence touched.

    A `fastener_length` op targets a definition, which by INSTANCE_OF reaches every
    occurrence of it -- that breadth is the point of a definition-level substitution
    and it is also how a change that is fine in most places becomes illegal in a few.
    `targetOccurrences` narrows it when Lab means only some of them.
    """
    out = []
    for op in cand.ops:
        if op.get('op') != 'fastener_length':
            continue
        wanted = op.get('targetOccurrences')
        for occId, site in sorted(asm.sites.items()):
            if wanted is not None:
                if occId not in wanted:
                    continue
            elif site['defName'] != op.get('target'):
                continue
            cur = site['nominalLengthMm']
            if cur is None:
                continue
            out.append((site, cur, float(op['newLengthMm'])))
    return out


def thickness_deltas(cand):
    d = {}
    for op in cand.ops:
        if op.get('op') == 'thickness':
            d[op['target']] = d.get(op['target'], 0.0) + float(op['deltaMm'])
    return d


# ---------------------------------------------------------------------------
# 1. CLEARANCE -- does changed material reach into a neighbour?
# ---------------------------------------------------------------------------

def _first_contact(asm, site, growth):
    """Smallest growth at which the swept shank first reaches foreign material.

    Monotone in growth (a longer sweep contains a shorter one), so bisection is exact
    to CLEARANCE_RESOLUTION_MM.
    """
    lo, hi = 0.0, growth
    while hi - lo > CLEARANCE_RESOLUTION_MM:
        mid = (lo + hi) / 2.0
        if asm.sweep_beyond_tip(site, mid):
            hi = mid
        else:
            lo = mid
    return hi


def check_clearance(asm, cand, blocked):
    cid = 'CLEARANCE'
    if blocked:
        return _result(cid, 'unchecked', 'FAC-CLR-U02',
                       f'not evaluated: the candidate failed {blocked} first, so its '
                       f'declared geometry could not be resolved')

    fops = resolve_fastener_ops(asm, cand)
    thick = thickness_deltas(cand)
    grown = [(s, c, n) for s, c, n in fops if n > c]

    hits_all, affected, affected_defs, worst = [], set(), set(), None
    for site, cur, new in grown:
        growth = new - cur
        hits = asm.sweep_beyond_tip(site, growth)
        if not hits:
            continue
        clearance_before = _first_contact(asm, site, growth)
        penetration = round(growth - clearance_before, 3)
        rec = {'fastener': site['occId'], 'definition': site['defName'],
               'currentLengthMm': cur, 'proposedLengthMm': new,
               'growthMm': round(growth, 3),
               'clearanceBeforeMm': round(clearance_before, 3),
               'penetrationMm': penetration,
               'intersects': [{'occId': h['occId'], 'defName': h['defName'],
                               'verticesInside': h['hitCount'],
                               'firstContactAtMm': h['nearestMm']} for h in hits]}
        hits_all.append(rec)
        affected.add(site['occId'])
        affected_defs.add(site['defName'])
        for h in hits:
            affected.add(h['occId'])
            affected_defs.add(h['defName'])
        if worst is None or penetration > worst['penetrationMm']:
            worst = rec

    swept = len(grown)
    unchecked_note = None
    if thick:
        unchecked_note = (
            'thickness ops in this candidate (' +
            ', '.join(f'{k} {v:+g} mm' for k, v in sorted(thick.items())) +
            ') are NOT interference-checked: a scalar thickness delta does not declare '
            'which face the material grows from, and the growth direction is not '
            'derivable from the baseline. The engagement consequence IS measured by '
            'FASTENER_LENGTH.')

    if hits_all:
        n_occ = len({h['occId'] for r in hits_all for h in r['intersects']})
        return _result(
            cid, 'fail', 'FAC-CLR-001',
            f"{len(hits_all)} of {swept} lengthened fastener occurrences sweep into "
            f"material they do not touch today. Deepest: {worst['definition']} at "
            f"{worst['fastener']} grows {worst['growthMm']} mm with only "
            f"{worst['clearanceBeforeMm']} mm free, driving {worst['penetrationMm']} mm "
            f"into {worst['intersects'][0]['defName']}.",
            measured={'collidingOccurrences': len(hits_all),
                      'sweptOccurrences': swept,
                      'obstructedOccurrences': n_occ,
                      'maxPenetrationMm': worst['penetrationMm'],
                      'minClearanceBeforeMm': min(r['clearanceBeforeMm'] for r in hits_all),
                      'detail': hits_all,
                      'unchecked': unchecked_note},
            tolerance={'maxPenetrationMm': 0.0,
                       'resolutionMm': CLEARANCE_RESOLUTION_MM,
                       'note': 'penetration is a LOWER BOUND: OCCT places triangulation '
                               'nodes on the exact surface, so a reported vertex is a '
                               'real point of the real solid.'},
            affected=affected, affectedDefs=affected_defs)

    if swept == 0 and not thick:
        return _result(cid, 'unchecked', 'FAC-CLR-U01',
                       'candidate declares no operation that adds material along a '
                       'measurable axis, so there is nothing to sweep',
                       measured={'sweptOccurrences': 0})

    return _result(
        cid, 'pass', 'FAC-CLR-000',
        f'no vertex of any other occurrence falls inside the swept volume of '
        f'{swept} lengthened fastener occurrences'
        + (f'. {unchecked_note}' if unchecked_note else ''),
        measured={'sweptOccurrences': swept, 'collidingOccurrences': 0,
                  'samplingDensity': asm.sampling_density(),
                  'unchecked': unchecked_note},
        tolerance={'note': 'a pass is "no evidence of interference at this sampling '
                           'density", not proof of clearance: a surface can pass '
                           'through the swept volume without placing a vertex inside.'})


# ---------------------------------------------------------------------------
# 2. FASTENER_LENGTH -- does every joint keep the engagement it has today?
# ---------------------------------------------------------------------------

def check_fastener_length(asm, cand, blocked):
    cid = 'FASTENER_LENGTH'
    if blocked:
        return _result(cid, 'unchecked', 'FAC-LEN-U02',
                       f'not evaluated: the candidate failed {blocked} first')

    thick = thickness_deltas(cand)
    new_len = {}
    for site, cur, new in resolve_fastener_ops(asm, cand):
        new_len[site['occId']] = new

    losses, off_ladder, evaluated = [], [], 0
    affected, affected_defs = set(), set()
    for fid, stack in sorted(asm.stacks.items()):
        if stack['gripMm'] is None or stack['nominalLengthMm'] is None:
            continue
        grip_delta = sum(thick.get(m['defName'], 0.0) for m in stack['members'])
        length_delta = new_len.get(fid, stack['nominalLengthMm']) - stack['nominalLengthMm']
        if grip_delta == 0.0 and length_delta == 0.0:
            continue
        evaluated += 1
        engagement_delta = round(length_delta - grip_delta, 3)
        if engagement_delta < -ENGAGEMENT_TOL_MM:
            rec = {'fastener': fid, 'definition': stack['defName'],
                   'currentLengthMm': stack['nominalLengthMm'],
                   'proposedLengthMm': new_len.get(fid, stack['nominalLengthMm']),
                   'currentGripMm': stack['gripMm'],
                   'proposedGripMm': round(stack['gripMm'] + grip_delta, 3),
                   'engagementDeltaMm': engagement_delta,
                   'thickenedMembers': sorted(m['defName'] for m in stack['members']
                                              if m['defName'] in thick)}
            losses.append(rec)
            affected.add(fid)
            affected_defs.add(stack['defName'])
            affected_defs.update(rec['thickenedMembers'])
        if fid in new_len:
            ladder = asm.stock_ladder(stack['nominalM'])
            if ladder and new_len[fid] not in ladder:
                off_ladder.append({'fastener': fid, 'definition': stack['defName'],
                                   'proposedLengthMm': new_len[fid],
                                   'stockLadder': ladder})
                affected.add(fid)
                affected_defs.add(stack['defName'])

    if losses:
        worst = min(losses, key=lambda r: r['engagementDeltaMm'])
        by_def = sorted({r['definition'] for r in losses})
        return _result(
            cid, 'fail', 'FAC-LEN-001',
            f"{len(losses)} of {evaluated} affected fastener occurrences lose thread "
            f"engagement. {worst['definition']} at {worst['fastener']} must span "
            f"{worst['proposedGripMm']} mm of material (was {worst['currentGripMm']} mm) "
            f"on an unchanged {worst['currentLengthMm']} mm fastener -- "
            f"{abs(worst['engagementDeltaMm'])} mm short. Thickened: "
            f"{', '.join(worst['thickenedMembers']) or 'n/a'}.",
            measured={'engagementLosses': len(losses),
                      'evaluatedOccurrences': evaluated,
                      'worstEngagementDeltaMm': worst['engagementDeltaMm'],
                      'definitionsAffected': by_def, 'detail': losses},
            tolerance={'minEngagementDeltaMm': -ENGAGEMENT_TOL_MM,
                       'note': 'relative to the current build only. Absolute fastener '
                               'adequacy is not claimed: the threaded member is not '
                               'derivable from a STEP file.'},
            affected=affected, affectedDefs=affected_defs)

    if off_ladder:
        return _result(
            cid, 'fail', 'FAC-LEN-002',
            f"{len(off_ladder)} fastener occurrences are assigned a length that is not "
            f"an available stock size: "
            f"{off_ladder[0]['definition']} at {off_ladder[0]['proposedLengthMm']} mm, "
            f"ladder {off_ladder[0]['stockLadder']}.",
            measured={'offLadder': off_ladder},
            tolerance={'note': 'stock ladder from data/mfg/stock.json when present, '
                               'otherwise the ISO 4762 fallback in derive_edges.STOCK'},
            affected=affected, affectedDefs=affected_defs)

    if evaluated == 0:
        return _result(cid, 'unchecked', 'FAC-LEN-U01',
                       'candidate changes no measured grip stack, so no joint '
                       'engagement is affected', measured={'evaluatedOccurrences': 0})

    return _result(
        cid, 'pass', 'FAC-LEN-000',
        f'all {evaluated} affected fastener occurrences retain at least their current '
        f'thread engagement',
        measured={'evaluatedOccurrences': evaluated, 'engagementLosses': 0},
        tolerance={'minEngagementDeltaMm': -ENGAGEMENT_TOL_MM,
                   'note': 'relative to the current build only; absolute adequacy '
                           'is not claimed.'})


# ---------------------------------------------------------------------------
# 3. CONTRACT -- is the candidate well-formed and does it stay inside its lane?
# ---------------------------------------------------------------------------

def check_contract(asm, contract, cand):
    cid = 'CONTRACT'
    errs = list(cand.schema_errors())
    affected, affected_defs = set(), set()

    for target in cand.targets():
        if target not in asm.defs:
            errs.append(('FAC-CON-002',
                         f"op target '{target}' is not a component definition in "
                         f"{contract.stepFile}"))
            affected_defs.add(target)
            continue
        if target in contract.protectedInterfaces:
            p = contract.protectedInterfaces[target]
            errs.append(('FAC-CON-003',
                         f"'{target}' is a protected interface ({p.get('reason', '')}) "
                         f"and may not be altered by a candidate"))
            affected_defs.add(target)
            affected.update(asm.defs[target])

    if errs:
        code = errs[0][0]
        return _result(cid, 'fail', code,
                       '; '.join(m for _, m in errs),
                       measured={'violationCount': len(errs),
                                 'violations': [{'reasonCode': c, 'message': m}
                                                for c, m in errs],
                                 'targets': cand.targets()},
                       tolerance={'protectedInterfaces': sorted(contract.protectedInterfaces),
                                  'operationVocabulary': sorted(OPS)},
                       affected=affected, affectedDefs=affected_defs)

    return _result(cid, 'pass', 'FAC-CON-000',
                   f'{len(cand.ops)} operations are well-formed, resolve to real '
                   f'component definitions, and touch no protected interface',
                   measured={'operations': len(cand.ops), 'targets': cand.targets()},
                   tolerance={'protectedInterfaces': sorted(contract.protectedInterfaces)})


# ---------------------------------------------------------------------------
# 4. ARTIFACT -- is this the baseline the contract pinned?
# ---------------------------------------------------------------------------

def check_artifact(asm, contract):
    cid = 'ARTIFACT'
    problems = []
    if contract.stepSha256 and contract.stepSha256 != asm.stepSha256:
        problems.append(('FAC-ART-001',
                         f'baseline STEP sha256 {asm.stepSha256[:16]} does not match the '
                         f'contract pin {contract.stepSha256[:16]}'))
    if contract.corpusRevision and contract.corpusRevision != asm.corpusRevision:
        problems.append(('FAC-ART-002',
                         f'graph corpusRevision {asm.corpusRevision} does not match the '
                         f'contract pin {contract.corpusRevision}'))
    if contract.checkSetVersion != CHECK_SET_VERSION:
        problems.append(('FAC-ART-003',
                         f'check set {CHECK_SET_VERSION} does not match the contract pin '
                         f'{contract.checkSetVersion}'))
    measured = {'stepSha256': asm.stepSha256, 'corpusRevision': asm.corpusRevision,
                'checkSetVersion': CHECK_SET_VERSION, 'contractSource': contract.source}
    if problems:
        return _result(cid, 'fail', problems[0][0], '; '.join(m for _, m in problems),
                       measured=measured,
                       tolerance={'stepSha256': contract.stepSha256,
                                  'corpusRevision': contract.corpusRevision,
                                  'checkSetVersion': contract.checkSetVersion})
    return _result(cid, 'pass', 'FAC-ART-000',
                   'baseline artifact hash, graph corpus revision, and check-set '
                   'version all match the object contract',
                   measured=measured)


# ---------------------------------------------------------------------------
# 5. INVENTORY -- is the component population the one the contract describes?
# ---------------------------------------------------------------------------

def check_inventory(asm, contract):
    cid = 'INVENTORY'
    n_occ, n_def = len(asm.occurrences), len(asm.defs)
    measured = {'occurrences': n_occ, 'definitions': n_def}
    tol = {'expectedOccurrences': contract.expectedOccurrences,
           'expectedDefinitions': contract.expectedDefinitions}
    bad = []
    if contract.expectedOccurrences is not None and n_occ != contract.expectedOccurrences:
        bad.append(f'{n_occ} occurrences, contract expects {contract.expectedOccurrences}')
    if contract.expectedDefinitions is not None and n_def != contract.expectedDefinitions:
        bad.append(f'{n_def} definitions, contract expects {contract.expectedDefinitions}')
    if bad:
        return _result(cid, 'fail', 'FAC-INV-001', '; '.join(bad),
                       measured=measured, tolerance=tol)
    return _result(cid, 'pass', 'FAC-INV-000',
                   f'{n_occ} occurrences across {n_def} definitions, as pinned by the '
                   f'object contract', measured=measured, tolerance=tol)
