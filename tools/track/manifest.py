"""manifest.py -- the Factory -> Track input contract, `track.survivor-manifest/1`.

Track (issue #14) may only measure candidates that Factory (issue #13) passed.
Factory's implementation does not exist yet, so this file states the contract
defensively from Track's side: exactly what Track requires, refusing anything
else BY NAME, and never guessing at a producer's intent.

Single hard invariant, straight from issue #14's acceptance criteria:

    Factory-rejected candidates cannot enter Track.

It is enforced by code, not assumed:

  * `Manifest.assert_admissible()` raises `RejectedCandidateError` the moment a
    rejected id reaches an evaluation call, and `entry()` / `mask()` route every
    lookup through it -- the correct call is also the shortest one;
  * `Manifest` is a frozen dataclass, so `rejected_ids` cannot be reassigned to
    switch the guard off;
  * a `Rejected` record carries NO mask reference at all, so a rejected candidate
    has no geometry in this document -- there is nothing to evaluate even if a
    caller ignores the guard entirely. A `rejected` object that does carry a
    `mask` key is refused at parse time;
  * `all_entries()` is the only sanctioned iteration order and contains no
    rejected candidate by construction.

Masks are hash-addressed. `load_mask()` verifies the sha256 of the file bytes and
the array shape before returning an array, so a manifest can never silently point
at geometry that changed under it. Two mask formats: `npy` (fast, binary, lives
under .artifacts/) and `rle-json` (text, diffable, safe to commit to git).

numpy + stdlib only, deterministic, offline: this ships to an ARM64 GB10 box with
networking disabled. Verify with `python3 tools/track/manifest.py`.
"""
import copy
import hashlib
import json
import math
import os
import re
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import numpy as np

__all__ = [
    "SCHEMA_VERSION", "MASK_RLE_SCHEMA_VERSION", "UNITS",
    "ManifestError", "RejectedCandidateError", "MaskIntegrityError",
    "MaskRef", "Entry", "Rejected", "Manifest",
    "load_manifest", "parse_manifest", "load_mask", "write_mask",
    "sha256_file", "sha256_bytes", "dump_manifest",
    "encode_rle", "decode_rle", "selftest",
]

SCHEMA_VERSION = "track.survivor-manifest/1"
MASK_RLE_SCHEMA_VERSION = "track.mask-rle/1"
UNITS = "mm"                      # issue #43 freezes millimetre declarations

# Exact key sets. Unknown keys are refused by name (issue #43: "Unknown fields
# must be rejected") -- a typo'd key in a producer is a silently dropped check,
# which is exactly the failure mode this stage exists to prevent.
_TOP_KEYS = frozenset({"schemaVersion", "runId", "producedBy", "problemId",
                       "problemHash", "domainShape", "units",
                       "baseline", "survivors", "rejected"})
_ENTRY_KEYS = frozenset({"candidateId", "parentId", "verdict", "mask",
                         "evidencePath", "factoryChecks", "notes"})
_REJECTED_KEYS = frozenset({"candidateId", "parentId", "verdict", "reasonCode",
                            "measured", "tolerance", "units", "implicated",
                            "evidencePath"})
_MASK_KEYS = frozenset({"path", "format", "sha256", "shape"})
_CHECK_KEYS = frozenset({"check", "result", "measured", "tolerance", "units"})
_MASK_FORMATS = frozenset({"npy", "rle-json"})
# Nullable fields may be omitted; they default to null/empty. Everything else
# must be present. Explicit nulls are preferred and are what dump_manifest emits.
_ENTRY_OPTIONAL = frozenset({"parentId", "evidencePath", "factoryChecks", "notes"})
_REJECTED_OPTIONAL = frozenset({"parentId", "measured", "tolerance", "units",
                                "implicated", "evidencePath"})
_CHECK_OPTIONAL = frozenset({"measured", "tolerance", "units"})

_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class ManifestError(ValueError):
    """A manifest, or a use of one, violated the frozen Factory -> Track contract."""


class RejectedCandidateError(ManifestError):
    """A Factory-rejected candidate id reached an evaluation call. Never recover from this."""


class MaskIntegrityError(ManifestError):
    """Mask bytes or shape disagree with what the manifest declared."""


# ---------------------------------------------------------------------------
# hashing
# ---------------------------------------------------------------------------

def sha256_bytes(b):
    """'sha256:<hex>' for a bytes object."""
    if isinstance(b, str):
        b = b.encode("utf-8")
    return "sha256:" + hashlib.sha256(b).hexdigest()


def sha256_file(path):
    """'sha256:<hex>' for the RAW FILE BYTES -- identical rule for npy and rle-json,
    so integrity does not depend on how the mask happens to be serialised."""
    h = hashlib.sha256()
    p = Path(path)
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


# ---------------------------------------------------------------------------
# error-message helpers. Every message says what was EXPECTED and what was FOUND;
# they are read by a human under time pressure with a demo clock running.
# ---------------------------------------------------------------------------

