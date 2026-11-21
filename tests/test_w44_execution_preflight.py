"""Focused synthetic checks for W44 fail-closed execution preflights."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import w44_execution_preflight as preflight  # noqa: E402


def write(path: Path, content: bytes = b"fixture") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Task2EPreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.refresh = self.root / "refresh"
        self.refresh.mkdir()
        self.source = self.root / "task2a"
        for relative in preflight.TASK2E_REQUIRED_RELATIVE_FILES:
            write(self.source / relative)
        feature_manifest = self.source / "model_data/raw/feature_manifest.json"
        feature_manifest.write_text(json.dumps({
            "status": "completed", "target_start": "2024-01-01", "target_end": "2026-10-26"
        }), encoding="utf-8")
        self.previous = self.root / "previous"
        write(self.previous / "revised_domain/raw/nodes.parquet")
        write(self.previous / "revised_domain/graph/edges_queen.parquet")
        self.observation = write(self.root / "observations.csv", b"synthetic observation bytes")
        self.boundary = write(self.root / "boundary.gpkg")
        self.feature_manifest = feature_manifest

    def tearDown(self) -> None:
        self.temp.cleanup()

    def validate(self, **overrides):
        values = {
            "refresh_root_value": self.refresh,
            "source_root_value": self.source,
            "previous_root_value": self.previous,
            "observation_value": self.observation,
            "boundary_value": self.boundary,
            "boundary_layer": "study_states",
            "expected_observation_sha256": sha(self.observation),
            "expected_feature_manifest_sha256": sha(self.feature_manifest),
        }
        values.update(overrides)
        return preflight.validate_task2e(**values)

    def test_valid_explicit_new_output_is_accepted_without_creating_it(self) -> None:
        report = self.validate()
        self.assertEqual(report["response_end"], "2026-W44")
        self.assertEqual(report["observation_sha256"], sha(self.observation))
        self.assertEqual(report["output_directory_state"], "new")
        self.assertFalse((self.refresh / "revised_model_data").exists())

    def test_missing_or_empty_output_is_rejected_without_writes(self) -> None:
        with self.assertRaises(preflight.PreflightError):
            self.validate(refresh_root_value=None)
        with self.assertRaises(preflight.PreflightError):
            preflight.ensure_output_directory_available("", "output")
        self.assertEqual(list(self.refresh.iterdir()), [])

    def test_declared_observation_vintage_mismatch_is_rejected(self) -> None:
        with self.assertRaisesRegex(preflight.PreflightError, "observation source SHA-256"):
            self.validate(expected_observation_sha256="0" * 64)
        self.assertFalse((self.refresh / "revised_model_data").exists())

    def test_populated_output_is_protected(self) -> None:
        marker = write(self.refresh / "revised_model_data/keep.txt", b"preserve")
        with self.assertRaisesRegex(preflight.PreflightError, "populated"):
            self.validate()
        self.assertEqual(marker.read_bytes(), b"preserve")

    def test_empty_existing_output_is_accepted(self) -> None:
        (self.refresh / "revised_model_data").mkdir()
        report = self.validate()
        self.assertEqual(report["output_directory_state"], "empty-existing")


class GeneralPreflightTests(unittest.TestCase):
    def test_task2a_output_aliases_require_one_unambiguous_absolute_path(self) -> None:
        selected = Path(tempfile.gettempdir()) / "task2a-output"
        self.assertEqual(preflight.resolve_task2a_output_root("", str(selected)), selected)
        self.assertEqual(preflight.resolve_task2a_output_root(str(selected), ""), selected)
        with self.assertRaises(preflight.PreflightError):
            preflight.resolve_task2a_output_root(str(selected), str(selected.parent / "other"))
        with self.assertRaises(preflight.PreflightError):
            preflight.resolve_task2a_output_root("", "")

    def test_unsupported_stgnn_configuration_name_is_rejected(self) -> None:
        with self.assertRaisesRegex(preflight.PreflightError, "STGNN_OUTPUT_ROOOT"):
            preflight.check_environment_names("task2a", {"STGNN_OUTPUT_ROOOT": "/wrong"})

    def test_task2a_raw_stage_resume_is_limited_to_unstarted_pipeline_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "candidate"
            (output / "manifests").mkdir(parents=True)
            task1 = write(output / "manifests/preflight_manifest.json")
            raw = output / "model_data/raw"
            for name in preflight.TASK2A_RAW_FILES:
                write(raw / name)
            report = preflight.validate_task2a_pipeline(output, task1)
            self.assertTrue(report["continuation_from_raw_stage"])
            marker = write(output / "model_data/splits/existing.parquet")
            with self.assertRaisesRegex(preflight.PreflightError, "existing Task 2A pipeline output"):
                preflight.validate_task2a_pipeline(output, task1)
            self.assertEqual(marker.read_bytes(), b"fixture")


class FullfitPreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.output_root = self.root / "fullfit"
        self.model_output = self.root / "task2e"
        self.obs_sha = "a" * 64
        self.model_output.mkdir()
        write(self.model_output / "manifests/revised_production_manifest.json", json.dumps({
            "status": "production_dataset_built_audit_complete",
            "observation_source": {"sha256": self.obs_sha},
            "response": {"start": "2025-W01", "end": "2026-W44"},
        }).encode())
        for name in (
            "dynamic_features.npy", "dynamic_history_features.npy", "static_features.npy",
            "targets_count.npy", "targets_presence.npy", "weeks.parquet",
            "calendar_features.parquet", "nodes.parquet",
        ):
            write(self.model_output / "raw" / name)
        self.front = write(self.root / "front/causal_front_features.parquet")
        write(self.front.parent / "production_front_feature_manifest.json", json.dumps({
            "status": "production_causal_front_features_complete",
            "response_start": "2025-W01", "response_end": "2026-W44",
            "feature_sha256": sha(self.front),
            "leakage_audit": {"source_observation_sha256": self.obs_sha},
        }).encode())
        self.anthro = write(self.root / "anthro.parquet")
        self.soil = write(self.root / "soil.parquet")
        self.original_a3_manifest = preflight.A3_FEATURE_MANIFEST
        preflight.A3_FEATURE_MANIFEST = write(
            self.root / "a3_feature_manifest.json",
            json.dumps({
                "soil_artifact_sha256": sha(self.soil),
                "augmentation_manifest": {"anthropogenic_source_sha256": sha(self.anthro)},
            }).encode(),
        )

    def tearDown(self) -> None:
        preflight.A3_FEATURE_MANIFEST = self.original_a3_manifest
        self.temp.cleanup()

    def validate(self, **overrides):
        values = {
            "output_root_value": self.output_root,
            "model_output_value": self.model_output,
            "front_features_value": self.front,
            "anthropogenic_features_value": self.anthro,
            "soil_features_value": self.soil,
            "expected_observation_sha256": self.obs_sha,
            "response_start": "2025-W01", "response_end": "2026-W44",
        }
        values.update(overrides)
        return preflight.validate_fullfit(**values)

    def test_valid_vintage_and_new_output_are_accepted(self) -> None:
        report = self.validate()
        self.assertEqual(report["response_end"], "2026-W44")
        self.assertIn("source_artifacts", report)
        self.assertFalse(self.output_root.exists())

    def test_front_feature_vintage_mismatch_is_rejected(self) -> None:
        manifest = self.front.parent / "production_front_feature_manifest.json"
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["leakage_audit"]["source_observation_sha256"] = "b" * 64
        manifest.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(preflight.PreflightError, "front-feature source observation checksum"):
            self.validate()
        self.assertFalse(self.output_root.exists())

    def test_populated_fullfit_destination_is_protected(self) -> None:
        marker = write(self.output_root / "existing.bin", b"leave intact")
        with self.assertRaisesRegex(preflight.PreflightError, "populated"):
            self.validate()
        self.assertEqual(marker.read_bytes(), b"leave intact")

    def test_documented_completed_fit_resume_checks_source_checksums(self) -> None:
        initial = self.validate()
        for relative in (
            "model/fullfit_a3_model.json", "model/fullfit_a3_manifest.json",
            "predictions/weekly_predictions.parquet", "manifests/fullfit_data_horizon.json",
        ):
            write(self.output_root / relative)
        fit_manifest = {
            "status": "fit_complete", "model": "STRUCTURED_A3_FULLFIT",
            "horizon": {"full_fit_start_week": "2025-W01", "full_fit_end_week": "2026-W44"},
            "source_artifacts": initial["source_artifacts"],
        }
        fit_manifest["source_artifacts"].pop("a3_feature_manifest")
        fit_manifest["source_artifacts"].pop("front_feature_manifest")
        fit_manifest["source_artifacts"]["frozen_a3_evaluation_manifest"]["path"] = "/another/checkout/frozen_a3_evaluation_manifest.json"
        write(self.output_root / "manifests/fullfit_fit_manifest.json", json.dumps(fit_manifest).encode())
        resumed = self.validate(resume_after_fit=True)
        self.assertTrue(resumed["resume_after_fit"])
        self.soil.write_bytes(b"changed vintage")
        with self.assertRaisesRegex(preflight.PreflightError, "soil feature checksum"):
            self.validate(resume_after_fit=True)


if __name__ == "__main__":
    unittest.main()
