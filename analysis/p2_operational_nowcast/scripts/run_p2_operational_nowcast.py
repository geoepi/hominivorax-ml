#!/usr/bin/env python3
"""Run the exact-frozen Structured A3 P2 rolling-origin evaluation.

The workflow has three restartable modes:

``prepare``
    Validate the P0 freeze, assemble the 34-predictor cache from protected
    Atlas inputs, and write the deterministic origin manifest.
``origin``
    Fit one expanding-window historical A3 state and write its predictions and
    fit ledger atomically.  The fit is an evaluation artifact; it never
    overwrites the canonical P0 model.
``aggregate``
    Require every eligible origin to have a terminal result, combine the
    origin products, calculate horizon/frontier/reference/count metrics and
    dependence-aware uncertainty, and write compact repository results.

The fixed-theta fitter is imported from the repository's previously validated
Structured A3 implementation.  No tuning, selection, recalibration, or
threshold optimization occurs in this module.
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
from scipy.special import expit, gammaln
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, log_loss, roc_auc_score


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPOSITORY_ROOT / "analysis" / "predictor_augmentation" / "scripts"))
from run_predictor_augmentation import (  # noqa: E402
    ADDED_FEATURES,
    BASE_FEATURES,
    CALENDAR_FEATURES,
    FIXED_THETA,
    OPTIMIZER_MAXITER,
    PENALTY,
    fit_fixed_theta,
    predict,
    standardize,
)

HISTORY_FEATURES = [
    "distance_to_any_prior_positive_log1p",
    "distance_to_prev4_positive_log1p",
    "weeks_since_detection_within_50km_log1p",
    "any_prior_positive_available",
    "prev4_positive_available",
    "detection_within_50km_ever_available",
]
FEATURE_ORDER = list(BASE_FEATURES) + list(ADDED_FEATURES)


MODEL_ID = "STRUCTURED_A3"
P0_MODEL_SHA256 = "8a6a0a32a1a1e56f810b6aa1eafec5207dc3ac8d45cdf2270999f9721f080d1e"
P0_MERGE_SHA = "6a797c6b8fb7fb8cace20c21503ec86a0a5dd750"
P1_MERGE_SHA = "1a8cba7ad910f6608fc664effdc1bb218b90b8ac"
P0_MANIFEST = "config/production_model_freeze.json"
ORIGIN_START = "2026-W16"
MAX_HORIZON = 3
BOOTSTRAP_REPLICATES = 399
BOOTSTRAP_SEED = 20261029
NODE_COUNT = 10_037
FEATURE_COUNT = 34
TEMPORAL_BIN_COUNT = 10
COUNT_BIN_EDGES = np.asarray([0.0, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0, np.inf])


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


def write_parquet(path: Path, frame: pd.DataFrame) -> None:
    atomic_write(path, lambda target: frame.to_parquet(target, index=False, compression="zstd"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_payload(payload: Any) -> str:
    encoded = json.dumps(jsonable(payload), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


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


def week_number(value: str) -> int:
    return parse_week(value)[1]


def require_columns(frame: pd.DataFrame, columns: Iterable[str], label: str) -> None:
    missing = sorted(set(columns).difference(frame.columns))
    require(not missing, f"{label} is missing columns: {missing}")


def verify_p0(repository_root: Path) -> dict[str, Any]:
    sys.path.insert(0, str(repository_root))
    from scripts.verify_production_model_freeze import check_artifacts, load_json, verify

    manifest_path = repository_root / P0_MANIFEST
    verification = verify(manifest_path, repository_root)
    require(all(value == "PASS" for value in verification.values() if isinstance(value, str)), f"P0 freeze verification failed: {verification}")
    manifest = load_json(manifest_path)
    paths = check_artifacts(manifest, repository_root)
    model_path = paths["frozen_model_metadata_and_coefficients"]
    require(sha256_file(model_path) == P0_MODEL_SHA256, "P0 model artifact hash changed")
    return verification


def load_bundle(args: argparse.Namespace) -> dict[str, Any]:
    raw = args.model_output / "raw"
    manifest_path = args.model_output / "manifests" / "revised_production_manifest.json"
    require(manifest_path.exists(), f"missing production manifest: {manifest_path}")
    production_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    dynamic = np.asarray(np.load(raw / "dynamic_features.npy", mmap_mode="r"), dtype=np.float64)
    static = np.asarray(np.load(raw / "static_features.npy", mmap_mode="r"), dtype=np.float64)
    counts = np.asarray(np.load(raw / "targets_count.npy", mmap_mode="r"), dtype=np.int64)
    weeks = pd.read_parquet(raw / "weeks.parquet").reset_index(drop=True)
    require_columns(weeks, ["iso_week"], "weeks")
    labels = weeks["iso_week"].astype(str).tolist()
    calendar = pd.read_parquet(raw / "calendar_features.parquet")
    require_columns(calendar, ["iso_week", *CALENDAR_FEATURES], "calendar features")
    calendar = calendar.set_index("iso_week").loc[labels, list(CALENDAR_FEATURES)].to_numpy(np.float64)

    nodes = pd.read_parquet(raw / "nodes.parquet").sort_values("model_node_id").reset_index(drop=True)
    require_columns(nodes, ["model_node_id", "row", "column", "lon", "lat", "country_or_domain_region"], "nodes")
    require(len(nodes) == NODE_COUNT and np.array_equal(nodes["model_node_id"].to_numpy(np.int64), np.arange(NODE_COUNT)), "canonical node table changed")

    front = pd.read_parquet(args.front_features)
    require_columns(front, ["week_index", "model_node_id", *HISTORY_FEATURES, "history_cutoff_week"], "causal front features")
    front = front.sort_values(["week_index", "model_node_id"]).reset_index(drop=True)
    require(len(front) == len(labels) * NODE_COUNT, "causal front features do not cover the full refresh")
    expected_week = np.repeat(np.arange(len(labels)), NODE_COUNT)
    expected_node = np.tile(np.arange(NODE_COUNT), len(labels))
    require(np.array_equal(front["week_index"].to_numpy(np.int64), expected_week), "front week order is not canonical")
    require(np.array_equal(front["model_node_id"].to_numpy(np.int64), expected_node), "front node order is not canonical")
    require(np.isfinite(front[HISTORY_FEATURES].to_numpy(np.float64)).all(), "front features are non-finite")
    for index, label in enumerate(labels):
        cutoffs = front.iloc[index * NODE_COUNT : (index + 1) * NODE_COUNT]["history_cutoff_week"].dropna().astype(str)
        require(all(parse_week(cutoff) < parse_week(label) for cutoff in cutoffs), f"future or same-week history detected for {label}")

    require(dynamic.shape == (len(labels), NODE_COUNT, 12), f"unexpected dynamic shape: {dynamic.shape}")
    require(static.shape == (NODE_COUNT, 10), f"unexpected static shape: {static.shape}")
    require(counts.shape == (len(labels), NODE_COUNT), f"unexpected count shape: {counts.shape}")
    require(np.isfinite(dynamic).all() and np.isfinite(static).all() and np.isfinite(counts).all(), "input arrays contain non-finite values")
    require(np.all(counts >= 0), "negative response counts detected")

    road = pd.read_parquet(args.road_night).sort_values("model_node_id").reset_index(drop=True)
    soil = pd.read_parquet(args.soil).sort_values("model_node_id").reset_index(drop=True)
    require_columns(road, ["model_node_id", "road_density", "night_illumination"], "road/night features")
    require_columns(soil, ["model_node_id", "clay_0_15__mean", "water_difference_wv0033_minus_wv0010_0_15__mean"], "soil features")
    require(np.array_equal(road["model_node_id"].to_numpy(np.int64), np.arange(NODE_COUNT)), "road/night node order changed")
    require(np.array_equal(soil["model_node_id"].to_numpy(np.int64), np.arange(NODE_COUNT)), "soil node order changed")

    transformed_static = static.copy()
    transformed_static[:, :5] = np.log1p(transformed_static[:, :5])
    history = front[HISTORY_FEATURES].to_numpy(np.float64).reshape(len(labels), NODE_COUNT, len(HISTORY_FEATURES))
    road_values = np.column_stack([
        np.log1p(road["road_density"].to_numpy(np.float64)),
        np.log1p(road["night_illumination"].to_numpy(np.float64)),
    ])
    soil_values = soil[["clay_0_15__mean", "water_difference_wv0033_minus_wv0010_0_15__mean"]].to_numpy(np.float64)
    features = np.concatenate([
        dynamic,
        np.broadcast_to(transformed_static[None, :, :], (len(labels), NODE_COUNT, 10)),
        np.broadcast_to(calendar[:, None, :], (len(labels), NODE_COUNT, 2)),
        history,
        np.broadcast_to(road_values[None, :, :], (len(labels), NODE_COUNT, 2)),
        np.broadcast_to(soil_values[None, :, :], (len(labels), NODE_COUNT, 2)),
    ], axis=2)
    require(features.shape == (len(labels), NODE_COUNT, FEATURE_COUNT), f"feature matrix shape changed: {features.shape}")
    require(np.isfinite(features).all(), "feature matrix contains non-finite values")
    require(list(FEATURE_ORDER) == list(BASE_FEATURES) + list(ADDED_FEATURES), "feature order implementation contract changed")

    return {
        "raw": raw,
        "manifest_path": manifest_path,
        "production_manifest": production_manifest,
        "dynamic": dynamic,
        "static": static,
        "counts": counts,
        "weeks": weeks,
        "labels": labels,
        "nodes": nodes,
        "front": front,
        "features": features,
        "source_paths": {
            "production_manifest": manifest_path,
            "dynamic_features": raw / "dynamic_features.npy",
            "static_features": raw / "static_features.npy",
            "targets_count": raw / "targets_count.npy",
            "weeks": raw / "weeks.parquet",
            "calendar_features": raw / "calendar_features.parquet",
            "nodes": raw / "nodes.parquet",
            "front_features": args.front_features,
            "road_night_features": args.road_night,
            "soil_features": args.soil,
        },
    }


def predictor_availability_rows() -> list[dict[str, Any]]:
    return [
        {"family": "dynamic_environmental", "predictors": ",".join(BASE_FEATURES[:12]), "availability_class": "RETROSPECTIVE_ONLY", "evidence": "Validated refresh values are assembled for completed target weeks; no release-time or revision-lag metadata is present in the repository."},
        {"family": "livestock_static", "predictors": ",".join(BASE_FEATURES[12:17]), "availability_class": "STATIC", "evidence": "Node-static livestock covariates."},
        {"family": "livestock_imputation_indicators", "predictors": ",".join(BASE_FEATURES[17:22]), "availability_class": "STATIC", "evidence": "Frozen node-static 0/1 indicators."},
        {"family": "calendar", "predictors": ",".join(CALENDAR_FEATURES), "availability_class": "AVAILABLE_AS_OF_ISSUE", "evidence": "Calendar terms are deterministic from the target week."},
        {"family": "causal_detection_history", "predictors": ",".join(HISTORY_FEATURES), "availability_class": "DERIVED_FROM_PRIOR_DATA", "evidence": "Causal front table records a history cutoff strictly before each forecast week."},
        {"family": "anthropogenic_static", "predictors": "road_density,night_illumination", "availability_class": "STATIC", "evidence": "Validated node-static landscape covariates."},
        {"family": "soil_static", "predictors": "clay_0_15,water_difference_wv0033_minus_wv0010_0_15", "availability_class": "STATIC", "evidence": "Validated node-static soil covariates."},
    ]


def source_manifest(bundle: dict[str, Any], repository_root: Path, feature_cache: Path) -> dict[str, Any]:
    sources = []
    for name, path in bundle["source_paths"].items():
        sources.append({"name": name, "path": str(path), "sha256": sha256_file(path), "size_bytes": path.stat().st_size})
    fitting_script = REPOSITORY_ROOT / "analysis" / "predictor_augmentation" / "scripts" / "run_predictor_augmentation.py"
    return {
        "repository_sha": git_value(repository_root, "rev-parse", "HEAD"),
        "starting_main_sha": P1_MERGE_SHA,
        "p0_merge_sha": P0_MERGE_SHA,
        "p1_merge_sha": P1_MERGE_SHA,
        "model_id": MODEL_ID,
        "p0_model_artifact_sha256": P0_MODEL_SHA256,
        "p0_manifest": P0_MANIFEST,
        "sources": sources,
        "feature_cache_sha256": sha256_file(feature_cache),
        "feature_cache_shape": list(bundle["features"].shape),
        "fitting_implementation": str(fitting_script),
        "fitting_implementation_sha256": sha256_file(fitting_script),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "scipy": __import__("scipy").__version__,
        "sklearn": __import__("sklearn").__version__,
    }


def prepare(args: argparse.Namespace) -> None:
    args.output_root.mkdir(parents=True, exist_ok=True)
    for folder in ("fits", "predictions", "manifests", "logs"):
        (args.output_root / folder).mkdir(parents=True, exist_ok=True)
    verification = verify_p0(args.repository_root)
    bundle = load_bundle(args)
    cache = args.output_root / "manifests" / "a3_features.npy"
    if not cache.exists():
        def save_features(target: Path) -> None:
            with target.open("wb") as handle:
                np.save(handle, bundle["features"])
        atomic_write(cache, save_features)
    manifest = source_manifest(bundle, args.repository_root, cache)
    write_json(args.output_root / "manifests" / "freeze_verification.json", verification)
    write_json(args.output_root / "manifests" / "input_manifest.json", manifest)

    labels = bundle["labels"]
    require(ORIGIN_START in labels, f"origin start {ORIGIN_START} is missing")
    first = labels.index(ORIGIN_START)
    origins: list[dict[str, Any]] = []
    fitting_sha = manifest["fitting_implementation_sha256"]
    for index in range(first, len(labels) - MAX_HORIZON):
        origin_week = labels[index]
        target_weeks = labels[index + 1 : index + MAX_HORIZON + 1]
        train_counts = bundle["counts"][: index + 1]
        origins.append({
            "origin_index": index,
            "origin_week": origin_week,
            "training_start": labels[0],
            "training_cutoff": origin_week,
            "training_week_count": index + 1,
            "training_row_count": int((index + 1) * NODE_COUNT),
            "training_positive_rows": int((train_counts > 0).sum()),
            "training_positive_count_observations": int(train_counts[train_counts > 0].size),
            "predictor_count": FEATURE_COUNT,
            "penalty": PENALTY,
            "theta": FIXED_THETA,
            "theta_fixed": True,
            "objective": "exact_joint_hurdle_nll",
            "optimizer": "L-BFGS-B",
            "optimizer_maxiter": OPTIMIZER_MAXITER,
            "fitting_code_sha256": fitting_sha,
            "training_data_manifest_sha256": sha256_payload({"source_manifest_sha256": sha256_payload(manifest), "training_cutoff": origin_week}),
            "horizons_evaluated": "1;2;3",
            "target_weeks": ";".join(target_weeks),
            "status": "PENDING",
        })
    require(origins, "no eligible rolling origins were constructed")
    write_csv(args.output_root / "manifests" / "rolling_origin_manifest.csv", pd.DataFrame(origins))
    write_csv(args.output_root / "manifests" / "predictor_availability_audit.csv", pd.DataFrame(predictor_availability_rows()))
    write_json(args.output_root / "manifests" / "procedure_spec.json", {
        "model_id": MODEL_ID,
        "p0_model_artifact_sha256": P0_MODEL_SHA256,
        "feature_order": FEATURE_ORDER,
        "feature_count": FEATURE_COUNT,
        "training_window": "expanding 2025-W01 through origin T",
        "origin_start": ORIGIN_START,
        "horizons": [1, 2, 3],
        "penalty": PENALTY,
        "theta": FIXED_THETA,
        "theta_fixed": True,
        "objective": "exact_joint_hurdle_nll",
        "optimizer": "L-BFGS-B",
        "optimizer_maxiter": OPTIMIZER_MAXITER,
        "no_tuning": True,
        "no_feature_selection": True,
        "no_recalibration": True,
        "primary_evaluation_label": "RETROSPECTIVE_1_TO_3_WEEK_ROLLING_ORIGIN_EVALUATION",
        "uncertainty": {"unit": "target_week block", "replicates": BOOTSTRAP_REPLICATES, "seed": BOOTSTRAP_SEED, "interval": "percentile 95%"},
        "eligible_origins": len(origins),
    })
    write_csv(args.output_root / "manifests" / "fit_status_manifest.csv", pd.DataFrame(origins)[["origin_index", "origin_week", "target_weeks", "status"]])
    print(json.dumps({"status": "PREPARED", "eligible_origins": len(origins), "first_origin": origins[0]["origin_week"], "last_origin": origins[-1]["origin_week"], "feature_cache": str(cache)}, indent=2))


def load_origin(args: argparse.Namespace, origin_index: int) -> tuple[dict[str, Any], dict[str, Any], np.ndarray, np.ndarray, pd.DataFrame]:
    manifest = pd.read_csv(args.output_root / "manifests" / "rolling_origin_manifest.csv")
    row = manifest.loc[manifest["origin_index"].astype(int) == int(origin_index)]
    require(len(row) == 1, f"origin index {origin_index} is not in the eligible manifest")
    origin = row.iloc[0].to_dict()
    procedure = json.loads((args.output_root / "manifests" / "procedure_spec.json").read_text(encoding="utf-8"))
    features = np.load(args.output_root / "manifests" / "a3_features.npy", mmap_mode="r")
    counts = np.load(args.model_output / "raw" / "targets_count.npy", mmap_mode="r")
    nodes = pd.read_parquet(args.model_output / "raw" / "nodes.parquet").sort_values("model_node_id").reset_index(drop=True)
    require(tuple(features.shape[1:]) == (NODE_COUNT, FEATURE_COUNT), "feature cache shape does not match procedure spec")
    require(tuple(counts.shape) == (len(pd.read_parquet(args.model_output / "raw" / "weeks.parquet")), NODE_COUNT), "response array shape changed")
    return origin, procedure, features, counts, nodes


def historical_prevalence(counts: np.ndarray, labels: list[str], train_end: int, target_week: str) -> tuple[float, str]:
    target_number = week_number(target_week)
    training_labels = labels[: train_end + 1]
    match = np.asarray([week_number(label) == target_number for label in training_labels], dtype=bool)
    if match.any():
        return float(np.mean(np.asarray(counts[: train_end + 1])[match] > 0)), "historical_iso_week_prevalence"
    return float(np.mean(np.asarray(counts[: train_end + 1]) > 0)), "global_training_prevalence_fallback"


def origin(args: argparse.Namespace) -> None:
    started = time.time()
    origin_row, procedure, features, counts, nodes = load_origin(args, args.origin_index)
    index = int(origin_row["origin_index"])
    origin_week = str(origin_row["origin_week"])
    fit_path = args.output_root / "fits" / f"origin_{origin_week}.json"
    prediction_path = args.output_root / "predictions" / f"origin_{origin_week}.parquet"
    status_path = args.output_root / "manifests" / f"origin_{origin_week}.json"
    if status_path.exists() and fit_path.exists() and prediction_path.exists():
        try:
            existing = json.loads(status_path.read_text(encoding="utf-8"))
            if existing.get("status") == "COMPLETED":
                print(f"P2_ORIGIN_ALREADY_COMPLETE {origin_week}")
                return
        except Exception:
            pass

    labels = pd.read_parquet(args.model_output / "raw" / "weeks.parquet")["iso_week"].astype(str).tolist()
    raw_train = np.asarray(features[: index + 1], dtype=np.float64).reshape(-1, FEATURE_COUNT)
    target_indices = list(range(index + 1, index + MAX_HORIZON + 1))
    raw_eval = np.asarray(features[target_indices], dtype=np.float64).reshape(-1, FEATURE_COUNT)
    x_train, x_eval, scaling = standardize(raw_train, raw_eval, FEATURE_ORDER)
    y_train = np.asarray(counts[: index + 1], dtype=np.int64).reshape(-1)
    state = fit_fixed_theta(x_train, y_train)
    probability, conditional, mu = predict(state, x_eval)

    prior_occupied = np.any(np.asarray(counts[: index + 1]) > 0, axis=0)
    rows: list[pd.DataFrame] = []
    for horizon, target_index in enumerate(target_indices, start=1):
        n = NODE_COUNT
        observed = np.asarray(counts[target_index], dtype=np.int64)
        start = (horizon - 1) * n
        stop = horizon * n
        target_week = labels[target_index]
        reference_probability, reference_source = historical_prevalence(np.asarray(counts), labels, index, target_week)
        frame = pd.DataFrame({
            "origin_week": origin_week,
            "target_week": target_week,
            "horizon": horizon,
            "model_node_id": np.arange(NODE_COUNT, dtype=np.int64),
            "row": nodes["row"].to_numpy(np.int64),
            "column": nodes["column"].to_numpy(np.int64),
            "lon": nodes["lon"].to_numpy(np.float64),
            "lat": nodes["lat"].to_numpy(np.float64),
            "country_or_domain_region": nodes["country_or_domain_region"].astype(str).to_numpy(),
            "observed_count": observed,
            "observed_positive": (observed > 0).astype(np.int8),
            "p_occurrence": probability[start:stop],
            "conditional_count_mean": conditional[start:stop],
            "underlying_mu": mu[start:stop],
            "expected_count": probability[start:stop] * conditional[start:stop],
            "persistence_probability": prior_occupied.astype(float),
            "historical_prevalence_probability": reference_probability,
            "historical_reference_source": reference_source,
            "previously_occupied": prior_occupied,
            "prediction_frontier_class": np.where(prior_occupied, "previously_occupied", "previously_unoccupied"),
            "outcome_frontier_label": np.select([
                (observed > 0) & prior_occupied,
                (observed > 0) & (~prior_occupied),
            ], ["established_core", "newly_detected_frontier"], default="not_positive"),
        })
        rows.append(frame)
    predictions = pd.concat(rows, ignore_index=True)
    require(not predictions.duplicated(["origin_week", "target_week", "model_node_id"]).any(), "origin prediction keys are duplicated")
    write_parquet(prediction_path, predictions)

    fit_artifact = {
        "model": MODEL_ID,
        "origin_week": origin_week,
        "training_start": labels[0],
        "training_cutoff": origin_week,
        "training_week_count": index + 1,
        "feature_order": FEATURE_ORDER,
        "feature_count": FEATURE_COUNT,
        "penalty": PENALTY,
        "theta": FIXED_THETA,
        "theta_fixed": True,
        "objective": "exact_joint_hurdle_nll",
        "optimizer": "L-BFGS-B",
        "optimizer_maxiter": OPTIMIZER_MAXITER,
        "preprocessing": scaling,
        "occurrence_coefficients": np.asarray(state["occurrence_beta"], dtype=float).tolist(),
        "count_coefficients": np.asarray(state["count_beta"], dtype=float).tolist(),
        "fit_info": state["fit_info"],
        "training_data_manifest_sha256": str(origin_row["training_data_manifest_sha256"]),
        "fitting_code_sha256": str(origin_row["fitting_code_sha256"]),
        "horizons_evaluated": [1, 2, 3],
    }
    write_json(fit_path, fit_artifact)
    fit_hash = sha256_file(fit_path)
    status = {
        "status": "COMPLETED",
        "origin_index": index,
        "origin_week": origin_week,
        "training_cutoff": origin_week,
        "target_weeks": labels[index + 1 : index + MAX_HORIZON + 1],
        "horizons_evaluated": [1, 2, 3],
        "convergence": {"occurrence": bool(state["fit_info"]["occurrence_success"]), "count": bool(state["fit_info"]["count_success"])},
        "fit_artifact": str(fit_path),
        "fit_artifact_sha256": fit_hash,
        "prediction_artifact": str(prediction_path),
        "prediction_artifact_sha256": sha256_file(prediction_path),
        "runtime_seconds": time.time() - started,
        "training_rows": int(len(y_train)),
        "training_positive_rows": int((y_train > 0).sum()),
        "training_positive_count_observations": int((y_train[y_train > 0]).size),
        "procedure_spec_sha256": sha256_file(args.output_root / "manifests" / "procedure_spec.json"),
        "failure": None,
    }
    write_json(status_path, status)
    print(json.dumps(status, indent=2))


def logit(values: np.ndarray) -> np.ndarray:
    values = np.clip(np.asarray(values, dtype=float), 1e-12, 1.0 - 1e-12)
    return np.log(values) - np.log1p(-values)


def calibration_values(y: np.ndarray, p: np.ndarray) -> tuple[float, float]:
    if len(np.unique(y)) < 2:
        return math.nan, math.nan
    model = LogisticRegression(C=1e6, solver="lbfgs", max_iter=200)
    model.fit(logit(p).reshape(-1, 1), y.astype(np.int8))
    return float(model.intercept_[0]), float(model.coef_[0, 0])


def occurrence_metrics(frame: pd.DataFrame) -> dict[str, Any]:
    y = frame["observed_positive"].to_numpy(np.int8)
    p = np.clip(frame["p_occurrence"].to_numpy(float), 1e-12, 1.0 - 1e-12)
    result: dict[str, Any] = {
        "n": int(len(frame)),
        "positives": int(y.sum()),
        "prevalence": float(y.mean()) if len(y) else math.nan,
        "brier": float(np.mean((p - y) ** 2)) if len(frame) else math.nan,
        "log_loss": float(log_loss(y, p, labels=[0, 1])) if len(frame) else math.nan,
        "calibration_intercept": math.nan,
        "calibration_slope": math.nan,
        "auroc": math.nan,
        "auprc": math.nan,
        "mean_predicted_probability": float(p.mean()) if len(frame) else math.nan,
    }
    if len(np.unique(y)) == 2:
        result["auroc"] = float(roc_auc_score(y, p))
        result["auprc"] = float(average_precision_score(y, p))
        result["calibration_intercept"], result["calibration_slope"] = calibration_values(y, p)
    return result


def ztnb_loglikelihood(y: np.ndarray, mu: np.ndarray, theta: float) -> np.ndarray:
    y = np.asarray(y, dtype=float)
    mu = np.maximum(np.asarray(mu, dtype=float), 1e-12)
    log_p0 = theta * (math.log(theta) - np.log(theta + mu))
    return gammaln(y + theta) - gammaln(theta) - gammaln(y + 1.0) + log_p0 + y * (np.log(mu) - np.log(theta + mu)) - np.log(np.maximum(-np.expm1(log_p0), 1e-12))


def count_metrics(frame: pd.DataFrame) -> dict[str, Any]:
    y = frame["observed_count"].to_numpy(float)
    conditional = frame["conditional_count_mean"].to_numpy(float)
    expected = frame["expected_count"].to_numpy(float)
    positive = y > 0
    result: dict[str, Any] = {
        "positive_n": int(positive.sum()),
        "conditional_mae": math.nan,
        "conditional_rmse": math.nan,
        "conditional_bias": math.nan,
        "conditional_observed_predicted_ratio": math.nan,
        "conditional_zt_nb_nll": math.nan,
        "full_expected_mae": float(np.mean(np.abs(expected - y))) if len(y) else math.nan,
        "full_expected_rmse": float(np.sqrt(np.mean((expected - y) ** 2))) if len(y) else math.nan,
        "full_expected_bias": float(np.mean(expected - y)) if len(y) else math.nan,
        "observed_total": float(y.sum()),
        "predicted_expected_total": float(expected.sum()),
    }
    if positive.any():
        result.update({
            "conditional_mae": float(np.mean(np.abs(conditional[positive] - y[positive]))),
            "conditional_rmse": float(np.sqrt(np.mean((conditional[positive] - y[positive]) ** 2))),
            "conditional_bias": float(np.mean(conditional[positive] - y[positive])),
            "conditional_observed_predicted_ratio": float(y[positive].sum() / max(conditional[positive].sum(), 1e-12)),
            "conditional_zt_nb_nll": float(-np.mean(ztnb_loglikelihood(y[positive], frame.loc[positive, "underlying_mu"].to_numpy(float), FIXED_THETA))),
        })
    return result


def metric_rows_for_group(frame: pd.DataFrame, group: dict[str, Any]) -> dict[str, Any]:
    row = dict(group)
    row.update(occurrence_metrics(frame))
    row.update(count_metrics(frame))
    return row


def calibration_bins(frame: pd.DataFrame, horizon_label: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    fixed = frame if horizon_label == "all" else frame.loc[frame["horizon"] == int(horizon_label)]
    edges = np.linspace(0.0, 1.0, TEMPORAL_BIN_COUNT + 1)
    p = fixed["p_occurrence"].to_numpy(float)
    y = fixed["observed_positive"].to_numpy(np.int8)
    bucket = np.minimum(np.digitize(p, edges, right=False) - 1, TEMPORAL_BIN_COUNT - 1)
    for index in range(TEMPORAL_BIN_COUNT):
        mask = bucket == index
        n = int(mask.sum())
        rows.append({
            "metric_family": "occurrence",
            "scope": "all",
            "horizon": horizon_label,
            "bin_index": index,
            "lower": float(edges[index]),
            "upper": float(edges[index + 1]),
            "n": n,
            "positive_n": int(y[mask].sum()) if n else 0,
            "mean_predicted": float(p[mask].mean()) if n else math.nan,
            "observed_probability": float(y[mask].mean()) if n else math.nan,
            "observed_se": float(math.sqrt((y[mask].mean() * (1 - y[mask].mean())) / n)) if n else math.nan,
            "deterministic_rule": "10 fixed equal-width probability bins; no post-hoc merging",
        })
    return rows


def count_calibration_bins(frame: pd.DataFrame, horizon_label: str) -> list[dict[str, Any]]:
    fixed = frame if horizon_label == "all" else frame.loc[frame["horizon"] == int(horizon_label)]
    rows: list[dict[str, Any]] = []
    for family, prediction_column in [("conditional_count", "conditional_count_mean"), ("full_expected_count", "expected_count")]:
        predicted = fixed[prediction_column].to_numpy(float)
        observed = fixed["observed_count"].to_numpy(float)
        bucket = np.minimum(np.digitize(predicted, COUNT_BIN_EDGES, right=False) - 1, len(COUNT_BIN_EDGES) - 2)
        for index in range(len(COUNT_BIN_EDGES) - 1):
            mask = bucket == index
            n = int(mask.sum())
            positive_mask = mask & (observed > 0) if family == "conditional_count" else mask
            rows.append({
                "metric_family": family,
                "scope": "all",
                "horizon": horizon_label,
                "bin_index": index,
                "lower": float(COUNT_BIN_EDGES[index]),
                "upper": float(COUNT_BIN_EDGES[index + 1]),
                "n": n,
                "positive_n": int((observed[positive_mask] > 0).sum()) if family == "conditional_count" else int((observed[mask] > 0).sum()),
                "mean_predicted": float(predicted[mask].mean()) if n else math.nan,
                "observed_probability": float(observed[positive_mask].mean()) if positive_mask.any() else math.nan,
                "observed_se": math.nan,
                "mean_observed": float(observed[positive_mask].mean()) if positive_mask.any() else math.nan,
                "deterministic_rule": "fixed count ranges; positive-count family uses observed positives only",
            })
    return rows


def bootstrap_indices(frame: pd.DataFrame, rng: np.random.Generator) -> np.ndarray:
    weeks = sorted(frame["target_week"].astype(str).unique(), key=parse_week)
    selected = rng.choice(np.asarray(weeks, dtype=object), size=len(weeks), replace=True)
    positions = {week: np.flatnonzero(frame["target_week"].astype(str).to_numpy() == week) for week in weeks}
    return np.concatenate([positions[str(week)] for week in selected]) if len(selected) else np.asarray([], dtype=np.int64)


def bootstrap_metric_rows(frame: pd.DataFrame, scope: str, horizon: int | str, replicates: int, seed: int) -> list[dict[str, Any]]:
    selected = frame if horizon == "all" else frame.loc[frame["horizon"] == int(horizon)]
    metrics_to_collect = [
        "brier", "calibration_intercept", "calibration_slope", "auprc",
        "conditional_mae", "conditional_bias", "full_expected_mae", "full_expected_bias",
    ]
    values: dict[str, list[float]] = {metric: [] for metric in metrics_to_collect}
    rng = np.random.default_rng(seed)
    for _ in range(replicates):
        indices = bootstrap_indices(selected, rng)
        sample = selected.iloc[indices]
        occurrence = occurrence_metrics(sample)
        count = count_metrics(sample)
        combined = {**occurrence, **count}
        for metric in metrics_to_collect:
            value = combined.get(metric)
            if value is not None and np.isfinite(value):
                values[metric].append(float(value))
    estimate = {**occurrence_metrics(selected), **count_metrics(selected)}
    rows = []
    for metric in metrics_to_collect:
        sampled = np.asarray(values[metric], dtype=float)
        rows.append({
            "scope": scope,
            "horizon": horizon,
            "metric": metric,
            "estimate": estimate.get(metric),
            "bootstrap_replicates": int(len(sampled)),
            "lower_95": float(np.quantile(sampled, 0.025)) if len(sampled) else math.nan,
            "upper_95": float(np.quantile(sampled, 0.975)) if len(sampled) else math.nan,
            "bootstrap_se": float(sampled.std(ddof=1)) if len(sampled) > 1 else math.nan,
            "resampling_unit": "target-week block preserving all nodes, origins, and horizons for the selected target week",
            "seed": seed,
            "status": "estimable" if len(sampled) else "not_estimable",
        })
    return rows


def horizon_delta_rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    common_weeks = sorted(
        set(frame.loc[frame["horizon"] == 1, "target_week"])
        & set(frame.loc[frame["horizon"] == 3, "target_week"]),
        key=parse_week,
    )
    rows: list[dict[str, Any]] = []
    for metric in ["brier", "calibration_intercept", "calibration_slope", "auprc", "conditional_mae", "conditional_bias", "full_expected_mae", "full_expected_bias"]:
        one = frame.loc[(frame["horizon"] == 1) & frame["target_week"].isin(common_weeks)]
        three = frame.loc[(frame["horizon"] == 3) & frame["target_week"].isin(common_weeks)]
        values_one = {**occurrence_metrics(one), **count_metrics(one)}
        values_three = {**occurrence_metrics(three), **count_metrics(three)}
        rows.append({
            "comparison": "h3_minus_h1_common_target_weeks",
            "metric": metric,
            "horizon_1": values_one.get(metric),
            "horizon_3": values_three.get(metric),
            "delta_3_minus_1": (values_three.get(metric) - values_one.get(metric)) if np.isfinite(values_three.get(metric, math.nan)) and np.isfinite(values_one.get(metric, math.nan)) else math.nan,
            "common_target_week_start": common_weeks[0] if common_weeks else None,
            "common_target_week_end": common_weeks[-1] if common_weeks else None,
            "common_target_week_count": len(common_weeks),
        })
    return rows


def bootstrap_delta_rows(frame: pd.DataFrame, replicates: int, seed: int) -> list[dict[str, Any]]:
    common_weeks = sorted(
        set(frame.loc[frame["horizon"] == 1, "target_week"])
        & set(frame.loc[frame["horizon"] == 3, "target_week"]),
        key=parse_week,
    )
    one = frame.loc[(frame["horizon"] == 1) & frame["target_week"].isin(common_weeks)]
    three = frame.loc[(frame["horizon"] == 3) & frame["target_week"].isin(common_weeks)]
    positions_one = {week: np.flatnonzero(one["target_week"].astype(str).to_numpy() == week) for week in common_weeks}
    positions_three = {week: np.flatnonzero(three["target_week"].astype(str).to_numpy() == week) for week in common_weeks}
    metrics_to_collect = ["brier", "calibration_intercept", "calibration_slope", "auprc", "conditional_mae", "conditional_bias", "full_expected_mae", "full_expected_bias"]
    values = {metric: [] for metric in metrics_to_collect}
    rng = np.random.default_rng(seed)
    for _ in range(replicates):
        selected_weeks = rng.choice(np.asarray(common_weeks, dtype=object), size=len(common_weeks), replace=True)
        idx_one = np.concatenate([positions_one[str(week)] for week in selected_weeks])
        idx_three = np.concatenate([positions_three[str(week)] for week in selected_weeks])
        metrics_one = {**occurrence_metrics(one.iloc[idx_one]), **count_metrics(one.iloc[idx_one])}
        metrics_three = {**occurrence_metrics(three.iloc[idx_three]), **count_metrics(three.iloc[idx_three])}
        for metric in metrics_to_collect:
            left, right = metrics_one.get(metric), metrics_three.get(metric)
            if left is not None and right is not None and np.isfinite(left) and np.isfinite(right):
                values[metric].append(float(right - left))
    estimate_rows = {row["metric"]: row["delta_3_minus_1"] for row in horizon_delta_rows(frame)}
    rows = []
    for metric in metrics_to_collect:
        sampled = np.asarray(values[metric], dtype=float)
        rows.append({
            "scope": "common_target_weeks",
            "horizon": "h3_minus_h1",
            "metric": f"delta_{metric}",
            "estimate": estimate_rows.get(metric),
            "bootstrap_replicates": int(len(sampled)),
            "lower_95": float(np.quantile(sampled, 0.025)) if len(sampled) else math.nan,
            "upper_95": float(np.quantile(sampled, 0.975)) if len(sampled) else math.nan,
            "bootstrap_se": float(sampled.std(ddof=1)) if len(sampled) > 1 else math.nan,
            "resampling_unit": "target-week block paired across horizons on common target weeks",
            "seed": seed,
            "status": "estimable" if len(sampled) else "not_estimable",
        })
    return rows


def reference_metrics(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for horizon in [1, 2, 3]:
        subset = frame.loc[frame["horizon"] == horizon].copy()
        y = subset["observed_positive"].to_numpy(np.int8)
        a3 = occurrence_metrics(subset)
        for reference_name, column in [("persistence", "persistence_probability"), ("historical_prevalence", "historical_prevalence_probability")]:
            p = np.clip(subset[column].to_numpy(float), 1e-12, 1.0 - 1e-12)
            ref = {
                "n": len(subset),
                "positives": int(y.sum()),
                "coverage": 1.0,
                "brier": float(np.mean((p - y) ** 2)),
                "log_loss": float(log_loss(y, p, labels=[0, 1])),
                "auroc": float(roc_auc_score(y, p)) if len(np.unique(y)) == 2 else math.nan,
                "auprc": float(average_precision_score(y, p)) if len(np.unique(y)) == 2 else math.nan,
            }
            rows.append({
                "scope": "all",
                "horizon": horizon,
                "reference": reference_name,
                **ref,
                "a3_brier": a3["brier"],
                "a3_log_loss": a3["log_loss"],
                "a3_auprc": a3["auprc"],
                "a3_minus_reference_brier": a3["brier"] - ref["brier"],
                "a3_minus_reference_log_loss": a3["log_loss"] - ref["log_loss"],
                "a3_minus_reference_auprc": a3["auprc"] - ref["auprc"] if np.isfinite(a3["auprc"]) and np.isfinite(ref["auprc"]) else math.nan,
                "reference_definition": "state at origin for persistence; training-only same-ISO-week prevalence for historical prevalence",
            })
    return pd.DataFrame(rows)


def aggregate_metrics(frame: pd.DataFrame, fit_status: pd.DataFrame) -> dict[str, Any]:
    horizon_rows: list[dict[str, Any]] = []
    for horizon in [1, 2, 3]:
        horizon_rows.append(metric_rows_for_group(frame.loc[frame["horizon"] == horizon], {"scope": "all", "horizon": horizon, "region": "all"}))
        for region in sorted(frame["country_or_domain_region"].astype(str).unique()):
            horizon_rows.append(metric_rows_for_group(frame.loc[(frame["horizon"] == horizon) & (frame["country_or_domain_region"].astype(str) == region)], {"scope": "region", "horizon": horizon, "region": region}))
    horizon_rows.append(metric_rows_for_group(frame, {"scope": "all", "horizon": "all", "region": "all"}))

    frontier_rows: list[dict[str, Any]] = []
    for horizon in [1, 2, 3]:
        for category in ["previously_occupied", "previously_unoccupied"]:
            subset = frame.loc[(frame["horizon"] == horizon) & (frame["prediction_frontier_class"] == category)]
            frontier_rows.append(metric_rows_for_group(subset, {"horizon": horizon, "frontier_class": category, "classification_uses": "information through origin only"}))
        newly = frame.loc[(frame["horizon"] == horizon) & (frame["outcome_frontier_label"] == "newly_detected_frontier")]
        frontier_rows.append(metric_rows_for_group(newly, {"horizon": horizon, "frontier_class": "newly_detected_frontier_positive", "classification_uses": "reported outcome label nested within previously_unoccupied; never used for prediction"}))

    fit_status = fit_status.copy()
    fit_status["status"] = fit_status["status"].astype(str)
    successful = int((fit_status["status"] == "COMPLETED").sum())
    failed = fit_status.loc[fit_status["status"] != "COMPLETED"]
    return {"horizon": pd.DataFrame(horizon_rows), "frontier": pd.DataFrame(frontier_rows), "successful": successful, "failed": failed}


def p1_limitation_rows(frame: pd.DataFrame, fit_status: pd.DataFrame, horizon_metrics: pd.DataFrame, frontier_metrics: pd.DataFrame) -> pd.DataFrame:
    region_rows = horizon_metrics.loc[(horizon_metrics["scope"] == "region") & (horizon_metrics["horizon"] != "all")].copy()
    us = region_rows.loc[region_rows["region"].astype(str).str.contains("United States|U.S.", regex=True)]
    us_positive = int(us["positives"].sum()) if not us.empty else 0
    frontier_support = frontier_metrics.loc[frontier_metrics["frontier_class"] == "newly_detected_frontier_positive", "positives"].sum()
    full_count = frame.loc[frame["observed_positive"] == 1]
    count_bias = float((full_count["conditional_count_mean"] - full_count["observed_count"]).mean()) if not full_count.empty else math.nan
    failed = int((fit_status["status"] != "COMPLETED").sum())
    rows = [
        {
            "limitation_id": "P1_sparse_us_support",
            "p1_finding": "Sparse U.S./regional outcome support limits spatial transfer strength.",
            "p2_diagnostic": "Horizon-by-region occurrence metrics and positive counts.",
            "status": "PERSISTS" if us_positive < int(frame["observed_positive"].sum()) else "BETTER_CHARACTERIZED",
            "evidence": f"U.S./domain-region positives across h=1..3: {us_positive}; P2 does not pool regions silently.",
        },
        {
            "limitation_id": "P1_sparse_frontier_support",
            "p1_finding": "Sparse frontier positive support limits frontier transfer strength.",
            "p2_diagnostic": "Origin-time occupied versus previously-unoccupied strata and newly detected positive outcomes by horizon.",
            "status": "PERSISTS" if int(frontier_support) > 0 else "NOT_EVALUABLE_IN_P2",
            "evidence": f"Newly detected/frontier positive outcome rows across h=1..3: {int(frontier_support)}.",
        },
        {
            "limitation_id": "P1_count_process_bias",
            "p1_finding": "Positive-count error/count-process bias prevents an unrestricted validity claim.",
            "p2_diagnostic": "Conditional positive-count and full-hurdle calibration at h=1..3.",
            "status": "PERSISTS" if np.isfinite(count_bias) and abs(count_bias) > 0 else "BETTER_CHARACTERIZED",
            "evidence": f"P2 pooled conditional positive-count mean error: {count_bias:.6g}.",
        },
        {
            "limitation_id": "P1_not_spatial_holdout",
            "p1_finding": "P1 spatial transfer was a frozen-model geographic diagnostic, not a refitted spatial holdout.",
            "p2_diagnostic": "Rolling origins preserve geography but do not create a spatial holdout.",
            "status": "NOT_EVALUABLE_IN_P2",
            "evidence": "P2 is an operational rolling-origin assessment; no spatial refit/holdout was introduced.",
        },
        {
            "limitation_id": "P1_extended_transport_boundary",
            "p1_finding": "P1 evaluated extended transport of a single frozen W16 artifact, beyond normal operational use.",
            "p2_diagnostic": "Weekly expanding-window origins and paired h=1..3 degradation.",
            "status": "BETTER_CHARACTERIZED",
            "evidence": f"P2 evaluated {len(fit_status)} weekly origins through three weeks; failed origins: {failed}.",
        },
    ]
    return pd.DataFrame(rows)


def render_report(
    output: Path,
    repository_root: Path,
    procedure: dict[str, Any],
    input_manifest: dict[str, Any],
    fit_status: pd.DataFrame,
    horizon_metrics: pd.DataFrame,
    frontier_metrics: pd.DataFrame,
    horizon_deltas: pd.DataFrame,
    reference: pd.DataFrame,
    limitations: pd.DataFrame,
    decision: dict[str, Any],
) -> None:
    primary = horizon_metrics.loc[(horizon_metrics["scope"] == "all") & (horizon_metrics["horizon"].isin([1, 2, 3]))].copy()
    successful = int((fit_status["status"] == "COMPLETED").sum())
    failures = fit_status.loc[fit_status["status"] != "COMPLETED"]
    def value(horizon: int, column: str) -> Any:
        row = primary.loc[primary["horizon"] == horizon]
        return row.iloc[0][column] if len(row) else math.nan
    def fmt(value_: Any, digits: int = 4) -> str:
        if value_ is None or not np.isfinite(value_):
            return "NA"
        return f"{float(value_):.{digits}f}"

    lines = [
        "# P2 Operational Rolling-Origin Nowcast Evaluation",
        "",
        "## I. Governance",
        "",
        "SAE governance, the repository execution-governance policy, and the Atlas SSH policy were reviewed. Atlas access used the authorized direct WSL/Ubuntu `atlas-ssh` route. The evaluation agent retained authority for implementation and diagnostics only; the P0 artifact, scientific specification, qualification criteria, and production promotion boundary were not changed.",
        "",
        "## II. Canonical Starting State",
        "",
        f"Canonical `main` before P2: `{input_manifest['starting_main_sha']}`. P0 merge: `{input_manifest['p0_merge_sha']}`. P1 merge: `{input_manifest['p1_merge_sha']}`. The shared production-freeze verifier passed with model `STRUCTURED_A3`, and the canonical model SHA-256 remained `{P0_MODEL_SHA256}`.",
        "",
        "## III. P1 Follow-up",
        "",
        "P2 followed the exact P1 findings: sparse U.S./regional support; sparse frontier support; positive-count/count-process bias; the fact that P1 spatial transfer was a geographic diagnostic rather than a refitted spatial holdout; and the distinction between P1 extended temporal transport and normal operational use.",
        "",
        "| P1 limitation | P2 diagnostic | Resolution classification |",
        "|---|---|---|",
    ]
    for _, row in limitations.iterrows():
        lines.append(f"| {row['p1_finding']} | {row['p2_diagnostic']} | `{row['status']}` |")
    lines += [
        "",
        "## IV. P2 Repository State",
        "",
        f"Implementation branch: `{input_manifest['branch']}`. Implementation SHA at Atlas execution: `{input_manifest['repository_sha']}`. Local and Atlas worktrees were isolated from unrelated user changes. Successful rolling-origin fits: `{successful}` of `{len(fit_status)}`. Failed origins: `{len(failures)}`.",
        "",
        "Targeted P2 contract tests cover cutoff boundaries, expanding windows, no future response leakage, horizon assignment, feature-schema/hyperparameter identity, frontier leakage prevention, metric calculations, reference leakage, and provenance schemas. Existing P0/P1 tests remain preserved.",
        "",
        "## V. Rolling-Origin Design",
        "",
        f"The primary design used weekly origins from `{procedure['origin_start']}` through `{input_manifest['last_origin']}`, an expanding training window `{procedure['training_window']}`, and horizons `h=1,2,3` only. The refresh supplied `{input_manifest['refresh_week_count']}` complete weeks through `{input_manifest['latest_week']}`; `{len(fit_status)}` origins supported all three horizons. Each origin fit used only rows through its cutoff, the exact 34-predictor schema, penalty `{PENALTY}`, fixed theta `{FIXED_THETA}`, objective `exact_joint_hurdle_nll`, and the repository L-BFGS-B implementation. No feature selection or hyperparameter optimization occurred.",
        "",
        "## VI. Predictor Availability",
        "",
        "Because the validated environmental refresh does not provide release-time/revision-lag metadata, target-week environmental layers are conservatively classified as `RETROSPECTIVE_ONLY`. Static covariates are static; calendar terms are available as of issue; and detection-history features are derived from prior data with auditable cutoffs strictly before the target week. Therefore the result is labeled `RETROSPECTIVE_1_TO_3_WEEK_ROLLING_ORIGIN_EVALUATION`, not unrestricted operational pseudo-deployment.",
        "",
        "## VII. Occurrence Calibration",
        "",
        "The central calibration diagnostics are reported separately by horizon below. Intervals are percentile 95% intervals from target-week block bootstrap with all spatial nodes, origins, and overlapping-horizon records preserved within each sampled target week.",
        "",
        "| Horizon | N | Positives | Prevalence | Brier | Calibration intercept | Calibration slope | Log loss | AUROC | AUPRC |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for horizon in [1, 2, 3]:
        lines.append(f"| h={horizon} | {int(value(horizon, 'n'))} | {int(value(horizon, 'positives'))} | {fmt(value(horizon, 'prevalence'))} | {fmt(value(horizon, 'brier'))} | {fmt(value(horizon, 'calibration_intercept'))} | {fmt(value(horizon, 'calibration_slope'))} | {fmt(value(horizon, 'log_loss'))} | {fmt(value(horizon, 'auroc'))} | {fmt(value(horizon, 'auprc'))} |")
    lines += [
        "",
        "Bootstrap intervals for Brier, calibration intercept/slope, AUPRC, count error, and hurdle expectation error are in `results/bootstrap_intervals.csv`.",
        "",
        "## VIII. Horizon Degradation",
        "",
    ]
    delta = horizon_deltas.loc[horizon_deltas["metric"].isin(["brier", "calibration_intercept", "calibration_slope", "auprc", "conditional_mae", "full_expected_mae"])]
    lines.append("The h=1 versus h=3 comparison uses common target weeks only. The signed h=3 minus h=1 changes are:")
    for _, row in delta.iterrows():
        lines.append(f"- `{row['metric']}`: `{fmt(row['delta_3_minus_1'])}` (common weeks `{row['common_target_week_start']}`–`{row['common_target_week_end']}`).")
    lines += [
        "",
        "No primary evaluation beyond three weeks was performed. Any longer-horizon behavior remains P1 extended temporal transport, not normal operational nowcasting.",
        "",
        "## IX. Count Calibration",
        "",
        "Conditional positive counts and the full hurdle expectation were evaluated for every horizon. The conditional metrics use only observed positive counts; the full-hurdle metrics include zeros. Fixed predicted-count ranges and upper-tail behavior are in `results/calibration_bins.csv` and `results/count_metrics.csv`.",
        "",
        "| Horizon | Positive N | Conditional MAE | Conditional bias | Observed/predicted positive ratio | Full expected MAE | Full expected bias |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for horizon in [1, 2, 3]:
        lines.append(f"| h={horizon} | {int(value(horizon, 'positive_n'))} | {fmt(value(horizon, 'conditional_mae'))} | {fmt(value(horizon, 'conditional_bias'))} | {fmt(value(horizon, 'conditional_observed_predicted_ratio'))} | {fmt(value(horizon, 'full_expected_mae'))} | {fmt(value(horizon, 'full_expected_bias'))} |")
    lines += [
        "",
        "## X. Frontier Evaluation",
        "",
        "Frontier classes are assigned at issuance using only occupancy through origin T. `previously_occupied` and `previously_unoccupied` are prediction-time strata. `newly_detected_frontier_positive` is reported only as a descriptive positive-outcome subclass of previously unoccupied rows; future detections never enter a prediction or fit.",
        "",
        "| Horizon | Frontier class | N | Positives | Prevalence | Brier | Calibration slope | AUPRC |",
        "|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for _, row in frontier_metrics.iterrows():
        if row["frontier_class"] == "newly_detected_frontier_positive" or row["frontier_class"] in {"previously_occupied", "previously_unoccupied"}:
            lines.append(f"| h={row['horizon']} | {row['frontier_class']} | {int(row['n'])} | {int(row['positives'])} | {fmt(row['prevalence'])} | {fmt(row['brier'])} | {fmt(row['calibration_slope'])} | {fmt(row['auprc'])} |")
    lines += [
        "",
        "The P1 frontier limitation is followed up explicitly and remains a limitation when frontier positive support is sparse; the report does not pool frontier and established strata to conceal that fact.",
        "",
        "## XI. P1 Limitation Resolution",
        "",
    ]
    for _, row in limitations.iterrows():
        lines.append(f"- `{row['limitation_id']}`: `{row['status']}` — {row['evidence']}")
    lines += [
        "",
        "## XII. Minimal Reference Assessment",
        "",
        "Two and only two simple references were used: persistence from the observed state at origin T, and training-only same-ISO-week historical prevalence with a global training fallback only if a seasonal cell was unavailable. Both had complete coverage here because the validated response array has a value for every node and origin week. They are descriptive operational references, not alternative candidate models.",
        "",
        "| Horizon | Reference | Coverage | A3 Brier minus reference | A3 log loss minus reference | A3 AUPRC minus reference |",
        "|---:|---|---:|---:|---:|---:|",
    ]
    for _, row in reference.iterrows():
        lines.append(f"| h={row['horizon']} | {row['reference']} | {fmt(row['coverage'])} | {fmt(row['a3_minus_reference_brier'])} | {fmt(row['a3_minus_reference_log_loss'])} | {fmt(row['a3_minus_reference_auprc'])} |")
    lines += [
        "",
        "## XIII. Artifacts",
        "",
        "Compact machine-readable results are stored under `analysis/p2_operational_nowcast/` in the repository. Large row-level prediction archives remain on the isolated Atlas output root and are described, hashed, and schema-checked by `results/prediction_archive_manifest.json`.",
        "",
        "## XIV. Atlas Execution",
        "",
        f"Atlas used the authorized WSL route and environment `{input_manifest.get('python_environment', 'recorded in atlas_execution.json')}`. Output root: `{input_manifest['atlas_output_root']}`. Job IDs and terminal states are recorded in `results/atlas_execution.json` after execution.",
        "",
        "## XV. CI / PR / Merge",
        "",
        "Hosted CI status and the PR/merge SHA are recorded in the final task handoff. If the repository reports no hosted workflow/status checks for this branch, that absence is recorded explicitly rather than treated as a passing hosted gate. Post-merge canonical-main verification is required before cleanup.",
        "",
        "## XVI. P2 Decision",
        "",
        f"Decision: `{decision['decision']}`. The fixed procedure was fit successfully at all eligible origins, but the conservative retrospective-only environmental availability classification and the P1 regional/frontier/count limitations prevent an unrestricted operational qualification. No recalibration or production-model modification was applied.",
        "",
        decision["marker"],
    ]
    output.mkdir(parents=True, exist_ok=True)
    (output / "p2_operational_nowcast_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def aggregate(args: argparse.Namespace) -> None:
    started = time.time()
    procedure = json.loads((args.output_root / "manifests" / "procedure_spec.json").read_text(encoding="utf-8"))
    input_manifest = json.loads((args.output_root / "manifests" / "input_manifest.json").read_text(encoding="utf-8"))
    origin_manifest = pd.read_csv(args.output_root / "manifests" / "rolling_origin_manifest.csv")
    statuses = []
    prediction_frames = []
    for _, row in origin_manifest.iterrows():
        origin_week = str(row["origin_week"])
        status_path = args.output_root / "manifests" / f"origin_{origin_week}.json"
        require(status_path.exists(), f"missing terminal origin status: {status_path}")
        status = json.loads(status_path.read_text(encoding="utf-8"))
        statuses.append(status)
        require(status.get("status") == "COMPLETED", f"origin {origin_week} did not complete: {status}")
        prediction_path = Path(status["prediction_artifact"])
        require(prediction_path.exists(), f"missing origin predictions: {prediction_path}")
        frame = pd.read_parquet(prediction_path)
        require(len(frame) == NODE_COUNT * MAX_HORIZON, f"origin {origin_week} prediction row count changed")
        prediction_frames.append(frame)
    fit_status = pd.DataFrame(statuses).sort_values("origin_index").reset_index(drop=True)
    frame = pd.concat(prediction_frames, ignore_index=True)
    require(len(frame) == len(origin_manifest) * NODE_COUNT * MAX_HORIZON, "combined prediction row count changed")
    require(not frame.duplicated(["origin_week", "target_week", "model_node_id"]).any(), "combined prediction keys are duplicated")
    require(set(frame["horizon"].unique()) == {1, 2, 3}, "combined horizons are not exactly 1,2,3")

    combined_path = args.output_root / "predictions" / "rolling_origin_predictions.parquet"
    occurrence_path = args.output_root / "predictions" / "occurrence_predictions.parquet"
    count_path = args.output_root / "predictions" / "count_predictions.parquet"
    write_parquet(combined_path, frame)
    occurrence_columns = ["origin_week", "target_week", "horizon", "model_node_id", "row", "column", "lon", "lat", "country_or_domain_region", "observed_positive", "p_occurrence", "persistence_probability", "historical_prevalence_probability", "historical_reference_source", "previously_occupied", "prediction_frontier_class", "outcome_frontier_label"]
    count_columns = ["origin_week", "target_week", "horizon", "model_node_id", "row", "column", "lon", "lat", "country_or_domain_region", "observed_count", "p_occurrence", "conditional_count_mean", "underlying_mu", "expected_count", "previously_occupied", "prediction_frontier_class", "outcome_frontier_label"]
    write_parquet(occurrence_path, frame[occurrence_columns])
    write_parquet(count_path, frame[count_columns])

    results = args.repository_results
    results.mkdir(parents=True, exist_ok=True)
    summary = aggregate_metrics(frame, fit_status)
    horizon_metrics = summary["horizon"]
    frontier_metrics = summary["frontier"]
    write_csv(results / "horizon_metrics.csv", horizon_metrics)
    write_csv(results / "frontier_metrics.csv", frontier_metrics)
    count_metric_frame = horizon_metrics[["scope", "horizon", "region", "n", "positive_n", "conditional_mae", "conditional_rmse", "conditional_bias", "conditional_observed_predicted_ratio", "conditional_zt_nb_nll", "full_expected_mae", "full_expected_rmse", "full_expected_bias", "observed_total", "predicted_expected_total"]]
    write_csv(results / "count_metrics.csv", count_metric_frame)

    reliability_rows: list[dict[str, Any]] = []
    for label in ["all", "1", "2", "3"]:
        reliability_rows.extend(calibration_bins(frame, label))
        reliability_rows.extend(count_calibration_bins(frame, label))
    write_csv(results / "calibration_bins.csv", pd.DataFrame(reliability_rows))
    horizon_deltas = pd.DataFrame(horizon_delta_rows(frame))
    write_csv(results / "horizon_deltas.csv", horizon_deltas)
    reference = reference_metrics(frame)
    write_csv(results / "reference_metrics.csv", reference)

    bootstrap_rows: list[dict[str, Any]] = []
    for offset, horizon in enumerate(["all", 1, 2, 3]):
        bootstrap_rows.extend(bootstrap_metric_rows(frame, "all", horizon, BOOTSTRAP_REPLICATES, BOOTSTRAP_SEED + offset))
    bootstrap_rows.extend(bootstrap_delta_rows(frame, BOOTSTRAP_REPLICATES, BOOTSTRAP_SEED + 10))
    write_csv(results / "bootstrap_intervals.csv", pd.DataFrame(bootstrap_rows))

    limitations = p1_limitation_rows(frame, fit_status, horizon_metrics, frontier_metrics)
    write_csv(results / "p1_limitation_metrics.csv", limitations)
    write_csv(results / "fit_status_manifest.csv", fit_status)
    write_csv(results / "rolling_origin_manifest.csv", origin_manifest)
    write_csv(results / "predictor_availability_audit.csv", pd.read_csv(args.output_root / "manifests" / "predictor_availability_audit.csv"))

    decision = {
        "decision": "P2_OPERATIONAL_NOWCAST_SUPPORTED_WITH_LIMITATIONS" if len(fit_status) and summary["successful"] == len(fit_status) else ("P2_OPERATIONAL_NOWCAST_NOT_SUPPORTED" if summary["successful"] == 0 else "P2_OPERATIONAL_NOWCAST_SUPPORTED_WITH_LIMITATIONS"),
        "marker": "P2_OPERATIONAL_NOWCAST_SUPPORTED_WITH_LIMITATIONS" if len(fit_status) and summary["successful"] == len(fit_status) else ("P2_OPERATIONAL_NOWCAST_NOT_SUPPORTED" if summary["successful"] == 0 else "P2_OPERATIONAL_NOWCAST_SUPPORTED_WITH_LIMITATIONS"),
        "fit_stability": {"eligible_origins": len(fit_status), "successful_origins": summary["successful"], "failed_origins": int(len(fit_status) - summary["successful"])},
        "primary_evaluation_label": procedure["primary_evaluation_label"],
        "limitations": limitations.to_dict(orient="records"),
        "no_recalibration": True,
        "no_feature_selection": True,
        "no_new_predictors": True,
        "no_long_horizon_primary_evaluation": True,
    }
    write_json(results / "decision.json", decision)
    write_json(results / "freeze_verification.json", json.loads((args.output_root / "manifests" / "freeze_verification.json").read_text(encoding="utf-8")))
    write_json(results / "prediction_archive_manifest.json", {
        "output_root": str(args.output_root),
        "combined_prediction_archive": {"path": str(combined_path), "sha256": sha256_file(combined_path), "rows": len(frame), "columns": list(frame.columns)},
        "occurrence_predictions": {"path": str(occurrence_path), "sha256": sha256_file(occurrence_path), "rows": len(frame), "columns": occurrence_columns},
        "count_predictions": {"path": str(count_path), "sha256": sha256_file(count_path), "rows": len(frame), "columns": count_columns},
        "protection_boundary": "row-level predictions remain on Atlas; compact summaries and provenance are committed to the repository",
    })
    metadata = {
        **input_manifest,
        "branch": git_value(args.repository_root, "branch", "--show-current"),
        "repository_sha": git_value(args.repository_root, "rev-parse", "HEAD"),
        "starting_main_sha": input_manifest.get("starting_main_sha"),
        "p0_merge_sha": input_manifest.get("p0_merge_sha"),
        "p1_merge_sha": input_manifest.get("p1_merge_sha"),
        "latest_week": str(frame["target_week"].max()),
        "last_origin": str(origin_manifest["origin_week"].iloc[-1]),
        "refresh_week_count": int(len(pd.read_parquet(args.model_output / "raw" / "weeks.parquet"))),
        "eligible_origins": int(len(origin_manifest)),
        "successful_origins": int(summary["successful"]),
        "failed_origins": int(len(fit_status) - summary["successful"]),
        "runtime_seconds": time.time() - started,
        "bootstrap_replicates": BOOTSTRAP_REPLICATES,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "atlas_output_root": str(args.output_root),
    }
    write_json(results / "run_metadata.json", metadata)
    render_report(results.parent, args.repository_root, procedure, metadata, fit_status, horizon_metrics, frontier_metrics, horizon_deltas, reference, limitations, decision)
    print(json.dumps({"status": "AGGREGATED", "decision": decision["decision"], "successful_origins": summary["successful"], "eligible_origins": len(fit_status), "rows": len(frame)}, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["prepare", "origin", "aggregate"], required=True)
    parser.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--repository-results", type=Path, default=None)
    parser.add_argument("--model-output", type=Path, required=True)
    parser.add_argument("--front-features", type=Path, required=True)
    parser.add_argument("--road-night", type=Path, required=True)
    parser.add_argument("--soil", type=Path, required=True)
    parser.add_argument("--origin-index", type=int, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.repository_root = args.repository_root.resolve()
    args.output_root = args.output_root.resolve()
    args.model_output = args.model_output.resolve()
    args.front_features = args.front_features.resolve()
    args.road_night = args.road_night.resolve()
    args.soil = args.soil.resolve()
    if args.repository_results is None:
        args.repository_results = args.repository_root / "analysis" / "p2_operational_nowcast" / "results"
    else:
        args.repository_results = args.repository_results.resolve()
    try:
        if args.mode == "prepare":
            prepare(args)
        elif args.mode == "origin":
            require(args.origin_index is not None, "--origin-index is required for origin mode")
            origin(args)
        else:
            aggregate(args)
    except Exception as exc:
        print(f"P2_OPERATIONAL_NOWCAST_FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


