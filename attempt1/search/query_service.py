#!/usr/bin/env python3
"""Strict read-only MongoDB query service for Attempt 1 battery-tray data."""

from __future__ import annotations

import json
import math
import os
import re
from contextlib import contextmanager
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterator, Literal

from pymongo import MongoClient
from pymongo.errors import PyMongoError


SEARCH_ROOT = Path(__file__).resolve().parent
ONTOLOGY_PATH = SEARCH_ROOT / "ontology.json"
CONTEXT_PATH = SEARCH_ROOT / "AGENT_CONTEXT.md"

DEFAULT_MONGO_URI = "mongodb://127.0.0.1:27017"
DEFAULT_CAD_DATABASE = "attempt1_cad"
DEFAULT_SEARCH_DATABASE = "attempt1_search"
MAX_RESULTS = 50

PART_KINDS = {
    "battery_mounting_board",
    "battery_pad",
    "m2.5x6_mounting_screw",
}
BUILD_STATUSES = {"succeeded", "failed"}
EVALUATION_STATUSES = {"succeeded", "failed", "not_run"}
FAILURE_STAGES = {"build", "evaluation"}
SORT_FIELDS = {
    "ordinal": "ordinal",
    "clearanceGainProxyMm": "metrics.clearanceGainProxyMm",
    "materialVolumeProxyMm3": "metrics.materialVolumeProxyMm3",
}

PartKind = Literal[
    "battery_mounting_board", "battery_pad", "m2.5x6_mounting_screw"
]
BuildStatus = Literal["succeeded", "failed"]
EvaluationStatus = Literal["succeeded", "failed", "not_run"]
FailureStage = Literal["build", "evaluation"]
VariantSort = Literal[
    "ordinal", "clearanceGainProxyMm", "materialVolumeProxyMm3"
]
SortDirection = Literal["ascending", "descending"]
DependencyParameter = Literal["trayWidthMm"]


class QueryContractError(ValueError):
    """Raised before MongoDB sees an invalid or unsupported query."""


def load_ontology() -> dict[str, Any]:
    return json.loads(ONTOLOGY_PATH.read_text())


def load_agent_context() -> str:
    return CONTEXT_PATH.read_text()


def _mongo_uri() -> str:
    return os.environ.get("ATTEMPT1_MONGO_URI", DEFAULT_MONGO_URI)


def _cad_database() -> str:
    return os.environ.get("ATTEMPT1_CAD_DATABASE", DEFAULT_CAD_DATABASE)


def _search_database() -> str:
    return os.environ.get("ATTEMPT1_SEARCH_DATABASE", DEFAULT_SEARCH_DATABASE)


@contextmanager
def _client() -> Iterator[MongoClient]:
    client = MongoClient(_mongo_uri(), serverSelectionTimeoutMS=5000)
    try:
        client.admin.command("ping")
        yield client
    except PyMongoError as exc:
        raise RuntimeError(f"MongoDB read failed: {exc}") from exc
    finally:
        client.close()


