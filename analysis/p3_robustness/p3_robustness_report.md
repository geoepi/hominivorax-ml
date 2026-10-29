# P3 Bounded Robustness and Sensitivity Analysis

## I. Governance

SAE governance and the repository execution policy were reviewed. The Atlas SSH policy was reviewed and Atlas access used the authorized direct WSL/Ubuntu `atlas-ssh` route. P3 remained within the approved bounded scope; no Level-3 specification change or authorization boundary was encountered.

## II. Canonical Starting State

Canonical `main` SHA: `ec6e951c63f7ec7fd252de5ddea6bb9772fea906`. P2 merge SHA: `ec6e951c63f7ec7fd252de5ddea6bb9772fea906`. The P0 freeze verifier passed and the frozen model SHA-256 remained `8a6a0a32a1a1e56f810b6aa1eafec5207dc3ac8d45cdf2270999f9721f080d1e`.

## III. P3 Repository State

Branch: `feature/p3-bounded-robustness`. Worktree: `/project/disease_ecology/STGNN-output/worktrees/p3-bounded-robustness-v1`. Implementation SHA: `4de0937c229edfa86da1fd5580cd816f0661681a`. The P2 archive contained `632331` immutable rows with the verified canonical hash. No P0/P2 artifact was modified.

## IV. Prespecified Sensitivity Design

The prespecification was committed before result generation. F0 retained the P1/P2 through-origin occupancy definition; F1 used recent eight-week occupancy; F2 used nearest prior detection with 25-km and 100-km grid-distance bands. Count strata were 1–2, 3–5, 6–10, and >=11, with deterministic top-5% and top-1% diagnostic exclusions. Spatial schemes were country/domain, latitude macroregions, and longitude macroregions; temporal schemes were individual target weeks and fixed four-week blocks. Initialization variants were canonical, zero-all, and deterministic perturbed on W16, W26, and W36.

## V. Frontier Sensitivity

All leakage and reproducibility checks passed. F0 h=1 classes had positive counts: previously_occupied=316; previously_occupied=316; previously_occupied=373; previously_occupied=375; previously_occupied=354; previously_occupied=376; previously_occupied=392; previously_occupied=388; previously_occupied=363; previously_occupied=408; previously_occupied=394; previously_occupied=387; previously_occupied=351; previously_occupied=413; previously_occupied=400; previously_occupied=413; previously_occupied=390; previously_occupied=423; previously_occupied=422; previously_occupied=388; previously_occupied=446; previously_unoccupied=45; previously_unoccupied=57; previously_unoccupied=36; previously_unoccupied=40; previously_unoccupied=39; previously_unoccupied=33; previously_unoccupied=39; previously_unoccupied=33; previously_unoccupied=27; previously_unoccupied=44; previously_unoccupied=39; previously_unoccupied=49; previously_unoccupied=33; previously_unoccupied=42; previously_unoccupied=60; previously_unoccupied=43; previously_unoccupied=42; previously_unoccupied=33; previously_unoccupied=44; previously_unoccupied=47; previously_unoccupied=35. F1 and F2 are reported separately in the machine-readable metrics, with no post-hoc pooling. The sparse-frontier qualification therefore remains materially unchanged, although class sample sizes and prevalence move with the definition.

## VI. Count Influence

The untrimmed P2 count metrics remain primary: conditional MAE=1.7229, conditional bias=0.6491, and observed/predicted ratio=0.7774. Count-stratum absolute, squared, and signed-error contributions are in `results/count_stratum_metrics.csv`; deterministic diagnostics are in `results/count_influence.csv`. The analysis characterizes rather than replaces the known count-process limitation.

## VII. Partition Sensitivity

Spatial and temporal regrouping completed across 105 metric rows. The broad regional/frontier qualification is not reversed by regrouping. These are summaries of frozen predictions and do not constitute a spatial refit or spatial holdout.

## VIII. Fit Stability

All 21 immutable P2 fit artifacts converged for both components. The coefficient extraction found 15 parameter-series with at least one sign transition; these are reported for interpretation rather than treated as causal effect changes. Initialization diagnostics completed 9 variant-origin rows with status `PASS`. Structured A3 has no latent graph-effect parameter, recorded as not applicable.

## IX. P1/P2 Limitation Tracking

| Limitation | P3 classification |
|---|---|
| P1_sparse_frontier_support | `ROBUST_LIMITATION` |
| P1_sparse_us_regional_support | `ROBUST_LIMITATION` |
| P1_count_process_bias | `BETTER_CHARACTERIZED` |
| P1_P2_evaluation_partition_boundary | `NOT_ADDRESSABLE_IN_P3` |
| P1_P2_fit_stability | `BETTER_CHARACTERIZED` |
| P2_retrospective_environmental_availability | `NOT_ADDRESSABLE_IN_P3` |

## X. Artifacts

- `analysis/p3_robustness/p3_prespecification.md`
- `analysis/p3_robustness/p3_robustness_report.md`
- `analysis/p3_robustness/results/` machine-readable metrics, provenance, limitation tracking, and decision record
- `analysis/p3_robustness/figures/` bounded P3-1 through P3-4 figure set
- Atlas output root: `/project/disease_ecology/STGNN-output/p3_robustness_20261029`

## XI. Atlas

WSL route compliance: PASS. P3 aggregate job: `21059814` with terminal status `COMPLETED`. P2 prediction archives and fit artifacts were reused; no historical P2 output root was overwritten.

## XII. CI / PR / Merge

P3 branch, hosted CI, PR, merge, post-merge validation, and cleanup are recorded in the final task handoff. No production release tag was created.

## XIII. P3 Decision

P3_ROBUSTNESS_SUPPORTED_WITH_LIMITATIONS
