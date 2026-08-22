"""FactoryVerdict/1  ->  nightshift.factory-verdict/v1.

A thin, one-way adapter. It does not import, subclass, or modify ``verdict.py``
or ``checks.py`` -- those are merged, tested and NeoRacer-validated, and this
module deliberately owns none of their behaviour. It takes the dict they
already emit and re-expresses it in the frozen Step 02 (#43) envelope.

WHAT IS GROUND TRUTH HERE AND WHAT IS NOT
-----------------------------------------
The #43 contracts were said to live in ``.artifacts/worktrees/issue43/...``.
That path does not exist -- not on disk, not in any commit on any branch -- and
the strings ``nightshift.factory-verdict/v1`` and ``nightshift.track-result/v1``
have never appeared in this repository's history. So the envelope below is not
transcribed from the frozen schema; it is extrapolated from the two places that
*are* readable and authoritative:

  1. ``attempt1/physgen/lab/problem.py``, which enforces
     ``nightshift.design-problem/v1`` with ``_exact_object`` -- rejecting both
     missing and unknown keys. That gives the exact envelope every #43 entity
     shares (schema_version, id, run_id, parent_ids, source_hashes, units,
     creation_method, evidence_sources), the exact ``units`` dict, and the
     ``creation_method`` / ``source_hash`` / ``evidence_source`` sub-shapes.
  2. The contract-to-UI mapping table in ``PHYSGEN_UI_CONTEXT_ISSUES_42_50.md``,
     which names the FactoryVerdict body fields in snake_case: ``verdict``,
     ``checks``, ``failure_codes``, ``elapsed_ms``; and the Issue 47 section,
     which requires every check to expose check id, outcome, measured value,
     operator, threshold, implicated components and evidence links.

Everything that could change when the real schema lands is confined to the
mapping tables at the top of this file. Renaming a field, changing the schema
version string, or remapping an outcome value is a one-line edit there -- no
call site and no logic below needs to move.

Usage::

    from contract_adapter import (
        to_factory_verdict, NIGHTSHIFT_UNITS, factory_creation_method)

    record = to_factory_verdict(
        raw_verdict,
        run_id='run.neoracer-2026-08-22',
        units=NIGHTSHIFT_UNITS,
        creation_method=factory_creation_method(raw_verdict['checkSetVersion']),
        repo_root='/path/to/repo')
"""

from __future__ import annotations

import collections
import hashlib
import json
import math
import os
import re

SCHEMA_VERSION = 'nightshift.factory-verdict/v1'

# --------------------------------------------------------------------------
# MAPPING TABLE 1 -- output field names.
#
# This is the table to edit when the real #43 schema lands. Keys are the
# stable internal slots this module reasons about; values are the literal JSON
# keys written to the record. Renaming a contract field is one line here.
# --------------------------------------------------------------------------
FIELDS = {
    # envelope, shared by every #43 entity (see problem.py:_REQUIRED_TOP_LEVEL)
    'schema_version':   'schema_version',
    'id':               'id',
    'run_id':           'run_id',
    'parent_ids':       'parent_ids',
    'source_hashes':    'source_hashes',
    'units':            'units',
    'creation_method':  'creation_method',
    'evidence_sources': 'evidence_sources',
    # FactoryVerdict body (PHYSGEN_UI_CONTEXT_ISSUES_42_50.md, "Factory badge/details")
    'candidate_id':     'candidate_id',
    'verdict':          'verdict',
    'failure_codes':    'failure_codes',
    'checks':           'checks',
    'elapsed_ms':       'elapsed_ms',
}

# Per-check fields required by the Issue 47 section, in its own order.
CHECK_FIELDS = {
    'check_id':                 'check_id',
    'outcome':                  'outcome',
    'measured':                 'measured',
    'operator':                 'operator',
    'threshold':                'threshold',
    'implicated_component_ids': 'implicated_component_ids',
    'evidence_source_ids':      'evidence_source_ids',
}

# MAPPING TABLE 2 -- verdict and per-check outcome vocabularies.
# FactoryVerdict/1 already speaks pass/fail at the top level; the per-check
# `unchecked` state has no #43 equivalent and is passed through deliberately
# rather than being silently folded into `pass`.
VERDICT_MAP = {'pass': 'pass', 'fail': 'fail'}
OUTCOME_MAP = {'pass': 'pass', 'fail': 'fail', 'unchecked': 'unchecked'}

