# Task 2A validation design

Status: verified on Atlas in SLURM job `20839532`. Persisted split and scaler manifests are under `/project/disease_ecology/STGNN-output/model_data/{splits,scaling}/`.

## Temporal holdouts

The final test period is programmatically reserved as 2026-W04 through 2026-W29, 26 weeks. The development period is 2024-W01 through 2026-W03, 107 weeks. No predictive metric is calculated for the final test period; its QA is limited to interval, shape, and finiteness checks.

The four expanding-window folds are:

| Fold | Training | Validation |
|---:|---|---|
| 1 | 2024-W01–2024-W52 | 2025-W01–2025-W13 |
| 2 | 2024-W01–2025-W13 | 2025-W14–2025-W26 |
| 3 | 2024-W01–2025-W26 | 2025-W27–2025-W39 |
| 4 | 2024-W01–2025-W39 | 2025-W40–2025-W52 |

Weeks 2026-W01–2026-W03 remain available for the final development fit after model selection.

## Spatial and combined partitions

Spatial blocks are deterministic 5 × 5 full-raster cells. The 845 observed blocks are assigned round-robin in sorted raster row/column order to five folds, without using response prevalence. Node counts are 3,472, 3,368, 3,400, 3,264, and 3,252 across folds 0–4. Every node is assigned exactly once.

Combined masks are persisted for every temporal-fold × spatial-fold pair. Training loss masks include only temporal training weeks and non-held-out spatial nodes. Evaluation masks include only temporal validation weeks and the held-out spatial nodes. The fixed queen graph is unchanged and remains transductive; held-out targets are excluded from loss.

The graph has 31 connected components and 17 singleton components. The largest component has 16,385 nodes; the next largest has 172. Component membership, geographic extent, and whether observations occur are persisted in `diagnostics/graph_components.json` and `diagnostics/component_by_node.parquet`. The isolated nodes are retained.

## Leakage controls

Environmental features use identity transformation. The five density features use `log1p`; indicators remain binary. Every temporal-fold scaler is fitted only on that fold’s training node-weeks, and a separate final-development scaler is persisted. Raw arrays are never overwritten.

Synthetic perturbation tests changed validation features and validation targets while checking that training features, training inputs, and scaler parameters were unchanged. All four tests passed. The final-test QA confirms 26 weeks, dynamic shape `[26, 16756, 12]`, count shape `[26, 16756]`, and finite dynamic values, with `predictive_metrics_calculated: false`.
