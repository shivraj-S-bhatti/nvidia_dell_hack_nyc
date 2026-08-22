#!/usr/bin/env python3
"""Build the autoauto Issue #42-47 evidence replay from saved local artifacts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import sys
from typing import Any


HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parent
ARTIFACTS = REPOSITORY / ".artifacts" / "attempt1-physgen"
SOURCE_TEMPLATE = REPOSITORY / "frontend" / "index.template.html"
RUN_ID = "run.neoracer-wing-mount-l-seed-7"
PROBLEM_ID = "design-problem.neoracer-wing-mount-l"
BASELINE_ID = "candidate.neoracer-wing-mount-l-source-baseline"


class IntegrationError(RuntimeError):
    """A saved stage output does not satisfy the UI integration boundary."""


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise IntegrationError(f"missing required artifact: {path.relative_to(REPOSITORY)}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise IntegrationError(f"invalid JSON in {path.relative_to(REPOSITORY)}: {error}") from error
    if not isinstance(value, dict):
        raise IntegrationError(f"artifact root must be an object: {path.relative_to(REPOSITORY)}")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise IntegrationError(message)


def contract_source_root() -> Path:
    candidates = (
        REPOSITORY,
        REPOSITORY / ".artifacts" / "worktrees" / "issue47",
        REPOSITORY / ".artifacts" / "worktrees" / "issue43",
    )
    for candidate in candidates:
        if (candidate / "attempt1" / "physgen" / "contracts" / "loader.py").is_file():
            return candidate
    raise IntegrationError("Issue #43 frozen contract loaders are unavailable")


def validate_contracts(paths: list[Path]) -> tuple[int, int]:
    source_root = contract_source_root()
    sys.path.insert(0, str(source_root))
    try:
        from attempt1.physgen.contracts import load_contract, schema_inventory

        for path in paths:
            load_contract(path)
        return len(paths), len(schema_inventory())
    except Exception as error:
        raise IntegrationError(f"Issue #43 contract validation failed: {error}") from error
    finally:
        sys.path.pop(0)


def copy_verified_asset(base: Path, artifact: dict[str, Any], output_name: str) -> dict[str, Any]:
    relative = artifact.get("relative_path") or artifact.get("relativePath")
    expected = artifact.get("sha256")
    require(isinstance(relative, str) and isinstance(expected, str), f"invalid asset descriptor: {output_name}")
    source = (base / relative).resolve()
    require(source.is_relative_to(base.resolve()), f"asset escaped its stage root: {relative}")
    require(source.is_file(), f"missing asset: {source.relative_to(REPOSITORY)}")
    actual = sha256_file(source)
    require(actual == expected, f"asset hash mismatch for {relative}: expected {expected}, got {actual}")
    destination = HERE / "assets" / output_name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return {
        "url": f"assets/{output_name}",
        "sha256": actual,
        "source": str(source.relative_to(REPOSITORY)),
        "sizeBytes": source.stat().st_size,
    }


def load_full_vehicle_asset(component_manifest: dict[str, Any]) -> dict[str, Any]:
    manifest = read_json(HERE / "full-vehicle.json")
    require(manifest.get("schemaVersion") == "autoauto.full-vehicle-render/v1", "invalid full-car render manifest")
    source = manifest["sourceStep"]
    source_path = REPOSITORY / source["relativePath"]
    require(source["sha256"] == sha256_file(source_path), "full-car render source STEP hash changed")
    require(manifest["counts"] == component_manifest["counts"], "full-car render omitted assembly occurrences")
    render = manifest["render"]
    render_path = HERE / render["relativePath"]
    require(render["sha256"] == sha256_file(render_path), "full-car render image hash changed")
    return {
        "url": render["relativePath"],
        "sha256": render["sha256"],
        "source": source["relativePath"],
        "sizeBytes": render["sizeBytes"],
        "triangleCount": manifest["tessellation"]["triangleCount"],
    }


def load_interactive_vehicle_asset(component_manifest: dict[str, Any]) -> dict[str, Any]:
    manifest = read_json(HERE / "interactive-vehicle.json")
    require(
        manifest.get("schemaVersion") == "autoauto.interactive-vehicle/v1",
        "invalid interactive-car manifest",
    )
    source = manifest["sourceStep"]
    source_path = REPOSITORY / source["relativePath"]
    require(source["sha256"] == sha256_file(source_path), "interactive-car source STEP hash changed")
    component_source = manifest["componentManifest"]
    component_path = REPOSITORY / component_source["relativePath"]
    require(
        component_source["sha256"] == sha256_file(component_path),
        "interactive-car component manifest hash changed",
    )
    require(
        manifest["counts"]["definitions"] == component_manifest["counts"]["definitions"]
        and manifest["counts"]["occurrences"] == component_manifest["counts"]["occurrences"],
        "interactive car does not cover the Issue #42 assembly identity",
    )
    files = manifest["files"]
    for descriptor in files.values():
        path = HERE / descriptor["relativePath"]
        require(path.is_file(), f"missing interactive-car asset: {descriptor['relativePath']}")
        require(descriptor["sha256"] == sha256_file(path), f"interactive-car asset hash changed: {path.name}")
    return {
        "meshUrl": f"{files['mesh']['relativePath']}?v={files['mesh']['sha256'][:12]}",
        "positionUrl": f"{files['positions']['relativePath']}?v={files['positions']['sha256'][:12]}",
        "indexUrl": f"{files['indices']['relativePath']}?v={files['indices']['sha256'][:12]}",
        "files": files,
        "counts": manifest["counts"],
        "tessellation": manifest["tessellation"],
    }


def concise_candidate_id(candidate_id: str) -> str:
    if candidate_id == BASELINE_ID:
        return "Source baseline"
    return "OAT " + candidate_id.rsplit("-", 1)[-1]


def assemble_run() -> dict[str, Any]:
    object_root = ARTIFACTS / "object"
    problem_root = ARTIFACTS / "design-problem"
    lab_root = ARTIFACTS / "lab-runtime"
    compile_root = ARTIFACTS / "cad-candidates"
    factory_root = ARTIFACTS / "factory"

    target = read_json(object_root / "target-component.json")
    object_replay = read_json(object_root / "evidence" / "replay.json")
    component_manifest = read_json(object_root / "evidence" / "component-manifest.json")
    problem = read_json(problem_root / "design-problem.json")
    bridge_replay = read_json(problem_root / "evidence" / "replay.json")
    lab_run = read_json(lab_root / "run.json")
    candidate_set = read_json(lab_root / "candidates.json")
    evaluations = read_json(lab_root / "evaluations.json")
    compile_run = read_json(compile_root / "compile-run.json")
    factory_run = read_json(factory_root / "factory-run.json")
    survivors = read_json(factory_root / "survivors.json")

    require(object_replay.get("status") == "pass", "Issue #42 object replay did not pass")
    require(object_replay.get("offline") is True and object_replay.get("networkAccessUsed") is False,
            "Issue #42 replay is not proven offline")
    require(problem.get("id") == PROBLEM_ID and problem.get("run_id") == RUN_ID,
            "Issue #45 DesignProblem identity does not match the run")
    require(problem["target_component"]["component_id"] == target.get("componentId"),
            "Object target and DesignProblem component identity diverged")
    require(
        object_replay["manifests"]["targetComponentSha256"] == sha256_file(object_root / "target-component.json"),
        "Issue #42 target-component manifest hash changed",
    )
    require(
        target["baselineArtifact"]["sha256"]
        == sha256_file(object_root / target["baselineArtifact"]["relativePath"]),
        "Issue #42 baseline component hash changed",
    )
    require(lab_run.get("status") == "passed" and lab_run.get("offline") is True,
            "Issue #44 Lab run did not pass offline")
    require(candidate_set.get("run_id") == RUN_ID and candidate_set.get("design_problem_id") == PROBLEM_ID,
            "Lab candidate handoff lineage is inconsistent")
    require(
        candidate_set["design_problem_sha256"] == sha256_file(problem_root / "design-problem.json"),
        "Lab DesignProblem source hash changed",
    )
    require(compile_run.get("status") == "passed" and compile_run.get("offline") is True,
            "Issue #46 CAD compilation did not pass offline")
    require(compile_run.get("determinism", {}).get("identical_core_artifacts") is True,
            "Issue #46 CAD outputs are not deterministic")
    require(
        compile_run["candidate_set"]["sha256"] == sha256_file(lab_root / "candidates.json"),
        "CAD compiler candidate-set input hash changed",
    )
    require(factory_run.get("status") == "passed" and factory_run.get("offline") is True,
            "Issue #47 Factory run did not pass offline")
    require(factory_run.get("repeatability", {}).get("identical_verdict_measurements") is True,
            "Issue #47 verdict measurements are not repeatable")
    require(
        compile_run["factory_handoff"]["sha256"] == sha256_file(compile_root / "candidates.json"),
        "Factory candidate handoff hash changed",
    )
    require(
        factory_run["track_input"]["sha256"] == sha256_file(factory_root / "survivors.json"),
        "Factory survivor manifest hash changed",
    )

    candidate_contract_paths = [lab_root / item["contract_relative_path"] for item in candidate_set["candidates"]]
    verdict_paths = [factory_root / item["verdict_relative_path"] for item in factory_run["verdicts"]]
    feedback_paths = sorted((factory_root / "feedback").glob("*.json"))
    validated_contracts, schema_count = validate_contracts(
        [problem_root / "design-problem.json", *candidate_contract_paths, *verdict_paths, *feedback_paths]
    )

    evaluation_by_id = {item["candidate_id"]: item for item in evaluations["candidate_results"]}
    compiled_by_id: dict[str, dict[str, Any]] = {}
    for summary in compile_run["compiled_candidates"]:
        metadata = read_json(compile_root / summary["metadata_relative_path"])
        candidate_id = metadata.get("candidate_id") or BASELINE_ID
        require(summary["metadata_sha256"] == sha256_file(compile_root / summary["metadata_relative_path"]),
                f"compiled metadata hash mismatch: {summary['compiled_id']}")
        require(metadata["geometry"]["valid"] is True, f"invalid compiled geometry: {summary['compiled_id']}")
        for descriptor in (
            metadata["geometry"]["component_step"],
            metadata["geometry"]["assembly_step"],
            metadata["geometry"]["viewer"],
            metadata["occupancy"]["artifact"],
        ):
            artifact_path = compile_root / descriptor["relative_path"]
            require(
                descriptor["sha256"] == sha256_file(artifact_path),
                f"compiled artifact hash mismatch: {artifact_path.relative_to(REPOSITORY)}",
            )
        compiled_by_id[candidate_id] = metadata

    verdict_by_id: dict[str, dict[str, Any]] = {}
    for summary, path in zip(factory_run["verdicts"], verdict_paths, strict=True):
        require(summary["verdict_sha256"] == sha256_file(path), f"Factory verdict hash mismatch: {path.name}")
        evidence_path = factory_root / summary["evidence_relative_path"]
        require(
            summary["evidence_sha256"] == sha256_file(evidence_path),
            f"Factory evidence hash mismatch: {evidence_path.name}",
        )
        verdict = read_json(path)
        verdict_by_id[verdict["candidate_id"]] = verdict

    expected_ids = {BASELINE_ID, *(item["candidate_id"] for item in candidate_set["candidates"])}
    require(set(compiled_by_id) == expected_ids, "CAD compiler did not produce the complete candidate family")
    require(set(verdict_by_id) == expected_ids, "Factory did not evaluate the complete compiled family")

    proposal_ids = [item["candidate_id"] for item in candidate_set["candidates"]]
    pass_ids = [candidate_id for candidate_id in proposal_ids if verdict_by_id[candidate_id]["verdict"] == "pass"]
    fail_ids = [candidate_id for candidate_id in proposal_ids if verdict_by_id[candidate_id]["verdict"] == "fail"]
    track_ids = [item["candidate_id"] for item in survivors["track_inputs"]]
    require(verdict_by_id[BASELINE_ID]["verdict"] == "pass", "Factory baseline must pass")
    require(len(pass_ids) == 2 and len(fail_ids) == 1, "Factory must retain two proposal survivors and one real veto")
    require(fail_ids[0] not in track_ids and set(pass_ids).issubset(track_ids),
            "Factory survivor manifest leaked or omitted a proposal")

    full_vehicle_image = load_full_vehicle_asset(component_manifest)
    interactive_vehicle = load_interactive_vehicle_asset(component_manifest)
    context_image = copy_verified_asset(object_root, target["assemblyContextScreenshot"], "object-context.png")
    overlay_image = copy_verified_asset(problem_root, bridge_replay["domain"]["overlay"], "design-domain.png")

    proposals = []
    for index, candidate_summary in enumerate(candidate_set["candidates"]):
        candidate_id = candidate_summary["candidate_id"]
        contract = read_json(lab_root / candidate_summary["contract_relative_path"])
        evaluation = evaluation_by_id[candidate_id]
        compiled = compiled_by_id[candidate_id]
        verdict = verdict_by_id[candidate_id]
        preview_evidence = next(
            item for item in contract["evidence_sources"] if item["evidence_id"].endswith("-preview")
        )
        density_artifact = {
            "relative_path": f"candidates/{candidate_id}.png",
            "sha256": preview_evidence["sha256"],
        }
        density_image = copy_verified_asset(lab_root, density_artifact, f"lab-{index:02d}.png")
        compiled_image = copy_verified_asset(
            compile_root, compiled["geometry"]["viewer"], f"compiled-{index:02d}.png"
        )
        failed_checks = [check for check in verdict["checks"] if check["outcome"] == "fail"]
        proposals.append({
            "id": candidate_id,
            "shortId": f"C{index + 1}",
            "label": concise_candidate_id(candidate_id),
            "role": contract["role"],
            "method": contract["creation_method"]["name"],
            "seed": contract["seed"]["value"],
            "densityImage": density_image,
            "labEvaluation": {
                "materialFraction": evaluation["material_fraction"],
                "complianceNmm": evaluation["compliance_n_mm"],
                "finite": evaluation["finite"],
                "note": "Lab evaluator result; not a Track rank.",
            },
            "compile": {
                "id": compiled["compiled_id"],
                "valid": compiled["geometry"]["valid"],
                "solidCount": compiled["geometry"]["solid_count"],
                "volumeMm3": compiled["geometry"]["volume_mm3"],
                "materialFraction": compiled["occupancy"]["allowed_material_fraction"],
                "trueCells": compiled["occupancy"]["true_cells"],
                "seconds": compiled["measurements"]["compile_seconds"],
                "geometrySha256": compiled["geometry"]["geometry_hash"],
                "image": compiled_image,
            },
            "factory": {
                "verdict": verdict["verdict"],
                "verdictId": verdict["id"],
                "failureCodes": verdict["failure_codes"],
                "checksPassed": sum(check["outcome"] == "pass" for check in verdict["checks"]),
                "checkCount": len(verdict["checks"]),
                "failedChecks": failed_checks,
                "elapsedMs": verdict["elapsed_ms"],
            },
            "trackEligible": candidate_id in track_ids,
        })

    baseline = compiled_by_id[BASELINE_ID]
    baseline_verdict = verdict_by_id[BASELINE_ID]
    baseline_image = copy_verified_asset(compile_root, baseline["geometry"]["viewer"], "compiled-baseline.png")
    feedback = read_json(feedback_paths[0])
    rejected = next(item for item in proposals if item["factory"]["verdict"] == "fail")
    failed_check = rejected["factory"]["failedChecks"][0]

    events = [
        {
            "agent": "AS",
            "name": "Full assembly · #42",
            "text": f"Loaded all {object_replay['counts']['occurrences']} physical occurrences in the NeoRacer root assembly.",
            "image": full_vehicle_image,
            "heading": problem["assembly"]["name"],
            "subtitle": f"{object_replay['counts']['occurrences']} occurrences · every saved part visible",
        },
        {"agent": "OB", "name": "Object · #42", "text": f"Selected {target['definitionName']} with stable occurrence identity.", "image": context_image},
        {"agent": "CT", "name": "Contracts · #43", "text": f"Validated {validated_contracts} live records against {schema_count} frozen entity schemas.", "image": context_image},
        {"agent": "LB", "name": "Lab · #44", "text": f"Generated {len(proposals)} seeded OAT density fields offline.", "image": proposals[0]["densityImage"]},
        {"agent": "BI", "name": "CAD domain · #45", "text": f"Built a {bridge_replay['domain']['grid_shape'][0]} × {bridge_replay['domain']['grid_shape'][1]} grid with 4 protected interfaces.", "image": overlay_image},
        {"agent": "CC", "name": "CAD compiler · #46", "text": "Compiled baseline + 3 proposals into deterministic STEP solids.", "image": proposals[0]["compile"]["image"]},
        {"agent": "FX", "name": "Factory · #47", "text": f"Vetoed {rejected['label']}; two proposals remain Track-eligible.", "image": rejected["compile"]["image"]},
    ]

    return {
        "schemaVersion": "autoauto.issue42-47/v1",
        "meta": {
            "product": "autoauto",
            "runId": RUN_ID,
            "machine": "Dell GB10",
            "network": "offline",
            "scope": "Issues #42-47",
            "truthBoundary": "Component-level comparison fixture; no Track ranking or human selection has been run.",
        },
        "integration": {
            "object": {
                "assembly": problem["assembly"]["name"],
                "definitions": object_replay["counts"]["definitions"],
                "occurrences": object_replay["counts"]["occurrences"],
                "targetName": target["definitionName"],
                "componentId": target["componentId"],
                "occurrenceId": target["occurrenceId"],
                "occurrencePath": target["occurrencePath"],
                "units": target["units"],
                "protectedInterfaceCount": len(problem["protected_interfaces"]),
                "fullVehicleImage": full_vehicle_image,
                "interactiveVehicle": interactive_vehicle,
                "image": context_image,
                "bom": [
                    {
                        "name": definition["definitionName"],
                        "componentId": definition["componentId"],
                        "occurrenceCount": definition["occurrenceCount"],
                        "isRootAssembly": definition["isRootAssembly"],
                    }
                    for definition in component_manifest["definitions"]
                ],
            },
            "problem": {
                "id": PROBLEM_ID,
                "objective": "Minimize compliance at a fixed 35% material target",
                "grid": bridge_replay["domain"]["grid_shape"],
                "cellSizeMm": bridge_replay["domain"]["cell_size_mm"],
                "loadN": sum(abs(load["components"][1]) for load in problem["loads"]),
                "loadNote": "Demo comparison fixture assumption",
                "roundTripErrorCells": bridge_replay["domain"]["round_trip"]["maximum_round_trip_error_cells"],
                "image": overlay_image,
            },
            "contracts": {"recordsValidated": validated_contracts, "entitySchemas": schema_count},
            "lab": {
                "modelPair": lab_run["model_pair"]["name"],
                "candidateCount": len(proposals),
                "coldSeconds": lab_run["measurements"]["cold_seconds"],
                "warmSeconds": lab_run["measurements"]["warm_seconds"],
                "proposals": proposals,
            },
            "compile": {
                "status": compile_run["status"],
                "countIncludingBaseline": len(compiled_by_id),
                "deterministicRepetitions": compile_run["determinism"]["repetitions"],
                "wallSeconds": compile_run["measurements"]["total_wall_seconds"],
                "baseline": {
                    "id": BASELINE_ID,
                    "volumeMm3": baseline["geometry"]["volume_mm3"],
                    "geometrySha256": baseline["geometry"]["geometry_hash"],
                    "image": baseline_image,
                    "factoryVerdict": baseline_verdict["verdict"],
                },
            },
            "factory": {
                "status": factory_run["status"],
                "checkSetId": survivors["check_set_id"],
                "proposalSurvivors": len(pass_ids),
                "rejectedCandidateIds": fail_ids,
                "repeatability": factory_run["repeatability"],
                "wallSeconds": factory_run["measurements"]["total_wall_seconds"],
                "feedback": {
                    "id": feedback["id"],
                    "reasonCode": feedback["reason_code"],
                    "candidateId": feedback["target_candidate_id"],
                    "measured": feedback["measured"],
                    "threshold": feedback["threshold"],
                    "implicatedComponentIds": feedback["implicated_component_ids"],
                },
                "veto": {
                    "candidateId": rejected["id"],
                    "checkId": failed_check["check_id"],
                    "measured": failed_check["measured"],
                    "operator": failed_check["operator"],
                    "threshold": failed_check["threshold"],
                },
            },
            "pendingStages": ["Track", "Revision", "Human Review"],
            "events": events,
        },
    }


def build() -> dict[str, Any]:
    run = assemble_run()
    template = SOURCE_TEMPLATE.read_text(encoding="utf-8")
    require("__RUN_JSON__" in template, "frontend template is missing its run-data placeholder")
    template = template.replace('src="/examples/easyrc/viewer/?embed=1"', 'src="about:blank"')
    template = template.replace(
        "fetch('/examples/easyrc/viewer/parts.json')",
        "Promise.resolve({json:()=>Promise.resolve({parts:[]})})",
    )
    css_version = sha256_file(HERE / "integration.css")[:12]
    viewer_version = sha256_file(HERE / "interactive-viewer.js")[:12]
    integration_version = sha256_file(HERE / "integration.js")[:12]
    template = template.replace(
        "</head>", f'<link rel="stylesheet" href="integration.css?v={css_version}">\n</head>', 1
    )
    template = template.replace(
        "</body>",
        '<script src="/vendor/three-bundle.js"></script>\n'
        f'<script src="interactive-viewer.js?v={viewer_version}"></script>\n'
        f'<script src="integration.js?v={integration_version}"></script>\n</body>',
        1,
    )
    blob = json.dumps(run, ensure_ascii=False, allow_nan=False, separators=(",", ":")).replace("</", "<\\/")
    output = template.replace("__RUN_JSON__", blob)
    (HERE / "run.integrated.json").write_text(
        json.dumps(run, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"
    )
    (HERE / "index.html").write_text(output, encoding="utf-8")
    return run


if __name__ == "__main__":
    assembled = build()
    integration = assembled["integration"]
    print(
        f"built {HERE / 'index.html'} from {integration['lab']['candidateCount']} proposals; "
        f"{integration['factory']['proposalSurvivors']} survivors, "
        f"{len(integration['factory']['rejectedCandidateIds'])} veto"
    )
