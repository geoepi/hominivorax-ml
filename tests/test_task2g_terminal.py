import hashlib
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import run_task2g_terminal as task2g  # noqa: E402


def test_frozen_primary_contract_is_exact_and_excludes_augmented_models():
    contract = task2g.feature_contract()
    assert contract["model"] == "Hurdle-Current"
    assert contract["predictor_count"] == 24
    assert contract["penalty"] == 0.0
    assert contract["objective"] == "exact_joint_hurdle_nll"
    assert len(contract["predictor_order"]) == 24
    assert "Hurdle-Spatiotemporal" in contract["excluded_terminal_candidates"]


def test_feature_order_and_primary_shape_guard():
    array = np.zeros((task2g.EXPECTED_RESPONSE_WEEKS, task2g.EXPECTED_NODE_COUNT, 24))
    task2g.assert_primary_array(array)
    assert task2g.CANDIDATES["Hurdle-Current"] == task2g.BASE_FEATURES


def test_development_only_scaling_and_terminal_indices():
    array = np.zeros((81, 2, 24), dtype=float)
    array[:68, :, 0] = np.arange(68)[:, None]
    array[:, :, 17:24] = 1.0
    scaling = task2g.fit_scaling(array, list(range(68)), None)
    assert scaling["training_week_indices"] == list(range(68))
    assert scaling["unscaled_feature_indices"] == list(range(17, 24))
    assert task2g.TERMINAL_INDICES == list(range(68, 81))


def test_terminal_prediction_schema_and_probability_bounds():
    nodes = pd.DataFrame({
        "canonical_node_id": [10, 11],
        "raster_cell": [100, 101],
        "lon": [-100.0, -99.0],
        "lat": [30.0, 31.0],
        "country_or_domain_region": ["Mexico", "U.S.-to-40N"],
    })
    weeks = pd.DataFrame({"iso_week": [f"2026-W{i:02d}" for i in range(1, 82)]})
    data = {"nodes": nodes, "weeks": weeks}
    counts = np.zeros((13, 2), dtype=int)
    p = np.full((13, 2), 0.25)
    conditional = np.full((13, 2), 2.0)
    mu = np.full((13, 2), 1.0)
    frame = task2g.terminal_prediction_frame(data, counts, p, conditional, mu, np.array(["", "TX"]))
    required = {
        "week", "node_id", "latitude", "longitude", "state", "region",
        "observed_count", "observed_presence", "predicted_occurrence_probability",
        "predicted_conditional_positive_mean", "predicted_unconditional_mean",
    }
    assert required.issubset(frame.columns)
    assert len(frame) == 26
    assert np.all((frame["predicted_occurrence_probability"] >= 0) & (frame["predicted_occurrence_probability"] <= 1))


def test_adaptive_calibration_has_observed_and_predicted_fields():
    rows = task2g.calibration_rows(
        np.asarray([[0.01, 0.02, 0.8, 0.9]]),
        np.asarray([[0, 1, 0, 1]]),
        "full_revised_domain",
        bins=2,
    )
    assert len(rows) == 2
    assert {"mean_predicted_probability", "observed_prevalence", "sample_count"}.issubset(rows[0])


def test_freeze_checksum_verification_is_independent_of_terminal_targets():
    with tempfile.TemporaryDirectory() as directory:
        output = Path(directory) / "terminal_evaluation"
        (output / "manifests").mkdir(parents=True)
        manifest = {
            "status": "frozen_before_terminal_unlock",
            "model_specification": {"model": "Hurdle-Current", "penalty": 0.0},
            "terminal_targets_accessed_before_freeze": False,
        }
        path = output / "manifests" / "model_freeze_manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        (output / "manifests" / "model_freeze_manifest.sha256").write_text(
            f"{digest}  model_freeze_manifest.json\n", encoding="utf-8"
        )
        checked, actual = task2g.verify_freeze(output)
        assert checked["status"] == "frozen_before_terminal_unlock"
        assert actual == digest


