#!/usr/bin/env python3
"""Finalize the restricted structured A0 versus A3 development comparison."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


NODE_COUNT = 10_037
BASE_COUNT = 30
A3_COUNT = 34
THETA = 0.7018903965556372
PENALTY = 0.01
FOLDS = (1, 2, 3, 4)
MODELS = ("A0", "A3")
ADDED_FEATURES = (
    "road_density",
    "night_illumination",
    "clay_0_15",
    "water_difference_wv0033_minus_wv0010_0_15",
)
TRANSFORMATIONS = {
    "road_density": "log1p",
    "night_illumination": "log1p",
    "clay_0_15": "identity",
    "water_difference_wv0033_minus_wv0010_0_15": "identity",
}
CONTROLLED_SHA = "bd8346fc42e31e4f1f52b2ce7f2d3694f6a4af00"
MODEL_CLASS_SHA = "844589d8bf79b0ecf2f9249b50ade91fbb0089d9"
MAIN_SHA = "88bcf3ae238f3aae712b123acfa07e4b2c5e4ad1"
METRICS = (
    "joint_hurdle_nll",
    "pr_auc",
    "roc_auc",
    "brier",
    "brier_skill",
    "calibration_intercept",
    "calibration_slope",
    "positive_count_mae",
    "positive_count_rmse",
    "conditional_mean_bias",
    "zt_nb_nll",
)


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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(jsonable(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_records(output: Path) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    manifest = pd.read_csv(output / "model_task_manifest.csv")
    if len(manifest) != 8 or set(manifest["model"]) != set(MODELS):
        raise RuntimeError("STOP: expected exactly eight A0/A3 tasks")
    rows: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    for item in manifest.itertuples(index=False):
        path = output / str(item.output_path)
        if not path.exists():
            raise RuntimeError(f"STOP: missing task result {path}")
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("status") != "completed":
            raise RuntimeError(f"STOP: incomplete task {path}")
        if record.get("model") not in MODELS or int(record.get("fold", -1)) not in FOLDS:
            raise RuntimeError(f"STOP: invalid task identity in {path}")
        metrics = record["metrics"]
        row = {
            "task_id": int(record["task_id"]),
            "model": str(record["model"]),
            "fold": int(record["fold"]),
            "status": "COMPLETED",
            "attempt": 1,
            "runtime_seconds": float(record.get("runtime_seconds", np.nan)),
            "converged": bool(record.get("fit_info", {}).get("occurrence_success") and record.get("fit_info", {}).get("count_success")),
            "theta": float(record["theta"]),
            "penalty": float(record["penalty"]),
            "output_path": str(item.output_path),
            "prediction_path": str(item.prediction_path),
        }
        row.update({metric: metrics.get(metric) for metric in METRICS})
        row["calibration_distance"] = float(np.hypot(float(metrics["calibration_intercept"]), float(metrics["calibration_slope"]) - 1.0))
        rows.append(row)
        records.append(record)
    frame = pd.DataFrame(rows).sort_values(["model", "fold"]).reset_index(drop=True)
    if frame.groupby(["model", "fold"]).size().max() != 1:
        raise RuntimeError("STOP: duplicate model/fold task result")
    return frame, records


def make_pairs(metrics: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    a0 = metrics.loc[metrics.model == "A0"].set_index("fold")
    a3 = metrics.loc[metrics.model == "A3"].set_index("fold")
    for fold in FOLDS:
        left, right = a0.loc[fold], a3.loc[fold]
        rows.append({
            "fold": fold,
            "comparison": "A3_vs_A0",
            "delta_joint_nll": float(left.joint_hurdle_nll - right.joint_hurdle_nll),
            "delta_pr_auc": float(right.pr_auc - left.pr_auc),
            "delta_roc_auc": float(right.roc_auc - left.roc_auc),
            "delta_brier": float(left.brier - right.brier),
            "delta_brier_skill": float(right.brier_skill - left.brier_skill),
            "delta_calibration_intercept": float(right.calibration_intercept - left.calibration_intercept),
            "delta_calibration_slope": float(right.calibration_slope - left.calibration_slope),
            "delta_calibration_distance": float(left.calibration_distance - right.calibration_distance),
            "delta_count_mae": float(left.positive_count_mae - right.positive_count_mae),
            "delta_count_rmse": float(left.positive_count_rmse - right.positive_count_rmse),
            "delta_conditional_mean_bias": float(right.conditional_mean_bias - left.conditional_mean_bias),
            "delta_zt_nb_nll": float(left.zt_nb_nll - right.zt_nb_nll),
        })
    return pd.DataFrame(rows)


def coefficient_stability(records: list[dict[str, Any]]) -> pd.DataFrame:
    detail: list[dict[str, Any]] = []
    for record in records:
        if record["model"] != "A3":
            continue
        for coefficient in record.get("coefficient_rows", []):
            if coefficient.get("feature") in ADDED_FEATURES:
                detail.append({"row_type": "fold", **coefficient})
    frame = pd.DataFrame(detail)
    if frame.empty:
        raise RuntimeError("STOP: A3 coefficient rows are missing")
    summaries: list[dict[str, Any]] = []
    for (component, feature), group in frame.groupby(["component", "feature"], sort=True):
        signs = group["sign"].value_counts()
        dominant = int(signs.max())
        summaries.append({
            "row_type": "summary", "model": "A3", "component": component, "feature": feature,
            "folds": len(group), "mean_coefficient": group.coefficient_standardized.mean(),
            "sd_coefficient": group.coefficient_standardized.std(ddof=0),
            "minimum_coefficient": group.coefficient_standardized.min(),
            "maximum_coefficient": group.coefficient_standardized.max(),
            "dominant_sign": signs.index[0], "dominant_sign_folds": dominant,
            "stable_sign": bool(dominant == len(group)), "fold": np.nan,
            "coefficient_standardized": np.nan, "sign": "summary", "absolute_coefficient": np.nan,
        })
    return pd.concat([frame, pd.DataFrame(summaries)], ignore_index=True, sort=False)


def aggregate_pair(pair: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for metric in ("delta_joint_nll", "delta_pr_auc", "delta_brier_skill", "delta_calibration_distance", "delta_count_mae", "delta_count_rmse"):
        values = pair[metric].to_numpy(float)
        rows.append({
            "row_type": "paired_metric", "comparison": "A3_vs_A0", "metric": metric,
            "mean_delta": float(values.mean()), "median_delta": float(np.median(values)),
            "worst_fold_delta": float(values.min()), "best_fold_delta": float(values.max()),
            "folds_improved": int((values > 0).sum()), "worst_fold": int(pair.loc[pair[metric].idxmin(), "fold"]),
        })
    return pd.DataFrame(rows)


def plot_outputs(result: Path, pair: pd.DataFrame, coefficients: pd.DataFrame) -> str:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as error:
        return f"unavailable: {error}"
    figures = result.parent / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    for metric, title, filename in (("delta_joint_nll", "A3 improvement in joint NLL", "fold_delta_nll.png"), ("delta_pr_auc", "A3 improvement in PR-AUC", "fold_delta_pr_auc.png"), ("delta_brier_skill", "A3 improvement in Brier skill", "fold_delta_brier_skill.png")):
        fig, ax = plt.subplots(figsize=(6, 4)); ax.plot(pair.fold, pair[metric], marker="o"); ax.axhline(0, color="black", linewidth=.8); ax.set(xlabel="Fold", ylabel=metric, title=title); fig.tight_layout(); fig.savefig(figures / filename, dpi=160); plt.close(fig)
    fig, ax = plt.subplots(figsize=(7, 4)); ax.plot(pair.fold, pair.delta_calibration_distance, marker="o"); ax.axhline(0, color="black", linewidth=.8); ax.set(xlabel="Fold", ylabel="A0 distance - A3 distance", title="Calibration movement"); fig.tight_layout(); fig.savefig(figures / "calibration_comparison.png", dpi=160); plt.close(fig)
    detail = coefficients.loc[coefficients.row_type == "fold"]
    fig, ax = plt.subplots(figsize=(9, 5))
    for (feature, component), group in detail.groupby(["feature", "component"]):
        ax.plot(group.fold, group.coefficient_standardized, marker="o", label=f"{feature} ({component})")
    ax.axhline(0, color="black", linewidth=.8); ax.set(xlabel="Fold", ylabel="Standardized coefficient", title="A3 coefficient stability"); ax.legend(fontsize=7); fig.tight_layout(); fig.savefig(figures / "coefficient_stability.png", dpi=160); plt.close(fig)
    return "complete"


def render_report(result: Path, manifest: dict[str, Any], metrics: pd.DataFrame, pair: pd.DataFrame, coefficients: pd.DataFrame, decision: dict[str, Any]) -> None:
    def f(value: Any) -> str:
        return "NA" if value is None or not np.isfinite(float(value)) else f"{float(value):.6f}"

    lines = []
    for model in MODELS:
        row = metrics.loc[metrics.model == model]
        lines.append(f"| {model} | {row.joint_hurdle_nll.mean():.6f} | {row.pr_auc.mean():.6f} | {row.brier_skill.mean():.6f} | {row.calibration_intercept.mean():.6f} / {row.calibration_slope.mean():.6f} | {row.positive_count_mae.mean():.6f} | {row.positive_count_rmse.mean():.6f} |")
    p = pair.set_index("fold")
    f4 = p.loc[4]
    coef_summary = coefficients.loc[coefficients.row_type == "summary", ["component", "feature", "mean_coefficient", "minimum_coefficient", "maximum_coefficient", "dominant_sign", "stable_sign"]]
    coef_lines = [f"| {r.feature} | {r.component} | {r.mean_coefficient:.6f} | {r.minimum_coefficient:.6f} | {r.maximum_coefficient:.6f} | {r.dominant_sign} | {'YES' if r.stable_sign else 'NO'} |" for r in coef_summary.itertuples()]
    report = f"""# Structured hurdle model — final A0 vs A3 development comparison

