# STRUCTURED_A3 W44 Q1 retrospective qualification

**Execution:** `COMPLETED`; **scientific decision:** `NOT_ASSIGNED` because outcome maturity is uncertified.
**Candidate status:** `CANDIDATE_READY_FOR_REVIEW_NOT_PRODUCTION_QUALIFIED`.

## Identity and execution

- Candidate model SHA-256: `b1a66a65efbb9a65f6a4c966044d2f87576ee7e6a1d1a294c0fb1855f684f53b`.
- Observation source SHA-256: `784168081cc1d3206f3537b8731994cbfc34be15be7c515fe06710d4ea9bdaac`.
- Origins: 26 (2026-W16 through 2026-W41); origin-horizon blocks: 78; fitted origin states: 26.
- Prediction archive rows: 2348658; SHA-256: `cb60c167879e176d549de5ce041630114e74294c496690282edb7ab43d7bde3e`.
- Atlas output root: `/project/disease_ecology/STGNN-output/structured_a3_2026w44_q1_retrospective_attempt02/predictions/rolling_origin_predictions.parquet`.
- Aggregate analysis runtime: 4794.1 seconds. Origin task runtimes are recorded in `fit_status_manifest.csv`.
- Frozen 34-predictor A3 specification, penalty, theta, and hurdle objective were retained. The full W44 candidate was not used to predict targets included in its fit; each origin has an expanding-window state ending at that origin.

## Information boundaries

This is a retrospective updated-vintage hindcast. Historical observation publication/revision times and environmental release timestamps were unavailable. E0 and E1 use the approved observation-week cutoff of T-1, but cannot establish that the underlying environmental files were actually published by each historical issue time.
Detection-history predictors are sourced from the first target week T+1, whose audited history cutoff is no later than T, and are held fixed across horizons 1–3. No post-origin history enters h=2 or h=3. The three environmental conditions are REALIZED_ENV (descriptive retrospective reference), E0_LAST_AVAILABLE (primary), and E1_TRAILING3_MEAN (sensitivity).

## Outcome maturity and scoring status

The response bundle contains every target week needed for the replay, but the source snapshot does not certify reporting completeness or outcome maturity. Therefore all predictive metrics below are descriptive revised-vintage diagnostics. No primary qualification scoring decision or production designation is assigned. Target-week eligibility is itemized in `scoring_eligibility.csv`.

## Primary E0 descriptive performance

| Horizon | Rows | Positives | Brier | Log loss | ROC-AUC | PR-AUC | Calibration intercept | Calibration slope | Conditional count MAE | Full expected count MAE |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 260962 | 11193 | 0.0287 | 0.0917 | 0.9601 | 0.4349 | 0.0095 | 1.1422 | 1.6550 | 0.1454 |
| 2 | 260962 | 11282 | 0.0294 | 0.0949 | 0.9571 | 0.4288 | -0.0540 | 1.0680 | 1.6644 | 0.1478 |
| 3 | 260962 | 11361 | 0.0301 | 0.0984 | 0.9537 | 0.4197 | -0.1176 | 0.9994 | 1.6677 | 0.1500 |

E1, REALIZED_ENV, region-specific results, existing-region × origin-time frontier strata, calibration bins, reference comparisons, target-week bootstrap intervals, paired proxy contrasts, P5A strict/bounded descriptive comparisons, and residual spatial summaries are in the adjacent aggregate CSV/JSON outputs. Interpret all metric estimates as descriptive until maturity is established. Geographic strata use unchanged canonical country/domain region labels; no additional northern Mexico–Texas boundary is introduced.

## Spatial residual diagnostics

The aggregate emitted a non-fatal NumPy RuntimeWarning: Mean of empty slice during pooled positive-count residual averaging. Positive-count residuals are undefined for nodes without observed positive counts; all-NaN node columns were therefore excluded from the pooled mean. The resulting finite pooled sample sizes were 1,871, 1,897, and 1,939 nodes for horizons 1, 2, and 3; pooled Moran I and permutation summaries were finite. This warning did not affect aggregation completion or other metrics.

Residuals were evaluated on the W44 Queen graph using the established Moran-I implementation. Target-week/horizon statistics are descriptive; pooled-by-horizon permutation checks use 199 permutations with seed 20261017. These are rolling-origin diagnostics and are not a spatial holdout or the fixed-W44 P1 post-freeze test.

## Limitations and decision

The Q1 origin-specific fits and forecasts completed with the approved origin/target design and no detected future-history use. The retrospective source vintage, unavailable release timestamps, and uncertified target maturity limit the scientific conclusion. Because mature outcome scoring eligibility cannot be established, Q1 predictive qualification is not assigned. The W44 full-fit candidate was not refitted; no production configuration change, promotion, Q2 uncertainty/support execution, or Q3 prospective execution occurred.

All row-level predictions, fitted origin states, logs, and coordinate-bearing diagnostics remain on Atlas. Aggregate report path: `/project/disease_ecology/STGNN-output/worktrees/structured-a3-2026w44-q1-retrospective/analysis/structured_a3_data_refresh_2026w44/qualification_execution/results/2026w44_q1_retrospective`.
<!-- Q1 Slurm resource reconciliation -->

## Slurm execution and resource reconciliation

The aggregate/diagnostic Slurm job 21299924 completed in 01:20:02 with batch MaxRSS 4,456,604 KiB (4.25 GiB); aggregate analysis runtime reported by the script was 4,794.1 seconds. Input preparation jobs 21299800 and 21299855 completed in 14 and 15 seconds, respectively, with MaxRSS 1,060,656 KiB and 1,044,604 KiB.

All 26 origin fits and all 78 origin-horizon blocks completed successfully. The pilot array was `21299859` for slots 0 and 25; the full remaining array was `21299867` for slots 1–24.
Origin task elapsed time ranged from 9 to 22 seconds; peak batch-step MaxRSS ranged from 611.3 to 763.1 MiB. Per-origin and per-horizon Slurm IDs, elapsed time, memory, target keys, and artifact hashes are recorded in `origin_horizon_execution_manifest.csv`.
Input preparation jobs: 21299800, 21299855. Successful pilot array: 21299859. Full origin array: 21299867. Aggregate job: 21299924.
The first pilot attempt used job array 21299809 and stopped on an execution-code metadata-key error after writing partial predictions. Its outputs remain preserved under the `attempt01` Atlas root and are excluded from this Q1 result. The successful pilot and full origins use the isolated `attempt02` root.

The Q1 outcome maturity limitation still applies: all performance metrics are descriptive, and no qualification decision is assigned.
