# Release blockers

The software-release blockers addressed by this preparation pass are closed:

- `LICENSE` is MIT with copyright `(c) 2026 John Humphreys`.
- `CITATION.cff` identifies John Humphreys without inventing an ORCID,
  affiliation, email address, or DOI.
- The two soil feature tables were removed from all surviving branch and tag
  history in the isolated, externally backed-up rewrite.
- Tracked files are guarded by a 5 MiB limit and prohibited production-data
  extension checks in `scripts/check_repository_hygiene.py`.

The following are intentionally outside this technical release-preparation
scope and require an explicit organizational decision later:

- repository ownership or organization transfer;
- public visibility, branch protection, and publication of a GitHub Release;
- deployment to a production Atlas path, if the Atlas environment is not
  reachable from the release host.
