# Limitations

- The response is recorded detections, not organism abundance.
- Detection-history variables encode the evolving observed invasion/reporting
  state and are not direct measurements of latent abundance.
- Coefficients are conditional associations, not causal effects.
- Correlated predictors can share or redundantly encode information, so
  coefficient and permutation-importance interpretations require caution.
- Current full-fit weeks are operational fit data, not independent validation
  data.
- Prospective validation beyond the fitted horizon remains pending.
- Structured A3 has no explicit latent CAR, Gaussian-process, or graph-neural
  spatial process. Its spatial-temporal information is carried by structured
  predictors, seasonality, and causal lagged history features.
