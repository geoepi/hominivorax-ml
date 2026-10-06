# Structured hurdle model — final A0 vs A3 development comparison

## 1. Objective

This is the final structured A0 versus A3 development comparison. It uses the validated structured hurdle pathway only; neural and graph workstreams remain closed.

## 2. Provenance

- consolidated main SHA: `88bcf3ae238f3aae712b123acfa07e4b2c5e4ad1`
- controlled augmentation provenance SHA: `bd8346fc42e31e4f1f52b2ce7f2d3694f6a4af00`
- model-class diagnostic SHA: `844589d8bf79b0ecf2f9249b50ade91fbb0089d9`
- revised domain: 10,037 canonical nodes, Mexico plus the U.S. south of 40°N
- validated augmentation manifest: `/project/disease_ecology/STGNN-output/structured_a3_final_comparison/manifests/augmentation_manifest.json` (SHA-256 `ed471a2e08706b78516723e53760d66b76a70790e445bc3484a3fd877ac23087`)
- A0 manifest: `results/a0_reference_manifest.json`
- A3 manifest: `results/a3_feature_manifest.json`

## 3. A0 reproduction

The exact persisted A0 F1–F4 reference was reproduced before A3 interpretation. The gate tolerance was `1e-9` under fixed theta `0.7018903965556372` and penalty `0.01`.

**A0 REPRODUCTION PASSED**

## 4. Input QA

- A0 predictors: 30
- A3 predictors: 34
- A3 additions: `road_density, night_illumination, clay_0_15, water_difference_wv0033_minus_wv0010_0_15`
- transformations: road `log1p`, night `log1p`, soil identity for both frozen soil features
- node join: 10,037 to 10,037, zero unmatched, zero duplicates, zero unexplained missing/nonfinite values
- static A3 values: constant through time

## 5. Model protocol

Both models use exact joint hurdle NLL, Bernoulli occurrence, zero-truncated negative-binomial positive counts, fixed theta `0.7018903965556372`, penalty `0.01`, identical optimizer, frozen preprocessing, and F1–F4 only. No terminal/later outcomes, F5/F6, neural models, or graph models were used.

## 6. A0 vs A3 results

| Model | Mean NLL | Mean PR-AUC | Mean BSS | Calibration intercept / slope | Count MAE | Count RMSE |
|---|---:|---:|---:|---:|---:|---:|
| A0 | 0.076730 | 0.456112 | 0.366593 | 0.104302 / 1.185818 | 2.398808 | 3.267327 |
| A3 | 0.076333 | 0.474135 | 0.370679 | 0.103135 / 1.185496 | 2.331013 | 3.199617 |

## 7. Fold consistency

Improvement-oriented deltas are positive when A3 improves over A0. A3 improved joint NLL, PR-AUC, Brier skill, count MAE, and count RMSE in all four folds. Mean deltas were NLL `0.000397`, PR-AUC `0.018024`, and Brier skill `0.004086`.

F4 was not a failure fold: ΔNLL `0.000184`, ΔPR-AUC `0.007871`, ΔBSS `0.001365`, calibration-distance movement `0.013723`, count-MAE movement `0.044733`, and count-RMSE movement `0.003271`.

## 8. Calibration

A3 calibration was effectively preserved overall: mean calibration-distance movement was `0.000221` toward the ideal intercept 0/slope 1, with F4 improving. There was no systematic calibration deterioration.

## 9. Count behavior

A3 improved positive-count MAE and RMSE in every fold. Conditional mean bias is reported in `count_comparison.csv`; it was not used to conceal occurrence or proper-score degradation.

## 10. A3 coefficient stability

| Feature | Component | Mean standardized coefficient | Minimum | Maximum | Dominant sign | Stable sign |
|---|---|---:|---:|---:|---|---|
| clay_0_15 | occurrence | -0.034239 | -0.041984 | -0.024086 | negative | YES |
| night_illumination | occurrence | 0.017835 | 0.000696 | 0.028899 | positive | YES |
| road_density | occurrence | 0.060442 | 0.027980 | 0.083184 | positive | YES |
| water_difference_wv0033_minus_wv0010_0_15 | occurrence | -0.066868 | -0.069034 | -0.063677 | negative | YES |
| clay_0_15 | positive_count | -0.092355 | -0.134516 | -0.072339 | negative | YES |
| night_illumination | positive_count | -0.101533 | -0.130746 | -0.078827 | negative | YES |
| road_density | positive_count | 0.247861 | 0.069430 | 0.345251 | positive | YES |
| water_difference_wv0033_minus_wv0010_0_15 | positive_count | -0.086756 | -0.107658 | -0.076452 | negative | YES |

All four additions have stable signs across F1–F4 in both hurdle components. Coefficients are diagnostic evidence, not p-value-based feature selection.

## 11. Final decision

**ADVANCE**

The gain is modest but coherent: all four folds improve the primary proper scores, F4 improves rather than deteriorates, calibration is preserved, count errors improve, and coefficient signs are stable. This satisfies the frozen A3 development advancement rule without reopening feature selection.

## 12. Final structured specification

**STRUCTURED A3**

## 13. Final disposition

**STRUCTURED A3 DEVELOPMENT SPECIFICATION FROZEN**

This freezes a development specification only; it is not terminal or prospective validation.

## 14. Boundary checks

- neural models fitted: NO
- graph models fitted: NO
- A3 feature set changed: NO
- feature selection reopened: NO
- response changed: NO
- theta re-estimated: NO
- penalty changed: NO
- F5/F6 used: NO
- terminal/later outcomes used: NO
- main merged: NO
