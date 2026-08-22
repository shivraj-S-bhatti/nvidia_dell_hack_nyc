"""validate.py -- give every Lab candidate a Factory verdict.

    python3 tools/factory/validate.py                      # full family, human-readable
    python3 tools/factory/validate.py --repeat 3           # prove the verdicts repeat
    python3 tools/factory/validate.py --candidate cand-d-standardize-m25 --verbose
    python3 tools/factory/validate.py --json

Reads the object contract (#11 when it publishes one, the Factory fixture until then)
and a candidate family (#12 when it publishes one, the Factory fixture until then),
and writes verdicts, a survivor manifest, feedback events, and run timing under
--out. Every number printed here is measured; nothing on this path calls a model.
"""
import os, sys, json, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from candidate import ObjectContract, Candidate                          # noqa: E402
from geometry import Assembly                                            # noqa: E402
import verdict as V                                                      # noqa: E402

FIX = os.path.join(HERE, 'fixtures')
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))

# Issue #11 (OBJECT) owns the authoritative contract. Prefer it the moment it lands;
# fall back to the Factory fixture and record which one was used in every verdict.
CONTRACT_CANDIDATES = [os.path.join(ROOT, '.artifacts', 'object', 'object-contract.json'),
                       os.path.join(FIX, 'object-contract.json')]
FAMILY_CANDIDATES = [os.path.join(ROOT, '.artifacts', 'lab', 'candidates.json'),
                     os.path.join(FIX, 'candidates.json')]

STATUS_MARK = {'pass': 'PASS', 'fail': 'FAIL', 'unchecked': '----'}


def _wrap(text, width, indent=' ' * 13):
    import textwrap
    return ('\n' + indent).join(textwrap.wrap(text, width)) or text


def resolve_out(out_root, one_candidate):
    """Keep a single-candidate debug run out of the real Track input manifest.

    survivors.json is the mechanism that stops a rejected candidate reaching Track.
    A `--candidate X` run only knows about X, so writing its manifest to the family
    path would quietly shrink Track's input to one row -- and a partial manifest that
    looks complete is worse than no manifest. Single-candidate runs get their own
    directory.
    """
    return out_root if not one_candidate else os.path.join(out_root, '_single', one_candidate)


def _first_existing(paths):
    for p in paths:
        if os.path.exists(p):
            return p
    return paths[-1]


