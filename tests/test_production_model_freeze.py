"""Targeted tests for the immutable Structured A3 production freeze."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import verify_production_model_freeze as freeze  # noqa: E402


MANIFEST_PATH = REPO_ROOT / "config" / "production_model_freeze.json"


class ProductionModelFreezeTests(unittest.TestCase):
    def load_manifest(self) -> dict:
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    def write_manifest(self, payload: dict, directory: Path) -> Path:
        path = directory / "freeze.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path

    def assert_rejected(self, payload: dict) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self.write_manifest(payload, Path(directory))
            with self.assertRaises(freeze.FreezeVerificationError):
                freeze.verify(path, REPO_ROOT)

    def test_valid_manifest_is_accepted(self) -> None:
        result = freeze.verify(MANIFEST_PATH, REPO_ROOT)
        self.assertEqual(result["manifest"], "PASS")
        self.assertFalse(result["trains_model"])

    def test_missing_required_field_is_rejected(self) -> None:
        payload = self.load_manifest()
        del payload["identity"]["model_id"]
        self.assert_rejected(payload)

    def test_missing_artifact_is_rejected(self) -> None:
        payload = self.load_manifest()
        payload["frozen_artifacts"][0]["path"] = "tests/fixtures/missing-model.json"
        self.assert_rejected(payload)

    def test_artifact_hash_mismatch_is_rejected(self) -> None:
        payload = self.load_manifest()
        payload["frozen_artifacts"][0]["sha256"] = "0" * 64
        self.assert_rejected(payload)

    def test_predictor_schema_mismatch_is_rejected(self) -> None:
        payload = self.load_manifest()
        payload["predictor_specification"]["ordered_predictors"][0]["name"] = "unexpected_predictor"
        self.assert_rejected(payload)

    def test_known_answer_inference_is_deterministic(self) -> None:
        payload = self.load_manifest()
        model = freeze.load_json(REPO_ROOT / payload["frozen_artifacts"][0]["path"])
        fixture = REPO_ROOT / payload["verification"]["known_answer_fixture"]
        names = freeze.predictor_names(payload)
        freeze.check_fixture(fixture, model, names)

    def test_excluded_flight_and_sit_features_are_not_required_inputs(self) -> None:
        payload = self.load_manifest()
        payload = copy.deepcopy(payload)
        payload["predictor_specification"]["ordered_predictors"][0]["name"] = "sit_feature"
        with self.assertRaises(freeze.FreezeVerificationError):
            freeze.predictor_names(payload)


if __name__ == "__main__":
    unittest.main()
