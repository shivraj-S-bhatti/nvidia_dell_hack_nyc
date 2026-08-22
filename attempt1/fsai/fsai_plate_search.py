#!/usr/bin/env python3
"""CAD-backed, deterministic FS-AI sensor-plate search.

The source Formula Student vehicle is immutable context.  Candidates replace
only the named ``Example Plate`` and are evaluated with geometric checks.  No
structural or material claim is made by this module.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import re
import resource
import statistics
import sys
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

import cadquery as cq
from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.TDF import TDF_Label, TDF_LabelSequence
from OCP.TDocStd import TDocStd_Document
from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ShapeTool


ASSEMBLY_ID = "fs-ai-ads-dv-2026"
TARGET_PART = "Example Plate"
SENSOR_ASSEMBLY = "Team Additional Sensor Mounting"
OBJECTIVE = "minimize_plate_volume_with_knob_clearance"
MODEL_VERSION = "fsai-sensor-plate-search-v1"
DATABASE_NAME = "attempt1_fsai_search"

SOURCE_REPOSITORY_URL = "https://github.com/FS-AI/FS-AI_ADS-DV_CAD"
SOURCE_RULES_URL = (
    "https://www.imeche.org/docs/default-source/1-oscar/formula-student/"
    "2026/rules/fs-ai-2026-rules-v1.pdf?sfvrsn=2"
)
SOURCE_FILES: dict[str, dict[str, Any]] = {
    "vehicleAssembly": {
        "filename": "FS-AI_ADS-DV_CAD_2026.step",
        "sha256": "9490a334ebadcdfc278e81f78d3aa84b8545bd38e1fa9d45ef10463d82423ac6",
        "solidCount": 115,
        "faceCount": 4754,
    },
    "powerConnector": {
        "filename": "12V_Power_Mated.step",
        "sha256": "cb036de72be5d965263ac4f2a1f76408837b9c10b101bad2337e169bf5d3d458",
        "solidCount": 2,
        "faceCount": 1008,
    },
    "ethernetConnector": {
        "filename": "RJ45_Ethernet.step",
        "sha256": "5af5959761929abd6e7651784114a2917ad3245b60bd5ab4b6f0e7211c409c01",
        "solidCount": 17,
        "faceCount": 828,
    },
    "usbConnector": {
        "filename": "USB_Mated.step",
        "sha256": "3a7e9afd7f0e8cd0ad5dc01ac1a8ba353646a17456d390639ef88840f680efc2",
        "solidCount": 3,
        "faceCount": 643,
    },
}

# Local coordinates measured from the named source part.  Rebuilding these
# values produces exactly the imported source volume and topology.
BASELINE_PARAMETERS = {
    "plateWidthMm": 350.0,
    "topWidthMm": 160.0,
    "plateThicknessMm": 3.0,
}
PROFILE_BOTTOM_Y_MM = -125.0
PROFILE_SHOULDER_Y_MM = 125.0
PROFILE_TOP_Y_MM = 225.0
MOUNT_CENTERS_MM = (
    (-150.0, -100.0),
    (150.0, -100.0),
    (150.0, 100.0),
    (-150.0, 100.0),
)
CONSTRAINTS = {
    "mountHoleDiameterMm": 6.5,
    "knobClearanceDiameterMm": 40.0,
    "maxPlateThicknessMm": 5.0,
    "minimumMountCount": 3,
}
RANGE_NAMES = ("plateWidthMm", "topWidthMm", "plateThicknessMm")


class ContractError(ValueError):
    """Raised when an FS-AI request, asset, or checkpoint violates its contract."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(value: Any, length: int = 16) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()[:length]


def _is_number(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float))


def _finite_number(name: str, value: Any) -> float:
    if not _is_number(value) or not math.isfinite(float(value)):
        raise ContractError(f"{name} must be a finite number")
    return float(value)


@dataclass(frozen=True)
class RangeSpec:
    start: float
    stop: float
    step: float

    @classmethod
    def from_mapping(cls, name: str, value: Any) -> "RangeSpec":
        if not isinstance(value, dict) or set(value) != {"start", "stop", "step"}:
            raise ContractError(f"{name} range must contain only start, stop, and step")
        start = _finite_number(f"{name}.start", value["start"])
        stop = _finite_number(f"{name}.stop", value["stop"])
        step = _finite_number(f"{name}.step", value["step"])
        if step <= 0 or stop < start:
            raise ContractError(f"{name} requires step > 0 and stop >= start")
        result = cls(start=start, stop=stop, step=step)
        values = result.values()
        if not 1 <= len(values) <= 128:
            raise ContractError(f"{name} range must produce 1 to 128 values")
        return result

    def values(self) -> tuple[float, ...]:
        start = Decimal(str(self.start))
        stop = Decimal(str(self.stop))
        step = Decimal(str(self.step))
        span = stop - start
        if span % step != 0:
            raise ContractError("range stop must be reached by an integral number of steps")
        count = int(span / step) + 1
        return tuple(float(start + step * index) for index in range(count))

    def as_dict(self) -> dict[str, float]:
        return {"start": self.start, "stop": self.stop, "step": self.step}