# The exact units object problem.py accepts. Callers must pass this in
# explicitly -- it is exported, not defaulted, so a run can never silently
# declare units it did not mean.
NIGHTSHIFT_UNITS = {
    'length': 'mm',
    'mass': 'kg',
    'time': 's',
    'force': 'N',
    'pressure': 'Pa',
    'density': 'kg/m^3',
}

# --------------------------------------------------------------------------
# MAPPING TABLE 3 -- how a scalar `measured` / `operator` / `threshold` triple
# is recovered from a FactoryVerdict/1 check.
#
# Issue 47 requires a measured value, an operator and a threshold per check.
# FactoryVerdict/1 instead carries free-form `measured` and `tolerance` dicts
# whose keys differ per check AND per outcome, and it never names an operator.
# Each check below lists its rules in priority order; the first whose `key` is
# present in `measured` wins. A rule with key=None is a catch-all whose
# `transform` receives the whole `measured` dict.
#
# `unit` is recorded for documentation and for the day the contract grows a
# per-check unit field; it is not emitted today, because #43 rejects unknown
# keys and the Issue 47 list has exactly seven entries.
# --------------------------------------------------------------------------
_M = collections.namedtuple('_M', 'key operator threshold unit transform')

_SAME_AS_MEASURED = object()   # threshold sentinel: contract pinned this value


def _tol(key, default):
    return ('tolerance', key, default)


def _const(value):
    return ('const', value, None)


CHECK_MEASUREMENT = {
    'CLEARANCE': (
        _M('maxPenetrationMm', '<=', _tol('maxPenetrationMm', 0.0), 'mm', None),
        _M('collidingOccurrences', '<=', _const(0), 'count', None),
    ),
    'FASTENER_LENGTH': (
        _M('worstEngagementDeltaMm', '>=', _tol('minEngagementDeltaMm', 0.0), 'mm', None),
        _M('offLadder', '==', _const(0), 'count', len),
        _M('engagementLosses', '<=', _const(0), 'count', None),
    ),
    'CONTRACT': (
        _M('violationCount', '==', _const(0), 'count', None),
        # A passing CONTRACT check reports {operations, targets} and no count;
        # passing means exactly zero violations.
        _M(None, '==', _const(0), 'count', lambda measured: 0),
    ),
    # ARTIFACT and INVENTORY can each fail on any one of several pinned values.
    # Every one gets a rule, because a failing check must report the comparison
    # that actually broke -- reporting a satisfied one next to a `fail` outcome
    # would put a passing-looking row under a rejected candidate.
    'ARTIFACT': (
        _M('stepSha256', '==', _tol('stepSha256', _SAME_AS_MEASURED), 'sha256', None),
        _M('corpusRevision', '==', _tol('corpusRevision', _SAME_AS_MEASURED), 'hex', None),
        _M('checkSetVersion', '==', _tol('checkSetVersion', _SAME_AS_MEASURED), 'version', None),
    ),
    # An object contract need not pin the counts. Unpinned means "no constraint
    # to violate", which is reported as measured == measured rather than as
    # `measured == null` -- Issue 47 requires a threshold on every check, and a
    # null one reads as a missing measurement instead of an absent constraint.
    'INVENTORY': (
        _M('occurrences', '==', _tol('expectedOccurrences', _SAME_AS_MEASURED), 'count', None),
        _M('definitions', '==', _tol('expectedDefinitions', _SAME_AS_MEASURED), 'count', None),
    ),
}

# Minimum length of a hex digest accepted into source_hashes. stepSha256 is a
# full sha256 (64); corpusRevision is a 16-hex fingerprint of the same corpus.
# If #43 turns out to require 64 everywhere, raise this to 64 -- one line.
_MIN_HEX = 16
_HEX_RE = re.compile(r'^[0-9a-f]+\Z')


class ContractFieldError(ValueError):
    """A field the frozen contract requires has no source and was not supplied.

    Raised instead of inventing a value. run_id, units and creation_method have
    no representation anywhere in tools/factory, so they are parameters, and
    their absence is an error rather than a default.
    """


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _require(value, label):
    if value is None or (isinstance(value, (str, list, dict)) and not value):
        raise ContractFieldError(
            '%s is required by %s and has no source in FactoryVerdict/1; '
            'pass it explicitly' % (label, SCHEMA_VERSION))
    return value


