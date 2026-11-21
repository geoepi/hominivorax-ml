# STRUCTURED_A3 W44 scientific qualification design

**Design decision:** W44_QUALIFICATION_DESIGN_READY.
**Candidate status:** CANDIDATE_READY_FOR_REVIEW_NOT_PRODUCTION_QUALIFIED.
**Scope:** planning and evidence review only. No scientific fits, forecasts, qualification metrics, or production configuration were changed or run.

## I. Governance and starting state

The consolidated refresh branch was verified at **955ae4375043552457a3f052458e4f9115ce9095**. This report is on an isolated branch based on that commit. PR #31 remains a draft. Global execution governance, repository qualification instructions, and Atlas SSH policy were reviewed. Atlas metadata was accessed only through the approved WSL/Ubuntu **/home/johnh/bin/atlas-ssh** wrapper; no jobs were submitted.

The design follows P0–P7 in [docs/production_qualification_plan.md](../../../docs/production_qualification_plan.md). Qualification evaluates an immutable P0 object; it does not silently change model specification. Candidate-specific provenance and limitations remain those in [the W44 data-vintage manifest](../candidate_data_vintage_manifest.json): W44 is a provisional training endpoint; reporting completeness through W44 is uncertified; historical observation revisions are accepted but unexplained; the W29 lineage investigation remains deferred.

Candidate identity to carry forward:

- STRUCTURED_A3_2026W44; model SHA-256 **b1a66a65efbb9a65f6a4c966044d2f87576ee7e6a1d1a294c0fb1855f684f53b**.
- Training 2025-W01 through 2026-W44; 10,037 canonical cells at 25 × 25 km; 34 ordered predictors; penalized spatiotemporal hurdle model; unchanged A3 specification; SIT and flight-path predictors excluded.
- Observation input SHA-256 **784168081cc1d3206f3537b8731994cbfc34be15be7c515fe06710d4ea9bdaac**.
- Atlas candidate root: **/project/disease_ecology/STGNN-output/structured_a3_refresh_2026w44**.
- Existing full-fit products are descriptive fitted-period output, not independent validation. Preserve the model and outputs.

The source snapshot contains observations through W46 and the candidate fit completed on 2026-11-19. W45–W46 cannot be called prospectively issued, untouched W44 forecasts. The current source does not document a complete-week cutoff or release timestamps.

## II. Qualification framework and decision boundaries

P0–P7 are qualification phases, not eight automatic reruns. For a W44 production dossier:

- **P0 identity/freeze — required.** Record immutable W44 model, input, software, feature-order, transformation, and checksum identity. Verify; do not alter the W16 production freeze or refit W44.
- **P1 transfer — required for W44.** Reuse fixed-model temporal, spatial, spatiotemporal, frontier, key-join, and dependence-aware procedures. Score without refit across at least eight ordered complete post-issue weeks. Score at least two predeclared regions with both classes where estimable. P1 defines estimability, not a universal predictive-score cutoff.
- **P2 rolling-origin 1–3 weeks — required.** Apply the established expanding-window procedure on W44 data. Historical replay is retrospective and cannot replace independent post-freeze evaluation of the fixed W44 artifact.
- **P3 bounded robustness — required before carrying W16 robustness outcomes over.** Reuse the predeclared alternatives on W44 P2 outputs; add no variants or tuning.
- **P4 uncertainty/support — required and candidate-specific.** Recompute training support and uncertainty for W44; W16 thresholds/parameter uncertainty do not transfer.
- **P5/P5A availability — required for operational claims.** P5 did not support retrospective dynamic environmental inputs. Preserve the approved proxy rules and evaluate them on W44.
- **P6 hardening — required before production designation.** Existing W16 evidence is not W44 path acceptance. Validate W44 lineage and safe handling later in a separate output root; this design leaves production configuration untouched.
- **P7 publication artifacts — conditional.** Regenerate only if claims/results change. Existing cartography may remain candidate-review material. **P7I must be revisited before W44 operational early-warning/frontier claims** because W16 P7I found material issue-time degradation and A3 frontier ranking comparable to simple history.

