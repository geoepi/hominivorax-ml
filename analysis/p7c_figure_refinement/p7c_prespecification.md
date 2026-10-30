# P7C Figure Refinement Prespecification

P7C revises rendering, cartographic context, palettes, legends, and technical
captions only. The P7B scientific inputs and results remain unchanged.

Locked analytical choices:

- model: `STRUCTURED_A3`;
- proxy: `E0_LAST_AVAILABLE`;
- focal CRS: EPSG:4326;
- focal bounding box: longitude -107.5 to -96.0, latitude 24.0 to 33.0;
- focal cells: 1,689;
- h=1 focal interval: 2026-W17 through 2026-W37;
- map weeks: 2026-W17, W22, W27, W32, W37;
- support thresholds and definitions: unchanged P4 specification;
- occurrence and count values: canonical P7B outputs only.

Rendering contract:

- canonical grid-cell surfaces use `ggplot2::geom_tile`;
- boundary orientation uses the `study_states` layer from the provided Atlas
  GeoPackage, transformed to EPSG:4326;
- map comparisons use shared spatial extents and shared scale limits;
- map panels include longitude/latitude axes, boundary overlays, a north arrow,
  and a scale bar;
- occurrence and expected-count Figure 3 candidates are both retained;
- the P4 support map is reused where complete cell-level support records are
  unavailable for a new re-render.

Palette contract:

- continuous surfaces use viridis option D for occurrence probability and
  option C for expected count;
- `SUPPORTED` is green (`#009E73`), `CAUTION` is orange (`#E69F00`), and
  `EXTRAPOLATIVE` is vermilion (`#D55E00`);
- support classes are predictor-space support states, not confidence
  intervals, direct correctness measures, or causal categories.

Prohibited actions:

- model fitting, refitting, tuning, recalibration, or feature selection;
- changing the focal region, map weeks, response definitions, support
  thresholds, proxy rule, or scientific values;
- SHAP, permutation importance, ALE, partial dependence, ablation, or other
  new predictor-importance analyses;
- manuscript prose beyond concise technical figure captions.
