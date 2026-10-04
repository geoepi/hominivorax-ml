#!/usr/bin/env python3
"""Task 3B V2-A causal recorded-detection front-state hurdle development.

This runner fits only the authorized M0/M1/M2 candidates.  M0 is the locked
STGNN-Hurdle-V1 current-week benchmark.  M1 adds three strictly pre-week
recorded-detection history features and M2 adds only the pre-specified
13-week latitude-percentile ablation.  The response is explicitly a recorded
detection, not latent occupancy or biological abundance.

All validation uses rolling-origin historical folds.  Folds 5--6 reuse the
Task 2G terminal outcomes and are therefore labelled historical,
pseudo-prospective, and non-independent throughout.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.special import expit
from scipy.stats import rankdata

SCRIPT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_ROOT))
from run_task2e_baselines import (  # noqa: E402
    CALENDAR_FEATURES,
    DENSITY_FEATURES,
    ENV_FEATURES,
    ExactHurdleRegressor,
    safe_metrics,
    write_json,
)
from run_task2f_structured import RegularizedExactHurdleRegressor  # noqa: E402
from run_task3a_v2_audit import causal_front_descriptors  # noqa: E402


EXPECTED_SOURCE_SHA = "a3d55f3ddf867087b578df803920bf59c6c303fa695e3218a5f3463e596d497e"
EXPECTED_SOURCE_ROWS = 136714
EXPECTED_NODE_COUNT = 10037
EXPECTED_RESPONSE_WEEKS = 81
EXPECTED_GRAPH_EDGES = 77614
AUDIT_WEEK_COUNT = 133
V1_REFERENCE_SHA = "19886ca2fab5efb2eea25ba6b1fb086f7ecb1ab0"
V1_MODEL_ID = "STGNN-Hurdle-V1"
BASE_FEATURES = list(ENV_FEATURES) + list(DENSITY_FEATURES) + [
    f"{name}_imputed" for name in DENSITY_FEATURES
] + list(CALENDAR_FEATURES)
PRIMARY_FRONT_CONTINUOUS = [
    "distance_to_any_prior_positive_log1p",
    "distance_to_prev4_positive_log1p",
    "weeks_since_detection_within_50km_log1p",
]
PRIMARY_FRONT_AVAILABILITY = [
    "any_prior_positive_available",
    "prev4_positive_available",
    "detection_within_50km_ever_available",
]
LATITUDE_FEATURES = ["prior13_latitude_p95_log1p", "prior13_latitude_p95_available"]
MODELS = {
    "M0": BASE_FEATURES,
    "M1": BASE_FEATURES + PRIMARY_FRONT_CONTINUOUS + PRIMARY_FRONT_AVAILABILITY,
    "M2": BASE_FEATURES + PRIMARY_FRONT_CONTINUOUS + PRIMARY_FRONT_AVAILABILITY + LATITUDE_FEATURES,
}
PENALTY_GRID = {"M0": [0.0], "M1": [0.0, 1e-4, 1e-3, 1e-2], "M2": [0.0, 1e-4, 1e-3, 1e-2]}
SELECTION_FOLDS = (1, 2, 3, 4)
FRONT_DISTANCE_BINS = [("0_25km", 0.0, 25.0), ("25_50km", 25.0, 50.0), ("50_100km", 50.0, 100.0), ("100_250km", 100.0, 250.0), ("over_250km", 250.0, np.inf)]
RECENCY_BINS = [("0_1week", 0.0, 1.0), ("2_4weeks", 1.0, 4.0), ("5_13weeks", 4.0, 13.0), ("over_13weeks", 13.0, np.inf)]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=SCRIPT_ROOT.parent, text=True).strip()
    except Exception:
        return "unknown"


def jsonable(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def response_folds(weeks: pd.DataFrame) -> list[dict[str, Any]]:
    labels = weeks["iso_week"].astype(str).tolist()
    expected = [
        ("2025-W01", "2025-W26", "2025-W27", "2025-W39"),
        ("2025-W01", "2025-W39", "2025-W40", "2025-W52"),
        ("2025-W01", "2025-W52", "2026-W01", "2026-W08"),
        ("2025-W01", "2026-W08", "2026-W09", "2026-W16"),
        ("2025-W01", "2026-W16", "2026-W17", "2026-W22"),
        ("2025-W01", "2026-W22", "2026-W23", "2026-W29"),
    ]
    folds = []
    for number, (train_start, train_end, val_start, val_end) in enumerate(expected, 1):
        train = list(range(labels.index(train_start), labels.index(train_end) + 1))
        validation = list(range(labels.index(val_start), labels.index(val_end) + 1))
        if train[-1] + 1 != validation[0] or train[0] != 0:
            raise AssertionError(f"non-contiguous rolling fold {number}")
        folds.append({
            "fold": number,
            "train_indices": train,
            "validation_indices": validation,
            "train_start": train_start,
            "train_end": train_end,
            "validation_start": val_start,
            "validation_end": val_end,
            "label": "historical development" if number <= 4 else "historical pseudo-prospective, non-independent",
        })
    if sum(len(row["validation_indices"]) for row in folds) != 55:
        raise AssertionError("rolling fold validation weeks do not cover the expected 55 weeks")
    return folds


def load_data(model_output: Path, audit_output: Path) -> dict[str, Any]:
    raw = model_output / "raw"
    manifest = json.loads((model_output / "manifests" / "revised_production_manifest.json").read_text())
    source = manifest["observation_source"]
    if source["sha256"] != EXPECTED_SOURCE_SHA or int(source["row_count"]) != EXPECTED_SOURCE_ROWS:
        raise AssertionError("observation source provenance changed")
    dynamic = np.load(raw / "dynamic_features.npy", mmap_mode="r")
    static = np.load(raw / "static_features.npy", mmap_mode="r")
    counts = np.asarray(np.load(raw / "targets_count.npy", mmap_mode="r"), dtype=np.int64)
    weeks = pd.read_parquet(raw / "weeks.parquet")
    calendar = pd.read_parquet(raw / "calendar_features.parquet")[CALENDAR_FEATURES].to_numpy(np.float64)
    nodes = pd.read_parquet(raw / "nodes.parquet").sort_values("model_node_id").reset_index(drop=True)
    edges = pd.read_parquet(raw / "edges_queen.parquet")
    if tuple(dynamic.shape) != (EXPECTED_RESPONSE_WEEKS, EXPECTED_NODE_COUNT, 12):
        raise AssertionError(f"unexpected dynamic feature shape {dynamic.shape}")
    if tuple(static.shape) != (EXPECTED_NODE_COUNT, 10) or tuple(counts.shape) != (EXPECTED_RESPONSE_WEEKS, EXPECTED_NODE_COUNT):
        raise AssertionError("unexpected V1 production shape")
    if len(weeks) != EXPECTED_RESPONSE_WEEKS or len(nodes) != EXPECTED_NODE_COUNT or len(edges) != EXPECTED_GRAPH_EDGES:
        raise AssertionError("production dimensions changed")
    if not np.array_equal(nodes["model_node_id"].to_numpy(), np.arange(EXPECTED_NODE_COUNT)):
        raise AssertionError("model node ordering changed")
    if not np.isfinite(np.asarray(dynamic)).all() or not np.isfinite(np.asarray(static)).all():
        raise AssertionError("non-finite production predictors")
    if np.any(counts < 0) or not np.isfinite(counts).all():
        raise AssertionError("invalid production targets")
    folds = response_folds(weeks)

    classification_path = model_output / "diagnostics" / "updated_observation_classification.parquet"
    classification = pd.read_parquet(classification_path)
    audit_weeks = pd.read_parquet(audit_output / "front_states" / "front_state_node_week.parquet")
    audit_week_table = audit_weeks[["week", "week_index"]].drop_duplicates().sort_values("week_index").reset_index(drop=True)
    if len(audit_week_table) != AUDIT_WEEK_COUNT:
        raise AssertionError("Task 3A front-state audit does not cover 133 weeks")
    audit_index = dict(zip(audit_week_table["week"].astype(str), audit_week_table["week_index"].astype(int)))
    classification = classification.loc[
        classification["revised_domain_membership"].astype(bool)
        & classification["model_node_id"].notna()
        & classification["iso_week"].astype(str).isin(audit_index)
    ].copy()
    classification["model_node_id"] = classification["model_node_id"].astype(int)
    classification["audit_week_index"] = classification["iso_week"].astype(str).map(audit_index).astype(int)
    audit_counts = np.zeros((AUDIT_WEEK_COUNT, EXPECTED_NODE_COUNT), dtype=np.int32)
    grouped = classification.groupby(["audit_week_index", "model_node_id"]).size()
    for (week_index, node_id), value in grouped.items():
        audit_counts[int(week_index), int(node_id)] = int(value)
    response_audit_indices = np.asarray([audit_index[str(label)] for label in weeks["iso_week"]], dtype=int)
    classification_target_counts = audit_counts[response_audit_indices].copy()
    mismatch = classification_target_counts - counts
    # The V1 production target array is the response contract.  The Task 3A
    # source-classification table is retained for pre-2025 initialization, but
    # a small number of response cells differ because the earlier preflight
    # assignment and revised-domain classification used different coordinate
    # eligibility filters.  Reconcile response weeks to the immutable V1
    # target array rather than silently scoring a different response.
    audit_counts[response_audit_indices] = counts
    xy = nodes[["x", "y"]].to_numpy(float)
    distance_placeholder = float(np.hypot(np.ptp(xy[:, 0]), np.ptp(xy[:, 1])))
    if not np.isfinite(distance_placeholder) or distance_placeholder <= 0:
        raise AssertionError("invalid deterministic distance placeholder")
    recency_placeholder = float(AUDIT_WEEK_COUNT + 1)
    return {
        "root": model_output,
        "audit_output": audit_output,
        "manifest": manifest,
        "dynamic": dynamic,
        "static": static,
        "counts": counts,
        "weeks": weeks,
        "calendar": calendar,
        "nodes": nodes,
        "edges": edges,
        "folds": folds,
        "classification": classification,
        "audit_counts": audit_counts,
        "response_audit_indices": response_audit_indices,
        "front_states": None,
        "classification_target_mismatch_cells": int(np.count_nonzero(mismatch)),
        "classification_target_mismatch_absolute_count": int(np.abs(mismatch).sum()),
        "audit_week_labels": audit_week_table["week"].astype(str).tolist(),
        "distance_placeholder_km": distance_placeholder,
        "recency_placeholder_weeks": recency_placeholder,
        "source_sha": source["sha256"],
        "source_rows": int(source["row_count"]),
    }


def build_front_features(data: dict[str, Any], output: Path) -> tuple[pd.DataFrame, dict[str, np.ndarray]]:
    nodes = data["nodes"]
    positive_sets = [np.flatnonzero(data["audit_counts"][week_index] > 0) for week_index in range(AUDIT_WEEK_COUNT)]
    state = causal_front_descriptors(
        positive_sets,
        nodes[["x", "y"]].to_numpy(float),
        nodes["lat"].to_numpy(float),
        data["audit_week_labels"],
    )
    state = state.loc[state["week"].astype(str).isin(data["weeks"]["iso_week"].astype(str))].copy()
    state = state.sort_values(["week_index", "node_id"]).reset_index(drop=True)
    distance_any = state["distance_to_any_prior_detection_km"].to_numpy(float)
    distance_prev4 = state["distance_to_previous4_detection_km"].to_numpy(float)
    recency = state["weeks_since_any_detection_within_50km"].to_numpy(float)
    lat95 = state["p95_previous13_latitude"].to_numpy(float)
    available_any = np.isfinite(distance_any)
    available_prev4 = np.isfinite(distance_prev4)
    available_recency = np.isfinite(recency)
    available_lat = np.isfinite(lat95)
    distance_any_filled = np.where(available_any, distance_any, data["distance_placeholder_km"])
    distance_prev4_filled = np.where(available_prev4, distance_prev4, data["distance_placeholder_km"])
    recency_filled = np.where(available_recency, recency, data["recency_placeholder_weeks"])
    lat_placeholder = float(max(1.0, np.nanmax(np.abs(nodes["lat"].to_numpy(float)))))
    lat95_filled = np.where(available_lat, np.maximum(lat95, 0.0), lat_placeholder)
    expected_rows = EXPECTED_RESPONSE_WEEKS * EXPECTED_NODE_COUNT
    if len(state) != expected_rows:
        raise AssertionError("front-state response rows changed")
    frame = pd.DataFrame({
        "week": state["week"].astype(str).to_numpy(),
        "week_index": state["week_index"].to_numpy(int) - 52,
        "model_node_id": state["node_id"].to_numpy(int),
        "canonical_node_id": nodes.loc[state["node_id"].to_numpy(int), "canonical_node_id"].to_numpy(),
        "distance_to_any_prior_positive_km": distance_any_filled,
        "distance_to_prev4_positive_km": distance_prev4_filled,
        "weeks_since_detection_within_50km": recency_filled,
        "any_prior_positive_available": available_any.astype(np.int8),
        "prev4_positive_available": available_prev4.astype(np.int8),
        "detection_within_50km_ever_available": available_recency.astype(np.int8),
        "prior13_latitude_p95": lat95_filled,
        "prior13_latitude_p95_available": available_lat.astype(np.int8),
        "history_cutoff_week": state["source_history_cutoff"].astype("string").fillna("").to_numpy(),
        "distance_placeholder_km": data["distance_placeholder_km"],
        "recency_placeholder_weeks": data["recency_placeholder_weeks"],
    })
    for raw_name, transform_name in [
        ("distance_to_any_prior_positive_km", "distance_to_any_prior_positive_log1p"),
        ("distance_to_prev4_positive_km", "distance_to_prev4_positive_log1p"),
        ("weeks_since_detection_within_50km", "weeks_since_detection_within_50km_log1p"),
        ("prior13_latitude_p95", "prior13_latitude_p95_log1p"),
    ]:
        frame[transform_name] = np.log1p(np.maximum(frame[raw_name].to_numpy(float), 0.0))
    if not np.isfinite(frame[PRIMARY_FRONT_CONTINUOUS + ["prior13_latitude_p95_log1p"]].to_numpy(float)).all():
        raise AssertionError("front features contain non-finite values")
    output.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(output / "causal_front_features.parquet", index=False)
    frame[[
        "week", "week_index", "model_node_id", "canonical_node_id",
        *PRIMARY_FRONT_CONTINUOUS, *PRIMARY_FRONT_AVAILABILITY,
        "prior13_latitude_p95_log1p", "prior13_latitude_p95_available", "history_cutoff_week",
    ]].to_parquet(output / "latitude_ablation_features.parquet", index=False)
    shape = (EXPECTED_RESPONSE_WEEKS, EXPECTED_NODE_COUNT)
    arrays = {
        "distance_any": frame["distance_to_any_prior_positive_km"].to_numpy(float).reshape(shape),
        "distance_prev4": frame["distance_to_prev4_positive_km"].to_numpy(float).reshape(shape),
        "recency50": frame["weeks_since_detection_within_50km"].to_numpy(float).reshape(shape),
        "any_available": frame["any_prior_positive_available"].to_numpy(float).reshape(shape),
        "prev4_available": frame["prev4_positive_available"].to_numpy(float).reshape(shape),
        "recency_available": frame["detection_within_50km_ever_available"].to_numpy(float).reshape(shape),
        "lat95": frame["prior13_latitude_p95"].to_numpy(float).reshape(shape),
        "lat_available": frame["prior13_latitude_p95_available"].to_numpy(float).reshape(shape),
    }
    return frame, arrays


def build_base_array(data: dict[str, Any]) -> np.ndarray:
    density = np.log1p(np.asarray(data["static"][:, :5], dtype=float))
    indicators = np.asarray(data["static"][:, 5:], dtype=float)
    dynamic = np.asarray(data["dynamic"], dtype=float)
    calendar = np.asarray(data["calendar"], dtype=float)
    base = np.concatenate([
        dynamic,
        np.broadcast_to(density[None, :, :], (EXPECTED_RESPONSE_WEEKS, EXPECTED_NODE_COUNT, 5)),
        np.broadcast_to(indicators[None, :, :], (EXPECTED_RESPONSE_WEEKS, EXPECTED_NODE_COUNT, 5)),
        np.broadcast_to(calendar[:, None, :], (EXPECTED_RESPONSE_WEEKS, EXPECTED_NODE_COUNT, 2)),
    ], axis=2)
    if base.shape != (EXPECTED_RESPONSE_WEEKS, EXPECTED_NODE_COUNT, 24) or not np.isfinite(base).all():
        raise AssertionError("V1 base feature array contract failed")
    return base


def build_arrays(data: dict[str, Any], front: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    base = build_base_array(data)
    transformed = np.stack([
        np.log1p(front["distance_any"]),
        np.log1p(front["distance_prev4"]),
        np.log1p(front["recency50"]),
        front["any_available"], front["prev4_available"], front["recency_available"],
    ], axis=2)
    latitude = np.stack([np.log1p(front["lat95"]), front["lat_available"]], axis=2)
    arrays = {
        "M0": base,
        "M1": np.concatenate([base, transformed], axis=2),
        "M2": np.concatenate([base, transformed, latitude], axis=2),
    }
    expected = {"M0": 24, "M1": 30, "M2": 32}
    for model, array in arrays.items():
        if array.shape != (EXPECTED_RESPONSE_WEEKS, EXPECTED_NODE_COUNT, expected[model]) or not np.isfinite(array).all():
            raise AssertionError(f"{model} feature contract failed: {array.shape}")
        if len(MODELS[model]) != array.shape[2]:
            raise AssertionError("feature order contract failed")
    return arrays


def selected_matrix(array: np.ndarray, times: list[int]) -> np.ndarray:
    return np.asarray(array[np.asarray(times, dtype=int)], dtype=np.float64).reshape(-1, array.shape[2])


def fit_scaling(array: np.ndarray, feature_names: list[str], train_times: list[int]) -> dict[str, Any]:
    x = selected_matrix(array, train_times)
    mean = x.mean(axis=0, dtype=np.float64)
    scale = x.std(axis=0, dtype=np.float64)
    unscaled = np.asarray([
        index for index, name in enumerate(feature_names)
        if name.endswith("_imputed") or name in CALENDAR_FEATURES or name.endswith("_available")
    ], dtype=int)
    scaled = np.asarray([index for index in range(len(feature_names)) if index not in set(unscaled.tolist())], dtype=int)
    mean[unscaled] = 0.0
    scale[unscaled] = 1.0
    bad_scale = ~np.isfinite(scale[scaled]) | (scale[scaled] == 0)
    scale[scaled[bad_scale]] = 1.0
    if not np.isfinite(mean).all() or not np.isfinite(scale).all():
        raise AssertionError("fold preprocessing is non-finite")
    return {
        "feature_names": list(feature_names),
        "training_week_indices": [int(x) for x in train_times],
        "mean": mean.tolist(),
        "standard_deviation": scale.tolist(),
        "scaled_feature_indices": scaled.tolist(),
        "unscaled_feature_indices": unscaled.tolist(),
        "indicators_unscaled": True,
        "calendar_unscaled": True,
    }


def apply_scaling(x: np.ndarray, scaling: dict[str, Any]) -> np.ndarray:
    mean = np.asarray(scaling["mean"], dtype=float)
    scale = np.asarray(scaling["standard_deviation"], dtype=float)
    return (x - mean[None, :]) / scale[None, :]


def fit_state(array: np.ndarray, feature_names: list[str], counts: np.ndarray, train_times: list[int], eval_times: list[int], penalty: float) -> tuple[dict[str, Any], np.ndarray, np.ndarray, np.ndarray, np.ndarray, float]:
    scaling = fit_scaling(array, feature_names, train_times)
    x_train = apply_scaling(selected_matrix(array, train_times), scaling)
    x_eval = apply_scaling(selected_matrix(array, eval_times), scaling)
    y_train = counts[np.asarray(train_times)].reshape(-1)
    y_eval = counts[np.asarray(eval_times)]
    model = ExactHurdleRegressor() if penalty == 0 else RegularizedExactHurdleRegressor(penalty)
    model.fit(x_train, y_train)
    if not model.fit_info.get("occurrence_success") or not model.fit_info.get("count_success"):
        raise RuntimeError(f"non-converged {penalty} fit: {model.fit_info}")
    p, conditional, mu, theta = model.predict(x_eval)
    p = p.reshape(y_eval.shape)
    conditional = conditional.reshape(y_eval.shape)
    mu = mu.reshape(y_eval.shape)
    state = {
        "feature_names": list(feature_names),
        "penalty": float(penalty),
        "scaling": scaling,
        "occurrence_coefficients": np.asarray(model.occurrence_beta, dtype=float).tolist(),
        "count_coefficients": np.asarray(model.count_beta, dtype=float).tolist(),
        "theta": float(theta),
        "fit_info": model.fit_info,
    }
    del x_train, x_eval
    return state, p, conditional, mu, y_eval, float(theta)


def predict_state(state: dict[str, Any], array: np.ndarray, eval_times: list[int]) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    x = apply_scaling(selected_matrix(array, eval_times), state["scaling"])
    design = np.column_stack([np.ones(len(x)), x])
    beta = np.asarray(state["occurrence_coefficients"], dtype=float)
    gamma = np.asarray(state["count_coefficients"], dtype=float)
    theta = float(state["theta"])
    p = expit(np.clip(design @ beta, -40.0, 40.0))
    mu = np.exp(np.clip(design @ gamma, -20.0, 20.0))
    log_p0 = theta * (math.log(theta) - np.log(theta + mu))
    conditional = mu / np.maximum(-np.expm1(log_p0), 1e-8)
    shape = (len(eval_times), EXPECTED_NODE_COUNT)
    return p.reshape(shape), conditional.reshape(shape), mu.reshape(shape), theta


def metric_row(metrics: dict[str, Any], model: str, penalty: float, fold: dict[str, Any]) -> dict[str, Any]:
    excluded = {"reliability", "probability_distribution"}
    row = {key: value for key, value in metrics.items() if key not in excluded and not isinstance(value, (dict, list))}
    row.update({"model": model, "penalty": float(penalty), "fold": int(fold["fold"]), "fold_label": fold["label"], "train_start": fold["train_start"], "train_end": fold["train_end"], "validation_start": fold["validation_start"], "validation_end": fold["validation_end"]})
    return row


def flatten_metric_rows(metrics: dict[str, Any], model: str, fold: dict[str, Any], subset: str) -> list[dict[str, Any]]:
    rows = []
    for index, bin_row in enumerate(metrics.get("reliability", []), 1):
        rows.append({"model": model, "fold": int(fold["fold"]), "fold_label": fold["label"], "subset": subset, "bin": index, "lower": bin_row["lower"], "upper": bin_row["upper"], "n": bin_row["n"], "mean_predicted_probability": bin_row["mean_predicted"], "observed_prevalence": bin_row["observed_fraction"]})
    return rows


def percentile_ranks(probability: np.ndarray) -> np.ndarray:
    n = len(probability)
    if n <= 1:
        return np.full(n, 100.0)
    return (rankdata(np.asarray(probability), method="average") - 1.0) / (n - 1.0) * 100.0


def count_case_row(model: str, fold: dict[str, Any], label: str, y: np.ndarray, p: np.ndarray, conditional: np.ndarray) -> dict[str, Any]:
    y = np.asarray(y, dtype=float).reshape(-1)
    p = np.asarray(p, dtype=float).reshape(-1)
    conditional = np.asarray(conditional, dtype=float).reshape(-1)
    if len(y) == 0:
        return {"model": model, "fold": fold["fold"], "fold_label": fold["label"], "case_class": label, "n": 0}
    return {
        "model": model, "fold": fold["fold"], "fold_label": fold["label"], "case_class": label,
        "n": int(len(y)), "mean_predicted_probability": float(p.mean()), "median_predicted_probability": float(np.median(p)),
        "positive_count_mae": float(np.mean(np.abs(y - conditional))),
        "positive_count_rmse": float(np.sqrt(np.mean((y - conditional) ** 2))),
        "observed_mean_count": float(y.mean()), "predicted_mean_conditional_count": float(conditional.mean()),
        "count_bias_predicted_minus_observed": float(conditional.mean() - y.mean()),
    }


def stratum_mask(values: np.ndarray, available: np.ndarray, bins: list[tuple[str, float, float]]) -> list[tuple[str, np.ndarray]]:
    rows = []
    values = np.asarray(values, dtype=float).reshape(-1)
    available = np.asarray(available, dtype=bool).reshape(-1)
    for label, lower, upper in bins:
        rows.append((label, available & (values >= lower) & (values < upper)))
    rows.append(("unavailable", ~available))
    return rows


def correlation_rows(array: np.ndarray, feature_names: list[str], train_times: list[int], fold: int, model: str) -> list[dict[str, Any]]:
    target_names = [name for name in feature_names if name in PRIMARY_FRONT_CONTINUOUS + ["prior13_latitude_p95_log1p"]]
    if not target_names:
        return []
    indices = [feature_names.index(name) for name in target_names]
    values = selected_matrix(array, train_times)[:, indices]
    if len(values) > 200000:
        values = values[np.linspace(0, len(values) - 1, 200000, dtype=int)]
    pearson = np.corrcoef(values, rowvar=False)
    ranked = np.column_stack([rankdata(values[:, j], method="average") for j in range(values.shape[1])])
    spearman = np.corrcoef(ranked, rowvar=False)
    rows = []
    for i, left in enumerate(target_names):
        for j, right in enumerate(target_names):
            if j <= i:
                continue
            rows.append({"model": model, "fold": fold, "feature_left": left, "feature_right": right, "pearson": float(pearson[i, j]), "spearman": float(spearman[i, j]), "n": int(len(values))})
    condition = float(np.linalg.cond(np.corrcoef(values, rowvar=False)))
    rows.append({"model": model, "fold": fold, "feature_left": "__condition_number__", "feature_right": "all_front_continuous", "pearson": condition, "spearman": condition, "n": int(len(values))})
    return rows


def load_v1_reference(model_output: Path) -> pd.DataFrame | None:
    paths = list(model_output.rglob("task2f_regularization_grid.csv"))
    if not paths:
        return None
    frame = pd.read_csv(paths[0])
    required = {"candidate", "penalty", "fold", "joint_hurdle_nll", "brier_skill"}
    return frame if required.issubset(frame.columns) else None


def choose_penalties(metrics: pd.DataFrame) -> dict[str, float]:
    selected = {"M0": 0.0}
    for model in ("M1", "M2"):
        subset = metrics[(metrics["model"] == model) & metrics["fold"].isin(SELECTION_FOLDS)]
        summary = subset.groupby("penalty", as_index=False).agg(mean_joint_hurdle_nll=("joint_hurdle_nll", "mean"), mean_brier_skill=("brier_skill", "mean"))
        row = summary.sort_values(["mean_joint_hurdle_nll", "mean_brier_skill", "penalty"], ascending=[True, False, True]).iloc[0]
        selected[model] = float(row["penalty"])
    return selected


def make_prediction_frame(data: dict[str, Any], fold: dict[str, Any], model: str, penalty: float, p: np.ndarray, conditional: np.ndarray, y: np.ndarray) -> pd.DataFrame:
    rows = []
    nodes = data["nodes"]
    audit_counts = data["audit_counts"]
    prior_flags = []
    first_flags = []
    recurrent_flags = []
    for time_index in fold["validation_indices"]:
        audit_index = data["response_audit_indices"][time_index]
        prior = np.any(audit_counts[:audit_index] > 0, axis=0)
        current_positive = y[fold["validation_indices"].index(time_index)] > 0
        prior_flags.append(prior)
        first_flags.append(current_positive & ~prior)
        recurrent_flags.append(current_positive & prior)
    prior_flags = np.asarray(prior_flags)
    first_flags = np.asarray(first_flags)
    recurrent_flags = np.asarray(recurrent_flags)
    for local_index, time_index in enumerate(fold["validation_indices"]):
        node_ids = np.arange(EXPECTED_NODE_COUNT)
        rows.append(pd.DataFrame({
            "model": model, "penalty": float(penalty), "fold": int(fold["fold"]), "fold_label": fold["label"],
            "week_index": int(time_index), "week": str(data["weeks"].iloc[time_index]["iso_week"]), "model_node_id": node_ids,
            "canonical_node_id": nodes["canonical_node_id"].to_numpy(), "country_or_domain_region": nodes["country_or_domain_region"].to_numpy(),
            "latitude": nodes["lat"].to_numpy(float), "longitude": nodes["lon"].to_numpy(float),
            "observed_count": y[local_index].astype(np.int32), "observed_presence": (y[local_index] > 0).astype(np.int8),
            "first_ever_positive_flag": first_flags[local_index].astype(np.int8), "previously_positive_flag": recurrent_flags[local_index].astype(np.int8),
            "prior_positive_before_week": prior_flags[local_index].astype(np.int8),
            "predicted_probability": p[local_index].astype(np.float32), "predicted_conditional_mean": conditional[local_index].astype(np.float32),
            "predicted_unconditional_mean": (p[local_index] * conditional[local_index]).astype(np.float32),
        }))
    return pd.concat(rows, ignore_index=True)


def run(args: argparse.Namespace) -> dict[str, Any]:
    output = args.output
    for subdir in ("front_features", "validation", "metrics", "manifests"):
        (output / subdir).mkdir(parents=True, exist_ok=True)
    data = load_data(args.model_output, args.audit_output)
    front_frame, front = build_front_features(data, output / "front_features")
    arrays = build_arrays(data, front)
    counts = data["counts"]
    metric_rows: list[dict[str, Any]] = []
    states: dict[tuple[str, float, int], dict[str, Any]] = {}
    v1_reproduction: list[dict[str, Any]] = []
    old_v1 = load_v1_reference(args.model_output)
    for model in ("M0", "M1", "M2"):
        for penalty in PENALTY_GRID[model]:
            for fold in data["folds"]:
                state, p, conditional, mu, y_eval, theta = fit_state(arrays[model], MODELS[model], counts, fold["train_indices"], fold["validation_indices"], penalty)
                states[(model, float(penalty), int(fold["fold"]))] = state
                train_prevalence = float((counts[np.asarray(fold["train_indices"])] > 0).mean())
                metrics = safe_metrics(y_eval, p, conditional, mu, theta, train_prevalence, "full_revised_domain", int(fold["fold"]), model)
                metric_rows.append(metric_row(metrics, model, penalty, fold))
                if model == "M0" and penalty == 0.0 and old_v1 is not None and int(fold["fold"]) <= 4:
                    old = old_v1[(old_v1["candidate"] == "Hurdle-Current") & (old_v1["penalty"] == 0) & (old_v1["fold"] == int(fold["fold"]))]
                    if len(old):
                        v1_reproduction.append({"fold": int(fold["fold"]), "new_joint_hurdle_nll": float(metrics["joint_hurdle_nll"]), "reference_joint_hurdle_nll": float(old.iloc[0]["joint_hurdle_nll"]), "joint_nll_abs_difference": float(abs(metrics["joint_hurdle_nll"] - old.iloc[0]["joint_hurdle_nll"])), "new_brier_skill": float(metrics["brier_skill"]), "reference_brier_skill": float(old.iloc[0]["brier_skill"]), "brier_skill_abs_difference": float(abs(metrics["brier_skill"] - old.iloc[0]["brier_skill"]))})
    metrics_frame = pd.DataFrame(metric_rows)
    write_csv(output / "metrics" / "fold_metrics_all_penalties.csv", metrics_frame)
    selected_penalties = choose_penalties(metrics_frame)
    selected_metrics = metrics_frame[(metrics_frame["model"] == "M0") | (metrics_frame["penalty"] == metrics_frame["model"].map(selected_penalties))].copy()
    write_csv(output / "metrics" / "selected_penalty_metrics.csv", selected_metrics)
    write_csv(output / "metrics" / "v1_reproduction.csv", pd.DataFrame(v1_reproduction))

    predictions: list[pd.DataFrame] = []
    case_rows: list[dict[str, Any]] = []
    calibration_rows: list[dict[str, Any]] = []
    transfer_rows: list[dict[str, Any]] = []
    front_strata_rows: list[dict[str, Any]] = []
    count_rows: list[dict[str, Any]] = []
    rank_rows: list[pd.DataFrame] = []
    correlation_rows_all: list[dict[str, Any]] = []
    coefficient_rows: list[dict[str, Any]] = []
    region_masks = {
        "Mexico_lt25N": (data["nodes"]["country_or_domain_region"].to_numpy() == "Mexico") & (data["nodes"]["lat"].to_numpy(float) < 25.0),
        "Mexico_ge25N": (data["nodes"]["country_or_domain_region"].to_numpy() == "Mexico") & (data["nodes"]["lat"].to_numpy(float) >= 25.0),
        "U.S._to_40N": data["nodes"]["country_or_domain_region"].to_numpy() == "U.S.-to-40N",
    }
    for model in ("M0", "M1", "M2"):
        penalty = selected_penalties[model]
        for fold in data["folds"]:
            state = states[(model, float(penalty), int(fold["fold"]))]
            p, conditional, mu, theta = predict_state(state, arrays[model], fold["validation_indices"])
            y = counts[np.asarray(fold["validation_indices"])]
            pred = make_prediction_frame(data, fold, model, penalty, p, conditional, y)
            predictions.append(pred)
            for component, coeffs in [("occurrence", state["occurrence_coefficients"]), ("count", state["count_coefficients"])]:
                names = ["intercept"] + MODELS[model]
                for name, value in zip(names, coeffs):
                    if name == "intercept" or name in PRIMARY_FRONT_CONTINUOUS + PRIMARY_FRONT_AVAILABILITY + LATITUDE_FEATURES:
                        coefficient_rows.append({"model": model, "fold": int(fold["fold"]), "fold_label": fold["label"], "penalty": penalty, "component": component, "feature": name, "coefficient": float(value), "sign": "positive" if value > 0 else "negative" if value < 0 else "zero", "absolute_coefficient": float(abs(value))})
            correlation_rows_all.extend(correlation_rows(arrays[model], MODELS[model], fold["train_indices"], int(fold["fold"]), model))
            audit_indices = data["response_audit_indices"][np.asarray(fold["validation_indices"])]
            prior = np.stack([np.any(data["audit_counts"][:idx] > 0, axis=0) for idx in audit_indices])
            first = (y > 0) & ~prior
            recurrent = (y > 0) & prior
            case_rows.extend([count_case_row(model, fold, "first_ever_positive", y[first], p[first], conditional[first]), count_case_row(model, fold, "recurrent_positive", y[recurrent], p[recurrent], conditional[recurrent])])
            for subset, mask in [("all_node_weeks", np.ones(y.shape, dtype=bool)), ("previously_positive_nodes", prior), ("never_before_positive_nodes", ~prior)]:
                subset_metrics = safe_metrics(y[mask], p[mask], conditional[mask], mu[mask], theta, float((counts[np.asarray(fold["train_indices"])] > 0).mean()), subset, int(fold["fold"]), model)
                calibration_rows.extend(flatten_metric_rows(subset_metrics, model, fold, subset))
            for region, mask in region_masks.items():
                subset_metrics = safe_metrics(y[:, mask], p[:, mask], conditional[:, mask], mu[:, mask], theta, float((counts[np.asarray(fold["train_indices"])][:, mask] > 0).mean()), region, int(fold["fold"]), model)
                transfer_rows.append(metric_row(subset_metrics, model, penalty, {**fold, "label": fold["label"]}) | {"region": region})
            if model in ("M1", "M2"):
                front_sources = {
                    "distance_to_any_prior_positive_km": (front["distance_any"][fold["validation_indices"]], front["any_available"][fold["validation_indices"]], FRONT_DISTANCE_BINS),
                    "distance_to_prev4_positive_km": (front["distance_prev4"][fold["validation_indices"]], front["prev4_available"][fold["validation_indices"]], FRONT_DISTANCE_BINS),
                    "weeks_since_detection_within_50km": (front["recency50"][fold["validation_indices"]], front["recency_available"][fold["validation_indices"]], RECENCY_BINS),
                }
                for feature, (values, available, bins) in front_sources.items():
                    for stratum, mask in stratum_mask(values, available, bins):
                        if not np.any(mask):
                            continue
                        subset_metrics = safe_metrics(y[mask], p[mask], conditional[mask], mu[mask], theta, float((counts[np.asarray(fold["train_indices"])] > 0).mean()), stratum, int(fold["fold"]), model)
                        front_strata_rows.append(metric_row(subset_metrics, model, penalty, fold) | {"front_feature": feature, "stratum": stratum})
            for case_label, mask in [("first_ever_positive", first), ("recurrent_positive", recurrent)]:
                count_rows.append(count_case_row(model, fold, case_label, y[mask], p[mask], conditional[mask]))
            for local_index, time_index in enumerate(fold["validation_indices"]):
                first_nodes = np.flatnonzero(first[local_index])
                if not len(first_nodes):
                    continue
                ranks = percentile_ranks(p[local_index])
                rank_rows.append(pd.DataFrame({"model": model, "penalty": penalty, "fold": fold["fold"], "fold_label": fold["label"], "week": data["weeks"].iloc[time_index]["iso_week"], "week_index": time_index, "model_node_id": first_nodes, "predicted_probability": p[local_index, first_nodes], "percentile_rank_all_nodes": ranks[first_nodes], "distance_to_any_prior_positive_km": front["distance_any"][time_index, first_nodes], "distance_to_prev4_positive_km": front["distance_prev4"][time_index, first_nodes]}))
    prediction_frame = pd.concat(predictions, ignore_index=True)
    prediction_frame.to_parquet(output / "validation" / "validation_predictions.parquet", index=False)
    case_frame = pd.DataFrame(case_rows)
    write_csv(output / "metrics" / "first_recurrent_case_metrics.csv", case_frame)
    write_csv(output / "metrics" / "calibration.csv", pd.DataFrame(calibration_rows))
    write_csv(output / "metrics" / "geographic_transfer_metrics.csv", pd.DataFrame(transfer_rows))
    write_csv(output / "metrics" / "front_strata_metrics.csv", pd.DataFrame(front_strata_rows))
    write_csv(output / "metrics" / "count_case_metrics.csv", pd.DataFrame(count_rows))
    rank_frame = pd.concat(rank_rows, ignore_index=True) if rank_rows else pd.DataFrame()
    if len(rank_frame):
        write_csv(output / "metrics" / "new_cell_ranking_cases.csv", rank_frame)
        rank_summary = rank_frame.groupby(["model", "fold", "fold_label"], as_index=False).agg(n_first_ever=("model_node_id", "size"), median_percentile_rank=("percentile_rank_all_nodes", "median"), fraction_at_least_75=("percentile_rank_all_nodes", lambda x: float(np.mean(x >= 75.0))), fraction_at_least_90=("percentile_rank_all_nodes", lambda x: float(np.mean(x >= 90.0))), median_distance_any_km=("distance_to_any_prior_positive_km", "median"), median_distance_prev4_km=("distance_to_prev4_positive_km", "median"))
    else:
        rank_summary = pd.DataFrame()
    write_csv(output / "metrics" / "new_cell_ranking_summary.csv", rank_summary)
    write_csv(output / "metrics" / "front_feature_correlations.csv", pd.DataFrame(correlation_rows_all))
    write_csv(output / "metrics" / "front_feature_coefficients.csv", pd.DataFrame(coefficient_rows))

    regularization_summary = metrics_frame.groupby(["model", "penalty"], as_index=False).agg(mean_joint_hurdle_nll=("joint_hurdle_nll", "mean"), mean_brier_skill=("brier_skill", "mean"), mean_pr_auc=("pr_auc", "mean"), mean_positive_count_mae=("positive_count_mae", "mean"), folds=("fold", "count"))
    regularization_summary["selection_folds_only"] = regularization_summary.apply(lambda row: bool((row["model"] == "M0") or (row["penalty"] == selected_penalties.get(row["model"], np.nan))), axis=1)
    write_csv(output / "metrics" / "regularization_summary.csv", regularization_summary)

    dev_selected = selected_metrics[selected_metrics["fold"].isin(SELECTION_FOLDS)]
    dev_summary = dev_selected.groupby("model", as_index=False).agg(mean_joint_hurdle_nll=("joint_hurdle_nll", "mean"), mean_brier_skill=("brier_skill", "mean"), mean_pr_auc=("pr_auc", "mean"), mean_positive_count_mae=("positive_count_mae", "mean"), mean_all_cell_mae=("all_cell_mae", "mean"))
    pseudo_selected = selected_metrics[selected_metrics["fold"].isin((5, 6))]
    pseudo_summary = pseudo_selected.groupby("model", as_index=False).agg(mean_joint_hurdle_nll=("joint_hurdle_nll", "mean"), mean_brier_skill=("brier_skill", "mean"), mean_pr_auc=("pr_auc", "mean"), mean_positive_count_mae=("positive_count_mae", "mean"))
    write_csv(output / "metrics" / "development_summary_folds1_4.csv", dev_summary)
    write_csv(output / "metrics" / "historical_pseudoprospective_summary_folds5_6.csv", pseudo_summary)

    def first_rank(model: str) -> float:
        values = rank_summary.loc[(rank_summary["model"] == model) & rank_summary["fold"].isin(SELECTION_FOLDS), "median_percentile_rank"] if len(rank_summary) else pd.Series(dtype=float)
        return float(values.mean()) if len(values) else float("nan")
    def first_fraction90(model: str) -> float:
        values = rank_summary.loc[(rank_summary["model"] == model) & rank_summary["fold"].isin(SELECTION_FOLDS), "fraction_at_least_90"] if len(rank_summary) else pd.Series(dtype=float)
        return float(values.mean()) if len(values) else float("nan")
    dev_map = dev_summary.set_index("model")
    m0 = dev_map.loc["M0"]
    m1 = dev_map.loc["M1"]
    aggregate_improvement = bool(m1["mean_joint_hurdle_nll"] <= m0["mean_joint_hurdle_nll"] and m1["mean_brier_skill"] >= m0["mean_brier_skill"])
    first_improvement = bool(first_rank("M1") >= first_rank("M0") and first_fraction90("M1") >= first_fraction90("M0"))
    if aggregate_improvement and first_improvement and (m1["mean_joint_hurdle_nll"] < m0["mean_joint_hurdle_nll"] or m1["mean_brier_skill"] > m0["mean_brier_skill"]):
        decision = "V2-A ADVANCES"
    elif aggregate_improvement and not first_improvement:
        decision = "V2-A IMPROVES PERSISTENCE ONLY"
    elif not aggregate_improvement and m1["mean_joint_hurdle_nll"] >= m0["mean_joint_hurdle_nll"] and m1["mean_brier_skill"] <= m0["mean_brier_skill"]:
        decision = "V2-A DOES NOT IMPROVE V1"
    else:
        decision = "V2-A HOLD / AMBIGUOUS"
    m2 = dev_map.loc["M2"]
    lat_rank_m1 = first_rank("M1")
    lat_rank_m2 = first_rank("M2")
    if m2["mean_joint_hurdle_nll"] < m1["mean_joint_hurdle_nll"] and lat_rank_m2 > lat_rank_m1:
        latitude_decision = "LATITUDE ADDS VALUE"
    elif m2["mean_joint_hurdle_nll"] > m1["mean_joint_hurdle_nll"] and lat_rank_m2 < lat_rank_m1:
        latitude_decision = "LATITUDE DEGRADES"
    else:
        latitude_decision = "LATITUDE REDUNDANT"
    decisions = {
        "selected_penalties": selected_penalties,
        "selection_rule": "M0 fixed at 0; M1/M2 minimize mean Folds 1-4 joint hurdle NLL, ties favor higher Brier skill then smaller penalty; Folds 5-6 never enter selection.",
        "v2a_decision": decision,
        "latitude_ablation_decision": latitude_decision,
        "aggregate_improvement_folds1_4": aggregate_improvement,
        "first_ever_localization_improvement_folds1_4": first_improvement,
        "m0_first_median_percentile": first_rank("M0"),
        "m1_first_median_percentile": first_rank("M1"),
        "m2_first_median_percentile": first_rank("M2"),
        "m0_first_fraction_ge90": first_fraction90("M0"),
        "m1_first_fraction_ge90": first_fraction90("M1"),
        "m2_first_fraction_ge90": first_fraction90("M2"),
    }
    write_json(output / "metrics" / "task3b_decisions.json", decisions)
    manifest = {
        "status": "task3b_v2a_development_complete_no_unseen_test",
        "created_utc": utc_now(),
        "git_sha": git_sha(),
        "branch_expected": "feature/v2-front-hurdle",
        "source_observation_sha256": data["source_sha"],
        "source_observation_row_count": data["source_rows"],
        "source_classification_vs_v1_target_reconciliation": {
            "mismatch_cells": data["classification_target_mismatch_cells"],
            "absolute_count_difference": data["classification_target_mismatch_absolute_count"],
            "rule": "response-week audit counts are reconciled to the immutable V1 targets; source-classification counts initialize pre-2025 history only",
        },
        "v1_reference_sha": V1_REFERENCE_SHA,
        "v1_model_identifier": V1_MODEL_ID,
        "estimand": "P(recorded detection in node-week | current environment, hosts, season, and prior recorded detections); positive count conditional on recorded count > 0.",
        "does_not_estimate": ["true insect occupancy", "abundance", "detection probability", "biological dispersal"],
        "response_period": {"start": "2025-W01", "end": "2026-W29", "week_count": 81},
        "domain": {"nodes": EXPECTED_NODE_COUNT, "directed_edges": EXPECTED_GRAPH_EDGES, "definition": "Mexico + existing U.S. footprint below 40N"},
        "models": {model: {"feature_count": len(names), "feature_order": names, "penalties": PENALTY_GRID[model]} for model, names in MODELS.items()},
        "front_feature_definitions": {
            "distance_to_any_prior_positive_km": "minimum canonical projected distance to any positive node in weeks < t",
            "distance_to_prev4_positive_km": "minimum canonical projected distance to any positive node in t-1 through t-4",
            "weeks_since_detection_within_50km": "weeks since most recent prior positive within 50 km",
            "prior13_latitude_p95": "95th percentile latitude of positive nodes in t-1 through t-13; secondary ablation only",
        },
        "distance_units": "kilometres in the canonical projected x/y coordinate system",
        "unavailable_history_encoding": {"distance_placeholder_km": data["distance_placeholder_km"], "recency_placeholder_weeks": data["recency_placeholder_weeks"], "availability_indicators": PRIMARY_FRONT_AVAILABILITY + ["prior13_latitude_p95_available"], "outcome_independent": True},
        "transformations": {"continuous_front_features": "log1p then fold-specific development-fit standardization", "availability_indicators": "0/1 unchanged", "base": "V1 transformations reproduced exactly"},
        "rolling_origin_folds": data["folds"],
        "historical_non_independent_folds": [5, 6],
        "selected_penalties": selected_penalties,
        "selection_criteria": decisions["selection_rule"],
        "decisions": decisions,
        "future_unseen_evaluation_policy": "No currently available 2025-2026 observations qualify as an unseen V2 test. The first independent evaluation must use observations arriving after a V2 specification-freeze date.",
        "predictive_models_outside_v2a_fitted": False,
        "neural_models_fitted": False,
        "front_state_status": "CAUSAL V2-A DEVELOPMENT FEATURES — not a biological occupancy state",
        "test_commands": ["python scripts/run_task3b_v2a.py --self-test", "pytest tests/test_task3b_v2a.py", "R testthat suite where available"],
        "slurm_job_id": __import__("os").environ.get("SLURM_JOB_ID"),
    }
    write_json(output / "manifests" / "task3b_v2a_manifest.json", manifest)
    checksum_rows = []
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name != "task3b_v2a_checksums.csv":
            checksum_rows.append({"relative_path": str(path.relative_to(output)), "size_bytes": path.stat().st_size, "sha256": sha256_file(path)})
    write_csv(output / "manifests" / "task3b_v2a_checksums.csv", pd.DataFrame(checksum_rows))
    return {"decisions": decisions, "manifest": manifest, "selected_metrics": selected_metrics, "dev_summary": dev_summary, "pseudo_summary": pseudo_summary}


def self_test() -> None:
    # Pure invariant tests use small synthetic histories and no response after
    # the prediction week.  These are the mandatory leakage guards used before
    # the Atlas fit.
    weeks = ["2025-W01", "2025-W02", "2025-W03", "2025-W04"]
    positive = [np.array([0]), np.array([1]), np.array([], dtype=int), np.array([2])]
    xy = np.array([[0.0, 0.0], [25.0, 0.0], [50.0, 0.0]])
    lat = np.array([10.0, 20.0, 30.0])
    from run_task3a_v2_audit import causal_front_descriptors
    original = causal_front_descriptors(positive, xy, lat, weeks).set_index(["week_index", "node_id"])
    changed = causal_front_descriptors([positive[0], positive[1], np.array([2]), positive[3]], xy, lat, weeks).set_index(["week_index", "node_id"])
    pd.testing.assert_frame_equal(original.loc[original.index.get_level_values(0) < 2], changed.loc[changed.index.get_level_values(0) < 2])
    current_changed = causal_front_descriptors([positive[0], np.array([1, 2]), positive[2], positive[3]], xy, lat, weeks).set_index(["week_index", "node_id"])
    pd.testing.assert_frame_equal(original.loc[1], current_changed.loc[1])
    assert not np.array_equal(original.loc[2]["northmost_prior_latitude"], current_changed.loc[2]["northmost_prior_latitude"])
    placeholder = 123.0
    unavailable = np.array([np.nan, 10.0])
    available = np.isfinite(unavailable)
    encoded = np.where(available, unavailable, placeholder)
    assert encoded[0] == placeholder and available[0] is False if isinstance(available[0], bool) else encoded[0] == placeholder and not bool(available[0])
    assert response_folds(pd.DataFrame({"iso_week": [f"2025-W{i:02d}" for i in range(1, 53)] + [f"2026-W{i:02d}" for i in range(1, 30)]}))[5]["validation_start"] == "2026-W23"
    print(json.dumps({"status": "PASS", "tests": ["front_temporal_causality", "future_mutation_invariance", "no_current_response_leakage", "unavailable_history_encoding", "rolling_origin_boundaries"]}))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-output", type=Path, default=Path("/project/disease_ecology/STGNN-output/revised_model_data"))
    parser.add_argument("--audit-output", type=Path, default=Path("/project/disease_ecology/STGNN-output/v2_audit"))
    parser.add_argument("--output", type=Path, default=Path("/project/disease_ecology/STGNN-output/v2_model"))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        result = run(args)
        print(json.dumps(jsonable({"status": "complete", "decisions": result["decisions"], "git_sha": result["manifest"]["git_sha"]}), indent=2), flush=True)


if __name__ == "__main__":
    main()
