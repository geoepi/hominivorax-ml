# P5 Operational Evaluation and Production Contract Validation

## I. Governance

SAE governance, `EXECUTION_GOVERNANCE.md`, and `ATLAS_SSH_POLICY.md` were reviewed. Atlas access used the authorized direct WSL/Ubuntu `atlas-ssh` route. P5 stayed within evaluation and contract-validation scope; no production deployment automation, scheduler, monitoring, rollback, release tag, or model-specification change was authorized.

## II. Canonical Starting State

Starting canonical main/P4 merge SHA: `313c156c787a649ab79ed81918184013573b922d`. The P0 freeze verifier passed before implementation. Frozen model: `STRUCTURED_A3`; frozen artifact SHA-256: `8a6a0a32a1a1e56f810b6aa1eafec5207dc3ac8d45cdf2270999f9721f080d1e`. P0/P1/P2/P3/P4 reports were read and their unresolved limitations were carried forward explicitly.

## III. P5 Repository State

Implementation SHA used for Atlas execution: `47d9facfa93ce7fe2f62ad09bedf4fa2f6b4c0d5`. The P5 implementation is isolated under `analysis/p5_operational_contract/`. The final branch/worktree/PR state is recorded in Section XVI. Standard-library contract tests were used because the validated Atlas Python environment does not provide pytest; the pytest gap is recorded as a P6 tooling recommendation rather than hidden or worked around by modifying the environment.

## IV. Predictor Availability Audit

All 34 frozen predictors received an explicit class. Counts are:

| Availability class | Predictor count |
|---|---:|
| AVAILABLE_AS_OF_ISSUE | 2 |
| AVAILABLE_WITH_KNOWN_LAG | 6 |
| RETROSPECTIVE_ONLY | 12 |
| STATIC | 14 |

RETROSPECTIVE_ONLY predictors: era5_mintemp, era5_soilmoist, era5_lai_low, agera5_relhum_min, era5land_tmean, era5land_soiltemp_l1_mean, era5land_soiltemp_l2_mean, era5land_soilwater_l1_mean, era5land_soilwater_l2_mean, era5land_surface_pressure_mean, era5land_lai_high_mean, era5land_lai_low_mean. UNKNOWN predictors: none. Environmental release-time/revision metadata were not available, so the dynamic environmental block was not silently treated as current. Horizon-specific blockers included: era5_mintemp h=1 (BLOCKED_RETROSPECTIVE_ONLY), era5_mintemp h=2 (BLOCKED_RETROSPECTIVE_ONLY), era5_mintemp h=3 (BLOCKED_RETROSPECTIVE_ONLY), era5_soilmoist h=1 (BLOCKED_RETROSPECTIVE_ONLY), era5_soilmoist h=2 (BLOCKED_RETROSPECTIVE_ONLY), era5_soilmoist h=3 (BLOCKED_RETROSPECTIVE_ONLY), era5_lai_low h=1 (BLOCKED_RETROSPECTIVE_ONLY), era5_lai_low h=2 (BLOCKED_RETROSPECTIVE_ONLY), era5_lai_low h=3 (BLOCKED_RETROSPECTIVE_ONLY), agera5_relhum_min h=1 (BLOCKED_RETROSPECTIVE_ONLY), agera5_relhum_min h=2 (BLOCKED_RETROSPECTIVE_ONLY), agera5_relhum_min h=3 (BLOCKED_RETROSPECTIVE_ONLY).

## V. Operational Issue Contract

Issue week `T` is a completed ISO week; the issue timestamp is Monday 00:00 UTC immediately after `T`. Targets are exactly `T+1`, `T+2`, and `T+3`. Response history and frontier history are cut off at `T`; a history feature with `history_cutoff_week > T` blocks prospective operation. Predictor vintages are explicit in `production_input_manifest.csv`; future-dated, unknown, missing, or retrospective-only inputs block `run` mode. No stale substitution, resampling, reprojecting, zero-fill, predictor replacement, or prior-output reuse is permitted.

## VI. Production Workflow

Canonical entry point: `analysis/p5_operational_contract/scripts/run_p5_operational_contract.py`. Stages are frozen-model verification, issue-week resolution, input discovery, vintage/freshness validation, spatial and temporal validation, exact frozen feature assembly, schema validation, coefficient-only STRUCTURED_A3 inference, unchanged P4 support/interval join, output validation, provenance, and terminal status. `dry-run` performs preflight only; `run` blocks on contract failure. Completed output roots are immutable.

## VII. Support / Uncertainty Integration

P4 classes `SUPPORTED`, `CAUTION`, and `EXTRAPOLATIVE` and the P4 thresholds are consumed unchanged. Rows retain extrapolative predictions and carry `EXTRAPOLATIVE_SUPPORT`; caution rows carry `CAUTION_SUPPORT`. Exact hurdle interval fields are included. Precomputed P4 bootstrap fields are included when available; P5 does not refit 100 bootstrap models per issuance and marks unavailable operational model uncertainty as `NOT_COMPUTED_OPERATIONALLY`/`PARTIAL_UNCERTAINTY`.

