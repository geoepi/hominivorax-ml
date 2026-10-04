#!/usr/bin/env python3
"""Task 2G frozen Hurdle-Current terminal evaluation.

The runner has two deliberately separate phases:

``freeze``
    Fits the locked 24-predictor Hurdle-Current model on development weeks
    only, persists the fitted preprocessing/model state, and writes a
    checksummed freeze manifest. Terminal target values are not materialized.

``score``
    Requires the checksummed freeze manifest, records the terminal unlock once,
    then reads terminal targets and calculates the pre-specified evaluation
    outputs. It refuses to run if the terminal unlock has already been recorded.

No augmented candidate is fitted or scored by this module.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import rankdata

SCRIPT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_ROOT))

from run_task2e_baselines import (  # noqa: E402
    ExactHurdleRegressor,
    safe_metrics,
    write_csv,
    write_json,
)
from run_task2f_structured import (  # noqa: E402
    BASE_FEATURES,
    CANDIDATES,
    DEVELOPMENT_WEEKS,
    EXPECTED_NODE_COUNT,
    EXPECTED_RESPONSE_WEEKS,
    apply_scaling,
    build_feature_arrays,
    fit_scaling,
    load_inputs,
    select_matrix,
    git_sha,
)


TERMINAL_START = DEVELOPMENT_WEEKS
TERMINAL_END = EXPECTED_RESPONSE_WEEKS
TERMINAL_INDICES = list(range(TERMINAL_START, TERMINAL_END))
MODEL_NAME = "Hurdle-Current"
MODEL_PENALTY = 0.0
MODEL_OBJECTIVE = "exact_joint_hurdle_nll"
COUNT_FAMILY = "zero_truncated_negative_binomial"
EPS = 1e-8
LATITUDE_BANDS = (
    ("<20N", -np.inf, 20.0),
    ("20-25N", 20.0, 25.0),
    ("25-30N", 25.0, 30.0),
    ("30-35N", 30.0, 35.0),
    ("35-40N", 35.0, 40.0),
)
REQUIRED_TERMINAL_WEEKS = (68, 72, 74, 76, 80)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def output_layout(output: Path) -> None:
    for subdir in ("model", "predictions", "metrics", "regional", "us_transfer", "figures", "manifests"):
        (output / subdir).mkdir(parents=True, exist_ok=True)


def feature_contract() -> dict[str, Any]:
    return {
        "model": MODEL_NAME,
        "predictor_count": len(BASE_FEATURES),
        "predictor_order": list(BASE_FEATURES),
        "predictor_groups": {
            "current_environmental": list(BASE_FEATURES[:12]),
            "livestock_log1p": list(BASE_FEATURES[12:17]),
            "livestock_imputation_indicators": list(BASE_FEATURES[17:22]),
            "calendar": list(BASE_FEATURES[22:24]),
        },
        "penalty": MODEL_PENALTY,
        "objective": MODEL_OBJECTIVE,
        "occurrence_model": "Bernoulli/logistic",
        "positive_count_model": COUNT_FAMILY,
        "dispersion": "one learned global theta",
        "excluded_terminal_candidates": [
            "Hurdle-Spatial",
            "Hurdle-Temporal",
            "Hurdle-Spatiotemporal",
            "GRU",
            "GConvGRU",
        ],
    }


def assert_primary_array(array: np.ndarray) -> None:
    if array.shape != (EXPECTED_RESPONSE_WEEKS, EXPECTED_NODE_COUNT, len(BASE_FEATURES)):
        raise AssertionError(f"unexpected Hurdle-Current feature shape: {array.shape}")
    if list(CANDIDATES[MODEL_NAME]) != list(BASE_FEATURES):
        raise AssertionError("Hurdle-Current feature ordering changed")
    if not np.isfinite(array).all():
        raise AssertionError("Hurdle-Current predictors contain non-finite values")


def training_fit(data: dict[str, Any], array: np.ndarray) -> tuple[ExactHurdleRegressor, dict[str, Any], dict[str, Any]]:
    """Fit exactly once on all development cells and return model state."""
    train_times = list(range(DEVELOPMENT_WEEKS))
    scaling = fit_scaling(array, train_times, None)
    x_train = apply_scaling(select_matrix(array, train_times, None), scaling)
    y_train = np.asarray(data["counts"], dtype=np.int64).reshape(-1)
    if y_train.size != DEVELOPMENT_WEEKS * EXPECTED_NODE_COUNT:
        raise AssertionError("development training cell count mismatch")
    model = ExactHurdleRegressor().fit(x_train, y_train)
    if not model.fit_info.get("occurrence_success") or not model.fit_info.get("count_success"):
        raise RuntimeError(f"frozen model did not converge: {model.fit_info}")
    if model.occurrence_beta is None or model.count_beta is None or model.theta is None:
        raise RuntimeError("frozen model did not expose complete fitted state")
    if not np.isfinite(model.occurrence_beta).all() or not np.isfinite(model.count_beta).all():
        raise RuntimeError("frozen model coefficients are not finite")
    if not np.isfinite(model.theta) or model.theta <= 0:
        raise RuntimeError("frozen model theta is not finite and positive")

    p, conditional, mu, theta = model.predict(x_train)
    train_matrix = y_train.reshape(DEVELOPMENT_WEEKS, EXPECTED_NODE_COUNT)
    train_metrics = safe_metrics(
        train_matrix,
        p.reshape(train_matrix.shape),
        conditional.reshape(train_matrix.shape),
        mu.reshape(train_matrix.shape),
        theta,
        float(np.mean(y_train > 0)),
        "development_training_fit",
        0,
        MODEL_NAME,
    )
    return model, scaling, {"training_metrics": train_metrics, "training_rows": int(y_train.size)}


def model_state(model: ExactHurdleRegressor, scaling: dict[str, Any], fit_details: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": MODEL_NAME,
        "penalty": MODEL_PENALTY,
        "objective": MODEL_OBJECTIVE,
        "count_family": COUNT_FAMILY,
        "occurrence_coefficients": np.asarray(model.occurrence_beta, dtype=float).tolist(),
        "positive_count_coefficients": np.asarray(model.count_beta, dtype=float).tolist(),
        "theta": float(model.theta),
        "fit_info": model.fit_info,
        "fit_details": fit_details,
        "feature_order": list(BASE_FEATURES),
        "intercept_included": True,
        "l2_penalty_excludes_intercept_and_theta": True,
        "scaling": scaling,
    }


def write_freeze_phase(data: dict[str, Any], array: np.ndarray, output: Path) -> dict[str, Any]:
    manifest_path = output / "manifests" / "model_freeze_manifest.json"
    checksum_path = output / "manifests" / "model_freeze_manifest.sha256"
    if manifest_path.exists() or checksum_path.exists():
        raise RuntimeError("model freeze already exists; refusing to refit or overwrite it")
    if (output / "manifests" / "terminal_unlock.json").exists():
        raise RuntimeError("terminal unlock already exists")

    model, scaling, fit_details = training_fit(data, array)
    model_path = output / "model" / "frozen_model.json"
    scaling_path = output / "model" / "fitted_preprocessing.json"
    state = model_state(model, scaling, fit_details)
    write_json(model_path, state)
    write_json(scaling_path, scaling)

    source_manifest_path = data["root"] / "manifests" / "revised_production_manifest.json"
    manifest = {
        "status": "frozen_before_terminal_unlock",
        "freeze_timestamp_utc": utc_now(),
        "git_sha": git_sha(),
        "branch_expected": "feature/terminal-evaluation",
        "source_observation_sha256": data["source_sha"],
        "source_observation_row_count": 136714,
        "dataset_manifest_sha256": sha256_file(source_manifest_path),
        "graph_checksum_sha256": data["graph_checksum"],
        "model_specification": feature_contract(),
        "development_period": {
            "indices": list(range(DEVELOPMENT_WEEKS)),
            "start": str(data["weeks"]["iso_week"].iloc[0]),
            "end": str(data["weeks"]["iso_week"].iloc[DEVELOPMENT_WEEKS - 1]),
            "week_count": DEVELOPMENT_WEEKS,
            "node_count": EXPECTED_NODE_COUNT,
        },
        "terminal_period": {
            "indices": TERMINAL_INDICES,
            "start": str(data["weeks"]["iso_week"].iloc[TERMINAL_START]),
            "end": str(data["weeks"]["iso_week"].iloc[TERMINAL_END - 1]),
            "week_count": len(TERMINAL_INDICES),
        },
        "preprocessing": {
            "dynamic_environment": "identity then development-period mean/std scaling",
            "livestock_density": "log1p then development-fit mean/std scaling",
            "livestock_imputation_indicators": "0/1 unchanged",
            "calendar": "week_sin and week_cos unchanged",
            "fit_scope": "all development weeks and all revised-domain nodes only",
            "artifact": "model/fitted_preprocessing.json",
        },
        "optimizer": model.fit_info,
        "training_metrics": fit_details["training_metrics"],
        "theta": float(model.theta),
        "coefficient_artifact": "model/frozen_model.json",
        "preprocessing_artifact": "model/fitted_preprocessing.json",
        "terminal_targets_accessed_before_freeze": False,
        "augmented_models_scored": False,
    }
    write_json(manifest_path, manifest)
    checksum = sha256_file(manifest_path)
    checksum_path.write_text(f"{checksum}  model_freeze_manifest.json\n", encoding="utf-8")
    manifest["manifest_sha256"] = checksum
    # The checksum is intentionally stored beside, rather than inside, the
    # manifest so the manifest hash remains stable and independently verifiable.
    return manifest


def verify_freeze(output: Path) -> tuple[dict[str, Any], str]:
    manifest_path = output / "manifests" / "model_freeze_manifest.json"
    checksum_path = output / "manifests" / "model_freeze_manifest.sha256"
    if not manifest_path.exists() or not checksum_path.exists():
        raise RuntimeError("missing pre-evaluation freeze manifest/checksum")
    recorded = checksum_path.read_text(encoding="utf-8").strip().split()[0]
    actual = sha256_file(manifest_path)
    if recorded != actual:
        raise RuntimeError("model freeze manifest checksum mismatch")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "frozen_before_terminal_unlock":
        raise RuntimeError("freeze manifest does not have the required pre-unlock status")
    if manifest.get("model_specification", {}).get("model") != MODEL_NAME:
        raise RuntimeError("freeze manifest model mismatch")
    if manifest.get("model_specification", {}).get("penalty") != MODEL_PENALTY:
        raise RuntimeError("freeze manifest penalty mismatch")
    if manifest.get("terminal_targets_accessed_before_freeze") is not False:
        raise RuntimeError("freeze manifest does not certify terminal exclusion")
    return manifest, actual


def load_frozen_model(output: Path) -> tuple[ExactHurdleRegressor, dict[str, Any]]:
    state = json.loads((output / "model" / "frozen_model.json").read_text(encoding="utf-8"))
    model = ExactHurdleRegressor()
    model.occurrence_beta = np.asarray(state["occurrence_coefficients"], dtype=np.float64)
    model.count_beta = np.asarray(state["positive_count_coefficients"], dtype=np.float64)
    model.theta = float(state["theta"])
    model.fit_info = state["fit_info"]
    if model.occurrence_beta.size != len(BASE_FEATURES) + 1 or model.count_beta.size != len(BASE_FEATURES) + 1:
        raise RuntimeError("frozen coefficient width does not match the 24-feature contract")
    if not np.isfinite(model.occurrence_beta).all() or not np.isfinite(model.count_beta).all() or model.theta <= 0:
        raise RuntimeError("frozen model state is invalid")
    return model, state["scaling"]


def load_terminal_targets(root: Path) -> tuple[np.ndarray, np.ndarray]:
    counts_memmap = np.load(root / "raw" / "targets_count.npy", mmap_mode="r")
    presence_memmap = np.load(root / "raw" / "targets_presence.npy", mmap_mode="r")
    counts = np.asarray(counts_memmap[TERMINAL_START:TERMINAL_END], dtype=np.int64)
    presence = np.asarray(presence_memmap[TERMINAL_START:TERMINAL_END], dtype=np.int8)
    if counts.shape != (len(TERMINAL_INDICES), EXPECTED_NODE_COUNT):
        raise AssertionError(f"terminal count shape mismatch: {counts.shape}")
    if not np.array_equal(presence, (counts > 0).astype(np.int8)):
        raise AssertionError("terminal presence does not equal terminal count > 0")
    if np.any(counts < 0):
        raise AssertionError("negative terminal count")
    return counts, presence


def load_state_map(root: Path, node_count: int) -> np.ndarray:
    path = root / "diagnostics" / "updated_observation_classification.parquet"
    state_by_node: dict[int, str] = {}
    if path.exists():
        frame = pd.read_parquet(path, columns=["model_node_id", "state"])
        for node_id, group in frame.dropna(subset=["model_node_id"]).groupby("model_node_id"):
            values = group["state"].dropna().astype(str)
            if len(values):
                state_by_node[int(node_id)] = str(values.mode().iloc[0])
    return np.asarray([state_by_node.get(index, "") for index in range(node_count)], dtype=object)


def terminal_prediction_frame(data: dict[str, Any], counts: np.ndarray, p: np.ndarray, conditional: np.ndarray, mu: np.ndarray, state: np.ndarray) -> pd.DataFrame:
    nodes = data["nodes"]
    records: list[pd.DataFrame] = []
    for local_t, global_t in enumerate(TERMINAL_INDICES):
        records.append(pd.DataFrame({
            "terminal_week_index": int(global_t),
            "week": str(data["weeks"]["iso_week"].iloc[global_t]),
            "node_id": np.arange(len(nodes), dtype=np.int32),
            "canonical_node_id": nodes["canonical_node_id"].to_numpy(np.int64),
            "raster_cell": nodes["raster_cell"].to_numpy(np.int64),
            "longitude": nodes["lon"].to_numpy(np.float64),
            "latitude": nodes["lat"].to_numpy(np.float64),
            "state": state,
            "region": nodes["country_or_domain_region"].astype(str).to_numpy(),
            "observed_count": counts[local_t].astype(np.int32),
            "observed_presence": (counts[local_t] > 0).astype(np.int8),
            "predicted_occurrence_probability": p[local_t],
            "predicted_conditional_positive_mean": conditional[local_t],
            "predicted_underlying_mu": mu[local_t],
            "predicted_unconditional_mean": p[local_t] * conditional[local_t],
        }))
    return pd.concat(records, ignore_index=True)


def terminal_metrics(data: dict[str, Any], counts: np.ndarray, p: np.ndarray, conditional: np.ndarray, mu: np.ndarray, theta: float, train_prevalence: float) -> dict[str, Any]:
    primary = safe_metrics(counts, p, conditional, mu, theta, train_prevalence, "full_revised_domain", 0, MODEL_NAME)
    primary["terminal_start"] = str(data["weeks"]["iso_week"].iloc[TERMINAL_START])
    primary["terminal_end"] = str(data["weeks"]["iso_week"].iloc[TERMINAL_END - 1])
    primary["terminal_prevalence"] = float(np.mean(counts > 0))
    primary["observed_total_detections"] = int(counts.sum())
    primary["predicted_expected_total_detections"] = float(np.sum(p * conditional))
    primary["observed_positive_node_weeks"] = int(np.sum(counts > 0))
    primary["predicted_total_occurrence_probability_mass"] = float(np.sum(p))
    return primary


def regional_evaluation(data: dict[str, Any], counts: np.ndarray, p: np.ndarray, conditional: np.ndarray, mu: np.ndarray, theta: float, train_prevalence: float) -> list[dict[str, Any]]:
    region_values = data["nodes"]["country_or_domain_region"].astype(str).to_numpy()
    masks = {
        "full_revised_domain": np.ones(len(region_values), dtype=bool),
        "Mexico": region_values == "Mexico",
        "United States": region_values == "U.S.-to-40N",
    }
    rows: list[dict[str, Any]] = []
    for region, mask in masks.items():
        result = safe_metrics(counts[:, mask], p[:, mask], conditional[:, mask], mu[:, mask], theta, train_prevalence, region, 0, MODEL_NAME)
        result.update({
            "region": region,
            "model": MODEL_NAME,
            "penalty": MODEL_PENALTY,
            "node_count": int(mask.sum()),
            "node_weeks": int(mask.sum() * len(TERMINAL_INDICES)),
            "positive_node_weeks": int(np.sum(counts[:, mask] > 0)),
            "observed_total_detections": int(counts[:, mask].sum()),
            "predicted_expected_total_detections": float(np.sum(p[:, mask] * conditional[:, mask])),
        })
        rows.append(result)
    return rows


def weekly_evaluation(data: dict[str, Any], counts: np.ndarray, p: np.ndarray, conditional: np.ndarray, train_prevalence: float) -> list[dict[str, Any]]:
    region_values = data["nodes"]["country_or_domain_region"].astype(str).to_numpy()
    us = region_values == "U.S.-to-40N"
    rows: list[dict[str, Any]] = []
    for local_t, global_t in enumerate(TERMINAL_INDICES):
        y = counts[local_t]
        probability = p[local_t]
        expected = probability * conditional[local_t]
        us_probability = probability[us]
        rows.append({
            "terminal_week_index": int(global_t),
            "week": str(data["weeks"]["iso_week"].iloc[global_t]),
            "mean_predicted_probability": float(probability.mean()),
            "observed_prevalence": float(np.mean(y > 0)),
            "observed_positive_node_count": int(np.sum(y > 0)),
            "weekly_observed_count": int(y.sum()),
            "weekly_expected_count": float(expected.sum()),
            "mean_predicted_unconditional_count": float(expected.mean()),
            "us_max_predicted_probability": float(us_probability.max()),
            "us_mean_predicted_probability": float(us_probability.mean()),
            "us_p95_predicted_probability": float(np.percentile(us_probability, 95)),
            "us_observed_positive_nodes": int(np.sum(y[us] > 0)),
            "us_observed_count": int(y[us].sum()),
            "training_prevalence_reference": train_prevalence,
        })
    return rows


def us_positive_ranks(data: dict[str, Any], counts: np.ndarray, p: np.ndarray, state: np.ndarray) -> list[dict[str, Any]]:
    region_values = data["nodes"]["country_or_domain_region"].astype(str).to_numpy()
    us_nodes = np.flatnonzero(region_values == "U.S.-to-40N")
    domain_nodes = np.arange(len(region_values))
    rows: list[dict[str, Any]] = []
    for local_t, global_t in enumerate(TERMINAL_INDICES):
        us_rank = rankdata(p[local_t, us_nodes], method="average")
        domain_rank = rankdata(p[local_t, domain_nodes], method="average")
        us_denominator = max(len(us_nodes) - 1, 1)
        domain_denominator = max(len(domain_nodes) - 1, 1)
        for node_id in us_nodes[counts[local_t, us_nodes] > 0]:
            us_position = int(np.flatnonzero(us_nodes == node_id)[0])
            rows.append({
                "week": str(data["weeks"]["iso_week"].iloc[global_t]),
                "terminal_week_index": int(global_t),
                "node_id": int(node_id),
                "state": str(state[node_id]),
                "latitude": float(data["nodes"]["lat"].iloc[node_id]),
                "longitude": float(data["nodes"]["lon"].iloc[node_id]),
                "observed_count": int(counts[local_t, node_id]),
                "predicted_occurrence_probability": float(p[local_t, node_id]),
                "percentile_rank_among_us_nodes": float(100.0 * (us_rank[us_position] - 1.0) / us_denominator),
                "percentile_rank_among_revised_domain_nodes": float(100.0 * (domain_rank[node_id] - 1.0) / domain_denominator),
            })
    return rows


def latitude_evaluation(data: dict[str, Any], counts: np.ndarray, p: np.ndarray) -> list[dict[str, Any]]:
    latitudes = data["nodes"]["lat"].to_numpy(np.float64)
    rows: list[dict[str, Any]] = []
    for local_t, global_t in enumerate(TERMINAL_INDICES):
        for band, lower, upper in LATITUDE_BANDS:
            mask = (latitudes >= lower) & (latitudes < upper)
            if not mask.any():
                continue
            rows.append({
                "week": str(data["weeks"]["iso_week"].iloc[global_t]),
                "terminal_week_index": int(global_t),
                "latitude_band": band,
                "node_count": int(mask.sum()),
                "mean_predicted_probability": float(p[local_t, mask].mean()),
                "p95_predicted_probability": float(np.percentile(p[local_t, mask], 95)),
                "max_predicted_probability": float(p[local_t, mask].max()),
                "positive_node_weeks": int(np.sum(counts[local_t, mask] > 0)),
            })
    return rows


def calibration_rows(p: np.ndarray, y: np.ndarray, region: str, bins: int = 10) -> list[dict[str, Any]]:
    p_flat = np.asarray(p, dtype=np.float64).reshape(-1)
    y_flat = (np.asarray(y, dtype=np.int64).reshape(-1) > 0).astype(np.int8)
    if p_flat.size == 0 or np.unique(y_flat).size < 2:
        return []
    order = np.argsort(p_flat, kind="mergesort")
    rows: list[dict[str, Any]] = []
    for index, bin_indices in enumerate(np.array_split(order, min(bins, p_flat.size)), start=1):
        if len(bin_indices) == 0:
            continue
        rows.append({
            "region": region,
            "adaptive_bin": index,
            "mean_predicted_probability": float(p_flat[bin_indices].mean()),
            "observed_prevalence": float(y_flat[bin_indices].mean()),
            "sample_count": int(len(bin_indices)),
            "minimum_predicted_probability": float(p_flat[bin_indices].min()),
            "maximum_predicted_probability": float(p_flat[bin_indices].max()),
        })
    return rows


def count_diagnostics(data: dict[str, Any], counts: np.ndarray, conditional: np.ndarray) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    positive = counts > 0
    observed = counts[positive].astype(np.float64)
    predicted = conditional[positive].astype(np.float64)
    threshold = float(np.percentile(observed, 95)) if observed.size else None
    summary = {
        "positive_node_weeks": int(observed.size),
        "mae": float(np.mean(np.abs(observed - predicted))) if observed.size else None,
        "rmse": float(np.sqrt(np.mean((observed - predicted) ** 2))) if observed.size else None,
        "bias_predicted_minus_observed": float(np.mean(predicted - observed)) if observed.size else None,
        "observed_mean": float(observed.mean()) if observed.size else None,
        "predicted_conditional_mean": float(predicted.mean()) if observed.size else None,
        "extreme_threshold_observed_count_p95": threshold,
    }
    rows: list[dict[str, Any]] = []
    extreme: list[dict[str, Any]] = []
    for local_t, global_t in enumerate(TERMINAL_INDICES):
        for node_id in np.flatnonzero(positive[local_t]):
            row = {
                "week": str(data["weeks"]["iso_week"].iloc[global_t]),
                "terminal_week_index": int(global_t),
                "node_id": int(node_id),
                "observed_count": int(counts[local_t, node_id]),
                "predicted_conditional_positive_mean": float(conditional[local_t, node_id]),
            }
            rows.append(row)
            if threshold is not None and counts[local_t, node_id] >= threshold:
                extreme.append(row)
    return summary, pd.DataFrame(rows), pd.DataFrame(extreme)


def development_comparison(data: dict[str, Any], terminal_primary: dict[str, Any]) -> list[dict[str, Any]]:
    path = data["root"] / "structured" / "validation" / "task2f_temporal_metrics.csv"
    if not path.exists():
        raise FileNotFoundError(f"required Task 2F development metrics missing: {path}")
    frame = pd.read_csv(path)
    frame = frame[frame["candidate"] == MODEL_NAME]
    if len(frame) != 4:
        raise AssertionError("expected four Task 2F development folds for Hurdle-Current")
    terminal_values = {
        "brier_skill": terminal_primary.get("brier_skill"),
        "pr_auc": terminal_primary.get("pr_auc"),
        "joint_hurdle_nll": terminal_primary.get("joint_hurdle_nll"),
        "positive_count_mae": terminal_primary.get("positive_count_mae"),
    }
    rows: list[dict[str, Any]] = []
    for metric, terminal_value in terminal_values.items():
        values = pd.to_numeric(frame[metric], errors="coerce").dropna().to_numpy(float)
        rows.append({
            "model": MODEL_NAME,
            "metric": metric,
            "development_fold_min": float(values.min()),
            "development_mean": float(values.mean()),
            "development_fold_max": float(values.max()),
            "terminal_value": terminal_value,
            "terminal_within_development_range": bool(terminal_value is not None and values.min() <= float(terminal_value) <= values.max()),
        })
    return rows


def classify_generalization(primary: dict[str, Any], mexico: dict[str, Any], development: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    by_metric = {row["metric"]: row for row in development}
    brier = primary.get("brier_skill")
    enrichment = primary.get("pr_auc_over_prevalence")
    joint = primary.get("joint_hurdle_nll")
    full_positive_signal = bool((brier is not None and brier > 0) or (enrichment is not None and enrichment > 1))
    mexico_signal = bool(mexico.get("brier_skill") is not None and mexico["brier_skill"] > 0)
    within_core_range = bool(
        brier is not None
        and by_metric["brier_skill"]["development_fold_min"] <= float(brier) <= by_metric["brier_skill"]["development_fold_max"]
        and joint is not None
        and float(joint) <= by_metric["joint_hurdle_nll"]["development_fold_max"]
    )
    if within_core_range and full_positive_signal and mexico_signal:
        label = "GENERALIZES"
    elif full_positive_signal or mexico_signal:
        label = "PARTIAL GENERALIZATION"
    else:
        label = "FAILS TERMINAL GENERALIZATION"
    return label, {
        "full_domain_positive_signal": full_positive_signal,
        "mexico_positive_signal": mexico_signal,
        "core_metrics_within_development_range": within_core_range,
        "interpretation_rule": "Qualitative assessment using full-domain calibration/discrimination, Brier skill, joint NLL, Mexico behavior, and count diagnostics; no composite score.",
    }


def classify_us_transfer(us_primary: dict[str, Any], ranks: list[dict[str, Any]], weekly: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    if not ranks:
        return "NO EVIDENCE OF NORTHWARD TRANSFER", {"reason": "no positive U.S. terminal node-weeks"}
    within = np.asarray([row["percentile_rank_among_us_nodes"] for row in ranks], dtype=float)
    high_rank_fraction = float(np.mean(within >= 75.0))
    first_positive_week = min(row["terminal_week_index"] for row in ranks)
    before = [row for row in weekly if row["terminal_week_index"] < first_positive_week]
    pre_detection_max = max((row["us_max_predicted_probability"] for row in before), default=None)
    all_week_max = max(row["us_max_predicted_probability"] for row in weekly)
    brier_signal = us_primary.get("brier_skill")
    if high_rank_fraction >= 0.5 and brier_signal is not None and brier_signal > 0 and pre_detection_max is not None and pre_detection_max >= float(np.median([row["us_max_predicted_probability"] for row in weekly])):
        label = "USEFUL NORTHWARD TRANSFER"
    elif high_rank_fraction > 0 or (brier_signal is not None and brier_signal > 0) or (pre_detection_max is not None and pre_detection_max > 0):
        label = "WEAK / AMBIGUOUS NORTHWARD TRANSFER"
    else:
        label = "NO EVIDENCE OF NORTHWARD TRANSFER"
    return label, {
        "positive_case_count": len(ranks),
        "high_within_us_rank_fraction": high_rank_fraction,
        "first_positive_week_index": int(first_positive_week),
        "pre_detection_max_probability": pre_detection_max,
        "all_week_max_probability": all_week_max,
        "interpretation_rule": "Descriptive assessment using positive-case within-U.S. ranks, U.S. discrimination/calibration where estimable, and pre-detection probability patterns; no probability threshold was introduced.",
    }


def generate_maps(data: dict[str, Any], counts: np.ndarray, p: np.ndarray, output: Path) -> list[str]:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ModuleNotFoundError:
        return generate_svg_maps(data, counts, p, output)

    nodes = data["nodes"]
    lon = nodes["lon"].to_numpy(float)
    lat = nodes["lat"].to_numpy(float)
    vmax = max(float(np.max(p)), EPS)
    generated: list[str] = []

    def save_map(name: str, title: str, values: np.ndarray, positive: np.ndarray, focus: np.ndarray | None = None) -> None:
        fig, ax = plt.subplots(figsize=(10, 6), constrained_layout=True)
        use = np.ones(len(nodes), dtype=bool) if focus is None else focus
        ax.scatter(lon[use], lat[use], c=values[use], s=3, cmap="viridis", vmin=0, vmax=vmax, linewidths=0)
        if np.any(positive & use):
            ax.scatter(lon[positive & use], lat[positive & use], s=18, facecolors="none", edgecolors="red", linewidths=0.8, label="observed positive")
            ax.legend(loc="upper right")
        ax.set_xlabel("Longitude")
        ax.set_ylabel("Latitude")
        ax.set_title(title)
        fig.colorbar(ax.collections[0], ax=ax, label="P(recorded detection > 0)")
        path = output / "figures" / name
        fig.savefig(path, dpi=180)
        plt.close(fig)
        generated.append(str(path))

    for global_t in REQUIRED_TERMINAL_WEEKS:
        local_t = TERMINAL_INDICES.index(global_t)
        week = str(data["weeks"]["iso_week"].iloc[global_t])
        save_map(f"terminal_probability_{week}.png", f"Task 2G terminal probability — {week}", p[local_t], counts[local_t] > 0)

    max_probability = p.max(axis=0)
    max_week = np.asarray([str(data["weeks"]["iso_week"].iloc[TERMINAL_INDICES[index]]) for index in p.argmax(axis=0)], dtype=object)
    pd.DataFrame({"node_id": np.arange(len(nodes)), "week_of_max_predicted_probability": max_week, "max_predicted_probability": max_probability}).to_csv(output / "metrics" / "terminal_node_max_probability.csv", index=False)
    save_map("terminal_probability_maximum.png", "Task 2G maximum terminal probability", max_probability, counts.max(axis=0) > 0)

    first_positive = np.flatnonzero((counts[:, data["nodes"]["country_or_domain_region"].astype(str).to_numpy() == "U.S.-to-40N"] > 0).any(axis=1))
    if len(first_positive):
        first_local = int(first_positive[0])
        for local_t in sorted(set([max(0, first_local - 1), first_local, min(len(TERMINAL_INDICES) - 1, first_local + 1)])):
            global_t = TERMINAL_INDICES[local_t]
            week = str(data["weeks"]["iso_week"].iloc[global_t])
            focus = (lat >= 20.0) & (lat < 41.0) & (lon >= -125.0) & (lon <= -95.0)
            save_map(f"us_northern_mexico_probability_{week}.png", f"Task 2G U.S./northern Mexico probability — {week}", p[local_t], counts[local_t] > 0, focus)
    return generated


def generate_svg_maps(data: dict[str, Any], counts: np.ndarray, p: np.ndarray, output: Path) -> list[str]:
    """Write dependency-free vector maps when matplotlib is unavailable."""
    from xml.sax.saxutils import escape

    nodes = data["nodes"]
    lon = nodes["lon"].to_numpy(float)
    lat = nodes["lat"].to_numpy(float)
    vmax = max(float(np.max(p)), EPS)
    generated: list[str] = []
    width, height = 1200, 720
    left, right, top, bottom = 78, 30, 58, 70

    def color(value: float) -> str:
        ratio = min(max(float(value) / vmax, 0.0), 1.0)
        # Perceptually ordered dark-purple -> blue -> green -> yellow scale.
        stops = [(68, 1, 84), (59, 82, 139), (33, 145, 140), (94, 201, 98), (253, 231, 37)]
        position = ratio * (len(stops) - 1)
        lower = min(int(position), len(stops) - 2)
        fraction = position - lower
        rgb = tuple(round(stops[lower][i] + fraction * (stops[lower + 1][i] - stops[lower][i])) for i in range(3))
        return "#%02x%02x%02x" % rgb

    def save_map(name: str, title: str, values: np.ndarray, positive: np.ndarray, focus: np.ndarray | None = None) -> None:
        use = np.ones(len(nodes), dtype=bool) if focus is None else focus
        if not use.any():
            return
        x_values = lon[use]
        y_values = lat[use]
        x_min, x_max = float(x_values.min()), float(x_values.max())
        y_min, y_max = float(y_values.min()), float(y_values.max())
        x_span = max(x_max - x_min, 1.0)
        y_span = max(y_max - y_min, 1.0)

        def project(x: float, y: float) -> tuple[float, float]:
            px = left + (x - x_min) / x_span * (width - left - right)
            py = height - bottom - (y - y_min) / y_span * (height - top - bottom)
            return px, py

        elements = [
            f'<rect width="{width}" height="{height}" fill="white"/>',
            f'<text x="{left}" y="30" font-family="sans-serif" font-size="20">{escape(title)}</text>',
            f'<line x1="{left}" y1="{height-bottom}" x2="{width-right}" y2="{height-bottom}" stroke="#555"/>',
            f'<line x1="{left}" y1="{top}" x2="{left}" y2="{height-bottom}" stroke="#555"/>',
            f'<text x="{(left + width - right) / 2:.1f}" y="{height-20}" text-anchor="middle" font-family="sans-serif" font-size="14">Longitude</text>',
            f'<text x="18" y="{(top + height-bottom) / 2:.1f}" transform="rotate(-90 18 {(top + height-bottom) / 2:.1f})" text-anchor="middle" font-family="sans-serif" font-size="14">Latitude</text>',
        ]
        for node_id in np.flatnonzero(use):
            px, py = project(lon[node_id], lat[node_id])
            elements.append(f'<circle cx="{px:.2f}" cy="{py:.2f}" r="2" fill="{color(values[node_id])}" fill-opacity="0.75"/>')
        for node_id in np.flatnonzero(positive & use):
            px, py = project(lon[node_id], lat[node_id])
            elements.append(f'<circle cx="{px:.2f}" cy="{py:.2f}" r="5" fill="none" stroke="#d62728" stroke-width="1.2"/>')
        elements.extend([
            f'<text x="{width-220}" y="{top+18}" font-family="sans-serif" font-size="12">common scale: 0 to {vmax:.4g}</text>',
            f'<text x="{width-220}" y="{top+38}" font-family="sans-serif" font-size="12" fill="#d62728">red outline = observed positive</text>',
        ])
        path = output / "figures" / name
        path.write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">' + "".join(elements) + "</svg>\n",
            encoding="utf-8",
        )
        generated.append(str(path))

    for global_t in REQUIRED_TERMINAL_WEEKS:
        local_t = TERMINAL_INDICES.index(global_t)
        week = str(data["weeks"]["iso_week"].iloc[global_t])
        save_map(f"terminal_probability_{week}.svg", f"Task 2G terminal probability — {week}", p[local_t], counts[local_t] > 0)

    max_probability = p.max(axis=0)
    max_week = np.asarray([str(data["weeks"]["iso_week"].iloc[TERMINAL_INDICES[index]]) for index in p.argmax(axis=0)], dtype=object)
    pd.DataFrame({"node_id": np.arange(len(nodes)), "week_of_max_predicted_probability": max_week, "max_predicted_probability": max_probability}).to_csv(output / "metrics" / "terminal_node_max_probability.csv", index=False)
    save_map("terminal_probability_maximum.svg", "Task 2G maximum terminal probability", max_probability, counts.max(axis=0) > 0)

    us_mask = data["nodes"]["country_or_domain_region"].astype(str).to_numpy() == "U.S.-to-40N"
    first_positive = np.flatnonzero((counts[:, us_mask] > 0).any(axis=1))
    if len(first_positive):
        first_local = int(first_positive[0])
        focus = (lat >= 20.0) & (lat < 41.0) & (lon >= -125.0) & (lon <= -95.0)
        for local_t in sorted(set([max(0, first_local - 1), first_local, min(len(TERMINAL_INDICES) - 1, first_local + 1)])):
            global_t = TERMINAL_INDICES[local_t]
            week = str(data["weeks"]["iso_week"].iloc[global_t])
            save_map(f"us_northern_mexico_probability_{week}.svg", f"Task 2G U.S./northern Mexico probability — {week}", p[local_t], counts[local_t] > 0, focus)
    return generated


def score_terminal_phase(data: dict[str, Any], array: np.ndarray, output: Path) -> dict[str, Any]:
    manifest, freeze_checksum = verify_freeze(output)
    unlock_path = output / "manifests" / "terminal_unlock.json"
    if unlock_path.exists():
        raise RuntimeError("terminal targets have already been unlocked; Task 2G scoring is one-time")
    if (output / "predictions" / "terminal_predictions.parquet").exists():
        raise RuntimeError("terminal predictions already exist; refusing to rescore")

    unlock = {
        "status": "terminal_unlocked_once",
        "terminal_unlock_timestamp_utc": utc_now(),
        "model_freeze_manifest_sha256": freeze_checksum,
        "terminal_indices": TERMINAL_INDICES,
        "terminal_targets_will_be_read_after_this_record": True,
        "model": MODEL_NAME,
        "penalty": MODEL_PENALTY,
        "augmented_models_scored": False,
    }
    write_json(unlock_path, unlock)

    counts, presence = load_terminal_targets(data["root"])
    model, scaling = load_frozen_model(output)
    x_terminal = apply_scaling(select_matrix(array, TERMINAL_INDICES, None), scaling)
    p, conditional, mu, theta = model.predict(x_terminal)
    shape = (len(TERMINAL_INDICES), EXPECTED_NODE_COUNT)
    p = p.reshape(shape)
    conditional = conditional.reshape(shape)
    mu = mu.reshape(shape)
    if p.shape != counts.shape or conditional.shape != counts.shape or mu.shape != counts.shape:
        raise AssertionError("terminal prediction shape mismatch")
    if not np.isfinite(p).all() or not np.isfinite(conditional).all() or not np.isfinite(mu).all():
        raise AssertionError("terminal predictions contain non-finite values")
    if np.any(p < 0) or np.any(p > 1) or np.any(conditional <= 0) or np.any(mu <= 0):
        raise AssertionError("terminal predictions outside valid ranges")

    state = load_state_map(data["root"], EXPECTED_NODE_COUNT)
    predictions = terminal_prediction_frame(data, counts, p, conditional, mu, state)
    predictions.to_parquet(output / "predictions" / "terminal_predictions.parquet", index=False)

    train_prevalence = float(np.mean(np.asarray(data["counts"]) > 0))
    primary = terminal_metrics(data, counts, p, conditional, mu, theta, train_prevalence)
    regional = regional_evaluation(data, counts, p, conditional, mu, theta, train_prevalence)
    regional_by_name = {row["region"]: row for row in regional}
    weekly = weekly_evaluation(data, counts, p, conditional, train_prevalence)
    latitude = latitude_evaluation(data, counts, p)
    ranks = us_positive_ranks(data, counts, p, state)
    us_primary = regional_by_name["United States"]
    calibration: list[dict[str, Any]] = []
    region_values = data["nodes"]["country_or_domain_region"].astype(str).to_numpy()
    masks = {
        "full_revised_domain": np.ones(len(region_values), dtype=bool),
        "Mexico": region_values == "Mexico",
        "United States": region_values == "U.S.-to-40N",
    }
    for name, mask in masks.items():
        if name != "United States" or int(np.sum(counts[:, mask] > 0)) >= 2:
            calibration.extend(calibration_rows(p[:, mask], counts[:, mask], name))
    count_summary, count_rows, extreme_rows = count_diagnostics(data, counts, conditional)
    development = development_comparison(data, primary)
    generalization, generalization_evidence = classify_generalization(primary, regional_by_name["Mexico"], development)
    us_transfer, us_transfer_evidence = classify_us_transfer(us_primary, ranks, weekly)

    write_json(output / "metrics" / "terminal_metrics.json", {
        "model": MODEL_NAME,
        "penalty": MODEL_PENALTY,
        "freeze_manifest_sha256": freeze_checksum,
        "terminal_unlock_timestamp_utc": unlock["terminal_unlock_timestamp_utc"],
        "terminal_scoring_timestamp_utc": utc_now(),
        "training_prevalence_reference": train_prevalence,
        "primary_full_domain": primary,
        "totals": {
            "observed_total_detections": int(counts.sum()),
            "predicted_expected_total_detections": float(np.sum(p * conditional)),
            "observed_positive_node_weeks": int(np.sum(counts > 0)),
            "predicted_total_occurrence_probability_mass": float(np.sum(p)),
        },
        "generalization_classification": generalization,
        "generalization_evidence": generalization_evidence,
        "us_transfer_classification": us_transfer,
        "us_transfer_evidence": us_transfer_evidence,
        "terminal_target_values_accessed": True,
        "model_specification_changed_after_unlock": False,
        "secondary_model_scored": False,
    })
    write_csv(output / "regional" / "terminal_regional_metrics.csv", regional)
    write_csv(output / "metrics" / "terminal_weekly_metrics.csv", weekly)
    write_csv(output / "metrics" / "terminal_latitude_metrics.csv", latitude)
    write_csv(output / "metrics" / "terminal_calibration.csv", calibration)
    write_csv(output / "us_transfer" / "terminal_us_positive_ranks.csv", ranks)
    write_json(output / "us_transfer" / "terminal_us_summary.json", {
        "region": "United States",
        "terminal_node_weeks": int(np.sum(masks["United States"]) * len(TERMINAL_INDICES)),
        "positive_node_weeks": int(np.sum(counts[:, masks["United States"]] > 0)),
        "unique_positive_nodes": int(np.sum((counts[:, masks["United States"]] > 0).any(axis=0))),
        "recorded_detections": int(counts[:, masks["United States"]].sum()),
        "weeks_with_detections": [str(data["weeks"]["iso_week"].iloc[TERMINAL_INDICES[i]]) for i in np.flatnonzero((counts[:, masks["United States"]] > 0).any(axis=1))],
        "metrics": us_primary,
        "classification": us_transfer,
        "classification_evidence": us_transfer_evidence,
    })
    write_json(output / "metrics" / "terminal_count_metrics.json", count_summary)
    count_rows.to_csv(output / "metrics" / "terminal_positive_count_diagnostics.csv", index=False)
    extreme_rows.to_csv(output / "metrics" / "terminal_extreme_positive_counts.csv", index=False)
    write_csv(output / "metrics" / "development_vs_terminal.csv", development)
    generated_maps = generate_maps(data, counts, p, output)

    complete = {
        "status": "completed_terminal_evaluation",
        "model": MODEL_NAME,
        "penalty": MODEL_PENALTY,
        "freeze_manifest_sha256": freeze_checksum,
        "terminal_unlock_timestamp_utc": unlock["terminal_unlock_timestamp_utc"],
        "terminal_scoring_timestamp_utc": utc_now(),
        "generalization_classification": generalization,
        "us_transfer_classification": us_transfer,
        "primary_model_changed_after_terminal_scoring": False,
        "secondary_model_scored": False,
        "terminal_target_values_accessed": True,
        "generated_maps": generated_maps,
        "required_outputs": [
            "predictions/terminal_predictions.parquet",
            "metrics/terminal_metrics.json",
            "regional/terminal_regional_metrics.csv",
            "metrics/terminal_weekly_metrics.csv",
            "us_transfer/terminal_us_positive_ranks.csv",
            "metrics/terminal_latitude_metrics.csv",
            "metrics/terminal_calibration.csv",
        ],
    }
    write_json(output / "manifests" / "terminal_evaluation_complete.json", complete)
    files = []
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name != "terminal_output_checksums.csv":
            files.append({"path": str(path.relative_to(output)), "sha256": sha256_file(path)})
    write_csv(output / "manifests" / "terminal_output_checksums.csv", files)
    return {"status": complete["status"], "generalization": generalization, "us_transfer": us_transfer, "freeze_manifest_sha256": freeze_checksum}


def main() -> int:
    parser = __import__("argparse").ArgumentParser()
    parser.add_argument("--phase", choices=("freeze", "score"), required=True)
    parser.add_argument("--model-output", type=Path, required=True)
    parser.add_argument("--terminal-output", type=Path, required=True)
    args = parser.parse_args()
    output_layout(args.terminal_output)
    data = load_inputs(args.model_output)
    arrays, _ = build_feature_arrays(data)
    array = arrays[MODEL_NAME]
    assert_primary_array(array)
    if args.phase == "freeze":
        result = write_freeze_phase(data, array, args.terminal_output)
        print(json.dumps({"status": result["status"], "freeze_manifest_sha256": result["manifest_sha256"], "terminal_targets_accessed": False}, indent=2))
    else:
        result = score_terminal_phase(data, array, args.terminal_output)
        print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
