# Current frozen Structured A3 model specification

> **CURRENT FROZEN SUPPORTED SPECIFICATION**

This document is authoritative for the supported Structured A3 workflow. It
supersedes earlier documents that describe the 24-predictor Hurdle-Current or
V2-A-only specifications. Those documents remain historical records.

## Model family and response

- Model family: structured hurdle model.
- Response: weekly insect count per revised-domain node, with occurrence defined as `Y > 0` and positive counts modeled conditionally on `Y > 0`.
- Occurrence likelihood: Bernoulli/logistic.
- Positive-count likelihood: zero-truncated negative binomial.
- Objective: `exact_joint_hurdle_nll`.
- Dispersion: fixed `theta = 0.7018903965556372`.
- Regularization penalty: `0.01`.
- Predictor count: 34.

## Spatial and temporal domain

The domain contains 10,037 canonical 25 × 25 km cells covering Mexico and the United States south of 40°N. The temporal resolution is weekly. The development response bundle spans 2025-W01 through 2026-W29; fitting uses only 2025-W01 through 2026-W16.

## Exact predictor order

1. `era5_mintemp`
2. `era5_soilmoist`
3. `era5_lai_low`
4. `agera5_relhum_min`
5. `era5land_tmean`
6. `era5land_soiltemp_l1_mean`
7. `era5land_soiltemp_l2_mean`
8. `era5land_soilwater_l1_mean`
9. `era5land_soilwater_l2_mean`
10. `era5land_surface_pressure_mean`
11. `era5land_lai_high_mean`
12. `era5land_lai_low_mean`
13. `cattle_density`
14. `goat_density`
15. `sheep_density`
16. `horse_density`
17. `pig_density`
18. `cattle_density_imputed`
19. `goat_density_imputed`
20. `sheep_density_imputed`
21. `horse_density_imputed`
22. `pig_density_imputed`
23. `week_sin`
24. `week_cos`
25. `distance_to_any_prior_positive_log1p`
26. `distance_to_prev4_positive_log1p`
27. `weeks_since_detection_within_50km_log1p`
28. `any_prior_positive_available`
29. `prev4_positive_available`
30. `detection_within_50km_ever_available`
31. `road_density`
32. `night_illumination`
33. `clay_0_15`
34. `water_difference_wv0033_minus_wv0010_0_15`

Predictors 1–30 are the frozen V2-A/A0 reference. Predictors 31–34 are the frozen A3 additions.

## Transformations and preprocessing

- Environmental and front-history continuous features use the source contract and development-only mean/standard-deviation scaling.
- Livestock densities use `log1p`; livestock imputation indicators remain unchanged binary indicators.
- Calendar variables remain unchanged.
- Road density and nighttime illumination use `log1p`.
- Clay and the water-retention contrast use identity transforms.
- Availability indicators remain unchanged binary indicators.
- All fitted means and standard deviations are computed from the 68 development weeks only. Evaluation-period responses and predictor summaries are not used for preprocessing, fitting, calibration, or selection.

## Development and evaluation protocol

- Development fitting period: 2025-W01–2026-W16, 68 weeks.
- Development comparison: F1–F4 only; A0 and A3 each completed four fixed-theta fits.
- Selection status: A3 improved the recorded development comparison metrics and the STRUCTURED A3 development specification was frozen.
- Historical exposed holdout: 2026-W17–2026-W29, including the previously visible F5/F6 horizon; it is not an independent prospective claim.
- Independent prospective evaluation: not yet available. Later source observations extend to 2026-W31, but complete A3 predictor support ends at 2026-W29 and the later source snapshot predates the freeze.

## Causality rule

Detection-history/front variables may use observations from weeks strictly earlier than the forecast week `t`. Same-week and future observations are prohibited. The evaluation audit records zero same-week/future history uses and zero missing history cutoffs for the canonical front artifact.

## Reproducibility and provenance

The final development decision is recorded in `analysis/structured_a3_final_comparison/results/structured_a3_final_manifest.json`. The evaluation boundary is frozen in `analysis/structured_a3_evaluation/results/frozen_a3_evaluation_manifest.json` with SHA-256 `9d7bc7b9ce41263064104aa933e75771b2b918ed853e4e34145db83c3a2c8f61`.

The canonical implementation and artifact paths are mapped in
`docs/history/repository_reconciliation/canonical_component_map.csv` and
`docs/current/data_artifact_map.md`.

## Known limitations

- Historical exposed holdout support does not establish independent prospective validity.
- Complete A3 predictor support is not available after 2026-W29.
- Neural and graph/GConvGRU pathways were evaluated diagnostically and are not supported as the current production-development path.
- The release-facing production launcher is documented in `docs/current/atlas.md`.
