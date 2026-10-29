# P5A Issue-Time Environmental Proxy Validation

## I. Governance

SAE governance and the Atlas SSH policy were reviewed. Atlas execution used
the authorized WSL/Ubuntu `atlas-ssh` route. P5A remained within environmental
input-contract validation: no coefficients, P0 artifact, predictor identities,
transformations, P4 thresholds, or response definitions were changed. The
validated Atlas environment was not modified to install pytest.

## II. Canonical Starting State

P5 merge SHA: `650edd2397279a1a6a68dd89e42c724621d6da04`. P5 decision was
`P5_OPERATIONAL_CONTRACT_NOT_SUPPORTED` with production availability
`RETROSPECTIVE_ONLY`. P0 freeze verification passed. Frozen model:
`STRUCTURED_A3`; frozen artifact SHA-256:
`8a6a0a32a1a1e56f810b6aa1eafec5207dc3ac8d45cdf2270999f9721f080d1e`.

## III. P5A Repository State

P5A repository SHA during result generation: `e30f1b4d88be4bab26f66be6f47c0b70ed46937b`.
The exact P2 rolling-origin fit artifacts were reused; `no_model_refit` is
`True`. The P2 reference archive was preserved unchanged with hash
`918b33e80d352c080fcefb3d7b2a44dc29d0096b0b2e7dd6f5b017becc983170`. The P5A result root contains atomic
per-origin outputs and a completion ledger.

## IV. Proxy Definitions

| Contract | Definition |
|---|---|
| REALIZED_ENV | Unchanged P2 target-week environmental values and predictions. |
| E0_LAST_AVAILABLE | Persist the latest safely prior environmental feature state at `L(T)=T-1` across h=1,2,3. |
| E1_TRAILING3_MEAN | Mean of exactly the three prior feature states `T-1:T-3`, held across h=1,2,3. |
| E2_SEASONAL_EXPECTATION | Same ISO-week historical mean using only observations through `T-1`, requiring two prior seasonal cycles. |

## V. Predictor Applicability

All 12 P5 `RETROSPECTIVE_ONLY` environmental predictors received proxy
substitution. Already-lagged ERA5-Land soil-temperature and soil-water
features were treated as frozen feature values; they were not re-lagged or
re-transformed. The remaining 22 frozen predictors remained unchanged.

Eligible predictors: era5_mintemp, era5_soilmoist, era5_lai_low, agera5_relhum_min, era5land_tmean, era5land_soiltemp_l1_mean, era5land_soiltemp_l2_mean, era5land_soilwater_l1_mean, era5land_soilwater_l2_mean, era5land_surface_pressure_mean, era5land_lai_high_mean, era5land_lai_low_mean.

## VI. Rolling-Origin Execution

The P2 design was reused: 21 origins from
`2026-W16` through `2026-W36`, h=1,2,3, expanding-window fitted artifacts,
and identical paired P2 records. Completed origins: 21;
failed origins: none. E2 feasibility:
NOT_EVALUABLE_INSUFFICIENT_SEASONAL_ARCHIVE; available E2 rows: 0.

## VII. Environmental Proxy Accuracy

The proxy error analysis used only environmental observations through `T-1`.
Errors are proxy minus realized target-week feature values.

