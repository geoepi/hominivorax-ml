#!/usr/bin/env python3
"""Task 2F structured revised-domain hurdle development.

This runner evaluates the pre-specified current, spatial, temporal, and
spatiotemporal linear hurdle candidates using development weeks only.  The
terminal response target values are never loaded into the scoring arrays.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import sparse
from scipy.optimize import minimize

SCRIPT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_ROOT))
from run_task2e_baselines import (  # noqa: E402,E401
    CALENDAR_FEATURES,
    DENSITY_FEATURES,
    ENV_FEATURES,
    ExactHurdleRegressor,
    FEATURES,
    INDICATOR_FEATURES,
    add_intercept,
    flatten_metric_records,
    logistic_objective,
    safe_metrics,
    season_labels,
    write_csv,
    write_json,
    zt_nb_objective,
)

from scipy.special import digamma, expit  # noqa: E402


BASE_FEATURES = list(FEATURES)
L2_GRID = [0.0, 1e-5, 1e-4, 1e-3, 1e-2]
DEVELOPMENT_WEEKS = 68
EXPECTED_SOURCE_SHA = "a3d55f3ddf867087b578df803920bf59c6c303fa695e3218a5f3463e596d497e"
EXPECTED_SOURCE_ROWS = 136714
EXPECTED_GRAPH_EDGES = 77614
EXPECTED_NODE_COUNT = 10037
EXPECTED_RESPONSE_WEEKS = 81
EPS = 1e-8

CANDIDATES = {
    "Hurdle-Current": BASE_FEATURES,
    "Hurdle-Spatial": BASE_FEATURES
    + [f"{name}_localmean" for name in ENV_FEATURES + DENSITY_FEATURES],
    "Hurdle-Temporal": BASE_FEATURES
    + [f"{name}_lag1" for name in ENV_FEATURES]
    + [f"{name}_prev4mean" for name in ENV_FEATURES]
    + [f"{name}_prev13mean" for name in ENV_FEATURES],
    "Hurdle-Spatiotemporal": BASE_FEATURES
    + [f"{name}_localmean" for name in ENV_FEATURES + DENSITY_FEATURES]
    + [f"{name}_lag1" for name in ENV_FEATURES]
    + [f"{name}_prev4mean" for name in ENV_FEATURES]
    + [f"{name}_prev13mean" for name in ENV_FEATURES],
}


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def finite_float(value: Any) -> float | None:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if np.isfinite(value) else None


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


def load_inputs(root: Path) -> dict[str, Any]:
    raw = root / "raw"
    manifest = json.loads((root / "manifests" / "revised_production_manifest.json").read_text())
    source = manifest["observation_source"]
    if source["sha256"] != EXPECTED_SOURCE_SHA or int(source["row_count"]) != EXPECTED_SOURCE_ROWS:
        raise AssertionError("Task 2E source provenance does not match the authorized refreshed source")
    dynamic = np.load(raw / "dynamic_features.npy", mmap_mode="r")
    history = np.load(raw / "dynamic_history_features.npy", mmap_mode="r")
    static = np.load(raw / "static_features.npy", mmap_mode="r")
    counts_memmap = np.load(raw / "targets_count.npy", mmap_mode="r")
    presence_memmap = np.load(raw / "targets_presence.npy", mmap_mode="r")
    expected_shapes = {
        "dynamic": (81, 10037, 12),
        "history": (185, 10037, 12),
        "static": (10037, 10),
        "counts": (81, 10037),
        "presence": (81, 10037),
    }
    actual_shapes = {
        "dynamic": tuple(dynamic.shape),
        "history": tuple(history.shape),
        "static": tuple(static.shape),
        "counts": tuple(counts_memmap.shape),
        "presence": tuple(presence_memmap.shape),
    }
    if actual_shapes != expected_shapes:
        raise AssertionError(f"Task 2E shape mismatch: {actual_shapes}")
    # Read only development targets.  The terminal response values are never
    # materialized in this process.
    counts = np.asarray(counts_memmap[:DEVELOPMENT_WEEKS], dtype=np.int64)
    presence = np.asarray(presence_memmap[:DEVELOPMENT_WEEKS], dtype=np.int8)
    del counts_memmap, presence_memmap
    if not np.array_equal(presence, (counts > 0).astype(np.int8)):
        raise AssertionError("development presence does not equal count > 0")
    if np.any(counts < 0):
        raise AssertionError("negative development response count")
    if not np.isfinite(np.asarray(dynamic)).all() or not np.isfinite(np.asarray(history)).all():
        raise AssertionError("non-finite environmental covariates")
    static_values = np.asarray(static)
    if not np.isfinite(static_values).all() or np.any(static_values[:, :5] < 0) or not np.all(np.isin(static_values[:, 5:], [0, 1])):
        raise AssertionError("invalid static livestock features")
    weeks = pd.read_parquet(raw / "weeks.parquet")
    history_weeks = pd.read_parquet(raw / "history_weeks.parquet")
    calendar = pd.read_parquet(raw / "calendar_features.parquet")[CALENDAR_FEATURES].to_numpy(np.float64)
    nodes = pd.read_parquet(raw / "nodes.parquet")
    edges = pd.read_parquet(raw / "edges_queen.parquet")
    spatial = pd.read_parquet(root / "splits" / "spatial_node_assignments.parquet")
    splits = json.loads((root / "splits" / "temporal_splits.json").read_text())
    holdout = np.asarray(splits["final_test"]["indices"], dtype=np.int64)
    if not np.array_equal(holdout, np.arange(68, 81)):
        raise AssertionError("terminal holdout indices are not 68:80")
    if len(weeks) != EXPECTED_RESPONSE_WEEKS or len(history_weeks) != 185:
        raise AssertionError("unexpected response/history week count")
    if not np.array_equal(nodes["model_node_id"].to_numpy(), np.arange(EXPECTED_NODE_COUNT)):
        raise AssertionError("model node IDs are not contiguous")
    if len(edges) != EXPECTED_GRAPH_EDGES:
        raise AssertionError("persisted graph edge count changed")
    graph_checksum = sha256_file(raw / "edges_queen.parquet")
    if graph_checksum != manifest["revised_domain"]["graph_checksum"]:
        raise AssertionError("persisted graph checksum does not match Task 2E manifest")
    if not np.array_equal(spatial["model_node_id"].to_numpy(), np.arange(EXPECTED_NODE_COUNT)):
        raise AssertionError("spatial assignment node order changed")
    for fold in splits["temporal_folds"]:
        indices = list(fold["train_indices"]) + list(fold["validation_indices"])
        if any(int(index) >= DEVELOPMENT_WEEKS for index in indices):
            raise AssertionError("temporal fold accessed terminal holdout")
    return {
        "root": root,
        "dynamic": dynamic,
        "history": history,
        "static": static,
        "counts": counts,
        "presence": presence,
        "weeks": weeks,
        "history_weeks": history_weeks,
        "calendar": calendar,
        "nodes": nodes,
        "edges": edges,
        "spatial": spatial,
        "splits": splits,
        "manifest": manifest,
        "graph_checksum": graph_checksum,
        "source_sha": source["sha256"],
    }


def build_self_normalized_operator(edges: pd.DataFrame, node_count: int) -> sparse.csr_matrix:
    adjacency = sparse.coo_matrix(
        (np.ones(len(edges), dtype=np.float64), (edges["source_node"], edges["target_node"])),
        shape=(node_count, node_count),
    ).tocsr()
    operator = adjacency + sparse.identity(node_count, format="csr", dtype=np.float64)
    row_sum = np.asarray(operator.sum(axis=1)).ravel()
    if np.any(row_sum <= 0):
        raise AssertionError("self-normalized queen operator has an empty row")
    return sparse.diags(1.0 / row_sum) @ operator


def spatial_mean(operator: sparse.csr_matrix, values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=np.float64)
    if values.ndim == 2:
        return np.asarray(operator @ values)
    if values.ndim != 3:
        raise ValueError("spatial_mean expects [node,feature] or [week,node,feature]")
    return np.stack([np.asarray(operator @ values[index]) for index in range(values.shape[0])], axis=0)


def build_antecedents(history: np.ndarray, history_weeks: pd.DataFrame, response_weeks: pd.DataFrame) -> np.ndarray:
    history = np.asarray(history, dtype=np.float64)
    history_index = {str(label): index for index, label in enumerate(history_weeks["iso_week"].astype(str))}
    positions = np.asarray([history_index[str(label)] for label in response_weeks["iso_week"]], dtype=np.int64)
    if positions.min() < 13:
        raise AssertionError("history does not provide 13 preceding weeks for the earliest response week")
    blocks: list[np.ndarray] = []
    for lag in (1,):
        indices = positions - lag
        if np.any(indices >= positions):
            raise AssertionError("lag feature uses a future environmental week")
        blocks.append(history[indices])
    for width in (4, 13):
        indices = np.stack([positions - lag for lag in range(1, width + 1)], axis=1)
        if np.any(indices >= positions[:, None]):
            raise AssertionError("antecedent mean uses a future environmental week")
        blocks.append(history[indices].mean(axis=1))
    result = np.concatenate(blocks, axis=2)
    expected_width = history.shape[2] * 3
    if result.shape != (len(response_weeks), history.shape[1], expected_width):
        raise AssertionError(f"unexpected antecedent shape: {result.shape}")
    if not np.isfinite(result).all():
        raise AssertionError("antecedent environmental features are not finite")
    return result


def build_feature_arrays(data: dict[str, Any]) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    dynamic = np.asarray(data["dynamic"], dtype=np.float64)
    static = np.asarray(data["static"], dtype=np.float64)
    density = np.log1p(static[:, :5])
    indicators = static[:, 5:]
    calendar = np.asarray(data["calendar"], dtype=np.float64)
    t_count, node_count = dynamic.shape[:2]
    base = np.concatenate(
        [
            dynamic,
            np.broadcast_to(density[None, :, :], (t_count, node_count, 5)),
            np.broadcast_to(indicators[None, :, :], (t_count, node_count, 5)),
            np.broadcast_to(calendar[:, None, :], (t_count, node_count, 2)),
        ],
        axis=2,
    ).copy()
    operator = build_self_normalized_operator(data["edges"], node_count)
    local = np.concatenate(
        [spatial_mean(operator, dynamic), spatial_mean(operator, density[None, :, :])[0][None, :, :].repeat(t_count, axis=0)],
        axis=2,
    )
    # The previous expression uses the time-invariant livestock field; keep the
    # explicit shape check to guard against accidental response/time mixing.
    if local.shape != (t_count, node_count, 17):
        raise AssertionError(f"unexpected spatial feature shape: {local.shape}")
    antecedents = build_antecedents(data["history"], data["history_weeks"], data["weeks"])
    arrays = {
        "Hurdle-Current": base,
        "Hurdle-Spatial": np.concatenate([base, local], axis=2),
        "Hurdle-Temporal": np.concatenate([base, antecedents], axis=2),
        "Hurdle-Spatiotemporal": np.concatenate([base, local, antecedents], axis=2),
    }
    expected_widths = {"Hurdle-Current": 24, "Hurdle-Spatial": 41, "Hurdle-Temporal": 60, "Hurdle-Spatiotemporal": 77}
    for candidate, array in arrays.items():
        if array.shape != (81, node_count, expected_widths[candidate]):
            raise AssertionError(f"{candidate} feature shape mismatch: {array.shape}")
        if not np.isfinite(array).all():
            raise AssertionError(f"{candidate} contains non-finite predictors")
    qa = {
        "operator": "S = D_self^-1 (A + I), binary queen adjacency with focal self-loop",
        "operator_node_count": int(node_count),
        "operator_directed_edges": int(len(data["edges"])),
        "constant_field_invariant_max_error": float(np.max(np.abs(spatial_mean(operator, np.ones((node_count, 1))) - 1.0))),
        "isolated_node_count": int(np.sum(np.asarray(operator.getnnz(axis=1)) == 1)),
        "antecedent_response_week_count": int(antecedents.shape[0]),
        "antecedent_feature_count": int(antecedents.shape[2]),
        "earliest_response_iso_week": str(data["weeks"]["iso_week"].iloc[0]),
        "earliest_antecedent_max_history_index": int(min({str(label): index for index, label in enumerate(data["history_weeks"]["iso_week"].astype(str))}.values())),
        "feature_widths": expected_widths,
        "feature_names": {candidate: names for candidate, names in CANDIDATES.items()},
    }
    if qa["constant_field_invariant_max_error"] > 1e-12:
        raise AssertionError("spatial constant-field invariant failed")
    return arrays, qa


def select_matrix(array: np.ndarray, times: list[int] | np.ndarray, nodes: np.ndarray | None = None) -> np.ndarray:
    times = np.asarray(times, dtype=np.int64)
    node_ids = np.arange(array.shape[1], dtype=np.int64) if nodes is None else np.asarray(nodes, dtype=np.int64)
    return np.asarray(array[np.ix_(times, node_ids)], dtype=np.float64).reshape(-1, array.shape[2])


def select_targets(targets: np.ndarray, times: list[int] | np.ndarray, nodes: np.ndarray | None = None) -> np.ndarray:
    times = np.asarray(times, dtype=np.int64)
    if nodes is None:
        return np.asarray(targets[times], dtype=np.int64)
    return np.asarray(targets[np.ix_(times, np.asarray(nodes, dtype=np.int64))], dtype=np.int64)


def assert_development_only(indices: list[int] | np.ndarray) -> None:
    if any(int(index) >= DEVELOPMENT_WEEKS for index in indices):
        raise RuntimeError("Task 2F attempted to access terminal holdout response indices")


def feature_family_indices(candidate: str) -> tuple[np.ndarray, np.ndarray]:
    names = CANDIDATES[candidate]
    unscaled = np.asarray([index for index, name in enumerate(names) if name in INDICATOR_FEATURES + CALENDAR_FEATURES], dtype=np.int64)
    scaled = np.asarray([index for index in range(len(names)) if index not in set(unscaled.tolist())], dtype=np.int64)
    return scaled, unscaled


def fit_scaling(array: np.ndarray, train_times: list[int] | np.ndarray, train_nodes: np.ndarray | None) -> dict[str, Any]:
    assert_development_only(train_times)
    x = select_matrix(array, train_times, train_nodes)
    mean = x.mean(axis=0, dtype=np.float64)
    scale = x.std(axis=0, dtype=np.float64)
    # Current and local livestock fields have already received log1p before
    # spatial averaging; all other derived environmental fields are raw.
    scaled, unscaled = feature_family_indices("Hurdle-Current") if array.shape[2] == 24 else (None, None)
    if scaled is None:
        # Feature order is base, optional spatial, optional antecedent.  Only
        # indicator/calendar base positions remain unscaled.
        unscaled = np.asarray([i for i in range(array.shape[2]) if i in (17, 18, 19, 20, 21, 22, 23)], dtype=np.int64)
        scaled = np.asarray([i for i in range(array.shape[2]) if i not in set(unscaled.tolist())], dtype=np.int64)
    mean[unscaled] = 0.0
    scale[unscaled] = 1.0
    bad_scale = ~np.isfinite(scale[scaled]) | (scale[scaled] == 0)
    scale[scaled[bad_scale]] = 1.0
    return {
        "training_week_indices": [int(value) for value in train_times],
        "training_node_count": int(array.shape[1] if train_nodes is None else len(train_nodes)),
        "mean": mean.tolist(),
        "standard_deviation": scale.tolist(),
        "unscaled_feature_indices": unscaled.tolist(),
        "scaled_feature_indices": scaled.tolist(),
        "indicators_unscaled": True,
        "calendar_unscaled": True,
        "livestock_log1p_applied_before_spatial_mean": True,
    }


def apply_scaling(x: np.ndarray, scaling: dict[str, Any]) -> np.ndarray:
    mean = np.asarray(scaling["mean"], dtype=np.float64)
    scale = np.asarray(scaling["standard_deviation"], dtype=np.float64)
    return (x - mean[None, :]) / scale[None, :]


def regularized_logistic_objective(beta: np.ndarray, x: np.ndarray, y: np.ndarray, penalty: float) -> tuple[float, np.ndarray]:
    loss, gradient = logistic_objective(beta, x, y)
    loss += 0.5 * penalty * float(np.sum(beta[1:] ** 2))
    gradient = gradient.copy()
    gradient[1:] += penalty * beta[1:]
    return loss, gradient


def regularized_zt_nb_objective(params: np.ndarray, x: np.ndarray, y: np.ndarray, penalty: float) -> tuple[float, np.ndarray]:
    loss, gradient = zt_nb_objective(params, x, y)
    loss += 0.5 * penalty * float(np.sum(params[1:-1] ** 2))
    gradient = gradient.copy()
    gradient[1:-1] += penalty * params[1:-1]
    return loss, gradient


class RegularizedExactHurdleRegressor:
    def __init__(self, penalty: float, maxiter: int = 500) -> None:
        self.penalty = float(penalty)
        self.maxiter = int(maxiter)
        self.occurrence_beta: np.ndarray | None = None
        self.count_beta: np.ndarray | None = None
        self.theta: float | None = None
        self.fit_info: dict[str, Any] = {}

    def fit(self, x: np.ndarray, counts: np.ndarray) -> "RegularizedExactHurdleRegressor":
        y = (np.asarray(counts, dtype=np.int64) > 0).astype(np.float64)
        positive = np.asarray(counts, dtype=np.float64) > 0
        if not positive.any() or positive.all():
            raise ValueError("hurdle fit requires both zero and positive observations")
        x_design = add_intercept(x)
        occurrence = minimize(
            lambda beta: regularized_logistic_objective(beta, x_design, y, self.penalty),
            np.zeros(x_design.shape[1]),
            jac=True,
            method="L-BFGS-B",
            options={"maxiter": self.maxiter, "ftol": 1e-10, "gtol": 1e-7},
        )
        x_positive = x_design[positive]
        y_positive = np.asarray(counts, dtype=np.float64)[positive]
        mean_positive = max(float(y_positive.mean()), 1e-3)
        variance = float(y_positive.var())
        theta0 = max(mean_positive * mean_positive / max(variance - mean_positive, 1e-6), 0.1)
        count_start = np.zeros(x_design.shape[1] + 1, dtype=np.float64)
        count_start[0] = math.log(mean_positive)
        count_start[-1] = math.log(theta0)
        count = minimize(
            lambda params: regularized_zt_nb_objective(params, x_positive, y_positive, self.penalty),
            count_start,
            jac=True,
            method="L-BFGS-B",
            options={"maxiter": self.maxiter, "ftol": 1e-10, "gtol": 1e-7, "maxls": 40},
        )
        self.occurrence_beta = occurrence.x
        self.count_beta = count.x[:-1]
        self.theta = float(np.exp(np.clip(count.x[-1], -12.0, 12.0)))
        self.fit_info = {
            "objective": "exact_joint_hurdle_nll",
            "l2_penalty": self.penalty,
            "l2_penalty_excludes_intercepts_and_theta": True,
            "occurrence_success": bool(occurrence.success),
            "occurrence_message": str(occurrence.message),
            "occurrence_iterations": int(occurrence.nit),
            "count_success": bool(count.success),
            "count_message": str(count.message),
            "count_iterations": int(count.nit),
            "theta": self.theta,
            "training_rows": int(len(counts)),
            "training_positive_rows": int(positive.sum()),
        }
        return self

    def predict(self, x: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
        if self.occurrence_beta is None or self.count_beta is None or self.theta is None:
            raise RuntimeError("model has not been fitted")
        x_design = add_intercept(x)
        probability = expit(np.clip(x_design @ self.occurrence_beta, -40.0, 40.0))
        mu = np.exp(np.clip(x_design @ self.count_beta, -20.0, 20.0))
        log_p0 = self.theta * (math.log(self.theta) - np.log(self.theta + mu))
        conditional = mu / np.maximum(-np.expm1(log_p0), EPS)
        return probability, conditional, mu, self.theta


def fit_evaluate(
    array: np.ndarray,
    targets: np.ndarray,
    train_times: list[int] | np.ndarray,
    eval_times: list[int] | np.ndarray,
    penalty: float,
    train_nodes: np.ndarray | None = None,
    eval_nodes: np.ndarray | None = None,
    region: str = "full_revised_domain",
    fold: int = 0,
) -> dict[str, Any]:
    assert_development_only(list(train_times) + list(eval_times))
    if train_nodes is None:
        train_nodes = np.arange(array.shape[1], dtype=np.int64)
    if eval_nodes is None:
        eval_nodes = np.arange(array.shape[1], dtype=np.int64)
    scaling = fit_scaling(array, train_times, train_nodes)
    x_train = apply_scaling(select_matrix(array, train_times, train_nodes), scaling)
    x_eval = apply_scaling(select_matrix(array, eval_times, eval_nodes), scaling)
    y_train = select_targets(targets, train_times, train_nodes).reshape(-1)
    y_eval = select_targets(targets, eval_times, eval_nodes)
    model = (ExactHurdleRegressor() if penalty == 0.0 else RegularizedExactHurdleRegressor(penalty)).fit(x_train, y_train)
    probability, conditional, mu, theta = model.predict(x_eval)
    probability = probability.reshape(y_eval.shape)
    conditional = conditional.reshape(y_eval.shape)
    mu = mu.reshape(y_eval.shape)
    train_prevalence = float(np.mean(y_train > 0))
    metrics = safe_metrics(y_eval, probability, conditional, mu, theta, train_prevalence, region, fold, "structured")
    return {
        "metrics": metrics,
        "scaling": scaling,
        "model": model,
        "probability": probability,
        "conditional": conditional,
        "mu": mu,
        "theta": theta,
        "y_eval": y_eval,
        "y_train": y_train,
    }


def temporal_grid(data: dict[str, Any], arrays: dict[str, np.ndarray], output: Path) -> tuple[list[dict[str, Any]], dict[str, float]]:
    rows: list[dict[str, Any]] = []
    output.mkdir(parents=True, exist_ok=True)
    for candidate, array in arrays.items():
        for penalty in L2_GRID:
            print(f"grid {candidate} penalty={penalty:g}", flush=True)
            for fold_record in data["splits"]["temporal_folds"]:
                fold = int(fold_record["fold"])
                result = fit_evaluate(array, data["counts"], fold_record["train_indices"], fold_record["validation_indices"], penalty, fold=fold)
                row = dict(result["metrics"])
                row.update({"candidate": candidate, "penalty": penalty, "fold": fold, "occurrence_success": result["model"].fit_info["occurrence_success"], "count_success": result["model"].fit_info["count_success"]})
                rows.append(row)
    write_csv(output / "validation" / "task2f_regularization_grid.csv", rows)
    selected: dict[str, float] = {}
    summary_rows: list[dict[str, Any]] = []
    frame = pd.DataFrame(rows)
    for candidate in arrays:
        for penalty in L2_GRID:
            subset = frame[(frame["candidate"] == candidate) & (frame["penalty"] == penalty)]
            summary_rows.append({
                "candidate": candidate,
                "penalty": penalty,
                "mean_joint_hurdle_nll": float(subset["joint_hurdle_nll"].mean()),
                "median_joint_hurdle_nll": float(subset["joint_hurdle_nll"].median()),
                "sd_joint_hurdle_nll": float(subset["joint_hurdle_nll"].std(ddof=0)),
                "mean_brier_skill": float(subset["brier_skill"].mean()),
                "mean_pr_auc": float(subset["pr_auc"].mean()),
                "fold4_brier_skill": float(subset.loc[subset["fold"] == 4, "brier_skill"].iloc[0]),
                "all_fits_converged": bool(subset["occurrence_success"].all() and subset["count_success"].all()),
            })
        candidate_summary = [row for row in summary_rows if row["candidate"] == candidate]
        if candidate == "Hurdle-Current":
            selected[candidate] = 0.0
        else:
            selected[candidate] = min(candidate_summary, key=lambda row: (row["mean_joint_hurdle_nll"], -row["mean_brier_skill"], row["penalty"]))["penalty"]
    write_csv(output / "validation" / "task2f_regularization_summary.csv", summary_rows)
    write_json(output / "manifests" / "task2f_selected_penalties.json", {"selected_penalties": selected, "selection_rule": "Hurdle-Current is locked at 0 to reproduce Task 2E; each augmented candidate minimizes mean four-fold exact joint hurdle NLL, ties favor Brier skill then smaller penalty", "grid": L2_GRID})
    return rows, selected


def prediction_frame(data: dict[str, Any], candidate: str, penalty: float, fold: int, eval_times: list[int], y: np.ndarray, probability: np.ndarray, conditional: np.ndarray) -> pd.DataFrame:
    node_count = len(data["nodes"])
    nodes = data["nodes"]
    seasons = season_labels(data["weeks"])
    lat_band = pd.cut(nodes["lat"], [-np.inf, 20, 25, 30, 35, 40], labels=["<20N", "20-25N", "25-30N", "30-35N", "35-40N"], right=False).astype(str).to_numpy()
    times = np.repeat(np.asarray(eval_times, dtype=np.int16), node_count)
    node_ids = np.tile(np.arange(node_count, dtype=np.int32), len(eval_times))
    observed = np.asarray(y).reshape(-1)
    predicted_probability = np.asarray(probability).reshape(-1)
    predicted_conditional = np.asarray(conditional).reshape(-1)
    return pd.DataFrame({
        "model": candidate,
        "penalty": float(penalty),
        "fold": int(fold),
        "node_id": node_ids,
        "week": data["weeks"]["iso_week"].astype(str).to_numpy()[times],
        "latitude_band": lat_band[node_ids],
        "season": seasons[times],
        "observed_presence": (observed > 0).astype(np.int8),
        "observed_count": observed.astype(np.int32),
        "predicted_probability": predicted_probability,
        "predicted_conditional_mean": predicted_conditional,
        "predicted_unconditional_mean": predicted_probability * predicted_conditional,
    })


def final_temporal_evaluation(data: dict[str, Any], arrays: dict[str, np.ndarray], selected: dict[str, float], output: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[tuple[str, int], dict[str, Any]]]:
    temporal: list[dict[str, Any]] = []
    seasonal: list[dict[str, Any]] = []
    latitude: list[dict[str, Any]] = []
    regional: list[dict[str, Any]] = []
    coefficients: list[dict[str, Any]] = []
    fitted: dict[tuple[str, int], dict[str, Any]] = {}
    seasons = season_labels(data["weeks"])
    lat_band = pd.cut(data["nodes"]["lat"], [-np.inf, 20, 25, 30, 35, 40], labels=["<20N", "20-25N", "25-30N", "30-35N", "35-40N"], right=False).astype(str).to_numpy()
    for candidate, array in arrays.items():
        prediction_parts: list[pd.DataFrame] = []
        penalty = selected[candidate]
        for fold_record in data["splits"]["temporal_folds"]:
            fold = int(fold_record["fold"])
            result = fit_evaluate(array, data["counts"], fold_record["train_indices"], fold_record["validation_indices"], penalty, fold=fold)
            if not result["model"].fit_info["occurrence_success"] or not result["model"].fit_info["count_success"]:
                raise RuntimeError(f"{candidate} fold {fold} did not converge at selected penalty {penalty}")
            metrics = dict(result["metrics"])
            metrics.update({"candidate": candidate, "penalty": penalty, "fold": fold, "fit_info": result["model"].fit_info})
            temporal.append(metrics)
            fitted[(candidate, fold)] = result
            prediction_parts.append(prediction_frame(data, candidate, penalty, fold, fold_record["validation_indices"], result["y_eval"], result["probability"], result["conditional"]))
            eval_times = np.asarray(fold_record["validation_indices"], dtype=np.int64)
            y = result["y_eval"]
            for season in ("winter", "spring", "summer", "fall"):
                mask = seasons[eval_times] == season
                if mask.any():
                    season_metrics = safe_metrics(y[mask], result["probability"][mask], result["conditional"][mask], result["mu"][mask], result["theta"], float(np.mean(result["y_train"] > 0)), season, fold, candidate)
                    season_metrics.update({"candidate": candidate, "penalty": penalty, "fold": fold, "season": season})
                    seasonal.append(season_metrics)
            for band in ("<20N", "20-25N", "25-30N", "30-35N", "35-40N"):
                mask = lat_band == band
                band_metrics = safe_metrics(y[:, mask], result["probability"][:, mask], result["conditional"][:, mask], result["mu"][:, mask], result["theta"], float(np.mean(result["y_train"] > 0)), band, fold, candidate)
                band_metrics.update({"candidate": candidate, "penalty": penalty, "fold": fold, "latitude_band": band})
                latitude.append(band_metrics)
            for region, mask in {
                "full_revised_domain": np.ones(len(data["nodes"]), dtype=bool),
                "Mexico": data["nodes"]["country_or_domain_region"].to_numpy() == "Mexico",
                "U.S.": data["nodes"]["country_or_domain_region"].to_numpy() == "U.S.-to-40N",
            }.items():
                region_metrics = safe_metrics(y[:, mask], result["probability"][:, mask], result["conditional"][:, mask], result["mu"][:, mask], result["theta"], float(np.mean(result["y_train"] > 0)), region, fold, candidate)
                region_metrics.update({"candidate": candidate, "penalty": penalty, "fold": fold})
                regional.append(region_metrics)
            for component, beta in (("occurrence", result["model"].occurrence_beta), ("positive_count", result["model"].count_beta)):
                coefficients.extend({"candidate": candidate, "penalty": penalty, "fold": fold, "component": component, "feature": "intercept" if index == 0 else CANDIDATES[candidate][index - 1], "coefficient_standardized": float(value), "sign": "positive" if value > 0 else ("negative" if value < 0 else "zero"), "absolute_magnitude": abs(float(value))} for index, value in enumerate(beta))
        pd.concat(prediction_parts, ignore_index=True).to_parquet(output / "predictions" / f"{slug(candidate)}_temporal.parquet", index=False)
    write_csv(output / "validation" / "task2f_temporal_metrics.csv", flatten_metric_records([{"metrics": row} for row in temporal]))
    write_csv(output / "validation" / "task2f_seasonal_metrics.csv", seasonal)
    write_csv(output / "validation" / "task2f_latitude_metrics.csv", latitude)
    write_csv(output / "validation" / "task2f_regional_metrics.csv", regional)
    write_csv(output / "diagnostics" / "task2f_coefficients.csv", coefficients)
    return temporal, seasonal, latitude, regional, coefficients, fitted


def summarize_temporal(temporal: list[dict[str, Any]], output: Path) -> list[dict[str, Any]]:
    frame = pd.DataFrame(temporal)
    rows: list[dict[str, Any]] = []
    for candidate in CANDIDATES:
        subset = frame[frame["candidate"] == candidate]
        row = {"candidate": candidate, "penalty": float(subset["penalty"].iloc[0]), "feature_count": len(CANDIDATES[candidate])}
        for metric in ("joint_hurdle_nll", "brier", "brier_skill", "pr_auc", "roc_auc", "positive_count_mae", "positive_count_rmse", "bernoulli_nll", "zt_nb_nll"):
            values = pd.to_numeric(subset[metric], errors="coerce")
            row[f"{metric}_mean"] = float(values.mean())
            row[f"{metric}_median"] = float(values.median())
            row[f"{metric}_sd"] = float(values.std(ddof=0))
            row[f"{metric}_worst_fold"] = float(values.min() if metric in ("brier_skill", "pr_auc", "roc_auc") else values.max())
            fold4 = subset.loc[subset["fold"] == 4, metric]
            row[f"{metric}_fold4"] = finite_float(fold4.iloc[0]) if len(fold4) else None
        rows.append(row)
    write_csv(output / "validation" / "task2f_candidate_summary.csv", rows)
    return rows


def northward_transfer(data: dict[str, Any], arrays: dict[str, np.ndarray], selected: dict[str, float], output: Path) -> list[dict[str, Any]]:
    nodes = data["nodes"]
    mexico = nodes["country_or_domain_region"].to_numpy() == "Mexico"
    south = mexico & (nodes["lat"].to_numpy(float) < 25.0)
    north = mexico & (nodes["lat"].to_numpy(float) >= 25.0)
    if not south.any() or not north.any():
        raise AssertionError("northward-transfer proxy lacks one of its fixed Mexico latitude strata")
    dev_times = np.arange(DEVELOPMENT_WEEKS, dtype=np.int64)
    rows: list[dict[str, Any]] = []
    for candidate, array in arrays.items():
        result = fit_evaluate(array, data["counts"], dev_times, dev_times, selected[candidate], np.flatnonzero(south), np.flatnonzero(north), "Mexico>=25N_transfer_proxy", 0)
        row = dict(result["metrics"])
        row.update({"candidate": candidate, "penalty": selected[candidate], "training_region": "Mexico<25N", "evaluation_region": "Mexico>=25N", "training_node_count": int(south.sum()), "evaluation_node_count": int(north.sum()), "training_positive_count": int((result["y_train"] > 0).sum()), "evaluation_positive_count": int((result["y_eval"] > 0).sum()), "development_only": True, "not_us_validation": True})
        rows.append(row)
    write_csv(output / "validation" / "task2f_northward_transfer_proxy.csv", rows)
    return rows


def finalist_candidates(summary: list[dict[str, Any]]) -> tuple[str, list[str]]:
    augmented = [row for row in summary if row["candidate"] != "Hurdle-Current"]
    best = min(augmented, key=lambda row: (-row["brier_skill_mean"], row["joint_hurdle_nll_mean"], row["feature_count"]))["candidate"]
    return best, ["Hurdle-Current", best]


def spatial_validation(data: dict[str, Any], arrays: dict[str, np.ndarray], selected: dict[str, float], finalists: list[str], output: Path) -> list[dict[str, Any]]:
    dev_times = np.arange(DEVELOPMENT_WEEKS, dtype=np.int64)
    folds = np.sort(data["spatial"]["spatial_fold"].unique())
    rows: list[dict[str, Any]] = []
    for candidate in finalists:
        for spatial_fold in folds:
            train_nodes = np.flatnonzero(data["spatial"]["spatial_fold"].to_numpy() != spatial_fold)
            eval_nodes = np.flatnonzero(data["spatial"]["spatial_fold"].to_numpy() == spatial_fold)
            result = fit_evaluate(arrays[candidate], data["counts"], dev_times, dev_times, selected[candidate], train_nodes, eval_nodes, "spatial_holdout_nodes", int(spatial_fold))
            row = dict(result["metrics"])
            row.update({"candidate": candidate, "penalty": selected[candidate], "spatial_fold": int(spatial_fold), "evaluated_nodes": int(len(eval_nodes)), "training_nodes": int(len(train_nodes))})
            rows.append(row)
            for region, mask in (("Mexico", data["nodes"].iloc[eval_nodes]["country_or_domain_region"].to_numpy() == "Mexico"), ("U.S.", data["nodes"].iloc[eval_nodes]["country_or_domain_region"].to_numpy() == "U.S.-to-40N")):
                if mask.any():
                    regional = safe_metrics(result["y_eval"][:, mask], result["probability"][:, mask], result["conditional"][:, mask], result["mu"][:, mask], result["theta"], float(np.mean(result["y_train"] > 0)), region, int(spatial_fold), candidate)
                    regional.update({"candidate": candidate, "penalty": selected[candidate], "spatial_fold": int(spatial_fold), "evaluated_nodes": int(mask.sum())})
                    rows.append(regional)
    write_csv(output / "validation" / "task2f_spatial_metrics.csv", rows)
    return rows


def combined_pairs(train_times: list[int], validation_times: list[int], train_nodes: np.ndarray, eval_nodes: np.ndarray, node_count: int) -> tuple[np.ndarray, np.ndarray]:
    assert_development_only(list(train_times) + list(validation_times))
    train_mask = np.zeros((DEVELOPMENT_WEEKS, node_count), dtype=bool)
    train_mask[np.ix_(np.asarray(train_times), np.asarray(train_nodes))] = True
    eval_mask = np.zeros_like(train_mask)
    eval_mask[np.asarray(validation_times), :] = True
    eval_mask[:, np.asarray(eval_nodes)] = True
    if np.any(train_mask & eval_mask):
        raise AssertionError("combined validation train/evaluation masks overlap")
    return np.argwhere(train_mask), np.argwhere(eval_mask)


def combined_validation(data: dict[str, Any], arrays: dict[str, np.ndarray], selected: dict[str, float], finalists: list[str], output: Path) -> list[dict[str, Any]]:
    spatial_folds = np.sort(data["spatial"]["spatial_fold"].unique())
    spatial_values = data["spatial"]["spatial_fold"].to_numpy()
    rows: list[dict[str, Any]] = []
    for candidate in finalists:
        for fold_record in data["splits"]["temporal_folds"]:
            temporal_fold = int(fold_record["fold"])
            train_times = np.asarray(fold_record["train_indices"], dtype=np.int64)
            validation_times = np.asarray(fold_record["validation_indices"], dtype=np.int64)
            for spatial_fold in spatial_folds:
                train_nodes = np.flatnonzero(spatial_values != spatial_fold)
                eval_nodes = np.flatnonzero(spatial_values == spatial_fold)
                train_pairs, eval_pairs = combined_pairs(train_times, validation_times, train_nodes, eval_nodes, len(data["nodes"]))
                array = arrays[candidate]
                scaling = fit_scaling(array, train_times, train_nodes)
                x_train = apply_scaling(array[train_pairs[:, 0], train_pairs[:, 1], :], scaling)
                x_eval = apply_scaling(array[eval_pairs[:, 0], eval_pairs[:, 1], :], scaling)
                y_train = data["counts"][train_pairs[:, 0], train_pairs[:, 1]]
                y_eval = data["counts"][eval_pairs[:, 0], eval_pairs[:, 1]]
                model = RegularizedExactHurdleRegressor(selected[candidate]).fit(x_train, y_train)
                probability, conditional, mu, theta = model.predict(x_eval)
                metrics = safe_metrics(y_eval, probability, conditional, mu, theta, float(np.mean(y_train > 0)), "combined_development", temporal_fold * 10 + int(spatial_fold), candidate)
                metrics.update({"candidate": candidate, "penalty": selected[candidate], "temporal_fold": temporal_fold, "spatial_fold": int(spatial_fold), "training_rows": int(len(y_train)), "evaluation_rows": int(len(y_eval)), "training_nodes": int(len(train_nodes)), "evaluation_nodes": int(len(eval_nodes))})
                rows.append(metrics)
    write_csv(output / "validation" / "task2f_combined_metrics.csv", rows)
    return rows


def coefficient_summary(coefficients: list[dict[str, Any]], output: Path) -> None:
    frame = pd.DataFrame(coefficients)
    rows: list[dict[str, Any]] = []
    for (candidate, component, feature), subset in frame.groupby(["candidate", "component", "feature"], sort=False):
        values = subset["coefficient_standardized"].to_numpy(float)
        signs = np.sign(values)
        rows.append({"candidate": candidate, "component": component, "feature": feature, "fold_count": len(values), "mean": float(values.mean()), "sd": float(values.std(ddof=0)), "mean_absolute": float(np.abs(values).mean()), "max_absolute": float(np.abs(values).max()), "sign_stability": float(max(np.mean(signs > 0), np.mean(signs < 0), np.mean(signs == 0)))})
    write_csv(output / "diagnostics" / "task2f_coefficient_stability.csv", rows)
    frame["family"] = np.where(frame["feature"].str.endswith("_localmean"), "spatial_local_mean", np.where(frame["feature"].str.endswith("_lag1"), "environment_lag1", np.where(frame["feature"].str.endswith("_prev4mean"), "environment_prev4mean", np.where(frame["feature"].str.endswith("_prev13mean"), "environment_prev13mean", "base"))))
    family = frame.groupby(["candidate", "component", "family"], as_index=False).agg(mean_absolute=("absolute_magnitude", "mean"), max_absolute=("absolute_magnitude", "max"), mean_coefficient=("coefficient_standardized", "mean"), sd_coefficient=("coefficient_standardized", "std"))
    write_csv(output / "diagnostics" / "task2f_coefficient_family_summary.csv", family.to_dict("records"))


def compare_reference(data: dict[str, Any], temporal: list[dict[str, Any]], output: Path) -> dict[str, Any]:
    reference_path = data["root"] / "validation" / "task2e_baseline_metrics.csv"
    reference = pd.read_csv(reference_path)
    reference = reference[(reference["model"] == "current_week_exact_hurdle") & (reference["region"] == "full_revised_domain")]
    current = pd.DataFrame([row for row in temporal if row["candidate"] == "Hurdle-Current"])
    comparisons: list[dict[str, Any]] = []
    for fold in range(1, 5):
        left = reference[reference["fold"] == fold].iloc[0]
        right = current[current["fold"] == fold].iloc[0]
        for metric in ("brier", "brier_skill", "pr_auc", "joint_hurdle_nll"):
            comparisons.append({"fold": fold, "metric": metric, "task2e": float(left[metric]), "task2f": float(right[metric]), "absolute_difference": abs(float(left[metric]) - float(right[metric]))})
    max_difference = max(row["absolute_difference"] for row in comparisons)
    result = {"passed": bool(max_difference <= 1e-4), "maximum_absolute_difference": max_difference, "tolerance": 1e-4, "comparison": comparisons}
    write_json(output / "diagnostics" / "task2e_baseline_reproduction.json", result)
    if not result["passed"]:
        raise AssertionError(f"Task 2E current baseline reproduction failed: {max_difference}")
    return result


def classify_and_select(summary: list[dict[str, Any]], spatial: list[dict[str, Any]], combined: list[dict[str, Any]], output: Path) -> dict[str, Any]:
    by_candidate = {row["candidate"]: row for row in summary}
    current = by_candidate["Hurdle-Current"]
    spatial_full = pd.DataFrame([row for row in spatial if row.get("region") == "spatial_holdout_nodes"])
    combined_frame = pd.DataFrame(combined)
    decisions: list[dict[str, Any]] = []
    for candidate in CANDIDATES:
        if candidate == "Hurdle-Current":
            continue
        row = by_candidate[candidate]
        spatial_candidate = spatial_full[spatial_full["candidate"] == candidate]
        combined_candidate = combined_frame[combined_frame["candidate"] == candidate]
        spatial_skill = float(spatial_candidate["brier_skill"].mean()) if len(spatial_candidate) else None
        combined_skill = float(combined_candidate["brier_skill"].mean()) if len(combined_candidate) else None
        evidence = {
            "candidate": candidate,
            "mean_brier_skill_delta": row["brier_skill_mean"] - current["brier_skill_mean"],
            "fold4_brier_skill_delta": row["brier_skill_fold4"] - current["brier_skill_fold4"],
            "mean_joint_hurdle_nll_delta": row["joint_hurdle_nll_mean"] - current["joint_hurdle_nll_mean"],
            "mean_pr_auc_delta": row["pr_auc_mean"] - current["pr_auc_mean"],
            "mean_spatial_brier_skill": spatial_skill,
            "mean_combined_brier_skill": combined_skill,
        }
        evidence["material_consistency_rule"] = {
            "mean_brier_skill_delta_at_least": 0.005,
            "fold4_brier_skill_delta_at_least": -0.005,
            "joint_nll_delta_at_most": 0.005,
            "pr_auc_delta_at_least": -0.01,
            "spatial_brier_skill_delta_at_least": -0.005,
            "combined_brier_skill_delta_at_least": -0.005,
        }
        evidence["passes_material_consistency_rule"] = bool(
            evidence["mean_brier_skill_delta"] >= 0.005
            and evidence["fold4_brier_skill_delta"] >= -0.005
            and evidence["mean_joint_hurdle_nll_delta"] <= 0.005
            and evidence["mean_pr_auc_delta"] >= -0.01
            and spatial_skill is not None
            and spatial_skill >= float(spatial_full[spatial_full["candidate"] == "Hurdle-Current"]["brier_skill"].mean()) - 0.005
            and combined_skill is not None
            and combined_skill >= float(combined_frame[combined_frame["candidate"] == "Hurdle-Current"]["brier_skill"].mean()) - 0.005
        )
        decisions.append(evidence)
    advancing = [row for row in decisions if row["passes_material_consistency_rule"]]
    if advancing:
        preferred = min(advancing, key=lambda row: (-row["mean_brier_skill_delta"], CANDIDATES[row["candidate"]].__len__()))["candidate"]
        classification = "AUGMENTATION ADVANCES"
    else:
        preferred = "Hurdle-Current"
        any_partial = any(row["mean_brier_skill_delta"] > 0 or row["fold4_brier_skill_delta"] > 0 for row in decisions)
        classification = "HOLD / AMBIGUOUS" if any_partial else "NO MATERIAL AUGMENTATION BENEFIT"
    result = {
        "preferred_candidate": preferred,
        "preferred_penalty": float(by_candidate[preferred]["penalty"]),
        "reference_comparator": "Hurdle-Current",
        "augmentation_classification": classification,
        "candidate_decisions": decisions,
        "selection_rule": "No composite score; an augmented candidate must meet every pre-specified material-consistency guardrail, and ties favor the smaller feature set.",
        "gconvgru_status": "DO NOT ADVANCE",
        "terminal_holdout_metrics_calculated": False,
        "terminal_us_positive_outcomes_inspected": False,
    }
    write_json(output / "manifests" / "task2f_model_selection.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-output", type=Path, required=True)
    args = parser.parse_args()
    output = args.model_output / "structured"
    for subdir in ("features", "predictions", "validation", "diagnostics", "manifests"):
        (output / subdir).mkdir(parents=True, exist_ok=True)
    started = time.time()
    data = load_inputs(args.model_output)
    arrays, feature_qa = build_feature_arrays(data)
    write_json(output / "diagnostics" / "task2f_feature_qa.json", feature_qa)
    feature_manifest = {
        "task": "2F",
        "source_dataset_sha256": data["source_sha"],
        "source_git_sha": git_sha(),
        "task2e_manifest_git_sha": data["manifest"]["git_sha"],
        "spatial_operator": feature_qa["operator"],
        "temporal_definitions": {"lag1": "X(t-1)", "prev4mean": "mean(X(t-1),...,X(t-4))", "prev13mean": "mean(X(t-1),...,X(t-13))"},
        "candidate_feature_names": CANDIDATES,
        "candidate_feature_counts": {candidate: len(names) for candidate, names in CANDIDATES.items()},
        "regularization_grid": L2_GRID,
        "fold_definitions": data["splits"]["temporal_folds"],
        "terminal_holdout": data["splits"]["final_test"],
        "terminal_holdout_guard": "response indices 68:80 are never loaded into scoring arrays",
        "l2_formula": "0.5 * penalty * sum(non_intercept_coefficients^2); global theta is unpenalized",
    }
    write_json(output / "manifests" / "task2f_feature_manifest.json", feature_manifest)
    grid_rows, selected = temporal_grid(data, arrays, output)
    temporal, seasonal, latitude, regional, coefficients, fitted = final_temporal_evaluation(data, arrays, selected, output)
    summary = summarize_temporal(temporal, output)
    reproduction = compare_reference(data, temporal, output)
    best_augmented, finalists = finalist_candidates(summary)
    transfer = northward_transfer(data, arrays, selected, output)
    spatial = spatial_validation(data, arrays, selected, finalists, output)
    combined = combined_validation(data, arrays, selected, finalists, output)
    coefficient_summary(coefficients, output)
    selection = classify_and_select(summary, spatial, combined, output)
    final_manifest = {
        "task": "2F",
        "status": "completed_development_structured_evaluation",
        "branch": "feature/structured-revised-domain",
        "source_dataset_sha256": data["source_sha"],
        "source_git_sha": git_sha(),
        "task2e_reference_git_sha": data["manifest"]["git_sha"],
        "dimensions": {"response_weeks": 81, "development_weeks": DEVELOPMENT_WEEKS, "nodes": EXPECTED_NODE_COUNT},
        "candidate_feature_counts": {candidate: len(names) for candidate, names in CANDIDATES.items()},
        "selected_penalties": selected,
        "best_augmented_candidate_by_temporal_brier": best_augmented,
        "spatial_validation_candidates": finalists,
        "combined_validation_candidates": finalists,
        "task2e_baseline_reproduction": reproduction,
        "model_selection": selection,
        "terminal_holdout_metrics_calculated": False,
        "terminal_us_positive_outcomes_inspected": False,
        "runtime_seconds": time.time() - started,
        "artifact_root": str(output),
    }
    write_json(output / "manifests" / "task2f_manifest.json", final_manifest)
    print(json.dumps({"status": "completed", "preferred_candidate": selection["preferred_candidate"], "preferred_penalty": selection["preferred_penalty"], "augmentation_classification": selection["augmentation_classification"], "best_augmented_candidate": best_augmented, "terminal_holdout_metrics_calculated": False, "terminal_us_positive_outcomes_inspected": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
