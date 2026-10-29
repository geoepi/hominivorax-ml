# P6 Production Hardening and Monitoring Report

## 1. Objective and qualified specification

P6 hardened the already-qualified `STRUCTURED_A3` workflow without changing
scientific content. The production specification remains the frozen model
artifact (`8a6a0a32a1a1e56f810b6aa1eafec5207dc3ac8d45cdf2270999f9721f080d1e`),
the unchanged P4 support categories and thresholds, the P5A
`E0_LAST_AVAILABLE` proxy (`L(T)=T-1`), and horizons 1--3. P0 and P5A files
were not modified.

## 2. Canonical command

The single entry point is
`analysis/p6_production_hardening/scripts/p6_production.py`. It supports
explicit `preflight`, `production`, `replay`, and `verify` modes. The ordered
stages are frozen-model verification, proxy verification, issue/target
resolution, input-vintage validation, E0 construction, non-environment and
spatial/temporal validation, frozen 34-column inference, P4 support and
uncertainty attachment, output validation, atomic output/provenance writing,
and terminal status writing.

`preflight` never writes final predictions. A prospective preflight against the
historical refresh bundle correctly returned `BLOCKED_INPUT_INVALID` with
`FUTURE_DATED_ENVIRONMENT_SOURCE` and `HISTORY_CUTOFF_AFTER_ISSUE`. This is a
safe contract failure, not a retrospective replay being misrepresented as a
prospective run.

## 3. Input readiness and E0 enforcement

The E0 state is copied only into the first 12 environmental columns at target
weeks `T+1:T+3`; all other 22 predictors remain unchanged. The run manifest
records the latest environmental week, source timestamp, source hash, issue
timestamp, target weeks, and input signature. Missing, future-dated, invalid,
or provenance-inconsistent inputs fail closed. No resampling, reordering,
newer-source substitution, zero filling, or reuse of a prior output is used.

## 4. Restartability and immutability

Stage markers are written atomically for `PREFLIGHT_COMPLETE` through
`RUN_COMPLETE`; predictor matrices, predictions, manifests, checksums, status,
and monitoring records use temporary-file-then-rename writes. An interrupted
W26 run was stopped after `PREDICTOR_MATRIX_COMPLETE`, resumed with attempt 1,
and produced the same 30,111-row scientific/support output as the uninterrupted
reference (maximum numeric difference 0.0, identical schema and support flags).

Rerunning the completed W16 root returned `DUPLICATE_COMPLETED_RUN`, and a
follow-up `verify` returned `PASS` with the original output hash. A separate
corruption copy returned `OUTPUT_HASH_MISMATCH` before downstream completion;
the original root was untouched.

## 5. Monitoring and drift

Each completed run records latest environmental week, input freshness counts and
hashes, output row count, probability and expected-count distributions,
high-risk and near-zero proportions, novelty quantiles, support-class counts
and proportions, uncertainty availability, runtime, retry count, warnings, and
drift state. Fixed monitoring states are `NO_MATERIAL_DRIFT`, `DRIFT_WARNING`,
and `DRIFT_REVIEW_REQUIRED`. The simulation produced all three states using
prespecified thresholds. Drift only emits `REVIEW_REQUIRED`; no automated
retraining or model update exists.

Support remains explicit as `SUPPORTED`, `CAUTION`, or `EXTRAPOLATIVE`.
Extrapolative predictions are retained and flagged. P4 reference uncertainty is
reported where available; missing operational bootstrap values are represented
as unavailable rather than fabricated.

## 6. Historical replay validation

Three production-like E0 replays were run through the authorized Atlas
WSL/Ubuntu route in the isolated output root
`/project/disease_ecology/STGNN-output/p6_production_hardening_20261029_v1/`.
Each completed with warnings that preserve historical-vintage limitations.

| Issue week | Target weeks | Rows | Output SHA-256 | Runtime (s) |
|---|---|---:|---|---:|
| 2026-W16 | W17--W19 | 30,111 | `c39dfb33c02ccd74a5c7b81bd98bdf271a7059adf8d75853922e09c24516e572` | 42.98 |
| 2026-W26 | W27--W29 | 30,111 | `524849ca80ed3f088ca068a16faafb10dfbf47de0588e69f4db0ee7aba5fa753` | 55.18 |
| 2026-W36 | W37--W39 | 30,111 | `7b594b74e1725235745e59fecbc6d9400e669002d9036f00cc22531cb0c572d8` | 56.39 |

The W16/W26/W36 support proportions were, respectively, 78.57%/18.41%/3.02%,
23.94%/25.52%/50.54%, and 21.84%/16.83%/61.33% for
SUPPORTED/CAUTION/EXTRAPOLATIVE. These are monitoring observations, not new
support thresholds or model-selection results.

## 7. Failure and recovery tests

The deliberate tests passed:

* missing front-feature input: `BLOCKED_INPUT_MISSING`;
* prospective historical-bundle preflight: future-vintage/history-cutoff block;
* duplicate completed run: `DUPLICATE_COMPLETED_RUN` with original verification passing;
* corrupted validation copy: `OUTPUT_HASH_MISMATCH` with no downstream completion;
* interruption and restart: exact scientific/support equality;
* monitoring fixtures: deterministic warning and review states.

## 8. Runbook and delayed outcomes

`docs/production_runbook.md` covers routine preflight, normal production,
verification, replay, delayed/stale input handling, failed-job recovery,
corruption, model/support hash mismatch, revised-source replay, rollback, and
delayed outcome evaluation. Every completed replay also writes a separate
delayed-outcome template keyed by run ID, issue week, target week, horizon, and
canonical node; the original manifest is not mutated.

## 9. Environment and limitations

Atlas used the repository-authorized `/project/disease_ecology/STGNN-python-venv`
with `hpc/env_python.sh`; Python 3.12.14, NumPy, pandas, SciPy, and the
validated P2--P5A dependencies were available. Pytest is not installed in the
validated environment, so focused standard-library `unittest` was used (5/5
passed) alongside bytecode compilation and direct operational assertions. This
tooling gap is documented and is not hidden by changing the environment.

Remaining limitations are explicit: provider release timestamps are not
available in the historical bundle; h2/h3 causal history remains a prospective
input requirement; sparse frontier support, sparse U.S./regional outcome
support, count-process bias, extrapolative-support prevalence, and lack of a
refitted spatial holdout remain scientific limitations; and pytest remains a
tooling limitation. P6 monitors or fails safely around these limitations but
does not resolve them.

## 10. P6 decision

The hardening controls passed: deterministic entry point, fail-closed preflight,
atomic and immutable outputs, restartability, duplicate protection, corruption
detection, complete manifests, monitoring/drift records, delayed-outcome
structure, and validated recovery procedures. Because the historical source
bundle cannot itself prove live provider-vintage timing and inherits the
documented scientific/tooling limitations, the qualification is:

P6_PRODUCTION_HARDENING_SUPPORTED_WITH_LIMITATIONS
