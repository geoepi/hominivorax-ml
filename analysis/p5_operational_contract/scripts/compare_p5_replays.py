#!/usr/bin/env python3
"""Compare two immutable P5 historical replay outputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from p5_contract import jsonable


ALLOWED_MANIFEST_DIFFERENCES = {"run_id", "output_root", "output_path", "output_sha256", "runtime_seconds", "terminal_status", "validation_status"}


def compare(first: Path, second: Path, output: Path) -> dict[str, Any]:
    first_manifest = json.loads((first / "run_manifest.json").read_text(encoding="utf-8"))
    second_manifest = json.loads((second / "run_manifest.json").read_text(encoding="utf-8"))
    first_frame = pd.read_parquet(first / "predictions.parquet").sort_values(["target_week", "horizon", "model_node_id"], kind="mergesort").reset_index(drop=True)
    second_frame = pd.read_parquet(second / "predictions.parquet").sort_values(["target_week", "horizon", "model_node_id"], kind="mergesort").reset_index(drop=True)
    schema_equal = list(first_frame.columns) == list(second_frame.columns)
    row_count_equal = len(first_frame) == len(second_frame)
    key_columns = ["target_week", "horizon", "model_node_id"]
    keys_equal = row_count_equal and first_frame[key_columns].equals(second_frame[key_columns])
    numeric_columns = [column for column in first_frame.columns if pd.api.types.is_numeric_dtype(first_frame[column])]
    max_abs_difference = 0.0
    exact_numeric = True
    if schema_equal and row_count_equal:
        for column in numeric_columns:
            left = first_frame[column].to_numpy(float)
            right = second_frame[column].to_numpy(float)
            difference = np.nan_to_num(np.abs(left - right), nan=0.0)
            max_abs_difference = max(max_abs_difference, float(difference.max(initial=0.0)))
            exact_numeric = exact_numeric and bool(np.array_equal(left, right, equal_nan=True))
    support_equal = row_count_equal and first_frame.get("support_class", pd.Series(dtype=object)).equals(second_frame.get("support_class", pd.Series(dtype=object)))
    warning_equal = row_count_equal and first_frame.get("warning_flags", pd.Series(dtype=object)).equals(second_frame.get("warning_flags", pd.Series(dtype=object)))
    provenance_differences = []
    for key in sorted(set(first_manifest) | set(second_manifest)):
        if key in ALLOWED_MANIFEST_DIFFERENCES:
            continue
        if first_manifest.get(key) != second_manifest.get(key):
            provenance_differences.append(key)
    result = {
        "status": "PASS" if schema_equal and row_count_equal and keys_equal and exact_numeric and support_equal and warning_equal and not provenance_differences else "FAIL",
        "first_output_sha256": first_manifest.get("output_sha256"),
        "second_output_sha256": second_manifest.get("output_sha256"),
        "row_count_equal": row_count_equal,
        "schema_equal": schema_equal,
        "keys_equal": keys_equal,
        "exact_numeric_equality": exact_numeric,
        "max_abs_numeric_difference": max_abs_difference,
        "support_flags_equal": support_equal,
        "warning_flags_equal": warning_equal,
        "provenance_differences_outside_allowed_run_fields": provenance_differences,
        "allowed_manifest_differences": sorted(ALLOWED_MANIFEST_DIFFERENCES),
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "reproducibility_comparison.json").write_text(json.dumps(jsonable(result), indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--first", type=Path, required=True)
    parser.add_argument("--second", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = compare(args.first, args.second, args.output)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
