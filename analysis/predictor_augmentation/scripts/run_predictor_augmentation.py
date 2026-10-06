#!/usr/bin/env python3
"""Restartable fixed-protocol A0--A3 predictor augmentation runner.

The runner deliberately lives under ``analysis/predictor_augmentation`` and
does not modify the production V2-A implementation.  It reuses the existing
data contract and metric implementation, but fits a fixed-theta exact hurdle
model so that every comparison has the same theta, penalty, folds, and
preprocessing rules.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import digamma, expit, gammaln

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
import sys

sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))
sys.path.insert(0, str(REPOSITORY_ROOT / "python"))
from run_task2e_baselines import (  # noqa: E402
    CALENDAR_FEATURES,
    DENSITY_FEATURES,
    ENV_FEATURES,
)
from task2c_metrics import evaluate_predictions  # noqa: E402


NODE_COUNT = 10_037
TOTAL_WEEKS = 81
DEVELOPMENT_WEEKS = 68
PENALTY = 0.01
FIXED_THETA = 0.7018903965556372
OPTIMIZER_MAXITER = 2_000
EPS = 1e-12
STARTING_MAIN_SHA = "88bcf3ae238f3aae712b123acfa07e4b2c5e4ad1"
SOIL_BRANCH_SHA = "97defc7"

BASE_FEATURES = list(ENV_FEATURES) + list(DENSITY_FEATURES) + [
    f"{name}_imputed" for name in DENSITY_FEATURES
] + list(CALENDAR_FEATURES) + [
    "distance_to_any_prior_positive_log1p",
    "distance_to_prev4_positive_log1p",
    "weeks_since_detection_within_50km_log1p",
    "any_prior_positive_available",
    "prev4_positive_available",
    "detection_within_50km_ever_available",
]
ADDED_FEATURES = [
    "road_density",
    "night_illumination",
    "clay_0_15",
    "water_difference_wv0033_minus_wv0010_0_15",
]
MODELS = {
    "A0": [],
    "A1": ["road_density", "night_illumination"],
    "A2": ["clay_0_15", "water_difference_wv0033_minus_wv0010_0_15"],
    "A3": list(ADDED_FEATURES),
}
FOLDS = [
    {"fold": 1, "train_start": "2025-W01", "train_end": "2025-W26", "validation_start": "2025-W27", "validation_end": "2025-W39", "train_indices": list(range(0, 26)), "validation_indices": list(range(26, 39))},
    {"fold": 2, "train_start": "2025-W01", "train_end": "2025-W39", "validation_start": "2025-W40", "validation_end": "2025-W52", "train_indices": list(range(0, 39)), "validation_indices": list(range(39, 52))},
    {"fold": 3, "train_start": "2025-W01", "train_end": "2025-W52", "validation_start": "2026-W01", "validation_end": "2026-W08", "train_indices": list(range(0, 52)), "validation_indices": list(range(52, 60))},
    {"fold": 4, "train_start": "2025-W01", "train_end": "2026-W08", "validation_start": "2026-W09", "validation_end": "2026-W16", "train_indices": list(range(0, 60)), "validation_indices": list(range(60, 68))},
]
EXPECTED_F1_F4_VALIDATION_WEEKS = 42
METRIC_COLUMNS = [
    "joint_hurdle_nll", "pr_auc", "roc_auc", "brier", "brier_skill",
    "calibration_intercept", "calibration_slope", "positive_count_mae",
    "positive_count_rmse", "conditional_mean_bias",
]


def utc_now() -> str:
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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git_value(*args: str) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=REPOSITORY_ROOT, text=True).strip()
    except Exception:
        return "unknown"


def atomic_write(path: Path, writer) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        temporary = Path(handle.name)
    try:
        writer(temporary)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_json(path: Path, payload: Any) -> None:
    atomic_write(path, lambda temporary: temporary.write_text(json.dumps(jsonable(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8"))


def atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    atomic_write(path, lambda temporary: frame.to_csv(temporary, index=False))


def atomic_npy(path: Path, array: np.ndarray) -> None:
    def write(temporary: Path) -> None:
        with temporary.open("wb") as handle:
            np.save(handle, array)
    atomic_write(path, write)


def atomic_npz(path: Path, **arrays: np.ndarray) -> None:
    def write(temporary: Path) -> None:
        with temporary.open("wb") as handle:
            np.savez_compressed(handle, **arrays)
    atomic_write(path, write)


def read_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in {".parquet", ".feather", ".arrow"}:
        return pd.read_parquet(path)
    return pd.read_csv(path)


def validate_nodes(nodes: pd.DataFrame) -> pd.DataFrame:
    id_column = "model_node_id" if "model_node_id" in nodes.columns else "node_id"
    if id_column not in nodes.columns:
        raise AssertionError("node table lacks model_node_id/node_id")
    nodes = nodes.sort_values(id_column).reset_index(drop=True)
    ids = pd.to_numeric(nodes[id_column], errors="raise").to_numpy(np.int64)
    if len(nodes) != NODE_COUNT or not np.array_equal(ids, np.arange(NODE_COUNT)):
        raise AssertionError("canonical node table is not exactly 10,037 zero-based nodes")
    nodes["model_node_id"] = ids
    return nodes


def response_folds(weeks: pd.DataFrame) -> list[dict[str, Any]]:
    labels = weeks["iso_week"].astype(str).tolist()
    result: list[dict[str, Any]] = []
    for fold in FOLDS:
        train = list(range(labels.index(fold["train_start"]), labels.index(fold["train_end"]) + 1))
        validation = list(range(labels.index(fold["validation_start"]), labels.index(fold["validation_end"]) + 1))
        if train != fold["train_indices"] or validation != fold["validation_indices"]:
            raise AssertionError(f"persisted weeks do not reconstruct prescribed F{fold['fold']}")
        result.append(dict(fold))
    if sum(len(item["validation_indices"]) for item in result) != EXPECTED_F1_F4_VALIDATION_WEEKS:
        raise AssertionError(f"F1--F4 validation weeks must cover {EXPECTED_F1_F4_VALIDATION_WEEKS} weeks")
    return result


def load_base(model_output: Path, front_features: Path) -> tuple[np.ndarray, np.ndarray, pd.DataFrame, dict[str, Any]]:
    raw = model_output / "raw"
    manifest_path = model_output / "manifests" / "revised_production_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    dynamic = np.load(raw / "dynamic_features.npy", mmap_mode="r")
    static = np.load(raw / "static_features.npy", mmap_mode="r")
    counts = np.asarray(np.load(raw / "targets_count.npy", mmap_mode="r")[:DEVELOPMENT_WEEKS], dtype=np.int64)
    expected = {"dynamic": (TOTAL_WEEKS, NODE_COUNT, 12), "static": (NODE_COUNT, 10), "counts": (DEVELOPMENT_WEEKS, NODE_COUNT)}
    actual = {"dynamic": tuple(dynamic.shape), "static": tuple(static.shape), "counts": tuple(counts.shape)}
    if actual != expected:
        raise AssertionError(f"production shape contract failed: {actual}")
    if np.any(counts < 0):
        raise AssertionError("negative development response")
    weeks = pd.read_parquet(raw / "weeks.parquet")
    if len(weeks) != TOTAL_WEEKS:
        raise AssertionError("response week count changed")
    folds = response_folds(weeks)
    nodes = validate_nodes(pd.read_parquet(raw / "nodes.parquet"))
    calendar = pd.read_parquet(raw / "calendar_features.parquet")[CALENDAR_FEATURES].to_numpy(np.float64)
    front_columns = [
        "week_index", "model_node_id", "distance_to_any_prior_positive_log1p",
        "distance_to_prev4_positive_log1p", "weeks_since_detection_within_50km_log1p",
        "any_prior_positive_available", "prev4_positive_available",
        "detection_within_50km_ever_available",
    ]
    front = pd.read_parquet(front_features, columns=front_columns)
    front = front.loc[front["week_index"] < DEVELOPMENT_WEEKS].copy()
    front = front.sort_values(["week_index", "model_node_id"]).reset_index(drop=True)
    if len(front) != DEVELOPMENT_WEEKS * NODE_COUNT:
        raise AssertionError("front features do not cover exactly F1--F4")
    front_ids = front["model_node_id"].to_numpy(np.int64).reshape(DEVELOPMENT_WEEKS, NODE_COUNT)
    if not np.array_equal(front_ids[0], np.arange(NODE_COUNT)):
        raise AssertionError("front feature node ordering changed")
    if not np.array_equal(front_ids, np.broadcast_to(np.arange(NODE_COUNT), front_ids.shape)):
        raise AssertionError("front features are not complete for every week")
    if not np.isfinite(front[front_columns[2:]].to_numpy(np.float64)).all():
        raise AssertionError("front feature values are non-finite")

    density = np.log1p(np.asarray(static[:, :5], dtype=np.float64))
    indicators = np.asarray(static[:, 5:], dtype=np.float64)
    dynamic_dev = np.asarray(dynamic[:DEVELOPMENT_WEEKS], dtype=np.float64)
    front_values = front[front_columns[2:]].to_numpy(np.float64).reshape(DEVELOPMENT_WEEKS, NODE_COUNT, 6)
    base = np.concatenate([
        dynamic_dev,
        np.broadcast_to(density[None, :, :], (DEVELOPMENT_WEEKS, NODE_COUNT, 5)),
        np.broadcast_to(indicators[None, :, :], (DEVELOPMENT_WEEKS, NODE_COUNT, 5)),
        np.broadcast_to(calendar[:DEVELOPMENT_WEEKS, None, :], (DEVELOPMENT_WEEKS, NODE_COUNT, 2)),
        front_values,
    ], axis=2)
    if base.shape != (DEVELOPMENT_WEEKS, NODE_COUNT, len(BASE_FEATURES)) or not np.isfinite(base).all():
        raise AssertionError("frozen V2-A 30-feature base cache is invalid")
    if not np.isfinite(np.asarray(static)).all() or not np.isfinite(np.asarray(dynamic[:DEVELOPMENT_WEEKS])).all():
        raise AssertionError("production predictors are non-finite")
    metadata = {"manifest": manifest, "folds": folds, "node_count": NODE_COUNT, "base_feature_order": BASE_FEATURES}
    return base, counts, nodes, metadata


def choose_transform(values: np.ndarray) -> tuple[str, dict[str, float]]:
    values = np.asarray(values, dtype=np.float64)
    if not np.isfinite(values).all() or np.any(values < 0):
        raise AssertionError("road/night feature must be finite and nonnegative before transformation")
    mean = float(values.mean())
    sd = float(values.std())
    skew = float(np.mean(((values - mean) / sd) ** 3)) if sd > 0 else 0.0
    p50, p99 = np.quantile(values, [0.50, 0.99])
    transform = "log1p" if skew > 2.0 or (p50 > 0 and p99 / p50 > 10.0) else "identity"
    return transform, {"minimum": float(values.min()), "p50": float(p50), "p99": float(p99), "maximum": float(values.max()), "mean": mean, "standard_deviation": sd, "skewness": skew}


def prepare(args: argparse.Namespace) -> None:
    output = args.output_root
    for folder in ("cache", "tasks", "predictions", "metrics", "figures", "manifests"):
        (output / folder).mkdir(parents=True, exist_ok=True)
    base, counts, nodes, metadata = load_base(args.model_output, args.front_features)
    soil = validate_nodes(read_table(args.soil_features))
    anthropogenic = validate_nodes(read_table(args.anthropogenic_features))
    soil_columns: dict[str, str] = {}
    for feature in ("clay_0_15", "water_difference_wv0033_minus_wv0010_0_15"):
        source_column = feature if feature in soil.columns else f"{feature}__mean"
        if source_column not in soil.columns:
            raise AssertionError(f"frozen Phase S1 source lacks {feature} or {feature}__mean")
        soil_columns[feature] = source_column
    required_anthropogenic = ["road_density", "night_illumination"]
    if any(feature not in anthropogenic.columns for feature in required_anthropogenic):
        raise AssertionError("anthropogenic node table lacks road_density/night_illumination")
    coverage_columns = ["road_coverage_fraction", "night_illumination_coverage_fraction"]
    if any(column not in anthropogenic.columns for column in coverage_columns):
        raise AssertionError("anthropogenic node table lacks required coverage diagnostics")
    for column in coverage_columns:
        coverage = pd.to_numeric(anthropogenic[column], errors="coerce").to_numpy(np.float64)
        if not np.isfinite(coverage).all() or np.any(coverage <= 0) or np.any(coverage > 1 + 1e-8):
            raise RuntimeError(f"STOP: invalid or zero coverage remains in {column}")
    soil = soil[["model_node_id", *soil_columns.values()]].rename(columns={value: key for key, value in soil_columns.items()})
    anthropogenic = anthropogenic[["model_node_id", "road_density", "night_illumination", *[column for column in anthropogenic.columns if column.endswith("coverage_fraction")]]]
    joined = nodes[["model_node_id"]].merge(soil, on="model_node_id", how="left", validate="one_to_one").merge(anthropogenic, on="model_node_id", how="left", validate="one_to_one")
    if len(joined) != NODE_COUNT or not np.array_equal(joined["model_node_id"].to_numpy(np.int64), np.arange(NODE_COUNT)):
        raise AssertionError("static feature join changed canonical nodes")
    if joined["model_node_id"].isna().any():
        raise AssertionError("static feature join created missing node IDs")

    missing_rows = []
    for feature in ADDED_FEATURES:
        numeric = pd.to_numeric(joined[feature], errors="coerce").to_numpy(np.float64)
        na_nodes = int(pd.isna(joined[feature]).sum())
        nonfinite_nodes = int((~np.isfinite(numeric)).sum())
        missing_rows.append({"feature": feature, "na_node_count": na_nodes, "nonfinite_node_count": nonfinite_nodes, "na_node_week_count": na_nodes * DEVELOPMENT_WEEKS, "nonfinite_node_week_count": nonfinite_nodes * DEVELOPMENT_WEEKS})
        if na_nodes or nonfinite_nodes:
            raise RuntimeError(f"STOP: unexplained missingness remains for {feature}")

    transformations: dict[str, str] = {feature: "identity" for feature in ADDED_FEATURES}
    transformation_diagnostics: list[dict[str, Any]] = []
    for feature in ("road_density", "night_illumination"):
        transformations[feature], diagnostics = choose_transform(joined[feature].to_numpy(np.float64))
        transformation_diagnostics.append({"feature": feature, "transformation": transformations[feature], **diagnostics})
    added_raw = joined[ADDED_FEATURES].to_numpy(np.float64)
    added = added_raw.copy()
    for index, feature in enumerate(ADDED_FEATURES):
        if transformations[feature] == "log1p":
            added[:, index] = np.log1p(added[:, index])
    if not np.isfinite(added).all():
        raise AssertionError("transformed augmentation features are non-finite")

    atomic_npy(output / "cache/base_features_development.npy", base)
    atomic_npy(output / "cache/counts_development.npy", counts)
    atomic_npy(output / "cache/added_features_node.npy", added)
    atomic_csv(output / "join_qa.csv", pd.DataFrame([
        {"metric": "model_nodes", "value": NODE_COUNT},
        {"metric": "soil_nodes", "value": len(soil)},
        {"metric": "anthropogenic_nodes", "value": len(anthropogenic)},
        {"metric": "matched_nodes", "value": NODE_COUNT},
        {"metric": "unmatched_nodes", "value": 0},
        {"metric": "node_weeks_before_join", "value": DEVELOPMENT_WEEKS * NODE_COUNT},
        {"metric": "node_weeks_after_join", "value": DEVELOPMENT_WEEKS * NODE_COUNT},
        {"metric": "response_rows_before_join", "value": DEVELOPMENT_WEEKS * NODE_COUNT},
        {"metric": "response_rows_after_join", "value": DEVELOPMENT_WEEKS * NODE_COUNT},
    ]))
    atomic_csv(output / "missingness_qa.csv", pd.DataFrame(missing_rows))
    atomic_csv(output / "transformation_diagnostics.csv", pd.DataFrame(transformation_diagnostics))
    atomic_csv(output / "scaling_parameters.csv", pd.DataFrame(columns=["task_id", "fold", "model", "component", "feature", "training_mean", "training_sd"]))

    task_rows: list[dict[str, Any]] = []
    task_id = 1
    for fold in FOLDS:
        for model in ("A0", "A1", "A2", "A3"):
            task_rows.append({
                "task_id": task_id, "fold": fold["fold"], "model": model,
                "added_features": "+".join(MODELS[model]), "status": "PENDING", "attempt": 1,
                "output_path": f"tasks/task_{task_id:03d}_{model}_fold{fold['fold']}.json",
                "prediction_path": f"predictions/task_{task_id:03d}_{model}_fold{fold['fold']}.npz",
            })
            task_id += 1
    atomic_csv(output / "model_task_manifest.csv", pd.DataFrame(task_rows))
    atomic_json(output / "manifests/augmentation_manifest.json", {
        "status": "prepared_baseline_gate_pending", "created_utc": utc_now(),
        "branch": git_value("branch", "--show-current"), "starting_main_sha": STARTING_MAIN_SHA,
        "origin_main_sha_at_start": STARTING_MAIN_SHA, "soil_branch_sha": SOIL_BRANCH_SHA,
        "feature_count_v2a": len(BASE_FEATURES), "models": {model: BASE_FEATURES + MODELS[model] for model in MODELS},
        "added_features": ADDED_FEATURES, "transformations": transformations,
        "penalty": PENALTY, "theta": FIXED_THETA, "theta_fixed": True,
        "objective": "exact_joint_hurdle_nll", "optimizer": "L-BFGS-B", "maxiter": OPTIMIZER_MAXITER,
        "selection_folds": "F1-F4 only", "terminal_response_loaded": False,
        "stgnn_fitted": False, "production_v2a_modified": False,
        "soil_source_artifact": str(args.soil_features), "soil_source_sha256": sha256_file(args.soil_features),
        "anthropogenic_source_artifact": str(args.anthropogenic_features), "anthropogenic_source_sha256": sha256_file(args.anthropogenic_features),
        "reference_metrics": str(args.reference_metrics), "reference_metrics_sha256": sha256_file(args.reference_metrics),
        "canonical_nodes": NODE_COUNT, "response_period": ["2025-W01", "2026-W16"],
        "software": {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__},
        "data_manifest": metadata["manifest"],
    })
    atomic_write(output / "software_environment.txt", lambda temporary: temporary.write_text("\n".join([
        f"python={platform.python_version()}", f"numpy={np.__version__}", f"pandas={pd.__version__}",
        f"scipy={__import__('scipy').__version__}", "optimizer=L-BFGS-B", f"maxiter={OPTIMIZER_MAXITER}",
        f"penalty={PENALTY}", f"theta={FIXED_THETA}", "theta_fixed=True", "objective=exact_joint_hurdle_nll",
        "folds=F1-F4 only", "terminal_response_loaded=False", "stgnn_fitted=False",
    ]) + "\n", encoding="utf-8"))
    print(json.dumps({"status": "prepared", "tasks": len(task_rows), "node_count": NODE_COUNT, "transformations": transformations}, indent=2))


def regularized_logistic_objective(beta: np.ndarray, x: np.ndarray, y: np.ndarray, penalty: float) -> tuple[float, np.ndarray]:
    z = np.clip(x @ beta, -40.0, 40.0)
    probability = expit(z)
    loss = float(np.mean(np.logaddexp(0.0, z) - y * z)) + 0.5 * penalty * float(np.sum(beta[1:] ** 2))
    gradient = (x.T @ (probability - y)) / y.size
    gradient = gradient.copy()
    gradient[1:] += penalty * beta[1:]
    return loss, gradient


def fixed_theta_zt_nb_objective(beta: np.ndarray, x: np.ndarray, y: np.ndarray, penalty: float) -> tuple[float, np.ndarray]:
    theta = FIXED_THETA
    log_mu = np.clip(x @ beta, -20.0, 20.0)
    mu = np.exp(log_mu)
    log_theta = math.log(theta)
    denominator = theta + mu
    log_p0 = theta * (log_theta - np.log(denominator))
    p0 = np.exp(np.minimum(log_p0, 0.0))
    p_positive = np.maximum(-np.expm1(log_p0), EPS)
    logpmf = gammaln(y + theta) - gammaln(theta) - gammaln(y + 1.0) + theta * (log_theta - np.log(denominator)) + y * (log_mu - np.log(denominator))
    loss = -float(np.mean(logpmf - np.log(p_positive))) + 0.5 * penalty * float(np.sum(beta[1:] ** 2))
    dlogpmf_dz = y - (theta + y) * mu / denominator
    dlogp0_dz = -theta * mu / denominator
    dlogpositive_dz = -(p0 / p_positive) * dlogp0_dz
    gradient = -(x.T @ (dlogpmf_dz - dlogpositive_dz)) / y.size
    gradient = gradient.copy()
    gradient[1:] += penalty * beta[1:]
    return loss, gradient


def fit_fixed_theta(x: np.ndarray, counts: np.ndarray) -> dict[str, Any]:
    y = (np.asarray(counts, dtype=np.int64) > 0).astype(np.float64)
    positive = np.asarray(counts, dtype=np.float64) > 0
    if not positive.any() or positive.all():
        raise ValueError("hurdle fit requires both zero and positive observations")
    design = np.column_stack([np.ones(len(x), dtype=np.float64), x])
    occurrence = minimize(lambda beta: regularized_logistic_objective(beta, design, y, PENALTY), np.zeros(design.shape[1]), jac=True, method="L-BFGS-B", options={"maxiter": OPTIMIZER_MAXITER, "ftol": 1e-10, "gtol": 1e-7})
    positive_design = design[positive]
    positive_counts = np.asarray(counts, dtype=np.float64)[positive]
    start = np.zeros(design.shape[1], dtype=np.float64)
    start[0] = math.log(max(float(positive_counts.mean()), 1e-3))
    count = minimize(lambda beta: fixed_theta_zt_nb_objective(beta, positive_design, positive_counts, PENALTY), start, jac=True, method="L-BFGS-B", options={"maxiter": OPTIMIZER_MAXITER, "ftol": 1e-10, "gtol": 1e-7, "maxls": 40})
    if not occurrence.success or not count.success:
        raise RuntimeError(f"non-converged fixed-theta fit: occurrence={occurrence.message}; count={count.message}")
    return {
        "occurrence_beta": occurrence.x, "count_beta": count.x,
        "theta": FIXED_THETA,
        "fit_info": {"objective": "exact_joint_hurdle_nll", "penalty": PENALTY, "theta": FIXED_THETA, "theta_fixed": True, "occurrence_success": bool(occurrence.success), "count_success": bool(count.success), "occurrence_iterations": int(occurrence.nit), "count_iterations": int(count.nit), "occurrence_nll_training": float(occurrence.fun), "positive_count_nll_training": float(count.fun), "training_rows": int(len(counts)), "training_positive_rows": int(positive.sum())},
    }


def predict(state: dict[str, Any], x: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    design = np.column_stack([np.ones(len(x), dtype=np.float64), x])
    p = expit(np.clip(design @ state["occurrence_beta"], -40.0, 40.0))
    mu = np.exp(np.clip(design @ state["count_beta"], -20.0, 20.0))
    log_p0 = FIXED_THETA * (math.log(FIXED_THETA) - np.log(FIXED_THETA + mu))
    conditional = mu / np.maximum(-np.expm1(log_p0), EPS)
    return p, conditional, mu


def task_row(output: Path, task_id: int) -> dict[str, Any]:
    manifest = pd.read_csv(output / "model_task_manifest.csv")
    rows = manifest.loc[manifest["task_id"] == task_id]
    if len(rows) != 1:
        raise KeyError(f"unknown task_id {task_id}")
    return rows.iloc[0].to_dict()


def standardize(raw_train: np.ndarray, raw_eval: np.ndarray, feature_names: list[str]) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    mean = raw_train.mean(axis=0, dtype=np.float64)
    scale = raw_train.std(axis=0, dtype=np.float64)
    unscaled = [index for index, name in enumerate(feature_names) if name.endswith("_imputed") or name.endswith("_available") or name in CALENDAR_FEATURES]
    scaled = [index for index in range(len(feature_names)) if index not in set(unscaled)]
    mean[unscaled] = 0.0
    scale[unscaled] = 1.0
    scale = np.asarray(scale, dtype=np.float64)
    scale[scaled] = np.where(np.isfinite(scale[scaled]) & (scale[scaled] > 0), scale[scaled], 1.0)
    if not np.isfinite(mean).all() or not np.isfinite(scale).all():
        raise AssertionError("fold scaling is non-finite")
    state = {"feature_names": feature_names, "training_mean": mean.tolist(), "training_sd": scale.tolist(), "scaled_feature_indices": scaled, "unscaled_feature_indices": unscaled}
    return (raw_train - mean[None, :]) / scale[None, :], (raw_eval - mean[None, :]) / scale[None, :], state


def worker(args: argparse.Namespace) -> None:
    output = args.output_root
    row = task_row(output, args.task_id)
    task_path = output / str(row["output_path"])
    prediction_path = output / str(row["prediction_path"])
    if task_path.exists() and prediction_path.exists():
        try:
            existing = json.loads(task_path.read_text(encoding="utf-8"))
            if existing.get("status") == "completed":
                print(f"SKIP -- already complete task_id={args.task_id}")
                return
        except Exception:
            pass
    model = str(row["model"])
    if model != "A0":
        gate_path = output / "baseline_gate.json"
        if not gate_path.exists() or not json.loads(gate_path.read_text(encoding="utf-8")).get("pass", False):
            raise RuntimeError("STOP: A0 baseline reproduction gate has not passed")
    base = np.load(output / "cache/base_features_development.npy", mmap_mode="r")
    counts = np.load(output / "cache/counts_development.npy", mmap_mode="r")
    added = np.load(output / "cache/added_features_node.npy", mmap_mode="r")
    fold = next(item for item in FOLDS if int(item["fold"]) == int(row["fold"]))
    train_times = np.asarray(fold["train_indices"], dtype=np.int64)
    eval_times = np.asarray(fold["validation_indices"], dtype=np.int64)
    added_features = list(MODELS[model])
    feature_names = BASE_FEATURES + added_features
    if added_features:
        indices = np.asarray([ADDED_FEATURES.index(name) for name in added_features], dtype=np.int64)
        extra = np.broadcast_to(np.asarray(added[:, indices])[None, :, :], (DEVELOPMENT_WEEKS, NODE_COUNT, len(indices)))
        array = np.concatenate([np.asarray(base), extra], axis=2)
    else:
        array = np.asarray(base)
    raw_train = array[train_times].reshape(-1, len(feature_names)).astype(np.float64, copy=False)
    raw_eval = array[eval_times].reshape(-1, len(feature_names)).astype(np.float64, copy=False)
    x_train, x_eval, scaling = standardize(raw_train, raw_eval, feature_names)
    y_train = np.asarray(counts[train_times], dtype=np.int64).reshape(-1)
    y_eval = np.asarray(counts[eval_times], dtype=np.int64).reshape(-1)
    started = time.time()
    state = fit_fixed_theta(x_train, y_train)
    p, conditional, mu = predict(state, x_eval)
    metrics = evaluate_predictions(y_eval, p, conditional, mu, FIXED_THETA, training_prevalence=float(np.mean(y_train > 0)), count_score_family="zt_nb")
    metrics["conditional_mean_bias"] = float(np.mean(conditional[y_eval > 0]) - np.mean(y_eval[y_eval > 0])) if np.any(y_eval > 0) else None
    coefficient_rows = []
    for component, coefficients in (("occurrence", state["occurrence_beta"]), ("positive_count", state["count_beta"])):
        for feature, coefficient in zip(feature_names, coefficients[1:]):
            coefficient_rows.append({"model": model, "fold": int(row["fold"]), "component": component, "feature": feature, "coefficient_standardized": float(coefficient), "sign": "positive" if coefficient > 0 else "negative" if coefficient < 0 else "zero", "absolute_coefficient": float(abs(coefficient))})
    result = {
        "status": "completed", "task_id": int(args.task_id), "model": model, "fold": int(row["fold"]),
        "added_features": added_features, "feature_names": feature_names, "penalty": PENALTY,
        "theta": FIXED_THETA, "theta_fixed": True, "metrics": metrics, "fit_info": state["fit_info"],
        "occurrence_coefficients": state["occurrence_beta"].tolist(), "count_coefficients": state["count_beta"].tolist(),
        "scaling": scaling, "coefficient_rows": coefficient_rows, "validation_rows": int(len(y_eval)),
        "runtime_seconds": float(time.time() - started), "terminal_response_loaded": False, "stgnn_fitted": False,
    }
    atomic_npz(prediction_path, y=y_eval, p=p, conditional=conditional, mu=mu)
    atomic_json(task_path, result)
    print(json.dumps({"status": "completed", "task_id": int(args.task_id), "model": model, "fold": int(row["fold"]), "runtime_seconds": result["runtime_seconds"]}, indent=2))


def baseline_gate(args: argparse.Namespace) -> None:
    output = args.output_root
    reference = pd.read_csv(args.reference_metrics)
    if "fold" not in reference.columns:
        raise RuntimeError("authoritative baseline reference lacks fold")
    reference = reference.set_index("fold")
    rows = []
    for fold in range(1, 5):
        task = task_row(output, int((fold - 1) * 4 + 1))
        result_path = output / str(task["output_path"])
        if not result_path.exists():
            raise RuntimeError(f"STOP: A0 fold {fold} result is missing")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if result.get("status") != "completed" or int(result.get("fold", -1)) != fold or result.get("model") != "A0":
            raise RuntimeError(f"STOP: invalid A0 fold {fold} result")
        for metric in METRIC_COLUMNS:
            expected = float(reference.loc[fold, metric])
            observed = float(result["metrics"][metric])
            difference = abs(observed - expected)
            rows.append({"fold": fold, "metric": metric, "reference": expected, "reproduced": observed, "absolute_difference": difference, "tolerance": 1e-9, "within_tolerance": bool(difference <= 1e-9)})
    comparison = pd.DataFrame(rows)
    passed = bool(comparison["within_tolerance"].all())
    atomic_csv(output / "baseline_reproduction.csv", comparison)
    gate = {"status": "baseline_reproduction_passed" if passed else "STOP_BASELINE_REPRODUCTION_FAILED", "pass": passed, "feature_count": len(BASE_FEATURES), "penalty": PENALTY, "theta": FIXED_THETA, "theta_fixed": True, "objective": "exact_joint_hurdle_nll", "optimizer": "L-BFGS-B", "folds": "F1-F4 only", "metric_tolerance": 1e-9, "reference_metrics": str(args.reference_metrics), "reference_sha256": sha256_file(args.reference_metrics), "terminal_response_loaded": False, "stgnn_fitted": False, "generated_utc": utc_now()}
    atomic_json(output / "baseline_gate.json", gate)
    atomic_json(output / "manifests/baseline_reproduction_manifest.json", gate)
    print(json.dumps(gate, indent=2))
    if not passed:
        raise SystemExit("STOP: A0 baseline reproduction failed")


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="mode", required=True)
    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--model-output", type=Path, required=True)
    prepare_parser.add_argument("--front-features", type=Path, required=True)
    prepare_parser.add_argument("--anthropogenic-features", type=Path, required=True)
    prepare_parser.add_argument("--soil-features", type=Path, required=True)
    prepare_parser.add_argument("--reference-metrics", type=Path, required=True)
    prepare_parser.add_argument("--output-root", type=Path, required=True)
    worker_parser = subparsers.add_parser("worker")
    worker_parser.add_argument("--output-root", type=Path, required=True)
    worker_parser.add_argument("--task-id", type=int, required=True)
    baseline_parser = subparsers.add_parser("baseline")
    baseline_parser.add_argument("--output-root", type=Path, required=True)
    baseline_parser.add_argument("--reference-metrics", type=Path, required=True)
    finalize_parser = subparsers.add_parser("finalize")
    finalize_parser.add_argument("--output-root", type=Path, required=True)
    finalize_parser.add_argument("--reference-manifest", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "prepare":
        prepare(args)
    elif args.mode == "worker":
        worker(args)
    elif args.mode == "baseline":
        baseline_gate(args)
    else:
        from finalize_predictor_augmentation import finalize
        finalize(args.output_root, args.reference_manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

