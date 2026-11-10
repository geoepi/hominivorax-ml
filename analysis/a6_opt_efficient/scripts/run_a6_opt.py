"""Run the bounded, two-stage A6-OPT GPBoost challenger."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import inspect
import json
import math
import os
import platform
import shutil
import subprocess
import sys
import time
import traceback
import warnings
from contextlib import contextmanager, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

try:
    import resource
except ImportError:  # pragma: no cover - Windows-only import guard for local contract checks
    resource = None


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
A6_DIR = REPOSITORY_ROOT / "analysis/a6_gpboost_correlated_spatial_ml/scripts"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load module {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


A6 = load_module(A6_DIR / "run_a6.py", "a6_opt_original_helpers")
A5 = A6.A5
PARAMETER_NAMES = ["GP_var", "GP_range_time", "GP_range_space"]
PARENT_A6_SHA = "e734427b29111917261861a67aafa2379a5bfc07"
OPT_CANDIDATE = "A6-OPT"


class A6OptBlocked(RuntimeError):
    """Raised when the requested two-stage GPBoost contract cannot be honored."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def write_csv_atomic(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    frame.to_csv(temporary, index=False)
    os.replace(temporary, path)


def write_npz_atomic(path: Path, arrays: dict[str, np.ndarray]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp.npz")
    np.savez_compressed(temporary, **arrays)
    with np.load(temporary, allow_pickle=False) as check:
        if set(check.files) != set(arrays):
            raise RuntimeError(f"prediction archive validation failed for {path}")
    os.replace(temporary, path)


def read_config(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    opt = json.loads(path.read_text(encoding="utf-8"))
    if opt.get("analysis") != "a6_opt_efficient" or opt.get("parent_a6_commit") != PARENT_A6_SHA:
        raise RuntimeError("A6-OPT parent or analysis identifier changed")
    base_path = (path.parent / opt["base_config"]).resolve()
    base = json.loads(base_path.read_text(encoding="utf-8"))
    if base.get("analysis") != "a6_gpboost_correlated_spatial_ml":
        raise RuntimeError("the original A6 configuration is not the declared base")
    if base["gpboost"]["num_neighbors"] != 20 or base["gpboost"]["num_neighbors_pred"] != 40:
        raise RuntimeError("the frozen original A6 Vecchia specification changed")
    config = copy.deepcopy(base)
    config["analysis"] = "a6_opt_efficient"
    config["gpboost"].update(opt["gpboost_overrides"])
    if config["gpboost"]["num_neighbors"] != 8 or config["gpboost"]["num_neighbors_pred"] != 40:
        raise RuntimeError("A6-OPT training/prediction neighbor contract failed")
    if config["gpboost"]["cov_fct_shape"] != 1.5 or config["gpboost"]["likelihood"] != "bernoulli_logit":
        raise RuntimeError("A6-OPT Matérn or likelihood contract changed")
    if config["predictors"]["count"] != 34 or config["predictors"]["coordinates_are_tree_features"]:
        raise RuntimeError("A6-OPT predictor contract changed")
    if config["development_period"]["folds"] != base["development_period"]["folds"] or config["seeds"] != [1729, 31415, 271828]:
        raise RuntimeError("A6-OPT temporal folds or seeds changed")
    if opt["covariance_estimation"]["parameter_names"] != PARAMETER_NAMES:
        raise RuntimeError("A6-OPT named covariance parameter order changed")
    config["a6_opt"] = opt
    config["a6_opt_provenance"] = {
        "opt_config_path": str(path.resolve()),
        "opt_config_sha256": sha256_file(path),
        "base_config_path": str(base_path),
        "base_config_sha256": sha256_file(base_path),
    }
    return config, opt


def resolve_output_root(explicit: Path | None) -> Path:
    value = explicit or (Path(os.environ["A6_OPT_OUTPUT_ROOT"]) if os.environ.get("A6_OPT_OUTPUT_ROOT") else None)
    if value is None:
        raise RuntimeError("A6_OPT_OUTPUT_ROOT or --output-root is required")
    root = value.expanduser().resolve()
    if "/90daydata/" not in str(root).replace("\\", "/"):
        raise RuntimeError(f"A6-OPT large outputs must be under /90daydata/disease_ecology: {root}")
    return root


def runtime_snapshot() -> dict[str, float]:
    if resource is None:
        return {"cpu_seconds": 0.0, "peak_rss_bytes": 0.0}
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return {
        "cpu_seconds": float(usage.ru_utime + usage.ru_stime),
        "peak_rss_bytes": float(usage.ru_maxrss * 1024),
    }


@contextmanager
def fold_lock(path: Path):
    """Use an OS lock, released automatically if a Slurm process is interrupted."""
    import fcntl

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(f"identical fold task already holds {path}") from exc
        yield


def load_data(args: argparse.Namespace) -> Any:
    data_args = argparse.Namespace(
        config=args.config,
        model_output=args.model_output,
        front_features=args.front_features,
        anthropogenic_features=args.anthropogenic_features,
        soil_features=args.soil_features,
        edges=args.edges,
        a3_reference=args.a3_reference,
        a3_frozen_output=args.a3_frozen_output,
        spatial_assignments=args.spatial_assignments,
    )
    return A6.load_data(data_args)


def source_checksums(config_path: Path) -> dict[str, str]:
    paths = {
        "a6_opt_runner": Path(__file__).resolve(),
        "original_a6_runner": Path(A6.__file__).resolve(),
        "a5_runner": Path(A5.__file__).resolve(),
        "a5b_runner": Path(A6.A5B.__file__).resolve(),
        "a5_augmentation": Path(A5.AUG.__file__).resolve(),
        "a4_reference_helpers": Path(A5.A4.__file__).resolve(),
        "a5_model": (REPOSITORY_ROOT / "analysis/a5_gnn_bounded_comparison/scripts/a5_model.py").resolve(),
        "task2c_metrics": (REPOSITORY_ROOT / "python/task2c_metrics.py").resolve(),
        "a6_opt_config": config_path.resolve(),
        "a6_base_config": (config_path.parent / json.loads(config_path.read_text(encoding="utf-8"))["base_config"]).resolve(),
    }
    result = {}
    for name, path in paths.items():
        if not path.exists():
            raise RuntimeError(f"required implementation provenance source is missing: {path}")
        result[name] = sha256_file(path)
    return result


def load_gpboost():
    try:
        import gpboost as gpb
    except Exception as exc:  # environment-dependent
        raise A6OptBlocked(f"A6_OPT_SOFTWARE_BLOCKED: GPBoost import failed: {exc}") from exc
    if getattr(gpb, "__version__", None) != "1.8.0":
        raise A6OptBlocked(f"A6_OPT_SOFTWARE_BLOCKED: expected GPBoost 1.8.0, got {getattr(gpb, '__version__', None)}")
    return gpb


def audit_gpboost_api(gpb: Any, output: Path) -> dict[str, Any]:
    fit_sig = inspect.signature(gpb.GPModel.fit)
    optim_sig = inspect.signature(gpb.GPModel.set_optim_params)
    train_sig = inspect.signature(gpb.train)
    pred_sig = inspect.signature(gpb.GPModel.set_prediction_data)
    required = {
        "GPModel.fit_offset": "offset" in fit_sig.parameters,
        "GPModel.set_optim_params": "params" in optim_sig.parameters,
        "train_fixed_covariance": "train_gp_model_cov_pars" in train_sig.parameters,
        "prediction_neighbor_setting": "num_neighbors_pred" in pred_sig.parameters,
        "GPModel_fit_init_cov_pars_documented": "init_cov_pars" in (inspect.getdoc(gpb.GPModel.set_optim_params) or ""),
        "train_fixed_covariance_documented": "provide values via the 'init_cov_pars'" in (inspect.getdoc(gpb.train) or ""),
        "GPModel_fit_forwards_offset": "offset_c" in inspect.getsource(gpb.GPModel.fit) and "GPB_OptimCovPar" in inspect.getsource(gpb.GPModel.fit),
    }
    if not all(required.values()):
        raise A6OptBlocked(f"installed GPBoost 1.8.0 does not satisfy the A6-OPT API contract: {required}")
    payload = {
        "status": "PASSED",
        "gpboost_version": gpb.__version__,
        "gpboost_path": str(Path(gpb.__file__).resolve()),
        "api_signatures": {
            "GPModel.fit": str(fit_sig),
            "GPModel.set_optim_params": str(optim_sig),
            "GPModel.set_prediction_data": str(pred_sig),
            "gpb.train": str(train_sig),
        },
        "api_contract": required,
        "verified_model_contract": {
            "bernoulli_logit": True,
            "matern_space_time": True,
            "vecchia": True,
            "fit_offset_on_linear_predictor": True,
            "fixed_covariance_train_flag": True,
            "init_cov_pars_via_set_optim_params": True,
            "explicit_prediction_neighbors": 40,
        },
    }
    path = output / "provenance/gpboost_api_audit.json"
    if path.exists():
        old = json.loads(path.read_text(encoding="utf-8"))
        if old != payload:
            raise RuntimeError(f"refusing to overwrite changed GPBoost API audit: {path}")
    else:
        write_json_atomic(path, payload)
    return payload


def select_spatial_sites(coords_xy: np.ndarray, eligible_nodes: np.ndarray, sample_size: int, bins_per_axis: int, seed: int) -> tuple[np.ndarray, dict[str, Any]]:
    """Choose outcome-blind sites round-robin over fixed spatial tiles."""
    eligible = np.asarray(eligible_nodes, dtype=np.int64)
    coords = np.asarray(coords_xy, dtype=np.float64)
    if len(eligible) == 0 or len(np.unique(eligible)) != len(eligible):
        raise RuntimeError("covariance subset requires unique eligible spatial nodes")
    sample_size = min(int(sample_size), len(eligible))
    values = coords[eligible]
    x_edges = np.linspace(float(values[:, 0].min()), float(values[:, 0].max()) + 1e-12, bins_per_axis + 1)
    y_edges = np.linspace(float(values[:, 1].min()), float(values[:, 1].max()) + 1e-12, bins_per_axis + 1)
    bx = np.clip(np.searchsorted(x_edges, values[:, 0], side="right") - 1, 0, bins_per_axis - 1)
    by = np.clip(np.searchsorted(y_edges, values[:, 1], side="right") - 1, 0, bins_per_axis - 1)
    tile = bx * bins_per_axis + by
    rng = np.random.default_rng(seed)
    priority = rng.random(len(eligible))
    grouped: list[np.ndarray] = []
    for tile_id in range(bins_per_axis * bins_per_axis):
        local = np.flatnonzero(tile == tile_id)
        if len(local):
            grouped.append(eligible[local[np.argsort(priority[local], kind="stable")]])
    edge_nodes = {
        int(eligible[int(np.argmin(values[:, 0]))]),
        int(eligible[int(np.argmax(values[:, 0]))]),
        int(eligible[int(np.argmin(values[:, 1]))]),
        int(eligible[int(np.argmax(values[:, 1]))]),
    }
    chosen = list(sorted(edge_nodes))
    chosen_set = set(chosen)
    for depth in range(max((len(group) for group in grouped), default=0)):
        for group in grouped:
            if depth >= len(group):
                continue
            node = int(group[depth])
            if node not in chosen_set:
                chosen.append(node)
                chosen_set.add(node)
                if len(chosen) == sample_size:
                    break
        if len(chosen) == sample_size:
            break
    if len(chosen) != sample_size:
        raise RuntimeError(f"deterministic spatial subset selected {len(chosen)} sites, expected {sample_size}")
    sample = np.asarray(chosen, dtype=np.int64)
    full_nn = cKDTree(values).query(values, k=2)[0][:, 1]
    sample_nn = cKDTree(coords[sample]).query(coords[sample], k=2)[0][:, 1]

    def quantiles(arr: np.ndarray) -> dict[str, float]:
        return {f"p{q}": float(np.quantile(arr, q / 100)) for q in (10, 50, 90)}

    summary = {
        "method": "deterministic_spatial_stratification_all_training_weeks",
        "uses_outcomes_for_site_selection": False,
        "seed": int(seed),
        "grid_bins_per_axis": int(bins_per_axis),
        "full_eligible_sites": int(len(eligible)),
        "sampled_sites": int(len(sample)),
        "sampling_fraction": float(len(sample) / len(eligible)),
        "occupied_spatial_tiles": int(len(grouped)),
        "full_domain_extent_xy": {"min": values.min(axis=0).tolist(), "max": values.max(axis=0).tolist()},
        "sample_extent_xy": {"min": coords[sample].min(axis=0).tolist(), "max": coords[sample].max(axis=0).tolist()},
        "nearest_neighbor_distance_km": {"full_domain": quantiles(full_nn), "sample": quantiles(sample_nn)},
        "sample_node_ids": sample.tolist(),
    }
    return sample, summary


def flatten_training(fold: Any, times: np.ndarray, node_ids: np.ndarray, coords_xy: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    times = np.asarray(times, dtype=np.int64)
    node_ids = np.asarray(node_ids, dtype=np.int64)
    x = fold.x[times[:, None], node_ids, :].reshape(-1, 34).astype(np.float64)
    y_count = fold.counts[times[:, None], node_ids].reshape(-1).astype(np.int64)
    y = (y_count > 0).astype(np.int64)
    offset = fold.eta[times[:, None], node_ids].reshape(-1).astype(np.float64)
    coords = A6.build_coords(coords_xy, times, node_ids, space_time=True)
    if x.shape[1] != 34 or coords.shape != (len(y), 3) or len(offset) != len(y):
        raise RuntimeError("training feature, offset, and space-time coordinate rows are not aligned")
    if not np.array_equal(coords[:, 0].astype(np.int64), np.repeat(times, len(node_ids))):
        raise RuntimeError("space-time coordinate first column is not the weekly index")
    return x, y, y_count, offset, coords


def make_gp_model(gpb: Any, coords: np.ndarray, seed: int, config: dict[str, Any], threads: int) -> Any:
    gp = config["gpboost"]
    model = gpb.GPModel(
        likelihood=gp["likelihood"],
        gp_coords=coords,
        cov_function=gp["spatiotemporal_cov_function"],
        cov_fct_shape=gp["cov_fct_shape"],
        gp_approx=gp["gp_approx"],
        num_parallel_threads=threads,
        num_neighbors=gp["num_neighbors"],
        vecchia_ordering=gp["vecchia_ordering_spatiotemporal"],
        vecchia_pred_type=gp["vecchia_pred_type"],
        num_neighbors_pred=gp["num_neighbors_pred"],
        seed=int(seed),
    )
    return model


def covariance_table(gp: Any) -> tuple[dict[str, float], list[dict[str, Any]]]:
    table = gp.get_cov_pars(format_pandas=True)
    if not isinstance(table, pd.DataFrame) or len(table) != 1:
        raise A6OptBlocked("GPBoost did not return one named space-time covariance parameter row")
    missing = set(PARAMETER_NAMES) - set(table.columns)
    if missing:
        raise A6OptBlocked(f"GPBoost covariance table is missing named parameters: {sorted(missing)}")
    values = {name: float(table.iloc[0][name]) for name in PARAMETER_NAMES}
    rows = table.to_dict(orient="records")
    return values, rows


def validate_covariance(values: dict[str, float], maxit: int | None = None, iterations: int | None = None) -> dict[str, Any]:
    positive = all(math.isfinite(values[name]) and values[name] > 0 for name in PARAMETER_NAMES)
    nondegenerate = bool(positive and values["GP_var"] > 1e-8 and all(1e-8 < values[name] < 1e8 for name in PARAMETER_NAMES[1:]))
    convergence = bool(iterations is not None and iterations > 0 and (maxit is None or iterations < maxit))
    return {
        "finite_positive": bool(positive),
        "non_degenerate": bool(nondegenerate),
        "optimizer_iterations": int(iterations) if iterations is not None else None,
        "optimizer_maxit": int(maxit) if maxit is not None else None,
        "convergence_diagnostic": "optimizer_returned_before_maxit" if convergence else "no_confirmed_convergence_before_maxit",
        "converged": convergence,
    }


def covariance_fingerprint(
    stage: str,
    fold_id: int,
    train_times: np.ndarray,
    eligible_nodes: np.ndarray,
    sample_nodes: np.ndarray,
    data: Any,
    config: dict[str, Any],
) -> dict[str, Any]:
    return {
        "stage": stage,
        "fold": int(fold_id),
        "training_week_indices": np.asarray(train_times, dtype=np.int64).tolist(),
        "training_node_ids_sha256": sha256_json(np.asarray(eligible_nodes, dtype=np.int64).tolist()),
        "sample_node_ids_sha256": sha256_json(np.asarray(sample_nodes, dtype=np.int64).tolist()),
        "input_sha256": dict(data.hashes),
        "config_sha256": sha256_json(config["a6_opt_provenance"]),
        "source_sha256": config["a6_opt_provenance"]["source_sha256"],
        "gpboost_version": "1.8.0",
    }


def load_completed_covariance(stage_dir: Path, fingerprint: dict[str, Any]) -> dict[str, Any] | None:
    if not stage_dir.exists():
        return None
    for attempt_dir in sorted(stage_dir.glob("attempt_*")):
        marker = attempt_dir / "completion.json"
        estimate = attempt_dir / "stage_a_estimate.json"
        if not marker.exists():
            continue
        payload = json.loads(marker.read_text(encoding="utf-8"))
        if payload.get("status") != "COMPLETED":
            continue
        if not estimate.exists() or sha256_file(estimate) != payload.get("estimate_sha256"):
            raise RuntimeError(f"completed Stage A covariance artifact checksum failed: {estimate}")
        if payload.get("fingerprint") == fingerprint:
            result = json.loads(estimate.read_text(encoding="utf-8"))
            result["attempt_directory"] = str(attempt_dir)
            result["estimate_sha256"] = payload["estimate_sha256"]
            result["reused"] = True
            return result
    return None


def next_attempt_dir(stage_dir: Path) -> Path:
    stage_dir.mkdir(parents=True, exist_ok=True)
    numbers = [int(path.name.split("_")[-1]) for path in stage_dir.glob("attempt_*") if path.name.split("_")[-1].isdigit()]
    attempt = max(numbers, default=0) + 1
    path = stage_dir / f"attempt_{attempt:03d}"
    path.mkdir(exist_ok=False)
    return path


def estimate_covariance(
    gpb: Any,
    fold: Any,
    train_times: np.ndarray,
    eligible_nodes: np.ndarray,
    coords_xy: np.ndarray,
    fold_root: Path,
    data: Any,
    config: dict[str, Any],
    fold_id: int,
    stage_name: str,
    threads: int,
) -> dict[str, Any]:
    opt = config["a6_opt"]["covariance_estimation"]
    sample_nodes, sample_summary = select_spatial_sites(
        coords_xy,
        eligible_nodes,
        opt["sample_nodes"],
        opt["spatial_grid_bins_per_axis"],
        int(opt["sampling_seed"]),
    )
    fingerprint = covariance_fingerprint(stage_name, fold_id, train_times, eligible_nodes, sample_nodes, data, config)
    stage_dir = fold_root / "covariance" / stage_name
    reused = load_completed_covariance(stage_dir, fingerprint)
    if reused is not None:
        reused["reused"] = True
        return reused

    x, y, _, offset, coords = flatten_training(fold, train_times, sample_nodes, coords_xy)
    week_class_counts = []
    n_sites = len(sample_nodes)
    for index, week in enumerate(np.asarray(train_times, dtype=np.int64)):
        start = index * n_sites
        stop = start + n_sites
        week_class_counts.append({"week_index": int(week), "positive": int(y[start:stop].sum()), "negative": int(len(y[start:stop]) - y[start:stop].sum())})
    if np.unique(y).size < 2:
        raise A6OptBlocked(f"Stage A {stage_name} subset lacks occurrence-class variation")
    if any(row["positive"] + row["negative"] != n_sites for row in week_class_counts):
        raise RuntimeError("Stage A per-week subset row accounting failed")
    initial = opt["initial_covariance_parameters"]
    if list(initial) != PARAMETER_NAMES:
        initial = {name: float(initial[name]) for name in PARAMETER_NAMES}
    init_frame = pd.DataFrame([{name: float(initial[name]) for name in PARAMETER_NAMES}], columns=PARAMETER_NAMES)
    seed = int(opt["sampling_seed"]) + int(fold_id)
    gp = make_gp_model(gpb, coords, seed, config, threads)
    params = {
        "init_cov_pars": init_frame,
        "optimizer_cov": opt["optimizer_cov"],
        "maxit": int(opt["maxit"]),
        "delta_rel_conv": float(opt["delta_rel_conv"]),
        "trace": bool(opt["trace"]),
    }
    attempt_dir = next_attempt_dir(stage_dir)
    write_json_atomic(attempt_dir / "status.json", {"status": "RUNNING", "stage": stage_name, "started_utc": utc_now(), "fingerprint": fingerprint})
    before = runtime_snapshot()
    started = time.perf_counter()
    caught: list[str] = []
    try:
        with warnings.catch_warnings(record=True) as warning_records:
            warnings.simplefilter("always")
            gp.fit(y=y.astype(np.float64), offset=offset.astype(np.float64), params=params)
            caught = [str(item.message) for item in warning_records]
        elapsed = time.perf_counter() - started
        after = runtime_snapshot()
        covariance, table = covariance_table(gp)
        iterations = int(gp._get_num_optim_iter())
        diagnostics = validate_covariance(covariance, int(opt["maxit"]), iterations)
        if not diagnostics["finite_positive"] or not diagnostics["non_degenerate"] or not diagnostics["converged"]:
            raise A6OptBlocked(f"Stage A covariance validation failed: {diagnostics}; parameters={covariance}")
        estimate = {
            "status": "COMPLETED",
            "stage": stage_name,
            "fold": int(fold_id),
            "covariance_parameters": covariance,
            "covariance_parameter_table": table,
            "covariance_diagnostics": diagnostics,
            "observations_used": int(len(y)),
            "full_partition_observations": int(len(train_times) * len(eligible_nodes)),
            "training_weeks": np.asarray(train_times, dtype=np.int64).tolist(),
            "training_week_extent": [int(np.min(train_times)), int(np.max(train_times))],
            "temporal_separation_coverage_weeks": {
                "adjacent_week_gap_min": int(np.diff(np.asarray(train_times, dtype=np.int64)).min()) if len(train_times) > 1 else None,
                "adjacent_week_gap_median": float(np.median(np.diff(np.asarray(train_times, dtype=np.int64)))) if len(train_times) > 1 else None,
                "adjacent_week_gap_max": int(np.diff(np.asarray(train_times, dtype=np.int64)).max()) if len(train_times) > 1 else None,
                "available_pairwise_lag_weeks": sorted(set(int(abs(left - right)) for index, left in enumerate(np.asarray(train_times, dtype=np.int64)) for right in np.asarray(train_times, dtype=np.int64)[index + 1:])),
            },
            "sampled_occurrence_counts": {"positive": int(y.sum()), "negative": int(len(y) - y.sum())},
            "sampled_week_class_counts": week_class_counts,
            "spatial_sampling": sample_summary,
            "optimizer": params | {"init_cov_pars": init_frame.to_dict(orient="records")},
            "runtime": {
                "wall_seconds": float(elapsed),
                "cpu_seconds": max(0.0, after["cpu_seconds"] - before["cpu_seconds"]),
                "peak_rss_bytes_process": after["peak_rss_bytes"],
                "allocated_cpus": int(threads),
            },
            "warnings": caught,
            "input_sha256": dict(data.hashes),
            "config_sha256": sha256_json(config["a6_opt_provenance"]),
            "source_sha256": config["a6_opt_provenance"]["source_sha256"],
            "execution_sha": os.environ.get("STGNN_GIT_SHA", "unknown"),
            "gpboost_version": gpb.__version__,
            "created_utc": utc_now(),
        }
        estimate_path = attempt_dir / "stage_a_estimate.json"
        write_json_atomic(estimate_path, estimate)
        marker = {
            "status": "COMPLETED",
            "stage": stage_name,
            "fingerprint": fingerprint,
            "estimate_path": str(estimate_path),
            "estimate_sha256": sha256_file(estimate_path),
            "completed_utc": utc_now(),
        }
        write_json_atomic(attempt_dir / "completion.json", marker)
        write_json_atomic(attempt_dir / "status.json", marker)
        estimate["attempt_directory"] = str(attempt_dir)
        estimate["estimate_sha256"] = marker["estimate_sha256"]
        estimate["reused"] = False
        return estimate
    except Exception as exc:
        write_json_atomic(attempt_dir / "failure.json", {"status": "FAILED", "stage": stage_name, "error": str(exc), "traceback": traceback.format_exc(), "failed_utc": utc_now(), "fingerprint": fingerprint})
        write_json_atomic(attempt_dir / "status.json", {"status": "FAILED", "stage": stage_name, "error": str(exc), "failed_utc": utc_now(), "fingerprint": fingerprint})
        raise


def thread_count() -> int:
    requested = int(os.environ.get("SLURM_CPUS_PER_TASK", os.cpu_count() or 1))
    return max(1, min(16, requested))


def covariance_frame(values: dict[str, float]) -> pd.DataFrame:
    return pd.DataFrame([{name: float(values[name]) for name in PARAMETER_NAMES}], columns=PARAMETER_NAMES)


def fixed_covariance_train(
    gpb: Any,
    config: dict[str, Any],
    seed: int,
    x_train: np.ndarray,
    y_train: np.ndarray,
    offset_train: np.ndarray,
    coords_train: np.ndarray,
    rounds: int,
    covariance: dict[str, float],
    valid: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray] | None = None,
    early_stopping: bool = False,
) -> tuple[Any, Any, dict[str, Any]]:
    gp = make_gp_model(gpb, coords_train, seed, config, thread_count())
    gp.set_optim_params({"init_cov_pars": covariance_frame(covariance)})
    train_set = A6.make_dataset(gpb, x_train, y_train, offset_train)
    valid_set = None
    if valid is not None:
        x_valid, y_valid, offset_valid, coords_valid = valid
        valid_set = A6.make_dataset(gpb, x_valid, y_valid, offset_valid)
        gp.set_prediction_data(
            vecchia_pred_type=config["gpboost"]["vecchia_pred_type"],
            num_neighbors_pred=int(config["gpboost"]["num_neighbors_pred"]),
            gp_coords_pred=coords_valid,
        )
    params = A6.model_params(config, seed)
    params["num_threads"] = thread_count()
    started = time.perf_counter()
    caught: list[str] = []
    with warnings.catch_warnings(record=True) as warning_records:
        warnings.simplefilter("always")
        booster = gpb.train(
            params=params,
            train_set=train_set,
            num_boost_round=int(rounds),
            gp_model=gp,
            use_gp_model_for_validation=True,
            train_gp_model_cov_pars=False,
            valid_sets=[valid_set] if valid_set is not None else None,
            valid_names=["inner"] if valid_set is not None else None,
            early_stopping_rounds=int(config["boosting"]["early_stopping_rounds"]) if early_stopping else None,
            verbose_eval=False,
            keep_training_booster=True,
        )
        caught = [str(item.message) for item in warning_records]
    elapsed = time.perf_counter() - started
    before_covariance = {name: float(covariance[name]) for name in PARAMETER_NAMES}
    after_covariance, after_table = covariance_table(gp)
    differences = {name: float(after_covariance[name] - before_covariance[name]) for name in PARAMETER_NAMES}
    fixed_ok = bool(all(abs(value) <= 1e-10 for value in differences.values()))
    if not fixed_ok:
        raise A6OptBlocked(f"GPBoost changed covariance parameters with train_gp_model_cov_pars=False: {differences}")
    current_iteration = int(booster.current_iteration())
    best_iteration = int(getattr(booster, "best_iteration", 0) or 0)
    info = {
        "seed": int(seed),
        "requested_rounds": int(rounds),
        "best_iteration": best_iteration,
        "current_iteration": current_iteration,
        "selected_rounds": best_iteration if early_stopping and best_iteration > 0 else current_iteration,
        "runtime_seconds": float(elapsed),
        "train_gp_model_cov_pars": False,
        "use_gp_model_for_validation": True,
        "covariance_parameters_before": before_covariance,
        "covariance_parameters_after": after_covariance,
        "covariance_parameter_table_after": after_table,
        "covariance_parameter_differences": differences,
        "covariance_fixed_verified": fixed_ok,
        "prediction_neighbors_explicit": int(config["gpboost"]["num_neighbors_pred"]),
        "warnings": caught,
        "converged": bool(current_iteration > 0 and fixed_ok),
    }
    if info["selected_rounds"] <= 0:
        info["selected_rounds"] = int(rounds)
    return booster, gp, info


def get_original_a6_row(original_root: Path, candidate: str, fold: int, seed: int) -> tuple[dict[str, Any], dict[str, np.ndarray], dict[str, Any]]:
    metric_path = original_root / "results/fold_seed_metrics.csv"
    prediction_path = original_root / "predictions" / f"{candidate}_fold{fold}_seed{seed}.npz"
    manifest_path = original_root / "manifests" / f"{candidate}_fold{fold}_seed{seed}.json"
    if not metric_path.exists() or not prediction_path.exists() or not manifest_path.exists():
        raise RuntimeError(f"original A6 comparison artifacts are incomplete for {candidate}, fold {fold}, seed {seed}")
    metrics = pd.read_csv(metric_path)
    candidate_rows = metrics.loc[metrics["candidate"].astype(str).eq(candidate)]
    selected = candidate_rows.loc[
        candidate_rows["fold"].astype(int).eq(int(fold))
        & candidate_rows["seed"].astype(int).eq(int(seed))
    ]
    if len(selected) != 1:
        raise RuntimeError(f"expected one original A6 metrics row for {candidate}, fold {fold}, seed {seed}")
    with np.load(prediction_path, allow_pickle=False) as archive:
        arrays = {key: np.asarray(archive[key]) for key in archive.files}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return selected.iloc[0].to_dict(), arrays, {
        "manifest_path": str(manifest_path),
        "manifest_sha256": sha256_file(manifest_path),
        "prediction_path": str(prediction_path),
        "prediction_sha256": sha256_file(prediction_path),
        "original_runtime_seconds_total": float(manifest.get("runtime_seconds_total", math.nan)),
        "original_manifest": manifest,
    }


def prediction_metrics_from_record(record: dict[str, Any]) -> dict[str, float]:
    return {name: float(record[name]) for name in A6.REQUIRED_METRICS if name in record and pd.notna(record[name])}


def save_a3_baseline(fold: Any, data: Any, fold_root: Path, frozen_output: Path) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    fold_root.mkdir(parents=True, exist_ok=True)
    metric_path = fold_root / "a3_metrics.json"
    prediction_path = fold_root / "a3_predictions.npz"
    if metric_path.exists() and prediction_path.exists():
        record = json.loads(metric_path.read_text(encoding="utf-8"))
        if sha256_file(prediction_path) != record.get("prediction_sha256"):
            raise RuntimeError("existing A3 baseline prediction checksum failed; refusing to overwrite")
        with np.load(prediction_path, allow_pickle=False) as archive:
            arrays = {key: np.asarray(archive[key]) for key in archive.files}
        if record.get("input_sha256") == data.hashes:
            return record["record"], arrays
        raise RuntimeError("existing A3 fold baseline has incompatible inputs; refusing to overwrite")
    frozen = A5.load_frozen_a3_predictions(frozen_output, fold.fold, data.counts, fold.validation_times)
    raw_validation = data.a3[np.asarray(fold.validation_times, dtype=np.int64)].reshape(-1, 34)
    precise_x = A5.apply_frozen_scaling(
        raw_validation,
        fold.scaling,
        A5.AUG.BASE_FEATURES + A5.AUG.ADDED_FEATURES,
    )
    precise_predictions = A5.AUG.predict(fold.a3_state, precise_x)
    reproduced = (
        fold.counts[np.asarray(fold.validation_times, dtype=np.int64)].reshape(-1).astype(np.int64),
        *precise_predictions,
    )
    for name, expected, observed in zip(("y", "p", "conditional", "mu"), (frozen[k] for k in ("y", "p", "conditional", "mu")), reproduced):
        if name == "y":
            if not np.array_equal(expected, observed):
                raise RuntimeError("frozen A3 validation labels do not align with A6-OPT fold rows")
        elif not np.allclose(expected, observed, rtol=0, atol=1e-9):
            raise RuntimeError(f"frozen A3 {name} reproduction failed for fold {fold.fold}")
    y, p, conditional, mu = (np.asarray(frozen[key]) for key in ("y", "p", "conditional", "mu"))
    train_prev = float(np.mean(fold.counts[fold.train_times] > 0))
    record, arrays = A5.fold_prediction_record(
        "A3", fold.fold, None, fold.validation_times, None, y, p, conditional, mu, train_prev,
        {"converged": True, "a3_fit": "frozen_A3", "reproduced_max_abs": {"p": float(np.max(np.abs(p - reproduced[1]))), "conditional": float(np.max(np.abs(conditional - reproduced[2]))), "mu": float(np.max(np.abs(mu - reproduced[3])))}}
    )
    write_npz_atomic(prediction_path, arrays)
    write_json_atomic(metric_path, {"record": record, "input_sha256": dict(data.hashes), "prediction_sha256": sha256_file(prediction_path)})
    return record, arrays


def validate_outer_fold(fold: Any) -> None:
    train = np.asarray(fold.train_times, dtype=np.int64)
    validation = np.asarray(fold.validation_times, dtype=np.int64)
    if len(train) == 0 or len(validation) == 0 or not set(train).isdisjoint(set(validation)):
        raise RuntimeError("outer training and validation weeks overlap or are empty")
    if int(train.max()) >= int(validation.min()):
        raise RuntimeError("outer validation includes a week at or before the training cutoff")


def find_completed_seed(
    seed_root: Path,
    seed: int,
    config: dict[str, Any],
    data: Any,
    training_node_ids: np.ndarray | None = None,
    prediction_node_ids: np.ndarray | None = None,
) -> dict[str, Any] | None:
    if not seed_root.exists():
        return None
    for attempt_dir in sorted(seed_root.glob("attempt_*")):
        manifest_path = attempt_dir / "completion.json"
        if not manifest_path.exists():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("status") != "COMPLETED":
            continue
        if manifest.get("seed") != int(seed):
            continue
        if manifest.get("input_sha256") != data.hashes or manifest.get("config_sha256") != config["a6_opt_provenance"]["opt_config_sha256"] or manifest.get("source_sha256") != config["a6_opt_provenance"]["source_sha256"]:
            continue
        if training_node_ids is not None and manifest.get("training_node_ids_sha256") != sha256_json(np.asarray(training_node_ids, dtype=np.int64).tolist()):
            continue
        if prediction_node_ids is not None and manifest.get("prediction_node_ids_sha256") != sha256_json(np.asarray(prediction_node_ids, dtype=np.int64).tolist()):
            continue
        for rel, digest in manifest["checksums"].items():
            path = attempt_dir / rel
            if not path.exists() or sha256_file(path) != digest:
                raise RuntimeError(f"completed seed artifact checksum failed: {path}")
        return manifest
    return None


def next_seed_attempt(seed_root: Path) -> Path:
    seed_root.mkdir(parents=True, exist_ok=True)
    return next_attempt_dir(seed_root)


def fit_seed(
    gpb: Any,
    data: Any,
    fold: Any,
    fold_root: Path,
    fold_id: int,
    seed: int,
    coords_xy: np.ndarray,
    config: dict[str, Any],
    data_hashes: dict[str, str],
    inner_cov: dict[str, Any],
    outer_cov: dict[str, Any],
    seed_count: int,
    train_nodes: np.ndarray | None = None,
    prediction_nodes: np.ndarray | None = None,
    unit_scope: str = "primary_temporal_oof",
) -> tuple[dict[str, Any], dict[str, np.ndarray], dict[str, Any]]:
    seed_root = fold_root / "seeds" / f"seed_{seed}"
    train_nodes = np.arange(A6.NODE_COUNT, dtype=np.int64) if train_nodes is None else np.asarray(train_nodes, dtype=np.int64)
    prediction_nodes = np.arange(A6.NODE_COUNT, dtype=np.int64) if prediction_nodes is None else np.asarray(prediction_nodes, dtype=np.int64)
    existing = find_completed_seed(seed_root, seed, config, data, train_nodes, prediction_nodes)
    if existing is not None:
        prediction_path = Path(existing["artifact_paths"]["prediction"])
        with np.load(prediction_path, allow_pickle=False) as archive:
            arrays = {key: np.asarray(archive[key]) for key in archive.files}
        return existing["record"], arrays, existing

    attempt_dir = next_seed_attempt(seed_root)
    write_json_atomic(attempt_dir / "status.json", {"status": "RUNNING", "seed": int(seed), "fold": int(fold_id), "started_utc": utc_now()})
    started_total = time.perf_counter()
    before_total = runtime_snapshot()
    try:
        evaluation_mask = np.zeros(A6.NODE_COUNT, dtype=bool)
        evaluation_mask[prediction_nodes] = True
        inner_train, inner_monitor = A5.inner_split(
            fold.train_times,
            config["boosting"]["inner_monitor_fraction"],
            config["boosting"]["inner_monitor_min_weeks"],
        )
        if set(inner_train) & set(inner_monitor) or not set(inner_train).issubset(set(fold.train_times)) or not set(inner_monitor).issubset(set(fold.train_times)):
            raise RuntimeError("inner early-stopping split is not contained in the outer training partition")
        x_inner, y_inner, _, offset_inner, coords_inner = flatten_training(fold, inner_train, train_nodes, coords_xy)
        x_monitor, y_monitor, _, offset_monitor, coords_monitor = flatten_training(fold, inner_monitor, train_nodes, coords_xy)
        inner_booster, inner_gp, inner_info = fixed_covariance_train(
            gpb, config, seed, x_inner, y_inner, offset_inner, coords_inner,
            config["boosting"]["maximum_boosting_rounds"], inner_cov["covariance_parameters"],
            (x_monitor, y_monitor, offset_monitor, coords_monitor), True,
        )
        selected_rounds = int(inner_info["selected_rounds"])
        if selected_rounds < 1 or selected_rounds > int(config["boosting"]["maximum_boosting_rounds"]):
            raise A6OptBlocked(f"invalid inner-selected boosting rounds: {selected_rounds}")
        inner_info["inner_train_week_indices"] = np.asarray(inner_train, dtype=np.int64).tolist()
        inner_info["inner_monitor_week_indices"] = np.asarray(inner_monitor, dtype=np.int64).tolist()
        inner_info["outer_validation_used"] = False
        del inner_booster, inner_gp

        x_train, y_train, _, offset_train, coords_train = flatten_training(fold, fold.train_times, train_nodes, coords_xy)
        if len(y_train) != len(fold.train_times) * len(train_nodes):
            raise RuntimeError("Stage B did not receive the complete outer training dataset")
        if set(np.unique(coords_train[:, 0].astype(np.int64))) - set(np.asarray(fold.train_times, dtype=np.int64)):
            raise RuntimeError("outer validation or future weeks entered Stage B coordinates")
        final_booster, final_gp, final_info = fixed_covariance_train(
            gpb, config, seed, x_train, y_train, offset_train, coords_train,
            selected_rounds, outer_cov["covariance_parameters"],
        )
        train_prevalence = float(np.mean(y_train))

        predict_started = time.perf_counter()
        x_eval, y_eval, _, offset_eval, coords_eval = flatten_training(fold, fold.validation_times, prediction_nodes, coords_xy)
        final_gp.set_prediction_data(
            vecchia_pred_type=config["gpboost"]["vecchia_pred_type"],
            num_neighbors_pred=int(config["gpboost"]["num_neighbors_pred"]),
            gp_coords_pred=coords_eval,
        )
        first = final_booster.predict(
            x_eval,
            gp_coords_pred=coords_eval,
            offset_pred=offset_eval,
            num_iteration=selected_rounds,
        )
        second = final_booster.predict(
            x_eval,
            gp_coords_pred=coords_eval,
            offset_pred=offset_eval,
            num_iteration=selected_rounds,
        )
        predict_seconds = time.perf_counter() - predict_started
        if not isinstance(first, dict) or "response_mean" not in first or not isinstance(second, dict) or "response_mean" not in second:
            raise A6OptBlocked("GPBoost prediction did not return response_mean with the A3 offset")
        probability = np.asarray(first["response_mean"], dtype=np.float64)
        repeat_probability = np.asarray(second["response_mean"], dtype=np.float64)
        repeat_difference = float(np.max(np.abs(probability - repeat_probability))) if len(probability) else 0.0
        tolerance = float(config["prediction_repeatability"]["absolute_tolerance"])
        repeatability = bool(np.allclose(probability, repeat_probability, rtol=0, atol=tolerance))
        if not repeatability:
            raise A6OptBlocked(f"label-free prediction repeatability failed: max_abs_difference={repeat_difference}, tolerance={tolerance}")
        if probability.shape != y_eval.shape or not np.isfinite(probability).all() or np.any(probability < -1e-12) or np.any(probability > 1 + 1e-12):
            raise A6OptBlocked("A6-OPT returned invalid validation probabilities")
        probability = np.clip(probability, 0.0, 1.0)

        y_a3, p_a3, conditional_a3, mu_a3 = A5.numpy_a3_predictions(fold, fold.validation_times, evaluation_mask)
        if not np.array_equal(y_a3, y_eval):
            raise RuntimeError("prediction node mask and validation labels are not aligned")
        train_prevalence = float(np.mean(fold.counts[np.asarray(fold.train_times)[:, None], train_nodes] > 0))
        record, arrays = A5.fold_prediction_record(
            OPT_CANDIDATE,
            fold_id,
            seed,
            fold.validation_times,
            evaluation_mask,
            y_eval,
            probability,
            conditional_a3,
            mu_a3,
            train_prevalence,
            {
                "converged": bool(inner_info["covariance_fixed_verified"] and final_info["covariance_fixed_verified"]),
                "selected_rounds": selected_rounds,
                "gpboost_version": gpb.__version__,
                "num_neighbors": 8,
                "num_neighbors_pred": 40,
                "covariance_parameters": outer_cov["covariance_parameters"],
                "covariance_fixed_verified": bool(final_info["covariance_fixed_verified"]),
            },
        )
        record.update({
            "stage_a_inner_runtime_seconds": float(inner_cov["runtime"]["wall_seconds"]),
            "stage_a_outer_runtime_seconds": float(outer_cov["runtime"]["wall_seconds"]),
            "stage_b_inner_round_selection_seconds": float(inner_info["runtime_seconds"]),
            "stage_b_full_training_seconds": float(final_info["runtime_seconds"]),
            "prediction_runtime_seconds": float(predict_seconds),
            "observations_covariance_inner": int(inner_cov["observations_used"]),
            "observations_covariance_outer": int(outer_cov["observations_used"]),
            "observations_boosting": int(len(y_train)),
            "prediction_repeatability_max_abs_difference": repeat_difference,
            "outer_validation_labels_supplied_to_prediction": False,
            "outer_validation_used_for_round_selection": False,
            "training_offset": "frozen_A3_logit_offset_init_score",
            "prediction_offset": "frozen_A3_logit_offset_pred",
            "coordinate_order": ["time_week_offset", "x_km", "y_km"],
            "spatial_support_audit": support_audit(data, fold, coords_xy, coords_eval, train_nodes),
            "unit_scope": unit_scope,
            "training_node_count": int(len(train_nodes)),
            "evaluation_node_count": int(len(prediction_nodes)),
        })

        booster_path = attempt_dir / "a6_opt.booster.txt"
        gp_path = attempt_dir / "a6_opt.gpmodel.json"
        prediction_path = attempt_dir / "predictions.npz"
        final_booster.save_model(str(booster_path))
        final_gp.save_model(str(gp_path))
        write_npz_atomic(prediction_path, arrays)
        for artifact in (booster_path, gp_path, prediction_path):
            if not artifact.exists() or artifact.stat().st_size <= 0:
                raise A6OptBlocked(f"completed model/prediction artifact is empty: {artifact}")
        elapsed_total = time.perf_counter() - started_total
        after_total = runtime_snapshot()
        stage_b_cpu_seconds = max(0.0, after_total["cpu_seconds"] - before_total["cpu_seconds"])
        stage_a_shared_runtime = float(inner_cov["runtime"]["wall_seconds"] + outer_cov["runtime"]["wall_seconds"])
        stage_a_shared_cpu = float(inner_cov["runtime"]["cpu_seconds"] + outer_cov["runtime"]["cpu_seconds"])
        seed_count = max(1, int(seed_count))
        record["stage_b_runtime_seconds_total"] = float(elapsed_total)
        record["stage_a_shared_runtime_seconds_total"] = stage_a_shared_runtime
        record["stage_a_allocated_runtime_seconds"] = stage_a_shared_runtime / seed_count
        record["runtime_seconds_total"] = float(elapsed_total + stage_a_shared_runtime / seed_count)
        record["stage_b_cpu_seconds"] = stage_b_cpu_seconds
        record["stage_a_allocated_cpu_seconds"] = stage_a_shared_cpu / seed_count
        record["cpu_seconds_total"] = stage_b_cpu_seconds + stage_a_shared_cpu / seed_count
        record["peak_rss_bytes_process"] = after_total["peak_rss_bytes"]
        record["allocated_cpus"] = thread_count()
        record["cpu_utilization_fraction"] = float(record["cpu_seconds_total"] / max(record["runtime_seconds_total"] * thread_count(), 1e-9))
        record["stage_b_covariance_parameter_changes"] = final_info["covariance_parameter_differences"]
        record["stage_b_covariance_train_flag"] = False
        write_json_atomic(attempt_dir / "metrics.json", record)
        checksums = {
            "a6_opt.booster.txt": sha256_file(booster_path),
            "a6_opt.gpmodel.json": sha256_file(gp_path),
            "predictions.npz": sha256_file(prediction_path),
            "metrics.json": sha256_file(attempt_dir / "metrics.json"),
        }
        completion = {
            "status": "COMPLETED",
            "candidate": OPT_CANDIDATE,
            "fold": int(fold_id),
            "seed": int(seed),
            "attempt": attempt_dir.name,
            "record": record,
            "artifact_paths": {"booster": str(booster_path), "gp_model": str(gp_path), "prediction": str(prediction_path)},
            "checksums": checksums,
            "input_sha256": data_hashes,
            "config_sha256": config["a6_opt_provenance"]["opt_config_sha256"],
            "source_sha256": config["a6_opt_provenance"]["source_sha256"],
            "inner_covariance_sha256": inner_cov["estimate_sha256"],
            "outer_covariance_sha256": outer_cov["estimate_sha256"],
            "training_node_ids_sha256": sha256_json(train_nodes.tolist()),
            "prediction_node_ids_sha256": sha256_json(prediction_nodes.tolist()),
            "completed_utc": utc_now(),
            "execution_sha": os.environ.get("STGNN_GIT_SHA", "unknown"),
            "execution_branch": os.environ.get("STGNN_GIT_BRANCH", "unknown"),
        }
        write_json_atomic(attempt_dir / "completion.json", completion)
        write_json_atomic(attempt_dir / "status.json", {"status": "COMPLETED", "completion_path": str(attempt_dir / "completion.json"), "completed_utc": utc_now()})
        del final_booster, final_gp
        return record, arrays, completion
    except Exception as exc:
        write_json_atomic(attempt_dir / "failure.json", {"status": "FAILED", "fold": int(fold_id), "seed": int(seed), "error": str(exc), "traceback": traceback.format_exc(), "failed_utc": utc_now()})
        write_json_atomic(attempt_dir / "status.json", {"status": "FAILED", "fold": int(fold_id), "seed": int(seed), "error": str(exc), "failed_utc": utc_now()})
        raise


def prepare_fold(args: argparse.Namespace, data: Any, fold_id: int, frozen_output: Path) -> tuple[Any, dict[str, Any], dict[str, np.ndarray]]:
    fold_record = next((item for item in A6.FOLDS if int(item["fold"]) == int(fold_id)), None)
    if fold_record is None:
        raise ValueError(f"unknown A6 temporal fold {fold_id}")
    fold = A5.prepare_temporal_fold(data, fold_record, frozen_output)
    validate_outer_fold(fold)
    fold_root = args.output_root / "folds" / f"fold_{fold_id:02d}"
    a3_record, a3_arrays = save_a3_baseline(fold, data, fold_root, frozen_output)
    return fold, a3_record, a3_arrays


def run_fold(args: argparse.Namespace, config: dict[str, Any], opt: dict[str, Any], data: Any, gpb: Any, fold_id: int, seeds: list[int], mode: str) -> dict[str, Any]:
    if any(seed not in config["seeds"] for seed in seeds):
        raise ValueError(f"A6-OPT seed not in original A6 seed set: {seeds}")
    fold_root = args.output_root / "folds" / f"fold_{fold_id:02d}"
    with fold_lock(fold_root / ".fold.lock"):
        fold, a3_record, a3_arrays = prepare_fold(args, data, fold_id, args.a3_frozen_output)
        coords_xy = A6.node_coordinates(data)
        train_times = np.asarray(fold.train_times, dtype=np.int64)
        inner_train, inner_monitor = A5.inner_split(
            train_times,
            config["boosting"]["inner_monitor_fraction"],
            config["boosting"]["inner_monitor_min_weeks"],
        )
        if set(inner_train) & set(inner_monitor) or not set(inner_train).issubset(set(train_times)) or not set(inner_monitor).issubset(set(train_times)):
            raise RuntimeError("inner early-stopping split violates outer training boundaries")
        all_nodes = np.arange(A6.NODE_COUNT, dtype=np.int64)
        inner_cov = estimate_covariance(gpb, fold, inner_train, all_nodes, coords_xy, fold_root, data, config, fold_id, "inner_round_selection", thread_count())
        outer_cov = estimate_covariance(gpb, fold, train_times, all_nodes, coords_xy, fold_root, data, config, fold_id, "outer_final_fit", thread_count())
        results: list[dict[str, Any]] = []
        statuses: list[dict[str, Any]] = []
        for seed in seeds:
            record, arrays, completion = fit_seed(gpb, data, fold, fold_root, fold_id, int(seed), coords_xy, config, data.hashes, inner_cov, outer_cov, len(seeds))
            results.append(record)
            statuses.append({"seed": int(seed), "status": completion["status"], "attempt": completion.get("attempt")})
        metrics_path = fold_root / "fold_seed_metrics.csv"
        requested_frame = pd.DataFrame(results)
        if metrics_path.exists():
            old = pd.read_csv(metrics_path)
            old_keys = set(zip(old["fold"].astype(int), old["seed"].astype(int)))
            new_keys = set(zip(requested_frame["fold"].astype(int), requested_frame["seed"].astype(int)))
            if old_keys != new_keys:
                raise RuntimeError(f"existing completed fold metrics differ in seed coverage: {metrics_path}")
            old_metrics = old.sort_values(["fold", "seed"]).reset_index(drop=True)
            new_metrics = requested_frame.sort_values(["fold", "seed"]).reset_index(drop=True)
            for metric in A6.REQUIRED_METRICS:
                if metric in old_metrics and not np.allclose(old_metrics[metric], new_metrics[metric], rtol=0, atol=1e-12, equal_nan=True):
                    raise RuntimeError(f"existing completed fold metrics changed for {metric}: {metrics_path}")
        else:
            write_csv_atomic(metrics_path, requested_frame)
        status = {
            "status": "COMPLETED",
            "mode": mode,
            "fold": int(fold_id),
            "seed_status": statuses,
            "inner_covariance_attempt": inner_cov["attempt_directory"],
            "outer_covariance_attempt": outer_cov["attempt_directory"],
            "covariance_reused": {"inner": bool(inner_cov.get("reused")), "outer": bool(outer_cov.get("reused"))},
            "input_sha256": dict(data.hashes),
            "config_sha256": config["a6_opt_provenance"]["opt_config_sha256"],
            "source_sha256": config["a6_opt_provenance"]["source_sha256"],
            "execution_sha": os.environ.get("STGNN_GIT_SHA", "unknown"),
            "completed_utc": utc_now(),
        }
        fold_status_path = fold_root / "fold_status.json"
        if fold_status_path.exists():
            old_status = json.loads(fold_status_path.read_text(encoding="utf-8"))
            if old_status.get("status") != "COMPLETED" or old_status.get("input_sha256") != status["input_sha256"] or old_status.get("config_sha256") != status["config_sha256"] or old_status.get("source_sha256") != status["source_sha256"]:
                raise RuntimeError(f"existing completed fold status conflicts with this run: {fold_status_path}")
        else:
            write_json_atomic(fold_status_path, status)
        return {"status": "COMPLETED", "fold": fold_id, "metrics": results, "a3_record": a3_record, "a3_arrays": a3_arrays, "inner_covariance": inner_cov, "outer_covariance": outer_cov}


def require_primary_spatial_authorization(output_root: Path) -> dict[str, Any]:
    decision_path = output_root / "results/a6_opt_decision.json"
    status_path = output_root / "results/aggregate_status.json"
    if not decision_path.exists() or not status_path.exists():
        raise RuntimeError("spatial-stress execution requires completed primary temporal aggregation")
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    aggregate_status = json.loads(status_path.read_text(encoding="utf-8"))
    if aggregate_status.get("status") != "COMPLETED" or not decision.get("primary_guardrails_passed", False):
        raise RuntimeError("spatial-stress execution is not authorized because primary temporal guardrails did not pass")
    return decision


def prepare_spatial_stress_fold(data: Any, spatial_fold: int) -> tuple[Any, np.ndarray, np.ndarray, dict[str, Any], dict[str, np.ndarray]]:
    if data.spatial_assignment is None:
        raise RuntimeError("spatial-stress assignment file was not loaded")
    assignment_frame = data.spatial_assignment
    if "model_node_id" not in assignment_frame or "spatial_fold" not in assignment_frame:
        raise RuntimeError("spatial-stress assignment lacks model_node_id/spatial_fold")
    if not np.array_equal(assignment_frame["model_node_id"].to_numpy(np.int64), np.arange(A6.NODE_COUNT)):
        raise RuntimeError("spatial-stress node assignments are not in canonical node order")
    assignment = assignment_frame["spatial_fold"].to_numpy(np.int64)
    spatial_values = np.unique(assignment)
    if len(spatial_values) < 2 or spatial_fold not in set(spatial_values.tolist()):
        raise RuntimeError(f"unknown spatial-stress fold {spatial_fold}; configured folds are {spatial_values.tolist()}")
    train_nodes = np.flatnonzero(assignment != int(spatial_fold)).astype(np.int64)
    eval_nodes = np.flatnonzero(assignment == int(spatial_fold)).astype(np.int64)
    if len(train_nodes) == 0 or len(eval_nodes) == 0 or np.intersect1d(train_nodes, eval_nodes).size:
        raise RuntimeError("spatial-stress training and evaluation nodes are empty or overlap")
    all_times = np.arange(A6.DEVELOPMENT_WEEKS, dtype=np.int64)
    raw_train = data.a3[:, train_nodes].reshape(-1, 34)
    raw_all = data.a3.reshape(-1, 34)
    y_train_count = data.counts[:, train_nodes].reshape(-1)
    state, (_, x_all_flat), _, scaling = A5.fit_a3_for_rows(
        raw_train, y_train_count, raw_all, A5.AUG.BASE_FEATURES + A5.AUG.ADDED_FEATURES,
    )
    x_all = x_all_flat.reshape(A6.DEVELOPMENT_WEEKS, A6.NODE_COUNT, 34).astype(np.float32)
    design_all = np.concatenate([np.ones((A6.DEVELOPMENT_WEEKS, A6.NODE_COUNT, 1)), x_all.astype(np.float64)], axis=2)
    eta = np.einsum("tnp,p->tn", design_all, state["occurrence_beta"]).astype(np.float32)
    xi = np.einsum("tnp,p->tn", design_all, state["count_beta"]).astype(np.float32)
    fold_id = 100 + int(spatial_fold)
    fold = A5.FoldPrepared(fold_id, all_times, all_times, x_all, data.counts, eta, xi, {**state, "scaling": scaling}, scaling)
    mask = np.zeros(A6.NODE_COUNT, dtype=bool)
    mask[eval_nodes] = True
    train_prevalence = float(np.mean(y_train_count > 0))
    y_eval, p_eval, conditional_eval, mu_eval = A5.numpy_a3_predictions(fold, all_times, mask)
    a3_record, a3_arrays = A5.fold_prediction_record(
        "A3", fold_id, None, all_times, mask, y_eval, p_eval, conditional_eval, mu_eval, train_prevalence,
        {"converged": True, "a3_fit": "refit_on_spatial_training_nodes", "selection_used": False},
    )
    a3_record.update({"spatial_fold": int(spatial_fold), "training_nodes": int(len(train_nodes)), "evaluation_nodes": int(len(eval_nodes)), "unit_scope": "secondary_spatial_stress"})
    return fold, train_nodes, eval_nodes, a3_record, a3_arrays


def run_spatial_fold(args: argparse.Namespace, config: dict[str, Any], data: Any, gpb: Any, spatial_fold: int) -> dict[str, Any]:
    decision = require_primary_spatial_authorization(args.output_root)
    fold_root = args.output_root / "spatial_stress/folds" / f"spatial_fold_{int(spatial_fold):02d}"
    with fold_lock(fold_root / ".fold.lock"):
        fold, train_nodes, eval_nodes, a3_record, a3_arrays = prepare_spatial_stress_fold(data, spatial_fold)
        a3_path = fold_root / "a3_predictions.npz"
        a3_metrics_path = fold_root / "a3_metrics.json"
        if a3_path.exists() or a3_metrics_path.exists():
            if not a3_path.exists() or not a3_metrics_path.exists():
                raise RuntimeError(f"incomplete spatial-stress A3 baseline exists under {fold_root}")
            existing_a3 = json.loads(a3_metrics_path.read_text(encoding="utf-8"))
            if existing_a3.get("prediction_sha256") != sha256_file(a3_path) or existing_a3.get("input_sha256") != data.hashes or existing_a3.get("training_node_ids_sha256") != sha256_json(train_nodes.tolist()):
                raise RuntimeError(f"spatial-stress A3 baseline provenance/checksum conflict under {fold_root}")
            with np.load(a3_path, allow_pickle=False) as archive:
                a3_arrays = {key: np.asarray(archive[key]) for key in archive.files}
            a3_record = existing_a3["record"]
        else:
            write_npz_atomic(a3_path, a3_arrays)
            write_json_atomic(a3_metrics_path, {
                "record": a3_record,
                "input_sha256": dict(data.hashes),
                "training_node_ids_sha256": sha256_json(train_nodes.tolist()),
                "prediction_node_ids_sha256": sha256_json(eval_nodes.tolist()),
                "prediction_sha256": sha256_file(a3_path),
            })

        coords_xy = A6.node_coordinates(data)
        all_times = np.arange(A6.DEVELOPMENT_WEEKS, dtype=np.int64)
        inner_train, inner_monitor = A5.inner_split(
            all_times,
            config["boosting"]["inner_monitor_fraction"],
            config["boosting"]["inner_monitor_min_weeks"],
        )
        if set(inner_train) & set(inner_monitor) or set(inner_train) | set(inner_monitor) != set(all_times):
            raise RuntimeError("spatial-stress round-selection split is invalid")
        inner_cov = estimate_covariance(gpb, fold, inner_train, train_nodes, coords_xy, fold_root, data, config, 100 + spatial_fold, "inner_round_selection", thread_count())
        outer_cov = estimate_covariance(gpb, fold, all_times, train_nodes, coords_xy, fold_root, data, config, 100 + spatial_fold, "outer_final_fit", thread_count())
        results: list[dict[str, Any]] = []
        for seed in config["seeds"]:
            record, _, _ = fit_seed(
                gpb, data, fold, fold_root, 100 + int(spatial_fold), int(seed), coords_xy,
                config, data.hashes, inner_cov, outer_cov, len(config["seeds"]),
                train_nodes=train_nodes, prediction_nodes=eval_nodes,
                unit_scope="secondary_spatial_stress",
            )
            record.update({"spatial_fold": int(spatial_fold), "training_nodes": int(len(train_nodes)), "evaluation_nodes": int(len(eval_nodes))})
            results.append(record)
        metrics_path = fold_root / "spatial_fold_metrics.csv"
        requested = pd.DataFrame([a3_record, *results])
        if metrics_path.exists():
            existing = pd.read_csv(metrics_path)
            old_keys = set(zip(existing["candidate"].astype(str), existing["seed"].fillna(-1).astype(int)))
            new_keys = set(zip(requested["candidate"].astype(str), requested["seed"].fillna(-1).astype(int)))
            if old_keys != new_keys:
                raise RuntimeError(f"existing spatial-stress metrics have conflicting seed coverage: {metrics_path}")
        else:
            write_csv_atomic(metrics_path, requested)
        status = {
            "status": "COMPLETED", "spatial_fold": int(spatial_fold), "fold_id": int(100 + spatial_fold),
            "seed_ids": [int(seed) for seed in config["seeds"]], "selection_used": False, "a4s_refit": False,
            "primary_decision": decision["status"], "training_nodes": int(len(train_nodes)), "evaluation_nodes": int(len(eval_nodes)),
            "training_node_ids_sha256": sha256_json(train_nodes.tolist()), "prediction_node_ids_sha256": sha256_json(eval_nodes.tolist()),
            "input_sha256": dict(data.hashes), "config_sha256": config["a6_opt_provenance"]["opt_config_sha256"],
            "source_sha256": config["a6_opt_provenance"]["source_sha256"], "completed_utc": utc_now(),
        }
        status_path = fold_root / "fold_status.json"
        if status_path.exists():
            prior = json.loads(status_path.read_text(encoding="utf-8"))
            if prior.get("status") != "COMPLETED" or prior.get("input_sha256") != status["input_sha256"] or prior.get("training_node_ids_sha256") != status["training_node_ids_sha256"]:
                raise RuntimeError(f"existing spatial-stress fold status conflicts: {status_path}")
        else:
            write_json_atomic(status_path, status)
        return status


def support_audit(data: Any, fold: Any, coords_xy: np.ndarray, coords_pred: np.ndarray, training_node_ids: np.ndarray | None = None) -> dict[str, Any]:
    train_nodes = np.arange(len(coords_xy), dtype=np.int64) if training_node_ids is None else np.asarray(training_node_ids, dtype=np.int64)
    train_xy = coords_xy[train_nodes]
    eval_xy = coords_pred[:, 1:]
    xmin, ymin = train_xy.min(axis=0)
    xmax, ymax = train_xy.max(axis=0)
    inside = (eval_xy[:, 0] >= xmin) & (eval_xy[:, 0] <= xmax) & (eval_xy[:, 1] >= ymin) & (eval_xy[:, 1] <= ymax)
    times = coords_pred[:, 0].astype(np.int64)
    return {
        "training_node_count": int(len(train_xy)),
        "prediction_row_count": int(len(coords_pred)),
        "prediction_spatial_fraction_within_training_extent": float(np.mean(inside)),
        "training_xy_min": [float(xmin), float(ymin)],
        "training_xy_max": [float(xmax), float(ymax)],
        "prediction_week_min": int(times.min()),
        "prediction_week_max": int(times.max()),
        "last_training_week": int(np.max(fold.train_times)),
        "temporal_extrapolation_weeks": [int(times.min() - np.max(fold.train_times)), int(times.max() - np.max(fold.train_times))],
        "queen_adjacency_used_for_gp": False,
        "gp_coordinates_from_canonical_projected_node_xy": True,
        "future_or_same_week_outcomes_used_as_predictors": False,
    }


def compare_gate(
    args: argparse.Namespace,
    config: dict[str, Any],
    data: Any,
    fold_id: int,
    seed: int,
    fit_record: dict[str, Any],
    opt_arrays: dict[str, np.ndarray],
    a3_record: dict[str, Any],
    a3_arrays: dict[str, np.ndarray],
    covariance: dict[str, Any],
) -> dict[str, Any]:
    original_root = args.original_a6_run_root
    original_metrics, original_arrays, original_provenance = get_original_a6_row(original_root, "A6-GPB-ST", fold_id, seed)
    for key in ("y", "week_index", "node_id"):
        if key not in original_arrays or key not in opt_arrays or not np.array_equal(original_arrays[key], opt_arrays[key]):
            raise RuntimeError(f"original A6 and A6-OPT fold rows do not align for {key}")
    spatial = A5.spatial_diagnostics(
        {"A3": a3_arrays, "A6-GPB-ST": original_arrays, OPT_CANDIDATE: opt_arrays},
        data, config, args.output_root,
    )
    temporal = A5.temporal_diagnostics({"A3": a3_arrays, "A6-GPB-ST": original_arrays, OPT_CANDIDATE: opt_arrays}, args.output_root)
    frontier = A5.frontier_diagnostics({"A3": a3_arrays, "A6-GPB-ST": original_arrays, OPT_CANDIDATE: opt_arrays}, data, args.output_root)
    leakage = A6.run_leakage_tests(config, data, args.output_root)
    shell_one = spatial.loc[spatial["residual"].eq("occurrence") & spatial["shell"].eq(1)].set_index("candidate")["moran_i"].to_dict()
    guard = config["guardrails"]
    gate = config["a6_opt"]["gate"]
    pr_a3_diff = float(fit_record["pr_auc"] - a3_record["pr_auc"])
    brier_a3_diff = float(fit_record["brier_skill"] - a3_record["brier_skill"])
    nll_a3_diff = float(fit_record["joint_hurdle_nll"] - a3_record["joint_hurdle_nll"])
    intercept_a3_worsening = abs(abs(float(fit_record["calibration_intercept"])) - abs(float(a3_record["calibration_intercept"])))
    slope_a3_worsening = abs(abs(float(fit_record["calibration_slope"])) - abs(float(a3_record["calibration_slope"])))
    pr_original_diff = float(fit_record["pr_auc"] - original_metrics["pr_auc"])
    brier_original_diff = float(fit_record["brier_skill"] - original_metrics["brier_skill"])
    nll_original_diff = float(fit_record["joint_hurdle_nll"] - original_metrics["joint_hurdle_nll"])
    original_runtime = float(original_provenance["original_runtime_seconds_total"])
    opt_runtime = float(fit_record["runtime_seconds_total"])
    speedup = original_runtime / opt_runtime if math.isfinite(original_runtime) and opt_runtime > 0 else float("nan")
    moran_reduction = float(shell_one["A3"] - shell_one[OPT_CANDIDATE])
    moran_worsening_vs_original = float(shell_one[OPT_CANDIDATE] - shell_one["A6-GPB-ST"])
    checks = {
        "stage_a_covariance_converged_and_valid": bool(covariance["covariance_diagnostics"]["converged"] and covariance["covariance_diagnostics"]["non_degenerate"]),
        "stage_b_covariance_fixed": bool(fit_record["covariance_fixed_verified"] and all(abs(value) <= 1e-10 for value in fit_record["stage_b_covariance_parameter_changes"].values())),
        "prediction_repeatability": bool(fit_record["prediction_repeatability_max_abs_difference"] <= config["prediction_repeatability"]["absolute_tolerance"]),
        "a3_offset_and_34_predictor_contract": bool(fit_record["training_offset"] == "frozen_A3_logit_offset_init_score" and fit_record["prediction_offset"] == "frozen_A3_logit_offset_pred" and fit_record["observations_boosting"] > 0),
        "outer_validation_not_used_for_fit_or_round_selection": bool(not fit_record["outer_validation_labels_supplied_to_prediction"] and not fit_record["outer_validation_used_for_round_selection"]),
        "outer_fold_leakage_contract": bool(leakage.get("status") == "PASSED"),
        "spatial_temporal_prediction_support": bool(fit_record["spatial_support_audit"]["prediction_spatial_fraction_within_training_extent"] == 1.0 and min(fit_record["spatial_support_audit"]["temporal_extrapolation_weeks"]) >= 1),
        "canonical_coordinate_order": bool(fit_record["coordinate_order"] == ["time_week_offset", "x_km", "y_km"] and not fit_record["spatial_support_audit"]["queen_adjacency_used_for_gp"]),
        "minimum_twofold_runtime_reduction": bool(speedup >= float(gate["minimum_speedup_vs_original_a6"])),
        "pr_auc_guardrail_vs_a3": bool(pr_a3_diff >= -float(gate["maximum_pr_auc_degradation_vs_a3"]))
        and bool(pr_original_diff >= -float(gate["maximum_pr_auc_degradation_vs_a3"])),
        "brier_skill_guardrail": bool(brier_a3_diff >= -float(gate["maximum_brier_skill_degradation_vs_a3"]))
        and bool(brier_original_diff >= -float(gate["maximum_brier_skill_degradation_vs_a3"])),
        "joint_hurdle_nll_guardrail": bool(nll_a3_diff <= float(gate["maximum_joint_hurdle_nll_worsening_vs_a3"]))
        and bool(nll_original_diff <= float(gate["maximum_joint_hurdle_nll_worsening_vs_a3"])),
        "calibration_guardrails_vs_a3": bool(intercept_a3_worsening <= float(gate["maximum_calibration_intercept_worsening_vs_a3"]) and slope_a3_worsening <= float(gate["maximum_calibration_slope_worsening_vs_a3"])),
        "shell1_occurrence_moran_reduction_vs_a3": bool(moran_reduction >= float(gate["minimum_shell1_occurrence_moran_reduction_vs_a3"])),
        "shell1_occurrence_moran_not_degraded_vs_original_a6": bool(moran_worsening_vs_original <= float(gate["maximum_shell1_occurrence_moran_worsening_vs_original_a6"])),
    }
    supported = all(checks.values())
    decision = "A6_OPT_GATE_SUPPORTED_WITH_LIMITATIONS" if supported else "A6_OPT_GATE_NOT_SUPPORTED"
    payload = {
        "status": decision,
        "fold": int(fold_id),
        "seed": int(seed),
        "created_utc": utc_now(),
        "checks": checks,
        "comparison": {
            "predictive_metrics_a3": prediction_metrics_from_record(a3_record),
            "predictive_metrics_original_a6": prediction_metrics_from_record(original_metrics),
            "predictive_metrics_a6_opt": prediction_metrics_from_record(fit_record),
            "differences_vs_a3": {"pr_auc": pr_a3_diff, "brier_skill": brier_a3_diff, "joint_hurdle_nll": nll_a3_diff, "calibration_intercept_worsening": intercept_a3_worsening, "calibration_slope_worsening": slope_a3_worsening},
            "differences_vs_original_a6": {"pr_auc": pr_original_diff, "brier_skill": brier_original_diff, "joint_hurdle_nll": nll_original_diff},
            "spatial_shell1_occurrence_moran": {name: float(shell_one[name]) for name in ("A3", "A6-GPB-ST", OPT_CANDIDATE)},
            "shell1_moran_reduction_vs_a3": moran_reduction,
            "shell1_moran_worsening_vs_original_a6": moran_worsening_vs_original,
            "covariance_parameters": covariance["covariance_parameters"],
            "original_a6_runtime_seconds": original_runtime,
            "a6_opt_gate_runtime_seconds": opt_runtime,
            "speedup": speedup,
            "runtime_components_seconds": {
                "stage_a_inner_covariance": float(fit_record["stage_a_inner_runtime_seconds"]),
                "stage_a_outer_covariance": float(fit_record["stage_a_outer_runtime_seconds"]),
                "stage_b_inner_round_selection": float(fit_record["stage_b_inner_round_selection_seconds"]),
                "stage_b_full_training": float(fit_record["stage_b_full_training_seconds"]),
                "prediction": float(fit_record["prediction_runtime_seconds"]),
            },
            "original_a6_artifacts": original_provenance,
            "frontier_rows": int(len(frontier)),
            "temporal_residual_rows": int(len(temporal)),
        },
        "limitations": [
            "The qualification uses one outer fold and one seed.",
            "Stage A covariance estimates use the deterministic 2,048-site subset specified in the A6-OPT config.",
            "A successful gate permits, but does not automatically launch, the complete temporal evaluation.",
        ],
        "execution_sha": os.environ.get("STGNN_GIT_SHA", "unknown"),
        "config_sha256": config["a6_opt_provenance"]["opt_config_sha256"],
    }
    write_csv_atomic(args.output_root / "results/a6_opt_gate_metrics.csv", pd.DataFrame([
        {"candidate": "A3", "fold": fold_id, "seed": seed, **prediction_metrics_from_record(a3_record)},
        {"candidate": "A6-GPB-ST", "fold": fold_id, "seed": seed, **prediction_metrics_from_record(original_metrics)},
        {"candidate": OPT_CANDIDATE, "fold": fold_id, "seed": seed, **prediction_metrics_from_record(fit_record)},
    ]))
    report_path = args.durable_summary_root / f"a6_opt_gate_report_{args.output_root.name}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = [
        "# A6-OPT bounded qualification gate", "",
        f"**Gate decision:** `{decision}`", "",
        f"Fold {fold_id}, seed {seed}; original A6 comparator: fold {fold_id}, seed {seed}.",
        f"Measured speedup: **{speedup:.2f}×** ({original_runtime / 3600:.2f} original hours / {opt_runtime / 3600:.2f} A6-OPT hours).",
        f"Training data: {fit_record['observations_boosting']:,} full Stage B rows; covariance subsets {covariance['observations_used']:,} outer and {fit_record['observations_covariance_inner']:,} inner rows.",
        "", "## Gate checks", "", "| Check | Result |", "|---|---:|",
    ]
    report.extend(f"| {name.replace('_', ' ')} | {'PASS' if passed else 'FAIL'} |" for name, passed in checks.items())
    report.extend([
        "", "## Predictive and spatial comparison", "",
        "| Metric | Frozen A3 | Original A6 | A6-OPT |", "|---|---:|---:|---:|",
    ])
    for metric in ("pr_auc", "brier_skill", "calibration_intercept", "calibration_slope", "joint_hurdle_nll"):
        report.append(f"| {metric} | {float(a3_record[metric]):.6g} | {float(original_metrics[metric]):.6g} | {float(fit_record[metric]):.6g} |")
    report.extend([
        "", f"Shell 1 occurrence Moran's I: A3 {shell_one['A3']:.6g}; original A6 {shell_one['A6-GPB-ST']:.6g}; A6-OPT {shell_one[OPT_CANDIDATE]:.6g}.",
        "", "## Runtime components", "", "| Component | Seconds |", "|---|---:|",
    ])
    report.extend(f"| {name.replace('_', ' ')} | {seconds:.2f} |" for name, seconds in payload["comparison"]["runtime_components_seconds"].items())
    report.extend([
        "", "## Interpretation", "",
        "This gate uses one temporal fold and seed. A supported result is a qualification to run the prespecified four-fold temporal evaluation; it is not a final scientific decision or production promotion. The gate used the frozen A3 occurrence offset, the unchanged 34 predictors, Matérn space-time GP, eight training neighbors, and explicit 40-neighbor prediction setting.",
        "",
    ])
    report_path.write_text("\n".join(report), encoding="utf-8")
    write_json_atomic(args.output_root / "results/a6_opt_gate_decision.json", payload)
    return payload


def run_gate(args: argparse.Namespace, config: dict[str, Any], opt: dict[str, Any], data: Any, gpb: Any, fold_id: int, seed: int) -> dict[str, Any]:
    existing_decision_path = args.output_root / "results/a6_opt_gate_decision.json"
    if existing_decision_path.exists():
        existing = json.loads(existing_decision_path.read_text(encoding="utf-8"))
        if existing.get("status") in {"A6_OPT_GATE_SUPPORTED", "A6_OPT_GATE_SUPPORTED_WITH_LIMITATIONS", "A6_OPT_GATE_NOT_SUPPORTED"}:
            return existing
    try:
        result = run_fold(args, config, opt, data, gpb, fold_id, [seed], "gate")
        fold_root = args.output_root / "folds" / f"fold_{fold_id:02d}"
        seed_complete = find_completed_seed(fold_root / "seeds" / f"seed_{seed}", seed, config, data)
        if seed_complete is None:
            raise RuntimeError("gate fit completion marker is missing")
        opt_arrays = result["a3_arrays"]
        with np.load(seed_complete["artifact_paths"]["prediction"], allow_pickle=False) as archive:
            opt_arrays = {key: np.asarray(archive[key]) for key in archive.files}
        a3_record = result["a3_record"]
        a3_arrays = result["a3_arrays"]
        outer_cov = result["outer_covariance"]
        gate = compare_gate(args, config, data, fold_id, seed, seed_complete["record"], opt_arrays, a3_record, a3_arrays, outer_cov)
        write_json_atomic(args.output_root / "results/run_status.json", {"status": gate["status"], "completed_utc": utc_now(), "fold": fold_id, "seed": seed})
        return gate
    except Exception as exc:
        if existing_decision_path.exists():
            existing = json.loads(existing_decision_path.read_text(encoding="utf-8"))
            if existing.get("status") in {"A6_OPT_GATE_SUPPORTED", "A6_OPT_GATE_SUPPORTED_WITH_LIMITATIONS", "A6_OPT_GATE_NOT_SUPPORTED"}:
                return existing
        decision = {
            "status": "A6_OPT_GATE_NOT_SUPPORTED",
            "fold": int(fold_id),
            "seed": int(seed),
            "reason": str(exc),
            "traceback": traceback.format_exc(),
            "created_utc": utc_now(),
            "execution_sha": os.environ.get("STGNN_GIT_SHA", "unknown"),
            "config_sha256": config["a6_opt_provenance"]["opt_config_sha256"],
        }
        write_json_atomic(args.output_root / "results/a6_opt_gate_decision.json", decision)
        report_path = args.durable_summary_root / f"a6_opt_gate_report_{args.output_root.name}.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            "# A6-OPT bounded qualification gate\n\n"
            "**Gate decision:** `A6_OPT_GATE_NOT_SUPPORTED`\n\n"
            f"Fold {fold_id}, seed {seed}.\n\n"
            f"Observed blocker: {exc}\n\n"
            "The gate stopped at this failure. No additional optimization experiment or full temporal evaluation was launched.\n",
            encoding="utf-8",
        )
        write_json_atomic(args.output_root / "results/run_status.json", {"status": decision["status"], "reason": str(exc), "completed_utc": utc_now()})
        return decision


