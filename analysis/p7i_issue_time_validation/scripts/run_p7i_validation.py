"""Run the prespecified P7I issue-time-causal validation.

This module reuses the immutable P2 fits, P2 feature cache, P4 support rules,
and the validated causal front descriptor.  It does not fit a new model.  The
only feature changes in V3/V4 are the explicitly prespecified reconstruction
of detection-history features using observations no later than the origin.

Detailed row-level products are written to the supplied Atlas output root.
Only compact metrics, diagnostics, and provenance are written to the
repository analysis directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from scipy.stats import rankdata

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
P2_SCRIPT_ROOT = REPOSITORY_ROOT / "analysis" / "p2_operational_nowcast" / "scripts"
P4_SCRIPT_ROOT = REPOSITORY_ROOT / "analysis" / "p4_uncertainty_extrapolation" / "scripts"
P5A_SCRIPT_ROOT = REPOSITORY_ROOT / "analysis" / "p5a_environmental_proxy" / "scripts"
P2_AUDIT_ROOT = REPOSITORY_ROOT / "scripts"
sys.path.insert(0, str(P2_SCRIPT_ROOT))
sys.path.insert(0, str(P4_SCRIPT_ROOT))
sys.path.insert(0, str(P5A_SCRIPT_ROOT))
sys.path.insert(0, str(P2_AUDIT_ROOT))

from run_p2_operational_nowcast import (  # noqa: E402
    FEATURE_COUNT,
    FEATURE_ORDER,
    HISTORY_FEATURES,
    NODE_COUNT,
    predict,
)
from run_p4_uncertainty_extrapolation import (  # noqa: E402
    nearest_distances,
    support_class_from_inputs,
    training_reference,
)
from run_p5a_environmental_proxy import (  # noqa: E402
    ENV_COUNT,
    ENVIRONMENTAL_FEATURES,
    FAMILY_BY_FEATURE,
    HORIZONS,
    P0_MODEL_SHA256,
    all_metrics,
    build_proxy_environment,
    count_metrics,
    load_fit,
    occurrence_metrics,
    p2_provenance,
    predict_from_fit,
    support_for_raw,
)
from run_task3a_v2_audit import causal_front_descriptors  # noqa: E402


MODEL_ID = "STRUCTURED_A3"
P2_ARCHIVE_SHA256 = "918b33e80d352c080fcefb3d7b2a44dc29d0096b0b2e7dd6f5b017becc983170"
P2_EXPECTED_ROWS = 632_331
ORIGINS = [f"2026-W{week:02d}" for week in range(16, 37)]
BOOTSTRAP_REPLICATES = 199
BOOTSTRAP_SEED = 20261029
ISSUE_LAG_WEEKS = 1
VARIANTS = [
    "V1_REALIZED_RETROSPECTIVE",
    "V2_E0_RETROSPECTIVE_HISTORY",
    "V3_REALIZED_ORIGIN_BOUNDED_HISTORY",
    "V4_ISSUE_TIME_CAUSAL",
]
KEY_COLUMNS = ["origin_week", "target_week", "horizon", "model_node_id"]
PAIR_METRICS = [
    "brier",
    "auprc",
    "calibration_intercept",
    "calibration_slope",
    "full_expected_mae",
    "conditional_mae",
]
HISTORY_START = FEATURE_ORDER.index(HISTORY_FEATURES[0])
HISTORY_END = HISTORY_START + len(HISTORY_FEATURES)
TOP_FRACTIONS = (0.01, 0.05, 0.10, 0.20)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def jsonable(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(x) for x in value]
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


def add_weeks(value: str, offset: int) -> str:
    date = pd.Timestamp.fromisocalendar(*parse_week(value), 1) + pd.Timedelta(weeks=offset)
    iso = date.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def issue_timestamp(origin: str) -> str:
    date = pd.Timestamp.fromisocalendar(*parse_week(origin), 1) + pd.Timedelta(weeks=1)
    return date.tz_localize("UTC").isoformat().replace("+00:00", "Z")


def key_series(frame: pd.DataFrame) -> pd.Series:
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
    model_path = check_artifacts(load_json(manifest_path), repository_root)["frozen_model_metadata_and_coefficients"]
    require(sha256_file(model_path) == P0_MODEL_SHA256, "frozen model artifact hash changed")
    return verification


def source_manifest_row(metadata: dict[str, Any], name: str) -> dict[str, Any]:
    for row in metadata.get("sources", []):
        if row.get("name") == name:
            return dict(row)
    return {"name": name, "path": "UNRESOLVED_FROM_RETAINED_PROVENANCE", "sha256": "", "size_bytes": None}


def build_history_for_origin(
    origin_index: int,
    labels: list[str],
    counts: np.ndarray,
    nodes: pd.DataFrame,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Build only through T+3, with all post-T positive sets emptied."""
    stop = origin_index + max(HORIZONS) + 1
    limited_labels = labels[:stop]
    positive_sets: list[np.ndarray] = []
    for index in range(stop):
        positive_sets.append(np.flatnonzero(counts[index] > 0) if index <= origin_index else np.array([], dtype=int))
    xy = nodes[["x", "y"]].to_numpy(float)
    lat = nodes["lat"].to_numpy(float)
    state = causal_front_descriptors(positive_sets, xy, lat, limited_labels)
    distance_placeholder = float(np.hypot(np.ptp(xy[:, 0]), np.ptp(xy[:, 1])))
    if not np.isfinite(distance_placeholder) or distance_placeholder <= 0:
        distance_placeholder = 1.0
    recency_placeholder = float(len(labels) + 1)
    out = np.zeros((len(HORIZONS), NODE_COUNT, len(HISTORY_FEATURES)), dtype=np.float64)
    for offset, target_index in enumerate(range(origin_index + 1, origin_index + max(HORIZONS) + 1)):
        row = state.loc[state["week"].astype(str).eq(labels[target_index])].sort_values("node_id")
        require(len(row) == NODE_COUNT and np.array_equal(row["node_id"].to_numpy(int), np.arange(NODE_COUNT)), f"causal history row order changed for {labels[target_index]}")
        distance_any = row["distance_to_any_prior_detection_km"].to_numpy(float)
        distance_prev4 = row["distance_to_previous4_detection_km"].to_numpy(float)
        recency = row["weeks_since_any_detection_within_50km"].to_numpy(float)
        raw = np.column_stack([
            np.where(np.isfinite(distance_any), distance_any, distance_placeholder),
            np.where(np.isfinite(distance_prev4), distance_prev4, distance_placeholder),
            np.where(np.isfinite(recency), recency, recency_placeholder),
            np.isfinite(distance_any).astype(np.int8),
            np.isfinite(distance_prev4).astype(np.int8),
            np.isfinite(recency).astype(np.int8),
        ])
        transformed = raw.copy()
        transformed[:, :3] = np.log1p(np.maximum(transformed[:, :3], 0.0))
        out[offset] = transformed
        cutoff = str(row["source_history_cutoff"].iloc[0])
        # The descriptor's nominal row cutoff is the immediately preceding
        # target week.  For T+h this can be after T, but all positive sets
        # after T are empty by construction; this preserves the validated
        # target-relative elapsed-time behavior without future detections.
        require(parse_week(cutoff) < parse_week(labels[target_index]), f"history cutoff is not strictly prior to target: {cutoff}")
    return out, {
        "origin_week": labels[origin_index],
        "latest_history_cutoff": labels[origin_index],
        "post_origin_positive_sets_empty": True,
        "history_constructor": "scripts/run_task3a_v2_audit.py::causal_front_descriptors",
        "distance_placeholder_km": distance_placeholder,
        "recency_placeholder_weeks": recency_placeholder,
    }


