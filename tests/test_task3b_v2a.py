"""Unit and contract tests for the Task 3B causal V2-A workflow."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import run_task3b_v2a as task3b  # noqa: E402
from run_task3a_v2_audit import causal_front_descriptors  # noqa: E402


def test_exact_feature_width_and_order():
    assert len(task3b.MODELS["M0"]) == 24
    assert len(task3b.MODELS["M1"]) == 30
    assert len(task3b.MODELS["M2"]) == 32
    assert task3b.MODELS["M1"][-6:] == task3b.PRIMARY_FRONT_CONTINUOUS + task3b.PRIMARY_FRONT_AVAILABILITY
    assert task3b.MODELS["M2"][-2:] == task3b.LATITUDE_FEATURES


def test_front_features_are_strictly_temporally_causal():
    weeks = ["2025-W01", "2025-W02", "2025-W03", "2025-W04"]
    xy = np.array([[0.0, 0.0], [25.0, 0.0], [50.0, 0.0]])
    lat = np.array([10.0, 20.0, 30.0])
    original = [np.array([0]), np.array([1]), np.array([], dtype=int), np.array([2])]
    mutated = [np.array([0]), np.array([1]), np.array([2]), np.array([2])]
    left = causal_front_descriptors(original, xy, lat, weeks).set_index(["week_index", "node_id"])
    right = causal_front_descriptors(mutated, xy, lat, weeks).set_index(["week_index", "node_id"])
    pd.testing.assert_frame_equal(left.loc[left.index.get_level_values(0) < 2], right.loc[right.index.get_level_values(0) < 2])
    assert not np.array_equal(left.loc[2]["northmost_prior_latitude"], right.loc[2]["northmost_prior_latitude"])


def test_current_response_cannot_change_current_predictor():
    weeks = ["2025-W01", "2025-W02", "2025-W03"]
    xy = np.array([[0.0, 0.0], [25.0, 0.0], [50.0, 0.0]])
    lat = np.array([10.0, 20.0, 30.0])
    original = causal_front_descriptors([np.array([0]), np.array([1]), np.array([], dtype=int)], xy, lat, weeks).set_index(["week_index", "node_id"])
    changed = causal_front_descriptors([np.array([0]), np.array([1, 2]), np.array([], dtype=int)], xy, lat, weeks).set_index(["week_index", "node_id"])
    pd.testing.assert_frame_equal(original.loc[1], changed.loc[1])


def test_unavailable_history_uses_nonzero_deterministic_placeholder():
    raw = np.array([np.nan, 25.0])
    available = np.isfinite(raw)
    placeholder = 1000.0
    encoded = np.where(available, raw, placeholder)
    assert encoded[0] == placeholder
    assert not bool(available[0])
    assert encoded[1] == 25.0
    assert bool(available[1])


def test_rolling_origin_boundaries_and_historical_labels():
    labels = [f"2025-W{i:02d}" for i in range(1, 53)] + [f"2026-W{i:02d}" for i in range(1, 30)]
    folds = task3b.response_folds(pd.DataFrame({"iso_week": labels}))
    assert folds[0]["train_start"] == "2025-W01"
    assert folds[0]["validation_start"] == "2025-W27"
    assert folds[3]["validation_end"] == "2026-W16"
    assert folds[4]["label"] == "historical pseudo-prospective, non-independent"
    assert folds[5]["validation_start"] == "2026-W23"
    assert all(max(fold["validation_indices"]) < 81 for fold in folds)


def test_v1_feature_contract_is_unchanged():
    assert task3b.BASE_FEATURES[:12] == [
        "era5_mintemp", "era5_soilmoist", "era5_lai_low", "agera5_relhum_min",
        "era5land_tmean", "era5land_soiltemp_l1_mean", "era5land_soiltemp_l2_mean",
        "era5land_soilwater_l1_mean", "era5land_soilwater_l2_mean",
        "era5land_surface_pressure_mean", "era5land_lai_high_mean", "era5land_lai_low_mean",
    ]
    assert task3b.BASE_FEATURES[-2:] == ["week_sin", "week_cos"]
