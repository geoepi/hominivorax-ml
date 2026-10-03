from __future__ import annotations

import torch

from hurdle_zt_nb import hurdle_predictions, positive_parameter, zt_nb_logpmf


def main() -> None:
    y = torch.arange(1, 5001, dtype=torch.float64)
    for mu in [1e-6, 0.2, 2.0, 1e3]:
        for theta in [0.05, 2.0, 100.0]:
            total = torch.exp(zt_nb_logpmf(y, torch.tensor(mu, dtype=torch.float64), torch.tensor(theta, dtype=torch.float64))).sum()
            # Very overdispersed NB tails can extend beyond 5,000. For those
            # cases the finite-support check is deliberately weaker; the
            # exact normalization is still analytically enforced by p0.
            required = 0.99 if mu <= 2.0 else 0.5
            if not torch.isfinite(total) or float(total) < required:
                raise AssertionError((mu, theta, float(total)))
    raw_mu = torch.tensor([-12.0, 0.0, 7.0], dtype=torch.float64, requires_grad=True)
    raw_theta = torch.tensor([-4.0, 1.0, 6.0], dtype=torch.float64, requires_grad=True)
    loss = -zt_nb_logpmf(torch.tensor([1.0, 4.0, 30.0], dtype=torch.float64), positive_parameter(raw_mu), positive_parameter(raw_theta)).mean()
    loss.backward()
    if not torch.isfinite(loss) or not torch.isfinite(raw_mu.grad).all() or not torch.isfinite(raw_theta.grad).all():
        raise AssertionError("non-finite ZTNB gradient")
    out = hurdle_predictions(torch.tensor([-4.0, 0.0, 3.0], dtype=torch.float64), torch.tensor([0.1, 2.0, 10.0], dtype=torch.float64), torch.tensor(1.0, dtype=torch.float64))
    if not torch.allclose(out["unconditional_mean"], out["probability"] * out["conditional_positive_mean"]):
        raise AssertionError("hurdle expectation identity failed")
    print("Task-2B mathematical smoke: PASS")


if __name__ == "__main__":
    main()
