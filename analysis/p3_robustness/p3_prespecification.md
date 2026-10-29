# P3 Bounded Robustness and Sensitivity Analysis — Prespecification

This prespecification is written before inspecting P3 sensitivity results. P3
reuses the immutable P2 rolling-origin predictions and fit artifacts where
possible. It does not alter the frozen `STRUCTURED_A3` object, its 34
predictors, transformations, lags, response, penalty, fixed theta, optimizer,
graph methodology, or production artifact.

## Reference qualification state

- P0 frozen model: `STRUCTURED_A3`.
- P0 model artifact SHA-256:
  `8a6a0a32a1a1e56f810b6aa1eafec5207dc3ac8d45cdf2270999f9721f080d1e`.
- P2 merge SHA: `ec6e951c63f7ec7fd252de5ddea6bb9772fea906`.
- P2 primary evaluation: 21 expanding origins, `2026-W16` through
  `2026-W36`, horizons 1–3.

## A. Frontier-definition sensitivity

F0 is the unchanged P1/P2 reference: a node is `previously_occupied` when any
positive count has been observed for that node through origin T; otherwise it
is `previously_unoccupied`.

Two alternatives are prespecified:

- F1 `recent_8_week_occupancy`: a node is occupied when it has at least one
  positive observation in the eight weeks ending at origin T, clipped to the
  available training history. Nodes without such a recent positive are
  `recent_8_week_unoccupied`.
- F2 `distance_to_prior_detection`: calculate the nearest positive node through
  origin T using the canonical grid row/column coordinates and a 25-km grid
  scale. Classify `near_established` at <=25 km, `intermediate_frontier` at
  >25 and <=100 km, and `distal_or_unoccupied` at >100 km or when no prior
  positive exists.

Only counts through T are supplied to either classifier. Future target-week
counts are used only as outcomes. The leakage contract tests mutate T+1:T+3
counts while holding through-T counts fixed and require identical classes.

For F0–F2 and h=1,2,3, report N, positives, prevalence, Brier, calibration
intercept/slope, AUPRC, AUROC, conditional count MAE/bias, and full expected
count MAE/bias for each class. Sparse-frontier support is assessed from the
class N and positive count; no class is pooled post hoc.

## B. Count-error influence

The P2 positive-count predictions are reused unchanged. Strata are defined by
observed positive count before results are inspected:

- `low_1_2`: 1–2;
- `moderate_3_5`: 3–5;
- `high_6_10`: 6–10;
- `extreme_11_plus`: >=11.

For each stratum, report N, observed and predicted means, MAE, RMSE, signed
error, observed/predicted ratio, and contributions to total absolute error,
total squared error, and the untrimmed overall conditional mean bias.

Diagnostic exclusions are rank-based and secondary: remove the largest
`ceil(0.05*N)` and `ceil(0.01*N)` observed-positive rows, respectively, with
ties resolved deterministically by origin week, target week, and model node ID.
Recompute conditional and full-hurdle metrics, but do not refit, winsorize,
change the response, or replace the untrimmed production interpretation.

## C. Evaluation-partition sensitivity

The reference spatial partition S0 is the P2 `country_or_domain_region`
partition. Two fixed alternatives are defined independently of performance:

- S1 latitude macroregions: `south_of_20N` (<20°N), `20_to_30N` (>=20 and
  <30°N), and `30_to_40N` (>=30°N).
- S2 longitude macroregions: `west_of_105W` (<-105°), `105W_to_95W` (>=-105
  and <-95°), and `east_of_95W` (>=-95°).

Temporal summaries are:

- T0 individual target weeks;
- T1 fixed four-week blocks beginning at `2026-W17`, with final block
  `2026-W37`–`2026-W39`.

For S0–S2 and T0–T1, report the P2 occurrence metrics (N, positives,
prevalence, Brier, calibration intercept/slope, AUROC, AUPRC) and count
metrics (conditional MAE/bias and full expected MAE/bias) by h=1,2,3. This is
regrouping of frozen predictions, not a new training regime or a spatial
holdout. The P1/P2 spatial-holdout limitation therefore remains separately
tracked.

## D. Fit and numerical stability

The 21 immutable P2 fit artifacts are summarized without refitting: component
coefficients, signs, mean/SD/range, 5th–95th percentiles, relative variation,
sign changes, optimizer iterations, component objectives, convergence flags,
coefficient norms, and predefined feature-group norms. Structured A3 has no
latent graph-effect parameter; that component is recorded as not applicable.

Because the implementation explicitly initializes L-BFGS-B, a bounded
initialization experiment is prespecified for origins `2026-W16`, `2026-W26`,
and `2026-W36`:

- `canonical`: the exact P2 starts (zero occurrence slopes/intercept and count
  intercept log positive mean with zero count slopes);
- `zero_all`: zero vectors for both components;
- `deterministic_perturbed`: canonical starts plus the deterministic alternating
  perturbation `0.10*(-1)^j/(1+sqrt(j))` for coefficient index j, including
  intercept index 0.

All variants use the exact P2 objective, penalty, fixed theta, predictor
schema, preprocessing, and L-BFGS-B settings. They are diagnostics only.
Compare convergence, final component objectives, occurrence/count predictions,
and the principal P2 metrics. No random starts or tuning are allowed.

## Primary metrics and decision rules

Primary metrics are occurrence Brier, calibration intercept/slope, AUPRC,
frontier positive support, conditional count MAE/bias, full expected count
MAE/bias, and initialization prediction/objective differences.

`ROBUST` means no bounded alternative reverses a P1/P2 qualification and no
new instability is exposed. `SENSITIVE_BUT_INTERPRETABLE` means an interpretable
dependence or reinforced limitation appears without reversal. A
`MATERIAL_ROBUSTNESS_FAILURE` requires a defensible alternative that reverses a
principal qualification or exposes substantive numerical instability.

P3 will use one of the required decision markers and will not promote an
unrestricted production claim. The retrospective environmental release-time
limitation is not addressable by these analyses.
