# P6 Production Hardening and Monitoring Prespecification

**Status:** locked before P6 implementation and replay inspection  
**Scientific model:** `STRUCTURED_A3`  
**Operational proxy:** `E0_LAST_AVAILABLE`  
**Target horizons:** `h = 1, 2, 3`

## Purpose and boundaries

P6 hardens the qualified P0--P5A workflow. It does not retrain, recalibrate,
retune, change the 34-predictor schema, alter P4 thresholds, change E0, or
introduce automated model updating. A prospective run must fail closed when
the P5/P5A issue-time contract cannot be demonstrated. Historical replay is an
explicitly labelled validation mode and is not evidence of prospective input
availability.

## Production states

The canonical run states are `PREFLIGHT_COMPLETE`, `INPUTS_VALIDATED`,
`PREDICTOR_MATRIX_COMPLETE`, `INFERENCE_COMPLETE`, `SUPPORT_COMPLETE`,
`OUTPUT_VALIDATED`, `MANIFEST_COMPLETE`, and `RUN_COMPLETE`. Terminal
readiness states are `READY`, `READY_WITH_WARNINGS`, `BLOCKED_INPUT_MISSING`,
`BLOCKED_INPUT_STALE`, `BLOCKED_INPUT_INVALID`, `BLOCKED_PROVENANCE`, and
`BLOCKED_MODEL_INTEGRITY`. A blocked or failed state never produces a completed
prediction product.

## Input and freshness rules

Issue week `T` is a completed ISO week. The issue timestamp is Monday 00:00:00
UTC immediately after `T`. Target weeks are the canonical ISO successors
`T+1`, `T+2`, and `T+3`. E0 requires the latest legitimate environmental
observation `L(T) = T-1`; the same environment state is copied to every target
horizon. Source timestamps later than the issue timestamp are future-dated and
block prospective operation. Unknown environmental release metadata block a
prospective run; they may only be retained as an explicit warning in historical
replay.

The six history predictors must have a causal `history_cutoff_week <= T` for
prospective operation. Static, calendar, and already-derived predictors remain
unchanged. Missing files, missing weeks, duplicate weeks, incomplete canonical
grids, schema mismatch, wrong model/support hashes, and invalid provenance are
blocking. No resampling, reordering, zero-filling, newer-source substitution,
or reuse of a prior output is permitted.

## Monitoring metrics and thresholds

Every run records source vintages and hashes, freshness counts, missingness,
prediction and expected-count summaries, high-risk and near-zero proportions,
novelty summaries, support proportions, uncertainty availability, runtime,
retry count, and warnings. Drift is descriptive only and never triggers
retraining. Relative to the frozen P4/reference record or a supplied recent
history record:

* absolute support-class or extrapolative-proportion shift `> 0.10` is
  `DRIFT_WARNING`; `> 0.20` is `DRIFT_REVIEW_REQUIRED`;
* absolute relative shift in mean occurrence probability or expected count
  `> 0.25` is `DRIFT_WARNING`; `> 0.50` is `DRIFT_REVIEW_REQUIRED`;
* novelty q99 or the extrapolative proportion exceeding its P4/reference
  baseline by `> 0.10` is a warning and by `> 0.20` requires review.

These thresholds are fixed before replay inspection. A drift state produces
`REVIEW_REQUIRED`, not a model update.

## Restart, immutability, and recovery

Stage files, status, manifests, checksums, and outputs are written atomically.
An incomplete run can resume only when its run identity, configuration hash,
model hash, proxy ID, and input signature match. A completed run is immutable.
An attempt to rerun the same completed identity in the same output root blocks
without overwriting it. Verification reads and checks the existing artifacts.
Corruption is tested in a validation copy and must be detected before
downstream completion.

## Delayed outcome evaluation

Outcome evaluation is a separate artifact keyed by run ID, issue week, target
week, and horizon. It can later calculate Brier, calibration, AUPRC, conditional
count error, full expected-count error, and frontier performance. It never
mutates the original production manifest or prediction output.

## Acceptance and decision rules

P6 is supported when the canonical command is deterministic, preflight and
input monitoring work, restart and duplicate protection pass, completed
outputs are immutable, corruption is detected, provenance is complete, and
monitoring/recovery artifacts are generated without silent failure. It is
supported with limitations when those controls pass but inherited scientific
support, proxy, sparse-frontier, or test-tooling limitations remain explicit.
It is not supported if any silent-failure path, unsafe restart, overwrite of a
completed output, incomplete provenance, or unrecoverable reproducibility
failure remains.
