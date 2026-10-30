# P7A Manuscript Figure and Table Design Audit Prespecification

## Objective

Audit the existing P7 publication package and define a compact journal-style
main-figure/table set without changing any P0--P7 scientific artifact. P7A may
only reuse canonical outputs or compute transparent descriptive aggregations
from retained cell-week records. It must not refit, retune, recalibrate,
select predictors, change support thresholds, or introduce a new importance
method.

## Design decisions to be audited

1. Main figures will be limited to approximately 4--6 figures and will cover
   framework/domain, horizon performance, focal Mexico--Texas behavior,
   issue-time proxy validation, predictor association/contribution, and
   support/extrapolation as space permits.
2. Main tables will be limited to approximately 3--5 tables and will cover
   model/data specification, occurrence performance, count performance, proxy
   comparison, and limitations/operational interpretation.
3. Existing P7 figures and machine-readable sources are preferred. Reformatting
   or descriptive aggregation is allowed; new scientific analyses are not.
4. A focal region must be defined from the canonical grid/domain using a fixed
   geographic rule, not optimized for visual agreement or model performance.
5. Focal map weeks must be selected by a prespecified rule evaluated against
   evenly spaced, peak-burden, largest-change, and frontier-interval options.
6. Predictor contribution will use only canonical coefficient or stability
   evidence. Raw coefficient ranking is prohibited unless scale comparability
   is demonstrated. SHAP, permutation importance, partial dependence, ALE,
   and leave-one-predictor-out refitting are out of scope.

## Source and evidence rules

Every recommended panel must identify its canonical source artifact, available
variables, temporal/spatial coverage, and whether processing is descriptive
aggregation or requires separate analytic authorization. A panel is not
publication-ready if its source cannot be traced to P0--P7 artifacts.

## Focal-region rules

The default candidate is a fixed border-corridor crop covering northern Mexico,
the U.S.--Mexico border, and central/mid-Texas. The final definition must be
stored as canonical cell IDs or a fixed bounding box with CRS and rationale.
The recommended temporal interval must be the common retained weekly interval
with adequate source coverage. The preferred regional time-series pair is
observed positive cells and the model-based expected number of positive cells
`sum_i p_i`; summed occurrence probabilities must be labeled as expected
positive-cell burden, not regional risk. Count totals may be used only where
weekly count comparability is retained.

## Proxy and support rules

The environmental figure must retain REALIZED_ENV as the retrospective reference
and E0_LAST_AVAILABLE as the selected issue-time proxy. P4 support classes and
thresholds remain unchanged. Support/extrapolation panels must show caveats and
must not imply universal environmental support.

## Rounding and terminology

Use P7 terminology: retrospective rolling-origin evaluation, prospective
issue-time proxy, 1--3 week nowcast, conditional positive count, full hurdle
expected count, SUPPORTED, CAUTION, and EXTRAPOLATIVE. Preserve canonical
numeric values in machine-readable outputs; publication formatting may round
only after source checks.

## Decision rules

Each proposed figure/table is classified MAIN_REQUIRED, MAIN_PREFERRED,
SUPPLEMENT, or DROP. Any panel requiring a new scientific analysis is marked
`REQUIRES_SEPARATE_ANALYTIC_AUTHORIZATION`. P7A ends with
`P7A_FIGURE_PLAN_SUPPORTED` when the compact plan is fully source-supported,
`P7A_FIGURE_PLAN_SUPPORTED_WITH_LIMITATIONS` when one or more desired panels
remain feasible only after bounded separate analysis, and
`P7A_FIGURE_PLAN_NOT_SUPPORTED` only if a coherent source-traceable plan cannot
be assembled.
