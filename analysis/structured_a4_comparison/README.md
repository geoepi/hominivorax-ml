# Structured A4 architecture comparison

Final architecture decision: **HOLD — NO A4 CANDIDATE JUSTIFIED**.

This was a controlled architecture-comparison phase on pre-W30 blocked folds. It did not deploy A4, change production A3, or use the authoritative prospective period 2026-W30 through 2026-W39 for fitting, tuning, scoring, or selection.

## Executive Summary

The comparison targeted the diagnosed A3 failure modes: residual spatial dependence, systematic positive-count mismatch, deterioration in extrapolative history regimes, and possible observation/reporting heterogeneity. The tested candidates were frozen A3, A4-S (graph-Laplacian residual effects), A4-C (training-fold positive-count dispersion revision), A4-SC (spatial plus count), and A4-O (bounded observation/reporting sensitivity only).

A4-S and A4-SC improved several structural diagnostics without materially degrading mean or worst-fold occurrence discrimination. A4-S reduced positive-count residual Moran's I from 0.3634 to 0.2852 and mean count bias from 0.7976 to 0.5003; A4-SC reduced them to 0.2801 and 0.4786. However, the U.S. positive-risk ranking endpoint was not estimable in the pre-W30 development folds because there were zero U.S. positive node-weeks. Under the pre-registered guardrails, candidates cannot advance without evidence that the primary U.S. ranking endpoint is preserved.

Therefore the single architecture decision is **HOLD — NO A4 CANDIDATE JUSTIFIED**. This is a decision to collect/authorize a development period with U.S. positives or an appropriate transfer-validation design, not a claim that A4-S or A4-SC have no structural benefit.

Recorded detections are not treated as true latent abundance. Recorded count mismatch may arise from the latent count model, the observation/reporting process, or both. U.S. outcomes are additionally confounded by stronger SIT suppression, which can reduce recorded occurrence, counts, and northward progression. SIT covariates were intentionally excluded and are reserved as `RESERVED_FUTURE_INTERVENTION_LAYER`.

## Methods

### Frozen scope and temporal design

- Canonical baseline: `fae2d0f08c72a018338b9359543cfd2b88d7d8e2`.
- Development data: 2025-W01 through 2026-W16, 68 weeks.
- Fold 1: train 2025-W01–W26; validate 2025-W27–W39.
- Fold 2: train 2025-W01–W39; validate 2025-W40–W52.
- Fold 3: train 2025-W01–W52; validate 2026-W01–W08.
- Fold 4: train 2025-W01–2026-W08; validate 2026-W09–W16.
- Excluded exactly: 2026-W30 through 2026-W39.
- Node domain: 10,037 nodes; 34 predictors.
- A3 occurrence coefficients, scaling, theta `0.7018903965556372`, and penalty `0.01` were frozen.
- No random row-wise cross-validation or future leakage was used.

A3 was independently reproduced before A4 interpretation. All required fold-level anchor metrics passed at tolerance `1e-9`; the maximum absolute difference was approximately `1.33e-15`. The reproduction table is `results/a3_baseline_reproduction.csv`.

Metrics include Brier skill, PR-AUC, ROC-AUC, calibration intercept/slope, zero-truncated negative-binomial positive-count NLL, joint hurdle NLL, count MAE/RMSE/bias, blocked-fold U.S. ranking endpoints, and out-of-fold residual Moran's I with deterministic permutation p-values. A4-S uses a fixed graph-Laplacian residual operator; A4-C estimates positive-count dispersion within each training fold; A4-SC combines those two changes. No SIT variable or intervention proxy was supplied to any candidate.

### Observation-process assessment

The authorized observation source contains event date, host, longitude, and latitude. It contains no surveillance jurisdiction, reporting source, sampling program, inspection effort, reporting denominator, reporting-frequency metadata, or authorized effort/accessibility artifact. The inventory is in `results/observation_process_inventory.csv`.

A4-O is consequently sensitivity-only and not identified. Reporting-rate scenarios were predeclared at 0.50, 0.75, and 1.00; they do not identify unconstrained latent intensity and reporting probability from the same data. Results are in `results/a4_o_sensitivity.csv`. A4-SO was not fitted because the observation component was not identified.

### Advancement guardrails

Before reviewing candidate results, the comparison required preservation of PR-AUC, Brier skill, worst-fold PR-AUC, calibration, and U.S. ranking, plus a material improvement in at least one targeted structural failure mode. Simpler candidates were preferred when performance was similar. Because U.S. ranking was not estimable, every fitted A4 candidate failed advancement on `us_ranking_not_assessable`; this is an evidence limitation, not a prospective U.S. performance estimate.

## Candidate Results

| Candidate | Mean PR-AUC | Worst PR-AUC | Mean Brier skill | Mean joint NLL | Count NLL | Count bias | Occurrence Moran's I | Positive-count Moran's I | U.S. median percentile | U.S. top-10 recall | Selection status |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| A3 | 0.4741 | 0.3800 | 0.3707 | 0.0763 | 1.8955 | 0.7976 | 0.2933 | 0.3634 | NA | NA | Reference |
| A4-S | 0.5033 | 0.4148 | 0.3746 | 0.0757 | 1.8710 | 0.5003 | 0.2885 | 0.2852 | NA | NA | Not advanced |
| A4-C | 0.4741 | 0.3800 | 0.3707 | 0.0766 | 1.9082 | 0.7877 | 0.2933 | 0.3592 | NA | NA | Not advanced |
| A4-SC | 0.5033 | 0.4148 | 0.3746 | 0.0758 | 1.8788 | 0.4786 | 0.2885 | 0.2801 | NA | NA | Not advanced |
| A4-O | NA | NA | NA | NA | NA | NA | NA | NA | NA | NA | Sensitivity only; not identified |

