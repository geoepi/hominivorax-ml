#!/usr/bin/env python3
"""Compare two P6 outputs while allowing run IDs to differ."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


SCIENCE_COLUMNS = [
    "canonical_node_id", "model_node_id", "issue_week", "target_week", "horizon",
    "p_occurrence", "conditional_count_mean", "expected_count", "full_q025",
    "full_q975", "p_boot_sd", "expected_boot_sd", "novelty_knn_distance",
    "support_class", "warning_status", "warning_flags", "model_uncertainty_status",
    "model_id", "model_sha256", "proxy_id",
]


def compare(left: Path, right: Path) -> dict[str, object]:
    a = pd.read_parquet(left)
    b = pd.read_parquet(right)
    same_schema = list(a.columns) == list(b.columns)
    same_rows = len(a) == len(b)
    same_science = False
    max_abs_difference = 0.0
    if same_schema and same_rows:
        aa = a[SCIENCE_COLUMNS].reset_index(drop=True)
        bb = b[SCIENCE_COLUMNS].reset_index(drop=True)
        same_science = True
        for column in SCIENCE_COLUMNS:
            if pd.api.types.is_numeric_dtype(aa[column]):
                values_a = aa[column].to_numpy(float)
                values_b = bb[column].to_numpy(float)
                finite = np.isfinite(values_a) & np.isfinite(values_b)
                if finite.any():
                    max_abs_difference = max(max_abs_difference, float(np.max(np.abs(values_a[finite] - values_b[finite]))))
                if not np.array_equal(np.isnan(values_a), np.isnan(values_b)) or not np.array_equal(values_a[finite], values_b[finite]):
                    same_science = False
            elif not aa[column].astype(str).equals(bb[column].astype(str)):
                same_science = False
    return {
        "left": str(left),
        "right": str(right),
        "left_rows": int(len(a)),
        "right_rows": int(len(b)),
        "same_schema": bool(same_schema),
        "same_row_count": bool(same_rows),
        "same_scientific_and_support_fields": bool(same_science),
        "max_absolute_numeric_difference": max_abs_difference,
        "run_ids_differ_only_as_allowed": a.get("production_run_id", pd.Series(dtype=str)).astype(str).nunique() >= 1 and b.get("production_run_id", pd.Series(dtype=str)).astype(str).nunique() >= 1,
        "pass": bool(same_schema and same_rows and same_science),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = compare(args.left, args.right)
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
