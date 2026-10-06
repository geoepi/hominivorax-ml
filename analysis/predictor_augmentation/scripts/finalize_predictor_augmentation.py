#!/usr/bin/env python3
"""Finalize metrics, guardrails, diagnostics, figures, and report."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

FOLDS = (1, 2, 3, 4)
MODELS = ("A0", "A1", "A2", "A3")
PAIRS = (("A0", "A1", "A1_vs_A0"), ("A0", "A2", "A2_vs_A0"), ("A0", "A3", "A3_vs_A0"), ("A1", "A3", "A3_vs_A1"), ("A2", "A3", "A3_vs_A2"))
ADDED_FEATURES = ("road_density", "night_illumination", "clay_0_15", "water_difference_wv0033_minus_wv0010_0_15")
METRICS = ("joint_hurdle_nll", "pr_auc", "roc_auc", "brier", "brier_skill", "calibration_intercept", "calibration_slope", "positive_count_mae", "positive_count_rmse", "conditional_mean_bias")
NLL_WORST_DEGRADATION_TOL = 0.005
PRIMARY_WORST_DEGRADATION_TOL = 0.005
CALIBRATION_DISTANCE_WORST_TOL = 0.10
CALIBRATION_DISTANCE_MEAN_MINIMUM = -0.05


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def jsonable(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def atomic_write(path: Path, writer) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    writer(temporary)
    temporary.replace(path)


def atomic_json(path: Path, payload: Any) -> None:
    atomic_write(path, lambda temporary: temporary.write_text(json.dumps(jsonable(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8"))


def atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    atomic_write(path, lambda temporary: frame.to_csv(temporary, index=False))


def read_tasks(output: Path) -> pd.DataFrame:
    manifest = pd.read_csv(output / "model_task_manifest.csv")
    rows: list[dict[str, Any]] = []
    for row in manifest.itertuples(index=False):
        path = output / str(row.output_path)
        if not path.exists():
            raise RuntimeError(f"STOP: missing task output {path}")
        result = json.loads(path.read_text(encoding="utf-8"))
        if result.get("status") != "completed":
            raise RuntimeError(f"STOP: task not completed {path}")
        if int(result["fold"]) not in FOLDS or result["model"] not in MODELS:
            raise RuntimeError(f"invalid task identity in {path}")
        metrics = result["metrics"]
        row_values = {"task_id": int(result["task_id"]), "fold": int(result["fold"]), "model": str(result["model"]), "runtime_seconds": float(result.get("runtime_seconds", np.nan)), "converged": bool(result.get("fit_info", {}).get("occurrence_success") and result.get("fit_info", {}).get("count_success")), "theta": float(result["theta"]), "penalty": float(result["penalty"])}
        row_values.update({metric: metrics.get(metric) for metric in METRICS})
        row_values["calibration_distance"] = float(np.hypot(float(metrics["calibration_intercept"]), float(metrics["calibration_slope"]) - 1.0))
        rows.append(row_values)
    frame = pd.DataFrame(rows).sort_values(["model", "fold"]).reset_index(drop=True)
    if len(frame) != 16 or frame.groupby(["model", "fold"]).size().max() != 1:
        raise RuntimeError("expected exactly one completed result for each of 16 fold/model tasks")
    return frame


def pairwise(metrics: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for comparator, augmented, name in PAIRS:
        left = metrics.loc[metrics["model"] == comparator].set_index("fold")
        right = metrics.loc[metrics["model"] == augmented].set_index("fold")
        for fold in FOLDS:
            a, b = left.loc[fold], right.loc[fold]
            rows.append({
                "fold": fold, "comparison": name, "comparator_model": comparator, "augmented_model": augmented,
                "delta_joint_nll": float(a["joint_hurdle_nll"] - b["joint_hurdle_nll"]),
                "delta_pr_auc": float(b["pr_auc"] - a["pr_auc"]),
                "delta_roc_auc": float(b["roc_auc"] - a["roc_auc"]),
                "delta_brier": float(a["brier"] - b["brier"]),
                "delta_brier_skill": float(b["brier_skill"] - a["brier_skill"]),
                "delta_calibration_intercept": float(b["calibration_intercept"] - a["calibration_intercept"]),
                "delta_calibration_slope": float(b["calibration_slope"] - a["calibration_slope"]),
                "delta_calibration_distance": float(a["calibration_distance"] - b["calibration_distance"]),
                "delta_count_mae": float(a["positive_count_mae"] - b["positive_count_mae"]),
                "delta_count_rmse": float(a["positive_count_rmse"] - b["positive_count_rmse"]),
            })
    return pd.DataFrame(rows)


def coefficient_stability(output: Path) -> pd.DataFrame:
    manifest = pd.read_csv(output / "model_task_manifest.csv")
    rows: list[dict[str, Any]] = []
    for row in manifest.itertuples(index=False):
        result = json.loads((output / str(row.output_path)).read_text(encoding="utf-8"))
        for coefficient in result.get("coefficient_rows", []):
            if coefficient["feature"] in ADDED_FEATURES:
                rows.append({"row_type": "fold", **coefficient})
    detail = pd.DataFrame(rows)
    summaries: list[dict[str, Any]] = []
    if not detail.empty:
        for (model, component, feature), group in detail.groupby(["model", "component", "feature"], sort=True):
            signs = group["sign"].value_counts()
            dominant = int(signs.max()) if len(signs) else 0
            summaries.append({"row_type": "summary", "model": model, "component": component, "feature": feature, "folds": len(group), "mean_coefficient": group["coefficient_standardized"].mean(), "sd_coefficient": group["coefficient_standardized"].std(ddof=0), "minimum_coefficient": group["coefficient_standardized"].min(), "maximum_coefficient": group["coefficient_standardized"].max(), "dominant_sign": signs.index[0] if len(signs) else "unknown", "dominant_sign_folds": dominant, "stable_sign": bool(dominant >= 3), "fold": np.nan, "coefficient_standardized": np.nan, "sign": "summary", "absolute_coefficient": np.nan})
    return pd.concat([detail, pd.DataFrame(summaries)], ignore_index=True, sort=False) if summaries else detail


def pair_summary(pair: pd.DataFrame, name: str) -> dict[str, Any]:
    subset = pair.loc[pair["comparison"] == name]
    return {"mean_delta_nll": float(subset["delta_joint_nll"].mean()), "median_delta_nll": float(subset["delta_joint_nll"].median()), "worst_fold_delta_nll": float(subset["delta_joint_nll"].min()), "best_fold_delta_nll": float(subset["delta_joint_nll"].max()), "sd_delta_nll": float(subset["delta_joint_nll"].std(ddof=0)), "iqr_delta_nll": float(subset["delta_joint_nll"].quantile(.75) - subset["delta_joint_nll"].quantile(.25)), "folds_improved_nll": int((subset["delta_joint_nll"] > 0).sum()), "mean_delta_pr_auc": float(subset["delta_pr_auc"].mean()), "worst_fold_delta_pr_auc": float(subset["delta_pr_auc"].min()), "folds_improved_pr_auc": int((subset["delta_pr_auc"] > 0).sum()), "mean_delta_brier_skill": float(subset["delta_brier_skill"].mean()), "worst_fold_delta_brier_skill": float(subset["delta_brier_skill"].min()), "folds_improved_brier_skill": int((subset["delta_brier_skill"] > 0).sum()), "mean_delta_calibration_distance": float(subset["delta_calibration_distance"].mean()), "worst_fold_delta_calibration_distance": float(subset["delta_calibration_distance"].min()), "worst_fold": int(subset.loc[subset["delta_joint_nll"].idxmin(), "fold"]), "pair_name": name}


def classify(summary: dict[str, Any], coefficient_rows: pd.DataFrame, augmented: str) -> str:
    if augmented == "A0":
        return "REFERENCE"
    stable = True
    if not coefficient_rows.empty:
        selected = coefficient_rows.loc[(coefficient_rows["row_type"] == "summary") & (coefficient_rows["model"] == augmented)]
        stable = bool(selected.empty or selected["stable_sign"].fillna(False).all())
    credible = (
        summary["mean_delta_nll"] >= 0.0
        and summary["mean_delta_brier_skill"] >= 0.0
        and summary["mean_delta_pr_auc"] >= 0.0
        and summary["worst_fold_delta_nll"] >= -NLL_WORST_DEGRADATION_TOL
        and summary["worst_fold_delta_brier_skill"] >= -PRIMARY_WORST_DEGRADATION_TOL
        and summary["worst_fold_delta_calibration_distance"] >= -CALIBRATION_DISTANCE_WORST_TOL
        and summary["mean_delta_calibration_distance"] >= CALIBRATION_DISTANCE_MEAN_MINIMUM
        and stable
    )
    mixed = summary["mean_delta_nll"] >= 0 or summary["mean_delta_brier_skill"] >= 0 or summary["mean_delta_pr_auc"] >= 0
    return "SUPPORTED" if credible else "HOLD / AMBIGUOUS" if mixed else "NOT SUPPORTED"


def make_figures(output: Path, pair: pd.DataFrame, metrics: pd.DataFrame, coefficients: pd.DataFrame) -> str:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as error:
        return f"unavailable: {error}"
    figure_dir = output / "figures"
    figure_dir.mkdir(parents=True, exist_ok=True)
    for metric, label, filename in (("delta_joint_nll", "Improvement in joint NLL", "fold_delta_joint_nll.png"), ("delta_pr_auc", "Improvement in PR-AUC", "fold_delta_pr_auc.png"), ("delta_brier_skill", "Improvement in Brier skill", "fold_delta_brier_skill.png")):
        fig, ax = plt.subplots(figsize=(7, 4))
        for name in ("A1_vs_A0", "A2_vs_A0", "A3_vs_A0"):
            sub = pair.loc[pair["comparison"] == name]
            ax.plot(sub["fold"], sub[metric], marker="o", label=name)
        ax.axhline(0, color="black", linewidth=.8)
        ax.set(xlabel="F1--F4 fold", ylabel=label)
        ax.legend()
        fig.tight_layout(); fig.savefig(figure_dir / filename, dpi=160); plt.close(fig)
    for name, filename, title in (("A3_vs_A1", "a3_vs_a1_soil_retention.png", "A3 vs A1: soil retention"), ("A3_vs_A2", "a3_vs_a2_anthropogenic_retention.png", "A3 vs A2: anthropogenic retention")):
        sub = pair.loc[pair["comparison"] == name]
        fig, ax = plt.subplots(figsize=(7, 4))
        ax.plot(sub["fold"], sub["delta_joint_nll"], marker="o", label="joint NLL")
        ax.plot(sub["fold"], sub["delta_brier_skill"], marker="s", label="Brier skill")
        ax.plot(sub["fold"], sub["delta_pr_auc"], marker="^", label="PR-AUC")
        ax.axhline(0, color="black", linewidth=.8); ax.set(xlabel="F1--F4 fold", ylabel="Improvement", title=title); ax.legend()
        fig.tight_layout(); fig.savefig(figure_dir / filename, dpi=160); plt.close(fig)
    cal = pair.groupby("comparison", as_index=False)["delta_calibration_distance"].mean()
    fig, ax = plt.subplots(figsize=(8, 4)); ax.bar(cal["comparison"], cal["delta_calibration_distance"]); ax.axhline(0, color="black", linewidth=.8); ax.set_ylabel("Movement toward ideal calibration"); fig.tight_layout(); fig.savefig(figure_dir / "calibration_comparison.png", dpi=160); plt.close(fig)
    detail = coefficients.loc[(coefficients["row_type"] == "fold") & (coefficients["model"] == "A3")]
    fig, ax = plt.subplots(figsize=(9, 5))
    if not detail.empty:
        for (feature, component), group in detail.groupby(["feature", "component"]):
            ax.plot(group["fold"], group["coefficient_standardized"], marker="o", label=f"{feature} ({component})")
    ax.axhline(0, color="black", linewidth=.8); ax.set(xlabel="F1--F4 fold", ylabel="Standardized coefficient", title="A3 coefficient stability"); ax.legend(fontsize=7); fig.tight_layout(); fig.savefig(figure_dir / "coefficient_stability.png", dpi=160); plt.close(fig)
    return "complete"


def render_report(output: Path, manifest: dict[str, Any], metrics: pd.DataFrame, summary: pd.DataFrame, pair_summary_frame: pd.DataFrame, recommendation: dict[str, Any]) -> None:
    def fmt(value: Any) -> str:
        return "NA" if value is None or (isinstance(value, float) and not np.isfinite(value)) else f"{float(value):.6g}" if isinstance(value, (float, np.floating)) else str(value)
    model_lines = []
    for row in summary.itertuples(index=False):
        model_lines.append(f"| {row.model} | {row.added_features or 'none'} | {fmt(row.mean_nll_vs_a0)} | {fmt(row.mean_pr_auc_vs_a0)} | {fmt(row.mean_brier_skill_vs_a0)} | {row.worst_fold} | {fmt(row.mean_calibration_distance_vs_a0)} | {row.status} |")
    pair_lines = []
    for row in pair_summary_frame.itertuples(index=False):
        pair_lines.append(f"| {row.pair_name} | {fmt(row.mean_delta_nll)} | {fmt(row.mean_delta_pr_auc)} | {fmt(row.mean_delta_brier_skill)} | F{int(row.worst_fold)} | {row.interpretation} |")
    transformations = manifest.get("transformations", {})
    report = f"""# Controlled predictor augmentation — A0–A3 development comparison

