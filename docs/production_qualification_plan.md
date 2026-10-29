# Production qualification plan

This plan records the order, scope, and decision boundaries for qualifying the
frozen `STRUCTURED_A3` primary production candidate. The exact P0 object is
defined by [`config/production_model_freeze.json`](../config/production_model_freeze.json)
and summarized in [`production_model_freeze.md`](production_model_freeze.md).

## Qualification sequence

### P0 — Formal production freeze

Identify and preserve the canonical primary model, predictor schema, response,
training horizon, provenance, software references, required artifacts, hashes,
and deterministic inference contract. P0 produces the immutable reference for
all later work.

### P1 — Temporal, spatial, spatiotemporal, and frontier validation

Evaluate the frozen candidate under the predeclared temporal, spatial,
space-time, and frontier validation regimes. Report the estimand, data boundary,
and limitations of each regime.

### P2 — Calibration and minimal reference/null prediction assessment

Assess probability calibration, count calibration where supported, and minimal
reference/null comparators. Keep these assessments descriptive and tied to the
frozen response definition.

### P3 — Bounded robustness and sensitivity analyses

Run only bounded, pre-specified robustness and sensitivity analyses needed to
characterize material dependence on the frozen data and evaluation choices.

### P4 — Uncertainty and extrapolation assessment

Characterize predictive uncertainty, support limits, extrapolation, and
geographic or temporal regions where the frozen candidate lacks adequate
evidence.

### P5 — Operational evaluation

Evaluate the production workflow, input readiness, output contracts, failure
handling, run provenance, and operational behavior without changing the
scientific model.

### P6 — Production hardening and monitoring

Harden deployment, integrity checks, monitoring, drift detection, runbooks,
and rollback procedures. Monitoring code and wrappers remain mutable; the P0
scientific object does not.

### P7 — Publication artifact generation

Generate the reproducible reports, tables, figures, provenance summaries, and
software/data availability materials needed for publication or public release.

## Scientific boundaries and decisions

P1–P7 operate on the frozen P0 model and **must not silently modify it**. They
must not add, remove, reorder, or substitute predictors; change the response,
transformations, lags, threshold, domain, resolution, training cutoff, theta,
penalty, objective, or randomization contract; or promote a challenger based
only on performance. Flight-path predictors and SIT predictors are explicitly
outside the P0 primary model and remain separate scientific work.

If qualification identifies a material model defect, the frozen candidate fails
qualification. Any replacement is developed as a separately identified
challenger or new model version with its own provenance and freeze record. A
qualification result cannot be used to rewrite the P0 record retroactively.

This plan does not authorize P1–P7 analyses, release tagging, or manuscript
claims by itself. Each phase requires its own scoped decision record and
validation evidence. The frozen candidate remains a production candidate under
qualification until the complete decision process is finished.