def _require_units(units):
    _require(units, 'units')
    if not isinstance(units, dict):
        raise ContractFieldError('units must be an object')
    missing = sorted(set(NIGHTSHIFT_UNITS) - set(units))
    unknown = sorted(set(units) - set(NIGHTSHIFT_UNITS))
    if missing or unknown:
        raise ContractFieldError(
            'units must declare exactly %s; missing=%s unknown=%s'
            % (sorted(NIGHTSHIFT_UNITS), missing, unknown))
    wrong = {k: units[k] for k in NIGHTSHIFT_UNITS if units[k] != NIGHTSHIFT_UNITS[k]}
    if wrong:
        raise ContractFieldError(
            'units must match the frozen system %s; got %s'
            % (NIGHTSHIFT_UNITS, wrong))
    return dict(units)


_CREATION_METHOD_FIELDS = ('kind', 'name', 'version', 'deterministic')


def _require_creation_method(method):
    _require(method, 'creation_method')
    if not isinstance(method, dict):
        raise ContractFieldError('creation_method must be an object')
    missing = sorted(set(_CREATION_METHOD_FIELDS) - set(method))
    unknown = sorted(set(method) - set(_CREATION_METHOD_FIELDS))
    if missing or unknown:
        raise ContractFieldError(
            'creation_method must declare exactly %s; missing=%s unknown=%s'
            % (list(_CREATION_METHOD_FIELDS), missing, unknown))
    return dict(method)


def factory_creation_method(check_set_version):
    """The creation method for a deterministic Factory check-set run.

    Offered as a convenience so callers do not hand-roll the sub-object, but it
    still has to be passed to to_factory_verdict() explicitly.
    """
    _require(check_set_version, 'checkSetVersion')
    return {
        'kind': 'deterministic-check-set',
        'name': 'nvidia_dell_hack_nyc tools/factory',
        'version': check_set_version,
        'deterministic': True,
    }


def _hex_digest(value, label):
    if not isinstance(value, str) or not _HEX_RE.match(value) or len(value) < _MIN_HEX:
        raise ContractFieldError(
            '%s must be a lowercase hex digest of at least %d characters, got %r'
            % (label, _MIN_HEX, value))
    return value


