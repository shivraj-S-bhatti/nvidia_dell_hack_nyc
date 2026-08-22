import tempfile
import unittest
from pathlib import Path

from attempt1.physgen.object.prepare import (
    GateError,
    _canonicalize_exported_step,
    load_json,
    stable_id,
    validate_schema,
)


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


class ManifestTests(unittest.TestCase):
    def test_golden_manifests_validate(self):
        cases = (
            ("asset-manifest.json", "asset-manifest.schema.json"),
            ("component-manifest.json", "component-manifest.schema.json"),
            ("target-component.json", "target-component.schema.json"),
        )
        for fixture, schema in cases:
            with self.subTest(fixture=fixture):
                validate_schema(load_json(FIXTURES / fixture), schema)

    def test_asset_manifest_rejects_missing_hash(self):
        value = load_json(FIXTURES / "asset-manifest.json")
        del value["artifacts"][0]["sha256"]
        with self.assertRaises(GateError):
            validate_schema(value, "asset-manifest.schema.json")

    def test_asset_manifest_rejects_ambiguous_units(self):
        value = load_json(FIXTURES / "asset-manifest.json")
        value["loadContract"]["units"] = "metric"
        with self.assertRaises(GateError):
            validate_schema(value, "asset-manifest.schema.json")

    def test_target_manifest_rejects_unknown_fields(self):
        value = load_json(FIXTURES / "target-component.json")
        value["geometry"]["notes"] = "free-form ambiguity"
        with self.assertRaises(GateError):
            validate_schema(value, "target-component.schema.json")

    def test_component_manifest_ids_are_unique(self):
        value = load_json(FIXTURES / "component-manifest.json")
        definition_ids = [item["componentId"] for item in value["definitions"]]
        occurrence_ids = [item["occurrenceId"] for item in value["occurrences"]]
        self.assertEqual(len(definition_ids), len(set(definition_ids)))
        self.assertEqual(len(occurrence_ids), len(set(occurrence_ids)))
        self.assertEqual(value["counts"], {"definitions": 379, "occurrences": 647})

    def test_selected_identity_is_hash_stable(self):
        source_hash = "73d18cf9104c93177495f09f1aa4569c887c089ce0c9d0ddf4a97d1f26fc7c73"
        self.assertEqual(
            stable_id("component", source_hash, "WING-MOUNT-L"),
            "component-651d2501fdff2aa4f1cd",
        )
        self.assertEqual(
            stable_id("occurrence", source_hash, "SST000_ASM (1):1/WING-MOUNT-L:1"),
            "occurrence-356ea2a4ca15007f265a",
        )

    def test_step_export_timestamp_is_canonicalized(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "target.step"
            path.write_bytes(
                b"FILE_NAME('Open CASCADE Shape Model','2026-08-22T20:05:13',('Author'),'Open CASCADE');"
            )
            _canonicalize_exported_step(path)
            self.assertIn(b"1970-01-01T00:00:00", path.read_bytes())
            self.assertNotIn(b"2026-08-22T20:05:13", path.read_bytes())


if __name__ == "__main__":
    unittest.main()
