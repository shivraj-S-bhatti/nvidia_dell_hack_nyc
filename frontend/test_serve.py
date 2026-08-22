from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from frontend.serve import (
    ArtifactStore,
    RequestValidationError,
    make_change_request,
    make_human_selection,
)
from frontend.run_controller import LiveRunError, RunController, capabilities, normalize_request


class FrontendControlRecordsTest(unittest.TestCase):
    def test_change_request_maps_human_input_without_claiming_execution(self) -> None:
        record = make_change_request({
            "component": "Chassis bottom",
            "objective": "Remove mass from the quiet edge.",
            "constraint": "Preserve all four arm mounts.",
            "protectedInterfaces": ["Arm mount A", "Arm mount B"],
            "sourceRunId": "run-07",
        })
        self.assertEqual("ChangeRequest/1", record["schemaVersion"])
        self.assertEqual("queued", record["status"])
        self.assertEqual("pending", record["pipeline"]["execution"])
        self.assertEqual("Chassis bottom", record["target"]["component"])

    def test_request_rejects_missing_bounded_constraint(self) -> None:
        with self.assertRaisesRegex(RequestValidationError, "constraint"):
            make_change_request({"component": "Plate", "objective": "Make it lighter"})

    def test_human_selection_is_explicit(self) -> None:
        record = make_human_selection({
            "candidateId": "C2r",
            "candidateLabel": "Twin-spar + tension gusset",
            "runId": "run-07",
        })
        self.assertEqual("HumanSelection/1", record["schemaVersion"])
        self.assertEqual("human", record["actorType"])
        self.assertEqual("selected", record["decision"])

    def test_artifact_store_writes_and_reads_records(self) -> None:
        with TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory))
            record = {"requestId": "change-01", "status": "queued"}
            path = store.write("requests", record["requestId"], record)
            self.assertEqual(record, json.loads(path.read_text(encoding="utf-8")))
            self.assertEqual([record], store.recent("requests"))

    def test_live_request_is_bounded_to_verified_plate_adapter(self) -> None:
        request = normalize_request({
            "component": "Example Plate",
            "objective": "Reduce material to 42% while minimizing compliance.",
            "constraint": "Preserve every mount hole and interface.",
        })
        self.assertEqual(0.42, request["materialFractionTarget"])
        self.assertEqual(4, len(request["protectedInterfaces"]))
        with self.assertRaisesRegex(LiveRunError, "only Example Plate"):
            normalize_request({
                "component": "Chassis bottom",
                "objective": "Reduce material to 42%.",
                "constraint": "Preserve every mount.",
            })

    def test_capability_exposes_truthful_local_scope(self) -> None:
        value = capabilities()
        self.assertEqual("Example Plate", value["components"][0]["name"])
        self.assertEqual(4, len(value["components"][0]["protectedInterfaces"]))
        self.assertIn("factory", value["pipeline"])

    def test_live_selection_closes_only_an_eligible_run(self) -> None:
        with TemporaryDirectory() as directory:
            controller = RunController(Path(directory))
            root = Path(directory) / "run-test-01"
            root.mkdir()
            status = {
                "schemaVersion": "LiveRunStatus/1",
                "runId": "run-test-01",
                "status": "awaiting_review",
                "events": [{"stage": "review", "status": "running", "message": "Waiting"}],
            }
            result = {
                "runId": "run-test-01",
                "status": "awaiting_human_review",
                "selectionEligibleCandidateIds": ["candidate-pass"],
                "candidates": [{"id": "candidate-pass", "label": "Measured survivor"}],
            }
            (root / "status.json").write_text(json.dumps(status), encoding="utf-8")
            (root / "run.json").write_text(json.dumps(result), encoding="utf-8")
            record, destination = controller.select("run-test-01", {"candidateId": "candidate-pass"})
            self.assertEqual("candidate-pass", record["candidateId"])
            self.assertTrue(destination.is_file())
            self.assertEqual("completed", controller.get("run-test-01")["status"])


if __name__ == "__main__":
    unittest.main()
