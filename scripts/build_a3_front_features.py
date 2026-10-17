#!/usr/bin/env python3
"""Build horizon-general causal Structured A3 front/history features.

The positive-node history is constructed from the refreshed Task 2E source
classification and passed to the validated Task 3A descriptor algorithm.  The
output is production data, not a model-development rerun: no candidate model,
penalty, theta, or scaling parameter is estimated here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

SCRIPT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_ROOT))


NODE_COUNT = 10_037
RESPONSE_START = "2025-W01"
HISTORY_FEATURES = [
    "distance_to_any_prior_positive_log1p",
    "distance_to_prev4_positive_log1p",
    "weeks_since_detection_within_50km_log1p",
    "any_prior_positive_available",
    "prev4_positive_available",
    "detection_within_50km_ever_available",
]
RAW_FEATURES = [
    "distance_to_any_prior_positive_km",
    "distance_to_prev4_positive_km",
    "weeks_since_detection_within_50km",
]
REQUIRED_COLUMNS = {
    "week",
    "week_index",
    "model_node_id",
    "canonical_node_id",
    "history_cutoff_week",
    *HISTORY_FEATURES,
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def week_tuple(value: str) -> tuple[int, int]:
    year, week = str(value).split("-W")
    return int(year), int(week)


def iso_week_start(value: str) -> date:
    year, week = week_tuple(value)
    return date.fromisocalendar(year, week, 1)


def require_contiguous_weeks(labels: list[str]) -> None:
    if not labels:
        raise RuntimeError("the environmental week table is empty")
    starts = [iso_week_start(label) for label in labels]
    expected = [f"{start.isocalendar().year}-W{start.isocalendar().week:02d}" for start in starts]
    if labels != expected:
        raise RuntimeError("week labels are not canonical ISO weeks")
    if any((right - left).days != 7 for left, right in zip(starts, starts[1:])):
        raise RuntimeError("week table contains a gap or duplicate ISO week")


def jsonable(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (date, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value


def validate_front_features(frame: pd.DataFrame, response_weeks: list[str], node_count: int = NODE_COUNT) -> dict[str, Any]:
    missing = REQUIRED_COLUMNS.difference(frame.columns)
    if missing:
        raise RuntimeError(f"causal front feature output is missing columns: {sorted(missing)}")
    expected_rows = len(response_weeks) * node_count
    if len(frame) != expected_rows:
        raise RuntimeError(f"causal front feature row count is {len(frame)}, expected {expected_rows}")
    ordered = frame.sort_values(["week_index", "model_node_id"]).reset_index(drop=True)
    expected_week_index = np.repeat(np.arange(len(response_weeks), dtype=np.int64), node_count)
    expected_node_id = np.tile(np.arange(node_count, dtype=np.int64), len(response_weeks))
    if not np.array_equal(ordered["week_index"].to_numpy(np.int64), expected_week_index):
        raise RuntimeError("causal front features are not in canonical week order")
    if not np.array_equal(ordered["model_node_id"].to_numpy(np.int64), expected_node_id):
        raise RuntimeError("causal front features are not in canonical node order")
    if ordered[["week", "model_node_id"]].duplicated().any():
        raise RuntimeError("duplicate causal front node/week rows")
    labels = ordered["week"].astype(str).tolist()[::node_count]
    if labels != response_weeks:
        raise RuntimeError("causal front feature week labels do not match the response bundle")
    cutoffs = ordered["history_cutoff_week"]
    missing_cutoffs = int(cutoffs.isna().sum() + (cutoffs.astype(str).str.strip() == "").sum())
    same_or_future = 0
    for week, cutoff in zip(ordered["week"].astype(str), cutoffs.astype("string")):
        if pd.isna(cutoff) or str(cutoff).strip() == "":
            continue
        try:
            if week_tuple(str(cutoff)) >= week_tuple(week):
                same_or_future += 1
        except ValueError:
            same_or_future += 1
    if missing_cutoffs:
        raise RuntimeError(f"causal front features contain {missing_cutoffs} missing history cutoffs")
    if same_or_future:
        raise RuntimeError(f"causal front features contain {same_or_future} same-week/future history uses")
    duplicate_count = int(ordered[["week", "model_node_id"]].duplicated().sum())
    numeric = ordered[HISTORY_FEATURES].to_numpy(np.float64)
    nonfinite = int((~np.isfinite(numeric)).sum())
    if nonfinite:
        raise RuntimeError(f"causal front features contain {nonfinite} non-finite production predictor values")
    if not set(ordered["any_prior_positive_available"].unique()).issubset({0, 1}):
        raise RuntimeError("any_prior_positive_available is not binary")
    if not set(ordered["prev4_positive_available"].unique()).issubset({0, 1}):
        raise RuntimeError("prev4_positive_available is not binary")
    if not set(ordered["detection_within_50km_ever_available"].unique()).issubset({0, 1}):
        raise RuntimeError("detection_within_50km_ever_available is not binary")
    return {
        "status": "PASS",
        "rows": int(len(ordered)),
        "weeks": int(len(response_weeks)),
        "nodes": int(node_count),
        "duplicate_node_week_rows": duplicate_count,
        "missing_history_cutoff_rows": missing_cutoffs,
        "same_week_or_future_history_uses": same_or_future,
        "nonfinite_predictor_values": nonfinite,
        "history_cutoff_rule": "history_cutoff_week < week for every response node/week",
    }


def _source_counts(classification: pd.DataFrame, week_index: dict[str, int], node_count: int) -> np.ndarray:
    required = {"iso_week", "model_node_id", "revised_domain_membership"}
    missing = required.difference(classification.columns)
    if missing:
        raise RuntimeError(f"observation classification is missing columns: {sorted(missing)}")
    selected = classification.loc[
        classification["revised_domain_membership"].astype(bool)
        & classification["iso_week"].astype("string").isin(week_index.keys())
        & classification["model_node_id"].notna(),
        ["iso_week", "model_node_id"],
    ].copy()
    selected["week_index"] = selected["iso_week"].astype(str).map(week_index)
    selected["model_node_id"] = selected["model_node_id"].astype(int)
    if ((selected["model_node_id"] < 0) | (selected["model_node_id"] >= node_count)).any():
        raise RuntimeError("observation classification contains an out-of-range model node")
    counts = np.zeros((len(week_index), node_count), dtype=np.int32)
    grouped = selected.groupby(["week_index", "model_node_id"], sort=False).size()
    for (week, node), value in grouped.items():
        counts[int(week), int(node)] = int(value)
    return counts


def build_front_frame(model_output: Path, response_start: str = RESPONSE_START, response_end: str | None = None) -> tuple[pd.DataFrame, list[str], dict[str, Any]]:
    # Import the validated spatial descriptor implementation only when the
    # production build is requested. This keeps the pure leakage validator
    # usable in lightweight contract-test environments.
    from run_task3a_v2_audit import causal_front_descriptors

    raw = model_output / "raw"
    manifest_path = model_output / "manifests" / "revised_production_manifest.json"
    classification_path = model_output / "diagnostics" / "updated_observation_classification.parquet"
    nodes_path = raw / "nodes.parquet"
    weeks_path = raw / "weeks.parquet"
    for path in (manifest_path, classification_path, nodes_path, weeks_path):
        if not path.exists():
            raise RuntimeError(f"required production artifact is missing: {path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    nodes = pd.read_parquet(nodes_path).sort_values("model_node_id").reset_index(drop=True)
    required_nodes = {"model_node_id", "canonical_node_id", "x", "y", "lat"}
    if not required_nodes.issubset(nodes.columns):
        raise RuntimeError(f"production nodes are missing columns: {sorted(required_nodes.difference(nodes.columns))}")
    if len(nodes) != NODE_COUNT or not np.array_equal(nodes["model_node_id"].to_numpy(np.int64), np.arange(NODE_COUNT)):
        raise RuntimeError("production nodes do not preserve the canonical 10,037-node order")
    weeks = pd.read_parquet(weeks_path).sort_values("week_index").reset_index(drop=True)
    labels = weeks["iso_week"].astype(str).tolist()
    require_contiguous_weeks(labels)
    if response_start not in labels:
        raise RuntimeError(f"response start {response_start} is not present in the production week table")
    response_end = response_end or labels[-1]
    if response_end not in labels or week_tuple(response_end) < week_tuple(response_start):
        raise RuntimeError("response end is invalid or precedes the response start")
    response_indices = [index for index, label in enumerate(labels) if week_tuple(response_start) <= week_tuple(label) <= week_tuple(response_end)]
    response_weeks = [labels[index] for index in response_indices]
    classification = pd.read_parquet(classification_path)
    week_index = {label: index for index, label in enumerate(labels)}
    counts = _source_counts(classification, week_index, NODE_COUNT)
    positive_sets = [np.flatnonzero(counts[index] > 0) for index in range(len(labels))]
    state = causal_front_descriptors(
        positive_sets,
        nodes[["x", "y"]].to_numpy(float),
        nodes["lat"].to_numpy(float),
        labels,
    )
    response_state = state.loc[state["week"].astype(str).isin(response_weeks)].copy()
    response_state["response_week_index"] = response_state["week"].astype(str).map({label: index for index, label in enumerate(response_weeks)})
    response_state = response_state.sort_values(["response_week_index", "node_id"]).reset_index(drop=True)
    distance_any = response_state["distance_to_any_prior_detection_km"].to_numpy(float)
    distance_prev4 = response_state["distance_to_previous4_detection_km"].to_numpy(float)
    recency = response_state["weeks_since_any_detection_within_50km"].to_numpy(float)
    available_any = np.isfinite(distance_any)
    available_prev4 = np.isfinite(distance_prev4)
    available_recency = np.isfinite(recency)
    xy = nodes[["x", "y"]].to_numpy(float)
    distance_placeholder = float(np.hypot(np.ptp(xy[:, 0]), np.ptp(xy[:, 1])))
    if not np.isfinite(distance_placeholder) or distance_placeholder <= 0:
        distance_placeholder = 1.0
    recency_placeholder = float(len(labels) + 1)
    frame = pd.DataFrame({
        "week": response_state["week"].astype(str).to_numpy(),
        "week_index": response_state["response_week_index"].to_numpy(np.int64),
        "model_node_id": response_state["node_id"].to_numpy(np.int64),
        "canonical_node_id": nodes.loc[response_state["node_id"].to_numpy(np.int64), "canonical_node_id"].to_numpy(np.int64),
        "distance_to_any_prior_positive_km": np.where(available_any, distance_any, distance_placeholder),
        "distance_to_prev4_positive_km": np.where(available_prev4, distance_prev4, distance_placeholder),
        "weeks_since_detection_within_50km": np.where(available_recency, recency, recency_placeholder),
        "any_prior_positive_available": available_any.astype(np.int8),
        "prev4_positive_available": available_prev4.astype(np.int8),
        "detection_within_50km_ever_available": available_recency.astype(np.int8),
        "history_cutoff_week": response_state["source_history_cutoff"].astype("string").to_numpy(),
    })
    for raw_name, transformed_name in (
        ("distance_to_any_prior_positive_km", "distance_to_any_prior_positive_log1p"),
        ("distance_to_prev4_positive_km", "distance_to_prev4_positive_log1p"),
        ("weeks_since_detection_within_50km", "weeks_since_detection_within_50km_log1p"),
    ):
        frame[transformed_name] = np.log1p(np.maximum(frame[raw_name].to_numpy(float), 0.0))
    frame = frame[["week", "week_index", "model_node_id", "canonical_node_id", *RAW_FEATURES, *HISTORY_FEATURES]]
    audit = validate_front_features(frame, response_weeks)
    audit.update({
        "response_start": response_weeks[0],
        "response_end": response_weeks[-1],
        "source_observation_sha256": manifest.get("observation_source", {}).get("sha256"),
        "source_observation_path": manifest.get("observation_source", {}).get("path"),
        "source_observation_row_count": manifest.get("observation_source", {}).get("row_count"),
        "distance_placeholder_km": distance_placeholder,
        "recency_placeholder_weeks": recency_placeholder,
    })
    return frame, response_weeks, audit


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-output", type=Path, default=Path("/project/disease_ecology/STGNN-output/revised_model_data"))
    parser.add_argument("--output", type=Path, default=Path("/project/disease_ecology/STGNN-output/v2_model/front_features"))
    parser.add_argument("--response-start", default=RESPONSE_START)
    parser.add_argument("--response-end")
    args = parser.parse_args()
    frame, response_weeks, audit = build_front_frame(args.model_output, args.response_start, args.response_end)
    args.output.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(args.output / "causal_front_features.parquet", index=False)
    (args.output / "leakage_audit.json").write_text(json.dumps(jsonable(audit), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = {
        "status": "production_causal_front_features_complete",
        "response_start": response_weeks[0],
        "response_end": response_weeks[-1],
        "response_week_count": len(response_weeks),
        "node_count": NODE_COUNT,
        "predictor_order": HISTORY_FEATURES,
        "causal_rule": "history for week t uses observations strictly before week t",
        "leakage_audit": audit,
        "feature_path": str(args.output / "causal_front_features.parquet"),
        "feature_sha256": sha256_file(args.output / "causal_front_features.parquet"),
    }
    (args.output / "production_front_feature_manifest.json").write_text(json.dumps(jsonable(manifest), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(jsonable(manifest), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
