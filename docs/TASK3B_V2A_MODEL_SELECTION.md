# Task 3B — V2-A Model Development and Selection

This document records the historical development comparison of the frozen V1 benchmark and the two authorized V2-A candidates. It must not be interpreted as a final V2 validation: all currently available 2025–2026 outcomes are previously seen historical data.

## Models and validation

M0 is `STGNN-Hurdle-V1` reproduced without specification changes. M1 is V2-A with the three causal recorded-detection history features. M2 is the single latitude ablation. The six rolling-origin folds are exactly:

| Fold | Training | Validation | Status |
|---|---|---|---|
| 1 | 2025-W01–W26 | 2025-W27–W39 | historical development |
| 2 | 2025-W01–W39 | 2025-W40–W52 | historical development |
| 3 | 2025-W01–W52 | 2026-W01–W08 | historical development |
| 4 | 2025-W01–2026-W08 | 2026-W09–W16 | historical development |
| 5 | 2025-W01–2026-W16 | 2026-W17–W22 | historical pseudo-prospective, non-independent |
| 6 | 2025-W01–2026-W22 | 2026-W23–W29 | historical pseudo-prospective, non-independent |

M0 is fixed at penalty 0. M1 and M2 use only the authorized grid `0`, `1e-4`, `1e-3`, `1e-2`; penalty selection uses Folds 1–4 only, minimizing mean joint hurdle NLL with Brier skill and then smaller penalty as tie-breakers.

## Results

The final fold-level metrics, regularization comparison, first-ever versus recurrent diagnostics, new-cell ranks, transfer diagnostics, calibration, count diagnostics, coefficient stability, and collinearity are machine-readable under `STGNN-output/v2_model/metrics/`. The decision and selected penalties are recorded in `metrics/task3b_decisions.json` and `manifests/task3b_v2a_manifest.json`.

The final decision classification is populated only after the CPU workflow completes. No V2-B, V2-C, V2-D, GRU, or GConvGRU model is fitted in Task 3B.

