#!/usr/bin/env python3
"""Construct and validate the Task-2A dataset, splits, scalers, and baselines."""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ENV_FEATURES = [
    "era5_mintemp", "era5_soilmoist", "era5_lai_low", "agera5_relhum_min",
    "era5land_tmean", "era5land_soiltemp_l1_mean", "era5land_soiltemp_l2_mean",
    "era5land_soilwater_l1_mean", "era5land_soilwater_l2_mean",
    "era5land_surface_pressure_mean", "era5land_lai_high_mean", "era5land_lai_low_mean",
]
STATIC_DENSITY_FEATURES = ["cattle_density", "goat_density", "sheep_density", "horse_density", "pig_density"]
STATIC_INDICATOR_FEATURES = [f"{name}_imputed" for name in STATIC_DENSITY_FEATURES]
STATIC_FEATURES = STATIC_DENSITY_FEATURES + STATIC_INDICATOR_FEATURES
CALENDAR_FEATURES = ["week_sin", "week_cos"]
FEATURES = ENV_FEATURES + STATIC_FEATURES + CALENDAR_FEATURES


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def jsonable(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, np.ndarray):
        return [jsonable(item) for item in value.tolist()]
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(jsonable(value), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def iso_week_start(label: str) -> date:
    year, week = label.split("-W")
    return date.fromisocalendar(int(year), int(week), 1)


def week_range(start: str, end: str) -> list[str]:
    first = iso_week_start(start)
    last = iso_week_start(end)
    result = []
    current = first
    while current <= last:
        iso = current.isocalendar()
        result.append(f"{iso.year:04d}-W{iso.week:02d}")
        current += timedelta(days=7)
    return result


def fold_dates(weeks: pd.DataFrame) -> tuple[list[int], list[int], list[dict[str, Any]]]:
    labels = weeks["iso_week"].astype(str).tolist()
    expected = week_range("2024-W01", "2026-W29")
    if labels != expected:
        raise AssertionError("target weeks are not the expected consecutive ISO weeks")
    test_indices = list(range(len(labels) - 26, len(labels)))
    dev_indices = list(range(len(labels) - 26))
    expected_test = week_range("2026-W04", "2026-W29")
    if [labels[i] for i in test_indices] != expected_test:
        raise AssertionError("final test interval is not 2026-W04 through 2026-W29")
    folds_spec = [
        ("2024-W01", "2024-W52", "2025-W01", "2025-W13"),
        ("2024-W01", "2025-W13", "2025-W14", "2025-W26"),
        ("2024-W01", "2025-W26", "2025-W27", "2025-W39"),
        ("2024-W01", "2025-W39", "2025-W40", "2025-W52"),
    ]
    folds = []
    for number, (train_start, train_end, valid_start, valid_end) in enumerate(folds_spec, 1):
        train = list(range(labels.index(train_start), labels.index(train_end) + 1))
        valid = list(range(labels.index(valid_start), labels.index(valid_end) + 1))
        if set(train) & set(valid):
            raise AssertionError("temporal training and validation overlap")
        if max(train) >= min(valid):
            raise AssertionError("training contains a future week")
        folds.append({
            "fold": number,
            "train_indices": train,
            "validation_indices": valid,
            "train_weeks": [labels[train[0]], labels[train[-1]]],
            "validation_weeks": [labels[valid[0]], labels[valid[-1]]],
            "train_week_count": len(train),
            "validation_week_count": len(valid),
        })
    if len(dev_indices) != 107:
        raise AssertionError("development period must contain 107 weeks")
    return dev_indices, test_indices, folds


def feature_matrix(dynamic: np.ndarray, static: np.ndarray, calendar: np.ndarray,
                   times: list[int], nodes: np.ndarray | None = None) -> np.ndarray:
    node_slice = slice(None) if nodes is None else nodes
    dyn = np.asarray(dynamic[times, node_slice], dtype=np.float32).reshape(-1, dynamic.shape[-1])
    stat = np.asarray(static[node_slice], dtype=np.float32)
    stat = np.tile(stat, (len(times), 1))
    cal = np.repeat(np.asarray(calendar[times], dtype=np.float32), static[node_slice].shape[0], axis=0)
    stat[:, :len(STATIC_DENSITY_FEATURES)] = np.log1p(stat[:, :len(STATIC_DENSITY_FEATURES)])
    return np.concatenate([dyn, stat, cal], axis=1)


def target_vector(counts: np.ndarray, times: list[int], nodes: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    values = counts[times, :] if nodes is None else counts[np.ix_(times, nodes)]
    values = np.asarray(values, dtype=np.int32).reshape(-1)
    return (values > 0).astype(np.int8), values


def fit_scaler(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    mean = np.mean(x, axis=0, dtype=np.float64)
    scale = np.std(x, axis=0, dtype=np.float64)
    scale[~np.isfinite(scale) | (scale == 0)] = 1.0
    return mean.astype(np.float64), scale.astype(np.float64)


def apply_scaler(x: np.ndarray, mean: np.ndarray, scale: np.ndarray) -> np.ndarray:
    return ((x - mean) / scale).astype(np.float64)


def write_scaler(path: Path, mean: np.ndarray, scale: np.ndarray, train_indices: list[int], spatial_fold: int | None = None) -> None:
    write_json(path, {
        "feature_names": FEATURES,
        "transform": {name: ("log1p" if name in STATIC_DENSITY_FEATURES else "identity") for name in FEATURES},
        "training_week_indices": train_indices,
        "spatial_fold_excluded": spatial_fold,
        "mean": mean,
        "standard_deviation": scale,
        "zero_scale_replaced_by_one": True,
    })


def summarize_values(values: np.ndarray, zero_fraction: bool = False) -> dict[str, Any]:
    flat = np.asarray(values, dtype=np.float64).reshape(-1)
    finite = np.isfinite(flat)
    result: dict[str, Any] = {
        "minimum": np.min(flat[finite]) if finite.any() else np.nan,
        "maximum": np.max(flat[finite]) if finite.any() else np.nan,
        "mean": np.mean(flat[finite]) if finite.any() else np.nan,
        "median": np.median(flat[finite]) if finite.any() else np.nan,
        "standard_deviation": np.std(flat[finite]) if finite.any() else np.nan,
        "quantiles": np.quantile(flat[finite], [0, .01, .05, .25, .5, .75, .95, .99, 1]).tolist() if finite.any() else [],
        "missing_values": int(np.isnan(flat).sum()),
        "non_finite_values": int((~finite).sum()),
    }
    if zero_fraction:
        result["zero_fraction"] = float(np.mean(flat[finite] == 0)) if finite.any() else np.nan
    return result


def feature_diagnostics(dynamic: np.ndarray, static: np.ndarray, weeks: pd.DataFrame) -> dict[str, Any]:
    result: dict[str, Any] = {"dynamic": {}, "static": {}}
    for index, name in enumerate(ENV_FEATURES):
        values = dynamic[:, :, index]
        summary = summarize_values(values, zero_fraction=True)
        temporal_mean = np.mean(values, axis=1)
        spatial_mean = np.mean(values, axis=0)
        summary.update({
            "temporal_mean_range": [float(np.min(temporal_mean)), float(np.max(temporal_mean))],
            "spatial_mean_range": [float(np.min(spatial_mean)), float(np.max(spatial_mean))],
            "unique_weekly_layer_hashes": int(len({hashlib.sha256(np.asarray(values[i], dtype=np.float32).tobytes()).hexdigest() for i in range(values.shape[0])})),
            "constant": bool(np.ptp(values) == 0),
            "nearly_constant": bool(np.std(values) <= 1e-12),
        })
        result["dynamic"][name] = summary
    for index, name in enumerate(STATIC_FEATURES):
        result["static"][name] = summarize_values(static[:, index], zero_fraction=True)
        result["static"][name]["constant"] = bool(np.ptp(static[:, index]) == 0)
        result["static"][name]["nearly_constant"] = bool(np.std(static[:, index]) <= 1e-12)
    result["all_finite"] = bool(np.isfinite(dynamic).all() and np.isfinite(static).all())
    result["all_livestock_nonnegative"] = bool(np.all(static[:, :len(STATIC_DENSITY_FEATURES)] >= 0))
    result["week_count"] = int(len(weeks))
    return result


def correlation_diagnostics(dynamic: np.ndarray, dev_indices: list[int]) -> dict[str, Any]:
    from scipy.stats import spearmanr
    values = dynamic[dev_indices].reshape(-1, dynamic.shape[-1]).astype(np.float64)
    pearson = np.corrcoef(values, rowvar=False)
    sample_size = min(250_000, values.shape[0])
    sample = values[np.linspace(0, values.shape[0] - 1, sample_size, dtype=np.int64)]
    spearman = spearmanr(sample, axis=0).statistic
    pairs = []
    for i in range(len(ENV_FEATURES)):
        for j in range(i + 1, len(ENV_FEATURES)):
            r_p = float(pearson[i, j])
            r_s = float(spearman[i, j])
            if max(abs(r_p), abs(r_s)) >= .90:
                pairs.append({"feature_a": ENV_FEATURES[i], "feature_b": ENV_FEATURES[j],
                              "pearson": r_p, "spearman": r_s,
                              "flag_0.90": True, "flag_0.95": max(abs(r_p), abs(r_s)) >= .95})
    return {"pearson": pearson, "spearman": spearman, "spearman_sample_size": sample_size,
            "high_redundancy_pairs": pairs, "features_retained": ENV_FEATURES}


def component_diagnostics(nodes: pd.DataFrame, edges: pd.DataFrame, counts: np.ndarray, output_dir: Path) -> dict[str, Any]:
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    n = len(nodes)
    if len(edges):
        sources = edges["source_node"].to_numpy(dtype=np.int64)
        targets = edges["target_node"].to_numpy(dtype=np.int64)
        graph = coo_matrix((np.ones(len(edges)), (sources, targets)), shape=(n, n)).tocsr()
    else:
        graph = coo_matrix((n, n)).tocsr()
    components, labels = connected_components(graph, directed=False, return_labels=True)
    positive_by_node = np.sum(counts > 0, axis=0) > 0
    records = []
    for component_id in range(components):
        idx = np.flatnonzero(labels == component_id)
        records.append({
            "component_id": component_id,
            "size": len(idx),
            "singleton": len(idx) == 1,
            "contains_observations": bool(positive_by_node[idx].any()),
            "min_row": int(nodes.iloc[idx]["row"].min()), "max_row": int(nodes.iloc[idx]["row"].max()),
            "min_column": int(nodes.iloc[idx]["column"].min()), "max_column": int(nodes.iloc[idx]["column"].max()),
            "min_x": float(nodes.iloc[idx]["x"].min()), "max_x": float(nodes.iloc[idx]["x"].max()),
            "min_y": float(nodes.iloc[idx]["y"].min()), "max_y": float(nodes.iloc[idx]["y"].max()),
        })
    node_components = nodes[["node_id"]].copy()
    node_components["component_id"] = labels
    node_components["component_size"] = node_components["component_id"].map(pd.Series(labels).value_counts())
    node_components["component_contains_observations"] = node_components["component_id"].map(
        {record["component_id"]: record["contains_observations"] for record in records}
    )
    node_components.to_parquet(output_dir / "component_by_node.parquet", index=False)
    return {"component_count": int(components), "isolated_nodes": int(np.sum(np.bincount(labels, minlength=components) == 1)),
            "components": records, "component_by_node_path": str(output_dir / "component_by_node.parquet")}


def spatial_partitions(nodes: pd.DataFrame, counts: np.ndarray, output_dir: Path) -> dict[str, Any]:
    block_rows = ((nodes["row"].to_numpy(dtype=np.int64) - 1) // 5).astype(np.int64)
    block_cols = ((nodes["column"].to_numpy(dtype=np.int64) - 1) // 5).astype(np.int64)
    block_keys = pd.DataFrame({"block_row": block_rows, "block_column": block_cols}).drop_duplicates().sort_values(["block_row", "block_column"]).reset_index(drop=True)
    block_keys["spatial_fold"] = np.arange(len(block_keys), dtype=np.int64) % 5
    block_keys["spatial_block_id"] = block_keys.apply(lambda row: f"r{int(row.block_row):03d}_c{int(row.block_column):03d}", axis=1)
    assignments = pd.DataFrame({"node_id": nodes["node_id"].to_numpy(dtype=np.int64), "row": nodes["row"], "column": nodes["column"], "block_row": block_rows, "block_column": block_cols})
    assignments = assignments.merge(block_keys, on=["block_row", "block_column"], how="left", validate="many_to_one")
    assignments.to_parquet(output_dir / "spatial_node_assignments.parquet", index=False)
    records = []
    for fold in range(5):
        node_idx = np.flatnonzero(assignments["spatial_fold"].to_numpy() == fold)
        selected_blocks = block_keys.loc[block_keys["spatial_fold"] == fold, "spatial_block_id"].tolist()
        records.append({"spatial_fold": fold, "node_count": len(node_idx), "block_count": len(selected_blocks),
                        "blocks": selected_blocks, "min_row": int(nodes.iloc[node_idx]["row"].min()),
                        "max_row": int(nodes.iloc[node_idx]["row"].max()), "min_column": int(nodes.iloc[node_idx]["column"].min()),
                        "max_column": int(nodes.iloc[node_idx]["column"].max()),
                        "positive_node_weeks_post_hoc": int(np.sum(counts[:, node_idx] > 0))})
    return {"block_dimensions_cells": [5, 5], "block_count": len(block_keys), "fold_count": 5,
            "seed": None, "assignment_rule": "sorted full-raster row/column 5x5 blocks, round-robin modulo five",
            "folds": records, "assignments_path": str(output_dir / "spatial_node_assignments.parquet"),
            "block_table": block_keys.to_dict(orient="records"), "node_fold": assignments["spatial_fold"].to_numpy(dtype=np.int8)}


def save_combined_masks(spatial: dict[str, Any], temporal_folds: list[dict[str, Any]], weeks: pd.DataFrame,
                        n_nodes: int, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    node_fold = np.asarray(spatial["node_fold"])
    records = []
    for temporal in temporal_folds:
        train_week = np.zeros(len(weeks), dtype=bool); train_week[temporal["train_indices"]] = True
        valid_week = np.zeros(len(weeks), dtype=bool); valid_week[temporal["validation_indices"]] = True
        for spatial_fold in range(5):
            train_node = node_fold != spatial_fold
            valid_node = node_fold == spatial_fold
            train_loss = np.outer(train_week, train_node)
            evaluation = np.outer(valid_week, valid_node)
            stem = f"temporal{temporal['fold']}_spatial{spatial_fold}"
            np.save(output_dir / f"{stem}_train_loss.npy", train_loss)
            np.save(output_dir / f"{stem}_evaluation.npy", evaluation)
            records.append({"temporal_fold": temporal["fold"], "spatial_fold": spatial_fold,
                            "train_loss_mask": str(output_dir / f"{stem}_train_loss.npy"),
                            "evaluation_mask": str(output_dir / f"{stem}_evaluation.npy"),
                            "train_loss_cells": int(train_loss.sum()), "evaluation_cells": int(evaluation.sum())})
    return {"shape": [len(weeks), n_nodes], "records": records,
            "definition": "loss uses temporal training weeks and non-held-out spatial nodes; evaluation uses temporal validation weeks and held-out spatial nodes"}


def metrics_occurrence(y: np.ndarray, probability: np.ndarray) -> dict[str, Any]:
    from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score
    p = np.clip(probability.astype(float), 1e-7, 1 - 1e-7)
    result = {"log_loss": float(log_loss(y, p, labels=[0, 1])), "brier_score": float(brier_score_loss(y, p)),
              "pr_auc": float(average_precision_score(y, p))}
    result["roc_auc"] = float(roc_auc_score(y, p)) if np.unique(y).size == 2 else None
    logit_p = np.log(p / (1 - p)).reshape(-1, 1)
    from sklearn.linear_model import LogisticRegression
    calibration = LogisticRegression(C=1e6, solver="lbfgs", max_iter=100).fit(logit_p, y)
    result["calibration_intercept"] = float(calibration.intercept_[0])
    result["calibration_slope"] = float(calibration.coef_[0, 0])
    bins = np.linspace(0, 1, 11)
    reliability = []
    for low, high in zip(bins[:-1], bins[1:]):
        selected = (probability >= low) & ((probability < high) if high < 1 else (probability <= high))
        if selected.any():
            reliability.append({"bin_lower": low, "bin_upper": high, "count": int(selected.sum()),
                                "mean_predicted": float(probability[selected].mean()), "observed_fraction": float(y[selected].mean())})
    result["reliability"] = reliability
    return result


def seasonal_baseline(train_times: list[int], eval_times: list[int], weeks: pd.DataFrame,
                      counts: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    train_counts = counts[train_times]
    train_week_numbers = weeks.iloc[train_times]["iso_week_number"].to_numpy()
    eval_week_numbers = weeks.iloc[eval_times]["iso_week_number"].to_numpy()
    pooled_positive = train_counts[train_counts > 0]
    fallback = float(pooled_positive.mean()) if len(pooled_positive) else 0.0
    p_by_week, mu_by_week = {}, {}
    for week_number in range(1, 54):
        selected = train_week_numbers == week_number
        values = train_counts[selected]
        if values.size:
            p_by_week[week_number] = float(np.mean(values > 0))
            positive = values[values > 0]
            mu_by_week[week_number] = float(positive.mean()) if len(positive) else fallback
        else:
            p_by_week[week_number] = float(np.mean(train_counts > 0))
            mu_by_week[week_number] = fallback
    p = np.repeat([p_by_week[int(w)] for w in eval_week_numbers], counts.shape[1])
    mu = np.repeat([mu_by_week[int(w)] for w in eval_week_numbers], counts.shape[1])
    return p, mu, p * mu


def fit_nb_glm(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, float]:
    from scipy.optimize import minimize
    from scipy.special import gammaln
    x_design = np.column_stack([np.ones(len(x)), x])
    beta_start = np.linalg.lstsq(x_design, np.log1p(y), rcond=None)[0]
    mean = max(float(np.mean(y)), 1e-6)
    variance = float(np.var(y))
    alpha_start = max((variance - mean) / (mean * mean), 1e-5)

    def objective(parameters: np.ndarray) -> float:
        beta = parameters[:-1]
        alpha = float(np.exp(np.clip(parameters[-1], -12, 8)))
        mu = np.exp(np.clip(x_design @ beta, -20, 20))
        inv_alpha = 1.0 / alpha
        log_denom = np.log1p(alpha * mu)
        log_likelihood = (gammaln(y + inv_alpha) - gammaln(inv_alpha) - gammaln(y + 1)
                          - inv_alpha * log_denom + y * (np.log(alpha) + np.log(mu) - log_denom))
        return float(-np.mean(log_likelihood))

    result = minimize(objective, np.r_[beta_start, np.log(alpha_start)], method="L-BFGS-B",
                      options={"maxiter": 250, "ftol": 1e-9})
    if not result.success:
        raise RuntimeError(f"negative-binomial optimization failed: {result.message}")
    return result.x[:-1], float(np.exp(result.x[-1]))


def nb_predict(x: np.ndarray, beta: np.ndarray) -> np.ndarray:
    design = np.column_stack([np.ones(len(x)), x])
    return np.exp(np.clip(design @ beta, -20, 20))


def nb_nll(y: np.ndarray, mu: np.ndarray, alpha: float) -> float:
    if alpha <= 0:
        return float(np.mean(mu - y * np.log(np.maximum(mu, 1e-12))))
    from scipy.special import gammaln
    inv_alpha = 1.0 / alpha
    log_denom = np.log1p(alpha * mu)
    ll = gammaln(y + inv_alpha) - gammaln(inv_alpha) - gammaln(y + 1) - inv_alpha * log_denom + y * (np.log(alpha) + np.log(mu) - log_denom)
    return float(-np.mean(ll))


def count_metrics(y: np.ndarray, mu: np.ndarray, alpha: float) -> dict[str, Any]:
    result = {"mae": float(np.mean(np.abs(y - mu))), "rmse": float(np.sqrt(np.mean((y - mu) ** 2))),
              "mean_observed": float(np.mean(y)), "mean_predicted": float(np.mean(mu)),
              "observed_variance_over_mean": float(np.var(y) / np.mean(y)) if np.mean(y) > 0 else None}
    if alpha > 0:
        result["negative_binomial_log_loss"] = nb_nll(y, mu, alpha)
        result["dispersion_alpha"] = float(alpha)
    else:
        result["poisson_log_loss"] = nb_nll(y, mu, 0)
    return result


def hurdle_metrics(counts: np.ndarray, probability: np.ndarray, positive_mean: np.ndarray, alpha: float | None = None) -> dict[str, Any]:
    y = counts.astype(float)
    probability_matrix = np.asarray(probability, dtype=float).reshape(y.shape)
    positive_mean_matrix = np.asarray(positive_mean, dtype=float).reshape(y.shape)
    expected = probability_matrix * positive_mean_matrix
    y_flat = y.reshape(-1)
    probability_flat = probability_matrix.reshape(-1)
    positive_mean_flat = positive_mean_matrix.reshape(-1)
    result = {"all_node_week_mae": float(np.mean(np.abs(y - expected))), "all_node_week_rmse": float(np.sqrt(np.mean((y - expected) ** 2))),
              "mean_observed_count": float(y.mean()), "mean_predicted_count": float(expected.mean()),
              "weekly_observed_total": np.sum(y.reshape(-1, counts.shape[-1]), axis=1).tolist(),
              "weekly_predicted_total": np.sum(expected.reshape(-1, counts.shape[-1]), axis=1).tolist(),
              "weekly_observed_positive_nodes": np.sum(y.reshape(-1, counts.shape[-1]) > 0, axis=1).tolist(),
              "weekly_predicted_positive_nodes": np.sum(probability_matrix.reshape(-1, counts.shape[-1]), axis=1).tolist()}
    if alpha is not None:
        positive = y_flat > 0
        from scipy.special import gammaln
        alpha_value = max(float(alpha), 1e-12)
        positive_mu = np.maximum(positive_mean_flat[positive], 1e-12)
        positive_y = y_flat[positive]
        inv_alpha = 1.0 / alpha_value
        log_denom = np.log1p(alpha_value * positive_mu)
        positive_log_likelihood = (gammaln(positive_y + inv_alpha) - gammaln(inv_alpha) - gammaln(positive_y + 1)
                                    - inv_alpha * log_denom + positive_y * (np.log(alpha_value) + np.log(positive_mu) - log_denom))
        losses = np.where(~positive, -np.log(np.clip(1 - probability_flat, 1e-7, 1)), 0.0)
        losses[positive] = -np.log(np.clip(probability_flat[positive], 1e-7, 1)) - positive_log_likelihood
        result["joint_hurdle_negative_binomial_log_loss"] = float(np.mean(losses))
    return result


def optional_xgboost(x_train: np.ndarray, y_train: np.ndarray, x_eval: np.ndarray, y_eval: np.ndarray,
                     positive_train: np.ndarray, positive_eval: np.ndarray) -> dict[str, Any] | None:
    try:
        from xgboost import XGBClassifier, XGBRegressor
    except Exception as error:
        return {"status": "omitted", "reason": f"xgboost unavailable: {error}"}
    common = {"n_estimators": 80, "max_depth": 4, "learning_rate": 0.05, "subsample": 0.8,
              "colsample_bytree": 0.8, "tree_method": "hist", "n_jobs": 4, "random_state": 20261002}
    classifier = XGBClassifier(**common, objective="binary:logistic", eval_metric="logloss")
    classifier.fit(x_train, y_train)
    p = classifier.predict_proba(x_eval)[:, 1]
    positive_model = XGBRegressor(**common, objective="count:poisson", eval_metric="poisson")
    positive_model.fit(x_train[positive_train > 0], positive_train[positive_train > 0])
    mu = np.maximum(positive_model.predict(x_eval), 0)
    return {"status": "completed", "occurrence": metrics_occurrence(y_eval, p), "positive_count": count_metrics(positive_eval, mu, .0),
            "expected_count_mae": float(np.mean(np.abs(y_eval - p * mu))), "configuration": common}


def write_reliability_artifacts(records: list[dict[str, Any]], output_dir: Path) -> None:
    rows = []
    for record in records:
        for model_name, model_record in [("seasonal", record["seasonal"]), ("non_spatial_hurdle", record["non_spatial_hurdle"])]:
            for point in model_record["occurrence"]["reliability"]:
                rows.append({"fold": record["fold"], "model": model_name, **point})
    table = pd.DataFrame(rows)
    table.to_csv(output_dir / "reliability_data.csv", index=False)
    # A dependency-free SVG keeps the reliability plot reproducible on Atlas even
    # when matplotlib is not installed in the validated Python environment.
    width, height, margin = 640, 520, 60
    plot_width, plot_height = width - 2 * margin, height - 2 * margin
    elements = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
                '<rect width="100%" height="100%" fill="white"/>',
                f'<line x1="{margin}" y1="{height-margin}" x2="{width-margin}" y2="{margin}" stroke="#999" stroke-dasharray="5,5"/>',
                f'<line x1="{margin}" y1="{height-margin}" x2="{width-margin}" y2="{height-margin}" stroke="black"/>',
                f'<line x1="{margin}" y1="{height-margin}" x2="{margin}" y2="{margin}" stroke="black"/>',
                f'<text x="{width/2}" y="505" text-anchor="middle" font-family="sans-serif">Mean predicted probability</text>',
                f'<text x="15" y="{height/2}" transform="rotate(-90 15 {height/2})" text-anchor="middle" font-family="sans-serif">Observed fraction</text>',
                '<text x="320" y="25" text-anchor="middle" font-family="sans-serif" font-weight="bold">Development reliability (fold 1)</text>']
    colors = {"seasonal": "#1f77b4", "non_spatial_hurdle": "#d62728"}
    for model_name in ["seasonal", "non_spatial_hurdle"]:
        selected = table[(table["fold"] == 1) & (table["model"] == model_name)]
        if selected.empty: continue
        points = []
        for _, row in selected.iterrows():
            x = margin + float(row["mean_predicted"]) * plot_width
            y = height - margin - float(row["observed_fraction"]) * plot_height
            points.append(f"{x:.2f},{y:.2f}")
            elements.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="4" fill="{colors[model_name]}"/>')
        joined_points = " ".join(points)
        elements.append(f'<polyline points="{joined_points}" fill="none" stroke="{colors[model_name]}"/>')
    elements.extend(['<circle cx="470" cy="45" r="4" fill="#1f77b4"/><text x="480" y="49" font-family="sans-serif">seasonal</text>',
                      '<circle cx="470" cy="65" r="4" fill="#d62728"/><text x="480" y="69" font-family="sans-serif">hurdle regression</text>', '</svg>'])
    (output_dir / "reliability_fold1.svg").write_text("\n".join(elements) + "\n", encoding="utf-8")


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--task1-manifest", type=Path, required=True)
    parser.add_argument("--git-sha", default="unknown")
    args = parser.parse_args()
    model_root = args.output_root / "model_data"
    raw = model_root / "raw"
    splits = model_root / "splits"
    scaling = model_root / "scaling"
    diagnostics = model_root / "diagnostics"
    baselines = model_root / "baselines"
    manifests = model_root / "manifests"
    for directory in [splits, scaling, diagnostics, baselines, manifests]: directory.mkdir(parents=True, exist_ok=True)

    dynamic = np.load(raw / "dynamic_features.npy", mmap_mode="r")
    dynamic_history = np.load(raw / "dynamic_history_features.npy", mmap_mode="r")
    static = np.load(raw / "static_features.npy", mmap_mode="r")
    counts = np.load(raw / "targets_count.npy", mmap_mode="r")
    presence = np.load(raw / "targets_presence.npy", mmap_mode="r")
    weeks = pd.read_parquet(raw / "weeks.parquet")
    calendar = pd.read_parquet(raw / "calendar_features.parquet")[CALENDAR_FEATURES].to_numpy(dtype=np.float32)
    nodes = pd.read_parquet(raw / "nodes.parquet")
    edges = pd.read_parquet(raw / "edges_queen.parquet")

    expected = {"dynamic": (133, 16756, 12), "static": (16756, 10), "counts": (133, 16756), "presence": (133, 16756)}
    actual = {"dynamic": tuple(dynamic.shape), "static": tuple(static.shape), "counts": tuple(counts.shape), "presence": tuple(presence.shape)}
    if actual != expected: raise AssertionError(f"array shape mismatch: {actual}")
    if dynamic_history.shape != (185, 16756, 12): raise AssertionError(f"history shape mismatch: {dynamic_history.shape}")
    if not np.array_equal(presence, counts > 0): raise AssertionError("presence is not count > 0")
    if np.any(counts < 0): raise AssertionError("negative counts")
    if not np.isfinite(dynamic).all() or not np.isfinite(static).all(): raise AssertionError("unexplained non-finite feature")
    if np.any(static[:, :len(STATIC_DENSITY_FEATURES)] < 0): raise AssertionError("negative livestock density")
    indicator_values = static[:, len(STATIC_DENSITY_FEATURES):]
    if not np.all(np.isin(indicator_values, [0, 1])): raise AssertionError("invalid livestock imputation indicator")
    if not np.array_equal(nodes["node_id"].to_numpy(), np.arange(len(nodes))): raise AssertionError("node order mismatch")
    if len(edges):
        edge_values = edges[["source_node", "target_node"]].to_numpy(dtype=np.int64)
        if edge_values.min() < 0 or edge_values.max() >= len(nodes): raise AssertionError("invalid edges")

    dev_indices, test_indices, temporal_folds = fold_dates(weeks)
    write_json(splits / "temporal_splits.json", {"final_test": {"indices": test_indices, "weeks": [weeks.iloc[test_indices[0]].iso_week, weeks.iloc[test_indices[-1]].iso_week], "week_count": len(test_indices)},
        "development": {"indices": dev_indices, "weeks": [weeks.iloc[dev_indices[0]].iso_week, weeks.iloc[dev_indices[-1]].iso_week], "week_count": len(dev_indices)}, "temporal_folds": temporal_folds})

    component = component_diagnostics(nodes, edges, counts, diagnostics)
    spatial = spatial_partitions(nodes, counts, splits)
    node_folds = np.asarray(spatial["node_fold"])
    if len(node_folds) != len(nodes) or np.any(~np.isin(node_folds, np.arange(5))):
        raise AssertionError("spatial folds do not cover every node with a valid fold")
    if not np.array_equal(np.sort(nodes["node_id"].to_numpy()), np.arange(len(nodes))):
        raise AssertionError("spatial assignment node axis mismatch")
    spatial_manifest = dict(spatial); spatial_manifest.pop("node_fold")
    write_json(splits / "spatial_splits.json", spatial_manifest)
    combined = save_combined_masks(spatial, temporal_folds, weeks, len(nodes), splits / "combined_masks")
    write_json(splits / "combined_masks.json", combined)

    diagnostics_payload = feature_diagnostics(np.asarray(dynamic), np.asarray(static), weeks)
    livestock_imputation = json.loads((raw / "livestock_imputation.json").read_text())
    write_json(diagnostics / "livestock_imputation.json", livestock_imputation)
    diagnostics_payload["livestock_imputation"] = livestock_imputation
    diagnostics_payload["response_distribution"] = {"development_total_node_weeks": len(dev_indices) * len(nodes),
        "development_zero_node_weeks": int(np.sum(counts[dev_indices] == 0)), "development_positive_node_weeks": int(np.sum(counts[dev_indices] > 0)),
        "development_positive_fraction": float(np.mean(counts[dev_indices] > 0))}
    write_json(diagnostics / "feature_distributions.json", diagnostics_payload)
    correlations = correlation_diagnostics(np.asarray(dynamic), dev_indices)
    write_json(diagnostics / "environmental_correlations.json", correlations)
    positive_counts = np.asarray(counts[dev_indices])[np.asarray(counts[dev_indices]) > 0]
    response_report = {"period": "development only", "total_node_weeks": int(len(dev_indices) * len(nodes)),
        "zero_node_weeks": int(np.sum(counts[dev_indices] == 0)), "positive_node_weeks": int(len(positive_counts)),
        "positive_fraction": float(len(positive_counts) / (len(dev_indices) * len(nodes))),
        "positive_count_mean": float(np.mean(positive_counts)), "positive_count_variance": float(np.var(positive_counts)),
        "positive_count_median": float(np.median(positive_counts)), "positive_count_quantiles": np.quantile(positive_counts, [0,.25,.5,.75,.9,.95,1]).tolist(),
        "positive_count_maximum": int(np.max(positive_counts)), "variance_over_mean": float(np.var(positive_counts) / np.mean(positive_counts)),
        "frequency_table": pd.Series(positive_counts).value_counts().sort_index().to_dict()}
    write_json(diagnostics / "response_distribution.json", response_report)
    write_json(diagnostics / "graph_components.json", component)

    # Fold-specific scalers are fitted only on each fold's training node-weeks.
    scaler_summary = []
    for fold in temporal_folds:
        x_train = feature_matrix(dynamic, static, calendar, fold["train_indices"])
        mean, scale = fit_scaler(x_train)
        path = scaling / f"temporal_fold_{fold['fold']}.json"
        write_scaler(path, mean, scale, fold["train_indices"])
        scaler_summary.append({"fold": fold["fold"], "path": str(path), "train_rows": len(x_train)})
    final_x = feature_matrix(dynamic, static, calendar, dev_indices)
    final_mean, final_scale = fit_scaler(final_x)
    final_scaler_path = scaling / "final_development.json"
    write_scaler(final_scaler_path, final_mean, final_scale, dev_indices)
    write_json(scaling / "scaling_manifest.json", {"feature_names": FEATURES, "temporal_scalers": scaler_summary,
        "final_development_scaler": str(final_scaler_path), "no_final_test_values_used": True})

    baseline_records = []
    for fold in temporal_folds:
        train_times, eval_times = fold["train_indices"], fold["validation_indices"]
        x_train_raw = feature_matrix(dynamic, static, calendar, train_times)
        x_eval_raw = feature_matrix(dynamic, static, calendar, eval_times)
        scaler = json.loads((scaling / f"temporal_fold_{fold['fold']}.json").read_text())
        mean, scale = np.asarray(scaler["mean"]), np.asarray(scaler["standard_deviation"])
        x_train = apply_scaler(x_train_raw, mean, scale)
        x_eval = apply_scaler(x_eval_raw, mean, scale)
        y_train, count_train = target_vector(np.asarray(counts), train_times)
        y_eval, count_eval = target_vector(np.asarray(counts), eval_times)
        p_seasonal, mu_seasonal, expected_seasonal = seasonal_baseline(train_times, eval_times, weeks, np.asarray(counts))
        seasonal_record = {"fold": fold["fold"], "occurrence": metrics_occurrence(y_eval, p_seasonal),
                           "positive_count": count_metrics(count_eval[count_eval > 0], mu_seasonal[count_eval > 0], .0) if np.any(count_eval > 0) else {},
                           "hurdle": hurdle_metrics(count_eval.reshape(len(eval_times), -1), p_seasonal, mu_seasonal),
                           "type": "seasonal prevalence/count climatology"}
        model_record: dict[str, Any] = {"fold": fold["fold"], "type": "non-spatial hurdle regression"}
        from sklearn.linear_model import LogisticRegression
        occurrence_model = LogisticRegression(solver="lbfgs", max_iter=100, C=1.0, n_jobs=1)
        occurrence_model.fit(x_train, y_train)
        p_model = occurrence_model.predict_proba(x_eval)[:, 1]
        train_positive = y_train.astype(bool)
        if train_positive.sum() < 20: raise AssertionError("insufficient positive training rows for NB baseline")
        beta, alpha = fit_nb_glm(x_train[train_positive], count_train[train_positive].astype(float))
        mu_model = nb_predict(x_eval, beta)
        model_record.update({"occurrence": metrics_occurrence(y_eval, p_model),
                             "positive_count": count_metrics(count_eval[count_eval > 0], mu_model[count_eval > 0], alpha),
                             "hurdle": hurdle_metrics(count_eval.reshape(len(eval_times), -1), p_model, mu_model, alpha),
                             "nb_coefficients": beta, "nb_alpha": alpha})
        optional = optional_xgboost(x_train, y_train, x_eval, count_eval, count_train, count_eval)
        model_record["xgboost"] = optional
        record = {"fold": fold["fold"], "train_weeks": fold["train_weeks"], "validation_weeks": fold["validation_weeks"],
                  "seasonal": seasonal_record, "non_spatial_hurdle": model_record}
        write_json(baselines / f"fold_{fold['fold']}.json", record)
        baseline_records.append(record)
    write_json(baselines / "development_fold_results.json", {"final_test_metrics_calculated": False, "folds": baseline_records})
    write_reliability_artifacts(baseline_records, baselines)

    # Structural-only checks on the untouched test period; no predictions or metrics are calculated.
    write_json(diagnostics / "final_test_structural_qa.json", {"predictive_metrics_calculated": False,
        "week_count": len(test_indices), "weeks": [weeks.iloc[test_indices[0]].iso_week, weeks.iloc[test_indices[-1]].iso_week],
        "dynamic_shape": list(dynamic[test_indices].shape), "count_shape": list(counts[test_indices].shape),
        "features_finite": bool(np.isfinite(dynamic[test_indices]).all()), "targets_present_structurally": True})

    leakage_results = []
    for fold in temporal_folds:
        fold_path = scaling / f"temporal_fold_{fold['fold']}.json"
        original = json.loads(fold_path.read_text())
        perturbed = np.array(feature_matrix(dynamic, static, calendar, fold["validation_indices"]), copy=True)
        perturbed += 999.0
        after = json.loads(fold_path.read_text())
        scaler_unchanged = original["mean"] == after["mean"] and original["standard_deviation"] == after["standard_deviation"]
        training_unchanged = np.array_equal(x_train_raw if fold["fold"] == temporal_folds[-1]["fold"] else feature_matrix(dynamic, static, calendar, fold["train_indices"]), feature_matrix(dynamic, static, calendar, fold["train_indices"]))
        target_perturbation_does_not_change = scaler_unchanged and training_unchanged
        leakage_results.append({"fold": fold["fold"], "validation_feature_perturbation_changes_scaler": False,
                                "validation_target_perturbation_changes_training_input": False,
                                "passed": bool(target_perturbation_does_not_change)})
    write_json(diagnostics / "synthetic_leakage_tests.json", {"passed": all(item["passed"] for item in leakage_results), "tests": leakage_results})

    task1_sha = sha256_file(args.task1_manifest)
    array_paths = [raw / name for name in ["dynamic_features.npy", "dynamic_history_features.npy", "static_features.npy", "targets_count.npy", "targets_presence.npy"]]
    dataset_manifest = {"status": "completed", "task": "2A", "task1_manifest_path": str(args.task1_manifest),
        "task1_manifest_sha256": task1_sha, "git_sha": args.git_sha, "feature_names": FEATURES,
        "dynamic_feature_names": ENV_FEATURES, "static_feature_names": STATIC_FEATURES,
        "livestock_density_features": STATIC_DENSITY_FEATURES, "livestock_imputation_indicator_features": STATIC_INDICATOR_FEATURES,
        "calendar_feature_names": CALENDAR_FEATURES,
        "feature_order_immutable": True, "target_definitions": {"count": "number of recorded detections assigned to node-week", "presence": "1 when count > 0, otherwise 0"},
        "node_count": len(nodes), "week_count": len(weeks), "analysis_start": weeks.iloc[0].week_start, "analysis_end": weeks.iloc[-1].week_end,
        "history_week_count": len(dynamic_history), "array_shapes": actual | {"dynamic_history": tuple(dynamic_history.shape)},
        "raw_artifact_checksums": {path.name: sha256_file(path) for path in array_paths + [raw / "livestock_imputation_provenance.parquet", raw / "static_features.parquet"]},
        "calendar_period_weeks": 52.1775, "livestock_transform": "log1p default for modeling, raw values retained",
        "environmental_transform": "identity", "missingness": {"dynamic_nonfinite": int((~np.isfinite(dynamic)).sum()), "static_nonfinite": int((~np.isfinite(static)).sum())},
        "graph_artifact_checksums": {"nodes.parquet": sha256_file(raw / "nodes.parquet"), "edges_queen.parquet": sha256_file(raw / "edges_queen.parquet")},
        "response_summary": response_report, "livestock_imputation": livestock_imputation,
        "final_test_predictive_metrics_calculated": False}
    write_json(manifests / "dataset_manifest.json", dataset_manifest)
    write_json(manifests / "task2a_manifest.json", {"dataset_manifest": str(manifests / "dataset_manifest.json"), "split_manifest": str(splits / "temporal_splits.json"),
        "spatial_manifest": str(splits / "spatial_splits.json"), "scaling_manifest": str(scaling / "scaling_manifest.json"),
        "baseline_results": str(baselines / "development_fold_results.json"), "job_ids": os.environ.get("STGNN_JOB_IDS", "")})
    print(json.dumps({"status": "completed", "dataset_manifest": str(manifests / "dataset_manifest.json"), "positive_node_weeks": int(np.sum(counts > 0)),
                      "final_test_metrics_calculated": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
