#!/usr/bin/env python3
"""Build an offline, occurrence-addressable NeoRacer mesh for the autoauto UI."""

from __future__ import annotations

from array import array
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sys
from typing import Any


HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parent
OBJECT_ROOT = REPOSITORY / ".artifacts" / "attempt1-physgen" / "object"
SOURCE_STEP = OBJECT_ROOT / "source" / "neoracer-hardware-files" / "full-vehicle" / "neoracer-full-vehicle.step"
COMPONENT_MANIFEST = OBJECT_ROOT / "evidence" / "component-manifest.json"
OUTPUT_ROOT = HERE / "interactive"
OUTPUT_MANIFEST = HERE / "interactive-vehicle.json"
EXPECTED_SOURCE_SHA256 = "73d18cf9104c93177495f09f1aa4569c887c089ce0c9d0ddf4a97d1f26fc7c73"
LINEAR_DEFLECTION_MM = 2.2
ANGULAR_DEFLECTION_RAD = 0.45


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def label_name(label: Any) -> str:
    from OCP.TDataStd import TDataStd_Name

    attribute = TDataStd_Name()
    if label.FindAttribute(TDataStd_Name.GetID_s(), attribute):
        return attribute.Get().ToExtString()
    return ""


def padded(stream: BytesIO) -> None:
    remainder = stream.tell() % 4
    if remainder:
        stream.write(b"\0" * (4 - remainder))


def little_endian_bytes(values: array) -> bytes:
    if sys.byteorder != "little":
        values.byteswap()
    return values.tobytes()


def ancestor_identity(path: str, occurrences: dict[str, dict[str, Any]]) -> tuple[list[str], list[str]]:
    component_ids: list[str] = []
    occurrence_ids: list[str] = []
    cursor: str | None = path
    while cursor:
        occurrence = occurrences[cursor]
        component_ids.append(occurrence["componentId"])
        occurrence_ids.append(occurrence["occurrenceId"])
        cursor = occurrence["parentOccurrencePath"]
    component_ids.reverse()
    occurrence_ids.reverse()
    return component_ids, occurrence_ids