def _finite(value):
    """#43 rejects non-finite numbers. bool is not a number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    if not math.isfinite(value):
        raise ContractFieldError('non-finite number %r cannot enter %s'
                                 % (value, SCHEMA_VERSION))
    return value


def _repo_uri(path, repo_root):
    """#43 rejects machine-specific artifact paths; FactoryVerdict/1 writes an
    absolute one into evidencePath. Relativize it against the repo root."""
    if not path:
        return None
    if repo_root:
        # A relative evidencePath is relative to the repo, not to wherever the
        # process happened to be started. Resolving it against cwd would make
        # the emitted record depend on the caller's working directory.
        absolute = path if os.path.isabs(path) else os.path.join(repo_root, path)
        try:
            rel = os.path.relpath(os.path.abspath(absolute), os.path.abspath(repo_root))
        except ValueError:                        # different drive on Windows
            rel = path
    else:
        rel = path
    if rel.startswith('..') or os.path.isabs(rel):
        raise ContractFieldError(
            'evidencePath %r is outside repo_root %r; %s rejects machine-specific '
            'paths' % (path, repo_root, SCHEMA_VERSION))
    return 'repo://' + rel.replace(os.sep, '/')


def _sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(4 * 1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_threshold(spec, measured, tolerance):
    kind, key, default = spec
    if kind == 'const':
        return key
    # checks.py writes some tolerance keys unconditionally with a None value
    # (expectedOccurrences on an unpinned contract). A present-but-None entry
    # means "not pinned", so it must fall through to the default rather than
    # emitting `measured == null`.
    value = tolerance.get(key)
    if value is None:
        value = default
    if value is _SAME_AS_MEASURED:
        return measured
    return value


def _violates(value, operator, threshold):
    """True when this comparison is the one that broke.

    Used to pick which rule a failing check reports. A threshold that is not
    pinned cannot be violated.
    """
    if threshold is None or value is None:
        return False
    try:
        if operator == '<=':
            return value > threshold
        if operator == '>=':
            return value < threshold
        if operator == '==':
            return value != threshold
    except TypeError:                             # incomparable types
        return False
    return False


def _measurement(check, status):
    """Recover (measured, operator, threshold) for one check via CHECK_MEASUREMENT.

    Returns (None, None, None) when no rule matches, which happens only for an
    `unchecked` check -- a check that could not be evaluated has nothing to
    report, and saying so is more honest than emitting a zero.

    Catch-all rules (key=None) are skipped for an unchecked outcome for the same
    reason: they exist to supply the implied value of a decided check, and an
    unchecked check has decided nothing.
    """
    check_id = check.get('check')
    measured = check.get('measured') or {}
    tolerance = check.get('tolerance') or {}

    resolved = []
    for rule in CHECK_MEASUREMENT.get(check_id, ()):
        if rule.key is None:
            if status not in ('pass', 'fail'):
                continue
            value = rule.transform(measured)
        elif rule.key in measured:
            value = measured[rule.key]
            if rule.transform is not None:
                value = rule.transform(value)
        else:
            continue
        threshold = _resolve_threshold(rule.threshold, value, tolerance)
        resolved.append((_finite(value), rule.operator, _finite(threshold)))

    if not resolved:
        return None, None, None
    if status == 'fail':
        # Report the comparison that actually broke. A check with several
        # pinned values (ARTIFACT, INVENTORY) can fail on any one of them, and
        # the first rule in the table is not necessarily the guilty one.
        for triple in resolved:
            if _violates(*triple):
                return triple
    return resolved[0]


def _implicated(check):
    """Both definitions and occurrences identify implicated components: a
    definition names the part, an occurrence names the placed instance that
    actually collided. Dropping either loses information the UI needs."""
    ids = set(check.get('affectedDefinitions') or ())
    ids.update(check.get('affectedOccurrences') or ())
    return sorted(ids)


# --------------------------------------------------------------------------
# the adapter
# --------------------------------------------------------------------------

def to_factory_verdict(raw, run_id=None, units=None, creation_method=None,
                       repo_root=None, evidence_sha256=None,
                       candidate_entity_prefix='candidate'):
    """Re-express one FactoryVerdict/1 dict as nightshift.factory-verdict/v1.

    ``raw`` is the dict emitted by ``tools/factory/verdict.py:evaluate`` (or the
    JSON it writes). It is never mutated.

    ``run_id``, ``units`` and ``creation_method`` have no source anywhere in
    tools/factory and must be supplied; omitting any of them raises
    ContractFieldError rather than producing a record with an invented value.

    ``repo_root`` is required to relativize the absolute ``evidencePath``.
    ``evidence_sha256`` overrides hashing the evidence file (needed when the
    verdict has not been written to disk yet).
    """
    if not isinstance(raw, dict):
        raise TypeError('expected a FactoryVerdict/1 dict, got %r' % type(raw))
    if raw.get('schema') != 'FactoryVerdict/1':
        raise ContractFieldError(
            'expected schema FactoryVerdict/1, got %r -- this adapter maps that '
            'shape only' % raw.get('schema'))

    run_id = _require(run_id, 'run_id')
    units = _require_units(units)
    creation_method = _require_creation_method(creation_method)

    candidate_id = _require(raw.get('candidateId'), 'candidateId')
    verdict_value = raw.get('verdict')
    if verdict_value not in VERDICT_MAP:
        raise ContractFieldError(
            'verdict must be one of %s, got %r' % (sorted(VERDICT_MAP), verdict_value))

    # ---- evidence -------------------------------------------------------
    evidence_sources = []
    evidence_ids = []
    uri = _repo_uri(raw.get('evidencePath'), repo_root)
    if uri:
        if evidence_sha256 is None:
            abs_path = raw['evidencePath']
            if not os.path.isabs(abs_path) and repo_root:
                abs_path = os.path.join(repo_root, abs_path)
            if os.path.exists(abs_path):
                evidence_sha256 = _sha256_file(abs_path)
            else:
                raise ContractFieldError(
                    'evidence file %r does not exist and evidence_sha256 was not '
                    'supplied; %s references evidence by hash'
                    % (abs_path, SCHEMA_VERSION))
        evidence_id = 'evidence.factory-verdict.%s' % candidate_id
        evidence_sources.append({
            'evidence_id': evidence_id,
            'kind': 'verdict',
            'uri': uri,
            'sha256': _hex_digest(evidence_sha256, 'evidence sha256'),
        })
        evidence_ids.append(evidence_id)

    # ---- source hashes --------------------------------------------------
    source_hashes = []
    if raw.get('stepSha256'):
        source_hashes.append({
            'source_id': 'source.step-file',
            'sha256': _hex_digest(raw['stepSha256'], 'stepSha256'),
        })
    if raw.get('corpusRevision'):
        source_hashes.append({
            'source_id': 'source.corpus-revision',
            'sha256': _hex_digest(raw['corpusRevision'], 'corpusRevision'),
        })
    _require(source_hashes, 'source_hashes')

    # ---- checks ---------------------------------------------------------
    checks = []
    for check in raw.get('checks') or ():
        status = check.get('status')
        if status not in OUTCOME_MAP:
            raise ContractFieldError(
                'check %r has outcome %r, not one of %s'
                % (check.get('check'), status, sorted(OUTCOME_MAP)))
        measured, operator, threshold = _measurement(check, status)
        if status in ('pass', 'fail') and measured is None:
            raise ContractFieldError(
                'check %r resolved outcome %r but no measured value; add a rule '
                'to CHECK_MEASUREMENT[%r]' % (check.get('check'), status, check.get('check')))
        checks.append({
            CHECK_FIELDS['check_id']: check.get('check'),
            CHECK_FIELDS['outcome']: OUTCOME_MAP[status],
            CHECK_FIELDS['measured']: measured,
            CHECK_FIELDS['operator']: operator,
            CHECK_FIELDS['threshold']: threshold,
            CHECK_FIELDS['implicated_component_ids']: _implicated(check),
            CHECK_FIELDS['evidence_source_ids']: list(evidence_ids),
        })

    failure_codes = [c.get('reasonCode') for c in (raw.get('checks') or ())
                     if c.get('status') == 'fail']

    record = {
        FIELDS['schema_version']:   SCHEMA_VERSION,
        FIELDS['id']:               'factory-verdict.%s' % candidate_id,
        FIELDS['run_id']:           run_id,
        # A verdict descends from the candidate it judges; that edge is what
        # makes the lineage graph traversable from a verdict back to Lab.
        FIELDS['parent_ids']:       ['%s.%s' % (candidate_entity_prefix, candidate_id)],
        FIELDS['source_hashes']:    source_hashes,
        FIELDS['units']:            units,
        FIELDS['creation_method']:  creation_method,
        FIELDS['evidence_sources']: evidence_sources,
        FIELDS['candidate_id']:     candidate_id,
        FIELDS['verdict']:          VERDICT_MAP[verdict_value],
        FIELDS['failure_codes']:    failure_codes,
        FIELDS['checks']:           checks,
        FIELDS['elapsed_ms']:       _finite(raw.get('elapsedMs')),
    }
    # raw['parentId'] is deliberately not carried here: it is the *candidate's*
    # lineage and belongs on the Candidate record. Putting it on the verdict
    # would add a key the contract does not declare, which #43 rejects.
    return record


def to_factory_verdicts(raws, **kwargs):
    """Adapt a family of verdicts. Same required parameters as to_factory_verdict."""
    return [to_factory_verdict(raw, **kwargs) for raw in raws]


def passed(record):
    """True when a nightshift.factory-verdict/v1 record is a clean pass.

    Convenience for callers filtering a family before handing it to Track. The
    Track adapter does NOT import this -- it re-declares the field names it
    reads, so that a rename here fails its gate closed rather than silently
    widening it. This is the same predicate, kept in sync by
    tools/contract_smoke.py rather than by a shared import.
    """
    return (record.get(FIELDS['verdict']) == VERDICT_MAP['pass']
            and not record.get(FIELDS['failure_codes'])
            and not any(c.get(CHECK_FIELDS['outcome']) == 'fail'
                        for c in record.get(FIELDS['checks']) or ()))


def canonical_json(record):
    """Byte-stable serialization, matching how tools/factory writes evidence.

    allow_nan=False so a non-finite value that slipped past _finite raises here
    rather than being written as a bare NaN literal that is not valid JSON.
    """
    return json.dumps(record, indent=2, sort_keys=True, allow_nan=False) + '\n'
