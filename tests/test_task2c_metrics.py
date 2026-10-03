import numpy as np
import torch

from python.hurdle_zt_nb import hurdle_losses
from python.task2c_metrics import evaluate_predictions, exact_joint_identity


def test_exact_joint_nll_identity_matches_prevalence_weighted_components():
    counts = np.array([0, 0, 1, 2, 0, 4], dtype=np.int64)
    probability = np.array([0.02, 0.10, 0.20, 0.45, 0.05, 0.70])
    mu = np.array([0.5, 0.8, 1.2, 2.0, 0.6, 3.0])
    theta = 1.7
    positive_probability = -np.expm1(theta * (np.log(theta) - np.log(theta + mu)))
    conditional = mu / positive_probability
    explicit, weighted = exact_joint_identity(
        counts, probability, conditional, mu, theta
    )
    assert np.isclose(explicit, weighted, atol=1e-10)


def test_common_evaluator_rewards_probability_ranking_and_reports_skill():
    counts = np.array([0, 1, 0, 1], dtype=np.int64)
    good = evaluate_predictions(
        counts, np.array([0.01, 0.99, 0.02, 0.98]), np.ones(4), np.ones(4), 2.0
    )
    reversed_case = evaluate_predictions(
        counts, np.array([0.99, 0.01, 0.98, 0.02]), np.ones(4), np.ones(4), 2.0
    )
    assert good["pr_auc"] > reversed_case["pr_auc"]
    assert good["brier_skill"] > reversed_case["brier_skill"]
    assert len(good["reliability"]) >= 1


def test_training_objectives_are_distinct_and_finite():
    counts = torch.tensor([0.0, 1.0, 0.0, 3.0])
    logits = torch.tensor([-1.0, 0.2, -0.3, 0.8], requires_grad=True)
    mu = torch.tensor([0.5, 1.2, 0.7, 2.0], requires_grad=True)
    raw_theta = torch.tensor(0.5, requires_grad=True)
    outputs = hurdle_losses(logits, mu, raw_theta, counts)
    assert torch.isfinite(outputs["balanced_multitask_loss"])
    assert torch.isfinite(outputs["exact_joint_hurdle_nll"])
    assert not torch.allclose(
        outputs["balanced_multitask_loss"], outputs["exact_joint_hurdle_nll"]
    )
    outputs["exact_joint_hurdle_nll"].backward()
    assert all(
        parameter.grad is not None and torch.isfinite(parameter.grad).all()
        for parameter in (logits, mu, raw_theta)
    )
