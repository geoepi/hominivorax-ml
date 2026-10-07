# Release hygiene audit — current tree

Audit scope: tracked files at the release-preparation worktree, excluding the
preserved historical documentation from current-tree path and secret results.
The audit was run on 2026-10-07.

## Findings

- No high-confidence credential pattern was found in the current tree by the
  targeted scan for private-key headers, AWS access keys, GitHub-style tokens,
  and quoted credential assignments.
- No tracked observation extract, raw raster, Parquet feature table, model
  cache, checkpoint, or temporary SLURM output is present in the current
  release-preparation tree. Compact CSV/JSON provenance and test fixtures are
  retained where intentionally part of the source contract.
- Unnecessary personal Windows/Linux paths found in current operational files
  were replaced with configurable repository or library-root variables.
- No license file is present.

## Full-history review status

The whole reachable Git object set was enumerated with `git rev-list
--objects --all`. A targeted all-reachable-blob scan found zero high-confidence
secret-pattern hits. However, the local `feature/soil-feature-screening` ref
contains a 10,038-row soil feature table and its Parquet representation in
commit `da416ca`. These objects are not in the current main release tree, but
they are reachable under the required `--all` audit and require project-owner
classification/remediation before a public release.

History was not rewritten and the objects were not deleted automatically.
Public release preparation is halted pending that review.

## Largest historical objects reviewed

The largest reachable blobs were compact analysis outputs rather than raw
rasters. The largest listed object was approximately 530 KB. The soil feature
Parquet object was approximately 59 KB but is treated as a release blocker
because its data-distribution status is not established by this audit.
