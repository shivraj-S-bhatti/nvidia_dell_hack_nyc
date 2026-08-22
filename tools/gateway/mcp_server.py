#!/usr/bin/env python3
"""MCP surface for issue #10: three read-only tools over already-verified CLIs.

Mirrors the registration shape already proven in attempt1/search/mcp_server.py.
Every tool here is read-only: it shells out to (or reads the last stored output
of) tools/depgraph, tools/factory, or tools/track and returns that output
unchanged. No tool here computes a verdict, a measurement, or a ranking.
"""

from __future__ import annotations

from typing import Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

import gateway_tools as gw


SERVER_INSTRUCTIONS = """\
Use these tools to answer questions about one S500 component change: its blast
radius (work_order), whether a proposed candidate is a valid assembly
(factory_verdict), and how a Factory survivor scored against baseline
(track_result). Translate the user's request into exactly one typed call, then
explain the returned evidence in prose. Never state a number, verdict, or rank
that is not present in the tool's returned JSON, and never call these tools to
change anything -- all three are read-only.
"""

mcp = MCPServer(
    "night-shift-gateway",
    title="Night Shift Gateway",
    description="Read-only ripple, Factory-verdict, and Track-result retrieval for the S500 object.",
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
    description=(
        "Blast radius for one part: every dependent definition a change ripples "
        "into, with hop distance and reason. Pass thicker_mm to also return the "
        "fastener length actions a thickness change of that many mm forces."
    ),
    annotations=READ_ONLY,
)
async def work_order(part: str, thicker_mm: float | None = None, hops: int = 3) -> dict[str, Any]:
    return gw.work_order(part, thicker=thicker_mm, hops=hops)


@mcp.tool(
    description=(
        "Factory's pass/fail verdict for one candidate id (or the whole fixture "
        "family if candidate_id is omitted), with the measured reason and "
        "implicated parts. Recomputed deterministically from measured geometry "
        "on every call -- no cached or invented result."
    ),
    annotations=READ_ONLY,
)
async def factory_verdict(candidate_id: str | None = None) -> dict[str, Any]:
    return gw.factory_verdict(candidate_id=candidate_id)


@mcp.tool(
    description=(
        "Track's last stored ranking for one candidate id (or the full report if "
        "candidate_id is omitted): baseline-relative compliance, material "
        "fraction, and specific-stiffness rank. Reads the last "
        ".artifacts/track/track-report.json; does not re-run the FEA solve."
    ),
    annotations=READ_ONLY,
)
async def track_result(candidate_id: str | None = None) -> dict[str, Any]:
    return gw.track_result(candidate_id=candidate_id)


if __name__ == "__main__":
    mcp.run()
