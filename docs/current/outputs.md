# Production outputs

The established Structured A3 production output contract includes:

- `p_occurrence` weekly GeoTIFFs;
- `conditional_count_mean` weekly GeoTIFFs;
- `expected_count` weekly GeoTIFFs;
- summary GeoTIFFs;
- nowcast PDFs;
- weekly summary tables;
- model, scaling, and artifact manifests;
- interpretation figures when enabled;
- GIF animations when enabled.

Production output roots are configured on Atlas. Prospective evaluation uses a
distinct `prospective_evaluation/<run_id>/` root and must not overwrite
full-fit artifacts.
