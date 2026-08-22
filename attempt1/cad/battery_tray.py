#!/usr/bin/env python3
"""Deterministic six-part S500 battery-tray generator for Issue #11."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import cadquery as cq


ASSEMBLY_ID = "s500-battery-tray-v1"
MODEL_DEFINITION_VERSION = "cadquery-battery-tray-v1"
SOURCE_STEP_SHA256 = (
    "c8d3bc53168bbfe29d7c49cfe49f8523844c5c12d6431a4ea0c30e8b2d851c36"
)
SOURCE_GUIDE_URL = (
    "https://github.com/PX4/PX4-user_guide/blob/main/en/frames_multicopter/"
    "holybro_s500_v2_pixhawk4.md"
)

# Millimetres. Board, pad, hole pattern, and screw-head envelope were measured
# from the checked-in, vendor-sourced S500 STEP. M2.5 x 6 is from the guide BOM.
BASELINE_TRAY_WIDTH_MM = 100.0
BOARD_DEPTH_MM = 40.3
BOARD_THICKNESS_MM = 2.0
BASELINE_PAD_WIDTH_MM = 78.551819982
PAD_DEPTH_MM = 24.0
PAD_THICKNESS_MM = 2.0
BASELINE_SCREW_COLUMN_OFFSET_MM = 35.0
SCREW_ROW_OFFSET_MM = 12.5
SCREW_NOMINAL_DIAMETER_MM = 2.5
SCREW_NOMINAL_LENGTH_MM = 6.0
SCREW_CLEARANCE_DIAMETER_MM = 2.6
SCREW_HEAD_DIAMETER_MM = 4.2
SCREW_HEAD_HEIGHT_MM = 1.3

BOARD_ID = "battery-mounting-board"
PAD_ID = "battery-pad"
SCREW_IDS = (
    "mounting-screw-left-front",
    "mounting-screw-left-rear",
    "mounting-screw-right-front",
    "mounting-screw-right-rear",
)
PART_IDS = (BOARD_ID, PAD_ID, *SCREW_IDS)


class ContractError(ValueError):
    """Raised when the fixed Issue #11 mutation contract is violated."""


@dataclass(frozen=True)
class MutationRequest:
    parameter: str
    delta_mm: float

    @classmethod
    def from_mapping(cls, value: Any) -> "MutationRequest":
        if not isinstance(value, dict):
            raise ContractError("request must be a JSON object")
        expected_keys = {"parameter", "deltaMm"}
        if set(value) != expected_keys:
            raise ContractError(
                "request must contain only 'parameter' and 'deltaMm'"
            )
        if value["parameter"] != "trayWidthMm":
            raise ContractError("parameter must be 'trayWidthMm'")
        delta = value["deltaMm"]
        if isinstance(delta, bool) or not isinstance(delta, (int, float)):
            raise ContractError("deltaMm must be a number")
        delta = float(delta)
        if not math.isfinite(delta):
            raise ContractError("deltaMm must be finite")
        # The issue freezes one bounded mutation. Expand the schema only when a
        # later issue explicitly approves another design operation.
        if delta != 10.0:
            raise ContractError("Issue #11 currently permits only deltaMm = 10")
        return cls(parameter="trayWidthMm", delta_mm=delta)

    def as_dict(self) -> dict[str, Any]:
        return {"parameter": self.parameter, "deltaMm": self.delta_mm}


@dataclass
class PartModel:
    part_id: str
    kind: str
    shape: cq.Workplane
    values: dict[str, Any]


@dataclass
class RevisionModel:
    revision_id: str
    parent_revision_id: str | None
    tray_width_mm: float
    parts: list[PartModel]

    def part(self, part_id: str) -> PartModel:
        return next(part for part in self.parts if part.part_id == part_id)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(value: Any, length: int = 12) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()[:length]


def revision_id(tray_width_mm: float) -> str:
    payload = {
        "assemblyId": ASSEMBLY_ID,
        "modelDefinitionVersion": MODEL_DEFINITION_VERSION,
        "sourceStepSha256": SOURCE_STEP_SHA256,
        "trayWidthMm": tray_width_mm,
    }
    return f"tray-rev-{_digest(payload)}"


def request_id(request: MutationRequest) -> str:
    return f"change-{_digest({'assemblyId': ASSEMBLY_ID, **request.as_dict()})}"


