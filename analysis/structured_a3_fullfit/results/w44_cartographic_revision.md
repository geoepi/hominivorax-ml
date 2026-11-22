# STRUCTURED_A3 W44 Cartographic Revision

**Decision:** `W44_CARTOGRAPHIC_REVISION_COMPLETE`\
**Candidate status:** `CANDIDATE_READY_FOR_REVIEW_NOT_PRODUCTION_QUALIFIED`\
**Change classification:** C — visualization code and focused tests; model calculations and outputs were not changed.

## I. Governance and repository state

The revision was implemented in isolated branch `analysis/structured-a3-2026w44-cartographic-v1`, based on refresh PR #31 at `4974ac4a5f0306cc3e6c43d38b5a1a71ce08580c`. The graphics revision is separate from the W44 model refresh. Atlas access followed the approved WSL/Ubuntu `atlas-ssh` wrapper. No production promotion or model fitting was performed.

## II. Existing figure-generation implementation

The candidate artifact manifest was used to resolve input artifacts. The renderer reads prediction GeoTIFFs, existing summary and observation tables, and interpretation artifacts from the W44 candidate output. It writes into a new versioned output directory and protects the 346 candidate artifacts with before/after checksums. Original figure outputs are preserved.

## III. Palette and normalization changes

Prediction maps now share the sequential palette `#F4F4F4`, `#E0EDF7`, `#A6CEE3`, `#5596C5`, `#2166AC`, `#08306B`, ordered from zero/light to higher/darker values. Missing cells use `#BDBDBD`, distinct from valid zero. Occurrence maps retain a common linear 0–1 scale. Expected-count maps use a fixed linear limit of 0–3.22590302155403 and a supplementary monotonic `log1p` view with colorbar labels in original count units. The transformation is display-only; raster values were not changed.

## IV. Observation-map separation

Prediction maps contain no observation layer. Separate location and observed-cell-count maps are provided. The candidate `observed_detections.csv` was already aggregated to occupied 25 km model-cell centroids, so the location maps show those centroids rather than record-level detection locations. No raw observation source was read or reprocessed for this revision.

## V. Geographic layout changes

The renderer provides full model-domain overviews and a rendering-only Mexico–Texas detail view at longitude `[-108, -93]`, latitude `[22, 37]`. Raster values and model domain were not cropped or resampled. Layouts use larger map panels, restrained boundary lines, legible legends, correct geographic aspect, and opaque white PNG backgrounds.

## VI. Regenerated figure inventory

Output root on Atlas: `/project/disease_ecology/STGNN-output/structured_a3_refresh_2026w44/figures_cartographic_revision_v1`.

The aggregate manifest records 74 figure products and 148 output files (74 PNG, 74 PDF):

- 36 weekly prediction products for 2026-W39 through W44: occurrence, fixed-scale expected count, and supplementary log1p expected count, each with overview and detail views.
- 6 six-week comparison products.
- 3 spatial progression snapshot products, retaining the original selected weeks 2025-W01, 2025-W48, 2026-W17, 2026-W42, and 2026-W44 as the temporal inputs to the progression panels.
- 12 separate occupied-cell location products and 12 observed-cell-count products for W39–W44, with overview and detail views.
- 5 interpretation products: occurrence coefficient ranking, count coefficient ranking, permutation importance, effect response, and seasonal effect.

## VII. Visual inspection results

A rendering pilot was inspected before full generation. Representative outputs included an occurrence map, expected-count map, occupied-cell location map, six-week comparison, and Mexico–Texas detail. The sequential gradients read from light low values to dark high values; valid zeros and missing cells are visually distinct; prediction surfaces are unobstructed by markers; legends, boundaries, and axes remain readable. The fixed 0–1 occurrence scale is retained as the primary probability view. The expected-count log1p companion improves visibility in the right-skewed values while retaining original-unit ticks.

## VIII. Focused validation

- Atlas R style tests passed for exact palette values, light-to-dark ordering, zero color, NoData distinction, and `log1p` monotonicity/inversion.
- `bash -n` passed for the visualization Slurm wrapper.
- The renderer verified all 148 outputs, recorded checksums, PNG opacity/white backgrounds, and PDF signatures.
- Independent manifest reconciliation found zero output checksum mismatches.
- The candidate model SHA-256 remained `b1a66a65efbb9a65f6a4c966044d2f87576ee7e6a1d1a294c0fb1855f684f53b`; the input output-manifest SHA-256 remained `52205515e55e42de2ede04259913aac5bb2093fe8b7a5ff98fd41fc4824e73d7`.
- The renderer's before/after protection check found all 346 candidate artifacts unchanged.

Package-wide tests, model fitting, and unrelated HPC or production qualification workflows were not run because this change is limited to visualization and focused rendering validation.

## IX. Original artifact preservation

Original candidate rasters, model files, source data, and figures were left in place. The new figures and their two aggregate manifests are stored separately. Two candidate artifact manifest entries were already mismatched before rendering: `logs/fullfit_21272817.out` and `structured_a3_fullfit_output_manifest.json`. The renderer recorded these pre-existing discrepancies and verified the artifact hashes stayed constant through the run; neither mismatch is a cartographic output.

## X. Repository and pull-request status

Source-code commit before this report and aggregate manifests: `2025517af1ec8418a3aa211dd1fd39666f1fd0b1`. The output manifest checksums are:

- `figure_manifest.csv`: `b8c41cb95eda295c2cc199bb7902b0480c70cd0e98e092c17bed8261bada789c`
- `figure_manifest.json`: `0c4f3adf00d084298dc492d26d0b018043c9f082f9de12f2c340cf42a22fdd50`

The change is prepared as a separate draft PR targeting `analysis/structured-a3-2026w44-refresh` and referencing refresh PR #31. PR #31 remains open and draft; neither pull request is to be merged as part of this task.

## XI. Remaining graphical limitations

Observation-location marks represent existing occupied-cell centroids, not event-level locations, because only the pre-aggregated candidate observation table was used. The fixed expected-count linear scale places most low predictions near the light end; the companion log1p view addresses visual exploration without replacing the fixed linear comparison. Two pre-existing candidate artifact-manifest mismatches are noted above.

## XII. Final decision

All requested cartographic products were generated, visually inspected, and validated without modifying prediction values or candidate artifacts. Final administrative decision: `W44_CARTOGRAPHIC_REVISION_COMPLETE`. The model remains `CANDIDATE_READY_FOR_REVIEW_NOT_PRODUCTION_QUALIFIED`.