| proxy_id | horizon | family | n | mean_error | mae | rmse |
| --- | --- | --- | --- | --- | --- | --- |
| E0_LAST_AVAILABLE | 1 | humidity_pressure | 421554.0000 | -0.3998 | 3.4556 | 6.2374 |
| E0_LAST_AVAILABLE | 1 | moisture_water | 632331.0000 | 0.0004 | 0.0347 | 0.0518 |
| E0_LAST_AVAILABLE | 1 | temperature | 843108.0000 | -0.8425 | 2.0762 | 2.7576 |
| E0_LAST_AVAILABLE | 1 | vegetation | 632331.0000 | -0.0149 | 0.0335 | 0.0832 |
| E0_LAST_AVAILABLE | 2 | humidity_pressure | 421554.0000 | -0.5829 | 3.5250 | 6.3265 |
| E0_LAST_AVAILABLE | 2 | moisture_water | 632331.0000 | -0.0001 | 0.0372 | 0.0551 |
| E0_LAST_AVAILABLE | 2 | temperature | 843108.0000 | -1.1699 | 2.3163 | 3.0880 |
| E0_LAST_AVAILABLE | 2 | vegetation | 632331.0000 | -0.0193 | 0.0491 | 0.1203 |
| E0_LAST_AVAILABLE | 3 | humidity_pressure | 421554.0000 | -0.8192 | 3.8088 | 6.7793 |
| E0_LAST_AVAILABLE | 3 | moisture_water | 632331.0000 | -0.0007 | 0.0413 | 0.0600 |
| E0_LAST_AVAILABLE | 3 | temperature | 843108.0000 | -1.3999 | 2.8315 | 3.7737 |
| E0_LAST_AVAILABLE | 3 | vegetation | 632331.0000 | -0.0212 | 0.0644 | 0.1547 |
| E1_TRAILING3_MEAN | 1 | humidity_pressure | 421554.0000 | -0.4835 | 3.0712 | 5.4576 |
| E1_TRAILING3_MEAN | 1 | moisture_water | 632331.0000 | 0.0006 | 0.0341 | 0.0495 |
| E1_TRAILING3_MEAN | 1 | temperature | 843108.0000 | -1.2875 | 2.1446 | 2.8375 |
| E1_TRAILING3_MEAN | 1 | vegetation | 632331.0000 | -0.0263 | 0.0499 | 0.1232 |
| E1_TRAILING3_MEAN | 2 | humidity_pressure | 421554.0000 | -0.6666 | 3.2966 | 5.8758 |
| E1_TRAILING3_MEAN | 2 | moisture_water | 632331.0000 | 0.0000 | 0.0381 | 0.0549 |
| E1_TRAILING3_MEAN | 2 | temperature | 843108.0000 | -1.6149 | 2.5777 | 3.3678 |
| E1_TRAILING3_MEAN | 2 | vegetation | 632331.0000 | -0.0306 | 0.0649 | 0.1584 |
| E1_TRAILING3_MEAN | 3 | humidity_pressure | 421554.0000 | -0.9028 | 3.6654 | 6.6019 |
| E1_TRAILING3_MEAN | 3 | moisture_water | 632331.0000 | -0.0005 | 0.0424 | 0.0608 |
| E1_TRAILING3_MEAN | 3 | temperature | 843108.0000 | -1.8449 | 3.1184 | 4.0402 |
| E1_TRAILING3_MEAN | 3 | vegetation | 632331.0000 | -0.0326 | 0.0795 | 0.1908 |

## VIII. Occurrence and Count Performance

REALIZED_ENV is the unchanged P2 reference. The following table reports the
paired evaluation metrics for the realized condition and the two evaluable
proxies.

