# STRUCTURED_A3 data refresh audit: 2026-W44

Administrative result: REFRESH_BLOCKED_BY_INPUT_DATA.

The read-only input and specification audit is documented here. The environmental products reach W44 and match the frozen training bundle over its original fit horizon. The observation release has no documented complete-week cutoff and makes substantial, unexplained revisions in the frozen training period. The user-provided stop rule therefore halted work before model execution.

## Audit files

- input_manifest.json: source metadata and observation schema checks.
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

Restricted data and fitted artifacts remain outside Git. No candidate model or qualification result was created.
