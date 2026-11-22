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
- The W44 candidate source has no certified reporting-completeness statement;
  historical observation revisions remain unexplained. W44 Q1 target maturity
  is uncertified, so the retrospective metrics are descriptive and its
  scientific qualification decision is `NOT_ASSIGNED`.
- Point-level observations are strongly geographically clustered: the
  same-week nearest-neighbour median was about 1.45 km. This descriptive
  pattern is limited by opportunistic reporting, is not a movement or spatial
  covariance estimate, and did not justify a new A3 covariate.
- Structured A3 has no explicit latent CAR, Gaussian-process, or graph-neural
  spatial process. Its spatial-temporal information is carried by structured
  predictors, seasonality, and causal lagged history features.
- Residual spatial correlation persists and should remain a diagnostic and
  limitation. No requirement is established to eliminate it before use.