| proxy_id | horizon | n | positives | prevalence | brier | calibration_intercept | calibration_slope | log_loss | auroc | auprc | conditional_mae | conditional_bias | full_expected_mae | full_expected_bias |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| REALIZED_ENV | 1 | 210777 | 8948 | 0.0425 | 0.0281 | 0.0072 | 1.1407 | 0.0891 | 0.9623 | 0.4452 | 1.6797 | 0.5748 | 0.1433 | 0.0327 |
| REALIZED_ENV | 2 | 210777 | 9009 | 0.0427 | 0.0284 | -0.0161 | 1.1418 | 0.0905 | 0.9614 | 0.4414 | 1.7185 | 0.6546 | 0.1474 | 0.0383 |
| REALIZED_ENV | 3 | 210777 | 9102 | 0.0432 | 0.0288 | -0.0295 | 1.1461 | 0.0918 | 0.9607 | 0.4402 | 1.7698 | 0.7167 | 0.1522 | 0.0428 |
| E0_LAST_AVAILABLE | 1 | 210777 | 8948 | 0.0425 | 0.0280 | 0.0287 | 1.1406 | 0.0891 | 0.9623 | 0.4457 | 1.6413 | 0.5011 | 0.1408 | 0.0281 |
| E0_LAST_AVAILABLE | 2 | 210777 | 9009 | 0.0427 | 0.0284 | 0.0147 | 1.1432 | 0.0903 | 0.9614 | 0.4427 | 1.6625 | 0.5512 | 0.1437 | 0.0316 |
| E0_LAST_AVAILABLE | 3 | 210777 | 9102 | 0.0432 | 0.0287 | 0.0091 | 1.1459 | 0.0917 | 0.9606 | 0.4408 | 1.6970 | 0.5818 | 0.1473 | 0.0339 |
| E1_TRAILING3_MEAN | 1 | 210777 | 8948 | 0.0425 | 0.0280 | 0.0397 | 1.1408 | 0.0891 | 0.9623 | 0.4462 | 1.6246 | 0.4681 | 0.1397 | 0.0259 |
| E1_TRAILING3_MEAN | 2 | 210777 | 9009 | 0.0427 | 0.0284 | 0.0246 | 1.1421 | 0.0904 | 0.9613 | 0.4420 | 1.6450 | 0.5139 | 0.1425 | 0.0293 |
| E1_TRAILING3_MEAN | 3 | 210777 | 9102 | 0.0432 | 0.0288 | 0.0195 | 1.1452 | 0.0917 | 0.9606 | 0.4401 | 1.6770 | 0.5429 | 0.1461 | 0.0315 |

## IX. Proxy Degradation

Proxy-minus-realized effects were calculated on identical keys. Dependence-
aware target-week block bootstrap intervals use the prespecified 199
replicates and seed `20261029`; the machine-readable intervals are in
`metrics/bootstrap_intervals.csv`.

