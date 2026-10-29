# STRUCTURED_A3 Production Runbook

This runbook operates the qualified `STRUCTURED_A3` model with the versioned
`E0_LAST_AVAILABLE` contract. It does not authorize model changes, threshold
changes, retraining, or automated promotion.

## Routine preflight

Run the canonical P6 command with `--mode preflight`, a new run ID, the issue
week, the validated input bundle, and the P4 reference root. Review
`input_readiness.json`. `READY` is required for a prospective run;
`READY_WITH_WARNINGS` is permitted only for warnings explicitly listed in the
configuration. `BLOCKED_*` states require correction or a separately governed
replay. The preflight must report `L(T)=T-1`, all three target weeks, source
hashes, and no future-dated source.

## Normal production run

Use `--mode production` with the same declared inputs after a successful
preflight. The command verifies the frozen artifact and contracts, builds E0,
validates spatial/temporal inputs, runs inference, recomputes P4 support,
validates the stable output schema, and writes an immutable run directory.
The terminal status is `RUN_COMPLETE`; the embedded status may indicate
warnings. Do not copy or rename a completed run into the canonical root.

## Verification

Use `--mode verify --output-root <completed-run> --config <config>`. Verification
checks the manifest/config hash, output checksum, schema, row count, support
classes, and every completion marker. It does not rewrite the run.

## Historical replay

Use `--mode replay` and a separate output root. Replay is for reproducibility
and operational testing only. It adds `HISTORICAL_REPLAY` and preserves any
source-timestamp/history-cutoff limitations; it is not prospective evidence.
Never use a replay root as the production root.

## Warnings and blocking states

`CAUTION_SUPPORT`, `EXTRAPOLATIVE_SUPPORT`, `PARTIAL_UNCERTAINTY`, and
`REVIEW_REQUIRED` remain visible in the output and monitoring record.
Missing inputs, future-dated environmental inputs, unknown environmental
vintage, an E0 reference other than `T-1`, invalid grids, schema changes,
model/support hash mismatch, and history cutoffs after the issue week block
prospective operation. No stale or newer environmental state may be silently
substituted.

## Interrupted or failed job recovery

Inspect `status.json`, `failure.json`, and the stage directory. Preserve the
original logs and increment `--attempt`. If the root is incomplete and its run
ID/config/input signature match, rerun the same command; deterministic stages
may be regenerated and completed stage artifacts are not treated as final until
`RUN_COMPLETE`. If the identity does not match, use a new root. A completed
root is immutable and must never be restarted in place.

## Duplicate and corruption handling

Rerunning a completed identity in its root returns `DUPLICATE_COMPLETED_RUN`.
Use `verify` to inspect it. If verification reports an output or stage checksum
failure, preserve the original root and open a review; do not repair it in
place. A separate replay or validation root may be created from declared
inputs.

## Delayed outcomes

When observations mature, populate the separate delayed-outcome evaluation
template keyed by run ID, issue week, target week, horizon, and canonical cell.
Write a new evaluation artifact. Do not edit prediction files or the original
run manifest.

## Revised source products and rollback

A revised environmental product does not rewrite historical production output.
It may be used only in an explicitly named replay. Rollback means selecting a
previously validated software/configuration version, verifying its model,
proxy, support, and schema hashes, and running preflight before inference. A
single warning never triggers automatic rollback or retraining.