## 1. Objective

This development-only analysis compares frozen V2-A (A0) with road/night
augmentation (A1), frozen Phase S2 soil augmentation (A2), and the joint
augmentation (A3). It uses no terminal, prospective, later, or F5/F6 outcomes.

## 2. Provenance

- augmentation branch: `{manifest.get('branch')}`
- starting consolidated `main` SHA: `{manifest.get('starting_main_sha')}`
- `origin/main` SHA recorded at start: `{manifest.get('origin_main_sha_at_start')}`
- frozen soil branch SHA: `{manifest.get('soil_branch_sha')}`
- frozen soil specification: `clay_0_15`, `water_difference_wv0033_minus_wv0010_0_15`
- road source: `/project/disease_ecology/NWScrewworm/data/raw_data/road_density/road_density_crp.tif`
- nighttime source: `/project/disease_ecology/NWScrewworm/data/raw_data/night_illumination/night_illum_crp.tif`
- fixed-theta baseline manifest: `analysis/predictor_augmentation/provenance/fixed_theta_baseline_manifest.json`

## 3. Static feature construction

Road density and nighttime illumination were aggregated with exact area-aware
overlap weights to the existing canonical mask-cell polygons. The source
rasters were not modified. The frozen soil node-level values were reused from
the validated Phase S1 table; no SoilGrids aggregation or Phase S1/S2 rerun was
performed. The pre-response marginal rule selected transformations:
`{json.dumps(transformations, sort_keys=True)}`.

