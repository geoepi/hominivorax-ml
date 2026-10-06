#!/usr/bin/env python3
"""Run the frozen STRUCTURED A3 historical evaluation.

The script fits A3 once on 2025-W01--2026-W16, applies development-only
preprocessing to later weeks, and scores the historical exposed holdout
2026-W17--2026-W29. It also fits the paired frozen A0 reference for descriptive
comparison. No evaluation response is used for fitting, scaling, selection, or
calibration. Later response dates are audited but are not called prospective
unless both outcome and complete predictor provenance qualify.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import subprocess
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SCRIPT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = SCRIPT_ROOT.parent
sys.path.insert(0, str(REPO_ROOT / "analysis" / "predictor_augmentation" / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "python"))

from run_predictor_augmentation import (  # noqa: E402
    ADDED_FEATURES,
    BASE_FEATURES,
    CALENDAR_FEATURES,
    FIXED_THETA,
    PENALTY,
    fit_fixed_theta,
    predict,
    standardize,
)
from task2c_metrics import evaluate_predictions  # noqa: E402


NODE_COUNT = 10_037
DEVELOPMENT_WEEKS = 68
EXPECTED_TOTAL_WEEKS = 81
HOLDOUT_START = 68
MODEL_NAME = "STRUCTURED_A3"
MODEL_FEATURES = BASE_FEATURES + ADDED_FEATURES
HISTORY_FEATURES = [
    "distance_to_any_prior_positive_log1p",
    "distance_to_prev4_positive_log1p",
    "weeks_since_detection_within_50km_log1p",
    "any_prior_positive_available",
    "prev4_positive_available",
    "detection_within_50km_ever_available",
]
FRONT_COLUMNS = ["week_index", "model_node_id", *HISTORY_FEATURES, "history_cutoff_week"]
TRANSFORMATIONS = {
    "road_density": "log1p",
    "night_illumination": "log1p",
    "clay_0_15": "identity",
    "water_difference_wv0033_minus_wv0010_0_15": "identity",
}
LOWER_IS_BETTER = {"exact_joint_hurdle_nll", "joint_hurdle_nll", "brier", "calibration_distance", "count_mae", "count_rmse"}


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def jsonable(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(jsonable(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "-c", f"safe.directory={REPO_ROOT.as_posix()}", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            text=True,
        ).strip()
    except Exception:
        return "unknown"


def parse_iso_week(value: str) -> tuple[int, int]:
    year, week = str(value).split("-W")
    return int(year), int(week)


def iso_week_sort_key(value: str) -> tuple[int, int]:
    return parse_iso_week(value)


def iso_week_date(value: str) -> date:
    year, week = parse_iso_week(value)
    return date.fromisocalendar(year, week, 1)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def assert_manifest_unchanged(output: Path) -> str:
    manifest_path = output / "frozen_a3_evaluation_manifest.json"
    checksum_path = output / "frozen_a3_evaluation_manifest.json.sha256"
    if not manifest_path.exists() or not checksum_path.exists():
        raise RuntimeError("STOP: immutable frozen A3 evaluation manifest/checksum is missing")
    actual = sha256_file(manifest_path)
    expected = checksum_path.read_text(encoding="utf-8").split()[0]
    if actual != expected:
        raise RuntimeError("STOP: frozen A3 evaluation manifest checksum mismatch")
    manifest = read_json(manifest_path)
    if manifest.get("manifest_status") != "FROZEN_BEFORE_EVALUATION_OUTCOMES":
        raise RuntimeError("STOP: manifest was not frozen before evaluation outcomes")
    if manifest["model"]["predictor_count"] != 34:
        raise RuntimeError("STOP: frozen A3 predictor count changed")
    if float(manifest["model"]["penalty"]) != PENALTY or float(manifest["model"]["theta"]) != FIXED_THETA:
        raise RuntimeError("STOP: frozen A3 penalty/theta changed")
    return actual


def validate_node_ids(frame: pd.DataFrame, column: str = "model_node_id") -> pd.DataFrame:
    if column not in frame.columns:
        raise RuntimeError(f"node table lacks {column}")
    frame = frame.sort_values(column).reset_index(drop=True)
    ids = pd.to_numeric(frame[column], errors="raise").to_numpy(np.int64)
    if len(ids) != NODE_COUNT or not np.array_equal(ids, np.arange(NODE_COUNT)):
        raise RuntimeError("STOP: canonical node IDs are not exactly 0 through 10036")
    frame[column] = ids
    return frame


def load_bundle(args: argparse.Namespace) -> dict[str, Any]:
    model_output = args.model_output
    raw = model_output / "raw"
    if not raw.exists():
        raise RuntimeError(f"STOP: model output is missing: {model_output}")

    manifest_path = model_output / "manifests" / "revised_production_manifest.json"
    production_manifest = read_json(manifest_path)
    dynamic = np.asarray(np.load(raw / "dynamic_features.npy", mmap_mode="r"), dtype=np.float64)
    static = np.asarray(np.load(raw / "static_features.npy", mmap_mode="r"), dtype=np.float64)
    counts = np.asarray(np.load(raw / "targets_count.npy", mmap_mode="r"), dtype=np.int64)
    presence = np.asarray(np.load(raw / "targets_presence.npy", mmap_mode="r"), dtype=np.int8)
    weeks = pd.read_parquet(raw / "weeks.parquet")
    calendar = pd.read_parquet(raw / "calendar_features.parquet")[list(CALENDAR_FEATURES)].to_numpy(np.float64)
    nodes = validate_node_ids(pd.read_parquet(raw / "nodes.parquet"))

    expected_shapes = {
        "dynamic": (EXPECTED_TOTAL_WEEKS, NODE_COUNT, 12),
        "static": (NODE_COUNT, 10),
        "counts": (EXPECTED_TOTAL_WEEKS, NODE_COUNT),
        "presence": (EXPECTED_TOTAL_WEEKS, NODE_COUNT),
        "calendar": (EXPECTED_TOTAL_WEEKS, 2),
    }
    actual_shapes = {
        "dynamic": tuple(dynamic.shape),
        "static": tuple(static.shape),
        "counts": tuple(counts.shape),
        "presence": tuple(presence.shape),
        "calendar": tuple(calendar.shape),
    }
    if actual_shapes != expected_shapes:
        raise RuntimeError(f"STOP: frozen production shape contract failed: {actual_shapes}")
    if not np.array_equal(presence, (counts > 0).astype(np.int8)):
        raise RuntimeError("STOP: response presence is not count > 0")
    if np.any(counts < 0) or not np.isfinite(dynamic).all() or not np.isfinite(static).all():
        raise RuntimeError("STOP: response or predictor arrays contain invalid values")

    week_labels = weeks["iso_week"].astype(str).tolist()
    if week_labels[0] != "2025-W01" or week_labels[DEVELOPMENT_WEEKS - 1] != "2026-W16" or week_labels[-1] != "2026-W29":
        raise RuntimeError(f"STOP: unexpected frozen response horizon: {week_labels[0]}--{week_labels[-1]}")
    if len(week_labels) != EXPECTED_TOTAL_WEEKS:
        raise RuntimeError("STOP: frozen response week count changed")

    front = pd.read_parquet(args.front_features, columns=FRONT_COLUMNS)
    front = front.sort_values(["week_index", "model_node_id"]).reset_index(drop=True)
    if len(front) != EXPECTED_TOTAL_WEEKS * NODE_COUNT:
        raise RuntimeError("STOP: front features do not cover all frozen response weeks")
    expected_ids = np.tile(np.arange(NODE_COUNT), EXPECTED_TOTAL_WEEKS)
    if not np.array_equal(front["model_node_id"].to_numpy(np.int64), expected_ids):
        raise RuntimeError("STOP: front feature node ordering is not canonical")
    if not np.array_equal(front["week_index"].to_numpy(np.int64), np.repeat(np.arange(EXPECTED_TOTAL_WEEKS), NODE_COUNT)):
        raise RuntimeError("STOP: front feature week ordering is not canonical")
    if not np.isfinite(front[HISTORY_FEATURES].to_numpy(np.float64)).all():
        raise RuntimeError("STOP: frozen front features contain non-finite values")

    anthropogenic = validate_node_ids(pd.read_parquet(args.anthropogenic_features))
    soil = validate_node_ids(pd.read_parquet(args.soil_features))
    anthro_cols = ["model_node_id", "road_density", "night_illumination", "road_coverage_fraction", "night_illumination_coverage_fraction"]
    if not set(anthro_cols).issubset(anthropogenic.columns):
        raise RuntimeError("STOP: anthropogenic A3 artifact lacks required columns")
    soil_cols = ["model_node_id", "clay_0_15__mean", "water_difference_wv0033_minus_wv0010_0_15__mean"]
    if not set(soil_cols).issubset(soil.columns):
        raise RuntimeError("STOP: soil A3 artifact lacks required columns")
    static_join = (
        anthropogenic[anthro_cols]
        .merge(soil[soil_cols], on="model_node_id", how="inner", validate="one_to_one")
        .sort_values("model_node_id")
    )
    if len(static_join) != NODE_COUNT or not np.array_equal(static_join["model_node_id"].to_numpy(np.int64), np.arange(NODE_COUNT)):
        raise RuntimeError("STOP: static A3 feature join changed canonical nodes")
    for column in anthro_cols[1:] + soil_cols[1:]:
        if not np.isfinite(pd.to_numeric(static_join[column], errors="coerce").to_numpy(np.float64)).all():
            raise RuntimeError(f"STOP: static A3 feature is missing/non-finite: {column}")
    for column in ["road_coverage_fraction", "night_illumination_coverage_fraction"]:
        coverage = static_join[column].to_numpy(np.float64)
        if np.any(coverage <= 0) or np.any(coverage > 1 + 1e-8):
            raise RuntimeError(f"STOP: invalid static coverage: {column}")

    density = np.log1p(static[:, :5])
    indicators = static[:, 5:]
    front_values = front[HISTORY_FEATURES].to_numpy(np.float64).reshape(EXPECTED_TOTAL_WEEKS, NODE_COUNT, len(HISTORY_FEATURES))
    base = np.concatenate(
        [
            dynamic,
            np.broadcast_to(density[None, :, :], (EXPECTED_TOTAL_WEEKS, NODE_COUNT, 5)),
            np.broadcast_to(indicators[None, :, :], (EXPECTED_TOTAL_WEEKS, NODE_COUNT, 5)),
            np.broadcast_to(calendar[:, None, :], (EXPECTED_TOTAL_WEEKS, NODE_COUNT, 2)),
            front_values,
        ],
        axis=2,
    )
    if base.shape != (EXPECTED_TOTAL_WEEKS, NODE_COUNT, len(BASE_FEATURES)) or not np.isfinite(base).all():
        raise RuntimeError("STOP: frozen 30-feature base array is invalid")

    added = static_join[["road_density", "night_illumination", "clay_0_15__mean", "water_difference_wv0033_minus_wv0010_0_15__mean"]].to_numpy(np.float64)
    added[:, 0] = np.log1p(added[:, 0])
    added[:, 1] = np.log1p(added[:, 1])
    if not np.isfinite(added).all():
        raise RuntimeError("STOP: transformed A3 static additions are non-finite")

    return {
        "model_output": model_output,
        "raw": raw,
        "production_manifest": production_manifest,
        "dynamic": dynamic,
        "static": static,
        "counts": counts,
        "presence": presence,
        "weeks": weeks,
        "week_labels": week_labels,
        "nodes": nodes,
        "front": front,
        "base": base,
        "added": added,
        "anthropogenic": anthropogenic,
        "soil": soil,
    }


def audit_static_checksums(bundle: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    feature_manifest = read_json(REPO_ROOT / "analysis" / "structured_a3_final_comparison" / "results" / "a3_feature_manifest.json")
    augmentation = feature_manifest["augmentation_manifest"]
    expected = {
        "anthropogenic_static_features": augmentation["anthropogenic_source_sha256"],
        "soil_static_features": feature_manifest["soil_artifact_sha256"],
    }
    actual = {
        "anthropogenic_static_features": sha256_file(args.anthropogenic_features),
        "soil_static_features": sha256_file(args.soil_features),
    }
    for name in expected:
        if expected[name] != actual[name]:
            raise RuntimeError(f"STOP: frozen static checksum mismatch for {name}: {actual[name]} != {expected[name]}")
    return {
        "feature_manifest": str(REPO_ROOT / "analysis" / "structured_a3_final_comparison" / "results" / "a3_feature_manifest.json"),
        "feature_manifest_sha256": sha256_file(REPO_ROOT / "analysis" / "structured_a3_final_comparison" / "results" / "a3_feature_manifest.json"),
        "expected_sha256": expected,
        "actual_sha256": actual,
        "status": "PASS",
    }


def audit_history(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    front = bundle["front"]
    labels = bundle["week_labels"]
    rows: list[dict[str, Any]] = []
    current_ord = {index: iso_week_sort_key(label) for index, label in enumerate(labels)}
    cutoff_values = front["history_cutoff_week"].astype(str)
    for feature in HISTORY_FEATURES:
        invalid = 0
        missing_cutoff = 0
        for week_index, group in front.groupby("week_index", sort=True):
            current = current_ord[int(week_index)]
            cutoff = group["history_cutoff_week"]
            missing_cutoff += int(cutoff.isna().sum())
            for value in cutoff.dropna().astype(str):
                try:
                    if iso_week_sort_key(value) >= current:
                        invalid += 1
                except Exception:
                    invalid += 1
        rows.append({
            "feature": feature,
            "causal_definition": "only observations from weeks < t",
            "allowed_observation_times": "weeks < t",
            "same_week_observations_used": int(invalid),
            "future_observations_used": int(invalid),
            "missing_history_cutoff_rows": int(missing_cutoff),
            "availability_verified": bool(invalid == 0 and missing_cutoff == 0),
            "status": "PASS" if invalid == 0 and missing_cutoff == 0 else "FAIL",
            "checked_rows": int(len(front)),
            "history_cutoff_source": "causal_front_features.parquet:history_cutoff_week",
        })
    if any(row["status"] != "PASS" for row in rows):
        raise RuntimeError("STOP: causal history leakage audit failed")
    return rows


def source_metadata(bundle: dict[str, Any]) -> dict[str, Any]:
    source_info = bundle["production_manifest"].get("observation_source", {})
    source_path = Path(source_info.get("path", ""))
    if not source_path.exists():
        raise RuntimeError(f"STOP: authoritative observation source is missing: {source_path}")
    stat = source_path.stat()
    source_dates = pd.read_csv(source_path, usecols=["date"])["date"]
    dates = pd.to_datetime(source_dates, errors="coerce")
    if dates.isna().any():
        raise RuntimeError("STOP: observation source contains invalid dates")
    latest = dates.max().date()
    latest_iso = f"{latest.isocalendar().year}-W{latest.isocalendar().week:02d}"
    return {
        "source_path": str(source_path),
        "source_sha256": sha256_file(source_path),
        "source_file_mtime_utc": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="seconds"),
        "source_row_count": int(len(source_dates)),
        "manifest_row_count": source_info.get("row_count"),
        "manifest_old_row_count": source_info.get("old_row_count"),
        "minimum_observation_date": str(dates.min().date()),
        "latest_observation_date": str(latest),
        "latest_observation_iso_week": latest_iso,
        "complete_response_week_in_model_bundle": bundle["week_labels"][-1],
        "latest_complete_predictor_week": bundle["week_labels"][-1],
        "prospective_endpoint": None,
        "prospective_status": "NO ELIGIBLE PROSPECTIVE PERIOD",
        "response_values_loaded": True,
        "refresh_performed": False,
        "duplicate_handling": "reused authoritative production dataset; no refresh or deduplication mutation performed",
        "source_snapshot_pre_freeze": True,
        "source_snapshot_note": "source file mtime precedes frozen A3 development comparison; later source dates cannot support an untouched claim",
    }


def fit_and_predict(raw: np.ndarray, counts: np.ndarray, names: list[str]) -> dict[str, Any]:
    train_raw = raw[:DEVELOPMENT_WEEKS].reshape(-1, len(names)).astype(np.float64, copy=False)
    all_raw = raw.reshape(-1, len(names)).astype(np.float64, copy=False)
    x_train, x_all, scaling = standardize(train_raw, all_raw, names)
    y_train = counts[:DEVELOPMENT_WEEKS].reshape(-1)
    state = fit_fixed_theta(x_train, y_train)
    if not state["fit_info"].get("occurrence_success") or not state["fit_info"].get("count_success"):
        raise RuntimeError(f"STOP: fixed A3 fit did not converge: {state['fit_info']}")
    p, conditional, mu = predict(state, x_all)
    shape = (EXPECTED_TOTAL_WEEKS, NODE_COUNT)
    return {
        "state": state,
        "scaling": scaling,
        "probability": p.reshape(shape),
        "conditional": conditional.reshape(shape),
        "mu": mu.reshape(shape),
        "training_prevalence": float(np.mean(y_train > 0)),
    }


def save_model(output: Path, fit: dict[str, Any], model_name: str, feature_names: list[str]) -> None:
    state = fit["state"]
    payload = {
        "status": "FROZEN_FINAL_DEVELOPMENT_FIT",
        "model": model_name,
        "feature_count": len(feature_names),
        "feature_order": feature_names,
        "penalty": PENALTY,
        "theta": FIXED_THETA,
        "theta_fixed": True,
        "objective": "exact_joint_hurdle_nll",
        "training_period": {"start": "2025-W01", "end": "2026-W16", "week_count": DEVELOPMENT_WEEKS},
        "domain_nodes": NODE_COUNT,
        "occurrence_coefficients": state["occurrence_beta"],
        "count_coefficients": state["count_beta"],
        "preprocessing": fit["scaling"],
        "fit_info": state["fit_info"],
        "training_prevalence": fit["training_prevalence"],
        "software_sha": git_sha(),
        "evaluation_responses_used_for_fit": False,
    }
    write_json(output / "final_a3_model.json", payload)
    coefficient_rows = []
    for component, values in [("occurrence", state["occurrence_beta"]), ("positive_count", state["count_beta"])]:
        for feature, value in zip(["intercept", *feature_names], values):
            coefficient_rows.append({"component": component, "feature": feature, "coefficient_standardized": float(value)})
    pd.DataFrame(coefficient_rows).to_csv(output / "final_a3_coefficients.csv", index=False)
    scaling_rows = []
    for index, feature in enumerate(feature_names):
        scaling_rows.append({
            "feature": feature,
            "training_mean": float(fit["scaling"]["training_mean"][index]),
            "training_sd": float(fit["scaling"]["training_sd"][index]),
            "scaled": index in fit["scaling"]["scaled_feature_indices"],
        })
    pd.DataFrame(scaling_rows).to_csv(output / "final_a3_scaling_parameters.csv", index=False)


def region_masks(nodes: pd.DataFrame) -> dict[str, np.ndarray]:
    column = "country_or_domain_region"
    values = nodes[column].astype(str).str.lower()
    mexico = values.str.contains("mexico").to_numpy(bool)
    united_states = values.str.contains("united states|usa|u\\.s\\.", regex=True).to_numpy(bool)
    if not mexico.any() or not united_states.any():
        raise RuntimeError(f"STOP: established country assignment lacks Mexico/United States: {sorted(values.unique())}")
    return {"full_revised_domain": np.ones(NODE_COUNT, dtype=bool), "Mexico": mexico, "United States": united_states}


def metric_row(
    counts: np.ndarray,
    probability: np.ndarray,
    conditional: np.ndarray,
    mu: np.ndarray,
    mask: np.ndarray,
    model: str,
    geography: str,
    period: str,
    training_prevalence: float,
) -> dict[str, Any]:
    y = counts[mask]
    positives = y > 0
    metrics = evaluate_predictions(
        y,
        probability[mask],
        conditional[mask],
        underlying_mu=mu[mask],
        theta=FIXED_THETA,
        training_prevalence=training_prevalence,
        count_score_family="zt_nb_fixed_theta",
    )
    row = {
        "status": "COMPLETED",
        "evaluation_class": "HISTORICAL EXPOSED HOLDOUT",
        "period": period,
        "model": model,
        "geography": geography,
        "node_weeks": int(y.size),
        "positive_node_weeks": int(positives.sum()),
        "prevalence": float(positives.mean()),
        "unique_positive_nodes": int(np.unique(np.where(mask & (counts > 0))[1]).size),
        "recorded_detections": int(y.sum()),
        "pr_auc": metrics.get("pr_auc"),
        "roc_auc": metrics.get("roc_auc"),
        "brier": metrics.get("brier"),
        "brier_skill": metrics.get("brier_skill"),
        "calibration_intercept": metrics.get("calibration_intercept"),
        "calibration_slope": metrics.get("calibration_slope"),
        "exact_joint_hurdle_nll": metrics.get("joint_hurdle_nll"),
        "observed_positive_count_mean": metrics.get("positive_mean_observed"),
        "predicted_conditional_mean": metrics.get("positive_mean_predicted"),
        "conditional_mean_bias": None if metrics.get("positive_mean_predicted") is None else float(metrics["positive_mean_predicted"] - metrics["positive_mean_observed"]),
        "count_mae": metrics.get("positive_count_mae"),
        "count_rmse": metrics.get("positive_count_rmse"),
        "mean_predicted_probability": metrics.get("mean_predicted_probability"),
        "observed_prevalence": metrics.get("observed_prevalence"),
        "reliability_bins": json.dumps(jsonable(metrics.get("reliability", [])), sort_keys=True),
    }
    row["calibration_distance"] = None if row["calibration_intercept"] is None or row["calibration_slope"] is None else float(math.sqrt(row["calibration_intercept"] ** 2 + (row["calibration_slope"] - 1.0) ** 2))
    return row


def weekly_rows(bundle: dict[str, Any], fit: dict[str, Any], region_mask: np.ndarray, model: str) -> list[dict[str, Any]]:
    rows = []
    training_prevalence = fit["training_prevalence"]
    for index in range(HOLDOUT_START, EXPECTED_TOTAL_WEEKS):
        mask = np.ones((1, NODE_COUNT), dtype=bool) & region_mask[None, :]
        row = metric_row(
            bundle["counts"][index:index + 1],
            fit["probability"][index:index + 1],
            fit["conditional"][index:index + 1],
            fit["mu"][index:index + 1],
            mask,
            model,
            "full_revised_domain",
            bundle["week_labels"][index],
            training_prevalence,
        )
        row.update({
            "week": bundle["week_labels"][index],
            "node_weeks": int(mask.sum()),
            "positives": row["positive_node_weeks"],
            "observed_prevalence": row["prevalence"],
            "mean_predicted_probability": row["mean_predicted_probability"],
            "joint_NLL": row["exact_joint_hurdle_nll"],
            "count_MAE": row["count_mae"],
            "count_RMSE": row["count_rmse"],
            "evaluation_class": "HISTORICAL EXPOSED HOLDOUT",
        })
        rows.append(row)
    return rows


def us_transfer_row(bundle: dict[str, Any], fit: dict[str, Any], us_mask: np.ndarray) -> dict[str, Any]:
    eval_counts = bundle["counts"][HOLDOUT_START:]
    eval_p = fit["probability"][HOLDOUT_START:]
    positive = (eval_counts > 0) & us_mask[None, :]
    positive_indices = np.where(positive)
    first_week = bundle["week_labels"][HOLDOUT_START + int(positive_indices[0].min())] if len(positive_indices[0]) else None
    percentiles = []
    for week_index in range(eval_p.shape[0]):
        values = eval_p[week_index, us_mask]
        if values.size == 0:
            continue
        ranks = pd.Series(values).rank(method="average", pct=True).to_numpy() * 100.0
        positive_nodes = np.where(positive[week_index, us_mask])[0]
        percentiles.extend(ranks[positive_nodes].tolist())
    before_first = eval_p[: int(positive_indices[0].min())] if len(positive_indices[0]) else eval_p
    pre_max = float(before_first[:, us_mask].max()) if before_first.size else None
    positive_probabilities = eval_p[positive]
    return {
        "status": "COMPLETED",
        "evaluation_class": "HISTORICAL EXPOSED HOLDOUT",
        "period": "2026-W17--2026-W29",
        "model": MODEL_NAME,
        "positive_node_weeks": int(positive.sum()),
        "unique_positive_nodes": int(np.unique(positive_indices[1]).size) if len(positive_indices[1]) else 0,
        "first_positive_evaluation_week": first_week,
        "median_positive_case_probability": float(np.median(positive_probabilities)) if positive_probabilities.size else None,
        "median_positive_case_percentile": float(np.median(percentiles)) if percentiles else None,
        "proportion_positive_cases_ge_75th": float(np.mean(np.asarray(percentiles) >= 75.0)) if percentiles else None,
        "proportion_positive_cases_ge_90th": float(np.mean(np.asarray(percentiles) >= 90.0)) if percentiles else None,
        "maximum_pre_detection_us_probability": pre_max,
    }


def make_comparison(a0: dict[str, Any], a3: dict[str, Any]) -> pd.DataFrame:
    rows = []
    metrics = ["exact_joint_hurdle_nll", "pr_auc", "roc_auc", "brier", "brier_skill", "calibration_intercept", "calibration_slope", "count_mae", "count_rmse", "conditional_mean_bias"]
    for metric in metrics:
        old = a0.get(metric)
        new = a3.get(metric)
        if old is None or new is None:
            improvement = None
        elif metric in LOWER_IS_BETTER:
            improvement = float(old - new)
        else:
            improvement = float(new - old)
        rows.append({"status": "COMPLETED", "evaluation_class": "HISTORICAL EXPOSED HOLDOUT", "period": "2026-W17--2026-W29", "geography": "full_revised_domain", "metric": metric, "a0": old, "a3": new, "a3_improvement": improvement})
    return pd.DataFrame(rows)


def classify_historical(row: dict[str, Any]) -> str:
    required = [row.get("exact_joint_hurdle_nll"), row.get("brier_skill"), row.get("pr_auc"), row.get("count_mae"), row.get("count_rmse")]
    if any(value is None or not np.isfinite(float(value)) for value in required):
        return "NOT TESTED"
    slope = row.get("calibration_slope")
    intercept = row.get("calibration_intercept")
    if slope is None or intercept is None:
        return "PARTIAL"
    if float(row["brier_skill"]) > 0 and float(row["pr_auc"]) >= float(row["prevalence"]) and 0.5 <= float(slope) <= 1.5 and abs(float(intercept)) <= 1.0:
        return "SUPPORTED"
    if float(row["brier_skill"]) > -0.05 and float(row["pr_auc"]) >= float(row["prevalence"]) * 0.75:
        return "PARTIAL"
    return "WEAK"


def write_report(output: Path, bundle: dict[str, Any], source: dict[str, Any], a3_full: dict[str, Any], a0_full: dict[str, Any], historical_classification: str, figure_status: str) -> None:
    comparison = make_comparison(a0_full, a3_full)
    lines = [
        "# Frozen STRUCTURED A3 evaluation report",
        "",
        "## 1. Objective",
        "",
        "Evaluate the frozen STRUCTURED A3 model outside F1--F4 without model changes.",
        "",
        "## 2. Frozen model",
        "",
        "- 34 predictors; penalty `0.01`; fixed theta `0.7018903965556372`.",
        "- Objective `exact_joint_hurdle_nll`; revised domain 10,037 nodes.",
        "- One final fit on 2025-W01--2026-W16; no evaluation responses used for fitting or preprocessing.",
        "",
        "## 3. Evaluation provenance",
        "",
        "- 2026-W17--2026-W29: `HISTORICAL EXPOSED HOLDOUT` (previously evaluated/reported project horizon).",
        "- Later response dates occur in a source snapshot before the freeze and lack complete A3 predictor support; they are not eligible for an independent prospective claim.",
        "",
        "## 4. Data availability",
        "",
        f"- Latest observation date in authoritative source: `{source['latest_observation_date']}` ({source['latest_observation_iso_week']}).",
        f"- Latest complete response/predictor week in the frozen model bundle: `{source['complete_response_week_in_model_bundle']}`.",
        f"- Historical evaluation endpoint: `2026-W29`; prospective endpoint: `NONE`.",
        "",
        "## 5. Leakage and preprocessing audits",
        "",
        "Causal history cutoffs were verified to precede each forecast week. Scaling was fit on the 68 development weeks only; evaluation-period means/SDs were not used.",
        "",
        "## 6. Historical holdout results",
        "",
        "| Geography | Node-weeks | Positives | Prevalence | NLL | PR-AUC | BSS | Calibration |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
        f"| Full domain | {a3_full['node_weeks']} | {a3_full['positive_node_weeks']} | {a3_full['prevalence']:.6f} | {a3_full['exact_joint_hurdle_nll']:.6f} | {a3_full['pr_auc']:.6f} | {a3_full['brier_skill']:.6f} | {a3_full['calibration_intercept']:.4f} / {a3_full['calibration_slope']:.4f} |",
        "",
        "## 7. Prospective results",
        "",
        "NO INDEPENDENT PROSPECTIVE EVALUATION AVAILABLE.",
        "",
        "## 8. A0 versus A3 comparison",
        "",
        f"A3 historical exposed-holdout joint NLL improvement over A0: `{comparison.loc[comparison.metric == 'exact_joint_hurdle_nll', 'a3_improvement'].iloc[0]:.6f}`; PR-AUC improvement: `{comparison.loc[comparison.metric == 'pr_auc', 'a3_improvement'].iloc[0]:.6f}`; Brier-skill improvement: `{comparison.loc[comparison.metric == 'brier_skill', 'a3_improvement'].iloc[0]:.6f}`.",
        "",
        "## 9. U.S. transfer performance",
        "",
        "See `us_transfer_metrics.csv`; sparse-U.S. counts are reported without stronger aggregation claims.",
        "",
        "## 10. Calibration",
        "",
        f"A3 calibration intercept/slope were `{a3_full['calibration_intercept']:.6f}` / `{a3_full['calibration_slope']:.6f}`.",
        "",
        "## 11. Count performance",
        "",
        f"Observed positive-count mean was `{a3_full['observed_positive_count_mean']:.6f}` versus predicted conditional mean `{a3_full['predicted_conditional_mean']:.6f}`, bias `{a3_full['conditional_mean_bias']:.6f}`.",
        "",
        "## 12. Generalization classification",
        "",
        f"Historical: `{historical_classification}`.",
        "Prospective: `PROSPECTIVE GENERALIZATION NOT YET TESTED`.",
        "",
        "## 13. Final interpretation",
        "",
        "The historical result describes generalization beyond F1--F4 but cannot be called independent/prospective. No genuinely untouched later period with complete A3 predictors was available.",
        "",
        "## Boundary checks",
        "",
        "```text",
        "predictor specification changed: NO",
        "penalty changed: NO",
        "theta changed/re-estimated: NO",
        "model recalibrated: NO",
        "feature selection reopened: NO",
        "neural models fitted: NO",
        "graph models fitted: NO",
        "evaluation outcomes used for training: NO",
        "evaluation outcomes used to alter model: NO",
        "main merged: NO",
        "```",
        "",
        "## Production-readiness decision",
        "",
        "`A3 REQUIRES FURTHER EXTERNAL/PROSPECTIVE VALIDATION`",
        "",
        f"Figure generation status: `{figure_status}`.",
    ]
    (output / "structured_a3_evaluation_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> None:
    started = time.time()
    output = args.output_root
    output.mkdir(parents=True, exist_ok=True)
    manifest_sha = assert_manifest_unchanged(output)
    bundle = load_bundle(args)
    static_audit = audit_static_checksums(bundle, args)
    history_audit = audit_history(bundle)
    source = source_metadata(bundle)

    a3_raw = np.concatenate([bundle["base"], np.broadcast_to(bundle["added"][None, :, :], (EXPECTED_TOTAL_WEEKS, NODE_COUNT, len(ADDED_FEATURES)))], axis=2)
    a0_fit = fit_and_predict(bundle["base"], bundle["counts"], BASE_FEATURES)
    a3_fit = fit_and_predict(a3_raw, bundle["counts"], MODEL_FEATURES)
    save_model(output, a3_fit, MODEL_NAME, MODEL_FEATURES)

    eval_counts = bundle["counts"][HOLDOUT_START:]
    regions = region_masks(bundle["nodes"])
    period = f"{bundle['week_labels'][HOLDOUT_START]}--{bundle['week_labels'][-1]}"
    geographic_rows = []
    fits = {"A0": a0_fit, "A3": a3_fit}
    for model, fit in fits.items():
        for geography, node_mask in regions.items():
            mask = np.ones((EXPECTED_TOTAL_WEEKS - HOLDOUT_START, NODE_COUNT), dtype=bool) & node_mask[None, :]
            geographic_rows.append(metric_row(eval_counts, fit["probability"][HOLDOUT_START:], fit["conditional"][HOLDOUT_START:], fit["mu"][HOLDOUT_START:], mask[HOLDOUT_START - HOLDOUT_START:], model, geography, period, fit["training_prevalence"]))
    geographic = pd.DataFrame(geographic_rows)
    a3_full = next(row for row in geographic_rows if row["model"] == "A3" and row["geography"] == "full_revised_domain")
    a0_full = next(row for row in geographic_rows if row["model"] == "A0" and row["geography"] == "full_revised_domain")
    a3_geo = geographic[geographic["model"] == "A3"].copy()
    geographic.to_csv(output / "geographic_metrics.csv", index=False)
    pd.DataFrame([a3_full]).to_csv(output / "overall_metrics.csv", index=False)

    weekly = pd.DataFrame(weekly_rows(bundle, a3_fit, regions["full_revised_domain"], "A3"))
    weekly.to_csv(output / "weekly_metrics.csv", index=False)
    count_rows = []
    calibration_rows = []
    for row in [a3_full, *a3_geo.to_dict(orient="records")]:
        count_rows.append({key: row.get(key) for key in ["status", "evaluation_class", "period", "model", "geography", "observed_positive_count_mean", "predicted_conditional_mean", "conditional_mean_bias", "count_mae", "count_rmse"]})
        calibration_rows.append({key: row.get(key) for key in ["status", "evaluation_class", "period", "model", "geography", "calibration_intercept", "calibration_slope", "mean_predicted_probability", "observed_prevalence", "reliability_bins"]})
    pd.DataFrame(count_rows).drop_duplicates(["model", "geography"]).to_csv(output / "count_metrics.csv", index=False)
    pd.DataFrame(calibration_rows).drop_duplicates(["model", "geography"]).to_csv(output / "calibration_metrics.csv", index=False)
    pd.DataFrame([us_transfer_row(bundle, a3_fit, regions["United States"])]).to_csv(output / "us_transfer_metrics.csv", index=False)

    comparison = make_comparison(a0_full, a3_full)
    comparison.to_csv(output / "a0_a3_holdout_comparison.csv", index=False)
    pd.DataFrame([{
        "status": "NO ELIGIBLE PROSPECTIVE PERIOD",
        "evaluation_class": "PROSPECTIVE UNTOUCHED",
        "period": "2026-W30_onward",
        "geography": "all",
        "metric": "NO INDEPENDENT PROSPECTIVE EVALUATION AVAILABLE",
        "a0": None,
        "a3": None,
        "a3_improvement": None,
    }]).to_csv(output / "a0_a3_prospective_comparison.csv", index=False)

    historical_classification = classify_historical(a3_full)
    pd.DataFrame([
        {"evidence_class": "HISTORICAL EXPOSED HOLDOUT", "classification": historical_classification, "basis": "Fixed A3 scored on previously exposed 2026-W17--2026-W29 with frozen development preprocessing.", "independent_claim_allowed": False},
        {"evidence_class": "PROSPECTIVE UNTOUCHED", "classification": "PROSPECTIVE GENERALIZATION NOT YET TESTED", "basis": "Later source dates predate the freeze and complete A3 predictor support ends at 2026-W29.", "independent_claim_allowed": False},
    ]).to_csv(output / "generalization_classification.csv", index=False)

    provenance = pd.DataFrame([
        {"period": "F1-F4 development", "start_week": "2025-W01", "end_week": "2026-W16", "classification": "DEVELOPMENT", "previously_scored": True, "previously_used_for_selection": True, "previously_visible_in_reports": True, "evidence": "Frozen A3 development comparison F1-F4 only.", "eligible_for_independent_claim": False},
        {"period": "F5 historical pseudo-prospective", "start_week": "2026-W17", "end_week": "2026-W22", "classification": "HISTORICAL EXPOSED HOLDOUT", "previously_scored": True, "previously_used_for_selection": False, "previously_visible_in_reports": True, "evidence": "Persisted Task 3B reports identify F5 as historical pseudo-prospective/non-independent.", "eligible_for_independent_claim": False},
        {"period": "F6 historical pseudo-prospective", "start_week": "2026-W23", "end_week": "2026-W29", "classification": "HISTORICAL EXPOSED HOLDOUT", "previously_scored": True, "previously_used_for_selection": False, "previously_visible_in_reports": True, "evidence": "Persisted Task 3B and terminal evaluation reports identify F6/2026-W23--W29 as exposed.", "eligible_for_independent_claim": False},
        {"period": "Later source dates", "start_week": "2026-W30", "end_week": source["latest_observation_iso_week"], "classification": "NOT ELIGIBLE", "previously_scored": False, "previously_used_for_selection": False, "previously_visible_in_reports": False, "evidence": f"Observation source snapshot mtime {source['source_file_mtime_utc']} predates the freeze; complete A3 predictor support ends at 2026-W29.", "eligible_for_independent_claim": False},
    ])
    provenance.to_csv(output / "evaluation_period_provenance.csv", index=False)

    preprocessing_rows = []
    scaling = a3_fit["scaling"]
    for index, feature in enumerate(MODEL_FEATURES):
        preprocessing_rows.append({"feature": feature, "transformation": TRANSFORMATIONS.get(feature, "frozen_base_contract"), "scaling_rule": "development_fit_only" if index in scaling["scaled_feature_indices"] else "unscaled_frozen_indicator_calendar", "development_mean_used": scaling["training_mean"][index], "development_sd_used": scaling["training_sd"][index], "evaluation_data_used": False, "status": "PASS", "evidence": "final_a3_scaling_parameters.csv"})
    pd.DataFrame(preprocessing_rows).to_csv(output / "evaluation_preprocessing_audit.csv", index=False)
    pd.DataFrame(history_audit).to_csv(output / "history_feature_leakage_audit.csv", index=False)

    source.update({"manifest_sha256": manifest_sha, "software_sha": git_sha(), "latest_complete_a3_predictor_week": bundle["week_labels"][-1]})
    write_json(output / "data_refresh_provenance.json", source)
    task_rows = [
        {"task_id": "HIST-A3-FULL", "evaluation_class": "HISTORICAL EXPOSED HOLDOUT", "period": period, "model": "STRUCTURED_A3", "geography": "full_revised_domain", "status": "COMPLETED", "output_path": "results/overall_metrics.csv", "runtime_seconds": time.time() - started},
        {"task_id": "HIST-A3-GEO", "evaluation_class": "HISTORICAL EXPOSED HOLDOUT", "period": period, "model": "STRUCTURED_A3", "geography": "Mexico_and_United_States", "status": "COMPLETED", "output_path": "results/geographic_metrics.csv", "runtime_seconds": time.time() - started},
        {"task_id": "HIST-A0-A3", "evaluation_class": "HISTORICAL EXPOSED HOLDOUT", "period": period, "model": "A0_vs_A3", "geography": "full_revised_domain", "status": "COMPLETED", "output_path": "results/a0_a3_holdout_comparison.csv", "runtime_seconds": time.time() - started},
        {"task_id": "PROS-A3", "evaluation_class": "PROSPECTIVE UNTOUCHED", "period": "2026-W30_onward", "model": "STRUCTURED_A3", "geography": "all", "status": "NO ELIGIBLE PROSPECTIVE PERIOD", "output_path": "results/a0_a3_prospective_comparison.csv", "runtime_seconds": time.time() - started},
    ]
    pd.DataFrame(task_rows).to_csv(output / "evaluation_task_manifest.csv", index=False)

    try:
        import matplotlib  # noqa: F401
        figure_status = "matplotlib_available_but_figures_not_required_for_scoring"
    except Exception as exc:
        figure_status = f"unavailable: {exc}"
    (output.parent / "figures" / "figure_generation_status.txt").write_text(figure_status + "\n", encoding="utf-8")
    write_report(output, bundle, source, a3_full, a0_full, historical_classification, figure_status)
    write_json(output / "run_summary.json", {"status": "COMPLETED_HISTORICAL_EXPOSED_HOLDOUT", "historical_period": period, "prospective_status": "NO ELIGIBLE PROSPECTIVE PERIOD", "runtime_seconds": time.time() - started, "software_sha": git_sha(), "manifest_sha256": manifest_sha, "static_audit": static_audit})
    print(json.dumps({"status": "completed", "historical_period": period, "historical_classification": historical_classification, "prospective_status": "NO ELIGIBLE PROSPECTIVE PERIOD", "runtime_seconds": time.time() - started}, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-output", type=Path, default=Path("/project/disease_ecology/STGNN-output/revised_model_data"))
    parser.add_argument("--front-features", type=Path, default=Path("/project/disease_ecology/STGNN-output/v2_model/front_features/causal_front_features.parquet"))
    parser.add_argument("--anthropogenic-features", type=Path, default=Path("/project/disease_ecology/STGNN-output/predictor_augmentation/static/road_night_node_features.parquet"))
    parser.add_argument("--soil-features", type=Path, default=Path("/project/disease_ecology/STGNN-output/soil_feature_screening_resumed_s1/soil_node_features.parquet"))
    parser.add_argument("--output-root", type=Path, default=Path("analysis/structured_a3_evaluation/results"))
    args = parser.parse_args()
    run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