| proxy_id | horizon | metric | proxy_value | realized_value | difference_proxy_minus_realized |
| --- | --- | --- | --- | --- | --- |
| E0_LAST_AVAILABLE | 1 | brier | 0.0280 | 0.0281 | -0.0000 |
| E0_LAST_AVAILABLE | 1 | calibration_intercept | 0.0287 | 0.0072 | 0.0215 |
| E0_LAST_AVAILABLE | 1 | calibration_slope | 1.1406 | 1.1407 | -0.0001 |
| E0_LAST_AVAILABLE | 1 | log_loss | 0.0891 | 0.0891 | -0.0001 |
| E0_LAST_AVAILABLE | 1 | auprc | 0.4457 | 0.4452 | 0.0004 |
| E0_LAST_AVAILABLE | 1 | conditional_mae | 1.6413 | 1.6797 | -0.0384 |
| E0_LAST_AVAILABLE | 1 | conditional_bias | 0.5011 | 0.5748 | -0.0737 |
| E0_LAST_AVAILABLE | 1 | full_expected_mae | 0.1408 | 0.1433 | -0.0024 |
| E0_LAST_AVAILABLE | 1 | full_expected_bias | 0.0281 | 0.0327 | -0.0046 |
| E0_LAST_AVAILABLE | 2 | brier | 0.0284 | 0.0284 | -0.0000 |
| E0_LAST_AVAILABLE | 2 | calibration_intercept | 0.0147 | -0.0161 | 0.0309 |
| E0_LAST_AVAILABLE | 2 | calibration_slope | 1.1432 | 1.1418 | 0.0014 |
| E0_LAST_AVAILABLE | 2 | log_loss | 0.0903 | 0.0905 | -0.0001 |
| E0_LAST_AVAILABLE | 2 | auprc | 0.4427 | 0.4414 | 0.0013 |
| E0_LAST_AVAILABLE | 2 | conditional_mae | 1.6625 | 1.7185 | -0.0560 |
| E0_LAST_AVAILABLE | 2 | conditional_bias | 0.5512 | 0.6546 | -0.1034 |
| E0_LAST_AVAILABLE | 2 | full_expected_mae | 0.1437 | 0.1474 | -0.0037 |
| E0_LAST_AVAILABLE | 2 | full_expected_bias | 0.0316 | 0.0383 | -0.0067 |
| E0_LAST_AVAILABLE | 3 | brier | 0.0287 | 0.0288 | -0.0000 |
| E0_LAST_AVAILABLE | 3 | calibration_intercept | 0.0091 | -0.0295 | 0.0386 |
| E0_LAST_AVAILABLE | 3 | calibration_slope | 1.1459 | 1.1461 | -0.0002 |
| E0_LAST_AVAILABLE | 3 | log_loss | 0.0917 | 0.0918 | -0.0001 |
| E0_LAST_AVAILABLE | 3 | auprc | 0.4408 | 0.4402 | 0.0006 |
| E0_LAST_AVAILABLE | 3 | conditional_mae | 1.6970 | 1.7698 | -0.0728 |
| E0_LAST_AVAILABLE | 3 | conditional_bias | 0.5818 | 0.7167 | -0.1349 |
| E0_LAST_AVAILABLE | 3 | full_expected_mae | 0.1473 | 0.1522 | -0.0049 |
| E0_LAST_AVAILABLE | 3 | full_expected_bias | 0.0339 | 0.0428 | -0.0089 |
| E1_TRAILING3_MEAN | 1 | brier | 0.0280 | 0.0281 | -0.0000 |
| E1_TRAILING3_MEAN | 1 | calibration_intercept | 0.0397 | 0.0072 | 0.0325 |
| E1_TRAILING3_MEAN | 1 | calibration_slope | 1.1408 | 1.1407 | 0.0000 |
| E1_TRAILING3_MEAN | 1 | log_loss | 0.0891 | 0.0891 | -0.0001 |
| E1_TRAILING3_MEAN | 1 | auprc | 0.4462 | 0.4452 | 0.0009 |
| E1_TRAILING3_MEAN | 1 | conditional_mae | 1.6246 | 1.6797 | -0.0551 |
| E1_TRAILING3_MEAN | 1 | conditional_bias | 0.4681 | 0.5748 | -0.1067 |
| E1_TRAILING3_MEAN | 1 | full_expected_mae | 0.1397 | 0.1433 | -0.0036 |
| E1_TRAILING3_MEAN | 1 | full_expected_bias | 0.0259 | 0.0327 | -0.0068 |
| E1_TRAILING3_MEAN | 2 | brier | 0.0284 | 0.0284 | -0.0000 |
| E1_TRAILING3_MEAN | 2 | calibration_intercept | 0.0246 | -0.0161 | 0.0407 |
| E1_TRAILING3_MEAN | 2 | calibration_slope | 1.1421 | 1.1418 | 0.0004 |
| E1_TRAILING3_MEAN | 2 | log_loss | 0.0904 | 0.0905 | -0.0001 |
| E1_TRAILING3_MEAN | 2 | auprc | 0.4420 | 0.4414 | 0.0005 |
| E1_TRAILING3_MEAN | 2 | conditional_mae | 1.6450 | 1.7185 | -0.0735 |
| E1_TRAILING3_MEAN | 2 | conditional_bias | 0.5139 | 0.6546 | -0.1407 |
| E1_TRAILING3_MEAN | 2 | full_expected_mae | 0.1425 | 0.1474 | -0.0048 |
| E1_TRAILING3_MEAN | 2 | full_expected_bias | 0.0293 | 0.0383 | -0.0090 |
| E1_TRAILING3_MEAN | 3 | brier | 0.0288 | 0.0288 | -0.0000 |
| E1_TRAILING3_MEAN | 3 | calibration_intercept | 0.0195 | -0.0295 | 0.0490 |
| E1_TRAILING3_MEAN | 3 | calibration_slope | 1.1452 | 1.1461 | -0.0010 |
| E1_TRAILING3_MEAN | 3 | log_loss | 0.0917 | 0.0918 | -0.0001 |
| E1_TRAILING3_MEAN | 3 | auprc | 0.4401 | 0.4402 | -0.0001 |
| E1_TRAILING3_MEAN | 3 | conditional_mae | 1.6770 | 1.7698 | -0.0928 |
| E1_TRAILING3_MEAN | 3 | conditional_bias | 0.5429 | 0.7167 | -0.1738 |
| E1_TRAILING3_MEAN | 3 | full_expected_mae | 0.1461 | 0.1522 | -0.0062 |
| E1_TRAILING3_MEAN | 3 | full_expected_bias | 0.0315 | 0.0428 | -0.0113 |

