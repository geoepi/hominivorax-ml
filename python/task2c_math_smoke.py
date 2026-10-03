#!/usr/bin/env python3
"""Dependency-light Task-2C likelihood and metric audit tests."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hurdle_zt_nb import hurdle_losses, positive_parameter
from task2c_metrics import exact_joint_identity, evaluate_predictions


def main() -> int:
    torch.manual_seed(20261002)
    counts = torch.tensor([0., 0., 1., 2., 4., 0.])
    logits = torch.tensor([-4., -1., 0., 1., 2., -2.], requires_grad=True)
    mu = torch.tensor([1., 1., .5, 1., 2., 1.], requires_grad=True)
    raw_theta = torch.tensor(.3, requires_grad=True)
    eligible = torch.tensor([True, True, True, True, True, False])
    losses = hurdle_losses(logits, mu, raw_theta, counts, eligible, positive_weight=1.)
    for name in ["balanced_multitask_loss", "exact_joint_hurdle_nll", "bernoulli_nll", "zt_nb_nll"]:
        assert torch.isfinite(losses[name]), name
    losses["exact_joint_hurdle_nll"].backward(retain_graph=True)
    assert all(parameter.grad is not None and torch.isfinite(parameter.grad).all() for parameter in [logits, mu, raw_theta])
    probability = torch.sigmoid(logits.detach()).numpy()
    mu_np = mu.detach().numpy()
    theta = float(positive_parameter(raw_theta.detach()))
    explicit, weighted = exact_joint_identity(counts.numpy(), probability, mu_np / np.maximum(1 - np.exp(theta * (np.log(theta) - np.log(theta + mu_np))), 1e-8), mu_np, theta, eligible.numpy())
    assert abs(explicit - weighted) < 1e-6, (explicit, weighted)
    metrics = evaluate_predictions(counts.numpy(), probability, mu_np, mu_np, theta, eligible.numpy(), training_prevalence=.2)
    assert metrics["n_node_weeks"] == 5
    assert np.isfinite(metrics["joint_hurdle_nll"])
    perfect = evaluate_predictions(np.array([0, 1, 0, 1]), np.array([.01, .99, .02, .98]), np.ones(4), np.ones(4), 2.)
    reversed_case = evaluate_predictions(np.array([0, 1, 0, 1]), np.array([.99, .01, .98, .02]), np.ones(4), np.ones(4), 2.)
    assert perfect["pr_auc"] > reversed_case["pr_auc"]
    print("Task-2C mathematical/evaluator smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