## 4. Data/join QA

The join retained exactly 10,037 canonical nodes and 68 × 10,037 development
node-weeks. Missingness and coverage results are in `join_qa.csv`,
`missingness_qa.csv`, and `road_night_aggregation_qa.csv`. No ad hoc imputation
was used.

## 5. Model protocol

All fits use the same 30 frozen V2-A predictors, exact joint hurdle NLL,
Bernoulli occurrence, zero-truncated negative-binomial positive-count model,
penalty `0.01`, fixed theta `0.7018903965556372`, L-BFGS-B, and fold-safe
training-only scaling. Only F1–F4 are used. No STGNN is fitted.

## 6. A0–A3 results

| Model | Added features | Mean Δ NLL vs A0 | Mean Δ PR-AUC vs A0 | Mean Δ BSS vs A0 | Worst fold | Calibration movement | Status |
|---|---|---:|---:|---:|---|---:|---|
{chr(10).join(model_lines)}

## 7. Pairwise interpretation

| Comparison | Mean Δ NLL | Mean Δ PR-AUC | Mean Δ BSS | Worst fold | Interpretation |
|---|---:|---:|---:|---|---|
{chr(10).join(pair_lines)}

Positive deltas indicate improvement. The key soil-retention comparison is
A3 vs A1; the key anthropogenic-retention comparison is A3 vs A2. Proper scores
and calibration take precedence over ROC-AUC.

