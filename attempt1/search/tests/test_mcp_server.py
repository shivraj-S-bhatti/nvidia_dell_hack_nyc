from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path


SEARCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SEARCH_ROOT))

from mcp import Client  # noqa: E402
from mcp_server import mcp  # noqa: E402


EXPECTED_TOOLS = {
    "get_ontology",
    "search_parts",
    "search_variants",
    "get_dependencies",
    "list_design_runs",
    "get_winner",
    "get_variant_lineage",
}


class MCPProtocolTests(unittest.TestCase):
    def test_protocol_exposes_tools_resources_and_prompt(self) -> None:
        async def check() -> None:
            async with Client(mcp) as client:
                tools = await client.list_tools()
                self.assertEqual({tool.name for tool in tools.tools}, EXPECTED_TOOLS)
                self.assertTrue(all(tool.annotations.read_only_hint for tool in tools.tools))

                resources = await client.list_resources()
                self.assertEqual(len(resources.resources), 4)
                context = await client.read_resource("context://attempt1/battery-tray-search")
                self.assertIn("six physical", context.contents[0].text)

                prompts = await client.list_prompts()
                self.assertEqual([prompt.name for prompt in prompts.prompts], ["battery_tray_search_context"])
                prompt = await client.get_prompt(
                    "battery_tray_search_context",
                    {"user_request": "find the left screws"},
                )
                self.assertIn("find the left screws", prompt.messages[0].content.text)

                rejected = await client.call_tool(
                    "search_variants",
                    {"min_tray_width_mm": 110, "max_tray_width_mm": 100},
                )
                self.assertTrue(rejected.is_error)
                self.assertIn("cannot exceed", rejected.content[0].text)

        asyncio.run(check())

    @unittest.skipUnless(os.environ.get("TEST_MONGO_URI"), "TEST_MONGO_URI is not set")
    def test_protocol_calls_mongo_backed_tools(self) -> None:
        async def check() -> None:
            async with Client(mcp) as client:
                parts = await client.call_tool("search_parts", {"query_text": "batery bord"})
                self.assertFalse(parts.is_error)
                self.assertEqual(parts.structured_content["results"][0]["partId"], "battery-mounting-board")

                variants = await client.call_tool(
                    "search_variants",
                    {"tray_width_mm": 110, "board_thickness_mm": 2, "pad_thickness_mm": 2},
                )
                self.assertFalse(variants.is_error)
                self.assertEqual(variants.structured_content["results"][0]["ordinal"], 18)

        asyncio.run(check())


if __name__ == "__main__":
    unittest.main()
