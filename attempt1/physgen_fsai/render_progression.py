"""Render the real FS-AI assembly and build an offline progression viewer."""

from __future__ import annotations

import argparse
import hashlib
from html import escape
import json
from pathlib import Path
import time
from typing import Any

import cadquery as cq
import numpy as np
import vtk
from vtk.util.numpy_support import numpy_to_vtk, numpy_to_vtkIdTypeArray


PALETTE = (
    (0.20, 0.48, 0.78),
    (0.32, 0.67, 0.80),
    (0.48, 0.61, 0.71),
    (0.20, 0.31, 0.43),
    (0.72, 0.78, 0.84),
    (0.13, 0.56, 0.53),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def actor_from_tessellation(
    vertices: list[Any],
    triangles: list[tuple[int, int, int]],
    color: tuple[float, float, float],
) -> vtk.vtkActor:
    points_array = np.asarray([vertex.toTuple() for vertex in vertices], dtype=np.float64)
    triangles_array = np.asarray(triangles, dtype=np.int64)
    cells = np.empty((len(triangles_array), 4), dtype=np.int64)
    cells[:, 0] = 3
    cells[:, 1:] = triangles_array
    points = vtk.vtkPoints()
    points.SetData(numpy_to_vtk(points_array, deep=True))
    polygons = vtk.vtkCellArray()
    polygons.SetCells(len(triangles_array), numpy_to_vtkIdTypeArray(cells.ravel(), deep=True))
    polydata = vtk.vtkPolyData()
    polydata.SetPoints(points)
    polydata.SetPolys(polygons)
    normals = vtk.vtkPolyDataNormals()
    normals.SetInputData(polydata)
    normals.SetFeatureAngle(42.0)
    normals.ConsistencyOn()
    normals.AutoOrientNormalsOn()
    normals.SplittingOn()
    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputConnection(normals.GetOutputPort())
    mapper.ScalarVisibilityOff()
    actor = vtk.vtkActor()
    actor.SetMapper(mapper)
    actor.GetProperty().SetColor(color)
    actor.GetProperty().SetInterpolationToPBR()
    actor.GetProperty().SetMetallic(0.12)
    actor.GetProperty().SetRoughness(0.56)
    return actor


def tessellated_actors(
    shape: cq.Shape,
    linear_tolerance_mm: float,
    angular_tolerance_rad: float,
    *,
    monochrome: bool = False,
) -> tuple[list[vtk.vtkActor], dict[str, int]]:
    actors = []
    vertices_total = 0
    triangles_total = 0
    solids = shape.Solids()
    for index, solid in enumerate(solids):
        vertices, triangles = solid.tessellate(linear_tolerance_mm, angular_tolerance_rad)
        if not vertices or not triangles:
            continue
        color = (0.34, 0.62, 0.84) if monochrome else PALETTE[index % len(PALETTE)]
        actors.append(actor_from_tessellation(vertices, triangles, color))
        vertices_total += len(vertices)
        triangles_total += len(triangles)
    return actors, {
        "solid_count": len(solids),
        "rendered_actor_count": len(actors),
        "vertex_count": vertices_total,
        "triangle_count": triangles_total,
    }


def highlight_actor(center: tuple[float, float, float], size: tuple[float, float, float]) -> vtk.vtkActor:
    cube = vtk.vtkCubeSource()
    cube.SetCenter(*center)
    cube.SetXLength(size[0])
    cube.SetYLength(size[1])
    cube.SetZLength(size[2])
    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputConnection(cube.GetOutputPort())
    actor = vtk.vtkActor()
    actor.SetMapper(mapper)
    actor.GetProperty().SetColor(1.0, 0.20, 0.10)
    actor.GetProperty().SetRepresentationToWireframe()
    actor.GetProperty().SetLineWidth(5.0)
    return actor


def render(
    actors: list[vtk.vtkActor],
    path: Path,
    *,
    center: tuple[float, float, float],
    span: float,
    camera_vector: tuple[float, float, float],
    view_up: tuple[float, float, float],
    parallel_scale: float,
    extra_actor: vtk.vtkActor | None = None,
) -> None:
    renderer = vtk.vtkRenderer()
    renderer.SetBackground(0.018, 0.035, 0.060)
    renderer.SetBackground2(0.075, 0.135, 0.205)
    renderer.GradientBackgroundOn()
    for actor in actors:
        renderer.AddActor(actor)
    if extra_actor is not None:
        renderer.AddActor(extra_actor)
    camera = vtk.vtkCamera()
    camera.SetFocalPoint(*center)
    camera.SetPosition(*(center[index] + camera_vector[index] * span for index in range(3)))
    camera.SetViewUp(*view_up)
    camera.ParallelProjectionOn()
    camera.SetParallelScale(parallel_scale)
    renderer.SetActiveCamera(camera)
    renderer.ResetCameraClippingRange()
    window = vtk.vtkRenderWindow()
    window.SetOffScreenRendering(1)
    window.SetSize(1400, 900)
    window.SetMultiSamples(8)
    window.AddRenderer(renderer)
    window.Render()
    capture = vtk.vtkWindowToImageFilter()
    capture.SetInput(window)
    capture.SetInputBufferTypeToRGB()
    capture.ReadFrontBufferOff()
    capture.Update()
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = vtk.vtkPNGWriter()
    writer.SetFileName(str(path))
    writer.SetInputConnection(capture.GetOutputPort())
    writer.Write()
    window.Finalize()


def bounding_box(shape: cq.Shape) -> dict[str, list[float]]:
    box = shape.BoundingBox()
    return {
        "min": [box.xmin, box.ymin, box.zmin],
        "max": [box.xmax, box.ymax, box.zmax],
        "size": [box.xlen, box.ylen, box.zlen],
        "center": [(box.xmin + box.xmax) / 2, (box.ymin + box.ymax) / 2, (box.zmin + box.zmax) / 2],
    }


def write_progression_html(output_root: Path, simulation_root: Path, metrics: dict[str, Any]) -> None:
    candidate_by_id = {candidate["id"]: candidate for candidate in metrics["candidates"]}
    braced = candidate_by_id["candidate-braced"]
    disconnected = candidate_by_id["candidate-disconnected"]
    relative_simulation = Path("..") / simulation_root.name
    steps = [
        ("01", "Full racecar context", "Actual 115-solid FS-AI 2026 STEP assembly.", "images/vehicle-isometric.png", "context"),
        ("02", "Target located in assembly", "The red box marks the Example Plate at its real vehicle transform.", "images/vehicle-plate-highlight.png", "selection"),
        ("03", "Isolated source part", "Actual selected Example Plate STEP, before topology exploration.", "images/example-plate-isometric.png", "source part"),
        ("04", "Connected proposal", f"Actual saved 35% density field; compliance {braced['evaluation']['compliance_n_mm']:.3f} N·mm in the comparison fixture.", (relative_simulation / braced["preview"]).as_posix(), "simulation candidate"),
        ("05", "Rejected counterfactual", "Actual saved field with a full-height break; rejected by deterministic connectivity.", (relative_simulation / disconnected["preview"]).as_posix(), "failed candidate"),
    ]
    cards = "".join(
        f"""<article class="step"><div class="number">{number}</div><div class="copy"><div class="kind">{escape(kind)}</div><h2>{escape(title)}</h2><p>{escape(description)}</p></div><img src="{escape(image)}" alt="{escape(title)}"></article>"""
        for number, title, description, image, kind in steps
    )
    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>FS-AI vehicle progression</title>
<style>
:root{{color-scheme:dark;font-family:Inter,ui-sans-serif,system-ui,sans-serif;background:#06101d;color:#edf5ff}}*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 20% 0,#173555,#06101d 52rem)}}main{{max-width:1280px;margin:auto;padding:44px 28px 80px}}.kicker,.kind{{text-transform:uppercase;letter-spacing:.16em;font-size:11px;font-weight:850;color:#67e8f9}}h1{{font-size:clamp(40px,7vw,86px);letter-spacing:-.06em;line-height:.92;margin:10px 0 20px}}header p{{color:#aec1d5;max-width:760px;line-height:1.65;font-size:17px}}.timeline{{display:grid;gap:18px;margin-top:38px}}.step{{display:grid;grid-template-columns:70px 310px minmax(0,1fr);align-items:center;gap:22px;background:#0b1929;border:1px solid #294158;border-radius:22px;padding:18px;box-shadow:0 20px 55px #0005}}.number{{font-size:42px;color:#4d6985;font-weight:900;letter-spacing:-.06em}}.copy h2{{font-size:24px;margin:7px 0}}.copy p{{color:#9fb2c7;line-height:1.5}}.step img{{width:100%;height:310px;object-fit:contain;background:#f7fafc;border-radius:14px}}.step:nth-child(-n+3) img{{background:#071423}}.notice{{margin:26px 0;padding:18px 20px;border-left:4px solid #f59e0b;background:#2c210f;color:#fde6ae;border-radius:8px}}a{{color:#7dd3fc}}@media(max-width:850px){{.step{{grid-template-columns:55px 1fr}}.step img{{grid-column:1/-1;height:auto}}}}
</style></head><body><main><header><div class="kicker">Actual local CAD and solver artifacts</div><h1>Racecar → part → candidates</h1><p>This is the official 2026 Formula Student AI autonomous racecar assembly. The progression now begins with the full vehicle and keeps the selected part visibly grounded in that context.</p><div class="notice">The last two images are 2-D topology fields for one sensor plate, not alternate whole-car bodies. Physics remains an in-plane comparison fixture, not a vehicle safety or performance claim.</div></header><section class="timeline">{cards}</section></main></body></html>"""
    (output_root / "index.html").write_text(html, encoding="utf-8")


def run(
    assembly_step: Path,
    plate_step: Path,
    target_path: Path,
    simulation_root: Path,
    output_root: Path,
) -> dict[str, Any]:
    started = time.perf_counter()
    assembly = cq.importers.importStep(str(assembly_step)).val()
    plate = cq.importers.importStep(str(plate_step)).val()
    if len(assembly.Solids()) != 115 or not assembly.isValid() or len(plate.Solids()) != 1 or not plate.isValid():
        raise RuntimeError("source assembly or selected plate failed the frozen geometry gate")
    target = json.loads(target_path.read_text(encoding="utf-8"))
    simulation = json.loads((simulation_root / "simulation.json").read_text(encoding="utf-8"))
    assembly_box = bounding_box(assembly)
    center = tuple(assembly_box["center"])
    span = max(assembly_box["size"])
    actors, assembly_mesh = tessellated_actors(assembly, 3.0, 0.3)
    plate_actors, plate_mesh = tessellated_actors(plate, 0.5, 0.2, monochrome=True)
    transform = target["assemblyTransform"]
    local_box = target["geometry"]["boundingBoxMm"]
    plate_center = tuple(
        (float(local_box["min"][axis]) + float(local_box["max"][axis])) / 2 + float(transform[axis][3])
        for axis in range(3)
    )
    plate_size = tuple(float(local_box["max"][axis]) - float(local_box["min"][axis]) + (20.0 if axis == 2 else 30.0) for axis in range(3))
    output_root.mkdir(parents=True, exist_ok=True)
    render(actors, output_root / "images" / "vehicle-isometric.png", center=center, span=span, camera_vector=(1.45, -1.85, 1.05), view_up=(0, 0, 1), parallel_scale=span * 0.52)
    render(actors, output_root / "images" / "vehicle-top.png", center=center, span=span, camera_vector=(0, 0, 3.0), view_up=(0, 1, 0), parallel_scale=span * 0.55)
    render(actors, output_root / "images" / "vehicle-side.png", center=center, span=span, camera_vector=(3.0, 0, 0.35), view_up=(0, 0, 1), parallel_scale=span * 0.54)
    render(actors, output_root / "images" / "vehicle-plate-highlight.png", center=center, span=span, camera_vector=(1.45, -1.85, 1.05), view_up=(0, 0, 1), parallel_scale=span * 0.52, extra_actor=highlight_actor(plate_center, plate_size))
    plate_box = bounding_box(plate)
    render(plate_actors, output_root / "images" / "example-plate-isometric.png", center=tuple(plate_box["center"]), span=max(plate_box["size"]), camera_vector=(1.3, -1.5, 1.15), view_up=(0, 0, 1), parallel_scale=max(plate_box["size"]) * 0.62)
    write_progression_html(output_root, simulation_root, simulation)
    images = {
        path.name: {"sha256": sha256_file(path), "size_bytes": path.stat().st_size}
        for path in sorted((output_root / "images").glob("*.png"))
    }
    evidence = {
        "schema_version": "nightshift.fsai-progression-viewer/v1",
        "status": "passed",
        "assembly": {"path": str(assembly_step), "sha256": sha256_file(assembly_step), "bounding_box_mm": assembly_box, **assembly_mesh},
        "selected_part": {"name": target["definitionName"], "occurrence_path": target["occurrencePath"], "assembly_center_mm": list(plate_center), "mesh": plate_mesh},
        "simulation": {"path": str(simulation_root / "simulation.json"), "sha256": sha256_file(simulation_root / "simulation.json"), "status": simulation["status"]},
        "images": images,
        "wall_seconds": time.perf_counter() - started,
        "offline": True,
    }
    (output_root / "evidence.json").write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assembly-step", type=Path, required=True)
    parser.add_argument("--plate-step", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--simulation-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    if not args.offline:
        raise SystemExit("--offline is mandatory")
    result = run(*(path.resolve() for path in (args.assembly_step, args.plate_step, args.target, args.simulation_root, args.output_root)))
    print(json.dumps({"status": result["status"], "output_root": str(args.output_root.resolve()), "wall_seconds": result["wall_seconds"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
