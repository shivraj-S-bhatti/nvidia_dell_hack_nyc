#!/usr/bin/env python3
"""Deterministic 27-variant battery-tray search worker for Issue #12."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


ASSEMBLY_ID = "s500-battery-tray-v1"
OBJECTIVE = "maximize_clearance_then_minimize_material"
DATABASE_NAME = "attempt1_search"
MODEL_VERSION = "battery-tray-search-v1"

BASELINE_TRAY_WIDTH_MM = 100.0
BASELINE_PAD_WIDTH_MM = 78.551819982
BOARD_DEPTH_MM = 40.3
PAD_DEPTH_MM = 24.0
SCREW_HOLE_RADIUS_MM = 1.3

SLOT_DEFINITIONS: tuple[tuple[str, tuple[float, float, float]], ...] = (
    ("trayWidthMm", (100.0, 105.0, 110.0)),
    ("boardThicknessMm", (2.0, 2.5, 3.0)),
    ("padThicknessMm", (2.0, 2.5, 3.0)),
)
SLOT_NAMES = tuple(name for name, _ in SLOT_DEFINITIONS)
SLOT_CHOICES = {name: choices for name, choices in SLOT_DEFINITIONS}


class ContractError(ValueError):
    """Raised when a request or fixture violates the frozen Search contract."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(value: Any, length: int = 16) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()[:length]


def _is_number(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float))


@dataclass(frozen=True)
class SearchRequest:
    normalized: dict[str, Any]

    @classmethod
    def from_mapping(cls, value: Any) -> "SearchRequest":
        if not isinstance(value, dict):
            raise ContractError("request must be a JSON object")
        required = {"assemblyId", "objective", "slots", "constraints"}
        if set(value) != required:
            raise ContractError(
                "request must contain only assemblyId, objective, slots, and constraints"
            )
        if value["assemblyId"] != ASSEMBLY_ID:
            raise ContractError(f"assemblyId must be {ASSEMBLY_ID!r}")
        if value["objective"] != OBJECTIVE:
            raise ContractError(f"objective must be {OBJECTIVE!r}")
        if value["constraints"] != {}:
            raise ContractError("constraints must be empty for the fixture-only slice")

        slots = value["slots"]
        if not isinstance(slots, dict) or set(slots) != set(SLOT_NAMES):
            raise ContractError(f"slots must be exactly {', '.join(SLOT_NAMES)}")
        normalized_slots: dict[str, list[float]] = {}
        for slot_name, canonical_choices in SLOT_DEFINITIONS:
            supplied = slots[slot_name]
            if not isinstance(supplied, list) or len(supplied) != 3:
                raise ContractError(f"{slot_name} must contain exactly three choices")
            if not all(_is_number(choice) and math.isfinite(float(choice)) for choice in supplied):
                raise ContractError(f"{slot_name} choices must be finite numbers")
            supplied_values = tuple(float(choice) for choice in supplied)
            if len(set(supplied_values)) != 3 or set(supplied_values) != set(canonical_choices):
                raise ContractError(
                    f"{slot_name} choices must be exactly {list(canonical_choices)}"
                )
            normalized_slots[slot_name] = list(canonical_choices)

        return cls(
            normalized={
                "assemblyId": ASSEMBLY_ID,
                "objective": OBJECTIVE,
                "slots": normalized_slots,
                "constraints": {},
            }
        )

    @property
    def run_id(self) -> str:
        return f"search-run-{_digest({'modelVersion': MODEL_VERSION, **self.normalized})}"


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read JSON from {path}: {exc}") from exc


def _parameter_key(parameters: dict[str, float]) -> str:
    return "|".join(format(parameters[name], "g") for name in SLOT_NAMES)


