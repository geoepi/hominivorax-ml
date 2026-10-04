#!/usr/bin/env python3
"""Task 3A descriptive audit of reporting process and moving-front dynamics.

This module deliberately does not fit a predictive model.  It constructs
descriptive node-week histories, strictly pre-week front-state candidates,
presence/background design summaries, and validation-design documentation.
All front-state columns are audit-only and use observations from weeks < t.
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.spatial import ConvexHull, cKDTree


SOURCE_PATH = Path("/project/disease_ecology/NWScrewworm/data/processed_data/case_detections/combined_clean_obs_2027-07-31.csv")
CLASSIFICATION_PATH_NAME = "diagnostics/updated_observation_classification.parquet"
V1_OUTPUT = Path("/project/disease_ecology/STGNN-output/terminal_evaluation")
EXPECTED_SOURCE_SHA = "a3d55f3ddf867087b578df803920bf59c6c303fa695e3218a5f3463e596d497e"
EXPECTED_SOURCE_ROWS = 136714
EXPECTED_NODE_COUNT = 10037
EXPECTED_EDGE_COUNT = 77614
AUDIT_START = "2024-W01"
AUDIT_END = "2026-W29"
V1_REFERENCE_SHA = "19886ca2fab5efb2eea25ba6b1fb086f7ecb1ab0"
LATITUDE_KM = 111.32
RNG_SEED = 20261003

ENVIRONMENTAL_FEATURES = [
    "era5_mintemp", "era5_soilmoist", "era5_lai_low", "agera5_relhum_min",
    "era5land_tmean", "era5land_soiltemp_l1_mean", "era5land_soiltemp_l2_mean",
    "era5land_soilwater_l1_mean", "era5land_soilwater_l2_mean",
    "era5land_surface_pressure_mean", "era5land_lai_high_mean", "era5land_lai_low_mean",
]
DENSITY_FEATURES = ["cattle_density", "goat_density", "sheep_density", "horse_density", "pig_density"]
INDICATOR_FEATURES = [f"{name}_imputed" for name in DENSITY_FEATURES]
ALL_COVARIATE_FEATURES = ENVIRONMENTAL_FEATURES + DENSITY_FEATURES + INDICATOR_FEATURES


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (pd.Timestamp, date)):
        return value.isoformat()
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(f"unsupported JSON value: {type(value)!r}")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=json_default) + "\n", encoding="utf-8")


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def audit_week_frame() -> pd.DataFrame:
    start = date.fromisocalendar(2024, 1, 1)
    end = date.fromisocalendar(2026, 29, 1)
    starts = []
    current = start
    while current <= end:
        iso = current.isocalendar()
        starts.append((len(starts), f"{iso.year}-W{iso.week:02d}", current))
        current += timedelta(days=7)
    return pd.DataFrame(starts, columns=["audit_week_index", "week", "week_start"])


def quantiles(values: Any) -> dict[str, float | None]:
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if values.size == 0:
        return {"n": 0, "median": None, "iqr": None, "p90": None, "p95": None, "maximum": None}
    q = np.percentile(values, [25, 50, 75, 90, 95, 100])
    return {
        "n": int(values.size),
        "median": float(q[1]),
        "iqr": float(q[2] - q[0]),
        "p90": float(q[3]),
        "p95": float(q[4]),
        "maximum": float(q[5]),
    }


def summarize_vector(prefix: str, values: Any) -> dict[str, Any]:
    stats = quantiles(values)
    return {f"{prefix}_{key}": value for key, value in stats.items()}


def convex_hull_area_km2(xy: np.ndarray) -> float:
    if len(xy) < 3:
        return 0.0
    try:
        # The canonical Albers axes are explicitly kilometre-scaled.
        return float(ConvexHull(xy).volume)
    except Exception:
        return 0.0


def principal_axis(xy: np.ndarray) -> tuple[float | None, np.ndarray | None]:
    if len(xy) < 2:
        return None, None
    centered = xy - xy.mean(axis=0)
    covariance = np.cov(centered, rowvar=False)
    if not np.isfinite(covariance).all():
        return None, None
    values, vectors = np.linalg.eigh(covariance)
    axis = vectors[:, int(np.argmax(values))]
    if axis[1] < 0:
        axis = -axis
    angle = float(np.degrees(np.arctan2(axis[1], axis[0])) % 180.0)
    return angle, axis


def tree_distances(xy: np.ndarray, node_ids: np.ndarray, query_xy: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    if len(node_ids) == 0:
        return np.full(len(query_xy), np.nan), np.full(len(query_xy), -1, dtype=int)
    tree = cKDTree(xy[node_ids])
    distance, nearest = tree.query(query_xy, k=1)
    # Existing node x/y coordinates use the canonical Albers kilometre axes.
    return np.asarray(distance, dtype=float), node_ids[np.asarray(nearest, dtype=int)]


def causal_front_descriptors(
    positive_sets: list[np.ndarray],
    xy: np.ndarray,
    lat: np.ndarray,
    weeks: list[str],
) -> pd.DataFrame:
    """Return strict-predecessor front descriptors for every node-week.

    The current positive set is not used until after the current row has been
    constructed. This pure function is also exercised by leakage tests.
    """
    node_count = len(lat)
    ever = np.zeros(node_count, dtype=bool)
    last_seen = {radius: np.full(node_count, -1, dtype=int) for radius in (25, 50, 100)}
    frames = []
    for week_index, week in enumerate(weeks):
        current = np.asarray(positive_sets[week_index], dtype=int)
        prior_nodes = np.flatnonzero(ever)
        previous4 = np.unique(np.concatenate(positive_sets[max(0, week_index - 4):week_index])) if week_index else np.array([], dtype=int)
        previous13 = np.unique(np.concatenate(positive_sets[max(0, week_index - 13):week_index])) if week_index else np.array([], dtype=int)
        prior_lats = lat[prior_nodes]
        previous4_lats = lat[previous4]
        previous13_lats = lat[previous13]
        northmost = float(np.max(prior_lats)) if len(prior_lats) else np.nan
        p95_prior = float(np.percentile(prior_lats, 95)) if len(prior_lats) else np.nan
        p95_previous4 = float(np.percentile(previous4_lats, 95)) if len(previous4_lats) else np.nan
        p95_previous13 = float(np.percentile(previous13_lats, 95)) if len(previous13_lats) else np.nan
        distance_any, _ = tree_distances(xy, prior_nodes, xy)
        distance4, _ = tree_distances(xy, previous4, xy)
        distance13, _ = tree_distances(xy, previous13, xy)
        frame = pd.DataFrame({
            "week": week,
            "week_index": week_index,
            "node_id": np.arange(node_count, dtype=int),
            "source_history_cutoff": weeks[week_index - 1] if week_index else None,
            "northmost_prior_latitude": northmost,
            "p95_prior_latitude": p95_prior,
            "p95_previous4_latitude": p95_previous4,
            "p95_previous13_latitude": p95_previous13,
            "distance_to_any_prior_detection_km": distance_any,
            "distance_to_previous4_detection_km": distance4,
            "distance_to_previous13_detection_km": distance13,
            "distance_north_of_previous_front_km": (lat - northmost) * LATITUDE_KM if np.isfinite(northmost) else np.nan,
            "distance_south_of_previous_front_km": (northmost - lat) * LATITUDE_KM if np.isfinite(northmost) else np.nan,
            "weeks_since_any_detection_within_25km": np.where(last_seen[25] >= 0, week_index - last_seen[25], np.nan),
            "weeks_since_any_detection_within_50km": np.where(last_seen[50] >= 0, week_index - last_seen[50], np.nan),
            "weeks_since_any_detection_within_100km": np.where(last_seen[100] >= 0, week_index - last_seen[100], np.nan),
        })
        frames.append(frame)
        if len(current):
            current_tree = cKDTree(xy[current])
            current_dist = current_tree.query(xy, k=1)[0]
            for radius in (25, 50, 100):
                exposed = current_dist <= radius
                last_seen[radius][exposed] = week_index
        ever[current] = True
    return pd.concat(frames, ignore_index=True)


def load_inputs(model_output: Path, source_path: Path) -> dict[str, Any]:
    if sha256_file(source_path) != EXPECTED_SOURCE_SHA:
        raise AssertionError("authoritative observation source SHA changed")
    with source_path.open("rb") as handle:
        source_rows = sum(1 for _ in handle) - 1
    if source_rows != EXPECTED_SOURCE_ROWS:
        raise AssertionError(f"unexpected source row count: {source_rows}")
    nodes = pd.read_parquet(model_output / "raw" / "nodes.parquet").sort_values("model_node_id").reset_index(drop=True)
    edges = pd.read_parquet(model_output / "raw" / "edges_queen.parquet")
    weeks = audit_week_frame()
    classification = pd.read_parquet(model_output / CLASSIFICATION_PATH_NAME)
    classification["audit_week_index"] = classification["iso_week"].map(dict(zip(weeks["week"], weeks["audit_week_index"])))
    obs = classification.loc[
        classification["revised_domain_membership"].astype(bool)
        & classification["audit_week_index"].notna()
        & classification["model_node_id"].notna()
    ].copy()
    obs["audit_week_index"] = obs["audit_week_index"].astype(int)
    obs["model_node_id"] = obs["model_node_id"].astype(int)
    if len(nodes) != EXPECTED_NODE_COUNT or len(edges) != EXPECTED_EDGE_COUNT:
        raise AssertionError("accepted revised-domain dimensions changed")
    if not np.array_equal(nodes["model_node_id"].to_numpy(), np.arange(EXPECTED_NODE_COUNT)):
        raise AssertionError("model node ordering changed")
    counts = np.zeros((len(weeks), len(nodes)), dtype=np.int32)
    grouped = obs.groupby(["audit_week_index", "model_node_id"]).size()
    for (week_index, node_id), value in grouped.items():
        counts[int(week_index), int(node_id)] = int(value)
    return {
        "nodes": nodes,
        "edges": edges,
        "weeks": weeks,
        "obs": obs,
        "counts": counts,
        "source_sha": EXPECTED_SOURCE_SHA,
        "source_rows": source_rows,
    }


def archive_v1_artifacts(output: Path, git_sha: str) -> dict[str, Any]:
    archive = output / "v1_archive"
    manifest_path = archive / "v1_artifact_archive_manifest.json"
    if manifest_path.exists():
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    required = [
        "manifests/model_freeze_manifest.json",
        "manifests/model_freeze_manifest.sha256",
        "manifests/terminal_unlock.json",
        "manifests/terminal_evaluation_complete.json",
        "model/frozen_model.json",
        "model/fitted_preprocessing.json",
        "predictions/terminal_predictions.parquet",
        "metrics/terminal_metrics.json",
        "metrics/terminal_weekly_metrics.csv",
        "metrics/terminal_latitude_metrics.csv",
        "metrics/terminal_calibration.csv",
        "regional/terminal_regional_metrics.csv",
        "us_transfer/terminal_us_positive_ranks.csv",
    ]
    records = []
    for relative in required:
        source = V1_OUTPUT / relative
        if not source.exists():
            raise FileNotFoundError(source)
        destination = archive / "artifacts" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        records.append({
            "relative_path": relative,
            "source_path": str(source),
            "archive_path": str(destination),
            "size_bytes": source.stat().st_size,
            "sha256": sha256_file(source),
        })
    payload = {
        "status": "V1_ARTIFACTS_ARCHIVED_IMMUTABLE_REFERENCE",
        "created_utc": utc_now(),
        "v1_model_identifier": "STGNN-Hurdle-V1",
        "v1_reference_git_sha": V1_REFERENCE_SHA,
        "current_git_sha_when_archived": git_sha,
        "former_terminal_status": "historical_evaluated_data",
        "source_observation_sha256": EXPECTED_SOURCE_SHA,
        "artifacts": records,
    }
    write_json(manifest_path, payload)
    (archive / "v1_artifact_archive_manifest.sha256").write_text(
        f"{sha256_file(manifest_path)}  v1_artifact_archive_manifest.json\n", encoding="utf-8"
    )
    return payload


def build_histories(data: dict[str, Any]) -> dict[str, Any]:
    nodes = data["nodes"]
    weeks = data["weeks"]
    counts = data["counts"]
    obs = data["obs"]
    positive_sets = [np.flatnonzero(counts[w] > 0) for w in range(len(weeks))]
    new_matrix = np.zeros_like(counts, dtype=bool)
    ever = np.zeros(len(nodes), dtype=bool)
    first_rows = []
    history_rows = []
    for w, current in enumerate(positive_sets):
        new = current[~ever[current]]
        new_matrix[w, new] = True
        ever[current] = True
        for node_id in new:
            first_rows.append({
                "week": weeks.iloc[w]["week"],
                "week_index": w,
                "node_id": int(node_id),
                "latitude": float(nodes.iloc[node_id]["lat"]),
                "longitude": float(nodes.iloc[node_id]["lon"]),
                "region": nodes.iloc[node_id]["country_or_domain_region"],
                "observed_count": int(counts[w, node_id]),
            })
    for node_id in np.flatnonzero(ever):
        node_weeks = np.flatnonzero(counts[:, node_id] > 0)
        runs = np.split(node_weeks, np.where(np.diff(node_weeks) > 1)[0] + 1)
        gaps = np.diff(node_weeks) - 1
        history_rows.append({
            "node_id": int(node_id),
            "region": nodes.iloc[node_id]["country_or_domain_region"],
            "latitude": float(nodes.iloc[node_id]["lat"]),
            "longitude": float(nodes.iloc[node_id]["lon"]),
            "first_positive_week": weeks.iloc[int(node_weeks[0])]["week"],
            "last_positive_week": weeks.iloc[int(node_weeks[-1])]["week"],
            "positive_weeks": int(len(node_weeks)),
            "total_detections": int(counts[:, node_id].sum()),
            "maximum_weekly_count": int(counts[:, node_id].max()),
            "longest_consecutive_positive_run": int(max(len(run) for run in runs)),
            "separate_positive_episodes": int(len(runs)),
            "episode_gaps_weeks": ";".join(str(int(value)) for value in gaps),
            "median_gap_weeks": float(np.median(gaps)) if len(gaps) else np.nan,
            "maximum_gap_weeks": int(gaps.max()) if len(gaps) else np.nan,
        })
    weekly = []
    for w, current in enumerate(positive_sets):
        prior = set(np.flatnonzero(np.any(counts[:w] > 0, axis=0)).tolist())
        new = [int(node) for node in current if int(node) not in prior]
        recurrent = [int(node) for node in current if int(node) in prior]
        weekly.append({
            "week": weeks.iloc[w]["week"],
            "week_index": w,
            "first_ever_positive_nodes": len(new),
            "recurrent_positive_nodes": len(recurrent),
            "fraction_first_ever": len(new) / len(current) if len(current) else np.nan,
            "fraction_recurrent": len(recurrent) / len(current) if len(current) else np.nan,
        })
    positive_frame = pd.DataFrame(first_rows)
    return {
        "positive_sets": positive_sets,
        "new_matrix": new_matrix,
        "first_rows": positive_frame,
        "history": pd.DataFrame(history_rows),
        "weekly_new_recurrent": pd.DataFrame(weekly),
    }


def build_front_audit(data: dict[str, Any], histories: dict[str, Any]) -> dict[str, Any]:
    nodes = data["nodes"]
    weeks = data["weeks"]
    counts = data["counts"]
    obs = data["obs"]
    xy = nodes[["x", "y"]].to_numpy(float)
    lat = nodes["lat"].to_numpy(float)
    lon = nodes["lon"].to_numpy(float)
    positive_sets = histories["positive_sets"]
    front_states = causal_front_descriptors(positive_sets, xy, lat, weeks["week"].tolist())
    weekly_rows = []
    previous_centroid = None
    previous_axis = None
    prior_ever = np.array([], dtype=int)
    first_distance_rows = []
    for w, current in enumerate(positive_sets):
        current_xy = xy[current]
        current_lat = lat[current]
        current_lon = lon[current]
        previous = positive_sets[w - 1] if w else np.array([], dtype=int)
        previous4 = np.unique(np.concatenate(positive_sets[max(0, w - 4):w])) if w else np.array([], dtype=int)
        previous13 = np.unique(np.concatenate(positive_sets[max(0, w - 13):w])) if w else np.array([], dtype=int)
        prior_tree = cKDTree(xy[prior_ever]) if len(prior_ever) else None
        previous4_tree = cKDTree(xy[previous4]) if len(previous4) else None
        previous13_tree = cKDTree(xy[previous13]) if len(previous13) else None
        previous_tree = cKDTree(xy[previous]) if len(previous) else None
        new = current[~np.isin(current, prior_ever)]
        if prior_tree is not None and len(new):
            distance_any, nearest_any = prior_tree.query(xy[new], k=1)
            distance_any = np.asarray(distance_any)
            nearest_any = prior_ever[np.asarray(nearest_any, dtype=int)]
            if previous4_tree is not None:
                distance_previous4, nearest_previous4 = previous4_tree.query(xy[new], k=1)
                distance_previous4 = np.asarray(distance_previous4)
                nearest_previous4 = previous4[np.asarray(nearest_previous4, dtype=int)]
            else:
                distance_previous4 = np.full(len(new), np.nan)
                nearest_previous4 = np.full(len(new), -1, dtype=int)
            if previous13_tree is not None:
                distance_previous13, nearest_previous13 = previous13_tree.query(xy[new], k=1)
                distance_previous13 = np.asarray(distance_previous13)
                nearest_previous13 = previous13[np.asarray(nearest_previous13, dtype=int)]
            else:
                distance_previous13 = np.full(len(new), np.nan)
                nearest_previous13 = np.full(len(new), -1, dtype=int)
            first_distance_rows.extend({
                "week": weeks.iloc[w]["week"],
                "week_index": w,
                "node_id": int(node_id),
                "latitude": float(lat[node_id]),
                "longitude": float(lon[node_id]),
                "region": nodes.iloc[node_id]["country_or_domain_region"],
                "observed_count": int(counts[w, node_id]),
                "distance_to_nearest_any_prior_km": float(distance),
                "nearest_any_prior_node_id": int(nearest),
                "distance_to_nearest_previous4_km": float(distance4),
                "nearest_previous4_node_id": int(nearest4),
                "distance_to_nearest_previous13_km": float(distance13),
                "nearest_previous13_node_id": int(nearest13),
            } for node_id, distance, nearest, distance4, nearest4, distance13, nearest13 in zip(
                new, distance_any, nearest_any, distance_previous4, nearest_previous4, distance_previous13, nearest_previous13
            ))
        else:
            distance_any = np.full(len(new), np.nan)
        previous_distance = previous_tree.query(current_xy, k=1)[0] if previous_tree is not None and len(current) else np.array([])
        centroid = current_xy.mean(axis=0) if len(current) else None
        centroid_delta = centroid - previous_centroid if centroid is not None and previous_centroid is not None else None
        current_angle, current_axis = principal_axis(current_xy)
        principal_projection = float(np.dot(centroid_delta, previous_axis)) if centroid_delta is not None and previous_axis is not None else np.nan
        new_vectors = []
        new_direction = np.nan
        if prior_tree is not None and len(new):
            new_vectors = xy[new] - xy[nearest_any]
            vector = np.mean(new_vectors, axis=0)
            new_direction = float(np.degrees(np.arctan2(vector[1], vector[0])) % 360.0)
        node_lat_spread = float(current_lat.max() - current_lat.min()) if len(current) else np.nan
        node_lon_spread = float(current_lon.max() - current_lon.min()) if len(current) else np.nan
        week_obs = obs.loc[obs["audit_week_index"] == w]
        row = {
            "week": weeks.iloc[w]["week"],
            "week_index": w,
            "total_recorded_detections": int(counts[w].sum()),
            "positive_nodes": int(len(current)),
            "first_ever_positive_nodes": int(len(new)),
            "recurrent_positive_nodes": int(len(current) - len(new)),
            "fraction_first_ever": len(new) / len(current) if len(current) else np.nan,
            "fraction_recurrent": (len(current) - len(new)) / len(current) if len(current) else np.nan,
            "occupied_state_count": int(week_obs["state"].dropna().nunique()),
            "occupied_region_count": int(week_obs["broad_region"].dropna().nunique()),
            "latitude_min": float(current_lat.min()) if len(current) else np.nan,
            "latitude_max": float(current_lat.max()) if len(current) else np.nan,
            "latitude_span": node_lat_spread,
            "longitude_min": float(current_lon.min()) if len(current) else np.nan,
            "longitude_max": float(current_lon.max()) if len(current) else np.nan,
            "longitude_span": node_lon_spread,
            "occupied_25km_cells": int(nodes.iloc[current].groupby(["row", "column"]).ngroups) if len(current) else 0,
            "convex_hull_area_km2": convex_hull_area_km2(current_xy),
            "principal_axis_angle_deg": current_angle,
            "centroid_x_km": float(centroid[0]) if centroid is not None else np.nan,
            "centroid_y_km": float(centroid[1]) if centroid is not None else np.nan,
            "centroid_displacement_km": float(np.linalg.norm(centroid_delta)) if centroid_delta is not None else np.nan,
            "centroid_dx_km": float(centroid_delta[0]) if centroid_delta is not None else np.nan,
            "centroid_dy_km": float(centroid_delta[1]) if centroid_delta is not None else np.nan,
            "principal_axis_displacement_km": principal_projection,
            "nearest_new_cell_direction_deg": new_direction,
            "northmost_change_km": float((current_lat.max() - lat[positive_sets[w - 1]].max()) * LATITUDE_KM) if w and len(current) and len(previous) else np.nan,
            "p95_front_latitude": float(np.percentile(current_lat, 95)) if len(current) else np.nan,
            "northmost_latitude": float(current_lat.max()) if len(current) else np.nan,
            "p95_front_change_km": float((np.percentile(current_lat, 95) - np.percentile(lat[previous], 95)) * LATITUDE_KM) if w and len(current) and len(previous) else np.nan,
            "new_to_prior_distance_median_km": float(np.nanmedian(distance_any)) if len(distance_any) and np.isfinite(distance_any).any() else np.nan,
            "new_to_prior_distance_p90_km": float(np.nanpercentile(distance_any, 90)) if len(distance_any) and np.isfinite(distance_any).any() else np.nan,
            "new_to_prior_distance_p95_km": float(np.nanpercentile(distance_any, 95)) if len(distance_any) and np.isfinite(distance_any).any() else np.nan,
            "new_to_prior_distance_max_km": float(np.nanmax(distance_any)) if len(distance_any) and np.isfinite(distance_any).any() else np.nan,
            "previous_week_distance_median_km": float(np.nanmedian(previous_distance)) if len(previous_distance) else np.nan,
            "previous_week_distance_p95_km": float(np.nanpercentile(previous_distance, 95)) if len(previous_distance) else np.nan,
        }
        weekly_rows.append(row)
        previous_centroid = centroid
        previous_axis = current_axis
        prior_ever = np.unique(np.concatenate([prior_ever, current]))
    weekly = pd.DataFrame(weekly_rows)
    first_distances = pd.DataFrame(first_distance_rows)
    front_candidates = []
    candidate_map = {
        "candidate_A_northmost_prior_latitude": "northmost_prior_latitude",
        "candidate_B_p95_prior_latitude": "p95_prior_latitude",
        "candidate_C_p95_previous4_latitude": "p95_previous4_latitude",
        "candidate_D_p95_previous13_latitude": "p95_previous13_latitude",
    }
    for label, column in candidate_map.items():
        stats = quantiles(front_states[column])
        front_candidates.append({"candidate": label, "definition": "strictly prior observations", **stats})
    pairwise = front_states[list(candidate_map.values())].corr(min_periods=2)
    pairwise.insert(0, "candidate", pairwise.index)
    return {
        "front_states": front_states,
        "weekly": weekly,
        "first_distances": first_distances,
        "front_candidates": pd.DataFrame(front_candidates),
        "front_pairwise": pairwise.reset_index(drop=True),
    }


def build_zero_transitions(data: dict[str, Any], front_states: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    counts = data["counts"]
    rows = []
    time_rows = []
    weeks, nodes = counts.shape
    nearest = front_states["distance_to_any_prior_detection_km"].to_numpy().reshape(weeks, nodes)
    since = {
        25: front_states["weeks_since_any_detection_within_25km"].to_numpy().reshape(weeks, nodes),
        50: front_states["weeks_since_any_detection_within_50km"].to_numpy().reshape(weeks, nodes),
        100: front_states["weeks_since_any_detection_within_100km"].to_numpy().reshape(weeks, nodes),
    }
    future = {}
    for horizon in (1, 4, 13):
        values = np.zeros_like(counts, dtype=bool)
        for offset in range(1, horizon + 1):
            if offset < weeks:
                values[:-offset] |= counts[offset:] > 0
        future[horizon] = values
    bins = [-np.inf, 25, 50, 100, 250, np.inf]
    labels = ["never_exposed", "0-25km", "25-50km", "50-100km", "100-250km", ">250km"]
    for horizon in (1, 4, 13):
        available = np.arange(weeks - horizon)
        zeros = counts[available] == 0
        distance = nearest[available]
        categories = np.full(distance.shape, "never_exposed", dtype=object)
        finite = np.isfinite(distance)
        categories[finite] = pd.cut(
            distance[finite],
            bins=[-np.inf, 25, 50, 100, 250, np.inf],
            labels=["0-25km", "25-50km", "50-100km", "100-250km", ">250km"],
            include_lowest=True,
        ).astype(str)
        for label in labels:
            mask = zeros & (categories == label)
            n = int(mask.sum())
            positives = int(future[horizon][available][mask].sum()) if n else 0
            rows.append({
                "distance_stratum": label,
                "horizon_weeks": horizon,
                "node_weeks": n,
                "subsequent_positive_node_weeks": positives,
                "subsequent_positive_probability": positives / n if n else np.nan,
            })
    for radius, values in since.items():
        for horizon in (1, 4, 13):
            available = np.arange(weeks - horizon)
            current = values[available]
            labels_since = np.full(current.shape, "never_exposed", dtype=object)
            finite = np.isfinite(current)
            labels_since[finite & (current == 0)] = "current_week_exposure"
            labels_since[finite & (current >= 1) & (current <= 3)] = "1-3_weeks"
            labels_since[finite & (current >= 4) & (current <= 12)] = "4-12_weeks"
            labels_since[finite & (current >= 13)] = "13plus_weeks"
            for label in ("never_exposed", "current_week_exposure", "1-3_weeks", "4-12_weeks", "13plus_weeks"):
                mask = (counts[available] == 0) & (labels_since == label)
                n = int(mask.sum())
                positive = int(future[horizon][available][mask].sum()) if n else 0
                time_rows.append({
                    "radius_km": radius,
                    "time_since_stratum": label,
                    "horizon_weeks": horizon,
                    "node_weeks": n,
                    "subsequent_positive_node_weeks": positive,
                    "subsequent_positive_probability": positive / n if n else np.nan,
                })
    return pd.DataFrame(rows), pd.DataFrame(time_rows)


def build_environment_comparison(data: dict[str, Any], histories: dict[str, Any], background_samples: pd.DataFrame) -> pd.DataFrame:
    model_output = Path(data["model_output"])
    raw_weeks = pd.read_parquet(model_output / "raw" / "weeks.parquet")
    # The parquet week_index is global to the production response history,
    # while dynamic_features.npy is stored in the local row order of weeks.parquet.
    raw_week_map = {week: index for index, week in enumerate(raw_weeks["iso_week"])}
    dynamic = np.load(model_output / "raw" / "dynamic_features.npy")
    static = np.load(model_output / "raw" / "static_features.npy")
    week_map = dict(zip(data["weeks"]["week"], data["weeks"]["audit_week_index"]))
    raw_indices = {int(week_map[week]): int(raw_week_map[week]) for week in raw_week_map if week in week_map}
    positive = np.argwhere(data["counts"] > 0)
    positive = pd.DataFrame(positive, columns=["week_index", "node_id"])
    first_matrix = histories["new_matrix"]
    positive["positive_type"] = np.where(first_matrix[positive["week_index"], positive["node_id"]], "first_ever", "recurrent")
    rows = []
    group_names = ["first_ever", "recurrent", "all_zero_node_weeks"]
    for scheme in sorted(background_samples["scheme"].unique()):
        sampled = background_samples.loc[background_samples["scheme"] == scheme]
        for feature_index, feature in enumerate(ALL_COVARIATE_FEATURES):
            feature_values: dict[str, np.ndarray] = {}
            for group in group_names:
                if group == "all_zero_node_weeks":
                    selected = sampled.loc[sampled["class"] == "background"]
                else:
                    selected = positive.loc[positive["positive_type"] == group]
                selected = selected[selected["week_index"].isin(raw_indices)]
                if selected.empty:
                    values = np.array([], dtype=float)
                elif feature_index < len(ENVIRONMENTAL_FEATURES):
                    raw_w = selected["week_index"].map(raw_indices).to_numpy(int)
                    values = dynamic[raw_w, selected["node_id"].to_numpy(int), feature_index]
                else:
                    static_index = feature_index - len(ENVIRONMENTAL_FEATURES)
                    values = static[selected["node_id"].to_numpy(int), static_index]
                feature_values[group] = np.asarray(values, dtype=float)
            pos_values = np.concatenate([feature_values["first_ever"], feature_values["recurrent"]])
            bg_values = feature_values["all_zero_node_weeks"]
            if len(pos_values) and len(bg_values):
                positive_q05, positive_q95 = np.percentile(pos_values, [5, 95])
                background_min, background_max = np.nanmin(bg_values), np.nanmax(bg_values)
                overlap = max(0.0, min(positive_q95, background_max) - max(positive_q05, background_min))
                denominator = max(positive_q95 - positive_q05, 1e-12)
                overlap_fraction = overlap / denominator
            else:
                positive_q05 = positive_q95 = background_min = background_max = overlap_fraction = np.nan
            rows.append({
                "scheme": scheme,
                "feature": feature,
                "positive_n": int(len(pos_values)),
                "background_n": int(len(bg_values)),
                "positive_mean": float(np.nanmean(pos_values)) if len(pos_values) else np.nan,
                "background_mean": float(np.nanmean(bg_values)) if len(bg_values) else np.nan,
                "positive_q05": positive_q05,
                "positive_q95": positive_q95,
                "background_min": background_min,
                "background_max": background_max,
                "positive_5_95_range_covered_by_background": overlap_fraction,
                "covariate_history_note": "Dynamic covariates available from 2025-W01; static covariates available across the domain.",
            })
    return pd.DataFrame(rows)


def build_background_design(data: dict[str, Any], histories: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    nodes = data["nodes"]
    counts = data["counts"]
    weeks = data["weeks"]
    rng = np.random.default_rng(RNG_SEED)
    positive = pd.DataFrame(np.argwhere(counts > 0), columns=["week_index", "node_id"])
    positive["class"] = "positive"
    positive["lat"] = nodes.iloc[positive["node_id"]]["lat"].to_numpy()
    positive["lon"] = nodes.iloc[positive["node_id"]]["lon"].to_numpy()
    positive["region"] = nodes.iloc[positive["node_id"]]["country_or_domain_region"].to_numpy()
    positive["week"] = positive["week_index"].map(dict(zip(weeks["audit_week_index"], weeks["week"])))
    positive["latitude_band_5deg"] = np.floor(positive["lat"] / 5.0) * 5.0
    zero_by_week = [np.flatnonzero(counts[w] == 0) for w in range(len(weeks))]
    all_zero = np.argwhere(counts == 0)
    samples = []
    for scheme in ("A_all_available_domain_node_weeks", "B_temporally_matched_random_nonpositive", "C_temporally_matched_region_latitude_nonpositive"):
        pos_copy = positive.copy()
        pos_copy["scheme"] = scheme
        samples.append(pos_copy)
        if scheme == "A_all_available_domain_node_weeks":
            take = min(100000, len(all_zero))
            selected = all_zero[rng.choice(len(all_zero), size=take, replace=False)]
        else:
            selected_rows = []
            for row in positive.itertuples(index=False):
                candidates = zero_by_week[int(row.week_index)]
                if scheme.startswith("C_"):
                    candidate_mask = (
                        nodes.iloc[candidates]["country_or_domain_region"].to_numpy() == row.region
                    ) & (
                        np.floor(nodes.iloc[candidates]["lat"].to_numpy() / 5.0) * 5.0 == row.latitude_band_5deg
                    )
                    constrained = candidates[candidate_mask]
                    candidates = constrained if len(constrained) else candidates
                if len(candidates):
                    selected_rows.append((int(row.week_index), int(rng.choice(candidates))))
            selected = np.asarray(selected_rows, dtype=int)
        if len(selected):
            background = pd.DataFrame(selected, columns=["week_index", "node_id"])
            background["class"] = "background"
            background["lat"] = nodes.iloc[background["node_id"]]["lat"].to_numpy()
            background["lon"] = nodes.iloc[background["node_id"]]["lon"].to_numpy()
            background["region"] = nodes.iloc[background["node_id"]]["country_or_domain_region"].to_numpy()
            background["week"] = background["week_index"].map(dict(zip(weeks["audit_week_index"], weeks["week"])))
            background["latitude_band_5deg"] = np.floor(background["lat"] / 5.0) * 5.0
            background["scheme"] = scheme
            samples.append(background)
    sample_frame = pd.concat(samples, ignore_index=True)
    summary = []
    for scheme in sample_frame["scheme"].unique():
        scheme_samples = sample_frame[sample_frame["scheme"] == scheme]
        bg = scheme_samples[scheme_samples["class"] == "background"]
        pos = scheme_samples[scheme_samples["class"] == "positive"]
        if scheme.startswith("A_"):
            candidate_count = int(counts.size)
            definition = "all available revised-domain node-weeks; coverage sample uses at most 100,000 zero node-weeks"
            geographic_constraint = "none"
        elif scheme.startswith("B_"):
            candidate_count = int(sum(len(zero) for zero in zero_by_week))
            definition = "one deterministic random nonpositive node-week matched by week"
            geographic_constraint = "same week only"
        else:
            candidate_count = int(sum(len(zero) for zero in zero_by_week))
            definition = "one deterministic nonpositive node-week matched by week, broad region, and fixed 5-degree latitude band when available"
            geographic_constraint = "same week, broad region, fixed 5-degree latitude band; no response-dependent buffer"
        summary.append({
            "scheme": scheme,
            "definition": definition,
            "positive_rows": int(len(pos)),
            "candidate_background_rows": candidate_count,
            "sampled_background_rows": int(len(bg)),
            "weeks_represented": int(scheme_samples["week_index"].nunique()),
            "positive_latitude_mean": float(pos["lat"].mean()),
            "background_latitude_mean": float(bg["lat"].mean()),
            "background_latitude_min": float(bg["lat"].min()),
            "background_latitude_max": float(bg["lat"].max()),
            "background_mexico_rows": int((bg["region"] == "Mexico").sum()),
            "background_us_rows": int((bg["region"] == "U.S.-to-40N").sum()),
            "random_seed": RNG_SEED,
            "geographic_constraint": geographic_constraint,
        })
    weekly = []
    for scheme in sample_frame["scheme"].unique():
        for row in weeks.itertuples(index=False):
            sub = sample_frame[(sample_frame["scheme"] == scheme) & (sample_frame["week_index"] == row.audit_week_index)]
            zeros = int(len(zero_by_week[int(row.audit_week_index)]))
            weekly.append({
                "scheme": scheme,
                "week": row.week,
                "positive_rows": int((sub["class"] == "positive").sum()),
                "sampled_background_rows": int((sub["class"] == "background").sum()),
                "zero_nodeweek_candidates": zeros,
            })
    return sample_frame, pd.DataFrame(summary), pd.DataFrame(weekly)


def build_transition_figures(output: Path, weekly: pd.DataFrame, histories: dict[str, Any], front: dict[str, Any], transitions: pd.DataFrame) -> None:
    figures = output / "figures"
    figures.mkdir(parents=True, exist_ok=True)

    def chart(path: Path, title: str, series: list[tuple[str, np.ndarray]], y_label: str) -> None:
        width, height = 1100, 620
        left, top, right, bottom = 80, 55, 30, 70
        plot_w, plot_h = width - left - right, height - top - bottom
        values = np.concatenate([v[np.isfinite(v)] for _, v in series if np.isfinite(v).any()]) if any(np.isfinite(v).any() for _, v in series) else np.array([0, 1])
        lo, hi = float(values.min()), float(values.max())
        if math.isclose(lo, hi):
            hi = lo + 1.0
        def sx(i: int) -> float:
            return left + plot_w * i / max(1, len(series[0][1]) - 1)
        def sy(v: float) -> float:
            return top + plot_h * (hi - v) / (hi - lo)
        colors = ["#2166ac", "#b2182b", "#4d9221", "#762a83"]
        lines = [f'<line x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" y2="{top + plot_h}" stroke="#333"/>', f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_h}" stroke="#333"/>']
        for index, (label, values_series) in enumerate(series):
            points = []
            for i, value in enumerate(values_series):
                if np.isfinite(value):
                    points.append(f"{sx(i):.2f},{sy(float(value)):.2f}")
            if points:
                lines.append(f'<polyline fill="none" stroke="{colors[index % len(colors)]}" stroke-width="2" points="{" ".join(points)}"/>')
            lines.append(f'<text x="{left + 10 + index * 190}" y="{height - 30}" fill="{colors[index % len(colors)]}" font-size="14">{label}</text>')
        svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">', f'<rect width="100%" height="100%" fill="white"/>', f'<text x="{left}" y="28" font-size="20" font-family="sans-serif">{title}</text>', f'<text x="15" y="{top + plot_h / 2}" transform="rotate(-90 15 {top + plot_h / 2})" font-size="13">{y_label}</text>'] + lines + ["</svg>"]
        path.write_text("\n".join(svg), encoding="utf-8")

    chart(figures / "01_weekly_detections_and_new_nodes.svg", "Recorded detections and first-ever positive nodes", [("detections", weekly["total_recorded_detections"].to_numpy(float)), ("first-ever nodes", weekly["first_ever_positive_nodes"].to_numpy(float)), ("recurrent nodes", weekly["recurrent_positive_nodes"].to_numpy(float))], "count")
    chart(figures / "02_recurrent_vs_first_positive_nodes.svg", "First-ever versus recurrent positive nodes", [("first-ever", weekly["first_ever_positive_nodes"].to_numpy(float)), ("recurrent", weekly["recurrent_positive_nodes"].to_numpy(float))], "positive nodes")
    chart(figures / "03_front_latitude_progression.svg", "Northmost and percentile front progression", [("northmost", weekly["northmost_latitude"].to_numpy(float)), ("p95 current", weekly["p95_front_latitude"].to_numpy(float)), ("p95 prior", front["front_states"].groupby("week_index")["p95_prior_latitude"].first().reindex(weekly["week_index"]).to_numpy(float))], "latitude")
    chart(figures / "05_apparent_front_progression.svg", "Apparent front progression diagnostics", [("northmost change km", weekly["northmost_change_km"].to_numpy(float)), ("p95 change km", weekly["p95_front_change_km"].to_numpy(float)), ("centroid displacement km", weekly["centroid_displacement_km"].to_numpy(float))], "km per week")

    distances = front["first_distances"]["distance_to_nearest_any_prior_km"].to_numpy(float) if not front["first_distances"].empty else np.array([])
    histogram_path = figures / "04_first_positive_distance_histogram.svg"
    bins = np.array([0, 25, 50, 100, 250, 500, 1000, np.inf])
    labels = ["0-25", "25-50", "50-100", "100-250", "250-500", "500-1000", ">1000"]
    counts = [int(((distances >= bins[i]) & (distances < bins[i + 1])).sum()) for i in range(len(labels))]
    max_count = max(counts + [1])
    bars = [f'<rect x="{90 + i * 135}" y="{540 - 420 * value / max_count}" width="90" height="{420 * value / max_count}" fill="#4393c3"/><text x="{95 + i * 135}" y="565" font-size="12">{label}</text><text x="{120 + i * 135}" y="{530 - 420 * value / max_count}" font-size="12">{value}</text>' for i, (label, value) in enumerate(zip(labels, counts))]
    histogram_path.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="620"><rect width="100%" height="100%" fill="white"/><text x="80" y="30" font-size="20">First-positive distance to any prior positive node</text><line x1="80" y1="540" x2="1050" y2="540" stroke="#333"/>{"".join(bars)}<text x="20" y="300" transform="rotate(-90 20 300)" font-size="13">node count</text></svg>', encoding="utf-8")

    map_path = figures / "06_first_positive_week_by_node.svg"
    nodes = front["nodes"]
    first_week = histories["history"].set_index("node_id")["first_positive_week"] if not histories["history"].empty else pd.Series(dtype=object)
    svg_nodes = []
    lon = nodes["lon"].to_numpy(float)
    lat = nodes["lat"].to_numpy(float)
    xmin, xmax, ymin, ymax = lon.min(), lon.max(), lat.min(), lat.max()
    for node_id in range(len(nodes)):
        if node_id not in first_week.index:
            color = "#d9d9d9"
        else:
            value = weekly.index[weekly["week"] == first_week.loc[node_id]].tolist()[0] if (weekly["week"] == first_week.loc[node_id]).any() else 0
            color = f"hsl({220 - 1.3 * value:.1f},70%,45%)"
        px = 40 + 1020 * (lon[node_id] - xmin) / (xmax - xmin)
        py = 560 - 500 * (lat[node_id] - ymin) / (ymax - ymin)
        svg_nodes.append(f'<circle cx="{px:.2f}" cy="{py:.2f}" r="1.2" fill="{color}"/>')
    map_path.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="620"><rect width="100%" height="100%" fill="white"/><text x="40" y="25" font-size="20">First-positive week by retained-domain node</text>{"".join(svg_nodes)}</svg>', encoding="utf-8")

    transition_path = figures / "07_time_since_nearby_detection_transition.svg"
    subset = transitions[transitions["radius_km"] == 50]
    chart(transition_path, "Subsequent positivity by time since nearby detection (50 km)", [(str(h), subset.loc[subset["horizon_weeks"] == h, "subsequent_positive_probability"].to_numpy(float)) for h in (1, 4, 13)], "probability")

    bg_path = figures / "08_presence_background_candidate_coverage.svg"
    base = weekly[["week_index", "week", "positive_nodes"]].copy()
    chart(bg_path, "Positive-node temporal coverage used by background designs", [("positive nodes", base["positive_nodes"].to_numpy(float))], "node-weeks")


def build_proxy_inventory() -> pd.DataFrame:
    return pd.DataFrame([
        {"proxy": "administrative state", "available": True, "spatial_coverage": "U.S. observations where classified", "temporal_coverage": "observation dates", "interpretation": "coarse reporting geography", "confounding_risk": "high; geography is correlated with ecology and data availability"},
        {"proxy": "broad region / country grouping", "available": True, "spatial_coverage": "Mexico and U.S.-to-40N domain", "temporal_coverage": "observation dates", "interpretation": "coarse administrative/domain label", "confounding_risk": "high; not an observation-effort measure"},
        {"proxy": "host category", "available": True, "spatial_coverage": "positive source records", "temporal_coverage": "observation dates", "interpretation": "reported host type", "confounding_risk": "high; conditional on reporting"},
        {"proxy": "longitude, latitude, projected x/y", "available": True, "spatial_coverage": "all retained nodes and source points", "temporal_coverage": "static coordinates", "interpretation": "location and accessibility surrogate only", "confounding_risk": "high"},
        {"proxy": "road density / night illumination / population / accessibility / survey effort", "available": False, "spatial_coverage": "not found in project holdings searched for Task 3A", "temporal_coverage": "not available", "interpretation": "potential reporting covariates require new data or review", "confounding_risk": "unknown; no automatic acquisition authorized"},
    ])


def build_design_tables() -> tuple[pd.DataFrame, pd.DataFrame]:
    families = pd.DataFrame([
        {"family": "V2-A", "status": "RECOMMENDED NEXT", "description": "Current hurdle plus strictly causal front-state features", "identifiability": "high for the recorded-detection estimand", "passive_reporting_compatibility": "moderate; retains observed detection response", "moving_front": "directly represented", "positive_counts": "retained", "computational_feasibility": "high", "validation_feasibility": "high", "data_requirements": "existing data", "leakage_risk": "manageable with causal tests", "rationale": "Best next descriptive-to-predictive bridge if prior proximity and front history show strong structure; requires review of the response estimand."},
        {"family": "V2-B", "status": "PLAUSIBLE SECONDARY", "description": "Presence-background occurrence plus conditional count", "identifiability": "depends on background estimand", "passive_reporting_compatibility": "potentially better for unequal opportunity", "moving_front": "can be added", "positive_counts": "retained", "computational_feasibility": "moderate", "validation_feasibility": "moderate", "data_requirements": "defensible background design", "leakage_risk": "background construction risk", "rationale": "Useful sensitivity direction if zero-label exchangeability is strongly contradicted, but background sampling changes the estimand."},
        {"family": "V2-C", "status": "DEFER", "description": "Discrete spatiotemporal recorded-detection intensity / point-process approximation", "identifiability": "moderate for recorded intensity, not latent occurrence", "passive_reporting_compatibility": "good if lambda is explicitly recorded-detection intensity", "moving_front": "natural", "positive_counts": "natural", "computational_feasibility": "moderate", "validation_feasibility": "moderate", "data_requirements": "existing data plus careful exposure interpretation", "leakage_risk": "manageable", "rationale": "Conceptually coherent for counts, but should follow the observation and front audit rather than replace it prematurely."},
        {"family": "V2-D", "status": "NOT IDENTIFIABLE", "description": "Latent occurrence/intensity plus explicit observation/reporting process", "identifiability": "not defensible from current data alone", "passive_reporting_compatibility": "best conceptually", "moving_front": "possible", "positive_counts": "possible", "computational_feasibility": "low", "validation_feasibility": "low without new data", "data_requirements": "observation denominator or validated reporting proxies", "leakage_risk": "high", "rationale": "A latent observation process cannot be separated from occurrence without repeated negatives, effort, known-at-risk units, or credible reporting proxies."},
    ])
    validation = pd.DataFrame([
        {"strategy": "A rolling-origin validation", "role": "development validation", "feasibility": "high", "strength": "uses multiple temporal origins and tests causal availability", "limitation": "not independent of already inspected 2025-2026 outcomes", "recommendation": "use for V2 development checks"},
        {"strategy": "B leave-late-period-out pseudo-prospective folds", "role": "historical pseudo-prospective evaluation", "feasibility": "high", "strength": "tests late-period transfer under frozen fold specifications", "limitation": "historical outcomes are previously seen and cannot be called final test", "recommendation": "use as secondary development evidence"},
        {"strategy": "C geographic transfer folds", "role": "development transfer validation", "feasibility": "moderate", "strength": "directly probes Mexico-to-U.S. and south-to-north transfer", "limitation": "few U.S. positives and domain imbalance", "recommendation": "use as a pre-specified diagnostic"},
        {"strategy": "D future unseen-data accumulation", "role": "genuinely unseen evaluation", "feasibility": "requires future data", "strength": "preserves independence after V2 specification freeze", "limitation": "requires waiting and a written freeze protocol", "recommendation": "preferred long-term final evaluation"},
    ])
    return families, validation


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-output", type=Path, default=Path("/project/disease_ecology/STGNN-output/revised_model_data"))
    parser.add_argument("--source", type=Path, default=SOURCE_PATH)
    parser.add_argument("--output", type=Path, default=Path("/project/disease_ecology/STGNN-output/v2_audit"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    for subdir in ("v1_archive", "observation_process", "front_states", "background_design", "figures", "tables", "manifests"):
        (args.output / subdir).mkdir(parents=True, exist_ok=True)
    data = load_inputs(args.model_output, args.source)
    data["model_output"] = str(args.model_output)
    branch = subprocess.run(["git", "branch", "--show-current"], capture_output=True, text=True, check=True).stdout.strip()
    git_sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    archive = archive_v1_artifacts(args.output, git_sha)
    histories = build_histories(data)
    front = build_front_audit(data, histories)
    transitions, time_since = build_zero_transitions(data, front["front_states"])
    backgrounds, background_summary, background_weekly = build_background_design(data, histories)
    environmental = build_environment_comparison(data, histories, backgrounds)
    proxies = build_proxy_inventory()
    families, validation = build_design_tables()

    write_csv(args.output / "observation_process" / "weekly_reporting_intensity.csv", front["weekly"])
    write_csv(args.output / "observation_process" / "node_detection_history.csv", histories["history"])
    write_csv(args.output / "observation_process" / "first_vs_recurrent_weekly.csv", histories["weekly_new_recurrent"])
    write_csv(args.output / "observation_process" / "first_positive_distance_summary.csv", pd.DataFrame([
        {"metric": key, **quantiles(front["first_distances"][key])}
        for key in front["first_distances"].columns if key.endswith("_km")
    ]))
    write_csv(args.output / "observation_process" / "zero_distance_transition_summary.csv", transitions)
    write_csv(args.output / "observation_process" / "time_since_nearby_detection_transition.csv", time_since)
    write_csv(args.output / "observation_process" / "environmental_first_recurrent_zero_summary.csv", environmental)
    write_csv(args.output / "front_states" / "weekly_front_summary.csv", front["weekly"])
    write_csv(args.output / "front_states" / "front_candidate_comparison.csv", front["front_candidates"])
    write_csv(args.output / "front_states" / "front_candidate_pairwise_correlations.csv", front["front_pairwise"])
    write_csv(args.output / "front_states" / "first_positive_distance_summary.csv", pd.DataFrame([
        {"metric": key, **quantiles(front["first_distances"][key])}
        for key in front["first_distances"].columns if key.endswith("_km")
    ]))
    write_csv(args.output / "front_states" / "front_progression_summary.csv", pd.DataFrame([
        {"metric": key, **quantiles(front["weekly"][key])}
        for key in ("northmost_change_km", "p95_front_change_km", "centroid_displacement_km", "principal_axis_displacement_km", "new_to_prior_distance_median_km", "new_to_prior_distance_p95_km")
    ]))
    front["front_states"].to_parquet(args.output / "front_states" / "front_state_node_week.parquet", index=False)
    write_csv(args.output / "background_design" / "background_design_comparison.csv", background_summary)
    write_csv(args.output / "background_design" / "background_design_weekly.csv", background_weekly)
    backgrounds.to_parquet(args.output / "background_design" / "background_design_samples.parquet", index=False)
    write_csv(args.output / "background_design" / "background_environment_coverage.csv", environmental)
    write_csv(args.output / "tables" / "reporting_proxy_inventory.csv", proxies)
    write_csv(args.output / "tables" / "v2_model_family_comparison.csv", families)
    write_csv(args.output / "tables" / "validation_strategy_comparison.csv", validation)
    build_transition_figures(args.output, front["weekly"], histories, {**front, "nodes": data["nodes"]}, time_since)

    manifest = {
        "status": "task3a_v2_audit_complete_no_predictive_fit",
        "created_utc": utc_now(),
        "git_sha": git_sha,
        "branch": branch,
        "v1_reference_sha": V1_REFERENCE_SHA,
        "v1_model_identifier": "STGNN-Hurdle-V1",
        "former_terminal_status": "historical_evaluated_data",
        "observation_source": str(args.source),
        "observation_source_sha256": data["source_sha"],
        "observation_source_rows": data["source_rows"],
        "domain": {"nodes": EXPECTED_NODE_COUNT, "directed_queen_edges": EXPECTED_EDGE_COUNT, "regions": ["Mexico", "U.S.-to-40N"], "components": 4, "isolates": 3},
        "audit_period": {"start": AUDIT_START, "end": AUDIT_END, "weeks": int(len(data["weeks"]))},
        "front_definitions": {
            "A": "northmost observed latitude through prior weeks",
            "B": "95th percentile latitude of all prior positive nodes",
            "C": "95th percentile latitude in prior four weeks",
            "D": "95th percentile latitude in prior thirteen weeks",
            "E": "distance to nearest node positive in any prior week",
            "F": "distance to nearest node positive in prior four weeks",
        },
        "distance_definitions": {"coordinate_system": "canonical Albers equal-area projected node x/y axes with kilometre length units", "units": "kilometres", "radii_km": [25, 50, 100], "zero_distance_bins_km": [0, 25, 50, 100, 250, "inf"]},
        "front_state_status": "AUDIT ONLY — NOT YET AUTHORIZED AS MODEL FEATURES",
        "background_designs": ["A_all_available_domain_node_weeks", "B_temporally_matched_random_nonpositive", "C_temporally_matched_region_latitude_nonpositive"],
        "reporting_proxies_found": proxies.to_dict("records"),
        "tests": ["tests/test_task3a_v2_audit.py", "strict temporal causality", "future-data mutation invariance", "node/week ordering", "background reproducibility", "manifest consistency"],
        "slurm_jobs": {"v1_freeze": "20844222", "v1_terminal_score": "20844224", "v1_reporting_recovery": "20844226", "task3a_audit_job": __import__("os").environ.get("SLURM_JOB_ID")},
        "recommended_v2_family": "V2-A",
        "recommended_v2_family_status": "RECOMMENDED NEXT — requires explicit V2 estimand review before fitting",
        "secondary_v2_family": "V2-B",
        "deferred_v2_families": ["V2-C"],
        "not_identifiable_v2_families": ["V2-D"],
        "validation_recommendation": "Use rolling-origin and geographic-transfer folds for V2 development, while reserving newly arriving observations after the V2 specification freeze as the first genuinely unseen evaluation.",
        "no_v2_predictive_model_fitted": True,
        "v1_archive_manifest": str(args.output / "v1_archive" / "v1_artifact_archive_manifest.json"),
    }
    write_json(args.output / "manifests" / "task3a_v2_audit_manifest.json", manifest)
    checksum_rows = []
    for path in sorted(args.output.rglob("*")):
        if path.is_file() and path.name != "task3a_v2_audit_checksums.csv":
            checksum_rows.append({"relative_path": str(path.relative_to(args.output)), "size_bytes": path.stat().st_size, "sha256": sha256_file(path)})
    write_csv(args.output / "manifests" / "task3a_v2_audit_checksums.csv", pd.DataFrame(checksum_rows))


if __name__ == "__main__":
    main()