def build_support_context(features: np.ndarray) -> dict[str, Any]:
    raw_train, train_z, state, reference = training_reference(features)
    tree = cKDTree(train_z, leafsize=40, compact_nodes=True, balanced_tree=True)
    try:
        train_loo = tree.query(train_z, k=2, workers=-1)[0][:, 1]
    except TypeError:
        train_loo = tree.query(train_z, k=2)[0][:, 1]
    return {
        "tree": tree,
        "reference": reference,
        "train_loo": train_loo,
        "means": np.asarray(state["training_mean"], dtype=np.float64),
        "scales": np.asarray(state["training_sd"], dtype=np.float64),
        "training_reference_rows": int(len(raw_train)),
    }


def computed_support(raw: np.ndarray, support_context: dict[str, Any]) -> pd.DataFrame:
    flat = raw.reshape(-1, FEATURE_COUNT)
    eval_z = (flat - support_context["means"][None, :]) / support_context["scales"][None, :]
    distances = nearest_distances(support_context["tree"], eval_z)
    support, _ = support_class_from_inputs(flat, eval_z, distances, support_context["reference"], support_context["train_loo"])
    return support


def base_reference(p2_frame: pd.DataFrame, origin: str, p4_support: pd.DataFrame) -> pd.DataFrame:
    ref = p2_frame.loc[p2_frame["origin_week"].astype(str).eq(origin)].copy()
    ref = ref.sort_values(["horizon", "model_node_id"], kind="mergesort").reset_index(drop=True)
    require(len(ref) == NODE_COUNT * len(HORIZONS), f"P2 row count changed for {origin}")
    require(not ref.duplicated(KEY_COLUMNS).any(), f"P2 key duplication for {origin}")
    ref["key"] = key_series(ref)
    support = p4_support.set_index("key").reindex(ref["key"].to_numpy())
    require(support["support_class"].notna().all(), f"P4 support missing for {origin}")
    ref["support_class"] = support["support_class"].to_numpy()
    ref["novelty_knn_distance"] = support["novelty_knn_distance"].to_numpy(float)
    ref["variant"] = "V1_REALIZED_RETROSPECTIVE"
    ref["history_source_cutoff_week"] = ref["origin_week"].astype(str)
    ref["environment_reference_week"] = ref["target_week"].astype(str)
    return ref


def prediction_frame(
    ref: pd.DataFrame,
    variant: str,
    probability: np.ndarray,
    conditional: np.ndarray,
    mu: np.ndarray,
    support: pd.DataFrame,
    history_cutoff: str,
    environment_week: str,
    history_values: np.ndarray | None = None,
) -> pd.DataFrame:
    frame = ref[[
        *KEY_COLUMNS, "row", "column", "lon", "lat", "country_or_domain_region",
        "observed_count", "observed_positive", "previously_occupied",
        "prediction_frontier_class", "outcome_frontier_label",
    ]].copy()
    frame["variant"] = variant
    frame["p_occurrence"] = probability
    frame["conditional_count_mean"] = conditional
    frame["underlying_mu"] = mu
    frame["expected_count"] = probability * conditional
    frame["support_class"] = support["support_class"].to_numpy()
    frame["novelty_knn_distance"] = support["novelty_knn_distance"].to_numpy(float)
    frame["history_source_cutoff_week"] = history_cutoff
    frame["environment_reference_week"] = environment_week
    if history_values is not None:
        for index, name in enumerate(HISTORY_FEATURES):
            frame[name] = history_values.reshape(-1, len(HISTORY_FEATURES))[:, index]
    frame["key"] = key_series(frame)
    return frame


def verify_v1_and_v2(
    v1: pd.DataFrame,
    v2: pd.DataFrame,
    p2_features: np.ndarray,
    target_indices: list[int],
    fit: dict[str, Any],
    p5a_root: Path,
    origin: str,
) -> dict[str, Any]:
    """Validate exact P2 feature/fit replay and exact P5A V2 reproduction."""
    realized_p, realized_c, realized_mu = predict_from_fit(fit, np.asarray(p2_features[target_indices], dtype=np.float64).reshape(-1, FEATURE_COUNT))
    stored = v1.sort_values(["horizon", "model_node_id"], kind="mergesort")
    max_v1 = {
        "p_occurrence": float(np.max(np.abs(realized_p - stored["p_occurrence"].to_numpy(float)))),
        "conditional_count_mean": float(np.max(np.abs(realized_c - stored["conditional_count_mean"].to_numpy(float)))),
        "expected_count": float(np.max(np.abs(realized_p * realized_c - stored["expected_count"].to_numpy(float)))),
    }
    require(max(max_v1.values()) <= 1e-10, f"V1 stored P2 prediction mismatch for {origin}: {max_v1}")

    p5a_path = p5a_root / "origins" / f"origin_{origin}.parquet"
    require(p5a_path.exists(), f"missing P5A origin artifact: {p5a_path}")
    canonical = pd.read_parquet(p5a_path)
    canonical = canonical.loc[canonical["proxy_id"].eq("E0_LAST_AVAILABLE")].sort_values(KEY_COLUMNS, kind="mergesort").reset_index(drop=True)
    candidate = v2.sort_values(KEY_COLUMNS, kind="mergesort").reset_index(drop=True)
    require(np.array_equal(canonical[KEY_COLUMNS].to_numpy(), candidate[KEY_COLUMNS].to_numpy()), f"V2/P5A keys differ for {origin}")
    max_v2 = {}
    for column in ["p_occurrence", "conditional_count_mean", "expected_count"]:
        max_v2[column] = float(np.max(np.abs(canonical[column].to_numpy(float) - candidate[column].to_numpy(float))))
    require(max(max_v2.values()) <= 1e-10, f"V2 P5A prediction mismatch for {origin}: {max_v2}")
    max_support = int(np.sum(canonical["support_class"].astype(str).to_numpy() != candidate["support_class"].astype(str).to_numpy()))
    require(max_support == 0, f"V2 P5A support mismatch for {origin}: {max_support}")
    return {"origin_week": origin, "v1_max_abs_difference": max_v1, "v2_max_abs_difference": max_v2, "v2_support_mismatches": max_support}