def load_outcome_fixture(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"default", "overrides"}:
        raise ContractError("outcome fixture must contain default and overrides")
    default = value["default"]
    overrides = value["overrides"]
    if not isinstance(default, dict) or not isinstance(overrides, list):
        raise ContractError("invalid outcome fixture structure")

    required_default = {"buildStatus", "evaluationStatus", "buildMs", "evaluationMs"}
    if set(default) != required_default:
        raise ContractError("outcome fixture default fields changed")
    if default["buildStatus"] != "succeeded" or default["evaluationStatus"] != "succeeded":
        raise ContractError("default fixture outcome must succeed")

    by_key: dict[str, dict[str, Any]] = {}
    for override in overrides:
        required_override = {
            "parameters",
            "buildStatus",
            "evaluationStatus",
            "failureStage",
            "failureReason",
            "buildMs",
            "evaluationMs",
        }
        if not isinstance(override, dict) or set(override) != required_override:
            raise ContractError("fixture override fields changed")
        parameters = override["parameters"]
        if not isinstance(parameters, dict) or set(parameters) != set(SLOT_NAMES):
            raise ContractError("fixture override parameters changed")
        normalized_parameters = {name: float(parameters[name]) for name in SLOT_NAMES}
        for name, choice in normalized_parameters.items():
            if choice not in SLOT_CHOICES[name]:
                raise ContractError(f"fixture override has invalid {name}")
        key = _parameter_key(normalized_parameters)
        if key in by_key:
            raise ContractError(f"duplicate fixture override for {key}")
        by_key[key] = {field: override[field] for field in required_override - {"parameters"}}

    return {"default": default, "byKey": by_key}


def material_volume_proxy_mm3(parameters: dict[str, float]) -> float:
    width_delta_mm = parameters["trayWidthMm"] - BASELINE_TRAY_WIDTH_MM
    pad_width_mm = BASELINE_PAD_WIDTH_MM + width_delta_mm
    board_holes_mm3 = (
        4.0
        * math.pi
        * SCREW_HOLE_RADIUS_MM**2
        * parameters["boardThicknessMm"]
    )
    board_mm3 = (
        parameters["trayWidthMm"]
        * BOARD_DEPTH_MM
        * parameters["boardThicknessMm"]
        - board_holes_mm3
    )
    pad_mm3 = pad_width_mm * PAD_DEPTH_MM * parameters["padThicknessMm"]
    return round(board_mm3 + pad_mm3, 6)


def variant_id(run_id: str, ordinal: int, parameters: dict[str, float]) -> str:
    return f"variant-{_digest({'runId': run_id, 'ordinal': ordinal, 'parameters': parameters})}"


def enumerate_variants(
    request: SearchRequest, outcome_fixture: dict[str, Any]
) -> list[dict[str, Any]]:
    combinations = itertools.product(*(SLOT_CHOICES[name] for name in SLOT_NAMES))
    raw_parameters = [
        {name: float(choice) for name, choice in zip(SLOT_NAMES, combination, strict=True)}
        for combination in combinations
    ]
    if len(raw_parameters) != 27:
        raise RuntimeError(f"expected 27 combinations, got {len(raw_parameters)}")

    baseline_id = variant_id(request.run_id, 0, raw_parameters[0])
    variants: list[dict[str, Any]] = []
    for ordinal, parameters in enumerate(raw_parameters):
        fixture = dict(outcome_fixture["default"])
        fixture.update(outcome_fixture["byKey"].get(_parameter_key(parameters), {}))
        build_status = fixture["buildStatus"]
        evaluation_status = fixture["evaluationStatus"]
        validity = build_status == "succeeded" and evaluation_status == "succeeded"

        failure_stage = fixture.get("failureStage")
        failure_reason = fixture.get("failureReason")
        if validity:
            failure_stage = None
            failure_reason = None
            metrics: dict[str, float] | None = {
                "clearanceGainProxyMm": round(
                    parameters["trayWidthMm"] - BASELINE_TRAY_WIDTH_MM, 6
                ),
                "materialVolumeProxyMm3": material_volume_proxy_mm3(parameters),
            }
        else:
            metrics = None
            if not failure_stage or not failure_reason:
                raise ContractError("failed fixture outcomes require stage and reason")

        current_variant_id = variant_id(request.run_id, ordinal, parameters)
        variants.append(
            {
                "_id": current_variant_id,
                "runId": request.run_id,
                "variantId": current_variant_id,
                "parentVariantId": None if ordinal == 0 else baseline_id,
                "ordinal": ordinal,
                "parameters": parameters,
                "partModeRevision": None,
                "artifactPath": None,
                "metrics": metrics,
                "validity": validity,
                "buildStatus": build_status,
                "evaluationStatus": evaluation_status,
                "failureStage": failure_stage,
                "failureReason": failure_reason,
                "timing": {
                    "source": "fixture",
                    "buildMs": fixture["buildMs"],
                    "evaluationMs": fixture["evaluationMs"],
                },
                "evidenceSource": "fixture",
            }
        )

    ids = [variant["variantId"] for variant in variants]
    parameter_keys = [_canonical_json(variant["parameters"]) for variant in variants]
    if len(set(ids)) != 27 or len(set(parameter_keys)) != 27:
        raise RuntimeError("enumeration did not produce 27 unique variants")
    return variants