## X. Count Performance

Conditional positive-count and full-hurdle expected-count MAE, RMSE, bias, and
observed/predicted totals are included in `occurrence_count_metrics.csv` and
the paired degradation table. No recalibration was performed.

## XI. Frontier Evaluation

Frontier effects were evaluated separately for previously occupied and
previously unoccupied cells. Newly detected frontier positives remain a
descriptive sparse-outcome subclass and were not pooled into established rows.

| proxy_id | horizon | frontier_class | n | positives | brier | calibration_intercept | calibration_slope | auprc |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| REALIZED_ENV | 1 | previously_occupied | 29369 | 8088 | 0.1743 | 0.0653 | 1.3021 | 0.4653 |
| REALIZED_ENV | 1 | previously_unoccupied | 181408 | 860 | 0.0044 | 1.1528 | 1.3853 | 0.1077 |
| REALIZED_ENV | 2 | previously_occupied | 29369 | 7935 | 0.1713 | 0.0594 | 1.3181 | 0.4663 |
| REALIZED_ENV | 2 | previously_unoccupied | 181408 | 1074 | 0.0053 | 0.3153 | 1.1714 | 0.1763 |
| REALIZED_ENV | 3 | previously_occupied | 29369 | 7825 | 0.1688 | 0.0601 | 1.3320 | 0.4694 |
| REALIZED_ENV | 3 | previously_unoccupied | 181408 | 1277 | 0.0061 | 0.0612 | 1.1141 | 0.2070 |
| E0_LAST_AVAILABLE | 1 | previously_occupied | 29369 | 8088 | 0.1742 | 0.0918 | 1.3055 | 0.4658 |
| E0_LAST_AVAILABLE | 1 | previously_unoccupied | 181408 | 860 | 0.0044 | 1.1994 | 1.3901 | 0.1085 |
| E0_LAST_AVAILABLE | 2 | previously_occupied | 29369 | 7935 | 0.1712 | 0.0973 | 1.3239 | 0.4676 |
| E0_LAST_AVAILABLE | 2 | previously_unoccupied | 181408 | 1074 | 0.0053 | 0.3654 | 1.1746 | 0.1774 |
| E0_LAST_AVAILABLE | 3 | previously_occupied | 29369 | 7825 | 0.1687 | 0.1061 | 1.3341 | 0.4697 |
| E0_LAST_AVAILABLE | 3 | previously_unoccupied | 181408 | 1277 | 0.0061 | 0.1146 | 1.1158 | 0.2076 |
| E1_TRAILING3_MEAN | 1 | previously_occupied | 29369 | 8088 | 0.1741 | 0.1071 | 1.3104 | 0.4664 |
| E1_TRAILING3_MEAN | 1 | previously_unoccupied | 181408 | 860 | 0.0044 | 1.2273 | 1.3936 | 0.1089 |
| E1_TRAILING3_MEAN | 2 | previously_occupied | 29369 | 7935 | 0.1712 | 0.1104 | 1.3254 | 0.4668 |
| E1_TRAILING3_MEAN | 2 | previously_unoccupied | 181408 | 1074 | 0.0053 | 0.3781 | 1.1723 | 0.1763 |
| E1_TRAILING3_MEAN | 3 | previously_occupied | 29369 | 7825 | 0.1687 | 0.1190 | 1.3349 | 0.4689 |
| E1_TRAILING3_MEAN | 3 | previously_unoccupied | 181408 | 1277 | 0.0061 | 0.1315 | 1.1174 | 0.2067 |

