# V2-A Operational Forecasting

The operational entry point is:

```text
python scripts/run_v2a_prospective.py --forecast-week 2026-W30 --mode dry-run
python scripts/run_v2a_prospective.py --forecast-week 2026-W30 --mode forecast
python scripts/run_v2a_prospective.py --forecast-week 2026-W30 --mode score --observation-source /path/to/node_assigned_outcomes.parquet
```

Use `--test-mode` only for historical sandbox validation. Test-mode artifacts are written below `v2_prospective/sandbox/` and do not update the production registry, state, or prospective ledger.

## Operator sequence

1. Run `dry-run` and confirm predictor availability, node order, feature width, model checksum, and the exact prior-week cutoff.
2. Run `forecast` and retain the prediction parquet and `.sha256` file.
3. Verify the registry records the issue timestamp and `awaiting_outcomes` status.
4. After outcomes become available, run `score` with an audited node-assigned source.
5. Verify the outcome artifact, weekly metrics, cumulative metrics, ledger, and scored map.
6. Review source-refresh provenance and prospective status.

The sbatch wrapper is `hpc/run_v2a_prospective.sbatch`. It uses CPU resources only and accepts `FORECAST_WEEK`, `MODE`, `OBSERVATION_SOURCE`, `ISSUE_TIMESTAMP_UTC`, `SOURCE_AVAILABLE_TIMESTAMP_UTC`, and `TEST_MODE` through `--export`.

The workflow never retrains coefficients. Retraining, feature changes, recalibration, and front redesign require a separately authorized development task.

Current operational limitation: the existing production dynamic-environment array is a retrospective artifact with no per-variable acquisition timestamps. The availability audit therefore classifies all 12 current-week environmental predictors as `uncertain`; a true operational prospective forecast requires a future predictor bundle with documented pre-outcome availability.
