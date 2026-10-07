# 003 — Soil feature screening

## Question

Which soil summaries, if any, can be added without reopening the frozen base selection?

## Decision

Retain the prespecified soil additions used by STRUCTURED A3: `clay_0_15` and `water_difference_wv0033_minus_wv0010_0_15`.

## Evidence

The soil workstream recorded bounded SoilGrids acquisition/aggregation failures, resumed screening, fixed-theta audits, and a final compact soil specification. The canonical A3 feature manifest checksums the soil node-feature artifact rather than embedding the protected artifact in Git.

## Rejected alternatives

The full soil-screening branch, its tracked Parquet/CSV node table, and intermediate screening candidates are not merged into the canonical repository. They remain on the historical branch and on authorized Atlas storage.

## Provenance and status

Relevant branch: `feature/soil-feature-screening` tip `97defc7`; compact provenance is also referenced by `feature/controlled-predictor-augmentation` and `analysis/structured_a3_final_comparison/results/a3_feature_manifest.json`. Status: **superseded branch, conclusion retained**.