## VIII. Historical Replay

Replay issue week: `2026-W36`; target weeks: `2026-W37, 2026-W38, 2026-W39`. Atlas job ID: `21060933`. Replay terminal status: `PRODUCTION_RUN_COMPLETE_WITH_WARNINGS`. Output rows: `30111`. Output SHA-256: `62be368f743a0d17d62208be8e1073f5156f1650b62f2a596fca00d8d542af2a`. Output size: `2414337` bytes. This is an explicit retrospective reconstruction, not prospective availability evidence.

## IX. Reproducibility

The replay was run twice from identical declared inputs. Comparison status: `PASS`; row-count equality: `True`; schema equality: `True`; exact numeric equality: `True`; maximum absolute numeric difference: `0.0`; support-flag equality: `True`; warning-flag equality: `True`. Differences were limited to allowed run/output/runtime fields: `[]`.

## X. Failure-Mode Validation

The standard-library failure suite completed `13/13` tests with status `PASS`. Every deliberate failure produced a deterministic code and no false-success production output.

| Failure test | Observed code | Status |
|---|---|---|
| missing predictor file | `MISSING_REQUIRED_INPUT` | PASS |
| stale predictor | `STALE_BLOCKING` | PASS |
| future-dated predictor | `FUTURE_DATED` | PASS |
| wrong CRS | `SPATIAL_CONTRACT_FAILED` | PASS |
| wrong resolution | `SPATIAL_CONTRACT_FAILED` | PASS |
| wrong extent | `SPATIAL_CONTRACT_FAILED` | PASS |
| predictor-schema mismatch | `PREDICTOR_SCHEMA_MISMATCH` | PASS |
| corrupted model artifact/hash mismatch | `MODEL_HASH_MISMATCH` | PASS |
| missing support-reference artifact | `MISSING_SUPPORT_REFERENCE` | PASS |
| duplicate target week | `DUPLICATE_TARGET_WEEK` | PASS |
| invalid issue week | `INVALID_ISSUE_WEEK` | PASS |
| partial predictor coverage | `MISSING_REQUIRED_INPUT` | PASS |
| missing provenance metadata | `MISSING_PROVENANCE_METADATA` | PASS |

## XI. Operational Practicality

The Atlas production-like replay completed in `4.862443685531616` seconds and produced `30111` rows (2414337 bytes). The fixed-model inference and P4-reference join are computationally practical for a weekly run; full P4 bootstrap refitting is intentionally not part of each issuance. The managed Atlas environment lacks pytest; the repository-defined R suite and standard-library P5 contracts remain separate from that tooling limitation.

## XII. Production Availability Classification

`RETROSPECTIVE_ONLY`

The successful retrospective replay does not override the availability classification: current dynamic environmental products lack auditable issue-time release/revision metadata and the frozen target-week history artifact requires future-of-issue cutoffs for later horizons. The prospective `run`/`dry-run` contract therefore blocks rather than silently using future information.

## XIII. P1–P4 Limitation Tracking

| Limitation | P5 classification |
|---|---|
| sparse frontier support | `ROBUST_LIMITATION` |
| sparse U.S./regional outcome support | `ROBUST_LIMITATION` |
| count-process bias | `BETTER_CHARACTERIZED` |
| retrospective environmental availability | `BLOCKING_OPERATIONAL_READINESS` |
| extrapolative support proportion | `BETTER_CHARACTERIZED` |
| lack of refitted spatial holdout | `NOT_ADDRESSABLE_IN_P5` |
| pytest/test-environment gap | `NOT_ADDRESSABLE_IN_P5` |

## XIV. Artifacts

- `analysis/p5_operational_contract/p5_prespecification.md`
- `analysis/p5_operational_contract/p5_operational_contract_report.md`
- `analysis/p5_operational_contract/results/predictor_availability_audit.csv`
- `analysis/p5_operational_contract/results/input_contract.json`
- `analysis/p5_operational_contract/results/replay_manifest.json`
- `analysis/p5_operational_contract/results/failure_mode_test_results.csv`
- `analysis/p5_operational_contract/results/decision.json`
- Atlas output root: `/project/disease_ecology/STGNN-output/p5_operational_contract_20261029_v5`

## XV. Atlas

WSL route compliance: PASS. Atlas job ID: `21060933`; terminal status: COMPLETED. The isolated output root was `/project/disease_ecology/STGNN-output/p5_operational_contract_20261029_v5`. P0–P4 roots were not overwritten.

## XVI. CI / PR / Merge

Hosted CI, PR, merge, post-merge freeze verification, and cleanup will be recorded in the task handoff. No production release tag will be created.

## XVII. P5 Decision

P5_OPERATIONAL_CONTRACT_NOT_SUPPORTED
