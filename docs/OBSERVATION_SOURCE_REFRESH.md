# Task 2E — Observation source refresh audit

Task 2E refreshes the revised-domain production dataset from the newer case
detection source. The refresh is intentionally separated from the Task 2D
audit so that the earlier source, node order, graph, and audit outputs remain
recoverable.

## Source identity

| Source | SHA-256 | rows |
|---|---|---:|
| Task 2D superseded source | `099f5fcc61dbd3686bd9bfd0dbfb0a4e37a36f2cba8b443580d2c456544f8a41` | 136,670 |
| Task 2E authoritative source | `a3d55f3ddf867087b578df803920bf59c6c303fa695e3218a5f3463e596d497e` | 136,714 |

The older file was not available for row-level comparison during the Atlas
run. The refresh therefore treats the SHA-256, row-count delta, date/coordinate
validation, and spatial reassignment as the authoritative change audit.

## Newly observed U.S. records

The +44 row-count delta is entirely U.S. source records:

- 43 rows in Texas;
- 1 row in New Mexico;
- earliest date 2026-06-03;
- latest date 2026-07-31;
- all 44 rows fall inside the revised domain and environmental-support mask.

The prior Task 2D source had no U.S. detections in its retained response
period. The refreshed response contains 30 positive U.S. node-weeks. These
new U.S. detections begin in 2026-W23, so the retained U.S. positives fall in
the terminal holdout window (with the 2026-W30 source tail outside the
response endpoint). This is why U.S. temporal PR-AUC and ROC-AUC are reported
as undefined/not informative in the baseline diagnostics rather than being
interpreted as evidence of discrimination.

## Audit artifacts

The row-level and aggregate audit outputs are written under
`/project/disease_ecology/STGNN-output/revised_model_data/diagnostics/`:

- `updated_observation_classification.parquet` and `.csv`;
- `us_observation_assignments.parquet`;
- `observation_source_change.parquet` and `.csv`;
- `us_observations_by_state.parquet`;
- `us_observations_by_month.parquet`;
- `us_observations_by_iso_week.parquet`;
- `weekly_observation_regime.parquet`;
- `candidate_start_comparison.parquet` and `candidate_start_screen.parquet`.

The source classification also preserves explicit flags for invalid or
unassignable records and records observations outside the revised domain or
environmental support. These are audit quantities, not silent deletions from
the source file; only the fixed response-period/domain assignment contributes
to the production targets.
