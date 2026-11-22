# Structured A3 production and validation entrypoint inventory

The P6 inference implementation, P0–P5 full-fit/evaluation pipeline, and W44
candidate refresh are separate pathways. A tracked example config does not
prove the current Atlas deployment. The [current status](../current/status.md)
records the latest artifact identities and their limits.

| Supported command / path | Primary implementation | Inputs | Outputs | Fits model? | Changes active production state? | Status | Relevant checks and documentation |
|---|---|---|---|---|---|---|---|
| P6 `preflight` | `analysis/p6_production_hardening/scripts/p6_production.py` | Declared issue week, model/config, canonical predictors, issue-time environmental source, P4 reference, explicit run root | Readiness report, source identities, blocked/warning details | No | No | Documented hardened inference preflight for the frozen W16 contract | `analysis/p6_production_hardening/scripts/test_p6_production.py`; [runbook](../production_runbook.md) |
| P6 `production` | Same P6 script | Inputs that passed P6 readiness and the `E0_LAST_AVAILABLE` contract | Immutable h=1–3 inference, expected counts, support classes, uncertainty/provenance, completion manifest | No; inference only | Writes a run-specific artifact; does not update the deployment pointer | Documented operational inference path. Active Atlas use must be reconciled with the W29 deployment isolation record | P6 focused tests and `analysis/p6_production_hardening/results/p6_decision.json`; [Atlas paths](../current/atlas.md) |
| P6 `verify` / `replay` | Same P6 script | Completed output root or explicitly identified historical inputs | Read-only verification, or separately rooted `HISTORICAL_REPLAY` | No | No | Supported verification and replay modes; replay is not prospective evidence | P6 focused tests; [runbook](../production_runbook.md) |
| P0–P5 `production_fullfit` | `slurm/submit_a3_pipeline.sh` → `scripts/a3_pipeline.py` → `scripts/a3_preflight.py`, `a3_preprocess.py`, `a3_fit.py`, `a3_score.py`, `a3_products.py`, `a3_finalize.py`; fit/render implementations in `analysis/structured_a3_fullfit/` | Atlas configuration, accepted input bundle, model freeze, output root | New full-fit model, descriptive predictions, GeoTIFFs, tables, reports, checksums | Yes, exactly one full fit | Writes a versioned full-fit run; no automatic deployment/promotion | Supported descriptive full-fit pipeline; separate from P6 inference | `tests/test_fullfit_output_manifest.py`; `slurm/submit_a3_pipeline.sh`; [Atlas documentation](../current/atlas.md) |
| P0–P5 `prospective_evaluation` | Same P0–P5 orchestration; `scripts/a3_score.py --no-refit` | Deployed frozen model manifest and complete eligible post-horizon weeks | Separate prospective score artifacts and manifest | No | Writes a separate evaluation root; no deployment update | Supported no-refit scoring mode, with eligibility governed by the configured contract | Pipeline contract tests; [Atlas documentation](../current/atlas.md) |
| W44 development candidate refresh | `scripts/w44_execution_preflight.py`, `scripts/run_task2e_refresh.R`, `hpc/run_task2e_refresh.sbatch` on `analysis/structured-a3-2026w44-refresh` | Accepted corrected W44 observation source, environmental products, frozen specification, isolated worktree | `STRUCTURED_A3_2026W44` candidate and descriptive full-fit products under `/project/disease_ecology/STGNN-output/structured_a3_refresh_2026w44` | Yes | No; dedicated development root | Completed for the W44 candidate; `CANDIDATE_READY_FOR_REVIEW_NOT_PRODUCTION_QUALIFIED`. No further refresh is authorized here | W44 preflight/output-integrity checks on the candidate branch; current status page and W44 decision report |
| W44 Q1 retrospective | `analysis/structured_a3_data_refresh_2026w44/qualification_execution/run_w44_q1_retrospective.py` plus `hpc/run_w44_q1_*.sbatch` on W44 branch | W44 candidate identity, historical source, 26-origin design | Aggregate repository report/CSVs; row-level prediction archive and logs remain on Atlas | Yes, origin-specific retrospective fits | No | Completed; targets are ineligible for confirmatory scoring due uncertified maturity; decision `NOT_ASSIGNED`. No further run authorized | Six focused Q1 tests passed on Atlas; Q1 report on W44 branch |
| Point-level proximity analysis | `analysis/a3_point_spatiotemporal_clustering/scripts/run_point_clustering.py` and `hpc/run_point_clustering.sbatch` on W44 branch | Original point coordinates and W44 observation vintage | Aggregate CSV/SVG summaries and scientific report; no row-level points committed | No | No | Complete descriptive study; decision `POINT_PROXIMITY_CHALLENGER_NOT_JUSTIFIED`; no follow-up authorized | [Decision register](../current/model_development_decisions.md); point study report on W44 branch |
| P7 publication artifact build | `analysis/p7_publication/scripts/build_publication_artifacts.R` | Tracked P1–P6 artifacts and publication configuration | Publication tables, figures, manifests, and synthesis | No | No | Conditional release-facing documentation build | P7 report and [qualification summary](../model_qualification_summary.md) |

## Boundaries and maintenance notes

- `production_fullfit`, P6 issue-time inference, and the W44 development
  candidate refresh are not interchangeable commands. Their inputs, output
  roots, model-fit behavior, and production effects differ.
- A successful full fit or candidate-refresh workflow does not update the
  active model pointer. W44 remains unpromoted.
- The current active production artifact is the W29 full fit according to the
  latest isolation record. The P6 tracked config identifies the frozen W16
  model contract; resolve that identity difference before any deployment use.
- Atlas code should use repository bootstrap scripts and wrappers. Do not
  infer an active environment from an example config, create alternate
  environment stacks, or submit work outside a separately authorized task.
- Experimental A4/A5/A5B/A6 branches are historical research artifacts, not
  supported production entrypoints. Their decision and preservation status is
  in `docs/current/model_development_decisions.md` and the maintenance
  reconciliation records.
