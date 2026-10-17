"""Regression tests for horizon-general causal A3 front features."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import build_a3_front_features as front  # noqa: E402


def synthetic_frame(weeks: list[str], nodes: int = 2) -> pd.DataFrame:
    rows = []
    for week_index, week in enumerate(weeks):
        for node_id in range(nodes):
            rows.append({
                "week": week,
                "week_index": week_index,
                "model_node_id": node_id,
                "canonical_node_id": node_id + 10,
                "distance_to_any_prior_positive_km": 100.0,
                "distance_to_prev4_positive_km": 100.0,
                "weeks_since_detection_within_50km": 4.0,
                "any_prior_positive_available": 1,
                "prev4_positive_available": 1,
                "detection_within_50km_ever_available": 1,
                "distance_to_any_prior_positive_log1p": np.log1p(100.0),
                "distance_to_prev4_positive_log1p": np.log1p(100.0),
                "weeks_since_detection_within_50km_log1p": np.log1p(4.0),
                "history_cutoff_week": "2024-W52",
            })
    return pd.DataFrame(rows)


def test_extended_horizon_has_variable_row_contract():
    weeks = [f"2025-W{i:02d}" for i in range(1, 83)]
    frame = synthetic_frame(weeks)
    audit = front.validate_front_features(frame, weeks, node_count=2)
    assert audit["status"] == "PASS"
    assert audit["rows"] == 164
    assert audit["weeks"] == 82


def test_missing_history_cutoff_is_rejected():
    frame = synthetic_frame(["2025-W01", "2025-W02"])
    frame.loc[0, "history_cutoff_week"] = None
    with pytest.raises(RuntimeError, match="missing history cutoffs"):
        front.validate_front_features(frame, ["2025-W01", "2025-W02"], node_count=2)


def test_same_week_history_is_rejected():
    frame = synthetic_frame(["2025-W01", "2025-W02"])
    frame["history_cutoff_week"] = "2025-W02"
    with pytest.raises(RuntimeError, match="same-week/future"):
        front.validate_front_features(frame, ["2025-W01", "2025-W02"], node_count=2)


def test_front_builder_has_no_hard_coded_observation_provenance():
    source = Path(front.__file__).read_text(encoding="utf-8")
    assert "EXPECTED_SOURCE_SHA" not in source
    assert "EXPECTED_SOURCE_ROWS" not in source
    assert "2026-07-19" not in source
    assert "2026-W29" not in source
