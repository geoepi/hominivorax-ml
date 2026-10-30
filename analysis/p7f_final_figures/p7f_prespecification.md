# P7F Final Science Figure Set Prespecification

## Scope

P7F consolidates already-qualified P7B–P7E visual artifacts into a final
science-facing figure package. It does not fit, refit, tune, recalibrate, or
change the frozen STRUCTURED_A3 model, E0_LAST_AVAILABLE proxy, support
thresholds, horizons, or scientific decisions.

## Prespecified package

- Main figures: F1–F6, with F4 regenerated from the canonical P7E compact
  rolling-origin archive using the specified neutral/accent styling.
- Supplementary figures: S1–S6.
- Archive figures: A1 expected-count spatial candidate and A2 single-W36
  trajectory.
- The main package retains the predictor-association display as a conditional
  coefficient figure, not as a global feature-importance claim.
- The package retains the rolling-origin Panel C error distribution
  provisionally; it is not converted to an uncertainty interval.

## Rolling-origin figure rules

Observed positive-cell history is dark neutral. All forecast threads are light
neutral, with origins W16, W20, W24, W28, W32, and W36 highlighted in one
accent color. Horizon is encoded by point shape. The error axis uses the
plain-language label `Forecast error (expected - observed positive cells)`.
No regional uncertainty ribbon is added because the canonical artifacts do not
support one.

## Source and provenance rules

Each figure is copied unchanged from its qualified P7C/P7D source unless the
figure is the P7E rolling-origin regeneration. The rolling-origin plotted data
are written as deterministic CSV artifacts. Every panel is registered with its
source phase, source fields, transformation/filter description, output path,
and output SHA-256.

## QA and acceptance rules

The package must have six main figures, an explicit supplement/archive
disposition, complete captions, stable output hashes or deterministic plotted
data, and a passing focused validator. No captions may contain manuscript
Results, Discussion, Methods, Introduction, or abstract prose. Predictor
associations remain limited to conditional coefficient associations with
scale-comparability caveats; stronger influence claims require a separately
authorized analysis.