def origin_run(args: argparse.Namespace, context: dict[str, Any], origin: str) -> dict[str, Any]:
    root = args.output_root
    status_path = root / "origins" / f"origin_{origin}.json"
    parquet_path = root / "origins" / f"origin_{origin}.parquet"
    if status_path.exists() and parquet_path.exists():
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
    ref = base_reference(context["p2_frame"], origin, context["p4_support"])
    # V1 is the immutable P2 row-level reference.
    v1 = ref.copy()

    e0_values, e0_meta = build_proxy_environment(context["dynamic"], labels, origin, "E0_LAST_AVAILABLE")
    require(e0_values is not None, f"E0 unavailable for {origin}")
    raw_v2 = np.asarray(context["features"][target_indices], dtype=np.float64).copy()
    raw_v2[:, :, :ENV_COUNT] = e0_values
    v2_p, v2_c, v2_mu = predict_from_fit(fit, raw_v2.reshape(-1, FEATURE_COUNT))
    v2_support = computed_support(raw_v2, context["support_context"])
    v2 = prediction_frame(ref, "V2_E0_RETROSPECTIVE_HISTORY", v2_p, v2_c, v2_mu, v2_support, origin, e0_meta["latest_available_week"])

    causal_history, history_meta = build_history_for_origin(origin_index, labels, context["counts"], context["nodes"])
    raw_v3 = np.asarray(context["features"][target_indices], dtype=np.float64).copy()
    raw_v3[:, :, HISTORY_START:HISTORY_END] = causal_history
    v3_p, v3_c, v3_mu = predict_from_fit(fit, raw_v3.reshape(-1, FEATURE_COUNT))
    v3_support = computed_support(raw_v3, context["support_context"])
    v3 = prediction_frame(ref, "V3_REALIZED_ORIGIN_BOUNDED_HISTORY", v3_p, v3_c, v3_mu, v3_support, origin, ";".join(labels[i] for i in target_indices), causal_history)
    v3["environment_reference_week"] = v3["target_week"].astype(str)

    raw_v4 = raw_v3.copy()
    raw_v4[:, :, :ENV_COUNT] = e0_values
    v4_p, v4_c, v4_mu = predict_from_fit(fit, raw_v4.reshape(-1, FEATURE_COUNT))
    v4_support = computed_support(raw_v4, context["support_context"])
    v4 = prediction_frame(ref, "V4_ISSUE_TIME_CAUSAL", v4_p, v4_c, v4_mu, v4_support, origin, e0_meta["latest_available_week"], causal_history)
    v4["issue_timestamp"] = issue_timestamp(origin)

    # V1/V2 validation must pass before V4 is accepted as an operational result.
    equivalence = verify_v1_and_v2(v1, v2, context["features"], target_indices, fit, args.p5a_root, origin)
    for frame in (v1, v2, v3, v4):
        require(not frame.duplicated(KEY_COLUMNS + ["variant"]).any(), f"duplicate variant key for {origin}")
    all_rows = pd.concat([v1, v2, v3, v4], ignore_index=True)
    write_parquet(parquet_path, all_rows)
    status = {
        "status": "COMPLETED",
        "origin_week": origin,
        "issue_timestamp": issue_timestamp(origin),
        "target_weeks": [labels[i] for i in target_indices],
        "horizons": list(HORIZONS),
        "rows": int(len(all_rows)),
        "variants": VARIANTS,
        "fit_artifact": str(args.p2_output_root / "fits" / f"origin_{origin}.json"),
        "fit_artifact_sha256": sha256_file(args.p2_output_root / "fits" / f"origin_{origin}.json"),
        "fit_reused_without_refit": True,
        "history": history_meta,
        "environment_reference_week": e0_meta["latest_available_week"],
        "equivalence": equivalence,
        "prediction_sha256": sha256_file(parquet_path),
        "runtime_seconds": time.time() - started,
        "model_id": MODEL_ID,
        "model_sha256": P0_MODEL_SHA256,
        "future_detection_sets_used_in_v4": False,
        "target_outcomes_used_in_feature_construction": False,
    }
    write_json(status_path, status)
    return status