@dataclass(frozen=True)
class SearchRequest:
    ranges: dict[str, RangeSpec]
    candidate_budget: int
    normalized: dict[str, Any]

    @classmethod
    def from_mapping(cls, value: Any) -> "SearchRequest":
        if not isinstance(value, dict):
            raise ContractError("request must be a JSON object")
        required = {
            "assemblyId",
            "targetPart",
            "objective",
            "candidateBudget",
            "ranges",
            "constraints",
        }
        if set(value) != required:
            raise ContractError(f"request fields must be exactly {sorted(required)}")
        if value["assemblyId"] != ASSEMBLY_ID:
            raise ContractError(f"assemblyId must be {ASSEMBLY_ID!r}")
        if value["targetPart"] != TARGET_PART:
            raise ContractError(f"targetPart must be {TARGET_PART!r}")
        if value["objective"] != OBJECTIVE:
            raise ContractError(f"objective must be {OBJECTIVE!r}")
        if value["constraints"] != CONSTRAINTS:
            raise ContractError("constraints must match the frozen FS-AI geometry contract")

        supplied_ranges = value["ranges"]
        if not isinstance(supplied_ranges, dict) or set(supplied_ranges) != set(RANGE_NAMES):
            raise ContractError(f"ranges must be exactly {', '.join(RANGE_NAMES)}")
        ranges = {
            name: RangeSpec.from_mapping(name, supplied_ranges[name])
            for name in RANGE_NAMES
        }
        if not 320.0 <= ranges["plateWidthMm"].start <= ranges["plateWidthMm"].stop <= 400.0:
            raise ContractError("plateWidthMm must stay within 320 to 400 mm")
        if not 80.0 <= ranges["topWidthMm"].start <= ranges["topWidthMm"].stop <= 300.0:
            raise ContractError("topWidthMm must stay within 80 to 300 mm")
        if not 1.0 <= ranges["plateThicknessMm"].start <= ranges["plateThicknessMm"].stop <= 7.0:
            raise ContractError("plateThicknessMm must stay within 1 to 7 mm")
        for name, baseline in BASELINE_PARAMETERS.items():
            if baseline not in ranges[name].values():
                raise ContractError(f"{name} range must contain source baseline {baseline:g}")

        budget = value["candidateBudget"]
        if (
            isinstance(budget, bool)
            or not isinstance(budget, int)
            or not 1 <= budget <= 100_000
        ):
            raise ContractError("candidateBudget must be an integer from 1 to 100000")
        available = math.prod(len(ranges[name].values()) for name in RANGE_NAMES)
        if budget > available:
            raise ContractError(
                f"candidateBudget {budget} exceeds {available} unique combinations"
            )

        normalized = {
            "assemblyId": ASSEMBLY_ID,
            "targetPart": TARGET_PART,
            "objective": OBJECTIVE,
            "candidateBudget": budget,
            "ranges": {name: ranges[name].as_dict() for name in RANGE_NAMES},
            "constraints": dict(CONSTRAINTS),
        }
        return cls(ranges=ranges, candidate_budget=budget, normalized=normalized)

    @property
    def run_id(self) -> str:
        return f"fsai-run-{_digest({'modelVersion': MODEL_VERSION, **self.normalized})}"


def load_request(path: Path) -> SearchRequest:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read request JSON from {path}: {exc}") from exc
    return SearchRequest.from_mapping(value)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonicalize_step_header(path: Path) -> None:
    """Remove the OpenCascade wall-clock timestamp from retained STEP evidence."""

    rendered = path.read_text()
    canonical, timestamp_replacements = re.subn(
        r"(FILE_NAME\('[^']*',)'[^']*'",
        r"\1'1970-01-01T00:00:00'",
        rendered,
        count=1,
    )
    canonical, occurrence_replacements = re.subn(
        r"(NEXT_ASSEMBLY_USAGE_OCCURRENCE\()'\d+'",
        r"\1'1'",
        canonical,
    )
    if timestamp_replacements != 1 or occurrence_replacements != 1:
        raise RuntimeError(f"could not canonicalize STEP FILE_NAME header: {path}")
    path.write_text(canonical)