## 8. Calibration and stability

Calibration movement is measured toward intercept 0 and slope 1. Standardized
coefficients for all four additions and both hurdle components are in
`augmentation_effect_stability.csv`; fold signs and magnitudes are diagnostic,
not p-value selection criteria. Guardrails use the same conservative worst-fold
and stability philosophy as corrected Phase S2.

## 9. Final recommended specification

**{recommendation['model']}** — {recommendation['added_features'] or 'no added predictors'}.

Rationale: {recommendation['rationale']}

## 10. Final disposition

F1–F4 only: **YES**  
F5/F6 used for selection: **NO**  
Terminal/later responses used: **NO**  
Theta re-estimated: **NO**  
Soil specification changed: **NO**  
STGNN fitted: **NO**  
Production V2-A altered: **NO**

{recommendation['final_disposition']}
"""
    atomic_write(output / "predictor_augmentation_report.md", lambda temporary: temporary.write_text(report, encoding="utf-8"))


def finalize(output: Path, reference_manifest_path: Path) -> None:
    gate_path = output / "baseline_gate.json"
    if not gate_path.exists() or not json.loads(gate_path.read_text(encoding="utf-8")).get("pass", False):
        raise RuntimeError("STOP: A0 baseline reproduction gate is absent or failed")
    metrics = read_tasks(output)
    atomic_csv(output / "fold_metrics.csv", metrics)
    calibration = metrics[["model", "fold", "calibration_intercept", "calibration_slope", "calibration_distance"]].copy()
    calibration["ideal_intercept"] = 0.0; calibration["ideal_slope"] = 1.0
    atomic_csv(output / "calibration_metrics.csv", calibration)
    pair = pairwise(metrics)
    atomic_csv(output / "pairwise_comparison_deltas.csv", pair)
    coefficients = coefficient_stability(output)
    atomic_csv(output / "augmentation_effect_stability.csv", coefficients)
    scaling_rows: list[dict[str, Any]] = []
    manifest = pd.read_csv(output / "model_task_manifest.csv")
    for row in manifest.itertuples(index=False):
        result = json.loads((output / str(row.output_path)).read_text(encoding="utf-8"))
        for feature, mean, sd in zip(result["scaling"]["feature_names"], result["scaling"]["training_mean"], result["scaling"]["training_sd"]):
            if feature in ADDED_FEATURES:
                scaling_rows.append({"task_id": int(result["task_id"]), "fold": int(result["fold"]), "model": result["model"], "component": "predictor", "feature": feature, "training_mean": mean, "training_sd": sd})
    atomic_csv(output / "scaling_parameters.csv", pd.DataFrame(scaling_rows))

    summaries: list[dict[str, Any]] = []
    pair_summaries = {name: pair_summary(pair, name) for _, _, name in PAIRS}
    statuses: dict[str, str] = {"A0": "REFERENCE"}
    for model, comparison in (("A1", "A1_vs_A0"), ("A2", "A2_vs_A0"), ("A3", "A3_vs_A0")):
        statuses[model] = classify(pair_summaries[comparison], coefficients, model)
    a3_retains_both = all(classify(pair_summaries[name], coefficients, "A3") == "SUPPORTED" for name in ("A3_vs_A1", "A3_vs_A2"))
    if statuses["A3"] == "SUPPORTED" and a3_retains_both:
        recommendation_model = "A3"
        rationale = "A3 provides credible, stable proper-score and calibration improvement over A0 and retains incremental value against both simpler augmentations."
    elif statuses["A1"] == "SUPPORTED" and statuses["A2"] == "SUPPORTED":
        recommendation_model = "A1" if pair_summaries["A1_vs_A0"]["mean_delta_nll"] >= pair_summaries["A2_vs_A0"]["mean_delta_nll"] else "A2"
        rationale = "Both single-family augmentations are supported; the simpler family with the stronger mean joint-NLL improvement is preferred on parsimony grounds."
    elif statuses["A1"] == "SUPPORTED":
        recommendation_model = "A1"; rationale = "The anthropogenic augmentation is supported while the alternatives are not consistently supported by proper scores, calibration, and fold stability."
    elif statuses["A2"] == "SUPPORTED":
        recommendation_model = "A2"; rationale = "The frozen soil augmentation is supported while the alternatives are not consistently supported by proper scores, calibration, and fold stability."
    else:
        recommendation_model = "A0"; rationale = "No augmentation meets the predeclared proper-score, calibration, worst-fold, and stability guardrails."
    recommendation = {"model": recommendation_model, "added_features": "+".join({"A0": [], "A1": ["road_density", "night_illumination"], "A2": ["clay_0_15", "water_difference_wv0033_minus_wv0010_0_15"], "A3": list(ADDED_FEATURES)}[recommendation_model]), "rationale": rationale, "final_disposition": "AUGMENTED SPECIFICATION FROZEN FOR NEXT MODELING STAGE" if recommendation_model != "A0" else "NO AUGMENTATION ADVANCED BEYOND V2-A"}
    summary_rows: list[dict[str, Any]] = []
    for model in MODELS:
        base = metrics.loc[metrics["model"] == model]
        if model == "A0":
            s = {"mean_delta_nll": 0.0, "mean_delta_pr_auc": 0.0, "mean_delta_brier_skill": 0.0, "mean_delta_calibration_distance": 0.0, "worst_fold": "reference"}
        else:
            s = pair_summaries[f"{model}_vs_A0"]
        a3a1 = pair_summaries["A3_vs_A1"] if model == "A3" else {}
        a3a2 = pair_summaries["A3_vs_A2"] if model == "A3" else {}
        summary_rows.append({"model": model, "added_features": "+".join({"A0": [], "A1": ["road_density", "night_illumination"], "A2": ["clay_0_15", "water_difference_wv0033_minus_wv0010_0_15"], "A3": list(ADDED_FEATURES)}[model]), "mean_nll": base["joint_hurdle_nll"].mean(), "mean_pr_auc": base["pr_auc"].mean(), "mean_brier_skill": base["brier_skill"].mean(), "mean_nll_vs_a0": s["mean_delta_nll"], "mean_pr_auc_vs_a0": s["mean_delta_pr_auc"], "mean_brier_skill_vs_a0": s["mean_delta_brier_skill"], "mean_calibration_distance_vs_a0": s["mean_delta_calibration_distance"], "worst_fold": s["worst_fold"], "a3_vs_a1_mean_delta_nll": a3a1.get("mean_delta_nll"), "a3_vs_a1_mean_delta_brier_skill": a3a1.get("mean_delta_brier_skill"), "a3_vs_a2_mean_delta_nll": a3a2.get("mean_delta_nll"), "a3_vs_a2_mean_delta_brier_skill": a3a2.get("mean_delta_brier_skill"), "status": statuses[model]})
    summary = pd.DataFrame(summary_rows)
    atomic_csv(output / "augmentation_summary.csv", summary)
    pair_summary_rows = []
    interpretations = {"A1_vs_A0": "incremental anthropogenic value", "A2_vs_A0": "incremental soil value", "A3_vs_A0": "full augmentation value", "A3_vs_A1": "soil retention after roads/night illumination", "A3_vs_A2": "anthropogenic retention after soil"}
    for name, values in pair_summaries.items():
        pair_summary_rows.append({**values, "interpretation": interpretations[name]})
    pair_summary_frame = pd.DataFrame(pair_summary_rows)
    atomic_csv(output / "pairwise_summary.csv", pair_summary_frame)
    atomic_csv(output / "final_augmentation_recommendation.csv", pd.DataFrame([recommendation]))
    figure_status = make_figures(output, pair, metrics, coefficients)
    atomic_write(output / "figures/figure_generation_status.txt", lambda temporary: temporary.write_text(figure_status + "\n", encoding="utf-8"))
    manifest_path = output / "manifests/augmentation_manifest.json"
    final_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    final_manifest.update({"status": "complete", "finalized_utc": now(), "baseline_gate_passed": True, "recommendation": recommendation, "statuses": statuses, "figure_generation": figure_status, "atlas_job_ids": {key: value for key, value in os.environ.items() if "SLURM" in key and "JOB" in key}, "execution": {"fit_count": 16, "completed": 16, "failed": 0, "array_concurrency": os.environ.get("AUGMENTATION_ARRAY_CONCURRENCY", "declared by sbatch"), "terminal_response_loaded": False, "stgnn_fitted": False}})
    atomic_json(manifest_path, final_manifest)
    render_report(output, final_manifest, metrics, summary, pair_summary_frame, recommendation)
    atomic_json(output / "final_augmentation_recommendation.json", recommendation)
    print(json.dumps({"status": "complete", "recommendation": recommendation, "statuses": statuses, "figure_generation": figure_status}, indent=2))

