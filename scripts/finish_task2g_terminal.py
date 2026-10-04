#!/usr/bin/env python3
"""Finish Task 2G reporting after a completed one-time terminal score.

This utility is only for a reporting-stage failure after terminal predictions
and metrics have already been persisted. It never fits a model, reads raw
terminal targets, or recalculates terminal metrics.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

SCRIPT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_ROOT))
from run_task2e_baselines import write_csv, write_json  # noqa: E402
from run_task2f_structured import build_feature_arrays, load_inputs  # noqa: E402
from run_task2g_terminal import (  # noqa: E402
    EXPECTED_NODE_COUNT,
    TERMINAL_INDICES,
    generate_maps,
    sha256_file,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-output", type=Path, required=True)
    parser.add_argument("--terminal-output", type=Path, required=True)
    args = parser.parse_args()
    output = args.terminal_output
    unlock_path = output / "manifests" / "terminal_unlock.json"
    predictions_path = output / "predictions" / "terminal_predictions.parquet"
    metrics_path = output / "metrics" / "terminal_metrics.json"
    if not unlock_path.exists() or not predictions_path.exists() or not metrics_path.exists():
        raise RuntimeError("terminal reporting cannot be finalized because required persisted outputs are missing")
    if (output / "manifests" / "terminal_evaluation_complete.json").exists():
        raise RuntimeError("Task 2G reporting is already finalized")

    data = load_inputs(args.model_output)
    frame = pd.read_parquet(predictions_path)
    expected_rows = len(TERMINAL_INDICES) * EXPECTED_NODE_COUNT
    required = {"terminal_week_index", "node_id", "observed_count", "predicted_occurrence_probability"}
    if len(frame) != expected_rows or not required.issubset(frame.columns):
        raise AssertionError("persisted terminal prediction schema/row count is invalid")
    frame = frame.sort_values(["terminal_week_index", "node_id"]).reset_index(drop=True)
    if frame["terminal_week_index"].drop_duplicates().tolist() != TERMINAL_INDICES:
        raise AssertionError("persisted terminal week indices are incomplete or reordered")
    counts = frame["observed_count"].to_numpy(np.int64).reshape(len(TERMINAL_INDICES), EXPECTED_NODE_COUNT)
    probability = frame["predicted_occurrence_probability"].to_numpy(float).reshape(len(TERMINAL_INDICES), EXPECTED_NODE_COUNT)
    generated_maps = generate_maps(data, counts, probability, output)

    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    unlock = json.loads(unlock_path.read_text(encoding="utf-8"))
    complete = {
        "status": "completed_terminal_evaluation",
        "model": metrics["model"],
        "penalty": metrics["penalty"],
        "freeze_manifest_sha256": unlock["model_freeze_manifest_sha256"],
        "terminal_unlock_timestamp_utc": unlock["terminal_unlock_timestamp_utc"],
        "terminal_scoring_timestamp_utc": metrics["terminal_scoring_timestamp_utc"],
        "generalization_classification": metrics["generalization_classification"],
        "us_transfer_classification": metrics["us_transfer_classification"],
        "primary_model_changed_after_terminal_scoring": False,
        "secondary_model_scored": False,
        "terminal_target_values_accessed": True,
        "reporting_recovery": "maps and final checksums completed from persisted terminal predictions; no refit or terminal metric rescore",
        "generated_maps": generated_maps,
        "required_outputs": [
            "predictions/terminal_predictions.parquet",
            "metrics/terminal_metrics.json",
            "regional/terminal_regional_metrics.csv",
            "metrics/terminal_weekly_metrics.csv",
            "us_transfer/terminal_us_positive_ranks.csv",
            "metrics/terminal_latitude_metrics.csv",
            "metrics/terminal_calibration.csv",
        ],
    }
    write_json(output / "manifests" / "terminal_evaluation_complete.json", complete)
    checksums = []
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name != "terminal_output_checksums.csv":
            checksums.append({"path": str(path.relative_to(output)), "sha256": sha256_file(path)})
    write_csv(output / "manifests" / "terminal_output_checksums.csv", checksums)
    print(json.dumps({"status": complete["status"], "maps": len(generated_maps), "refit": False, "rescore": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