def _shape_metrics(shape: cq.Shape) -> dict[str, Any]:
    box = shape.BoundingBox()
    solids = shape.Solids()
    return {
        "solidCount": len(solids),
        "faceCount": len(shape.Faces()),
        "valid": shape.isValid() and all(solid.isValid() for solid in solids),
        "volumeMm3": round(shape.Volume(), 6),
        "boundingBoxMm": {
            "x": round(box.xlen, 6),
            "y": round(box.ylen, 6),
            "z": round(box.zlen, 6),
        },
    }


def _label_name(label: TDF_Label) -> str:
    attribute = TDataStd_Name()
    if label.FindAttribute(TDataStd_Name.GetID_s(), attribute):
        return attribute.Get().ToExtString()
    return ""


def _read_vehicle_xcaf(path: Path) -> tuple[Any, Any, TDF_LabelSequence]:
    document = TDocStd_Document(TCollection_ExtendedString("fsai-intake"))
    reader = STEPCAFControl_Reader()
    reader.SetNameMode(True)
    status = reader.ReadFile(str(path))
    if not str(status).endswith("RetDone"):
        raise ContractError(f"OpenCascade could not read {path.name}: {status}")
    if not reader.Transfer(document):
        raise ContractError(f"OpenCascade could not transfer {path.name}")
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    roots = TDF_LabelSequence()
    shape_tool.GetFreeShapes(roots)
    if roots.Length() != 1:
        raise ContractError(f"expected one vehicle root, got {roots.Length()}")
    return document, shape_tool, roots


def _definition_labels(shape_tool: Any) -> dict[str, TDF_Label]:
    labels = TDF_LabelSequence()
    shape_tool.GetShapes(labels)
    result: dict[str, TDF_Label] = {}
    for index in range(1, labels.Length() + 1):
        label = labels.Value(index)
        name = _label_name(label)
        if name:
            if name in result:
                raise ContractError(f"duplicate product definition name: {name}")
            result[name] = label
    return result


def _component_inventory(shape_tool: Any, assembly_label: TDF_Label) -> list[dict[str, Any]]:
    components = TDF_LabelSequence()
    if not XCAFDoc_ShapeTool.GetComponents_s(assembly_label, components, False):
        raise ContractError(f"{SENSOR_ASSEMBLY!r} has no component instances")
    inventory: list[dict[str, Any]] = []
    for index in range(1, components.Length() + 1):
        instance = components.Value(index)
        referred = TDF_Label()
        if not XCAFDoc_ShapeTool.GetReferredShape_s(instance, referred):
            raise ContractError(f"sensor component {_label_name(instance)!r} is not a reference")
        shape = cq.Shape.cast(XCAFDoc_ShapeTool.GetShape_s(referred))
        inventory.append(
            {
                "instanceName": _label_name(instance),
                "productName": _label_name(referred),
                "geometry": _shape_metrics(shape),
            }
        )
    return inventory


