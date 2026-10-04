"""Contract tests for the frozen V2-A prospective harness.

These tests intentionally exercise chronology and artifact contracts rather than
prospective model performance.  Historical sandbox artifacts are test fixtures
only and are never counted as prospective evidence.
"""

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import run_v2a_prospective as task3c  # noqa: E402
from run_task3a_v2_audit import causal_front_descriptors  # noqa: E402


OUTPUT = Path(os.environ.get("STGNN_V2_PROSPECTIVE_OUTPUT", "/project/disease_ecology/STGNN-output/v2_prospective"))
EXPECTED_FEATURES = [
    "era5_mintemp", "era5_soilmoist", "era5_lai_low", "agera5_relhum_min",
    "era5land_tmean", "era5land_soiltemp_l1_mean", "era5land_soiltemp_l2_mean",
    "era5land_soilwater_l1_mean", "era5land_soilwater_l2_mean",
    "era5land_surface_pressure_mean", "era5land_lai_high_mean", "era5land_lai_low_mean",
    "cattle_density", "goat_density", "sheep_density", "horse_density", "pig_density",
    "cattle_density_imputed", "goat_density_imputed", "sheep_density_imputed",
    "horse_density_imputed", "pig_density_imputed", "week_sin", "week_cos",
    "distance_to_any_prior_positive_log1p", "distance_to_prev4_positive_log1p",
    "weeks_since_detection_within_50km_log1p", "any_prior_positive_available",
    "prev4_positive_available", "detection_within_50km_ever_available",
]


def test_frozen_model_contract_and_feature_order():
    manifest_path = OUTPUT / "manifests/v2a_frozen_specification_manifest.json"
    if not manifest_path.exists():
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["model_id"] == "STGNN-Hurdle-V2A"
    assert int(manifest["feature_count"]) == 30
    assert list(manifest["feature_order"]) == EXPECTED_FEATURES
    assert float(manifest["penalty"]) == 0.01
    assert manifest["no_online_retraining"] is True


def test_history_cutoff_is_exactly_prior_iso_week():
    assert task3c.previous_week("2026-W30") == "2026-W29"
    assert task3c.previous_week("2027-W01") == "2026-W53"
    assert task3c.week_end_timestamp("2026-W29").endswith("23:59:59+00:00")


def test_front_history_is_strictly_causal_and_future_invariant():
    weeks = ["2025-W01", "2025-W02", "2025-W03", "2025-W04"]
    xy = np.array([[0.0, 0.0], [25.0, 0.0], [50.0, 0.0]])
    lat = np.array([10.0, 20.0, 30.0])
    original = [np.array([0]), np.array([1]), np.array([], dtype=int), np.array([2])]
    mutated_future = [np.array([0]), np.array([1]), np.array([2]), np.array([2])]
    left = causal_front_descriptors(original, xy, lat, weeks).set_index(["week_index", "node_id"])
    right = causal_front_descriptors(mutated_future, xy, lat, weeks).set_index(["week_index", "node_id"])
    pd.testing.assert_frame_equal(left.loc[left.index.get_level_values(0) < 2], right.loc[right.index.get_level_values(0) < 2])
    pd.testing.assert_frame_equal(left.loc[2], right.loc[2])
    assert not np.array_equal(left.loc[3]["distance_to_any_prior_detection_km"], right.loc[3]["distance_to_any_prior_detection_km"])


def test_current_week_response_cannot_change_current_front_state():
    weeks = ["2025-W01", "2025-W02", "2025-W03"]
    xy = np.array([[0.0, 0.0], [25.0, 0.0], [50.0, 0.0]])
    lat = np.array([10.0, 20.0, 30.0])
    original = causal_front_descriptors([np.array([0]), np.array([1]), np.array([], dtype=int)], xy, lat, weeks).set_index(["week_index", "node_id"])
    changed = causal_front_descriptors([np.array([0]), np.array([1, 2]), np.array([], dtype=int)], xy, lat, weeks).set_index(["week_index", "node_id"])
    pd.testing.assert_frame_equal(original.loc[1], changed.loc[1])


def test_unavailable_history_encoding_is_deterministic_and_nonzero():
    raw = np.array([np.nan, 25.0])
    available = np.isfinite(raw)
    encoded1 = np.where(available, raw, 1000.0)
    encoded2 = np.where(available, raw, 1000.0)
    assert np.array_equal(encoded1, encoded2)
    assert encoded1[0] != 0.0 and not bool(available[0])
    assert encoded1[1] == 25.0 and bool(available[1])


