# P2 Operational Rolling-Origin Nowcast Evaluation

## I. Governance

SAE governance, the repository execution-governance policy, and the Atlas SSH policy were reviewed. Atlas access used the authorized direct WSL/Ubuntu `atlas-ssh` route. The evaluation agent retained authority for implementation and diagnostics only; the P0 artifact, scientific specification, qualification criteria, and production promotion boundary were not changed.

## II. Canonical Starting State

Canonical `main` before P2: `1a8cba7ad910f6608fc664effdc1bb218b90b8ac`. P0 merge: `6a797c6b8fb7fb8cace20c21503ec86a0a5dd750`. P1 merge: `1a8cba7ad910f6608fc664effdc1bb218b90b8ac`. The shared production-freeze verifier passed with model `STRUCTURED_A3`, and the canonical model SHA-256 remained `8a6a0a32a1a1e56f810b6aa1eafec5207dc3ac8d45cdf2270999f9721f080d1e`.

## III. P1 Follow-up

P2 followed the exact P1 findings: sparse U.S./regional support; sparse frontier support; positive-count/count-process bias; the fact that P1 spatial transfer was a geographic diagnostic rather than a refitted spatial holdout; and the distinction between P1 extended temporal transport and normal operational use.

| P1 limitation | P2 diagnostic | Resolution classification |
|---|---|---|
| Sparse U.S./regional outcome support limits spatial transfer strength. | Horizon-by-region occurrence metrics and positive counts. | `PERSISTS` |
| Sparse frontier positive support limits frontier transfer strength. | Origin-time occupied versus previously-unoccupied strata and newly detected positive outcomes by horizon. | `PERSISTS` |
| Positive-count error/count-process bias prevents an unrestricted validity claim. | Conditional positive-count and full-hurdle calibration at h=1..3. | `PERSISTS` |
| P1 spatial transfer was a frozen-model geographic diagnostic, not a refitted spatial holdout. | Rolling origins preserve geography but do not create a spatial holdout. | `NOT_EVALUABLE_IN_P2` |
| P1 evaluated extended transport of a single frozen W16 artifact, beyond normal operational use. | Weekly expanding-window origins and paired h=1..3 degradation. | `BETTER_CHARACTERIZED` |

## IV. P2 Repository State

Implementation branch: `feature/p2-operational-nowcast`. Aggregate execution SHA: `c79bb8ec0a169f6833fda6c3b236e9179e65a3e2`; figure-render SHA: `bd9d72c8`.

Targeted P2 contract tests cover cutoff boundaries, expanding windows, no future response leakage, horizon assignment, feature-schema/hyperparameter identity, frontier leakage prevention, metric calculations, reference leakage, and provenance schemas. Existing P0/P1 tests remain preserved.

## V. Rolling-Origin Design

The primary design used weekly origins from `2026-W16` through `2026-W36`, an expanding training window `expanding 2025-W01 through origin T`, and horizons `h=1,2,3` only. The refresh supplied `91` complete weeks through `2026-W39`; `21` origins supported all three horizons. Each origin fit used only rows through its cutoff, the exact 34-predictor schema, penalty `0.01`, fixed theta `0.7018903965556372`, objective `exact_joint_hurdle_nll`, and the repository L-BFGS-B implementation. No feature selection or hyperparameter optimization occurred.

## VI. Predictor Availability

Because the validated environmental refresh does not provide release-time/revision-lag metadata, target-week environmental layers are conservatively classified as `RETROSPECTIVE_ONLY`. Static covariates are static; calendar terms are available as of issue; and detection-history features are derived from prior data with auditable cutoffs strictly before the target week. Therefore the result is labeled `RETROSPECTIVE_1_TO_3_WEEK_ROLLING_ORIGIN_EVALUATION`, not unrestricted operational pseudo-deployment.

## VII. Occurrence Calibration

The central calibration diagnostics are reported separately by horizon below. Intervals are percentile 95% intervals from target-week block bootstrap with all spatial nodes, origins, and overlapping-horizon records preserved within each sampled target week.

| Horizon | N | Positives | Prevalence | Brier | Calibration intercept | Calibration slope | Log loss | AUROC | AUPRC |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| h=1 | 210777 | 8948 | 0.0425 | 0.0281 | 0.0072 | 1.1407 | 0.0891 | 0.9623 | 0.4452 |
| h=2 | 210777 | 9009 | 0.0427 | 0.0284 | -0.0161 | 1.1418 | 0.0905 | 0.9614 | 0.4414 |
| h=3 | 210777 | 9102 | 0.0432 | 0.0288 | -0.0295 | 1.1461 | 0.0918 | 0.9607 | 0.4402 |

Bootstrap intervals for Brier, calibration intercept/slope, AUPRC, count error, and hurdle expectation error are in `results/bootstrap_intervals.csv`.

## VIII. Horizon Degradation

The h=1 versus h=3 comparison uses common target weeks only. The signed h=3 minus h=1 changes are:
- `brier`: `0.0001` (common weeks `2026-W19`–`2026-W37`).
- `calibration_intercept`: `-0.0212` (common weeks `2026-W19`–`2026-W37`).
- `calibration_slope`: `-0.0049` (common weeks `2026-W19`–`2026-W37`).
- `auprc`: `-0.0030` (common weeks `2026-W19`–`2026-W37`).
- `conditional_mae`: `0.0670` (common weeks `2026-W19`–`2026-W37`).
- `full_expected_mae`: `0.0041` (common weeks `2026-W19`–`2026-W37`).

No primary evaluation beyond three weeks was performed. Any longer-horizon behavior remains P1 extended temporal transport, not normal operational nowcasting.

## IX. Count Calibration

