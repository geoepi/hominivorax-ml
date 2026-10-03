import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import run_task2f_structured as task2f  # noqa: E402
from run_task2e_baselines import logistic_objective  # noqa: E402


def test_spatial_constant_and_isolated_node_invariants():
    edges = pd.DataFrame({"source_node": [0, 1], "target_node": [1, 0]})
    operator = task2f.build_self_normalized_operator(edges, 3)
    constant = task2f.spatial_mean(operator, np.ones((3, 2)))
    assert np.allclose(constant, 1.0)
    assert np.allclose(operator.toarray()[2], [0.0, 0.0, 1.0])


def test_antecedent_windows_use_only_previous_environmental_weeks():
    history_weeks = pd.DataFrame({"iso_week": [f"W{i:02d}" for i in range(20)]})
    response_weeks = pd.DataFrame({"iso_week": ["W13", "W14"]})
    history = np.arange(20, dtype=float).reshape(20, 1, 1)
    result = task2f.build_antecedents(history, history_weeks, response_weeks)
    assert result.shape == (2, 1, 3)
    assert np.allclose(result[0, 0], [12.0, 10.5, 6.0])
    assert np.allclose(result[1, 0], [13.0, 11.5, 7.0])


def test_feature_widths_and_order_are_pre_specified():
    assert [len(task2f.CANDIDATES[name]) for name in task2f.CANDIDATES] == [24, 41, 60, 77]
    assert task2f.CANDIDATES["Hurdle-Spatial"][24].endswith("_localmean")
    assert task2f.CANDIDATES["Hurdle-Temporal"][24].endswith("_lag1")
    assert task2f.CANDIDATES["Hurdle-Temporal"][-1].endswith("_prev13mean")


def test_fold_safe_scaling_leaves_indicators_and_calendar_natural():
    array = np.zeros((3, 2, 24), dtype=float)
    array[0, :, 0] = 0.0
    array[1, :, 0] = 2.0
    array[2, :, 0] = 100.0
    array[:, :, 17:24] = 7.0
    scaling = task2f.fit_scaling(array, [0, 1], None)
    assert scaling["training_week_indices"] == [0, 1]
    assert scaling["mean"][0] == 1.0
    assert scaling["standard_deviation"][17:24] == [1.0] * 7
    transformed = task2f.apply_scaling(array[2].reshape(2, 24), scaling)
    assert np.all(transformed[:, 0] > 50.0)
    assert np.allclose(transformed[:, 17:24], 7.0)


def test_l2_penalty_excludes_intercept():
    x = np.column_stack([np.ones(4), np.arange(4, dtype=float)])
    y = np.array([0.0, 0.0, 1.0, 1.0])
    beta = np.array([0.25, -0.5])
    base_loss, base_gradient = logistic_objective(beta, x, y)
    loss, gradient = task2f.regularized_logistic_objective(beta, x, y, 0.1)
    assert np.isclose(loss - base_loss, 0.5 * 0.1 * beta[1] ** 2)
    assert np.isclose(gradient[0], base_gradient[0])
    assert np.isclose(gradient[1] - base_gradient[1], 0.1 * beta[1])


def test_combined_masks_exclude_either_holdout_condition_from_training():
    train_pairs, eval_pairs = task2f.combined_pairs([0, 1], [2], np.array([0, 1]), np.array([2]), 3)
    train_set = {tuple(pair) for pair in train_pairs.tolist()}
    eval_set = {tuple(pair) for pair in eval_pairs.tolist()}
    assert train_set.isdisjoint(eval_set)
    assert (0, 2) in eval_set
    assert (2, 0) in eval_set
    assert (0, 0) in train_set


def test_terminal_guard_and_class_degenerate_metric_safeguard():
    task2f.assert_development_only([0, 67])
    try:
        task2f.assert_development_only([68])
    except RuntimeError:
        pass
    else:
        raise AssertionError("terminal holdout index was accepted")
    result = task2f.safe_metrics(
        np.zeros((2, 2), dtype=int),
        np.full((2, 2), 0.1),
        np.ones((2, 2)),
        np.ones((2, 2)),
        1.0,
        0.0,
        "U.S.",
        1,
        "Hurdle-Current",
    )
    assert result["pr_auc"] is None
    assert result["roc_auc"] is None
    assert "lacks both classes" in result["regional_metric_note"]
