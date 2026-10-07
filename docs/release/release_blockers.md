# Release blockers and transfer boundary

The final private-release candidate closes the repository and orchestration
preparation blockers:

- `LICENSE` is MIT with copyright `(c) 2026 John Humphreys`.
- `CITATION.cff` identifies John Humphreys without inventing an ORCID,
  affiliation, email address, or DOI.
- The two soil feature tables were removed from all surviving branch and tag
  history in the isolated, externally backed-up rewrite.
- Tracked files are guarded by a 5 MiB limit and prohibited production-data
  extension checks in `scripts/check_repository_hygiene.py`.
- GitHub synchronization and the final release-tag correction are authorized
  release actions for this private candidate and are verified in the final
  release audit.
- All audited non-main branches have an explicit reconciliation record in
  `docs/release/final_branch_reconciliation.csv`. Fully represented branches
  are deletable; unique scientific audit branches are preserved by milestone
  tags before deletion.
- Atlas production configuration and currently supported input paths resolve
  under `/project/disease_ecology/STGNN-production-config/`; the development
  checkout remains separate and dirty by design.
- The bounded Atlas six-stage orchestration smoke test completed through P0 to
  P5 with `afterok` dependencies and a completed run manifest. It used no-op
  stage commands and did not fit a model.

One technical Atlas integration blocker remains: the external production
entrypoints referenced by the protected configuration (`a3_data_horizon_preflight.py`,
`a3_feature_assembly.py`, `a3_production_fullfit.py`,
`a3_prospective_score.py`, `a3_generate_products.py`, and
`a3_finalize_report.py`) are not currently present in the Atlas production
configuration directory. The real full-fit and prospective workflows must not
be represented as complete until those validated components are supplied. The
no-op smoke result validates scheduler/orchestration mechanics only.

The following are intentionally outside this technical release-preparation
scope and require an explicit organizational or scientific decision later:

- repository ownership or organization transfer;
- public visibility, branch protection, and publication of a GitHub Release;
- independent prospective validation, which remains pending by design.