def preflight_assets(asset_root: Path) -> dict[str, Any]:
    start = time.perf_counter()
    root = asset_root.resolve()
    if not root.is_dir():
        raise ContractError(f"asset root does not exist: {root}")

    paths: dict[str, Path] = {}
    files: dict[str, Any] = {}
    for role, contract in SOURCE_FILES.items():
        path = (root / contract["filename"]).resolve()
        if path.parent != root or not path.is_file():
            raise ContractError(f"missing required local asset: {contract['filename']}")
        actual_hash = _sha256_file(path)
        if actual_hash != contract["sha256"]:
            raise ContractError(
                f"SHA-256 mismatch for {path.name}: expected {contract['sha256']}, got {actual_hash}"
            )
        paths[role] = path
        files[role] = {
            "filename": path.name,
            "sha256": actual_hash,
            "sizeBytes": path.stat().st_size,
        }

    # XCAF preserves the names and assembly structure needed to find the target.
    document, shape_tool, roots = _read_vehicle_xcaf(paths["vehicleAssembly"])
    definitions = _definition_labels(shape_tool)
    if len(definitions) != 45:
        raise ContractError(f"expected 45 product definitions, got {len(definitions)}")
    missing = {TARGET_PART, SENSOR_ASSEMBLY} - set(definitions)
    if missing:
        raise ContractError(f"missing named FS-AI definitions: {sorted(missing)}")

    vehicle = cq.Shape.cast(XCAFDoc_ShapeTool.GetShape_s(roots.Value(1)))
    vehicle_metrics = _shape_metrics(vehicle)
    expected_vehicle = SOURCE_FILES["vehicleAssembly"]
    if (
        vehicle_metrics["solidCount"] != expected_vehicle["solidCount"]
        or vehicle_metrics["faceCount"] != expected_vehicle["faceCount"]
        or not vehicle_metrics["valid"]
    ):
        raise ContractError(f"vehicle geometry contract changed: {vehicle_metrics}")
    files["vehicleAssembly"]["geometry"] = vehicle_metrics

    target_shape = cq.Shape.cast(XCAFDoc_ShapeTool.GetShape_s(definitions[TARGET_PART]))
    target_metrics = _shape_metrics(target_shape)
    expected_target_box = {"x": 350.0, "y": 350.0, "z": 3.0}
    if target_metrics["boundingBoxMm"] != expected_target_box:
        raise ContractError(f"source target bounding box changed: {target_metrics}")
    if not math.isclose(target_metrics["volumeMm3"], 338601.803131, abs_tol=1e-6):
        raise ContractError(f"source target volume changed: {target_metrics['volumeMm3']}")
    cylindrical_centers = sorted(
        (round(face.Center().x, 6), round(face.Center().y, 6))
        for face in target_shape.Faces()
        if face.geomType() == "CYLINDER"
    )
    if cylindrical_centers != sorted(MOUNT_CENTERS_MM):
        raise ContractError(f"source target mount centers changed: {cylindrical_centers}")

    sensor_components = _component_inventory(shape_tool, definitions[SENSOR_ASSEMBLY])
    if len(sensor_components) != 13:
        raise ContractError(
            f"expected 13 sensor-mount components, got {len(sensor_components)}"
        )

    for role in ("powerConnector", "ethernetConnector", "usbConnector"):
        imported = cq.importers.importStep(str(paths[role])).val()
        metrics = _shape_metrics(imported)
        contract = SOURCE_FILES[role]
        if (
            metrics["solidCount"] != contract["solidCount"]
            or metrics["faceCount"] != contract["faceCount"]
            or not metrics["valid"]
        ):
            raise ContractError(f"{role} geometry contract changed: {metrics}")
        files[role]["geometry"] = metrics

    return {
        "sourceId": ASSEMBLY_ID,
        "sourceRepositoryUrl": SOURCE_REPOSITORY_URL,
        "sourceRulesUrl": SOURCE_RULES_URL,
        "redistributionWarning": (
            "Keep downloaded and derivative CAD under gitignored local artifacts; "
            "the upstream repository does not grant a general redistribution license."
        ),
        "files": files,
        "assembly": {
            "productDefinitionCount": len(definitions),
            **vehicle_metrics,
        },
        "targetPart": {
            "productName": TARGET_PART,
            "geometry": target_metrics,
            "mountCentersMm": [list(center) for center in MOUNT_CENTERS_MM],
        },
        "sensorMountingAssembly": {
            "productName": SENSOR_ASSEMBLY,
            "componentCount": len(sensor_components),
            "components": sensor_components,
        },
        "intakeElapsedMs": round((time.perf_counter() - start) * 1000.0, 3),
    }


def profile_points(parameters: dict[str, float]) -> tuple[tuple[float, float], ...]:
    half_width = parameters["plateWidthMm"] / 2.0
    half_top = parameters["topWidthMm"] / 2.0
    return (
        (-half_width, PROFILE_BOTTOM_Y_MM),
        (half_width, PROFILE_BOTTOM_Y_MM),
        (half_width, PROFILE_SHOULDER_Y_MM),
        (half_top, PROFILE_TOP_Y_MM),
        (-half_top, PROFILE_TOP_Y_MM),
        (-half_width, PROFILE_SHOULDER_Y_MM),
    )


def build_plate(parameters: dict[str, float]) -> cq.Workplane:
    points = profile_points(parameters)
    return (
        cq.Workplane("XY")
        .polyline(points)
        .close()
        .extrude(parameters["plateThicknessMm"])
        .faces(">Z")
        .workplane()
        .pushPoints(MOUNT_CENTERS_MM)
        .hole(CONSTRAINTS["mountHoleDiameterMm"])
    )


def _point_segment_distance(
    point: tuple[float, float], start: tuple[float, float], end: tuple[float, float]
) -> float:
    px, py = point
    ax, ay = start
    bx, by = end
    dx, dy = bx - ax, by - ay
    length_squared = dx * dx + dy * dy
    if length_squared == 0:
        return math.hypot(px - ax, py - ay)
    fraction = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_squared))
    nearest_x = ax + fraction * dx
    nearest_y = ay + fraction * dy
    return math.hypot(px - nearest_x, py - nearest_y)


