# Data availability and schema contract

The public repository contains code, configuration templates, predictor
definitions, compact manifests, and documentation. It does not distribute
protected observation extracts or large production artifacts.

## Public and external inputs

- Public code and exact predictor definitions are tracked in this repository.
- Environmental inputs are externally obtainable but are expected to be
  assembled into the validated Atlas schema before production use.
- The canonical node order, weekly encoding, CRS, resolution, and response
  definition are part of the frozen manifest.

## Non-distributed inputs and products

- Protected or non-distributed observation data remain on authorized Atlas
  storage.
- Large derived rasters, Parquet feature tables, model parameters, and
  production output stacks remain outside Git.
- Atlas-local scratch, logs, manifests, and SLURM outputs are deployment
  artifacts, not public inputs.

## Expected schemas

Production inputs must provide canonical integer `model_node_id` values
`0..10036`, explicit weekly identifiers, the 34 predictors in frozen order,
and finite values wherever the specification requires them. Raster inputs must
match the validated CRS, extent, resolution, origin, and node mask. History
features must include auditable cutoffs strictly before each forecast week.

Schema or unit changes are stop conditions; the launcher does not silently
reinterpret columns or units.

## Data vintages

The original frozen development/evaluation data and the later W44 candidate
source are separate vintages. The W44 candidate used
`combined_clean_obs_2026-11-13.csv` (SHA-256
`784168081cc1d3206f3537b8731994cbfc34be15be7c515fe06710d4ea9bdaac`). That
snapshot contains 164,767 records observed through W46; W45–W46 were excluded
from the candidate's W44 fitting horizon. The source snapshot has no certified
reporting-completeness or outcome-maturity record, and historical revisions
remain unexplained. These caveats limit evaluation; they do not alter the
frozen specification. See the [data-vintage and artifact map](data_artifact_map.md)
and [current status](status.md).
