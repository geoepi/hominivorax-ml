# Frozen STRUCTURED A3 evaluation report

## 1. Objective

Evaluate the frozen STRUCTURED A3 model outside F1--F4 without model changes.

## 2. Frozen model

- 34 predictors; penalty `0.01`; fixed theta `0.7018903965556372`.
- Objective `exact_joint_hurdle_nll`; revised domain 10,037 nodes.
- One final fit on 2025-W01--2026-W16; no evaluation responses used for fitting or preprocessing.

## 3. Evaluation provenance

- 2026-W17--2026-W29: `HISTORICAL EXPOSED HOLDOUT` (previously evaluated/reported project horizon).
- Later response dates occur in a source snapshot before the freeze and lack complete A3 predictor support; they are not eligible for an independent prospective claim.

## 4. Data availability

- Latest observation date in authoritative source: `2026-07-31` (2026-W31).
- Latest complete response/predictor week in the frozen model bundle: `2026-W29`.
- Historical evaluation endpoint: `2026-W29`; prospective endpoint: `NONE`.

## 5. Leakage and preprocessing audits

Causal history cutoffs were verified to precede each forecast week. Scaling was fit on the 68 development weeks only; evaluation-period means/SDs were not used.

## 6. Historical holdout results

| Geography | Node-weeks | Positives | Prevalence | NLL | PR-AUC | BSS | Calibration |
|---|---:|---:|---:|---:|---:|---:|---|
| Full domain | 130481 | 5302 | 0.040634 | 0.144818 | 0.440342 | 0.331273 | -0.0004 / 1.1197 |

## 7. Prospective results

NO INDEPENDENT PROSPECTIVE EVALUATION AVAILABLE.

## 8. A0 versus A3 comparison

A3 historical exposed-holdout joint NLL improvement over A0: `0.000848`; PR-AUC improvement: `0.012601`; Brier-skill improvement: `0.003182`.

## 9. U.S. transfer performance

See `us_transfer_metrics.csv`; sparse-U.S. counts are reported without stronger aggregation claims.

## 10. Calibration

A3 calibration intercept/slope were `-0.000407` / `1.119740`.

## 11. Count performance

Observed positive-count mean was `2.201622` versus predicted conditional mean `2.956889`, bias `0.755267`.

## 12. Generalization classification

Historical: `SUPPORTED`.
Prospective: `PROSPECTIVE GENERALIZATION NOT YET TESTED`.

## 13. Final interpretation

The historical result describes generalization beyond F1--F4 but cannot be called independent/prospective. No genuinely untouched later period with complete A3 predictors was available.

## Boundary checks

```text
predictor specification changed: NO
penalty changed: NO
theta changed/re-estimated: NO
model recalibrated: NO
feature selection reopened: NO
neural models fitted: NO
graph models fitted: NO
evaluation outcomes used for training: NO
evaluation outcomes used to alter model: NO
main merged: NO
```

## Production-readiness decision

`A3 REQUIRES FURTHER EXTERNAL/PROSPECTIVE VALIDATION`

Figure generation status: `unavailable: No module named 'matplotlib'`.
