import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import run_task3a_v2_audit as task3a  # noqa: E402


def _descriptor_map(frame):
    return frame.set_index(["week_index", "node_id"]).sort_index()


def test_front_features_use_only_prior_weeks():
    weeks = ["2024-W01", "2024-W02", "2024-W03", "2024-W04"]
    xy = np.array([[0.0, 0.0], [25000.0, 0.0], [50000.0, 0.0]])
    lat = np.array([10.0, 20.0, 30.0])
    positive = [np.array([0]), np.array([1]), np.array([], dtype=int), np.array([2])]
    frame = task3a.causal_front_descriptors(positive, xy, lat, weeks)
    current = _descriptor_map(frame)
    assert np.isnan(current.loc[(0, 0), "northmost_prior_latitude"])
    assert np.isclose(current.loc[(1, 2), "northmost_prior_latitude"], 10.0)
    assert np.isclose(current.loc[(2, 2), "northmost_prior_latitude"], 20.0)
    assert np.isclose(current.loc[(3, 2), "northmost_prior_latitude"], 20.0)


def test_future_data_mutation_does_not_change_prior_front_features():
    weeks = ["2024-W01", "2024-W02", "2024-W03", "2024-W04"]
    xy = np.array([[0.0, 0.0], [25000.0, 0.0], [50000.0, 0.0]])
    lat = np.array([10.0, 20.0, 30.0])
    original = [np.array([0]), np.array([1]), np.array([], dtype=int), np.array([2])]
    mutated = [np.array([0]), np.array([1]), np.array([2]), np.array([2])]
    original_frame = _descriptor_map(task3a.causal_front_descriptors(original, xy, lat, weeks))
    mutated_frame = _descriptor_map(task3a.causal_front_descriptors(mutated, xy, lat, weeks))
    prior_index = original_frame.index.get_level_values("week_index") < 2
    left = original_frame.loc[prior_index]
    right = mutated_frame.loc[prior_index]
    pd.testing.assert_frame_equal(left, right, check_exact=True)


def test_changing_week_t_response_does_not_change_week_t_predictor():
    weeks = ["2024-W01", "2024-W02", "2024-W03"]
    xy = np.array([[0.0, 0.0], [25000.0, 0.0], [50000.0, 0.0]])
    lat = np.array([10.0, 20.0, 30.0])
    original = [np.array([0]), np.array([1]), np.array([], dtype=int)]
    changed = [np.array([0]), np.array([1, 2]), np.array([], dtype=int)]
    left = _descriptor_map(task3a.causal_front_descriptors(original, xy, lat, weeks))
    right = _descriptor_map(task3a.causal_front_descriptors(changed, xy, lat, weeks))
    pd.testing.assert_frame_equal(left.loc[1], right.loc[1], check_exact=True)
    assert not np.array_equal(left.loc[2]["northmost_prior_latitude"], right.loc[2]["northmost_prior_latitude"])


def test_background_sampling_is_reproducible():
    nodes = pd.DataFrame({
        "lat": [10.0, 10.1, 20.0, 20.1],
        "lon": [-100.0, -99.9, -100.0, -99.9],
        "country_or_domain_region": ["Mexico", "Mexico", "U.S.-to-40N", "U.S.-to-40N"],
    })
    weeks = pd.DataFrame({"audit_week_index": [0, 1], "week": ["2024-W01", "2024-W02"]})
    counts = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], dtype=np.int32)
    data = {"nodes": nodes, "weeks": weeks, "counts": counts}
    histories = {"new_matrix": counts > 0}
    first, first_summary, first_weekly = task3a.build_background_design(data, histories)
    second, second_summary, second_weekly = task3a.build_background_design(data, histories)
    pd.testing.assert_frame_equal(first, second)
    pd.testing.assert_frame_equal(first_summary, second_summary)
    pd.testing.assert_frame_equal(first_weekly, second_weekly)


def test_v1_archive_manifest_schema_is_immutable_reference():
    output = Path("/project/disease_ecology/STGNN-output/v2_audit")
    manifest = output / "v1_archive" / "v1_artifact_archive_manifest.json"
    if not manifest.exists():
        return
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["status"] == "V1_ARTIFACTS_ARCHIVED_IMMUTABLE_REFERENCE"
    assert payload["former_terminal_status"] == "historical_evaluated_data"
    assert len(payload["artifacts"]) >= 8
    for artifact in payload["artifacts"]:
        path = Path(artifact["archive_path"])
        assert path.exists()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == artifact["sha256"]


def test_manifest_marks_audit_only_and_no_predictive_fit():
    output = Path("/project/disease_ecology/STGNN-output/v2_audit")
    manifest_path = output / "manifests" / "task3a_v2_audit_manifest.json"
    if not manifest_path.exists():
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["no_v2_predictive_model_fitted"] is True
    assert "AUDIT ONLY" in manifest["front_state_status"]
    assert manifest["former_terminal_status"] == "historical_evaluated_data"


def test_persisted_front_state_and_long_jump_schema():
    output = Path("/project/disease_ecology/STGNN-output/v2_audit")
    states_path = output / "front_states" / "front_state_node_week.parquet"
    long_jump_path = output / "front_states" / "first_positive_distance_summary.csv"
    if not states_path.exists() or not long_jump_path.exists():
        return
    states = pd.read_parquet(states_path)
    assert len(states) == 133 * 10037
    assert states["node_id"].nunique() == 10037
    assert states["week"].nunique() == 133
    assert states[["week_index", "node_id"]].duplicated().sum() == 0
    assert {"distance_to_any_prior_detection_km", "distance_to_previous4_detection_km", "distance_to_previous13_detection_km"}.issubset(states.columns)
    long_jump = pd.read_csv(long_jump_path)
    assert set(long_jump["metric"]) >= {
        "distance_to_nearest_any_prior_km",
        "distance_to_nearest_previous4_km",
        "distance_to_nearest_previous13_km",
    }