def completed_covariance_estimate(fold_root: Path, stage_name: str) -> dict[str, Any]:
    stage_root = fold_root / "covariance" / stage_name
    if not stage_root.exists():
        raise RuntimeError(f"missing Stage A covariance folder: {stage_root}")
    for attempt_dir in sorted(stage_root.glob("attempt_*"), reverse=True):
        marker_path = attempt_dir / "completion.json"
        estimate_path = attempt_dir / "stage_a_estimate.json"
        if not marker_path.exists():
            continue
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        if marker.get("status") != "COMPLETED":
            continue
        if not estimate_path.exists() or sha256_file(estimate_path) != marker.get("estimate_sha256"):
            raise RuntimeError(f"completed covariance checksum failed: {estimate_path}")
        result = json.loads(estimate_path.read_text(encoding="utf-8"))
        result["attempt_directory"] = str(attempt_dir)
        result["estimate_sha256"] = marker["estimate_sha256"]
        result["reused"] = True
        return result
    raise RuntimeError(f"no completed Stage A covariance estimate in {stage_root}")


def mean_prediction_arrays(arrays: list[dict[str, np.ndarray]]) -> dict[str, np.ndarray]:
    if not arrays:
        raise RuntimeError("cannot aggregate an empty prediction list")
    first = arrays[0]
    for other in arrays[1:]:
        for key in ("y", "week_index", "node_id", "fold"):
            if key in first and (key not in other or not np.array_equal(first[key], other[key])):
                raise RuntimeError(f"prediction rows differ across seeds for {key}")
    result = {key: np.asarray(first[key]).copy() for key in first}
    for key in ("p", "conditional", "mu"):
        result[key] = np.mean([np.asarray(item[key], dtype=np.float64) for item in arrays], axis=0)
    return result


