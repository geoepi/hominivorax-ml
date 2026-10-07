# 002 — V2-A feature selection

## Question

Which non-neural predictor contract should be carried into structured A3 development?

## Decision

Freeze the 30-predictor V2-A/A0 contract: environmental variables, livestock densities and imputation indicators, calendar terms, and causal detection-history/front features.

## Evidence

The V2-A audit established the history/front availability contract and the development comparison selected the 30-feature reference. Front features use only observations from weeks strictly before the forecast week.

## Rejected alternatives

Same-week or future history features, latitude re-opening, and neural/GConvGRU candidates are not part of the current A0 reference.

## Provenance and status

Relevant history: `7c50c75`, `cda6f64`, `docs/V2A_FROZEN_SPECIFICATION.md`. Status: **frozen reference for A3**.
