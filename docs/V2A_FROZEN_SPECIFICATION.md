# STGNN-Hurdle-V2A Frozen Specification

## Status

`STGNN-Hurdle-V2A` is the development-frozen candidate selected in Task 3B. It is not a prospectively validated final production model.

Development specification freeze date: **2026-10-03**.

No post-freeze observation may alter this specification before the first prospective review.

## Estimand

The model estimates the probability and conditional positive count of a **recorded detection** in a node-week, given current environmental conditions, host covariates, seasonality, and strictly prior recorded-detection history.

It does not estimate true occupancy, true abundance, detection probability, reporting probability, or biological dispersal.

## Frozen model

- Model ID: `STGNN-Hurdle-V2A`
- Candidate: Task-3B M1 / V2-A
- Predictors: 30
- Penalty: `0.01`, coefficient vectors only
- Occurrence: Bernoulli/logistic
- Positive count: zero-truncated negative binomial
- Dispersion: one global learned theta
- Objective: `exact_joint_hurdle_nll`
- Domain: Mexico plus the existing U.S. footprint below 40°N
- Historical fit: 2025-W01 through 2026-W29

The 30-feature order is persisted in `model/v2a_feature_order.txt` and in the frozen specification manifest. It is the 24-feature V1 order followed by:

1. `distance_to_any_prior_positive_log1p`
2. `distance_to_prev4_positive_log1p`
3. `weeks_since_detection_within_50km_log1p`
4. `any_prior_positive_available`
5. `prev4_positive_available`
6. `detection_within_50km_ever_available`

M2 and its latitude feature are excluded.

## Front-state encoding

All front variables use only weeks before the forecast week. Distances are projected kilometres and use `log1p` before frozen development-fit standardization. Recency uses `log1p(weeks)`. Availability indicators remain 0/1 and unstandardized.

Unavailable distance values use the fixed maximum domain inter-node distance. Unavailable recency uses the fixed audit-window length plus one week. Availability indicators prevent those placeholders from being interpreted as measured distances.

## Development evidence and limitations

Task 3B selected penalty 0.01 for M1 using Folds 1–4 only. Folds 5–6 were historical pseudo-prospective and non-independent. The model improved first-ever-positive localization in Folds 1–4, while distance features remain highly collinear. No post-freeze data were used for specification changes.

The next independent evaluation must use predictions frozen before outcomes arriving after 2026-10-03 are ingested.
