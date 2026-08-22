#!/usr/bin/env python3
"""Render the complete NeoRacer XCAF root assembly for autoauto's opening view."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parent
OBJECT_ROOT = REPOSITORY / ".artifacts" / "attempt1-physgen" / "object"
SOURCE_STEP = OBJECT_ROOT / "source" / "neoracer-hardware-files" / "full-vehicle" / "neoracer-full-vehicle.step"
COMPONENT_MANIFEST = OBJECT_ROOT / "evidence" / "component-manifest.json"
OUTPUT = HERE / "assets" / "full-vehicle.png"
MANIFEST = HERE / "full-vehicle.json"
EXPECTED_SOURCE_SHA256 = "73d18cf9104c93177495f09f1aa4569c887c089ce0c9d0ddf4a97d1f26fc7c73"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def label_name(label) -> str:
    from OCP.TDataStd import TDataStd_Name

    attribute = TDataStd_Name()
    if label.FindAttribute(TDataStd_Name.GetID_s(), attribute):
        return attribute.Get().ToExtString()
    return ""


def main() -> int:
    if sha256_file(SOURCE_STEP) != EXPECTED_SOURCE_SHA256:
        raise RuntimeError("the full-vehicle STEP does not match the Issue #42 source hash")

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    import cadquery as cq
    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDF import TDF_LabelSequence
    from OCP.TDocStd import TDocStd_Document
    from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ShapeTool

    document = TDocStd_Document(TCollection_ExtendedString("autoauto-full-neoracer"))
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
    root = roots.Value(1)
    root_name = label_name(root)
    root_shape = XCAFDoc_ShapeTool.GetShape_s(root)

    vertices, triangles = cq.Shape.cast(root_shape).tessellate(3.0, 0.4)
    xyz = [vertex.toTuple() for vertex in vertices]
    faces = [[xyz[a], xyz[b], xyz[c]] for a, b, c in triangles]
    if not faces:
        raise RuntimeError("the complete assembly tessellation was empty")

    component_manifest = json.loads(COMPONENT_MANIFEST.read_text(encoding="utf-8"))
    counts = component_manifest["counts"]
    figure = plt.figure(figsize=(14, 8), facecolor="#0d1117")
    axis = figure.add_subplot(111, projection="3d", facecolor="#0d1117")
    collection = Poly3DCollection(
        faces,
        facecolor="#93a4b8",
        edgecolor="#263443",
        linewidth=0.035,
        alpha=0.9,
    )
    collection.set_rasterized(True)
    axis.add_collection3d(collection)

    minima = [min(point[index] for point in xyz) for index in range(3)]
    maxima = [max(point[index] for point in xyz) for index in range(3)]
    center = [(low + high) / 2.0 for low, high in zip(minima, maxima)]
    radius = max(high - low for low, high in zip(minima, maxima)) / 2.0 * 1.04
    axis.set_xlim(center[0] - radius, center[0] + radius)
    axis.set_ylim(center[1] - radius, center[1] + radius)
    axis.set_zlim(center[2] - radius, center[2] + radius)
    axis.view_init(elev=23, azim=-58, roll=90)
    axis.set_axis_off()
    axis.set_title("NeoRacer v0 — complete root assembly", color="white", fontsize=17, pad=18)
    figure.text(
        0.02,
        0.025,
        f"All {counts['occurrences']} occurrences · {counts['definitions']} component definitions · source STEP SHA {EXPECTED_SOURCE_SHA256[:12]}",
        color="#c9d1d9",
        fontsize=10,
    )
    plt.tight_layout()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(
        OUTPUT,
        dpi=180,
        facecolor=figure.get_facecolor(),
        bbox_inches="tight",
        metadata={"Software": "autoauto complete NeoRacer assembly render"},
    )
    plt.close(figure)

    result = {
        "schemaVersion": "autoauto.full-vehicle-render/v1",
        "rootName": root_name,
        "sourceStep": {
            "relativePath": str(SOURCE_STEP.relative_to(REPOSITORY)),
            "sha256": EXPECTED_SOURCE_SHA256,
            "sizeBytes": SOURCE_STEP.stat().st_size,
        },
        "counts": counts,
        "tessellation": {
            "linearDeflectionMm": 3.0,
            "angularDeflectionRad": 0.4,
            "vertexCount": len(xyz),
            "triangleCount": len(faces),
        },
        "render": {
            "relativePath": str(OUTPUT.relative_to(HERE)),
            "sha256": sha256_file(OUTPUT),
            "sizeBytes": OUTPUT.stat().st_size,
        },
    }
    MANIFEST.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        f"rendered {counts['occurrences']} occurrences as {len(faces):,} triangles to {OUTPUT}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