def concatenate_prediction_arrays(arrays: list[dict[str, np.ndarray]]) -> dict[str, np.ndarray]:
    if not arrays:
        raise RuntimeError("cannot concatenate an empty prediction list")
    keys = set(arrays[0])
    if any(set(item) != keys for item in arrays[1:]):
        raise RuntimeError("prediction archives have different array keys")
    return {key: np.concatenate([np.asarray(item[key]) for item in arrays], axis=0) for key in arrays[0]}


def write_diagnostics_svg(path: Path, mean_metrics: pd.DataFrame, spatial: pd.DataFrame) -> None:
    candidates = ["A3", "A6-GB-IID", "A6-GPB-ST", OPT_CANDIDATE]
    palette = {"A3": "#65758b", "A6-GB-IID": "#d17c26", "A6-GPB-ST": "#277da1", OPT_CANDIDATE: "#6a4c93"}
    means = mean_metrics.set_index("candidate")
    plot_candidates = [name for name in candidates if name in means.index]
    shell = spatial.loc[spatial["residual"].eq("occurrence")].groupby(["candidate", "shell"], as_index=False)["moran_i"].mean()
    width, height = 1000, 440
    left_x, right_x = 80, 545
    top_y, bottom_y = 74, 365
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
             '<rect width="100%" height="100%" fill="#ffffff"/>',
             '<style>text{font-family:Arial,sans-serif;fill:#243244}.axis{stroke:#8793a1;stroke-width:1}.grid{stroke:#e4e8ed;stroke-width:1}.label{font-size:12px}.title{font-size:18px;font-weight:700}.small{font-size:11px}</style>',
             '<text x="80" y="34" class="title">A6-OPT temporal evaluation</text>',
             '<text x="80" y="58" class="label">Mean precision-recall AUC across folds/seeds</text>',
             '<text x="545" y="58" class="label">Occurrence residual Moran’s I by queen shell</text>']
    pr_values = {name: float(means.loc[name, "pr_auc"]) for name in plot_candidates}
    max_pr = max(0.05, max(pr_values.values(), default=0.1) * 1.08)
    for tick in range(5):
        y = bottom_y - (bottom_y - top_y) * tick / 4
        val = max_pr * tick / 4
        parts.append(f'<line x1="{left_x}" y1="{y:.1f}" x2="{left_x+390}" y2="{y:.1f}" class="grid"/>')
        parts.append(f'<text x="{left_x-10}" y="{y+4:.1f}" text-anchor="end" class="small">{val:.2f}</text>')
    parts.extend([f'<line x1="{left_x}" y1="{top_y}" x2="{left_x}" y2="{bottom_y}" class="axis"/>',
                  f'<line x1="{left_x}" y1="{bottom_y}" x2="{left_x+390}" y2="{bottom_y}" class="axis"/>'])
    slot = 390 / max(1, len(plot_candidates))
    for idx, name in enumerate(plot_candidates):
        val = pr_values[name]
        bar_h = (bottom_y - top_y) * val / max_pr
        x = left_x + idx * slot + slot * 0.24
        y = bottom_y - bar_h
        parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{slot*0.52:.1f}" height="{bar_h:.1f}" rx="3" fill="{palette[name]}"/>')
        parts.append(f'<text x="{x+slot*0.26:.1f}" y="{y-7:.1f}" text-anchor="middle" class="small">{val:.3f}</text>')
        parts.append(f'<text x="{x+slot*0.26:.1f}" y="{bottom_y+22}" text-anchor="middle" class="small">{name}</text>')
    moran_values = shell["moran_i"].astype(float).to_numpy()
    low = min(-0.05, float(moran_values.min()) - 0.02) if len(moran_values) else -0.05
    high = max(0.1, float(moran_values.max()) + 0.02) if len(moran_values) else 0.1
    for tick in range(5):
        y = bottom_y - (bottom_y - top_y) * tick / 4
        val = low + (high - low) * tick / 4
        parts.append(f'<line x1="{right_x}" y1="{y:.1f}" x2="{right_x+390}" y2="{y:.1f}" class="grid"/>')
        parts.append(f'<text x="{right_x-10}" y="{y+4:.1f}" text-anchor="end" class="small">{val:.2f}</text>')
    parts.extend([f'<line x1="{right_x}" y1="{top_y}" x2="{right_x}" y2="{bottom_y}" class="axis"/>',
                  f'<line x1="{right_x}" y1="{bottom_y}" x2="{right_x+390}" y2="{bottom_y}" class="axis"/>'])
    for name in plot_candidates:
        subset = shell.loc[shell["candidate"].eq(name)].sort_values("shell")
        points = []
        for _, row in subset.iterrows():
            x = right_x + 30 + (int(row["shell"]) - 1) * 105
            y = bottom_y - (float(row["moran_i"]) - low) / (high - low) * (bottom_y - top_y)
            points.append((x, y))
        if points:
            point_text = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
            parts.append(f'<polyline points="{point_text}" fill="none" stroke="{palette[name]}" stroke-width="3"/>')
            for x, y in points:
                parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{palette[name]}"/>')
        legend_y = 395 + (candidates.index(name) % 2) * 18
        legend_x = right_x + (candidates.index(name) // 2) * 170
        parts.append(f'<line x1="{legend_x}" y1="{legend_y}" x2="{legend_x+22}" y2="{legend_y}" stroke="{palette[name]}" stroke-width="3"/>')
        parts.append(f'<text x="{legend_x+28}" y="{legend_y+4}" class="small">{name}</text>')
    parts.extend(['<text x="275" y="423" text-anchor="middle" class="small">Candidate</text>',
                  '<text x="740" y="423" text-anchor="middle" class="small">Queen-contiguity shell</text>',
                  '</svg>'])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(parts), encoding="utf-8")


