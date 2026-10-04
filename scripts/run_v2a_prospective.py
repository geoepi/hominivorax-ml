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
    return end.replace(tzinfo=timezone.utc).isoformat(timespec="seconds")


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
    if history[["week", "model_node_id"]].duplicated().any() or (history["observed_count"] <= 0).any():
        raise RuntimeError("recorded-detection history contains invalid or duplicate positive rows")
    return history.sort_values(["week", "model_node_id"]).reset_index(drop=True)


def front_state_for_week(history: pd.DataFrame, forecast_week: str, nodes: pd.DataFrame) -> dict[str, np.ndarray | str | float]:
    if forecast_week <= SOURCE_HISTORY_START:
        labels = week_range(SOURCE_HISTORY_START, forecast_week)
    else:
        labels = week_range(SOURCE_HISTORY_START, forecast_week)
    grouped = history.loc[history["week"].isin(labels) & (history["week"] < forecast_week)].groupby("week")["model_node_id"]
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
) -> pd.DataFrame:
    if forecast_week not in predictor["weeks"]:
        raise RuntimeError(f"current-week environmental predictors for {forecast_week} are not available")
    index = predictor["weeks"].index(forecast_week)
    nodes = predictor["nodes"]
    front = front_state_for_week(history, forecast_week, nodes)
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
        "history_cutoff_week": front["history_cutoff_week"],
        "history_cutoff_timestamp": week_end_timestamp(front["history_cutoff_week"]),
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
            if any(str(old.get(key)) != str(row.get(key)) for key in row):
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
    if "revised_domain_membership" in raw.columns:
        raw = raw.loc[raw["revised_domain_membership"].astype(bool)].copy()
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
    prior_nodes = set(history.loc[history["week"] < str(predictions["forecast_week"].iloc[0]), "model_node_id"].astype(int))
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
    try:
        import matplotlib.pyplot as plt
    except Exception as exc:  # pragma: no cover - environment-specific fallback
        write_json(Path(str(path) + ".unavailable.json"), {"status": "map_unavailable", "error": str(exc)})
        return
    fig, ax = plt.subplots(figsize=(10, 7))
    points = ax.scatter(frame["lon"], frame["lat"], c=frame["predicted_probability"], s=3, cmap="viridis", vmin=0, vmax=1)
    if observed is not None and np.any(observed > 0):
        sub = frame.loc[observed > 0]
        ax.scatter(sub["lon"], sub["lat"], facecolors="none", edgecolors="red", s=20, linewidths=0.7, label="recorded positive")
        ax.legend(loc="upper left")
    ax.set_title(title)
    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")
    fig.colorbar(points, ax=ax, label="predicted recorded-detection probability")
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, format="svg")
    plt.close(fig)


def run_forecast(args: argparse.Namespace) -> dict[str, Any]:
    manifest, model, model_manifest_sha, frozen_input_sha = require_frozen_model(args.output)
    predictor = load_predictor_bundle(args.input_bundle or args.model_output)
    history = load_history(args.output)
    if iso_date(args.forecast_week) <= date.fromisoformat(FREEZE_DATE) and not args.test_mode:
        raise RuntimeError("historical weeks require --test-mode; production forecasts must be post-freeze")
    available = args.forecast_week in predictor["weeks"]
    if args.mode == "dry-run":
        result = {
            "status": "READY" if available else "NOT_READY",
            "forecast_week": args.forecast_week,
            "history_cutoff_week": previous_week(args.forecast_week),
            "predictor_week_available": available,
            "model_manifest_sha": model_manifest_sha,
            "input_manifest_sha": frozen_input_sha,
            "test_mode": bool(args.test_mode),
            "operational_feasibility": "PARTIAL" if available else "FALSE",
            "reason": None if available else "no current-week environmental predictor bundle is available",
        }
        print(json.dumps(result, indent=2))
        return result
    issue_timestamp = args.issue_timestamp_utc or utc_now()
    frame = make_prediction_frame(predictor, model, model_manifest_sha, frozen_input_sha, history, args.forecast_week, issue_timestamp)
    root = args.output / "sandbox" if args.test_mode else args.output
    prediction_path = root / "predictions" / f"prospective_predictions_{args.forecast_week}.parquet"
    prediction_sha = immutable_parquet(frame, prediction_path)
    write_map(frame, root / "maps" / f"forecast_{args.forecast_week}_preoutcome.svg", f"{MODEL_ID} forecast {args.forecast_week} — pre-outcome", None)
    if not args.test_mode:
        append_unique_csv(args.output / "forecast_registry" / "prospective_forecast_registry.csv", {
            "forecast_week": args.forecast_week,
            "issue_timestamp": issue_timestamp,
            "prediction_path": str(prediction_path),
            "prediction_sha256": prediction_sha,
            "model_sha256": model_manifest_sha,
            "input_sha256": frozen_input_sha,
            "history_cutoff": previous_week(args.forecast_week),
            "outcomes_ingested": False,
            "score_status": "awaiting_outcomes",
            "test_mode": False,
        }, ["forecast_week"])
        status = json.loads((args.output / "prospective_status.json").read_text())
        status["latest_forecast_week"] = args.forecast_week
        write_json(args.output / "prospective_status.json", status)
    print(json.dumps({"status": "forecast_frozen", "forecast_week": args.forecast_week, "prediction_path": str(prediction_path), "prediction_sha256": prediction_sha, "test_mode": bool(args.test_mode)}, indent=2))
    return {"frame": frame, "prediction_path": prediction_path, "prediction_sha": prediction_sha, "manifest": manifest, "model": model, "model_manifest_sha": model_manifest_sha, "history": history, "predictor": predictor}


