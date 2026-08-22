"""track.result/1  ->  nightshift.track-result/v1.

A thin, one-way adapter. It does not import, subclass or modify ``evaluate.py``,
``fea.py`` or ``manifest.py`` -- those are merged, tested and fixture-frozen.
It takes the result dict the evaluator already emits and re-expresses it in the
frozen Step 02 (#43) envelope.

See ``tools/factory/contract_adapter.py`` for why the envelope below is
extrapolated rather than transcribed: the ``.artifacts/worktrees/issue43``
path does not exist, and ``nightshift.track-result/v1`` has never appeared in
this repository's history. The envelope is taken from
``attempt1/physgen/lab/problem.py`` (which enforces the shared #43 envelope
exactly), and the body fields from the contract-to-UI mapping table in
``PHYSGEN_UI_CONTEXT_ISSUES_42_50.md``: ``status``, ``metrics``, ``score``,
``rank``, ``feedback_recommended``.

THE BOUNDARY THIS FILE ENFORCES
-------------------------------
#43 states the rule as: *a candidate with a failed Factory verdict cannot have
a Track result.* That is enforced here structurally, not by convention --
:func:`to_track_result` requires the candidate's Factory verdict and raises
:class:`FactoryRejectedError` if it is not a pass. There is no flag to bypass
it and no code path that produces a record without it.

Note this is a second, independent gate. ``tools/track/manifest.py`` already
refuses to parse a survivor manifest whose entries are not ``verdict == 'pass'``
and gives Rejected records no mask to solve. This adapter closes the same door
at the emit end, so a TrackResult cannot be minted from a rejected candidate
even by a caller that bypassed the manifest entirely.

Usage::

    from contract_adapter import (
        to_track_result, NIGHTSHIFT_UNITS, track_creation_method)

    record = to_track_result(
        raw_result,
        factory_verdict=verdict_record,          # required; gates the emit
        run_id='run.neoracer-2026-08-22',
        units=NIGHTSHIFT_UNITS,
        creation_method=track_creation_method('track.result/1'))
"""

from __future__ import annotations

import json
import math
import re

SCHEMA_VERSION = 'nightshift.track-result/v1'

# --------------------------------------------------------------------------
# MAPPING TABLE 1 -- output field names.
#
# This is the table to edit when the real #43 schema lands. Renaming a contract
# field is one line here; nothing below or at any call site needs to move.
# --------------------------------------------------------------------------
FIELDS = {
    # envelope, shared by every #43 entity (see problem.py:_REQUIRED_TOP_LEVEL)
    'schema_version':       'schema_version',
    'id':                   'id',
    'run_id':               'run_id',
    'parent_ids':           'parent_ids',
    'source_hashes':        'source_hashes',
    'units':                'units',
    'creation_method':      'creation_method',
    'evidence_sources':     'evidence_sources',
    # TrackResult body (PHYSGEN_UI_CONTEXT_ISSUES_42_50.md, "Track comparison")
    'candidate_id':         'candidate_id',
    'status':               'status',
    'metrics':              'metrics',
    'score':                'score',
    'rank':                 'rank',
    'feedback_recommended': 'feedback_recommended',
}

# MAPPING TABLE 2 -- metric names: track.result/1 key -> contract metric key.
#
# The evaluator carries units in the key suffix (Nmm, Mm, Seconds). The
# contract declares units once in the envelope, so the suffixes are dropped
# here and the unit is recorded in the comment column. Anything not listed is
# not emitted -- that is deliberate, so a new evaluator key cannot silently
# appear in a record the contract has not declared.
MEASURE_METRICS = {
    'complianceNmm':             'compliance',                  # N*mm
    'compliancePerCaseNmm':      'compliance_per_load_case',     # N*mm, per case
    'maxDisplacementMm':         'max_displacement',             # mm
    'maxDisplacementLoadCase':   'max_displacement_load_case',   # load-case name
    'maxDisplacementAtXZMm':     'max_displacement_at_xz',       # [x, z] mm
    'solidCells':                'solid_cells',                  # count
    'materialFractionOfDomain':  'material_fraction_of_domain',  # dimensionless
    'unbackedFixtureNodes':      'unbacked_fixture_nodes',       # count
    'solveSeconds':              'solve_seconds',                # s
}

# Baseline-relative metrics. Issue 48 requires the baseline comparison be
# visible next to the absolute numbers, so they land in the same `metrics` map.
RELATIVE_METRICS = {
    'complianceRatioToBaseline':      'compliance_ratio_to_baseline',
    'materialRatioToBaseline':        'material_ratio_to_baseline',
    'maxDisplacementRatioToBaseline': 'max_displacement_ratio_to_baseline',
    'specificStiffnessRatio':         'specific_stiffness_ratio',
}

