# Structured A3 formal production freeze

## Frozen object

The frozen primary production candidate is `STRUCTURED_A3`, also described as
Structured A3. It predicts the probability of a recorded *Cochliomyia
hominivorax* detection and the conditional positive detection count for each
canonical node-week. The response is a recorded detection process, not latent
occupancy, abundance, transmission, or organism movement.

The model is a penalized spatiotemporal hurdle regression with a
Bernoulli/logistic occurrence component and a zero-truncated negative-binomial
positive-count component. It has 34 predictors, penalty `0.01`, fixed theta
`0.7018903965556372`, and objective `exact_joint_hurdle_nll`. The domain is
10,037 canonical 25 × 25 km cells covering Mexico and the established United
States footprint south of 40°N, at weekly resolution.

The frozen fit uses 2025-W01 through 2026-W16: 68 weeks, 682,516 training
rows, and 9,546 positive node-weeks. The response/predictor bundle extends
through 2026-W29 for the historical evaluation boundary. The evaluation
period was not used for fitting, preprocessing, selection, or calibration.

## Predictors and provenance

The predictor order is the 34-column order in
[`docs/current/predictors.csv`](current/predictors.csv). It combines weekly
environmental fields, log-transformed livestock densities, livestock
imputation indicators, calendar terms, strictly prior detection-history/front
features, road density, nighttime illumination, clay, and the water-retention
contrast. Continuous predictors use development-fit mean/SD scaling; calendar
and availability/imputation indicators remain unscaled. Detection-history
features may use only weeks strictly earlier than the forecast week.

The exact machine-readable contract is
[`config/production_model_freeze.json`](../config/production_model_freeze.json).
It records the ordered predictor metadata, transformations, lag rules,
missing-data handling, training provenance, model parameters, artifact hashes,
software references, and immutability rules.

## Frozen artifacts and integrity

The compact frozen coefficient artifact is
[`final_a3_model.json`](../analysis/structured_a3_evaluation/results/final_a3_model.json).
The coefficient and scaling audit tables, immutable evaluation boundary,
controlled feature provenance, and predictor schema are listed and hashed in
the freeze manifest. Protected observations, large feature tables, and Atlas
production outputs remain external and are referenced by their authoritative
paths/manifests rather than copied into Git.

Verify the freeze from the repository root with:

```text
python scripts/verify_production_model_freeze.py
```

The verifier checks manifest parsing, required fields, artifact existence and
SHA-256 values, cross-file predictor/model metadata, convergence and response
contracts, environment references, source revision consistency, and a small
known-answer inference fixture. It does not train or refit a model. Success is
reported as `PRODUCTION_MODEL_FREEZE_VERIFIED`.

## Explicit exclusions

Flight-path predictors are not part of the frozen primary model. SIT predictors
are not part of the frozen primary model. Flight-path and SIT analyses remain
separate scientific work and do not alter P0.

The freeze also excludes any silent change to the response definition,
predictor order, transformations, lags, training cutoff, domain, penalty,
theta, objective, or stored coefficient artifact. Coefficients are conditional
model parameters and must not be interpreted as causal effects.

## Subsequent qualification

P1–P7 may evaluate the frozen candidate’s temporal, spatial, spatiotemporal,
frontier, calibration, robustness, uncertainty, extrapolation, operational,
monitoring, and publication behavior. They must not silently modify P0. A
material defect means that this candidate fails qualification; a replacement
must be developed and recorded as a separately identified challenger or new
model version.

This record formalizes a production candidate under qualification. It does not
create a release tag or claim independent prospective validation.
