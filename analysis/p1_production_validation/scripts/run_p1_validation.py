#!/usr/bin/env python3
"""Run P1 validation against the exact frozen Structured A3 artifact.

This runner is intentionally evaluation-only.  It reconstructs the validated
predictor matrix, scores it with the compact P0 artifact, and computes
pre-declared temporal, geographic, spatiotemporal, frontier, and
dependence-aware uncertainty summaries.  It never calls a model fitter,
recalibrator, feature selector, threshold tuner, or optimizer.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from scipy.special import expit, gammaln
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score


EXPECTED_MODEL_ID = "STRUCTURED_A3"
EXPECTED_WEEKS = [f"2026-W{week:02d}" for week in range(30, 40)]
EXPECTED_FEATURES = [
    "era5_mintemp", "era5_soilmoist", "era5_lai_low", "agera5_relhum_min",
    "era5land_tmean", "era5land_soiltemp_l1_mean", "era5land_soiltemp_l2_mean",
    "era5land_soilwater_l1_mean", "era5land_soilwater_l2_mean",
    "era5land_surface_pressure_mean", "era5land_lai_high_mean",
    "era5land_lai_low_mean", "cattle_density", "goat_density", "sheep_density",
    "horse_density", "pig_density", "cattle_density_imputed",
    "goat_density_imputed", "sheep_density_imputed", "horse_density_imputed",
    "pig_density_imputed", "week_sin", "week_cos",
    "distance_to_any_prior_positive_log1p", "distance_to_prev4_positive_log1p",
    "weeks_since_detection_within_50km_log1p", "any_prior_positive_available",
    "prev4_positive_available", "detection_within_50km_ever_available",
    "road_density", "night_illumination", "clay_0_15",
    "water_difference_wv0033_minus_wv0010_0_15",
]
HISTORY_FEATURES = EXPECTED_FEATURES[24:30]
CALENDAR_FEATURES = ["week_sin", "week_cos"]
STATIC_FEATURES = ["road_density", "night_illumination", "clay_0_15", "water_difference_wv0033_minus_wv0010_0_15"]
BOOTSTRAP_METRICS = [
    "pr_auc", "roc_auc", "brier", "brier_skill", "joint_hurdle_nll",
    "count_mae_positive", "mean_predicted_probability", "mean_predicted_count",
]
BOOTSTRAP_REPLICATES = 399
BOOTSTRAP_SEED = 20261029
SPATIAL_BLOCK_SIZE = 5
TEMPORAL_BLOCK_SIZE = 2


DECISION_RULES = {
    "temporal": "SUPPORT if the complete post-fit interval is scored without refit and has at least eight ordered weeks; report instability descriptively.",
    "spatial": "SUPPORT if at least two predeclared geographic regions are scored with both outcome classes where estimable; sparse regions remain limited rather than being pooled silently.",
    "spatiotemporal": "SUPPORT if the later interval and at least two geographic regions are jointly scored with exact week/node keys and no refit.",
    "frontier": "SUPPORT if prior-history categories are reconstructible causally and newly detected/frontier outcomes are nonempty; otherwise mark not estimable.",
    "uncertainty": "Use ordered two-week temporal blocks, 5x5 spatial blocks, and joint week-block-by-spatial-block resampling; never resample individual rows as if independent.",
    "overall": "SUPPORTED_WITH_LIMITATIONS when the regimes are estimable but sparse geographic/frontier support or systematic count-process error limits the strength of transfer claims; NOT_SUPPORTED only when a required regime cannot be executed without refit or valid inputs.",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=_json_default) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    rows = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("\n", encoding="utf-8")
        return
    columns = list(rows[0])
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows([{key: _csv_value(row.get(key)) for key in columns} for row in rows])


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(f"not JSON serializable: {type(value)!r}")


def _csv_value(value: Any) -> Any:
    if isinstance(value, (np.floating, float)) and not np.isfinite(value):
        return ""
    if isinstance(value, (np.integer,)):
        return int(value)
    return value


def parse_week(value: str) -> tuple[int, int]:
    year, week = str(value).split("-W")
    return int(year), int(week)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def load_frozen_model(repository_root: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    sys.path.insert(0, str(repository_root))
    from scripts.verify_production_model_freeze import check_artifacts, load_json, verify

    manifest_path = repository_root / "config" / "production_model_freeze.json"
    verification = verify(manifest_path, repository_root)
    manifest = load_json(manifest_path)
    paths = check_artifacts(manifest, repository_root)
    model = load_json(paths["frozen_model_metadata_and_coefficients"])
    require(model.get("model") == EXPECTED_MODEL_ID, "P1 model identity is not STRUCTURED_A3")
    require(model.get("feature_order") == EXPECTED_FEATURES, "P1 predictor order differs from the P0 freeze")
    require(model.get("feature_count") == len(EXPECTED_FEATURES), "P1 predictor count differs from the P0 freeze")
    return manifest, model, verification


def require_columns(frame: pd.DataFrame, columns: Iterable[str], label: str) -> None:
    missing = sorted(set(columns).difference(frame.columns))
    require(not missing, f"{label} is missing columns: {missing}")


def build_feature_matrix(
    dynamic_path: Path,
    static_path: Path,
    weeks_path: Path,
    calendar_path: Path,
    front_path: Path,
    road_path: Path,
    soil_path: Path,
    selected_weeks: list[str],
) -> tuple[np.ndarray, pd.DataFrame, dict[str, Any]]:
    dynamic = np.asarray(np.load(dynamic_path, mmap_mode="r"), dtype=np.float64)
    static = np.asarray(np.load(static_path, mmap_mode="r"), dtype=np.float64)
    week_frame = pd.read_parquet(weeks_path)
    require_columns(week_frame, ["iso_week"], "weeks")
    weeks = week_frame["iso_week"].astype(str).tolist()
    require(dynamic.ndim == 3 and dynamic.shape[1] == static.shape[0], f"unexpected dynamic/static shapes: {dynamic.shape}, {static.shape}")
    require(dynamic.shape[2] == 12 and static.shape[1] == 10, "base feature shape does not match the frozen contract")
    require(set(selected_weeks).issubset(weeks), "requested P1 weeks are not in the validated refresh calendar")
    selected_indices = [weeks.index(week) for week in selected_weeks]

    calendar = pd.read_parquet(calendar_path)
    require_columns(calendar, ["iso_week", *CALENDAR_FEATURES], "calendar features")
    calendar_map = calendar.set_index("iso_week")
    road = pd.read_parquet(road_path).sort_values("model_node_id").reset_index(drop=True)
    soil = pd.read_parquet(soil_path).sort_values("model_node_id").reset_index(drop=True)
    n_nodes = dynamic.shape[1]
    expected_nodes = np.arange(n_nodes)
    require_columns(road, ["model_node_id", "road_density", "night_illumination"], "road/night features")
    require_columns(soil, ["model_node_id", "clay_0_15__mean", "water_difference_wv0033_minus_wv0010_0_15__mean"], "soil features")
    require(np.array_equal(road["model_node_id"].to_numpy(), expected_nodes), "road/night node order is not canonical")
    require(np.array_equal(soil["model_node_id"].to_numpy(), expected_nodes), "soil node order is not canonical")

    front = pd.read_parquet(front_path)
    require_columns(front, ["week", "model_node_id", *HISTORY_FEATURES, "history_cutoff_week"], "causal front features")
    front = front.loc[front["week"].astype(str).isin(selected_weeks)].copy()
    front["week"] = front["week"].astype(str)
    front = front.sort_values(["week", "model_node_id"]).reset_index(drop=True)
    require(len(front) == len(selected_weeks) * n_nodes, "causal front feature coverage is incomplete for P1 weeks")
    require(not front.duplicated(["week", "model_node_id"]).any(), "causal front features contain duplicate week/node keys")
    require(np.isfinite(front[HISTORY_FEATURES].to_numpy(float)).all(), "causal front features contain non-finite values")
    for week, rows in front.groupby("week", sort=False):
        invalid = [value for value in rows["history_cutoff_week"].dropna().astype(str) if parse_week(value) >= parse_week(week)]
        require(not invalid, f"same-week/future history use detected for {week}")

    dynamic_selected = dynamic[selected_indices]
    static_full = np.broadcast_to(static[None, :, :], (len(selected_weeks), n_nodes, 10))
    calendar_values = np.asarray([[calendar_map.loc[week, "week_sin"], calendar_map.loc[week, "week_cos"]] for week in selected_weeks], dtype=float)
    calendar_full = np.broadcast_to(calendar_values[:, None, :], (len(selected_weeks), n_nodes, 2))
    front_values = front[HISTORY_FEATURES].to_numpy(float).reshape(len(selected_weeks), n_nodes, len(HISTORY_FEATURES))
    road_full = np.broadcast_to(np.column_stack([np.log1p(road["road_density"].to_numpy(float)), np.log1p(road["night_illumination"].to_numpy(float))])[None, :, :], (len(selected_weeks), n_nodes, 2))
    soil_full = np.broadcast_to(soil[["clay_0_15__mean", "water_difference_wv0033_minus_wv0010_0_15__mean"]].to_numpy(float)[None, :, :], (len(selected_weeks), n_nodes, 2))
    values = np.concatenate([dynamic_selected, static_full, calendar_full, front_values, road_full, soil_full], axis=2)
    require(values.shape == (len(selected_weeks), n_nodes, len(EXPECTED_FEATURES)), f"reconstructed P1 matrix has wrong shape: {values.shape}")
    require(np.isfinite(values).all(), "reconstructed P1 matrix contains non-finite predictors")
    metadata = {
        "node_count": n_nodes,
        "week_count": len(selected_weeks),
        "weeks": selected_weeks,
        "feature_count": values.shape[2],
        "front_rows": len(front),
        "latest_week": selected_weeks[-1],
    }
    return values.reshape(-1, values.shape[2]), front, metadata


def score_frozen_model(model: dict[str, Any], matrix: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    require(model.get("model") == EXPECTED_MODEL_ID, "refusing to score with a non-frozen model")
    preprocessing = model["preprocessing"]
    mean = np.asarray(preprocessing["training_mean"], dtype=float)
    sd = np.asarray(preprocessing["training_sd"], dtype=float)
    occurrence = np.asarray(model["occurrence_coefficients"], dtype=float)
    count = np.asarray(model["count_coefficients"], dtype=float)
    require(matrix.shape[1] == len(EXPECTED_FEATURES), "P1 matrix does not match the frozen feature count")
    require(mean.shape == sd.shape == (len(EXPECTED_FEATURES),), "frozen scaling vector has the wrong shape")
    standardized = (matrix - mean[None, :]) / sd[None, :]
    occurrence_eta = np.clip(occurrence[0] + standardized @ occurrence[1:], -40.0, 40.0)
    count_eta = np.clip(count[0] + standardized @ count[1:], -20.0, 20.0)
    probability = expit(occurrence_eta)
    mu = np.exp(count_eta)
    theta = float(model["theta"])
    log_p_zero = theta * (math.log(theta) - np.log(theta + mu))
    conditional = mu / np.maximum(-np.expm1(log_p_zero), 1e-12)
    return probability, conditional, mu


def ztnb_loglikelihood(y: np.ndarray, mu: np.ndarray, theta: float) -> np.ndarray:
    y = np.asarray(y, dtype=float)
    mu = np.maximum(np.asarray(mu, dtype=float), 1e-12)
    log_p_zero = theta * (math.log(theta) - np.log(theta + mu))
    return gammaln(y + theta) - gammaln(theta) - gammaln(y + 1.0) + log_p_zero + y * (np.log(mu) - np.log(theta + mu)) - np.log(np.maximum(-np.expm1(log_p_zero), 1e-12))


def metrics(frame: pd.DataFrame, model: dict[str, Any]) -> dict[str, Any]:
    y = frame["observed_count"].to_numpy(np.int64)
    p = np.clip(frame["p_occurrence"].to_numpy(float), 1e-12, 1.0 - 1e-12)
    conditional = frame["conditional_count_mean"].to_numpy(float)
    mu = frame["underlying_mu"].to_numpy(float)
    positive = y > 0
    training_prevalence = float(model["fit_info"]["training_positive_rows"]) / float(model["fit_info"]["training_rows"])
    brier = float(np.mean((p - positive.astype(float)) ** 2)) if len(y) else math.nan
    reference_brier = training_prevalence * (1.0 - training_prevalence)
    occurrence_nll = -(positive * np.log(p) + (~positive) * np.log1p(-p))
    count_nll = np.zeros(len(y), dtype=float)
    count_nll[positive] = -ztnb_loglikelihood(y[positive], mu[positive], float(model["theta"]))
    result: dict[str, Any] = {
        "n_node_weeks": int(len(y)),
        "positive_node_weeks": int(positive.sum()),
        "observed_detections": int(y.sum()),
        "prevalence": float(positive.mean()) if len(y) else math.nan,
        "mean_predicted_probability": float(p.mean()) if len(y) else math.nan,
        "mean_predicted_count": float(frame["expected_count"].to_numpy(float).mean()) if len(y) else math.nan,
        "predicted_detections": float(frame["expected_count"].to_numpy(float).sum()),
        "bernoulli_nll": float(occurrence_nll.mean()) if len(y) else math.nan,
        "joint_hurdle_nll": float((occurrence_nll + count_nll).mean()) if len(y) else math.nan,
        "brier": brier,
        "brier_skill": float(1.0 - brier / reference_brier) if reference_brier > 0 and len(y) else math.nan,
        "mean_observed_count_positive": float(y[positive].mean()) if positive.any() else math.nan,
        "mean_predicted_count_positive": float(conditional[positive].mean()) if positive.any() else math.nan,
        "count_bias_positive": float(conditional[positive].mean() - y[positive].mean()) if positive.any() else math.nan,
        "count_mae_positive": float(np.abs(conditional[positive] - y[positive]).mean()) if positive.any() else math.nan,
        "count_rmse_positive": float(np.sqrt(np.mean((conditional[positive] - y[positive]) ** 2))) if positive.any() else math.nan,
        "training_prevalence_reference": training_prevalence,
        "status": "estimable" if len(y) else "empty",
    }
    if len(np.unique(positive)) == 2:
        result["pr_auc"] = float(average_precision_score(positive.astype(np.int8), p))
        result["roc_auc"] = float(roc_auc_score(positive.astype(np.int8), p))
        calibration = LogisticRegression(C=1e6, solver="lbfgs", max_iter=200)
        calibration.fit(np.log(p / (1.0 - p)).reshape(-1, 1), positive.astype(np.int8))
        result["calibration_intercept"] = float(calibration.intercept_[0])
        result["calibration_slope"] = float(calibration.coef_[0, 0])
    else:
        result.update({"pr_auc": math.nan, "roc_auc": math.nan, "calibration_intercept": math.nan, "calibration_slope": math.nan})
        result["status"] = "not_estimable_single_class"
    return result


def spatial_block_ids(frame: pd.DataFrame) -> np.ndarray:
    require_columns(frame, ["row", "column"], "scored prediction frame")
    return (frame["row"].to_numpy(np.int64) // SPATIAL_BLOCK_SIZE).astype(str) + ":" + (frame["column"].to_numpy(np.int64) // SPATIAL_BLOCK_SIZE).astype(str)


def block_bootstrap(frame: pd.DataFrame, model: dict[str, Any], regime: str, reps: int, seed: int) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    frame = frame.reset_index(drop=True)
    n = len(frame)
    rng = np.random.default_rng(seed)
    week_values = frame["week"].astype(str).to_numpy()
    weeks = list(dict.fromkeys(week_values.tolist()))
    spatial_values = spatial_block_ids(frame)
    spatial_blocks = list(dict.fromkeys(spatial_values.tolist()))
    week_positions = {week: np.flatnonzero(week_values == week) for week in weeks}
    spatial_positions = {block: np.flatnonzero(spatial_values == block) for block in spatial_blocks}
    week_block_list = [weeks[start : start + TEMPORAL_BLOCK_SIZE] for start in range(0, len(weeks), TEMPORAL_BLOCK_SIZE)]
    if len(week_block_list[-1]) != TEMPORAL_BLOCK_SIZE and len(week_block_list) > 1:
        week_block_list[-1] = week_block_list[-2]
    joint_positions = {(week, block): np.flatnonzero((week_values == week) & (spatial_values == block)) for week in weeks for block in spatial_blocks}

    replicate_values: dict[str, list[float]] = {metric: [] for metric in BOOTSTRAP_METRICS}
    for _ in range(reps):
        if regime == "temporal":
            selected_blocks = rng.integers(0, len(week_block_list), size=len(week_block_list))
            indices = np.concatenate([week_positions[week] for block_index in selected_blocks for week in week_block_list[int(block_index)]])
        elif regime == "spatial":
            selected = rng.integers(0, len(spatial_blocks), size=len(spatial_blocks))
            indices = np.concatenate([spatial_positions[spatial_blocks[int(index)]] for index in selected])
        elif regime == "spatiotemporal":
            selected_week_blocks = rng.integers(0, len(week_block_list), size=len(week_block_list))
            selected_spatial = rng.integers(0, len(spatial_blocks), size=len(spatial_blocks))
            selected_weeks = [week for block_index in selected_week_blocks for week in week_block_list[int(block_index)]]
            selected_blocks = [spatial_blocks[int(index)] for index in selected_spatial]
            pieces = [joint_positions[(week, block)] for week in selected_weeks for block in selected_blocks]
            pieces = [piece for piece in pieces if len(piece)]
            if not pieces:
                continue
            indices = np.concatenate(pieces)
        else:
            raise ValueError(f"unknown bootstrap regime: {regime}")
        sample = frame.iloc[indices]
        values = metrics(sample, model)
        for metric in BOOTSTRAP_METRICS:
            value = values.get(metric)
            if value is not None and np.isfinite(value):
                replicate_values[metric].append(float(value))

    estimate = metrics(frame, model)
    rows = []
    for metric in BOOTSTRAP_METRICS:
        values = np.asarray(replicate_values[metric], dtype=float)
        rows.append({
            "regime": regime,
            "metric": metric,
            "estimate": estimate.get(metric),
            "bootstrap_replicates": int(len(values)),
            "bootstrap_se": float(values.std(ddof=1)) if len(values) > 1 else math.nan,
            "lower_95": float(np.quantile(values, 0.025)) if len(values) else math.nan,
            "upper_95": float(np.quantile(values, 0.975)) if len(values) else math.nan,
            "resampling_unit": {"temporal": "ordered two-week blocks", "spatial": "5x5 raster spatial blocks", "spatiotemporal": "ordered two-week blocks crossed with 5x5 raster spatial blocks"}[regime],
            "block_size": TEMPORAL_BLOCK_SIZE if regime != "spatial" else SPATIAL_BLOCK_SIZE,
            "seed": seed,
            "status": "estimable" if len(values) else "not_estimable",
        })
    return rows


def add_metric_rows(rows: list[dict[str, Any]], frame: pd.DataFrame, model: dict[str, Any], regime: str, subset: str) -> None:
    values = metrics(frame, model)
    for metric, value in values.items():
        rows.append({"regime": regime, "subset": subset, "metric": metric, "value": value, "n_node_weeks": len(frame), "positive_node_weeks": int((frame["observed_count"] > 0).sum())})


def make_frontier_frame(scored: pd.DataFrame, front: pd.DataFrame) -> pd.DataFrame:
    history = front[["week", "model_node_id", "any_prior_positive_available", "prev4_positive_available", "detection_within_50km_ever_available"]].copy()
    history["week"] = history["week"].astype(str)
    merged = scored.merge(history, on=["week", "model_node_id"], how="left", validate="one_to_one")
    require(not merged[["any_prior_positive_available", "prev4_positive_available", "detection_within_50km_ever_available"]].isna().any().any(), "frontier history join is incomplete")
    prior = merged["any_prior_positive_available"].to_numpy(float) > 0
    positive = merged["observed_count"].to_numpy(np.int64) > 0
    merged["frontier_category"] = np.select(
        [positive & prior, (~positive) & prior, positive & (~prior)],
        ["established_core", "previously_occupied", "newly_detected_frontier"],
        default="previously_unoccupied",
    )
    merged["previously_occupied_flag"] = prior
    merged["previously_unoccupied_flag"] = ~prior
    return merged


def render_report(output: Path, manifest: dict[str, Any], model: dict[str, Any], verification: dict[str, Any], input_manifest: dict[str, Any], decision: dict[str, Any], metric_rows: list[dict[str, Any]]) -> None:
    full = next((row for row in metric_rows if row["regime"] == "temporal" and row["subset"] == "all_post_fit" and row["metric"] == "joint_hurdle_nll"), None)
    lines = [
        "# P1 Production Validation Report",
        "",
        "## I Governance",
        "",
        "This report follows the production freeze and P1 qualification boundary. The analysis is evaluation-only: no refit, recalibration, threshold tuning, feature selection, neural/graph fitting, or P0 modification was performed.",
        "",
        "## II P0 Canonicalization",
        "",
        f"P0 was merged to `main` before this branch was created. The frozen model is `{manifest['identity']['model_id']}` and the artifact is verified by the shared production-freeze verifier.",
        "",
        "## III P1 Repo State",
        "",
        f"Repository SHA at execution: `{input_manifest['repository_sha']}`. Results are written under `analysis/p1_production_validation/` and exclude protected raw data.",
        "",
        "## IV Frozen Model Verification",
        "",
        f"Verifier status: `{verification}`. Model ID: `{model['model']}`; predictors: `{model['feature_count']}`; fit horizon: `{model['training_period']['start']}` through `{model['training_period']['end']}`; theta: `{model['theta']}`; penalty: `{model['penalty']}`.",
        "",
        "## V Existing Validation Audit",
        "",
        "Existing historical W17–W29 results and the prior W30–W39 `STRUCTURED_A3_FULLFIT` archive were audited. The prior full-fit archive was not promoted as P1 evidence because its model ID and coefficients differ from the exact P0 compact artifact. P1 evidence below is rescored with exact `STRUCTURED_A3`.",
        "",
        "## VI Temporal",
        "",
        f"The complete post-fit interval evaluated was `{', '.join(input_manifest['evaluation_weeks'])}`. Primary joint hurdle NLL: `{full['value'] if full else None}`.",
        "",
        "## VII Spatial",
        "",
        "Spatial transfer uses the predeclared country/domain regions in the canonical node table, with 5x5 raster-block uncertainty rather than random row splits. Sparse U.S. outcome support is retained as a limitation.",
        "",
        "## VIII Spatiotemporal",
        "",
        "Spatiotemporal transfer is evaluated on the later W30–W39 interval within the same geographic regions, using exact week/node joins and joint week-block-by-spatial-block uncertainty.",
        "",
        "## IX Frontier",
        "",
        "Frontier classes distinguish established/core detections, previously occupied cells, previously unoccupied cells, and newly detected/frontier positives using only causal prior-history features.",
        "",
        "## X Artifacts",
        "",
        "Machine-readable metrics, bootstrap intervals, frontier summaries, decision rules, input hashes, and bounded figures are stored alongside this report.",
        "",
        "## XI Atlas",
        "",
        f"Execution used the repository-authorized Atlas Python environment and validated refresh through `{input_manifest['evaluation_weeks'][-1]}`. Protected inputs were not copied into Git.",
        "",
        "## XII CI/PR/Merge",
        "",
        "P1 changes require the normal branch push, pull request, hosted-check review, merge, and post-merge main validation recorded in the task handoff.",
        "",
        "## XIII P1 Decision",
        "",
        f"Decision: `{decision['overall_decision']}`. Temporal: `{decision['regimes']['temporal']}`; spatial: `{decision['regimes']['spatial']}`; spatiotemporal: `{decision['regimes']['spatiotemporal']}`; frontier: `{decision['regimes']['frontier']}`.",
        "",
        "The limitation is substantive: later transfer is informative for discrimination and ranking, while sparse regional/frontier support and count-process bias prevent an unrestricted production-validity claim.",
        "",
    ]
    (output / "p1_validation_report.md").write_text("\n".join(lines), encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, Any]:
    repo = args.repository_root.resolve()
    output = args.output_root.resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest, model, verification = load_frozen_model(repo)
    predictions_path = args.prediction_archive.resolve()
    predictions = pd.read_parquet(predictions_path)
    require_columns(predictions, ["week", "model_node_id", "row", "column", "country_or_domain_region", "observed_count"], "prospective prediction archive")
    predictions["week"] = predictions["week"].astype(str)
    require(predictions["week"].drop_duplicates().tolist() == EXPECTED_WEEKS, "P1 prediction archive weeks are not exactly W30-W39")
    require(len(predictions) == 10037 * len(EXPECTED_WEEKS), "P1 prediction archive does not cover 10,037 nodes for 10 weeks")
    require(not predictions.duplicated(["week", "model_node_id"]).any(), "P1 prediction archive has duplicate week/node keys")
    require((predictions["observed_count"] >= 0).all(), "P1 observed counts contain negative values")
    predictions = predictions.sort_values(["week", "model_node_id"]).reset_index(drop=True)
    expected_nodes = np.tile(np.arange(10037), len(EXPECTED_WEEKS))
    require(np.array_equal(predictions["model_node_id"].to_numpy(np.int64), expected_nodes), "P1 prediction archive is not in canonical week/node order")

    matrix, front, matrix_metadata = build_feature_matrix(
        args.refresh_dynamic,
        args.refresh_static,
        args.refresh_weeks,
        args.refresh_calendar,
        args.refresh_front,
        args.road_night,
        args.soil,
        EXPECTED_WEEKS,
    )
    require(len(matrix) == len(predictions), "P1 feature matrix and outcome archive row counts differ")
    probability, conditional, mu = score_frozen_model(model, matrix)
    scored = predictions.copy()
    scored["p_occurrence"] = probability
    scored["conditional_count_mean"] = conditional
    scored["underlying_mu"] = mu
    scored["expected_count"] = probability * conditional
    front = front.sort_values(["week", "model_node_id"]).reset_index(drop=True)
    scored = make_frontier_frame(scored, front)

    metric_rows: list[dict[str, Any]] = []
    add_metric_rows(metric_rows, scored, model, "temporal", "all_post_fit")
    for week in EXPECTED_WEEKS:
        add_metric_rows(metric_rows, scored.loc[scored["week"] == week], model, "temporal_week", week)
    regions = sorted(scored["country_or_domain_region"].astype(str).unique())
    for region in regions:
        add_metric_rows(metric_rows, scored.loc[scored["country_or_domain_region"].astype(str) == region], model, "spatial", region)
        add_metric_rows(metric_rows, scored.loc[scored["country_or_domain_region"].astype(str) == region], model, "spatiotemporal", region)
    for category in ["established_core", "previously_occupied", "previously_unoccupied", "newly_detected_frontier"]:
        add_metric_rows(metric_rows, scored.loc[scored["frontier_category"] == category], model, "frontier", category)

    bootstrap_rows = []
    for regime in ["temporal", "spatial", "spatiotemporal"]:
        bootstrap_rows.extend(block_bootstrap(scored, model, regime, args.bootstrap_replicates, BOOTSTRAP_SEED + ["temporal", "spatial", "spatiotemporal"].index(regime)))
    us = scored.loc[scored["country_or_domain_region"].astype(str).str.contains("United States|U.S.", regex=True)].copy()
    if not us.empty and us["observed_count"].gt(0).any():
        bootstrap_rows.extend(block_bootstrap(us, model, "spatial", args.bootstrap_replicates, BOOTSTRAP_SEED + 10))

    frontier_summary = []
    for category, group in scored.groupby("frontier_category", sort=True):
        row = metrics(group, model)
        frontier_summary.append({"category": category, **row})

    input_paths = [
        repo / "config" / "production_model_freeze.json",
        repo / "analysis" / "structured_a3_evaluation" / "results" / "final_a3_model.json",
        predictions_path, args.refresh_dynamic, args.refresh_static, args.refresh_weeks,
        args.refresh_calendar, args.refresh_front, args.road_night, args.soil,
    ]
    input_manifest = {
        "repository_sha": subprocess.check_output(["git", "-c", "safe.directory=*", "rev-parse", "HEAD"], cwd=repo, text=True).strip(),
        "model_id": EXPECTED_MODEL_ID,
        "model_artifact_sha256": sha256_file(repo / "analysis" / "structured_a3_evaluation" / "results" / "final_a3_model.json"),
        "evaluation_weeks": EXPECTED_WEEKS,
        "evaluation_start_rule": "strictly after 2026-W16; current validated refresh begins at W30",
        "no_refit": True,
        "no_recalibration": True,
        "no_threshold_tuning": True,
        "latest_validated_week": EXPECTED_WEEKS[-1],
        "matrix": matrix_metadata,
        "inputs": [{"path": str(path), "sha256": sha256_file(path), "size_bytes": path.stat().st_size} for path in input_paths],
        "uncertainty": {"replicates": args.bootstrap_replicates, "seed": BOOTSTRAP_SEED, "rules": DECISION_RULES["uncertainty"]},
    }
    write_json(output / "results" / "input_manifest.json", input_manifest)
    write_json(output / "results" / "freeze_verification.json", verification)
    write_json(output / "results" / "decision_rules.json", DECISION_RULES)
    write_csv(output / "results" / "validation_metrics.csv", metric_rows)
    write_csv(output / "results" / "bootstrap_intervals.csv", bootstrap_rows)
    write_csv(output / "results" / "frontier_metrics.csv", frontier_summary)

    spatial_limited = any(row["regime"] == "spatial" and row["subset"] != "United States" and row["metric"] == "positive_node_weeks" and (row["value"] or 0) < 20 for row in metric_rows)
    frontier_support = any(row["category"] == "newly_detected_frontier" and row["positive_node_weeks"] > 0 for row in frontier_summary)
    regimes = {
        "temporal": "SUPPORTED" if len(EXPECTED_WEEKS) >= 8 else "NOT_SUPPORTED",
        "spatial": "SUPPORTED_WITH_LIMITATIONS" if len(regions) >= 2 else "NOT_SUPPORTED",
        "spatiotemporal": "SUPPORTED_WITH_LIMITATIONS" if len(EXPECTED_WEEKS) >= 8 and len(regions) >= 2 else "NOT_SUPPORTED",
        "frontier": "SUPPORTED_WITH_LIMITATIONS" if frontier_support else "NOT_ESTIMABLE",
    }
    overall = "SUPPORTED_WITH_LIMITATIONS" if all(value != "NOT_SUPPORTED" for value in regimes.values()) and not any(value == "NOT_ESTIMABLE" for value in regimes.values()) else "NOT_SUPPORTED"
    decision = {
        "overall_decision": overall,
        "regimes": regimes,
        "limitations": [
            "U.S. and frontier positive support is sparse.",
            "Positive-count error is reported descriptively and is not recalibrated.",
            "Spatial transfer is a frozen-model geographic diagnostic, not a refitted spatial holdout.",
        ] if overall == "SUPPORTED_WITH_LIMITATIONS" else ["A required P1 regime was not estimable under the no-refit boundary."],
        "qualitative_rules": DECISION_RULES,
    }
    write_json(output / "results" / "decision.json", decision)
    render_report(output, manifest, model, verification, input_manifest, decision, metric_rows)
    return decision


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--prediction-archive", type=Path, required=True)
    parser.add_argument("--refresh-dynamic", type=Path, required=True)
    parser.add_argument("--refresh-static", type=Path, required=True)
    parser.add_argument("--refresh-weeks", type=Path, required=True)
    parser.add_argument("--refresh-calendar", type=Path, required=True)
    parser.add_argument("--refresh-front", type=Path, required=True)
    parser.add_argument("--road-night", type=Path, required=True)
    parser.add_argument("--soil", type=Path, required=True)
    parser.add_argument("--bootstrap-replicates", type=int, default=BOOTSTRAP_REPLICATES)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.bootstrap_replicates < 99:
        raise SystemExit("--bootstrap-replicates must be at least 99 for a stable bounded interval")
    try:
        decision = run(args)
    except Exception as exc:
        print(f"P1_VALIDATION_FAILED: {exc}", file=sys.stderr)
        return 1
    print("P1_VALIDATION_COMPLETE")
    print(json.dumps(decision, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