def _kind(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "boolean %s" % json.dumps(v)
    if isinstance(v, str):
        return "string %r" % v
    if isinstance(v, (int, float)):
        return "number %r" % v
    if isinstance(v, list):
        return "array %s" % json.dumps(v[:6])
    if isinstance(v, dict):
        return "object with keys %s" % sorted(v)
    return type(v).__name__


def _mapping(value, where):
    if not isinstance(value, dict):
        raise ManifestError("%s: expected a JSON object, found %s" % (where, _kind(value)))
    return value


def _reject_unknown(obj, allowed, where):
    extra = sorted(set(obj) - set(allowed))
    if extra:
        raise ManifestError(
            "%s: unknown key(s) %s; allowed keys are %s. This contract is frozen -- "
            "a key Track does not know is a check Track cannot honour."
            % (where, extra, sorted(allowed)))


def _require_keys(obj, required, where):
    missing = sorted(set(required) - set(obj))
    if missing:
        raise ManifestError("%s: missing required key(s) %s; required keys are %s"
                            % (where, missing, sorted(required)))


def _string(obj, key, where, nullable=False):
    v = obj.get(key)
    if v is None and nullable:
        return None
    if not isinstance(v, str) or (not nullable and not v.strip()):
        raise ManifestError("%s.%s: expected a %snon-empty string, found %s"
                            % (where, key, "null or a " if nullable else "", _kind(v)))
    return v


def _number(obj, key, where):
    """Nullable finite number. bool is rejected explicitly: in Python `True` passes
    isinstance(x, int), and a measured value of `true` is meaningless."""
    v = obj.get(key)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ManifestError("%s.%s: expected a finite number or null, found %s"
                            % (where, key, _kind(v)))
    if not math.isfinite(v):
        raise ManifestError("%s.%s: expected a finite number or null, found %r"
                            % (where, key, v))
    return v


def _sha256(obj, key, where):
    v = obj.get(key)
    if not isinstance(v, str) or not _SHA256_RE.match(v):
        raise ManifestError(
            "%s.%s: expected 'sha256:' followed by 64 lowercase hex digits, found %s"
            % (where, key, _kind(v)))
    return v


def _shape(value, where):
    """[nely, nelx], both positive ints. Row-major, rows first -- the same
    convention numpy uses, so shape tuples compare directly against array.shape."""
    if (not isinstance(value, list) or len(value) != 2
            or any(isinstance(x, bool) or not isinstance(x, int) or x <= 0 for x in value)):
        raise ManifestError("%s: expected [nely, nelx] with two positive integers, found %s"
                            % (where, _kind(value)))
    return (int(value[0]), int(value[1]))


def _mask_path(value, where):
    """Mask paths are RELATIVE to the manifest file. Absolute paths and `..` are
    refused: the manifest plus its directory must be replayable after being copied
    to the GB10, and a mask reference must not be able to read outside that tree."""
    if not isinstance(value, str) or not value.strip():
        raise ManifestError("%s: expected a non-empty relative path string, found %s"
                            % (where, _kind(value)))
    parts = PurePosixPath(value).parts
    if os.path.isabs(value) or value.startswith("/") or "\\" in value or ".." in parts:
        raise ManifestError(
            "%s: expected a relative POSIX path under the manifest directory "
            "(no leading '/', no '..', no '\\'), found %r" % (where, value))
    return value


# ---------------------------------------------------------------------------
# records
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MaskRef:
    path: str            # relative to the manifest directory
    format: str          # "npy" | "rle-json"
    sha256: str          # "sha256:<64 hex>" over the raw file bytes
    shape: tuple         # (nely, nelx)

    def to_json(self):
        return {"path": self.path, "format": self.format,
                "sha256": self.sha256, "shape": [int(self.shape[0]), int(self.shape[1])]}


@dataclass(frozen=True)
class Entry:
    """A candidate Factory passed. Only these may be measured by Track."""
    candidate_id: str
    parent_id: object          # str or None
    verdict: str               # always "pass"
    mask: MaskRef
    evidence_path: object      # str or None
    factory_checks: tuple      # tuple of plain dicts, 1:1 with the JSON shape
    notes: object              # str or None

    def to_json(self):
        return {"candidateId": self.candidate_id, "parentId": self.parent_id,
                "verdict": self.verdict, "mask": self.mask.to_json(),
                "evidencePath": self.evidence_path,
                "factoryChecks": [dict(c) for c in self.factory_checks],
                "notes": self.notes}


@dataclass(frozen=True)
class Rejected:
    """A candidate Factory vetoed. Deliberately has NO mask field: a rejected
    candidate publishes no geometry into Track's input, so it cannot be measured
    even by a caller who ignores every guard below."""
    candidate_id: str
    parent_id: object
    verdict: str               # always "fail"
    reason_code: str           # e.g. FACTORY.CONNECTIVITY_BROKEN
    measured: object
    tolerance: object
    units: object
    implicated: tuple
    evidence_path: object

    def to_json(self):
        return {"candidateId": self.candidate_id, "parentId": self.parent_id,
                "verdict": self.verdict, "reasonCode": self.reason_code,
                "measured": self.measured, "tolerance": self.tolerance,
                "units": self.units, "implicated": list(self.implicated),
                "evidencePath": self.evidence_path}

    def describe(self):
        """One line a human can act on -- reused verbatim in guard errors."""
        bits = ["reason=%s" % self.reason_code]
        if self.measured is not None:
            bits.append("measured=%s" % self.measured)
        if self.tolerance is not None:
            bits.append("tolerance=%s" % self.tolerance)
        if self.units:
            bits.append("units=%s" % self.units)
        if self.implicated:
            bits.append("implicated=%s" % list(self.implicated))
        return ", ".join(bits)


@dataclass(frozen=True)
class Manifest:
    """Frozen on purpose. `rejected_ids` is the guard; if the object were mutable a
    caller could disable the single hard invariant with one assignment."""
    schema_version: str
    run_id: str
    produced_by: str
    problem_id: str
    problem_hash: str
    domain_shape: tuple
    units: str
    baseline: Entry
    survivors: tuple
    rejected: tuple
    base_dir: Path
    rejected_ids: frozenset = field(init=False, repr=False)
    admissible_ids: frozenset = field(init=False, repr=False)

    def __post_init__(self):
        object.__setattr__(self, "rejected_ids",
                           frozenset(r.candidate_id for r in self.rejected))
        object.__setattr__(self, "admissible_ids",
                           frozenset([self.baseline.candidate_id])
                           | frozenset(s.candidate_id for s in self.survivors))

    # -- the guard ---------------------------------------------------------
    def assert_admissible(self, candidate_id):
        """THE invariant. Raises before any evaluation touches a rejected candidate.

        RejectedCandidateError -> Factory vetoed this id; it is not a Track input.
        ManifestError          -> the id is not in this manifest at all.
        """
        if candidate_id in self.rejected_ids:
            rej = self.rejection(candidate_id)
            raise RejectedCandidateError(
                "candidate %r was REJECTED by Factory (%s) and must never enter Track "
                "(run %s). Admissible ids are %s."
                % (candidate_id, rej.describe() if rej else "no record",
                   self.run_id, sorted(self.admissible_ids)))
        if candidate_id not in self.admissible_ids:
            raise ManifestError(
                "unknown candidate %r in run %s: expected one of %s (rejected ids, "
                "which are also not evaluable: %s)"
                % (candidate_id, self.run_id, sorted(self.admissible_ids),
                   sorted(self.rejected_ids)))

    def entry(self, candidate_id):
        """Entry for an admissible candidate. Guarded -- use this, never a raw id."""
        self.assert_admissible(candidate_id)
        if self.baseline.candidate_id == candidate_id:
            return self.baseline
        for s in self.survivors:
            if s.candidate_id == candidate_id:
                return s
        raise ManifestError("internal: %r passed the guard but has no Entry" % candidate_id)

    def mask(self, candidate_id):
        """Verified (nely, nelx) uint8 mask for an admissible candidate. Guarded."""
        return load_mask(self.entry(candidate_id), self.base_dir)

    def rejection(self, candidate_id):
        """The Rejected record for a vetoed id, or None. For feedback back to Lab --
        this is the ONLY sanctioned way to read a rejected candidate."""
        for r in self.rejected:
            if r.candidate_id == candidate_id:
                return r
        return None

    def all_entries(self):
        """Baseline first, then survivors in manifest order. The only sanctioned
        iteration order for Track, and rejected-free by construction."""
        return (self.baseline,) + tuple(self.survivors)

    def to_json(self):
        return {"schemaVersion": self.schema_version, "runId": self.run_id,
                "producedBy": self.produced_by, "problemId": self.problem_id,
                "problemHash": self.problem_hash,
                "domainShape": [int(self.domain_shape[0]), int(self.domain_shape[1])],
                "units": self.units, "baseline": self.baseline.to_json(),
                "survivors": [s.to_json() for s in self.survivors],
                "rejected": [r.to_json() for r in self.rejected]}


# ---------------------------------------------------------------------------
# parsing
# ---------------------------------------------------------------------------

def _parse_mask_ref(doc, where, domain_shape):
    _mapping(doc, where)
    _reject_unknown(doc, _MASK_KEYS, where)
    _require_keys(doc, _MASK_KEYS, where)
    path = _mask_path(doc.get("path"), where + ".path")
    fmt = doc.get("format")
    if fmt not in _MASK_FORMATS:
        raise ManifestError("%s.format: expected one of %s, found %s"
                            % (where, sorted(_MASK_FORMATS), _kind(fmt)))
    digest = _sha256(doc, "sha256", where)
    shape = _shape(doc.get("shape"), where + ".shape")
    if shape != domain_shape:
        raise ManifestError(
            "%s.shape: expected the manifest domainShape %s, found %s. Track scores "
            "every candidate on one fixture; a differently shaped mask is not comparable."
            % (where, list(domain_shape), list(shape)))
    return MaskRef(path=path, format=fmt, sha256=digest, shape=shape)


def _parse_checks(value, where):
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ManifestError("%s: expected an array of check objects or null, found %s"
                            % (where, _kind(value)))
    out = []
    for i, raw in enumerate(value):
        w = "%s[%d]" % (where, i)
        _mapping(raw, w)
        _reject_unknown(raw, _CHECK_KEYS, w)
        _require_keys(raw, _CHECK_KEYS - _CHECK_OPTIONAL, w)
        name = _string(raw, "check", w)
        result = raw.get("result")
        if result != "pass":
            raise ManifestError(
                "%s.result: expected 'pass', found %s. This candidate is listed as a "
                "Factory survivor, so every check it carries must have passed."
                % (w, _kind(result)))
        out.append({"check": name, "result": result,
                    "measured": _number(raw, "measured", w),
                    "tolerance": _number(raw, "tolerance", w),
                    "units": _string(raw, "units", w, nullable=True)})
    return tuple(out)


def _parse_entry(doc, where, domain_shape):
    _mapping(doc, where)
    _reject_unknown(doc, _ENTRY_KEYS, where)
    _require_keys(doc, _ENTRY_KEYS - _ENTRY_OPTIONAL, where)
    verdict = doc.get("verdict")
    if verdict != "pass":
        raise ManifestError(
            "%s.verdict: expected 'pass', found %s. Only Factory-passed candidates "
            "belong in `baseline` or `survivors`; a failed candidate belongs in "
            "`rejected` and is never evaluated." % (where, _kind(verdict)))
    return Entry(
        candidate_id=_string(doc, "candidateId", where),
        parent_id=_string(doc, "parentId", where, nullable=True),
        verdict=verdict,
        mask=_parse_mask_ref(doc.get("mask"), where + ".mask", domain_shape),
        evidence_path=_string(doc, "evidencePath", where, nullable=True),
        factory_checks=_parse_checks(doc.get("factoryChecks"), where + ".factoryChecks"),
        notes=_string(doc, "notes", where, nullable=True))


def _parse_rejected(doc, where):
    _mapping(doc, where)
    # Named ahead of the generic unknown-key error because this specific mistake --
    # a vetoed candidate still shipping geometry -- is the one that would let a
    # rejected candidate be measured.
    if "mask" in doc:
        raise ManifestError(
            "%s: rejected candidates must not carry a 'mask' key. Factory-rejected "
            "geometry never enters Track; publish the evidence path instead." % where)
    _reject_unknown(doc, _REJECTED_KEYS, where)
    _require_keys(doc, _REJECTED_KEYS - _REJECTED_OPTIONAL, where)
    verdict = doc.get("verdict")
    if verdict != "fail":
        raise ManifestError(
            "%s.verdict: expected 'fail', found %s. Everything in `rejected` is a "
            "Factory veto." % (where, _kind(verdict)))
    implicated = doc.get("implicated")
    if implicated is None:
        implicated = []
    if not isinstance(implicated, list) or any(not isinstance(x, str) or not x for x in implicated):
        raise ManifestError("%s.implicated: expected an array of non-empty component or "
                            "region id strings, found %s" % (where, _kind(implicated)))
    return Rejected(
        candidate_id=_string(doc, "candidateId", where),
        parent_id=_string(doc, "parentId", where, nullable=True),
        verdict=verdict,
        reason_code=_string(doc, "reasonCode", where),
        measured=_number(doc, "measured", where),
        tolerance=_number(doc, "tolerance", where),
        units=_string(doc, "units", where, nullable=True),
        implicated=tuple(implicated),
        evidence_path=_string(doc, "evidencePath", where, nullable=True))


def parse_manifest(doc, base_dir=".", require_survivors=True):
    """Validate a manifest document and return a frozen `Manifest`.

    Structure only -- no mask file is read here, so parsing is cheap and a manifest
    can be validated before its artifacts are copied. `load_mask()` does the bytes.
    """
    where = "manifest"
    _mapping(doc, where)

    # schemaVersion first: everything below is only meaningful under this contract.
    ver = doc.get("schemaVersion")
    if ver != SCHEMA_VERSION:
        raise ManifestError(
            "%s.schemaVersion: expected %r, found %s. Track reads only this frozen "
            "contract; regenerate the manifest with the current Factory."
            % (where, SCHEMA_VERSION, _kind(ver)))
    _reject_unknown(doc, _TOP_KEYS, where)
    _require_keys(doc, _TOP_KEYS, where)

    run_id = _string(doc, "runId", where)
    produced_by = _string(doc, "producedBy", where)
    problem_id = _string(doc, "problemId", where)
    problem_hash = _sha256(doc, "problemHash", where)
    domain_shape = _shape(doc.get("domainShape"), where + ".domainShape")
    units = doc.get("units")
    if units != UNITS:
        raise ManifestError("%s.units: expected %r, found %s (issue #43 freezes "
                            "millimetre declarations)" % (where, UNITS, _kind(units)))

    baseline = _parse_entry(doc.get("baseline"), where + ".baseline", domain_shape)

    raw_survivors = doc.get("survivors")
    if not isinstance(raw_survivors, list):
        raise ManifestError("%s.survivors: expected an array of Entry objects, found %s"
                            % (where, _kind(raw_survivors)))
    survivors = tuple(_parse_entry(s, "%s.survivors[%d]" % (where, i), domain_shape)
                      for i, s in enumerate(raw_survivors))

    raw_rejected = doc.get("rejected")
    if not isinstance(raw_rejected, list):
        raise ManifestError("%s.rejected: expected an array of Rejected objects (use [] "
                            "when Factory vetoed nothing), found %s"
                            % (where, _kind(raw_rejected)))
    rejected = tuple(_parse_rejected(r, "%s.rejected[%d]" % (where, i))
                     for i, r in enumerate(raw_rejected))

    # Identity bookkeeping. An id in two sections is the exact ambiguity that could
    # let a vetoed candidate be measured, so it is named separately and first.
    sections = {}
    for cid, sec in ([(baseline.candidate_id, "baseline")]
                     + [(s.candidate_id, "survivors") for s in survivors]
                     + [(r.candidate_id, "rejected") for r in rejected]):
        sections.setdefault(cid, []).append(sec)
    both = sorted(c for c, s in sections.items() if "rejected" in s and set(s) - {"rejected"})
    if both:
        raise ManifestError(
            "%s: candidate id(s) %s appear in both the passed set and `rejected`. A "
            "candidate is a survivor or a veto, never both -- Track cannot decide "
            "which, and refuses to guess." % (where, both))
    dupes = sorted(c for c, s in sections.items() if len(s) > 1)
    if dupes:
        raise ManifestError(
            "%s: duplicate candidateId(s) %s; ids must be unique across baseline + "
            "survivors + rejected. Sections: %s"
            % (where, dupes, {c: sections[c] for c in dupes}))

    if require_survivors and not survivors:
        raise ManifestError(
            "%s.survivors: expected at least 1 survivor Entry, found 0. Track ranks "
            "Factory survivors against the baseline, so an empty survivor list has "
            "nothing to rank. A baseline-only manifest (Factory vetoed every "
            "candidate) is legitimate -- pass require_survivors=False to accept it."
            % where)

    return Manifest(schema_version=ver, run_id=run_id, produced_by=produced_by,
                    problem_id=problem_id, problem_hash=problem_hash,
                    domain_shape=domain_shape, units=units, baseline=baseline,
                    survivors=survivors, rejected=rejected,
                    base_dir=Path(base_dir))


def load_manifest(path, require_survivors=True):
    """Read and validate a manifest file. Mask paths resolve against its directory."""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise ManifestError("cannot read manifest %s: %s" % (p, exc))
    try:
        doc = json.loads(text)
    except ValueError as exc:
        raise ManifestError("manifest %s is not valid JSON: %s" % (p, exc))
    return parse_manifest(doc, base_dir=p.parent, require_survivors=require_survivors)


def dump_manifest(manifest_dict, path, validate=True):
    """Write canonical JSON: sort_keys=True, indent=2, trailing newline, ASCII.

    Byte-stable for the same document, which is what makes manifest hashes and
    3/3 repeated runs comparable. Validates first by default -- writing a manifest
    Track will refuse is a failure that should surface at the producer, not at Track.
    """
    p = Path(path)
    if validate:
        parse_manifest(manifest_dict, base_dir=p.parent, require_survivors=False)
    text = json.dumps(manifest_dict, sort_keys=True, indent=2,
                      ensure_ascii=True, allow_nan=False) + "\n"
    if p.parent and str(p.parent):
        p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# masks
# ---------------------------------------------------------------------------

def _as_binary_array(array, where):
    arr = np.asarray(array)
    if arr.ndim != 2:
        raise ManifestError("%s: expected a 2-D (nely, nelx) array, found ndim=%d shape=%s"
                            % (where, arr.ndim, list(arr.shape)))
    if arr.dtype.kind == "f" and not np.all(np.isfinite(arr)):
        raise ManifestError("%s: expected a binary 0/1 array, found non-finite values" % where)
    vals = np.unique(arr)
    if vals.size and not np.all((vals == 0) | (vals == 1)):
        bad = [x.item() for x in vals if x not in (0, 1)][:6]
        raise ManifestError("%s: expected a binary mask containing only 0 and 1, found "
                            "value(s) %s" % (where, bad))
    return np.ascontiguousarray(arr.astype(np.uint8))


def encode_rle(array):
    """Row-major run-length encoding: {"schemaVersion", "shape", "runs":[[value,count]]}.

    The git-safe mask format. npy is binary and diffs to noise; this is text, so a
    fixture mask can be committed and reviewed. Deterministic by construction.
    """
    arr = _as_binary_array(array, "encode_rle(array)")
    flat = arr.reshape(-1)
    if flat.size == 0:
        runs = []
    else:
        edges = np.flatnonzero(flat[1:] != flat[:-1]) + 1
        starts = np.concatenate(([0], edges))
        ends = np.concatenate((edges, [flat.size]))
        runs = [[int(flat[s]), int(e - s)] for s, e in zip(starts, ends)]
    return {"schemaVersion": MASK_RLE_SCHEMA_VERSION,
            "shape": [int(arr.shape[0]), int(arr.shape[1])],
            "runs": runs}


def decode_rle(doc):
    """Inverse of encode_rle, with the same paranoia as the manifest parser."""
    where = "mask-rle"
    if not isinstance(doc, dict):
        raise MaskIntegrityError("%s: expected a JSON object, found %s" % (where, _kind(doc)))
    ver = doc.get("schemaVersion")
    if ver != MASK_RLE_SCHEMA_VERSION:
        raise MaskIntegrityError("%s.schemaVersion: expected %r, found %s"
                                 % (where, MASK_RLE_SCHEMA_VERSION, _kind(ver)))
    extra = sorted(set(doc) - {"schemaVersion", "shape", "runs"})
    if extra:
        raise MaskIntegrityError("%s: unknown key(s) %s; allowed keys are "
                                 "['runs', 'schemaVersion', 'shape']" % (where, extra))
    try:
        shape = _shape(doc.get("shape"), where + ".shape")
    except ManifestError as exc:
        raise MaskIntegrityError(str(exc))
    runs = doc.get("runs")
    if not isinstance(runs, list):
        raise MaskIntegrityError("%s.runs: expected an array of [value, count] pairs, "
                                 "found %s" % (where, _kind(runs)))
    total = shape[0] * shape[1]
    flat = np.zeros(total, dtype=np.uint8)
    at = 0
    for i, run in enumerate(runs):
        if (not isinstance(run, list) or len(run) != 2
                or any(isinstance(x, bool) or not isinstance(x, int) for x in run)):
            raise MaskIntegrityError("%s.runs[%d]: expected [value, count] with two "
                                     "integers, found %s" % (where, i, _kind(run)))
        value, count = run
        if value not in (0, 1):
            raise MaskIntegrityError("%s.runs[%d]: expected value 0 or 1, found %r"
                                     % (where, i, value))
        if count <= 0:
            raise MaskIntegrityError("%s.runs[%d]: expected count >= 1, found %r"
                                     % (where, i, count))
        if at + count > total:
            raise MaskIntegrityError("%s.runs: runs overflow the declared shape %s "
                                     "(%d cells); reached %d at run %d"
                                     % (where, list(shape), total, at + count, i))
        if value:
            flat[at:at + count] = 1
        at += count
    if at != total:
        raise MaskIntegrityError("%s.runs: expected runs summing to %d cells for shape %s, "
                                 "found %d" % (where, total, list(shape), at))
    return flat.reshape(shape)


def write_mask(array, path, rel_to=None):
    """Persist a binary mask and return its MaskRef with a REAL sha256.

    Format follows the suffix: `.npy` -> numpy (fast, .artifacts/), `.json` ->
    rle-json (text, git-safe). `rel_to` sets the MaskRef path relative to the
    manifest directory -- manifests must never contain machine-specific absolute
    paths (AGENTS.md: no machine-specific venue state).
    """
    p = Path(path)
    arr = _as_binary_array(array, "write_mask(array)")
    suffix = p.suffix.lower()
    if suffix == ".npy":
        fmt = "npy"
    elif suffix == ".json":
        fmt = "rle-json"
    else:
        raise ManifestError("write_mask: expected a path ending in '.npy' or '.json', "
                            "found %r" % str(p))
    if str(p.parent):
        p.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "npy":
        with p.open("wb") as fh:
            np.save(fh, arr, allow_pickle=False)   # header is fixed-width: byte-stable
    else:
        p.write_text(json.dumps(encode_rle(arr), sort_keys=True, indent=2,
                                ensure_ascii=True, allow_nan=False) + "\n",
                     encoding="utf-8")
    ref_path = str(p)
    if rel_to is not None:
        ref_path = PurePosixPath(os.path.relpath(str(p.resolve()),
                                                 str(Path(rel_to).resolve()))).as_posix()
    return MaskRef(path=ref_path, format=fmt, sha256=sha256_file(p),
                   shape=(int(arr.shape[0]), int(arr.shape[1])))


def load_mask(entry_or_maskref, base_dir="."):
    """Return the (nely, nelx) uint8 0/1 mask for an Entry or MaskRef.

    Verifies the sha256 of the file bytes and the declared shape before returning.
    A mask that drifted from its manifest is a silent scoring bug; here it is loud.
    """
    if isinstance(entry_or_maskref, Rejected):
        raise RejectedCandidateError(
            "candidate %r was REJECTED by Factory (%s); rejected candidates carry no "
            "mask and are never evaluated by Track."
            % (entry_or_maskref.candidate_id, entry_or_maskref.describe()))
    if isinstance(entry_or_maskref, Entry):
        ref = entry_or_maskref.mask
        who = entry_or_maskref.candidate_id
    elif isinstance(entry_or_maskref, MaskRef):
        ref = entry_or_maskref
        who = ref.path
    else:
        raise ManifestError("load_mask: expected an Entry or MaskRef, found %s"
                            % type(entry_or_maskref).__name__)

    p = Path(base_dir) / ref.path
    if not p.is_file():
        raise MaskIntegrityError("mask for %s: expected a file at %s (declared path %r, "
                                 "resolved against %s), found none"
                                 % (who, p, ref.path, base_dir))
    found = sha256_file(p)
    if found != ref.sha256:
        raise MaskIntegrityError(
            "mask for %s: sha256 mismatch on %s -- manifest declares %s, file bytes hash "
            "to %s. The mask changed after the manifest was written; regenerate both."
            % (who, ref.path, ref.sha256, found))

    if ref.format == "npy":
        try:
            arr = np.load(str(p), allow_pickle=False)
        except Exception as exc:
            raise MaskIntegrityError("mask for %s: %s is not a readable .npy: %s"
                                     % (who, ref.path, exc))
    elif ref.format == "rle-json":
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise MaskIntegrityError("mask for %s: %s is not valid JSON: %s"
                                     % (who, ref.path, exc))
        arr = decode_rle(doc)
    else:
        raise MaskIntegrityError("mask for %s: unknown format %r; expected one of %s"
                                 % (who, ref.format, sorted(_MASK_FORMATS)))

    if tuple(arr.shape) != tuple(ref.shape):
        raise MaskIntegrityError(
            "mask for %s: shape mismatch on %s -- manifest declares %s, file contains %s"
            % (who, ref.path, list(ref.shape), list(arr.shape)))
    try:
        return _as_binary_array(arr, "mask for %s (%s)" % (who, ref.path))
    except ManifestError as exc:
        raise MaskIntegrityError(str(exc))


# ---------------------------------------------------------------------------
# selftest -- style mirrors tools/depgraph/check.py
# ---------------------------------------------------------------------------

def _fixture(base):
    """A minimal, realistic manifest: baseline + 2 survivors (one npy, one rle-json)
    + 1 real Factory veto. Written to `base`; returns the JSON document."""
    nely, nelx = 4, 6
    baseline = np.ones((nely, nelx), np.uint8)
    s1 = baseline.copy(); s1[1, 2] = 0
    s2 = baseline.copy(); s2[2, 3] = 0; s2[2, 4] = 0
    r_base = write_mask(baseline, base / "masks" / "baseline.npy", rel_to=base)
    r_s1 = write_mask(s1, base / "masks" / "cand-001.npy", rel_to=base)
    r_s2 = write_mask(s2, base / "masks" / "cand-002.mask.json", rel_to=base)

    def entry(cid, parent, ref, checks, notes):
        return {"candidateId": cid, "parentId": parent, "verdict": "pass",
                "mask": ref.to_json(),
                "evidencePath": "evidence/%s/factory.json" % cid,
                "factoryChecks": copy.deepcopy(checks), "notes": notes}

    checks = [
        {"check": "brep.valid_closed_solid", "result": "pass",
         "measured": 0.0, "tolerance": 0.0, "units": None},
        {"check": "interface.mount_hole_placement", "result": "pass",
         "measured": 0.04, "tolerance": 0.10, "units": "mm"},
        {"check": "connectivity.load_to_support", "result": "pass",
         "measured": 1.0, "tolerance": 1.0, "units": "fraction"},
    ]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "runId": "run-2026-08-22-selftest",
        "producedBy": "track-fixture",
        "problemId": "s500-arm-bracket-v1",
        "problemHash": sha256_bytes(b"s500-arm-bracket-v1"),
        "domainShape": [nely, nelx],
        "units": "mm",
        "baseline": entry("baseline", None, r_base, checks, "unmodified S500 baseline"),
        "survivors": [entry("cand-001", "baseline", r_s1, checks, None),
                      entry("cand-002", "baseline", r_s2, checks, None)],
        "rejected": [{
            "candidateId": "cand-003", "parentId": "baseline", "verdict": "fail",
            "reasonCode": "FACTORY.CONNECTIVITY_BROKEN",
            "measured": 0.0, "tolerance": 1.0, "units": "fraction",
            "implicated": ["ARM-MOUNT-FR", "BOTTOM-PLATE-S500"],
            "evidencePath": "evidence/cand-003/factory.json"}],
    }


