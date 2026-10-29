# P4 Uncertainty and Extrapolation Assessment

## I. Governance

SAE governance and the repository execution policy were reviewed. The Atlas SSH policy was reviewed; Atlas execution used the authorized direct WSL/Ubuntu `atlas-ssh` route. P4 remained evaluation-only: the frozen model, P0 artifact, canonical P2 predictions, and qualification boundary were not modified.

## II. Canonical Starting State

Starting main/P3 merge SHA: `7aba3f3527324a13349d4355170d6ac81dcb8376`. The P0 freeze verifier passed before P4 execution. The frozen model SHA-256 remained `8a6a0a32a1a1e56f810b6aa1eafec5207dc3ac8d45cdf2270999f9721f080d1e`. The immutable P2 archive contained 632331 rows with hash `918b33e80d352c080fcefb3d7b2a44dc29d0096b0b2e7dd6f5b017becc983170`.

## III. P3 Reporting Correction

The P3 Frontier Sensitivity prose previously emitted one repeated class label for every origin. It was corrected to aggregate F0 h=1 positive counts across origins (`previously_occupied=8088; previously_unoccupied=860`), with a regression contract and generator guard. P3 machine-readable metrics, decision record, model artifact, and scientific decision were unchanged.

## IV. P4 Repository State

Branch: ``. Implementation SHA at Atlas execution: `a3a4e94b8909690ca3eef0a377fbce2c9017343a`. The P4 prespecification was committed before result generation. P4 outputs were written under `analysis/p4_uncertainty_extrapolation/` and the isolated Atlas root `/project/disease_ecology/STGNN-output/p4_uncertainty_extrapolation_20261029`.

## V. Environmental Novelty

Novelty uses nearest-neighbor Euclidean distance in the standardized frozen 34-predictor space. Scaling, range summaries, and support thresholds use only all-node training weeks 2025-W01 through 2026-W16. Training leave-one-out distance thresholds are fixed at q95 for caution and q99 for extrapolation; min/max and 1–99% range exceedances are preserved by predictor.

| Support class | Rows | Proportion |
|---|---:|---:|
| SUPPORTED | 211662 | 0.3347 |
| CAUTION | 147298 | 0.2329 |
| EXTRAPOLATIVE | 273371 | 0.4323 |

Continuous novelty, range exceedance causes, and representative-domain maps are machine-readable; environmental novelty is kept separate from sparse outcome support.

## VI. Predictive Uncertainty

Occurrence uncertainty is the canonical Bernoulli predictive variance p(1-p). Count uncertainty uses the exact frozen zero-truncated negative-binomial distribution and exact hurdle mixture quantiles; bootstrap model uncertainty is reported separately.

| Horizon | Nominal | Empirical full-hurdle coverage | Mean interval width |
|---:|---:|---:|---:|
| h=1 | 0.50 | 0.9781 | 0.1391 |
| h=1 | 0.50 | 0.8946 | 1.1033 |
| h=1 | 0.50 | 0.9985 | 0.0000 |
| h=1 | 0.50 | 0.8691 | 0.9278 |
| h=1 | 0.50 | 0.9887 | 0.0000 |
| h=1 | 0.50 | 0.8576 | 1.3425 |
| h=1 | 0.50 | 0.9990 | 0.0000 |
| h=1 | 0.80 | 0.9905 | 0.3978 |
| h=1 | 0.80 | 0.9655 | 3.1230 |
| h=1 | 0.80 | 0.9988 | 0.0026 |
| h=1 | 0.80 | 0.9554 | 2.6369 |
| h=1 | 0.80 | 0.9903 | 0.0166 |
| h=1 | 0.80 | 0.9585 | 3.6018 |
| h=1 | 0.80 | 0.9991 | 0.0004 |
| h=1 | 0.95 | 0.9974 | 0.8851 |
| h=1 | 0.95 | 0.9891 | 6.4892 |
| h=1 | 0.95 | 0.9998 | 0.0301 |
| h=1 | 0.95 | 0.9887 | 5.4950 |
| h=1 | 0.95 | 0.9972 | 0.2019 |
| h=1 | 0.95 | 0.9895 | 7.2212 |
| h=1 | 0.95 | 0.9997 | 0.0132 |
| h=2 | 0.50 | 0.9783 | 0.1454 |
| h=2 | 0.50 | 0.9013 | 1.1281 |
| h=2 | 0.50 | 0.9989 | 0.0001 |
| h=2 | 0.50 | 0.8723 | 0.9343 |
| h=2 | 0.50 | 0.9879 | 0.0148 |
| h=2 | 0.50 | 0.8641 | 1.4363 |
| h=2 | 0.50 | 0.9993 | 0.0000 |
| h=2 | 0.80 | 0.9908 | 0.4164 |
| h=2 | 0.80 | 0.9704 | 3.2210 |
| h=2 | 0.80 | 0.9991 | 0.0023 |
| h=2 | 0.80 | 0.9569 | 2.6718 |
| h=2 | 0.80 | 0.9904 | 0.0540 |
| h=2 | 0.80 | 0.9628 | 3.8238 |
| h=2 | 0.80 | 0.9994 | 0.0004 |
| h=2 | 0.95 | 0.9976 | 0.9281 |
| h=2 | 0.95 | 0.9905 | 6.7135 |
| h=2 | 0.95 | 0.9999 | 0.0267 |
| h=2 | 0.95 | 0.9893 | 5.5924 |
| h=2 | 0.95 | 0.9972 | 0.2765 |
| h=2 | 0.95 | 0.9926 | 7.6791 |
| h=2 | 0.95 | 0.9997 | 0.0100 |
| h=3 | 0.50 | 0.9784 | 0.1515 |
| h=3 | 0.50 | 0.9063 | 1.1468 |
| h=3 | 0.50 | 0.9992 | 0.0002 |
| h=3 | 0.50 | 0.8740 | 0.9398 |
| h=3 | 0.50 | 0.9873 | 0.0276 |
| h=3 | 0.50 | 0.8751 | 1.5562 |
| h=3 | 0.50 | 0.9996 | 0.0000 |
| h=3 | 0.80 | 0.9909 | 0.4354 |
| h=3 | 0.80 | 0.9716 | 3.2928 |
| h=3 | 0.80 | 0.9993 | 0.0018 |
| h=3 | 0.80 | 0.9579 | 2.7077 |
| h=3 | 0.80 | 0.9905 | 0.0877 |
| h=3 | 0.80 | 0.9649 | 4.1049 |
| h=3 | 0.80 | 0.9997 | 0.0002 |
| h=3 | 0.95 | 0.9976 | 0.9711 |
| h=3 | 0.95 | 0.9909 | 6.8926 |
| h=3 | 0.95 | 0.9999 | 0.0235 |
| h=3 | 0.95 | 0.9897 | 5.6853 |
| h=3 | 0.95 | 0.9973 | 0.3431 |
| h=3 | 0.95 | 0.9916 | 8.2272 |
| h=3 | 0.95 | 0.9999 | 0.0070 |