def aggregate_primary(args: argparse.Namespace, config: dict[str, Any], data: Any) -> dict[str, Any]:
    decision_path = args.output_root / "results/a6_opt_decision.json"
    aggregate_status_path = args.output_root / "results/aggregate_status.json"
    if decision_path.exists():
        existing = json.loads(decision_path.read_text(encoding="utf-8"))
        if aggregate_status_path.exists() and json.loads(aggregate_status_path.read_text(encoding="utf-8")).get("status") == "COMPLETED":
            return existing
        raise RuntimeError(f"an incomplete aggregation already has a decision artifact; preserve it and use a new run root: {decision_path}")

    seed_ids = [int(seed) for seed in config["seeds"]]
    metrics_rows: list[dict[str, Any]] = []
    diagnostics_arrays: dict[str, list[dict[str, np.ndarray]]] = {"A3": [], "A6-GB-IID": [], "A6-GPB-ST": [], OPT_CANDIDATE: []}
    covariance_rows: list[dict[str, Any]] = []
    support_rows: list[dict[str, Any]] = []
    coords_xy = A6.node_coordinates(data)
    for fold_record in A6.FOLDS:
        fold_id = int(fold_record["fold"])
        fold_root = args.output_root / "folds" / f"fold_{fold_id:02d}"
        status_path = fold_root / "fold_status.json"
        if not status_path.exists() or json.loads(status_path.read_text(encoding="utf-8")).get("status") != "COMPLETED":
            raise RuntimeError(f"A6-OPT temporal fold {fold_id} has no completed fold status")
        if not (fold_root / "a3_metrics.json").exists() or not (fold_root / "a3_predictions.npz").exists():
            raise RuntimeError(f"A3 fold baseline missing for fold {fold_id}")
        a3_payload = json.loads((fold_root / "a3_metrics.json").read_text(encoding="utf-8"))
        if sha256_file(fold_root / "a3_predictions.npz") != a3_payload.get("prediction_sha256"):
            raise RuntimeError(f"A3 prediction checksum failed for fold {fold_id}")
        a3_record = a3_payload["record"]
        with np.load(fold_root / "a3_predictions.npz", allow_pickle=False) as archive:
            a3_arrays = {key: np.asarray(archive[key]) for key in archive.files}
        diagnostics_arrays["A3"].append(a3_arrays)
        metrics_rows.append(a3_record)

        inner_estimate = completed_covariance_estimate(fold_root, "inner_round_selection")
        outer_estimate = completed_covariance_estimate(fold_root, "outer_final_fit")
        for estimate in (inner_estimate, outer_estimate):
            covariance_rows.append({
                "fold": fold_id,
                "stage": estimate["stage"],
                "observations_used": int(estimate["observations_used"]),
                "full_partition_observations": int(estimate["full_partition_observations"]),
                "runtime_seconds": float(estimate["runtime"]["wall_seconds"]),
                "cpu_seconds": float(estimate["runtime"]["cpu_seconds"]),
                "peak_rss_bytes_process": float(estimate["runtime"]["peak_rss_bytes_process"]),
                "converged": bool(estimate["covariance_diagnostics"]["converged"]),
                "covariance_non_degenerate": bool(estimate["covariance_diagnostics"]["non_degenerate"]),
                "covariance_parameters": estimate["covariance_parameters"],
                "estimate_sha256": estimate["estimate_sha256"],
            })

        a6_original_arrays_by_type: dict[str, list[dict[str, np.ndarray]]] = {"A6-GB-IID": [], "A6-GPB-ST": []}
        opt_arrays: list[dict[str, np.ndarray]] = []
        for seed in seed_ids:
            completed = find_completed_seed(fold_root / "seeds" / f"seed_{seed}", seed, config, data)
            if completed is None:
                raise RuntimeError(f"A6-OPT seed is incomplete: fold {fold_id}, seed {seed}")
            metrics_rows.append(completed["record"])
            with np.load(completed["artifact_paths"]["prediction"], allow_pickle=False) as archive:
                opt_arrays.append({key: np.asarray(archive[key]) for key in archive.files})
            for candidate in ("A6-GB-IID", "A6-GPB-ST"):
                original_metrics, original_arrays, _ = get_original_a6_row(args.original_a6_run_root, candidate, fold_id, seed)
                for key in ("y", "week_index", "node_id"):
                    if key not in original_arrays or not np.array_equal(original_arrays[key], a3_arrays[key]):
                        raise RuntimeError(f"original A6 {candidate} rows differ from the frozen A3 fold for {key}")
                metrics_rows.append(original_metrics)
                a6_original_arrays_by_type[candidate].append(original_arrays)
        for candidate, candidate_arrays in a6_original_arrays_by_type.items():
            diagnostics_arrays[candidate].append(mean_prediction_arrays(candidate_arrays))
        diagnostics_arrays[OPT_CANDIDATE].append(mean_prediction_arrays(opt_arrays))

        fold = A5.prepare_temporal_fold(data, next(item for item in A6.FOLDS if int(item["fold"]) == fold_id), args.a3_frozen_output)
        coords_pred = A6.build_coords(coords_xy, fold.validation_times, np.arange(A6.NODE_COUNT, dtype=np.int64), True)
        support = support_audit(data, fold, coords_xy, coords_pred)
        support["fold"] = fold_id
        support["validation_start"] = fold_record["validation_start"]
        support["validation_end"] = fold_record["validation_end"]
        support_rows.append(support)

    metric_frame = pd.DataFrame(metrics_rows)
    write_csv_atomic(args.output_root / "results/fold_seed_metrics.csv", metric_frame)
    candidate_metric_rows = []
    for candidate, group in metric_frame.groupby("candidate"):
        metrics = [name for name in A6.REQUIRED_METRICS if name in group]
        candidate_metric_rows.append({"candidate": candidate, "aggregation": "mean_fold_seed", "n_rows": int(len(group)), **{name: float(group[name].mean()) for name in metrics}})
        if candidate != "A3":
            for fold_id, fold_group in group.groupby("fold"):
                candidate_metric_rows.append({"candidate": candidate, "aggregation": "fold_mean", "fold": int(fold_id), "n_rows": int(len(fold_group)), **{name: float(fold_group[name].mean()) for name in metrics}})
    mean_metrics = pd.DataFrame(candidate_metric_rows)
    write_csv_atomic(args.output_root / "results/aggregate_metrics.csv", mean_metrics)
    covariance_frame_out = pd.DataFrame(covariance_rows)
    write_csv_atomic(args.output_root / "results/covariance_parameters.csv", covariance_frame_out)
    write_csv_atomic(args.output_root / "results/spatial_support_assessment.csv", pd.DataFrame(support_rows))

    combined_predictions = {name: concatenate_prediction_arrays(items) for name, items in diagnostics_arrays.items()}
    spatial = A5.spatial_diagnostics(combined_predictions, data, config, args.output_root)
    temporal = A5.temporal_diagnostics(combined_predictions, args.output_root)
    frontier = A5.frontier_diagnostics(combined_predictions, data, args.output_root)
    leakage = A6.run_leakage_tests(config, data, args.output_root)
    spatial_means = spatial.groupby(["candidate", "residual", "shell"], as_index=False)["moran_i"].mean()
    occurrence = spatial_means.loc[spatial_means["residual"].eq("occurrence")]
    a3_shell = occurrence.loc[occurrence["candidate"].eq("A3")].set_index("shell")["moran_i"]
    opt_shell = occurrence.loc[occurrence["candidate"].eq(OPT_CANDIDATE)].set_index("shell")["moran_i"]
    iid_shell = occurrence.loc[occurrence["candidate"].eq("A6-GB-IID")].set_index("shell")["moran_i"]
    opt_rows = metric_frame.loc[metric_frame["candidate"].eq(OPT_CANDIDATE)]
    a3_rows = metric_frame.loc[metric_frame["candidate"].eq("A3")]
    original_st_rows = metric_frame.loc[metric_frame["candidate"].eq("A6-GPB-ST")]
    guard = config["guardrails"]
    a3_mean = {name: float(a3_rows[name].mean()) for name in A6.REQUIRED_METRICS}
    opt_mean = {name: float(opt_rows[name].mean()) for name in A6.REQUIRED_METRICS}
    opt_fold_pr = opt_rows.groupby("fold")["pr_auc"].mean()
    a3_fold_pr = a3_rows.groupby("fold")["pr_auc"].mean()
    pr_fold_worst = float(opt_fold_pr.min() - a3_fold_pr.min())
    calibration_intercept_worsening = abs(abs(opt_mean["calibration_intercept"]) - abs(a3_mean["calibration_intercept"]))
    calibration_slope_worsening = abs(abs(opt_mean["calibration_slope"]) - abs(a3_mean["calibration_slope"]))
    shell_reductions = {str(shell_id): float(a3_shell.loc[shell_id] - opt_shell.loc[shell_id]) for shell_id in (1, 2, 3, 4)}
    outer_shell_worst_worsening = max(float(opt_shell.loc[shell_id] - a3_shell.loc[shell_id]) for shell_id in (2, 3, 4))
    iid_attribution = float(iid_shell.loc[1] - opt_shell.loc[1])
    seed_sd = float(opt_rows.groupby("seed")["pr_auc"].mean().std(ddof=0))
    cov_ok = bool(not covariance_frame_out.empty and covariance_frame_out["converged"].astype(bool).all() and covariance_frame_out["covariance_non_degenerate"].astype(bool).all())
    predictive_guardrails = {
        "mean_pr_auc": bool(opt_mean["pr_auc"] >= a3_mean["pr_auc"] - guard["mean_pr_auc_degradation"]),
        "mean_brier_skill": bool(opt_mean["brier_skill"] >= a3_mean["brier_skill"] - guard["mean_brier_skill_degradation"]),
        "worst_fold_pr_auc": bool(pr_fold_worst >= -guard["worst_fold_pr_auc_degradation"]),
        "calibration_intercept": bool(calibration_intercept_worsening <= guard["calibration_intercept_worsening"]),
        "calibration_slope": bool(calibration_slope_worsening <= guard["calibration_slope_worsening"]),
        "joint_hurdle_nll": bool(opt_mean["joint_hurdle_nll"] <= a3_mean["joint_hurdle_nll"] + guard["joint_hurdle_nll_worsening"]),
    }
    spatial_guardrails = {
        "shell1_occurrence_reduction_vs_a3": bool(shell_reductions["1"] >= guard["shell1_occurrence_moran_reduction"]),
        "shell2_to_4_not_worse_than_a3": bool(outer_shell_worst_worsening <= guard["outer_shell_moran_worsening"]),
        "shell1_attribution_over_iid": bool(iid_attribution >= guard["shell1_attribution_over_iid"]),
    }
    stability_guardrails = {
        "all_fits_covariance_fixed": bool(opt_rows["covariance_fixed_verified"].astype(bool).all()),
        "all_fits_converged": bool(opt_rows["converged"].astype(bool).all()),
        "all_required_metrics_finite": bool(np.isfinite(opt_rows[A6.REQUIRED_METRICS].to_numpy(dtype=np.float64)).all()),
        "pr_auc_seed_sd_at_most_0_05": bool(seed_sd <= 0.05),
        "covariance_estimates_valid": cov_ok,
        "leakage_contract": leakage.get("status") == "PASSED",
    }
    all_primary_guardrails = bool(all(predictive_guardrails.values()) and all(spatial_guardrails.values()) and all(stability_guardrails.values()))
    decision = "A6_OPT_SUPPORTED_WITH_LIMITATIONS" if all_primary_guardrails else "A6_OPT_NOT_SUPPORTED"
    runtime_opt = float(opt_rows["runtime_seconds_total"].sum())
    runtime_original = float(original_st_rows["runtime_seconds_total"].sum()) if "runtime_seconds_total" in original_st_rows else float("nan")
    speedup = runtime_original / runtime_opt if math.isfinite(runtime_original) and runtime_opt > 0 else float("nan")
    stage_a_total = float(covariance_frame_out["runtime_seconds"].sum())
    stage_a_cpu = float(covariance_frame_out["cpu_seconds"].sum())
    stage_b_cpu = float(opt_rows["stage_b_cpu_seconds"].sum())
    cpu_seconds = stage_a_cpu + stage_b_cpu
    wall_seconds = runtime_opt
    cpus = int(max(opt_rows["allocated_cpus"].max(), 1))
    peak_rss = float(max(covariance_frame_out["peak_rss_bytes_process"].max(), opt_rows["peak_rss_bytes_process"].max()))
    computation = {
        "covariance_observations_total_across_eight_stage_a_fits": int(covariance_frame_out["observations_used"].sum()),
        "boosting_observations_total_across_twelve_stage_b_fits": int(opt_rows["observations_boosting"].sum()),
        "stage_a_covariance_wall_seconds": stage_a_total,
        "stage_a_covariance_cpu_seconds": stage_a_cpu,
        "stage_b_inner_selection_wall_seconds": float(opt_rows["stage_b_inner_round_selection_seconds"].sum()),
        "stage_b_full_training_wall_seconds": float(opt_rows["stage_b_full_training_seconds"].sum()),
        "prediction_wall_seconds": float(opt_rows["prediction_runtime_seconds"].sum()),
        "total_wall_seconds_serial_fit_sum": wall_seconds,
        "total_cpu_seconds": cpu_seconds,
        "total_cpu_hours": cpu_seconds / 3600,
        "mean_cpu_utilization_fraction": float(cpu_seconds / max(wall_seconds * cpus, 1e-9)),
        "peak_rss_bytes": peak_rss,
        "allocated_cpus_per_fold_job": cpus,
        "original_a6_spatiotemporal_runtime_seconds": runtime_original,
        "a6_opt_runtime_seconds": runtime_opt,
        "measured_speedup_vs_original_a6": speedup,
        "vecchia_training_neighbors": 8,
        "vecchia_prediction_neighbors": 40,
        "covariance_estimates_reused_across_three_seeds": True,
        "parallel_array_concurrency": 1,
        "speedup_attribution": "combined_observed_effect_only; no component-specific causal attribution",
        "measurement_limitation": "Slurm CPU and peak-memory summaries are in each fold manifest and scheduler accounting; reported peak is the highest process high-water mark captured by Python resource usage.",
    }
    write_json_atomic(args.output_root / "results/computational_performance.json", computation)
    a3_occ_mean = float(a3_shell.loc[1])
    opt_occ_mean = float(opt_shell.loc[1])
    original_mean = {name: float(original_st_rows[name].mean()) for name in A6.REQUIRED_METRICS}
    evidence = {
        "status": decision,
        "primary_guardrails_passed": all_primary_guardrails,
        "development_classification": "DEVELOPMENT_INFORMED_FOLLOWUP",
        "predictive_guardrails": predictive_guardrails,
        "spatial_guardrails": spatial_guardrails,
        "stability_guardrails": stability_guardrails,
        "mean_metrics": {"A3": a3_mean, "original_A6_GPB_ST": original_mean, "A6_OPT": opt_mean},
        "worst_fold_pr_auc_difference_vs_a3": pr_fold_worst,
        "calibration_intercept_worsening_vs_a3": calibration_intercept_worsening,
        "calibration_slope_worsening_vs_a3": calibration_slope_worsening,
        "occurrence_shell_reductions_vs_a3": shell_reductions,
        "outer_shell_worst_worsening_vs_a3": outer_shell_worst_worsening,
        "shell1_attribution_over_original_a6_iid": iid_attribution,
        "shell1_occurrence_moran": {"A3": a3_occ_mean, "A6-GB-IID": float(iid_shell.loc[1]), "A6-GPB-ST": float(occurrence.loc[occurrence["candidate"].eq("A6-GPB-ST") & occurrence["shell"].eq(1)]["moran_i"].iloc[0]), OPT_CANDIDATE: opt_occ_mean},
        "seed_pr_auc_standard_deviation": seed_sd,
        "covariance_estimates": covariance_rows,
        "computational_performance": computation,
        "spatial_stress_status": "AUTHORIZED_AFTER_PRIMARY_GUARDRAILS_PASS" if all_primary_guardrails else "NOT_RUN_PRIMARY_GUARDRAILS_FAILED",
        "production_promotion": "NOT_AUTHORIZED",
        "a3_artifact_modified": False,
        "a4s_artifact_modified": False,
        "original_a6_artifacts_modified": False,
    }
    write_json_atomic(decision_path, evidence)

    mean_for_figure = mean_metrics.loc[mean_metrics["aggregation"].eq("mean_fold_seed")]
    figure_path = args.output_root / "results/a6_opt_diagnostics.svg"
    write_diagnostics_svg(figure_path, mean_for_figure, spatial_means)
    report_path = args.output_root / "results/final_decision_report.md"
    lines = [
        "# A6-OPT temporal evaluation", "",
        f"**Final primary decision:** `{decision}`", "",
        "A6-OPT is a development-informed challenger. The decision uses the four forward temporal folds, three original seeds, frozen A3 as the benchmark, the original A6 spatiotemporal GPBoost candidate, and the original A6 spatial guardrails.",
        "",
        "## Predictive performance", "",
        "| Candidate | PR AUC | Brier skill | Calibration intercept | Calibration slope | Joint hurdle NLL |", "|---|---:|---:|---:|---:|---:|",
    ]
    for candidate in ("A3", "A6-GB-IID", "A6-GPB-ST", OPT_CANDIDATE):
        row = mean_for_figure.loc[mean_for_figure["candidate"].eq(candidate)]
        if row.empty:
            continue
        item = row.iloc[0]
        lines.append(f"| {candidate} | {item['pr_auc']:.4f} | {item['brier_skill']:.4f} | {item['calibration_intercept']:.4f} | {item['calibration_slope']:.4f} | {item['joint_hurdle_nll']:.4f} |")
    lines.extend(["", "## Spatial residual dependence", "", "| Candidate | Shell 1 Moran’s I | Shell 2 | Shell 3 | Shell 4 |", "|---|---:|---:|---:|---:|"])
    for candidate in ("A3", "A6-GB-IID", "A6-GPB-ST", OPT_CANDIDATE):
        vals = occurrence.loc[occurrence["candidate"].eq(candidate)].set_index("shell")["moran_i"]
        if len(vals):
            lines.append(f"| {candidate} | {vals.get(1, math.nan):.4f} | {vals.get(2, math.nan):.4f} | {vals.get(3, math.nan):.4f} | {vals.get(4, math.nan):.4f} |")
    lines.extend([
        "", "## Primary guardrails", "", "| Guardrail | Result |", "|---|---:|",
    ])
    lines.extend(f"| {section.replace('_', ' ')}: {name.replace('_', ' ')} | {'PASS' if passed else 'FAIL'} |" for section, checks in (("predictive", predictive_guardrails), ("spatial", spatial_guardrails), ("stability", stability_guardrails)) for name, passed in checks.items())
    lines.extend([
        "", "## Computational performance", "",
        f"Measured A6-OPT to original A6 runtime ratio: **{speedup:.2f}×**. Stage A covariance estimation used a deterministic 2,048-site spatial sample across all training weeks. Stage B used all applicable training rows.",
        "",
        f"Stage A wall time: {stage_a_total / 3600:.2f} hours; Stage B inner selection: {computation['stage_b_inner_selection_wall_seconds'] / 3600:.2f} hours; Stage B final training: {computation['stage_b_full_training_wall_seconds'] / 3600:.2f} hours; prediction: {computation['prediction_wall_seconds'] / 3600:.2f} hours.",
        f"Total measured CPU: {computation['total_cpu_hours']:.2f} CPU-hours; peak process RSS: {peak_rss / (1024**3):.2f} GiB; fold array concurrency: 1.",
        "",
        "![A6-OPT predictive and spatial diagnostics](a6_opt_diagnostics.svg)",
        "",
        "The observed runtime difference reflects the combined changes to training-neighbor count, fixed covariance training, deterministic covariance subsampling, and reuse across seeds. These effects were not isolated experimentally, so component-specific speedup attribution is not made.",
        "",
        "## Spatial-stress evaluation", "",
        "The existing spatial-stress framework is eligible to run only because the primary temporal guardrails passed." if all_primary_guardrails else "Spatial-stress evaluation was not run because the primary temporal guardrails failed.",
        "Spatial-stress results remain secondary and do not change candidate selection.",
        "",
        "No production model was promoted. Frozen A3, A4-S, and original A6 source and artifacts remain unchanged.",
        "",
    ])
    report_path.write_text("\n".join(lines), encoding="utf-8")

    compact_rel = [
        "results/fold_seed_metrics.csv", "results/aggregate_metrics.csv", "results/covariance_parameters.csv",
        "results/residual_spatial_summary.csv", "results/residual_spatial_map_data.csv",
        "results/residual_temporal_summary.csv", "results/frontier_metrics.csv",
        "results/spatial_support_assessment.csv", "results/computational_performance.json",
        "results/a6_opt_decision.json", "results/a6_opt_diagnostics.svg", "results/final_decision_report.md",
        "results/spatial_stress_gate.json", "results/leakage_tests.json", "provenance/environment_manifest.json", "provenance/gpboost_api_audit.json",
    ]
    durable_manifest = []
    args.durable_summary_root.mkdir(parents=True, exist_ok=True)
    for rel in compact_rel:
        source = args.output_root / rel
        if not source.exists():
            continue
        destination = args.durable_summary_root / Path(rel).name
        if destination.exists():
            if sha256_file(destination) != sha256_file(source):
                raise RuntimeError(f"durable A6-OPT result exists with a different checksum: {destination}")
        else:
            shutil.copy2(source, destination)
        durable_manifest.append({"path": str(destination), "size_bytes": int(destination.stat().st_size), "sha256": sha256_file(destination)})
    checksum = {
        "status": "COMPLETED",
        "storage_class": "DURABLE_PROJECT_ARTIFACTS",
        "temporary_output_root": str(args.output_root),
        "durable_summary_root": str(args.durable_summary_root),
        "execution_sha": os.environ.get("STGNN_GIT_SHA", "unknown"),
        "files": durable_manifest,
        "large_outputs_retained_under": "/90daydata/disease_ecology/hominivorax-ml/a6_opt_efficient",
    }
    write_json_atomic(args.output_root / "provenance/a6_opt_checksum_manifest.json", checksum)
    if all_primary_guardrails:
        write_json_atomic(args.output_root / "results/spatial_stress_gate.json", {"status": "AUTHORIZED_AFTER_PRIMARY_PASS", "selection_used": False, "primary_decision": decision})
    else:
        write_json_atomic(args.output_root / "results/spatial_stress_gate.json", {"status": "NOT_RUN_PRIMARY_GUARDRAILS_FAILED", "selection_used": False, "primary_decision": decision})
    write_json_atomic(aggregate_status_path, {"status": "COMPLETED", "decision": decision, "config_sha256": config["a6_opt_provenance"]["opt_config_sha256"], "source_sha256": config["a6_opt_provenance"]["source_sha256"], "completed_utc": utc_now()})
    return evidence


