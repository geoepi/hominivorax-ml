#!/usr/bin/env python3
"""Descriptive W44 point-level spatiotemporal clustering investigation.

Restricted point coordinates and distances remain under the Atlas output root.
Only aggregate CSV/SVG products are written to the optional repository-results
directory.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import importlib.metadata
import json
import math
import os
import platform
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import Affine, rowcol
from rasterio.warp import transform as transform_coordinates
from scipy.spatial import cKDTree
from scipy.stats import pearsonr, spearmanr

try:
    import resource
except ImportError:  # Windows can run the synthetic unit checks.
    resource = None


EXPECTED_SOURCE_SHA256 = "784168081cc1d3206f3537b8731994cbfc34be15be7c515fe06710d4ea9bdaac"
SOURCE_PATH = Path(
    "/project/disease_ecology/NWScrewworm/data/processed_data/"
    "case_detections/combined_clean_obs_2026-11-13.csv"
)
CANDIDATE_ROOT = Path(
    "/project/disease_ecology/STGNN-output/structured_a3_refresh_2026w44"
)
GRID_PATH = Path(
    "/project/disease_ecology/STGNN-output/preflight/canonical_environment_mask.tif"
)
OUTPUT_DEFAULT = Path(
    "/project/disease_ecology/STGNN-output/"
    "a3_point_spatiotemporal_clustering_w44"
)
PRIMARY_START = "2025-W01"
PRIMARY_END = "2026-W44"
LAGS = (0, 1, 2, 3, 4, 8, 12)
HISTORY_WINDOWS = (1, 3, 8, 12)
DISTANCE_THRESHOLDS_KM = (1.0, 5.0, 10.0, 25.0)
CONCENTRATION_RADII_KM = (25.0, 50.0)
BOUNDARY_BAND_KM = 5.0
WGS84_WKT = (
    'GEOGCS["WGS 84",DATUM["WGS_1984",'
    'SPHEROID["WGS 84",6378137,298.257223563,'
    'AUTHORITY["EPSG","7030"]],AUTHORITY["EPSG","6326"]],'
    'PRIMEM["Greenwich",0,AUTHORITY["EPSG","8901"]],'
    'UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]],'
    'AUTHORITY["EPSG","4326"]]'
)
WEEK_EPOCH_MONDAY = date(1970, 1, 5)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def week_parts(value: str) -> tuple[int, int]:
    year_text, week_text = value.split("-W")
    return int(year_text), int(week_text)


def week_ordinal(year: int, week: int) -> int:
    monday = date.fromisocalendar(year, week, 1)
    return (monday - WEEK_EPOCH_MONDAY).days // 7


def ordinal_label(ordinal: int) -> str:
    monday = WEEK_EPOCH_MONDAY + timedelta(weeks=int(ordinal))
    iso = monday.isocalendar()
    return f"{iso.year:04d}-W{iso.week:02d}"


def canonical_decimal(value: str) -> str:
    from decimal import Decimal

    parsed = Decimal(value)
    if parsed == 0:
        return "0"
    return format(parsed.normalize(), "f")


def nearest_self_excluding(points_xy: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Nearest other record, excluding the queried record ID rather than coordinates."""
    count = len(points_xy)
    distances = np.full(count, np.nan, dtype=np.float64)
    neighbors = np.full(count, -1, dtype=np.int64)
    if count < 2:
        return distances, neighbors

    tree = cKDTree(points_xy)
    k = min(2, count)
    d, ix = tree.query(points_xy, k=k, workers=1)
    d = np.asarray(d).reshape(count, k)
    ix = np.asarray(ix).reshape(count, k)
    for i in range(count):
        eligible = [(float(d[i, j]), int(ix[i, j])) for j in range(k) if int(ix[i, j]) != i]
        if not eligible:
            continue
        nearest = min(item[0] for item in eligible)
        tied = [idx for dist_km, idx in eligible if abs(dist_km - nearest) <= 1e-12]
        distances[i] = nearest
        neighbors[i] = min(tied)
    return distances, neighbors


def nearest_reference(
    query_xy: np.ndarray,
    reference_xy: np.ndarray,
    *,
    reference_cell: np.ndarray | None = None,
    excluded_cell: np.ndarray | None = None,
    reference_ids: np.ndarray | None = None,
    workers: int = 1,
) -> tuple[np.ndarray, np.ndarray]:
    """Nearest historical point, optionally excluding each focal cell."""
    n_query = len(query_xy)
    distances = np.full(n_query, np.nan, dtype=np.float64)
    neighbors = np.full(n_query, -1, dtype=np.int64)
    n_reference = len(reference_xy)
    if n_query == 0 or n_reference == 0:
        return distances, neighbors
    tree = cKDTree(reference_xy)

    if excluded_cell is None:
        d, ix = tree.query(query_xy, k=1, workers=workers)
        d = np.asarray(d, dtype=np.float64).reshape(-1)
        ix = np.asarray(ix, dtype=np.int64).reshape(-1)
        valid = ix < n_reference
        distances[valid] = d[valid]
        if reference_ids is None:
            neighbors[valid] = ix[valid]
        else:
            neighbors[valid] = reference_ids[ix[valid]]
        return distances, neighbors

    if reference_cell is None:
        raise ValueError("reference_cell is required for focal-cell exclusion")
    if reference_ids is None:
        reference_ids = np.arange(n_reference, dtype=np.int64)
    pending = np.arange(n_query, dtype=np.int64)
    k = min(8, n_reference)
    while len(pending):
        d, ix = tree.query(query_xy[pending], k=k, workers=workers)
        d = np.asarray(d, dtype=np.float64)
        ix = np.asarray(ix, dtype=np.int64)
        if k == 1:
            d = d.reshape(-1, 1)
            ix = ix.reshape(-1, 1)
        next_pending: list[int] = []
        for row, focal_index in enumerate(pending):
            candidates = [
                (float(d[row, j]), int(ix[row, j]))
                for j in range(k)
                if int(ix[row, j]) < n_reference
                and int(reference_cell[int(ix[row, j])]) != int(excluded_cell[focal_index])
            ]
            if not candidates:
                if k < n_reference:
                    next_pending.append(int(focal_index))
                continue
            nearest = min(item[0] for item in candidates)
            tied = [idx for dist_km, idx in candidates if abs(dist_km - nearest) <= 1e-12]
            chosen = min(tied, key=lambda idx: int(reference_ids[idx]))
            distances[focal_index] = nearest
            neighbors[focal_index] = int(reference_ids[chosen])
        if not next_pending or k == n_reference:
            break
        pending = np.asarray(next_pending, dtype=np.int64)
        k = min(n_reference, k * 2)
    return distances, neighbors


def summarize_distances(values: Iterable[float], n_focal: int) -> dict[str, float | int]:
    values = np.asarray(list(values), dtype=np.float64)
    defined = values[np.isfinite(values)]
    result: dict[str, float | int] = {
        "n_focal": int(n_focal),
        "n_defined": int(len(defined)),
        "n_undefined": int(n_focal - len(defined)),
        "mean_km": np.nan,
        "sd_km": np.nan,
        "median_km": np.nan,
        "p10_km": np.nan,
        "p25_km": np.nan,
        "p75_km": np.nan,
        "p90_km": np.nan,
    }
    for threshold in DISTANCE_THRESHOLDS_KM:
        result[f"proportion_within_{threshold:g}km"] = np.nan
    if not len(defined):
        return result
    q = np.quantile(defined, [0.10, 0.25, 0.50, 0.75, 0.90])
    result.update(
        mean_km=float(defined.mean()),
        sd_km=float(defined.std(ddof=1)) if len(defined) > 1 else np.nan,
        p10_km=float(q[0]),
        p25_km=float(q[1]),
        median_km=float(q[2]),
        p75_km=float(q[3]),
        p90_km=float(q[4]),
    )
    for threshold in DISTANCE_THRESHOLDS_KM:
        result[f"proportion_within_{threshold:g}km"] = float(np.mean(defined <= threshold))
    return result


