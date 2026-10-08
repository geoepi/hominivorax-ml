"""Contract tests for the limited Structured A3 orchestration layer."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import a3_pipeline  # noqa: E402


def make_config(output_root: Path, log_root: Path, prospective_manifest: Path | None = None) -> dict:
    config = {
        "schema_version": 1,
        "repository_root": str(REPO_ROOT),
        "scientific_config": str(REPO_ROOT / "config" / "structured_a3.yaml"),
        "output_root": str(output_root),
        "prospective_output_root": str(output_root / "prospective_evaluation"),
        "scratch_root": str(output_root / "scratch"),
        "logs_root": str(log_root),
        "inputs": {
            "observation_path": str(output_root / "observations.csv"),
            "environmental_root": str(output_root / "environmental"),
            "static_predictor_root": str(output_root / "static"),
            "history_feature_path": str(output_root / "history.parquet"),
        },
        "slurm": {"account": "test", "partition": "test"},
        "commands": {
            "P0": "true",
            "P1": "true",
            "P2": "true",
            "P4": "true",
            "P5": "true",
            "production_fullfit": {"P3": "true"},
            "prospective_evaluation": {"P3": "true --no-refit"},
        },
    }
    if prospective_manifest is not None:
        config["inputs"]["deployed_model_manifest"] = str(prospective_manifest)
    return config


class A3OrchestrationTests(unittest.TestCase):
    def test_chime_execution_id_validation_and_normalization(self) -> None:
        self.assertIsNone(a3_pipeline.normalize_chime_execution_id(None))
        self.assertIsNone(a3_pipeline.normalize_chime_execution_id("  \t"))
        self.assertEqual(
            a3_pipeline.normalize_chime_execution_id("  manual-correlation-validation-20261007  "),
            "manual-correlation-validation-20261007",
        )
        with self.assertRaises(a3_pipeline.PipelineError):
            a3_pipeline.normalize_chime_execution_id("valid\ninvalid")
        with self.assertRaises(a3_pipeline.PipelineError):
            a3_pipeline.normalize_chime_execution_id("valid\x00invalid")
        with self.assertRaises(a3_pipeline.PipelineError):
            a3_pipeline.normalize_chime_execution_id("x" * (a3_pipeline.CHIME_EXECUTION_ID_MAX_BYTES + 1))

    def test_chime_execution_id_is_manifest_provenance_only(self) -> None:
        scientific = a3_pipeline.validate_frozen_manifest(REPO_ROOT / "config" / "structured_a3.yaml")
        without_id = a3_pipeline.base_manifest("same-run", "production_fullfit", scientific, REPO_ROOT)
        with_id = a3_pipeline.base_manifest(
            "same-run",
            "production_fullfit",
            scientific,
            REPO_ROOT,
            "manual-correlation-validation-20261007",
        )
        self.assertIsNone(without_id["chime_execution_id"])
        self.assertEqual(with_id["chime_execution_id"], "manual-correlation-validation-20261007")
        for field in (
            "run_id",
            "repository_sha",
            "scientific_specification_sha256",
            "predictor_manifest_sha256",
            "model_name",
            "theta",
            "penalty",
            "domain_node_count",
        ):
            self.assertEqual(with_id[field], without_id[field], field)

    def test_chime_execution_id_is_exported_unchanged_to_all_stages(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = make_config(root / "outputs", root / "logs")
            scientific = a3_pipeline.validate_frozen_manifest(REPO_ROOT / "config" / "structured_a3.yaml")
            submitted: list[tuple[list[str], dict]] = []

            def fake_run(command, **kwargs):
                if command and command[0] == "sbatch":
                    submitted.append((command, kwargs))
                return mock.Mock(stdout=f"{len(submitted)}\n")

            with mock.patch.dict(a3_pipeline.os.environ, {a3_pipeline.CHIME_EXECUTION_ID_ENV: "  correlation-A  "}, clear=False):
                with mock.patch.object(a3_pipeline.subprocess, "run", side_effect=fake_run):
                    result = a3_pipeline.submit_pipeline(
                        config,
                        root / "atlas.yaml",
                        REPO_ROOT,
                        "production_fullfit",
                        "same-run",
                        scientific,
                        None,
                    )
            self.assertEqual(result, 0)
            self.assertEqual(len(submitted), len(a3_pipeline.STAGES))
            manifest = json.loads((root / "logs" / "same-run" / "submission_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["chime_execution_id"], "correlation-A")
            for command, kwargs in submitted:
                self.assertIn("--export=ALL", command)
                self.assertEqual(kwargs["env"][a3_pipeline.CHIME_EXECUTION_ID_ENV], "correlation-A")

    def test_exact_frozen_model_guard(self) -> None:
        scientific = a3_pipeline.validate_frozen_manifest(REPO_ROOT / "config" / "structured_a3.yaml")
        self.assertEqual(scientific["model_name"], "STRUCTURED_A3")
        self.assertEqual(scientific["predictor_count"], 34)
        self.assertEqual(scientific["theta"], 0.7018903965556372)
        self.assertEqual(scientific["penalty"], 0.01)
        self.assertEqual(scientific["node_count"], 10037)

    def test_dependency_plan_and_dry_run_do_not_submit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = make_config(root / "outputs", root / "logs")
            config_path = root / "atlas.yaml"
            try:
                import yaml  # type: ignore

                config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
            except ImportError:
                self.skipTest("PyYAML is required for the executable dry-run test")
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                result = a3_pipeline.main(["--mode", "production_fullfit", "--config", str(config_path), "--dry-run", "--run-id", "test-run"])
            self.assertEqual(result, 0)
            output = stream.getvalue()
            self.assertIn("stage=P0 job_id=NOT_SUBMITTED dependency=none", output)
            self.assertIn("stage=P1 job_id=NOT_SUBMITTED dependency=afterok:<job:P0>", output)
            self.assertIn("chime_execution_id: null", output)
            self.assertIn("submissions: 0", output)
            self.assertFalse((root / "logs").exists())

    def test_prospective_mode_requires_no_refit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            deployed = root / "deployed.json"
            deployed.write_text(json.dumps({
                "model_sha": "release-sha",
                "fit_end_week": "2026-W29",
                "evaluation_end_week": "2026-W29",
                "predictor_manifest_sha256": "pending",
                "theta": a3_pipeline.THETA,
                "penalty": a3_pipeline.PENALTY,
            }), encoding="utf-8")
            config = make_config(root / "outputs", root / "logs", deployed)
            config["commands"]["prospective_evaluation"]["P3"] = "python score.py --refit"
            scientific = a3_pipeline.validate_frozen_manifest(REPO_ROOT / "config" / "structured_a3.yaml")
            with self.assertRaises(a3_pipeline.PipelineError):
                a3_pipeline.validate_config(config, "prospective_evaluation", dry_run=True, scientific=scientific)

    def test_prospective_output_is_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = make_config(root / "outputs", root / "logs")
            config["prospective_output_root"] = config["output_root"]
            with self.assertRaises(a3_pipeline.PipelineError):
                a3_pipeline.output_root(config, "prospective_evaluation")


if __name__ == "__main__":
    unittest.main()
