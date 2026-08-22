"""Strict DesignProblem v1 to native OAT adapter.

STEP 02 owns the pipeline contract. OAT-only discretization constants live in
the hash-addressed ``design_domain`` sidecar instead of weakening that shared
contract with stage-specific fields.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any


class ProblemContractError(ValueError):
    """Raised when a DesignProblem cannot be mapped to OAT deterministically."""


_REQUIRED_TOP_LEVEL = {
    "schema_version",
    "id",
    "run_id",
    "parent_ids",
    "source_hashes",
    "units",
    "creation_method",
    "evidence_sources",
    "assembly",
    "target_component",
    "design_domain",
    "coordinate_transform",
    "protected_interfaces",
    "keep_outs",
    "supports",
    "loads",
    "material",
    "solver",
    "candidate_budget",
    "seed_policy",
    "material_fraction_target",
    "objective",
}
_DOMAIN_FIELDS = {
    "schema_version",
    "source",
    "grid_shape",
    "extent_mm",
    "thickness_mm",
    "void_stiffness",
    "filter_radius_elements",
    "simp_penalty",
    "density_threshold",
}
_UNITS = {
    "length": "mm",
    "mass": "kg",
    "time": "s",
    "force": "N",
    "pressure": "Pa",
    "density": "kg/m^3",
}
_IDENTITY_4X4 = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]


def _finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProblemContractError(f"{label} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise ProblemContractError(f"{label} must be finite")
    return result


def _vector(value: Any, length: int, label: str) -> tuple[float, ...]:
    if not isinstance(value, list) or len(value) != length:
        raise ProblemContractError(f"{label} must contain exactly {length} values")
    return tuple(_finite_number(item, f"{label}[{index}]") for index, item in enumerate(value))


def _exact_object(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProblemContractError(f"{label} must be an object")
    missing = sorted(fields - value.keys())
    unknown = sorted(value.keys() - fields)
    if missing:
        raise ProblemContractError(f"missing {label} fields: {', '.join(missing)}")
    if unknown:
        raise ProblemContractError(f"unknown {label} fields: {', '.join(unknown)}")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _repository_root(path: Path) -> Path:
    for parent in (path.parent, *path.parents):
        if (parent / ".git").exists():
            return parent
    return Path.cwd().resolve()


def _region_center(region: Any, label: str) -> tuple[float, float]:
    if not isinstance(region, dict):
        raise ProblemContractError(f"{label} must be an object")
    kind = region.get("kind")
    if kind == "axis_aligned_box":
        _exact_object(region, {"kind", "min_mm", "max_mm"}, label)
        minimum = _vector(region["min_mm"], 3, f"{label}.min_mm")
        maximum = _vector(region["max_mm"], 3, f"{label}.max_mm")
        if any(low > high for low, high in zip(minimum, maximum, strict=True)):
            raise ProblemContractError(f"{label}.min_mm must not exceed max_mm")
        return ((minimum[0] + maximum[0]) / 2, (minimum[1] + maximum[1]) / 2)
    if kind == "cylinder":
        _exact_object(region, {"kind", "center_mm", "axis", "radius_mm", "height_mm"}, label)
        center = _vector(region["center_mm"], 3, f"{label}.center_mm")
        return (center[0], center[1])
    raise ProblemContractError(f"{label}.kind is not supported by the OAT 2-D adapter: {kind!r}")


@dataclass(frozen=True)
class Support:
    position_mm: tuple[float, float]
    dofs: tuple[int, int]


@dataclass(frozen=True)
class Load:
    position_mm: tuple[float, float]
    force_n: tuple[float, float]


@dataclass(frozen=True)
class CanonicalProblem:
    raw: dict[str, Any]
    schema_version: str
    design_problem_id: str
    run_id: str
    target_component_id: str
    protected_interface_ids: tuple[str, ...]
    grid_shape: tuple[int, int]
    extent_mm: tuple[float, float]
    supports: tuple[Support, ...]
    loads: tuple[Load, ...]
    material_fraction: float
    candidate_budget: int
    seeds: tuple[int, ...]
    young_modulus_mpa: float
    poisson_ratio: float
    thickness_mm: float
    void_stiffness: float
    filter_radius_elements: float
    simp_penalty: float
    density_threshold: float
    domain_artifact_path: Path

    @classmethod
    def from_path(cls, path: Path) -> "CanonicalProblem":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProblemContractError(f"cannot read DesignProblem {path}: {exc}") from exc
        return cls.from_dict(payload, repository_root=_repository_root(path.resolve()))

    @classmethod
    def from_dict(
        cls,
        payload: Any,
        *,
        repository_root: Path | None = None,
    ) -> "CanonicalProblem":
        root = (repository_root or Path.cwd()).resolve()
        problem = _exact_object(payload, _REQUIRED_TOP_LEVEL, "DesignProblem")
        if problem["schema_version"] != "nightshift.design-problem/v1":
            raise ProblemContractError("schema_version must be nightshift.design-problem/v1")
        problem_id = problem["id"]
        run_id = problem["run_id"]
        if not all(isinstance(value, str) and value for value in (problem_id, run_id)):
            raise ProblemContractError("id and run_id must be non-empty strings")
        if problem["units"] != _UNITS:
            raise ProblemContractError(f"units must be exactly {_UNITS}")
        if problem["parent_ids"] != []:
            raise ProblemContractError("DesignProblem parent_ids must be empty")

        transform = problem["coordinate_transform"]
        if not isinstance(transform, dict) or transform.get("matrix_row_major") != _IDENTITY_4X4:
            raise ProblemContractError("the OAT 2-D adapter currently requires an identity coordinate transform")

        domain_ref = problem["design_domain"]
        if not isinstance(domain_ref, dict):
            raise ProblemContractError("design_domain must be an artifact reference")
        digest = domain_ref.get("sha256")
        if not isinstance(digest, str) or domain_ref.get("uri") != f"artifact://sha256/{digest}":
            raise ProblemContractError("design_domain artifact URI and sha256 must match")
        domain_evidence = next(
            (
                source
                for source in problem["evidence_sources"]
                if isinstance(source, dict)
                and source.get("sha256") == digest
                and isinstance(source.get("uri"), str)
                and source["uri"].startswith("repo://")
            ),
            None,
        )
        if domain_evidence is None:
            raise ProblemContractError("design_domain must have a same-hash repo:// evidence source")
        relative = domain_evidence["uri"].removeprefix("repo://")
        domain_path = (root / relative).resolve()
        if not domain_path.is_relative_to(root):
            raise ProblemContractError("design_domain repo URI escapes the repository")
        if not domain_path.is_file():
            raise ProblemContractError(f"design_domain sidecar is missing: {domain_path}")
        actual_digest = _sha256_file(domain_path)
        if actual_digest != digest:
            raise ProblemContractError(
                f"design_domain hash mismatch: expected {digest}, observed {actual_digest}"
            )
        try:
            domain = json.loads(domain_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ProblemContractError(f"invalid design_domain JSON: {exc}") from exc
        domain = _exact_object(domain, _DOMAIN_FIELDS, "design_domain sidecar")
        if domain["schema_version"] != "nightshift.oat-domain/v1":
            raise ProblemContractError("unsupported design_domain sidecar schema_version")

        shape = domain["grid_shape"]
        if (
            not isinstance(shape, list)
            or len(shape) != 2
            or any(isinstance(value, bool) or not isinstance(value, int) or value < 2 for value in shape)
        ):
            raise ProblemContractError("design_domain grid_shape must contain two integers >= 2")
        grid_shape = (shape[0], shape[1])
        extent_values = _vector(domain["extent_mm"], 2, "design_domain.extent_mm")
        extent = (extent_values[0], extent_values[1])
        if min(extent) <= 0:
            raise ProblemContractError("design_domain extent_mm values must be positive")

        supports_raw = problem["supports"]
        if not isinstance(supports_raw, list) or not supports_raw:
            raise ProblemContractError("supports must be a non-empty array")
        supports: list[Support] = []
        for index, support in enumerate(supports_raw):
            if not isinstance(support, dict):
                raise ProblemContractError(f"supports[{index}] must be an object")
            position = _region_center(support.get("region"), f"supports[{index}].region")
            constrained = support.get("constrained_dofs")
            if not isinstance(constrained, list) or not constrained:
                raise ProblemContractError(f"supports[{index}].constrained_dofs must be non-empty")
            unsupported = sorted(set(constrained) - {"x", "y"})
            if unsupported:
                raise ProblemContractError(
                    f"supports[{index}] has non-2-D constrained DOFs: {', '.join(unsupported)}"
                )
            supports.append(Support(position, (int("x" in constrained), int("y" in constrained))))

        loads_raw = problem["loads"]
        if not isinstance(loads_raw, list) or not loads_raw:
            raise ProblemContractError("loads must be a non-empty array")
        loads: list[Load] = []
        for index, load in enumerate(loads_raw):
            if not isinstance(load, dict) or load.get("kind") != "force":
                raise ProblemContractError(f"loads[{index}] must be a force for the OAT 2-D adapter")
            position = _region_center(load.get("region"), f"loads[{index}].region")
            components = _vector(load.get("components"), 3, f"loads[{index}].components")
            if components[2] != 0:
                raise ProblemContractError(f"loads[{index}] has a non-zero out-of-plane component")
            loads.append(Load(position, (components[0], components[1])))

        for label, point in [
            *(("support", item.position_mm) for item in supports),
            *(("load", item.position_mm) for item in loads),
        ]:
            if not (0 <= point[0] <= extent[0] and 0 <= point[1] <= extent[1]):
                raise ProblemContractError(f"{label} position {point} lies outside domain extent {extent}")

        fraction = _finite_number(problem["material_fraction_target"], "material_fraction_target")
        if not 0 < fraction <= 1:
            raise ProblemContractError("material_fraction_target must be in (0, 1]")
        budget = problem["candidate_budget"]
        if isinstance(budget, bool) or not isinstance(budget, int) or budget < 3:
            raise ProblemContractError("candidate_budget must be an integer >= 3")
        seed_policy = problem["seed_policy"]
        if not isinstance(seed_policy, dict) or set(seed_policy) != {"mode", "seeds"}:
            raise ProblemContractError("seed_policy must contain exactly mode and seeds")
        if seed_policy["mode"] not in {"fixed", "sequence"}:
            raise ProblemContractError("seed_policy.mode must be fixed or sequence")
        seeds = seed_policy["seeds"]
        if not isinstance(seeds, list) or not seeds or any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in seeds
        ):
            raise ProblemContractError("seed_policy.seeds must be a non-empty non-negative integer array")

        material = problem["material"]
        solver = problem["solver"]
        if not isinstance(material, dict) or not isinstance(solver, dict):
            raise ProblemContractError("material and solver must be objects")
        if solver.get("analysis_type") != "linear_static" or solver.get("element_type") != "plane_stress_quad":
            raise ProblemContractError("OAT runtime requires linear_static plane_stress_quad")
        if solver.get("deterministic") is not True:
            raise ProblemContractError("solver.deterministic must be true")

        interfaces = problem["protected_interfaces"]
        if not isinstance(interfaces, list) or not interfaces:
            raise ProblemContractError("protected_interfaces must be non-empty")
        interface_ids = tuple(item.get("interface_id") for item in interfaces if isinstance(item, dict))
        if len(interface_ids) != len(interfaces) or any(not isinstance(value, str) for value in interface_ids):
            raise ProblemContractError("every protected interface must have an interface_id")
        target = problem["target_component"]
        if not isinstance(target, dict) or not isinstance(target.get("component_id"), str):
            raise ProblemContractError("target_component.component_id is required")

        youngs_pa = _finite_number(material.get("youngs_modulus_pa"), "material.youngs_modulus_pa")
        thickness = _finite_number(domain["thickness_mm"], "design_domain.thickness_mm")
        void = _finite_number(domain["void_stiffness"], "design_domain.void_stiffness")
        filter_radius = _finite_number(domain["filter_radius_elements"], "design_domain.filter_radius_elements")
        penalty = _finite_number(domain["simp_penalty"], "design_domain.simp_penalty")
        threshold = _finite_number(domain["density_threshold"], "design_domain.density_threshold")
        if youngs_pa <= 0 or thickness <= 0 or filter_radius <= 0 or penalty <= 0:
            raise ProblemContractError("material and domain physical/solver constants must be positive")
        if not 0 < void < 1 or not 0 < threshold < 1:
            raise ProblemContractError("void_stiffness and density_threshold must be in (0, 1)")

        return cls(
            raw=problem,
            schema_version=problem["schema_version"],
            design_problem_id=problem_id,
            run_id=run_id,
            target_component_id=target["component_id"],
            protected_interface_ids=interface_ids,
            grid_shape=grid_shape,
            extent_mm=extent,
            supports=tuple(supports),
            loads=tuple(loads),
            material_fraction=fraction,
            candidate_budget=budget,
            seeds=tuple(seeds),
            young_modulus_mpa=youngs_pa / 1_000_000.0,
            poisson_ratio=_finite_number(material.get("poisson_ratio"), "material.poisson_ratio"),
            thickness_mm=thickness,
            void_stiffness=void,
            filter_radius_elements=filter_radius,
            simp_penalty=penalty,
            density_threshold=threshold,
            domain_artifact_path=domain_path,
        )

    def oat_boundary_conditions(self) -> list[list[float]]:
        return [
            [support.position_mm[0], support.position_mm[1], float(support.dofs[0]), float(support.dofs[1])]
            for support in self.supports
        ]

    def oat_loads(self) -> list[list[float]]:
        return [
            [load.position_mm[0], load.position_mm[1], load.force_n[0], load.force_n[1]]
            for load in self.loads
        ]
