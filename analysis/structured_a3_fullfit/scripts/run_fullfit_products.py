#!/usr/bin/env python3
"""Fit the frozen STRUCTURED A3 model and assemble descriptive products.

The fit stage reads the canonical production bundle and frozen A3 static
features, verifies the causal history contract, fits one fixed-theta
penalized hurdle model through the last complete supported week, and writes
the complete weekly node prediction archive plus interpretation tables. The R
renderer consumes that archive without fitting or changing the model. The
finalize stage assembles checksums, the report, and the master manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

SCRIPT_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = SCRIPT_ROOT
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

NODE_COUNT = 10_037
START_WEEK = "2025-W01"
MODEL_ID = "STRUCTURED_A3_FULLFIT"
HISTORY_FEATURES = [
    "distance_to_any_prior_positive_log1p",
    "distance_to_prev4_positive_log1p",
    "weeks_since_detection_within_50km_log1p",
    "any_prior_positive_available",
    "prev4_positive_available",
    "detection_within_50km_ever_available",
]
FEATURE_ORDER = list(BASE_FEATURES) + list(ADDED_FEATURES)
TRANSFORMATIONS = {
    **{name: "identity" for name in BASE_FEATURES[:12]},
    **{name: "log1p" for name in BASE_FEATURES[12:17]},
    **{name: "identity" for name in BASE_FEATURES[17:22]},
    "week_sin": "identity",
    "week_cos": "identity",
    "distance_to_any_prior_positive_log1p": "log1p",
    "distance_to_prev4_positive_log1p": "log1p",
    "weeks_since_detection_within_50km_log1p": "log1p",
    "any_prior_positive_available": "identity",
    "prev4_positive_available": "identity",
    "detection_within_50km_ever_available": "identity",
    "road_density": "log1p",
    "night_illumination": "log1p",
    "clay_0_15": "identity",
    "water_difference_wv0033_minus_wv0010_0_15": "identity",
}
GROUPS = {
    **{name: "environmental" for name in BASE_FEATURES[:12]},
    **{name: "livestock" for name in BASE_FEATURES[12:17]},
    **{name: "livestock missingness" for name in BASE_FEATURES[17:22]},
    "week_sin": "seasonal",
    "week_cos": "seasonal",
    **{name: "detection history/front" for name in HISTORY_FEATURES},
    "road_density": "anthropogenic",
    "night_illumination": "anthropogenic",
    "clay_0_15": "soil",
    "water_difference_wv0033_minus_wv0010_0_15": "soil",
}
STATIC_FEATURES = {
    "cattle_density", "goat_density", "sheep_density", "horse_density", "pig_density",
    "cattle_density_imputed", "goat_density_imputed", "sheep_density_imputed",
    "horse_density_imputed", "pig_density_imputed", "road_density", "night_illumination",
    "clay_0_15", "water_difference_wv0033_minus_wv0010_0_15",
}
CALENDAR_SET = set(CALENDAR_FEATURES)
UNSCALED = {name for name in FEATURE_ORDER if name.endswith("_imputed") or name.endswith("_available")} | CALENDAR_SET


def utc_now() -> str:
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
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def atomic_write(path: Path, writer) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{__import__('os').getpid()}")
    try:
        writer(temporary)
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_json(path: Path, payload: Any) -> None:
    atomic_write(path, lambda p: p.write_text(json.dumps(jsonable(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8"))


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    atomic_write(path, lambda p: frame.to_csv(p, index=False))


def write_parquet(path: Path, frame: pd.DataFrame) -> None:
    atomic_write(path, lambda p: frame.to_parquet(p, index=False, compression="zstd"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_value(*args: str) -> str:
    try:
        return subprocess.check_output(["git", "-c", f"safe.directory={REPO_ROOT.as_posix()}", *args], cwd=REPO_ROOT, text=True).strip()
    except Exception:
        return "unknown"


def parse_week(value: str) -> tuple[int, int]:
    year, week = str(value).split("-W")
    return int(year), int(week)


def iso_week_before(left: str, right: str) -> bool:
    return parse_week(left) < parse_week(right)


def require_columns(frame: pd.DataFrame, columns: Iterable[str], label: str) -> None:
    missing = sorted(set(columns).difference(frame.columns))
    if missing:
        raise RuntimeError(f"{label} is missing columns: {missing}")


def validate_nodes(nodes: pd.DataFrame) -> pd.DataFrame:
    require_columns(nodes, ["model_node_id", "raster_cell", "row", "column", "lon", "lat", "country_or_domain_region"], "nodes")
    nodes = nodes.sort_values("model_node_id").reset_index(drop=True)
    ids = nodes["model_node_id"].to_numpy(np.int64)
    if len(nodes) != NODE_COUNT or not np.array_equal(ids, np.arange(NODE_COUNT)):
        raise RuntimeError("canonical node count/order is not exactly 10,037 nodes 0..10036")
    if nodes["raster_cell"].duplicated().any():
        raise RuntimeError("canonical raster-cell mapping contains duplicates")
    return nodes


def validate_feature_nodes(nodes: pd.DataFrame, label: str) -> pd.DataFrame:
    require_columns(nodes, ["model_node_id"], label)
    nodes = nodes.sort_values("model_node_id").reset_index(drop=True)
    ids = nodes["model_node_id"].to_numpy(np.int64)
    if len(nodes) != NODE_COUNT or not np.array_equal(ids, np.arange(NODE_COUNT)):
        raise RuntimeError(f"{label} does not cover canonical node IDs 0..10036")
    return nodes


def load_bundle(args: argparse.Namespace) -> dict[str, Any]:
    root = args.model_output
    raw = root / "raw"
    manifest_path = root / "manifests" / "revised_production_manifest.json"
    if not manifest_path.exists():
        raise RuntimeError(f"missing production manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    dynamic = np.asarray(np.load(raw / "dynamic_features.npy", mmap_mode="r"), dtype=np.float64)
    static = np.asarray(np.load(raw / "static_features.npy", mmap_mode="r"), dtype=np.float64)
    counts = np.asarray(np.load(raw / "targets_count.npy", mmap_mode="r"), dtype=np.int64)
    presence = np.asarray(np.load(raw / "targets_presence.npy", mmap_mode="r"), dtype=np.int8)
    weeks = pd.read_parquet(raw / "weeks.parquet").reset_index(drop=True)
    calendar = pd.read_parquet(raw / "calendar_features.parquet")[list(CALENDAR_FEATURES)].to_numpy(np.float64)
    nodes = validate_nodes(pd.read_parquet(raw / "nodes.parquet"))
    front = pd.read_parquet(args.front_features, columns=["week_index", "model_node_id", *HISTORY_FEATURES, "history_cutoff_week"])
    front = front.sort_values(["week_index", "model_node_id"]).reset_index(drop=True)
    labels = weeks["iso_week"].astype(str).tolist()
    if not labels or labels[0] != START_WEEK:
        raise RuntimeError(f"unexpected response start: {labels[0] if labels else 'none'}")
    if dynamic.ndim != 3 or dynamic.shape[1:] != (NODE_COUNT, 12):
        raise RuntimeError(f"unexpected dynamic feature shape: {dynamic.shape}")
    if static.shape != (NODE_COUNT, 10) or counts.shape != (len(labels), NODE_COUNT) or presence.shape != counts.shape:
        raise RuntimeError(f"unexpected static/count shapes: {static.shape}, {counts.shape}")
    if calendar.shape != (len(labels), 2):
        raise RuntimeError(f"unexpected calendar shape: {calendar.shape}")
    if len(front) != len(labels) * NODE_COUNT:
        raise RuntimeError("front-history feature coverage does not match all response weeks/nodes")
    expected_week = np.repeat(np.arange(len(labels)), NODE_COUNT)
    expected_node = np.tile(np.arange(NODE_COUNT), len(labels)
    )
    if not np.array_equal(front["week_index"].to_numpy(np.int64), expected_week) or not np.array_equal(front["model_node_id"].to_numpy(np.int64), expected_node):
        raise RuntimeError("front-history rows are not in canonical week/node order")
    if np.any(counts < 0) or not np.isfinite(dynamic).all() or not np.isfinite(static).all() or not np.isfinite(calendar).all():
        raise RuntimeError("production arrays contain non-finite predictors or negative responses")
    if not np.isfinite(front[HISTORY_FEATURES].to_numpy(np.float64)).all():
        raise RuntimeError("front-history predictors contain non-finite values")
    if not np.array_equal(presence, (counts > 0).astype(np.int8)):
        raise RuntimeError("response presence contract failed")
    anthro = validate_feature_nodes(pd.read_parquet(args.anthropogenic_features), "anthropogenic features")
    soil = validate_feature_nodes(pd.read_parquet(args.soil_features), "soil features")
    require_columns(anthro, ["road_density", "night_illumination"], "anthropogenic features")
    soil_map = {name: (name if name in soil.columns else f"{name}__mean") for name in ["clay_0_15", "water_difference_wv0033_minus_wv0010_0_15"]}
    require_columns(soil, soil_map.values(), "soil features")
    static_a3 = anthro[["model_node_id", "road_density", "night_illumination"]].merge(soil[["model_node_id", *soil_map.values()]], on="model_node_id", validate="one_to_one").rename(columns={value: key for key, value in soil_map.items()}).sort_values("model_node_id")
    if len(static_a3) != NODE_COUNT or not np.array_equal(static_a3["model_node_id"].to_numpy(np.int64), np.arange(NODE_COUNT)):
        raise RuntimeError("A3 static feature join changed canonical node order")
    if not np.isfinite(static_a3[ADDED_FEATURES].to_numpy(np.float64)).all():
        raise RuntimeError("A3 static features contain non-finite values")
    transformed_static = static.copy()
    transformed_static[:, :5] = np.log1p(transformed_static[:, :5])
    added = static_a3[ADDED_FEATURES].to_numpy(np.float64)
    added[:, 0:2] = np.log1p(added[:, 0:2])
    history = front[HISTORY_FEATURES].to_numpy(np.float64).reshape(len(labels), NODE_COUNT, len(HISTORY_FEATURES))
    base = np.concatenate([
        dynamic,
        np.broadcast_to(transformed_static[:, :5][None, :, :], (len(labels), NODE_COUNT, 5)),
        np.broadcast_to(transformed_static[:, 5:][None, :, :], (len(labels), NODE_COUNT, 5)),
        np.broadcast_to(calendar[:, None, :], (len(labels), NODE_COUNT, 2)),
        history,
    ], axis=2)
    full = np.concatenate([base, np.broadcast_to(added[None, :, :], (len(labels), NODE_COUNT, len(ADDED_FEATURES)))], axis=2)
    if full.shape != (len(labels), NODE_COUNT, len(FEATURE_ORDER)) or not np.isfinite(full).all():
        raise RuntimeError(f"A3 feature array contract failed: {full.shape}")
    source_paths = {
        "production_manifest": manifest_path,
        "dynamic_features": raw / "dynamic_features.npy",
        "dynamic_history_features": raw / "dynamic_history_features.npy",
        "static_features": raw / "static_features.npy",
        "targets_count": raw / "targets_count.npy",
        "targets_presence": raw / "targets_presence.npy",
        "weeks": raw / "weeks.parquet",
        "calendar_features": raw / "calendar_features.parquet",
        "nodes": raw / "nodes.parquet",
        "front_features": args.front_features,
        "anthropogenic_features": args.anthropogenic_features,
        "soil_features": args.soil_features,
        "frozen_a3_evaluation_manifest": REPO_ROOT / "analysis" / "structured_a3_evaluation" / "results" / "frozen_a3_evaluation_manifest.json",
    }
    return {"root": root, "raw": raw, "manifest_path": manifest_path, "production_manifest": manifest, "dynamic": dynamic, "static": static, "counts": counts, "presence": presence, "calendar": calendar, "weeks": weeks, "labels": labels, "nodes": nodes, "front": front, "features": full, "static_a3": static_a3, "source_paths": source_paths}


def completeness(bundle: dict[str, Any]) -> tuple[dict[str, Any], pd.DataFrame]:
    labels, dynamic, counts, front = bundle["labels"], bundle["dynamic"], bundle["counts"], bundle["front"]
    response_complete = np.isfinite(counts).all(axis=1)
    environmental_complete = np.isfinite(dynamic).all(axis=(1, 2))
    history_complete = np.zeros(len(labels), dtype=bool)
    same_or_future = np.zeros(len(labels), dtype=np.int64)
    missing_cutoff = np.zeros(len(labels), dtype=np.int64)
    for index, label in enumerate(labels):
        rows = front.iloc[index * NODE_COUNT : (index + 1) * NODE_COUNT]
        cutoff = rows["history_cutoff_week"]
        missing_cutoff[index] = int(cutoff.isna().sum())
        invalid = 0
        for value in cutoff.dropna().astype(str):
            try:
                if not iso_week_before(value, label):
                    invalid += 1
            except Exception:
                invalid += 1
        same_or_future[index] = invalid
        history_complete[index] = bool(len(rows) == NODE_COUNT and np.isfinite(rows[HISTORY_FEATURES].to_numpy(np.float64)).all() and missing_cutoff[index] == 0 and invalid == 0)
    a3_complete = environmental_complete & history_complete
    support = response_complete & a3_complete
    if not support.any():
        raise RuntimeError("no complete response/predictor-supported week exists")
    last = int(np.flatnonzero(support)[-1])
    rows = []
    for index, label in enumerate(labels):
        rows.append({"week": label, "response_complete": bool(response_complete[index]), "environmental_predictors_complete": bool(environmental_complete[index]), "a3_predictors_complete": bool(a3_complete[index]), "causally_constructible_history_complete": bool(history_complete[index]), "same_week_or_future_history_uses": int(same_or_future[index]), "missing_history_cutoff_rows": int(missing_cutoff[index]), "complete_fit_support": bool(support[index])})
    observation_source = bundle["production_manifest"].get("observation_source", {})
    latest_observation_date = observation_source.get("maximum_date")
    latest_observation_week = None
    if latest_observation_date:
        latest_observation_iso = date.fromisoformat(str(latest_observation_date)).isocalendar()
        latest_observation_week = f"{latest_observation_iso.year}-W{latest_observation_iso.week:02d}"
    return {"status": "verified", "latest_observation_week_in_bundle": labels[-1], "latest_observation_week_authoritative_source": latest_observation_week, "latest_observation_date_authoritative_source": latest_observation_date, "observation_source_path": observation_source.get("path"), "latest_complete_environmental_predictor_week": labels[int(np.flatnonzero(environmental_complete)[-1])], "latest_complete_a3_predictor_week": labels[int(np.flatnonzero(a3_complete)[-1])], "latest_causally_constructible_history_feature_week": labels[int(np.flatnonzero(history_complete)[-1])], "full_fit_start_week": START_WEEK, "full_fit_end_week": labels[last], "full_fit_week_count": last + 1, "node_count": NODE_COUNT, "predictor_count": len(FEATURE_ORDER), "response_presence_definition": "count > 0"}, pd.DataFrame(rows)


def source_checksums(bundle: dict[str, Any]) -> dict[str, Any]:
    result = {}
    for name, path in bundle["source_paths"].items():
        result[name] = {"path": str(path), "sha256": sha256_file(path) if path.exists() else None, "size_bytes": path.stat().st_size if path.exists() else None}
    return result


def fit_full(bundle: dict[str, Any], horizon: dict[str, Any]) -> dict[str, Any]:
    end = int(horizon["full_fit_week_count"])
    raw_train = bundle["features"][:end].reshape(-1, len(FEATURE_ORDER)).astype(np.float64, copy=False)
    raw_all = bundle["features"].reshape(-1, len(FEATURE_ORDER)).astype(np.float64, copy=False)
    x_train, x_all, scaling = standardize(raw_train, raw_all, FEATURE_ORDER)
    y_train = bundle["counts"][:end].reshape(-1)
    state = fit_fixed_theta(x_train, y_train)
    if not state["fit_info"].get("occurrence_success") or not state["fit_info"].get("count_success"):
        raise RuntimeError(f"full-fit optimizer did not converge: {state['fit_info']}")
    p, conditional, mu = predict(state, x_all)
    shape = (len(bundle["labels"]), NODE_COUNT)
    return {"state": state, "scaling": scaling, "probability": p.reshape(shape), "conditional": conditional.reshape(shape), "mu": mu.reshape(shape), "training_prevalence": float(np.mean(y_train > 0)), "training_rows": int(len(y_train)), "training_positive_rows": int(np.sum(y_train > 0))}


def coefficient_table(fit: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for component, coefficients in [("occurrence", fit["state"]["occurrence_beta"]), ("positive_count", fit["state"]["count_beta"])]:
        for name, value in zip(["intercept", *FEATURE_ORDER], coefficients):
            rows.append({"component": component, "predictor": name, "group": "intercept" if name == "intercept" else GROUPS[name], "transformation": "identity" if name == "intercept" else TRANSFORMATIONS.get(name, "identity"), "coefficient": float(value), "absolute_coefficient": float(abs(value)), "sign": "positive" if value > 0 else "negative" if value < 0 else "zero", "standardized": name != "intercept"})
    table = pd.DataFrame(rows)
    for component in ["occurrence", "positive_count"]:
        mask = (table["component"] == component) & (table["predictor"] != "intercept")
        table.loc[mask, "rank_by_absolute_magnitude"] = table.loc[mask, "absolute_coefficient"].rank(method="min", ascending=False).astype(int)
    return table


def ztnb_loglikelihood(y: np.ndarray, mu: np.ndarray) -> np.ndarray:
    from scipy.special import gammaln
    theta, mu = FIXED_THETA, np.maximum(np.asarray(mu, dtype=np.float64), 1e-12)
    y = np.asarray(y, dtype=np.float64)
    denominator = theta + mu
    log_p0 = theta * (math.log(theta) - np.log(denominator))
    return gammaln(y + theta) - gammaln(theta) - gammaln(y + 1.0) + theta * (math.log(theta) - np.log(denominator)) + y * (np.log(mu) - np.log(denominator)) - np.log(np.maximum(-np.expm1(log_p0), 1e-12))


def model_metrics(y: np.ndarray, p: np.ndarray, conditional: np.ndarray, mu: np.ndarray) -> dict[str, float]:
    positive = y > 0
    occurrence_nll = -(positive * np.log(np.maximum(p, 1e-12)) + (~positive) * np.log(np.maximum(1.0 - p, 1e-12)))
    count_nll = np.zeros_like(occurrence_nll, dtype=np.float64)
    count_nll[positive] = -ztnb_loglikelihood(y[positive], mu[positive])
    try:
        from sklearn.metrics import average_precision_score
        pr_auc = float(average_precision_score(positive.astype(int), p))
    except Exception:
        order = np.argsort(-p)
        sorted_y = positive[order].astype(np.int64)
        cumulative = np.cumsum(sorted_y)
        pr_auc = float(np.sum((cumulative / np.arange(1, len(sorted_y) + 1)) * sorted_y) / max(sorted_y.sum(), 1))
    return {"joint_nll": float(np.mean(occurrence_nll + count_nll)), "brier": float(np.mean((p - positive) ** 2)), "pr_auc": pr_auc, "mean_p": float(np.mean(p)), "mean_expected": float(np.mean(p * conditional))}


def permutation_importance(bundle: dict[str, Any], fit: dict[str, Any], end: int, replicates: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    raw = bundle["features"][:end].reshape(-1, len(FEATURE_ORDER)).astype(np.float64, copy=True)
    y = bundle["counts"][:end].reshape(-1).astype(np.int64, copy=False)
    baseline_x, _, _ = standardize(raw, raw, FEATURE_ORDER)
    base_p, base_cond, base_mu = predict(fit["state"], baseline_x)
    base = model_metrics(y, base_p, base_cond, base_mu)
    records = []
    for index, name in enumerate(FEATURE_ORDER):
        strategy = "static_across_nodes" if name in STATIC_FEATURES else "dynamic_within_week" if name in BASE_FEATURES[:12] else "calendar_week_block" if name in CALENDAR_SET else "history_within_week"
        values = []
        for _ in range(replicates):
            permuted = raw.copy()
            block = permuted.reshape(end, NODE_COUNT, -1)[:, :, index]
            if strategy == "static_across_nodes":
                block[:] = block[:, rng.permutation(NODE_COUNT)]
            elif strategy == "calendar_week_block":
                block[:] = block[rng.permutation(end)]
            else:
                for week in range(end):
                    block[week] = block[week, rng.permutation(NODE_COUNT)]
            standardized, _, _ = standardize(permuted, permuted, FEATURE_ORDER)
            p, cond, mu = predict(fit["state"], standardized)
            score = model_metrics(y, p, cond, mu)
            values.append({"nll": score["joint_nll"] - base["joint_nll"], "brier": score["brier"] - base["brier"], "pr_auc": base["pr_auc"] - score["pr_auc"]})
        records.append({"predictor": name, "group": GROUPS[name], "permutation_strategy": strategy, "replicates": replicates, "baseline_joint_nll": base["joint_nll"], "baseline_brier": base["brier"], "baseline_pr_auc": base["pr_auc"], "permutation_nll_importance": float(np.mean([v["nll"] for v in values])), "permutation_nll_sd": float(np.std([v["nll"] for v in values], ddof=1)) if replicates > 1 else 0.0, "permutation_brier_importance": float(np.mean([v["brier"] for v in values])), "permutation_brier_sd": float(np.std([v["brier"] for v in values], ddof=1)) if replicates > 1 else 0.0, "permutation_pr_auc_importance": float(np.mean([v["pr_auc"] for v in values])), "permutation_pr_auc_sd": float(np.std([v["pr_auc"] for v in values], ddof=1)) if replicates > 1 else 0.0})
    table = pd.DataFrame(records)
    table["rank_by_mean_degradation"] = table[["permutation_nll_importance", "permutation_brier_importance", "permutation_pr_auc_importance"]].mean(axis=1).rank(method="min", ascending=False).astype(int)
    return table.sort_values(["rank_by_mean_degradation", "predictor"]).reset_index(drop=True)


def effect_reference(scaled: np.ndarray) -> np.ndarray:
    reference = np.median(scaled, axis=0)
    for index, name in enumerate(FEATURE_ORDER):
        if name in UNSCALED:
            reference[index] = 0.0
    reference[FEATURE_ORDER.index("week_sin")] = 0.0
    reference[FEATURE_ORDER.index("week_cos")] = 1.0
    return reference


def effect_response(bundle: dict[str, Any], fit: dict[str, Any], coefficient: pd.DataFrame, importance: pd.DataFrame, end: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = bundle["features"][:end].reshape(-1, len(FEATURE_ORDER)).astype(np.float64, copy=False)
    scaled, _, scaling = standardize(raw, raw, FEATURE_ORDER)
    reference = effect_reference(scaled)
    occ_top = coefficient.query("component == 'occurrence' and predictor != 'intercept'").nlargest(4, "absolute_coefficient")["predictor"].tolist()
    count_top = coefficient.query("component == 'positive_count' and predictor != 'intercept'").nlargest(4, "absolute_coefficient")["predictor"].tolist()
    imp_top = importance.nsmallest(4, "rank_by_mean_degradation")["predictor"].tolist()
    selected = []
    for name in occ_top + count_top + imp_top:
        if name not in selected and len(selected) < 10:
            selected.append(name)
    if len(selected) < 8:
        selected = FEATURE_ORDER[:8]
    rows = []
    for name in selected:
        index = FEATURE_ORDER.index(name)
        stored_values = raw[:, index]
        transform = TRANSFORMATIONS.get(name, "identity")
        natural = np.expm1(stored_values) if transform == "log1p" else stored_values
        lo, hi = float(np.nanquantile(natural, 0.01)), float(np.nanquantile(natural, 0.99))
        if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
            lo, hi = float(np.nanmin(natural)), float(np.nanmax(natural))
        mean, sd = float(scaling["training_mean"][index]), float(scaling["training_sd"][index])
        for value in np.linspace(lo, hi, 101):
            model_value = math.log1p(max(value, 0.0)) if transform == "log1p" else value
            vector = reference.copy()
            vector[index] = (model_value - mean) / sd if index in scaling["scaled_feature_indices"] else model_value
            p, conditional, _ = predict(fit["state"], vector.reshape(1, -1))
            rows.append({"predictor": name, "group": GROUPS[name], "transformation": transform, "reference_profile": "median continuous; zero indicators; representative season/history", "natural_scale_value": value, "occurrence_probability": float(p[0]), "conditional_count_mean": float(conditional[0]), "expected_count": float(p[0] * conditional[0])})
    return pd.DataFrame(rows), pd.DataFrame([{"predictor": name, "selection_basis": "union of top four standardized occurrence coefficients, top four standardized count coefficients, and top four permutation degradations; first ten unique retained", "reference_profile": "median continuous predictors; zero indicators; week_sin=0, week_cos=1"} for name in selected])


def seasonality(fit: dict[str, Any]) -> pd.DataFrame:
    occurrence, count = fit["state"]["occurrence_beta"], fit["state"]["count_beta"]
    sin_occ, cos_occ = occurrence[1 + FEATURE_ORDER.index("week_sin")], occurrence[1 + FEATURE_ORDER.index("week_cos")]
    sin_count, cos_count = count[1 + FEATURE_ORDER.index("week_sin")], count[1 + FEATURE_ORDER.index("week_cos")]
    return pd.DataFrame([{"epidemiological_week": week, "occurrence_linear_predictor_contribution": sin_occ * math.sin(2 * math.pi * week / 52) + cos_occ * math.cos(2 * math.pi * week / 52), "count_linear_predictor_contribution": sin_count * math.sin(2 * math.pi * week / 52) + cos_count * math.cos(2 * math.pi * week / 52), "week_sin_coefficient_occurrence": sin_occ, "week_cos_coefficient_occurrence": cos_occ, "week_sin_coefficient_count": sin_count, "week_cos_coefficient_count": cos_count} for week in range(1, 53)])


def save_fit_outputs(bundle: dict[str, Any], horizon: dict[str, Any], support: pd.DataFrame, fit: dict[str, Any], args: argparse.Namespace) -> None:
    out = args.output_root
    for folder in ["model", "manifests", "predictions", "interpretation/coefficients", "interpretation/importance", "interpretation/effects", "interpretation/seasonality", "tables", "report", "geotiff", "raster_summaries", "nowcast_pdf"]:
        (out / folder).mkdir(parents=True, exist_ok=True)
    write_json(out / "manifests/fullfit_data_horizon.json", horizon)
    write_csv(out / "manifests/fullfit_support_audit.csv", support)
    repository_audit_root = getattr(args, "repository_audit_root", None)
    if repository_audit_root:
        repository_audit_root = Path(repository_audit_root)
        write_json(repository_audit_root / "fullfit_data_horizon.json", horizon)
    leakage = support.rename(columns={"same_week_or_future_history_uses": "same_week_or_future_response_leakage_rows"})[["week", "same_week_or_future_response_leakage_rows", "missing_history_cutoff_rows", "causally_constructible_history_complete"]]
    leakage["status"] = np.where((leakage["same_week_or_future_response_leakage_rows"] == 0) & (leakage["missing_history_cutoff_rows"] == 0) & leakage["causally_constructible_history_complete"], "PASS", "FAIL")
    leakage["checked_node_rows"] = NODE_COUNT
    write_csv(out / "manifests/history_feature_leakage_audit.csv", leakage)
    if repository_audit_root:
        write_csv(repository_audit_root / "history_feature_leakage_audit.csv", leakage)
    if not (leakage["status"] == "PASS").all():
        raise RuntimeError("history feature leakage audit failed")

    state = fit["state"]
    write_json(out / "model/fullfit_a3_model.json", {"status": "completed_full_fit", "model_id": MODEL_ID, "model_family": "structured hurdle model", "response": "weekly recorded detection count per canonical node; occurrence is count > 0", "predictor_count": len(FEATURE_ORDER), "predictor_order": FEATURE_ORDER, "transformations": TRANSFORMATIONS, "penalty": PENALTY, "theta": FIXED_THETA, "theta_fixed": True, "objective": "exact_joint_hurdle_nll", "domain": "10,037 revised-domain nodes", "fit_start_week": START_WEEK, "fit_end_week": horizon["full_fit_end_week"], "fit_week_count": horizon["full_fit_week_count"], "training_rows": fit["training_rows"], "training_positive_rows": fit["training_positive_rows"], "training_prevalence": fit["training_prevalence"], "occurrence_coefficients": state["occurrence_beta"], "count_coefficients": state["count_beta"], "fit_info": state["fit_info"], "scaling": fit["scaling"], "repository_sha": git_value("rev-parse", "HEAD"), "generation_utc": utc_now(), "validation_statement": "descriptive full-fit output; no independent validation claim"})
    coeff = coefficient_table(fit)
    write_csv(out / "model/fullfit_a3_coefficients.csv", coeff)
    write_csv(out / "model/fullfit_a3_scaling_parameters.csv", pd.DataFrame({"predictor": FEATURE_ORDER, "training_mean": fit["scaling"]["training_mean"], "training_sd": fit["scaling"]["training_sd"], "scaled": [index in fit["scaling"]["scaled_feature_indices"] for index in range(len(FEATURE_ORDER))]}))
    write_csv(out / "interpretation/coefficients/occurrence_coefficients_ranked.csv", coeff.query("component == 'occurrence' and predictor != 'intercept'").sort_values("rank_by_absolute_magnitude"))
    write_csv(out / "interpretation/coefficients/count_coefficients_ranked.csv", coeff.query("component == 'positive_count' and predictor != 'intercept'").sort_values("rank_by_absolute_magnitude"))

    frames = []
    for index, week in enumerate(bundle["labels"]):
        frame = bundle["nodes"][["model_node_id", "canonical_node_id", "raster_cell", "row", "column", "x", "y", "lon", "lat", "country_or_domain_region"]].copy()
        frame.insert(0, "week", week)
        frame["p_occurrence"], frame["conditional_count_mean"] = fit["probability"][index], fit["conditional"][index]
        frame["expected_count"], frame["observed_count"] = fit["probability"][index] * fit["conditional"][index], bundle["counts"][index]
        frames.append(frame)
    predictions = pd.concat(frames, ignore_index=True)
    write_parquet(out / "predictions/weekly_predictions.parquet", predictions)
    write_csv(out / "predictions/observed_detections.csv", predictions.loc[predictions["observed_count"] > 0, ["week", "model_node_id", "lon", "lat", "country_or_domain_region", "observed_count"]])

    importance = permutation_importance(bundle, fit, int(horizon["full_fit_week_count"]), args.permutation_replicates, args.seed)
    write_csv(out / "interpretation/importance/predictive_importance.csv", importance)
    occ_summary = coeff.query("component == 'occurrence' and predictor != 'intercept'").rename(columns={"coefficient": "occurrence_coefficient", "absolute_coefficient": "occurrence_absolute_coefficient", "rank_by_absolute_magnitude": "occurrence_rank"})[["predictor", "group", "transformation", "occurrence_coefficient", "occurrence_rank"]]
    count_summary = coeff.query("component == 'positive_count' and predictor != 'intercept'").rename(columns={"coefficient": "count_coefficient", "absolute_coefficient": "count_absolute_coefficient", "rank_by_absolute_magnitude": "count_rank"})[["predictor", "count_coefficient", "count_rank"]]
    effect_summary = occ_summary.merge(count_summary, on="predictor", validate="one_to_one").merge(importance[["predictor", "permutation_nll_importance", "permutation_brier_importance", "permutation_pr_auc_importance"]], on="predictor", validate="one_to_one")
    effect_summary["occurrence_standardized_coefficient"] = effect_summary["occurrence_coefficient"]
    effect_summary["count_standardized_coefficient"] = effect_summary["count_coefficient"]
    write_csv(out / "interpretation/fullfit_a3_effect_summary.csv", effect_summary[["predictor", "group", "transformation", "occurrence_coefficient", "occurrence_standardized_coefficient", "count_coefficient", "count_standardized_coefficient", "occurrence_rank", "count_rank", "permutation_nll_importance", "permutation_brier_importance", "permutation_pr_auc_importance"]])
    feature_frame = bundle["features"][: int(horizon["full_fit_week_count"])].reshape(-1, len(FEATURE_ORDER))
    sample = feature_frame[np.linspace(0, len(feature_frame) - 1, min(args.correlation_sample, len(feature_frame))).astype(int)]
    corr = pd.DataFrame(np.corrcoef(sample, rowvar=False), index=FEATURE_ORDER, columns=FEATURE_ORDER)
    corr.reset_index(names="predictor").to_csv(out / "interpretation/importance/predictor_correlation_matrix.csv", index=False)
    high_corr = [{"predictor_a": left, "predictor_b": FEATURE_ORDER[right_index], "correlation": float(corr.iloc[left_index, right_index]), "flag": "strong correlation; permutation ranks may share redundant information"} for left_index, left in enumerate(FEATURE_ORDER) for right_index in range(left_index + 1, len(FEATURE_ORDER)) if abs(float(corr.iloc[left_index, right_index])) >= 0.7]
    write_csv(out / "interpretation/importance/strong_predictor_correlations.csv", pd.DataFrame(high_corr, columns=["predictor_a", "predictor_b", "correlation", "flag"]))
    effects, selected = effect_response(bundle, fit, coeff, importance, int(horizon["full_fit_week_count"]))
    write_csv(out / "interpretation/effects/effect_response.csv", effects)
    write_csv(out / "interpretation/effects/selected_effect_predictors.csv", selected)
    write_csv(out / "interpretation/seasonality/seasonal_effect.csv", seasonality(fit))

    summary = []
    for index, week in enumerate(bundle["labels"]):
        p, expected = fit["probability"][index], fit["probability"][index] * fit["conditional"][index]
        summary.append({"week": week, "mean_p_occurrence": float(np.mean(p)), "median_p_occurrence": float(np.median(p)), "max_p_occurrence": float(np.max(p)), "mean_expected_count": float(np.mean(expected)), "sum_expected_count": float(np.sum(expected)), "cells_p_ge_025": int(np.sum(p >= 0.25)), "cells_p_ge_050": int(np.sum(p >= 0.50)), "valid_cells": NODE_COUNT})
    write_csv(out / "tables/weekly_prediction_summary.csv", pd.DataFrame(summary))
    regions = bundle["nodes"]["country_or_domain_region"].astype(str).to_numpy()
    geo = []
    for index, week in enumerate(bundle["labels"]):
        expected = fit["probability"][index] * fit["conditional"][index]
        for geography in sorted(pd.unique(regions)):
            mask = regions == geography
            geo.append({"week": week, "geography": geography, "valid_cells": int(mask.sum()), "mean_p_occurrence": float(np.mean(fit["probability"][index, mask])), "mean_expected_count": float(np.mean(expected[mask])), "sum_expected_count_index": float(np.sum(expected[mask])), "cells_p_ge_025": int(np.sum(fit["probability"][index, mask] >= 0.25)), "cells_p_ge_050": int(np.sum(fit["probability"][index, mask] >= 0.50))})
    write_csv(out / "tables/weekly_geographic_summary.csv", pd.DataFrame(geo))

    tasks = [{"task_id": f"{week}:{product}", "week": week, "product": product, "status": "PENDING", "runtime": None, "output": relative, "checksum": None} for week in bundle["labels"] for product, relative in [("p_occurrence", f"geotiff/occurrence/a3_p_occurrence_{week.replace('-', '_')}.tif"), ("conditional_count_mean", f"geotiff/conditional_count/a3_conditional_count_{week.replace('-', '_')}.tif"), ("expected_count", f"geotiff/expected_count/a3_expected_count_{week.replace('-', '_')}.tif")]]
    write_csv(out / "manifests/fullfit_product_task_manifest.csv", pd.DataFrame(tasks))
    write_json(out / "manifests/fullfit_fit_manifest.json", {"status": "fit_complete", "model": MODEL_ID, "horizon": horizon, "source_artifacts": source_checksums(bundle), "repository_sha": git_value("rev-parse", "HEAD"), "software": {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__, "scipy": __import__("scipy").__version__}, "permutation_replicates": args.permutation_replicates, "seed": args.seed})


def update_model_manifest(output: Path) -> None:
    payload = json.loads((output / "manifests/fullfit_fit_manifest.json").read_text(encoding="utf-8"))
    model = output / "model/fullfit_a3_model.json"
    payload.update({"model_file": str(model), "model_sha256": sha256_file(model), "coefficients_file": str(output / "model/fullfit_a3_coefficients.csv"), "scaling_file": str(output / "model/fullfit_a3_scaling_parameters.csv"), "predictor_order": FEATURE_ORDER, "transformations": TRANSFORMATIONS, "penalty": PENALTY, "theta": FIXED_THETA, "objective": "exact_joint_hurdle_nll", "domain": "10,037 revised-domain nodes", "fit_start_week": payload["horizon"]["full_fit_start_week"], "fit_end_week": payload["horizon"]["full_fit_end_week"], "software_versions": payload.get("software", {})})
    write_json(output / "model/fullfit_a3_manifest.json", payload)


def finalize(args: argparse.Namespace) -> None:
    out = args.output_root
    update_model_manifest(out)
    horizon = json.loads((out / "manifests/fullfit_data_horizon.json").read_text(encoding="utf-8"))
    model_sha = sha256_file(out / "model/fullfit_a3_model.json")
    records = []
    manifest_path = out / "structured_a3_fullfit_output_manifest.csv"
    for path in sorted(out.rglob("*")):
        if not path.is_file() or path.name.startswith(".") or path.suffix.lower() in {".tmp", ".part"} or path == manifest_path or path.name.endswith(".sha256"):
            continue
        relative = path.relative_to(out).as_posix()
        artifact_type = "geotiff" if path.suffix.lower() in {".tif", ".tiff"} else "pdf" if path.suffix.lower() == ".pdf" else "figure" if path.suffix.lower() in {".png", ".svg"} else "table" if path.suffix.lower() in {".csv", ".parquet"} else "report" if path.suffix.lower() in {".md", ".html"} else "model_artifact" if "/model/" in f"/{relative}" else "manifest"
        records.append({"artifact_type": artifact_type, "week": "", "variable": "", "path": str(path), "relative_path": relative, "sha256": sha256_file(path), "size_bytes": path.stat().st_size, "model_sha": model_sha, "fit_end_week": horizon["full_fit_end_week"]})
    master = pd.DataFrame(records)
    write_csv(manifest_path, master)
    manifest_sha = sha256_file(manifest_path)
    write_json(out / "structured_a3_fullfit_output_manifest.json", {"status": "complete", "artifact_count": int(len(master)), "manifest_sha256": manifest_sha, "generated_utc": utc_now()})
    (out / "structured_a3_fullfit_output_manifest.csv.sha256").write_text(f"{manifest_sha}  structured_a3_fullfit_output_manifest.csv\n", encoding="utf-8")
    weekly = pd.read_csv(out / "tables/weekly_prediction_summary.csv")
    occ = pd.read_csv(out / "interpretation/coefficients/occurrence_coefficients_ranked.csv")
    count = pd.read_csv(out / "interpretation/coefficients/count_coefficients_ranked.csv")
    nowcast_weeks = weekly["week"].tail(6).tolist()
    report = ["# STRUCTURED A3 full-fit products", "", "> Descriptive full-fit output; not an independent validation product.", "", "## 1. Model specification", "", f"- Structured A3 hurdle model; 34 predictors; 10,037 revised-domain nodes.", f"- Fit horizon: `{horizon['full_fit_start_week']}` through `{horizon['full_fit_end_week']}`.", f"- Fixed theta `{FIXED_THETA}`; penalty `{PENALTY}`; objective `exact_joint_hurdle_nll`.", "- The frozen predictor order and transformations were reused without modification.", "", "## 2. Full-fit data horizon", "", f"The authoritative observation source extends through `{horizon.get('latest_observation_week_authoritative_source')}` (`{horizon.get('latest_observation_date_authoritative_source')}`), while the latest complete response and predictor-supported week was `{horizon['full_fit_end_week']}`. The causal history audit passed with zero same-week/future response uses.", "", "## 3. Study-period predictions", "", f"The weekly archive contains {len(weekly)} weeks and all {NODE_COUNT:,} canonical nodes per week. GeoTIFFs provide occurrence probability, exact conditional positive-count mean, and unconditional expected count.", "", "## 4. Spatial progression", "", "Selected spatial snapshots use predeclared temporal milestones (early, midpoint, holdout-start, recent, and latest complete week). They are descriptive visual summaries, not threshold-optimized classifications.", "", "## 5. Current nowcast", "", f"The descriptive nowcast visualization covers the latest six complete weeks: {', '.join(nowcast_weeks)}. Weekly PDFs and one multi-week summary preserve the existing Task 3E continuous-cell map layout with occurrence and expected-count panels, observations, boundaries, and provenance footer.", "", "## 6. Occurrence drivers", "", "Standardized coefficients are conditional model coefficients. The top occurrence rankings are:", "", "| Rank | Predictor | Group | Coefficient |", "|---:|---|---|---:|"]
    report += [f"| {int(row.rank_by_absolute_magnitude)} | {row.predictor} | {row.group} | {row.coefficient:.6g} |" for row in occ.head(10).itertuples()]
    report += ["", "## 7. Count drivers", "", "The positive-count rankings are conditional coefficients, not causal effects or independent importance:", "", "| Rank | Predictor | Group | Coefficient |", "|---:|---|---|---:|"]
    report += [f"| {int(row.rank_by_absolute_magnitude)} | {row.predictor} | {row.group} | {row.coefficient:.6g} |" for row in count.head(10).itertuples()]
    report += ["", "## 8. Key fitted relationships", "", "Selected effect-response curves are model-implied response-scale relationships over observed natural-scale predictor ranges with other predictors held at the documented reference profile. Curvature reflects link inversion, zero truncation, and log1p transformations; it is not evidence of an arbitrary nonlinear learner.", "", "## 9. Seasonality", "", "Week-sine and week-cosine coefficients are combined into one implied seasonal function for occurrence and positive-count linear-predictor contributions.", "", "## 10. Limitations", "", "- Fitted-period outputs are descriptive and are not independent validation.", "- Coefficients describe conditional associations, not causal effects.", "- Correlated predictors can share information and complicate permutation-importance rankings.", "- The model remains untested on a genuinely untouched prospective period beyond current complete A3 predictor support.", "- Zero recorded detections are not confirmed biological absences.", "", "## Provenance", "", f"Repository SHA: `{git_value('rev-parse', 'HEAD')}`. Full-fit end week: `{horizon['full_fit_end_week']}`. Generation UTC: `{utc_now()}`.", ""]
    atomic_write(out / "report/structured_a3_fullfit_summary.md", lambda p: p.write_text("\n".join(report), encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["fit", "finalize"])
    parser.add_argument("--model-output", type=Path, default=Path("/project/disease_ecology/STGNN-output/revised_model_data"))
    parser.add_argument("--front-features", type=Path, default=Path("/project/disease_ecology/STGNN-output/v2_model/front_features/causal_front_features.parquet"))
    parser.add_argument("--anthropogenic-features", type=Path, default=Path("/project/disease_ecology/STGNN-output/predictor_augmentation/static/road_night_node_features.parquet"))
    parser.add_argument("--soil-features", type=Path, default=Path("/project/disease_ecology/STGNN-output/soil_feature_screening_resumed_s1/soil_node_features.parquet"))
    parser.add_argument("--output-root", type=Path, default=Path("/project/disease_ecology/STGNN-output/structured_a3_fullfit"))
    parser.add_argument("--permutation-replicates", type=int, default=10)
    parser.add_argument("--correlation-sample", type=int, default=100_000)
    parser.add_argument("--seed", type=int, default=20261006)
    parser.add_argument("--repository-audit-root", type=Path, default=None)
    args = parser.parse_args()
    if args.stage == "fit":
        if args.permutation_replicates != 10:
            raise RuntimeError("permutation replicate count is predeclared at 10 for this workflow")
        bundle = load_bundle(args)
        horizon, support = completeness(bundle)
        fit = fit_full(bundle, horizon)
        save_fit_outputs(bundle, horizon, support, fit, args)
        update_model_manifest(args.output_root)
        print(json.dumps({"status": "fit_complete", "fit_end_week": horizon["full_fit_end_week"], "node_count": NODE_COUNT, "predictor_count": len(FEATURE_ORDER), "theta": FIXED_THETA, "penalty": PENALTY, "occurrence_converged": fit["state"]["fit_info"].get("occurrence_success"), "count_converged": fit["state"]["fit_info"].get("count_success")}, indent=2))
    else:
        finalize(args)
        print(json.dumps({"status": "finalized", "output_root": str(args.output_root)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