def minimum_mount_edge_clearance_mm(parameters: dict[str, float]) -> float:
    points = profile_points(parameters)
    segments = tuple(zip(points, points[1:] + points[:1], strict=True))
    return min(
        _point_segment_distance(center, start, end)
        for center in MOUNT_CENTERS_MM
        for start, end in segments
    )


def parameter_combinations(request: SearchRequest) -> list[dict[str, float]]:
    all_parameters = [
        {name: float(value) for name, value in zip(RANGE_NAMES, combination, strict=True)}
        for combination in itertools.product(
            *(request.ranges[name].values() for name in RANGE_NAMES)
        )
    ]
    baseline = dict(BASELINE_PARAMETERS)
    all_parameters.remove(baseline)
    all_parameters.sort(key=lambda parameters: _digest(parameters, length=64))
    selected = [baseline, *all_parameters[: request.candidate_budget - 1]]
    if len({_canonical_json(parameters) for parameters in selected}) != len(selected):
        raise RuntimeError("candidate selection produced duplicate parameters")
    return selected


def geometry_revision_id(parameters: dict[str, float]) -> str:
    return f"fsai-plate-rev-{_digest({'modelVersion': MODEL_VERSION, 'parameters': parameters})}"


def variant_id(run_id: str, ordinal: int, parameters: dict[str, float]) -> str:
    return f"fsai-variant-{_digest({'runId': run_id, 'ordinal': ordinal, 'parameters': parameters})}"


def evaluate_variant(
    request: SearchRequest,
    ordinal: int,
    parameters: dict[str, float],
    baseline_id: str,
) -> dict[str, Any]:
    build_start = time.perf_counter()
    current_id = variant_id(request.run_id, ordinal, parameters)
    try:
        plate = build_plate(parameters)
        shape = plate.val()
        solid_count = len(shape.Solids())
        geometry_valid = solid_count == 1 and shape.isValid()
        build_ms = (time.perf_counter() - build_start) * 1000.0
    except Exception as exc:  # OpenCascade exceptions vary by wheel version.
        return {
            "_id": current_id,
            "runId": request.run_id,
            "variantId": current_id,
            "parentVariantId": None if ordinal == 0 else baseline_id,
            "ordinal": ordinal,
            "parameters": parameters,
            "sourcePartName": TARGET_PART,
            "geometryRevisionId": geometry_revision_id(parameters),
            "artifactPath": None,
            "artifactSha256": None,
            "metrics": None,
            "checks": None,
            "validity": False,
            "buildStatus": "failed",
            "evaluationStatus": "not_run",
            "physicsStatus": "not_run",
            "failureStage": "build",
            "failureReason": f"cad_build_failure:{type(exc).__name__}",
            "timing": {
                "source": "measured",
                "buildMs": round((time.perf_counter() - build_start) * 1000.0, 3),
                "evaluationMs": None,
            },
            "evidenceSource": "cad-derived-parametric",
        }

    evaluation_start = time.perf_counter()
    edge_clearance = minimum_mount_edge_clearance_mm(parameters)
    knob_radius = CONSTRAINTS["knobClearanceDiameterMm"] / 2.0
    knob_margin = edge_clearance - knob_radius
    thickness_margin = CONSTRAINTS["maxPlateThicknessMm"] - parameters["plateThicknessMm"]
    mounted_count = len(MOUNT_CENTERS_MM)
    checks = {
        "oneValidClosedSolid": geometry_valid,
        "mountCount": mounted_count,
        "minimumMountCount": CONSTRAINTS["minimumMountCount"],
        "mountCountPassed": mounted_count >= CONSTRAINTS["minimumMountCount"],
        "knobEnvelopePassed": knob_margin >= -1e-9,
        "thicknessPassed": thickness_margin >= -1e-9,
        "evaluationMethod": "deterministic_geometry_only",
    }
    failures: list[str] = []
    if not geometry_valid:
        failures.append("invalid_closed_solid")
    if not checks["mountCountPassed"]:
        failures.append("insufficient_mount_count")
    if not checks["knobEnvelopePassed"]:
        failures.append("knob_clearance_envelope_intersects_plate_edge")
    if not checks["thicknessPassed"]:
        failures.append("plate_exceeds_5mm_rule_limit")
    valid = not failures
    evaluation_ms = (time.perf_counter() - evaluation_start) * 1000.0
    volume = shape.Volume()
    source_volume = 338601.80313115753
    return {
        "_id": current_id,
        "runId": request.run_id,
        "variantId": current_id,
        "parentVariantId": None if ordinal == 0 else baseline_id,
        "ordinal": ordinal,
        "parameters": parameters,
        "sourcePartName": TARGET_PART,
        "geometryRevisionId": geometry_revision_id(parameters),
        "artifactPath": None,
        "artifactSha256": None,
        "metrics": {
            "materialVolumeMm3": round(volume, 6),
            "volumeReductionVsSourcePercent": round(
                (source_volume - volume) / source_volume * 100.0, 6
            ),
            "minimumMountEdgeClearanceMm": round(edge_clearance, 6),
            "knobClearanceMarginMm": round(knob_margin, 6),
            "thicknessMarginMm": round(thickness_margin, 6),
        },
        "checks": checks,
        "validity": valid,
        "buildStatus": "succeeded",
        "evaluationStatus": "succeeded" if valid else "failed",
        "physicsStatus": "not_run",
        "failureStage": None if valid else "geometry_evaluation",
        "failureReason": None if valid else ";".join(failures),
        "timing": {
            "source": "measured",
            "buildMs": round(build_ms, 3),
            "evaluationMs": round(evaluation_ms, 3),
        },
        "evidenceSource": "cad-derived-parametric",
    }


