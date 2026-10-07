# V2-A Estimand

V2-A models the probability and count of a **recorded detection** in a node-week, conditional on current environmental covariates, host covariates, season, and prior recorded-detection history. It does not estimate true insect occupancy, abundance, detection probability, reporting probability, or biological dispersal.

The primary model remains a hurdle model:

- Bernoulli/logistic occurrence for `P(recorded detection > 0)`;
- zero-truncated negative-binomial count conditional on a recorded positive;
- one learned global dispersion parameter `theta`;
- exact joint hurdle negative log likelihood;
- fold-specific development preprocessing;
- M0 penalty fixed at 0 and V2-A penalties restricted to `0`, `1e-4`, `1e-3`, and `1e-2`.

## Candidates

M0 is the faithfully reproduced `STGNN-Hurdle-V1` current-week model with 24 predictors. M1 is V2-A with 30 predictors: the 24 V1 predictors plus three causal continuous front-history features and three availability indicators. M2 is the secondary V2-A+Latitude ablation with M1 plus `prior13_latitude_p95` and its availability indicator.

The former V1 terminal observations, 2026-W17–2026-W29, are historical evaluated data. Rolling folds 1–4 are historical development folds. Folds 5–6 are historical pseudo-prospective, non-independent folds and cannot establish independent V2 generalization.

## Future evaluation

No currently available 2025–2026 observations qualify as an unseen V2 test. If a V2 specification is frozen, the first independent evaluation must use observations arriving after that freeze date.