def aggregate_spatial_stress(args: argparse.Namespace, config: dict[str, Any], data: Any) -> dict[str, Any]:
    primary = require_primary_spatial_authorization(args.output_root)
    prior_status_path = args.output_root / "results/spatial_stress_status.json"
    if prior_status_path.exists():
        prior_status = json.loads(prior_status_path.read_text(encoding="utf-8"))
        if prior_status.get("status") == "COMPLETED":
            if prior_status.get("primary_decision") != primary.get("status") or prior_status.get("config_sha256") != config["a6_opt_provenance"]["opt_config_sha256"]:
                raise RuntimeError(f"completed spatial-stress status has conflicting provenance: {prior_status_path}")
            return prior_status
    if data.spatial_assignment is None:
        raise RuntimeError("spatial-stress assignment file was not loaded")
    assignment = data.spatial_assignment["spatial_fold"].to_numpy(np.int64)
    spatial_folds = sorted(int(value) for value in np.unique(assignment))
    rows: list[pd.DataFrame] = []
    for spatial_fold in spatial_folds:
        fold_root = args.output_root / "spatial_stress/folds" / f"spatial_fold_{spatial_fold:02d}"
        status_path = fold_root / "fold_status.json"
        metrics_path = fold_root / "spatial_fold_metrics.csv"
        if not status_path.exists() or json.loads(status_path.read_text(encoding="utf-8")).get("status") != "COMPLETED":
            raise RuntimeError(f"spatial-stress fold {spatial_fold} has no completed status")
        if not metrics_path.exists():
            raise RuntimeError(f"spatial-stress metrics are missing for fold {spatial_fold}")
        frame = pd.read_csv(metrics_path)
        if set(frame["candidate"].astype(str)) != {"A3", OPT_CANDIDATE} or len(frame.loc[frame["candidate"].eq(OPT_CANDIDATE)]) != len(config["seeds"]):
            raise RuntimeError(f"spatial-stress fold {spatial_fold} has invalid candidate or seed coverage")
        frame["spatial_fold"] = int(spatial_fold)
        rows.append(frame)

    original_stress_path = args.original_a6_run_root / "results/spatial_stress_metrics.csv"
    original_comparison_available = False
    if original_stress_path.exists():
        original = pd.read_csv(original_stress_path)
        original = original.loc[original["candidate"].astype(str).eq("A6-GPB-ST")].copy()
        if not original.empty:
            original["unit_scope"] = "original_a6_secondary_spatial_stress"
            rows.append(original)
            original_comparison_available = True
    combined = pd.concat(rows, ignore_index=True, sort=False)
    write_csv_atomic(args.output_root / "results/spatial_stress_metrics.csv", combined)
    metric_columns = [name for name in A6.REQUIRED_METRICS if name in combined]
    summary_rows: list[dict[str, Any]] = []
    for candidate, group in combined.groupby("candidate", dropna=False):
        summary_rows.append({
            "candidate": candidate,
            "aggregation": "mean_spatial_fold_seed",
            "n_rows": int(len(group)),
            **{name: float(group[name].mean()) for name in metric_columns},
        })
        if "spatial_fold" in group:
            for spatial_fold, fold_group in group.groupby("spatial_fold"):
                summary_rows.append({
                    "candidate": candidate,
                    "aggregation": "spatial_fold_mean",
                    "spatial_fold": int(spatial_fold),
                    "n_rows": int(len(fold_group)),
                    **{name: float(fold_group[name].mean()) for name in metric_columns},
                })
    summary = pd.DataFrame(summary_rows)
    write_csv_atomic(args.output_root / "results/spatial_stress_summary.csv", summary)
    report_path = args.output_root / "results/spatial_stress_report.md"
    mean_rows = summary.loc[summary["aggregation"].eq("mean_spatial_fold_seed")]
    report = [
        "# A6-OPT secondary spatial-stress evaluation", "",
        f"**Status:** `COMPLETED`; primary decision: `{primary['status']}`.", "",
        f"The existing deterministic spatial assignment was used across {len(spatial_folds)} held-out spatial folds. A3 was refit on the training nodes within each fold; A6-OPT used those fold-specific A3 occurrence offsets, all 34 predictors, and only training-node outcomes. Selection used: false. A4-S refit: false.", "",
        f"Original A6 spatial-stress comparison included: {str(original_comparison_available).lower()}.", "",
        "| Candidate | Mean PR AUC | Mean Brier skill | Mean calibration intercept | Mean calibration slope | Mean joint hurdle NLL |", "|---|---:|---:|---:|---:|---:|",
    ]
    for _, row in mean_rows.iterrows():
        report.append(f"| {row['candidate']} | {row.get('pr_auc', math.nan):.4f} | {row.get('brier_skill', math.nan):.4f} | {row.get('calibration_intercept', math.nan):.4f} | {row.get('calibration_slope', math.nan):.4f} | {row.get('joint_hurdle_nll', math.nan):.4f} |")
    report.extend(["", "Spatial-stress outcomes are secondary and were not used to select or alter A6-OPT. These results do not change the primary temporal decision.", ""])
    report_path.write_text("\n".join(report), encoding="utf-8")
    status = {
        "status": "COMPLETED",
        "spatial_fold_count": len(spatial_folds),
        "spatial_folds": spatial_folds,
        "selection_used": False,
        "a4s_refit": False,
        "candidate_scope": sorted(combined["candidate"].dropna().astype(str).unique().tolist()),
        "original_a6_spatial_stress_comparison_available": original_comparison_available,
        "original_a6_spatial_stress_path": str(original_stress_path),
        "original_a6_spatial_stress_sha256": sha256_file(original_stress_path) if original_comparison_available else None,
        "primary_decision": primary["status"],
        "config_sha256": config["a6_opt_provenance"]["opt_config_sha256"],
        "source_sha256": config["a6_opt_provenance"]["source_sha256"],
        "completed_utc": utc_now(),
    }
    status_path = args.output_root / "results/spatial_stress_status.json"
    write_json_atomic(status_path, status)
    durable_files = []
    args.durable_summary_root.mkdir(parents=True, exist_ok=True)
    for source in (args.output_root / "results/spatial_stress_metrics.csv", args.output_root / "results/spatial_stress_summary.csv", report_path, status_path):
        destination = args.durable_summary_root / source.name
        if destination.exists():
            if sha256_file(destination) != sha256_file(source):
                raise RuntimeError(f"durable spatial-stress artifact exists with different content: {destination}")
        else:
            shutil.copy2(source, destination)
        durable_files.append({"path": str(destination), "size_bytes": int(destination.stat().st_size), "sha256": sha256_file(destination)})
    write_json_atomic(args.output_root / "provenance/spatial_stress_checksum_manifest.json", {
        "status": "COMPLETED", "selection_used": False, "primary_decision": primary["status"],
        "temporary_output_root": str(args.output_root), "durable_summary_root": str(args.durable_summary_root),
        "execution_sha": os.environ.get("STGNN_GIT_SHA", "unknown"), "files": durable_files,
    })
    checksum_path = args.output_root / "provenance/spatial_stress_checksum_manifest.json"
    checksum_destination = args.durable_summary_root / checksum_path.name
    if checksum_destination.exists():
        if sha256_file(checksum_destination) != sha256_file(checksum_path):
            raise RuntimeError(f"durable spatial-stress checksum manifest differs: {checksum_destination}")
    else:
        shutil.copy2(checksum_path, checksum_destination)
    return status


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["gate", "fold", "aggregate", "spatial-fold", "spatial-aggregate"], required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--model-output", type=Path, required=True)
    parser.add_argument("--front-features", type=Path, required=True)
    parser.add_argument("--anthropogenic-features", type=Path, required=True)
    parser.add_argument("--soil-features", type=Path, required=True)
    parser.add_argument("--edges", type=Path, required=True)
    parser.add_argument("--a3-reference", type=Path, required=True)
    parser.add_argument("--a3-frozen-output", type=Path, required=True)
    parser.add_argument("--spatial-assignments", type=Path)
    parser.add_argument("--original-a6-run-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--durable-summary-root", type=Path, default=REPOSITORY_ROOT / "analysis/a6_opt_efficient/results")
    parser.add_argument("--fold", type=int)
    parser.add_argument("--spatial-fold-index", type=int)
    parser.add_argument("--seeds", type=int, nargs="+")
    return parser