def append_source_history(output: Path, metadata: dict[str, Any], eligible: bool) -> None:
    path = output / "manifests" / "source_history_manifest.csv"
    row = dict(metadata)
    row["status"] = "prospective_eligible" if eligible else "historical_backfill"
    row["prospective_eligible_rows"] = int(eligible)
    append_unique_csv(path, row, ["sha256"])


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
    status = json.loads((output / "prospective_status.json").read_text())
    scores_path = output / "scores" / "prospective_scores.csv"
    ledger_path = output / "prospective_evaluation_ledger.parquet"
    if scores_path.exists():
        scores = pd.read_csv(scores_path)
        eligible = scores.loc[(scores["scope"] == "weekly") & (scores["prospective_eligible"].astype(str).str.lower() == "true")]
        status["number_genuine_prospective_weeks"] = int(eligible["forecast_week"].nunique())
    if ledger_path.exists():
        ledger = pd.read_parquet(ledger_path)
        eligible_ledger = ledger.loc[ledger["prospective_eligible"].astype(bool)]
        status["number_genuine_prospective_positive_node_weeks"] = int(eligible_ledger["observed_presence"].sum())
        status["number_first_ever_positive_nodes"] = int(eligible_ledger["first_ever_positive_flag"].sum())
    status["evaluation_status"] = "PROSPECTIVE EVALUATION ACTIVE" if status["number_genuine_prospective_weeks"] else "HARNESS READY — AWAITING FUTURE DATA"
    write_json(output / "prospective_status.json", status)


