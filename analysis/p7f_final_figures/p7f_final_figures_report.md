# P7F — Final Science Figure Set Consolidation and QA

## Scope

P7F consolidates qualified P7B-P7E figure assets into a final candidate
package for scientific review. It changes layout, labeling, disposition, and
rendering only. No model fitting, prediction regeneration, recalibration,
retuning, predictor influence analysis, or support-threshold change was run.

## Canonical state

The package was built from main SHA
`5c826708c03dbd9117da0ddf0e1fa842000767d2` with frozen model
`STRUCTURED_A3`, frozen artifact SHA-256
`8a6a0a32a1a1e56f810b6aa1eafec5207dc3ac8d45cdf2270999f9721f080d1e`, and
operational proxy `E0_LAST_AVAILABLE`. The Atlas freeze verifier returned
`PRODUCTION_MODEL_FREEZE_VERIFIED`.

## Final main package

The active main set contains six figures:

1. Domain and model framework — corrected P7D domain colors, boundaries,
   hurdle schematic, and E0 timeline.
2. Predictive performance across horizons — refined P7C canonical P2 metrics.
3. Mexico-Texas spatial-temporal occurrence dynamics — corrected P7D
   occurrence-probability maps and expected positive-cell burden.
4. Rolling-origin 1-3 week nowcast trajectories — regenerated from compact
   P7E plotted data with the P7F cleanup contract.
5. Issue-time environmental proxy validation — refined P7C/P7D canonical P5A
   paired comparison.
6. Predictor associations — refined signed coefficient display with the
   mixed-scaling caveat retained.

## Final supplementary package

The supplement contains reliability curves, frontier sensitivity, count
diagnostics, proxy/support transitions, support/extrapolation, and the rolling
count-nowcast candidate. The support and count displays are retained because
they document important limitations without competing with the primary
occurrence figures.

## Archived candidates

The superseded expected-count spatial candidate and the single-W36 forecast
trajectory are preserved under `figures/archive/`. They are excluded from the
active manuscript candidate set. Earlier P7B-P7E source artifacts remain
untouched in their original directories.

## Rolling-origin cleanup

Panel A uses a dark neutral observed trajectory, light neutral forecast
threads, one orange accent for the deterministic highlighted origins, and
horizon point shapes. Direct labels identify observed positive cells and
rolling 1-3 week nowcasts. Panel B retains the signed error and zero line,
with light connecting lines and prominent points. Panel C is retained. The
count figure is supplementary by default.

## Style and visual QA

The style specification records sans-serif typography, 11-point base text,
consistent panel labels, 11 x 8.5 inch full-width main dimensions, 8.5 x 7
inch supplement dimensions, 220 DPI previews, vector SVG/PDF preference,
sequential light-low/dark-high maps, dark observed series, neutral forecast
threads, and unchanged support-class colors.

PNG previews were inspected at rendered resolution. No clipped labels,
corrupted mathematical glyphs, missing map boundaries, or unsupported
uncertainty ribbons were found in the regenerated rolling figure. The
predictor-association figure remains technically useful but does not support a
global importance ranking because scale classes are mixed and correlated.

## Reproducibility

The generator copies only qualified existing assets and regenerates the P7E
rolling occurrence figure from existing compact plotted data. The underlying
rolling plotted-data files are written deterministically. The source registry
records source files, output files, dispositions, and output hashes.

## Decision

P7F_FINAL_FIGURE_SET_SUPPORTED_WITH_LIMITATIONS

The package is coherent and QA-checked for scientific review. The remaining
limitation is that predictor associations remain conditional coefficient
displays rather than a global influence analysis; any stronger influence
figure requires a separately authorized task.
