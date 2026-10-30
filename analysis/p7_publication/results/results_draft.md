# Results Draft

## Model and retrospective nowcast performance

P2 all-domain Brier scores were 0.0281, 0.0284, 0.0288 for h=1--3 and AUPRC values were 0.4452, 0.4414, 0.4402.
Performance was evaluated retrospectively with explicit horizon labels and
common-week comparisons. The canonical source table reports calibration,
discrimination, prevalence, and sample sizes for each horizon.

## Environmental proxy validation

P5A E0 Brier differences relative to REALIZED_ENV were -0.0000, -0.0000, -0.0000 for h=1--3; the source comparison is paired and uses the same evaluation records.
E0 was selected by the prespecified simplicity-first rule in P5A. This result
supports prospective issue-time input construction with explicit proxy
limitations; it does not turn E0 into a future environmental observation.

## Frontier, counts, support, and production

Frontier strata remain weaker and sparse, count predictions retain measurable
bias, and P4 support flags identify heterogeneous environmental support. P6
demonstrated deterministic replay, restartability, duplicate-run protection,
and corruption detection without changing the scientific model.