def test_incremental_front_state_matches_clean_prefix_recomputation():
    weeks = ["2025-W01", "2025-W02", "2025-W03", "2025-W04"]
    xy = np.array([[0.0, 0.0], [25.0, 0.0], [50.0, 0.0]])
    lat = np.array([10.0, 20.0, 30.0])
    positives = [np.array([0]), np.array([1]), np.array([2]), np.array([], dtype=int)]
    full = causal_front_descriptors(positives, xy, lat, weeks)
    for target in range(len(weeks)):
        prefix = positives[:target] + [np.array([], dtype=int)]
        prefix_state = causal_front_descriptors(prefix, xy, lat, weeks[: target + 1])
        expected = full.loc[full["week_index"] == target].sort_values("node_id").reset_index(drop=True)
        actual = prefix_state.loc[prefix_state["week_index"] == target].sort_values("node_id").reset_index(drop=True)
        pd.testing.assert_frame_equal(expected, actual)


def test_immutable_forecast_artifact_rejects_mutation():
    frame = pd.DataFrame({"forecast_week": ["2026-W30"], "predicted_probability": [0.25]})
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "forecast.parquet"
        first = task3c.immutable_parquet(frame, path)
        second = task3c.immutable_parquet(frame.copy(), path)
        assert first == second == hashlib.sha256(path.read_bytes()).hexdigest()
        with np.testing.assert_raises(RuntimeError):
            task3c.immutable_parquet(frame.assign(predicted_probability=0.75), path)


def test_historical_sandbox_artifacts_are_not_prospective():
    outcomes = OUTPUT / "sandbox/outcomes/prospective_outcomes_2026-W28.parquet"
    ledger = OUTPUT / "sandbox/prospective_evaluation_ledger.parquet"
    if not outcomes.exists() or not ledger.exists():
        return
    outcome = pd.read_parquet(outcomes)
    assert not outcome["prospective_eligible"].astype(bool).any()
    assert outcome["historical_backfill"].astype(bool).all()
    required = {"forecast_issue_timestamp_utc", "outcome_ingestion_timestamp_utc", "prospective_eligible", "historical_backfill", "observed_count", "observed_presence", "region"}
    assert required.issubset(pd.read_parquet(ledger).columns)


def test_sandbox_prediction_has_no_outcome_fields_and_has_front_contract():
    prediction = OUTPUT / "sandbox/predictions/prospective_predictions_2026-W28.parquet"
    if not prediction.exists():
        return
    frame = pd.read_parquet(prediction)
    assert len(frame) == task3c.NODE_COUNT
    assert not {"observed_count", "observed_presence"}.intersection(frame.columns)
    assert {"history_cutoff_week", "history_cutoff_timestamp", "model_manifest_sha", "input_manifest_sha"}.issubset(frame.columns)
    assert frame["forecast_week"].eq("2026-W28").all()
    assert frame["history_cutoff_week"].eq("2026-W27").all()
    assert frame["predicted_probability"].between(0, 1).all()


def test_sandbox_map_separation_if_map_fixture_exists():
    pre = OUTPUT / "sandbox/maps/forecast_2026-W27_preoutcome.svg"
    scored = OUTPUT / "sandbox/maps/forecast_2026-W27_scored.svg"
    if not pre.exists() or not scored.exists():
        return
    assert "pre-outcome" in pre.read_text(encoding="utf-8")
    assert "scored" in scored.read_text(encoding="utf-8")


def test_production_registry_and_status_are_initially_awaiting_data():
    registry = OUTPUT / "forecast_registry/prospective_forecast_registry.csv"
    status = OUTPUT / "prospective_status.json"
    if not registry.exists() or not status.exists():
        return
    registry_frame = pd.read_csv(registry)
    assert {"forecast_week", "prediction_sha256", "model_sha256", "score_status", "test_mode"}.issubset(registry_frame.columns)
    assert registry_frame.empty
    status_json = status.read_text(encoding="utf-8")
    assert "HARNESS READY" in status_json


def test_input_bundle_contract_if_frozen_artifacts_exist():
    bundle = Path("/project/disease_ecology/STGNN-output/revised_model_data")
    if not (bundle / "raw/dynamic_features.npy").exists():
        return
    predictor = task3c.load_predictor_bundle(bundle)
    assert predictor["dynamic"].shape[1:] == (task3c.NODE_COUNT, 12)
    assert predictor["static"].shape == (task3c.NODE_COUNT, 10)
    assert len(predictor["weeks"]) == len(predictor["calendar"])
