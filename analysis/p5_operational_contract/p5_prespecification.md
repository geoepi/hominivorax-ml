# P5 Operational Evaluation and Production Contract Validation

## Scope and non-goals

P5 validates operation of the frozen `STRUCTURED_A3` candidate. It does not
add predictors, change lags or transformations, retune the model, recalibrate
predictions, alter P4 thresholds, or create a challenger. Historical replay
and prospective readiness are reported as separate estimands.

## Issue-time contract

An issue week `T` is a completed ISO week. The issue timestamp is Monday
00:00:00 UTC immediately after `T`. P5 produces exactly `T+1`, `T+2`, and
`T+3`, and requires the target weeks to be present in the validated input
bundle. Detection responses and frontier history are cut off at `T`.

The frozen history feature definition remains strictly prior to its forecast
week, but P5 does not invent a carry-forward or forecast substitution for
`T+2` or `T+3`. If the validated history artifact requires a cutoff later than
`T`, the prospective run is blocked. A historical replay may continue only
when explicitly labelled `replay`; it is not prospective evidence.

## Predictor availability classes

Every frozen predictor is classified as `STATIC`, `AVAILABLE_AS_OF_ISSUE`,
`AVAILABLE_WITH_KNOWN_LAG`, `REVISION_PRONE`, `RETROSPECTIVE_ONLY`, or
`UNKNOWN`. Environmental predictors are `RETROSPECTIVE_ONLY` because the
validated refresh documents completed-week products but not release-time or
revision-lag metadata. Static node covariates are `STATIC`; calendar terms
are deterministic and `AVAILABLE_AS_OF_ISSUE`; detection-history predictors
are `AVAILABLE_WITH_KNOWN_LAG` only when their auditable cutoff is no later
than `T`.

No source with a missing or future vintage is silently accepted. No
retrospective environmental layer is silently relabelled as current.

## Freshness states and input validation

The deterministic states are `CURRENT`, `STALE_ALLOWED`, `STALE_BLOCKING`,
`MISSING`, `FUTURE_DATED`, and `UNKNOWN_VINTAGE`. Missing, future-dated,
unknown-vintage, retrospective-only, wrong-schema, wrong-spatial-contract,
duplicate-target, or hash-mismatched inputs block a prospective run.

Every gridded source must preserve the frozen 10,037-node canonical order,
25 × 25 km resolution, revised-domain mask, and documented coordinate/grid
contract. No resampling, reprojection, cropping, cell reordering, zero-fill,
or fallback to a prior output is authorized.

## Operational workflow

The canonical P5 entry point is
`analysis/p5_operational_contract/scripts/run_p5_operational_contract.py`.
It verifies P0, resolves `T` and horizons, validates source files and
vintages, validates spatial/temporal/schema contracts, runs the frozen
coefficient-only inference, joins unchanged P4 support and interval
references, validates outputs, and writes an immutable run manifest.

`dry-run` performs all preflight checks and no inference. `run` is the
prospective mode and stops on any blocker. `replay` is an explicit historical
reconstruction mode used only to test deterministic execution against the
validated retrospective bundle.

## Support and uncertainty

The P4 support classes and thresholds are consumed unchanged. Every output
row includes continuous novelty, support class, support warning, exact hurdle
interval fields, and optional precomputed P4 bootstrap uncertainty. P5 never
reruns the full bootstrap for each weekly issuance; missing operational model
uncertainty is represented as `NOT_COMPUTED_OPERATIONALLY` and
`PARTIAL_UNCERTAINTY`. `EXTRAPOLATIVE` predictions are retained and flagged.

## Failure contract

The failure suite deliberately exercises missing files, stale inputs,
future-dated inputs, CRS/resolution/extent mismatches, schema mismatch,
model hash mismatch, missing support reference, duplicate targets, invalid
issue week, partial coverage, and missing provenance. Each must produce a
stable machine-readable error code, a human-readable message, and no false
success output.

## Reproducibility criteria

One historical issue week is run twice from identical declared inputs. The
replays must have identical model/input hashes, row counts, schema, support
flags, and numerically identical prediction columns within an exact-zero
tolerance. Only run identifiers, output roots, timestamps, and runtime fields
may differ.

## Acceptance and decision rules

`PROSPECTIVE_READY` requires all required inputs to be issue-time admissible.
`PROSPECTIVE_READY_WITH_LAG_LIMITATIONS` permits only documented bounded lag
with safe enforcement. `RETROSPECTIVE_ONLY` applies when the frozen predictor
definition cannot be supplied prospectively without future information.
`BLOCKED_BY_UNKNOWN_AVAILABILITY` applies when evidence is insufficient.

P5 uses `P5_OPERATIONAL_CONTRACT_SUPPORTED` only when the prospective contract
is enforceable, all failure tests are safe, and replay reproducibility passes.
It uses `P5_OPERATIONAL_CONTRACT_SUPPORTED_WITH_LIMITATIONS` when execution
is deterministic and safe but documented lag/availability limitations remain.
It uses `P5_OPERATIONAL_CONTRACT_NOT_SUPPORTED` when required predictors are
retrospective or unknown, leakage cannot be prevented, reproducibility fails,
or failures can produce false-success outputs.
