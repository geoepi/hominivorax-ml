#!/usr/bin/env python3
"""Diagnostic-only analysis of the frozen Structured A3 prospective archive.

This module deliberately contains no A3 fitting, parameter updates, feature
selection, recalibration, or imported optimizer.  The only fitted quantities
are the two-parameter logistic calibration summaries required by the existing
project metric convention, and ordinary descriptive linear trend summaries.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from scipy.special import expit, gammaln
from scipy.stats import linregress, t as student_t
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score


EXPECTED_WEEKS = [f"2026-W{week:02d}" for week in range(30, 40)]
LATITUDE_BANDS = [
    ("<20N", -np.inf, 20.0),
    ("20-25N", 20.0, 25.0),
    ("25-30N", 25.0, 30.0),
    ("30-35N", 30.0, 35.0),
    ("35-40N", 35.0, 40.0),
]
FRONT_DISTANCE_BINS = [
    ("unavailable", None, None),
    ("0-25 km", 0.0, 25.0),
    ("25-50 km", 25.0, 50.0),
    ("50-100 km", 50.0, 100.0),
    ("100-250 km", 100.0, 250.0),
    ("250-500 km", 250.0, 500.0),
    (">500 km", 500.0, np.inf),
]
RECENCY_BINS = [
    ("unavailable", None, None),
    ("0-2 weeks", 0.0, 2.0),
    ("2-4 weeks", 2.0, 4.0),
    ("4-8 weeks", 4.0, 8.0),
    ("8-16 weeks", 8.0, 16.0),
    (">16 weeks", 16.0, np.inf),
]
TOP_K = (0.01, 0.05, 0.10, 0.20)
CALIBRATION_BINS = 10
TRAINING_PREVALENCE = None
EPS = 1e-8

# Pre-registered before looking at the diagnostic outcomes.
RELATIVE_SIMILAR_THRESHOLD = 0.10
ABSOLUTE_SIMILAR_THRESHOLDS = {
    "prevalence": 0.01,
    "brier": 0.005,
    "brier_skill": 0.05,
    "pr_auc": 0.05,
    "roc_auc": 0.05,
    "joint_hurdle_nll": 0.10,
    "calibration_intercept": 0.10,
    "calibration_slope": 0.10,
    "observed_detections": 100.0,
    "predicted_detections": 100.0,
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, float_format="%.15g")


def clean_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): clean_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_value(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, float):
        return None if not np.isfinite(value) else value
    if pd.isna(value):
        return None
    return value


def git_head(repository_root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-c", "safe.directory=*", "-C", str(repository_root), "rev-parse", "HEAD"],
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def import_authoritative_metrics(repository_root: Path):
    # Import the project evaluator so metric definitions remain identical to
    # the authoritative production report.  This is a scoring helper only.
    sys.path.insert(0, str(repository_root))
    from python.task2c_metrics import evaluate_predictions  # type: ignore

    return evaluate_predictions


def calibration_fit(p: np.ndarray, y: np.ndarray) -> tuple[float | None, float | None, str]:
    p = np.asarray(p, dtype=float)
    y = np.asarray(y, dtype=np.int8)
    n_positive = int(y.sum())
    n_negative = int(y.size - n_positive)
    if n_positive == 0 or n_negative == 0:
        return None, None, "not_estimable_single_class"
    flags: list[str] = []
    if n_positive < 20 or n_negative < 20:
        flags.append("low_support")
    clipped = np.clip(p, EPS, 1.0 - EPS)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        model = LogisticRegression(C=1e6, solver="lbfgs", max_iter=200)
        model.fit(np.log(clipped / (1.0 - clipped)).reshape(-1, 1), y)
    if any(issubclass(w.category, ConvergenceWarning) for w in caught):
        flags.append("convergence_warning")
    if not np.isfinite(model.intercept_[0]) or not np.isfinite(model.coef_[0, 0]):
        return None, None, "nonfinite_fit"
    return float(model.intercept_[0]), float(model.coef_[0, 0]), ";".join(flags) or "estimable"


def reliability_rows(p: np.ndarray, y: np.ndarray, region: str, binning: str) -> list[dict[str, Any]]:
    p = np.asarray(p, dtype=float).reshape(-1)
    y = (np.asarray(y).reshape(-1) > 0).astype(np.int8)
    if p.size == 0:
        return []
    rows: list[dict[str, Any]] = []
    if binning == "equal_frequency":
        order = np.argsort(p, kind="mergesort")
        bins = np.array_split(order, min(CALIBRATION_BINS, p.size))
        for index, indices in enumerate(bins, start=1):
            if indices.size == 0:
                continue
            lower = float(p[indices].min())
            upper = float(p[indices].max())
            mean_predicted = float(p[indices].mean())
            observed = float(y[indices].mean())
            rows.append({
                "row_type": "bin",
                "region": region,
                "binning": binning,
                "bin": index,
                "lower": lower,
                "upper": upper,
                "n": int(indices.size),
                "mean_predicted": mean_predicted,
                "observed_fraction": observed,
                "absolute_calibration_error": abs(mean_predicted - observed),
            })
    elif binning == "equal_width":
        edges = np.linspace(0.0, 1.0, CALIBRATION_BINS + 1)
        for index in range(CALIBRATION_BINS):
            selected = (p >= edges[index]) & ((p <= edges[index + 1]) if index == CALIBRATION_BINS - 1 else (p < edges[index + 1]))
            if not selected.any():
                continue
            mean_predicted = float(p[selected].mean())
            observed = float(y[selected].mean())
            rows.append({
                "row_type": "bin",
                "region": region,
                "binning": binning,
                "bin": index + 1,
                "lower": float(edges[index]),
                "upper": float(edges[index + 1]),
                "n": int(selected.sum()),
                "mean_predicted": mean_predicted,
                "observed_fraction": observed,
                "absolute_calibration_error": abs(mean_predicted - observed),
            })
    return rows


def brier_decomposition(rows: list[dict[str, Any]], prevalence: float) -> tuple[float, float, float, float]:
    if not rows:
        return math.nan, math.nan, prevalence * (1.0 - prevalence), math.nan
    total = sum(row["n"] for row in rows)
    reliability = sum(row["n"] / total * (row["mean_predicted"] - row["observed_fraction"]) ** 2 for row in rows)
    resolution = sum(row["n"] / total * (row["observed_fraction"] - prevalence) ** 2 for row in rows)
    uncertainty = prevalence * (1.0 - prevalence)
    return reliability, resolution, uncertainty, reliability - resolution + uncertainty


def exact_metric_evaluation(frame: pd.DataFrame, training_prevalence: float, theta: float, evaluate_predictions) -> dict[str, Any]:
    counts = frame["observed_count"].to_numpy(np.int64)
    p = frame["p_occurrence"].to_numpy(float)
    conditional = frame["conditional_count_mean"].to_numpy(float)
    mu = frame["underlying_mu"].to_numpy(float)
    metrics = evaluate_predictions(
        counts,
        p,
        conditional,
        mu,
        theta,
        training_prevalence=training_prevalence,
    )
    metrics["positive_node_weeks"] = int((counts > 0).sum())
    metrics["observed_detections"] = int(counts.sum())
    metrics["predicted_detections"] = float(frame["expected_count"].sum())
    return metrics


def safe_subset_metrics(frame: pd.DataFrame, training_prevalence: float, theta: float, evaluate_predictions) -> dict[str, Any]:
    y = frame["observed_count"].to_numpy(np.int64)
    positives = y > 0
    metrics: dict[str, Any] = {
        "n_node_weeks": int(len(frame)),
        "positive_node_weeks": int(positives.sum()),
        "prevalence": float(positives.mean()) if len(frame) else math.nan,
        "mean_predicted_probability": float(frame["p_occurrence"].mean()) if len(frame) else math.nan,
        "observed_detections": int(y.sum()),
        "predicted_detections": float(frame["expected_count"].sum()),
        "pr_auc": math.nan,
        "roc_auc": math.nan,
        "calibration_intercept": math.nan,
        "calibration_slope": math.nan,
        "calibration_flag": "not_estimable",
        "joint_hurdle_nll": math.nan,
        "zt_nb_nll": math.nan,
        "conditional_mean_from_underlying": math.nan,
        "brier": math.nan,
        "brier_skill": math.nan,
        "brier_null": math.nan,
        "mean_observed_count": float(y.mean()) if len(frame) else math.nan,
        "mean_predicted_count": float(frame["expected_count"].mean()) if len(frame) else math.nan,
    }
    if len(frame) == 0:
        return metrics
    p = np.clip(frame["p_occurrence"].to_numpy(float), EPS, 1.0 - EPS)
    if positives.any():
        scored = evaluate_predictions(
            y,
            p,
            frame["conditional_count_mean"].to_numpy(float),
            frame["underlying_mu"].to_numpy(float),
            theta,
            training_prevalence=training_prevalence,
        )
        for key in ["joint_hurdle_nll", "zt_nb_nll", "conditional_mean_from_underlying", "brier", "brier_skill", "brier_null"]:
            metrics[key] = scored[key]
    if len(np.unique(positives)) == 2:
        metrics["pr_auc"] = float(average_precision_score(positives.astype(np.int8), p))
        metrics["roc_auc"] = float(roc_auc_score(positives.astype(np.int8), p))
        intercept, slope, flag = calibration_fit(p, positives)
        metrics["calibration_intercept"] = intercept if intercept is not None else math.nan
        metrics["calibration_slope"] = slope if slope is not None else math.nan
        metrics["calibration_flag"] = flag
    else:
        metrics["pr_auc"] = math.nan
        metrics["calibration_flag"] = "not_estimable_single_class"
    return metrics


def row_from_metrics(base: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    result.update(metrics)
    return {key: clean_value(value) for key, value in result.items()}


def add_tolerance_rows(authoritative: dict[str, Any], recomputed: dict[str, Any]) -> pd.DataFrame:
    fields = [
        ("node_week_count", authoritative["node_weeks"], recomputed["n_node_weeks"], 0.0),
        ("positive_node_weeks", authoritative["positive_node_weeks"], recomputed["positive_node_weeks"], 0.0),
        ("prevalence", authoritative["prevalence"], recomputed["observed_prevalence"], 1e-12),
        ("brier", authoritative["metrics"]["brier"], recomputed["brier"], 1e-12),
        ("brier_skill", authoritative["metrics"]["brier_skill"], recomputed["brier_skill"], 1e-12),
        ("pr_auc", authoritative["metrics"]["pr_auc"], recomputed["pr_auc"], 1e-12),
        ("roc_auc", authoritative["metrics"]["roc_auc"], recomputed["roc_auc"], 1e-12),
        ("zt_nb_nll", authoritative["metrics"]["zt_nb_nll"], recomputed["zt_nb_nll"], 1e-12),
        ("joint_hurdle_nll", authoritative["metrics"]["joint_hurdle_nll"], recomputed["joint_hurdle_nll"], 1e-12),
        ("observed_detections", authoritative["observed_total_detections"], recomputed["observed_detections"], 0.0),
        ("predicted_detections", authoritative["predicted_total_detections"], recomputed["predicted_detections"], 1e-8),
        ("calibration_intercept", authoritative["metrics"]["calibration_intercept"], recomputed["calibration_intercept"], 1e-12),
        ("calibration_slope", authoritative["metrics"]["calibration_slope"], recomputed["calibration_slope"], 1e-12),
    ]
    rows = []
    for metric, expected, observed, tolerance in fields:
        difference = abs(float(expected) - float(observed))
        rows.append({
            "metric": metric,
            "authoritative_value": expected,
            "recomputed_value": observed,
            "absolute_difference": difference,
            "tolerance": tolerance,
            "pass": bool(difference <= tolerance),
        })
    return pd.DataFrame(rows)


def load_inputs(args: argparse.Namespace) -> dict[str, Any]:
    prospective_root = Path(args.prospective_root)
    terminal_root = Path(args.terminal_root)
    refresh_root = Path(args.refresh_root)
    model_root = Path(args.model_root)
    production_config = Path(args.production_config)
    authoritative_report_path = prospective_root / "reports/prospective_evaluation_report.json"
    prediction_path = prospective_root / "predictions/prospective_predictions.parquet"
    status = read_json(prospective_root / "manifests/prospective_status.json")
    preprocessing = read_json(prospective_root / "manifests/preprocessing_manifest.json")
    model_manifest = read_json(model_root / "model/fullfit_a3_manifest.json")
    model = read_json(model_root / "model/fullfit_a3_model.json")
    deploy_manifest = Path(args.deployed_model_manifest)
    report = read_json(authoritative_report_path)
    weeks = list(report["eligible_weeks"])
    if weeks != EXPECTED_WEEKS:
        raise RuntimeError(f"STOP: authoritative evaluation weeks {weeks} do not equal {EXPECTED_WEEKS}")
    if status.get("refit_performed") is not False or report.get("refit_performed") is not False:
        raise RuntimeError("STOP: authoritative prospective archive is not explicitly marked no-refit")
    if report.get("scaling_reestimated") is not False:
        raise RuntimeError("STOP: authoritative prospective archive is not explicitly marked fixed-scaling")
    paths = {
        "prospective_predictions": prediction_path,
        "corrected_prospective_report": authoritative_report_path,
        "frozen_deployed_model": model_root / "model/fullfit_a3_model.json",
        "deployed_model_manifest": deploy_manifest,
        "observation_source": Path(preprocessing["input_paths"]["observation_path"]),
        "refreshed_production_manifest": refresh_root / "revised_model_data/manifests/revised_production_manifest.json",
        "causal_front_feature_artifact": Path(preprocessing["input_paths"]["history_feature_path"]),
        "refresh_node_table": refresh_root / "revised_model_data/raw/nodes.parquet",
        "refresh_edges": refresh_root / "revised_model_data/raw/edges_queen.parquet",
        "refresh_dynamic_features": refresh_root / "revised_model_data/raw/dynamic_features.npy",
        "refresh_static_features": refresh_root / "revised_model_data/raw/static_features.npy",
        "refresh_calendar_features": refresh_root / "revised_model_data/raw/calendar_features.parquet",
        "refresh_weeks": refresh_root / "revised_model_data/raw/weeks.parquet",
        "development_dynamic_features": Path(model_manifest["source_artifacts"]["dynamic_features"]["path"]),
        "development_static_features": Path(model_manifest["source_artifacts"]["static_features"]["path"]),
        "development_weeks": Path(model_manifest["source_artifacts"]["weeks"]["path"]),
        "development_front_features": Path(model_manifest["source_artifacts"]["front_features"]["path"]),
        "road_night_features": Path(model_manifest["source_artifacts"]["anthropogenic_features"]["path"]),
        "soil_features": Path(model_manifest["source_artifacts"]["soil_features"]["path"]),
        "frozen_model_scaling": model_root / "model/fullfit_a3_scaling_parameters.csv",
        "terminal_metrics": terminal_root / "metrics/terminal_metrics.json",
        "terminal_regional_metrics": terminal_root / "regional/terminal_regional_metrics.csv",
    }
    missing = [f"{key}: {path}" for key, path in paths.items() if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing diagnostic inputs:\n" + "\n".join(missing))
    hashes = {key: {"path": str(path), "sha256": sha256_file(path), "size_bytes": path.stat().st_size} for key, path in paths.items()}
    predictions = pd.read_parquet(prediction_path)
    if list(predictions["week"].drop_duplicates()) != EXPECTED_WEEKS:
        raise RuntimeError("STOP: prediction archive week ordering/boundary is not exactly W30-W39")
    if len(predictions) != 100370 or predictions["model_node_id"].nunique() != 10037:
        raise RuntimeError("STOP: prediction archive does not have the expected 100,370 node-weeks and 10,037 nodes")
    if predictions.duplicated(["week", "model_node_id"]).any():
        raise RuntimeError("STOP: duplicate week/node prediction keys")
    return {
        "args": args,
        "prospective_root": prospective_root,
        "terminal_root": terminal_root,
        "refresh_root": refresh_root,
        "model_root": model_root,
        "production_config": production_config,
        "report": report,
        "status": status,
        "preprocessing": preprocessing,
        "model_manifest": model_manifest,
        "model": model,
        "predictions": predictions,
        "paths": paths,
        "hashes": hashes,
        "weeks": weeks,
    }


def make_analysis_manifest(
    data: dict[str, Any],
    repository_root: Path,
    script_path: Path,
    repository_sha_override: str | None = None,
) -> dict[str, Any]:
    model = data["model"]
    render_script = script_path.parent / "render_figures.R"
    script_versions = {
        "run_diagnostics_sha256": sha256_file(script_path),
        "python": sys.version,
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "scikit_learn": __import__("sklearn").__version__,
    }
    if render_script.exists():
        script_versions["render_figures_sha256"] = sha256_file(render_script)
    return {
        "repository_sha": repository_sha_override or git_head(repository_root),
        "input_paths": data["hashes"],
        "evaluation_weeks": data["weeks"],
        "node_count": int(data["preprocessing"]["node_count"]),
        "predictor_count": int(data["preprocessing"]["predictor_count"]),
        "model_id": model["model_id"],
        "frozen_theta": float(model["theta"]),
        "frozen_penalty": float(model["penalty"]),
        "analysis_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "script_versions": script_versions,
        "comparison_thresholds": {
            "relative_similar": RELATIVE_SIMILAR_THRESHOLD,
            "absolute_similar": ABSOLUTE_SIMILAR_THRESHOLDS,
        },
        "no_refit": True,
        "no_recalibration": True,
    }


def terminal_value(row: pd.Series, metric: str) -> float | None:
    mapping = {
        "prevalence": "observed_prevalence",
        "brier": "brier",
        "brier_skill": "brier_skill",
        "pr_auc": "pr_auc",
        "roc_auc": "roc_auc",
        "joint_hurdle_nll": "joint_hurdle_nll",
        "calibration_intercept": "calibration_intercept",
        "calibration_slope": "calibration_slope",
        "observed_detections": "observed_total_detections",
        "predicted_detections": "predicted_expected_total_detections",
    }
    value = row.get(mapping[metric], np.nan)
    return None if pd.isna(value) else float(value)


def comparison_class(metric: str, terminal: float | None, prospective: float | None) -> str:
    if terminal is None or prospective is None or not np.isfinite(terminal) or not np.isfinite(prospective):
        return "NOT_COMPARABLE"
    if metric in {"observed_detections", "predicted_detections"}:
        return "NOT_COMPARABLE"
    change = prospective - terminal
    absolute = abs(change)
    threshold = ABSOLUTE_SIMILAR_THRESHOLDS[metric]
    relative = absolute / max(abs(terminal), EPS)
    if absolute <= threshold or relative <= RELATIVE_SIMILAR_THRESHOLD:
        return "SIMILAR"
    if metric in {"brier", "joint_hurdle_nll"}:
        return "IMPROVED" if change < 0 else "DEGRADED"
    if metric in {"brier_skill", "pr_auc", "roc_auc"}:
        return "IMPROVED" if change > 0 else "DEGRADED"
    if metric in {"calibration_intercept", "calibration_slope"}:
        old_distance = abs(terminal - (0.0 if metric.endswith("intercept") else 1.0))
        new_distance = abs(prospective - (0.0 if metric.endswith("intercept") else 1.0))
        return "IMPROVED" if new_distance < old_distance else "DEGRADED"
    return "IMPROVED" if relative < 0 else "DEGRADED"


def terminal_comparison(data: dict[str, Any], prospective_metrics: dict[str, Any]) -> pd.DataFrame:
    terminal_metrics = read_json(data["paths"]["terminal_metrics"])
    regional = pd.read_csv(data["paths"]["terminal_regional_metrics"])
    prediction_frame = data["predictions"]
    prospective_regions = {
        "full_domain": prediction_frame,
        "Mexico": prediction_frame.loc[prediction_frame["country_or_domain_region"] == "Mexico"],
        "United States": prediction_frame.loc[prediction_frame["country_or_domain_region"] == "U.S.-to-40N"],
    }
    regions = [
        ("full_domain", "full_revised_domain", data["report"]["metrics"]),
        ("Mexico", "Mexico", data["report"]["regional_metrics"]["Mexico"]),
        ("United States", "United States", data["report"]["regional_metrics"]["U.S.-to-40N"]),
    ]
    rows: list[dict[str, Any]] = []
    metric_names = [
        "prevalence", "brier", "brier_skill", "pr_auc", "roc_auc", "joint_hurdle_nll",
        "calibration_intercept", "calibration_slope", "observed_detections", "predicted_detections",
    ]
    for region_label, terminal_region, prospective in regions:
        if terminal_region == "full_revised_domain":
            terminal_row = terminal_metrics["primary_full_domain"]
        else:
            terminal_row = regional.loc[regional["region"] == terminal_region].iloc[0]
        prospective_frame = prospective_regions[region_label]
        for metric in metric_names:
            prospective_key = {
                "prevalence": "observed_prevalence",
                "observed_detections": "observed_detections",
                "predicted_detections": "predicted_detections",
            }.get(metric, metric)
            terminal_value_ = terminal_value(terminal_row, metric)
            if metric == "observed_detections":
                prospective_value = float(prospective_frame["observed_count"].sum())
            elif metric == "predicted_detections":
                prospective_value = float(prospective_frame["expected_count"].sum())
            else:
                prospective_value = prospective.get(prospective_key)
            class_ = comparison_class(metric, terminal_value_, prospective_value)
            rows.append({
                "metric": metric,
                "region": region_label,
                "terminal_value": terminal_value_,
                "prospective_value": prospective_value,
                "absolute_change": None if terminal_value_ is None or prospective_value is None else float(prospective_value - terminal_value_),
                "relative_change": None if terminal_value_ in (None, 0) or prospective_value is None else float((prospective_value - terminal_value_) / abs(terminal_value_)),
                "interpretation_class": class_,
                "comparison_note": (
                    "Raw totals are not comparable because terminal and prospective windows contain different numbers of node-weeks; use count_process_metrics.csv for normalized diagnostics."
                    if metric in {"observed_detections", "predicted_detections"}
                    else "Same target/metric definition; terminal comparator is persisted Hurdle-Current output, not a refit of frozen Structured A3."
                ),
            })
    return pd.DataFrame(rows)


def weekly_diagnostics(data: dict[str, Any], evaluate_predictions) -> tuple[pd.DataFrame, pd.DataFrame]:
    frame = data["predictions"]
    training_prevalence = float(data["report"]["metrics"]["training_prevalence"])
    theta = float(data["model"]["theta"])
    rows = []
    for index, week in enumerate(EXPECTED_WEEKS):
        subset = frame.loc[frame["week"] == week]
        metrics = safe_subset_metrics(subset, training_prevalence, theta, evaluate_predictions)
        rows.append(row_from_metrics({"week": week, "week_index": index + 1}, metrics))
    weekly = pd.DataFrame(rows)
    trend_rows = []
    for metric in ["prevalence", "brier_skill", "pr_auc", "roc_auc", "joint_hurdle_nll", "observed_detections", "predicted_detections"]:
        selected = weekly[["week_index", metric]].dropna()
        if len(selected) < 3:
            trend_rows.append({"metric": metric, "n_weeks": len(selected), "slope_per_week": math.nan, "ci_low": math.nan, "ci_high": math.nan, "p_value": math.nan, "trend_flag": "not_estimable"})
            continue
        fit = linregress(selected["week_index"], selected[metric])
        degrees = max(len(selected) - 2, 1)
        margin = float(student_t.ppf(0.975, degrees) * fit.stderr) if np.isfinite(fit.stderr) else math.nan
        slope = float(fit.slope)
        if not np.isfinite(margin) or abs(slope) < 1e-12:
            trend = "no_clear_monotonic_trend"
        elif fit.pvalue < 0.05:
            trend = "increasing" if slope > 0 else "decreasing"
        else:
            trend = "no_clear_monotonic_trend"
        trend_rows.append({
            "metric": metric,
            "n_weeks": len(selected),
            "slope_per_week": slope,
            "ci_low": slope - margin,
            "ci_high": slope + margin,
            "p_value": float(fit.pvalue),
            "trend_flag": trend,
        })
    return weekly, pd.DataFrame(trend_rows)


def geographic_diagnostics(data: dict[str, Any], evaluate_predictions) -> pd.DataFrame:
    frame = data["predictions"]
    training_prevalence = float(data["report"]["metrics"]["training_prevalence"])
    theta = float(data["model"]["theta"])
    rows = []
    strata = [("domain", "full_domain", np.ones(len(frame), dtype=bool))]
    strata.extend(("country", label, frame["country_or_domain_region"].eq(source).to_numpy()) for label, source in [("Mexico", "Mexico"), ("United States", "U.S.-to-40N")])
    for label, lower, upper in LATITUDE_BANDS:
        strata.append(("latitude", label, (frame["lat"].to_numpy(float) >= lower) & (frame["lat"].to_numpy(float) < upper)))
    for kind, label, mask in strata:
        subset = frame.loc[mask]
        if subset.empty:
            continue
        metrics = safe_subset_metrics(subset, training_prevalence, theta, evaluate_predictions)
        rows.append(row_from_metrics({"stratum_type": kind, "stratum": label}, metrics))
    return pd.DataFrame(rows)


def front_distance_diagnostics(data: dict[str, Any], evaluate_predictions) -> pd.DataFrame:
    frame = data["predictions"]
    front_path = data["paths"]["causal_front_feature_artifact"]
    front = pd.read_parquet(front_path, columns=[
        "week", "model_node_id", "distance_to_any_prior_positive_km", "distance_to_prev4_positive_km",
        "weeks_since_detection_within_50km", "any_prior_positive_available", "prev4_positive_available", "detection_within_50km_ever_available",
    ])
    front = front.loc[front["week"].isin(EXPECTED_WEEKS)].copy()
    joined = frame.merge(front, on=["week", "model_node_id"], how="left", validate="one_to_one")
    if joined[["distance_to_any_prior_positive_km", "distance_to_prev4_positive_km"]].isna().any().any():
        raise RuntimeError("front-feature join failed for prospective week/node keys")
    training_prevalence = float(data["report"]["metrics"]["training_prevalence"])
    theta = float(data["model"]["theta"])
    configs = [
        ("distance_to_any_prior_positive_km", "any_prior_positive_available", FRONT_DISTANCE_BINS),
        ("distance_to_prev4_positive_km", "prev4_positive_available", FRONT_DISTANCE_BINS),
        ("weeks_since_detection_within_50km", "detection_within_50km_ever_available", RECENCY_BINS),
    ]
    rows = []
    for feature, available, bins in configs:
        for label, lower, upper in bins:
            if label == "unavailable":
                mask = joined[available].to_numpy(int) == 0
            else:
                values = joined[feature].to_numpy(float)
                mask = (joined[available].to_numpy(int) == 1) & (values >= lower) & (values < upper)
            subset = joined.loc[mask]
            if subset.empty:
                continue
            metrics = safe_subset_metrics(subset, training_prevalence, theta, evaluate_predictions)
            rows.append(row_from_metrics({"front_feature": feature, "stratum": label}, metrics))
    return pd.DataFrame(rows)


def us_risk_ranking(data: dict[str, Any]) -> pd.DataFrame:
    frame = data["predictions"]
    us = frame.loc[frame["country_or_domain_region"] == "U.S.-to-40N"].copy()
    rows: list[dict[str, Any]] = []
    all_positive_ranks: list[float] = []
    all_positive_nodes: set[int] = set()
    for week in EXPECTED_WEEKS:
        subset = us.loc[us["week"] == week].copy()
        if subset.empty:
            rows.append({
                "row_type": "week_summary", "week": week, "top_k": None,
                "n_us_nodes": 0, "positive_node_weeks": 0, "unique_positive_nodes": 0,
                "median_positive_risk_percentile": math.nan, "mean_positive_risk_percentile": math.nan,
                "positive_percentile_ge_50": math.nan, "positive_percentile_ge_75": math.nan,
                "positive_percentile_ge_90": math.nan, "positive_percentile_ge_95": math.nan,
                "flagged_node_weeks": None, "positives_captured": None, "precision": None, "recall": None,
                "rank_p25": math.nan, "rank_median": math.nan, "rank_p75": math.nan, "rank_p95": math.nan,
            })
            continue
        p = subset["p_occurrence"].to_numpy(float)
        y = (subset["observed_count"].to_numpy(int) > 0)
        percentile = pd.Series(p).rank(method="average", pct=True).to_numpy(float) * 100.0
        positive_ranks = percentile[y]
        all_positive_ranks.extend(positive_ranks.tolist())
        all_positive_nodes.update(subset.loc[y, "model_node_id"].astype(int).tolist())
        rows.append({
            "row_type": "week_summary", "week": week, "top_k": None,
            "n_us_nodes": int(len(subset)), "positive_node_weeks": int(y.sum()),
            "unique_positive_nodes": int(subset.loc[y, "model_node_id"].nunique()),
            "median_positive_risk_percentile": float(np.median(positive_ranks)) if positive_ranks.size else math.nan,
            "mean_positive_risk_percentile": float(np.mean(positive_ranks)) if positive_ranks.size else math.nan,
            "positive_percentile_ge_50": float(np.mean(positive_ranks >= 50.0)) if positive_ranks.size else math.nan,
            "positive_percentile_ge_75": float(np.mean(positive_ranks >= 75.0)) if positive_ranks.size else math.nan,
            "positive_percentile_ge_90": float(np.mean(positive_ranks >= 90.0)) if positive_ranks.size else math.nan,
            "positive_percentile_ge_95": float(np.mean(positive_ranks >= 95.0)) if positive_ranks.size else math.nan,
            "flagged_node_weeks": None, "positives_captured": None, "precision": None, "recall": None,
            "rank_p25": float(np.percentile(percentile, 25)), "rank_median": float(np.percentile(percentile, 50)),
            "rank_p75": float(np.percentile(percentile, 75)), "rank_p95": float(np.percentile(percentile, 95)),
        })
        for k in TOP_K:
            n_flagged = max(1, int(math.ceil(k * len(subset))))
            selected = np.argsort(-p, kind="mergesort")[:n_flagged]
            captured = int(y[selected].sum())
            rows.append({
                "row_type": "top_k", "week": week, "top_k": k,
                "n_us_nodes": int(len(subset)), "positive_node_weeks": int(y.sum()), "unique_positive_nodes": None,
                "median_positive_risk_percentile": None, "mean_positive_risk_percentile": None,
                "positive_percentile_ge_50": None, "positive_percentile_ge_75": None,
                "positive_percentile_ge_90": None, "positive_percentile_ge_95": None,
                "flagged_node_weeks": n_flagged, "positives_captured": captured,
                "precision": captured / n_flagged, "recall": captured / max(int(y.sum()), 1),
                "rank_p25": None, "rank_median": None, "rank_p75": None, "rank_p95": None,
            })
        for node_index in np.flatnonzero(y):
            rows.append({
                "row_type": "positive_case", "week": week, "top_k": None,
                "n_us_nodes": int(len(subset)), "positive_node_weeks": None, "unique_positive_nodes": None,
                "median_positive_risk_percentile": float(percentile[node_index]),
                "mean_positive_risk_percentile": None, "positive_percentile_ge_50": None,
                "positive_percentile_ge_75": None, "positive_percentile_ge_90": None,
                "positive_percentile_ge_95": None, "flagged_node_weeks": None,
                "positives_captured": None, "precision": None, "recall": None,
                "rank_p25": None, "rank_median": None, "rank_p75": None, "rank_p95": None,
                "model_node_id": int(subset.iloc[node_index]["model_node_id"]),
                "predicted_probability": float(p[node_index]),
                "observed_count": int(subset.iloc[node_index]["observed_count"]),
            })
    total_positive = int((us["observed_count"] > 0).sum())
    summary_ranks = np.asarray(all_positive_ranks, dtype=float)
    rows.append({
        "row_type": "overall_positive_summary", "week": "ALL", "top_k": None,
        "n_us_nodes": int(us["model_node_id"].nunique()), "positive_node_weeks": total_positive,
        "unique_positive_nodes": len(all_positive_nodes),
        "median_positive_risk_percentile": float(np.median(summary_ranks)) if summary_ranks.size else math.nan,
        "mean_positive_risk_percentile": float(np.mean(summary_ranks)) if summary_ranks.size else math.nan,
        "positive_percentile_ge_50": float(np.mean(summary_ranks >= 50.0)) if summary_ranks.size else math.nan,
        "positive_percentile_ge_75": float(np.mean(summary_ranks >= 75.0)) if summary_ranks.size else math.nan,
        "positive_percentile_ge_90": float(np.mean(summary_ranks >= 90.0)) if summary_ranks.size else math.nan,
        "positive_percentile_ge_95": float(np.mean(summary_ranks >= 95.0)) if summary_ranks.size else math.nan,
        "flagged_node_weeks": None, "positives_captured": None, "precision": None, "recall": None,
        "rank_p25": None, "rank_median": None, "rank_p75": None, "rank_p95": None,
    })
    for k in TOP_K:
        flags = []
        for week in EXPECTED_WEEKS:
            subset = us.loc[us["week"] == week]
            if subset.empty:
                continue
            p = subset["p_occurrence"].to_numpy(float)
            y = (subset["observed_count"].to_numpy(int) > 0)
            n_flagged = max(1, int(math.ceil(k * len(subset))))
            flags.extend((subset.iloc[np.argsort(-p, kind="mergesort")[:n_flagged]]["observed_count"].to_numpy(int) > 0).tolist())
        captured = int(sum(flags))
        rows.append({
            "row_type": "overall_top_k", "week": "ALL", "top_k": k,
            "n_us_nodes": int(us["model_node_id"].nunique()), "positive_node_weeks": total_positive, "unique_positive_nodes": None,
            "median_positive_risk_percentile": None, "mean_positive_risk_percentile": None,
            "positive_percentile_ge_50": None, "positive_percentile_ge_75": None,
            "positive_percentile_ge_90": None, "positive_percentile_ge_95": None,
            "flagged_node_weeks": len(flags), "positives_captured": captured,
            "precision": captured / max(len(flags), 1), "recall": captured / max(total_positive, 1),
            "rank_p25": None, "rank_median": None, "rank_p75": None, "rank_p95": None,
        })
    return pd.DataFrame(rows)


def count_process_diagnostics(data: dict[str, Any], evaluate_predictions) -> pd.DataFrame:
    frame = data["predictions"]
    training_prevalence = float(data["report"]["metrics"]["training_prevalence"])
    theta = float(data["model"]["theta"])
    strata: list[tuple[str, str, pd.Series]] = [("domain", "full_domain", pd.Series(True, index=frame.index))]
    strata.extend(("country", label, frame["country_or_domain_region"].eq(source)) for label, source in [("Mexico", "Mexico"), ("United States", "U.S.-to-40N")])
    for label, lower, upper in LATITUDE_BANDS:
        strata.append(("latitude", label, (frame["lat"] >= lower) & (frame["lat"] < upper)))
    strata.extend(("week", week, frame["week"].eq(week)) for week in EXPECTED_WEEKS)
    rows = []
    for kind, label, mask in strata:
        subset = frame.loc[mask & frame["observed_count"].gt(0)].copy()
        if subset.empty:
            rows.append({"stratum_type": kind, "stratum": label, "positive_node_weeks": 0, "status": "not_estimable_no_positive_rows"})
            continue
        y = subset["observed_count"].to_numpy(float)
        cond = subset["conditional_count_mean"].to_numpy(float)
        metrics = safe_subset_metrics(frame.loc[mask], training_prevalence, theta, evaluate_predictions)
        metrics.update({
            "observed_median_count": float(np.median(y)),
            "predicted_median_conditional_mean": float(np.median(cond)),
            "positive_mae": float(np.mean(np.abs(y - cond))),
            "positive_rmse": float(np.sqrt(np.mean((y - cond) ** 2))),
            "mean_absolute_log_error": float(np.mean(np.abs(np.log1p(y) - np.log1p(cond)))),
            "status": "estimable",
        })
        rows.append(row_from_metrics({"stratum_type": kind, "stratum": label}, metrics))
    return pd.DataFrame(rows)


def build_feature_matrix(data: dict[str, Any], split: str) -> tuple[np.ndarray, list[str], list[str], pd.DataFrame]:
    model_manifest = data["model_manifest"]
    model = data["model"]
    names = list(model["predictor_order"])
    if split == "development":
        dyn_path = data["paths"]["development_dynamic_features"]
        static_path = data["paths"]["development_static_features"]
        weeks_path = data["paths"]["development_weeks"]
        front_path = data["paths"]["development_front_features"]
    else:
        dyn_path = data["paths"]["refresh_dynamic_features"]
        static_path = data["paths"]["refresh_static_features"]
        weeks_path = data["paths"]["refresh_weeks"]
        front_path = data["paths"]["causal_front_feature_artifact"]
    dynamic = np.load(dyn_path, mmap_mode="r").astype(np.float64)
    static = np.load(static_path, mmap_mode="r").astype(np.float64)
    weeks_frame = pd.read_parquet(weeks_path)
    weeks = weeks_frame["iso_week"].astype(str).tolist()
    n_weeks, n_nodes, _ = dynamic.shape
    if static.shape != (n_nodes, 10):
        raise RuntimeError(f"unexpected static feature shape {static.shape}")
    calendar = pd.read_parquet(data["paths"]["refresh_calendar_features"])[["iso_week", "week_sin", "week_cos"]]
    calendar_map = calendar.set_index("iso_week")
    road = pd.read_parquet(data["paths"]["road_night_features"])[["model_node_id", "road_density", "night_illumination"]].sort_values("model_node_id")
    soil = pd.read_parquet(data["paths"]["soil_features"])[["model_node_id", "clay_0_15__mean", "water_difference_wv0033_minus_wv0010_0_15__mean"]].sort_values("model_node_id")
    if not np.array_equal(road["model_node_id"].to_numpy(), np.arange(n_nodes)) or not np.array_equal(soil["model_node_id"].to_numpy(), np.arange(n_nodes)):
        raise RuntimeError("static predictor node order does not match model_node_id order")
    road_values = np.column_stack([np.log1p(road["road_density"].to_numpy(float)), np.log1p(road["night_illumination"].to_numpy(float))])
    soil_values = soil[["clay_0_15__mean", "water_difference_wv0033_minus_wv0010_0_15__mean"]].to_numpy(float)
    front = pd.read_parquet(front_path, columns=[
        "week", "model_node_id", "distance_to_any_prior_positive_log1p", "distance_to_prev4_positive_log1p",
        "weeks_since_detection_within_50km_log1p", "any_prior_positive_available", "prev4_positive_available", "detection_within_50km_ever_available",
    ])
    front = front.loc[front["week"].isin(weeks)].copy()
    front = front.sort_values(["week", "model_node_id"])
    if len(front) != n_weeks * n_nodes or front.duplicated(["week", "model_node_id"]).any():
        raise RuntimeError(f"front feature matrix shape mismatch for {split}: {front.shape}")
    front_values = front[[
        "distance_to_any_prior_positive_log1p", "distance_to_prev4_positive_log1p", "weeks_since_detection_within_50km_log1p",
        "any_prior_positive_available", "prev4_positive_available", "detection_within_50km_ever_available",
    ]].to_numpy(float).reshape(n_weeks, n_nodes, 6)
    calendar_values = np.asarray([[calendar_map.loc[week, "week_sin"], calendar_map.loc[week, "week_cos"]] for week in weeks], dtype=float)
    calendar_values = np.broadcast_to(calendar_values[:, None, :], (n_weeks, n_nodes, 2))
    static_full = np.broadcast_to(static[None, :, :], (n_weeks, n_nodes, 10))
    road_full = np.broadcast_to(road_values[None, :, :], (n_weeks, n_nodes, 2))
    soil_full = np.broadcast_to(soil_values[None, :, :], (n_weeks, n_nodes, 2))
    values = np.concatenate([dynamic, static_full, calendar_values, front_values, road_full, soil_full], axis=2)
    produced = [
        "era5_mintemp", "era5_soilmoist", "era5_lai_low", "agera5_relhum_min", "era5land_tmean",
        "era5land_soiltemp_l1_mean", "era5land_soiltemp_l2_mean", "era5land_soilwater_l1_mean", "era5land_soilwater_l2_mean",
        "era5land_surface_pressure_mean", "era5land_lai_high_mean", "era5land_lai_low_mean",
        "cattle_density", "goat_density", "sheep_density", "horse_density", "pig_density",
        "cattle_density_imputed", "goat_density_imputed", "sheep_density_imputed", "horse_density_imputed", "pig_density_imputed",
        "week_sin", "week_cos", "distance_to_any_prior_positive_log1p", "distance_to_prev4_positive_log1p",
        "weeks_since_detection_within_50km_log1p", "any_prior_positive_available", "prev4_positive_available", "detection_within_50km_ever_available",
        "road_density", "night_illumination", "clay_0_15", "water_difference_wv0033_minus_wv0010_0_15",
    ]
    if produced != names:
        raise RuntimeError("reconstructed predictor order differs from the frozen model predictor order")
    return values.reshape(-1, values.shape[-1]), names, weeks, front


def covariate_shift_diagnostics(data: dict[str, Any], evaluate_predictions) -> pd.DataFrame:
    development, names, _, _ = build_feature_matrix(data, "development")
    current, current_names, current_weeks, _ = build_feature_matrix(data, "prospective")
    selected = np.asarray([week in EXPECTED_WEEKS for week in current_weeks], dtype=bool)
    prospective = current.reshape(len(current_weeks), 10037, -1)[selected].reshape(-1, current.shape[-1])
    if names != current_names or len(prospective) != len(data["predictions"]):
        raise RuntimeError("prospective covariate matrix does not align with prediction archive")
    model_scaling = pd.read_csv(data["paths"]["frozen_model_scaling"])
    scaling = model_scaling.set_index("predictor").reindex(names)
    frame = data["predictions"]
    rows = []
    for index, feature in enumerate(names):
        train = development[:, index]
        prospect = prospective[:, index]
        mean = float(scaling.iloc[index]["training_mean"])
        sd = float(scaling.iloc[index]["training_sd"])
        if not np.isfinite(sd) or sd <= 0:
            sd = float(np.std(train, ddof=0)) or 1.0
        z = (prospect - mean) / sd
        abs_z = np.abs(z)
        groups = {
            "in_distribution": abs_z <= 2.0,
            "moderately_extrapolative": (abs_z > 2.0) & (abs_z <= 3.0),
            "strongly_extrapolative": abs_z > 3.0,
        }
        for group, mask in groups.items():
            subset = frame.loc[mask]
            metrics = safe_subset_metrics(subset, float(data["report"]["metrics"]["training_prevalence"]), float(data["model"]["theta"]), evaluate_predictions) if mask.any() else {}
            rows.append({
                "feature": feature, "regime": group, "n": int(mask.sum()),
                "development_mean": float(np.mean(train)), "development_sd": float(np.std(train, ddof=0)),
                "development_min": float(np.min(train)), "development_max": float(np.max(train)),
                "prospective_mean": float(np.mean(prospect)), "prospective_sd": float(np.std(prospect, ddof=0)),
                "prospective_min": float(np.min(prospect)), "prospective_max": float(np.max(prospect)),
                "standardized_mean_shift": float((np.mean(prospect) - np.mean(train)) / (np.std(train, ddof=0) or 1.0)),
                "fraction_beyond_2sd": float(np.mean(abs_z > 2.0)),
                "fraction_beyond_3sd": float(np.mean(abs_z > 3.0)),
                "fraction_outside_development_range": float(np.mean((prospect < np.min(train)) | (prospect > np.max(train)))),
                "group_fraction": float(mask.mean()),
                "brier": metrics.get("brier", math.nan), "joint_hurdle_nll": metrics.get("joint_hurdle_nll", math.nan),
                "observed_detections": metrics.get("observed_detections", math.nan), "predicted_detections": metrics.get("predicted_detections", math.nan),
            })
    return pd.DataFrame(rows)


def nb_logpmf(y: np.ndarray, mu: np.ndarray, theta: float) -> np.ndarray:
    y = np.asarray(y, dtype=float)
    mu = np.maximum(np.asarray(mu, dtype=float), EPS)
    theta = max(float(theta), EPS)
    denominator = np.log(theta + mu)
    return gammaln(y + theta) - gammaln(theta) - gammaln(y + 1.0) + theta * (np.log(theta) - denominator) + y * (np.log(mu) - denominator)


def spatial_moran(values: np.ndarray, source: np.ndarray, target: np.ndarray) -> float:
    values = np.asarray(values, dtype=float)
    finite = np.isfinite(values)
    if finite.sum() < 3:
        return math.nan
    source = np.asarray(source, dtype=np.int64)
    target = np.asarray(target, dtype=np.int64)
    keep = finite[source] & finite[target]
    source = source[keep]
    target = target[keep]
    if len(source) == 0:
        return math.nan
    x = values[finite]
    mean = float(x.mean())
    denominator = float(np.sum((x - mean) ** 2))
    if denominator <= 0:
        return math.nan
    centered = values - mean
    return float(len(x) / len(source) * np.sum(centered[source] * centered[target]) / denominator)


def spatial_permutation_p(values: np.ndarray, source: np.ndarray, target: np.ndarray, seed: int = 20261017, n_permutations: int = 199) -> float:
    observed = spatial_moran(values, source, target)
    if not np.isfinite(observed):
        return math.nan
    rng = np.random.default_rng(seed)
    permuted = []
    base = np.asarray(values, dtype=float).copy()
    for _ in range(n_permutations):
        permuted.append(spatial_moran(rng.permutation(base), source, target))
    permuted = np.asarray(permuted, dtype=float)
    expected = -1.0 / max(int(np.isfinite(base).sum()) - 1, 1)
    return float((1.0 + np.sum(np.abs(permuted - expected) >= abs(observed - expected))) / (len(permuted) + 1.0))


def spatial_residual_diagnostics(data: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    frame = data["predictions"].sort_values(["week", "model_node_id"]).reset_index(drop=True)
    nodes = pd.read_parquet(data["paths"]["refresh_node_table"]).sort_values("model_node_id")
    edges = pd.read_parquet(data["paths"]["refresh_edges"])
    source = edges["source_node"].to_numpy(np.int64)
    target = edges["target_node"].to_numpy(np.int64)
    weeks = frame["week"].drop_duplicates().tolist()
    occurrence = (frame["observed_count"].to_numpy(int) > 0).astype(float) - frame["p_occurrence"].to_numpy(float)
    count_residual = np.where(frame["observed_count"].to_numpy(int) > 0, frame["observed_count"].to_numpy(float) - frame["conditional_count_mean"].to_numpy(float), np.nan)
    combined = frame["observed_count"].to_numpy(float) - frame["expected_count"].to_numpy(float)
    rows = []
    for index, week in enumerate(weeks):
        sl = slice(index * 10037, (index + 1) * 10037)
        occ = occurrence[sl]
        cnt = count_residual[sl]
        comb = combined[sl]
        rows.extend([
            {"scope": "week", "week": week, "residual_type": "occurrence", "n": int(np.isfinite(occ).sum()), "mean": float(np.nanmean(occ)), "sd": float(np.nanstd(occ)), "moran_i": spatial_moran(occ, source, target), "permutation_p": math.nan},
            {"scope": "week", "week": week, "residual_type": "positive_count", "n": int(np.isfinite(cnt).sum()), "mean": float(np.nanmean(cnt)), "sd": float(np.nanstd(cnt)), "moran_i": spatial_moran(cnt, source, target), "permutation_p": math.nan},
            {"scope": "week", "week": week, "residual_type": "combined_expected_count", "n": int(np.isfinite(comb).sum()), "mean": float(np.mean(comb)), "sd": float(np.std(comb)), "moran_i": spatial_moran(comb, source, target), "permutation_p": math.nan},
        ])
    pooled_occ = occurrence.reshape(len(weeks), 10037).mean(axis=0)
    count_matrix = count_residual.reshape(len(weeks), 10037)
    count_valid = np.isfinite(count_matrix).sum(axis=0)
    pooled_count = np.divide(
        np.nansum(count_matrix, axis=0),
        count_valid,
        out=np.full(count_valid.shape, np.nan, dtype=float),
        where=count_valid > 0,
    )
    pooled_combined = combined.reshape(len(weeks), 10037).mean(axis=0)
    for residual_type, values in [("occurrence", pooled_occ), ("positive_count", pooled_count), ("combined_expected_count", pooled_combined)]:
        rows.append({
            "scope": "pooled_node_mean", "week": "ALL", "residual_type": residual_type,
            "n": int(np.isfinite(values).sum()), "mean": float(np.nanmean(values)), "sd": float(np.nanstd(values)),
            "moran_i": spatial_moran(values, source, target), "permutation_p": spatial_permutation_p(values, source, target),
        })
    residual_map = nodes[["model_node_id", "lon", "lat", "country_or_domain_region"]].copy()
    residual_map["pooled_occurrence_residual"] = pooled_occ
    residual_map["pooled_positive_count_residual"] = pooled_count
    residual_map["pooled_combined_expected_count_residual"] = pooled_combined
    return pd.DataFrame(rows), residual_map


def error_case_tables(data: dict[str, Any], evaluate_predictions) -> dict[str, pd.DataFrame]:
    frame = data["predictions"].copy()
    front = pd.read_parquet(data["paths"]["causal_front_feature_artifact"], columns=[
        "week", "model_node_id", "distance_to_any_prior_positive_km", "distance_to_prev4_positive_km", "weeks_since_detection_within_50km",
    ])
    frame = frame.merge(front.loc[front["week"].isin(EXPECTED_WEEKS)], on=["week", "model_node_id"], how="left", validate="one_to_one")
    nodes = pd.read_parquet(data["paths"]["refresh_node_table"])
    frame = frame.merge(nodes, on=["model_node_id", "canonical_node_id", "raster_cell", "row", "column", "x", "y", "lon", "lat", "country_or_domain_region"], how="left", validate="many_to_one")
    # Compact predictor context for the selected records.
    matrix, names, weeks, _ = build_feature_matrix(data, "prospective")
    current_weeks = np.asarray(weeks)
    selected = np.isin(current_weeks, EXPECTED_WEEKS)
    matrix = matrix.reshape(len(weeks), 10037, len(names))[selected].reshape(-1, len(names))
    predictor_frame = pd.DataFrame(matrix, columns=names)
    predictor_frame["week"] = np.repeat(EXPECTED_WEEKS, 10037)
    predictor_frame["model_node_id"] = np.tile(np.arange(10037), len(EXPECTED_WEEKS))
    frame = frame.merge(predictor_frame, on=["week", "model_node_id"], how="left", validate="one_to_one")
    positive = frame["observed_count"] > 0
    tables = {
        "highest_confidence_false_positives": frame.loc[~positive].nlargest(25, "p_occurrence"),
        "highest_confidence_false_negatives": frame.loc[positive].nsmallest(25, "p_occurrence"),
        "largest_count_underpredictions": frame.loc[positive].assign(count_gap=lambda x: x["observed_count"] - x["expected_count"]).nlargest(25, "count_gap"),
        "largest_count_overpredictions": frame.loc[positive].assign(count_gap=lambda x: x["expected_count"] - x["observed_count"]).nlargest(25, "count_gap"),
    }
    keep = [
        "week", "model_node_id", "canonical_node_id", "lon", "lat", "country_or_domain_region", "p_occurrence", "conditional_count_mean", "underlying_mu", "observed_count", "expected_count",
        "distance_to_any_prior_positive_km", "distance_to_prev4_positive_km", "weeks_since_detection_within_50km",
    ] + names
    return {name: table[keep + (["count_gap"] if "count_gap" in table.columns else [])].reset_index(drop=True) for name, table in tables.items()}


def save_figures(data: dict[str, Any], output: Path, comparison: pd.DataFrame, weekly: pd.DataFrame, geographic: pd.DataFrame, us_rank: pd.DataFrame, front: pd.DataFrame, calibration: pd.DataFrame, spatial_map: pd.DataFrame) -> None:
    try:
        import matplotlib
    except ModuleNotFoundError:
        # Atlas's validated project venv intentionally contains the scoring
        # stack but not a plotting stack.  The repository R environment has
        # the canonical ggplot2 renderer; the caller runs render_figures.R
        # after this diagnostic table-producing pass.
        return

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.size": 9, "axes.titlesize": 10, "axes.labelsize": 9, "figure.dpi": 150})
    output.mkdir(parents=True, exist_ok=True)

    def save(fig: Any, stem: str) -> None:
        fig.tight_layout()
        fig.savefig(output / f"{stem}.png", dpi=300, bbox_inches="tight")
        fig.savefig(output / f"{stem}.pdf", bbox_inches="tight")
        plt.close(fig)

    full = comparison.loc[comparison["region"] == "full_domain"].copy()
    panel_metrics = ["brier_skill", "pr_auc", "roc_auc", "joint_hurdle_nll"]
    fig, axes = plt.subplots(2, 2, figsize=(8.5, 6.0))
    for ax, metric in zip(axes.ravel(), panel_metrics):
        row = full.loc[full["metric"] == metric].iloc[0]
        ax.bar([0, 1], [row["terminal_value"], row["prospective_value"]], color=["#777777", "#1f77b4"], width=0.65)
        ax.set_xticks([0, 1], ["Terminal", "Prospective"])
        ax.set_title(metric.replace("_", " ").title())
        ax.grid(axis="y", alpha=0.25)
        for x, value in enumerate([row["terminal_value"], row["prospective_value"]]):
            ax.text(x, value, f"{value:.3g}", ha="center", va="bottom", fontsize=8)
    save(fig, "01_prospective_vs_terminal_metrics")

    fig, axes = plt.subplots(2, 2, figsize=(8.5, 6.0), sharex=True)
    for ax, metric in zip(axes.ravel(), ["prevalence", "brier_skill", "pr_auc", "joint_hurdle_nll"]):
        ax.plot(weekly["week_index"], weekly[metric], marker="o", color="#1f77b4")
        ax.set_title(metric.replace("_", " ").title())
        ax.set_ylabel(metric)
        ax.grid(alpha=0.25)
    axes[1, 0].set_xlabel("Prospective week index (W30 = 1)")
    axes[1, 1].set_xlabel("Prospective week index (W30 = 1)")
    save(fig, "02_weekly_performance_trajectory")

    fig, axes = plt.subplots(1, 3, figsize=(10.0, 3.5), sharey=False)
    for ax, region in zip(axes, ["full_domain", "Mexico", "United States"]):
        rows = calibration.loc[(calibration["row_type"] == "bin") & (calibration["binning"] == "equal_frequency") & (calibration["region"] == region)]
        ax.plot([0, 1], [0, 1], color="#888888", linestyle="--", linewidth=1)
        ax.plot(rows["mean_predicted"], rows["observed_fraction"], marker="o", color="#d62728")
        ax.set_title(region)
        ax.set_xlabel("Mean predicted probability")
        ax.set_ylabel("Observed fraction")
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.grid(alpha=0.25)
    save(fig, "03_reliability_calibration")

    lat = geographic.loc[geographic["stratum_type"] == "latitude"].copy()
    order = [label for label, _, _ in LATITUDE_BANDS]
    lat["order"] = lat["stratum"].map({x: i for i, x in enumerate(order)})
    lat = lat.sort_values("order")
    fig, axes = plt.subplots(1, 3, figsize=(10.0, 3.5), sharex=True)
    for ax, metric in zip(axes, ["brier", "pr_auc", "joint_hurdle_nll"]):
        ax.plot(lat["stratum"], lat[metric], marker="o", color="#2ca02c")
        ax.set_title(metric.replace("_", " ").title())
        ax.tick_params(axis="x", rotation=45)
        ax.grid(alpha=0.25)
    save(fig, "04_latitude_band_performance")

    top = us_rank.loc[us_rank["row_type"] == "overall_top_k"].sort_values("top_k")
    fig, ax = plt.subplots(figsize=(6.5, 4.0))
    ax.plot(top["top_k"] * 100, top["recall"] * 100, marker="o", label="Recall / capture")
    ax.plot(top["top_k"] * 100, top["precision"] * 100, marker="s", label="Precision")
    ax.set_xlabel("Top-k fraction of U.S. nodes (%)")
    ax.set_ylabel("Percent (%)")
    ax.set_xticks(top["top_k"] * 100, [f"{int(k*100)}%" for k in top["top_k"]])
    ax.set_ylim(0, 100)
    ax.legend(frameon=False)
    ax.grid(alpha=0.25)
    save(fig, "05_us_risk_rank_capture")

    fig, axes = plt.subplots(1, 3, figsize=(10.0, 3.5))
    for ax, feature in zip(axes, ["distance_to_any_prior_positive_km", "distance_to_prev4_positive_km", "weeks_since_detection_within_50km"]):
        rows = front.loc[front["front_feature"] == feature].copy()
        ax.plot(rows["stratum"], rows["joint_hurdle_nll"], marker="o", color="#9467bd")
        ax.set_title(feature.replace("_", " ").replace(" km", ""))
        ax.tick_params(axis="x", rotation=60)
        ax.set_ylabel("Joint hurdle NLL")
        ax.grid(alpha=0.25)
    save(fig, "06_front_distance_performance")

    fig, ax = plt.subplots(figsize=(7.0, 5.0))
    scatter = ax.scatter(spatial_map["lon"], spatial_map["lat"], c=spatial_map["pooled_combined_expected_count_residual"], s=4, cmap="coolwarm", vmin=-np.nanpercentile(abs(spatial_map["pooled_combined_expected_count_residual"]), 99), vmax=np.nanpercentile(abs(spatial_map["pooled_combined_expected_count_residual"]), 99))
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_title("Pooled combined expected-count residual")
    fig.colorbar(scatter, ax=ax, label="Observed count − expected count")
    ax.grid(alpha=0.2)
    save(fig, "07_spatial_residual_map")

    fig, ax = plt.subplots(figsize=(7.0, 4.0))
    ax.plot(weekly["week"], weekly["observed_detections"], marker="o", label="Observed")
    ax.plot(weekly["week"], weekly["predicted_detections"], marker="o", label="Expected")
    ax.set_ylabel("Detections")
    ax.set_xlabel("Week")
    ax.tick_params(axis="x", rotation=45)
    ax.legend(frameon=False)
    ax.grid(alpha=0.25)
    save(fig, "08_observed_vs_predicted_by_week")


def decision_summary(data: dict[str, Any], weekly: pd.DataFrame, trends: pd.DataFrame, geographic: pd.DataFrame, us_rank: pd.DataFrame, front: pd.DataFrame, calibration: pd.DataFrame, spatial: pd.DataFrame, covariate: pd.DataFrame, count: pd.DataFrame) -> tuple[str, dict[str, Any]]:
    full = data["report"]["metrics"]
    us = data["report"]["regional_metrics"]["U.S.-to-40N"]
    us_overall = us_rank.loc[us_rank["row_type"] == "overall_positive_summary"].iloc[0]
    top10 = us_rank.loc[(us_rank["row_type"] == "overall_top_k") & (np.isclose(us_rank["top_k"], 0.10))].iloc[0]
    pooled_occ = spatial.loc[(spatial["scope"] == "pooled_node_mean") & (spatial["residual_type"] == "occurrence")].iloc[0]
    pooled_count = spatial.loc[(spatial["scope"] == "pooled_node_mean") & (spatial["residual_type"] == "positive_count")].iloc[0]
    brier_trend = trends.loc[trends["metric"] == "brier_skill"].iloc[0]
    joint_trend = trends.loc[trends["metric"] == "joint_hurdle_nll"].iloc[0]
    us_useful = bool(
        float(us_overall["median_positive_risk_percentile"]) >= 75.0
        and float(us_overall["positive_percentile_ge_75"]) >= 0.50
        and float(top10["recall"]) >= 0.50
    )
    temporal_major = bool(
        (brier_trend["trend_flag"] == "decreasing" and brier_trend["slope_per_week"] < -0.01)
        or (joint_trend["trend_flag"] == "increasing" and joint_trend["slope_per_week"] > 0.02)
    )
    spatial_major = bool(float(pooled_occ["permutation_p"]) < 0.01 and abs(float(pooled_occ["moran_i"])) >= 0.10)
    count_domain = count.loc[(count["stratum_type"] == "domain") & (count["stratum"] == "full_domain")].iloc[0]
    count_ratio = float(count_domain["predicted_median_conditional_mean"] / max(count_domain["observed_median_count"], EPS))
    count_major = bool(count_ratio > 2.0 or float(count_domain["mean_absolute_log_error"]) > 1.0)
    strong = covariate.loc[covariate["regime"] == "strongly_extrapolative"]
    meaningful_shift = strong.loc[
        (strong["group_fraction"] > 0.10)
        & ((strong["standardized_mean_shift"].abs() > 0.50) | (strong["fraction_outside_development_range"] > 0.10))
    ]
    shift_major = bool(len(meaningful_shift) >= 2)
    front_far = front.loc[(front["front_feature"] == "distance_to_any_prior_positive_km") & (front["stratum"] == ">500 km")]
    front_far_not_estimable = bool(front_far.empty or float(front_far.iloc[0]["positive_node_weeks"]) == 0)
    front_concern = "NOT ASSESSABLE" if front_far_not_estimable else "PASS"
    calibration_summary = calibration.loc[calibration["row_type"] == "summary"]
    calibration_low_support = bool(calibration_summary["calibration_flag"].astype(str).str.contains("low_support").any())
    if not us_useful or temporal_major or spatial_major or count_major or shift_major:
        recommendation = "DEVELOP A4"
    else:
        intercept = float(full["calibration_intercept"])
        slope = float(full["calibration_slope"])
        if abs(intercept) > 0.25 or abs(slope - 1.0) > 0.25:
            recommendation = "RECALIBRATE ONLY"
        else:
            recommendation = "RETAIN A3"
    assessments = {
        "discrimination": "PASS" if full["roc_auc"] >= 0.90 and full["pr_auc"] >= 0.30 else "MINOR CONCERN",
        "calibration": "MINOR CONCERN" if calibration_low_support or abs(full["calibration_intercept"]) > 0.25 or abs(full["calibration_slope"] - 1.0) > 0.25 else "PASS",
        "us_transfer": "PASS" if us_useful else "MAJOR CONCERN",
        "temporal_stability": "MAJOR CONCERN" if temporal_major else "PASS",
        "front_propagation": front_concern,
        "count_process": "MAJOR CONCERN" if count_major else "PASS",
        "spatial_residual_dependence": "MAJOR CONCERN" if spatial_major else "PASS",
        "covariate_shift": "MAJOR CONCERN" if shift_major else "PASS",
    }
    evidence = {
        "recommendation": recommendation,
        "assessment": assessments,
        "us_useful_rule": "median positive percentile >=75, at least 50% of positive node-weeks >=75th percentile, and top-10% recall >=50%.",
        "us_median_positive_percentile": float(us_overall["median_positive_risk_percentile"]),
        "us_positive_percentile_ge_75": float(us_overall["positive_percentile_ge_75"]),
        "us_top10_recall": float(top10["recall"]),
        "temporal_major": temporal_major,
        "spatial_occurrence_moran_i": float(pooled_occ["moran_i"]),
        "spatial_occurrence_permutation_p": float(pooled_occ["permutation_p"]),
        "spatial_positive_count_moran_i": float(pooled_count["moran_i"]),
        "count_conditional_median_ratio": count_ratio,
        "strong_covariate_extrapolation_features": int(len(meaningful_shift)),
    }
    return recommendation, evidence


def write_readme(output_root: Path, data: dict[str, Any], reproduction: pd.DataFrame, comparison: pd.DataFrame, weekly: pd.DataFrame, trends: pd.DataFrame, decision: str, evidence: dict[str, Any]) -> None:
    report = data["report"]
    full = report["metrics"]
    us = report["regional_metrics"]["U.S.-to-40N"]
    lines = [
        "# Structured A3 prospective failure-mode analysis",
        "",
        f"Authoritative archive: `{report['frozen_model_id']}` prospective run `{data['status']['run_id']}`.",
        "This is a diagnostic-only evaluation. The frozen A3 coefficients, scaling, theta, penalty, predictors, and evaluation period were not changed; no A3 refit, recalibration, feature selection, or A4 fit was performed.",
        "",
        "## Executive summary",
        "",
        f"The analysis covers exactly `{', '.join(EXPECTED_WEEKS)}` ({len(data['predictions']):,} node-weeks; {int((data['predictions']['observed_count'] > 0).sum()):,} positive node-weeks). Reproduction of the stored full-domain report is `{'PASS' if bool(reproduction['pass'].all()) else 'FAIL'}`.",
        f"Full-domain prospective performance was ROC-AUC `{full['roc_auc']:.4f}`, PR-AUC `{full['pr_auc']:.4f}`, Brier skill `{full['brier_skill']:.4f}`, and joint hurdle NLL `{full['joint_hurdle_nll']:.4f}`. The full-domain calibration intercept/slope were `{full['calibration_intercept']:.4f}` / `{full['calibration_slope']:.4f}`.",
        f"The U.S. transfer assessment was based on within-U.S. risk ranks, not full-domain ROC-AUC: the prospective U.S. region contained {int(us['positive_count']):,} positive node-weeks, with median positive risk percentile and top-k capture reported in `results/us_risk_ranking.csv`.",
        f"Final pre-registered decision: **{decision}**.",
        "",
        "## Decision evidence",
        "",
        f"- U.S. median positive risk percentile: `{evidence['us_median_positive_percentile']:.2f}`; fraction at or above the 75th percentile: `{evidence['us_positive_percentile_ge_75']:.3f}`; top-10% recall: `{evidence['us_top10_recall']:.3f}`.",
        f"- Pooled occurrence-residual Moran's I: `{evidence['spatial_occurrence_moran_i']:.4f}`; deterministic permutation p-value: `{evidence['spatial_occurrence_permutation_p']:.4f}`.",
        f"- Pooled positive-count residual Moran's I: `{evidence['spatial_positive_count_moran_i']:.4f}`.",
        f"- Prospective conditional-count median ratio (predicted/observed): `{evidence['count_conditional_median_ratio']:.3f}`.",
        f"- Features with more than 10% of prospective rows beyond ±3 frozen training SD: `{evidence['strong_covariate_extrapolation_features']}`.",
        "",
        "## Methods",
        "",
        f"- Frozen model: `{report['frozen_model_id']}`, fit/evaluation horizon ending `2026-W29`, theta `{data['model']['theta']}`, penalty `{data['model']['penalty']}`, 34 predictors, 10,037 nodes.",
        "- Prospective observations and predictions were joined by exact `(week, model_node_id)` keys. The required boundary check fails closed unless the weeks are exactly W30-W39.",
        "- Occurrence and hurdle likelihood metrics use the repository evaluator in `python/task2c_metrics.py`. Weekly and strata metrics are descriptive slices; insufficient-class metrics are marked not estimable.",
        "- Calibration uses the established two-parameter logistic calibration convention and is reported diagnostically only; no recalibration parameters are written back to A3.",
        "- Fixed latitude bands are <20N, 20-25N, 25-30N, 30-35N, and 35-40N. Front-distance bins are predeclared in the runner. U.S. rank usefulness requires median positive percentile ≥75, ≥50% of positive node-weeks at ≥75, and top-10% recall ≥50%.",
        "- Spatial diagnostics use the fixed queen graph and deterministic 199-permutation Moran's I checks. Covariate shift uses the frozen training means/SDs, development min/max, and reconstructed 34-predictor matrices; associations are not interpreted causally.",
        "",
        "## Results",
        "",
        "Authoritative tables:",
        "",
        "- `results/metric_reproduction_check.csv`",
        "- `results/prospective_vs_terminal_metrics.csv`",
        "- `results/weekly_metrics.csv` and `results/weekly_trend_summary.csv`",
        "- `results/geographic_strata_metrics.csv`",
        "- `results/us_risk_ranking.csv`",
        "- `results/front_distance_metrics.csv`",
        "- `results/calibration_summary.csv`",
        "- `results/count_process_metrics.csv`",
        "- `results/spatial_residual_summary.csv`",
        "- `results/covariate_shift_summary.csv`",
        "- `results/highest_confidence_false_positives.csv`, `results/highest_confidence_false_negatives.csv`, `results/largest_count_underpredictions.csv`, and `results/largest_count_overpredictions.csv`",
        "",
        "Required figures are in `figures/` as 300-DPI PNG and vector PDF files. On Atlas they are rendered by `scripts/render_figures.R` using the validated repository R environment because the project Python venv is intentionally table/scoring focused.",
        "",
        "## Failure-mode assessment",
        "",
        "See `results/a3_prospective_diagnostic_summary.json` for machine-readable PASS / MINOR CONCERN / MAJOR CONCERN classifications and evidence. Individual records are descriptive examples only and are not causal explanations.",
        "",
        "## Provenance and immutability",
        "",
        "`results/analysis_manifest.json` records the repository SHA, all input paths and SHA-256 values, model constants, weeks, predictor/node counts, and runtime versions. The analysis reads authoritative Atlas artifacts and writes only to its separate analysis output root; it does not overwrite production or corrected prospective artifacts.",
        "",
        "## Reproduction",
        "",
        "Use the repository Python bootstrap, then run `python analysis/structured_a3_prospective_diagnostics/scripts/run_diagnostics.py --help`. The production Atlas paths are intentionally passed explicitly; large Atlas data products are not committed to Git.",
        "",
        "## Pre-registered comparison thresholds",
        "",
        f"A change is `SIMILAR` when its absolute change is within the metric-specific thresholds in `results/analysis_manifest.json` or relative change is ≤ {RELATIVE_SIMILAR_THRESHOLD:.0%}; otherwise direction is determined by the metric's stated better/worse direction. Thresholds were fixed before inspecting diagnostic outcomes.",
    ]
    (output_root / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", required=True, type=Path)
    parser.add_argument(
        "--repository-sha",
        default=None,
        help="Canonical repository SHA to record in the analysis manifest; defaults to the repository checkout HEAD.",
    )
    parser.add_argument("--prospective-root", required=True, type=Path)
    parser.add_argument("--terminal-root", required=True, type=Path)
    parser.add_argument("--refresh-root", required=True, type=Path)
    parser.add_argument("--model-root", required=True, type=Path)
    parser.add_argument("--production-config", required=True, type=Path)
    parser.add_argument("--deployed-model-manifest", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repository_root = args.repository_root.resolve()
    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    data = load_inputs(args)
    evaluate_predictions = import_authoritative_metrics(repository_root)
    manifest = make_analysis_manifest(
        data,
        repository_root,
        Path(__file__).resolve(),
        repository_sha_override=args.repository_sha,
    )
    write_json(output_root / "results/analysis_manifest.json", manifest)

    # This is the first substantive calculation.  No downstream diagnostic is
    # run if the stored report cannot be reproduced within the predeclared
    # tolerances.
    recomputed = exact_metric_evaluation(
        data["predictions"],
        float(data["report"]["metrics"]["training_prevalence"]),
        float(data["model"]["theta"]),
        evaluate_predictions,
    )
    reproduction = add_tolerance_rows(data["report"], recomputed)
    write_csv(output_root / "results/metric_reproduction_check.csv", reproduction)
    if not bool(reproduction["pass"].all()):
        raise RuntimeError("STOP: authoritative prospective metric reproduction failed; no further diagnostics were run")

    comparison = terminal_comparison(data, recomputed)
    weekly, trends = weekly_diagnostics(data, evaluate_predictions)
    geographic = geographic_diagnostics(data, evaluate_predictions)
    front = front_distance_diagnostics(data, evaluate_predictions)
    us_rank = us_risk_ranking(data)
    calibration_rows: list[dict[str, Any]] = []
    calibration_summary_rows: list[dict[str, Any]] = []
    regions = [("full_domain", data["predictions"]), ("Mexico", data["predictions"].loc[data["predictions"]["country_or_domain_region"] == "Mexico"]), ("United States", data["predictions"].loc[data["predictions"]["country_or_domain_region"] == "U.S.-to-40N"])]
    for region, subset in regions:
        p = subset["p_occurrence"].to_numpy(float)
        y = (subset["observed_count"].to_numpy(int) > 0)
        intercept, slope, flag = calibration_fit(p, y)
        freq = reliability_rows(p, y, region, "equal_frequency")
        width = reliability_rows(p, y, region, "equal_width")
        calibration_rows.extend(freq + width)
        reliability, resolution, uncertainty, reconstructed = brier_decomposition(freq, float(y.mean()))
        calibration_summary_rows.append({
            "row_type": "summary", "region": region, "binning": "both", "bin": None, "lower": None, "upper": None, "n": int(len(subset)),
            "mean_predicted": float(p.mean()), "observed_fraction": float(y.mean()),
            "absolute_calibration_error": None, "calibration_intercept": intercept, "calibration_slope": slope,
            "calibration_flag": flag, "expected_calibration_error": float(sum(row["n"] * row["absolute_calibration_error"] for row in freq) / len(subset)),
            "maximum_calibration_error": float(max((row["absolute_calibration_error"] for row in freq), default=math.nan)),
            "brier_reliability": reliability, "brier_resolution": resolution, "brier_uncertainty": uncertainty,
            "brier_reconstructed": reconstructed,
        })
    calibration = pd.DataFrame(calibration_rows + calibration_summary_rows)
    count = count_process_diagnostics(data, evaluate_predictions)
    spatial, spatial_map = spatial_residual_diagnostics(data)
    covariate = covariate_shift_diagnostics(data, evaluate_predictions)
    errors = error_case_tables(data, evaluate_predictions)
    decision, evidence = decision_summary(data, weekly, trends, geographic, us_rank, front, calibration, spatial, covariate, count)
    summary = {
        "analysis": "structured_a3_prospective_failure_mode_analysis",
        "status": "completed",
        "repository_sha": manifest["repository_sha"],
        "evaluation_weeks": EXPECTED_WEEKS,
        "node_count": 10037,
        "node_week_count": int(len(data["predictions"])),
        "positive_node_weeks": int((data["predictions"]["observed_count"] > 0).sum()),
        "prevalence": float((data["predictions"]["observed_count"] > 0).mean()),
        "authoritative_metric_reproduction": {"pass": bool(reproduction["pass"].all()), "max_absolute_difference": float(reproduction["absolute_difference"].max())},
        "full_domain_metrics": clean_value(recomputed),
        "us_transfer": clean_value(evidence),
        "temporal_trends": clean_value(trends.to_dict(orient="records")),
        "failure_mode_assessment": clean_value(evidence["assessment"]),
        "final_decision": decision,
        "no_refit": True,
        "no_recalibration": True,
    }
    write_json(output_root / "results/a3_prospective_diagnostic_summary.json", summary)
    write_csv(output_root / "results/prospective_vs_terminal_metrics.csv", comparison)
    write_csv(output_root / "results/weekly_metrics.csv", weekly)
    write_csv(output_root / "results/weekly_trend_summary.csv", trends)
    write_csv(output_root / "results/geographic_strata_metrics.csv", geographic)
    write_csv(output_root / "results/us_risk_ranking.csv", us_rank)
    write_csv(output_root / "results/front_distance_metrics.csv", front)
    write_csv(output_root / "results/calibration_summary.csv", calibration)
    write_csv(output_root / "results/count_process_metrics.csv", count)
    write_csv(output_root / "results/spatial_residual_summary.csv", spatial)
    write_csv(output_root / "results/spatial_residual_map_data.csv", spatial_map)
    write_csv(output_root / "results/covariate_shift_summary.csv", covariate)
    for name, table in errors.items():
        write_csv(output_root / f"results/{name}.csv", table)
    save_figures(data, output_root / "figures", comparison, weekly, geographic, us_rank, front, calibration, spatial_map)
    write_readme(output_root, data, reproduction, comparison, weekly, trends, decision, evidence)

    # Verify the frozen inputs were not modified during the analysis.
    post_hashes = {key: {"path": str(path), "sha256": sha256_file(path), "size_bytes": path.stat().st_size} for key, path in data["paths"].items()}
    if post_hashes != data["hashes"]:
        write_json(output_root / "results/input_immutability_check.json", {"pass": False, "before": data["hashes"], "after": post_hashes})
        raise RuntimeError("STOP: one or more frozen input artifacts changed during analysis")
    write_json(output_root / "results/input_immutability_check.json", {"pass": True, "inputs": post_hashes})
    print(json.dumps({"status": "completed", "decision": decision, "output_root": str(output_root)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
