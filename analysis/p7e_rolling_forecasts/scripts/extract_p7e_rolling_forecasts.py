#!/usr/bin/env python3
"""Extract compact, aggregated P7E rolling-origin forecast data on Atlas."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq


P2_ARCHIVE = Path(
    "/project/disease_ecology/STGNN-output/p2_operational_nowcast_20261029/"
    "predictions/rolling_origin_predictions.parquet"
)
OUTPUT_ROOT = Path("/project/disease_ecology/STGNN-output/p7e_rolling_forecasts_20261030")
ORIGINS = [f"2026-W{week:02d}" for week in range(16, 37)]
HORIZONS = [1, 2, 3]
FOCAL_BBOX = {"xmin": -107.5, "xmax": -96.0, "ymin": 24.0, "ymax": 33.0}
FIELDS = [
    "origin_week", "target_week", "horizon", "model_node_id", "row", "column",
    "lon", "lat", "observed_count", "observed_positive", "p_occurrence",
    "expected_count",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_week(value: str) -> tuple[int, int]:
    year, week = value.split("-W")
    return int(year), int(week)


def add_weeks(value: str, offset: int) -> str:
    year, week = parse_week(value)
    monday = date.fromisocalendar(year, week, 1) + timedelta(weeks=offset)
    iso = monday.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def focal(frame: pd.DataFrame) -> pd.DataFrame:
    mask = (
        frame["lon"].between(FOCAL_BBOX["xmin"], FOCAL_BBOX["xmax"])
        & frame["lat"].between(FOCAL_BBOX["ymin"], FOCAL_BBOX["ymax"])
    )
    return frame.loc[mask].copy()


def atomic_csv(frame: pd.DataFrame, path: Path) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    frame.to_csv(temporary, index=False)
    temporary.replace(path)


def main() -> None:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    fields = set(FIELDS)
    table = pq.read_table(
        P2_ARCHIVE,
        columns=FIELDS,
        filters=[("origin_week", "in", ORIGINS), ("horizon", "in", HORIZONS)],
    )
    frame = focal(table.to_pandas())
    missing = sorted(fields.difference(frame.columns))
    if missing:
        raise RuntimeError(f"missing source fields: {missing}")

    expected_rows = len(ORIGINS) * len(HORIZONS) * 1689
    coverage = []
    occurrence_rows = []
    count_rows = []
    for origin in ORIGINS:
        for horizon in HORIZONS:
            subset = frame[(frame["origin_week"] == origin) & (frame["horizon"] == horizon)].copy()
            if subset["model_node_id"].nunique() != 1689 or len(subset) != 1689:
                raise RuntimeError(f"incomplete focal coverage for {origin}, h={horizon}")
            target_values = sorted(subset["target_week"].astype(str).unique())
            expected_target = add_weeks(origin, horizon)
            if target_values != [expected_target]:
                raise RuntimeError(f"chronology mismatch for {origin}, h={horizon}: {target_values}")
            observed_positive = float((subset["observed_positive"] > 0).sum())
            expected_positive = float(subset["p_occurrence"].sum())
            observed_count = float(subset["observed_count"].sum())
            expected_count = float(subset["expected_count"].sum())
            occurrence_rows.append({
                "issue_week": origin, "target_week": expected_target, "horizon": horizon,
                "observed_positive_cells": observed_positive,
                "expected_positive_cells": expected_positive,
                "forecast_error": expected_positive - observed_positive,
                "absolute_error": abs(expected_positive - observed_positive),
                "relative_error": ((expected_positive - observed_positive) / observed_positive) if observed_positive else None,
            })
            count_rows.append({
                "issue_week": origin, "target_week": expected_target, "horizon": horizon,
                "observed_total_count": observed_count, "expected_total_count": expected_count,
                "forecast_error": expected_count - observed_count,
                "absolute_error": abs(expected_count - observed_count),
                "relative_error": ((expected_count - observed_count) / observed_count) if observed_count else None,
            })
            coverage.append({
                "issue_week": origin, "target_week": expected_target, "horizon": horizon,
                "focal_rows": int(len(subset)), "focal_cells": int(subset["model_node_id"].nunique()),
            })

    target_cell = frame[["target_week", "model_node_id", "observed_positive", "observed_count"]].copy()
    consistency = target_cell.groupby(["target_week", "model_node_id"], as_index=False).agg(
        positive_n=("observed_positive", "nunique"), count_n=("observed_count", "nunique")
    )
    if int(consistency[["positive_n", "count_n"]].max().max()) != 1:
        raise RuntimeError("observed outcomes are inconsistent across repeated archive records")
    unique_observed = target_cell.drop_duplicates(["target_week", "model_node_id"])
    history = (
        unique_observed.groupby("target_week", as_index=False)
        .agg(
            observed_positive_cells=("observed_positive", lambda x: int((x > 0).sum())),
            observed_total_count=("observed_count", "sum"),
            focal_cells=("model_node_id", "nunique"),
        )
        .sort_values("target_week")
    )
    if not set(history["focal_cells"]) == {1689}:
        raise RuntimeError("observed history does not have complete 1,689-cell coverage")

    occurrence = pd.DataFrame(occurrence_rows).sort_values(["issue_week", "horizon"])
    counts = pd.DataFrame(count_rows).sort_values(["issue_week", "horizon"])
    coverage_frame = pd.DataFrame(coverage).sort_values(["issue_week", "horizon"])
    for name, value in {
        "rolling_occurrence_forecasts.csv": occurrence,
        "observed_occurrence_history.csv": history,
        "rolling_count_forecasts.csv": counts,
        "rolling_forecast_coverage.csv": coverage_frame,
    }.items():
        atomic_csv(value, OUTPUT_ROOT / name)

    manifest = {
        "source_archive": str(P2_ARCHIVE), "source_archive_sha256": sha256(P2_ARCHIVE),
        "source_fields": FIELDS, "focal_bbox": FOCAL_BBOX, "focal_cells": 1689,
        "origins": ORIGINS, "horizons": HORIZONS, "forecast_row_count": int(len(occurrence)),
        "expected_source_cell_rows": expected_rows,
        "history_start": str(history["target_week"].min()), "history_end": str(history["target_week"].max()),
        "history_row_count": int(len(history)), "target_week_range": sorted(occurrence["target_week"].unique().tolist()),
        "aggregation": {
            "observed_positive_cells": "sum(observed_positive > 0)",
            "expected_positive_cells": "sum(p_occurrence)",
            "observed_total_count": "sum(observed_count)",
            "expected_total_count": "sum(expected_count)",
        },
        "outputs": {}, "scientific_status": "bounded descriptive aggregation; no model fitting or scientific transformation",
        "uncertainty_status": "NOT_SUPPORTED_BY_CURRENT_CANONICAL_ARTIFACTS",
    }
    for name in ["rolling_occurrence_forecasts.csv", "observed_occurrence_history.csv", "rolling_count_forecasts.csv", "rolling_forecast_coverage.csv"]:
        manifest["outputs"][name] = {"path": str(OUTPUT_ROOT / name), "sha256": sha256(OUTPUT_ROOT / name)}
    manifest_path = OUTPUT_ROOT / "rolling_forecast_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, sort_keys=True))


if __name__ == "__main__":
    main()
