# A5-GNN bounded comparison report

## I. Governance

This is a supervised-agent, development-only comparison. The frozen Structured A3 artifact and frozen A4-S challenger were treated as immutable. Atlas access used the authorized WSL/Ubuntu `atlas-ssh` route. No production tag, release, or merge was created.

## II. Canonical starting state

Starting SHA: `6715a4397dad21a77414bd2ce41586751290f374`. Execution SHA: `b33a2ab`. Branch: `feature/a5-gnn-bounded-comparison`. Development boundary: `2025-W01` through `2026-W16`; only F1--F4 were selection-eligible.

## III. Software/environment audit

{'python': '3.12.14', 'numpy': '2.5.3', 'pandas': '3.0.6', 'scipy': '1.18.1', 'torch': '2.10.0', 'torch_geometric': True, 'torch_geometric_temporal': True, 'cuda_available': True, 'cuda_version': '12.8', 'gpu': 'NVIDIA A100-SXM4-80GB', 'device_used': 'cuda', 'output_root': '/90daydata/disease_ecology/hominivorax-ml/a5_gnn_bounded_comparison/run_20261101T201500Z_b33a2ab', 'durable_summary_root': '/project/disease_ecology/STGNN-output/_WORKTREES/a5-gnn-bounded-comparison/analysis/a5_gnn_bounded_comparison', 'temporary_storage_class': 'TEMPORARY_90DAY_STORAGE', 'xdg_cache_home': '/90daydata/disease_ecology/hominivorax-ml/a5_gnn_bounded_comparison/run_20261101T201500Z_b33a2ab/cache/xdg', 'torch_home': '/90daydata/disease_ecology/hominivorax-ml/a5_gnn_bounded_comparison/run_20261101T201500Z_b33a2ab/cache/torch', 'tmpdir': '/90daydata/disease_ecology/hominivorax-ml/a5_gnn_bounded_comparison/run_20261101T201500Z_b33a2ab/tmp'}. The local Windows environment did not provide the required Python/R runtime; Atlas supplied the supported Python environment. Large runtime products remain under TEMPORARY_90DAY_STORAGE and are automatically removed after 90 days without activity.

## IV. A3 reproduction

The canonical fixed-theta A3 fit was reproduced independently within each outer fold before neural fitting. The exact-loss reproduction gate is stored in `results/a3_baseline_reproduction.csv`.

## V. A5-GNN architecture

A5-GNN is a two-layer mean-aggregation GraphSAGE residual model with separate occurrence and positive-count branches, hidden width 16, ReLU, dropout 0.10, AdamW, learning rate 1e-3, weight decay 1e-4, and gradient clipping 1.0. The exact trainable parameter count is recorded in `fold_seed_metrics.csv`. A5-PE is the node-wise MLP control; A5-GNN-NOPE omits positional encodings.

## VI. Leakage and causal-timing verification

Inputs are the standardized 34 causal A3 predictors, frozen A3 offsets, standardized node coordinates, and eight response-independent graph-Laplacian eigenvectors. Neighbor outcomes and residuals are never included. The graph is deterministic, bidirectional, outcome-free, and has no explicit self-loops; self-information is supplied by GraphSAGE concatenation.

## VII. Predictive results

A3 mean PR-AUC was `0.474135`, Brier skill `0.370679`, and joint hurdle NLL `0.076333`. A5-GNN mean-over-seed/fold PR-AUC was `0.513739`, Brier skill `0.363890`, and joint hurdle NLL `0.076200`. Full fold/seed metrics, including count MAE/RMSE/bias, totals, ROC-AUC, calibration, and ZTNB NLL, are machine-readable in `results/`.

## VIII. Residual spatial dependence

First-shell occurrence residual Moran's I was `0.293260` for A3 and `0.301054` for A5-GNN (reduction `-0.007793`). First-shell positive-count residual Moran's I was `0.363370` for A3 and `0.363276` for A5-GNN (reduction `0.000095`). Shells 1--4, deterministic permutation p-values, valid-value counts, graph-pair counts, and residual maps are in `results/`.

## IX. Residual temporal dependence

Same-cell residual correlations at lags 1--3 are reported separately for occurrence, full hurdle count, and estimable positive-count residuals. A5-GNN is non-recurrent; remaining temporal dependence is therefore documented rather than modeled away.

## X. Ablation results

A5-PE, A5-GNN-NOPE, and A5-GNN used identical folds, seeds, loss, optimizer settings, and training-duration protocol. The comparison is descriptive and was prespecified before outer-fold results were read.

## XI. Spatial stress test

Spatial stress-test status: `COMPLETED`. The existing deterministic spatial partition was used when available; held-out outcomes were excluded from training loss, and stress-test results were not used for model selection. A4-S was not refit in the stress test because its frozen artifact is immutable.

## XII. Seed stability

Three fixed seeds were applied to every A5 variant. Seed-level summaries are included; figure-generation status is recorded separately because the supported Atlas environment may not provide matplotlib. The guardrail evidence reports PR-AUC seed SD `0.0033469186665952225`.

## XIII. Guardrail assessment

Predictive preservation: `{'mean_pr_auc': True, 'mean_brier_skill': True, 'worst_fold_pr_auc': True, 'calibration_intercept': True, 'calibration_slope': True, 'joint_hurdle_nll': True}`. Spatial guardrails: `{'occurrence': False, 'positive_count': False}`. Graph-ablation evidence: `{'gnn_joint_nll_not_worse': True, 'graph_structural_advantage': False}`. These are development guardrails only.

## XIV. Limitations

The analysis uses recorded detections, not latent abundance. Residual spatial improvement does not identify causal transmission, dispersal, surveillance effort, intervention effects, or biological mechanism. The development period is historical and cannot establish prospective validity. The neural challenger is deliberately shallow and non-recurrent.

## XV. Primary decision

`A5_GNN_NOT_SUPPORTED`

The scientific conclusion is therefore: shallow graph message passing did not capture materially useful spatial information according to the prespecified quantitative guardrails beyond Structured A3 and simpler positional corrections; this conclusion does not authorize deployment.

## XVI. Repository/PR state

Branch: `feature/a5-gnn-bounded-comparison`. No merge was performed. The production A3 artifact hash check and A4-S manifest checks are recorded in `provenance/a5_analysis_manifest.json`. A PR remains a separate handoff step.