## VII. Model/Parameter Uncertainty

Dependence-aware bootstrap refits resampled complete training weeks with base seed 20261029, exact A3 fitting code, and no tuning. 120 of 120 slots succeeded; 0 failed; 100 successful replicates were used in the summaries. Canonical predictions remain primary.

Bootstrap diagnostics include failure causes, convergence, objectives, iterations, coefficient norms, coefficient-level stability summaries, and per-target SD/quantiles. A low-support target is not silently reclassified as supported because its bootstrap interval is narrow.

## VIII. Performance Versus Support

Occurrence and count metrics are reported by support class and fixed continuous novelty bin. The results characterize whether empirical reliability changes with support; they do not tune the support thresholds.

## IX. Frontier × Support

Frontier and established rows are crossed with supported versus low-support predictor conditions in `frontier_support_metrics.csv`. Sparse strata are shown without pooling. Environmental extrapolation can partially explain weak frontier predictions, but it does not remove the underlying sparse-frontier outcome limitation.

## X. U.S./Regional Support

U.S./other regional row counts, positive outcomes, novelty, support proportions, and performance are in `regional_support_summary.csv`. P4 does not claim to resolve sparse U.S./regional outcome support.

## XI. Production Support Flag

The deterministic input-only flag is `SUPPORTED`, `CAUTION`, or `EXTRAPOLATIVE`. It uses only the training reference, predictor ranges, and frozen standardized nearest-neighbor distance; no observed outcome is used to assign it. It is suitable as a diagnostic input to later operational work, subject to the limitations below.

## XII. P1–P3 Limitation Tracking

| Limitation | P4 classification |
|---|---|
| sparse_frontier_support | `ROBUST_LIMITATION` |
| sparse_us_regional_outcome_support | `ROBUST_LIMITATION` |
| count_process_bias | `BETTER_CHARACTERIZED` |
| retrospective_environmental_availability | `NOT_ADDRESSABLE_IN_P4` |
| no_true_refitted_spatial_holdout | `NOT_ADDRESSABLE_IN_P4` |
| numerical_stability | `BETTER_CHARACTERIZED` |
| environmental_extrapolation | `PARTIALLY_EXPLAINED_BY_EXTRAPOLATION` |

## XIII. Artifacts

- `analysis/p4_uncertainty_extrapolation/p4_prespecification.md`
- `analysis/p4_uncertainty_extrapolation/p4_uncertainty_extrapolation_report.md`
- `analysis/p4_uncertainty_extrapolation/results/` compact machine-readable summaries and provenance
- `analysis/p4_uncertainty_extrapolation/figures/` bounded P4-1 through P4-6 figure set
- Atlas full row-level products: `novelty_metrics.parquet`, `support_classifications.parquet`, `count_predictive_intervals.parquet`, and `model_uncertainty_summary.parquet` under the recorded P4 output root

## XIV. Atlas

WSL route compliance: PASS. Output root: `/project/disease_ecology/STGNN-output/p4_uncertainty_extrapolation_20261029`. Bootstrap slots were restartable by replicate ID; terminal status is recorded in `bootstrap_manifest.csv` and `bootstrap_fit_diagnostics.csv`.

## XV. CI / PR / Merge

Hosted CI, PR, merge, post-merge freeze verification, and cleanup are recorded in the task handoff. No production release tag was created.

## XVI. P4 Decision

P4_UNCERTAINTY_SUPPORT_SUPPORTED_WITH_LIMITATIONS