No thresholds are added. Apply phase-specific rules from existing prespecifications. The W16 historical exposed-holdout rubric required finite joint NLL/BSS/PR-AUC/count-error metrics; its SUPPORTED rule was BSS > 0, PR-AUC at least prevalence, calibration slope 0.5–1.5, and absolute intercept at most 1. Its weaker historical/partial rubric used BSS > −0.05 and PR-AUC at least 0.75 × prevalence plus calibration details. Those rules belong to the exposed W16 holdout in analysis/structured_a3_evaluation/scripts/run_frozen_a3_evaluation.py and are not W44 production cutoffs. W29 exploratory diagnostics likewise do not set W44 thresholds. The separate V2A delayed prospective trigger (eight weeks / ten first-ever-positive events) is not an A3 W44 acceptance rule. The repository defines no single numeric composite rule that automatically promotes a candidate. Report phase outcomes and limitations to the authorized decision process. Convergence and raster generation alone do not qualify predictions.

## III. Existing evidence and reuse

See [existing_evidence_inventory.csv](existing_evidence_inventory.csv). Reuse classes apply to W44 claims. Qualification procedures, schemas, no-refit boundaries, metric definitions, and thresholds are **DIRECTLY_REUSABLE**. W16 outcomes are **CONTEXT_ONLY** because model hash, fit vintage, source vintage, or issue-time status differs. W44 manifests establish identity, not predictive performance. Fitted-period output and cartographic products are **NOT_APPLICABLE** as independent validation. Historical development folds on the 16,756-node domain cannot be treated as W44 holdouts without an explicit crosswalk and distinct estimand.

## IV. Rolling-origin forecast design

The P2 runner begins at origin W16, uses an expanding window from 2025-W01 through origin T, and evaluates h=1,2,3. Prior results covered 21 origins W16–W36 and targets W17–W39. On the 96-week W44 bundle, origins W16–W41 have three available targets: **26 origins, 78 origin-horizon blocks, 782,886 node-horizon rows** over 10,037 cells. Exact rows are in [rolling_origin_design.csv](rolling_origin_design.csv).

Retain the 34 predictors/transforms/order, penalty 0.01, fixed theta 0.7018903965556372, exact_joint_hurdle_nll, L-BFGS-B settings, response definition, domain, and history cutoff strictly before each target. Fit response rows stop at T; no T+1:T+3 outcomes enter fitting or feature construction. Preserve exact origin/target/node keys and weekly responses.

The historical replay uses current W44 response and feature snapshots even for past origins. It is a **retrospective updated-vintage hindcast**, not a reconstruction of information available then: observation revision history and environmental release timestamps are missing. Forecasts using realized target-week weather are retrospective. No W44 raster proves it was available at a historical origin.

Separately, issue the unchanged fixed W44 model at eight consecutive weekly origins after exact freeze and before target outcomes are observed. At h=1,2,3 this is **24 blocks** (10,037 nodes/block); each horizon has eight consecutive targets and the union has ten target weeks. P1’s eight-week rule can be met only after eight post-issue outcomes are complete and mature. Retain issue timestamp, model hash, source availability times, history cutoff, target and maturity status. Keep row-level predictions and coordinates on Atlas. W45–W46 do not meet the prospective issue-time condition.

The user clarified the environmental convention for this plan: keep E0_LAST_AVAILABLE (T−1 carried across h=1,2,3) as primary and E1_TRAILING3_MEAN (mean over T−1:T−3) as sensitivity. This preserves the existing P5A roles. Evaluate E1 only to the extent required by the existing framework. Apply the same origin-time information restrictions to both. E2 remains not evaluable under the retained seasonal archive. Historical input release timestamps remain unavailable, so label E0/E1 as availability proxies rather than proof that historical values were issued in real time.

For P5A proxy comparison, retain its predeclared strict limits at every horizon: Brier increase ≤0.002; relative PR-AUC loss ≤5%; absolute calibration-intercept change ≤0.05; full expected-count MAE increase ≤0.02; conditional-count MAE increase ≤0.10; frontier Brier increase ≤0.002 where estimable. If no proxy meets all strict bounds, the existing bounded-with-limitations limits are Brier ≤0.005, relative PR-AUC loss ≤10%, calibration-intercept change ≤0.10, full expected-count MAE increase ≤0.05, conditional-count MAE increase ≤0.25, and frontier Brier increase ≤0.005. Do not change these after results are seen.

Retain P2 metrics: occurrence Brier, log loss, ROC-AUC, PR-AUC, prevalence, calibration intercept/slope and frozen simple references; conditional positive-count MAE/RMSE/bias and observed:predicted ratio; unconditional hurdle expected-count MAE/RMSE/bias; joint hurdle NLL; horizon/frontier/region strata. Preserve target-week bootstrap rules/seed/count. Do not recalibrate.

## V. Spatial validation, calibration, uncertainty