def test_persisted_terminal_output_schema_and_expectation_consistency():
    output = Path("/project/disease_ecology/STGNN-output/terminal_evaluation")
    prediction_path = output / "predictions" / "terminal_predictions.parquet"
    if not prediction_path.exists():
        return

    frame = pd.read_parquet(prediction_path)
    assert len(frame) == 13 * 10037
    required = {
        "week", "node_id", "latitude", "longitude", "state", "region",
        "observed_count", "observed_presence", "predicted_occurrence_probability",
        "predicted_conditional_positive_mean", "predicted_unconditional_mean",
    }
    assert required.issubset(frame.columns)
    assert set(frame["week"]) == {f"2026-W{i:02d}" for i in range(17, 30)}
    assert np.all((frame["predicted_occurrence_probability"] >= 0) &
                  (frame["predicted_occurrence_probability"] <= 1))
    assert np.all(frame["predicted_conditional_positive_mean"] > 0)
    assert np.all(frame["predicted_unconditional_mean"] >= 0)
    assert np.allclose(
        frame["predicted_unconditional_mean"],
        frame["predicted_occurrence_probability"] *
        frame["predicted_conditional_positive_mean"],
        rtol=1e-10,
        atol=1e-12,
    )
    assert np.array_equal(
        frame["observed_presence"].to_numpy(dtype=int),
        (frame["observed_count"].to_numpy(dtype=int) > 0).astype(int),
    )


def test_persisted_terminal_regional_and_us_partitions_are_consistent():
    output = Path("/project/disease_ecology/STGNN-output/terminal_evaluation")
    prediction_path = output / "predictions" / "terminal_predictions.parquet"
    regional_path = output / "regional" / "terminal_regional_metrics.csv"
    us_path = output / "us_transfer" / "terminal_us_positive_ranks.csv"
    us_summary_path = output / "us_transfer" / "terminal_us_summary.json"
    if not all(path.exists() for path in (prediction_path, regional_path, us_path, us_summary_path)):
        return

    frame = pd.read_parquet(prediction_path)
    regional = pd.read_csv(regional_path)
    us_ranks = pd.read_csv(us_path)
    us_summary = json.loads(us_summary_path.read_text(encoding="utf-8"))
    full = regional.loc[regional["region"] == "full_revised_domain"].iloc[0]
    regional_parts = regional.loc[regional["region"].isin(["Mexico", "United States"])]
    assert regional_parts["node_weeks"].sum() == full["node_weeks"]
    assert regional_parts["positive_node_weeks"].sum() == full["positive_node_weeks"]
    assert regional_parts["observed_total_detections"].sum() == full["observed_total_detections"]
    assert len(us_ranks) == us_summary["positive_node_weeks"]
    assert np.all(us_ranks["observed_count"] > 0)
    assert np.all((us_ranks["percentile_rank_among_us_nodes"] >= 0) &
                  (us_ranks["percentile_rank_among_us_nodes"] <= 100))
    assert np.all((us_ranks["percentile_rank_among_revised_domain_nodes"] >= 0) &
                  (us_ranks["percentile_rank_among_revised_domain_nodes"] <= 100))
    assert int((frame["region"] == "U.S.-to-40N").sum()) == us_summary["terminal_node_weeks"]


def test_persisted_terminal_reporting_outputs_have_required_shapes():
    output = Path("/project/disease_ecology/STGNN-output/terminal_evaluation")
    weekly_path = output / "metrics" / "terminal_weekly_metrics.csv"
    latitude_path = output / "metrics" / "terminal_latitude_metrics.csv"
    calibration_path = output / "metrics" / "terminal_calibration.csv"
    if not all(path.exists() for path in (weekly_path, latitude_path, calibration_path)):
        return

    weekly = pd.read_csv(weekly_path)
    latitude = pd.read_csv(latitude_path)
    calibration = pd.read_csv(calibration_path)
    assert len(weekly) == 13
    assert set(weekly["week"]) == {f"2026-W{i:02d}" for i in range(17, 30)}
    assert set(latitude["latitude_band"]) == {"<20N", "20-25N", "25-30N", "30-35N", "35-40N"}
    assert len(latitude) == 13 * 5
    assert {"region", "adaptive_bin", "mean_predicted_probability", "observed_prevalence", "sample_count"}.issubset(calibration.columns)
    assert set(calibration["region"]) >= {"full_revised_domain", "Mexico", "United States"}
    assert np.all(calibration["sample_count"] > 0)
