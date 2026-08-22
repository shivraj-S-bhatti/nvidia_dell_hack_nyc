"""candidate.py -- what Factory accepts from Lab, and the object contract it checks against.

A candidate is a set of declared parametric operations on the baseline assembly, not
a new STEP file. That is a deliberate boundary: Factory can measure a declared delta
exactly (a shank grows N mm along its own axis; a clamped member grows N mm through
every stack containing it), whereas re-authoring B-rep without a CAD kernel would
force Factory to guess what changed and then measure its own guess.

Lab owns #12 and has not published a candidate family yet. This module IS the input
contract Lab writes to; the fixture under fixtures/ is Factory's stand-in until then
and is labelled as such in its own `provenance` field.
"""
import json

CHECK_SET_VERSION = 'factory-checks/1.0.0'

# Operations Factory can measure. Anything outside this vocabulary is a contract
# failure, never a silent pass -- an op Factory does not understand is an op Factory
# cannot clear.
OPS = {
    'fastener_length': {
        'doc': 'Substitute a different nominal length for a fastener definition or '
               'a listed set of its occurrences.',
        'required': ('op', 'target', 'newLengthMm'),
    },
    'thickness': {
        'doc': 'Change a component definition thickness by deltaMm. Every measured '
               'grip stack containing that component moves by the same delta.',
        'required': ('op', 'target', 'deltaMm'),
    },
}


class ObjectContract:
    """The baseline the candidates are deltas against, plus what may not be touched.

    Issue #11 (OBJECT) owns the authoritative contract. Factory reads it if present
    and otherwise falls back to the fixture, recording which one it used in the
    verdict so a replay cannot silently swap the baseline underneath a result.
    """

    def __init__(self, payload, source):
        self.source = source
        self.objectId = payload['objectId']
        self.stepFile = payload['stepFile']
        self.stepSha256 = payload.get('stepSha256')
        self.corpusRevision = payload.get('corpusRevision')
        self.checkSetVersion = payload.get('checkSetVersion', CHECK_SET_VERSION)
        self.expectedOccurrences = payload.get('expectedOccurrences')
        self.expectedDefinitions = payload.get('expectedDefinitions')
        # Protected interfaces are components a candidate may not alter: purchased
        # standard parts and mating surfaces the rest of the build is dimensioned to.
        self.protectedInterfaces = {p['definition']: p for p in
                                    payload.get('protectedInterfaces', [])}

    @staticmethod
    def load(path):
        return ObjectContract(json.load(open(path)), path)


class Candidate:
    """One Lab proposal: an id, its parent, and the ops that make it different."""

    def __init__(self, payload):
        self.raw = payload
        self.id = payload.get('candidateId')
        self.parentId = payload.get('parentId')
        self.label = payload.get('label', '')
        self.rationale = payload.get('rationale', '')
        self.ops = payload.get('ops', [])

    @staticmethod
    def load_family(path):
        payload = json.load(open(path))
        return payload, [Candidate(c) for c in payload['candidates']]

    def schema_errors(self):
        """Structural problems that make a candidate unmeasurable.

        Returned as (code, message) pairs rather than raised, because a malformed
        candidate must still produce a verdict -- an unreadable proposal is a
        rejection with a reason, not a crash that takes the family down with it.
        """
        errs = []
        if not self.id:
            errs.append(('FAC-CON-001', 'candidate is missing candidateId'))
        if not isinstance(self.ops, list):
            errs.append(('FAC-CON-001', 'ops must be a list'))
            return errs
        for i, op in enumerate(self.ops):
            if not isinstance(op, dict) or 'op' not in op:
                errs.append(('FAC-CON-001', f'ops[{i}] has no op field'))
                continue
            kind = op['op']
            if kind not in OPS:
                errs.append(('FAC-CON-004',
                             f"ops[{i}] op '{kind}' is outside the {CHECK_SET_VERSION} "
                             f"vocabulary {sorted(OPS)}; Factory cannot measure it"))
                continue
            for field in OPS[kind]['required']:
                if field not in op:
                    errs.append(('FAC-CON-001',
                                 f"ops[{i}] ({kind}) is missing required field '{field}'"))
        return errs

    def targets(self):
        """Definition names this candidate claims to change."""
        return sorted({op['target'] for op in self.ops
                       if isinstance(op, dict) and 'target' in op})
