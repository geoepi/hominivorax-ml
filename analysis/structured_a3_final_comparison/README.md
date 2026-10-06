# Structured A0–A3 final development comparison

This directory records the final structured hurdle-model comparison on the revised 10,037-node domain. It compares the frozen 30-predictor V2-A specification (A0) with the frozen 34-predictor A3 specification, using only F1–F4 development folds, fixed `theta = 0.7018903965556372`, penalty `0.01`, and the exact joint hurdle negative log-likelihood.

The A0 reproduction gate passed within `1e-9` for every persisted fold metric. All eight fits completed and converged. A3 improved joint NLL, PR-AUC, Brier skill, count MAE, and count RMSE in all four folds, including F4. Calibration was preserved and the four additions had stable coefficient signs across folds and both hurdle components.

Final development decision: **ADVANCE**.

Final structured specification: **STRUCTURED A3**.

Final disposition: **STRUCTURED A3 DEVELOPMENT SPECIFICATION FROZEN**.

The result is a development freeze only; it is not terminal or prospective validation. Neural and graph models were not fitted, feature selection was not reopened, and `main` was not merged.

Atlas result artifacts are in `results/`; large task and prediction artifacts remain outside Git under `/project/disease_ecology/STGNN-output/structured_a3_final_comparison/`.
