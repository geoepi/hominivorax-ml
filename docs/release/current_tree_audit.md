# Release hygiene audit

Audit date: 2026-10-07. Scope: the release-preparation tree and every
surviving branch/tag ref selected for the private `hominivorax-ml` release.

## Current tree

- No high-confidence credential pattern was found by the targeted scan for
  private-key headers, AWS access keys, GitHub-style tokens, and quoted
  credential assignments.
- No tracked observation extract, raw raster, Parquet feature table, model
  cache, checkpoint, or temporary SLURM output is present. Compact CSV/JSON
  provenance, scientific results, and test fixtures are retained where they
  are part of the source contract.
- Unnecessary personal Windows/Linux paths in operational files were replaced
  with configurable repository or library-root variables.
- `LICENSE` and `CITATION.cff` are present and checked into the release branch.

## Full-history review

The pre-rewrite all-ref audit identified exactly two prohibited production
artifacts:

- `analysis/soil_feature_screening/results/stgnn_cell_soil_features.csv`
- `analysis/soil_feature_screening/results/stgnn_cell_soil_features.parquet`

Both are the same 10,038-row soil feature table in CSV and Parquet forms.
Both were removed from surviving branch/tag history with `git-filter-repo`
2.47.0. Post-rewrite `git rev-list --objects --all` contains no occurrence of
either path and no prohibited production-data extension. The targeted
high-confidence secret scan remains zero-hit.

The recovery bundle was created before the rewrite outside the repository:

`D:\Github\.codex-local\backups\STGNN-pre-public-history-rewrite-20261007.bundle`

SHA-256:
`31077C0D8285BFC3D3CB47C7F81001CE9AC3DB0128992266CC961E78D67E8B73`

## Ref disposition

- Existing remote branch topology: preserve and force-update rewritten refs.
- Existing `structured-a3-development` tag: preserve with rewritten target.
- New `feature/hominivorax-ml-release-prep` branch: preserve through final
  merge, then retain as the release-preparation record.
- Codex-local snapshot/tree refs: remove from the local release namespace;
  they are not public branches or tags and were the only remaining local path
  to the prohibited historical objects.
