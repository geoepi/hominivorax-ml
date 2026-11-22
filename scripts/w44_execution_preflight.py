#!/usr/bin/env python3
"""Read-only preflight checks for the W44 Task 2A, Task 2E, and full-fit jobs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Mapping


class PreflightError(ValueError):
    """Raised when a refresh job cannot be shown to be safe to start."""


A3_FEATURE_MANIFEST = (
    Path(__file__).resolve().parents[1]
    / "analysis" / "structured_a3_final_comparison" / "results" / "a3_feature_manifest.json"
)


SUPPORTED_ENV = {
    "task2a": {
        "STGNN_OUTPUT_ROOT", "STGNN_REFRESH_ROOT", "STGNN_ENVIRONMENTAL_ROOT",
        "STGNN_TEMPLATE_PATH", "STGNN_PYTHON_ENV", "STGNN_ANALYSIS_START",
        "STGNN_ANALYSIS_END", "STGNN_SKIP_DATASET_BUILD", "STGNN_R_LIBS_USER",
        "STGNN_REPOSITORY_ROOT", "STGNN_JOB_IDS",
    },
    "task2e": {
        "STGNN_REPOSITORY_ROOT", "STGNN_REFRESH_ROOT", "STGNN_SOURCE_OUTPUT_ROOT",
        "STGNN_PREVIOUS_OUTPUT_ROOT", "STGNN_OBSERVATION_PATH", "STGNN_BOUNDARY_PATH",
        "STGNN_BOUNDARY_LAYER", "STGNN_ANALYSIS_START", "STGNN_ANALYSIS_END",
        "STGNN_RESPONSE_START", "STGNN_RESPONSE_END", "STGNN_TASK2D_COMMIT",
        "STGNN_EXPECTED_OBSERVATION_SHA256", "STGNN_EXPECTED_FEATURE_MANIFEST_SHA256",
        "STGNN_R_LIBS_USER",
    },
    "fullfit": {
        "STGNN_FULLFIT_OUTPUT_ROOT", "STGNN_MODEL_OUTPUT_ROOT", "STGNN_FRONT_FEATURES",
        "STGNN_FRONT_FEATURE_ROOT", "STGNN_ANTHROPOGENIC_FEATURES", "STGNN_SOIL_FEATURES",
        "STGNN_BUILD_A3_FRONT_FEATURES", "STGNN_RESPONSE_START", "STGNN_RESPONSE_END",
        "STGNN_EXPECTED_OBSERVATION_SHA256", "STGNN_R_LIBS_USER", "STGNN_REPOSITORY_ROOT",
        "STGNN_RESUME_AFTER_FIT", "STGNN_FULLFIT_MASK",
    },
}


def check_environment_names(mode: str, environ: Mapping[str, str] | None = None) -> None:
    """Reject unknown names in the project STGNN configuration namespace only."""
    values = os.environ if environ is None else environ
    unsupported = sorted(
        name for name in values
        if name.startswith("STGNN_") and name not in SUPPORTED_ENV[mode]
    )
    if unsupported:
        raise PreflightError(
            f"unsupported {mode} configuration variable(s): {', '.join(unsupported)}"
        )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _absolute_path(value: str | Path | None, label: str) -> Path:
    if value is None or not str(value).strip():
        raise PreflightError(f"{label} is required and must not be empty")
    path = Path(value)
    if not path.is_absolute():
        raise PreflightError(f"{label} must be an absolute path: {value}")
    return path


def resolve_task2a_output_root(output_root_value: str | None, refresh_root_value: str | None) -> Path:
    """Resolve the documented Task 2A output aliases without a fallback path."""
    output_root = (output_root_value or "").strip()
    refresh_root = (refresh_root_value or "").strip()
    if output_root and refresh_root and Path(output_root) != Path(refresh_root):
        raise PreflightError("STGNN_OUTPUT_ROOT and STGNN_REFRESH_ROOT disagree")
    selected = output_root or refresh_root
    return _absolute_path(selected, "STGNN_OUTPUT_ROOT or STGNN_REFRESH_ROOT")


def _existing_file(value: str | Path | None, label: str) -> Path:
    path = _absolute_path(value, label)
    if not path.is_file():
        raise PreflightError(f"{label} is not an existing file: {path}")
    return path.resolve(strict=True)


def _existing_directory(value: str | Path | None, label: str) -> Path:
    path = _absolute_path(value, label)
    if not path.is_dir():
        raise PreflightError(f"{label} is not an existing directory: {path}")
    return path.resolve(strict=True)


def ensure_output_directory_available(value: str | Path | None, label: str) -> Path:
    """Allow an absent or empty destination; never create, clear, or reuse data."""
    path = _absolute_path(value, label)
    if path.is_symlink():
        raise PreflightError(f"{label} must not be a symbolic link: {path}")
    parent = path.parent
    if not parent.is_dir():
        raise PreflightError(f"{label} parent directory must already exist: {parent}")
    if path.exists():
        if not path.is_dir():
            raise PreflightError(f"{label} exists but is not a directory: {path}")
        if any(path.iterdir()):
            raise PreflightError(f"refusing to write into populated {label}: {path}")
    return path.resolve(strict=False)


def _json_file(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PreflightError(f"{label} is not readable JSON: {path}: {error}") from error
    if not isinstance(value, dict):
        raise PreflightError(f"{label} must contain a JSON object: {path}")
    return value


def _iso_week(value: str, label: str) -> date:
    match = re.fullmatch(r"(\d{4})-W(\d{2})", value or "")
    if not match:
        raise PreflightError(f"{label} must use YYYY-Www format")
    try:
        return date.fromisocalendar(int(match.group(1)), int(match.group(2)), 1)
    except ValueError as error:
        raise PreflightError(f"{label} is not a valid ISO week: {value}") from error


def _week_label_from_date(value: str, label: str) -> str:
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError) as error:
        raise PreflightError(f"{label} must be an ISO date in a feature manifest") from error
    iso = parsed.isocalendar()
    return f"{iso.year:04d}-W{iso.week:02d}"


def _empty_or_missing_subdirs(root: Path, names: tuple[str, ...], label: str) -> None:
    for name in names:
        path = root / name
        if path.exists() and (not path.is_dir() or any(path.iterdir())):
            raise PreflightError(f"refusing to continue over existing {label} output: {path}")


def validate_task2a_pipeline(output_root_value: str | Path, task1_manifest_value: str | Path) -> dict[str, Any]:
    """Validate the documented continuation from completed Task 2A raw artifacts."""
    raw_output_root = _absolute_path(output_root_value, "Task 2A output root")
    if raw_output_root.is_symlink():
        raise PreflightError("Task 2A output root must not be a symbolic link")
    output_root = _existing_directory(raw_output_root, "Task 2A output root")
    task1_manifest = _existing_file(task1_manifest_value, "Task 1 preflight manifest")
    model_root = output_root / "model_data"
    raw = model_root / "raw"
    if model_root.is_symlink() or not model_root.is_dir():
        raise PreflightError("Task 2A raw-stage continuation requires an existing model_data directory")
    missing = [name for name in TASK2A_RAW_FILES if not (raw / name).is_file()]
    if missing:
        raise PreflightError(f"Task 2A continuation is missing raw-stage artifacts: {', '.join(missing)}")
    if (model_root / "manifests" / "task2a_manifest.json").exists():
        raise PreflightError("Task 2A continuation refuses an already completed task2a_manifest.json")
    _empty_or_missing_subdirs(model_root, ("splits", "scaling", "diagnostics", "baselines", "manifests"), "Task 2A pipeline")
    return {
        "stage": "task2a_pipeline_resume",
        "output_root": str(output_root),
        "raw_output": str(raw.resolve()),
        "task1_manifest_path": str(task1_manifest),
        "task1_manifest_sha256": sha256_file(task1_manifest),
        "continuation_from_raw_stage": True,
    }


TASK2A_RAW_FILES = (
    "dynamic_features.npy", "dynamic_history_features.npy", "static_features.npy",
    "targets_count.npy", "targets_presence.npy", "weeks.parquet", "nodes.parquet",
    "edges_queen.parquet", "calendar_features.parquet", "feature_manifest.json",
)


def validate_task2a(
    output_root_value: str | Path | None,
    environmental_root_value: str | Path | None,
    template_value: str | Path | None,
    task1_manifest_value: str | Path | None,
    skip_dataset_build: bool = False,
    analysis_start: str = "2024-01-01",
    analysis_end: str | None = None,
) -> dict[str, Any]:
    raw_output_root = _absolute_path(output_root_value, "Task 2A output root")
    if raw_output_root.is_symlink():
        raise PreflightError("Task 2A output root must not be a symbolic link")
    output_root = _existing_directory(raw_output_root, "Task 2A output root")
    environmental_root = _existing_directory(environmental_root_value, "environmental bundle root")
    template = _existing_file(template_value, "canonical template")
    task1_manifest = _existing_file(task1_manifest_value, "Task 1 preflight manifest")
    model_root = output_root / "model_data"
    if model_root.is_symlink():
        raise PreflightError(f"Task 2A model_data destination must not be a symbolic link: {model_root}")
    if model_root.exists() and not model_root.is_dir():
        raise PreflightError(f"Task 2A model_data destination is not a directory: {model_root}")
    if model_root.exists() and not skip_dataset_build and any(model_root.iterdir()):
        raise PreflightError(f"refusing to overwrite populated Task 2A output: {model_root}")

    if skip_dataset_build:
        validate_task2a_pipeline(output_root, task1_manifest)
    try:
        start_date = date.fromisoformat(analysis_start)
        end_date = date.fromisoformat(analysis_end) if analysis_end else None
    except (TypeError, ValueError) as error:
        raise PreflightError("Task 2A analysis dates must be ISO dates") from error
    if end_date and start_date > end_date:
        raise PreflightError("Task 2A analysis end precedes analysis start")

    return {
        "stage": "task2a",
        "output_root": str(output_root),
        "output_destination": str(model_root),
        "continuation_from_raw_stage": bool(skip_dataset_build),
        "environmental_root": str(environmental_root),
        "template_path": str(template),
        "template_sha256": sha256_file(template),
        "task1_manifest_path": str(task1_manifest),
        "task1_manifest_sha256": sha256_file(task1_manifest),
        "analysis_start": start_date.isoformat(),
        "analysis_end": end_date.isoformat() if end_date else "latest-common-supported-week",
    }


TASK2E_REQUIRED_RELATIVE_FILES = (
    "model_data/raw/nodes.parquet", "model_data/raw/edges_queen.parquet",
    "model_data/raw/weeks.parquet", "model_data/raw/calendar_features.parquet",
    "model_data/raw/dynamic_features.npy", "model_data/raw/dynamic_history_features.npy",
    "model_data/raw/static_features.npy", "model_data/raw/feature_manifest.json",
    "model_data/splits/spatial_node_assignments.parquet", "preflight/canonical_environment_mask.tif",
)


def validate_task2e(
    refresh_root_value: str | Path | None,
    source_root_value: str | Path | None,
    previous_root_value: str | Path | None,
    observation_value: str | Path | None,
    boundary_value: str | Path | None,
    boundary_layer: str,
    analysis_start: str = "2024-01-01",
    analysis_end: str | None = None,
    response_start: str = "2025-W01",
    response_end: str | None = None,
    task2d_commit: str = "e18777f1d98c539c92acc9ba1e7e4deb84b54319",
    expected_observation_sha256: str | None = None,
    expected_feature_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    raw_refresh_root = _absolute_path(refresh_root_value, "Task 2E refresh root")
    if raw_refresh_root.is_symlink():
        raise PreflightError("Task 2E refresh root must not be a symbolic link")
    refresh_root = _existing_directory(raw_refresh_root, "Task 2E refresh root")
    source_root = _existing_directory(source_root_value, "Task 2A environmental bundle root")
    previous_root = _existing_directory(previous_root_value, "previous Task 2D root")
    observation = _existing_file(observation_value, "observation source")
    boundary = _existing_file(boundary_value, "boundary source")
    if not boundary_layer or not boundary_layer.strip():
        raise PreflightError("boundary layer is required and must not be empty")
    for expected, label in (
        (expected_observation_sha256, "STGNN_EXPECTED_OBSERVATION_SHA256"),
        (expected_feature_manifest_sha256, "STGNN_EXPECTED_FEATURE_MANIFEST_SHA256"),
    ):
        if expected is None or not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
            raise PreflightError(f"{label} is required and must be a 64-character SHA-256")
    try:
        analysis_start_date = date.fromisoformat(analysis_start)
    except ValueError as error:
        raise PreflightError("analysis start must be an ISO date") from error
    if analysis_end:
        try:
            analysis_end_date = date.fromisoformat(analysis_end)
        except ValueError as error:
            raise PreflightError("analysis end must be an ISO date") from error
    else:
        analysis_end_date = None

    output = ensure_output_directory_available(refresh_root / "revised_model_data", "Task 2E output directory")
    if output == previous_root or output == source_root / "model_data":
        raise PreflightError("Task 2E output directory collides with a selected input vintage")
    if previous_root == output or output in previous_root.parents:
        raise PreflightError("Task 2E output directory must not replace or contain the previous Task 2D root")

    feature_manifest_path = source_root / "model_data" / "raw" / "feature_manifest.json"
    feature_manifest = _json_file(_existing_file(feature_manifest_path, "Task 2A feature manifest"), "Task 2A feature manifest")
    if feature_manifest.get("status") != "completed":
        raise PreflightError("Task 2A feature manifest is not complete")
    target_start = feature_manifest.get("target_start")
    target_end = feature_manifest.get("target_end")
    try:
        target_start_date = date.fromisoformat(str(target_start))
        target_end_date = date.fromisoformat(str(target_end))
    except ValueError as error:
        raise PreflightError("Task 2A feature manifest lacks a valid target_start/target_end") from error
    effective_response_end = response_end or _week_label_from_date(str(target_end), "target_end")
    if _iso_week(response_start, "response start") < _iso_week(_week_label_from_date(str(target_start), "target_start"), "target_start"):
        raise PreflightError("requested response start precedes the environmental bundle")
    if _iso_week(effective_response_end, "response end") > _iso_week(_week_label_from_date(str(target_end), "target_end"), "target_end"):
        raise PreflightError("requested response end exceeds the environmental bundle horizon")
    if _iso_week(effective_response_end, "response end") < _iso_week(response_start, "response start"):
        raise PreflightError("response end precedes response start")
    if analysis_end_date is None:
        analysis_end_date = target_end_date
    if analysis_start_date > analysis_end_date or analysis_end_date > target_end_date:
        raise PreflightError("analysis dates exceed or invert the environmental bundle horizon")

    previous_dir = previous_root / "revised_domain"
    previous_nodes = previous_dir / "raw" / "nodes.parquet"
    previous_edges = previous_dir / "graph" / "edges_queen.parquet"
    previous_manifest_path = previous_dir / "manifests" / "revised_domain_manifest.json"
    for label, path in (("previous revised nodes", previous_nodes), ("previous revised graph", previous_edges)):
        _existing_file(path, label)
    previous_manifest_sha = None
    previous_manifest_status = "unavailable"
    if previous_manifest_path.is_file():
        previous_manifest = _json_file(previous_manifest_path, "previous Task 2D manifest")
        previous_manifest_sha = sha256_file(previous_manifest_path)
        previous_manifest_status = str(previous_manifest.get("status", "unknown"))

    missing = [str(source_root / relative) for relative in TASK2E_REQUIRED_RELATIVE_FILES if not (source_root / relative).is_file()]
    if missing:
        raise PreflightError("Task 2A source bundle is incomplete: " + ", ".join(missing))
    observation_sha = sha256_file(observation)
    feature_manifest_sha = sha256_file(feature_manifest_path)
    boundary_sha = sha256_file(boundary)
    if observation_sha.lower() != expected_observation_sha256.lower():
        raise PreflightError("observation source SHA-256 does not match STGNN_EXPECTED_OBSERVATION_SHA256")
    if feature_manifest_sha.lower() != expected_feature_manifest_sha256.lower():
        raise PreflightError("Task 2A feature manifest SHA-256 does not match STGNN_EXPECTED_FEATURE_MANIFEST_SHA256")

    return {
        "stage": "task2e",
        "repository_sha": None,
        "observation_path": str(observation),
        "observation_sha256": observation_sha,
        "environmental_bundle_root": str(source_root),
        "feature_manifest_path": str(feature_manifest_path.resolve()),
        "feature_manifest_sha256": feature_manifest_sha,
        "environmental_target_start": str(target_start),
        "environmental_target_end": str(target_end),
        "previous_task2d_root": str(previous_root),
        "previous_task2d_manifest_path": str(previous_manifest_path) if previous_manifest_path.is_file() else None,
        "previous_task2d_manifest_sha256": previous_manifest_sha,
        "previous_task2d_manifest_status": previous_manifest_status,
        "boundary_path": str(boundary),
        "boundary_sha256": boundary_sha,
        "boundary_layer": boundary_layer,
        "analysis_start": analysis_start_date.isoformat(),
        "analysis_end": analysis_end_date.isoformat(),
        "response_start": response_start,
        "response_end": effective_response_end,
        "task2d_commit": task2d_commit,
        "selected_configuration": "Task 2E revised-domain refresh; model specification unchanged",
        "output_directory": str(output),
        "output_directory_state": "empty-existing" if output.exists() else "new",
    }


def validate_fullfit(
    output_root_value: str | Path | None,
    model_output_value: str | Path | None,
    front_features_value: str | Path | None,
    anthropogenic_features_value: str | Path | None,
    soil_features_value: str | Path | None,
    build_front_features: bool = False,
    front_feature_root_value: str | Path | None = None,
    expected_observation_sha256: str | None = None,
    response_start: str | None = None,
    response_end: str | None = None,
    resume_after_fit: bool = False,
    mask_path_value: str | Path | None = None,
) -> dict[str, Any]:
    output_root = _absolute_path(output_root_value, "full-fit output directory")
    model_output = _existing_directory(model_output_value, "Task 2E model-output root")
    anthropogenic = _existing_file(anthropogenic_features_value, "anthropogenic feature table")
    soil = _existing_file(soil_features_value, "soil feature table")
    mask_path = _existing_file(mask_path_value, "full-fit canonical mask") if mask_path_value is not None else None
    if build_front_features:
        front_root = _absolute_path(front_feature_root_value, "front-feature output root")
        if not front_root.parent.is_dir():
            raise PreflightError(f"front-feature output parent must already exist: {front_root.parent}")
        if front_root.is_symlink() or (front_root.exists() and (not front_root.is_dir() or any(front_root.iterdir()))):
            raise PreflightError(f"refusing to overwrite front-feature output directory: {front_root}")
        front_features = None
    else:
        front_root = None
        front_features = _existing_file(front_features_value, "front-history feature table")

    task2e_manifest_path = model_output / "manifests" / "revised_production_manifest.json"
    task2e_manifest = _json_file(_existing_file(task2e_manifest_path, "Task 2E data manifest"), "Task 2E data manifest")
    if task2e_manifest.get("status") != "production_dataset_built_audit_complete":
        raise PreflightError("Task 2E data manifest is not complete")
    response = task2e_manifest.get("response", {})
    observation_sha = str(task2e_manifest.get("observation_source", {}).get("sha256", ""))
    if not response.get("start") or not response.get("end") or not observation_sha:
        raise PreflightError("Task 2E data manifest lacks the response vintage or observation checksum")
    if response_start and response_start != response["start"]:
        raise PreflightError("requested full-fit response start differs from the Task 2E manifest")
    if response_end and response_end != response["end"]:
        raise PreflightError("requested full-fit response end differs from the Task 2E manifest")
    if expected_observation_sha256 is None or not re.fullmatch(r"[0-9a-fA-F]{64}", expected_observation_sha256):
        raise PreflightError("STGNN_EXPECTED_OBSERVATION_SHA256 is required and must be a 64-character SHA-256")
    if observation_sha.lower() != expected_observation_sha256.lower():
        raise PreflightError("Task 2E observation checksum does not match STGNN_EXPECTED_OBSERVATION_SHA256")
    if output_root == model_output or output_root in model_output.parents:
        raise PreflightError("full-fit output directory must not replace or contain the Task 2E input root")

    effective_start = response_start or str(response["start"])
    effective_end = response_end or str(response["end"])
    if effective_start != str(response["start"]) or effective_end != str(response["end"]):
        raise PreflightError("full-fit response horizon must match the Task 2E manifest")

    a3_feature_manifest = _json_file(
        _existing_file(A3_FEATURE_MANIFEST, "frozen A3 feature manifest"),
        "frozen A3 feature manifest",
    )
    expected_anthropogenic_sha = str(
        a3_feature_manifest.get("augmentation_manifest", {}).get("anthropogenic_source_sha256", "")
    )
    expected_soil_sha = str(a3_feature_manifest.get("soil_artifact_sha256", ""))
    anthropogenic_sha = sha256_file(anthropogenic)
    soil_sha = sha256_file(soil)
    if anthropogenic_sha.lower() != expected_anthropogenic_sha.lower():
        raise PreflightError("anthropogenic feature checksum differs from the frozen A3 feature manifest")
    if soil_sha.lower() != expected_soil_sha.lower():
        raise PreflightError("soil feature checksum differs from the frozen A3 feature manifest")

    input_paths: dict[str, Path] = {
        "production_manifest": task2e_manifest_path,
        "dynamic_features": model_output / "raw" / "dynamic_features.npy",
        "dynamic_history_features": model_output / "raw" / "dynamic_history_features.npy",
        "static_features": model_output / "raw" / "static_features.npy",
        "targets_count": model_output / "raw" / "targets_count.npy",
        "targets_presence": model_output / "raw" / "targets_presence.npy",
        "weeks": model_output / "raw" / "weeks.parquet",
        "calendar_features": model_output / "raw" / "calendar_features.parquet",
        "nodes": model_output / "raw" / "nodes.parquet",
        "anthropogenic_features": anthropogenic,
        "soil_features": soil,
        "a3_feature_manifest": A3_FEATURE_MANIFEST,
        "frozen_a3_evaluation_manifest": Path(__file__).resolve().parents[1] / "analysis" / "structured_a3_evaluation" / "results" / "frozen_a3_evaluation_manifest.json",
    }
    front_manifest_path: Path | None = None
    if front_features is not None:
        input_paths["front_features"] = front_features
        front_manifest_path = front_features.parent / "production_front_feature_manifest.json"
        front_manifest = _json_file(_existing_file(front_manifest_path, "front-feature manifest"), "front-feature manifest")
        if front_manifest.get("status") != "production_causal_front_features_complete":
            raise PreflightError("front-feature manifest is not complete")
        if sha256_file(front_features).lower() != str(front_manifest.get("feature_sha256", "")).lower():
            raise PreflightError("front-feature file checksum does not match its manifest")
        if front_manifest.get("response_start") != effective_start or front_manifest.get("response_end") != effective_end:
            raise PreflightError("front-feature response horizon differs from the Task 2E manifest")
        front_obs_sha = str(front_manifest.get("leakage_audit", {}).get("source_observation_sha256", ""))
        if front_obs_sha.lower() != observation_sha.lower():
            raise PreflightError("front-feature source observation checksum differs from the Task 2E manifest")
        input_paths["front_feature_manifest"] = front_manifest_path
    missing_sources = [name for name, path in input_paths.items() if not path.is_file()]
    if missing_sources:
        raise PreflightError("full-fit source artifacts are missing: " + ", ".join(missing_sources))
    source_records = {
        name: {"path": str(path.resolve()), "sha256": sha256_file(path)}
        for name, path in input_paths.items()
    }

    if resume_after_fit:
        if build_front_features:
            raise PreflightError("STGNN_RESUME_AFTER_FIT=1 cannot rebuild front features")
        if output_root.is_symlink() or not output_root.is_dir():
            raise PreflightError("full-fit resume requires an existing output directory")
        fit_manifest_path = output_root / "manifests" / "fullfit_fit_manifest.json"
        fit_manifest = _json_file(_existing_file(fit_manifest_path, "completed full-fit manifest"), "completed full-fit manifest")
        if fit_manifest.get("status") != "fit_complete" or fit_manifest.get("model") != "STRUCTURED_A3_FULLFIT":
            raise PreflightError("full-fit resume requires a completed STRUCTURED_A3_FULLFIT fit manifest")
        fit_horizon = fit_manifest.get("horizon", {})
        if fit_horizon.get("full_fit_start_week") != effective_start:
            raise PreflightError("completed full-fit start week differs from the selected Task 2E vintage")
        fit_end = fit_horizon.get("full_fit_end_week")
        if not fit_end or _iso_week(str(fit_end), "completed fit end") > _iso_week(effective_end, "Task 2E response end"):
            raise PreflightError("completed full-fit end week is outside the selected Task 2E vintage")
        recorded_sources = fit_manifest.get("source_artifacts", {})
        legacy_manifest_inputs = {"a3_feature_manifest", "front_feature_manifest"}
        immutable_manifest_inputs = {"a3_feature_manifest", "frozen_a3_evaluation_manifest"}
        for name, current in source_records.items():
            recorded = recorded_sources.get(name, {})
            if not recorded and name in legacy_manifest_inputs:
                # Older completed fits predate explicit provenance for these manifests.
                # Their referenced data files are still checked below and against the manifests above.
                continue
            if not recorded:
                raise PreflightError(f"completed fit manifest lacks source provenance for: {name}")
            if name not in immutable_manifest_inputs and Path(str(recorded.get("path", ""))).resolve(strict=False) != Path(current["path"]):
                raise PreflightError(f"full-fit resume source path differs from the completed fit: {name}")
            if str(recorded.get("sha256", "")).lower() != current["sha256"].lower():
                raise PreflightError(f"full-fit resume source checksum differs from the completed fit: {name}")
        required_fit_outputs = (
            "model/fullfit_a3_model.json", "model/fullfit_a3_manifest.json",
            "predictions/weekly_predictions.parquet", "manifests/fullfit_data_horizon.json",
        )
        missing_fit_outputs = [name for name in required_fit_outputs if not (output_root / name).is_file()]
        if missing_fit_outputs:
            raise PreflightError("completed full-fit resume is missing outputs: " + ", ".join(missing_fit_outputs))
    else:
        ensure_output_directory_available(output_root, "full-fit output directory")

    return {
        "stage": "fullfit",
        "model": "STRUCTURED_A3_FULLFIT",
        "repository_sha": None,
        "output_directory": str(output_root),
        "output_directory_state": "empty-existing" if output_root.exists() else "new",
        "task2e_model_output_root": str(model_output),
        "task2e_manifest_path": str(task2e_manifest_path),
        "task2e_manifest_sha256": sha256_file(task2e_manifest_path),
        "observation_source_sha256": observation_sha,
        "response_start": str(response["start"]),
        "response_end": str(response["end"]),
        "front_features": str(front_features) if front_features else None,
        "front_feature_output_root": str(front_root) if front_root else None,
        "anthropogenic_features": str(anthropogenic),
        "soil_features": str(soil),
        "canonical_mask": str(mask_path) if mask_path else None,
        "canonical_mask_sha256": sha256_file(mask_path) if mask_path else None,
        "a3_feature_manifest_path": str(A3_FEATURE_MANIFEST),
        "a3_feature_manifest_sha256": sha256_file(A3_FEATURE_MANIFEST),
        "source_artifacts": source_records,
        "resume_after_fit": resume_after_fit,
        "model_configuration": "Frozen STRUCTURED_A3_FULLFIT constants in the committed source; no configuration override accepted.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    env_parser = commands.add_parser("check-env")
    env_parser.add_argument("--mode", choices=sorted(SUPPORTED_ENV), required=True)

    task2a_root_parser = commands.add_parser("resolve-task2a-output")
    task2a_root_parser.add_argument("--output-root", default="")
    task2a_root_parser.add_argument("--refresh-root", default="")

    task2a_parser = commands.add_parser("task2a")
    task2a_parser.add_argument("--output-root", required=True)
    task2a_parser.add_argument("--environment-root", required=True)
    task2a_parser.add_argument("--template", required=True)
    task2a_parser.add_argument("--task1-manifest", required=True)
    task2a_parser.add_argument("--skip-dataset-build", action="store_true")
    task2a_parser.add_argument("--analysis-start", default="2024-01-01")
    task2a_parser.add_argument("--analysis-end")

    task2a_pipeline_parser = commands.add_parser("task2a-pipeline")
    task2a_pipeline_parser.add_argument("--output-root", required=True)
    task2a_pipeline_parser.add_argument("--task1-manifest", required=True)

    task2e_parser = commands.add_parser("task2e")
    task2e_parser.add_argument("--refresh-root", required=True)
    task2e_parser.add_argument("--source-output-root", required=True)
    task2e_parser.add_argument("--previous-output-root", required=True)
    task2e_parser.add_argument("--observation-path", required=True)
    task2e_parser.add_argument("--boundary-path", required=True)
    task2e_parser.add_argument("--boundary-layer", default="study_states")
    task2e_parser.add_argument("--analysis-start", default="2024-01-01")
    task2e_parser.add_argument("--analysis-end")
    task2e_parser.add_argument("--response-start", default="2025-W01")
    task2e_parser.add_argument("--response-end")
    task2e_parser.add_argument("--task2d-commit", default="e18777f1d98c539c92acc9ba1e7e4deb84b54319")
    task2e_parser.add_argument("--expected-observation-sha256", required=True)
    task2e_parser.add_argument("--expected-feature-manifest-sha256", required=True)

    fit_parser = commands.add_parser("fullfit")
    fit_parser.add_argument("--output-root", required=True)
    fit_parser.add_argument("--model-output", required=True)
    fit_parser.add_argument("--front-features")
    fit_parser.add_argument("--front-feature-root")
    fit_parser.add_argument("--build-front-features", action="store_true")
    fit_parser.add_argument("--anthropogenic-features", required=True)
    fit_parser.add_argument("--soil-features", required=True)
    fit_parser.add_argument("--expected-observation-sha256")
    fit_parser.add_argument("--response-start")
    fit_parser.add_argument("--response-end")
    fit_parser.add_argument("--resume-after-fit", action="store_true")
    fit_parser.add_argument("--mask-path")

    args = parser.parse_args(argv)
    try:
        if args.command == "check-env":
            check_environment_names(args.mode)
            print(json.dumps({"status": "CONFIG_ENVIRONMENT_VALIDATED", "mode": args.mode}, sort_keys=True))
        elif args.command == "resolve-task2a-output":
            print(resolve_task2a_output_root(args.output_root, args.refresh_root))
        elif args.command == "task2a":
            report = validate_task2a(
                args.output_root, args.environment_root, args.template, args.task1_manifest,
                args.skip_dataset_build, args.analysis_start, args.analysis_end,
            )
            print(json.dumps(report, indent=2, sort_keys=True))
        elif args.command == "task2a-pipeline":
            report = validate_task2a_pipeline(args.output_root, args.task1_manifest)
            print(json.dumps(report, indent=2, sort_keys=True))
        elif args.command == "task2e":
            report = validate_task2e(
                args.refresh_root, args.source_output_root, args.previous_output_root,
                args.observation_path, args.boundary_path, args.boundary_layer,
                args.analysis_start, args.analysis_end, args.response_start, args.response_end,
                args.task2d_commit, args.expected_observation_sha256,
                args.expected_feature_manifest_sha256,
            )
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            report = validate_fullfit(
                args.output_root, args.model_output, args.front_features,
                args.anthropogenic_features, args.soil_features,
                args.build_front_features, args.front_feature_root,
                args.expected_observation_sha256, args.response_start, args.response_end,
                args.resume_after_fit,
                args.mask_path,
            )
            print(json.dumps(report, indent=2, sort_keys=True))
    except PreflightError as error:
        print(f"preflight failed: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