# MAPPING TABLE 3 -- solver state -> contract status.
#
# #43 allows exactly `measured` and `solver_failed`. The evaluator has four
# states, so two judgement calls are recorded here explicitly:
#
#   load_path_lost   -> measured. The solve succeeded; compliance blew up past
#                       BLOWUP_RATIO because the structure is disconnected.
#                       That is a real measurement of a bad design, and Issue 48
#                       requires a known-poor survivor stay visible. Calling it
#                       solver_failed would hide a genuine result as an error.
#   fixture_unsupported -> solver_failed. Loaded or held nodes have no material
#                       under them, so the number produced is meaningless.
STATUS_MAP = {
    'ok':                  'measured',
    'load_path_lost':      'measured',
    'non_finite':          'solver_failed',
    'fixture_unsupported': 'solver_failed',
}

# The metric the documented ranking rule sorts on, primary key first.
# evaluate.py: "specificStiffnessRatio desc; ties by materialRatio asc, ..."
SCORE_SOURCE = 'specificStiffnessRatio'

# The exact units object problem.py accepts. Exported, never defaulted.
NIGHTSHIFT_UNITS = {
    'length': 'mm',
    'mass': 'kg',
    'time': 's',
    'force': 'N',
    'pressure': 'Pa',
    'density': 'kg/m^3',
}

# Field names read off the Factory side. Kept here so that if the Factory
# adapter's FIELDS table is edited, the mismatch surfaces as a loud failure at
# the boundary rather than as a silently-skipped gate.
FACTORY_VERDICT_FIELD = 'verdict'
FACTORY_CANDIDATE_FIELD = 'candidate_id'
FACTORY_FAILURE_CODES_FIELD = 'failure_codes'
FACTORY_CHECKS_FIELD = 'checks'
FACTORY_CHECK_ID_FIELD = 'check_id'
FACTORY_CHECK_OUTCOME_FIELD = 'outcome'
FACTORY_PASS_VALUE = 'pass'
FACTORY_SCHEMA_VERSION = 'nightshift.factory-verdict/v1'

_MIN_HEX = 16
_HEX_RE = re.compile(r'^[0-9a-f]+\Z')

# Track writes its digests as 'sha256:<hex>' while Factory writes bare hex, and
# problem.py's source_hash sub-object carries bare hex. Normalizing the two
# producers onto one representation is precisely why this adapter exists; if
# #43 turns out to want the prefix kept, drop this tuple.
_HASH_PREFIXES = ('sha256:',)


class ContractFieldError(ValueError):
    """A field the frozen contract requires has no source and was not supplied."""


class FactoryRejectedError(ValueError):
    """A Factory-rejected candidate was pushed at the Track contract boundary.

    #43: a candidate with a failed Factory verdict cannot have a Track result.
    Raised rather than warned, so the invariant cannot be violated by a caller
    that ignores return values.
    """


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _require(value, label):
    if value is None or (isinstance(value, (str, list, dict)) and not value):
        raise ContractFieldError(
            '%s is required by %s and has no source in track.result/1; '
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
            'units must match the frozen system %s; got %s' % (NIGHTSHIFT_UNITS, wrong))
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


def track_creation_method(solver_version):
    """The creation method for a deterministic Track solve.

    A convenience constructor; the result must still be passed explicitly.
    """
    _require(solver_version, 'solver_version')
    return {
        'kind': 'deterministic-fea',
        'name': 'nvidia_dell_hack_nyc tools/track',
        'version': solver_version,
        'deterministic': True,
    }


def _hex_digest(value, label):
    if isinstance(value, str):
        for prefix in _HASH_PREFIXES:
            if value.startswith(prefix):
                value = value[len(prefix):]
                break
    if not isinstance(value, str) or not _HEX_RE.match(value) or len(value) < _MIN_HEX:
        raise ContractFieldError(
            '%s must be a lowercase hex digest of at least %d characters '
            '(optionally %s-prefixed), got %r'
            % (label, _MIN_HEX, '/'.join(p.rstrip(':') for p in _HASH_PREFIXES), value))
    return value


def _finite(value):
    """#43 rejects non-finite numbers. bool is not a number; lists recurse."""
    if isinstance(value, bool) or not isinstance(value, (int, float, list, dict)):
        return value
    if isinstance(value, list):
        return [_finite(v) for v in value]
    if isinstance(value, dict):
        return {k: _finite(v) for k, v in value.items()}
    if not math.isfinite(value):
        raise ContractFieldError('non-finite number %r cannot enter %s'
                                 % (value, SCHEMA_VERSION))
    return value


_DROPPED = object()


