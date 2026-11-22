# Atlas execution paths and operations

Atlas deployment is controlled by protected configuration and explicit
release decisions. Updating the repository or `main` does not change the
deployed model. The latest documented isolation record identifies the W29
full-fit as the active production artifact; see the [current status](status.md).
The Git-tracked Atlas configuration files are examples, not proof of the
deployed tag or active path.

## P6 issue-time operational inference

The documented hardened inference implementation is
`analysis/p6_production_hardening/scripts/p6_production.py`. It verifies the
declared model and input contracts, builds the `E0_LAST_AVAILABLE` predictor
view, produces h=1–3 inference with P4 support classes, and writes an immutable
run-specific output. It does not fit, recalibrate, retune, or promote a model.

Use the [production runbook](../production_runbook.md) and a separately
validated Atlas configuration for `preflight`, `production`, `verify`, or
`replay`. The tracked `config/p6_production_config.json` describes the frozen
W16 model contract; it does not establish that P6 replaced the W29 artifact in
the active deployment. Reconcile model and configuration identity before any
operational run.

## P0–P5 full-fit and prospective-evaluation pipeline

`slurm/submit_a3_pipeline.sh` submits the P0→P5 chain from
`scripts/a3_pipeline.py`:

```bash
bash slurm/submit_a3_pipeline.sh --mode production_fullfit \
  --config /project/disease_ecology/STGNN-production-config/atlas-production.yaml
bash slurm/submit_a3_pipeline.sh --mode prospective_evaluation \
  --config /project/disease_ecology/STGNN-production-config/atlas-production.yaml
```

`production_fullfit` fits the frozen scientific specification once on the
latest accepted complete input horizon and writes descriptive fitted-period
products. Its updated coefficients are not prospective validation and are not
deployed automatically. `prospective_evaluation` uses the deployed frozen
artifact, performs no refit, and writes eligible post-horizon scores to its
separate output root. Use `--dry-run` to inspect the dependency chain before
submission. This pipeline is distinct from P6 inference.

## W44 candidate-refresh development workflow

The W44 candidate refresh is a development workflow represented by
`scripts/w44_execution_preflight.py`, `scripts/run_task2e_refresh.R`, and
`hpc/run_task2e_refresh.sbatch` on the consolidated W44 branch. It created
`STRUCTURED_A3_2026W44` in the separate development root
`/project/disease_ecology/STGNN-output/structured_a3_refresh_2026w44`.
That candidate remains `CANDIDATE_READY_FOR_REVIEW_NOT_PRODUCTION_QUALIFIED`.
Its presence in the W44 branch does not change production configuration or
authorize another refresh, qualification run, or promotion.

The Q1 retrospective workflow is separately recorded under
`analysis/structured_a3_data_refresh_2026w44/qualification_execution/` on the
W44 branch. It completed 26 origin fits, but outcomes are not certified as
mature; its scientific qualification decision is `NOT_ASSIGNED`. Row-level
predictions and logs remain on Atlas.

## Run identity, recovery, and cancellation

For P0–P5, inspect its submission manifest, stage/job IDs, dependency chain,
and logs. Status and cancellation commands are documented with the launcher.
For P6, use `status.json`, `failure.json`, and the declared run root; resume an
incomplete identity only when model, configuration, inputs, and run ID match.
Completed P6 runs are immutable. Do not copy or rename output directories or
substitute stale environmental products. A replay requires a separate,
explicitly named root and is not prospective evidence.

An optional `CHIME_EXECUTION_ID` may be captured as opaque provenance by the
P0–P5 launcher. It does not change run IDs, model inputs, scientific outputs,
or execution policy; unset and blank values are recorded as null.
