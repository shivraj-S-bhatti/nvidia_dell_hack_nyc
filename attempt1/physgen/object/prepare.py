"""Verify and replay the offline NeoRacer object-intake gate from Issue #42.

The module intentionally separates identity extraction from CAD-kernel checks:

* the existing standard-library STEP parser owns stable product/occurrence IDs;
* OpenCascade/XCAF proves that the chosen occurrence resolves to one valid solid;
* tracked manifests pin every source and derived artifact by SHA-256.

No network client is imported. ``--offline`` is mandatory.
"""

from __future__ import annotations

import argparse
import collections
import gc
import hashlib
import importlib.metadata
import json
import math
import os
import re
import resource
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator


SCHEMA_VERSION = "1.0.0"
MODULE_DIR = Path(__file__).resolve().parent
SCHEMA_DIR = MODULE_DIR / "schemas"
DEFAULT_COMPONENT_MANIFEST = MODULE_DIR / "fixtures" / "component-manifest.json"
DEFAULT_TARGET_COMPONENT = MODULE_DIR / "fixtures" / "target-component.json"
CANONICAL_STEP_TIMESTAMP = b"1970-01-01T00:00:00"


class GateError(RuntimeError):
    """A deterministic input, identity, geometry, or hash gate failed."""


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise GateError(f"expected a JSON object: {path}")
    return value


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode("utf-8")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(canonical_json_bytes(value))
    temporary.replace(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def stable_id(kind: str, source_sha256: str, value: str) -> str:
    payload = f"{source_sha256}\0{kind}\0{value}".encode("utf-8")
    return f"{kind}-{hashlib.sha256(payload).hexdigest()[:20]}"


def validate_schema(instance: dict[str, Any], schema_name: str) -> None:
    schema_path = SCHEMA_DIR / schema_name
    schema = load_json(schema_path)
    Draft202012Validator.check_schema(schema)
    errors = sorted(Draft202012Validator(schema).iter_errors(instance), key=lambda item: list(item.path))
    if errors:
        details = []
        for error in errors[:12]:
            location = "/".join(str(item) for item in error.absolute_path) or "<root>"
            details.append(f"{location}: {error.message}")
        raise GateError(f"{schema_name} rejected input:\n  " + "\n  ".join(details))


def safe_relative_path(root: Path, relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise GateError(f"artifact path must be relative and traversal-free: {relative!r}")
    resolved_root = root.resolve()
    resolved = (resolved_root / candidate).resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise GateError(f"artifact path escaped output root: {relative!r}")
    return resolved


def verify_file(path: Path, expected_sha256: str, expected_size: int, role: str) -> None:
    if not path.is_file():
        raise GateError(f"missing {role}: {path}")
    actual_size = path.stat().st_size
    if actual_size != expected_size:
        raise GateError(f"{role} size mismatch: expected {expected_size}, found {actual_size}: {path}")
    actual_sha256 = sha256_file(path)
    if actual_sha256 != expected_sha256:
        raise GateError(
            f"{role} SHA-256 mismatch: expected {expected_sha256}, found {actual_sha256}: {path}"
        )


def verify_source_cache(asset: dict[str, Any], output_root: Path) -> tuple[Path, Path]:
    repository = safe_relative_path(output_root, asset["cache"]["repositoryRelativePath"])
    if not repository.is_dir():
        raise GateError(f"offline source repository is absent: {repository}")

    try:
        revision = subprocess.run(
            ["git", "-C", str(repository), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as error:
        raise GateError(f"cannot resolve cached source revision: {repository}") from error
    if revision != asset["source"]["commitSha"]:
        raise GateError(f"cached source revision mismatch: expected {asset['source']['commitSha']}, found {revision}")

    license_info = asset["source"]["license"]
    license_path = safe_relative_path(repository, license_info["repositoryPath"])
    verify_file(license_path, license_info["sha256"], license_info["sizeBytes"], "license")

    source_step = None
    for artifact in asset["artifacts"]:
        path = safe_relative_path(repository, artifact["repositoryPath"])
        verify_file(path, artifact["sha256"], artifact["sizeBytes"], artifact["role"])
        if artifact["sha256"] != artifact["lfsOidSha256"]:
            raise GateError(f"LFS OID does not match artifact SHA-256 for {artifact['artifactId']}")
        if artifact["role"] == "source-assembly-step":
            if source_step is not None:
                raise GateError("asset manifest selects more than one source assembly STEP")
            source_step = path
    if source_step is None:
        raise GateError("asset manifest has no source-assembly-step artifact")
    return repository, source_step


def _matrix4(transform: tuple[list[list[float]], list[float]]) -> list[list[float]]:
    rotation, translation = transform
    return [
        [float(rotation[row][0]), float(rotation[row][1]), float(rotation[row][2]), float(translation[row])]
        for row in range(3)
    ] + [[0.0, 0.0, 0.0, 1.0]]


def build_component_manifest(source_step: Path, asset: dict[str, Any]) -> dict[str, Any]:
    """Build the byte-stable identity manifest from the pinned STEP text."""

    try:
        from tools.depgraph.parse_step import Step
    except ImportError as error:
        raise GateError("tools.depgraph.parse_step is required from the repository root") from error

    source_sha256 = next(
        artifact["sha256"]
        for artifact in asset["artifacts"]
        if artifact["role"] == "source-assembly-step"
    )
    step = Step(str(source_step))
    if not any(".MILLI.,.METRE." in arguments for _, arguments in step.ents.values()):
        raise GateError("source STEP does not declare millimetre length units")

    parsed_occurrences = sorted(step.occurrences(), key=lambda item: item["occId"])
    occurrence_counts = collections.Counter(item["defName"] for item in parsed_occurrences)
    product_names = sorted(set(step.prod.values()))
    used_names = set(occurrence_counts)
    root_names = sorted(set(product_names) - used_names)
    if root_names != ["OSRBOT110-SSTMINI-V2_ASM"]:
        raise GateError(f"unexpected root product definitions: {root_names}")
    root_name = root_names[0]

    definitions = [
        {
            "componentId": stable_id("component", source_sha256, name),
            "definitionName": name,
            "occurrenceCount": occurrence_counts.get(name, 0),
            "isRootAssembly": name == root_name,
        }
        for name in product_names
    ]
    occurrences = []
    for item in parsed_occurrences:
        occurrence_path = item["occId"]
        parent_path = occurrence_path.rpartition("/")[0] or None
        occurrences.append(
            {
                "occurrenceId": stable_id("occurrence", source_sha256, occurrence_path),
                "componentId": stable_id("component", source_sha256, item["defName"]),
                "definitionName": item["defName"],
                "occurrenceName": item["occName"],
                "occurrencePath": occurrence_path,
                "parentOccurrencePath": parent_path,
                "assemblyTransform": _matrix4(item["T"]),
                "units": "mm",
            }
        )

    result = {
        "schemaVersion": SCHEMA_VERSION,
        "assetId": asset["assetId"],
        "sourceArtifactSha256": source_sha256,
        "assembly": {
            "assemblyId": stable_id("assembly", source_sha256, root_name),
            "definitionName": root_name,
            "displayName": "NeoRacer v0 full vehicle",
            "units": "mm",
        },
        "counts": {"definitions": len(definitions), "occurrences": len(occurrences)},
        "definitions": definitions,
        "occurrences": occurrences,
    }
    validate_schema(result, "component-manifest.schema.json")
    return result


def _label_name(label: Any) -> str:
    from OCP.TDataStd import TDataStd_Name

    attribute = TDataStd_Name()
    if label.FindAttribute(TDataStd_Name.GetID_s(), attribute):
        return attribute.Get().ToExtString()
    return ""


def _bbox(shape: Any, *, rounded: bool = False) -> dict[str, list[float]]:
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box)
    raw = [float(value) for value in box.Get()]
    if rounded:
        raw = [round(value, 6) for value in raw]
    return {"min": raw[:3], "max": raw[3:]}


def _shape_metrics(shape: Any) -> dict[str, Any]:
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer

    explorer = TopExp_Explorer(shape, TopAbs_SOLID)
    solid_count = 0
    while explorer.More():
        solid_count += 1
        explorer.Next()
    properties = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, properties)
    return {
        "solidCount": solid_count,
        "valid": bool(BRepCheck_Analyzer(shape).IsValid()),
        "volumeMm3": float(properties.Mass()),
        "boundingBoxMm": _bbox(shape),
    }


def _find_target(shape_tool: Any, roots: Any, definition_name: str) -> list[dict[str, Any]]:
    from OCP.TDF import TDF_Label, TDF_LabelSequence
    from OCP.XCAFDoc import XCAFDoc_ShapeTool

    found: list[dict[str, Any]] = []

    def walk(parent: Any, path: list[str]) -> None:
        components = TDF_LabelSequence()
        if not XCAFDoc_ShapeTool.GetComponents_s(parent, components, False):
            return
        for index in range(1, components.Length() + 1):
            component = components.Value(index)
            referred = TDF_Label()
            if not XCAFDoc_ShapeTool.GetReferredShape_s(component, referred):
                continue
            occurrence_name = _label_name(component)
            referred_name = _label_name(referred)
            if referred_name == definition_name:
                siblings = []
                for sibling_index in range(1, components.Length() + 1):
                    sibling = components.Value(sibling_index)
                    sibling_ref = TDF_Label()
                    if not XCAFDoc_ShapeTool.GetReferredShape_s(sibling, sibling_ref):
                        continue
                    siblings.append(
                        {
                            "occurrenceName": _label_name(sibling),
                            "definitionName": _label_name(sibling_ref),
                            "boundingBoxMm": _bbox(XCAFDoc_ShapeTool.GetShape_s(sibling), rounded=True),
                        }
                    )
                found.append(
                    {
                        "component": component,
                        "referred": referred,
                        "parent": parent,
                        "path": path + [occurrence_name],
                        "siblings": siblings,
                    }
                )
            walk(referred, path + [occurrence_name or referred_name])

    for root_index in range(1, roots.Length() + 1):
        root = roots.Value(root_index)
        walk(root, [_label_name(root)])
    return found


def _canonicalize_exported_step(path: Path) -> None:
    data = path.read_bytes()
    canonical, substitutions = re.subn(
        rb"(FILE_NAME\('Open CASCADE Shape Model',')[^']+(')",
        rb"\g<1>" + CANONICAL_STEP_TIMESTAMP + rb"\g<2>",
        data,
        count=1,
    )
    if substitutions != 1:
        raise GateError("could not canonicalize the generated STEP header timestamp")
    path.write_bytes(canonical)


def _export_baseline(shape: Any, destination: Path) -> None:
    import cadquery as cq

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    cq.exporters.export(cq.Shape.cast(shape), str(temporary), exportType="STEP")
    _canonicalize_exported_step(temporary)
    temporary.replace(destination)


def _render_context(context_shape: Any, target_shape: Any, destination: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    import cadquery as cq

    context_vertices, context_triangles = cq.Shape.cast(context_shape).tessellate(1.0, 0.25)
    target_vertices, target_triangles = cq.Shape.cast(target_shape).tessellate(0.4, 0.15)
    context_xyz = [vertex.toTuple() for vertex in context_vertices]
    target_xyz = [vertex.toTuple() for vertex in target_vertices]
    context_faces = [[context_xyz[a], context_xyz[b], context_xyz[c]] for a, b, c in context_triangles]
    target_faces = [[target_xyz[a], target_xyz[b], target_xyz[c]] for a, b, c in target_triangles]

    figure = plt.figure(figsize=(12, 7), facecolor="#0d1117")
    axis = figure.add_subplot(111, projection="3d", facecolor="#0d1117")
    axis.add_collection3d(
        Poly3DCollection(
            context_faces,
            facecolor="#7f8b99",
            edgecolor="#27313c",
            linewidth=0.08,
            alpha=0.38,
        )
    )
    axis.add_collection3d(
        Poly3DCollection(
            target_faces,
            facecolor="#f59e0b",
            edgecolor="#fff0c2",
            linewidth=0.12,
            alpha=1.0,
        )
    )
    minima = [min(point[index] for point in context_xyz) for index in range(3)]
    maxima = [max(point[index] for point in context_xyz) for index in range(3)]
    center = [(low + high) / 2.0 for low, high in zip(minima, maxima)]
    radius = max(high - low for low, high in zip(minima, maxima)) / 2.0 * 1.08
    axis.set_xlim(center[0] - radius, center[0] + radius)
    axis.set_ylim(center[1] - radius, center[1] + radius)
    axis.set_zlim(center[2] - radius, center[2] + radius)
    axis.view_init(elev=24, azim=-63)
    axis.set_axis_off()
    axis.set_title(
        "NeoRacer rear assembly context — selected WING-MOUNT-L:1",
        color="white",
        fontsize=15,
        pad=16,
    )
    figure.text(
        0.02,
        0.025,
        "Orange: target solid   Gray: neighboring rear-wing subassembly   Source: NeoRacer @ 05d9c69",
        color="#c9d1d9",
        fontsize=9,
    )
    plt.tight_layout()
    destination.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(
        destination,
        dpi=180,
        facecolor=figure.get_facecolor(),
        bbox_inches="tight",
        metadata={"Software": "Issue 42 deterministic OpenCascade/Matplotlib render"},
    )
    plt.close(figure)


def _assert_close(actual: float, expected: float, description: str, tolerance: float = 1e-6) -> None:
    if not math.isclose(actual, expected, rel_tol=tolerance, abs_tol=tolerance):
        raise GateError(f"{description} changed: expected {expected}, found {actual}")


def _assert_bbox(actual: dict[str, list[float]], expected: dict[str, list[float]], description: str) -> None:
    for bound in ("min", "max"):
        for index, (actual_value, expected_value) in enumerate(zip(actual[bound], expected[bound])):
            _assert_close(actual_value, expected_value, f"{description} {bound}[{index}]")


def _ensure_derived_artifacts(
    output_root: Path,
    target: dict[str, Any],
    definition_shape: Any,
    parent_shape: Any,
    located_target_shape: Any,
) -> None:
    baseline = target["baselineArtifact"]
    baseline_path = safe_relative_path(output_root, baseline["relativePath"])
    if not baseline_path.exists():
        _export_baseline(definition_shape, baseline_path)
    verify_file(baseline_path, baseline["sha256"], baseline["sizeBytes"], "baseline component")

    screenshot = target["assemblyContextScreenshot"]
    screenshot_path = safe_relative_path(output_root, screenshot["relativePath"])
    if not screenshot_path.exists():
        _render_context(parent_shape, located_target_shape, screenshot_path)
    verify_file(screenshot_path, screenshot["sha256"], screenshot["sizeBytes"], "assembly-context screenshot")


def _load_once(
    source_step: Path,
    target: dict[str, Any],
    output_root: Path,
    create_artifacts: bool,
) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        from OCP.STEPCAFControl import STEPCAFControl_Reader
        from OCP.TCollection import TCollection_ExtendedString
        from OCP.TDF import TDF_LabelSequence
        from OCP.TDocStd import TDocStd_Document
        from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ShapeTool
    except ImportError as error:
        raise GateError("CadQuery/OCP is required; install attempt1/physgen/object/requirements.txt") from error

    document = TDocStd_Document(TCollection_ExtendedString("issue42-offline-replay"))
    reader = STEPCAFControl_Reader()
    reader.SetNameMode(True)
    reader.SetColorMode(True)
    status = int(reader.ReadFile(str(source_step)))
    if status != 1:
        raise GateError(f"OpenCascade STEP reader returned status {status}")
    if not reader.Transfer(document):
        raise GateError("OpenCascade could not transfer the STEP into XCAF")

    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    roots = TDF_LabelSequence()
    shape_tool.GetFreeShapes(roots)
    root_names = [_label_name(roots.Value(index)) for index in range(1, roots.Length() + 1)]
    if root_names != ["NEORACER v0"]:
        raise GateError(f"unexpected XCAF roots: {root_names}")

    matches = _find_target(shape_tool, roots, target["definitionName"])
    if len(matches) != 1:
        raise GateError(f"expected one XCAF target match, found {len(matches)}")
    match = matches[0]
    definition_shape = XCAFDoc_ShapeTool.GetShape_s(match["referred"])
    located_target_shape = XCAFDoc_ShapeTool.GetShape_s(match["component"])
    parent_shape = XCAFDoc_ShapeTool.GetShape_s(match["parent"])
    metrics = _shape_metrics(definition_shape)

    expected_geometry = target["geometry"]
    if metrics["solidCount"] != expected_geometry["solidCount"]:
        raise GateError(f"target solid count changed: {metrics['solidCount']}")
    if metrics["valid"] is not expected_geometry["valid"]:
        raise GateError(f"target validity changed: {metrics['valid']}")
    _assert_close(metrics["volumeMm3"], expected_geometry["volumeMm3"], "target volume")
    _assert_bbox(metrics["boundingBoxMm"], expected_geometry["boundingBoxMm"], "target local bounding box")

    sibling_map = {item["occurrenceName"]: item for item in match["siblings"]}
    for keepout in target["neighborKeepOuts"]:
        sibling = sibling_map.get(keepout["occurrenceName"])
        if sibling is None or sibling["definitionName"] != keepout["definitionName"]:
            raise GateError(f"neighbor keep-out identity changed: {keepout['occurrenceName']}")
        _assert_bbox(sibling["boundingBoxMm"], keepout["boundingBoxMm"], keepout["occurrenceName"])

    if create_artifacts:
        _ensure_derived_artifacts(output_root, target, definition_shape, parent_shape, located_target_shape)

    signature_payload = {
        "definitionName": target["definitionName"],
        "solidCount": metrics["solidCount"],
        "valid": metrics["valid"],
        "volumeMm3": round(metrics["volumeMm3"], 9),
        "boundingBoxMm": {
            key: [round(value, 9) for value in values]
            for key, values in metrics["boundingBoxMm"].items()
        },
    }
    observation = {
        "wallTimeSec": round(time.perf_counter() - started, 6),
        "processPeakRssKiB": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "rootNames": root_names,
        "targetDefinitionName": target["definitionName"],
        "targetComponentId": target["componentId"],
        "targetOccurrenceId": target["occurrenceId"],
        "solidCount": metrics["solidCount"],
        "valid": metrics["valid"],
        "selectionSignature": sha256_json(signature_payload),
        "repairApplied": False,
    }
    del reader, shape_tool, document
    gc.collect()
    return observation


def _validate_baseline_load(output_root: Path, target: dict[str, Any]) -> dict[str, Any]:
    import cadquery as cq

    baseline = target["baselineArtifact"]
    path = safe_relative_path(output_root, baseline["relativePath"])
    started = time.perf_counter()
    imported = cq.importers.importStep(str(path))
    solids = imported.solids().vals()
    valid = len(solids) == 1 and all(solid.isValid() for solid in solids)
    if not valid:
        raise GateError(f"isolated baseline is not exactly one valid solid: {path}")
    return {
        "relativePath": baseline["relativePath"],
        "sha256": sha256_file(path),
        "sizeBytes": path.stat().st_size,
        "solidCount": len(solids),
        "valid": valid,
        "wallTimeSec": round(time.perf_counter() - started, 6),
    }


def _actual_toolchain() -> dict[str, Any]:
    versions = {}
    for distribution in ("cadquery", "cadquery-ocp", "jsonschema", "matplotlib", "psutil"):
        try:
            versions[distribution] = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            versions[distribution] = None
    try:
        import OCP

        ocp_module = OCP.__version__
    except ImportError:
        ocp_module = None
    return {
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "cadquery": versions["cadquery"],
        "cadqueryOcp": versions["cadquery-ocp"],
        "openCascade": ".".join(ocp_module.split(".")[:3]) if ocp_module else None,
        "ocpModule": ocp_module,
        "jsonschema": versions["jsonschema"],
        "matplotlib": versions["matplotlib"],
        "psutil": versions["psutil"],
        "freeCADExecutable": shutil.which("FreeCADCmd") or shutil.which("freecadcmd"),
        "modelInventory": [],
    }


def _verify_toolchain(expected: dict[str, Any], actual: dict[str, Any]) -> None:
    if not actual["python"].startswith(expected["python"] + "."):
        raise GateError(f"Python version mismatch: expected {expected['python']}.x, found {actual['python']}")
    for key in ("cadquery", "cadqueryOcp", "openCascade"):
        if actual[key] != expected[key]:
            raise GateError(f"{key} version mismatch: expected {expected[key]}, found {actual[key]}")
    if actual["modelInventory"] != expected["modelInventory"]:
        raise GateError("this object slice must not add a learned model dependency")


def _request_cold_file_cache(path: Path) -> str:
    """Best-effort per-file cache eviction without requiring root privileges."""

    if not hasattr(os, "posix_fadvise") or not hasattr(os, "POSIX_FADV_DONTNEED"):
        return "cold-cache request unavailable on this platform"
    os.sync()
    with path.open("rb") as handle:
        os.posix_fadvise(handle.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)
    return "POSIX_FADV_DONTNEED requested before load; kernel compliance is not asserted"


def replay(asset_manifest_path: Path, output_root: Path, load_repetitions: int) -> dict[str, Any]:
    started = time.perf_counter()
    asset = load_json(asset_manifest_path)
    target_path = asset_manifest_path.parent / "target-component.json"
    component_path = asset_manifest_path.parent / "component-manifest.json"
    target = load_json(target_path)
    expected_component = load_json(component_path)
    validate_schema(asset, "asset-manifest.schema.json")
    validate_schema(target, "target-component.schema.json")
    validate_schema(expected_component, "component-manifest.schema.json")
    if target["assetId"] != asset["assetId"]:
        raise GateError("target assetId does not match the asset manifest")
    source_artifact_hashes = {
        artifact["sha256"] for artifact in asset["artifacts"] if artifact["role"] == "source-assembly-step"
    }
    if source_artifact_hashes != {target["sourceArtifactSha256"]}:
        raise GateError("target sourceArtifactSha256 does not match the selected assembly STEP")
    if load_repetitions < asset["loadContract"]["requiredOfflineLoads"]:
        raise GateError(
            f"load repetitions must be at least {asset['loadContract']['requiredOfflineLoads']}, found {load_repetitions}"
        )

    _, source_step = verify_source_cache(asset, output_root)
    actual_toolchain = _actual_toolchain()
    _verify_toolchain(asset["toolchain"], actual_toolchain)
    generated_component = build_component_manifest(source_step, asset)
    if generated_component != expected_component:
        raise GateError("regenerated component-manifest.json differs from the tracked golden manifest")
    generated_component_path = output_root / "evidence" / "component-manifest.json"
    write_json(generated_component_path, generated_component)

    matching_occurrences = [
        occurrence
        for occurrence in generated_component["occurrences"]
        if occurrence["occurrencePath"] == target["occurrencePath"]
    ]
    if len(matching_occurrences) != 1:
        raise GateError(f"target occurrence path resolved {len(matching_occurrences)} times")
    occurrence = matching_occurrences[0]
    for key in ("componentId", "occurrenceId", "definitionName"):
        if occurrence[key] != target[key]:
            raise GateError(f"target {key} changed: expected {target[key]}, found {occurrence[key]}")
    if occurrence["assemblyTransform"] != target["assemblyTransform"]:
        raise GateError("target assembly transform changed")

    observations = []
    for index in range(load_repetitions):
        cache_state = _request_cold_file_cache(source_step) if index == 0 else "warm/uncontrolled"
        observation = _load_once(source_step, target, output_root, create_artifacts=index == 0)
        observation["run"] = index + 1
        observation["cacheState"] = cache_state
        observations.append(observation)
    signatures = {observation["selectionSignature"] for observation in observations}
    ids = {
        (observation["targetComponentId"], observation["targetOccurrenceId"])
        for observation in observations
    }
    if len(signatures) != 1 or len(ids) != 1:
        raise GateError("target geometry or stable identity changed across offline loads")

    baseline_load = _validate_baseline_load(output_root, target)
    screenshot = target["assemblyContextScreenshot"]
    screenshot_path = safe_relative_path(output_root, screenshot["relativePath"])
    replay_log = {
        "schemaVersion": SCHEMA_VERSION,
        "status": "pass",
        "offline": True,
        "networkAccessUsed": False,
        "source": {
            "repositoryUrl": asset["source"]["repositoryUrl"],
            "commitSha": asset["source"]["commitSha"],
            "artifactSha256": target["sourceArtifactSha256"],
            "artifactSizeBytes": source_step.stat().st_size,
            "license": asset["source"]["license"],
        },
        "manifests": {
            "assetManifestSha256": sha256_json(asset),
            "componentManifestSha256": sha256_json(generated_component),
            "targetComponentSha256": sha256_json(target),
            "componentManifestRelativePath": str(generated_component_path.relative_to(output_root)),
        },
        "inventory": actual_toolchain,
        "counts": generated_component["counts"],
        "target": {
            "selectionStatus": target["selectionStatus"],
            "componentId": target["componentId"],
            "occurrenceId": target["occurrenceId"],
            "definitionName": target["definitionName"],
            "occurrencePath": target["occurrencePath"],
            "baseline": baseline_load,
            "assemblyContextScreenshot": {
                "relativePath": screenshot["relativePath"],
                "sha256": sha256_file(screenshot_path),
                "sizeBytes": screenshot_path.stat().st_size,
            },
        },
        "loadEvidence": {
            "requiredLoads": asset["loadContract"]["requiredOfflineLoads"],
            "successfulLoads": len(observations),
            "stableIdentity": len(ids) == 1,
            "stableGeometry": len(signatures) == 1,
            "observations": observations,
        },
        "fallback": {
            "selected": target["selectionStatus"] == "selected-s500-fallback",
            **target["fallback"],
        },
        "failureEvidence": [],
        "overallWallTimeSec": round(time.perf_counter() - started, 6),
        "processPeakRssKiB": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    }
    write_json(output_root / "evidence" / "replay.json", replay_log)
    return replay_log


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset-manifest", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--offline", action="store_true", help="required: prohibit acquisition during replay")
    parser.add_argument("--load-repetitions", type=int, default=3)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    if not arguments.offline:
        raise GateError("--offline is mandatory; asset acquisition is a separate, explicit development step")
    result = replay(arguments.asset_manifest.resolve(), arguments.output_root.resolve(), arguments.load_repetitions)
    summary = {
        "status": result["status"],
        "definitions": result["counts"]["definitions"],
        "occurrences": result["counts"]["occurrences"],
        "target": result["target"]["definitionName"],
        "offlineLoads": result["loadEvidence"]["successfulLoads"],
        "overallWallTimeSec": result["overallWallTimeSec"],
        "processPeakRssKiB": result["processPeakRssKiB"],
        "replayLog": str((arguments.output_root / "evidence" / "replay.json").resolve()),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
