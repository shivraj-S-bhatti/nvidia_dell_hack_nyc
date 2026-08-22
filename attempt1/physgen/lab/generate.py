"""Offline Issue #44 replay command.

The learned model proposes density fields.  OAT's deterministic pyEDGE code
alone computes and reports structural values.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
import time
from typing import Any

from .artifacts import sha256_file, write_density, write_json, write_manifest
from .oat_runtime import generate_density_family
from .physics import evaluate_and_baseline
from .problem import CanonicalProblem


_LARGE_REVISIONS = {
    "OpenTO/NFAE_L": "fa35ac13660f11897fd8bebad3233a66f0f3dc82",
    "OpenTO/LDM_L": "e434497c712983290345d537a0f25304fa0991a3",
}
_STANDARD_REVISIONS = {
    "OpenTO/NFAE": "120c69fd0869e1180f6e552873e37a7acadf1f47",
    "OpenTO/LDM": "59aca1e92d46173fa8d010036cd8374a10e2ec58",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate and evaluate a seeded local OAT topology family")
    parser.add_argument("--problem", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--offline", action="store_true", help="require every source/model path to be local")
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--candidates", type=int)
    parser.add_argument("--sampling-steps", type=int, default=20)
    parser.add_argument("--baseline-iterations", type=int, default=50)
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    parser.add_argument("--oat-root", type=Path)
    parser.add_argument("--ae-model", type=Path)
    parser.add_argument("--ldm-model", type=Path)
    parser.add_argument("--check", action="store_true", help="validate inputs and inventory without running models")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.offline:
        raise SystemExit("Issue #44 requires --offline")
    _force_offline()
    started = time.perf_counter()
    problem = CanonicalProblem.from_path(args.problem)
    if args.seed not in problem.seeds:
        raise SystemExit(f"seed {args.seed} is not allowed by DesignProblem seed_policy {problem.seeds}")
    count = args.candidates if args.candidates is not None else problem.candidate_budget
    if count < 3 or count > problem.candidate_budget:
        raise SystemExit(f"candidate count must be between 3 and frozen budget {problem.candidate_budget}")

    paths = _discover_paths(args)
    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    problem_sha = sha256_file(args.problem)
    contract_validation = _validate_step02_contract(args.problem, problem.raw)
    inventory = _inventory(paths, args.device)
    write_json(output_root / "inventory.json", inventory)
    if args.check:
        write_json(
            output_root / "check.json",
            {
                "status": "ready",
                "problem_sha256": problem_sha,
                "contract_validation": contract_validation,
                "paths": {key: str(value) for key, value in paths.items()},
            },
        )
        print(json.dumps({"status": "ready", "output_root": str(output_root)}, sort_keys=True))
        return 0

    failures: list[dict[str, Any]] = []
    selected_pair: dict[str, Any] | None = None
    densities = measurements = model_info = None
    pairs = _model_pairs(args, paths)
    for pair in pairs:
        try:
            densities, measurements, model_info = generate_density_family(
                problem,
                oat_root=paths["oat_root"],
                ae_model=pair["ae_path"],
                ldm_model=pair["ldm_path"],
                seed=args.seed,
                count=count,
                sampling_steps=args.sampling_steps,
                device=args.device,
            )
            selected_pair = pair
            break
        except Exception as exc:
            failures.append(
                {
                    "pair": pair["name"],
                    "exception_type": type(exc).__name__,
                    "message": str(exc),
                }
            )
    if densities is None or measurements is None or model_info is None or selected_pair is None:
        write_json(output_root / "oat-failures.json", failures)
        raise SystemExit("both cached OAT model pairs failed; failure evidence was retained")

    candidate_dir = output_root / "candidates"
    candidate_ids: list[str] = []
    density_artifacts: list[dict[str, Any]] = []
    for index, density in enumerate(densities):
        candidate_id = f"candidate.opento-s{args.seed}-{index:02d}"
        density_info = write_density(candidate_dir / f"{candidate_id}.npy", density)
        candidate_ids.append(candidate_id)
        density_artifacts.append(density_info)

    evaluations, baseline_density, baseline_evaluation, physics_details = evaluate_and_baseline(
        problem,
        densities,
        oat_root=paths["oat_root"],
        baseline_iterations=args.baseline_iterations,
    )
    baseline_info = write_density(output_root / "baseline" / "simp-baseline.npy", baseline_density)
    candidate_records = [
        _proposal_candidate(
            problem,
            candidate_id=candidate_id,
            index=index,
            seed=args.seed,
            problem_sha=problem_sha,
            model_pair=selected_pair,
            density_info=density_info,
            material_fraction_actual=evaluation.material_fraction,
        )
        for index, (candidate_id, density_info, evaluation) in enumerate(
            zip(candidate_ids, density_artifacts, evaluations, strict=True)
        )
    ]
    candidate_contracts = []
    for record in candidate_records:
        path = candidate_dir / f"{record['id']}.json"
        write_json(path, record)
        candidate_contracts.append(_validate_candidate_contract(path, record))

    baseline_record = _baseline_candidate(
        problem,
        problem_sha=problem_sha,
        density_info=baseline_info,
        material_fraction_actual=baseline_evaluation.material_fraction,
        oat_commit=inventory["oat"]["commit"],
    )
    baseline_record_path = output_root / "baseline" / "simp-baseline.json"
    write_json(baseline_record_path, baseline_record)
    baseline_contract = _validate_candidate_contract(baseline_record_path, baseline_record)
    evaluation_payload = {
        "schema_version": "nightshift.lab-evaluations/v1",
        "design_problem_id": problem.design_problem_id,
        "candidate_results": [
            {"candidate_id": record["id"], **asdict(evaluation)}
            for record, evaluation in zip(candidate_records, evaluations, strict=True)
        ],
        "baseline": {
            "candidate_id": baseline_record["id"],
            "artifact": baseline_info,
            **asdict(baseline_evaluation),
        },
        "physics": physics_details,
    }
    write_json(output_root / "evaluations.json", evaluation_payload)

    success = (
        len(densities) >= 3
        and all(evaluation.finite for evaluation in evaluations)
        and baseline_evaluation.finite
        and physics_details["baseline_deterministic_replay"]
        and measurements.deterministic_replay
    )
    selected_pair_record = {
        key: str(value) if isinstance(value, Path) else value
        for key, value in selected_pair.items()
    }
    run = {
        "schema_version": "nightshift.lab-run/v1",
        "run_id": problem.run_id,
        "design_problem_id": problem.design_problem_id,
        "status": "passed" if success else "failed",
        "success_criteria": {
            "complete_seeded_oat_run": True,
            "at_least_three_finite_bounded_fields": len(densities) >= 3,
            "finite_independent_evaluations": all(evaluation.finite for evaluation in evaluations),
            "replayable_deterministic_baseline": (
                baseline_evaluation.finite and physics_details["baseline_deterministic_replay"]
            ),
            "byte_stable_seeded_replay": measurements.deterministic_replay,
        },
        "contract_validation": contract_validation,
        "candidate_contract_validation": {
            "proposals": candidate_contracts,
            "baseline": baseline_contract,
        },
        "model_pair": selected_pair_record,
        "model_runtime": model_info,
        "measurements": {
            **asdict(measurements),
            "peak_cpu_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            "total_wall_seconds": time.perf_counter() - started,
            "gpu_memory_scope": "allocation visible to this OAT process; shared vLLM residency is excluded",
        },
        "candidate_ids": [record["id"] for record in candidate_records],
        "baseline_candidate_id": baseline_record["id"],
        "failures_before_selected_pair": failures,
        "offline": True,
        "replay": {
            "command": (
                "python -m attempt1.physgen.lab.generate "
                f"--problem {args.problem} --output-root {args.output_root} "
                f"--offline --seed {args.seed}"
            ),
            "python_executable": sys.executable,
            "network_behavior": "local paths only; Hugging Face, Transformers, and Datasets offline flags forced",
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    write_json(output_root / "run.json", run)
    write_manifest(output_root)
    print(json.dumps({"status": run["status"], "output_root": str(output_root)}, sort_keys=True))
    return 0 if success else 1


def _force_offline() -> None:
    for name in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "DATASETS_OFFLINE"):
        os.environ[name] = "1"
    os.environ["HF_DATASETS_DISABLE_PROGRESS_BARS"] = "1"


def _discover_paths(args: argparse.Namespace) -> dict[str, Path]:
    kit_root = Path(os.environ.get("PHYSGEN_KIT_ROOT", Path.home() / "Documents" / "hackathon-hdd"))
    defaults = {
        "oat_root": kit_root / "source" / "checkouts" / "OptimizeAnyTopology",
        "large_ae": kit_root / "models" / "OpenTO--NFAE_L",
        "large_ldm": kit_root / "models" / "OpenTO--LDM_L",
        "standard_ae": kit_root / "models" / "OpenTO--NFAE",
        "standard_ldm": kit_root / "models" / "OpenTO--LDM",
    }
    if args.oat_root is not None:
        defaults["oat_root"] = args.oat_root
    for path in defaults.values():
        if not path.exists():
            raise SystemExit(f"required offline path is missing: {path}")
    return {key: value.resolve() for key, value in defaults.items()}


def _model_pairs(args: argparse.Namespace, paths: dict[str, Path]) -> list[dict[str, Any]]:
    if (args.ae_model is None) != (args.ldm_model is None):
        raise SystemExit("--ae-model and --ldm-model must be supplied together")
    if args.ae_model is not None and args.ldm_model is not None:
        ae_path, ldm_path = args.ae_model.resolve(), args.ldm_model.resolve()
        return [_pair_record("explicit", "local/NFAE", ae_path, "local/LDM", ldm_path, {})]
    return [
        _pair_record("OpenTO large latent", "OpenTO/NFAE_L", paths["large_ae"], "OpenTO/LDM_L", paths["large_ldm"], _LARGE_REVISIONS),
        _pair_record("OpenTO standard", "OpenTO/NFAE", paths["standard_ae"], "OpenTO/LDM", paths["standard_ldm"], _STANDARD_REVISIONS),
    ]


def _pair_record(name: str, ae_id: str, ae_path: Path, ldm_id: str, ldm_path: Path, revisions: dict[str, str]) -> dict[str, Any]:
    ae_weight = ae_path / "model.safetensors"
    ldm_weight = ldm_path / "diffusion_pytorch_model.safetensors"
    return {
        "name": name,
        "ae_id": ae_id,
        "ae_revision": revisions.get(ae_id, "unknown-local"),
        "ae_path": ae_path,
        "ae_sha256": sha256_file(ae_weight),
        "ldm_id": ldm_id,
        "ldm_revision": revisions.get(ldm_id, "unknown-local"),
        "ldm_path": ldm_path,
        "ldm_sha256": sha256_file(ldm_weight),
    }


def _inventory(paths: dict[str, Path], device: str) -> dict[str, Any]:
    packages = {}
    for name in ("torch", "torchvision", "numpy", "scipy", "diffusers", "huggingface-hub", "numba", "cupy-cuda13x", "vtk"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    oat_commit = subprocess.run(
        ["git", "-C", str(paths["oat_root"]), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    result: dict[str, Any] = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "packages": packages,
        "oat": {"path": str(paths["oat_root"]), "commit": oat_commit},
        "models": {
            key: {"path": str(path), "size_bytes": sum(item.stat().st_size for item in path.iterdir() if item.is_file())}
            for key, path in paths.items()
            if key != "oat_root"
        },
        "device_requested": device,
        "fallback_inventory": {
            "scikit_topt": {
                "selected": False,
                "reason": "cached scikit-topt cannot resolve offline without the missing pyamg wheel; OAT pyEDGE SIMP/OC is selected",
            },
            "cholmod": {
                "selected": False,
                "reason": "optional ARM64 scikit-sparse binding is unavailable; scipy SPSOLVE is selected",
            },
        },
    }
    try:
        import torch

        result["torch_runtime"] = {
            "version": torch.__version__,
            "cuda_version": torch.version.cuda,
            "cuda_available": torch.cuda.is_available(),
            "device_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
            "device_total_bytes": torch.cuda.get_device_properties(0).total_memory if torch.cuda.is_available() else None,
        }
    except Exception as exc:
        result["torch_runtime"] = {"error": f"{type(exc).__name__}: {exc}"}
    return result


def _artifact_reference(artifact_id: str, digest: str, media_type: str) -> dict[str, Any]:
    return {
        "artifact_id": artifact_id,
        "uri": f"artifact://sha256/{digest}",
        "sha256": digest,
        "media_type": media_type,
    }


def _density_evidence(candidate_id: str, density_info: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    stem = candidate_id.removeprefix("candidate.")
    array_digest = density_info["array"]["sha256"]
    preview_digest = density_info["preview"]["sha256"]
    density_evidence_id = f"evidence.{stem}-density"
    evidence = [
        {
            "evidence_id": density_evidence_id,
            "kind": "geometry",
            "uri": f"artifact://sha256/{array_digest}",
            "sha256": array_digest,
        },
        {
            "evidence_id": f"evidence.{stem}-preview",
            "kind": "geometry",
            "uri": f"artifact://sha256/{preview_digest}",
            "sha256": preview_digest,
        },
    ]
    geometry = _artifact_reference(f"artifact.{stem}-density", array_digest, "application/x-npy")
    return evidence, geometry


def _interface_claims(problem: CanonicalProblem, evidence_id: str) -> list[dict[str, Any]]:
    return [
        {
            "interface_id": interface_id,
            "status": "unknown",
            "evidence_source_ids": [evidence_id],
        }
        for interface_id in problem.protected_interface_ids
    ]


def _proposal_candidate(
    problem: CanonicalProblem,
    *,
    candidate_id: str,
    index: int,
    seed: int,
    problem_sha: str,
    model_pair: dict[str, Any],
    density_info: dict[str, Any],
    material_fraction_actual: float,
) -> dict[str, Any]:
    evidence, geometry = _density_evidence(candidate_id, density_info)
    return {
        "schema_version": "nightshift.candidate/v1",
        "id": candidate_id,
        "run_id": problem.run_id,
        "parent_ids": [],
        "source_hashes": [
            {"source_id": "source.design-problem", "sha256": problem_sha},
            {"source_id": "source.oat-autoencoder", "sha256": model_pair["ae_sha256"]},
            {"source_id": "source.oat-diffusion", "sha256": model_pair["ldm_sha256"]},
        ],
        "units": problem.raw["units"],
        "creation_method": {
            "kind": "model_proposal",
            "name": f"OptimizeAnyTopology OATPipeline {model_pair['name']}",
            "version": model_pair["ldm_revision"],
            "deterministic": True,
        },
        "evidence_sources": evidence,
        "problem_id": problem.design_problem_id,
        "family_id": f"family.opento-s{seed}",
        "generation": 0,
        "role": "proposal",
        "state": "proposed",
        "geometry": geometry,
        "feedback_event_ids": [],
        "changed_components": [
            {
                "component_id": problem.target_component_id,
                "change_kind": "geometry",
                "summary": f"Seeded OAT DDIM topology proposal {index + 1}",
            }
        ],
        "protected_interface_claims": _interface_claims(problem, evidence[0]["evidence_id"]),
        "material_fraction_target": problem.material_fraction,
        "material_fraction_actual": material_fraction_actual,
        "seed": {"policy": "fixed", "value": seed},
    }


def _baseline_candidate(
    problem: CanonicalProblem,
    *,
    problem_sha: str,
    density_info: dict[str, Any],
    material_fraction_actual: float,
    oat_commit: str,
) -> dict[str, Any]:
    candidate_id = "candidate.opento-simp-baseline"
    evidence, geometry = _density_evidence(candidate_id, density_info)
    return {
        "schema_version": "nightshift.candidate/v1",
        "id": candidate_id,
        "run_id": problem.run_id,
        "parent_ids": [],
        "source_hashes": [{"source_id": "source.design-problem", "sha256": problem_sha}],
        "units": problem.raw["units"],
        "creation_method": {
            "kind": "solver",
            "name": "OptimizeAnyTopology pyEDGE OC",
            "version": oat_commit,
            "deterministic": True,
        },
        "evidence_sources": evidence,
        "problem_id": problem.design_problem_id,
        "family_id": "family.opento-simp-baseline",
        "generation": 0,
        "role": "baseline",
        "state": "proposed",
        "geometry": geometry,
        "feedback_event_ids": [],
        "changed_components": [],
        "protected_interface_claims": _interface_claims(problem, evidence[0]["evidence_id"]),
        "material_fraction_target": problem.material_fraction,
        "material_fraction_actual": material_fraction_actual,
        "seed": {"policy": "none", "value": None},
    }


def _validate_step02_contract(problem_path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    return _validate_shared_contract(problem_path, payload, "nightshift.design-problem/v1")


def _validate_candidate_contract(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    return _validate_shared_contract(path, payload, "nightshift.candidate/v1")


def _validate_shared_contract(path: Path, payload: dict[str, Any], schema_version: str) -> dict[str, Any]:
    try:
        from attempt1.physgen.contracts import load_contract
    except ModuleNotFoundError as exc:
        if not (
            exc.name == "attempt1.physgen.contracts"
            or (isinstance(exc.name, str) and exc.name.startswith("attempt1.physgen.contracts."))
        ):
            raise
    else:
        try:
            contract = load_contract(payload)
        except Exception as exc:
            raise SystemExit(f"STEP 02 contract rejected {path}: {type(exc).__name__}: {exc}") from exc
        if contract.schema_version != schema_version:
            raise SystemExit(
                f"STEP 02 contract returned {contract.schema_version} for {path}; expected {schema_version}"
            )
        return {
            "status": "validated",
            "schema_version": contract.schema_version,
            "contract_id": contract.id,
            "validator": "attempt1.physgen.contracts.load_contract",
        }

    return {
        "status": "pending_step_02",
        "schema_version": schema_version,
        "message": "STEP 02 contract package is not present in this checkout; the strict Issue #44 adapter accepted the record",
    }


if __name__ == "__main__":
    sys.exit(main())
