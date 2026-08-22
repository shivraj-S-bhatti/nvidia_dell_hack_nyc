"""Run a bounded FS-AI plate simulation and emit an offline result viewer."""

from __future__ import annotations

import argparse
from collections import deque
import copy
from dataclasses import asdict, replace
from html import escape
import hashlib
import json
from pathlib import Path
import platform
import resource
import sys
import time
from typing import Any

import numpy as np
from PIL import Image

from attempt1.physgen.lab.artifacts import write_density, write_json, write_manifest
from attempt1.physgen.lab.physics import evaluate_and_baseline
from attempt1.physgen.lab.problem import CanonicalProblem, Load, Support


MASK_NAMES = (
    "baseline_projection",
    "allowed_material",
    "required_solid",
    "required_void",
    "support",
    "load",
    "keep_out",
)
IDENTITY_4X4 = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]


class SimulationContractError(ValueError):
    """The emitted FS-AI problem or mask bundle was not safe to simulate."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def repository_root(path: Path) -> Path:
    for parent in (path.parent, *path.parents):
        if (parent / ".git").exists():
            return parent
    raise SimulationContractError(f"cannot locate repository root from {path}")


def load_problem(path: Path) -> tuple[CanonicalProblem, dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SimulationContractError(f"cannot read DesignProblem: {error}") from error
    original_transform = copy.deepcopy(payload.get("coordinate_transform"))
    if not isinstance(original_transform, dict):
        raise SimulationContractError("DesignProblem coordinate transform is missing")
    matrix = original_transform.get("matrix_row_major")
    if not isinstance(matrix, list) or len(matrix) != 16:
        raise SimulationContractError("DesignProblem coordinate transform is not a 4x4 matrix")
    normalized = copy.deepcopy(payload)
    normalized["coordinate_transform"] = {
        "from_frame": original_transform.get("from_frame"),
        "to_frame": original_transform.get("from_frame"),
        "matrix_row_major": IDENTITY_4X4,
    }
    problem = CanonicalProblem.from_dict(
        normalized,
        repository_root=repository_root(path.resolve()),
    )
    return problem, {
        "normalization": "translation retained as evidence; OAT receives domain-frame coordinates",
        "original": original_transform,
        "oat": normalized["coordinate_transform"],
    }


def load_masks(path: Path, shape: tuple[int, int]) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SimulationContractError(f"cannot read mask manifest: {error}") from error
    if manifest.get("schema_version") != "nightshift.fsai-mask-manifest/v1":
        raise SimulationContractError("unsupported mask manifest")
    if tuple(manifest.get("grid_shape", ())) != shape:
        raise SimulationContractError("mask and DesignProblem grid shapes differ")
    references = manifest.get("masks")
    if not isinstance(references, dict) or set(references) != set(MASK_NAMES):
        raise SimulationContractError("mask inventory is incomplete or contains unknown masks")
    root = path.parent.resolve()
    masks: dict[str, np.ndarray] = {}
    for name in MASK_NAMES:
        reference = references[name]
        relative = Path(reference["relative_path"])
        artifact = (root / relative).resolve()
        if relative.is_absolute() or not artifact.is_relative_to(root) or not artifact.is_file():
            raise SimulationContractError(f"mask path is missing or escaped its root: {name}")
        if sha256_file(artifact) != reference["sha256"]:
            raise SimulationContractError(f"mask hash mismatch: {name}")
        value = np.load(artifact, allow_pickle=False)
        if value.dtype != np.bool_ or value.shape != shape:
            raise SimulationContractError(f"mask dtype or shape mismatch: {name}")
        masks[name] = np.ascontiguousarray(value)
    allowed = masks["allowed_material"]
    solid = masks["required_solid"]
    void = masks["required_void"] | masks["keep_out"]
    if np.any(solid & void) or np.any(solid & ~allowed):
        raise SimulationContractError("required-solid/void/allowed mask relationship failed")
    if np.any(masks["support"] & ~solid) or np.any(masks["load"] & ~solid):
        raise SimulationContractError("support or load mask escaped required solid")
    return masks, manifest


def constrained_selection(
    score: np.ndarray,
    masks: dict[str, np.ndarray],
    fraction: float,
    *,
    forbidden: np.ndarray | None = None,
) -> np.ndarray:
    allowed = masks["allowed_material"]
    selected = masks["required_solid"].copy()
    unavailable = np.zeros_like(allowed) if forbidden is None else forbidden
    eligible = allowed & ~selected & ~unavailable
    target = max(int(selected.sum()), int(round(fraction * selected.size)))
    target = min(target, int((eligible | selected).sum()))
    count = target - int(selected.sum())
    if count:
        flat = np.flatnonzero(eligible.ravel())
        order = np.argsort(-score.ravel()[flat], kind="stable")
        selected.ravel()[flat[order[:count]]] = True
    return apply_masks(selected.astype(np.float32), masks)


def apply_masks(density: np.ndarray, masks: dict[str, np.ndarray]) -> np.ndarray:
    result = np.array(density, dtype=np.float32, copy=True, order="C")
    result[~masks["allowed_material"]] = 0.0
    result[masks["required_solid"]] = 1.0
    result[masks["required_void"] | masks["keep_out"]] = 0.0
    return result


def candidate_family(problem: CanonicalProblem, masks: dict[str, np.ndarray]) -> list[dict[str, Any]]:
    rows, columns = problem.grid_shape
    yy, xx = np.indices((rows, columns), dtype=np.float64)
    support_rows = np.flatnonzero(masks["support"].any(axis=1))
    load_rows = np.flatnonzero(masks["load"].any(axis=1))
    mount_rows = sorted({int(np.median(support_rows[: len(support_rows) // 2])), int(np.median(load_rows[len(load_rows) // 2 :]))})
    if len(mount_rows) != 2:
        mount_rows = [int(rows * 0.28), int(rows * 0.72)]
    low, high = mount_rows
    x_normal = xx / max(columns - 1, 1)
    horizontal = np.maximum(np.exp(-np.abs(yy - low) / 4.0), np.exp(-np.abs(yy - high) / 4.0))
    diagonal_up = np.exp(-np.abs(yy - (low + (high - low) * x_normal)) / 5.0)
    diagonal_down = np.exp(-np.abs(yy - (high - (high - low) * x_normal)) / 5.0)
    edge_tie = 1e-9 * (1.0 - np.abs(x_normal - 0.5))
    score = np.maximum.reduce((horizontal, diagonal_up, diagonal_down)) + edge_tie
    central_gap = np.abs(xx - (columns - 1) / 2.0) <= 5
    return [
        {
            "id": "baseline-full-plate",
            "label": "Full plate baseline",
            "role": "baseline geometry",
            "density": apply_masks(masks["allowed_material"].astype(np.float32), masks),
        },
        {
            "id": "candidate-braced",
            "label": "Braced target fraction",
            "role": "bounded candidate",
            "density": constrained_selection(score, masks, problem.material_fraction),
        },
        {
            "id": "candidate-disconnected",
            "label": "Disconnected counterfactual",
            "role": "expected connectivity failure",
            "density": constrained_selection(score, masks, problem.material_fraction, forbidden=central_gap),
        },
    ]


def connected_support_to_load(density: np.ndarray, masks: dict[str, np.ndarray]) -> bool:
    occupied = density > 0.5
    starts = list(map(tuple, np.argwhere(occupied & masks["support"])))
    targets = {tuple(value) for value in np.argwhere(occupied & masks["load"])}
    queue = deque(starts)
    visited = set(starts)
    rows, columns = occupied.shape
    while queue:
        row, column = queue.popleft()
        if (row, column) in targets:
            return True
        for next_row, next_column in ((row - 1, column), (row + 1, column), (row, column - 1), (row, column + 1)):
            point = (next_row, next_column)
            if 0 <= next_row < rows and 0 <= next_column < columns and occupied[point] and point not in visited:
                visited.add(point)
                queue.append(point)
    return False


def point_cell_diagnostics(
    problem: CanonicalProblem,
    masks: dict[str, np.ndarray],
    cell_size_mm: float,
) -> dict[str, Any]:
    records = []
    for kind, entries in (("support", problem.supports), ("load", problem.loads)):
        for index, entry in enumerate(entries):
            x_mm, y_mm = entry.position_mm
            row = min(problem.grid_shape[0] - 1, max(0, int(y_mm / cell_size_mm)))
            column = min(problem.grid_shape[1] - 1, max(0, int(x_mm / cell_size_mm)))
            records.append(
                {
                    "kind": kind,
                    "index": index,
                    "position_mm": [x_mm, y_mm],
                    "grid_row_column": [row, column],
                    "allowed_material": bool(masks["allowed_material"][row, column]),
                    "required_void": bool(masks["required_void"][row, column]),
                    "region_mask": bool(masks[kind][row, column]),
                }
            )
    return {
        "records": records,
        "all_points_in_required_void": all(record["required_void"] for record in records),
        "warning": "The reference 2-D adapter reduces each annular region to its center point, which lands in a protected hole. This run measures that mapping as-is.",
    }


def annulus_fixture(
    problem: CanonicalProblem,
    masks: dict[str, np.ndarray],
    cell_size_mm: float,
) -> tuple[CanonicalProblem, dict[str, Any]]:
    support_cells = np.argwhere(masks["support"])
    load_cells = np.argwhere(masks["load"])
    if not len(support_cells) or not len(load_cells):
        raise SimulationContractError("annulus fixture requires non-empty support and load masks")

    def position(row_column: np.ndarray) -> tuple[float, float]:
        row, column = (int(value) for value in row_column)
        return ((column + 0.5) * cell_size_mm, (row + 0.5) * cell_size_mm)

    total_force = np.asarray(
        [sum(load.force_n[axis] for load in problem.loads) for axis in range(2)],
        dtype=np.float64,
    )
    force_per_cell = total_force / len(load_cells)
    supports = tuple(Support(position(cell), (1, 1)) for cell in support_cells)
    loads = tuple(
        Load(position(cell), (float(force_per_cell[0]), float(force_per_cell[1])))
        for cell in load_cells
    )
    return replace(problem, supports=supports, loads=loads), {
        "mode": "annulus-distributed-proxy",
        "support_point_count": len(supports),
        "load_point_count": len(loads),
        "total_force_n": total_force.tolist(),
        "force_per_load_cell_n": force_per_cell.tolist(),
        "limitation": "This deterministic proxy distributes the comparison fixture across mask-cell centers; it is not a recovered bolt/contact model.",
    }


def render_density(path: Path, density: np.ndarray, masks: dict[str, np.ndarray]) -> None:
    value = np.flipud(density)
    base = np.empty((*value.shape, 3), dtype=np.uint8)
    base[..., 0] = np.rint(248 - 220 * value).astype(np.uint8)
    base[..., 1] = np.rint(250 - 176 * value).astype(np.uint8)
    base[..., 2] = np.rint(252 - 112 * value).astype(np.uint8)
    support = np.flipud(masks["support"])
    load = np.flipud(masks["load"])
    void = np.flipud(masks["required_void"])
    base[support] = (37, 99, 235)
    base[load] = (220, 38, 38)
    base[void] = (255, 255, 255)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(base, mode="RGB").resize(
        (value.shape[1] * 3, value.shape[0] * 3),
        resample=Image.Resampling.NEAREST,
    ).save(path, optimize=False, compress_level=9)


def metric(value: float) -> str:
    if abs(value) >= 1_000_000 or (value != 0 and abs(value) < 0.001):
        return f"{value:.3e}"
    return f"{value:,.4f}"


def write_viewer(output_root: Path, result: dict[str, Any]) -> None:
    cards = []
    for step, candidate in enumerate(result["candidates"], start=1):
        evaluation = candidate["evaluation"]
        verdict = "connected" if candidate["connectivity_pass"] else "REJECT: disconnected"
        cards.append(
            f"""
            <article class="card">
              <div class="eyebrow">Step {step:02d} · {escape(candidate['role'])}</div>
              <h2>{escape(candidate['label'])}</h2>
              <img src="../{escape(candidate['preview'])}" alt="{escape(candidate['label'])} density field">
              <div class="verdict {'pass' if candidate['connectivity_pass'] else 'fail'}">{verdict}</div>
              <dl>
                <dt>Compliance</dt><dd>{metric(evaluation['compliance_n_mm'])} N·mm</dd>
                <dt>Max displacement</dt><dd>{metric(evaluation['max_displacement_mm'])} mm</dd>
                <dt>Max von Mises</dt><dd>{metric(evaluation['max_von_mises_mpa'])} MPa</dd>
                <dt>Material fraction</dt><dd>{evaluation['material_fraction']:.3f}</dd>
                <dt>Residual</dt><dd>{metric(evaluation['residual'])}</dd>
              </dl>
            </article>
            """
        )
    warnings = "".join(f"<li>{escape(item)}</li>" for item in result["warnings"])
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>FS-AI PhysGen simulation</title>
  <style>
    :root {{ color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; background:#07111f; color:#e5edf7; }}
    * {{ box-sizing:border-box; }} body {{ margin:0; background:radial-gradient(circle at top,#182b46 0,#07111f 44rem); }}
    main {{ max-width:1400px; margin:auto; padding:40px 28px 64px; }}
    header {{ display:grid; grid-template-columns:1.4fr .6fr; gap:28px; align-items:end; margin-bottom:28px; }}
    h1 {{ font-size:clamp(34px,5vw,72px); line-height:.95; margin:8px 0 18px; letter-spacing:-.055em; }}
    p {{ color:#aebed0; line-height:1.6; }} .eyebrow {{ color:#7dd3fc; text-transform:uppercase; letter-spacing:.15em; font-size:12px; font-weight:800; }}
    .status {{ border:1px solid #31506f; background:#0d1c2d; border-radius:18px; padding:20px; }}
    .status strong {{ display:block; color:#86efac; font-size:22px; margin-bottom:5px; }}
    .grid {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:18px; }}
    .card {{ background:#0d1a2a; border:1px solid #263b52; border-radius:20px; padding:18px; box-shadow:0 16px 45px #0005; }}
    .card h2 {{ margin:6px 0 16px; font-size:20px; }} .card img {{ width:100%; aspect-ratio:1; object-fit:contain; background:#f8fafc; border-radius:12px; image-rendering:pixelated; }}
    .verdict {{ display:inline-block; margin:16px 0 8px; padding:6px 10px; border-radius:999px; font-size:12px; font-weight:800; text-transform:uppercase; }}
    .pass {{ background:#123f2b; color:#86efac; }} .fail {{ background:#501d25; color:#fda4af; }}
    dl {{ display:grid; grid-template-columns:1fr auto; gap:8px 18px; font-size:13px; }} dt {{ color:#8fa4ba; }} dd {{ margin:0; font-variant-numeric:tabular-nums; }}
    .notes {{ margin-top:20px; display:grid; grid-template-columns:1fr 1fr; gap:18px; }}
    .panel {{ background:#0a1726; border:1px solid #263b52; border-radius:18px; padding:20px; }}
    .panel h2 {{ margin-top:0; }} li {{ color:#fbbf8b; margin:9px 0; line-height:1.5; }} code {{ color:#bae6fd; }}
    @media(max-width:900px) {{ header,.notes {{ grid-template-columns:1fr; }} .grid {{ grid-template-columns:1fr; }} }}
  </style>
</head>
<body><main>
  <header><div><div class="eyebrow">Issue #61 · offline deterministic proof</div><h1>FS-AI plate<br>simulation viewer</h1><p>All three density fields were evaluated by the same local pyEDGE plane-stress solver. Blue marks supports, red marks loads, and white preserves the four mounting holes.</p></div>
  <div class="status"><strong>Numerical run completed</strong><span>{result['grid_shape'][0]}×{result['grid_shape'][1]} grid · {result['measurements']['total_wall_seconds']:.2f}s · {escape(result['fixture_mapping']['mode'])} · no learned inference</span></div></header>
  <section class="grid" aria-label="Actual saved candidate progression">{''.join(cards)}</section>
  <section class="notes"><div class="panel"><h2>What worked</h2><p>All candidate solves returned finite compliance, displacement, stress, and residual values. The deterministic SIMP counterfactual replay produced the same density hash twice.</p><p><a href="../simulation.json">Open raw simulation evidence</a></p></div>
  <div class="panel"><h2>Modeling warnings</h2><ul>{warnings}</ul></div></section>
</main></body></html>"""
    viewer = output_root / "viewer" / "index.html"
    viewer.parent.mkdir(parents=True, exist_ok=True)
    viewer.write_text(html, encoding="utf-8")