## XII. Support / Extrapolation

P4 support thresholds were consumed unchanged and support classes were
recalculated from each proxy predictor matrix against the P4 training-only
reference distribution.

| proxy_id | horizon | support_class | n | proportion |
| --- | --- | --- | --- | --- |
| E0_LAST_AVAILABLE | 1 | SUPPORTED | 78778 | 0.3738 |
| E0_LAST_AVAILABLE | 1 | CAUTION | 47374 | 0.2248 |
| E0_LAST_AVAILABLE | 1 | EXTRAPOLATIVE | 84625 | 0.4015 |
| E0_LAST_AVAILABLE | 2 | SUPPORTED | 72153 | 0.3423 |
| E0_LAST_AVAILABLE | 2 | CAUTION | 48040 | 0.2279 |
| E0_LAST_AVAILABLE | 2 | EXTRAPOLATIVE | 90584 | 0.4298 |
| E0_LAST_AVAILABLE | 3 | SUPPORTED | 63574 | 0.3016 |
| E0_LAST_AVAILABLE | 3 | CAUTION | 49150 | 0.2332 |
| E0_LAST_AVAILABLE | 3 | EXTRAPOLATIVE | 98053 | 0.4652 |
| E1_TRAILING3_MEAN | 1 | SUPPORTED | 87958 | 0.4173 |
| E1_TRAILING3_MEAN | 1 | CAUTION | 45033 | 0.2137 |
| E1_TRAILING3_MEAN | 1 | EXTRAPOLATIVE | 77786 | 0.3690 |
| E1_TRAILING3_MEAN | 2 | SUPPORTED | 80245 | 0.3807 |
| E1_TRAILING3_MEAN | 2 | CAUTION | 46488 | 0.2206 |
| E1_TRAILING3_MEAN | 2 | EXTRAPOLATIVE | 84044 | 0.3987 |
| E1_TRAILING3_MEAN | 3 | SUPPORTED | 70351 | 0.3338 |
| E1_TRAILING3_MEAN | 3 | CAUTION | 48525 | 0.2302 |
| E1_TRAILING3_MEAN | 3 | EXTRAPOLATIVE | 91901 | 0.4360 |
| REALIZED_ENV | 1 | SUPPORTED | 75475 | 0.3581 |
| REALIZED_ENV | 1 | CAUTION | 49266 | 0.2337 |
| REALIZED_ENV | 1 | EXTRAPOLATIVE | 86036 | 0.4082 |
| REALIZED_ENV | 2 | SUPPORTED | 70362 | 0.3338 |
| REALIZED_ENV | 2 | CAUTION | 49251 | 0.2337 |
| REALIZED_ENV | 2 | EXTRAPOLATIVE | 91164 | 0.4325 |
| REALIZED_ENV | 3 | SUPPORTED | 65825 | 0.3123 |
| REALIZED_ENV | 3 | CAUTION | 48781 | 0.2314 |
| REALIZED_ENV | 3 | EXTRAPOLATIVE | 96171 | 0.4563 |

Nonzero support transitions are recorded below:

