#!/usr/bin/env python3
"""Extract the bounded P7B focal-region data from the canonical P2 archive.

This script is intentionally Atlas-side and read-only with respect to the P2
archive.  It writes only a compact derived extract and deterministic summaries
needed by the P7B figure scripts.  It does not fit a model or copy the full
prediction archive into the repository.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq


FOCAL_BBOX = {
    "crs": "EPSG:4326",
    "longitude_min": -107.5,
    "longitude_max": -96.0,
    "latitude_min": 24.0,
    "latitude_max": 33.0,
}
FOCAL_CELLS = 1689
MAP_WEEKS = [
    "2026-W17",
    "2026-W22",
    "2026-W27",
    "2026-W32",
    "2026-W37",
]
ALL_WEEKS = [f"2026-W{week:02d}" for week in range(17, 38)]
REQUIRED_COLUMNS = [
    "origin_week",
    "target_week",
    "horizon",
    "model_node_id",
    "row",
    "column",
    "lon",
    "lat",
    "country_or_domain_region",
    "observed_count",
    "observed_positive",
    "p_occurrence",
    "conditional_count_mean",
    "expected_count",
    "previously_occupied",
    "prediction_frontier_class",
    "outcome_frontier_label",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, float_format="%.17g", lineterminator="\n")


def read_expected_source_hash(repo_root: Path) -> str | None:
    manifest = repo_root / "analysis/p2_operational_nowcast/results/prediction_archive_manifest.json"
    if not manifest.exists():
        return None
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    for key in ("sha256", "archive_sha256", "combined_archive_sha256"):
        value = payload.get(key)
        if isinstance(value, str) and len(value) == 64:
            return value
    combined = payload.get("combined_archive")
    if isinstance(combined, dict):
        value = combined.get("sha256") or combined.get("sha256_hex")
        if isinstance(value, str) and len(value) == 64:
            return value
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    args = parser.parse_args()

    archive = args.archive.resolve()
    output_root = args.output_root.resolve()
    repo_root = args.repo_root.resolve()
    results = repo_root / "analysis/p7b_science_figures/results"
    results.mkdir(parents=True, exist_ok=True)
    output_root.mkdir(parents=True, exist_ok=True)

    available = set(pq.ParquetFile(archive).schema.names)
    missing = [name for name in REQUIRED_COLUMNS if name not in available]
    if missing:
        raise SystemExit(f"Missing canonical P2 columns: {missing}")

    table = pq.read_table(archive, columns=REQUIRED_COLUMNS)
    frame = table.to_pandas()
    frame = frame.loc[
        (frame["horizon"] == 1)
        & (frame["lon"] >= FOCAL_BBOX["longitude_min"])
        & (frame["lon"] <= FOCAL_BBOX["longitude_max"])
        & (frame["lat"] >= FOCAL_BBOX["latitude_min"])
        & (frame["lat"] <= FOCAL_BBOX["latitude_max"])
        & frame["target_week"].isin(ALL_WEEKS)
    ].copy()
    frame = frame.sort_values(
        ["target_week", "model_node_id", "origin_week"],
        kind="mergesort",
    ).reset_index(drop=True)

    cells = frame[["model_node_id", "row", "column", "lon", "lat", "country_or_domain_region"]].drop_duplicates(
        "model_node_id"
    )
    if len(cells) != FOCAL_CELLS:
        raise SystemExit(f"Expected {FOCAL_CELLS} focal cells, found {len(cells)}")
    if set(frame["target_week"].unique()) != set(ALL_WEEKS):
        raise SystemExit("Focal target-week interval is incomplete")
    expected_rows = FOCAL_CELLS * len(ALL_WEEKS)
    if len(frame) != expected_rows:
        raise SystemExit(f"Expected {expected_rows} focal rows, found {len(frame)}")

    focal_parquet = output_root / "focal_extract/mexico_texas_focal_h1_2026w17_w37.parquet"
    focal_parquet.parent.mkdir(parents=True, exist_ok=True)
    table_out = __import__("pyarrow").Table.from_pandas(frame, preserve_index=False)
    __import__("pyarrow.parquet").parquet.write_table(table_out, focal_parquet)

    domain_week = pq.read_table(
        archive,
        columns=[
            "target_week",
            "horizon",
            "model_node_id",
            "row",
            "column",
            "lon",
            "lat",
            "country_or_domain_region",
        ],
        filters=[("target_week", "=", "2026-W17"), ("horizon", "=", 1)],
    ).to_pandas()
    domain_grid = domain_week.drop_duplicates("model_node_id").sort_values("model_node_id")
    if len(domain_grid) != 10037:
        raise SystemExit(f"Expected 10037 domain cells, found {len(domain_grid)}")
    stable_csv(
        domain_grid.drop(columns=["target_week", "horizon"]),
        results / "figure_01_domain_grid.csv",
    )

    map_frame = frame.loc[frame["target_week"].isin(MAP_WEEKS)].copy()
    map_frame = map_frame.sort_values(["target_week", "model_node_id"], kind="mergesort")
    stable_csv(map_frame, results / "figure_03_focal_h1_map_data.csv")

    weekly = (
        frame.groupby("target_week", sort=True)
        .agg(
            rows=("model_node_id", "size"),
            cells=("model_node_id", "nunique"),
            observed_positive_cells=("observed_positive", "sum"),
            expected_positive_cells=("p_occurrence", "sum"),
            observed_count=("observed_count", "sum"),
            expected_count=("expected_count", "sum"),
            frontier_positive_cells=("observed_positive", lambda x: 0),
        )
        .reset_index()
    )
    frontier = frame["prediction_frontier_class"].astype("string").str.upper().str.contains("FRONTIER", na=False)
    frontier_frame = frame.loc[frontier]
    frontier_weekly = (
        frontier_frame.groupby("target_week", sort=True)
        .agg(
            frontier_positive_cells=("observed_positive", "sum"),
            frontier_expected_positive_cells=("p_occurrence", "sum"),
        )
        .reset_index()
    )
    weekly = weekly.drop(columns=["frontier_positive_cells"]).merge(frontier_weekly, on="target_week", how="left")
    weekly[["frontier_positive_cells", "frontier_expected_positive_cells"]] = weekly[
        ["frontier_positive_cells", "frontier_expected_positive_cells"]
    ].fillna(0)
    weekly["expected_positive_cells_change"] = weekly["expected_positive_cells"].diff()
    weekly["frontier_positive_cells_change"] = weekly["frontier_positive_cells"].diff()
    stable_csv(weekly, results / "figure_03_focal_h1_time_series.csv")

    source_manifest = repo_root / "analysis/p2_operational_nowcast/results/prediction_archive_manifest.json"
    source_hash = read_expected_source_hash(repo_root)
    extraction_script = repo_root / "analysis/p7b_science_figures/scripts/extract_focal_region_atlas.py"
    manifest = {
        "artifact": "P7B_FOCAL_EXTRACTION",
        "source_phase": "P2",
        "source_archive": str(archive),
        "source_manifest": str(source_manifest),
        "source_archive_sha256_declared": source_hash,
        "source_archive_sha256_computed": sha256_file(archive),
        "output_parquet": str(focal_parquet),
        "output_parquet_sha256": sha256_file(focal_parquet),
        "filter": {
            "horizon": 1,
            **FOCAL_BBOX,
            "target_week_start": ALL_WEEKS[0],
            "target_week_end": ALL_WEEKS[-1],
        },
        "map_weeks": MAP_WEEKS,
        "focal_cells": int(len(cells)),
        "focal_rows": int(len(frame)),
        "map_rows": int(len(map_frame)),
        "columns": REQUIRED_COLUMNS,
        "domain_cells": int(len(domain_grid)),
        "support_class_status": "NOT_EXTRACTED; canonical P6 support coverage is incomplete across the P2 interval",
        "extraction_script": str(extraction_script),
        "extraction_script_sha256": sha256_file(extraction_script),
        "no_full_archive_copied": True,
    }
    (results / "focal_extraction_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"rows": len(frame), "cells": len(cells), "map_rows": len(map_frame), "parquet": str(focal_parquet)}, indent=2))


if __name__ == "__main__":
    main()
