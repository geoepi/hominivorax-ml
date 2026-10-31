# Results Draft

## Model and retrospective nowcast performance

P2 all-domain Brier scores were 0.0281, 0.0284, and 0.0288 for h=1--3; AUPRC values were 0.4452, 0.4414, and 0.4402. These are retrospective rolling-origin results with explicit horizon labels, not unrestricted prospective forecasts.

## Dependence and first-recorded detection diagnostics

P7G dependence diagnostics showed positive raw occurrence association across spatial shells and temporal lags. At h=1, pooled shell-1 association was 0.6774 for raw occurrence and 0.3630 for the occurrence residual; at shell 4 the corresponding values were 0.4950 and 0.1160. Pooled temporal lag-1 occurrence association at h=1 was 0.4778 for raw occurrence and 0.1535 for the residual. Residual association was lower but remained positive; this is a diagnostic, not a spatial holdout.

Among 860 first-recorded frontier-relative events at h=1, the top 5% of p_occurrence-ranked cells captured 84.0% of events; corresponding capture was 79.7% at h=2 and 74.7% at h=3. These are retrospective ranking diagnostics within fixed pools and do not establish causal early-warning performance.

## Predictor dependence and conditional associations

The 34 frozen predictors included 19 pairs with absolute Pearson correlation at least 0.70 and 11 pairs at least 0.90 in the P4 training reference. The standardized association display therefore uses fitted-scale contrasts with scale-category labels; it is not a global importance ranking. A retained P4 coefficient-bootstrap stability artifact was unavailable, so no coefficient intervals were fabricated.

## Environmental proxy validation

P5A E0 Brier differences relative to REALIZED_ENV were -0.0000, -0.0000, and -0.0000 for h=1--3 in the paired comparison. E0 was selected by the prespecified simplicity-first rule and uses only the latest legitimate issue-time environmental state; it is not a realized future environment or a numerical weather forecast.

## Support-stratified calibration

Empirical occurrence performance varied by support class. Brier scores for SUPPORTED rows were 0.0088, 0.0080, 0.0072 across h=1--3, compared with 0.0513, 0.0510, 0.0505 for EXTRAPOLATIVE rows. These estimates are conditional support-stratified diagnostics; support classes are not direct correctness probabilities and thresholds were not retuned.

## Frontier, counts, support, and production

Frontier strata remain sparse and weaker, count predictions retain measurable bias, and P4 support flags identify heterogeneous predictor-space support. P6 demonstrated deterministic replay, restartability, duplicate-run protection, and corruption detection without changing the scientific model.