def run_score(args: argparse.Namespace) -> dict[str, Any]:
    manifest, model, model_manifest_sha, _ = require_frozen_model(args.output)
    root = args.output / "sandbox" if args.test_mode else args.output
    prediction_path = root / "predictions" / f"prospective_predictions_{args.forecast_week}.parquet"
    checksum_path = Path(str(prediction_path) + ".sha256")
    if not prediction_path.exists() or not checksum_path.exists():
        raise RuntimeError("no immutable forecast exists for score mode")
    stored_sha = checksum_path.read_text().split()[0]
    if stored_sha != sha256_file(prediction_path):
        raise RuntimeError("forecast checksum does not match archived forecast")
    predictions = pd.read_parquet(prediction_path)
    if "observed_count" in predictions.columns or "observed_presence" in predictions.columns:
        raise RuntimeError("forecast artifact contains outcome fields")
    if predictions["model_manifest_sha"].nunique() != 1 or predictions["model_manifest_sha"].iloc[0] != model_manifest_sha:
        raise RuntimeError("forecast model manifest does not match frozen model")
    history = load_history(args.output)
    outcomes, metadata = source_observations(args.observation_source, args.forecast_week, NODE_COUNT)
    issue_timestamp = parse_timestamp(str(predictions["forecast_issue_timestamp_utc"].iloc[0]))
    source_available = parse_timestamp(args.source_available_timestamp_utc) if args.source_available_timestamp_utc else parse_timestamp(metadata["file_mtime_utc"])
    eligible = (not args.test_mode) and (iso_date(args.forecast_week) > iso_date("2026-W29")) and source_available > issue_timestamp
    historical_backfill = not eligible
    full_outcomes = pd.DataFrame({"forecast_week": args.forecast_week, "model_node_id": np.arange(NODE_COUNT, dtype=int), "observed_count": 0})
    selected = outcomes.loc[outcomes["week"] == args.forecast_week, ["model_node_id", "observed_count"]]
    full_outcomes.loc[selected["model_node_id"].to_numpy(int), "observed_count"] = selected["observed_count"].to_numpy(int)
    full_outcomes["observed_presence"] = (full_outcomes["observed_count"] > 0).astype(np.int8)
    full_outcomes["source_sha256"] = metadata["sha256"]
    full_outcomes["outcome_ingestion_timestamp_utc"] = utc_now()
    full_outcomes["prospective_eligible"] = eligible
    full_outcomes["historical_backfill"] = historical_backfill
    outcome_path = root / "outcomes" / f"prospective_outcomes_{args.forecast_week}.parquet"
    immutable_parquet(full_outcomes, outcome_path)
    training_prevalence = float(manifest["fit_metrics"].get("training_prevalence", 0.0))
    metrics, merged = score_frame(predictions, full_outcomes, history, predictions, float(model["theta"]), training_prevalence, eligible)
    metrics["historical_backfill"] = historical_backfill
    metrics["source_sha256"] = metadata["sha256"]
    score_path = root / "scores" / "prospective_scores.csv"
    row = {"scope": "weekly", "region": "full_revised_domain", **{key: value for key, value in metrics.items() if not isinstance(value, (dict, list, np.ndarray))}}
    append_unique_csv(score_path, row, ["scope", "forecast_week", "region"])
    regional_rows = []
    for region in ["Mexico", "United States", "full_revised_domain"]:
        sub = merged if region == "full_revised_domain" else merged.loc[merged["country_or_region"] == region]
        if len(sub) == 0:
            continue
        reg = safe_metrics(sub["observed_count"].to_numpy(int), sub["predicted_probability"].to_numpy(float), sub["predicted_conditional_positive_mean"].to_numpy(float), sub["predicted_underlying_mu"].to_numpy(float), float(model["theta"]), training_prevalence, region, 0, MODEL_ID)
        reg.update({"scope": "weekly", "region": region, "forecast_week": args.forecast_week, "prospective_eligible": eligible, "historical_backfill": historical_backfill})
        regional_rows.append(reg)
    for reg in regional_rows:
        append_unique_csv(root / "scores" / "prospective_regional_scores.csv", {key: value for key, value in reg.items() if not isinstance(value, (dict, list, np.ndarray))}, ["scope", "forecast_week", "region"])
    write_diagnostics(args.output, merged, metadata, eligible, root)
    ledger_columns = [
        "forecast_week", "forecast_issue_timestamp_utc", "outcome_ingestion_timestamp_utc", "prospective_eligible", "model_node_id", "canonical_node_id", "region", "predicted_probability", "predicted_conditional_positive_mean", "predicted_underlying_mu", "predicted_unconditional_mean", "observed_presence", "observed_count", "first_ever_positive_flag", "previously_positive_flag", "occurrence_nll_contribution", "joint_nll_contribution", "positive_count_absolute_error", "positive_count_squared_error", "distance_to_any_prior_positive_km", "distance_to_prev4_positive_km", "weeks_since_detection_within_50km", "percentile_rank_region", "percentile_rank_full_domain",
    ]
    ledger_rows = merged[ledger_columns].copy()
    ledger_path = root / "prospective_evaluation_ledger.parquet"
    if ledger_path.exists():
        existing = pd.read_parquet(ledger_path)
        if len(existing) and (existing["forecast_week"].astype(str) == args.forecast_week).any():
            old = existing.loc[existing["forecast_week"].astype(str) == args.forecast_week].sort_values("model_node_id").reset_index(drop=True)
            new = ledger_rows.sort_values("model_node_id").reset_index(drop=True)
            pd.testing.assert_frame_equal(old[ledger_columns], new[ledger_columns], check_dtype=False, check_exact=False, rtol=1e-7, atol=1e-9)
        else:
            pd.concat([existing, ledger_rows], ignore_index=True).to_parquet(ledger_path, index=False)
    else:
        ledger_rows.to_parquet(ledger_path, index=False)
    if eligible:
        cumulative = pd.read_parquet(ledger_path).loc[lambda frame: frame["prospective_eligible"].astype(bool)].copy()
        for region in ["full_revised_domain", "Mexico", "United States"]:
            sub = cumulative if region == "full_revised_domain" else cumulative.loc[cumulative["region"] == region]
            if len(sub) == 0:
                continue
            cumulative_metrics = safe_metrics(
                sub["observed_count"].to_numpy(int),
                sub["predicted_probability"].to_numpy(float),
                sub["predicted_conditional_positive_mean"].to_numpy(float),
                sub["predicted_underlying_mu"].to_numpy(float),
                float(model["theta"]), training_prevalence, region, 0, MODEL_ID,
            )
            cumulative_metrics.update({
                "scope": "cumulative",
                "region": region,
                "forecast_week": args.forecast_week,
                "prospective_eligible": True,
                "historical_backfill": False,
                "number_weeks": int(sub["forecast_week"].nunique()),
            })
            append_unique_csv(root / "scores" / "prospective_scores.csv", {key: value for key, value in cumulative_metrics.items() if not isinstance(value, (dict, list, np.ndarray))}, ["scope", "forecast_week", "region"])
    if not args.test_mode:
        append_source_history(args.output, metadata, eligible)
        registry_row = pd.read_csv(args.output / "forecast_registry" / "prospective_forecast_registry.csv")
        mask = registry_row["forecast_week"].astype(str) == args.forecast_week
        if not mask.any():
            raise RuntimeError("forecast registry entry is missing")
        registry_row.loc[mask, "outcomes_ingested"] = True
        registry_row.loc[mask, "score_status"] = "prospective_eligible_scored" if eligible else "historical_backfill_scored"
        registry_row.to_csv(args.output / "forecast_registry" / "prospective_forecast_registry.csv", index=False)
        if len(merged.loc[merged["observed_count"] > 0]):
            prior_history = history.copy()
            new_positive = merged.loc[merged["observed_count"] > 0, ["model_node_id", "observed_count"]].copy()
            new_positive["week"] = args.forecast_week
            new_positive["source"] = metadata["sha256"]
            new_positive["available_before_week"] = args.forecast_week
            new_positive["historical_initialization"] = False
            new_positive = new_positive[["week", "model_node_id", "observed_count", "source", "available_before_week", "historical_initialization"]]
            if not ((prior_history["week"].astype(str) == args.forecast_week).any()):
                pd.concat([prior_history, new_positive], ignore_index=True).drop_duplicates(["week", "model_node_id"]).sort_values(["week", "model_node_id"]).to_parquet(args.output / "state" / "recorded_detection_history.parquet", index=False)
        update_status(args.output)
        write_map(predictions, args.output / "maps" / f"forecast_{args.forecast_week}_scored.svg", f"{MODEL_ID} forecast {args.forecast_week} — scored", merged["observed_count"].to_numpy(int))
    print(json.dumps({"status": "scored", "forecast_week": args.forecast_week, "prospective_eligible": eligible, "historical_backfill": historical_backfill, "observed_positive_node_weeks": int(merged["observed_presence"].sum()), "score_path": str(score_path)}, indent=2))
    return {"metrics": metrics, "eligible": eligible}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--forecast-week", required=True)
    parser.add_argument("--mode", choices=["forecast", "score", "dry-run"], required=True)
    parser.add_argument("--observation-source", type=Path)
    parser.add_argument("--source-available-timestamp-utc")
    parser.add_argument("--issue-timestamp-utc")
    parser.add_argument("--test-mode", action="store_true")
    parser.add_argument("--model-output", type=Path, default=Path("/project/disease_ecology/STGNN-output/revised_model_data"))
    parser.add_argument("--output", type=Path, default=Path("/project/disease_ecology/STGNN-output/v2_prospective"))
    parser.add_argument("--input-bundle", type=Path)
    args = parser.parse_args()
    if args.mode == "score" and args.observation_source is None:
        parser.error("--observation-source is required for --mode score")
    if args.mode == "score":
        run_score(args)
    else:
        run_forecast(args)


if __name__ == "__main__":
    main()
