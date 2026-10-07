# STGNN-Hurdle-V1 model card

## Status

`STGNN-Hurdle-V1` is frozen and is the immutable benchmark for all subsequent
V2 development. Its former terminal period, 2026-W17 through 2026-W29, is now
classified as `historical_evaluated_data`. It must not be described again as an
unseen test set or as an independent final test.

## Model specification

| Item | Frozen definition |
| --- | --- |
| Model identifier | `STGNN-Hurdle-V1` |
| Model family | Current-week hurdle model |
| Occurrence model | Bernoulli/logistic |
| Positive-count model | Zero-truncated negative binomial |
| Predictors | 24 |
| Regularization | Penalty = 0 |
| Dispersion | One learned global theta |
| Domain | Mexico plus the retained U.S. footprint below 40°N |
| Domain size | 10,037 nodes; 77,614 directed queen edges; 4 components; 3 isolates |
| Response start | 2025-W01 |
| Development end | 2026-W16 |
| Former terminal end | 2026-W29 |
| Observation source SHA | `a3d55f3ddf867087b578df803920bf59c6c303fa695e3218a5f3463e596d497e` |

Dynamic environmental predictors use identity transforms followed by
development-fit mean/std scaling. Livestock densities use `log1p` followed by
development-fit preprocessing. Livestock imputation indicators and calendar
terms remain unchanged. No terminal targets were used during fitting.

## V1 result

V1 achieved **PARTIAL GENERALIZATION** on its historical evaluated period.
Full-domain prevalence was 0.040634, mean predicted probability was 0.015339,
observed detections were 11,673, and predicted expected detections were
7,009.48. Brier skill was 0.079974, PR-AUC was 0.212306, ROC-AUC was 0.885607,
and joint hurdle NLL was 0.210440.

The U.S. transfer result was **WEAK / AMBIGUOUS NORTHWARD TRANSFER**. There were
30 positive U.S. node-weeks across 24 nodes and 40 recorded detections. The
first retained U.S. positive occurred in 2026-W23. The U.S. ROC-AUC was 0.595942
and only 6.67% of positive U.S. cases were at or above the 75th within-U.S.
percentile.

## Selection history and limitations

The GConvGRU path was not advanced. Revised-domain Hurdle-Current was advanced
from development data, and structured augmentation remained HOLD / AMBIGUOUS.
V1 therefore remains the benchmark; no augmented model replaced it.

The response is a recorded detection assigned to a node-week. A zero means no
recorded detection, not confirmed biological absence. Passive reporting,
unequal observation opportunity, repeated reporting, and a moving geographic
front limit the interpretation of the hurdle occurrence component. The former
terminal results are motivation for V2 audit work, not a tuning target.
