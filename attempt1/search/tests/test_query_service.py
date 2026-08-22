from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path


SEARCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SEARCH_ROOT))

import query_service as service  # noqa: E402


class PureQueryContractTests(unittest.TestCase):
    def test_typo_matches_battery_board(self) -> None:
        score, candidate = service._part_score(  # noqa: SLF001
            "batery bord", ["battery mounting board", "battery pad"]
        )
        self.assertGreater(score, 0.5)
        self.assertEqual(candidate, "battery mounting board")

    def test_left_screw_alias_is_high_confidence(self) -> None:
        score, _ = service._part_score("left screw", ["left front screw"])  # noqa: SLF001
        self.assertEqual(score, 0.95)

    def test_invalid_limit_is_rejected(self) -> None:
        with self.assertRaises(service.QueryContractError):
            service._limit(51)  # noqa: SLF001

    def test_ontology_explicitly_separates_parts_and_variants(self) -> None:
        ontology = service.load_ontology()
        self.assertIn("Part", ontology["entities"])
        self.assertIn("Variant", ontology["entities"])
        self.assertFalse(ontology["queryPolicy"]["rawMongoQueriesAllowed"])
        self.assertFalse(ontology["queryPolicy"]["writesAllowed"])


@unittest.skipUnless(os.environ.get("TEST_MONGO_URI"), "TEST_MONGO_URI is not set")
class MongoQueryIntegrationTests(unittest.TestCase):
    def test_fuzzy_part_search_retrieves_board(self) -> None:
        result = service.search_parts(query="batery bord")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["results"][0]["partId"], "battery-mounting-board")

    def test_alias_retrieves_two_left_screws(self) -> None:
        result = service.search_parts(query="left screw")
        self.assertEqual(
            [item["partId"] for item in result["results"]],
            ["mounting-screw-left-front", "mounting-screw-left-rear"],
        )

    def test_exact_variant_filters_retrieve_configuration(self) -> None:
        result = service.search_variants(
            tray_width_mm=110,
            board_thickness_mm=2,
            pad_thickness_mm=2,
        )
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["results"][0]["ordinal"], 18)

    def test_failure_filters_retrieve_both_fixture_failures(self) -> None:
        result = service.search_variants(validity=False)
        self.assertEqual(result["count"], 2)
        self.assertEqual(
            {item["failureStage"] for item in result["results"]},
            {"build", "evaluation"},
        )

    def test_dependencies_and_lineage_are_retrievable(self) -> None:
        dependencies = service.get_dependencies(parameter="trayWidthMm")
        self.assertEqual(dependencies["count"], 6)
        self.assertIn("away from the centerline", dependencies["movementInterpretation"])
        winner = service.get_winner()
        lineage = service.get_variant_lineage(winner["winner"]["variantId"])
        self.assertEqual(
            lineage["lineageVariantIds"],
            ["variant-17ebc1f113c81f77", "variant-f8e93743a5f01287"],
        )


if __name__ == "__main__":
    unittest.main()
