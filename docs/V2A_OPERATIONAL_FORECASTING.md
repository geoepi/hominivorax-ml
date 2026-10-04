# V2-A Operational Forecasting

The operational entry point is:

```text
python scripts/run_v2a_prospective.py --forecast-week 2026-W30 --mode readiness
python scripts/run_v2a_prospective.py --forecast-week 2026-W30 --mode dry-run
python scripts/run_v2a_prospective.py --forecast-week 2026-W30 --mode forecast
python scripts/run_v2a_prospective.py --forecast-week 2026-W30 --mode score --score-version 1 --outcome-maturity provisional --observation-source /path/to/node_assigned_outcomes.parquet
```

Use `--test-mode` only for historical sandbox validation. Test-mode artifacts are written below `v2_prospective/sandbox/` and do not update the production registry, state, or prospective ledger.

## Operator sequence

1. Run `readiness` and confirm that a complete environmental bundle is verified and that week-*t* outcomes were not already available.
2. Run `dry-run` and confirm the availability-causal history cutoff and frozen model checksum.
3. Run `forecast` and retain the immutable prediction parquet and `.sha256` file.
4. After later outcomes become available, run `score` with an audited node-assigned source and explicit score maturity.
5. Verify the versioned outcome artifact, weekly/cumulative metrics, append-only ledger, and scored map.
6. Review source-refresh provenance, eligibility state, and the prospective status manifest.

The sbatch wrapper is `hpc/run_v2a_prospective.sbatch`. It uses CPU resources only and accepts `FORECAST_WEEK`, `MODE`, `OBSERVATION_SOURCE`, `ISSUE_TIMESTAMP_UTC`, `SOURCE_AVAILABLE_TIMESTAMP_UTC`, `ENVIRONMENT_AVAILABLE_TIMESTAMP_UTC`, `ENVIRONMENT_AVAILABILITY_STATUS`, `HISTORY_MODE`, `SCORE_VERSION`, `OUTCOME_MATURITY`, and `TEST_MODE` through `--export`.

The workflow never retrains coefficients. Retraining, feature changes, recalibration, and front redesign require a separately authorized development task.

Operational terminology is deliberately `delayed prospective nowcast`, not real-time or same-week forecast. The existing production dynamic-environment array is a retrospective artifact with no per-variable acquisition timestamps. The availability audit therefore classifies all 12 current-week environmental predictors as `uncertain`; a true operational prospective nowcast requires a future complete predictor bundle with documented pre-outcome availability.
