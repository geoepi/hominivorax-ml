# STRUCTURED_A3 data refresh audit: 2026-W44

Administrative result: REFRESH_BLOCKED_BY_INPUT_DATA. The latest source verification, for SHA-256 `784168081cc1d3206f3537b8731994cbfc34be15be7c515fe06710d4ea9bdaac`, found 164,767 unique `(date, lon, lat)` keys and zero redundant keys (`OBSERVATION_SOURCE_CORRECTION_VERIFIED`). Earlier duplicate findings remain preserved as historical results for their respective source checksums.

The read-only input and specification audit is documented here. The environmental products reach W44 and match the frozen training bundle over its original fit horizon. The current observation source passes the duplicate-key verification, but still has no documented complete-week cutoff and historical revisions remain unexplained. The original duplicate-precision audits and their source-specific results are retained in observation_duplicate_precision_audit.md and observation_corrected_source_reaudit.md. The latest verification is recorded in decision_report.md and input_manifest.json.

## Audit files

- input_manifest.json: source metadata and observation schema checks.
- observation_duplicate_precision_audit.md: superseding source-precision duplicate investigation and interpretation.
- observation_duplicate_precision_summary.csv: duplicate metrics by dataset, time subset, and comparison method.
- observation_coordinate_precision_summary.csv: coordinate decimal-place distribution and representation checks.
- observation_rounding_sensitivity.csv: diagnostic coordinate-rounding comparisons; no rounded values are used as source data.
- observation_date_normalization_summary.csv: date-representation comparison results.
- observation_duplicate_audit_manifest.json: source checksums, parser/method details, and aggregate audit metadata.
- observation_duplicate_precision_r_crosscheck.csv: independent aggregate base R key-count cross-check.
- scripts/observation_duplicate_precision_audit.py and scripts/observation_duplicate_precision_audit.R: reproducible read-only audit implementations.
- observation_corrected_source_reaudit.md: corrected-source re-audit and current readiness decision.
- observation_corrected_source_summary.csv: current source duplicate metrics by temporal subset and method.
- observation_source_version_comparison.csv: comparison with retained prior aggregate results; key-level comparison is unavailable because the prior source file was not found.
- observation_corrected_weekly_inventory.csv: corrected-source aggregate weekly counts and duplicate-key metrics.
- observation_corrected_source_manifest.json: corrected source identity, validation, decisions, and blockers.
- observation_corrected_coordinate_precision.csv, observation_corrected_rounding_sensitivity.csv, observation_historical_release_comparison.csv, observation_historical_weekly_comparison.csv, and observation_corrected_source_r_crosscheck.csv: aggregate precision, rounding diagnostic, historical-release, weekly, and independent R results.
- scripts/observation_corrected_source_reaudit.py: reproducible corrected-source audit runner using the committed Python helpers.
- ../../tests/test_observation_duplicate_precision.py: focused synthetic duplicate and exact-decimal tests.
- environmental_completeness_inventory.json: per-predictor weekly coverage, W44 hashes, node support, and provenance.
- historical_revision_summary.json: aggregate multiset comparisons; no row-level values.
- compatibility_report.md: Stage A findings.
- frozen_specification_verification.json: frozen predictor and model contract.
- candidate_data_vintage_manifest.json: blocked candidate status; no candidate artifacts.
- execution_environment_manifest.json: Atlas, repository, and validation record.
- artifact_integrity_manifest.json: frozen and pre-existing deployed artifact checksums.
- qualification_report.md: stage gates and omitted qualification.
- production_isolation_verification.md: current production boundary.
- decision_report.md: required 13-part execution summary.

Restricted data and fitted artifacts remain outside Git. No candidate model or qualification result was created. Reporting completeness through W44, historical revision provenance, and the separate W29 artifact-lineage question remain unresolved, so model fitting must not begin.