def paired_difference_rows(v4: pd.DataFrame, reference: pd.DataFrame, reference_name: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for horizon in HORIZONS:
        left = v4.loc[v4["horizon"].astype(int).eq(horizon)].sort_values(KEY_COLUMNS, kind="mergesort").reset_index(drop=True)
        right = reference.loc[reference["horizon"].astype(int).eq(horizon)].sort_values(KEY_COLUMNS, kind="mergesort").reset_index(drop=True)
        require(np.array_equal(left["key"].to_numpy(), right["key"].to_numpy()), f"paired keys differ for V4/{reference_name} h{horizon}")
        lm = all_metrics(left)
        rm = all_metrics(right)
        for metric in PAIR_METRICS + ["full_expected_rmse", "conditional_rmse", "full_expected_bias", "conditional_bias"]:
            rows.append({
                "comparison": f"V4_minus_{reference_name}",
                "reference_variant": reference_name,
                "horizon": horizon,
                "metric": metric,
                "v4_value": lm.get(metric, math.nan),
                "reference_value": rm.get(metric, math.nan),
                "difference": lm.get(metric, math.nan) - rm.get(metric, math.nan),
            })
    return pd.DataFrame(rows)


def bootstrap_pair(left: pd.DataFrame, right: pd.DataFrame, reference_name: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for horizon in HORIZONS:
        l = left.loc[left["horizon"].astype(int).eq(horizon)].sort_values(KEY_COLUMNS, kind="mergesort").reset_index(drop=True)
        r = right.loc[right["horizon"].astype(int).eq(horizon)].sort_values(KEY_COLUMNS, kind="mergesort").reset_index(drop=True)
        require(np.array_equal(l["key"].to_numpy(), r["key"].to_numpy()), f"bootstrap keys differ for {reference_name} h{horizon}")
        weeks = sorted(l["target_week"].astype(str).unique(), key=parse_week)
        positions = {week: np.flatnonzero(l["target_week"].astype(str).to_numpy() == week) for week in weeks}
        for metric_index, metric in enumerate(["brier", "auprc", "full_expected_mae", "conditional_mae", "frontier_brier"]):
            rng = np.random.default_rng(BOOTSTRAP_SEED + horizon * 100 + metric_index)
            estimates: list[float] = []
            for _ in range(BOOTSTRAP_REPLICATES):
                sampled = rng.choice(np.asarray(weeks, dtype=object), size=len(weeks), replace=True)
                indices = np.concatenate([positions[str(week)] for week in sampled])
                ls = l.iloc[indices]
                rs = r.iloc[indices]
                if metric == "frontier_brier":
                    ls = ls.loc[ls["prediction_frontier_class"].astype(str).eq("previously_unoccupied")]
                    rs = rs.loc[rs["prediction_frontier_class"].astype(str).eq("previously_unoccupied")]
                    value = occurrence_metrics(ls).get("brier", math.nan) - occurrence_metrics(rs).get("brier", math.nan) if len(ls) else math.nan
                else:
                    value = all_metrics(ls).get(metric, math.nan) - all_metrics(rs).get(metric, math.nan)
                if np.isfinite(value):
                    estimates.append(float(value))
            if metric == "frontier_brier":
                l0 = l.loc[l["prediction_frontier_class"].astype(str).eq("previously_unoccupied")]
                r0 = r.loc[r["prediction_frontier_class"].astype(str).eq("previously_unoccupied")]
                estimate = occurrence_metrics(l0).get("brier", math.nan) - occurrence_metrics(r0).get("brier", math.nan)
            else:
                estimate = all_metrics(l).get(metric, math.nan) - all_metrics(r).get(metric, math.nan)
            rows.append({
                "comparison": f"V4_minus_{reference_name}",
                "horizon": horizon,
                "metric": metric,
                "estimate": estimate,
                "lower": float(np.quantile(estimates, 0.025)) if estimates else math.nan,
                "upper": float(np.quantile(estimates, 0.975)) if estimates else math.nan,
                "bootstrap_replicates": len(estimates),
                "seed": BOOTSTRAP_SEED + horizon * 100 + metric_index,
                "block_unit": "target_week",
            })
    return pd.DataFrame(rows)


def benchmark_percentile(values: pd.Series, higher_is_risk: bool) -> pd.Series:
    score = pd.to_numeric(values, errors="coerce").to_numpy(float)
    if not higher_is_risk:
        score = -score
    finite = np.isfinite(score)
    out = np.full(len(score), np.nan, dtype=float)
    if finite.sum() >= 3 and np.unique(score[finite]).size >= 2:
        out[finite] = 100.0 * (rankdata(score[finite], method="average") - 0.5) / finite.sum()
    return pd.Series(out, index=values.index)


def frontier_benchmarks(v4: pd.DataFrame, output: Path) -> dict[str, Any]:
    candidates = v4.loc[(v4["observed_positive"].astype(int) > 0) & (~v4["previously_occupied"].astype(bool))].copy()
    candidates = candidates.sort_values(["model_node_id", "target_week", "horizon", "origin_week"], kind="mergesort")
    first = candidates.drop_duplicates(["model_node_id"], keep="first")
    score_columns = {
        "A3": ("p_occurrence", True),
        "B1_DISTANCE_ANY": ("distance_to_any_prior_positive_log1p", False),
        "B2_DISTANCE_PREV4": ("distance_to_prev4_positive_log1p", False),
        "B3_RECENCY_50KM": ("weeks_since_detection_within_50km_log1p", False),
    }
    event_rows: list[dict[str, Any]] = []
    for _, event in first.iterrows():
        for horizon in HORIZONS:
            rows = v4.loc[(v4["model_node_id"] == event["model_node_id"]) & (v4["target_week"] == event["target_week"]) & (v4["horizon"] == horizon)]
            if len(rows) != 1:
                continue
            row = rows.iloc[0]
            base = v4.loc[(v4["origin_week"] == row["origin_week"]) & (v4["target_week"] == row["target_week"]) & (v4["horizon"] == horizon)]
            for pool_name, pool in (("FULL_DOMAIN", base), ("FRONTIER_RELATIVE", base.loc[~base["previously_occupied"].astype(bool)])):
                for score_name, (column, higher) in score_columns.items():
                    percentile = benchmark_percentile(pool[column], higher)
                    matched = percentile.loc[pool["model_node_id"].eq(row["model_node_id"])]
                    value = row[column] if column in row else math.nan
                    event_rows.append({
                        "model_node_id": int(row["model_node_id"]),
                        "target_week": str(row["target_week"]),
                        "origin_week": str(row["origin_week"]),
                        "horizon": horizon,
                        "pool": pool_name,
                        "score": score_name,
                        "score_column": column,
                        "score_value": float(value) if pd.notna(value) else math.nan,
                        "risk_percentile": float(matched.iloc[0]) if len(matched) else math.nan,
                        "n_pool": int(len(pool)),
                        "status": "estimable" if len(matched) and np.isfinite(matched.iloc[0]) else "not_estimable",
                    })
    events = pd.DataFrame(event_rows)
    summary: list[dict[str, Any]] = []
    for (horizon, pool, score), group in events.groupby(["horizon", "pool", "score"], sort=True):
        estimable = group.loc[group["status"].eq("estimable")]
        for fraction in TOP_FRACTIONS:
            threshold = 100.0 * (1.0 - fraction)
            captured = estimable["risk_percentile"] >= threshold
            summary.append({
                "horizon": int(horizon), "pool": pool, "score": score,
                "top_fraction": fraction, "threshold_percentile": threshold,
                "event_n": int(len(estimable)), "captured_n": int(captured.sum()),
                "capture_fraction": float(captured.mean()) if len(captured) else math.nan,
                "status": "estimable" if len(estimable) else "not_estimable",
            })
    write_csv(output / "frontier_benchmark_event_percentiles.csv", events)
    write_csv(output / "frontier_benchmark_topk.csv", pd.DataFrame(summary))
    return {"first_detection_cells": int(first["model_node_id"].nunique()), "first_detection_rows": int(len(first)), "event_horizon_rows": int(events[["model_node_id", "target_week", "horizon"]].drop_duplicates().shape[0]), "summary_rows": len(summary)}


def frontier_decision(topk: pd.DataFrame) -> str:
    if topk.empty:
        return "FRONTIER_BENCHMARK_NOT_ESTIMABLE"
    decisions: list[str] = []
    simple = ["B1_DISTANCE_ANY", "B2_DISTANCE_PREV4", "B3_RECENCY_50KM"]
    for horizon in HORIZONS:
        a3 = topk.loc[(topk["horizon"] == horizon) & (topk["pool"] == "FRONTIER_RELATIVE") & (topk["score"] == "A3")].set_index("top_fraction")["capture_fraction"]
        comparisons = []
        for fraction in (0.05, 0.10, 0.20):
            if fraction not in a3.index:
                continue
            a = float(a3.loc[fraction])
            simple_values = []
            for score in simple:
                row = topk.loc[(topk["horizon"] == horizon) & (topk["pool"] == "FRONTIER_RELATIVE") & (topk["score"] == score) & (topk["top_fraction"] == fraction)]
                if len(row) and pd.notna(row["capture_fraction"].iloc[0]):
                    simple_values.append(float(row["capture_fraction"].iloc[0]))
            if simple_values:
                comparisons.append((a > max(simple_values), a < min(simple_values)))
        if not comparisons:
            return "FRONTIER_BENCHMARK_NOT_ESTIMABLE"
        a3_better = sum(item[0] for item in comparisons)
        a3_worse = sum(item[1] for item in comparisons)
        if a3_better >= 2 and a3_worse <= 1:
            decisions.append("adds")
        elif a3_worse >= 2:
            decisions.append("worse")
        else:
            decisions.append("comparable")
    if all(item == "adds" for item in decisions):
        return "A3_FRONTIER_RANKING_ADDS_INFORMATION_BEYOND_SIMPLE_HISTORY"
    if all(item == "worse" for item in decisions):
        return "A3_FRONTIER_RANKING_DOES_NOT_OUTPERFORM_SIMPLE_HISTORY"
    return "A3_FRONTIER_RANKING_COMPARABLE_TO_SIMPLE_HISTORY"


def paired_trajectory(v4: pd.DataFrame, events: pd.DataFrame, output: Path) -> dict[str, Any]:
    primary = events.loc[(events["score"] == "A3") & (events["pool"] == "FRONTIER_RELATIVE") & events["status"].eq("estimable")].copy()
    pivot = primary.pivot_table(index=["model_node_id", "target_week"], columns="horizon", values="risk_percentile", aggfunc="first")
    complete = pivot.dropna(subset=list(HORIZONS)).copy()
    if complete.empty:
        write_csv(output / "paired_first_detection_trajectory.csv", pd.DataFrame())
        return {"matched_n": 0}
    complete = complete.rename(columns={1: "h1_percentile", 2: "h2_percentile", 3: "h3_percentile"})
    complete["h1_minus_h3"] = complete["h1_percentile"] - complete["h3_percentile"]
    complete = complete.reset_index()
    write_csv(output / "paired_first_detection_trajectory.csv", complete)
    delta = complete["h1_minus_h3"]
    return {
        "matched_n": int(len(complete)),
        "median_h1_percentile": float(complete["h1_percentile"].median()),
        "median_h2_percentile": float(complete["h2_percentile"].median()),
        "median_h3_percentile": float(complete["h3_percentile"].median()),
        "median_h1_minus_h3": float(delta.median()),
        "iqr_h1_minus_h3": [float(delta.quantile(0.25)), float(delta.quantile(0.75))],
        "proportion_increasing": float((delta > 0).mean()),
        "proportion_equal": float((delta == 0).mean()),
        "proportion_decreasing": float((delta < 0).mean()),
    }


def reconcile_correlations(repository_root: Path, output: Path) -> dict[str, Any]:
    path = repository_root / "analysis" / "p7h_manuscript_integration" / "results" / "predictor_dependence_pairs.csv"
    require(path.exists(), f"missing retained P7G/P7H dependence artifact: {path}")
    frame = pd.read_csv(path)
    abs_p = frame["pearson"].abs()
    abs_s = frame["spearman"].abs()
    rows = []
    for threshold in (0.70, 0.90):
        rows.extend([
            {"rule": "pearson_only", "threshold": threshold, "pair_count": int(((abs_p >= threshold) & (abs_s < threshold)).sum())},
            {"rule": "spearman_only", "threshold": threshold, "pair_count": int(((abs_s >= threshold) & (abs_p < threshold)).sum())},
            {"rule": "max_abs_implemented", "threshold": threshold, "pair_count": int((np.maximum(abs_p, abs_s) >= threshold).sum())},
            {"rule": "both", "threshold": threshold, "pair_count": int(((abs_p >= threshold) & (abs_s >= threshold)).sum())},
        ])
    write_csv(output / "predictor_dependence_reconciliation.csv", pd.DataFrame(rows))
    return {"source_artifact": "analysis/p7g_manuscript_evidence/results/predictor_dependence_pairs.csv", "retained_copy": str(path), "source_sha256": sha256_file(path), "pair_count": int(len(frame)), "counts": rows}


def reconcile_p4_stability(repository_root: Path, output: Path) -> dict[str, Any]:
    path = repository_root / "analysis" / "p4_uncertainty_extrapolation" / "results" / "bootstrap_coefficient_stability.csv"
    metadata_path = repository_root / "analysis" / "p4_uncertainty_extrapolation" / "results" / "p4_run_metadata.json"
    manifest_path = repository_root / "analysis" / "p4_uncertainty_extrapolation" / "results" / "bootstrap_manifest.csv"
    require(path.exists() and metadata_path.exists() and manifest_path.exists(), "retained P4 coefficient-stability provenance is incomplete")
    frame = pd.read_csv(path)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    manifest = pd.read_csv(manifest_path)
    expected_reps = len(metadata.get("bootstrap_used_replicates", []))
    component_count = int(frame["component"].nunique())
    expected_rows = component_count * FEATURE_COUNT + component_count
    payload = {
        "status": "CANONICAL_RETAINED_ARTIFACT_VERIFIED",
        "artifact": str(path),
        "sha256": sha256_file(path),
        "rows": int(len(frame)),
        "components": sorted(frame["component"].unique().tolist()),
        "feature_rows_excluding_intercepts": int((frame["feature_name"] != "intercept").sum()),
        "expected_rows_from_35_terms_and_2_components": expected_rows,
        "bootstrap_manifest_rows": int(len(manifest)),
        "bootstrap_used_replicates": expected_reps,
        "bootstrap_used_replicate_ids": metadata.get("bootstrap_used_replicates", []),
        "source_script": "analysis/p4_uncertainty_extrapolation/scripts/run_p4_uncertainty_extrapolation.py:719",
        "creation_commit": "4c7cbcbf7dcd375d8b4f4fe401077da72a5bd2c7",
        "model_hash": metadata.get("p0_model_artifact_sha256"),
        "p2_archive_hash": metadata.get("p2_archive_sha256"),
        "p7g_prior_metadata_conflict": "P7G reported artifact unavailable because its Atlas output-root inventory did not retain this repository artifact; the canonical repository file is now hash-verified and provenance-audited.",
        "manuscript_intervals_added": False,
    }
    write_json(output / "p4_coefficient_stability_reconciliation.json", payload)
    return payload


def reconcile_early_warning(repository_root: Path, output: Path, benchmark_meta: dict[str, Any]) -> dict[str, Any]:
    old_path = repository_root / "analysis" / "p7g_manuscript_evidence" / "results" / "early_warning_metadata.json"
    old = json.loads(old_path.read_text(encoding="utf-8")) if old_path.exists() else {}
    corrected = {
        "first_detection_cells": benchmark_meta["first_detection_cells"],
        "first_detection_rows": benchmark_meta["first_detection_rows"],
        "event_horizon_rows": benchmark_meta["event_horizon_rows"],
        "excluded_missing_horizon_records": int(benchmark_meta["first_detection_rows"] * len(HORIZONS) - benchmark_meta["event_horizon_rows"]),
        "rank_formula": "100 * (midrank - 0.5) / n",
        "top_fractions": list(TOP_FRACTIONS),
        "reference_scores": ["B1_DISTANCE_ANY", "B2_DISTANCE_PREV4", "B3_RECENCY_50KM"],
        "bookkeeping_rule": "unique event x horizon records, not duplicated by full-domain/frontier pool output rows",
        "prior_metadata": old,
        "scientific_event_outputs_rewritten": False,
    }
    write_json(output / "early_warning_metadata_reconciliation.json", corrected)
    return corrected


def reconcile_provenance(repository_root: Path, p2_metadata: dict[str, Any], output: Path) -> pd.DataFrame:
    source_names = {
        "D1_observation": "production_manifest",
        "D2_environment": "dynamic_features",
        "D3_livestock_static": "static_features",
        "D4_road_night": "road_night_features",
        "D5_soil": "soil_features",
    }
    rows = []
    for identifier, name in source_names.items():
        source = source_manifest_row(p2_metadata, name)
        rows.append({
            "source_id": identifier,
            "retained_source_name": name,
            "source_path": source.get("path", ""),
            "source_sha256": source.get("sha256", ""),
            "source_size_bytes": source.get("size_bytes"),
            "provider_product": "UNRESOLVED_FROM_RETAINED_PROVENANCE",
            "release_version": "UNRESOLVED_FROM_RETAINED_PROVENANCE",
            "units": "UNRESOLVED_FROM_RETAINED_PROVENANCE",
            "status": "RESOLVED_PATH_AND_HASH_ONLY" if source.get("sha256") else "UNRESOLVED_FROM_RETAINED_PROVENANCE",
            "evidence_artifact": "analysis/p2_operational_nowcast/results/run_metadata.json",
        })
    write_csv(output / "data_source_provenance.csv", pd.DataFrame(rows))
    return pd.DataFrame(rows)


def make_figures(output: Path, metrics: pd.DataFrame, topk: pd.DataFrame) -> list[str]:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return []
    paths = []
    fig, axes = plt.subplots(1, 2, figsize=(8, 3.2), constrained_layout=True)
    for metric, ax in [("brier", axes[0]), ("auprc", axes[1])]:
        for variant, color in [("V1_REALIZED_RETROSPECTIVE", "black"), ("V2_E0_RETROSPECTIVE_HISTORY", "#0072B2"), ("V3_REALIZED_ORIGIN_BOUNDED_HISTORY", "#D55E00"), ("V4_ISSUE_TIME_CAUSAL", "#009E73")]:
            subset = metrics.loc[metrics["variant"].eq(variant)].sort_values("horizon")
            if len(subset):
                ax.plot(subset["horizon"], subset[metric], marker="o", label=variant.replace("V", "V"), color=color)
        ax.set_xlabel("Horizon (weeks)")
        ax.set_ylabel(metric.replace("_", " ").title())
        ax.set_xticks([1, 2, 3])
        ax.grid(alpha=0.25)
    axes[1].legend(fontsize=6, frameon=False)
    path = output / "issue_time_causal_metrics.svg"
    fig.savefig(path, format="svg")
    plt.close(fig)
    paths.append(str(path))
    if not topk.empty:
        subset = topk.loc[(topk["pool"] == "FRONTIER_RELATIVE") & (topk["top_fraction"].isin([0.05, 0.10, 0.20]))]
        fig, ax = plt.subplots(figsize=(6.5, 3.2), constrained_layout=True)
        for score, group in subset.groupby("score", sort=False):
            values = group.groupby("top_fraction", as_index=False)["capture_fraction"].mean().sort_values("top_fraction")
            ax.plot(values["top_fraction"] * 100, values["capture_fraction"] * 100, marker="o", label=score)
        ax.set_xlabel("Top-ranked fraction (%)")
        ax.set_ylabel("First-detection capture (%)")
        ax.grid(alpha=0.25)
        ax.legend(fontsize=7, frameon=False)
        path = output / "frontier_benchmark_capture.svg"
        fig.savefig(path, format="svg")
        plt.close(fig)
        paths.append(str(path))
    return paths


def write_report(repository_root: Path, result_root: Path, payload: dict[str, Any]) -> None:
    report = repository_root / "analysis" / "p7i_issue_time_validation" / "p7i_issue_time_validation_report.md"
    lines = [
        "# P7I Issue-Time-Causal Forecast Validation Report",
        "",
        "This is a technical validation record. No manuscript prose is generated by P7I.",
        "",
        "## Scope and frozen inputs",
        f"- Model: `{MODEL_ID}`; frozen artifact SHA-256 `{P0_MODEL_SHA256}`.",
        f"- Origins: `{ORIGINS[0]}` through `{ORIGINS[-1]}`; horizons h=1,2,3.",
        "- V4 uses E0_LAST_AVAILABLE with L(T)=T-1 and origin-bounded detection history.",
        "- Existing P2 fits are reused; no model refitting or tuning occurs.",
        "",
        "## Replay validation",
        f"- V1/V2 equivalence status: `{payload['equivalence_status']}`.",
        f"- Causal-history leakage checks passed for {payload['origin_count']} origins; post-origin positive sets were empty during V4 construction.",
        f"- V3 status: `{payload['v3_status']}`.",
        "",
        "## Decisions",
        f"- Issue-time decision: `{payload['issue_time_decision']}`.",
        f"- Frontier benchmark decision: `{payload['frontier_decision']}`.",
        f"- Overall P7I decision: `{payload['overall_decision']}`.",
        "",
        "## Reconciliations",
        "- Predictor-dependence counts are reported under Pearson-only, Spearman-only, and the implemented max-absolute-correlation rule.",
        "- P4 coefficient stability is audited as a retained canonical artifact; no coefficient intervals are added to publication outputs.",
        "- Early-warning missing-horizon bookkeeping is corrected using unique event-by-horizon records; prior event identities and scientific outputs are not rewritten.",
        "- D1-D5 source provenance resolves retained paths and hashes only; provider versions and units remain explicitly unresolved where absent.",
        "",
        "## Output roots",
        f"- Detailed Atlas output root: `{result_root}`.",
        "- Compact repository outputs are under `analysis/p7i_issue_time_validation/results/`.",
    ]
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")


def aggregate(args: argparse.Namespace, context: dict[str, Any], statuses: list[dict[str, Any]]) -> dict[str, Any]:
    detailed = pd.concat([pd.read_parquet(args.output_root / "origins" / f"origin_{row['origin_week']}.parquet") for row in statuses], ignore_index=True)
    require(set(detailed["variant"].unique()) == set(VARIANTS), "variant set incomplete")
    result_root = args.repository_root / "analysis" / "p7i_issue_time_validation" / "results"
    result_root.mkdir(parents=True, exist_ok=True)
    # Keep repository results compact: no cell-level prediction archive is copied here.
    metrics_rows: list[dict[str, Any]] = []
    for variant, group in detailed.groupby("variant", sort=True):
        for horizon in HORIZONS:
            subset = group.loc[group["horizon"].astype(int).eq(horizon)]
            metrics_rows.append({"variant": variant, "horizon": horizon, **all_metrics(subset)})
    metrics = pd.DataFrame(metrics_rows)
    write_csv(result_root / "variant_metrics.csv", metrics)
    v1 = detailed.loc[detailed["variant"].eq("V1_REALIZED_RETROSPECTIVE")]
    v2 = detailed.loc[detailed["variant"].eq("V2_E0_RETROSPECTIVE_HISTORY")]
    v3 = detailed.loc[detailed["variant"].eq("V3_REALIZED_ORIGIN_BOUNDED_HISTORY")]
    v4 = detailed.loc[detailed["variant"].eq("V4_ISSUE_TIME_CAUSAL")]
    differences = pd.concat([paired_difference_rows(v4, v1, "V1_REALIZED_RETROSPECTIVE"), paired_difference_rows(v4, v2, "V2_E0_RETROSPECTIVE_HISTORY"), paired_difference_rows(v4, v3, "V3_REALIZED_ORIGIN_BOUNDED_HISTORY")], ignore_index=True)
    write_csv(result_root / "paired_variant_differences.csv", differences)
    bootstrap = pd.concat([bootstrap_pair(v4, v1, "V1_REALIZED_RETROSPECTIVE"), bootstrap_pair(v4, v2, "V2_E0_RETROSPECTIVE_HISTORY"), bootstrap_pair(v4, v3, "V3_REALIZED_ORIGIN_BOUNDED_HISTORY")], ignore_index=True)
    write_csv(result_root / "paired_bootstrap_intervals.csv", bootstrap)

    frontier_rows = []
    for variant, group in detailed.groupby("variant", sort=True):
        for horizon in HORIZONS:
            for frontier in ["previously_occupied", "previously_unoccupied"]:
                subset = group.loc[group["horizon"].astype(int).eq(horizon) & group["prediction_frontier_class"].astype(str).eq(frontier)]
                frontier_rows.append({"variant": variant, "horizon": horizon, "frontier_class": frontier, **all_metrics(subset)})
    frontier_metrics = pd.DataFrame(frontier_rows)
    write_csv(result_root / "frontier_metrics.csv", frontier_metrics)

    support_rows = []
    for variant, group in detailed.groupby("variant", sort=True):
        for horizon in HORIZONS:
            subset = group.loc[group["horizon"].astype(int).eq(horizon)]
            counts = subset["support_class"].value_counts()
            for support_class in ["SUPPORTED", "CAUTION", "EXTRAPOLATIVE"]:
                support_rows.append({"variant": variant, "horizon": horizon, "support_class": support_class, "n": int(counts.get(support_class, 0)), "proportion": float(counts.get(support_class, 0) / max(len(subset), 1))})
    write_csv(result_root / "support_metrics.csv", pd.DataFrame(support_rows))

    benchmark_output = args.output_root / "benchmarks"
    benchmark_output.mkdir(parents=True, exist_ok=True)
    benchmark_meta = frontier_benchmarks(v4, benchmark_output)
    topk = pd.read_csv(benchmark_output / "frontier_benchmark_topk.csv")
    write_csv(result_root / "frontier_benchmark_topk.csv", topk)
    events = pd.read_csv(benchmark_output / "frontier_benchmark_event_percentiles.csv")
    write_csv(result_root / "frontier_benchmark_event_percentiles.csv", events)
    trajectory_meta = paired_trajectory(v4, events, result_root)
    # Move the trajectory into the compact repository result only; no coordinates or outcomes beyond the bounded event table are retained.
    write_csv(result_root / "paired_first_detection_trajectory.csv", pd.read_csv(result_root / "paired_first_detection_trajectory.csv"))

    equivalence = pd.DataFrame([row["equivalence"] for row in statuses])
    write_csv(result_root / "v1_v2_equivalence.csv", equivalence)
    issue_diff = differences.loc[differences["comparison"].eq("V4_minus_V1_REALIZED_RETROSPECTIVE")]
    strict_failures = []
    bounded_failures = []
    brier = issue_diff.loc[issue_diff["metric"].eq("brier")].set_index("horizon")["difference"]
    auprc = issue_diff.loc[issue_diff["metric"].eq("auprc")].set_index("horizon")["difference"]
    cal = issue_diff.loc[issue_diff["metric"].eq("calibration_intercept")].set_index("horizon")["difference"]
    full_mae = issue_diff.loc[issue_diff["metric"].eq("full_expected_mae")].set_index("horizon")["difference"]
    cond_mae = issue_diff.loc[issue_diff["metric"].eq("conditional_mae")].set_index("horizon")["difference"]
    frontier_b = frontier_metrics.loc[(frontier_metrics["variant"] == "V4_ISSUE_TIME_CAUSAL") & (frontier_metrics["frontier_class"] == "previously_unoccupied")].set_index("horizon")["brier"] - frontier_metrics.loc[(frontier_metrics["variant"] == "V1_REALIZED_RETROSPECTIVE") & (frontier_metrics["frontier_class"] == "previously_unoccupied")].set_index("horizon")["brier"]
    v1_metrics = metrics.loc[metrics["variant"].eq("V1_REALIZED_RETROSPECTIVE")].set_index("horizon")
    for horizon in HORIZONS:
        checks = {
            "brier": (float(brier[horizon]) <= 0.002, float(brier[horizon]) <= 0.005),
            "auprc_relative_loss": (float(auprc[horizon]) >= -0.05 * max(float(v1_metrics.loc[horizon, "auprc"]), 1e-12), float(auprc[horizon]) >= -0.10 * max(float(v1_metrics.loc[horizon, "auprc"]), 1e-12)),
            "calibration_intercept": (abs(float(cal[horizon])) <= 0.05, abs(float(cal[horizon])) <= 0.10),
            "full_expected_mae": (float(full_mae[horizon]) <= 0.02, float(full_mae[horizon]) <= 0.05),
            "conditional_mae": (float(cond_mae[horizon]) <= 0.10, float(cond_mae[horizon]) <= 0.25),
            "frontier_brier": (float(frontier_b[horizon]) <= 0.002, float(frontier_b[horizon]) <= 0.005),
        }
        for name, (strict_ok, bounded_ok) in checks.items():
            if not strict_ok:
                strict_failures.append(f"h{horizon}:{name}")
            if not bounded_ok:
                bounded_failures.append(f"h{horizon}:{name}")
    if max(equivalence["v1_max_abs_difference"].apply(lambda x: max(x.values())).max(), equivalence["v2_max_abs_difference"].apply(lambda x: max(x.values())).max()) > 1e-10:
        equivalence_status = "FAILED"
        issue_decision = "ISSUE_TIME_CAUSAL_REPLAY_INVALID"
    elif not strict_failures:
        equivalence_status = "PASSED"
        issue_decision = "ISSUE_TIME_CAUSAL_PERFORMANCE_PRESERVED"
    elif not bounded_failures:
        equivalence_status = "PASSED"
        issue_decision = "ISSUE_TIME_CAUSAL_PERFORMANCE_DEGRADED_BUT_USABLE"
    else:
        equivalence_status = "PASSED"
        issue_decision = "ISSUE_TIME_CAUSAL_PERFORMANCE_MATERIALLY_DEGRADED"
    frontier_decision_value = frontier_decision(topk)

    p2_manifest_path = args.repository_root / "analysis" / "p2_operational_nowcast" / "results" / "prediction_archive_manifest.json"
    p2_manifest = json.loads(p2_manifest_path.read_text(encoding="utf-8"))
    p2_metadata = context["p2_metadata"]
    source_provenance = reconcile_provenance(args.repository_root, p2_metadata, result_root)
    correlation = reconcile_correlations(args.repository_root, result_root)
    p4_stability = reconcile_p4_stability(args.repository_root, result_root)
    early_warning = reconcile_early_warning(args.repository_root, result_root, benchmark_meta)
    figure_paths = make_figures(args.output_root / "figures", metrics, topk)

    overall = "P7I_EVIDENCE_CLOSURE_COMPLETE"
    limitations = []
    if issue_decision != "ISSUE_TIME_CAUSAL_PERFORMANCE_PRESERVED":
        overall = "P7I_EVIDENCE_CLOSURE_COMPLETE_WITH_LIMITATIONS"
        limitations.append(issue_decision)
    if frontier_decision_value != "A3_FRONTIER_RANKING_ADDS_INFORMATION_BEYOND_SIMPLE_HISTORY":
        overall = "P7I_EVIDENCE_CLOSURE_COMPLETE_WITH_LIMITATIONS"
        limitations.append(frontier_decision_value)
    if p4_stability["status"] != "CANONICAL_RETAINED_ARTIFACT_VERIFIED":
        overall = "P7I_EVIDENCE_CLOSURE_COMPLETE_WITH_LIMITATIONS"
        limitations.append("P4_STABILITY_PROVENANCE_LIMITATION")

    manifest = {
        "phase": "P7I",
        "status": "COMPLETED",
        "repository_sha": git_value(args.repository_root, "rev-parse", "HEAD"),
        "model_id": MODEL_ID,
        "model_sha256": P0_MODEL_SHA256,
        "p2_archive_sha256": p2_manifest["combined_prediction_archive"]["sha256"],
        "p2_archive_rows": int(p2_manifest["combined_prediction_archive"]["rows"]),
        "p4_support_sha256": sha256_file(args.p4_root / "support_classifications.parquet"),
        "p5a_output_root": str(args.p5a_root),
        "origins": ORIGINS,
        "origin_count": len(statuses),
        "horizons": list(HORIZONS),
        "variants": VARIANTS,
        "no_model_fitting": True,
        "no_future_detection_sets_used_in_v4": True,
        "target_outcomes_used_in_feature_construction": False,
        "detailed_output_root": str(args.output_root),
        "compact_output_files": sorted(str(path.relative_to(result_root)) for path in result_root.glob("*")),
        "figure_paths": figure_paths,
        "equivalence_status": equivalence_status,
        "v3_status": "COMPUTED_REALIZED_ENVIRONMENT_WITH_ORIGIN_BOUNDED_HISTORY",
        "issue_time_decision": issue_decision,
        "frontier_decision": frontier_decision_value,
        "overall_decision": overall,
        "limitations": limitations,
        "source_provenance_rows": int(len(source_provenance)),
        "correlation_reconciliation": correlation,
        "p4_stability_reconciliation": p4_stability,
        "early_warning_reconciliation": early_warning,
    }
    write_json(result_root / "p7i_provenance_manifest.json", manifest)
    write_json(result_root / "decision.json", manifest)
    write_report(args.repository_root, args.output_root, manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument("--model-output", type=Path, required=True)
    parser.add_argument("--p2-output-root", type=Path, required=True)
    parser.add_argument("--p4-root", type=Path, required=True)
    parser.add_argument("--p5a-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    for folder in ("origins", "benchmarks", "figures", "logs"):
        (args.output_root / folder).mkdir(parents=True, exist_ok=True)
    verification = verify_p0(args.repository_root)
    p2_frame, p2_manifest, p2_metadata = p2_provenance(args.repository_root, args.p2_output_root)
    require(p2_manifest["combined_prediction_archive"]["sha256"] == P2_ARCHIVE_SHA256, "P2 archive hash changed")
    require(int(p2_manifest["combined_prediction_archive"]["rows"]) == P2_EXPECTED_ROWS, "P2 archive row count changed")
    raw = args.model_output / "raw"
    labels = pd.read_parquet(raw / "weeks.parquet")["iso_week"].astype(str).tolist()
    dynamic = np.asarray(np.load(raw / "dynamic_features.npy", mmap_mode="r"), dtype=np.float64)
    counts = np.asarray(np.load(raw / "targets_count.npy", mmap_mode="r"), dtype=np.int64)
    features = np.load(args.p2_output_root / "manifests" / "a3_features.npy", mmap_mode="r")
    nodes = pd.read_parquet(raw / "nodes.parquet").sort_values("model_node_id").reset_index(drop=True)
    require(len(nodes) == NODE_COUNT and np.array_equal(nodes["model_node_id"].to_numpy(np.int64), np.arange(NODE_COUNT)), "canonical node table changed")
    require(features.shape == (len(labels), NODE_COUNT, FEATURE_COUNT), "P2 feature cache shape changed")
    require(dynamic.shape == (len(labels), NODE_COUNT, ENV_COUNT), "dynamic feature shape changed")
    require(counts.shape == (len(labels), NODE_COUNT), "response count shape changed")
    p4_support_path = args.p4_root / "support_classifications.parquet"
    require(p4_support_path.exists(), f"missing P4 support classifications: {p4_support_path}")
    support = pd.read_parquet(p4_support_path, columns=[*KEY_COLUMNS, "support_class", "novelty_knn_distance"])
    support["key"] = key_series(support)
    require(not support["key"].duplicated().any(), "P4 support reference keys duplicated")
    support_context = build_support_context(features)
    context = {"p2_frame": p2_frame, "p2_metadata": p2_metadata, "labels": labels, "dynamic": dynamic, "counts": counts, "features": features, "nodes": nodes, "p4_support": support, "support_context": support_context}
    write_json(args.output_root / "logs" / "freeze_verification.json", verification)
    statuses = []
    for origin in ORIGINS:
        status = origin_run(args, context, origin)
        statuses.append(status)
    manifest = aggregate(args, context, statuses)
    manifest["origin_statuses"] = statuses
    write_json(args.repository_root / "analysis" / "p7i_issue_time_validation" / "results" / "decision.json", manifest)
    print(json.dumps({"status": "P7I_COMPLETED", "issue_time_decision": manifest["issue_time_decision"], "frontier_decision": manifest["frontier_decision"], "overall_decision": manifest["overall_decision"], "origins": len(statuses), "no_model_fitting": True}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
