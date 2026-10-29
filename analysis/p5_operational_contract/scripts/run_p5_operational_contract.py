#!/usr/bin/env python3
"""Validate and replay the frozen Structured A3 operational contract.

Modes are deliberately explicit:

``dry-run``
    Validate the issue-time contract and write a preflight decision.  It does
    not run inference.
``run``
    Run only when all required inputs are prospectively admissible.  A blocked
    contract writes a blocked manifest and exits non-zero.
``replay``
    Run an explicitly labelled historical reconstruction using the validated
    retrospective feature bundle.  This is not evidence of prospective
    availability and is never presented as a production-complete run.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import platform
import sys
import time
from typing import Any

import numpy as np
import pandas as pd


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
P2_SCRIPT_ROOT = REPOSITORY_ROOT / "analysis" / "p2_operational_nowcast" / "scripts"
sys.path.insert(0, str(P2_SCRIPT_ROOT))
import run_p2_operational_nowcast as p2  # noqa: E402

CONTRACT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(CONTRACT_ROOT))
from p5_contract import (  # noqa: E402
    MODEL_ID,
    MODEL_SHA256,
    P4_SUPPORT_CLASSES,
    P5ContractError,
    fail,
    freshness_status,
    highest_warning,
    issue_timestamp,
    jsonable,
    output_schema,
    parse_iso_week,
    sha256_file,
    target_week,
    validate_manifest_fields,
    validate_predictor_schema,
    validate_required_files,
    validate_spatial_contract,
    validate_target_rows,
    verify_hash,
    warning_flags,
)


P4_REQUIRED = (
    "novelty_metrics.parquet",
    "count_predictive_intervals.parquet",
    "support_classifications.parquet",
    "model_uncertainty_summary.parquet",
    "support_thresholds.csv",
    "support_flag_specification.json",
    "p4_run_metadata.json",
)
P4_COMPACT_ROOT = REPOSITORY_ROOT / "analysis" / "p4_uncertainty_extrapolation" / "results"
HISTORY_FEATURES = [
    "distance_to_any_prior_positive_log1p",
    "distance_to_prev4_positive_log1p",
    "weeks_since_detection_within_50km_log1p",
    "any_prior_positive_available",
    "prev4_positive_available",
    "detection_within_50km_ever_available",
]
EXPECTED_SPATIAL = {
    "node_count": 10037,
    "row_count": "canonical_mask",
    "column_count": "canonical_mask",
    "canonical_mask": "canonical 10,037-node revised domain",
    "cell_order": "model_node_id 0..10036",
    "crs": "EPSG:4326 node coordinates with frozen 25 x 25 km canonical cells",
    "resolution": "25 x 25 km canonical cells",
    "extent": "canonical model_node_id 0 through 10036 in revised-domain order",
}


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


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    atomic_write(path, lambda target: frame.to_csv(target, index=False))


def write_parquet(path: Path, frame: pd.DataFrame) -> None:
    atomic_write(path, lambda target: frame.to_parquet(target, index=False, compression="zstd"))


def git_value(*args: str) -> str:
    import subprocess

    try:
        return subprocess.check_output(
            ["git", "-c", f"safe.directory={REPOSITORY_ROOT.as_posix()}", *args],
            cwd=REPOSITORY_ROOT,
            text=True,
        ).strip()
    except Exception:
        return "unknown"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def verify_frozen_model() -> tuple[dict[str, Any], Path, dict[str, Any]]:
    sys.path.insert(0, str(REPOSITORY_ROOT))
    from scripts.verify_production_model_freeze import check_artifacts, load_json, verify

    manifest_path = REPOSITORY_ROOT / "config" / "production_model_freeze.json"
    verification = verify(manifest_path, REPOSITORY_ROOT)
    if not all(value == "PASS" for value in verification.values() if isinstance(value, str)):
        fail("FROZEN_MODEL_VERIFICATION_FAILED", str(verification))
    manifest = load_json(manifest_path)
    paths = check_artifacts(manifest, REPOSITORY_ROOT)
    model_path = Path(paths["frozen_model_metadata_and_coefficients"])
    verify_hash(model_path, MODEL_SHA256)
    model = json.loads(model_path.read_text(encoding="utf-8"))
    if model.get("model") != MODEL_ID or model.get("feature_count") != 34:
        fail("FROZEN_MODEL_SCHEMA_MISMATCH", "frozen model identity or feature count changed")
    return verification, model_path, model


def load_bundle(args: argparse.Namespace) -> dict[str, Any]:
    p2_args = argparse.Namespace(
        model_output=args.model_output,
        front_features=args.front_features,
        road_night=args.road_night,
        soil=args.soil,
    )
    return p2.load_bundle(p2_args)


def source_record(source_id: str, path: Path, availability_class: str, source_version: str, evidence: str, stale_after_days: int | None = None) -> dict[str, Any]:
    if not path.exists():
        fail("MISSING_REQUIRED_INPUT", f"source file is missing: {path}")
    stat = path.stat()
    source_timestamp = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "source_id": source_id,
        "path": str(path),
        "path_kind": "runtime_resolved_external_input",
        "source_version": source_version,
        "source_timestamp": source_timestamp,
        "sha256": sha256_file(path),
        "size_bytes": stat.st_size,
        "availability_class": availability_class,
        "evidence_source": evidence,
        "stale_after_days": stale_after_days,
    }


def p4_artifact_path(p4_root: Path, name: str) -> Path:
    external = p4_root / name
    if external.exists():
        return external
    compact = P4_COMPACT_ROOT / name
    if compact.exists():
        return compact
    return external


def source_records(args: argparse.Namespace, bundle: dict[str, Any], p4_root: Path) -> list[dict[str, Any]]:
    manifest = bundle["production_manifest"]
    version = str(manifest.get("git_sha", "unknown"))
    paths = bundle["source_paths"]
    records = [
        source_record("dynamic_environmental", Path(paths["dynamic_features"]), "RETROSPECTIVE_ONLY", version, "P2 validated refresh manifest; no release-time/revision-lag metadata", None),
        source_record("livestock_static", Path(paths["static_features"]), "STATIC", version, "P2 validated node-static input contract"),
        source_record("calendar", Path(paths["calendar_features"]), "AVAILABLE_AS_OF_ISSUE", version, "Deterministic ISO-week calendar source"),
        source_record("detection_history", Path(paths["front_features"]), "AVAILABLE_WITH_KNOWN_LAG", version, "P2 causal front artifact with history_cutoff_week"),
        source_record("anthropogenic_static", Path(paths["road_night_features"]), "STATIC", version, "P0/P2 checksummed node-static A3 augmentation"),
        source_record("soil_static", Path(paths["soil_features"]), "STATIC", version, "P0/P2 checksummed node-static A3 augmentation"),
        source_record("weeks", Path(paths["weeks"]), "AVAILABLE_AS_OF_ISSUE", version, "Canonical ISO-week table"),
        source_record("nodes", Path(paths["nodes"]), "STATIC", version, "Canonical revised-domain node table"),
        source_record("production_manifest", Path(paths["production_manifest"]), "STATIC", version, "Validated refresh provenance manifest"),
    ]
    observation_path = manifest.get("observation_source", {}).get("path")
    if observation_path and Path(observation_path).exists():
        records.append(source_record("observations", Path(observation_path), "AVAILABLE_WITH_KNOWN_LAG", version, "Validated observation source manifest"))
    for name in P4_REQUIRED:
        records.append(source_record(f"p4_{name.removesuffix('.parquet').removesuffix('.csv').removesuffix('.json')}", p4_artifact_path(p4_root, name), "STATIC", "P4_RUN", "P4 frozen support-reference artifact"))
    return records


def predictor_groups() -> dict[str, tuple[list[str], str, str, str, str]]:
    return {
        "environmental": (p2.BASE_FEATURES[:12], "dynamic_environmental", "RETROSPECTIVE_ONLY", "weekly", "no authorized substitution"),
        "livestock": (p2.BASE_FEATURES[12:17], "livestock_static", "STATIC", "static", "none"),
        "livestock_imputation": (p2.BASE_FEATURES[17:22], "livestock_static", "STATIC", "static", "none"),
        "calendar": (p2.CALENDAR_FEATURES, "calendar", "AVAILABLE_AS_OF_ISSUE", "weekly", "deterministic from target week"),
        "detection_history": (HISTORY_FEATURES, "detection_history", "AVAILABLE_WITH_KNOWN_LAG", "weekly", "history_cutoff_week must be <= issue week"),
        "anthropogenic": (p2.ADDED_FEATURES[:2], "anthropogenic_static", "STATIC", "static", "none"),
        "soil": (p2.ADDED_FEATURES[2:], "soil_static", "STATIC", "static", "none"),
    }


def input_state_records(records: list[dict[str, Any]], issue_week_value: str) -> list[dict[str, Any]]:
    issue = issue_timestamp(issue_week_value).isoformat().replace("+00:00", "Z")
    output = []
    for record in records:
        row = dict(record)
        row["freshness_status"] = freshness_status(row["source_timestamp"], issue, row["availability_class"], row.get("stale_after_days"))
        output.append(row)
    return output


def availability_audit(issue_week_value: str, bundle: dict[str, Any], records: list[dict[str, Any]]) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    labels = bundle["labels"]
    index_by_week = {label: index for index, label in enumerate(labels)}
    issue_index = index_by_week.get(issue_week_value)
    if issue_index is None:
        fail("INVALID_ISSUE_WEEK", f"issue week is not present in the validated response bundle: {issue_week_value}")
    front = bundle["front"]
    group_map = predictor_groups()
    rows: list[dict[str, Any]] = []
    blockers: list[str] = []
    matrix_rows: list[dict[str, Any]] = []
    for group, (predictors, source_id, availability_class, resolution, substitution) in group_map.items():
        source = next(item for item in records if item["source_id"] == source_id)
        for predictor in predictors:
            values = {"predictor": predictor, "group": group, "availability_class": availability_class, "source_product": source_id, "temporal_resolution": resolution, "publication_cadence": "weekly" if resolution == "weekly" else "static", "typical_lag": "unknown" if availability_class == "RETROSPECTIVE_ONLY" else ("strictly prior week" if group == "detection_history" else "none"), "worst_declared_lag": "unknown" if availability_class == "RETROSPECTIVE_ONLY" else ("target-week history cutoff" if group == "detection_history" else "none"), "revision_behavior": "not documented" if availability_class == "RETROSPECTIVE_ONLY" else ("history changes with newly received observations" if group == "detection_history" else "fixed/static"), "required_lag_or_substitution": substitution, "evidence_source": source["evidence_source"]}
            statuses: list[str] = []
            for horizon in (1, 2, 3):
                target = target_week(issue_week_value, horizon)
                target_index = index_by_week.get(target)
                status = "AVAILABLE"
                if target_index is None:
                    status = "MISSING_TARGET_WEEK"
                elif availability_class == "RETROSPECTIVE_ONLY":
                    status = "BLOCKED_RETROSPECTIVE_ONLY"
                elif group == "detection_history":
                    cutoffs = front.loc[front["week_index"].astype(int) == int(target_index), "history_cutoff_week"].dropna().astype(str)
                    if not len(cutoffs) or any(parse_iso_week(cutoff) > parse_iso_week(issue_week_value) for cutoff in cutoffs):
                        status = "BLOCKED_FUTURE_HISTORY_CUTOFF"
                statuses.append(status)
                matrix_rows.append({"predictor": predictor, "horizon": horizon, "status": status, "issue_week": issue_week_value, "target_week": target})
            values.update({"h1": statuses[0], "h2": statuses[1], "h3": statuses[2], "operational_blocker": ";".join(status for status in statuses if status.startswith("BLOCKED")) or "none"})
            if values["operational_blocker"] != "none":
                blockers.append(f"{predictor}:{values['operational_blocker']}")
            rows.append(values)
    return pd.DataFrame(rows), pd.DataFrame(matrix_rows), sorted(set(blockers))


def validate_bundle_contract(bundle: dict[str, Any]) -> None:
    nodes = bundle["nodes"]
    if len(nodes) != 10037 or not np.array_equal(nodes["model_node_id"].to_numpy(np.int64), np.arange(10037)):
        fail("SPATIAL_CONTRACT_FAILED", "canonical model node order is not 0..10036")
    if nodes[["row", "column", "lon", "lat"]].isna().any().any() or not np.isfinite(nodes[["lon", "lat"]].to_numpy(float)).all():
        fail("SPATIAL_CONTRACT_FAILED", "canonical node coordinates or raster indices are missing/non-finite")
    if nodes[["row", "column"]].duplicated().any():
        fail("SPATIAL_CONTRACT_FAILED", "canonical raster row/column cells are duplicated")
    actual = dict(EXPECTED_SPATIAL)
    actual["node_count"] = len(nodes)
    actual["row_count"] = "canonical_mask"
    actual["column_count"] = "canonical_mask"
    validate_spatial_contract(actual, EXPECTED_SPATIAL)
    validate_predictor_schema(p2.FEATURE_ORDER, p2.FEATURE_ORDER)


def load_p4_references(p4_root: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    artifact_paths = {name: p4_artifact_path(p4_root, name) for name in P4_REQUIRED}
    validate_required_files(artifact_paths.values(), code="MISSING_SUPPORT_REFERENCE")
    spec = json.loads(artifact_paths["support_flag_specification.json"].read_text(encoding="utf-8"))
    if spec.get("categories") != list(P4_SUPPORT_CLASSES) or not spec.get("outcome_free"):
        fail("SUPPORT_REFERENCE_INVALID", "P4 support specification does not match the frozen support contract")
    metadata = json.loads(artifact_paths["p4_run_metadata.json"].read_text(encoding="utf-8"))
    if metadata.get("p0_model_artifact_sha256") != MODEL_SHA256:
        fail("SUPPORT_REFERENCE_INVALID", "P4 support reference does not identify the frozen model hash")
    key = ["origin_week", "target_week", "horizon", "model_node_id"]
    novelty = pd.read_parquet(artifact_paths["novelty_metrics.parquet"], columns=key + ["novelty_knn_distance", "support_class"])
    intervals = pd.read_parquet(artifact_paths["count_predictive_intervals.parquet"], columns=key + ["full_q025", "full_q975", "full_q100", "full_q900", "full_q250", "full_q750", "conditional_q025", "conditional_q975"])
    uncertainty_path = artifact_paths["model_uncertainty_summary.parquet"]
    uncertainty = pd.read_parquet(uncertainty_path) if uncertainty_path.exists() else pd.DataFrame()
    return novelty, intervals, uncertainty, {"spec": spec, "metadata": metadata, "support_reference_hash": sha256_file(artifact_paths["support_flag_specification.json"]), "artifact_paths": {name: str(path) for name, path in artifact_paths.items()}}


def model_predictions(bundle: dict[str, Any], model: dict[str, Any], issue_week_value: str, horizons: list[int]) -> pd.DataFrame:
    labels = bundle["labels"]
    index_by_week = {label: index for index, label in enumerate(labels)}
    mean = np.asarray(model["preprocessing"]["training_mean"], dtype=np.float64)
    scale = np.asarray(model["preprocessing"]["training_sd"], dtype=np.float64)
    state = {"occurrence_beta": np.asarray(model["occurrence_coefficients"], dtype=np.float64), "count_beta": np.asarray(model["count_coefficients"], dtype=np.float64)}
    frames = []
    node_columns = ["model_node_id", "row", "column", "lon", "lat", "country_or_domain_region"]
    for horizon in horizons:
        target = target_week(issue_week_value, horizon)
        if target not in index_by_week:
            fail("MISSING_TARGET_WEEK", f"target week is absent from validated inputs: {target}")
        target_index = index_by_week[target]
        raw = np.asarray(bundle["features"][target_index], dtype=np.float64)
        x = (raw - mean[None, :]) / scale[None, :]
        if not np.isfinite(x).all():
            fail("NONFINITE_PREDICTOR_MATRIX", f"non-finite standardized predictor matrix for {target}")
        probability, conditional, mu = p2.predict(state, x)
        frame = bundle["nodes"][node_columns].copy()
        frame.insert(0, "target_week", target)
        frame.insert(1, "horizon", horizon)
        frame["canonical_node_id"] = frame["model_node_id"].astype(np.int64)
        frame["p_occurrence"] = probability
        frame["conditional_count_mean"] = conditional
        frame["expected_count"] = probability * conditional
        frame["underlying_mu"] = mu
        frame["observed_count"] = np.asarray(bundle["counts"][target_index], dtype=np.int64)
        frames.append(frame)
    output = pd.concat(frames, ignore_index=True)
    if output.duplicated(["target_week", "horizon", "model_node_id"]).any():
        fail("DUPLICATE_TARGET_WEEK", "production output keys are duplicated")
    return output


def add_p4_outputs(predictions: pd.DataFrame, issue_week_value: str, novelty: pd.DataFrame, intervals: pd.DataFrame, uncertainty: pd.DataFrame) -> pd.DataFrame:
    key = ["origin_week", "target_week", "horizon", "model_node_id"]
    lookup_key = ["target_week", "horizon", "model_node_id"]
    n = novelty.loc[novelty["origin_week"].astype(str).eq(issue_week_value)].copy()
    i = intervals.loc[intervals["origin_week"].astype(str).eq(issue_week_value)].copy()
    if len(n) != len(predictions) or len(i) != len(predictions):
        fail("SUPPORT_REFERENCE_COVERAGE_FAILED", f"P4 reference does not cover issue {issue_week_value} target rows")
    n = n.rename(columns={"origin_week": "reference_origin_week"})
    i = i.rename(columns={"origin_week": "interval_reference_origin_week"})
    merged = predictions.merge(n.drop(columns=["reference_origin_week"]), on=lookup_key, how="left", validate="one_to_one")
    merged = merged.merge(i.drop(columns=["interval_reference_origin_week"]), on=lookup_key, how="left", validate="one_to_one", suffixes=("", "_interval"))
    if merged["support_class"].isna().any() or not set(merged["support_class"]).issubset(set(P4_SUPPORT_CLASSES)):
        fail("SUPPORT_REFERENCE_COVERAGE_FAILED", "P4 support class is missing or invalid")
    uncertainty_available = False
    if len(uncertainty):
        u = uncertainty.copy()
        if all(column in u.columns for column in lookup_key):
            wanted = [column for column in [*lookup_key, "p_boot_sd", "expected_boot_sd", "p_boot_q025", "p_boot_q975", "expected_boot_q025", "expected_boot_q975"] if column in u.columns]
            u = u[wanted].drop_duplicates(lookup_key)
            merged = merged.merge(u, on=lookup_key, how="left", validate="one_to_one")
            uncertainty_available = bool(merged["p_boot_sd"].notna().any()) if "p_boot_sd" in merged.columns else False
    for column in ("p_boot_sd", "expected_boot_sd", "p_boot_q025", "p_boot_q975", "expected_boot_q025", "expected_boot_q975"):
        if column not in merged.columns:
            merged[column] = math.nan
    return merged


def operational_manifest(
    args: argparse.Namespace,
    mode: str,
    issue_week_value: str,
    target_weeks: list[str],
    records: list[dict[str, Any]],
    availability: pd.DataFrame,
    blockers: list[str],
    verification: dict[str, Any],
    model_path: Path,
    p4_info: dict[str, Any],
) -> dict[str, Any]:
    states = sorted(set(input_state_records(records, issue_week_value)[index]["freshness_status"] for index in range(len(records))))
    return {
        "run_id": args.run_id,
        "mode": mode,
        "historical_replay": mode == "replay",
        "issue_timestamp": issue_timestamp(issue_week_value),
        "issue_week": issue_week_value,
        "target_weeks": target_weeks,
        "horizons": [int(value) for value in args.horizons],
        "model_id": MODEL_ID,
        "model_sha256": sha256_file(model_path),
        "code_git_sha": git_value("rev-parse", "HEAD"),
        "freeze_manifest_version": json.loads((REPOSITORY_ROOT / "config" / "production_model_freeze.json").read_text(encoding="utf-8")).get("manifest_version"),
        "p4_support_reference_sha256": p4_info.get("support_reference_hash"),
        "p4_support_classes": list(P4_SUPPORT_CLASSES),
        "input_records": records,
        "input_freshness_states": states,
        "input_validation_status": "BLOCKED" if blockers else "PASS",
        "contract_blockers": blockers,
        "support_reference_metadata": p4_info.get("metadata", {}),
        "freeze_verification": verification,
        "response_history_cutoff": "observations through completed issue week T only",
        "frontier_history_cutoff": "front features must have history_cutoff_week <= issue week T",
        "output_immutability": "one run_id/output root; existing completed run is never overwritten",
        "validation_status": "PENDING",
        "terminal_status": "PENDING",
    }


def finalize_output(output: Path, manifest: dict[str, Any], predictions: pd.DataFrame | None, mode: str) -> None:
    if output.exists() and any(output.iterdir()):
        fail("OUTPUT_ROOT_NOT_IMMUTABLE", f"refusing to write into non-empty output root: {output}")
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "run_manifest.json", manifest)
    if predictions is not None:
        output_path = output / "predictions.parquet"
        write_parquet(output_path, predictions)
        manifest["output_row_count"] = int(len(predictions))
        manifest["output_schema"] = list(predictions.columns)
        manifest["output_sha256"] = sha256_file(output_path)
        manifest["output_path"] = str(output_path)
        write_csv(output / "output_schema.csv", pd.DataFrame(output_schema()))
    write_json(output / "run_manifest.json", manifest)
    write_json(output / "status.json", {"run_id": manifest["run_id"], "terminal_status": manifest["terminal_status"], "mode": mode, "error_code": manifest.get("error_code"), "message": manifest.get("message")})


def execute(args: argparse.Namespace) -> dict[str, Any]:
    started = time.time()
    parse_iso_week(args.issue_week)
    horizons = sorted(set(int(value) for value in args.horizons))
    if horizons != [1, 2, 3]:
        fail("INVALID_HORIZON", "P5 requires horizons exactly 1,2,3")
    target_weeks = [target_week(args.issue_week, horizon) for horizon in horizons]
    verification, model_path, model = verify_frozen_model()
    validate_predictor_schema(model["feature_order"], p2.FEATURE_ORDER)
    bundle = load_bundle(args)
    validate_bundle_contract(bundle)
    records = source_records(args, bundle, args.p4_root)
    records = input_state_records(records, args.issue_week)
    availability, matrix, blockers = availability_audit(args.issue_week, bundle, records)
    target_rows = [{"target_week": target, "horizon": horizon} for target, horizon in zip(target_weeks, horizons)]
    validate_target_rows(args.issue_week, target_rows)
    novelty, intervals, uncertainty, p4_info = load_p4_references(args.p4_root)
    output = args.output_root
    if output.exists() and any(output.iterdir()):
        fail("OUTPUT_ROOT_NOT_IMMUTABLE", f"refusing to write into non-empty output root: {output}")
    output.mkdir(parents=True, exist_ok=True)
    write_csv(output / "predictor_availability_audit.csv", availability)
    write_csv(output / "horizon_availability_matrix.csv", matrix)
    write_csv(output / "production_input_manifest.csv", pd.DataFrame(records))
    write_json(output / "production_input_manifest.json", {"issue_week": args.issue_week, "issue_timestamp": issue_timestamp(args.issue_week), "records": records})
    write_json(output / "input_contract.json", {
        "issue_week_rule": "completed ISO week T; issue timestamp is Monday 00:00 UTC immediately after T",
        "target_horizons": [1, 2, 3],
        "target_week_rule": "T+h ISO week",
        "response_history_cutoff": "through issue week T only",
        "frontier_history_cutoff": "history_cutoff_week <= T",
        "future_input_rule": "source_timestamp > issue_timestamp is FUTURE_DATED and blocks production",
        "retrospective_input_rule": "RETROSPECTIVE_ONLY blocks production; only explicit historical replay may continue",
        "no_silent_fallback": True,
        "spatial_contract": EXPECTED_SPATIAL,
        "feature_order": list(model["feature_order"]),
    })
    write_json(output / "freshness_rules.json", {
        "states": ["CURRENT", "STALE_ALLOWED", "STALE_BLOCKING", "MISSING", "FUTURE_DATED", "UNKNOWN_VINTAGE"],
        "rules": [
            "missing source -> MISSING and block",
            "source timestamp after issue timestamp -> FUTURE_DATED and block",
            "RETROSPECTIVE_ONLY -> STALE_BLOCKING and block",
            "undocumented vintage -> UNKNOWN_VINTAGE and block",
            "known bounded lag may be STALE_ALLOWED only when declared in the input manifest",
        ],
    })
    write_json(output / "output_schema.json", {"fields": output_schema(), "support_classes": list(P4_SUPPORT_CLASSES)})
    write_json(output / "warning_error_codes.json", {
        "warnings": ["OK", "CAUTION_SUPPORT", "EXTRAPOLATIVE_SUPPORT", "STALE_INPUT", "UNKNOWN_VINTAGE", "PARTIAL_UNCERTAINTY"],
        "blocking_errors": ["INPUT_VALIDATION_FAILED", "PRODUCTION_BLOCKED", "FUTURE_DATED_INPUT", "MISSING_REQUIRED_INPUT", "MODEL_HASH_MISMATCH", "PREDICTOR_SCHEMA_MISMATCH", "SPATIAL_CONTRACT_FAILED", "DUPLICATE_TARGET_WEEK", "MISSING_PROVENANCE_METADATA"],
    })
    manifest = operational_manifest(args, args.mode, args.issue_week, target_weeks, records, availability, blockers, verification, model_path, p4_info)
    production_blockers = list(blockers)
    if any(record["freshness_status"] in {"MISSING", "FUTURE_DATED", "STALE_BLOCKING", "UNKNOWN_VINTAGE"} for record in records):
        production_blockers.append("input_freshness_contract")
    if args.mode in {"dry-run", "run"} and production_blockers:
        manifest.update({"validation_status": "BLOCKED", "terminal_status": "PRODUCTION_RUN_BLOCKED", "contract_blockers": sorted(set(production_blockers)), "runtime_seconds": time.time() - started, "message": "prospective issue-time contract is not satisfied; no inference was run"})
        write_json(output / "run_manifest.json", manifest)
        write_json(output / "status.json", {"run_id": args.run_id, "terminal_status": manifest["terminal_status"], "error_code": "PRODUCTION_BLOCKED", "message": manifest["message"]})
        return manifest
    predictions = model_predictions(bundle, model, args.issue_week, horizons)
    predictions = add_p4_outputs(predictions, args.issue_week, novelty, intervals, uncertainty)
    input_states = [record["freshness_status"] for record in records]
    prediction_flags = []
    for _, row in predictions.iterrows():
        flags = warning_flags(str(row["support_class"]), bool(pd.notna(row.get("p_boot_sd"))), input_states)
        if args.mode == "replay":
            flags.append("HISTORICAL_REPLAY")
        prediction_flags.append(flags)
    predictions["warning_flags"] = [";".join(flags) for flags in prediction_flags]
    predictions["warning_status"] = [highest_warning(flags) for flags in prediction_flags]
    predictions["model_uncertainty_status"] = np.where(predictions["p_boot_sd"].notna(), "REFERENCE_AVAILABLE", "NOT_COMPUTED_OPERATIONALLY")
    if args.mode == "replay":
        terminal = "PRODUCTION_RUN_COMPLETE_WITH_WARNINGS"
        validation_status = "HISTORICAL_REPLAY_COMPLETE_RETROSPECTIVE_INPUTS"
    else:
        terminal = "PRODUCTION_RUN_COMPLETE" if not any(predictions["warning_status"] != "OK") else "PRODUCTION_RUN_COMPLETE_WITH_WARNINGS"
        validation_status = "PASS"
    manifest.update({"validation_status": validation_status, "terminal_status": terminal, "runtime_seconds": time.time() - started, "warning_flags": sorted(set(flag for flags in prediction_flags for flag in flags)), "output_immutability": True})
    finalize_output(output, manifest, predictions, args.mode)
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("dry-run", "run", "replay"), required=True)
    parser.add_argument("--issue-week", required=True)
    parser.add_argument("--horizons", default="1,2,3")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--model-output", type=Path, required=True)
    parser.add_argument("--front-features", type=Path, required=True)
    parser.add_argument("--road-night", type=Path, required=True)
    parser.add_argument("--soil", type=Path, required=True)
    parser.add_argument("--p4-root", type=Path, required=True)
    args = parser.parse_args()
    args.horizons = [int(value) for value in str(args.horizons).split(",") if str(value).strip()]
    return args


def main() -> int:
    args = parse_args()
    try:
        result = execute(args)
        print(json.dumps(jsonable(result), indent=2, sort_keys=True))
        return 0
    except P5ContractError as exc:
        output = args.output_root
        output.mkdir(parents=True, exist_ok=True)
        payload = {"run_id": args.run_id, "mode": args.mode, "issue_week": args.issue_week, "validation_status": "FAILED", "terminal_status": "PRODUCTION_RUN_FAILED", "error_code": exc.code, "message": exc.message, "runtime_seconds": 0.0}
        write_json(output / "run_manifest.json", payload)
        write_json(output / "status.json", payload)
        print(json.dumps(payload, indent=2, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