def main() -> int:
    args = create_parser().parse_args()
    config, opt = read_config(args.config)
    args.output_root = resolve_output_root(args.output_root)
    args.original_a6_run_root = args.original_a6_run_root.expanduser().resolve()
    args.durable_summary_root = args.durable_summary_root.expanduser().resolve() / args.output_root.name
    source_sha256 = source_checksums(args.config)
    config["a6_opt_provenance"]["source_sha256"] = source_sha256
    for name in ("results", "provenance", "folds", "logs", "spatial_stress"):
        (args.output_root / name).mkdir(parents=True, exist_ok=True)
    gpb = load_gpboost()
    api = audit_gpboost_api(gpb, args.output_root)
    data = load_data(args)
    environment = {
        "status": "PASSED",
        "gpboost_version": gpb.__version__,
        "python": sys.version,
        "executable": sys.executable,
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "slurm_cpus_per_task": int(os.environ.get("SLURM_CPUS_PER_TASK", thread_count())),
        "input_sha256": dict(data.hashes),
        "config_provenance": config["a6_opt_provenance"],
        "source_sha256": source_sha256,
        "api_audit": api,
        "created_utc": utc_now(),
    }
    environment_path = args.output_root / "provenance/environment_manifest.json"
    if not environment_path.exists():
        write_json_atomic(environment_path, environment)
    else:
        prior_environment = json.loads(environment_path.read_text(encoding="utf-8"))
        for key in ("gpboost_version", "input_sha256", "config_provenance", "api_audit"):
            if prior_environment.get(key) != environment.get(key):
                raise RuntimeError(f"existing environment provenance changed in {key}: {environment_path}")
        if prior_environment.get("status") != "PASSED":
            raise RuntimeError(f"existing environment provenance is not PASSED: {environment_path}")
    if args.mode == "gate":
        if args.fold is None or args.seeds is None or len(args.seeds) != 1:
            raise ValueError("gate mode requires --fold and exactly one --seeds value")
        result = run_gate(args, config, opt, data, gpb, args.fold, args.seeds[0])
        print(json.dumps({"status": result["status"], "fold": args.fold, "seed": args.seeds[0]}, indent=2))
        return 0
    if args.mode == "fold":
        if args.fold is None or not args.seeds:
            raise ValueError("fold mode requires --fold and --seeds")
        result = run_fold(args, config, opt, data, gpb, args.fold, args.seeds, "temporal")
        print(json.dumps({"status": result["status"], "fold": args.fold, "seeds": args.seeds}, indent=2))
        return 0
    if args.mode == "aggregate":
        result = aggregate_primary(args, config, data)
        print(json.dumps({"status": result["status"], "primary_guardrails_passed": result["primary_guardrails_passed"]}, indent=2))
        return 0
    if args.mode == "spatial-fold":
        if args.spatial_fold_index is None or data.spatial_assignment is None:
            raise ValueError("spatial-fold mode requires --spatial-fold-index and spatial assignments")
        spatial_values = sorted(int(value) for value in data.spatial_assignment["spatial_fold"].unique())
        if args.spatial_fold_index < 0 or args.spatial_fold_index >= len(spatial_values):
            raise ValueError(f"spatial-fold index {args.spatial_fold_index} is outside 0..{len(spatial_values) - 1}")
        spatial_fold = spatial_values[args.spatial_fold_index]
        result = run_spatial_fold(args, config, data, gpb, spatial_fold)
        print(json.dumps(result, indent=2))
        return 0
    if args.mode == "spatial-aggregate":
        result = aggregate_spatial_stress(args, config, data)
        print(json.dumps(result, indent=2))
        return 0
    raise AssertionError(f"unsupported mode {args.mode}")


if __name__ == "__main__":
    raise SystemExit(main())
