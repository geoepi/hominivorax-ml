#!/usr/bin/env python3
"""Summarize authoritative Task-2C development metrics without touching test weeks."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path


METRICS = [
    "mean_predicted_probability", "pr_auc", "pr_auc_over_prevalence", "brier", "brier_skill",
    "bernoulli_nll", "roc_auc", "calibration_intercept", "calibration_slope",
    "joint_hurdle_nll", "zt_nb_nll", "positive_count_mae", "all_cell_mae", "theta",
]


def number(value: str) -> float | None:
    if value in {"", "None", "null"}:
        return None
    return float(value)


def summarize(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"mean": None, "median": None, "sd": None, "min": None, "max": None}
    return {
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "sd": statistics.stdev(values) if len(values) > 1 else 0.0,
        "min": min(values),
        "max": max(values),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--overall", action="store_true", help="pool folds and seeds by model/objective")
    parser.add_argument("--compact", action="store_true", help="print one tabular mean row per group")
    parser.add_argument("--regime", choices=["temporal", "spatial", "combined"])
    args = parser.parse_args()
    groups: dict[tuple[str, str, str, str], list[dict[str, str]]] = defaultdict(list)
    with args.csv_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("model") not in {"gru", "gconvgru"}:
                continue
            if args.regime and row.get("evaluation_regime") != args.regime:
                continue
            fold = "all" if args.overall else row["fold"]
            key = (row["evaluation_regime"], row["model"], row["loss_objective"], row["lambda"], fold)
            groups[key].append(row)
    output = []
    for key, rows in sorted(groups.items()):
        regime, model, objective, multiplier, fold = key
        record = {"evaluation_regime": regime, "model": model, "loss_objective": objective, "lambda": multiplier, "fold": fold if args.overall else int(fold), "n": len(rows)}
        for metric in METRICS:
            values = [number(row.get(metric, "")) for row in rows]
            record[metric] = summarize([value for value in values if value is not None and math.isfinite(value)])
        output.append(record)
    if args.compact:
        columns = ["evaluation_regime", "model", "loss_objective", "lambda", "fold", "n", "mean_predicted_probability", "pr_auc", "pr_auc_over_prevalence", "brier", "brier_skill", "bernoulli_nll", "roc_auc", "calibration_intercept", "calibration_slope", "joint_hurdle_nll", "zt_nb_nll", "positive_count_mae", "all_cell_mae", "theta"]
        print(",".join(columns))
        for record in output:
            values = []
            for column in columns:
                value = record[column]
                if isinstance(value, dict):
                    value = value["mean"]
                values.append("" if value is None else str(value))
            print(",".join(values))
    else:
        print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
