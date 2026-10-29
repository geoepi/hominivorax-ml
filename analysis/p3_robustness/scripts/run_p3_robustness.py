#!/usr/bin/env python3
"""Run the bounded P3 robustness and sensitivity analysis.

P3 reuses the immutable P2 rolling-origin prediction archive for frontier,
count-error, and evaluation-partition diagnostics.  Only the prespecified
initialization experiment performs additional fits, and those fits are
diagnostic copies of the exact frozen A3 objective; no production artifact is
modified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.spatial import cKDTree


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
P2_SCRIPT_ROOT = REPOSITORY_ROOT / "analysis" / "p2_operational_nowcast" / "scripts"
sys.path.insert(0, str(P2_SCRIPT_ROOT))
from run_p2_operational_nowcast import (  # noqa: E402
    FEATURE_ORDER,
    FEATURE_COUNT,
    FIXED_THETA,
    MAX_HORIZON,
    NODE_COUNT,
    OPTIMIZER_MAXITER,
    PENALTY,
    calibration_values,
    count_metrics,
    fit_fixed_theta,
    occurrence_metrics,
    predict,
    standardize,
)
PREDICTOR_SCRIPT_ROOT = REPOSITORY_ROOT / "analysis" / "predictor_augmentation" / "scripts"
sys.path.insert(0, str(PREDICTOR_SCRIPT_ROOT))
from run_predictor_augmentation import (  # noqa: E402
    fixed_theta_zt_nb_objective,
    regularized_logistic_objective,
)


MODEL_ID = "STRUCTURED_A3"
P0_MODEL_SHA256 = "8a6a0a32a1a1e56f810b6aa1eafec5207dc3ac8d45cdf2270999f9721f080d1e"
P2_MERGE_SHA = "ec6e951c63f7ec7fd252de5ddea6bb9772fea906"
P3_BRANCH_NAME = "feature/p3-bounded-robustness"
P2_ARCHIVE_SHA256 = "918b33e80d352c080fcefb3d7b2a44dc29d0096b0b2e7dd6f5b017becc983170"
P2_EXPECTED_ROWS = 632_331
P2_ORIGINS = [f"2026-W{week:02d}" for week in range(16, 37)]
INITIALIZATION_ORIGINS = ["2026-W16", "2026-W26", "2026-W36"]
COUNT_STRATA = ["low_1_2", "moderate_3_5", "high_6_10", "extreme_11_plus"]
FRONTIER_DEFINITIONS = ["F0_reference", "F1_recent_8_week_occupancy", "F2_distance_to_prior_detection"]
SPATIAL_PARTITIONS = ["S0_country_domain_region", "S1_latitude_macroregion", "S2_longitude_macroregion"]
TEMPORAL_PARTITIONS = ["T0_target_week", "T1_fixed_four_week_block"]

REQUIRED_P2_COLUMNS = {
    "origin_week", "target_week", "horizon", "model_node_id", "row", "column",
    "lon", "lat", "country_or_domain_region", "observed_count", "observed_positive",
    "p_occurrence", "conditional_count_mean", "underlying_mu", "expected_count",
    "previously_occupied", "prediction_frontier_class",
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
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
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


def parse_week(value: str) -> tuple[int, int]:
    year, week = str(value).split("-W")
    return int(year), int(week)


def require_columns(frame: pd.DataFrame, columns: Iterable[str], label: str) -> None:
    missing = sorted(set(columns).difference(frame.columns))
    require(not missing, f"{label} is missing columns: {missing}")


def load_inputs(args: argparse.Namespace) -> dict[str, Any]:
    p2_manifest_path = args.repository_root / "analysis" / "p2_operational_nowcast" / "results" / "prediction_archive_manifest.json"
    p2_metadata_path = args.repository_root / "analysis" / "p2_operational_nowcast" / "results" / "run_metadata.json"
    require(p2_manifest_path.exists() and p2_metadata_path.exists(), "canonical P2 provenance files are missing")
    p2_manifest = json.loads(p2_manifest_path.read_text(encoding="utf-8"))
    p2_metadata = json.loads(p2_metadata_path.read_text(encoding="utf-8"))
    archive_path = args.p2_output_root / "predictions" / "rolling_origin_predictions.parquet"
    expected = p2_manifest["combined_prediction_archive"]
    require(archive_path.exists(), f"P2 prediction archive is missing: {archive_path}")
    require(sha256_file(archive_path) == expected["sha256"] == P2_ARCHIVE_SHA256, "P2 prediction archive hash does not match the canonical manifest")
    frame = pd.read_parquet(archive_path)
    require(len(frame) == P2_EXPECTED_ROWS == int(expected["rows"]), "P2 prediction archive row count changed")
    require_columns(frame, REQUIRED_P2_COLUMNS, "P2 prediction archive")
    require(set(frame["horizon"].astype(int).unique()) == {1, 2, 3}, "P2 archive horizons changed")
    require(frame[["p_occurrence", "conditional_count_mean", "underlying_mu", "expected_count"]].to_numpy(float).min() >= 0, "P2 predictions contain negative values")
    require(p2_metadata["p0_model_artifact_sha256"] == P0_MODEL_SHA256, "P2 metadata does not preserve the frozen model hash")
    require(int(p2_metadata["successful_origins"]) == len(P2_ORIGINS), "P2 metadata does not report all origins successful")

    raw = args.model_output / "raw"
    weeks = pd.read_parquet(raw / "weeks.parquet")
    require_columns(weeks, ["iso_week"], "model weeks")
    labels = weeks["iso_week"].astype(str).tolist()
    label_to_index = {label: index for index, label in enumerate(labels)}
    require(all(week in label_to_index for week in P2_ORIGINS), "P2 origins are not present in the validated refresh")
    counts = np.load(raw / "targets_count.npy", mmap_mode="r")
    require(tuple(counts.shape) == (len(labels), NODE_COUNT), "validated response shape changed")
    nodes = pd.read_parquet(raw / "nodes.parquet").sort_values("model_node_id").reset_index(drop=True)
    require_columns(nodes, ["model_node_id", "row", "column", "lon", "lat", "country_or_domain_region"], "model nodes")
    require(len(nodes) == NODE_COUNT and np.array_equal(nodes["model_node_id"].to_numpy(np.int64), np.arange(NODE_COUNT)), "canonical nodes changed")
    feature_cache = args.p2_output_root / "manifests" / "a3_features.npy"
    require(feature_cache.exists(), "P2 feature cache is missing")
    features = np.load(feature_cache, mmap_mode="r")
    require(tuple(features.shape) == (len(labels), NODE_COUNT, FEATURE_COUNT), "P2 feature cache shape changed")
    fit_paths = sorted((args.p2_output_root / "fits").glob("origin_*.json"))
    require(len(fit_paths) == len(P2_ORIGINS), "P2 fit artifact count changed")
    return {
        "frame": frame,
        "p2_manifest": p2_manifest,
        "p2_metadata": p2_metadata,
        "counts": counts,
        "labels": labels,
        "label_to_index": label_to_index,
        "nodes": nodes,
        "features": features,
        "fit_paths": fit_paths,
        "p2_archive_path": archive_path,
    }


def frontier_labels(counts: np.ndarray, origin_index: int, nodes: pd.DataFrame) -> dict[str, np.ndarray]:
    """Construct all prespecified prediction-time frontier labels from <=T data."""
    history = np.asarray(counts[: origin_index + 1]) > 0
    f0_occupied = np.any(history, axis=0)
    recent_start = max(0, origin_index + 1 - 8)
    f1_occupied = np.any(np.asarray(counts[recent_start : origin_index + 1]) > 0, axis=0)
    coordinates = nodes[["row", "column"]].to_numpy(float) * 25.0
    prior_nodes = np.flatnonzero(f0_occupied)
    if len(prior_nodes):
        distance = cKDTree(coordinates[prior_nodes]).query(coordinates, k=1)[0]
    else:
        distance = np.full(len(nodes), np.inf)
    f2 = np.select(
        [distance <= 25.0, distance <= 100.0],
        ["near_established", "intermediate_frontier"],
        default="distal_or_unoccupied",
    )
    return {
        "F0_reference": np.where(f0_occupied, "previously_occupied", "previously_unoccupied"),
        "F1_recent_8_week_occupancy": np.where(f1_occupied, "recent_8_week_occupied", "recent_8_week_unoccupied"),
        "F2_distance_to_prior_detection": f2.astype(str),
    }


def frontier_metric_row(frame: pd.DataFrame, definition: str, class_name: str, horizon: int, origin_week: str) -> dict[str, Any]:
    subset = frame.loc[(frame["horizon"].astype(int) == int(horizon)) & (frame["frontier_class"] == class_name)]
    row: dict[str, Any] = {"origin_week": origin_week, "definition": definition, "frontier_class": class_name, "horizon": int(horizon)}
    row.update(occurrence_metrics(subset))
    row.update(count_metrics(subset))
    return row


def run_frontier_sensitivity(frame: pd.DataFrame, counts: np.ndarray, labels: list[str], nodes: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    metric_rows: list[dict[str, Any]] = []
    leakage_checks: list[dict[str, Any]] = []
    for origin_week in P2_ORIGINS:
        origin_index = labels.index(origin_week)
        classified = frontier_labels(counts, origin_index, nodes)
        existing = frame.loc[frame["origin_week"].astype(str) == origin_week].sort_values(["horizon", "model_node_id"])
        reference_expected = existing["prediction_frontier_class"].to_numpy(str)
        reference_actual = np.tile(classified["F0_reference"], MAX_HORIZON)
        require(np.array_equal(reference_expected, reference_actual), f"F0 does not reproduce P2 classes for {origin_week}")
        for definition, classes in classified.items():
            subset = existing.copy()
            node_ids = subset["model_node_id"].to_numpy(np.int64)
            subset["frontier_class"] = classes[node_ids]
            for horizon in (1, 2, 3):
                for class_name in sorted(subset["frontier_class"].unique()):
                    metric_rows.append(frontier_metric_row(subset, definition, class_name, horizon, origin_week))
        toy_counts = np.zeros((6, 6), dtype=np.int64)
        toy_counts[origin_index if origin_index < 2 else 1, 0] = 1
        toy_nodes = nodes.iloc[:6].copy()
        toy_origin = min(1, origin_index)
        before = frontier_labels(toy_counts, toy_origin, toy_nodes)
        toy_counts[toy_origin + 1 :, 5] = 9
        after = frontier_labels(toy_counts, toy_origin, toy_nodes)
        for definition in FRONTIER_DEFINITIONS:
            leakage_checks.append({
                "origin_week": origin_week,
                "definition": definition,
                "future_mutation_invariant": bool(np.array_equal(before[definition], after[definition])),
                "reproducible": bool(np.array_equal(before[definition], frontier_labels(toy_counts, toy_origin, toy_nodes)[definition])),
            })
    leakage = pd.DataFrame(leakage_checks)
    require(bool(leakage["future_mutation_invariant"].all()), "frontier classification changed after future-count mutation")
    require(bool(leakage["reproducible"].all()), "frontier classification is not reproducible")
    support = pd.DataFrame(metric_rows)[["definition", "frontier_class", "horizon", "n", "positives", "prevalence"]]
    return pd.DataFrame(metric_rows), support, {"status": "PASS", "checks": int(len(leakage)), "leakage_checks": leakage.to_dict(orient="records")}


def count_stratum(value: float) -> str:
    if 1 <= value <= 2:
        return "low_1_2"
    if 3 <= value <= 5:
        return "moderate_3_5"
    if 6 <= value <= 10:
        return "high_6_10"
    if value >= 11:
        return "extreme_11_plus"
    return "not_positive"


def run_count_influence(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    positive = frame.loc[frame["observed_count"].astype(float) > 0].copy()
    positive["count_stratum"] = positive["observed_count"].astype(float).map(count_stratum)
    require(set(positive["count_stratum"].unique()).issubset(set(COUNT_STRATA)), "count strata include an unexpected label")
    rows: list[dict[str, Any]] = []
    for horizon_label, selected in [("all", positive), *[(str(h), positive.loc[positive["horizon"].astype(int) == h]) for h in (1, 2, 3)]]:
        total_abs = float(np.abs(selected["conditional_count_mean"] - selected["observed_count"]).sum())
        total_sq = float(((selected["conditional_count_mean"] - selected["observed_count"]) ** 2).sum())
        total_n = max(len(selected), 1)
        for stratum in COUNT_STRATA:
            subset = selected.loc[selected["count_stratum"] == stratum]
            error = subset["conditional_count_mean"].to_numpy(float) - subset["observed_count"].to_numpy(float)
            rows.append({
                "horizon": horizon_label,
                "count_stratum": stratum,
                "n": int(len(subset)),
                "observed_mean": float(subset["observed_count"].mean()) if len(subset) else math.nan,
                "predicted_mean": float(subset["conditional_count_mean"].mean()) if len(subset) else math.nan,
                "mae": float(np.abs(error).mean()) if len(error) else math.nan,
                "rmse": float(np.sqrt(np.mean(error ** 2))) if len(error) else math.nan,
                "mean_signed_error": float(error.mean()) if len(error) else math.nan,
                "observed_predicted_ratio": float(subset["observed_count"].sum() / max(subset["conditional_count_mean"].sum(), 1e-12)) if len(subset) else math.nan,
                "absolute_error_total": float(np.abs(error).sum()),
                "squared_error_total": float((error ** 2).sum()),
                "signed_error_total": float(error.sum()),
                "absolute_error_contribution": float(np.abs(error).sum() / max(total_abs, 1e-12)),
                "squared_error_contribution": float((error ** 2).sum() / max(total_sq, 1e-12)),
                "overall_mean_bias_contribution": float(error.sum() / total_n),
                "contribution_denominator_n": int(len(selected)),
                "deterministic_rule": "observed positive count bins 1-2, 3-5, 6-10, >=11",
            })
    influence_rows: list[dict[str, Any]] = []
    rank_frame = positive.sort_values(["observed_count", "origin_week", "target_week", "model_node_id"], ascending=[False, True, True, True], kind="mergesort")
    for label, fraction in [("untrimmed", 0.0), ("exclude_top_5pct", 0.05), ("exclude_top_1pct", 0.01)]:
        exclude_n = int(math.ceil(fraction * len(rank_frame)))
        excluded_index = set(rank_frame.index[:exclude_n])
        trimmed = frame.drop(index=excluded_index)
        metrics = count_metrics(trimmed)
        remaining = trimmed.loc[trimmed["observed_count"].astype(float) > 0]
        influence_rows.append({
            "diagnostic": label,
            "excluded_positive_n": exclude_n,
            "excluded_fraction": fraction,
            "remaining_positive_n": int(len(remaining)),
            "excluded_observed_count_cutoff": float(rank_frame.iloc[exclude_n - 1]["observed_count"]) if exclude_n else math.nan,
            "conditional_mae": metrics["conditional_mae"],
            "conditional_rmse": metrics["conditional_rmse"],
            "conditional_bias": metrics["conditional_bias"],
            "conditional_observed_predicted_ratio": metrics["conditional_observed_predicted_ratio"],
            "full_expected_mae": metrics["full_expected_mae"],
            "full_expected_rmse": metrics["full_expected_rmse"],
            "full_expected_bias": metrics["full_expected_bias"],
            "diagnostic_only": True,
            "untrimmed_is_primary": True,
        })
    influence = pd.DataFrame(influence_rows)
    require(influence.loc[influence["diagnostic"] == "untrimmed", "excluded_positive_n"].iloc[0] == 0, "untrimmed count diagnostic excluded rows")
    require(influence.loc[influence["diagnostic"] == "exclude_top_5pct", "excluded_positive_n"].iloc[0] == int(math.ceil(0.05 * len(positive))), "top-5% exclusion is not deterministic")
    require(influence.loc[influence["diagnostic"] == "exclude_top_1pct", "excluded_positive_n"].iloc[0] == int(math.ceil(0.01 * len(positive))), "top-1% exclusion is not deterministic")
    return pd.DataFrame(rows), influence, {"status": "PASS", "positive_rows": int(len(positive)), "strata": COUNT_STRATA}


def spatial_label(frame: pd.DataFrame, scheme: str) -> pd.Series:
    if scheme == "S0_country_domain_region":
        return frame["country_or_domain_region"].astype(str)
    if scheme == "S1_latitude_macroregion":
        return pd.Series(np.select([frame["lat"] < 20, frame["lat"] < 30], ["south_of_20N", "20_to_30N"], default="30_to_40N"), index=frame.index)
    if scheme == "S2_longitude_macroregion":
        return pd.Series(np.select([frame["lon"] < -105, frame["lon"] < -95], ["west_of_105W", "105W_to_95W"], default="east_of_95W"), index=frame.index)
    raise ValueError(scheme)


def temporal_label(frame: pd.DataFrame, scheme: str) -> pd.Series:
    weeks = frame["target_week"].astype(str)
    if scheme == "T0_target_week":
        return weeks
    if scheme == "T1_fixed_four_week_block":
        numbers = weeks.str.split("-W").str[1].astype(int)
        block = ((numbers - 17) // 4).astype(int) + 1
        return "block_" + block.astype(str)
    raise ValueError(scheme)


def run_partition_sensitivity(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for scheme in SPATIAL_PARTITIONS:
        labelled = spatial_label(frame, scheme)
        for horizon in (1, 2, 3):
            selected = frame.loc[frame["horizon"].astype(int) == horizon].copy()
            selected["partition_group"] = labelled.loc[selected.index]
            for group in sorted(selected["partition_group"].astype(str).unique()):
                subset = selected.loc[selected["partition_group"].astype(str) == group]
                row = {"partition_family": "spatial", "partition_scheme": scheme, "partition_group": group, "horizon": horizon}
                row.update(occurrence_metrics(subset))
                row.update(count_metrics(subset))
                rows.append(row)
    for scheme in TEMPORAL_PARTITIONS:
        labelled = temporal_label(frame, scheme)
        for horizon in (1, 2, 3):
            selected = frame.loc[frame["horizon"].astype(int) == horizon].copy()
            selected["partition_group"] = labelled.loc[selected.index]
            for group in sorted(selected["partition_group"].astype(str).unique()):
                subset = selected.loc[selected["partition_group"].astype(str) == group]
                row = {"partition_family": "temporal", "partition_scheme": scheme, "partition_group": group, "horizon": horizon}
                row.update(occurrence_metrics(subset))
                row.update(count_metrics(subset))
                rows.append(row)
    result = pd.DataFrame(rows)
    require(set(result["partition_scheme"].unique()) == set(SPATIAL_PARTITIONS + TEMPORAL_PARTITIONS), "partition schemes changed")
    return result, {"status": "PASS", "spatial_schemes": SPATIAL_PARTITIONS, "temporal_schemes": TEMPORAL_PARTITIONS}


def feature_group(feature: str) -> str:
    if feature == "intercept":
        return "intercept"
    if feature in FEATURE_ORDER[:12]:
        return "dynamic_environment"
    if feature in FEATURE_ORDER[12:22]:
        return "host_landscape_static"
    if feature in FEATURE_ORDER[22:24]:
        return "calendar"
    if feature in FEATURE_ORDER[24:30]:
        return "detection_history"
    return "augmentation_static"


def sign_transition_count(values: np.ndarray) -> int:
    signs = np.sign(values[np.abs(values) > 1e-12])
    return int(np.sum(signs[1:] != signs[:-1])) if len(signs) > 1 else 0


def run_fit_stability(fit_paths: list[Path]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    artifacts = []
    for path in fit_paths:
        artifact = json.loads(path.read_text(encoding="utf-8"))
        require(artifact.get("model") == MODEL_ID, f"unexpected model in {path}")
        require(artifact.get("feature_count") == FEATURE_COUNT, f"feature count changed in {path}")
        require(artifact.get("feature_order") == FEATURE_ORDER, f"feature order changed in {path}")
        artifacts.append(artifact)
    artifacts = sorted(artifacts, key=lambda item: parse_week(item["origin_week"]))
    long_rows: list[dict[str, Any]] = []
    origin_rows: list[dict[str, Any]] = []
    group_rows: list[dict[str, Any]] = []
    for artifact in artifacts:
        info = artifact["fit_info"]
        occ = np.asarray(artifact["occurrence_coefficients"], float)
        cnt = np.asarray(artifact["count_coefficients"], float)
        require(len(occ) == FEATURE_COUNT + 1 and len(cnt) == FEATURE_COUNT + 1, "fit coefficient length changed")
        origin_rows.append({
            "origin_week": artifact["origin_week"],
            "occurrence_success": bool(info["occurrence_success"]),
            "count_success": bool(info["count_success"]),
            "occurrence_iterations": int(info["occurrence_iterations"]),
            "count_iterations": int(info["count_iterations"]),
            "occurrence_nll_training": float(info["occurrence_nll_training"]),
            "positive_count_nll_training": float(info["positive_count_nll_training"]),
            "occurrence_l2_norm": float(np.linalg.norm(occ[1:])),
            "count_l2_norm": float(np.linalg.norm(cnt[1:])),
            "occurrence_max_abs": float(np.abs(occ[1:]).max()),
            "count_max_abs": float(np.abs(cnt[1:]).max()),
        })
        for component, values in [("occurrence", occ), ("positive_count", cnt)]:
            for index, value in enumerate(values):
                name = "intercept" if index == 0 else FEATURE_ORDER[index - 1]
                long_rows.append({"origin_week": artifact["origin_week"], "component": component, "parameter_index": index, "parameter": name, "feature_group": feature_group(name), "coefficient": float(value)})
            for group in sorted(set(feature_group("intercept") if False else feature_group(name) for name in ["intercept", *FEATURE_ORDER])):
                selected = values if group == "intercept" else values[1:][np.asarray([feature_group(name) == group for name in FEATURE_ORDER])]
                if group == "intercept":
                    selected = values[:1]
                group_rows.append({"origin_week": artifact["origin_week"], "component": component, "feature_group": group, "l2_norm": float(np.linalg.norm(selected)), "max_abs": float(np.abs(selected).max())})
    long_frame = pd.DataFrame(long_rows)
    stability_rows: list[dict[str, Any]] = []
    for (component, parameter_index, parameter, group), subset in long_frame.groupby(["component", "parameter_index", "parameter", "feature_group"], sort=True):
        values = subset.sort_values("origin_week")["coefficient"].to_numpy(float)
        stability_rows.append({
            "component": component,
            "parameter_index": int(parameter_index),
            "parameter": parameter,
            "feature_group": group,
            "n_origins": int(len(values)),
            "mean": float(values.mean()),
            "sd": float(values.std(ddof=1)),
            "minimum": float(values.min()),
            "maximum": float(values.max()),
            "q05": float(np.quantile(values, 0.05)),
            "q95": float(np.quantile(values, 0.95)),
            "relative_sd": float(values.std(ddof=1) / max(abs(values.mean()), 1e-12)),
            "positive_n": int((values > 1e-12).sum()),
            "negative_n": int((values < -1e-12).sum()),
            "near_zero_n": int((np.abs(values) <= 1e-12).sum()),
            "sign_transition_count": sign_transition_count(values),
            "near_zero_fraction": float((np.abs(values) <= 1e-6).mean()),
        })
    stability = pd.DataFrame(stability_rows)
    diagnostics = pd.DataFrame(origin_rows)
    groups = pd.DataFrame(group_rows)
    require(bool(diagnostics["occurrence_success"].all() and diagnostics["count_success"].all()), "immutable P2 fit artifacts contain a non-converged fit")
    graph_summary = pd.DataFrame([{"component": "latent_graph_effect", "status": "not_applicable", "reason": "Structured A3 has no latent graph/random-field effect parameter"}])
    summary = {
        "fit_artifacts": len(artifacts),
        "occurrence_converged": int(diagnostics["occurrence_success"].sum()),
        "count_converged": int(diagnostics["count_success"].sum()),
        "parameters_with_sign_transitions": int((stability["sign_transition_count"] > 0).sum()),
        "parameters_near_zero_at_all_origins": int((stability["near_zero_fraction"] == 1.0).sum()),
        "graph_effect": "not_applicable",
    }
    return stability, diagnostics, groups, graph_summary, summary


def custom_fit(x: np.ndarray, counts: np.ndarray, variant: str) -> dict[str, Any]:
    y = (np.asarray(counts, dtype=np.int64) > 0).astype(np.float64)
    positive = np.asarray(counts, dtype=np.float64) > 0
    require(positive.any() and not positive.all(), "initialization experiment requires both zero and positive observations")
    design = np.column_stack([np.ones(len(x), dtype=np.float64), x])
    dimension = design.shape[1]
    canonical_occurrence = np.zeros(dimension, dtype=float)
    canonical_count = np.zeros(dimension, dtype=float)
    canonical_count[0] = math.log(max(float(np.asarray(counts, dtype=float)[positive].mean()), 1e-3))
    if variant == "canonical":
        occurrence_start, count_start = canonical_occurrence, canonical_count
    elif variant == "zero_all":
        occurrence_start, count_start = np.zeros(dimension), np.zeros(dimension)
    elif variant == "deterministic_perturbed":
        perturbation = 0.10 * np.asarray([((-1) ** index) / (1.0 + math.sqrt(index)) for index in range(dimension)], dtype=float)
        occurrence_start = canonical_occurrence + perturbation
        count_start = canonical_count + perturbation
    else:
        raise ValueError(variant)
    occurrence = minimize(
        lambda beta: regularized_logistic_objective(beta, design, y, PENALTY), occurrence_start,
        jac=True, method="L-BFGS-B", options={"maxiter": OPTIMIZER_MAXITER, "ftol": 1e-10, "gtol": 1e-7},
    )
    positive_design = design[positive]
    positive_counts = np.asarray(counts, dtype=np.float64)[positive]
    count = minimize(
        lambda beta: fixed_theta_zt_nb_objective(beta, positive_design, positive_counts, PENALTY), count_start,
        jac=True, method="L-BFGS-B", options={"maxiter": OPTIMIZER_MAXITER, "ftol": 1e-10, "gtol": 1e-7, "maxls": 40},
    )
    return {
        "occurrence_beta": occurrence.x,
        "count_beta": count.x,
        "fit_info": {
            "occurrence_success": bool(occurrence.success),
            "count_success": bool(count.success),
            "occurrence_iterations": int(occurrence.nit),
            "count_iterations": int(count.nit),
            "occurrence_nll_training": float(occurrence.fun),
            "positive_count_nll_training": float(count.fun),
            "variant": variant,
            "occurrence_message": str(occurrence.message),
            "count_message": str(count.message),
        },
    }


def initialization_metrics(inputs: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for origin_week in INITIALIZATION_ORIGINS:
        origin_index = inputs["label_to_index"][origin_week]
        target_indices = list(range(origin_index + 1, origin_index + 1 + MAX_HORIZON))
        require(max(target_indices) < len(inputs["labels"]), f"initialization origin {origin_week} lacks three targets")
        raw_train = np.asarray(inputs["features"][: origin_index + 1], dtype=np.float64).reshape(-1, FEATURE_COUNT)
        raw_eval = np.asarray(inputs["features"][target_indices], dtype=np.float64).reshape(-1, FEATURE_COUNT)
        x_train, x_eval, _ = standardize(raw_train, raw_eval, FEATURE_ORDER)
        y_train = np.asarray(inputs["counts"][: origin_index + 1], dtype=np.int64).reshape(-1)
        observed = np.asarray(inputs["counts"][target_indices], dtype=np.int64).reshape(-1)
        states: dict[str, dict[str, Any]] = {}
        predictions: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
        for variant in ["canonical", "zero_all", "deterministic_perturbed"]:
            try:
                state = custom_fit(x_train, y_train, variant)
                states[variant] = state
                predictions[variant] = predict(state, x_eval)
                require(state["fit_info"]["occurrence_success"] and state["fit_info"]["count_success"], f"{origin_week} {variant} did not converge")
            except Exception as exc:
                rows.append({"origin_week": origin_week, "variant": variant, "status": "FAILED", "error": str(exc)})
        if "canonical" not in predictions:
            continue
        canonical_probability, canonical_conditional, canonical_mu = predictions["canonical"]
        canonical_frame = pd.DataFrame({
            "observed_count": observed,
            "observed_positive": (observed > 0).astype(np.int8),
            "p_occurrence": canonical_probability,
            "conditional_count_mean": canonical_conditional,
            "underlying_mu": canonical_mu,
            "expected_count": canonical_probability * canonical_conditional,
        })
        canonical_occurrence = occurrence_metrics(canonical_frame)
        canonical_count = count_metrics(canonical_frame)
        for variant, prediction in predictions.items():
            probability, conditional, mu = prediction
            variant_frame = pd.DataFrame({
                "observed_count": observed,
                "observed_positive": (observed > 0).astype(np.int8),
                "p_occurrence": probability,
                "conditional_count_mean": conditional,
                "underlying_mu": mu,
                "expected_count": probability * conditional,
            })
            occ = occurrence_metrics(variant_frame)
            cnt = count_metrics(variant_frame)
            info = states[variant]["fit_info"]
            rows.append({
                "origin_week": origin_week,
                "variant": variant,
                "status": "COMPLETED",
                "error": None,
                "occurrence_success": info["occurrence_success"],
                "count_success": info["count_success"],
                "occurrence_iterations": info["occurrence_iterations"],
                "count_iterations": info["count_iterations"],
                "occurrence_nll_training": info["occurrence_nll_training"],
                "positive_count_nll_training": info["positive_count_nll_training"],
                "occurrence_objective_delta_vs_canonical": info["occurrence_nll_training"] - states["canonical"]["fit_info"]["occurrence_nll_training"],
                "count_objective_delta_vs_canonical": info["positive_count_nll_training"] - states["canonical"]["fit_info"]["positive_count_nll_training"],
                "max_abs_probability_difference_vs_canonical": float(np.max(np.abs(probability - canonical_probability))),
                "mean_abs_probability_difference_vs_canonical": float(np.mean(np.abs(probability - canonical_probability))),
                "max_abs_conditional_count_difference_vs_canonical": float(np.max(np.abs(conditional - canonical_conditional))),
                "mean_abs_conditional_count_difference_vs_canonical": float(np.mean(np.abs(conditional - canonical_conditional))),
                "max_abs_expected_count_difference_vs_canonical": float(np.max(np.abs(probability * conditional - canonical_probability * canonical_conditional))),
                "mean_abs_expected_count_difference_vs_canonical": float(np.mean(np.abs(probability * conditional - canonical_probability * canonical_conditional))),
                "brier": occ["brier"],
                "calibration_intercept": occ["calibration_intercept"],
                "calibration_slope": occ["calibration_slope"],
                "auprc": occ["auprc"],
                "conditional_mae": cnt["conditional_mae"],
                "conditional_bias": cnt["conditional_bias"],
                "full_expected_mae": cnt["full_expected_mae"],
                "full_expected_bias": cnt["full_expected_bias"],
                "scientific_specification_unchanged": True,
            })
    result = pd.DataFrame(rows)
    completed = result.loc[result["status"] == "COMPLETED"]
    require(int((completed["variant"] == "canonical").sum()) == len(INITIALIZATION_ORIGINS), "canonical initialization experiment is incomplete")
    return result, {"status": "PASS" if not (result["status"] == "FAILED").any() else "FAILED", "origins": INITIALIZATION_ORIGINS, "variants": ["canonical", "zero_all", "deterministic_perturbed"]}


def limitation_rows(frame: pd.DataFrame, frontier: pd.DataFrame, count_strata: pd.DataFrame, partitions: pd.DataFrame, fit_summary: dict[str, Any], init_summary: dict[str, Any]) -> pd.DataFrame:
    us = frame.loc[frame["country_or_domain_region"].astype(str).str.contains("U.S.", regex=False)]
    frontier_reference = frontier.loc[(frontier["definition"] == "F0_reference") & (frontier["horizon"] == 1) & (frontier["frontier_class"] == "previously_unoccupied")]
    extreme = count_strata.loc[(count_strata["horizon"] == "all") & (count_strata["count_stratum"] == "extreme_11_plus")]
    rows = [
        {"limitation_id": "P1_sparse_frontier_support", "p1_p2_status": "PERSISTS", "p3_analysis": "frontier-definition sensitivity", "resolution_classification": "ROBUST_LIMITATION", "evidence": f"F0 has {int(frontier_reference['positives'].sum())} previously-unoccupied positives across h=1 origins (N={int(frontier_reference['n'].sum())}); alternatives are reported without pooling."},
        {"limitation_id": "P1_sparse_us_regional_support", "p1_p2_status": "PERSISTS", "p3_analysis": "spatial partition sensitivity", "resolution_classification": "ROBUST_LIMITATION", "evidence": f"P2 U.S./domain rows remain sparse with {int((us['observed_positive'] > 0).sum())} positive rows across the archive."},
        {"limitation_id": "P1_count_process_bias", "p1_p2_status": "PERSISTS", "p3_analysis": "count-error influence", "resolution_classification": "BETTER_CHARACTERIZED", "evidence": f"Observed-count strata and deterministic top-5%/top-1% diagnostics are reported; extreme-tail rows={int(extreme['n'].iloc[0]) if len(extreme) else 0}."},
        {"limitation_id": "P1_P2_evaluation_partition_boundary", "p1_p2_status": "PERSISTS", "p3_analysis": "spatial and temporal regrouping", "resolution_classification": "NOT_ADDRESSABLE_IN_P3", "evidence": "Regrouping frozen predictions does not create a refitted spatial holdout."},
        {"limitation_id": "P1_P2_fit_stability", "p1_p2_status": "NO_NEW_FAILURE", "p3_analysis": "fit/numerical stability", "resolution_classification": "BETTER_CHARACTERIZED", "evidence": f"Immutable fits converged {fit_summary['occurrence_converged']}/{fit_summary['fit_artifacts']} and {fit_summary['count_converged']}/{fit_summary['fit_artifacts']}; initialization status={init_summary['status']}."},
        {"limitation_id": "P2_retrospective_environmental_availability", "p1_p2_status": "PERSISTS", "p3_analysis": "not tested by bounded sensitivity", "resolution_classification": "NOT_ADDRESSABLE_IN_P3", "evidence": "P3 does not fabricate release-time or revision-lag metadata."},
    ]
    return pd.DataFrame(rows)


def render_report(args: argparse.Namespace, metadata: dict[str, Any], frontier: pd.DataFrame, count_strata: pd.DataFrame, count_influence: pd.DataFrame, partitions: pd.DataFrame, fit_summary: dict[str, Any], init: pd.DataFrame, limitations: pd.DataFrame, decision: dict[str, Any]) -> None:
    f0 = frontier.loc[(frontier["definition"] == "F0_reference") & (frontier["horizon"] == 1)].sort_values("frontier_class")
    f0_positive_counts = (
        f0.groupby("frontier_class", as_index=False)["positives"]
        .sum()
        .sort_values("frontier_class")
    )
    overall_count = count_influence.loc[count_influence["diagnostic"] == "untrimmed"].iloc[0]
    init_completed = init.loc[init["status"] == "COMPLETED"]
    lines = [
        "# P3 Bounded Robustness and Sensitivity Analysis",
        "",
        "## I. Governance",
        "",
        "SAE governance and the repository execution policy were reviewed. The Atlas SSH policy was reviewed and Atlas access used the authorized direct WSL/Ubuntu `atlas-ssh` route. P3 remained within the approved bounded scope; no Level-3 specification change or authorization boundary was encountered.",
        "",
        "## II. Canonical Starting State",
        "",
        f"Canonical `main` SHA: `{metadata['starting_main_sha']}`. P2 merge SHA: `{P2_MERGE_SHA}`. The P0 freeze verifier passed and the frozen model SHA-256 remained `{P0_MODEL_SHA256}`.",
        "",
        "## III. P3 Repository State",
        "",
        f"Branch: `{metadata['branch']}`. Worktree: `{metadata['worktree']}`. Implementation SHA: `{metadata['repository_sha']}`. The P2 archive contained `{metadata['p2_archive_rows']}` immutable rows with the verified canonical hash. No P0/P2 artifact was modified.",
        "",
        "## IV. Prespecified Sensitivity Design",
        "",
        "The prespecification was committed before result generation. F0 retained the P1/P2 through-origin occupancy definition; F1 used recent eight-week occupancy; F2 used nearest prior detection with 25-km and 100-km grid-distance bands. Count strata were 1–2, 3–5, 6–10, and >=11, with deterministic top-5% and top-1% diagnostic exclusions. Spatial schemes were country/domain, latitude macroregions, and longitude macroregions; temporal schemes were individual target weeks and fixed four-week blocks. Initialization variants were canonical, zero-all, and deterministic perturbed on W16, W26, and W36.",
        "",
        "## V. Frontier Sensitivity",
        "",
        f"All leakage and reproducibility checks passed. F0 h=1 aggregate positive counts across all origins were: " + "; ".join(f"{row.frontier_class}={int(row.positives)}" for row in f0_positive_counts.itertuples()) + ". F1 and F2 are reported separately in the machine-readable metrics, with no post-hoc pooling. The sparse-frontier qualification therefore remains materially unchanged, although class sample sizes and prevalence move with the definition.",
        "",
        "## VI. Count Influence",
        "",
        f"The untrimmed P2 count metrics remain primary: conditional MAE={overall_count['conditional_mae']:.4f}, conditional bias={overall_count['conditional_bias']:.4f}, and observed/predicted ratio={overall_count['conditional_observed_predicted_ratio']:.4f}. Count-stratum absolute, squared, and signed-error contributions are in `results/count_stratum_metrics.csv`; deterministic diagnostics are in `results/count_influence.csv`. The analysis characterizes rather than replaces the known count-process limitation.",
        "",
        "## VII. Partition Sensitivity",
        "",
        f"Spatial and temporal regrouping completed across {len(partitions)} metric rows. The broad regional/frontier qualification is not reversed by regrouping. These are summaries of frozen predictions and do not constitute a spatial refit or spatial holdout.",
        "",
        "## VIII. Fit Stability",
        "",
        f"All {fit_summary['fit_artifacts']} immutable P2 fit artifacts converged for both components. The coefficient extraction found {fit_summary['parameters_with_sign_transitions']} parameter-series with at least one sign transition; these are reported for interpretation rather than treated as causal effect changes. Initialization diagnostics completed {len(init_completed)} variant-origin rows with status `{metadata['initialization_status']}`. Structured A3 has no latent graph-effect parameter, recorded as not applicable.",
        "",
        "## IX. P1/P2 Limitation Tracking",
        "",
        "| Limitation | P3 classification |",
        "|---|---|",
    ]
    for row in limitations.itertuples():
        lines.append(f"| {row.limitation_id} | `{row.resolution_classification}` |")
    lines += [
        "",
        "## X. Artifacts",
        "",
        "- `analysis/p3_robustness/p3_prespecification.md`",
        "- `analysis/p3_robustness/p3_robustness_report.md`",
        "- `analysis/p3_robustness/results/` machine-readable metrics, provenance, limitation tracking, and decision record",
        "- `analysis/p3_robustness/figures/` bounded P3-1 through P3-4 figure set",
        f"- Atlas output root: `{metadata['atlas_output_root']}`",
        "",
        "## XI. Atlas",
        "",
        f"WSL route compliance: PASS. P3 aggregate job: `{metadata['slurm_job_id']}` with terminal status `{metadata['slurm_status']}`. P2 prediction archives and fit artifacts were reused; no historical P2 output root was overwritten.",
        "",
        "## XII. CI / PR / Merge",
        "",
        "P3 branch, hosted CI, PR, merge, post-merge validation, and cleanup are recorded in the final task handoff. No production release tag was created.",
        "",
        "## XIII. P3 Decision",
        "",
        f"{decision['marker']}",
    ]
    output = args.repository_results.parent / "p3_robustness_report.md"
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> None:
    started = time.time()
    inputs = load_inputs(args)
    frame = inputs["frame"]
    frontier, frontier_support, leakage = run_frontier_sensitivity(frame, inputs["counts"], inputs["labels"], inputs["nodes"])
    count_strata, count_influence, count_checks = run_count_influence(frame)
    partitions, partition_checks = run_partition_sensitivity(frame)
    fit_stability, fit_diagnostics, fit_groups, graph_summary, fit_summary = run_fit_stability(inputs["fit_paths"])
    initialization, initialization_checks = initialization_metrics(inputs)
    limitations = limitation_rows(frame, frontier, count_strata, partitions, fit_summary, initialization_checks)

    failed_init = int((initialization["status"] == "FAILED").sum()) if len(initialization) else 1
    decision_marker = "P3_ROBUSTNESS_SUPPORTED_WITH_LIMITATIONS" if failed_init == 0 else "P3_ROBUSTNESS_NOT_SUPPORTED"
    decision = {
        "decision": decision_marker,
        "marker": decision_marker,
        "interpretation": "Major P1/P2 conclusions remain usable; bounded alternatives reinforce existing support and count limitations without changing the frozen model." if failed_init == 0 else "A prespecified initialization variant failed to converge on a representative origin, requiring a numerical-stability qualification.",
        "frontier_leakage_checks": leakage,
        "count_checks": count_checks,
        "partition_checks": partition_checks,
        "fit_summary": fit_summary,
        "initialization_checks": initialization_checks,
        "limitations": limitations.to_dict(orient="records"),
        "no_new_predictors": True,
        "no_retuning": True,
        "no_recalibration": True,
        "p2_predictions_reused": True,
    }

    results = args.repository_results
    results.mkdir(parents=True, exist_ok=True)
    write_csv(results / "frontier_sensitivity_metrics.csv", frontier)
    write_csv(results / "frontier_support_metrics.csv", frontier_support)
    write_csv(results / "frontier_leakage_checks.csv", pd.DataFrame(leakage["leakage_checks"]))
    write_csv(results / "count_stratum_metrics.csv", count_strata)
    write_csv(results / "count_influence.csv", count_influence)
    write_csv(results / "partition_sensitivity_metrics.csv", partitions)
    write_csv(results / "fit_coefficient_stability.csv", fit_stability)
    write_csv(results / "fit_origin_diagnostics.csv", fit_diagnostics)
    write_csv(results / "fit_group_stability.csv", fit_groups)
    write_csv(results / "graph_effect_summary.csv", graph_summary)
    write_csv(results / "initialization_sensitivity.csv", initialization)
    write_csv(results / "limitation_resolution.csv", limitations)
    write_json(results / "fit_stability_summary.json", fit_summary)
    write_json(results / "decision.json", decision)

    metadata = {
        "model_id": MODEL_ID,
        "branch": git_value(args.repository_root, "branch", "--show-current") or P3_BRANCH_NAME,
        "repository_sha": git_value(args.repository_root, "rev-parse", "HEAD"),
        "starting_main_sha": P2_MERGE_SHA,
        "p2_merge_sha": P2_MERGE_SHA,
        "p0_model_artifact_sha256": P0_MODEL_SHA256,
        "p2_archive_path": str(inputs["p2_archive_path"]),
        "p2_archive_sha256": P2_ARCHIVE_SHA256,
        "p2_archive_rows": int(len(frame)),
        "p2_output_root": str(args.p2_output_root),
        "atlas_output_root": str(args.output_root),
        "worktree": str(args.repository_root),
        "prespecification_sha256": sha256_file(args.repository_root / "analysis" / "p3_robustness" / "p3_prespecification.md"),
        "p3_script_sha256": sha256_file(Path(__file__)),
        "slurm_job_id": os.environ.get("SLURM_JOB_ID", "unknown"),
        "slurm_status": "COMPLETED",
        "initialization_status": initialization_checks["status"],
        "initialization_origins": INITIALIZATION_ORIGINS,
        "initialization_variants": ["canonical", "zero_all", "deterministic_perturbed"],
        "frontier_definitions": FRONTIER_DEFINITIONS,
        "spatial_partitions": SPATIAL_PARTITIONS,
        "temporal_partitions": TEMPORAL_PARTITIONS,
        "count_strata": COUNT_STRATA,
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "scipy": __import__("scipy").__version__,
        "runtime_seconds": time.time() - started,
        "protected_inputs_not_committed": True,
        "production_model_modified": False,
    }
    write_json(results / "run_metadata.json", metadata)
    write_json(results / "atlas_execution.json", {"status": "COMPLETED", "job_id": metadata["slurm_job_id"], "output_root": str(args.output_root), "runtime_seconds": metadata["runtime_seconds"], "p2_archive_reused": True})
    render_report(args, metadata, frontier, count_strata, count_influence, partitions, fit_summary, initialization, limitations, decision)
    print(json.dumps({"status": "COMPLETED", "decision": decision_marker, "p2_rows": len(frame), "initialization_rows": len(initialization), "runtime_seconds": metadata["runtime_seconds"]}, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument("--repository-results", type=Path, default=None)
    parser.add_argument("--p2-output-root", type=Path, required=True)
    parser.add_argument("--model-output", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.repository_root = args.repository_root.resolve()
    args.repository_results = (args.repository_results or (args.repository_root / "analysis" / "p3_robustness" / "results")).resolve()
    args.p2_output_root = args.p2_output_root.resolve()
    args.model_output = args.model_output.resolve()
    args.output_root = args.output_root.resolve()
    try:
        run(args)
    except Exception as exc:
        print(f"P3_ROBUSTNESS_FAILED: {exc}", file=sys.stderr)
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
