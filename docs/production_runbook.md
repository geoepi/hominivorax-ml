# STRUCTURED_A3 P6 operational runbook

This runbook describes issue-time inference with the declared frozen
`STRUCTURED_A3` artifact and `E0_LAST_AVAILABLE` contract. P6 does not train or
refit. The latest isolation record still identifies the W29 full-fit as the
active production artifact; reconcile the declared model/configuration with
that deployment record before a run. The W44 candidate is not production
qualified and is not an authorized P6 input.

## Routine preflight

Run `analysis/p6_production_hardening/scripts/p6_production.py --mode
preflight` with a new run ID, issue week, explicit output root, validated input
bundle, and P4 reference root. Use an Atlas configuration that has been
validated for the intended deployment. Review `input_readiness.json`. `READY`
is required for prospective inference. `READY_WITH_WARNINGS` is permitted only
for warnings explicitly listed in that configuration. `BLOCKED_*` states
require correction or a separately governed replay. Preflight must report
`L(T)=T-1`, all three target weeks, source hashes, and no future-dated source.

## Normal inference run

Use `--mode production` with the same declared inputs after successful
preflight. The command verifies the frozen artifact and contracts, builds E0,
validates spatial/temporal inputs, runs inference, recomputes P4 support,
validates the stable output schema, and writes an immutable run directory. It
does not update the model or the active deployment pointer. The terminal state
is `RUN_COMPLETE`; the embedded status may indicate warnings. Do not copy or
rename a completed run into the canonical root.

## Verification and historical replay

Use `--mode verify --output-root <completed-run> --config <config>` to check the
manifest/config hash, output checksum, schema, row count, support classes, and
completion markers. Verification is read-only.

Use `--mode replay` with a separate output root for reproducibility or
operational testing. Replay is labeled `HISTORICAL_REPLAY`, preserves source
timestamp/history-cutoff limitations, and is not prospective evidence. Never
use a replay root as the production root.

## Warnings, blockers, and recovery

`CAUTION_SUPPORT`, `EXTRAPOLATIVE_SUPPORT`, `PARTIAL_UNCERTAINTY`, and
`REVIEW_REQUIRED` remain visible in output and monitoring records. Missing
inputs, future-dated or unknown-vintage environmental inputs, an E0 reference
other than `T-1`, invalid grids, schema changes, model/support hash mismatch,
and history cutoffs after the issue week block prospective operation. No stale
or newer environmental state may be silently substituted.

Inspect `status.json`, `failure.json`, and stage directories after an
interrupted run. Preserve the original logs and increment `--attempt`. Resume
only when run ID, configuration, model, and input identity match. A completed
root is immutable. A duplicate completed identity returns
`DUPLICATE_COMPLETED_RUN`; checksum failures require a separate review, not an
in-place repair.

## Delayed outcomes and rollback

When outcomes mature, populate the separate delayed-outcome evaluation
template keyed by run ID, issue week, target week, horizon, and canonical cell.
Write a new evaluation artifact; do not edit prediction files or the original
run manifest. A revised environmental product may be used only in an explicit
replay. Rollback selects a previously validated software/configuration
version, verifies model/proxy/support/schema hashes, and runs preflight before
inference. A warning never triggers automatic rollback or retraining.