| proxy_id | from_support_class | to_support_class | n |
| --- | --- | --- | --- |
| E0_LAST_AVAILABLE | SUPPORTED | SUPPORTED | 168093 |
| E0_LAST_AVAILABLE | SUPPORTED | CAUTION | 32583 |
| E0_LAST_AVAILABLE | SUPPORTED | EXTRAPOLATIVE | 10986 |
| E0_LAST_AVAILABLE | CAUTION | SUPPORTED | 34000 |
| E0_LAST_AVAILABLE | CAUTION | CAUTION | 89377 |
| E0_LAST_AVAILABLE | CAUTION | EXTRAPOLATIVE | 23921 |
| E0_LAST_AVAILABLE | EXTRAPOLATIVE | SUPPORTED | 12412 |
| E0_LAST_AVAILABLE | EXTRAPOLATIVE | CAUTION | 22604 |
| E0_LAST_AVAILABLE | EXTRAPOLATIVE | EXTRAPOLATIVE | 238355 |
| E1_TRAILING3_MEAN | SUPPORTED | SUPPORTED | 179206 |
| E1_TRAILING3_MEAN | SUPPORTED | CAUTION | 25965 |
| E1_TRAILING3_MEAN | SUPPORTED | EXTRAPOLATIVE | 6491 |
| E1_TRAILING3_MEAN | CAUTION | SUPPORTED | 41555 |
| E1_TRAILING3_MEAN | CAUTION | CAUTION | 87763 |
| E1_TRAILING3_MEAN | CAUTION | EXTRAPOLATIVE | 17980 |
| E1_TRAILING3_MEAN | EXTRAPOLATIVE | SUPPORTED | 17793 |
| E1_TRAILING3_MEAN | EXTRAPOLATIVE | CAUTION | 26318 |
| E1_TRAILING3_MEAN | EXTRAPOLATIVE | EXTRAPOLATIVE | 229260 |

## XIII. Proxy Decision

| proxy_id | classification | reason |
| --- | --- | --- |
| E0_LAST_AVAILABLE | OPERATIONALLY_ACCEPTABLE | Meets all prespecified strict degradation bounds at h=1,2,3. |
| E1_TRAILING3_MEAN | OPERATIONALLY_ACCEPTABLE | Meets all prespecified strict degradation bounds at h=1,2,3. |
| E2_SEASONAL_EXPECTATION | NOT_EVALUABLE | E2 requires two prior seasonal cycles; the validated archive supplies only one. |

The prespecified simplicity-first rule selected
`E0_LAST_AVAILABLE`. No proxy-window or threshold tuning was
performed after results were inspected.

## XIV. Production Availability Reclassification

Previous classification: `RETROSPECTIVE_ONLY`.

Updated classification: `PROSPECTIVE_READY_WITH_PROXY_LIMITATIONS`.

The selected proxy requires a source observation week no later than `T-1` and
a source vintage timestamp no later than the issue timestamp. P5's
non-environmental limitations remain explicit; proxy acceptance does not make
future environmental observations available or alter the frozen model.

## XV. Operational Contract Update

The separately versioned P5A proxy contract is recorded in
`manifests/proxy_contract.json`. Required future production provenance fields
are proxy ID, latest environmental observation week, trailing-window weeks,
source vintages, proxy generation timestamp, and input hashes. A production
implementation must fail on missing, future-vintage, or nonfinite proxy inputs.

## XVI. Artifacts

- `analysis/p5a_environmental_proxy/p5a_prespecification.md`
- `analysis/p5a_environmental_proxy/results/` compact machine-readable results
- `analysis/p5a_environmental_proxy/figures/P5A-1_proxy_design.svg` through
  `P5A-6_support_class_impact.svg` (or PNG equivalents when matplotlib is available)
- Atlas output root: `/project/disease_ecology/STGNN-output/p5a_environmental_proxy_20261029_v1`

## XVII. CI / PR / Merge

Hosted CI, PR, merge, post-merge freeze verification, and cleanup are recorded
in the task handoff. No production release tag was created.

## XVIII. P5A Decision

P5A_ENVIRONMENTAL_PROXY_SUPPORTED