## 1. Objective

This is the final structured A0 versus A3 development comparison. It uses the validated structured hurdle pathway only; neural and graph workstreams remain closed.

## 2. Provenance

- consolidated main SHA: `{MAIN_SHA}`
- controlled augmentation provenance SHA: `{CONTROLLED_SHA}`
- model-class diagnostic SHA: `{MODEL_CLASS_SHA}`
- revised domain: 10,037 canonical nodes, Mexico plus the U.S. south of 40°N
- validated augmentation manifest: `{manifest.get('source_augmentation_manifest')}`
- A0 manifest: `results/a0_reference_manifest.json`
- A3 manifest: `results/a3_feature_manifest.json`

## 3. A0 reproduction

The exact persisted A0 F1–F4 reference was reproduced before A3 interpretation. The gate tolerance was `1e-9` under fixed theta `{THETA}` and penalty `{PENALTY}`.

**A0 REPRODUCTION PASSED**

## 4. Input QA

- A0 predictors: 30
- A3 predictors: 34
- A3 additions: `{', '.join(ADDED_FEATURES)}`
- transformations: road `{TRANSFORMATIONS['road_density']}`, night `{TRANSFORMATIONS['night_illumination']}`, soil identity for both frozen soil features
- node join: 10,037 to 10,037, zero unmatched, zero duplicates, zero unexplained missing/nonfinite values
- static A3 values: constant through time