def main() -> int:
    if sha256_file(SOURCE_STEP) != EXPECTED_SOURCE_SHA256:
        raise RuntimeError("the full-vehicle STEP does not match the Issue #42 source hash")

    import cadquery as cq
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDF import TDF_Label, TDF_LabelSequence
    from OCP.TDocStd import TDocStd_Document
    from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ShapeTool

    component_manifest = json.loads(COMPONENT_MANIFEST.read_text(encoding="utf-8"))
    occurrence_by_path = {item["occurrencePath"]: item for item in component_manifest["occurrences"]}

    document = TDocStd_Document(TCollection_ExtendedString("autoauto-interactive-neoracer"))
    reader = STEPCAFControl_Reader()
    reader.SetNameMode(True)
    reader.SetColorMode(True)
    if int(reader.ReadFile(str(SOURCE_STEP))) != 1 or not reader.Transfer(document):
        raise RuntimeError("OpenCascade could not load the complete NeoRacer STEP")

    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    roots = TDF_LabelSequence()
    shape_tool.GetFreeShapes(roots)
    if roots.Length() != 1:
        raise RuntimeError(f"expected one root assembly, found {roots.Length()}")

    root_shape = XCAFDoc_ShapeTool.GetShape_s(roots.Value(1))
    root_box = Bnd_Box()
    BRepBndLib.Add_s(root_shape, root_box)
    bounds = [float(value) for value in root_box.Get()]
    minimum = bounds[:3]
    maximum = bounds[3:]
    scale = [(maximum[index] - minimum[index]) / 65534.0 for index in range(3)]

    position_stream = BytesIO()
    index_stream = BytesIO()
    parts: list[dict[str, Any]] = []
    matched_paths: set[str] = set()
    triangle_count = 0
    vertex_count = 0

    def add_leaf(component: Any, occurrence: dict[str, Any]) -> None:
        nonlocal triangle_count, vertex_count
        shape = XCAFDoc_ShapeTool.GetShape_s(component)
        vertices, triangles = cq.Shape.cast(shape).tessellate(
            LINEAR_DEFLECTION_MM,
            ANGULAR_DEFLECTION_RAD,
        )
        if not vertices or not triangles:
            return

        xyz = [vertex.toTuple() for vertex in vertices]
        quantized = array("H")
        for point in xyz:
            for axis in range(3):
                value = round((point[axis] - minimum[axis]) / scale[axis])
                quantized.append(max(0, min(65534, value)))

        padded(position_stream)
        position_offset = position_stream.tell()
        position_stream.write(little_endian_bytes(quantized))

        use_uint32 = len(vertices) >= 65536
        indices = array("I" if use_uint32 else "H")
        for triangle in triangles:
            indices.extend(int(index) for index in triangle)
        padded(index_stream)
        index_offset = index_stream.tell()
        index_stream.write(little_endian_bytes(indices))

        component_ids, occurrence_ids = ancestor_identity(occurrence["occurrencePath"], occurrence_by_path)
        local_min = [min(point[axis] for point in xyz) for axis in range(3)]
        local_max = [max(point[axis] for point in xyz) for axis in range(3)]
        centroid = [sum(point[axis] for point in xyz) / len(xyz) for axis in range(3)]
        parts.append(
            {
                "name": occurrence["definitionName"],
                "componentId": occurrence["componentId"],
                "occurrenceId": occurrence["occurrenceId"],
                "occurrencePath": occurrence["occurrencePath"],
                "ancestorComponentIds": component_ids,
                "ancestorOccurrenceIds": occurrence_ids,
                "pOff": position_offset,
                "pCount": len(vertices),
                "iOff": index_offset,
                "iCount": len(indices),
                "i32": use_uint32,
                "min": [round(value, 5) for value in local_min],
                "max": [round(value, 5) for value in local_max],
                "centroid": [round(value, 5) for value in centroid],
            }
        )
        triangle_count += len(triangles)
        vertex_count += len(vertices)

    def walk(parent: Any, path: list[str]) -> None:
        components = TDF_LabelSequence()
        if not XCAFDoc_ShapeTool.GetComponents_s(parent, components, False):
            return
        for index in range(1, components.Length() + 1):
            component = components.Value(index)
            referred = TDF_Label()
            if not XCAFDoc_ShapeTool.GetReferredShape_s(component, referred):
                continue
            occurrence_name = label_name(component) or label_name(referred)
            occurrence_path = "/".join([*path, occurrence_name])
            occurrence = occurrence_by_path.get(occurrence_path)
            if occurrence is not None:
                matched_paths.add(occurrence_path)
                if not XCAFDoc_ShapeTool.IsAssembly_s(referred):
                    add_leaf(component, occurrence)
            if XCAFDoc_ShapeTool.IsAssembly_s(referred):
                walk(referred, [*path, occurrence_name])

    for root_index in range(1, roots.Length() + 1):
        walk(roots.Value(root_index), [])

    expected_paths = set(occurrence_by_path)
    if matched_paths != expected_paths:
        missing = sorted(expected_paths - matched_paths)
        raise RuntimeError(f"XCAF traversal omitted {len(missing)} Issue #42 occurrences: {missing[:3]}")
    if not parts:
        raise RuntimeError("the interactive vehicle tessellation was empty")

    # Keep a complete root-assembly render mesh as the authoritative visible
    # surface. Leaf occurrence meshes remain separately addressable for picking,
    # highlighting, and exploded inspection. This avoids dropping geometry that
    # some hybrid STEP assembly nodes own directly instead of through a leaf.
    display_vertices, display_triangles = cq.Shape.cast(root_shape).tessellate(
        LINEAR_DEFLECTION_MM,
        ANGULAR_DEFLECTION_RAD,
    )
    if not display_vertices or not display_triangles:
        raise RuntimeError("the complete display tessellation was empty")
    display_quantized = array("H")
    for vertex in display_vertices:
        point = vertex.toTuple()
        for axis in range(3):
            value = round((point[axis] - minimum[axis]) / scale[axis])
            display_quantized.append(max(0, min(65534, value)))
    padded(position_stream)
    display_position_offset = position_stream.tell()
    position_stream.write(little_endian_bytes(display_quantized))
    display_use_uint32 = len(display_vertices) >= 65536
    display_indices = array("I" if display_use_uint32 else "H")
    for triangle in display_triangles:
        display_indices.extend(int(index) for index in triangle)
    padded(index_stream)
    display_index_offset = index_stream.tell()
    index_stream.write(little_endian_bytes(display_indices))
    display = {
        "name": component_manifest["assembly"]["displayName"],
        "pOff": display_position_offset,
        "pCount": len(display_vertices),
        "iOff": display_index_offset,
        "iCount": len(display_indices),
        "i32": display_use_uint32,
    }

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    position_path = OUTPUT_ROOT / "mesh_pos.bin"
    index_path = OUTPUT_ROOT / "mesh_idx.bin"
    mesh_path = OUTPUT_ROOT / "mesh.json"
    position_path.write_bytes(position_stream.getvalue())
    index_path.write_bytes(index_stream.getvalue())
    mesh_record = {
        "schemaVersion": "autoauto.interactive-mesh/v1",
        "min": minimum,
        "scale": scale,
        "display": display,
        "parts": parts,
    }
    mesh_path.write_text(json.dumps(mesh_record, separators=(",", ":")) + "\n", encoding="utf-8")

    files = {}
    for key, path in (("mesh", mesh_path), ("positions", position_path), ("indices", index_path)):
        files[key] = {
            "relativePath": str(path.relative_to(HERE)),
            "sha256": sha256_file(path),
            "sizeBytes": path.stat().st_size,
        }

    result = {
        "schemaVersion": "autoauto.interactive-vehicle/v1",
        "sourceStep": {
            "relativePath": str(SOURCE_STEP.relative_to(REPOSITORY)),
            "sha256": EXPECTED_SOURCE_SHA256,
        },
        "componentManifest": {
            "relativePath": str(COMPONENT_MANIFEST.relative_to(REPOSITORY)),
            "sha256": sha256_file(COMPONENT_MANIFEST),
        },
        "counts": {
            "definitions": component_manifest["counts"]["definitions"],
            "occurrences": component_manifest["counts"]["occurrences"],
            "renderableLeafOccurrences": len(parts),
            "vertices": len(display_vertices),
            "triangles": len(display_triangles),
            "selectionVertices": vertex_count,
            "selectionTriangles": triangle_count,
        },
        "tessellation": {
            "linearDeflectionMm": LINEAR_DEFLECTION_MM,
            "angularDeflectionRad": ANGULAR_DEFLECTION_RAD,
        },
        "files": files,
    }
    OUTPUT_MANIFEST.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        f"packed a {len(display_triangles):,}-triangle complete car plus {len(parts)} selectable "
        f"leaf occurrences ({triangle_count:,} selection triangles) across all "
        f"{len(matched_paths)} assembly occurrences",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
