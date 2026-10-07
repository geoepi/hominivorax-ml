# STGNN-Hurdle-V1 validation summary

## Development and historical evaluation

The frozen V1 model was fit on 68 development weeks and evaluated once on 13
future weeks. The historical evaluated period is not an untouched test set for
future V2 work.

| Metric | Development four-fold range | Development mean | Historical evaluated result |
| --- | ---: | ---: | ---: |
| Brier skill | 0.02637–0.09856 | 0.05314 | 0.07997 |
| PR-AUC | 0.17816–0.26096 | 0.22738 | 0.21231 |
| Joint hurdle NLL | 0.10969–0.16158 | 0.13220 | 0.21044 |
| Positive-count MAE | 1.42037–3.11982 | 2.37180 | 1.99475 |

The historical result retains useful ranking and Brier skill, but the joint NLL
and calibration deteriorate relative to development. Mexico has Brier skill
0.078999, PR-AUC 0.246035, and ROC-AUC 0.757739. The U.S. has Brier skill
0.187048, but only 30 positive node-weeks, PR-AUC 0.000386, and ROC-AUC
0.595942.

## Freeze and evaluation controls

The model-freeze manifest was written before terminal unlock and records the
exact feature order, development-only preprocessing, optimizer convergence,
coefficients, and theta. The terminal unlock was recorded exactly once. V1
outputs are preserved under
`/project/disease_ecology/STGNN-output/terminal_evaluation/` and archived by
checksum under the V2-audit archive.

## Interpretation

V1 is the benchmark, not a claim of a complete biological occurrence model. It
predicts recorded detection, and its zeros combine non-occurrence, missed
detection, non-reporting, and weak observation opportunity. The first retained
U.S. detections were not localized strongly enough to support a claim of useful
northward transfer. No V2 model should claim improvement solely by fitting or
retesting the same historical evaluated outcomes.
