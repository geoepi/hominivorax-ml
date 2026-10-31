#!/usr/bin/env python3
"""Run the prespecified P7G manuscript-evidence analyses.

This script is evaluation-only.  It reads the canonical P2 prediction archive,
the canonical P4 support classifications, the frozen A3 coefficients/scaling,
and the canonical P2 feature cache.  It never calls a model-fitting routine.
The intended execution environment is the validated Atlas Python environment.
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
from datetime import date, timedelta, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from scipy import sparse
from scipy.stats import rankdata
from sklearn.metrics import average_precision_score
from sklearn.linear_model import LogisticRegression


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
P2_SCRIPT_ROOT = REPOSITORY_ROOT / "analysis" / "p2_operational_nowcast" / "scripts"
sys.path.insert(0, str(P2_SCRIPT_ROOT))
from run_p2_operational_nowcast import (  # noqa: E402
    FEATURE_COUNT,
    FEATURE_ORDER,
    NODE_COUNT,
    occurrence_metrics,
    standardize,
)


MODEL_ID = "STRUCTURED_A3"
P0_MODEL_SHA256 = "8a6a0a32a1a1e56f810b6aa1eafec5207dc3ac8d45cdf2270999f9721f080d1e"
P2_ARCHIVE_SHA256 = "918b33e80d352c080fcefb3d7b2a44dc29d0096b0b2e7dd6f5b017becc983170"
P4_SUPPORT_SHA256 = "c35bf794fcc882e3ea71bc1a279b90e4f32aeff412a9399f2fb25e383141d058"
P2_ROWS = 632331
TRAIN_WEEK_COUNT = 68
TRAIN_REFERENCE = "2025-W01:2026-W16"
ORIGINS = [f"2026-W{week:02d}" for week in range(16, 37)]
HORIZONS = (1, 2, 3)
SUPPORT_CLASSES = ("SUPPORTED", "CAUTION", "EXTRAPOLATIVE")
BOOTSTRAP_REPLICATES = 199
BOOTSTRAP_SEED = 20261029
SPATIAL_SHELLS = (1, 2, 3, 4)
TOP_FRACTIONS = (0.01, 0.05, 0.10, 0.20)
P2_KEYS = ["origin_week", "target_week", "horizon", "model_node_id"]
REQUIRED_P2 = P2_KEYS + [
    "row", "column", "lon", "lat", "country_or_domain_region", "observed_count",
    "observed_positive", "p_occurrence", "conditional_count_mean", "underlying_mu",
    "expected_count", "previously_occupied", "prediction_frontier_class",
    "outcome_frontier_label",
]


def fail(message: str) -> None:
    raise RuntimeError(f"P7G_BLOCKED: {message}")


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


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
    atomic_write(path, lambda target: frame.to_csv(target, index=False, na_rep=""))


def parse_week(label: str) -> date:
    year, week = str(label).split("-W")
    return date.fromisocalendar(int(year), int(week), 1)


def week_distance(left: str, right: str) -> int:
    return (parse_week(right) - parse_week(left)).days // 7


def git_value(repo: Path, *args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", "-c", f"safe.directory={repo.as_posix()}", *args],
            cwd=repo, text=True, stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


def finite_corr(x: np.ndarray, y: np.ndarray, method: str = "pearson") -> tuple[float, int, str]:
    mask = np.isfinite(x) & np.isfinite(y)
    if int(mask.sum()) < 3:
        return math.nan, int(mask.sum()), "not_estimable_insufficient_pairs"
    xx = np.asarray(x[mask], dtype=float)
    yy = np.asarray(y[mask], dtype=float)
    if method == "spearman":
        xx = rankdata(xx, method="average")
        yy = rankdata(yy, method="average")
    if np.std(xx) <= 0 or np.std(yy) <= 0:
        return math.nan, int(mask.sum()), "not_estimable_zero_variance"
    return float(np.corrcoef(xx, yy)[0, 1]), int(mask.sum()), "estimable"


def moran(values: np.ndarray, source: np.ndarray, target: np.ndarray) -> tuple[float, int, str]:
    values = np.asarray(values, dtype=float)
    finite = np.isfinite(values)
    if int(finite.sum()) < 3:
        return math.nan, int(finite.sum()), "not_estimable_insufficient_values"
    keep = finite[source] & finite[target]
    source2 = source[keep]
    target2 = target[keep]
    if len(source2) == 0:
        return math.nan, 0, "not_estimable_no_finite_edges"
    x = values[finite]
    mean = float(x.mean())
    denominator = float(np.sum((x - mean) ** 2))
    if denominator <= 0:
        return math.nan, int(len(source2)), "not_estimable_zero_variance"
    centered = values - mean
    return float(len(x) / len(source2) * np.sum(centered[source2] * centered[target2]) / denominator), int(len(source2)), "estimable"


def read_sources(args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    p2_manifest_path = args.repository_root / "analysis/p2_operational_nowcast/results/prediction_archive_manifest.json"
    p4_metadata_path = args.repository_root / "analysis/p4_uncertainty_extrapolation/results/p4_run_metadata.json"
    require(p2_manifest_path.exists(), f"missing P2 manifest: {p2_manifest_path}")
    require(p4_metadata_path.exists(), f"missing P4 metadata: {p4_metadata_path}")
    p2_manifest = json.loads(p2_manifest_path.read_text(encoding="utf-8"))
    p4_metadata = json.loads(p4_metadata_path.read_text(encoding="utf-8"))
    require(args.p2_archive.exists(), f"missing P2 archive: {args.p2_archive}")
    p2_sha = sha256_file(args.p2_archive)
    require(p2_sha == P2_ARCHIVE_SHA256, f"P2 archive hash mismatch: {p2_sha}")
    p2 = pd.read_parquet(args.p2_archive)
    require(len(p2) == P2_ROWS, f"P2 row count changed: {len(p2)}")
    missing = sorted(set(REQUIRED_P2).difference(p2.columns))
    require(not missing, f"P2 missing required columns: {missing}")
    require(set(p2["horizon"].astype(int).unique()) == set(HORIZONS), "P2 horizons changed")
    require(set(p2["origin_week"].astype(str).unique()) == set(ORIGINS), "P2 origins changed")
    require(not p2.duplicated(P2_KEYS).any(), "P2 prediction keys are duplicated")
    require(args.p4_support.exists(), f"missing P4 support archive: {args.p4_support}")
    p4_sha = sha256_file(args.p4_support)
    require(p4_sha == P4_SUPPORT_SHA256, f"P4 support hash mismatch: {p4_sha}")
    support = pd.read_parquet(args.p4_support)
    require(len(support) == P2_ROWS, f"P4 support row count changed: {len(support)}")
    require(set(P2_KEYS + ["support_class"]).issubset(support.columns), "P4 support schema is incomplete")
    require(not support.duplicated(P2_KEYS).any(), "P4 support keys are duplicated")
    support = support[P2_KEYS + ["support_class"]].copy()
    require(set(support["support_class"].dropna().unique()).issubset(set(SUPPORT_CLASSES)), "unknown P4 support class")
    merged = p2.merge(support, on=P2_KEYS, how="left", validate="one_to_one", indicator=True)
    require((merged["_merge"] == "both").all(), "P4 support join is incomplete")
    merged = merged.drop(columns="_merge")
    merged["horizon"] = merged["horizon"].astype(int)
    merged["model_node_id"] = merged["model_node_id"].astype(int)
    merged["target_week"] = merged["target_week"].astype(str)
    merged["origin_week"] = merged["origin_week"].astype(str)
    source = {
        "p2_manifest_sha256": sha256_file(p2_manifest_path),
        "p2_archive": {"path": str(args.p2_archive), "sha256": p2_sha, "rows": len(p2), "manifest_entry": p2_manifest.get("combined_prediction_archive")},
        "p4_metadata": {"path": str(p4_metadata_path), "sha256": sha256_file(p4_metadata_path), "output_root": p4_metadata.get("atlas_output_root")},
        "p4_support": {"path": str(args.p4_support), "sha256": p4_sha, "rows": len(support)},
    }
    return merged, support, source


def build_shells(edges: pd.DataFrame) -> dict[int, tuple[np.ndarray, np.ndarray]]:
    require({"source_node", "target_node"}.issubset(edges.columns), "queen graph edge schema is incomplete")
    src = edges["source_node"].to_numpy(np.int64)
    dst = edges["target_node"].to_numpy(np.int64)
    require(len(src) > 0 and src.min() >= 0 and dst.min() >= 0 and src.max() < NODE_COUNT and dst.max() < NODE_COUNT, "queen graph node range changed")
    adjacency = sparse.csr_matrix((np.ones(len(src), dtype=np.int8), (src, dst)), shape=(NODE_COUNT, NODE_COUNT), dtype=np.int8)
    adjacency = adjacency.maximum(adjacency.T).astype(bool)
    adjacency.setdiag(False)
    adjacency.eliminate_zeros()
    identity = sparse.identity(NODE_COUNT, format="csr", dtype=bool)
    visited = identity.copy()
    frontier = adjacency
    shells: dict[int, tuple[np.ndarray, np.ndarray]] = {}
    for order in SPATIAL_SHELLS:
        if order > 1:
            candidate = (frontier @ adjacency).astype(np.int8)
            candidate = candidate - visited.astype(np.int8)
            candidate.data[candidate.data < 0] = 0
            candidate = candidate.astype(bool)
            candidate.setdiag(False)
            candidate.eliminate_zeros()
            frontier = candidate
        visited = (visited + frontier).astype(bool)
        s, t = frontier.nonzero()
        shells[order] = (np.asarray(s, dtype=np.int64), np.asarray(t, dtype=np.int64))
    return shells


def spatial_analysis(frame: pd.DataFrame, edges: pd.DataFrame, output: Path) -> None:
    shells = build_shells(edges)
    global_rows: list[dict[str, Any]] = []
    shell_rows: list[dict[str, Any]] = []
    variables = {
        "raw_occurrence": lambda d: d["observed_positive"].to_numpy(float),
        "residual_occurrence": lambda d: d["observed_positive"].to_numpy(float) - d["p_occurrence"].to_numpy(float),
        "raw_positive_count": lambda d: np.where(d["observed_count"].to_numpy(float) > 0, d["observed_count"].to_numpy(float), np.nan),
        "residual_positive_count": lambda d: np.where(d["observed_count"].to_numpy(float) > 0, d["observed_count"].to_numpy(float) - d["conditional_count_mean"].to_numpy(float), np.nan),
        "raw_full_count": lambda d: d["observed_count"].to_numpy(float),
        "residual_full_count": lambda d: d["observed_count"].to_numpy(float) - d["expected_count"].to_numpy(float),
    }
    for horizon in HORIZONS:
        sub = frame.loc[frame["horizon"] == horizon]
        node_means: dict[str, np.ndarray] = {}
        for variable, fn in variables.items():
            values = np.full(NODE_COUNT, np.nan, dtype=float)
            sums = np.zeros(NODE_COUNT, dtype=float)
            counts = np.zeros(NODE_COUNT, dtype=float)
            for _, group in sub.groupby("target_week", sort=True):
                group = group.sort_values("model_node_id")
                x = fn(group)
                node = group["model_node_id"].to_numpy(int)
                mask = np.isfinite(x)
                sums[node[mask]] += x[mask]
                counts[node[mask]] += 1
                statistic, n_pairs, status = moran(x, edges["source_node"].to_numpy(np.int64), edges["target_node"].to_numpy(np.int64))
                global_rows.append({"scope": "target_week", "horizon": horizon, "target_week": str(group["target_week"].iloc[0]), "variable": variable, "moran_i": statistic, "n_values": int(mask.sum()), "n_edges": n_pairs, "status": status})
            np.divide(sums, counts, out=values, where=counts > 0)
            node_means[variable] = values
        for variable, values in node_means.items():
            for shell_order, (src, dst) in shells.items():
                statistic, n_pairs, status = moran(values, src, dst)
                shell_rows.append({"scope": "pooled_node_mean", "horizon": horizon, "shell_order": shell_order, "variable": variable, "moran_i": statistic, "n_values": int(np.isfinite(values).sum()), "n_pairs": n_pairs, "status": status})
    write_csv(output / "spatial_dependence.csv", pd.DataFrame(global_rows).sort_values(["horizon", "target_week", "variable"]))
    write_csv(output / "spatial_shell_dependence.csv", pd.DataFrame(shell_rows).sort_values(["horizon", "shell_order", "variable"]))


def temporal_analysis(frame: pd.DataFrame, output: Path) -> None:
    rows: list[dict[str, Any]] = []
    variables = {
        "raw_occurrence": lambda d: d["observed_positive"].to_numpy(float),
        "residual_occurrence": lambda d: d["observed_positive"].to_numpy(float) - d["p_occurrence"].to_numpy(float),
        "raw_positive_count": lambda d: np.where(d["observed_count"].to_numpy(float) > 0, d["observed_count"].to_numpy(float), np.nan),
        "residual_positive_count": lambda d: np.where(d["observed_count"].to_numpy(float) > 0, d["observed_count"].to_numpy(float) - d["conditional_count_mean"].to_numpy(float), np.nan),
    }
    for horizon in HORIZONS:
        sub = frame.loc[frame["horizon"] == horizon].sort_values(["target_week", "model_node_id"])
        weeks = sorted(sub["target_week"].unique(), key=parse_week)
        matrices: dict[str, np.ndarray] = {}
        for name, fn in variables.items():
            matrix = np.full((len(weeks), NODE_COUNT), np.nan, dtype=float)
            for i, week in enumerate(weeks):
                group = sub.loc[sub["target_week"] == week].sort_values("model_node_id")
                require(len(group) == NODE_COUNT and group["model_node_id"].to_numpy(int).tolist() == list(range(NODE_COUNT)), f"temporal node grid changed for {week} h={horizon}")
                matrix[i] = fn(group)
            matrices[name] = matrix
        for lag in (1, 2, 3):
            for variable, matrix in matrices.items():
                if len(weeks) <= lag:
                    rows.append({"horizon": horizon, "lag_weeks": lag, "variable": variable, "scope": "pooled", "correlation": math.nan, "n_pairs": 0, "status": "not_estimable_insufficient_weeks"})
                    continue
                x = matrix[:-lag].reshape(-1)
                y = matrix[lag:].reshape(-1)
                corr, n_pairs, status = finite_corr(x, y)
                node_corr = []
                for node in range(NODE_COUNT):
                    c, n, s = finite_corr(matrix[:-lag, node], matrix[lag:, node])
                    if s == "estimable":
                        node_corr.append(c)
                rows.append({"horizon": horizon, "lag_weeks": lag, "variable": variable, "scope": "pooled", "correlation": corr, "n_pairs": n_pairs, "status": status})
                rows.append({"horizon": horizon, "lag_weeks": lag, "variable": variable, "scope": "node_median", "correlation": float(np.median(node_corr)) if node_corr else math.nan, "n_pairs": len(node_corr), "status": "estimable" if node_corr else "not_estimable"})
    write_csv(output / "temporal_dependence.csv", pd.DataFrame(rows).sort_values(["horizon", "lag_weeks", "variable", "scope"]))


def risk_percentiles(group: pd.DataFrame, score: str) -> pd.Series:
    values = group[score].to_numpy(float)
    ranks = rankdata(values, method="average")
    return pd.Series(100.0 * (ranks - 0.5) / len(values), index=group.index)


def early_warning_analysis(frame: pd.DataFrame, output: Path) -> None:
    candidates = frame.loc[(frame["observed_positive"].astype(int) > 0) & (frame["previously_occupied"].astype(bool) == False)].copy()  # noqa: E712
    candidates = candidates.sort_values(["model_node_id", "target_week", "horizon", "origin_week"])
    first = candidates.drop_duplicates(["model_node_id"], keep="first")
    require(len(first) > 0, "no first-recorded detections are available")
    event_rows: list[dict[str, Any]] = []
    score_columns = ["p_occurrence"]
    for name in ("historical_prevalence_probability", "persistence_probability"):
        if name in frame.columns:
            score_columns.append(name)
    for _, event in first.iterrows():
        key = (event["model_node_id"], event["target_week"])
        for horizon in HORIZONS:
            rows = frame.loc[(frame["model_node_id"] == key[0]) & (frame["target_week"] == key[1]) & (frame["horizon"] == horizon)]
            if len(rows) != 1:
                continue
            row = rows.iloc[0]
            base = frame.loc[(frame["origin_week"] == row["origin_week"]) & (frame["target_week"] == row["target_week"]) & (frame["horizon"] == horizon)]
            for pool_name, pool in (("FULL_DOMAIN", base), ("FRONTIER_RELATIVE", base.loc[base["previously_occupied"].astype(bool) == False])):  # noqa: E712
                if len(pool) == 0 or row["model_node_id"] not in set(pool["model_node_id"]):
                    continue
                for score in score_columns:
                    values = pd.to_numeric(pool[score], errors="coerce")
                    if values.notna().sum() < 3 or values.nunique(dropna=True) < 2:
                        event_rows.append({"model_node_id": int(row["model_node_id"]), "target_week": str(row["target_week"]), "horizon": horizon, "pool": pool_name, "score": score, "score_value": float(row[score]) if pd.notna(row[score]) else math.nan, "risk_percentile": math.nan, "n_pool": int(values.notna().sum()), "status": "not_informative"})
                        continue
                    valid = pool.loc[values.notna()].copy()
                    valid["_risk_percentile"] = risk_percentiles(valid, score)
                    matched = valid.loc[valid["model_node_id"] == row["model_node_id"]]
                    if len(matched) != 1:
                        continue
                    event_rows.append({"model_node_id": int(row["model_node_id"]), "target_week": str(row["target_week"]), "horizon": horizon, "pool": pool_name, "score": score, "score_value": float(row[score]), "risk_percentile": float(matched["_risk_percentile"].iloc[0]), "n_pool": int(len(valid)), "status": "estimable"})
    events = pd.DataFrame(event_rows)
    summary: list[dict[str, Any]] = []
    for (horizon, pool, score), group in events.groupby(["horizon", "pool", "score"], sort=True):
        for fraction in TOP_FRACTIONS:
            estimable = group.loc[group["status"] == "estimable"]
            captured = estimable["risk_percentile"] >= 100.0 * (1.0 - fraction)
            summary.append({"horizon": int(horizon), "pool": pool, "score": score, "top_fraction": fraction, "threshold_percentile": 100.0 * (1.0 - fraction), "event_n": int(len(estimable)), "captured_n": int(captured.sum()), "capture_fraction": float(captured.mean()) if len(captured) else math.nan, "status": "estimable" if len(estimable) else "not_estimable"})
    write_csv(output / "early_warning_topk.csv", pd.DataFrame(summary).sort_values(["score", "pool", "horizon", "top_fraction"]))
    write_csv(output / "first_detection_event_rankings.csv", events.sort_values(["target_week", "model_node_id", "horizon", "pool", "score"]))
    trajectories: list[dict[str, Any]] = []
    primary = events.loc[(events["score"] == "p_occurrence") & (events["pool"].isin(["FULL_DOMAIN", "FRONTIER_RELATIVE"])) & (events["status"] == "estimable")].copy()
    for pool, group in primary.groupby("pool"):
        pivot = group.pivot_table(index=["model_node_id", "target_week"], columns="horizon", values="risk_percentile", aggfunc="first")
        complete = pivot.dropna(subset=list(HORIZONS))
        for index, row in complete.iterrows():
            trajectories.append({"pool": pool, "model_node_id": int(index[0]), "target_week": str(index[1]), "h1_percentile": float(row[1]), "h2_percentile": float(row[2]), "h3_percentile": float(row[3]), "h3_to_h1_change": float(row[1] - row[3])})
    write_csv(output / "early_warning_trajectory.csv", pd.DataFrame(trajectories))
    write_json(output / "early_warning_metadata.json", {"first_detection_cells": int(first["model_node_id"].nunique()), "first_detection_rows": int(len(first)), "excluded_missing_horizon_records": int(len(first) * 3 - events.loc[events["score"] == "p_occurrence", "horizon"].nunique()), "rank_formula": "100 * (midrank - 0.5) / n", "top_fractions": list(TOP_FRACTIONS), "reference_scores": [x for x in score_columns if x != "p_occurrence"]})


def predictor_analysis(args: argparse.Namespace, output: Path) -> dict[str, Any]:
    feature_cache = np.load(args.feature_cache, mmap_mode="r")
    require(tuple(feature_cache.shape) == (91, NODE_COUNT, FEATURE_COUNT), f"feature cache shape changed: {feature_cache.shape}")
    raw = np.asarray(feature_cache[:TRAIN_WEEK_COUNT], dtype=np.float64).reshape(-1, FEATURE_COUNT)
    standardized, _, state = standardize(raw, raw, FEATURE_ORDER)
    model = json.loads(args.model_json.read_text(encoding="utf-8"))
    require(model.get("feature_order") == list(FEATURE_ORDER), "frozen model feature order changed")
    require(len(model.get("occurrence_coefficients", [])) == FEATURE_COUNT + 1 and len(model.get("count_coefficients", [])) == FEATURE_COUNT + 1, "frozen coefficient length changed")
    scaling = pd.read_csv(args.scaling_csv)
    require(list(scaling["predictor"].astype(str)) == list(FEATURE_ORDER), "frozen scaling order changed")
    assoc_rows: list[dict[str, Any]] = []
    occ_beta = np.asarray(model["occurrence_coefficients"], dtype=float)[1:]
    count_beta = np.asarray(model["count_coefficients"], dtype=float)[1:]
    categories: dict[str, str] = {}
    for i, name in enumerate(FEATURE_ORDER):
        raw_values = raw[:, i]
        finite = raw_values[np.isfinite(raw_values)]
        q25, q75 = (float(np.quantile(finite, 0.25)), float(np.quantile(finite, 0.75))) if len(finite) else (math.nan, math.nan)
        scaled = bool(scaling.loc[i, "scaled"])
        if name in {"week_sin", "week_cos"}:
            category = "calendar"
        elif name.endswith("_imputed"):
            category = "imputation_indicator"
        elif name in {"any_prior_positive_available", "prev4_positive_available", "detection_within_50km_ever_available"}:
            category = "binary_availability_indicator"
        elif not scaled:
            category = "identity_unstandardized"
        else:
            category = "continuous_standardized"
        categories[name] = category
        if category in {"calendar", "binary_availability_indicator", "imputation_indicator"}:
            delta_raw = 1.0 if category != "calendar" else q75 - q25
        else:
            delta_raw = q75 - q25
        sd = float(scaling.loc[i, "training_sd"])
        delta_fitted = delta_raw / sd if scaled and np.isfinite(sd) and sd > 0 else delta_raw
        for component, beta in (("occurrence", occ_beta[i]), ("positive_count", count_beta[i])):
            linear = float(beta * delta_fitted) if np.isfinite(delta_fitted) else math.nan
            assoc_rows.append({"predictor": name, "feature_index": i, "component": component, "category": category, "scaled_in_fitted_model": scaled, "training_q25": q25, "training_q75": q75, "contrast_raw": delta_raw, "contrast_fitted_scale": delta_fitted, "coefficient": float(beta), "coefficient_contrast": linear, "odds_or_mean_parameter_ratio": float(np.exp(linear)) if component == "occurrence" and np.isfinite(linear) else (float(np.exp(linear)) if component == "positive_count" and np.isfinite(linear) else math.nan), "interpretation": "conditional predictive association; not causal"})
    write_csv(output / "predictor_standardized_associations.csv", pd.DataFrame(assoc_rows).sort_values(["component", "feature_index"]))
    dep_rows: list[dict[str, Any]] = []
    for i in range(FEATURE_COUNT):
        for j in range(i + 1, FEATURE_COUNT):
            pearson, n_p, ps = finite_corr(raw[:, i], raw[:, j], "pearson")
            spearman, n_s, ss = finite_corr(raw[:, i], raw[:, j], "spearman")
            max_abs = max(abs(pearson) if np.isfinite(pearson) else 0.0, abs(spearman) if np.isfinite(spearman) else 0.0)
            flag = "HIGH_DEPENDENCE" if max_abs >= 0.90 else ("DEPENDENCE_WARNING" if max_abs >= 0.70 else "none")
            dep_rows.append({"predictor_a": FEATURE_ORDER[i], "predictor_b": FEATURE_ORDER[j], "pearson": pearson, "spearman": spearman, "n_pearson": n_p, "n_spearman": n_s, "flag": flag, "estimability": "estimable" if ps == "estimable" and ss == "estimable" else f"{ps};{ss}"})
    dependence = pd.DataFrame(dep_rows).sort_values(["flag", "predictor_a", "predictor_b"])
    write_csv(output / "predictor_dependence_pairs.csv", dependence)
    write_csv(output / "predictor_dependence_summary.csv", pd.DataFrame([{"threshold_abs_correlation": 0.70, "pair_count": int((dependence["flag"] == "DEPENDENCE_WARNING").sum() + (dependence["flag"] == "HIGH_DEPENDENCE").sum()), "meaning": "dependence warning"}, {"threshold_abs_correlation": 0.90, "pair_count": int((dependence["flag"] == "HIGH_DEPENDENCE").sum()), "meaning": "high dependence"}]))
    return {"training_rows": int(len(raw)), "training_reference": TRAIN_REFERENCE, "standardize_state_matches_cache": bool(np.isfinite(standardized).all()), "p4_coefficient_bootstrap_available": False, "p4_coefficient_bootstrap_reason": "No bootstrap_coefficient_stability.csv was retained in the canonical P4 output root; no new coefficient refitting was performed.", "predictor_count": FEATURE_COUNT}


def support_metric_row(group: pd.DataFrame, horizon: int, support_class: str) -> dict[str, Any]:
    metrics = occurrence_metrics(group)
    return {"horizon": horizon, "support_class": support_class, **metrics, "status": "estimable" if metrics["n"] > 0 else "not_estimable"}


def calibration_reliability(group: pd.DataFrame, horizon: int, support_class: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    p = group["p_occurrence"].to_numpy(float)
    y = group["observed_positive"].to_numpy(np.int8)
    edges = np.linspace(0.0, 1.0, 11)
    bucket = np.minimum(np.digitize(p, edges, right=False) - 1, 9)
    for index in range(10):
        mask = bucket == index
        n = int(mask.sum())
        rows.append({"horizon": horizon, "support_class": support_class, "bin_index": index, "lower": float(edges[index]), "upper": float(edges[index + 1]), "n": n, "positive_n": int(y[mask].sum()) if n else 0, "mean_predicted": float(p[mask].mean()) if n else math.nan, "observed_probability": float(y[mask].mean()) if n else math.nan, "deterministic_rule": "P2 fixed equal-width probability bins; no post-hoc merging"})
    return rows


def support_bootstrap(group: pd.DataFrame, horizon: int, support_class: str) -> dict[str, Any]:
    weeks = sorted(group["target_week"].astype(str).unique(), key=parse_week)
    positions = {week: np.flatnonzero(group["target_week"].astype(str).to_numpy() == week) for week in weeks}
    rng = np.random.default_rng(BOOTSTRAP_SEED + horizon * 100 + list(SUPPORT_CLASSES).index(support_class))
    brier: list[float] = []
    auprc: list[float] = []
    for _ in range(BOOTSTRAP_REPLICATES):
        selected_weeks = rng.choice(np.asarray(weeks, dtype=object), size=len(weeks), replace=True)
        indices = np.concatenate([positions[str(week)] for week in selected_weeks]) if len(selected_weeks) else np.asarray([], dtype=int)
        y = group.iloc[indices]["observed_positive"].to_numpy(np.int8)
        p = np.clip(group.iloc[indices]["p_occurrence"].to_numpy(float), 1e-12, 1 - 1e-12)
        brier.append(float(np.mean((p - y) ** 2)))
        auprc.append(float(average_precision_score(y, p)) if len(np.unique(y)) == 2 else math.nan)
    return {"horizon": horizon, "support_class": support_class, "bootstrap_replicates": BOOTSTRAP_REPLICATES, "bootstrap_seed": BOOTSTRAP_SEED + horizon * 100 + list(SUPPORT_CLASSES).index(support_class), "brier_lower": float(np.nanquantile(brier, 0.025)), "brier_upper": float(np.nanquantile(brier, 0.975)), "auprc_lower": float(np.nanquantile(auprc, 0.025)) if np.isfinite(auprc).any() else math.nan, "auprc_upper": float(np.nanquantile(auprc, 0.975)) if np.isfinite(auprc).any() else math.nan, "blocking": False}


def support_analysis(frame: pd.DataFrame, output: Path) -> None:
    metric_rows: list[dict[str, Any]] = []
    reliability: list[dict[str, Any]] = []
    bootstrap: list[dict[str, Any]] = []
    for horizon in HORIZONS:
        for support_class in SUPPORT_CLASSES:
            group = frame.loc[(frame["horizon"] == horizon) & (frame["support_class"] == support_class)].copy()
            metric_rows.append(support_metric_row(group, horizon, support_class))
            reliability.extend(calibration_reliability(group, horizon, support_class))
            bootstrap.append(support_bootstrap(group, horizon, support_class))
    write_csv(output / "support_horizon_calibration_metrics.csv", pd.DataFrame(metric_rows).sort_values(["horizon", "support_class"]))
    write_csv(output / "support_horizon_reliability.csv", pd.DataFrame(reliability).sort_values(["horizon", "support_class", "bin_index"]))
    write_csv(output / "support_horizon_bootstrap_ci.csv", pd.DataFrame(bootstrap).sort_values(["horizon", "support_class"]))
    counts = frame.groupby("support_class", dropna=False).size().rename("n").reset_index()
    counts["proportion"] = counts["n"] / len(frame)
    write_csv(output / "support_class_proportions.csv", counts.sort_values("support_class"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument("--p2-archive", type=Path, required=True)
    parser.add_argument("--p4-support", type=Path, required=True)
    parser.add_argument("--feature-cache", type=Path, required=True)
    parser.add_argument("--nodes", type=Path, required=True)
    parser.add_argument("--edges", type=Path, required=True)
    parser.add_argument("--model-json", type=Path, default=None)
    parser.add_argument("--scaling-csv", type=Path, default=None)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    args.repository_root = args.repository_root.resolve()
    args.p2_archive = args.p2_archive.resolve()
    args.p4_support = args.p4_support.resolve()
    args.feature_cache = args.feature_cache.resolve()
    args.nodes = args.nodes.resolve()
    args.edges = args.edges.resolve()
    args.output_root = args.output_root.resolve()
    args.model_json = (args.model_json or (args.repository_root / "analysis/structured_a3_evaluation/results/final_a3_model.json")).resolve()
    args.scaling_csv = (args.scaling_csv or (args.repository_root / "analysis/structured_a3_evaluation/results/final_a3_scaling_parameters.csv")).resolve()
    args.output_root.mkdir(parents=True, exist_ok=True)
    output = args.output_root
    frame, support, source = read_sources(args)
    nodes = pd.read_parquet(args.nodes)
    edges = pd.read_parquet(args.edges)
    require(len(nodes) == NODE_COUNT and set(["model_node_id", "lon", "lat"]).issubset(nodes.columns), "canonical node table changed")
    require(nodes["model_node_id"].to_numpy(int).tolist() == list(range(NODE_COUNT)), "canonical node order changed")
    require(len(edges) > 0, "canonical queen graph is empty")
    source.update({"nodes": {"path": str(args.nodes), "sha256": sha256_file(args.nodes), "rows": len(nodes)}, "edges": {"path": str(args.edges), "sha256": sha256_file(args.edges), "rows": len(edges)}, "feature_cache": {"path": str(args.feature_cache), "sha256": sha256_file(args.feature_cache), "shape": list(np.load(args.feature_cache, mmap_mode="r").shape)}, "frozen_model": {"path": str(args.model_json), "sha256": sha256_file(args.model_json)}, "frozen_scaling": {"path": str(args.scaling_csv), "sha256": sha256_file(args.scaling_csv)}})
    write_json(output / "source_hash_manifest.json", source)
    spatial_analysis(frame, edges, output)
    temporal_analysis(frame, output)
    early_warning_analysis(frame, output)
    predictor_meta = predictor_analysis(args, output)
    support_analysis(frame, output)
    write_json(output / "predictor_analysis_metadata.json", predictor_meta)
    write_json(output / "configuration.json", {"model_id": MODEL_ID, "p0_model_sha256": P0_MODEL_SHA256, "p2_archive_sha256": P2_ARCHIVE_SHA256, "p4_support_sha256": P4_SUPPORT_SHA256, "origins": ORIGINS, "horizons": list(HORIZONS), "train_reference": TRAIN_REFERENCE, "spatial_shells": list(SPATIAL_SHELLS), "temporal_lags": [1, 2, 3], "top_fractions": list(TOP_FRACTIONS), "dependence_thresholds": {"warning": 0.70, "high": 0.90}, "support_bootstrap_replicates": BOOTSTRAP_REPLICATES, "support_bootstrap_seed": BOOTSTRAP_SEED, "no_model_fitting": True, "p4_bootstrap_reused": False})
    decision = {"status": "complete_with_limitations", "decision": "P7G_MANUSCRIPT_EVIDENCE_COMPLETE_WITH_LIMITATIONS", "limitations": ["P4 coefficient-bootstrap stability artifact was not retained in the canonical P4 output root, so no coefficient interval/stability panel was generated.", "Support-stratified estimates and first-detection strata are descriptive and may be sparse.", "The P2 archive is retrospective realized-environment evaluation; no prospective environmental data are introduced."], "source_hash_manifest": str(output / "source_hash_manifest.json"), "no_model_fitting": True}
    write_json(output / "decision.json", decision)
    write_json(output / "run_metadata.json", {"status": "completed", "repository_sha": git_value(args.repository_root, "rev-parse", "HEAD"), "repository_branch": git_value(args.repository_root, "branch", "--show-current"), "python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__, "generated_utc": datetime.now(timezone.utc).isoformat(), "output_root": str(output), "no_model_fitting": True})
    print(json.dumps({"status": "completed", "output_root": str(output), "decision": decision["decision"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
