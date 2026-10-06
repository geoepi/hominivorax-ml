# STGNN revised-domain neural A0 architecture and training audit

## Final disposition

**A0 VALIDITY IMPROVED BUT REMAINS AMBIGUOUS**

The audit completed all prescribed phases N1-N4 on the frozen revised-domain A0 task. The exact joint hurdle loss, non-graph control, K1 graph depth, and 36-epoch training duration each provide diagnostic information, but no tested neural configuration passes the validity gate (finite/nondegenerate predictions, positive Brier skill, PR-AUC above the frozen reference, and joint hurdle NLL below the frozen reference). The audit therefore does not support freezing a corrected neural baseline or proceeding to A3 predictor use.

## A0 boundary and provenance

- Input: exactly 30 frozen V2-A predictors, F1-F4 only; no A3 predictors were loaded.
- Graph: 10,037 nodes and 77,614 directed queen edges; fixed node order; no response or domain changes.
- Temporal contract: 52 warm-up weeks, 13-week TBPTT, development folds F1-F4 only; terminal/later outcomes excluded.
- Fixed hurdle parameter: theta = 0.7018903965556372; no re-estimation.
- Source provenance: `feature/stgnn-a3-ablation` at `4797edff54c019cdd978b92e57413b58992d18ec`; audit branch starts from consolidated `main`.

## Deterministic objective audit

The current `balanced_multitask_loss` is **not** the exact observation-level joint hurdle negative log-likelihood. The single-positive terms agree, but the current loss uses a positive-count denominator and is undefined for a batch containing no positive observations. The material batch differences were:

- mixed `[0,1,2,100]`: current minus exact = `2.493114699`;
- rare-positive `[0,0,0,0,1]`: current minus exact = `0.995312096`;
- rare-positive gradient cosine = `0.793447`.

The exact loss was therefore used for N2-N4. It improved the objective, but N1-E remained invalid.

## Graph audit

The persisted graph passed the structural checks: 10,037 nodes, 77,614 directed edges, 4 connected components, 3 isolates, zero missing reverse edges, zero duplicates, and zero self-loops. N2 implicated the graph component because the non-graph GRU improved mean NLL from 0.411013 to 0.321573, but its Brier skill remained negative (-2.783580). N3 K1 was modestly better than K3 but remained invalid.

## Paired phase results

| model | runs | mean joint NLL | mean PR-AUC | mean Brier skill | count MAE | calibration intercept | calibration slope | valid |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| N1-R | 20 | 0.454955 | 0.086126 | -5.938873 | 1.915214 | 1.095273 | 6.112684 | no |
| N1-E | 20 | 0.411013 | 0.026727 | -4.878234 | 1.842956 | -4.016148 | -1.009804 | no |
| N2-G0 | 20 | 0.321573 | 0.039942 | -2.783580 | 1.885959 | -1.843337 | 0.501255 | no |
| N2-R | 20 | 0.411013 | 0.026727 | -4.878234 | 1.842956 | -4.016148 | -1.009804 | no |
| N3-K1 | 20 | 0.408927 | 0.025379 | -4.457243 | 1.860068 | -5.787732 | -1.748819 | no |
| N3-K3 | 20 | 0.411013 | 0.026727 | -4.878234 | 1.842956 | -4.016148 | -1.009804 | no |
| N4-E12 | 20 | 0.411013 | 0.026727 | -4.878234 | 1.842956 | -4.016147 | -1.009803 | no |
| N4-E36 | 20 | 0.183256 | 0.106408 | -0.502420 | 2.000843 | 10.551985 | 6.348592 | no |


N4 showed the strongest improvement: E36 reduced mean joint NLL to 0.183256 and increased mean PR-AUC to 0.106408, but mean Brier skill remained -0.502420, with materially non-ideal calibration (intercept 10.551985, slope 6.348592). Duration therefore improves the diagnostic result without restoring the validity gate.

## Training, temporal, and prediction checks

- All 160 task records completed successfully on Atlas; all were finite and nondegenerate.
- The training loop resets hidden state per task, replays the 52-week warm-up without response loss, trains contiguous 13-week TBPTT chunks, and detaches hidden state between chunks.
- The fold/seed, weekly calibration, prediction-distribution, count-summary, and training-behavior tables are preserved in `results/`. Optional raster figures were not generated because matplotlib is unavailable in the Atlas runtime.

## Boundary checks and final recommendation

All boundary checks are false: A3 predictors used, F5/F6 used, terminal/later outcomes used, feature selection reopened, feature set changed, response changed, theta changed/re-estimated, and main merged. The final recommendation is to retain the frozen 30-predictor A0 specification as the analysis boundary only, do not freeze any tested neural configuration as a validated baseline, and stop before A3 augmentation or feature selection reopening.
