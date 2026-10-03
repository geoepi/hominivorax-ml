# Task 2B hurdle negative-binomial specification

Status: development-only implementation. The final 26-week test interval is
locked and is not scored by Task 2B.

For node `i` and week `t`, the response is the recorded detection count
`y_it`; the occurrence indicator is `z_it = I(y_it > 0)`. The occurrence head
outputs a logit and uses the stable Bernoulli-with-logits loss. The positive
head models `Y | Y > 0` with a zero-truncated negative-binomial distribution.

The underlying NB uses mean `mu > 0` and shape `theta > 0`:

```
E[Y] = mu
Var[Y] = mu + mu^2 / theta
```

The analytic log PMF is

```
lgamma(y + theta) - lgamma(theta) - lgamma(y + 1)
+ theta * (log(theta) - log(theta + mu))
+ y * (log(mu) - log(theta + mu))
```

The positive-count likelihood subtracts `log(1 - NB(0))`. This normalization
is evaluated with a stable `log1mexp` implementation using `expm1` near zero;
the code does not use the cancellation-prone `log(1-exp(log_p0))` directly.

The model has one learned global dispersion parameter:

```
theta = softplus(raw_theta) + 1e-8
```

The optimization objective is the mean Bernoulli NLL over eligible node-weeks
plus `lambda` times the mean ZTNB NLL over positive eligible node-weeks, with
`lambda = 1`. This component-balanced objective is reported separately from
the exact observation-level joint hurdle NLL, which uses `log(1-p)` for zero
counts and `log(p) + log ZTNB(y)` for positive counts.

The conditional positive expectation is `mu / (1 - NB(0))`, and the
unconditional expectation is `p * E[Y | Y > 0]`. The implementation therefore
does not multiply `p` by the underlying untruncated `mu`.

Mathematical tests cover agreement with SciPy's independent NB implementation,
normalization over a large positive support, small/large `mu`, small/large
`theta`, finite gradients, and the hurdle expectation identity.

## Atlas verification

The dependency-light mathematical smoke suite passed on Atlas, including the
analytic PMF checks, zero-truncation normalization, extreme-value cases,
finite-gradient checks, and the Monte Carlo expectation check. The matched GRU
and GConvGRU forward/backward smoke tests also passed with finite gradients.
The A100 mixed-precision smoke test passed with the likelihood calculations in
float32. Task 2B remains development-only; the final-test access guard rejects
predictive scoring in `evaluation_mode: development`.