def choose_winner(variants: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [variant for variant in variants if variant["validity"]]
    if not valid:
        raise RuntimeError("no valid fixture variant")
    return min(
        valid,
        key=lambda variant: (
            -variant["metrics"]["clearanceGainProxyMm"],
            variant["metrics"]["materialVolumeProxyMm3"],
            variant["ordinal"],
        ),
    )


def winner_ancestry_pipeline(run_id: str) -> list[dict[str, Any]]:
    return [
        {"$match": {"runId": run_id, "validity": True}},
        {
            "$sort": {
                "metrics.clearanceGainProxyMm": -1,
                "metrics.materialVolumeProxyMm3": 1,
                "ordinal": 1,
            }
        },
        {"$limit": 1},
        {
            "$graphLookup": {
                "from": "variants",
                "startWith": "$parentVariantId",
                "connectFromField": "parentVariantId",
                "connectToField": "_id",
                "as": "ancestors",
                "depthField": "depth",
                "restrictSearchWithMatch": {"runId": run_id},
            }
        },
        {
            "$project": {
                "_id": 0,
                "winner": {
                    "variantId": "$variantId",
                    "parentVariantId": "$parentVariantId",
                    "ordinal": "$ordinal",
                    "parameters": "$parameters",
                    "metrics": "$metrics",
                },
                "ancestors": {
                    "$map": {
                        "input": "$ancestors",
                        "as": "ancestor",
                        "in": {
                            "variantId": "$$ancestor.variantId",
                            "parentVariantId": "$$ancestor.parentVariantId",
                            "ordinal": "$$ancestor.ordinal",
                            "parameters": "$$ancestor.parameters",
                            "depth": "$$ancestor.depth",
                        },
                    }
                },
            }
        },
    ]


def persist_mongo(
    mongo_uri: str,
    database_name: str,
    request: SearchRequest,
    variants: list[dict[str, Any]],
    elapsed_ms: float,
) -> dict[str, Any]:
    from pymongo import ASCENDING, DESCENDING, MongoClient, ReplaceOne
    from pymongo.errors import PyMongoError

    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    try:
        client.admin.command("ping")
        database = client[database_name]
        database.variants.bulk_write(
            [
                ReplaceOne({"_id": variant["_id"]}, variant, upsert=True)
                for variant in variants
            ],
            ordered=True,
        )
        database.variants.create_index(
            [("runId", ASCENDING), ("ordinal", ASCENDING)], unique=True
        )
        database.variants.create_index(
            [
                ("runId", ASCENDING),
                ("validity", ASCENDING),
                ("metrics.clearanceGainProxyMm", DESCENDING),
                ("metrics.materialVolumeProxyMm3", ASCENDING),
                ("ordinal", ASCENDING),
            ]
        )

        winner = choose_winner(variants)
        run_document = {
            "_id": request.run_id,
            "runId": request.run_id,
            "modelVersion": MODEL_VERSION,
            "normalizedRequest": request.normalized,
            "variantCount": len(variants),
            "validVariantCount": sum(variant["validity"] for variant in variants),
            "failedBuildCount": sum(
                variant["buildStatus"] == "failed" for variant in variants
            ),
            "failedEvaluationCount": sum(
                variant["evaluationStatus"] == "failed" for variant in variants
            ),
            "baselineVariantId": variants[0]["variantId"],
            "winnerVariantId": winner["variantId"],
            "status": "completed",
            "timing": {"enumerationMs": round(elapsed_ms, 3)},
        }
        database.design_runs.replace_one(
            {"_id": request.run_id}, run_document, upsert=True
        )

        query = winner_ancestry_pipeline(request.run_id)
        query_results = list(database.variants.aggregate(query))
        if len(query_results) != 1:
            raise RuntimeError("winner ancestry query did not return exactly one result")
        query_result = query_results[0]
        ancestors = sorted(
            query_result["ancestors"],
            key=lambda ancestor: (-ancestor["depth"], ancestor["ordinal"]),
        )
        lineage_ids = [ancestor["variantId"] for ancestor in ancestors]
        lineage_ids.append(query_result["winner"]["variantId"])

        collections = sorted(database.list_collection_names())
        evidence = {
            "database": database_name,
            "collections": collections,
            "designRunCount": database.design_runs.count_documents(
                {"_id": request.run_id}
            ),
            "variantCount": database.variants.count_documents(
                {"runId": request.run_id}
            ),
            "failedBuildCount": database.variants.count_documents(
                {"runId": request.run_id, "buildStatus": "failed"}
            ),
            "failedEvaluationCount": database.variants.count_documents(
                {"runId": request.run_id, "evaluationStatus": "failed"}
            ),
            "winnerVariantId": query_result["winner"]["variantId"],
            "lineageVariantIds": lineage_ids,
            "winnerQuery": query,
        }
        expected = {
            "collections": ["design_runs", "variants"],
            "designRunCount": 1,
            "variantCount": 27,
            "failedBuildCount": 1,
            "failedEvaluationCount": 1,
        }
        for field, expected_value in expected.items():
            if evidence[field] != expected_value:
                raise RuntimeError(
                    f"MongoDB evidence mismatch for {field}: {evidence[field]!r}"
                )
        if evidence["winnerVariantId"] != winner["variantId"]:
            raise RuntimeError("MongoDB winner does not match deterministic winner")
        if evidence["lineageVariantIds"] != [variants[0]["variantId"], winner["variantId"]]:
            raise RuntimeError("MongoDB ancestry did not reconstruct baseline -> winner")
        return evidence
    except PyMongoError as exc:
        raise RuntimeError(f"MongoDB operation failed: {exc}") from exc
    finally:
        client.close()


def _write_json(path: Path, value: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    return str(path.resolve())


def run(
    request: SearchRequest,
    outcome_fixture: dict[str, Any],
    output_root: Path,
    mongo_uri: str | None = None,
    database_name: str = DATABASE_NAME,
) -> dict[str, Any]:
    start = time.perf_counter()
    variants = enumerate_variants(request, outcome_fixture)
    winner = choose_winner(variants)
    elapsed_before_persist_ms = (time.perf_counter() - start) * 1000.0

    mongo_evidence = None
    if mongo_uri:
        mongo_evidence = persist_mongo(
            mongo_uri,
            database_name,
            request,
            variants,
            elapsed_before_persist_ms,
        )

    failures = [variant for variant in variants if not variant["validity"]]
    output_root = output_root.resolve()
    output_paths = {
        "normalizedRequest": _write_json(
            output_root / "normalized-request.json", request.normalized
        ),
        "variants": _write_json(output_root / "variants.json", variants),
        "winnerAncestryQuery": _write_json(
            output_root / "winner-ancestry-query.json",
            winner_ancestry_pipeline(request.run_id),
        ),
    }
    elapsed_ms = round((time.perf_counter() - start) * 1000.0, 3)
    return {
        "runId": request.run_id,
        "normalizedRequest": request.normalized,
        "variantCount": len(variants),
        "uniqueVariantIdCount": len({variant["variantId"] for variant in variants}),
        "baselineVariantId": variants[0]["variantId"],
        "winner": {
            "variantId": winner["variantId"],
            "parentVariantId": winner["parentVariantId"],
            "ordinal": winner["ordinal"],
            "parameters": winner["parameters"],
            "metrics": winner["metrics"],
        },
        "failureCounts": {
            "build": sum(variant["buildStatus"] == "failed" for variant in failures),
            "evaluation": sum(
                variant["evaluationStatus"] == "failed" for variant in failures
            ),
        },
        "failedVariants": [
            {
                "variantId": variant["variantId"],
                "ordinal": variant["ordinal"],
                "failureStage": variant["failureStage"],
                "failureReason": variant["failureReason"],
            }
            for variant in failures
        ],
        "mongo": mongo_evidence,
        "outputPaths": output_paths,
        "elapsedMs": elapsed_ms,
    }


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--outcomes", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--mongo-uri")
    parser.add_argument("--database", default=DATABASE_NAME)
    parser.add_argument("--result-json", type=Path)
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        request = SearchRequest.from_mapping(load_json(args.request))
        outcome_fixture = load_outcome_fixture(load_json(args.outcomes))
        result = run(
            request=request,
            outcome_fixture=outcome_fixture,
            output_root=args.output_root,
            mongo_uri=args.mongo_uri,
            database_name=args.database,
        )
    except (ContractError, RuntimeError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}), file=sys.stderr)
        return 2

    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.result_json:
        args.result_json.parent.mkdir(parents=True, exist_ok=True)
        args.result_json.write_text(rendered)
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
