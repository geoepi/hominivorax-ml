# Engineering hardening findings

## Input and output protection

- P6 already enforces explicit run identity, immutable completed outputs,
  source/model/configuration hashes, input readiness, support and schema
  checks. Its output root is an explicit required argument. Documentation now
  makes clear that P6 inference does not refit.
- The P0–P5 full-fit pipeline and W44 candidate refresh have different roots
  and fit behavior; the current entrypoint inventory now states these effects
  directly.
- W44 row-level predictions, coordinates, residuals, and logs remain on Atlas;
  only aggregate reports are committed.
- The tracked `config/atlas-production.example.yaml` contains a W29
  observation path and a developer-specific R library path. It is an example,
  not the active Atlas configuration. The active configuration remains
  outside Git and was not changed. Replace or validate the example paths in a
  separately scoped configuration-maintenance review.

## Reproducibility and provenance

- The original W16 freeze, predictor order, model hash, and qualification
  status are identified separately from W29/W44 fit artifacts.
- The existing repository hygiene checker now validates every tracked JSON
  file, tracked YAML syntax using Ruby's standard-library Psych parser,
  relative internal Markdown targets, frozen scientific artifact references
  and SHA-256 values, the canonical current-status declaration, the unique
  branch inventory, the existing 5 MiB limit, and prohibited data extensions.
- W44 branch inventory records full branch heads, comparison bases, unique
  commit IDs/messages, changed files, PR links, preservation methods, and
  dispositions. The cleanup manifest is advisory and records no deletion.

## Operational clarity

- Current status documentation separates P6, P0–P5, and W44 development
  workflows.
- W29 is still the active production artifact according to the last isolation
  record; the P6 tracked config identifies the W16 freeze. Resolve that
  artifact/configuration mismatch before deployment.
- No checked-in path or environment example is evidence of the live Atlas
  deployment. The explicit deployment tag was not established from repository
  templates.

## GitHub Actions and validation

`.github/workflows/repository-hygiene.yml` now runs on every pull request and
on pushes to `main`. It retains the existing `hygiene` job name and does not
use path filters, preserving a stable PR check. This scopes out the duplicate
feature-branch push run while retaining PR validation and default-branch
validation.

The checker changes are Category C executable validation changes. No new test
framework or package dependency was added. This complete task is Category D
because it also integrates the completed scientific point-clustering work
into the W44 branch. No scientific calculations, model parameters, production
configuration, or active deployment state were changed.