def wgs84_geodesic_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Vincenty inverse distance on WGS84; stable for the regional pairs here."""
    a = 6378.137
    flattening = 1.0 / 298.257223563
    b = (1.0 - flattening) * a
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    l = math.radians(lon2 - lon1)
    u1 = math.atan((1.0 - flattening) * math.tan(phi1))
    u2 = math.atan((1.0 - flattening) * math.tan(phi2))
    sin_u1, cos_u1 = math.sin(u1), math.cos(u1)
    sin_u2, cos_u2 = math.sin(u2), math.cos(u2)
    lam = l
    for _ in range(200):
        sin_lam, cos_lam = math.sin(lam), math.cos(lam)
        sin_sigma = math.sqrt(
            (cos_u2 * sin_lam) ** 2
            + (cos_u1 * sin_u2 - sin_u1 * cos_u2 * cos_lam) ** 2
        )
        if sin_sigma == 0:
            return 0.0
        cos_sigma = sin_u1 * sin_u2 + cos_u1 * cos_u2 * cos_lam
        sigma = math.atan2(sin_sigma, cos_sigma)
        sin_alpha = cos_u1 * cos_u2 * sin_lam / sin_sigma
        cos_sq_alpha = 1.0 - sin_alpha**2
        cos_2sigma_m = (
            cos_sigma - 2.0 * sin_u1 * sin_u2 / cos_sq_alpha
            if cos_sq_alpha > 1e-15
            else 0.0
        )
        c = flattening / 16.0 * cos_sq_alpha * (4.0 + flattening * (4.0 - 3.0 * cos_sq_alpha))
        updated = l + (1.0 - c) * flattening * sin_alpha * (
            sigma
            + c
            * sin_sigma
            * (
                cos_2sigma_m
                + c * cos_sigma * (-1.0 + 2.0 * cos_2sigma_m**2)
            )
        )
        if abs(updated - lam) < 1e-12:
            lam = updated
            break
        lam = updated
    else:
        raise RuntimeError("WGS84 inverse geodesic did not converge for a regional pair")
    u_sq = cos_sq_alpha * (a * a - b * b) / (b * b)
    cap_a = 1.0 + u_sq / 16384.0 * (
        4096.0 + u_sq * (-768.0 + u_sq * (320.0 - 175.0 * u_sq))
    )
    cap_b = u_sq / 1024.0 * (
        256.0 + u_sq * (-128.0 + u_sq * (74.0 - 47.0 * u_sq))
    )
    delta_sigma = cap_b * sin_sigma * (
        cos_2sigma_m
        + cap_b
        / 4.0
        * (
            cos_sigma * (-1.0 + 2.0 * cos_2sigma_m**2)
            - cap_b
            / 6.0
            * cos_2sigma_m
            * (-3.0 + 4.0 * sin_sigma**2)
            * (-3.0 + 4.0 * cos_2sigma_m**2)
        )
    )
    return b * cap_a * (sigma - delta_sigma)


def run_synthetic_checks() -> dict[str, object]:
    xy = np.array([[0.0, 0.0], [3.0, 4.0]], dtype=np.float64)
    d, ix = nearest_self_excluding(xy)
    assert np.allclose(d, [5.0, 5.0])
    assert ix[0] == 1 and ix[1] == 0
    threshold_xy = np.array([[0.0, 0.0], [3.0, 4.0], [0.0, 4.0]])
    threshold_tree = cKDTree(threshold_xy)
    ordered = threshold_tree.count_neighbors(
        threshold_tree, np.nextafter(5.0, -np.inf), cumulative=True
    )
    assert int((ordered - len(threshold_xy)) // 2) == 2

    colocated = np.array([[0.0, 0.0], [0.0, 0.0], [4.0, 0.0]], dtype=np.float64)
    d0, ix0 = nearest_self_excluding(colocated)
    assert d0[0] == 0.0 and ix0[0] == 1
    assert d0[1] == 0.0 and ix0[1] == 0

    references = np.array([[0.0, 0.0], [1.0, 0.0], [3.0, 0.0]], dtype=np.float64)
    reference_cells = np.array([7, 7, 8], dtype=np.int64)
    focal_xy = np.array([[0.0, 0.0]], dtype=np.float64)
    within_d, _ = nearest_reference(focal_xy, references)
    outside_d, _ = nearest_reference(
        focal_xy,
        references,
        reference_cell=reference_cells,
        excluded_cell=np.array([7]),
        reference_ids=np.array([10, 11, 12]),
    )
    assert within_d[0] == 0.0
    assert outside_d[0] == 3.0
    no_external, _ = nearest_reference(
        focal_xy,
        references[:2],
        reference_cell=reference_cells[:2],
        excluded_cell=np.array([7]),
    )
    assert np.isnan(no_external[0])

    t = week_ordinal(2025, 1)
    history_ordinals = np.array([t - 2, t - 1, t, t + 1], dtype=np.int64)
    eligible = history_ordinals[history_ordinals < t]
    assert eligible.tolist() == [t - 2, t - 1]
    assert ordinal_label(t) == "2025-W01"
    assert abs(wgs84_geodesic_km(0.0, 0.0, 1.0, 0.0) - 111.3194908) < 1e-5
    tiny_distances = pd.DataFrame(
        {
            "week": [ordinal_label(t), ordinal_label(t)],
            "week_ord": [t, t],
            "lag_weeks": [0, 1],
            "distance_km": [5.0, 6.0],
        }
    )
    tiny_weekly, tiny_lags = summarize_weeks(tiny_distances, {t: 1}, LAGS)
    assert tiny_weekly.loc[0, "median_km"] == 5.0
    assert tiny_lags.loc[tiny_lags["lag_weeks"] == 1, "median_km"].iloc[0] == 6.0

    singleton_point = pd.DataFrame(
        {
            "primary_period": [True],
            "in_fitted_domain": [True],
            "x_km": [0.0],
            "y_km": [0.0],
            "point_id": [101],
            "model_node_id": [3],
            "region": ["Mexico"],
            "distance_to_cell_boundary_km": [1.0],
            "point_to_cell_centroid_km": [2.0],
            "week": [ordinal_label(t)],
            "week_ord": [t],
        }
    )
    singleton_node = pd.DataFrame({"model_node_id": [3], "x": [2.0], "y": [0.0]})
    singleton_pairs, singleton_summary = between_cell_analysis(singleton_point, singleton_node)
    assert not singleton_pairs.loc[0, "same_cell_neighbor"]
    assert not singleton_pairs.loc[0, "cross_cell_neighbor"]
    assert singleton_summary.loc[0, "n_cross_cell_nearest_pairs"] == 0

    affine = Affine(25.0, 0.0, 0.0, 0.0, -25.0, 50.0)
    rows, columns = rowcol(affine, [10.0, 35.0, 80.0], [40.0, 40.0, 40.0])
    crosswalk = {(1, 1): 12, (1, 2): 13}
    assigned = [
        crosswalk.get((int(row) + 1, int(column) + 1), -1)
        for row, column in zip(rows, columns)
    ]
    assert assigned == [12, 13, -1]

    return {
        "status": "PASS",
        "checks": [
            "projected Euclidean 3-4-5 distance is in kilometers",
            "streamed spatial-tree pair counts use strict distance thresholds",
            "self-record exclusion preserves distinct co-located records",
            "exact historical eligibility excludes target and future weeks",
            "lag summaries use the recorded lag_weeks field",
            "focal-cell exclusion selects the nearest outside-cell point",
            "missing outside-cell history remains undefined",
            "WGS84 geodesic diagnostic matches the equatorial one-degree reference",
            "existing affine row/column crosswalk assigns only listed model cells",
            "a week-region with one observation has no defined cross-cell neighbour",
        ],
    }


def load_and_prepare(output_root: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, np.ndarray, dict, dict]:
    if not SOURCE_PATH.is_file():
        raise FileNotFoundError(f"Authoritative observation source is missing: {SOURCE_PATH}")
    source_hash = sha256_file(SOURCE_PATH)
    if source_hash != EXPECTED_SOURCE_SHA256:
        raise RuntimeError(
            "Observation source SHA-256 differs from the accepted W44 source; "
            f"expected {EXPECTED_SOURCE_SHA256}, observed {source_hash}"
        )

    response_root = CANDIDATE_ROOT / "revised_model_data"
    nodes_path = response_root / "raw" / "nodes.parquet"
    weeks_path = response_root / "raw" / "weeks.parquet"
    counts_path = response_root / "raw" / "targets_count.npy"
    front_path = CANDIDATE_ROOT / "front_features" / "causal_front_features.parquet"
    for path in (GRID_PATH, nodes_path, weeks_path, counts_path, front_path):
        if not path.is_file():
            raise FileNotFoundError(f"Required existing A3 input is missing: {path}")

    hashes = {
        "analysis_script": sha256_file(Path(__file__)),
        "observation_source": source_hash,
        "canonical_grid_geometry": sha256_file(GRID_PATH),
        "a3_node_crosswalk": sha256_file(nodes_path),
        "a3_response_weeks": sha256_file(weeks_path),
        "a3_response_counts": sha256_file(counts_path),
        "a3_history_predictors": sha256_file(front_path),
    }

    raw = pd.read_csv(
        SOURCE_PATH,
        dtype={"date": "string", "lon": "string", "lat": "string", "host": "string"},
        usecols=["date", "lon", "lat", "host"],
    )
    if len(raw) != 164767 or set(raw.columns) != {"date", "lon", "lat", "host"}:
        raise RuntimeError(
            f"Unexpected corrected observation source schema or row count: {len(raw)} rows, {list(raw.columns)}"
        )
    raw["point_id"] = np.arange(len(raw), dtype=np.int64)
    raw["date"] = pd.to_datetime(raw["date"], format="%Y-%m-%d", errors="raise")
    raw["lon_deg"] = pd.to_numeric(raw["lon"], errors="raise").astype(np.float64)
    raw["lat_deg"] = pd.to_numeric(raw["lat"], errors="raise").astype(np.float64)
    iso = raw["date"].dt.isocalendar()
    raw["week"] = iso["year"].astype(str).str.zfill(4) + "-W" + iso["week"].astype(str).str.zfill(2)
    raw["week_ord"] = [
        week_ordinal(int(year), int(week))
        for year, week in zip(iso["year"].to_numpy(), iso["week"].to_numpy())
    ]
    end_ord = week_ordinal(*week_parts(PRIMARY_END))
    points = raw.loc[raw["week_ord"] <= end_ord].copy()
    if points["week"].max() != PRIMARY_END:
        raise RuntimeError(f"Accepted observation cutoff did not end at {PRIMARY_END}")
    location_lookup: dict[tuple[str, str], int] = {}
    location_ids = np.empty(len(points), dtype=np.int64)
    for i, (lon_text, lat_text) in enumerate(zip(points["lon"].tolist(), points["lat"].tolist())):
        key = (canonical_decimal(str(lon_text)), canonical_decimal(str(lat_text)))
        location_ids[i] = location_lookup.setdefault(key, len(location_lookup))
    points["location_id"] = location_ids

    nodes = pd.read_parquet(nodes_path).sort_values("model_node_id").reset_index(drop=True)
    weeks = pd.read_parquet(weeks_path).sort_values("week_index").reset_index(drop=True)
    target_counts = np.load(counts_path, mmap_mode="r")
    front_columns = [
        "week",
        "week_index",
        "model_node_id",
        "distance_to_any_prior_positive_km",
        "distance_to_prev4_positive_km",
        "weeks_since_detection_within_50km",
        "distance_to_any_prior_positive_log1p",
        "distance_to_prev4_positive_log1p",
        "weeks_since_detection_within_50km_log1p",
        "any_prior_positive_available",
        "prev4_positive_available",
        "detection_within_50km_ever_available",
    ]
    front = pd.read_parquet(front_path, columns=front_columns)
    if nodes["model_node_id"].tolist() != list(range(len(nodes))):
        raise RuntimeError("Existing A3 node crosswalk is not ordered 0..N-1")
    if len(nodes) != 10037 or len(weeks) != 96 or target_counts.shape != (96, 10037):
        raise RuntimeError(
            f"Unexpected frozen W44 response geometry: nodes={len(nodes)}, weeks={len(weeks)}, "
            f"target_shape={target_counts.shape}"
        )
    if weeks["iso_week"].iloc[0] != PRIMARY_START or weeks["iso_week"].iloc[-1] != PRIMARY_END:
        raise RuntimeError("Existing W44 response week table does not match the required primary period")
    if len(front) != len(nodes) * len(weeks):
        raise RuntimeError("Existing causal A3 history feature table is not a complete cell-week panel")

    with rasterio.open(GRID_PATH) as dataset:
        grid = {
            "width": dataset.width,
            "height": dataset.height,
            "transform": dataset.transform,
            "crs_wkt": dataset.crs.to_wkt(),
            "crs_text": str(dataset.crs),
            "nodata": dataset.nodata,
            "mask_valid_cell_count": int(np.count_nonzero(dataset.read(1) != dataset.nodata)),
            "resolution_km": [float(dataset.transform.a), float(abs(dataset.transform.e))],
        }

    a, b, c, d, e, f = tuple(grid["transform"])[:6]
    if abs(b) > 1e-12 or abs(d) > 1e-12 or a <= 0 or e >= 0:
        raise RuntimeError("The existing A3 raster affine is not the expected north-up grid")
    wkt_unit = "kilometre" if 'UNIT["kilometre",1000' in grid["crs_wkt"].replace(" ", "") else None
    if wkt_unit is None:
        compact_wkt = grid["crs_wkt"].replace(" ", "").lower()
        if 'unit["kilometre",1000' not in compact_wkt and 'unit["kilometer",1000' not in compact_wkt:
            raise RuntimeError("The existing A3 grid WKT does not declare kilometre coordinate units")
    grid["distance_units"] = "kilometres"
    grid["projection_name"] = "WGS84 Albers Conic Equal Area"

    expected_cells = (nodes["row"].to_numpy() - 1) * grid["width"] + nodes["column"].to_numpy()
    if not np.array_equal(expected_cells.astype(np.int64), nodes["raster_cell"].to_numpy(dtype=np.int64)):
        raise RuntimeError("A3 node raster_cell values do not match the stored row/column crosswalk")
    if (
        nodes["row"].min() < 1
        or nodes["row"].max() > grid["height"]
        or nodes["column"].min() < 1
        or nodes["column"].max() > grid["width"]
    ):
        raise RuntimeError("A3 node row/column crosswalk lies outside the canonical grid geometry")
    cell_x = c + a * (nodes["column"].to_numpy(dtype=np.float64) - 0.5)
    cell_y = f + e * (nodes["row"].to_numpy(dtype=np.float64) - 0.5)
    center_error = np.hypot(cell_x - nodes["x"].to_numpy(), cell_y - nodes["y"].to_numpy())
    if float(center_error.max()) > 1e-6:
        raise RuntimeError(
            "Stored A3 node coordinates do not match the existing grid affine; "
            f"maximum center residual is {center_error.max():.9g} km"
        )

    grid_lookup = {
        (int(row), int(column)): int(node_id)
        for row, column, node_id in zip(nodes["row"], nodes["column"], nodes["model_node_id"])
    }
    x, y = transform_coordinates(
        WGS84_WKT,
        grid["crs_wkt"],
        points["lon_deg"].to_numpy(dtype=np.float64).tolist(),
        points["lat_deg"].to_numpy(dtype=np.float64).tolist(),
    )
    points["x_km"] = np.asarray(x, dtype=np.float64)
    points["y_km"] = np.asarray(y, dtype=np.float64)
    row_indices, column_indices = rowcol(
        grid["transform"], points["x_km"].to_numpy(), points["y_km"].to_numpy()
    )
    row_indices = np.asarray(row_indices, dtype=np.int64)
    column_indices = np.asarray(column_indices, dtype=np.int64)
    inside_raster = (
        (row_indices >= 0)
        & (row_indices < grid["height"])
        & (column_indices >= 0)
        & (column_indices < grid["width"])
    )
    model_node_ids = np.full(len(points), -1, dtype=np.int64)
    for i in np.flatnonzero(inside_raster):
        model_node_ids[i] = grid_lookup.get(
            (int(row_indices[i] + 1), int(column_indices[i] + 1)), -1
        )
    points["raster_row"] = row_indices + 1
    points["raster_column"] = column_indices + 1
    points["model_node_id"] = model_node_ids
    points["in_fitted_domain"] = model_node_ids >= 0

    region_by_node = nodes["country_or_domain_region"].astype(str).to_numpy()
    region = np.full(len(points), "outside_fitted_domain", dtype=object)
    assigned = model_node_ids >= 0
    region[assigned] = region_by_node[model_node_ids[assigned]]
    points["region"] = region
    node_x = nodes["x"].to_numpy(dtype=np.float64)
    node_y = nodes["y"].to_numpy(dtype=np.float64)
    own_x = np.full(len(points), np.nan, dtype=np.float64)
    own_y = np.full(len(points), np.nan, dtype=np.float64)
    own_x[assigned] = node_x[model_node_ids[assigned]]
    own_y[assigned] = node_y[model_node_ids[assigned]]
    points["point_to_cell_centroid_km"] = np.hypot(points["x_km"] - own_x, points["y_km"] - own_y)
    points["point_to_cell_footprint_km"] = np.where(assigned, 0.0, np.nan)

    x_left = c + a * column_indices
    x_right = x_left + a
    y_top = f + e * row_indices
    y_bottom = y_top + e
    boundary = np.full(len(points), np.nan, dtype=np.float64)
    boundary[assigned] = np.minimum.reduce(
        [
            points.loc[assigned, "x_km"].to_numpy() - x_left[assigned],
            x_right[assigned] - points.loc[assigned, "x_km"].to_numpy(),
            points.loc[assigned, "y_km"].to_numpy() - y_bottom[assigned],
            y_top[assigned] - points.loc[assigned, "y_km"].to_numpy(),
        ]
    )
    boundary[assigned] = np.maximum(boundary[assigned], 0.0)
    points["distance_to_cell_boundary_km"] = boundary

    node_lon = nodes["lon"].to_numpy(dtype=np.float64)
    node_lat = nodes["lat"].to_numpy(dtype=np.float64)
    projected_node_x, projected_node_y = transform_coordinates(
        WGS84_WKT, grid["crs_wkt"], node_lon.tolist(), node_lat.tolist()
    )
    centroid_transform_error = np.hypot(
        np.asarray(projected_node_x) - node_x,
        np.asarray(projected_node_y) - node_y,
    )
    if float(centroid_transform_error.max()) > 0.02:
        raise RuntimeError(
            "WGS84-to-A3 projection check exceeds 20 m for stored cell centroids; "
            f"maximum residual={centroid_transform_error.max():.6g} km"
        )
    grid["centroid_transform_residual_m"] = {
        "median": float(np.median(centroid_transform_error) * 1000.0),
        "p95": float(np.quantile(centroid_transform_error, 0.95) * 1000.0),
        "maximum": float(np.max(centroid_transform_error) * 1000.0),
    }

    primary_start_ord = week_ordinal(*week_parts(PRIMARY_START))
    points["primary_period"] = (
        (points["week_ord"] >= primary_start_ord) & (points["week_ord"] <= end_ord)
    )
    points["history_cutoff_eligible"] = points["week_ord"] <= end_ord

    return points, nodes, weeks, np.asarray(target_counts), grid, {
        "paths": {
            "observation_source": str(SOURCE_PATH),
            "grid_geometry": str(GRID_PATH),
            "a3_nodes": str(nodes_path),
            "a3_week_table": str(weeks_path),
            "a3_response_counts": str(counts_path),
            "a3_history_features": str(front_path),
        },
        "sha256": hashes,
        "source_row_count": int(len(raw)),
        "rows_through_w44": int(len(points)),
        "latest_included_week": str(points["week"].max()),
        "primary_period_rows": int(points["primary_period"].sum()),
        "history_first_week": str(points["week"].min()),
        "source_columns": ["date", "lon", "lat", "host"],
    }


def build_response_audit(
    points: pd.DataFrame, nodes: pd.DataFrame, weeks: pd.DataFrame, target_counts: np.ndarray
) -> tuple[pd.DataFrame, dict[str, object]]:
    week_labels = weeks["iso_week"].astype(str).tolist()
    week_position = {label: index for index, label in enumerate(week_labels)}
    node_count = len(nodes)
    derived = np.zeros((len(weeks), node_count), dtype=np.int64)
    in_domain = points.loc[
        points["primary_period"] & points["in_fitted_domain"],
        ["week", "model_node_id"],
    ]
    week_codes = in_domain["week"].map(week_position)
    if week_codes.isna().any():
        raise RuntimeError("Some in-domain primary observations lack an A3 target week")
    np.add.at(
        derived,
        (week_codes.to_numpy(dtype=np.int64), in_domain["model_node_id"].to_numpy(dtype=np.int64)),
        1,
    )
    expected = np.asarray(target_counts, dtype=np.int64)
    mismatch = derived != expected
    mismatch_count = int(mismatch.sum())
    abs_error = np.abs(derived - expected)
    audit = {
        "status": "PASS" if mismatch_count == 0 else "FAIL",
        "target_week_count": int(len(weeks)),
        "node_count": int(node_count),
        "mismatched_cell_weeks": mismatch_count,
        "absolute_count_difference_sum": int(abs_error.sum()),
        "maximum_cell_week_count_difference": int(abs_error.max()),
        "source_assigned_point_count": int(derived.sum()),
        "existing_response_count_sum": int(expected.sum()),
    }
    if mismatch_count:
        raise RuntimeError(
            "Point-to-cell assignments do not reproduce the existing W44 A3 response counts: "
            f"{audit}"
        )
    return pd.DataFrame(
        {
            "week": np.repeat(week_labels, node_count),
            "week_index": np.repeat(weeks["week_index"].to_numpy(), node_count),
            "model_node_id": np.tile(np.arange(node_count, dtype=np.int64), len(weeks)),
            "count": expected.reshape(-1),
        }
    ), audit


def summarize_group(values: np.ndarray) -> dict[str, object]:
    summary = summarize_distances(values, len(values))
    return summary


def focused_check(
    points: pd.DataFrame,
    nodes: pd.DataFrame,
    weeks: pd.DataFrame,
    target_counts: np.ndarray,
    grid: dict,
) -> tuple[dict[str, object], pd.DataFrame, dict[str, object]]:
    synthetic = run_synthetic_checks()
    response_panel, response_audit = build_response_audit(points, nodes, weeks, target_counts)
    primary = points.loc[points["primary_period"]].copy()
    if primary["week"].nunique() != 96:
        raise RuntimeError("Primary observation subset does not contain all 96 W44 target weeks")
    sample = primary.groupby(["week", "region"], sort=True, group_keys=False).head(20)
    sample_nn: list[dict[str, object]] = []
    for (week, region), group in sample.groupby(["week", "region"], sort=True):
        if len(group) < 2:
            continue
        d, ix = nearest_self_excluding(group[["x_km", "y_km"]].to_numpy(dtype=np.float64))
        sample_nn.append(
            {
                "week": str(week),
                "region": str(region),
                "sample_n": int(len(group)),
                "n_defined": int(np.isfinite(d).sum()),
                "minimum_km": float(np.nanmin(d)),
                "maximum_km": float(np.nanmax(d)),
            }
        )
        assert np.all(ix[np.isfinite(d)] >= 0)
    if not sample_nn:
        raise RuntimeError("Focused W44 sample contains no eligible same-week neighbor groups")
    early_weeks = sorted(primary["week_ord"].unique())[:3]
    lag_check_count = 0
    for target_ord in early_weeks:
        focal = primary.loc[primary["week_ord"] == target_ord]
        reference_ord = target_ord - 1
        reference = points.loc[points["week_ord"] == reference_ord]
        if len(focal) and len(reference):
            d, ix = nearest_reference(
                focal[["x_km", "y_km"]].to_numpy(dtype=np.float64),
                reference[["x_km", "y_km"]].to_numpy(dtype=np.float64),
                reference_ids=reference["point_id"].to_numpy(dtype=np.int64),
            )
            assert np.isfinite(d).all()
            assert np.isin(ix, reference["point_id"].to_numpy()).all()
            assert reference["week_ord"].max() == reference_ord < target_ord
            lag_check_count += len(focal)
    if lag_check_count == 0:
        raise RuntimeError("Focused exact-lag sample did not validate any eligible historical references")
    region_map = dict(
        zip(nodes["model_node_id"].astype(int), nodes["country_or_domain_region"].astype(str))
    )
    assert set(region_map.values()).issubset({"Mexico", "U.S.-to-40N"})
    assigned = points.loc[points["in_fitted_domain"]]
    if not len(assigned) or not np.isfinite(assigned["point_to_cell_centroid_km"]).all():
        raise RuntimeError("Focused point-to-cell centroid or footprint assignment failed")
    check = {
        "status": "PASS",
        "synthetic_checks": synthetic,
        "coordinate_units": grid["distance_units"],
        "projection": grid["projection_name"],
        "node_affine_crosswalk": {
            "status": "PASS",
            "node_count": int(len(nodes)),
            "max_cell_center_residual_km": float(
                np.hypot(
                    grid["transform"].c
                    + grid["transform"].a * (nodes["column"].to_numpy(dtype=float) - 0.5)
                    - nodes["x"].to_numpy(dtype=float),
                    grid["transform"].f
                    + grid["transform"].e * (nodes["row"].to_numpy(dtype=float) - 0.5)
                    - nodes["y"].to_numpy(dtype=float),
                ).max()
            ),
        },
        "centroid_projection_residual_m": grid["centroid_transform_residual_m"],
        "source_point_assignment": {
            "status": "PASS",
            "in_domain_rows_through_w44": int(points["in_fitted_domain"].sum()),
            "outside_domain_rows_through_w44": int((~points["in_fitted_domain"]).sum()),
            "primary_sample_rows": int(len(sample)),
            "sample_region_week_groups_with_neighbors": int(len(sample_nn)),
        },
        "same_week_self_exclusion": {
            "status": "PASS",
            "sample_groups": sample_nn,
        },
        "exact_one_week_lag": {
            "status": "PASS",
            "focal_observations_checked": int(lag_check_count),
            "reference_week_rule": "week_ord(target) - 1; reference points strictly before target week",
        },
        "focal_cell_exclusion": {
            "status": "PASS",
            "synthetic_nearest_outside_cell_km": 3.0,
            "empty_outside_history": "undefined",
        },
        "response_reproduction": response_audit,
    }
    return check, response_panel, region_map


def summarize_weeks(
    distances: pd.DataFrame, point_counts: dict[int, int], lags: tuple[int, ...]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    weekly_rows: list[dict[str, object]] = []
    lag_rows: list[dict[str, object]] = []
    for week_ord in sorted(point_counts):
        week_label = ordinal_label(week_ord)
        part = distances.loc[
            (distances["week_ord"] == week_ord) & (distances["lag_weeks"] == 0)
        ]
        row: dict[str, object] = {"week": week_label, "week_ord": int(week_ord), "n_observations": int(point_counts[week_ord])}
        row.update(summarize_distances(part["distance_km"].to_numpy(), int(point_counts[week_ord])))
        weekly_rows.append(row)
    for lag in lags:
        part = distances.loc[distances["lag_weeks"] == lag]
        row = {"lag_weeks": int(lag), "lag_label": "same_week" if lag == 0 else f"{lag}_week_earlier"}
        row.update(summarize_distances(part["distance_km"].to_numpy(), len(part)))
        lag_rows.append(row)
    return pd.DataFrame(weekly_rows), pd.DataFrame(lag_rows)


def run_point_temporal_analysis(
    points: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    primary = points.loc[points["primary_period"]].copy()
    by_week = {int(key): group for key, group in points.groupby("week_ord", sort=True)}
    records: list[pd.DataFrame] = []
    for target_ord, focal in primary.groupby("week_ord", sort=True):
        target_ord = int(target_ord)
        focal = focal.reset_index(drop=True)
        focal_xy = focal[["x_km", "y_km"]].to_numpy(dtype=np.float64)
        for lag in LAGS:
            reference = by_week.get(target_ord - lag)
            if reference is None or len(reference) == 0:
                d = np.full(len(focal), np.nan)
                ix = np.full(len(focal), -1, dtype=np.int64)
            elif lag == 0:
                d, local_ix = nearest_self_excluding(focal_xy)
                ix = np.full(len(focal), -1, dtype=np.int64)
                valid = local_ix >= 0
                ix[valid] = focal["point_id"].to_numpy(dtype=np.int64)[local_ix[valid]]
            else:
                d, ix = nearest_reference(
                    focal_xy,
                    reference[["x_km", "y_km"]].to_numpy(dtype=np.float64),
                    reference_ids=reference["point_id"].to_numpy(dtype=np.int64),
                    workers=1,
                )
            valid = ix >= 0
            if valid.any():
                ref_rows = reference.set_index("point_id").reindex(ix[valid])
                neighbor_cell = np.full(len(focal), -1, dtype=np.int64)
                neighbor_region = np.full(len(focal), "undefined", dtype=object)
                neighbor_cell[valid] = ref_rows["model_node_id"].fillna(-1).to_numpy(dtype=np.int64)
                neighbor_region[valid] = ref_rows["region"].astype(str).to_numpy()
            else:
                neighbor_cell = np.full(len(focal), -1, dtype=np.int64)
                neighbor_region = np.full(len(focal), "undefined", dtype=object)
            records.append(
                pd.DataFrame(
                    {
                        "point_id": focal["point_id"].to_numpy(dtype=np.int64),
                        "week": focal["week"].astype(str).to_numpy(),
                        "week_ord": target_ord,
                        "lag_weeks": lag,
                        "reference_week": ordinal_label(target_ord - lag),
                        "distance_km": d,
                        "neighbor_point_id": np.where(valid, ix, -1),
                        "focal_model_node_id": focal["model_node_id"].to_numpy(dtype=np.int64),
                        "neighbor_model_node_id": neighbor_cell,
                        "focal_region": focal["region"].astype(str).to_numpy(),
                        "neighbor_region": neighbor_region,
                    }
                )
            )
    point_distances = pd.concat(records, ignore_index=True)
    count_by_week = primary.groupby("week_ord").size().to_dict()
    weekly, overall_lag = summarize_weeks(point_distances, count_by_week, LAGS)

    regional_rows: list[dict[str, object]] = []
    region_weekly_rows: list[dict[str, object]] = []
    included_regions = ["Mexico", "U.S.-to-40N"]
    primary_regional = primary.loc[primary["region"].isin(included_regions)]
    all_by_week_region = {
        (int(week_ord), str(region)): group
        for (week_ord, region), group in points.loc[points["region"].isin(included_regions)].groupby(
            ["week_ord", "region"], sort=True
        )
    }
    for (target_ord, region), focal in primary_regional.groupby(["week_ord", "region"], sort=True):
        target_ord = int(target_ord)
        region = str(region)
        focal = focal.reset_index(drop=True)
        q = focal[["x_km", "y_km"]].to_numpy(dtype=np.float64)
        for lag in LAGS:
            ref = all_by_week_region.get((target_ord - lag, region))
            if ref is None or len(ref) == 0:
                d = np.full(len(focal), np.nan)
            elif lag == 0:
                d, _ = nearest_self_excluding(q)
            else:
                d, _ = nearest_reference(q, ref[["x_km", "y_km"]].to_numpy(dtype=np.float64))
            row = {
                "week": ordinal_label(target_ord),
                "week_ord": target_ord,
                "region": region,
                "lag_weeks": lag,
                "lag_label": "same_week" if lag == 0 else f"{lag}_week_earlier",
            }
            row.update(summarize_distances(d, len(focal)))
            regional_rows.append(row)
            if lag == 0:
                region_weekly_rows.append(
                    {
                        "week": ordinal_label(target_ord),
                        "week_ord": target_ord,
                        "region": region,
                        "n_observations": int(len(focal)),
                        **summarize_distances(d, len(focal)),
                    }
                )
    return point_distances, weekly, overall_lag, pd.DataFrame(region_weekly_rows), pd.DataFrame(regional_rows)


def point_cell_week_counts(points: pd.DataFrame) -> pd.DataFrame:
    rows = points.loc[
        points["primary_period"] & points["in_fitted_domain"],
        ["week", "week_ord", "model_node_id", "region", "point_id"],
    ]
    return (
        rows.groupby(["week", "week_ord", "model_node_id", "region"], sort=True)
        .size()
        .rename("n_observations")
        .reset_index()
    )


def within_cell_analysis(
    points: pd.DataFrame, cell_week_counts: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    primary_in = points.loc[
        points["primary_period"] & points["in_fitted_domain"]
    ].copy()
    cell_rows: list[dict[str, object]] = []
    point_rows: list[pd.DataFrame] = []
    for (week, node_id), group in primary_in.groupby(["week", "model_node_id"], sort=True):
        if len(group) < 2:
            continue
        xy = group[["x_km", "y_km"]].to_numpy(dtype=np.float64)
        nearest_d, _ = nearest_self_excluding(xy)
        tree = cKDTree(xy)
        n_pairs = len(xy) * (len(xy) - 1) // 2
        row = {
            "week": str(week),
            "week_ord": int(group["week_ord"].iloc[0]),
            "model_node_id": int(node_id),
            "region": str(group["region"].iloc[0]),
            "n_observations": int(len(group)),
            "n_point_pairs": int(n_pairs),
            "nearest_neighbor_median_km": float(np.median(nearest_d)),
            "nearest_neighbor_mean_km": float(np.mean(nearest_d)),
        }
        for threshold in (5.0, 10.0, 25.0):
            # count_neighbors counts ordered pairs and self-pairs. Subtract the
            # diagonal and halve to recover unique pairs without materializing
            # the potentially quadratic pair-distance vector.
            strict_radius = np.nextafter(float(threshold), -np.inf)
            ordered_with_self = tree.count_neighbors(tree, strict_radius, cumulative=True)
            n_within = int((ordered_with_self - len(xy)) // 2)
            row[f"pairs_within_{threshold:g}km"] = n_within
            row[f"proportion_pairs_within_{threshold:g}km"] = float(n_within / n_pairs)
        cell_rows.append(row)
        point_rows.append(
            pd.DataFrame(
                {
                    "point_id": group["point_id"].to_numpy(dtype=np.int64),
                    "week": str(week),
                    "model_node_id": int(node_id),
                    "region": str(group["region"].iloc[0]),
                    "within_cell_nearest_neighbor_km": nearest_d,
                }
            )
        )
    cell_metrics = pd.DataFrame(cell_rows)
    point_nn = pd.concat(point_rows, ignore_index=True) if point_rows else pd.DataFrame()

    dist_rows: list[dict[str, object]] = []
    for group_name, group in cell_week_counts.groupby(["week", "region"], sort=True):
        week, region = str(group_name[0]), str(group_name[1])
        primary_week = primary_in.loc[
            (primary_in["week"] == week) & (primary_in["region"] == region)
        ]
        counts = group["n_observations"].to_numpy(dtype=np.int64)
        multi_obs = int(group.loc[group["n_observations"] >= 2, "n_observations"].sum())
        row = {
            "week": week,
            "region": region,
            "n_occupied_cell_weeks": int(len(group)),
            "n_multi_detection_cell_weeks": int(np.sum(counts >= 2)),
            "proportion_occupied_cell_weeks_multi": float(np.mean(counts >= 2)),
            "n_in_domain_observations": int(len(primary_week)),
            "n_observations_in_multi_cell_weeks": multi_obs,
            "proportion_observations_in_multi_cell_weeks": (
                float(multi_obs / len(primary_week)) if len(primary_week) else np.nan
            ),
            "mean_detections_per_occupied_cell_week": float(counts.mean()),
            "median_detections_per_occupied_cell_week": float(np.median(counts)),
            "p90_detections_per_occupied_cell_week": float(np.quantile(counts, 0.90)),
            "maximum_detections_per_occupied_cell_week": int(counts.max()),
            "n_cell_weeks_with_within_cell_distances": int(np.sum(counts >= 2)),
        }
        for n in (1, 2, 3, 4, 5, 10):
            row[f"occupied_cell_weeks_with_{n}_detections"] = int(np.sum(counts == n))
        row["occupied_cell_weeks_with_6plus_detections"] = int(np.sum(counts >= 6))
        dist_rows.append(row)

    within_rows: list[dict[str, object]] = []
    if len(point_nn):
        for (week, region), group in point_nn.groupby(["week", "region"], sort=True):
            within_rows.append(
                {
                    "week": str(week),
                    "region": str(region),
                    "n_cell_weeks": int(cell_metrics.loc[
                        (cell_metrics["week"] == week) & (cell_metrics["region"] == region)
                    ].shape[0]),
                    "n_observations": int(len(group)),
                    **summarize_distances(
                        group["within_cell_nearest_neighbor_km"].to_numpy(), len(group)
                    ),
                }
            )
    return cell_metrics, point_nn, pd.DataFrame(dist_rows), pd.DataFrame(within_rows)


def bounded_short_pairs(points: pd.DataFrame) -> pd.DataFrame:
    primary = points.loc[
        points["primary_period"] & points["in_fitted_domain"]
    ]
    records: list[dict[str, object]] = []
    thresholds = (5.0, 10.0, 25.0)
    for (week_ord, region), group in primary.groupby(["week_ord", "region"], sort=True):
        xy = group[["x_km", "y_km"]].to_numpy(dtype=np.float64)
        if len(xy) < 2:
            pairs = np.empty((0, 2), dtype=np.int64)
            pair_d = np.empty(0, dtype=np.float64)
        else:
            tree = cKDTree(xy)
            pairs = tree.query_pairs(r=25.0, output_type="ndarray")
            if pairs.size:
                delta = xy[pairs[:, 0]] - xy[pairs[:, 1]]
                pair_d = np.hypot(delta[:, 0], delta[:, 1])
                strictly_under = pair_d < 25.0
                pairs, pair_d = pairs[strictly_under], pair_d[strictly_under]
            else:
                pair_d = np.empty(0, dtype=np.float64)
        cells = group["model_node_id"].to_numpy(dtype=np.int64)
        same_cell = cells[pairs[:, 0]] == cells[pairs[:, 1]] if len(pairs) else np.zeros(0, dtype=bool)
        for threshold in thresholds:
            selected = pair_d < threshold
            n = int(selected.sum())
            same = int(np.sum(same_cell[selected]))
            different = n - same
            records.append(
                {
                    "week": ordinal_label(int(week_ord)),
                    "week_ord": int(week_ord),
                    "region": str(region),
                    "threshold_km": threshold,
                    "short_point_pairs": n,
                    "within_same_cell_pairs": same,
                    "across_cell_boundary_pairs": different,
                    "fraction_within_same_cell": float(same / n) if n else np.nan,
                    "fraction_across_cell_boundary": float(different / n) if n else np.nan,
                }
            )
    return pd.DataFrame(records)


def between_cell_analysis(
    points: pd.DataFrame, nodes: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    primary = points.loc[
        points["primary_period"] & points["in_fitted_domain"]
    ]
    nearest_rows: list[pd.DataFrame] = []
    node_xy = nodes.set_index("model_node_id")[["x", "y"]].rename(
        columns={"x": "x_km", "y": "y_km"}
    )
    for (week, week_ord, _region), group in primary.groupby(
        ["week", "week_ord", "region"], sort=True
    ):
        group = group.reset_index(drop=True)
        d, ix = nearest_self_excluding(group[["x_km", "y_km"]].to_numpy(dtype=np.float64))
        valid = ix >= 0
        neighbor_cells = np.full(len(group), -1, dtype=np.int64)
        neighbor_ids = np.full(len(group), -1, dtype=np.int64)
        neighbor_regions = np.full(len(group), "undefined", dtype=object)
        if valid.any():
            neighbor_cells[valid] = group["model_node_id"].to_numpy(dtype=np.int64)[ix[valid]]
            neighbor_ids[valid] = group["point_id"].to_numpy(dtype=np.int64)[ix[valid]]
            neighbor_regions[valid] = group["region"].astype(str).to_numpy()[ix[valid]]
        focal_cell = group["model_node_id"].to_numpy(dtype=np.int64)
        cell_x = node_xy.loc[focal_cell, "x_km"].to_numpy(dtype=np.float64)
        cell_y = node_xy.loc[focal_cell, "y_km"].to_numpy(dtype=np.float64)
        neighbor_cell_x = np.full(len(group), np.nan)
        neighbor_cell_y = np.full(len(group), np.nan)
        valid_cells = valid & (neighbor_cells >= 0)
        neighbor_cell_x[valid_cells] = node_xy.loc[
            neighbor_cells[valid_cells], "x_km"
        ].to_numpy(dtype=np.float64)
        neighbor_cell_y[valid_cells] = node_xy.loc[
            neighbor_cells[valid_cells], "y_km"
        ].to_numpy(dtype=np.float64)
        centroid_separation = np.hypot(cell_x - neighbor_cell_x, cell_y - neighbor_cell_y)
        point_d = d
        overstatement = centroid_separation - point_d
        same_cell = valid & (neighbor_cells == focal_cell)
        cross_cell = valid & (neighbor_cells != focal_cell)
        boundary = group["distance_to_cell_boundary_km"].to_numpy(dtype=np.float64)
        near = boundary <= BOUNDARY_BAND_KM
        data = pd.DataFrame(
            {
                "point_id": group["point_id"].to_numpy(dtype=np.int64),
                "week": str(week),
                "week_ord": int(week_ord),
                "focal_model_node_id": focal_cell,
                "neighbor_point_id": neighbor_ids,
                "neighbor_model_node_id": neighbor_cells,
                "focal_region": group["region"].astype(str).to_numpy(),
                "neighbor_region": neighbor_regions,
                "distance_to_cell_boundary_km": boundary,
                "point_to_own_centroid_km": group["point_to_cell_centroid_km"].to_numpy(),
                "point_to_point_nn_km": point_d,
                "same_cell_neighbor": same_cell,
                "cross_cell_neighbor": cross_cell,
                "centroid_to_centroid_km": centroid_separation,
                "centroid_overstatement_km": overstatement,
                "within_boundary_band": near,
            }
        )
        nearest_rows.append(data)
    nearest_pairs = pd.concat(nearest_rows, ignore_index=True)
    summary_rows: list[dict[str, object]] = []
    for (week, region), group in nearest_pairs.loc[nearest_pairs["within_boundary_band"]].groupby(
        ["week", "focal_region"], sort=True
    ):
        cross = group.loc[group["cross_cell_neighbor"]]
        delta = cross["centroid_overstatement_km"].to_numpy(dtype=np.float64)
        actual = cross["point_to_point_nn_km"].to_numpy(dtype=np.float64)
        represented = cross["centroid_to_centroid_km"].to_numpy(dtype=np.float64)
        finite = np.isfinite(delta) & np.isfinite(actual) & np.isfinite(represented)
        delta, actual, represented = delta[finite], actual[finite], represented[finite]
        row: dict[str, object] = {
            "week": str(week),
            "region": str(region),
            "boundary_band_km": BOUNDARY_BAND_KM,
            "n_near_boundary_observations": int(len(group)),
            "n_cross_cell_nearest_pairs": int(len(cross)),
            "n_within_cell_nearest_pairs": int(np.sum(group["same_cell_neighbor"])),
            "median_point_to_cell_centroid_km": float(
                group["point_to_own_centroid_km"].median()
            ),
            "median_cross_cell_point_distance_km": float(np.median(actual)) if len(actual) else np.nan,
            "median_cross_cell_centroid_distance_km": float(np.median(represented)) if len(represented) else np.nan,
            "median_centroid_overstatement_km": float(np.median(delta)) if len(delta) else np.nan,
            "p90_centroid_overstatement_km": float(np.quantile(delta, 0.90)) if len(delta) else np.nan,
            "proportion_centroid_overstates": float(np.mean(delta > 0.0)) if len(delta) else np.nan,
            "proportion_overstates_by_5km": float(np.mean(delta >= 5.0)) if len(delta) else np.nan,
            "proportion_overstates_by_10km": float(np.mean(delta >= 10.0)) if len(delta) else np.nan,
            "proportion_centroid_at_least_2x_point_distance": float(
                np.mean((represented >= 2.0 * actual) & (represented > 0.0))
            ) if len(delta) else np.nan,
        }
        summary_rows.append(row)
    return nearest_pairs, pd.DataFrame(summary_rows)


def add_history_features(
    points: pd.DataFrame,
    nodes: pd.DataFrame,
    weeks: pd.DataFrame,
    response_panel: pd.DataFrame,
    front_path: Path,
    *,
    workers: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    front = pd.read_parquet(
        front_path,
        columns=[
            "week",
            "week_index",
            "model_node_id",
            "distance_to_any_prior_positive_km",
            "distance_to_prev4_positive_km",
            "weeks_since_detection_within_50km",
            "distance_to_any_prior_positive_log1p",
            "distance_to_prev4_positive_log1p",
            "weeks_since_detection_within_50km_log1p",
            "any_prior_positive_available",
            "prev4_positive_available",
            "detection_within_50km_ever_available",
        ],
    )
    panel = response_panel.merge(
        nodes[["model_node_id", "country_or_domain_region", "x", "y"]],
        on="model_node_id",
        how="left",
        validate="many_to_one",
    ).rename(
        columns={
            "country_or_domain_region": "region",
            "x": "centroid_x_km",
            "y": "centroid_y_km",
        }
    )
    panel = panel.merge(
        front,
        on=["week", "week_index", "model_node_id"],
        how="left",
        validate="one_to_one",
    )
    panel["occurrence"] = (panel["count"] > 0).astype(np.int8)
    first_week_by_node = (
        points.loc[points["in_fitted_domain"]]
        .groupby("model_node_id")["week_ord"]
        .min()
    )
    week_ord_by_label = {str(w): week_ordinal(*week_parts(str(w))) for w in panel["week"].unique()}
    panel["week_ord"] = panel["week"].map(week_ord_by_label).astype(np.int64)
    first_ord = panel["model_node_id"].map(first_week_by_node).fillna(np.iinfo(np.int64).max)
    panel["previously_occupied"] = np.where(first_ord < panel["week_ord"], "previously_occupied", "previously_unoccupied")
    panel["history_cutoff_week"] = [ordinal_label(int(x) - 1) for x in panel["week_ord"]]

    point_by_week = {
        int(ord_value): group
        for ord_value, group in points.groupby("week_ord", sort=True)
    }
    centroid_xy = panel.drop_duplicates("model_node_id")[
        ["model_node_id", "centroid_x_km", "centroid_y_km"]
    ].sort_values("model_node_id")
    eval_xy = centroid_xy[["centroid_x_km", "centroid_y_km"]].to_numpy(dtype=np.float64)
    eval_cells = centroid_xy["model_node_id"].to_numpy(dtype=np.int64)
    output_features: list[pd.DataFrame] = []
    concentration_summaries: list[pd.DataFrame] = []

    for target_week, target_ord in zip(weeks["iso_week"].astype(str), weeks["week_index"].to_numpy()):
        target_week = str(target_week)
        target_ord = week_ordinal(*week_parts(target_week))
        focal_rows = panel.loc[panel["week"] == target_week].sort_values("model_node_id")
        if len(focal_rows) != len(nodes):
            raise RuntimeError(f"Incomplete W44 cell-week panel for {target_week}")
        feature_block = focal_rows[["week", "week_index", "week_ord", "model_node_id", "region"]].copy()
        feature_block["history_cutoff_week"] = ordinal_label(target_ord - 1)
        feature_block["lookback_start_week_prev1w"] = ordinal_label(target_ord - 1)
        for window in HISTORY_WINDOWS:
            ref_ord = np.arange(target_ord - window, target_ord, dtype=np.int64)
            reference = pd.concat(
                [point_by_week[o] for o in ref_ord if o in point_by_week],
                ignore_index=True,
            ) if any(o in point_by_week for o in ref_ord) else points.iloc[0:0]
            prefix = f"prev{window}w"
            feature_block[f"history_n_observations_{prefix}"] = int(len(reference))
            feature_block[f"history_available_{prefix}"] = int(len(reference) > 0)
            if len(reference):
                refs_xy = reference[["x_km", "y_km"]].to_numpy(dtype=np.float64)
                refs_id = reference["point_id"].to_numpy(dtype=np.int64)
                refs_cell = reference["model_node_id"].to_numpy(dtype=np.int64)
                d_any, _ = nearest_reference(
                    eval_xy, refs_xy, reference_ids=refs_id, workers=workers
                )
                d_outside, _ = nearest_reference(
                    eval_xy,
                    refs_xy,
                    reference_cell=refs_cell,
                    excluded_cell=eval_cells,
                    reference_ids=refs_id,
                    workers=workers,
                )
            else:
                d_any = np.full(len(eval_xy), np.nan)
                d_outside = np.full(len(eval_xy), np.nan)
            feature_block[f"nearest_history_point_any_{prefix}_km"] = d_any
            feature_block[f"nearest_history_point_outside_focal_cell_{prefix}_km"] = d_outside
            feature_block[f"lookback_start_week_{prefix}"] = ordinal_label(target_ord - window)

        history12_ord = np.arange(target_ord - 12, target_ord, dtype=np.int64)
        history12 = pd.concat(
            [point_by_week[o] for o in history12_ord if o in point_by_week],
            ignore_index=True,
        ) if any(o in point_by_week for o in history12_ord) else points.iloc[0:0]
        feature_block["history_n_observations_prev12w_concentration"] = int(len(history12))
        for radius in CONCENTRATION_RADII_KM:
            stem = f"prev12w_within_{radius:g}km"
            n_records = np.zeros(len(eval_xy), dtype=np.int64)
            n_locations = np.zeros(len(eval_xy), dtype=np.int64)
            n_cells = np.zeros(len(eval_xy), dtype=np.int64)
            if len(history12):
                hist_xy = history12[["x_km", "y_km"]].to_numpy(dtype=np.float64)
                hist_locs = history12["location_id"].to_numpy(dtype=np.int64)
                hist_cells = history12["model_node_id"].to_numpy(dtype=np.int64)
                tree = cKDTree(hist_xy)
                neighborhoods = tree.query_ball_point(
                    eval_xy, r=float(radius), workers=workers, return_sorted=True
                )
                for i, hit in enumerate(neighborhoods):
                    if not len(hit):
                        continue
                    delta = hist_xy[hit] - eval_xy[i]
                    dist_km = np.hypot(delta[:, 0], delta[:, 1])
                    selected = np.asarray(hit, dtype=np.int64)[dist_km <= radius]
                    if len(selected):
                        n_records[i] = len(selected)
                        n_locations[i] = np.unique(hist_locs[selected]).size
                        occupied = hist_cells[selected]
                        n_cells[i] = np.unique(occupied[occupied >= 0]).size
            feature_block[f"n_point_records_{stem}"] = n_records
            feature_block[f"n_distinct_locations_{stem}"] = n_locations
            feature_block[f"n_distinct_a3_cells_{stem}"] = n_cells

        output_features.append(feature_block)
    features = pd.concat(output_features, ignore_index=True)
    panel = panel.merge(
        features.drop(
            columns=["week_index", "week_ord", "region", "history_cutoff_week"],
            errors="ignore",
        ),
        on=["week", "model_node_id"],
        how="left",
        validate="one_to_one",
    )
    panel["history_cutoff_is_strictly_prior"] = [
        week_ordinal(*week_parts(str(cutoff))) < int(ord_value)
        for cutoff, ord_value in zip(panel["history_cutoff_week"], panel["week_ord"])
    ]
    if not panel["history_cutoff_is_strictly_prior"].all():
        raise RuntimeError("Historical feature cutoff includes the target week or future data")
    if panel.filter(regex=r"^nearest_history").isna().all(axis=None):
        raise RuntimeError("All centroid-to-history proximity features are missing")
    return panel, features


def feature_inventory(panel: pd.DataFrame) -> pd.DataFrame:
    feature_cols = [
        c
        for c in panel.columns
        if c.startswith("nearest_history_point_")
        or c.startswith("n_point_records_prev12w")
        or c.startswith("n_distinct_locations_prev12w")
        or c.startswith("n_distinct_a3_cells_prev12w")
    ]
    records: list[dict[str, object]] = []
    for name in feature_cols:
        values = pd.to_numeric(panel[name], errors="coerce").to_numpy(dtype=np.float64)
        finite = values[np.isfinite(values)]
        records.append(
            {
                "feature": name,
                "evaluation_location": "existing A3 model-cell centroid in A3 Albers CRS",
                "distance_units": "kilometres" if name.startswith("nearest_history") else "count",
                "historical_cutoff": "strictly before target ISO week",
                "lookback": "name-encoded fixed prior-week window",
                "n_cell_weeks": int(len(panel)),
                "n_defined": int(len(finite)),
                "n_missing": int(len(values) - len(finite)),
                "mean": float(np.mean(finite)) if len(finite) else np.nan,
                "sd": float(np.std(finite, ddof=1)) if len(finite) > 1 else np.nan,
                "p10": float(np.quantile(finite, 0.10)) if len(finite) else np.nan,
                "p25": float(np.quantile(finite, 0.25)) if len(finite) else np.nan,
                "median": float(np.median(finite)) if len(finite) else np.nan,
                "p75": float(np.quantile(finite, 0.75)) if len(finite) else np.nan,
                "p90": float(np.quantile(finite, 0.90)) if len(finite) else np.nan,
                "maximum": float(np.max(finite)) if len(finite) else np.nan,
            }
        )
    return pd.DataFrame(records)


def feature_group_summaries(panel: pd.DataFrame) -> pd.DataFrame:
    feature_cols = [
        c
        for c in panel.columns
        if c.startswith("nearest_history_point_")
        or c.startswith("n_point_records_prev12w")
        or c.startswith("n_distinct_locations_prev12w")
        or c.startswith("n_distinct_a3_cells_prev12w")
    ]
    long = panel[["week", "region", "model_node_id", *feature_cols]].melt(
        id_vars=["week", "region", "model_node_id"],
        var_name="feature",
        value_name="value",
    )
    long["year"] = long["week"].str.slice(0, 4)
    out: list[pd.DataFrame] = []
    for grouping, keys in (("region", ["region"]), ("year", ["year"]), ("week_region", ["week", "region"])):
        rows: list[dict[str, object]] = []
        for group_key, part in long.groupby([*keys, "feature"], sort=True, dropna=False):
            if not isinstance(group_key, tuple):
                group_key = (group_key,)
            values = pd.to_numeric(part["value"], errors="coerce").to_numpy(dtype=np.float64)
            finite = values[np.isfinite(values)]
            row = {"grouping": grouping, "feature": str(group_key[-1]), "n_cell_weeks": int(len(part)), "n_defined": int(len(finite))}
            for key, value in zip(keys, group_key[:-1]):
                row[key] = value
            row.update(
                {
                    "mean": float(np.mean(finite)) if len(finite) else np.nan,
                    "median": float(np.median(finite)) if len(finite) else np.nan,
                    "p90": float(np.quantile(finite, 0.90)) if len(finite) else np.nan,
                }
            )
            rows.append(row)
        out.append(pd.DataFrame(rows))
    return pd.concat(out, ignore_index=True)


def correlation_diagnostics(panel: pd.DataFrame) -> pd.DataFrame:
    new_features = [
        c
        for c in panel.columns
        if c.startswith("nearest_history_point_")
        or c.startswith("n_point_records_prev12w")
        or c.startswith("n_distinct_locations_prev12w")
        or c.startswith("n_distinct_a3_cells_prev12w")
    ]
    existing = [
        "distance_to_any_prior_positive_log1p",
        "distance_to_prev4_positive_log1p",
        "weeks_since_detection_within_50km_log1p",
        "any_prior_positive_available",
        "prev4_positive_available",
        "detection_within_50km_ever_available",
    ]
    groups: list[tuple[str, pd.Series]] = [("all", pd.Series(True, index=panel.index))]
    for region in sorted(panel["region"].dropna().astype(str).unique()):
        groups.append((f"region:{region}", panel["region"].astype(str) == region))
    for year in sorted(panel["week"].astype(str).str.slice(0, 4).unique()):
        groups.append((f"year:{year}", panel["week"].astype(str).str.startswith(year)))
    rows: list[dict[str, object]] = []
    for scope, mask in groups:
        subset = panel.loc[mask]
        for new in new_features:
            for old in existing:
                x = pd.to_numeric(subset[new], errors="coerce").to_numpy(dtype=np.float64)
                y = pd.to_numeric(subset[old], errors="coerce").to_numpy(dtype=np.float64)
                keep = np.isfinite(x) & np.isfinite(y)
                n = int(keep.sum())
                if n < 3 or np.nanstd(x[keep]) == 0 or np.nanstd(y[keep]) == 0:
                    pearson, spearman = np.nan, np.nan
                else:
                    pearson = float(pearsonr(x[keep], y[keep]).statistic)
                    spearman = float(spearmanr(x[keep], y[keep]).statistic)
                rows.append(
                    {
                        "scope": scope,
                        "new_feature": new,
                        "frozen_a3_history_predictor": old,
                        "n_complete_pairs": n,
                        "pearson_r": pearson,
                        "spearman_rho": spearman,
                    }
                )
    return pd.DataFrame(rows)


DISTANCE_BIN_EDGES = np.array([0.0, 1.0, 5.0, 10.0, 25.0, 50.0, 100.0, 250.0, np.inf])
DISTANCE_BIN_LABELS = ["<1", "1-5", "5-10", "10-25", "25-50", "50-100", "100-250", "250+"]


def response_associations(panel: pd.DataFrame) -> pd.DataFrame:
    features = [
        c
        for c in panel.columns
        if c.startswith("nearest_history_point_")
    ]
    rows: list[dict[str, object]] = []
    for feature in features:
        values = pd.to_numeric(panel[feature], errors="coerce").to_numpy(dtype=np.float64)
        bins = np.full(len(panel), "missing", dtype=object)
        finite = np.isfinite(values)
        bins[finite] = pd.cut(
            values[finite],
            bins=DISTANCE_BIN_EDGES,
            labels=DISTANCE_BIN_LABELS,
            right=False,
            include_lowest=True,
        ).astype(str)
        for label in [*DISTANCE_BIN_LABELS, "missing"]:
            selected = bins == label
            part = panel.loc[selected]
            if len(part) == 0:
                continue
            counts = part["count"].to_numpy(dtype=np.float64)
            rows.append(
                {
                    "feature": feature,
                    "distance_bin_km": label,
                    "n_cell_weeks": int(len(part)),
                    "occurrence_rate": float(np.mean(counts > 0)),
                    "mean_count_including_zeros": float(np.mean(counts)),
                    "mean_count_when_positive": float(np.mean(counts[counts > 0])) if np.any(counts > 0) else np.nan,
                }
            )
    return pd.DataFrame(rows)


def pairwise_projection_accuracy(
    points: pd.DataFrame, point_distances: pd.DataFrame, seed: int = 20261122
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows: list[dict[str, object]] = []
    point_idx = points.set_index("point_id")
    for lag in LAGS:
        subset = point_distances.loc[
            (point_distances["lag_weeks"] == lag)
            & (point_distances["neighbor_point_id"] >= 0)
        ]
        if len(subset) > 1000:
            picks = np.sort(rng.choice(len(subset), size=1000, replace=False))
            subset = subset.iloc[picks]
        projected: list[float] = []
        geodesic: list[float] = []
        for row in subset.itertuples(index=False):
            focal = point_idx.loc[int(row.point_id)]
            neighbor = point_idx.loc[int(row.neighbor_point_id)]
            g = wgs84_geodesic_km(
                float(focal["lon_deg"]),
                float(focal["lat_deg"]),
                float(neighbor["lon_deg"]),
                float(neighbor["lat_deg"]),
            )
            p = float(row.distance_km)
            projected.append(p)
            geodesic.append(g)
        p_arr = np.asarray(projected, dtype=np.float64)
        g_arr = np.asarray(geodesic, dtype=np.float64)
        relative = np.divide(
            p_arr - g_arr,
            g_arr,
            out=np.full(len(g_arr), np.nan, dtype=np.float64),
            where=g_arr > 1e-12,
        )
        rows.append(
            {
                "lag_weeks": int(lag),
                "n_pairs_sampled": int(len(p_arr)),
                "sampling_seed": seed,
                "sample_rule": "up to 1000 point-nearest pairs per lag, deterministic uniform sample",
                "median_absolute_difference_km": float(np.median(np.abs(p_arr - g_arr))) if len(p_arr) else np.nan,
                "p95_absolute_difference_km": float(np.quantile(np.abs(p_arr - g_arr), 0.95)) if len(p_arr) else np.nan,
                "maximum_absolute_difference_km": float(np.max(np.abs(p_arr - g_arr))) if len(p_arr) else np.nan,
                "median_relative_difference": float(np.nanmedian(relative)) if np.isfinite(relative).any() else np.nan,
                "p95_absolute_relative_difference": float(np.nanquantile(np.abs(relative), 0.95)) if np.isfinite(relative).any() else np.nan,
                "maximum_absolute_relative_difference": float(np.nanmax(np.abs(relative))) if np.isfinite(relative).any() else np.nan,
            }
        )
    return pd.DataFrame(rows)


def write_svg(path: Path, body: str, width: int, height: int, title: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
        '<rect width="100%" height="100%" fill="#ffffff"/>'
        f'<title>{html.escape(title)}</title>'
        '<style>text{font-family:Arial,Helvetica,sans-serif;fill:#20303f}'
        '.title{font-size:22px;font-weight:700}.label{font-size:13px}'
        '.small{font-size:11px;fill:#526273}.axis{stroke:#526273;stroke-width:1}'
        '.grid{stroke:#dce3e9;stroke-width:1}.line{fill:none;stroke-width:2.2}'
        '</style>'
        f'{body}</svg>'
    )
    path.write_text(content, encoding="utf-8")


COLORS = ["#087e8b", "#e07a28", "#5661a8", "#4f8a5b", "#ba4a68", "#7d5a9b"]


def svg_weekly(weekly: pd.DataFrame, path: Path) -> None:
    width, height = 1120, 660
    left, right = 80, 1060
    top1, bottom1 = 90, 365
    top2, bottom2 = 445, 585
    data = weekly.sort_values("week_ord")
    x = np.linspace(left, right, len(data))
    ymax = max(25.0, float(np.nanquantile(data["p90_km"], 0.98)) if data["p90_km"].notna().any() else 25.0)
    ymax = min(ymax, max(100.0, float(np.nanmax(data["p90_km"])) if data["p90_km"].notna().any() else 100.0))
    body = ['<text x="80" y="42" class="title">Weekly point-level nearest-neighbor distance</text>']
    for tick in np.linspace(0, ymax, 6):
        yy = bottom1 - (tick / ymax) * (bottom1 - top1)
        body.append(f'<line x1="{left}" y1="{yy:.1f}" x2="{right}" y2="{yy:.1f}" class="grid"/>')
        body.append(f'<text x="{left-12}" y="{yy+4:.1f}" text-anchor="end" class="small">{tick:.0f}</text>')
    body.extend(
        [
            f'<line x1="{left}" y1="{top1}" x2="{left}" y2="{bottom1}" class="axis"/>',
            f'<line x1="{left}" y1="{bottom1}" x2="{right}" y2="{bottom1}" class="axis"/>',
            f'<text x="22" y="{(top1+bottom1)//2}" transform="rotate(-90 22 {(top1+bottom1)//2})" class="label">Distance (km)</text>',
            f'<text x="{(left+right)//2}" y="415" text-anchor="middle" class="label">ISO week (2025-W01 to 2026-W44)</text>',
        ]
    )
    for i, row in enumerate(data.itertuples(index=False)):
        if not np.isfinite(row.median_km):
            continue
        yy = lambda val: bottom1 - (float(val) / ymax) * (bottom1 - top1)
        body.append(f'<line x1="{x[i]:.1f}" y1="{yy(row.p25_km):.1f}" x2="{x[i]:.1f}" y2="{yy(row.p75_km):.1f}" stroke="#087e8b" stroke-width="2"/>')
        body.append(f'<circle cx="{x[i]:.1f}" cy="{yy(row.median_km):.1f}" r="3" fill="#087e8b"/>')
    for i in (0, len(data)//2, len(data)-1):
        body.append(f'<text x="{x[i]:.1f}" y="{bottom1+22}" text-anchor="middle" class="small">{html.escape(str(data.iloc[i]["week"]))}</text>')
    nmax = max(1, int(data["n_observations"].max()))
    body.extend(
        [
            f'<text x="{left}" y="{top2-18}" class="label">Weekly observations (counts shown to contextualize reporting intensity)</text>',
            f'<line x1="{left}" y1="{bottom2}" x2="{right}" y2="{bottom2}" class="axis"/>',
        ]
    )
    barw = max(2.0, (right-left) / len(data) * 0.7)
    for i, n in enumerate(data["n_observations"].to_numpy()):
        bh = float(n) / nmax * (bottom2-top2)
        body.append(f'<rect x="{x[i]-barw/2:.1f}" y="{bottom2-bh:.1f}" width="{barw:.1f}" height="{bh:.1f}" fill="#94b8c1"/>')
    write_svg(path, "".join(body), width, height, "Weekly point-level nearest-neighbor distance")


def svg_lag(lags: pd.DataFrame, path: Path) -> None:
    width, height = 900, 560
    left, right, top, bottom = 95, 850, 90, 450
    data = lags.sort_values("lag_weeks")
    max_value = float(np.nanquantile(data["p90_km"], 0.95)) if data["p90_km"].notna().any() else 25.0
    max_value = max(25.0, min(max_value, 2000.0))
    body = ['<text x="78" y="42" class="title">Nearest point distance by exact temporal lag</text>']
    for tick in (0.0, 5.0, 10.0, 25.0, 50.0, 100.0, 250.0, 500.0, 1000.0, 2000.0):
        if tick > max_value:
            continue
        y = bottom - tick / max_value * (bottom-top)
        body.append(f'<line x1="{left}" y1="{y:.1f}" x2="{right}" y2="{y:.1f}" class="grid"/>')
        body.append(f'<text x="{left-12}" y="{y+4:.1f}" text-anchor="end" class="small">{tick:g}</text>')
    body.extend(
        [
            f'<line x1="{left}" y1="{top}" x2="{left}" y2="{bottom}" class="axis"/>',
            f'<line x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}" class="axis"/>',
            f'<text x="28" y="{(top+bottom)//2}" transform="rotate(-90 28 {(top+bottom)//2})" class="label">Distance (km)</text>',
            '<text x="470" y="520" text-anchor="middle" class="label">Reference period</text>',
        ]
    )
    xs = np.linspace(left+45, right-45, len(data))
    for i, row in enumerate(data.itertuples(index=False)):
        if not np.isfinite(row.median_km):
            continue
        scale = lambda v: bottom - float(v) / max_value * (bottom-top)
        body.append(f'<line x1="{xs[i]:.1f}" y1="{scale(row.p10_km):.1f}" x2="{xs[i]:.1f}" y2="{scale(row.p90_km):.1f}" stroke="#a9bdc6" stroke-width="8"/>')
        body.append(f'<line x1="{xs[i]:.1f}" y1="{scale(row.p25_km):.1f}" x2="{xs[i]:.1f}" y2="{scale(row.p75_km):.1f}" stroke="#087e8b" stroke-width="13"/>')
        body.append(f'<circle cx="{xs[i]:.1f}" cy="{scale(row.median_km):.1f}" r="5" fill="#e07a28"/>')
        label = "Same week" if row.lag_weeks == 0 else f"{row.lag_weeks} week{'s' if row.lag_weeks != 1 else ''} earlier"
        body.append(f'<text x="{xs[i]:.1f}" y="{bottom+25}" text-anchor="middle" class="small">{label}</text>')
    body.extend(
        [
            '<circle cx="105" cy="485" r="5" fill="#e07a28"/><text x="118" y="489" class="small">Median</text>',
            '<line x1="205" y1="485" x2="235" y2="485" stroke="#087e8b" stroke-width="13"/><text x="245" y="489" class="small">Interquartile range</text>',
            '<line x1="395" y1="485" x2="425" y2="485" stroke="#a9bdc6" stroke-width="8"/><text x="435" y="489" class="small">10th–90th percentiles</text>',
        ]
    )
    write_svg(path, "".join(body), width, height, "Nearest point distance by temporal lag")


def svg_regional(regional: pd.DataFrame, path: Path) -> None:
    width, height = 1120, 650
    left, right, top, bottom = 85, 1050, 100, 430
    body = ['<text x="80" y="42" class="title">Weekly clustering by existing A3 geographic stratum</text>']
    regions = sorted(regional["region"].astype(str).unique())
    ymax = float(np.nanquantile(regional["p90_km"], 0.98)) if regional["p90_km"].notna().any() else 100.0
    ymax = max(25.0, min(ymax, 1500.0))
    for tick in np.linspace(0, ymax, 6):
        y = bottom - tick / ymax * (bottom-top)
        body.append(f'<line x1="{left}" y1="{y:.1f}" x2="{right}" y2="{y:.1f}" class="grid"/>')
        body.append(f'<text x="{left-12}" y="{y+4:.1f}" text-anchor="end" class="small">{tick:.0f}</text>')
    body.extend(
        [
            f'<line x1="{left}" y1="{top}" x2="{left}" y2="{bottom}" class="axis"/>',
            f'<line x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}" class="axis"/>',
            f'<text x="28" y="{(top+bottom)//2}" transform="rotate(-90 28 {(top+bottom)//2})" class="label">Same-region distance (km)</text>',
        ]
    )
    weeks = sorted(regional["week_ord"].unique())
    x_map = {week: left + (right-left) * i / max(1, len(weeks)-1) for i, week in enumerate(weeks)}
    for index, region in enumerate(regions):
        part = regional.loc[regional["region"].astype(str) == region].sort_values("week_ord")
        color = COLORS[index % len(COLORS)]
        coords = []
        for row in part.itertuples(index=False):
            if not np.isfinite(row.median_km):
                continue
            x = x_map[int(row.week_ord)]
            y = bottom - float(row.median_km) / ymax * (bottom-top)
            coords.append((x, y))
        if coords:
            body.append(
                '<polyline class="line" stroke="'
                + color
                + '" points="'
                + " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
                + '"/>'
            )
        lx = 780 + index * 125
        body.append(f'<line x1="{lx}" y1="67" x2="{lx+25}" y2="67" stroke="{color}" stroke-width="3"/>')
        body.append(f'<text x="{lx+32}" y="71" class="small">{html.escape(region)}</text>')
    for i in (0, len(weeks)//2, len(weeks)-1):
        w = weeks[i]
        body.append(f'<text x="{x_map[w]:.1f}" y="{bottom+24}" text-anchor="middle" class="small">{ordinal_label(w)}</text>')
    body.append('<text x="550" y="505" text-anchor="middle" class="label">ISO week (counts are recorded in the companion summary)</text>')
    write_svg(path, "".join(body), width, height, "Regional point-level clustering")


def svg_associations(associations: pd.DataFrame, path: Path) -> None:
    windows = list(HISTORY_WINDOWS)
    width, height = 1160, 680
    panel_w, panel_h = 515, 235
    body = ['<text x="60" y="38" class="title">Observed cell-week response across prespecified proximity bins</text>']
    for w_i, window in enumerate(windows):
        row_i, col_i = divmod(w_i, 2)
        x0 = 70 + col_i * 560
        y0 = 88 + row_i * 285
        subset = associations.loc[
            associations["feature"] == f"nearest_history_point_any_prev{window}w_km"
        ].copy()
        if subset.empty:
            continue
        subset["distance_bin_km"] = pd.Categorical(
            subset["distance_bin_km"], categories=[*DISTANCE_BIN_LABELS, "missing"], ordered=True
        )
        subset = subset.sort_values("distance_bin_km")
        plot = subset.loc[subset["distance_bin_km"] != "missing"]
        n = len(plot)
        xs = np.linspace(x0+45, x0+panel_w-15, max(1, n))
        body.append(f'<text x="{x0}" y="{y0-12}" class="label" font-weight="700">Previous {window} week{"s" if window != 1 else ""}</text>')
        body.append(f'<line x1="{x0+35}" y1="{y0+panel_h-35}" x2="{x0+panel_w}" y2="{y0+panel_h-35}" class="axis"/>')
        body.append(f'<line x1="{x0+35}" y1="{y0+10}" x2="{x0+35}" y2="{y0+panel_h-35}" class="axis"/>')
        body.append(f'<line x1="{x0+35}" y1="{y0+10}" x2="{x0+panel_w}" y2="{y0+10}" class="grid"/>')
        body.append(f'<text x="{x0+8}" y="{y0+panel_h//2}" transform="rotate(-90 {x0+8} {y0+panel_h//2})" class="small">Occurrence rate</text>')
        coords = []
        for i, r in enumerate(plot.itertuples(index=False)):
            x = xs[i]
            y = y0 + panel_h - 35 - float(r.occurrence_rate) * (panel_h-45)
            coords.append((x,y))
            body.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{COLORS[w_i]}"/>')
            body.append(f'<text x="{x:.1f}" y="{y0+panel_h-14}" text-anchor="middle" class="small">{r.distance_bin_km}</text>')
            body.append(f'<text x="{x:.1f}" y="{y0+panel_h-24}" text-anchor="middle" class="small">{int(r.n_cell_weeks)}</text>')
        if coords:
            body.append(f'<polyline class="line" stroke="{COLORS[w_i]}" points="' + " ".join(f"{x:.1f},{y:.1f}" for x,y in coords) + '"/>')
        body.append(f'<text x="{x0+panel_w//2}" y="{y0+panel_h+8}" text-anchor="middle" class="small">Distance bin (km); labels below axis show N cell-weeks</text>')
    body.append('<text x="70" y="660" class="small">Missing-history cell-weeks are reported in the accompanying table; the curves are descriptive and are not causal effects.</text>')
    write_svg(path, "".join(body), width, height, "Observed response by historical proximity")


def svg_boundary_examples(
    points: pd.DataFrame,
    nearest_pairs: pd.DataFrame,
    nodes: pd.DataFrame,
    grid: dict,
    path: Path,
) -> None:
    cross = nearest_pairs.loc[
        (~nearest_pairs["same_cell_neighbor"])
        & np.isfinite(nearest_pairs["point_to_point_nn_km"])
    ].sort_values(["point_to_point_nn_km", "week_ord", "point_id"])
    if cross.empty:
        return
    pair = cross.iloc[0]
    primary_in = points.loc[
        (points["week"] == pair["week"])
        & points["in_fitted_domain"]
    ]
    focal = primary_in.loc[primary_in["point_id"] == int(pair["point_id"])].iloc[0]
    neighbor = primary_in.loc[primary_in["point_id"] == int(pair["neighbor_point_id"])].iloc[0]
    cell_nodes = nodes.set_index("model_node_id")
    focal_node = cell_nodes.loc[int(pair["focal_model_node_id"])]
    neighbor_node = cell_nodes.loc[int(pair["neighbor_model_node_id"])]
    centers_x = [float(focal_node["x"]), float(neighbor_node["x"])]
    centers_y = [float(focal_node["y"]), float(neighbor_node["y"])]
    a, _, c, _, e, f = tuple(grid["transform"])[:6]
    half_x, half_y = a/2.0, abs(e)/2.0
    pad = max(35.0, abs(centers_x[0]-centers_x[1]) + 15.0)
    xmin, xmax = min(centers_x)-pad, max(centers_x)+pad
    ymin, ymax = min(centers_y)-pad, max(centers_y)+pad
    width, height = 820, 670
    left, right, top, bottom = 80, 790, 90, 590
    sx = (right-left)/(xmax-xmin)
    sy = (bottom-top)/(ymax-ymin)
    scale = min(sx, sy)
    xmid = (xmin+xmax)/2
    ymid = (ymin+ymax)/2
    px = lambda value: (right+left)/2 + (float(value)-xmid)*scale
    py = lambda value: (bottom+top)/2 - (float(value)-ymid)*scale
    body = [
        '<text x="65" y="40" class="title">Two observations assigned to different A3 cells</text>',
        f'<text x="65" y="65" class="small">{html.escape(str(pair["week"]))}; point separation {float(pair["point_to_point_nn_km"]):.2f} km; centroid separation {float(pair["centroid_to_centroid_km"]):.2f} km</text>',
    ]
    # Draw the exact neighboring cell footprints from the canonical grid affine.
    for node in (focal_node, neighbor_node):
        col0, row0 = int(node["column"])-1, int(node["row"])-1
        x0, y1 = c + a*col0, f + e*row0
        x1, y0 = x0+a, y1+e
        body.append(
            f'<rect x="{px(x0):.1f}" y="{py(y1):.1f}" width="{a*scale:.1f}" height="{abs(e)*scale:.1f}" '
            'fill="#eaf1f4" stroke="#34495e" stroke-width="2"/>'
        )
        body.append(f'<circle cx="{px(node["x"]):.1f}" cy="{py(node["y"]):.1f}" r="4" fill="#34495e"/>')
    view = primary_in.loc[
        (primary_in["x_km"] >= xmin)
        & (primary_in["x_km"] <= xmax)
        & (primary_in["y_km"] >= ymin)
        & (primary_in["y_km"] <= ymax)
    ]
    body.append(f'<line x1="{px(focal["x_km"]):.1f}" y1="{py(focal["y_km"]):.1f}" x2="{px(neighbor["x_km"]):.1f}" y2="{py(neighbor["y_km"]):.1f}" stroke="#c94f38" stroke-width="2.5"/>')
    body.append(f'<circle cx="{px(focal["x_km"]):.1f}" cy="{py(focal["y_km"]):.1f}" r="6" fill="#087e8b" stroke="#fff" stroke-width="1.5"/>')
    body.append(f'<circle cx="{px(neighbor["x_km"]):.1f}" cy="{py(neighbor["y_km"]):.1f}" r="6" fill="#e07a28" stroke="#fff" stroke-width="1.5"/>')
    for r in view.itertuples(index=False):
        if int(r.point_id) in (int(focal["point_id"]), int(neighbor["point_id"])):
            continue
        body.append(f'<circle cx="{px(r.x_km):.1f}" cy="{py(r.y_km):.1f}" r="2.8" fill="#7b8991" opacity="0.75"/>')
    body.extend(
        [
            '<circle cx="120" cy="625" r="5" fill="#087e8b"/><text x="132" y="629" class="small">Focal observation</text>',
            '<circle cx="280" cy="625" r="5" fill="#e07a28"/><text x="292" y="629" class="small">Nearest point in another cell</text>',
            '<rect x="500" y="617" width="18" height="14" fill="#eaf1f4" stroke="#34495e"/><text x="526" y="629" class="small">Existing model-cell footprint</text>',
        ]
    )
    write_svg(path, "".join(body), width, height, "Point nearest-neighbor relative to A3 cell boundaries")


def write_csv(path: Path, data: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data.to_csv(path, index=False, float_format="%.12g", quoting=csv.QUOTE_MINIMAL)


def serialize_point_products(
    output_root: Path,
    points: pd.DataFrame,
    point_distances: pd.DataFrame,
    cell_metrics: pd.DataFrame,
    within_cell_nn: pd.DataFrame,
    panel: pd.DataFrame,
    boundary_pairs: pd.DataFrame,
) -> None:
    detailed = output_root / "detailed"
    detailed.mkdir(parents=True, exist_ok=True)
    point_cols = [
        "point_id",
        "date",
        "week",
        "week_ord",
        "lon",
        "lat",
        "lon_deg",
        "lat_deg",
        "host",
        "x_km",
        "y_km",
        "raster_row",
        "raster_column",
        "model_node_id",
        "region",
        "in_fitted_domain",
        "point_to_cell_centroid_km",
        "point_to_cell_footprint_km",
        "distance_to_cell_boundary_km",
        "primary_period",
    ]
    points[point_cols].to_parquet(detailed / "point_assignments.parquet", index=False)
    point_distances.to_parquet(detailed / "point_nearest_neighbors.parquet", index=False)
    if len(cell_metrics):
        cell_metrics.to_parquet(detailed / "within_cell_pair_metrics.parquet", index=False)
    if len(within_cell_nn):
        within_cell_nn.to_parquet(detailed / "within_cell_point_nearest_neighbors.parquet", index=False)
    panel.to_parquet(detailed / "cell_week_proximity_features.parquet", index=False)
    boundary_pairs.to_parquet(detailed / "boundary_nearest_pairs.parquet", index=False)


def collect_output_hashes(root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name not in {"run_complete.json"}:
            hashes[str(path.relative_to(root))] = sha256_file(path)
    return hashes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=OUTPUT_DEFAULT)
    parser.add_argument("--repository-results", type=Path, default=None)
    parser.add_argument("--mode", choices=["check", "full"], default="full")
    parser.add_argument("--workers", type=int, default=int(os.environ.get("SLURM_CPUS_PER_TASK", "1")))
    args = parser.parse_args()
    if args.workers < 1:
        raise ValueError("--workers must be >=1")
    started = time.monotonic()

    allowed_existing = {"focused_validation.json"}
    if args.output_root.exists():
        existing_files = {
            str(path.relative_to(args.output_root))
            for path in args.output_root.rglob("*")
            if path.is_file()
        }
        unexpected = existing_files - allowed_existing
        if unexpected:
            raise RuntimeError(
                "The Atlas output root is nonempty or contains an incomplete prior run; "
                f"preserving it and stopping. Existing paths: {sorted(unexpected)[:20]}"
            )
    args.output_root.mkdir(parents=True, exist_ok=True)

    synthetic = run_synthetic_checks()
    points, nodes, weeks, target_counts, grid, provenance = load_and_prepare(args.output_root)
    check, response_panel, _ = focused_check(points, nodes, weeks, target_counts, grid)
    check["synthetic_checks"] = synthetic
    check["input_hashes"] = provenance["sha256"]
    check["primary_week_start"] = PRIMARY_START
    check["primary_week_end"] = PRIMARY_END
    check["workers"] = int(args.workers)
    (args.output_root / "focused_validation.json").write_text(
        json.dumps(check, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"focused_validation": check["status"], "source_rows": provenance["source_row_count"]}))
    if args.mode == "check":
        return

    point_distances, weekly_summary, lag_summary, regional_weekly, regional_lag = run_point_temporal_analysis(
        points
    )
    point_distances["reference_week_defined"] = point_distances["distance_km"].notna()
    projection_accuracy = pairwise_projection_accuracy(points, point_distances)
    cell_week_counts = point_cell_week_counts(points)
    within_cell_metrics, within_cell_nn, cellweek_summary, within_cell_summary = within_cell_analysis(
        points, cell_week_counts
    )
    short_pair_summary = bounded_short_pairs(points)
    boundary_pairs, boundary_summary = between_cell_analysis(points, nodes)
    front_path = CANDIDATE_ROOT / "front_features" / "causal_front_features.parquet"
    panel, proximity_features = add_history_features(
        points, nodes, weeks, response_panel, front_path, workers=args.workers
    )
    inventory = feature_inventory(panel)
    feature_groups = feature_group_summaries(panel)
    correlations = correlation_diagnostics(panel)
    associations = response_associations(panel)

    output_root = args.output_root
    aggregate_dir = output_root / "aggregate"
    figure_dir = output_root / "figures"
    aggregate_dir.mkdir(parents=True, exist_ok=True)
    figure_dir.mkdir(parents=True, exist_ok=True)
    write_csv(aggregate_dir / "weekly_nearest_neighbor_summary.csv", weekly_summary)
    write_csv(aggregate_dir / "temporal_lag_summary.csv", lag_summary)
    write_csv(aggregate_dir / "regional_clustering_summary.csv", regional_weekly)
    write_csv(aggregate_dir / "regional_temporal_lag_summary.csv", regional_lag)
    write_csv(aggregate_dir / "cell_week_concentration_summary.csv", cellweek_summary)
    write_csv(aggregate_dir / "within_cell_distance_summary.csv", within_cell_summary)
    write_csv(aggregate_dir / "between_cell_proximity_summary.csv", boundary_summary)
    write_csv(aggregate_dir / "short_distance_pair_summary.csv", short_pair_summary)
    write_csv(aggregate_dir / "historical_proximity_feature_inventory.csv", inventory)
    write_csv(aggregate_dir / "historical_feature_distribution_by_group.csv", feature_groups)
    write_csv(aggregate_dir / "feature_redundancy_correlations.csv", correlations)
    write_csv(aggregate_dir / "response_associations_by_distance_bin.csv", associations)
    write_csv(aggregate_dir / "projection_distance_accuracy.csv", projection_accuracy)
    if args.repository_results is not None:
        repo_results = args.repository_results
        repo_results.mkdir(parents=True, exist_ok=True)
        for source in aggregate_dir.glob("*.csv"):
            write_csv(repo_results / source.name, pd.read_csv(source))
        figure_targets = repo_results.parent / "figures"
        figure_targets.mkdir(parents=True, exist_ok=True)
        svg_weekly(weekly_summary, figure_targets / "weekly_nearest_neighbor_distance.svg")
        svg_lag(lag_summary, figure_targets / "temporal_lag_distance_distribution.svg")
        svg_regional(regional_weekly, figure_targets / "regional_clustering.svg")
        svg_associations(associations, figure_targets / "historical_proximity_response_associations.svg")
    svg_weekly(weekly_summary, figure_dir / "weekly_nearest_neighbor_distance.svg")
    svg_lag(lag_summary, figure_dir / "temporal_lag_distance_distribution.svg")
    svg_regional(regional_weekly, figure_dir / "regional_clustering.svg")
    svg_associations(associations, figure_dir / "historical_proximity_response_associations.svg")
    svg_boundary_examples(
        points,
        boundary_pairs,
        nodes,
        grid,
        figure_dir / "point_nearest_neighbor_at_cell_boundary.svg",
    )

    resource_info = {
        "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
        "slurm_job_name": os.environ.get("SLURM_JOB_NAME"),
        "hostname": platform.node(),
        "cpus_per_task": os.environ.get("SLURM_CPUS_PER_TASK"),
        "mem_per_node": os.environ.get("SLURM_MEM_PER_NODE"),
        "elapsed_seconds": float(time.monotonic() - started),
        "peak_rss_kib": (
            int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
            if resource is not None
            else None
        ),
        "python": sys.version.split()[0],
        "packages": {
            name: importlib.metadata.version(name)
            for name in ("numpy", "pandas", "scipy", "rasterio", "pyarrow")
        },
        "execution": "single CPU Slurm job using the existing STGNN Python bootstrap",
        "model_fitting": False,
    }
    (output_root / "execution_resources.json").write_text(
        json.dumps(resource_info, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    domain_by_week = (
        points.loc[points["primary_period"]]
        .groupby(["week", "region"], sort=True)
        .size()
        .rename("n_observations")
        .reset_index()
    )
    domain_by_week = domain_by_week.pivot(
        index="week", columns="region", values="n_observations"
    ).fillna(0).reset_index()
    write_csv(aggregate_dir / "domain_assignment_by_week.csv", domain_by_week)
    resource_info["rows_in_primary_period"] = int(points["primary_period"].sum())
    resource_info["rows_assigned_to_model_domain"] = int(
        (points["primary_period"] & points["in_fitted_domain"]).sum()
    )
    resource_info["rows_outside_model_domain"] = int(
        (points["primary_period"] & ~points["in_fitted_domain"]).sum()
    )
    resource_info["cell_week_rows"] = int(len(panel))
    resource_info["point_lag_rows"] = int(len(point_distances))
    (output_root / "execution_resources.json").write_text(
        json.dumps(resource_info, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    serialize_point_products(
        output_root,
        points,
        point_distances,
        within_cell_metrics,
        within_cell_nn,
        panel,
        boundary_pairs,
    )
    provenance["grid"] = {
        "projection": grid["projection_name"],
        "distance_units": grid["distance_units"],
        "resolution_km": grid["resolution_km"],
        "height": grid["height"],
        "width": grid["width"],
        "valid_environment_mask_cells": grid["mask_valid_cell_count"],
        "fitted_model_cells": int(len(nodes)),
        "affine": list(grid["transform"]),
        "centroid_transform_residual_m": grid["centroid_transform_residual_m"],
    }
    provenance["analysis"] = {
        "primary_week_start": PRIMARY_START,
        "primary_week_end": PRIMARY_END,
        "exact_lags_weeks": list(LAGS),
        "historical_windows_weeks": list(HISTORY_WINDOWS),
        "concentration_radii_km": list(CONCENTRATION_RADII_KM),
        "concentration_lookback_weeks": 12,
        "boundary_band_km": BOUNDARY_BAND_KM,
        "source_points_through_w44": int(len(points)),
        "primary_period_points": int(points["primary_period"].sum()),
        "in_domain_points_through_w44": int(points["in_fitted_domain"].sum()),
        "out_of_domain_points_through_w44": int((~points["in_fitted_domain"]).sum()),
        "response_reproduction": check["response_reproduction"],
        "strict_history_cutoff_violations": int((~panel["history_cutoff_is_strictly_prior"]).sum()),
    }
    provenance["runtime"] = resource_info
    (output_root / "analysis_manifest.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )

    if args.repository_results is not None:
        copy_manifest = {
            "data_vintage": provenance["sha256"]["observation_source"],
            "repository_results_path": str(args.repository_results),
            "aggregate_files": sorted(p.name for p in aggregate_dir.glob("*.csv")),
            "figures": [
                "weekly_nearest_neighbor_distance.svg",
                "temporal_lag_distance_distribution.svg",
                "regional_clustering.svg",
                "historical_proximity_response_associations.svg",
            ],
            "detailed_point_outputs": "retained only under the Atlas output root",
        }
        (args.repository_results / "aggregate_result_manifest.json").write_text(
            json.dumps(copy_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    completion = {
        "status": "COMPLETE",
        "output_hashes": collect_output_hashes(output_root),
        "completed_at_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }
    (output_root / "run_complete.json").write_text(
        json.dumps(completion, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": "COMPLETE",
                "output_root": str(output_root),
                "primary_observations": int(points["primary_period"].sum()),
                "in_domain_primary_observations": int(
                    (points["primary_period"] & points["in_fitted_domain"]).sum()
                ),
                "point_lag_rows": int(len(point_distances)),
                "cell_week_feature_rows": int(len(panel)),
                "elapsed_seconds": resource_info["elapsed_seconds"],
            }
        )
    )


if __name__ == "__main__":
    main()
