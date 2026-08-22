"""Execute the bounded FS-AI Example Plate loop and emit fresh STEP candidates."""

from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import sys
import time
import traceback
from typing import Any

import cadquery as cq
import numpy as np
from scipy import ndimage

from attempt1.physgen.lab.artifacts import write_density, write_json
from attempt1.physgen.lab.physics import evaluate_and_baseline
from attempt1.physgen_fsai.simulate import (
    annulus_fixture,
    apply_masks,
    candidate_family,
    connected_support_to_load,
    load_masks,
    load_problem,
    render_density,
)


EVENTS = (
    ("object", "OB", "Object"),
    ("lab", "LB", "Lab"),
    ("cad", "CC", "CAD Compile"),
    ("factory", "FX", "Factory"),
    ("revision", "RV", "Revision"),
    ("track", "TR", "Track"),
    ("review", "HU", "Human Review"),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def write_evidence_manifest(output_root: Path) -> None:
    """Hash immutable design evidence, excluding mutable control/runtime state."""
    paths: list[Path] = []
    for relative in ("request.json",):
        path = output_root / relative
        if path.is_file():
            paths.append(path)
    for relative in ("input", "candidates", "cad"):
        directory = output_root / relative
        if directory.is_dir():
            paths.extend(path for path in directory.rglob("*") if path.is_file())
    entries = [
        {
            "path": path.relative_to(output_root).as_posix(),
            "sizeBytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in sorted(paths)
    ]
    write_json(
        output_root / "manifest.json",
        {
            "schemaVersion": "ImmutableEvidenceManifest/1",
            "algorithm": "sha256",
            "artifacts": entries,
            "mutableControlFilesExcluded": [
                "status.json",
                "run.json",
                "selection.json",
                "logs/",
                "numba-cache/",
            ],
        },
    )


class Progress:
    def __init__(self, path: Path, run_id: str, request: dict[str, Any]) -> None:
        self.path = path
        self.value: dict[str, Any] = {
            "schemaVersion": "LiveRunStatus/1",
            "runId": run_id,
            "status": "running",
            "request": request,
            "events": [
                {"stage": stage, "agent": agent, "name": name, "status": "waiting", "message": "Waiting for upstream evidence."}
                for stage, agent, name in EVENTS
            ],
            "resultPath": None,
            "error": None,
        }
        self.write()

    def write(self) -> None:
        temporary = self.path.with_suffix(f".{os.getpid()}.tmp")
        temporary.write_text(json.dumps(self.value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        os.replace(temporary, self.path)

    def update(self, stage: str, status: str, message: str, evidence: list[str] | None = None) -> None:
        record = next(item for item in self.value["events"] if item["stage"] == stage)
        record.update({"status": status, "message": message})
        if status == "running" and "startedAt" not in record:
            record["startedAt"] = utc_now()
        if status in {"completed", "failed", "blocked"}:
            record["completedAt"] = utc_now()
        if evidence is not None:
            record["evidence"] = evidence
        self.write()

    def fail(self, stage: str, error: Exception) -> None:
        self.update(stage, "failed", f"{type(error).__name__}: {error}")
        self.value.update({"status": "failed", "error": f"{type(error).__name__}: {error}"})
        self.write()


def _simplify_loop(points: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if len(points) < 4:
        return points
    result: list[tuple[int, int]] = []
    for index, point in enumerate(points):
        previous = points[index - 1]
        following = points[(index + 1) % len(points)]
        if (point[0] - previous[0], point[1] - previous[1]) == (following[0] - point[0], following[1] - point[1]):
            continue
        result.append(point)
    return result


def _signed_area(points: list[tuple[int, int]]) -> float:
    return 0.5 * sum(
        points[index][0] * points[(index + 1) % len(points)][1]
        - points[(index + 1) % len(points)][0] * points[index][1]
        for index in range(len(points))
    )


def _inside(point: tuple[int, int], polygon: list[tuple[int, int]]) -> bool:
    x, y = point
    inside = False
    previous = polygon[-1]
    for current in polygon:
        x1, y1 = previous
        x2, y2 = current
        if (y1 > y) != (y2 > y):
            crossing = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < crossing:
                inside = not inside
        previous = current
    return inside


def _component_loops(mask: np.ndarray) -> list[list[tuple[int, int]]]:
    edges: dict[tuple[int, int], list[tuple[int, int]]] = {}

    def add(start: tuple[int, int], end: tuple[int, int]) -> None:
        edges.setdefault(start, []).append(end)

    rows, columns = mask.shape
    for row, column in np.argwhere(mask):
        row = int(row)
        column = int(column)
        if row == 0 or not mask[row - 1, column]:
            add((column, row), (column + 1, row))
        if column == columns - 1 or not mask[row, column + 1]:
            add((column + 1, row), (column + 1, row + 1))
        if row == rows - 1 or not mask[row + 1, column]:
            add((column + 1, row + 1), (column, row + 1))
        if column == 0 or not mask[row, column - 1]:
            add((column, row + 1), (column, row))
    loops: list[list[tuple[int, int]]] = []
    while edges:
        start = min(edges)
        current = start
        loop = [start]
        while True:
            choices = edges.get(current)
            if not choices:
                raise ValueError("raster boundary did not close")
            following = choices.pop(0)
            if not choices:
                edges.pop(current)
            current = following
            if current == start:
                break
            loop.append(current)
            if len(loop) > mask.size * 4:
                raise ValueError("raster boundary exceeded safe trace length")
        loops.append(_simplify_loop(loop))
    return loops


def density_to_step(
    density: np.ndarray,
    *,
    threshold: float,
    cell_size_mm: float,
    thickness_mm: float,
    translation_mm: tuple[float, float],
    destination: Path,
) -> dict[str, Any]:
    occupied = np.asarray(density) > threshold
    labels, count = ndimage.label(occupied, structure=np.asarray([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=np.uint8))
    solids: list[cq.Shape] = []
    loop_count = 0
    for component in range(1, count + 1):
        loops = _component_loops(labels == component)
        loop_count += len(loops)
        outers = [loop for loop in loops if _signed_area(loop) > 0]
        holes = [loop for loop in loops if _signed_area(loop) < 0]
        if len(outers) != 1:
            raise ValueError(f"connected raster component produced {len(outers)} outer boundaries")
        outer = outers[0]
        owned_holes = [hole for hole in holes if _inside(hole[0], outer)]

        def wire(points: list[tuple[int, int]]) -> cq.Wire:
            vectors = [
                cq.Vector(
                    point[0] * cell_size_mm + translation_mm[0],
                    point[1] * cell_size_mm + translation_mm[1],
                    0.0,
                )
                for point in points
            ]
            return cq.Wire.makePolygon(vectors, close=True)

        solids.append(cq.Solid.extrudeLinear(wire(outer), [wire(hole) for hole in owned_holes], cq.Vector(0, 0, thickness_mm)))
    if not solids:
        raise ValueError("candidate density contains no solid cells")
    shape = solids[0] if len(solids) == 1 else cq.Compound.makeCompound(solids)
    destination.parent.mkdir(parents=True, exist_ok=True)
    cq.exporters.export(shape, str(destination), exportType="STEP")
    imported = cq.importers.importStep(str(destination)).val()
    imported_solids = imported.Solids()
    return {
        "path": destination.as_posix(),
        "sha256": sha256_file(destination),
        "sizeBytes": destination.stat().st_size,
        "valid": bool(imported.isValid()),
        "solidCount": len(imported_solids),
        "volumeMm3": float(sum(solid.Volume() for solid in imported_solids)),
        "boundaryLoopCount": loop_count,
    }


def extra_candidate(problem: Any, masks: dict[str, np.ndarray]) -> dict[str, Any]:
    rows, columns = problem.grid_shape
    yy, xx = np.indices((rows, columns), dtype=np.float64)
    support_points = np.argwhere(masks["support"])
    load_points = np.argwhere(masks["load"])
    left = float(np.median(support_points[:, 1]))
    right = float(np.median(load_points[:, 1]))
    mount_rows = sorted((float(np.quantile(support_points[:, 0], 0.25)), float(np.quantile(support_points[:, 0], 0.75))))
    low, high = mount_rows
    score = np.maximum.reduce((
        np.exp(-np.abs(yy - low) / 5.0),
        np.exp(-np.abs(yy - high) / 5.0),
        0.8 * np.exp(-np.abs(xx - left) / 5.0),
        0.8 * np.exp(-np.abs(xx - right) / 5.0),
    ))
    from attempt1.physgen_fsai.simulate import constrained_selection

    return {
        "id": "candidate-perimeter-frame",
        "label": "Perimeter frame",
        "role": "bounded candidate",
        "density": constrained_selection(score, masks, problem.material_fraction),
    }


def repaired_candidate(disconnected: dict[str, Any], braced: dict[str, Any], masks: dict[str, np.ndarray]) -> dict[str, Any]:
    density = np.asarray(disconnected["density"], dtype=np.float32).copy()
    columns = density.shape[1]
    bridge = np.zeros_like(density, dtype=bool)
    bridge[:, max(0, columns // 2 - 5) : min(columns, columns // 2 + 6)] = True
    density[bridge & (np.asarray(braced["density"]) > 0.5)] = 1.0
    return {
        "id": "candidate-disconnected-r1",
        "label": "Repaired central bridge",
        "role": "feedback revision",
        "parentId": disconnected["id"],
        "feedback": "Factory connectivity veto: restore material across the severed central load path.",
        "density": apply_masks(density, masks),
    }


def run(args: argparse.Namespace, progress: Progress, request: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    progress.update("object", "running", "Validating the downloaded FS-AI target and protected interfaces.")
    problem, transform = load_problem(args.problem)
    masks, mask_manifest = load_masks(args.masks, problem.grid_shape)
    target = json.loads(args.target.read_text(encoding="utf-8"))
    if target.get("componentId") != request["target"]["componentId"]:
        raise ValueError("request target does not match the verified FS-AI component")
    progress.update(
        "object",
        "completed",
        f"Mapped {target['definitionName']} with {len(problem.protected_interface_ids)} protected mount interfaces.",
        [args.target.as_posix(), args.problem.as_posix(), args.masks.as_posix()],
    )

    progress.update("lab", "running", "Generating a bounded three-proposal density family from the requested material fraction.")
    generated = candidate_family(problem, masks)
    baseline = generated[0]
    braced = generated[1]
    disconnected = generated[-1]
    perimeter = extra_candidate(problem, masks)
    proposals = [braced, perimeter, disconnected]
    candidate_root = args.output_root / "candidates"
    for candidate in [baseline, *proposals]:
        artifact = write_density(candidate_root / f"{candidate['id']}.npy", candidate["density"])
        preview = candidate_root / f"{candidate['id']}-viewer.png"
        render_density(preview, candidate["density"], masks)
        candidate["densityArtifact"] = artifact
        candidate["previewPath"] = preview.relative_to(args.output_root).as_posix()
    progress.update("lab", "completed", f"Generated {len(proposals)} proposals at {problem.material_fraction:.1%} requested material.", ["candidates/"])

    progress.update("cad", "running", "Compiling raster boundaries into inspectable STEP solids.")
    # ``load_problem`` normalizes the solver payload into domain coordinates,
    # while its second return value preserves the original CAD transform.  STEP
    # exports must be translated back into that original component frame.
    transform_values = transform["original"]["matrix_row_major"]
    translation = (float(transform_values[3]), float(transform_values[7]))
    compiled: dict[str, dict[str, Any]] = {}
    for candidate in [baseline, *proposals]:
        step_path = args.output_root / "cad" / f"{candidate['id']}.step"
        compiled[candidate["id"]] = density_to_step(
            candidate["density"],
            threshold=problem.density_threshold,
            cell_size_mm=float(mask_manifest["cell_size_mm"]),
            thickness_mm=problem.thickness_mm,
            translation_mm=translation,
            destination=step_path,
        )
    progress.update("cad", "completed", f"Compiled baseline plus {len(proposals)} fresh STEP candidates.", ["cad/"])

    progress.update("factory", "running", "Applying geometry validity, single-solid, mount-preservation, and load-path gates.")
    verdicts: dict[str, dict[str, Any]] = {}
    for candidate in [baseline, *proposals]:
        connectivity = connected_support_to_load(candidate["density"], masks)
        mounts = bool(np.all(np.asarray(candidate["density"])[masks["required_solid"]] > problem.density_threshold))
        geometry = compiled[candidate["id"]]
        failures = []
        if not geometry["valid"]:
            failures.append("invalid-step")
        if geometry["solidCount"] != 1:
            failures.append("not-one-solid")
        if not mounts:
            failures.append("protected-interface-lost")
        if not connectivity:
            failures.append("load-path-disconnected")
        verdicts[candidate["id"]] = {
            "candidateId": candidate["id"],
            "verdict": "pass" if not failures else "fail",
            "failureCodes": failures,
            "checks": {
                "stepValid": geometry["valid"],
                "solidCount": geometry["solidCount"],
                "protectedMounts": mounts,
                "supportToLoadConnected": connectivity,
            },
        }
    failed = [candidate for candidate in proposals if verdicts[candidate["id"]]["verdict"] == "fail"]
    passed = [candidate for candidate in proposals if verdicts[candidate["id"]]["verdict"] == "pass"]
    progress.update("factory", "completed", f"Factory retained {len(passed)} proposals and vetoed {len(failed)}.", ["run.json#factory"])

    progress.update("revision", "running", "Repairing the measured connectivity veto before Track.")
    revision = repaired_candidate(disconnected, braced, masks)
    artifact = write_density(candidate_root / f"{revision['id']}.npy", revision["density"])
    preview = candidate_root / f"{revision['id']}-viewer.png"
    render_density(preview, revision["density"], masks)
    revision["densityArtifact"] = artifact
    revision["previewPath"] = preview.relative_to(args.output_root).as_posix()
    compiled[revision["id"]] = density_to_step(
        revision["density"],
        threshold=problem.density_threshold,
        cell_size_mm=float(mask_manifest["cell_size_mm"]),
        thickness_mm=problem.thickness_mm,
        translation_mm=translation,
        destination=args.output_root / "cad" / f"{revision['id']}.step",
    )
    revision_connectivity = connected_support_to_load(revision["density"], masks)
    revision_geometry = compiled[revision["id"]]
    revision_failures = [] if revision_connectivity and revision_geometry["valid"] and revision_geometry["solidCount"] == 1 else ["revision-failed-factory"]
    verdicts[revision["id"]] = {
        "candidateId": revision["id"],
        "verdict": "pass" if not revision_failures else "fail",
        "failureCodes": revision_failures,
        "checks": {
            "stepValid": revision_geometry["valid"],
            "solidCount": revision_geometry["solidCount"],
            "protectedMounts": bool(np.all(np.asarray(revision["density"])[masks["required_solid"]] > problem.density_threshold)),
            "supportToLoadConnected": revision_connectivity,
        },
    }
    if revision_failures:
        raise ValueError("bounded revision did not pass Factory")
    passed.append(revision)
    progress.update("revision", "completed", f"{revision['id']} restored the central load path and passed Factory.", [revision["previewPath"], compiled[revision["id"]]["path"]])

    progress.update("track", "running", f"Evaluating {len(passed)} Factory survivors on the common offline pyEDGE fixture.")
    simulation_problem, fixture = annulus_fixture(problem, masks, float(mask_manifest["cell_size_mm"]))
    rows, columns = problem.grid_shape
    simulation_problem = replace(simulation_problem, grid_shape=(columns, rows))
    track_candidates = [baseline, *passed]
    evaluations, oat_baseline, oat_baseline_evaluation, physics = evaluate_and_baseline(
        simulation_problem,
        [np.ascontiguousarray(candidate["density"].T) for candidate in track_candidates],
        oat_root=args.oat_root,
        baseline_iterations=args.baseline_iterations,
    )
    evaluation_by_id = {candidate["id"]: asdict(evaluation) for candidate, evaluation in zip(track_candidates, evaluations, strict=True)}
    baseline_metrics = evaluation_by_id[baseline["id"]]
    ranked = []
    for candidate in passed:
        metrics = evaluation_by_id[candidate["id"]]
        compliance_ratio = metrics["compliance_n_mm"] / baseline_metrics["compliance_n_mm"]
        material_ratio = metrics["material_fraction"] / baseline_metrics["material_fraction"]
        score = 1.0 / (compliance_ratio * material_ratio)
        ranked.append({
            "candidateId": candidate["id"],
            "label": candidate["label"],
            "parentId": candidate.get("parentId", "baseline-full-plate"),
            "score": score,
            "metrics": metrics,
            "relative": {"complianceRatio": compliance_ratio, "materialRatio": material_ratio, "specificStiffnessRatio": score},
        })
    ranked.sort(key=lambda item: (-item["score"], item["metrics"]["material_fraction"], item["candidateId"]))
    for rank, item in enumerate(ranked, start=1):
        item["rank"] = rank
    progress.update("track", "completed", f"Ranked {len(ranked)} survivors; {ranked[0]['label']} is the measured recommendation.", ["run.json#track"])

    all_candidates = [baseline, *proposals, revision]
    run_id = request["runId"]
    url_root = f"/.artifacts/design-run/runs/{run_id}"
    result = {
        "schemaVersion": "LiveDesignRun/1",
        "runId": run_id,
        "status": "awaiting_human_review",
        "createdAt": utc_now(),
        "offline": True,
        "object": {
            "assembly": problem.raw["assembly"]["name"],
            "component": target["definitionName"],
            "componentId": target["componentId"],
            "sourceSha256": target["sourceArtifactSha256"],
            "protectedInterfaceCount": len(problem.protected_interface_ids),
        },
        "problem": {
            "id": problem.design_problem_id,
            "objective": request["request"]["objective"],
            "constraint": request["request"]["constraint"],
            "materialFractionTarget": problem.material_fraction,
            "fixture": fixture,
        },
        "candidates": [
            {
                "id": candidate["id"],
                "label": candidate["label"],
                "role": candidate["role"],
                "parentId": candidate.get("parentId"),
                "previewUrl": f"{url_root}/{candidate['previewPath']}",
                "stepUrl": f"{url_root}/cad/{candidate['id']}.step",
                "densitySha256": candidate["densityArtifact"]["content_sha256"],
                "compile": compiled[candidate["id"]],
                "factory": verdicts[candidate["id"]],
                "track": next((item for item in ranked if item["candidateId"] == candidate["id"]), None),
            }
            for candidate in all_candidates
        ],
        "factory": {
            "verdicts": list(verdicts.values()),
            "rejectedCandidateIds": [candidate["id"] for candidate in failed],
            "survivorCandidateIds": [candidate["id"] for candidate in passed],
        },
        "revision": {
            "id": revision["id"],
            "parentId": revision["parentId"],
            "feedback": revision["feedback"],
        },
        "track": {
            "baseline": {"candidateId": baseline["id"], "metrics": baseline_metrics},
            "ranking": ranked,
            "recommendation": ranked[0]["candidateId"],
            "physics": physics,
            "oatBaseline": {"metrics": asdict(oat_baseline_evaluation), "densityMean": float(oat_baseline.mean(dtype=np.float64))},
        },
        "measurements": {
            "totalWallSeconds": time.perf_counter() - started,
            "peakRssBytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        },
        "inventory": {
            "python": platform.python_version(),
            "machine": platform.machine(),
            "cadKernel": "OpenCascade via CadQuery",
            "solver": "OptimizeAnyTopology pyEDGE CPU",
            "learnedInferenceUsed": False,
        },
        "limitations": [
            "2-D in-plane plane-stress comparison fixture; not a vehicle certification result.",
            "Generated STEP boundaries follow the 2.5 mm CAD-derived occupancy grid.",
        ],
        "selectionEligibleCandidateIds": [item["candidateId"] for item in ranked],
    }
    write_json(args.output_root / "run.json", result)
    write_evidence_manifest(args.output_root)
    progress.update("review", "running", "Fresh candidates are ready; waiting for a persisted human selection.", ["run.json"])
    progress.value.update({"status": "awaiting_review", "resultPath": "run.json"})
    progress.write()
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--problem", type=Path, required=True)
    parser.add_argument("--masks", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--oat-root", type=Path, required=True)
    parser.add_argument("--baseline-iterations", type=int, default=4)
    parser.add_argument("--offline", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.offline:
        raise SystemExit("--offline is mandatory")
    args.output_root.mkdir(parents=True, exist_ok=True)
    request = json.loads(args.request.read_text(encoding="utf-8"))
    progress = Progress(args.output_root / "status.json", request["runId"], request["request"])
    current_stage = "object"
    try:
        run(args, progress, request)
    except Exception as error:
        for event in progress.value["events"]:
            if event["status"] == "running":
                current_stage = event["stage"]
                break
        progress.fail(current_stage, error)
        (args.output_root / "logs").mkdir(parents=True, exist_ok=True)
        (args.output_root / "logs" / "traceback.log").write_text(traceback.format_exc(), encoding="utf-8")
        print(json.dumps({"status": "failed", "stage": current_stage, "error": str(error)}))
        return 1
    print(json.dumps({"status": "awaiting_review", "runId": request["runId"], "result": "run.json"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