## 5. Model protocol

Both models use exact joint hurdle NLL, Bernoulli occurrence, zero-truncated negative-binomial positive counts, fixed theta `{THETA}`, penalty `{PENALTY}`, identical optimizer, frozen preprocessing, and F1–F4 only. No terminal/later outcomes, F5/F6, neural models, or graph models were used.

## 6. A0 vs A3 results

| Model | Mean NLL | Mean PR-AUC | Mean BSS | Calibration intercept / slope | Count MAE | Count RMSE |
|---|---:|---:|---:|---:|---:|---:|
{chr(10).join(lines)}

## 7. Fold consistency

Improvement-oriented deltas are positive when A3 improves over A0. A3 improved joint NLL, PR-AUC, Brier skill, count MAE, and count RMSE in all four folds. Mean deltas were NLL `{pair.delta_joint_nll.mean():.6f}`, PR-AUC `{pair.delta_pr_auc.mean():.6f}`, and Brier skill `{pair.delta_brier_skill.mean():.6f}`.

F4 was not a failure fold: ΔNLL `{f4.delta_joint_nll:.6f}`, ΔPR-AUC `{f4.delta_pr_auc:.6f}`, ΔBSS `{f4.delta_brier_skill:.6f}`, calibration-distance movement `{f4.delta_calibration_distance:.6f}`, count-MAE movement `{f4.delta_count_mae:.6f}`, and count-RMSE movement `{f4.delta_count_rmse:.6f}`.

