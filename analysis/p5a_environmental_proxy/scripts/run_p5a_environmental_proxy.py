#!/usr/bin/env python3
"""Run the prespecified P5A issue-time environmental proxy evaluation.

The workflow reuses the immutable P2 rolling-origin fits and reference archive.
It never refits STRUCTURED_A3.  Only the first 12 frozen environmental feature
columns are replaced for E0/E1; every other predictor remains the P2 value.
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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, log_loss, roc_auc_score

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
P2_SCRIPT_ROOT = REPOSITORY_ROOT / "analysis" / "p2_operational_nowcast" / "scripts"
P4_SCRIPT_ROOT = REPOSITORY_ROOT / "analysis" / "p4_uncertainty_extrapolation" / "scripts"
sys.path.insert(0, str(P2_SCRIPT_ROOT))
sys.path.insert(0, str(P4_SCRIPT_ROOT))
from run_p2_operational_nowcast import (  # noqa: E402
    FEATURE_COUNT,
    FEATURE_ORDER,
    FIXED_THETA,
    NODE_COUNT,
    predict,
)
from run_p4_uncertainty_extrapolation import (  # noqa: E402
    nearest_distances,
    support_class_from_inputs,
    training_reference,
)

MODEL_ID = "STRUCTURED_A3"
P0_MODEL_SHA256 = "8a6a0a32a1a1e56f810b6aa1eafec5207dc3ac8d45cdf2270999f9721f080d1e"
P5_MERGE_SHA = "650edd2397279a1a6a68dd89e42c724621d6da04"
P2_ARCHIVE_SHA256 = "918b33e80d352c080fcefb3d7b2a44dc29d0096b0b2e7dd6f5b017becc983170"
P2_EXPECTED_ROWS = 632_331
P2_ORIGINS = [f"2026-W{week:02d}" for week in range(16, 37)]
HORIZONS = (1, 2, 3)
ENV_COUNT = 12
ISSUE_LAG_WEEKS = 1
E2_MIN_SEASONAL_CYCLES = 2
BOOTSTRAP_REPLICATES = 199
BOOTSTRAP_SEED = 20261029
PROXY_IDS = ["REALIZED_ENV", "E0_LAST_AVAILABLE", "E1_TRAILING3_MEAN", "E2_SEASONAL_EXPECTATION"]
ENVIRONMENTAL_FEATURES = list(FEATURE_ORDER[:ENV_COUNT])
STATIC_AND_DERIVED = list(FEATURE_ORDER[ENV_COUNT:])
FAMILY_BY_FEATURE = {
    "era5_mintemp": "temperature",
    "era5land_tmean": "temperature",
    "era5land_soiltemp_l1_mean": "temperature",
    "era5land_soiltemp_l2_mean": "temperature",
    "era5_soilmoist": "moisture_water",
    "era5land_soilwater_l1_mean": "moisture_water",
    "era5land_soilwater_l2_mean": "moisture_water",
    "era5_lai_low": "vegetation",
    "era5land_lai_high_mean": "vegetation",
    "era5land_lai_low_mean": "vegetation",
    "agera5_relhum_min": "humidity_pressure",
    "era5land_surface_pressure_mean": "humidity_pressure",
}
KEY_COLUMNS = ["origin_week", "target_week", "horizon", "model_node_id"]
METRIC_NAMES = [
    "brier", "calibration_intercept", "calibration_slope", "log_loss", "auroc", "auprc",
    "conditional_mae", "conditional_rmse", "conditional_bias", "conditional_observed_predicted_ratio",
    "full_expected_mae", "full_expected_rmse", "full_expected_bias",
]


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


def week_date(value: str) -> datetime:
    year, week = parse_week(value)
    return datetime.fromisocalendar(year, week, 1)


def add_weeks(value: str, offset: int) -> str:
    date = week_date(value) + timedelta(weeks=offset)
    iso = date.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def issue_timestamp(origin_week: str) -> str:
    return (week_date(origin_week) + timedelta(weeks=1)).replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def latest_available_week(origin_week: str) -> str:
    return add_weeks(origin_week, -ISSUE_LAG_WEEKS)


def make_key(frame: pd.DataFrame) -> pd.Series:
    return (
        frame["origin_week"].astype(str) + "|" + frame["target_week"].astype(str) + "|"
        + frame["horizon"].astype(int).astype(str) + "|" + frame["model_node_id"].astype(int).astype(str)
    )


def verify_p0(repository_root: Path) -> dict[str, Any]:
    sys.path.insert(0, str(repository_root))
    from scripts.verify_production_model_freeze import check_artifacts, load_json, verify

    manifest_path = repository_root / "config" / "production_model_freeze.json"
    verification = verify(manifest_path, repository_root)
    require(all(value == "PASS" for value in verification.values() if isinstance(value, str)), f"P0 verification failed: {verification}")
    manifest = load_json(manifest_path)
    model_path = check_artifacts(manifest, repository_root)["frozen_model_metadata_and_coefficients"]
    require(sha256_file(model_path) == P0_MODEL_SHA256, "P0 model artifact hash changed")
    return verification


def p2_provenance(repository_root: Path, p2_output_root: Path) -> tuple[pd.DataFrame, dict[str, Any], dict[str, Any]]:
    manifest = json.loads((repository_root / "analysis" / "p2_operational_nowcast" / "results" / "prediction_archive_manifest.json").read_text(encoding="utf-8"))
    metadata = json.loads((repository_root / "analysis" / "p2_operational_nowcast" / "results" / "run_metadata.json").read_text(encoding="utf-8"))
    archive = p2_output_root / "predictions" / "rolling_origin_predictions.parquet"
    expected = manifest["combined_prediction_archive"]
    require(archive.exists(), f"missing P2 archive: {archive}")
    require(sha256_file(archive) == expected["sha256"] == P2_ARCHIVE_SHA256, "P2 archive hash changed")
    frame = pd.read_parquet(archive)
    require(len(frame) == P2_EXPECTED_ROWS == int(expected["rows"]), "P2 archive row count changed")
    require(set(frame["origin_week"].astype(str).unique()) == set(P2_ORIGINS), "P2 origin set changed")
    require(set(frame["horizon"].astype(int).unique()) == set(HORIZONS), "P2 horizon set changed")
    require(metadata["p0_model_artifact_sha256"] == P0_MODEL_SHA256, "P2 provenance does not preserve frozen model hash")
    return frame, manifest, metadata


def load_support_reference(p4_root: Path) -> pd.DataFrame:
    path = p4_root / "support_classifications.parquet"
    require(path.exists(), f"missing P4 support reference: {path}")
    support = pd.read_parquet(path, columns=[*KEY_COLUMNS, "support_class", "novelty_knn_distance"])
    support["key"] = make_key(support)
    require(not support["key"].duplicated().any(), "P4 support reference keys are duplicated")
    return support


def proxy_applicability() -> pd.DataFrame:
    rows = []
    for name in FEATURE_ORDER:
        if name in ENVIRONMENTAL_FEATURES:
            lagged = name in {
                "era5land_soiltemp_l1_mean", "era5land_soiltemp_l2_mean",
                "era5land_soilwater_l1_mean", "era5land_soilwater_l2_mean",
            }
            rows.append({
                "predictor": name,
                "frozen_role": "already_lagged_environment" if lagged else "dynamic_environment",
                "availability_class": "RETROSPECTIVE_ONLY",
                "proxy_applicable": True,
                "proxy_rule": "feature-level E0/E1/E2; no re-lagging or re-transformation" if lagged else "E0/E1/E2 feature-level proxy",
                "family": FAMILY_BY_FEATURE[name],
            })
        else:
            rows.append({
                "predictor": name,
                "frozen_role": "static_or_derived_non_environment",
                "availability_class": "UNCHANGED_FROM_P2",
                "proxy_applicable": False,
                "proxy_rule": "unchanged P2 value",
                "family": "non_environment",
            })
    return pd.DataFrame(rows)


def seasonal_cycle_count(labels: list[str], target_week: str, latest_week: str) -> int:
    target_number = parse_week(target_week)[1]
    return sum(parse_week(label)[1] == target_number and parse_week(label) <= parse_week(latest_week) for label in labels)


def availability_table(labels: list[str], origins: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    e2_rows = []
    for origin in origins:
        latest = latest_available_week(origin)
        latest_index = labels.index(latest)
        window = [add_weeks(latest, -offset) for offset in range(3)]
        targets = [add_weeks(origin, h) for h in HORIZONS]
        for proxy_id in ["E0_LAST_AVAILABLE", "E1_TRAILING3_MEAN", "E2_SEASONAL_EXPECTATION"]:
            for predictor in ENVIRONMENTAL_FEATURES:
                for horizon, target in zip(HORIZONS, targets):
                    cycles = seasonal_cycle_count(labels, target, latest)
                    feasible = len(window) == 3 and all(item in labels and labels.index(item) <= latest_index for item in window)
                    if proxy_id == "E2_SEASONAL_EXPECTATION":
                        feasible = cycles >= E2_MIN_SEASONAL_CYCLES
                    rows.append({
                        "origin_week": origin,
                        "issue_timestamp": issue_timestamp(origin),
                        "target_week": target,
                        "horizon": horizon,
                        "predictor": predictor,
                        "proxy_id": proxy_id,
                        "latest_available_week": latest,
                        "environmental_window": ";".join(window) if proxy_id == "E1_TRAILING3_MEAN" else latest,
                        "seasonal_cycles_available": cycles,
                        "status": "AVAILABLE" if feasible else "NOT_EVALUABLE",
                        "cutoff_rule": "observation_week <= T-1",
                    })
        for target in targets:
            e2_rows.append({
                "origin_week": origin,
                "target_week": target,
                "horizon": targets.index(target) + 1,
                "latest_available_week": latest,
                "seasonal_cycles_available": seasonal_cycle_count(labels, target, latest),
                "required_seasonal_cycles": E2_MIN_SEASONAL_CYCLES,
                "status": "AVAILABLE" if seasonal_cycle_count(labels, target, latest) >= E2_MIN_SEASONAL_CYCLES else "NOT_EVALUABLE",
                "reason": "insufficient prior seasonal cycles" if seasonal_cycle_count(labels, target, latest) < E2_MIN_SEASONAL_CYCLES else "",
            })
    return pd.DataFrame(rows), pd.DataFrame(e2_rows)


def prepare(args: argparse.Namespace) -> None:
    root = args.output_root
    for folder in ("origins", "manifests", "metrics", "figures", "logs"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    verification = verify_p0(args.repository_root)
    p2_frame, p2_manifest, p2_metadata = p2_provenance(args.repository_root, args.p2_output_root)
    raw = args.model_output / "raw"
    weeks = pd.read_parquet(raw / "weeks.parquet")
    labels = weeks["iso_week"].astype(str).tolist()
    origins = sorted(p2_frame["origin_week"].astype(str).unique(), key=parse_week)
    require(origins == P2_ORIGINS, "P2 origin manifest does not match the prespecified 21 origins")
    applicability = proxy_applicability()
    availability, e2 = availability_table(labels, origins)
    origin_rows = []
    for index, origin in enumerate(origins):
        target_weeks = [add_weeks(origin, h) for h in HORIZONS]
        origin_rows.append({
            "origin_index": index,
            "origin_week": origin,
            "issue_timestamp": issue_timestamp(origin),
            "latest_available_week": latest_available_week(origin),
            "target_weeks": ";".join(target_weeks),
            "horizons": "1;2;3",
            "status": "PENDING",
        })
    write_csv(root / "manifests" / "origin_manifest.csv", pd.DataFrame(origin_rows))
    write_csv(root / "manifests" / "proxy_applicability.csv", applicability)
    write_csv(root / "manifests" / "issue_time_environmental_availability.csv", availability)
    write_csv(root / "manifests" / "e2_feasibility.csv", e2)
    write_json(root / "manifests" / "freeze_verification.json", verification)
    write_json(root / "manifests" / "p2_reference_manifest.json", {
        "p2_archive_sha256": p2_manifest["combined_prediction_archive"]["sha256"],
        "p2_archive_rows": int(p2_manifest["combined_prediction_archive"]["rows"]),
        "p2_output_root": str(args.p2_output_root),
        "p2_metadata_sha256": hashlib.sha256(json.dumps(p2_metadata, sort_keys=True).encode()).hexdigest(),
        "p2_origins": origins,
        "p2_horizons": list(HORIZONS),
    })
    write_json(root / "manifests" / "proxy_contract.json", {
        "proxy_ids": PROXY_IDS,
        "environmental_predictors": ENVIRONMENTAL_FEATURES,
        "non_environmental_predictors_unchanged": STATIC_AND_DERIVED,
        "issue_time_cutoff": "observation_week <= T-1",
        "latest_available_rule": "L(T)=T-1",
        "e1_window": 3,
        "e2_minimum_seasonal_cycles": E2_MIN_SEASONAL_CYCLES,
        "bootstrap_replicates": BOOTSTRAP_REPLICATES,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "model_id": MODEL_ID,
        "model_sha256": P0_MODEL_SHA256,
        "p5_merge_sha": P5_MERGE_SHA,
        "no_model_refit": True,
    })
    write_json(root / "manifests" / "run_metadata.json", {
        "status": "PREPARED",
        "repository_sha": git_value(args.repository_root, "rev-parse", "HEAD"),
        "model_id": MODEL_ID,
        "model_sha256": P0_MODEL_SHA256,
        "p5_merge_sha": P5_MERGE_SHA,
        "origin_count": len(origins),
        "origins": origins,
        "horizons": list(HORIZONS),
        "e2_status": "NOT_EVALUABLE_INSUFFICIENT_SEASONAL_ARCHIVE" if not e2.loc[e2["status"] == "AVAILABLE"].shape[0] else "PARTIAL",
        "p2_archive_sha256": p2_manifest["combined_prediction_archive"]["sha256"],
        "p2_archive_rows": int(p2_manifest["combined_prediction_archive"]["rows"]),
    })
    print(json.dumps({"status": "PREPARED", "origins": len(origins), "e2_available_rows": int((e2["status"] == "AVAILABLE").sum())}, indent=2))


def load_fit(path: Path) -> dict[str, Any]:
    require(path.exists(), f"missing P2 fit artifact: {path}")
    fit = json.loads(path.read_text(encoding="utf-8"))
    require(fit.get("model") == MODEL_ID, f"fit artifact model changed: {path}")
    require(fit.get("feature_order") == FEATURE_ORDER and fit.get("feature_count") == FEATURE_COUNT, f"fit schema changed: {path}")
    require(float(fit.get("theta")) == FIXED_THETA and float(fit.get("penalty")) == 0.01, f"fit hyperparameters changed: {path}")
    return fit


def predict_from_fit(fit: dict[str, Any], raw_eval: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    preprocessing = fit["preprocessing"]
    mean = np.asarray(preprocessing["training_mean"], dtype=np.float64)
    scale = np.asarray(preprocessing["training_sd"], dtype=np.float64)
    require(mean.shape == (FEATURE_COUNT,) and scale.shape == (FEATURE_COUNT,), "fit preprocessing schema changed")
    x_eval = (raw_eval - mean[None, :]) / scale[None, :]
    state = {
        "occurrence_beta": np.asarray(fit["occurrence_coefficients"], dtype=np.float64),
        "count_beta": np.asarray(fit["count_coefficients"], dtype=np.float64),
    }
    return predict(state, x_eval)


def build_proxy_environment(dynamic: np.ndarray, labels: list[str], origin: str, proxy_id: str) -> tuple[np.ndarray | None, dict[str, Any]]:
    origin_index = labels.index(origin)
    latest_index = origin_index - ISSUE_LAG_WEEKS
    require(latest_index >= 2, f"origin {origin} lacks the fixed E1 window")
    latest = labels[latest_index]
    if proxy_id == "E0_LAST_AVAILABLE":
        values = np.broadcast_to(dynamic[latest_index][None, :, :], (3, dynamic.shape[1], ENV_COUNT)).copy()
        return values, {"latest_available_week": latest, "window": latest, "rule": "persist latest safely prior feature state"}
    if proxy_id == "E1_TRAILING3_MEAN":
        values = np.mean(dynamic[latest_index - 2 : latest_index + 1, :, :], axis=0)
        values = np.broadcast_to(values[None, :, :], (3, dynamic.shape[1], ENV_COUNT)).copy()
        window = [labels[item] for item in range(latest_index - 2, latest_index + 1)]
        return values, {"latest_available_week": latest, "window": ";".join(window), "rule": "fixed mean of exactly three prior feature states"}
    if proxy_id == "E2_SEASONAL_EXPECTATION":
        return None, {"latest_available_week": latest, "window": "", "rule": "infeasible unless two prior seasonal cycles exist"}
    raise ValueError(f"unknown proxy: {proxy_id}")


def support_for_raw(raw_eval: np.ndarray, support_context: dict[str, Any]) -> pd.DataFrame:
    means = support_context["means"]
    scales = support_context["scales"]
    eval_z = (raw_eval - means[None, :]) / scales[None, :]
    distances = nearest_distances(support_context["tree"], eval_z)
    support, _ = support_class_from_inputs(
        raw_eval, eval_z, distances, support_context["reference"], support_context["train_loo"]
    )
    return support


def environment_error_rows(dynamic: np.ndarray, labels: list[str], origin: str, proxy_id: str, env_values: np.ndarray) -> list[dict[str, Any]]:
    if env_values is None:
        return []
    origin_index = labels.index(origin)
    rows = []
    for offset, horizon in enumerate(HORIZONS):
        target_index = origin_index + horizon
        target = dynamic[target_index]
        proxy = env_values[offset]
        for feature_index, predictor in enumerate(ENVIRONMENTAL_FEATURES):
            real = target[:, feature_index].astype(float)
            pred = proxy[:, feature_index].astype(float)
            diff = pred - real
            finite = np.isfinite(real) & np.isfinite(pred)
            real = real[finite]
            pred = pred[finite]
            diff = diff[finite]
            correlation = float(np.corrcoef(pred, real)[0, 1]) if len(real) > 1 and np.std(pred) > 0 and np.std(real) > 0 else math.nan
            rows.append({
                "origin_week": origin,
                "target_week": labels[target_index],
                "horizon": horizon,
                "proxy_id": proxy_id,
                "predictor": predictor,
                "family": FAMILY_BY_FEATURE[predictor],
                "n": int(len(diff)),
                "sum_error": float(diff.sum()),
                "sum_abs_error": float(np.abs(diff).sum()),
                "sum_sq_error": float(np.square(diff).sum()),
                "sum_proxy": float(pred.sum()),
                "sum_realized": float(real.sum()),
                "sum_proxy_sq": float(np.square(pred).sum()),
                "sum_realized_sq": float(np.square(real).sum()),
                "sum_proxy_realized": float((pred * real).sum()),
                "mean_error": float(diff.mean()) if len(diff) else math.nan,
                "mae": float(np.abs(diff).mean()) if len(diff) else math.nan,
                "rmse": float(np.sqrt(np.mean(np.square(diff)))) if len(diff) else math.nan,
                "correlation": correlation,
            })
    return rows


def p2_reference_for_origin(p2_frame: pd.DataFrame, origin: str) -> pd.DataFrame:
    ref = p2_frame.loc[p2_frame["origin_week"].astype(str).eq(origin)].copy()
    ref = ref.sort_values(["horizon", "model_node_id"], kind="mergesort").reset_index(drop=True)
    require(len(ref) == NODE_COUNT * len(HORIZONS), f"origin {origin} P2 row count changed")
    require(not ref.duplicated(KEY_COLUMNS).any(), f"origin {origin} P2 keys duplicated")
    return ref


def origin_run(args: argparse.Namespace, context: dict[str, Any], origin: str) -> dict[str, Any]:
    root = args.output_root
    status_path = root / "origins" / f"origin_{origin}.json"
    prediction_path = root / "origins" / f"origin_{origin}.parquet"
    error_path = root / "origins" / f"environment_error_{origin}.csv"
    if status_path.exists() and prediction_path.exists() and error_path.exists():
        try:
            status = json.loads(status_path.read_text(encoding="utf-8"))
            if status.get("status") == "COMPLETED":
                return status
        except Exception:
            pass
    started = time.time()
    labels = context["labels"]
    origin_index = labels.index(origin)
    target_indices = [origin_index + h for h in HORIZONS]
    fit = load_fit(args.p2_output_root / "fits" / f"origin_{origin}.json")
    ref = p2_reference_for_origin(context["p2_frame"], origin)
    rows = []
    errors = []
    e2_available = bool((context["e2"].loc[(context["e2"]["origin_week"] == origin) & (context["e2"]["status"] == "AVAILABLE")]).shape[0] == len(HORIZONS))
    for proxy_id in PROXY_IDS:
        if proxy_id == "REALIZED_ENV":
            frame = ref[[*KEY_COLUMNS, "row", "column", "lon", "lat", "country_or_domain_region", "observed_count", "observed_positive", "previously_occupied", "prediction_frontier_class", "outcome_frontier_label", "p_occurrence", "conditional_count_mean", "underlying_mu", "expected_count"]].copy()
            frame["proxy_id"] = proxy_id
            frame["proxy_source_week"] = frame["target_week"].astype(str)
            frame["proxy_window"] = frame["target_week"].astype(str)
            frame["proxy_rule"] = "unchanged P2 realized-environment reference"
            support = context["p4_support"].set_index("key").reindex(make_key(frame).to_numpy())
            require(support["support_class"].notna().all(), "P4 realized support reference does not cover P2 keys")
            frame["support_class"] = support["support_class"].to_numpy()
            frame["novelty_knn_distance"] = support["novelty_knn_distance"].to_numpy()
            rows.append(frame)
            continue
        env_values, proxy_meta = build_proxy_environment(context["dynamic"], labels, origin, proxy_id)
        if env_values is None or (proxy_id == "E2_SEASONAL_EXPECTATION" and not e2_available):
            continue
        raw_target = np.asarray(context["features"][target_indices], dtype=np.float64).copy()
        raw_target[:, :, :ENV_COUNT] = env_values
        flat_raw = raw_target.reshape(-1, FEATURE_COUNT)
        probability, conditional, mu = predict_from_fit(fit, flat_raw)
        frame = ref[[*KEY_COLUMNS, "row", "column", "lon", "lat", "country_or_domain_region", "observed_count", "observed_positive", "previously_occupied", "prediction_frontier_class", "outcome_frontier_label"]].copy()
        frame["proxy_id"] = proxy_id
        frame["proxy_source_week"] = proxy_meta["latest_available_week"]
        frame["proxy_window"] = proxy_meta["window"]
        frame["proxy_rule"] = proxy_meta["rule"]
        frame["p_occurrence"] = probability
        frame["conditional_count_mean"] = conditional
        frame["underlying_mu"] = mu
        frame["expected_count"] = probability * conditional
        support = support_for_raw(flat_raw, context["support_context"])
        frame["support_class"] = support["support_class"].to_numpy()
        frame["novelty_knn_distance"] = support["novelty_knn_distance"].to_numpy()
        rows.append(frame)
        errors.extend(environment_error_rows(context["dynamic"], labels, origin, proxy_id, env_values))
    predictions = pd.concat(rows, ignore_index=True)
    predictions["key"] = make_key(predictions)
    require(not predictions[["key", "proxy_id"]].duplicated().any(), f"origin {origin} proxy keys duplicated")
    require(set(predictions["proxy_id"].unique()) >= {"REALIZED_ENV", "E0_LAST_AVAILABLE", "E1_TRAILING3_MEAN"}, f"origin {origin} missing required proxy")
    write_parquet(prediction_path, predictions)
    write_csv(error_path, pd.DataFrame(errors))
    status = {
        "status": "COMPLETED",
        "origin_week": origin,
        "issue_timestamp": issue_timestamp(origin),
        "latest_available_week": latest_available_week(origin),
        "target_weeks": [add_weeks(origin, h) for h in HORIZONS],
        "horizons": list(HORIZONS),
        "proxy_ids_evaluated": sorted(predictions["proxy_id"].unique().tolist()),
        "e2_status": "AVAILABLE" if e2_available else "NOT_EVALUABLE_INSUFFICIENT_SEASONAL_ARCHIVE",
        "rows": int(len(predictions)),
        "prediction_sha256": sha256_file(prediction_path),
        "fit_artifact": str(args.p2_output_root / "fits" / f"origin_{origin}.json"),
        "fit_artifact_sha256": sha256_file(args.p2_output_root / "fits" / f"origin_{origin}.json"),
        "runtime_seconds": time.time() - started,
        "model_id": MODEL_ID,
        "model_sha256": P0_MODEL_SHA256,
        "no_model_refit": True,
    }
    write_json(status_path, status)
    return status


def update_ledger(root: Path, statuses: list[dict[str, Any]]) -> None:
    ordered = sorted(statuses, key=lambda row: parse_week(row["origin_week"]))
    ledger = pd.DataFrame(ordered)
    write_csv(root / "manifests" / "completion_ledger.csv", ledger)
    manifest_path = root / "manifests" / "origin_manifest.csv"
    if manifest_path.exists():
        manifest = pd.read_csv(manifest_path)
        status_map = ledger.set_index("origin_week")["status"].to_dict()
        manifest["status"] = manifest["origin_week"].astype(str).map(status_map).fillna(manifest["status"])
        write_csv(manifest_path, manifest)


def load_context(args: argparse.Namespace) -> dict[str, Any]:
    p2_frame, _, _ = p2_provenance(args.repository_root, args.p2_output_root)
    raw = args.model_output / "raw"
    weeks = pd.read_parquet(raw / "weeks.parquet")
    labels = weeks["iso_week"].astype(str).tolist()
    dynamic = np.asarray(np.load(raw / "dynamic_features.npy", mmap_mode="r"), dtype=np.float64)
    counts = np.asarray(np.load(raw / "targets_count.npy", mmap_mode="r"), dtype=np.int64)
    features = np.load(args.p2_output_root / "manifests" / "a3_features.npy", mmap_mode="r")
    require(dynamic.shape == (len(labels), NODE_COUNT, ENV_COUNT), f"dynamic feature shape changed: {dynamic.shape}")
    require(features.shape == (len(labels), NODE_COUNT, FEATURE_COUNT), f"P2 feature cache shape changed: {features.shape}")
    require(counts.shape == (len(labels), NODE_COUNT), f"response shape changed: {counts.shape}")
    p4_support = load_support_reference(args.p4_root)
    raw_train, train_z, _, reference = training_reference(features)
    tree = cKDTree(train_z, leafsize=40, compact_nodes=True, balanced_tree=True)
    try:
        train_loo = tree.query(train_z, k=2, workers=-1)[0][:, 1]
    except TypeError:
        train_loo = tree.query(train_z, k=2)[0][:, 1]
    # The reference support calculation is performed once and then reused for
    # each proxy. This keeps the P4 thresholds and training reference unchanged.
    return {
        "labels": labels,
        "dynamic": dynamic,
        "counts": counts,
        "features": features,
        "p2_frame": p2_frame,
        "p4_support": p4_support,
        "e2": pd.read_csv(args.output_root / "manifests" / "e2_feasibility.csv"),
        "support_context": {
            "tree": tree,
            "reference": reference,
            "train_loo": train_loo,
            "means": np.asarray(training_reference(features)[2]["training_mean"], dtype=np.float64),
            "scales": np.asarray(training_reference(features)[2]["training_sd"], dtype=np.float64),
        },
        "raw_train_rows": int(len(raw_train)),
    }


def calibration_values(y: np.ndarray, p: np.ndarray) -> tuple[float, float]:
    if len(np.unique(y)) < 2:
        return math.nan, math.nan
    model = LogisticRegression(C=1e6, solver="lbfgs", max_iter=200)
    model.fit(np.log(np.clip(p, 1e-12, 1 - 1e-12) / np.clip(1 - p, 1e-12, 1)).reshape(-1, 1), y.astype(np.int8))
    return float(model.intercept_[0]), float(model.coef_[0, 0])


def occurrence_metrics(frame: pd.DataFrame) -> dict[str, Any]:
    y = frame["observed_positive"].to_numpy(np.int8)
    p = np.clip(frame["p_occurrence"].to_numpy(float), 1e-12, 1 - 1e-12)
    result = {
        "n": int(len(frame)),
        "positives": int(y.sum()),
        "prevalence": float(y.mean()) if len(y) else math.nan,
        "brier": float(np.mean((p - y) ** 2)) if len(y) else math.nan,
        "calibration_intercept": math.nan,
        "calibration_slope": math.nan,
        "log_loss": float(log_loss(y, p, labels=[0, 1])) if len(y) else math.nan,
        "auroc": math.nan,
        "auprc": math.nan,
    }
    if len(np.unique(y)) == 2:
        result["calibration_intercept"], result["calibration_slope"] = calibration_values(y, p)
        result["auroc"] = float(roc_auc_score(y, p))
        result["auprc"] = float(average_precision_score(y, p))
    return result


def count_metrics(frame: pd.DataFrame) -> dict[str, Any]:
    y = frame["observed_count"].to_numpy(float)
    conditional = frame["conditional_count_mean"].to_numpy(float)
    expected = frame["expected_count"].to_numpy(float)
    positive = y > 0
    result = {
        "conditional_mae": math.nan,
        "conditional_rmse": math.nan,
        "conditional_bias": math.nan,
        "conditional_observed_predicted_ratio": math.nan,
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
        })
    return result


def all_metrics(frame: pd.DataFrame) -> dict[str, Any]:
    return {**occurrence_metrics(frame), **count_metrics(frame)}


def summarize_environment_errors(errors: pd.DataFrame) -> pd.DataFrame:
    if errors.empty:
        return errors
    group_cols = ["proxy_id", "horizon", "predictor", "family"]
    rows = []
    for key, group in errors.groupby(group_cols, sort=True):
        n = float(group["n"].sum())
        sum_error = float(group["sum_error"].sum())
        sum_abs = float(group["sum_abs_error"].sum())
        sum_sq = float(group["sum_sq_error"].sum())
        sx = float(group["sum_proxy"].sum())
        sy = float(group["sum_realized"].sum())
        sxx = float(group["sum_proxy_sq"].sum())
        syy = float(group["sum_realized_sq"].sum())
        sxy = float(group["sum_proxy_realized"].sum())
        numerator = n * sxy - sx * sy
        denominator = math.sqrt(max(n * sxx - sx * sx, 0.0) * max(n * syy - sy * sy, 0.0))
        rows.append({
            **dict(zip(group_cols, key)),
            "n": int(n),
            "mean_error": sum_error / n if n else math.nan,
            "mae": sum_abs / n if n else math.nan,
            "rmse": math.sqrt(sum_sq / n) if n else math.nan,
            "correlation": numerator / denominator if denominator > 0 else math.nan,
        })
    return pd.DataFrame(rows)


def bootstrap_difference(proxy: pd.DataFrame, realized: pd.DataFrame, metric: str, horizon: int, seed: int) -> dict[str, Any]:
    p = proxy.loc[proxy["horizon"].astype(int).eq(horizon)].copy()
    r = realized.loc[realized["horizon"].astype(int).eq(horizon)].copy()
    require(np.array_equal(p["key"].to_numpy(), r["key"].to_numpy()), "paired key order changed during bootstrap")
    weeks = sorted(p["target_week"].astype(str).unique(), key=parse_week)
    positions = {week: np.flatnonzero(p["target_week"].astype(str).to_numpy() == week) for week in weeks}
    rng = np.random.default_rng(seed)
    values = []
    for _ in range(BOOTSTRAP_REPLICATES):
        sampled = rng.choice(np.asarray(weeks, dtype=object), size=len(weeks), replace=True)
        indices = np.concatenate([positions[str(week)] for week in sampled])
        ps = p.iloc[indices]
        rs = r.iloc[indices]
        if metric == "frontier_brier":
            mask_p = ps["prediction_frontier_class"].astype(str).eq("previously_unoccupied")
            mask_r = rs["prediction_frontier_class"].astype(str).eq("previously_unoccupied")
            ps = ps.loc[mask_p]
            rs = rs.loc[mask_r]
            value = occurrence_metrics(ps)["brier"] - occurrence_metrics(rs)["brier"] if len(ps) else math.nan
        else:
            value = all_metrics(ps).get(metric, math.nan) - all_metrics(rs).get(metric, math.nan)
        if np.isfinite(value):
            values.append(float(value))
    estimate = all_metrics(p).get(metric, math.nan) - all_metrics(r).get(metric, math.nan) if metric != "frontier_brier" else (
        occurrence_metrics(p.loc[p["prediction_frontier_class"].astype(str).eq("previously_unoccupied")])["brier"]
        - occurrence_metrics(r.loc[r["prediction_frontier_class"].astype(str).eq("previously_unoccupied")])["brier"]
    )
    return {
        "horizon": horizon,
        "metric": metric,
        "estimate": float(estimate),
        "lower": float(np.quantile(values, 0.025)) if values else math.nan,
        "upper": float(np.quantile(values, 0.975)) if values else math.nan,
        "bootstrap_replicates": int(len(values)),
        "seed": seed,
    }


def aggregate(args: argparse.Namespace, context: dict[str, Any]) -> dict[str, Any]:
    root = args.output_root
    statuses = [json.loads(path.read_text(encoding="utf-8")) for path in sorted((root / "origins").glob("origin_*.json"))]
    statuses = sorted(statuses, key=lambda row: parse_week(row["origin_week"]))
    require(len(statuses) == len(P2_ORIGINS) and all(row.get("status") == "COMPLETED" for row in statuses), "not all P5A origins completed")
    predictions = pd.concat([pd.read_parquet(root / "origins" / f"origin_{row['origin_week']}.parquet") for row in statuses], ignore_index=True)
    errors = pd.concat([pd.read_csv(root / "origins" / f"environment_error_{row['origin_week']}.csv") for row in statuses], ignore_index=True)
    require(not predictions.duplicated([*KEY_COLUMNS, "proxy_id"]).any(), "P5A prediction keys are duplicated")
    require(set(predictions["proxy_id"].unique()) == {"REALIZED_ENV", "E0_LAST_AVAILABLE", "E1_TRAILING3_MEAN"}, "unexpected evaluated proxy set")
    write_parquet(root / "metrics" / "paired_predictions.parquet", predictions)
    metrics_rows = []
    for proxy_id in PROXY_IDS:
        if proxy_id not in set(predictions["proxy_id"]):
            continue
        proxy = predictions.loc[predictions["proxy_id"].eq(proxy_id)]
        for horizon in HORIZONS:
            group = proxy.loc[proxy["horizon"].astype(int).eq(horizon)]
            metrics_rows.append({"proxy_id": proxy_id, "horizon": horizon, **all_metrics(group)})
    metrics = pd.DataFrame(metrics_rows)
    write_csv(root / "metrics" / "occurrence_count_metrics.csv", metrics)

    realized = predictions.loc[predictions["proxy_id"].eq("REALIZED_ENV")].sort_values(KEY_COLUMNS, kind="mergesort").reset_index(drop=True)
    paired_rows = []
    coverage_rows = []
    for proxy_id in ["E0_LAST_AVAILABLE", "E1_TRAILING3_MEAN", "E2_SEASONAL_EXPECTATION"]:
        if proxy_id not in set(predictions["proxy_id"]):
            for horizon in HORIZONS:
                coverage_rows.append({"proxy_id": proxy_id, "horizon": horizon, "paired_n": 0, "reference_n": int((realized["horizon"] == horizon).sum()), "coverage": 0.0, "status": "NOT_EVALUABLE"})
            continue
        proxy = predictions.loc[predictions["proxy_id"].eq(proxy_id)].sort_values(KEY_COLUMNS, kind="mergesort").reset_index(drop=True)
        require(np.array_equal(proxy["key"].to_numpy(), realized["key"].to_numpy()), f"paired keys differ for {proxy_id}")
        for horizon in HORIZONS:
            p_h = proxy.loc[proxy["horizon"].astype(int).eq(horizon)]
            r_h = realized.loc[realized["horizon"].astype(int).eq(horizon)]
            coverage_rows.append({"proxy_id": proxy_id, "horizon": horizon, "paired_n": len(p_h), "reference_n": len(r_h), "coverage": len(p_h) / max(len(r_h), 1), "status": "AVAILABLE"})
            p_metrics = all_metrics(p_h)
            r_metrics = all_metrics(r_h)
            for metric in METRIC_NAMES:
                paired_rows.append({
                    "proxy_id": proxy_id,
                    "horizon": horizon,
                    "metric": metric,
                    "proxy_value": p_metrics.get(metric, math.nan),
                    "realized_value": r_metrics.get(metric, math.nan),
                    "difference_proxy_minus_realized": p_metrics.get(metric, math.nan) - r_metrics.get(metric, math.nan),
                })
    coverage = pd.DataFrame(coverage_rows)
    paired = pd.DataFrame(paired_rows)
    write_csv(root / "metrics" / "coverage.csv", coverage)
    write_csv(root / "metrics" / "paired_proxy_minus_realized.csv", paired)
    write_csv(root / "metrics" / "horizon_degradation.csv", paired)

    frontier_rows = []
    for proxy_id in ["REALIZED_ENV", "E0_LAST_AVAILABLE", "E1_TRAILING3_MEAN"]:
        group = predictions.loc[predictions["proxy_id"].eq(proxy_id)]
        for horizon in HORIZONS:
            for frontier in ["previously_occupied", "previously_unoccupied"]:
                subset = group.loc[group["horizon"].astype(int).eq(horizon) & group["prediction_frontier_class"].astype(str).eq(frontier)]
                frontier_rows.append({"proxy_id": proxy_id, "horizon": horizon, "frontier_class": frontier, **all_metrics(subset)})
    frontier = pd.DataFrame(frontier_rows)
    write_csv(root / "metrics" / "frontier_metrics.csv", frontier)

    support_rows = []
    for proxy_id, group in predictions.groupby("proxy_id", sort=True):
        for horizon in HORIZONS:
            subset = group.loc[group["horizon"].astype(int).eq(horizon)]
            counts = subset["support_class"].value_counts()
            for support_class in ["SUPPORTED", "CAUTION", "EXTRAPOLATIVE"]:
                support_rows.append({"proxy_id": proxy_id, "horizon": horizon, "support_class": support_class, "n": int(counts.get(support_class, 0)), "proportion": float(counts.get(support_class, 0) / max(len(subset), 1))})
    support_metrics = pd.DataFrame(support_rows)
    write_csv(root / "metrics" / "support_metrics.csv", support_metrics)

    transition_rows = []
    for proxy_id in ["E0_LAST_AVAILABLE", "E1_TRAILING3_MEAN"]:
        proxy = predictions.loc[predictions["proxy_id"].eq(proxy_id)].sort_values(KEY_COLUMNS, kind="mergesort").reset_index(drop=True)
        require(np.array_equal(proxy["key"].to_numpy(), realized["key"].to_numpy()), f"support transition keys differ for {proxy_id}")
        transition = pd.crosstab(realized["support_class"], proxy["support_class"])
        for from_class in ["SUPPORTED", "CAUTION", "EXTRAPOLATIVE"]:
            for to_class in ["SUPPORTED", "CAUTION", "EXTRAPOLATIVE"]:
                transition_rows.append({"proxy_id": proxy_id, "from_support_class": from_class, "to_support_class": to_class, "n": int(transition.loc[from_class, to_class]) if from_class in transition.index and to_class in transition.columns else 0})
    write_csv(root / "metrics" / "support_transitions.csv", pd.DataFrame(transition_rows))

    spread_rows = []
    for proxy_id in ["E0_LAST_AVAILABLE", "E1_TRAILING3_MEAN"]:
        proxy = predictions.loc[predictions["proxy_id"].eq(proxy_id)].sort_values(KEY_COLUMNS, kind="mergesort").reset_index(drop=True)
        require(np.array_equal(proxy["key"].to_numpy(), realized["key"].to_numpy()), f"spread keys differ for {proxy_id}")
        work = pd.DataFrame({
            "horizon": realized["horizon"].to_numpy(),
            "support_class": realized["support_class"].to_numpy(),
            "frontier_class": realized["prediction_frontier_class"].to_numpy(),
            "abs_p_difference": np.abs(proxy["p_occurrence"].to_numpy() - realized["p_occurrence"].to_numpy()),
            "abs_expected_count_difference": np.abs(proxy["expected_count"].to_numpy() - realized["expected_count"].to_numpy()),
        })
        for (horizon, support_class, frontier_class), group in work.groupby(["horizon", "support_class", "frontier_class"], sort=True):
            spread_rows.append({"proxy_id": proxy_id, "horizon": horizon, "support_class": support_class, "frontier_class": frontier_class, "n": len(group), "mean_abs_p_difference": float(group["abs_p_difference"].mean()), "q95_abs_p_difference": float(group["abs_p_difference"].quantile(0.95)), "mean_abs_expected_count_difference": float(group["abs_expected_count_difference"].mean())})
    write_csv(root / "metrics" / "proxy_prediction_spread.csv", pd.DataFrame(spread_rows))

    env_errors = summarize_environment_errors(errors)
    write_csv(root / "metrics" / "environmental_proxy_error.csv", env_errors)
    family_error = env_errors.groupby(["proxy_id", "horizon", "family"], as_index=False).apply(lambda group: pd.Series({"n": int(group["n"].sum()), "mean_error": float(np.average(group["mean_error"], weights=group["n"])), "mae": float(np.average(group["mae"], weights=group["n"])), "rmse": float(np.sqrt(np.average(group["rmse"] ** 2, weights=group["n"]))) })).reset_index(drop=True)
    write_csv(root / "metrics" / "environmental_proxy_error_by_family.csv", family_error)

    bootstrap_rows = []
    for proxy_id in ["E0_LAST_AVAILABLE", "E1_TRAILING3_MEAN"]:
        proxy = predictions.loc[predictions["proxy_id"].eq(proxy_id)].sort_values(KEY_COLUMNS, kind="mergesort").reset_index(drop=True)
        for horizon in HORIZONS:
            for offset, metric in enumerate(["brier", "auprc", "full_expected_mae", "conditional_mae", "frontier_brier"]):
                bootstrap_rows.append({"proxy_id": proxy_id, **bootstrap_difference(proxy, realized, metric, horizon, BOOTSTRAP_SEED + offset + horizon * 100)})
    write_csv(root / "metrics" / "bootstrap_intervals.csv", pd.DataFrame(bootstrap_rows))

    decision_rows = []
    for proxy_id in ["E0_LAST_AVAILABLE", "E1_TRAILING3_MEAN", "E2_SEASONAL_EXPECTATION"]:
        if proxy_id not in set(predictions["proxy_id"]):
            decision_rows.append({"proxy_id": proxy_id, "classification": "NOT_EVALUABLE", "reason": "E2 requires two prior seasonal cycles; the validated archive supplies only one."})
            continue
        p = paired.loc[paired["proxy_id"].eq(proxy_id)]
        strict_failures = []
        bounded_failures = []
        for horizon in HORIZONS:
            def value(metric: str) -> float:
                row = p.loc[(p["horizon"] == horizon) & (p["metric"] == metric)]
                return float(row["difference_proxy_minus_realized"].iloc[0])
            realized_auprc = float(p.loc[(p["horizon"] == horizon) & (p["metric"] == "auprc"), "realized_value"].iloc[0])
            frontier_delta = float((frontier.loc[(frontier["proxy_id"] == proxy_id) & (frontier["horizon"] == horizon) & (frontier["frontier_class"] == "previously_unoccupied"), "brier"].iloc[0]) - (frontier.loc[(frontier["proxy_id"] == "REALIZED_ENV") & (frontier["horizon"] == horizon) & (frontier["frontier_class"] == "previously_unoccupied"), "brier"].iloc[0]))
            extra_real = float(support_metrics.loc[(support_metrics["proxy_id"] == "REALIZED_ENV") & (support_metrics["horizon"] == horizon) & (support_metrics["support_class"] == "EXTRAPOLATIVE"), "proportion"].iloc[0])
            extra_proxy = float(support_metrics.loc[(support_metrics["proxy_id"] == proxy_id) & (support_metrics["horizon"] == horizon) & (support_metrics["support_class"] == "EXTRAPOLATIVE"), "proportion"].iloc[0])
            checks = {
                "brier": (value("brier") <= 0.002, value("brier") <= 0.005),
                "auprc": (value("auprc") >= -0.05 * max(realized_auprc, 1e-12), value("auprc") >= -0.10 * max(realized_auprc, 1e-12)),
                "calibration_intercept": (abs(value("calibration_intercept")) <= 0.05, abs(value("calibration_intercept")) <= 0.10),
                "full_expected_mae": (value("full_expected_mae") <= 0.02, value("full_expected_mae") <= 0.05),
                "conditional_mae": (value("conditional_mae") <= 0.10, value("conditional_mae") <= 0.25),
                "frontier_brier": (frontier_delta <= 0.002, frontier_delta <= 0.005),
                "extrapolative_support": (extra_proxy - extra_real <= 0.05, extra_proxy - extra_real <= 0.10),
            }
            for name, (strict_ok, bounded_ok) in checks.items():
                if not strict_ok:
                    strict_failures.append(f"h{horizon}:{name}")
                if not bounded_ok:
                    bounded_failures.append(f"h{horizon}:{name}")
        if not strict_failures:
            classification = "OPERATIONALLY_ACCEPTABLE"
            reason = "Meets all prespecified strict degradation bounds at h=1,2,3."
        elif not bounded_failures:
            classification = "ACCEPTABLE_WITH_LIMITATIONS"
            reason = "Strict bounds are exceeded but all prespecified bounded limits hold at h=1,2,3."
        else:
            classification = "NOT_ACCEPTABLE"
            reason = "Exceeded prespecified bounded limits: " + ", ".join(bounded_failures)
        decision_rows.append({"proxy_id": proxy_id, "classification": classification, "reason": reason, "strict_failures": ";".join(strict_failures), "bounded_failures": ";".join(bounded_failures)})
    decisions = pd.DataFrame(decision_rows)
    write_csv(root / "metrics" / "proxy_decision.csv", decisions)
    selected = None
    for desired in ["OPERATIONALLY_ACCEPTABLE", "ACCEPTABLE_WITH_LIMITATIONS"]:
        candidates = decisions.loc[decisions["classification"].eq(desired)]
        if len(candidates):
            selected = str(candidates.iloc[0]["proxy_id"])
            selected_class = desired
            break
    if selected is None:
        availability = "RETROSPECTIVE_ONLY"
        decision_marker = "P5A_ENVIRONMENTAL_PROXY_NOT_SUPPORTED"
    elif selected_class == "OPERATIONALLY_ACCEPTABLE":
        availability = "PROSPECTIVE_READY_WITH_PROXY_LIMITATIONS"
        decision_marker = "P5A_ENVIRONMENTAL_PROXY_SUPPORTED"
    else:
        availability = "PROSPECTIVE_READY_WITH_PROXY_LIMITATIONS"
        decision_marker = "P5A_ENVIRONMENTAL_PROXY_SUPPORTED_WITH_LIMITATIONS"
    write_json(root / "metrics" / "availability_reclassification.json", {
        "previous_classification": "RETROSPECTIVE_ONLY",
        "classification": availability,
        "selected_proxy_id": selected,
        "selected_proxy_classification": selected_class if selected else None,
        "reason": "No accepted issue-time proxy" if selected is None else "Selected by prespecified simplicity-first rule",
        "environmental_source_requirement": "source observation week <= T-1 and source timestamp <= issue timestamp",
        "p5_non_environmental_limitations_preserved": True,
    })
    metadata = json.loads((root / "manifests" / "run_metadata.json").read_text(encoding="utf-8"))
    metadata.update({
        "status": "COMPLETED",
        "runtime_seconds": float(sum(row.get("runtime_seconds", 0.0) for row in statuses)),
        "aggregate_rows": int(len(predictions)),
        "evaluated_proxy_ids": sorted(predictions["proxy_id"].unique().tolist()),
        "failed_origins": [row["origin_week"] for row in statuses if row.get("status") != "COMPLETED"],
        "selected_proxy_id": selected,
        "availability_reclassification": availability,
        "decision": decision_marker,
        "production_model_modified": False,
        "p2_reference_unchanged": True,
    })
    write_json(root / "manifests" / "run_metadata.json", metadata)
    write_json(root / "metrics" / "decision.json", {
        "decision": decision_marker,
        "marker": decision_marker,
        "selected_proxy_id": selected,
        "availability_reclassification": availability,
        "proxy_decisions": decisions.to_dict(orient="records"),
        "p2_reference_unchanged": True,
        "production_model_modified": False,
    })
    print(json.dumps({"status": "AGGREGATED", "decision": decision_marker, "selected_proxy_id": selected, "rows": len(predictions)}, indent=2))
    return metadata


def all_mode(args: argparse.Namespace) -> None:
    if not (args.output_root / "manifests" / "origin_manifest.csv").exists():
        prepare(args)
    context = load_context(args)
    origins = pd.read_csv(args.output_root / "manifests" / "origin_manifest.csv")["origin_week"].astype(str).tolist()
    statuses = []
    for origin in origins:
        status = origin_run(args, context, origin)
        statuses.append(status)
        update_ledger(args.output_root, statuses)
        print(json.dumps({"origin_week": origin, "status": status.get("status"), "rows": status.get("rows")}, sort_keys=True))
    aggregate(args, context)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["prepare", "all"], required=True)
    parser.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--model-output", type=Path, required=True)
    parser.add_argument("--p2-output-root", type=Path, required=True)
    parser.add_argument("--p4-root", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.repository_root = args.repository_root.resolve()
    args.output_root = args.output_root.resolve()
    args.model_output = args.model_output.resolve()
    args.p2_output_root = args.p2_output_root.resolve()
    args.p4_root = args.p4_root.resolve()
    if args.mode == "prepare":
        prepare(args)
    else:
        all_mode(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
