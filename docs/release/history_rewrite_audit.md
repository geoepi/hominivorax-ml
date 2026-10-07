# History rewrite audit

Audit date: 2026-10-07

## Authorized scope

The repository owner authorized history remediation to remove clearly raw or
derived production data before the private research release. Cosmetic history
rewriting was not performed.

## Removed artifacts

- `analysis/soil_feature_screening/results/stgnn_cell_soil_features.csv`
- `analysis/soil_feature_screening/results/stgnn_cell_soil_features.parquet`

These files were two serialized forms of the same 10,038-row soil feature
table. Compact scientific result CSVs, coefficients, quality-assurance
outputs, manifests, documentation, and fixtures remain in release scope.

## Method and recovery

The rewrite used isolated `git-filter-repo` version 2.47.0. A complete
pre-rewrite bundle was created outside the repository before the rewrite:

- path:
  `D:\Github\.codex-local\backups\STGNN-pre-public-history-rewrite-20261007.bundle`
- SHA-256:
  `31077C0D8285BFC3D3CB47C7F81001CE9AC3DB0128992266CC961E78D67E8B73`
- creation date: 2026-10-07

## Verification

The post-rewrite audit enumerated all surviving branch and tag objects with
`git rev-list --objects --all` and found no occurrence of either removed path.
No prohibited production-data extension was reachable. The targeted
high-confidence secret scan found zero hits. Internal Codex snapshot/tree
refs were excluded from the release namespace because they are not public
branches or tags and could otherwise retain stale worktree history.