def choose_finalists(variants: list[dict[str, Any]], count: int = 3) -> list[dict[str, Any]]:
    valid = [variant for variant in variants if variant["validity"]]
    if len(valid) < count:
        raise RuntimeError(f"need {count} valid finalists, found {len(valid)}")
    return sorted(
        valid,
        key=lambda variant: (
            variant["metrics"]["materialVolumeMm3"],
            -variant["metrics"]["knobClearanceMarginMm"],
            variant["ordinal"],
        ),
    )[:count]


def export_finalist(
    variant: dict[str, Any], output_root: Path, artifact_group: str = "finalists"
) -> dict[str, Any]:
    shape = build_plate(variant["parameters"])
    if artifact_group not in {"baseline", "finalists"}:
        raise ContractError("artifact_group must be baseline or finalists")
    artifact_dir = output_root.resolve() / artifact_group / variant["geometryRevisionId"]
    artifact_dir.mkdir(parents=True, exist_ok=True)
    step_path = artifact_dir / "sensor-mounting-plate.step"
    stl_path = artifact_dir / "sensor-mounting-plate.stl"
    manifest_path = artifact_dir / "manifest.json"

    assembly = cq.Assembly(name=ASSEMBLY_ID)
    assembly.add(shape, name="sensor-mounting-plate", color=cq.Color(0.25, 0.30, 0.36))
    assembly.export(str(step_path), exportType="STEP", mode="default")
    _canonicalize_step_header(step_path)
    cq.exporters.export(shape, str(stl_path), tolerance=0.05, angularTolerance=0.1)

    roundtrip = cq.importers.importStep(str(step_path)).val()
    solid_count = len(roundtrip.Solids())
    valid = solid_count == 1 and roundtrip.isValid()
    source_volume = shape.val().Volume()
    roundtrip_volume = roundtrip.Volume()
    if not valid or not math.isclose(source_volume, roundtrip_volume, rel_tol=1e-9):
        raise RuntimeError(
            f"finalist STEP round-trip failed for {variant['variantId']}: "
            f"solids={solid_count}, valid={valid}"
        )
    manifest = {
        "assemblyId": ASSEMBLY_ID,
        "sourcePartName": TARGET_PART,
        "variantId": variant["variantId"],
        "geometryRevisionId": variant["geometryRevisionId"],
        "parameters": variant["parameters"],
        "metrics": variant["metrics"],
        "checks": variant["checks"],
        "engineeringClaim": "geometric checks only; structural physics not run",
        "sourceAssemblySha256": SOURCE_FILES["vehicleAssembly"]["sha256"],
        "validation": {
            "stepRoundtripSolidCount": solid_count,
            "stepRoundtripValid": valid,
            "stepRoundtripVolumeMm3": round(roundtrip_volume, 6),
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    paths = {"step": str(step_path), "stl": str(stl_path), "manifest": str(manifest_path)}
    return {
        "artifactPath": paths,
        "artifactSha256": {name: _sha256_file(Path(path)) for name, path in paths.items()},
        "validation": manifest["validation"],
    }


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * fraction) - 1))
    return round(ordered[index], 3)


