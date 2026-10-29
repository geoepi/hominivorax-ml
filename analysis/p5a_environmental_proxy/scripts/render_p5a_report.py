#!/usr/bin/env python3
"""Render the human-readable P5A report from deterministic result files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def table(frame: pd.DataFrame, columns: list[str], digits: int = 4) -> str:
    if frame.empty:
        return "_No rows._"
    work = frame[columns].copy()
    for column in work.columns:
        if pd.api.types.is_float_dtype(work[column]):
            work[column] = work[column].map(lambda value: "NA" if pd.isna(value) else f"{value:.{digits}f}")
    return work.to_markdown(index=False)


def render(repository_root: Path, output_root: Path) -> None:
    metrics_root = output_root / "metrics"
    manifests = output_root / "manifests"
    metadata = json.loads((manifests / "run_metadata.json").read_text(encoding="utf-8"))
    decision = json.loads((metrics_root / "decision.json").read_text(encoding="utf-8"))
    availability = json.loads((metrics_root / "availability_reclassification.json").read_text(encoding="utf-8"))
    applicability = pd.read_csv(manifests / "proxy_applicability.csv")
    e2 = pd.read_csv(manifests / "e2_feasibility.csv")
    occurrence = pd.read_csv(metrics_root / "occurrence_count_metrics.csv")
    paired = pd.read_csv(metrics_root / "paired_proxy_minus_realized.csv")
    frontier = pd.read_csv(metrics_root / "frontier_metrics.csv")
    support = pd.read_csv(metrics_root / "support_metrics.csv")
    transitions = pd.read_csv(metrics_root / "support_transitions.csv")
    env = pd.read_csv(metrics_root / "environmental_proxy_error.csv")
    env_family = pd.read_csv(metrics_root / "environmental_proxy_error_by_family.csv")
    coverage = pd.read_csv(metrics_root / "coverage.csv")

    env_app = applicability.loc[applicability["proxy_applicable"]].copy()
    unchanged = applicability.loc[~applicability["proxy_applicable"]].copy()
    metric_view = occurrence.loc[occurrence["proxy_id"].isin(["REALIZED_ENV", "E0_LAST_AVAILABLE", "E1_TRAILING3_MEAN"]), ["proxy_id", "horizon", "n", "positives", "prevalence", "brier", "calibration_intercept", "calibration_slope", "log_loss", "auroc", "auprc", "conditional_mae", "conditional_bias", "full_expected_mae", "full_expected_bias"]]
    degradation_view = paired.loc[paired["metric"].isin(["brier", "calibration_intercept", "calibration_slope", "log_loss", "auprc", "conditional_mae", "conditional_bias", "full_expected_mae", "full_expected_bias"])]
    frontier_view = frontier.loc[frontier["frontier_class"].isin(["previously_occupied", "previously_unoccupied"]), ["proxy_id", "horizon", "frontier_class", "n", "positives", "brier", "calibration_intercept", "calibration_slope", "auprc"]]
    support_view = support.loc[support["proxy_id"].isin(["REALIZED_ENV", "E0_LAST_AVAILABLE", "E1_TRAILING3_MEAN"])]
    transition_view = transitions.loc[transitions["n"] > 0]
    error_family_view = env_family.loc[env_family["proxy_id"].isin(["E0_LAST_AVAILABLE", "E1_TRAILING3_MEAN"])]

    report = f"""# P5A Issue-Time Environmental Proxy Validation

## I. Governance

SAE governance and the Atlas SSH policy were reviewed. Atlas execution used
the authorized WSL/Ubuntu `atlas-ssh` route. P5A remained within environmental
input-contract validation: no coefficients, P0 artifact, predictor identities,
transformations, P4 thresholds, or response definitions were changed. The
validated Atlas environment was not modified to install pytest.

## II. Canonical Starting State

P5 merge SHA: `650edd2397279a1a6a68dd89e42c724621d6da04`. P5 decision was
`P5_OPERATIONAL_CONTRACT_NOT_SUPPORTED` with production availability
`RETROSPECTIVE_ONLY`. P0 freeze verification passed. Frozen model:
`STRUCTURED_A3`; frozen artifact SHA-256:
`8a6a0a32a1a1e56f810b6aa1eafec5207dc3ac8d45cdf2270999f9721f080d1e`.

## III. P5A Repository State

P5A repository SHA during result generation: `{metadata.get('repository_sha')}`.
The exact P2 rolling-origin fit artifacts were reused; `no_model_refit` is
`True`. The P2 reference archive was preserved unchanged with hash
`{metadata.get('p2_archive_sha256')}`. The P5A result root contains atomic
per-origin outputs and a completion ledger.

## IV. Proxy Definitions

| Contract | Definition |
|---|---|
| REALIZED_ENV | Unchanged P2 target-week environmental values and predictions. |
| E0_LAST_AVAILABLE | Persist the latest safely prior environmental feature state at `L(T)=T-1` across h=1,2,3. |
| E1_TRAILING3_MEAN | Mean of exactly the three prior feature states `T-1:T-3`, held across h=1,2,3. |
| E2_SEASONAL_EXPECTATION | Same ISO-week historical mean using only observations through `T-1`, requiring two prior seasonal cycles. |

