import numpy as np
import pytest
import torch

from python.hurdle_zt_nb import (
    hurdle_predictions,
    log1mexp,
    nb_logpmf,
    positive_parameter,
    zt_nb_logpmf,
    zt_nb_positive_mean,
)


def test_log1mexp_is_finite_near_zero():
    values = torch.tensor([-1e-8, -1e-6, -0.1, -1.0, -10.0], dtype=torch.float64)
    assert torch.isfinite(log1mexp(values)).all()


def test_nb_mean_theta_parameterization_matches_scipy():
    scipy = pytest.importorskip("scipy.stats")
    mu = torch.tensor([0.2, 2.0, 20.0], dtype=torch.float64)
    theta = torch.tensor([0.05, 2.0, 100.0], dtype=torch.float64)
    y = torch.tensor([[0.0, 1.0, 5.0], [1.0, 3.0, 10.0], [2.0, 5.0, 20.0]], dtype=torch.float64)
    got = nb_logpmf(y, mu[:, None], theta[:, None]).numpy()
    expected = np.empty_like(got)
    for i in range(3):
        p = float(theta[i] / (theta[i] + mu[i]))
        expected[i] = scipy.nbinom.logpmf(y[i].numpy(), float(theta[i]), p)
    assert np.allclose(got, expected, atol=1e-10)


@pytest.mark.parametrize("mu", [1e-6, 0.2, 2.0, 1e3])
@pytest.mark.parametrize("theta", [0.05, 2.0, 100.0])
def test_zt_nb_normalizes(mu, theta):
    y = torch.arange(1, 5001, dtype=torch.float64)
    logp = zt_nb_logpmf(y, torch.tensor(mu, dtype=torch.float64), torch.tensor(theta, dtype=torch.float64))
    total = torch.exp(logp).sum().item()
    assert np.isfinite(total)
    required = 0.99 if mu <= 2.0 else 0.5
    assert total >= required


def test_zt_nb_gradients_are_finite():
    raw_mu = torch.tensor([-12.0, 0.0, 7.0], dtype=torch.float64, requires_grad=True)
    raw_theta = torch.tensor([-4.0, 1.0, 6.0], dtype=torch.float64, requires_grad=True)
    mu = positive_parameter(raw_mu).double()
    theta = positive_parameter(raw_theta).double()
    y = torch.tensor([1.0, 4.0, 30.0], dtype=torch.float64)
    loss = -zt_nb_logpmf(y, mu, theta).mean()
    loss.backward()
    assert torch.isfinite(loss)
    assert torch.isfinite(raw_mu.grad).all()
    assert torch.isfinite(raw_theta.grad).all()


def test_hurdle_expectation_is_probability_times_truncated_mean():
    logits = torch.tensor([-4.0, 0.0, 3.0], dtype=torch.float64)
    mu = torch.tensor([0.1, 2.0, 10.0], dtype=torch.float64)
    raw_theta = torch.tensor(1.0, dtype=torch.float64)
    out = hurdle_predictions(logits, mu, raw_theta)
    assert torch.allclose(out["unconditional_mean"], out["probability"] * out["conditional_positive_mean"])
    assert torch.all(out["conditional_positive_mean"] >= 1.0)

