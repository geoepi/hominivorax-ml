"""Task 3D delayed-nowcast chronology and immutability contracts.

These tests use synthetic histories only.  They verify information availability
and artifact behavior; they are not predictive validation.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import run_v2a_prospective as task3d  # noqa: E402


def _history() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "week": ["2026-W01", "2026-W02", "2026-W02"],
            "model_node_id": [0, 1, 2],
            "observed_count": [1, 2, 1],
            "first_available_timestamp": [
                "2026-01-12T00:00:00+00:00",
                "2026-01-19T00:00:00+00:00",
                "2026-02-01T00:00:00+00:00",
            ],
        }
    )


def test_event_date_and_availability_date_are_both_required():
    history = _history()
    visible = task3d.history_visible_at_issue(
        history,
        "2026-W03",
        "2026-01-26T00:00:00+00:00",
        "availability_causal",
    )
    assert set(visible["model_node_id"]) == {0, 1}
    assert 2 not in set(visible["model_node_id"])


def test_delayed_outcome_is_invisible_before_availability_and_visible_after():
    history = pd.DataFrame(
        {
            "week": ["2026-W03"],
            "model_node_id": [4],
            "observed_count": [1],
            "first_available_timestamp": ["2026-01-29T00:00:00+00:00"],
        }
    )
    before = task3d.history_visible_at_issue(
        history, "2026-W04", "2026-01-28T23:59:59+00:00", "availability_causal"
    )
    after = task3d.history_visible_at_issue(
        history, "2026-W04", "2026-01-29T00:00:01+00:00", "availability_causal"
    )
    assert before.empty
    assert len(after) == 1


def test_late_backfill_cannot_mutate_a_prior_forecast_history():
    history = _history()
    issue = "2026-01-19T12:00:00+00:00"
    first = task3d.history_visible_at_issue(history, "2026-W03", issue, "availability_causal")
    later = task3d.history_visible_at_issue(
        history,
        "2026-W03",
        "2026-02-02T00:00:00+00:00",
        "availability_causal",
    )
    assert set(first["model_node_id"]) == {0, 1}
    assert set(later["model_node_id"]) == {0, 1, 2}
    # The archived pre-outcome history is the first result and is not rewritten.
    assert set(first["model_node_id"]) == {0, 1}


def test_front_state_availability_mode_requires_issue_timestamp():
    nodes = pd.DataFrame(
        {
            "x": np.zeros(task3d.NODE_COUNT),
            "y": np.zeros(task3d.NODE_COUNT),
            "lat": np.full(task3d.NODE_COUNT, 20.0),
        }
    )
    with np.testing.assert_raises(RuntimeError):
        task3d.front_state_for_week(
            _history(), "2026-W03", nodes, history_mode="availability_causal"
        )


def test_unavailable_history_encoding_is_finite_deterministic_and_nonzero():
    raw = np.array([np.nan, 25.0])
    available = np.isfinite(raw)
    first = np.where(available, raw, 1000.0)
    second = np.where(available, raw, 1000.0)
    assert np.array_equal(first, second)
    assert np.isfinite(first).all()
    assert first[0] != 0.0


def test_registry_schema_contains_task3d_availability_fields():
    with tempfile.TemporaryDirectory() as directory:
        frame = task3d.ensure_registry_schema(Path(directory))
        required = {
            "environment_available_timestamp",
            "forecast_issue_timestamp",
            "history_mode",
            "prospective_eligibility",
            "outcome_first_available_timestamp",
            "latest_score_version",
            "outcome_maturity",
        }
        assert required.issubset(frame.columns)


def test_score_version_and_timestamp_contracts():
    assert task3d.score_version(1) == 1
    assert task3d.timestamp_or_none("unknown") is None
    assert task3d.timestamp_or_none("2026-10-03T12:00:00Z") == "2026-10-03T12:00:00+00:00"
    with np.testing.assert_raises(ValueError):
        task3d.score_version(0)

