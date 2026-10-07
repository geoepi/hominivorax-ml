# Post-release verification checklist

- [ ] Verify the private repository is `geoepi/hominivorax-ml`.
- [ ] Verify the repository remains private and `main` remains the default
  branch.
- [ ] Preserve the classified surviving branches and tags after the history
  audit; do not rewrite history, move tags, or publish the recovery bundle.
- [ ] Configure branch protection after transfer verification: require pull
  requests and passing CI, prevent force pushes, and prevent branch deletion.
- [ ] Update the canonical local and Atlas remotes to the transferred
  repository.
- [ ] Verify annotated tag `v1.0.1-research` and its commit target.
- [ ] Verify issue templates, citation metadata, and MIT license.
- [ ] Run the final history/security audit and repository hygiene check.
- [ ] Confirm the repository has no GitHub Release page; the research tag is
  the release anchor.
- [ ] Test a clean clone from the private GeoEpi URL.
- [ ] Verify the release-facing documentation links.
- [ ] Keep ownership under `geoepi`; do not transfer or make public as part of
  this technical preparation.
