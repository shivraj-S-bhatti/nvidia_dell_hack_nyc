from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path


SEARCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SEARCH_ROOT))

import search_worker as search  # noqa: E402


REQUEST_PATH = SEARCH_ROOT / "fixtures" / "search-request.json"
OUTCOMES_PATH = SEARCH_ROOT / "fixtures" / "outcomes.json"


def request() -> search.SearchRequest:
    return search.SearchRequest.from_mapping(search.load_json(REQUEST_PATH))


def outcomes() -> dict:
    return search.load_outcome_fixture(search.load_json(OUTCOMES_PATH))


class ContractTests(unittest.TestCase):
    def test_normalization_ignores_object_and_choice_order(self) -> None:
        canonical = request()
        reordered = search.SearchRequest.from_mapping(
            {
                "constraints": {},
                "slots": {
                    "padThicknessMm": [3, 2.5, 2],
                    "boardThicknessMm": [3, 2, 2.5],
                    "trayWidthMm": [110, 100, 105],
                },
                "objective": search.OBJECTIVE,
                "assemblyId": search.ASSEMBLY_ID,
            }
        )
        self.assertEqual(reordered.normalized, canonical.normalized)
        self.assertEqual(reordered.run_id, canonical.run_id)

    def test_unknown_choice_is_rejected(self) -> None:
        value = search.load_json(REQUEST_PATH)
        value["slots"]["trayWidthMm"] = [100, 105, 115]
        with self.assertRaises(search.ContractError):
            search.SearchRequest.from_mapping(value)


class EnumerationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.request = request()
        self.variants = search.enumerate_variants(self.request, outcomes())

    def test_exactly_27_unique_variants_in_stable_order(self) -> None:
        second = search.enumerate_variants(self.request, outcomes())
        self.assertEqual(len(self.variants), 27)
        self.assertEqual(len({variant["variantId"] for variant in self.variants}), 27)
        self.assertEqual(
            [variant["variantId"] for variant in self.variants],
            [variant["variantId"] for variant in second],
        )
        self.assertEqual([variant["ordinal"] for variant in self.variants], list(range(27)))

    def test_baseline_and_parent_lineage(self) -> None:
        baseline = self.variants[0]
        self.assertEqual(
            baseline["parameters"],
            {
                "trayWidthMm": 100.0,
                "boardThicknessMm": 2.0,
                "padThicknessMm": 2.0,
            },
        )
        self.assertIsNone(baseline["parentVariantId"])
        self.assertTrue(
            all(
                variant["parentVariantId"] == baseline["variantId"]
                for variant in self.variants[1:]
            )
        )
        self.assertTrue(
            all(
                variant["partModeRevision"] is None
                and variant["artifactPath"] is None
                for variant in self.variants
            )
        )

    def test_fixture_failures_remain_queryable(self) -> None:
        build_failures = [
            variant for variant in self.variants if variant["buildStatus"] == "failed"
        ]
        evaluation_failures = [
            variant
            for variant in self.variants
            if variant["evaluationStatus"] == "failed"
        ]
        self.assertEqual(len(build_failures), 1)
        self.assertEqual(build_failures[0]["failureReason"], "fixture_build_failure")
        self.assertIsNone(build_failures[0]["metrics"])
        self.assertEqual(len(evaluation_failures), 1)
        self.assertEqual(
            evaluation_failures[0]["failureReason"], "fixture_evaluation_failure"
        )
        self.assertIsNone(evaluation_failures[0]["metrics"])

    def test_winner_obeys_lexicographic_objective(self) -> None:
        winner = search.choose_winner(self.variants)
        self.assertEqual(winner["ordinal"], 18)
        self.assertEqual(
            winner["parameters"],
            {
                "trayWidthMm": 110.0,
                "boardThicknessMm": 2.0,
                "padThicknessMm": 2.0,
            },
        )
        self.assertEqual(winner["parentVariantId"], self.variants[0]["variantId"])


@unittest.skipUnless(os.environ.get("TEST_MONGO_URI"), "TEST_MONGO_URI is not set")
class MongoIntegrationTests(unittest.TestCase):
    def test_two_collections_and_one_query_recover_winner_ancestry(self) -> None:
        current_request = request()
        variants = search.enumerate_variants(current_request, outcomes())
        evidence = search.persist_mongo(
            os.environ["TEST_MONGO_URI"],
            "attempt1_search_test",
            current_request,
            variants,
            elapsed_ms=0.0,
        )
        winner = search.choose_winner(variants)
        self.assertEqual(evidence["collections"], ["design_runs", "variants"])
        self.assertEqual(evidence["variantCount"], 27)
        self.assertEqual(evidence["winnerVariantId"], winner["variantId"])
        self.assertEqual(
            evidence["lineageVariantIds"],
            [variants[0]["variantId"], winner["variantId"]],
        )


if __name__ == "__main__":
    unittest.main()
