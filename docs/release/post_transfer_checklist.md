# Post-release verification checklist

- [ ] Rename the private repository to `JMHumphreys/hominivorax-ml`.
- [ ] Verify the repository remains private and `main` remains the default
  branch.
- [ ] Force-update only the classified surviving branches and tags after the
  history audit; do not publish the recovery bundle.
- [ ] Configure branch protection after the rewrite is complete: require pull
  requests and passing CI, prevent force pushes, and prevent branch deletion.
- [ ] Update the canonical local and Atlas remotes to the renamed repository.
- [ ] Verify annotated tag `v1.0.0-research` and its commit target.
- [ ] Verify issue templates, citation metadata, and MIT license.
- [ ] Run the final history/security audit and repository hygiene check.
- [ ] Confirm the repository has no GitHub Release page; the research tag is
  the release anchor.
- [ ] Test a clean clone from the private renamed URL.
- [ ] Verify the release-facing documentation links.
- [ ] Keep ownership under `JMHumphreys`; do not transfer or make public as
  part of this technical preparation.
