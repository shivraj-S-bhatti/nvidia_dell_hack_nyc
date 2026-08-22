"""evaluate.py -- Track: solve every Factory survivor on one frozen fixture, rank
them against the baseline, and return one actionable result to Lab.

    python3 tools/track/evaluate.py                      # build fixture, run, report
    python3 tools/track/evaluate.py --repeat 3           # repeatability check
    python3 tools/track/evaluate.py --survivors <path>   # consume Factory's manifest

Hard rules this file enforces rather than assumes (issue #14 acceptance):

* A Factory-rejected candidate cannot be evaluated. `manifest.assert_admissible`
  is called before every solve, and the rejected ids are carried into the report
  so a veto stays visible instead of vanishing.
* The baseline and every survivor use the same fixture. Every result carries the
  fixture hash and `rank()` refuses to rank a set whose hashes disagree.
* Nothing is claimed that the test does not measure. The metric is in-plane
  compliance under a declared fixture -- a stiffness proxy for material layout.
  Not strength, not lap time, not flight loads, not certification.
"""
import argparse
import json
import os
import platform
import subprocess
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import candidates  # noqa: E402
import domain  # noqa: E402
import fea  # noqa: E402
import fixture as fixture_mod  # noqa: E402
import manifest as mf  # noqa: E402

RESULT_VERSION = "track.result/1"
FEEDBACK_VERSION = "track.feedback/1"
REPORT_VERSION = "track.report/1"

# Declared repeatability tolerance. The solve is a direct sparse factorisation,
# so identical input must give identical output; this bound exists to catch
# nondeterminism creeping in (threaded BLAS reordering, a stray rng), not to
# absorb expected noise.
REPEAT_TOLERANCE = 1e-9

METRIC = ("in-plane compliance under the frozen fixture "
          "(a stiffness proxy for material layout)")
BOUNDARY = ("Measured: 2D linear-elastic plane-stress compliance, peak nodal "
            "displacement, and material fraction on the frozen grid. Not "
            "measured and not claimed: strength, margin of safety, out-of-plane "
            "bending, buckling, fatigue, flight loads, aerodynamic range, crash "
            "performance, manufacturability, or certification.")


# --- environment ----------------------------------------------------------
def peak_rss_mb():
    import resource
    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS reports bytes, Linux reports kilobytes.
    return r / (1024.0 * 1024.0) if sys.platform == "darwin" else r / 1024.0


def git_sha():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"],
                                       stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return None


def host_record():
    """Recorded, never asserted. Issue #14 wants elapsed time measured on the
    GB10; stamping the real host is what makes a GB10 run self-evidently a GB10
    run and a laptop run self-evidently not one."""
    import scipy
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or None,
        "cpuCount": os.cpu_count(),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "compute": "cpu",
        "gpuPeakMemoryMb": None,
        "gpuNote": "solver is CPU sparse-direct; no GPU memory is allocated",
        "gitSha": git_sha(),
    }


# --- measurement ----------------------------------------------------------
# A compliance this far above baseline means the load is being carried by the
# void stiffness floor, not by material: a floating island, or an
# under-constrained fixture. fea.py's `finite` flag cannot see that (SuperLU
# factors a singular system without complaint), so Track detects it here rather
# than reporting a number that is wrong by nine orders of magnitude.
BLOWUP_RATIO = 1e6


