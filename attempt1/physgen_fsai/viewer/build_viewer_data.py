"""Build the JS viewer bundle from attempt1-physgen-fsai artifacts only."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any


class ViewerDataError(RuntimeError):
    """The isolated artifact tree did not satisfy the viewer contract."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"


def require_inside(root: Path, path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise ViewerDataError(f"path escaped the PhysGen-FSAI artifact root: {resolved}")
    return resolved


def load_json(root: Path, relative: str) -> dict[str, Any]:
    path = require_inside(root, root / relative)
    if not path.is_file():
        raise ViewerDataError(f"required viewer input is missing: {relative}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ViewerDataError(f"invalid JSON in {relative}: {error}") from error
    if not isinstance(value, dict):
        raise ViewerDataError(f"viewer input must be an object: {relative}")
    return value


def copy_asset(root: Path, output: Path, relative: str, name: str) -> dict[str, Any]:
    source = require_inside(root, root / relative)
    if not source.is_file():
        raise ViewerDataError(f"viewer asset is missing: {relative}")
    destination = require_inside(root, output / "assets" / name)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return {
        "url": f"/assets/{name}",
        "source": relative,
        "sha256": sha256_file(source),
        "sizeBytes": source.stat().st_size,
    }


def metric(label: str, value: float | int, unit: str = "", tone: str = "neutral") -> dict[str, Any]:
    return {"label": label, "value": value, "unit": unit, "tone": tone}


def evaluation_metrics(evaluation: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        metric("Compliance", evaluation["compliance_n_mm"], "N·mm"),
        metric("Max displacement", evaluation["max_displacement_mm"], "mm"),
        metric("Max von Mises", evaluation["max_von_mises_mpa"], "MPa"),
        metric("Material fraction", evaluation["material_fraction"], ""),
        metric("Residual", evaluation["residual"], ""),
    ]


def candidate_record(
    candidate: dict[str, Any],
    image: dict[str, Any],
    baseline: dict[str, Any],
) -> dict[str, Any]:
    evaluation = candidate["evaluation"]
    candidate_id = candidate["id"]
    status = "reference" if candidate_id == "baseline-full-plate" else ("survivor" if candidate["connectivity_pass"] else "rejected")
    material_delta = evaluation["material_fraction"] - baseline["material_fraction"]
    return {
        "id": candidate_id,
        "name": candidate["label"],
        "role": candidate["role"],
        "status": status,
        "eligible": bool(candidate["connectivity_pass"]),
        "image": image,
        "metrics": evaluation_metrics(evaluation),
        "rawMetrics": evaluation,
        "changes": [
            {
                "label": "Material fraction",
                "before": baseline["material_fraction"],
                "after": evaluation["material_fraction"],
                "delta": material_delta,
                "unit": "",
            },
            {
                "label": "Compliance",
                "before": baseline["compliance_n_mm"],
                "after": evaluation["compliance_n_mm"],
                "delta": evaluation["compliance_n_mm"] - baseline["compliance_n_mm"],
                "unit": "N·mm",
            },
            {
                "label": "Max displacement",
                "before": baseline["max_displacement_mm"],
                "after": evaluation["max_displacement_mm"],
                "delta": evaluation["max_displacement_mm"] - baseline["max_displacement_mm"],
                "unit": "mm",
            },
        ],
        "verdict": (
            "Reference geometry retained for the common structural test."
            if status == "reference"
            else (
                "Connected across the support and load regions; eligible for comparison."
                if status == "survivor"
                else "Rejected by four-neighbor support-to-load connectivity despite a finite void-stiffness solve."
            )
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    repository_root = Path(__file__).resolve().parents[3]
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=repository_root / ".artifacts" / "attempt1-physgen-fsai",
    )
    parser.add_argument("--output")
    arguments = parser.parse_args()
    artifact_root = arguments.artifact_root.resolve()
    if artifact_root.name != "attempt1-physgen-fsai" or not artifact_root.is_dir():
        raise ViewerDataError("viewer input must be the isolated attempt1-physgen-fsai artifact root")
    output = require_inside(
        artifact_root,
        Path(arguments.output).resolve() if arguments.output else artifact_root / "js-viewer" / "public",
    )
    output.mkdir(parents=True, exist_ok=True)

    target = load_json(artifact_root, "object/target-component.json")
    object_replay = load_json(artifact_root, "object/evidence/replay.json")
    bridge_replay = load_json(artifact_root, "design-problem/evidence/replay.json")
    pre_snap_replay = load_json(artifact_root, "design-problem.pre-snap/evidence/replay.json")
    problem = load_json(artifact_root, "design-problem/design-problem.json")
    masks = load_json(artifact_root, "design-problem/mask-manifest.json")
    center_run = load_json(artifact_root, "simulation-check/simulation.json")
    annulus_run = load_json(artifact_root, "simulation-annulus/simulation.json")
    final_run = load_json(artifact_root, "simulation-annulus-v2/simulation.json")
    progression = load_json(artifact_root, "progression-viewer/evidence.json")

    if target.get("definitionName") != "Example Plate" or progression.get("assembly", {}).get("solid_count") != 115:
        raise ViewerDataError("the viewer artifact is not the verified FS-AI racecar/Example Plate run")
    if final_run.get("physics", {}).get("layout_mapping", {}).get("transposed_before_and_after_solver") is not True:
        raise ViewerDataError("the final simulation does not contain the corrected pyEDGE layout mapping")

    overlay_relative = "design-problem/" + masks["overlay"]["relative_path"]
    assets = {
        "vehicleIso": copy_asset(artifact_root, output, "progression-viewer/images/vehicle-isometric.png", "vehicle-isometric.png"),
        "vehicleTop": copy_asset(artifact_root, output, "progression-viewer/images/vehicle-top.png", "vehicle-top.png"),
        "vehicleSide": copy_asset(artifact_root, output, "progression-viewer/images/vehicle-side.png", "vehicle-side.png"),
        "vehicleHighlight": copy_asset(artifact_root, output, "progression-viewer/images/vehicle-plate-highlight.png", "vehicle-plate-highlight.png"),
        "plateIso": copy_asset(artifact_root, output, "progression-viewer/images/example-plate-isometric.png", "example-plate-isometric.png"),
        "domainOverlay": copy_asset(artifact_root, output, overlay_relative, "domain-overlay.png"),
        "plateField": copy_asset(artifact_root, output, "simulation-annulus-v2/candidates/baseline-full-plate-viewer.png", "baseline-full-plate.png"),
        "bracedField": copy_asset(artifact_root, output, "simulation-annulus-v2/candidates/candidate-braced-viewer.png", "candidate-braced.png"),
        "disconnectedField": copy_asset(artifact_root, output, "simulation-annulus-v2/candidates/candidate-disconnected-viewer.png", "candidate-disconnected.png"),
        "simpField": copy_asset(artifact_root, output, "simulation-annulus-v2/baseline/simp-rectangle-viewer.png", "simp-counterfactual.png"),
    }

    final_candidates = {item["id"]: item for item in final_run["candidates"]}
    baseline_evaluation = final_candidates["baseline-full-plate"]["evaluation"]
    candidates = [
        candidate_record(final_candidates["baseline-full-plate"], assets["plateField"], baseline_evaluation),
        candidate_record(final_candidates["candidate-braced"], assets["bracedField"], baseline_evaluation),
        candidate_record(final_candidates["candidate-disconnected"], assets["disconnectedField"], baseline_evaluation),
    ]
    candidates.append(
        {
            "id": "simp-counterfactual",
            "name": "SIMP / OC counterfactual",
            "role": "deterministic optimization baseline",
            "status": "warning",
            "eligible": False,
            "image": assets["simpField"],
            "metrics": evaluation_metrics(final_run["baseline"]["evaluation"]),
            "rawMetrics": final_run["baseline"]["evaluation"],
            "changes": [],
            "verdict": f"Numerically deterministic, but {final_run['baseline']['posthoc_mask_changed_cells']:,} cells change when FS-AI masks are applied post hoc; not an eligible masked baseline yet.",
        }
    )

    object_inventory = object_replay.get("inventory", {}).get("packages", {})
    solver_version = problem["solver"]["version"]
    models = [
        {
            "id": "ocp-xcaf",
            "name": "OpenCascade / XCAF",
            "type": "deterministic CAD model",
            "version": object_inventory.get("cadquery-ocp", "7.9.3.1.1"),
            "learned": False,
            "responsibility": "Resolve the 115-solid assembly, preserve names/transforms, isolate Example Plate, and tessellate evidence views.",
        },
        {
            "id": "cad-domain-bridge",
            "name": "CAD → topology domain bridge",
            "type": "deterministic geometry projection",
            "version": "issue61-v1",
            "learned": False,
            "responsibility": "Map component-local millimetres to a bounded 144×144 solver grid and produce enforceable masks.",
        },
        {
            "id": "fallback-generator",
            "name": "Bounded topology fallback",
            "type": "deterministic candidate generator",
            "version": "analytic-brace-v1",
            "learned": False,
            "responsibility": "Produce connected and deliberately disconnected 35% material fields while the learned OpenTO path remains unrun.",
        },
        {
            "id": "pyedge",
            "name": "OptimizeAnyTopology pyEDGE",
            "type": "plane-stress finite-element model",
            "version": solver_version,
            "learned": False,
            "responsibility": "Apply the same 100 N annulus-distributed comparison fixture and report compliance, displacement, stress, and residual.",
        },
        {
            "id": "factory-connectivity",
            "name": "Factory connectivity veto",
            "type": "deterministic graph check",
            "version": "4-neighbor-v1",
            "learned": False,
            "responsibility": "Reject a field with no solid support-to-load path even when void stiffness makes the numerical solve finite.",
        },
    ]

    mask_counts = masks["validation"]["true_cells"]
    fixture = final_run["fixture_mapping"]
    stages = [
        {
            "id": "vehicle-context",
            "order": 1,
            "phase": "CAD",
            "label": "Resolve the racecar",
            "modelId": "ocp-xcaf",
            "status": "passed",
            "image": assets["vehicleIso"],
            "supportingImages": [assets["vehicleTop"], assets["vehicleSide"]],
            "justification": "Start from the recognizable full vehicle so every later alteration stays attached to its assembly context.",
            "alteration": {"scope": "read-only assembly intake", "before": "20 MB source STEP", "after": "45 product definitions / 115 valid solids", "summary": "No geometry changed."},
            "metrics": [metric("Solids", progression["assembly"]["solid_count"]), metric("Triangles", progression["assembly"]["triangle_count"]), metric("Length", progression["assembly"]["bounding_box_mm"]["size"][1], "mm")],
            "evidence": ["progression-viewer/evidence.json", "object/evidence/replay.json"],
        },
        {
            "id": "object-gate",
            "order": 2,
            "phase": "CAD",
            "label": "Select Example Plate",
            "modelId": "ocp-xcaf",
            "status": "passed",
            "image": assets["vehicleHighlight"],
            "supportingImages": [assets["plateIso"]],
            "justification": "Whole-car FEA is out of scope; the named sensor plate is planar, bounded, and has four verifiable interfaces.",
            "alteration": {"scope": "component isolation", "before": "115-solid vehicle assembly", "after": "1 valid 350×350×3 mm plate", "summary": "Extracted a hash-addressed baseline; source assembly remained immutable."},
            "metrics": [metric("Plate solids", target["geometry"]["solidCount"]), metric("Protected holes", len(target["protectedMountRegions"])), metric("Volume", target["geometry"]["volumeMm3"], "mm³")],
            "evidence": ["object/target-component.json", "object/evidence/replay.json"],
        },
        {
            "id": "domain-bridge",
            "order": 3,
            "phase": "Bridge",
            "label": "Project and constrain",
            "modelId": "cad-domain-bridge",
            "status": "repaired",
            "image": assets["domainOverlay"],
            "supportingImages": [],
            "justification": "The 2-D structural runtime needs an explicit coordinate map and masks that participate in repair/rejection rather than decorative metadata.",
            "alteration": {"scope": "CAD-to-grid representation", "before": "B-rep plate in component-local millimetres", "after": "144×144 boolean domain at 2.5 mm/cell", "summary": "Preserved holes, interfaces, supports, and loads; snapped kernel tolerance noise."},
            "metrics": [metric("Allowed cells", mask_counts["allowed_material"]), metric("Required solid", mask_counts["required_solid"]), metric("Required void", mask_counts["required_void"]), metric("Round-trip error", bridge_replay["domain"]["coordinate_report"]["maximum_round_trip_error_mm"], "mm")],
            "evidence": ["design-problem/design-problem.json", "design-problem/mask-manifest.json", "design-problem/evidence/replay.json"],
        },
        {
            "id": "candidate-family",
            "order": 4,
            "phase": "Generate",
            "label": "Explore a bounded family",
            "modelId": "fallback-generator",
            "status": "fallback",
            "image": assets["bracedField"],
            "supportingImages": [assets["plateField"], assets["disconnectedField"]],
            "justification": "Exercise the complete comparison and veto path now without mislabeling deterministic fields as learned PhysGen output.",
            "alteration": {"scope": "density topology", "before": "87.11% source-plate projection", "after": "35.00% braced and disconnected alternatives", "summary": "The learned OpenTO generator was not used in this artifact."},
            "metrics": [metric("Family size", 3), metric("Target material", problem["material_fraction_target"]), metric("Learned inference", 0, "runs")],
            "evidence": ["simulation-annulus-v2/simulation.json"],
        },
        {
            "id": "physics-evaluation",
            "order": 5,
            "phase": "Physics",
            "label": "Apply one common test",
            "modelId": "pyedge",
            "status": "passed-with-boundary",
            "image": assets["bracedField"],
            "supportingImages": [],
            "justification": "Every field must be measured by the same deterministic fixture before ranking; language-model opinion is not structural evidence.",
            "alteration": {"scope": "measurement only", "before": "Unscored density fields", "after": "Compliance, displacement, stress, residual", "summary": f"Distributed {fixture['total_force_n'][0]:g} N across {fixture['load_point_count']} load-ring cells and constrained {fixture['support_point_count']} support-ring cells."},
            "metrics": evaluation_metrics(final_candidates["candidate-braced"]["evaluation"]),
            "evidence": ["simulation-annulus-v2/simulation.json"],
        },
        {
            "id": "factory-veto",
            "order": 6,
            "phase": "Veto",
            "label": "Retain the real failure",
            "modelId": "factory-connectivity",
            "status": "rejected",
            "image": assets["disconnectedField"],
            "supportingImages": [],
            "justification": "Non-zero void stiffness can return finite FEA for disconnected material, so topology validity must be checked independently.",
            "alteration": {"scope": "verdict", "before": "Finite but disconnected field", "after": "Rejected and retained", "summary": "No silent repair and no deletion of the failed candidate."},
            "metrics": evaluation_metrics(final_candidates["candidate-disconnected"]["evaluation"]),
            "evidence": ["simulation-annulus-v2/simulation.json"],
        },
        {
            "id": "simp-counterfactual",
            "order": 7,
            "phase": "Physics",
            "label": "Audit the counterfactual",
            "modelId": "pyedge",
            "status": "open-issue",
            "image": assets["simpField"],
            "supportingImages": [],
            "justification": "A deterministic SIMP/OC run is the required counterfactual, but it is only comparable once the optimizer enforces the same FS-AI masks natively.",
            "alteration": {"scope": "optimizer audit", "before": "Unmasked rectangular SIMP density", "after": "Post-hoc mask diagnostic", "summary": f"{final_run['baseline']['posthoc_mask_changed_cells']:,} cells changed; baseline remains ineligible."},
            "metrics": evaluation_metrics(final_run["baseline"]["evaluation"]),
            "evidence": ["simulation-annulus-v2/simulation.json"],
        },
    ]

    center_eval = center_run["candidates"][0]["evaluation"]
    annulus_eval = annulus_run["candidates"][0]["evaluation"]
    corrected_eval = final_run["candidates"][0]["evaluation"]
    repairs = [
        {
            "id": "grid-snap",
            "status": "fixed",
            "modelId": "cad-domain-bridge",
            "title": "Kernel tolerance added a phantom column",
            "diagnosis": "OpenCascade reported -175.00000000000014 mm, so floor/ceil expanded a nominally exact bound.",
            "change": "Snap CAD bounds to 1e-9 mm before grid floor/ceil.",
            "before": f"{pre_snap_replay['domain']['grid_shape'][0]}×{pre_snap_replay['domain']['grid_shape'][1]}",
            "after": f"{bridge_replay['domain']['grid_shape'][0]}×{bridge_replay['domain']['grid_shape'][1]}",
        },
        {
            "id": "annulus-fixture",
            "status": "fixed-by-proxy",
            "modelId": "pyedge",
            "title": "Region centers landed inside protected holes",
            "diagnosis": "The reference adapter collapsed annular mount regions to four void-center points.",
            "change": "Distribute the same 100 N over 408 load-ring cells and constrain 408 support-ring cells.",
            "before": {"displacementMm": center_eval["max_displacement_mm"], "stressMpa": center_eval["max_von_mises_mpa"]},
            "after": {"displacementMm": annulus_eval["max_displacement_mm"], "stressMpa": annulus_eval["max_von_mises_mpa"]},
        },
        {
            "id": "axis-layout",
            "status": "fixed",
            "modelId": "pyedge",
            "title": "Square grid hid an X/Y transpose",
            "diagnosis": "Image masks use (row-y, column-x); pyEDGE design variables use (x, y). A 144×144 shape check could not detect the swap.",
            "change": "Transpose density fields before the solver and transpose results back for CAD/view orientation.",
            "before": {"displacementMm": annulus_eval["max_displacement_mm"], "stressMpa": annulus_eval["max_von_mises_mpa"]},
            "after": {"displacementMm": corrected_eval["max_displacement_mm"], "stressMpa": corrected_eval["max_von_mises_mpa"]},
        },
        {
            "id": "mask-aware-simp",
            "status": "open",
            "modelId": "pyedge",
            "title": "SIMP optimizer does not enforce FS-AI masks",
            "diagnosis": "The reference rectangular baseline is deterministic but violates the component domain and protected cells.",
            "change": "Pending: enforce allowed/required masks during every OC update, not after optimization.",
            "before": {"posthocChangedCells": final_run["baseline"]["posthoc_mask_changed_cells"]},
            "after": None,
        },
    ]

    warnings = list(final_run["warnings"])
    warnings.insert(0, "No learned OpenTO/PhysGen inference was used in this artifact; the displayed family is the deterministic fallback.")
    bundle = {
        "schemaVersion": "nightshift.fsai-js-viewer/v1",
        "run": {
            "id": final_run["problem"]["id"],
            "title": "FS-AI Example Plate progression",
            "subtitle": "Racecar context → bounded part → deterministic candidates → common physics → retained failure",
            "issue": 61,
            "status": "evidence-ready-with-open-mask-work",
            "offline": True,
            "learnedInferenceUsed": False,
            "wallSeconds": final_run["measurements"]["total_wall_seconds"],
            "peakRssBytes": final_run["measurements"]["peak_rss_bytes"],
            "sourceAssemblySha256": progression["assembly"]["sha256"],
            "fixture": fixture,
        },
        "assets": assets,
        "models": models,
        "stages": stages,
        "candidates": candidates,
        "repairs": repairs,
        "warnings": warnings,
        "provenance": {
            "artifactRoot": ".artifacts/attempt1-physgen-fsai",
            "inputs": [
                "object/target-component.json",
                "object/evidence/replay.json",
                "design-problem.pre-snap/evidence/replay.json",
                "design-problem/evidence/replay.json",
                "design-problem/design-problem.json",
                "design-problem/mask-manifest.json",
                "simulation-check/simulation.json",
                "simulation-annulus/simulation.json",
                "simulation-annulus-v2/simulation.json",
                "progression-viewer/evidence.json",
            ],
            "generator": "attempt1/physgen_fsai/viewer/build_viewer_data.py",
        },
    }
    data_dir = require_inside(artifact_root, output / "data")
    data_dir.mkdir(parents=True, exist_ok=True)
    data_path = require_inside(artifact_root, data_dir / "viewer-data.json")
    data_path.write_text(canonical_json(bundle), encoding="utf-8")
    manifest = {
        "schemaVersion": "nightshift.fsai-js-viewer-manifest/v1",
        "artifactBoundary": ".artifacts/attempt1-physgen-fsai",
        "data": {"path": "data/viewer-data.json", "sha256": sha256_file(data_path)},
        "assets": {
            path.name: {"sha256": sha256_file(path), "sizeBytes": path.stat().st_size}
            for path in sorted((output / "assets").glob("*"))
            if path.is_file()
        },
    }
    manifest_path = require_inside(artifact_root, output / "manifest.json")
    manifest_path.write_text(canonical_json(manifest), encoding="utf-8")
    print(canonical_json({"status": "passed", "data": str(data_path), "stages": len(stages), "models": len(models), "candidates": len(candidates), "repairs": len(repairs)}), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
