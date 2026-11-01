# A6 GPBoost correlated-residual challenger

A6 is a `DEVELOPMENT_INFORMED_FOLLOWUP`, not independent validation or a
production change. It evaluates three fixed occurrence candidates using the
established 34-predictor A3 design and an A3 occurrence linear-predictor
offset:

- `A6-GB-IID`: boosted residual mean only;
- `A6-GPB-S`: boosted residual mean plus a fixed-shape Matérn spatial GP;
- `A6-GPB-ST`: boosted residual mean plus a fixed-shape Matérn space-time GP.

The GPBoost likelihood is Bernoulli-logit, Vecchia uses 20 training neighbors
and 40 prediction neighbors, predictions use
`order_obs_first_cond_obs_only`, and Matérn smoothness is fixed at 1.5.
The first GPBoost coordinate is the integer week offset; projected canonical
Albers x/y coordinates are in kilometres. Coordinates are covariance inputs,
never ordinary tree features.

The exact A3 positive-count component is retained for primary hurdle metrics.
The A6-GPB-ST plus immutable A4-S positive-count component is descriptive only
when no fold-specific A4-S artifact exists and is excluded from selection.
All fitting uses only 2025-W01 through 2026-W16 and the established F1-F4
forward temporal folds. Outer validation outcomes are never used for early
stopping, covariance estimation, prediction conditioning, or model choice.
