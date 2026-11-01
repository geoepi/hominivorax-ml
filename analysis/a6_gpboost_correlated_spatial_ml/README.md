# A6 Correlated-Boosting Spatial ML Challenger

This directory contains the prespecified A6 GPBoost follow-up to A5B. It is a
`DEVELOPMENT_INFORMED_FOLLOWUP`, not independent validation and not a production
model. A6 tests whether an explicit spatiotemporal correlated residual process
adds value beyond an otherwise equivalent independent boosted residual mean.

Compact metrics, provenance, checksums, reports, and figure-source tables are
durable project artifacts. GPBoost model files, predictions, caches, logs, and
other large regenerable products are temporary 90-day artifacts under
`/90daydata/disease_ecology/hominivorax-ml/a6_gpboost_correlated_spatial_ml/`.

The shared Atlas environment is not modified. GPBoost 1.8.0 is installed in an
isolated environment under the temporary 90-day root when needed.