def _finite_or_drop(value):
    """Like _finite, but drops non-finite values instead of raising.

    Used only for a solver_failed result. `evaluate.py` still writes inf/nan
    into the measures of a non-finite solve, and #43 rejects those -- but the
    record itself must still exist, because a solve that failed is a fact the
    run has to carry. So the failure is reported and the unusable numbers are
    omitted, rather than the whole record being refused.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, list, dict)):
        return value
    if isinstance(value, list):
        kept = [_finite_or_drop(v) for v in value]
        return _DROPPED if any(v is _DROPPED for v in kept) else kept
    if isinstance(value, dict):
        kept = {k: _finite_or_drop(v) for k, v in value.items()}
        return {k: v for k, v in kept.items() if v is not _DROPPED}
    return value if math.isfinite(value) else _DROPPED


# --------------------------------------------------------------------------
# the boundary
# --------------------------------------------------------------------------

def assert_factory_passed(factory_verdict, candidate_id):
    """The #43 transition rule, enforced.

    Accepts a nightshift.factory-verdict/v1 record (the Factory adapter's
    output). Raises FactoryRejectedError unless it is a pass for this exact
    candidate.
    """
    if not isinstance(factory_verdict, dict):
        raise FactoryRejectedError(
            'candidate %r: a Factory verdict is required before a TrackResult '
            'may exist; got %r' % (candidate_id, type(factory_verdict)))

    schema = factory_verdict.get('schema_version')
    if schema != FACTORY_SCHEMA_VERSION:
        raise FactoryRejectedError(
            'candidate %r: expected a %s record at the Track boundary, got '
            'schema_version=%r. Adapt the raw FactoryVerdict/1 with '
            'tools/factory/contract_adapter.to_factory_verdict first.'
            % (candidate_id, FACTORY_SCHEMA_VERSION, schema))

    verdict_candidate = factory_verdict.get(FACTORY_CANDIDATE_FIELD)
    # Compared as strings: `1 == True` in Python, and this is the identity
    # check the whole invariant rests on.
    if (not isinstance(verdict_candidate, str) or not isinstance(candidate_id, str)
            or verdict_candidate != candidate_id):
        raise FactoryRejectedError(
            'Factory verdict is for candidate %r but the Track result is for %r; '
            'a verdict may not be used to clear a different candidate'
            % (verdict_candidate, candidate_id))

    outcome = factory_verdict.get(FACTORY_VERDICT_FIELD)
    if outcome != FACTORY_PASS_VALUE:
        raise FactoryRejectedError(
            'candidate %r was rejected by Factory (verdict=%r, failure_codes=%s) '
            'and therefore cannot have a TrackResult -- #43 forbids the '
            'transition. Keep it visible as a rejected candidate instead.'
            % (candidate_id, outcome, factory_verdict.get(FACTORY_FAILURE_CODES_FIELD)))

    # The top-level string is not taken on trust. A verdict that says `pass`
    # while carrying a failing check is self-contradictory, and resolving that
    # contradiction in favour of `pass` is exactly the mistake the #43
    # transition rule exists to prevent.
    codes = factory_verdict.get(FACTORY_FAILURE_CODES_FIELD)
    if codes:
        raise FactoryRejectedError(
            'candidate %r has verdict=%r but reports failure codes %s; refusing '
            'to mint a TrackResult from a self-contradictory verdict'
            % (candidate_id, outcome, codes))
    failing = [c.get(FACTORY_CHECK_ID_FIELD)
               for c in factory_verdict.get(FACTORY_CHECKS_FIELD) or ()
               if c.get(FACTORY_CHECK_OUTCOME_FIELD) == 'fail']
    if failing:
        raise FactoryRejectedError(
            'candidate %r has verdict=%r but checks %s failed; refusing to mint '
            'a TrackResult from a self-contradictory verdict'
            % (candidate_id, outcome, failing))
    return True


# --------------------------------------------------------------------------
# the adapter
# --------------------------------------------------------------------------

def to_track_result(raw, factory_verdict=None, run_id=None, units=None,
                    creation_method=None, feedback_recommended=None,
                    candidate_entity_prefix='candidate'):
    """Re-express one track.result/1 dict as nightshift.track-result/v1.

    ``raw`` is one entry from ``report['results']`` as written by
    ``tools/track/evaluate.py``. It is never mutated.

    ``factory_verdict`` is the candidate's nightshift.factory-verdict/v1 record
    and is **required** -- it gates the emit. A rejected candidate raises
    FactoryRejectedError.

    ``run_id``, ``units`` and ``creation_method`` must be supplied; omitting any
    raises ContractFieldError rather than inventing a value.

    ``feedback_recommended`` may be passed explicitly. When omitted it is
    derived: feedback is recommended when the solve did not produce a usable
    measurement, or when a survivor missed the documented target.
    """
    if not isinstance(raw, dict):
        raise TypeError('expected a track.result/1 dict, got %r' % type(raw))
    if raw.get('schemaVersion') != 'track.result/1':
        raise ContractFieldError(
            'expected schemaVersion track.result/1, got %r -- this adapter maps '
            'that shape only' % raw.get('schemaVersion'))

    candidate_id = _require(raw.get('candidateId'), 'candidateId')

    # The boundary. Before anything else is computed.
    assert_factory_passed(factory_verdict, candidate_id)

    run_id = _require(run_id, 'run_id')
    units = _require_units(units)
    creation_method = _require_creation_method(creation_method)

    measures = raw.get('measures') or {}
    relative = raw.get('relative') or {}

    state = measures.get('state')
    if state not in STATUS_MAP:
        raise ContractFieldError(
            'candidate %r: solver state %r has no mapping to a %s status; add it '
            'to STATUS_MAP' % (candidate_id, state, SCHEMA_VERSION))
    status = STATUS_MAP[state]

    # ---- metrics --------------------------------------------------------
    # A measured result must carry finite numbers or it is not a measurement.
    # A solver_failed result keeps whatever survived, so the failure is still
    # reportable; see _finite_or_drop.
    keep = _finite if status == 'measured' else _finite_or_drop
    metrics = {}
    for source, table in ((measures, MEASURE_METRICS), (relative, RELATIVE_METRICS)):
        for source_key, contract_key in table.items():
            if source_key in source:
                value = keep(source[source_key])
                if value is not _DROPPED:
                    metrics[contract_key] = value
    if status == 'measured':
        _require(metrics, 'metrics')

    # ---- score ----------------------------------------------------------
    # The score is the documented ranking primary. A solver_failed candidate
    # has no defensible score; emitting one would let a meaningless number into
    # a comparison table.
    score = _finite(relative.get(SCORE_SOURCE)) if status == 'measured' else None

    # ---- feedback_recommended -------------------------------------------
    if feedback_recommended is None:
        feedback_recommended = bool(
            status != 'measured' or raw.get('meetsTarget') is False)
    if not isinstance(feedback_recommended, bool):
        raise ContractFieldError('feedback_recommended must be a bool, got %r'
                                 % type(feedback_recommended))

    # ---- source hashes --------------------------------------------------
    # The fixture hash is what makes a ranking comparable; Issue 48 requires it
    # stay visible next to the comparison.
    source_hashes = []
    for source_id, value in (('source.fixture', raw.get('fixtureHash')),
                             ('source.problem', raw.get('problemHash')),
                             ('source.occupancy-mask', raw.get('maskSha256'))):
        if value:
            source_hashes.append({'source_id': source_id,
                                  'sha256': _hex_digest(value, source_id)})
    _require(source_hashes, 'source_hashes')

    # ---- lineage --------------------------------------------------------
    # A TrackResult descends from the candidate and from the verdict that
    # cleared it. Recording the verdict edge makes the #43 transition rule
    # auditable from the result alone.
    parent_ids = ['%s.%s' % (candidate_entity_prefix, candidate_id)]
    verdict_id = factory_verdict.get('id')
    if verdict_id:
        parent_ids.append(verdict_id)

    return {
        FIELDS['schema_version']:       SCHEMA_VERSION,
        FIELDS['id']:                   'track-result.%s' % candidate_id,
        FIELDS['run_id']:               run_id,
        FIELDS['parent_ids']:           parent_ids,
        FIELDS['source_hashes']:        source_hashes,
        FIELDS['units']:                units,
        FIELDS['creation_method']:      creation_method,
        FIELDS['evidence_sources']:     [],
        FIELDS['candidate_id']:         candidate_id,
        FIELDS['status']:               status,
        FIELDS['metrics']:              metrics,
        FIELDS['score']:                score,
        FIELDS['rank']:                 _finite(raw.get('rank')),
        FIELDS['feedback_recommended']: feedback_recommended,
    }


def to_track_results(raws, verdicts_by_candidate, **kwargs):
    """Adapt a set of track.result/1 entries against their Factory verdicts.

    ``verdicts_by_candidate`` maps candidate id -> nightshift.factory-verdict/v1
    record. A result whose candidate has no verdict raises FactoryRejectedError:
    absence of a verdict is not permission to proceed.
    """
    out = []
    for raw in raws:
        candidate_id = raw.get('candidateId')
        out.append(to_track_result(
            raw, factory_verdict=verdicts_by_candidate.get(candidate_id), **kwargs))
    return out


def canonical_json(record):
    """Byte-stable serialization, matching how tools/track writes evidence.

    allow_nan=False so a non-finite value that slipped past _finite raises here
    rather than being written as a bare NaN literal that is not valid JSON.
    """
    return json.dumps(record, indent=2, sort_keys=True, allow_nan=False) + '\n'
