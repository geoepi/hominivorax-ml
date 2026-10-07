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
- Stable repository entrypoints now replace the previously absent external
  configuration-directory scripts. Their responsibilities and validated
  implementations are recorded in
  `docs/release/production_entrypoint_inventory.md`.
- A real isolated Atlas `production_fullfit` run completed P0 through P5 with
  `afterok` dependencies. The fixed-theta optimizer converged, spatial
  products and GeoTIFF QA completed, and the run was compared with the
  established full-fit output. Model specification, coefficients, all
  812,997 node-week predictions, summary metrics, and 15 representative
  GeoTIFFs matched exactly.
- A real isolated Atlas `prospective_evaluation` run completed P0 through P5
  with the frozen deployed model, `refit_performed: false`, and the expected
  successful `status: no_eligible_weeks` at the current complete-support end
  of `2026-W29`.

The following are intentionally outside this technical release-preparation
scope and require an explicit organizational or scientific decision later:

- repository ownership or organization transfer;
- public visibility, branch protection, and publication of a GitHub Release;
- independent prospective validation, which remains pending by design.
