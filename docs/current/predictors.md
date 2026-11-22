# Structured A3 predictors

This is the original frozen W16 predictor schema. The later W44 candidate
retains the same schema; it does not amend the W16 freeze. See the
[current status](status.md) for candidate and production artifact identities.

The exact 34-predictor order is recorded in [`predictors.csv`](predictors.csv)
and is checked against the frozen manifest during preflight. The predictors
include dynamic environmental variables, static livestock and landscape
covariates, calendar terms, and strictly causal detection-history variables.

Transformations are frozen: environmental variables use identity followed by
development-fit scaling; livestock densities and the two anthropogenic
variables use `log1p` followed by development-fit scaling; clay and the
water-retention contrast use identity followed by development-fit scaling;
calendar and availability indicators remain unchanged. History features may
only use observations from weeks strictly earlier than the forecast week.

Do not reorder predictors, reinterpret units, or add imputation during a
production run. Unexpected schema, CRS, node-order, resolution, or support
changes are preflight failures.