The full machine-readable table is `results/a4_candidate_comparison.csv`; guardrails are in `results/a4_guardrail_assessment.csv`; fold-level outcomes are in `results/a4_fold_metrics.csv`.

### Failure-mode assessment

| Failure mode | Assessment | Evidence |
|---|---|---|
| Occurrence discrimination | PASS | A4-S/A4-SC improved mean PR-AUC to 0.5033 from 0.4741 and did not worsen worst-fold PR-AUC. |
| Calibration | PASS | Mean intercept/slope remained close to A3 and all fitted candidates passed the calibration guardrail. |
| U.S. transfer/ranking | NOT ASSESSABLE | Zero U.S. positive node-weeks occurred in the pre-W30 development folds; prospective W30–W39 was intentionally untouched. |
| Temporal blocked stability | PASS | All four folds converged for all fitted candidates; no random CV or future leakage was used. |
| Positive-count process | MINOR CONCERN | A4-S/A4-SC reduced count bias and positive-count Moran's I, but did not establish an unconfounded observation-aware count process. |
| Residual spatial dependence | MAJOR CONCERN | A4-S/A4-SC improved spatial residual dependence, but occurrence Moran's I remained about 0.289 with permutation p=0.005 and positive-count Moran's I remained about 0.285 with p=0.005. |
| History extrapolation | MINOR CONCERN | Strong-history joint NLL improved modestly for A4-S/A4-SC, approximately 0.9019/0.9030 versus A3 0.9094, without a decisive transfer guarantee. |
| Observation/reporting bias | NOT ASSESSABLE | No usable reporting-effort proxy was available; A4-O remained sensitivity-only. |

### U.S. interpretation

U.S. risk ranking is a primary endpoint, but it cannot be estimated on these development folds. The U.S. ranking CSV records zero U.S. positive node-weeks for every candidate. Raw U.S. count magnitude and progression velocity remain secondary `INTERVENTION_CONFOUNDED` endpoints because stronger SIT suppression may reduce observed counts and northward progression. They were not used as primary A4 advancement targets.

### Count-process interpretation

Observed total detections were not treated as latent truth. A4-S and A4-SC reduced systematic conditional-count excess relative to A3, while preserving occurrence ranking. A4-C alone did not produce a material structural improvement and slightly worsened count NLL. This supports further investigation of the count/observation distinction, but not promotion of a count-only architecture.

### Sensitivity analysis

The A4-O scenarios changed the implied latent conditional mean from approximately 3.89 at reporting rate 1.00 to 7.78 at 0.50, while remaining explicitly sensitivity-only. Recorded-scale discrimination was similar across the scenarios, but latent magnitude was not identified. Candidate rankings were therefore not treated as evidence for an observation-aware production model.

## Figures

Static PNG and PDF figures are in `figures/`:

1. `candidate_pr_auc`
2. `candidate_brier_skill`
3. `candidate_joint_nll`
4. `candidate_count_observed_vs_predicted`
5. `candidate_residual_moran_i`
6. `residual_spatial_map`
7. `us_top_k_capture` (explicit not-assessable annotation)
8. `extrapolative_regime_performance`
9. `complexity_vs_performance`

The source/figure manifest is `figures/figure_manifest.csv`. The residual map data are retained in the external Atlas output root rather than committed as a large generated table.

## Validation and provenance

The analysis manifest is `provenance/a4_analysis_manifest.json`. It records input SHA-256 values, model constants, fold definitions, script hashes, runtime, and the explicit flags `prospective_data_loaded=false`, `prospective_selection_used=false`, and `sit_included=false`.

Validation covered exact pre-W30 boundaries, deterministic F1–F4 folds, candidate metric comparability, out-of-fold residual diagnostics, fixed observation-sensitivity scenarios, no SIT covariates, and unchanged frozen A3 baseline. Python syntax and focused repository tests were run with the Atlas Python environment; R figure rendering used the repository Atlas bootstrap and validated R library paths. The Atlas Python environment did not provide pytest, so the focused test module was executed by its repository-compatible manual harness rather than substituting a different full-suite runner.

## Final Decision

**HOLD — NO A4 CANDIDATE JUSTIFIED**

The strongest reasons are:

1. A4-S and A4-SC improve spatial/count diagnostics, but residual spatial dependence remains significant and not fully solved.
2. The required U.S. positive-risk ranking endpoint is not estimable on pre-W30 folds; advancing without that guardrail would be unsupported.
3. A4-C does not materially improve the targeted count failure mode.
4. Observation/reporting effort is unmeasured, so A4-O and A4-SO cannot be promoted as identified models.
5. SIT is deliberately excluded and U.S. counts/progression are intervention-confounded; this phase cannot use them as clean advancement evidence.

No A4 candidate is deployed by this analysis.
