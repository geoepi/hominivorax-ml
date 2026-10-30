# Controlled Results Synthesis

This document is generated only from canonical P1--P6 machine-readable artifacts.
It is a controlled source for manuscript wording, not a new scientific analysis.

## Qualified model and horizon

The frozen model is `STRUCTURED_A3` with 34 predictors on the 25 x 25 km canonical cells canonical grid (10037 cells). The qualified operational configuration uses `E0_LAST_AVAILABLE` across the 1--3 week nowcast horizon.
Source: `config/production_model_freeze.json`; `config/p6_production_config.json`.

## Canonical decisions

- P1: `P1_TRANSFER_VALIDATION_SUPPORTED_WITH_LIMITATIONS`
- P2: `P2_OPERATIONAL_NOWCAST_SUPPORTED_WITH_LIMITATIONS`
- P3: `P3_ROBUSTNESS_SUPPORTED_WITH_LIMITATIONS`
- P4: `P4_UNCERTAINTY_SUPPORT_SUPPORTED_WITH_LIMITATIONS`
- P5: `P5_OPERATIONAL_CONTRACT_NOT_SUPPORTED`
- P5A: `P5A_ENVIRONMENTAL_PROXY_SUPPORTED`
- P6: `P6_PRODUCTION_HARDENING_SUPPORTED_WITH_LIMITATIONS`

## Occurrence performance

P2 all-domain Brier scores were 0.0281, 0.0284, 0.0288 for h=1--3 and AUPRC values were 0.4452, 0.4414, 0.4402.
Calibration intercepts, slopes, AUROC, sample sizes, and prevalence are in
`tables/table_2_occurrence_performance.csv`, sourced from
`analysis/p2_operational_nowcast/results/horizon_metrics.csv`. These are
retrospective rolling-origin results, not unrestricted prospective forecasts.

## Horizon change

The canonical common-week Brier change from h=1 to h=3 was 0.0001. Source: `analysis/p2_operational_nowcast/results/horizon_deltas.csv`.

## Environmental proxy

P5A E0 Brier differences relative to REALIZED_ENV were -0.0000, -0.0000, -0.0000 for h=1--3; the source comparison is paired and uses the same evaluation records.
E0 is the latest legitimately available environmental state held across h=1--3;
it is not a realized future environment or a numerical weather forecast.
Source: `analysis/p5a_environmental_proxy/results/paired_proxy_minus_realized.csv` and
`analysis/p5a_environmental_proxy/results/proxy_contract.json`.

## Frontier, count, and support limitations

Previously unoccupied/frontier rows have weaker performance and sparse positive
support in the canonical frontier strata. Conditional positive-count and full-hurdle
metrics retain measurable bias. P4 support classification is emitted per row
and a substantial share of E0 predictions are CAUTION or EXTRAPOLATIVE.
Under E0 at h=3, support proportions were SUPPORTED 30.2%, CAUTION 23.3%, EXTRAPOLATIVE 46.5%.
Sources: P1--P4 frontier/support artifacts, `analysis/p2_operational_nowcast/results/count_metrics.csv`,
and `analysis/p5a_environmental_proxy/results/support_metrics.csv`.

## Production qualification

P6 records deterministic replay, restartability, duplicate-run protection,
corruption detection, and provenance within the qualified contract, with the
documented source-vintage and history-cutoff limitations. The production
interpretation is short-horizon nowcasting under an issue-time environmental
proxy assumption, with support and uncertainty flags retained.
Source: `analysis/p6_production_hardening/results/p6_decision.json`.
