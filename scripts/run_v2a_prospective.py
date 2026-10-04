#!/usr/bin/env python3
"""Sequential, leakage-safe prospective harness for frozen STGNN-Hurdle-V2A.

The forecast path never reads the forecast week's outcomes.  The score path
only reads outcomes after an immutable forecast and checksum have been
verified.  Historical sandbox runs are explicitly separated from the
production prospective registry and ledger with ``test_mode=true``.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import shutil
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.special import expit, gammaln

SCRIPT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_ROOT))
from run_task2e_baselines import safe_metrics  # noqa: E402
from run_task3a_v2_audit import causal_front_descriptors  # noqa: E402


MODEL_ID = "STGNN-Hurdle-V2A"
FREEZE_DATE = "2026-10-03"
NODE_COUNT = 10037
SOURCE_HISTORY_START = "2024-W01"
DISTANCE_PLACEHOLDER_KM = None
RECENCY_PLACEHOLDER_WEEKS = 134.0
LATITUDE_BANDS = [
    ("lt20N", -np.inf, 20.0),
    ("20_25N", 20.0, 25.0),
    ("25_30N", 25.0, 30.0),
    ("30_35N", 30.0, 35.0),
    ("35_40N", 35.0, 40.0),
]
ELIGIBILITY_STATES = {
    "prospective_eligible",
    "retrospective_only",
    "environment_not_available",
    "outcome_already_available",
    "availability_uncertain",
}
OUTCOME_MATURITY = {"provisional", "mature"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def jsonable(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(jsonable(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def iso_date(week: str) -> date:
    year, number = (int(part) for part in week.split("-W"))
    return date.fromisocalendar(year, number, 1)


def previous_week(week: str) -> str:
    previous = iso_date(week) - timedelta(weeks=1)
    iso = previous.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def week_range(start: str, end: str) -> list[str]:
    current = iso_date(start)
    finish = iso_date(end)
    result = []
    while current <= finish:
        iso = current.isocalendar()
        result.append(f"{iso.year}-W{iso.week:02d}")
        current += timedelta(weeks=1)
    return result


def week_end_timestamp(week: str) -> str:
    end = iso_date(week) + timedelta(days=6, hours=23, minutes=59, seconds=59)
    return datetime.combine(end, datetime.max.time(), tzinfo=timezone.utc).isoformat(timespec="seconds")


def timestamp_or_none(value: Any) -> str | None:
    if value is None or str(value).strip().lower() in {"", "none", "nan", "nat", "unknown"}:
        return None
    return parse_timestamp(str(value)).isoformat(timespec="seconds")


def week_start_timestamp(week: str) -> str:
    return datetime.combine(iso_date(week), datetime.min.time(), tzinfo=timezone.utc).isoformat(timespec="seconds")


def score_version(value: Any) -> int:
    version = int(value)
    if version < 1:
        raise ValueError("score version must be a positive integer")
    return version


def effective_history_mode(args: argparse.Namespace) -> str:
    if args.history_mode:
        return args.history_mode
    return "event_causal" if args.test_mode else "availability_causal"


def require_frozen_model(output: Path) -> tuple[dict[str, Any], dict[str, Any], str, str]:
    manifest_path = output / "manifests" / "v2a_frozen_specification_manifest.json"
    checksum_path = Path(str(manifest_path) + ".sha256")
    model_path = output / "model" / "v2a_frozen_model.json"
    if not manifest_path.exists() or not checksum_path.exists() or not model_path.exists():
        raise RuntimeError("frozen V2-A model artifacts are missing")
    expected = checksum_path.read_text(encoding="utf-8").split()[0]
    actual = sha256_file(manifest_path)
    if expected != actual:
        raise RuntimeError("frozen model manifest checksum mismatch")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    model = json.loads(model_path.read_text(encoding="utf-8"))
    if manifest.get("model_id") != MODEL_ID or model.get("model_id") != MODEL_ID:
        raise RuntimeError("frozen model identifier mismatch")
    if manifest.get("feature_count") != 30 or len(manifest.get("feature_order", [])) != 30:
        raise RuntimeError("frozen feature count/order mismatch")
    if float(manifest.get("penalty")) != 0.01 or float(model.get("penalty")) != 0.01:
        raise RuntimeError("frozen penalty mismatch")
    if manifest.get("freeze_date") != FREEZE_DATE:
        raise RuntimeError("frozen date mismatch")
    if len(model.get("occurrence_coefficients", [])) != 31 or len(model.get("count_coefficients", [])) != 31:
        raise RuntimeError("frozen coefficient width mismatch")
    if not np.isfinite(np.asarray(model["occurrence_coefficients"], dtype=float)).all() or not np.isfinite(np.asarray(model["count_coefficients"], dtype=float)).all() or float(model["theta"]) <= 0:
        raise RuntimeError("frozen coefficients or theta are invalid")
    input_manifest_path = output / "manifests" / "prospective_input_manifest.json"
    if not input_manifest_path.exists():
        raise RuntimeError("prospective input manifest is missing")
    return manifest, model, actual, sha256_file(input_manifest_path)


def load_predictor_bundle(bundle: Path) -> dict[str, Any]:
    raw = bundle / "raw"
    dynamic = np.asarray(np.load(raw / "dynamic_features.npy", mmap_mode="r"), dtype=float)
    static = np.asarray(np.load(raw / "static_features.npy", mmap_mode="r"), dtype=float)
    weeks = pd.read_parquet(raw / "weeks.parquet")
    calendar = pd.read_parquet(raw / "calendar_features.parquet")[["week_sin", "week_cos"]].to_numpy(float)
    nodes = pd.read_parquet(raw / "nodes.parquet").sort_values("model_node_id").reset_index(drop=True)
    if dynamic.ndim != 3 or dynamic.shape[1:] != (NODE_COUNT, 12):
        raise RuntimeError(f"dynamic environmental input contract failed: {dynamic.shape}")
    if static.shape != (NODE_COUNT, 10) or calendar.shape != (len(weeks), 2):
        raise RuntimeError("static/calendar input contract failed")
    if len(nodes) != NODE_COUNT or not np.array_equal(nodes["model_node_id"].to_numpy(), np.arange(NODE_COUNT)):
        raise RuntimeError("node-order input contract failed")
    if not np.isfinite(dynamic).all() or not np.isfinite(static).all() or not np.isfinite(calendar).all():
        raise RuntimeError("non-finite current-week predictor input")
    labels = weeks["iso_week"].astype(str).tolist()
    return {"bundle": bundle, "dynamic": dynamic, "static": static, "calendar": calendar, "weeks": labels, "nodes": nodes}


def ensure_status_fields(output: Path) -> dict[str, Any]:
    path = output / "prospective_status.json"
    status = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    status.setdefault("model_id", MODEL_ID)
    status.setdefault("operational_mode", "delayed_prospective_nowcast")
    status.setdefault("environment_latency_status", "uncertain")
    status.setdefault("observation_latency_status", "uncertain")
    status.setdefault("latest_eligible_nowcast_week", None)
    status.setdefault("genuine_prospective_forecasts", 0)
    status.setdefault("genuine_prospective_scored_weeks", 0)
    status.setdefault("latest_score_version", None)
    status.setdefault("evaluation_status", "HARNESS READY — AWAITING ELIGIBLE NOWCAST WINDOW")
    write_json(path, status)
    return status


def source_history_schema() -> list[str]:
    return [
        "source_path", "sha256", "row_count", "first_seen_timestamp", "file_timestamp",
        "minimum_date", "maximum_date", "new_rows", "new_current_week_rows",
        "historical_backfill_rows", "source_status",
    ]


def ensure_source_history(output: Path, root: Path) -> pd.DataFrame:
    path = root / "source_history" / "observation_source_history.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        frame = pd.read_parquet(path)
    else:
        legacy = output / "manifests" / "source_history_manifest.csv"
        rows = []
        if legacy.exists():
            old = pd.read_csv(legacy)
            for _, row in old.iterrows():
                file_timestamp = row.get("file_timestamp", row.get("file_mtime_utc"))
                rows.append({
                    "source_path": row.get("source_path", row.get("file_path")),
                    "sha256": row.get("sha256"),
                    "row_count": row.get("row_count"),
                    "first_seen_timestamp": file_timestamp,
                    "file_timestamp": file_timestamp,
                    "minimum_date": row.get("minimum_date"),
                    "maximum_date": row.get("maximum_date"),
                    "new_rows": 0,
                    "new_current_week_rows": 0,
                    "historical_backfill_rows": 0,
                    "source_status": row.get("status", "historical_initialization_not_prospective"),
                })
        frame = pd.DataFrame(rows, columns=source_history_schema())
        frame.to_parquet(path, index=False)
    for column in source_history_schema():
        if column not in frame.columns:
            frame[column] = 0 if column in {"new_rows", "new_current_week_rows", "historical_backfill_rows"} else None
    return frame[source_history_schema()].sort_values(["first_seen_timestamp", "sha256"], na_position="last").reset_index(drop=True)


def bundle_inventory(predictor: dict[str, Any], forecast_week: str, environment_timestamp: str | None, availability_status: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    raw = predictor["bundle"] / "raw"
    files = [raw / name for name in ["dynamic_features.npy", "static_features.npy", "calendar_features.parquet", "weeks.parquet", "nodes.parquet"]]
    if not all(path.exists() for path in files):
        raise RuntimeError("environment bundle files are incomplete")
    file_hashes = [f"{path.name}:{sha256_file(path)}" for path in files]
    bundle_sha = hashlib.sha256("|".join(file_hashes).encode("utf-8")).hexdigest()
    file_timestamp = max(datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc) for path in files).isoformat(timespec="seconds")
    complete = 12 if predictor["dynamic"].shape[2] == 12 else int(predictor["dynamic"].shape[2])
    rows = []
    verified_timestamp = timestamp_or_none(environment_timestamp) if availability_status == "verified" else None
    for week in predictor["weeks"]:
        is_target = str(week) == str(forecast_week)
        status = "verified" if is_target and verified_timestamp else "availability_uncertain"
        first_verified = verified_timestamp if is_target else None
        lag = None
        if first_verified:
            lag = (parse_timestamp(first_verified) - parse_timestamp(week_end_timestamp(str(week)))).total_seconds() / 86400.0
        rows.append({
            "represented_week": str(week),
            "bundle_path": str(predictor["bundle"]),
            "bundle_sha256": bundle_sha,
            "file_modification_timestamp": file_timestamp,
            "first_verified_available_timestamp": first_verified,
            "complete_predictor_count": complete,
            "availability_status": status,
            "availability_lag_days": lag,
            "ready_for_nowcast": bool(complete == 12 and status == "verified" and first_verified),
        })
    return pd.DataFrame(rows), {"bundle_sha256": bundle_sha, "file_timestamp": file_timestamp, "complete_predictor_count": complete}


def ensure_environment_history(output: Path, root: Path, predictor: dict[str, Any], forecast_week: str, environment_timestamp: str | None, availability_status: str) -> pd.DataFrame:
    path = root / "availability" / "environment_bundle_history.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    fresh, _ = bundle_inventory(predictor, forecast_week, environment_timestamp, availability_status)
    if path.exists():
        existing = pd.read_parquet(path)
        fresh = pd.concat([existing, fresh], ignore_index=True)
        fresh = fresh.sort_values(["represented_week", "first_verified_available_timestamp"], na_position="last").drop_duplicates("represented_week", keep="last")
    fresh.to_parquet(path, index=False)
    verified = fresh.loc[fresh["availability_status"].eq("verified") & fresh["availability_lag_days"].notna(), "availability_lag_days"].astype(float)
    summary = {
        "n_verified_bundles": int(len(verified)),
        "median_days": None if len(verified) == 0 else float(verified.median()),
        "minimum_days": None if len(verified) == 0 else float(verified.min()),
        "maximum_days": None if len(verified) == 0 else float(verified.max()),
        "iqr_days": None if len(verified) == 0 else float(verified.quantile(0.75) - verified.quantile(0.25)),
        "initial_expectation_days": "approximately 7–14 days; measured rather than imposed",
    }
    write_json(root / "availability" / "environment_latency_summary.json", summary)
    return fresh


def source_week_series(path: Path) -> pd.Series:
    if path.suffix.lower() == ".parquet":
        columns = pd.read_parquet(path, engine="pyarrow").columns.tolist()
        use = [column for column in ["iso_week", "week", "date"] if column in columns]
        raw = pd.read_parquet(path, columns=use)
    else:
        raw = pd.read_csv(path)
    if "iso_week" in raw.columns:
        return raw["iso_week"].astype(str)
    if "week" in raw.columns:
        return raw["week"].astype(str)
    if "date" in raw.columns:
        dates = pd.to_datetime(raw["date"], errors="coerce")
        if dates.isna().any():
            raise RuntimeError("observation dates contain invalid values")
        iso = dates.dt.isocalendar()
        return iso.year.astype(str) + "-W" + iso.week.astype(str).str.zfill(2)
    raise RuntimeError("observation source lacks iso_week/week/date")


def source_metadata_for_readiness(path: Path, forecast_week: str, available_timestamp: str | None) -> dict[str, Any]:
    if not path.exists():
        return {"source_path": str(path), "exists": False, "available_timestamp": None, "contains_forecast_week": False}
    weeks = source_week_series(path)
    stat = path.stat()
    file_timestamp = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(timespec="seconds")
    available = timestamp_or_none(available_timestamp) or file_timestamp
    return {
        "source_path": str(path),
        "exists": True,
        "sha256": sha256_file(path),
        "row_count": int(len(weeks)),
        "minimum_week": str(weeks.min()),
        "maximum_week": str(weeks.max()),
        "file_timestamp": file_timestamp,
        "first_seen_timestamp": available,
        "contains_forecast_week": bool((weeks == forecast_week).any()),
        "forecast_week_rows": int((weeks == forecast_week).sum()),
    }


def resolve_observation_source(output: Path, root: Path, requested: Path | None) -> Path | None:
    if requested is not None:
        return requested
    history = ensure_source_history(output, root)
    if len(history):
        candidate = Path(str(history.iloc[-1]["source_path"]))
        return candidate if candidate.exists() else None
    return None


def load_history(output: Path) -> pd.DataFrame:
    path = output / "state" / "recorded_detection_history.parquet"
    if not path.exists():
        raise RuntimeError("recorded-detection history state is missing")
    history = pd.read_parquet(path)
    required = {"week", "model_node_id", "observed_count"}
    if not required.issubset(history.columns):
        raise RuntimeError("recorded-detection history schema is incomplete")
    history["week"] = history["week"].astype(str)
    history["model_node_id"] = history["model_node_id"].astype(int)
    history["observed_count"] = history["observed_count"].astype(int)
    if "first_available_timestamp" not in history.columns:
        source_history = ensure_source_history(output, output)
        fallback = None if len(source_history) == 0 else source_history.iloc[0]["first_seen_timestamp"]
        history["first_available_timestamp"] = fallback
    history["first_available_timestamp"] = history["first_available_timestamp"].map(timestamp_or_none)
    if history[["week", "model_node_id"]].duplicated().any() or (history["observed_count"] <= 0).any():
        raise RuntimeError("recorded-detection history contains invalid or duplicate positive rows")
    return history.sort_values(["week", "model_node_id"]).reset_index(drop=True)


def history_visible_at_issue(history: pd.DataFrame, forecast_week: str, issue_timestamp: str, history_mode: str) -> pd.DataFrame:
    visible = history.loc[history["week"] < forecast_week].copy()
    if history_mode == "availability_causal":
        issue = parse_timestamp(issue_timestamp)
        available = pd.to_datetime(visible["first_available_timestamp"], utc=True, errors="coerce")
        visible = visible.loc[available < issue].copy()
    elif history_mode != "event_causal":
        raise RuntimeError(f"unsupported history mode: {history_mode}")
    return visible


def front_state_for_week(history: pd.DataFrame, forecast_week: str, nodes: pd.DataFrame, history_mode: str = "event_causal", issue_timestamp: str | None = None) -> dict[str, np.ndarray | str | float]:
    if forecast_week <= SOURCE_HISTORY_START:
        labels = week_range(SOURCE_HISTORY_START, forecast_week)
    else:
        labels = week_range(SOURCE_HISTORY_START, forecast_week)
    eligible_history = history.loc[history["week"].isin(labels) & (history["week"] < forecast_week)].copy()
    if history_mode == "availability_causal":
        if issue_timestamp is None:
            raise RuntimeError("availability-causal history requires an issue timestamp")
        eligible_history = history_visible_at_issue(eligible_history, forecast_week, issue_timestamp, history_mode)
    elif history_mode != "event_causal":
        raise RuntimeError(f"unsupported history mode: {history_mode}")
    grouped = eligible_history.groupby("week")["model_node_id"]
    positive_sets = [grouped.get_group(label).to_numpy(int) if label in grouped.groups else np.array([], dtype=int) for label in labels]
    positive_sets.append(np.array([], dtype=int))
    labels_with_current = labels + [forecast_week] if labels[-1] != forecast_week else labels
    state = causal_front_descriptors(
        positive_sets[:len(labels_with_current)],
        nodes[["x", "y"]].to_numpy(float),
        nodes["lat"].to_numpy(float),
        labels_with_current,
    )
    row = state.loc[state["week"].astype(str) == forecast_week].sort_values("node_id")
    if len(row) != NODE_COUNT:
        raise RuntimeError("front-state row count does not match the prediction domain")
    distance_placeholder = float(np.hypot(np.ptp(nodes["x"].to_numpy(float)), np.ptp(nodes["y"].to_numpy(float))))
    any_distance = row["distance_to_any_prior_detection_km"].to_numpy(float)
    prev4_distance = row["distance_to_previous4_detection_km"].to_numpy(float)
    recency = row["weeks_since_any_detection_within_50km"].to_numpy(float)
    any_available = np.isfinite(any_distance)
    prev4_available = np.isfinite(prev4_distance)
    recency_available = np.isfinite(recency)
    return {
        "distance_any": np.where(any_available, any_distance, distance_placeholder),
        "distance_prev4": np.where(prev4_available, prev4_distance, distance_placeholder),
        "recency50": np.where(recency_available, recency, RECENCY_PLACEHOLDER_WEEKS),
        "any_available": any_available.astype(np.int8),
        "prev4_available": prev4_available.astype(np.int8),
        "recency_available": recency_available.astype(np.int8),
        "history_cutoff_week": previous_week(forecast_week),
        "history_information_cutoff_timestamp": issue_timestamp or "unknown",
        "history_mode": history_mode,
        "prior_positive_nodes": np.unique(np.concatenate(positive_sets[:-1])) if positive_sets[:-1] else np.array([], dtype=int),
    }


def make_prediction_frame(
    predictor: dict[str, Any],
    model: dict[str, Any],
    model_manifest_sha: str,
    input_manifest_sha: str,
    history: pd.DataFrame,
    forecast_week: str,
    issue_timestamp: str,
    history_mode: str,
    chronology: dict[str, Any],
) -> pd.DataFrame:
    if forecast_week not in predictor["weeks"]:
        raise RuntimeError(f"current-week environmental predictors for {forecast_week} are not available")
    index = predictor["weeks"].index(forecast_week)
    nodes = predictor["nodes"]
    front = front_state_for_week(history, forecast_week, nodes, history_mode=history_mode, issue_timestamp=issue_timestamp)
    density = np.log1p(predictor["static"][:, :5])
    indicators = predictor["static"][:, 5:]
    base = np.concatenate([predictor["dynamic"][index], density, indicators, np.broadcast_to(predictor["calendar"][index], (NODE_COUNT, 2))], axis=1)
    transformed = np.column_stack([
        np.log1p(front["distance_any"]),
        np.log1p(front["distance_prev4"]),
        np.log1p(front["recency50"]),
        front["any_available"], front["prev4_available"], front["recency_available"],
    ])
    x = np.concatenate([base, transformed], axis=1)
    feature_order = model["feature_order"]
    if len(feature_order) != 30 or x.shape != (NODE_COUNT, 30):
        raise RuntimeError("frozen feature-order or feature-width contract failed")
    scaling = model["preprocessing"]
    x = (x - np.asarray(scaling["mean"], dtype=float)[None, :]) / np.asarray(scaling["standard_deviation"], dtype=float)[None, :]
    design = np.column_stack([np.ones(NODE_COUNT), x])
    p = expit(np.clip(design @ np.asarray(model["occurrence_coefficients"], dtype=float), -40.0, 40.0))
    mu = np.exp(np.clip(design @ np.asarray(model["count_coefficients"], dtype=float), -20.0, 20.0))
    theta = float(model["theta"])
    log_p0 = theta * (np.log(theta) - np.log(theta + mu))
    conditional = mu / np.maximum(-np.expm1(log_p0), 1e-8)
    region = np.where(nodes["country_or_domain_region"].astype(str).str.startswith("U.S").to_numpy(), "United States", "Mexico")
    frame = pd.DataFrame({
        "forecast_week": forecast_week,
        "forecast_issue_timestamp_utc": issue_timestamp,
        "environment_bundle_available_timestamp": chronology.get("environment_available_timestamp", "unknown"),
        "observation_source_available_timestamp": chronology.get("observation_source_available_timestamp", "unknown"),
        "history_information_cutoff_timestamp": issue_timestamp,
        "history_cutoff_week": front["history_cutoff_week"],
        "history_cutoff_timestamp": week_end_timestamp(front["history_cutoff_week"]),
        "history_mode": history_mode,
        "prospective_eligibility": chronology["prospective_eligibility"],
        "outcome_maturity": "unscored",
        "score_version": 0,
        "nowcast_window_open_timestamp": chronology.get("nowcast_window_open_timestamp", "unknown"),
        "nowcast_window_close_timestamp": chronology.get("nowcast_window_close_timestamp", "unknown"),
        "model_id": MODEL_ID,
        "model_manifest_sha": model_manifest_sha,
        "input_manifest_sha": input_manifest_sha,
        "model_node_id": np.arange(NODE_COUNT, dtype=np.int32),
        "canonical_node_id": nodes["canonical_node_id"].to_numpy(np.int64),
        "lon": nodes["lon"].to_numpy(float),
        "lat": nodes["lat"].to_numpy(float),
        "country_or_region": region,
        "predicted_probability": p,
        "predicted_conditional_positive_mean": conditional,
        "predicted_underlying_mu": mu,
        "predicted_unconditional_mean": p * conditional,
        "distance_to_any_prior_positive_km": front["distance_any"],
        "distance_to_prev4_positive_km": front["distance_prev4"],
        "weeks_since_detection_within_50km": front["recency50"],
        "any_prior_positive_available": front["any_available"],
        "prev4_positive_available": front["prev4_available"],
        "detection_within_50km_ever_available": front["recency_available"],
    })
    if not frame["predicted_probability"].between(0, 1).all() or not np.isfinite(frame.select_dtypes(include=[np.number]).to_numpy()).all():
        raise RuntimeError("prediction probability/range contract failed")
    return frame


def immutable_parquet(frame: pd.DataFrame, path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    candidate = Path(str(path) + ".candidate")
    frame.to_parquet(candidate, index=False)
    candidate_sha = sha256_file(candidate)
    checksum_path = Path(str(path) + ".sha256")
    if path.exists():
        existing_sha = sha256_file(path)
        if existing_sha != candidate_sha:
            candidate.unlink()
            raise RuntimeError(f"immutable artifact already exists with a different checksum: {path}")
        candidate.unlink()
        if not checksum_path.exists():
            checksum_path.write_text(f"{existing_sha}  {path.name}\n", encoding="utf-8")
        return existing_sha
    candidate.replace(path)
    checksum_path.write_text(f"{candidate_sha}  {path.name}\n", encoding="utf-8")
    return candidate_sha


def append_unique_csv(path: Path, row: dict[str, Any], keys: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        frame = pd.read_csv(path)
    else:
        frame = pd.DataFrame()
    if len(frame) and all(key in frame.columns for key in keys):
        mask = np.ones(len(frame), dtype=bool)
        for key in keys:
            mask &= frame[key].astype(str).to_numpy() == str(row[key])
        if mask.any():
            old = frame.loc[mask].iloc[0].to_dict()
            equivalent = True
            for column, value in row.items():
                old_value = old.get(column)
                try:
                    if np.isfinite(float(old_value)) and np.isfinite(float(value)):
                        if not np.isclose(float(old_value), float(value), rtol=1e-12, atol=1e-12):
                            equivalent = False
                            break
                    elif str(old_value) != str(value):
                        equivalent = False
                        break
                except (TypeError, ValueError):
                    if str(old_value) != str(value):
                        equivalent = False
                        break
            if not equivalent:
                raise RuntimeError(f"append-only ledger conflict for {keys}")
            return
    frame = pd.concat([frame, pd.DataFrame([row])], ignore_index=True)
    frame.to_csv(path, index=False)


def source_observations(path: Path, forecast_week: str, node_count: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    if not path.exists():
        raise RuntimeError(f"observation source does not exist: {path}")
    source_sha = sha256_file(path)
    raw = pd.read_parquet(path) if path.suffix.lower() == ".parquet" else pd.read_csv(path)
    if "model_node_id" not in raw.columns and "node_id" in raw.columns:
        raw = raw.rename(columns={"node_id": "model_node_id"})
    if "model_node_id" not in raw.columns:
        raise RuntimeError("score mode requires a node-assigned observation parquet with model_node_id; raw lon/lat CSVs require an upstream audited assignment step")
    if "revised_domain_membership" in raw.columns:
        raw = raw.loc[raw["revised_domain_membership"].astype(bool)].copy()
    if "iso_week" in raw.columns:
        raw["week"] = raw["iso_week"].astype(str)
    elif "week" not in raw.columns and "date" in raw.columns:
        dates = pd.to_datetime(raw["date"], errors="coerce")
        if dates.isna().any():
            raise RuntimeError("observation dates contain invalid values")
        raw["week"] = dates.dt.isocalendar().year.astype(str) + "-W" + dates.dt.isocalendar().week.astype(str).str.zfill(2)
    if "week" not in raw.columns:
        raise RuntimeError("observation source lacks iso_week/week/date")
    raw["model_node_id"] = pd.to_numeric(raw["model_node_id"], errors="coerce")
    if raw["model_node_id"].isna().any() or (raw["model_node_id"] < 0).any() or (raw["model_node_id"] >= node_count).any():
        raise RuntimeError("observation node assignment is invalid")
    count_column = "observed_count" if "observed_count" in raw.columns else "count" if "count" in raw.columns else None
    if count_column is None:
        raw["event_count"] = 1
    else:
        raw["event_count"] = pd.to_numeric(raw[count_column], errors="coerce")
    if raw["event_count"].isna().any() or (raw["event_count"] < 0).any():
        raise RuntimeError("observation counts are invalid")
    grouped = raw.groupby(["week", "model_node_id"], as_index=False)["event_count"].sum().rename(columns={"event_count": "observed_count"})
    grouped["model_node_id"] = grouped["model_node_id"].astype(int)
    grouped["observed_count"] = grouped["observed_count"].astype(int)
    if grouped.loc[grouped["week"] == forecast_week, "model_node_id"].duplicated().any():
        raise RuntimeError("duplicate node/week outcome assignment")
    dates = pd.to_datetime(raw["date"], errors="coerce") if "date" in raw.columns else pd.Series(dtype="datetime64[ns]")
    stat = path.stat()
    metadata = {
        "source_path": str(path),
        "sha256": source_sha,
        "row_count": int(len(raw)),
        "minimum_date": None if dates.empty else str(dates.min().date()),
        "maximum_date": None if dates.empty else str(dates.max().date()),
        "file_mtime_utc": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(timespec="seconds"),
        "ingestion_timestamp_utc": utc_now(),
        "forecast_week": forecast_week,
        "forecast_week_event_rows": int((raw["week"] == forecast_week).sum()),
        "forecast_week_mexico_rows": int(((raw["week"] == forecast_week) & raw.get("country_code", pd.Series("", index=raw.index)).astype(str).str.upper().isin(["MX", "MEXICO"])).sum()),
        "forecast_week_us_rows": int(((raw["week"] == forecast_week) & raw.get("country_code", pd.Series("", index=raw.index)).astype(str).str.upper().isin(["US", "USA", "UNITED STATES"])).sum()),
    }
    return grouped, metadata


def nb_joint_contributions(y: np.ndarray, p: np.ndarray, mu: np.ndarray, theta: float) -> tuple[np.ndarray, np.ndarray]:
    y = np.asarray(y, dtype=float)
    p = np.asarray(p, dtype=float)
    mu = np.asarray(mu, dtype=float)
    theta = float(theta)
    log_p0 = theta * (np.log(theta) - np.log(theta + mu))
    log_nb = gammaln(y + theta) - gammaln(theta) - gammaln(y + 1.0) + log_p0 + y * (np.log(mu) - np.log(theta + mu))
    log_trunc = log_nb - np.log(np.maximum(-np.expm1(log_p0), 1e-12))
    zero = y <= 0
    joint = np.where(zero, -np.log(np.maximum(1.0 - p, 1e-12)), -(np.log(np.maximum(p, 1e-12)) + log_trunc))
    count_nll = np.where(zero, 0.0, -log_trunc)
    return joint, count_nll


def region_name(value: str) -> str:
    return "United States" if str(value).startswith("U.S") or str(value).startswith("United") else "Mexico"


def score_frame(predictions: pd.DataFrame, outcomes: pd.DataFrame, history: pd.DataFrame, nodes: pd.DataFrame, theta: float, training_prevalence: float, eligible: bool) -> tuple[dict[str, Any], pd.DataFrame]:
    merged = predictions.merge(outcomes, on=["forecast_week", "model_node_id"], how="left", validate="one_to_one")
    if len(merged) != NODE_COUNT or merged["observed_count"].isna().any():
        raise RuntimeError("prediction/outcome node-week join is incomplete")
    y = merged["observed_count"].to_numpy(int)
    p = merged["predicted_probability"].to_numpy(float)
    conditional = merged["predicted_conditional_positive_mean"].to_numpy(float)
    mu = merged["predicted_underlying_mu"].to_numpy(float)
    joint, count_nll = nb_joint_contributions(y, p, mu, theta)
    forecast_week = str(predictions["forecast_week"].iloc[0])
    if "history_information_cutoff_timestamp" in predictions.columns:
        issue_timestamp = str(predictions["history_information_cutoff_timestamp"].iloc[0])
    elif "forecast_issue_timestamp_utc" in predictions.columns:
        issue_timestamp = str(predictions["forecast_issue_timestamp_utc"].iloc[0])
    elif "forecast_issue_timestamp" in predictions.columns:
        issue_timestamp = str(predictions["forecast_issue_timestamp"].iloc[0])
    else:
        raise RuntimeError("forecast artifact is missing its issue timestamp")
    history_mode = str(predictions.get("history_mode", pd.Series(["event_causal"])).iloc[0])
    prior_visible = history_visible_at_issue(history, forecast_week, issue_timestamp, history_mode)
    prior_nodes = set(prior_visible["model_node_id"].astype(int))
    merged["first_ever_positive_flag"] = ((y > 0) & ~merged["model_node_id"].isin(prior_nodes)).astype(np.int8)
    merged["previously_positive_flag"] = ((y > 0) & merged["model_node_id"].isin(prior_nodes)).astype(np.int8)
    merged["region"] = merged["country_or_region"]
    full_rank = (pd.Series(p).rank(method="average", pct=True).to_numpy() * 100.0)
    merged["percentile_rank_full_domain"] = full_rank
    merged["percentile_rank_region"] = merged.groupby("country_or_region")["predicted_probability"].rank(method="average", pct=True).to_numpy() * 100.0
    merged["occurrence_nll_contribution"] = np.where(y > 0, -np.log(np.maximum(p, 1e-12)), -np.log(np.maximum(1.0 - p, 1e-12)))
    merged["joint_nll_contribution"] = joint
    merged["positive_count_absolute_error"] = np.where(y > 0, np.abs(y - conditional), 0.0)
    merged["positive_count_squared_error"] = np.where(y > 0, (y - conditional) ** 2, 0.0)
    metrics = safe_metrics(y, p, conditional, mu, theta, training_prevalence, "full_revised_domain", 0, MODEL_ID)
    metrics.update({
        "forecast_week": str(predictions["forecast_week"].iloc[0]),
        "prospective_eligible": bool(eligible),
        "observed_total_detections": int(y.sum()),
        "predicted_expected_total_detections": float(np.sum(p * conditional)),
        "observed_positive_node_weeks": int(np.sum(y > 0)),
        "mean_predicted_probability": float(p.mean()),
    })
    return metrics, merged


def write_map(frame: pd.DataFrame, path: Path, title: str, observed: np.ndarray | None = None) -> None:
    """Write a dependency-light SVG map with a common 0--1 probability scale."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lon = frame["lon"].to_numpy(float)
    lat = frame["lat"].to_numpy(float)
    probability = np.clip(frame["predicted_probability"].to_numpy(float), 0.0, 1.0)
    left, right = float(np.nanmin(lon)), float(np.nanmax(lon))
    bottom, top = float(np.nanmin(lat)), float(np.nanmax(lat))
    lon_span = max(right - left, 1e-9)
    lat_span = max(top - bottom, 1e-9)
    width, height, margin = 1000, 700, 40
    x = margin + (lon - left) / lon_span * (width - 2 * margin)
    y = height - margin - (lat - bottom) / lat_span * (height - 2 * margin)
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f'<title>{html.escape(title)}</title>',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{margin}" y="24" font-family="sans-serif" font-size="16">{html.escape(title)}</text>',
        f'<rect x="{margin}" y="{margin}" width="{width-2*margin}" height="{height-2*margin}" fill="#f4f7fb" stroke="#9aa7b5"/>',
    ]
    for xi, yi, value in zip(x, y, probability):
        red = int(round(255 * value))
        blue = int(round(255 * (1.0 - value)))
        green = int(round(90 + 90 * (1.0 - value)))
        lines.append(f'<circle cx="{xi:.2f}" cy="{yi:.2f}" r="1.8" fill="rgb({red},{green},{blue})" fill-opacity="0.72"/>')
    if observed is not None and np.any(observed > 0):
        mask = np.asarray(observed, dtype=int) > 0
        for xi, yi in zip(x[mask], y[mask]):
            lines.append(f'<circle cx="{xi:.2f}" cy="{yi:.2f}" r="4.0" fill="none" stroke="#d62728" stroke-width="1.2"/>')
    lines.extend([
        f'<text x="{margin}" y="{height-12}" font-family="sans-serif" font-size="11">longitude {left:.2f} to {right:.2f}; latitude {bottom:.2f} to {top:.2f}</text>',
        '<text x="820" y="50" font-family="sans-serif" font-size="11">blue: low p; red: high p</text>',
        '</svg>',
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def assess_nowcast_chronology(
    output: Path,
    root: Path,
    predictor: dict[str, Any],
    forecast_week: str,
    issue_timestamp: str,
    history_mode: str,
    environment_timestamp: str | None,
    environment_status: str,
    observation_source: Path | None,
    observation_timestamp: str | None,
) -> dict[str, Any]:
    ensure_source_history(output, root)
    environment_history = ensure_environment_history(output, root, predictor, forecast_week, environment_timestamp, environment_status)
    environment_row = environment_history.loc[environment_history["represented_week"].astype(str).eq(forecast_week)]
    environment_available = bool(len(environment_row) and environment_row.iloc[-1]["complete_predictor_count"] == 12)
    environment_verified = bool(len(environment_row) and environment_row.iloc[-1]["availability_status"] == "verified")
    environment_available_timestamp = None if not environment_verified else timestamp_or_none(environment_row.iloc[-1]["first_verified_available_timestamp"])
    source_info = source_metadata_for_readiness(observation_source, forecast_week, observation_timestamp) if observation_source else {"exists": False, "contains_forecast_week": False, "first_seen_timestamp": None}
    source_available_timestamp = timestamp_or_none(source_info.get("first_seen_timestamp"))
    issue = parse_timestamp(issue_timestamp)
    outcome_known_before_issue = bool(
        source_info.get("exists")
        and source_info.get("contains_forecast_week")
        and source_available_timestamp is not None
        and parse_timestamp(source_available_timestamp) < issue
    )
    if not environment_available:
        state = "environment_not_available"
        reason = "all 12 represented-week environmental predictors are not available in the predictor bundle"
    elif outcome_known_before_issue:
        state = "outcome_already_available"
        reason = "the observation source already contained the forecast-week event records before forecast issue"
    elif not environment_verified or environment_available_timestamp is None:
        state = "availability_uncertain"
        reason = "environment bundle timing is not verified; file modification time is only a conservative proxy"
    elif history_mode != "availability_causal":
        state = "retrospective_only"
        reason = "production nowcasts require availability_causal front history"
    else:
        state = "prospective_eligible"
        reason = None
    if state not in ELIGIBILITY_STATES:
        raise RuntimeError(f"invalid prospective eligibility state: {state}")
    return {
        "forecast_week": forecast_week,
        "prospective_eligibility": state,
        "reason": reason,
        "environment_ready": environment_available,
        "environment_verified": environment_verified,
        "environment_available_timestamp": environment_available_timestamp or "unknown",
        "observation_source_available_timestamp": source_available_timestamp or "unknown",
        "observation_outcome_already_available": outcome_known_before_issue,
        "history_information_cutoff_timestamp": issue_timestamp,
        "history_cutoff_week": previous_week(forecast_week),
        "history_mode": history_mode,
        "nowcast_window_open_timestamp": environment_available_timestamp or "unknown",
        "nowcast_window_close_timestamp": source_available_timestamp or "unknown",
        "source_info": source_info,
    }


def ensure_registry_schema(output: Path) -> pd.DataFrame:
    path = output / "forecast_registry" / "prospective_forecast_registry.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "forecast_week", "environment_available_timestamp", "forecast_issue_timestamp", "history_cutoff",
        "history_mode", "prediction_path", "prediction_sha", "prediction_sha256", "model_sha256", "input_sha256",
        "prospective_eligibility", "outcome_first_available_timestamp", "latest_score_version",
        "outcome_maturity", "outcomes_ingested", "score_status", "test_mode",
    ]
    frame = pd.read_csv(path) if path.exists() else pd.DataFrame()
    for column in columns:
        if column not in frame.columns:
            frame[column] = None
    frame = frame[columns]
    frame.to_csv(path, index=False)
    return frame


def run_readiness(args: argparse.Namespace) -> dict[str, Any]:
    manifest, _, model_manifest_sha, frozen_input_sha = require_frozen_model(args.output)
    predictor = load_predictor_bundle(args.input_bundle or args.model_output)
    root = args.output / "sandbox" if args.test_mode else args.output
    issue_timestamp = args.issue_timestamp_utc or utc_now()
    history_mode = effective_history_mode(args)
    observation_source = resolve_observation_source(args.output, root, args.observation_source)
    chronology = assess_nowcast_chronology(
        args.output, root, predictor, args.forecast_week, issue_timestamp, history_mode,
        args.environment_available_timestamp_utc, args.environment_availability_status,
        observation_source, args.source_available_timestamp_utc,
    )
    result = {
        "status": "READY" if chronology["prospective_eligibility"] == "prospective_eligible" else "NOT_READY",
        "operational_mode": "delayed_prospective_nowcast",
        "forecast_week": args.forecast_week,
        "environment_ready": chronology["environment_ready"],
        "environment_available_timestamp": chronology["environment_available_timestamp"],
        "observation_source_available_timestamp": chronology["observation_source_available_timestamp"],
        "observation_outcome_already_available": chronology["observation_outcome_already_available"],
        "forecast_issue_timestamp": issue_timestamp,
        "history_information_cutoff_timestamp": issue_timestamp,
        "history_cutoff_week": chronology["history_cutoff_week"],
        "history_mode": history_mode,
        "prospective_eligibility": chronology["prospective_eligibility"],
        "nowcast_window_open_timestamp": chronology["nowcast_window_open_timestamp"],
        "nowcast_window_close_timestamp": chronology["nowcast_window_close_timestamp"],
        "model_manifest_sha": model_manifest_sha,
        "input_manifest_sha": frozen_input_sha,
        "reason": chronology["reason"],
        "test_mode": bool(args.test_mode),
    }
    if not args.test_mode:
        # Keep the production registry schema current even while no eligible
        # forecast has yet been issued.  Readiness is intentionally read-only
        # with respect to forecast artifacts, but it may initialize contracts.
        ensure_registry_schema(args.output)
        status = ensure_status_fields(args.output)
        status["operational_mode"] = "delayed_prospective_nowcast"
        status["environment_latency_status"] = "verified" if chronology["environment_verified"] else "uncertain"
        status["observation_latency_status"] = "known" if chronology["observation_source_available_timestamp"] != "unknown" else "uncertain"
        if chronology["prospective_eligibility"] != "prospective_eligible" and status.get("genuine_prospective_forecasts", 0) == 0:
            status["evaluation_status"] = "HARNESS READY — AWAITING ELIGIBLE NOWCAST WINDOW"
        write_json(args.output / "prospective_status.json", status)
    print(json.dumps(result, indent=2))
    return result


def run_forecast(args: argparse.Namespace) -> dict[str, Any]:
    manifest, model, model_manifest_sha, frozen_input_sha = require_frozen_model(args.output)
    predictor = load_predictor_bundle(args.input_bundle or args.model_output)
    history = load_history(args.output)
    root = args.output / "sandbox" if args.test_mode else args.output
    history_mode = effective_history_mode(args)
    issue_timestamp = args.issue_timestamp_utc or utc_now()
    observation_source = resolve_observation_source(args.output, root, args.observation_source)
    chronology = assess_nowcast_chronology(
        args.output, root, predictor, args.forecast_week, issue_timestamp, history_mode,
        args.environment_available_timestamp_utc, args.environment_availability_status,
        observation_source, args.source_available_timestamp_utc,
    )
    available = bool(chronology["environment_ready"] and args.forecast_week in predictor["weeks"])
    if args.mode == "dry-run":
        result = {
            "status": "READY" if chronology["prospective_eligibility"] == "prospective_eligible" else "NOT_READY",
            "forecast_week": args.forecast_week,
            "history_cutoff_week": previous_week(args.forecast_week),
            "predictor_week_available": available,
            "model_manifest_sha": model_manifest_sha,
            "input_manifest_sha": frozen_input_sha,
            "test_mode": bool(args.test_mode),
            "operational_mode": "delayed_prospective_nowcast",
            "history_mode": history_mode,
            "environment_ready": chronology["environment_ready"],
            "environment_verified": chronology["environment_verified"],
            "prospective_eligibility": chronology["prospective_eligibility"],
            "operational_feasibility": "PARTIAL" if available else "FALSE",
            "reason": chronology["reason"],
        }
        print(json.dumps(result, indent=2))
        return result
    if not args.test_mode and chronology["prospective_eligibility"] != "prospective_eligible":
        raise RuntimeError(f"delayed nowcast is not eligible: {chronology['prospective_eligibility']}; {chronology['reason']}")
    frame = make_prediction_frame(
        predictor, model, model_manifest_sha, frozen_input_sha, history, args.forecast_week,
        issue_timestamp, history_mode, chronology,
    )
    prediction_path = root / "predictions" / f"prospective_predictions_{args.forecast_week}.parquet"
    prediction_sha = immutable_parquet(frame, prediction_path)
    write_map(frame, root / "maps" / f"forecast_{args.forecast_week}_preoutcome.svg", f"{MODEL_ID} forecast {args.forecast_week} — pre-outcome", None)
    if not args.test_mode:
        ensure_registry_schema(args.output)
        append_unique_csv(args.output / "forecast_registry" / "prospective_forecast_registry.csv", {
            "forecast_week": args.forecast_week,
            "environment_available_timestamp": chronology["environment_available_timestamp"],
            "forecast_issue_timestamp": issue_timestamp,
            "history_mode": history_mode,
            "prediction_path": str(prediction_path),
            "prediction_sha": prediction_sha,
            "prediction_sha256": prediction_sha,
            "model_sha256": model_manifest_sha,
            "input_sha256": frozen_input_sha,
            "history_cutoff": previous_week(args.forecast_week),
            "prospective_eligibility": chronology["prospective_eligibility"],
            "outcome_first_available_timestamp": chronology["observation_source_available_timestamp"],
            "latest_score_version": 0,
            "outcome_maturity": "unscored",
            "outcomes_ingested": False,
            "score_status": "awaiting_outcomes",
            "test_mode": False,
        }, ["forecast_week"])
        status = ensure_status_fields(args.output)
        status["latest_forecast_week"] = args.forecast_week
        status["latest_eligible_nowcast_week"] = args.forecast_week
        status["evaluation_status"] = "DELAYED PROSPECTIVE EVALUATION ACTIVE"
        write_json(args.output / "prospective_status.json", status)
    print(json.dumps({"status": "forecast_frozen", "forecast_week": args.forecast_week, "prediction_path": str(prediction_path), "prediction_sha256": prediction_sha, "prospective_eligibility": chronology["prospective_eligibility"], "history_mode": history_mode, "test_mode": bool(args.test_mode)}, indent=2))
    return {"frame": frame, "prediction_path": prediction_path, "prediction_sha": prediction_sha, "manifest": manifest, "model": model, "model_manifest_sha": model_manifest_sha, "history": history, "predictor": predictor}


def append_source_history(output: Path, metadata: dict[str, Any], eligible: bool) -> None:
    path = output / "manifests" / "source_history_manifest.csv"
    row = dict(metadata)
    row["status"] = "prospective_eligible" if eligible else "historical_backfill"
    row["prospective_eligible_rows"] = int(eligible)
    append_unique_csv(path, row, ["sha256"])


def append_source_version(output: Path, root: Path, metadata: dict[str, Any], available_timestamp: str | None, forecast_week: str) -> pd.DataFrame:
    path = root / "source_history" / "observation_source_history.parquet"
    history = ensure_source_history(output, root)
    if str(metadata["sha256"]) in history["sha256"].astype(str).tolist():
        return history
    previous_rows = int(history.iloc[-1]["row_count"]) if len(history) else 0
    current_rows = int(metadata.get("row_count", 0))
    row = {
        "source_path": metadata.get("source_path"),
        "sha256": metadata.get("sha256"),
        "row_count": current_rows,
        "first_seen_timestamp": timestamp_or_none(available_timestamp) or metadata.get("file_mtime_utc"),
        "file_timestamp": metadata.get("file_mtime_utc"),
        "minimum_date": metadata.get("minimum_date"),
        "maximum_date": metadata.get("maximum_date"),
        "new_rows": max(0, current_rows - previous_rows),
        "new_current_week_rows": int(metadata.get("forecast_week_event_rows", 0)),
        "historical_backfill_rows": max(0, current_rows - int(metadata.get("forecast_week_event_rows", 0))),
        "source_status": "observed_first_available_timestamp",
    }
    history = pd.concat([history, pd.DataFrame([row])], ignore_index=True)
    history.to_parquet(path, index=False)
    return history


def write_source_refresh_report(output: Path, metadata: dict[str, Any], eligible: bool, test_root: Path) -> None:
    """Persist a source-refresh audit before outcome scoring begins."""
    history_path = output / "manifests" / "source_history_manifest.csv"
    previous_sha = None
    previous_rows = None
    if history_path.exists():
        history = pd.read_csv(history_path)
        if len(history):
            previous_sha = str(history.iloc[-1].get("sha256"))
            previous_rows = int(history.iloc[-1].get("row_count", 0))
    payload = {
        "previous_sha256": previous_sha,
        "new_sha256": metadata["sha256"],
        "row_count": int(metadata["row_count"]),
        "row_count_change": None if previous_rows is None else int(metadata["row_count"]) - previous_rows,
        "new_event_dates": [metadata["forecast_week"]] if int(metadata.get("forecast_week_event_rows", 0)) else [],
        "forecast_week": metadata["forecast_week"],
        "forecast_week_event_rows": int(metadata.get("forecast_week_event_rows", 0)),
        "new_mexico_records": int(metadata.get("forecast_week_mexico_rows", 0)),
        "new_us_records": int(metadata.get("forecast_week_us_rows", 0)),
        "historical_backfill_rows": int(metadata["row_count"]) if not eligible else 0,
        "prospective_eligible_records": int(metadata.get("forecast_week_event_rows", 0)) if eligible else 0,
        "source_available_timestamp_utc": metadata.get("file_mtime_utc"),
        "audit_timestamp_utc": utc_now(),
        "prospective_eligible": bool(eligible),
        "limitation": "No explicit report-ingestion timestamp was available; file mtime/model-run chronology is used conservatively.",
    }
    write_json(test_root / "manifests" / f"source_refresh_{metadata['forecast_week']}.json", payload)


def write_diagnostics(output: Path, merged: pd.DataFrame, metadata: dict[str, Any], eligible: bool, test_root: Path) -> None:
    week = str(merged["forecast_week"].iloc[0])
    positive = merged["observed_count"].to_numpy(int) > 0
    first = merged.loc[merged["first_ever_positive_flag"].astype(bool)].copy()
    first = first.loc[first["observed_count"] > 0]
    first_path = test_root / "scores" / f"first_ever_localization_{week}.csv"
    first_path.parent.mkdir(parents=True, exist_ok=True)
    first.to_csv(first_path, index=False)
    bands = []
    for label, lower, upper in LATITUDE_BANDS:
        sub = merged.loc[(merged["lat"] >= lower) & (merged["lat"] < upper)]
        bands.append({"forecast_week": week, "latitude_band": label, "mean_predicted_probability": float(sub["predicted_probability"].mean()), "p95_predicted_probability": float(sub["predicted_probability"].quantile(0.95)), "maximum_predicted_probability": float(sub["predicted_probability"].max()), "positive_node_weeks": int((sub["observed_count"] > 0).sum()), "prospective_eligible": eligible})
    append_unique_csv(test_root / "scores" / "latitude_scores.csv", bands[0], ["forecast_week", "latitude_band"])
    lat_path = test_root / "scores" / "latitude_scores.csv"
    if len(bands) > 1:
        existing = pd.read_csv(lat_path) if lat_path.exists() else pd.DataFrame()
        for row in bands[1:]:
            if not len(existing) or not ((existing["forecast_week"].astype(str) == week) & (existing["latitude_band"].astype(str) == row["latitude_band"])).any():
                existing = pd.concat([existing, pd.DataFrame([row])], ignore_index=True)
        existing.to_csv(lat_path, index=False)
    us = merged.loc[(merged["country_or_region"] == "United States") & positive].copy()
    if len(us):
        us.to_csv(test_root / "scores" / f"us_transfer_cases_{week}.csv", index=False)
    max_lat = float(merged.loc[positive, "lat"].max()) if positive.any() else None
    p95_lat = float(merged.loc[positive, "lat"].quantile(0.95)) if positive.any() else None
    front = {"forecast_week": week, "new_first_ever_positive_nodes": int(first.shape[0]), "recurrent_positive_nodes": int(merged["previously_positive_flag"].sum()), "northmost_positive_latitude": max_lat, "p95_positive_latitude": p95_lat, "median_first_positive_distance_to_prior_km": None if len(first) == 0 else float(first["distance_to_any_prior_positive_km"].median()), "maximum_first_positive_distance_to_prior_km": None if len(first) == 0 else float(first["distance_to_any_prior_positive_km"].max()), "prospective_eligible": eligible}
    append_unique_csv(test_root / "scores" / "front_evolution.csv", front, ["forecast_week"])


def update_status(output: Path) -> None:
    status = ensure_status_fields(output)
    scores_path = output / "scores" / "prospective_scores.csv"
    ledger_path = output / "prospective_evaluation_ledger.parquet"
    if scores_path.exists():
        scores = pd.read_csv(scores_path)
        eligible = scores.loc[
            (scores["scope"].astype(str) == "weekly")
            & (scores["prospective_eligible"].astype(str).str.lower() == "true")
        ]
        status["number_genuine_prospective_weeks"] = int(eligible["forecast_week"].nunique())
    if ledger_path.exists():
        ledger = pd.read_parquet(ledger_path)
        eligible_ledger = ledger.loc[
            ledger["prospective_eligible"].astype(str).str.lower() == "true"
        ]
        status["number_genuine_prospective_positive_node_weeks"] = int(eligible_ledger["observed_presence"].sum())
        status["number_first_ever_positive_nodes"] = int(eligible_ledger["first_ever_positive_flag"].sum())
    status["evaluation_status"] = (
        "DELAYED PROSPECTIVE EVALUATION ACTIVE"
        if status.get("number_genuine_prospective_weeks", 0)
        else "HARNESS READY — AWAITING ELIGIBLE NOWCAST WINDOW"
    )
    write_json(output / "prospective_status.json", status)


def run_score(args: argparse.Namespace) -> dict[str, Any]:
    manifest, model, model_manifest_sha, _ = require_frozen_model(args.output)
    root = args.output / "sandbox" if args.test_mode else args.output
    version = score_version(args.score_version)
    prediction_path = root / "predictions" / f"prospective_predictions_{args.forecast_week}.parquet"
    checksum_path = Path(str(prediction_path) + ".sha256")
    if not prediction_path.exists() or not checksum_path.exists():
        raise RuntimeError("no immutable forecast exists for score mode")
    if checksum_path.read_text().split()[0] != sha256_file(prediction_path):
        raise RuntimeError("forecast checksum does not match archived forecast")
    predictions = pd.read_parquet(prediction_path)
    if "observed_count" in predictions.columns or "observed_presence" in predictions.columns:
        raise RuntimeError("forecast artifact contains outcome fields")
    if predictions["model_manifest_sha"].nunique() != 1 or predictions["model_manifest_sha"].iloc[0] != model_manifest_sha:
        raise RuntimeError("forecast model manifest does not match frozen model")
    history = load_history(args.output)
    outcomes, metadata = source_observations(args.observation_source, args.forecast_week, NODE_COUNT)
    issue_timestamp = str(predictions["forecast_issue_timestamp_utc"].iloc[0])
    source_available = timestamp_or_none(args.source_available_timestamp_utc) or timestamp_or_none(metadata["file_mtime_utc"])
    archived_state = str(predictions.get("prospective_eligibility", pd.Series(["retrospective_only"])).iloc[0])
    eligible = (not args.test_mode) and archived_state == "prospective_eligible"
    historical_backfill = not eligible
    outcome_path = root / "outcomes" / f"prospective_outcomes_{args.forecast_week}_v{version}.parquet"
    full_outcomes = pd.DataFrame({"forecast_week": args.forecast_week, "model_node_id": np.arange(NODE_COUNT, dtype=int), "observed_count": 0})
    selected = outcomes.loc[outcomes["week"] == args.forecast_week, ["model_node_id", "observed_count"]]
    full_outcomes.loc[selected["model_node_id"].to_numpy(int), "observed_count"] = selected["observed_count"].to_numpy(int)
    full_outcomes["observed_presence"] = (full_outcomes["observed_count"] > 0).astype(np.int8)
    full_outcomes["source_sha256"] = metadata["sha256"]
    full_outcomes["outcome_ingestion_timestamp_utc"] = utc_now()
    full_outcomes["observation_first_available_timestamp"] = source_available or "unknown"
    source_known_before_forecast = bool(
        source_available
        and parse_timestamp(source_available) < parse_timestamp(issue_timestamp)
    )
    positive_availability_class = (
        "known_before_forecast"
        if source_known_before_forecast
        else "prospective_new_outcome"
    )
    full_outcomes["outcome_availability_class"] = np.where(
        full_outcomes["observed_presence"].astype(bool),
        positive_availability_class,
        "no_recorded_observation",
    )
    full_outcomes["prospective_eligible"] = eligible
    full_outcomes["historical_backfill"] = historical_backfill
    full_outcomes["outcome_maturity"] = args.outcome_maturity
    full_outcomes["score_version"] = version
    full_outcomes["source_available_timestamp"] = source_available or "unknown"
    if outcome_path.exists():
        existing = pd.read_parquet(outcome_path)
        immutable_columns = [column for column in full_outcomes.columns if column != "outcome_ingestion_timestamp_utc"]
        if not set(immutable_columns).issubset(existing.columns):
            raise RuntimeError("existing versioned outcome artifact schema is incomplete")
        pd.testing.assert_frame_equal(existing[immutable_columns].sort_values("model_node_id").reset_index(drop=True), full_outcomes[immutable_columns].sort_values("model_node_id").reset_index(drop=True), check_dtype=False, check_exact=False, rtol=1e-7, atol=1e-9)
        full_outcomes = existing
    else:
        immutable_parquet(full_outcomes, outcome_path)
    write_source_refresh_report(args.output, metadata, eligible, root)
    append_source_version(args.output, root, metadata, source_available, args.forecast_week)
    training_prevalence = float(manifest["fit_metrics"].get("training_prevalence", 0.0))
    metrics, merged = score_frame(predictions, full_outcomes, history, predictions, float(model["theta"]), training_prevalence, eligible)
    for column in ["environment_bundle_available_timestamp", "observation_source_available_timestamp", "history_mode", "prospective_eligibility"]:
        merged[column] = predictions[column].iloc[0] if column in predictions.columns else ("event_causal" if column == "history_mode" else "retrospective_only")
    merged["outcome_maturity"] = args.outcome_maturity
    merged["score_version"] = version
    metrics.update({"historical_backfill": historical_backfill, "source_sha256": metadata["sha256"], "score_version": version, "outcome_maturity": args.outcome_maturity, "score_timestamp": utc_now()})
    score_row = {"scope": "weekly", "region": "full_revised_domain", **{key: value for key, value in metrics.items() if not isinstance(value, (dict, list, np.ndarray))}}
    regional_rows = []
    for region in ["Mexico", "United States", "full_revised_domain"]:
        sub = merged if region == "full_revised_domain" else merged.loc[merged["country_or_region"] == region]
        if len(sub) == 0:
            continue
        reg = safe_metrics(sub["observed_count"].to_numpy(int), sub["predicted_probability"].to_numpy(float), sub["predicted_conditional_positive_mean"].to_numpy(float), sub["predicted_underlying_mu"].to_numpy(float), float(model["theta"]), training_prevalence, region, 0, MODEL_ID)
        reg.update({"scope": "weekly", "region": region, "forecast_week": args.forecast_week, "prospective_eligible": eligible, "historical_backfill": historical_backfill, "score_version": version, "outcome_maturity": args.outcome_maturity})
        regional_rows.append(reg)
    version_rows = pd.DataFrame([score_row] + [{key: value for key, value in row.items() if not isinstance(value, (dict, list, np.ndarray))} for row in regional_rows])
    version_dir = root / "score_versions"
    version_dir.mkdir(parents=True, exist_ok=True)
    version_path = version_dir / f"prospective_scores_{args.forecast_week}_v{version}.csv"
    if version_path.exists():
        pd.testing.assert_frame_equal(pd.read_csv(version_path), version_rows, check_dtype=False, check_exact=False, rtol=1e-10, atol=1e-12)
    else:
        version_rows.to_csv(version_path, index=False)
    append_unique_csv(root / "scores" / "prospective_scores.csv", score_row, ["scope", "forecast_week", "region", "score_version"])
    for row in regional_rows:
        append_unique_csv(root / "scores" / "prospective_regional_scores.csv", {key: value for key, value in row.items() if not isinstance(value, (dict, list, np.ndarray))}, ["scope", "forecast_week", "region", "score_version"])
    write_diagnostics(args.output, merged, metadata, eligible, root)
    ledger_columns = [
        "forecast_week", "environment_bundle_available_timestamp", "forecast_issue_timestamp_utc", "observation_first_available_timestamp", "outcome_ingestion_timestamp_utc", "history_mode", "prospective_eligibility", "prospective_eligible", "historical_backfill", "outcome_maturity", "score_version", "source_sha256", "outcome_availability_class", "model_node_id", "canonical_node_id", "region", "predicted_probability", "predicted_conditional_positive_mean", "predicted_underlying_mu", "predicted_unconditional_mean", "observed_presence", "observed_count", "first_ever_positive_flag", "previously_positive_flag", "occurrence_nll_contribution", "joint_nll_contribution", "positive_count_absolute_error", "positive_count_squared_error", "distance_to_any_prior_positive_km", "distance_to_prev4_positive_km", "weeks_since_detection_within_50km", "percentile_rank_region", "percentile_rank_full_domain",
    ]
    for column, default in [("environment_bundle_available_timestamp", "unknown"), ("history_mode", "event_causal"), ("prospective_eligibility", "retrospective_only"), ("outcome_maturity", args.outcome_maturity), ("score_version", version), ("source_sha256", metadata["sha256"]), ("outcome_availability_class", "no_recorded_observation")]:
        if column not in merged.columns:
            merged[column] = predictions[column].iloc[0] if column in predictions.columns else default
    ledger_rows = merged[ledger_columns].copy()
    ledger_path = root / "prospective_evaluation_ledger.parquet"
    existing = pd.read_parquet(ledger_path) if ledger_path.exists() else pd.DataFrame()
    for column in ledger_columns:
        if column not in existing.columns:
            existing[column] = None
    existing = existing[ledger_columns] if len(existing.columns) else existing
    key_mask = np.zeros(len(existing), dtype=bool) if not len(existing) else (existing["forecast_week"].astype(str) == args.forecast_week) & (pd.to_numeric(existing["score_version"], errors="coerce").fillna(-1).astype(int) == version)
    if key_mask.any():
        old = existing.loc[key_mask].sort_values("model_node_id").reset_index(drop=True)
        new = ledger_rows.sort_values("model_node_id").reset_index(drop=True)
        compare = [column for column in ledger_columns if column not in {"outcome_ingestion_timestamp_utc"}]
        pd.testing.assert_frame_equal(old[compare], new[compare], check_dtype=False, check_exact=False, rtol=1e-7, atol=1e-9)
    else:
        existing = pd.concat([existing, ledger_rows], ignore_index=True) if len(existing.columns) else ledger_rows
        existing.to_parquet(ledger_path, index=False)
    if eligible:
        cumulative = pd.read_parquet(ledger_path)
        cumulative = cumulative.loc[cumulative["prospective_eligible"].astype(bool)].sort_values(["forecast_week", "score_version"]).drop_duplicates("forecast_week", keep="last")
        for region in ["full_revised_domain", "Mexico", "United States"]:
            sub = cumulative if region == "full_revised_domain" else cumulative.loc[cumulative["region"] == region]
            if len(sub) == 0:
                continue
            cumulative_metrics = safe_metrics(sub["observed_count"].to_numpy(int), sub["predicted_probability"].to_numpy(float), sub["predicted_conditional_positive_mean"].to_numpy(float), sub["predicted_underlying_mu"].to_numpy(float), float(model["theta"]), training_prevalence, region, 0, MODEL_ID)
            cumulative_metrics.update({"scope": "cumulative", "region": region, "forecast_week": args.forecast_week, "prospective_eligible": True, "historical_backfill": False, "number_weeks": int(sub["forecast_week"].nunique()), "score_version": version, "outcome_maturity": args.outcome_maturity})
            append_unique_csv(root / "scores" / "prospective_scores.csv", {key: value for key, value in cumulative_metrics.items() if not isinstance(value, (dict, list, np.ndarray))}, ["scope", "forecast_week", "region", "score_version"])
    if not args.test_mode:
        ensure_registry_schema(args.output)
        append_source_history(args.output, metadata, eligible)
        registry_row = pd.read_csv(args.output / "forecast_registry" / "prospective_forecast_registry.csv")
        mask = registry_row["forecast_week"].astype(str) == args.forecast_week
        if not mask.any():
            raise RuntimeError("forecast registry entry is missing")
        registry_row.loc[mask, "outcomes_ingested"] = True
        registry_row.loc[mask, "latest_score_version"] = version
        registry_row.loc[mask, "outcome_maturity"] = args.outcome_maturity
        registry_row.loc[mask, "outcome_first_available_timestamp"] = source_available or "unknown"
        registry_row.loc[mask, "score_status"] = f"{archived_state}_scored_v{version}_{args.outcome_maturity}"
        registry_row.to_csv(args.output / "forecast_registry" / "prospective_forecast_registry.csv", index=False)
        if len(merged.loc[merged["observed_count"] > 0]):
            prior_history = history.copy()
            new_positive = merged.loc[merged["observed_count"] > 0, ["model_node_id", "observed_count"]].copy()
            new_positive["week"] = args.forecast_week
            new_positive["source"] = metadata["sha256"]
            new_positive["available_before_week"] = args.forecast_week
            new_positive["historical_initialization"] = False
            new_positive["first_available_timestamp"] = source_available or "unknown"
            new_positive = new_positive[["week", "model_node_id", "observed_count", "source", "available_before_week", "historical_initialization", "first_available_timestamp"]]
            if not ((prior_history["week"].astype(str) == args.forecast_week).any()):
                pd.concat([prior_history, new_positive], ignore_index=True).drop_duplicates(["week", "model_node_id"]).sort_values(["week", "model_node_id"]).to_parquet(args.output / "state" / "recorded_detection_history.parquet", index=False)
        status = ensure_status_fields(args.output)
        status["latest_scored_week"] = args.forecast_week
        status["latest_score_version"] = version
        status["genuine_prospective_scored_weeks"] = int(pd.read_csv(root / "scores" / "prospective_scores.csv").query("scope == 'weekly' and prospective_eligible == True")["forecast_week"].nunique()) if (root / "scores" / "prospective_scores.csv").exists() else 0
        status["evaluation_status"] = "DELAYED PROSPECTIVE EVALUATION ACTIVE"
        write_json(args.output / "prospective_status.json", status)
    write_map(predictions, root / "maps" / f"forecast_{args.forecast_week}_scored.svg", f"{MODEL_ID} forecast {args.forecast_week} — scored", merged["observed_count"].to_numpy(int))
    print(json.dumps({"status": "scored", "forecast_week": args.forecast_week, "prospective_eligibility": archived_state, "prospective_eligible": eligible, "historical_backfill": historical_backfill, "score_version": version, "outcome_maturity": args.outcome_maturity, "observed_positive_node_weeks": int(merged["observed_presence"].sum()), "score_path": str(version_path)}, indent=2))
    return {"metrics": metrics, "eligible": eligible, "score_version": version}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--forecast-week", required=True)
    parser.add_argument("--mode", choices=["forecast", "score", "dry-run", "readiness"], required=True)
    parser.add_argument("--observation-source", type=Path)
    parser.add_argument("--source-available-timestamp-utc")
    parser.add_argument("--environment-available-timestamp-utc")
    parser.add_argument("--environment-availability-status", choices=["verified", "uncertain"], default="uncertain")
    parser.add_argument("--issue-timestamp-utc")
    parser.add_argument("--history-mode", choices=["event_causal", "availability_causal"])
    parser.add_argument("--score-version", type=int, default=1)
    parser.add_argument("--outcome-maturity", choices=sorted(OUTCOME_MATURITY), default="provisional")
    parser.add_argument("--test-mode", action="store_true")
    parser.add_argument("--model-output", type=Path, default=Path("/project/disease_ecology/STGNN-output/revised_model_data"))
    parser.add_argument("--output", type=Path, default=Path("/project/disease_ecology/STGNN-output/v2_prospective"))
    parser.add_argument("--input-bundle", type=Path)
    args = parser.parse_args()
    if args.mode == "score" and args.observation_source is None:
        parser.error("--observation-source is required for --mode score")
    args.score_version = score_version(args.score_version)
    if args.mode == "score":
        run_score(args)
    elif args.mode == "readiness":
        run_readiness(args)
    else:
        run_forecast(args)


if __name__ == "__main__":
    main()
