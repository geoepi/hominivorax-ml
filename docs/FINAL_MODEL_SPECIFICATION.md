# Final frozen model specification

## Task 2G terminal evaluation

The primary model was frozen before terminal target values were unlocked. The
terminal evaluation is therefore a one-time future holdout assessment, not a
model-selection step.

| Component | Frozen specification |
| --- | --- |
| Model | `Hurdle-Current` |
| Domain | Revised retained domain, 10,037 nodes |
| Development responses | 2025-W01 through 2026-W16, 68 weeks |
| Terminal responses | 2026-W17 through 2026-W29, 13 weeks |
| Predictors | 24 |
| Regularization | penalty = 0 |
| Occurrence likelihood | Bernoulli/logistic |
| Positive-count likelihood | Zero-truncated negative binomial |
| Dispersion | One learned global theta |
| Objective | `exact_joint_hurdle_nll` |
| Terminal candidates excluded | Hurdle-Spatial, Hurdle-Temporal, Hurdle-Spatiotemporal, GRU, GConvGRU |

## Predictor order

The exact feature order is:

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

## Preprocessing

The twelve current-week environmental variables use identity transforms followed
by mean/std scaling fitted on the complete development period only. The five
livestock densities use `log1p` followed by development-fit preprocessing. The
five livestock imputation indicators remain unchanged 0/1 variables. The two
calendar variables remain unchanged. The fitted parameters are persisted in
`model/fitted_preprocessing.json`.

## Reproducibility record

The pre-evaluation freeze record is
`manifests/model_freeze_manifest.json`, with SHA-256
`d5787cf89e593dc1f70aa9cb60f6ca7f34160f63dac8dd12df491f7157a0895f`.
It records the source and dataset checksums, graph checksum, feature order,
periods, preprocessing, optimizer settings, fitted coefficients, and theta.
The fitted global theta is `0.9063853224209942`. Both optimizer fits reported
successful L-BFGS-B convergence with finite coefficients and finite positive
theta.

This specification must remain unchanged when interpreting the Task 2G
terminal results. Any later revision must be a separately labeled development
cycle that treats these terminal outcomes as previously observed data.
