# Release blockers

Known unresolved items for public release:

- **License decision required.** No license file is currently present; a
  license must be selected by the project owner.
- **Citation-author confirmation required.** Authorship and citation metadata
  must be confirmed by the project owner rather than inferred from commit
  history.
- **History remediation required.** The local `feature/soil-feature-screening`
  ref contains a 10,038-row soil feature table and Parquet object reachable by
  `git rev-list --objects --all`. The project owner must classify it and decide
  whether to remove the ref/object from release scope or authorize a reviewed
  remediation. Do not rewrite history automatically.
- **Full-history security review is not a public-release clearance.** The
  targeted all-reachable-blob secret scan found no high-confidence hits, but
  the dataset blocker remains unresolved.
- **Organization policy remains pending.** Transfer, branch protection, and
  public visibility are intentionally deferred.