def _box(width: float, depth: float, height: float, z_bottom: float) -> cq.Workplane:
    return (
        cq.Workplane("XY")
        .box(width, depth, height, centered=(True, True, False))
        .translate((0.0, 0.0, z_bottom))
    )


def _screw(x_mm: float, y_mm: float) -> cq.Workplane:
    # The threaded section is intentionally represented by its exact nominal
    # M2.5 x 6 envelope; cosmetic thread geometry is not part of the contract.
    shaft = (
        cq.Workplane("XY")
        .circle(SCREW_NOMINAL_DIAMETER_MM / 2.0)
        .extrude(SCREW_NOMINAL_LENGTH_MM)
        .translate((x_mm, y_mm, BOARD_THICKNESS_MM - SCREW_NOMINAL_LENGTH_MM))
    )
    head = (
        cq.Workplane("XY")
        .circle(SCREW_HEAD_DIAMETER_MM / 2.0)
        .extrude(SCREW_HEAD_HEIGHT_MM)
        .translate((x_mm, y_mm, BOARD_THICKNESS_MM))
    )
    return shaft.union(head)


def build_revision(tray_width_mm: float, parent_revision_id: str | None) -> RevisionModel:
    width_delta_mm = tray_width_mm - BASELINE_TRAY_WIDTH_MM
    pad_width_mm = BASELINE_PAD_WIDTH_MM + width_delta_mm
    screw_column_offset_mm = BASELINE_SCREW_COLUMN_OFFSET_MM + width_delta_mm / 2.0

    hole_points = [
        (-screw_column_offset_mm, -SCREW_ROW_OFFSET_MM),
        (-screw_column_offset_mm, SCREW_ROW_OFFSET_MM),
        (screw_column_offset_mm, -SCREW_ROW_OFFSET_MM),
        (screw_column_offset_mm, SCREW_ROW_OFFSET_MM),
    ]
    board_shape = (
        _box(tray_width_mm, BOARD_DEPTH_MM, BOARD_THICKNESS_MM, 0.0)
        .faces(">Z")
        .workplane()
        .pushPoints(hole_points)
        .hole(SCREW_CLEARANCE_DIAMETER_MM)
    )
    pad_shape = _box(
        pad_width_mm,
        PAD_DEPTH_MM,
        PAD_THICKNESS_MM,
        BOARD_THICKNESS_MM,
    )

    screw_positions = (
        (-screw_column_offset_mm, -SCREW_ROW_OFFSET_MM),
        (-screw_column_offset_mm, SCREW_ROW_OFFSET_MM),
        (screw_column_offset_mm, -SCREW_ROW_OFFSET_MM),
        (screw_column_offset_mm, SCREW_ROW_OFFSET_MM),
    )
    parts = [
        PartModel(
            part_id=BOARD_ID,
            kind="battery_mounting_board",
            shape=board_shape,
            values={
                "widthMm": tray_width_mm,
                "depthMm": BOARD_DEPTH_MM,
                "thicknessMm": BOARD_THICKNESS_MM,
                "holeColumnOffsetMm": screw_column_offset_mm,
                "holeRowOffsetMm": SCREW_ROW_OFFSET_MM,
                "holeDiameterMm": SCREW_CLEARANCE_DIAMETER_MM,
            },
        ),
        PartModel(
            part_id=PAD_ID,
            kind="battery_pad",
            shape=pad_shape,
            values={
                "widthMm": pad_width_mm,
                "depthMm": PAD_DEPTH_MM,
                "thicknessMm": PAD_THICKNESS_MM,
            },
        ),
    ]
    for part_id, (x_mm, y_mm) in zip(SCREW_IDS, screw_positions, strict=True):
        parts.append(
            PartModel(
                part_id=part_id,
                kind="m2.5x6_mounting_screw",
                shape=_screw(x_mm, y_mm),
                values={
                    "xMm": x_mm,
                    "yMm": y_mm,
                    "nominalDiameterMm": SCREW_NOMINAL_DIAMETER_MM,
                    "nominalLengthMm": SCREW_NOMINAL_LENGTH_MM,
                },
            )
        )

    return RevisionModel(
        revision_id=revision_id(tray_width_mm),
        parent_revision_id=parent_revision_id,
        tray_width_mm=tray_width_mm,
        parts=parts,
    )


def _shape_solid_count(shape: cq.Workplane) -> int:
    return len(shape.val().Solids())


