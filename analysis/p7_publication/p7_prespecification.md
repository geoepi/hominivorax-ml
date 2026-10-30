# P7 Publication Artifact Generation and Release Candidate Assembly

## Status

This prespecification is locked before generation of publication claims, tables,
figures, or manuscript components. P7 is an aggregation and provenance phase;
it does not modify the frozen scientific model or any P0--P6 result.

## Scientific boundary

The publication package will describe the qualified `STRUCTURED_A3` model with
the `E0_LAST_AVAILABLE` issue-time environmental proxy, horizons `h = 1, 2, 3`,
the unchanged P4 support classes (`SUPPORTED`, `CAUTION`, `EXTRAPOLATIVE`), and
the P6 output schema `P6_OUTPUT_1.0`. No model fitting, tuning, recalibration,
threshold adjustment, predictor change, or proxy change is permitted.

## Controlled claim set

The package will support only the following bounded claim families, and only
when the cited canonical source artifact contains the required value:

| ID | Claim family | Allowed interpretation | Prohibited interpretation |
|---|---|---|---|
| A | Short-horizon occurrence performance | Occurrence discrimination and calibration are summarized for the 1--3 week retrospective rolling-origin evaluation. | Unrestricted future forecasting or universal validity. |
| B | Horizon degradation | Common-week paired performance changes are reported across h=1--3. | Claiming degradation is absent when uncertainty or sparse strata do not support that statement. |
| C | Environmental proxy viability | `E0_LAST_AVAILABLE` is compared with `REALIZED_ENV` using the canonical P5A paired results. | Calling the proxy a true future environmental forecast or claiming exact equivalence without source support. |
| D | Frontier limitation | Frontier/newly unoccupied prediction is weaker and has sparse positive support where canonical results show it. | Claiming complete frontier validity. |
| E | Count limitation | Conditional and full-hurdle count behavior is reported, including measurable bias where present. | Claiming unbiased abundance prediction. |
| F | Robustness | Bounded P3 sensitivity analyses support stability of the stated conclusions where documented. | Claiming stability outside the prespecified sensitivity scope. |
| G | Environmental support limitation | P4 support proportions and novelty classes are reported explicitly. | Claiming universal environmental support. |
| H | Production reproducibility | P5/P6 evidence supports deterministic, hash-verified, restartable, failure-safe operation within the qualified contract. | Claiming production operation without limitations or automatic retraining. |

Claims of causal environmental effects, superiority over alternative frameworks,
complete U.S. or regional validation, and unrestricted prospective forecasting are
excluded from the package.

## Primary publication artifacts

The build will create the following primary figures and tables from canonical
machine-readable source files. The source mapping is part of the build manifest.

### Figures

1. Study/model framework and issue-time proxy schematic.
2. Retrospective rolling-origin performance by horizon.
3. Reliability/calibration by horizon.
4. Environmental proxy comparison (`REALIZED_ENV`, `E0_LAST_AVAILABLE`, and
   `E1_TRAILING3_MEAN` when present in the canonical source).
5. Frontier versus previously occupied performance.
6. Conditional and full-hurdle count behavior.
7. P4 environmental support/extrapolation proportions.
8. P0--P6 qualification sequence and production contract.

### Tables

1. Data and model specification.
2. Occurrence performance by horizon.
3. Count performance by horizon.
4. Proxy comparison and paired degradation.
5. Limitation summary.

Supplementary tables will include the 34-predictor inventory, predictor
provenance, transfer and robustness summaries, support definitions, proxy
applicability, warning/error codes, reproducibility hashes, and software/runtime
metadata. Existing canonical scientific figures may be reused when their data
and provenance are unchanged; any formatting-only regeneration must retain the
same underlying source values.

## Source-artifact policy

Every reported number must be read from a tracked P1--P6 machine-readable output
or a value deterministically derived from such an output. Manual transcription
of scientific values is prohibited. The build must fail if a required source
file, required schema column, or expected source hash is unavailable or changed.

The source registry will include the canonical P1--P6 decision artifacts,
P2 occurrence/count metrics, P3 robustness summaries, P4 support summaries,
P5A proxy metrics and contract, and P6 production configuration and validation
records. Large or protected raw data are not publication-package inputs.

## Terminology

Use `STRUCTURED_A3`, `E0_LAST_AVAILABLE`, `1--3 week nowcast horizon`,
`retrospective rolling-origin evaluation`, `prospective issue-time proxy`,
`SUPPORTED`, `CAUTION`, `EXTRAPOLATIVE`, `conditional positive count`, and
`full hurdle expected count`. The words *forecast*, *nowcast*, *retrospective
prediction*, and *prospective prediction* must be qualified when used.

## Rounding and interval rules

* Metrics and probabilities: four decimal places in machine-readable and main
  table outputs unless the source is an integer count.
* Counts and sample sizes: integers.
* Percentages: one decimal place.
* Confidence or uncertainty interval endpoints: the same precision as estimates.
* Hashes: full SHA-256 in machine-readable manifests; abbreviated only in prose.
* Figures use the unrounded source values for geometry and annotations.

## Reproducibility rules

The canonical publication command will verify the freeze and source artifacts,
generate tables, figures, synthesis, manuscript components, and the
reproducibility manifest, then validate outputs. It will not invoke model fitting.
Two builds from the same commit must have identical source-derived tables,
claim values, plotted data, and output schemas. Rendering metadata or allowed
generation timestamps may differ only when recorded explicitly; otherwise output
hashes must match.

## Limitation wording

The publication package must retain, at minimum, sparse frontier positives,
sparse U.S./regional support, measurable count-process bias, the burden of
`CAUTION`/`EXTRAPOLATIVE` support, dependence on `E0_LAST_AVAILABLE`, the
applicable spatial-holdout limitation, observational/predictive rather than
causal interpretation, and source-product availability/version limitations.
Warnings or operational flags do not resolve a scientific limitation.

## Release-candidate contents

The release candidate will contain source scripts, generated tables and figures,
the controlled results synthesis, manuscript component drafts, qualification
summary, runbook and production-use statement references, source hashes, and
the publication reproducibility manifest. It will exclude protected raw data,
secrets, unnecessary large Atlas intermediates, and machine-specific paths as
runtime dependencies. No final release tag will be created during P7.

## Acceptance and decision rules

P7 is supported only if all primary claims trace to canonical source artifacts,
tables and figures regenerate, the build fails safely on missing or mismatched
sources, limitations are explicit, and the release candidate is coherent.
Minor rendering, data-access, or tooling limitations that do not affect claims
will be reported and may yield `P7_PUBLICATION_PACKAGE_SUPPORTED_WITH_LIMITATIONS`.
Any untraceable primary result, silent source substitution, missing required
limitation, or protected-data dependency required for regeneration yields
`P7_PUBLICATION_PACKAGE_NOT_SUPPORTED`.
