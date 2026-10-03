import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import run_task2e_baselines as task2e  # noqa: E402


def test_terminal_holdout_guard_rejects_holdout_indices():
    splits = {"final_test": {"indices": [68, 69, 70]}}
    task2e.assert_development_only([0, 67], splits)
    try:
        task2e.assert_development_only([67, 68], splits)
    except RuntimeError as error:
        assert "terminal holdout" in str(error)
    else:
        raise AssertionError("terminal holdout index was accepted")


def test_fold_preprocessor_uses_training_weeks_only():
    data = {
        "dynamic": np.zeros((3, 2, 12), dtype=float),
        "static": np.zeros((2, 10), dtype=float),
        "calendar": np.zeros((3, 2), dtype=float),
    }
    data["dynamic"][1, :, :] = 10.0
    data["dynamic"][2, :, :] = 100.0
    prep = task2e.fit_preprocessor(data, [0, 1])
    assert prep["training_week_indices"] == [0, 1]
    x_eval = task2e.feature_matrix(data, [2])
    assert np.all(task2e.apply_preprocessor(x_eval, prep)[:, 0] > 10.0)


def test_degenerate_regional_metrics_are_flagged():
    counts = np.zeros((2, 2), dtype=int)
    probabilities = np.full((2, 2), 0.1)
    result = task2e.safe_metrics(
        counts,
        probabilities,
        np.ones((2, 2)),
        np.ones((2, 2)),
        1.0,
        0.0,
        "U.S.",
        1,
        "current_week_exact_hurdle",
    )
    assert result["roc_auc"] is None
    assert result["pr_auc"] is None
    assert "lacks both classes" in result["regional_metric_note"]


def test_advancement_classifier_reads_nested_metric_region():
    records = []
    for fold in range(1, 5):
        records.append(
            {
                "fold": fold,
                "model": "current_week_exact_hurdle",
                "metrics": {"region": "full_revised_domain", "brier_skill": 0.05},
                "fit_info": {"occurrence_success": True, "count_success": True},
            }
        )
    spatial = [{"region": "spatial_holdout_nodes", "brier_skill": 0.05}]
    decision, evidence = task2e.classify_advancement(records, spatial)
    assert decision == "ADVANCE"
    assert evidence["mean_temporal_brier_skill_positive"] is True
