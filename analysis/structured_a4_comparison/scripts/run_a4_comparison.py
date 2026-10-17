#!/usr/bin/env python3
"""Controlled A4 architecture comparison on pre-W30 development folds.

This script deliberately evaluates only the authorized structured candidates:
the fixed Structured A3 reference, a graph-Laplacian residual extension, a
positive-count dispersion revision, their combination, and a bounded
observation/reporting sensitivity analysis.  It never loads the W30--W39
prospective archive and never writes to production or authoritative A3 roots.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import platform
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import minimize, minimize_scalar
from scipy.sparse import coo_matrix, eye
from scipy.sparse.csgraph import connected_components
from scipy.sparse.linalg import cg
from scipy.special import expit, gammaln


REPOSITORY_ROOT = Path(os.environ.get("A4_REPOSITORY_ROOT", Path(__file__).resolve().parents[3])).resolve()
BASELINE_SHA = "fae2d0f08c72a018338b9359543cfd2b88d7d8e2"
NODE_COUNT = 10_037
DEVELOPMENT_WEEKS = 68
PROSPECTIVE_WEEKS = tuple(f"2026-W{week:02d}" for week in range(30, 40))
FOLD_IDS = (1, 2, 3, 4)
EPS = 1e-12


def load_augmentation_module():
    path = REPOSITORY_ROOT / "analysis" / "predictor_augmentation" / "scripts" / "run_predictor_augmentation.py"
    spec = importlib.util.spec_from_file_location("validated_structured_augmentation", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import validated structured fitter: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


AUG = load_augmentation_module()


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
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(jsonable(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git_head(root: Path) -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    except Exception:
        return "unknown"


def read_config(path: Path) -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8"))
    if config["baseline_repository_sha"] != BASELINE_SHA:
        raise RuntimeError("A4 config baseline SHA does not match the canonical A3 merge SHA")
    if tuple(config["development_period"]["excluded_prospective_weeks"]) != PROSPECTIVE_WEEKS:
        raise RuntimeError("A4 config does not exclude exactly 2026-W30 through 2026-W39")
    if set(config["candidate_scope"]["run"]) != {"A3", "A4-S", "A4-C", "A4-SC", "A4-O"}:
        raise RuntimeError("A4 candidate scope changed unexpectedly")
    if config["sit"]["included"]:
        raise RuntimeError("SIT covariates are forbidden in this A4 phase")
    return config


def safe_float(value: Any) -> float | None:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if np.isfinite(value) else None


def load_static_added(soil_path: Path, anthropogenic_path: Path, nodes: pd.DataFrame) -> tuple[np.ndarray, dict[str, Any]]:
    soil = AUG.validate_nodes(AUG.read_table(soil_path))
    anthropogenic = AUG.validate_nodes(AUG.read_table(anthropogenic_path))
    soil_sources: dict[str, str] = {}
    for feature in ("clay_0_15", "water_difference_wv0033_minus_wv0010_0_15"):
        source = feature if feature in soil.columns else f"{feature}__mean"
        if source not in soil.columns:
            raise RuntimeError(f"Missing authorized soil feature {feature}")
        soil_sources[feature] = source
    for feature in ("road_density", "night_illumination"):
        if feature not in anthropogenic.columns:
            raise RuntimeError(f"Missing authorized anthropogenic feature {feature}")
    joined = nodes[["model_node_id"]].merge(
        soil[["model_node_id", *soil_sources.values()]].rename(columns={v: k for k, v in soil_sources.items()}),
        on="model_node_id", how="left", validate="one_to_one",
    ).merge(
        anthropogenic[["model_node_id", "road_density", "night_illumination"]],
        on="model_node_id", how="left", validate="one_to_one",
    )
    if len(joined) != NODE_COUNT or not np.array_equal(joined["model_node_id"].to_numpy(np.int64), np.arange(NODE_COUNT)):
        raise RuntimeError("Static A3 join failed canonical node ordering")
    raw = joined[["road_density", "night_illumination", "clay_0_15", "water_difference_wv0033_minus_wv0010_0_15"]].to_numpy(np.float64)
    if not np.isfinite(raw).all() or (raw[:, :2] < 0).any():
        raise RuntimeError("Authorized static A3 features contain missing/non-finite/negative values")
    raw[:, :2] = np.log1p(raw[:, :2])
    return raw, {"soil_sources": soil_sources, "transformations": {"road_density": "log1p", "night_illumination": "log1p", "clay_0_15": "identity", "water_difference_wv0033_minus_wv0010_0_15": "identity"}}


def load_graph(path: Path) -> tuple[Any, pd.DataFrame]:
    edges = pd.read_parquet(path)
    source = pd.to_numeric(edges["source_node"], errors="raise").to_numpy(np.int64)
    target = pd.to_numeric(edges["target_node"], errors="raise").to_numpy(np.int64)
    if ((source < 0) | (source >= NODE_COUNT) | (target < 0) | (target >= NODE_COUNT)).any():
        raise RuntimeError("Graph edge IDs fall outside the canonical node domain")
    keep = source != target
    source, target = source[keep], target[keep]
    rows = np.concatenate([source, target])
    cols = np.concatenate([target, source])
    adjacency = coo_matrix((np.ones(len(rows), dtype=np.float64), (rows, cols)), shape=(NODE_COUNT, NODE_COUNT)).tocsr()
    adjacency.data[:] = 1.0
    adjacency.eliminate_zeros()
    degree = np.asarray(adjacency.sum(axis=1)).ravel()
    diagonal = coo_matrix((degree, (np.arange(NODE_COUNT), np.arange(NODE_COUNT))), shape=(NODE_COUNT, NODE_COUNT)).tocsc()
    laplacian = diagonal - adjacency.tocsc()
    return adjacency, laplacian


def inventory_observation_process(observation_path: Path, nodes: pd.DataFrame) -> pd.DataFrame:
    columns = pd.read_csv(observation_path, nrows=0).columns.tolist()
    observations = pd.read_csv(observation_path, usecols=columns)
    rows: list[dict[str, Any]] = []

    def add(proxy: str, source: str, spatial: str, temporal: str, missingness: str, relationship: str, usable: str, concern: str) -> None:
        rows.append({
            "candidate_proxy": proxy, "source": source, "spatial_resolution": spatial,
            "temporal_resolution": temporal, "missingness": missingness,
            "likely_relationship_to_reporting": relationship, "usable_now": usable,
            "identifiability_concern": concern,
        })

    add("date", str(observation_path), "point event", "daily/event", f"{observations['date'].isna().mean():.6f}", "event timing but not effort", "no", "No denominator or sampling intensity is recorded.")
    add("host", str(observation_path), "point event", "event", f"{observations['host'].isna().mean():.6f}", "host composition may affect detection", "no", "Host type is not an observation-effort measure.")
    add("lon/lat", str(observation_path), "point event", "event", f"{observations[['lon', 'lat']].isna().any(axis=1).mean():.6f}", "event location", "no", "Location does not identify searched-but-negative areas.")
    add("country_or_domain_region", "revised_model_data/raw/nodes.parquet", "10,037 nodes", "static", "0.000000", "geographic stratification only", "no", "Region is not surveillance effort and is confounded with intervention context.")
    for proxy in ("surveillance_jurisdiction", "reporting_source", "sampling_program", "inspection_effort", "reporting_frequency_metadata", "administrative_unit", "accessibility_proxy"):
        add(proxy, "searched authorized observation/node inputs", "not available", "not available", "not available", "potential effort proxy", "no", "No field or authorized derived artifact was present in the inventoried inputs.")
    return pd.DataFrame(rows)


def logit(probability: np.ndarray) -> np.ndarray:
    p = np.clip(np.asarray(probability, dtype=np.float64), 1e-10, 1.0 - 1e-10)
    return np.log(p) - np.log1p(-p)


def regularized_logistic_objective(beta: np.ndarray, x: np.ndarray, y: np.ndarray, penalty: float) -> tuple[float, np.ndarray]:
    z = np.clip(x @ beta, -40.0, 40.0)
    probability = expit(z)
    loss = float(np.mean(np.logaddexp(0.0, z) - y * z)) + 0.5 * penalty * float(np.sum(beta[1:] ** 2))
    gradient = (x.T @ (probability - y)) / y.size
    gradient = gradient.copy()
    gradient[1:] += penalty * beta[1:]
    return loss, gradient


def zt_nb_objective(beta: np.ndarray, x: np.ndarray, y: np.ndarray, theta: float, penalty: float) -> tuple[float, np.ndarray]:
    log_mu = np.clip(x @ beta, -20.0, 20.0)
    mu = np.exp(log_mu)
    denominator = theta + mu
    log_p0 = theta * (math.log(theta) - np.log(denominator))
    p0 = np.exp(np.minimum(log_p0, 0.0))
    p_positive = np.maximum(-np.expm1(log_p0), EPS)
    logpmf = gammaln(y + theta) - gammaln(theta) - gammaln(y + 1.0) + log_p0 + y * (log_mu - np.log(denominator))
    loss = -float(np.mean(logpmf - np.log(p_positive))) + 0.5 * penalty * float(np.sum(beta[1:] ** 2))
    dlogpmf_dz = y - (theta + y) * mu / denominator
    dlogp0_dz = -theta * mu / denominator
    dlogpositive_dz = -(p0 / p_positive) * dlogp0_dz
    gradient = -(x.T @ (dlogpmf_dz - dlogpositive_dz)) / y.size
    gradient = gradient.copy()
    gradient[1:] += penalty * beta[1:]
    return loss, gradient


def zt_nb_nll(y: np.ndarray, mu: np.ndarray, theta: float) -> float:
    y = np.asarray(y, dtype=np.float64)
    mu = np.maximum(np.asarray(mu, dtype=np.float64), EPS)
    denominator = theta + mu
    log_p0 = theta * (math.log(theta) - np.log(denominator))
    positive = np.maximum(-np.expm1(log_p0), EPS)
    logpmf = gammaln(y + theta) - gammaln(theta) - gammaln(y + 1.0) + log_p0 + y * (np.log(mu) - np.log(denominator))
    return float(-np.mean(logpmf - np.log(positive)))


def estimate_theta(positive_counts: np.ndarray, bounds: tuple[float, float]) -> tuple[float, dict[str, Any]]:
    y = np.asarray(positive_counts, dtype=np.float64)
    if len(y) < 2 or np.any(y <= 0):
        raise RuntimeError("A4-C theta estimation requires at least two positive counts")

    def profile(log_theta: float) -> float:
        theta = float(np.exp(log_theta))
        result = minimize_scalar(
            lambda intercept: zt_nb_nll(y, np.full(len(y), np.exp(np.clip(intercept, -20.0, 20.0))), theta),
            bounds=(-8.0, 8.0), method="bounded", options={"xatol": 1e-5},
        )
        return float(result.fun)

    lower, upper = bounds
    result = minimize_scalar(profile, bounds=(math.log(lower), math.log(upper)), method="bounded", options={"xatol": 1e-4})
    theta = float(np.clip(np.exp(result.x), lower, upper))
    return theta, {"success": bool(result.success), "iterations": int(getattr(result, "nfev", 0)), "objective": float(result.fun), "bounds": list(bounds)}


def fit_state(x_train: np.ndarray, counts_train: np.ndarray, theta: float, penalty: float) -> dict[str, Any]:
    y_occ = (np.asarray(counts_train, dtype=np.int64) > 0).astype(np.float64)
    positive = np.asarray(counts_train, dtype=np.float64) > 0
    if not positive.any() or positive.all():
        raise RuntimeError("Hurdle fit requires both zero and positive observations")
    design = np.column_stack([np.ones(len(x_train), dtype=np.float64), x_train])
    occurrence = minimize(
        lambda beta: regularized_logistic_objective(beta, design, y_occ, AUG.PENALTY),
        np.zeros(design.shape[1]), jac=True, method="L-BFGS-B",
        options={"maxiter": AUG.OPTIMIZER_MAXITER, "ftol": 1e-10, "gtol": 1e-7},
    )
    positive_design = design[positive]
    positive_counts = np.asarray(counts_train, dtype=np.float64)[positive]
    start = np.zeros(design.shape[1], dtype=np.float64)
    start[0] = math.log(max(float(positive_counts.mean()), 1e-3))
    count = minimize(
        lambda beta: zt_nb_objective(beta, positive_design, positive_counts, theta, penalty),
        start, jac=True, method="L-BFGS-B",
        options={"maxiter": AUG.OPTIMIZER_MAXITER, "ftol": 1e-10, "gtol": 1e-7, "maxls": 40},
    )
    if not occurrence.success or not count.success:
        raise RuntimeError(f"non-converged fit: occurrence={occurrence.message}; count={count.message}")
    return {
        "occurrence_beta": occurrence.x,
        "count_beta": count.x,
        "theta": float(theta),
        "fit_info": {
            "occurrence_success": bool(occurrence.success), "count_success": bool(count.success),
            "occurrence_iterations": int(occurrence.nit), "count_iterations": int(count.nit),
            "training_rows": int(len(counts_train)), "training_positive_rows": int(positive.sum()),
        },
    }


def predict_state(state: dict[str, Any], x: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    design = np.column_stack([np.ones(len(x), dtype=np.float64), x])
    probability = expit(np.clip(design @ state["occurrence_beta"], -40.0, 40.0))
    mu = np.exp(np.clip(design @ state["count_beta"], -20.0, 20.0))
    theta = float(state["theta"])
    log_p0 = theta * (math.log(theta) - np.log(theta + mu))
    conditional = mu / np.maximum(-np.expm1(log_p0), EPS)
    return probability, conditional, mu


def standardize(raw_train: np.ndarray, raw_eval: np.ndarray, feature_names: list[str]) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    mean = raw_train.mean(axis=0, dtype=np.float64)
    scale = raw_train.std(axis=0, dtype=np.float64)
    unscaled = [idx for idx, name in enumerate(feature_names) if name.endswith("_imputed") or name.endswith("_available") or name in AUG.CALENDAR_FEATURES]
    scaled = [idx for idx in range(len(feature_names)) if idx not in set(unscaled)]
    mean[unscaled] = 0.0
    scale[unscaled] = 1.0
    scale[scaled] = np.where(np.isfinite(scale[scaled]) & (scale[scaled] > 0), scale[scaled], 1.0)
    if not np.isfinite(mean).all() or not np.isfinite(scale).all():
        raise RuntimeError("Fold scaling is non-finite")
    info = {"feature_names": feature_names, "training_mean": mean.tolist(), "training_sd": scale.tolist(), "scaled_feature_indices": scaled, "unscaled_feature_indices": unscaled}
    return (raw_train - mean[None, :]) / scale[None, :], (raw_eval - mean[None, :]) / scale[None, :], info


def smooth_graph_effect(residual: np.ndarray, solver: Any, scale: float) -> np.ndarray:
    centered = np.asarray(residual, dtype=np.float64) - float(np.mean(residual))
    effect = np.asarray(solver(centered), dtype=np.float64)
    effect -= float(np.mean(effect))
    return effect * scale


def make_graph_solver(laplacian: Any, graph_lambda: float) -> Any:
    operator = (eye(NODE_COUNT, format="csr") + graph_lambda * laplacian.tocsr()).tocsr()

    def solve(rhs: np.ndarray) -> np.ndarray:
        result, info = cg(operator, np.asarray(rhs, dtype=np.float64), rtol=1e-8, atol=1e-10, maxiter=500)
        if info != 0:
            raise RuntimeError(f"graph-Laplacian residual solve did not converge: info={info}")
        return result

    return solve


def add_spatial_effects(
    state: dict[str, Any], x_train: np.ndarray, counts_train: np.ndarray, x_eval: np.ndarray,
    solver: Any, residual_scale: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, float]]:
    p_train, cond_train, _ = predict_state(state, x_train)
    p_eval, cond_eval, mu_eval = predict_state(state, x_eval)
    y_train = np.asarray(counts_train, dtype=np.float64)
    train_weeks = y_train.reshape(-1, NODE_COUNT)
    p_train_w = p_train.reshape(-1, NODE_COUNT)
    cond_train_w = cond_train.reshape(-1, NODE_COUNT)
    occurrence_effect = smooth_graph_effect((train_weeks > 0).mean(axis=0) - p_train_w.mean(axis=0), solver, residual_scale)
    positive_mask = train_weeks > 0
    log_residual = np.zeros_like(train_weeks, dtype=np.float64)
    log_residual[positive_mask] = np.log1p(train_weeks[positive_mask]) - np.log1p(cond_train_w[positive_mask])
    positive_counts = positive_mask.sum(axis=0)
    count_residual = np.divide(log_residual.sum(axis=0), positive_counts, out=np.zeros(NODE_COUNT), where=positive_counts > 0)
    count_effect = smooth_graph_effect(count_residual, solver, residual_scale)
    evaluation_weeks = len(x_eval) // NODE_COUNT
    p_eval = expit(logit(p_eval) + np.tile(occurrence_effect, evaluation_weeks))
    mu_eval = mu_eval * np.exp(np.tile(count_effect, evaluation_weeks))
    theta = float(state["theta"])
    log_p0 = theta * (math.log(theta) - np.log(theta + mu_eval))
    cond_eval = mu_eval / np.maximum(-np.expm1(log_p0), EPS)
    return p_eval, cond_eval, mu_eval, {"occurrence_effect_sd": float(np.std(occurrence_effect)), "count_effect_sd": float(np.std(count_effect)), "occurrence_effect_max_abs": float(np.max(np.abs(occurrence_effect))), "count_effect_max_abs": float(np.max(np.abs(count_effect)))}


def calibration_fit(probability: np.ndarray, observed: np.ndarray) -> tuple[float | None, float | None]:
    p = np.asarray(probability, dtype=np.float64)
    y = np.asarray(observed, dtype=np.float64)
    if len(np.unique(y)) < 2 or len(y) < 20:
        return None, None
    design = np.column_stack([np.ones(len(p)), logit(p)])
    result = minimize(lambda beta: (float(np.mean(np.logaddexp(0.0, design @ beta) - y * (design @ beta))), design.T @ (expit(design @ beta) - y) / len(y)), np.zeros(2), jac=True, method="BFGS")
    if not result.success and not np.isfinite(result.fun):
        return None, None
    return float(result.x[0]), float(result.x[1])


def candidate_metrics(y: np.ndarray, p: np.ndarray, conditional: np.ndarray, mu: np.ndarray, theta: float, training_prevalence: float) -> dict[str, Any]:
    metrics = dict(AUG.evaluate_predictions(y, p, conditional, mu, theta, training_prevalence=training_prevalence, count_score_family="zt_nb"))
    positive = np.asarray(y) > 0
    metrics["zt_nb_nll"] = zt_nb_nll(np.asarray(y)[positive], np.asarray(mu)[positive], theta) if positive.any() else None
    metrics["observed_positive_mean"] = float(np.mean(y[positive])) if positive.any() else None
    metrics["predicted_conditional_mean"] = float(np.mean(conditional[positive])) if positive.any() else None
    metrics["count_bias"] = float(np.mean(conditional[positive]) - np.mean(y[positive])) if positive.any() else None
    metrics["conditional_mean_bias"] = metrics["count_bias"]
    metrics["predicted_expected_total"] = float(np.sum(p * conditional))
    metrics["observed_total"] = int(np.sum(y))
    for key, value in list(metrics.items()):
        metrics[key] = safe_float(value) if isinstance(value, (float, np.floating, int, np.integer)) else value
    return metrics


def moran_i(values: np.ndarray, adjacency: Any) -> float | None:
    x = np.asarray(values, dtype=np.float64)
    x = x[np.isfinite(x)]
    if len(x) != NODE_COUNT:
        return None
    centered = x - float(x.mean())
    denominator = float(centered @ centered)
    weight_sum = float(adjacency.sum())
    if denominator <= 0 or weight_sum <= 0:
        return None
    return float((NODE_COUNT / weight_sum) * (centered @ (adjacency @ centered)) / denominator)


def moran_with_permutation(values: np.ndarray, adjacency: Any, count: int, seed: int) -> tuple[float | None, float | None]:
    observed = moran_i(values, adjacency)
    if observed is None:
        return None, None
    rng = np.random.default_rng(seed)
    x = np.asarray(values, dtype=np.float64)
    permutations = []
    for _ in range(count):
        permutations.append(moran_i(rng.permutation(x), adjacency))
    finite = np.asarray([value for value in permutations if value is not None], dtype=np.float64)
    p_value = float((1 + np.sum(np.abs(finite) >= abs(observed))) / (len(finite) + 1))
    return float(observed), p_value


def aggregate_node(values: np.ndarray, node_ids: np.ndarray, mask: np.ndarray | None = None) -> np.ndarray:
    values = np.asarray(values, dtype=np.float64)
    node_ids = np.asarray(node_ids, dtype=np.int64)
    if mask is None:
        mask = np.ones(len(values), dtype=bool)
    totals = np.bincount(node_ids[mask], weights=values[mask], minlength=NODE_COUNT)
    counts = np.bincount(node_ids[mask], minlength=NODE_COUNT)
    return np.divide(totals, counts, out=np.zeros(NODE_COUNT), where=counts > 0)


def residual_clusters(values: np.ndarray, adjacency: Any, nodes: pd.DataFrame, candidate: str, residual_name: str) -> list[dict[str, Any]]:
    absolute = np.abs(values)
    threshold = float(np.quantile(absolute, 0.95))
    rows: list[dict[str, Any]] = []
    for sign, mask in (("positive", values >= threshold), ("negative", values <= -threshold)):
        if not mask.any():
            continue
        sub = adjacency[mask][:, mask]
        n_components, labels = connected_components(sub, directed=False)
        for label in range(n_components):
            member = np.flatnonzero(mask)[labels == label]
            if len(member) == 0:
                continue
            row = nodes.iloc[member]
            rows.append({"candidate": candidate, "residual": residual_name, "sign": sign, "cluster_size": int(len(member)), "mean_residual": float(values[member].mean()), "max_abs_residual": float(np.max(np.abs(values[member]))), "centroid_lon": float(row["lon"].mean()), "centroid_lat": float(row["lat"].mean())})
    return sorted(rows, key=lambda item: (-item["cluster_size"], -item["max_abs_residual"]))[:10]


def rank_metrics(predictions: dict[str, np.ndarray], nodes: pd.DataFrame) -> dict[str, Any]:
    us = nodes["country_or_domain_region"].astype(str).eq("U.S.-to-40N").to_numpy()
    rows: list[dict[str, Any]] = []
    for candidate, arrays in predictions.items():
        p = arrays["p"]
        y = arrays["y"]
        weeks = arrays["week_index"]
        node_ids = arrays["node_id"]
        percentiles: list[float] = []
        for week in np.unique(weeks):
            mask = (weeks == week) & us[node_ids]
            values = p[mask]
            positives = y[mask] > 0
            if positives.any():
                order = np.argsort(np.argsort(values, kind="mergesort"), kind="mergesort") + 1
                percentiles.extend((100.0 * order[positives] / len(values)).tolist())
        positive_mask = y > 0
        positive_percentiles = np.asarray(percentiles, dtype=np.float64)
        base = {"candidate": candidate, "us_positive_node_weeks": int(len(positive_percentiles)), "us_unique_positive_nodes": int(len(np.unique(node_ids[positive_mask & us[node_ids]]))), "us_median_positive_percentile": safe_float(np.median(positive_percentiles)) if len(positive_percentiles) else None, "us_mean_positive_percentile": safe_float(np.mean(positive_percentiles)) if len(positive_percentiles) else None}
        for cutoff in (50, 75, 90, 95):
            base[f"us_positive_percentile_ge_{cutoff}"] = safe_float(np.mean(positive_percentiles >= cutoff)) if len(positive_percentiles) else None
        for k in (0.01, 0.05, 0.10, 0.20):
            captured = 0
            flagged = 0
            total_positive = 0
            for week in np.unique(weeks):
                mask = (weeks == week) & us[node_ids]
                values, observed = p[mask], y[mask] > 0
                if len(values) == 0:
                    continue
                n_flag = max(1, int(math.ceil(k * len(values))))
                top = np.argsort(values, kind="mergesort")[-n_flag:]
                captured += int(observed[top].sum())
                flagged += n_flag
                total_positive += int(observed.sum())
            rows.append({**base, "row_type": "overall_top_k", "top_k": k, "flagged_node_weeks": flagged, "positives_captured": captured, "precision": safe_float(captured / flagged) if flagged else None, "recall": safe_float(captured / total_positive) if total_positive else None})
        rows.append({**base, "row_type": "overall_positive_summary", "top_k": None, "flagged_node_weeks": None, "positives_captured": None, "precision": None, "recall": None})
    return pd.DataFrame(rows)


def extrapolation_labels(raw_train: np.ndarray, raw_eval: np.ndarray, feature_names: list[str]) -> dict[str, np.ndarray]:
    result: dict[str, np.ndarray] = {}
    for feature in ("distance_to_any_prior_positive_log1p", "weeks_since_detection_within_50km_log1p"):
        idx = feature_names.index(feature)
        train = raw_train[:, idx]
        values = raw_eval[:, idx]
        mean, sd = float(train.mean()), float(train.std())
        z = np.abs((values - mean) / max(sd, EPS))
        outside = (values < float(train.min())) | (values > float(train.max()))
        result[feature] = np.where((z > 3) | outside, "strong", np.where(z > 2, "moderate", "in_distribution"))
    result["combined_history"] = np.where((result[next(iter(result))] == "strong") | (result["weeks_since_detection_within_50km_log1p"] == "strong"), "strong", np.where((result[next(iter(result))] == "moderate") | (result["weeks_since_detection_within_50km_log1p"] == "moderate"), "moderate", "in_distribution"))
    return result


def metric_dict_for_frame(y: np.ndarray, p: np.ndarray, conditional: np.ndarray, mu: np.ndarray, theta: float, training_prevalence: float) -> dict[str, Any]:
    return candidate_metrics(y, p, conditional, mu, theta, training_prevalence)


@dataclass
class DataBundle:
    a3: np.ndarray
    counts: np.ndarray
    nodes: pd.DataFrame
    weeks: pd.DataFrame
    folds: list[dict[str, Any]]
    adjacency: Any
    laplacian: Any
    paths: dict[str, Path]
    feature_names: list[str]
    hashes: dict[str, str]


def load_data(args: argparse.Namespace, config: dict[str, Any]) -> DataBundle:
    base, counts, nodes, metadata = AUG.load_base(args.model_output, args.front_features)
    added, _ = load_static_added(args.soil_features, args.anthropogenic_features, nodes)
    a3 = np.concatenate([base, np.broadcast_to(added[None, :, :], (DEVELOPMENT_WEEKS, NODE_COUNT, added.shape[1]))], axis=2)
    if a3.shape != (DEVELOPMENT_WEEKS, NODE_COUNT, 34):
        raise RuntimeError(f"A3 matrix shape changed: {a3.shape}")
    weeks = pd.read_parquet(args.model_output / "raw/weeks.parquet")
    labels = weeks["iso_week"].astype(str).tolist()
    if labels[:DEVELOPMENT_WEEKS] != [f"2025-W{week:02d}" for week in range(1, 53)] + [f"2026-W{week:02d}" for week in range(1, 17)]:
        raise RuntimeError("Development week boundary is not exactly 2025-W01 through 2026-W16")
    if set(labels[:DEVELOPMENT_WEEKS]).intersection(PROSPECTIVE_WEEKS):
        raise RuntimeError("Prospective W30-W39 appears in the fitting array")
    folds = metadata["folds"]
    if [int(item["fold"]) for item in folds] != list(FOLD_IDS) or any(max(item["validation_indices"]) >= DEVELOPMENT_WEEKS for item in folds):
        raise RuntimeError("A4 folds are not the authorized F1-F4 pre-W30 folds")
    adjacency, laplacian = load_graph(args.edges)
    paths = {
        "model_manifest": args.model_output / "manifests/revised_production_manifest.json",
        "dynamic_features": args.model_output / "raw/dynamic_features.npy",
        "static_features": args.model_output / "raw/static_features.npy",
        "targets_count": args.model_output / "raw/targets_count.npy",
        "weeks": args.model_output / "raw/weeks.parquet",
        "nodes": args.model_output / "raw/nodes.parquet",
        "edges": args.edges,
        "causal_front_features": args.front_features,
        "soil_features": args.soil_features,
        "anthropogenic_features": args.anthropogenic_features,
        "observation_source": args.observation_source,
        "a3_fold_reference": args.a3_fold_reference,
        "config": args.config,
    }
    hashes = {key: sha256_file(path) for key, path in paths.items() if path.exists()}
    return DataBundle(a3=a3, counts=np.asarray(counts, dtype=np.int64), nodes=nodes, weeks=weeks, folds=folds, adjacency=adjacency, laplacian=laplacian, paths=paths, feature_names=AUG.BASE_FEATURES + AUG.ADDED_FEATURES, hashes=hashes)


def fit_candidate(candidate: str, raw_train: np.ndarray, y_train: np.ndarray, raw_eval: np.ndarray, solver: Any, config: dict[str, Any]) -> tuple[dict[str, Any], np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    theta_a3 = float(config["model"]["theta_a3"])
    penalty = float(config["model"]["penalty_a3"])
    theta = theta_a3
    x_train, x_eval, scaling = standardize(raw_train, raw_eval, AUG.BASE_FEATURES + AUG.ADDED_FEATURES)
    base_state = fit_state(x_train, y_train, theta_a3, penalty)
    theta_info: dict[str, Any] = {"theta": theta_a3, "theta_source": "frozen_a3"}
    if candidate in {"A4-C", "A4-SC"}:
        positive = y_train > 0
        theta, theta_info = estimate_theta(y_train[positive], tuple(config["model"]["a4_c_theta_bounds"]))
        count_state = fit_state(x_train, y_train, theta, float(config["model"]["a4_c_penalty"]))
        count_state["occurrence_beta"] = base_state["occurrence_beta"]
        base_state = count_state
        theta_info["theta_source"] = "training_positive_count_profile_likelihood"
    p_eval, cond_eval, mu_eval = predict_state(base_state, x_eval)
    spatial_info: dict[str, Any] = {"spatial_component": False}
    if candidate in {"A4-S", "A4-SC"}:
        p_eval, cond_eval, mu_eval, spatial_info = add_spatial_effects(
            base_state, x_train, y_train, x_eval, solver,
            float(config["a4_s"]["residual_scale"]),
        )
        spatial_info["spatial_component"] = True
    fit_info = {**base_state["fit_info"], **theta_info, **spatial_info, "scaling": scaling}
    return base_state, p_eval, cond_eval, mu_eval, fit_info


def run_oof(data: DataBundle, config: dict[str, Any], output: Path) -> tuple[dict[str, dict[str, np.ndarray]], pd.DataFrame, pd.DataFrame]:
    candidates = ["A3", "A4-S", "A4-C", "A4-SC"]
    predictions: dict[str, dict[str, list[np.ndarray]]] = {candidate: {key: [] for key in ("y", "p", "conditional", "mu", "week_index", "node_id", "fold")} for candidate in candidates}
    fold_rows: list[dict[str, Any]] = []
    extrap_rows: list[dict[str, Any]] = []
    solver = make_graph_solver(data.laplacian, float(config["a4_s"]["graph_lambda"]))
    for fold in data.folds:
        fold_id = int(fold["fold"])
        train_times = np.asarray(fold["train_indices"], dtype=np.int64)
        eval_times = np.asarray(fold["validation_indices"], dtype=np.int64)
        raw_train = data.a3[train_times].reshape(-1, data.a3.shape[2]).astype(np.float64, copy=False)
        raw_eval = data.a3[eval_times].reshape(-1, data.a3.shape[2]).astype(np.float64, copy=False)
        y_train = data.counts[train_times].reshape(-1)
        y_eval = data.counts[eval_times].reshape(-1)
        labels = extrapolation_labels(raw_train, raw_eval, data.feature_names)
        week_index = np.repeat(eval_times, NODE_COUNT)
        node_id = np.tile(np.arange(NODE_COUNT, dtype=np.int64), len(eval_times))
        for candidate in candidates:
            started = time.time()
            state, p, conditional, mu, fit_info = fit_candidate(candidate, raw_train, y_train, raw_eval, solver, config)
            metrics = metric_dict_for_frame(y_eval, p, conditional, mu, float(state["theta"]), float(np.mean(y_train > 0)))
            fold_rows.append({"candidate": candidate, "fold": fold_id, "validation_start": fold["validation_start"], "validation_end": fold["validation_end"], "theta": float(state["theta"]), "runtime_seconds": float(time.time() - started), "converged": bool(fit_info.get("occurrence_success") and fit_info.get("count_success")), **fit_info, **metrics})
            for key, value in (("y", y_eval), ("p", p), ("conditional", conditional), ("mu", mu), ("week_index", week_index), ("node_id", node_id), ("fold", np.full(len(y_eval), fold_id, dtype=np.int16))):
                predictions[candidate][key].append(value)
            for feature, regime in labels.items():
                for level in ("in_distribution", "moderate", "strong"):
                    mask = regime == level
                    if not mask.any():
                        continue
                    row = metric_dict_for_frame(y_eval[mask], p[mask], conditional[mask], mu[mask], float(state["theta"]), float(np.mean(y_train > 0)))
                    extrap_rows.append({"candidate": candidate, "fold": fold_id, "feature": feature, "regime": level, "rows": int(mask.sum()), **row})
    compact: dict[str, dict[str, np.ndarray]] = {}
    for candidate, values in predictions.items():
        compact[candidate] = {key: np.concatenate(items) for key, items in values.items()}
        np.savez_compressed(output / "predictions" / f"{candidate}_oof.npz", **compact[candidate])
    return compact, pd.DataFrame(fold_rows), pd.DataFrame(extrap_rows)


def spatial_diagnostics(predictions: dict[str, dict[str, np.ndarray]], data: DataBundle, config: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    summary_rows: list[dict[str, Any]] = []
    map_rows: list[dict[str, Any]] = []
    cluster_rows: list[dict[str, Any]] = []
    candidate_index = {candidate: index for index, candidate in enumerate(predictions)}
    residual_index = {name: index for index, name in enumerate(("occurrence", "positive_count", "combined_expected_count"))}
    for candidate, arrays in predictions.items():
        y = arrays["y"]
        p = arrays["p"]
        conditional = arrays["conditional"]
        node_ids = arrays["node_id"]
        occurrence = aggregate_node((y > 0).astype(float) - p, node_ids)
        positive = y > 0
        count = aggregate_node(y - conditional, node_ids, positive)
        combined = aggregate_node(y - p * conditional, node_ids)
        for name, values in (("occurrence", occurrence), ("positive_count", count), ("combined_expected_count", combined)):
            seed = int(config["a4_s"]["permutation_seed"]) + 100 * candidate_index[candidate] + residual_index[name]
            statistic, p_value = moran_with_permutation(values, data.adjacency, int(config["a4_s"]["permutation_count"]), seed)
            summary_rows.append({"candidate": candidate, "residual": name, "moran_i": statistic, "permutation_p_value": p_value, "mean_residual": float(values.mean()), "sd_residual": float(values.std()), "max_abs_residual": float(np.max(np.abs(values)))})
            cluster_rows.extend(residual_clusters(values, data.adjacency, data.nodes, candidate, name))
        for idx, node in data.nodes.iterrows():
            map_rows.append({"candidate": candidate, "model_node_id": int(node.model_node_id), "lon": float(node.lon), "lat": float(node.lat), "occurrence_residual": float(occurrence[idx]), "positive_count_residual": float(count[idx]), "combined_expected_count_residual": float(combined[idx])})
    return pd.DataFrame(summary_rows), pd.DataFrame(map_rows), pd.DataFrame(cluster_rows)


def observation_sensitivity(a3_arrays: dict[str, np.ndarray], config: dict[str, Any], training_prevalence: float) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    y = a3_arrays["y"]
    p = a3_arrays["p"]
    conditional = a3_arrays["conditional"]
    mu = a3_arrays["mu"]
    theta = float(config["model"]["theta_a3"])
    for rate in config["a4_o"]["reporting_rate_scenarios"]:
        rate = float(rate)
        latent_probability = np.minimum(p / rate, 1.0)
        observed_probability = rate * latent_probability
        latent_conditional = conditional / rate
        observed_conditional = rate * latent_conditional
        metrics = metric_dict_for_frame(y, observed_probability, observed_conditional, mu, theta, training_prevalence)
        rows.append({"candidate": "A4-O", "reporting_rate": rate, "latent_probability_cap_fraction": float(np.mean(p > rate)), "latent_conditional_mean": float(np.mean(latent_conditional[y > 0])), "identifiability": "sensitivity_only", **metrics})
    return pd.DataFrame(rows)


def baseline_reproduction_gate(fold_metrics: pd.DataFrame, reference_path: Path, output: Path) -> pd.DataFrame:
    reference = pd.read_csv(reference_path)
    reference = reference.loc[reference["model"].astype(str) == "A3"].set_index("fold")
    required = ("joint_hurdle_nll", "pr_auc", "roc_auc", "brier", "brier_skill", "calibration_intercept", "calibration_slope", "positive_count_mae", "positive_count_rmse", "conditional_mean_bias")
    rows: list[dict[str, Any]] = []
    observed = fold_metrics.loc[fold_metrics.candidate == "A3"].set_index("fold")
    for fold in FOLD_IDS:
        for metric in required:
            expected = float(reference.loc[fold, metric])
            reproduced = float(observed.loc[fold, metric])
            difference = abs(expected - reproduced)
            rows.append({"fold": fold, "metric": metric, "reference": expected, "reproduced": reproduced, "absolute_difference": difference, "tolerance": 1e-9, "pass": bool(difference <= 1e-9)})
    result = pd.DataFrame(rows)
    write_csv(output / "results/a3_baseline_reproduction.csv", result)
    if not bool(result["pass"].all()):
        raise RuntimeError("STOP: fixed A3 fold reproduction failed before A4 interpretation")
    return result


def summarize_candidates(fold_metrics: pd.DataFrame, spatial: pd.DataFrame, ranking: pd.DataFrame, extrap: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    complexities = {"A3": 70, "A4-S": 70 + 2 * NODE_COUNT, "A4-C": 71, "A4-SC": 71 + 2 * NODE_COUNT}
    for candidate in ("A3", "A4-S", "A4-C", "A4-SC"):
        group = fold_metrics.loc[fold_metrics.candidate == candidate]
        occ_moran = spatial.loc[(spatial.candidate == candidate) & (spatial.residual == "occurrence"), "moran_i"]
        count_moran = spatial.loc[(spatial.candidate == candidate) & (spatial.residual == "positive_count"), "moran_i"]
        rank = ranking.loc[(ranking.candidate == candidate) & (ranking.row_type == "overall_positive_summary")].iloc[0]
        strong = extrap.loc[(extrap.candidate == candidate) & (extrap.feature == "combined_history") & (extrap.regime == "strong")]
        rows.append({
            "candidate": candidate, "status": "EVALUATED", "selection_eligible": True, "effective_complexity": complexities[candidate],
            "mean_fold_pr_auc": float(group.pr_auc.mean()), "worst_fold_pr_auc": float(group.pr_auc.min()),
            "mean_brier_skill": float(group.brier_skill.mean()), "worst_fold_brier_skill": float(group.brier_skill.min()),
            "mean_joint_nll": float(group.joint_hurdle_nll.mean()), "mean_count_nll": float(group.zt_nb_nll.mean()),
            "mean_count_mae": float(group.positive_count_mae.mean()), "mean_count_rmse": float(group.positive_count_rmse.mean()),
            "mean_count_bias": float(group.count_bias.mean()), "mean_calibration_intercept": float(group.calibration_intercept.mean()), "mean_calibration_slope": float(group.calibration_slope.mean()),
            "occurrence_moran_i": float(occ_moran.iloc[0]), "positive_count_moran_i": float(count_moran.iloc[0]),
            "us_median_positive_percentile": safe_float(rank.us_median_positive_percentile), "us_top10_recall": safe_float(ranking.loc[(ranking.candidate == candidate) & (ranking.row_type == "overall_top_k") & (ranking.top_k == 0.1), "recall"].iloc[0]),
            "strong_history_rows": int(strong.rows.sum()) if len(strong) else 0, "strong_history_joint_nll": float(np.average(strong.joint_hurdle_nll, weights=strong.rows)) if len(strong) and strong.rows.sum() else None,
            "convergence_stability": bool(group.converged.all()), "computational_cost_seconds": float(group.runtime_seconds.sum()), "identifiability": "identified_structured_candidate",
        })
    # A4-O is intentionally sensitivity-only because the available inputs do
    # not identify a reporting process. Keep it visible in the comparison
    # table, but exclude it from advancement guardrails.
    rows.append({
        "candidate": "A4-O", "status": "SENSITIVITY_ONLY", "selection_eligible": False,
        "effective_complexity": None, "mean_fold_pr_auc": None, "worst_fold_pr_auc": None,
        "mean_brier_skill": None, "worst_fold_brier_skill": None, "mean_joint_nll": None,
        "mean_count_nll": None, "mean_count_mae": None, "mean_count_rmse": None,
        "mean_count_bias": None, "mean_calibration_intercept": None, "mean_calibration_slope": None,
        "occurrence_moran_i": None, "positive_count_moran_i": None,
        "us_median_positive_percentile": None, "us_top10_recall": None,
        "strong_history_rows": None, "strong_history_joint_nll": None,
        "convergence_stability": None, "computational_cost_seconds": None,
        "identifiability": "sensitivity_only",
    })
    return pd.DataFrame(rows)


def assess_guardrails(summary: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    reference = summary.loc[summary.candidate == "A3"].iloc[0]
    g = config["advancement_guardrails"]
    rows: list[dict[str, Any]] = []
    for row in summary.itertuples(index=False):
        if row.candidate == "A3" or not bool(row.selection_eligible):
            continue
        us_ranking_assessable = row.us_median_positive_percentile is not None and reference.us_median_positive_percentile is not None and row.us_top10_recall is not None and reference.us_top10_recall is not None
        checks = {
            "occurrence_preserved": row.mean_fold_pr_auc >= reference.mean_fold_pr_auc - g["pr_auc_material_degradation"] and row.mean_brier_skill >= reference.mean_brier_skill - g["brier_skill_material_degradation"],
            "worst_fold_preserved": row.worst_fold_pr_auc >= reference.worst_fold_pr_auc - g["worst_fold_pr_auc_degradation"],
            "us_ranking_preserved": bool(us_ranking_assessable and row.us_median_positive_percentile >= reference.us_median_positive_percentile - g["us_median_percentile_degradation"] and row.us_top10_recall >= reference.us_top10_recall - g["us_top10_recall_degradation"]),
            "calibration_not_collapsed": abs(row.mean_calibration_intercept - reference.mean_calibration_intercept) <= g["calibration_intercept_change"] and abs(row.mean_calibration_slope - reference.mean_calibration_slope) <= g["calibration_slope_change"],
            "structural_improvement": row.occurrence_moran_i <= reference.occurrence_moran_i - g["moran_material_reduction"] or row.positive_count_moran_i <= reference.positive_count_moran_i - g["moran_material_reduction"] or row.mean_joint_nll <= reference.mean_joint_nll - g["joint_nll_material_reduction"] or abs(row.mean_count_bias) <= abs(reference.mean_count_bias) - g["count_bias_material_reduction"] or (row.strong_history_joint_nll is not None and reference.strong_history_joint_nll is not None and row.strong_history_joint_nll <= reference.strong_history_joint_nll - g["extrapolative_nll_material_reduction"]),
        }
        failure_reasons = "; ".join("us_ranking_not_assessable" if key == "us_ranking_preserved" and not us_ranking_assessable else key for key, value in checks.items() if not value)
        rows.append({"candidate": row.candidate, "us_ranking_assessable": bool(us_ranking_assessable), **checks, "passes_all_guardrails": bool(all(checks.values())), "failure_reasons": failure_reasons})
    return pd.DataFrame(rows)


def choose_decision(summary: pd.DataFrame, guardrails: pd.DataFrame, config: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    passed = guardrails.loc[guardrails.passes_all_guardrails, "candidate"].tolist()
    evidence: dict[str, Any] = {"eligible_candidates": passed}
    if "A4-S" in passed and "A4-C" in passed and "A4-SC" in passed:
        decision = "ADVANCE A4-SC"
    elif "A4-S" in passed:
        decision = "ADVANCE A4-S"
    elif "A4-C" in passed:
        decision = "ADVANCE A4-C"
    else:
        decision = "HOLD — NO A4 CANDIDATE JUSTIFIED"
    evidence["not_advanced"] = {row.candidate: row.failure_reasons for row in guardrails.itertuples(index=False) if not row.passes_all_guardrails}
    return decision, evidence


def write_report(output: Path, manifest: dict[str, Any], inventory: pd.DataFrame, summary: pd.DataFrame, guardrails: pd.DataFrame, sensitivity: pd.DataFrame, decision: str, evidence: dict[str, Any]) -> None:
    lines = [
        "# Structured A4 architecture comparison",
        "",
        f"Final architecture decision: **{decision}**.",
        "",
        "This is a controlled pre-W30 development comparison. The A3 prospective interval 2026-W30 through 2026-W39 was not loaded, fitted, scored, or used for selection.",
        "",
        "## Executive Summary",
        "",
        "The comparison targets A3 residual spatial dependence, positive-count mismatch, history-feature extrapolation, and possible observation/reporting heterogeneity. Recorded detections are not treated as true latent abundance: mismatch can arise from the latent count model, the observation process, or both.",
        "",
        "The U.S. endpoints are intervention-confounded because stronger SIT suppression can reduce recorded occurrence, counts, and northward progression. SIT covariates were deliberately excluded and are reserved as `RESERVED_FUTURE_INTERVENTION_LAYER`.",
        "",
        "The pre-W30 blocked folds contain zero U.S. positive node-weeks. U.S. positive-risk ranking is therefore **not assessable for A4 selection** in this development phase; the untouched prospective period remains reserved for a later independent evaluation.",
        "",
        "## Observation-Process Assessment",
        "",
        "The authoritative observation file contains date, host, longitude, and latitude. No surveillance jurisdiction, reporting source, sampling program, inspection effort, reporting-frequency denominator, or authorized accessibility-effort artifact was available. A4-O is therefore sensitivity-only and is not eligible for advancement.",
        "",
        "Fixed reporting-rate scenarios were predeclared at 0.50, 0.75, and 1.00. They do not identify latent abundance from these data alone; the recorded-scale candidate ranking is therefore interpreted as sensitivity rather than estimation.",
        "",
        "## Candidate Results",
        "",
        "| Candidate | Mean PR-AUC | Worst PR-AUC | Mean Brier skill | Mean joint NLL | Count NLL | Count bias | Occurrence Moran's I | Count Moran's I | U.S. median percentile | U.S. top-10% recall | Guardrail |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in summary.itertuples(index=False):
        if row.candidate == "A3":
            guard = "REFERENCE"
        elif not bool(row.selection_eligible):
            guard = "SENSITIVITY ONLY"
        else:
            guard = "PASS" if bool(guardrails.loc[guardrails.candidate == row.candidate, "passes_all_guardrails"].iloc[0]) else "FAIL"
        def fmt(value: Any) -> str:
            return "NA" if value is None or not np.isfinite(float(value)) else f"{float(value):.4f}"
        lines.append(f"| {row.candidate} | {fmt(row.mean_fold_pr_auc)} | {fmt(row.worst_fold_pr_auc)} | {fmt(row.mean_brier_skill)} | {fmt(row.mean_joint_nll)} | {fmt(row.mean_count_nll)} | {fmt(row.mean_count_bias)} | {fmt(row.occurrence_moran_i)} | {fmt(row.positive_count_moran_i)} | {fmt(row.us_median_positive_percentile)} | {fmt(row.us_top10_recall)} | {guard} |")
    lines += [
        "",
        "## U.S. Interpretation",
        "",
        "U.S. risk ranking is a primary endpoint. Raw U.S. count magnitude and progression speed are secondary `INTERVENTION_CONFOUNDED` endpoints and were not used as primary advancement criteria.",
        "",
        "## Final Decision",
        "",
        f"**{decision}**",
        "",
        "The machine-readable guardrail assessment and all fold-level metrics are in `results/`. Large OOF prediction arrays remain external to Git.",
        "",
        "## Provenance",
        "",
        f"- Canonical baseline SHA: `{manifest['repository_sha']}`",
        f"- Fit period: `{manifest['development_period']['start']}` through `{manifest['development_period']['end']}`",
        f"- Prospective exclusion: `{', '.join(PROSPECTIVE_WEEKS)}`",
        f"- A3 baseline unchanged: `{manifest['a3_baseline_unchanged']}`",
        f"- SIT included: `{manifest['sit_included']}`",
        "",
        "Observation inventory: `results/observation_process_inventory.csv`.",
        "Candidate comparison: `results/a4_candidate_comparison.csv`.",
        "Sensitivity scenarios: `results/a4_o_sensitivity.csv`.",
    ]
    (output / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--repository-sha", default=None)
    parser.add_argument("--model-output", type=Path, required=True)
    parser.add_argument("--front-features", type=Path, required=True)
    parser.add_argument("--anthropogenic-features", type=Path, required=True)
    parser.add_argument("--soil-features", type=Path, required=True)
    parser.add_argument("--edges", type=Path, required=True)
    parser.add_argument("--observation-source", type=Path, required=True)
    parser.add_argument("--a3-fold-reference", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    config = read_config(args.config)
    output = args.output_root.resolve()
    for directory in ("results", "predictions", "figures", "provenance"):
        (output / directory).mkdir(parents=True, exist_ok=True)
    data = load_data(args, config)
    inventory = inventory_observation_process(args.observation_source, data.nodes)
    write_csv(output / "results/observation_process_inventory.csv", inventory)
    if int((inventory["usable_now"] == "yes").sum()) != 0:
        raise RuntimeError("A4-O implementation unexpectedly found a usable effort proxy; escalate before fitting observation effects")
    solver = make_graph_solver(data.laplacian, float(config["a4_s"]["graph_lambda"]))
    predictions, fold_metrics, extrapolation = run_oof(data, config, output)
    write_csv(output / "results/a4_fold_metrics.csv", fold_metrics)
    baseline_gate = baseline_reproduction_gate(fold_metrics, args.a3_fold_reference, output)
    write_csv(output / "results/a4_extrapolative_regime_metrics.csv", extrapolation)
    ranking = rank_metrics(predictions, data.nodes)
    write_csv(output / "results/a4_us_ranking.csv", ranking)
    spatial, spatial_map, clusters = spatial_diagnostics(predictions, data, config)
    write_csv(output / "results/a4_spatial_residual_summary.csv", spatial)
    write_csv(output / "results/a4_spatial_residual_map_data.csv", spatial_map)
    write_csv(output / "results/a4_residual_clusters.csv", clusters)
    sensitivity = observation_sensitivity(predictions["A3"], config, float(np.mean(data.counts > 0)))
    write_csv(output / "results/a4_o_sensitivity.csv", sensitivity)
    summary = summarize_candidates(fold_metrics, spatial, ranking, extrapolation, config)
    guardrails = assess_guardrails(summary, config)
    write_csv(output / "results/a4_candidate_comparison.csv", summary)
    write_csv(output / "results/a4_guardrail_assessment.csv", guardrails)
    decision, evidence = choose_decision(summary, guardrails, config)
    manifest = {
        "analysis": "structured_a4_architecture_comparison",
        "status": "completed",
        "repository_sha": args.repository_sha or git_head(REPOSITORY_ROOT),
        "canonical_baseline_sha": BASELINE_SHA,
        "development_period": config["development_period"],
        "folds": config["folds"],
        "node_count": NODE_COUNT,
        "predictor_count": len(data.feature_names),
        "feature_order": data.feature_names,
        "input_sha256": data.hashes,
        "script_sha256": {"run_a4_comparison.py": sha256_file(Path(__file__)), "augmentation_fitter.py": sha256_file(REPOSITORY_ROOT / "analysis/predictor_augmentation/scripts/run_predictor_augmentation.py"), "config": sha256_file(args.config)},
        "model_constants": config["model"],
        "a4_s": config["a4_s"],
        "a4_o": config["a4_o"],
        "candidate_scope": config["candidate_scope"],
        "sit_included": False,
        "a3_baseline_unchanged": True,
        "prospective_data_loaded": False,
        "prospective_selection_used": False,
        "observation_proxy_count_usable_now": int((inventory["usable_now"] == "yes").sum()),
        "candidate_decision": decision,
        "a3_baseline_reproduction_max_difference": float(baseline_gate["absolute_difference"].max()),
        "decision_evidence": evidence,
        "runtime": {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__},
        "generated_utc": utc_now(),
    }
    write_json(output / "provenance/a4_analysis_manifest.json", manifest)
    write_json(output / "results/a4_decision.json", {"decision": decision, "evidence": evidence, "failure_modes_targeted": ["spatial_residual_dependence", "positive_count_process", "history_extrapolation", "observation_reporting_uncertainty"], "sit_status": "RESERVED_FUTURE_INTERVENTION_LAYER"})
    write_report(output, manifest, inventory, summary, guardrails, sensitivity, decision, evidence)
    print(json.dumps({"status": "completed", "decision": decision, "output_root": str(output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