def _write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def _load_checkpoint(
    path: Path, request: SearchRequest, parameters: list[dict[str, float]]
) -> list[dict[str, Any]]:
    try:
        checkpoint = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read resume checkpoint {path}: {exc}") from exc
    if not isinstance(checkpoint, dict) or set(checkpoint) != {
        "runId",
        "completedCandidateCount",
        "variants",
        "complete",
    }:
        raise ContractError("checkpoint fields changed")
    if checkpoint["runId"] != request.run_id or not isinstance(checkpoint["variants"], list):
        raise ContractError("checkpoint does not belong to this normalized request")
    variants = checkpoint["variants"]
    if checkpoint["completedCandidateCount"] != len(variants) or len(variants) > len(parameters):
        raise ContractError("checkpoint candidate count is inconsistent")
    for ordinal, variant in enumerate(variants):
        expected_id = variant_id(request.run_id, ordinal, parameters[ordinal])
        if (
            variant.get("ordinal") != ordinal
            or variant.get("variantId") != expected_id
            or variant.get("parameters") != parameters[ordinal]
        ):
            raise ContractError(f"checkpoint variant {ordinal} is inconsistent")
    return variants


def _persist_mongo(
    mongo_uri: str,
    database_name: str,
    request: SearchRequest,
    variants: list[dict[str, Any]],
    result: dict[str, Any],
) -> dict[str, Any]:
    from pymongo import MongoClient
    from pymongo.errors import PyMongoError

    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    try:
        client.admin.command("ping")
        database = client[database_name]
        for variant in variants:
            database.variants.replace_one({"_id": variant["_id"]}, variant, upsert=True)
        run_record = {
            "_id": request.run_id,
            "runId": request.run_id,
            "modelVersion": MODEL_VERSION,
            "normalizedRequest": request.normalized,
            "sourceAssemblySha256": SOURCE_FILES["vehicleAssembly"]["sha256"],
            "candidateCount": len(variants),
            "validCount": result["validCount"],
            "failedCount": result["failedCount"],
            "winnerVariantId": result["winner"]["variantId"],
            "finalistVariantIds": result["finalistVariantIds"],
            "engineeringClaim": result["engineeringClaim"],
        }
        database.design_runs.replace_one({"_id": request.run_id}, run_record, upsert=True)
        evidence = {
            "database": database_name,
            "designRunCount": database.design_runs.count_documents({"runId": request.run_id}),
            "variantCount": database.variants.count_documents({"runId": request.run_id}),
        }
    except PyMongoError as exc:
        raise RuntimeError(f"MongoDB persistence failed: {exc}") from exc
    finally:
        client.close()
    if evidence["designRunCount"] != 1 or evidence["variantCount"] != len(variants):
        raise RuntimeError(f"MongoDB evidence count mismatch: {evidence}")
    return evidence