def render(verdicts, run, survivors, feedback, verbose=False):
    print(f"\nFACTORY   {run['checkSetVersion']}   corpus {run['corpusRevision']}   "
          f"object {run['objectId']}")
    print(f"contract  {os.path.relpath(run['contractSource'], ROOT)}")
    print(f"\n{'candidate':30s} {'verdict':8s} {'reason code':16s} why")
    print(f"{'-'*30} {'-'*8} {'-'*16} {'-'*58}")
    for v in verdicts:
        why = v['reason'].replace('\n', ' ')
        print(f"{(v['candidateId'] or '?')[:30]:30s} {v['verdict'].upper():8s} "
              f"{v['reasonCode']:16s} {why[:58]}")

    if verbose:
        for v in verdicts:
            print(f"\n--- {v['candidateId']}   {v['label']}")
            if v['rationale']:
                print(f"    lab rationale: {v['rationale']}")
            for c in v['checks']:
                print(f"    [{STATUS_MARK[c['status']]}] {c['check']:16s} {c['reasonCode']:14s} "
                      f"{c['reason'][:74]}")
                # A caveat that only survives in the JSON is a silent pass in practice.
                # Anything the check could not verify is printed next to its own result.
                note = (c['measured'] or {}).get('unchecked')
                if note:
                    print(f"           NOT CHECKED: {_wrap(note, 84, ' ' * 24)}")
                if c['status'] == 'fail' and c['measured'].get('detail'):
                    for d in c['measured']['detail'][:4]:
                        print(f"           {json.dumps(d, sort_keys=True)[:110]}")
            if v['affectedOccurrences']:
                print(f"    implicated: {len(v['affectedOccurrences'])} occurrences, "
                      f"{len(v['affectedDefinitions'])} definitions")
                for o in v['affectedOccurrences'][:6]:
                    print(f"        {o}")
                if len(v['affectedOccurrences']) > 6:
                    print(f"        ... {len(v['affectedOccurrences']) - 6} more")

    print(f"\nSURVIVORS -- {len(survivors['survivors'])} eligible for Track, "
          f"{len(survivors['rejected'])} rejected")
    for s in survivors['survivors']:
        print(f"  PASS  {s['candidateId']:28s} {s['label']}")
    for r in survivors['rejected']:
        print(f"  FAIL  {r['candidateId']:28s} {r['reasonCode']} ({r['check']})")

    for fe in feedback:
        print(f"\nFEEDBACK -> lab   {fe['candidateId']}   {fe['reasonCode']}")
        print(f"  check      {fe['check']}")
        print(f"  implicated {len(fe['implicatedOccurrences'])} occurrences: "
              f"{', '.join(fe['implicatedDefinitions'])}")
        if fe['constraint']:
            print(f"  constraint {fe['constraint']['kind']}")
            # Per-definition constraints are joined with '; ' and split back apart for
            # display. A contract statement is free prose that may contain one, so it
            # is printed whole.
            lines = ([fe['constraint']['statement']]
                     if fe['constraint']['kind'] == 'contract'
                     else fe['constraint']['statement'].split('; '))
            for line in lines:
                print(f"             {_wrap(line, 90)}")

    print(f"\n{run['candidates']} candidates, {run['passed']} passed, {run['failed']} failed "
          f"in {run['elapsedMs']:.0f} ms   peak RSS {run['peakRssMb']} MB")
    print("verdict path contains no language model: every reason code above is "
          "arithmetic on measured geometry.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--step', default=os.path.join(ROOT, 'S500-C1_ASM.step'))
    ap.add_argument('--art', default=os.path.join(ROOT, '.artifacts', 'depgraph'))
    ap.add_argument('--contract', default=None)
    ap.add_argument('--candidates', default=None)
    ap.add_argument('--out', default=os.path.join(ROOT, '.artifacts', 'factory'))
    ap.add_argument('--candidate', default=None, help='evaluate one candidate by id')
    ap.add_argument('--repeat', type=int, default=1,
                    help='run the family N times and compare verdict digests')
    ap.add_argument('--verbose', action='store_true')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()

    contract_path = a.contract or _first_existing(CONTRACT_CANDIDATES)
    family_path = a.candidates or _first_existing(FAMILY_CANDIDATES)
    contract = ObjectContract.load(contract_path)
    _, cands = Candidate.load_family(family_path)
    if a.candidate:
        cands = [c for c in cands if c.id == a.candidate]
        if not cands:
            print(f"no candidate '{a.candidate}' in {family_path}", file=sys.stderr)
            return 2

    out_root = resolve_out(a.out, a.candidate)
    asm = Assembly(a.step, a.art)

    digests = []
    for i in range(max(1, a.repeat)):
        verdicts, feedback, survivors, run = V.run_family(asm, contract, cands, out_root)
        digests.append(V.digest(verdicts))

    if a.json:
        print(json.dumps({'run': run, 'verdicts': verdicts, 'survivors': survivors,
                          'feedback': feedback, 'verdictDigests': digests},
                         indent=2, sort_keys=True))
        return 0

    render(verdicts, run, survivors, feedback, a.verbose)
    if a.repeat > 1:
        same = len(set(digests)) == 1
        print(f"\nREPEATABILITY -- {a.repeat} runs, "
              f"{'all verdict digests identical' if same else 'DIGESTS DIFFER'}: "
              f"{digests[0]}")
        if not same:
            for i, d in enumerate(digests):
                print(f"  run {i+1}: {d}")
            return 1
    print(f"\nevidence: {os.path.relpath(out_root, ROOT)}/  "
          f"(verdicts/, feedback/, survivors.json, check-set.json, run.json)")
    return 0


if __name__ == '__main__':
    sys.exit(main())
