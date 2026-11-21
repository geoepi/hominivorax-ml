#!/usr/bin/env python3
"""Execute the approved W44 Q1 retrospective rolling-origin qualification.

The candidate full-fit artifact is read only.  Each forecast origin receives
its own expanding-window fit under the frozen A3 specification.  Environmental
inputs are evaluated under the approved E0 primary and E1 sensitivity rules;
non-environmental detection-history predictors are held at the first target
week's origin-causal values for all three horizons.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPOSITORY_ROOT))
from analysis.p2_operational_nowcast.scripts import run_p2_operational_nowcast as p2  # noqa: E402
import analysis.p5a_environmental_proxy.scripts.run_p5a_environmental_proxy as p5a  # noqa: E402
from analysis.p5a_environmental_proxy.scripts.run_p5a_environmental_proxy import (  # noqa: E402
    build_proxy_environment,
    latest_available_week,
    issue_timestamp,
    ENVIRONMENTAL_FEATURES,
)
import analysis.structured_a3_prospective_diagnostics.scripts.run_diagnostics as diagnostics  # noqa: E402
from analysis.structured_a3_prospective_diagnostics.scripts.run_diagnostics import (  # noqa: E402
    spatial_moran,
    spatial_permutation_p,
)


DESIGN_DIR = REPOSITORY_ROOT / "analysis" / "structured_a3_data_refresh_2026w44" / "qualification_design"
DESIGN_TABLE = DESIGN_DIR / "rolling_origin_design.csv"
RESULTS_RELATIVE = Path(
    "analysis/structured_a3_data_refresh_2026w44/qualification_execution/results/2026w44_q1_retrospective"
)
OBSERVATION_SHA256 = "784168081cc1d3206f3537b8731994cbfc34be15be7c515fe06710d4ea9bdaac"
CANDIDATE_MODEL_SHA256 = "b1a66a65efbb9a65f6a4c966044d2f87576ee7e6a1d1a294c0fb1855f684f53b"
CANDIDATE_ID = "STRUCTURED_A3_2026W44"
HORIZONS = (1, 2, 3)
PROXIES = ("REALIZED_ENV", "E0_LAST_AVAILABLE", "E1_TRAILING3_MEAN")
PRIMARY_PROXY = "E0_LAST_AVAILABLE"
HISTORY_FEATURES = tuple(p2.HISTORY_FEATURES)
HISTORY_INDICES = np.asarray([p2.FEATURE_ORDER.index(name) for name in HISTORY_FEATURES], dtype=np.int64)
ENVIRONMENTAL_INDICES = np.asarray([p2.FEATURE_ORDER.index(name) for name in ENVIRONMENTAL_FEATURES], dtype=np.int64)
KEY_COLUMNS = ["origin_week", "target_week", "horizon", "model_node_id"]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git_value(repository_root: Path, *args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", "-c", f"safe.directory={repository_root.as_posix()}", *args],
            cwd=repository_root,
            text=True,
        ).strip()
    except Exception:
        return "unknown"


def write_json(path: Path, value: Any) -> None:
    p2.write_json(path, value)


def make_origin_target_features(
    features: np.ndarray,
    target_indices: list[int],
    origin_index: int,
) -> np.ndarray:
    """Copy target covariates while holding detection history as of origin T.

    The feature row for T+1 contains detection-history values with a cutoff
    strictly before T+1, so it is the latest origin-causal history row.  Its
    history fields replace the otherwise future-updated history fields at
    T+2 and T+3.  Calendar and all other target-specific values remain intact.
    """
    require(len(target_indices) == len(HORIZONS), "three target weeks are required")
    history_source_index = origin_index + 1
    require(target_indices[0] == history_source_index, "first target must be origin plus one week")
    held = np.asarray(features[target_indices], dtype=np.float64).copy()
    source = np.asarray(features[history_source_index][:, HISTORY_INDICES], dtype=np.float64)
    held[:, :, HISTORY_INDICES] = source[None, :, :]
    return held


def make_proxy_environment(
    dynamic: np.ndarray,
    labels: list[str],
    origin_week: str,
    proxy_id: str,
) -> np.ndarray:
    """Return exactly three origin-safe 12-feature environmental slices."""
    values, metadata = build_proxy_environment(dynamic, labels, origin_week, proxy_id)
    require(values is not None, f"proxy is unavailable for {origin_week}: {proxy_id}")
    require(values.shape == (3, dynamic.shape[1], len(ENVIRONMENTAL_INDICES)), "proxy feature shape changed")
    require(np.isfinite(values).all(), f"nonfinite proxy inputs for {origin_week}: {proxy_id}")
    require(metadata["latest_available_week"] < origin_week, "environment proxy uses a same-week or future observation")
    return np.asarray(values, dtype=np.float64)


def make_proxy_target_features(
    features: np.ndarray,
    dynamic: np.ndarray,
    labels: list[str],
    origin_week: str,
    origin_index: int,
    proxy_id: str,
) -> np.ndarray:
    target_indices = list(range(origin_index + 1, origin_index + 1 + len(HORIZONS)))
    result = make_origin_target_features(features, target_indices, origin_index)
    if proxy_id != "REALIZED_ENV":
        result[:, :, ENVIRONMENTAL_INDICES] = make_proxy_environment(dynamic, labels, origin_week, proxy_id)
    require(np.isfinite(result).all(), f"nonfinite target features for {origin_week}, {proxy_id}")
    return result


def verify_design(design: pd.DataFrame, labels: list[str]) -> pd.DataFrame:
    required = {"design", "origin_week", "training_start_week", "training_cutoff_week", "target_week", "horizon_weeks", "node_count", "expected_node_horizon_rows"}
    require(required.issubset(design.columns), f"qualification origin table is missing columns: {sorted(required - set(design.columns))}")
    design = design.loc[design["design"].astype(str).eq("RETROSPECTIVE_UPDATED_VINTAGE_P2")].copy()
    design["horizon_weeks"] = design["horizon_weeks"].astype(int)
    origins = sorted(design["origin_week"].astype(str).unique(), key=p2.parse_week)
    require(len(origins) == 26, f"approved design must contain 26 origins; found {len(origins)}")
    require(origins[0] == "2026-W16" and origins[-1] == "2026-W41", "approved origin range changed")
    require(len(design) == 78, f"approved design must contain 78 origin-horizon rows; found {len(design)}")
    output: list[dict[str, Any]] = []
    for slot, origin_week in enumerate(origins):
        rows = design.loc[design["origin_week"].astype(str).eq(origin_week)].sort_values("horizon_weeks")
        require(rows["horizon_weeks"].tolist() == list(HORIZONS), f"origin {origin_week} does not have h=1,2,3")
        origin_index = labels.index(origin_week)
        targets = [labels[origin_index + horizon] for horizon in HORIZONS]
        require(rows["target_week"].astype(str).tolist() == targets, f"origin-target mapping differs from approved design for {origin_week}")
        require(set(rows["training_cutoff_week"].astype(str)) == {origin_week}, f"training cutoff differs from origin for {origin_week}")
        require(set(rows["training_start_week"].astype(str)) == {labels[0]}, f"training start changed for {origin_week}")
        require(set(rows["node_count"].astype(int)) == {p2.NODE_COUNT}, f"node count changed for {origin_week}")
        for horizon, target in zip(HORIZONS, targets):
            row = rows.loc[rows["horizon_weeks"].eq(horizon)].iloc[0]
            require(int(row["expected_node_horizon_rows"]) == p2.NODE_COUNT, f"design node rows changed for {origin_week} h={horizon}")
            output.append({
                "slot": slot,
                "origin_index": origin_index,
                "origin_week": origin_week,
                "training_start_week": labels[0],
                "training_cutoff_week": origin_week,
                "target_week": target,
                "horizon": horizon,
                "node_count": p2.NODE_COUNT,
                "status": "PENDING",
            })
    return pd.DataFrame(output)


def input_paths(args: argparse.Namespace, candidate_manifest: dict[str, Any]) -> dict[str, Path]:
    artifacts = candidate_manifest["source_artifacts"]
    return {
        "candidate_model": args.candidate_root / "fullfit_products/model/fullfit_a3_model.json",
        "candidate_model": args.candidate_root / "fullfit_products/model/fullfit_a3_model.json",
        "candidate_model_manifest": args.candidate_root / "fullfit_products/model/fullfit_a3_manifest.json",
        "candidate_fit_manifest": args.candidate_root / "fullfit_products/manifests/fullfit_fit_manifest.json",
        "revised_production_manifest": args.candidate_root / "revised_model_data/manifests/revised_production_manifest.json",
        "dynamic_features": args.candidate_root / "revised_model_data/raw/dynamic_features.npy",
        "static_features": args.candidate_root / "revised_model_data/raw/static_features.npy",
        "targets_count": args.candidate_root / "revised_model_data/raw/targets_count.npy",
        "weeks": args.candidate_root / "revised_model_data/raw/weeks.parquet",
        "calendar_features": args.candidate_root / "revised_model_data/raw/calendar_features.parquet",
        "nodes": args.candidate_root / "revised_model_data/raw/nodes.parquet",
        "queen_edges": args.candidate_root / "revised_model_data/raw/edges_queen.parquet",
        "front_features": Path(args.front_features),
        "road_night_features": Path(artifacts["anthropogenic_features"]["path"]),
        "soil_features": Path(artifacts["soil_features"]["path"]),
        "observation_source": Path(args.observation_source),
        "qualification_design": DESIGN_TABLE,
        "p0_freeze_manifest": args.repository_root / p2.P0_MANIFEST,
        "candidate_fullfit_implementation": args.repository_root / "analysis/predictor_augmentation/scripts/run_predictor_augmentation.py",
        "rolling_origin_fit_implementation": Path(p2.__file__),
        "environment_proxy_implementation": Path(p5a.__file__),
        "spatial_diagnostic_implementation": Path(diagnostics.__file__),
        "q1_execution_implementation": Path(__file__),
    }


def check_candidate_and_inputs(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    candidate_path = args.candidate_root / "fullfit_products/model/fullfit_a3_manifest.json"
    revised_path = args.candidate_root / "revised_model_data/manifests/revised_production_manifest.json"
    require(candidate_path.exists() and revised_path.exists(), "W44 candidate manifests are missing")
    candidate_manifest = json.loads(candidate_path.read_text(encoding="utf-8"))
    revised_manifest = json.loads(revised_path.read_text(encoding="utf-8"))
    model_path = args.candidate_root / "fullfit_products/model/fullfit_a3_model.json"
    require(candidate_manifest.get("candidate_id", CANDIDATE_ID) == CANDIDATE_ID, "candidate identifier differs from approved W44 candidate")
    require(candidate_manifest.get("model_sha256") == CANDIDATE_MODEL_SHA256, "candidate manifest model checksum differs from the approved checksum")
    require(sha256_file(model_path) == CANDIDATE_MODEL_SHA256, "W44 candidate model checksum changed")
    training_horizon = candidate_manifest.get("training_horizon")
    if isinstance(training_horizon, dict) and "end_week" in training_horizon:
        require(training_horizon["end_week"] == "2026-W44", "candidate training cutoff is not W44")
    require(int(candidate_manifest.get("node_count", p2.NODE_COUNT)) == p2.NODE_COUNT, "candidate node count changed")
    source = revised_manifest.get("observation_source", {})
    require(source.get("sha256") == OBSERVATION_SHA256, "W44 observation source checksum in the response manifest changed")
    require(sha256_file(Path(args.observation_source)) == OBSERVATION_SHA256, "authoritative observation source checksum changed")
    require(revised_manifest.get("final_usable_response_predictor_week") == "2026-W44", "W44 response/predictor endpoint changed")
    require(revised_manifest.get("environmental_maximum_complete_week") == "2026-W44", "environmental bundle no longer ends at W44")
    p0_verification = p2.verify_p0(args.repository_root)
    return candidate_manifest, revised_manifest, p0_verification


def validate_graph(bundle: dict[str, Any], revised_manifest: dict[str, Any], paths: dict[str, Path]) -> dict[str, Any]:
    nodes = bundle["nodes"].sort_values("model_node_id").reset_index(drop=True)
    require(np.array_equal(nodes["model_node_id"].to_numpy(np.int64), np.arange(p2.NODE_COUNT)), "W44 node IDs are not canonical and contiguous")
    require(not nodes.duplicated(["row", "column"]).any(), "W44 grid row/column keys are duplicated")
    edges = pd.read_parquet(paths["queen_edges"])
    require({"source_node", "target_node"}.issubset(edges.columns), "W44 Queen graph columns changed")
    src = edges["source_node"].to_numpy(np.int64)
    dst = edges["target_node"].to_numpy(np.int64)
    require(len(src) > 0 and np.all((src >= 0) & (src < p2.NODE_COUNT)) and np.all((dst >= 0) & (dst < p2.NODE_COUNT)), "W44 Queen graph references out-of-domain nodes")
    require(np.all(src != dst), "W44 Queen graph contains self-edges")
    pairs = pd.MultiIndex.from_arrays([src, dst])
    require(not pairs.has_duplicates, "W44 Queen graph contains duplicate directed edges")
    require(set(zip(src.tolist(), dst.tolist())) == set(zip(dst.tolist(), src.tolist())), "W44 Queen graph is not symmetric")
    graph_sha = sha256_file(paths["queen_edges"])
    require(graph_sha == revised_manifest["revised_domain"]["graph_checksum"], "W44 Queen graph checksum differs from the source manifest")
    return {"node_count": len(nodes), "unique_grid_cells": int(nodes[["row", "column"]].drop_duplicates().shape[0]), "directed_edge_count": len(edges), "graph_sha256": graph_sha, "symmetric": True, "self_edges": 0}


def prepare(args: argparse.Namespace) -> None:
    started = time.time()
    args.repository_root = args.repository_root.resolve()
    args.candidate_root = args.candidate_root.resolve()
    args.output_root = args.output_root.resolve()
    candidate_manifest, revised_manifest, p0_verification = check_candidate_and_inputs(args)
    source = revised_manifest.get("observation_source", {})
    model_output = args.candidate_root / "revised_model_data"
    args.model_output = model_output
    if args.front_features is None:
        args.front_features = args.candidate_root / "front_features/causal_front_features.parquet"
    candidate = json.loads((args.candidate_root / "fullfit_products/model/fullfit_a3_manifest.json").read_text(encoding="utf-8"))
    sources = candidate["source_artifacts"]
    args.road_night = Path(sources["anthropogenic_features"]["path"])
    args.soil = Path(sources["soil_features"]["path"])

    output = args.output_root
    require(output != args.candidate_root and args.candidate_root not in output.parents, "Q1 output root must be separate from the immutable W44 candidate root")
    require("q1" in output.name.lower() or "q1" in str(output).lower(), "Q1 output root must be versioned and task-specific")
    if output.exists():
        existing_files = [path for path in output.iterdir() if path.name != "logs"]
        require(not existing_files or (output / "manifests/input_manifest.json").exists(), "refusing to reuse a nonempty Q1 output root without its input manifest")
    output.mkdir(parents=True, exist_ok=True)
    for folder in ("fits", "predictions", "manifests", "logs"):
        (output / folder).mkdir(parents=True, exist_ok=True)

    verification = p0_verification
    bundle = p2.load_bundle(argparse.Namespace(
        model_output=model_output,
        front_features=Path(args.front_features),
        road_night=args.road_night,
        soil=args.soil,
    ))
    labels = bundle["labels"]
    require(labels[0] == "2025-W01" and labels[-1] == "2026-W44" and len(labels) == 96, "W44 response week coverage changed")
    origins = verify_design(pd.read_csv(DESIGN_TABLE), labels)
    front = bundle["front"]
    history_audit_rows = []
    for origin_week in origins["origin_week"].drop_duplicates().astype(str):
        origin_index = labels.index(origin_week)
        source_index = origin_index + 1
        source_rows = front.loc[front["week_index"].astype(int).eq(source_index)]
        require(len(source_rows) == p2.NODE_COUNT, f"origin-causal history rows are incomplete for {origin_week}")
        require(source_rows["history_cutoff_week"].notna().all(), f"origin-causal history cutoff missing for {origin_week}")
        cutoffs = source_rows["history_cutoff_week"].astype(str)
        later = [week for week in cutoffs if p2.parse_week(week) > p2.parse_week(origin_week)]
        require(not later, f"future history is present at origin {origin_week}")
        history_audit_rows.append({
            "origin_week": origin_week,
            "history_feature_week": labels[source_index],
            "cutoff_min": min(cutoffs, key=p2.parse_week),
            "cutoff_max": max(cutoffs, key=p2.parse_week),
            "rows": len(source_rows),
            "future_history_uses": 0,
        })
    graph = validate_graph(bundle, revised_manifest, input_paths(args, candidate_manifest))
    cache = output / "manifests/a3_features.npy"
    if not cache.exists():
        def save_features(temporary: Path) -> None:
            with temporary.open("wb") as handle:
                np.save(handle, bundle["features"])
        p2.atomic_write(cache, save_features)
    paths = input_paths(args, candidate_manifest)
    missing = [str(path) for path in paths.values() if not path.exists()]
    require(not missing, f"W44 input artifact is missing: {missing}")
    input_files = {name: {"path": str(path), "sha256": sha256_file(path), "size_bytes": path.stat().st_size} for name, path in paths.items()}
    disk = __import__("shutil").disk_usage(output.parent)
    input_manifest = {
        "status": "PREFLIGHT_PASSED",
        "candidate_id": CANDIDATE_ID,
        "candidate_model_sha256": CANDIDATE_MODEL_SHA256,
        "observation_source_sha256": OBSERVATION_SHA256,
        "source_dataset": {"row_count": source.get("row_count"), "maximum_iso_week": source.get("maximum_iso_week"), "maximum_date": source.get("maximum_date")},
        "response_and_environment": {"start_week": labels[0], "end_week": labels[-1], "week_count": len(labels), "node_count": p2.NODE_COUNT, "predictor_count": p2.FEATURE_COUNT, "environmental_maximum_complete_week": revised_manifest.get("environmental_maximum_complete_week")},
        "p0_specification_verification": verification,
        "candidate_manifest_sha256": sha256_file(paths["candidate_model_manifest"]),
        "revised_production_manifest_sha256": sha256_file(paths["revised_production_manifest"]),
        "source_files": input_files,
        "feature_cache_sha256": sha256_file(cache),
        "feature_cache_shape": list(bundle["features"].shape),
        "feature_order": p2.FEATURE_ORDER,
        "rolling_origin_rows": len(origins),
        "rolling_origin_count": int(origins["origin_week"].nunique()),
        "origin_target_design_sha256": sha256_file(DESIGN_TABLE),
        "history_cutoff_rule": "For each origin T, use the first target week T+1 history row only; its history cutoff must be <= T and is held fixed across h=1,2,3.",
        "history_cutoff_audit": history_audit_rows,
        "environmental_specs": {"primary": "E0_LAST_AVAILABLE", "sensitivity": "E1_TRAILING3_MEAN", "availability_cutoff": "T-1", "historical_release_timestamp_available": False},
        "graph_contract": graph,
        "environmental_bundle_contract": {"array_shape": list(bundle["dynamic"].shape), "feature_names": ENVIRONMENTAL_FEATURES, "input_dataset_identity": revised_manifest.get("task")},
        "validation_type": "RETROSPECTIVE_UPDATED_VINTAGE_HINDCAST; historical source release dates unavailable",
        "outcome_maturity": "NOT_CERTIFIED; forecasts may be retained and descriptive metrics computed, but no primary qualification scoring decision is supported",
        "repository": {"branch": git_value(args.repository_root, "branch", "--show-current"), "sha": git_value(args.repository_root, "rev-parse", "HEAD")},
        "runtime": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "scipy": __import__("scipy").__version__,
            "scikit_learn": __import__("sklearn").__version__,
        },
        "rolling_origin_fit_implementation": {
            "path": str(paths["rolling_origin_fit_implementation"]),
            "sha256": input_files["rolling_origin_fit_implementation"]["sha256"],
            "fit_function": "p2.fit_fixed_theta",
        },
        "atlas_output_root": str(output),
        "repository_results_path": str(args.repository_root / RESULTS_RELATIVE),
        "filesystem_free_bytes_before_run": int(disk.free),
        "written_at_epoch_seconds": time.time(),
        "prepare_runtime_seconds": time.time() - started,
        "no_candidate_or_production_writes": True,
    }
    manifest_path = output / "manifests/input_manifest.json"
    if manifest_path.exists():
        old = json.loads(manifest_path.read_text(encoding="utf-8"))
        require(old.get("candidate_model_sha256") == CANDIDATE_MODEL_SHA256 and old.get("observation_source_sha256") == OBSERVATION_SHA256 and old.get("origin_target_design_sha256") == input_manifest["origin_target_design_sha256"], "existing Q1 output root belongs to a different input or design")
        require(old.get("source_files") == input_manifest["source_files"], "existing Q1 output root was prepared from different input files or code")
        require(old.get("feature_cache_sha256") == input_manifest["feature_cache_sha256"], "existing Q1 feature cache does not match its original input manifest")
    else:
        write_json(manifest_path, input_manifest)
    p2.write_csv(output / "manifests/rolling_origin_manifest.csv", origins)
    p2.write_csv(output / "manifests/history_cutoff_audit.csv", pd.DataFrame(history_audit_rows))
    write_json(output / "manifests/p0_verification.json", p0_verification)
    write_json(output / "manifests/procedure_spec.json", {
        "candidate_id": CANDIDATE_ID,
        "candidate_model_sha256": CANDIDATE_MODEL_SHA256,
        "origin_fit_count": 26,
        "origin_range": ["2026-W16", "2026-W41"],
        "target_horizons": list(HORIZONS),
        "training_window": "expanding from 2025-W01 through each origin T",
        "fit_parameters": {"feature_count": p2.FEATURE_COUNT, "feature_order": p2.FEATURE_ORDER, "penalty": p2.PENALTY, "theta": p2.FIXED_THETA, "objective": "exact_joint_hurdle_nll", "optimizer": "L-BFGS-B", "optimizer_maxiter": p2.OPTIMIZER_MAXITER},
        "environmental_specification": {"primary": "E0_LAST_AVAILABLE", "sensitivity": "E1_TRAILING3_MEAN", "issue_time_cutoff": "observation week <= T-1", "all_horizons_use_same_origin-state proxy": True},
        "non_environmental_future_history": "History predictors are held at the T-causal values sourced from week T+1 across h=1,2,3.",
        "target_outcomes_in_fit": False,
        "no_tuning": True,
        "no_feature_selection": True,
        "no_recalibration": True,
        "scoring_role": "DESCRIPTIVE_ONLY_UNLESS_TARGET_MATURITY_IS_AUTHORIZED",
    })
    print(json.dumps({"status": "PREFLIGHT_PASSED", "candidate_model_sha256": CANDIDATE_MODEL_SHA256, "origins": int(origins["origin_week"].nunique()), "origin_horizon_blocks": len(origins), "graph": graph, "output_root": str(output)}, indent=2))


def load_run_inputs(args: argparse.Namespace) -> tuple[dict[str, Any], np.ndarray, np.ndarray, pd.DataFrame, list[str], np.ndarray, pd.DataFrame]:
    root = args.output_root
    manifest = json.loads((root / "manifests/input_manifest.json").read_text(encoding="utf-8"))
    require(manifest.get("candidate_model_sha256") == CANDIDATE_MODEL_SHA256, "Q1 input manifest candidate mismatch")
    require(manifest.get("observation_source_sha256") == OBSERVATION_SHA256, "Q1 input manifest source mismatch")
    candidate_model = args.candidate_root / "fullfit_products/model/fullfit_a3_model.json"
    observation = Path(args.observation_source)
    require(sha256_file(candidate_model) == CANDIDATE_MODEL_SHA256, "candidate model changed after preflight")
    require(sha256_file(observation) == OBSERVATION_SHA256, "observation source changed after preflight")
    features = np.load(root / "manifests/a3_features.npy", mmap_mode="r")
    model_output = args.candidate_root / "revised_model_data"
    counts = np.load(model_output / "raw/targets_count.npy", mmap_mode="r")
    dynamic = np.load(model_output / "raw/dynamic_features.npy", mmap_mode="r")
    labels = pd.read_parquet(model_output / "raw/weeks.parquet")["iso_week"].astype(str).tolist()
    nodes = pd.read_parquet(model_output / "raw/nodes.parquet").sort_values("model_node_id").reset_index(drop=True)
    origin_manifest = pd.read_csv(root / "manifests/rolling_origin_manifest.csv")
    require(tuple(features.shape) == (len(labels), p2.NODE_COUNT, p2.FEATURE_COUNT), "Q1 feature cache shape changed")
    require(tuple(counts.shape) == (len(labels), p2.NODE_COUNT), "Q1 response array shape changed")
    require(tuple(dynamic.shape) == (len(labels), p2.NODE_COUNT, len(ENVIRONMENTAL_INDICES)), "Q1 environmental feature shape changed")
    require(np.array_equal(nodes["model_node_id"].to_numpy(np.int64), np.arange(p2.NODE_COUNT)), "Q1 canonical node order changed")
    return manifest, features, counts, nodes, labels, dynamic, origin_manifest


def verify_origin_history(args: argparse.Namespace, origin_row: pd.Series, labels: list[str]) -> None:
    origin_week = str(origin_row["origin_week"])
    audit = pd.read_csv(args.output_root / "manifests/history_cutoff_audit.csv")
    row = audit.loc[audit["origin_week"].astype(str).eq(origin_week)]
    require(len(row) == 1, f"history-cutoff audit missing origin {origin_week}")
    row = row.iloc[0]
    require(p2.parse_week(str(row["cutoff_max"])) <= p2.parse_week(origin_week), f"origin {origin_week} contains post-origin history")
    require(labels[int(origin_row["origin_index"]) + 1] == str(row["history_feature_week"]), f"origin {origin_week} history row changed")


def origin(args: argparse.Namespace) -> None:
    started = time.time()
    manifest, features, counts, nodes, labels, dynamic, origins = load_run_inputs(args)
    slots = origins[["slot", "origin_index", "origin_week", "training_cutoff_week", "target_week", "horizon"]].drop_duplicates(["slot", "origin_index", "origin_week"]).sort_values("slot")
    require(0 <= int(args.origin_slot) < len(slots), f"origin slot outside approved range: {args.origin_slot}")
    selected = slots.iloc[int(args.origin_slot)]
    origin_index = int(selected["origin_index"])
    origin_week = str(selected["origin_week"])
    verify_origin_history(args, selected, labels)
    output = args.output_root
    fit_path = output / f"fits/origin_{origin_week}.json"
    prediction_path = output / f"predictions/origin_{origin_week}.parquet"
    status_path = output / f"manifests/origin_{origin_week}.json"
    if status_path.exists() and fit_path.exists() and prediction_path.exists():
        existing = json.loads(status_path.read_text(encoding="utf-8"))
        if existing.get("status") == "COMPLETED" and existing.get("candidate_model_sha256") == CANDIDATE_MODEL_SHA256:
            require(existing.get("fit_artifact_sha256") == sha256_file(fit_path), f"resumed fit hash mismatch for {origin_week}")
            require(existing.get("prediction_artifact_sha256") == sha256_file(prediction_path), f"resumed prediction hash mismatch for {origin_week}")
            print(f"Q1_ORIGIN_ALREADY_COMPLETE {origin_week}")
            return

    target_indices = [origin_index + horizon for horizon in HORIZONS]
    target_weeks = [labels[index] for index in target_indices]
    manifest_rows = origins.loc[origins["origin_week"].astype(str).eq(origin_week)].sort_values("horizon")
    require(manifest_rows["target_week"].astype(str).tolist() == target_weeks, f"approved target mapping changed for {origin_week}")
    raw_train = np.asarray(features[: origin_index + 1], dtype=np.float64).reshape(-1, p2.FEATURE_COUNT)
    y_train = np.asarray(counts[: origin_index + 1], dtype=np.int64).reshape(-1)
    x_train, _, scaling = p2.standardize(raw_train, raw_train[:1], p2.FEATURE_ORDER)
    fit_state = p2.fit_fixed_theta(x_train, y_train)
    require(bool(fit_state["fit_info"]["occurrence_success"]) and bool(fit_state["fit_info"]["count_success"]), f"origin fit did not converge: {origin_week}")
    mean = np.asarray(scaling["training_mean"], dtype=np.float64)
    scale = np.asarray(scaling["training_sd"], dtype=np.float64)
    prior_occupied = np.any(np.asarray(counts[: origin_index + 1]) > 0, axis=0)
    records: list[pd.DataFrame] = []
    target_meta: dict[str, dict[str, Any]] = {}
    for proxy_id in PROXIES:
        raw_eval = make_proxy_target_features(features, dynamic, labels, origin_week, origin_index, proxy_id)
        standardized = (raw_eval.reshape(-1, p2.FEATURE_COUNT) - mean[None, :]) / scale[None, :]
        probability, conditional, mu = p2.predict(fit_state, standardized)
        for h_index, (horizon, target_index, target_week) in enumerate(zip(HORIZONS, target_indices, target_weeks)):
            start = h_index * p2.NODE_COUNT
            stop = (h_index + 1) * p2.NODE_COUNT
            observed = np.asarray(counts[target_index], dtype=np.int64)
            prevalence, prevalence_source = p2.historical_prevalence(np.asarray(counts), labels, origin_index, target_week)
            if proxy_id == "REALIZED_ENV":
                proxy_window = target_week
            elif proxy_id == "E0_LAST_AVAILABLE":
                proxy_window = latest_available_week(origin_week)
            else:
                proxy_window = ";".join(labels[origin_index - 3 : origin_index])
            records.append(pd.DataFrame({
                "origin_week": origin_week,
                "target_week": target_week,
                "horizon": horizon,
                "model_node_id": np.arange(p2.NODE_COUNT, dtype=np.int64),
                "row": nodes["row"].to_numpy(np.int64),
                "column": nodes["column"].to_numpy(np.int64),
                "lon": nodes["lon"].to_numpy(np.float64),
                "lat": nodes["lat"].to_numpy(np.float64),
                "country_or_domain_region": nodes["country_or_domain_region"].astype(str).to_numpy(),
                "observed_count": observed,
                "observed_positive": (observed > 0).astype(np.int8),
                "p_occurrence": probability[start:stop],
                "conditional_count_mean": conditional[start:stop],
                "underlying_mu": mu[start:stop],
                "expected_count": probability[start:stop] * conditional[start:stop],
                "persistence_probability": prior_occupied.astype(float),
                "historical_prevalence_probability": prevalence,
                "historical_reference_source": prevalence_source,
                "previously_occupied": prior_occupied,
                "prediction_frontier_class": np.where(prior_occupied, "previously_occupied", "previously_unoccupied"),
                "outcome_frontier_label": np.select([
                    (observed > 0) & prior_occupied,
                    (observed > 0) & (~prior_occupied),
                ], ["established_core", "newly_detected_frontier"], default="not_positive"),
                "proxy_id": proxy_id,
                "proxy_source_week": target_week if proxy_id == "REALIZED_ENV" else latest_available_week(origin_week),
                "proxy_window": proxy_window,
                    "issue_timestamp": p5a.issue_timestamp(origin_week),
                "proxy_rule": {"REALIZED_ENV": "target-week realized environmental reference", "E0_LAST_AVAILABLE": "persist T-1 feature state through h=1,2,3", "E1_TRAILING3_MEAN": "mean exactly T-1,T-2,T-3 and persist through h=1,2,3"}[proxy_id],
                "scoring_eligibility": "NOT_CERTIFIED_TARGET_MATURITY",
            }))
            target_meta[f"h{horizon}"] = {"target_week": target_week, "rows": p2.NODE_COUNT}
    prediction = pd.concat(records, ignore_index=True)
    prediction_keys = [*KEY_COLUMNS, "proxy_id"]
    require(not prediction.duplicated(prediction_keys).any(), f"origin {origin_week} prediction keys are duplicated")
    require(len(prediction) == len(PROXIES) * len(HORIZONS) * p2.NODE_COUNT, f"origin {origin_week} prediction row count changed")
    require(np.isfinite(prediction[["p_occurrence", "conditional_count_mean", "underlying_mu", "expected_count"]].to_numpy(np.float64)).all(), f"nonfinite prediction values for {origin_week}")
    require(prediction["p_occurrence"].between(0.0, 1.0).all(), f"occurrence probabilities out of range for {origin_week}")
    require((prediction[["conditional_count_mean", "underlying_mu", "expected_count"]] >= 0).all().all(), f"negative count prediction for {origin_week}")
    p2.write_parquet(prediction_path, prediction)
    fit_artifact = {
        "candidate_id": CANDIDATE_ID,
        "candidate_model_sha256": CANDIDATE_MODEL_SHA256,
        "origin_week": origin_week,
        "training_start": labels[0],
        "training_cutoff": origin_week,
        "training_week_count": origin_index + 1,
        "training_rows": int(len(y_train)),
        "training_positive_rows": int((y_train > 0).sum()),
        "feature_order": p2.FEATURE_ORDER,
        "feature_count": p2.FEATURE_COUNT,
        "penalty": p2.PENALTY,
        "theta": p2.FIXED_THETA,
        "theta_fixed": True,
        "objective": "exact_joint_hurdle_nll",
        "optimizer": "L-BFGS-B",
        "optimizer_maxiter": p2.OPTIMIZER_MAXITER,
        "preprocessing": scaling,
        "occurrence_coefficients": np.asarray(fit_state["occurrence_beta"], dtype=float).tolist(),
        "count_coefficients": np.asarray(fit_state["count_beta"], dtype=float).tolist(),
        "fit_info": fit_state["fit_info"],
        "fitting_implementation_sha256": manifest["source_files"]["origin_fit_implementation"]["sha256"],
        "environmental_proxy_predictions": list(PROXIES),
        "origin_causal_history_features_held_across_horizons": list(HISTORY_FEATURES),
        "future_history_uses": 0,
        "validation_type": manifest["validation_type"],
    }
    write_json(fit_path, fit_artifact)
    status = {
        "status": "COMPLETED",
        "candidate_id": CANDIDATE_ID,
        "candidate_model_sha256": CANDIDATE_MODEL_SHA256,
        "origin_index": origin_index,
        "origin_week": origin_week,
        "training_cutoff": origin_week,
        "targets": target_meta,
        "horizons": list(HORIZONS),
        "proxies": list(PROXIES),
        "model_state": "origin-specific expanding window; target outcomes excluded",
        "convergence": fit_state["fit_info"],
        "future_history_uses": 0,
        "prediction_rows": len(prediction),
        "fit_artifact": str(fit_path),
        "fit_artifact_sha256": sha256_file(fit_path),
        "prediction_artifact": str(prediction_path),
        "prediction_artifact_sha256": sha256_file(prediction_path),
        "runtime_seconds": time.time() - started,
        "status_written_epoch_seconds": time.time(),
    }
    write_json(status_path, status)
    print(json.dumps(status, indent=2))


def paired_bootstrap_differences(frame: pd.DataFrame, left_proxy: str, right_proxy: str, horizon: int, replicates: int, seed: int, frontier_only: bool = False) -> list[dict[str, Any]]:
    selected = frame.loc[frame["horizon"].eq(horizon)].copy()
    if frontier_only:
        selected = selected.loc[selected["prediction_frontier_class"].eq("previously_unoccupied")]
    left = selected.loc[selected["proxy_id"].eq(left_proxy)].sort_values(KEY_COLUMNS, kind="mergesort").reset_index(drop=True)
    right = selected.loc[selected["proxy_id"].eq(right_proxy)].sort_values(KEY_COLUMNS, kind="mergesort").reset_index(drop=True)
    require(left[KEY_COLUMNS].equals(right[KEY_COLUMNS]), f"paired proxy keys differ: {left_proxy} vs {right_proxy}, h={horizon}")
    weeks = sorted(left["target_week"].astype(str).unique(), key=p2.parse_week)
    positions = {week: np.flatnonzero(left["target_week"].astype(str).to_numpy() == week) for week in weeks}
    metrics = ["brier", "auprc", "calibration_intercept", "full_expected_mae", "conditional_mae"]
    if frontier_only:
        metrics = ["brier"]
    collected: dict[str, list[float]] = {metric: [] for metric in metrics}
    rng = np.random.default_rng(seed)
    for _ in range(replicates):
        draws = rng.choice(np.asarray(weeks, dtype=object), size=len(weeks), replace=True)
        indices = np.concatenate([positions[str(week)] for week in draws]) if len(draws) else np.asarray([], dtype=np.int64)
        lm = {**p2.occurrence_metrics(left.iloc[indices]), **p2.count_metrics(left.iloc[indices])}
        rm = {**p2.occurrence_metrics(right.iloc[indices]), **p2.count_metrics(right.iloc[indices])}
        for metric in metrics:
            lv, rv = lm.get(metric), rm.get(metric)
            if lv is not None and rv is not None and np.isfinite(lv) and np.isfinite(rv):
                collected[metric].append(float(lv - rv))
    original_left = {**p2.occurrence_metrics(left), **p2.count_metrics(left)}
    original_right = {**p2.occurrence_metrics(right), **p2.count_metrics(right)}
    rows = []
    for metric in metrics:
        values = np.asarray(collected[metric], dtype=np.float64)
        lv, rv = original_left.get(metric), original_right.get(metric)
        estimate = float(lv - rv) if lv is not None and rv is not None and np.isfinite(lv) and np.isfinite(rv) else math.nan
        rows.append({
            "left_proxy": left_proxy,
            "right_proxy": right_proxy,
            "horizon": horizon,
            "scope": "previously_unoccupied" if frontier_only else "all",
            "metric": metric,
            "difference_left_minus_right": estimate,
            "bootstrap_replicates": int(len(values)),
            "lower_95": float(np.quantile(values, 0.025)) if len(values) else math.nan,
            "upper_95": float(np.quantile(values, 0.975)) if len(values) else math.nan,
            "resampling_unit": "paired target-week blocks; all nodes and horizons for each selected target week",
            "seed": seed,
            "scoring_eligibility": "NOT_CERTIFIED_TARGET_MATURITY",
        })
    return rows


def residual_spatial_summary(frame: pd.DataFrame, edges: pd.DataFrame) -> pd.DataFrame:
    primary = frame.loc[frame["proxy_id"].eq(PRIMARY_PROXY)].copy()
    source = edges["source_node"].to_numpy(np.int64)
    target = edges["target_node"].to_numpy(np.int64)
    residual_definitions = {
        "occurrence": lambda x: x["observed_positive"].to_numpy(float) - x["p_occurrence"].to_numpy(float),
        "positive_count": lambda x: np.where(x["observed_count"].to_numpy(float) > 0, x["observed_count"].to_numpy(float) - x["conditional_count_mean"].to_numpy(float), np.nan),
        "combined_expected_count": lambda x: x["observed_count"].to_numpy(float) - x["expected_count"].to_numpy(float),
    }
    rows: list[dict[str, Any]] = []
    for horizon in HORIZONS:
        work = primary.loc[primary["horizon"].eq(horizon)]
        residual_blocks = {name: [] for name in residual_definitions}
        for target_week, block in work.groupby("target_week", sort=True):
            block = block.sort_values("model_node_id")
            require(len(block) == p2.NODE_COUNT and np.array_equal(block["model_node_id"].to_numpy(np.int64), np.arange(p2.NODE_COUNT)), f"Moran input node order changed for {target_week} h={horizon}")
            for name, fn in residual_definitions.items():
                values = fn(block)
                residual_blocks[name].append(values)
                rows.append({
                    "scope": "target_week_horizon",
                    "target_week": target_week,
                    "horizon": horizon,
                    "residual_type": name,
                    "n": int(np.isfinite(values).sum()),
                    "moran_i": spatial_moran(values, source, target),
                    "permutation_p": math.nan,
                    "permutations": 0,
                })
        for name, blocks in residual_blocks.items():
            matrix = np.vstack(blocks)
            values = np.nanmean(matrix, axis=0) if name == "positive_count" else np.mean(matrix, axis=0)
            rows.append({
                "scope": "pooled_node_mean_by_horizon",
                "target_week": "ALL",
                "horizon": horizon,
                "residual_type": name,
                "n": int(np.isfinite(values).sum()),
                "moran_i": diagnostics.spatial_moran(values, source, target),
                "permutation_p": diagnostics.spatial_permutation_p(values, source, target, seed=20261017, n_permutations=199),
                "permutations": 199,
            })
    return pd.DataFrame(rows)


def geographic_frontier_metrics(frame: pd.DataFrame) -> pd.DataFrame:
    """Cross existing canonical region labels with origin-time frontier strata."""
    rows = []
    for key, group in frame.groupby(
        ["horizon", "country_or_domain_region", "prediction_frontier_class"],
        sort=True,
        dropna=False,
    ):
        horizon, region, frontier = key
        rows.append(p2.metric_rows_for_group(group, {
            "horizon": int(horizon),
            "region": str(region),
            "prediction_frontier_class": str(frontier),
            "classification_uses": "recorded occupancy through origin T only",
            "geographic_partition": "unchanged country_or_domain_region labels from W44 canonical node table",
        }))
    return pd.DataFrame(rows)


def proxy_threshold_comparison(frame: pd.DataFrame) -> pd.DataFrame:
    """Apply the existing P5A bounded comparisons descriptively, without new limits."""
    rows = []
    for proxy_id in ("E0_LAST_AVAILABLE", "E1_TRAILING3_MEAN"):
        for horizon in HORIZONS:
            proxy = frame.loc[(frame["proxy_id"].eq(proxy_id)) & frame["horizon"].eq(horizon)]
            realized = frame.loc[(frame["proxy_id"].eq("REALIZED_ENV")) & frame["horizon"].eq(horizon)]
            proxy_all = {**p2.occurrence_metrics(proxy), **p2.count_metrics(proxy)}
            realized_all = {**p2.occurrence_metrics(realized), **p2.count_metrics(realized)}
            proxy_frontier = proxy.loc[proxy["prediction_frontier_class"].eq("previously_unoccupied")]
            realized_frontier = realized.loc[realized["prediction_frontier_class"].eq("previously_unoccupied")]
            proxy_frontier_brier = p2.occurrence_metrics(proxy_frontier)["brier"]
            realized_frontier_brier = p2.occurrence_metrics(realized_frontier)["brier"]
            differences = {
                "brier_increase": proxy_all["brier"] - realized_all["brier"],
                "auprc_difference": proxy_all["auprc"] - realized_all["auprc"],
                "calibration_intercept_abs_change": abs(proxy_all["calibration_intercept"] - realized_all["calibration_intercept"]),
                "full_expected_mae_increase": proxy_all["full_expected_mae"] - realized_all["full_expected_mae"],
                "conditional_mae_increase": proxy_all["conditional_mae"] - realized_all["conditional_mae"],
                "frontier_brier_increase": proxy_frontier_brier - realized_frontier_brier,
            }
            strict_limits = {"brier_increase": 0.002, "calibration_intercept_abs_change": 0.05, "full_expected_mae_increase": 0.02, "conditional_mae_increase": 0.10, "frontier_brier_increase": 0.002}
            bounded_limits = {"brier_increase": 0.005, "calibration_intercept_abs_change": 0.10, "full_expected_mae_increase": 0.05, "conditional_mae_increase": 0.25, "frontier_brier_increase": 0.005}
            strict_ok = []
            bounded_ok = []
            for metric, limit in strict_limits.items():
                value = differences[metric]
                if metric == "frontier_brier_increase" and not np.isfinite(value):
                    continue
                strict_ok.append(bool(np.isfinite(value) and value <= limit))
                bounded_ok.append(bool(np.isfinite(value) and value <= bounded_limits[metric]))
            ref_auprc = realized_all["auprc"]
            auprc_diff = differences["auprc_difference"]
            auprc_strict = bool(np.isfinite(ref_auprc) and np.isfinite(auprc_diff) and auprc_diff >= -0.05 * max(float(ref_auprc), 1e-12))
            auprc_bounded = bool(np.isfinite(ref_auprc) and np.isfinite(auprc_diff) and auprc_diff >= -0.10 * max(float(ref_auprc), 1e-12))
            strict_ok.append(auprc_strict)
            bounded_ok.append(auprc_bounded)
            rows.append({
                "proxy_id": proxy_id,
                "reference_proxy": "REALIZED_ENV",
                "horizon": horizon,
                **differences,
                "reference_auprc": ref_auprc,
                "strict_pass_descriptive": bool(all(strict_ok)),
                "bounded_pass_descriptive": bool(all(bounded_ok)),
                "comparison_status": "DESCRIPTIVE_ONLY_UNCERTIFIED_TARGET_MATURITY",
                "threshold_source": "analysis/p7i_issue_time_validation/p7i_prespecification.md; retained P5A strict/bounded limits",
                "frontier_scope": "previously_unoccupied across canonical domain; when estimable",
            })
    return pd.DataFrame(rows)


def aggregate(args: argparse.Namespace) -> None:
    started = time.time()
    root = args.output_root
    output_results = args.repository_root / RESULTS_RELATIVE
    output_results.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((root / "manifests/input_manifest.json").read_text(encoding="utf-8"))
    require(sha256_file(args.candidate_root / "fullfit_products/model/fullfit_a3_model.json") == CANDIDATE_MODEL_SHA256, "W44 candidate model changed before aggregation")
    require(sha256_file(Path(args.observation_source)) == OBSERVATION_SHA256, "observation source changed before aggregation")
    origin_manifest = pd.read_csv(root / "manifests/rolling_origin_manifest.csv")
    statuses = []
    frames = []
    for origin_week in origin_manifest["origin_week"].drop_duplicates().astype(str):
        status_path = root / f"manifests/origin_{origin_week}.json"
        fit_path = root / f"fits/origin_{origin_week}.json"
        prediction_path = root / f"predictions/origin_{origin_week}.parquet"
        require(status_path.exists() and fit_path.exists() and prediction_path.exists(), f"missing Q1 origin output for {origin_week}")
        status = json.loads(status_path.read_text(encoding="utf-8"))
        require(status.get("status") == "COMPLETED" and status.get("candidate_model_sha256") == CANDIDATE_MODEL_SHA256, f"origin did not complete under the expected candidate: {origin_week}")
        require(status.get("fit_artifact_sha256") == sha256_file(fit_path), f"fit checksum mismatch for {origin_week}")
        require(status.get("prediction_artifact_sha256") == sha256_file(prediction_path), f"prediction checksum mismatch for {origin_week}")
        statuses.append(status)
        frames.append(pd.read_parquet(prediction_path))
    predictions = pd.concat(frames, ignore_index=True)
    expected_rows = 26 * 3 * p2.NODE_COUNT * len(PROXIES)
    require(len(predictions) == expected_rows, f"prediction archive row count changed: {len(predictions)} != {expected_rows}")
    require(not predictions.duplicated([*KEY_COLUMNS, "proxy_id"]).any(), "archive contains duplicate proxy prediction keys")
    require(set(predictions["proxy_id"].unique()) == set(PROXIES), "archive proxy set changed")
    require(np.isfinite(predictions[["p_occurrence", "conditional_count_mean", "underlying_mu", "expected_count"]].to_numpy(np.float64)).all(), "archive contains nonfinite predictions")
    require(predictions["p_occurrence"].between(0, 1).all(), "archive occurrence probabilities are out of range")
    require((predictions[["conditional_count_mean", "underlying_mu", "expected_count"]] >= 0).all().all(), "archive contains negative count predictions")
    predictions = predictions.sort_values(["proxy_id", *KEY_COLUMNS], kind="mergesort").reset_index(drop=True)
    archive_path = root / "predictions/rolling_origin_predictions.parquet"
    p2.write_parquet(archive_path, predictions)

    fit_status = pd.DataFrame([{"origin_week": s["origin_week"], "status": s["status"], "training_cutoff": s["training_cutoff"], "runtime_seconds": s["runtime_seconds"], "fit_sha256": s["fit_artifact_sha256"], "prediction_sha256": s["prediction_artifact_sha256"]} for s in statuses])
    metric_rows: list[dict[str, Any]] = []
    frontier_rows: list[dict[str, Any]] = []
    calibration_rows: list[dict[str, Any]] = []
    count_calibration_rows: list[dict[str, Any]] = []
    reference_rows: list[pd.DataFrame] = []
    temporal_rows: list[dict[str, Any]] = []
    for proxy_id in PROXIES:
        current = predictions.loc[predictions["proxy_id"].eq(proxy_id)].copy()
        summaries = p2.aggregate_metrics(current, fit_status)
        for row in summaries["horizon"].to_dict(orient="records"):
            row.update({"proxy_id": proxy_id, "scoring_eligibility": "NOT_CERTIFIED_TARGET_MATURITY"})
            metric_rows.append(row)
        for row in summaries["frontier"].to_dict(orient="records"):
            row.update({"proxy_id": proxy_id, "scoring_eligibility": "NOT_CERTIFIED_TARGET_MATURITY"})
            frontier_rows.append(row)
        for horizon in ["all", *HORIZONS]:
            calibration_rows.extend([{**row, "proxy_id": proxy_id, "scoring_eligibility": "NOT_CERTIFIED_TARGET_MATURITY"} for row in p2.calibration_bins(current, str(horizon))])
            count_calibration_rows.extend([{**row, "proxy_id": proxy_id, "scoring_eligibility": "NOT_CERTIFIED_TARGET_MATURITY"} for row in p2.count_calibration_bins(current, str(horizon))])
        refs = p2.reference_metrics(current)
        refs["proxy_id"] = proxy_id
        refs["scoring_eligibility"] = "NOT_CERTIFIED_TARGET_MATURITY"
        reference_rows.append(refs)
        for (origin_week, horizon), block in current.groupby(["origin_week", "horizon"], sort=True):
            temporal_rows.append({**p2.metric_rows_for_group(block, {"scope": "origin_horizon", "origin_week": origin_week, "horizon": int(horizon)}), "proxy_id": proxy_id, "scoring_eligibility": "NOT_CERTIFIED_TARGET_MATURITY"})
    metric_frame = pd.DataFrame(metric_rows)
    frontier_frame = pd.DataFrame(frontier_rows)
    geographic_frontier = pd.concat([
        geographic_frontier_metrics(predictions.loc[predictions["proxy_id"].eq(proxy_id)]).assign(proxy_id=proxy_id)
        for proxy_id in PROXIES
    ], ignore_index=True)
    p2.write_csv(output_results / "origin_horizon_performance.csv", pd.DataFrame(temporal_rows))
    p2.write_csv(output_results / "horizon_region_performance.csv", metric_frame)
    p2.write_csv(output_results / "frontier_performance.csv", frontier_frame)
    p2.write_csv(output_results / "geographic_frontier_performance.csv", geographic_frontier)
    p2.write_csv(output_results / "occurrence_calibration_bins.csv", pd.DataFrame(calibration_rows))
    p2.write_csv(output_results / "count_calibration_bins.csv", pd.DataFrame(count_calibration_rows))
    p2.write_csv(output_results / "reference_comparison.csv", pd.concat(reference_rows, ignore_index=True))

    bootstrap_rows = []
    primary = predictions.loc[predictions["proxy_id"].eq(PRIMARY_PROXY)].copy()
    for offset, horizon in enumerate(["all", *HORIZONS]):
        bootstrap_rows.extend(p2.bootstrap_metric_rows(primary, "all", horizon, 399, 20261029 + offset))
    p2.write_csv(output_results / "primary_target_week_bootstrap.csv", pd.DataFrame(bootstrap_rows))
    sensitivity_rows = []
    for proxy_id in ["E0_LAST_AVAILABLE", "E1_TRAILING3_MEAN"]:
        for horizon in HORIZONS:
            sensitivity_rows.extend(paired_bootstrap_differences(predictions, proxy_id, "REALIZED_ENV", horizon, 199, 20261029 + horizon, False))
            sensitivity_rows.extend(paired_bootstrap_differences(predictions, proxy_id, "REALIZED_ENV", horizon, 199, 20261039 + horizon, True))
    p2.write_csv(output_results / "environment_proxy_paired_sensitivity.csv", pd.DataFrame(sensitivity_rows))
    p2.write_csv(output_results / "environment_proxy_threshold_comparison.csv", proxy_threshold_comparison(predictions))

    edges = pd.read_parquet(args.candidate_root / "revised_model_data/raw/edges_queen.parquet")
    spatial = residual_spatial_summary(predictions, edges)
    p2.write_csv(output_results / "residual_spatial_diagnostics.csv", spatial)
    p2.write_csv(output_results / "fit_status_manifest.csv", fit_status)
    p2.write_csv(output_results / "scoring_eligibility.csv", pd.DataFrame([{
        "target_week": week,
        "forecast_rows_present": True,
        "source_week_present": True,
        "authoritative_reporting_maturity_evidence": "NOT_AVAILABLE",
        "primary_qualification_scoring": "NOT_ELIGIBLE_UNCERTIFIED_MATURITY",
        "descriptive_revised_vintage_metrics": "RETAINED",
    } for week in sorted(predictions["target_week"].astype(str).unique(), key=p2.parse_week)]))

    archive_manifest = {
        "candidate_id": CANDIDATE_ID,
        "candidate_model_sha256": CANDIDATE_MODEL_SHA256,
        "input_manifest_sha256": sha256_file(root / "manifests/input_manifest.json"),
        "repository_sha": git_value(args.repository_root, "rev-parse", "HEAD"),
        "origin_count": len(statuses),
        "origin_horizon_blocks": 78,
        "fit_count": len(statuses),
        "horizons": list(HORIZONS),
        "proxy_ids": list(PROXIES),
        "primary_proxy": PRIMARY_PROXY,
        "prediction_rows": len(predictions),
        "rows_per_proxy": {proxy: int(predictions["proxy_id"].eq(proxy).sum()) for proxy in PROXIES},
        "prediction_keys_unique": True,
        "archive": {"path": str(archive_path), "sha256": sha256_file(archive_path), "size_bytes": archive_path.stat().st_size, "rows": len(predictions), "columns": list(predictions.columns)},
        "fit_artifacts": [{"origin_week": s["origin_week"], "sha256": s["fit_artifact_sha256"]} for s in statuses],
        "historical_information_classification": "RETROSPECTIVE_UPDATED_VINTAGE_HINDCAST; source publication and environmental release timestamps unavailable",
        "target_maturity_decision": "NOT_CERTIFIED; primary qualification scores are not assigned",
        "candidate_and_production_isolation": "W44 full-fit, W16/W29 artifacts and production configuration were read-only",
        "aggregate_results_path": str(output_results),
    }
    write_json(root / "manifests/prediction_archive_manifest.json", archive_manifest)
    write_json(output_results / "qualification_decision.json", {
        "candidate_id": CANDIDATE_ID,
        "q1_execution_status": "COMPLETED",
        "fit_and_prediction_construction": "VALIDATED_RETROSPECTIVE_ORIGIN_SPECIFIC",
        "primary_proxy": PRIMARY_PROXY,
        "sensitivity_proxy": "E1_TRAILING3_MEAN",
        "predictive_scoring_eligibility": "LIMITED_NOT_CERTIFIED_TARGET_MATURITY",
        "scientific_qualification_decision": "NOT_ASSIGNED",
        "reason": "The authoritative observation snapshot has no certified reporting-completeness or target-maturity evidence for the Q1 target weeks. Descriptive revised-vintage metrics are retained and are not treated as qualification scores.",
        "candidate_status": "CANDIDATE_READY_FOR_REVIEW_NOT_PRODUCTION_QUALIFIED",
        "no_new_thresholds": True,
    })
    report = render_report(manifest, archive_manifest, metric_frame, frontier_frame, spatial, statuses, output_results, time.time() - started)
    (output_results / "q1_retrospective_qualification_report.md").write_text(report, encoding="utf-8")
    write_json(root / "manifests/aggregate_status.json", {
        "status": "COMPLETED",
        "runtime_seconds": time.time() - started,
        "origin_count": len(statuses),
        "origin_horizon_blocks": 78,
        "prediction_rows": len(predictions),
        "prediction_archive_sha256": archive_manifest["archive"]["sha256"],
        "aggregate_results_path": str(output_results),
        "target_maturity_decision": "NOT_CERTIFIED",
    })
    require(sha256_file(args.candidate_root / "fullfit_products/model/fullfit_a3_model.json") == CANDIDATE_MODEL_SHA256, "W44 candidate model changed during aggregation")
    print(json.dumps({"status": "AGGREGATED", "origins": len(statuses), "blocks": 78, "prediction_rows": len(predictions), "archive_sha256": archive_manifest["archive"]["sha256"], "results": str(output_results)}, indent=2))


def render_report(input_manifest: dict[str, Any], archive_manifest: dict[str, Any], metrics: pd.DataFrame, frontier: pd.DataFrame, spatial: pd.DataFrame, statuses: list[dict[str, Any]], results: Path, runtime: float) -> str:
    main = metrics.loc[(metrics["proxy_id"] == PRIMARY_PROXY) & (metrics["scope"] == "all") & (metrics["horizon"].isin([1, 2, 3]))]
    lines = [
        "# STRUCTURED_A3 W44 Q1 retrospective qualification",
        "",
        "**Execution:** `COMPLETED`; **scientific decision:** `NOT_ASSIGNED` because outcome maturity is uncertified.",
        "**Candidate status:** `CANDIDATE_READY_FOR_REVIEW_NOT_PRODUCTION_QUALIFIED`.",
        "",
        "## Identity and execution",
        "",
        f"- Candidate model SHA-256: `{CANDIDATE_MODEL_SHA256}`.",
        f"- Observation source SHA-256: `{OBSERVATION_SHA256}`.",
        f"- Origins: {archive_manifest['origin_count']} (2026-W16 through 2026-W41); origin-horizon blocks: {archive_manifest['origin_horizon_blocks']}; fitted origin states: {archive_manifest['fit_count']}.",
        f"- Prediction archive rows: {archive_manifest['prediction_rows']}; SHA-256: `{archive_manifest['archive']['sha256']}`.",
        f"- Atlas output root: `{archive_manifest['archive']['path']}`.",
        f"- Aggregate analysis runtime: {runtime:.1f} seconds. Origin task runtimes are recorded in `fit_status_manifest.csv`.",
        "- Frozen 34-predictor A3 specification, penalty, theta, and hurdle objective were retained. The full W44 candidate was not used to predict targets included in its fit; each origin has an expanding-window state ending at that origin.",
        "",
        "## Information boundaries",
        "",
        "This is a retrospective updated-vintage hindcast. Historical observation publication/revision times and environmental release timestamps were unavailable. E0 and E1 use the approved observation-week cutoff of T-1, but cannot establish that the underlying environmental files were actually published by each historical issue time.",
        "Detection-history predictors are sourced from the first target week T+1, whose audited history cutoff is no later than T, and are held fixed across horizons 1–3. No post-origin history enters h=2 or h=3. The three environmental conditions are REALIZED_ENV (descriptive retrospective reference), E0_LAST_AVAILABLE (primary), and E1_TRAILING3_MEAN (sensitivity).",
        "",
        "## Outcome maturity and scoring status",
        "",
        "The response bundle contains every target week needed for the replay, but the source snapshot does not certify reporting completeness or outcome maturity. Therefore all predictive metrics below are descriptive revised-vintage diagnostics. No primary qualification scoring decision or production designation is assigned. Target-week eligibility is itemized in `scoring_eligibility.csv`.",
        "",
        "## Primary E0 descriptive performance",
        "",
        "| Horizon | Rows | Positives | Brier | Log loss | ROC-AUC | PR-AUC | Calibration intercept | Calibration slope | Conditional count MAE | Full expected count MAE |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for _, row in main.sort_values("horizon").iterrows():
        def fmt(value: Any) -> str:
            return "NA" if value is None or not np.isfinite(value) else f"{float(value):.4f}"
        lines.append("| " + " | ".join([str(row["horizon"]), str(int(row["n"])), str(int(row["positives"])), fmt(row["brier"]), fmt(row["log_loss"]), fmt(row["auroc"]), fmt(row["auprc"]), fmt(row["calibration_intercept"]), fmt(row["calibration_slope"]), fmt(row["conditional_mae"]), fmt(row["full_expected_mae"])]) + " |")
    lines.extend([
        "",
        "E1, REALIZED_ENV, region-specific results, existing-region × origin-time frontier strata, calibration bins, reference comparisons, target-week bootstrap intervals, paired proxy contrasts, P5A strict/bounded descriptive comparisons, and residual spatial summaries are in the adjacent aggregate CSV/JSON outputs. Interpret all metric estimates as descriptive until maturity is established. Geographic strata use unchanged canonical country/domain region labels; no additional northern Mexico–Texas boundary is introduced.",
        "",
        "## Spatial residual diagnostics",
        "",
        "Residuals were evaluated on the W44 Queen graph using the established Moran-I implementation. Target-week/horizon statistics are descriptive; pooled-by-horizon permutation checks use 199 permutations with seed 20261017. These are rolling-origin diagnostics and are not a spatial holdout or the fixed-W44 P1 post-freeze test.",
        "",
        "## Limitations and decision",
        "",
        "The Q1 origin-specific fits and forecasts completed with the approved origin/target design and no detected future-history use. The retrospective source vintage, unavailable release timestamps, and uncertified target maturity limit the scientific conclusion. Because mature outcome scoring eligibility cannot be established, Q1 predictive qualification is not assigned. The W44 full-fit candidate was not refitted; no production configuration change, promotion, Q2 uncertainty/support execution, or Q3 prospective execution occurred.",
        "",
        f"All row-level predictions, fitted origin states, logs, and coordinate-bearing diagnostics remain on Atlas. Aggregate report path: `{results}`.",
    ])
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["prepare", "origin", "aggregate"], required=True)
    parser.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--observation-source", type=Path, required=True)
    parser.add_argument("--front-features", type=Path, default=None)
    parser.add_argument("--origin-slot", type=int, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.repository_root = args.repository_root.resolve()
    args.candidate_root = args.candidate_root.resolve()
    args.output_root = args.output_root.resolve()
    args.front_features = args.front_features or args.candidate_root / "front_features/causal_front_features.parquet"
    args.front_features = Path(args.front_features).resolve()
    args.observation_source = args.observation_source.resolve()
    if args.mode == "prepare":
        prepare(args)
    elif args.mode == "origin":
        require(args.origin_slot is not None, "--origin-slot is required for origin mode")
        origin(args)
    else:
        aggregate(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
