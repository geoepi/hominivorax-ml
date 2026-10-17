#!/usr/bin/env python3
"""No-retuning, paired future evaluation entrypoint for frozen A3 and A4-S.

The command refuses to run without ``--no-refit``. It uses only rows strictly
after the frozen boundary, scores both models on the identical node-week set,
and never calls an optimizer or updates model parameters. ``--plan-only`` is
provided for the freeze stage when no eligible post-freeze observations exist.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


NODE_COUNT = 10_037
EXPECTED_WEEKS = tuple(f"2026-W{week:02d}" for week in range(30, 40))
FEATURES = [
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
HISTORY = FEATURES[24:30]
EPS = 1e-12


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def jsonable(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def parse_week(value: str) -> tuple[int, int]:
    year, week = value.split("-W")
    return int(year), int(week)


def assert_manifest(path: Path) -> tuple[dict[str, Any], str]:
    sidecar = path.with_name(path.name + ".sha256")
    if not path.exists() or not sidecar.exists():
        raise RuntimeError(f"missing immutable manifest or sidecar: {path}")
    actual = sha256_file(path)
    expected = sidecar.read_text(encoding="utf-8").split()[0]
    if actual != expected:
        raise RuntimeError(f"manifest checksum mismatch: {path}")
    return read_json(path), actual


def validate_contract(a3_manifest: Path, a3_model: Path, a4_manifest: Path, a4_json: Path, a4_npz: Path) -> dict[str, Any]:
    a3, a3_sha = assert_manifest(a3_manifest)
    a4, a4_sha = assert_manifest(a4_manifest)
    if a3["model"]["id"] != "STRUCTURED_A3" or a3["model"]["predictor_count"] != 34:
        raise RuntimeError("frozen A3 manifest is not the supported 34-predictor model")
    if a3["evaluation_guardrails"]["no_refit"] is not True:
        raise RuntimeError("frozen A3 manifest does not require no-refit evaluation")
    if a4["model"]["id"] != "STRUCTURED_A4S_CHALLENGER" or a4["model"]["status"] != "FROZEN_FOR_DEFERRED_INDEPENDENT_EVALUATION":
        raise RuntimeError("A4-S manifest is not a frozen provisional challenger")
    if a4["model"]["predictor_count"] != 34 or a4["model"]["predictor_order"] != FEATURES:
        raise RuntimeError("A4-S predictor contract changed")
    if a4["evaluation_boundary"]["challenger_freeze_week"] != "2026-W42" or a4["evaluation_boundary"]["evaluation_eligible_week"] != "2026-W43":
        raise RuntimeError("A4-S evaluation boundary changed")
    if a4["scientific_caveats"]["sit_covariates_included"] or a4["scientific_caveats"]["reporting_effort_covariates_available"]:
        raise RuntimeError("SIT/reporting covariates are forbidden in the frozen challenger")
    if a4["evaluation_restrictions"]["no_refit_after_freeze"] is not True:
        raise RuntimeError("A4-S no-refit restriction is missing")
    artifact = a4["artifact"]
    for path, key in ((a4_json, "model_json"), (a4_npz, "model_npz")):
        if sha256_file(path) != artifact["sha256"][key]:
            raise RuntimeError(f"A4-S artifact checksum mismatch: {path}")
    model = read_json(a3_model)
    if model.get("model") != "STRUCTURED_A3" or model.get("feature_count") != 34:
        raise RuntimeError("A3 model artifact is not the frozen 34-predictor model")
    return {"a3": a3, "a3_manifest_sha256": a3_sha, "a4s": a4, "a4s_manifest_sha256": a4_sha, "a3_model_sha256": sha256_file(a3_model)}


def build_raw_features(model_output: Path, front_features: Path, soil_features: Path, anthropogenic_features: Path) -> tuple[np.ndarray, np.ndarray, pd.DataFrame, list[str]]:
    raw = model_output / "raw"
    dynamic = np.asarray(np.load(raw / "dynamic_features.npy", mmap_mode="r"), dtype=np.float64)
    static = np.asarray(np.load(raw / "static_features.npy", mmap_mode="r"), dtype=np.float64)
    counts = np.asarray(np.load(raw / "targets_count.npy", mmap_mode="r"), dtype=np.int64)
    weeks = pd.read_parquet(raw / "weeks.parquet")
    labels = weeks["iso_week"].astype(str).tolist()
    n_weeks = len(labels)
    if dynamic.shape[:2] != (n_weeks, NODE_COUNT) or counts.shape != (n_weeks, NODE_COUNT) or static.shape != (NODE_COUNT, 10):
        raise RuntimeError("future scoring bundle shape contract failed")
    nodes = pd.read_parquet(raw / "nodes.parquet").sort_values("model_node_id").reset_index(drop=True)
    if not np.array_equal(nodes["model_node_id"].to_numpy(np.int64), np.arange(NODE_COUNT)):
        raise RuntimeError("future node IDs are not canonical")
    calendar = pd.read_parquet(raw / "calendar_features.parquet")[["week_sin", "week_cos"]].to_numpy(np.float64)
    front_columns = ["week_index", "model_node_id", *HISTORY]
    front = pd.read_parquet(front_features, columns=front_columns).sort_values(["week_index", "model_node_id"]).reset_index(drop=True)
    if len(front) != n_weeks * NODE_COUNT:
        raise RuntimeError("front features do not cover the scoring horizon")
    if not np.array_equal(front["model_node_id"].to_numpy(np.int64), np.tile(np.arange(NODE_COUNT), n_weeks)):
        raise RuntimeError("front feature node ordering is not canonical")
    front_values = front[HISTORY].to_numpy(np.float64).reshape(n_weeks, NODE_COUNT, 6)
    density = np.log1p(static[:, :5])
    base = np.concatenate([
        dynamic,
        np.broadcast_to(density[None, :, :], (n_weeks, NODE_COUNT, 5)),
        np.broadcast_to(static[:, 5:][None, :, :], (n_weeks, NODE_COUNT, 5)),
        np.broadcast_to(calendar[:, None, :], (n_weeks, NODE_COUNT, 2)),
        front_values,
    ], axis=2)
    soil = pd.read_parquet(soil_features).sort_values("model_node_id")
    anthro = pd.read_parquet(anthropogenic_features).sort_values("model_node_id")
    soil_cols = ["clay_0_15" if "clay_0_15" in soil.columns else "clay_0_15__mean", "water_difference_wv0033_minus_wv0010_0_15" if "water_difference_wv0033_minus_wv0010_0_15" in soil.columns else "water_difference_wv0033_minus_wv0010_0_15__mean"]
    added = nodes[["model_node_id"]].merge(anthro[["model_node_id", "road_density", "night_illumination"]], on="model_node_id", validate="one_to_one").merge(soil[["model_node_id", *soil_cols]], on="model_node_id", validate="one_to_one")
    added = added[["road_density", "night_illumination", *soil_cols]].to_numpy(np.float64)
    added[:, :2] = np.log1p(added[:, :2])
    features = np.concatenate([base, np.broadcast_to(added[None, :, :], (n_weeks, NODE_COUNT, 4))], axis=2)
    if features.shape != (n_weeks, NODE_COUNT, 34) or not np.isfinite(features).all():
        raise RuntimeError("future feature matrix is invalid")
    return features, counts, nodes, labels


def logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(np.asarray(p, dtype=np.float64), EPS, 1.0 - EPS)
    return np.log(p) - np.log1p(-p)


def predict(beta_occ: np.ndarray, beta_count: np.ndarray, theta: float, x: np.ndarray, occurrence_effect: np.ndarray | None = None, count_effect: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    design = np.column_stack([np.ones(len(x)), x])
    p = 1.0 / (1.0 + np.exp(-np.clip(design @ beta_occ, -40, 40)))
    mu = np.exp(np.clip(design @ beta_count, -20, 20))
    if occurrence_effect is not None:
        p = 1.0 / (1.0 + np.exp(-np.clip(logit(p) + np.tile(occurrence_effect, len(x) // NODE_COUNT), -40, 40)))
    if count_effect is not None:
        mu = mu * np.exp(np.tile(count_effect, len(x) // NODE_COUNT))
    p0 = np.exp(theta * (math.log(theta) - np.log(theta + mu)))
    conditional = mu / np.maximum(-np.expm1(theta * (math.log(theta) - np.log(theta + mu))), EPS)
    return p, conditional, mu


def calibration(p: np.ndarray, y: np.ndarray) -> tuple[float | None, float | None]:
    if len(y) < 20 or len(np.unique(y)) < 2:
        return None, None
    z = np.column_stack([np.ones(len(p)), logit(p)])
    beta = np.array([0.0, 1.0], dtype=np.float64)
    for _ in range(60):
        q = 1.0 / (1.0 + np.exp(-np.clip(z @ beta, -40, 40)))
        gradient = z.T @ (q - y)
        weight = q * (1.0 - q)
        hessian = z.T @ (z * weight[:, None])
        try:
            step = np.linalg.solve(hessian + np.eye(2) * 1e-10, gradient)
        except np.linalg.LinAlgError:
            return None, None
        beta -= step
        if np.max(np.abs(step)) < 1e-8:
            return float(beta[0]), float(beta[1])
    return None, None


def pr_auc(y: np.ndarray, p: np.ndarray) -> float | None:
    if not np.any(y):
        return None
    order = np.argsort(-p, kind="mergesort")
    yy = y[order].astype(np.float64)
    precision = np.cumsum(yy) / np.arange(1, len(yy) + 1)
    return float(np.sum(precision[yy == 1]) / np.sum(yy))


def roc_auc(y: np.ndarray, p: np.ndarray) -> float | None:
    pos = y.astype(bool)
    neg = ~pos
    if not pos.any() or not neg.any():
        return None
    order = np.argsort(p, kind="mergesort")
    ranks = np.empty(len(p), dtype=np.float64)
    ranks[order] = np.arange(1, len(p) + 1)
    return float((ranks[pos].sum() - pos.sum() * (pos.sum() + 1) / 2) / (pos.sum() * neg.sum()))


def zt_nll(y: np.ndarray, mu: np.ndarray, theta: float) -> float | None:
    if len(y) == 0:
        return None
    from math import lgamma
    mu = np.maximum(mu, EPS)
    denom = theta + mu
    log_p0 = theta * (math.log(theta) - np.log(denom))
    log_positive = np.log(np.maximum(-np.expm1(log_p0), EPS))
    logpmf = np.array([lgamma(float(v) + theta) - lgamma(theta) - lgamma(float(v) + 1) for v in y]) + log_p0 + y * (np.log(mu) - np.log(denom))
    return float(-np.mean(logpmf - log_positive))


def metrics(y_count: np.ndarray, p: np.ndarray, conditional: np.ndarray, mu: np.ndarray, theta: float, reference_prevalence: float) -> dict[str, Any]:
    y = (y_count > 0).astype(np.int8)
    positive = y.astype(bool)
    joint_log = np.where(y == 0, np.log(np.maximum(1.0 - p, EPS)), np.log(np.maximum(p, EPS)))
    if positive.any():
        mu_pos = mu[positive]
        count_y = y_count[positive].astype(np.float64)
        denom = theta + mu_pos
        log_p0 = theta * (math.log(theta) - np.log(denom))
        logpmf = np.array([math.lgamma(float(v) + theta) - math.lgamma(theta) - math.lgamma(float(v) + 1) for v in count_y]) + log_p0 + count_y * (np.log(mu_pos) - np.log(denom))
        joint_log[positive] += logpmf - np.log(np.maximum(-np.expm1(log_p0), EPS))
    result = {
        "node_weeks": int(len(y)), "positive_node_weeks": int(y.sum()), "prevalence": float(y.mean()),
        "mean_predicted_probability": float(p.mean()), "brier": float(np.mean((p - y) ** 2)),
        "brier_skill": float(1.0 - np.mean((p - y) ** 2) / max(reference_prevalence * (1 - reference_prevalence), EPS)),
        "pr_auc": pr_auc(y, p), "roc_auc": roc_auc(y, p),
        "calibration_intercept": calibration(p, y)[0], "calibration_slope": calibration(p, y)[1],
        "joint_hurdle_nll": float(-np.mean(joint_log)), "positive_count_nll": zt_nll(y_count, mu_pos, theta) if positive.any() else None,
        "observed_detections": int(y_count.sum()), "predicted_expected_detections": float(np.sum(p * conditional)),
        "observed_positive_mean": float(y_count[positive].mean()) if positive.any() else None,
        "predicted_conditional_mean": float(conditional[positive].mean()) if positive.any() else None,
        "count_bias": float(conditional[positive].mean() - y_count[positive].mean()) if positive.any() else None,
        "count_mae": float(np.mean(np.abs(conditional[positive] - y_count[positive]))) if positive.any() else None,
        "count_rmse": float(np.sqrt(np.mean((conditional[positive] - y_count[positive]) ** 2))) if positive.any() else None,
    }
    return result


def moran(values: np.ndarray, source: np.ndarray, target: np.ndarray, permutations: int = 199, seed: int = 20261017) -> tuple[float | None, float | None]:
    x = np.asarray(values, dtype=np.float64)
    if len(x) != NODE_COUNT or not np.isfinite(x).all():
        return None, None
    centered = x - x.mean()
    denominator = float(np.dot(centered, centered))
    if denominator <= 0 or len(source) == 0:
        return None, None
    def score(v: np.ndarray) -> float:
        c = v - v.mean()
        return float((NODE_COUNT / len(source)) * np.sum(c[source] * c[target]) / max(np.dot(c, c), EPS))
    observed = score(x)
    rng = np.random.default_rng(seed)
    null = np.array([score(rng.permutation(x)) for _ in range(permutations)])
    return observed, float((1 + np.sum(np.abs(null) >= abs(observed))) / (permutations + 1))


def ranking(p: np.ndarray, y_count: np.ndarray, labels: list[str], nodes: pd.DataFrame) -> dict[str, Any]:
    us = nodes["country_or_domain_region"].astype(str).eq("U.S.-to-40N").to_numpy()
    percentiles: list[float] = []
    captures: dict[str, dict[str, Any]] = {}
    for week_index, week in enumerate(labels):
        mask = us
        values = p[week_index * NODE_COUNT:(week_index + 1) * NODE_COUNT][mask]
        obs = y_count[week_index * NODE_COUNT:(week_index + 1) * NODE_COUNT][mask] > 0
        if not len(values):
            continue
        order = np.argsort(values, kind="mergesort")
        ranks = np.empty(len(values), dtype=np.int64)
        ranks[order] = np.arange(1, len(values) + 1)
        percentiles.extend((100 * ranks[obs] / len(values)).tolist())
        for k in (0.01, 0.05, 0.10, 0.20):
            n = max(1, int(math.ceil(k * len(values))))
            top = order[-n:]
            entry = captures.setdefault(str(k), {"flagged_node_weeks": 0, "positives_captured": 0, "total_positive": 0})
            entry["flagged_node_weeks"] += n
            entry["positives_captured"] += int(obs[top].sum())
            entry["total_positive"] += int(obs.sum())
    positive_percentiles = np.asarray(percentiles, dtype=np.float64)
    return {
        "us_positive_node_weeks": int(len(positive_percentiles)),
        "us_unique_positive_nodes": int(np.unique(np.flatnonzero(us & (np.asarray(y_count).reshape(-1, NODE_COUNT).sum(axis=0) > 0))).size) if len(y_count) else 0,
        "us_median_positive_percentile": float(np.median(positive_percentiles)) if len(positive_percentiles) else None,
        "us_mean_positive_percentile": float(np.mean(positive_percentiles)) if len(positive_percentiles) else None,
        "top_k": {key: {**value, "recall": value["positives_captured"] / value["total_positive"] if value["total_positive"] else None, "precision": value["positives_captured"] / value["flagged_node_weeks"] if value["flagged_node_weeks"] else None} for key, value in captures.items()},
    }


def score_model(raw: np.ndarray, counts: np.ndarray, labels: list[str], nodes: pd.DataFrame, model: str, model_json: dict[str, Any], arrays: dict[str, np.ndarray] | None = None) -> tuple[dict[str, Any], pd.DataFrame]:
    if model == "A3":
        beta_occ = np.asarray(model_json["occurrence_coefficients"], dtype=np.float64)
        beta_count = np.asarray(model_json["count_coefficients"], dtype=np.float64)
        mean = np.asarray(model_json["preprocessing"]["training_mean"], dtype=np.float64)
        sd = np.asarray(model_json["preprocessing"]["training_sd"], dtype=np.float64)
        theta = float(model_json["theta"])
        prevalence = float(model_json["training_prevalence"])
        occ_effect = count_effect = None
    else:
        assert arrays is not None
        beta_occ = arrays["occurrence_beta"]
        beta_count = arrays["count_beta"]
        mean = arrays["training_mean"]
        sd = arrays["training_sd"]
        theta = float(model_json["theta"])
        prevalence = float(model_json["training_prevalence"])
        occ_effect = arrays["occurrence_spatial_effect"]
        count_effect = arrays["count_spatial_effect"]
    x = (raw - mean[None, :]) / sd[None, :]
    p, conditional, mu = predict(beta_occ, beta_count, theta, x, occ_effect, count_effect)
    y = counts.reshape(-1)
    summary = metrics(y, p, conditional, mu, theta, prevalence)
    summary["model"] = model
    summary["us_ranking"] = ranking(p, y, labels, nodes)
    weekly: list[dict[str, Any]] = []
    for index, week in enumerate(labels):
        sl = slice(index * NODE_COUNT, (index + 1) * NODE_COUNT)
        row = metrics(y[sl], p[sl], conditional[sl], mu[sl], theta, prevalence)
        row.update({"model": model, "week": week})
        weekly.append(row)
    return summary, pd.DataFrame(weekly)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-refit", action="store_true")
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--a3-manifest", type=Path, required=True)
    parser.add_argument("--a3-model", type=Path, required=True)
    parser.add_argument("--a4s-manifest", type=Path, required=True)
    parser.add_argument("--a4s-model-json", type=Path, required=True)
    parser.add_argument("--a4s-model-npz", type=Path, required=True)
    parser.add_argument("--model-output", type=Path)
    parser.add_argument("--front-features", type=Path)
    parser.add_argument("--soil-features", type=Path)
    parser.add_argument("--anthropogenic-features", type=Path)
    parser.add_argument("--edges", type=Path)
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args()
    if not args.no_refit:
        raise SystemExit("STOP: evaluation requires explicit --no-refit")
    contract = validate_contract(args.a3_manifest, args.a3_model, args.a4s_manifest, args.a4s_model_json, args.a4s_model_npz)
    plan = {
        "status": "NO_FUTURE_EVALUATION_PERFORMED" if args.plan_only else "READY_FOR_POST_FREEZE_EVALUATION",
        "no_refit": True,
        "challenger_freeze_week": "2026-W42",
        "evaluation_eligible_week": "2026-W43",
        "forbidden_independent_period": list(EXPECTED_WEEKS),
        "a3_manifest_sha256": contract["a3_manifest_sha256"],
        "a4s_manifest_sha256": contract["a4s_manifest_sha256"],
    }
    if args.plan_only:
        print(json.dumps(plan, indent=2, sort_keys=True))
        return 0
    required = [args.model_output, args.front_features, args.soil_features, args.anthropogenic_features, args.edges, args.output_root]
    if any(value is None for value in required):
        raise SystemExit("future evaluation requires model/data paths unless --plan-only is used")
    raw, counts, nodes, labels = build_raw_features(args.model_output, args.front_features, args.soil_features, args.anthropogenic_features)
    eligible = [i for i, label in enumerate(labels) if parse_week(label) >= parse_week("2026-W43")]
    if not eligible:
        plan["status"] = "NO_ELIGIBLE_POST_FREEZE_WEEKS"
        print(json.dumps(plan, indent=2, sort_keys=True))
        return 0
    selected_labels = [labels[i] for i in eligible]
    if set(selected_labels).intersection(EXPECTED_WEEKS):
        raise RuntimeError("W30-W39 cannot be used as A4-S independent evaluation")
    row_indices = np.concatenate([np.arange(i * NODE_COUNT, (i + 1) * NODE_COUNT) for i in eligible])
    selected_raw = raw.reshape(-1, 34)[row_indices]
    selected_counts = counts.reshape(-1)[row_indices]
    a4_json = read_json(args.a4s_model_json)
    arrays_npz = np.load(args.a4s_model_npz)
    arrays = {key: arrays_npz[key] for key in arrays_npz.files}
    a3_json = read_json(args.a3_model)
    a3_summary, a3_weekly = score_model(selected_raw, selected_counts, selected_labels, nodes, "A3", a3_json)
    a4_summary, a4_weekly = score_model(selected_raw, selected_counts, selected_labels, nodes, "A4-S", a4_json, arrays)
    out = args.output_root
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([a3_summary, a4_summary]).to_json(out / "a3_vs_a4s_summary.json", orient="records", indent=2)
    pd.concat([a3_weekly, a4_weekly], ignore_index=True).to_csv(out / "weekly_a3_vs_a4s.csv", index=False)
    paired = []
    for key in sorted(set(a3_summary).intersection(a4_summary)):
        if isinstance(a3_summary[key], (int, float)) and isinstance(a4_summary[key], (int, float)):
            delta = float(a4_summary[key] - a3_summary[key])
            paired.append({"metric": key, "a3_value": a3_summary[key], "a4s_value": a4_summary[key], "absolute_difference": delta, "relative_difference": delta / a3_summary[key] if a3_summary[key] else None, "threshold_source": "config/a3_vs_a4s_advancement_rules.yaml"})
    pd.DataFrame(paired).to_csv(out / "a3_vs_a4s_paired_comparison.csv", index=False)
    plan["status"] = "COMPLETED_NO_RETUNING"
    plan["eligible_weeks"] = selected_labels
    (out / "evaluation_status.json").write_text(json.dumps(jsonable(plan), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(jsonable(plan), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