def measure(mask, fx):
    """Solve every load case on one candidate. Returns a measures dict."""
    mask = np.ascontiguousarray(mask, dtype=np.float64)
    if mask.shape != fx.shape:
        raise ValueError("mask shape %s != fixture domain %s"
                         % (mask.shape, fx.shape))

    backed = fixture_mod.nodes_on_material(mask)
    loaded = np.unique(np.array(fx.load_cases[0]["dofs"], dtype=np.int64) // 2)
    held = np.unique(fx.fixed_dofs // 2)
    unbacked = int((~backed[loaded]).sum() + (~backed[held]).sum())

    per_case, energy, t_solve = {}, None, 0.0
    max_disp, max_disp_case, max_disp_xy = 0.0, None, None
    finite = True
    for case in fx.load_cases:
        t0 = time.perf_counter()
        res = fea.solve(
            mask, fx.hx, fx.hy, fx.params["thicknessMm"],
            fx.params["youngsModulusMPa"], fx.params["poissonRatio"],
            fx.fixed_dofs, list(zip(case["dofs"], case["magnitudes"])),
            penal=fx.params["penal"], void_ratio=fx.params["voidRatio"])
        t_solve += time.perf_counter() - t0
        finite = finite and bool(res.finite)
        per_case[case["name"]] = float(res.compliance)
        if float(res.max_displacement) > max_disp:
            max_disp = float(res.max_displacement)
            max_disp_case = case["name"]
            max_disp_xy = res.max_displacement_xy
        energy = res.element_energy if energy is None else energy + res.element_energy

    solid = int((mask > 0.5).sum())
    state = "ok"
    if not finite:
        state = "non_finite"
    elif unbacked:
        state = "fixture_unsupported"

    at_mm = None
    if max_disp_xy is not None:
        ix, iy = int(max_disp_xy[0]), int(max_disp_xy[1])
        at_mm = [round(float(fx.transform["x0"]) + ix * fx.hx, 3),
                 round(float(fx.transform["z0"]) + iy * fx.hy, 3)]

    return {
        "compliancePerCaseNmm": {k: round(v, 9) for k, v in per_case.items()},
        "complianceNmm": round(float(sum(per_case.values())), 9),
        "maxDisplacementMm": round(max_disp, 9),
        "maxDisplacementLoadCase": max_disp_case,
        "maxDisplacementAtXZMm": at_mm,
        "solidCells": solid,
        "materialFractionOfDomain": round(solid / float(mask.size), 9),
        "state": state,
        "unbackedFixtureNodes": unbacked,
        "solveSeconds": round(t_solve, 6),
        "_energy": energy,
    }


def flag_blowup(m, base):
    """Set after the baseline is known; see BLOWUP_RATIO."""
    if m["state"] == "ok" and base["complianceNmm"] > 0 and \
            m["complianceNmm"] / base["complianceNmm"] > BLOWUP_RATIO:
        m["state"] = "load_path_lost"
    return m


def derive_relative(m, base):
    """Everything Track displays is baseline-relative, so the absolute load
    magnitude and the grid resolution cancel out of the comparison."""
    cr = m["complianceNmm"] / base["complianceNmm"]
    mr = m["solidCells"] / float(base["solidCells"])
    return {
        "complianceRatioToBaseline": round(cr, 9),
        "materialRatioToBaseline": round(mr, 9),
        "maxDisplacementRatioToBaseline":
            round(m["maxDisplacementMm"] / base["maxDisplacementMm"], 9)
            if base["maxDisplacementMm"] else None,
        # stiffness per unit material, relative to baseline. >1 means the
        # material that was removed was worth more gone than kept.
        "specificStiffnessRatio": round((1.0 / cr) * (1.0 / mr), 9),
    }


# --- ranking --------------------------------------------------------------
def rank(results):
    """Deterministic ordering. Documented so a judge can reproduce it by hand.

    Primary   : specificStiffnessRatio, descending (stiffness per unit material).
    Tie-break : materialRatioToBaseline ascending (lighter wins),
                then complianceRatioToBaseline ascending (stiffer wins),
                then candidateId ascending (stable, arbitrary, and last).

    Candidates whose state is not "ok" are ranked last and keep their numbers;
    a bad result is never dropped from the table.
    """
    hashes = {r["fixtureHash"] for r in results}
    if len(hashes) != 1:
        raise ValueError(
            "refusing to rank results from %d different fixtures: %s -- the "
            "baseline and every survivor must face the same test"
            % (len(hashes), sorted(hashes)))
    survivors = [r for r in results if r["role"] == "survivor"]
    ordered = sorted(
        survivors,
        key=lambda r: (
            0 if r["measures"]["state"] == "ok" else 1,
            -r["relative"]["specificStiffnessRatio"],
            r["relative"]["materialRatioToBaseline"],
            r["relative"]["complianceRatioToBaseline"],
            r["candidateId"],
        ))
    for i, r in enumerate(ordered, 1):
        r["rank"] = i
    return ordered


def meets_target(rel):
    t = fixture_mod.TARGET
    return bool(rel["materialRatioToBaseline"] <= t["materialFractionRatioMax"]
                and rel["complianceRatioToBaseline"] <= t["complianceRatioMax"])


# --- feedback to Lab ------------------------------------------------------
def removal_diagnosis(base_mask, cand_mask, base_energy, fx):
    """First-order account of what a candidate deleted, measured on the baseline
    field: how much mass, and how much of the baseline's strain energy that mass
    was carrying. Cheap, computed for every survivor, and comparable across them.

    It is first-order on purpose and labelled as such: removing material
    redistributes load, so the baseline field predicts the *direction* of a
    change well and its magnitude only roughly. The overload regions below are
    the second-order half, and they come from the candidate's own solve.
    """
    base_solid = base_mask.astype(bool)
    removed = base_solid & ~cand_mask.astype(bool)
    total_e = float(base_energy[base_solid].sum())
    mass = float(removed.sum()) / float(base_solid.sum())
    energy = float(base_energy[removed].sum()) / total_e if total_e > 0 else 0.0
    return {
        "massFractionRemoved": round(mass, 6),
        "strainEnergyFractionRemoved": round(energy, 6),
        # >1: the deleted cells were carrying more than their share of the load.
        "payoffRatio": round(energy / mass, 4) if mass > 0 else None,
        "basis": "first-order, evaluated on the baseline strain-energy field",
    }


def _regions(sel, weight, total, fx, limit=3, min_cells=8):
    """Connected components of a boolean selection, in model millimetres."""
    from scipy import ndimage
    lbl, n = ndimage.label(sel)
    out = []
    for i in range(1, n + 1):
        cells = lbl == i
        c = int(cells.sum())
        if c < min_cells:                  # ignore rasteriser speckle
            continue
        ys, xs = np.nonzero(cells)
        out.append({
            # float() on every value: numpy scalars serialise but print as
            # "np.float64(-0.2)", which is noise in a demo transcript.
            "centreXZMm": [
                round(float(fx.transform["x0"]) + float(xs.mean() + 0.5) * fx.hx, 2),
                round(float(fx.transform["z0"]) + float(ys.mean() + 0.5) * fx.hy, 2)],
            "cells": c,
            "areaMm2": round(c * fx.hx * fx.hy, 2),
            "strainEnergyShare": round(float(weight[cells].sum()) / total, 6)
            if total > 0 else None,
        })
    out.sort(key=lambda r: (-(r["strainEnergyShare"] or 0), r["centreXZMm"]))
    return out[:limit]


def feedback_event(worst, best, base_mask, worst_mask, base_energy, worst_energy,
                   fx, run_id):
    """Turn one poor Track result into something Lab can act on.

    "It got worse" is not actionable. Three measured things are:
      1. how the mass it deleted compares, per unit mass, to the mass the best
         survivor deleted -- same fixture, so the comparison is fair;
      2. where the load went instead, from the candidate's own strain-energy
         field against the baseline's;
      3. where the same mass was available for almost no load.
    """
    base_solid = base_mask.astype(bool)
    worst_solid = worst_mask.astype(bool)
    removed = base_solid & ~worst_solid
    total_e = float(base_energy[base_solid].sum())

    d = worst["removalDiagnosis"]
    cmp_block, verdict_line = None, ""
    if best is not None and best["candidateId"] != worst["candidateId"]:
        bd = best["removalDiagnosis"]
        # Energy carried per unit mass deleted. This is the number that separates
        # a good cut from a bad one; the absolute payoff ratio does not.
        wd_dens = (d["payoffRatio"] or 0.0)
        bd_dens = (bd["payoffRatio"] or 0.0)
        cmp_block = {
            "candidateId": best["candidateId"],
            "massFractionRemoved": bd["massFractionRemoved"],
            "strainEnergyFractionRemoved": bd["strainEnergyFractionRemoved"],
            "complianceRatioToBaseline":
                best["relative"]["complianceRatioToBaseline"],
            "specificStiffnessRatio": best["relative"]["specificStiffnessRatio"],
            "loadBearingDensityMultiple":
                round(wd_dens / bd_dens, 2) if bd_dens > 0 else None,
        }
        verdict_line = (
            "`%s` removed %.1f%% of baseline mass for +%.1f%% compliance. This "
            "candidate removed %.1f%% for +%.1f%%. Per unit mass deleted, this "
            "candidate took out %s as much load-carrying material."
            % (best["candidateId"], 100 * bd["massFractionRemoved"],
               100 * (best["relative"]["complianceRatioToBaseline"] - 1),
               100 * d["massFractionRemoved"],
               100 * (worst["relative"]["complianceRatioToBaseline"] - 1),
               ("%.0fx" % cmp_block["loadBearingDensityMultiple"])
               if cmp_block["loadBearingDensityMultiple"] else "more"))

    # Second-order, measured on this candidate: cells still present whose strain
    # energy rose most. This is where the deleted material's load actually went.
    still = base_solid & worst_solid
    floor = float(np.quantile(base_energy[base_solid], 0.50)) or 1.0
    ratio = np.zeros_like(base_energy)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio[still] = worst_energy[still] / np.maximum(base_energy[still], floor * 1e-6)
    hot = still & (ratio >= 2.0)
    overload = _regions(hot, worst_energy,
                        float(worst_energy[worst_solid].sum()), fx, limit=3)

    # Where the same mass was available for almost no load.
    spare = base_solid & ~fx.protected
    if spare.any():
        cutoff = float(np.quantile(base_energy[spare], 0.10))
        cheap = spare & (base_energy <= cutoff)
    else:
        cheap = np.zeros_like(base_solid)
    cheap_mass = float(cheap.sum()) / float(base_solid.sum())
    cheap_energy = (float(base_energy[cheap].sum()) / total_e
                    if total_e > 0 else 0.0)

    return {
        "schemaVersion": FEEDBACK_VERSION,
        "runId": run_id,
        "from": "track",
        "to": "lab",
        "candidateId": worst["candidateId"],
        "parentId": worst["parentId"],
        "verdict": "underperformed-baseline",
        "fixtureId": worst["fixtureId"],
        "fixtureHash": worst["fixtureHash"],
        "metric": METRIC,
        "measured": {
            "complianceRatioToBaseline":
                worst["relative"]["complianceRatioToBaseline"],
            "materialRatioToBaseline":
                worst["relative"]["materialRatioToBaseline"],
            "specificStiffnessRatio": worst["relative"]["specificStiffnessRatio"],
        },
        "removalDiagnosis": d,
        "comparedToBestSurvivor": cmp_block,
        "removedRegions": _regions(removed, base_energy, total_e, fx),
        "overloadedRegions": {
            "definition": "cells retained by this candidate whose strain energy "
                          "is at least 2x their baseline value -- where the "
                          "deleted material's load went instead",
            "cells": int(hot.sum()),
            "regions": overload,
        },
        "cheaperMaterialAvailable": {
            "definition": "solid, unprotected baseline cells in the lowest "
                          "strain-energy-density decile",
            "massFractionOfBaseline": round(cheap_mass, 6),
            "strainEnergyShare": round(cheap_energy, 6),
            "regions": _regions(cheap, base_energy, total_e, fx),
        },
        "recommendation": (
            (verdict_line + " ") if verdict_line else "") + (
            "Keep material on the payload-pad-to-arm-mount paths and on the "
            "overloaded regions listed above. The same mass is available in the "
            "low-energy regions: %.1f%% of baseline mass carrying %.1f%% of "
            "baseline strain energy."
            % (100 * cheap_mass, 100 * cheap_energy)),
        "boundary": BOUNDARY,
    }


# --- run ------------------------------------------------------------------
def run(fx, man, run_id):
    """Solve baseline first, then every survivor, on the one fixture."""
    if tuple(man.domain_shape) != fx.shape:
        raise ValueError(
            "manifest domainShape %s does not match the fixture grid %s -- the "
            "candidates were compiled against a different domain"
            % (tuple(man.domain_shape), fx.shape))
    host = host_record()
    results, energies, masks = [], {}, {}
    baseline_id = man.baseline.candidate_id
    t_wall0 = time.perf_counter()

    for entry in man.all_entries():
        man.assert_admissible(entry.candidate_id)      # the gate, on every solve
        mask = mf.load_mask(entry, man.base_dir)       # verifies sha256 + shape
        if tuple(mask.shape) != fx.shape:
            raise ValueError(
                "candidate %s has domain %s but the fixture is %s -- the "
                "manifest and the fixture disagree"
                % (entry.candidate_id, mask.shape, fx.shape))
        m = measure(mask, fx)
        energies[entry.candidate_id] = m.pop("_energy")
        masks[entry.candidate_id] = mask
        results.append({
            "schemaVersion": RESULT_VERSION,
            "runId": run_id,
            "candidateId": entry.candidate_id,
            "parentId": entry.parent_id,
            "role": "baseline" if entry.candidate_id == baseline_id else "survivor",
            "fixtureId": fx.params["fixtureId"],
            "fixtureHash": fx.hash(),
            "problemHash": man.problem_hash,
            "maskSha256": entry.mask.sha256,
            "metric": METRIC,
            "measures": m,
            "relative": None,
            "notes": entry.notes,
        })

    base = next(r for r in results if r["role"] == "baseline")
    if base["measures"]["state"] != "ok":
        raise RuntimeError(
            "baseline solve state is %r -- fix the fixture, do not special-case "
            "the baseline" % base["measures"]["state"])
    base_mask, base_energy = masks[base["candidateId"]], energies[base["candidateId"]]
    for r in results:
        if r is not base:
            flag_blowup(r["measures"], base["measures"])
        r["relative"] = derive_relative(r["measures"], base["measures"])
        r["meetsTarget"] = meets_target(r["relative"]) if r["role"] == "survivor" else None
        r["removalDiagnosis"] = removal_diagnosis(
            base_mask, masks[r["candidateId"]], base_energy, fx)

    ordered = rank(results)
    wall = time.perf_counter() - t_wall0
    for r in results:
        r["timing"] = {"solveSeconds": r["measures"]["solveSeconds"]}
        r["host"] = host
    return results, ordered, base, energies, masks, wall, host


def markdown_table(results, ordered, base, fx):
    t = fixture_mod.TARGET
    lines = [
        "| rank | candidate | state | compliance (N·mm) | vs base | material | vs base | "
        "specific stiffness vs base | max disp (mm) | meets target |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]

    def row(r, rank_label):
        m, rel = r["measures"], r["relative"]
        return ("| %s | `%s` | %s | %.4g | %.3f× | %d cells | %.3f× | **%.3f×** | %.4g | %s |"
                % (rank_label, r["candidateId"], m["state"], m["complianceNmm"],
                   rel["complianceRatioToBaseline"], m["solidCells"],
                   rel["materialRatioToBaseline"], rel["specificStiffnessRatio"],
                   m["maxDisplacementMm"],
                   "—" if r["meetsTarget"] is None
                   else ("yes" if r["meetsTarget"] else "no")))

    lines.append(row(base, "base"))
    for r in ordered:
        lines.append(row(r, str(r["rank"])))
    lines.append("")
    lines.append("Displayed target: material ≤ %.2f× baseline **and** compliance "
                 "≤ %.2f× baseline." % (t["materialFractionRatioMax"],
                                        t["complianceRatioMax"]))
    return "\n".join(lines)


def repeatability(fx, man, run_id, n):
    """Re-run the whole evaluation n times and report the worst relative spread
    across every displayed measure."""
    runs = []
    for i in range(n):
        res, _, _, _, _, wall, _ = run(fx, man, "%s-rep%d" % (run_id, i + 1))
        runs.append(({r["candidateId"]: r for r in res}, wall))
    keys = sorted(runs[0][0])
    worst, worst_where = 0.0, "none (every measure agreed exactly)"
    for cid in keys:
        for field in ("complianceNmm", "maxDisplacementMm"):
            vals = [r[0][cid]["measures"][field] for r in runs]
            ref = abs(vals[0]) or 1.0
            spread = (max(vals) - min(vals)) / ref
            if spread > worst:
                worst, worst_where = spread, "%s.%s" % (cid, field)
        for field in ("complianceRatioToBaseline", "specificStiffnessRatio"):
            vals = [r[0][cid]["relative"][field] for r in runs]
            ref = abs(vals[0]) or 1.0
            spread = (max(vals) - min(vals)) / ref
            if spread > worst:
                worst, worst_where = spread, "%s.%s" % (cid, field)
    return {
        "runs": n,
        "declaredTolerance": REPEAT_TOLERANCE,
        "maxRelativeSpread": worst,
        "worstMeasure": worst_where,
        "withinTolerance": bool(worst <= REPEAT_TOLERANCE),
        "wallSecondsPerRun": [round(r[1], 4) for r in runs],
        "note": ("direct sparse factorisation, so exact agreement is the "
                 "expectation; the tolerance guards against nondeterminism, "
                 "not against numerical noise"),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--survivors", default=None,
                    help="path to a track.survivor-manifest/1 document. Omit to "
                         "generate Track's stand-in family (Factory not landed).")
    ap.add_argument("--artifacts", default=".artifacts/depgraph",
                    help="depgraph artifact directory (mesh + graph)")
    ap.add_argument("--step", default="S500-C1_ASM.step")
    ap.add_argument("--output-root", default=".artifacts/track")
    ap.add_argument("--run-id", default="track-run-1")
    ap.add_argument("--repeat", type=int, default=1,
                    help="re-run N times and report the observed spread")
    ap.add_argument("--nelx", type=int, default=None)
    ap.add_argument("--nely", type=int, default=None)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)

    out = os.path.abspath(a.output_root)
    os.makedirs(out, exist_ok=True)
    t0 = time.perf_counter()

    over = {}
    if a.nelx:
        over["nelx"] = a.nelx
    if a.nely:
        over["nely"] = a.nely
    fx = fixture_mod.build(a.artifacts, a.step, over or None)
    t_fixture = time.perf_counter() - t0

    if a.survivors:
        man = mf.load_manifest(a.survivors)
        src = a.survivors
    else:
        _, src = candidates.stand_in_manifest(fx, out, a.run_id)
        man = mf.load_manifest(src)

    if man.problem_hash != fx.hash():
        raise SystemExit(
            "manifest problemHash %s does not match this fixture %s.\nTrack "
            "will not score candidates that were compiled against a different "
            "domain." % (man.problem_hash, fx.hash()))

    results, ordered, base, energies, masks, wall, host = run(fx, man, a.run_id)

    rep = repeatability(fx, man, a.run_id, a.repeat) if a.repeat > 1 else None

    # Feedback goes to the worst-performing survivor that actually solved.
    ok = [r for r in ordered if r["measures"]["state"] == "ok"]
    fb = None
    if ok:
        worst, best = ok[-1], ok[0]
        fb = feedback_event(worst, best, masks[base["candidateId"]],
                            masks[worst["candidateId"]],
                            energies[base["candidateId"]],
                            energies[worst["candidateId"]], fx, a.run_id)

    report = {
        "schemaVersion": REPORT_VERSION,
        "runId": a.run_id,
        "generatedFrom": os.path.relpath(src, out) if os.path.isabs(src) else src,
        "metric": METRIC,
        "rankingRule": ("specificStiffnessRatio desc; ties by materialRatio asc, "
                        "then complianceRatio asc, then candidateId asc; "
                        "non-ok states last"),
        "target": dict(fixture_mod.TARGET),
        "fixture": fx.summary(),
        "manifest": {
            "producedBy": man.produced_by,
            "problemId": man.problem_id,
            "problemHash": man.problem_hash,
            "survivorCount": len(man.survivors),
            "rejectedCount": len(man.rejected),
        },
        "gate": {
            "rule": "Factory-rejected candidates cannot enter Track",
            "enforcedBy": "manifest.Manifest.assert_admissible, called before "
                          "every solve",
            "rejectedIds": sorted(man.rejected_ids),
            "evaluatedIds": [r["candidateId"] for r in results],
            "rejectedEvaluated": sorted(man.rejected_ids
                                        & {r["candidateId"] for r in results}),
            "rejected": [
                {"candidateId": r.candidate_id, "reasonCode": r.reason_code,
                 "measured": r.measured, "tolerance": r.tolerance,
                 "units": r.units, "implicated": list(r.implicated)}
                for r in man.rejected],
        },
        "baseline": base,
        "ranking": [
            {"rank": r["rank"], "candidateId": r["candidateId"],
             "specificStiffnessRatio": r["relative"]["specificStiffnessRatio"],
             "complianceRatioToBaseline": r["relative"]["complianceRatioToBaseline"],
             "materialRatioToBaseline": r["relative"]["materialRatioToBaseline"],
             "state": r["measures"]["state"], "meetsTarget": r["meetsTarget"]}
            for r in ordered],
        "results": results,
        "repeatability": rep,
        "feedbackToLab": fb,
        "timing": {
            "fixtureBuildSeconds": round(t_fixture, 4),
            "evaluationWallSeconds": round(wall, 4),
            "totalWallSeconds": round(time.perf_counter() - t0, 4),
            "peakRssMb": round(peak_rss_mb(), 2),
        },
        "host": host,
        "boundary": BOUNDARY,
    }
    if report["gate"]["rejectedEvaluated"]:
        raise SystemExit("GATE VIOLATION: rejected candidates were evaluated: %s"
                         % report["gate"]["rejectedEvaluated"])

    with open(os.path.join(out, "track-report.json"), "w") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)
        fh.write("\n")
    if fb:
        with open(os.path.join(out, "feedback-event.json"), "w") as fh:
            json.dump(fb, fh, indent=2, sort_keys=True)
            fh.write("\n")
    table = markdown_table(results, ordered, base, fx)
    with open(os.path.join(out, "comparison.md"), "w") as fh:
        fh.write(table + "\n")

    if not a.quiet:
        print("TRACK -- %s" % fx.params["fixtureId"])
        print("fixture %s   grid %dx%d   cell %.3f x %.3f mm   %s"
              % (fx.hash()[:19], fx.nely, fx.nelx, fx.hx, fx.hy,
                 fx.params["solver"]))
        print("metric: %s\n" % METRIC)
        print(table)
        print("\nGATE -- rejected by Factory, not evaluated: %s"
              % (", ".join(sorted(man.rejected_ids)) or "(none)"))
        for r in man.rejected:
            print("   %-24s %s  measured %s / %s %s"
                  % (r.candidate_id, r.reason_code, r.measured, r.tolerance,
                     r.units or ""))
        if rep:
            print("\nREPEATABILITY -- %d runs, max relative spread %.3g on %s "
                  "(declared tolerance %.0e) -> %s"
                  % (rep["runs"], rep["maxRelativeSpread"], rep["worstMeasure"],
                     rep["declaredTolerance"],
                     "PASS" if rep["withinTolerance"] else "FAIL"))
        if fb:
            print("\nFEEDBACK TO LAB -- %s" % fb["candidateId"])
            d = fb["removalDiagnosis"]
            print("   removed %.1f%% of baseline mass carrying %.1f%% of baseline "
                  "strain energy (payoff %.2f, first-order)"
                  % (100 * d["massFractionRemoved"],
                     100 * d["strainEnergyFractionRemoved"],
                     d["payoffRatio"] or 0.0))
            if fb["overloadedRegions"]["regions"]:
                print("   load went to %d cells now at >=2x baseline energy, "
                      "centred %s" % (fb["overloadedRegions"]["cells"],
                                      ", ".join(str(r["centreXZMm"]) for r in
                                                fb["overloadedRegions"]["regions"])))
            print("   %s" % fb["recommendation"])
        print("\nTIMING -- fixture %.2fs, evaluate %.2fs, total %.2fs, peak RSS %.0f MB"
              % (report["timing"]["fixtureBuildSeconds"],
                 report["timing"]["evaluationWallSeconds"],
                 report["timing"]["totalWallSeconds"],
                 report["timing"]["peakRssMb"]))
        print("HOST -- %s / %s / py%s  (recorded, not asserted)"
              % (host["machine"], host["platform"], host["python"]))
        print("\nwrote %s" % os.path.join(out, "track-report.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
