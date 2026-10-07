# Structured A3 production entrypoint inventory

This inventory records the production adapters introduced for the Structured
A3 release. The adapters are intentionally thin: the frozen model contract,
feature construction, fixed-theta optimizer, prediction function, and spatial
renderer remain in the validated implementations identified below.

| Pipeline stage | Stable entrypoint | Validated implementation invoked | Production responsibility |
|---|---|---|---|
| P0 | `scripts/a3_preflight.py` | `run_fullfit_products.py::load_bundle` and `::completeness` | Validate input existence, model specification, complete horizons, and strictly prior history; persist `preflight_summary.json` and leakage evidence. |
| P1 | `scripts/a3_preprocess.py` | `run_fullfit_products.py::load_bundle` and `::completeness` | Persist the run-specific horizon, support audit, feature order, and preprocessing manifest without fitting. |
| P2 | `scripts/a3_fit.py` | `analysis/structured_a3_fullfit/scripts/run_fullfit_products.py fit` | Run exactly one production full fit using the frozen theta, penalty, objective, predictor order, and convergence checks. |
| P3 production | `scripts/a3_score.py` | `run_fullfit_products.py` outputs and `run_predictor_augmentation.py::predict` | Validate the full-fit prediction archive and score-stage provenance; no second fit is performed. |
| P3 prospective | `scripts/a3_score.py --no-refit` | `run_fullfit_products.py::load_bundle` and `run_predictor_augmentation.py::predict` | Load the deployed model artifact, identify complete weeks strictly after the deployed evaluation horizon, and return `no_eligible_weeks` successfully when none exist. Refit functions are not called. |
| P4 | `scripts/a3_products.py` | `analysis/structured_a3_fullfit/scripts/render_fullfit_spatial.R` | Render and QA weekly GeoTIFFs, raster summaries, nowcast PDFs, tables, and interpretation products. |
| P5 | `scripts/a3_finalize.py` | `run_fullfit_products.py finalize` | Write the run-specific artifact manifest, checksums, report, and final summary. |

## Orchestration contract

`scripts/a3_pipeline.py` remains the only submission coordinator. It submits
P0 through P5 with `afterok` dependencies and validates the frozen scientific
manifest before submission. Production and prospective modes use distinct
output roots, and each invocation appends its `run_id` to the configured root.

The Atlas template uses the canonical Python environment for all Python stages
and loads the pinned R/GDAL/PROJ/GEOS stack only for P4. No credentials are
stored in the repository. The production configuration is copied to the
protected Atlas configuration path separately from the repository checkout.

## Scientific invariants

The adapters do not change the frozen specification: 34 predictors, 10,037
canonical nodes, fixed `theta = 0.7018903965556372`, penalty `0.01`, and
`exact_joint_hurdle_nll`. `production_fullfit` is descriptive fitted-period
output. `prospective_evaluation` is frozen-model scoring only and is never
allowed to refit or retrain.
