"""Create the bounded P7D focal forecast trajectory extract on Atlas."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq


P2_ARCHIVE = Path(
    "/project/disease_ecology/STGNN-output/p2_operational_nowcast_20261029/"
    "predictions/rolling_origin_predictions.parquet"
)
OUTPUT_ROOT = Path(
    "/project/disease_ecology/STGNN-output/p7d_cartography_forecast_20261030"
)
ISSUE_WEEK = "2026-W36"
HISTORY_TARGETS = [f"2026-W{week:02d}" for week in range(17, 37)]
HISTORY_ORIGINS = [f"2026-W{week:02d}" for week in range(16, 36)]
FUTURE_TARGETS = ["2026-W37", "2026-W38", "2026-W39"]
FOCAL_BBOX = {"xmin": -107.5, "xmax": -96.0, "ymin": 24.0, "ymax": 33.0}
FIELDS = [
    "origin_week", "target_week", "horizon", "model_node_id", "row", "column",
    "lon", "lat", "observed_count", "observed_positive", "p_occurrence",
    "conditional_count_mean", "expected_count", "previously_occupied",
    "prediction_frontier_class", "outcome_frontier_label",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def focal(frame: pd.DataFrame) -> pd.DataFrame:
    mask = (
        frame["lon"].between(FOCAL_BBOX["xmin"], FOCAL_BBOX["xmax"])
        & frame["lat"].between(FOCAL_BBOX["ymin"], FOCAL_BBOX["ymax"])
    )
    return frame.loc[mask].copy()


def main() -> None:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    history = pq.read_table(
        P2_ARCHIVE,
        columns=FIELDS,
        filters=[[('origin_week', 'in', HISTORY_ORIGINS), ('horizon', '==', 1)]],
    ).to_pandas()
    history = focal(history)
    history = history[history["target_week"].isin(HISTORY_TARGETS)].copy()
    history["trajectory_role"] = "observed_history"
    history["observation_status"] = "available_at_issue"

    forecast = pq.read_table(
        P2_ARCHIVE,
        columns=FIELDS,
        filters=[[('origin_week', '==', ISSUE_WEEK), ('horizon', 'in', [1, 2, 3])]],
    ).to_pandas()
    forecast = focal(forecast)
    forecast = forecast[forecast["target_week"].isin(FUTURE_TARGETS)].copy()
    forecast["trajectory_role"] = "issue_W36_forecast"
    forecast["observation_status"] = "subsequently_observed_only"

    output = pd.concat([history, forecast], ignore_index=True)
    output = output.sort_values(
        ["target_week", "trajectory_role", "horizon", "model_node_id"],
        kind="mergesort",
    ).reset_index(drop=True)
    output_path = OUTPUT_ROOT / "mexico_texas_issue_W36_forecast_trajectory.csv"
    output.to_csv(output_path, index=False)
    manifest = {
        "source_archive": str(P2_ARCHIVE),
        "source_archive_sha256": "918b33e80d352c080fcefb3d7b2a44dc29d0096b0b2e7dd6f5b017becc983170",
        "issue_week": ISSUE_WEEK,
        "history_origins": HISTORY_ORIGINS,
        "history_targets": HISTORY_TARGETS,
        "future_targets": FUTURE_TARGETS,
        "future_horizons": [1, 2, 3],
        "focal_bbox": FOCAL_BBOX,
        "focal_cells": int(output["model_node_id"].nunique()),
        "row_count": int(len(output)),
        "history_row_count": int(len(history)),
        "forecast_row_count": int(len(forecast)),
        "forecast_origin_unique": sorted(forecast["origin_week"].unique().tolist()),
        "target_horizon_alignment": forecast[["target_week", "horizon"]]
        .drop_duplicates().sort_values(["horizon", "target_week"])
        .to_dict(orient="records"),
        "output_path": str(output_path),
        "output_sha256": sha256(output_path),
        "scientific_status": "bounded descriptive extract; no model fitting or scientific transformation",
    }
    (OUTPUT_ROOT / "forecast_trajectory_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, sort_keys=True))


if __name__ == "__main__":
    main()

