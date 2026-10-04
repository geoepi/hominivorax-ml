#!/usr/bin/env python3
"""Create the immutable Task 3C STGNN-Hurdle-V2A development fit.

This script reuses the Task 3B M1 data, causal-front, preprocessing, and exact
hurdle-fitting contracts.  It fits one model on the complete authorized
historical response period through 2026-W29 and writes only frozen model and
prospective-harness provenance artifacts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

SCRIPT_ROOT = Path(__file__).resolve().parent
import sys

sys.path.insert(0, str(SCRIPT_ROOT))
from run_task3b_v2a import (  # noqa: E402
    BASE_FEATURES,
    EXPECTED_NODE_COUNT,
    EXPECTED_RESPONSE_WEEKS,
    PRIMARY_FRONT_AVAILABILITY,
    PRIMARY_FRONT_CONTINUOUS,
    build_arrays,
    build_front_features,
    fit_state,
    load_data,
    predict_state,
    safe_metrics,
)


MODEL_ID = "STGNN-Hurdle-V2A"
MODEL_NAME = "M1"
PENALTY = 0.01
FREEZE_DATE = "2026-10-03"
TASK3B_SHA = "66443123df639c1ae811aeb58ef87546814ecd6e"
SOURCE_SHA = "a3d55f3ddf867087b578df803920bf59c6c303fa695e3218a5f3463e596d497e"
SOURCE_PATH = Path("/project/disease_ecology/NWScrewworm/data/processed_data/case_detections/combined_clean_obs_2027-07-31.csv")
FEATURE_ORDER = BASE_FEATURES + PRIMARY_FRONT_CONTINUOUS + PRIMARY_FRONT_AVAILABILITY


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_sha(repo: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()


def task3b_is_ancestor(repo: Path) -> bool:
    return subprocess.run(
        ["git", "merge-base", "--is-ancestor", TASK3B_SHA, "HEAD"],
        cwd=repo,
        check=False,
    ).returncode == 0


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


def source_metadata() -> dict[str, Any]:
    stat = SOURCE_PATH.stat()
    source = pd.read_csv(SOURCE_PATH, usecols=["date"])
    dates = pd.to_datetime(source["date"], errors="coerce")
    return {
        "file_path": str(SOURCE_PATH),
        "sha256": sha256_file(SOURCE_PATH),
        "row_count": int(len(source)),
        "minimum_date": str(dates.min().date()),
        "maximum_date": str(dates.max().date()),
        "file_mtime_utc": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(timespec="seconds"),
        "ingestion_timestamp_utc": utc_now(),
        "status": "historical_initialization_not_prospective",
        "prospective_eligible_rows": 0,
    }


def write_coefficients(path: Path, state: dict[str, Any]) -> None:
    rows = []
    names = ["intercept"] + FEATURE_ORDER
    for component, key in [("occurrence", "occurrence_coefficients"), ("positive_count", "count_coefficients")]:
        coefficients = np.asarray(state[key], dtype=float)
        if len(coefficients) != len(names):
            raise AssertionError(f"{component} coefficient width changed")
        rows.extend({"component": component, "feature": name, "coefficient": float(value)} for name, value in zip(names, coefficients))
    pd.DataFrame(rows).to_csv(path, index=False)


def write_availability_audit(path: Path, manifest: dict[str, Any]) -> None:
    rows = []
    for feature in manifest["base_feature_order"][:12]:
        rows.append({
            "feature": feature,
            "source": "/project/disease_ecology/STGNN-output/revised_model_data/raw/dynamic_features.npy",
            "nominal_week_represented": "forecast week t",
            "actual_file_availability_timing": f"No per-week acquisition timestamp; production manifest mtime {manifest['source_manifest_file_mtime_utc']}",
            "classification": "uncertain",
            "pre_outcome_week_t_availability": "not established",
            "audit_note": "The array is a retrospective production artifact. It cannot by itself establish operational pre-outcome availability.",
        })
    pd.DataFrame(rows).to_csv(path, index=False)


def initialize_registry(output: Path, model_manifest_sha: str, input_manifest_sha: str) -> None:
    registry = output / "forecast_registry" / "prospective_forecast_registry.csv"
    if not registry.exists():
        registry.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(columns=[
            "forecast_week", "issue_timestamp", "prediction_path", "prediction_sha256",
            "model_sha256", "input_sha256", "history_cutoff", "outcomes_ingested",
            "score_status", "test_mode",
        ]).to_csv(registry, index=False)
    status = output / "prospective_status.json"
    if not status.exists():
        write_json(status, {
            "model_id": MODEL_ID,
            "model_manifest_sha": model_manifest_sha,
            "input_manifest_sha": input_manifest_sha,
            "freeze_date": FREEZE_DATE,
            "latest_forecast_week": None,
            "latest_scored_week": None,
            "number_genuine_prospective_weeks": 0,
            "number_genuine_prospective_positive_node_weeks": 0,
            "number_first_ever_positive_nodes": 0,
            "evaluation_status": "HARNESS READY — AWAITING FUTURE DATA",
        })
    source_history = output / "manifests" / "source_history_manifest.csv"
    if not source_history.exists():
        source_history.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(columns=[
            "source_path", "sha256", "row_count", "minimum_date", "maximum_date",
            "file_mtime_utc", "ingestion_timestamp_utc", "status", "prospective_eligible_rows",
        ]).to_csv(source_history, index=False)
    ledger = output / "prospective_evaluation_ledger.parquet"
    if not ledger.exists():
        pd.DataFrame(columns=[
            "forecast_week", "forecast_issue_timestamp_utc", "outcome_ingestion_timestamp_utc",
            "prospective_eligible", "model_node_id", "canonical_node_id", "region",
            "predicted_probability", "predicted_conditional_positive_mean", "predicted_unconditional_mean",
            "predicted_underlying_mu",
            "observed_presence", "observed_count", "first_ever_positive_flag", "previously_positive_flag",
            "occurrence_nll_contribution", "joint_nll_contribution", "positive_count_absolute_error",
            "positive_count_squared_error", "distance_to_any_prior_positive_km", "distance_to_prev4_positive_km",
            "weeks_since_detection_within_50km", "percentile_rank_region", "percentile_rank_full_domain",
        ]).to_parquet(ledger, index=False)


def initialize_history(output: Path, data: dict[str, Any]) -> None:
    """Persist positive historical detections used to initialize future state."""
    rows = []
    response_lookup = {str(week): index for index, week in enumerate(data["weeks"]["iso_week"].astype(str))}
    for audit_index, week in enumerate(data["audit_week_labels"]):
        if week in response_lookup:
            counts = np.asarray(data["counts"][response_lookup[week]], dtype=int)
            source = "immutable_v1_response_target"
        else:
            counts = np.asarray(data["audit_counts"][audit_index], dtype=int)
            source = "pre_response_classification_initialization"
        for node_id in np.flatnonzero(counts > 0):
            rows.append({
                "week": str(week),
                "model_node_id": int(node_id),
                "observed_count": int(counts[node_id]),
                "source": source,
                "available_before_week": str(week),
                "historical_initialization": True,
            })
    history = output / "state" / "recorded_detection_history.parquet"
    history.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows)
    if history.exists():
        existing = pd.read_parquet(history)
        if not existing.equals(frame):
            raise RuntimeError("initialized recorded-detection history already exists and differs")
    else:
        frame.to_parquet(history, index=False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-output", type=Path, default=Path("/project/disease_ecology/STGNN-output/revised_model_data"))
    parser.add_argument("--audit-output", type=Path, default=Path("/project/disease_ecology/STGNN-output/v2_audit"))
    parser.add_argument("--output", type=Path, default=Path("/project/disease_ecology/STGNN-output/v2_prospective"))
    args = parser.parse_args()
    repo = SCRIPT_ROOT.parent
    if not task3b_is_ancestor(repo):
        raise RuntimeError(f"Task 3C branch must descend from Task 3B HEAD {TASK3B_SHA}; current {git_sha(repo)}")
    data = load_data(args.model_output, args.audit_output)
    if data["source_sha"] != SOURCE_SHA or len(data["weeks"]) != EXPECTED_RESPONSE_WEEKS:
        raise AssertionError("historical production data contract changed")
    training_times = list(range(EXPECTED_RESPONSE_WEEKS))
    front_dir = args.output / "model" / "historical_front_features"
    front_frame, front = build_front_features(data, front_dir)
    arrays = build_arrays(data, front)
    state, _, _, _, _, theta = fit_state(arrays[MODEL_NAME], FEATURE_ORDER, data["counts"], training_times, [0], PENALTY)
    p, conditional, mu, _ = predict_state(state, arrays[MODEL_NAME], training_times)
    fit_metrics = safe_metrics(
        data["counts"], p, conditional, mu, theta,
        float(np.mean(data["counts"] > 0)), "full_revised_domain", 0, MODEL_ID,
    )
    if not state["fit_info"].get("occurrence_success") or not state["fit_info"].get("count_success"):
        raise RuntimeError(f"frozen M1 fit did not converge: {state['fit_info']}")
    if not np.isfinite(np.asarray(state["occurrence_coefficients"])).all() or not np.isfinite(np.asarray(state["count_coefficients"])).all() or theta <= 0:
        raise RuntimeError("invalid frozen fit parameters")

    model_dir = args.output / "model"
    manifests_dir = args.output / "manifests"
    model_dir.mkdir(parents=True, exist_ok=True)
    manifests_dir.mkdir(parents=True, exist_ok=True)
    preprocessing = state["scaling"]
    model_payload = {
        "model_id": MODEL_ID,
        "candidate": MODEL_NAME,
        "penalty": PENALTY,
        "likelihood": "exact_joint_hurdle_nll",
        "occurrence": "Bernoulli/logistic",
        "positive_count": "zero-truncated negative binomial",
        "dispersion": "one global theta",
        "feature_order": FEATURE_ORDER,
        "occurrence_coefficients": state["occurrence_coefficients"],
        "count_coefficients": state["count_coefficients"],
        "theta": theta,
        "preprocessing": preprocessing,
        "fit_info": state["fit_info"],
        "training_weeks": data["weeks"]["iso_week"].astype(str).tolist(),
        "training_start": str(data["weeks"]["iso_week"].iloc[0]),
        "training_end": str(data["weeks"]["iso_week"].iloc[-1]),
        "frozen_fit_status": "V2A_FROZEN_DEVELOPMENT_FIT",
    }
    write_json(model_dir / "v2a_frozen_model.json", model_payload)
    write_json(model_dir / "v2a_preprocessing.json", preprocessing)
    (model_dir / "v2a_feature_order.txt").write_text("\n".join(FEATURE_ORDER) + "\n", encoding="utf-8")
    write_coefficients(model_dir / "v2a_coefficients.csv", state)
    source = source_metadata()
    source_manifest = args.model_output / "manifests" / "revised_production_manifest.json"
    source_manifest_sha = sha256_file(source_manifest)
    source_manifest_json = json.loads(source_manifest.read_text())
    source_manifest_mtime = source_manifest_json.get("observation_source", {}).get("file_mtime", "unknown")
    base_manifest = {
        "model_id": MODEL_ID,
        "candidate": MODEL_NAME,
        "freeze_date": FREEZE_DATE,
        "task3b_git_sha": TASK3B_SHA,
        "git_sha": git_sha(repo),
        "source_observation_sha256": SOURCE_SHA,
        "source_observation_path": str(SOURCE_PATH),
        "estimand": "Probability and conditional positive count of a recorded detection in a node-week given current environment, hosts, seasonality, and strictly prior recorded-detection history.",
        "does_not_estimate": ["true occupancy", "true abundance", "detection probability", "reporting probability", "biological dispersal"],
        "feature_count": len(FEATURE_ORDER),
        "feature_order": FEATURE_ORDER,
        "base_feature_order": BASE_FEATURES,
        "front_continuous_features": PRIMARY_FRONT_CONTINUOUS,
        "front_availability_features": PRIMARY_FRONT_AVAILABILITY,
        "front_definitions": {
            "distance_to_any_prior_positive_log1p": "log1p minimum projected domain distance in km to any recorded positive in weeks < t",
            "distance_to_prev4_positive_log1p": "log1p minimum projected domain distance in km to a recorded positive in t-1 through t-4",
            "weeks_since_detection_within_50km_log1p": "log1p weeks since most recent recorded positive within 50 km using weeks < t",
        },
        "placeholder_rules": {
            "distance": "fixed maximum domain projected inter-node distance, paired with availability indicator",
            "recency": "fixed audit-window length + 1 weeks, paired with availability indicator",
            "availability_encoding": "0/1, unstandardized",
        },
        "penalty": PENALTY,
        "likelihood": "exact_joint_hurdle_nll",
        "occurrence": "Bernoulli/logistic",
        "positive_count": "zero-truncated negative binomial",
        "dispersion": "one global theta",
        "theta": theta,
        "preprocessing": "Task 3B fold-safe contract fit on complete 2025-W01 through 2026-W29 historical response period; continuous features standardized, indicators and week_sin/week_cos unchanged",
        "training_period": {"start": str(data["weeks"]["iso_week"].iloc[0]), "end": str(data["weeks"]["iso_week"].iloc[-1]), "week_count": len(data["weeks"])},
        "historical_data_status": "historical_development_or_evaluated_data",
        "validation_provenance": {
            "task3b_branch": "feature/v2-front-hurdle",
            "task3b_head": TASK3B_SHA,
            "selection_folds": "Folds 1-4",
            "non_independent_folds": [5, 6],
            "selected_penalty": PENALTY,
        },
        "optimizer_settings": {"method": "L-BFGS-B", "maxiter": 2000, "objective": "exact_joint_hurdle_nll", "technical_reason": "Task 3B reproducible CPU convergence safeguard"},
        "future_evaluation_policy": "No currently available outcomes qualify as an unseen V2 test. Only forecasts frozen before post-2026-10-03 outcome ingestion can contribute to genuinely prospective evaluation.",
        "no_online_retraining": True,
        "fit_metrics": {key: value for key, value in fit_metrics.items() if not isinstance(value, (dict, list))},
        "artifact_paths": {
            "frozen_model": "model/v2a_frozen_model.json",
            "preprocessing": "model/v2a_preprocessing.json",
            "coefficients": "model/v2a_coefficients.csv",
            "feature_order": "model/v2a_feature_order.txt",
        },
        "source_manifest_sha256": source_manifest_sha,
        "source_manifest_file_mtime_utc": source_manifest_mtime,
        "created_utc": utc_now(),
    }
    manifest_path = manifests_dir / "v2a_frozen_specification_manifest.json"
    write_json(manifest_path, base_manifest)
    (manifests_dir / "v2a_frozen_specification_manifest.json.sha256").write_text(f"{sha256_file(manifest_path)}  {manifest_path.name}\n", encoding="utf-8")
    write_availability_audit(model_dir / "current_week_environment_availability_audit.csv", {"base_feature_order": BASE_FEATURES, "source_manifest_file_mtime_utc": source_manifest_mtime})
    input_manifest = {
        "input_manifest_type": "historical_predictor_bundle",
        "source_manifest_path": str(source_manifest),
        "source_manifest_sha256": source_manifest_sha,
        "raw_predictor_root": str(args.model_output / "raw"),
        "latest_available_predictor_week": str(data["weeks"]["iso_week"].iloc[-1]),
        "node_count": EXPECTED_NODE_COUNT,
        "dynamic_feature_count": 12,
        "availability_status": "historical retrospective bundle; current-week operational timing uncertain",
        "created_utc": utc_now(),
    }
    input_manifest_path = manifests_dir / "prospective_input_manifest.json"
    write_json(input_manifest_path, input_manifest)
    input_manifest_sha = sha256_file(input_manifest_path)
    write_json(manifests_dir / "v2a_fit_summary.json", {"model_id": MODEL_ID, "theta": theta, "fit_info": state["fit_info"], "fit_metrics": fit_metrics, "source": source})
    pd.DataFrame([source]).to_csv(manifests_dir / "source_history_manifest.csv", index=False)
    initialize_history(args.output, data)
    initialize_registry(args.output, sha256_file(manifest_path), input_manifest_sha)
    checksums = []
    for path in sorted(args.output.rglob("*")):
        if path.is_file() and path.name != "v2a_frozen_model_checksums.csv":
            checksums.append({"relative_path": str(path.relative_to(args.output)), "size_bytes": path.stat().st_size, "sha256": sha256_file(path)})
    pd.DataFrame(checksums).to_csv(manifests_dir / "v2a_frozen_model_checksums.csv", index=False)
    print(json.dumps({"status": "complete", "model_id": MODEL_ID, "theta": theta, "git_sha": git_sha(repo), "model_manifest_sha": sha256_file(manifest_path), "input_manifest_sha": input_manifest_sha}, indent=2))


if __name__ == "__main__":
    main()