Conditional positive counts and the full hurdle expectation were evaluated for every horizon. The conditional metrics use only observed positive counts; the full-hurdle metrics include zeros. Fixed predicted-count ranges and upper-tail behavior are in `results/calibration_bins.csv` and `results/count_metrics.csv`.

| Horizon | Positive N | Conditional MAE | Conditional bias | Observed/predicted positive ratio | Full expected MAE | Full expected bias |
|---:|---:|---:|---:|---:|---:|---:|
| h=1 | 8948 | 1.6797 | 0.5748 | 0.7979 | 0.1433 | 0.0327 |
| h=2 | 9009 | 1.7185 | 0.6546 | 0.7755 | 0.1474 | 0.0383 |
| h=3 | 9102 | 1.7698 | 0.7167 | 0.7601 | 0.1522 | 0.0428 |

## X. Frontier Evaluation

Frontier classes are assigned at issuance using only occupancy through origin T. `previously_occupied` and `previously_unoccupied` are prediction-time strata. `newly_detected_frontier_positive` is reported only as a descriptive positive-outcome subclass of previously unoccupied rows; future detections never enter a prediction or fit.

| Horizon | Frontier class | N | Positives | Prevalence | Brier | Calibration slope | AUPRC |
|---:|---|---:|---:|---:|---:|---:|---:|
| h=1 | previously_occupied | 29369 | 8088 | 0.2754 | 0.1743 | 1.3021 | 0.4653 |
| h=1 | previously_unoccupied | 181408 | 860 | 0.0047 | 0.0044 | 1.3853 | 0.1077 |
| h=1 | newly_detected_frontier_positive | 860 | 860 | 1.0000 | 0.8705 | NA | NA |
| h=2 | previously_occupied | 29369 | 7935 | 0.2702 | 0.1713 | 1.3181 | 0.4663 |
| h=2 | previously_unoccupied | 181408 | 1074 | 0.0059 | 0.0053 | 1.1714 | 0.1763 |
| h=2 | newly_detected_frontier_positive | 1074 | 1074 | 1.0000 | 0.7757 | NA | NA |
| h=3 | previously_occupied | 29369 | 7825 | 0.2664 | 0.1688 | 1.3320 | 0.4694 |
| h=3 | previously_unoccupied | 181408 | 1277 | 0.0070 | 0.0061 | 1.1141 | 0.2070 |
| h=3 | newly_detected_frontier_positive | 1277 | 1277 | 1.0000 | 0.7140 | NA | NA |

The P1 frontier limitation is followed up explicitly and remains a limitation when frontier positive support is sparse; the report does not pool frontier and established strata to conceal that fact.

## XI. P1 Limitation Resolution

- `P1_sparse_us_support`: `PERSISTS` — U.S./domain-region positives across h=1..3: 123; P2 does not pool regions silently.
- `P1_sparse_frontier_support`: `PERSISTS` — Newly detected/frontier positive outcome rows across h=1..3: 3211.
- `P1_count_process_bias`: `PERSISTS` — P2 pooled conditional positive-count mean error: 0.649105.
- `P1_not_spatial_holdout`: `NOT_EVALUABLE_IN_P2` — P2 is an operational rolling-origin assessment; no spatial refit/holdout was introduced.
- `P1_extended_transport_boundary`: `BETTER_CHARACTERIZED` — P2 evaluated 21 weekly origins through three weeks; failed origins: 0.

## XII. Minimal Reference Assessment

Two and only two simple references were used: persistence from the observed state at origin T, and training-only same-ISO-week historical prevalence with a global training fallback only if a seasonal cell was unavailable. Both had complete coverage here because the validated response array has a value for every node and origin week. They are descriptive operational references, not alternative candidate models.

| Horizon | Reference | Coverage | A3 Brier minus reference | A3 log loss minus reference | A3 AUPRC minus reference |
|---:|---|---:|---:|---:|---:|
| h=1 | persistence | 1.0000 | -0.0770 | -2.8133 | 0.1922 |
| h=1 | historical_prevalence | 1.0000 | -0.0135 | -0.1094 | 0.4011 |
| h=2 | persistence | 1.0000 | -0.0784 | -2.8601 | 0.1983 |
| h=2 | historical_prevalence | 1.0000 | -0.0134 | -0.1081 | 0.3974 |
| h=3 | persistence | 1.0000 | -0.0795 | -2.8998 | 0.2051 |
| h=3 | historical_prevalence | 1.0000 | -0.0134 | -0.1080 | 0.3959 |

## XIII. Artifacts

Compact machine-readable results are stored under `analysis/p2_operational_nowcast/` in the repository. Large row-level prediction archives remain on the isolated Atlas output root and are described, hashed, and schema-checked by `results/prediction_archive_manifest.json`.

## XIV. Atlas Execution

Atlas used the authorized WSL route and environment `recorded in atlas_execution.json`. Output root: `/project/disease_ecology/STGNN-output/p2_operational_nowcast_20261029`. Job IDs and terminal states are recorded in `results/atlas_execution.json` after execution.

## XV. CI / PR / Merge

Hosted CI status and the PR/merge SHA are recorded in the final task handoff. If the repository reports no hosted workflow/status checks for this branch, that absence is recorded explicitly rather than treated as a passing hosted gate. Post-merge canonical-main verification is required before cleanup.

## XVI. P2 Decision

Decision: `P2_OPERATIONAL_NOWCAST_SUPPORTED_WITH_LIMITATIONS`. The fixed procedure was fit successfully at all eligible origins, but the conservative retrospective-only environmental availability classification and the P1 regional/frontier/count limitations prevent an unrestricted operational qualification. No recalibration or production-model modification was applied.

P2_OPERATIONAL_NOWCAST_SUPPORTED_WITH_LIMITATIONS
