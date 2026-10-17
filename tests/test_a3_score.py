"""Focused regression tests for prospective Structured A3 scoring."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import a3_score  # noqa: E402


class _FakeContext:
    def __init__(self, root: Path) -> None:
        self.config = {}
        self.config_path = root / "config.yaml"
        self.repo_root = root
        self.scientific = {
            "theta": 0.7,
            "penalty": 0.01,
            "objective": "exact_joint_hurdle_nll",
            "node_count": 2,
        }
        self.mode = "prospective_evaluation"
        self.run_id = "test-run"
        self.output_root = root / "output"
        self.log_root = root / "logs"
        self.chime_execution_id = None

    def input_path(self, _key: str) -> Path:
        return self.config_path

    def canonical_args(self) -> SimpleNamespace:
        return SimpleNamespace()


class _FakeFullfitModule:
    NODE_COUNT = 2
    FEATURE_ORDER = ["feature"]

    @staticmethod
    def load_bundle(_args: SimpleNamespace) -> dict:
        nodes = pd.DataFrame({
            "model_node_id": [101, 102],
            "canonical_node_id": [1, 2],
            "raster_cell": [11, 12],
            "row": [1, 1],
            "column": [1, 2],
            "x": [0.0, 1.0],
            "y": [0.0, 1.0],
            "lon": [-100.0, -99.0],
            "lat": [20.0, 21.0],
            "country_or_domain_region": ["Mexico", "U.S.-to-40N"],
        })
        return {
            "features": np.zeros((2, 2, 1), dtype=float),
            "labels": ["2026-W30", "2026-W31"],
            "counts": np.asarray([[5, 0], [2, 1]], dtype=np.int64),
            "nodes": nodes,
            "production_manifest": {
                "observation_source": {"sha256": "observation-sha"},
                "environmental_maximum_complete_week": "2026-W39",
            },
        }

    @staticmethod
    def completeness(_bundle: dict) -> tuple[dict, pd.DataFrame]:
        return (
            {"full_fit_end_week": "2026-W39"},
            pd.DataFrame({
                "week": ["2026-W30", "2026-W31"],
                "complete_fit_support": [True, True],
            }),
        )

    @staticmethod
    def predict(_state: dict, x: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        assert x.shape == (4, 1)
        return (
            np.asarray([0.1, 0.2, 0.3, 0.4]),
            np.asarray([1.0, 2.0, 3.0, 4.0]),
            np.asarray([10.0, 20.0, 30.0, 40.0]),
        )


def _write_model(path: Path, *, training_prevalence: float | None = 0.1) -> None:
    model = {
        "theta_fixed": True,
        "theta": 0.7,
        "penalty": 0.01,
        "objective": "exact_joint_hurdle_nll",
        "scaling": {"training_mean": [0.0], "training_sd": [1.0]},
        "occurrence_coefficients": [0.0, 0.0],
        "count_coefficients": [0.0, 0.0],
        "model_id": "STRUCTURED_A3_FULLFIT",
    }
    if training_prevalence is not None:
        model["training_prevalence"] = training_prevalence
    path.write_text(json.dumps(model), encoding="utf-8")


def test_prospective_predictions_preserve_week_node_array_alignment(tmp_path: Path) -> None:
    context = _FakeContext(tmp_path)
    model_path = tmp_path / "frozen_model.json"
    _write_model(model_path)
    with (
        patch("a3_pipeline.validate_deployed_manifest"),
        patch.object(a3_score, "read_json_or_yaml", return_value={"evaluation_end_week": "2026-W29"}),
        patch.object(a3_score, "deployed_model_path", return_value=model_path),
        patch.object(a3_score, "load_fullfit_module", return_value=_FakeFullfitModule),
        patch.object(a3_score, "build_prospective_report", return_value={}),
    ):
        a3_score.prospective_score(context, no_refit=True)

    frame = pd.read_parquet(context.output_root / "predictions/prospective_predictions.parquet")
    frame = frame.sort_values(["week", "model_node_id"]).reset_index(drop=True)
    np.testing.assert_allclose(frame["p_occurrence"], [0.1, 0.2, 0.3, 0.4])
    np.testing.assert_allclose(frame["conditional_count_mean"], [1.0, 2.0, 3.0, 4.0])
    np.testing.assert_allclose(frame["underlying_mu"], [10.0, 20.0, 30.0, 40.0])
    np.testing.assert_allclose(frame["expected_count"], [0.1, 0.4, 0.9, 1.6])
    np.testing.assert_array_equal(frame["observed_count"], [5, 0, 2, 1])
    assert list(zip(frame["week"], frame["model_node_id"])) == [
        ("2026-W30", 101),
        ("2026-W30", 102),
        ("2026-W31", 101),
        ("2026-W31", 102),
    ]


def test_prospective_report_rejects_missing_training_prevalence() -> None:
    predictions = pd.DataFrame({
        "observed_count": [1],
        "p_occurrence": [0.5],
        "conditional_count_mean": [2.0],
        "underlying_mu": [1.0],
        "expected_count": [1.0],
        "country_or_domain_region": ["Mexico"],
    })
    with pytest.raises(RuntimeError, match="training_prevalence"):
        a3_score.build_prospective_report(predictions, {"theta": 0.7}, [0], {})


@pytest.mark.parametrize("training_prevalence", [0.0, 1.0, -0.1, 1.1])
def test_prospective_report_rejects_endpoint_or_invalid_training_prevalence(training_prevalence: float) -> None:
    predictions = pd.DataFrame({
        "observed_count": [1],
        "p_occurrence": [0.5],
        "conditional_count_mean": [2.0],
        "underlying_mu": [1.0],
        "expected_count": [1.0],
        "country_or_domain_region": ["Mexico"],
    })
    with pytest.raises(RuntimeError, match="training_prevalence"):
        a3_score.build_prospective_report(predictions, {"theta": 0.7, "training_prevalence": training_prevalence}, [0], {})


def test_prospective_score_requires_no_refit() -> None:
    with pytest.raises(RuntimeError, match="requires --no-refit"):
        a3_score.prospective_score(None, no_refit=False)