See [spatial_validation_design.md](spatial_validation_design.md). P1 spatial is fixed-coefficient geographic transfer, not leave-region-out refitting. Use predeclared regions; do not pool sparse strata after looking. Preserve exact week/node keys, 5×5-cell spatial blocks, two-week temporal blocks, and joint space-time resampling. Check W44 node ordering and graph identity.

Report occurrence metrics and conditional/unconditional count error by horizon and region. Mark class-dependent metrics not estimable where necessary. Report central 50%, 80%, 95% predictive interval coverage and width overall and by support/frontier class where estimable. Use the frozen zero-truncated negative-binomial conditional law and full hurdle mixture.

Recompute P4 support from W44 training predictors only: feature min/max and 1–99% ranges, standardized nearest-neighbor distance, and leave-one-out training-distance Q95/Q99. Existing flags remain: any min/max excursion or distance >Q99 → EXTRAPOLATIVE; otherwise any 1–99% excursion or distance >Q95 → CAUTION; otherwise SUPPORTED. For W44 parameter uncertainty use the established whole-training-week bootstrap (seed base 20261029; 100 successful replicates, max 120 deterministic slots; keep all nodes in a sampled week). Do not reuse W16 coefficient uncertainty or replace canonical predictions with bootstrap means.

For W44 residual spatial autocorrelation, score independent post-freeze residuals on the fixed Queen graph and use the established deterministic 199-permutation diagnostic. W29 Moran values (occurrence I=0.3087; positive-count I=0.2232) are context only, not W44 thresholds.

## VI. W16 versus W44

Current artifacts cannot provide a paired out-of-sample comparison: W16 rolling forecasts differ in model vintage; W44 fitted-period predictions differ in target status. Do not compare training-period scores as independent performance.

[The comparison design](w16_w44_comparison_design.md) separates fitted surfaces, predictor associations, calibration, predictive performance, support/extrapolation, and the effect of training-history extension. The predictive comparison is to issue both frozen W16 and W44 models at identical future times, inputs/cutoffs, horizons, spatial keys, and mature outcomes. Refit neither during paired forecasts.

An optional W16-cutoff diagnostic fit on current W44 inputs truncated at W16 can help separate added training weeks from historical input-vintage differences. It is not required for fixed W44 predictive performance. If used, keep the A3 specification unchanged and label it diagnostic. Coefficient changes are associations, not causal effects.

## VII. Computation and execution boundary

See [computational_feasibility.md](computational_feasibility.md) and [qualification_execution_plan.json](qualification_execution_plan.json). Reuse one W44 origin archive across P2/P3/P4/P5A; add no W44 full-model refit; await eight consecutive post-issue weeks for fixed W44 evidence. Historical and prospective designs answer different questions.

Historical Atlas records: P2 origin tasks 11–21 sec each; sampled MaxRSS 642,120–758,468 KB. P2 prepare/aggregate 13 sec/26:41. P1 6:54; P3 1:49; P4 support 4:37; sampled P4 bootstrap slots 10–16 sec. W44 fit took 8:47 and must not be repeated. Qualification requests were 64G or 96G with 16 CPUs; sampled batch MaxRSS was about 0.6–4.8 GB. P5A metadata reported 410.3 seconds but no job ID/MaxRSS. These are observations, not runtime promises.

Atlas /project showed 8.1 TB total, 3.6 TB used, 4.5 TB available. quota -s was not permitted. Existing P2 prediction Parquet is 23,770,151 bytes for 632,331 rows; P4 bootstrap target manifest is 2,118,021 bytes. Do not infer future W44 sizes. Check project quota/destination before execution. Keep row-level predictions, coordinates, residuals and detailed maps on Atlas; commit only aggregates, metadata, configuration, code and documentation.

## VIII. Limitations and decision

Execution gates: verify/freeze W44 exact hash; retain pre-outcome issue time and input-availability record; wait for at least eight ordered complete mature post-issue weeks; verify W44 node/graph/key alignment. The environmental primary/sensitivity roles are resolved by the user clarification above. Historical replay may run earlier after separate authorization, but cannot satisfy P1’s prospective gate.

Accepted limitations: provisional W44 endpoint, uncertified completeness through W44, unexplained historical observation revisions, missing historical observation/environment release times, and deferred W29 lineage. They do not permit model or threshold changes.

This design outcome is **W44_QUALIFICATION_DESIGN_READY**. Candidate status remains **CANDIDATE_READY_FOR_REVIEW_NOT_PRODUCTION_QUALIFIED**. No scientific qualification execution or production promotion is authorized.
