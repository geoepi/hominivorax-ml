# Output classes and roots

The repository has three distinct output pathways. Do not move artifacts
between them or describe descriptive full-fit products as forecasts.

## P6 issue-time inference

P6 writes an immutable run directory under the configured production output
root. Its schema includes:

- `p_occurrence` weekly GeoTIFFs;
- `conditional_count_mean` weekly GeoTIFFs;
- `expected_count` weekly GeoTIFFs;
- summary GeoTIFFs;
- nowcast PDFs;
- weekly summary tables;
- model, scaling, and artifact manifests;
- interpretation figures when enabled;
- GIF animations when enabled.

The deployed production output root is configured on Atlas; use the P6
runbook and never copy a completed run into the canonical root. P6 inference
does not refit.

## P0–P5 descriptive full fit

The `production_fullfit` mode fits once on the accepted complete horizon and
writes descriptive predictions, GeoTIFFs, summaries, reports, and manifests
under its full-fit root. It is separate from P6 inference. The
`prospective_evaluation` mode of that pipeline writes to a separate
`prospective_evaluation/<run_id>/` root, performs no refit, and scores only
eligible weeks strictly after the deployed model's evaluation horizon.

## W44 candidate and Q1 retrospective

W44 candidate products use the development root
`/project/disease_ecology/STGNN-output/structured_a3_refresh_2026w44`. Q1
row-level predictions, coordinates, residuals, and logs remain on Atlas; only
aggregate results are tracked under
`analysis/structured_a3_data_refresh_2026w44/qualification_execution/results/2026w44_q1_retrospective/`.
The W44 candidate is not production-qualified, and Q1 metrics are descriptive
because target maturity is uncertified.