## V. Predictor Applicability

All 12 P5 `RETROSPECTIVE_ONLY` environmental predictors received proxy
substitution. Already-lagged ERA5-Land soil-temperature and soil-water
features were treated as frozen feature values; they were not re-lagged or
re-transformed. The remaining {len(unchanged)} frozen predictors remained unchanged.

Eligible predictors: {', '.join(env_app['predictor'].tolist())}.

## VI. Rolling-Origin Execution

The P2 design was reused: {metadata.get('origin_count')} origins from
`2026-W16` through `2026-W36`, h=1,2,3, expanding-window fitted artifacts,
and identical paired P2 records. Completed origins: {metadata.get('origin_count')};
failed origins: {metadata.get('failed_origins') or 'none'}. E2 feasibility:
{metadata.get('e2_status')}; available E2 rows: {int((e2['status'] == 'AVAILABLE').sum())}.

## VII. Environmental Proxy Accuracy

The proxy error analysis used only environmental observations through `T-1`.
Errors are proxy minus realized target-week feature values.

{table(error_family_view, ['proxy_id', 'horizon', 'family', 'n', 'mean_error', 'mae', 'rmse', 'correlation'])}

## VIII. Occurrence and Count Performance

REALIZED_ENV is the unchanged P2 reference. The following table reports the
paired evaluation metrics for the realized condition and the two evaluable
proxies.

{table(metric_view, ['proxy_id', 'horizon', 'n', 'positives', 'prevalence', 'brier', 'calibration_intercept', 'calibration_slope', 'log_loss', 'auroc', 'auprc', 'conditional_mae', 'conditional_bias', 'full_expected_mae', 'full_expected_bias'])}

## IX. Proxy Degradation

Proxy-minus-realized effects were calculated on identical keys. Dependence-
aware target-week block bootstrap intervals use the prespecified 199
replicates and seed `20261029`; the machine-readable intervals are in
`metrics/bootstrap_intervals.csv`.

{table(degradation_view, ['proxy_id', 'horizon', 'metric', 'proxy_value', 'realized_value', 'difference_proxy_minus_realized'])}

## X. Count Performance

Conditional positive-count and full-hurdle expected-count MAE, RMSE, bias, and
observed/predicted totals are included in `occurrence_count_metrics.csv` and
the paired degradation table. No recalibration was performed.

## XI. Frontier Evaluation

Frontier effects were evaluated separately for previously occupied and
previously unoccupied cells. Newly detected frontier positives remain a
descriptive sparse-outcome subclass and were not pooled into established rows.

{table(frontier_view, ['proxy_id', 'horizon', 'frontier_class', 'n', 'positives', 'brier', 'calibration_intercept', 'calibration_slope', 'auprc'])}

## XII. Support / Extrapolation

P4 support thresholds were consumed unchanged and support classes were
recalculated from each proxy predictor matrix against the P4 training-only
reference distribution.

{table(support_view, ['proxy_id', 'horizon', 'support_class', 'n', 'proportion'])}

Nonzero support transitions are recorded below:

{table(transition_view, ['proxy_id', 'from_support_class', 'to_support_class', 'n'])}

## XIII. Proxy Decision

{table(pd.DataFrame(decision.get('proxy_decisions', [])), ['proxy_id', 'classification', 'reason'])}

The prespecified simplicity-first rule selected
`{decision.get('selected_proxy_id')}`. No proxy-window or threshold tuning was
performed after results were inspected.

## XIV. Production Availability Reclassification

Previous classification: `RETROSPECTIVE_ONLY`.

Updated classification: `{availability.get('classification')}`.

The selected proxy requires a source observation week no later than `T-1` and
a source vintage timestamp no later than the issue timestamp. P5's
non-environmental limitations remain explicit; proxy acceptance does not make
future environmental observations available or alter the frozen model.

## XV. Operational Contract Update

The separately versioned P5A proxy contract is recorded in
`manifests/proxy_contract.json`. Required future production provenance fields
are proxy ID, latest environmental observation week, trailing-window weeks,
source vintages, proxy generation timestamp, and input hashes. A production
implementation must fail on missing, future-vintage, or nonfinite proxy inputs.

## XVI. Artifacts

- `analysis/p5a_environmental_proxy/p5a_prespecification.md`
- `analysis/p5a_environmental_proxy/results/` compact machine-readable results
- `analysis/p5a_environmental_proxy/figures/P5A-1_proxy_design.png` through `P5A-6_support_class_impact.png`
- Atlas output root: `{output_root}`

## XVII. CI / PR / Merge

Hosted CI, PR, merge, post-merge freeze verification, and cleanup are recorded
in the task handoff. No production release tag was created.

## XVIII. P5A Decision

{decision.get('decision')}
"""
    path = repository_root / "analysis" / "p5a_environmental_proxy" / "p5a_environmental_proxy_report.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report, encoding="utf-8")
    print(json.dumps({"status": "RENDERED", "report": str(path), "decision": decision.get("decision")}, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    render(args.repository_root.resolve(), args.output_root.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
