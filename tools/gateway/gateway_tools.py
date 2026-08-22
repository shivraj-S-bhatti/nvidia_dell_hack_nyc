"""gateway_tools.py -- the entire tool surface for issue #10's OpenClaw wiring.

Each function below shells out to one already-verified CLI (or reads one
already-written artifact) and returns its output verbatim as a dict. None of
them measure geometry, run a solver, or decide a verdict -- tools/depgraph,
tools/factory, and tools/track already did that, deterministically, with no
language model on the path. A model that calls these functions may translate
natural language into the call, and may explain the returned evidence in
prose; it must never originate a number that is not present in the returned
dict. That boundary is enforced by these functions doing nothing but subprocess
+ JSON parse (or, for Track, a plain file read of an already-computed report).

    python3 tools/gateway/gateway_tools.py work_order BOTTOM-PLATE-S500 --thicker 1.0
    python3 tools/gateway/gateway_tools.py factory_verdict --candidate cand-d-standardize-m25
    python3 tools/gateway/gateway_tools.py track_result --candidate cand-a-edge-scallops
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class GatewayToolError(RuntimeError):
    """A wrapped CLI exited non-zero, or its output could not be parsed as JSON."""


def _run_json(cmd, timeout=120):
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise GatewayToolError(
            f"`{' '.join(cmd)}` exited {proc.returncode}: {proc.stderr.strip()[:2000]}"
        )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise GatewayToolError(f"`{' '.join(cmd)}` did not print valid JSON: {e}") from e


def work_order(part, thicker=None, hops=3):
    """Blast radius / ripple for one part -- tools/depgraph/work_order.py --json.

    Returns corpusRevision, the anchor part, every impacted definition with its
    hop distance and reason, and (if `thicker` is given) the fastener length
    actions a thickness change forces. See tools/depgraph/README.md.
    """
    cmd = [sys.executable, os.path.join(ROOT, 'tools', 'depgraph', 'work_order.py'), part]
    if thicker is not None:
        cmd += ['--thicker', str(thicker)]
    cmd += ['--hops', str(hops), '--json']
    return _run_json(cmd)


def factory_verdict(candidate_id=None):
    """One candidate's Factory verdict, or the whole family -- tools/factory/validate.py --json.

    validate.py recomputes deterministically from measured geometry every call
    (tools/factory/README.md: 3/3 repeated runs produce an identical verdict
    digest) -- this function does not cache or alter that result, only parses it.
    """
    cmd = [sys.executable, os.path.join(ROOT, 'tools', 'factory', 'validate.py'), '--json']
    if candidate_id:
        cmd += ['--candidate', candidate_id]
    return _run_json(cmd)


def track_result(candidate_id=None):
    """Track's last stored ranking -- reads .artifacts/track/track-report.json.

    This does not re-run the FEA solve; it reads the report tools/track/render.py
    itself describes as "the last report" (tools/track/README.md /
    `bash scripts/track-run.sh`). Run that script first if the file is missing or
    stale for the candidate you need.
    """
    path = os.path.join(ROOT, '.artifacts', 'track', 'track-report.json')
    if not os.path.exists(path):
        raise GatewayToolError(
            f"{path} does not exist -- run `bash scripts/track-run.sh` first"
        )
    with open(path) as fh:
        report = json.load(fh)

    if candidate_id is None:
        return report

    result = next((r for r in report.get('results', [])
                   if r.get('candidateId') == candidate_id), None)
    if result is None:
        raise GatewayToolError(f"no candidate '{candidate_id}' in {path}")
    rank = next((r for r in report.get('ranking', [])
                 if r.get('candidateId') == candidate_id), None)
    return {
        'runId': report.get('runId'),
        'metric': report.get('metric'),
        'target': report.get('target'),
        'result': result,
        'ranking': rank,
    }


TOOLS = {'work_order': work_order, 'factory_verdict': factory_verdict, 'track_result': track_result}


def _cli():
    if len(sys.argv) < 2 or sys.argv[1] not in TOOLS:
        print(f"usage: {sys.argv[0]} {{{'|'.join(TOOLS)}}} ...", file=sys.stderr)
        return 2
    name = sys.argv[1]
    rest = sys.argv[2:]
    kwargs = {}
    positional = []
    i = 0
    while i < len(rest):
        tok = rest[i]
        if tok.startswith('--'):
            kwargs[tok[2:]] = rest[i + 1]
            i += 2
        else:
            positional.append(tok)
            i += 1
    try:
        if name == 'work_order':
            result = work_order(positional[0], thicker=kwargs.get('thicker'),
                                 hops=int(kwargs.get('hops', 3)))
        elif name == 'factory_verdict':
            result = factory_verdict(candidate_id=kwargs.get('candidate'))
        else:
            result = track_result(candidate_id=kwargs.get('candidate'))
    except (GatewayToolError, IndexError) as e:
        print(json.dumps({'error': str(e)}), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(_cli())
