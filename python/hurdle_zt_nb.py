"""Numerically stable Bernoulli + zero-truncated negative-binomial utilities.

The negative-binomial parameterization is by mean ``mu`` and shape ``theta``:
E[Y] = mu and Var[Y] = mu + mu**2 / theta.  The hurdle count component is
conditioned on Y > 0; its underlying NB mean is therefore not its conditional
positive-count mean.
"""

from __future__ import annotations

import math
from typing import Any

import torch
from torch import Tensor
from torch.nn import functional as F


EPS = 1e-8


def log1mexp(log_x: Tensor) -> Tensor:
    """Return log(1-exp(log_x)) for log_x <= 0 without cancellation."""
    if torch.any(log_x > 0):
        raise ValueError("log1mexp requires log_x <= 0")
    cutoff = -math.log(2.0)
    return torch.where(
        log_x < cutoff,
        torch.log1p(-torch.exp(log_x)),
        torch.log(-torch.expm1(log_x)),
    )


def positive_parameter(raw: Tensor, epsilon: float = EPS) -> Tensor:
    return F.softplus(raw) + epsilon


def nb_logpmf(y: Tensor, mu: Tensor, theta: Tensor) -> Tensor:
    """Analytic NB log PMF for integer y >= 0, mean mu, shape theta."""
    y = y.to(dtype=torch.get_default_dtype())
    mu = torch.clamp(mu, min=EPS)
    theta = torch.clamp(theta, min=EPS)
    log_theta_mu = torch.log(theta + mu)
    return (
        torch.lgamma(y + theta)
        - torch.lgamma(theta)
        - torch.lgamma(y + 1.0)
        + theta * (torch.log(theta) - log_theta_mu)
        + y * (torch.log(mu) - log_theta_mu)
    )


def nb_log_p0(mu: Tensor, theta: Tensor) -> Tensor:
    mu = torch.clamp(mu, min=EPS)
    theta = torch.clamp(theta, min=EPS)
    return theta * (torch.log(theta) - torch.log(theta + mu))


def zt_nb_logpmf(y: Tensor, mu: Tensor, theta: Tensor) -> Tensor:
    """Log PMF of NB(y | y > 0); caller must supply y >= 1."""
    if torch.any(y < 1):
        raise ValueError("zero-truncated NB is defined only for y >= 1")
    return nb_logpmf(y, mu, theta) - log1mexp(nb_log_p0(mu, theta))


def zt_nb_positive_mean(mu: Tensor, theta: Tensor) -> Tensor:
    """E[Y | Y > 0] for the underlying NB distribution."""
    p_positive = -torch.expm1(nb_log_p0(mu, theta))
    return torch.clamp(mu, min=EPS) / torch.clamp(p_positive, min=EPS)


def bernoulli_nll(logits: Tensor, presence: Tensor) -> Tensor:
    return F.binary_cross_entropy_with_logits(logits, presence.to(logits.dtype), reduction="none")


def hurdle_losses(
    logits: Tensor,
    mu: Tensor,
    raw_theta: Tensor,
    counts: Tensor,
    eligible: Tensor | None = None,
    positive_weight: float = 1.0,
) -> dict[str, Tensor]:
    """Return normalized optimization loss and exact observation likelihood.

    ``optimization_loss`` is the component-balanced training objective.  The
    exact joint hurdle NLL is separately returned as ``joint_nll`` and averages
    the observation-level likelihood over all eligible node-weeks.
    """
    if eligible is None:
        eligible = torch.ones_like(counts, dtype=torch.bool)
    counts = counts.to(logits.device)
    eligible = eligible.to(logits.device).bool()
    positive = counts > 0
    theta = positive_parameter(raw_theta)
    occurrence = bernoulli_nll(logits, positive)
    pos_count = torch.zeros_like(occurrence)
    if torch.any(positive & eligible):
        pos_count[positive] = -zt_nb_logpmf(counts[positive], mu[positive], theta)
    eligible_count = torch.clamp(eligible.sum(), min=1)
    positive_eligible = positive & eligible
    positive_count = torch.clamp(positive_eligible.sum(), min=1)
    opt = occurrence[eligible].mean() + positive_weight * pos_count[positive_eligible].mean()
    exact = torch.where(
        positive,
        -F.logsigmoid(logits) + pos_count,
        F.softplus(logits),
    )
    return {
        "optimization_loss": opt,
        "bernoulli_nll": occurrence[eligible].sum() / eligible_count,
        "zt_nb_nll": pos_count[positive_eligible].sum() / positive_count,
        "joint_nll": exact[eligible].mean(),
        "theta": theta,
        "positive_count": positive_eligible.sum().to(logits.dtype),
    }


def hurdle_predictions(logits: Tensor, mu: Tensor, raw_theta: Tensor) -> dict[str, Tensor]:
    theta = positive_parameter(raw_theta)
    p = torch.sigmoid(logits)
    positive_mean = zt_nb_positive_mean(mu, theta)
    return {
        "probability": p,
        "underlying_mu": mu,
        "theta": theta,
        "conditional_positive_mean": positive_mean,
        "unconditional_mean": p * positive_mean,
    }


def as_jsonable(value: Any) -> Any:
    if isinstance(value, Tensor):
        return value.detach().cpu().tolist()
    return value
