# 004 — Controlled predictor augmentation

## Question

Can a small, prespecified set of anthropogenic and soil covariates be evaluated against the frozen A0 reference without changing the protocol?

## Decision

Evaluate four additions only: road density, nighttime illumination, clay at 0–15 cm, and the WV0033-minus-WV0010 water-retention contrast. Preserve the fixed penalty, fixed theta, response, domain, and development folds.

## Evidence

The controlled augmentation branch provides static aggregation, baseline gates, development-only preprocessing, and provenance. The final A3 manifest records 34 predictors and the exact static-source checksums.

## Rejected alternatives

Uncontrolled feature search, re-estimation of theta, response changes, and evaluation-period preprocessing are outside this decision.

## Provenance and status

Relevant branch/commit: `feature/controlled-predictor-augmentation` at `bd8346f`; final structured comparison at `93ecc92`. Status: **integrated into reconciliation branch**.
