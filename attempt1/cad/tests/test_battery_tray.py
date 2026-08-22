from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


CAD_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CAD_ROOT))

import battery_tray as tray  # noqa: E402


class ContractTests(unittest.TestCase):
    def test_frozen_request_is_accepted(self) -> None:
        request = tray.MutationRequest.from_mapping(
            {"parameter": "trayWidthMm", "deltaMm": 10}
        )
        self.assertEqual(request.as_dict(), {"parameter": "trayWidthMm", "deltaMm": 10.0})

    def test_unapproved_delta_is_rejected(self) -> None:
        with self.assertRaises(tray.ContractError):
            tray.MutationRequest.from_mapping(
                {"parameter": "trayWidthMm", "deltaMm": 5}
            )

    def test_extra_field_is_rejected(self) -> None:
        with self.assertRaises(tray.ContractError):
            tray.MutationRequest.from_mapping(
                {"parameter": "trayWidthMm", "deltaMm": 10, "guess": True}
            )


class GeometryTests(unittest.TestCase):
    def test_propagation_is_exact_and_revision_ids_are_stable(self) -> None:
        baseline = tray.build_revision(tray.BASELINE_TRAY_WIDTH_MM, None)
        changed = tray.build_revision(
            tray.BASELINE_TRAY_WIDTH_MM + 10.0, baseline.revision_id
        )
        self.assertEqual(baseline.revision_id, tray.revision_id(100.0))
        self.assertEqual(changed.revision_id, tray.revision_id(110.0))
        self.assertEqual(
            tray.compare_revisions(baseline, changed),
            {
                "boardWidthDeltaMm": 10.0,
                "padWidthDeltaMm": 10.0,
                "screwDeltaXmm": {
                    tray.SCREW_IDS[0]: -5.0,
                    tray.SCREW_IDS[1]: -5.0,
                    tray.SCREW_IDS[2]: 5.0,
                    tray.SCREW_IDS[3]: 5.0,
                },
                "alignedScrewCount": 4,
            },
        )

    def test_step_and_stl_export_roundtrip(self) -> None:
        revision = tray.build_revision(tray.BASELINE_TRAY_WIDTH_MM, None)
        with tempfile.TemporaryDirectory() as directory:
            exported = tray.export_revision(revision, Path(directory))
            self.assertEqual(exported["buildStatus"], "succeeded")
            self.assertEqual(exported["validation"]["stepRoundtripSolidCount"], 6)
            self.assertTrue(exported["validation"]["stepRoundtripValid"])
            for artifact in exported["artifactPath"].values():
                self.assertTrue(Path(artifact).is_file())
            manifest = json.loads(Path(exported["artifactPath"]["manifest"]).read_text())
            self.assertEqual(len(manifest["parts"]), 6)


if __name__ == "__main__":
    unittest.main()