def validate_revision(revision: RevisionModel) -> dict[str, Any]:
    errors: list[str] = []
    if tuple(part.part_id for part in revision.parts) != PART_IDS:
        errors.append("part IDs or order changed")

    part_checks: dict[str, Any] = {}
    for part in revision.parts:
        solid_count = _shape_solid_count(part.shape)
        valid = part.shape.val().isValid()
        part_checks[part.part_id] = {
            "solidCount": solid_count,
            "valid": valid,
        }
        if solid_count != 1 or not valid:
            errors.append(f"{part.part_id} is not one valid closed solid")

    expected_delta = revision.tray_width_mm - BASELINE_TRAY_WIDTH_MM
    expected_pad_width = BASELINE_PAD_WIDTH_MM + expected_delta
    expected_column = BASELINE_SCREW_COLUMN_OFFSET_MM + expected_delta / 2.0
    board = revision.part(BOARD_ID)
    pad = revision.part(PAD_ID)
    if not math.isclose(board.values["widthMm"], revision.tray_width_mm, abs_tol=1e-9):
        errors.append("board width does not follow trayWidthMm")
    if not math.isclose(pad.values["widthMm"], expected_pad_width, abs_tol=1e-9):
        errors.append("pad width did not propagate")

    expected_x = (-expected_column, -expected_column, expected_column, expected_column)
    expected_y = (
        -SCREW_ROW_OFFSET_MM,
        SCREW_ROW_OFFSET_MM,
        -SCREW_ROW_OFFSET_MM,
        SCREW_ROW_OFFSET_MM,
    )
    aligned_screws = 0
    for index, screw_id in enumerate(SCREW_IDS):
        screw = revision.part(screw_id)
        x_aligned = math.isclose(screw.values["xMm"], expected_x[index], abs_tol=1e-9)
        y_aligned = math.isclose(screw.values["yMm"], expected_y[index], abs_tol=1e-9)
        if x_aligned and y_aligned:
            aligned_screws += 1
        else:
            errors.append(f"{screw_id} is not aligned to its board hole")

    return {
        "passed": not errors,
        "errors": errors,
        "partCount": len(revision.parts),
        "closedSolidCount": sum(
            check["solidCount"] == 1 and check["valid"]
            for check in part_checks.values()
        ),
        "alignedScrewCount": aligned_screws,
        "partChecks": part_checks,
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def export_revision(revision: RevisionModel, output_root: Path) -> dict[str, Any]:
    validation = validate_revision(revision)
    if not validation["passed"]:
        raise RuntimeError(f"pre-export validation failed: {validation['errors']}")

    revision_dir = output_root.resolve() / revision.revision_id
    revision_dir.mkdir(parents=True, exist_ok=True)
    step_path = revision_dir / "battery-tray.step"
    stl_path = revision_dir / "battery-tray.stl"
    manifest_path = revision_dir / "manifest.json"

    assembly = cq.Assembly(name=ASSEMBLY_ID)
    colors = {
        BOARD_ID: cq.Color(0.24, 0.28, 0.33),
        PAD_ID: cq.Color(0.10, 0.10, 0.10),
    }
    for part in revision.parts:
        assembly.add(
            part.shape,
            name=part.part_id,
            color=colors.get(part.part_id, cq.Color(0.72, 0.72, 0.75)),
        )
    assembly.export(str(step_path), exportType="STEP", mode="default")

    compound = cq.Compound.makeCompound([part.shape.val() for part in revision.parts])
    cq.exporters.export(
        compound,
        str(stl_path),
        tolerance=0.05,
        angularTolerance=0.1,
    )

    roundtrip = cq.importers.importStep(str(step_path))
    roundtrip_solids = roundtrip.val().Solids()
    roundtrip_valid = all(solid.isValid() for solid in roundtrip_solids)
    if len(roundtrip_solids) != 6 or not roundtrip_valid:
        raise RuntimeError(
            "STEP round-trip failed: expected six valid solids, "
            f"got {len(roundtrip_solids)}"
        )

    manifest = {
        "assemblyId": ASSEMBLY_ID,
        "revisionId": revision.revision_id,
        "parentRevisionId": revision.parent_revision_id,
        "modelDefinitionVersion": MODEL_DEFINITION_VERSION,
        "source": {
            "stepPath": "S500-C1_ASM.step",
            "stepSha256": SOURCE_STEP_SHA256,
            "assemblyGuideUrl": SOURCE_GUIDE_URL,
        },
        "parameters": {"trayWidthMm": revision.tray_width_mm},
        "parts": [
            {"partId": part.part_id, "kind": part.kind, "values": part.values}
            for part in revision.parts
        ],
        "validation": {
            **validation,
            "stepRoundtripSolidCount": len(roundtrip_solids),
            "stepRoundtripValid": roundtrip_valid,
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    return {
        "assemblyId": ASSEMBLY_ID,
        "partModeRevision": revision.revision_id,
        "parentRevisionId": revision.parent_revision_id,
        "artifactPath": {
            "step": str(step_path),
            "stl": str(stl_path),
            "manifest": str(manifest_path),
        },
        "artifactSha256": {
            "step": _sha256_file(step_path),
            "stl": _sha256_file(stl_path),
            "manifest": _sha256_file(manifest_path),
        },
        "parameters": {"trayWidthMm": revision.tray_width_mm},
        "validation": manifest["validation"],
        "buildStatus": "succeeded",
    }


def _part_values(revision: RevisionModel) -> dict[str, dict[str, Any]]:
    return {part.part_id: part.values for part in revision.parts}


def compare_revisions(
    baseline: RevisionModel, changed: RevisionModel
) -> dict[str, Any]:
    return {
        "boardWidthDeltaMm": (
            changed.part(BOARD_ID).values["widthMm"]
            - baseline.part(BOARD_ID).values["widthMm"]
        ),
        "padWidthDeltaMm": (
            changed.part(PAD_ID).values["widthMm"]
            - baseline.part(PAD_ID).values["widthMm"]
        ),
        "screwDeltaXmm": {
            screw_id: (
                changed.part(screw_id).values["xMm"]
                - baseline.part(screw_id).values["xMm"]
            )
            for screw_id in SCREW_IDS
        },
        "alignedScrewCount": validate_revision(changed)["alignedScrewCount"],
    }


def dependency_edges() -> list[dict[str, Any]]:
    parameter_id = "parameter:trayWidthMm"
    edges = [
        {
            "_id": f"{parameter_id}->{BOARD_ID}",
            "from": parameter_id,
            "to": BOARD_ID,
            "type": "parameter_drives",
            "targetFields": ["widthMm", "holeColumnOffsetMm"],
            "rule": "width += deltaMm; holeColumnOffset += deltaMm / 2",
            "approved": True,
        },
        {
            "_id": f"{parameter_id}->{PAD_ID}",
            "from": parameter_id,
            "to": PAD_ID,
            "type": "parameter_drives",
            "targetFields": ["widthMm"],
            "rule": "width += deltaMm",
            "approved": True,
        },
    ]
    for screw_id in SCREW_IDS:
        direction = -1 if "left" in screw_id else 1
        edges.append(
            {
                "_id": f"{parameter_id}->{screw_id}",
                "from": parameter_id,
                "to": screw_id,
                "type": "parameter_drives",
                "targetFields": ["xMm"],
                "rule": f"x += deltaMm / 2 * {direction}",
                "approved": True,
            }
        )
    return edges


def persist_mongo(
    mongo_uri: str,
    database_name: str,
    request: MutationRequest,
    baseline: RevisionModel,
    changed: RevisionModel,
    baseline_export: dict[str, Any],
    changed_export: dict[str, Any],
) -> dict[str, Any]:
    from pymongo import MongoClient
    from pymongo.errors import PyMongoError

    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    try:
        client.admin.command("ping")
    except PyMongoError as exc:
        client.close()
        raise RuntimeError(f"MongoDB connection failed: {exc}") from exc
    database = client[database_name]

    baseline_values = _part_values(baseline)
    changed_values = _part_values(changed)
    for part_id in PART_IDS:
        part = baseline.part(part_id)
        database.parts.replace_one(
            {"_id": part_id},
            {
                "_id": part_id,
                "assemblyId": ASSEMBLY_ID,
                "kind": part.kind,
                "source": "team-authored-parametric-proxy",
                "sourceStepSha256": SOURCE_STEP_SHA256,
                "revisionValues": {
                    baseline.revision_id: baseline_values[part_id],
                    changed.revision_id: changed_values[part_id],
                },
            },
            upsert=True,
        )

    edges = dependency_edges()
    for edge in edges:
        database.dependencies.replace_one({"_id": edge["_id"]}, edge, upsert=True)

    change_id = request_id(request)
    database.change_requests.replace_one(
        {"_id": change_id},
        {
            "_id": change_id,
            "assemblyId": ASSEMBLY_ID,
            "requestText": "Make the battery tray 10 mm wider.",
            "typedRequest": request.as_dict(),
            "baselineRevisionId": baseline.revision_id,
            "changedRevisionId": changed.revision_id,
            "oldValues": baseline_values,
            "newValues": changed_values,
            "status": "applied",
        },
        upsert=True,
    )

    for revision, exported in (
        (baseline, baseline_export),
        (changed, changed_export),
    ):
        database.revisions.replace_one(
            {"_id": revision.revision_id},
            {
                "_id": revision.revision_id,
                "assemblyId": ASSEMBLY_ID,
                "parentRevisionId": revision.parent_revision_id,
                "requestId": None if revision is baseline else change_id,
                "parameters": {"trayWidthMm": revision.tray_width_mm},
                "partValues": _part_values(revision),
                "artifactPath": exported["artifactPath"],
                "artifactSha256": exported["artifactSha256"],
                "validation": exported["validation"],
            },
            upsert=True,
        )

    evidence = {
        "database": database_name,
        "partNodeCount": database.parts.count_documents({"_id": {"$in": list(PART_IDS)}}),
        "parameterDrivesEdgeCount": database.dependencies.count_documents(
            {"_id": {"$in": [edge["_id"] for edge in edges]}, "type": "parameter_drives"}
        ),
        "changeRequestCount": database.change_requests.count_documents(
            {"_id": change_id}
        ),
        "revisionCount": database.revisions.count_documents(
            {"_id": {"$in": [baseline.revision_id, changed.revision_id]}}
        ),
    }
    client.close()
    if evidence != {
        "database": database_name,
        "partNodeCount": 6,
        "parameterDrivesEdgeCount": 6,
        "changeRequestCount": 1,
        "revisionCount": 2,
    }:
        raise RuntimeError(f"MongoDB evidence counts failed: {evidence}")
    return evidence


def run(
    request: MutationRequest,
    output_root: Path,
    mongo_uri: str | None = None,
    database_name: str = "attempt1_cad",
) -> dict[str, Any]:
    start = time.perf_counter()
    baseline = build_revision(BASELINE_TRAY_WIDTH_MM, parent_revision_id=None)
    changed = build_revision(
        BASELINE_TRAY_WIDTH_MM + request.delta_mm,
        parent_revision_id=baseline.revision_id,
    )
    baseline_export = export_revision(baseline, output_root)
    changed_export = export_revision(changed, output_root)
    comparison = compare_revisions(baseline, changed)

    expected_comparison = {
        "boardWidthDeltaMm": 10.0,
        "padWidthDeltaMm": 10.0,
        "screwDeltaXmm": {
            SCREW_IDS[0]: -5.0,
            SCREW_IDS[1]: -5.0,
            SCREW_IDS[2]: 5.0,
            SCREW_IDS[3]: 5.0,
        },
        "alignedScrewCount": 4,
    }
    if comparison != expected_comparison:
        raise RuntimeError(f"propagation comparison failed: {comparison}")

    mongo_evidence = None
    if mongo_uri:
        mongo_evidence = persist_mongo(
            mongo_uri,
            database_name,
            request,
            baseline,
            changed,
            baseline_export,
            changed_export,
        )

    return {
        "requestId": request_id(request),
        "request": request.as_dict(),
        "baseline": baseline_export,
        "changed": changed_export,
        "comparison": comparison,
        "mongo": mongo_evidence,
        "elapsedMs": round((time.perf_counter() - start) * 1000.0, 3),
    }


def _load_request(path: Path) -> MutationRequest:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read request JSON: {exc}") from exc
    return MutationRequest.from_mapping(value)


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--mongo-uri",
        help="Optional local MongoDB URI; omit for geometry-only replay.",
    )
    parser.add_argument("--database", default="attempt1_cad")
    parser.add_argument(
        "--result-json",
        type=Path,
        help="Optional path for the retained replay response.",
    )
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = run(
            request=_load_request(args.request),
            output_root=args.output_root,
            mongo_uri=args.mongo_uri,
            database_name=args.database,
        )
    except (ContractError, RuntimeError) as exc:
        print(json.dumps({"buildStatus": "failed", "error": str(exc)}), file=sys.stderr)
        return 2
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.result_json:
        args.result_json.parent.mkdir(parents=True, exist_ok=True)
        args.result_json.write_text(rendered)
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
