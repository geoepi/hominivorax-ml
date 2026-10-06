# 006 — STRUCTURED A3 development freeze

## Question

Which structured hurdle specification should be carried forward after F1–F4 development comparison?

## Decision

Freeze STRUCTURED A3: 34 predictors, penalty `0.01`, fixed `theta = 0.7018903965556372`, exact joint hurdle NLL, and 10,037 nodes.

## Evidence

All eight A0/A3 fixed-theta fits completed. A3 improved joint NLL, PR-AUC, Brier skill, count MAE, and count RMSE in all four F1–F4 folds. No F5/F6 outcomes, terminal later outcomes, neural fits, graph fits, or feature-selection reopening were used.

## Rejected alternatives

V2-A/A0 remains the paired reference, but is not the preferred final development specification. Neural/GNN candidates were not included in the final comparison.

## Provenance and status

Relevant branch/commit: `feature/structured-a3-final-comparison` at `93ecc92`; final manifest and report are under `analysis/structured_a3_final_comparison/results/`. Status: **current frozen development specification**.
