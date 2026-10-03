#!/usr/bin/env python3
"""Task 2E development-only revised-domain baseline evaluation.

This script consumes the refreshed 2025-W01--2026-W29 production dataset,
fits prevalence, seasonal-climatology, and current-week exact-joint hurdle
baselines, and evaluates only the four temporal development folds plus the
development-period spatial validation.  The terminal holdout is never scored.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.special import digamma, expit, gammaln
from scipy.optimize import minimize

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT / "python"))
from task2c_metrics import evaluate_predictions


ENV_FEATURES = [
    "era5_mintemp", "era5_soilmoist", "era5_lai_low", "agera5_relhum_min",
    "era5land_tmean", "era5land_soiltemp_l1_mean", "era5land_soiltemp_l2_mean",
    "era5land_soilwater_l1_mean", "era5land_soilwater_l2_mean",
    "era5land_surface_pressure_mean", "era5land_lai_high_mean", "era5land_lai_low_mean",
]
DENSITY_FEATURES = ["cattle_density", "goat_density", "sheep_density", "horse_density", "pig_density"]
INDICATOR_FEATURES = [f"{name}_imputed" for name in DENSITY_FEATURES]
CALENDAR_FEATURES = ["week_sin", "week_cos"]
FEATURES = ENV_FEATURES + DENSITY_FEATURES + INDICATOR_FEATURES + CALENDAR_FEATURES
PERIOD = 52.1775
EPS = 1e-8


def jsonable(value: Any) -> Any:
    if isinstance(value, (np.integer,)): return int(value)
    if isinstance(value, (np.floating,)): return None if not np.isfinite(value) else float(value)
    if isinstance(value, np.ndarray): return value.tolist()
    if isinstance(value, dict): return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [jsonable(v) for v in value]
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(jsonable(value), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_data(root: Path) -> dict[str, Any]:
    raw = root / "raw"
    return {
        "root": root,
        "dynamic": np.load(raw / "dynamic_features.npy", mmap_mode="r"),
        "history": np.load(raw / "dynamic_history_features.npy", mmap_mode="r"),
        "static": np.load(raw / "static_features.npy", mmap_mode="r"),
        "counts": np.load(raw / "targets_count.npy", mmap_mode="r"),
        "presence": np.load(raw / "targets_presence.npy", mmap_mode="r"),
        "weeks": pd.read_parquet(raw / "weeks.parquet"),
        "calendar": pd.read_parquet(raw / "calendar_features.parquet")[CALENDAR_FEATURES].to_numpy(np.float64),
        "nodes": pd.read_parquet(raw / "nodes.parquet"),
        "edges": pd.read_parquet(raw / "edges_queen.parquet"),
        "splits": json.loads((root / "splits/temporal_splits.json").read_text()),
        "spatial": pd.read_parquet(root / "splits/spatial_node_assignments.parquet"),
        "manifest": json.loads((root / "manifests/revised_production_manifest.json").read_text()),
    }


def assert_contract(data: dict[str, Any]) -> None:
    expected = {
        "dynamic": (81, 10037, 12), "history": (185, 10037, 12),
        "static": (10037, 10), "counts": (81, 10037), "presence": (81, 10037),
    }
    actual = {key: tuple(data[key].shape) for key in expected}
    if actual != expected:
        raise AssertionError(f"refreshed shape mismatch: {actual}")
    if not np.array_equal(np.asarray(data["presence"]), np.asarray(data["counts"]) > 0):
        raise AssertionError("presence does not equal count > 0")
    if np.any(np.asarray(data["counts"]) < 0):
        raise AssertionError("negative target count")
    if not np.isfinite(np.asarray(data["dynamic"])).all() or not np.isfinite(np.asarray(data["static"])).all():
        raise AssertionError("non-finite predictor")
    if not np.all(np.asarray(data["static"])[:, :5] >= 0):
        raise AssertionError("negative livestock density")
    if not np.all(np.isin(np.asarray(data["static"])[:, 5:], [0, 1])):
        raise AssertionError("invalid livestock indicator")
    nodes = data["nodes"]["model_node_id"].to_numpy()
    if not np.array_equal(nodes, np.arange(10037)):
        raise AssertionError("model node IDs are not zero-based contiguous")
    edges = data["edges"][["source_node", "target_node"]].to_numpy(np.int64)
    if edges.size and (edges.min() < 0 or edges.max() >= 10037):
        raise AssertionError("edge index out of bounds")
    if int(data["splits"]["response_week_count"]) != 81:
        raise AssertionError("response period is not 81 weeks")
    holdout = np.asarray(data["splits"]["final_test"]["indices"], dtype=np.int64)
    if not np.array_equal(holdout, np.arange(68, 81)):
        raise AssertionError("terminal holdout indices are not 2026-W17--2026-W29")


def assert_development_only(indices: list[int] | np.ndarray, splits: dict[str, Any]) -> None:
    holdout = set(int(i) for i in splits["final_test"]["indices"])
    if any(int(i) in holdout for i in indices):
        raise RuntimeError("development evaluation attempted to access terminal holdout")


def feature_matrix(data: dict[str, Any], times: list[int] | np.ndarray, nodes: np.ndarray | None = None) -> np.ndarray:
    times = np.asarray(times, dtype=np.int64)
    node_ids = np.arange(data["static"].shape[0], dtype=np.int64) if nodes is None else np.asarray(nodes, dtype=np.int64)
    dynamic = np.asarray(data["dynamic"][np.ix_(times, node_ids)], dtype=np.float64).reshape(-1, 12)
    static = np.asarray(data["static"][node_ids], dtype=np.float64)
    static = np.concatenate([np.log1p(static[:, :5]), static[:, 5:]], axis=1)
    static_rows = np.tile(static, (len(times), 1))
    calendar_rows = np.repeat(np.asarray(data["calendar"])[times], len(node_ids), axis=0)
    return np.concatenate([dynamic, static_rows, calendar_rows], axis=1)


def target_matrix(data: dict[str, Any], times: list[int] | np.ndarray, nodes: np.ndarray | None = None) -> np.ndarray:
    times = np.asarray(times, dtype=np.int64)
    if nodes is None:
        return np.asarray(data["counts"][times], dtype=np.int64)
    return np.asarray(data["counts"][np.ix_(times, np.asarray(nodes, dtype=np.int64))], dtype=np.int64)


def fit_preprocessor(data: dict[str, Any], train_times: list[int], train_nodes: np.ndarray | None = None) -> dict[str, Any]:
    x = feature_matrix(data, train_times, train_nodes)
    mean = x.mean(axis=0, dtype=np.float64)
    scale = x.std(axis=0, dtype=np.float64)
    mean[17:] = 0.0
    scale[17:] = 1.0
    scale[:17][~np.isfinite(scale[:17]) | (scale[:17] == 0)] = 1.0
    return {
        "feature_names": FEATURES,
        "transform": {name: ("log1p" if name in DENSITY_FEATURES else "identity") for name in FEATURES},
        "training_week_indices": [int(x) for x in train_times],
        "training_node_count": int(data["static"].shape[0] if train_nodes is None else len(train_nodes)),
        "mean": mean.tolist(), "standard_deviation": scale.tolist(),
        "indicators_unscaled": True, "calendar_unscaled": True,
    }


def apply_preprocessor(x: np.ndarray, prep: dict[str, Any]) -> np.ndarray:
    mean = np.asarray(prep["mean"], dtype=np.float64)
    scale = np.asarray(prep["standard_deviation"], dtype=np.float64)
    return (x - mean[None, :]) / scale[None, :]


def add_intercept(x: np.ndarray) -> np.ndarray:
    return np.column_stack([np.ones(x.shape[0], dtype=np.float64), x])


def logistic_objective(beta: np.ndarray, x: np.ndarray, y: np.ndarray) -> tuple[float, np.ndarray]:
    z = np.clip(x @ beta, -40.0, 40.0)
    loss = np.mean(np.logaddexp(0.0, z) - y * z)
    p = expit(z)
    gradient = (x.T @ (p - y)) / y.size
    return float(loss), gradient


def zt_nb_objective(params: np.ndarray, x: np.ndarray, y: np.ndarray) -> tuple[float, np.ndarray]:
    beta = params[:-1]
    theta = float(np.exp(np.clip(params[-1], -12.0, 12.0)))
    log_mu = np.clip(x @ beta, -20.0, 20.0)
    mu = np.exp(log_mu)
    log_theta = math.log(theta)
    denom = theta + mu
    log_p0 = theta * (log_theta - np.log(denom))
    p0 = np.exp(np.minimum(log_p0, 0.0))
    p_positive = np.maximum(-np.expm1(log_p0), EPS)
    logpmf = (gammaln(y + theta) - gammaln(theta) - gammaln(y + 1.0)
              + theta * (log_theta - np.log(denom))
              + y * (log_mu - np.log(denom)))
    zt_logpmf = logpmf - np.log(p_positive)
    loss = -float(np.mean(zt_logpmf))

    dlogpmf_dz = y - (theta + y) * mu / denom
    dlogp0_dz = -theta * mu / denom
    dlogpositive_dz = -(p0 / p_positive) * dlogp0_dz
    dzt_dz = dlogpmf_dz - dlogpositive_dz
    grad_beta = -(x.T @ dzt_dz) / y.size

    dlogpmf_dtheta = (digamma(y + theta) - digamma(theta) + log_theta + 1.0
                      - np.log(denom) - (theta + y) / denom)
    dlogp0_dtheta = log_theta + 1.0 - np.log(denom) - theta / denom
    dlogpositive_dtheta = -(p0 / p_positive) * dlogp0_dtheta
    dzt_dtheta = dlogpmf_dtheta - dlogpositive_dtheta
    grad_log_theta = -float(np.mean(dzt_dtheta * theta))
    return loss, np.concatenate([grad_beta, [grad_log_theta]])


class ExactHurdleRegressor:
    def __init__(self, maxiter: int = 500) -> None:
        self.maxiter = maxiter
        self.occurrence_beta: np.ndarray | None = None
        self.count_beta: np.ndarray | None = None
        self.theta: float | None = None
        self.fit_info: dict[str, Any] = {}

    def fit(self, x: np.ndarray, counts: np.ndarray) -> "ExactHurdleRegressor":
        y = (np.asarray(counts, dtype=np.int64) > 0).astype(np.float64)
        positive = np.asarray(counts, dtype=np.float64) > 0
        if not positive.any() or positive.all():
            raise ValueError("hurdle fit requires both zero and positive observations")
        x_design = add_intercept(x)
        occurrence = minimize(lambda b: logistic_objective(b, x_design, y), np.zeros(x_design.shape[1]), jac=True,
                              method="L-BFGS-B", options={"maxiter": self.maxiter, "ftol": 1e-10, "gtol": 1e-7})
        x_pos = x_design[positive]
        y_pos = np.asarray(counts, dtype=np.float64)[positive]
        mean_pos = max(float(y_pos.mean()), 1e-3)
        variance = float(y_pos.var())
        theta0 = max(mean_pos * mean_pos / max(variance - mean_pos, 1e-6), 0.1)
        count_start = np.zeros(x_design.shape[1] + 1, dtype=np.float64)
        count_start[0] = math.log(mean_pos)
        count_start[-1] = math.log(theta0)
        count = minimize(lambda b: zt_nb_objective(b, x_pos, y_pos), count_start, jac=True,
                         method="L-BFGS-B", options={"maxiter": self.maxiter, "ftol": 1e-10, "gtol": 1e-7, "maxls": 40})
        self.occurrence_beta = occurrence.x
        self.count_beta = count.x[:-1]
        self.theta = float(np.exp(np.clip(count.x[-1], -12.0, 12.0)))
        self.fit_info = {
            "objective": "exact_joint_hurdle_nll",
            "occurrence_success": bool(occurrence.success), "occurrence_message": str(occurrence.message),
            "occurrence_iterations": int(occurrence.nit), "occurrence_nll": float(occurrence.fun),
            "count_success": bool(count.success), "count_message": str(count.message),
            "count_iterations": int(count.nit), "zt_nb_nll_training_positive": float(count.fun),
            "theta": self.theta, "training_rows": int(len(counts)), "training_positive_rows": int(positive.sum()),
        }
        return self

    def predict(self, x: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
        if self.occurrence_beta is None or self.count_beta is None or self.theta is None:
            raise RuntimeError("model has not been fitted")
        x_design = add_intercept(x)
        p = expit(np.clip(x_design @ self.occurrence_beta, -40.0, 40.0))
        mu = np.exp(np.clip(x_design @ self.count_beta, -20.0, 20.0))
        log_p0 = self.theta * (math.log(self.theta) - np.log(self.theta + mu))
        conditional = mu / np.maximum(-np.expm1(log_p0), EPS)
        return p, conditional, mu, self.theta


def safe_metrics(counts: np.ndarray, p: np.ndarray, conditional: np.ndarray, mu: np.ndarray,
                 theta: float, train_prevalence: float, region: str, fold: int, model: str) -> dict[str, Any]:
    y = np.asarray(counts, dtype=np.int64)
    positive = y > 0
    result = evaluate_predictions(y, p, conditional, mu, theta, training_prevalence=train_prevalence, count_score_family="zt_nb")
    if int(positive.sum()) == 0 or int((~positive).sum()) == 0:
        result["pr_auc"] = None
        result["pr_auc_over_prevalence"] = None
        result["roc_auc"] = None
        result["calibration_intercept"] = None
        result["calibration_slope"] = None
        result["regional_metric_note"] = "PR-AUC/ROC-AUC not defined or informative because the regional target lacks both classes"
    result.update({"fold": int(fold), "model": model, "region": region, "positive_count": int(positive.sum()), "negative_count": int((~positive).sum())})
    return result


def seasonal_predictions(data: dict[str, Any], train_times: list[int], eval_times: list[int]) -> tuple[np.ndarray, np.ndarray, float, float, dict[str, Any]]:
    counts = np.asarray(data["counts"], dtype=np.int64)
    week_numbers = pd.to_datetime(data["weeks"]["week_start"]).dt.isocalendar().week.to_numpy(np.int64)
    train = counts[np.asarray(train_times)]
    train_presence = train > 0
    global_p = float(train_presence.mean())
    global_cond = float(train[train_presence].mean()) if train_presence.any() else 1.0
    stats: dict[str, Any] = {}
    prior = 10.0
    p_by_week: dict[int, float] = {}
    mu_by_week: dict[int, float] = {}
    for week in sorted(set(int(x) for x in week_numbers)):
        rows = train[np.array([week_numbers[t] == week for t in train_times])]
        pres = rows > 0
        p_by_week[week] = float((pres.sum() + prior * global_p) / (pres.size + prior))
        cond = float(rows[pres].mean()) if pres.any() else global_cond
        mu_by_week[week] = float((cond * pres.sum() + prior * global_cond) / (pres.sum() + prior)) if pres.any() else global_cond
        stats[str(week)] = {"n": int(pres.size), "positive": int(pres.sum()), "probability": p_by_week[week], "conditional_mean": mu_by_week[week], "pooling_prior": prior}
    p = np.concatenate([np.full(counts.shape[1], p_by_week[int(week_numbers[t])]) for t in eval_times])
    mu = np.concatenate([np.full(counts.shape[1], mu_by_week[int(week_numbers[t])]) for t in eval_times])
    return p, mu, global_p, global_cond, {"pooling": "10 pseudo-node-weeks toward the global training stratum; global conditional mean when a week has no positive training count", "strata": stats}


def season_labels(weeks: pd.DataFrame) -> np.ndarray:
    months = pd.to_datetime(weeks["week_start"]).dt.month.to_numpy()
    return np.where(np.isin(months, [12, 1, 2]), "winter", np.where(np.isin(months, [3, 4, 5]), "spring", np.where(np.isin(months, [6, 7, 8]), "summer", "fall")))


def flatten_metric_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keys = sorted({key for record in records for key in record.keys()} | {key for record in records for key in record.get("metrics", {}).keys()})
    rows = []
    for record in records:
        row = {key: record.get(key) for key in keys if key != "metrics"}
        row.update(record.get("metrics", {}))
        rows.append(row)
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("\n", encoding="utf-8")
        return
    fields = sorted({key for row in rows for key in row.keys()})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def save_prediction(path: Path, eval_indices: list[int], y: np.ndarray, p: np.ndarray, cond: np.ndarray, mu: np.ndarray, theta: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, week_index=np.asarray(eval_indices, dtype=np.int16), counts=np.asarray(y, dtype=np.int16), observed_presence=(np.asarray(y) > 0).astype(np.int8), predicted_occurrence_probability=np.asarray(p, dtype=np.float32), predicted_conditional_mean=np.asarray(cond, dtype=np.float32), predicted_underlying_mu=np.asarray(mu, dtype=np.float32), predicted_unconditional_mean=(np.asarray(p) * np.asarray(cond)).astype(np.float32), theta=np.float32(theta))


def regional_records(data: dict[str, Any], eval_times: list[int], p_matrix: np.ndarray, cond_matrix: np.ndarray, mu_matrix: np.ndarray, theta: float, train_prevalence: float, fold: int, model: str) -> list[dict[str, Any]]:
    regions = {
        "full_revised_domain": np.ones(10037, dtype=bool),
        "Mexico": data["nodes"]["country_or_domain_region"].to_numpy() == "Mexico",
        "U.S.": data["nodes"]["country_or_domain_region"].to_numpy() == "U.S.-to-40N",
    }
    y_matrix = target_matrix(data, eval_times)
    result = []
    for region, mask in regions.items():
        result.append({"metrics": safe_metrics(y_matrix[:, mask], p_matrix[:, mask], cond_matrix[:, mask], mu_matrix[:, mask], theta, train_prevalence, region, fold, model), "fold": fold, "model": model, "region": region})
    return result


def temporal_evaluation(data: dict[str, Any], output: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    seasonal_records: list[dict[str, Any]] = []
    regional_records_all: list[dict[str, Any]] = []
    latitude_records: list[dict[str, Any]] = []
    coefficient_records: list[dict[str, Any]] = []
    us_records: list[dict[str, Any]] = []
    labels = data["weeks"]["iso_week"].astype(str).to_numpy()
    seasons = season_labels(data["weeks"])
    region_labels = data["nodes"]["country_or_domain_region"].to_numpy()
    latitudes = data["nodes"]["lat"].to_numpy(float)
    latitude_bands = pd.cut(latitudes, [-np.inf, 20, 25, 30, 35, 40], labels=["<20N", "20-25N", "25-30N", "30-35N", "35-40N"], right=False)

    for fold_record in data["splits"]["temporal_folds"]:
        fold = int(fold_record["fold"])
        train_times = [int(x) for x in fold_record["train_indices"]]
        eval_times = [int(x) for x in fold_record["validation_indices"]]
        assert_development_only(train_times + eval_times, data["splits"])
        prep = fit_preprocessor(data, train_times)
        write_json(output / "scaling" / f"temporal_fold_{fold}.json", prep)
        x_train = apply_preprocessor(feature_matrix(data, train_times), prep)
        x_eval = apply_preprocessor(feature_matrix(data, eval_times), prep)
        y_train_matrix = target_matrix(data, train_times)
        y_eval_matrix = target_matrix(data, eval_times)
        y_train = y_train_matrix.reshape(-1)
        y_eval = y_eval_matrix.reshape(-1)
        train_prev = float(np.mean(y_train > 0))
        train_cond = float(y_train[y_train > 0].mean())

        p_null = np.full(y_eval.shape, train_prev, dtype=float)
        mu_null = np.full(y_eval.shape, train_cond, dtype=float)
        null_metrics = safe_metrics(y_eval, p_null, mu_null, mu_null, 1e6, train_prev, "full_revised_domain", fold, "prevalence_null")
        records.append({"fold": fold, "model": "prevalence_null", "loss_objective": "not_applicable", "metrics": null_metrics})

        p_seasonal, mu_seasonal, _, _, seasonal_meta = seasonal_predictions(data, train_times, eval_times)
        seasonal_metrics = safe_metrics(y_eval, p_seasonal, mu_seasonal, mu_seasonal, 1e6, train_prev, "full_revised_domain", fold, "seasonal_climatology")
        records.append({"fold": fold, "model": "seasonal_climatology", "loss_objective": "not_applicable", "metrics": seasonal_metrics})
        write_json(output / "diagnostics" / f"seasonal_climatology_fold{fold}.json", seasonal_meta)

        model = ExactHurdleRegressor().fit(x_train, y_train)
        p, conditional, mu, theta = model.predict(x_eval)
        p_matrix = p.reshape(y_eval_matrix.shape)
        conditional_matrix = conditional.reshape(y_eval_matrix.shape)
        mu_matrix = mu.reshape(y_eval_matrix.shape)
        hurdle_metrics = safe_metrics(y_eval_matrix, p_matrix, conditional_matrix, mu_matrix, theta, train_prev, "full_revised_domain", fold, "current_week_exact_hurdle")
        records.append({"fold": fold, "model": "current_week_exact_hurdle", "loss_objective": "exact_joint_hurdle_nll", "metrics": hurdle_metrics, "fit_info": model.fit_info})
        save_prediction(output / "predictions" / "temporal" / f"current_week_exact_hurdle_fold{fold}.npz", eval_times, y_eval_matrix, p_matrix, conditional_matrix, mu_matrix, theta)
        regional_records_all.extend(regional_records(data, eval_times, p_matrix, conditional_matrix, mu_matrix, theta, train_prev, fold, "current_week_exact_hurdle"))

        for component, coefficients in [("occurrence", model.occurrence_beta), ("positive_count", model.count_beta)]:
            coefficient_records.append({"fold": fold, "component": component, "feature": "intercept", "coefficient_standardized": float(coefficients[0]), "sign": "positive" if coefficients[0] > 0 else ("negative" if coefficients[0] < 0 else "zero"), "absolute_magnitude": abs(float(coefficients[0]))})
            for feature, coefficient in zip(FEATURES, coefficients[1:]):
                coefficient_records.append({"fold": fold, "component": component, "feature": feature, "coefficient_standardized": float(coefficient), "sign": "positive" if coefficient > 0 else ("negative" if coefficient < 0 else "zero"), "absolute_magnitude": abs(float(coefficient))})

        for season in ["winter", "spring", "summer", "fall"]:
            mask_time = np.array([seasons[t] == season for t in eval_times])
            y = y_eval_matrix[mask_time]
            pm = p_matrix[mask_time]
            cm = conditional_matrix[mask_time]
            mum = mu_matrix[mask_time]
            if y.size:
                seasonal_records.append({"fold": fold, "model": "current_week_exact_hurdle", "season": season, "metrics": safe_metrics(y, pm, cm, mum, theta, train_prev, "full_revised_domain", fold, "current_week_exact_hurdle")})

        northmost = float(np.max(latitudes[np.any(y_eval_matrix > 0, axis=0)])) if np.any(y_eval_matrix > 0) else None
        for band in ["<20N", "20-25N", "25-30N", "30-35N", "35-40N"]:
            mask_nodes = np.asarray(latitude_bands == band)
            y = y_eval_matrix[:, mask_nodes]
            pm = p_matrix[:, mask_nodes]
            cm = conditional_matrix[:, mask_nodes]
            mum = mu_matrix[:, mask_nodes]
            if y.size:
                latitude_records.append({"fold": fold, "latitude_band": band, "observed_northernmost_positive_latitude": northmost, "metrics": safe_metrics(y, pm, cm, mum, theta, train_prev, "full_revised_domain", fold, "current_week_exact_hurdle")})

        us_mask = region_labels == "U.S.-to-40N"
        us_y = y_eval_matrix[:, us_mask]
        us_p = p_matrix[:, us_mask]
        if us_y.size:
            positive_p = us_p[us_y > 0]
            zero_p = us_p[us_y == 0]
            all_p = us_p.reshape(-1)
            us_records.append({"fold": fold, "evaluated_us_node_weeks": int(us_y.size), "positive_us_node_weeks": int((us_y > 0).sum()), "positive_probability_mean": float(positive_p.mean()) if positive_p.size else None, "positive_probability_median": float(np.median(positive_p)) if positive_p.size else None, "zero_probability_mean": float(zero_p.mean()) if zero_p.size else None, "zero_probability_median": float(np.median(zero_p)) if zero_p.size else None, "positive_probability_percentile_among_us_predictions": [float(np.mean(all_p <= value) * 100) for value in positive_p] if positive_p.size else [], "validation_weeks": [labels[eval_times[0]], labels[eval_times[-1]]]})

    return records, seasonal_records, regional_records_all, latitude_records, coefficient_records, us_records


def spatial_evaluation(data: dict[str, Any], output: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    dev_times = list(range(68))
    assert_development_only(dev_times, data["splits"])
    spatial_fold_values = data["spatial"]["spatial_fold"].to_numpy(int)
    region_labels = data["nodes"]["country_or_domain_region"].to_numpy()
    for spatial_fold in sorted(np.unique(spatial_fold_values)):
        train_nodes = np.flatnonzero(spatial_fold_values != spatial_fold)
        eval_nodes = np.flatnonzero(spatial_fold_values == spatial_fold)
        prep = fit_preprocessor(data, dev_times, train_nodes)
        write_json(output / "scaling" / f"spatial_fold_{spatial_fold}.json", prep)
        x_train = apply_preprocessor(feature_matrix(data, dev_times, train_nodes), prep)
        x_eval = apply_preprocessor(feature_matrix(data, dev_times, eval_nodes), prep)
        y_train = target_matrix(data, dev_times, train_nodes).reshape(-1)
        y_eval = target_matrix(data, dev_times, eval_nodes)
        train_prev = float(np.mean(y_train > 0))
        model = ExactHurdleRegressor().fit(x_train, y_train)
        p, cond, mu, theta = model.predict(x_eval)
        p_matrix, cond_matrix, mu_matrix = p.reshape(y_eval.shape), cond.reshape(y_eval.shape), mu.reshape(y_eval.shape)
        result = safe_metrics(y_eval, p_matrix, cond_matrix, mu_matrix, theta, train_prev, "spatial_holdout_nodes", int(spatial_fold), "current_week_exact_hurdle")
        result["spatial_fold"] = int(spatial_fold)
        result["evaluated_nodes"] = int(len(eval_nodes))
        records.append(result)
        for region in ["Mexico", "U.S."]:
            mask = region_labels[eval_nodes] == ("Mexico" if region == "Mexico" else "U.S.-to-40N")
            if mask.any():
                regional = safe_metrics(y_eval[:, mask], p_matrix[:, mask], cond_matrix[:, mask], mu_matrix[:, mask], theta, train_prev, region, int(spatial_fold), "current_week_exact_hurdle")
                regional.update({"spatial_fold": int(spatial_fold), "evaluated_nodes": int(mask.sum())})
                records.append(regional)
    return records


def classify_advancement(records: list[dict[str, Any]], spatial: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    hurdle = [r for r in records if r.get("model") == "current_week_exact_hurdle" and r["metrics"].get("region") == "full_revised_domain"]
    fold4 = next((r for r in hurdle if int(r["fold"]) == 4), None)
    spatial_full = [r for r in spatial if r.get("region") == "spatial_holdout_nodes"]
    stable = all(bool(r.get("fit_info", {}).get("occurrence_success", True)) and bool(r.get("fit_info", {}).get("count_success", True)) for r in records if r.get("model") == "current_week_exact_hurdle")
    positive_skill = bool(hurdle) and float(np.mean([r["metrics"].get("brier_skill", -np.inf) for r in hurdle])) > 0.0
    fold4_ok = fold4 is not None and float(fold4["metrics"].get("brier_skill", -np.inf)) > -0.25
    spatial_ok = bool(spatial_full) and float(np.mean([r.get("brier_skill", -np.inf) for r in spatial_full])) > -0.25
    if stable and positive_skill and fold4_ok and spatial_ok:
        decision = "ADVANCE"
    elif stable and (positive_skill or fold4_ok or spatial_ok):
        decision = "HOLD"
    else:
        decision = "RETHINK OBSERVATION MODEL"
    evidence = {"stable_optimization": stable, "mean_temporal_brier_skill_positive": positive_skill, "fold4_non_catastrophic": fold4_ok, "spatial_validation_non_catastrophic": spatial_ok, "decision_rule": "ADVANCE requires stable optimization, positive mean Brier skill, non-catastrophic Fold 4, and non-catastrophic spatial development validation; otherwise HOLD if partial evidence remains, else RETHINK OBSERVATION MODEL"}
    return decision, evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-output", type=Path, required=True)
    args = parser.parse_args()
    data = load_data(args.model_output)
    assert_contract(data)
    output = args.model_output
    started = time.time()
    records, seasonal, regional, latitude, coefficients, us = temporal_evaluation(data, output)
    spatial = spatial_evaluation(data, output)
    decision, evidence = classify_advancement(records, spatial)

    write_json(output / "validation" / "task2e_baseline_results.json", {"evaluation_mode": "development", "terminal_holdout_metrics_calculated": False, "records": records, "seasonal_records": seasonal, "regional_records": regional, "latitude_records": latitude, "us_case_diagnostics": us, "spatial_records": spatial, "advancement_classification": decision, "advancement_evidence": evidence, "runtime_seconds": time.time() - started})
    write_csv(output / "validation" / "task2e_baseline_metrics.csv", flatten_metric_records(records))
    write_csv(output / "validation" / "task2e_regional_metrics.csv", flatten_metric_records(regional))
    write_csv(output / "validation" / "task2e_seasonal_metrics.csv", flatten_metric_records(seasonal))
    write_csv(output / "validation" / "task2e_latitude_metrics.csv", flatten_metric_records(latitude))
    write_csv(output / "validation" / "task2e_spatial_metrics.csv", spatial)
    write_csv(output / "validation" / "task2e_coefficients.csv", coefficients)
    write_csv(output / "validation" / "task2e_us_case_diagnostics.csv", us)

    manifest_path = output / "manifests/revised_production_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest.update({"status": "completed_development_baselines", "predictive_models_fitted": True, "terminal_holdout_metrics_calculated": False, "baseline_results": {"metrics": str(output / "validation/task2e_baseline_metrics.csv"), "regional": str(output / "validation/task2e_regional_metrics.csv"), "seasonal": str(output / "validation/task2e_seasonal_metrics.csv"), "spatial": str(output / "validation/task2e_spatial_metrics.csv"), "coefficients": str(output / "validation/task2e_coefficients.csv"), "us_case_diagnostics": str(output / "validation/task2e_us_case_diagnostics.csv")}, "advancement_classification": decision, "advancement_evidence": evidence, "terminal_holdout_guard": "development evaluation rejects indices 68:80"})
    write_json(manifest_path, manifest)
    write_json(output / "manifests/task2e_baseline_manifest.json", {"task": "2E", "evaluation_mode": "development", "models": ["prevalence_null", "seasonal_climatology", "current_week_exact_hurdle"], "loss_objective": "exact_joint_hurdle_nll", "terminal_holdout_metrics_calculated": False, "advancement_classification": decision, "advancement_evidence": evidence, "temporal_fold_count": 4, "spatial_fold_count": len(np.unique(data["spatial"]["spatial_fold"]))})
    print(json.dumps({"status": "completed", "advancement_classification": decision, "temporal_records": len(records), "spatial_records": len(spatial), "terminal_holdout_metrics_calculated": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