# Collapses the run-specific temp directory out of echoed messages so repeated
# selftest runs are byte-identical -- the repo's bar is 3/3 agreeing runs.
_TMP_RE = re.compile(re.escape(tempfile.gettempdir().rstrip(os.sep)) + r"/[^/\s]+")


def _expect(exc_type, needle, fn, *a, **kw):
    """(ok, detail) -- fn must raise exc_type with `needle` in the message."""
    try:
        fn(*a, **kw)
    except exc_type as exc:
        msg = _TMP_RE.sub("$TMPDIR", str(exc).replace("\n", " "))
        if needle in msg:
            return True, msg[:110]
        return False, "message lacks %r: %s" % (needle, msg[:110])
    except Exception as exc:                                # noqa: BLE001
        return False, "wrong exception %s: %s" % (type(exc).__name__, str(exc)[:90])
    return False, "no exception raised (expected %s)" % exc_type.__name__


def selftest():
    fail = []

    def ck(name, cond, detail=''):
        print("  %s  %s%s" % ('PASS' if cond else 'FAIL', name, '  ' + str(detail) if detail else ''))
        if not cond:
            fail.append(name)

    def mut(doc, fn):
        d = copy.deepcopy(doc)
        fn(d)
        return d

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        doc = _fixture(base)
        path = dump_manifest(doc, base / "survivors.json")

        print("=== happy path ===")
        m = load_manifest(path)
        ck('manifest loads', isinstance(m, Manifest), m.run_id)
        ck('schema version pinned', m.schema_version == SCHEMA_VERSION)
        ck('2 survivors + 1 rejection', len(m.survivors) == 2 and len(m.rejected) == 1)
        ck('admissible_ids', m.admissible_ids == frozenset({'baseline', 'cand-001', 'cand-002'}),
           str(sorted(m.admissible_ids)))
        ck('rejected_ids', m.rejected_ids == frozenset({'cand-003'}))
        ck('all_entries baseline-first, rejection-free',
           [e.candidate_id for e in m.all_entries()] == ['baseline', 'cand-001', 'cand-002'])
        ck('domainShape (4, 6)', m.domain_shape == (4, 6), str(m.domain_shape))
        ck('entry() returns Entry', isinstance(m.entry('cand-001'), Entry))
        a1 = m.mask('cand-001')
        ck('npy mask loads verified', a1.shape == (4, 6) and a1.dtype == np.uint8 and a1[1, 2] == 0)
        a2 = m.mask('cand-002')
        ck('rle-json mask loads verified', a2.shape == (4, 6) and int(a2.sum()) == 22, str(int(a2.sum())))
        ck('baseline mask is all solid', int(m.mask('baseline').sum()) == 24)
        ck('checks carried through', len(m.baseline.factory_checks) == 3
           and m.baseline.factory_checks[1]['measured'] == 0.04)
        b1 = path.read_bytes(); dump_manifest(doc, path); b2 = path.read_bytes()
        ck('canonical dump is byte-stable', b1 == b2, '%d bytes' % len(b1))
        ck('npy write is byte-stable (repeat runs hash equal)',
           write_mask(a1, base / 'masks' / 'stable-a.npy').sha256
           == write_mask(a1, base / 'masks' / 'stable-b.npy').sha256)
        ck('round-trip to_json -> parse is stable', parse_manifest(m.to_json(), base).to_json() == m.to_json())

        print("=== the invariant: rejected candidates cannot enter Track ===")
        ok, d = _expect(RejectedCandidateError, 'FACTORY.CONNECTIVITY_BROKEN',
                        m.assert_admissible, 'cand-003')
        ck('assert_admissible raises RejectedCandidateError', ok, d)
        ok, d = _expect(RejectedCandidateError, 'cand-003', m.entry, 'cand-003')
        ck('entry() raises for a rejected id', ok, d)
        ok, d = _expect(RejectedCandidateError, 'cand-003', m.mask, 'cand-003')
        ck('mask() raises for a rejected id', ok, d)
        ok, d = _expect(RejectedCandidateError, 'carry no mask', load_mask, m.rejected[0], base)
        ck('load_mask(Rejected) raises', ok, d)
        ok, d = _expect(ManifestError, 'unknown candidate', m.assert_admissible, 'cand-999')
        ck('assert_admissible raises ManifestError for unknown id', ok, d)
        ck('RejectedCandidateError is a ManifestError', issubclass(RejectedCandidateError, ManifestError))
        ok, d = _expect(Exception, '', setattr, m, 'rejected_ids', frozenset())
        ck('guard cannot be disabled (frozen Manifest)', ok, d)
        ck('Rejected record has no mask field', not hasattr(m.rejected[0], 'mask'))
        ck('rejection() exposes the veto for Lab feedback',
           m.rejection('cand-003').reason_code == 'FACTORY.CONNECTIVITY_BROKEN')

        print("=== strictness ===")
        ok, d = _expect(ManifestError, 'bogusTopKey',
                        parse_manifest, mut(doc, lambda x: x.update({'bogusTopKey': 1})), base)
        ck('unknown top-level key rejected by name', ok, d)
        ok, d = _expect(ManifestError, 'mysteryField', parse_manifest,
                        mut(doc, lambda x: x['survivors'][0].update({'mysteryField': 1})), base)
        ck('unknown entry key rejected by name', ok, d)
        ok, d = _expect(ManifestError, 'whyThis', parse_manifest,
                        mut(doc, lambda x: x['rejected'][0].update({'whyThis': 1})), base)
        ck('unknown rejected key rejected by name', ok, d)
        ok, d = _expect(ManifestError, "must not carry a 'mask'", parse_manifest,
                        mut(doc, lambda x: x['rejected'][0].update(
                            {'mask': doc['baseline']['mask']})), base)
        ck('rejected entry carrying a mask refused', ok, d)
        ok, d = _expect(ManifestError, 'schemaVersion', parse_manifest,
                        mut(doc, lambda x: x.update({'schemaVersion': 'track.survivor-manifest/2'})), base)
        ck('wrong schemaVersion rejected', ok, d)
        ok, d = _expect(ManifestError, 'schemaVersion', parse_manifest,
                        mut(doc, lambda x: x.pop('schemaVersion')), base)
        ck('absent schemaVersion rejected', ok, d)
        ok, d = _expect(ManifestError, 'runId', parse_manifest,
                        mut(doc, lambda x: x.pop('runId')), base)
        ck('missing required top-level key rejected', ok, d)
        ok, d = _expect(ManifestError, 'baseline.verdict', parse_manifest,
                        mut(doc, lambda x: x['baseline'].update({'verdict': 'fail'})), base)
        ck('baseline verdict != pass rejected', ok, d)
        ok, d = _expect(ManifestError, 'survivors[1].verdict', parse_manifest,
                        mut(doc, lambda x: x['survivors'][1].update({'verdict': 'fail'})), base)
        ck('survivor verdict != pass rejected', ok, d)
        ok, d = _expect(ManifestError, 'rejected[0].verdict', parse_manifest,
                        mut(doc, lambda x: x['rejected'][0].update({'verdict': 'pass'})), base)
        ck('rejected verdict != fail rejected', ok, d)
        ok, d = _expect(ManifestError, "'cand-001'", parse_manifest,
                        mut(doc, lambda x: x['survivors'][1].update({'candidateId': 'cand-001'})), base)
        ck('duplicate candidateId rejected by name', ok, d)
        ok, d = _expect(ManifestError, "'baseline'", parse_manifest,
                        mut(doc, lambda x: x['rejected'][0].update({'candidateId': 'baseline'})), base)
        ck('id in both passed set and rejected named', ok, d)
        ok, d = _expect(ManifestError, 'domainShape', parse_manifest,
                        mut(doc, lambda x: x['survivors'][0]['mask'].update({'shape': [3, 6]})), base)
        ck('mask shape disagreeing with domainShape rejected', ok, d)
        ok, d = _expect(ManifestError, '64 lowercase hex', parse_manifest,
                        mut(doc, lambda x: x['survivors'][0]['mask'].update({'sha256': 'sha256:ABC'})), base)
        ck('malformed mask sha256 rejected', ok, d)
        ok, d = _expect(ManifestError, '64 lowercase hex', parse_manifest,
                        mut(doc, lambda x: x.update({'problemHash': 'deadbeef'})), base)
        ck('malformed problemHash rejected', ok, d)
        ok, d = _expect(ManifestError, 'relative', parse_manifest,
                        mut(doc, lambda x: x['survivors'][0]['mask'].update(
                            {'path': '/etc/passwd.npy'})), base)
        ck('absolute mask path rejected', ok, d)
        ok, d = _expect(ManifestError, 'relative', parse_manifest,
                        mut(doc, lambda x: x['survivors'][0]['mask'].update(
                            {'path': '../outside/x.npy'})), base)
        ck('parent-traversal mask path rejected', ok, d)
        ok, d = _expect(ManifestError, 'format', parse_manifest,
                        mut(doc, lambda x: x['survivors'][0]['mask'].update({'format': 'stl'})), base)
        ck('unknown mask format rejected', ok, d)
        ok, d = _expect(ManifestError, "'mm'", parse_manifest,
                        mut(doc, lambda x: x.update({'units': 'inch'})), base)
        ck('units != mm rejected', ok, d)
        ok, d = _expect(ManifestError, 'nely, nelx', parse_manifest,
                        mut(doc, lambda x: x.update({'domainShape': [4, 6, 2]})), base)
        ck('domainShape of wrong rank rejected', ok, d)
        ok, d = _expect(ManifestError, "expected 'pass'", parse_manifest,
                        mut(doc, lambda x: x['survivors'][0]['factoryChecks'][0].update(
                            {'result': 'fail'})), base)
        ck('survivor carrying a failed check rejected', ok, d)
        ok, d = _expect(ManifestError, 'finite number', parse_manifest,
                        mut(doc, lambda x: x['rejected'][0].update({'measured': True})), base)
        ck('boolean measured value rejected', ok, d)
        ok, d = _expect(ManifestError, 'at least 1 survivor', parse_manifest,
                        mut(doc, lambda x: x.update({'survivors': []})), base)
        ck('empty survivors rejected when require_survivors=True', ok, d)
        degenerate = parse_manifest(mut(doc, lambda x: x.update({'survivors': []})), base,
                                    require_survivors=False)
        ck('empty survivors accepted when require_survivors=False',
           degenerate.admissible_ids == frozenset({'baseline'}))
        ok, d = _expect(ManifestError, 'not valid JSON', load_manifest,
                        _write(base / 'broken.json', '{nope'))
        ck('non-JSON manifest file rejected', ok, d)

        print("=== mask integrity ===")
        bad_sha = mut(doc, lambda x: x['survivors'][0]['mask'].update(
            {'sha256': 'sha256:' + '0' * 64}))
        msha = parse_manifest(bad_sha, base)
        ok, d = _expect(MaskIntegrityError, 'sha256 mismatch', msha.mask, 'cand-001')
        ck('sha256 mismatch raises MaskIntegrityError', ok, d)
        ck('MaskIntegrityError is a ManifestError', issubclass(MaskIntegrityError, ManifestError))
        wrong = write_mask(np.ones((3, 6), np.uint8), base / 'masks' / 'wrong.npy', rel_to=base)
        onshape = mut(doc, lambda x: x['survivors'][0]['mask'].update(
            {'path': wrong.path, 'sha256': wrong.sha256}))
        ok, d = _expect(MaskIntegrityError, 'shape mismatch',
                        parse_manifest(onshape, base).mask, 'cand-001')
        ck('on-disk shape mismatch raises MaskIntegrityError', ok, d)
        gone = mut(doc, lambda x: x['survivors'][0]['mask'].update({'path': 'masks/absent.npy'}))
        ok, d = _expect(MaskIntegrityError, 'found none', parse_manifest(gone, base).mask, 'cand-001')
        ck('missing mask file raises MaskIntegrityError', ok, d)
        tern = np.ones((4, 6), np.uint8); tern[0, 0] = 2
        np.save(str(base / 'masks' / 'tern.npy'), tern, allow_pickle=False)
        tdoc = mut(doc, lambda x: x['survivors'][0]['mask'].update(
            {'path': 'masks/tern.npy', 'sha256': sha256_file(base / 'masks' / 'tern.npy')}))
        ok, d = _expect(MaskIntegrityError, 'only 0 and 1', parse_manifest(tdoc, base).mask, 'cand-001')
        ck('non-binary mask raises MaskIntegrityError', ok, d)
        ok, d = _expect(ManifestError, 'only 0 and 1', write_mask, tern, base / 'masks' / 'no.npy')
        ck('write_mask refuses a non-binary array', ok, d)

        print("=== rle-json ===")
        rng = np.random.default_rng(20260822)          # fixed seed: deterministic
        r = (rng.random((17, 23)) > 0.4).astype(np.uint8)
        ck('rle round-trip equals original', np.array_equal(decode_rle(encode_rle(r)), r))
        ck('rle round-trip preserves shape', decode_rle(encode_rle(r)).shape == (17, 23))
        for edge, label in ((np.zeros((4, 6), np.uint8), 'all-void'),
                            (np.ones((1, 1), np.uint8), '1x1')):
            ck('rle round-trip %s' % label, np.array_equal(decode_rle(encode_rle(edge)), edge))
        ck('rle encoding is deterministic', encode_rle(r) == encode_rle(r))
        ok, d = _expect(MaskIntegrityError, 'schemaVersion', decode_rle,
                        dict(encode_rle(r), schemaVersion='track.mask-rle/9'))
        ck('rle wrong schemaVersion rejected', ok, d)
        ok, d = _expect(MaskIntegrityError, 'summing to', decode_rle,
                        dict(encode_rle(r), runs=encode_rle(r)['runs'][:-1]))
        ck('rle run-count mismatch rejected', ok, d)
        ok, d = _expect(MaskIntegrityError, 'value 0 or 1', decode_rle,
                        dict(encode_rle(r), runs=[[7, 17 * 23]]))
        ck('rle non-binary run value rejected', ok, d)

    print()
    print('ALL CHECKS PASSED' if not fail else '%d FAILURES: %s' % (len(fail), ', '.join(fail)))
    return len(fail)


def _write(path, text):
    """selftest helper: write raw text and return the path (used for invalid files)."""
    p = Path(path)
    p.write_text(text, encoding="utf-8")
    return p


if __name__ == '__main__':
    sys.exit(selftest())