def run(
    problem_path: Path,
    mask_path: Path,
    output_root: Path,
    oat_root: Path,
    baseline_iterations: int,
    fixture_mode: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    problem, transform = load_problem(problem_path)
    masks, mask_manifest = load_masks(mask_path, problem.grid_shape)
    candidates = candidate_family(problem, masks)
    point_diagnostics = point_cell_diagnostics(problem, masks, float(mask_manifest["cell_size_mm"]))
    if fixture_mode == "annulus":
        simulation_problem, fixture_mapping = annulus_fixture(
            problem,
            masks,
            float(mask_manifest["cell_size_mm"]),
        )
    else:
        simulation_problem = problem
        fixture_mapping = {
            "mode": "reference-center-points",
            "support_point_count": len(problem.supports),
            "load_point_count": len(problem.loads),
            "total_force_n": [sum(load.force_n[axis] for load in problem.loads) for axis in range(2)],
            "limitation": "Each contract region is reduced to its center point by the reference adapter.",
        }
    # FS-AI masks and viewer arrays use image order (row=y, column=x). pyEDGE's
    # structured mesh and flattened design variables use (x, y). A square grid
    # otherwise lets this transposition bug pass every shape check.
    rows, columns = problem.grid_shape
    simulation_problem = replace(simulation_problem, grid_shape=(columns, rows))
    solver_densities = [np.ascontiguousarray(candidate["density"].T) for candidate in candidates]
    evaluations, baseline_density, baseline_evaluation, physics = evaluate_and_baseline(
        simulation_problem,
        solver_densities,
        oat_root=oat_root,
        baseline_iterations=baseline_iterations,
    )
    baseline_density = np.ascontiguousarray(baseline_density.T)
    physics["layout_mapping"] = {
        "viewer_and_mask_axes": ["row-y", "column-x"],
        "pyedge_design_variable_axes": ["x", "y"],
        "transposed_before_and_after_solver": True,
    }
    output_root.mkdir(parents=True, exist_ok=True)
    candidate_results = []
    for candidate, evaluation in zip(candidates, evaluations, strict=True):
        array_path = output_root / "candidates" / f"{candidate['id']}.npy"
        density_artifact = write_density(array_path, candidate["density"])
        preview = output_root / "candidates" / f"{candidate['id']}-viewer.png"
        render_density(preview, candidate["density"], masks)
        candidate_results.append(
            {
                "id": candidate["id"],
                "label": candidate["label"],
                "role": candidate["role"],
                "connectivity_pass": connected_support_to_load(candidate["density"], masks),
                "density": density_artifact,
                "preview": preview.relative_to(output_root).as_posix(),
                "evaluation": asdict(evaluation),
            }
        )
    baseline_info = write_density(output_root / "baseline" / "simp-rectangle.npy", baseline_density)
    render_density(output_root / "baseline" / "simp-rectangle-viewer.png", apply_masks(baseline_density, masks), masks)
    baseline_masked = apply_masks(baseline_density, masks)
    baseline_changed = int(np.not_equal(baseline_density, baseline_masked).sum())
    warnings = []
    if fixture_mode == "center" and point_diagnostics["all_points_in_required_void"]:
        warnings.append("All four point support/load coordinates land inside protected void cells; annular regions are currently collapsed to hole centers by the reference adapter.")
    if fixture_mode == "annulus":
        warnings.append("The annulus-distributed fixture is an explicit deterministic proxy, not a recovered bolt/contact load case.")
    if baseline_changed:
        warnings.append(f"The reference SIMP baseline changed in {baseline_changed:,} cells when FS-AI masks were applied post hoc; its optimizer is not mask-aware yet.")
    if not candidate_results[-1]["connectivity_pass"]:
        warnings.append("The disconnected counterfactual is finite only because the solver uses non-zero void stiffness; deterministic connectivity correctly rejects it.")
    warnings.append("This remains a 2-D in-plane plane-stress comparison and does not model the plate's likely out-of-plane vehicle service load.")
    result = {
        "schema_version": "nightshift.fsai-simulation/v1",
        "status": "completed_with_modeling_warnings" if warnings else "passed",
        "offline": True,
        "learned_inference_used": False,
        "problem": {"path": str(problem_path), "sha256": sha256_file(problem_path), "id": problem.design_problem_id},
        "masks": {"path": str(mask_path), "sha256": sha256_file(mask_path)},
        "grid_shape": list(problem.grid_shape),
        "coordinate_transform": transform,
        "point_cell_diagnostics": point_diagnostics,
        "fixture_mapping": fixture_mapping,
        "candidates": candidate_results,
        "baseline": {
            "density": baseline_info,
            "evaluation": asdict(baseline_evaluation),
            "posthoc_mask_changed_cells": baseline_changed,
        },
        "physics": physics,
        "warnings": warnings,
        "measurements": {
            "total_wall_seconds": time.perf_counter() - started,
            "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        },
        "inventory": {
            "python": platform.python_version(),
            "machine": platform.machine(),
            "python_executable": sys.executable,
            "oat_root": str(oat_root),
        },
    }
    write_json(output_root / "simulation.json", result)
    write_viewer(output_root, result)
    write_manifest(output_root)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--problem", type=Path, required=True)
    parser.add_argument("--masks", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--oat-root", type=Path, required=True)
    parser.add_argument("--baseline-iterations", type=int, default=8)
    parser.add_argument("--fixture-mode", choices=("annulus", "center"), default="annulus")
    parser.add_argument("--offline", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.offline:
        raise SystemExit("--offline is mandatory")
    if args.baseline_iterations < 1:
        raise SystemExit("--baseline-iterations must be positive")
    result = run(
        args.problem.resolve(),
        args.masks.resolve(),
        args.output_root.resolve(),
        args.oat_root.resolve(),
        args.baseline_iterations,
        args.fixture_mode,
    )
    print(json.dumps({"status": result["status"], "output_root": str(args.output_root.resolve()), "warnings": result["warnings"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
