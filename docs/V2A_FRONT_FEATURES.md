# V2-A Causal Front Features

All V2-A front variables are predictors of week `t` and use only recorded detections from weeks `< t`. They are descriptive recorded-detection history variables, not latent biological front states.

## Primary features

1. `distance_to_any_prior_positive_km`: minimum projected distance to any node with a recorded positive in any earlier week.
2. `distance_to_prev4_positive_km`: minimum projected distance to any node positive in weeks `t-1` through `t-4`.
3. `weeks_since_detection_within_50km`: weeks since the most recent earlier recorded positive within 50 km.

The 50-km radius was authorized from the Task 3A descriptive audit and is not tuned in Task 3B. Distances are kilometres in the canonical projected coordinate system.

## Availability and transformations

Unavailable distance values are filled with one deterministic domain-scale distance: the projected bounding-box diagonal of the accepted prediction domain. Unavailable recency values are filled with the fixed audit-window length plus one. These placeholders are never used without their paired indicators:

- `any_prior_positive_available`;
- `prev4_positive_available`;
- `detection_within_50km_ever_available`.

Continuous front features are transformed with `log1p` and then standardized using only the training portion of each rolling fold. Availability indicators remain 0/1. The same deterministic rule is applied to all folds and is independent of outcomes in the validation period.

## Secondary ablation

M2 adds only `prior13_latitude_p95`, the 95th-percentile latitude of positive nodes from `t-1` through `t-13`, with an explicit availability indicator. No other latitude-front candidate is fitted.

## Leakage controls

The causal constructor is tested for: no current-week response influence, future-mutation invariance of earlier predictors, permitted influence only on later weeks, fixed node/week ordering, deterministic unavailable-history encoding, and exact rolling-origin boundaries. Machine-readable features are stored under `STGNN-output/v2_model/front_features/` with `history_cutoff_week`.

