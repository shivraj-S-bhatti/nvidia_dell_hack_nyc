from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from attempt1.physgen.lab.artifacts import sha256_array, validate_density, write_density
from attempt1.physgen.lab.problem import CanonicalProblem, ProblemContractError


FIXTURE = Path("attempt1/physgen/fixtures/canonical-problem.json")


class ProblemTests(unittest.TestCase):
    def test_canonical_fixture_maps_to_native_oat_fields(self) -> None:
        problem = CanonicalProblem.from_path(FIXTURE)
        self.assertEqual(problem.schema_version, "nightshift.design-problem/v1")
        self.assertEqual(problem.design_problem_id, "design-problem.opento-test-0000")
        self.assertEqual(problem.grid_shape, (88, 107))
        self.assertEqual(problem.candidate_budget, 3)
        self.assertEqual(problem.seeds, (7,))
        self.assertEqual(problem.oat_loads(), [[0.5887850522994995, 0.38317757844924927, 0.0, 1.0]])
        self.assertEqual(len(problem.oat_boundary_conditions()), 3)

    def test_unknown_problem_field_is_rejected(self) -> None:
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        payload["surprise"] = True
        with self.assertRaisesRegex(ProblemContractError, "unknown DesignProblem fields"):
            CanonicalProblem.from_dict(payload)

    def test_out_of_domain_support_is_rejected(self) -> None:
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        payload["supports"][0]["region"]["min_mm"] = [99.0, 0.0, 0.0]
        payload["supports"][0]["region"]["max_mm"] = [99.0, 0.0, 0.0]
        with self.assertRaisesRegex(ProblemContractError, "outside domain"):
            CanonicalProblem.from_dict(payload)

    def test_domain_sidecar_hash_is_enforced(self) -> None:
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        payload["design_domain"]["sha256"] = "0" * 64
        payload["design_domain"]["uri"] = f"artifact://sha256/{'0' * 64}"
        with self.assertRaisesRegex(ProblemContractError, "same-hash repo:// evidence"):
            CanonicalProblem.from_dict(payload)


class ArtifactTests(unittest.TestCase):
    def test_density_hash_is_byte_stable(self) -> None:
        density = np.arange(12, dtype=np.float32).reshape(3, 4) / 11
        self.assertEqual(sha256_array(density), sha256_array(density.copy()))

    def test_nonfinite_and_unbounded_density_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "non-finite"):
            validate_density(np.array([[0.0, np.nan]], dtype=np.float32))
        with self.assertRaisesRegex(ValueError, "outside"):
            validate_density(np.array([[0.0, 1.1]], dtype=np.float32))

    def test_array_and_preview_are_hash_addressed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "density.npy"
            result = write_density(output, np.full((4, 5), 0.25, dtype=np.float32))
            self.assertTrue(output.exists())
            self.assertTrue(output.with_suffix(".png").exists())
            self.assertEqual(result["shape"], [4, 5])
            self.assertEqual(len(result["content_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
