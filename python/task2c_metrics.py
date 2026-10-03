"""Authoritative development evaluator for Task 2C.

All Task-2A and Task-2B comparison metrics pass through this module.  It uses
average precision for PR-AUC, adaptive quantile calibration bins, and explicit
node-week masks.  It never accesses the locked final-test targets.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy.special import gammaln
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score


EPS = 1e-8


def _masked(
    counts: np.ndarray,
    probability: np.ndarray,
    conditional_mean: np.ndarray,
    underlying_mu: np.ndarray | None,
    mask: np.ndarray | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray | None]:
    y = np.asarray(counts).astype(np.int64)
    p = np.asarray(probability, dtype=np.float64)
    conditional = np.asarray(conditional_mean, dtype=np.float64)
    mu = None if underlying_mu is None else np.asarray(underlying_mu, dtype=np.float64)
    if mask is None:
        selected = np.ones(y.shape, dtype=bool)
    else:
        selected = np.asarray(mask, dtype=bool)
        if selected.shape != y.shape:
            raise ValueError(f"mask shape {selected.shape} does not match target shape {y.shape}")
    if p.shape != y.shape or conditional.shape != y.shape or (mu is not None and mu.shape != y.shape):
        raise ValueError("prediction and target shapes must agree")
    return y[selected].reshape(-1), p[selected].reshape(-1), conditional[selected].reshape(-1), None if mu is None else mu[selected].reshape(-1)


def _calibration(p: np.ndarray, positive: np.ndarray) -> tuple[float | None, float | None]:
    if np.unique(positive).size != 2:
        return None, None
    clipped = np.clip(p, EPS, 1 - EPS)
    model = LogisticRegression(C=1e6, solver="lbfgs", max_iter=200)
    model.fit(np.log(clipped / (1 - clipped)).reshape(-1, 1), positive.astype(np.int8))
    return float(model.intercept_[0]), float(model.coef_[0, 0])


def _reliability(p: np.ndarray, positive: np.ndarray, bins: int = 10) -> list[dict[str, float | int]]:
    edges = np.unique(np.quantile(p, np.linspace(0, 1, bins + 1)))
    result: list[dict[str, float | int]] = []
    for index, (low, high) in enumerate(zip(edges[:-1], edges[1:])):
        selected = (p >= low) & ((p <= high) if index == len(edges) - 2 else (p < high))
        if selected.any():
            result.append({
                "lower": float(low), "upper": float(high), "n": int(selected.sum()),
                "mean_predicted": float(p[selected].mean()),
                "observed_fraction": float(positive[selected].mean()),
            })
    return result


def _distribution(p: np.ndarray, positive: np.ndarray) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for label, selected in [("zeros", ~positive), ("positives", positive)]:
        values = p[selected]
        result[label] = {
            "n": int(values.size),
            "mean": float(values.mean()) if values.size else None,
            "median": float(np.median(values)) if values.size else None,
            "quantiles": {f"p{q:g}": float(np.quantile(values, q / 100)) for q in [5, 25, 75, 95, 99]} if values.size else {},
        }
    if positive.any() and (~positive).any():
        result["mean_positive_minus_zero"] = float(p[positive].mean() - p[~positive].mean())
        result["mean_positive_to_zero_ratio"] = float(p[positive].mean() / max(p[~positive].mean(), EPS))
    else:
        result["mean_positive_minus_zero"] = None
        result["mean_positive_to_zero_ratio"] = None
    return result


def _nb_logpmf(y: np.ndarray, mu: np.ndarray, theta: float) -> np.ndarray:
    theta = max(float(theta), EPS)
    mu = np.maximum(mu, EPS)
    y = y.astype(np.float64)
    log_denom = np.log(theta + mu)
    return (gammaln(y + theta) - gammaln(theta) - gammaln(y + 1)
            + theta * (np.log(theta) - log_denom)
            + y * (np.log(mu) - log_denom))


def evaluate_predictions(
    counts: np.ndarray,
    probability: np.ndarray,
    conditional_mean: np.ndarray,
    underlying_mu: np.ndarray | None = None,
    theta: float | None = None,
    mask: np.ndarray | None = None,
    training_prevalence: float | None = None,
    count_score_family: str = "zt_nb",
) -> dict[str, Any]:
    """Evaluate one masked node-week prediction set.

    ``conditional_mean`` is the predicted E[Y | Y>0].  If ``underlying_mu``
    and ``theta`` are supplied, ZTNB and exact joint hurdle likelihoods are
    calculated from the underlying NB parameterization.  Baselines may pass
    their fitted NB mean as ``underlying_mu``; the family is recorded so that
    post-hoc common scoring is not confused with the training specification.
    """
    y, p, conditional, mu = _masked(counts, probability, conditional_mean, underlying_mu, mask)
    if y.size == 0:
        raise ValueError("cannot evaluate an empty mask")
    p = np.clip(p, EPS, 1 - EPS)
    positive = y > 0
    observed_prevalence = float(positive.mean())
    train_prev = observed_prevalence if training_prevalence is None else float(training_prevalence)
    null_brier = train_prev * train_prev * (1 - observed_prevalence) + (1 - train_prev) ** 2 * observed_prevalence
    intercept, slope = _calibration(p, positive)
    result: dict[str, Any] = {
        "n_node_weeks": int(y.size),
        "observed_prevalence": observed_prevalence,
        "training_prevalence": train_prev,
        "mean_predicted_probability": float(p.mean()),
        "bernoulli_nll": float(log_loss(positive.astype(np.int8), p, labels=[0, 1])),
        "brier": float(brier_score_loss(positive.astype(np.int8), p)),
        "brier_null": float(null_brier),
        "brier_skill": float(1 - brier_score_loss(positive.astype(np.int8), p) / max(null_brier, EPS)),
        "pr_auc": float(average_precision_score(positive.astype(np.int8), p)),
        "pr_auc_over_prevalence": float(average_precision_score(positive.astype(np.int8), p) / max(observed_prevalence, EPS)),
        "roc_auc": float(roc_auc_score(positive.astype(np.int8), p)) if np.unique(positive).size == 2 else None,
        "calibration_intercept": intercept,
        "calibration_slope": slope,
        "reliability": _reliability(p, positive),
        "probability_distribution": _distribution(p, positive),
        "count_score_family": count_score_family,
        "all_cell_mae": float(np.mean(np.abs(y - p * conditional))),
        "all_cell_rmse": float(np.sqrt(np.mean((y - p * conditional) ** 2))),
        "mean_observed_count": float(y.mean()),
        "mean_predicted_count": float(np.mean(p * conditional)),
    }
    if positive.any():
        result.update({
            "positive_count_mae": float(np.mean(np.abs(y[positive] - conditional[positive]))),
            "positive_count_rmse": float(np.sqrt(np.mean((y[positive] - conditional[positive]) ** 2))),
            "positive_mean_observed": float(y[positive].mean()),
            "positive_mean_predicted": float(conditional[positive].mean()),
            "positive_count_variance": float(np.var(y[positive])),
            "positive_count_variance_over_mean": float(np.var(y[positive]) / max(np.mean(y[positive]), EPS)),
        })
    else:
        result.update({"positive_count_mae": None, "positive_count_rmse": None, "positive_mean_observed": None, "positive_mean_predicted": None, "positive_count_variance": None, "positive_count_variance_over_mean": None})
    if mu is not None and theta is not None and positive.any():
        theta = max(float(theta), EPS)
        mu = np.maximum(mu, EPS)
        log_p0 = theta * (np.log(theta) - np.log(theta + mu))
        positive_probability = -np.expm1(log_p0)
        zt_logpmf = _nb_logpmf(y[positive], mu[positive], theta) - np.log(np.maximum(positive_probability[positive], EPS))
        joint = np.where(positive, -np.log(p) - np.where(positive, 0.0, 0.0), -np.log1p(-p))
        joint[positive] = -np.log(p[positive]) - zt_logpmf
        result.update({
            "theta": theta,
            "zt_nb_nll": float(-zt_logpmf.mean()),
            "joint_hurdle_nll": float(joint.mean()),
            "conditional_mean_from_underlying": float(np.mean(mu[positive] / np.maximum(positive_probability[positive], EPS))),
        })
    else:
        result.update({"theta": theta, "zt_nb_nll": None, "joint_hurdle_nll": None, "conditional_mean_from_underlying": None})
    return result


def exact_joint_identity(
    counts: np.ndarray,
    probability: np.ndarray,
    conditional_mean: np.ndarray,
    underlying_mu: np.ndarray,
    theta: float,
    mask: np.ndarray | None = None,
) -> tuple[float, float]:
    """Return explicit joint NLL and prevalence-weighted component NLL."""
    result = evaluate_predictions(counts, probability, conditional_mean, underlying_mu, theta, mask)
    y, p, _, mu = _masked(counts, probability, conditional_mean, underlying_mu, mask)
    positive = y > 0
    theta = max(float(theta), EPS)
    log_p0 = theta * (np.log(theta) - np.log(theta + np.maximum(mu, EPS)))
    ppositive = -np.expm1(log_p0)
    zt = _nb_logpmf(y[positive], mu[positive], theta) - np.log(np.maximum(ppositive[positive], EPS))
    explicit_nll = (float(np.sum(-np.log(p[positive]) - zt)) + float(np.sum(-np.log1p(-p[~positive])))) / y.size
    weighted = float(result["bernoulli_nll"] + positive.mean() * result["zt_nb_nll"])
    return explicit_nll, weighted