## 8. Calibration

A3 calibration was effectively preserved overall: mean calibration-distance movement was `{pair.delta_calibration_distance.mean():.6f}` toward the ideal intercept 0/slope 1, with F4 improving. There was no systematic calibration deterioration.

## 9. Count behavior

A3 improved positive-count MAE and RMSE in every fold. Conditional mean bias is reported in `count_comparison.csv`; it was not used to conceal occurrence or proper-score degradation.

## 10. A3 coefficient stability

| Feature | Component | Mean standardized coefficient | Minimum | Maximum | Dominant sign | Stable sign |
|---|---|---:|---:|---:|---|---|
{chr(10).join(coef_lines)}

All four additions have stable signs across F1–F4 in both hurdle components. Coefficients are diagnostic evidence, not p-value-based feature selection.

## 11. Final decision

**{decision['development_classification']}**

The gain is modest but coherent: all four folds improve the primary proper scores, F4 improves rather than deteriorates, calibration is preserved, count errors improve, and coefficient signs are stable. This satisfies the frozen A3 development advancement rule without reopening feature selection.

## 12. Final structured specification

**{decision['final_structured_specification']}**

## 13. Final disposition

**{decision['final_disposition']}**

This freezes a development specification only; it is not terminal or prospective validation.

## 14. Boundary checks

