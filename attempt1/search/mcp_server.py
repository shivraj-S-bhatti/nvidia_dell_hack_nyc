#!/usr/bin/env python3
"""MCP surface that exposes strict read-only Attempt 1 battery-tray retrieval."""

from __future__ import annotations

from typing import Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

import query_service as query


SERVER_INSTRUCTIONS = """\
Use these tools only for the local Attempt 1 S500 battery-tray experiment.
There are six physical parts and 27 fixture parameter configurations; never
describe the 27 variants as 27 parts. Use get_ontology when the request is
ambiguous. Fuzzy matching is available only for part names/aliases. All IDs,
dimensions, statuses, and graph relations are exact typed filters. Results are
read-only. Search metrics/outcomes are fixture proxies, and variants have no
connected CAD artifact or PartMode revision yet.
"""

mcp = MCPServer(
    "attempt1-search",
    title="Attempt 1 Battery Tray Search",
    description="Read-only ontology and MongoDB retrieval for battery-tray parts and fixture variants.",
    instructions=SERVER_INSTRUCTIONS,
    version="1.0.0",
)

READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)


@mcp.tool(
    description="Return the exposed entity schema, relations, units, aliases, limitations, and query policy. Call this before translating an ambiguous natural-language request.",
    annotations=READ_ONLY,
)
async def get_ontology() -> dict[str, Any]:
    return query.load_ontology()


@mcp.tool(
    description="Find the six physical battery-tray part records. `query_text` uses deterministic fuzzy matching over part IDs and documented aliases; `kind` and `revision_id` are exact filters.",
    annotations=READ_ONLY,
)
async def search_parts(
    query_text: str | None = None,
    kind: query.PartKind | None = None,
    revision_id: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    return query.search_parts(query=query_text, kind=kind, revision_id=revision_id, limit=limit)


@mcp.tool(
    description="Find the 27 possible fixture parameter configurations using exact typed dimension/status filters or a tray-width range. These records are variants, not physical parts.",
    annotations=READ_ONLY,
)
async def search_variants(
    run_id: str | None = None,
    tray_width_mm: float | None = None,
    min_tray_width_mm: float | None = None,
    max_tray_width_mm: float | None = None,
    board_thickness_mm: float | None = None,
    pad_thickness_mm: float | None = None,
    validity: bool | None = None,
    build_status: query.BuildStatus | None = None,
    evaluation_status: query.EvaluationStatus | None = None,
    failure_stage: query.FailureStage | None = None,
    sort_by: query.VariantSort = "ordinal",
    sort_direction: query.SortDirection = "ascending",
    limit: int = 27,
) -> dict[str, Any]:
    return query.search_variants(
        run_id=run_id,
        tray_width_mm=tray_width_mm,
        min_tray_width_mm=min_tray_width_mm,
        max_tray_width_mm=max_tray_width_mm,
        board_thickness_mm=board_thickness_mm,
        pad_thickness_mm=pad_thickness_mm,
        validity=validity,
        build_status=build_status,
        evaluation_status=evaluation_status,
        failure_stage=failure_stage,
        sort_by=sort_by,
        sort_direction=sort_direction,
        limit=limit,
    )


@mcp.tool(
    description="Return approved trayWidthMm-to-part dependency edges. Resolve an imprecise part name with search_parts before passing an exact part_id.",
    annotations=READ_ONLY,
)
async def get_dependencies(
    part_id: str | None = None,
    parameter: query.DependencyParameter | None = None,
) -> dict[str, Any]:
    return query.get_dependencies(part_id=part_id, parameter=parameter)


@mcp.tool(
    description="List deterministic design runs so an agent can obtain an exact run_id before querying a winner.",
    annotations=READ_ONLY,
)
async def list_design_runs(limit: int = 10) -> dict[str, Any]:
    return query.list_design_runs(limit=limit)


@mcp.tool(
    description="Return the stored winning fixture configuration for a design run and explain the proxy objective. If exactly one run exists, run_id may be omitted.",
    annotations=READ_ONLY,
)
async def get_winner(run_id: str | None = None) -> dict[str, Any]:
    return query.get_winner(run_id=run_id)


@mcp.tool(
    description="Return deterministic baseline-to-variant ancestry for one exact variant_id.",
    annotations=READ_ONLY,
)
async def get_variant_lineage(variant_id: str) -> dict[str, Any]:
    return query.get_variant_lineage(variant_id=variant_id)


@mcp.resource(
    "ontology://attempt1/battery-tray",
    name="attempt1-battery-tray-ontology",
    description="Machine-readable entity schema, aliases, relations, units, and query policy.",
    mime_type="application/json",
)
async def ontology_resource() -> str:
    import json

    return json.dumps(query.load_ontology(), indent=2, sort_keys=True)


@mcp.resource(
    "context://attempt1/battery-tray-search",
    name="attempt1-battery-tray-context",
    description="Agent-facing semantic and evidence boundaries for the fixture search.",
    mime_type="text/markdown",
)
async def context_resource() -> str:
    return query.load_agent_context()


@mcp.resource(
    "schema://attempt1/search-request",
    name="attempt1-search-request-schema",
    description="Frozen JSON Schema for a deterministic search request.",
    mime_type="application/schema+json",
)
async def search_request_schema_resource() -> str:
    return (query.SEARCH_ROOT / "schemas" / "search-request.schema.json").read_text()


@mcp.resource(
    "schema://attempt1/variant",
    name="attempt1-variant-schema",
    description="Frozen JSON Schema for one fixture-backed search variant.",
    mime_type="application/schema+json",
)
async def variant_schema_resource() -> str:
    return (query.SEARCH_ROOT / "schemas" / "variant.schema.json").read_text()


@mcp.prompt(
    name="battery_tray_search_context",
    description="Ground an agent before translating a natural-language battery-tray retrieval request.",
)
async def battery_tray_search_context(user_request: str) -> str:
    return f"{SERVER_INSTRUCTIONS}\nUser request:\n{user_request}"


if __name__ == "__main__":
    mcp.run()