def run(
    request: SearchRequest,
    asset_root: Path,
    output_root: Path,
    mongo_uri: str | None = None,
    database_name: str = DATABASE_NAME,
    checkpoint_every: int = 50,
    resume: bool = False,
) -> dict[str, Any]:
    if checkpoint_every < 1:
        raise ContractError("checkpoint_every must be at least 1")
    start = time.perf_counter()
    initial_peak_rss_kib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    source_intake = preflight_assets(asset_root)
    parameters = parameter_combinations(request)
    baseline_shape = build_plate(BASELINE_PARAMETERS).val()
    source_target = source_intake["targetPart"]["geometry"]
    reconstruction = {
        "sourceVolumeMm3": source_target["volumeMm3"],
        "reconstructedVolumeMm3": round(baseline_shape.Volume(), 6),
        "absoluteVolumeDeltaMm3": round(
            abs(source_target["volumeMm3"] - baseline_shape.Volume()), 9
        ),
        "sourceFaceCount": source_target["faceCount"],
        "reconstructedFaceCount": len(baseline_shape.Faces()),
        "matched": (
            math.isclose(source_target["volumeMm3"], baseline_shape.Volume(), abs_tol=1e-6)
            and source_target["faceCount"] == len(baseline_shape.Faces())
        ),
    }
    if not reconstruction["matched"]:
        raise RuntimeError(f"source plate reconstruction changed: {reconstruction}")

    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    checkpoint_path = output_root / "checkpoint.json"
    variants: list[dict[str, Any]] = []
    if resume:
        if not checkpoint_path.is_file():
            raise ContractError(f"--resume requested but checkpoint is missing: {checkpoint_path}")
        variants = _load_checkpoint(checkpoint_path, request, parameters)
    resumed_count = len(variants)
    baseline_id = variant_id(request.run_id, 0, parameters[0])
    for ordinal in range(resumed_count, len(parameters)):
        variants.append(
            evaluate_variant(request, ordinal, parameters[ordinal], baseline_id)
        )
        if len(variants) % checkpoint_every == 0 or len(variants) == len(parameters):
            _write_json_atomic(
                checkpoint_path,
                {
                    "runId": request.run_id,
                    "completedCandidateCount": len(variants),
                    "variants": variants,
                    "complete": False,
                },
            )

    finalists = choose_finalists(variants)
    baseline_export = export_finalist(variants[0], output_root, artifact_group="baseline")
    variants[0]["artifactPath"] = baseline_export["artifactPath"]
    variants[0]["artifactSha256"] = baseline_export["artifactSha256"]
    finalist_artifacts: dict[str, Any] = {}
    for finalist in finalists:
        exported = export_finalist(finalist, output_root)
        finalist["artifactPath"] = exported["artifactPath"]
        finalist["artifactSha256"] = exported["artifactSha256"]
        finalist_artifacts[finalist["variantId"]] = exported

    winner = finalists[0]
    valid_count = sum(variant["validity"] for variant in variants)
    failed_count = len(variants) - valid_count
    build_times = [
        float(variant["timing"]["buildMs"])
        for variant in variants
        if variant["timing"]["buildMs"] is not None
    ]
    output_files = {
        "normalizedRequest": str(output_root / "normalized-request.json"),
        "sourceIntake": str(output_root / "source-intake.json"),
        "variants": str(output_root / "variants.json"),
        "winnerAncestry": str(output_root / "winner-ancestry-query.json"),
        "checkpoint": str(checkpoint_path),
    }
    ancestry = [variants[0], winner] if winner["ordinal"] != 0 else [winner]
    _write_json_atomic(Path(output_files["normalizedRequest"]), request.normalized)
    _write_json_atomic(Path(output_files["sourceIntake"]), source_intake)
    _write_json_atomic(Path(output_files["variants"]), variants)
    _write_json_atomic(
        Path(output_files["winnerAncestry"]),
        {
            "runId": request.run_id,
            "winnerVariantId": winner["variantId"],
            "lineageVariantIds": [variant["variantId"] for variant in ancestry],
            "lineage": ancestry,
        },
    )
    _write_json_atomic(
        checkpoint_path,
        {
            "runId": request.run_id,
            "completedCandidateCount": len(variants),
            "variants": variants,
            "complete": True,
        },
    )

    result = {
        "runId": request.run_id,
        "modelVersion": MODEL_VERSION,
        "normalizedRequest": request.normalized,
        "sourceIntake": source_intake,
        "sourceReconstruction": reconstruction,
        "candidateCount": len(variants),
        "resumedCandidateCount": resumed_count,
        "validCount": valid_count,
        "failedCount": failed_count,
        "winner": winner,
        "baselineArtifact": baseline_export,
        "finalistVariantIds": [variant["variantId"] for variant in finalists],
        "finalistArtifacts": finalist_artifacts,
        "engineeringClaim": (
            "CAD-backed geometry and FS-AI mounting-envelope checks only; "
            "material, load case, FEA, and structural safety are not evaluated."
        ),
        "timing": {
            "candidateBuildP50Ms": round(statistics.median(build_times), 3),
            "candidateBuildP95Ms": _percentile(build_times, 0.95),
            "candidateBuildP99Ms": _percentile(build_times, 0.99),
            "elapsedMs": round((time.perf_counter() - start) * 1000.0, 3),
        },
        "memory": {
            "initialPeakRssKiB": initial_peak_rss_kib,
            "finalPeakRssKiB": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        },
        "outputFiles": output_files,
        "mongo": None,
    }
    if mongo_uri:
        result["mongo"] = _persist_mongo(
            mongo_uri, database_name, request, variants, result
        )
    return result


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--asset-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--mongo-uri")
    parser.add_argument("--database", default=DATABASE_NAME)
    parser.add_argument("--checkpoint-every", type=int, default=50)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--result-json", type=Path)
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = run(
            request=load_request(args.request),
            asset_root=args.asset_root,
            output_root=args.output_root,
            mongo_uri=args.mongo_uri,
            database_name=args.database,
            checkpoint_every=args.checkpoint_every,
            resume=args.resume,
        )
    except (ContractError, RuntimeError) as exc:
        print(json.dumps({"runStatus": "failed", "error": str(exc)}), file=sys.stderr)
        return 2
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.result_json:
        args.result_json.parent.mkdir(parents=True, exist_ok=True)
        args.result_json.write_text(rendered)
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
