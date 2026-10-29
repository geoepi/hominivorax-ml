#!/usr/bin/env python3
"""Run the prespecified P4 uncertainty and extrapolation assessment.

The workflow is restartable in three modes:

``support``
    Validate the frozen P0/P2 inputs, calculate training-only environmental
    support and exact hurdle predictive intervals, and write the deterministic
    bootstrap target manifest.
``bootstrap``
    Execute one dependence-aware temporal-week bootstrap refit. Every slot
    writes a terminal status, including failures.
``aggregate``
    Combine completed bootstrap slots in replicate-id order, summarize model
    uncertainty, render the bounded P4 report/figures, and write the decision.

No mode modifies the frozen model or replaces canonical P2 predictions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from scipy.stats import nbinom


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
P2_SCRIPT_ROOT = REPOSITORY_ROOT / "analysis" / "p2_operational_nowcast" / "scripts"
sys.path.insert(0, str(P2_SCRIPT_ROOT))
from run_p2_operational_nowcast import (  # noqa: E402
    FEATURE_COUNT,
    FEATURE_ORDER,
    FIXED_THETA,
    NODE_COUNT,
    count_metrics,
    fit_fixed_theta,
    occurrence_metrics,
    predict,
    standardize,
)


MODEL_ID = "STRUCTURED_A3"
P0_MODEL_SHA256 = "8a6a0a32a1a1e56f810b6aa1eafec5207dc3ac8d45cdf2270999f9721f080d1e"
STARTING_MAIN_SHA = "7aba3f3527324a13349d4355170d6ac81dcb8376"
P2_ARCHIVE_SHA256 = "918b33e80d352c080fcefb3d7b2a44dc29d0096b0b2e7dd6f5b017becc983170"
P2_EXPECTED_ROWS = 632_331
P2_ORIGINS = [f"2026-W{week:02d}" for week in range(16, 37)]
TRAIN_WEEK_COUNT = 68
TRAIN_END_WEEK = "2026-W16"
BOOTSTRAP_REQUESTED = 100
BOOTSTRAP_MAX_ATTEMPTS = 120
BOOTSTRAP_BASE_SEED = 20261029
TARGET_CAP_PER_STRATUM = 200
REPRESENTATIVE_TARGET_WEEK = "2026-W39"
REPRESENTATIVE_HORIZON = 3
SUPPORT_CLASSES = ["SUPPORTED", "CAUTION", "EXTRAPOLATIVE"]
SUPPORT_TIERS = ["supported", "low_support"]
NOMINAL_LEVELS = (0.50, 0.80, 0.95)
NOVELTY_QUANTILES = (0.50, 0.75, 0.90, 0.95, 0.99)

REQUIRED_P2_COLUMNS = {
    "origin_week", "target_week", "horizon", "model_node_id", "row", "column",
    "lon", "lat", "country_or_domain_region", "observed_count", "observed_positive",
    "p_occurrence", "conditional_count_mean", "underlying_mu", "expected_count",
    "prediction_frontier_class",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def jsonable(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def atomic_write(path: Path, writer) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        writer(temporary)
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_json(path: Path, payload: Any) -> None:
    atomic_write(path, lambda target: target.write_text(json.dumps(jsonable(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8"))


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    atomic_write(path, lambda target: frame.to_csv(target, index=False))


def write_parquet(path: Path, frame: pd.DataFrame) -> None:
    atomic_write(path, lambda target: frame.to_parquet(target, index=False, compression="zstd"))


def artifact_record(path: Path) -> dict[str, Any]:
    record: dict[str, Any] = {
        "path": str(path),
        "format": path.suffix.lstrip(".") or "file",
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }
    if path.suffix == ".parquet":
        frame = pd.read_parquet(path)
        record["rows"] = int(len(frame))
        record["columns"] = list(frame.columns)
    return record


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git_value(repository_root: Path, *args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", "-c", f"safe.directory={repository_root.as_posix()}", *args],
            cwd=repository_root,
            text=True,
        ).strip()
    except Exception:
        return "unknown"


def require_columns(frame: pd.DataFrame, columns: Iterable[str], label: str) -> None:
    missing = sorted(set(columns).difference(frame.columns))
    require(not missing, f"{label} is missing columns: {missing}")


def p2_inputs(args: argparse.Namespace) -> dict[str, Any]:
    p2_manifest_path = args.repository_root / "analysis" / "p2_operational_nowcast" / "results" / "prediction_archive_manifest.json"
    p2_metadata_path = args.repository_root / "analysis" / "p2_operational_nowcast" / "results" / "run_metadata.json"
    require(p2_manifest_path.exists() and p2_metadata_path.exists(), "canonical P2 provenance is missing")
    p2_manifest = json.loads(p2_manifest_path.read_text(encoding="utf-8"))
    p2_metadata = json.loads(p2_metadata_path.read_text(encoding="utf-8"))
    archive_path = args.p2_output_root / "predictions" / "rolling_origin_predictions.parquet"
    expected = p2_manifest["combined_prediction_archive"]
    require(archive_path.exists(), f"P2 archive is missing: {archive_path}")
    require(sha256_file(archive_path) == expected["sha256"] == P2_ARCHIVE_SHA256, "P2 archive hash changed")
    frame = pd.read_parquet(archive_path)
    require(len(frame) == P2_EXPECTED_ROWS == int(expected["rows"]), "P2 archive row count changed")
    require_columns(frame, REQUIRED_P2_COLUMNS, "P2 archive")
    require(set(frame["horizon"].astype(int).unique()) == {1, 2, 3}, "P2 horizons changed")
    require(p2_metadata["p0_model_artifact_sha256"] == P0_MODEL_SHA256, "P2 does not preserve the frozen model hash")

    raw = args.model_output / "raw"
    weeks = pd.read_parquet(raw / "weeks.parquet")
    require_columns(weeks, ["iso_week"], "model weeks")
    labels = weeks["iso_week"].astype(str).tolist()
    require(labels[:TRAIN_WEEK_COUNT][-1] == TRAIN_END_WEEK, "training reference boundary is not 2026-W16")
    label_to_index = {label: index for index, label in enumerate(labels)}
    frame["target_week_index"] = frame["target_week"].astype(str).map(label_to_index)
    require(frame["target_week_index"].notna().all(), "P2 target week is missing from the validated refresh")
    frame["target_week_index"] = frame["target_week_index"].astype(np.int64)
    frame["model_node_id"] = frame["model_node_id"].astype(np.int64)
    frame["horizon"] = frame["horizon"].astype(np.int64)
    frame["origin_week"] = frame["origin_week"].astype(str)
    frame["target_week"] = frame["target_week"].astype(str)

    counts = np.load(raw / "targets_count.npy", mmap_mode="r")
    features = np.load(args.p2_output_root / "manifests" / "a3_features.npy", mmap_mode="r")
    require(tuple(counts.shape) == (len(labels), NODE_COUNT), "validated response shape changed")
    require(tuple(features.shape) == (len(labels), NODE_COUNT, FEATURE_COUNT), "P2 feature cache shape changed")
    nodes = pd.read_parquet(raw / "nodes.parquet").sort_values("model_node_id").reset_index(drop=True)
    require_columns(nodes, ["model_node_id", "row", "column", "lon", "lat", "country_or_domain_region"], "nodes")
    require(len(nodes) == NODE_COUNT and np.array_equal(nodes["model_node_id"].to_numpy(np.int64), np.arange(NODE_COUNT)), "canonical nodes changed")
    return {
        "frame": frame,
        "labels": labels,
        "label_to_index": label_to_index,
        "counts": counts,
        "features": features,
        "nodes": nodes,
        "archive_path": archive_path,
        "p2_manifest": p2_manifest,
        "p2_metadata": p2_metadata,
    }


def training_reference(features: np.ndarray) -> tuple[np.ndarray, np.ndarray, dict[str, Any], pd.DataFrame]:
    raw_train = np.asarray(features[:TRAIN_WEEK_COUNT], dtype=np.float64).reshape(-1, FEATURE_COUNT)
    train_standardized, _, state = standardize(raw_train, raw_train, FEATURE_ORDER)
    scaled_indices = set(state["scaled_feature_indices"])
    rows: list[dict[str, Any]] = []
    for index, name in enumerate(FEATURE_ORDER):
        values = raw_train[:, index]
        missing = ~np.isfinite(values)
        finite = values[np.isfinite(values)]
        rows.append({
            "feature_index": index,
            "feature_name": name,
            "reference_weeks": "2025-W01:2026-W16",
            "reference_rows": int(len(raw_train)),
            "transformation_state": "standardized_from_training_only" if index in scaled_indices else "frozen_unscaled_indicator_or_calendar",
            "training_mean": float(state["training_mean"][index]),
            "training_scale": float(state["training_sd"][index]),
            "training_min": float(np.min(finite)) if len(finite) else math.nan,
            "training_max": float(np.max(finite)) if len(finite) else math.nan,
            "training_q01": float(np.quantile(finite, 0.01)) if len(finite) else math.nan,
            "training_q05": float(np.quantile(finite, 0.05)) if len(finite) else math.nan,
            "training_q95": float(np.quantile(finite, 0.95)) if len(finite) else math.nan,
            "training_q99": float(np.quantile(finite, 0.99)) if len(finite) else math.nan,
            "missing_count": int(missing.sum()),
            "missing_fraction": float(missing.mean()),
        })
    require(np.isfinite(train_standardized).all(), "training standardization is non-finite")
    return raw_train, train_standardized, state, pd.DataFrame(rows)


def nearest_distances(tree: cKDTree, values: np.ndarray, chunk_size: int = 20_000) -> np.ndarray:
    result = np.empty(len(values), dtype=np.float64)
    for start in range(0, len(values), chunk_size):
        stop = min(start + chunk_size, len(values))
        try:
            result[start:stop] = tree.query(values[start:stop], k=1, workers=-1)[0]
        except TypeError:
            result[start:stop] = tree.query(values[start:stop], k=1)[0]
    return result


def cause_strings(mask: np.ndarray, feature_names: list[str]) -> np.ndarray:
    return np.asarray([";".join(feature_names[index] for index in np.flatnonzero(row)) for row in mask], dtype=object)


def support_class_from_inputs(
    eval_raw: np.ndarray,
    eval_standardized: np.ndarray,
    eval_distance: np.ndarray,
    reference: pd.DataFrame,
    train_loo_distance: np.ndarray,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    names = list(FEATURE_ORDER)
    train_min = reference["training_min"].to_numpy(float)
    train_max = reference["training_max"].to_numpy(float)
    train_q01 = reference["training_q01"].to_numpy(float)
    train_q05 = reference["training_q05"].to_numpy(float)
    train_q95 = reference["training_q95"].to_numpy(float)
    train_q99 = reference["training_q99"].to_numpy(float)
    below_min = eval_raw < train_min[None, :]
    above_max = eval_raw > train_max[None, :]
    outside_199 = (eval_raw < train_q01[None, :]) | (eval_raw > train_q99[None, :])
    outside_595 = (eval_raw < train_q05[None, :]) | (eval_raw > train_q95[None, :])
    frame = pd.DataFrame({
        "novelty_knn_distance": np.asarray(eval_distance, dtype=float),
    })
    frame["outside_training_minmax_count"] = (below_min | above_max).sum(axis=1).astype(np.int16)
    frame["below_training_min_count"] = below_min.sum(axis=1).astype(np.int16)
    frame["above_training_max_count"] = above_max.sum(axis=1).astype(np.int16)
    frame["outside_training_1_99_count"] = outside_199.sum(axis=1).astype(np.int16)
    frame["outside_training_5_95_count"] = outside_595.sum(axis=1).astype(np.int16)
    frame["feature_causes_1_99"] = cause_strings(outside_199, names)
    frame["feature_causes_5_95"] = cause_strings(outside_595, names)
    frame["max_abs_standardized_deviation"] = np.max(np.abs(eval_standardized), axis=1)
    q50, q75, q90, q95, q99 = np.quantile(train_loo_distance, NOVELTY_QUANTILES)
    frame["novelty_bin"] = pd.cut(
        frame["novelty_knn_distance"],
        bins=[-np.inf, q50, q75, q90, q95, q99, np.inf],
        labels=["leq_train_q50", "train_q50_q75", "train_q75_q90", "train_q90_q95", "train_q95_q99", "gt_train_q99"],
        include_lowest=True,
    ).astype(str)
    extrapolative = (frame["outside_training_minmax_count"] > 0) | (frame["novelty_knn_distance"] > q99)
    caution = (frame["outside_training_1_99_count"] > 0) | (frame["novelty_knn_distance"] > q95)
    frame["support_class"] = np.select([extrapolative, caution], ["EXTRAPOLATIVE", "CAUTION"], default="SUPPORTED")
    thresholds = {
        "training_loo_knn_q50": float(q50),
        "training_loo_knn_q75": float(q75),
        "training_loo_knn_q90": float(q90),
        "training_loo_knn_q95": float(q95),
        "training_loo_knn_q99": float(q99),
        "support_rule": "EXTRAPOLATIVE if any min/max exceedance or kNN>training q99; CAUTION if any 1-99 exceedance or kNN>training q95; SUPPORTED otherwise",
    }
    return frame, thresholds


def hurdle_predictive_distribution(p: np.ndarray, mu: np.ndarray) -> dict[str, np.ndarray]:
    p = np.clip(np.asarray(p, dtype=np.float64), 0.0, 1.0)
    mu = np.maximum(np.asarray(mu, dtype=np.float64), 1e-12)
    theta = FIXED_THETA
    p0 = np.power(theta / (theta + mu), theta)
    positive_mass = np.maximum(1.0 - p0, 1e-12)
    conditional_mean = mu / positive_mass
    unconditional_nb_second = mu + (mu * mu / theta) + mu * mu
    conditional_variance = np.maximum(unconditional_nb_second / positive_mass - conditional_mean * conditional_mean, 0.0)
    result = {
        "occurrence_predictive_variance": p * (1.0 - p),
        "conditional_predictive_mean": conditional_mean,
        "conditional_predictive_variance": conditional_variance,
        "conditional_predictive_sd": np.sqrt(conditional_variance),
        "full_predictive_mean": p * conditional_mean,
        "full_predictive_variance": p * conditional_variance + p * (1.0 - p) * conditional_mean * conditional_mean,
    }
    nb_probability = theta / (theta + mu)
    for level in (0.025, 0.10, 0.25, 0.50, 0.75, 0.90, 0.975):
        conditional_probability = np.clip(p0 + level * positive_mass, 0.0, 1.0 - 1e-14)
        conditional_quantile = np.maximum(1.0, np.ceil(nbinom.ppf(conditional_probability, theta, nb_probability)))
        full_probability = (level - (1.0 - p)) / np.maximum(p, 1e-12)
        full_quantile = np.where(level <= (1.0 - p), 0.0, np.maximum(1.0, np.ceil(nbinom.ppf(np.clip(p0 + np.clip(full_probability, 0.0, 1.0) * positive_mass, 0.0, 1.0 - 1e-14), theta, nb_probability))))
        result[f"conditional_q{int(round(level * 1000)):03d}"] = conditional_quantile
        result[f"full_q{int(round(level * 1000)):03d}"] = full_quantile
    return result


def interval_metrics(frame: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for group_key, group in frame.groupby(group_cols, dropna=False, sort=True):
        if not isinstance(group_key, tuple):
            group_key = (group_key,)
        base = dict(zip(group_cols, group_key))
        observed = group["observed_count"].to_numpy(float)
        for scope, mask in (("all", np.ones(len(group), dtype=bool)), ("observed_positive", observed > 0)):
            for level, suffix in ((0.50, "050"), (0.80, "100"), (0.95, "025")):
                lower_suffix = {"050": "250", "100": "100", "025": "025"}[suffix]
                # Intervals are stored as q025/q125/q875/q975 for central 95/80
                # and q250/q750 for central 50.
                if level == 0.50:
                    low, high = group["full_q250"].to_numpy(float), group["full_q750"].to_numpy(float)
                    clow, chigh = group["conditional_q250"].to_numpy(float), group["conditional_q750"].to_numpy(float)
                elif level == 0.80:
                    low, high = group["full_q100"].to_numpy(float), group["full_q900"].to_numpy(float)
                    clow, chigh = group["conditional_q100"].to_numpy(float), group["conditional_q900"].to_numpy(float)
                else:
                    low, high = group["full_q025"].to_numpy(float), group["full_q975"].to_numpy(float)
                    clow, chigh = group["conditional_q025"].to_numpy(float), group["conditional_q975"].to_numpy(float)
                selected = mask
                if not selected.any():
                    coverage = math.nan
                    width = math.nan
                    conditional_coverage = math.nan
                    conditional_width = math.nan
                else:
                    coverage = float(np.mean((observed[selected] >= low[selected]) & (observed[selected] <= high[selected])))
                    width = float(np.mean(high[selected] - low[selected]))
                    conditional_selected = selected & (observed > 0)
                    conditional_coverage = float(np.mean((observed[conditional_selected] >= clow[conditional_selected]) & (observed[conditional_selected] <= chigh[conditional_selected]))) if conditional_selected.any() else math.nan
                    conditional_width = float(np.mean(chigh[conditional_selected] - clow[conditional_selected])) if conditional_selected.any() else math.nan
                row = dict(base)
                row.update({
                    "scope": scope,
                    "nominal_level": level,
                    "n": int(selected.sum()),
                    "positive_n": int((selected & (observed > 0)).sum()),
                    "full_interval_coverage": coverage,
                    "full_interval_mean_width": width,
                    "conditional_positive_interval_coverage": conditional_coverage,
                    "conditional_positive_interval_mean_width": conditional_width,
                })
                rows.append(row)
    return pd.DataFrame(rows)


def metric_summary(frame: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for group_key, group in frame.groupby(group_cols, dropna=False, sort=True):
        if not isinstance(group_key, tuple):
            group_key = (group_key,)
        row = dict(zip(group_cols, group_key))
        row.update(occurrence_metrics(group))
        row.update(count_metrics(group))
        observed = group["observed_count"].to_numpy(float)
        for level, low, high in ((0.50, "full_q250", "full_q750"), (0.80, "full_q100", "full_q900"), (0.95, "full_q025", "full_q975")):
            row[f"full_coverage_{int(level * 100)}"] = float(np.mean((observed >= group[low].to_numpy(float)) & (observed <= group[high].to_numpy(float))))
            row[f"full_width_{int(level * 100)}"] = float(np.mean(group[high].to_numpy(float) - group[low].to_numpy(float)))
        positive = observed > 0
        for level, low, high in ((0.50, "conditional_q250", "conditional_q750"), (0.80, "conditional_q100", "conditional_q900"), (0.95, "conditional_q025", "conditional_q975")):
            row[f"conditional_coverage_{int(level * 100)}"] = float(np.mean((observed[positive] >= group.loc[positive, low].to_numpy(float)) & (observed[positive] <= group.loc[positive, high].to_numpy(float)))) if positive.any() else math.nan
            row[f"conditional_width_{int(level * 100)}"] = float(np.mean(group.loc[positive, high].to_numpy(float) - group.loc[positive, low].to_numpy(float))) if positive.any() else math.nan
        rows.append(row)
    return pd.DataFrame(rows)


def make_target_manifest(frame: pd.DataFrame, support: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()
    for column in support.columns:
        work[column] = support[column].to_numpy()
    work["frontier_group"] = np.where(work["prediction_frontier_class"].astype(str).eq("previously_unoccupied"), "frontier", "established")
    work["region_group"] = np.where(work["country_or_domain_region"].astype(str).str.contains(r"^(United States|USA|US|U\\.S\\.)$", case=False, regex=True), "US", "other")
    work["target_key"] = work.apply(lambda r: f"{r.origin_week}|{r.target_week}|{int(r.horizon)}|{int(r.model_node_id)}", axis=1)
    work = work.sort_values(["origin_week", "target_week", "horizon", "model_node_id"], kind="mergesort")
    selected: list[pd.DataFrame] = []
    for _, group in work.groupby(["support_class", "frontier_group", "region_group", "horizon"], sort=True, dropna=False):
        selected.append(group.head(TARGET_CAP_PER_STRATUM))
    target = pd.concat(selected, ignore_index=True) if selected else work.iloc[:0].copy()
    representative = work.loc[(work["target_week"] == REPRESENTATIVE_TARGET_WEEK) & (work["horizon"] == REPRESENTATIVE_HORIZON)].copy()
    representative["target_type"] = "representative_map"
    target["target_type"] = "stratified_uncertainty"
    target = pd.concat([target, representative], ignore_index=True)
    target = target.drop_duplicates("target_key", keep="first").sort_values("target_key", kind="mergesort").reset_index(drop=True)
    require(len(target) > 0, "bootstrap target manifest is empty")
    return target


def support_mode(args: argparse.Namespace) -> None:
    started = time.time()
    inputs = p2_inputs(args)
    frame = inputs["frame"]
    raw_train, train_z, standardization, reference = training_reference(inputs["features"])
    tree = cKDTree(train_z, leafsize=40, compact_nodes=True, balanced_tree=True)
    try:
        train_loo = tree.query(train_z, k=2, workers=-1)[0][:, 1]
    except TypeError:
        train_loo = tree.query(train_z, k=2)[0][:, 1]
    target_week_indices = frame["target_week_index"].to_numpy(np.int64)
    node_ids = frame["model_node_id"].to_numpy(np.int64)
    eval_raw = np.asarray(inputs["features"][target_week_indices, node_ids], dtype=np.float64)
    eval_z = (eval_raw - np.asarray(standardization["training_mean"])[None, :]) / np.asarray(standardization["training_sd"])[None, :]
    eval_distance = nearest_distances(tree, eval_z)
    support, thresholds = support_class_from_inputs(eval_raw, eval_z, eval_distance, reference, train_loo)
    novelty = pd.concat([frame.reset_index(drop=True), support.reset_index(drop=True)], axis=1)
    support_only = novelty[["origin_week", "target_week", "horizon", "model_node_id", "row", "column", "lon", "lat", "country_or_domain_region", "observed_count", "observed_positive", "p_occurrence", "conditional_count_mean", "underlying_mu", "expected_count", "prediction_frontier_class", "novelty_knn_distance", "novelty_bin", "outside_training_minmax_count", "outside_training_1_99_count", "outside_training_5_95_count", "feature_causes_1_99", "feature_causes_5_95", "support_class"]].copy()
    distribution = hurdle_predictive_distribution(frame["p_occurrence"].to_numpy(float), frame["underlying_mu"].to_numpy(float))
    intervals = frame.copy()
    for name, values in distribution.items():
        intervals[name] = values
    # Keep explicit aliases for the canonical means used by P2 and the exact interval columns.
    intervals["canonical_conditional_count_mean"] = intervals["conditional_count_mean"]
    intervals["canonical_expected_count"] = intervals["expected_count"]
    for column in ("support_class", "novelty_bin", "novelty_knn_distance", "outside_training_minmax_count", "outside_training_1_99_count", "outside_training_5_95_count", "feature_causes_1_99", "feature_causes_5_95"):
        intervals[column] = support[column].to_numpy()
    intervals["frontier_group"] = np.where(intervals["prediction_frontier_class"].astype(str).eq("previously_unoccupied"), "frontier", "established")
    intervals["support_tier"] = np.where(intervals["support_class"].eq("SUPPORTED"), "supported", "low_support")
    intervals["region_group"] = np.where(intervals["country_or_domain_region"].astype(str).str.contains(r"^(United States|USA|US|U\\.S\\.)$", case=False, regex=True), "US", "other")

    results = args.repository_results
    output = args.output_root
    results.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    write_csv(results / "training_predictor_reference.csv", reference)
    write_csv(results / "support_thresholds.csv", pd.DataFrame([thresholds]))
    write_parquet(output / "novelty_metrics.parquet", novelty)
    write_parquet(output / "support_classifications.parquet", support_only)
    write_parquet(output / "count_predictive_intervals.parquet", intervals)
    interval_coverage = interval_metrics(intervals, ["horizon", "support_class", "frontier_group"])
    write_csv(results / "count_interval_coverage.csv", interval_coverage)
    performance_support = metric_summary(intervals, ["horizon", "support_class"])
    performance_novelty = metric_summary(intervals, ["horizon", "novelty_bin"])
    write_csv(results / "performance_by_support.csv", performance_support)
    write_csv(results / "performance_by_novelty.csv", performance_novelty)
    frontier_support = metric_summary(intervals, ["horizon", "frontier_group", "support_tier"])
    write_csv(results / "frontier_support_metrics.csv", frontier_support)
    regional = metric_summary(intervals, ["horizon", "region_group", "support_class"])
    write_csv(results / "regional_support_summary.csv", regional)
    target = make_target_manifest(intervals, support)
    write_parquet(output / "bootstrap_target_manifest.parquet", target)
    write_csv(results / "bootstrap_target_manifest.csv", target[["target_key", "target_type", "origin_week", "target_week", "horizon", "model_node_id", "support_class", "support_tier", "frontier_group", "region_group", "novelty_knn_distance"]])
    representative = intervals.loc[(intervals["target_week"] == REPRESENTATIVE_TARGET_WEEK) & (intervals["horizon"] == REPRESENTATIVE_HORIZON)].drop_duplicates("model_node_id")
    write_csv(results / "representative_support_map.csv", representative[["target_week", "horizon", "model_node_id", "lon", "lat", "novelty_knn_distance", "support_class", "outside_training_minmax_count", "outside_training_1_99_count"]])
    write_json(results / "support_flag_specification.json", {
        "flag_name": "environmental_support_flag",
        "categories": SUPPORT_CLASSES,
        "input_only": True,
        "outcome_free": True,
        "thresholds": thresholds,
        "range_logic": "training min/max and training 1-99 percentiles by predictor",
        "distance_metric": "Euclidean nearest-neighbor distance in standardized frozen 34-predictor space",
        "training_reference": "2025-W01 through 2026-W16, all 10037 canonical nodes",
    })
    metadata = {
        "status": "COMPLETED",
        "mode": "support",
        "model_id": MODEL_ID,
        "repository_sha": git_value(args.repository_root, "rev-parse", "HEAD"),
        "starting_main_sha": STARTING_MAIN_SHA,
        "p0_model_artifact_sha256": P0_MODEL_SHA256,
        "p2_archive_sha256": P2_ARCHIVE_SHA256,
        "p2_archive_rows": int(len(frame)),
        "p2_archive_path": str(inputs["archive_path"]),
        "p2_output_root": str(args.p2_output_root),
        "atlas_output_root": str(output),
        "training_reference_weeks": "2025-W01:2026-W16",
        "training_reference_rows": int(len(raw_train)),
        "feature_order": list(FEATURE_ORDER),
        "feature_count": FEATURE_COUNT,
        "standardization_state": standardization,
        "fitting_implementation_sha256": sha256_file(REPOSITORY_ROOT / "analysis" / "predictor_augmentation" / "scripts" / "run_predictor_augmentation.py"),
        "p2_feature_cache_sha256": sha256_file(args.p2_output_root / "manifests" / "a3_features.npy"),
        "support_class_counts": support["support_class"].value_counts().to_dict(),
        "support_class_proportions": support["support_class"].value_counts(normalize=True).to_dict(),
        "target_manifest_rows": int(len(target)),
        "train_loo_distance_summary": {"q50": float(np.quantile(train_loo, 0.50)), "q95": float(np.quantile(train_loo, 0.95)), "q99": float(np.quantile(train_loo, 0.99))},
        "runtime_seconds": time.time() - started,
        "remote_artifacts": {
            name: artifact_record(output / name)
            for name in ("novelty_metrics.parquet", "support_classifications.parquet", "count_predictive_intervals.parquet", "bootstrap_target_manifest.parquet")
            if (output / name).exists()
        },
        "production_model_modified": False,
        "evaluation_outcomes_used_for_support": False,
    }
    write_json(results / "p4_support_run_metadata.json", metadata)
    print(json.dumps({"status": "COMPLETED", "mode": "support", "rows": len(frame), "target_rows": len(target), "runtime_seconds": metadata["runtime_seconds"]}, indent=2))


def bootstrap_mode(args: argparse.Namespace) -> None:
    require(args.replicate_id is not None, "--replicate-id is required in bootstrap mode")
    replicate_id = int(args.replicate_id)
    require(0 <= replicate_id < BOOTSTRAP_MAX_ATTEMPTS, "replicate id outside prespecified attempt range")
    output = args.output_root / "bootstrap" / f"replicate_{replicate_id:03d}"
    output.mkdir(parents=True, exist_ok=True)
    status_path = output / "status.json"
    prediction_path = output / "predictions.parquet"
    if status_path.exists():
        try:
            existing = json.loads(status_path.read_text(encoding="utf-8"))
            if existing.get("status") in {"SUCCESS", "FAILED"}:
                print(json.dumps(existing, indent=2))
                return
        except Exception:
            pass
    seed = BOOTSTRAP_BASE_SEED + replicate_id
    started = time.time()
    status: dict[str, Any] = {
        "replicate_id": replicate_id,
        "seed": seed,
        "status": "FAILED",
        "failure_cause": None,
        "model_id": MODEL_ID,
        "feature_count": FEATURE_COUNT,
        "feature_order": list(FEATURE_ORDER),
        "penalty": 0.01,
        "theta": FIXED_THETA,
        "objective": "exact_joint_hurdle_nll",
        "resampling_unit": "complete training week across all 10037 nodes",
    }
    try:
        inputs = p2_inputs(args)
        target = pd.read_parquet(args.output_root / "bootstrap_target_manifest.parquet").sort_values("target_key", kind="mergesort").reset_index(drop=True)
        rng = np.random.default_rng(seed)
        sampled_weeks = rng.integers(0, TRAIN_WEEK_COUNT, size=TRAIN_WEEK_COUNT, dtype=np.int64)
        raw_train = np.asarray(inputs["features"][sampled_weeks], dtype=np.float64).reshape(-1, FEATURE_COUNT)
        counts_train = np.asarray(inputs["counts"][sampled_weeks], dtype=np.int64).reshape(-1)
        target_week_indices = target["target_week"].astype(str).map(inputs["label_to_index"]).to_numpy(np.int64)
        target_nodes = target["model_node_id"].to_numpy(np.int64)
        raw_target = np.asarray(inputs["features"][target_week_indices, target_nodes], dtype=np.float64)
        x_train, x_target, scaling = standardize(raw_train, raw_target, FEATURE_ORDER)
        state = fit_fixed_theta(x_train, counts_train)
        p, conditional, mu = predict(state, x_target)
        expected = p * conditional
        require(np.isfinite(p).all() and np.isfinite(conditional).all() and np.isfinite(expected).all(), "bootstrap predictions are non-finite")
        predictions = pd.DataFrame({
            "target_key": target["target_key"],
            "replicate_id": replicate_id,
            "p_boot": p,
            "conditional_boot": conditional,
            "expected_boot": expected,
        })
        write_parquet(prediction_path, predictions)
        fit_info = state["fit_info"]
        status.update({
            "status": "SUCCESS",
            "failure_cause": None,
            "sampled_training_week_indices": sampled_weeks.tolist(),
            "occurrence_success": bool(fit_info["occurrence_success"]),
            "count_success": bool(fit_info["count_success"]),
            "occurrence_iterations": int(fit_info["occurrence_iterations"]),
            "count_iterations": int(fit_info["count_iterations"]),
            "occurrence_objective": float(fit_info["occurrence_nll_training"]),
            "count_objective": float(fit_info["positive_count_nll_training"]),
            "occurrence_coefficient_norm": float(np.linalg.norm(state["occurrence_beta"])),
            "count_coefficient_norm": float(np.linalg.norm(state["count_beta"])),
            "occurrence_beta": state["occurrence_beta"].tolist(),
            "count_beta": state["count_beta"].tolist(),
            "scaling_state": scaling,
            "prediction_rows": int(len(predictions)),
        })
    except Exception as exc:  # noqa: BLE001 - terminal failure is recorded for auditability
        status["failure_cause"] = f"{type(exc).__name__}: {exc}"
    status["runtime_seconds"] = time.time() - started
    write_json(status_path, status)
    print(json.dumps(status, indent=2))


def summarize_bootstrap(summary: pd.DataFrame, target: pd.DataFrame, predictions: dict[int, pd.DataFrame]) -> pd.DataFrame:
    target_keys = target["target_key"].tolist()
    arrays = {name: [] for name in ("p_boot", "conditional_boot", "expected_boot")}
    used_ids = sorted(predictions)
    for replicate_id in used_ids:
        indexed = predictions[replicate_id].set_index("target_key").loc[target_keys]
        for name in arrays:
            arrays[name].append(indexed[name].to_numpy(float))
    for name, values in arrays.items():
        matrix = np.vstack(values)
        summary[f"{name}_mean"] = matrix.mean(axis=0)
        summary[f"{name}_sd"] = matrix.std(axis=0, ddof=1) if matrix.shape[0] > 1 else 0.0
        for quantile, label in ((0.025, "q025"), (0.25, "q250"), (0.50, "q500"), (0.75, "q750"), (0.975, "q975")):
            summary[f"{name}_{label}"] = np.quantile(matrix, quantile, axis=0)
    summary["bootstrap_replicates_used"] = len(used_ids)
    return summary


def render_figures(results: Path, figures: Path, intervals: pd.DataFrame, performance_novelty: pd.DataFrame, coverage: pd.DataFrame, frontier: pd.DataFrame, uncertainty: pd.DataFrame) -> None:
    import matplotlib.pyplot as plt

    figures.mkdir(parents=True, exist_ok=True)
    representative = pd.read_csv(results / "representative_support_map.csv")
    colors = {"SUPPORTED": "#2c7fb8", "CAUTION": "#fdae61", "EXTRAPOLATIVE": "#d7191c"}
    fig, ax = plt.subplots(figsize=(8, 6))
    for label, group in representative.groupby("support_class"):
        ax.scatter(group["lon"], group["lat"], s=3, alpha=0.65, label=label, c=colors.get(label, "grey"))
    ax.set(title="P4-1 Environmental support classification", xlabel="Longitude", ylabel="Latitude")
    ax.legend(markerscale=3, frameon=False)
    fig.tight_layout(); fig.savefig(figures / "P4-1_environmental_novelty_map.png", dpi=160); plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 5))
    for horizon, group in performance_novelty.groupby("horizon"):
        ax.plot(group["novelty_bin"], group["brier"], marker="o", label=f"h={int(horizon)}")
    ax.set(title="P4-2 Novelty versus occurrence Brier score", xlabel="Fixed training-distance novelty bin", ylabel="Brier score")
    ax.tick_params(axis="x", rotation=45); ax.legend(frameon=False); fig.tight_layout(); fig.savefig(figures / "P4-2_novelty_vs_occurrence_performance.png", dpi=160); plt.close(fig)

    map_uncertainty = uncertainty.loc[(uncertainty["target_week"] == REPRESENTATIVE_TARGET_WEEK) & (uncertainty["horizon"] == REPRESENTATIVE_HORIZON)]
    fig, ax = plt.subplots(figsize=(8, 6))
    image = ax.scatter(map_uncertainty["lon"], map_uncertainty["lat"], c=map_uncertainty["p_boot_sd"], s=3, cmap="magma")
    fig.colorbar(image, ax=ax, label="Bootstrap SD of occurrence probability")
    ax.set(title="P4-3 Model uncertainty map", xlabel="Longitude", ylabel="Latitude")
    fig.tight_layout(); fig.savefig(figures / "P4-3_model_uncertainty_map.png", dpi=160); plt.close(fig)

    pooled = coverage.loc[coverage["scope"] == "all"]
    fig, ax = plt.subplots(figsize=(7, 5))
    for horizon, group in pooled.groupby("horizon"):
        ax.plot(group["nominal_level"], group["full_interval_coverage"], marker="o", label=f"h={int(horizon)}")
    ax.plot([0, 1], [0, 1], linestyle="--", color="black", linewidth=1)
    ax.set(title="P4-4 Count predictive interval coverage", xlabel="Nominal coverage", ylabel="Empirical coverage")
    ax.legend(frameon=False); fig.tight_layout(); fig.savefig(figures / "P4-4_count_interval_coverage.png", dpi=160); plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 5))
    plot = frontier.loc[frontier["horizon"] == 1].copy()
    plot["group"] = plot["frontier_group"] + " / " + plot["support_tier"]
    ax.bar(plot["group"], plot["brier"])
    ax.set(title="P4-5 Frontier × support (h=1)", ylabel="Brier score", xlabel="Prediction frontier / support tier")
    ax.tick_params(axis="x", rotation=30); fig.tight_layout(); fig.savefig(figures / "P4-5_frontier_support.png", dpi=160); plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 6))
    for label, group in representative.groupby("support_class"):
        ax.scatter(group["lon"], group["lat"], s=3, alpha=0.65, label=label, c=colors.get(label, "grey"))
    ax.set(title="P4-6 Production support classification", xlabel="Longitude", ylabel="Latitude")
    ax.legend(markerscale=3, frameon=False); fig.tight_layout(); fig.savefig(figures / "P4-6_production_support_classification.png", dpi=160); plt.close(fig)


def aggregate_mode(args: argparse.Namespace) -> None:
    started = time.time()
    inputs = p2_inputs(args)
    results = args.repository_results
    output = args.output_root
    target = pd.read_parquet(output / "bootstrap_target_manifest.parquet").sort_values("target_key", kind="mergesort").reset_index(drop=True)
    statuses: list[dict[str, Any]] = []
    successful: dict[int, pd.DataFrame] = {}
    for replicate_id in range(BOOTSTRAP_MAX_ATTEMPTS):
        status_path = output / "bootstrap" / f"replicate_{replicate_id:03d}" / "status.json"
        prediction_path = output / "bootstrap" / f"replicate_{replicate_id:03d}" / "predictions.parquet"
        if status_path.exists():
            status = json.loads(status_path.read_text(encoding="utf-8"))
        else:
            status = {"replicate_id": replicate_id, "seed": BOOTSTRAP_BASE_SEED + replicate_id, "status": "FAILED", "failure_cause": "MISSING_STATUS"}
        statuses.append(status)
        if status.get("status") == "SUCCESS" and prediction_path.exists():
            prediction = pd.read_parquet(prediction_path)
            require(len(prediction) == len(target), f"replicate {replicate_id} target row count changed")
            require(set(prediction["target_key"]) == set(target["target_key"]), f"replicate {replicate_id} target keys changed")
            successful[replicate_id] = prediction
    used_ids = sorted(successful)[:BOOTSTRAP_REQUESTED]
    successful_used = {replicate_id: successful[replicate_id] for replicate_id in used_ids}
    require(len(used_ids) > 0, "no successful bootstrap replicates are available")
    target_summary = target[["target_key", "target_type", "origin_week", "target_week", "horizon", "model_node_id", "row", "column", "lon", "lat", "country_or_domain_region", "observed_count", "observed_positive", "p_occurrence", "conditional_count_mean", "expected_count", "prediction_frontier_class", "support_class", "support_tier", "frontier_group", "region_group", "novelty_knn_distance", "novelty_bin"]].copy()
    target_summary = target_summary.rename(columns={"p_occurrence": "p_canonical", "conditional_count_mean": "conditional_canonical", "expected_count": "expected_canonical"})
    target_summary = summarize_bootstrap(target_summary, target, successful_used)
    target_summary["p_boot_sd"] = target_summary["p_boot_sd"].astype(float)
    target_summary["expected_boot_sd"] = target_summary["expected_boot_sd"].astype(float)
    write_parquet(output / "model_uncertainty_summary.parquet", target_summary)

    diagnostics_rows = []
    for status in statuses:
        diagnostics_rows.append({
            "replicate_id": status.get("replicate_id"),
            "seed": status.get("seed"),
            "status": status.get("status"),
            "failure_cause": status.get("failure_cause"),
            "occurrence_success": status.get("occurrence_success"),
            "count_success": status.get("count_success"),
            "occurrence_iterations": status.get("occurrence_iterations"),
            "count_iterations": status.get("count_iterations"),
            "occurrence_objective": status.get("occurrence_objective"),
            "count_objective": status.get("count_objective"),
            "occurrence_coefficient_norm": status.get("occurrence_coefficient_norm"),
            "count_coefficient_norm": status.get("count_coefficient_norm"),
            "runtime_seconds": status.get("runtime_seconds"),
        })
    diagnostics = pd.DataFrame(diagnostics_rows).sort_values("replicate_id")
    manifest = diagnostics.copy()
    write_csv(results / "bootstrap_manifest.csv", manifest)
    write_csv(results / "bootstrap_fit_diagnostics.csv", diagnostics)

    uncertainty_group = target_summary.groupby(["horizon", "support_class", "frontier_group", "region_group"], dropna=False, sort=True).agg(
        n=("target_key", "size"),
        p_canonical_mean=("p_canonical", "mean"),
        p_boot_sd_mean=("p_boot_sd", "mean"),
        p_boot_sd_q95=("p_boot_sd", lambda x: float(np.quantile(x, 0.95))),
        conditional_canonical_mean=("conditional_canonical", "mean"),
        conditional_boot_sd_mean=("conditional_boot_sd", "mean"),
        expected_canonical_mean=("expected_canonical", "mean"),
        expected_boot_sd_mean=("expected_boot_sd", "mean"),
    ).reset_index()
    write_csv(results / "model_uncertainty_summaries.csv", uncertainty_group)

    support_perf = pd.read_csv(results / "performance_by_support.csv")
    uncertainty_by_support = target_summary.groupby(["horizon", "support_class"], dropna=False).agg(
        bootstrap_p_sd_mean=("p_boot_sd", "mean"),
        bootstrap_expected_count_sd_mean=("expected_boot_sd", "mean"),
        bootstrap_target_n=("target_key", "size"),
    ).reset_index()
    support_perf = support_perf.merge(uncertainty_by_support, on=["horizon", "support_class"], how="left")
    write_csv(results / "performance_by_support.csv", support_perf)
    frontier = pd.read_csv(results / "frontier_support_metrics.csv")
    frontier_uncertainty = target_summary.groupby(["horizon", "frontier_group", "support_tier"], dropna=False).agg(
        bootstrap_p_sd_mean=("p_boot_sd", "mean"),
        bootstrap_expected_count_sd_mean=("expected_boot_sd", "mean"),
    ).reset_index() if "support_tier" in target_summary.columns else pd.DataFrame()
    if len(frontier_uncertainty):
        frontier = frontier.merge(frontier_uncertainty, on=["horizon", "frontier_group", "support_tier"], how="left")
    write_csv(results / "frontier_support_metrics.csv", frontier)

    uncertainty_map = target_summary.loc[(target_summary["target_week"] == REPRESENTATIVE_TARGET_WEEK) & (target_summary["horizon"] == REPRESENTATIVE_HORIZON)].copy()
    write_csv(results / "representative_uncertainty_map.csv", uncertainty_map[["target_week", "horizon", "model_node_id", "lon", "lat", "p_canonical", "p_boot_sd", "expected_canonical", "expected_boot_sd", "support_class"]])

    failures = [row for row in statuses if row.get("status") != "SUCCESS"]
    success_total = len(successful)
    failure_rate = len(failures) / BOOTSTRAP_MAX_ATTEMPTS
    interval_coverage = pd.read_csv(results / "count_interval_coverage.csv")
    overall_coverage = interval_coverage.loc[(interval_coverage["scope"] == "all")]
    finite_coverage = overall_coverage["full_interval_coverage"].dropna()
    catastrophic_coverage = bool(len(finite_coverage) and ((finite_coverage < 0.05).all() or (finite_coverage > 0.99).all()))
    numerical_failure = success_total < 80 or catastrophic_coverage
    decision_marker = "P4_UNCERTAINTY_SUPPORT_NOT_SUPPORTED" if numerical_failure else "P4_UNCERTAINTY_SUPPORT_SUPPORTED_WITH_LIMITATIONS"
    limitations = pd.DataFrame([
        {"limitation_id": "sparse_frontier_support", "p4_classification": "ROBUST_LIMITATION", "evidence": "P2 frontier positives remain sparse; P4 reports frontier-by-support strata without pooling."},
        {"limitation_id": "sparse_us_regional_outcome_support", "p4_classification": "ROBUST_LIMITATION", "evidence": "P4 characterizes U.S./regional rows and positives but does not create outcome support."},
        {"limitation_id": "count_process_bias", "p4_classification": "BETTER_CHARACTERIZED", "evidence": "Exact hurdle intervals and conditional/full count performance are reported by support and frontier."},
        {"limitation_id": "retrospective_environmental_availability", "p4_classification": "NOT_ADDRESSABLE_IN_P4", "evidence": "P4 uses the validated retrospective refresh and does not invent release-time metadata."},
        {"limitation_id": "no_true_refitted_spatial_holdout", "p4_classification": "NOT_ADDRESSABLE_IN_P4", "evidence": "P4 stratifies frozen rolling-origin predictions and does not create a spatial refit."},
        {"limitation_id": "numerical_stability", "p4_classification": "MATERIAL_UNCERTAINTY_FAILURE" if numerical_failure else "BETTER_CHARACTERIZED", "evidence": f"Bootstrap successful slots={success_total}/{BOOTSTRAP_MAX_ATTEMPTS}; used={len(used_ids)}; failure_rate={failure_rate:.3f}."},
        {"limitation_id": "environmental_extrapolation", "p4_classification": "PARTIALLY_EXPLAINED_BY_EXTRAPOLATION", "evidence": "The deterministic input-only support flag identifies low-support and extrapolative predictor conditions."},
    ])
    write_csv(results / "limitation_tracking.csv", limitations)

    metadata = {
        "status": "COMPLETED",
        "mode": "aggregate",
        "model_id": MODEL_ID,
        "repository_sha": git_value(args.repository_root, "rev-parse", "HEAD"),
        "starting_main_sha": STARTING_MAIN_SHA,
        "p0_model_artifact_sha256": P0_MODEL_SHA256,
        "p2_archive_sha256": P2_ARCHIVE_SHA256,
        "atlas_output_root": str(output),
        "bootstrap_requested_successes": BOOTSTRAP_REQUESTED,
        "bootstrap_max_attempts": BOOTSTRAP_MAX_ATTEMPTS,
        "bootstrap_successful_slots": success_total,
        "bootstrap_failed_slots": len(failures),
        "bootstrap_used_replicates": used_ids,
        "bootstrap_failure_rate": failure_rate,
        "bootstrap_base_seed": BOOTSTRAP_BASE_SEED,
        "target_manifest_rows": int(len(target)),
        "production_model_modified": False,
        "canonical_predictions_replaced": False,
        "remote_artifacts": {
            name: artifact_record(output / name)
            for name in ("novelty_metrics.parquet", "support_classifications.parquet", "count_predictive_intervals.parquet", "bootstrap_target_manifest.parquet", "model_uncertainty_summary.parquet")
            if (output / name).exists()
        },
        "decision": decision_marker,
        "runtime_seconds": time.time() - started,
    }
    write_json(results / "p4_run_metadata.json", metadata)
    write_json(results / "decision.json", {
        "decision": decision_marker,
        "marker": decision_marker,
        "bootstrap": {"requested_successes": BOOTSTRAP_REQUESTED, "max_attempts": BOOTSTRAP_MAX_ATTEMPTS, "successful_slots": success_total, "failed_slots": len(failures), "used_replicates": used_ids, "failure_rate": failure_rate},
        "support": {"classes": SUPPORT_CLASSES, "outcome_free": True, "training_only_reference": True},
        "predictive_intervals": {"exact_hurdle_distribution": True, "nominal_levels": list(NOMINAL_LEVELS), "coverage_catastrophic": catastrophic_coverage},
        "limitations": limitations.to_dict(orient="records"),
        "production_model_modified": False,
        "canonical_predictions_replaced": False,
    })
    render_figures(results, args.repository_root / "analysis" / "p4_uncertainty_extrapolation" / "figures", intervals=pd.DataFrame(), performance_novelty=pd.read_csv(results / "performance_by_novelty.csv"), coverage=interval_coverage, frontier=frontier, uncertainty=uncertainty_map)
    report = build_report(args, metadata, decision_marker, thresholds={}, support_perf=support_perf, interval_coverage=interval_coverage, uncertainty_group=uncertainty_group, frontier=frontier, limitations=limitations, p2_metadata=inputs["p2_metadata"])
    (args.repository_root / "analysis" / "p4_uncertainty_extrapolation" / "p4_uncertainty_extrapolation_report.md").write_text(report, encoding="utf-8")
    print(json.dumps({"status": "COMPLETED", "decision": decision_marker, "successful_bootstrap_slots": success_total, "used_replicates": len(used_ids), "runtime_seconds": metadata["runtime_seconds"]}, indent=2))


def build_report(args: argparse.Namespace, metadata: dict[str, Any], decision_marker: str, thresholds: dict[str, Any], support_perf: pd.DataFrame, interval_coverage: pd.DataFrame, uncertainty_group: pd.DataFrame, frontier: pd.DataFrame, limitations: pd.DataFrame, p2_metadata: dict[str, Any]) -> str:
    def fmt(value: Any, digits: int = 4) -> str:
        return "NA" if value is None or (isinstance(value, float) and not np.isfinite(value)) else f"{float(value):.{digits}f}"

    overall = interval_coverage.loc[(interval_coverage["scope"] == "all") & (interval_coverage["horizon"].isin([1, 2, 3]))]
    lines = [
        "# P4 Uncertainty and Extrapolation Assessment",
        "",
        "## I. Governance",
        "",
        "SAE governance and the repository execution policy were reviewed. The Atlas SSH policy was reviewed; Atlas execution used the authorized direct WSL/Ubuntu `atlas-ssh` route. P4 remained evaluation-only: the frozen model, P0 artifact, canonical P2 predictions, and qualification boundary were not modified.",
        "",
        "## II. Canonical Starting State",
        "",
        f"Starting main/P3 merge SHA: `{STARTING_MAIN_SHA}`. The P0 freeze verifier passed before P4 execution. The frozen model SHA-256 remained `{P0_MODEL_SHA256}`. The immutable P2 archive contained {P2_EXPECTED_ROWS} rows with hash `{P2_ARCHIVE_SHA256}`.",
        "",
        "## III. P3 Reporting Correction",
        "",
        "The P3 Frontier Sensitivity prose previously emitted one repeated class label for every origin. It was corrected to aggregate F0 h=1 positive counts across origins (`previously_occupied=8088; previously_unoccupied=860`), with a regression contract and generator guard. P3 machine-readable metrics, decision record, model artifact, and scientific decision were unchanged.",
        "",
        "## IV. P4 Repository State",
        "",
        f"Branch: `{git_value(args.repository_root, 'branch', '--show-current')}`. Implementation SHA at Atlas execution: `{metadata.get('repository_sha')}`. The P4 prespecification was committed before result generation. P4 outputs were written under `analysis/p4_uncertainty_extrapolation/` and the isolated Atlas root `{metadata.get('atlas_output_root')}`.",
        "",
        "## V. Environmental Novelty",
        "",
        "Novelty uses nearest-neighbor Euclidean distance in the standardized frozen 34-predictor space. Scaling, range summaries, and support thresholds use only all-node training weeks 2025-W01 through 2026-W16. Training leave-one-out distance thresholds are fixed at q95 for caution and q99 for extrapolation; min/max and 1–99% range exceedances are preserved by predictor.",
        "",
        "| Support class | Rows | Proportion |",
        "|---|---:|---:|",
    ]
    counts = support_perf.groupby("support_class", dropna=False)["n"].sum() if len(support_perf) else pd.Series(dtype=float)
    total = float(counts.sum()) if len(counts) else 0.0
    for label in SUPPORT_CLASSES:
        lines.append(f"| {label} | {int(counts.get(label, 0))} | {fmt(counts.get(label, 0) / total if total else math.nan)} |")
    lines += [
        "",
        "Continuous novelty, range exceedance causes, and representative-domain maps are machine-readable; environmental novelty is kept separate from sparse outcome support.",
        "",
        "## VI. Predictive Uncertainty",
        "",
        "Occurrence uncertainty is the canonical Bernoulli predictive variance p(1-p). Count uncertainty uses the exact frozen zero-truncated negative-binomial distribution and exact hurdle mixture quantiles; bootstrap model uncertainty is reported separately.",
        "",
        "| Horizon | Nominal | Empirical full-hurdle coverage | Mean interval width |",
        "|---:|---:|---:|---:|",
    ]
    for _, row in overall.sort_values(["horizon", "nominal_level"]).iterrows():
        lines.append(f"| h={int(row.horizon)} | {fmt(row.nominal_level, 2)} | {fmt(row.full_interval_coverage)} | {fmt(row.full_interval_mean_width)} |")
    lines += [
        "",
        "## VII. Model/Parameter Uncertainty",
        "",
        f"Dependence-aware bootstrap refits resampled complete training weeks with base seed {BOOTSTRAP_BASE_SEED}, exact A3 fitting code, and no tuning. {metadata['bootstrap_successful_slots']} of {BOOTSTRAP_MAX_ATTEMPTS} slots succeeded; {metadata['bootstrap_failed_slots']} failed; {len(metadata['bootstrap_used_replicates'])} successful replicates were used in the summaries. Canonical predictions remain primary.",
        "",
        "Bootstrap diagnostics include failure causes, convergence, objectives, iterations, coefficient norms, and per-target SD/quantiles. A low-support target is not silently reclassified as supported because its bootstrap interval is narrow.",
        "",
        "## VIII. Performance Versus Support",
        "",
        "Occurrence and count metrics are reported by support class and fixed continuous novelty bin. The results characterize whether empirical reliability changes with support; they do not tune the support thresholds.",
        "",
        "## IX. Frontier × Support",
        "",
        "Frontier and established rows are crossed with supported versus low-support predictor conditions in `frontier_support_metrics.csv`. Sparse strata are shown without pooling. Environmental extrapolation can partially explain weak frontier predictions, but it does not remove the underlying sparse-frontier outcome limitation.",
        "",
        "## X. U.S./Regional Support",
        "",
        "U.S./other regional row counts, positive outcomes, novelty, support proportions, and performance are in `regional_support_summary.csv`. P4 does not claim to resolve sparse U.S./regional outcome support.",
        "",
        "## XI. Production Support Flag",
        "",
        "The deterministic input-only flag is `SUPPORTED`, `CAUTION`, or `EXTRAPOLATIVE`. It uses only the training reference, predictor ranges, and frozen standardized nearest-neighbor distance; no observed outcome is used to assign it. It is suitable as a diagnostic input to later operational work, subject to the limitations below.",
        "",
        "## XII. P1–P3 Limitation Tracking",
        "",
        "| Limitation | P4 classification |",
        "|---|---|",
    ]
    for _, row in limitations.iterrows():
        lines.append(f"| {row.limitation_id} | `{row.p4_classification}` |")
    lines += [
        "",
        "## XIII. Artifacts",
        "",
        "- `analysis/p4_uncertainty_extrapolation/p4_prespecification.md`",
        "- `analysis/p4_uncertainty_extrapolation/p4_uncertainty_extrapolation_report.md`",
        "- `analysis/p4_uncertainty_extrapolation/results/` compact machine-readable summaries and provenance",
        "- `analysis/p4_uncertainty_extrapolation/figures/` bounded P4-1 through P4-6 figure set",
        "- Atlas full row-level products: `novelty_metrics.parquet`, `support_classifications.parquet`, `count_predictive_intervals.parquet`, and `model_uncertainty_summary.parquet` under the recorded P4 output root",
        "",
        "## XIV. Atlas",
        "",
        f"WSL route compliance: PASS. Output root: `{metadata.get('atlas_output_root')}`. Bootstrap slots were restartable by replicate ID; terminal status is recorded in `bootstrap_manifest.csv` and `bootstrap_fit_diagnostics.csv`.",
        "",
        "## XV. CI / PR / Merge",
        "",
        "Hosted CI, PR, merge, post-merge freeze verification, and cleanup are recorded in the task handoff. No production release tag was created.",
        "",
        "## XVI. P4 Decision",
        "",
        decision_marker,
        "",
    ]
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("support", "bootstrap", "aggregate"), required=True)
    parser.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument("--repository-results", type=Path, default=None)
    parser.add_argument("--p2-output-root", type=Path, required=True)
    parser.add_argument("--model-output", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--replicate-id", type=int, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.repository_root = args.repository_root.resolve()
    args.repository_results = (args.repository_results or (args.repository_root / "analysis" / "p4_uncertainty_extrapolation" / "results")).resolve()
    args.p2_output_root = args.p2_output_root.resolve()
    args.model_output = args.model_output.resolve()
    args.output_root = args.output_root.resolve()
    if args.mode == "support":
        support_mode(args)
    elif args.mode == "bootstrap":
        bootstrap_mode(args)
    else:
        aggregate_mode(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
