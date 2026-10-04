# V2-A Prospective Evaluation Protocol

## Purpose and status

This protocol evaluates `STGNN-Hurdle-V2A` sequentially after the 2026-10-03 development-specification freeze. Existing 2025–2026 outcomes are historical development/evaluated data and cannot be relabeled as an unseen test.

Initial status: **HARNESS READY — AWAITING FUTURE DATA**.

## Forecast chronology

For week *t*:

1. establish the cutoff at the end of *t − 1*;
2. load the week-*t* predictor bundle;
3. construct front state using responses from weeks `< t` only;
4. apply frozen preprocessing and coefficients;
5. write and checksum the forecast artifact;
6. only then ingest week-*t* outcomes;
7. write a separate outcome artifact;
8. score by node/week join;
9. append the evaluation ledger and cumulative scores.

Forecast artifacts never contain outcome fields and are never rewritten after scoring.

## Eligibility and historical backfill

A scored week is `prospective_eligible` only when its outcome source became available after the forecast issue timestamp and the week is post-freeze. Otherwise it is labeled `historical_backfill` and excluded from prospective cumulative metrics.

When no explicit report-ingestion timestamp exists, the source file acquisition/modification time is used conservatively. Detection date is not treated as an observation-availability timestamp.

Raw lon/lat CSVs are not silently assigned to nodes during scoring. Score mode requires an audited node-assigned parquet source containing `model_node_id` and a week/date field.

## Metrics

Weekly and cumulative scoring includes Bernoulli NLL, Brier score, Brier skill against the frozen development prevalence, PR-AUC and ROC-AUC where defined, joint hurdle NLL, positive-count ZTNB NLL, positive-count MAE/RMSE, all-cell MAE/RMSE, prevalence, and expected detections.

Diagnostics separate first-ever and recurrent positives, new-cell percentile ranks, Mexico/U.S./full-domain metrics, fixed latitude bands, U.S. transfer cases, and front progression.

## Review trigger

Formal prospective review should wait for at least 8 genuinely post-freeze weeks and preferably at least 10 first-ever positive node-weeks. This is a review trigger, not an automatic pass criterion.

Future review classifications are `PROSPECTIVE SUPPORT`, `PARTIAL PROSPECTIVE SUPPORT`, `NO PROSPECTIVE SUPPORT`, or `INSUFFICIENT DATA`. The harness does not assign these automatically.
