from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


FSAI_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FSAI_ROOT))

import fsai_plate_search as search  # noqa: E402


REQUEST_PATH = FSAI_ROOT / "requests" / "canary-27.json"
LONG_REQUEST_PATH = FSAI_ROOT / "requests" / "long-4096.json"


def request() -> search.SearchRequest:
    return search.load_request(REQUEST_PATH)


def variants() -> list[dict]:
    current_request = request()
    parameters = search.parameter_combinations(current_request)
    baseline_id = search.variant_id(current_request.run_id, 0, parameters[0])
    return [
        search.evaluate_variant(current_request, ordinal, values, baseline_id)
        for ordinal, values in enumerate(parameters)
    ]


class ContractTests(unittest.TestCase):
    def test_canary_contract_and_run_id_are_stable(self) -> None:
        first = request()
        second = request()
        self.assertEqual(first.candidate_budget, 27)
        self.assertEqual(first.normalized, second.normalized)
        self.assertEqual(first.run_id, second.run_id)

    def test_baseline_must_be_inside_every_range(self) -> None:
        value = json.loads(REQUEST_PATH.read_text())
        value["ranges"]["topWidthMm"] = {"start": 120, "stop": 210, "step": 30}
        with self.assertRaises(search.ContractError):
            search.SearchRequest.from_mapping(value)

    def test_budget_cannot_exceed_unique_combinations(self) -> None:
        value = json.loads(REQUEST_PATH.read_text())
        value["candidateBudget"] = 28
        with self.assertRaises(search.ContractError):
            search.SearchRequest.from_mapping(value)

    def test_long_contract_selects_4096_stable_unique_candidates(self) -> None:
        long_request = search.load_request(LONG_REQUEST_PATH)
        first = search.parameter_combinations(long_request)
        second = search.parameter_combinations(long_request)
        self.assertEqual(len(first), 4096)
        self.assertEqual(first, second)
        self.assertEqual(first[0], search.BASELINE_PARAMETERS)
        self.assertEqual(len({search._canonical_json(item) for item in first}), 4096)


class GeometryTests(unittest.TestCase):
    def test_source_profile_reconstruction_is_exact(self) -> None:
        shape = search.build_plate(search.BASELINE_PARAMETERS).val()
        box = shape.BoundingBox()
        self.assertEqual(len(shape.Solids()), 1)
        self.assertTrue(shape.isValid())
        self.assertEqual(len(shape.Faces()), 12)
        self.assertAlmostEqual(shape.Volume(), 338601.80313115753, places=6)
        self.assertEqual((box.xlen, box.ylen, box.zlen), (350.0, 350.0, 3.0))

    def test_canary_has_real_clearance_failures_and_stable_lineage(self) -> None:
        current_request = request()
        parameters = search.parameter_combinations(current_request)
        self.assertEqual(len(parameters), 27)
        self.assertEqual(parameters[0], search.BASELINE_PARAMETERS)
        evaluated = variants()
        self.assertEqual(sum(item["validity"] for item in evaluated), 18)
        failures = [item for item in evaluated if not item["validity"]]
        self.assertTrue(
            all(
                item["failureReason"]
                == "knob_clearance_envelope_intersects_plate_edge"
                for item in failures
            )
        )
        self.assertTrue(
            all(item["parameters"]["plateWidthMm"] == 330.0 for item in failures)
        )
        self.assertIsNone(evaluated[0]["parentVariantId"])
        self.assertTrue(
            all(
                item["parentVariantId"] == evaluated[0]["variantId"]
                for item in evaluated[1:]
            )
        )

    def test_winner_and_finalists_follow_measured_volume(self) -> None:
        finalists = search.choose_finalists(variants())
        self.assertEqual(
            finalists[0]["parameters"],
            {
                "plateWidthMm": 340.0,
                "topWidthMm": 120.0,
                "plateThicknessMm": 3.0,
            },
        )
        volumes = [item["metrics"]["materialVolumeMm3"] for item in finalists]
        self.assertEqual(volumes, sorted(volumes))
        self.assertTrue(all(item["physicsStatus"] == "not_run" for item in finalists))

    def test_over_thickness_candidate_is_retained_as_failure(self) -> None:
        current_request = request()
        parameters = {
            "plateWidthMm": 350.0,
            "topWidthMm": 160.0,
            "plateThicknessMm": 6.0,
        }
        baseline_id = search.variant_id(
            current_request.run_id, 0, search.BASELINE_PARAMETERS
        )
        variant = search.evaluate_variant(current_request, 1, parameters, baseline_id)
        self.assertEqual(variant["buildStatus"], "succeeded")
        self.assertEqual(variant["evaluationStatus"], "failed")
        self.assertEqual(variant["failureReason"], "plate_exceeds_5mm_rule_limit")

    def test_finalist_step_roundtrip(self) -> None:
        finalist = search.choose_finalists(variants(), count=1)[0]
        with tempfile.TemporaryDirectory() as directory:
            first = search.export_finalist(finalist, Path(directory) / "first")
            second = search.export_finalist(finalist, Path(directory) / "second")
            self.assertEqual(first["validation"]["stepRoundtripSolidCount"], 1)
            self.assertTrue(first["validation"]["stepRoundtripValid"])
            self.assertEqual(first["artifactSha256"], second["artifactSha256"])
            for path in first["artifactPath"].values():
                self.assertTrue(Path(path).is_file())


@unittest.skipUnless(
    os.environ.get("FS_AI_ASSET_ROOT"), "FS_AI_ASSET_ROOT is not set"
)
class SourceIntakeTests(unittest.TestCase):
    def test_downloaded_assets_and_named_target_pass_intake(self) -> None:
        evidence = search.preflight_assets(Path(os.environ["FS_AI_ASSET_ROOT"]))
        self.assertEqual(evidence["assembly"]["productDefinitionCount"], 45)
        self.assertEqual(evidence["assembly"]["solidCount"], 115)
        self.assertEqual(evidence["targetPart"]["productName"], "Example Plate")
        self.assertEqual(
            evidence["sensorMountingAssembly"]["componentCount"], 13
        )


if __name__ == "__main__":
    unittest.main()