def _limit(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_RESULTS:
        raise QueryContractError(f"limit must be an integer from 1 to {MAX_RESULTS}")
    return value


def _optional_number(name: str, value: float | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise QueryContractError(f"{name} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise QueryContractError(f"{name} must be finite")
    return result


def _validated_id(name: str, value: str | None, pattern: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or re.fullmatch(pattern, value) is None:
        raise QueryContractError(f"invalid {name}")
    return value


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(re.findall(r"[a-z0-9]+", value.lower()))


def _normalized(value: str) -> str:
    return " ".join(_tokens(value))


def _part_score(query: str, candidates: list[str]) -> tuple[float, str]:
    normalized_query = _normalized(query)
    query_tokens = set(_tokens(query))
    best_score = 0.0
    best_candidate = ""
    for candidate in candidates:
        normalized_candidate = _normalized(candidate)
        candidate_tokens = set(_tokens(candidate))
        if normalized_query == normalized_candidate:
            score = 1.0
        elif query_tokens and query_tokens.issubset(candidate_tokens):
            score = 0.95
        else:
            union = query_tokens | candidate_tokens
            jaccard = len(query_tokens & candidate_tokens) / len(union) if union else 0.0
            sequence = SequenceMatcher(None, normalized_query, normalized_candidate).ratio()
            token_similarity = (
                sum(
                    max(
                        SequenceMatcher(None, query_token, candidate_token).ratio()
                        for candidate_token in candidate_tokens
                    )
                    for query_token in query_tokens
                )
                / len(query_tokens)
                if query_tokens and candidate_tokens
                else 0.0
            )
            score = max(jaccard, sequence * 0.75, token_similarity * 0.9)
        if score > best_score:
            best_score = score
            best_candidate = candidate
    return round(best_score, 6), best_candidate


def _without_mongo_id(document: dict[str, Any]) -> dict[str, Any]:
    result = dict(document)
    result.pop("_id", None)
    return result


def search_parts(
    query: str | None = None,
    kind: PartKind | None = None,
    revision_id: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Find physical parts; fuzzy matching applies only to query names/aliases."""

    limit = _limit(limit)
    if query is not None:
        if not isinstance(query, str) or not query.strip() or len(query) > 200:
            raise QueryContractError("query must be 1 to 200 non-blank characters")
        query = query.strip()
    if kind is not None and kind not in PART_KINDS:
        raise QueryContractError("unsupported part kind")
    revision_id = _validated_id("revision_id", revision_id, r"tray-rev-[0-9a-f]{12}")

    mongo_filter: dict[str, Any] = {}
    if kind is not None:
        mongo_filter["kind"] = kind
    if revision_id is not None:
        mongo_filter[f"revisionValues.{revision_id}"] = {"$exists": True}

    with _client() as client:
        documents = list(
            client[_cad_database()].parts.find(
                mongo_filter,
                {"sourceStepSha256": 0},
            )
        )

    aliases_by_id = load_ontology()["partAliases"]
    matches: list[dict[str, Any]] = []
    for document in documents:
        part_id = document["_id"]
        aliases = aliases_by_id.get(part_id, [])
        candidates = [part_id, part_id.replace("-", " "), document["kind"], *aliases]
        if query is None:
            score, matched_name = 1.0, part_id
        else:
            score, matched_name = _part_score(query, candidates)
        revision_values = document.get("revisionValues", {})
        if revision_id is not None:
            revision_values = {revision_id: revision_values[revision_id]}
        matches.append(
            {
                "partId": part_id,
                "kind": document["kind"],
                "assemblyId": document["assemblyId"],
                "source": document["source"],
                "match": {"score": score, "matchedName": matched_name},
                "aliases": aliases,
                "revisionValues": revision_values,
            }
        )
    if query is not None and matches:
        top_score = max(item["match"]["score"] for item in matches)
        cutoff = max(0.45, top_score * 0.75)
        matches = [item for item in matches if item["match"]["score"] >= cutoff]
    matches.sort(key=lambda item: (-item["match"]["score"], item["partId"]))
    return {
        "recordType": "physical_parts",
        "fuzzyMatchingApplied": query is not None,
        "count": min(len(matches), limit),
        "totalMatched": len(matches),
        "results": matches[:limit],
    }


def search_variants(
    run_id: str | None = None,
    tray_width_mm: float | None = None,
    min_tray_width_mm: float | None = None,
    max_tray_width_mm: float | None = None,
    board_thickness_mm: float | None = None,
    pad_thickness_mm: float | None = None,
    validity: bool | None = None,
    build_status: BuildStatus | None = None,
    evaluation_status: EvaluationStatus | None = None,
    failure_stage: FailureStage | None = None,
    sort_by: VariantSort = "ordinal",
    sort_direction: SortDirection = "ascending",
    limit: int = 27,
) -> dict[str, Any]:
    """Query fixture configurations with exact typed filters and bounded ranges."""

    limit = _limit(limit)
    run_id = _validated_id("run_id", run_id, r"search-run-[0-9a-f]{16}")
    tray_width_mm = _optional_number("tray_width_mm", tray_width_mm)
    min_tray_width_mm = _optional_number("min_tray_width_mm", min_tray_width_mm)
    max_tray_width_mm = _optional_number("max_tray_width_mm", max_tray_width_mm)
    board_thickness_mm = _optional_number("board_thickness_mm", board_thickness_mm)
    pad_thickness_mm = _optional_number("pad_thickness_mm", pad_thickness_mm)
    if min_tray_width_mm is not None and max_tray_width_mm is not None:
        if min_tray_width_mm > max_tray_width_mm:
            raise QueryContractError("min_tray_width_mm cannot exceed max_tray_width_mm")
    if validity is not None and not isinstance(validity, bool):
        raise QueryContractError("validity must be a boolean")
    if build_status is not None and build_status not in BUILD_STATUSES:
        raise QueryContractError("unsupported build_status")
    if evaluation_status is not None and evaluation_status not in EVALUATION_STATUSES:
        raise QueryContractError("unsupported evaluation_status")
    if failure_stage is not None and failure_stage not in FAILURE_STAGES:
        raise QueryContractError("unsupported failure_stage")
    if sort_by not in SORT_FIELDS:
        raise QueryContractError("unsupported sort_by")
    if sort_direction not in {"ascending", "descending"}:
        raise QueryContractError("unsupported sort_direction")

    mongo_filter: dict[str, Any] = {}
    if run_id is not None:
        mongo_filter["runId"] = run_id
    if tray_width_mm is not None:
        mongo_filter["parameters.trayWidthMm"] = tray_width_mm
    else:
        width_range: dict[str, float] = {}
        if min_tray_width_mm is not None:
            width_range["$gte"] = min_tray_width_mm
        if max_tray_width_mm is not None:
            width_range["$lte"] = max_tray_width_mm
        if width_range:
            mongo_filter["parameters.trayWidthMm"] = width_range
    if board_thickness_mm is not None:
        mongo_filter["parameters.boardThicknessMm"] = board_thickness_mm
    if pad_thickness_mm is not None:
        mongo_filter["parameters.padThicknessMm"] = pad_thickness_mm
    if validity is not None:
        mongo_filter["validity"] = validity
    if build_status is not None:
        mongo_filter["buildStatus"] = build_status
    if evaluation_status is not None:
        mongo_filter["evaluationStatus"] = evaluation_status
    if failure_stage is not None:
        mongo_filter["failureStage"] = failure_stage

    sort_direction_value = 1 if sort_direction == "ascending" else -1
    with _client() as client:
        collection = client[_search_database()].variants
        total = collection.count_documents(mongo_filter)
        documents = list(
            collection.find(mongo_filter, {"_id": 0})
            .sort([(SORT_FIELDS[sort_by], sort_direction_value), ("ordinal", 1)])
            .limit(limit)
        )
    return {
        "recordType": "fixture_parameter_configurations",
        "fuzzyMatchingApplied": False,
        "evidenceWarning": "Metrics, outcomes, and timing are deterministic fixtures/proxies; CAD references are not connected.",
        "count": len(documents),
        "totalMatched": total,
        "results": documents,
    }


def get_dependencies(
    part_id: str | None = None,
    parameter: DependencyParameter | None = None,
) -> dict[str, Any]:
    """Return approved parameter-to-part propagation edges."""

    part_id = _validated_id(
        "part_id", part_id, r"(?:battery-(?:mounting-board|pad)|mounting-screw-(?:left|right)-(?:front|rear))"
    )
    if parameter is not None and parameter != "trayWidthMm":
        raise QueryContractError("the only exposed parameter is trayWidthMm")
    mongo_filter: dict[str, Any] = {"type": "parameter_drives", "approved": True}
    if part_id is not None:
        mongo_filter["to"] = part_id
    if parameter is not None:
        mongo_filter["from"] = f"parameter:{parameter}"
    with _client() as client:
        documents = [
            _without_mongo_id(document)
            for document in client[_cad_database()].dependencies.find(mongo_filter).sort("to", 1)
        ]
    return {
        "relationship": "parameter_drives",
        "movementInterpretation": (
            "Increasing trayWidthMm widens the board and pad, moves left screws "
            "toward negative X, and moves right screws toward positive X; both "
            "screw columns move away from the centerline."
        ),
        "count": len(documents),
        "results": documents,
    }


def list_design_runs(limit: int = 10) -> dict[str, Any]:
    """List completed deterministic search runs."""

    limit = _limit(limit)
    with _client() as client:
        collection = client[_search_database()].design_runs
        total = collection.count_documents({})
        documents = list(collection.find({}, {"_id": 0}).sort("runId", 1).limit(limit))
    return {"count": len(documents), "totalMatched": total, "results": documents}


def _resolve_run(client: MongoClient, run_id: str | None) -> dict[str, Any]:
    run_id = _validated_id("run_id", run_id, r"search-run-[0-9a-f]{16}")
    collection = client[_search_database()].design_runs
    if run_id is not None:
        run = collection.find_one({"runId": run_id})
        if run is None:
            raise QueryContractError(f"design run not found: {run_id}")
        return run
    runs = list(collection.find({}).sort("runId", 1).limit(2))
    if not runs:
        raise QueryContractError("no design runs are available")
    if len(runs) > 1:
        raise QueryContractError("multiple design runs exist; provide run_id")
    return runs[0]


def get_winner(run_id: str | None = None) -> dict[str, Any]:
    """Return the stored winner for exactly one deterministic design run."""

    with _client() as client:
        run = _resolve_run(client, run_id)
        winner = client[_search_database()].variants.find_one(
            {"variantId": run["winnerVariantId"]}, {"_id": 0}
        )
    if winner is None:
        raise RuntimeError("stored winnerVariantId does not resolve to a variant")
    return {
        "runId": run["runId"],
        "objective": run["normalizedRequest"]["objective"],
        "evidenceWarning": "Winner ranking uses deterministic fixture proxy metrics.",
        "winner": winner,
    }


def get_variant_lineage(variant_id: str) -> dict[str, Any]:
    """Recover baseline-to-variant ancestry using a bounded MongoDB graph query."""

    variant_id = _validated_id("variant_id", variant_id, r"variant-[0-9a-f]{16}")
    assert variant_id is not None
    pipeline = [
        {"$match": {"variantId": variant_id}},
        {
            "$graphLookup": {
                "from": "variants",
                "startWith": "$parentVariantId",
                "connectFromField": "parentVariantId",
                "connectToField": "_id",
                "as": "ancestors",
                "depthField": "depth",
                "maxDepth": 26,
            }
        },
        {"$project": {"_id": 0, "subject": "$$ROOT", "ancestors": 1}},
    ]
    with _client() as client:
        results = list(client[_search_database()].variants.aggregate(pipeline))
    if not results:
        raise QueryContractError(f"variant not found: {variant_id}")
    result = results[0]
    subject = result["subject"]
    subject.pop("_id", None)
    subject.pop("ancestors", None)
    ancestors = sorted(result["ancestors"], key=lambda item: (-item["depth"], item["ordinal"]))
    lineage = []
    for ancestor in ancestors:
        ancestor.pop("_id", None)
        lineage.append(ancestor)
    lineage.append(subject)
    return {
        "variantId": variant_id,
        "lineageVariantIds": [item["variantId"] for item in lineage],
        "lineage": lineage,
    }
