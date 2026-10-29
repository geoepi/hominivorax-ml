#!/usr/bin/env python3
"""P6 hardened production entry point for the frozen STRUCTURED_A3 contract.

The wrapper deliberately reuses the validated P2/P4/P5 implementations.  It
adds only operational controls: explicit modes, E0 construction, fail-closed
readiness, atomic stage markers, immutable completed runs, monitoring, and
verification.  A replay is a labelled historical reconstruction; it is not a
claim that retrospective source files were published at the historical issue
time.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any

import numpy as np
import pandas as pd


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
P5_ROOT = REPOSITORY_ROOT / "analysis" / "p5_operational_contract" / "scripts"
P5A_ROOT = REPOSITORY_ROOT / "analysis" / "p5a_environmental_proxy" / "scripts"
P4_ROOT = REPOSITORY_ROOT / "analysis" / "p4_uncertainty_extrapolation" / "scripts"
sys.path.insert(0, str(P5_ROOT))
sys.path.insert(0, str(P5A_ROOT))
sys.path.insert(0, str(P4_ROOT))
import run_p5_operational_contract as p5  # noqa: E402
import run_p5a_environmental_proxy as p5a  # noqa: E402
from p5_contract import (  # noqa: E402
    MODEL_ID,
    MODEL_SHA256,
    P4_SUPPORT_CLASSES,
    P5ContractError,
    issue_timestamp,
    jsonable,
    parse_iso_week,
    sha256_file,
    target_week,
)


P6_STAGES = (
    "PREFLIGHT_COMPLETE",
    "INPUTS_VALIDATED",
    "PREDICTOR_MATRIX_COMPLETE",
    "INFERENCE_COMPLETE",
    "SUPPORT_COMPLETE",
    "OUTPUT_VALIDATED",
    "MANIFEST_COMPLETE",
    "RUN_COMPLETE",
)
OUTPUT_COLUMNS = [
    "canonical_node_id", "model_node_id", "issue_week", "target_week", "horizon",
    "p_occurrence", "conditional_count_mean", "expected_count", "full_q025",
    "full_q975", "p_boot_sd", "expected_boot_sd", "novelty_knn_distance",
    "support_class", "warning_status", "warning_flags", "model_uncertainty_status",
    "production_run_id", "model_id", "model_sha256", "proxy_id",
]
ENV_COUNT = 12
HISTORY_FEATURES = list(p5.HISTORY_FEATURES)


class P6Error(RuntimeError):
    """Machine-readable operational failure."""

    def __init__(self, code: str, message: str, state: str = "BLOCKED_INPUT_INVALID"):
        self.code = str(code)
        self.message = str(message)
        self.state = str(state)
        super().__init__(f"{self.code}: {self.message}")


class P6Interrupted(P6Error):
    def __init__(self, stage: str):
        super().__init__("INTENTIONAL_INTERRUPTION", f"stopped after {stage}", "PRODUCTION_RUN_INTERRUPTED")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_payload(payload: Any) -> str:
    return hashlib.sha256(json.dumps(jsonable(payload), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def atomic_write(path: Path, writer) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        writer(temporary)
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_json(path: Path, payload: Any) -> None:
    atomic_write(path, lambda target: target.write_text(json.dumps(jsonable(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8"))


def write_text(path: Path, value: str) -> None:
    atomic_write(path, lambda target: target.write_text(value, encoding="utf-8"))


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    atomic_write(path, lambda target: frame.to_csv(target, index=False))


def write_parquet(path: Path, frame: pd.DataFrame) -> None:
    atomic_write(path, lambda target: frame.to_parquet(target, index=False, compression="zstd"))


def write_npy(path: Path, values: np.ndarray) -> None:
    def writer(target: Path) -> None:
        with target.open("wb") as handle:
            np.save(handle, values, allow_pickle=False)
    atomic_write(path, writer)


def git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "-c", f"safe.directory={REPOSITORY_ROOT.as_posix()}", "rev-parse", "HEAD"],
            cwd=REPOSITORY_ROOT,
            text=True,
        ).strip()
    except Exception:
        return "unknown"


def load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise P6Error("MISSING_PROVENANCE", f"missing JSON artifact: {path}", "BLOCKED_PROVENANCE")
    except json.JSONDecodeError as exc:
        raise P6Error("INVALID_PROVENANCE", f"invalid JSON artifact: {path}: {exc}") from exc


def load_config(path: Path) -> tuple[dict[str, Any], str]:
    config = load_json(path)
    required = ("scientific_model", "operational_contract", "support_specification", "input_contract", "output_contract", "drift")
    missing = [key for key in required if key not in config]
    if missing:
        raise P6Error("PRODUCTION_CONFIG_INVALID", "missing config sections: " + ", ".join(missing), "BLOCKED_PROVENANCE")
    if config["scientific_model"].get("model_id") != MODEL_ID or config["scientific_model"].get("artifact_sha256") != MODEL_SHA256:
        raise P6Error("PRODUCTION_CONFIG_MODEL_MISMATCH", "production config does not identify the frozen model", "BLOCKED_MODEL_INTEGRITY")
    if config["operational_contract"].get("proxy_id") != "E0_LAST_AVAILABLE":
        raise P6Error("PRODUCTION_CONFIG_PROXY_MISMATCH", "P6 requires the frozen E0_LAST_AVAILABLE proxy", "BLOCKED_PROVENANCE")
    return config, sha256_file(path)


def verify_referenced_hashes(config: dict[str, Any]) -> None:
    checks = [
        (config["support_specification"], "support specification"),
        (config["input_contract"], "input contract"),
        (config["output_contract"], "output contract"),
        (config["operational_contract"], "proxy contract"),
    ]
    for section, label in checks:
        relative = section.get("path") or section.get("proxy_contract")
        expected = section.get("sha256") or section.get("proxy_contract_sha256")
        if not relative or not expected:
            raise P6Error("PRODUCTION_CONFIG_INVALID", f"{label} lacks path/hash", "BLOCKED_PROVENANCE")
        path = REPOSITORY_ROOT / relative
        if not path.exists():
            raise P6Error("MISSING_PROVENANCE", f"missing {label}: {path}", "BLOCKED_PROVENANCE")
        if sha256_file(path).lower() != str(expected).lower():
            raise P6Error("CONTRACT_HASH_MISMATCH", f"{label} hash changed: {path}", "BLOCKED_PROVENANCE")
    model_path = REPOSITORY_ROOT / "config" / "production_model_freeze.json"
    expected = config["scientific_model"].get("freeze_manifest_sha256")
    if expected and sha256_file(model_path).lower() != str(expected).lower():
        raise P6Error("FREEZE_MANIFEST_HASH_MISMATCH", "freeze manifest hash changed", "BLOCKED_MODEL_INTEGRITY")


def verify_frozen_model() -> tuple[dict[str, Any], Path, dict[str, Any]]:
    try:
        verification, model_path, model = p5.verify_frozen_model()
    except P5ContractError as exc:
        raise P6Error(exc.code, exc.message, "BLOCKED_MODEL_INTEGRITY") from exc
    except Exception as exc:
        raise P6Error("FROZEN_MODEL_VERIFICATION_FAILED", str(exc), "BLOCKED_MODEL_INTEGRITY") from exc
    if sha256_file(model_path).lower() != MODEL_SHA256.lower() or model.get("model") != MODEL_ID or model.get("feature_count") != 34:
        raise P6Error("MODEL_HASH_MISMATCH", "frozen STRUCTURED_A3 artifact is not the qualified artifact", "BLOCKED_MODEL_INTEGRITY")
    return verification, model_path, model


def previous_week(value: str) -> str:
    year, week = parse_iso_week(value)
    prior = datetime.fromisocalendar(year, week, 1) - pd.Timedelta(days=7)
    iso = prior.isocalendar()
    return f"{iso.year:04d}-W{iso.week:02d}"


def stage_path(root: Path, stage: str) -> Path:
    return root / "stages" / f"{stage}.json"


def write_stage(root: Path, stage: str, run_id: str, input_signature: str, **extra: Any) -> None:
    write_json(stage_path(root, stage), {
        "stage": stage,
        "run_id": run_id,
        "input_signature": input_signature,
        "completed_at": utc_now(),
        **extra,
    })


def maybe_interrupt(args: argparse.Namespace, stage: str) -> None:
    if args.stop_after_stage == stage:
        raise P6Interrupted(stage)


def prepare_root(args: argparse.Namespace, mode: str, config_hash: str) -> dict[str, Any] | None:
    root = args.output_root
    if root.exists() and any(root.iterdir()):
        status_path = root / "status.json"
        if not status_path.exists():
            raise P6Error("OUTPUT_ROOT_NOT_IMMUTABLE", f"non-empty output root has no status: {root}")
        status = load_json(status_path)
        if status.get("terminal_status") == "RUN_COMPLETE":
            if mode == "verify":
                return status
            raise P6Error("DUPLICATE_COMPLETED_RUN", f"completed run already exists at {root}")
        manifest_path = root / "run_manifest.json"
        if manifest_path.exists():
            manifest = load_json(manifest_path)
            if manifest.get("config_sha256") not in (None, config_hash):
                raise P6Error("RESTART_MANIFEST_MISMATCH", "incomplete run has a different production configuration")
            if args.run_id and manifest.get("run_id") not in (None, args.run_id):
                raise P6Error("RESTART_MANIFEST_MISMATCH", "incomplete run has a different run ID")
        return status
    root.mkdir(parents=True, exist_ok=True)
    return None


def source_hash(path: Path) -> str | None:
    return sha256_file(path) if path.exists() else None


def bundle_from_args(args: argparse.Namespace) -> dict[str, Any]:
    try:
        namespace = argparse.Namespace(
            model_output=args.model_output,
            front_features=args.front_features,
            road_night=args.road_night,
            soil=args.soil,
        )
        return p5.load_bundle(namespace)
    except P5ContractError as exc:
        raise P6Error(exc.code, exc.message) from exc
    except FileNotFoundError as exc:
        raise P6Error("BLOCKED_INPUT_MISSING", str(exc), "BLOCKED_INPUT_MISSING") from exc
    except Exception as exc:
        raise P6Error("BLOCKED_INPUT_INVALID", str(exc), "BLOCKED_INPUT_INVALID") from exc


def validate_issue_and_targets(bundle: dict[str, Any], issue_week: str) -> list[str]:
    try:
        parse_iso_week(issue_week)
    except P5ContractError as exc:
        raise P6Error(exc.code, exc.message) from exc
    labels = set(bundle["labels"])
    if issue_week not in labels:
        raise P6Error("INVALID_ISSUE_WEEK", f"issue week is absent from validated bundle: {issue_week}")
    targets = [target_week(issue_week, h) for h in (1, 2, 3)]
    missing = [week for week in targets if week not in labels]
    if missing:
        raise P6Error("MISSING_TARGET_WEEK", "target week(s) absent from validated bundle: " + ", ".join(missing), "BLOCKED_INPUT_MISSING")
    return targets


def validate_p4(args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    try:
        novelty, intervals, uncertainty, info = p5.load_p4_references(args.p4_root)
    except P5ContractError as exc:
        raise P6Error(exc.code, exc.message, "BLOCKED_PROVENANCE") from exc
    except Exception as exc:
        raise P6Error("SUPPORT_REFERENCE_INVALID", str(exc), "BLOCKED_PROVENANCE") from exc
    expected = args.config_data["support_specification"]["sha256"].lower()
    if str(info.get("support_reference_hash", "")).lower() != expected:
        raise P6Error("SUPPORT_REFERENCE_HASH_MISMATCH", "P4 support specification hash does not match P6 config", "BLOCKED_PROVENANCE")
    return novelty, intervals, uncertainty, info


def e0_features(bundle: dict[str, Any], issue_week: str) -> tuple[np.ndarray, dict[str, Any]]:
    labels = bundle["labels"]
    if previous_week(issue_week) not in labels:
        raise P6Error("MISSING_ENVIRONMENT_REFERENCE", f"E0 requires {previous_week(issue_week)} in the environmental archive", "BLOCKED_INPUT_MISSING")
    issue_index = labels.index(issue_week)
    latest_index = labels.index(previous_week(issue_week))
    target_indices = [labels.index(target_week(issue_week, h)) for h in (1, 2, 3)]
    features = np.asarray(bundle["features"], dtype=np.float64).copy()
    state = features[latest_index, :, :ENV_COUNT].copy()
    for index in target_indices:
        features[index, :, :ENV_COUNT] = state
    if not np.isfinite(features[target_indices, :, :]).all():
        raise P6Error("NONFINITE_PREDICTOR_MATRIX", "E0 predictor matrix contains non-finite values")
    return features, {
        "issue_week": issue_week,
        "latest_environment_week": previous_week(issue_week),
        "latest_environment_index": latest_index,
        "issue_index": issue_index,
        "target_indices": target_indices,
        "rule": "copy the latest environment observation legitimately available at T, L(T)=T-1, to h=1,2,3",
        "environmental_predictor_count": ENV_COUNT,
    }


def front_cutoff_issues(bundle: dict[str, Any], issue_week: str, targets: list[str]) -> list[str]:
    labels = bundle["labels"]
    problems = []
    for target in targets:
        index = labels.index(target)
        cutoffs = bundle["front"].iloc[index * 10037 : (index + 1) * 10037]["history_cutoff_week"].dropna().astype(str)
        if any(parse_iso_week(value) > parse_iso_week(issue_week) for value in cutoffs):
            problems.append(f"{target}:history_cutoff_after_issue")
    return problems


def input_records(args: argparse.Namespace, bundle: dict[str, Any], issue_week: str, e0: dict[str, Any], mode: str) -> list[dict[str, Any]]:
    issue = issue_timestamp(issue_week)
    paths = bundle["source_paths"]
    records = []
    for source_id, path, role in (
        ("dynamic_environmental", Path(paths["dynamic_features"]), "E0_REFERENCE_INPUT"),
        ("front_features", Path(paths["front_features"]), "CAUSAL_HISTORY_INPUT"),
        ("road_night", Path(paths["road_night_features"]), "STATIC_INPUT"),
        ("soil", Path(paths["soil_features"]), "STATIC_INPUT"),
        ("production_manifest", Path(paths["production_manifest"]), "STATIC_INPUT"),
    ):
        if not path.exists():
            raise P6Error("MISSING_REQUIRED_INPUT", f"missing {source_id}: {path}", "BLOCKED_INPUT_MISSING")
        timestamp = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        future = timestamp > issue
        state = "FUTURE_DATED" if future else ("CURRENT" if role != "E0_REFERENCE_INPUT" else "ACCEPTABLE_LAG")
        records.append({
            "source_id": source_id,
            "role": role,
            "path": str(path),
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
            "source_timestamp": timestamp.isoformat().replace("+00:00", "Z"),
            "observation_week": e0["latest_environment_week"] if source_id == "dynamic_environmental" else None,
            "freshness_state": state,
            "future_dated_at_issue": future,
            "vintage_evidence": "filesystem-ingestion timestamp; not an authoritative provider release timestamp",
            "mode": mode,
        })
    return records


def readiness(args: argparse.Namespace, bundle: dict[str, Any], issue_week: str, targets: list[str], e0: dict[str, Any], mode: str) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    records = input_records(args, bundle, issue_week, e0, mode)
    blockers: list[str] = []
    warnings: list[str] = []
    env = next(item for item in records if item["source_id"] == "dynamic_environmental")
    if env["future_dated_at_issue"]:
        if mode in {"production", "preflight"}:
            blockers.append("FUTURE_DATED_ENVIRONMENT_SOURCE")
        else:
            warnings.append("HISTORICAL_REPLAY_SOURCE_TIMESTAMP_AFTER_ISSUE")
    history_issues = front_cutoff_issues(bundle, issue_week, targets)
    if history_issues:
        if mode in {"production", "preflight"}:
            blockers.append("HISTORY_CUTOFF_AFTER_ISSUE")
        else:
            warnings.append("HISTORY_CUTOFF_LIMITATION")
    if env["observation_week"] != previous_week(issue_week):
        blockers.append("E0_LATEST_WEEK_MISMATCH")
    return records, sorted(set(blockers)), sorted(set(warnings))


def support_for_features(features: np.ndarray, bundle: dict[str, Any], issue_week: str) -> pd.DataFrame:
    """Recalculate P4 support using the unchanged P4 reference and thresholds."""
    raw_train, train_z, state, reference = p5a.training_reference(features)
    tree = p5a.cKDTree(train_z, leafsize=40, compact_nodes=True, balanced_tree=True)
    try:
        train_loo = tree.query(train_z, k=2, workers=-1)[0][:, 1]
    except TypeError:
        train_loo = tree.query(train_z, k=2)[0][:, 1]
    labels = bundle["labels"]
    eval_indices = [labels.index(target_week(issue_week, h)) for h in (1, 2, 3)]
    raw_eval = np.asarray(features[eval_indices], dtype=np.float64).reshape(-1, features.shape[-1])
    means = np.asarray(state["training_mean"], dtype=np.float64)
    scales = np.asarray(state["training_sd"], dtype=np.float64)
    eval_z = (raw_eval - means[None, :]) / scales[None, :]
    try:
        distance = p5a.nearest_distances(tree, eval_z)
    except Exception as exc:
        raise P6Error("SUPPORT_REFERENCE_INVALID", f"P4 nearest-neighbour support calculation failed: {exc}", "BLOCKED_PROVENANCE") from exc
    support, thresholds = p5a.support_class_from_inputs(raw_eval, eval_z, distance, reference, train_loo)
    rows = []
    for horizon, target in enumerate([target_week(issue_week, h) for h in (1, 2, 3)], start=1):
        part = support.iloc[(horizon - 1) * 10037 : horizon * 10037].copy().reset_index(drop=True)
        part.insert(0, "target_week", target)
        part.insert(1, "horizon", horizon)
        part.insert(2, "model_node_id", np.arange(10037, dtype=np.int64))
        rows.append(part)
    return pd.concat(rows, ignore_index=True)


def make_predictions(bundle: dict[str, Any], features: np.ndarray, model: dict[str, Any], issue_week: str, novelty: pd.DataFrame, intervals: pd.DataFrame, uncertainty: pd.DataFrame) -> pd.DataFrame:
    proxy_bundle = dict(bundle)
    proxy_bundle["features"] = features
    predictions = p5.model_predictions(proxy_bundle, model, issue_week, [1, 2, 3])
    predictions = p5.add_p4_outputs(predictions, issue_week, novelty, intervals, uncertainty)
    support = support_for_features(features, bundle, issue_week)
    predictions = predictions.sort_values(["horizon", "model_node_id"], kind="mergesort").reset_index(drop=True)
    support = support.sort_values(["horizon", "model_node_id"], kind="mergesort").reset_index(drop=True)
    if len(predictions) != len(support):
        raise P6Error("SUPPORT_REFERENCE_COVERAGE_FAILED", "proxy support rows do not cover predictions", "BLOCKED_PROVENANCE")
    predictions["novelty_knn_distance"] = support["novelty_knn_distance"].to_numpy(float)
    predictions["support_class"] = support["support_class"].astype(str).to_numpy()
    predictions["issue_week"] = issue_week
    predictions["proxy_id"] = "E0_LAST_AVAILABLE"
    predictions["production_run_id"] = "__RUN_ID__"
    prediction_flags = []
    for _, row in predictions.iterrows():
        flags = p5.warning_flags(str(row["support_class"]), bool(pd.notna(row.get("p_boot_sd"))), [])
        prediction_flags.append(flags)
    predictions["warning_flags"] = [";".join(flags) if flags else "OK" for flags in prediction_flags]
    predictions["warning_status"] = [p5.highest_warning(flags) for flags in prediction_flags]
    predictions["model_uncertainty_status"] = np.where(predictions["p_boot_sd"].notna(), "P4_REFERENCE_AVAILABLE", "NOT_COMPUTED_OPERATIONALLY")
    for column in ("full_q025", "full_q975", "p_boot_sd", "expected_boot_sd"):
        if column not in predictions:
            predictions[column] = np.nan
    return predictions


def support_monitoring(predictions: pd.DataFrame) -> dict[str, Any]:
    counts = predictions["support_class"].value_counts().to_dict()
    total = max(len(predictions), 1)
    proportions = {key: float(counts.get(key, 0) / total) for key in P4_SUPPORT_CLASSES}
    p = predictions["p_occurrence"].to_numpy(float)
    expected = predictions["expected_count"].to_numpy(float)
    novelty = predictions["novelty_knn_distance"].to_numpy(float)
    return {
        "row_count": int(len(predictions)),
        "target_week_count": int(predictions["target_week"].nunique()),
        "support_class_counts": {key: int(counts.get(key, 0)) for key in P4_SUPPORT_CLASSES},
        "support_class_proportions": proportions,
        "novelty_summary": {"q50": float(np.quantile(novelty, .50)), "q95": float(np.quantile(novelty, .95)), "q99": float(np.quantile(novelty, .99)), "max": float(np.max(novelty))},
        "occurrence_summary": {"mean": float(np.mean(p)), "q95": float(np.quantile(p, .95)), "max": float(np.max(p)), "high_risk_fraction_p_ge_0_5": float(np.mean(p >= .5)), "near_zero_fraction_p_le_0_001": float(np.mean(p <= .001))},
        "expected_count_summary": {"mean": float(np.mean(expected)), "q95": float(np.quantile(expected, .95)), "max": float(np.max(expected)), "total": float(np.sum(expected))},
        "uncertainty": {"p_boot_sd_available": int(predictions["p_boot_sd"].notna().sum()), "expected_boot_sd_available": int(predictions["expected_boot_sd"].notna().sum())},
    }


def drift_state(monitor: dict[str, Any], reference: dict[str, Any] | None, config: dict[str, Any]) -> dict[str, Any]:
    if not reference:
        return {"state": "NO_MATERIAL_DRIFT", "comparisons": [], "reason": "no prior monitoring reference supplied"}
    threshold = config["drift"]
    comparisons = []
    max_severity = 0
    for category in P4_SUPPORT_CLASSES:
        observed = monitor["support_class_proportions"].get(category, 0.0)
        prior = reference.get("support_class_proportions", {}).get(category)
        if prior is not None:
            delta = abs(float(observed) - float(prior))
            severity = 2 if delta > threshold["support_proportion_review_absolute"] else (1 if delta > threshold["support_proportion_warning_absolute"] else 0)
            max_severity = max(max_severity, severity)
            comparisons.append({"metric": f"support_proportion:{category}", "observed": observed, "reference": prior, "absolute_delta": delta, "severity": severity})
    for label, key in (("occurrence_mean", "occurrence_summary"), ("expected_count_mean", "expected_count_summary")):
        observed = monitor[key]["mean"]
        prior = reference.get(key, {}).get("mean")
        if prior is not None and float(prior) != 0:
            rel = abs(float(observed) - float(prior)) / abs(float(prior))
            severity = 2 if rel > threshold["distribution_relative_review"] else (1 if rel > threshold["distribution_relative_warning"] else 0)
            max_severity = max(max_severity, severity)
            comparisons.append({"metric": label, "observed": observed, "reference": prior, "relative_delta": rel, "severity": severity})
    state = ("DRIFT_REVIEW_REQUIRED" if max_severity >= 2 else "DRIFT_WARNING" if max_severity == 1 else "NO_MATERIAL_DRIFT")
    return {"state": state, "comparisons": comparisons, "action": "REVIEW_REQUIRED" if state != "NO_MATERIAL_DRIFT" else "NONE"}


def input_signature(records: list[dict[str, Any]], e0: dict[str, Any], config_hash: str) -> str:
    return sha256_payload({"records": records, "e0": e0, "config_sha256": config_hash, "model_sha256": MODEL_SHA256})


def add_metadata(predictions: pd.DataFrame, run_id: str, warnings: list[str], mode: str) -> pd.DataFrame:
    predictions = predictions.copy()
    predictions["production_run_id"] = run_id
    for index in predictions.index:
        flags = [item for item in str(predictions.at[index, "warning_flags"]).split(";") if item and item != "OK"]
        if mode == "replay":
            flags.append("HISTORICAL_REPLAY")
        flags.extend(warnings)
        flags = list(dict.fromkeys(flags))
        predictions.at[index, "warning_flags"] = ";".join(flags) if flags else "OK"
        predictions.at[index, "warning_status"] = p5.highest_warning(flags) if flags else "OK"
    for column in OUTPUT_COLUMNS:
        if column not in predictions:
            predictions[column] = np.nan
    return predictions[OUTPUT_COLUMNS]


def validate_output(predictions: pd.DataFrame, issue_week: str, run_id: str) -> None:
    if list(predictions.columns) != OUTPUT_COLUMNS:
        raise P6Error("OUTPUT_SCHEMA_INVALID", "output columns do not match the P6 stable schema")
    if len(predictions) != 3 * 10037:
        raise P6Error("OUTPUT_ROW_COUNT_INVALID", f"expected {3 * 10037} rows, observed {len(predictions)}")
    if predictions[["target_week", "horizon", "model_node_id"]].duplicated().any():
        raise P6Error("DUPLICATE_TARGET_WEEK", "output target keys are duplicated")
    if predictions["issue_week"].ne(issue_week).any() or predictions["production_run_id"].ne(run_id).any():
        raise P6Error("OUTPUT_PROVENANCE_INVALID", "output provenance does not match the run")
    if not set(predictions["support_class"].astype(str)).issubset(set(P4_SUPPORT_CLASSES)):
        raise P6Error("SUPPORT_REFERENCE_INVALID", "output contains an invalid support class", "BLOCKED_PROVENANCE")
    if not np.isfinite(predictions[["p_occurrence", "conditional_count_mean", "expected_count", "novelty_knn_distance"]].to_numpy(float)).all():
        raise P6Error("NONFINITE_OUTPUT", "output contains non-finite required numeric values")


def manifest(args: argparse.Namespace, config: dict[str, Any], config_hash: str, model_path: Path, verification: dict[str, Any], issue_week: str, targets: list[str], e0: dict[str, Any], records: list[dict[str, Any]], warnings: list[str], blockers: list[str], signature: str) -> dict[str, Any]:
    return {
        "run_id": args.run_id,
        "mode": args.mode,
        "issue_timestamp": issue_timestamp(issue_week),
        "issue_week": issue_week,
        "target_weeks": targets,
        "horizons": [1, 2, 3],
        "model_id": MODEL_ID,
        "model_sha256": sha256_file(model_path),
        "code_git_sha": git_sha(),
        "production_config_sha256": config_hash,
        "production_software_version": config.get("production_software_version"),
        "proxy_id": "E0_LAST_AVAILABLE",
        "proxy_contract_version": config["operational_contract"]["contract_version"],
        "support_specification_sha256": config["support_specification"]["sha256"],
        "freeze_verification": verification,
        "e0": e0,
        "input_records": records,
        "input_signature": signature,
        "warning_codes": warnings,
        "blocking_codes": blockers,
        "retry_count": int(args.attempt),
        "terminal_status": "PENDING",
        "validation_status": "PENDING",
        "output_immutability": "completed output is immutable; replay uses a separate root",
    }


def write_status(root: Path, run_id: str, terminal_status: str, **extra: Any) -> None:
    write_json(root / "status.json", {"run_id": run_id, "terminal_status": terminal_status, "updated_at": utc_now(), **extra})


def execute(args: argparse.Namespace) -> dict[str, Any]:
    started = time.time()
    config, config_hash = load_config(args.config)
    args.config_data = config
    verify_referenced_hashes(config)
    existing = prepare_root(args, args.mode, config_hash)
    if args.mode == "verify":
        return verify_run(args.output_root, config, config_hash)
    if not args.run_id or not args.issue_week:
        raise P6Error("MISSING_RUN_ARGUMENT", "run/replay/preflight require --run-id and --issue-week")
    parse_iso_week(args.issue_week)
    verification, model_path, model = verify_frozen_model()
    bundle = bundle_from_args(args)
    targets = validate_issue_and_targets(bundle, args.issue_week)
    e0, e0_meta = e0_features(bundle, args.issue_week)
    records, blockers, readiness_warnings = readiness(args, bundle, args.issue_week, targets, e0_meta, args.mode)
    signature = input_signature(records, e0_meta, config_hash)
    run_manifest = manifest(args, config, config_hash, model_path, verification, args.issue_week, targets, e0_meta, records, readiness_warnings, blockers, signature)
    write_json(args.output_root / "run_manifest.json", run_manifest)
    write_json(args.output_root / "input_readiness.json", {
        "run_id": args.run_id,
        "issue_week": args.issue_week,
        "latest_environment_week": e0_meta["latest_environment_week"],
        "target_weeks": targets,
        "records": records,
        "blocking_codes": blockers,
        "warning_codes": readiness_warnings,
        "readiness_state": "BLOCKED_INPUT_INVALID" if blockers else ("READY_WITH_WARNINGS" if readiness_warnings else "READY"),
    })
    write_stage(args.output_root, "PREFLIGHT_COMPLETE", args.run_id, signature, readiness_state="BLOCKED" if blockers else "READY")
    write_status(args.output_root, args.run_id, "PRODUCTION_RUN_BLOCKED" if blockers and args.mode in {"production", "preflight"} else "PREFLIGHT_COMPLETE", error_code="PRODUCTION_BLOCKED" if blockers and args.mode in {"production", "preflight"} else None, blocking_codes=blockers)
    maybe_interrupt(args, "PREFLIGHT_COMPLETE")
    if args.mode == "preflight":
        run_manifest.update({"terminal_status": "PRODUCTION_RUN_BLOCKED" if blockers else "PREFLIGHT_COMPLETE", "validation_status": "BLOCKED" if blockers else "PASS", "runtime_seconds": time.time() - started})
        write_json(args.output_root / "run_manifest.json", run_manifest)
        return run_manifest
    if blockers and args.mode == "production":
        run_manifest.update({"terminal_status": "PRODUCTION_RUN_BLOCKED", "validation_status": "BLOCKED", "runtime_seconds": time.time() - started, "message": "prospective input contract is not satisfied; no inference was run"})
        write_json(args.output_root / "run_manifest.json", run_manifest)
        write_status(args.output_root, args.run_id, "PRODUCTION_RUN_BLOCKED", error_code="PRODUCTION_BLOCKED", blocking_codes=blockers)
        return run_manifest
    write_stage(args.output_root, "INPUTS_VALIDATED", args.run_id, signature, mode=args.mode)
    maybe_interrupt(args, "INPUTS_VALIDATED")
    write_npy(args.output_root / "predictor_matrix_e0.npy", e0)
    write_stage(args.output_root, "PREDICTOR_MATRIX_COMPLETE", args.run_id, signature, latest_environment_week=e0_meta["latest_environment_week"])
    maybe_interrupt(args, "PREDICTOR_MATRIX_COMPLETE")
    novelty, intervals, uncertainty, p4_info = validate_p4(args)
    predictions = make_predictions(bundle, e0, model, args.issue_week, novelty, intervals, uncertainty)
    predictions = add_metadata(predictions, args.run_id, readiness_warnings, args.mode)
    write_stage(args.output_root, "INFERENCE_COMPLETE", args.run_id, signature, row_count=int(len(predictions)))
    maybe_interrupt(args, "INFERENCE_COMPLETE")
    write_stage(args.output_root, "SUPPORT_COMPLETE", args.run_id, signature, support_class_counts=predictions["support_class"].value_counts().to_dict())
    maybe_interrupt(args, "SUPPORT_COMPLETE")
    validate_output(predictions, args.issue_week, args.run_id)
    write_parquet(args.output_root / "predictions.parquet", predictions)
    write_csv(args.output_root / "output_schema.csv", pd.DataFrame({"field": OUTPUT_COLUMNS}))
    monitor = support_monitoring(predictions)
    reference = load_json(args.reference_monitoring) if args.reference_monitoring else None
    monitor["input"] = {"latest_environment_week": e0_meta["latest_environment_week"], "freshness_counts": pd.Series([item["freshness_state"] for item in records]).value_counts().to_dict(), "source_hashes": {item["source_id"]: item["sha256"] for item in records}}
    monitor["operational"] = {"runtime_seconds_through_inference": time.time() - started, "retry_count": int(args.attempt), "warning_codes": readiness_warnings}
    monitor["drift"] = drift_state(monitor, reference, config)
    write_json(args.output_root / "monitoring_record.json", monitor)
    write_json(args.output_root / "support_summary.json", {"support_class_counts": monitor["support_class_counts"], "support_class_proportions": monitor["support_class_proportions"], "proxy_id": "E0_LAST_AVAILABLE", "thresholds_unchanged": True})
    write_stage(args.output_root, "OUTPUT_VALIDATED", args.run_id, signature, output_sha256=sha256_file(args.output_root / "predictions.parquet"))
    maybe_interrupt(args, "OUTPUT_VALIDATED")
    output_hash = sha256_file(args.output_root / "predictions.parquet")
    run_manifest.update({"p4_support_reference_artifacts": p4_info.get("artifact_paths"), "output_row_count": int(len(predictions)), "output_sha256": output_hash, "output_path": str(args.output_root / "predictions.parquet"), "monitoring_record_sha256": sha256_file(args.output_root / "monitoring_record.json"), "validation_status": "PASS", "terminal_status": "PRODUCTION_RUN_COMPLETE_WITH_WARNINGS" if readiness_warnings or (monitor["drift"]["state"] != "NO_MATERIAL_DRIFT") else "PRODUCTION_RUN_COMPLETE", "runtime_seconds": time.time() - started, "warning_codes": sorted(set(readiness_warnings + (["REVIEW_REQUIRED"] if monitor["drift"]["state"] != "NO_MATERIAL_DRIFT" else [])))})
    write_json(args.output_root / "run_manifest.json", run_manifest)
    write_stage(args.output_root, "MANIFEST_COMPLETE", args.run_id, signature, output_sha256=output_hash)
    maybe_interrupt(args, "MANIFEST_COMPLETE")
    write_stage(args.output_root, "RUN_COMPLETE", args.run_id, signature, terminal_status=run_manifest["terminal_status"])
    write_status(args.output_root, args.run_id, "RUN_COMPLETE", terminal_status_detail=run_manifest["terminal_status"], output_sha256=output_hash, warning_codes=run_manifest["warning_codes"])
    return run_manifest


def verify_run(root: Path, config: dict[str, Any], config_hash: str) -> dict[str, Any]:
    status = load_json(root / "status.json")
    manifest = load_json(root / "run_manifest.json")
    if status.get("terminal_status") != "RUN_COMPLETE":
        raise P6Error("RUN_NOT_COMPLETE", "verify requires a completed run")
    if manifest.get("production_config_sha256") != config_hash:
        raise P6Error("PROVENANCE_HASH_MISMATCH", "run config hash differs from current P6 config", "BLOCKED_PROVENANCE")
    output = root / "predictions.parquet"
    if not output.exists():
        raise P6Error("MISSING_COMPLETED_OUTPUT", "completed run lacks predictions.parquet")
    observed_hash = sha256_file(output)
    if observed_hash != manifest.get("output_sha256") or observed_hash != status.get("output_sha256"):
        raise P6Error("OUTPUT_HASH_MISMATCH", "completed output checksum does not match manifest/status")
    frame = pd.read_parquet(output)
    validate_output(frame, str(manifest["issue_week"]), str(manifest["run_id"]))
    for stage in P6_STAGES:
        if not stage_path(root, stage).exists():
            raise P6Error("MISSING_STAGE_MARKER", f"completed run lacks stage marker {stage}")
    return {"run_id": manifest["run_id"], "terminal_status": "RUN_COMPLETE", "output_sha256": observed_hash, "row_count": int(len(frame)), "verification": "PASS"}


def write_delayed_evaluation_template(root: Path, run_id: str) -> Path:
    path = root / "delayed_outcome_evaluation_template.csv"
    frame = pd.DataFrame(columns=["production_run_id", "issue_week", "target_week", "horizon", "canonical_node_id", "observed_count", "p_occurrence", "expected_count", "brier", "calibration", "auprc", "conditional_count_error", "full_expected_count_error", "frontier_group"])
    write_csv(path, frame)
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("preflight", "production", "verify", "replay"), required=True)
    parser.add_argument("--issue-week")
    parser.add_argument("--run-id")
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=REPOSITORY_ROOT / "config" / "p6_production_config.json")
    parser.add_argument("--model-output", type=Path)
    parser.add_argument("--front-features", type=Path)
    parser.add_argument("--road-night", type=Path)
    parser.add_argument("--soil", type=Path)
    parser.add_argument("--p4-root", type=Path)
    parser.add_argument("--reference-monitoring", type=Path)
    parser.add_argument("--attempt", type=int, default=0)
    parser.add_argument("--stop-after-stage", choices=P6_STAGES)
    parser.add_argument("--write-delayed-template", action="store_true")
    args = parser.parse_args()
    if args.mode != "verify":
        missing = [name for name in ("model_output", "front_features", "road_night", "soil", "p4_root") if getattr(args, name) is None]
        if missing:
            parser.error("missing required input arguments: " + ", ".join(missing))
    return args


def main() -> int:
    args = parse_args()
    try:
        result = execute(args)
        if args.write_delayed_template and args.run_id:
            result["delayed_outcome_template"] = str(write_delayed_evaluation_template(args.output_root, args.run_id))
        print(json.dumps(jsonable(result), indent=2, sort_keys=True))
        return 0
    except P6Interrupted as exc:
        args.output_root.mkdir(parents=True, exist_ok=True)
        write_status(args.output_root, args.run_id or "unknown", exc.state, error_code=exc.code, message=exc.message)
        print(json.dumps({"terminal_status": exc.state, "error_code": exc.code, "message": exc.message}, indent=2), file=sys.stderr)
        return 75
    except P6Error as exc:
        args.output_root.mkdir(parents=True, exist_ok=True)
        payload = {"run_id": args.run_id, "mode": args.mode, "issue_week": args.issue_week, "terminal_status": "PRODUCTION_RUN_FAILED" if exc.state != "PRODUCTION_RUN_BLOCKED" else "PRODUCTION_RUN_BLOCKED", "error_code": exc.code, "message": exc.message, "readiness_state": exc.state, "updated_at": utc_now()}
        completed = False
        status_path = args.output_root / "status.json"
        if status_path.exists():
            try:
                completed = load_json(status_path).get("terminal_status") == "RUN_COMPLETE"
            except Exception:
                completed = False
        if args.mode != "verify" and not completed:
            write_json(args.output_root / "failure.json", payload)
            write_status(args.output_root, args.run_id or "unknown", payload["terminal_status"], error_code=exc.code, message=exc.message, readiness_state=exc.state)
        print(json.dumps(payload, indent=2, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
