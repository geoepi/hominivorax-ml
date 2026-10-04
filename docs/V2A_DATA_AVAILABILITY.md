# V2-A Data Availability Audit

## Operational contract

V2-A is evaluated operationally as a delayed prospective nowcast conditional
on complete current-week environmental covariates becoming available after the
represented week and before the corresponding observation outcomes are known to
the workflow. Detection/event dates and information-availability dates are
tracked separately.

## Environmental bundles

For every represented week the harness records the bundle path, a content
checksum, file modification time, first verified availability timestamp,
complete-predictor count, and readiness status in
`environment_bundle_history.parquet`. The production contract requires all 12
dynamic predictors, the expected grid identity, the expected node order, and
finite values. Missing, wrong-week, wrong-grid, or non-finite input fails the
readiness check; no forward-filling is performed.

The currently available historical predictor array is a retrospective project
artifact. It has no per-variable acquisition chronology, so its operational
availability is classified as `uncertain` unless an operator supplies a
verified bundle timestamp. The harness measures
`availability_lag_days` relative to represented week end once verified bundles
accumulate; it does not hard-code the expected seven-to-fourteen-day lag.

## Observation source chronology

Each source revision is retained in
`source_history/observation_source_history.parquet` with path, SHA-256, row
count, file timestamp, first-seen timestamp, date range, new-row counts, and
backfill counts. Where row-level ingestion timestamps are absent, the first
source revision containing a row is the conservative
`observed_first_available_timestamp`.

The current authoritative file is a historical snapshot through 2026-W29.
Because its week-t outcomes were already present before the Task 3D readiness
check, W29 is `outcome_already_available`, not an eligible nowcast window.
Event date alone never establishes prospective eligibility.

## Nowcast window

For week *t*, the window opens at the first verified complete environmental
bundle timestamp and closes when week-*t* outcomes become available to the
workflow. The readiness mode reports both timestamps when they are known. If
either side is unknown, the run is `availability_uncertain` and is excluded
from genuine prospective scoring.

## Current limitations

The existing holdings do not provide a routinely timestamped sequence of
future observation-source releases or verified per-week environmental bundle
acquisition times. The first operationally eligible window must therefore be
created from a post-freeze source/bundle chronology, not reconstructed from the
historical snapshot. Historical sandbox reenactments are QA only.

