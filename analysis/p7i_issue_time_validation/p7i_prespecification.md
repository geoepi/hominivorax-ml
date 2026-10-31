# P7I Prespecification — Issue-Time-Causal Forecast Validation

## Scope and boundary

P7I validates the frozen `STRUCTURED_A3` procedure under issue-time-causal
inputs. It does not change predictors, transformations, coefficients, penalty,
theta, response definitions, thresholds, or the P0 artifact. No candidate model
is fitted or tuned. Any exact rolling-origin refit required only to reproduce a
retained P2 state is a validation replay and must use the exact frozen procedure.

The starting scientific anchors are main `92c80e72c201e176e4be8c6b3bcd66accfc59408`,
the frozen artifact SHA-256
`8a6a0a32a1a1e56f810b6aa1eafec5207dc3ac8d45cdf2270999f9721f080d1e`, the
canonical P2 rolling-origin archive, the P4 support specification, the P5A
`E0_LAST_AVAILABLE` contract, and the P7G/P7H evidence manifests. Their hashes
are recorded in the final P7I provenance manifest before result interpretation.

## Forecast design

- Origins: canonical P2 origins `2026-W16` through `2026-W36`.
- Horizons: `h=1,2,3`; target weeks are the ISO-week targets implied by each
  origin and horizon.
- Issue time: Monday 00:00 UTC immediately after completed origin week `T`.
- Training outcomes: rows dated through `T`, with the original expanding-window
  training convention and no post-`T` outcomes.
- History: the validated P6 origin-bounded constructor, using only detections
  available through `T`; target-relative elapsed-time behavior is preserved
  exactly as defined by that constructor.
- Environment: primary operational replay uses `E0_LAST_AVAILABLE`, with
  `L(T)=T-1` ISO week and the exact P5A/P6 missing/future-vintage failure rules.
- Static and calendar predictors: unchanged, with calendar values generated for
  the target week as in the frozen preprocessing contract.

## Comparison variants

The paired evaluation key is origin, target week, horizon, and canonical cell.
The required variants are:

1. `V1_REALIZED_RETROSPECTIVE`: unchanged P2 realized target-week environment
   and existing P2 target-week history.
2. `V2_E0_RETROSPECTIVE_HISTORY`: E0 environment with existing target-week
   history, reproducing the P5A comparison.
3. `V3_REALIZED_ORIGIN_BOUNDED_HISTORY`: realized environment with the
   origin-bounded history, if retained inputs permit exact construction.
4. `V4_ISSUE_TIME_CAUSAL`: E0 environment with origin-bounded history; this is
   the primary operational result.

V1 reproduction is a gate: canonical predictions and metrics must agree within
  absolute tolerance `1e-10` for stored deterministic values, or the replay
  fails closed. V2 must reproduce the canonical P5A result within the same
  metric tolerance where records are identical. If V3 is infeasible from
  retained artifacts, it is reported as not evaluable without weakening V4.

## Metrics and uncertainty

For every available variant and horizon, report N, positives, prevalence,
PR-AUC, ROC-AUC, Brier, log loss, calibration intercept/slope, reliability bins,
conditional-count MAE/RMSE/bias/observed-to-predicted ratio, and full-hurdle
MAE/RMSE/bias/observed and predicted totals. Differences use signed
`variant - reference` conventions, with lower-is-better metrics interpreted
explicitly.

Uncertainty uses target-week block resampling: all cells and overlapping-horizon
records for a sampled target week remain together. The fixed P5A convention of
199 replicates and seed `20261029` is used for paired proxy/causal differences
where computationally practical, with percentile 95% intervals. Replicate
count, seed, and statistic definitions are not changed after results are seen.

## Frontier benchmarks

Frontier pools are the same origin-bounded previously-unoccupied pools used for
V4 and the same first-recorded-detection eligibility. Scores are:

- `A3`: V4 occurrence probability;
- `B1`: inverse rank of distance to any prior recorded positive;
- `B2`: inverse rank of distance to the canonical recent recorded positive;
- `B3`: inverse rank of the canonical nearby-detection recency variable.

Ranks use deterministic midranks, larger percentile means higher risk, and the
same eligible pool for every score. Missing scores receive the prespecified
lowest-risk rank within the pool. Report event N, median percentile, IQR, and
top 1%, 5%, 10%, and 20% capture. PR-AUC/Brier are not calculated for
uncalibrated benchmark ranks.

The benchmark decision is defined before execution: `A3_FRONTIER_RANKING_ADDS_INFORMATION_BEYOND_SIMPLE_HISTORY`
requires A3 to exceed every available simple score in at least two of the three
top-k operating points (5%, 10%, 20%) in each horizon and not be worse at more
than one point; otherwise use `A3_FRONTIER_RANKING_COMPARABLE_TO_SIMPLE_HISTORY`
when no method is consistently superior, or
`A3_FRONTIER_RANKING_DOES_NOT_OUTPERFORM_SIMPLE_HISTORY` when a simple score is
consistently better. If eligibility or score construction fails, use
`FRONTIER_BENCHMARK_NOT_ESTIMABLE`.

## Paired first-detection trajectory

Only first-recorded-detection events with valid V4 predictions at all h=1, h=2,
and h=3 are retained. Report matched N, median risk percentile by horizon,
median and IQR of h1−h3 percentile change, and the proportions increasing,
equal, and decreasing. This is descriptive and uses no significance test.

## Reconciliation rules

- Correlation: report Pearson-only counts, Spearman-only counts, and the
  implemented `max(abs(Pearson), abs(Spearman))` warning counts at thresholds
  0.70 and 0.90. Active documentation uses the implemented max rule; historical
  signed artifacts are not rewritten silently.
- P4 coefficient stability: audit file hash, creation history, source script,
  canonical bootstrap correspondence, predictor order, and model identity.
  No bootstrap refit is performed and no coefficient intervals are added to the
  manuscript package.
- Early-warning metadata: correct bookkeeping only; event identities, scores,
  ranks, and scientific event-output hashes must remain unchanged.
- D1–D5 provenance: use retained manifests and source metadata; unresolved
  fields are recorded as `UNRESOLVED_FROM_RETAINED_PROVENANCE`, never guessed.
- References: persistence means any recorded positivity through origin `T`;
  historical prevalence means the training-only same-ISO-week prevalence with
  the retained P2 fallback rule.

## Leakage, output, and interpretation contracts

V4 must fail if any detection after `T`, target outcome, disallowed environmental
vintage, or post-origin training row enters feature construction. Every output
must retain variant, origin, target, horizon, cell, source hashes, history
cutoff, environmental reference week, and model hash. Compact scientific outputs
are generated twice and must have identical hashes.

Operational validity thresholds are inherited from P5A where applicable:
strictly negligible degradation is Brier increase ≤0.002, relative PR-AUC loss
≤5%, absolute calibration-intercept change ≤0.05, full-count MAE increase ≤0.02,
conditional-count MAE increase ≤0.10, and frontier Brier increase ≤0.002 when
estimable. A usable-but-degraded result may use P5A bounded limits of 0.005,
10%, 0.10, 0.05, 0.25, and 0.005 respectively. These thresholds are fixed
before results.

Issue-time conclusions concern prediction of recorded detection only. First
recorded detection is not biological arrival or establishment; counts are not
direct adult abundance; and the replay does not establish causal effects.

