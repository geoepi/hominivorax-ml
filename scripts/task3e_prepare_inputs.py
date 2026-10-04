#!/usr/bin/env python3
"""Prepare persisted Task 3E prediction and overlay inputs.

This script does not fit a model.  It selects the already-persisted M1/0.01
historical pseudo-prospective predictions from the frozen V2-A validation
artifact, joins them to the persisted canonical node-to-raster-cell mapping,
and exports small, explicit CSV contracts for the R/terra/ggplot2 renderer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd


MODEL_ID = "STGNN-Hurdle-V2A"
SELECTED_MODEL = "M1"
SELECTED_PENALTY = 0.01
WEEKS = [f"2026-W{week:02d}" for week in range(17, 30)]
FOLD_BY_WEEK = {week: (5 if int(week[-2:]) <= 22 else 6) for week in WEEKS}
NODE_COUNT = 10037


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_sha(repo: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True
    ).strip()


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("/project/disease_ecology/STGNN-output/v2_rasters"),
    )
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[1]
    output_root = args.output_root
    input_root = output_root / "inputs"
    input_root.mkdir(parents=True, exist_ok=True)

    prediction_path = Path(
        "/project/disease_ecology/STGNN-output/v2_model/validation/validation_predictions.parquet"
    )
    nodes_path = Path(
        "/project/disease_ecology/STGNN-output/revised_model_data/raw/nodes.parquet"
    )
    weeks_path = Path(
        "/project/disease_ecology/STGNN-output/revised_model_data/raw/weeks.parquet"
    )
    targets_path = Path(
        "/project/disease_ecology/STGNN-output/revised_model_data/raw/targets_count.npy"
    )
    model_manifest_path = Path(
        "/project/disease_ecology/STGNN-output/v2_prospective/manifests/"
        "v2a_frozen_specification_manifest.json"
    )
    task3b_decisions_path = Path(
        "/project/disease_ecology/STGNN-output/v2_model/metrics/task3b_decisions.json"
    )

    for path in [
        prediction_path,
        nodes_path,
        weeks_path,
        targets_path,
        model_manifest_path,
        task3b_decisions_path,
    ]:
        if not path.exists():
            raise FileNotFoundError(path)

    model_manifest = json.loads(model_manifest_path.read_text(encoding="utf-8"))
    decisions = json.loads(task3b_decisions_path.read_text(encoding="utf-8"))
    if model_manifest.get("model_id") != MODEL_ID:
        raise RuntimeError("frozen model manifest is not STGNN-Hurdle-V2A")
    if model_manifest.get("candidate") != SELECTED_MODEL:
        raise RuntimeError("frozen model candidate is not M1")
    if decisions.get("selected_penalties", {}).get(SELECTED_MODEL) != SELECTED_PENALTY:
        raise RuntimeError("Task-3B selected penalty does not match 0.01")
    if decisions.get("v2a_decision") != "V2-A ADVANCES":
        raise RuntimeError("Task-3B decision does not authorize V2-A outputs")

    predictions = pd.read_parquet(prediction_path)
    required_prediction_columns = {
        "model",
        "penalty",
        "fold",
        "fold_label",
        "week",
        "model_node_id",
        "predicted_probability",
        "predicted_conditional_mean",
        "predicted_unconditional_mean",
    }
    missing = required_prediction_columns.difference(predictions.columns)
    if missing:
        raise RuntimeError(f"prediction artifact is missing columns: {sorted(missing)}")

    selected = predictions.loc[
        (predictions["model"] == SELECTED_MODEL)
        & np.isclose(predictions["penalty"].astype(float), SELECTED_PENALTY)
        & predictions["week"].astype(str).isin(WEEKS)
    ].copy()
    selected["week"] = selected["week"].astype(str)
    selected["model_node_id"] = selected["model_node_id"].astype(int)
    selected = selected.loc[
        selected.apply(lambda row: int(row["fold"]) == FOLD_BY_WEEK[row["week"]], axis=1)
    ].copy()
    if selected["fold_label"].astype(str).nunique() != 1:
        raise RuntimeError("selected prediction rows have inconsistent fold labels")
    expected_rows = len(WEEKS) * NODE_COUNT
    if len(selected) != expected_rows:
        raise RuntimeError(f"selected prediction row count {len(selected)} != {expected_rows}")
    if selected.duplicated(["week", "model_node_id"]).any():
        raise RuntimeError("selected prediction artifact has duplicate week-node rows")
    for week in WEEKS:
        week_rows = selected.loc[selected["week"] == week]
        if len(week_rows) != NODE_COUNT:
            raise RuntimeError(f"selected prediction count is incomplete for {week}")
        if week_rows["fold"].astype(int).nunique() != 1 or int(week_rows["fold"].iloc[0]) != FOLD_BY_WEEK[week]:
            raise RuntimeError(f"selected prediction fold is incorrect for {week}")

    nodes = pd.read_parquet(nodes_path).sort_values("model_node_id").reset_index(drop=True)
    required_node_columns = {
        "model_node_id",
        "canonical_node_id",
        "raster_cell",
        "row",
        "column",
        "x",
        "y",
        "lon",
        "lat",
        "country_or_domain_region",
    }
    missing = required_node_columns.difference(nodes.columns)
    if missing:
        raise RuntimeError(f"node artifact is missing columns: {sorted(missing)}")
    if len(nodes) != NODE_COUNT or not np.array_equal(
        nodes["model_node_id"].to_numpy(), np.arange(NODE_COUNT)
    ):
        raise RuntimeError("canonical node order/count contract failed")
    if nodes["raster_cell"].duplicated().any():
        raise RuntimeError("canonical raster-cell mapping is not unique")

    mapping_columns = [
        "canonical_node_id",
        "raster_cell",
        "row",
        "column",
        "x",
        "y",
        "lon",
        "lat",
        "country_or_domain_region",
    ]
    selected = selected.drop(
        columns=[column for column in mapping_columns if column in selected.columns]
    )
    selected = selected.merge(
        nodes[
            [
                "model_node_id",
                "canonical_node_id",
                "raster_cell",
                "row",
                "column",
                "x",
                "y",
                "lon",
                "lat",
                "country_or_domain_region",
            ]
        ],
        on="model_node_id",
        how="left",
        validate="many_to_one",
    )
    if selected["raster_cell"].isna().any():
        raise RuntimeError("prediction-to-node mapping is incomplete")
    if not np.isfinite(
        selected[
            [
                "predicted_probability",
                "predicted_conditional_mean",
                "predicted_unconditional_mean",
            ]
        ].to_numpy(float)
    ).all():
        raise RuntimeError("selected predictions contain non-finite values")
    if (
        (selected["predicted_probability"] < 0).any()
        or (selected["predicted_probability"] > 1).any()
        or (selected["predicted_unconditional_mean"] < 0).any()
        or (selected["predicted_conditional_mean"] < 0).any()
    ):
        raise RuntimeError("selected prediction ranges failed")

    prediction_columns = [
        "week",
        "model_node_id",
        "canonical_node_id",
        "raster_cell",
        "row",
        "column",
        "x",
        "y",
        "lon",
        "lat",
        "country_or_domain_region",
        "predicted_probability",
        "predicted_conditional_mean",
        "predicted_unconditional_mean",
    ]
    selected[prediction_columns].sort_values(["week", "model_node_id"]).to_csv(
        input_root / "task3e_predictions.csv", index=False, float_format="%.17g"
    )

    week_table = pd.read_parquet(weeks_path).reset_index(drop=True)
    week_positions = {str(value): index for index, value in enumerate(week_table["iso_week"])}
    missing_weeks = sorted(set(WEEKS).difference(week_positions))
    if missing_weeks:
        raise RuntimeError(f"requested weeks missing from canonical week table: {missing_weeks}")
    targets = np.load(targets_path, mmap_mode="r")
    if targets.ndim != 2 or targets.shape[1] != NODE_COUNT or targets.shape[0] != len(week_table):
        raise RuntimeError(f"target count array shape failed: {targets.shape}")

    observation_frames = []
    for week in WEEKS:
        counts = np.asarray(targets[week_positions[week]], dtype=np.int64)
        positive_nodes = np.flatnonzero(counts > 0).astype(int)
        frame = nodes.loc[
            nodes["model_node_id"].isin(positive_nodes),
            ["model_node_id", "canonical_node_id", "lon", "lat", "country_or_domain_region"],
        ].copy()
        frame.insert(0, "week", week)
        frame["observed_count"] = frame["model_node_id"].map(
            dict(zip(positive_nodes.tolist(), counts[positive_nodes].tolist()))
        )
        observation_frames.append(frame)
    observations = pd.concat(observation_frames, ignore_index=True)
    observations.to_csv(input_root / "task3e_observations.csv", index=False, float_format="%.17g")

    manifest = {
        "model_id": MODEL_ID,
        "candidate": SELECTED_MODEL,
        "penalty": SELECTED_PENALTY,
        "prediction_selection": {
            "artifact": str(prediction_path),
            "fold_by_week": FOLD_BY_WEEK,
            "fold_label": str(selected["fold_label"].iloc[0]),
            "interpretation": "persisted historical pseudo-prospective validation predictions; no refit",
        },
        "weeks": WEEKS,
        "node_count": NODE_COUNT,
        "prediction_rows": int(len(selected)),
        "observation_overlay_rows": int(len(observations)),
        "variables": [
            "predicted_probability",
            "predicted_unconditional_mean",
            "predicted_conditional_mean",
        ],
        "source_artifacts": {
            "prediction": {"path": str(prediction_path), "sha256": sha256_file(prediction_path)},
            "nodes": {"path": str(nodes_path), "sha256": sha256_file(nodes_path)},
            "weeks": {"path": str(weeks_path), "sha256": sha256_file(weeks_path)},
            "targets_count": {"path": str(targets_path), "sha256": sha256_file(targets_path)},
            "frozen_model_manifest": {
                "path": str(model_manifest_path),
                "sha256": sha256_file(model_manifest_path),
            },
        },
        "git_sha": git_sha(repo),
        "created_utc": pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"),
        "output_files": {
            "predictions": str(input_root / "task3e_predictions.csv"),
            "observations": str(input_root / "task3e_observations.csv"),
        },
    }
    write_json(input_root / "task3e_input_manifest.json", manifest)
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
