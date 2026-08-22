from __future__ import annotations

import json
import unittest

from autoauto.build import HERE, assemble_run, build


class AutoautoIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.run_record = assemble_run()
        cls.integration = cls.run_record["integration"]

    def test_real_family_and_factory_boundary(self) -> None:
        proposals = self.integration["lab"]["proposals"]
        self.assertEqual(3, len(proposals))
        self.assertEqual(2, sum(item["trackEligible"] for item in proposals))
        self.assertEqual(1, sum(item["factory"]["verdict"] == "fail" for item in proposals))

    def test_rejected_candidate_cannot_reach_track(self) -> None:
        rejected = next(item for item in self.integration["lab"]["proposals"] if item["factory"]["verdict"] == "fail")
        self.assertFalse(rejected["trackEligible"])
        self.assertEqual("check.volume-centroid-shift", rejected["factory"]["failedChecks"][0]["check_id"])

    def test_object_and_contract_identity(self) -> None:
        self.assertEqual("WING-MOUNT-L", self.integration["object"]["targetName"])
        self.assertEqual(647, self.integration["object"]["occurrences"])
        self.assertEqual(379, len(self.integration["object"]["bom"]))
        self.assertGreater(self.integration["object"]["fullVehicleImage"]["triangleCount"], 0)
        interactive = self.integration["object"]["interactiveVehicle"]
        self.assertEqual(647, interactive["counts"]["occurrences"])
        self.assertEqual(499, interactive["counts"]["renderableLeafOccurrences"])
        self.assertGreater(interactive["counts"]["triangles"], 1_000_000)
        self.assertGreater(interactive["counts"]["selectionTriangles"], 800_000)
        self.assertGreaterEqual(self.integration["contracts"]["recordsValidated"], 9)
        self.assertEqual(7, self.integration["contracts"]["entitySchemas"])

    def test_build_uses_separate_ui_files(self) -> None:
        build()
        html = (HERE / "index.html").read_text(encoding="utf-8")
        self.assertIn("integration.js", html)
        self.assertIn("interactive-viewer.js", html)
        self.assertIn("/vendor/three-bundle.js", html)
        self.assertIn('data-viewer-mode="exploded"', html)
        self.assertIn('data-viewer-mode="focus"', html)
        self.assertIn("autoauto.issue42-47/v1", html)
        self.assertIn("full-vehicle.png", html)
        self.assertNotIn('/examples/easyrc/viewer/?embed=1', html)
        self.assertNotIn('/examples/easyrc/viewer/parts.json', html)

    def test_interactive_mesh_preserves_clickable_occurrence_identity(self) -> None:
        mesh = json.loads((HERE / "interactive" / "mesh.json").read_text(encoding="utf-8"))
        parts = mesh["parts"]
        self.assertEqual(499, len(parts))
        self.assertEqual(len(parts), len({part["occurrenceId"] for part in parts}))
        self.assertTrue(any(part["occurrenceId"] == self.integration["object"]["occurrenceId"] for part in parts))
        position_size = (HERE / "interactive" / "mesh_pos.bin").stat().st_size
        index_size = (HERE / "interactive" / "mesh_idx.bin").stat().st_size
        display = mesh["display"]
        self.assertLessEqual(display["pOff"] + display["pCount"] * 3 * 2, position_size)
        display_index_width = 4 if display["i32"] else 2
        self.assertLessEqual(display["iOff"] + display["iCount"] * display_index_width, index_size)
        for part in parts:
            self.assertEqual(part["componentId"], part["ancestorComponentIds"][-1])
            self.assertEqual(part["occurrenceId"], part["ancestorOccurrenceIds"][-1])
            self.assertLessEqual(part["pOff"] + part["pCount"] * 3 * 2, position_size)
            index_width = 4 if part["i32"] else 2
            self.assertLessEqual(part["iOff"] + part["iCount"] * index_width, index_size)


if __name__ == "__main__":
    unittest.main()