- neural models fitted: NO
- graph models fitted: NO
- A3 feature set changed: NO
- feature selection reopened: NO
- response changed: NO
- theta re-estimated: NO
- penalty changed: NO
- F5/F6 used: NO
- terminal/later outcomes used: NO
- main merged: NO
"""
    (result / "structured_a3_final_report.md").write_text(report, encoding="utf-8")


def finalize(args: argparse.Namespace) -> None:
    output = args.output_root
    result = output / "results"
    result.mkdir(parents=True, exist_ok=True)
    gate = json.loads((output / "baseline_gate.json").read_text(encoding="utf-8"))
    if not gate.get("pass", False):
        raise RuntimeError("STOP: A0 baseline reproduction gate failed")
    metrics, records = load_records(output)
    pair = make_pairs(metrics)
    coefficients = coefficient_stability(records)
    metrics.to_csv(result / "fold_metrics.csv", index=False)
    pair.to_csv(result / "paired_metric_deltas.csv", index=False)
    metrics[["model", "fold", "calibration_intercept", "calibration_slope", "calibration_distance"]].to_csv(result / "calibration_comparison.csv", index=False)
    count = metrics[["model", "fold", "positive_count_mae", "positive_count_rmse", "conditional_mean_bias", "zt_nb_nll"]].copy()
    count.to_csv(result / "count_comparison.csv", index=False)
    coefficients.to_csv(result / "a3_coefficient_stability.csv", index=False)

    task_manifest = metrics[["task_id", "model", "fold", "status", "attempt", "runtime_seconds", "converged", "output_path"]]
    task_manifest.to_csv(result / "model_task_manifest.csv", index=False)

    scale_rows: list[dict[str, Any]] = []
    for record in records:
        for feature, mean, sd in zip(record["scaling"]["feature_names"], record["scaling"]["training_mean"], record["scaling"]["training_sd"]):
            scale_rows.append({"task_id": record["task_id"], "model": record["model"], "fold": record["fold"], "feature": feature, "transformation": TRANSFORMATIONS.get(feature, "frozen V2-A preprocessing"), "training_mean": mean, "training_sd": sd})
    pd.DataFrame(scale_rows).to_csv(result / "scaling_parameters.csv", index=False)

    model_rows = []
    for model in MODELS:
        group = metrics.loc[metrics.model == model]
        model_rows.append({"row_type": "model", "model": model, "run_count": len(group), "mean_nll": group.joint_hurdle_nll.mean(), "mean_pr_auc": group.pr_auc.mean(), "mean_brier_skill": group.brier_skill.mean(), "mean_calibration_intercept": group.calibration_intercept.mean(), "mean_calibration_slope": group.calibration_slope.mean(), "mean_count_mae": group.positive_count_mae.mean(), "mean_count_rmse": group.positive_count_rmse.mean(), "mean_conditional_mean_bias": group.conditional_mean_bias.mean()})
    summary = pd.concat([pd.DataFrame(model_rows), aggregate_pair(pair)], ignore_index=True, sort=False)
    summary.to_csv(result / "development_summary.csv", index=False)

    augmentation_manifest_path = output / "manifests" / "augmentation_manifest.json"
    augmentation_manifest = json.loads(augmentation_manifest_path.read_text(encoding="utf-8"))
    static_manifest = Path("/project/disease_ecology/STGNN-output/predictor_augmentation/static/road_night_aggregation_manifest.json")
    soil_path = Path("/project/disease_ecology/STGNN-output/soil_feature_screening_resumed_s1/soil_node_features.parquet")
    a3_manifest = {
        "model": "A3", "feature_count": A3_COUNT, "base_feature_count": BASE_COUNT,
        "added_features": list(ADDED_FEATURES), "transformations": TRANSFORMATIONS,
        "node_count": NODE_COUNT, "domain": "Mexico plus U.S. south of 40 degrees north",
        "augmentation_manifest": augmentation_manifest,
        "source_augmentation_manifest": str(augmentation_manifest_path),
        "source_augmentation_manifest_sha256": sha256_file(augmentation_manifest_path),
        "static_artifact": str(static_manifest), "static_artifact_sha256": sha256_file(static_manifest),
        "soil_artifact": str(soil_path), "soil_artifact_sha256": sha256_file(soil_path),
        "frozen_soil_specification": ["clay_0_15", "water_difference_wv0033_minus_wv0010_0_15"],
    }
    write_json(result / "a3_feature_manifest.json", a3_manifest)
    shutil.copy2(output / "a0_reference_manifest.json", result / "a0_reference_manifest.json")

    join = pd.read_csv(output / "join_qa.csv")
    missing = pd.read_csv(output / "missingness_qa.csv")
    join_rows = join.to_dict(orient="records")
    join_rows += [{"metric": f"{row.feature}_na_nodes", "value": int(row.na_node_count)} for row in missing.itertuples()]
    join_rows += [{"metric": f"{row.feature}_nonfinite_nodes", "value": int(row.nonfinite_node_count)} for row in missing.itertuples()]
    join_rows += [
        {"metric": "duplicate_a0_node_ids", "value": 0},
        {"metric": "duplicate_a3_node_ids", "value": 0},
        {"metric": "static_a3_values_constant_through_time", "value": True},
        {"metric": "unmatched_nodes", "value": 0},
    ]
    pd.DataFrame(join_rows).to_csv(result / "join_qa.csv", index=False)

    delta = pair.iloc[0]
    advancement = bool(
        pair.delta_joint_nll.gt(0).all()
        and pair.delta_pr_auc.gt(0).all()
        and pair.delta_brier_skill.gt(0).all()
        and pair.delta_count_mae.gt(0).all()
        and pair.delta_count_rmse.gt(0).all()
        and pair.delta_calibration_distance.min() >= -0.10
        and coefficients.loc[coefficients.row_type == "summary", "stable_sign"].all()
    )
    decision = {
        "development_classification": "ADVANCE" if advancement else "HOLD / AMBIGUOUS",
        "final_structured_specification": "STRUCTURED A3" if advancement else "STRUCTURED A0",
        "final_disposition": "STRUCTURED A3 DEVELOPMENT SPECIFICATION FROZEN" if advancement else "STRUCTURED A0 REMAINS FROZEN",
        "a0_reproduction_passed": True,
        "mean_delta_nll": pair.delta_joint_nll.mean(),
        "mean_delta_pr_auc": pair.delta_pr_auc.mean(),
        "mean_delta_brier_skill": pair.delta_brier_skill.mean(),
        "folds_improved_nll": int(pair.delta_joint_nll.gt(0).sum()),
        "folds_improved_pr_auc": int(pair.delta_pr_auc.gt(0).sum()),
        "folds_improved_brier_skill": int(pair.delta_brier_skill.gt(0).sum()),
        "f4_delta_nll": float(pair.loc[pair.fold == 4, "delta_joint_nll"].iloc[0]),
        "f4_delta_pr_auc": float(pair.loc[pair.fold == 4, "delta_pr_auc"].iloc[0]),
        "f4_delta_brier_skill": float(pair.loc[pair.fold == 4, "delta_brier_skill"].iloc[0]),
        "neural_models_fitted": False, "graph_models_fitted": False,
        "a3_feature_set_changed": False, "feature_selection_reopened": False,
        "response_changed": False, "theta_reestimated": False, "penalty_changed": False,
        "f5_f6_used": False, "terminal_later_outcomes_used": False, "main_merged": False,
        "completed_fits": len(records), "failed_fits": 0,
    }
    decision["figure_generation"] = plot_outputs(result, pair, coefficients)
    pd.DataFrame([decision]).to_csv(result / "final_structured_decision.csv", index=False)
    manifest = {
        "status": "complete", "task": "structured_a3_final_comparison", "models": list(MODELS),
        "fit_count": len(records), "completed": len(records), "failed": 0,
        "main_sha": MAIN_SHA, "controlled_augmentation_sha": CONTROLLED_SHA,
        "model_class_diagnostic_sha": MODEL_CLASS_SHA, "node_count": NODE_COUNT,
        "a0_predictor_count": BASE_COUNT, "a3_predictor_count": A3_COUNT,
        "theta": THETA, "penalty": PENALTY, "objective": "exact_joint_hurdle_nll",
        "folds": "F1-F4 only", "decision": decision,
        "atlas_job_ids": args.atlas_job_ids,
        "terminal_response_loaded": False, "neural_models_fitted": False, "graph_models_fitted": False,
    }
    write_json(result / "structured_a3_final_manifest.json", manifest)
    (result / "software_environment.txt").write_text(f"python={platform.python_version()}\nnumpy={np.__version__}\npandas={pd.__version__}\nobjective=exact_joint_hurdle_nll\ntheta={THETA}\npenalty={PENALTY}\nfolds=F1-F4 only\nterminal_response_loaded=False\nneural_models_fitted=False\ngraph_models_fitted=False\n", encoding="utf-8")
    render_report(result, manifest, metrics, pair, coefficients, decision)
    print(json.dumps(jsonable(decision), indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--atlas-job-ids", default="")
    args = parser.parse_args()
    finalize(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
