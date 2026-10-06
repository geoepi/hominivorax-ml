# STGNN model-class diagnostic: structured vs feed-forward vs temporal neural baselines

## 1. Objective

GConvGRU is no longer the default path. This diagnostic tests whether neural modeling is viable at all under the frozen A0 task and whether non-graph temporal recurrence adds value beyond a minimal feed-forward neural hurdle model.

## 2. Provenance

- Branch: `feature/model-class-diagnostic`, based on consolidated main `88bcf3ae238f3aae712b123acfa07e4b2c5e4ad1`.
- Prior audit provenance: `feature/neural-a0-architecture-audit` at `45dd7fe342b536cbe2a9d410b5b26cb1e3f9e485`.
- Frozen data: 10,037 nodes, 77,614 directed edges retained only as provenance, exactly 30 V2-A predictors, F1-F4, theta `0.7018903965556372`, and 52-week warm-up where applicable.
- Neural fits: exact joint hurdle NLL only; penalty applies to M0 (`0.01`).

## 3. Structured reference (M0)

M0 is the persisted structured V2-A A0 model, recovered from the four persisted A0 fold rows without retraining. It remains the current validated scientific reference.

## 4. Feed-forward neural baseline (M1)

M1 uses independent node-week observations, input dimension 30, one 64-unit ReLU hidden layer, dropout 0.1, two hurdle heads, fixed theta, training-fold-derived scaling, and maximum 36 epochs with patience 3.

## 5. Temporal neural baseline (M2)

M2 uses the audited non-graph one-layer GRU, hidden size 64, dropout 0.1, exact hurdle NLL, fixed theta, 52-week warm-up, 13-week TBPTT, training-fold-derived scaling, and maximum 36 epochs with patience 3. No graph convolution or K parameter was used.

## 6. Neural validity

| model | runs | mean NLL | mean PR-AUC | mean Brier skill | calibration intercept / slope | count MAE | valid |
|---|---:|---:|---:|---:|---:|---:|---|
| M0 | 4 | 0.076730 | 0.456112 | 0.366593 | 0.104302 / 1.185818 | 2.398808 | YES |
| M1 | 20 | 0.245959 | 0.125174 | -1.547991 | -1.270433 / 2.001971 | 2.233487 | NO |
| M2 | 20 | 0.275472 | 0.256948 | -2.959883 | 0.341955 / 3.378571 | 1.881578 | NO |

Validity required finite and nondegenerate probabilities, positive Brier skill, PR-AUC above fold prevalence, NLL better than the trivial hurdle reference, non-pathological calibration, and at least 15 valid fold-seed runs. M1 valid: **NO**. M2 valid: **NO**.

## 7. Pairwise model-class comparison

Positive deltas favor the named comparison model.

| comparison | mean Δ NLL | mean Δ PR-AUC | mean Δ Brier skill | paired NLL result |
|---|---:|---:|---:|---|
| M1 vs M0 | -0.169229 | -0.330937 | -1.914584 | 0.00% favorable on NLL |
| M2 vs M0 | -0.198742 | -0.199164 | -3.326476 | 0.00% favorable on NLL |
| M2 vs M1 | -0.029513 | 0.131774 | -1.411892 | 65.00% favorable on NLL |

## 8. Calibration and prediction distributions

The required occurrence-head, prediction-distribution, weekly-calibration, and calibration-summary tables are persisted under `results/`. These include logit ranges, probability saturation checks, prevalence relationships, and fold-week diagnostics. No model is advanced solely on PR-AUC.

## 9. Count behavior

Positive-count MAE, RMSE, conditional mean bias, observed conditional means, and predicted conditional means are persisted in `count_prediction_summary.csv`. Count behavior is part of the validity gate and is not traded away for small occurrence-discrimination gains.

## 10. Final model-class recommendation

**NEURAL MODEL CLASS NOT SUPPORTED FOR CURRENT TASK**

## 11. Graph recommendation

**DO NOT REOPEN GRAPH MODELS**

## 12. Boundary checks

- A3 predictors used: NO
- Graph neural model fitted: NO
- Feature selection reopened: NO
- Predictor set changed: NO
- Response changed: NO
- Theta re-estimated: NO
- F5/F6 used: NO
- Terminal/later outcomes used: NO
- Main merged: NO

The task stops here. Large checkpoints remain outside Git; compact tables, manifests, configurations, and report are committed.
