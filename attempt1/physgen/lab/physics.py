"""OAT pyEDGE evaluator and deterministic SIMP/OC baseline."""

from __future__ import annotations

from dataclasses import dataclass
import math
import sys
import time
import types
from pathlib import Path
from typing import Any

import numpy as np

from .artifacts import sha256_array, validate_density
from .problem import CanonicalProblem


@dataclass(frozen=True)
class Evaluation:
    compliance_n_mm: float
    material_fraction: float
    max_displacement_mm: float
    max_von_mises_mpa: float
    residual: float
    finite: bool


def evaluate_and_baseline(
    problem_spec: CanonicalProblem,
    candidates: list[np.ndarray],
    *,
    oat_root: Path,
    baseline_iterations: int,
) -> tuple[list[Evaluation], np.ndarray, Evaluation, dict[str, Any]]:
    if baseline_iterations < 1:
        raise ValueError("baseline_iterations must be positive")
    _prepare_upstream_imports(oat_root)

    from pyEDGE.CPU import (
        FiniteElement,
        MinimumCompliance,
        OC,
        SPSOLVE,
        StructuredFilter2D,
        StructuredMesh2D,
        StructuredStiffnessKernel,
    )
    from pyEDGE.physics.LinearElasticity import LinearElasticity

    height, width = problem_spec.grid_shape
    lx, ly = problem_spec.extent_mm
    physics = LinearElasticity(
        E=problem_spec.young_modulus_mpa,
        nu=problem_spec.poisson_ratio,
        thickness=problem_spec.thickness_mm,
        type="PlaneStress",
    )
    mesh = StructuredMesh2D(height, width, lx, ly, dtype=np.float64, physics=physics)
    kernel = StructuredStiffnessKernel(mesh)
    density_filter = StructuredFilter2D(mesh, problem_spec.filter_radius_elements)
    fe = FiniteElement(mesh, kernel, SPSOLVE(kernel))
    supports = np.asarray(problem_spec.oat_boundary_conditions(), dtype=np.float64)
    loads = np.asarray(problem_spec.oat_loads(), dtype=np.float64)
    fe.reset_dirichlet_boundary_conditions()
    fe.reset_forces()
    fe.add_dirichlet_boundary_condition(positions=supports[:, :2], dofs=supports[:, 2:])
    fe.add_point_forces(positions=loads[:, :2], forces=loads[:, 2:])

    topology_problem = MinimumCompliance(
        fe,
        density_filter,
        void=problem_spec.void_stiffness,
        penalty=problem_spec.simp_penalty,
        volume_fraction=[problem_spec.material_fraction],
        heavyside=False,
    )
    started = time.perf_counter()
    evaluations = [_evaluate(topology_problem, density, problem_spec.density_threshold) for density in candidates]
    candidate_seconds = time.perf_counter() - started

    baseline_started = time.perf_counter()
    baseline_density, history, converged = _run_baseline(
        topology_problem,
        OC,
        problem_spec.grid_shape,
        baseline_iterations,
    )
    baseline_evaluation = _evaluate(topology_problem, baseline_density, problem_spec.density_threshold)
    baseline_seconds = time.perf_counter() - baseline_started
    replay_started = time.perf_counter()
    replay_density, replay_history, replay_converged = _run_baseline(
        topology_problem,
        OC,
        problem_spec.grid_shape,
        baseline_iterations,
    )
    replay_seconds = time.perf_counter() - replay_started
    baseline_hash = sha256_array(baseline_density)
    replay_hash = sha256_array(replay_density)
    details = {
        "evaluator": "OptimizeAnyTopology pyEDGE CPU MinimumCompliance.FEA",
        "linear_solver": "scipy.sparse.linalg.spsolve",
        "optimizer": "OptimizeAnyTopology pyEDGE OC (deterministic SIMP)",
        "candidate_evaluation_seconds": candidate_seconds,
        "baseline_seconds": baseline_seconds,
        "baseline_replay_seconds": replay_seconds,
        "baseline_iterations_requested": baseline_iterations,
        "baseline_iterations_completed": len(history),
        "baseline_converged": converged,
        "baseline_final_log": history[-1],
        "baseline_content_sha256": baseline_hash,
        "baseline_replay_content_sha256": replay_hash,
        "baseline_deterministic_replay": baseline_hash == replay_hash,
        "baseline_replay_iterations_completed": len(replay_history),
        "baseline_replay_converged": replay_converged,
        "compatibility_shims": [
            "optional sksparse.cholmod import stub; CHOLMOD is never selected",
            "optional k3d import stub; visualization API is never selected",
        ],
    }
    return evaluations, baseline_density, baseline_evaluation, details


def _run_baseline(problem: Any, optimizer_class: Any, shape: tuple[int, int], iterations: int) -> tuple[np.ndarray, list[dict[str, Any]], bool]:
    problem.init_desvars()
    optimizer = optimizer_class(problem)
    history: list[dict[str, Any]] = []
    converged = False
    for _ in range(iterations):
        optimizer.iter()
        history.append(optimizer.logs())
        if optimizer.converged():
            converged = True
            break
    density = validate_density(problem.get_desvars().reshape(shape))
    return density, history, converged


def _evaluate(problem: Any, density: np.ndarray, threshold: float) -> Evaluation:
    canonical = validate_density(density)
    # OAT's published evaluator uses 0.5. Reject a different fixture value so
    # the wrapper cannot silently report results under a changed fixture.
    if threshold != 0.5:
        raise ValueError("OAT MinimumCompliance.FEA uses the frozen density threshold 0.5")
    problem.desvars = canonical.astype(np.float64, copy=False).reshape(-1)
    result = problem.FEA()
    displacement = np.asarray(result["Displacements"])
    von_mises = np.asarray(result["von_mises"])
    rhs_norm = np.linalg.norm(problem.FE.rhs)
    residual = float(np.linalg.norm(problem.FE.rhs - problem.FE.kernel @ displacement) / rhs_norm)
    values = {
        "compliance_n_mm": float(result["compliance"]),
        "material_fraction": float((canonical > threshold).mean()),
        "max_displacement_mm": float(np.linalg.norm(displacement.reshape(-1, 2), axis=1).max()),
        "max_von_mises_mpa": float(np.abs(von_mises).max()),
        "residual": residual,
    }
    finite = all(math.isfinite(value) for value in values.values())
    return Evaluation(**values, finite=finite)


def _prepare_upstream_imports(oat_root: Path) -> None:
    source = str(oat_root)
    if source not in sys.path:
        sys.path.insert(0, source)
    try:
        import sksparse.cholmod  # type: ignore[import-not-found]  # noqa: F401
    except ImportError:
        package = types.ModuleType("sksparse")
        module = types.ModuleType("sksparse.cholmod")

        def unavailable(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("CHOLMOD is unavailable; Issue #44 selects SPSOLVE")

        module.cholesky = unavailable  # type: ignore[attr-defined]
        package.cholmod = module  # type: ignore[attr-defined]
        sys.modules["sksparse"] = package
        sys.modules["sksparse.cholmod"] = module
    try:
        import k3d  # type: ignore[import-not-found]  # noqa: F401
    except ImportError:
        sys.modules["k3d"] = types.ModuleType("k3d")
