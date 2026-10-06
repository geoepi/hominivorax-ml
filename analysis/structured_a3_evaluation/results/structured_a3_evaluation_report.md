# Frozen STRUCTURED A3 evaluation report

## 1. Objective

This workstream was authorized to evaluate the frozen STRUCTURED A3 model
outside the F1--F4 development-selection period, separating historical exposed
holdout evidence from genuinely untouched prospective evidence.

## 2. Frozen model

The pre-evaluation manifest records exactly 34 predictors, penalty `0.01`, fixed
theta `0.7018903965556372`, `exact_joint_hurdle_nll`, and the 10,037-node revised
domain. The final fit would use development responses from 2025-W01 through
2026-W16 only, with development-fit preprocessing parameters.

## 3. Evaluation provenance

F5 (2026-W17--2026-W22) and F6 (2026-W23--2026-W29) are classified as
`HISTORICAL EXPOSED HOLDOUT`. Persisted project documentation identifies them as
historical pseudo-prospective/non-independent periods, and the terminal horizon
was already reported. They cannot be called independent or prospective.

No later eligible period could be established from the accessible workspace.
See `evaluation_period_provenance.csv`.

## 4. Data availability and stop condition

The protected authoritative model-output bundle, causal front-feature table,
anthropogenic static A3 features, soil static A3 features, and observation
source are not mounted in the accessible workspace. The only local project
content under `D:/project/disease_ecology/STGNN-output` is a partial soil
screening directory without the required node feature artifact.

Per the task stop conditions, scoring stopped before loading response arrays or
generating evaluation metrics. No data refresh was performed, and no later
observation endpoint was inferred.

## 5. Leakage and preprocessing audits

The frozen manifest records the causal rule that every history/front feature for
week `t` may use only weeks `< t`, and that evaluation data may not be used to
fit scaling. The executable audits are marked `NOT_RUN` because their required
authoritative inputs are unavailable. No claim of successful leakage or
preprocessing verification is made.

## 6. Historical holdout results

No historical A3 metrics were generated. The required metric tables contain
explicit blocked statuses rather than fabricated values. Historical exposure is
established as provenance, but STRUCTURED A3 historical generalization is not
assessable from this workspace.

## 7. Prospective results

NO INDEPENDENT PROSPECTIVE EVALUATION AVAILABLE.

The prospective comparison file records `NO ELIGIBLE PROSPECTIVE PERIOD`.

## 8. A0 versus A3 comparison

No paired A0/A3 holdout or prospective metrics were generated because the
authoritative inputs are unavailable.

## 9. U.S. transfer performance

No U.S. transfer metrics were generated. Sparse-U.S. interpretation therefore
cannot be performed.

## 10. Calibration

Calibration was not evaluated. No discrimination or calibration claim is made.

## 11. Count performance

Count performance was not evaluated. No conclusion about positive-count
overprediction can be drawn.

## 12. Generalization classification

Historical: `NOT ASSESSED` because the exposed periods could not be scored in
this workspace.

Prospective: `PROSPECTIVE GENERALIZATION NOT YET TESTED`.

## 13. Final interpretation

This run establishes the frozen A3 evaluation boundary and provenance ledger;
it does not establish model generalization. A protected-data execution is
required before any historical or prospective performance claim can be made.

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

## Final classification

```text
HISTORICAL GENERALIZATION:
NOT TESTED IN THIS EXECUTION

PROSPECTIVE GENERALIZATION:
NOT YET TESTED
```

## Production-readiness decision

```text
A3 REQUIRES FURTHER EXTERNAL/PROSPECTIVE VALIDATION
```
